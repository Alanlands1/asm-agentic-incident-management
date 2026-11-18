"""Closure Quality agent endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ticket import Ticket
from app.schemas.closure import (
    ClosureCheckResponse,
    ClosureQueueItem,
    ClosureReportOut,
    ClosureReviewCreate,
    ClosureReviewOut,
    ClosureRunResponse,
)
from app.services.closure import check_ticket, run_closure
from app.services.closure import review as closure_review
from app.services.closure.run import RESOLVED

router = APIRouter(prefix="/closure", tags=["closure quality"])


@router.post("/run", response_model=ClosureRunResponse, summary="Check the close notes of resolved tickets")
async def run(
    include_history: bool = Query(False, description="Also score tickets that were already closed when they arrived"),
    db: AsyncSession = Depends(get_db),
) -> ClosureRunResponse:
    """Score the close notes of every resolved or closed ticket. Safe to re-run: unchanged notes are skipped."""
    result = await db.run_sync(run_closure, include_history)
    return ClosureRunResponse(
        evaluated=result.evaluated, skipped=result.skipped, model_errors=result.model_errors, by_verdict=dict(result.by_verdict)
    )


@router.post("/tickets/{ticket_id}/check", response_model=ClosureCheckResponse, summary="Check one ticket's close notes")
async def check_one_ticket(ticket_id: str, db: AsyncSession = Depends(get_db)) -> ClosureCheckResponse:
    """Rules, then the model if the rules cannot stop the notes and the model is enabled. Resolved tickets only."""
    return await db.run_sync(_check_one, ticket_id)


def _check_one(db: Session, ticket_id: str) -> ClosureCheckResponse:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    if ticket.status not in RESOLVED:
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id} is {ticket.status}, not resolved")
    run, _ = check_ticket(db, ticket)
    db.commit()
    return ClosureCheckResponse(ticket_id=ticket.id, verdict=run.verdict, stage=run.output["stage"], output=run.output)


@router.get("/queue", response_model=list[ClosureQueueItem], summary="Close notes that need work")
async def queue(limit: int = Query(50, ge=1, le=500), db: AsyncSession = Depends(get_db)) -> list[ClosureQueueItem]:
    """Resolved tickets whose notes need work and have no decision yet, lowest score first."""
    items = await db.run_sync(closure_review.pending, limit)
    return [
        ClosureQueueItem(
            ticket_id=t.id, summary=t.summary, application=t.application, closed_at=t.closed_at, notes=t.resolution_notes,
            score=run.output["score"], rule=run.output["rule"], reason=run.output["reason"],
            questions=run.output["questions"], draft_notes=run.output["draft_notes"],
        )
        for t, run in items
    ]


@router.post("/tickets/{ticket_id}/review", response_model=ClosureReviewOut, status_code=201, summary="Record a decision")
async def review_ticket(ticket_id: str, payload: ClosureReviewCreate, db: AsyncSession = Depends(get_db)) -> ClosureReviewOut:
    """Accept the draft, edit the notes, or reject the check. The ticket's own notes are not changed."""
    return await db.run_sync(_review_one, ticket_id, payload)


def _review_one(db: Session, ticket_id: str, payload: ClosureReviewCreate) -> ClosureReviewOut:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    try:
        decision = closure_review.review(db, ticket, **payload.model_dump())
    except closure_review.AlreadyReviewed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except closure_review.ReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ClosureReviewOut.model_validate(decision)


@router.get("/report", response_model=ClosureReportOut, summary="How good the close notes are")
async def report(days: int = Query(7, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> ClosureReportOut:
    """Checks by verdict, why notes were stopped, and how often engineers rejected the check (`days`, default 7)."""
    r = await db.run_sync(closure_review.report, days)
    return ClosureReportOut(
        days=r.days, checks=dict(r.checks), reviewed=r.reviewed, by_action=dict(r.by_action), by_reason=dict(r.by_reason),
        by_rule=dict(r.by_rule), check_wrong_rate=r.check_wrong_rate,
    )
