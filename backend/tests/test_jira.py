"""Jira pull: issue mapping and the sync endpoints, with Jira itself faked."""

import pytest
from pydantic import SecretStr

from app.services import jira

ISSUE = {
    "key": "AMS-7",
    "fields": {
        "summary": "Payroll export fails",
        "description": {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Export stops at 40%."}]},
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Since Monday"}, {"type": "hardBreak"}, {"type": "text", "text": "for all users."},
            ]},
        ]},
        "priority": {"name": "High"},
        "status": {"name": "Done", "statusCategory": {"key": "done"}},
        "reporter": {"displayName": "Jane Doe"},
        "components": [{"name": "PayrollPro"}],
        "created": "2026-11-01T09:30:00.000-0500",
        "resolutiondate": "2026-11-02T10:00:00.000+0000",
        "project": {"key": "AMS", "name": "AMS Support"},
    },
}


def test_adf_text_keeps_paragraphs_and_breaks():
    assert jira.adf_text(ISSUE["fields"]["description"]).strip() == "Export stops at 40%.\nSince Monday\nfor all users."
    assert jira.adf_text(None) == ""


def test_map_issue():
    row = jira.map_issue(ISSUE, None)
    assert row["ticket_id"] == "AMS-7"
    assert row["priority"] == "2 - High"
    assert row["service"] == "PayrollPro"
    assert row["assignment_group"] == "AMS Support"  # no team picked: project name
    assert row["opened_at"].isoformat() == "2026-11-01T14:30:00"  # naive UTC
    assert row["closed_at"].isoformat() == "2026-11-02T10:00:00"
    assert jira.map_issue(ISSUE, "AMS-Finance")["assignment_group"] == "AMS-Finance"
    fields = {**ISSUE["fields"], "status": {"statusCategory": {"key": "new"}}, "components": [], "priority": None}
    open_issue = {"key": "AMS-8", "fields": fields}
    row = jira.map_issue(open_issue, None)
    assert row["closed_at"] is None and row["service"] is None and row["priority"] is None


OPEN_ISSUE = {"key": "AMS-8", "fields": {**ISSUE["fields"], "status": {"name": "Backlog", "statusCategory": {"key": "new"}},
                                         "resolutiondate": None}}


