"""OpenTelemetry request and LLM call tracing, exported to Arize Phoenix when PHOENIX_ENABLED is set.

Request spans carry only HTTP metadata (method, route, status, latency). LLM spans carry the prompt and response sent to
the model. Prompts hold ticket text already redacted by Masker, and responses hold placeholders, so raw PII stays out
of the collector.
"""

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.core.config import settings

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger("app.telemetry")

_provider: "TracerProvider | None" = None


def setup_telemetry(app: FastAPI) -> None:
    """Instrument the app and export its request spans to Phoenix. Never raises: tracing must not stop startup."""
    global _provider
    if not settings.PHOENIX_ENABLED or _provider is not None:
        return
    try:
        from openinference.instrumentation.anthropic import AnthropicInstrumentor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({
            "service.name": settings.PHOENIX_PROJECT_NAME,
            "openinference.project.name": settings.PHOENIX_PROJECT_NAME,
        })
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.PHOENIX_COLLECTOR_ENDPOINT)))
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls="health")
        AnthropicInstrumentor().instrument(tracer_provider=provider)
        _provider = provider
        logger.info(f"Phoenix tracing enabled: {settings.PHOENIX_COLLECTOR_ENDPOINT}")
    except Exception:
        logger.warning("Phoenix tracing could not be set up; continuing without it", exc_info=True)


def shutdown_telemetry() -> None:
    """Flush pending spans and stop the exporter."""
    global _provider
    if _provider is None:
        return
    try:
        from openinference.instrumentation.anthropic import AnthropicInstrumentor

        AnthropicInstrumentor().uninstrument()
        _provider.shutdown()
    finally:
        _provider = None
