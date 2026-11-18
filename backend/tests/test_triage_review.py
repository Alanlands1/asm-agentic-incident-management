"""Engineer review of Triage recommendations: queue order, decisions, the agreement report and the endpoints."""

import pytest
from sqlalchemy import select

from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket
from app.services.triage import run_triage
from app.services.triage.review import ReviewError, pending, report, review
from tests.test_triage import db  # noqa: F401  (fixture: every open ticket as if Data Quality had passed it)


@pytest.fixture
def triaged(db):  # noqa: F811
    run_triage(db)
    return db


def test_queue_puts_flagged_and_urgent_tickets_first(triaged):
    queue = pending(triaged)
    assert queue and all(t.pipeline_status == PipelineStatus.TRIAGED for t, _ in queue)
    flagged = [run.output["needs_review"] for _, run in queue]
    assert flagged == sorted(flagged, reverse=True)  # every flagged ticket before every other one
    calm = [run.output["priority"] for _, run in queue if not run.output["needs_review"]]
    assert calm == sorted(calm)
    assert len(pending(triaged, limit=3)) == 3


def test_accept_edit_and_reject(triaged):
    accepted = review(triaged, triaged.get(Ticket, "AMS-1209"), "accepted", "ravi@contoso.com")
    assert accepted.final_priority == 3  # the recommendation, not the reporter's P1
    assert triaged.get(Ticket, "AMS-1209").pipeline_status == PipelineStatus.REVIEWED

    edited = review(triaged, triaged.get(Ticket, "AMS-1214"), "edited", "ravi@contoso.com", priority=2, reason_code="wrong_facts")
    assert (edited.final_priority, edited.reason_code) == (2, "wrong_facts")

    rejected = review(triaged, triaged.get(Ticket, "AMS-1213"), "rejected", "ravi@contoso.com", reason_code="wrong_rule")
    assert rejected.final_priority == 3  # no priority given: the reporter's stands

    run = triaged.scalars(select(AgentRun).where(AgentRun.id == accepted.agent_run_id)).one()
    assert run.output["priority"] == 3 and run.verdict == "P3"  # the recommendation itself is never changed


def test_decisions_that_do_not_fit_are_refused(triaged):
    ticket = triaged.get(Ticket, "AMS-1209")
    with pytest.raises(ReviewError):
        review(triaged, ticket, "edited", "ravi@contoso.com", priority=3)  # same as the recommendation
    with pytest.raises(ReviewError):
        review(triaged, ticket, "rejected", "ravi@contoso.com")  # no reason
    assert ticket.pipeline_status == PipelineStatus.TRIAGED and not triaged.scalars(select(Review)).all()


def test_report_shows_agreement_by_rule_and_stage(triaged):
    review(triaged, triaged.get(Ticket, "AMS-1209"), "accepted", "ravi@contoso.com")
    review(triaged, triaged.get(Ticket, "AMS-1214"), "edited", "ravi@contoso.com", priority=2, reason_code="wrong_facts")
    review(triaged, triaged.get(Ticket, "AMS-1210"), "edited", "ravi@contoso.com", priority=3, reason_code="wrong_rule")

    r = report(triaged)
    assert (r.reviewed, r.agreement, r.raised_by_engineer, r.lowered_by_engineer) == (3, 0.333, 1, 1)
    assert r.by_rule["account_locked"] == {"accepted": 1} and r.by_rule["confirmation_email_missing"] == {"edited": 1}
    assert r.by_stage["rules"]["edited"] == 2 and r.by_reason == {"wrong_facts": 1, "wrong_rule": 1}


async def test_review_endpoints(client):
    await client.post("/api/v1/ingest")
    assert (await client.get("/api/v1/triage/review-queue")).json() == []  # nothing triaged yet
    body = {"action": "accepted", "reviewer": "ravi@contoso.com"}
    assert (await client.post("/api/v1/triage/tickets/NOPE/review", json=body)).status_code == 404
    assert (await client.post("/api/v1/triage/tickets/AMS-1209/review", json=body)).status_code == 409  # pending
    assert (await client.post("/api/v1/triage/tickets/AMS-1209/review", json={**body, "priority": 7})).status_code == 422
    assert (await client.get("/api/v1/triage/review-report")).json()["reviewed"] == 0