@pytest.fixture
def fake_jira(monkeypatch):
    calls = {"search": [], "agents": 0}

    async def search(keys, since=None):
        assert keys == ["AMS"]
        calls["search"].append(since)
        return [ISSUE, OPEN_ISSUE]

    def agents():
        calls["agents"] += 1
    async def replies(issue, c=None):
        return []
    monkeypatch.setattr(jira, "search_issues", search)
    monkeypatch.setattr(jira, "start_agents", agents)
    monkeypatch.setattr(jira, "reporter_replies", replies)
    # A made-up site, so the sync never depends on backend/.env and never calls the real one.
    monkeypatch.setattr(jira.settings, "ATLASSIAN_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setattr(jira.settings, "ATLASSIAN_EMAIL", "bot@example.com")
    monkeypatch.setattr(jira.settings, "ATLASSIAN_API_TOKEN", SecretStr("x"))
    monkeypatch.setattr(jira.settings, "PII_MASKING_ENABLED", False)
    return calls


async def test_sync_without_projects_is_recorded_as_failed(client):
    r = await client.post("/api/v1/jira/sync")
    assert r.status_code == 200
    assert r.json()["error"].startswith("No projects selected")


async def test_sync_creates_then_updates(client, fake_jira):
    r = await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": "AMS-Finance"}])
    assert r.status_code == 200
    first = (await client.post("/api/v1/jira/sync")).json()
    assert (first["pulled"], first["created"], first["updated"], first["queued"], first["error"]) == (2, 2, 0, 1, None)
    assert fake_jira["agents"] == 1  # only the open ticket goes to the agents, closed one is history
    second = (await client.post("/api/v1/jira/sync")).json()
    assert (second["created"], second["updated"], second["queued"]) == (0, 2, 0)
    assert fake_jira["agents"] == 1 and fake_jira["search"] == [None, None]  # manual syncs pull everything
    history = (await client.get("/api/v1/jira/syncs")).json()
    assert [h["id"] for h in history] == [second["id"], first["id"]]
    ticket = (await client.get("/api/v1/servicenow/tickets/AMS-7")).json()
    assert ticket["assignment_group"] == "AMS-Finance" and ticket["priority"] == "2 - High"


async def test_project_key_is_validated(client):
    r = await client.put("/api/v1/jira/projects", json=[{"key": "ams) OR 1=1", "name": "x"}])
    assert r.status_code == 422


def test_map_ticket_for_the_agents():
    row = jira.map_ticket(OPEN_ISSUE, "AMS-Finance")
    assert (row["id"], row["source"], row["status"], row["reported_priority"]) == ("AMS-8", "JIRA", "new", 2)
    assert row["application"] == "PayrollPro" and row["assignment_group"] == "AMS-Finance"
    assert row["closed_at"] is None and "Jane Doe" not in str(row["raw"])
    assert jira.map_ticket(ISSUE, None)["status"] == "closed"


async def test_tickets_reach_the_agents_table(client, fake_jira):
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support"}])
    await client.post("/api/v1/jira/sync")
    from app.db.session import get_db
    from app.main import app
    from app.models.ticket import Ticket
    async for db in app.dependency_overrides[get_db]():
        assert (await db.get(Ticket, "AMS-8")).pipeline_status == "pending"
        assert (await db.get(Ticket, "AMS-7")).pipeline_status == "historical"


async def test_edited_issue_awaiting_info_is_checked_again(client, fake_jira, monkeypatch):
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support"}])
    await client.post("/api/v1/jira/sync")
    from app.db.session import get_db
    from app.main import app
    from app.models.ticket import Ticket
    async for db in app.dependency_overrides[get_db]():
        (await db.get(Ticket, "AMS-8")).pipeline_status = "awaiting_info"
        await db.commit()
    assert (await client.post("/api/v1/jira/sync")).json()["queued"] == 0  # nothing edited: still waiting

    async def edited(keys, since=None):
        return [{**OPEN_ISSUE, "fields": {**OPEN_ISSUE["fields"], "summary": "Payroll export fails at step 3"}}]
    monkeypatch.setattr(jira, "search_issues", edited)
    assert (await client.post("/api/v1/jira/sync")).json()["queued"] == 1
    assert fake_jira["agents"] == 2
    async for db in app.dependency_overrides[get_db]():
        assert (await db.get(Ticket, "AMS-8")).pipeline_status == "pending"


async def test_reporter_comment_in_jira_sends_awaiting_info_back(client, fake_jira, monkeypatch):
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support"}])
    await client.post("/api/v1/jira/sync")
    from sqlalchemy import select

    from app.db.session import get_db
    from app.main import app
    from app.models.ticket import Comment, Ticket

    async def waiting():
        async for db in app.dependency_overrides[get_db]():
            (await db.get(Ticket, "AMS-8")).pipeline_status = "awaiting_info"
            await db.commit()

    async def replies(issue, c=None):
        assert issue["key"] == "AMS-8"  # only tickets awaiting information are asked about
        return ["It fails at step 3 with error E42."]
    monkeypatch.setattr(jira, "reporter_replies", replies)
    await waiting()
    assert (await client.post("/api/v1/jira/sync")).json()["queued"] == 1
    await waiting()
    assert (await client.post("/api/v1/jira/sync")).json()["queued"] == 0  # the same reply is not new the second time
    async for db in app.dependency_overrides[get_db]():
        stored = (await db.scalars(select(Comment).where(Comment.ticket_id == "AMS-8"))).all()
        assert [(c.body, c.from_reporter) for c in stored] == [("It fails at step 3 with error E42.", True)]


async def test_triaged_issue_leaves_the_backlog(client, fake_jira, monkeypatch):
    import httpx

    from app.db.session import get_db
    from app.main import app
    from app.models.ticket import Ticket
    from app.services import atlassian
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support"}])
    await client.post("/api/v1/jira/sync")
    posted, history = [], []  # history: the status changes Jira has seen on AMS-8

    def jira_site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/issue/AMS-8":  # the closed AMS-7 is not touched
            return httpx.Response(200, json={"changelog": {"histories": history}})
        assert request.url.path == "/rest/api/3/issue/AMS-8/transitions"
        if request.method == "POST":
            posted.append(request.read())
            return httpx.Response(204)
        steps = [{"id": "31", "to": {"name": "In Progress"}}, {"id": "21", "to": {"name": "Selected for development"}}]
        return httpx.Response(200, json={"transitions": steps})
    fake = httpx.MockTransport(jira_site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    async for db in app.dependency_overrides[get_db]():
        assert await jira.move_triaged(db) == 0  # writing to Jira is off
        monkeypatch.setattr(jira.settings, "JIRA_WRITE_BACK", True)
        assert await jira.move_triaged(db) == 0  # not triaged yet
        (await db.get(Ticket, "AMS-8")).pipeline_status = "triaged"
        await db.commit()
        assert await jira.move_triaged(db) == 1 and posted == [b'{"transition":{"id":"21"}}']
        ticket = await db.get(Ticket, "AMS-8")
        assert (ticket.status, ticket.source_status) == ("in_progress", "Selected for development")
        assert await jira.move_triaged(db) == 0 and len(posted) == 1  # out of the backlog: not moved again
        ticket.status = "new"  # a person dragged it back to the backlog, as the next sync brings it
        history.append({"items": [{"field": "status"}]})
        await db.commit()
        assert await jira.move_triaged(db) == 0 and len(posted) == 1  # the status set in Jira is final


def test_a_comment_to_the_agents_is_not_a_reporter_reply():
    assert jira._to_agents("/ams help") and jira._to_agents("AMS dq") and jira._to_agents("/AMS agree")
    assert not jira._to_agents("AMS team, it fails at step 3")


async def test_system_comments_are_posted_in_a_panel(monkeypatch):
    sent = {}

    async def call(c, method, url, **kw):
        sent.update(kw["json"])

    monkeypatch.setattr(jira.settings, "JIRA_WRITE_BACK", True)
    monkeypatch.setattr(jira.atlassian, "call", call)
    await jira.post_comment("AMS-1", "AMS agents on AMS-1. Hello\n\nMore", c=object())
    (panel,) = sent["body"]["content"]
    assert panel["type"] == "panel" and len(panel["content"]) == 3
    assert jira.adf_text(sent["body"]).strip() == "AMS agents on AMS-1. Hello\n\nMore"  # an answer is still found by its text


def test_sla_warnings_follow_the_console_states():
    levels = jira._levels()
    assert levels[-1] == 100 and levels == tuple(sorted(levels))
    assert jira._step(levels[0] - 1, levels) == 0
    assert jira._step(levels[1], levels) == levels[1]
    assert jira._step(595, levels) == 100


async def test_scheduled_sync_pulls_only_recent_changes(client, fake_jira):
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support"}])
    await client.post("/api/v1/jira/sync")
    from app.db.session import get_db
    from app.main import app
    async for db in app.dependency_overrides[get_db]():
        await jira.run_sync(db, "schedule")
    assert fake_jira["search"][0] is None
    assert 2 <= fake_jira["search"][1] <= 4  # minutes since the last good sync, plus overlap


async def test_agents_run_off_the_event_loop_thread(monkeypatch):
    import threading
    seen = []
    monkeypatch.setattr(jira.settings, "DATABASE_URL", "sqlite+aiosqlite://")
    monkeypatch.setattr(jira, "run_data_quality", lambda db: seen.append(("dq", threading.current_thread().name)))
    monkeypatch.setattr(jira, "run_triage", lambda db: seen.append(("triage", threading.current_thread().name)))
    await jira.run_agents()
    assert [s[0] for s in seen] == ["dq", "triage"]
    assert all(name != threading.current_thread().name for _, name in seen)  # the API's loop stays free
