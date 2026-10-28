from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from tests.conftest import HANDWRITTEN, make_settings
from triage.db.migrate import upgrade
from triage.db.models import Ticket
from triage.db.repository import Repository
from triage.db.session import make_engine, make_session_factory, session_scope
from triage.jobs.seed import clear_demo, load_demo_tickets, seed_demo
from triage.service import TriageService

NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)  # Wednesday afternoon


def test_demo_tickets_come_from_the_test_split() -> None:
    rows = load_demo_tickets(HANDWRITTEN, count=60)
    assert len(rows) == 60 and all(r["split"] == "test" for r in rows)
    assert load_demo_tickets(HANDWRITTEN, count=60) == rows  # deterministic


def test_seed_and_clear_demo_queue(service: TriageService) -> None:
    engine = make_engine(make_settings())
    upgrade(engine)
    sessions = make_session_factory(engine)
    with session_scope(sessions) as s:
        assert seed_demo(service, s, HANDWRITTEN, now=NOW) == 60
    with session_scope(sessions) as s:
        times = list(s.execute(select(Ticket.created_at).where(Ticket.is_seed.is_(True))).scalars())
        assert len(times) == 60 and max(times) < NOW
        assert all(t.astimezone(UTC).weekday() < 5 for t in times)
        assert Repository(s).count_seed() == 60
        assert clear_demo(s) == 60
    with session_scope(sessions) as s:
        assert s.execute(select(func.count(Ticket.id))).scalar_one() == 0
