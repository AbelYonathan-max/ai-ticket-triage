"""Database engine and sessions.

Locally the app uses SQLite, or SQL Server with a SQL login in docker compose. In Azure it connects
to Azure SQL with a Microsoft Entra access token from its managed identity: the server has SQL
authentication switched off, so there is no database password anywhere.

Azure SQL serverless pauses when idle and the first connection after a pause fails while it resumes
(error 40613), so new connections are retried with backoff.
"""

from __future__ import annotations

import logging
import struct
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from triage.settings import Settings

log = logging.getLogger(__name__)

SQL_COPT_SS_ACCESS_TOKEN = 1256  # pyodbc connection attribute for an Entra access token
SQL_SCOPE = "https://database.windows.net/.default"
TRANSIENT_SQL_ERRORS = (
    "40613",
    "40197",
    "40501",
    "49918",
    "49919",
    "49920",
    "4060",
    "10928",
    "10929",
    "HYT00",
)


def token_struct(token: str) -> bytes:
    """Pack an access token the way the ODBC driver expects it."""
    raw = token.encode("utf-16-le")
    return struct.pack(f"<I{len(raw)}s", len(raw), raw)


def azure_sql_url(server: str, database: str) -> URL:
    odbc = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{server},1433;Database={database};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30"
    )
    return URL.create("mssql+pyodbc", query={"odbc_connect": odbc})


def _is_transient(exc: BaseException) -> bool:
    text = str(exc)
    return any(code in text for code in TRANSIENT_SQL_ERRORS)


def make_engine(settings: Settings, credential: Any | None = None) -> Engine:
    if settings.database_url:
        url = settings.database_url
        if url.startswith("sqlite"):
            kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
            if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
                kwargs["poolclass"] = StaticPool
            engine = create_engine(url, **kwargs)

            @event.listens_for(engine, "connect")
            def _sqlite_pragmas(dbapi_conn: Any, _: Any) -> None:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

            return engine
        return create_engine(url, pool_pre_ping=True, pool_recycle=1800)

    if not (settings.sql_server and settings.sql_database):
        raise RuntimeError("no database configured: set TRIAGE_DATABASE_URL or TRIAGE_SQL_SERVER")
    if credential is None:
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

        credential = (
            ManagedIdentityCredential(client_id=settings.azure_client_id)
            if settings.azure_client_id
            else DefaultAzureCredential()
        )
    engine = create_engine(
        azure_sql_url(settings.sql_server, settings.sql_database),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=5,
    )

    @event.listens_for(engine, "do_connect")
    def _connect_with_token(dialect: Any, conn_rec: Any, cargs: Any, cparams: dict[str, Any]) -> Any:
        delay = 2.0
        for attempt in range(1, 8):
            token = credential.get_token(SQL_SCOPE).token
            cparams["attrs_before"] = {SQL_COPT_SS_ACCESS_TOKEN: token_struct(token)}
            try:
                return dialect.connect(*cargs, **cparams)
            except Exception as exc:
                if attempt == 7 or not _is_transient(exc):
                    raise
                log.warning("sql_connect_retry", extra={"attempt": attempt, "delay_s": delay})
                time.sleep(delay)
                delay = min(delay * 2, 20.0)
        raise RuntimeError("unreachable")

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: Callable[[], Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
