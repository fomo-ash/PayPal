"""Celery tasks (Phase 2-3). Each is idempotent, keyed by (job_id, step).
validate_suite(job_id) · grade_submission(sub_id) · judge_submission(sub_id)
process_outbox() · expire_claims() · check_authorizations()"""
