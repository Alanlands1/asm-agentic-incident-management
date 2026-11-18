"""Closure Quality settings, loaded from data/registry/closure_rules.yaml."""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import config_version
from app.core.registry import load_registry, register_document

PARTS = ("cause", "action", "check")


@dataclass(frozen=True)
class ClosureConfig:
    version: str  # hash of the rules file; a change re-checks every ticket
    min_length: int
    filler: frozenset[str]  # normalised, see normalise()
    test_ticket: tuple[re.Pattern, ...]
    similar_to_description: float
    min_action: int  # 0 none, 1 vague, 2 specific
    min_total: int  # of 6
    kb_citation_is_cause: bool  # a cited, existing KB article stands in for the cause when the action is specific
    questions: dict[str, str]


def normalise(text: str) -> str:
    """Lower-case letters, digits and single spaces only: 'N/A.' -> 'na'."""
    return " ".join(re.sub(r"[^a-z0-9 ]", "", text.casefold()).split())


def get_config() -> ClosureConfig:
    return _build(config_version())


@lru_cache(maxsize=1)
def _build(version: int) -> ClosureConfig:
    """Rebuilt when an admin changes the rules (the config version moves)."""
    doc = load_registry("closure_rules.yaml")
    config = ClosureConfig(
        version=hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()[:12],
        min_length=doc["min_length"],
        filler=frozenset(normalise(f) for f in doc["filler"]) - {""},
        test_ticket=tuple(re.compile(p, re.I) for p in doc["test_ticket"]),
        similar_to_description=doc["similar_to_description"],
        min_action=doc["pass"]["min_action"],
        min_total=doc["pass"]["min_total"],
        kb_citation_is_cause=bool(doc["kb_citation_is_cause"]),
        questions={part: doc["questions"][part] for part in PARTS},
    )
    if config.min_length < 1 or not 0 < config.similar_to_description <= 1:
        raise ValueError("min_length must be at least 1 and similar_to_description between 0 and 1")
    if not 0 <= config.min_action <= 2 or not 0 <= config.min_total <= 6:
        raise ValueError("pass.min_action must be 0..2 and pass.min_total 0..6")
    return config


register_document("closure_rules", "closure_rules.yaml", get_config)
