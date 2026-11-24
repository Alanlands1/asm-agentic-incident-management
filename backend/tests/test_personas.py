"""The persona board: open tickets only, the priority in force, and the same P1/P2 count Incidents shows."""

from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.models.incident import FirstMessage
from app.models.jira import JiraSync
from app.models.ticket import AgentRun, Comment, Review, Ticket
from app.personas import service
from app.services.jira import SAID, SLA_BOT
from app.services.triage.review import review
from app.services.triage.sla import open_p1_p2
from tests.test_storms_sla import session  # noqa: F401  (fixture: an empty database)

AT = datetime(2026, 11, 10, 12, 0)


def seed(db):
    def t(i, stage, hours, **kw):
        return Ticket(id=f"AMS-{i}", source="JIRA", summary="s", status="new", pipeline_status=stage,
                      opened_at=AT - timedelta(hours=hours), **kw)

    def triage(i, priority):
        return AgentRun(ticket_id=f"AMS-{i}", agent="triage", verdict=f"P{priority}", output={
            "ai": "used", "priority": priority, "rule": "r", "reason": "x", "stage": "model", "needs_review": False,
        })

    db.add_all([
        t(1, "triaged", 100, assignee="Ravi"),  # P1, long past its target
        t(2, "triaged", 1, assignee="Ravi"),  # P3
        t(3, "awaiting_info", 1),  # not triaged yet
        t(4, "triaged", 1, closed_at=AT),  # closed in Jira: off the board
        t(5, "historical", 1),
        t(6, "triaged", 0),  # recommended P3, raised to P1 by an engineer below
    ])
    db.flush()
    db.add_all([triage(1, 1), triage(2, 3), triage(4, 2), triage(6, 3)])
    db.commit()
    review(db, db.get(Ticket, "AMS-6"), "edited", "priya", priority=1, reason_code="wrong_facts")


def test_board_counts_open_tickets_and_agrees_with_incidents(session, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "ATLASSIAN_BASE_URL", "https://x.atlassian.net/")
    seed(session)
    board = service.board(session, at=AT)

    assert board["totals"] == {"open": 4, "p1_p2": 2, "sla_breached": 1, "sla_at_risk": 0, "waiting_review": 2,
                               "unassigned": 2}
    assert board["totals"]["p1_p2"] == len(open_p1_p2(session, AT))
    assert [r["id"] for r in board["tickets"]] == ["AMS-1", "AMS-6", "AMS-2", "AMS-3"]  # most at risk first
    first, raised, _, waiting = board["tickets"]
    assert (first["sla_state"], first["url"]) == ("breached", "https://x.atlassian.net/browse/AMS-1")
    assert (raised["priority"], raised["priority_from"]) == (1, "reviewed")
    assert (waiting["priority"], waiting["sla_state"]) == (None, None)
    assert board["people"] == [
        {"name": "Ravi", "open": 2, "p1_p2": 1, "breached": 1, "waiting_review": 2},
        {"name": None, "open": 2, "p1_p2": 1, "breached": 0, "waiting_review": 0},
    ]


def test_person_sees_only_their_own(session):  # noqa: F811
    seed(session)
    board = service.board(session, person="Ravi", at=AT)
    assert ({r["id"] for r in board["tickets"]}, board["totals"]["unassigned"]) == ({"AMS-1", "AMS-2"}, 0)


def test_board_says_what_triage_found_and_what_is_missing(session):  # noqa: F811
    seed(session)
    session.get(Ticket, "AMS-1").reported_priority = 3
    session.add_all([
        AgentRun(ticket_id="AMS-3", agent="data_quality", verdict="uncertain", output={"stage": "rules"}),
        AgentRun(ticket_id="AMS-3", agent="data_quality", verdict="needs_info",
                 output={"stage": "model", "answer": {"missing": ["what_happened", "application"]}}),
    ])
    session.commit()
    tickets = {r["id"]: r for r in service.board(session, at=AT)["tickets"]}
    assert [tickets["AMS-1"][k] for k in ("triage_reason", "reported_priority", "missing")] == ["x", 3, []]
    assert [tickets["AMS-3"][k] for k in ("triage_reason", "reported_priority", "missing")] == [
        None, None, ["what_happened", "application"]]


