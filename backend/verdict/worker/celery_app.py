"""Celery app (Phase 2). Queues: grading (sandbox-heavy), judge (LLM), money (PayPal, concurrency 1).
Beat schedule: claim deadlines every minute; authorization honor-period check hourly."""
