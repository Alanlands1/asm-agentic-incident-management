"""Ticket ingestion and query endpoints."""

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.api.v1.endpoints.auth import require_role
from app.core.config import settings
from app.db.session import get_db
from app.llm import ModelError, call_model
from app.models.ticket import AgentRun, Feedback, PipelineStatus, Review, Ticket
from app.personas.service import ASSIGNMENT
from app.privacy.masking import Masker
from app.schemas.ticket import (
    AgentRunOut, AssignCreate, ChatCreate, ChatUse, CommentCreate, CommentOut, FeedbackCreate, FeedbackOut, FixOutcomeCreate,
    IngestResponse, LeadReviewCreate, ReviewStepCreate, TicketDetail, TicketList, TicketSummary,
)
from app.schemas.closure import ClosureReviewOut
from app.schemas.triage import ReviewOut
from app.services import fix, fix_chat, jira, lead_review
from app.services.atlassian import AtlassianError
from app.services.comments import add_comment
from app.services.closure import check_ticket as check_closure
from app.services.closure.run import _input_hash as closure_input_hash
from app.services.data_quality import _input_hash as dq_input_hash
from app.services.data_quality import check_ticket, last_run, reporter_text
from app.services.resolution import busy as resolution_busy
from app.services.resolution import current_hash as resolution_hash
from app.services.resolution import input_changed as resolution_input_changed
from app.services.triage.run import _input_hash as triage_input_hash
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
    # Only Triage reviews decide the priority; Closure Quality and Knowledge Builder reviews are about other things.
    last = await db.scalar(
        select(Review).where(Review.ticket_id == ticket_id, Review.agent == "triage").order_by(Review.id.desc()).limit(1)
    )
    detail.decided = ReviewOut.model_validate(last) if last else None
    closing = await db.scalar(
        select(Review).where(Review.ticket_id == ticket_id, Review.agent == "closure_quality").order_by(Review.id.desc()).limit(1)
    )
    detail.closure_decision = ClosureReviewOut.model_validate(closing) if closing else None
    rated = await db.scalars(select(Feedback).where(Feedback.ticket_id == ticket_id).order_by(Feedback.id))
    detail.feedback = [FeedbackOut.model_validate(f) for f in rated]
    detail.changed = await _changed(db, ticket)
    detail.agents_running = jira.agents_lock.locked() or resolution_busy()
    answers = await db.scalars(select(Review).where(Review.ticket_id == ticket_id, Review.agent == fix.AGENT).order_by(Review.id))
    detail.fix_outcomes = [ReviewOut.model_validate(a) for a in answers]
    steps = await db.scalars(
        select(Review).where(Review.ticket_id == ticket_id, Review.agent == lead_review.AGENT).order_by(Review.id))
    detail.lead_reviews = [ReviewOut.model_validate(s) for s in steps]
    detail.lead_review_required = await db.run_sync(lambda s: lead_review.required(s, ticket))
    return detail


async def _changed(db: AsyncSession, ticket: Ticket) -> dict[str, bool]:
    """For each agent that ran on the ticket: does its input differ from its last run? Same hashes the runs skip on."""
    body = reporter_text(ticket)
    current = {
        "data_quality": lambda: dq_input_hash(ticket, body),
        "triage": lambda: triage_input_hash(ticket, body),
        "closure_quality": lambda: closure_input_hash(ticket),
    }
    changed = {}
    for agent, digest in current.items():
        if (last := last_run(ticket, agent)) is not None:
            changed[agent] = last.input_hash is None or last.input_hash != digest()
    if last_run(ticket, "resolution") is not None:
        changed["resolution"] = await resolution_input_changed(db, ticket)
    return changed


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
    """Thumbs up (5) or down (1) on one agent's result, with optional reasons and a suggestion. Ratings of Resolution
    answers move the runbooks they cite up or down for later tickets of the same kind."""
    run = await db.get(AgentRun, payload.agent_run_id)
    if run is None or run.ticket_id != ticket_id:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} has no agent result {payload.agent_run_id}")
    reason = payload.reason
    if reason and settings.PII_MASKING_ENABLED:  # stored masked, like the note
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


async def _comment_in_jira(ticket: Ticket, text: str, tone: str | None = None) -> None:
    if ticket.source != "JIRA":
        raise HTTPException(status_code=409, detail=f"Ticket {ticket.id} did not come from Jira")
    try:
        await jira.post_comment(ticket.id, text, tone=tone)
    except AtlassianError as exc:  # not stored: the comment is not on the issue
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tickets/{ticket_id}/agent-summary", response_model=CommentOut, status_code=201, summary="Send the agents' result")
async def send_agent_summary(
    ticket_id: str, author_email: str = Body(..., embed=True, min_length=3), db: AsyncSession = Depends(get_db)
):
    """Comment what the agents decided on the Jira issue and keep a copy under the ticket's replies."""
    ticket = await db.run_sync(_get_or_404, ticket_id)
    text, tone = await db.run_sync(lambda s: (jira.agent_summary(ticket), jira.headline(ticket)[0]))
    await _comment_in_jira(ticket, text, tone)
    return await db.run_sync(lambda s: add_comment(s, ticket, author_email, jira.plain(text)))


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
    if summary.pipeline_status == PipelineStatus.REVIEWED:  # Triage approved it without a person
        jira.start_resolution()
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


