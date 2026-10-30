"""Read tickets from the source workbook and upsert them into the database.

Each source sheet keeps its native format; the readers below map it to the common
Ticket fields. Only the source sheets are read; any other sheet is ignored.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.models.ticket import PipelineStatus, Ticket

logger = logging.getLogger("app.ingestion")

SNOW_STATUS = {"New": "new", "In Progress": "in_progress", "On Hold": "on_hold", "Resolved": "resolved", "Closed": "closed"}
JIRA_STATUS = {"Open": "new", "In Progress": "in_progress", "Waiting for customer": "on_hold", "Done": "closed"}
JIRA_PRIORITY = {"Highest": 1, "High": 2, "Medium": 3, "Low": 4, "Lowest": 5}
CLOSED_STATUSES = {"resolved", "closed"}


@dataclass
class IngestResult:
    created: int = 0
    updated: int = 0
    by_source: Counter = field(default_factory=Counter)


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _datetime(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    value = str(value).strip()
    return datetime.fromisoformat(value) if value else None


def _snow_priority(label: Optional[str]) -> Optional[int]:
    # "2 - High" -> 2
    if not label:
        return None
    head = label.split("-", 1)[0].strip()
    return int(head) if head.isdigit() else None


def _from_servicenow(row: dict[str, Any]) -> dict[str, Any]:
    return dict(
        id=row["number"],
        source="ServiceNow",
        reporter_name=_text(row["caller_id"]),
        reporter_email=_text(row["caller_email"]),
        reporter_department=_text(row["caller_department"]),
        channel=_text(row["contact_type"]),
        application=_text(row["cmdb_ci"]),
        category=_text(row["category"]),
        subcategory=_text(row["subcategory"]),
        environment=None,
        summary=_text(row["short_description"]) or "",
        description=_text(row["description"]) or "",
        attachments=None,
        reported_priority=_snow_priority(_text(row["priority"])),
        reported_priority_label=_text(row["priority"]),
        status=SNOW_STATUS.get(row["state"], "new"),
        source_status=_text(row["state"]),
        assignment_group=_text(row["assignment_group"]),
        assignee=_text(row["assigned_to"]),
        resolution_notes=_text(row["close_notes"]),
        opened_at=_datetime(row["opened_at"]),
        resolved_at=_datetime(row["resolved_at"]),
        closed_at=_datetime(row["closed_at"]),
    )


def _from_jira(row: dict[str, Any]) -> dict[str, Any]:
    status = JIRA_STATUS.get(row["status"], "new")
    return dict(
        id=row["issue_key"],
        source="JIRA",
        reporter_name=_text(row["reporter"]),
        reporter_email=_text(row["reporter_email"]),
        reporter_department=None,
        channel="Portal",
        application=_text(row["components"]),
        category=_text(row["issue_type"]),
        subcategory=None,
        environment=_text(row["environment"]),
        summary=_text(row["summary"]) or "",
        description=_text(row["description"]) or "",
        attachments=None,
        reported_priority=JIRA_PRIORITY.get(row["priority"]),
        reported_priority_label=_text(row["priority"]),
        status=status,
        source_status=_text(row["status"]),
        assignment_group=None,
        assignee=_text(row["assignee"]),
        resolution_notes=_text(row["resolution_comment"]),
        opened_at=_datetime(row["created"]),
        resolved_at=_datetime(row["resolved"]),
        closed_at=_datetime(row["resolved"]) if status == "closed" else None,
    )


def _from_mailbox(row: dict[str, Any]) -> dict[str, Any]:
    # emails have no structured fields: application, category and priority are left for the agents
    return dict(
        id=row["mailbox_ref"],
        source="Mailbox",
        reporter_name=_text(row["from_name"]),
        reporter_email=_text(row["from_email"]),
        reporter_department=None,
        channel="Email",
        application=None,
        category=None,
        subcategory=None,
        environment=None,
        summary=_text(row["subject"]) or "",
        description=_text(row["body"]) or "",
        attachments=_text(row["attachment_names"]),
        reported_priority=None,
        reported_priority_label=f"Importance: {row['importance']}" if row["importance"] else None,
        status="new",
        source_status=None,
        assignment_group=None,
        assignee=None,
        resolution_notes=None,
        opened_at=_datetime(row["received_at"]),
        resolved_at=None,
        closed_at=None,
    )


SOURCES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "ServiceNow": _from_servicenow,
    "JIRA": _from_jira,
    "Mailbox": _from_mailbox,
}


def _rows(workbook, sheet: str) -> Iterator[dict[str, Any]]:
    rows = workbook[sheet].iter_rows(values_only=True)
    header = next(rows)
    for values in rows:
        if any(v is not None for v in values):
            yield dict(zip(header, values))


def _raw(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


def ingest_workbook(db: Session, path: Path) -> IngestResult:
    """Upsert every ticket from the source sheets. Agent results already stored are kept."""
    if not path.exists():
        raise FileNotFoundError(f"Tickets file not found: {path}")

    workbook = load_workbook(path, read_only=True)
    result = IngestResult()
    try:
        for sheet, mapper in SOURCES.items():
            for row in _rows(workbook, sheet):
                fields = mapper(row)
                fields["raw"] = _raw(row)
                ticket = db.get(Ticket, fields["id"])
                if ticket is None:
                    fields["pipeline_status"] = (
                        PipelineStatus.HISTORICAL if fields["status"] in CLOSED_STATUSES else PipelineStatus.PENDING
                    )
                    db.add(Ticket(**fields))
                    result.created += 1
                else:
                    for key, value in fields.items():
                        setattr(ticket, key, value)
                    result.updated += 1
                result.by_source[sheet] += 1
        db.commit()
    finally:
        workbook.close()

    logger.info(f"Ingested {path.name}: created={result.created} updated={result.updated} by_source={dict(result.by_source)}")
    return result