def test_board_gives_the_deadline_the_runbook_and_whether_a_reply_is_drafted(session):  # noqa: F811
    seed(session)
    by_rule, by_reason = session.get(Ticket, "AMS-1").agent_runs[-1], session.get(Ticket, "AMS-2").agent_runs[-1]
    by_rule.output = {**by_rule.output, "application": "OrderHub", "rule": "checkout_failing"}
    by_reason.output = {**by_reason.output, "reason": "Customers cannot complete checkout (KB-ORD-003): P1"}
    session.add(AgentRun(ticket_id="AMS-3", agent="data_quality", verdict="needs_info",
                         output={"stage": "model", "answer": {"missing": ["when"], "chase_email": "Hello, when did it start?"}}))
    session.commit()
    tickets = {r["id"]: r for r in service.board(session, at=AT)["tickets"]}
    due = next(i.sla.due_at for i in open_p1_p2(session, AT) if i.ticket.id == "AMS-1")
    assert [tickets["AMS-1"][k] for k in ("due_at", "runbook", "has_draft")] == [due.replace(tzinfo=UTC), "KB-ORD-003", False]
    assert [tickets["AMS-2"][k] for k in ("due_at", "runbook", "has_draft")] == [None, "KB-ORD-003", False]
    assert [tickets["AMS-3"][k] for k in ("due_at", "runbook", "has_draft")] == [None, None, True]


def test_activity_groups_what_happened_and_keeps_to_one_person(session):  # noqa: F811
    day = datetime(2026, 11, 10, tzinfo=UTC)

    def at(hour, minute=0, second=0):
        return day + timedelta(hours=hour, minutes=minute, seconds=second)

    def run(i, agent, verdict, when, input_hash, **output):
        return AgentRun(ticket_id=f"AMS-{i}", agent=agent, verdict=verdict, input_hash=input_hash, created_at=when, output=output)

    session.add_all([Ticket(id=f"AMS-{i}", source="JIRA", summary="s", status="new", pipeline_status="triaged", assignee=who)
                     for i, who in ((1, "Ravi"), (2, "Ravi"), (3, "Priya"))])
    session.flush()
    decided = run(2, "triage", "P2", at(9, 1, 20), "c", priority=2)
    session.add_all([
        run(1, "triage", "P3", at(-5), "a", priority=3),  # the day before: only what the re-run is compared with
        run(1, "data_quality", "passed", at(9), "b"),
        run(2, "data_quality", "uncertain", at(9, 0, 5), "b"), run(2, "data_quality", "passed", at(9, 0, 20), "b"),  # one pass
        run(3, "data_quality", "passed", at(9, 0, 30), "b"),
        run(1, "triage", "uncertain", at(9, 1), "c"), run(1, "triage", "P3", at(9, 1, 10), "c", priority=3),
        decided,
        Comment(ticket_id="AMS-1", author_email=SLA_BOT, body="Automatic SLA warning", created_at=at(10)),
        Comment(ticket_id="AMS-2", author_email="ravi@example.com", body=f"{SAID}AMS-2.", created_at=at(10, 5)),
        Comment(ticket_id="AMS-2", author_email="ravi@example.com", body="An ordinary reply", created_at=at(10, 6)),
        FirstMessage(ticket_id="AMS-3", text="t", sent_by="Priya", sent_at=at(11)),
        JiraSync(trigger="scheduled", started_at=at(12), error="Jira did not answer"),
        JiraSync(trigger="scheduled", started_at=at(12, 5), error="Jira did not answer"),
        JiraSync(trigger="scheduled", started_at=at(12, 10)),  # succeeded
    ])
    session.flush()
    session.add(Review(ticket_id="AMS-2", agent_run_id=decided.id, agent="triage", action="edited", final_priority=1,
                       reviewer="Ravi", created_at=at(11, 30)))
    session.commit()

    def told(person=None, **kw):
        keys = ("kind", "ticket_ids", "actor", "action", "priority", "previous_priority", "error")
        return [tuple(i.get(k) for k in keys) for i in service.activity(session, person, since=day, **kw)]

    assert told() == [  # newest first
        ("sync_failed", [], None, None, None, None, "Jira did not answer"),
        ("review", ["AMS-2"], "Ravi", "edited", 1, None, None),
        ("first_message", ["AMS-3"], "Priya", None, None, None, None),
        ("summary_sent", ["AMS-2"], "ravi@example.com", None, None, None, None),
        ("sla_warning", ["AMS-1"], None, None, None, None, None),
        ("triage", ["AMS-2"], None, None, None, None, None),
        ("triage_rerun", ["AMS-1"], None, None, 3, 3, None),
        ("data_quality", ["AMS-1", "AMS-2", "AMS-3"], None, None, None, None, None),
    ]
    mine = told("Priya")
    kinds = [(kind, ids) for kind, ids, *_ in mine]
    assert kinds == [("sync_failed", []), ("first_message", ["AMS-3"]), ("data_quality", ["AMS-3"])]
    assert told(limit=2) == told()[:2]
    assert service.activity(session, since=day)[0]["at"] == at(12, 5)  # the last time the sync failed