@router.post("/tickets/{ticket_id}/fix-outcome", response_model=TicketSummary, summary="Say whether the suggested fix worked")
async def fix_outcome(ticket_id: str, payload: FixOutcomeCreate, db: AsyncSession = Depends(get_db)) -> TicketSummary:
    """worked, or partly with what you changed: the fix is confirmed and the closure note opens, drafted from the fix and
    checked by Closure Quality. wrong, with what happened: Resolution looks for another fix; after three, the ticket
    waits for the lead. Nothing is written to Jira."""
    summary = await db.run_sync(_fix_outcome, ticket_id, payload)
    if summary.pipeline_status == PipelineStatus.REVIEWED:  # the fix did not work: look again, with what happened
        jira.start_resolution(ticket_id)
    return summary


def _fix_outcome(db: Session, ticket_id: str, payload: FixOutcomeCreate) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    note = (payload.note or "").strip()
    if note and settings.PII_MASKING_ENABLED:  # stored masked, like the note to the agents
        note = str(_masker(ticket, note).mask(note))
    try:
        fix.record(db, ticket, payload.agent_run_id, payload.outcome, payload.reviewer, note)
    except fix.NotOpen as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except fix.OutcomeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if ticket.pipeline_status == PipelineStatus.FIX_CONFIRMED:
        check_closure(db, ticket)
    db.commit()
    db.refresh(ticket)
    return TicketSummary.model_validate(ticket)


@router.put("/tickets/{ticket_id}/closure-note", response_model=TicketSummary, summary="Save the closure note")
async def set_closure_note(
    ticket_id: str, text: str = Body(..., embed=True, max_length=8000), db: AsyncSession = Depends(get_db)
) -> TicketSummary:
    """Keep the engineer's closure note and let Closure Quality check it again. It stays in the console until the
    engineer sends it to Jira."""
    return await db.run_sync(_set_closure_note, ticket_id, text)


def _set_closure_note(db: Session, ticket_id: str, text: str) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    if ticket.pipeline_status == PipelineStatus.IN_REVIEW:
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id}: the lead is reviewing the closure note")
    if ticket.closed_at is not None or ticket.pipeline_status not in (PipelineStatus.FIX_CONFIRMED, PipelineStatus.APPROVED):
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id}: the closure note opens once the fix worked")
    ticket.pipeline_status = PipelineStatus.FIX_CONFIRMED  # a changed note is not the one the lead approved
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="The closure note is empty")
    if settings.PII_MASKING_ENABLED:  # stored masked, like the description
        text = str(_masker(ticket, text).mask(text))
    ticket.resolution_notes = text
    check_closure(db, ticket)
    db.commit()
    db.refresh(ticket)
    return TicketSummary.model_validate(ticket)


@router.post("/tickets/{ticket_id}/chat", response_model=AgentRunOut, summary="Ask the AI assistant about the fix")
async def chat(ticket_id: str, payload: ChatCreate, db: AsyncSession = Depends(get_db)) -> AgentRunOut:
    """One turn: the masked ticket, the runbook fix, the fixes tried and the chat so far go to the model; its reply,
    and a proposed fix once it has enough to go on, are stored with the ticket."""
    ticket = await db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    kb = await fix_chat.articles(db, ticket, payload.message.strip())
    text, masker = await db.run_sync(_chat_input, ticket_id, payload.message.strip(), kb)
    await db.commit()  # no transaction open while the model thinks
    try:  # in a worker thread: a model call takes seconds and must not hold up other requests
        answer, audit = await asyncio.to_thread(lambda: call_model(fix_chat.chat_spec(), masker.mask(text), masker))
    except ModelError as exc:
        raise HTTPException(status_code=502, detail=f"The assistant gave no answer ({type(exc).__name__}). Try again.") from exc
    rerun = None
    if answer.rerun is not None:  # the engineer said to run an agent again
        started = datetime.now(UTC)
        rerun = await db.run_sync(_chat_rerun, ticket_id, answer.rerun)
        if rerun["ran"] and rerun["agent"] == "resolution":
            jira.start_resolution(ticket_id)  # several model calls: in the background, as after a fix that did not work
        elif rerun["ran"] and rerun["agent"] in ("data_quality", "triage"):  # as the Run buttons do
            await jira.announce(db, started)
            await jira.move_triaged(db)
            if rerun["stage"] == PipelineStatus.REVIEWED:
                jira.start_resolution()
    return await db.run_sync(_chat_saved, ticket_id, payload, answer, asdict(audit), rerun)


