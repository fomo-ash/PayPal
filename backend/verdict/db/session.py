"""SQLAlchemy engine and session factory.

Usage:
    SessionLocal = make_session_factory(settings.database_url)
    with SessionLocal.begin() as s:      # commits on success, rolls back on any exception
        ...
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker


def make_engine(url: str, **kw) -> Engine:
    engine = create_engine(url, pool_pre_ping=True, future=True, **kw)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):                      # SQLite ignores FKs unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


def make_session_factory(url_or_engine: str | Engine) -> sessionmaker:
    engine = make_engine(url_or_engine) if isinstance(url_or_engine, str) else url_or_engine
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