async def test_activity_and_runbook_endpoints(client):
    assert (await client.get("/api/v1/personas/activity?since=2026-11-10T00:00:00Z")).json() == []
    runbook = (await client.get("/api/v1/runbooks/KB-ORD-003")).json()
    assert (runbook["id"], runbook["application"]) == ("KB-ORD-003", "OrderHub")
    assert runbook["title"].startswith("Checkout fails") and runbook["markdown"].startswith("**Symptoms**")
    assert "---" not in runbook["markdown"] and "KB-ORD-004" not in runbook["markdown"]
    assert (await client.get("/api/v1/runbooks/KB-NOPE-1")).status_code == 404


async def test_board_endpoint(client):
    body = (await client.get("/api/v1/personas/board")).json()
    assert (body["totals"]["open"], body["tickets"], body["people"]) == (0, [], [])


def test_lead_review_steps_fix_answers_and_closes_have_their_own_kinds(session):  # noqa: F811
    """Before: every stored review read as a Triage decision ("rejected the recommendation")."""
    day = datetime(2026, 11, 10, tzinfo=UTC)
    session.add(Ticket(id="AMS-1", source="JIRA", summary="s", status="new", pipeline_status="in_review"))
    session.flush()
    fix = AgentRun(ticket_id="AMS-1", agent="resolution", verdict="resolved", output={}, created_at=day)
    session.add(fix)
    session.flush()

    def step(agent, action, minute):
        return Review(ticket_id="AMS-1", agent_run_id=fix.id, agent=agent, action=action, reviewer="Ravi",
                      created_at=day + timedelta(hours=9, minutes=minute))

    session.add_all([step("resolution", "worked", 0), step("lead_review", "submitted", 5),
                     step("lead_review", "approved", 10), step("close", "sent", 15)])
    session.commit()
    told = [(i["kind"], i["action"]) for i in service.activity(session, since=day)]
    assert told == [("closed", "sent"), ("lead_review", "approved"), ("lead_review", "submitted"), ("fix_answer", "worked")]


def test_board_says_where_each_ticket_is(session, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "LEAD_REVIEW", "always")
    session.add(Ticket(id="AMS-1", source="JIRA", summary="s", status="new", pipeline_status="fix_confirmed", assignee="Ravi"))
    session.flush()
    fix = AgentRun(ticket_id="AMS-1", agent="resolution", verdict="resolved", output={})
    check = AgentRun(ticket_id="AMS-1", agent="closure_quality", verdict="good", output={"score": 6})
    session.add_all([fix, check])
    session.flush()
    session.add_all([Review(ticket_id="AMS-1", agent_run_id=fix.id, agent="resolution", action="worked", reviewer="Ravi"),
                     Review(ticket_id="AMS-1", agent_run_id=check.id, agent="lead_review", action="sent_back",
                            note="Say how you checked", reviewer="Priya")])
    session.commit()
    row = service.board(session, at=AT)["tickets"][0]
    assert {k: row[k] for k in ("fix_verdict", "fix_answer", "fix_rated", "closure_verdict", "closure_score",
                                "lead_step", "lead_by", "review_required")} == {
        "fix_verdict": "resolved", "fix_answer": "worked", "fix_rated": False, "closure_verdict": "good",
        "closure_score": 6, "lead_step": "sent_back", "lead_by": "Priya", "review_required": True}


