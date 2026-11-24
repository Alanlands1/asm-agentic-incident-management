"""Feedback from use: what people already do on a ticket is stored as a rating of the agent's result."""

from datetime import timedelta

from sqlalchemy import select

from app.models.ticket import AgentRun, Comment, Feedback, PipelineStatus, Ticket
from app.services import fix
from app.services.data_quality import check_ticket
from app.services.triage.review import review
from tests.test_triage import db  # noqa: F401  (fixture: every open ticket as if Data Quality had passed it)


def _ratings(db, agent):  # noqa: F811
    return [(f.stars, f.reason, f.reviewer) for f in db.scalars(select(Feedback).where(Feedback.agent == agent))]


def test_agreeing_or_changing_the_priority_rates_triage(db):  # noqa: F811
    db.add(AgentRun(ticket_id="AMS-1209", agent="triage", verdict="P3", output={"priority": 3}))
    db.flush()
    review(db, db.get(Ticket, "AMS-1209"), "edited", "ravi@contoso.com", priority=1, reason_code="wrong_facts")
    assert _ratings(db, "triage") == [(1, "From use: changed P3 to P1", "ravi@contoso.com")]


def test_the_agents_approving_their_own_priority_is_no_feedback(db):  # noqa: F811
    db.add(AgentRun(ticket_id="AMS-1209", agent="triage", verdict="P3", output={"priority": 3}))
    db.flush()
    review(db, db.get(Ticket, "AMS-1209"), "accepted", "AMS agents (auto)")
    assert _ratings(db, "triage") == []


def test_saying_the_fix_worked_rates_resolution(db):  # noqa: F811
    ticket = db.get(Ticket, "AMS-1209")
    ticket.pipeline_status = PipelineStatus.REVIEWED
    run = AgentRun(ticket_id="AMS-1209", agent="resolution", verdict="resolved",
                   output={"root_cause": "x", "steps": ["Do it."], "references": ["KB-PAY-004"]})
    db.add(run)
    db.flush()
    fix.record(db, ticket, run.id, "partly", "ravi@contoso.com", "Changed step 1")
    assert _ratings(db, "resolution") == [(3, "From use: the fix worked with changes", "ravi@contoso.com")]


def test_a_reporter_supplying_what_was_asked_rates_data_quality_right(db, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from app.llm import CallAudit
    from app.services import data_quality

    complete = SimpleNamespace(complete=True, model_dump=lambda: {"complete": True})
    audit = CallAudit(provider="anthropic", model="m", prompt_version="v", attempts=1, input_tokens=1, output_tokens=1,
                      latency_ms=1)
    monkeypatch.setattr(data_quality.settings, "LLM_ENABLED", True)
    monkeypatch.setattr(data_quality, "check_completeness", lambda *a: (complete, audit))  # the model says complete
    ticket = db.get(Ticket, "AMS-1209")
    asked = AgentRun(ticket_id="AMS-1209", agent="data_quality", verdict="needs_info", output={})
    db.add(asked)
    db.flush()
    ticket.application, ticket.description = "PayrollPro", "Payslips do not open."
    db.add(Comment(ticket_id="AMS-1209", author_email="reporter@contoso.com", from_reporter=True,
                   body="Since 09:00 today every payslip PDF in PayrollPro opens blank for all 40 staff in Pune, with error "
                        "PDF-GEN-500 when I open it from the portal. Steps: Payslips > November > Download.",
                   created_at=asked.created_at + timedelta(minutes=5)))  # the reply comes after the ask; on Windows two
    # rows written back to back can share a timestamp (the clock ticks every 15.6 ms)
    db.flush()
    db.refresh(ticket)
    assert check_ticket(db, ticket).verdict == "passed"
    assert _ratings(db, "data_quality") == [(5, "From use: the reporter supplied what was missing", "Reporter reply")]
