"""Model stage of the Triage agent: the facts the rules could not find, each backed by a quote from the ticket.

The model never sets the priority. It picks a rule from the rulebook and reports how many are affected and whether
the business context applies; rules.decide() turns that into the priority, exactly as for the rules stage.
It also reports the impact on three pillars (regulatory, financial, system), shown to the engineer beside the priority.
A fact or impact level whose quote is not really in the ticket goes back to unknown or none (see verified()).
The prompt text comes from data/registry/prompts.yaml, the rulebook inside it from triage_rules.yaml and jobs.yaml.
"""

import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.agents.triage.config import MustFollow, Raise, TriageConfig, get_config
from app.agents.triage.rules import RuleResult, find_rule
from app.core.config import config_version
from app.core.registry import load_registry, register_document
from app.llm import CallAudit, CallSpec, call_model
from app.models.ticket import Ticket
from app.privacy.masking import Masker

TRIAGE_PROMPT_NAME = "triage_priority"  # the entry in prompts.yaml
MIN_QUOTE = 8  # characters; shorter quotes ("my", "all") prove nothing
PILLARS = ("regulatory", "financial", "system")

ImpactLevel = Literal["none", "low", "medium", "high"]


class TriageAssessment(BaseModel):
    application: str | None = Field(description="The affected application from the rulebook, or null if none applies")
    rule: str = Field(description="The best-fitting rule: a must-follow rule, a rule of that application, or a generic rule")
    scope: Literal["single", "wide", "unknown"] = Field(description="How many are affected")
    scope_quote: str | None = Field(description="Exact words from the ticket that show the scope; null when unknown")
    context_applies: bool = Field(description="Whether the business context in the rule's 'raised when' note is described")
    context_quote: str | None = Field(description="Exact words from the ticket that show that context; null if it does not apply")
    regulatory_impact: ImpactLevel = Field(description="A legal, compliance, audit or statutory obligation at risk")
    regulatory_quote: str | None = Field(description="Exact words from the ticket that show it; null when none")
    financial_impact: ImpactLevel = Field(description="Money lost, delayed or wrong")
    financial_quote: str | None = Field(description="Exact words from the ticket that show it; null when none")
    system_impact: ImpactLevel = Field(description="How much of the service is not working")
    system_quote: str | None = Field(description="Exact words from the ticket that show it; null when none")
    reason: str = Field(description="One or two sentences for the support team")

    @model_validator(mode="after")
    def in_rulebook(self) -> "TriageAssessment":
        config = get_config()
        if self.application is not None and self.application not in config.applications:
            raise ValueError(f"application {self.application!r} is not in the rulebook")
        if find_rule(config, self.application, self.rule) is None:
            raise ValueError(f"rule {self.rule!r} is not a must-follow rule, a generic rule or a rule of {self.application}")
        return self


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def _quoted(quote: str | None, ticket_text: str) -> bool:
    return bool(quote) and len(quote.strip()) >= MIN_QUOTE and _normal(quote) in _normal(ticket_text)


def verified(answer: TriageAssessment, ticket_text: str) -> tuple[TriageAssessment, list[str]]:
    """Facts without a real quote from the ticket go back to unknown, impact levels to none.
    Returns the checked answer and what was dropped."""
    update, dropped = {}, []
    if answer.scope != "unknown" and not _quoted(answer.scope_quote, ticket_text):
        update["scope"], dropped = "unknown", [*dropped, "scope"]
    if answer.context_applies and not _quoted(answer.context_quote, ticket_text):
        update["context_applies"], dropped = False, [*dropped, "context"]
    for pillar in PILLARS:
        if getattr(answer, f"{pillar}_impact") != "none" and not _quoted(getattr(answer, f"{pillar}_quote"), ticket_text):
            update[f"{pillar}_impact"], update[f"{pillar}_quote"], dropped = "none", None, [*dropped, f"{pillar}_impact"]
    return answer.model_copy(update=update), dropped


def impact(answer: TriageAssessment) -> dict[str, dict[str, str | None]]:
    """The three pillars as stored on the run and shown to the engineer."""
    return {p: {"level": getattr(answer, f"{p}_impact"), "quote": getattr(answer, f"{p}_quote")} for p in PILLARS}


