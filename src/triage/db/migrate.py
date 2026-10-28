"""Run database migrations and grant the app's managed identity least-privilege access.

In Azure this runs as a Container Apps job under a separate "migrate" identity, which is the SQL
server's Microsoft Entra admin. The web app's own identity only gets read and write on the tables,
so a compromise of the web app cannot change the schema or grant itself more rights.
"""

from __future__ import annotations

import re
import uuid

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "triage.db:migrations")
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade(engine: Engine) -> None:
    with engine.begin() as conn:
        command.upgrade(alembic_config(conn), "head")


def entra_sid(client_id: str) -> str:
    """The SID SQL Server uses for a Microsoft Entra application: its client ID in GUID byte order."""
    return "0x" + uuid.UUID(client_id).bytes_le.hex().upper()


def grant_statements(name: str, client_id: str) -> list[str]:
    """T-SQL to create a contained user for a managed identity and give it read and write only.

    CREATE USER cannot take parameters, so both values are validated strictly before use: the name
    against a conservative pattern and the client ID by parsing it as a GUID.
    """
    if not _SAFE_NAME.match(name):
        raise ValueError(f"unsafe identity name: {name!r}")
    sid = entra_sid(client_id)
    user = f"[{name}]"
    return [
        # Both inputs were validated above.
        f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'{name}') "  # noqa: S608 # nosec B608
        f"CREATE USER {user} WITH SID = {sid}, TYPE = E",
        f"IF IS_ROLEMEMBER('db_datareader', N'{name}') = 0 ALTER ROLE db_datareader ADD MEMBER {user}",
        f"IF IS_ROLEMEMBER('db_datawriter', N'{name}') = 0 ALTER ROLE db_datawriter ADD MEMBER {user}",
    ]


def grant_app_identity(engine: Engine, name: str, client_id: str) -> None:
    if engine.dialect.name != "mssql":
        return
    with engine.begin() as conn:
        for stmt in grant_statements(name, client_id):
            conn.execute(text(stmt))
