"""Integration / API tests for ServiceNow tickets endpoints."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_db
from app.main import app
from app.models.servicenow import ServiceNowTicket

SAMPLE_HEADERS = [
    "ticket_id",
    "caller",
    "short_description",
    "description",
    "priority",
    "assignment_group",
    "service",
    "resolution_notes",
    "opened_at",
    "closed_at",
]


def make_excel_bytes(
    rows: list[list[Any]],
    sheet_name: str = "servicenow_tickets",
) -> bytes:
    """Helper to generate in-memory Excel file bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.rollback = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    db.scalars.return_value = mock_scalars
    return db


@pytest.fixture
async def sn_client(mock_db):
    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_servicenow_tickets(sn_client, mock_db):
    now = datetime.now(UTC)
    ticket1 = ServiceNowTicket(
        ticket_id="INC0001001",
        caller="John Doe",
        short_description="Password reset",
        priority="3 - Moderate",
        service="Active Directory",
        dq_flag=False,
        created_at=now,
    )
    ticket2 = ServiceNowTicket(
        ticket_id="INC0001002",
        caller=None,
        short_description="test",
        priority="4 - Low",
        service="Payment Gateway",
        dq_flag=True,
        dq_reason="Blank caller",
        created_at=now,
    )

    mock_db.scalar.return_value = 2
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [ticket1, ticket2]
    mock_db.scalars.return_value = mock_scalars

    response = await sn_client.get("/api/v1/servicenow/tickets", params={"dq_flag": True})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["ticket_id"] == "INC0001001"
    assert data["items"][1]["dq_flag"] is True
    assert data["items"][1]["dq_reason"] == "Blank caller"


@pytest.mark.asyncio
async def test_get_servicenow_ticket_detail(sn_client, mock_db):
    now = datetime.now(UTC)
    ticket = ServiceNowTicket(
        ticket_id="INC0001001",
        caller="Alice Smith",
        short_description="Network connectivity issue",
        priority="2 - High",
        service="Network",
        dq_flag=False,
        created_at=now,
    )
    mock_db.get.return_value = ticket

    response = await sn_client.get("/api/v1/servicenow/tickets/INC0001001")
    assert response.status_code == 200
    data = response.json()
    assert data["ticket_id"] == "INC0001001"
    assert data["caller"] == "Alice Smith"
    assert data["priority"] == "2 - High"


@pytest.mark.asyncio
async def test_get_servicenow_ticket_not_found(sn_client, mock_db):
    mock_db.get.return_value = None

    response = await sn_client.get("/api/v1/servicenow/tickets/UNKNOWN_TICKET")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ingest_servicenow_rejects_non_excel(sn_client):
    # Plain text rejected
    resp_txt = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("test.txt", b"plain text", "text/plain")},
    )
    assert resp_txt.status_code == 400
    assert "Invalid file format" in resp_txt.json()["detail"]

    # Legacy .xls rejected
    resp_xls = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("test.xls", b"binary xls data", "application/vnd.ms-excel")},
    )
    assert resp_xls.status_code == 400
    assert "Invalid file format" in resp_xls.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_servicenow_file_too_large(sn_client):
    # Payload over 10 MB limit
    large_payload = b"0" * (10 * 1024 * 1024 + 10)
    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", large_payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 413
    assert "maximum limit of 10MB" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_servicenow_corrupt_file(sn_client):
    corrupt_bytes = b"Not a valid zip or excel file"
    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", corrupt_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 400
    assert "Invalid or corrupt Excel file" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_servicenow_empty_sheet(sn_client):
    excel_bytes = make_excel_bytes([])
    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 400
    assert "Excel sheet is empty" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_servicenow_missing_id_column(sn_client):
    excel_bytes = make_excel_bytes([["caller", "short_description"], ["Alice", "Issue"]])
    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 400
    assert "must contain 'ticket_id' (or 'number') column" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_servicenow_valid_excel(sn_client, mock_db):
    row = [
        "INC0099999",
        "Tester",
        "Test short desc",
        "Test full desc",
        "3 - Moderate",
        "AMS-Test",
        "PayrollPro",
        "Resolved",
        "2026-10-01 10:00:00",
        None,
    ]
    excel_bytes = make_excel_bytes([SAMPLE_HEADERS, row])

    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_processed"] == 1
    assert data["created"] == 1
    assert data["updated"] == 0
    assert data["skipped"] == 0
    assert "Successfully ingested 1 ServiceNow tickets" in data["message"]


