"""Database tables.

Only redacted text is ever stored. The original ticket text exists in memory for the few
milliseconds it takes to redact it, and is never written to the database or the logs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Unicode,
    UnicodeText,
    Uuid,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store timezone-aware UTC datetimes the same way on SQL Server (datetimeoffset) and SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: use timezone-aware UTC times")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: UTCDateTime(),
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    channel: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(Unicode(300))  # redacted
    body: Mapped[str] = mapped_column(UnicodeText)  # redacted
    pii_counts: Mapped[dict[str, Any]] = mapped_column(default=dict)
    special_category_hint: Mapped[bool] = mapped_column(Boolean, default=False)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, reviewed

    result: Mapped[TriageRecord | None] = relationship(
        back_populates="ticket", uselist=False, cascade="all, delete-orphan", lazy="joined"
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="Review.created_at"
    )

    __table_args__ = (
        Index("ix_tickets_created_at", "created_at"),
        Index("ix_tickets_seed_status", "is_seed", "status"),
    )


class TriageRecord(Base):
    __tablename__ = "triage_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    model_version: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(20))
    category_confidence: Mapped[float] = mapped_column(Float)
    ticket_type: Mapped[str] = mapped_column(String(20))
    type_confidence: Mapped[float] = mapped_column(Float)
    model_impact: Mapped[int] = mapped_column(Integer)
    model_urgency: Mapped[int] = mapped_column(Integer)
    impact: Mapped[int] = mapped_column(Integer)
    urgency: Mapped[int] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer)
    resolver_group: Mapped[str] = mapped_column(String(100))
    major_incident: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean)
    review_reasons: Mapped[list[Any]] = mapped_column(default=list)
    rules_fired: Mapped[list[Any]] = mapped_column(default=list)
    flags: Mapped[list[Any]] = mapped_column(default=list)
    respond_by: Mapped[datetime]
    resolve_by: Mapped[datetime]
    explanation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    kb_ids: Mapped[list[Any]] = mapped_column(default=list)
    llm_status: Mapped[str] = mapped_column(String(20), default="disabled")
    llm_summary: Mapped[str | None] = mapped_column(Unicode(500))
    llm_category: Mapped[str | None] = mapped_column(String(20))
    llm_reply_draft: Mapped[str | None] = mapped_column(Unicode(2000))
    llm_questions: Mapped[list[Any]] = mapped_column(default=list)
    llm_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    ticket: Mapped[Ticket] = relationship(back_populates="result")

    __table_args__ = (Index("ix_triage_results_review", "needs_review", "priority"),)


class Review(Base):
    """An analyst's check of a triage decision. These are the labels for the next model version."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    reviewer: Mapped[str] = mapped_column(String(64))  # Entra object ID, or "analyst" for the shared key
    category: Mapped[str] = mapped_column(String(20))
    ticket_type: Mapped[str] = mapped_column(String(20))
    impact: Mapped[int] = mapped_column(Integer)
    urgency: Mapped[int] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer)
    agreed: Mapped[bool] = mapped_column(Boolean)  # did the analyst keep every triage decision?
    notes: Mapped[str | None] = mapped_column(Unicode(1000))  # redacted before saving

    ticket: Mapped[Ticket] = relationship(back_populates="reviews")


class AuditEvent(Base):
    """Who did what, without ticket text. Kept longer than tickets for accountability."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(40))
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
