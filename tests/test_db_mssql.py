"""Runs the migrations and a round trip against a real SQL Server (the CI service container).

Set TEST_MSSQL_URL, for example:
mssql+pyodbc://sa:<password>@localhost:1433/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from tests.conftest import HANDWRITTEN, make_settings
from triage.db.migrate import current_revision, grant_statements, head_revision, upgrade
from triage.db.repository import Repository, ReviewInput
from triage.db.session import make_engine, make_session_factory, session_scope
from triage.jobs import run
from triage.service import TriageService
from triage.settings import get_settings

pytestmark = pytest.mark.mssql
URL = os.environ.get("TEST_MSSQL_URL")


@pytest.fixture
def database_url() -> str:  # type: ignore[misc]
    """A new, empty database for each test."""
    if not URL:
        pytest.skip("TEST_MSSQL_URL not set")
    name = f"triage_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE [{name}]"))
    yield URL.replace("/master?", f"/{name}?")
    with admin.connect() as conn:
        conn.execute(text(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"))
        conn.execute(text(f"DROP DATABASE [{name}]"))
    admin.dispose()


def test_migrate_and_round_trip_on_sql_server(database_url: str, service: TriageService) -> None:
    engine = make_engine(make_settings(database_url=database_url))
    upgrade(engine)
    upgrade(engine)  # idempotent
    assert current_revision(engine) == head_revision()
    sessions = make_session_factory(engine)
    result = service.triage("Outlook", "Outlook won't open. Ring me on 07700 900123 – thanks, Priya Shah")
    with session_scope(sessions) as s:
        repo = Repository(s)
        ticket = repo.add_ticket(result, channel="api")
        assert ticket.result is not None
        repo.add_review(ticket, "analyst", ReviewInput("m365", "incident", 3, 2, "ok"))
        repo.audit("analyst", "ticket.reviewed", ticket.id, agreed=False)
        ticket_id = ticket.id
    with session_scope(sessions) as s:
        repo = Repository(s)
        loaded = repo.get(ticket_id)
        assert loaded is not None and loaded.result is not None
        assert loaded.result.respond_by.tzinfo is not None
        assert loaded.reviews[0].category == "m365" and loaded.status == "reviewed"
        assert "–" in loaded.body  # unicode survives NVARCHAR
        stats = repo.stats()
        assert stats["total"] == 1 and stats["reviewed"] == 1
    # The grant SQL is valid T-SQL (the user cannot be created on SQL Server outside Azure, so the
    # statement is checked for syntax only).
    with engine.connect() as conn:
        conn.execute(text("SET PARSEONLY ON"))
        for stmt in grant_statements("id-triage-app", str(uuid.uuid4())):
            conn.execute(text(stmt))
        conn.execute(text("SET PARSEONLY OFF"))


def test_jobs_queue_dashboard_and_api_on_sql_server(
    database_url: str,
    service: TriageService,
    make_client: Callable[..., TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-SQL rejects some SQL that SQLite accepts ("IS 1" for a boolean filter, for one), so both
    jobs, every repository filter and the analyst pages and API run here against SQL Server too."""
    monkeypatch.setenv("TRIAGE_DATABASE_URL", database_url)
    monkeypatch.setattr(run, "build_service", lambda settings, with_llm=True: service)
    get_settings.cache_clear()
    try:
        run.migrate(HANDWRITTEN)
        run.migrate(HANDWRITTEN)  # each deploy runs it again: no error, no second demo queue
        run.retention(HANDWRITTEN)
    finally:
        get_settings.cache_clear()

    sessions = make_session_factory(make_engine(make_settings(database_url=database_url)))
    with session_scope(sessions) as s:
        repo = Repository(s)
        assert repo.count_seed() == 60
        assert repo.list(seed_only=True)[1] == 60
        for needs_review in (True, False):
            repo.list(
                seed_only=True, needs_review=needs_review, category="network", priority=2, status="open"
            )
        assert repo.stats(seed_only=True)["total"] > 0
        assert repo.purge_older_than(datetime.now(UTC)) == 0  # the demo queue is never purged

    client = make_client(database_url=database_url)
    created = client.post(
        "/api/v1/triage", json={"subject": "VPN dropping", "body": "The VPN keeps dropping at home."}
    )
    assert created.status_code == 201, created.text
    ticket = created.json()
    for path in (
        "/queue",
        "/queue?view=open&category=network&priority=2",
        "/queue?view=all&page=2",
        "/dashboard",
        f"/tickets/{ticket['id']}",
        "/api/v1/tickets?needs_review=true",
        "/api/v1/tickets?needs_review=false&status=open&category=network&priority=2",
        "/api/v1/stats",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:500])
    review = {k: ticket[k] for k in ("category", "ticket_type", "impact", "urgency")}
    reviewed = client.post(f"/api/v1/tickets/{ticket['id']}/review", json=review)
    assert reviewed.status_code == 200, reviewed.text

    with session_scope(sessions) as s:
        # The test service's clock is a fixed morning next week, so the cutoff is a year ahead.
        assert Repository(s).purge_older_than(datetime.now(UTC) + timedelta(days=365)) == 1
