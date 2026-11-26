"""The engineer's answer to a suggested fix, the fix loop, the closure note and sending it to Jira."""

import httpx
import pytest
from sqlalchemy import select

from app.models.ticket import AgentRun, Comment, PipelineStatus, Review, Ticket
from app.services import fix
from tests.test_triage import db  # noqa: F401  (fixture: every open ticket as if Data Quality had passed it)

FIX = {"root_cause": "The posting batch rejected the debit file.", "steps": ["1. Check the posting log.", "2. Re-run posting."],
       "references": ["KB-PAY-001"]}


def _suggest(session, ticket_id="AMS-1209", verdict="resolved", output=FIX) -> AgentRun:
    """A reviewed ticket with a suggested fix from Resolution."""
    run = AgentRun(ticket_id=ticket_id, agent="resolution", verdict=verdict, output=output)
    session.add(run)
    session.get(Ticket, ticket_id).pipeline_status = PipelineStatus.REVIEWED
    session.commit()
    return run


def test_worked_confirms_the_fix_and_drafts_the_closure_note(db):  # noqa: F811
    run = _suggest(db)
    ticket = db.get(Ticket, "AMS-1209")
    ticket.resolution_notes = None
    fix.record(db, ticket, run.id, "worked", "ravi@contoso.com")
    assert ticket.pipeline_status == PipelineStatus.FIX_CONFIRMED
    assert ticket.resolution_notes.splitlines() == [
        "Cause: The posting batch rejected the debit file.", "Fix: followed the suggested fix (KB-PAY-001):",
        "1. Check the posting log.", "2. Re-run posting.", "Checked: [engineer to add: check]",
    ]
    assert fix.answers(db, ticket.id)[run.id].action == "worked"


def test_partly_needs_what_changed_and_keeps_notes_already_written(db):  # noqa: F811
    run = _suggest(db)
    ticket = db.get(Ticket, "AMS-1209")
    with pytest.raises(fix.OutcomeError):
        fix.record(db, ticket, run.id, "partly", "ravi@contoso.com", "  ")
    ticket.resolution_notes = None
    fix.record(db, ticket, run.id, "partly", "ravi@contoso.com", "Re-generated the file first")
    assert "Changed from the suggested fix: Re-generated the file first" in ticket.resolution_notes
    ticket.resolution_notes = "My own notes"
    fix.record(db, ticket, run.id, "worked", "ravi@contoso.com")  # changing the answer keeps the note
    assert ticket.resolution_notes == "My own notes"


def test_wrong_asks_again_and_three_wrong_fixes_wait_for_the_lead(db):  # noqa: F811
    ticket = db.get(Ticket, "AMS-1209")
    with pytest.raises(fix.OutcomeError):
        fix.record(db, ticket, _suggest(db).id, "wrong", "ravi@contoso.com")  # what happened is needed
    for n in range(1, 4):
        run = _suggest(db) if n > 1 else fix.last_run(ticket, "resolution")
        fix.record(db, ticket, run.id, "wrong", "ravi@contoso.com", f"Failed again, try {n}")
        db.commit()
        db.refresh(ticket)
        assert ticket.pipeline_status == (PipelineStatus.NEEDS_LEAD if n == 3 else PipelineStatus.REVIEWED)
    with pytest.raises(fix.NotOpen):
        fix.record(db, ticket, run.id, "wrong", "ravi@contoso.com", "And again")  # the lead looks now
    fix.record(db, ticket, run.id, "worked", "ravi@contoso.com")  # fixed with the lead: the closure note still opens
    assert ticket.pipeline_status == PipelineStatus.FIX_CONFIRMED

    runs = [r for r in ticket.agent_runs if r.agent == "resolution"]
    text = fix.tried(runs, fix.answers(db, ticket.id))
    assert text.startswith("Fixes already tried:\nFix v1 did not work.")
    assert "Step 1: Check the posting log." in text and "What happened, from the engineer: Failed again, try 1" in text
    assert "Fix v4" not in text  # the one that worked is not listed


def test_only_the_latest_fix_of_an_open_ticket_can_be_answered(db):  # noqa: F811
    old, new = _suggest(db), _suggest(db)
    ticket = db.get(Ticket, "AMS-1209")
    with pytest.raises(fix.NotOpen):
        fix.record(db, ticket, old.id, "worked", "ravi@contoso.com")
    ticket.pipeline_status = PipelineStatus.TRIAGED
    with pytest.raises(fix.NotOpen):
        fix.record(db, ticket, new.id, "worked", "ravi@contoso.com")


def test_with_no_fix_suggested_the_engineer_says_what_they_did(db):  # noqa: F811
    run = _suggest(db, verdict="no_match", output={"notes": "Escalate to the payments team."})
    ticket = db.get(Ticket, "AMS-1209")
    ticket.resolution_notes = None
    for outcome in ("worked", "wrong"):
        with pytest.raises(fix.OutcomeError):
            fix.record(db, ticket, run.id, outcome, "ravi@contoso.com", "Restarted the gateway")
    fix.record(db, ticket, run.id, "partly", "ravi@contoso.com", "Restarted the gateway")
    assert ticket.resolution_notes.splitlines() == [
        "Cause: [engineer to add: cause]", "Fix: Restarted the gateway", "Checked: [engineer to add: check]",
    ]