def _chat_input(db: Session, ticket_id: str, message: str, kb: str):
    ticket = _get_or_404(db, ticket_id)
    try:
        return fix_chat.prepare(db, ticket, message, kb)
    except fix_chat.ChatError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _chat_rerun(db: Session, ticket_id: str, asked: fix_chat.Rerun) -> dict:
    """Run one agent again because the engineer said so in the chat, with their extra details kept as the note to the
    agents. Returns what happened, for the turn: ran or why not, and the new result's run id."""
    ticket = _get_or_404(db, ticket_id)
    note = asked.note.strip()
    result = {"agent": asked.agent, "note": note, "ran": False, "stage": ticket.pipeline_status}
    if (why := fix_chat.cannot_rerun(ticket, asked.agent)) is not None:
        return {**result, "detail": why}
    if note:
        if settings.PII_MASKING_ENABLED:  # stored masked, like the note
            note = str(_masker(ticket, note).mask(note))
        ticket.guidance = "\n".join(filter(None, [ticket.guidance, note]))
    run = None
    try:
        if asked.agent == "closure_quality":
            run, _ = check_closure(db, ticket)
        elif asked.agent == "data_quality":
            run = check_ticket(db, ticket)
        if asked.agent == "triage" or (asked.agent == "data_quality" and ticket.pipeline_status == PipelineStatus.DQ_PASSED):
            triaged, _ = triage_ticket(db, ticket)
            run = run or triaged
    except ModelError as exc:
        db.commit()  # keep the rules verdict and the note
        return {**result, "stage": ticket.pipeline_status, "detail": f"the model gave no usable answer ({type(exc).__name__})"}
    db.commit()
    return {**result, "ran": True, "stage": ticket.pipeline_status, "run_id": run.id if run else None}


def _chat_saved(db: Session, ticket_id: str, payload: ChatCreate, answer, audit: dict, rerun: dict | None) -> AgentRunOut:
    ticket = _get_or_404(db, ticket_id)
    run = fix_chat.save_turn(db, ticket, payload.message.strip(), payload.author.strip(), answer, audit, rerun)
    db.commit()
    db.refresh(run)
    return AgentRunOut.model_validate(run)


@router.delete("/tickets/{ticket_id}/chat", response_model=TicketSummary, summary="Clear the ticket's chat")
async def clear_chat(ticket_id: str, db: AsyncSession = Depends(get_db)) -> TicketSummary:
    """The chat with the AI assistant starts afresh for this ticket. The turns stay in the activity log."""
    return await db.run_sync(_chat_cleared, ticket_id)


def _chat_cleared(db: Session, ticket_id: str) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    fix_chat.clear(ticket)
    db.commit()
    db.refresh(ticket)
    return TicketSummary.model_validate(ticket)


@router.post("/tickets/{ticket_id}/chat/use", response_model=TicketSummary, summary="Use the assistant's fix")
async def use_chat_fix(ticket_id: str, payload: ChatUse, db: AsyncSession = Depends(get_db)) -> TicketSummary:
    """The proposal becomes the ticket's suggested fix (not from a runbook); then the engineer tries it and says if it
    worked, as for any fix."""
    ticket = await db.get(Ticket, ticket_id, options=[selectinload(Ticket.agent_runs), selectinload(Ticket.comments)])
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    seen = await resolution_hash(db, ticket)
    return await db.run_sync(_chat_used, ticket_id, payload, seen)


def _chat_used(db: Session, ticket_id: str, payload: ChatUse, seen: str) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    try:
        fix_chat.use(db, ticket, payload.run_id, payload.reviewer.strip(), seen)
    except fix_chat.ChatError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(ticket)
    return TicketSummary.model_validate(ticket)


@router.post("/tickets/{ticket_id}/assign", response_model=TicketSummary, summary="Assign the ticket to an engineer",
             dependencies=[Depends(require_role("lead", "admin"))])
async def assign(ticket_id: str, payload: AssignCreate, db: AsyncSession = Depends(get_db)) -> TicketSummary:
    """The lead assigns or reassigns the ticket here. A Jira issue is assigned in Jira first, so the next sync agrees;
    a ticket from another source is assigned in the console only."""
    ticket = await db.run_sync(_get_or_404, ticket_id)
    name = (payload.assignee or "").strip() or None
    if ticket.closed_at is not None:
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id} is closed")
    if name != ticket.assignee and ticket.source == "JIRA":
        await db.commit()  # no transaction open while Jira answers
        try:
            await jira.assign_issue(ticket_id, name)
        except AtlassianError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return await db.run_sync(_assigned, ticket_id, name, payload.by.strip())


