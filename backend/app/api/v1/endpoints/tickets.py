"""Ticket ingestion and query endpoints."""

from datetime import UTC, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.llm import ModelError
from app.models.ticket import AgentRun, Feedback, PipelineStatus, Review, Ticket
from app.privacy.masking import Masker
from app.schemas.ticket import (
    CommentCreate, CommentOut, FeedbackCreate, FeedbackOut, IngestResponse, TicketDetail, TicketList, TicketSummary,
)
from app.schemas.triage import ReviewOut
from app.services import jira
from app.services.atlassian import AtlassianError
from app.services.comments import add_comment
from app.services.data_quality import check_ticket
from app.services.ingestion import ingest_workbook
from app.services.triage import triage_ticket

router = APIRouter(tags=["tickets"])


@router.post("/ingest", response_model=IngestResponse, summary="Load tickets from all sources")
async def ingest(db: AsyncSession = Depends(get_db)) -> IngestResponse:
    """Read ServiceNow, JIRA and Mailbox tickets from the workbook and upsert them. Safe to re-run."""
    try:
        result = await db.run_sync(ingest_workbook, settings.TICKETS_FILE)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return IngestResponse(created=result.created, updated=result.updated, by_source=dict(result.by_source))


@router.get("/tickets", response_model=TicketList, summary="List tickets")
async def list_tickets(
    source: Optional[str] = Query(None, description="ServiceNow, JIRA or Mailbox"),
    status: Optional[str] = Query(None, description="new, in_progress, on_hold, resolved, closed"),
    application: Optional[str] = None,
    pipeline_status: Optional[str] = Query(None, description="historical, pending, awaiting_info, dq_passed, rejected, error"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> TicketList:
    """Tickets newest first, optionally filtered."""
    query = select(Ticket)
    for column, value in [
        (Ticket.source, source),
        (Ticket.status, status),
        (Ticket.application, application),
        (Ticket.pipeline_status, pipeline_status),
    ]:
        if value is not None:
            query = query.where(column == value)

    total_result = await db.scalar(select(func.count()).select_from(query.subquery()))
    items_result = await db.scalars(query.order_by(Ticket.opened_at.desc()).limit(limit).offset(offset))
    return TicketList(total=total_result or 0, items=items_result.all())


def _get_or_404(db: Session, ticket_id: str) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    return ticket


@router.get("/tickets/{ticket_id}", response_model=TicketDetail, summary="Get one ticket")
async def get_ticket(ticket_id: str, db: AsyncSession = Depends(get_db)) -> TicketDetail:
    """Full ticket with its original source row, replies, agent audit trail and the last decision on its priority."""
    ticket = await db.get(Ticket, ticket_id, options=[selectinload(Ticket.agent_runs), selectinload(Ticket.comments)])
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    detail = TicketDetail.model_validate(ticket)
    last = await db.scalar(select(Review).where(Review.ticket_id == ticket_id).order_by(Review.id.desc()).limit(1))
    detail.decided = ReviewOut.model_validate(last) if last else None
    rated = await db.scalars(select(Feedback).where(Feedback.ticket_id == ticket_id).order_by(Feedback.id))
    detail.feedback = [FeedbackOut.model_validate(f) for f in rated]
    return detail


@router.put("/tickets/{ticket_id}/guidance", response_model=TicketSummary, summary="Tell the agents more about a ticket")
async def set_guidance(
    ticket_id: str, text: str = Body(..., embed=True, max_length=4000), db: AsyncSession = Depends(get_db)
) -> TicketSummary:
    """Keep a person's note on the ticket: extra facts, a question or the answer they already know. Every agent run
    after it reads the note with the description. An empty text removes the note."""
    return await db.run_sync(_set_guidance, ticket_id, text)


def _masker(ticket: Ticket, text: str) -> Masker:
    """Masks a new note or reason. Numbering goes on after the ticket's other texts, and after the placeholders its own
    text brings back from an earlier save."""
    # shortcut: a first name alone ("Ravi fixed it") stays as typed, the model misses it; keep real names to match if that matters
    beside = [ticket.summary, ticket.description, ticket.guidance, *(c.body for c in ticket.comments), text]
    return Masker(known_names=[ticket.reporter_name], known_emails=[ticket.reporter_email], beside=beside)


def _set_guidance(db: Session, ticket_id: str, text: str) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    text = text.strip()
    if text and settings.PII_MASKING_ENABLED:  # stored masked, like the description
        text = str(_masker(ticket, text).mask(text))
    if text and text != ticket.guidance and ticket.pipeline_status == PipelineStatus.AWAITING_INFO:
        ticket.pipeline_status = PipelineStatus.PENDING  # the note may hold what was missing, like a reply from the reporter
    ticket.guidance = text or None
    db.commit()
    db.refresh(ticket)
    return TicketSummary.model_validate(ticket)


@router.post("/tickets/{ticket_id}/feedback", response_model=FeedbackOut, status_code=201, summary="Rate an agent's result")
async def rate_agent_run(ticket_id: str, payload: FeedbackCreate, db: AsyncSession = Depends(get_db)):
    """One to five stars on one agent's result, with the reason. Ratings of Resolution answers move the runbooks they
    cite up or down for later tickets of the same kind."""
    run = await db.get(AgentRun, payload.agent_run_id)
    if run is None or run.ticket_id != ticket_id:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} has no agent result {payload.agent_run_id}")
    reason = payload.reason
    if settings.PII_MASKING_ENABLED:  # stored masked, like the note
        ticket = await db.get(Ticket, ticket_id)
        await db.refresh(ticket, ["comments"])
        reason = str(_masker(ticket, reason).mask(reason))
    feedback = Feedback(ticket_id=ticket_id, agent_run_id=run.id, agent=run.agent, stars=payload.stars,
                        reason=reason, reviewer=payload.reviewer.strip())
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


@router.post("/tickets/{ticket_id}/comments", response_model=CommentOut, status_code=201, summary="Add a reply")
async def create_comment(ticket_id: str, payload: CommentCreate, db: AsyncSession = Depends(get_db)):
    """Add a reply. A reply from the reporter on a ticket awaiting information sends it back to pending."""
    ticket = await db.run_sync(_get_or_404, ticket_id)
    if payload.post_to_jira:
        await _comment_in_jira(ticket, payload.body)
    return await db.run_sync(lambda s: add_comment(s, ticket, payload.author_email, payload.body))


async def _comment_in_jira(ticket: Ticket, text: str) -> None:
    if ticket.source != "JIRA":
        raise HTTPException(status_code=409, detail=f"Ticket {ticket.id} did not come from Jira")
    try:
        await jira.post_comment(ticket.id, text)
    except AtlassianError as exc:  # not stored: the comment is not on the issue
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tickets/{ticket_id}/agent-summary", response_model=CommentOut, status_code=201, summary="Send the agents' result")
async def send_agent_summary(
    ticket_id: str, author_email: str = Body(..., embed=True, min_length=3), db: AsyncSession = Depends(get_db)
):
    """Comment what the agents decided on the Jira issue and keep a copy under the ticket's replies."""
    ticket = await db.run_sync(_get_or_404, ticket_id)
    text = await db.run_sync(lambda s: jira.agent_summary(ticket))
    await _comment_in_jira(ticket, text)
    return await db.run_sync(lambda s: add_comment(s, ticket, author_email, text))


# Stages where a person may start the agents; reviewed, rejected and historical tickets are already decided.
CAN_RUN = {
    PipelineStatus.PENDING, PipelineStatus.AWAITING_INFO, PipelineStatus.DQ_PASSED, PipelineStatus.TRIAGED, PipelineStatus.ERROR,
}


@router.post("/tickets/{ticket_id}/run-agents", response_model=TicketSummary, summary="Run the agents on one ticket")
async def run_agents_on_ticket(
    ticket_id: str,
    agent: Literal["data_quality", "triage"] = Body("data_quality", embed=True),
    db: AsyncSession = Depends(get_db),
) -> TicketSummary:
    """Run Data Quality on one open ticket (Triage follows if it passes), or only Triage; again if they ran before."""
    started = datetime.now(UTC)
    summary = await db.run_sync(_run_agents, ticket_id, agent)
    await jira.announce(db, started)
    await jira.move_triaged(db)
    return summary


def _run_agents(db: Session, ticket_id: str, agent: str) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    if ticket.closed_at is not None or ticket.pipeline_status not in CAN_RUN:
        stage = "closed in its source" if ticket.closed_at is not None else ticket.pipeline_status
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id} is {stage}: the agents do not run on it")
    if agent == "data_quality":
        try:
            check_ticket(db, ticket)
        except ModelError as exc:
            db.commit()  # keep the rules verdict
            raise HTTPException(status_code=502, detail=f"Model gave no usable answer ({type(exc).__name__})") from exc
    elif ticket.pipeline_status not in (PipelineStatus.DQ_PASSED, PipelineStatus.TRIAGED):
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id} has not passed Data Quality yet")
    if agent == "triage" or ticket.pipeline_status == PipelineStatus.DQ_PASSED:
        triage_ticket(db, ticket)
    db.commit()
    db.refresh(ticket)
    return TicketSummary.model_validate(ticket)
