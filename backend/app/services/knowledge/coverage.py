"""How much of what engineers fix is already in the knowledge base, per application."""

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.knowledge_builder.articles import articles
from app.models.knowledge import KBDraft, ResolvedCase

UNKNOWN = "(no application)"


@dataclass
class AppCoverage:
    application: str
    articles: int
    cases: int = 0
    matched: int = 0
    gap: int = 0
    uncertain: int = 0
    outside_kb: int = 0  # gaps that are not knowledge gaps: a request, or a problem outside the application
    drafts_waiting: int = 0  # drafts for this application waiting for an expert
    unused_articles: list[str] = field(default_factory=list)  # articles no resolved case has matched

    @property
    def covered_share(self) -> float:
        """Share of the saved cases that an article covers."""
        return round(self.matched / self.cases, 3) if self.cases else 0.0


def coverage(db: Session) -> list[AppCoverage]:
    """One row per application: its articles, the cases saved, how many an article covers, and which articles are unused."""
    known = articles()
    rows: dict[str, AppCoverage] = {}
    for app, n in sorted(Counter(a.app for a in known.values()).items()):
        rows[app] = AppCoverage(app, n)
    used: dict[str, set[str]] = {}
    for case in db.scalars(select(ResolvedCase)):
        row = rows.setdefault(case.application or UNKNOWN, AppCoverage(case.application or UNKNOWN, 0))
        row.cases += 1
        setattr(row, case.match_status, getattr(row, case.match_status) + 1)
        row.outside_kb += case.gap_kind in ("request", "outside_kb")
        if case.kb_article_id:
            used.setdefault(row.application, set()).add(case.kb_article_id)
    for draft in db.scalars(select(KBDraft).where(KBDraft.status == "draft")):
        rows.setdefault(draft.application, AppCoverage(draft.application, 0)).drafts_waiting += 1
    for app, row in rows.items():
        row.unused_articles = sorted(a.kb_id for a in known.values() if a.app == app and a.kb_id not in used.get(app, set()))
    return list(rows.values())
