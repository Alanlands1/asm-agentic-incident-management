"""Storm endpoints: many people reporting the same issue at once."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ticket import Storm, Ticket
from app.schemas.storm import StormDeclare, StormOut, StormRunResponse
from app.services.triage import storms as storm_service

router = APIRouter(prefix="/storms", tags=["storms"])


def _out(db: Session, storms: list[Storm]) -> list[StormOut]:
    members: dict[int, list[str]] = {}
    for storm_id, ticket_id in db.execute(select(Ticket.storm_id, Ticket.id).where(Ticket.storm_id.in_([s.id for s in storms]))):
        members.setdefault(storm_id, []).append(ticket_id)
    return [StormOut.model_validate(s).model_copy(update={"ticket_ids": sorted(members.get(s.id, []))}) for s in storms]


def _run(db: Session, at: datetime | None) -> StormRunResponse:
    result = storm_service.detect_storms(db, at)
    db.commit()
    return StormRunResponse(created=result.created, updated=result.updated, linked=result.linked, storms=_out(db, result.storms))


@router.post("/run", response_model=StormRunResponse, summary="Find storms among the open tickets")
async def run(
    at: datetime | None = Query(None, description="Treat this as the current time (default: now, UTC); for demos and tests"),
    db: AsyncSession = Depends(get_db),
) -> StormRunResponse:
    """Group open tickets that report the same issue at once. Safe to re-run: existing storms are updated."""
    return await db.run_sync(_run, at)


@router.get("", response_model=list[StormOut], summary="List storms")
async def list_storms(status: str | None = Query(None, pattern="^(open|closed|declared)$"), db: AsyncSession = Depends(get_db)):
    """Storms, newest first. Filter with `status`."""
    return await db.run_sync(_list, status)


def _list(db: Session, status: str | None) -> list[StormOut]:
    query = select(Storm).order_by(Storm.last_ticket_at.desc())
    return _out(db, list(db.scalars(query.where(Storm.status == status) if status else query)))


@router.post("/{storm_id}/declare", response_model=StormOut, summary="Declare a major incident")
async def declare(storm_id: int, payload: StormDeclare, db: AsyncSession = Depends(get_db)) -> StormOut:
    """A person declares a major incident. This records who and when; the major-incident agent starts from here."""
    return await db.run_sync(_declare, storm_id, payload)


def _declare(db: Session, storm_id: int, payload: StormDeclare) -> StormOut:
    storm = db.get(Storm, storm_id)
    if storm is None:
        raise HTTPException(status_code=404, detail=f"Storm {storm_id} not found")
    if storm.declared_at is not None:
        raise HTTPException(status_code=409, detail=f"Storm {storm_id} was already declared by {storm.declared_by}")
    return _out(db, [storm_service.declare(db, storm, payload.declared_by)])[0]
