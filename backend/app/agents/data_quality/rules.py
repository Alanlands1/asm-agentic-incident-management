"""Rules stage of the Data Quality agent.

Rules only make decisions they are certain about. They can stop a ticket but never pass one:
anything not stopped here is left to the model.
"""

from dataclasses import dataclass

from app.agents.data_quality.config import get_config
from app.agents.data_quality.signals import Signals, compute_signals
from app.agents.data_quality.verdict import Verdict


@dataclass(frozen=True)
class RuleResult:
    verdict: Verdict
    rule: str | None
    reason: str
    signals: Signals


def evaluate(summary: str, body: str, attachments: str | None = None, application: str | None = None) -> RuleResult:
    """Apply the rules in order; the first one that fires decides."""
    config = get_config()
    signals = compute_signals(summary, body, attachments, application, config)

    if any(p.search(text) for p in config.test_ticket for text in (summary, body)):
        return RuleResult(Verdict.NOT_AN_INCIDENT, "test_ticket", "Looks like a test ticket", signals)

    if signals.placeholder_only:
        return RuleResult(Verdict.NEEDS_INFO, "placeholder", "Description is only a placeholder, no detail", signals)

    if signals.body_length < config.min_body_length:
        reason = (
            "Only an attachment, no description of the problem"
            if signals.attachment_only
            else f"Description too short to act on ({signals.body_length} characters)"
        )
        return RuleResult(Verdict.NEEDS_INFO, "near_empty", reason, signals)

    return RuleResult(Verdict.UNCERTAIN, None, "No rule applies; needs a completeness check by the model", signals)
