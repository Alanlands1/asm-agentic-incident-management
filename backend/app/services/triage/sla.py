"""SLA risk and the first message for open P1/P2 tickets.

The priority used is the engineer's decision when there is one, else the Triage recommendation. Advisory only: the
message is drafted from a template (no model, no names) and a person sends it; nothing here sends or schedules anything.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.triage.config import get_config
from app.agents.triage.rules import find_rule
from app.core.registry import load_registry, register_document
from app.models.ticket import AgentRun, PipelineStatus, Review, Storm, Ticket
from app.services.data_quality import last_run
from app.services.triage.run import AGENT

SEVERITY = {"breached": 0, "breach_likely": 1, "watch": 2, "ok": 3}


@dataclass(frozen=True)
class SlaConfig:
    targets: dict[int, int]  # priority -> hours
    watch_at: float
    breach_likely_at: float
    first_message_minutes: int
    update_every_minutes: int
    template: str


def config() -> SlaConfig:
    doc = load_registry("sla.yaml")
    cfg = SlaConfig(
        targets={int(p): v["target_hours"] for p, v in doc["priorities"].items()},
        watch_at=doc["watch_at"], breach_likely_at=doc["breach_likely_at"],
        first_message_minutes=doc["first_message_minutes"], update_every_minutes=doc["update_every_minutes"],
        template=doc["first_message"],
    )
    if not 0 < cfg.watch_at < cfg.breach_likely_at < 1 or min(cfg.targets.values()) < 1:
        raise ValueError("watch_at must be below breach_likely_at, both between 0 and 1, and every target at least 1 hour")
    cfg.template.format(application="", what="", who="", ticket_id="", next_update="")  # an unknown placeholder raises
    return cfg


register_document("sla", "sla.yaml", config)


def now() -> datetime:
    """Ticket times are naive; they are compared as UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class SlaStatus:
    state: str  # ok, watch, breach_likely, breached
    used: float  # share of the target used
    due_at: datetime
    minutes_left: int  # negative once breached


def sla_status(priority: int, opened_at: datetime, at: datetime, cfg: SlaConfig | None = None) -> SlaStatus | None:
    """How much of the SLA target is used. None for a priority with no target (P3 and below)."""
    cfg = cfg or config()
    if (hours := cfg.targets.get(priority)) is None:
        return None
    target = timedelta(hours=hours)
    used = (at - opened_at) / target
    state = ("breached" if used >= 1 else "breach_likely" if used >= cfg.breach_likely_at
             else "watch" if used >= cfg.watch_at else "ok")
    return SlaStatus(state, round(used, 3), opened_at + target, int((opened_at + target - at).total_seconds() // 60))


@dataclass(frozen=True)
class FirstMessage:
    text: str
    send_by: datetime
    minutes_left: int


def _what(output: dict) -> str:
    """What is wrong, in the rulebook's words: the rule's description, never the reporter's."""
    book = get_config()
    rule = find_rule(book, output.get("application"), output.get("rule") or "")
    name = output.get("must_follow") or output.get("rule")
    about = rule.about if rule else next((m.about for m in book.must_follow if m.name == name), None)
    return (about or f"an issue is affecting {output.get('application') or 'a service'}").split(" (")[0].rstrip(".")


def _who(output: dict, storm: Storm | None) -> str:
    scope = (output.get("signals") or {}).get("scope") or (output.get("answer") or {}).get("scope")
    if storm:
        return f"{storm.people} people have reported it so far."
    return {"wide": "Several users are affected.", "single": "One user has reported it."}.get(scope, "")


def local(at: datetime) -> datetime:
    """A stored time (naive UTC) with its zone, for texts people read; print it with %Z. Always UTC: the server's zone
    changed between runs and left one issue with warnings in two zones; the console shows the viewer's own zone."""
    return at.replace(tzinfo=timezone.utc)


def first_message(ticket: Ticket, run: AgentRun, at: datetime, storm: Storm | None = None,
                  cfg: SlaConfig | None = None) -> FirstMessage:
    """The first message for a P1/P2, from the template. It names the application and the problem, never a person."""
    cfg = cfg or config()
    out = run.output
    text = cfg.template.format(
        application=out.get("application") or ticket.application or "Service",
        what=_what(out), who=_who(out, storm), ticket_id=ticket.id,
        next_update=local(at + timedelta(minutes=cfg.update_every_minutes)).strftime("%H:%M %Z"),
    )
    send_by = ticket.opened_at + timedelta(minutes=cfg.first_message_minutes)
    return FirstMessage(" ".join(text.split()), send_by, int((send_by - at).total_seconds() // 60))


@dataclass(frozen=True)
class SlaItem:
    ticket: Ticket
    priority: int
    priority_from: str  # reviewed (an engineer decided) or recommended
    sla: SlaStatus
    message: FirstMessage
    storm_id: int | None
    application: str | None  # as the agent found it; mailbox tickets have none of their own


def working_priorities(db: Session, tickets: list[Ticket]) -> dict[str, tuple[int, str, AgentRun]]:
    """Per ticket: the priority in force, where it came from, and the recommendation behind it. One query for the reviews."""
    reviews: dict[str, Review] = {}
    for r in db.scalars(select(Review).where(Review.ticket_id.in_([t.id for t in tickets]), Review.agent == AGENT)
                        .order_by(Review.id)):
        reviews[r.ticket_id] = r  # the last one wins
    result = {}
    for t in tickets:
        run = last_run(t, AGENT)
        review = reviews.get(t.id)
        priority = review.final_priority if review and review.final_priority else run.output["priority"] if run else None
        if priority is not None:
            result[t.id] = (priority, "reviewed" if review and review.final_priority else "recommended", run)
    return result


def open_p1_p2(db: Session, at: datetime | None = None) -> list[SlaItem]:
    """Open tickets whose priority in force is P1 or P2, most at risk first."""
    at, cfg = at or now(), config()
    tickets = db.scalars(
        select(Ticket)
        .where(Ticket.pipeline_status.in_([PipelineStatus.TRIAGED, PipelineStatus.REVIEWED]),
               Ticket.closed_at.is_(None), Ticket.opened_at.is_not(None))
        .options(selectinload(Ticket.agent_runs))
    ).all()
    storms = {s.id: s for s in db.scalars(select(Storm).where(Storm.id.in_({t.storm_id for t in tickets if t.storm_id})))}
    working = working_priorities(db, tickets)
    items = []
    for t in tickets:
        if t.id not in working or working[t.id][0] > 2:
            continue
        priority, source, run = working[t.id]
        status = sla_status(priority, t.opened_at, at, cfg)
        if status is not None:
            message = first_message(t, run, at, storms.get(t.storm_id), cfg)
            application = run.output.get("application") or t.application
            items.append(SlaItem(t, priority, source, status, message, t.storm_id, application))
    return sorted(items, key=lambda i: (SEVERITY[i.sla.state], i.sla.minutes_left))
