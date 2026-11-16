"""Admin API: settings, reference documents and the change history, applied live."""

import pytest

from app.core import registry
from app.core.config import bump_config_version, settings

KEY = {"X-Admin-Key": "test-key", "X-Admin-User": "alan"}


@pytest.fixture(autouse=True)
def admin_key(monkeypatch):
    """Admin on for these tests; settings and document overrides put back afterwards."""
    before = settings.model_dump()
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "test-key")
    yield
    for key, value in before.items():
        setattr(settings, key, value)
    registry.overrides.clear()
    bump_config_version()


async def test_admin_needs_the_key(client, monkeypatch):
    assert (await client.get("/api/v1/admin/settings")).status_code == 401
    assert (await client.get("/api/v1/admin/settings", headers={"X-Admin-Key": "wrong"})).status_code == 401
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "")
    assert (await client.get("/api/v1/admin/settings", headers=KEY)).status_code == 503


async def test_settings_list_hides_the_secret(client):
    rows = {r["key"]: r for r in (await client.get("/api/v1/admin/settings", headers=KEY)).json()}
    assert rows["ADMIN_API_KEY"]["value"] is True and not rows["ADMIN_API_KEY"]["editable"]
    assert rows["LLM_MODEL"]["editable"] and not rows["DATABASE_URL"]["editable"]


async def test_change_applies_live_and_is_recorded(client):
    response = await client.put("/api/v1/admin/settings/LLM_MODEL", headers=KEY, json={"value": "claude-haiku-5-5"})
    assert response.status_code == 200 and response.json()["overridden"] is True
    assert settings.LLM_MODEL == "claude-haiku-5-5"

    change = (await client.get("/api/v1/admin/changes", headers=KEY)).json()[0]
    assert change["key"] == "LLM_MODEL" and change["new_value"] == "claude-haiku-5-5" and change["claimed_by"] == "alan"

    reset = await client.delete("/api/v1/admin/settings/LLM_MODEL", headers=KEY)
    assert reset.json()["overridden"] is False and settings.LLM_MODEL == reset.json()["baseline"]


async def test_bad_values_and_guardrails_are_refused(client):
    for key, value in [
        ("LLM_PROVIDER", "openai"),  # not an allowed provider
        ("LLM_VALIDATION_ATTEMPTS", 0),  # below the minimum
        ("AWS_REGION", "us-east-1"),  # outside ALLOWED_AWS_REGIONS
        ("ALLOWED_AWS_REGIONS", ["us-east-1"]),  # env only
        ("ADMIN_API_KEY", "mine"),  # env only
    ]:
        response = await client.put(f"/api/v1/admin/settings/{key}", headers=KEY, json={"value": value})
        assert response.status_code == 422, key
    assert settings.AWS_REGION == "ca-central-1"
    old_name = await client.put("/api/v1/admin/settings/LLM_MAX_ATTEMPTS", headers=KEY, json={"value": 2})
    assert old_name.status_code == 404  # renamed to LLM_VALIDATION_ATTEMPTS


async def test_prompt_change_applies_live_and_bad_prompt_is_refused(client):
    from app.agents.data_quality.model_check import DQCompleteness, dq_completeness_spec

    baseline = dq_completeness_spec().prompt_version
    prompts = (await client.get("/api/v1/admin/documents/data_quality_prompts", headers=KEY)).json()["document"]
    prompts["dq_completeness"]["version"] = "dq_completeness@override"
    prompts["dq_completeness"]["system"] = "Shorter instructions."
    response = await client.put("/api/v1/admin/documents/data_quality_prompts", headers=KEY, json={"document": prompts})
    assert response.status_code == 200 and response.json()["overridden"] is True
    spec = dq_completeness_spec()
    assert spec.prompt_version == "dq_completeness@override" and spec.system == "Shorter instructions."
    assert spec.output is DQCompleteness  # the answer schema is code, not configurable

    broken = {"dq_completeness": {"version": "x"}}  # missing every other field
    assert (await client.put("/api/v1/admin/documents/data_quality_prompts", headers=KEY, json={"document": broken})).status_code == 422
    assert dq_completeness_spec().prompt_version == "dq_completeness@override"  # the refused change was not applied

    await client.delete("/api/v1/admin/documents/data_quality_prompts", headers=KEY)
    assert dq_completeness_spec().prompt_version == baseline


async def test_rule_change_applies_live(client):
    rules = (await client.get("/api/v1/admin/documents/data_quality_rules", headers=KEY)).json()["document"]
    rules["min_body_length"] = 10
    assert (await client.put("/api/v1/admin/documents/data_quality_rules", headers=KEY, json={"document": rules})).status_code == 200

    from app.agents.data_quality.config import get_config

    assert get_config().min_body_length == 10
    assert (await client.get("/api/v1/admin/documents/nope", headers=KEY)).status_code == 404


async def test_admin_sets_and_resets_agent_model(client):
    r = await client.put("/api/v1/admin/settings/TRIAGE_LLM_MODEL", headers=KEY, json={"value": "claude-haiku-5-5"})
    assert r.status_code == 200 and r.json()["value"] == "claude-haiku-5-5"
    bad = await client.put("/api/v1/admin/settings/TRIAGE_LLM_EFFORT", headers=KEY, json={"value": "extreme"})
    assert bad.status_code == 422
    reset = await client.delete("/api/v1/admin/settings/TRIAGE_LLM_MODEL", headers=KEY)
    assert reset.json()["value"] is None


async def test_get_yaml_keeps_repo_comments(client):
    r = (await client.get("/api/v1/admin/documents/storms/yaml", headers=KEY)).json()
    assert r["name"] == "storms" and r["overridden"] is False and "#" in r["text"]
    assert (await client.get("/api/v1/admin/documents/nope/yaml", headers=KEY)).status_code == 404


async def test_put_yaml_rejects_broken_document(client):
    url = "/api/v1/admin/documents/storms/yaml"
    unparsable = await client.put(url, headers=KEY, json={"text": "window_min: [unclosed"})
    assert unparsable.status_code == 422 and "YAML" in unparsable.json()["detail"]
    wrong_shape = await client.put(url, headers=KEY, json={"text": "- just\n- a list\n"})
    assert wrong_shape.status_code == 422
    assert (await client.get(url, headers=KEY)).json()["overridden"] is False


async def test_put_yaml_round_trip(client):
    url = "/api/v1/admin/documents/storms/yaml"
    text = (await client.get(url, headers=KEY)).json()["text"]
    saved = await client.put(url, headers=KEY, json={"text": text})
    assert saved.status_code == 200 and saved.json()["overridden"] is True and "#" not in saved.json()["text"]
    assert (await client.get("/api/v1/admin/changes", headers=KEY)).json()[0]["key"] == "storms"


async def test_settings_list_never_shows_connection_secrets(client):
    rows = {r["key"]: r for r in (await client.get("/api/v1/admin/settings", headers=KEY)).json()}
    for key in ("DATABASE_URL", "ATLASSIAN_API_TOKEN", "ATLASSIAN_EMAIL", "ANTHROPIC_API_KEY"):
        assert isinstance(rows[key]["value"], bool) and isinstance(rows[key]["baseline"], bool), key
