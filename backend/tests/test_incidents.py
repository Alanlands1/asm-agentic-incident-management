"""What needs attention now: open or declared storms, and P1/P2 tickets whose first message is not sent yet."""

import json
from datetime import UTC, datetime, timedelta

import httpx

from app.api.v1.endpoints import tickets
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.ticket import AgentRun, Review, Storm, Ticket
from app.services import atlassian, incidents, jira
from app.services.triage import sla
from app.services.triage.review import pending, review
from app.services.triage.run import run_triage
from app.services.triage.storms import declare
from tests.test_jira import OPEN_ISSUE, fake_jira  # noqa: F401
from tests.test_storms_sla import CHECKOUT, PEOPLE, T0, session, storm_of, ticket  # noqa: F401
from tests.test_triage import db  # noqa: F401

AT = datetime(2026, 10, 25, 21, 0)


def test_sent_message_leaves_the_count(db):  # noqa: F811
    run_triage(db)
    before = incidents.attention(db, AT)
    waiting = [i for i in before.items if i.ticket.id not in before.sent]
    assert "AMS-1215" in {i.ticket.id for i in waiting}
    count = incidents.attention_count(db, AT)
    assert count == len(before.storms) + len(waiting)

    sent = incidents.record_sent(db, db.get(Ticket, "AMS-1215"), "PayrollPro: salary file late.", "Priya Raman")
    assert (sent.ticket_id, sent.sent_by) == ("AMS-1215", "Priya Raman")
    after = incidents.attention(db, AT)
    assert after.sent["AMS-1215"].text == "PayrollPro: salary file late."
    assert incidents.attention_count(db, AT) == count - 1


def test_engineer_lowered_to_p3_is_not_listed(db):  # noqa: F811
    run_triage(db)
    review(db, db.get(Ticket, "AMS-1215"), "edited", "ravi@contoso.com", priority=3, reason_code="wrong_facts")
    assert "AMS-1215" not in {i.ticket.id for i in incidents.attention(db, AT).items}


def test_declared_storm_counts_closed_does_not(session):  # noqa: F811
    result = storm_of(session, [ticket(i, p, "OrderHub", CHECKOUT, minute=i) for i, p in enumerate(PEOPLE)])
    storm = result.storms[0]
    at = T0 + timedelta(minutes=30)
    assert [s.id for s in incidents.attention(session, at).storms] == [storm.id]
    declare(session, storm, "Priya Raman")
    session.commit()
    assert [s.status for s in incidents.attention(session, at).storms] == ["declared"]
    storm.status = "closed"
    session.commit()
    assert incidents.attention(session, at).storms == []


async def test_first_message_endpoint_validation(client):
    url = "/api/v1/incidents/tickets/{}/first-message"
    assert (await client.post(url.format("NOPE-1"), json={"text": "x", "sent_by": "Priya Raman"})).status_code == 404
    assert (await client.post(url.format("NOPE-1"), json={"text": "", "sent_by": "Priya Raman"})).status_code == 422
    body = (await client.get("/api/v1/incidents/attention")).json()
    assert body == {"storms": [], "p1_p2": [], "count": 0}


def test_storm_message_covers_its_linked_tickets(db, monkeypatch):  # noqa: F811
    run_triage(db)
    items = incidents.attention(db, AT).items[:2]
    assert len(items) == 2
    storm = Storm(issue_key="text", main_ticket_id=items[0].ticket.id, people=5, ticket_count=2,
                  opened_at=AT, last_ticket_at=AT, status="open")
    db.add(storm)
    db.flush()
    for i in items:
        i.ticket.storm_id = storm.id
    db.commit()
    monkeypatch.setattr(incidents.sla, "open_p1_p2", lambda s, at=None: [
        type(i)(**{**i.__dict__, "storm_id": storm.id}) for i in items
    ])
    incidents.record_sent(db, items[0].ticket, "Storm update", "Priya Raman")
    a = incidents.attention(db, AT)
    assert {i.ticket.id for i in a.items} <= set(a.sent)  # the linked ticket is covered by the storm's message
    assert a.count == 1  # only the storm itself


