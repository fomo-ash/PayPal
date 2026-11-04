"""Transactional outbox (Phase 2).

A job state change and the PayPal action it requires are written in ONE database transaction:
    UPDATE jobs SET state='CAPTURING' ...;
    INSERT INTO outbox(action='capture', key='<job>:capture', ...)
The money worker polls `outbox` (SELECT ... FOR UPDATE SKIP LOCKED), calls PayPal with
PayPal-Request-Id = outbox.idempotency_key, records the PayPal response, advances the state,
and marks the row done. A crash at any point is safe: the retry reuses the same key, so PayPal
returns the original result instead of capturing or paying twice.
"""
