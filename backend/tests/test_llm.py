"""Model client and the Data Quality model stage, against a scripted stand-in for the provider (no network)."""

from types import SimpleNamespace

import anthropic
import pytest
from pydantic import BaseModel, ValidationError

from app.common.config import settings
from app.common.llm import CallSpec, ModelDisabledError, ModelOutputError, ModelRefusedError, ModelUnavailableError, call_model
from app.common.llm import client as llm_client
from app.common.privacy.masking import Masker


class Answer(BaseModel):
    ok: bool
    note: str


SPEC = CallSpec(
    name="test", prompt_version="test@1", system="Answer.", output=Answer,
    wrapper="<t>{ticket}</t>", retry_note="{wrapped} rejected: {problem}", max_tokens=256,
)


def _reply(parsed=None, stop_reason="end_turn"):
    return SimpleNamespace(
        parsed_output=parsed, stop_reason=stop_reason, model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )


def _invalid():
    try:
        Answer.model_validate({"ok": "maybe"})
    except ValidationError as exc:
        return exc


class Provider:
    """Returns (or raises) the scripted items in order and records every request."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []
        self.messages = self
        self.beta = SimpleNamespace(messages=self)

    def parse(self, **params):
        self.requests.append(params)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ENABLED", True)

    def install(*script):
        fake = Provider(*script)
        monkeypatch.setattr(llm_client, "_sdk", lambda: fake)
        return fake

    return install


def test_plain_text_is_rejected(provider):
    provider(_reply(Answer(ok=True, note="")))
    with pytest.raises(TypeError):
        call_model(SPEC, "Priya Raman cannot log in", Masker())


def test_kill_switch_stops_before_any_request(provider, monkeypatch):
    fake = provider()
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    masker = Masker()
    with pytest.raises(ModelDisabledError):
        call_model(SPEC, masker.mask("text"), masker)
    assert fake.requests == []


def test_answer_is_unmasked_and_audit_has_no_text(provider):
    masker = Masker(known_names=["Priya Raman"])
    masked = masker.mask("Priya Raman cannot log in")
    assert "Priya" not in masked
    fake = provider(_reply(Answer(ok=True, note="Reply to <PERSON_1>")))

    answer, audit = call_model(SPEC, masked, masker)

    assert answer.note == "Reply to Priya Raman"
    assert "Priya" not in str(fake.requests[0]["messages"])
    assert audit.prompt_version == "test@1" and audit.attempts == 1 and audit.input_tokens == 100
    assert audit.pii_masked == {"PERSON": 1} and "Priya" not in str(audit)


def test_invalid_answer_is_retried_once(provider):
    masker = Masker()
    fake = provider(_invalid(), _reply(Answer(ok=False, note="fine")))
    answer, audit = call_model(SPEC, masker.mask("text"), masker)
    assert answer.ok is False and audit.attempts == 2
    assert "rejected" in fake.requests[1]["messages"][0]["content"]


def test_invalid_twice_raises(provider):
    masker = Masker()
    provider(_invalid(), _reply(Answer(ok=True, note="<PERSON_9>")))  # second: placeholder never issued
    with pytest.raises(ModelOutputError):
        call_model(SPEC, masker.mask("text"), masker)


def test_refusal_and_outage_raise(provider):
    masker = Masker()
    provider(_reply(stop_reason="refusal"))
    with pytest.raises(ModelRefusedError):
        call_model(SPEC, masker.mask("text"), masker)

    provider(anthropic.APIConnectionError(message="down", request=None))
    with pytest.raises(ModelUnavailableError):
        call_model(SPEC, masker.mask("text"), masker)


def test_bedrock_model_id_is_prefixed(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "bedrock")
    assert llm_client.model_id() == "anthropic.claude-opus-5-5"


# Data Quality model stage through the API

UNCERTAIN = "MBX-00006"  # the rules leave this one for the model, see test_data_quality


async def test_check_endpoint_runs_rules_only_when_model_is_off(client):
    await client.post("/api/v1/ingest")
    ticket_id = UNCERTAIN
    body = (await client.post(f"/api/v1/data-quality/tickets/{ticket_id}/check")).json()
    assert body["stage"] == "rules"


async def test_check_endpoint_uses_the_model(client, provider):
    from app.agents.data_quality.model_check import DQCompleteness

    await client.post("/api/v1/ingest")
    ticket_id = UNCERTAIN
    answer = DQCompleteness(complete=False, missing=["when"], reason="No start", chase_email="Hi <PERSON_1>, when did it start?")
    provider(_reply(answer))

    response = await client.post(f"/api/v1/data-quality/tickets/{ticket_id}/check")
    body = response.json()

    assert response.status_code == 200
    assert body["verdict"] == "needs_info" and body["pipeline_status"] == "awaiting_info"
    model_answer, audit = body["output"]["answer"], body["output"]["audit"]
    assert model_answer["missing"] == ["when"] and "<PERSON_1>" not in model_answer["chase_email"]
    assert audit["prompt_version"] == "dq_completeness@1" and "model" not in model_answer
    assert (await client.post(f"/api/v1/data-quality/tickets/{ticket_id}/check")).status_code == 409


async def test_model_outage_keeps_ticket_pending(client, provider):
    await client.post("/api/v1/ingest")
    ticket_id = UNCERTAIN
    provider(anthropic.APIConnectionError(message="down", request=None))
    response = await client.post(f"/api/v1/data-quality/tickets/{ticket_id}/check")
    assert response.status_code == 503
    assert (await client.get(f"/api/v1/tickets/{ticket_id}")).json()["pipeline_status"] == "pending"
