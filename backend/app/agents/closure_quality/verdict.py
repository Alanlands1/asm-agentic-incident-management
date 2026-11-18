"""The Closure Quality agent's verdicts, shared by the rules stage and the model stage."""

from enum import StrEnum


class Verdict(StrEnum):
    NOT_APPLICABLE = "not_applicable"  # rules only: e.g. a test ticket, not scored
    NEEDS_WORK = "needs_work"  # rules or model
    UNCERTAIN = "uncertain"  # rules could not decide; the model stage runs if enabled
    GOOD = "good"  # model only: the rules never pass a note
