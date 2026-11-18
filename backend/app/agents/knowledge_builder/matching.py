"""Rules stage of the Knowledge Builder: match a resolved ticket to an article without a model.

Order: an article the notes cite, then an error code or job name shared with one article, then word overlap.
The rules can say "matched" or "not sure". They never say that no article covers a case: only the model can.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from app.agents.knowledge_builder.articles import Article, articles, articles_version, codes
from app.agents.knowledge_builder.config import get_config

TOKEN = re.compile(r"[a-z0-9]{3,}")
KB_ID = re.compile(r"\bKB-[A-Z]+-\d+\b")


@dataclass(frozen=True)
class RuleMatch:
    status: str  # matched | uncertain
    article: str | None
    method: str | None  # cited | code | keywords
    reason: str
    ranking: tuple[tuple[str, float], ...]  # (article id, word-overlap score), best first: what the model is shown


def _tokens(text: str, stop: frozenset[str]) -> list[str]:
    return [t for t in TOKEN.findall(text.casefold()) if t not in stop]


def _vector(counts: Counter, idf: dict[str, float]) -> dict[str, float]:
    """Unit-length word weights: rarer words count for more. Words in no article are ignored."""
    weights = {t: (1 + math.log(c)) * idf[t] for t, c in counts.items() if t in idf}
    norm = math.sqrt(sum(w * w for w in weights.values()))
    return {t: w / norm for t, w in weights.items()} if norm else {}


@lru_cache(maxsize=2)
def _index(version: str, stop: frozenset[str]) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Word weights across all articles, and each article as a vector. Rebuilt when an article changes."""
    docs = {a.kb_id: Counter(_tokens(a.content, stop)) for a in articles().values()}
    frequency = Counter(t for counts in docs.values() for t in counts)
    idf = {t: math.log((len(docs) + 1) / (n + 1)) + 1 for t, n in frequency.items()}
    return idf, {kb: _vector(counts, idf) for kb, counts in docs.items()}


def known_application(application: str | None) -> str | None:
    return application if application in {a.app for a in articles().values()} else None


def rank(text: str, application: str | None) -> list[tuple[Article, float]]:
    """Articles of the application (all articles if it is unknown), best word overlap first."""
    config = get_config()
    idf, vectors = _index(articles_version(), config.stopwords)
    case = _vector(Counter(_tokens(text, config.stopwords)), idf)
    scored = [(a, sum(w * vectors[a.kb_id].get(t, 0.0) for t, w in case.items()))
              for a in articles().values() if application in (None, a.app)]
    return sorted(scored, key=lambda s: (-s[1], s[0].kb_id))


def evaluate(summary: str, description: str, notes: str | None, application: str | None) -> RuleMatch:
    """Apply the rules in order; the first one that is sure decides."""
    config, known = get_config(), articles()
    app = known_application(application)
    text = f"{summary}\n{description}\n{notes or ''}"
    ranked = rank(text, app)
    ranking = tuple((a.kb_id, round(score, 3)) for a, score in ranked)

    cited = sorted(set(KB_ID.findall(notes or "")) & known.keys())
    if len(cited) > 1:
        return RuleMatch("uncertain", None, None, f"The notes cite several articles ({', '.join(cited)})", ranking)
    if cited:
        if app and known[cited[0]].app != app:
            reason = f"The notes cite {cited[0]} ({known[cited[0]].app}) but the ticket is {app}"
            return RuleMatch("uncertain", None, None, reason, ranking)
        return RuleMatch("matched", cited[0], "cited", f"The notes cite {cited[0]}", ranking)

    case_codes = codes(text)
    shared = {a.kb_id: n for a, _ in ranked if (n := len(case_codes & a.codes))}
    if shared:
        best = max(shared.values())
        winners = [kb for kb, n in shared.items() if n == best]
        if len(winners) == 1:
            reason = f"Shares {sorted(case_codes & known[winners[0]].codes)} with {winners[0]}"
            return RuleMatch("matched", winners[0], "code", reason, ranking)

    top = ranked[0][1] if ranked else 0.0
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if top >= config.min_score and top >= config.margin * second:
        return RuleMatch("matched", ranked[0][0].kb_id, "keywords", f"Word overlap {top:.2f} with {ranked[0][0].kb_id}", ranking)
    return RuleMatch("uncertain", None, None, "No article is clearly the one; needs a check by the model", ranking)
