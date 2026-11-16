"""Behind every persona page (lead, engineer, and any added later): GET /personas/board and /personas/activity."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.personas import service

router = APIRouter(prefix="/personas", tags=["personas"])


class Totals(BaseModel):
    open: int
    p1_p2: int
    sla_breached: int
    sla_at_risk: int
    waiting_review: int
    unassigned: int


class PersonLoad(BaseModel):
    name: str | None  # None: no engineer yet
    open: int
    p1_p2: int
    breached: int
    waiting_review: int


class BoardTicket(BaseModel):
    id: str
    summary: str | None
    application: str | None
    priority: int | None  # the priority in force; None until Triage has run
    priority_from: str | None  # reviewed or recommended
    sla_state: str | None  # ok, watch, breach_likely, breached; None below P2
    minutes_left: int | None
    used_percent: int | None  # share of the SLA target used
    assignee: str | None
    team: str | None
    stage: str
    opened_at: datetime | None
    url: str | None  # the ticket in Jira, where it is assigned
    triage_reason: str | None  # why Triage recommends its priority
    reported_priority: int | None  # as reported in the source, 1 is the highest
    missing: list[str]  # what Data Quality still needs from the reporter, e.g. what_happened
    has_draft: bool  # Data Quality drafted the message that asks the reporter for them
    due_at: datetime | None  # when the SLA target is reached; None below P2
    runbook: str | None  # knowledge base id of the rule Triage matched, e.g. KB-ORD-003


class BoardOut(BaseModel):
    at: datetime
    totals: Totals
    people: list[PersonLoad]
    tickets: list[BoardTicket]


@router.get("/board", response_model=BoardOut, summary="Open tickets with priority, SLA and engineer, for a persona page")
async def board(
    person: str | None = Query(None, description="Only this engineer's tickets (their name in Jira)."),
    at: datetime | None = Query(None, description="Measure SLA at this time; defaults to now."),
    db: AsyncSession = Depends(get_db),
) -> BoardOut:
    return await db.run_sync(service.board, person, at)


class ActivityItem(BaseModel):
    at: datetime
    kind: str  # data_quality, triage, triage_rerun, summary_sent, sla_warning, first_message, review, sync_failed
    ticket_ids: list[str]
    actor: str | None = None  # who did it; None when the system did
    action: str | None = None  # review: accepted, edited or rejected
    priority: int | None = None  # triage_rerun: the new recommendation; review: the priority decided
    previous_priority: int | None = None  # triage_rerun: the recommendation before it
    error: str | None = None  # sync_failed


@router.get("/activity", response_model=list[ActivityItem], summary="What the agents and people did, newest first")
async def activity(
    person: str | None = Query(None, description="Only events on this engineer's tickets (their name in Jira)."),
    since: datetime | None = Query(None, description="Only events from this time on; defaults to the last 24 hours."),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[ActivityItem]:
    return await db.run_sync(service.activity, person, since, limit)
