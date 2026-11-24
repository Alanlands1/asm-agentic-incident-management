"""Pull issues from Jira Cloud and hand new ones to the agents.

Each issue is written twice: to servicenow_tickets (what the console pages and DQ rules read) and to tickets
(what the Data Quality and Triage agents read). Read-only towards Jira, except post_comment,
set_priority and assign_issue, which a person triggers, send_sla_warnings, which the scheduler runs when SLA_AUTO_WARN is on,
answer_commands, which answers a person who wrote "/ams" on the issue, announce, which comments and labels an issue
with what the agents decided, and move_triaged, which takes an issue out of the backlog once the agents have triaged it.
Of these, only what a person sends (replies, the closure note with close_issue) is written unless JIRA_AGENT_WRITES is
on (design D8): the automatic ones (announce*, move_triaged, answer_commands, SLA warnings) check agent_writes().
What a person sets on the issue is final: a status they chose is not moved again, and a priority they set on a triaged
ticket is recorded as the decision.
Uses the API token from the environment.
"""

import asyncio
import contextlib
import logging
import math
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, object_session, selectinload
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.confluence import ConfluencePage
from app.models.jira import JiraProject, JiraSync
from app.models.kb import KBChunk
from app.models.servicenow import ServiceNowTicket
from app.models.ticket import AgentRun, Comment, PipelineStatus, Review, Ticket
from app.privacy.masking import Masker
from app.services import atlassian
from app.services.atlassian import AtlassianError
from app.services.closure import run_closure
from app.services.comments import add_comment
from app.services.data_quality import last_run, run_data_quality
from app.services.knowledge import run_knowledge
from app.services.resolution import run_resolution
from app.services.triage import review as triage_review
from app.services.triage import run_triage, sla

logger = logging.getLogger("app.jira")

# Same labels the ServiceNow sheet uses, so priority chips and DQ rules work unchanged.
PRIORITY = {"Highest": "1 - Critical", "High": "2 - High", "Medium": "3 - Moderate", "Low": "4 - Low", "Lowest": "5 - Planning"}
FIELDS = [
    "summary", "description", "priority", "status", "reporter", "assignee", "components", "issuetype", "environment",
    "created", "resolutiondate", "project", "comment",
]
PRIORITY_NUMBER = {"Highest": 1, "High": 2, "Medium": 3, "Low": 4, "Lowest": 5}
STATUS = {"new": "new", "indeterminate": "in_progress", "done": "closed"}  # Jira status category -> tickets.status
MAX_ISSUES = 5000  # shortcut: one sync pulls at most this many issues; page by updated date if projects grow past it

sync_lock = asyncio.Lock()
agents_lock = asyncio.Lock()
_background: set[asyncio.Task] = set()  # keeps agent runs alive until they finish


JiraError = AtlassianError
whoami = atlassian.whoami


async def list_projects() -> list[dict[str, str]]:
    async with atlassian.client() as c:
        data = await atlassian.call(c, "GET", "/rest/api/3/project/search", params={"maxResults": 100, "orderBy": "key"})
    return [{"key": p["key"], "name": p["name"]} for p in data["values"]]


