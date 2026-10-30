"""Data Quality agent endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.data_quality.pipeline import check_ticket, run_data_quality
from app.agents.data_quality.schemas import DataQualityCheckResponse, DataQualityRunResponse
from app.common.llm import ModelError, ModelUnavailableError
from app.db.session import get_db
from app.models.ticket import PipelineStatus, Ticket

router = APIRouter(prefix="/data-quality", tags=["data quality"])


@router.post("/run", response_model=DataQualityRunResponse, summary="Check pending tickets")
def run(db: Session = Depends(get_db)) -> DataQualityRunResponse:
    """Run the Data Quality checks on every pending ticket. Safe to re-run: unchanged tickets are skipped."""
    result = run_data_quality(db)
    return DataQualityRunResponse(
        evaluated=result.evaluated, skipped=result.skipped, model_errors=result.model_errors, by_verdict=dict(result.by_verdict)
    )


@router.post("/tickets/{ticket_id}/check", response_model=DataQualityCheckResponse, summary="Check one ticket")
def check_one_ticket(ticket_id: str, db: Session = Depends(get_db)) -> DataQualityCheckResponse:
    """Rules, then the model if the rules cannot decide and the model is enabled. Pending tickets only."""
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
