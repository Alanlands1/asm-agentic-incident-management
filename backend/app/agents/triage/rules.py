"""Rules stage of the Triage agent, and the priority calculation both stages share.

The rules settle a ticket only when a rule fits and every fact it needs is known, or a must-follow rule fires on
the text alone. Otherwise the model is asked for the missing facts once; the priority is always calculated here.
Order: the application's rule (or the generic table), the application's ceiling, then the must-follow rules,
so no ceiling can cap them. A fact that is still unknown leans high only when it could make the ticket P1/P2.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.agents.triage.config import GenericRule, MustFollow, Raise, Rule, TriageConfig, get_config
from app.agents.triage.signals import Signals, clean_text, compute_signals
from app.agents.triage.verdict import Verdict

KNOWN_SCOPES = ("single", "wide")


@dataclass(frozen=True)
class Facts:
    """What a priority is decided from: found by the rules stage, or completed by the model."""
    application: str | None
    scope: str  # single, wide, or unknown / mixed
    windows: tuple[str, ...]
    failed_jobs: tuple[str, ...]
    context: Callable[[Raise], bool]  # whether a raise's business context holds
    in_storm: bool = False  # the ticket belongs to a storm


@dataclass(frozen=True)
class Decision:
    priority: int
    rule: str
    reason: str
    must_follow: str | None = None
    leaned_high: bool = False  # an unknown scope was counted as wide because that could make it P1/P2
    kept_reported: bool = False  # no rulebook for the application, so the reporter's priority stands


@dataclass(frozen=True)
class RuleResult:
    verdict: Verdict
    decision: Decision | None  # None when uncertain
    reason: str
    signals: Signals
    missing: tuple[str, ...] = ()  # facts the model is asked for
    fallback: Decision | None = None  # the rules' own answer, leaning high, for when the model cannot help

    @property
    def priority(self) -> int | None:
        return self.decision.priority if self.decision else None


def choosable(config: TriageConfig, application: str | None) -> list[Rule | GenericRule | MustFollow]:
    """Rules the model may pick: text-only must-follow rules, the application's rules, the generic rules."""
    app = config.applications.get(application) if application else None
    return [*(m for m in config.must_follow if m.match), *(app.rules if app else ()), *config.generic]


def find_rule(config: TriageConfig, application: str | None, name: str) -> Rule | GenericRule | MustFollow | None:
    return next((r for r in choosable(config, application) if r.name == name), None)


def _critical_job_failed(facts: Facts, config: TriageConfig) -> bool:
    return any(
        j.name in facts.failed_jobs and j.criticality == "critical" and (j.critical_in is None or j.critical_in in facts.windows)
        for j in config.jobs
    )


def _must_follow(rule: str | None, scope: str, facts: Facts, text: str, config: TriageConfig) -> MustFollow | None:
    fired = [
        m for m in config.must_follow
        if (m.name == rule or (m.rule is not None and m.rule == rule) or any(p.search(text) for p in m.match)
            or (m.critical_job and _critical_job_failed(facts, config)) or (m.storm and facts.in_storm))
        and (m.scope is None or m.scope == scope) and (m.window is None or m.window in facts.windows)
    ]
    return min(fired, key=lambda m: m.priority) if fired else None


def _holds(r: Raise, scope: str, facts: Facts) -> bool:
    """Every condition the raise sets must hold."""
    return (r.scope is None or r.scope == scope) and (r.window is None or r.window in facts.windows) and (
        not r.context or facts.context(r)
    )


