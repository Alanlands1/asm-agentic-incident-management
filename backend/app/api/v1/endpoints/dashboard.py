"""Admin home: one summary of ticket flow, agent results, the review queue, sync health and attention; and daily trends."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import require_role
from app.db.session import get_db
from app.services import dashboard, reports, service_report

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


class ApplicationReport(BaseModel):
    application: str
    opened: int
    open: int = Field(description="Open now, whenever opened")
    resolved: int = Field(description="Resolved or closed in the period")
    p1_p2: int
    sla_met: float | None = Field(description="Share of tickets opened in the period whose SLA is decided and was met")
    mean_hours_to_resolve: float | None
    runbook_fix: float | None = Field(description="Share of tickets with a Resolution answer that found a runbook fix")
    kb_covered: float | None = Field(description="Share of saved cases a knowledge article covers")


class AgentReport(BaseModel):
    agent: str
    runs: int
    model_used: float | None
    model_failed: int
    tokens: int
    rated: int
    correct: float | None
    partially_correct: float | None
    incorrect: float | None


class OutcomeReport(BaseModel):
    application: str
    fixes_confirmed: int
    first_fix: float | None = Field(description="Share of confirmed fixes that worked on the first suggestion")
    mean_attempts: float | None
    escalated: int = Field(description="Tickets escalated to the lead after repeated failed fixes")
    mean_closure_score: float | None = Field(description="Out of 6")
    closure_needs_work: float | None
    lead_approved: int
    lead_returned: int


class EngineerReport(BaseModel):
    engineer: str
    open: int
    closed: int
    mean_hours_to_resolve: float | None
    sla_breached: int
    priority_changes: int


class ReportsOut(BaseModel):
    days: int
    since: datetime
    applications: list[ApplicationReport]
    agents: list[AgentReport]
    outcomes: list[OutcomeReport]
    engineers: list[EngineerReport]


@router.get("/reports", response_model=ReportsOut, summary="Admin reports for a period",
            dependencies=[Depends(require_role("admin"))])
async def get_reports(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> ReportsOut:
    """Tickets by application, agent performance, fix and closure outcomes, and engineers, for the last `days` days."""
    return ReportsOut(**await db.run_sync(reports.reports, days))


class ServiceMeasures(BaseModel):
    opened: int
    resolved: int
    resolved_by_priority: dict[str, int] = Field(description="P1, P2, P3 and P4–P5")
    mttr_hours: float | None = Field(description="Mean hours from opened to resolved")
    median_hours: float | None
    sla_met: float | None = Field(description="Share of P1/P2 tickets resolved within their target")
    first_fix: float | None = Field(description="Share of confirmed fixes that worked on the first suggestion")


class ServiceKpis(BaseModel):
    current: ServiceMeasures
    previous: ServiceMeasures = Field(description="The period before, of the same length where the calendar allows")
    backlog: int = Field(description="Open now")
    backlog_past_sla: int
    spark: dict[str, list[float | None]] = Field(description="The last 6 months of opened, resolved, MTTR, SLA met, first fix")


class ServiceMonthly(BaseModel):
    months: list[str] = Field(examples=[["2025-12", "2026-01"]])
    opened: list[int]
    resolved: list[int]
    resolved_by_priority: dict[str, list[int]]
    mttr_by_priority: dict[str, list[float | None]]
    sla_met: list[float | None]
    resolved_by_application: dict[str, list[int]]


class ApplicationPerformance(BaseModel):
    application: str
    resolved: int
    mttr_hours: float | None
    sla_met: float | None


class ServiceOut(BaseModel):
    period: str
    start: datetime
    end: datetime
    applications: list[str] = Field(description="Every application, for the filter")
    sla_targets: dict[str, int] = Field(description="Hours, by priority")
    kpis: ServiceKpis
    monthly: ServiceMonthly = Field(description="The last 12 months, this one so far included")
    by_application: list[ApplicationPerformance] = Field(description="Resolved in the period, slowest first")
    ageing: list[dict[str, Any]] = Field(description="Open tickets by age and priority")


@router.get("/service", response_model=ServiceOut, summary="Service performance: KPIs and monthly trends",
            dependencies=[Depends(require_role("admin"))])
async def get_service(
    period: Literal["mtd", "last_month", "qtd", "ytd", "12m"] = "mtd",
    application: str | None = None,
    priority: int | None = Query(None, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
) -> ServiceOut:
    """Opened and resolved by priority, MTTR, SLA met and first-time fix for the period against the one before, the
    last 12 months by month and by application, and the open backlog by age."""
    return ServiceOut(**await db.run_sync(service_report.service_performance, period, application, priority))
