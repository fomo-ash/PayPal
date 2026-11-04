"""Shared fixtures.

Database tests run on in-memory SQLite by default (no services needed, so CI stays simple).
Set TEST_DATABASE_URL to a throwaway Postgres to run the same tests there, e.g.
    TEST_DATABASE_URL=postgresql+psycopg://verdict:verdict@localhost:5432/verdict_test pytest
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool

from verdict.db.models import Base, Job, User
from verdict.db.session import make_engine, make_session_factory

TEST_DB = os.getenv("TEST_DATABASE_URL", "")


@pytest.fixture
def engine():
    if TEST_DB:
        eng = make_engine(TEST_DB)
        Base.metadata.drop_all(eng)
    else:
        eng = make_engine("sqlite://", connect_args={"check_same_thread": False},
                          poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def Session(engine):  # noqa: N802 - it is a factory, named like a class on purpose
    return make_session_factory(engine)


@pytest.fixture
def make_job(Session):
    """Create a buyer + job in the given state and return the job id."""
    def _make(state: str = "DRAFT", amount: str = "100.00", **kw):
        with Session.begin() as s:
            buyer = User(email="buyer@example.com", role="buyer")
            s.add(buyer)
            s.flush()
            job = Job(buyer_id=buyer.id, title="log parser", amount=Decimal(amount),
                      min_score=Decimal("0.50"), fee_bps=500, state=state, **kw)
            s.add(job)
            s.flush()
            return job.id
    return _make
