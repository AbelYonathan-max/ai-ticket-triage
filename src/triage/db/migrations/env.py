"""Alembic environment. Uses the app's own engine, so Azure SQL gets the managed identity token."""

from alembic import context

from triage.db.models import Base

target_metadata = Base.metadata
config = context.config


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    from triage.db.session import make_engine
    from triage.settings import get_settings

    engine = make_engine(get_settings())
    with engine.connect() as conn:
        _run(conn)
        conn.commit()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported; run against a database")
run_migrations_online()
