"""Admin home summary: ticket flow, agent results, review queue, sync health."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.session import get_db
from app.main import app
from app.models.jira import JiraSync
from app.models.servicenow import ServiceNowTicket
from app.models.ticket import AgentRun, Review, Ticket
from app.services.dashboard import sync_state

NOW = datetime.now(UTC)
TODAY = NOW.replace(hour=0, minute=0, second=0, microsecond=0)


def test_sync_state():
    now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert sync_state(None, 1, now) == "never"
    assert sync_state(now - timedelta(minutes=2), 0, now) == "off"
    assert sync_state(now - timedelta(minutes=2), 1, now) == "running"
    assert sync_state(now - timedelta(minutes=4), 1, now) == "stale"
    assert sync_state((now - timedelta(minutes=2)).replace(tzinfo=None), 1, now) == "running"  # SQLite drops the zone


@pytest.fixture
async def seeded(client):
    async for db in app.dependency_overrides[get_db]():
        def t(i, stage, minutes, **kw):
            return Ticket(id=f"J-{i}", source="JIRA", summary="s", status="new", pipeline_status=stage,
                          ingested_at=TODAY + timedelta(minutes=minutes), **kw)

        db.add_all([
            t(1, "pending", -120),
            t(2, "triaged", 5, opened_at=datetime(2026, 11, 1, 8, 0)),
            t(3, "awaiting_info", 6),
            t(4, "historical", 7),
            ServiceNowTicket(ticket_id="INC1", created_at=TODAY + timedelta(minutes=8)),
            ServiceNowTicket(ticket_id="J-2", created_at=TODAY + timedelta(minutes=9)),  # a Jira issue's console row
        ])
        await db.flush()
        at = TODAY + timedelta(minutes=10)
        db.add_all([
            AgentRun(ticket_id="J-2", agent="data_quality", verdict="passed", output={"stage": "model"}, created_at=at),
            AgentRun(ticket_id="J-3", agent="data_quality", verdict="needs_info", output={"stage": "rules", "ai": "failed"},
                     created_at=at),
            AgentRun(ticket_id="J-2", agent="triage", verdict="P2", created_at=at, output={
                "ai": "used", "priority": 2, "rule": "r", "reason": "x", "stage": "model", "needs_review": False,
            }),
            AgentRun(ticket_id="J-3", agent="triage", verdict="P3", output={"ai": "failed"}, created_at=at),
            AgentRun(ticket_id="J-1", agent="triage", verdict="P4", output={"ai": "not_needed"},
                     created_at=TODAY - timedelta(hours=1)),
            JiraSync(trigger="schedule", projects="AMS", started_at=NOW - timedelta(minutes=1), finished_at=NOW, pulled=3),
        ])
        await db.commit()
    return client


async def test_summary_counts_today_only(seeded):
    body = (await seeded.get("/api/v1/dashboard/summary", params={"since": TODAY.isoformat()})).json()
    assert body["tickets"]["by_source_today"] == {"JIRA": 3, "ServiceNow": 1}
    assert body["tickets"]["by_stage"] == {"pending": 1, "triaged": 1, "awaiting_info": 1}  # historical left out


async def test_summary_agent_stats_queue_and_syncs(seeded, monkeypatch):
    monkeypatch.setattr("app.services.dashboard.settings.JIRA_SYNC_MINUTES", 1)
    monkeypatch.setattr("app.services.dashboard.settings.CONFLUENCE_SYNC_MINUTES", 0)
    body = (await seeded.get("/api/v1/dashboard/summary", params={"since": TODAY.isoformat()})).json()
    dq, triage = body["agents"]["data_quality"], body["agents"]["triage"]
    assert (dq["checked"], dq["model_used"], dq["by_verdict"]) == (2, 1, {"passed": 1, "needs_info": 1})
    assert dq["model_failed"] == 1
    assert (triage["checked"], triage["model_used"], triage["model_failed"]) == (2, 1, 1)  # yesterday's run left out
    assert body["review_queue"]["size"] == 1 and body["review_queue"]["p1_p2"] == 1
    assert body["review_queue"]["oldest_at"].startswith("2026-11-01T08:00")
    assert body["syncs"]["jira"]["state"] == "running" and body["syncs"]["jira"]["last_summary"] == "Pulled 3"
    assert body["syncs"]["confluence"]["state"] == "off"
    assert body["attention"] == 1  # J-2 is an open P2 whose first message is not sent


async def test_summary_rejects_bad_since(client):
    assert (await client.get("/api/v1/dashboard/summary", params={"since": "yesterday"})).status_code == 422
    assert (await client.get("/api/v1/dashboard/summary")).status_code == 200


async def test_summary_survives_a_triage_result_without_priority(seeded):
    async for db in app.dependency_overrides[get_db]():
        db.add(Ticket(id="J-9", source="JIRA", summary="s", status="new", pipeline_status="triaged", ingested_at=TODAY))
        db.add(AgentRun(ticket_id="J-9", agent="triage", verdict="uncertain", created_at=TODAY,
                        output={"ai": "failed", "priority": None, "needs_review": True}))
        await db.commit()
    assert (await seeded.get("/api/v1/dashboard/summary", params={"since": TODAY.isoformat()})).status_code == 200


async def test_agent_stats_count_tickets_not_runs(seeded):
    async for db in app.dependency_overrides[get_db]():
        at = TODAY + timedelta(minutes=9)  # the rules stage, stored before the model run of the same ticket
        db.add(AgentRun(ticket_id="J-2", agent="data_quality", verdict="uncertain", output={"stage": "rules"}, created_at=at))
        await db.commit()
    dq = (await seeded.get("/api/v1/dashboard/summary", params={"since": TODAY.isoformat()})).json()["agents"]["data_quality"]
    assert (dq["checked"], dq["by_verdict"]) == (2, {"passed": 1, "needs_info": 1})


async def test_trends_buckets_by_day(seeded):
    start = TODAY - timedelta(days=2)
    naive = TODAY.replace(tzinfo=None)
    async for db in app.dependency_overrides[get_db]():
        late = Ticket(id="J-7", source="JIRA", summary="s", status="new", pipeline_status="triaged",
                      opened_at=naive - timedelta(hours=20), ingested_at=TODAY)  # P1: 4 hours, never resolved
        fine = Ticket(id="J-8", source="Mailbox", summary="s", status="resolved", pipeline_status="reviewed",
                      opened_at=naive - timedelta(days=2), resolved_at=naive - timedelta(days=2) + timedelta(hours=1),
                      closed_at=naive - timedelta(days=1), ingested_at=TODAY)
        db.add_all([late, fine])
        await db.flush()
        runs = [AgentRun(ticket_id=t.id, agent="triage", verdict="P1", created_at=TODAY - timedelta(days=1), output={
            "ai": "used", "priority": 1, "rule": "r", "reason": "x", "stage": "model", "needs_review": False,
            "audit": {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 5},
        }) for t in (late, fine)]
        db.add_all(runs)
        await db.flush()
        db.add(Review(ticket_id="J-8", agent_run_id=runs[1].id, agent="triage", action="accepted", final_priority=1,
                      reviewer="Asha", created_at=TODAY))
        db.add(Review(ticket_id="J-8", agent_run_id=runs[1].id, agent="triage", action="accepted", final_priority=1,
                      reviewer="Asha", created_at=TODAY - timedelta(days=9)))  # before the period
        await db.commit()
    body = (await seeded.get("/api/v1/dashboard/trends", params={"since": start.isoformat(), "days": 3})).json()
    assert len(body["days"]) == 3 and body["days"][0].startswith(start.date().isoformat())
    # J-2 was opened on 1 Nov, outside the period; J-1 (pulled in yesterday evening) and J-3, J-4 have no open time
    assert body["tickets"] == {"JIRA": [0, 2, 2], "Mailbox": [1, 0, 0], "ServiceNow": [0, 0, 1]}
    assert body["tokens"] == {"triage": [0, 250, 0]}
    assert (body["tokens_in"], body["tokens_out"], body["model_calls"]) == (210, 40, 2)
    assert body["sla_breaches"] == {"P1": [0, 1, 0]}  # J-8 was resolved in time
    assert body["sla_open"] == {"breached": 2, "breach_likely": 0}  # J-7, and J-2 from the fixture
    assert body["reviews"] == {"Asha": 1}


async def test_trends_counts_every_model_call_of_a_resolution_run(seeded):
    async for db in app.dependency_overrides[get_db]():
        db.add(AgentRun(ticket_id="J-1", agent="resolution", verdict="answered", created_at=TODAY, output={
            "audit": [{"input_tokens": 100, "output_tokens": 20},
                      {"input_tokens": 50, "output_tokens": 10, "cache_read_tokens": 5}],
        }))  # Resolution asks the model several times and keeps one audit per call
        await db.commit()
    body = (await seeded.get("/api/v1/dashboard/trends", params={"since": TODAY.isoformat(), "days": 1})).json()
    assert body["tokens"] == {"resolution": [185]}
    assert (body["tokens_in"], body["tokens_out"], body["model_calls"]) == (155, 30, 2)


async def test_trends_rejects_bad_days(client):
    assert (await client.get("/api/v1/dashboard/trends", params={"days": 0})).status_code == 422
    assert (await client.get("/api/v1/dashboard/trends")).status_code == 200
