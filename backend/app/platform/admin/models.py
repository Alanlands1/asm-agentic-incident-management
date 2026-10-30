"""Admin overrides of settings and reference documents, and the history of every change."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.ticket import utcnow


class ConfigOverride(Base):
    """The current admin value for one setting or one reference document."""

    __tablename__ = "config_overrides"

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)  # setting | document
    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. LLM_MODEL, prompts
    value: Mapped[Any] = mapped_column(JSON)
    claimed_by: Mapped[str] = mapped_column(String(128))  # from X-Admin-User; not verified until real logins exist
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConfigChange(Base):
    """One admin change: what it was, what it became, who said they made it. Never updated or deleted."""

    __tablename__ = "config_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    old_value: Mapped[Any] = mapped_column(JSON)
    new_value: Mapped[Any] = mapped_column(JSON)  # null when the override was removed
    claimed_by: Mapped[str] = mapped_column(String(128))  # from X-Admin-User; not verified until real logins exist
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
