"""Ticket ingestion and query endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.db.session import get_db
from app.models.ticket import Ticket
from app.platform.tickets.comments import add_comment
from app.platform.tickets.ingestion import ingest_workbook
from app.platform.tickets.schemas import CommentCreate, CommentOut, IngestResponse, TicketDetail, TicketList

router = APIRouter(tags=["tickets"])


@router.post("/ingest", response_model=IngestResponse, summary="Load tickets from all sources")
def ingest(db: Session = Depends(get_db)) -> IngestResponse:
    """Read ServiceNow, JIRA and Mailbox tickets from the workbook and upsert them. Safe to re-run."""
    try:
        result = ingest_workbook(db, settings.TICKETS_FILE)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return IngestResponse(created=result.created, updated=result.updated, by_source=dict(result.by_source))


@router.get("/tickets", response_model=TicketList, summary="List tickets")
def list_tickets(
    source: Optional[str] = Query(None, description="ServiceNow, JIRA or Mailbox"),
    status: Optional[str] = Query(None, description="new, in_progress, on_hold, resolved, closed"),
    application: Optional[str] = None,
    pipeline_status: Optional[str] = Query(None, description="historical, pending, awaiting_info, dq_passed, rejected, error"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
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

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Ticket.opened_at.desc()).limit(limit).offset(offset)).all()
    return TicketList(total=total, items=items)


def _get_or_404(db: Session, ticket_id: str) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    return ticket


@router.get("/tickets/{ticket_id}", response_model=TicketDetail, summary="Get one ticket")
def get_ticket(ticket_id: str, db: Session = Depends(get_db)) -> Ticket:
    """Full ticket with its original source row, replies and agent audit trail."""
    return _get_or_404(db, ticket_id)


@router.post("/tickets/{ticket_id}/comments", response_model=CommentOut, status_code=201, summary="Add a reply")
def create_comment(ticket_id: str, payload: CommentCreate, db: Session = Depends(get_db)):
    """Add a reply. A reply from the reporter on a ticket awaiting information sends it back to pending."""
    return add_comment(db, _get_or_404(db, ticket_id), payload.author_email, payload.body)
