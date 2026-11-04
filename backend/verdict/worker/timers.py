"""Timers run by Celery Beat. Each is idempotent and moves jobs only through db.repo.move_job.

expire_claims  CLAIMED past its deadline → OPEN (the worker gets nothing; others may claim)
expire_holds   a hold close to the end of PayPal's 3-day honor period → VOIDING (MVP rule).
               Reauthorization (days 4-29) is a later option; see docs/STATE_MACHINE.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from verdict.core.outbox import Action
from verdict.core.state_machine import JobState as S
from verdict.db.models import Claim, Job, utcnow
from verdict.db.repo import OutboxItem, StaleState, move_job

HOLD_SAFETY_MARGIN = timedelta(hours=12)   # void while the funds are still guaranteed
NOT_STARTED = (S.FUNDED, S.OPEN, S.CLAIMED)


def expire_claims(Session: sessionmaker, now: datetime | None = None) -> int:  # noqa: N803
    now = now or utcnow()
    moved = 0
    with Session.begin() as s:
        rows = s.execute(
            select(Claim.id, Claim.job_id).join(Job, Job.id == Claim.job_id)
            .where(Claim.status == "active", Claim.deadline_at < now,
                   Job.state == S.CLAIMED.value)
        ).all()
    for claim_id, job_id in rows:
        try:
            with Session.begin() as s:
                move_job(s, job_id, S.CLAIMED, S.OPEN, reason="claim deadline missed",
                         data={"claim_id": claim_id})
                claim = s.get(Claim, claim_id)
                if claim is not None:
                    claim.status = "expired"
            moved += 1
        except StaleState:    # the worker submitted at the last second: fine, leave it
            continue
    return moved


def expire_holds(Session: sessionmaker, now: datetime | None = None) -> int:  # noqa: N803
    """Void holds that are about to lose PayPal's funding guarantee before work has started,
    and holds still waiting in SUBMITTED after the guarantee has already ended."""
    now = now or utcnow()
    with Session.begin() as s:
        rows = s.execute(
            select(Job.id, Job.state, Job.honor_expires_at)
            .where(Job.state.in_([st.value for st in (*NOT_STARTED, S.SUBMITTED)]),
                   Job.honor_expires_at.is_not(None))
        ).all()
    moved = 0
    for job_id, state, honor in rows:
        honor = honor if honor.tzinfo else honor.replace(tzinfo=now.tzinfo)  # SQLite drops tz
        due = now >= honor - HOLD_SAFETY_MARGIN if state != S.SUBMITTED else now >= honor
        if not due:
            continue
        try:
            with Session.begin() as s:
                move_job(s, job_id, state, S.VOIDING, reason="authorization honor period ending",
                         outbox=[OutboxItem(Action.VOID)])
            moved += 1
        except StaleState:
            continue
    return moved
