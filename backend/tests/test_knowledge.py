"""Knowledge Builder: the article reader, the matching rules, the model stage against a scripted provider (no network),
the run that saves masked cases, and coverage."""

from datetime import datetime, timedelta

import anthropic
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agents.knowledge_builder.articles import articles, articles_version, codes
from app.agents.knowledge_builder.drafting import KBDraftAnswer
from app.agents.knowledge_builder.matching import evaluate
from app.agents.knowledge_builder.model_check import KBMatch, checked
from app.core import registry
from app.core.config import bump_config_version, settings
from app.db.session import Base
from app.models.knowledge import ResolvedCase
from app.models.ticket import AgentRun, PipelineStatus, Review, Ticket
from app.services.knowledge import coverage, match_case, run_knowledge
from tests.test_llm import _reply, provider  # noqa: F401  (fixture)

BATCH = ("Payroll batch failed",
         "Control-M job PAY_CALC_MONTHLY ended Not OK with ORA-01555; the payroll period cannot be locked.")
FIX = "Re-ran the job in chunks of 500 from the last good chunk. The run completed and the variance report was shared."
VPN = ("VPN not connecting from home", "The VPN client shows Connection failed - gateway unreachable since yesterday.")
VPN_FIX = "The VPN gateway certificate had expired. The network team renewed it. Tested the VPN client from home."


def ticket(i: int, summary_description=BATCH, notes=FIX, app: str | None = "PayrollPro", name: str | None = None,
           status: str = "resolved") -> Ticket:
    return Ticket(
        id=f"K-{i}", source="JIRA", reporter_name=name, application=app, summary=summary_description[0],
        description=summary_description[1], status=status, pipeline_status=PipelineStatus.REVIEWED, resolution_notes=notes,
        opened_at=datetime(2026, 10, 1) + timedelta(days=i), closed_at=datetime(2026, 10, 2) + timedelta(days=i),
    )


def passed(session, *tickets: Ticket, verdict="good", quotes=None) -> None:
    """Close notes that passed Closure Quality."""
    session.add_all(tickets)
    session.commit()
    found = quotes or {"cause": None, "action": "Re-ran the job in chunks", "check": None}
    session.add_all(AgentRun(ticket_id=t.id, agent="closure_quality", verdict=verdict, input_hash="x",
                             output={"score": 6, "quotes": found}) for t in tickets)
    session.commit()


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ---- the articles ------------------------------------------------------------------------------------------------


def test_the_articles_are_read_with_their_title_symptoms_and_codes():
    found = articles()
    assert len(found) == 35 and {a.app for a in found.values()} >= {"PayrollPro", "OrderHub", "SalesConnect CRM"}
    batch = found["KB-PAY-002"]
    assert batch.title == "Monthly payroll batch PAY_CALC_MONTHLY fails" and "ORA-01555" in batch.codes
    assert "Control-M" in batch.symptoms and articles_version() == articles_version()
    assert codes("See KB-PAY-002 and ORA-01555, job PAY_CALC_MONTHLY, INC0010231") == {"ORA-01555", "PAY_CALC_MONTHLY"}


# ---- rules -------------------------------------------------------------------------------------------------------


def test_a_cited_article_that_exists_is_a_match_and_one_that_does_not_is_ignored():
    cited = evaluate(*BATCH, "Followed KB-PAY-002. " + FIX, "PayrollPro")
    assert (cited.status, cited.article, cited.method) == ("matched", "KB-PAY-002", "cited")
    assert evaluate("Slow", "Pages are slow.", "Followed KB-XXX-999. Restarted it.", "PayrollPro").status == "uncertain"


def test_a_citation_that_disagrees_with_the_ticket_or_cites_several_is_not_trusted():
    other_app = evaluate(*BATCH, "Followed KB-ORD-001. " + FIX, "PayrollPro")
    assert other_app.status == "uncertain" and "OrderHub" in other_app.reason
    several = evaluate(*BATCH, "Followed KB-PAY-001 and KB-PAY-002. " + FIX, "PayrollPro")
    assert several.status == "uncertain" and "several" in several.reason


def test_a_shared_error_code_and_word_overlap_match_without_a_citation():
    by_code = evaluate("Job failed", "Job log shows ORA-01555 snapshot too old.", FIX, "PayrollPro")
    assert (by_code.article, by_code.method) == ("KB-PAY-002", "code")
    by_words = evaluate("Handheld will not download pick lists", "After the Android update the handheld says the device is not "
                        "registered and no pick lists load.", "Pushed a new certificate from the MDM console.", "StockSense")
    assert (by_words.article, by_words.method) == ("KB-STK-001", "keywords")


