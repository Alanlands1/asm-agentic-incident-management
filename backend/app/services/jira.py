"""Pull issues from Jira Cloud and hand new ones to the agents.

Each issue is written twice: to servicenow_tickets (what the console pages and DQ rules read) and to tickets
(what the Data Quality and Triage agents read). Read-only towards Jira, except post_comment and
set_priority, which a person triggers, send_sla_warnings, which the scheduler runs when SLA_AUTO_WARN is on,
answer_commands, which answers a person who wrote "/ams" on the issue, announce, which comments and labels an issue
with what the agents decided, and move_triaged, which takes an issue out of the backlog once the agents have triaged it.
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.jira import JiraProject, JiraSync
from app.models.servicenow import ServiceNowTicket
from app.models.ticket import AgentRun, Comment, PipelineStatus, Review, Ticket
from app.privacy.masking import Masker
from app.services import atlassian
from app.services.atlassian import AtlassianError
from app.services.comments import add_comment
from app.services.data_quality import last_run, run_data_quality
from app.services.resolution import run_resolution
from app.services.triage import review as triage_review
from app.services.triage import run_triage, sla

logger = logging.getLogger("app.jira")

# Same labels the ServiceNow sheet uses, so priority chips and DQ rules work unchanged.
PRIORITY = {"Highest": "1 - Critical", "High": "2 - High", "Medium": "3 - Moderate", "Low": "4 - Low", "Lowest": "5 - Planning"}
FIELDS = [
    "summary", "description", "priority", "status", "reporter", "assignee", "components", "issuetype", "environment",
    "created", "resolutiondate", "project",
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
    return [t for t in texts if t and not t.startswith((SAID, "Automatic SLA warning")) and not _to_agents(t)]


async def post_comment(key: str, text: str, c: Any = None) -> None:
    """Add a comment to a Jira issue, as the owner of the API token."""
    if not settings.JIRA_WRITE_BACK:
        raise AtlassianError("Writing to Jira is switched off: set JIRA_WRITE_BACK=true in backend/.env")
    lines = [{"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []} for line in text.splitlines()]
    # an info panel marks the comment as the system's: Jira shows it under the token owner's name
    panel = {"type": "panel", "attrs": {"panelType": "info"}, "content": lines}
    async with _jira(c) as c:
        await atlassian.call(
            c, "POST", f"/rest/api/3/issue/{key}/comment", json={"body": {"type": "doc", "version": 1, "content": [panel]}}
        )


async def set_priority(key: str, priority: int, c: Any = None) -> None:
    """Set a Jira issue's priority to the reviewed one (1 Highest .. 5 Lowest), as the owner of the API token."""
    if not settings.JIRA_WRITE_BACK:
        raise AtlassianError("Writing to Jira is switched off: set JIRA_WRITE_BACK=true in backend/.env")
    name = next(n for n, p in PRIORITY_NUMBER.items() if p == priority)
    async with _jira(c) as c:
        await atlassian.call(c, "PUT", f"/rest/api/3/issue/{key}", json={"fields": {"priority": {"name": name}}})


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
            masker = _mask(r, "reporter_name", "reporter_email", ("summary", "description"))
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
            for k, v in r.items():  # agent results are kept, and the pipeline status unless set just above
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
        db.add(run)
        await db.commit()
        logger.info(
            "Jira sync %s: pulled=%s created=%s updated=%s queued=%s", run.id, run.pulled, run.created, run.updated, run.queued
        )
        return run


TRIAGED_STATUS = "Selected for development"  # where a triaged issue goes; an issue that cannot go there is left alone
TRIAGE_DONE = (PipelineStatus.TRIAGED, PipelineStatus.REVIEWED)
RECHECK = (PipelineStatus.AWAITING_INFO, PipelineStatus.REJECTED)  # an edit or a reporter's reply sends these back to the agents
IN_JIRA = "Set in Jira"  # the reviewer of a decision a person made on the issue itself


async def move_triaged(db: AsyncSession) -> int:
    """Move the Jira issues the agents have triaged out of the backlog, as the owner of the API token. Only an issue
    whose status never changed is moved, so once at most: one a person moved, also back to the backlog, stays where
    they put it. Returns how many were moved.

    shortcut: reads the newest 100 changes of an issue; page the changelog if issues get busier than that.
    """
    if not settings.JIRA_WRITE_BACK:
        return 0
    tickets = (await db.scalars(
        select(Ticket).where(Ticket.source == "JIRA", Ticket.status == "new", Ticket.pipeline_status.in_(TRIAGE_DONE))
    )).all()
    await db.commit()  # no transaction open while Jira answers
    moved = 0
    try:
        async with atlassian.client() as c:
            for ticket in tickets:
                history = {"fields": "status", "expand": "changelog"}
                issue = await atlassian.call(c, "GET", f"/rest/api/3/issue/{ticket.id}", params=history)
                if any(i["field"] == "status" for h in issue["changelog"]["histories"] for i in h["items"]):
                    continue  # the status set in Jira is final
                url = f"/rest/api/3/issue/{ticket.id}/transitions"
                steps = (await atlassian.call(c, "GET", url))["transitions"]
                step = next((s for s in steps if s["to"]["name"].casefold() == TRIAGED_STATUS.casefold()), None)
                if step is None:
                    continue
                await atlassian.call(c, "POST", url, json={"transition": {"id": step["id"]}})
                ticket.status, ticket.source_status = "in_progress", step["to"]["name"]  # what the next sync would bring
                moved += 1
    except AtlassianError as exc:  # the rest is moved after the next agent pass
        logger.warning("Triaged issues not moved in Jira: %s", exc)
    await db.commit()
    return moved


