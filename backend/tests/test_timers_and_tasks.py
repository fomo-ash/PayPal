from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from verdict.core.state_machine import JobState as S
from verdict.db.models import Claim, Outbox, User
from verdict.db.repo import move_job
from verdict.worker import timers

T0 = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=1)  # just after real "now"


def claimed_job(Session, make_job, deadline):
    job_id = make_job(S.OPEN, authorization_id="A1", honor_expires_at=T0 + timedelta(days=3))
    with Session.begin() as s:
        w = User(email="w@example.com", role="worker")
        s.add(w)
        s.flush()
        s.add(Claim(job_id=job_id, worker_id=w.id, deadline_at=deadline))
        move_job(s, job_id, S.OPEN, S.CLAIMED)
    return job_id


def state(Session, job_id):
    from verdict.db.models import Job
    with Session() as s:
        return s.get(Job, job_id).state


def test_missed_claim_deadline_reopens_the_job(Session, make_job):
    job_id = claimed_job(Session, make_job, deadline=T0 + timedelta(hours=24))
    assert timers.expire_claims(Session, now=T0 + timedelta(hours=23)) == 0
    assert timers.expire_claims(Session, now=T0 + timedelta(hours=25)) == 1
    assert state(Session, job_id) == "OPEN"
    with Session() as s:
        assert s.scalar(select(Claim.status)) == "expired"
    assert timers.expire_claims(Session, now=T0 + timedelta(hours=26)) == 0   # idempotent


def test_hold_is_voided_before_the_honor_period_ends(Session, make_job):
    job_id = make_job(S.OPEN, authorization_id="A1", honor_expires_at=T0 + timedelta(days=3))
    assert timers.expire_holds(Session, now=T0 + timedelta(days=2)) == 0
    assert timers.expire_holds(Session, now=T0 + timedelta(days=2, hours=13)) == 1
    assert state(Session, job_id) == "VOIDING"
    with Session() as s:
        assert s.scalar(select(Outbox.action)) == "void"
    assert timers.expire_holds(Session, now=T0 + timedelta(days=3)) == 0      # idempotent


def test_job_being_graded_is_not_voided_early(Session, make_job):
    job_id = make_job(S.SUBMITTED, authorization_id="A1",
                      honor_expires_at=T0 + timedelta(days=3))
    assert timers.expire_holds(Session, now=T0 + timedelta(days=2, hours=20)) == 0
    assert timers.expire_holds(Session, now=T0 + timedelta(days=3, minutes=1)) == 1
    assert state(Session, job_id) == "VOIDING"


def test_celery_routes_money_tasks_to_the_money_queue_and_schedules_timers():
    from verdict.worker.celery_app import app
    routes = app.conf.task_routes
    assert routes["verdict.worker.tasks.process_outbox"]["queue"] == "money"
    assert {e["task"] for e in app.conf.beat_schedule.values()} == {
        "verdict.worker.tasks.process_outbox", "verdict.worker.tasks.expire_claims",
        "verdict.worker.tasks.expire_holds"}
    import verdict.worker.tasks as tasks
    assert tasks.process_outbox.name in app.tasks
