"""First messages a person marked as sent (db/scripts/08_create_first_messages.sql)."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class FirstMessage(Base):
    """The first message of a P1/P2 as it was sent. A storm's message sits on its main ticket. One row per send."""

    __tablename__ = "first_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    storm_id: Mapped[int | None] = mapped_column(ForeignKey("storms.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    sent_by: Mapped[str] = mapped_column(String(256))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
