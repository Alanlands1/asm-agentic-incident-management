"""Knowledge Builder: a resolved ticket whose close notes passed, saved with names masked so Resolution can learn from it."""

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ResolvedCase(Base):
    """One good fix. All text is masked. match_status says whether a knowledge-base article covers it."""

    __tablename__ = "resolved_cases"

    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True)
    application: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text)  # the final close notes: the engineer's edit if there was one
    cause: Mapped[Optional[str]] = mapped_column(Text)  # the words that showed the cause, action and check (Closure Quality)
    action: Mapped[Optional[str]] = mapped_column(Text)
    check: Mapped[Optional[str]] = mapped_column(Text)
    score: Mapped[Optional[int]] = mapped_column(Integer)  # out of 6
    match_status: Mapped[str] = mapped_column(String(16), index=True)  # matched | gap | uncertain
    kb_article_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    match_method: Mapped[Optional[str]] = mapped_column(String(16))  # cited | code | keywords | model
    gap_kind: Mapped[Optional[str]] = mapped_column(String(16))  # for a gap: known_issue | request | outside_kb
    draft_id: Mapped[Optional[int]] = mapped_column(ForeignKey("kb_drafts.id", ondelete="SET NULL"), index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KBDraft(Base):
    """A knowledge-base article drafted from gap cases. It counts only once an expert approves it; nothing is published."""

    __tablename__ = "kb_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application: Mapped[str] = mapped_column(String(64), index=True)
    kb_id: Mapped[Optional[str]] = mapped_column(String(32), unique=True)  # given on approval, e.g. KB-PAY-006
    title: Mapped[str] = mapped_column(String(256))
    symptoms: Mapped[list[str]] = mapped_column(JSON, default=list)
    root_cause: Mapped[str] = mapped_column(Text)
    resolution_steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    escalation: Mapped[str] = mapped_column(Text)
    source_ticket_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), index=True, default="draft")  # draft | approved | rejected
    reviewer: Mapped[Optional[str]] = mapped_column(String(256))  # as given by the caller; not verified until there are logins
    reason_code: Mapped[Optional[str]] = mapped_column(String(32))
    note: Mapped[Optional[str]] = mapped_column(Text)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProblemCandidate(Base):
    """The same issue closed again and again: a suggestion to open a problem record. A person accepts or dismisses it."""

    __tablename__ = "problem_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    issue_key: Mapped[str] = mapped_column(String(64), index=True)  # article:KB-PAY-002 or draft:12
    ticket_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cases: Mapped[int] = mapped_column(Integer)
    first_closed: Mapped[datetime] = mapped_column(DateTime)
    last_closed: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), index=True, default="open")  # open | accepted | dismissed
    decided_by: Mapped[Optional[str]] = mapped_column(String(256))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
