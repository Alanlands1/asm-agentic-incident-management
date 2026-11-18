"""Data Quality (DQ) rule evaluation and run execution service."""

from datetime import datetime, timezone
import logging
import re
from typing import Any, Optional
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dq import DQRule, DQRun, DQRunTicket
from app.models.servicenow import ServiceNowTicket

logger = logging.getLogger("app.services.dq")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def evaluate_operator(operator: str, field_val: Any, rule_val: Optional[str]) -> bool:
    """Evaluate single operator against field value."""
    val_str = "" if field_val is None else str(field_val)
    target_str = "" if rule_val is None else str(rule_val)

    if operator == "is_empty":
        return field_val is None or str(field_val).strip() == ""
    if operator == "is_not_empty":
        return field_val is not None and str(field_val).strip() != ""
    if operator == "equals":
        return val_str.strip().lower() == target_str.strip().lower()
    if operator == "not_equals":
        return val_str.strip().lower() != target_str.strip().lower()
    if operator == "contains":
        return target_str.lower() in val_str.lower()
    if operator == "not_contains":
        return target_str.lower() not in val_str.lower()
    if operator == "starts_with":
        return val_str.lower().startswith(target_str.lower())
    if operator == "regex":
        try:
            return bool(re.search(target_str, val_str, re.IGNORECASE))
        except re.error:
            logger.warning(f"Invalid regex in DQ rule: {target_str}")
            return False
    if operator == "length_lt":
        try:
            return len(val_str) < int(target_str)
        except ValueError:
            return False
    if operator == "length_gt":
        try:
            return len(val_str) > int(target_str)
        except ValueError:
            return False
    return False


def ticket_matches_rule(rule: DQRule, ticket: ServiceNowTicket) -> bool:
    """Check if a ticket matches rule conditions (source, service, field operator)."""
    if rule.source:
        if rule.source.strip().lower() != "servicenow":
            return False

    if rule.service:
        if not ticket.service or ticket.service.strip().lower() != rule.service.strip().lower():
            return False

    if not hasattr(ticket, rule.field):
        return False

    field_val = getattr(ticket, rule.field)
    return evaluate_operator(rule.operator, field_val, rule.value)


async def execute_dq_run(
    db: AsyncSession,
    scope: str = "both",
    trigger: str = "manual",
) -> DQRun:
    """Apply active enabled DQ rules to tickets in scope (first match wins)."""
    # 1. Fetch active enabled rules
    rule_query = (
        select(DQRule)
        .where(DQRule.deleted_at.is_(None))
        .where(DQRule.is_enabled.is_(True))
    )
    if scope == "existing":
        rule_query = rule_query.where(DQRule.apply_to.in_(["existing", "both"]))
    elif scope == "new":
        rule_query = rule_query.where(DQRule.apply_to.in_(["new", "both"]))

    rule_res = await db.scalars(rule_query.order_by(DQRule.id.asc()))
    rules = list(rule_res.all())

    # Snapshot rules
    snapshot = [
        {
            "id": r.id,
            "name": r.name,
            "field": r.field,
            "operator": r.operator,
            "value": r.value,
            "source": r.source,
            "service": r.service,
            "apply_to": r.apply_to,
        }
        for r in rules
    ]

    # Create run entry
    run = DQRun(
        trigger=trigger,
        scope=scope,
        rules_snapshot=snapshot,
        tickets_evaluated=0,
        tickets_flagged=0,
        status="running",
        started_at=utcnow(),
    )
    db.add(run)
    await db.flush()

    # Query tickets (unresolved tickets for existing/both)
    ticket_query = select(ServiceNowTicket)
    if scope in ("existing", "both"):
        ticket_query = ticket_query.where(ServiceNowTicket.closed_at.is_(None))

    ticket_res = await db.scalars(ticket_query.order_by(ServiceNowTicket.opened_at.desc()))
    tickets = list(ticket_res.all())

    evaluated_count = 0
    flagged_count = 0

    for ticket in tickets:
        evaluated_count += 1
        for rule in rules:
            if ticket_matches_rule(rule, ticket):
                # First match wins
                match_record = DQRunTicket(
                    run_id=run.id,
                    ticket_id=ticket.ticket_id,
                    rule_id=rule.id,
                    reverted_dq_flag=ticket.dq_flag,
                    reverted_dq_reason=ticket.dq_reason,
                )
                db.add(match_record)

                ticket.dq_flag = True
                ticket.dq_reason = rule.name
                flagged_count += 1
                break

    run.tickets_evaluated = evaluated_count
    run.tickets_flagged = flagged_count
    run.status = "completed"
    run.finished_at = utcnow()

    await db.commit()
    await db.refresh(run)
    return run


async def revert_dq_run(db: AsyncSession, run_id: int) -> DQRun:
    """Revert a DQ run by restoring ticket flags prior to that run."""
    run = await db.get(DQRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"DQ run {run_id} not found")

    if run.status == "reverted":
        raise HTTPException(status_code=400, detail=f"DQ run {run_id} is already reverted")

    matches_query = select(DQRunTicket).where(DQRunTicket.run_id == run_id)
    matches_res = await db.scalars(matches_query)
    matches = list(matches_res.all())

    for match in matches:
        ticket = await db.get(ServiceNowTicket, match.ticket_id)
        if ticket:
            ticket.dq_flag = match.reverted_dq_flag
            ticket.dq_reason = match.reverted_dq_reason

    run.status = "reverted"
    run.reverted_at = utcnow()
    await db.commit()
    await db.refresh(run)
    return run
