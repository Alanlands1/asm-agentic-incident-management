"""Ticket request and response schemas."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.closure import ClosureReviewOut
from app.schemas.triage import ReviewOut


class IngestResponse(BaseModel):
    """Result of loading the source workbook."""
    created: int = Field(..., examples=[100])
    updated: int = Field(..., examples=[0])
    by_source: dict[str, int] = Field(..., examples=[{"ServiceNow": 50, "JIRA": 30, "Mailbox": 20}])


class AgentRunOut(BaseModel):
    """One agent's verdict on a ticket."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent: str
    verdict: str
    output: dict[str, Any]
    created_at: datetime


class CommentCreate(BaseModel):
    """A reply on a ticket."""
    author_email: str = Field(..., min_length=3, examples=["priya.raman@contoso.com"])
    body: str = Field(..., min_length=1, examples=["It is PayrollPro, the payslip PDF fails with PDF-GEN-500 since Monday."])
    post_to_jira: bool = Field(False, description="Also add the reply to the Jira issue as a comment (needs JIRA_WRITE_BACK)")


class CommentOut(BaseModel):
    """A stored reply."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_email: str
    from_reporter: bool
    body: str
    created_at: datetime


class FeedbackCreate(BaseModel):
    """A person's rating of one agent's result."""
    agent_run_id: int
    stars: int = Field(..., ge=1, le=5)  # thumbs: 5 up, 1 down
    reason: str = Field("", max_length=4000, description="Optional: quick reasons and a suggestion",
                        examples=["Wrong runbook. The runbook is for the card gateway, this is the bank transfer file."])
    reviewer: str = Field(..., min_length=3, examples=["priya.raman@contoso.com"])

    @field_validator("reason", mode="before")
    @classmethod
    def _no_blank_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class FeedbackOut(BaseModel):
    """A stored rating."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_run_id: int
    agent: str
    stars: int
    reason: str
    reviewer: str
    created_at: datetime


class ChatCreate(BaseModel):
    """A message to the AI assistant about one ticket."""
    message: str = Field(..., min_length=1, max_length=4000, examples=["The job log says ORA-01555 at 02:10. What now?"])
    author: str = Field(..., min_length=3, examples=["priya.raman@contoso.com"])


class ChatUse(BaseModel):
    """Make the assistant's proposed fix the ticket's suggested fix."""
    run_id: int
    reviewer: str = Field(..., min_length=3)


class ReviewStepCreate(BaseModel):
    """The engineer submits the closure note for the lead's review."""
    reviewer: str = Field(..., min_length=3, examples=["priya.raman@contoso.com"])


class LeadReviewCreate(BaseModel):
    """The lead's decision on a closure note in review."""
    action: Literal["approved", "sent_back"] = Field(..., description="approved; sent_back: with what to change (note)")
    note: str | None = Field(None, max_length=4000, examples=["Say how you checked that all four deals show paid."])
    reviewer: str = Field(..., min_length=3, examples=["lead@contoso.com"])


class AssignCreate(BaseModel):
    """The lead gives the ticket to an engineer, or takes it back."""
    assignee: str | None = Field(
        None, max_length=128, description="The engineer's name as in Jira; None: nobody", examples=["Ravi Kumar"])
    by: str = Field(..., min_length=3, examples=["lead@contoso.com"])


class FixOutcomeCreate(BaseModel):
    """The engineer's answer to the latest suggested fix."""
    agent_run_id: int
    outcome: Literal["worked", "partly", "wrong"] = Field(
        ..., description="worked; partly: worked with changes (note: what changed); wrong: did not work (note: what happened)")
    note: str | None = Field(
        None, max_length=4000, examples=["The re-run failed again with PAD_FILE_REJECT: trailer 412, file 411 rows."])
    reviewer: str = Field(..., min_length=3, examples=["priya.raman@contoso.com"])


class TicketSummary(BaseModel):
    """Ticket fields shown in lists."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    reporter_name: Optional[str]
    application: Optional[str]
    summary: str
    reported_priority: Optional[int]
    reported_priority_label: Optional[str]
    status: str
    pipeline_status: str
    opened_at: Optional[datetime]


class TicketDetail(TicketSummary):
    """Full ticket including the original source row and agent audit trail."""
    reporter_email: Optional[str]
    reporter_department: Optional[str]
    channel: Optional[str]
    category: Optional[str]
    subcategory: Optional[str]
    environment: Optional[str]
    description: str
    attachments: Optional[str]
    source_status: Optional[str]
    assignment_group: Optional[str]
    assignee: Optional[str]
    resolution_notes: Optional[str]
    resolved_at: Optional[datetime]
    closed_at: Optional[datetime]
    raw: dict[str, Any]
    guidance: Optional[str] = Field(None, description="A person's note to the agents, read with the description on every run")
    agent_runs: list[AgentRunOut]
    comments: list[CommentOut]
    feedback: list[FeedbackOut] = Field(default_factory=list, description="Star ratings people gave the agents' results")
    decided: Optional[ReviewOut] = Field(None, description="The last decision a person made on the priority, here or in Jira")
    closure_decision: Optional[ClosureReviewOut] = Field(None, description="The last decision a person made on the close notes")
    changed: dict[str, bool] = Field(
        default_factory=dict,
        description="Per agent that ran before: true when what it would see now differs from its last run, so running again "
                    "can give a different answer")
    agents_running: bool = Field(False, description="True while the agents' pass after a Jira sync is running")
    fix_outcomes: list[ReviewOut] = Field(
        default_factory=list, description="The engineer's answers on the suggested fixes (worked, partly, wrong), oldest first")
    lead_review_required: bool = Field(False, description="A lead approves the closure note before it is sent (LEAD_REVIEW)")
    lead_reviews: list[ReviewOut] = Field(
        default_factory=list, description="Submitted for review, approved, sent back (with the comment), oldest first")


class TicketList(BaseModel):
    """Paginated ticket list."""
    total: int
    items: list[TicketSummary]