async def search_issues(keys: list[str], since_minutes: int | None = None) -> list[dict[str, Any]]:
    """Issues of these projects; only those changed in the last since_minutes when given (relative, so no time zones)."""
    changed = f" AND updated >= -{since_minutes}m" if since_minutes else ""
    jql = f"project in ({', '.join(keys)}){changed} ORDER BY updated DESC"
    issues: list[dict[str, Any]] = []
    token = None
    async with atlassian.client() as c:
        while len(issues) < MAX_ISSUES:
            body: dict[str, Any] = {"jql": jql, "fields": FIELDS, "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            page = await atlassian.call(c, "POST", "/rest/api/3/search/jql", json=body)
            issues += page["issues"]
            token = page.get("nextPageToken")
            if page.get("isLast", True) or not token:
                break
    return issues


@contextlib.asynccontextmanager
async def _jira(c: Any = None):
    """The Jira connection a loop already holds, or a new one for a single call: opening one can take seconds."""
    if c is not None:
        yield c
    else:
        async with atlassian.client() as new:
            yield new


async def reporter_replies(issue: dict[str, Any], c: Any = None) -> list[str]:
    """What the reporter wrote in an issue's comments, oldest first. Commands to the agents and our own comments are
    left out: the API token may belong to the reporter.

    shortcut: reads the newest 20 comments only; page through them if reporters answer on busier issues.
    """
    reporter = (issue["fields"].get("reporter") or {}).get("accountId")
    async with _jira(c) as c:
        newest = {"orderBy": "-created", "maxResults": 20}
        data = await atlassian.call(c, "GET", f"/rest/api/3/issue/{issue['key']}/comment", params=newest)
    texts = [
        adf_text(comment["body"]).strip()
        for comment in reversed(data["comments"])
        if reporter and comment["author"].get("accountId") == reporter
    ]
    return [t for t in texts if t and not t.startswith(SYSTEM) and not _to_agents(t)]


INLINE = re.compile(r"`([^`]+)`|\[([^\]]+)\]\((https?://[^)\s]+)\)")  # `command` and [title](url) in a system comment
LABEL = re.compile(r"[A-Z][\w ]{0,24}: ")  # "Likely cause: ..." starts a line: the label is bold
ORDERED = re.compile(r"\d+\. ")


def plain(text: str) -> str:
    """A system comment without its `code` and [link](url) marks: the copy kept on the ticket."""
    return INLINE.sub(lambda m: m.group(1) or m.group(2), text)


def _t(text: str, *marks: dict) -> dict:
    return {"type": "text", "text": text, **({"marks": list(marks)} if marks else {})}


def _inline(line: str) -> list[dict]:
    nodes, at = [], 0
    if (label := LABEL.match(line)) is not None:
        nodes.append(_t(label.group(0)[:-1], {"type": "strong"}))
        at = label.end() - 1  # the space stays plain
    for m in INLINE.finditer(line, at):
        if m.start() > at:
            nodes.append(_t(line[at:m.start()]))
        nodes.append(_t(m.group(1), {"type": "code"}) if m.group(1)
                     else _t(m.group(2), {"type": "link", "attrs": {"href": m.group(3)}}))
        at = m.end()
    if at < len(line):
        nodes.append(_t(line[at:]))
    return nodes


def _panel(text: str, tone: str) -> dict:
    """A system comment as a coloured Jira panel: the first line a heading, "- " lines a bullet list, "1. " lines numbered."""
    title, *rest = text.splitlines()
    content: list[dict] = [{"type": "heading", "attrs": {"level": 4}, "content": [_t(title)]}]
    items = None
    for line in rest:
        kind = "bulletList" if line.startswith("- ") else "orderedList" if ORDERED.match(line) else None
        if kind is None:
            items = None
            if line:
                content.append({"type": "paragraph", "content": _inline(line)})
            continue
        if items is None or items["type"] != kind:
            items = {"type": kind, "content": []}
            content.append(items)
        body = line[2:] if kind == "bulletList" else ORDERED.sub("", line, count=1)
        items["content"].append({"type": "listItem", "content": [{"type": "paragraph", "content": _inline(body)}]})
    return {"type": "panel", "attrs": {"panelType": tone}, "content": content}


async def post_comment(key: str, text: str, c: Any = None, tone: str | None = None) -> None:
    """Add a comment to a Jira issue, as the owner of the API token. With a tone (info, note, success, warning, error)
    the text is a system comment, formatted in a panel of that colour; without one it goes as written, in an info panel.
    """
    if not settings.JIRA_WRITE_BACK:
        raise AtlassianError("Writing to Jira is switched off: set JIRA_WRITE_BACK=true in backend/.env")
    lines = [{"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []} for line in text.splitlines()]
    # a panel marks the comment as the system's: Jira shows it under the token owner's name
    panel = _panel(text, tone) if tone else {"type": "panel", "attrs": {"panelType": "info"}, "content": lines}
    async with _jira(c) as c:
        await atlassian.call(
            c, "POST", f"/rest/api/3/issue/{key}/comment", json={"body": {"type": "doc", "version": 1, "content": [panel]}}
        )


def agent_writes() -> bool:
    """Whether the system writes to Jira on its own (comments, labels, status, priority, SLA warnings, /ams answers).
    Off unless JIRA_AGENT_WRITES is on (design D8): then only what an engineer sends reaches Jira."""
    return settings.JIRA_WRITE_BACK and settings.JIRA_AGENT_WRITES


async def close_issue(key: str, text: str, c: Any = None, priority: int | None = None) -> str:
    """Post the closure note on a Jira issue and move the issue to a done status, as the owner of the API token. The note
    goes as written, so the next sync reads it back as the close notes. `priority`: the decided one, set first when it
    differs from the issue's (the decision goes back with the note). Returns the status the issue moved to."""
    if not settings.JIRA_WRITE_BACK:
        raise AtlassianError("Writing to Jira is switched off: set JIRA_WRITE_BACK=true in backend/.env")
    async with _jira(c) as c:
        url = f"/rest/api/3/issue/{key}/transitions"
        steps = (await atlassian.call(c, "GET", url))["transitions"]
        step = next((s for s in steps if (s["to"].get("statusCategory") or {}).get("key") == "done"), None)
        if step is None:  # checked before the comment, so a note is never left on an issue that stays open
            raise AtlassianError(f"{key} has no move to a done status from where it is in Jira")
        if priority is not None:
            await set_priority(key, priority, c)
        await post_comment(key, text, c)
        await atlassian.call(c, "POST", url, json={"transition": {"id": step["id"]}})
    return step["to"]["name"]


async def set_priority(key: str, priority: int, c: Any = None) -> None:
    """Set a Jira issue's priority to the reviewed one (1 Highest .. 5 Lowest), as the owner of the API token."""
    if not settings.JIRA_WRITE_BACK:
        raise AtlassianError("Writing to Jira is switched off: set JIRA_WRITE_BACK=true in backend/.env")
    name = next(n for n, p in PRIORITY_NUMBER.items() if p == priority)
    async with _jira(c) as c:
        await atlassian.call(c, "PUT", f"/rest/api/3/issue/{key}", json={"fields": {"priority": {"name": name}}})


async def assignable(keys: list[str], c: Any = None) -> list[str]:
    """The people an issue of these projects can be assigned to, by display name. Apps and closed accounts are left out."""
    names: set[str] = set()
    async with _jira(c) as c:
        for key in keys:
            people = await atlassian.call(
                c, "GET", "/rest/api/3/user/assignable/search", params={"project": key, "maxResults": 200})
            names |= {p["displayName"] for p in (people if isinstance(people, list) else [])
                      if isinstance(p, dict) and p.get("displayName") and p.get("active", True)
                      and p.get("accountType", "atlassian") == "atlassian"}
    return sorted(names)


known_people: list[str] | None = None  # who Jira lets a ticket be assigned to; None until Jira has answered
_people_asked: datetime | None = None
PEOPLE_RETRY = 300  # seconds before Jira is asked again after it did not answer


async def refresh_people(db: AsyncSession, force: bool = False) -> None:
    """Ask Jira who can be assigned in the selected projects and remember it: on every sync, and on the first read
    after a start. shortcut: kept in memory, one process; store it once the API runs as several."""
    global known_people, _people_asked
    now = datetime.now(UTC)
    waiting = _people_asked is not None and (now - _people_asked).total_seconds() < PEOPLE_RETRY
    if not force and (known_people is not None or waiting):
        return
    keys = list(await db.scalars(select(JiraProject.key)))
    await db.commit()  # no transaction open while Jira answers
    if not keys or not atlassian.configured():
        return
    _people_asked = now
    try:
        known_people = await assignable(keys)
    except AtlassianError:
        logger.warning("Jira did not say who can be assigned; the people known here are used")


async def assign_issue(key: str, name: str | None, c: Any = None) -> None:
    """Assign a Jira issue to the person with this display name (None: nobody), as the owner of the API token."""
    if not settings.JIRA_WRITE_BACK:
        raise AtlassianError("Writing to Jira is switched off: set JIRA_WRITE_BACK=true in backend/.env")
    async with _jira(c) as c:
        account = None
        if name:
            people = await atlassian.call(c, "GET", "/rest/api/3/user/assignable/search", params={"issueKey": key, "query": name})
            account = next((p["accountId"] for p in people or [] if p.get("displayName") == name), None)
            if account is None:
                raise AtlassianError(f"{name} cannot be assigned {key} in Jira")
        await atlassian.call(c, "PUT", f"/rest/api/3/issue/{key}/assignee", json={"accountId": account})


def adf_text(node: Any) -> str:
    """Plain text from a Jira description (Atlassian Document Format)."""
    if not isinstance(node, dict):
        return node if isinstance(node, str) else ""
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "hardBreak":
        return "\n"
    inner = "".join(adf_text(child) for child in node.get("content", []))
    return inner + "\n" if node.get("type") in {"paragraph", "heading", "listItem", "codeBlock"} else inner


def _when(value: str | None) -> datetime | None:
    # servicenow_tickets stores naive UTC
    return datetime.fromisoformat(value).astimezone(UTC).replace(tzinfo=None) if value else None


def map_issue(issue: dict[str, Any], team: str | None) -> dict[str, Any]:
    """Jira issue -> servicenow_tickets columns (before masking)."""
    f = issue["fields"]
    done = (f.get("status") or {}).get("statusCategory", {}).get("key") == "done"
    components = f.get("components") or []
    return dict(
        ticket_id=issue["key"],
        caller=(f.get("reporter") or {}).get("displayName"),
        short_description=f.get("summary"),
        description=adf_text(f.get("description")).strip() or None,
        priority=PRIORITY.get((f.get("priority") or {}).get("name", "")),
        assignment_group=team or (f.get("project") or {}).get("name"),
        service=components[0]["name"] if components else None,
        opened_at=_when(f.get("created")),
        closed_at=(_when(f.get("resolutiondate")) or datetime.now(UTC).replace(tzinfo=None)) if done else None,
    )


def _close_notes(fields: dict[str, Any]) -> str | None:
    """The newest comment a person wrote on the issue: on a done issue, how it was fixed (Jira has no close-notes field)."""
    for comment in reversed((fields.get("comment") or {}).get("comments", [])):
        text = adf_text(comment.get("body")).strip()
        if text and not text.startswith(SYSTEM) and not _to_agents(text):
            return text
    return None


def map_ticket(issue: dict[str, Any], team: str | None) -> dict[str, Any]:
    """Jira issue -> tickets columns (before masking), the agents' input."""
    f = issue["fields"]
    category = (f.get("status") or {}).get("statusCategory", {}).get("key", "new")
    status = STATUS.get(category, "new")
    reporter = f.get("reporter") or {}
    components = f.get("components") or []
    priority = (f.get("priority") or {}).get("name")
    resolved = _when(f.get("resolutiondate"))
    return dict(
        id=issue["key"],
        source="JIRA",
        reporter_name=reporter.get("displayName"),
        reporter_email=reporter.get("emailAddress"),
        channel="Portal",
        application=components[0]["name"] if components else None,
        category=(f.get("issuetype") or {}).get("name"),
        environment=adf_text(f.get("environment")).strip() or None,
        summary=f.get("summary") or "",
        description=adf_text(f.get("description")).strip(),
        reported_priority=PRIORITY_NUMBER.get(priority or ""),
        reported_priority_label=priority,
        status=status,
        source_status=(f.get("status") or {}).get("name"),
        assignment_group=team or (f.get("project") or {}).get("name"),
        assignee=(f.get("assignee") or {}).get("displayName"),
        opened_at=_when(f.get("created")),
        resolved_at=resolved,
        closed_at=(resolved or datetime.now(UTC).replace(tzinfo=None)) if status == "closed" else None,  # Done with no date
        resolution_notes=_close_notes(f) if status == "closed" else None,  # what Closure Quality checks
        # no names or text here: raw is stored unmasked
        raw={"key": issue["key"], "status": (f.get("status") or {}).get("name"), "priority": priority,
             "components": [c["name"] for c in components]},
    )


def _mask(row: dict[str, Any], name_key: str, email_key: str | None, text_keys: tuple[str, ...]) -> Masker:
    """Mask one ticket's personal data in place; one masker per ticket keeps placeholders stable between syncs."""
    masker = Masker(known_names=[row.get(name_key)], known_emails=[row.get(email_key)] if email_key else ())
    for k in (name_key, email_key, *text_keys):
        if k and row.get(k):
            row[k] = str(masker.mask(row[k]))
    return masker


async def _since_minutes(db: AsyncSession, trigger: str, projects: str) -> int | None:
    """Scheduled syncs pull only what changed since the last good sync of the same projects; others pull everything."""
    if trigger != "schedule":
        return None
    last = await db.scalar(
        select(JiraSync)
        .where(JiraSync.error.is_(None), JiraSync.finished_at.is_not(None), JiraSync.projects == projects)
        .order_by(JiraSync.started_at.desc())
        .limit(1)
    )
    if last is None:
        return None
    started = last.started_at if last.started_at.tzinfo else last.started_at.replace(tzinfo=UTC)  # SQLite drops the zone
    return math.ceil((datetime.now(UTC) - started).total_seconds() / 60) + 2  # overlap so nothing slips through


async def _upsert(
    db: AsyncSession, issues: list[dict[str, Any]], teams: dict[str, str | None], run: JiraSync, replies: dict[str, list[str]]
) -> None:
    console = [map_issue(i, teams.get(i["key"].split("-")[0])) for i in issues]
    agents = [map_ticket(i, teams.get(i["key"].split("-")[0])) for i in issues]
    if settings.PII_MASKING_ENABLED:
        for r in console:
            _mask(r, "caller", None, ("short_description", "description"))
        for r in agents:
            masker = _mask(r, "reporter_name", "reporter_email", ("summary", "description", "resolution_notes"))
            if r["id"] in replies:
                replies[r["id"]] = [str(masker.mask(body)) for body in replies[r["id"]]]

    ids = [r["ticket_id"] for r in console]
    found = {t.ticket_id: t for t in await db.scalars(select(ServiceNowTicket).where(ServiceNowTicket.ticket_id.in_(ids)))}
    for r in console:
        if (t := found.get(r["ticket_id"])) is not None:
            for k, v in r.items():
                setattr(t, k, v)
            run.updated += 1
        else:
            db.add(ServiceNowTicket(**r, dq_flag=False))
            run.created += 1

    known = {t.id: t for t in await db.scalars(select(Ticket).where(Ticket.id.in_(ids)))}
    stored = {(i, b) for i, b in await db.execute(select(Comment.ticket_id, Comment.body).where(Comment.ticket_id.in_(replies)))}
    repriced = [  # triaged tickets whose priority changed in Jira since the last sync
        t for r in agents
        if (t := known.get(r["id"])) is not None and t.pipeline_status in TRIAGE_DONE and r["reported_priority"]
        and "priority" in (t.raw or {}) and t.raw["priority"] != r["raw"]["priority"]
    ]
    in_force = await db.run_sync(lambda s: sla.working_priorities(s, repriced)) if repriced else {}
    for r in agents:
        if (t := known.get(r["id"])) is not None:
            if t.pipeline_status in TRIAGE_DONE:
                priority, source, triage = in_force.get(t.id, (None, None, None))
                if triage is not None and (source == "recommended" or r["reported_priority"] != priority):
                    # set by a person on the issue, not by a review here: what is set in Jira is the decision
                    action = "accepted" if r["reported_priority"] == triage.output["priority"] else "edited"
                    db.add(Review(ticket_id=t.id, agent_run_id=triage.id, agent="triage", action=action, reviewer=IN_JIRA,
                                  final_priority=r["reported_priority"], note=f"Priority set to {r['raw']['priority']} in Jira"))
                    if t.pipeline_status == PipelineStatus.TRIAGED:  # a ticket further on stays where it is
                        t.pipeline_status = PipelineStatus.REVIEWED
                # Jira now holds the decided priority; the reporter's own stays as they gave it
                r = {k: v for k, v in r.items() if not k.startswith("reported_priority")}
            edited = (t.summary, t.description) != (r["summary"], r["description"])
            new = [body for body in replies.get(t.id, []) if (t.id, body) not in stored]
            if t.pipeline_status in RECHECK and (edited or new) and r["status"] != "closed":
                t.pipeline_status = PipelineStatus.PENDING  # the missing details were added on the issue: check again
                run.queued += 1
                author = r["reporter_email"] or r["reporter_name"] or "reporter"  # Jira often hides the email
                db.add_all(Comment(ticket_id=t.id, author_email=author, body=body, from_reporter=True) for body in new)
            if r["status"] == "closed" and (t.status != "closed" or t.resolution_notes != r["resolution_notes"]):
                run.queued += 1  # closed in Jira, or its close notes changed: Closure Quality and Knowledge Builder run
            for k, v in r.items():  # agent results are kept, and the pipeline status unless set just above
                if k == "resolution_notes" and v is None:
                    continue  # an open issue has none: the closure note written in the console stays
                if k != "opened_at":  # never changes in Jira; a clock restarted here for a test survives the sync
                    setattr(t, k, v)
        else:
            closed = r["status"] == "closed"
            db.add(Ticket(**r, pipeline_status=PipelineStatus.HISTORICAL if closed else PipelineStatus.PENDING))
            run.queued += 0 if closed else 1
    run.pulled = len(issues)


async def run_sync(db: AsyncSession, trigger: str) -> JiraSync:
    """Pull the selected projects and upsert them. DQ flags and agent results already stored are kept."""
    if sync_lock.locked():
        raise JiraError("A sync is already running")
    async with sync_lock:
        projects = (await db.scalars(select(JiraProject).order_by(JiraProject.key))).all()
        keys = ",".join(p.key for p in projects)
        since = await _since_minutes(db, trigger, keys)
        run = JiraSync(trigger=trigger, projects=keys)
        db.add(run)
        await db.commit()
        try:
            if not projects:
                raise JiraError("No projects selected: pick at least one project first")
            teams = {p.key: p.team for p in projects}
            issues = await search_issues(list(teams), since)  # no transaction open while Jira answers
            waiting = set(await db.scalars(select(Ticket.id).where(Ticket.pipeline_status.in_(RECHECK))))
            await db.commit()  # again no transaction open while Jira answers
            replies = {}
            if asked := [i for i in issues if i["key"] in waiting]:
                async with atlassian.client() as c:  # one connection for all of them
                    replies = {i["key"]: await reporter_replies(i, c) for i in asked}
            await _upsert(db, issues, teams, run, replies)
        except Exception as exc:
            await db.rollback()  # nothing from this sync is kept
            await db.refresh(run)
            if isinstance(exc, JiraError):
                run.error = str(exc)
                logger.warning("Jira sync %s: %s", run.id, exc)
            else:
                run.error = f"Sync failed: {exc.__class__.__name__}"
                logger.exception("Jira sync %s failed", run.id)
        run.finished_at = datetime.now(UTC)
        await refresh_people(db, force=True)  # who can be assigned may have changed too
        db.add(run)
        await db.commit()
        logger.info(
            "Jira sync %s: pulled=%s created=%s updated=%s queued=%s", run.id, run.pulled, run.created, run.updated, run.queued
        )
        return run


TRIAGED_STATUS = "Selected for development"  # where a triaged issue goes; an issue that cannot go there is left alone
TRIAGE_DONE = (PipelineStatus.TRIAGED, PipelineStatus.REVIEWED, PipelineStatus.FIX_CONFIRMED, PipelineStatus.NEEDS_LEAD,
               PipelineStatus.IN_REVIEW, PipelineStatus.APPROVED)
RECHECK = (PipelineStatus.AWAITING_INFO, PipelineStatus.REJECTED)  # an edit or a reporter's reply sends these back to the agents
IN_JIRA = "Set in Jira"  # the reviewer of a decision a person made on the issue itself


async def move_triaged(db: AsyncSession) -> int:
    """Move the Jira issues the agents have triaged out of the backlog, as the owner of the API token. Only an issue
    whose status never changed is moved, so once at most: one a person moved, also back to the backlog, stays where
    they put it. Returns how many were moved.

    shortcut: reads the newest 100 changes of an issue; page the changelog if issues get busier than that.
    """
    if not agent_writes():
        return 0
    tickets = (await db.scalars(
        select(Ticket).where(Ticket.source == "JIRA", Ticket.status == "new", Ticket.pipeline_status.in_(TRIAGE_DONE))
    )).all()
    reset = await db.scalar(select(JiraSync.started_at).where(JiraSync.trigger == "reset")
                            .order_by(JiraSync.started_at.desc()).limit(1))
    reset = (reset if reset.tzinfo else reset.replace(tzinfo=UTC)) if reset else None  # SQLite drops the zone
    await db.commit()  # no transaction open while Jira answers
    moved = 0
    async with atlassian.client() as c:
        for ticket in tickets:
            try:
                history = {"fields": "status", "expand": "changelog"}
                issue = await atlassian.call(c, "GET", f"/rest/api/3/issue/{ticket.id}", params=history)
                if any(i["field"] == "status" for h in issue["changelog"]["histories"] for i in h["items"]
                       if reset is None or datetime.fromisoformat(h["created"]) > reset):
                    continue  # the status set in Jira is final (moves before a demo reset do not count)
                url = f"/rest/api/3/issue/{ticket.id}/transitions"
                steps = (await atlassian.call(c, "GET", url))["transitions"]
                step = next((s for s in steps if s["to"]["name"].casefold() == TRIAGED_STATUS.casefold()), None)
                if step is None:
                    continue
                await atlassian.call(c, "POST", url, json={"transition": {"id": step["id"]}})
            except AtlassianError as exc:  # one missing or locked issue must not stop the others; retried next pass
                logger.warning("Triaged issue %s not moved in Jira: %s", ticket.id, exc)
                continue
            ticket.status, ticket.source_status = "in_progress", step["to"]["name"]  # what the next sync would bring
            moved += 1
    await db.commit()
    return moved


def _agents_in_thread() -> None:
    """Data Quality, then Triage; then, for resolved tickets, Closure Quality and Knowledge Builder. In a worker thread
    with its own event loop and database engine.

    The agents call the model synchronously (up to a minute per call); on the API's loop that would freeze every request.
    """
    async def run() -> None:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        try:
            sessions = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
            started = datetime.now(UTC)
            async with sessions() as db:
                await db.run_sync(run_data_quality)
            async with sessions() as db:
                await db.run_sync(run_triage)
            async with sessions() as db:
                await announce(db, started)
                await move_triaged(db)
            closing = datetime.now(UTC)
            async with sessions() as db:
                await db.run_sync(run_closure)
            async with sessions() as db:
                await announce_closure(db, closing)
            async with sessions() as db:  # after Closure Quality: it learns only from notes that passed
                await db.run_sync(run_knowledge)
        finally:
            await engine.dispose()

    asyncio.run(run())


async def run_agents() -> None:
    """One agent pass at a time; a sync that finds new tickets while one runs leaves them for the next pass.
    Tickets whose priority Triage approved without a person go on to Resolution straight away."""
    if agents_lock.locked():
        return
    async with agents_lock:
        try:
            await asyncio.to_thread(_agents_in_thread)
        except Exception:
            logger.exception("Agents after Jira sync failed")
    await resolve_now()


def start_agents() -> None:
    task = asyncio.create_task(run_agents())
    _background.add(task)
    task.add_done_callback(_background.discard)


async def resolve_now(ticket_id: str | None = None) -> None:
    """Resolution for every reviewed ticket that changed, or for one ticket, without waiting for the next sync."""
    started = datetime.now(UTC)
    try:
        await run_resolution(ticket_id=ticket_id)
        async with AsyncSessionLocal() as db:
            await announce_resolution(db, started)
    except Exception:
        logger.exception("Resolution after a priority decision failed")


def start_resolution(ticket_id: str | None = None) -> None:
    """Run Resolution in the background once a priority is decided, by a person or automatically, or for one ticket
    whose fix did not work."""
    task = asyncio.create_task(resolve_now(ticket_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


def _knowledge_in_thread() -> None:
    """Knowledge Builder alone, in a worker thread with its own event loop and engine, as in the agents' pass."""
    async def run() -> None:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        try:
            async with async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
                await db.run_sync(run_knowledge)
        finally:
            await engine.dispose()

    asyncio.run(run())


async def learn_now() -> None:
    """Knowledge Builder right after a ticket is closed here, not on the next sync. Under the agents' lock, so it never
    runs beside a pass, and the ticket page shows the agents at work meanwhile."""
    async with agents_lock:
        try:
            await asyncio.to_thread(_knowledge_in_thread)
        except Exception:
            logger.exception("Knowledge Builder after closing a ticket failed")


def start_knowledge() -> None:
    task = asyncio.create_task(learn_now())
    _background.add(task)
    task.add_done_callback(_background.discard)


SLA_BOT = "AMS system (SLA warning)"


USED = re.compile(r"(\d+)% of the target")  # in every warning; the stored copies tell which level was sent


def _levels() -> tuple[int, ...]:
    """Warning levels as a share of the SLA target, in percent: watch, breach likely, breached (the console's states)."""
    cfg = sla.config()
    return (round(cfg.watch_at * 100), round(cfg.breach_likely_at * 100), 100)


def _step(percent: int, levels: tuple[int, ...]) -> int:
    """The highest level this share of the target has reached, 0 below the first."""
    return max((p for p in levels if percent >= p), default=0)


def _due_warnings(db: Session) -> list[tuple[Ticket, str, str]]:
    """Open P1/P2 Jira tickets that reached a warning level since their last warning, each with its text and tone."""
    items = [i for i in sla.open_p1_p2(db) if i.ticket.source == "JIRA"]
    levels = _levels()
    sent: dict[str, int] = {}
    for ticket_id, body in db.execute(select(Comment.ticket_id, Comment.body).where(
            Comment.author_email == SLA_BOT, Comment.ticket_id.in_([i.ticket.id for i in items]))):
        if (said := USED.search(body)) is not None:
            sent[ticket_id] = max(sent.get(ticket_id, 0), _step(int(said.group(1)), levels))
    due = []
    for i in items:
        used = int(i.sla.used * 100)
        if _step(used, levels) > sent.get(i.ticket.id, 0):  # levels passed while the system was off are not sent late
            due_at = f"{sla.local(i.sla.due_at):%d %b %H:%M %Z}"
            breached = used >= 100
            text = (f"SLA breached · P{i.priority}, {-i.sla.minutes_left} min over\nWas due: {due_at}" if breached
                    else f"SLA warning · P{i.priority} due in {i.sla.minutes_left} min\nDue: {due_at}")
            due.append((i.ticket, f"{text} ({used}% of the target time used)\nAssignee: {i.ticket.assignee or 'nobody'}",
                        "error" if breached else "warning"))
    return due


async def send_sla_warnings(db: AsyncSession) -> int:
    """Comment on a Jira issue when it reaches watch, breach likely and the breach of its SLA target (Jira then mails
    the people on the issue), and keep a copy on the ticket. Returns how many comments were sent.
    """
    due = await db.run_sync(_due_warnings)
    for ticket, text, tone in due:
        await post_comment(ticket.id, text, tone=tone)
        await db.run_sync(add_comment, ticket, SLA_BOT, text)  # the copy is what stops the same warning twice
    return len(due)


COMMAND = re.compile(r"/?ams\s*(dq|triage|agree)?")  # the whole comment: "/ams", "/ams dq", "ams triage", "/ams agree"
COMMAND_BOT = "AMS system (asked in Jira)"
AGENTS_BOT = "AMS agents"  # author of the stored copy of what announce wrote on the issue
SAID = "AMS agents · "  # how every answer starts (its heading); a command with an answer after it is not answered again
EARLIER = ("AMS agents on ", "Automatic SLA warning")  # how the system's comments started before
SYSTEM = (SAID, "SLA warning · ", "SLA breached · ", *EARLIER)  # how every comment the system writes on an issue starts


def help_text() -> str:
    return ("Reply with one of these as a whole comment:\n"
            "- `ams`: what the agents decided\n"
            "- `ams dq` or `ams triage`: one agent's result\n"
            "- `ams agree`: accept the recommended priority\n"
            f"Answers come within about {settings.JIRA_SYNC_MINUTES} min.")


# one at a time
LABELS = ["ams-needs-info", "ams-not-incident", "ams-dq-passed", "ams-uncertain", *(f"ams-p{n}" for n in range(1, 6))]
AGENTS = {"data_quality": "Data Quality", "triage": "Triage"}
NEXT = {  # the line under the heading, for a ticket where nothing else needs saying
    PipelineStatus.PENDING: "Waiting for the Data Quality agent.",
    PipelineStatus.DQ_PASSED: "Waiting for the Triage agent.",
    PipelineStatus.REVIEWED: "The priority is decided; the ticket is ready to be worked.",
    PipelineStatus.ERROR: "Next: a person needs to look at this ticket.",
    PipelineStatus.HISTORICAL: "Closed before the agents started.",
}


def _why(run: AgentRun | None) -> str:
    """The first sentence of an agent's reason, readable without the rest."""
    if run is None:
        return "has not checked this ticket yet."
    answer = run.output.get("answer") or {}
    reason = (answer.get("reason") or run.output.get("reason") or "").strip()
    return reason.split(". ")[0].rstrip(".") + "." if reason else ""


def _missing(run: AgentRun) -> list[str]:
    return [*run.output.get("missing", []), *(run.output.get("answer") or {}).get("missing", [])]


def headline(ticket: Ticket) -> tuple[str, str]:
    """The panel colour and the heading of a comment about where a ticket stands."""
    status = ticket.pipeline_status
    if status == PipelineStatus.AWAITING_INFO:
        return "warning", "More details needed"
    if status == PipelineStatus.REJECTED:
        return "note", "Not an incident"
    if status == PipelineStatus.ERROR:
        return "error", "An agent failed"
    if status == PipelineStatus.DQ_PASSED:
        return "info", "Details complete"
    if status == PipelineStatus.REVIEWED:
        db = object_session(ticket)
        final = db and db.scalar(select(Review.final_priority).where(Review.ticket_id == ticket.id, Review.agent == "triage")
                                 .order_by(Review.id.desc()).limit(1))
        return "success", f"Priority decided: P{final}" if final else "Priority decided"
    if status == PipelineStatus.TRIAGED:
        run = last_run(ticket, "triage")
        priority = run.output.get("priority") if run else None
        return ("info", f"Recommended priority: P{priority}") if priority else ("warning", "Priority unclear")
    return "info", "Working on it"


def agent_summary(ticket: Ticket, only: str | None = None, title: str | None = None) -> str:
    """What the agents decided on a ticket, as the text of a Jira comment: a heading and what to do next.
    `only` ("data_quality" or "triage") gives that agent's result instead."""
    lines = [f"{SAID}{title or headline(ticket)[1]}"]
    if only:
        run = last_run(ticket, only)
        verdict = run.verdict.replace("_", " ") if run else "not run"
        return "\n".join([*lines, f"{AGENTS[only]}: {verdict}", f"Why: {_why(run)}"])
    status, dq, triage = ticket.pipeline_status, last_run(ticket, "data_quality"), last_run(ticket, "triage")
    if status == PipelineStatus.AWAITING_INFO:
        missing = _missing(dq) or [_why(dq)]
        lines += ["Please add these to the description or as a comment:", *(f"- {m[:1].upper()}{m[1:]}" for m in missing),
                  "The agents check again on their own."]
    elif status == PipelineStatus.REJECTED:
        lines += [f"Why: {_why(dq)}", "If something is broken, describe it here and the agents check again."]
    elif status == PipelineStatus.DQ_PASSED:  # Triage has not run yet, so Jira still hears that the details are fine
        lines += [f"Data Quality: complete. {_why(dq)}", NEXT[status]]
    elif status == PipelineStatus.TRIAGED:
        lines += [f"Data Quality: complete. {_why(dq)}", f"Why: {_why(triage)}"]
        if triage and triage.output.get("priority"):
            if ticket.reported_priority and ticket.reported_priority != triage.output["priority"]:
                lines.append(f"Reported as: P{ticket.reported_priority}")
            lines.append("Next: an engineer confirms it. Reply `ams agree` to accept, or set another priority here.")
        else:
            lines.append("Next: set the priority on this issue.")
    else:
        lines.append(NEXT.get(status, status))
    return "\n".join(lines)


def _to_agents(text: str) -> bool:
    """A comment written to the agents ("/ams ...", or a short "ams ..." such as a mistyped "ams agre"), not a reply
    about the problem."""
    words = text.lower().split()
    return (text.lower().startswith("/ams") or COMMAND.fullmatch(text.lower()) is not None
            or (0 < len(words) <= 3 and words[0] == "ams"))


async def _asked(c: Any, key: str) -> tuple[str | None, str] | None:
    """The newest command among an issue's last comments and who wrote it, or None when there is none or it already
    has its answer. The command is None for "/ams", else "dq", "triage", "agree", or "help" for anything else after "/ams".
    """
    newest = {"orderBy": "-created", "maxResults": 20}
    data = await atlassian.call(c, "GET", f"/rest/api/3/issue/{key}/comment", params=newest)
    for comment in data["comments"]:
        text = adf_text(comment["body"]).strip()
        if text.startswith((SAID, EARLIER[0])):
            return None
        if _to_agents(text):
            asked = COMMAND.fullmatch(text.lower())
            return (asked.group(1) if asked else "help"), (comment.get("author") or {}).get("displayName") or "Someone in Jira"
    return None


async def _agree(db: AsyncSession, ticket: Ticket, who: str) -> tuple[str, str] | None:
    """ "/ams agree": the recommended priority becomes the decision, on the Jira issue too. Only for an open ticket that
    still waits for a decision. Returns the new priority's name and who accepted it, for the answer."""
    if ticket.pipeline_status != PipelineStatus.TRIAGED or ticket.closed_at is not None:
        return None
    recommended = await db.run_sync(lambda s: last_run(ticket, "triage").output["priority"])
    if recommended is None:
        return None
    changed = recommended != ticket.reported_priority
    if changed:
        await set_priority(ticket.id, recommended)
    await db.run_sync(lambda s: triage_review.review(s, ticket, "accepted", who))
    name = next(n for n, p in PRIORITY_NUMBER.items() if p == recommended)
    was = f" (was {ticket.reported_priority_label})" if changed else " (as reported)"
    return name, f"Accepted by: {who}{was}"


def _announcement(ticket: Ticket) -> tuple[str, str]:
    """The comment and the label for a ticket the agents just decided on."""
    if ticket.pipeline_status == PipelineStatus.AWAITING_INFO:
        return agent_summary(ticket), "ams-needs-info"
    if ticket.pipeline_status == PipelineStatus.REJECTED:
        return agent_summary(ticket), "ams-not-incident"
    if ticket.pipeline_status == PipelineStatus.DQ_PASSED:
        return agent_summary(ticket), "ams-dq-passed"
    run = last_run(ticket, "triage")
    return agent_summary(ticket), f"ams-{run.verdict.lower()}" if run and run.output.get("priority") else "ams-uncertain"


async def announce(db: AsyncSession, since: datetime) -> int:
    """Say on each open Jira issue what the agents decided since `since`, without waiting for a person: a comment (the
    question to the reporter when details are missing; Jira mails the people on the issue), a label for the board, and
    a copy of the comment on the ticket. Returns how many issues were told.

    shortcut: a comment Jira refuses is not sent again ("/ams" on the issue asks for it); queue them if that happens.
    """
    if not agent_writes():
        return 0
    say = (PipelineStatus.AWAITING_INFO, PipelineStatus.DQ_PASSED, PipelineStatus.TRIAGED, PipelineStatus.REJECTED)
    tickets = (await db.scalars(
        select(Ticket).where(Ticket.source == "JIRA", Ticket.closed_at.is_(None), Ticket.pipeline_status.in_(say),
                             Ticket.id.in_(select(AgentRun.ticket_id).where(AgentRun.created_at >= since)))
        .options(selectinload(Ticket.agent_runs))
    )).all()
    await db.commit()  # no transaction open while Jira answers
    told = 0
    if not tickets:
        return told
    async with atlassian.client() as c:
        for ticket in tickets:
            text, label = _announcement(ticket)
            labels = [*({"remove": other} for other in LABELS if other != label), {"add": label}]
            try:
                await post_comment(ticket.id, text, c, tone=headline(ticket)[0])
                await atlassian.call(c, "PUT", f"/rest/api/3/issue/{ticket.id}", json={"update": {"labels": labels}})
            except AtlassianError as exc:
                logger.warning("Agents' verdict on %s not fully written to Jira: %s", ticket.id, exc)
                continue
            await db.run_sync(add_comment, ticket, AGENTS_BOT, plain(text))
            told += 1
    return told


async def _runbooks(db: AsyncSession, kb_ids: set[str]) -> dict[str, str]:
    """Each runbook id as "[title](Confluence page)", or its title when the page is not known."""
    if not kb_ids:
        return {}
    rows = await db.execute(
        select(KBChunk.kb_id, KBChunk.title, ConfluencePage.url).distinct(KBChunk.kb_id)
        .outerjoin(ConfluencePage, KBChunk.source_path == func.concat("confluence-", ConfluencePage.id, ".md"))
        .where(KBChunk.kb_id.in_(kb_ids)).order_by(KBChunk.kb_id))
    return {kb_id: f"[{title}]({url})" if url else title for kb_id, title, url in rows}


ACTIONS = ("escalate", "notify", "contact", "raise", "assign", "route", "engage", "page ")  # how the agent's advice starts


def _resolution_text(ticket: Ticket, runbooks: dict[str, str]) -> tuple[str, str]:
    """The Resolution agent's answer as the text and the tone of a Jira comment."""
    a = last_run(ticket, "resolution").output
    if a.get("verdict") != "resolved":
        sentences = re.split(r"(?<=\.)\s+", (a.get("notes") or "").strip())
        advice = next((s.rstrip(".") for s in sentences if s.lower().startswith(ACTIONS)), None)  # "Escalate to ..."
        lines = [f"{SAID}No known fix", "Why: no runbook covers this problem.",
                 f"Next: {advice[:1].lower()}{advice[1:]}." if advice else "Next: an engineer investigates."]
        return "\n".join(lines), "warning"
    lines = [f"{SAID}Suggested fix",
             *([f"Likely cause: {a['root_cause']}"] if a.get("root_cause") else []),
             "Steps:", *(f"{n}. {s}" for n, s in enumerate(a.get("steps", []), 1)),
             f"Runbook: {', '.join(runbooks.get(r, r) for r in a.get('references', []))}",
             f"Confidence: {a.get('confidence', 'low')}",
             *([f"Note: {a['notes']}"] if a.get("notes") else [])]
    return "\n".join(lines), "success"


async def announce_resolution(db: AsyncSession, since: datetime) -> int:
    """Comment the Resolution agent's answer on each open Jira issue it answered since `since`. Returns how many."""
    if not agent_writes():
        return 0
    tickets = (await db.scalars(
        select(Ticket).where(Ticket.source == "JIRA", Ticket.closed_at.is_(None),
                             Ticket.id.in_(select(AgentRun.ticket_id).where(AgentRun.agent == "resolution",
                                                                             AgentRun.created_at >= since)))
        .options(selectinload(Ticket.agent_runs))
    )).all()
    runbooks = await _runbooks(db, {r for t in tickets for r in last_run(t, "resolution").output.get("references", [])})
    await db.commit()  # no transaction open while Jira answers
    told = 0
    if not tickets:
        return told
    async with atlassian.client() as c:
        for ticket in tickets:
            text, tone = _resolution_text(ticket, runbooks)
            try:
                await post_comment(ticket.id, text, c, tone=tone)
            except AtlassianError as exc:
                logger.warning("Resolution for %s not written to Jira: %s", ticket.id, exc)
                continue
            await db.run_sync(add_comment, ticket, AGENTS_BOT, plain(text))
            told += 1
    return told


def _closure_text(ticket: Ticket) -> str:
    """Closure Quality's ask on a done issue whose notes need work: what is missing, and notes to start from."""
    o = last_run(ticket, "closure_quality").output
    lines = [f"{SAID}Close notes need work", *(f"- {q}" for q in o.get("questions") or [])]
    if o.get("draft_notes"):
        lines += ["Suggested close notes, from what is already on this issue (fill in anything in brackets):",
                  o["draft_notes"]]
    lines.append("Next: reply here with the completed close notes; the agents check them again.")
    return "\n".join(lines)


async def announce_closure(db: AsyncSession, since: datetime) -> int:
    """Comment on each done Jira issue whose close notes Closure Quality found lacking since `since`. Returns how many."""
    if not agent_writes():
        return 0
    tickets = [t for t in (await db.scalars(
        select(Ticket).where(Ticket.source == "JIRA", Ticket.status == "closed",  # history closed before the agents: left alone
                             Ticket.pipeline_status != PipelineStatus.HISTORICAL,
                             Ticket.id.in_(select(AgentRun.ticket_id).where(AgentRun.agent == "closure_quality",
                                                                             AgentRun.created_at >= since)))
        .options(selectinload(Ticket.agent_runs))
    )).all() if last_run(t, "closure_quality").verdict == "needs_work"]
    await db.commit()  # no transaction open while Jira answers
    told = 0
    if not tickets:
        return told
    async with atlassian.client() as c:
        for ticket in tickets:
            text = _closure_text(ticket)
            try:
                await post_comment(ticket.id, text, c, tone="warning")
            except AtlassianError as exc:
                logger.warning("Closure Quality for %s not written to Jira: %s", ticket.id, exc)
                continue
            await db.run_sync(add_comment, ticket, AGENTS_BOT, plain(text))
            told += 1
    return told


async def answer_commands(db: AsyncSession) -> int:
    """Answer "/ams", "/ams dq", "/ams triage" or "/ams agree" written as a comment on a Jira issue: run the agents if
    the ticket still waits for them, record the agreement, then comment what they decided and keep a copy on the ticket.
    Anything else after "/ams" gets the list of commands. Returns how many were answered.

    shortcut: polled with the scheduled sync over recently changed issues; a Jira webhook needs a public server address.
    """
    keys = list(await db.scalars(select(JiraProject.key)))
    if not keys:
        return 0
    asked = {}
    if issues := await search_issues(keys, settings.JIRA_SYNC_MINUTES + 10):
        async with atlassian.client() as c:  # one connection for all of them
            for issue in issues:
                if (command := await _asked(c, issue["key"])) is not None:
                    asked[issue["key"]] = command
    if not asked or agents_lock.locked():  # a pass is running: answer on the next round
        return 0
    await run_agents()
    db.expire_all()  # the agents wrote through their own connection
    answered = 0
    for key, (command, who) in asked.items():
        ticket = await db.get(Ticket, key)
        if ticket is None:  # not pulled yet: the next sync brings it, the round after answers
            continue
        done = await _agree(db, ticket, who) if command == "agree" else None
        only = {"dq": "data_quality", "triage": "triage"}.get(command)
        if command == "help":
            text, tone = f"{SAID}Commands\n{help_text()}", "note"
        else:
            title = f"Priority set to {done[0]}" if done else None
            text = await db.run_sync(lambda s, t=ticket, o=only, h=title: agent_summary(t, o, h))
            tone = "success" if done else await db.run_sync(lambda s, t=ticket: headline(t)[0])
        if done:
            text = f"{text}\n{done[1]}"
        await post_comment(key, text, tone=tone)
        await db.run_sync(add_comment, ticket, COMMAND_BOT, plain(text))
        answered += 1
    return answered


async def schedule_loop(session_factory) -> None:
    """Sync every JIRA_SYNC_MINUTES (0 = off) while the app runs, and send new tickets to the agents."""
    waited = 0
    while True:
        await asyncio.sleep(60)
        waited += 1
        if not settings.JIRA_SYNC_MINUTES or waited < settings.JIRA_SYNC_MINUTES:
            continue
        waited = 0
        try:
            async with session_factory() as db:
                run = await run_sync(db, "schedule")
            if run.queued:
                start_agents()
            if settings.SLA_AUTO_WARN and agent_writes():
                async with session_factory() as db:
                    await send_sla_warnings(db)
            if agent_writes():
                async with session_factory() as db:
                    await answer_commands(db)
            resolved_from = datetime.now(UTC)
            await run_resolution()  # reviewed tickets get their fix without a person pressing Run; unchanged ones skip
            async with session_factory() as db:
                await announce_resolution(db, resolved_from)
        except JiraError as exc:
            logger.info("Scheduled Jira sync skipped: %s", exc)
        except Exception:
            logger.exception("Scheduled Jira sync failed")  # keep the loop alive
