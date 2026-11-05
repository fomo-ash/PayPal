"""LOCAL DEMO ONLY (`make local`, INLINE_WORKER=true): grade and settle in a background
thread of the API process, so the whole flow runs on one laptop without Redis or Celery.
Production uses the Celery tasks in worker/tasks.py; the logic called here is the same.
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


def run(svc: Any, submission_id: uuid.UUID) -> None:
    try:
        out = grading.grade_submission(svc.Session, svc.store, svc.runner, submission_id,
                                       timeout_s=svc.settings.sandbox_test_timeout_ms / 1000)
        log.warning("graded %s → %s", submission_id, out)
        deadline = time.monotonic() + MAX_WAIT_S
        while time.monotonic() < deadline:
            for o in money.process_outbox(svc.Session, svc.paypal):
                log.warning("outbox %s → %s %s", o.action, o.result, o.detail)
            state = _state(svc, submission_id)
            if state not in WAIT_STATES:
                log.warning("job settled: %s", state)
                return
            time.sleep(POLL_S)
        log.warning("still %s after %ss; run the Celery worker to finish", state, MAX_WAIT_S)
    except Exception:
        log.exception("inline worker failed for %s", submission_id)


def _state(svc: Any, submission_id: uuid.UUID) -> str | None:
    with svc.Session() as s:
        sub = s.get(Submission, submission_id)
        job = s.get(Job, sub.job_id) if sub else None
        return job.state if job else None