def _assigned(db: Session, ticket_id: str, name: str | None, by: str) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    if name != ticket.assignee:  # who gave it to whom, for the activity log
        db.add(AgentRun(ticket_id=ticket.id, agent=ASSIGNMENT, verdict="assigned" if name else "unassigned",
                        output={"to": name, "from": ticket.assignee, "by": by}))
        ticket.assignee = name
        db.commit()
        db.refresh(ticket)
    return TicketSummary.model_validate(ticket)


@router.post("/tickets/{ticket_id}/submit-review", response_model=TicketSummary, summary="Submit the closure note to the lead")
async def submit_review(ticket_id: str, payload: ReviewStepCreate, db: AsyncSession = Depends(get_db)) -> TicketSummary:
    """The engineer hands the checked closure note to the lead, when LEAD_REVIEW asks for it on this ticket."""
    return await db.run_sync(_review_step, ticket_id, lambda s, t: lead_review.submit(s, t, payload.reviewer))


@router.post("/tickets/{ticket_id}/lead-review", response_model=TicketSummary, summary="Approve the closure note or send it back",
             dependencies=[Depends(require_role("lead", "admin"))])
async def decide_review(ticket_id: str, payload: LeadReviewCreate, db: AsyncSession = Depends(get_db)) -> TicketSummary:
    """The lead approves the closure note (then it may be sent) or sends it back to the engineer with what to change."""
    return await db.run_sync(
        _review_step, ticket_id, lambda s, t: lead_review.decide(s, t, payload.action, payload.reviewer, payload.note))


def _review_step(db: Session, ticket_id: str, step) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    try:
        step(db, ticket)
    except lead_review.ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(ticket)
    return TicketSummary.model_validate(ticket)


@router.post("/tickets/{ticket_id}/close", response_model=TicketSummary, summary="Close the ticket with its closure note")
async def close_in_jira(
    ticket_id: str, author_email: str = Body(..., embed=True, min_length=3), db: AsyncSession = Depends(get_db)
) -> TicketSummary:
    """Post the closure note on the Jira issue, move the issue to done and close the ticket here. The one write to Jira
    at the end of the work, and only when the engineer asks (design D8). A ticket from another source is closed here
    only: nothing is sent, the engineer closes it in the source with this note."""
    ticket = await db.run_sync(_get_or_404, ticket_id)
    notes = (ticket.resolution_notes or "").strip()
    needs_lead = await db.run_sync(lambda s: lead_review.required(s, ticket))
    waiting = ticket.pipeline_status == PipelineStatus.FIX_CONFIRMED and needs_lead
    if ticket.pipeline_status == PipelineStatus.IN_REVIEW or waiting:
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id}: a lead approves the closure note before it is sent")
    if ticket.closed_at is not None or not await db.run_sync(lambda s: lead_review.may_send(s, ticket)) or not notes:
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id}: confirm the fix and write the closure note first")
    if "[engineer to add:" in notes:
        raise HTTPException(status_code=409, detail="Fill in the parts marked [engineer to add: …] first")
    decided = await db.scalar(  # the decided priority goes back with the note when it changed (design D8)
        select(Review.final_priority).where(Review.ticket_id == ticket_id, Review.agent == "triage")
        .order_by(Review.id.desc()).limit(1)
    )
    changed = decided if decided and decided != ticket.reported_priority else None
    await db.commit()  # no transaction open while Jira answers
    moved_to = "Closed"
    if ticket.source == "JIRA":
        try:
            moved_to = await jira.close_issue(ticket_id, notes, priority=changed)
        except AtlassianError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    closed = await db.run_sync(_closed, ticket_id, author_email, notes, moved_to)
    jira.start_knowledge()  # the case is learned now, not on the next sync
    return closed


def _closed(db: Session, ticket_id: str, author_email: str, notes: str, moved_to: str) -> TicketSummary:
    ticket = _get_or_404(db, ticket_id)
    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC, as the sync stores it
    ticket.status, ticket.source_status = "closed", moved_to  # what the next sync would bring
    ticket.resolved_at, ticket.closed_at = ticket.resolved_at or now, now
    check = last_run(ticket, "closure_quality") or (ticket.agent_runs[-1] if ticket.agent_runs else None)
    if check is not None:  # who closed it, for "Closed by you" and the activity
        db.add(Review(ticket_id=ticket.id, agent_run_id=check.id, agent=lead_review.CLOSE, action="sent",
                      reviewer=author_email.strip()))
    add_comment(db, ticket, author_email, notes)  # the copy under Updates; commits
    db.refresh(ticket)
    return TicketSummary.model_validate(ticket)
