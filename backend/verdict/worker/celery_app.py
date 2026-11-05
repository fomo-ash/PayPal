"""Celery app. Queues: grading (sandbox-heavy), judge (LLM), money (PayPal, run with
concurrency 1). Beat: outbox every 30s, claim deadlines every minute, holds every 10 minutes,
lost grading tasks every 5 minutes.

Run:  make worker   (celery -A verdict.worker.celery_app worker -Q money,grading,judge)
      make beat
"""

from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from verdict.config import get_settings

app = Celery("verdict", broker=get_settings().redis_url, include=["verdict.worker.tasks"])
app.conf.update(
    task_acks_late=True,                 # a crashed worker's task is redelivered…
    task_reject_on_worker_lost=True,     # …and every task is idempotent, so that is safe
    worker_prefetch_multiplier=1,
    task_default_queue="grading",
    task_routes={
        "verdict.worker.tasks.process_outbox": {"queue": "money"},
        "verdict.worker.tasks.expire_holds": {"queue": "money"},
        "verdict.worker.tasks.expire_claims": {"queue": "money"},
        "verdict.worker.tasks.grade_submission": {"queue": "grading"},
        "verdict.worker.tasks.requeue_stale": {"queue": "grading"},
        "verdict.worker.tasks.judge_submission": {"queue": "judge"},
    },
    beat_schedule={
        "outbox": {"task": "verdict.worker.tasks.process_outbox", "schedule": 30.0},
        "claims": {"task": "verdict.worker.tasks.expire_claims", "schedule": 60.0},
        "holds": {"task": "verdict.worker.tasks.expire_holds", "schedule": 600.0},
        "stale_grading": {"task": "verdict.worker.tasks.requeue_stale", "schedule": 300.0},
    },
    timezone="UTC",
)