def test_today_counts_each_agent_and_closed_by_names_the_closer(session):  # noqa: F811
    day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    session.add_all([Ticket(id="AMS-1", source="JIRA", summary="Paid orders stuck", status="closed",
                            pipeline_status="fix_confirmed", closed_at=datetime.now(UTC).replace(tzinfo=None)),
                     Ticket(id="AMS-2", source="JIRA", summary="s", status="new", pipeline_status="awaiting_info",
                            opened_at=datetime.now(UTC).replace(tzinfo=None))])
    session.flush()
    runs = [AgentRun(ticket_id="AMS-1", agent=a, verdict=v, output={"priority": 2} if a == "triage" else {})
            for a, v in (("data_quality", "passed"), ("triage", "P2"), ("resolution", "resolved"),
                         ("closure_quality", "good"), ("knowledge_builder", "matched"))]
    runs.append(AgentRun(ticket_id="AMS-2", agent="data_quality", verdict="needs_info", output={}))
    session.add_all(runs)
    session.flush()
    session.add(Review(ticket_id="AMS-1", agent_run_id=runs[3].id, agent="close", action="sent", reviewer="Ravi"))
    session.commit()
    got = service.today(session, day)
    assert (got["data_quality"]["done"], got["data_quality"]["flagged"], got["resolution"]["done"]) == (2, 1, 1)
    assert (got["knowledge_builder"]["done"], got["knowledge_builder"]["flagged"], got["closed"]) == (1, 1, 1)
    assert got["opened"] == 1  # AMS-1 has no opened date
    closed = service.closed_by(session, "Ravi")
    assert [(c["id"], c["summary"], c["kb"]) for c in closed] == [("AMS-1", "Paid orders stuck", None)]
    assert service.closed_by(session, "Priya") == []


def test_a_ticket_without_an_application_shows_the_one_triage_found(session):  # noqa: F811
    session.add(Ticket(id="MBX-1", source="Mailbox", summary="Invoice run failed", status="new", pipeline_status="triaged"))
    session.flush()
    session.add(AgentRun(ticket_id="MBX-1", agent="triage", verdict="P2",
                         output={"priority": 2, "application": "BillingEngine", "reason": "x", "rule": "r"}))
    session.commit()
    assert service.board(session, at=AT)["tickets"][0]["application"] == "BillingEngine"


def test_an_unassigned_ticket_is_suggested_to_who_knows_the_application_and_has_room(session):  # noqa: F811
    def t(i, app, who=None, closed=False):
        return Ticket(id=f"AMS-{i}", source="JIRA", summary="s", application=app, assignee=who,
                      status="closed" if closed else "new", pipeline_status="historical" if closed else "pending",
                      closed_at=AT if closed else None, opened_at=AT - timedelta(hours=20 - i))

    session.add_all([
        t(1, "OrderHub", "Ravi", closed=True), t(2, "OrderHub", "Ravi", closed=True), t(3, "PayrollPro", "Priya", closed=True),
        t(4, "OrderHub"), t(5, "OrderHub"), t(6, "PayrollPro"), t(7, None), t(8, "PayrollPro", "Priya"),
    ])
    session.commit()
    got = {s["id"]: (s["name"], s["reason"]) for s in service.suggestions(session, at=AT)}
    assert got == {
        "AMS-4": ("Ravi", "resolved 2 OrderHub tickets · holds 0 now, 2 after this batch"),
        "AMS-5": ("Ravi", "resolved 2 OrderHub tickets · holds 0 now, 2 after this batch"),  # nobody else knows OrderHub
        # the open one she holds is not resolved yet
        "AMS-6": ("Priya", "resolved 1 PayrollPro ticket · holds 1 now, 3 after this batch"),
        "AMS-7": ("Priya", "holds 1 now, 3 after this batch"),  # no application: both would hold 2, the name decides
    }
    session.add_all([t(i, "OrderHub", "Ravi") for i in range(10, 16)])  # Ravi is loaded now
    session.commit()
    assert service.suggestions(session, at=AT)[0]["name"] == "Priya"  # knowing OrderHub does not outweigh six more tickets


