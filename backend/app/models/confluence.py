"""Confluence copy: selected spaces, their pages and sync history (db/scripts/07_create_confluence.sql)."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ConfluenceSpace(Base):
    """A Confluence space an admin chose to copy."""

    __tablename__ = "confluence_spaces"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConfluencePage(Base):
    """One Confluence page as plain text: the knowledge base the agents read."""

    __tablename__ = "confluence_pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_key: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(String(1024))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConfluenceSync(Base):
    """One copy of the selected spaces, manual or scheduled."""

    __tablename__ = "confluence_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(16))
    spaces: Mapped[str] = mapped_column(String(512), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pulled: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
