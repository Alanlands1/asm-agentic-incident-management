"""Engineer review of Closure Quality: the queue of notes that need work, the decision, and how often engineers disagree.

Advisory only: the ticket's own close notes are never changed and nothing is written back to ServiceNow or JIRA.
The engineer's final notes are stored next to the check in agent_reviews, for Knowledge Builder to learn from.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.closure_quality.model_check import GAP
from app.agents.closure_quality.rules import evaluate
from app.agents.closure_quality.verdict import Verdict
from app.models.ticket import AgentRun, Review, Ticket
from app.services.closure.run import AGENT, RESOLVED
from app.services.data_quality import last_run


class ReviewError(ValueError):
    """The decision does not fit the check, e.g. accepting a draft that has gaps."""


class AlreadyReviewed(ReviewError):
    """A person has already decided on this check."""


def pending(db: Session, limit: int = 50) -> list[tuple[Ticket, AgentRun]]:
    """Resolved tickets whose latest check says needs_work and has no decision yet: lowest score first, then oldest."""
    reviewed = set(db.scalars(select(Review.agent_run_id).where(Review.agent == AGENT)))
    tickets = db.scalars(select(Ticket).where(Ticket.status.in_(RESOLVED)).options(selectinload(Ticket.agent_runs))).all()
    latest = [(t, last_run(t, AGENT)) for t in tickets]
    queue = [(t, run) for t, run in latest if run and run.verdict == Verdict.NEEDS_WORK and run.id not in reviewed]
    queue.sort(key=lambda q: (q[1].output["score"] if q[1].output["score"] is not None else -1, q[0].closed_at or datetime.max))
    return queue[:limit]


def review(db: Session, ticket: Ticket, action: str, reviewer: str, final_text: str | None = None,
           reason_code: str | None = None, note: str | None = None) -> Review:
    """Record the engineer's decision on the latest check.

    accepted  the agent's draft becomes the final notes (only a draft with no gaps left)
    edited    the engineer's own notes become the final notes (they must pass the rules)
    rejected  the check was wrong or not needed (a reason_code is required); the notes stand as they are
    """
    run = last_run(ticket, AGENT)
    if run is None or run.verdict != Verdict.NEEDS_WORK:
        raise ReviewError("There is no check waiting for a decision on this ticket")
    if db.scalar(select(Review.id).where(Review.agent == AGENT, Review.agent_run_id == run.id)) is not None:
        raise AlreadyReviewed("This check already has a decision")

    final = None
    if action == "accepted":
        draft = run.output.get("draft_notes")
        if not draft:
            raise ReviewError("There is no draft to accept; edit the notes instead")
        if GAP.search(draft):
            raise ReviewError("The draft still has gaps for the engineer to fill in; edit it instead")
        final = draft
    elif action == "edited":
        final = (final_text or "").strip()
        if not final or final == (ticket.resolution_notes or "").strip():
            raise ReviewError("An edit needs new notes")
        if (outcome := evaluate(final, ticket.summary, ticket.description)).verdict != Verdict.UNCERTAIN:
            raise ReviewError(f"The new notes would still be stopped: {outcome.reason}")
    elif reason_code is None:
        raise ReviewError("A rejection needs a reason_code")

    decision = Review(ticket_id=ticket.id, agent_run_id=run.id, agent=AGENT, action=action, final_text=final,
                      reason_code=reason_code, note=note, reviewer=reviewer.strip())
    db.add(decision)
    db.commit()
    return decision


@dataclass
class ClosureReport:
    days: int
    checks: Counter = field(default_factory=Counter)  # by verdict
    reviewed: int = 0
    by_action: Counter = field(default_factory=Counter)
    by_reason: Counter = field(default_factory=Counter)
    by_rule: Counter = field(default_factory=Counter)  # why notes were stopped by the rules

    @property
    def check_wrong_rate(self) -> float:
        return round(self.by_action["rejected"] / self.reviewed, 3) if self.reviewed else 0.0


def report(db: Session, days: int = 7) -> ClosureReport:
    """How good the notes are, how often engineers say the check was wrong, and why notes get stopped."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = ClosureReport(days=days)
    for run in db.scalars(select(AgentRun).where(AgentRun.agent == AGENT, AgentRun.created_at >= since)):
        result.checks[run.verdict] += 1
        if run.output.get("rule"):
            result.by_rule[run.output["rule"]] += 1
    for r in db.scalars(select(Review).where(Review.agent == AGENT, Review.created_at >= since)):
        result.reviewed += 1
        result.by_action[r.action] += 1
        result.by_reason[r.reason_code] += bool(r.reason_code)
    result.by_reason = Counter({k: v for k, v in result.by_reason.items() if v})
    return result
