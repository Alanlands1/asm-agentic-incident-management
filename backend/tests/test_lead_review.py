"""The lead's review of a closure note before it is sent (design D3): which tickets need it, and the steps."""

import pytest

from app.core.config import settings
from app.models.ticket import AgentRun, Review, Ticket
from app.services import lead_review
from tests.test_fix_outcome import _seed
from tests.test_triage import db  # noqa: F401  (fixture: every open ticket as if Data Quality had passed it)

NOTE = "Cause: the batch rejected the file. Fix: re-ran posting. Checked: all four deals show paid."


@pytest.mark.parametrize(("setting", "priority", "needed"), [
    ("p1_p2", 1, True), ("p1_p2", 2, True), ("p1_p2", 3, False), ("p1_p2", None, False),
    ("always", 4, True), ("always", None, True), ("never", 1, False),
])
def test_which_tickets_need_the_lead(db, monkeypatch, setting, priority, needed):  # noqa: F811
    monkeypatch.setattr(settings, "LEAD_REVIEW", setting)
    ticket = db.get(Ticket, "AMS-1209")
    ticket.reported_priority = priority
    assert lead_review.required(db, ticket) is needed


def test_the_decided_priority_counts_before_the_reporters(db, monkeypatch):  # noqa: F811
    ticket = db.get(Ticket, "AMS-1209")  # reported P1
    run = AgentRun(ticket_id=ticket.id, agent="triage", verdict="P3", output={"priority": 3})
    db.add(run)
    db.flush()
    db.add(Review(ticket_id=ticket.id, agent_run_id=run.id, agent="triage", action="accepted", final_priority=3,
                  reviewer="r@x.com"))
    db.flush()
    assert lead_review.priority_of(db, ticket) == 3 and not lead_review.required(db, ticket)


async def _confirmed(client) -> None:
    """AMS-1209 (a P1) with its fix confirmed and a complete closure note, checked by Closure Quality."""
    run_id = await _seed(client)
    await client.post("/api/v1/tickets/AMS-1209/fix-outcome",
                      json={"agent_run_id": run_id, "outcome": "worked", "reviewer": "ravi@contoso.com"})
    assert (await client.put("/api/v1/tickets/AMS-1209/closure-note", json={"text": NOTE})).status_code == 200


async def test_submit_send_back_then_approve_then_send(client, monkeypatch):
    from app.services import jira

    await _confirmed(client)
    engineer, lead = {"reviewer": "ravi@contoso.com"}, "lead@contoso.com"
    detail = (await client.get("/api/v1/tickets/AMS-1209")).json()
    assert detail["lead_review_required"] and detail["lead_reviews"] == []
    send = {"author_email": "ravi@contoso.com"}
    r = await client.post("/api/v1/tickets/AMS-1209/close", json=send)
    assert r.status_code == 409 and "lead approves" in r.json()["detail"]

    assert (await client.post("/api/v1/tickets/AMS-1209/submit-review", json=engineer)).json()["pipeline_status"] == "in_review"
    assert (await client.put("/api/v1/tickets/AMS-1209/closure-note", json={"text": NOTE})).status_code == 409  # in review
    back = {"action": "sent_back", "reviewer": lead}
    assert (await client.post("/api/v1/tickets/AMS-1209/lead-review", json=back)).status_code == 409  # no comment
    back["note"] = "Say which report showed the four deals as paid."
    assert (await client.post("/api/v1/tickets/AMS-1209/lead-review", json=back)).json()["pipeline_status"] == "fix_confirmed"

    await client.post("/api/v1/tickets/AMS-1209/submit-review", json=engineer)
    approve = {"action": "approved", "reviewer": lead}
    assert (await client.post("/api/v1/tickets/AMS-1209/lead-review", json=approve)).json()["pipeline_status"] == "approved"
    detail = (await client.get("/api/v1/tickets/AMS-1209")).json()
    assert [(s["action"], s["reviewer"]) for s in detail["lead_reviews"]] == [
        ("submitted", "ravi@contoso.com"), ("sent_back", lead), ("submitted", "ravi@contoso.com"), ("approved", lead)]
    assert detail["lead_reviews"][1]["note"] == back["note"]

    closed = []

    async def close_issue(key, text, c=None, priority=None):
        closed.append(key)
        return "Done"

    monkeypatch.setattr(jira, "close_issue", close_issue)
    assert (await client.post("/api/v1/tickets/AMS-1209/close", json=send)).json()["status"] == "closed"
    assert closed == ["AMS-1209"]
    mine = (await client.get("/api/v1/personas/closed", params={"person": "ravi@contoso.com"})).json()
    assert [c["id"] for c in mine] == ["AMS-1209"]  # who pressed Send is recorded


async def test_a_changed_note_needs_approval_again(client):
    await _confirmed(client)
    await client.post("/api/v1/tickets/AMS-1209/submit-review", json={"reviewer": "ravi@contoso.com"})
    await client.post("/api/v1/tickets/AMS-1209/lead-review", json={"action": "approved", "reviewer": "lead@contoso.com"})
    r = await client.put("/api/v1/tickets/AMS-1209/closure-note", json={"text": NOTE + " Also checked the ledger."})
    assert r.json()["pipeline_status"] == "fix_confirmed"


async def test_submit_is_refused_when_no_review_is_needed_or_the_note_has_gaps(client, monkeypatch):
    run_id = await _seed(client)
    await client.post("/api/v1/tickets/AMS-1209/fix-outcome",
                      json={"agent_run_id": run_id, "outcome": "worked", "reviewer": "ravi@contoso.com"})
    r = await client.post("/api/v1/tickets/AMS-1209/submit-review", json={"reviewer": "ravi@contoso.com"})
    assert r.status_code == 409 and "engineer to add" in r.json()["detail"]  # the drafted note still has gaps
    await client.put("/api/v1/tickets/AMS-1209/closure-note", json={"text": NOTE})
    monkeypatch.setattr(settings, "LEAD_REVIEW", "never")
    r = await client.post("/api/v1/tickets/AMS-1209/submit-review", json={"reviewer": "ravi@contoso.com"})
    assert r.status_code == 409 and "no lead review" in r.json()["detail"]
