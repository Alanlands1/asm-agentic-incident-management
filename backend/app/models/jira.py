"""Jira pull: selected projects and sync history (db/scripts/05_create_jira_sync.sql)."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class JiraProject(Base):
    """A Jira project an admin chose to pull tickets from."""

    __tablename__ = "jira_projects"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    team: Mapped[str | None] = mapped_column(String(64))
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JiraSync(Base):
    """One pull from Jira, manual or scheduled."""

    __tablename__ = "jira_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(16))
    projects: Mapped[str] = mapped_column(String(512), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pulled: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    queued: Mapped[int] = mapped_column(Integer, default=0)  # new open tickets handed to the agents
    error: Mapped[str | None] = mapped_column(Text)