def test_rules_never_say_no_article_and_do_not_force_an_unrelated_case_onto_one():
    result = evaluate(*VPN, VPN_FIX, None)  # no application: every article is a candidate
    assert (result.status, result.article, result.method) == ("uncertain", None, None)
    scores = [score for _, score in result.ranking]
    assert len(result.ranking) == 35 and scores == sorted(scores, reverse=True)  # every article, best first
    payslip_link = evaluate("Payslip link on homepage gives 404", "The My Payslips link returns 404 Page Not Found.",
                            "Updated the link to the new payslip route.", "EmployeePortal")
    assert payslip_link.article != "KB-PAY-001"  # a broken link is not a blank payslip PDF


# ---- model stage -------------------------------------------------------------------------------------------------


def test_a_gap_a_match_and_an_answer_that_cannot_be_trusted(provider):  # noqa: F811
    t = ticket(1, VPN, VPN_FIX, app=None, name="Meera Nair")
    fake = provider(_reply(KBMatch(article=None, evidence=None, reason="Network, not an application issue")))
    status, article, method, output, error = match_case(t, VPN_FIX)
    assert (status, article, method, error) == ("gap", None, None, None) and output["ai"] == "used"
    content = fake.requests[0]["messages"][0]["content"]
    assert "Meera" not in content and "Candidate articles:" in content and content.count("\n- KB-") == 5  # the 5 best, masked

    hard = ticket(2, ("Cannot change my picture", "Trying to change the profile picture just says upload failed."),
                  "The image was larger than the allowed size. Resized it and uploaded again.", app="EmployeePortal")
    provider(_reply(KBMatch(article="KB-EMP-005", evidence="change the profile picture", reason="Same symptom")))
    assert match_case(hard, hard.resolution_notes)[:3] == ("matched", "KB-EMP-005", "model")

    provider(_reply(KBMatch(article="KB-EMP-005", evidence="words that are not in the case", reason="?")))
    status, article, _, output, _ = match_case(hard, hard.resolution_notes)
    assert (status, article) == ("uncertain", None) and "exact words" in output["problem"]


def test_the_answer_must_name_an_article_it_was_shown_with_words_from_the_case():
    case = "The profile picture upload fails with upload failed."
    good = KBMatch(article="KB-EMP-005", evidence="profile picture upload fails", reason="r")
    assert checked(good, ["KB-EMP-005", "KB-EMP-003"], case) == ("KB-EMP-005", None)
    assert checked(good, ["KB-EMP-003"], case)[0] is None  # not one of the articles shown
    assert checked(KBMatch(article="KB-EMP-005", evidence="fails", reason="r"), ["KB-EMP-005"], case)[0] is None  # too short
    assert checked(KBMatch(article=None, evidence=None, reason="none fits"), ["KB-EMP-005"], case) == (None, None)


# ---- the run -----------------------------------------------------------------------------------------------------


def test_the_run_saves_masked_cases_only_for_notes_that_passed(session):
    named = "Followed KB-PAY-002. Meera Nair re-ran the job in chunks of 500 and confirmed it works."
    good, weak, open_ = ticket(1, notes=named, name="Meera Nair"), ticket(2), ticket(3, status="in_progress")
    passed(session, good, open_)
    session.add(weak)
    session.add(AgentRun(ticket_id="K-2", agent="closure_quality", verdict="needs_work", input_hash="x", output={"score": 1}))
    session.commit()

    result = run_knowledge(session)
    assert (result.evaluated, dict(result.by_status)) == (1, {"matched": 1})
    case = session.get(ResolvedCase, "K-1")
    assert (case.match_status, case.kb_article_id, case.match_method, case.score) == ("matched", "KB-PAY-002", "cited", 6)
    assert "Meera" not in case.notes and "<PERSON_1>" in case.notes  # names are masked
    assert case.action == "Re-ran the job in chunks"  # the words Closure Quality found, kept for unedited notes
    assert session.get(ResolvedCase, "K-2") is None and session.get(ResolvedCase, "K-3") is None
    assert run_knowledge(session).skipped == 1  # nothing changed


def test_an_engineers_edited_notes_are_what_is_saved_and_matched(session):
    weak = ticket(1, notes="done")
    session.add(weak)
    session.commit()
    run = AgentRun(ticket_id="K-1", agent="closure_quality", verdict="needs_work", input_hash="x",
                   output={"score": 0, "quotes": None})
    session.add(run)
    session.commit()
    session.add(Review(ticket_id="K-1", agent_run_id=run.id, agent="closure_quality", action="edited",
                       reviewer="ravi@contoso.com", final_text="Followed KB-PAY-002. " + FIX))
    session.commit()

    run_knowledge(session)
    case = session.get(ResolvedCase, "K-1")
    assert case.match_method == "cited" and case.notes.startswith("Followed KB-PAY-002")
    assert case.action is None  # the quotes belong to the original notes, so an edit has none


