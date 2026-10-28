"""Fill the public demo queue with realistic tickets.

The demo queue uses tickets from the hand-written test set, so visitors see the model's real
behaviour, mistakes included, rather than tickets from its own training distribution. Their open
times are spread over the last two working days so the SLA clocks look like a live queue. The
retention job refreshes the queue once a day.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from triage.db.models import Review, Ticket, TriageRecord
from triage.db.repository import Repository
from triage.service import TriageService

DEFAULT_PATH = Path("data/test/handwritten.jsonl")
DEMO_COUNT = 60


def load_demo_tickets(
    path: Path = DEFAULT_PATH, count: int = DEMO_COUNT, seed: int = 2026
) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if r.get("split") == "test"]
    # Choosing demo tickets, not security, so a seeded generator is right.
    random.Random(seed).shuffle(rows)  # noqa: S311 # nosec B311
    return rows[:count]


def _open_times(service: TriageService, n: int, now: datetime, seed: int) -> list[datetime]:
    """Business-hours times over the last two working days, newest first."""
    rng = random.Random(seed)  # noqa: S311 # nosec B311
    cal = service.policy.calendar
    times: list[datetime] = []
    day = now.astimezone(cal.tz).date()
    days: list[datetime] = []
    while len(days) < 3:
        if cal.is_business_day(day):
            days.append(datetime.combine(day, cal.start, tzinfo=cal.tz))
        day -= timedelta(days=1)
    span = int(
        (datetime.combine(now.date(), cal.end) - datetime.combine(now.date(), cal.start)).total_seconds()
        // 60
    )
    while len(times) < n:
        start = rng.choice(days)
        t = start + timedelta(minutes=rng.randrange(span))
        if t < now:
            times.append(t.astimezone(UTC))
    return sorted(times, reverse=True)


def seed_demo(
    service: TriageService,
    session: Session,
    path: Path = DEFAULT_PATH,
    now: datetime | None = None,
    seed: int = 2026,
) -> int:
    now = now or datetime.now(UTC)
    tickets = load_demo_tickets(path, seed=seed)
    repo = Repository(session)
    for row, opened in zip(tickets, _open_times(service, len(tickets), now, seed), strict=True):
        result = service.triage(row["subject"], row["body"], opened_at=opened, use_llm=False)
        repo.add_ticket(result, channel="portal", is_seed=True, created_at=opened)
    repo.audit("system", "demo.seeded", count=len(tickets))
    return len(tickets)


def clear_demo(session: Session) -> int:
    ids = list(session.execute(select(Ticket.id).where(Ticket.is_seed.is_(True))).scalars())
    if ids:
        session.execute(delete(Review).where(Review.ticket_id.in_(ids)))
        session.execute(delete(TriageRecord).where(TriageRecord.ticket_id.in_(ids)))
        session.execute(delete(Ticket).where(Ticket.id.in_(ids)))
    return len(ids)
