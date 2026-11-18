async def test_ingest_loads_all_sources(client):
    response = await client.post("/api/v1/ingest")
    assert response.status_code == 200
    assert response.json() == {"created": 50, "updated": 0, "by_source": {"JIRA": 30, "Mailbox": 20}}

    # re-running is an upsert, not a duplicate load
    again = (await client.post("/api/v1/ingest")).json()
    assert again["created"] == 0 and again["updated"] == 50


async def test_list_tickets_filters(client):
    await client.post("/api/v1/ingest")

    data = (await client.get("/api/v1/tickets", params={"source": "Mailbox", "limit": 500})).json()
    assert data["total"] == 20
    assert all(t["source"] == "Mailbox" and t["reported_priority"] is None for t in data["items"])

    pending = (await client.get("/api/v1/tickets", params={"pipeline_status": "pending", "limit": 500})).json()
    historical = (await client.get("/api/v1/tickets", params={"pipeline_status": "historical", "limit": 500})).json()
    assert pending["total"] + historical["total"] == 50
    assert all(t["status"] in ("resolved", "closed") for t in historical["items"])


async def test_get_ticket_normalises_source_fields(client):
    await client.post("/api/v1/ingest")
    first_jira = (await client.get("/api/v1/tickets", params={"source": "JIRA", "limit": 1})).json()["items"][0]

    detail = (await client.get(f"/api/v1/tickets/{first_jira['id']}")).json()
    assert detail["raw"]["issue_key"] == first_jira["id"]
    assert detail["reported_priority_label"] in ("Highest", "High", "Medium", "Low", "Lowest")
    assert 1 <= detail["reported_priority"] <= 5
    assert detail["agent_runs"] == []


async def test_get_unknown_ticket_returns_404(client):
    response = await client.get("/api/v1/tickets/INC9999999")
    assert response.status_code == 404


# --- the engineer's note to the agents, and star ratings of the agents' results ---

import re  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.ticket import AgentRun, Feedback, Ticket  # noqa: E402
from app.services.data_quality import reporter_text  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402


async def _first_ticket(client, offset=0):
    await client.post("/api/v1/ingest")
    return (await client.get("/api/v1/tickets", params={"source": "JIRA", "limit": 5})).json()["items"][offset]["id"]


async def _stored(ticket_id):
    async for db in app.dependency_overrides[get_db]():
        return await db.get(Ticket, ticket_id, options=[selectinload(Ticket.comments)])


async def _seed_run(ticket_id, agent="resolution", output=None):
    async for db in app.dependency_overrides[get_db]():
        run = AgentRun(ticket_id=ticket_id, agent=agent, verdict="resolved", output=output or {})
        db.add(run)
        await db.commit()
        return run.id


async def _ratings():
    async for db in app.dependency_overrides[get_db]():
        return await db.scalar(select(func.count()).select_from(Feedback))


async def test_ticket_detail_starts_with_no_note_and_no_ratings(client):
    ticket_id = await _first_ticket(client)
    detail = (await client.get(f"/api/v1/tickets/{ticket_id}")).json()
    assert detail["guidance"] is None
    assert detail["feedback"] == []


async def test_note_is_kept_and_read_by_the_agents(client, monkeypatch):
    monkeypatch.setattr(settings, "PII_MASKING_ENABLED", False)
    ticket_id = await _first_ticket(client)
    response = await client.put(f"/api/v1/tickets/{ticket_id}/guidance", json={"text": " Restarting the renderer fixed it last month. "})
    assert response.status_code == 200
    assert (await client.get(f"/api/v1/tickets/{ticket_id}")).json()["guidance"] == "Restarting the renderer fixed it last month."
    text = reporter_text(await _stored(ticket_id))
    assert text.endswith("Note from the support engineer:\nRestarting the renderer fixed it last month.")


async def test_empty_note_removes_it(client):
    ticket_id = await _first_ticket(client)
    await client.put(f"/api/v1/tickets/{ticket_id}/guidance", json={"text": "The renderer was restarted."})
    await client.put(f"/api/v1/tickets/{ticket_id}/guidance", json={"text": "   "})
    assert (await client.get(f"/api/v1/tickets/{ticket_id}")).json()["guidance"] is None
    assert "Note from the support engineer" not in reporter_text(await _stored(ticket_id))


