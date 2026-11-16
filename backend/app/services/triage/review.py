"""Engineer review of Triage recommendations: the queue, the decision, and how often people change what the agent said.

Advisory only: the recommendation in agent_runs is never changed, and this module never writes to the source
(the review endpoint sets a Jira issue's priority when JIRA_WRITE_BACK is on).
The engineer's decision is stored next to it in agent_reviews and moves the ticket on to Resolution.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.triage.config import get_config
from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket
from app.services.data_quality import last_run
from app.services.triage.run import AGENT


class ReviewError(ValueError):
    """The decision does not fit the recommendation, e.g. an edit to the same priority."""


def flags(output: dict) -> list[str]:
    """Why a recommendation needs a closer look, in the order an engineer should read them."""
    large = output["shift"] is not None and abs(output["shift"]) > get_config().review_shift
    return [name for name, on in [("downgrade", output["downgrade"]), ("leaned_high", output["leaned_high"]),
                                  ("kept_reported", output.get("kept_reported", False)), ("large_shift", large)] if on]


def pending(db: Session, limit: int = 50) -> list[tuple[Ticket, AgentRun]]:
    """Triaged tickets waiting for a person: flagged first, then the most urgent, then the oldest.
    A ticket closed in its source (Jira, ServiceNow) is not waiting any more."""
    tickets = db.scalars(
        select(Ticket).where(Ticket.pipeline_status == PipelineStatus.TRIAGED, Ticket.closed_at.is_(None))
        .options(selectinload(Ticket.agent_runs))
    ).all()
    queue = [(t, last_run(t, AGENT)) for t in tickets]
    queue.sort(key=lambda q: (not q[1].output["needs_review"], q[1].output["priority"] or 9, q[0].opened_at or datetime.max))
    return queue[:limit]


def final_priority(ticket: Ticket, action: str, priority: int | None = None, reason_code: str | None = None) -> int | None:
    """The priority a decision would leave in force, or ReviewError if the decision does not fit."""
    recommended = last_run(ticket, AGENT).output["priority"]
    if action == "accepted":
        return recommended
    if action == "edited":
        if priority is None or priority == recommended:
            raise ReviewError(f"An edit needs a priority other than the recommended P{recommended}")
        return priority
    if reason_code is None:
        raise ReviewError("A rejection needs a reason_code")
    return priority or ticket.reported_priority


def review(db: Session, ticket: Ticket, action: str, reviewer: str, priority: int | None = None,
           reason_code: str | None = None, note: str | None = None) -> Review:
    """Record the engineer's decision on the latest recommendation and send the ticket on to Resolution.

    accepted  the recommended priority stands
    edited    a different priority; a reason_code is encouraged
    rejected  the recommendation is unusable (reason_code required); the given priority, or else the reporter's, stands
    """
    run = last_run(ticket, AGENT)
    final = final_priority(ticket, action, priority, reason_code)

    decision = Review(ticket_id=ticket.id, agent_run_id=run.id, agent=AGENT, action=action, final_priority=final,
                      reason_code=reason_code, note=note, reviewer=reviewer.strip())
    db.add(decision)
    ticket.pipeline_status = PipelineStatus.REVIEWED
    db.commit()
    return decision


@dataclass
class ReviewReport:
    days: int
    reviewed: int = 0
    by_action: Counter = field(default_factory=Counter)
    raised_by_engineer: int = 0  # the engineer chose a more urgent priority than the agent
    lowered_by_engineer: int = 0
    by_reason: Counter = field(default_factory=Counter)
    by_rule: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    by_stage: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))  # rules or model

    @property
    def agreement(self) -> float:
        return round(self.by_action["accepted"] / self.reviewed, 3) if self.reviewed else 0.0


def report(db: Session, days: int = 7) -> ReviewReport:
    """How often engineers change the agent, and on which rules: the input for rule fixes."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    reviews = db.scalars(
        select(Review).where(Review.agent == AGENT, Review.created_at >= since).options(selectinload(Review.agent_run))
    ).all()
    result = ReviewReport(days=days, reviewed=len(reviews))
    for r in reviews:
        output = r.agent_run.output
        recommended = output["priority"]
        result.by_action[r.action] += 1
        result.by_reason[r.reason_code] += bool(r.reason_code)
        result.by_rule[output["rule"] or "(none)"][r.action] += 1
        result.by_stage[output["stage"]][r.action] += 1
        if r.final_priority and recommended and r.final_priority != recommended:
            result.raised_by_engineer += r.final_priority < recommended
            result.lowered_by_engineer += r.final_priority > recommended
    result.by_reason = Counter({k: v for k, v in result.by_reason.items() if v})
    return result
