"""SQLAlchemy 2.0 models. Table list and columns: docs/DATA_MODEL.md.

Rules:
  * Money is NUMERIC(12,2) and Python Decimal. Never float.
  * Timestamps are timezone-aware UTC.
  * IDs are UUID v7 (time-ordered, so indexes stay compact and rows sort by creation).
  * Types are portable: Postgres in dev/prod, SQLite in the offline unit tests.
"""

from __future__ import annotations

import secrets
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uuid7() -> uuid.UUID:
    """RFC 9562 UUID v7: 48-bit unix ms timestamp, version 7, variant 10, 74 random bits."""
    ms = time.time_ns() // 1_000_000
    rand = secrets.randbits(74)
    value = ((ms & ((1 << 48) - 1)) << 80) | (0x7 << 76) | ((rand >> 62) << 64) \
        | (0b10 << 62) | (rand & ((1 << 62) - 1))
    return uuid.UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes for TZ columns; every value we store is UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


Money = Numeric(12, 2, asdecimal=True)
Fraction = Numeric(5, 4, asdecimal=True)          # weights, min_score: 0.0000 … 1.0000
JsonDoc = JSON().with_variant(JSONB(), "postgresql")
TZ = DateTime(timezone=True)

# Deterministic constraint names so Alembic migrations are stable across databases.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid7)


def _created() -> Mapped[datetime]:
    return mapped_column(TZ, default=utcnow, nullable=False)


# ── people ───────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _id()
    paypal_payer_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    email: Mapped[str | None] = mapped_column(String(254))
    display_name: Mapped[str] = mapped_column(String(80), default="")
    role: Mapped[str] = mapped_column(String(16), default="buyer")      # buyer | worker | admin
    created_at: Mapped[datetime] = _created()
    __table_args__ = (CheckConstraint("role IN ('buyer','worker','admin')", name="role"),)


class Agent(Base):
    """Every AI agent has an accountable human owner; payouts go to the owner."""
    __tablename__ = "agents"
    id: Mapped[uuid.UUID] = _id()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(80))
    api_key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = _created()


# ── jobs and suites ──────────────────────────────────────────────────────────
class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = _id()
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    spec_md: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    min_score: Mapped[Decimal] = mapped_column(Fraction)
    fee_bps: Mapped[int] = mapped_column(Integer)
    deadline_hours: Mapped[int] = mapped_column(Integer, default=24)
    state: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    suite_sha256: Mapped[str | None] = mapped_column(String(64))
    paypal_order_id: Mapped[str | None] = mapped_column(String(64))
    authorization_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    authorized_at: Mapped[datetime | None] = mapped_column(TZ)
    honor_expires_at: Mapped[datetime | None] = mapped_column(TZ)
    capture_id: Mapped[str | None] = mapped_column(String(64))
    payout_batch_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("min_score >= 0 AND min_score <= 1", name="min_score_range"),
        CheckConstraint("fee_bps >= 0 AND fee_bps <= 10000", name="fee_range"),
    )


class TestGroup(Base):
    __tablename__ = "test_groups"
    __test__ = False                                    # not a pytest test class
    id: Mapped[uuid.UUID] = _id()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    weight: Mapped[Decimal] = mapped_column(Fraction)
    n_tests: Mapped[int] = mapped_column(Integer)
    fresh_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("job_id", "name", name="job_group"),)


class Suite(Base):
    __tablename__ = "suites"
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    r2_key: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    reference_key: Mapped[str] = mapped_column(String(300))
    generator_key: Mapped[str | None] = mapped_column(String(300))
    validated_at: Mapped[datetime | None] = mapped_column(TZ)


class SpecCheck(Base):
    __tablename__ = "spec_checks"
    id: Mapped[uuid.UUID] = _id()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    test_id: Mapped[str] = mapped_column(String(80))
    implied: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text, default="")


