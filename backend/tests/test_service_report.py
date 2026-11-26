"""Service performance: periods, KPIs, monthly trends, ageing, the demo history and admin-only access."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.auth import current_user
from app.main import app
from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket
from app.models.user import User
from app.services import demo_history
from app.services.service_report import service_performance, window
from tests.test_knowledge import session  # noqa: F401  (fixture)

NOW = datetime(2026, 11, 26, 12, 0)


@pytest.mark.parametrize(("period", "expected"), [
    ("mtd", (datetime(2026, 11, 1), NOW, datetime(2026, 10, 1), datetime(2026, 10, 26, 12))),
    ("last_month", (datetime(2026, 10, 1), datetime(2026, 11, 1), datetime(2026, 9, 1), datetime(2026, 10, 1))),
    ("qtd", (datetime(2026, 10, 1), NOW, datetime(2026, 7, 1), datetime(2026, 8, 26, 12))),
    ("ytd", (datetime(2026, 1, 1), NOW, datetime(2025, 1, 1), datetime(2025, 11, 26, 12))),
    ("12m", (datetime(2025, 12, 1), NOW, datetime(2024, 12, 1), datetime(2025, 12, 1))),
])
def test_each_period_is_compared_with_the_one_before(period, expected):
    assert window(period, NOW) == expected


def _ticket(i: str, priority: int, opened_h: float, took_h: float | None, app: str = "PayrollPro") -> Ticket:
    opened = NOW - timedelta(hours=opened_h)
    done = opened + timedelta(hours=took_h) if took_h is not None else None
    return Ticket(id=i, source="JIRA", application=app, summary=i, description="d", reported_priority=priority,
                  status="resolved" if done else "in_progress", pipeline_status=PipelineStatus.REVIEWED,
                  opened_at=opened, resolved_at=done)


def _fix_answers(session, ticket_id: str, *actions: str) -> None:  # noqa: F811
    run = AgentRun(ticket_id=ticket_id, agent="resolution", verdict="resolved", output={})
    session.add(run)
    session.flush()
    session.add_all(Review(ticket_id=ticket_id, agent_run_id=run.id, agent="resolution", action=a, reviewer="Ravi")
                    for a in actions)


def test_kpis_trends_and_ageing(session):  # noqa: F811
    session.add_all([
        _ticket("A", 1, 30, 2),          # P1 met (target 4 h)
        _ticket("B", 1, 40, 6),          # P1 breached
        _ticket("C", 3, 100, 30, "OrderHub"),  # P3: no target
        _ticket("D", 2, 20, None),       # open P2, past its 8 h target
        _ticket("E", 4, 2, None),        # open P4, under a day old
        _ticket("OLD", 3, 24 * 70, 10),  # resolved two months ago
    ])
    session.flush()
    _fix_answers(session, "A", "wrong", "worked")
    _fix_answers(session, "B", "worked")
    session.commit()

    r = service_performance(session, "mtd", now=NOW.replace(tzinfo=UTC))
    now = r["kpis"]["current"]
    assert (now["opened"], now["resolved"], now["resolved_by_priority"]) == (5, 3, {"P1": 2, "P2": 0, "P3": 1, "P4–P5": 0})
    assert (now["mttr_hours"], now["median_hours"]) == (12.7, 6.0)  # (2 + 6 + 30) / 3, and the middle value
    assert (now["sla_met"], now["first_fix"]) == (0.5, 0.5)  # only P1/P2 have targets; A needed a second fix
    assert (r["kpis"]["backlog"], r["kpis"]["backlog_past_sla"]) == (2, 1)
    assert r["kpis"]["previous"]["resolved"] == 0 and r["kpis"]["spark"]["resolved"][-1] == 3

    monthly = r["monthly"]
    assert len(monthly["months"]) == 12 and monthly["months"][-1] == "2026-11"
    assert monthly["resolved"][-1] == 3 and monthly["resolved"][-3] == 1  # OLD, in September
    assert monthly["mttr_by_priority"]["P1"][-1] == 4.0 and monthly["mttr_by_priority"]["P2"][-1] is None
    assert monthly["resolved_by_application"]["OrderHub"][-1] == 1

    assert r["by_application"][0] == {"application": "OrderHub", "resolved": 1, "mttr_hours": 30.0, "sla_met": None}
    ages = {row["age"]: row for row in r["ageing"]}
    assert (ages["< 1 day"]["P4–P5"], ages["< 1 day"]["P2"], ages["1–3 days"]["P2"]) == (1, 1, 0)  # D is 20 h old
    assert sum(row[g] for row in r["ageing"] for g in ("P1", "P2", "P3", "P4–P5", "Unprioritised")) == 2  # only D and E

    only_p1 = service_performance(session, "mtd", priority=1, now=NOW.replace(tzinfo=UTC))["kpis"]["current"]
    assert (only_p1["resolved"], only_p1["mttr_hours"]) == (2, 4.0)
    orderhub = service_performance(session, "12m", application="OrderHub", now=NOW.replace(tzinfo=UTC))
    assert orderhub["kpis"]["current"]["resolved"] == 1 and "PayrollPro" in orderhub["applications"]


def test_demo_history_is_closed_reversible_and_leaves_real_tickets_alone(session):  # noqa: F811
    session.add(_ticket("REAL-1", 3, 5, None))
    session.commit()
    made = demo_history.generate(session, months=3, now=NOW.replace(tzinfo=UTC))
    demo = session.scalars(select(Ticket).where(Ticket.source == "Demo")).all()
    assert made == len(demo) > 200
    assert all(t.status == "closed" and t.pipeline_status == "historical" and t.resolved_at <= NOW for t in demo)
    answers = [(r.ticket_id, r.created_at) for r in session.scalars(select(Review).where(Review.agent == "resolution"))]
    assert len(answers) == len(set(answers))  # a failed fix and the one that worked never share a time
    assert demo_history.generate(session, months=3, now=NOW.replace(tzinfo=UTC)) == made  # replaced, not doubled
    assert demo_history.remove(session) == made
    assert [t.id for t in session.scalars(select(Ticket))] == ["REAL-1"]
    assert session.scalars(select(AgentRun)).all() == [] and session.scalars(select(Review)).all() == []


async def test_service_endpoint_is_for_admins_only(client):
    r = await client.get("/api/v1/dashboard/service", params={"period": "qtd"})
    assert r.status_code == 200 and r.json()["period"] == "qtd" and len(r.json()["monthly"]["months"]) == 12
    assert (await client.get("/api/v1/dashboard/service", params={"period": "week"})).status_code == 422
    for role in ("lead", "engineer"):
        app.dependency_overrides[current_user] = lambda role=role: User(id=2, email=f"{role}@test", name=role, role=role)
        for path in ("/api/v1/dashboard/service", "/api/v1/dashboard/reports"):
            assert (await client.get(path)).status_code == 403
