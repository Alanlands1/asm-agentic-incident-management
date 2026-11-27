"""Demo reset with a saved baseline: the console's tables and the Jira issues go back to what was saved."""

import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import API_DIR, Settings, settings
from app.db.session import Base, get_db
from app.main import app
from app.models.incident import FirstMessage
from app.models.jira import JiraProject, JiraSync
from app.models.knowledge import ResolvedCase
from app.models.servicenow import ServiceNowTicket
from app.models.ticket import AgentRun, Comment, Feedback, PipelineStatus, Review, Storm, Ticket
from app.services import atlassian, baseline, jira, reset

T0 = datetime(2026, 11, 20, 9, 0)
SHIFT = timedelta(hours=2)
REAL = API_DIR / ".demo-baseline" / "2026-11-27"


def _seed(s: Session) -> None:
    """One open ticket in a declared storm and one closed ticket, each with rows in the tables around it."""
    s.add(Storm(id=1, application="OrderHub", issue_key="rule:checkout_failing", main_ticket_id="T-OPEN", people=2,
                ticket_count=2, opened_at=T0, last_ticket_at=T0 + timedelta(minutes=5), status="declared",
                declared_by="Priya Raman", declared_at=T0.replace(tzinfo=UTC) + timedelta(minutes=10)))
    s.add(Ticket(id="T-OPEN", source="JIRA", summary="Checkout fails", status="new", reported_priority=1, storm_id=1,
                 pipeline_status=PipelineStatus.TRIAGED, opened_at=T0, raw={"priority": "Highest"}))
    s.add(Ticket(id="T-CLOSED", source="Mailbox", summary="Payslip missing", status="closed", reported_priority=3,
                 pipeline_status=PipelineStatus.HISTORICAL, opened_at=T0 - timedelta(days=2), resolved_at=T0 - timedelta(days=1),
                 closed_at=T0 - timedelta(days=1), resolution_notes="Re-ran the payslip job."))
    for i in ("T-OPEN", "T-CLOSED"):
        s.add(ServiceNowTicket(ticket_id=i, short_description=i, opened_at=T0, dq_flag=False))
    s.flush()
    s.add(AgentRun(id=1, ticket_id="T-OPEN", agent="triage", verdict="P1", output={"priority": 1}))
    s.add(AgentRun(id=2, ticket_id="T-CLOSED", agent="closure_quality", verdict="passed", output={"score": 6}))
    s.flush()
    s.add(Review(ticket_id="T-OPEN", agent_run_id=1, agent="triage", action="accepted", final_priority=1, reviewer="Priya Raman"))
    s.add(Feedback(ticket_id="T-OPEN", agent_run_id=1, agent="triage", stars=5, reason="Right", reviewer="Priya Raman"))
    s.add(Comment(ticket_id="T-OPEN", author_email="asha@contoso.com", from_reporter=True, body="Still failing."))
    s.add(FirstMessage(ticket_id="T-OPEN", storm_id=1, text="OrderHub: checkout is failing.", sent_by="Priya Raman"))
    s.add(ResolvedCase(ticket_id="T-CLOSED", summary="Payslip missing", description="", notes="Re-ran the payslip job.",
                       match_status="gap", closed_at=T0 - timedelta(days=1)))
    s.commit()


def _change(s: Session) -> None:
    """What a demo leaves behind after the baseline."""
    ticket = s.get(Ticket, "T-OPEN")
    ticket.reported_priority, ticket.pipeline_status, ticket.storm_id = 4, PipelineStatus.REVIEWED, None
    s.execute(delete(AgentRun).where(AgentRun.ticket_id == "T-CLOSED"))
    s.execute(delete(ServiceNowTicket).where(ServiceNowTicket.ticket_id == "T-CLOSED"))
    s.add(FirstMessage(ticket_id="T-OPEN", text="Second update.", sent_by="Priya Raman"))
    s.add(Ticket(id="T-NEW", source="JIRA", summary="New since the baseline", status="new", opened_at=T0))
    s.add(AgentRun(ticket_id="T-NEW", agent="data_quality", verdict="passed", output={}))
    s.add(Storm(id=2, issue_key="cross:login", main_ticket_id="T-NEW", people=1, ticket_count=1, opened_at=T0,
                last_ticket_at=T0, status="open"))
    s.commit()