async def _seed(client, ticket_id="AMS-1209"):
    from app.db.session import get_db
    from app.main import app

    await client.post("/api/v1/ingest")
    async for session in app.dependency_overrides[get_db]():
        session.add(AgentRun(ticket_id=ticket_id, agent="resolution", verdict="resolved", output=FIX))
        ticket = await session.get(Ticket, ticket_id)
        ticket.pipeline_status, ticket.resolution_notes = PipelineStatus.REVIEWED, None
        await session.commit()
    detail = (await client.get(f"/api/v1/tickets/{ticket_id}")).json()
    return next(r["id"] for r in detail["agent_runs"] if r["agent"] == "resolution")


async def test_a_wrong_fix_starts_resolution_for_that_ticket(client, monkeypatch):
    from app.services import jira

    started = []
    monkeypatch.setattr(jira, "start_resolution", lambda ticket_id=None: started.append(ticket_id))
    run_id = await _seed(client)
    body = {"agent_run_id": run_id, "outcome": "wrong", "reviewer": "ravi@contoso.com"}
    assert (await client.post("/api/v1/tickets/AMS-1209/fix-outcome", json=body)).status_code == 422  # no note
    r = await client.post("/api/v1/tickets/AMS-1209/fix-outcome", json={**body, "note": "The re-run failed again"})
    assert r.status_code == 200 and r.json()["pipeline_status"] == "reviewed"
    assert started == ["AMS-1209"]
    answers = (await client.get("/api/v1/tickets/AMS-1209")).json()["fix_outcomes"]
    assert [(a["action"], a["note"]) for a in answers] == [("wrong", "The re-run failed again")]


async def test_closure_note_opens_when_the_fix_worked_and_is_checked_on_every_save(client):
    run_id = await _seed(client)
    note = {"text": "Cause: the batch rejected the file. Fix: re-ran posting. Checked: all four deals show paid."}
    assert (await client.put("/api/v1/tickets/AMS-1209/closure-note", json=note)).status_code == 409  # not confirmed yet

    body = {"agent_run_id": run_id, "outcome": "worked", "reviewer": "ravi@contoso.com"}
    assert (await client.post("/api/v1/tickets/AMS-1209/fix-outcome", json=body)).json()["pipeline_status"] == "fix_confirmed"
    detail = (await client.get("/api/v1/tickets/AMS-1209")).json()
    assert "[engineer to add: check]" in detail["resolution_notes"]
    assert [r["agent"] for r in detail["agent_runs"]].count("closure_quality") == 1  # checked as soon as it opened

    assert (await client.put("/api/v1/tickets/AMS-1209/closure-note", json={"text": " "})).status_code == 422
    assert (await client.put("/api/v1/tickets/AMS-1209/closure-note", json=note)).status_code == 200
    detail = (await client.get("/api/v1/tickets/AMS-1209")).json()
    assert detail["resolution_notes"] == note["text"]
    assert [r["agent"] for r in detail["agent_runs"]].count("closure_quality") == 2


