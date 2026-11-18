"""Read tickets from the source workbook and upsert them into the database.

Each source sheet keeps its native format; the readers below map it to the common
Ticket fields. Only the source sheets are read; any other sheet is ignored.
"""

import logging
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.servicenow import ServiceNowTicket
from app.models.ticket import PipelineStatus, Ticket
from app.privacy.masking import Masker

logger = logging.getLogger("app.ingestion")

SNOW_STATUS = {"New": "new", "In Progress": "in_progress", "On Hold": "on_hold", "Resolved": "resolved", "Closed": "closed"}
JIRA_STATUS = {"Open": "new", "In Progress": "in_progress", "Waiting for customer": "on_hold", "Done": "closed"}
JIRA_PRIORITY = {"Highest": 1, "High": 2, "Medium": 3, "Low": 4, "Lowest": 5}
CLOSED_STATUSES = {"resolved", "closed"}

DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d",
)


@dataclass
class IngestResult:
    created: int = 0
    updated: int = 0
    by_source: Counter = field(default_factory=Counter)


@dataclass
class ServiceNowIngestResult:
    total_processed: int
    created: int
    updated: int
    skipped: int = 0
    filename: str | None = None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _first(d: dict[str, Any], *keys: str) -> Any | None:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    value = str(value).strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        pass

    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue

    logger.warning(f"Failed to parse datetime value: {value!r}")
    return None


def _snow_priority(label: str | None) -> int | None:
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
            yield dict(zip(header, values, strict=False))


