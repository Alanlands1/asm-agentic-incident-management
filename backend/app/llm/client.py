"""One structured model call: masked text in, schema-validated object out. Every agent calls the model through here.

The provider is chosen by settings (LLM_PROVIDER), so moving from the Claude API to the client's own route
(for example Bedrock in a Canadian region) is a config change, not a code change.
"""

import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.config import config_version, settings
from app.privacy.masking import MaskedText, Masker

logger = logging.getLogger("app.llm")

# Facts about the provider APIs, not choices: they change only when the API does.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"  # Claude API server-side refusal fallback
BEDROCK_MODEL_PREFIX = "anthropic."  # Bedrock model ids are the Claude id with this prefix


class ModelError(RuntimeError):
    """Base class: the model gave no usable answer. Callers leave the ticket where it was."""


class ModelDisabledError(ModelError):
    """LLM_ENABLED is false (the kill switch)."""


class ModelUnavailableError(ModelError):
    """Network, timeout, rate limit or provider outage, after the SDK's own retries."""


class ModelRefusedError(ModelError):
    """The model declined the request."""


class ModelOutputError(ModelError):
    """The answer failed validation on every attempt (LLM_VALIDATION_ATTEMPTS)."""


@dataclass(frozen=True)
class CallSpec[T: BaseModel]:
    name: str  # e.g. "dq_completeness"; shown in logs and the audit record
    prompt_version: str  # bump on any change to system or output, so re-runs re-check
    system: str  # stable instructions; never ticket data
    output: type[T]  # the schema the answer must match
    wrapper: str  # puts the masked ticket in its own block: "...{ticket}..."
    retry_note: str  # sent after an invalid answer: "...{wrapped}...{problem}..."
    max_tokens: int  # includes thinking, which is always on for current models
    agent: str = ""  # "data_quality" or "triage": picks that agent's model and effort; "" = the shared ones
    model: str | None = None  # None = LLM_MODEL; set for calls that need a different (cheaper) model


@dataclass(frozen=True)
class CallAudit:
    """What a call cost and used. Safe to store and log: never any ticket text."""
    provider: str
    model: str
    prompt_version: str
    attempts: int
    input_tokens: int  # not from the cache
    output_tokens: int
    latency_ms: int
    pii_masked: dict[str, int] = field(default_factory=dict)  # placeholders issued, per label
    cache_read_tokens: int = 0  # billed at the cache-read rate
    cache_write_tokens: int = 0


def _sdk() -> anthropic.Anthropic | anthropic.AnthropicBedrockMantle:
    return _build_sdk(config_version())


@lru_cache(maxsize=1)
def _build_sdk(version: int) -> anthropic.Anthropic | anthropic.AnthropicBedrockMantle:
    """Provider client, rebuilt after an admin change. Credentials come from the environment, never from code."""
    options = {"timeout": settings.LLM_TIMEOUT_S, "max_retries": settings.LLM_TRANSPORT_RETRIES}
    if settings.LLM_PROVIDER == "bedrock":
        return anthropic.AnthropicBedrockMantle(aws_region=settings.AWS_REGION, **options)
    if key := settings.ANTHROPIC_API_KEY.get_secret_value():
        options["api_key"] = key
    return anthropic.Anthropic(**options)


AGENT_SETTING_PREFIX = {"data_quality": "DQ", "triage": "TRIAGE"}


def _agent_setting(agent: str | None, name: str) -> str:
    prefix = AGENT_SETTING_PREFIX.get(agent or "")
    return (getattr(settings, f"{prefix}_LLM_{name}") if prefix else None) or getattr(settings, f"LLM_{name}")


def model_id(agent: str | None = None, model: str | None = None) -> str:
    model = model or _agent_setting(agent, "MODEL")
    if settings.LLM_PROVIDER == "bedrock" and not model.startswith(BEDROCK_MODEL_PREFIX):
        return f"{BEDROCK_MODEL_PREFIX}{model}"
    return model


def effort(agent: str | None = None) -> str:
    return _agent_setting(agent, "EFFORT")


