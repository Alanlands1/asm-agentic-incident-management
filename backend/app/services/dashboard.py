"""Admin home numbers, all read from stored data: tickets, agent runs, reviews, syncs and what needs attention."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.confluence import ConfluenceSync
from app.models.jira import JiraSync
from app.models.servicenow import ServiceNowTicket
from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket
from app.services import incidents
from app.services.triage import review, sla

SyncState = Literal["off", "never", "running", "stale"]


def sync_state(last_started_at: datetime | None, minutes: int, now: datetime) -> SyncState:
    """off: manual only. never: no sync yet. stale: the last one started over 3 intervals ago."""
    if minutes == 0:
        return "off"
    if last_started_at is None:
        return "never"
    started = last_started_at if last_started_at.tzinfo else last_started_at.replace(tzinfo=UTC)
    return "stale" if now - started > timedelta(minutes=3 * minutes) else "running"


def _agent_stats(runs: list[AgentRun], agent: str) -> dict[str, Any]:
    latest: dict[str, AgentRun] = {}  # a model check stores two runs (rules, then model): count the ticket once
    for r in sorted((r for r in runs if r.agent == agent), key=lambda r: (r.created_at, r.id)):
        latest[r.ticket_id] = r
    mine = list(latest.values())
    if agent == "triage":
        used = sum(1 for r in mine if (r.output or {}).get("ai") == "used")
    else:
        used = sum(1 for r in mine if (r.output or {}).get("stage") == "model")
    failed = sum(1 for r in mine if (r.output or {}).get("ai") == "failed")
    verdicts = dict(Counter(r.verdict for r in mine))
    return {"checked": len(mine), "by_verdict": verdicts, "model_used": used, "model_failed": failed}


def _sync_health(db: Session, model: type[JiraSync] | type[ConfluenceSync], minutes: int, now: datetime) -> dict[str, Any]:
    last = db.scalar(select(model).order_by(model.started_at.desc(), model.id.desc()).limit(1))
    summary = None
    if last is not None and not last.error:
        if isinstance(last, JiraSync):
            summary = f"Pulled {last.pulled}" + (f" · {last.queued} sent to the agents" if last.queued else "")
        else:
            summary = f"Copied {last.pulled}" + (f" · {last.removed} removed" if last.removed else "")
    return {
        "state": sync_state(last.started_at if last else None, minutes, now),
        "minutes": minutes,
        "last_started_at": last.started_at if last else None,
        "last_error": last.error if last else None,
        "last_summary": summary,
    }


def summary(db: Session, since: datetime, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    today = select(Ticket.source, func.count()).where(Ticket.ingested_at >= since).group_by(Ticket.source)
    by_source = dict(db.execute(today).all())
    servicenow = db.scalar(select(func.count()).select_from(ServiceNowTicket).where(
        ServiceNowTicket.created_at >= since, ServiceNowTicket.ticket_id.not_in(select(Ticket.id))))  # Jira rows are in both
    if servicenow:
        by_source["ServiceNow"] = servicenow
    by_stage = dict(db.execute(
        select(Ticket.pipeline_status, func.count())
        .where(Ticket.pipeline_status != PipelineStatus.HISTORICAL)
        .group_by(Ticket.pipeline_status)
    ).all())

    runs = list(db.scalars(select(AgentRun).where(AgentRun.created_at >= since, AgentRun.agent.in_(("data_quality", "triage")))))

    queue = review.pending(db, limit=500)
    opened = [t.opened_at for t, _ in queue if t.opened_at]
    agreement = review.report(db, days=7)

    return {
        "tickets": {"by_source_today": by_source, "by_stage": by_stage},
        "agents": {"data_quality": _agent_stats(runs, "data_quality"), "triage": _agent_stats(runs, "triage")},
        "review_queue": {
            "size": len(queue),
            "oldest_at": min(opened) if opened else None,
            "p1_p2": sum(1 for _, run in queue if ((run.output or {}).get("priority") or 9) <= 2),
        },
        "agreement": {"days": agreement.days, "reviewed": agreement.reviewed, "agreement": agreement.agreement},
        "syncs": {
            "jira": _sync_health(db, JiraSync, settings.JIRA_SYNC_MINUTES, now),
            "confluence": _sync_health(db, ConfluenceSync, settings.CONFLUENCE_SYNC_MINUTES, now),
        },
        "attention": incidents.attention_count(db),
    }


def _utc(at: datetime) -> datetime:
    """Ticket times are naive UTC, and SQLite drops the zone."""
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def trends(db: Session, since: datetime, days: int, now: datetime | None = None) -> dict[str, Any]:
    """Per-day counts for `days` days from `since` (the viewer's midnight), so the days are the viewer's days."""
    since, now = _utc(since), now or datetime.now(UTC)
    naive = since.astimezone(UTC).replace(tzinfo=None)  # for the naive ticket columns

    def day(at: datetime) -> int | None:
        i = (_utc(at) - since) // timedelta(days=1)
        return i if 0 <= i < days else None

    def add(series: dict[str, list[int]], name: str, at: datetime, n: int = 1) -> None:
        if (i := day(at)) is not None:
            series.setdefault(name, [0] * days)[i] += n

    # Tickets by the day they were opened; the day they were pulled in when the source gives no open time.
    tickets: dict[str, list[int]] = {}
    for source, opened, ingested in db.execute(
        select(Ticket.source, Ticket.opened_at, Ticket.ingested_at)
        .where(or_(Ticket.opened_at >= naive, Ticket.ingested_at >= since))
    ):
        add(tickets, source, opened or ingested)
    for opened, created in db.execute(
        select(ServiceNowTicket.opened_at, ServiceNowTicket.created_at)
        .where(or_(ServiceNowTicket.opened_at >= naive, ServiceNowTicket.created_at >= since),
               ServiceNowTicket.ticket_id.not_in(select(Ticket.id)))  # Jira issues are written to both tables
    ):
        add(tickets, "ServiceNow", opened or created)

    # Tokens are only stored for model calls that gave an answer; a failed call leaves no count.
    tokens: dict[str, list[int]] = {}
    tokens_in = tokens_out = calls = 0
    for agent, output, created in db.execute(
        select(AgentRun.agent, AgentRun.output, AgentRun.created_at).where(AgentRun.created_at >= since)
    ):
        audit = (output or {}).get("audit")
        if not audit or day(created) is None:
            continue
        audits = audit if isinstance(audit, list) else [audit]  # Resolution keeps one audit per model call
        spent_in = sum(a.get(k) or 0 for a in audits for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens"))
        spent_out = sum(a.get("output_tokens") or 0 for a in audits)
        add(tokens, agent, created, spent_in + spent_out)
        tokens_in, tokens_out, calls = tokens_in + spent_in, tokens_out + spent_out, calls + len(audits)

    # A breach is counted on the day the SLA time ran out, for tickets not resolved by then.
    cfg, at = sla.config(), now.astimezone(UTC).replace(tzinfo=None)
    candidates = db.scalars(
        select(Ticket)
        .where(Ticket.pipeline_status.in_([PipelineStatus.TRIAGED, PipelineStatus.REVIEWED]),
               Ticket.opened_at >= naive - timedelta(hours=max(cfg.targets.values())))
        .options(selectinload(Ticket.agent_runs))
    ).all()
    breaches: dict[str, list[int]] = {}
    working = sla.working_priorities(db, candidates)
    for t in candidates:
        hours = cfg.targets.get(working[t.id][0]) if t.id in working else None
        if hours is None:
            continue
        due = t.opened_at + timedelta(hours=hours)
        if due <= (t.resolved_at or t.closed_at or at):
            add(breaches, f"P{working[t.id][0]}", due)

    open_now = Counter(i.sla.state for i in sla.open_p1_p2(db, at))
    reviews = Counter(
        reviewer for reviewer, created in db.execute(select(Review.reviewer, Review.created_at).where(Review.created_at >= since))
        if day(created) is not None
    )
    return {
        "days": [since + timedelta(days=i) for i in range(days)],
        "tickets": tickets,
        "tokens": tokens,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model_calls": calls,
        "sla_breaches": breaches,
        "sla_open": {"breached": open_now["breached"], "breach_likely": open_now["breach_likely"]},
        "reviews": dict(reviews),
    }
