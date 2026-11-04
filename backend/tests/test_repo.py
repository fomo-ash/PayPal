from decimal import Decimal as D

import pytest
from sqlalchemy import select, update

from verdict.core.outbox import Action, idempotency_key, jsonable
from verdict.core.state_machine import IllegalTransition
from verdict.core.state_machine import JobState as S
from verdict.db.models import AuditLog, Job, Outbox
from verdict.db.repo import OutboxItem, StaleState, move_job, verify_audit_chain


def test_move_writes_state_audit_and_outbox_together(Session, make_job):
    job_id = make_job(S.JUDGING)
    with Session.begin() as s:
        move_job(s, job_id, S.JUDGING, S.CAPTURING, reason="clear",
                 outbox=[OutboxItem(Action.CAPTURE, {"amount": D("81.50")})])
    with Session() as s:
        assert s.get(Job, job_id).state == "CAPTURING"
        row = s.scalar(select(Outbox).where(Outbox.job_id == job_id))
        assert row.action == "capture" and row.payload == {"amount": "81.50"}
        assert row.idempotency_key == idempotency_key(job_id, Action.CAPTURE)
        assert s.scalar(select(AuditLog.event).where(AuditLog.job_id == job_id)) \
            == "JUDGING->CAPTURING"


def test_failure_rolls_back_state_and_outbox(Session, make_job):
    job_id = make_job(S.JUDGING)
    with pytest.raises(RuntimeError), Session.begin() as s:
        move_job(s, job_id, S.JUDGING, S.CAPTURING, outbox=[OutboxItem(Action.CAPTURE)])
        raise RuntimeError("crash before commit")
    with Session() as s:
        assert s.get(Job, job_id).state == "JUDGING"
        assert s.scalar(select(Outbox)) is None


def test_concurrent_transition_only_one_wins(Session, make_job):
    job_id = make_job(S.JUDGING)
    # Two workers both read JUDGING. The first one commits its move.
    with Session.begin() as s:
        move_job(s, job_id, S.JUDGING, S.CAPTURING)
    # The second one still believes the job is JUDGING: its compare-and-set matches 0 rows.
    with pytest.raises(StaleState), Session.begin() as s:
        move_job(s, job_id, S.JUDGING, S.VOIDING)
    with Session() as s:
        assert s.get(Job, job_id).state == "CAPTURING"


def test_illegal_move_is_refused_before_touching_the_db(Session, make_job):
    job_id = make_job(S.OPEN)
    with pytest.raises(IllegalTransition), Session.begin() as s:
        move_job(s, job_id, S.OPEN, S.PAID)


def test_outbox_enqueue_is_idempotent(Session, make_job):
    job_id = make_job(S.HUMAN_REVIEW)
    with Session.begin() as s:
        move_job(s, job_id, S.HUMAN_REVIEW, S.CAPTURING, outbox=[OutboxItem(Action.CAPTURE)])
    with Session.begin() as s:   # e.g. retried step re-enqueues the same action
        from verdict.core.outbox import enqueue
        enqueue(s, job_id, Action.CAPTURE)
    with Session() as s:
        assert len(s.scalars(select(Outbox)).all()) == 1


def test_audit_chain_detects_tampering(Session, make_job):
    job_id = make_job(S.DRAFT)
    with Session.begin() as s:
        for a, b in [(S.DRAFT, S.VALIDATING), (S.VALIDATING, S.AWAITING_FUNDS),
                     (S.AWAITING_FUNDS, S.FUNDED)]:
            move_job(s, job_id, a, b, data={"amount": D("100.00")})
    with Session() as s:
        assert verify_audit_chain(s, job_id)
    with Session.begin() as s:
        s.execute(update(AuditLog).where(AuditLog.job_id == job_id, AuditLog.seq == 2)
                  .values(payload={"reason": "edited later"}))
    with Session() as s:
        assert not verify_audit_chain(s, job_id)


def test_payloads_never_contain_floats():
    assert jsonable({"a": D("1.10"), "b": [D("2.00")]}) == {"a": "1.10", "b": ["2.00"]}
    with pytest.raises(TypeError):
        jsonable({"a": 1.1})
