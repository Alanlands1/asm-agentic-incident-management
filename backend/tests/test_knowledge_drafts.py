"""Knowledge Builder part 2: drafts for gaps and their checks, the expert's decision, the markdown export, and repeat
issues. The model is a scripted stand-in (no network)."""

from datetime import datetime, timedelta

import anthropic
import pytest
from sqlalchemy import select

from app.agents.knowledge_builder.drafting import KBDraftAnswer
from app.agents.knowledge_builder.model_check import KBMatch
from app.models.knowledge import KBDraft, ProblemCandidate, ResolvedCase
from app.models.ticket import AgentRun
from app.services.knowledge import drafts, problems, run_knowledge
from tests.test_knowledge import passed, session, ticket  # noqa: F401  (fixture and helpers)
from tests.test_llm import _reply, provider  # noqa: F401  (fixture)

JOINER = ("New joiner missing from payroll register",
          "Employee E15775 joined on 3 October but is not in the October payroll register.")
JOINER_FIX = ("The employee master sync skipped the employee because the joining date fell on a weekend. "
              "Triggered a manual sync and recalculated the register.")
NO_ARTICLE = _reply(KBMatch(article=None, evidence=None, reason="No article covers a missing new joiner"))


def answer(kind: str = "known_issue", **changes) -> KBDraftAnswer:
    if kind != "known_issue":
        return KBDraftAnswer(kind=kind, title=None, symptoms=[], root_cause=None, resolution_steps=[], escalation=None,
                             reason="Not a known issue")
    fields = {"title": "New joiner missing from the payroll register",
              "symptoms": ["A new joiner is not in the payroll register."],
              "root_cause": "The employee master sync skips a joining date that falls on a weekend.",
              "resolution_steps": ["Trigger a manual sync for the employee.", "Recalculate the register."],
              "escalation": "[expert to add]", "reason": "A known issue the knowledge base does not cover"}
    return KBDraftAnswer(kind=kind, **(fields | changes))


def gap(session, i: int = 1, name: str | None = None, app: str | None = "PayrollPro"):  # noqa: F811
    passed(session, ticket(i, JOINER, JOINER_FIX, app=app, name=name))


# ---- drafts ------------------------------------------------------------------------------------------------------


def test_a_known_issue_gap_gets_a_draft_that_waits_for_an_expert(session, provider):  # noqa: F811
    gap(session)
    provider(NO_ARTICLE, _reply(answer()))
    result = run_knowledge(session)
    assert (dict(result.by_status), dict(result.drafts)) == ({"gap": 1}, {"created": 1})

    draft = session.scalars(select(KBDraft)).one()
    case = session.get(ResolvedCase, "K-1")
    assert (draft.status, draft.kb_id, draft.application, draft.source_ticket_ids) == ("draft", None, "PayrollPro", ["K-1"])
    assert (case.gap_kind, case.draft_id) == ("known_issue", draft.id)
    text = drafts.export(draft)
    assert text.startswith("### DRAFT — New joiner missing from the payroll register")
    assert "**Escalation:** [expert to add]" in text and "_Drafted from K-1._" in text


@pytest.mark.parametrize("changes, problem", [
    ({"resolution_steps": ["Run PAY_SYNC_09 for the employee."]}, "not in the tickets: PAY_SYNC_09"),
    ({"escalation": "Ask Meera, the payroll admin."}, "a name or contact from the tickets"),
    ({"escalation": "Call the payroll desk on 98765 43210."}, "PHONE"),
    ({"symptoms": [], "root_cause": ""}, "no symptoms"),
])
def test_a_draft_that_fails_the_checks_is_not_shown(session, provider, changes, problem):  # noqa: F811
    gap(session, name="Meera Nair")
    provider(NO_ARTICLE, _reply(answer(**changes)))
    assert dict(run_knowledge(session).drafts) == {"rejected_by_checks": 1}
    assert session.scalars(select(KBDraft)).all() == []
    run = session.scalars(select(AgentRun).where(AgentRun.agent == "knowledge_builder")).one()
    assert any(problem in p for p in run.output["draft"]["problems"])


