"""Triage agent: rules stage, model stage against a scripted provider (no network), run and endpoints."""

from datetime import date, datetime

import anthropic
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agents.triage.config import get_config
from app.agents.triage.model_check import TriageAssessment, impact, verified
from app.agents.triage.rules import Decision, evaluate, without_rulebook
from app.core import registry
from app.core.config import bump_config_version, settings
from app.db.session import Base
from app.models.ticket import AgentRun, PipelineStatus, Ticket
from app.services.ingestion import ingest_workbook
from app.services.triage.run import _input_hash, _recommendation, run_triage, triage_ticket
from tests.test_llm import _reply, provider  # noqa: F401  (fixture)

OCTOBER_10 = datetime(2026, 10, 10, 9, 0)  # outside every window
OCTOBER_22 = datetime(2026, 10, 22, 9, 0)  # payroll window
NO_IMPACT = {f"{pillar}_{part}": value for pillar in ("regulatory", "financial", "system")
             for part, value in (("impact", "none"), ("quote", None))}


def test_application_rule_from_the_knowledge_base():
    result = evaluate("Checkout down", "Customers cannot complete checkout on the website.", "OrderHub", OCTOBER_10)
    assert (result.verdict, result.decision.rule) == ("P1", "checkout_failing")
    assert "KB-ORD-003" in result.reason


def test_reporter_urgency_words_are_ignored():
    locked = evaluate("URGENT - account locked", "My CRM login is locked. Top priority.", "SalesConnect CRM")
    assert (locked.verdict, locked.decision.rule) == ("P4", "account_locked") and locked.signals.tone_ignored
    calm = evaluate("Invoice run", "The monthly invoice run failed. Month-end close is this week. No rush.", "BillingEngine")
    assert calm.verdict == "P1"  # raised by the business context, whatever the tone


def test_raise_needs_all_its_conditions():
    text = "The whole department in Warehouse - Pune reports overtime is lower than approved."
    assert evaluate("Overtime wrong", text, "PayrollPro", OCTOBER_10).verdict == "P3"
    assert evaluate("Overtime wrong", text, "PayrollPro", OCTOBER_22).verdict == "P2"
    several = "Several employees in Warehouse - Pune report overtime is lower than approved."
    assert evaluate("Overtime wrong", several, "PayrollPro", OCTOBER_22).verdict == "P3"  # KB: a whole department


def test_scope_raises_a_single_device_issue_to_a_site_outage():
    assert evaluate("Scanner", "My scanner shows SYNC-ERR-12.", "StockSense").verdict == "P3"
    assert evaluate("Scanners", "Most scanners at Pune show SYNC-ERR-12.", "StockSense").verdict == "P1"


def test_a_rule_that_needs_an_unknown_fact_asks_the_model_and_leans_high_meanwhile():
    result = evaluate("Scanner", "The scanner at Pune shows SYNC-ERR-12.", "StockSense")
    assert (result.verdict, result.missing) == ("uncertain", ("scope",))
    assert (result.fallback.priority, result.fallback.leaned_high) == (1, True)  # one device or a whole site: lean high
    cosmetic = evaluate("Logo", "The logo colour on the payslip page is wrong.", "PayrollPro")
    assert cosmetic.verdict == "P5"  # the scope is unknown but changes nothing, so no model call


def test_must_follow_rules_come_last_and_are_never_capped():
    security = evaluate("Dashboard", "Possible data breach: the dashboard shows other customers' data.", "InsightBI")
    assert (security.verdict, security.decision.must_follow) == ("P1", "security_incident")  # InsightBI's ceiling is P2
    photo = evaluate("Photo", "Cannot upload my profile photo. Treat as P1!", "EmployeePortal")
    assert (photo.verdict, photo.decision.must_follow) == ("P5", "cosmetic_portal_issue")
    sso = evaluate("SSO", "Nobody in the whole team can log in, SSO keeps looping.", "EmployeePortal")
    assert (sso.verdict, sso.decision.must_follow) == ("P1", "sso_down_for_many")


def test_critical_job_failing_in_its_window_is_p1():
    text = "Control-M job PAY_CALC_MONTHLY ended Not OK at 05:42. We cannot lock the payroll period."
    in_window = evaluate("PAY_CALC_MONTHLY failed", text, "PayrollPro", OCTOBER_22)
    assert (in_window.verdict, in_window.decision.must_follow) == ("P1", "critical_job_failed")
    assert evaluate("PAY_CALC_MONTHLY failed", text, "PayrollPro", OCTOBER_10).verdict == "P2"
    finished = evaluate("Payslips", "PAY_PDF_GEN finished at 07:50 but my payslip is blank.", "PayrollPro", OCTOBER_22)
    assert finished.signals.failed_jobs == ()