def test_with_the_model_off_a_case_the_rules_are_unsure_of_stays_unmatched(session):
    passed(session, ticket(1, VPN, VPN_FIX, app=None))
    assert dict(run_knowledge(session).by_status) == {"uncertain": 1}  # only the model can say "no article"
    assert run_knowledge(session).skipped == 1  # nothing to retry until the model is switched on


def test_an_outage_leaves_the_case_unmatched_and_it_is_retried(session, provider):  # noqa: F811
    passed(session, ticket(1, VPN, VPN_FIX, app=None))
    fake = provider(anthropic.APIConnectionError(message="down", request=None))
    outage = run_knowledge(session)
    run = session.scalars(select(AgentRun).where(AgentRun.agent == "knowledge_builder").order_by(AgentRun.id.desc())).first()
    assert (outage.model_errors, run.verdict, run.input_hash) == (1, "uncertain", None)  # retried next run

    provider(_reply(KBMatch(article=None, evidence=None, reason="no article covers a VPN certificate")))
    assert dict(run_knowledge(session).by_status) == {"gap": 1}
    assert session.get(ResolvedCase, "K-1").match_status == "gap" and len(fake.requests) == 1


# ---- coverage ----------------------------------------------------------------------------------------------------


def test_coverage_counts_matched_and_gap_cases_and_unused_articles(session, provider):  # noqa: F811
    matched = ticket(1, notes="Followed KB-PAY-002. " + FIX)
    gap = ticket(2, ("New joiner missing from payroll", "Employee E15775 is not in the payroll register."),
                 "The sync skipped the employee. Triggered a manual sync and the employee now appears in the register.")
    passed(session, matched, gap)
    draft = KBDraftAnswer(kind="known_issue", title="New joiner missing from the payroll register",
                          symptoms=["A new joiner is not in the payroll register."], root_cause="The sync skipped the employee.",
                          resolution_steps=["Trigger a manual sync."], escalation="[expert to add]", reason="A known issue")
    provider(_reply(KBMatch(article=None, evidence=None, reason="no article covers it")), _reply(draft))
    run_knowledge(session)

    payroll = next(r for r in coverage.coverage(session) if r.application == "PayrollPro")
    assert (payroll.drafts_waiting, payroll.outside_kb) == (1, 0)
    assert (payroll.articles, payroll.cases, payroll.matched, payroll.gap, payroll.covered_share) == (5, 2, 1, 1, 0.5)
    assert "KB-PAY-002" not in payroll.unused_articles and len(payroll.unused_articles) == 4
    assert next(r for r in coverage.coverage(session) if r.application == "OrderHub").cases == 0  # every application is listed


# ---- endpoints and admin -----------------------------------------------------------------------------------------


async def test_knowledge_endpoints(client):
    await client.post("/api/v1/ingest")
    empty = {"evaluated": 0, "skipped": 0, "model_errors": 0, "by_status": {}, "drafts": {}, "open_problems": 0}
    assert (await client.post("/api/v1/knowledge/run")).json() == empty
    assert (await client.get("/api/v1/knowledge/cases")).json() == []
    assert (await client.get("/api/v1/knowledge/cases", params={"match_status": "nope"})).status_code == 422
    rows = (await client.get("/api/v1/knowledge/coverage")).json()
    assert len(rows) == 7 and all(r["articles"] == 5 and r["cases"] == 0 for r in rows)


async def test_knowledge_settings_are_edited_and_checked_through_the_admin_api(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "test-key")
    key = {"X-Admin-Key": "test-key", "X-Admin-User": "alan"}
    try:
        doc = (await client.get("/api/v1/admin/documents/knowledge", headers=key)).json()["document"]
        doc["match"]["min_score"] = 0.5
        put = await client.put("/api/v1/admin/documents/knowledge", headers=key, json={"document": doc})
        assert put.status_code == 200
        reworded = evaluate("Handheld will not download pick lists", "Device not registered, no pick lists load.",
                            "Pushed a certificate.", "StockSense")
        assert reworded.status == "uncertain"  # 0.5 is now too strict for this one

        doc["match"]["min_score"] = 7
        put = await client.put("/api/v1/admin/documents/knowledge", headers=key, json={"document": doc})
        assert put.status_code == 422
    finally:
        registry.overrides.clear()
        bump_config_version()
