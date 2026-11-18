"""Triage agent schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TriageRunResponse(BaseModel):
    """Result of triaging the tickets that passed Data Quality."""
    evaluated: int = Field(..., examples=[20])
    skipped: int = Field(..., examples=[0])
    model_errors: int = Field(0, examples=[0], description="Tickets left in dq_passed because the model gave no usable answer")
    needs_review: int = Field(0, examples=[2], description="Recommendations far from the reporter's priority")
    by_verdict: dict[str, int] = Field(..., examples=[{"P1": 3, "P2": 4, "P3": 9, "P4": 3, "uncertain": 1}])


class TriageCheckResponse(BaseModel):
    """Recommended priority for one ticket."""
    ticket_id: str = Field(..., examples=["AMS-1209"])
    verdict: str = Field(..., examples=["P3"])
    stage: str = Field(..., examples=["rules"], description="rules, or model when the rules could not decide")
    pipeline_status: str = Field(..., examples=["triaged"])
    output: dict[str, Any] = Field(..., description="Priority, reported priority, rule, reason; model stage adds the audit")


class ReviewQueueItem(BaseModel):
    """A triaged ticket waiting for an engineer, with what the agent recommends and why."""
    ticket_id: str = Field(..., examples=["AMS-1209"])
    summary: str
    application: str | None
    opened_at: datetime | None
    reported_priority: int | None = Field(..., examples=[1], description="What the reporter chose; never changed")
    recommended_priority: int = Field(..., examples=[3])
    rule: str | None = Field(..., examples=["account_locked"])
    reason: str
    stage: str = Field(..., examples=["rules"], description="rules, or model when the rules could not settle it")
    flags: list[str] = Field(..., examples=[["downgrade"]],
                             description="downgrade (a P1/P2 lowered), leaned_high, kept_reported, large_shift")


class ReviewCreate(BaseModel):
    """An engineer's decision on the latest recommendation."""
    action: Literal["accepted", "edited", "rejected"]
    reviewer: str = Field(..., min_length=3, examples=["ravi.shankar@contoso.com"])
    priority: int | None = Field(None, ge=1, le=5, description="Required to edit; optional on a rejection")
    reason_code: Literal["wrong_facts", "wrong_rule", "wrong_application", "no_rule_fits", "other"] | None = Field(
        None, description="Why the recommendation was changed; required to reject"
    )
    note: str | None = None


class ReviewOut(BaseModel):
    """A stored decision."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: str
    agent_run_id: int
    action: str
    final_priority: int | None
    reason_code: str | None
    note: str | None
    reviewer: str
    created_at: datetime


class ReviewReportOut(BaseModel):
    """How often engineers change the agent's recommendation, and where."""
    days: int
    reviewed: int
    agreement: float = Field(..., examples=[0.85], description="Share of recommendations accepted as they were")
    by_action: dict[str, int] = Field(..., examples=[{"accepted": 17, "edited": 2, "rejected": 1}])
    raised_by_engineer: int
    lowered_by_engineer: int
    by_reason: dict[str, int] = Field(..., examples=[{"no_rule_fits": 2}])
    by_rule: dict[str, dict[str, int]] = Field(..., examples=[{"functional_error": {"accepted": 1, "edited": 2}}])
    by_stage: dict[str, dict[str, int]] = Field(..., examples=[{"rules": {"accepted": 15}, "model": {"edited": 2}}])
