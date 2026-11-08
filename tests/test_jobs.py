from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import false, func, select, true

from tests.conftest import HANDWRITTEN, make_settings
from triage.db.migrate import upgrade
from triage.db.models import AuditEvent, Ticket
from triage.db.repository import Repository
from triage.db.session import make_engine, make_session_factory, session_scope
from triage.jobs import run
from triage.jobs.seed import clear_demo, load_demo_tickets, seed_demo
from triage.service import TriageService
from triage.settings import get_settings

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
        times = list(s.execute(select(Ticket.created_at).where(Ticket.is_seed == true())).scalars())
        assert len(times) == 60 and max(times) < NOW
        assert all(t.astimezone(UTC).weekday() < 5 for t in times)
        assert Repository(s).count_seed() == 60
        assert clear_demo(s) == 60
    with session_scope(sessions) as s:
        assert s.execute(select(func.count(Ticket.id))).scalar_one() == 0


def test_retention_job_purges_old_tickets_and_refreshes_a_stale_demo_queue(
    service: TriageService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nightly retention job, end to end on SQLite: tickets past the retention period go, recent
    ones stay, the deletion is in the audit log, and a demo queue older than a day is replaced."""
    url = f"sqlite:///{tmp_path / 'triage.db'}"
    monkeypatch.setenv("TRIAGE_DATABASE_URL", url)
    monkeypatch.setenv("TRIAGE_RETENTION_DAYS", "30")
    monkeypatch.setattr(run, "build_service", lambda settings, with_llm=True: service)
    engine = make_engine(make_settings(database_url=url))
    upgrade(engine)
    sessions = make_session_factory(engine)
    now = datetime.now(UTC)
    with session_scope(sessions) as s:
        repo = Repository(s)
        repo.add_ticket(
            service.triage("Old", "VPN drops"), channel="api", created_at=now - timedelta(days=31)
        )
        repo.add_ticket(
            service.triage("New", "VPN drops"), channel="api", created_at=now - timedelta(days=29)
        )
        seed_demo(service, s, HANDWRITTEN, now=now - timedelta(days=3))

    get_settings.cache_clear()
    try:
        run.retention(HANDWRITTEN)
    finally:
        get_settings.cache_clear()

    with session_scope(sessions) as s:
        submitted = s.execute(select(Ticket.subject).where(Ticket.is_seed == false())).scalars().all()
        assert submitted == ["New"]
        assert Repository(s).count_seed() == 60
        # The queue was seeded twice: once above, once by the job. Checking the open times instead
        # fails at weekends and after bank holidays, when the newest working day is over a day ago.
        seeded = s.execute(select(AuditEvent).where(AuditEvent.action == "demo.seeded")).scalars().all()
        assert len(seeded) == 2
        purged = s.execute(select(AuditEvent).where(AuditEvent.action == "retention.purged")).scalar_one()
        assert purged.details == {"count": 1, "retention_days": 30}
    engine.dispose()