def _rows(s: Session) -> dict[str, list[dict]]:
    s.expire_all()
    return {name: sorted((dict(r) for r in s.execute(select(Base.metadata.tables[name])).mappings()), key=str)
            for name in baseline.TABLES}


def _one(rows: dict, table: str, **where) -> dict:
    return next(r for r in rows[table] if all(r[k] == v for k, v in where.items()))


def _markers(s: Session) -> int:
    return s.scalar(select(func.count()).select_from(JiraSync).where(JiraSync.trigger == "reset"))


async def test_reset_puts_the_tables_back_and_moves_open_tickets_in_time(client, monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(jira, "start_agents", lambda: started.append(1))
    assert (await client.post("/api/v1/demo/reset?dry_run=true")).status_code == 409  # a dry run needs a baseline
    async for s in app.dependency_overrides[get_db]():
        await s.run_sync(_seed)
        saved = await s.run_sync(lambda d: baseline.save_baseline(d, [], tmp_path))
        assert "users" not in saved["tables"] and "user_sessions" not in saved["tables"]
        with pytest.raises(FileExistsError):  # a saved baseline is never overwritten
            await s.run_sync(lambda d: baseline.save_baseline(d, [], tmp_path))
        before = await s.run_sync(_rows)
        await s.run_sync(_change)
        changed = await s.run_sync(_rows)
        assert changed != before
    taken_at = datetime.fromisoformat(saved["taken_at"])
    monkeypatch.setattr(settings, "DEMO_BASELINE_DIR", tmp_path)

    # reset at the moment of the baseline: nothing moves in time, so the rows are exactly the saved ones
    monkeypatch.setattr(reset, "datetime", SimpleNamespace(now=lambda tz: taken_at))
    dry = (await client.post("/api/v1/demo/reset?dry_run=true")).json()
    async for s in app.dependency_overrides[get_db]():
        assert await s.run_sync(_rows) == changed and await s.run_sync(_markers) == 0  # a dry run changes nothing
    done = (await client.post("/api/v1/demo/reset")).json()
    assert done == dry and (done["tickets"], done["restored_from"], done["jira_issues"]) == (1, saved["taken_at"], 0)
    assert started == []  # the restored state is final: the agents are not started
    async for s in app.dependency_overrides[get_db]():
        assert await s.run_sync(_rows) == before and await s.run_sync(_markers) == 1

    # reset two hours later: the open ticket, its rows and its storm are two hours later; the closed ticket is not
    monkeypatch.setattr(reset, "datetime", SimpleNamespace(now=lambda tz: taken_at + SHIFT))
    assert (await client.post("/api/v1/demo/reset?rerun=false")).status_code == 200
    async for s in app.dependency_overrides[get_db]():
        after = await s.run_sync(_rows)
    for table, where, columns in (
        ("tickets", {"id": "T-OPEN"}, ("opened_at", "ingested_at", "updated_at")),
        ("servicenow_tickets", {"ticket_id": "T-OPEN"}, ("opened_at", "created_at")),
        ("agent_runs", {"ticket_id": "T-OPEN"}, ("created_at",)),
        ("agent_reviews", {"ticket_id": "T-OPEN"}, ("created_at",)),
        ("agent_feedback", {"ticket_id": "T-OPEN"}, ("created_at",)),
        ("ticket_comments", {"ticket_id": "T-OPEN"}, ("created_at",)),
        ("first_messages", {"ticket_id": "T-OPEN"}, ("sent_at",)),
        ("storms", {"id": 1}, ("opened_at", "last_ticket_at", "declared_at", "created_at")),
    ):
        was, now = _one(before, table, **where), _one(after, table, **where)
        assert {c: now[c] - was[c] for c in columns} == dict.fromkeys(columns, SHIFT), table
        assert {k: v for k, v in now.items() if k not in columns} == {k: v for k, v in was.items() if k not in columns}
    assert _one(after, "tickets", id="T-OPEN")["opened_at"] == T0 + SHIFT
    for table in ("tickets", "servicenow_tickets", "agent_runs", "resolved_cases"):
        key = "id" if table == "tickets" else "ticket_id"
        assert _one(after, table, **{key: "T-CLOSED"}) == _one(before, table, **{key: "T-CLOSED"}), table


def _adf(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _issue(status: str, priority: str, labels: list[str], assignee: str | None, comments: list[tuple[str, str, str]]) -> dict:
    return {"status": status, "priority": priority, "labels": labels, "assignee": assignee,
            "comments": [{"id": i, "author": {"accountId": who}, "body": _adf(text)} for i, who, text in comments]}


class Site:
    """A made-up Jira site that keeps its issues, so a test can read what the reset left there."""

    STATUSES = {"Backlog": "new", "In Progress": "indeterminate", "Done": "done"}

    def __init__(self, issues: dict[str, dict]):
        self.issues, self.writes, self.broken = issues, [], set()

    def _status(self, name: str) -> dict:
        return {"name": name, "statusCategory": {"key": self.STATUSES[name]}}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method, parts = request.method, request.url.path.split("/")[4:]  # after /rest/api/3
        if parts[0] == "myself":
            return httpx.Response(200, json={"accountId": "me"})
        if parts[0] == "search":
            found = [{"key": k, "fields": {"status": self._status(i["status"])}} for k, i in self.issues.items()]
            return httpx.Response(200, json={"issues": found, "isLast": True})
        key, rest = parts[1], parts[2:]
        if key in self.broken:
            return httpx.Response(500)
        issue = self.issues[key]
        if method != "GET":
            self.writes.append((method, request.url.path))
        body = json.loads(request.read() or b"{}")
        if rest == ["comment"]:
            return httpx.Response(200, json={"comments": issue["comments"]})
        if rest[:1] == ["comment"]:
            issue["comments"] = [c for c in issue["comments"] if c["id"] != rest[1]]
        elif rest == ["assignee"]:
            issue["assignee"] = body["accountId"]
        elif rest == ["transitions"] and method == "GET":
            return httpx.Response(200, json={"transitions": [{"id": name, "to": self._status(name)} for name in self.STATUSES]})
        elif rest == ["transitions"]:
            issue["status"] = body["transition"]["id"]
        elif method == "PUT":
            fields = body["fields"]
            issue.update({k: fields[k]["name"] if k == "priority" else fields[k] for k in fields})
        else:
            return httpx.Response(200, json={"fields": {
                "summary": key, "status": self._status(issue["status"]), "priority": {"name": issue["priority"]},
                "labels": issue["labels"], "assignee": issue["assignee"] and {"accountId": issue["assignee"]}}})
        return httpx.Response(204)


async def test_reset_puts_jira_back(client, monkeypatch, tmp_path):
    site = Site({
        "AMS-1": _issue("Backlog", "High", ["ams-p2"], "ann", [("1", "me", "AMS agents · Recommended priority: P2"),
                                                               ("2", "ann", "It has failed since 9.")]),
        "AMS-2": _issue("Done", "Low", [], None, []),
        "AMS-9": _issue("Backlog", "Medium", [], None, []),
    })
    monkeypatch.setattr(atlassian, "client",
                        lambda: httpx.AsyncClient(base_url="https://jira.test", transport=httpx.MockTransport(site)))
    monkeypatch.setattr(settings, "JIRA_WRITE_BACK", True)
    monkeypatch.setattr(settings, "DEMO_BASELINE_DIR", tmp_path)
    async for s in app.dependency_overrides[get_db]():
        s.add(JiraProject(key="AMS", name="AMS Support"))
        await s.commit()
        async with atlassian.client() as c:
            issues = await baseline.fetch_issues(c, ["AMS"])
        await s.run_sync(lambda d, issues=issues: baseline.save_baseline(d, issues, tmp_path))
    assert [(i["key"], i["status"], i["assignee_id"]) for i in issues] == [
        ("AMS-1", "Backlog", "ann"), ("AMS-2", "Done", None), ("AMS-9", "Backlog", None)]
    assert [(c["id"], c["author_id"], c["ours"]) for c in issues[0]["comments"]] == [("1", "me", True), ("2", "ann", False)]
    saved = copy.deepcopy(site.issues)

    # since the baseline: the agents and a person worked on AMS-1, AMS-3 was created, and AMS-9 no longer answers
    later = [("3", "me", "SLA warning · P2 due in 20 min"), ("4", "ann", "AMS agents · I typed this myself"),
             ("5", "me", "I am looking at it.")]
    work = _issue("In Progress", "Highest", ["ams-p1", "urgent"], "bob", later)
    site.issues["AMS-1"] = {**work, "comments": site.issues["AMS-1"]["comments"] + work["comments"]}
    site.issues["AMS-3"] = _issue("Backlog", "Medium", [], None, [])
    site.broken.add("AMS-9")
    changed = copy.deepcopy(site.issues)

    dry = (await client.post("/api/v1/demo/reset?dry_run=true")).json()
    assert site.writes == [] and site.issues == changed  # a dry run sends no write to Jira

    done = (await client.post("/api/v1/demo/reset")).json()
    assert done == dry
    assert (done["jira_issues"], done["jira_comments_deleted"], done["jira_moved_back"], done["jira_priorities_restored"],
            done["jira_closed"]) == (2, 1, 1, 1, 1)
    assert done["jira_errors"] == ["AMS-9: Atlassian answered 500 for /rest/api/3/issue/AMS-9"]  # the others went on
    kept = [c["id"] for c in site.issues["AMS-1"].pop("comments")]
    assert kept == ["1", "2", "4", "5"]  # only our own later system comment went; the baseline's and people's stay
    assert site.issues["AMS-1"] == {k: v for k, v in saved["AMS-1"].items() if k != "comments"}
    assert site.issues["AMS-2"] == saved["AMS-2"] and not any("AMS-2" in path for _, path in site.writes)
    assert site.issues["AMS-3"]["status"] == "Done"  # created after the baseline: closed, as it cannot be deleted


def test_a_relative_baseline_folder_is_under_backend():
    assert Settings(DEMO_BASELINE_DIR=".demo-baseline/x").DEMO_BASELINE_DIR == API_DIR / ".demo-baseline" / "x"
    assert Settings(DEMO_BASELINE_DIR=None).DEMO_BASELINE_DIR is None
    assert baseline.load(None) is None and baseline.load(API_DIR / "no-such-folder") is None


def test_the_real_baseline_decodes_and_inserts():
    """Every row of the saved baseline goes into an empty database, with foreign keys checked. The files are only read."""
    saved = baseline.load(REAL)
    if saved is None:
        pytest.skip("no baseline saved on this machine")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for _ in range(2):  # the second time over the rows of the first
            open_tickets = baseline.restore_db(s, saved, saved.taken_at + SHIFT)
            s.commit()
        assert 0 < open_tickets < len(saved.tables["tickets"])
        for name in baseline.TABLES:
            table = Base.metadata.tables[name]
            assert s.scalar(select(func.count()).select_from(table)) == len(saved.tables[name]), name
        assert s.scalar(select(func.count()).select_from(Ticket).where(Ticket.storm_id.is_not(None))) > 0  # storms kept
