"""Demo history for the service-performance dashboard: about a year of resolved tickets, so the monthly trends have
something to show before real history builds up.

Every ticket is source "Demo" with an id DEMO-nnnnn, already resolved and closed (historical), so none reaches a queue,
a worklist or the agents. Each carries the agents' results the reports read: a triage priority, a Resolution fix with
the engineer's answer, and a Closure Quality score. remove() deletes them all; nothing else is touched.
Deterministic: the same seed and `now` give the same tickets.
"""

import math
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket

SOURCE = "Demo"
APPS = {"PayrollPro": 0.18, "OrderHub": 0.17, "BillingEngine": 0.15, "SalesConnect CRM": 0.14, "EmployeePortal": 0.14,
        "StockSense": 0.12, "InsightBI": 0.10}
PRIORITIES = {1: 0.04, 2: 0.14, 3: 0.47, 4: 0.28, 5: 0.07}
MEDIAN_HOURS = {1: 2.5, 2: 5.0, 3: 20.0, 4: 50.0, 5: 90.0}  # time to resolve; P1/P2 targets are 4 h and 8 h
ENGINEERS = ["Rohan Kulkarni", "Rahul Verma", "Ishita Bose", "Suresh Patil", "Karan Malhotra", "Sneha Iyer", "Ananya Das",
             "Aditya Rao"]
ISSUES = {
    "PayrollPro": ["Payslip PDF opens blank", "Monthly payroll batch failed", "Overtime not calculated"],
    "OrderHub": ["Checkout stuck at payment", "Promo code rejected", "Order export missing rows"],
    "BillingEngine": ["Invoice run stopped", "Credit note not applied", "GST rounding error"],
    "SalesConnect CRM": ["Lead import failed", "Opportunity stage not saving", "CRM sync delayed"],
    "EmployeePortal": ["SSO login loop", "MFA code not received", "Leave request not submitted"],
    "StockSense": ["Scanner not posting goods receipt", "Label printer offline", "Stock count mismatch"],
    "InsightBI": ["Dashboard not refreshing", "Report shows yesterday's data", "Export to Excel times out"],
}
AGENT_REVIEWER = "AMS agents (auto)"


def _pick(rng: random.Random, weights: dict):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _month_start(at: datetime, back: int) -> datetime:
    y, m = divmod(at.year * 12 + at.month - 1 - back, 12)
    return datetime(y, m + 1, 1)


def remove(db: Session) -> int:
    """Delete every demo ticket and what hangs off it (runs, reviews, ratings cascade)."""
    ids = db.scalars(select(Ticket.id).where(Ticket.source == SOURCE)).all()
    for model in (Review, AgentRun):
        db.execute(delete(model).where(model.ticket_id.in_(ids)))
    db.execute(delete(Ticket).where(Ticket.source == SOURCE))
    db.commit()
    return len(ids)


def generate(db: Session, months: int = 12, now: datetime | None = None, seed: int = 42) -> int:
    """Replace the demo history with `months` months of resolved tickets ending now. Returns how many were made."""
    remove(db)
    rng, now = random.Random(seed), (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    n = 0
    for back in range(months - 1, -1, -1):
        start, end = _month_start(now, back), min(_month_start(now, back - 1), now)
        progress = (months - 1 - back) / max(months - 1, 1)  # 0 for the oldest month, 1 for this one
        volume = round(110 + 40 * progress + 12 * math.sin(back) + rng.randint(-8, 8))  # demand grows over the year
        volume = round(volume * (end - start) / (_month_start(now, back - 1) - start))  # this month: only so far
        faster = 1 - 0.25 * progress  # the agents cut resolve times by about a quarter over the year
        for _ in range(volume):
            n += 1
            app, priority = _pick(rng, APPS), _pick(rng, PRIORITIES)
            opened = start + timedelta(seconds=rng.uniform(0, (end - start).total_seconds()))
            hours = MEDIAN_HOURS[priority] * faster * math.exp(rng.gauss(0, 0.55))
            resolved = opened + timedelta(hours=hours)
            if resolved > now:  # would still be open: closed just now instead, to keep demo tickets out of the queues
                resolved = now - timedelta(minutes=rng.randint(1, 60))
                opened = min(opened, resolved - timedelta(minutes=30))
            ticket_id, engineer = f"DEMO-{n:05d}", rng.choice(ENGINEERS)
            db.add(Ticket(id=ticket_id, source=SOURCE, application=app, summary=rng.choice(ISSUES[app]),
                          description="Demo history ticket.", status="closed", source_status="Done",
                          pipeline_status=PipelineStatus.HISTORICAL, reported_priority=priority,
                          assignee=engineer, opened_at=opened, resolved_at=resolved, closed_at=resolved,
                          raw={"demo": True}))
            triage = AgentRun(ticket_id=ticket_id, agent="triage", verdict=f"P{priority}", output={"priority": priority},
                              created_at=opened.replace(tzinfo=UTC))
            fix = AgentRun(ticket_id=ticket_id, agent="resolution", verdict="resolved", output={"references": []},
                           created_at=(opened + timedelta(minutes=5)).replace(tzinfo=UTC))
            good = rng.random() < 0.82
            check = AgentRun(ticket_id=ticket_id, agent="closure_quality", verdict="good" if good else "needs_work",
                             output={"score": rng.choice([4, 5, 5, 6, 6] if good else [2, 3])},
                             created_at=resolved.replace(tzinfo=UTC))
            db.add_all([triage, fix, check])
            db.flush()
            db.add(Review(ticket_id=ticket_id, agent_run_id=triage.id, agent="triage", action="accepted",
                          final_priority=priority, reviewer=AGENT_REVIEWER, created_at=opened.replace(tzinfo=UTC)))
            first_time = rng.random() < 0.62 + 0.18 * progress  # first-time fix rises as the runbooks improve
            if not first_time:  # the first fix failed partway through, then the next one worked
                db.add(Review(ticket_id=ticket_id, agent_run_id=fix.id, agent="resolution", action="wrong", note="Demo",
                              reviewer=engineer, created_at=(opened + (resolved - opened) / 2).replace(tzinfo=UTC)))
            db.add(Review(ticket_id=ticket_id, agent_run_id=fix.id, agent="resolution", action="worked", reviewer=engineer,
                          created_at=resolved.replace(tzinfo=UTC)))
        db.commit()
    return n
