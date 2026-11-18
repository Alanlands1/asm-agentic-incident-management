"""The Triage agent's verdicts, shared by the rules stage and the model stage."""

from enum import StrEnum


class Verdict(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"
    UNCERTAIN = "uncertain"  # rules could not decide; the model stage runs if enabled

    @classmethod
    def of(cls, priority: int) -> "Verdict":
        return cls(f"P{priority}")
