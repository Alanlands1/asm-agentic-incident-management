"""Resolution agent: the answer schema and the steps the model takes (finish or search)."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ResolutionAnswer(BaseModel):
    verdict: Literal["resolved", "no_match"]
    root_cause: str | None = Field(None, description="The cause the runbook gives for this problem; null if no match")
    steps: list[str] = Field(default_factory=list, description="Resolution steps in the runbook's order; empty if no match")
    references: list[str] = Field(default_factory=list, description="KB ids of the excerpts used, e.g. KB-PAY-001")
    confidence: Literal["low", "medium", "high"]
    notes: str = Field("", description="Discrepancies with the ticket, the group to escalate to, anything the team must know")

    @model_validator(mode="after")
    def consistent(self) -> "ResolutionAnswer":
        if self.verdict == "resolved" and (not self.steps or not self.references):
            raise ValueError("a resolved answer needs steps and references")
        if self.verdict == "no_match" and (self.steps or self.references):
            raise ValueError("a no_match answer has no steps or references")
        return self


class ReActStep(BaseModel):
    thought: str = Field(description="One sentence: what you know and what you need next")
    action: Literal["search", "finish"]
    query: str | None = Field(None, description="For search: keywords, 2 to 10 words")
    answer: ResolutionAnswer | None = Field(None, description="For finish: the answer")

    @model_validator(mode="after")
    def payload_for_action(self) -> "ReActStep":
        if self.action == "search" and not (self.query and self.query.strip()):
            raise ValueError("a search needs a query")
        if self.action == "finish" and self.answer is None:
            raise ValueError("a finish needs an answer")
        return self


def unseen_references(answer: ResolutionAnswer, seen: set[str]) -> list[str]:
    """References the answer cites that no excerpt it was shown contains. Such citations are invented."""
    return [ref for ref in answer.references if ref not in seen]
