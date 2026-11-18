"""Integration / API tests for Data Quality (DQ) rules and runs endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_db
from app.main import app
from app.models.dq import DQRule, DQRun


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.add = MagicMock()

    async def fake_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(timezone.utc)

    session.refresh.side_effect = fake_refresh
    return session


@pytest.fixture
async def dq_client(mock_db):
    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_dq_rule_success(dq_client, mock_db):
    mock_db.scalar.return_value = None  # No duplicate rule name

    payload = {
        "name": "Short Description Too Short",
        "description": "Flags tickets with tiny descriptions",
        "field": "short_description",
        "operator": "length_lt",
        "value": "10",
        "source": "ServiceNow",
        "apply_to": "both",
        "is_enabled": True,
    }

    response = await dq_client.post("/api/v1/dq/rules", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["field"] == payload["field"]
    assert data["operator"] == payload["operator"]
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_create_dq_rule_invalid_field(dq_client):
    payload = {
        "name": "Invalid Field Rule",
        "field": "unknown_column_name",
        "operator": "equals",
        "value": "test",
    }
    response = await dq_client.post("/api/v1/dq/rules", json=payload)
    assert response.status_code == 400
    assert "Invalid field" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_dq_rule_duplicate_name(dq_client, mock_db):
    existing_rule = DQRule(id=1, name="Existing Rule", field="caller", operator="is_empty")
    mock_db.scalar.return_value = existing_rule

    payload = {
        "name": "Existing Rule",
        "field": "caller",
        "operator": "is_empty",
    }
    response = await dq_client.post("/api/v1/dq/rules", json=payload)
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_dq_rule_by_id(dq_client, mock_db):
    now = datetime.now(timezone.utc)
    rule = DQRule(
        id=42,
        name="Check Caller",
        field="caller",
        operator="is_empty",
        apply_to="both",
        is_enabled=True,
        created_at=now,
        updated_at=now,
    )
    mock_db.get.return_value = rule

    response = await dq_client.get("/api/v1/dq/rules/42")
    assert response.status_code == 200
    assert response.json()["id"] == 42
    assert response.json()["name"] == "Check Caller"


@pytest.mark.asyncio
async def test_get_dq_rule_not_found(dq_client, mock_db):
    mock_db.get.return_value = None

    response = await dq_client.get("/api/v1/dq/rules/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_toggle_dq_rule(dq_client, mock_db):
    now = datetime.now(timezone.utc)
    rule = DQRule(
        id=10,
        name="Toggle Test",
        field="caller",
        operator="is_empty",
        is_enabled=True,
        apply_to="both",
        created_at=now,
        updated_at=now,
    )
    mock_db.get.return_value = rule

    response = await dq_client.patch("/api/v1/dq/rules/10/toggle")
    assert response.status_code == 200
    assert response.json()["is_enabled"] is False
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_soft_delete_dq_rule(dq_client, mock_db):
    now = datetime.now(timezone.utc)
    rule = DQRule(
        id=15,
        name="Delete Me",
        field="caller",
        operator="is_empty",
        is_enabled=True,
        apply_to="both",
        created_at=now,
        updated_at=now,
    )
    mock_db.get.return_value = rule

    response = await dq_client.delete("/api/v1/dq/rules/15")
    assert response.status_code == 200
    assert rule.deleted_at is not None
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_create_dq_run(dq_client, mock_db):
    now = datetime.now(timezone.utc)
    fake_run = DQRun(
        id=1,
        scope="both",
        trigger="manual",
        tickets_evaluated=50,
        tickets_flagged=5,
        status="completed",
        rules_snapshot=[],
        started_at=now,
        finished_at=now,
    )
    with patch("app.api.v1.endpoints.dq.execute_dq_run", return_value=fake_run):
        response = await dq_client.post("/api/v1/dq/runs", json={"scope": "both", "trigger": "manual"})
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["tickets_evaluated"] == 50
        assert data["tickets_flagged"] == 5


@pytest.mark.asyncio
async def test_revert_dq_run(dq_client, mock_db):
    now = datetime.now(timezone.utc)
    fake_run = DQRun(
        id=1,
        scope="both",
        trigger="manual",
        tickets_evaluated=50,
        tickets_flagged=5,
        status="reverted",
        rules_snapshot=[],
        started_at=now,
        finished_at=now,
        reverted_at=now,
    )
    with patch("app.api.v1.endpoints.dq.revert_dq_run", return_value=fake_run):
        response = await dq_client.post("/api/v1/dq/runs/1/revert")
        assert response.status_code == 200
        assert response.json()["status"] == "reverted"

@pytest.mark.asyncio
async def test_list_ticket_sources(dq_client, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.scalars.return_value = mock_result
    response = await dq_client.get("/api/v1/dq/sources")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    codes = [item["code"] for item in data]
    assert "servicenow" in codes
    assert "jira" in codes
    assert "mailbox" in codes
