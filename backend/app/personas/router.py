"""Behind every persona page (lead, engineer, and any added later): GET /personas/board and /personas/activity."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.personas import availability, service
from app.services import jira

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
    dq_verdict: str | None = None  # passed, needs_info, rejected
    fix_verdict: str | None = None  # resolved (a fix was suggested), no_match
    fix_answer: str | None = None  # the engineer's answer on the latest fix: worked, partly, wrong
    fix_rated: bool = False  # the latest fix has a star rating
    closure_verdict: str | None = None  # good, needs_work
    closure_score: int | None = None  # out of 6
    lead_step: str | None = None  # the latest lead review step: submitted, approved, sent_back
    lead_by: str | None = None  # who took it
    review_required: bool = False  # a lead approves this closure note before it is sent


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


@router.get("/people", response_model=list[str], summary="Everyone a ticket can be assigned to")
async def people(db: AsyncSession = Depends(get_db)) -> list[str]:
    """Everyone Jira lets an issue of the selected projects be assigned to, and everyone who has held a ticket here."""
    return [p["name"] for p in await roster(db)]


class Person(BaseModel):
    name: str
    in_jira: bool | None  # Jira lets them be assigned; None: Jira has not been asked (not set up, or away)
    held: bool  # has held a ticket here
    member: bool  # on the team: suggested for tickets, and has a shift status


@router.get("/roster", response_model=list[Person], summary="Everyone a ticket can go to, and who is on the team")
async def roster(db: AsyncSession = Depends(get_db)) -> list[Person]:
    await jira.refresh_people(db)
    return await db.run_sync(service.roster)


class Suggestion(BaseModel):
    id: str  # an open ticket nobody has
    name: str  # the engineer suggested for it
    reason: str  # e.g. "resolved 4 OrderHub tickets · holds 2 now, 5 after this batch"


class Availability(BaseModel):
    state: str  # on_shift, off_shift, on_leave
    until: date | None = None  # on_leave: its last day


@router.get("/availability", response_model=dict[str, Availability], summary="Who is on shift, off shift or on leave now")
async def team_status(db: AsyncSession = Depends(get_db)) -> dict[str, Availability]:
    await jira.refresh_people(db)
    return await db.run_sync(service.team_status)


class Suggestions(BaseModel):
    limit: int  # open tickets at which an engineer is suggested no more, except a P1 or P2
    suggestions: list[Suggestion]  # an unassigned ticket missing here has no one with room


@router.get("/suggestions", response_model=Suggestions, summary="An engineer for each unassigned open ticket")
async def suggestions(db: AsyncSession = Depends(get_db)) -> Suggestions:
    await jira.refresh_people(db)
    return Suggestions(limit=availability.config().max_open, suggestions=await db.run_sync(service.suggestions))


class AgentDay(BaseModel):
    done: int  # tickets the agent worked on (Triage: given a priority; Resolution: a fix suggested)
    rated: int = 0  # results rated in the last 7 days, by hand or from use (a person's latest rating counts)
    right: int = 0  # of those, rated right (thumbs up)
    flagged: int  # DQ: need details; Triage: approved without a person; Resolution: fixes that worked;
    # Closure Quality: notes good; Knowledge Builder: matched to an article


class TodayOut(BaseModel):
    data_quality: AgentDay
    triage: AgentDay
    resolution: AgentDay
    closure_quality: AgentDay
    knowledge_builder: AgentDay
    closed: int  # tickets closed since `since`
    opened: int  # tickets opened since `since`


@router.get("/today", response_model=TodayOut, summary="What each agent did today, and tickets closed")
async def today(
    since: datetime = Query(..., description="The viewer's midnight."),
    person: str | None = Query(None, description="Only this engineer's tickets."),
    db: AsyncSession = Depends(get_db),
) -> TodayOut:
    return await db.run_sync(service.today, since, person)


class ClosedItem(BaseModel):
    id: str
    summary: str | None
    at: datetime
    kb: str | None  # the article the case matched, "draft" when it drafted one, None when neither


@router.get("/closed", response_model=list[ClosedItem], summary="Tickets a person closed with Send, newest first")
async def closed(
    person: str = Query(..., min_length=1), days: int = Query(7, ge=1, le=90), db: AsyncSession = Depends(get_db)
) -> list[ClosedItem]:
    return await db.run_sync(service.closed_by, person, days)


class ActivityItem(BaseModel):
    at: datetime
    # data_quality, triage, triage_rerun, summary_sent, command_answered, sla_warning, first_message, review,
    # fix_answer, lead_review, closure_decision, closed, assigned, sync_failed
    kind: str
    ticket_ids: list[str]
    actor: str | None = None  # who did it; None when the system did
    action: str | None = None  # review: accepted, edited, rejected; fix_answer: worked, partly, wrong;
    # lead_review: submitted, approved, sent_back; assigned: the engineer it went to (None: nobody)
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
