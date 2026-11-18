"""Storm and SLA schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StormOut(BaseModel):
    """Many people reporting the same issue at once."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    application: str | None = Field(..., examples=["OrderHub"], description="None when it spans applications (login)")
    issue_key: str = Field(..., examples=["rule:checkout_failing"])
    main_ticket_id: str = Field(..., description="The ticket that is triaged; the others follow it")
    people: int = Field(..., examples=[6], description="Distinct reporters")
    ticket_count: int
    opened_at: datetime
    last_ticket_at: datetime
    status: Literal["open", "closed", "declared"]
    declared_by: str | None
    declared_at: datetime | None
    ticket_ids: list[str] = Field(default_factory=list)


class StormRunResponse(BaseModel):
    """Result of looking for storms among the open tickets."""
    created: int
    updated: int
    linked: int = Field(..., description="Tickets that now follow a main ticket")
    storms: list[StormOut]


class StormDeclare(BaseModel):
    """A person declares a major incident."""
    declared_by: str = Field(..., min_length=3, examples=["ravi.shankar@contoso.com"])


class FirstMessageOut(BaseModel):
    """The first message for a P1/P2, drafted from a template. A person sends it."""
    text: str = Field(..., examples=["OrderHub: Customers cannot complete checkout. 6 people have reported it so far. "
                                     "Teams are investigating. Ref AMS-1208. Next update 09:45."])
    send_by: datetime
    minutes_left: int = Field(..., description="Negative once the time to send it has passed")


class SlaItemOut(BaseModel):
    """An open P1/P2 ticket and how much of its SLA target is used."""
    ticket_id: str
    summary: str
    application: str | None
    priority: int = Field(..., examples=[1])
    priority_from: Literal["reviewed", "recommended"] = Field(..., description="reviewed: an engineer decided it")
    opened_at: datetime
    due_at: datetime
    used_percent: int = Field(..., examples=[52])
    state: Literal["ok", "watch", "breach_likely", "breached"]
    minutes_left: int
    storm_id: int | None
    first_message: FirstMessageOut
