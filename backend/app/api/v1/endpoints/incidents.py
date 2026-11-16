"""Incidents: what needs attention now, and sending or recording a P1/P2 first message."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.v1.endpoints.triage import _sla_item
from app.core.config import settings
from app.db.session import get_db
from app.models.ticket import Ticket
from app.schemas.storm import SlaItemOut, StormOut
from app.services import incidents, jira
from app.services.atlassian import AtlassianError

# shortcut: no auth, like the other console endpoints; who sent it is as given until there are logins.
router = APIRouter(prefix="/incidents", tags=["incidents"])


class FirstMessageSentIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    sent_by: str = Field(..., min_length=3, max_length=256)
    post_to_jira: bool = Field(False, description="Add the text to the Jira issue as a comment before recording it")


class FirstMessageSentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: str
    storm_id: int | None
    text: str
    sent_by: str
    sent_at: datetime


class AttentionItem(SlaItemOut):
    last_sent: FirstMessageSentOut | None = None
    can_post_to_jira: bool = False


class AttentionOut(BaseModel):
    storms: list[StormOut]
    p1_p2: list[AttentionItem]
    count: int = Field(..., description="Storms plus P1/P2 tickets without a sent first message")


def _attention(db: Session, at: datetime | None) -> AttentionOut:
    a = incidents.attention(db, at)
    members: dict[int, list[str]] = {}
    ids = [s.id for s in a.storms]
    for storm_id, ticket_id in db.execute(select(Ticket.storm_id, Ticket.id).where(Ticket.storm_id.in_(ids))):
        members.setdefault(storm_id, []).append(ticket_id)
    storms = [StormOut.model_validate(s).model_copy(update={"ticket_ids": sorted(members.get(s.id, []))}) for s in a.storms]
    items = []
    for i in a.items:
        sent = a.sent.get(i.ticket.id)
        last = FirstMessageSentOut.model_validate(sent) if sent else None
        to_jira = settings.JIRA_WRITE_BACK and i.ticket.source == "JIRA"
        items.append(AttentionItem(**_sla_item(i).model_dump(), last_sent=last, can_post_to_jira=to_jira))
    return AttentionOut(storms=storms, p1_p2=items, count=a.count)


@router.get("/attention", response_model=AttentionOut, summary="Storms and P1/P2 tickets that need a person now")
async def attention(
    at: datetime | None = Query(None, description="Treat this as the current time (default: now, UTC); for demos and tests"),
    db: AsyncSession = Depends(get_db),
) -> AttentionOut:
    return await db.run_sync(_attention, at)


@router.post(
    "/tickets/{ticket_id}/first-message", response_model=FirstMessageSentOut, status_code=201,
    summary="Post the first message to Jira, or record that a person sent it",
)
async def first_message_sent(
    ticket_id: str, payload: FirstMessageSentIn, db: AsyncSession = Depends(get_db)
) -> FirstMessageSentOut:
    """Records the text, who and when. With post_to_jira the text first goes on the Jira issue as a comment;
    without it nothing is sent from here: the person sent it themselves (Teams, email)."""
    ticket = await db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    if payload.post_to_jira:
        if ticket.source != "JIRA":
            raise HTTPException(status_code=409, detail=f"Ticket {ticket_id} did not come from Jira")
        try:
            await jira.post_comment(ticket.id, payload.text)
        except AtlassianError as exc:  # not recorded as sent: the comment is not on the issue
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def save(s: Session) -> FirstMessageSentOut:
        return FirstMessageSentOut.model_validate(incidents.record_sent(s, ticket, payload.text, payload.sent_by))

    return await db.run_sync(save)
