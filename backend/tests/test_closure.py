"""Closure Quality: rules, the model stage against a scripted provider (no network), the run, review and endpoints."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agents.closure_quality.model_check import ClosureFacts, cited_articles, invented, verified
from app.agents.closure_quality.rules import evaluate
from app.core import registry
from app.core.config import bump_config_version, settings
from app.db.session import Base
from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket
from app.services.closure import judge, review, run_closure
from tests.test_llm import _reply, provider  # noqa: F401  (fixture)

SUMMARY, PROBLEM = "Order stuck", "Order ORD-4411021 is stuck in Pending Payment since the morning."
GOOD = ("The payment webhook timed out because the signing key was rotated. Updated the key in payment-service and replayed "
        "the 14 stuck events. A test order moved to Paid straight away.")
CITED = "Followed KB-BI-003. Owner approval attached. Added user to BI workspace viewers group and assigned RLS role for region."


def ticket(i: int, notes: str | None, status: str = "resolved", pipeline=PipelineStatus.REVIEWED, name=None) -> Ticket:
    return Ticket(
        id=f"T-{i}", source="JIRA", reporter_name=name, summary=SUMMARY, description=PROBLEM, status=status,
        pipeline_status=pipeline, resolution_notes=notes, opened_at=datetime(2026, 10, 1) + timedelta(days=i),
        closed_at=datetime(2026, 10, 2) + timedelta(days=i),
    )


def facts(cause="specific", action="specific", check="specific", draft=None, quotes=("same", "same", "same")) -> ClosureFacts:
    """A model answer; the quotes default to a stretch of GOOD that is really in the notes."""
    real = ["signing key was rotated", "Updated the key in payment-service", "A test order moved to Paid"]
    q = [real[i] if quotes[i] == "same" else quotes[i] for i in range(3)]
    return ClosureFacts(cause_level=cause, cause_quote=q[0] if cause != "none" else None,
                        action_level=action, action_quote=q[1] if action != "none" else None,
                        check_level=check, check_quote=q[2] if check != "none" else None,
                        draft_notes=draft, reason="reason")


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ---- rules -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("notes, verdict, rule", [
    (None, "needs_work", "empty"),
    ("  ", "needs_work", "empty"),
    ("N/A.", "needs_work", "filler"),
    ("Working now", "needs_work", "filler"),
    ("Restarted it.", "needs_work", "too_short"),
    (PROBLEM, "needs_work", "copy_of_description"),
    ("Test ticket, closed without action.", "not_applicable", "test_ticket"),
    ("Restarted the application service and it is working normally now.", "uncertain", None),  # vague: left for the model
    (GOOD, "uncertain", None),  # rules never pass a note
])
def test_rules_stop_only_what_they_are_sure_of(notes, verdict, rule):
    result = evaluate(notes, SUMMARY, PROBLEM)
    assert (result.verdict, result.rule) == (verdict, rule)


# ---- model stage -------------------------------------------------------------------------------------------------


def test_levels_without_a_real_quote_drop_to_none():
    answer = facts(action="specific", quotes=("same", "scaled the database cluster", "same"))
    levels, quotes, dropped = verified(answer, GOOD)
    assert (levels, dropped, quotes["action"]) == ({"cause": 2, "action": 0, "check": 2}, ["action"], None)
    short = facts(quotes=("same", "key", "same"))  # too short to prove anything
    assert verified(short, GOOD)[2] == ["action"]


def test_a_good_note_passes_and_a_weak_one_is_held_with_questions_and_a_draft(provider):  # noqa: F811
    fake = provider(_reply(facts()), _reply(facts(cause="none", action="vague", check="none", draft=None,
                                                  quotes=("same", "Updated the key in payment-service", "same"))))
    verdict, output, error = judge(ticket(1, GOOD, name="Meera Nair"))
    assert (verdict, error, output["score"], output["questions"], output["draft_notes"]) == ("good", None, 6, [], None)
    assert output["ai"] == "used" and output["audit"]["prompt_version"] == "closure_score@1"
    assert "Meera" not in fake.requests[0]["messages"][0]["content"]  # names are masked

    draft = "Updated the key in payment-service. [engineer to add: cause] [engineer to add: check]"
    provider(_reply(facts(cause="none", action="vague", check="none", draft=draft,
                          quotes=("same", "Updated the key in payment-service", "same"))))
    verdict, output, _ = judge(ticket(2, GOOD))
    assert (verdict, output["score"], output["draft_notes"]) == ("needs_work", 1, draft)
    assert len(output["questions"]) == 3 and output["questions"][0].startswith("What caused it")


def test_a_draft_with_an_invented_code_is_dropped(provider):  # noqa: F811
    draft = "Replayed the 14 stuck events after ORA-99999 was cleared. [engineer to add: check]"
    provider(_reply(facts(cause="vague", action="vague", check="none", draft=draft)))
    verdict, output, _ = judge(ticket(1, GOOD))
    assert verdict == "needs_work" and output["draft_notes"] is None and output["draft_invented"] == ["ORA-99999"]
    assert invented("Replayed the 14 events", GOOD) == [] and invented("Raised CHG-1234", GOOD) == ["CHG-1234"]


def test_a_cited_article_stands_in_for_the_cause_when_the_action_is_specific(provider, monkeypatch):  # noqa: F811
    held = facts(cause="none", action="specific", check="none",
                 quotes=("same", "Added user to BI workspace viewers group", "same"))
    assert cited_articles(CITED + " Also KB-XXX-999.") == ["KB-BI-003"]  # an id that does not exist earns nothing

    provider(_reply(held))
    verdict, output, _ = judge(ticket(1, CITED))
    assert (verdict, output["levels"]["cause"], output["kb_cited"]) == ("good", 2, ["KB-BI-003"])

    vague = facts(cause="none", action="vague", check="vague", quotes=("same", "Owner approval attached", "assigned RLS role"))
    provider(_reply(vague))
    assert judge(ticket(2, CITED))[0] == "needs_work"  # a vague action earns no credit for the citation

    book = registry.read_file("closure_rules.yaml")
    book["kb_citation_is_cause"] = False
    monkeypatch.setitem(registry.overrides, "closure_rules.yaml", book)
    bump_config_version()
    try:
        provider(_reply(held))
        assert judge(ticket(3, CITED))[0] == "needs_work"  # the switch is off
    finally:
        registry.overrides.clear()
        bump_config_version()


def test_without_the_model_the_rules_leave_a_note_unjudged_and_it_is_retried_when_the_model_is_on(session):
    session.add(ticket(1, GOOD))
    session.commit()
    run_closure(session)
    run = session.scalars(select(AgentRun)).one()
    assert (run.verdict, run.output["ai"], run.input_hash is not None) == ("uncertain", "off", True)  # nothing to retry yet
    assert run_closure(session).skipped == 1


# ---- the run -----------------------------------------------------------------------------------------------------


def test_run_checks_resolved_tickets_skips_history_and_unchanged_notes(session):
    session.add_all([
        ticket(1, "done"), ticket(2, GOOD), ticket(3, "ok", status="in_progress"),
        ticket(4, "fixed", pipeline=PipelineStatus.HISTORICAL),
    ])
    session.commit()

    first = run_closure(session)
    assert (first.evaluated, first.skipped, dict(first.by_verdict)) == (2, 0, {"needs_work": 1, "uncertain": 1})
    assert run_closure(session).skipped == 2  # nothing changed

    session.get(Ticket, "T-1").resolution_notes = "Reset the lock and confirmed with the user."
    assert run_closure(session).evaluated == 1  # a changed note is checked again

    history = run_closure(session, include_history=True)
    old = session.scalars(select(AgentRun).where(AgentRun.ticket_id == "T-4")).one()
    assert history.evaluated == 1 and old.verdict == "needs_work"


def test_a_model_outage_leaves_the_note_unjudged_and_retries_it(session, provider):  # noqa: F811
    import anthropic

    provider(anthropic.APIConnectionError(message="down", request=None))
    session.add(ticket(1, GOOD))
    session.commit()
    result = run_closure(session)
    run = session.scalars(select(AgentRun)).one()
    assert (result.model_errors, run.verdict, run.output["ai"], run.input_hash) == (1, "uncertain", "failed", None)
    provider(_reply(facts()))
    assert run_closure(session).evaluated == 1
    assert session.scalars(select(AgentRun).order_by(AgentRun.id.desc())).first().verdict == "good"


# ---- review ------------------------------------------------------------------------------------------------------


def seeded(session, notes="done"):
    session.add(ticket(1, notes))
    session.commit()
    run_closure(session)
    return session.get(Ticket, "T-1")


def test_queue_puts_the_lowest_score_first_and_drops_decided_checks(session):
    session.add_all([ticket(1, "done"), ticket(2, "Restarted the application service and it is working normally now.")])
    session.commit()
    run_closure(session)
    order = [t.id for t, _ in review.pending(session)]
    assert order == ["T-1"]  # only the note the rules stopped; the vague one stays unjudged while the model is off
    review.review(session, session.get(Ticket, "T-1"), "rejected", "ravi@contoso.com", reason_code="notes_fine")
    assert review.pending(session) == []


def test_decisions_that_do_not_fit_are_refused(session):
    t = seeded(session)
    with pytest.raises(review.ReviewError, match="no draft"):
        review.review(session, t, "accepted", "ravi@contoso.com")  # a rules stop has no draft
    with pytest.raises(review.ReviewError, match="new notes"):
        review.review(session, t, "edited", "ravi@contoso.com", final_text="done")
    with pytest.raises(review.ReviewError, match="still be stopped"):
        review.review(session, t, "edited", "ravi@contoso.com", final_text="fixed.")
    with pytest.raises(review.ReviewError, match="reason_code"):
        review.review(session, t, "rejected", "ravi@contoso.com")
    assert not session.scalars(select(Review)).all() and t.resolution_notes == "done"


def test_edit_and_accept_store_the_final_notes_and_never_change_the_ticket(session):
    t = seeded(session)
    decision = review.review(session, t, "edited", "ravi@contoso.com", final_text=GOOD)
    assert (decision.final_text, decision.action, decision.agent) == (GOOD, "edited", "closure_quality")
    assert t.resolution_notes == "done"  # the source note is never changed
    with pytest.raises(review.AlreadyReviewed):
        review.review(session, t, "rejected", "ravi@contoso.com", reason_code="other")


def test_a_draft_with_gaps_cannot_be_accepted_but_a_complete_one_can(session):
    t = seeded(session)
    run = session.scalars(select(AgentRun)).one()
    run.output = {**run.output, "draft_notes": "Updated the key. [engineer to add: check]"}
    with pytest.raises(review.ReviewError, match="gaps"):
        review.review(session, t, "accepted", "ravi@contoso.com")
    run.output = {**run.output, "draft_notes": GOOD}
    assert review.review(session, t, "accepted", "ravi@contoso.com").final_text == GOOD


def test_report_counts_checks_decisions_and_rule_stops(session):
    t = seeded(session)
    review.review(session, t, "rejected", "ravi@contoso.com", reason_code="check_wrong")
    r = review.report(session)
    assert (r.checks["needs_work"], r.by_rule["filler"], r.reviewed, r.check_wrong_rate) == (1, 1, 1, 1.0)
    assert r.by_reason == {"check_wrong": 1}


# ---- endpoints and admin -----------------------------------------------------------------------------------------


async def test_closure_endpoints(client):
    await client.post("/api/v1/ingest")
    assert (await client.post("/api/v1/closure/run")).json()["evaluated"] == 0  # everything closed arrived closed: history
    history = (await client.post("/api/v1/closure/run", params={"include_history": True})).json()
    assert history["evaluated"] == 15 and history["model_errors"] == 0  # the 15 closed JIRA tickets
    assert (await client.post("/api/v1/closure/tickets/NOPE/check")).status_code == 404
    assert (await client.post("/api/v1/closure/tickets/AMS-1209/check")).status_code == 409  # still open
    assert (await client.get("/api/v1/closure/queue")).json() == []
    body = {"action": "rejected", "reviewer": "ravi@contoso.com", "reason_code": "other"}
    assert (await client.post("/api/v1/closure/tickets/NOPE/review", json=body)).status_code == 404
    assert (await client.post("/api/v1/closure/tickets/AMS-1209/review", json=body)).status_code == 422  # nothing to decide
    assert (await client.post("/api/v1/closure/tickets/AMS-1209/review", json={**body, "reason_code": "nope"})).status_code == 422
    assert (await client.get("/api/v1/closure/report")).json()["reviewed"] == 0


async def test_closure_rules_are_edited_and_checked_through_the_admin_api(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "test-key")
    key = {"X-Admin-Key": "test-key", "X-Admin-User": "alan"}
    try:
        rules = (await client.get("/api/v1/admin/documents/closure_rules", headers=key)).json()["document"]
        rules["min_length"] = 10
        put = await client.put("/api/v1/admin/documents/closure_rules", headers=key, json={"document": rules})
        assert put.status_code == 200
        assert evaluate("Restarted it now.", SUMMARY, PROBLEM).verdict == "uncertain"  # 17 characters: no longer too short

        rules["pass"]["min_total"] = 9
        put = await client.put("/api/v1/admin/documents/closure_rules", headers=key, json={"document": rules})
        assert put.status_code == 422
    finally:
        registry.overrides.clear()
        bump_config_version()
