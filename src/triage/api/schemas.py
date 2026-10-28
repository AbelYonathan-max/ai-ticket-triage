"""Request and response models for the JSON API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from triage.domain.taxonomy import CATEGORIES

CategoryCode = Literal["access", "hardware", "software", "m365", "network", "printing", "security"]
if set(CategoryCode.__args__) != set(CATEGORIES):  # type: ignore[attr-defined]
    raise RuntimeError("CategoryCode is out of step with the taxonomy")


class TicketIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200, description="Ticket subject line")
    body: str = Field(min_length=3, max_length=6000, description="Ticket description")
    channel: Literal["portal", "email", "phone", "api"] = "api"

    @field_validator("subject", "body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ReviewIn(BaseModel):
    category: CategoryCode
    ticket_type: Literal["incident", "request"]
    impact: int = Field(ge=1, le=3)
    urgency: int = Field(ge=1, le=3)
    notes: str | None = Field(default=None, max_length=1000)


class KbArticleOut(BaseModel):
    id: str
    title: str
    summary: str


class AssistOut(BaseModel):
    status: str
    summary: str | None
    category: str | None
    reply_draft: str | None
    questions: list[str]


class ReviewOut(BaseModel):
    created_at: datetime
    category: str
    ticket_type: str
    impact: int
    urgency: int
    priority: str
    agreed: bool
    notes: str | None


class TicketOut(BaseModel):
    id: uuid.UUID
    url: str
    created_at: datetime
    channel: str
    status: str
    redacted_subject: str
    redacted_body: str
    personal_data_removed: dict[str, int]
    special_category_hint: bool
    category: str
    category_label: str
    category_confidence: float
    ticket_type: str
    type_confidence: float
    impact: int
    urgency: int
    model_impact: int
    model_urgency: int
    priority: str
    priority_name: str
    resolver_group: str
    major_incident: bool
    needs_review: bool
    review_reasons: list[str]
    rules_fired: list[str]
    flags: list[str]
    respond_by: datetime
    resolve_by: datetime
    why: dict[str, list[str]]
    knowledge_base: list[KbArticleOut]
    assist: AssistOut
    model_version: str
    latency_ms: int
    reviews: list[ReviewOut] = []


class TicketPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TicketOut]
