"""Storm grouping, P1/P2 SLA risk and the first message. Tickets are built by hand so every number is known."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core import registry
from app.core.config import bump_config_version, settings
from app.db.session import Base
from app.models.ticket import AgentRun, PipelineStatus, Ticket
from app.services.triage.review import review
from app.services.triage.run import _input_hash, run_triage
from app.services.triage.sla import open_p1_p2, sla_status
from app.services.triage.storms import declare, detect_storms
from tests.test_triage import db  # noqa: F401  (fixture: every open sample ticket as if Data Quality had passed it)

T0 = datetime(2026, 10, 28, 9, 0)
PEOPLE = ["Asha", "Bram", "Chen", "Dev", "Esha"]
CHECKOUT = ("Checkout fails", "Customers cannot complete checkout on the website.")
DUPLICATE = ("Duplicate orders created", "A customer was charged twice and got duplicate orders.")


def ticket(i: int, who: str, app: str | None, text: tuple[str, str], minute: int = 0) -> Ticket:
    return Ticket(
        id=f"T-{i}", source="JIRA", reporter_name=who, reporter_email=f"{who.lower()}@contoso.com", application=app,
        summary=text[0], description=text[1], status="new", pipeline_status=PipelineStatus.DQ_PASSED, reported_priority=3,
        opened_at=T0 + timedelta(minutes=minute),
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def storm_of(session, tickets, at=T0 + timedelta(minutes=30)):
    session.add_all(tickets)
    session.commit()
    return detect_storms(session, at)


def test_enough_people_reporting_the_same_issue_is_a_storm(session):
    result = storm_of(session, [ticket(i, who, "OrderHub", CHECKOUT, minute=i * 4) for i, who in enumerate(PEOPLE)])
    (storm,) = result.storms
    assert (storm.people, storm.ticket_count, storm.issue_key, storm.main_ticket_id) == (5, 5, "rule:checkout_failing", "T-0")
    assert (result.created, result.linked, storm.status) == (1, 4, "open")
    assert {t.storm_id for t in session.scalars(select(Ticket))} == {storm.id}

    again = detect_storms(session, T0 + timedelta(hours=2))  # quiet for longer than quiet_min
    assert (again.created, again.updated, again.storms[0].id, again.storms[0].status) == (0, 1, storm.id, "closed")


def test_too_few_people_or_one_person_is_not_a_storm(session):
    assert not storm_of(session, [ticket(i, who, "OrderHub", CHECKOUT, minute=i) for i, who in enumerate(PEOPLE[:4])]).storms
    one_person = [ticket(10 + i, "Asha", "OrderHub", CHECKOUT, minute=i) for i in range(6)]
    assert not storm_of(session, one_person).storms  # the same person six times


def test_tickets_far_apart_in_time_do_not_group(session):
    assert not storm_of(session, [ticket(i, who, "OrderHub", CHECKOUT, minute=i * 40) for i, who in enumerate(PEOPLE)]).storms


def test_the_failed_job_is_the_main_ticket(session):
    job = ("PAY_CALC_MONTHLY failed", "Control-M job PAY_CALC_MONTHLY ended Not OK at 05:42. We cannot lock the payroll period.")
    lock = ("Cannot lock payroll", "We cannot lock the payroll period, the run did not finish.")
    tickets = [ticket(i, who, "PayrollPro", job if i == 3 else lock, minute=i) for i, who in enumerate(PEOPLE)]
    (storm,) = storm_of(session, tickets).storms
    assert storm.main_ticket_id == "T-3"  # not the first ticket


def test_login_problems_group_across_applications(session):
    apps = ["PayrollPro", "OrderHub", "StockSense", "InsightBI", "BillingEngine"]
    tickets = [ticket(i, who, app, ("I cant login", "I cant login to the application since morning."), minute=i)
               for i, (who, app) in enumerate(zip(PEOPLE, apps, strict=True))]
    (storm,) = storm_of(session, tickets).storms
    assert (storm.application, storm.issue_key, storm.people) == (None, "cross:login", 5)


def test_very_similar_text_groups_when_no_known_issue_matches(session):
    text = ("Gift wrap option missing", "The gift wrap option is missing on the cart page, please look at it.")
    (storm,) = storm_of(session, [ticket(i, who, "OrderHub", text, minute=i) for i, who in enumerate(PEOPLE)]).storms
    assert storm.issue_key == "similar text"


def test_a_person_can_declare_a_major_incident(session):
    (storm,) = storm_of(session, [ticket(i, who, "OrderHub", CHECKOUT, minute=i) for i, who in enumerate(PEOPLE)]).storms
    declare(session, storm, " ravi@contoso.com ")
    assert (storm.status, storm.declared_by) == ("declared", "ravi@contoso.com")
    assert detect_storms(session, T0 + timedelta(hours=3)).storms[0].status == "declared"  # a re-run keeps it declared


def test_a_storm_makes_the_main_ticket_p1_and_the_others_follow_it(session):
    session.add_all([ticket(i, who, "OrderHub", DUPLICATE, minute=i) for i, who in enumerate(PEOPLE)])
    session.commit()
    result = run_triage(session)
    assert result.evaluated == 5 and result.by_verdict["P1"] == 5  # a duplicate order alone is P3

    runs = {r.ticket_id: r.output for r in session.scalars(select(AgentRun))}
    assert (runs["T-0"]["stage"], runs["T-0"]["must_follow"], runs["T-0"]["priority"]) == ("rules", "storm", 1)
    assert [(runs[f"T-{i}"]["stage"], runs[f"T-{i}"]["linked_to"], runs[f"T-{i}"]["ai"]) for i in range(1, 5)] == [
        ("storm", "T-0", "not_needed")] * 4
    assert {t.pipeline_status for t in session.scalars(select(Ticket))} == {PipelineStatus.TRIAGED}


def test_joining_a_storm_triages_a_ticket_again():
    quiet, in_storm = ticket(1, "Asha", "OrderHub", DUPLICATE), ticket(1, "Asha", "OrderHub", DUPLICATE)
    in_storm.storm_id = 7
    assert _input_hash(quiet, "x") != _input_hash(in_storm, "x")


def test_sla_status_moves_from_ok_to_breached():
    def at(hours: float):
        return sla_status(2, T0, T0 + timedelta(hours=hours))

    states = [at(hours).state for hours in (3, 4, 6.4, 8, 9)]
    assert states == ["ok", "watch", "breach_likely", "breached", "breached"]
    assert (at(6).used, at(9).minutes_left, at(2).due_at) == (0.75, -60, T0 + timedelta(hours=8))
    assert sla_status(3, T0, T0) is None  # no target for P3


def test_open_p1_p2_with_sla_risk_and_first_message(db):  # noqa: F811
    run_triage(db)
    items = {i.ticket.id: i for i in open_p1_p2(db, datetime(2026, 10, 25, 21, 0))}
    salary = items["AMS-1215"]  # the salary file the bank has not received: P1, opened 18:32
    assert (salary.priority, salary.priority_from, salary.sla.state) == (1, "recommended", "watch")
    assert salary.message.text.startswith("PayrollPro: Salary transfer file not delivered to the bank")
    assert "Ref AMS-1215. Next update 21:30 UTC." in salary.message.text
    assert salary.ticket.reporter_name not in salary.message.text  # never a name
    assert all(i.priority <= 2 for i in items.values())
    ordered = [i.sla.state for i in open_p1_p2(db, datetime(2026, 10, 25, 21, 0))]
    assert ordered == sorted(ordered, key=["breached", "breach_likely", "watch", "ok"].index)  # most at risk first


def test_an_engineers_decision_replaces_the_recommendation(db):  # noqa: F811
    run_triage(db)
    review(db, db.get(Ticket, "AMS-1215"), "edited", "ravi@contoso.com", priority=3, reason_code="wrong_facts")
    review(db, db.get(Ticket, "AMS-1208"), "accepted", "ravi@contoso.com")
    items = {i.ticket.id: i for i in open_p1_p2(db, datetime(2026, 10, 25, 21, 0))}
    assert "AMS-1215" not in items  # lowered to P3: no longer tracked
    assert items["AMS-1208"].priority_from == "reviewed"


async def test_storm_and_sla_endpoints(client):
    await client.post("/api/v1/ingest")
    assert (await client.get("/api/v1/storms")).json() == []
    assert (await client.post("/api/v1/storms/run", params={"at": "2026-10-28T09:30:00"})).json()["storms"] == []
    assert (await client.post("/api/v1/storms/9/declare", json={"declared_by": "ravi@contoso.com"})).status_code == 404
    assert (await client.get("/api/v1/triage/sla")).json() == []  # nothing triaged yet
    assert (await client.get("/api/v1/triage/tickets/NOPE/first-message")).status_code == 404
    assert (await client.get("/api/v1/triage/tickets/AMS-1215/first-message")).status_code == 409  # not triaged yet


async def test_sla_and_storm_documents_are_checked_through_the_admin_api(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "test-key")
    key = {"X-Admin-Key": "test-key", "X-Admin-User": "alan"}
    try:
        sla_doc = (await client.get("/api/v1/admin/documents/sla", headers=key)).json()["document"]
        sla_doc["priorities"]["1"]["target_hours"] = 2
        assert (await client.put("/api/v1/admin/documents/sla", headers=key, json={"document": sla_doc})).status_code == 200
        sla_doc["watch_at"] = 0.9  # not below breach_likely_at
        assert (await client.put("/api/v1/admin/documents/sla", headers=key, json={"document": sla_doc})).status_code == 422
        sla_doc["watch_at"], sla_doc["first_message"] = 0.5, "{application} {nope}"
        assert (await client.put("/api/v1/admin/documents/sla", headers=key, json={"document": sla_doc})).status_code == 422

        storms = (await client.get("/api/v1/admin/documents/storms", headers=key)).json()["document"]
        storms["default"]["people_needed"] = 0
        assert (await client.put("/api/v1/admin/documents/storms", headers=key, json={"document": storms})).status_code == 422
    finally:
        registry.overrides.clear()
        bump_config_version()