def test_agent_model_change_rechecks(monkeypatch):
    from app.services import data_quality
    from app.services.triage import run as triage_run
    t = Ticket(id="X-1", source="JIRA", summary="s", description="d")
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    before = (data_quality._input_hash(t, "d"), triage_run._input_hash(t, "d"))
    monkeypatch.setattr(settings, "TRIAGE_LLM_MODEL", "claude-haiku-5-5")
    monkeypatch.setattr(settings, "DQ_LLM_EFFORT", "max")
    after = (data_quality._input_hash(t, "d"), triage_run._input_hash(t, "d"))
    assert before[0] != after[0] and before[1] != after[1]


async def test_post_to_jira_comments_on_the_issue_then_records(client, fake_jira, monkeypatch):  # noqa: F811
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": None}])
    await client.post("/api/v1/jira/sync")
    posted = []

    def jira_site(request: httpx.Request) -> httpx.Response:
        posted.append((request.method, request.url.path, request.read()))
        return httpx.Response(201, json={"id": "10001"})

    fake = httpx.MockTransport(jira_site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    url = "/api/v1/incidents/tickets/AMS-7/first-message"
    body = {"text": "We are on it.\n\nNext update 10:30.", "sent_by": "Alan Lands"}

    monkeypatch.setattr(settings, "JIRA_WRITE_BACK", False)
    off = await client.post(url, json={**body, "post_to_jira": True})
    assert off.status_code == 502 and "switched off" in off.json()["detail"] and posted == []

    monkeypatch.setattr(settings, "JIRA_WRITE_BACK", True)
    sent = await client.post(url, json={**body, "post_to_jira": True})
    assert sent.status_code == 201 and sent.json()["sent_by"] == "Alan Lands"
    [(method, path, payload)] = posted
    assert (method, path) == ("POST", "/rest/api/3/issue/AMS-7/comment")
    assert b'"text":"We are on it."' in payload and b'"text":"Next update 10:30."' in payload

    assert (await client.post(url, json=body)).status_code == 201 and len(posted) == 1  # "Mark as sent" writes nothing to Jira


async def test_review_sets_the_jira_priority_and_a_reply_is_commented(client, fake_jira, monkeypatch):  # noqa: F811
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": None}])
    await client.post("/api/v1/jira/sync")
    written, answer = [], [httpx.Response(500)]

    def jira_site(request: httpx.Request) -> httpx.Response:
        written.append((request.method, request.url.path, request.read()))
        return answer[0]

    fake = httpx.MockTransport(jira_site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    monkeypatch.setattr(settings, "JIRA_WRITE_BACK", True)

    reply = {"author_email": "Alan Lands", "body": "Which screen fails?", "post_to_jira": True}
    assert (await client.post("/api/v1/tickets/AMS-8/comments", json=reply)).status_code == 502  # Jira refused: not stored
    assert (await client.get("/api/v1/tickets/AMS-8")).json()["comments"] == []
    answer[0] = httpx.Response(201, json={"id": "10001"})
    assert (await client.post("/api/v1/tickets/AMS-8/comments", json=reply)).status_code == 201
    assert written[-1][:2] == ("POST", "/rest/api/3/issue/AMS-8/comment") and b"Which screen fails?" in written[-1][2]

    async for s in app.dependency_overrides[get_db]():  # as if Triage had recommended P3 (the reporter asked for P2)
        (await s.get(Ticket, "AMS-8")).pipeline_status = "triaged"
        s.add(AgentRun(ticket_id="AMS-8", agent="triage", verdict="P3", output={"priority": 3}))
        await s.commit()
    url = "/api/v1/triage/tickets/AMS-8/review"
    change = {"action": "edited", "reviewer": "Alan Lands", "priority": 5, "reason_code": "other"}
    written.clear()
    answer[0] = httpx.Response(500)
    assert (await client.post(url, json=change)).status_code == 502  # Jira refused: not reviewed, can be tried again
    answer[0] = httpx.Response(204)
    assert (await client.post(url, json=change)).status_code == 201
    assert written[-1] == ("PUT", "/rest/api/3/issue/AMS-8", b'{"fields":{"priority":{"name":"Lowest"}}}') and len(written) == 2

    async def lowest(keys, since=None):  # the next pull brings the reviewed priority back from Jira
        return [{"key": "AMS-8", "fields": {**OPEN_ISSUE["fields"], "priority": {"name": "Lowest"}}}]

    monkeypatch.setattr(jira, "search_issues", lowest)
    await client.post("/api/v1/jira/sync")
    ticket = (await client.get("/api/v1/tickets/AMS-8")).json()
    assert (ticket["pipeline_status"], ticket["reported_priority"]) == ("reviewed", 2)  # what the reporter asked for is kept


async def test_the_system_warns_at_watch_breach_likely_and_breach(client, fake_jira, monkeypatch):  # noqa: F811
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": None}])
    await client.post("/api/v1/jira/sync")
    posted = []

    def jira_site(request: httpx.Request) -> httpx.Response:
        posted.append((request.url.path, request.read()))
        return httpx.Response(201, json={"id": "10001"})

    fake = httpx.MockTransport(jira_site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    monkeypatch.setattr(settings, "JIRA_WRITE_BACK", True)
    target = timedelta(hours=sla.config().targets[1])
    async for s in app.dependency_overrides[get_db]():
        t = await s.get(Ticket, "AMS-8")
        t.pipeline_status = "triaged"
        s.add(AgentRun(ticket_id="AMS-8", agent="triage", verdict="P1", output={"priority": 1}))
        for used, sent in ((0.1, 0), (0.55, 1), (0.7, 0), (0.85, 1), (0.9, 0), (1.3, 1), (2.6, 0)):  # watch, likely, breach
            t.opened_at = sla.now() - target * used
            await s.commit()
            assert await jira.send_sla_warnings(s) == sent, used
    assert [path for path, _ in posted] == ["/rest/api/3/issue/AMS-8/comment"] * 3
    assert b"Automatic SLA warning: this P1 ticket is due by" in posted[0][1] and b"(55% of the target is used)" in posted[0][1]
    assert b"breached its SLA at" in posted[2][1]
    copies = (await client.get("/api/v1/tickets/AMS-8")).json()["comments"]
    assert len(copies) == 3 and all(c["author_email"] == jira.SLA_BOT and not c["from_reporter"] for c in copies)
    await client.post("/api/v1/jira/sync")  # the sync keeps the clock the test set
    async for s in app.dependency_overrides[get_db]():
        assert await jira.send_sla_warnings(s) == 0


async def test_a_ticket_closed_in_jira_is_no_longer_worked_here(client, fake_jira, monkeypatch):  # noqa: F811
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": None}])
    await client.post("/api/v1/jira/sync")
    async for s in app.dependency_overrides[get_db]():
        (await s.get(Ticket, "AMS-8")).pipeline_status = "triaged"
        s.add(AgentRun(ticket_id="AMS-8", agent="triage", verdict="P1", output={"priority": 1, "needs_review": False}))
        await s.commit()
        assert [t.id for t, _ in await s.run_sync(pending)] == ["AMS-8"]
        assert [i.ticket.id for i in await s.run_sync(sla.open_p1_p2)] == ["AMS-8"]

    async def done(keys, since=None):  # moved to Done on the Jira board; this project sets no resolution date
        status = {"name": "Done", "statusCategory": {"key": "done"}}
        return [{"key": "AMS-8", "fields": {**OPEN_ISSUE["fields"], "status": status}}]

    monkeypatch.setattr(jira, "search_issues", done)
    await client.post("/api/v1/jira/sync")
    ticket = (await client.get("/api/v1/tickets/AMS-8")).json()  # noqa: F811
    assert (ticket["status"], ticket["source_status"], ticket["pipeline_status"]) == ("closed", "Done", "triaged")
    async for s in app.dependency_overrides[get_db]():
        assert await s.run_sync(pending) == [] and await s.run_sync(sla.open_p1_p2) == []
        assert await jira.send_sla_warnings(s) == 0


async def test_a_command_written_in_jira_is_answered_once(client, fake_jira, monkeypatch):  # noqa: F811
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": None}])
    await client.post("/api/v1/jira/sync")
    said = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "/ams DQ"}]}]}
    comments = {"AMS-8": [{"body": said}]}  # newest first, as Jira is asked to return them

    def jira_site(request: httpx.Request) -> httpx.Response:
        key = request.url.path.split("/")[5]
        if request.method == "POST":
            comments[key].insert(0, json.loads(request.read()))
        return httpx.Response(200, json={"comments": comments.get(key, [])})

    async def agents_ran():
        ran.append(1)

    ran = []
    fake = httpx.MockTransport(jira_site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    monkeypatch.setattr(settings, "JIRA_WRITE_BACK", True)
    monkeypatch.setattr(jira, "run_agents", agents_ran)
    async for s in app.dependency_overrides[get_db]():
        assert await jira.answer_commands(s) == 1 and ran == [1]
        assert await jira.answer_commands(s) == 0  # the answer is on the issue
    answer = jira.adf_text(comments["AMS-8"][0]["body"])
    assert answer.startswith("AMS agents on AMS-8. Waiting for the Data Quality agent.")
    assert "Data Quality: has not checked this ticket yet." in answer and "Triage" not in answer  # "/ams dq" asks for one agent

    sent = await client.post("/api/v1/tickets/AMS-8/agent-summary", json={"author_email": "Alan Lands"})  # the button
    assert sent.status_code == 201 and "Triage: has not checked" in sent.json()["body"] and len(comments["AMS-8"]) == 3
    copies = (await client.get("/api/v1/tickets/AMS-8")).json()["comments"]
    assert [c["author_email"] for c in copies] == [jira.COMMAND_BOT, "Alan Lands"]
    assert (await client.post("/api/v1/tickets/NOPE-1/agent-summary", json={"author_email": "Alan Lands"})).status_code == 404


async def test_a_person_runs_the_agents_on_one_ticket(client, fake_jira, monkeypatch):  # noqa: F811
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": None}])
    await client.post("/api/v1/jira/sync")
    run = "/api/v1/tickets/AMS-8/run-agents"

    assert (await client.post(run, json={"agent": "triage"})).status_code == 409  # Data Quality has not passed yet
    first = await client.post(run, json={})  # Data Quality alone: the rules miss details, so Triage does not follow
    assert first.status_code == 200 and first.json()["pipeline_status"] == "awaiting_info"

    monkeypatch.setattr(tickets, "check_ticket", lambda _, t: setattr(t, "pipeline_status", "dq_passed"))
    assert (await client.post(run, json={})).status_code == 200  # it passed: Triage follows
    assert (await client.post(run, json={"agent": "triage"})).status_code == 200  # Triage alone, again
    runs = [r["agent"] for r in (await client.get("/api/v1/tickets/AMS-8")).json()["agent_runs"]]
    assert runs.count("triage") == 2  # the rules alone cannot settle this ticket; with the model it would be triaged

    async for s in app.dependency_overrides[get_db]():
        (await s.get(Ticket, "AMS-8")).pipeline_status = "reviewed"
        await s.commit()
    assert (await client.post(run, json={})).status_code == 409  # a person decided: the agents leave it alone
    assert (await client.post("/api/v1/tickets/NOPE-1/run-agents", json={})).status_code == 404


def _doc(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def _triaged_p1(client):
    """AMS-8 (the reporter asked for High) pulled from Jira and triaged as P1."""
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": None}])
    await client.post("/api/v1/jira/sync")
    async for s in app.dependency_overrides[get_db]():
        (await s.get(Ticket, "AMS-8")).pipeline_status = "triaged"
        s.add(AgentRun(ticket_id="AMS-8", agent="triage", verdict="P1", output={"priority": 1, "needs_review": False}))
        await s.commit()


async def test_a_priority_set_in_jira_is_the_decision(client, fake_jira, monkeypatch):  # noqa: F811
    from sqlalchemy import func, select
    await _triaged_p1(client)
    await client.post("/api/v1/jira/sync")
    assert (await client.get("/api/v1/tickets/AMS-8")).json()["decided"] is None  # nothing changed in Jira: still waiting

    async def lowered(keys, since=None):
        return [{"key": "AMS-8", "fields": {**OPEN_ISSUE["fields"], "priority": {"name": "Medium"}}}]
    monkeypatch.setattr(jira, "search_issues", lowered)
    await client.post("/api/v1/jira/sync")
    await client.post("/api/v1/jira/sync")  # the same priority again is not a new decision
    ticket = (await client.get("/api/v1/tickets/AMS-8")).json()  # noqa: F811
    assert (ticket["pipeline_status"], ticket["reported_priority"]) == ("reviewed", 2)  # the reporter's own priority is kept
    decided = ticket["decided"]
    assert (decided["action"], decided["final_priority"], decided["reviewer"]) == ("edited", 3, jira.IN_JIRA)
    async for s in app.dependency_overrides[get_db]():
        assert await s.scalar(select(func.count()).select_from(Review)) == 1


async def test_agree_and_an_unknown_command_in_jira(client, fake_jira, monkeypatch):  # noqa: F811
    await _triaged_p1(client)
    comments = [{"body": _doc("/ams agree"), "author": {"displayName": "Lena Lead"}}]  # newest first
    priorities = []

    def jira_site(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            priorities.append(json.loads(request.read()))
        elif request.method == "POST":
            comments.insert(0, json.loads(request.read()))
        return httpx.Response(200, json={"comments": comments if "/AMS-8" in request.url.path else []})

    async def no_agents():
        pass

    fake = httpx.MockTransport(jira_site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    monkeypatch.setattr(settings, "JIRA_WRITE_BACK", True)
    monkeypatch.setattr(jira, "run_agents", no_agents)
    async for s in app.dependency_overrides[get_db]():
        assert await jira.answer_commands(s) == 1
    assert priorities == [{"fields": {"priority": {"name": "Highest"}}}]  # the recommended P1 replaces the reporter's High
    ticket = (await client.get("/api/v1/tickets/AMS-8")).json()  # noqa: F811
    decided = ticket["decided"]
    assert (ticket["pipeline_status"], decided["action"], decided["final_priority"], decided["reviewer"]) == (
        "reviewed", "accepted", 1, "Lena Lead")
    answer = jira.adf_text(comments[0]["body"])
    assert answer.startswith("AMS agents on AMS-8. The priority is decided")
    assert "Lena Lead agreed: the priority is now Highest, was High." in answer

    comments.insert(0, {"body": _doc("/ams help")})
    async for s in app.dependency_overrides[get_db]():
        assert await jira.answer_commands(s) == 1
        assert await jira.answer_commands(s) == 0
    assert "ams agree (accept the recommended priority)" in jira.adf_text(comments[0]["body"])


async def test_the_agents_say_their_verdict_on_the_issue(client, fake_jira, monkeypatch):  # noqa: F811
    await client.put("/api/v1/jira/projects", json=[{"key": "AMS", "name": "AMS Support", "team": None}])
    await client.post("/api/v1/jira/sync")
    sent = []

    def jira_site(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, request.url.path, json.loads(request.read())))
        return httpx.Response(201, json={})

    fake = httpx.MockTransport(jira_site)
    monkeypatch.setattr(atlassian, "client", lambda: httpx.AsyncClient(base_url="https://jira.test", transport=fake))
    before = datetime.now(UTC) - timedelta(minutes=1)
    async for s in app.dependency_overrides[get_db]():
        (await s.get(Ticket, "AMS-8")).pipeline_status = "awaiting_info"
        said = {"stage": "rules", "reason": "The description is too short to act on", "missing": ["what is not working"]}
        s.add(AgentRun(ticket_id="AMS-8", agent="data_quality", verdict="needs_info", output=said))
        await s.commit()
        assert await jira.announce(s, before) == 0 and sent == []  # writing to Jira is off
        monkeypatch.setattr(settings, "JIRA_WRITE_BACK", True)
        assert await jira.announce(s, before) == 1
        assert await jira.announce(s, datetime.now(UTC) + timedelta(minutes=1)) == 0  # nothing new decided: nothing said again
    assert [(method, path) for method, path, _ in sent] == [
        ("POST", "/rest/api/3/issue/AMS-8/comment"), ("PUT", "/rest/api/3/issue/AMS-8")]
    text = jira.adf_text(sent[0][2]["body"])
    assert text.startswith("AMS agents on AMS-8. Next: the reporter gives the missing details.")
    assert "Missing: what is not working." in text and "Please add the missing details to this issue" in text
    labels = sent[1][2]["update"]["labels"]
    assert {"add": "ams-needs-info"} in labels and {"remove": "ams-p1"} in labels and {"remove": "ams-needs-info"} not in labels
    copies = (await client.get("/api/v1/tickets/AMS-8")).json()["comments"]
    assert [(c["author_email"], c["body"].strip()) for c in copies] == [(jira.AGENTS_BOT, text.strip())]
