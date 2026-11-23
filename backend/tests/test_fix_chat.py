"""The AI assistant on the ticket page: turns are stored, the chat so far goes with each turn, and a proposal becomes
the suggested fix that the usual loop (worked, closure note) takes from there."""

from app.llm import CallAudit, ModelUnavailableError
from app.services.fix_chat import ChatAnswer, ChatFix
from tests.test_fix_outcome import _seed

AUDIT = CallAudit(provider="anthropic", model="m", prompt_version="fix_chat@1", attempts=1, input_tokens=1,
                  output_tokens=1, latency_ms=1)


def _model(monkeypatch, answers):
    from app.api.v1.endpoints import tickets

    seen = []

    def call_model(spec, user, masker):
        seen.append(str(user))
        return answers.pop(0), AUDIT

    monkeypatch.setattr(tickets, "call_model", call_model)
    return seen


async def test_chat_keeps_the_conversation_and_a_proposal_becomes_the_fix(client, monkeypatch):
    await _seed(client)
    fix = ChatFix(root_cause="The posting batch rejected the file: the trailer count is one short.",
                  steps=["Regenerate the file with job PAY_BANK_FILE.", "Re-send it to the bank over SFTP."],
                  check="The bank portal shows the file accepted.")
    seen = _model(monkeypatch, [ChatAnswer(reply="What does the batch log say?", fix=None),
                                ChatAnswer(reply="Then regenerate the file.", fix=fix)])
    body = {"message": "Deals show unpaid after the posting run.", "author": "ravi@contoso.com"}
    first = (await client.post("/api/v1/tickets/AMS-1209/chat", json=body)).json()
    assert (first["agent"], first["verdict"]) == ("fix_chat", "answered")
    assert first["output"]["reply"] == "What does the batch log say?"
    second = (await client.post("/api/v1/tickets/AMS-1209/chat", json={**body, "message": "Trailer 412, file 411."})).json()
    assert second["verdict"] == "proposed"
    assert "Engineer: Deals show unpaid after the posting run." in seen[1] and "Trailer 412, file 411." in seen[1]

    use = {"run_id": second["id"], "reviewer": "ravi@contoso.com"}
    assert (await client.post("/api/v1/tickets/AMS-1209/chat/use", json={**use, "run_id": first["id"]})).status_code == 409
    assert (await client.post("/api/v1/tickets/AMS-1209/chat/use", json=use)).status_code == 200
    detail = (await client.get("/api/v1/tickets/AMS-1209")).json()
    chosen = [r for r in detail["agent_runs"] if r["agent"] == "resolution"][-1]
    assert chosen["verdict"] == "resolved" and chosen["output"]["source"] == "chat"
    assert chosen["output"]["steps"] == fix.steps and chosen["output"]["references"] == []

    worked = {"agent_run_id": chosen["id"], "outcome": "worked", "reviewer": "ravi@contoso.com"}
    assert (await client.post("/api/v1/tickets/AMS-1209/fix-outcome", json=worked)).json()["pipeline_status"] == "fix_confirmed"
    notes = (await client.get("/api/v1/tickets/AMS-1209")).json()["resolution_notes"]
    assert notes.startswith("Cause: The posting batch rejected the file") and "Regenerate the file" in notes


async def test_a_model_failure_is_a_502_and_stores_nothing(client, monkeypatch):
    from app.api.v1.endpoints import tickets

    await _seed(client)

    def down(spec, user, masker):
        raise ModelUnavailableError("APIConnectionError")

    monkeypatch.setattr(tickets, "call_model", down)
    r = await client.post("/api/v1/tickets/AMS-1209/chat", json={"message": "Any idea?", "author": "ravi@contoso.com"})
    assert r.status_code == 502
    runs = (await client.get("/api/v1/tickets/AMS-1209")).json()["agent_runs"]
    assert not [x for x in runs if x["agent"] == "fix_chat"]
