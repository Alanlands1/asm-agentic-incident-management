"""Phoenix tracing: no-op when disabled, one span per request and one per LLM call when enabled."""

import anthropic
import httpx
import httpx2
import pytest
from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http import trace_exporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import telemetry
from app.core.config import settings
from app.core.middleware import RequestLoggingMiddleware


@pytest.fixture(autouse=True)
def reset_telemetry():
    yield
    telemetry.shutdown_telemetry()


def test_setup_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "PHOENIX_ENABLED", False)
    telemetry.setup_telemetry(FastAPI())
    assert telemetry._provider is None


async def test_request_produces_span_when_enabled(monkeypatch):
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(settings, "PHOENIX_ENABLED", True)
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", lambda endpoint: exporter)

    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    telemetry.setup_telemetry(app)
    assert telemetry._provider is not None

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ping", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 200

    telemetry.shutdown_telemetry()
    spans = exporter.get_finished_spans()
    ping_spans = [s for s in spans if "/ping" in s.name]
    assert ping_spans, f"no span for /ping in {[s.name for s in spans]}"
    assert any(s.attributes.get("http.request_id") == "req-123" for s in ping_spans)
    assert telemetry._provider is None


def test_llm_call_produces_span_when_enabled(monkeypatch):
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(settings, "PHOENIX_ENABLED", True)
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", lambda endpoint: exporter)

    def fake_api(request: httpx2.Request) -> httpx2.Response:
        body = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }
        return httpx2.Response(200, json=body)

    client = anthropic.Anthropic(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(fake_api)))

    telemetry.setup_telemetry(FastAPI())
    assert telemetry._provider is not None

    client.messages.create(model="claude-test", max_tokens=16, messages=[{"role": "user", "content": "hello"}])

    telemetry.shutdown_telemetry()
    llm_spans = [s for s in exporter.get_finished_spans() if s.attributes.get("openinference.span.kind") == "LLM"]
    assert llm_spans, f"no LLM span in {[s.name for s in exporter.get_finished_spans()]}"
    assert llm_spans[0].attributes.get("llm.model_name") == "claude-test"