def test_a_request_or_a_problem_outside_the_knowledge_base_gets_no_draft(session, provider):  # noqa: F811
    gap(session, 1)
    vpn = ticket(2, ("VPN not connecting", "The VPN client shows gateway unreachable."), "Renewed the VPN gateway certificate.",
                 app=None)
    passed(session, vpn)
    fake = provider(NO_ARTICLE, _reply(answer("request")), NO_ARTICLE)
    assert dict(run_knowledge(session).drafts) == {"none": 2}
    assert (session.get(ResolvedCase, "K-1").gap_kind, session.get(ResolvedCase, "K-2").gap_kind) == ("request", "outside_kb")
    assert len(fake.requests) == 3  # no draft call for the VPN case: it is not an application in the knowledge base


def test_a_similar_gap_joins_the_open_draft_without_another_call(session, provider):  # noqa: F811
    gap(session, 1)
    passed(session, ticket(2, ("New joiner missing from the payroll register",
                               "Employee E20419 joined on 4 October but is not in the October payroll register."), JOINER_FIX))
    fake = provider(NO_ARTICLE, _reply(answer()), NO_ARTICLE)
    assert dict(run_knowledge(session).drafts) == {"created": 1, "joined": 1}
    assert session.scalars(select(KBDraft)).one().source_ticket_ids == ["K-1", "K-2"] and len(fake.requests) == 3


def test_a_failed_draft_call_is_tried_again_next_run(session, provider):  # noqa: F811
    gap(session)
    provider(NO_ARTICLE, anthropic.APIConnectionError(message="down", request=None))
    first = run_knowledge(session)
    assert (first.model_errors, dict(first.drafts)) == (1, {"failed": 1})
    provider(NO_ARTICLE, _reply(answer()))
    assert dict(run_knowledge(session).drafts) == {"created": 1}


# ---- the expert's decision ---------------------------------------------------------------------------------------


def drafted(session, provider, name=None):  # noqa: F811
    gap(session, name=name)
    provider(NO_ARTICLE, _reply(answer()))
    run_knowledge(session)
    return session.scalars(select(KBDraft)).one()


def test_approval_needs_every_gap_filled_and_gives_the_next_article_id(session, provider):  # noqa: F811
    draft = drafted(session, provider)
    with pytest.raises(drafts.DraftError, match="expert to add"):
        drafts.review_draft(session, draft, "approved", "expert@contoso.com")
    edited = drafts.review_draft(session, draft, "edited", "expert@contoso.com",
                                 {"escalation": "Payroll Dev team if the manual sync fails again."})
    assert (edited.status, edited.kb_id) == ("approved", "KB-PAY-006")
    assert edited.escalation == "Payroll Dev team if the manual sync fails again."
    assert drafts.export(edited).startswith("### KB-PAY-006 — New joiner missing from the payroll register")
    assert drafts.next_kb_id(session, "PayrollPro") == "KB-PAY-007"
    with pytest.raises(drafts.AlreadyDecided):
        drafts.review_draft(session, edited, "rejected", "expert@contoso.com", reason_code="other")


def test_a_gap_with_a_hint_still_blocks_approval(session, provider):  # noqa: F811
    gap(session)
    provider(NO_ARTICLE, _reply(answer(escalation="Payroll Dev team.", resolution_steps=["[expert to add: the sync job name]"])))
    run_knowledge(session)
    draft = session.scalars(select(KBDraft)).one()
    with pytest.raises(drafts.DraftError, match="expert to add"):
        drafts.review_draft(session, draft, "approved", "expert@contoso.com")


