"""Admin API: settings, reference documents and the change history, applied live."""

import pytest

from app.common import registry
from app.common.config import bump_config_version, settings

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

    prompts = (await client.get("/api/v1/admin/documents/data_quality_prompts", headers=KEY)).json()["document"]
    prompts["dq_completeness"]["version"] = "dq_completeness@2"
    prompts["dq_completeness"]["system"] = "Shorter instructions."
    response = await client.put("/api/v1/admin/documents/data_quality_prompts", headers=KEY, json={"document": prompts})
    assert response.status_code == 200 and response.json()["overridden"] is True
    spec = dq_completeness_spec()
    assert spec.prompt_version == "dq_completeness@2" and spec.system == "Shorter instructions."
    assert spec.output is DQCompleteness  # the answer schema is code, not configurable

    broken = {"dq_completeness": {"version": "x"}}  # missing every other field
    assert (await client.put("/api/v1/admin/documents/data_quality_prompts", headers=KEY, json={"document": broken})).status_code == 422
    assert dq_completeness_spec().prompt_version == "dq_completeness@2"  # the refused change was not applied

    await client.delete("/api/v1/admin/documents/data_quality_prompts", headers=KEY)
    assert dq_completeness_spec().prompt_version == "dq_completeness@1"


async def test_rule_change_applies_live(client):
    rules = (await client.get("/api/v1/admin/documents/data_quality_rules", headers=KEY)).json()["document"]
    rules["min_body_length"] = 10
    assert (await client.put("/api/v1/admin/documents/data_quality_rules", headers=KEY, json={"document": rules})).status_code == 200

    from app.agents.data_quality.config import get_config

    assert get_config().min_body_length == 10
    assert (await client.get("/api/v1/admin/documents/nope", headers=KEY)).status_code == 404
