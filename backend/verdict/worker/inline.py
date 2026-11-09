"""Single-process mode (INLINE_WORKER=true): grade and settle in background threads of the API
process, and run the beat schedule on a ticker thread, so the whole product runs without Redis
or Celery: `make local`, and a one-service deploy. The Celery tasks in worker/tasks.py call the
same functions; everything here is safe to run twice because state moves are compare-and-set.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from verdict.db.models import Job, Submission
from verdict.worker import grading, money

log = logging.getLogger("verdict.inline")
WAIT_STATES = {"CAPTURING", "PAYING_OUT", "VOIDING"}    # keep driving the outbox while here
POLL_S = 5
MAX_WAIT_S = 600                                         # payouts can take a few minutes


def start(svc: Any, submission_id: uuid.UUID) -> None:
    threading.Thread(target=run, args=(svc, submission_id), daemon=True,
                     name=f"inline-{submission_id}").start()


def start_money(svc: Any, job_id: uuid.UUID) -> None:
    """After a human review: drive the capture/void and payout for this job."""
    threading.Thread(target=_guarded, args=(drive_money, svc, job_id), daemon=True,
                     name=f"inline-money-{job_id}").start()


def run(svc: Any, submission_id: uuid.UUID) -> None:
    _guarded(_grade_then_pay, svc, submission_id)


def _grade_then_pay(svc: Any, submission_id: uuid.UUID) -> None:
    out = grading.grade_submission(svc.Session, svc.store, svc.runner, submission_id,
                                   timeout_s=svc.settings.sandbox_test_timeout_ms / 1000,
                                   llm=svc.llm)
    log.warning("graded %s → %s", submission_id, out)
    with svc.Session() as s:
        sub = s.get(Submission, submission_id)
        job_id = sub.job_id if sub else None
    if job_id is not None:
        drive_money(svc, job_id)


def drive_money(svc: Any, job_id: uuid.UUID) -> None:
    deadline = time.monotonic() + MAX_WAIT_S
    state = None
    while time.monotonic() < deadline:
        for o in money.process_outbox(svc.Session, svc.paypal):
            log.warning("outbox %s → %s %s", o.action, o.result, o.detail)
        with svc.Session() as s:
            job = s.get(Job, job_id)
            state = job.state if job else None
        if state not in WAIT_STATES:
            log.warning("job %s settled: %s", job_id, state)
            return
        time.sleep(POLL_S)
    log.warning("still %s after %ss; run the Celery worker to finish", state, MAX_WAIT_S)


def _guarded(fn: Any, svc: Any, arg: uuid.UUID) -> None:
    try:
        fn(svc, arg)
    except Exception:
        log.exception("inline worker failed for %s", arg)


# ── single-process timers: the Celery beat schedule, for hosts that run only the API ──
SCHEDULE = (("outbox", 30), ("claims", 60), ("holds", 600), ("stale", 300))


def tick(svc: Any, due: set[str]) -> dict[str, int]:
    """Run the named jobs once. Each one is safe to run twice or concurrently."""
    from verdict.worker import timers

    done: dict[str, int] = {}
    if "outbox" in due and svc.paypal is not None:
        done["outbox"] = len(money.process_outbox(svc.Session, svc.paypal))
    if "claims" in due:
        done["claims"] = timers.expire_claims(svc.Session)
    if "holds" in due:
        done["holds"] = timers.expire_holds(svc.Session)
    if "stale" in due:
        stale = grading.stale_submissions(svc.Session)
        for sid in stale:
            start(svc, sid)
        done["stale"] = len(stale)
    return done


def start_ticker(svc: Any, period: float = 5.0) -> threading.Thread:
    def loop() -> None:
        last = {name: 0.0 for name, _ in SCHEDULE}
        while True:
            now = time.monotonic()
            due = {n for n, every in SCHEDULE if now - last[n] >= every}
            if due:
                try:
                    out = tick(svc, due)
                    if any(out.values()):
                        log.warning("ticker %s", out)
                except Exception:
                    log.exception("ticker failed")
                for n in due:
                    last[n] = now
            time.sleep(period)

    t = threading.Thread(target=loop, daemon=True, name="inline-ticker")
    t.start()
    return t
