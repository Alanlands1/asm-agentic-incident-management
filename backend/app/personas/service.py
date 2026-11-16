"""One board for every persona page: the open tickets with the priority in force, SLA state, engineer and Jira link.

P1/P2 and SLA come from the same functions Incidents uses, so the pages cannot disagree. Read-only: assigning is done
in Jira, through the ticket's link.
"""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.agents.triage.config import get_config
from app.agents.triage.rules import find_rule
from app.core.config import settings
from app.models.incident import FirstMessage
from app.models.jira import JiraSync
from app.models.ticket import AgentRun, Comment, PipelineStatus, Review, Ticket
from app.services.data_quality import AGENT as DATA_QUALITY
from app.services.jira import COMMAND_BOT, SAID, SLA_BOT
from app.services.triage import sla
from app.services.triage.run import AGENT as TRIAGE

TRIAGED = (PipelineStatus.TRIAGED, PipelineStatus.REVIEWED)
KB_ID = re.compile(r"KB-[A-Z]+-\d+")


def _utc(at: datetime) -> datetime:
    """Ticket times are naive UTC, and SQLite drops the zone."""
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _runbook(output: dict) -> str | None:
    """The runbook of the rule Triage matched; when the rule is gone from the rulebook, the id its reason names."""
    rule = find_rule(get_config(), output.get("application"), output.get("rule") or "")
    named = KB_ID.search(output.get("reason") or "")
    return getattr(rule, "kb", None) or (named.group() if named else None)


def board(db: Session, person: str | None = None, at: datetime | None = None) -> dict:
    """Open tickets, most at risk first, with totals and one line per engineer. `person` keeps only that engineer's."""
    at = at or sla.now()
    query = select(Ticket).where(Ticket.closed_at.is_(None), Ticket.pipeline_status != PipelineStatus.HISTORICAL)
    if person:
        query = query.where(Ticket.assignee == person)
    tickets = db.scalars(query.options(selectinload(Ticket.agent_runs))).all()
    working = sla.working_priorities(db, [t for t in tickets if t.pipeline_status in TRIAGED])
    urgent = {i.ticket.id: i.sla for i in sla.open_p1_p2(db, at)}
    site = settings.ATLASSIAN_BASE_URL.rstrip("/")

    rows, people = [], {}
    for t in tickets:
        priority, source, run = working.get(t.id, (None, None, None))
        asked = next((r for r in reversed(t.agent_runs) if r.agent == DATA_QUALITY and r.output.get("stage") == "model"), None)
        answer = (asked.output.get("answer") or {}) if asked else {}
        status = urgent.get(t.id)
        row = {
            "id": t.id, "summary": t.summary, "application": t.application, "priority": priority,
            "priority_from": source, "sla_state": status.state if status else None,
            "minutes_left": status.minutes_left if status else None,
            "used_percent": round(status.used * 100) if status else None, "assignee": t.assignee,
            "team": t.assignment_group, "stage": t.pipeline_status, "opened_at": t.opened_at,
            "url": f"{site}/browse/{t.id}" if site and t.source == "JIRA" else None,
            "triage_reason": run.output.get("reason") if run else None, "reported_priority": t.reported_priority,
            "missing": answer.get("missing", []), "has_draft": bool(answer.get("chase_email")),
            "due_at": _utc(status.due_at) if status else None, "runbook": _runbook(run.output) if run else None,
        }
        rows.append(row)
        p = people.setdefault(t.assignee, {"name": t.assignee, "open": 0, "p1_p2": 0, "breached": 0, "waiting_review": 0})
        p["open"] += 1
        p["p1_p2"] += t.id in urgent
        p["breached"] += row["sla_state"] == "breached"
        p["waiting_review"] += t.pipeline_status == PipelineStatus.TRIAGED

    rows.sort(key=lambda r: (sla.SEVERITY.get(r["sla_state"], 4), r["priority"] or 9, r["opened_at"] or datetime.max))
    return {
        "at": at,
        "totals": {
            "open": len(rows),
            "p1_p2": sum(p["p1_p2"] for p in people.values()),
            "sla_breached": sum(p["breached"] for p in people.values()),
            "sla_at_risk": sum(r["sla_state"] == "breach_likely" for r in rows),
            "waiting_review": sum(p["waiting_review"] for p in people.values()),
            "unassigned": people.get(None, {}).get("open", 0),
        },
        "people": sorted(people.values(), key=lambda p: (p["name"] is None, -p["open"])),
        "tickets": rows,
    }


