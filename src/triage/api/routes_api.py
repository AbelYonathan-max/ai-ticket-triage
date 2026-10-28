"""JSON API, versioned under /api/v1."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from triage.api.app import Runtime, principal, repository, require_analyst, runtime
from triage.api.schemas import ReviewIn, TicketIn, TicketOut, TicketPage
from triage.api.views import ticket_out
from triage.db.repository import Repository, ReviewInput
from triage.privacy.redact import redact
from triage.security.auth import Principal
from triage.security.web import client_ip

router = APIRouter(prefix="/api/v1", tags=["triage"])
log = logging.getLogger("triage.api")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.post("/triage", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def triage_ticket(
    payload: TicketIn,
    request: Request,
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    who: Principal = Depends(principal),
) -> TicketOut:
    """Triage a ticket. Personal data is removed before anything is stored or sent to the AI."""
    if not who.is_analyst and not rt.limiter.allow(f"triage:{client_ip(request)}"):
        raise HTTPException(
            status_code=429, detail="Too many tickets from this address. Try again in a minute."
        )
    result = rt.service.triage(payload.subject, payload.body)
    ticket = repo.add_ticket(result, channel=payload.channel)
    repo.audit(who.id or "anonymous", "ticket.submitted", ticket.id, channel=payload.channel)
    log.info(
        "ticket_triaged",
        extra={
            "ticket_id": str(ticket.id),
            "category": result.category,
            "priority": result.priority,
            "needs_review": result.needs_review,
            "rules": ",".join(result.rules_fired),
            "pii_items": result.pii_total,
            "llm_status": result.assist.status if result.assist else "disabled",
            "latency_ms": result.latency_ms,
        },
    )
    return ticket_out(ticket, rt.kb, rt.policy, _base_url(request))


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(
    ticket_id: uuid.UUID,
    request: Request,
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
) -> TicketOut:
    """Fetch one ticket by its ID. The ID is random, so only someone who has the link can see it."""
    ticket = repo.get(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=404, detail="Ticket not found. Tickets are deleted after the retention period."
        )
    return ticket_out(ticket, rt.kb, rt.policy, _base_url(request))


@router.get("/tickets", response_model=TicketPage)
def list_tickets(
    request: Request,
    needs_review: bool | None = None,
    category: str | None = None,
    priority: int | None = Query(default=None, ge=1, le=4),
    ticket_status: Literal["open", "reviewed"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    _: Principal = Depends(require_analyst),
) -> TicketPage:
    """List tickets for analysts, highest priority and earliest SLA first."""
    items, total = repo.list(
        needs_review=needs_review,
        category=category,
        priority=priority,
        status=ticket_status,
        limit=limit,
        offset=offset,
    )
    base = _base_url(request)
    return TicketPage(
        total=total, limit=limit, offset=offset, items=[ticket_out(t, rt.kb, rt.policy, base) for t in items]
    )


@router.post("/tickets/{ticket_id}/review", response_model=TicketOut)
def review_ticket(
    ticket_id: uuid.UUID,
    payload: ReviewIn,
    request: Request,
    rt: Runtime = Depends(runtime),
    repo: Repository = Depends(repository),
    who: Principal = Depends(require_analyst),
) -> TicketOut:
    """Record an analyst's decision. Reviews become labelled data for the next model version."""
    ticket = repo.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    notes = redact(payload.notes).text if payload.notes else None
    review = repo.add_review(
        ticket,
        who.id,
        ReviewInput(payload.category, payload.ticket_type, payload.impact, payload.urgency, notes),
    )
    repo.audit(who.id, "ticket.reviewed", ticket.id, agreed=review.agreed, priority=review.priority)
    return ticket_out(ticket, rt.kb, rt.policy, _base_url(request))


@router.get("/stats")
def stats(repo: Repository = Depends(repository), who: Principal = Depends(principal)) -> dict[str, Any]:
    """Counts for the dashboard. Anonymous visitors see the demo queue only."""
    return repo.stats(seed_only=not who.is_analyst)


@router.get("/model")
def model_info(rt: Runtime = Depends(runtime)) -> dict[str, Any]:
    """The deployed model's version, review threshold and held-out test results."""
    meta = rt.service.model.metadata
    return {
        "version": meta.get("version"),
        "algorithm": meta.get("algorithm"),
        "review_threshold": meta.get("review_threshold"),
        "training": meta.get("training"),
        "test": meta.get("test_summary"),
        "llm_provider": rt.settings.llm_provider,
    }
