"""Knowledge Builder schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeRunResponse(BaseModel):
    """Result of saving and matching the resolved tickets whose close notes passed."""
    evaluated: int = Field(..., examples=[33])
    skipped: int = Field(..., examples=[0], description="Cases unchanged since their last match")
    model_errors: int = Field(0, examples=[0], description="Cases left unmatched because the model gave no usable answer")
    by_status: dict[str, int] = Field(..., examples=[{"matched": 30, "gap": 3}])
    drafts: dict[str, int] = Field(default_factory=dict, examples=[{"created": 2, "none": 1}],
                                   description="Per gap: created, joined, none, rejected_by_checks, waiting or failed")
    open_problems: int = Field(0, description="Open repeat-issue suggestions after this run")


class ResolvedCaseOut(BaseModel):
    """A saved case. All text is masked."""
    model_config = ConfigDict(from_attributes=True)
    ticket_id: str
    application: str | None
    summary: str
    notes: str = Field(..., description="The final close notes, names masked")
    score: int | None = Field(..., examples=[6], description="Closure Quality score, out of 6")
    match_status: Literal["matched", "gap", "uncertain"]
    kb_article_id: str | None = Field(..., examples=["KB-PAY-002"])
    match_method: str | None = Field(..., examples=["cited"], description="cited, code, keywords or model")
    closed_at: datetime | None


class AppCoverageOut(BaseModel):
    """How much of what is fixed in one application is already in the knowledge base."""
    application: str
    articles: int
    cases: int
    matched: int
    gap: int = Field(..., description="Cases no article covers: where a new article is needed")
    uncertain: int = Field(..., description="Cases the rules could not match and the model has not judged")
    outside_kb: int = Field(..., description="Gaps that are not knowledge gaps: a request, or a problem outside the application")
    drafts_waiting: int = Field(..., description="Drafted articles waiting for an expert")
    covered_share: float = Field(..., examples=[0.9], description="Matched cases as a share of all saved cases")
    unused_articles: list[str] = Field(..., description="Articles no resolved case has matched")


class KBDraftOut(BaseModel):
    """A drafted article. It counts only once an expert approves it; unknown parts read "[expert to add]"."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    application: str
    kb_id: str | None = Field(..., examples=["KB-PAY-006"], description="Given on approval")
    title: str
    symptoms: list[str]
    root_cause: str
    resolution_steps: list[str]
    escalation: str
    source_ticket_ids: list[str]
    status: Literal["draft", "approved", "rejected"]
    reviewer: str | None
    reason_code: str | None
    note: str | None
    decided_at: datetime | None
    created_at: datetime


class KBDraftReview(BaseModel):
    """An expert's decision on a draft."""
    action: Literal["approved", "edited", "rejected"]
    reviewer: str = Field(..., min_length=3, examples=["payroll.expert@contoso.com"])
    title: str | None = Field(None, description="To edit: any part the expert rewrites; the rest stays as drafted")
    symptoms: list[str] | None = None
    root_cause: str | None = None
    resolution_steps: list[str] | None = None
    escalation: str | None = None
    reason_code: Literal["not_a_known_issue", "duplicate", "wrong", "other"] | None = Field(
        None, description="Required to reject"
    )
    note: str | None = None


class ProblemCandidateOut(BaseModel):
    """The same issue closed again and again: a suggestion to open a problem record."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    application: str | None
    issue_key: str = Field(..., examples=["article:KB-PAY-002"], description="The article, or draft, the cases matched")
    ticket_ids: list[str]
    cases: int
    first_closed: datetime
    last_closed: datetime
    status: Literal["open", "accepted", "dismissed"]
    decided_by: str | None
    decided_at: datetime | None
    note: str | None


class ProblemDecision(BaseModel):
    """A person accepts the suggestion (and opens a problem record) or dismisses it."""
    action: Literal["accepted", "dismissed"]
    decided_by: str = Field(..., min_length=3, examples=["lead@contoso.com"])
    note: str | None = None
