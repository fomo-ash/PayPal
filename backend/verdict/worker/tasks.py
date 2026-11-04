"""Celery tasks. Thin wrappers: the logic lives in worker.money and worker.timers, which are
tested without Celery or Redis. Each task is idempotent and safe to run twice at the same time
(outbox rows are taken with FOR UPDATE SKIP LOCKED; state moves are compare-and-set).

Phase 3 adds grade_submission(sub_id) and judge_submission(sub_id).
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.orm import sessionmaker

from verdict.config import get_settings
from verdict.db.session import make_session_factory
from verdict.paypal.client import PayPalClient
from verdict.worker import money, timers
from verdict.worker.celery_app import app


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
