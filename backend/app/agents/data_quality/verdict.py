"""The Data Quality agent's verdicts, shared by the rules stage and the model stage."""

from enum import StrEnum


class Verdict(StrEnum):
    NOT_AN_INCIDENT = "not_an_incident"  # rules only
    NEEDS_INFO = "needs_info"  # rules or model
    UNCERTAIN = "uncertain"  # rules could not decide; the model stage runs if enabled
    PASSED = "passed"  # model only: the rules never pass a ticket
