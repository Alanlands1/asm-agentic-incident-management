"""The draft email to the requester once the closure note is final. The model is a scripted stand-in (no network)."""

import re

import pytest
from fastapi import HTTPException

from app.agents.closure_quality.requester_email import RequesterEmail
from app.api.v1.endpoints.closure import _draft_email
from tests.test_knowledge import session, ticket  # noqa: F401  (fixture and helper)
from tests.test_llm import _reply, provider  # noqa: F401  (fixture)

NOTES = "Cause: the PAY_CALC_MONTHLY batch ran out of undo space. Re-ran the job in chunks; the register now balances."


def saved(session, notes: str = NOTES):  # noqa: F811
    session.add(ticket(1, notes=notes, name="Meera Nair"))
    session.commit()


def test_the_draft_greets_the_requester_by_name_and_names_nothing_off_the_ticket(session, provider):  # noqa: F811
    saved(session)
    fake = provider()

    def parse(**params):  # greets the requester by the placeholder it was given, as the model would
        fake.requests.append(params)
        name = re.search(r"Requester: (<PERSON_\d+>)", str(params))[1]
        return _reply(RequesterEmail(subject="Resolved: payroll batch",
                                     body=f"Hello {name},\n\nThe batch was run again.\n\nIT Support"))

    fake.parse = parse
    email = _draft_email(session, "K-1")
    assert email.subject == "Resolved: payroll batch" and email.body.startswith("Hello Meera Nair,")
    sent = str(fake.requests[0])
    assert "Meera" not in sent and "PAY_CALC_MONTHLY" in sent  # the name is masked, the facts are not


def test_a_draft_with_a_code_not_on_the_ticket_is_not_shown(session, provider):  # noqa: F811
    saved(session)
    provider(_reply(RequesterEmail(subject="Resolved", body="We ran PAY_FIX_77 and it works now.")))
    with pytest.raises(HTTPException) as caught:
        _draft_email(session, "K-1")
    assert caught.value.status_code == 422 and "PAY_FIX_77" in caught.value.detail


@pytest.mark.parametrize("notes, status", [("", 409), ("Re-ran it. [engineer to add: check]", 409), (NOTES, 503)])
def test_no_draft_without_a_complete_note_or_with_the_model_off(session, notes, status):  # noqa: F811
    saved(session, notes)
    with pytest.raises(HTTPException) as caught:
        _draft_email(session, "K-1")
    assert caught.value.status_code == status  # the model is off in tests unless the provider fixture is used
