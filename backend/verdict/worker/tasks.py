"""Celery tasks. Thin wrappers: the logic lives in worker.money and worker.timers, which are
tested without Celery or Redis. Each task is idempotent and safe to run twice at the same time
(outbox rows are taken with FOR UPDATE SKIP LOCKED; state moves are compare-and-set).

grade_submission retries with backoff while the sandbox is unavailable; requeue_stale picks
up any submission whose task was lost. The AI review runs inside grade_submission.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from sqlalchemy.orm import sessionmaker

from verdict.config import get_settings
from verdict.db.session import make_session_factory
from verdict.judge.llm import LLMClient, optional_client
from verdict.paypal.client import PayPalClient
from verdict.sandbox.e2b_runner import SandboxUnavailable
from verdict.sandbox.runner import Runner
from verdict.storage import BlobStore, LocalBlobStore
from verdict.worker import grading, money, timers
from verdict.worker.celery_app import app
from verdict.worker.runners import make_runner


@lru_cache
def session_factory() -> sessionmaker:
    return make_session_factory(get_settings().database_url)


@lru_cache
def paypal() -> PayPalClient:
    cfg = get_settings()
    return PayPalClient(cfg.paypal_base_url, cfg.paypal_client_id, cfg.paypal_secret)


@app.task(name="verdict.worker.tasks.process_outbox")
def process_outbox() -> list[str]:
    return [f"{o.action}:{o.result}" for o in money.process_outbox(session_factory(), paypal())]


@app.task(name="verdict.worker.tasks.expire_claims")
def expire_claims() -> int:
    return timers.expire_claims(session_factory())


@app.task(name="verdict.worker.tasks.expire_holds")
def expire_holds() -> int:
    return timers.expire_holds(session_factory())


@lru_cache
def store() -> BlobStore:
    return LocalBlobStore(get_settings().blob_dir)


@lru_cache
def runner() -> Runner:
    return make_runner(get_settings())


@lru_cache
def llm() -> LLMClient | None:
    return optional_client(get_settings())


@app.task(name="verdict.worker.tasks.grade_submission", bind=True, max_retries=10)
def grade_submission(self, submission_id: str) -> str:
    try:
        out = grading.grade_submission(
            session_factory(), store(), runner(), uuid.UUID(submission_id),
            timeout_s=get_settings().sandbox_test_timeout_ms / 1000, llm=llm())
    except SandboxUnavailable as exc:
        raise self.retry(exc=exc, countdown=min(30 * 2 ** self.request.retries, 600)) from exc
    if out.state in {"CAPTURING", "VOIDING"}:
        process_outbox.delay()                 # don't wait for the next beat tick
    return f"{out.result}:{out.state}"


@app.task(name="verdict.worker.tasks.requeue_stale")
def requeue_stale() -> int:
    ids = grading.stale_submissions(session_factory())
    for sid in ids:
        grade_submission.delay(str(sid))
    return len(ids)
