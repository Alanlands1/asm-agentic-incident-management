"""Admin home: one summary of ticket flow, agent results, the review queue, sync health and attention; and daily trends."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services import dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class TicketFlow(BaseModel):
    by_source_today: dict[str, int]
    by_stage: dict[str, int]


class AgentStats(BaseModel):
    checked: int
    by_verdict: dict[str, int]
    model_used: int
    model_failed: int


class ReviewQueue(BaseModel):
    size: int
    oldest_at: datetime | None
    p1_p2: int


class Agreement(BaseModel):
    days: int
    reviewed: int
    agreement: float


class SyncHealth(BaseModel):
    state: Literal["off", "never", "running", "stale"]
    minutes: int
    last_started_at: datetime | None
    last_error: str | None
    last_summary: str | None


class DashboardOut(BaseModel):
    tickets: TicketFlow
    agents: dict[str, AgentStats]
    review_queue: ReviewQueue
    agreement: Agreement
    syncs: dict[str, SyncHealth]
    attention: int


@router.get("/summary", response_model=DashboardOut, summary="Numbers for the admin home")
async def summary(
    since: datetime | None = Query(None, description="Start of the viewer's day (default: today 00:00 UTC)"),
    db: AsyncSession = Depends(get_db),
) -> DashboardOut:
    start = since or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return DashboardOut(**await db.run_sync(dashboard.summary, start))


class TrendsOut(BaseModel):
    days: list[datetime]  # the start of each day
    tickets: dict[str, list[int]]  # source -> tickets opened, per day
    tokens: dict[str, list[int]]  # agent -> tokens in and out, per day
    tokens_in: int
    tokens_out: int
    model_calls: int
    sla_breaches: dict[str, list[int]]  # P1, P2 -> SLA times that ran out, per day
    sla_open: dict[str, int]  # open P1/P2 tickets now: breached, breach_likely
    reviews: dict[str, int]  # reviewer -> decisions in the period


@router.get("/trends", response_model=TrendsOut, summary="Daily numbers for the admin trends page")
async def trends(
    since: datetime | None = Query(None, description="Start of the viewer's first day (default: 00:00 UTC, `days` days back)"),
    days: int = Query(14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> TrendsOut:
    start = since or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    return TrendsOut(**await db.run_sync(dashboard.trends, start, days))
