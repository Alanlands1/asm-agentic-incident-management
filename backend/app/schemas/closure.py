"""Closure Quality agent schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ClosureRunResponse(BaseModel):
    """Result of checking the close notes of resolved tickets."""
    evaluated: int = Field(..., examples=[12])
    skipped: int = Field(..., examples=[0], description="Notes unchanged since their last check")
    model_errors: int = Field(0, examples=[0], description="Tickets left unchecked because the model gave no usable answer")
    by_verdict: dict[str, int] = Field(..., examples=[{"good": 8, "needs_work": 3, "not_applicable": 1}])


class ClosureCheckResponse(BaseModel):
    """How good the close notes of one ticket are."""
    ticket_id: str = Field(..., examples=["AMS-1200"])
    verdict: str = Field(..., examples=["needs_work"])
    stage: str = Field(..., examples=["model"], description="rules, or model when the rules could not stop the notes")
    output: dict[str, Any] = Field(..., description="Score out of 6, the three parts with their quotes, questions and any draft")


class ClosureQueueItem(BaseModel):
    """Close notes that need work, with what to ask the engineer and a draft built from what is on the ticket."""
    ticket_id: str
    summary: str
    application: str | None
    closed_at: datetime | None
    notes: str | None = Field(..., description="The close notes as written; never changed")
    score: int | None = Field(..., examples=[2], description="Out of 6; none when the rules stopped the notes")
    rule: str | None = Field(..., examples=["too_short"])
    reason: str
    questions: list[str]
    draft_notes: str | None = Field(..., description="Only facts from the ticket; gaps are marked [engineer to add: ...]")


class ClosureReviewCreate(BaseModel):
    """An engineer's decision on the latest check."""
    action: Literal["accepted", "edited", "rejected"]
    reviewer: str = Field(..., min_length=3, examples=["ravi.shankar@contoso.com"])
    final_text: str | None = Field(None, description="Required to edit: the notes the engineer settled on")
    reason_code: Literal["check_wrong", "notes_fine", "other"] | None = Field(None, description="Required to reject")
    note: str | None = None


class ClosureReviewOut(BaseModel):
    """A stored decision."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: str
    agent_run_id: int
    action: str
    final_text: str | None
    reason_code: str | None
    note: str | None
    reviewer: str
    created_at: datetime


class ClosureReportOut(BaseModel):
    """How good the close notes are, and how often engineers say the check was wrong."""
    days: int
    checks: dict[str, int] = Field(..., examples=[{"good": 8, "needs_work": 3}], description="Checks by verdict")
    reviewed: int
    by_action: dict[str, int]
    by_reason: dict[str, int]
    by_rule: dict[str, int] = Field(..., examples=[{"too_short": 2}], description="Why notes were stopped by the rules")
    check_wrong_rate: float = Field(..., examples=[0.1], description="Share of decisions that rejected the check")
