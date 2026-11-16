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
