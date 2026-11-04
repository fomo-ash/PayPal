"""The ONLY code that writes `jobs.state`.

`move_job` = validate (core.state_machine) + compare-and-set UPDATE + audit entry + outbox rows,
all in the caller's transaction. Two workers can never both move the same job: the second
UPDATE matches 0 rows and raises StaleState, and its whole transaction rolls back.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from verdict.core.audit import chain_hash
from verdict.core.outbox import Action, enqueue, jsonable
from verdict.core.state_machine import JobState, transition
from verdict.db.models import AuditLog, Job

GENESIS = "0" * 64


class StaleState(Exception):
    """The job was not in the expected state: someone else moved it first."""


@dataclass(frozen=True)
class OutboxItem:
    action: Action
    payload: dict[str, Any] = field(default_factory=dict)
    tag: str = ""


def move_job(session: Session, job_id: uuid.UUID, expected: JobState | str,
             target: JobState | str, *, reason: str = "", data: dict[str, Any] | None = None,
             outbox: Iterable[OutboxItem] = (), fields: dict[str, Any] | None = None) -> JobState:
    """Move a job from `expected` to `target`. `fields` are extra Job columns set atomically."""
    new = transition(expected, target)
    values: dict[str, Any] = {"state": new.value, **(fields or {})}
    res = session.execute(
        update(Job).where(Job.id == job_id, Job.state == JobState(expected).value)
        .values(**values).execution_options(synchronize_session="fetch")
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        raise StaleState(f"job {job_id} is not in state {expected}")
    append_audit(session, job_id, f"{JobState(expected).value}->{new.value}",
                 {"reason": reason, **(data or {})})
    for item in outbox:
        enqueue(session, job_id, item.action, item.payload, tag=item.tag)
    return new


def append_audit(session: Session, job_id: uuid.UUID, event: str,
                 payload: dict[str, Any]) -> AuditLog:
    last = session.execute(
        select(AuditLog.seq, AuditLog.hash).where(AuditLog.job_id == job_id)
        .order_by(AuditLog.seq.desc()).limit(1)
    ).first()
    seq, prev = (last.seq + 1, last.hash) if last else (1, GENESIS)
    body = jsonable(payload)
    row = AuditLog(job_id=job_id, seq=seq, event=event, payload=body, prev_hash=prev,
                   hash=chain_hash(prev, _audit_doc(job_id, seq, event, body)))
    session.add(row)
    session.flush()
    return row


def verify_audit_chain(session: Session, job_id: uuid.UUID) -> bool:
    """Recompute every hash. Editing, deleting or reordering any past entry breaks the chain."""
    prev = GENESIS
    rows = session.scalars(select(AuditLog).where(AuditLog.job_id == job_id)
                           .order_by(AuditLog.seq))
    for i, row in enumerate(rows, start=1):
        if row.seq != i or row.prev_hash != prev:
            return False
        if row.hash != chain_hash(prev, _audit_doc(job_id, row.seq, row.event, row.payload)):
            return False
        prev = row.hash
    return True


def _audit_doc(job_id: uuid.UUID, seq: int, event: str, payload: Any) -> dict[str, Any]:
    return {"job_id": str(job_id), "seq": seq, "event": event, "payload": payload}