def test_nobody_at_the_limit_is_suggested_another_ticket_unless_it_is_urgent(session, monkeypatch):  # noqa: F811
    from datetime import time

    from app.personas import availability
    from app.personas.availability import Hours, Team

    team = Team(timedelta(0), Hours(frozenset(range(7)), time(0), time(23, 59)), {}, (), max_open=2)
    monkeypatch.setattr(availability, "config", lambda: team)

    def t(i, stage="pending", who=None):
        return Ticket(id=f"AMS-{i}", source="JIRA", summary="s", status="new", pipeline_status=stage, assignee=who,
                      opened_at=AT - timedelta(minutes=i))

    session.add_all([t(1, who="Ravi"), t(2, who="Ravi"), t(3), t(4, "triaged")])  # Ravi is the team, and is full
    session.flush()
    session.add(AgentRun(ticket_id="AMS-4", agent="triage", verdict="P1", output={
        "ai": "used", "priority": 1, "rule": "r", "reason": "x", "stage": "model", "needs_review": False}))
    session.commit()
    got = service.suggestions(session, at=AT)
    # the P1 goes over the limit; the untriaged ticket waits for the lead
    assert got == [{"id": "AMS-4", "name": "Ravi", "reason": "holds 2 now, 3 after this batch · over the limit, urgent"}]


def test_who_resolved_a_ticket_counts_not_who_was_given_it_and_only_recently(session):  # noqa: F811
    def t(i, who, closed_days_ago):
        return Ticket(id=f"AMS-{i}", source="JIRA", summary="s", application="OrderHub", assignee=who, status="closed",
                      pipeline_status="historical", closed_at=AT - timedelta(days=closed_days_ago))

    session.add_all([t(1, "Ravi", 200), t(2, "Ravi", 5), t(3, "Ravi", 5)])  # one too long ago to count
    session.flush()
    fix = AgentRun(ticket_id="AMS-3", agent="resolution", verdict="resolved", output={})
    session.add(fix)
    session.flush()
    session.add(Review(ticket_id="AMS-3", agent_run_id=fix.id, agent="resolution", action="worked", reviewer="Priya",
                       created_at=AT - timedelta(days=5)))  # Priya fixed the ticket Ravi held
    session.commit()
    assert service._resolved(session, AT) == {("OrderHub", "Ravi"): 2, ("OrderHub", "Priya"): 1}


def test_nobody_on_leave_is_suggested_and_off_shift_only_when_nobody_is_on_shift(session, monkeypatch):  # noqa: F811
    from datetime import date, time

    from app.personas import availability
    from app.personas.availability import Hours, Team

    days = frozenset(range(5))
    office, night = Hours(days, time(9), time(18)), Hours(days, time(22), time(6))
    team = Team(timedelta(hours=5, minutes=30), office, {"Ravi": night}, (("Priya", date(2026, 11, 9), date(2026, 11, 11)),))
    monkeypatch.setattr(availability, "config", lambda: team)
    session.add_all([Ticket(id=f"AMS-{i}", source="JIRA", summary="s", status="closed", pipeline_status="historical",
                            assignee=who, closed_at=AT) for i, who in enumerate(("Ravi", "Priya", "Meera"), 1)])
    session.add(Ticket(id="AMS-9", source="JIRA", summary="s", status="new", pipeline_status="pending", opened_at=AT))
    session.commit()

    # AT is Tuesday 17:30 for the team: Meera in the office, Ravi before his night shift, Priya on leave
    assert service.team_status(session, AT) == {
        "Meera": {"state": "on_shift", "until": None}, "Priya": {"state": "on_leave", "until": date(2026, 11, 11)},
        "Ravi": {"state": "off_shift", "until": None}}
    assert [s["name"] for s in service.suggestions(session, at=AT)] == ["Meera"]
    night_time = AT + timedelta(hours=7)  # Wednesday 00:30 for the team: only Ravi works
    assert service.team_status(session, night_time)["Ravi"]["state"] == "on_shift"
    assert [s["name"] for s in service.suggestions(session, at=night_time)] == ["Ravi"]
    weekend = AT + timedelta(days=4)  # Saturday: nobody on shift, so someone off shift is suggested and it says so
    assert service.suggestions(session, at=weekend)[0]["reason"].endswith("off shift now")


