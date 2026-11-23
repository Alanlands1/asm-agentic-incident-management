"""The lead's review of a closure note before it goes to the source (design D3, Phase 3).

LEAD_REVIEW says which tickets need it: always, only P1-P2 (the default) or never. The engineer submits the checked
note, the lead approves it or sends it back with a comment; only then may it be sent. Each step is a review of the
latest Closure Quality run (agent "lead_review"), so "Who did what" can show the trail.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ticket import PipelineStatus, Review, Ticket
from app.services.data_quality import last_run
from app.services.fix import GAP

AGENT = "lead_review"
CLOSE = "close"  # a review row per closure note sent: who closed the ticket (action "sent")
CHECK = "closure_quality"


class ReviewError(ValueError):
    """The step does not fit the ticket now: wrong stage, nothing to review, or a comment missing."""


def priority_of(db: Session, ticket: Ticket) -> int | None:
    """The priority in force: a person's (or the agents') decision, else Triage's recommendation, else the reporter's."""
    decided = db.scalar(
        select(Review.final_priority)
        .where(Review.ticket_id == ticket.id, Review.agent == "triage", Review.final_priority.is_not(None))
        .order_by(Review.id.desc()).limit(1))
    if decided:
        return decided
    triage = last_run(ticket, "triage")
    recommended = triage.output.get("priority") if triage else None
    return recommended or ticket.reported_priority


def required(db: Session, ticket: Ticket) -> bool:
    """Whether a lead must approve this ticket's closure note before it is sent."""
    if settings.LEAD_REVIEW == "never":
        return False
    if settings.LEAD_REVIEW == "always":
        return True
    priority = priority_of(db, ticket)
    return priority is not None and priority <= 2


def submit(db: Session, ticket: Ticket, reviewer: str) -> Review:
    """The engineer hands the checked closure note to the lead. Not committed."""
    notes = (ticket.resolution_notes or "").strip()
    check = last_run(ticket, CHECK)
    if ticket.closed_at is not None or ticket.pipeline_status != PipelineStatus.FIX_CONFIRMED:
        raise ReviewError(f"Ticket {ticket.id}: the closure note opens once the fix worked")
    if not required(db, ticket):
        raise ReviewError("This ticket needs no lead review: send the closure note")
    if not notes or GAP.format("")[:-1] in notes:
        raise ReviewError("Fill in the parts marked [engineer to add: …] first")
    if check is None:
        raise ReviewError("Closure Quality has not checked the note yet")
    return _step(db, ticket, check.id, "submitted", reviewer, None, PipelineStatus.IN_REVIEW)


def decide(db: Session, ticket: Ticket, action: str, reviewer: str, note: str | None) -> Review:
    """The lead approves the note, or sends it back with what to change. Not committed."""
    note = (note or "").strip() or None
    if ticket.closed_at is not None or ticket.pipeline_status != PipelineStatus.IN_REVIEW:
        raise ReviewError(f"Ticket {ticket.id} is not waiting for a lead review")
    if action == "sent_back" and note is None:
        raise ReviewError("Say what to change")
    check = last_run(ticket, CHECK)
    status = PipelineStatus.APPROVED if action == "approved" else PipelineStatus.FIX_CONFIRMED
    return _step(db, ticket, check.id, action, reviewer, note, status)


def may_send(db: Session, ticket: Ticket) -> bool:
    """The closure note may go to the source: approved, or open with no review needed."""
    if ticket.pipeline_status == PipelineStatus.APPROVED:
        return True
    return ticket.pipeline_status == PipelineStatus.FIX_CONFIRMED and not required(db, ticket)


def _step(db: Session, ticket: Ticket, run_id: int, action: str, reviewer: str, note: str | None,
          status: PipelineStatus) -> Review:
    step = Review(ticket_id=ticket.id, agent_run_id=run_id, agent=AGENT, action=action, note=note, reviewer=reviewer.strip())
    db.add(step)
    ticket.pipeline_status = status
    return step
