from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.conftest import make_settings
from triage.db.migrate import current_revision, entra_sid, grant_statements, head_revision, upgrade
from triage.db.models import AuditEvent, Ticket
from triage.db.repository import Repository, ReviewInput
from triage.db.session import make_engine, make_session_factory, session_scope, token_struct
from triage.service import TriageService


@pytest.fixture
def sessions():  # type: ignore[no-untyped-def]
    engine = make_engine(make_settings())
    upgrade(engine)
    return make_session_factory(engine)


def test_migrations_reach_head() -> None:
    engine = make_engine(make_settings())
    assert current_revision(engine) is None
    upgrade(engine)
    assert current_revision(engine) == head_revision() == "0001"


def test_only_redacted_text_is_stored(service: TriageService, sessions) -> None:  # type: ignore[no-untyped-def]
    result = service.triage("Locked out", "My NI number is AB 12 34 56 C and my phone is 07700 900123")
    with session_scope(sessions) as s:
        ticket_id = Repository(s).add_ticket(result, channel="api").id
    with session_scope(sessions) as s:
        ticket = s.get(Ticket, ticket_id)
        assert ticket is not None and ticket.result is not None
        assert "AB 12" not in ticket.body and "07700" not in ticket.body
        assert ticket.pii_counts == {"NI_NUMBER": 1, "PHONE": 1}
        assert ticket.created_at.tzinfo is not None
        assert ticket.result.respond_by.tzinfo is not None


def test_review_agreement_and_stats(service: TriageService, sessions) -> None:  # type: ignore[no-untyped-def]
    with session_scope(sessions) as s:
        repo = Repository(s)
        a = repo.add_ticket(service.triage("VPN", "VPN keeps dropping at home"), channel="api")
        b = repo.add_ticket(service.triage("Printer", "Printer is offline on floor 3"), channel="api")
        assert a.result and b.result
        same = ReviewInput(a.result.category, a.result.ticket_type, a.result.impact, a.result.urgency)
        assert repo.add_review(a, "analyst-1", same).agreed
        changed = ReviewInput("hardware", b.result.ticket_type, b.result.impact, b.result.urgency)
        assert not repo.add_review(b, "analyst-1", changed).agreed
    with session_scope(sessions) as s:
        stats = Repository(s).stats()
        assert stats["total"] == 2 and stats["reviewed"] == 2 and stats["review_agreement"] == 0.5
        items, total = Repository(s).list(status="reviewed")
        assert total == 2 and len(items) == 2


def test_retention_purges_old_tickets_but_keeps_demo(service: TriageService, sessions) -> None:  # type: ignore[no-untyped-def]
    old = datetime.now(UTC) - timedelta(days=40)
    with session_scope(sessions) as s:
        repo = Repository(s)
        repo.add_ticket(service.triage("Old", "Old ticket about the VPN"), channel="api", created_at=old)
        repo.add_ticket(
            service.triage("Demo", "Demo ticket about printing"), channel="api", is_seed=True, created_at=old
        )
        repo.add_ticket(service.triage("New", "New ticket about Outlook"), channel="api")
    with session_scope(sessions) as s:
        assert Repository(s).purge_older_than(datetime.now(UTC) - timedelta(days=30)) == 1
    with session_scope(sessions) as s:
        subjects = sorted(s.execute(select(Ticket.subject)).scalars())
        assert subjects == ["Demo", "New"]


def test_audit_events_have_no_ticket_text(service: TriageService, sessions) -> None:  # type: ignore[no-untyped-def]
    with session_scope(sessions) as s:
        repo = Repository(s)
        t = repo.add_ticket(service.triage("VPN", "VPN keeps dropping"), channel="api")
        repo.audit("tester", "ticket.submitted", t.id, channel="api")
    with session_scope(sessions) as s:
        event = s.execute(select(AuditEvent)).scalar_one()
        assert event.details == {"channel": "api"} and event.actor == "tester"


def test_naive_datetimes_are_refused(service: TriageService, sessions) -> None:  # type: ignore[no-untyped-def]
    result = service.triage("VPN", "VPN keeps dropping")
    with pytest.raises(Exception, match="naive datetime"), session_scope(sessions) as s:
        Repository(s).add_ticket(result, channel="api", created_at=datetime(2026, 1, 1))


def test_entra_sid_and_grant_statements() -> None:
    client_id = "6e0c4d2f-4f1b-4a3c-9d8e-1f2a3b4c5d6e"
    assert entra_sid(client_id) == "0x2F4D0C6E1B4F3C4A9D8E1F2A3B4C5D6E"
    statements = grant_statements("id-triage-app", client_id)
    assert (
        "CREATE USER [id-triage-app] WITH SID = 0x2F4D0C6E1B4F3C4A9D8E1F2A3B4C5D6E, TYPE = E" in statements[0]
    )
    assert any("db_datawriter" in s for s in statements)
    with pytest.raises(ValueError, match="unsafe"):
        grant_statements("x]; DROP TABLE tickets; --", client_id)
    with pytest.raises(ValueError, match="badly formed"):
        grant_statements("ok-name", "not-a-guid")


def test_token_struct_layout() -> None:
    packed = token_struct("ab")
    assert packed[:4] == (4).to_bytes(4, "little") and packed[4:] == "ab".encode("utf-16-le")
