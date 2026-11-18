"""Unit tests for DQ rule evaluation service and operators."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models.dq import DQRule, DQRun, DQRunTicket
from app.models.servicenow import ServiceNowTicket
from app.services.dq import evaluate_operator, ticket_matches_rule, execute_dq_run, revert_dq_run


def test_evaluate_operator_equals():
    assert evaluate_operator("equals", "Test", "test") is True
    assert evaluate_operator("equals", "  value  ", "value") is True
    assert evaluate_operator("equals", "value1", "value2") is False
    assert evaluate_operator("equals", None, "") is True


def test_evaluate_operator_not_equals():
    assert evaluate_operator("not_equals", "Test", "other") is True
    assert evaluate_operator("not_equals", "Test", "test") is False


def test_evaluate_operator_contains():
    assert evaluate_operator("contains", "Incident description", "desc") is True
    assert evaluate_operator("contains", "Incident description", "XYZ") is False
    assert evaluate_operator("contains", None, "abc") is False


def test_evaluate_operator_not_contains():
    assert evaluate_operator("not_contains", "Sample text", "XYZ") is True
    assert evaluate_operator("not_contains", "Sample text", "sample") is False


def test_evaluate_operator_starts_with():
    assert evaluate_operator("starts_with", "INC123456", "inc") is True
    assert evaluate_operator("starts_with", "INC123456", "123") is False


def test_evaluate_operator_regex():
    assert evaluate_operator("regex", "INC0012345", r"^INC\d+$") is True
    assert evaluate_operator("regex", "INVALID", r"^INC\d+$") is False
    # Malformed regex handles error gracefully
    assert evaluate_operator("regex", "test", "[unclosed") is False


def test_evaluate_operator_empty_and_not_empty():
    assert evaluate_operator("is_empty", None, None) is True
    assert evaluate_operator("is_empty", "   ", None) is True
    assert evaluate_operator("is_empty", "not empty", None) is False

    assert evaluate_operator("is_not_empty", "hello", None) is True
    assert evaluate_operator("is_not_empty", None, None) is False
    assert evaluate_operator("is_not_empty", "   ", None) is False


def test_evaluate_operator_length():
    assert evaluate_operator("length_lt", "short", "10") is True
    assert evaluate_operator("length_lt", "very long text string", "5") is False
    assert evaluate_operator("length_lt", "text", "invalid_num") is False

    assert evaluate_operator("length_gt", "very long text string", "5") is True
    assert evaluate_operator("length_gt", "short", "10") is False


def test_ticket_matches_rule():
    ticket = ServiceNowTicket(
        ticket_id="INC001",
        short_description="test ticket",
        service="Payment Gateway",
    )

    # Matching rule
    rule_match = DQRule(
        name="Test flag",
        source="ServiceNow",
        service="Payment Gateway",
        field="short_description",
        operator="contains",
        value="test",
        is_enabled=True,
    )
    assert ticket_matches_rule(rule_match, ticket) is True

    # Mismatched service
    rule_diff_service = DQRule(
        name="Other Service",
        source="ServiceNow",
        service="Identity Management",
        field="short_description",
        operator="contains",
        value="test",
        is_enabled=True,
    )
    assert ticket_matches_rule(rule_diff_service, ticket) is False

    # Mismatched source
    rule_diff_source = DQRule(
        name="JIRA only",
        source="JIRA",
        field="short_description",
        operator="contains",
        value="test",
        is_enabled=True,
    )
    assert ticket_matches_rule(rule_diff_source, ticket) is False

    # Nonexistent field on ticket
    rule_invalid_field = DQRule(
        name="Bad field",
        field="non_existent_column",
        operator="equals",
        value="test",
        is_enabled=True,
    )
    assert ticket_matches_rule(rule_invalid_field, ticket) is False


@pytest.mark.asyncio
async def test_execute_dq_run_first_match_wins():
    rule1 = DQRule(
        id=1,
        name="Rule 1",
        field="short_description",
        operator="contains",
        value="test",
        is_enabled=True,
        apply_to="both",
    )
    rule2 = DQRule(
        id=2,
        name="Rule 2",
        field="short_description",
        operator="is_not_empty",
        is_enabled=True,
        apply_to="both",
    )

    ticket = ServiceNowTicket(
        ticket_id="INC100",
        short_description="this is a test",
        dq_flag=False,
        dq_reason=None,
    )

    mock_db = AsyncMock()

    rule_result = MagicMock()
    rule_result.all.return_value = [rule1, rule2]

    ticket_result = MagicMock()
    ticket_result.all.return_value = [ticket]

    mock_db.scalars.side_effect = [rule_result, ticket_result]

    run = await execute_dq_run(mock_db, scope="both", trigger="manual")

    assert run.tickets_evaluated == 1
    assert run.tickets_flagged == 1
    # Ticket flagged by first matching rule
    assert ticket.dq_flag is True
    assert ticket.dq_reason == "Rule 1"
    assert mock_db.commit.called