def activity(db: Session, person: str | None = None, since: datetime | None = None, limit: int = 20) -> list[dict]:
    """What the agents and people did since `since`, newest first. `person` keeps only that engineer's tickets.

    Events of one kind in the same minute are one item that lists the tickets. A failed Jira sync is for everyone,
    once per error however often it repeated.
    """
    since = _utc(since).astimezone(UTC) if since else datetime.now(UTC) - timedelta(days=1)
    mine = [Ticket.assignee == person] if person else []

    def recent(model, when, *where):
        return db.scalars(select(model).join(Ticket, Ticket.id == model.ticket_id).where(when >= since, *mine, *where))

    events = []  # (when, kind, ticket id, what the sentence needs besides the tickets)
    agents = AgentRun.agent.in_((DATA_QUALITY, TRIAGE))
    ran = {r.ticket_id for r in recent(AgentRun, AgentRun.created_at, agents)}
    passes: dict[tuple[str, str], list[AgentRun]] = {}  # (ticket, agent) -> the last run of each pass, oldest first
    for run in db.scalars(select(AgentRun).where(AgentRun.ticket_id.in_(ran), agents).order_by(AgentRun.created_at, AgentRun.id)):
        done = passes.setdefault((run.ticket_id, run.agent), [])
        if done and run.input_hash and done[-1].input_hash == run.input_hash:
            done[-1] = run  # the model's answer after the rules were uncertain: one pass
        else:
            done.append(run)
    for (ticket_id, agent), done in passes.items():
        for i, run in enumerate(done):
            if _utc(run.created_at) < since:
                continue
            if agent == TRIAGE and i:
                before = next((p.output.get("priority") for p in reversed(done[:i]) if p.output.get("priority")), None)
                events.append((run.created_at, "triage_rerun", ticket_id,
                               {"priority": run.output.get("priority"), "previous_priority": before}))
            else:
                events.append((run.created_at, agent, ticket_id, {}))

    bots = {SLA_BOT: "sla_warning", COMMAND_BOT: "summary_sent"}
    for c in recent(Comment, Comment.created_at, or_(Comment.author_email.in_(bots), Comment.body.startswith(SAID))):
        events.append((c.created_at, bots.get(c.author_email, "summary_sent"), c.ticket_id,
                       {} if c.author_email in bots else {"actor": c.author_email}))
    for m in recent(FirstMessage, FirstMessage.sent_at):
        events.append((m.sent_at, "first_message", m.ticket_id, {"actor": m.sent_by}))
    for r in recent(Review, Review.created_at):
        events.append((r.created_at, "review", r.ticket_id,
                       {"actor": r.reviewer, "action": r.action, "priority": r.final_priority}))
    for s in db.scalars(select(JiraSync).where(JiraSync.started_at >= since, JiraSync.error.is_not(None))):
        events.append((s.started_at, "sync_failed", None, {"error": s.error}))

    items: dict[tuple, dict] = {}
    for when, kind, ticket_id, details in events:
        when = _utc(when)
        key = (kind, when.replace(second=0, microsecond=0) if ticket_id else None, *details.values())
        item = items.setdefault(key, {"at": when, "kind": kind, "ticket_ids": set(), **details})
        item["at"] = max(item["at"], when)
        item["ticket_ids"] |= {ticket_id} if ticket_id else set()
    for item in items.values():
        item["ticket_ids"] = sorted(item["ticket_ids"], key=lambda i: (len(i), i))  # AMS-9 before AMS-16
    return sorted(items.values(), key=lambda i: i["at"], reverse=True)[:limit]
