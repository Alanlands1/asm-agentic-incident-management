"""End to end over the API: one ticket from ingestion to closed in Jira, then the reports.

Only each agent's model step is replaced (no network, no cost); everything else is real: the endpoints, the stages,
the reviews and ratings, the closure note, the email draft, the Jira write (to a fake site), Knowledge Builder and the
reports. Ingest -> Data Quality -> Triage -> (review) -> Resolution -> rating -> fix worked -> closure note -> email ->
(lead approval) -> send to Jira -> Knowledge Builder -> reports.
"""

from types import SimpleNamespace

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.closure_quality.model_check import ClosureFacts
from app.agents.closure_quality.requester_email import RequesterEmail
from app.agents.resolution import react
from app.agents.resolution.answer import ResolutionAnswer
from app.agents.resolution.retrieval import Filters
from app.db.session import get_db
from app.llm import CallAudit, ModelUnavailableError
from app.main import app
from app.services import atlassian, data_quality, jira
from app.services import resolution as resolution_service
from app.services.closure import run as closure_run
from app.services.triage import run as triage_run
from tests.test_llm import _reply, provider  # noqa: F401  (fixture)

TICKET = "AMS-1209"
ENGINEER = "Alan Test"
AUDIT = CallAudit(provider="anthropic", model="m", prompt_version="v", attempts=1, input_tokens=10, output_tokens=5,
                  latency_ms=1)
NOTE = ("Cause: the payslip job read a stale template. Fix: re-ran the payslip job with the new template. "
        "Checked: 40 payslips open.")


def _model_steps(monkeypatch):
    """Each agent's model step, scripted: Data Quality finds the ticket complete, the Triage model is unavailable (so
    the rules' own priority is used), Resolution finds a runbook fix, and Closure Quality finds every part specific."""
    complete = SimpleNamespace(complete=True, model_dump=lambda: {"complete": True})
    monkeypatch.setattr(data_quality, "check_completeness", lambda *a: (complete, AUDIT))

    def triage_model(*a):
        raise ModelUnavailableError("model down")

    monkeypatch.setattr(triage_run, "model_decision", triage_model)

    async def resolve(case, embedder=None):
        answer = ResolutionAnswer(verdict="resolved", root_cause="A stale payslip template.", confidence="high",
                                  steps=["Re-run the payslip job with the current template."], references=["KB-PAY-001"])
        return react.Resolution(answer=answer, filters=Filters(app=case.application), queries=[case.summary],
                                hypothetical=None, trace=[], audits=[AUDIT])

    monkeypatch.setattr(resolution_service, "resolve", resolve)
    facts = ClosureFacts(cause_level="specific", cause_quote="the payslip job read a stale template",
                         action_level="specific", action_quote="re-ran the payslip job with the new template",
                         check_level="specific", check_quote="40 payslips open", draft_notes=None, reason="Complete.")
    monkeypatch.setattr(closure_run, "assess_notes", lambda *a: (facts, AUDIT))


