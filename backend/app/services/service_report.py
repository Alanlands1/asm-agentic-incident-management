"""Service performance: the incident-management KPIs and monthly trends an AMS command centre reports.

Definitions (one place, so the tiles, charts and CSVs agree):
  opened      tickets opened in the period
  resolved    tickets resolved (or closed) in the period, by the priority in force
  backlog     tickets open now; past SLA when their P1/P2 target has run out
  MTTR        mean hours from opened to resolved, for tickets resolved in the period (the median is given beside it)
  SLA met     share of P1/P2 tickets resolved in the period within their target (only P1 and P2 have targets)
  first fix   share of confirmed fixes that worked on the first suggestion, for tickets resolved in the period
The priority in force is the decided one (Triage and its review), else the requester's.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.ticket import Review, Ticket
from app.services.reports import DONE, NO_APP, _done_at, _share
from app.services.triage import sla

Period = Literal["mtd", "last_month", "qtd", "ytd", "12m"]
GROUPS = ("P1", "P2", "P3", "P4–P5")
AGES = (("< 1 day", 1), ("1–3 days", 3), ("3–7 days", 7), ("7–30 days", 30), ("> 30 days", None))
TREND_MONTHS, SPARK_MONTHS = 12, 6


def _month(at: datetime, back: int = 0) -> datetime:
    """The first day of the month `back` months before `at`'s month."""
    y, m = divmod(at.year * 12 + at.month - 1 - back, 12)
    return datetime(y, m + 1, 1)


def window(period: Period, now: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    """(start, end) of the period and of the one before it, of the same length where the calendar allows."""
    if period == "last_month":
        return _month(now, 1), _month(now), _month(now, 2), _month(now, 1)
    if period == "12m":
        return _month(now, 11), now, _month(now, 23), _month(now, 11)
    if period == "mtd":
        start, prev = _month(now), _month(now, 1)
    elif period == "qtd":
        start = datetime(now.year, (now.month - 1) // 3 * 3 + 1, 1)
        prev = _month(start, 3)
    else:  # ytd
        start, prev = datetime(now.year, 1, 1), datetime(now.year - 1, 1, 1)
    return start, now, prev, min(prev + (now - start), start)


def _group(priority: int | None) -> str | None:
    return None if priority is None else GROUPS[min(priority, 4) - 1]


def service_performance(db: Session, period: Period = "mtd", application: str | None = None, priority: int | None = None,
                        now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)  # ticket times are naive UTC
    tickets = db.scalars(select(Ticket).options(selectinload(Ticket.agent_runs))).all()
    working = sla.working_priorities(db, tickets)
    prio = {t.id: working[t.id][0] if t.id in working else t.reported_priority for t in tickets}
    apps = sorted({t.application or NO_APP for t in tickets})
    tickets = [t for t in tickets if (application is None or (t.application or NO_APP) == application)
               and (priority is None or prio[t.id] == priority)]
    targets = sla.config().targets
    answers: dict[str, list[str]] = defaultdict(list)  # ticket -> the engineer's answers on its fixes, oldest first
    for ticket_id, action in db.execute(select(Review.ticket_id, Review.action).where(Review.agent == "resolution")
                                        .order_by(Review.id)):
        answers[ticket_id].append(action)

    def hours(t: Ticket) -> float:
        return (_done_at(t) - t.opened_at).total_seconds() / 3600

    def met(t: Ticket) -> bool | None:
        target = targets.get(prio[t.id])
        return None if target is None else hours(t) <= target

    def first_fix(t: Ticket) -> bool | None:
        said = [a for a in answers.get(t.id, []) if a in ("worked", "partly", "wrong")]
        return said[0] != "wrong" if any(a in ("worked", "partly") for a in said) else None

    def resolved_in(start: datetime, end: datetime) -> list[Ticket]:
        return [t for t in tickets if t.opened_at and (d := _done_at(t)) and start <= d < end]

    def measures(start: datetime, end: datetime) -> dict[str, Any]:
        done = resolved_in(start, end)
        took = [hours(t) for t in done]
        sla_ = [m for t in done if (m := met(t)) is not None]
        fixes = [f for t in done if (f := first_fix(t)) is not None]
        return {
            "opened": sum(1 for t in tickets if t.opened_at and start <= t.opened_at < end),
            "resolved": len(done),
            "resolved_by_priority": {g: sum(1 for t in done if _group(prio[t.id]) == g) for g in GROUPS},
            "mttr_hours": round(sum(took) / len(took), 1) if took else None,
            "median_hours": round(median(took), 1) if took else None,
            "sla_met": _share(sum(sla_), len(sla_)),
            "first_fix": _share(sum(fixes), len(fixes)),
        }

    start, end, prev_start, prev_end = window(period, now)
    months = [_month(now, back) for back in range(TREND_MONTHS - 1, -1, -1)]
    bounds = [(m, months[i + 1] if i + 1 < len(months) else now) for i, m in enumerate(months)]
    monthly = [measures(a, b) for a, b in bounds]
    spark = monthly[-SPARK_MONTHS:]

    open_now = [t for t in tickets if t.status not in DONE]
    past_sla = sum(1 for t in open_now
                   if t.opened_at and (h := targets.get(prio[t.id])) and t.opened_at + timedelta(hours=h) < now)

    def age(t: Ticket) -> str:
        days = (now - t.opened_at).total_seconds() / 86400 if t.opened_at else 0
        return next(label for label, limit in AGES if limit is None or days < limit)

    ageing = Counter((age(t), _group(prio[t.id]) or "Unprioritised") for t in open_now)
    period_done = resolved_in(start, end)
    by_app: dict[str, list[Ticket]] = defaultdict(list)
    for t in period_done:
        by_app[t.application or NO_APP].append(t)

    return {
        "period": period, "start": start.replace(tzinfo=UTC), "end": end.replace(tzinfo=UTC),
        "applications": apps,
        "sla_targets": {f"P{p}": h for p, h in sorted(targets.items())},
        "kpis": {
            "current": measures(start, end), "previous": measures(prev_start, prev_end),
            "backlog": len(open_now), "backlog_past_sla": past_sla,
            "spark": {k: [m[k] for m in spark] for k in ("opened", "resolved", "mttr_hours", "sla_met", "first_fix")},
        },
        "monthly": {
            "months": [m.strftime("%Y-%m") for m in months],
            "opened": [m["opened"] for m in monthly],
            "resolved": [m["resolved"] for m in monthly],
            "resolved_by_priority": {g: [m["resolved_by_priority"][g] for m in monthly] for g in GROUPS},
            "mttr_by_priority": {g: [_mean([hours(t) for t in resolved_in(a, b) if _group(prio[t.id]) == g]) for a, b in bounds]
                                 for g in GROUPS},
            "sla_met": [m["sla_met"] for m in monthly],
            "resolved_by_application": {app: [sum(1 for t in resolved_in(a, b) if (t.application or NO_APP) == app)
                                              for a, b in bounds] for app in sorted({t.application or NO_APP for t in tickets})},
        },
        "by_application": sorted(
            ({"application": app, "resolved": len(done), "mttr_hours": _mean([hours(t) for t in done]),
              "sla_met": _share(sum(m for t in done if (m := met(t)) is not None), sum(1 for t in done if met(t) is not None))}
             for app, done in by_app.items()),
            key=lambda r: -(r["mttr_hours"] or 0),
        ),
        "ageing": [{"age": label, **{g: ageing[(label, g)] for g in (*GROUPS, "Unprioritised")}} for label, _ in AGES],
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None
