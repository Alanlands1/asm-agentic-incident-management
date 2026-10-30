import pytest

from app.common.privacy.masking import MaskedText, Masker, UnknownPlaceholderError

TICKET = (
    "Hi, this is Priya Raman (E48213) from the Pune site. PayrollPro shows ORA-01555 on INV-2026-91226 since Monday 09:30. "
    "Call +91 98765 43210 or priya.raman@contoso.com. Ravi Kumar is also affected; job PAY_CALC_MONTHLY failed on "
    "pay-db-01.contoso.local.\n\nThanks,\nPriya"
)


@pytest.fixture
def masker():
    return Masker(known_names=["Priya Raman"], known_emails=["priya.raman@contoso.com"])


def test_masks_people_contacts_ids_sites_apps_codes_and_hosts(masker):
    masked = masker.mask(TICKET)
    assert isinstance(masked, MaskedText)
    for secret in ["Priya", "Raman", "E48213", "Pune", "PayrollPro", "ORA-01555", "INV-2026-91226", "98765", "contoso", "Ravi", "PAY_CALC"]:
        assert secret not in masked, secret
    assert "Monday 09:30" in masked  # agents need dates and times


def test_same_person_and_app_keep_one_placeholder(masker):
    masked = masker.mask(TICKET)
    assert masked.count("<PERSON_1>") == 2  # full name and signature first name
    assert "<PERSON_2>" in masked  # someone else
    assert masker.mask("Payroll Pro is down again") == "<APP_1> is down again"  # same app, same call


def test_generic_words_are_kept(masker):
    text = "The order report shows top-10 items and the payroll dashboard is slow."
    assert masker.mask(text) == text
    assert masker.mask("Hi,\n\nScanner not working at my station.") == "Hi,\n\nScanner not working at my station."


def test_ticket_without_reporter_name_is_still_masked():
    """Mailbox tickets can arrive with no sender name; NER still has to find people in the text."""
    masked = Masker(known_names=[None, " "]).mask("Ravi Kumar says PayrollPro is down")
    assert masked == "<PERSON_1> says <APP_1> is down"


def test_signature_department_is_not_part_of_the_name():
    masked = Masker(known_names=["Ravi Shankar"]).mask("Thanks,\nRavi Shankar\nWarehouse - Chennai")
    assert masked == "Thanks,\n<PERSON_1>\nWarehouse - <LOCATION_1>"


def test_unmask_restores_values_and_rejects_invented_placeholders(masker):
    masked = masker.mask("Priya Raman cannot open PayrollPro.")
    assert masker.unmask(f"Hi {masked.split()[0]}, which <APP_1> screen fails?") == "Hi Priya Raman, which PayrollPro screen fails?"
    with pytest.raises(UnknownPlaceholderError):
        masker.unmask("Please ask <PERSON_9>")
