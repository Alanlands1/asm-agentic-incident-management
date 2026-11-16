from app.agents.data_quality.rules import Verdict, evaluate
from app.agents.data_quality.signals import strip_body

EMAIL = "Hi Team,\n\nScanner not working at my station.\n\nThanks & Regards,\nRavi Shankar\nWarehouse - Chennai"


def test_strip_body_removes_greeting_and_signature():
    assert strip_body(EMAIL) == "Scanner not working at my station."
    assert strip_body("Hi, I need help.") == "I need help."


def test_test_ticket_is_not_an_incident():
    assert evaluate("Test", "test ticket please ignore").verdict == Verdict.NOT_AN_INCIDENT
    request = evaluate("Access request: new joiner needs a viewer role", "Our new analyst joins on Monday and needs a licence.")
    assert (request.verdict, request.rule) == (Verdict.NOT_AN_INCIDENT, "service_request")
    assert evaluate("Access request page returns error 500 for everyone", "x").rule != "service_request"  # something is broken


def test_near_empty_ticket_needs_info():
    result = evaluate("Scanner problem", EMAIL)
    assert result.verdict == Verdict.NEEDS_INFO and result.rule == "near_empty"
    assert result.signals.app_found == "StockSense" and result.signals.app_source == "keyword"


def test_placeholder_description_needs_info():
    for body in ["N/A", "n.a.", "-", "TBD", "Please check."]:
        result = evaluate("Login issue", body)
        assert result.verdict == Verdict.NEEDS_INFO and result.rule in ("placeholder", "near_empty"), body
    assert evaluate("Login issue", "N/A").rule == "placeholder"


def test_filler_does_not_count_towards_length():
    result = evaluate("Error", "Not working since morning. Please fix it ASAP, urgent!! Thanks in advance, see attached screenshot.")
    assert result.verdict == Verdict.NEEDS_INFO and result.signals.body_length < 50


def test_attachment_only_ticket_needs_info():
    result = evaluate("FW:", "", attachments="error.png")
    assert result.verdict == Verdict.NEEDS_INFO
    assert result.signals.attachment_only and result.signals.summary_equals_body


def test_detailed_ticket_goes_to_the_model_with_signals():
    result = evaluate(
        "Payslip download fails",
        "Since Monday every employee gets PDF-GEN-500 when downloading the October payslip, see INC0010231.",
        application="PayrollPro",
    )
    assert result.verdict == Verdict.UNCERTAIN and result.rule is None
    s = result.signals
    assert s.app_found == "PayrollPro" and s.app_source == "system"
    assert s.identifier_found and s.mentions_previous_ticket


async def _status(client, ticket_id):
    return (await client.get(f"/api/v1/tickets/{ticket_id}")).json()["pipeline_status"]


async def test_run_sets_statuses_and_is_idempotent(client):
    await client.post("/api/v1/ingest")
    first = (await client.post("/api/v1/data-quality/run")).json()
    assert first["evaluated"] == 35 and first["skipped"] == 0

    assert await _status(client, "MBX-00012") == "awaiting_info"
    assert await _status(client, "MBX-00006") == "pending"  # uncertain: left for the model

    again = (await client.post("/api/v1/data-quality/run")).json()
    assert again["evaluated"] == 0


async def test_reporter_reply_reopens_ticket_for_a_fresh_check(client):
    await client.post("/api/v1/ingest")
    await client.post("/api/v1/data-quality/run")
    ticket = (await client.get("/api/v1/tickets/MBX-00012")).json()

    other = await client.post("/api/v1/tickets/MBX-00012/comments", json={"author_email": "someone@contoso.com", "body": "+1"})
    assert other.status_code == 201 and not other.json()["from_reporter"]
    assert await _status(client, "MBX-00012") == "awaiting_info"

    reply = "It is EmployeePortal. Since 09:00 today SSO loops back to the login page for me and my team of 12."
    await client.post("/api/v1/tickets/MBX-00012/comments", json={"author_email": ticket["reporter_email"].upper(), "body": reply})
    assert await _status(client, "MBX-00012") == "pending"

    rerun = (await client.post("/api/v1/data-quality/run")).json()
    assert rerun["evaluated"] == 1 and rerun["by_verdict"] == {"uncertain": 1}


async def test_comment_on_unknown_ticket_returns_404(client):
    response = await client.post("/api/v1/tickets/INC9999999/comments", json={"author_email": "a@b.c", "body": "hi"})
    assert response.status_code == 404


async def test_a_changed_note_makes_the_ticket_due_for_a_new_check(client):
    await client.post("/api/v1/ingest")
    await client.post("/api/v1/data-quality/run")
    assert (await client.post("/api/v1/data-quality/run")).json()["evaluated"] == 0

    note = await client.put("/api/v1/tickets/MBX-00006/guidance", json={"text": "The renderer was restarted last month."})
    assert note.status_code == 200
    assert (await client.post("/api/v1/data-quality/run")).json()["evaluated"] == 1


async def test_a_note_sends_a_ticket_awaiting_information_back_for_a_fresh_check(client):
    await client.post("/api/v1/ingest")
    await client.post("/api/v1/data-quality/run")
    assert await _status(client, "MBX-00012") == "awaiting_info"

    await client.put("/api/v1/tickets/MBX-00012/guidance", json={"text": "It is PayrollPro, the March payslip PDF is blank."})
    assert await _status(client, "MBX-00012") == "pending"