def _score(rule, scope: str, facts: Facts, text: str, config: TriageConfig) -> tuple[int | None, str, MustFollow | None]:
    """Priority for a known scope, in the rulebook's order. None when neither a rule nor a must-follow applies."""
    app = config.applications.get(facts.application) if facts.application else None
    priority, reason = None, ""
    if isinstance(rule, MustFollow):
        priority, reason = rule.priority, rule.about
    elif isinstance(rule, GenericRule):
        tier = app.tier if app else config.default_tier
        priority = min(5, rule.priority[scope] + config.tier_offset[tier])
        reason = f"{rule.about}; {scope} impact, Tier {tier}: P{priority}"
    elif isinstance(rule, Rule):
        priority, reason = rule.priority, f"{rule.about}{f' ({rule.kb})' if rule.kb else ''}: P{rule.priority}"
        if (raised := next((r for r in rule.raises if _holds(r, scope, facts)), None)) and raised.to < priority:
            priority = raised.to
            why = [*(["wide impact"] if raised.scope else []), *([raised.window] if raised.window else []),
                   *(["business context"] if raised.context else [])]
            reason += f", raised to P{priority} ({' + '.join(why)})"
    if priority is not None and app and priority < app.ceiling and not isinstance(rule, MustFollow):
        priority = app.ceiling
        reason += f", capped at P{priority} for {facts.application}"

    must = _must_follow(rule.name if rule else None, scope, facts, text, config)
    if must and must is not rule and must.priority != priority:
        priority = must.priority
        reason = f"{reason + '; ' if reason else ''}must-follow {must.name}: {must.about}, P{priority}"
    return priority, reason, must


def decide(rule, facts: Facts, text: str, config: TriageConfig) -> Decision | None:
    """The priority for `rule` (or for the must-follow rules alone when rule is None). Leans high on an unknown scope."""
    leaned = False
    if facts.scope in KNOWN_SCOPES:
        priority, reason, must = _score(rule, facts.scope, facts, text, config)
    else:
        wide, single = _score(rule, "wide", facts, text, config), _score(rule, "single", facts, text, config)
        leaned = wide[0] is not None and wide[0] <= 2 and wide[0] != single[0]
        priority, reason, must = wide if leaned else single
        if wide[0] != single[0]:
            reason += f"; how many are affected is {facts.scope}, counted as {'many: it could be P1/P2' if leaned else 'one'}"
    if priority is None:
        return None
    name = rule.name if rule else must.name
    return Decision(priority, name, reason, must.name if must else None, leaned)


def without_rulebook(decision: Decision, reported: int | None) -> Decision:
    """An application outside the rulebook gives no basis to change the reporter's priority; must-follow rules still win."""
    if decision.must_follow or reported is None or reported == decision.priority:
        return decision
    reason = f"Application not in the rulebook: the reporter's P{reported} is kept (the rules would give P{decision.priority})"
    return Decision(reported, decision.rule, reason, kept_reported=True)


def evaluate(summary: str, body: str, application: str | None = None, opened_at=None, in_storm: bool = False) -> RuleResult:
    """The application's rules (the most severe match wins), else the first generic rule that matches."""
    config = get_config()
    signals = compute_signals(summary, body, application, opened_at, config)
    text = clean_text(summary, body, config)
    facts = Facts(signals.application, signals.scope, signals.windows, signals.failed_jobs,
                  lambda r: any(p.search(text) for p in r.context), in_storm)

    app = config.applications.get(signals.application) if signals.application else None
    hits = [r for r in app.rules if r.matches(text)] if app else []
    if app and not hits:
        hits = [g for g in config.generic if g.matches(text)][:1]
    scored = [(d, r) for r in (hits or [None]) if (d := decide(r, facts, text, config))]
    if not scored:
        reason = f"No {signals.application} rule or generic rule matches" if app else "Application unknown or not in the rulebook"
        return RuleResult(Verdict.UNCERTAIN, None, reason, signals)

    decision, rule = min(scored, key=lambda s: s[0].priority)
    must = next((m for m in config.must_follow if m.name == decision.must_follow), None)
    settled_by_text = must is not None and must.scope is None and (bool(must.match) or must.critical_job or must.storm)
    missing = tuple(
        n for n in (rule.needs if rule else ())
        if n == "scope" and signals.scope not in KNOWN_SCOPES  # and it changes the answer
        and _score(rule, "wide", facts, text, config)[0] != _score(rule, "single", facts, text, config)[0]
    )
    if missing and not settled_by_text:
        return RuleResult(Verdict.UNCERTAIN, None, f"Rule {rule.name} needs {', '.join(missing)}; it is {signals.scope}",
                          signals, missing, fallback=decision)
    return RuleResult(Verdict.of(decision.priority), decision, decision.reason, signals)