# ── work ─────────────────────────────────────────────────────────────────────
class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = _id()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    accepted_at: Mapped[datetime] = _created()
    deadline_at: Mapped[datetime] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(String(16), default="active")   # active|submitted|expired


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[uuid.UUID] = _id()
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    r2_key: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    grading_seed: Mapped[str | None] = mapped_column(String(20))   # secret seed, kept for replay
    submitted_at: Mapped[datetime] = _created()
    # One graded submission per worker per job: stops probing the hidden tests (W6).
    __table_args__ = (UniqueConstraint("job_id", "worker_id", name="one_per_worker"),)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = _id()
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))                 # examples | hidden | fresh
    group_name: Mapped[str] = mapped_column(String(40))
    passed: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    flaky_ids: Mapped[list[Any]] = mapped_column(JsonDoc, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JsonDoc, default=dict)


class ScanFinding(Base):
    __tablename__ = "scan_findings"
    id: Mapped[uuid.UUID] = _id()
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    rule: Mapped[str] = mapped_column(String(60))
    file: Mapped[str] = mapped_column(String(300))
    line: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    hard_signal: Mapped[str | None] = mapped_column(String(40))


class AIReview(Base):
    __tablename__ = "ai_reviews"
    id: Mapped[uuid.UUID] = _id()
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    model: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(20))
    findings: Mapped[list[Any]] = mapped_column(JsonDoc, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _created()


class Verdict(Base):
    __tablename__ = "verdicts"
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"),
                                                     primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), unique=True)
    raw_score: Mapped[Decimal] = mapped_column(Fraction)
    score: Mapped[Decimal] = mapped_column(Fraction)
    capture: Mapped[Decimal] = mapped_column(Money)
    fee: Mapped[Decimal] = mapped_column(Money)
    worker_amount: Mapped[Decimal] = mapped_column(Money)
    released: Mapped[Decimal] = mapped_column(Money)
    settlement: Mapped[str] = mapped_column(String(14))           # CAPTURE | VOID | HUMAN_REVIEW
    policy_reason: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(String(10), default="policy")   # policy | human
    decided_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("capture >= 0 AND fee >= 0 AND worker_amount >= 0 AND released >= 0",
                        name="money_non_negative"),
        # Exact on Postgres NUMERIC(12,2) (any real difference is >= 0.01); also correct on
        # SQLite, which stores NUMERIC as a float in the unit tests.
        CheckConstraint("abs(capture - fee - worker_amount) < 0.005", name="capture_split"),
    )


# ── money plumbing ───────────────────────────────────────────────────────────
class Outbox(Base):
    """PayPal actions to perform. Written in the SAME transaction as the state change."""
    __tablename__ = "outbox"
    id: Mapped[uuid.UUID] = _id()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDoc, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="pending")   # pending|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = _created()
    last_error: Mapped[str | None] = mapped_column(Text)
    response: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc)
    created_at: Mapped[datetime] = _created()
    done_at: Mapped[datetime | None] = mapped_column(TZ)
    __table_args__ = (
        CheckConstraint("status IN ('pending','done','failed')", name="status"),
        Index("ix_outbox_due", "status", "next_attempt_at"),
    )


class PayPalEvent(Base):
    __tablename__ = "paypal_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)   # PayPal event id → dedupe
    type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JsonDoc)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = _created()


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[uuid.UUID] = _id()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    account: Mapped[str] = mapped_column(String(30))
    debit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    credit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    ref: Mapped[str] = mapped_column(String(120), index=True)        # one balanced posting
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="non_negative"),
        CheckConstraint("(debit = 0) OR (credit = 0)", name="one_side"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = _id()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDoc, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
    # (job_id, seq) unique: two writers can never both append entry N to the same chain.
    __table_args__ = (UniqueConstraint("job_id", "seq", name="job_seq"),)


class Blob(Base):
    """Blob store in Postgres (BLOB_BACKEND=db), for deploys where the API and the worker do not
    share a disk. Suites and submissions are small (hard limit 1 MB per submission)."""
    __tablename__ = "blobs"
    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _created()


class Receipt(Base):
    __tablename__ = "receipts"
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    json_key: Mapped[str] = mapped_column(String(300))
    pdf_key: Mapped[str | None] = mapped_column(String(300))
    signature: Mapped[str] = mapped_column(Text)
    public_key_id: Mapped[str] = mapped_column(String(40))
    issued_at: Mapped[datetime] = _created()
