"""Reading and writing tickets, triage results, reviews and the audit log."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, false, func, select, true
from sqlalchemy.orm import Session, selectinload

from triage.db.models import AuditEvent, Review, Ticket, TriageRecord
from triage.domain.itil import priority_from
from triage.service import TriageResult


@dataclass(frozen=True)
class ReviewInput:
    category: str
    ticket_type: str
    impact: int
    urgency: int
    notes: str | None = None


def record_from_result(result: TriageResult) -> TriageRecord:
    assist = result.assist
    payload = assist.assist if assist else None
    return TriageRecord(
        model_version=result.model_version,
        category=result.category,
        category_confidence=result.category_confidence,
        ticket_type=result.ticket_type,
        type_confidence=result.type_confidence,
        model_impact=result.model_impact,
        model_urgency=result.model_urgency,
        impact=result.impact,
        urgency=result.urgency,
        priority=result.priority,
        resolver_group=result.resolver_group,
        major_incident=result.major_incident,
        needs_review=result.needs_review,
        review_reasons=list(result.review_reasons),
        rules_fired=list(result.rules_fired),
        flags=list(result.flags),
        respond_by=result.respond_by,
        resolve_by=result.resolve_by,
        explanation={head: [[t, w] for t, w in terms] for head, terms in result.explanation.items()},
        kb_ids=[h.article.id for h in result.kb_hits],
        llm_status=assist.status if assist else "disabled",
        llm_summary=payload.summary if payload else None,
        llm_category=payload.category if payload else None,
        llm_reply_draft=(payload.reply_draft or None) if payload else None,
        llm_questions=list(payload.missing_information) if payload else [],
        llm_tokens=assist.tokens if assist else 0,
        latency_ms=result.latency_ms,
    )


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ tickets
    def add_ticket(
        self, result: TriageResult, channel: str, is_seed: bool = False, created_at: datetime | None = None
    ) -> Ticket:
        ticket = Ticket(
            id=uuid.uuid4(),
            created_at=created_at or result.opened_at,
            channel=channel,
            subject=result.subject[:300],
            body=result.body,
            pii_counts=dict(result.pii_counts),
            special_category_hint=result.special_category_hint,
            is_seed=is_seed,
            status="open",
        )
        ticket.result = record_from_result(result)
        self.session.add(ticket)
        self.session.flush()
        return ticket

    def get(self, ticket_id: uuid.UUID) -> Ticket | None:
        stmt = select(Ticket).where(Ticket.id == ticket_id).options(selectinload(Ticket.reviews))
        return self.session.execute(stmt).unique().scalar_one_or_none()

    def list(
        self,
        *,
        seed_only: bool = False,
        needs_review: bool | None = None,
        category: str | None = None,
        priority: int | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Ticket], int]:
        # Booleans are compared with ==. SQL Server has no IS TRUE: .is_(True) becomes "IS 1", which
        # it rejects, though SQLite accepts it.
        conditions: list[ColumnElement[bool]] = []
        if seed_only:
            conditions.append(Ticket.is_seed == true())
        if needs_review is not None:
            conditions.append(TriageRecord.needs_review == needs_review)
        if category:
            conditions.append(TriageRecord.category == category)
        if priority:
            conditions.append(TriageRecord.priority == priority)
        if status:
            conditions.append(Ticket.status == status)
        count = select(func.count(Ticket.id)).join(Ticket.result).where(*conditions)
        total = self.session.execute(count).scalar_one()
        stmt = (
            select(Ticket)
            .join(Ticket.result)
            .where(*conditions)
            .order_by(TriageRecord.priority, TriageRecord.respond_by, Ticket.id)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).unique().scalars()), int(total)

    # ------------------------------------------------------------------ reviews
    def add_review(self, ticket: Ticket, reviewer: str, data: ReviewInput) -> Review:
        record = ticket.result
        if record is None:
            raise ValueError("ticket has no triage result")
        priority = priority_from(data.impact, data.urgency)
        agreed = (
            data.category == record.category
            and data.ticket_type == record.ticket_type
            and data.impact == record.impact
            and data.urgency == record.urgency
        )
        review = Review(
            reviewer=reviewer[:64],
            category=data.category,
            ticket_type=data.ticket_type,
            impact=data.impact,
            urgency=data.urgency,
            priority=priority,
            agreed=agreed,
            notes=data.notes,
        )
        ticket.reviews.append(review)
        ticket.status = "reviewed"
        self.session.flush()
        return review

    # ------------------------------------------------------------------ audit
    def audit(self, actor: str, action: str, ticket_id: uuid.UUID | None = None, **details: Any) -> None:
        self.session.add(AuditEvent(actor=actor[:64], action=action, ticket_id=ticket_id, details=details))

    # ------------------------------------------------------------------ stats
    def stats(self, seed_only: bool = False, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        base = select(Ticket.id).join(Ticket.result).where(Ticket.created_at >= since)
        if seed_only:
            base = base.where(Ticket.is_seed == true())
        ids = base.subquery()

        def grouped(column: Any) -> dict[Any, int]:
            rows = self.session.execute(
                select(column, func.count())
                .where(TriageRecord.ticket_id.in_(select(ids.c.id)))
                .group_by(column)
            ).all()
            return {k: int(v) for k, v in rows}

        review_counts = grouped(TriageRecord.needs_review)
        total = sum(review_counts.values())
        reviews = self.session.execute(
            select(Review.agreed, func.count())
            .where(Review.ticket_id.in_(select(ids.c.id)))
            .group_by(Review.agreed)
        ).all()
        agreed = {bool(k): int(v) for k, v in reviews}
        reviewed = sum(agreed.values())
        open_overdue = self.session.execute(
            select(func.count())
            .select_from(Ticket)
            .join(Ticket.result)
            .where(
                Ticket.id.in_(select(ids.c.id)),
                Ticket.status == "open",
                TriageRecord.respond_by < datetime.now(UTC),
            )
        ).scalar_one()
        return {
            "total": total,
            "by_category": grouped(TriageRecord.category),
            "by_priority": {int(k): v for k, v in grouped(TriageRecord.priority).items()},
            "by_type": grouped(TriageRecord.ticket_type),
            "needs_review": review_counts.get(True, 0),
            "auto_routed": review_counts.get(False, 0),
            "reviewed": reviewed,
            "review_agreement": (agreed.get(True, 0) / reviewed) if reviewed else None,
            "respond_overdue_open": int(open_overdue),
            "days": days,
        }

    # ------------------------------------------------------------------ retention
    def purge_older_than(self, cutoff: datetime) -> int:
        """Delete submitted tickets (not the synthetic demo set) created before the cutoff."""
        ids = list(
            self.session.execute(
                select(Ticket.id).where(Ticket.created_at < cutoff, Ticket.is_seed == false())
            ).scalars()
        )
        if not ids:
            return 0
        for chunk_start in range(0, len(ids), 500):
            chunk = ids[chunk_start : chunk_start + 500]
            self.session.execute(delete(Review).where(Review.ticket_id.in_(chunk)))
            self.session.execute(delete(TriageRecord).where(TriageRecord.ticket_id.in_(chunk)))
            self.session.execute(delete(Ticket).where(Ticket.id.in_(chunk)))
        return len(ids)

    def count_seed(self) -> int:
        return int(
            self.session.execute(select(func.count(Ticket.id)).where(Ticket.is_seed == true())).scalar_one()
        )