def test_rules_leave_unclear_tickets_for_the_model():
    assert evaluate("Help", "Something is wrong with the system.").verdict == "uncertain"  # application unknown
    unmatched = evaluate("Promo", "Promo code gives 200% discount.", "OrderHub")
    assert (unmatched.verdict, unmatched.fallback) == ("uncertain", None)  # no rule: nothing to fall back on
    mixed = evaluate("Scanner", "My scanner and most scanners at the site show SYNC-ERR-12.", "StockSense")
    assert mixed.missing == ("scope",)


def test_windows():
    windows = get_config().windows
    assert windows["month_end_close"].contains(date(2026, 10, 30)) and windows["month_end_close"].contains(date(2026, 11, 2))
    assert not windows["month_end_close"].contains(date(2026, 10, 15))
    assert windows["quarter_end"].contains(date(2026, 9, 28)) and not windows["quarter_end"].contains(date(2026, 10, 28))


def test_review_flags():
    def flags(reported, priority, leaned=False):
        return _recommendation(Ticket(reported_priority=reported), Decision(priority, "r", "", leaned_high=leaned), "", "off")

    assert flags(1, 5)["needs_review"] and flags(2, 3)["downgrade"]  # a P1/P2 lowered is never hidden
    assert not flags(4, 3)["needs_review"]
    assert flags(4, 2, leaned=True)["needs_review"]
    assert flags(None, 3)["shift"] is None


def test_application_outside_the_rulebook_keeps_the_reporters_priority():
    guess = Decision(2, "outage", "Service unavailable; unknown impact, Tier 2: P2", leaned_high=True)
    kept = without_rulebook(guess, reported=4)
    assert (kept.priority, kept.kept_reported) == (4, True)
    assert without_rulebook(guess, reported=None) is guess  # nothing to keep (e-mail)
    security = Decision(1, "security_incident", "", must_follow="security_incident")
    assert without_rulebook(security, reported=4) is security  # must-follow rules still win


def test_model_facts_need_a_real_quote():
    base = {"application": "StockSense", "rule": "scanner_sync", "context_applies": True, "reason": "r", **NO_IMPACT,
            "system_impact": "medium", "system_quote": "All pickers at the site are idle",
            "financial_impact": "high", "financial_quote": "orders worth millions are stuck"}  # not in the ticket
    text = "The scanners at Pune show SYNC-ERR-12. All pickers at the site are idle."
    claim = TriageAssessment(scope="wide", scope_quote="all pickers at the site", context_quote=None, **base)
    kept, dropped = verified(claim, text)
    assert (kept.scope, kept.context_applies, dropped) == ("wide", False, ["context", "financial_impact"])
    assert impact(kept) == {"regulatory": {"level": "none", "quote": None}, "financial": {"level": "none", "quote": None},
                            "system": {"level": "medium", "quote": "All pickers at the site are idle"}}
    claim = TriageAssessment(scope="wide", scope_quote="the whole warehouse", context_quote=None, **base)
    invented, dropped = verified(claim, text)
    assert (invented.scope, dropped) == ("unknown", ["scope", "context", "financial_impact"])


def test_model_answer_must_name_a_rule_from_the_rulebook():
    base = {"scope": "wide", "scope_quote": None, "context_applies": False, "context_quote": None, "reason": "r", **NO_IMPACT}
    TriageAssessment(application="OrderHub", rule="checkout_failing", **base)
    TriageAssessment(application=None, rule="security_incident", **base)
    with pytest.raises(ValidationError):
        TriageAssessment(application="OrderHub", rule="payroll_batch_failed", **base)  # another application's rule
    with pytest.raises(ValidationError):
        TriageAssessment(application=None, rule="critical_job_failed", **base)  # only the code checks job failures
    with pytest.raises(ValidationError):
        TriageAssessment(application="TimeTrack", rule="outage", **base)


