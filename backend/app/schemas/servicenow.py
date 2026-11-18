"""ServiceNow ticket schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ServiceNowTicketBase(BaseModel):
    ticket_id: str
    caller: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assignment_group: Optional[str] = None
    service: Optional[str] = None
    resolution_notes: Optional[str] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    dq_flag: bool = False
    dq_reason: Optional[str] = None


class ServiceNowTicketDetail(ServiceNowTicketBase):
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ServiceNowTicketList(BaseModel):
    total: int
    items: list[ServiceNowTicketDetail]


class ServiceNowIngestResponse(BaseModel):
    message: str
    total_processed: int
    created: int
    updated: int
    skipped: int = 0
    filename: str | None = None