def _request(spec: CallSpec, content: str):
    params: dict[str, Any] = {
        "model": model_id(spec.agent, spec.model),
        "max_tokens": spec.max_tokens,
        # cached: the instructions (and any rulebook in them) are identical on every call; ignored below 512 tokens
        "system": [{"type": "text", "text": spec.system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": content}],
        "output_format": spec.output,
        "output_config": {"effort": effort(spec.agent)},
    }
    if settings.LLM_PROVIDER == "anthropic" and settings.LLM_REFUSAL_FALLBACK:
        # On a refusal the API re-runs the request on a fallback model inside the same call (Claude API only)
        return _sdk().beta.messages.parse(**params, betas=[REFUSAL_FALLBACK_BETA], fallbacks="default")
    return _sdk().messages.parse(**params)


def _unmask(value: Any, masker: Masker) -> Any:
    if isinstance(value, str):
        return masker.unmask(value)
    if isinstance(value, list):
        return [_unmask(v, masker) for v in value]
    if isinstance(value, dict):
        return {k: _unmask(v, masker) for k, v in value.items()}
    return value


def call_model[T: BaseModel](spec: CallSpec[T], user: MaskedText, masker: Masker) -> tuple[T, CallAudit]:
    """Ask the model one question. Returns the validated answer with real values restored, and its audit record."""
    if not isinstance(user, MaskedText):
        raise TypeError("call_model only accepts text returned by Masker.mask()")
    if not settings.LLM_ENABLED:
        raise ModelDisabledError("LLM_ENABLED is false")

    attempts = settings.LLM_VALIDATION_ATTEMPTS
    wrapped = spec.wrapper.format(ticket=user)  # ticket text is untrusted data, kept inside its own block
    content = wrapped
    started = time.perf_counter()
    tokens_in = tokens_out = cache_read = cache_write = 0
    for attempt in range(1, attempts + 1):
        try:
            response = _request(spec, content)
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            _log(spec, "unavailable", attempt, started, tokens_in, tokens_out)
            raise ModelUnavailableError(type(exc).__name__) from exc
        except ValidationError as exc:  # schema matched but a validator rejected the answer
            problem = exc
        else:
            tokens_in += response.usage.input_tokens
            tokens_out += response.usage.output_tokens
            cache_read += getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cache_write += getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            if response.stop_reason == "refusal":
                _log(spec, "refused", attempt, started, tokens_in, tokens_out)
                raise ModelRefusedError(f"{spec.name} refused")
            if response.parsed_output is not None:
                try:
                    answer = spec.output.model_validate(_unmask(response.parsed_output.model_dump(), masker))
                except ValueError as exc:  # includes an unknown placeholder in the answer
                    problem = exc
                else:
                    audit = CallAudit(
                        provider=settings.LLM_PROVIDER,
                        model=response.model,
                        prompt_version=spec.prompt_version,
                        attempts=attempt,
                        input_tokens=tokens_in,
                        output_tokens=tokens_out,
                        latency_ms=round((time.perf_counter() - started) * 1000),
                        pii_masked=dict(masker.counts),
                        cache_read_tokens=cache_read,
                        cache_write_tokens=cache_write,
                    )
                    _log(spec, "ok", attempt, started, tokens_in, tokens_out)
                    return answer, audit
            else:
                problem = ValueError(f"no parsed output (stop_reason={response.stop_reason})")
        content = spec.retry_note.format(wrapped=wrapped, problem=problem)

    _log(spec, "invalid", attempts, started, tokens_in, tokens_out)
    raise ModelOutputError(f"{spec.name}: answer failed validation {attempts} times")


def _log(spec: CallSpec, outcome: str, attempts: int, started: float, tokens_in: int, tokens_out: int) -> None:
    latency = round((time.perf_counter() - started) * 1000)
    logger.info(
        f"model call {spec.name} {spec.prompt_version} model={model_id(spec.agent, spec.model)} outcome={outcome} "
        f"attempts={attempts} tokens_in={tokens_in} tokens_out={tokens_out} latency_ms={latency}"
    )
