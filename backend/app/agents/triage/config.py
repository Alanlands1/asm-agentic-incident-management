"""Triage rulebook, loaded from the editable files in data/registry."""

import calendar
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from app.core.config import config_version
from app.core.registry import load_registry, register_document

SCOPES = ("single", "wide")


@dataclass(frozen=True)
class Raise:
    """Raises a rule's priority to `to` when all of its conditions hold."""
    to: int
    scope: str | None = None
    window: str | None = None
    context: tuple[re.Pattern, ...] = ()


@dataclass(frozen=True)
class Rule:
    name: str
    about: str
    match: tuple[re.Pattern, ...]
    priority: int
    kb: str | None = None
    raises: tuple[Raise, ...] = ()
    needs: tuple[str, ...] = ()  # facts that must be known before this rule can settle a ticket

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.match)


@dataclass(frozen=True)
class GenericRule:
    name: str
    about: str
    match: tuple[re.Pattern, ...]  # empty: only the model can choose it
    priority: dict[str, int]  # scope -> priority, for a Tier 1 application
    needs: tuple[str, ...] = ("scope",)

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.match)


@dataclass(frozen=True)
class MustFollow:
    """Applied last, after the ceiling. Fires on its own patterns, its rule, or a critical job; then its conditions."""
    name: str
    about: str
    priority: int
    match: tuple[re.Pattern, ...] = ()
    rule: str | None = None
    critical_job: bool = False
    scope: str | None = None
    window: str | None = None
    storm: bool = False  # fires for a ticket that belongs to a storm


@dataclass(frozen=True)
class Job:
    name: str
    app: str
    failed: re.Pattern  # a name of the job near a failure word
    criticality: str
    critical_in: str | None  # window name; None = always
    breaks: str


@dataclass(frozen=True)
class Application:
    tier: int
    ceiling: int  # most severe priority allowed
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class Window:
    from_day: int | None = None
    first_days: int = 0
    last_days: int = 0
    months: frozenset[int] = frozenset(range(1, 13))

    def contains(self, day: date) -> bool:
        month_end = calendar.monthrange(day.year, day.month)[1]
        return day.month in self.months and (
            (self.from_day is not None and day.day >= self.from_day)
            or day.day <= self.first_days
            or day.day > month_end - self.last_days
        )


@dataclass(frozen=True)
class TriageConfig:
    version: str  # hash of the rulebook and the job list; a change re-triages every ticket
    tone: tuple[re.Pattern, ...]
    wide: tuple[re.Pattern, ...]
    single: tuple[re.Pattern, ...]
    must_follow: tuple[MustFollow, ...]
    generic: tuple[GenericRule, ...]
    tier_offset: dict[int, int]
    default_tier: int  # model stage, when the application is unknown
    review_shift: int
    windows: dict[str, Window]
    jobs: tuple[Job, ...]
    applications: dict[str, Application]
    apps: dict[str, re.Pattern] = field(repr=False)  # application name -> any of its terms, for detection


def _patterns(patterns: list[str]) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.I) for p in patterns)


def _alternatives(terms: list[str]) -> str:
    return "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))


def _any_term(terms: list[str]) -> re.Pattern:
    return re.compile(rf"\b(?:{_alternatives(terms)})s?\b", re.I)


def _window(name: str | None, windows: dict) -> str | None:
    if name is not None and name not in windows:
        raise ValueError(f"Unknown window {name!r}")
    return name


def _rule(spec: dict, windows: dict[str, Window]) -> Rule:
    return Rule(
        name=spec["name"],
        about=spec["about"],
        match=_patterns(spec["match"]),
        priority=spec["priority"],
        kb=spec.get("kb"),
        raises=tuple(
            Raise(r["to"], r.get("scope"), _window(r.get("window"), windows), _patterns(r.get("context", [])))
            for r in spec.get("raise", [])
        ),
        needs=tuple(spec.get("needs", [])),
    )


def _job(name: str, spec: dict, failed: list[str], windows: dict[str, Window]) -> Job:
    names, words = _alternatives(spec["names"]), _alternatives(failed)
    pattern = re.compile(rf"\b(?:{names})\b.{{0,60}}\b(?:{words})\b|\b(?:{words})\b.{{0,60}}\b(?:{names})\b", re.I | re.S)
    return Job(name, spec["app"], pattern, spec["criticality"], _window(spec.get("critical_in"), windows), spec["breaks"])


def get_config() -> TriageConfig:
    return _build(config_version())


@lru_cache(maxsize=1)
def _build(version: int) -> TriageConfig:
    """Rebuilt when an admin changes the rulebook (the config version moves)."""
    book, jobs = load_registry("triage_rules.yaml"), load_registry("jobs.yaml")
    windows = {
        name: Window(w.get("from_day"), w.get("first_days", 0), w.get("last_days", 0), frozenset(w.get("months", range(1, 13))))
        for name, w in book["windows"].items()
    }
    applications = {
        name: Application(app["tier"], app.get("ceiling", 1), tuple(_rule(r, windows) for r in app["rules"]))
        for name, app in book["applications"].items()
    }
    rule_names = {r.name for app in applications.values() for r in app.rules}
    must_follow = tuple(
        MustFollow(m["name"], m["about"], m["priority"], _patterns(m.get("match", [])), m.get("rule"),
                   m.get("critical_job", False), m.get("scope"), _window(m.get("window"), windows), m.get("storm", False))
        for m in book["must_follow"]
    )
    if unknown := [m.rule for m in must_follow if m.rule and m.rule not in rule_names]:
        raise ValueError(f"must_follow refers to unknown rules: {unknown}")
    return TriageConfig(
        version=hashlib.sha256(json.dumps([book, jobs], sort_keys=True, default=str).encode()).hexdigest()[:12],
        tone=_patterns(book["tone"]),
        wide=_patterns(book["scope"]["wide"]),
        single=_patterns(book["scope"]["single"]),
        must_follow=must_follow,
        generic=tuple(
            GenericRule(g["name"], g["about"], _patterns(g.get("match", [])), {s: g["priority"][s] for s in SCOPES})
            for g in book["generic"]
        ),
        tier_offset={int(k): v for k, v in book["tier_offset"].items()},
        default_tier=book["default_tier"],
        review_shift=book["review_shift"],
        windows=windows,
        jobs=tuple(_job(name, spec, jobs["failed"], windows) for name, spec in jobs["jobs"].items()),
        applications=applications,
        apps={name: _any_term(app["names"] + app["keywords"]) for name, app in load_registry("apps.yaml").items()},
    )


register_document("triage_rules", "triage_rules.yaml", get_config)
register_document("triage_jobs", "jobs.yaml", get_config)
register_document("apps", "apps.yaml", get_config)  # application detection reads it too
