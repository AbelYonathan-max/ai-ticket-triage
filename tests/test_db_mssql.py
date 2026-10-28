"""Runs the migrations and a round trip against a real SQL Server (the CI service container).

Set TEST_MSSQL_URL, for example:
mssql+pyodbc://sa:<password>@localhost:1433/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import make_settings
from triage.db.migrate import current_revision, grant_statements, head_revision, upgrade
from triage.db.repository import Repository, ReviewInput
from triage.db.session import make_engine, make_session_factory, session_scope
from triage.service import TriageService

pytestmark = pytest.mark.mssql
URL = os.environ.get("TEST_MSSQL_URL")


@pytest.fixture(scope="module")
def database_url() -> str:  # type: ignore[misc]
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