def _readable(pattern: re.Pattern) -> str:
    return pattern.pattern.replace(r"\b", "").replace("\\", "")


def _when(r: Raise) -> str:
    parts = [*(["wide impact"] if r.scope else []), *([f"in the {r.window}"] if r.window else []),
             *([f"the ticket mentions {' or '.join(map(_readable, r.context))}"] if r.context else [])]
    return " and ".join(parts)


def _must_follow_line(m: MustFollow) -> str:
    when = [*([f"rule {m.rule} applies"] if m.rule else []),
            *(["a critical batch job failed in its window"] if m.critical_job else []),
            *(["the ticket belongs to a storm"] if m.storm else []),
            *(["wide impact"] if m.scope else []), *([f"in the {m.window}"] if m.window else [])]
    pick = " You may choose it as the rule." if m.match else ""
    return f"- {m.name}: {m.about}. P{m.priority}{' when ' + ' and '.join(when) if when else ''}.{pick}"


def render_rulebook(config: TriageConfig) -> str:
    """The rulebook as the model reads it. Priorities are shown so the model understands what each rule means."""
    lines = ["Must-follow rules, applied last by the code:"]
    lines += [_must_follow_line(m) for m in config.must_follow]
    offsets = ", ".join(f"Tier {tier} by {n}" for tier, n in config.tier_offset.items() if n)
    lines += ["", f"Generic rules, when no application rule fits (P for single / wide impact at Tier 1; "
              f"lower tiers move down: {offsets}):"]
    lines += [f"- {g.name}: {g.about}. P{g.priority['single']} / P{g.priority['wide']}" for g in config.generic]
    for name, app in config.applications.items():
        ceiling = f", never above P{app.ceiling}" if app.ceiling > 1 else ""
        lines += ["", f"{name} (Tier {app.tier}{ceiling}):"]
        lines += [f"- {r.name}: {r.about}. P{r.priority}" + "".join(f"; raised to P{x.to} when {_when(x)}" for x in r.raises)
                  for r in app.rules]
    lines += ["", "Batch jobs:"]
    lines += [f"- {j.name} ({j.app}): {j.criticality}{f' in the {j.critical_in}' if j.critical_in else ''}; breaks {j.breaks}"
              for j in config.jobs]
    return "\n".join(lines)


def triage_priority_spec() -> CallSpec[TriageAssessment]:
    return _build_spec(config_version())


@lru_cache(maxsize=1)
def _build_spec(version: int) -> CallSpec[TriageAssessment]:
    """The call as configured now; rebuilt after an admin change to the prompt or the rulebook."""
    prompt = load_registry("prompts.yaml")[TRIAGE_PROMPT_NAME]
    return CallSpec(
        name=TRIAGE_PROMPT_NAME,
        prompt_version=prompt["version"],
        system=prompt["system"].format(rulebook=render_rulebook(get_config())),
        output=TriageAssessment,
        wrapper=prompt["wrapper"],
        retry_note=prompt["retry_note"],
        max_tokens=prompt["max_tokens"],
        agent="triage",
    )


register_document("data_quality_prompts", "prompts.yaml", triage_priority_spec)  # one prompts file for every call
register_document("triage_rules", "triage_rules.yaml", triage_priority_spec)
register_document("triage_jobs", "jobs.yaml", triage_priority_spec)


def assess_priority(ticket: Ticket, body: str, rules: RuleResult) -> tuple[TriageAssessment, CallAudit]:
    """One model call on the masked ticket. Raises app.llm.ModelError when there is no usable answer."""
    prompt = load_registry("prompts.yaml")[TRIAGE_PROMPT_NAME]
    s, none = rules.signals, prompt["not_given"]
    masker = Masker(known_names=[ticket.reporter_name, ticket.assignee], known_emails=[ticket.reporter_email])
    text = prompt["ticket_template"].format(
        application=s.application or none,
        candidate=(rules.decision or rules.fallback).rule if rules.decision or rules.fallback else none,
        missing=", ".join(rules.missing) or none,
        windows=", ".join(s.windows) or none,
        failed_jobs=", ".join(s.failed_jobs) or none,
        summary=ticket.summary,
        body=body,
    )
    return call_model(triage_priority_spec(), masker.mask(text), masker)
