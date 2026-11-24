"""Admin reports for one period: tickets by application, agent performance, fix and closure outcomes, and engineers.

Everything is read from stored data. A ticket counts in a period by the day it was opened; a resolution by the day it
was resolved; agent runs, ratings and reviews by the day they were recorded. The SLA uses the priority in force and the
targets of the SLA module, so the numbers match the SLA clocks in the console.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.knowledge import ResolvedCase
from app.models.ticket import AgentRun, Feedback, Review, Ticket
from app.services.data_quality import last_run
from app.services.fix import MAX_WRONG
from app.services.triage import sla
from app.services.triage.run import AUTO_REVIEWER

AGENTS = ("data_quality", "triage", "resolution", "closure_quality", "knowledge_builder")
NO_APP, UNASSIGNED = "No application", "Unassigned"
DONE = ("resolved", "closed")


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _hours(values: list[float]) -> float | None:
    return round(mean(values), 1) if values else None


def _done_at(t: Ticket) -> datetime | None:
    return t.resolved_at or t.closed_at


def _naive(at: datetime) -> datetime:
    """Run times carry a zone (SQLite drops it); ticket times are naive UTC."""
    return at.astimezone(UTC).replace(tzinfo=None) if at.tzinfo else at


def reports(db: Session, days: int, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)  # ticket times are naive UTC
    since = now - timedelta(days=days)
    tickets = db.scalars(select(Ticket).options(selectinload(Ticket.agent_runs))).all()
    opened = [t for t in tickets if t.opened_at and t.opened_at >= since]
    closed = [t for t in tickets if (d := _done_at(t)) and d >= since and t.opened_at]
    working = sla.working_priorities(db, tickets)
    targets = sla.config().targets
    reviews = db.scalars(select(Review).where(Review.created_at >= since.replace(tzinfo=UTC)).order_by(Review.id)).all()

    def sla_result(t: Ticket) -> bool | None:
        """True when met, False when breached, None when there is no target or the clock still runs."""
        hours = targets.get(working[t.id][0]) if t.id in working else None
        if hours is None:
            return None
        due, done = t.opened_at + timedelta(hours=hours), _done_at(t)
        if done is None and due > now:
            return None
        return done is not None and done <= due

    return {
        "days": days,
        "since": since.replace(tzinfo=UTC),
        "applications": _applications(db, tickets, opened, closed, working, sla_result, since),
        "agents": _agents(db, since),
        "outcomes": _outcomes(tickets, reviews, since),
        "engineers": _engineers(tickets, opened, closed, reviews, sla_result),
    }


def _applications(db, tickets, opened, closed, working, sla_result, since) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: {"opened": 0, "open": 0, "resolved": 0, "p1_p2": 0,
                                                            "sla": [], "ttr": [], "fix": [], "kb": []})
    for t in tickets:
        if t.status not in DONE:
            rows[t.application or NO_APP]["open"] += 1
    for t in opened:
        row = rows[t.application or NO_APP]
        row["opened"] += 1
        row["p1_p2"] += t.id in working and working[t.id][0] <= 2
        if (met := sla_result(t)) is not None:
            row["sla"].append(met)
        if fix := last_run(t, "resolution"):
            row["fix"].append(fix.verdict == "resolved")
    for t in closed:
        row = rows[t.application or NO_APP]
        row["resolved"] += 1
        row["ttr"].append((_done_at(t) - t.opened_at).total_seconds() / 3600)
    for app, status in db.execute(select(ResolvedCase.application, ResolvedCase.match_status)
                                  .where(ResolvedCase.closed_at >= since)):
        rows[app or NO_APP]["kb"].append(status == "matched")
    return sorted(
        ({"application": app, "opened": r["opened"], "open": r["open"], "resolved": r["resolved"], "p1_p2": r["p1_p2"],
          "sla_met": _share(sum(r["sla"]), len(r["sla"])), "mean_hours_to_resolve": _hours(r["ttr"]),
          "runbook_fix": _share(sum(r["fix"]), len(r["fix"])), "kb_covered": _share(sum(r["kb"]), len(r["kb"]))}
         for app, r in rows.items()),
        key=lambda r: (-r["opened"], r["application"]),
    )


def _agents(db, since) -> list[dict[str, Any]]:
    runs = db.execute(select(AgentRun.agent, AgentRun.output).where(AgentRun.created_at >= since.replace(tzinfo=UTC))).all()
    rated: dict[tuple[int, str], Feedback] = {}  # a person's latest rating of a result counts
    for f in db.scalars(select(Feedback).where(Feedback.created_at >= since.replace(tzinfo=UTC)).order_by(Feedback.id)):
        rated[(f.agent_run_id, f.reviewer)] = f
    rows = []
    for agent in AGENTS:
        mine = [o or {} for a, o in runs if a == agent]
        audits = [a for o in mine for a in ([o["audit"]] if isinstance(o.get("audit"), dict) else o.get("audit") or [])]
        stars = [f.stars for f in rated.values() if f.agent == agent]
        rows.append({
            "agent": agent, "runs": len(mine),
            "model_used": _share(sum(bool(o.get("audit")) for o in mine), len(mine)),
            "model_failed": sum(o.get("ai") == "failed" for o in mine),
            "tokens": sum((a.get(k) or 0) for a in audits for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                                                     "cache_write_tokens")),
            "rated": len(stars),
            "correct": _share(sum(s >= 4 for s in stars), len(stars)),
            "partially_correct": _share(sum(s == 3 for s in stars), len(stars)),
            "incorrect": _share(sum(s <= 2 for s in stars), len(stars)),
        })
    return rows


def _outcomes(tickets, reviews, since) -> list[dict[str, Any]]:
    """Per application: how fixes landed (the engineer's answers on Resolution runs) and how closure notes fared."""
    app_of = {t.id: t.application or NO_APP for t in tickets}
    answers: dict[str, list[str]] = defaultdict(list)  # ticket -> its fix answers, oldest first
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: {"first": [], "attempts": [], "escalated": 0, "scores": [],
                                                            "needs_work": [], "approved": 0, "returned": 0})
    for r in reviews:
        if r.agent == "resolution":
            answers[r.ticket_id].append(r.action)
        elif r.agent == "lead_review" and r.action in ("approved", "sent_back"):
            rows[app_of.get(r.ticket_id, NO_APP)]["approved" if r.action == "approved" else "returned"] += 1
    for ticket_id, said in answers.items():
        row = rows[app_of.get(ticket_id, NO_APP)]
        if any(a in ("worked", "partly") for a in said):
            row["first"].append(said[0] in ("worked", "partly"))
            row["attempts"].append(next(i for i, a in enumerate(said, 1) if a in ("worked", "partly")))
        row["escalated"] += said.count("wrong") >= MAX_WRONG
    for t in tickets:
        check = last_run(t, "closure_quality")  # the latest check of each ticket's closure note, made in the period
        if check and _naive(check.created_at) >= since and check.verdict in ("good", "needs_work"):
            row = rows[app_of[t.id]]
            row["needs_work"].append(check.verdict == "needs_work")
            if isinstance(check.output.get("score"), int):
                row["scores"].append(check.output["score"])
    return sorted(
        ({"application": app, "fixes_confirmed": len(r["first"]), "first_fix": _share(sum(r["first"]), len(r["first"])),
          "mean_attempts": round(mean(r["attempts"]), 1) if r["attempts"] else None, "escalated": r["escalated"],
          "mean_closure_score": round(mean(r["scores"]), 1) if r["scores"] else None,
          "closure_needs_work": _share(sum(r["needs_work"]), len(r["needs_work"])),
          "lead_approved": r["approved"], "lead_returned": r["returned"]}
         for app, r in rows.items() if r["first"] or r["escalated"] or r["needs_work"] or r["approved"] or r["returned"]),
        key=lambda r: r["application"],
    )


def _engineers(tickets, opened, closed, reviews, sla_result) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: {"open": 0, "closed": 0, "ttr": [], "breached": 0, "changed": 0})
    for t in tickets:
        if t.status not in DONE:
            rows[t.assignee or UNASSIGNED]["open"] += 1
    for t in closed:
        row = rows[t.assignee or UNASSIGNED]
        row["closed"] += 1
        row["ttr"].append((_done_at(t) - t.opened_at).total_seconds() / 3600)
    for t in opened:
        rows[t.assignee or UNASSIGNED]["breached"] += sla_result(t) is False
    for r in reviews:  # priorities a person changed in review; the agents' own approvals are not a person's work
        if r.agent == "triage" and r.action == "edited" and r.reviewer != AUTO_REVIEWER:
            rows[r.reviewer]["changed"] += 1
    return sorted(
        ({"engineer": name, "open": r["open"], "closed": r["closed"], "mean_hours_to_resolve": _hours(r["ttr"]),
          "sla_breached": r["breached"], "priority_changes": r["changed"]} for name, r in rows.items()),
        key=lambda r: (r["engineer"] == UNASSIGNED, -r["open"] - r["closed"], r["engineer"]),
    )
