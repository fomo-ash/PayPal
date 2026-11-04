"""Transactional outbox.

A job state change and the PayPal action it requires are written in ONE database transaction:
    UPDATE jobs SET state='CAPTURING' WHERE id=:id AND state='JUDGING';
    INSERT INTO outbox(action='capture', idempotency_key='verdict-<job>-capture', ...);
The money worker (verdict.worker.money) picks due rows (FOR UPDATE SKIP LOCKED on Postgres),
calls PayPal with PayPal-Request-Id = idempotency_key, records the response, advances the job
and marks the row done, again in one transaction. A crash at any point is safe: the retry reuses
the same key, so PayPal returns the original result instead of capturing or paying twice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


class Action(StrEnum):
    CAPTURE = "capture"              # capture(final_capture=true) → remainder released
    VOID = "void"                    # void the whole authorization
    PAYOUT = "payout"                # Payouts API → worker
    PAYOUT_STATUS = "payout_status"  # poll a payout batch until the item is final
    REAUTHORIZE = "reauthorize"


def idempotency_key(job_id: uuid.UUID, action: Action | str, tag: str = "") -> str:
    """Deterministic per (job, action[, tag]). Also used as PayPal-Request-Id and, for payouts,
    as sender_batch_id (PayPal rejects a reused sender_batch_id: a second payout is impossible).
    """
    key = f"verdict-{job_id}-{Action(action).value}"
    return f"{key}-{tag}" if tag else key


def jsonable(value: Any) -> Any:
    """Decimal → str (exact), UUID/datetime → str, recursively. JSON never sees a float."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID | datetime):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, float):
        raise TypeError("floats are not allowed in money payloads")
    return value


def enqueue(session: Session, job_id: uuid.UUID, action: Action | str,
            payload: dict[str, Any] | None = None, *, tag: str = "",
            delay: timedelta | None = None) -> Any:
    """Add an outbox row in the caller's transaction. Re-enqueuing the same key is a no-op."""
    from verdict.db.models import Outbox, utcnow

    key = idempotency_key(job_id, action, tag)
    existing = session.scalar(select(Outbox).where(Outbox.idempotency_key == key))
    if existing is not None:
        return existing
    row = Outbox(job_id=job_id, action=Action(action).value, idempotency_key=key,
                 payload=jsonable(payload or {}),
                 next_attempt_at=utcnow() + (delay or timedelta(0)))
    session.add(row)
    session.flush()
    return row
