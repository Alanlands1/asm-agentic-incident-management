"""Deterministic facts about a ticket, computed locally before any model call."""

from dataclasses import dataclass
from datetime import datetime

from app.agents.triage.config import TriageConfig


@dataclass(frozen=True)
class Signals:
    application: str | None
    app_source: str | None  # "system" when the source field names it, "keyword" when found in the text
    tier: int | None  # None when the application is not in the rulebook
    scope: str  # single, wide, unknown, or mixed when the text describes both
    windows: tuple[str, ...]  # calendar windows open when the ticket was raised
    failed_jobs: tuple[str, ...]  # batch jobs from jobs.yaml the ticket says failed
    tone_ignored: bool  # the reporter's own urgency words were removed before matching


def clean_text(summary: str, body: str, config: TriageConfig) -> str:
    """Summary and description without the reporter's urgency words, which say nothing about impact."""
    text = f"{summary}\n{body}"
    for pattern in config.tone:
        text = pattern.sub(" ", text)
    return text


def _find_app(text: str, config: TriageConfig) -> str | None:
    hits = {name: m.start() for name, pattern in config.apps.items() if (m := pattern.search(text))}
    return min(hits, key=hits.get) if hits else None


def _scope(text: str, config: TriageConfig) -> str:
    wide = any(p.search(text) for p in config.wide)
    single = any(p.search(text) for p in config.single)
    return "mixed" if wide and single else "wide" if wide else "single" if single else "unknown"


def compute_signals(
    summary: str, body: str, application: str | None, opened_at: datetime | None, config: TriageConfig
) -> Signals:
    text = clean_text(summary, body, config)
    keyword_app = None if application else _find_app(text, config)
    found = application or keyword_app
    app = config.applications.get(found) if found else None
    return Signals(
        application=found,
        app_source="system" if application else "keyword" if keyword_app else None,
        tier=app.tier if app else None,
        scope=_scope(text, config),
        windows=tuple(n for n, w in config.windows.items() if opened_at and w.contains(opened_at.date())),
        failed_jobs=tuple(job.name for job in config.jobs if job.failed.search(text)),
        tone_ignored=text != f"{summary}\n{body}",
    )
