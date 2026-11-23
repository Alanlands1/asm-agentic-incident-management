"""Repeat issues: the same article (or the same draft) closed again and again suggests a problem record.

A suggestion only: a person accepts or dismisses it. Grouping is by the article or draft the cases matched, which is
more precise than grouping by words: two cases on the same article are the same known issue.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.knowledge_builder.config import get_config
from app.models.knowledge import ProblemCandidate, ResolvedCase


class ProblemError(ValueError):
    """The decision does not fit, e.g. deciding twice."""


def _key(case: ResolvedCase) -> str | None:
    if case.kb_article_id:
        return f"article:{case.kb_article_id}"
    return f"draft:{case.draft_id}" if case.draft_id else None


def detect_problems(db: Session) -> list[ProblemCandidate]:
    """Find every issue closed at least problems.min_cases times within problems.window_days, and keep one open suggestion
    for it. A suggestion a person already decided is not raised again for the same tickets."""
    config = get_config()
    window = timedelta(days=config.problem_window_days)
    groups: dict[tuple[str | None, str], list[ResolvedCase]] = defaultdict(list)
    for case in db.scalars(select(ResolvedCase).where(ResolvedCase.closed_at.is_not(None))):
        if key := _key(case):
            groups[(case.application, key)].append(case)

    found = []
    for (app, key), cases in groups.items():
        cases.sort(key=lambda c: c.closed_at)
        best = max(([c for c in cases if end.closed_at - window <= c.closed_at <= end.closed_at] for end in cases), key=len)
        if len(best) < config.problem_min_cases:
            continue
        ids = [c.ticket_id for c in best]
        existing = db.scalars(select(ProblemCandidate).where(ProblemCandidate.issue_key == key)).all()
        if any(p.status != "open" and set(ids) <= set(p.ticket_ids) for p in existing):
            continue
        candidate = next((p for p in existing if p.status == "open"), None) or ProblemCandidate(application=app, issue_key=key)
        candidate.ticket_ids, candidate.cases = ids, len(ids)
        candidate.first_closed, candidate.last_closed = best[0].closed_at, best[-1].closed_at
        db.add(candidate)
        found.append(candidate)
    return found


def decide(db: Session, candidate: ProblemCandidate, action: str, decided_by: str, note: str | None = None) -> ProblemCandidate:
    """Accept (open a problem record) or dismiss a suggestion. Nothing is created in ServiceNow or JIRA."""
    if candidate.status != "open":
        raise ProblemError(f"This suggestion is already {candidate.status}")
    candidate.status, candidate.decided_by, candidate.note = action, decided_by.strip(), note
    candidate.decided_at = datetime.now(UTC)
    db.commit()
    return candidate
