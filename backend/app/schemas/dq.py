"""Data Quality (DQ) schemas for rules, runs, and matches."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DQOperator(str, Enum):
    equals = "equals"
    not_equals = "not_equals"
    contains = "contains"
    not_contains = "not_contains"
    starts_with = "starts_with"
    regex = "regex"
    is_empty = "is_empty"
    is_not_empty = "is_not_empty"
    length_lt = "length_lt"
    length_gt = "length_gt"


class TicketSource(str, Enum):
    servicenow = "servicenow"
    jira = "jira"
    mailbox = "mailbox"


class TicketSourceResponse(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class DQApplyTo(str, Enum):
    existing = "existing"
    new = "new"
    both = "both"


class DQRunTrigger(str, Enum):
    manual = "manual"
    ingestion = "ingestion"


class DQRunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    reverted = "reverted"


class DQRuleBase(BaseModel):
    name: str = Field(..., max_length=128)
    description: Optional[str] = None
    field: str = Field(..., max_length=64)
    operator: DQOperator
    value: Optional[str] = None
    source: Optional[TicketSource] = None
    service: Optional[str] = Field(None, max_length=64)
    apply_to: DQApplyTo = DQApplyTo.both
    is_enabled: bool = True

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, v: Any) -> Optional[str]:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            val = v.strip().lower()
            return val if val else None
        return v


class DQRuleCreate(DQRuleBase):
    pass


class DQRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    description: Optional[str] = None
    field: Optional[str] = Field(None, max_length=64)
    operator: Optional[DQOperator] = None
    value: Optional[str] = None
    source: Optional[TicketSource] = None
    service: Optional[str] = Field(None, max_length=64)
    apply_to: Optional[DQApplyTo] = None
    is_enabled: Optional[bool] = None

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, v: Any) -> Optional[str]:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            val = v.strip().lower()
            return val if val else None
        return v


class DQRuleResponse(DQRuleBase):
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DQRuleList(BaseModel):
    total: int
    items: list[DQRuleResponse]


class DQRunCreate(BaseModel):
    scope: DQApplyTo = DQApplyTo.both
    trigger: DQRunTrigger = DQRunTrigger.manual


class DQRunResponse(BaseModel):
    id: int
    trigger: DQRunTrigger
    scope: DQApplyTo
    rules_snapshot: list[dict[str, Any]]
    tickets_evaluated: int
    tickets_flagged: int
    status: DQRunStatus
    started_at: datetime
    finished_at: Optional[datetime] = None
    reverted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DQRunList(BaseModel):
    total: int
    items: list[DQRunResponse]


class DQRunTicketMatchResponse(BaseModel):
    run_id: int
    ticket_id: str
    rule_id: int
    rule_name: Optional[str] = None
    reverted_dq_flag: bool
    reverted_dq_reason: Optional[str] = None
    ticket_short_description: Optional[str] = None
    ticket_service: Optional[str] = None
    ticket_priority: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DQRunMatchesList(BaseModel):
    total: int
    items: list[DQRunTicketMatchResponse]
