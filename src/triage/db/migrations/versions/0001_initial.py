"""Initial schema: tickets, triage results, reviews and the audit log.

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("subject", sa.Unicode(300), nullable=False),
        sa.Column("body", sa.UnicodeText(), nullable=False),
        sa.Column("pii_counts", sa.JSON(), nullable=False),
        sa.Column("special_category_hint", sa.Boolean(), nullable=False),
        sa.Column("is_seed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
    )
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])
    op.create_index("ix_tickets_seed_status", "tickets", ["is_seed", "status"])

    op.create_table(
        "triage_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ticket_id",
            sa.Uuid(),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("model_version", sa.String(60), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("category_confidence", sa.Float(), nullable=False),
        sa.Column("ticket_type", sa.String(20), nullable=False),
        sa.Column("type_confidence", sa.Float(), nullable=False),
        sa.Column("model_impact", sa.Integer(), nullable=False),
        sa.Column("model_urgency", sa.Integer(), nullable=False),
        sa.Column("impact", sa.Integer(), nullable=False),
        sa.Column("urgency", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("resolver_group", sa.String(100), nullable=False),
        sa.Column("major_incident", sa.Boolean(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("review_reasons", sa.JSON(), nullable=False),
        sa.Column("rules_fired", sa.JSON(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("respond_by", TZ, nullable=False),
        sa.Column("resolve_by", TZ, nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.Column("kb_ids", sa.JSON(), nullable=False),
        sa.Column("llm_status", sa.String(20), nullable=False),
        sa.Column("llm_summary", sa.Unicode(500), nullable=True),
        sa.Column("llm_category", sa.String(20), nullable=True),
        sa.Column("llm_reply_draft", sa.Unicode(2000), nullable=True),
        sa.Column("llm_questions", sa.JSON(), nullable=False),
        sa.Column("llm_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_triage_results_review", "triage_results", ["needs_review", "priority"])

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("reviewer", sa.String(64), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("ticket_type", sa.String(20), nullable=False),
        sa.Column("impact", sa.Integer(), nullable=False),
        sa.Column("urgency", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("agreed", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Unicode(1000), nullable=True),
    )
    op.create_index("ix_reviews_ticket_id", "reviews", ["ticket_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", TZ, nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("reviews")
    op.drop_table("triage_results")
    op.drop_table("tickets")
