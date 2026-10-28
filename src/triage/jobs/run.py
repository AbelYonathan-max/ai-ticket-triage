"""Command line entry points for the Container Apps jobs.

python -m triage.jobs.run migrate     # schema upgrade, app identity grant, demo queue
python -m triage.jobs.run retention   # delete tickets past the retention period, refresh demo queue
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from triage.app_factory import build_service
from triage.db.migrate import grant_app_identity, upgrade
from triage.db.models import Ticket
from triage.db.repository import Repository
from triage.db.session import make_engine, make_session_factory, session_scope
from triage.jobs.seed import DEFAULT_PATH, clear_demo, seed_demo
from triage.settings import get_settings
from triage.telemetry import configure

log = logging.getLogger("triage.jobs")


def migrate(demo_path: Path) -> None:
    settings = get_settings()
    engine = make_engine(settings)
    upgrade(engine)
    log.info("migrations_applied")
    name = os.environ.get("TRIAGE_APP_IDENTITY_NAME")
    client_id = os.environ.get("TRIAGE_APP_IDENTITY_CLIENT_ID")
    if name and client_id:
        grant_app_identity(engine, name, client_id)
        log.info("app_identity_granted", extra={"identity": name})
    sessions = make_session_factory(engine)
    with session_scope(sessions) as session:
        if Repository(session).count_seed() == 0 and demo_path.exists():
            n = seed_demo(build_service(settings, with_llm=False), session, demo_path)
            log.info("demo_seeded", extra={"count": n})


def retention(demo_path: Path) -> None:
    settings = get_settings()
    engine = make_engine(settings)
    sessions = make_session_factory(engine)
    cutoff = datetime.now(UTC) - timedelta(days=settings.retention_days)
    with session_scope(sessions) as session:
        repo = Repository(session)
        deleted = repo.purge_older_than(cutoff)
        repo.audit("system", "retention.purged", count=deleted, retention_days=settings.retention_days)
        log.info("retention_purged", extra={"count": deleted})
        newest = session.execute(select(func.max(Ticket.created_at)).where(Ticket.is_seed.is_(True))).scalar()
        stale = newest is None or newest.replace(tzinfo=newest.tzinfo or UTC) < datetime.now(UTC) - timedelta(
            hours=20
        )
        if stale and demo_path.exists():
            cleared = clear_demo(session)
            n = seed_demo(build_service(settings, with_llm=False), session, demo_path)
            log.info("demo_refreshed", extra={"cleared": cleared, "seeded": n})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a maintenance job")
    parser.add_argument("job", choices=["migrate", "retention"])
    parser.add_argument("--demo-tickets", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    configure(get_settings())
    {"migrate": migrate, "retention": retention}[args.job](args.demo_tickets)


if __name__ == "__main__":
    main()