@pytest.mark.asyncio
async def test_ingest_servicenow_updates_existing_ticket(sn_client, mock_db):
    row = [
        "INC0099999",
        "Updated Caller",
        "Updated short desc",
        "Updated full desc",
        "2 - High",
        "AMS-DevOps",
        "OrderHub",
        "Fix applied",
        "2026-10-01 10:00:00",
        "2026-10-02 12:00:00",
    ]
    excel_bytes = make_excel_bytes([SAMPLE_HEADERS, row])

    existing = ServiceNowTicket(
        ticket_id="INC0099999",
        caller="Old Caller",
        short_description="Old desc",
        description="Old full desc",
        priority="3 - Moderate",
        assignment_group="Old Group",
        service="Old Service",
        resolution_notes="Old notes",
        opened_at=datetime(2026, 9, 1, 10, 0, 0),
        closed_at=None,
        dq_flag=True,
        dq_reason="Existing rule match",
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [existing]
    mock_db.scalars.return_value = mock_scalars

    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_processed"] == 1
    assert data["created"] == 0
    assert data["updated"] == 1
    assert data["skipped"] == 0

    # Verify updated fields (caller and caller name parts are masked via Presidio before DB write)
    assert existing.caller == "<PERSON_1>"
    assert existing.short_description == "<PERSON_1> short desc"
    assert existing.description == "<PERSON_1> full desc"
    assert existing.priority == "2 - High"
    assert existing.assignment_group == "AMS-DevOps"
    assert existing.service == "OrderHub"
    assert existing.resolution_notes == "Fix applied"
    assert existing.closed_at == datetime(2026, 10, 2, 12, 0, 0)

    # Verify DQ status preserved
    assert existing.dq_flag is True
    assert existing.dq_reason == "Existing rule match"


@pytest.mark.asyncio
async def test_ingest_servicenow_partial_columns_preserves_unmentioned_fields(sn_client, mock_db):
    # Excel only provides ticket_id and priority
    headers = ["ticket_id", "priority"]
    row = ["INC0099999", "1 - Critical"]
    excel_bytes = make_excel_bytes([headers, row])

    existing = ServiceNowTicket(
        ticket_id="INC0099999",
        caller="Keep This Caller",
        short_description="Keep This Desc",
        priority="3 - Moderate",
        service="Keep This Service",
        dq_flag=False,
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [existing]
    mock_db.scalars.return_value = mock_scalars

    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    assert existing.priority == "1 - Critical"
    assert existing.caller == "Keep This Caller"
    assert existing.short_description == "Keep This Desc"
    assert existing.service == "Keep This Service"


@pytest.mark.asyncio
async def test_ingest_servicenow_duplicate_ids_in_file(sn_client, mock_db):
    # Two rows with identical ticket_id in the same file
    row1 = ["INC0099999", "First Caller", "First Short", "", "3 - Moderate", "", "", "", None, None]
    row2 = ["INC0099999", "Second Caller", "Second Short", "", "1 - Critical", "", "", "", None, None]
    excel_bytes = make_excel_bytes([SAMPLE_HEADERS, row1, row2])

    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_processed"] == 2
    assert data["created"] == 1
    # db.add should only be called once for INC0099999
    assert mock_db.add.call_count == 1
    added_ticket = mock_db.add.call_args[0][0]
    # Caller masked via Presidio before DB write
    assert added_ticket.caller == "<PERSON_2>"
    assert added_ticket.priority == "1 - Critical"


@pytest.mark.asyncio
async def test_ingest_servicenow_skipped_rows(sn_client, mock_db):
    # Row with empty ticket_id
    valid_row = ["INC001", "Alice", "Desc 1", "", "3 - Moderate", "", "", "", None, None]
    empty_id_row = ["", "Bob", "Desc 2", "", "3 - Moderate", "", "", "", None, None]
    excel_bytes = make_excel_bytes([SAMPLE_HEADERS, valid_row, empty_id_row])

    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_processed"] == 1
    assert data["created"] == 1
    assert data["skipped"] == 1


@pytest.mark.asyncio
async def test_ingest_servicenow_db_error_triggers_rollback(sn_client, mock_db):
    row = ["INC0099999", "Tester", "Desc", "", "3 - Moderate", "", "", "", None, None]
    excel_bytes = make_excel_bytes([SAMPLE_HEADERS, row])

    mock_db.commit.side_effect = RuntimeError("Database connection lost")

    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("tickets.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to ingest file due to an internal server error."
    mock_db.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_ingest_actual_servicenow_file(sn_client, mock_db):
    file_path = Path(__file__).resolve().parents[2] / "data" / "tickets" / "servicenow_tickets.xlsx"
    if not file_path.exists():
        pytest.skip("servicenow_tickets.xlsx not found")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    xlsx_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response = await sn_client.post(
        "/api/v1/servicenow/ingest",
        files={"file": ("servicenow_tickets.xlsx", file_bytes, xlsx_mime)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_processed"] > 0
    assert data["created"] > 0
    assert data["skipped"] == 0
