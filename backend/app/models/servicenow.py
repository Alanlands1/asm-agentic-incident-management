"""ServiceNow ticket model."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ServiceNowTicket(Base):
    """ServiceNow incident ticket schema."""

    __tablename__ = "servicenow_tickets"

    ticket_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    caller: Mapped[Optional[str]] = mapped_column(String(128))
    short_description: Mapped[Optional[str]] = mapped_column(String(512))
    description: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[Optional[str]] = mapped_column(String(32))
    assignment_group: Mapped[Optional[str]] = mapped_column(String(64))
    service: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    dq_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    dq_reason: Mapped[Optional[str]] = mapped_column(String(256))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
