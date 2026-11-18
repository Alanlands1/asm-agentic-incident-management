"""Data Quality (DQ) rules and runs API endpoints."""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.dq import DQRule, DQRun, DQRunTicket, TicketSource as TicketSourceModel
from app.models.servicenow import ServiceNowTicket
from app.schemas.dq import (
    DQApplyTo,
    DQRuleCreate,
    DQRuleList,
    DQRuleResponse,
    DQRuleUpdate,
    DQRunCreate,
    DQRunList,
    DQRunMatchesList,
    DQRunResponse,
    DQRunTicketMatchResponse,
    TicketSource,
    TicketSourceResponse,
)
from app.services.dq import execute_dq_run, revert_dq_run

router = APIRouter(prefix="/dq", tags=["data-quality"])

ALLOWED_RULE_FIELDS = {
    "ticket_id",
    "caller",
    "short_description",
    "description",
    "priority",
    "assignment_group",
    "service",
    "resolution_notes",
    "opened_at",
    "closed_at",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------
# Rules Endpoints
# ---------------------------------------------------------


@router.get("/sources", response_model=list[TicketSourceResponse], summary="List available ticket sources")
async def list_sources(
    db: AsyncSession = Depends(get_db),
) -> list[TicketSourceResponse]:
    """Return available ticket source reference records from database (with enum fallback)."""
    sources = await db.scalars(select(TicketSourceModel).where(TicketSourceModel.is_active.is_(True)))
    source_list = list(sources.all())
    if not source_list:
        # Fallback to seeded standard enums if table not yet seeded in dev/test
        return [
            TicketSourceResponse(
                code=s.value,
                name="ServiceNow" if s.value == "servicenow" else s.name.capitalize(),
                description=f"Inbound tickets from {s.value}",
                is_active=True,
            )
            for s in TicketSource
        ]
    return [
        TicketSourceResponse(
            code=s.code,
            name=s.name,
            description=s.description,
            is_active=s.is_active,
        )
        for s in source_list
    ]


@router.post("/rules", response_model=DQRuleResponse, status_code=status.HTTP_201_CREATED, summary="Create DQ rule")
async def create_rule(
    payload: DQRuleCreate,
    db: AsyncSession = Depends(get_db),
) -> DQRule:
    """Create a new DQ rule."""
    if payload.field not in ALLOWED_RULE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid field '{payload.field}'. Must be one of: {sorted(ALLOWED_RULE_FIELDS)}",
        )

    # Name uniqueness check among active rules
    existing = await db.scalar(
        select(DQRule).where(
            func.lower(DQRule.name) == payload.name.strip().lower(),
            DQRule.deleted_at.is_(None),
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"Rule with name '{payload.name}' already exists")

    rule = DQRule(
        name=payload.name.strip(),
        description=payload.description,
        field=payload.field,
        operator=payload.operator.value,
        value=payload.value,
        source=payload.source,
        service=payload.service,
        apply_to=payload.apply_to.value,
        is_enabled=payload.is_enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get("/rules", response_model=DQRuleList, summary="List DQ rules")
async def list_rules(
    is_enabled: Optional[bool] = Query(None, description="Filter by active enabled status"),
    source: Optional[TicketSource] = Query(None, description="Filter by source"),
    service: Optional[str] = Query(None, description="Filter by service"),
    apply_to: Optional[DQApplyTo] = Query(None, description="Filter by apply_to"),
    include_deleted: bool = Query(False, description="Include soft-deleted rules"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DQRuleList:
    """List DQ rules, ordered by ID."""
    query = select(DQRule)
    if not include_deleted:
        query = query.where(DQRule.deleted_at.is_(None))
    if is_enabled is not None:
        query = query.where(DQRule.is_enabled == is_enabled)
    if source is not None:
        query = query.where(DQRule.source == source)
    if service is not None:
        query = query.where(DQRule.service == service)
    if apply_to is not None:
        query = query.where(DQRule.apply_to == apply_to.value)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    items = await db.scalars(query.order_by(DQRule.id.asc()).limit(limit).offset(offset))
    return DQRuleList(total=total or 0, items=list(items.all()))


@router.get("/rules/{rule_id}", response_model=DQRuleResponse, summary="Get one DQ rule")
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
) -> DQRule:
    """Get single DQ rule by ID."""
    rule = await db.get(DQRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return rule


@router.patch("/rules/{rule_id}", response_model=DQRuleResponse, summary="Update DQ rule")
@router.put("/rules/{rule_id}", response_model=DQRuleResponse, summary="Update DQ rule")
async def update_rule(
    rule_id: int,
    payload: DQRuleUpdate,
    db: AsyncSession = Depends(get_db),
) -> DQRule:
    """Update rule configuration."""
    rule = await db.get(DQRule, rule_id)
    if not rule or rule.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"Active rule {rule_id} not found")

    update_data = payload.model_dump(exclude_unset=True)

    if "field" in update_data and update_data["field"] not in ALLOWED_RULE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid field '{update_data['field']}'. Must be one of: {sorted(ALLOWED_RULE_FIELDS)}",
        )

    if "name" in update_data and update_data["name"]:
        name_clean = update_data["name"].strip()
        existing = await db.scalar(
            select(DQRule).where(
                func.lower(DQRule.name) == name_clean.lower(),
                DQRule.id != rule_id,
                DQRule.deleted_at.is_(None),
            )
        )
        if existing:
            raise HTTPException(status_code=400, detail=f"Rule with name '{name_clean}' already exists")
        rule.name = name_clean

    for attr, val in update_data.items():
        if attr == "name":
            continue
        if attr in ("operator", "apply_to") and val is not None:
            setattr(rule, attr, val.value if hasattr(val, "value") else str(val))
        else:
            setattr(rule, attr, val)

    rule.updated_at = utcnow()
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}/toggle", response_model=DQRuleResponse, summary="Toggle rule enabled state")
async def toggle_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
) -> DQRule:
    """Toggle is_enabled for a DQ rule."""
    rule = await db.get(DQRule, rule_id)
    if not rule or rule.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"Active rule {rule_id} not found")

    rule.is_enabled = not rule.is_enabled
    rule.updated_at = utcnow()
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", response_model=DQRuleResponse, summary="Soft delete DQ rule")
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
) -> DQRule:
    """Soft delete a DQ rule (sets deleted_at)."""
    rule = await db.get(DQRule, rule_id)
    if not rule or rule.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"Active rule {rule_id} not found")

    rule.deleted_at = utcnow()
    await db.commit()
    await db.refresh(rule)
    return rule