def test_an_edit_may_add_knowledge_but_not_personal_data(session, provider):  # noqa: F811
    draft = drafted(session, provider, name="Meera Nair")
    with pytest.raises(drafts.DraftError, match="personal data"):
        drafts.review_draft(session, draft, "edited", "expert@contoso.com", {"escalation": "Ask Meera Nair in payroll."})
    with pytest.raises(drafts.DraftError, match="changed text"):
        drafts.review_draft(session, draft, "edited", "expert@contoso.com", {"title": draft.title})
    approved = drafts.review_draft(session, draft, "edited", "expert@contoso.com",
                                   {"escalation": "Raise PAYDEV-SYNC with the payroll developers."})  # an expert may add a code
    assert approved.status == "approved"


def test_a_rejection_needs_a_reason(session, provider):  # noqa: F811
    draft = drafted(session, provider)
    with pytest.raises(drafts.DraftError, match="reason_code"):
        drafts.review_draft(session, draft, "rejected", "expert@contoso.com")
    rejected = drafts.review_draft(session, draft, "rejected", "expert@contoso.com", reason_code="duplicate")
    assert (rejected.status, rejected.kb_id, rejected.reason_code) == ("rejected", None, "duplicate")


# ---- repeat issues -----------------------------------------------------------------------------------------------


def closures(session, days: list[int], article: str = "KB-PAY-002", start: int = 0) -> None:  # noqa: F811
    session.add_all(ResolvedCase(ticket_id=f"R-{start + i}", application="PayrollPro", summary="s", description="d", notes="n",
                                 match_status="matched", kb_article_id=article,
                                 closed_at=datetime(2026, 9, 1) + timedelta(days=d))
                    for i, d in enumerate(days))
    session.commit()


@pytest.mark.parametrize("days, raised", [([0, 10, 25], True), ([0, 10], False), ([0, 20, 40], False)])
def test_the_same_article_three_times_in_thirty_days_suggests_a_problem_record(session, days, raised):  # noqa: F811
    closures(session, days)
    found = problems.detect_problems(session)
    assert bool(found) is raised
    if raised:
        assert (found[0].issue_key, found[0].ticket_ids, found[0].cases) == ("article:KB-PAY-002", ["R-0", "R-1", "R-2"], 3)


def test_a_decided_suggestion_is_not_raised_again_for_the_same_tickets(session):  # noqa: F811
    closures(session, [0, 10, 25])
    candidate = problems.detect_problems(session)[0]
    session.commit()
    problems.decide(session, candidate, "dismissed", "lead@contoso.com", "Fixed for good in the October release")
    assert problems.detect_problems(session) == []
    with pytest.raises(problems.ProblemError):
        problems.decide(session, candidate, "accepted", "lead@contoso.com")
    closures(session, [27], start=3)  # a new closure: a new suggestion
    assert problems.detect_problems(session)[0].cases == 4


# ---- endpoints ---------------------------------------------------------------------------------------------------


async def test_draft_and_problem_endpoints(client):
    assert (await client.get("/api/v1/knowledge/drafts")).json() == []
    assert (await client.get("/api/v1/knowledge/drafts", params={"status": "nope"})).status_code == 422
    assert (await client.get("/api/v1/knowledge/drafts/9")).status_code == 404
    assert (await client.get("/api/v1/knowledge/drafts/9/export")).status_code == 404
    body = {"action": "rejected", "reviewer": "expert@contoso.com", "reason_code": "duplicate"}
    assert (await client.post("/api/v1/knowledge/drafts/9/review", json=body)).status_code == 404
    assert (await client.post("/api/v1/knowledge/drafts/9/review", json={**body, "reason_code": "nope"})).status_code == 422
    assert (await client.get("/api/v1/knowledge/problems")).json() == []
    decision = {"action": "accepted", "decided_by": "lead@contoso.com"}
    assert (await client.post("/api/v1/knowledge/problems/9/decision", json=decision)).status_code == 404
    assert ProblemCandidate.__tablename__ == "problem_candidates"
