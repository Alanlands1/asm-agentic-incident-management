"""Data Quality settings, loaded once from the editable files in data/registry."""

import re
from dataclasses import dataclass
from functools import lru_cache

from app.common.config import config_version
from app.common.registry import load_registry, register_document


@dataclass(frozen=True)
class DQConfig:
    min_body_length: int
    placeholder: frozenset[str]  # normalised, see normalise()
    filler: tuple[re.Pattern, ...]
    test_ticket: tuple[re.Pattern, ...]
    ticket_reference: re.Pattern
    previous_ticket: tuple[re.Pattern, ...]
    identifier: tuple[re.Pattern, ...]
    apps: dict[str, re.Pattern]  # application name -> any of its terms


def normalise(text: str) -> str:
    """Lower-case letters, digits and single spaces only: 'N/A.' -> 'na'."""
    return " ".join(re.sub(r"[^a-z0-9 ]", "", text.casefold()).split())


def _any_term(terms: list[str]) -> re.Pattern:
    alternatives = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternatives})s?\b", re.I)


def get_config() -> DQConfig:
    return _build(config_version())


@lru_cache(maxsize=1)
def _build(version: int) -> DQConfig:
    """Rebuilt when an admin changes the rules (the config version moves)."""
    rules = load_registry("data_quality/rules.yaml")
    return DQConfig(
        min_body_length=rules["min_body_length"],
        placeholder=frozenset(normalise(p) for p in rules["placeholder"]) - {""},
        filler=tuple(re.compile(p, re.I) for p in rules["filler"]),
        test_ticket=tuple(re.compile(p, re.I) for p in rules["test_ticket"]),
        ticket_reference=re.compile(rules["ticket_reference"]),
        previous_ticket=tuple(re.compile(p, re.I) for p in rules["previous_ticket"]),
        identifier=tuple(re.compile(p) for p in rules["identifier"]),
        apps={name: _any_term(app["names"] + app["keywords"]) for name, app in load_registry("common/apps.yaml").items()},
    )


register_document("data_quality_rules", "data_quality/rules.yaml", get_config)
register_document("apps", "common/apps.yaml", get_config)  # the rules read application names too