def _fake_jira(monkeypatch) -> list[tuple[str, str]]:
    calls = []

    def site(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/transitions") and request.method == "GET":
            done = {"id": "41", "to": {"name": "Done", "statusCategory": {"key": "done"}}}
            return httpx.Response(200, json={"transitions": [done]})
        return httpx.Response(204 if request.url.path.endswith("/transitions") else 201, json={})

    fake = httpx.MockTransport(site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    monkeypatch.setattr(jira.settings, "JIRA_WRITE_BACK", True)
    return calls


async def test_a_ticket_goes_from_ingestion_to_closed_in_jira_and_into_the_reports(client, provider, monkeypatch):  # noqa: F811
    _model_steps(monkeypatch)
    email = RequesterEmail(subject="Resolved: payslips open again", body="Hello,\n\nThe payslips open again.\n\nIT Support")
    provider(_reply(email))
    async for session in app.dependency_overrides[get_db]():  # Resolution opens its own sessions on the same database
        maker = async_sessionmaker(bind=session.bind, expire_on_commit=False)
        monkeypatch.setattr(resolution_service, "AsyncSessionLocal", maker)

    # Intake: ingest, then Data Quality and Triage on the ticket
    assert (await client.post("/api/v1/ingest")).json()["created"] == 50
    ran = await client.post(f"/api/v1/tickets/{TICKET}/run-agents", json={"agent": "data_quality"})
    stage = ran.json()["pipeline_status"]
    assert stage in ("triaged", "reviewed")
    if stage == "triaged":  # Triage lowered the priority: a person decides
        decision = {"action": "accepted", "reviewer": ENGINEER}
        assert (await client.post(f"/api/v1/triage/tickets/{TICKET}/review", json=decision)).status_code == 201

    # Resolution suggests the fix; the engineer rates it and says it worked
    assert (await resolution_service.run_resolution(ticket_id=TICKET)).by_verdict == {"resolved": 1}
    ticket = (await client.get(f"/api/v1/tickets/{TICKET}")).json()
    fix = next(r for r in reversed(ticket["agent_runs"]) if r["agent"] == "resolution")
    outcome = {"agent_run_id": fix["id"], "outcome": "worked", "reviewer": ENGINEER}
    confirmed = await client.post(f"/api/v1/tickets/{TICKET}/fix-outcome", json=outcome)
    assert confirmed.json()["pipeline_status"] == "fix_confirmed"
    rating = {"agent_run_id": fix["id"], "stars": 3, "reason": "Steps incomplete", "reviewer": ENGINEER}
    assert (await client.post(f"/api/v1/tickets/{TICKET}/feedback", json=rating)).status_code == 201  # partially correct

    # Closure: the note is saved and passes the check; the requester email is drafted from it
    assert (await client.put(f"/api/v1/tickets/{TICKET}/closure-note", json={"text": NOTE})).status_code == 200
    ticket = (await client.get(f"/api/v1/tickets/{TICKET}")).json()
    assert next(r for r in reversed(ticket["agent_runs"]) if r["agent"] == "closure_quality")["verdict"] == "good"
    email = (await client.post(f"/api/v1/closure/tickets/{TICKET}/email")).json()
    assert email["subject"] == "Resolved: payslips open again"
    if ticket["lead_review_required"]:
        assert (await client.post(f"/api/v1/tickets/{TICKET}/submit-review", json={"reviewer": ENGINEER})).status_code == 200
        approve = {"action": "approved", "reviewer": "Alan Lands"}
        approved = await client.post(f"/api/v1/tickets/{TICKET}/lead-review", json=approve)
        assert approved.json()["pipeline_status"] == "approved"

    # Close: the note goes to Jira and the issue moves to Done
    calls = _fake_jira(monkeypatch)
    closed = await client.post(f"/api/v1/tickets/{TICKET}/close", json={"author_email": ENGINEER})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert ("POST", f"/rest/api/3/issue/{TICKET}/comment") in calls  # the closure note
    assert calls[-1] == ("POST", f"/rest/api/3/issue/{TICKET}/transitions")  # then Done

    # Knowledge Builder saves the good fix as a case
    monkeypatch.setattr(jira.settings, "LLM_ENABLED", False)  # the rules match it, or it waits for the model
    assert (await client.post("/api/v1/knowledge/run")).json()["evaluated"] >= 1
    cases = (await client.get("/api/v1/knowledge/cases")).json()
    assert TICKET in [c["ticket_id"] for c in cases]

    # The reports count it
    reports = (await client.get("/api/v1/dashboard/reports", params={"days": 365})).json()
    resolution = next(a for a in reports["agents"] if a["agent"] == "resolution")
    assert (resolution["rated"], resolution["partially_correct"]) == (1, 1.0)  # the engineer's latest rating
    assert sum(o["fixes_confirmed"] for o in reports["outcomes"]) == 1
    owner = ticket["assignee"] or "Unassigned"
    assert next(e for e in reports["engineers"] if e["engineer"] == owner)["closed"] >= 1
