"""Rules stage of the Closure Quality agent.

Rules only make decisions they are certain about. They can stop a note but never pass one:
anything not stopped here is left to the model.
"""

import re
from dataclasses import dataclass

from app.agents.closure_quality.config import get_config, normalise
from app.agents.closure_quality.verdict import Verdict

WORDS = re.compile(r"[a-z0-9]{3,}")
MIN_WORDS = 4  # fewer words than this cannot be judged a copy


@dataclass(frozen=True)
class RuleResult:
    verdict: Verdict
    rule: str | None
    reason: str


def _copy_share(notes: str, problem: str) -> float:
    """Share of the notes' words that are already in the problem text."""
    words = set(WORDS.findall(notes.casefold()))
    return len(words & set(WORDS.findall(problem.casefold()))) / len(words) if len(words) >= MIN_WORDS else 0.0


def evaluate(notes: str | None, summary: str, description: str) -> RuleResult:
    """Apply the rules in order; the first one that fires decides."""
    config, text = get_config(), " ".join((notes or "").split())

    if any(p.search(summary) or p.search(text) for p in config.test_ticket):
        return RuleResult(Verdict.NOT_APPLICABLE, "test_ticket", "Looks like a test ticket, not scored")
    if not text:
        return RuleResult(Verdict.NEEDS_WORK, "empty", "No close notes")
    if normalise(text) in config.filler:
        return RuleResult(Verdict.NEEDS_WORK, "filler", "The notes are only a filler word, no detail")
    if len(text) < config.min_length:
        return RuleResult(Verdict.NEEDS_WORK, "too_short", f"Notes too short to learn from ({len(text)} characters)")
    if _copy_share(text, f"{summary} {description}") >= config.similar_to_description:
        return RuleResult(Verdict.NEEDS_WORK, "copy_of_description", "The notes repeat the problem, not the fix")

    return RuleResult(Verdict.UNCERTAIN, None, "No rule applies; needs a quality check by the model")
