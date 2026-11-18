"""Data Quality agent schemas."""

from typing import Any

from pydantic import BaseModel, Field


class DataQualityRunResponse(BaseModel):
    """Result of checking the pending tickets."""
    evaluated: int = Field(..., examples=[67])
    skipped: int = Field(..., examples=[0])
    model_errors: int = Field(0, examples=[0], description="Tickets left pending because the model gave no usable answer")
    by_verdict: dict[str, int] = Field(..., examples=[{"passed": 40, "needs_info": 26, "not_an_incident": 1}])


class DataQualityCheckResponse(BaseModel):
    """Verdict on one ticket."""
    ticket_id: str = Field(..., examples=["INC0010231"])
    verdict: str = Field(..., examples=["needs_info"])
    stage: str = Field(..., examples=["model"], description="rules, or model when the rules could not decide")
    pipeline_status: str = Field(..., examples=["awaiting_info"])
    output: dict[str, Any] = Field(..., description="The stage's reasoning; for the model stage also the audit fields")
