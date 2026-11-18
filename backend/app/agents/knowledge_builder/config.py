"""Knowledge Builder settings, loaded from data/registry/knowledge.yaml."""

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import config_version
from app.core.registry import load_registry, register_document


@dataclass(frozen=True)
class KnowledgeConfig:
    version: str  # hash of the file; a change matches every case again
    min_score: float
    margin: float
    candidates: int
    stopwords: frozenset[str]
    draft_similar: float  # share of words a new gap must share with an open draft to join it
    problem_min_cases: int
    problem_window_days: int


def get_config() -> KnowledgeConfig:
    return _build(config_version())


@lru_cache(maxsize=1)
def _build(version: int) -> KnowledgeConfig:
    """Rebuilt when an admin changes the file (the config version moves)."""
    doc = load_registry("knowledge.yaml")
    config = KnowledgeConfig(
        version=hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()[:12],
        min_score=doc["match"]["min_score"],
        margin=doc["match"]["margin"],
        candidates=doc["match"]["candidates"],
        stopwords=frozenset(str(w).casefold() for w in doc["stopwords"]),
        draft_similar=doc["drafts"]["similar_text"],
        problem_min_cases=doc["problems"]["min_cases"],
        problem_window_days=doc["problems"]["window_days"],
    )
    if not 0 < config.min_score <= 1 or config.margin < 1 or config.candidates < 1:
        raise ValueError("match.min_score must be between 0 and 1, match.margin at least 1 and match.candidates at least 1")
    if not 0 < config.draft_similar <= 1 or config.problem_min_cases < 2 or config.problem_window_days < 1:
        raise ValueError(
            "drafts.similar_text must be between 0 and 1, problems.min_cases at least 2 and problems.window_days at least 1"
        )
    return config


register_document("knowledge", "knowledge.yaml", get_config)