async def test_the_team_document_is_checked_before_it_is_saved(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "test-key")
    key, url = {"X-Admin-Key": "test-key", "X-Admin-User": "lead"}, "/api/v1/admin/documents/team"
    team = (await client.get(url, headers=key)).json()["document"]
    leave = {"name": "Ravi", "from": "2026-11-26", "to": "2026-11-27"}
    assert (await client.put(url, headers=key, json={"document": {**team, "leave": [leave]}})).status_code == 200
    backwards = {**leave, "from": "2026-11-28"}
    assert (await client.put(url, headers=key, json={"document": {**team, "leave": [backwards]}})).status_code == 422
    assert (await client.get(url, headers=key)).json()["document"]["leave"] == [leave]  # the refused one changed nothing
    await client.delete(url, headers=key)


async def test_the_engineer_list_adds_who_jira_can_assign(client, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import settings
    from app.db.session import get_db
    from app.main import app
    from app.models.jira import JiraProject
    from app.services import jira

    async def assignable(keys):
        assert keys == ["AMS"]
        return ["Meera Nair", "Ravi"]

    monkeypatch.setattr(jira, "assignable", assignable)
    for name in ("ATLASSIAN_BASE_URL", "ATLASSIAN_EMAIL"):
        monkeypatch.setattr(settings, name, "https://x.atlassian.net")
    monkeypatch.setattr(settings, "ATLASSIAN_API_TOKEN", SecretStr("t"))
    async for db in app.dependency_overrides[get_db]():
        db.add_all([JiraProject(key="AMS", name="AMS Support"),
                    Ticket(id="AMS-1", source="JIRA", summary="s", status="new", pipeline_status="pending", assignee="Ravi")])
        await db.commit()
    assert (await client.get("/api/v1/personas/people")).json() == ["Meera Nair", "Ravi"]
    on_team = {p["name"]: p["member"] for p in (await client.get("/api/v1/personas/roster")).json()}
    assert on_team == {"Meera Nair": False, "Ravi": True}  # someone only Jira knows waits for the lead
    assert list((await client.get("/api/v1/personas/availability")).json()) == ["Ravi"]


def test_the_lead_decides_who_is_on_the_team(session, monkeypatch):  # noqa: F811
    from datetime import time

    from app.personas import availability
    from app.personas.availability import Hours, Team
    from app.services import jira

    hours = Hours(frozenset(range(7)), time(0), time(23, 59))
    session.add_all([Ticket(id=f"AMS-{i}", source="JIRA", summary="s", status="closed", pipeline_status="historical",
                            assignee=who, closed_at=AT) for i, who in enumerate(("Ravi", "Priya", "Gone"), 1)])
    session.add(Ticket(id="AMS-9", source="JIRA", summary="s", status="new", pipeline_status="pending", opened_at=AT))
    session.commit()
    monkeypatch.setattr(jira, "known_people", ["Meera", "New", "Priya", "Ravi"])  # Gone has left Jira
    team = Team(timedelta(0), hours, {}, (), members=frozenset({"New"}), not_members=frozenset({"Priya"}))
    monkeypatch.setattr(availability, "config", lambda: team)

    assert service.members(session) == ["New", "Ravi"]  # put on by the lead; held a ticket and still in Jira
    assert {r["name"] for r in service.roster(session)} == {"Gone", "Meera", "New", "Priya", "Ravi"}
    # someone new has no history, so the fewest open tickets decides, and the name between equals
    assert [(s["name"], s["reason"]) for s in service.suggestions(session, at=AT)] == [("New", "holds 0 now, 1 after this batch")]