# ---------------------------------------------------------
# Runs Endpoints
# ---------------------------------------------------------


@router.post("/runs", response_model=DQRunResponse, status_code=status.HTTP_201_CREATED, summary="Apply DQ rules")
async def apply_rules(
    payload: DQRunCreate = DQRunCreate(),
    db: AsyncSession = Depends(get_db),
) -> DQRun:
    """Execute DQ rule evaluation on tickets."""
    return await execute_dq_run(db, scope=payload.scope.value, trigger=payload.trigger.value)


@router.get("/runs", response_model=DQRunList, summary="List DQ runs")
async def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DQRunList:
    """List execution history of DQ runs, newest first."""
    query = select(DQRun).order_by(DQRun.started_at.desc())
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    items = await db.scalars(query.limit(limit).offset(offset))
    return DQRunList(total=total or 0, items=list(items.all()))


@router.get("/runs/{run_id}", response_model=DQRunResponse, summary="Get DQ run")
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> DQRun:
    """Get single DQ run detail by ID."""
    run = await db.get(DQRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"DQ run {run_id} not found")
    return run


@router.get("/runs/{run_id}/matches", response_model=DQRunMatchesList, summary="List matches for a DQ run")
async def get_run_matches(
    run_id: int,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DQRunMatchesList:
    """Get tickets flagged by a specific run and the rule that matched."""
    run = await db.get(DQRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"DQ run {run_id} not found")

    query = (
        select(
            DQRunTicket,
            DQRule.name.label("rule_name"),
            ServiceNowTicket.short_description.label("ticket_short_description"),
            ServiceNowTicket.service.label("ticket_service"),
            ServiceNowTicket.priority.label("ticket_priority"),
        )
        .join(DQRule, DQRunTicket.rule_id == DQRule.id)
        .join(ServiceNowTicket, DQRunTicket.ticket_id == ServiceNowTicket.ticket_id)
        .where(DQRunTicket.run_id == run_id)
    )

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.execute(query.limit(limit).offset(offset))

    matches = []
    for match_record, rule_name, short_desc, service, priority in rows.all():
        matches.append(
            DQRunTicketMatchResponse(
                run_id=match_record.run_id,
                ticket_id=match_record.ticket_id,
                rule_id=match_record.rule_id,
                rule_name=rule_name,
                reverted_dq_flag=match_record.reverted_dq_flag,
                reverted_dq_reason=match_record.reverted_dq_reason,
                ticket_short_description=short_desc,
                ticket_service=service,
                ticket_priority=priority,
            )
        )

    return DQRunMatchesList(total=total or 0, items=matches)


@router.post("/runs/{run_id}/revert", response_model=DQRunResponse, summary="Revert a DQ run")
async def revert_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> DQRun:
    """Revert flag state of tickets flagged in this run."""
    return await revert_dq_run(db, run_id)