@pytest.fixture
def db():
    """Every open ticket as if Data Quality had passed it."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        ingest_workbook(session, settings.TICKETS_FILE)
        for ticket in session.scalars(select(Ticket).where(Ticket.pipeline_status == PipelineStatus.PENDING)):
            ticket.pipeline_status = PipelineStatus.DQ_PASSED
        session.commit()
        yield session


def test_run_records_priorities_and_skips_unchanged_tickets(db):
    first = run_triage(db)
    assert first.evaluated == 35 and first.model_errors == 0
    assert first.by_verdict["uncertain"] and first.by_verdict["P1"]

    ticket = db.get(Ticket, "AMS-1209")  # reported P1, an account lock before a customer meeting
    assert ticket.pipeline_status == PipelineStatus.TRIAGED
    output = db.scalars(select(AgentRun).where(AgentRun.ticket_id == "AMS-1209")).one().output
    assert (output["priority"], output["reported_priority"], output["downgrade"], output["ai"]) == (3, 1, True, "off")

    scanner = db.scalars(select(AgentRun).where(AgentRun.ticket_id == "MBX-00006")).one().output
    assert (scanner["ai"], scanner["leaned_high"], scanner["needs_review"]) == ("off", True, True)  # model off: rules' answer

    ticket.pipeline_status = PipelineStatus.DQ_PASSED  # sent back, unchanged
    assert run_triage(db).skipped == first.by_verdict["uncertain"] + 1


def test_a_rulebook_change_re_triages(db, monkeypatch):
    ticket = db.get(Ticket, "AMS-1209")
    before = _input_hash(ticket, ticket.description)
    book = registry.read_file("triage_rules.yaml")
    book["review_shift"] = 1
    monkeypatch.setitem(registry.overrides, "triage_rules.yaml", book)
    bump_config_version()
    try:
        assert _input_hash(ticket, ticket.description) != before
    finally:
        registry.overrides.clear()
        bump_config_version()


def test_model_stage_reports_facts_and_the_code_sets_the_priority(db, provider):  # noqa: F811
    answer = TriageAssessment(application="StockSense", rule="scanner_sync", scope="single",
                              scope_quote="My handheld scanner HHD-PUN-098", context_applies=False, context_quote=None,
                              reason="One scanner", **{**NO_IMPACT, "system_impact": "low",
                                                       "system_quote": "My handheld scanner HHD-PUN-098"})
    fake = provider(_reply(answer))
    run, error = triage_ticket(db, db.get(Ticket, "MBX-00006"))

    assert error is None
    assert (run.verdict, run.output["stage"], run.output["ai"], run.output["dropped_facts"]) == ("P3", "model", "used", [])
    request = fake.requests[0]
    content = request["messages"][0]["content"]
    assert "Ganesh" not in content  # the reporter's name is masked
    assert "Candidate rule: scanner_sync" in content and "Facts still unknown: scope" in content
    system = request["system"][0]
    assert "StockSense (Tier 1)" in system["text"] and "PAY_CALC_MONTHLY" in system["text"]
    assert system["cache_control"] == {"type": "ephemeral"}  # the rulebook is cached across calls
    assert run.output["audit"]["prompt_version"] == "triage_priority@4"
    assert run.output["impact"]["system"] == {"level": "low", "quote": "My handheld scanner HHD-PUN-098"}


def test_a_ticket_the_rules_settle_still_gets_its_impact_from_the_model(db, provider):  # noqa: F811
    answer = TriageAssessment(application="SalesConnect CRM", rule="account_locked", scope="wide", scope_quote=None,
                              context_applies=False, context_quote=None, reason="One login",
                              **{**NO_IMPACT, "system_impact": "low", "system_quote": "My CRM login is locked"})
    provider(_reply(answer))
    run, error = triage_ticket(db, db.get(Ticket, "AMS-1209"))

    assert error is None
    assert (run.verdict, run.output["stage"], run.output["ai"]) == ("P3", "rules", "used")  # the rules' priority stands
    assert run.output["impact"]["system"]["level"] == "low" and run.output["audit"]
    assert len(db.scalars(select(AgentRun).where(AgentRun.ticket_id == "AMS-1209")).all()) == 1


def test_model_outage_falls_back_to_the_rules(db, provider):  # noqa: F811
    provider(anthropic.APIConnectionError(message="down", request=None))
    run, error = triage_ticket(db, db.get(Ticket, "MBX-00006"))
    assert error is not None
    assert (run.verdict, run.output["ai"], run.output["needs_review"]) == ("P1", "failed", True)
    assert db.get(Ticket, "MBX-00006").pipeline_status == PipelineStatus.TRIAGED


async def test_check_endpoint_needs_a_dq_passed_ticket(client):
    await client.post("/api/v1/ingest")
    assert (await client.post("/api/v1/triage/tickets/AMS-1209/check")).status_code == 409
    assert (await client.post("/api/v1/triage/tickets/NOPE/check")).status_code == 404
    assert (await client.post("/api/v1/triage/run")).json()["evaluated"] == 0  # nothing has passed Data Quality yet


async def test_rulebook_is_editable_and_checked_through_the_admin_api(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "test-key")
    key = {"X-Admin-Key": "test-key", "X-Admin-User": "alan"}
    try:
        book = (await client.get("/api/v1/admin/documents/triage_rules", headers=key)).json()["document"]
        book["applications"]["InsightBI"]["ceiling"] = 3
        assert (await client.put("/api/v1/admin/documents/triage_rules", headers=key, json={"document": book})).status_code == 200
        assert get_config().applications["InsightBI"].ceiling == 3

        book["must_follow"][2]["rule"] = "no_such_rule"
        assert (await client.put("/api/v1/admin/documents/triage_rules", headers=key, json={"document": book})).status_code == 422
        jobs = (await client.get("/api/v1/admin/documents/triage_jobs", headers=key)).json()["document"]
        jobs["jobs"]["PAY_CALC_MONTHLY"]["critical_in"] = "nope"
        assert (await client.put("/api/v1/admin/documents/triage_jobs", headers=key, json={"document": jobs})).status_code == 422
    finally:
        registry.overrides.clear()
        bump_config_version()