async def test_send_posts_the_closure_note_and_closes_the_issue(client, monkeypatch):
    from app.services import atlassian, jira

    monkeypatch.setattr(jira.settings, "LEAD_REVIEW", "never")  # Send itself; the lead's review has tests of its own

    run_id = await _seed(client)
    body = {"agent_run_id": run_id, "outcome": "worked", "reviewer": "ravi@contoso.com"}
    await client.post("/api/v1/tickets/AMS-1209/fix-outcome", json=body)
    send = {"author_email": "ravi@contoso.com"}
    r = await client.post("/api/v1/tickets/AMS-1209/close", json=send)
    assert r.status_code == 409 and "engineer to add" in r.json()["detail"]  # the draft still has a gap

    note = "Cause: the batch rejected the file. Fix: re-ran posting. Checked: all four deals show paid."
    await client.put("/api/v1/tickets/AMS-1209/closure-note", json={"text": note})
    assert (await client.post("/api/v1/tickets/AMS-1209/close", json=send)).status_code == 502  # writing to Jira is off

    calls = []

    def jira_site(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/transitions") and request.method == "GET":
            steps = [{"id": "11", "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}},
                     {"id": "41", "to": {"name": "Done", "statusCategory": {"key": "done"}}}]
            return httpx.Response(200, json={"transitions": steps})
        return httpx.Response(204 if request.url.path.endswith("/transitions") else 201, json={})

    fake = httpx.MockTransport(jira_site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    monkeypatch.setattr(jira.settings, "JIRA_WRITE_BACK", True)
    from app.db.session import get_db
    from app.main import app

    async for session in app.dependency_overrides[get_db]():  # a person decided P3 for the reporter's P1
        triage = AgentRun(ticket_id="AMS-1209", agent="triage", verdict="P3", output={"priority": 3})
        session.add(triage)
        await session.flush()
        session.add(Review(ticket_id="AMS-1209", agent_run_id=triage.id, agent="triage", action="accepted", final_priority=3,
                           reviewer="ravi@contoso.com"))
        await session.commit()
    learning = []
    monkeypatch.setattr(jira, "start_knowledge", lambda: learning.append(True))
    r = await client.post("/api/v1/tickets/AMS-1209/close", json=send)
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert learning == [True]  # Knowledge Builder starts at once, not on the next sync
    assert calls == [("GET", "/rest/api/3/issue/AMS-1209/transitions"), ("PUT", "/rest/api/3/issue/AMS-1209"),  # the decided P3
                     ("POST", "/rest/api/3/issue/AMS-1209/comment"),
                     ("POST", "/rest/api/3/issue/AMS-1209/transitions")]
    detail = (await client.get("/api/v1/tickets/AMS-1209")).json()
    assert (detail["source_status"], detail["closed_at"] is not None) == ("Done", True)
    assert detail["comments"][-1]["body"] == note
    assert (await client.post("/api/v1/tickets/AMS-1209/close", json=send)).status_code == 409  # closed once


async def test_an_issue_with_no_way_to_done_gets_no_comment(monkeypatch):
    from app.services import atlassian, jira

    posted = []

    async def call(c, method, url, **kw):
        posted.append((method, url))
        return {"transitions": [{"id": "11", "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}}]}

    monkeypatch.setattr(jira.settings, "JIRA_WRITE_BACK", True)
    monkeypatch.setattr(atlassian, "call", call)
    with pytest.raises(atlassian.AtlassianError):
        await jira.close_issue("AMS-1", "Closure note", c=object())
    assert posted == [("GET", "/rest/api/3/issue/AMS-1/transitions")]


def test_reviews_of_fixes_do_not_count_as_priority_decisions(db):  # noqa: F811
    run = _suggest(db)
    fix.record(db, db.get(Ticket, "AMS-1209"), run.id, "worked", "ravi@contoso.com")
    db.commit()
    assert db.scalars(select(Review).where(Review.agent == "triage", Review.ticket_id == "AMS-1209")).all() == []
    assert db.scalars(select(Comment).where(Comment.ticket_id == "AMS-1209")).all() == []  # nothing said anywhere


def test_parts_left_to_fill_in_count_as_missing():
    from app.services.closure.run import notes_for

    notes = "Cause: [engineer to add: cause]\nFix: restarted it\nChecked: [engineer to add: check]"
    ticket = Ticket(id="T-1", resolution_notes=notes)
    ticket.agent_runs = []
    assert notes_for(ticket)[0] == "Cause: \nFix: restarted it\nChecked:"


async def test_with_write_back_on_the_system_writes_nothing_on_its_own(monkeypatch):
    """Design D8: comments, labels, status moves and priorities only with JIRA_AGENT_WRITES; nothing reaches Jira here."""
    from datetime import UTC, datetime

    from app.services import atlassian, jira

    def no_jira():
        raise AssertionError("the system wrote to Jira on its own")

    monkeypatch.setattr(atlassian, "client", no_jira)
    monkeypatch.setattr(jira.settings, "JIRA_WRITE_BACK", True)
    now = datetime.now(UTC)
    assert not jira.agent_writes()
    for told in (await jira.announce(None, now), await jira.announce_resolution(None, now),
                 await jira.announce_closure(None, now), await jira.move_triaged(None)):
        assert told == 0


async def test_a_ticket_from_another_source_is_closed_here_without_jira(client, monkeypatch):
    from app.db.session import get_db
    from app.main import app
    from app.services import jira

    monkeypatch.setattr(jira.settings, "LEAD_REVIEW", "never")

    async def no_jira(*args, **kwargs):
        raise AssertionError("a mailbox ticket is never written to Jira")

    monkeypatch.setattr(jira, "close_issue", no_jira)
    run_id = await _seed(client)
    async for session in app.dependency_overrides[get_db]():
        (await session.get(Ticket, "AMS-1209")).source = "Mailbox"
        await session.commit()
    await client.post("/api/v1/tickets/AMS-1209/fix-outcome",
                      json={"agent_run_id": run_id, "outcome": "worked", "reviewer": "ravi@contoso.com"})
    note = "Cause: the batch rejected the file. Fix: re-ran posting. Checked: all four deals show paid."
    await client.put("/api/v1/tickets/AMS-1209/closure-note", json={"text": note})
    r = await client.post("/api/v1/tickets/AMS-1209/close", json={"author_email": "ravi@contoso.com"})
    assert r.status_code == 200 and r.json()["status"] == "closed"
    detail = (await client.get("/api/v1/tickets/AMS-1209")).json()
    assert detail["closed_at"] and detail["source_status"] == "Closed"
