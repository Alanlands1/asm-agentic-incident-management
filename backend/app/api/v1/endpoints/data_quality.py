"""Data Quality agent endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.llm import ModelError, ModelUnavailableError
from app.models.ticket import PipelineStatus, Ticket
from app.schemas.data_quality import DataQualityCheckResponse, DataQualityRunResponse
from app.services.data_quality import check_ticket, run_data_quality

router = APIRouter(prefix="/data-quality", tags=["data quality"])


@router.post("/run", response_model=DataQualityRunResponse, summary="Check pending tickets")
async def run(db: AsyncSession = Depends(get_db)) -> DataQualityRunResponse:
    """Run the Data Quality checks on every pending ticket. Safe to re-run: unchanged tickets are skipped."""
    result = await db.run_sync(run_data_quality)
    return DataQualityRunResponse(
        evaluated=result.evaluated, skipped=result.skipped, model_errors=result.model_errors, by_verdict=dict(result.by_verdict)
    )


@router.post("/tickets/{ticket_id}/check", response_model=DataQualityCheckResponse, summary="Check one ticket")
async def check_one_ticket(ticket_id: str, db: AsyncSession = Depends(get_db)) -> DataQualityCheckResponse:
    """Rules, then the model if the rules cannot decide and the model is enabled. Pending tickets only."""
    return await db.run_sync(_check_one, ticket_id)


def _check_one(db: Session, ticket_id: str) -> DataQualityCheckResponse:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    if ticket.pipeline_status != PipelineStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Ticket {ticket_id} is {ticket.pipeline_status}, not pending")

    try:
        agent_run = check_ticket(db, ticket)
    except ModelError as exc:
        db.commit()  # keep the rules verdict
        status = 503 if isinstance(exc, ModelUnavailableError) else 502
        raise HTTPException(status_code=status, detail=f"Model gave no usable answer ({type(exc).__name__})") from exc
    db.commit()
    return DataQualityCheckResponse(
        ticket_id=ticket.id,
        verdict=agent_run.verdict,
        stage=agent_run.output["stage"],
        pipeline_status=ticket.pipeline_status,
        output=agent_run.output,
    )
