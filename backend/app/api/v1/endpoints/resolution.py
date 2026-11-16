"""Resolution agent endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.ticket import AgentRun, Ticket
from app.schemas.resolution import ResolutionCheckResponse, ResolutionRunResponse
from app.services.resolution import AGENT, run_resolution

router = APIRouter(prefix="/resolution", tags=["resolution"])


@router.post("/run", response_model=ResolutionRunResponse, summary="Find runbook resolutions for reviewed tickets")
async def run() -> ResolutionRunResponse:
    """Search the runbooks for every reviewed ticket and record the answer. Safe to re-run: unchanged tickets are skipped."""
    result = await run_resolution()
    return ResolutionRunResponse(
        evaluated=result.evaluated, skipped=result.skipped, model_errors=result.model_errors,
        by_verdict=dict(result.by_verdict),
    )


@router.post("/tickets/{ticket_id}/check", response_model=ResolutionCheckResponse, summary="Find one ticket's runbook resolution")
async def check_one_ticket(ticket_id: str, db: AsyncSession = Depends(get_db)) -> ResolutionCheckResponse:
    """Runs again even when nothing changed. Reviewed tickets only."""
    result = await run_resolution(ticket_id=ticket_id)  # the database is read only after the model has answered
    if result.model_errors:
        raise HTTPException(status_code=502, detail="The model did not answer. Try again.")
    if not result.evaluated:
        ticket = await db.get(Ticket, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id} is {ticket.pipeline_status}, not reviewed")
    run = await db.scalar(
        select(AgentRun).where(AgentRun.ticket_id == ticket_id, AgentRun.agent == AGENT).order_by(AgentRun.id.desc()).limit(1)
    )
    return ResolutionCheckResponse(ticket_id=ticket_id, verdict=run.verdict, stage="model", output=run.output)
