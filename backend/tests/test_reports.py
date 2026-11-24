"""Admin reports: the numbers for a small, known set of tickets."""

from datetime import UTC, datetime, timedelta

from app.models.ticket import AgentRun, Feedback, PipelineStatus, Review, Ticket
from app.services.reports import reports
from tests.test_knowledge import session  # noqa: F401  (fixture)

NOW = datetime(2026, 11, 20, 12, 0)


def _ticket(i: str, app: str | None, opened_h: float, done_h: float | None = None, assignee: str | None = "Alan Test") -> Ticket:
    opened = NOW - timedelta(hours=opened_h)
    return Ticket(id=i, source="JIRA", application=app, summary=i, description="d", assignee=assignee,
                  status="resolved" if done_h is not None else "in_progress", pipeline_status=PipelineStatus.REVIEWED,
                  opened_at=opened, resolved_at=opened + timedelta(hours=done_h) if done_h is not None else None)


def test_reports_count_tickets_agents_outcomes_and_engineers(session):  # noqa: F811
    met, late = _ticket("A", "PayrollPro", 10, 4), _ticket("B", "PayrollPro", 30, 20)  # P2 target: 8 hours
    waiting = _ticket("C", None, 20, assignee=None)
    session.add_all([met, late, waiting])
    session.flush()
    at = NOW.replace(tzinfo=UTC) - timedelta(hours=1)
    triage = [AgentRun(ticket_id=t.id, agent="triage", verdict="P2", output={"priority": 2}, created_at=at) for t in (met, late)]
    fixes = [AgentRun(ticket_id="A", agent="resolution", verdict="resolved", created_at=at,
                      output={"audit": [{"input_tokens": 100, "output_tokens": 20}]}),
             AgentRun(ticket_id="B", agent="resolution", verdict="no_match", output={"ai": "failed"}, created_at=at)]
    note = AgentRun(ticket_id="A", agent="closure_quality", verdict="good", output={"score": 5}, created_at=at)
    session.add_all([*triage, *fixes, note])
    session.flush()
    by_alan = {"reviewer": "Alan Test", "created_at": at}
    session.add_all([
        Review(ticket_id="A", agent_run_id=fixes[0].id, agent="resolution", action="wrong", note="n", **by_alan),
        Review(ticket_id="A", agent_run_id=fixes[0].id, agent="resolution", action="worked", **by_alan),
        Review(ticket_id="B", agent_run_id=triage[1].id, agent="triage", action="edited", final_priority=2, **by_alan),
        Review(ticket_id="A", agent_run_id=note.id, agent="lead_review", action="approved", reviewer="Lead", created_at=at),
        Feedback(ticket_id="A", agent_run_id=fixes[0].id, agent="resolution", stars=1, reason="", **by_alan),
        Feedback(ticket_id="A", agent_run_id=fixes[0].id, agent="resolution", stars=3, reason="", **by_alan),
    ])
    session.commit()

    r = reports(session, days=7, now=NOW.replace(tzinfo=UTC))
    payroll = next(a for a in r["applications"] if a["application"] == "PayrollPro")
    assert (payroll["opened"], payroll["resolved"], payroll["p1_p2"], payroll["sla_met"]) == (2, 2, 2, 0.5)
    assert (payroll["mean_hours_to_resolve"], payroll["runbook_fix"]) == (12.0, 0.5)
    assert next(a for a in r["applications"] if a["application"] == "No application")["open"] == 1

    resolution = next(a for a in r["agents"] if a["agent"] == "resolution")
    assert (resolution["runs"], resolution["model_used"], resolution["model_failed"], resolution["tokens"]) == (2, 0.5, 1, 120)
    assert (resolution["rated"], resolution["partially_correct"]) == (1, 1.0)  # a person's latest rating counts

    outcome = r["outcomes"][0]
    assert (outcome["fixes_confirmed"], outcome["first_fix"], outcome["mean_attempts"]) == (1, 0.0, 2.0)
    assert (outcome["mean_closure_score"], outcome["lead_approved"]) == (5.0, 1)

    alan = next(e for e in r["engineers"] if e["engineer"] == "Alan Test")
    assert (alan["closed"], alan["sla_breached"], alan["priority_changes"]) == (2, 1, 1)
    assert r["engineers"][-1]["engineer"] == "Unassigned"


async def test_reports_endpoint(client):
    body = (await client.get("/api/v1/dashboard/reports", params={"days": 30})).json()
    assert body["days"] == 30 and body["applications"] == [] and len(body["agents"]) == 5
    assert (await client.get("/api/v1/dashboard/reports", params={"days": 0})).status_code == 422
