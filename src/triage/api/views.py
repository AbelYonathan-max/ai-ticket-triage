"""Turn stored tickets into what the API returns and the pages show."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from triage.api.schemas import AssistOut, KbArticleOut, ReviewOut, TicketOut
from triage.db.models import Ticket
from triage.domain.itil import SlaPolicy
from triage.domain.taxonomy import category_label
from triage.kb.retrieve import KnowledgeBase

LONDON = ZoneInfo("Europe/London")


def ticket_out(ticket: Ticket, kb: KnowledgeBase, policy: SlaPolicy, base_url: str = "") -> TicketOut:
    r = ticket.result
    if r is None:
        raise ValueError("ticket has no triage result")
    articles = [a for a in (kb.get(i) for i in r.kb_ids) if a is not None]
    return TicketOut(
        id=ticket.id,
        url=f"{base_url}/tickets/{ticket.id}",
        created_at=ticket.created_at,
        channel=ticket.channel,
        status=ticket.status,
        redacted_subject=ticket.subject,
        redacted_body=ticket.body,
        personal_data_removed=dict(ticket.pii_counts or {}),
        special_category_hint=ticket.special_category_hint,
        category=r.category,
        category_label=category_label(r.category),
        category_confidence=r.category_confidence,
        ticket_type=r.ticket_type,
        type_confidence=r.type_confidence,
        impact=r.impact,
        urgency=r.urgency,
        model_impact=r.model_impact,
        model_urgency=r.model_urgency,
        priority=f"P{r.priority}",
        priority_name=policy.targets[r.priority].name,
        resolver_group=r.resolver_group,
        major_incident=r.major_incident,
        needs_review=r.needs_review,
        review_reasons=list(r.review_reasons or []),
        rules_fired=list(r.rules_fired or []),
        flags=list(r.flags or []),
        respond_by=r.respond_by,
        resolve_by=r.resolve_by,
        why={head: [str(t[0]) for t in terms] for head, terms in (r.explanation or {}).items()},
        knowledge_base=[KbArticleOut(id=a.id, title=a.title, summary=a.summary) for a in articles],
        assist=AssistOut(
            status=r.llm_status,
            summary=r.llm_summary,
            category=r.llm_category,
            reply_draft=r.llm_reply_draft,
            questions=list(r.llm_questions or []),
        ),
        model_version=r.model_version,
        latency_ms=r.latency_ms,
        reviews=[
            ReviewOut(
                created_at=v.created_at,
                category=v.category,
                ticket_type=v.ticket_type,
                impact=v.impact,
                urgency=v.urgency,
                priority=f"P{v.priority}",
                agreed=v.agreed,
                notes=v.notes,
            )
            for v in ticket.reviews
        ],
    )


def london(dt: datetime) -> str:
    """Format a UTC time as London local time for people to read."""
    return dt.astimezone(LONDON).strftime("%a %d %b %Y, %H:%M")


def due_in(dt: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    minutes = int((dt - now).total_seconds() // 60)
    if minutes < 0:
        late = -minutes
        return f"overdue by {late // 60} h {late % 60} min" if late >= 60 else f"overdue by {late} min"
    if minutes >= 60 * 24:
        return f"in {minutes // (60 * 24)} d {(minutes % (60 * 24)) // 60} h"
    return f"in {minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"in {minutes} min"