def _agents_in_thread() -> None:
    """Data Quality, then Triage, in a worker thread with its own event loop and database engine.

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
        finally:
            await engine.dispose()

    asyncio.run(run())


async def run_agents() -> None:
    """One agent pass at a time; a sync that finds new tickets while one runs leaves them for the next pass."""
    if agents_lock.locked():
        return
    async with agents_lock:
        try:
            await asyncio.to_thread(_agents_in_thread)
        except Exception:
            logger.exception("Agents after Jira sync failed")


def start_agents() -> None:
    task = asyncio.create_task(run_agents())
    _background.add(task)
    task.add_done_callback(_background.discard)


SLA_BOT = "AMS system (SLA warning)"


USED = re.compile(r"\((\d+)% of the target is used\)")  # in every warning; the stored copies tell which level was sent


def _levels() -> tuple[int, ...]:
    """Warning levels as a share of the SLA target, in percent: watch, breach likely, breached (the console's states)."""
    cfg = sla.config()
    return (round(cfg.watch_at * 100), round(cfg.breach_likely_at * 100), 100)


def _step(percent: int, levels: tuple[int, ...]) -> int:
    """The highest level this share of the target has reached, 0 below the first."""
    return max((p for p in levels if percent >= p), default=0)


def _due_warnings(db: Session) -> list[tuple[Ticket, str]]:
    """Open P1/P2 Jira tickets that reached a warning level since their last warning, each with its text."""
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
            when = (f"breached its SLA at {due_at}, {-i.sla.minutes_left} minutes ago" if used >= 100
                    else f"is due by {due_at}, {i.sla.minutes_left} minutes from now")
            due.append((i.ticket, f"Automatic SLA warning: this P{i.priority} ticket {when} ({used}% of the target is used). "
                                  f"Assigned to {i.ticket.assignee or 'nobody'}."))
    return due


async def send_sla_warnings(db: AsyncSession) -> int:
    """Comment on a Jira issue when it reaches watch, breach likely and the breach of its SLA target (Jira then mails
    the people on the issue), and keep a copy on the ticket. Returns how many comments were sent.
    """
    due = await db.run_sync(_due_warnings)
    for ticket, text in due:
        await post_comment(ticket.id, text)
        await db.run_sync(add_comment, ticket, SLA_BOT, text)  # the copy is what stops the same warning twice
    return len(due)


COMMAND = re.compile(r"/?ams\s*(dq|triage|agree)?")  # the whole comment: "/ams", "/ams dq", "ams triage", "/ams agree"
COMMAND_BOT = "AMS system (asked in Jira)"
AGENTS_BOT = "AMS agents"  # author of the stored copy of what announce wrote on the issue
SAID = "AMS agents on "  # how every answer starts; a command with an answer after it is not answered again


def help_text() -> str:
    return ("Commands, each as a whole comment (the slash is optional, so Jira's menu stays closed): ams (what the agents "
            "decided), ams dq or ams triage (one agent), ams agree (accept the recommended priority). "
            f"Answered on the next sync, within about {settings.JIRA_SYNC_MINUTES} min.")


LABELS = ["ams-needs-info", "ams-not-incident", "ams-uncertain", *(f"ams-p{n}" for n in range(1, 6))]  # one at a time
AGENTS = {"data_quality": "Data Quality", "triage": "Triage"}
NEXT = {
    PipelineStatus.PENDING: "Waiting for the Data Quality agent.",
    PipelineStatus.AWAITING_INFO: "Next: the reporter gives the missing details.",
    PipelineStatus.DQ_PASSED: "Waiting for the Triage agent.",
    PipelineStatus.TRIAGED: "Next: an engineer reviews the recommended priority.",
    PipelineStatus.REVIEWED: "The priority is decided; the ticket is ready to be worked.",
    PipelineStatus.REJECTED: "Not an incident; nothing to do.",
    PipelineStatus.ERROR: "An agent failed; a person has to look.",
    PipelineStatus.HISTORICAL: "Closed before the agents started.",
}


def _said(run: AgentRun) -> str:
    o = run.output
    answer = o.get("answer") or {}
    verdict = f"recommends {run.verdict}" if run.verdict.startswith("P") else run.verdict.replace("_", " ")
    missing = [*o.get("missing", []), *answer.get("missing", [])]
    return f"{verdict}. {o.get('reason') or answer.get('reason') or ''}" + (f" Missing: {', '.join(missing)}." if missing else "")


def agent_summary(ticket: Ticket, only: str | None = None) -> str:
    """What the agents decided on a ticket, as the text of a Jira comment. `only` keeps one agent's line."""
    lines = [f"{SAID}{ticket.id}. {NEXT.get(ticket.pipeline_status, ticket.pipeline_status)}"]
    for agent, name in AGENTS.items():
        if only in (None, agent):
            run = last_run(ticket, agent)
            lines.append(f"{name}: {_said(run) if run else 'has not checked this ticket yet.'}")
    return "\n".join(lines)


def _to_agents(text: str) -> bool:
    """A comment written to the agents ("/ams ..."), not a reply about the problem."""
    return text.lower().startswith("/ams") or COMMAND.fullmatch(text.lower()) is not None


async def _asked(c: Any, key: str) -> tuple[str | None, str] | None:
    """The newest command among an issue's last comments and who wrote it, or None when there is none or it already
    has its answer. The command is None for "/ams", else "dq", "triage", "agree", or "help" for anything else after "/ams".
    """
    newest = {"orderBy": "-created", "maxResults": 20}
    data = await atlassian.call(c, "GET", f"/rest/api/3/issue/{key}/comment", params=newest)
    for comment in data["comments"]:
        text = adf_text(comment["body"]).strip()
        if text.startswith(SAID):
            return None
        if _to_agents(text):
            asked = COMMAND.fullmatch(text.lower())
            return (asked.group(1) if asked else "help"), (comment.get("author") or {}).get("displayName") or "Someone in Jira"
    return None


async def _agree(db: AsyncSession, ticket: Ticket, who: str) -> str | None:
    """ "/ams agree": the recommended priority becomes the decision, on the Jira issue too. Only for an open ticket that
    still waits for a decision. Returns what changed, for the answer."""
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
    was = f", was {ticket.reported_priority_label}." if changed else ", as reported."
    return f"{who} agreed: the priority is now {name}{was}"


def _announcement(ticket: Ticket) -> tuple[str, str]:
    """The comment and the label for a ticket the agents just decided on."""
    if ticket.pipeline_status == PipelineStatus.AWAITING_INFO:
        answer = last_run(ticket, "data_quality").output.get("answer") or {}
        ask = answer.get("chase_email") or (
            "Please add the missing details to this issue, in the description or as a comment. "
            "The agents check again on their own.")
        return f"{agent_summary(ticket, 'data_quality')}\n\n{ask}", "ams-needs-info"
    if ticket.pipeline_status == PipelineStatus.REJECTED:
        again = "If something is broken, describe it on this issue and the agents check again."
        return f"{agent_summary(ticket, 'data_quality')}\n\n{again}", "ams-not-incident"
    run = last_run(ticket, "triage")
    accept = "To accept this priority, comment ams agree. To decide another one, set" if run.output["priority"] else "Set"
    return (f"{agent_summary(ticket)}\n\n{accept} the priority on this issue: what is set in Jira is final.",
            f"ams-{run.verdict.lower()}" if run.output["priority"] else "ams-uncertain")


async def announce(db: AsyncSession, since: datetime) -> int:
    """Say on each open Jira issue what the agents decided since `since`, without waiting for a person: a comment (the
    question to the reporter when details are missing; Jira mails the people on the issue), a label for the board, and
    a copy of the comment on the ticket. Returns how many issues were told.

    shortcut: a comment Jira refuses is not sent again ("/ams" on the issue asks for it); queue them if that happens.
    """
    if not settings.JIRA_WRITE_BACK:
        return 0
    say = (PipelineStatus.AWAITING_INFO, PipelineStatus.TRIAGED, PipelineStatus.REJECTED)
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
                await post_comment(ticket.id, text, c)
                await atlassian.call(c, "PUT", f"/rest/api/3/issue/{ticket.id}", json={"update": {"labels": labels}})
            except AtlassianError as exc:
                logger.warning("Agents' verdict on %s not fully written to Jira: %s", ticket.id, exc)
                continue
            await db.run_sync(add_comment, ticket, AGENTS_BOT, text)
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
            text = f"{SAID}{key}. {help_text()}"
        else:
            text = await db.run_sync(lambda s, t=ticket, o=only: agent_summary(t, o))
        if done:
            text = f"{text}\n{done}"
        await post_comment(key, text)
        await db.run_sync(add_comment, ticket, COMMAND_BOT, text)
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
            if settings.SLA_AUTO_WARN and settings.JIRA_WRITE_BACK:
                async with session_factory() as db:
                    await send_sla_warnings(db)
            if settings.JIRA_WRITE_BACK:
                async with session_factory() as db:
                    await answer_commands(db)
            await run_resolution()  # reviewed tickets get their fix without a person pressing Run; unchanged ones skip
        except JiraError as exc:
            logger.info("Scheduled Jira sync skipped: %s", exc)
        except Exception:
            logger.exception("Scheduled Jira sync failed")  # keep the loop alive