async def test_note_is_masked_before_it_is_stored(client, monkeypatch):
    monkeypatch.setattr(settings, "PII_MASKING_ENABLED", True)
    ticket_id = await _first_ticket(client)
    await client.put(f"/api/v1/tickets/{ticket_id}/guidance", json={"text": "Ask priya.raman@contoso.com, she fixed it before."})
    stored = (await _stored(ticket_id)).guidance
    assert stored and "priya.raman@contoso.com" not in stored


async def test_names_added_to_a_masked_note_get_their_own_placeholder(client, monkeypatch):
    monkeypatch.setattr(settings, "PII_MASKING_ENABLED", True)
    ticket_id = await _first_ticket(client)
    await client.put(f"/api/v1/tickets/{ticket_id}/guidance", json={"text": "Ask Ravi Kumar, then Asha Rao."})
    first = (await _stored(ticket_id)).guidance
    await client.put(f"/api/v1/tickets/{ticket_id}/guidance", json={"text": f"{first} Also Vinay Sharma."})
    stored = (await _stored(ticket_id)).guidance
    assert "Vinay" not in stored and len(set(re.findall(r"<PERSON_\d+>", stored))) == 3


async def test_note_too_long_is_rejected(client):
    ticket_id = await _first_ticket(client)
    response = await client.put(f"/api/v1/tickets/{ticket_id}/guidance", json={"text": "x" * 4001})
    assert response.status_code == 422


async def test_note_on_unknown_ticket_is_404(client):
    response = await client.put("/api/v1/tickets/INC9999999/guidance", json={"text": "hello"})
    assert response.status_code == 404


def _rating(run_id, **kw):
    return {"agent_run_id": run_id, "stars": 4, "reason": "Right runbook, one step missing.", "reviewer": "Alan Test", **kw}


async def test_rating_is_stored_with_the_agent_of_the_result(client, monkeypatch):
    monkeypatch.setattr(settings, "PII_MASKING_ENABLED", False)
    ticket_id = await _first_ticket(client)
    run_id = await _seed_run(ticket_id, agent="triage")
    response = await client.post(f"/api/v1/tickets/{ticket_id}/feedback", json=_rating(run_id))
    assert response.status_code == 201
    assert response.json()["agent"] == "triage" and response.json()["stars"] == 4
    listed = (await client.get(f"/api/v1/tickets/{ticket_id}")).json()["feedback"]
    assert [(f["agent_run_id"], f["stars"], f["reason"], f["reviewer"]) for f in listed] == [
        (run_id, 4, "Right runbook, one step missing.", "Alan Test")
    ]


async def test_rating_needs_a_reason(client):
    ticket_id = await _first_ticket(client)
    run_id = await _seed_run(ticket_id)
    response = await client.post(f"/api/v1/tickets/{ticket_id}/feedback", json=_rating(run_id, reason="   "))
    assert response.status_code == 422
    assert await _ratings() == 0


async def test_stars_outside_one_to_five_are_rejected(client):
    ticket_id = await _first_ticket(client)
    run_id = await _seed_run(ticket_id)
    for stars in (0, 6):
        response = await client.post(f"/api/v1/tickets/{ticket_id}/feedback", json=_rating(run_id, stars=stars))
        assert response.status_code == 422
    assert await _ratings() == 0


async def test_rating_a_result_of_another_ticket_is_404(client):
    ticket_id = await _first_ticket(client)
    other = await _first_ticket(client, offset=1)
    run_id = await _seed_run(other)
    response = await client.post(f"/api/v1/tickets/{ticket_id}/feedback", json=_rating(run_id))
    assert response.status_code == 404
    assert await _ratings() == 0


async def test_reason_is_masked_before_it_is_stored(client, monkeypatch):
    monkeypatch.setattr(settings, "PII_MASKING_ENABLED", True)
    ticket_id = await _first_ticket(client)
    run_id = await _seed_run(ticket_id)
    reason = "priya.raman@contoso.com said this runbook is for the card gateway."
    response = await client.post(f"/api/v1/tickets/{ticket_id}/feedback", json=_rating(run_id, reason=reason))
    assert response.status_code == 201
    assert "priya.raman@contoso.com" not in response.json()["reason"]
