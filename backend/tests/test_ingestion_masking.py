"""Comprehensive tests for Presidio PII masking before DB ingestion."""

from datetime import datetime
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

from app.models.servicenow import ServiceNowTicket
from app.services.ingestion import ingest_servicenow_file

HEADERS = [
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


def make_excel(rows: list[list[Any]], sheet: str = "servicenow_tickets") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    db.scalars.return_value = mock_scalars
    return db


@pytest.mark.asyncio
async def test_servicenow_ingestion_masks_pii(mock_db):
    """Verify personal names, phone numbers, emails, and employee IDs are masked."""
    row = [
        "INC0012345",
        "Priya Raman",
        "Priya Raman cannot access PayrollPro",
        (
            "User Priya Raman (E48213) reported error ORA-01555 on OrderHub. "
            "Contact her at priya.raman@contoso.com or +91 98765 43210."
        ),
        "2 - High",
        "AMS-Support",
        "PayrollPro",
        "Contacted Priya Raman at priya.raman@contoso.com to resolve.",
        "2026-10-15 08:30:00",
        None,
    ]
    excel_bytes = make_excel([HEADERS, row])

    result = await ingest_servicenow_file(mock_db, excel_bytes, filename="snow.xlsx")
    assert result.created == 1
    assert mock_db.add.call_count == 1

    ticket: ServiceNowTicket = mock_db.add.call_args[0][0]

    # Caller must be masked to a placeholder
    assert ticket.caller == "<PERSON_1>"

    # Free text must not contain raw personal information
    for secret in ["Priya", "Raman", "E48213", "priya.raman@contoso.com", "98765 43210"]:
        assert secret not in ticket.short_description
        assert secret not in ticket.description
        assert secret not in ticket.resolution_notes

    # Verify appropriate Presidio placeholders replaced them
    assert "<PERSON_1>" in ticket.short_description
    assert "<EMPLOYEE_ID_1>" in ticket.description
    assert "<EMAIL_1>" in ticket.description
    assert "<PHONE_1>" in ticket.description

    # Protected entities (application names and error codes) must stay untouched
    assert "PayrollPro" in ticket.short_description
    assert "PayrollPro" == ticket.service
    assert "OrderHub" in ticket.description
    assert "ORA-01555" in ticket.description


@pytest.mark.asyncio
async def test_servicenow_ingestion_preserves_system_accounts(mock_db):
    """System accounts defined in pii.yaml should not be masked as persons."""
    row = [
        "INC0012346",
        "Service Desk",
        "Automated health check alert",
        "Logged by Service Desk for PayrollPro sync.",
        "3 - Moderate",
        "AMS-Ops",
        "PayrollPro",
        "Auto-resolved by Service Desk.",
        "2026-10-15 09:00:00",
        "2026-10-15 09:15:00",
    ]
    excel_bytes = make_excel([HEADERS, row])

    await ingest_servicenow_file(mock_db, excel_bytes)
    ticket: ServiceNowTicket = mock_db.add.call_args[0][0]

    assert ticket.caller == "Service Desk"
    assert "Service Desk" in ticket.description
    assert "Service Desk" in ticket.resolution_notes


@pytest.mark.asyncio
async def test_servicenow_ingestion_consistent_placeholders_across_batch(mock_db):
    """The same caller appearing in multiple tickets gets the same placeholder."""
    row1 = [
        "INC0001",
        "Ravi Kumar",
        "First issue",
        "Ravi Kumar has issue with TimeTrack.",
        "3 - Moderate",
        "AMS",
        "TimeTrack",
        None,
        None,
        None,
    ]
    row2 = [
        "INC0002",
        "Deepak Sharma",
        "Second issue",
        "Deepak Sharma has issue with InsightBI.",
        "3 - Moderate",
        "AMS",
        "InsightBI",
        None,
        None,
        None,
    ]
    row3 = [
        "INC0003",
        "Ravi Kumar",
        "Third issue",
        "Ravi Kumar reporting again.",
        "3 - Moderate",
        "AMS",
        "TimeTrack",
        None,
        None,
        None,
    ]
    excel_bytes = make_excel([HEADERS, row1, row2, row3])

    await ingest_servicenow_file(mock_db, excel_bytes)
    tickets = [call[0][0] for call in mock_db.add.call_args_list]
    assert len(tickets) == 3

    t1, t2, t3 = tickets
    assert t1.caller == t3.caller  # Same person (<PERSON_1>)
    assert t1.caller != t2.caller  # Different person (<PERSON_2>)
    assert "<PERSON_1>" in t3.description


@pytest.mark.asyncio
async def test_servicenow_ingestion_masking_can_be_disabled(mock_db):
    """When mask_pii=False, raw text is stored untouched."""
    row = [
        "INC009999",
        "Alice Smith",
        "Alice Smith needs password reset",
        "Contact Alice at alice@contoso.com",
        "4 - Low",
        "AMS",
        "OrderHub",
        None,
        None,
        None,
    ]
    excel_bytes = make_excel([HEADERS, row])

    await ingest_servicenow_file(mock_db, excel_bytes, mask_pii=False)
    ticket: ServiceNowTicket = mock_db.add.call_args[0][0]

    assert ticket.caller == "Alice Smith"
    assert "Alice Smith" in ticket.short_description
    assert "alice@contoso.com" in ticket.description


def test_ingest_workbook_masks_ticket_pii(tmp_path):
    """Verify legacy/unified ingest_workbook masks Ticket fields and raw row dict."""
    from app.models.ticket import Ticket
    from app.services.ingestion import ingest_workbook

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "JIRA"
    ws.append([
        "issue_key",
        "reporter",
        "reporter_email",
        "components",
        "issue_type",
        "environment",
        "summary",
        "description",
        "priority",
        "status",
        "assignee",
        "resolution_comment",
        "created",
        "resolved",
    ])
    ws.append([
        "JIRA-1001",
        "Sunil Verma",
        "sunil.verma@contoso.com",
        "PayrollPro",
        "Bug",
        "Prod",
        "Sunil Verma login error",
        "Call Sunil Verma at +91 98765 43210 regarding EMP12345.",
        "High",
        "Open",
        "Dev Lead",
        "Fix verified with Sunil Verma",
        datetime(2026, 11, 8, 16, 55, 16, 496000),
        None,
    ])
    file_path = tmp_path / "test_tickets.xlsx"
    wb.save(file_path)

    mock_session = MagicMock()
    mock_session.get.return_value = None  # New ticket

    result = ingest_workbook(mock_session, file_path, mask_pii=True)
    assert result.created == 1
    assert mock_session.add.call_count == 1

    ticket: Ticket = mock_session.add.call_args[0][0]
    assert ticket.reporter_name == "<PERSON_1>"
    assert ticket.reporter_email == "<EMAIL_1>"
    assert "<PERSON_1>" in ticket.summary
    assert "<PHONE_1>" in ticket.description
    assert "<EMPLOYEE_ID_1>" in ticket.description
    assert "Sunil" not in ticket.summary
    assert "sunil.verma@contoso.com" not in ticket.reporter_email

    # Raw dict should also have PII values masked
    assert ticket.raw["reporter"] == "<PERSON_1>"
    assert ticket.raw["reporter_email"] == "<EMAIL_1>"
    # ...but a date is not text: its digits must not be taken for a phone number
    assert ticket.raw["created"] == "2026-11-08T16:55:16.496000"

