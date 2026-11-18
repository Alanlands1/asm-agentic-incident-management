"""Data Quality (DQ) models: rules, runs, and matched tickets."""

from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.servicenow import ServiceNowTicket


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TicketSource(Base):
    """Reference lookup table for incident ticket source systems."""

    __tablename__ = "ticket_sources"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DQRule(Base):
    """User-managed data quality rule."""

    __tablename__ = "dq_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(ForeignKey("ticket_sources.code", ondelete="SET NULL"))
    service: Mapped[Optional[str]] = mapped_column(String(64))
    apply_to: Mapped[str] = mapped_column(String(16), default="both", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    source_ref: Mapped[Optional[TicketSource]] = relationship()


class DQRun(Base):
    """Execution history of applying DQ rules."""

    __tablename__ = "dq_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    rules_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    tickets_evaluated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tickets_flagged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reverted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    matched_tickets: Mapped[list["DQRunTicket"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class DQRunTicket(Base):
    """Per-ticket flag details for a run to support revertibility."""

    __tablename__ = "dq_run_tickets"

    run_id: Mapped[int] = mapped_column(ForeignKey("dq_runs.id", ondelete="CASCADE"), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("servicenow_tickets.ticket_id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("dq_rules.id"), nullable=False)
    reverted_dq_flag: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reverted_dq_reason: Mapped[Optional[str]] = mapped_column(String(256))

    run: Mapped[DQRun] = relationship(back_populates="matched_tickets")
    ticket: Mapped[ServiceNowTicket] = relationship()
    rule: Mapped[DQRule] = relationship()
