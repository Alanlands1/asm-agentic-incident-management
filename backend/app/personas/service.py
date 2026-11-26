"""One board for every persona page: the open tickets with the priority in force, SLA state, engineer and Jira link.

P1/P2 and SLA come from the same functions Incidents uses, so the pages cannot disagree. Read-only: the lead assigns
through POST /tickets/{id}/assign.
"""

import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.agents.triage.config import get_config
from app.agents.triage.rules import find_rule
from app.core.config import settings
from app.models.incident import FirstMessage
from app.models.jira import JiraSync
from app.models.knowledge import ResolvedCase
from app.models.ticket import AgentRun, Comment, Feedback, PipelineStatus, Review, Ticket
from app.personas import availability
from app.services import jira, lead_review
from app.services.data_quality import AGENT as DATA_QUALITY
from app.services.data_quality import last_run
from app.services.jira import COMMAND_BOT, EARLIER, SAID, SLA_BOT
from app.services.triage import sla
from app.services.triage.run import AGENT as TRIAGE

TRIAGED = sla.TRIAGED
FIX = "resolution"
RECENT = 90  # days of resolved tickets that count as knowing an application
ROOM = 3  # open tickets an engineer who knows the application may hold above the least loaded one and still get it
ASSIGNMENT = "assignment"  # an agent_runs row per assignment: who gave the ticket to whom
AUTO = "AMS agents (auto)"  # services/triage/run.AUTO_REVIEWER
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
    ids = [t.id for t in tickets]
    steps: dict[tuple[str, str], Review] = {}  # (ticket, agent) -> the latest fix answer or lead review step
    for r in db.scalars(select(Review).where(Review.ticket_id.in_(ids), Review.agent.in_((FIX, lead_review.AGENT)))
                        .order_by(Review.id)):
        steps[(r.ticket_id, r.agent if r.agent == lead_review.AGENT else f"{FIX}:{r.agent_run_id}")] = r
    rated = set(db.scalars(select(Feedback.agent_run_id).where(Feedback.ticket_id.in_(ids), Feedback.agent == FIX)))

    rows, people = [], {}
    for t in tickets:
        priority, source, run = working.get(t.id, (None, None, None))
        asked = next((r for r in reversed(t.agent_runs) if r.agent == DATA_QUALITY and r.output.get("stage") == "model"), None)
        answer = (asked.output.get("answer") or {}) if asked else {}
        status = urgent.get(t.id)
        row = {
            "id": t.id, "summary": t.summary, "application": _application(t), "priority": priority,
            "priority_from": source, "sla_state": status.state if status else None,
            "minutes_left": status.minutes_left if status else None,
            "used_percent": round(status.used * 100) if status else None, "assignee": t.assignee,
            "team": t.assignment_group, "stage": t.pipeline_status, "opened_at": t.opened_at,
            "url": f"{site}/browse/{t.id}" if site and t.source == "JIRA" else None,
            "triage_reason": run.output.get("reason") if run else None, "reported_priority": t.reported_priority,
            "missing": answer.get("missing", []), "has_draft": bool(answer.get("chase_email")),
            "due_at": _utc(status.due_at) if status else None, "runbook": _runbook(run.output) if run else None,
            **_progress(db, t, steps, rated),
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


def people(db: Session) -> list[str]:
    """Every engineer a ticket was ever assigned to, by name."""
    return sorted(db.scalars(select(Ticket.assignee).where(Ticket.assignee.is_not(None)).distinct()))


def roster(db: Session) -> list[dict]:
    """Everyone a ticket can go to: who Jira lets be assigned, and who has held a ticket here. `member` says who is on
    the team, so gets suggestions and a shift status: whoever the lead put on it; else someone who has held a ticket,
    unless Jira no longer lets them be assigned; never someone the lead took off."""
    team, held, in_jira = availability.config(), set(people(db)), jira.known_people
    rows = []
    for name in sorted(held | set(in_jira or [])):
        known = None if in_jira is None else name in in_jira
        member = name not in team.not_members and (name in team.members or (name in held and known is not False))
        rows.append({"name": name, "in_jira": known, "held": name in held, "member": member})
    return rows


def members(db: Session) -> list[str]:
    return [r["name"] for r in roster(db) if r["member"]]


def _resolved(db: Session, at: datetime) -> Counter:
    """(application, person) -> tickets that person resolved in the last RECENT days: they confirmed the fix or sent
    the closure note here, or the ticket was closed in its source while assigned to them. A person is who the page or
    Jira named: a step recorded under an email address does not count for the same person's Jira name."""
    since = at - timedelta(days=RECENT)
    done = or_(and_(Review.agent == FIX, Review.action.in_(("worked", "partly"))), Review.agent == lead_review.CLOSE)
    pairs = {(r.ticket_id, r.reviewer) for r in db.scalars(select(Review).where(Review.created_at >= _utc(since), done))}
    undated = and_(Ticket.closed_at.is_(None), Ticket.pipeline_status == PipelineStatus.HISTORICAL)
    in_source = or_(Ticket.closed_at >= since, undated)
    closed = db.scalars(select(Ticket).where(Ticket.assignee.is_not(None), in_source)
                        .options(selectinload(Ticket.agent_runs))).all()
    pairs |= {(t.id, t.assignee) for t in closed}
    tickets = {t.id: t for t in closed}
    others = {i for i, _ in pairs} - set(tickets)
    for t in db.scalars(select(Ticket).where(Ticket.id.in_(others)).options(selectinload(Ticket.agent_runs))):
        tickets[t.id] = t
    counts: Counter = Counter()
    for ticket_id, person in pairs:
        app = _application(tickets[ticket_id]) if ticket_id in tickets else None
        if app:
            counts[(app, person)] += 1
    return counts


def suggestions(db: Session, at: datetime | None = None) -> list[dict]:
    """An engineer for each open ticket nobody has, most at risk first: of those who have resolved tickets of the
    ticket's application, the one with the fewest open tickets now; when nobody has, or they all hold more than ROOM
    tickets above the least loaded engineer, whoever has the fewest. Nobody on leave is suggested, and someone off
    shift only when nobody is on shift. Each suggestion counts as a ticket for the next one, so a batch spreads over
    the team. Nobody holding the team's max_open tickets gets another, so a ticket may get no suggestion; a P1 or P2
    goes over the limit rather than wait."""
    at = at or sla.now()
    rows = board(db, at=at)["tickets"]
    team = availability.config()
    state = {e: availability.status(e, at, team)["state"] for e in members(db)}
    here = [e for e, s in state.items() if s != availability.ON_LEAVE]
    engineers = [e for e in here if state[e] == availability.ON_SHIFT] or here
    holds = Counter(r["assignee"] for r in rows if r["assignee"])  # before this batch
    load = Counter(holds)
    resolved = _resolved(db, at)

    picked = []  # (ticket, engineer, what they know of the application, anything unusual about the pick)
    for r in rows:
        urgent = r["priority"] is not None and r["priority"] <= 2
        free = engineers if urgent else [e for e in engineers if load[e] < team.max_open]
        if r["assignee"] or not free:
            continue
        app = r["application"]
        room = min(load[e] for e in free) + ROOM
        pool = [e for e in free if resolved[(app, e)] and load[e] <= room] or free
        name = min(pool, key=lambda e: (load[e], -resolved[(app, e)], e))
        n = resolved[(app, name)]
        knows = f"resolved {n} {app} {'ticket' if n == 1 else 'tickets'}" if n else app and f"no resolved {app} tickets yet"
        flags = [len(engineers) < len(here) and "the only one on shift now" if len(engineers) == 1
                 else len(engineers) < len(here) and "others are off shift",
                 load[name] >= team.max_open and "over the limit, urgent",
                 state[name] == availability.OFF_SHIFT and "off shift now"]
        picked.append((r["id"], name, knows, flags))
        load[name] += 1
    return [{"id": ticket, "name": name, "reason": " · ".join(
        part for part in (knows, f"holds {holds[name]} now, {load[name]} after this batch", *flags) if part)}
            for ticket, name, knows, flags in picked]


def team_status(db: Session, at: datetime | None = None) -> dict[str, dict]:
    """Each team member's state now: on_shift, off_shift, or on_leave with its last day."""
    team = availability.config()
    return {e: availability.status(e, at or sla.now(), team) for e in members(db)}


def _application(t: Ticket) -> str | None:
    """The ticket's application, else the one Triage worked out (a mailbox ticket arrives without one)."""
    triage = last_run(t, TRIAGE)
    return t.application or (triage.output.get("application") if triage else None)


def _progress(db: Session, t: Ticket, steps: dict, rated: set) -> dict:
    """Where the agents and people are on one ticket: for the card, the next step and the viewer's tasks."""
    dq, fix, check = last_run(t, DATA_QUALITY), last_run(t, FIX), last_run(t, "closure_quality")
    answer = steps.get((t.id, f"{FIX}:{fix.id}")) if fix else None
    lead = steps.get((t.id, lead_review.AGENT))
    closing = t.pipeline_status in (PipelineStatus.FIX_CONFIRMED, PipelineStatus.IN_REVIEW, PipelineStatus.APPROVED)
    return {
        "dq_verdict": dq.verdict if dq else None,
        "fix_verdict": fix.verdict if fix else None,  # resolved: a fix was suggested; no_match: none found
        "fix_answer": answer.action if answer else None,  # worked, partly, wrong
        "fix_rated": bool(fix and fix.id in rated),
        "closure_verdict": check.verdict if check else None,
        "closure_score": check.output.get("score") if check else None,
        "lead_step": lead.action if lead else None,  # submitted, approved, sent_back
        "lead_by": lead.reviewer if lead else None,
        "review_required": closing and lead_review.required(db, t),
    }


def today(db: Session, since: datetime, person: str | None = None) -> dict:
    """What each agent did since `since` (the viewer's midnight), and how many tickets were opened and closed."""
    since = _utc(since).astimezone(UTC)
    mine = [Ticket.assignee == person] if person else []
    runs = db.scalars(select(AgentRun).join(Ticket, Ticket.id == AgentRun.ticket_id)
                      .where(AgentRun.created_at >= since, *mine).order_by(AgentRun.id)).all()
    last: dict[tuple[str, str], AgentRun] = {}
    for r in runs:
        last[(r.agent, r.ticket_id)] = r

    def latest(agent: str) -> list[AgentRun]:
        return [r for (a, _), r in last.items() if a == agent]

    reviews = db.scalars(select(Review).join(Ticket, Ticket.id == Review.ticket_id)
                         .where(Review.created_at >= since, *mine)).all()
    week = datetime.now(UTC) - timedelta(days=7)
    rated: dict[tuple[int, str], Feedback] = {}  # a person's latest rating of a result counts
    for f in db.scalars(select(Feedback).join(Ticket, Ticket.id == Feedback.ticket_id)
                        .where(Feedback.created_at >= week, *mine).order_by(Feedback.id)):
        rated[(f.agent_run_id, f.reviewer)] = f

    def thumbs(agent: str) -> dict:
        given = [f for f in rated.values() if f.agent == agent]
        return {"rated": len(given), "right": sum(f.stars >= 4 for f in given)}

    closed = db.scalar(select(func.count()).select_from(Ticket).where(
        Ticket.closed_at >= since.replace(tzinfo=None), Ticket.pipeline_status != PipelineStatus.HISTORICAL, *mine))
    opened = db.scalar(select(func.count()).select_from(Ticket).where(
        Ticket.opened_at >= since.replace(tzinfo=None), Ticket.pipeline_status != PipelineStatus.HISTORICAL, *mine))
    return {
        "data_quality": {"done": len(latest(DATA_QUALITY)), **thumbs(DATA_QUALITY),
                         "flagged": sum(r.verdict == "needs_info" for r in latest(DATA_QUALITY))},
        "triage": {"done": sum(bool(r.output.get("priority")) for r in latest(TRIAGE)), **thumbs(TRIAGE),
                   "flagged": sum(r.agent == TRIAGE and r.reviewer == AUTO for r in reviews)},
        "resolution": {"done": sum(r.verdict == "resolved" for r in latest(FIX)), **thumbs(FIX),
                       "flagged": sum(r.agent == FIX and r.action in ("worked", "partly") for r in reviews)},
        "closure_quality": {"done": len(latest("closure_quality")), **thumbs("closure_quality"),
                            "flagged": sum(r.verdict == "good" for r in latest("closure_quality"))},
        "knowledge_builder": {"done": len(latest("knowledge_builder")), **thumbs("knowledge_builder"),
                              "flagged": sum(r.verdict == "matched" for r in latest("knowledge_builder"))},
        "closed": closed or 0,
        "opened": opened or 0,
    }


def closed_by(db: Session, person: str, days: int = 7) -> list[dict]:
    """The tickets `person` closed with Send in the last `days` days, newest first, with what the knowledge base got."""
    since = datetime.now(UTC) - timedelta(days=days)
    sent = db.scalars(select(Review).where(Review.agent == lead_review.CLOSE, Review.reviewer == person,
                                           Review.created_at >= since).order_by(Review.id.desc())).all()
    rows = []
    for r in sent:
        ticket, case = db.get(Ticket, r.ticket_id), db.get(ResolvedCase, r.ticket_id)
        kb = case.kb_article_id if case and case.match_status == "matched" else ("draft" if case and case.draft_id else None)
        rows.append({"id": r.ticket_id, "summary": ticket.summary if ticket else "", "at": _utc(r.created_at), "kb": kb})
    return rows


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

    for run in recent(AgentRun, AgentRun.created_at, AgentRun.agent == ASSIGNMENT):
        who = {"actor": run.output.get("by"), "action": run.output.get("to")}
        events.append((run.created_at, "assigned", run.ticket_id, who))

    bots = {SLA_BOT: "sla_warning", COMMAND_BOT: "command_answered"}
    said = or_(Comment.body.startswith(SAID), Comment.body.startswith(EARLIER[0]))  # the agents' answers, now and before
    for c in recent(Comment, Comment.created_at, or_(Comment.author_email.in_(bots), said)):
        events.append((c.created_at, bots.get(c.author_email, "summary_sent"), c.ticket_id,
                       {} if c.author_email in bots else {"actor": c.author_email}))
    for m in recent(FirstMessage, FirstMessage.sent_at):
        events.append((m.sent_at, "first_message", m.ticket_id, {"actor": m.sent_by}))
    kinds = {TRIAGE: "review", FIX: "fix_answer", lead_review.AGENT: "lead_review", lead_review.CLOSE: "closed",
             "closure_quality": "closure_decision"}
    for r in recent(Review, Review.created_at):
        events.append((r.created_at, kinds.get(r.agent, "review"), r.ticket_id,
                       {"actor": r.reviewer, "action": r.action, "priority": r.final_priority if r.agent == TRIAGE else None}))
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
