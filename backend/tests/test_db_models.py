import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from verdict.db.models import Base, Claim, Job, LedgerEntry, Submission, User, uuid7
from verdict.db.session import make_engine

TEST_DB = os.getenv("TEST_DATABASE_URL", "")


def test_uuid7_is_versioned_and_time_ordered():
    ids = [uuid7() for _ in range(200)]
    assert all(u.version == 7 and u.variant == "specified in RFC 4122" for u in ids)
    assert len(set(ids)) == 200
    assert ids[0].int >> 80 <= ids[-1].int >> 80      # timestamp prefix never goes backwards


def test_money_round_trips_as_exact_decimal(Session, make_job):
    job_id = make_job(amount="81.50")
    with Session() as s:
        amount = s.get(Job, job_id).amount
    assert isinstance(amount, Decimal) and amount == Decimal("81.50")


def test_check_constraints_reject_bad_money(Session, make_job):
    job_id = make_job()
    with pytest.raises(IntegrityError), Session.begin() as s:
        s.add(LedgerEntry(job_id=job_id, account="x", debit=Decimal("1.00"),
                          credit=Decimal("1.00"), ref="r"))


def test_one_graded_submission_per_worker_per_job(Session, make_job):
    job_id = make_job()
    with Session.begin() as s:
        w = User(email="w@example.com", role="worker")
        s.add(w)
        s.flush()
        claim = Claim(job_id=job_id, worker_id=w.id,
                      deadline_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(claim)
        s.flush()
        sub = dict(claim_id=claim.id, job_id=job_id, worker_id=w.id, r2_key="k", sha256="0" * 64)
        s.add(Submission(**sub))
    with pytest.raises(IntegrityError), Session.begin() as s:
        s.add(Submission(**sub))


@pytest.mark.skipif(bool(TEST_DB), reason="schema check uses a scratch SQLite file")
def test_migration_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend" / "migrations"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={url}"]})()
    command.upgrade(cfg, "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}),
                                Base.metadata)
    engine.dispose()
    assert diff == [], diff
    command.downgrade(cfg, "base")
