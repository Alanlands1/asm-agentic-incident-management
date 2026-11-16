import pytest

from app.privacy.masking import MaskedText, Masker, UnknownPlaceholderError

TICKET = (
    "Hi, this is Priya Raman (E48213) from the Pune site. PayrollPro shows ORA-01555 on INV-2026-91226 since Monday 09:30. "
    "Call +91 98765 43210 or priya.raman@contoso.com. Ravi Kumar is also affected; job PAY_CALC_MONTHLY failed on "
    "pay-db-01.contoso.local.\n\nThanks,\nPriya"
)


@pytest.fixture
def masker():
    return Masker(known_names=["Priya Raman"], known_emails=["priya.raman@contoso.com"])


def test_masks_personal_information(masker):
    masked = masker.mask(TICKET)
    assert isinstance(masked, MaskedText)
    for secret in ["Priya", "Raman", "E48213", "98765", "priya.raman@", "Ravi"]:
        assert secret not in masked, secret


def test_keeps_apps_codes_sites_hosts_and_dates(masker):
    masked = masker.mask(TICKET)
    for kept in ["PayrollPro", "ORA-01555", "INV-2026-91226", "PAY_CALC_MONTHLY", "Pune", "pay-db-01.contoso.local", "Monday 09:30"]:
        assert kept in masked, kept
    assert masker.mask("Fixed as per KB-BI-003 in InsightBI.") == "Fixed as per KB-BI-003 in InsightBI."


def test_same_person_keeps_one_placeholder(masker):
    masked = masker.mask(TICKET)
    assert masked.count("<PERSON_1>") == 2  # full name and signature first name
    assert "<PERSON_2>" in masked  # someone else


def test_shared_first_name_is_masked_but_not_linked():
    masker = Masker(known_names=["Ravi Shankar", "Ravi Kumar"])
    assert masker.mask("Thanks, Ravi") == "Thanks, <PERSON_1>"
    assert masker.mask("Ravi Shankar and Ravi Kumar") == "<PERSON_2> and <PERSON_3>"


def test_unknown_full_name_is_not_split_into_known_people():
    masked = Masker(known_names=["Ravi Shankar", "Deepak Kumar"]).mask("My manager Ravi Kumar approved it.")
    assert masked == "My manager <PERSON_1> approved it."


def test_system_accounts_and_generic_words_are_kept(masker):
    assert Masker(known_names=["Service Desk"]).mask("Logged by Service Desk") == "Logged by Service Desk"
    text = "The order report shows top-10 items and the payroll dashboard is slow."
    assert masker.mask(text) == text
    assert masker.mask("Hi,\n\nScanner not working at my station.") == "Hi,\n\nScanner not working at my station."


def test_ticket_without_reporter_name_is_still_masked():
    """Mailbox tickets can arrive with no sender name; NER still has to find people in the text."""
    masked = Masker(known_names=[None, " "]).mask("Ravi Kumar says PayrollPro is down")
    assert masked == "<PERSON_1> says PayrollPro is down"


def test_signature_department_is_not_part_of_the_name():
    masked = Masker(known_names=["Ravi Shankar"]).mask("Thanks,\nRavi Shankar\nWarehouse - Chennai")
    assert masked == "Thanks,\n<PERSON_1>\nWarehouse - Chennai"


def test_unmask_restores_values_and_rejects_invented_placeholders(masker):
    masked = masker.mask("Priya Raman cannot open PayrollPro.")
    assert masker.unmask(f"Hi {masked.split()[0]}, which PayrollPro screen fails?") == "Hi Priya Raman, which PayrollPro screen fails?"
    with pytest.raises(UnknownPlaceholderError):
        masker.unmask("Please ask <PERSON_9>")


def test_numbering_starts_after_the_placeholders_in_the_texts_it_sits_beside():
    masker = Masker(beside=["<PERSON_1> cannot log in.", "Ask <PERSON_2>.", None])
    assert str(masker.mask("Also ask Vinay Sharma.")) == "Also ask <PERSON_3>."