def _raw(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


def ingest_workbook(
    db: Session,
    path: Path,
    mask_pii: bool = False,
) -> IngestResult:
    """Upsert every ticket from the source sheets. Agent results already stored are kept."""
    if not path.exists():
        raise FileNotFoundError(f"Tickets file not found: {path}")

    should_mask = mask_pii
    workbook = load_workbook(path, read_only=True)
    result = IngestResult()
    try:
        for sheet, mapper in SOURCES.items():
            if sheet not in workbook.sheetnames:  # ServiceNow now has its own file and table
                continue
            for row in _rows(workbook, sheet):
                fields = mapper(row)
                fields["raw"] = _raw(row)
                if should_mask:
                    ticket_masker = Masker(
                        known_names=[fields.get("reporter_name")],
                        known_emails=[fields.get("reporter_email")],
                    )
                    for k in ("reporter_name", "reporter_email", "summary", "description", "resolution_notes"):
                        if fields.get(k):
                            fields[k] = str(ticket_masker.mask(fields[k]))
                    if "raw" in fields and isinstance(fields["raw"], dict):
                        for rk, rv in list(fields["raw"].items()):
                            if isinstance(row.get(rk), str) and rv:  # dates became text in _raw: not PII
                                fields["raw"][rk] = str(ticket_masker.mask(rv))

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


async def ingest_servicenow_file(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str | None = None,
    mask_pii: bool | None = None,
) -> ServiceNowIngestResult:
    """Ingest tickets from a ServiceNow Excel workbook (.xlsx) into servicenow_tickets table."""
    try:
        workbook = load_workbook(BytesIO(file_bytes), read_only=True)
    except (BadZipFile, InvalidFileException, KeyError, ValueError) as exc:
        raise ValueError("Invalid or corrupt Excel file (.xlsx).") from exc

    try:
        if "servicenow_tickets" in workbook.sheetnames:
            sheet = workbook["servicenow_tickets"]
        else:
            sheet = workbook.active

        if sheet is None:
            raise ValueError("Excel sheet is empty.")

        rows = sheet.iter_rows(values_only=True)
        raw_header = next(rows, None)
        if not raw_header:
            raise ValueError("Excel sheet is empty.")

        header = [str(h).strip().lower() if h is not None else "" for h in raw_header]
        if not any(header):
            raise ValueError("Excel sheet is empty.")

        if "ticket_id" not in header and "number" not in header:
            raise ValueError(
                "Invalid ServiceNow format: Excel sheet must contain 'ticket_id' (or 'number') column."
            )

        header_set = set(header)
        has_caller = bool({"caller", "caller_id"} & header_set)
        has_short_desc = bool({"short_description", "summary"} & header_set)
        has_desc = "description" in header_set
        has_priority = "priority" in header_set
        has_assignment_group = "assignment_group" in header_set
        has_service = bool({"service", "cmdb_ci"} & header_set)
        has_res_notes = bool({"resolution_notes", "close_notes"} & header_set)
        has_opened_at = "opened_at" in header_set
        has_closed_at = "closed_at" in header_set

        valid_rows: list[dict[str, Any]] = []
        skipped = 0

        for row_vals in rows:
            if not any(v is not None for v in row_vals):
                continue
            row_dict = dict(zip(header, row_vals, strict=False))
            ticket_id = _text(_first(row_dict, "ticket_id", "number"))
            if not ticket_id:
                skipped += 1
                logger.warning(f"Skipping row missing ticket_id: {row_vals}")
                continue
            valid_rows.append(row_dict)

        unique_ids = list(dict.fromkeys(
            _text(_first(r, "ticket_id", "number")) for r in valid_rows
        ))

        existing_tickets: dict[str, ServiceNowTicket] = {}
        if unique_ids:
            stmt = select(ServiceNowTicket).where(ServiceNowTicket.ticket_id.in_(unique_ids))
            result = await db.scalars(stmt)
            existing_tickets = {t.ticket_id: t for t in result.all()}

        new_tickets: dict[str, ServiceNowTicket] = {}
        created_ids: set[str] = set()
        updated_ids: set[str] = set()

        should_mask = settings.PII_MASKING_ENABLED if mask_pii is None else mask_pii
        masker: Masker | None = None
        if should_mask:
            callers = [
                c for r in valid_rows
                if (c := _text(_first(r, "caller", "caller_id"))) is not None
            ]
            masker = Masker(known_names=callers)

        for row_dict in valid_rows:
            ticket_id = _text(_first(row_dict, "ticket_id", "number"))
            assert ticket_id is not None
            caller = _text(_first(row_dict, "caller", "caller_id"))
            short_desc = _text(_first(row_dict, "short_description", "summary"))
            desc = _text(row_dict.get("description"))
            priority = _text(row_dict.get("priority"))
            assignment_group = _text(row_dict.get("assignment_group"))
            service = _text(_first(row_dict, "service", "cmdb_ci"))
            res_notes = _text(_first(row_dict, "resolution_notes", "close_notes"))
            opened_at = _datetime(row_dict.get("opened_at"))
            closed_at = _datetime(row_dict.get("closed_at"))

            if masker is not None:
                if caller is not None:
                    caller = str(masker.mask(caller))
                if short_desc is not None:
                    short_desc = str(masker.mask(short_desc))
                if desc is not None:
                    desc = str(masker.mask(desc))
                if res_notes is not None:
                    res_notes = str(masker.mask(res_notes))

            if ticket_id in existing_tickets:
                existing = existing_tickets[ticket_id]
                if has_caller:
                    existing.caller = caller
                if has_short_desc:
                    existing.short_description = short_desc
                if has_desc:
                    existing.description = desc
                if has_priority:
                    existing.priority = priority
                if has_assignment_group:
                    existing.assignment_group = assignment_group
                if has_service:
                    existing.service = service
                if has_res_notes:
                    existing.resolution_notes = res_notes
                if has_opened_at:
                    existing.opened_at = opened_at
                if has_closed_at:
                    existing.closed_at = closed_at
                updated_ids.add(ticket_id)
            elif ticket_id in new_tickets:
                pending = new_tickets[ticket_id]
                if has_caller:
                    pending.caller = caller
                if has_short_desc:
                    pending.short_description = short_desc
                if has_desc:
                    pending.description = desc
                if has_priority:
                    pending.priority = priority
                if has_assignment_group:
                    pending.assignment_group = assignment_group
                if has_service:
                    pending.service = service
                if has_res_notes:
                    pending.resolution_notes = res_notes
                if has_opened_at:
                    pending.opened_at = opened_at
                if has_closed_at:
                    pending.closed_at = closed_at
            else:
                new_ticket = ServiceNowTicket(
                    ticket_id=ticket_id,
                    caller=caller,
                    short_description=short_desc,
                    description=desc,
                    priority=priority,
                    assignment_group=assignment_group,
                    service=service,
                    resolution_notes=res_notes,
                    opened_at=opened_at,
                    closed_at=closed_at,
                    dq_flag=False,
                    dq_reason=None,
                )
                new_tickets[ticket_id] = new_ticket
                db.add(new_ticket)
                created_ids.add(ticket_id)

        await db.commit()
        if masker is not None and masker.counts:
            logger.info(
                f"Redacted PII during ServiceNow ingestion: {dict(masker.counts.most_common())}"
            )
    finally:
        workbook.close()

    created = len(created_ids)
    updated = len(updated_ids)
    total = len(valid_rows)

    logger.info(
        f"Ingested ServiceNow Excel ({filename or 'bytes'}): created={created} updated={updated} skipped={skipped} total={total}"
    )
    return ServiceNowIngestResult(
        total_processed=total,
        created=created,
        updated=updated,
        skipped=skipped,
        filename=filename,
    )
