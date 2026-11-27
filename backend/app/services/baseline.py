"""Demo baseline: the console's tables and the synced Jira issues saved to two files, which the demo reset puts back.

Tickets that were open at the baseline come back with their times moved by the time since then, so SLA clocks, "sent N
minutes ago" and storm ages read as they did when it was taken. Closed tickets keep their dates.
"""

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, delete, insert, select, text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers every table)
from app.db.session import Base
from app.models.ticket import PipelineStatus
from app.services import atlassian, jira

DB_FILE = "console-db.json.gz"
JIRA_FILE = "jira-ams-issues.json"
NOT_SAVED = ("users", "user_sessions")  # sign-ins are not demo data
# The tables the reset restores, in insert order (a parent before its rows; deleted in reverse) -> the column naming the
# row's ticket. None: the rows are not moved in time with a ticket (a storm moves with its open tickets, see restore_db).
TABLES = {
    "storms": None, "tickets": "id", "servicenow_tickets": "ticket_id", "agent_runs": "ticket_id",
    "agent_reviews": "ticket_id", "agent_feedback": "ticket_id", "ticket_comments": "ticket_id",
    "first_messages": "ticket_id", "resolved_cases": None,
}
FIELDS = "summary,status,priority,labels,assignee,reporter,components,created,updated,resolution"


@dataclass
class Baseline:
    taken_at: datetime
    tables: dict[str, list[dict[str, Any]]]
    issues: list[dict[str, Any]]


def load(directory: Path | None) -> Baseline | None:
    """The baseline saved in this folder; None when no folder is set or its two files are not there."""
    if directory is None or not (directory / DB_FILE).is_file() or not (directory / JIRA_FILE).is_file():
        return None
    with gzip.open(directory / DB_FILE, "rt", encoding="utf-8") as f:
        saved = json.load(f)
    issues = json.loads((directory / JIRA_FILE).read_text(encoding="utf-8"))["issues"]
    return Baseline(datetime.fromisoformat(saved["taken_at"]), saved["tables"], issues)


def _encode(value: Any) -> Any:
    """What JSON cannot write by itself."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return None
    return value.tolist()  # an embedding


def save_baseline(db: Session, issues: list[dict], directory: Path) -> dict:
    """Write every table except sign-ins, and these Jira issues (see fetch_issues), as a baseline in this folder.
    A baseline already there is never overwritten. Returns when it was taken and how many rows and issues it holds."""
    taken_at = datetime.now(UTC).isoformat()
    tables = {t.name: [dict(r) for r in db.execute(select(t)).mappings()]
              for t in Base.metadata.sorted_tables if t.name not in NOT_SAVED}
    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / DB_FILE, "xt", encoding="utf-8") as f:
        json.dump({"taken_at": taken_at, "tables": tables}, f, default=_encode)
    with open(directory / JIRA_FILE, "x", encoding="utf-8") as f:
        json.dump({"taken_at": taken_at, "issues": issues}, f, ensure_ascii=False, indent=1)
    return {"taken_at": taken_at, "issues": len(issues), "tables": {name: len(rows) for name, rows in tables.items()}}


async def read_issue(c: Any, key: str) -> dict[str, Any]:
    """One Jira issue with its comments, in the shape the baseline file keeps.

    shortcut: reads the first 100 comments of an issue, like the reset's _clean_issue.
    """
    f = (await atlassian.call(c, "GET", f"/rest/api/3/issue/{key}", params={"fields": FIELDS}))["fields"]
    comments = await atlassian.call(c, "GET", f"/rest/api/3/issue/{key}/comment", params={"maxResults": 100})
    texts = [(comment, jira.adf_text(comment["body"]).strip()) for comment in comments["comments"]]
    return {
        "key": key, "summary": f.get("summary"), "status": f["status"]["name"],
        "priority": (f.get("priority") or {}).get("name"), "labels": f.get("labels") or [],
        "assignee_id": (f.get("assignee") or {}).get("accountId"), "reporter_id": (f.get("reporter") or {}).get("accountId"),
        "components": [x["name"] for x in f.get("components") or []], "created": f.get("created"), "updated": f.get("updated"),
        "resolution": (f.get("resolution") or {}).get("name"),
        "comments": [{"id": comment["id"], "author_id": comment["author"].get("accountId"), "created": comment.get("created"),
                      "ours": body.startswith(jira.SYSTEM), "text": body} for comment, body in texts],
    }


async def fetch_issues(c: Any, keys: list[str]) -> list[dict[str, Any]]:
    """Every issue of these Jira projects (the synced ones: jira_projects) with its comments, for save_baseline."""
    found = await jira.search_issues(keys) if keys else []
    return [await read_issue(c, key) for key in sorted(i["key"] for i in found)]


def _decode(column: Any, value: Any, shift: timedelta) -> Any:
    """A saved value as its column takes it: a time as a datetime, naive or with a zone as the column is, moved by shift."""
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        at = datetime.fromisoformat(value)
        if column.type.timezone:
            at = at if at.tzinfo else at.replace(tzinfo=UTC)  # SQLite drops the zone
        elif at.tzinfo:
            at = at.astimezone(UTC).replace(tzinfo=None)
        return at + shift
    if isinstance(column.type, SqlEnum) and column.type.enum_class is not None:
        return column.type.enum_class(value)
    return value


def restore_db(db: Session, saved: Baseline, now: datetime) -> int:
    """Replace the rows of TABLES with the saved ones, in the caller's transaction. Returns how many tickets were open
    at the baseline: their times, and those of their rows and of their storms, are moved by the time since then."""
    shift = now - saved.taken_at
    rows = {name: saved.tables[name] for name in TABLES}  # a table missing from the file stops here, before any delete
    open_ids = {t["id"] for t in rows["tickets"]
                if t["closed_at"] is None and t["pipeline_status"] != PipelineStatus.HISTORICAL}
    open_storms = {t["storm_id"] for t in rows["tickets"] if t["id"] in open_ids}
    for name in reversed(TABLES):
        db.execute(delete(Base.metadata.tables[name]))
    for name, ticket in TABLES.items():
        table = Base.metadata.tables[name]
        values = []
        for row in rows[name]:
            moves = row["id"] in open_storms if name == "storms" else ticket is not None and row[ticket] in open_ids
            by = shift if moves else timedelta(0)
            values.append({c.name: _decode(c, row[c.name], by) for c in table.columns if c.name in row})
        if values:
            db.execute(insert(table), values)
        # The rows went in with their saved ids: on PostgreSQL the id sequence must not be behind the highest one.
        # It is never moved back. A sequence is not part of the transaction, so this also stays after a dry run.
        if "id" in table.c and table.c.id.autoincrement is True and db.get_bind().dialect.name == "postgresql":
            sequence = f"pg_get_serial_sequence('{name}', 'id')"
            db.execute(text(f"SELECT setval({sequence}, GREATEST(nextval({sequence}), "
                            f"(SELECT COALESCE(MAX(id), 0) + 1 FROM {name})), false)"))
    return len(open_ids)
