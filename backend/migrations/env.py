"""Alembic environment. The database URL comes from (in order):
`alembic -x url=...`, the DATABASE_URL environment variable / .env (verdict.config)."""

from alembic import context
from sqlalchemy import pool

from verdict.config import get_settings
from verdict.db.models import Base
from verdict.db.session import make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return context.get_x_argument(as_dictionary=True).get("url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        connectable = make_engine(_url(), poolclass=pool.NullPool).connect()
    with connectable as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
