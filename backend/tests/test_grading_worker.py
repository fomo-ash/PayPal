import uuid
from datetime import timedelta

import pytest

from verdict.core import ledger
from verdict.db.models import Job, Run, ScanFinding, Submission, Suite, Verdict, utcnow
from verdict.db.repo import verify_audit_chain
from verdict.sandbox.e2b_runner import SandboxUnavailable
from verdict.sandbox.runner import LocalRunner
from verdict.worker import grading


def run_grading(api, sub_id, **kw):
    return grading.grade_submission(api.services.Session, api.services.store, LocalRunner(),
                                    uuid.UUID(sub_id), **kw)


@pytest.mark.parametrize("name, state, capture", [
    ("honest_full", "CAPTURING", "100.00"),
    ("honest_partial", "CAPTURING", None),
    ("cheat_memorizer", "VOIDING", "0.00"),
    ("cheat_injection", "VOIDING", "0.00"),
])
def test_grading_reaches_the_right_settlement(api, submitted, Session, name, state, capture):
    buyer, _, job_id, sub_id = submitted(name)
    out = run_grading(api, sub_id)
    assert out.result == "graded" and out.state == state
    view = api.get(f"/submissions/{sub_id}", headers=buyer).json()
    assert view["job_state"] == state
    if capture:
        assert view["verdict"]["capture"] == capture
    with Session() as s:
        assert s.get(Submission, uuid.UUID(sub_id)).grading_seed is not None
        assert verify_audit_chain(s, uuid.UUID(job_id))


def test_memorizer_is_caught_by_fresh_inputs(api, submitted, Session):
    _, _, _, sub_id = submitted("cheat_memorizer")
    run_grading(api, sub_id)
    with Session() as s:
        runs = {(r.kind, r.group_name): (r.passed, r.total)
                for r in s.query(Run).filter_by(submission_id=uuid.UUID(sub_id))}
        v = s.get(Verdict, uuid.UUID(sub_id))
    assert runs[("hidden", "core")][0] == runs[("hidden", "core")][1]    # all hidden passed
    passed, total = runs[("fresh", "core")]
    assert total == 200 and passed < 50                                   # fresh inputs fail
    assert v.settlement == "VOID" and v.released == 100


def test_injection_findings_are_stored(api, submitted, Session):
    _, _, _, sub_id = submitted("cheat_injection")
    run_grading(api, sub_id)
    with Session() as s:
        hard = [f.hard_signal for f in s.query(ScanFinding).filter_by(
            submission_id=uuid.UUID(sub_id))]
    assert "GRADER_INJECTION" in hard


def test_grading_twice_keeps_one_result(api, submitted, Session):
    _, _, job_id, sub_id = submitted("honest_full")
    assert run_grading(api, sub_id).result == "graded"
    assert run_grading(api, sub_id).result == "skipped"
    with Session() as s:
        assert s.query(Verdict).filter_by(job_id=uuid.UUID(job_id)).count() == 1


def test_lost_race_writes_nothing(api, submitted, Session, monkeypatch):
    _, _, job_id, sub_id = submitted("honest_full")
    real = grading._run

    def slow_run(*a, **kw):          # another worker finishes while we are in the sandbox
        res = real(*a, **kw)
        with Session.begin() as s:
            s.get(Job, uuid.UUID(job_id)).state = "GRADING"
        return res
    monkeypatch.setattr(grading, "_run", slow_run)
    assert run_grading(api, sub_id).result == "lost_race"
    with Session() as s:
        assert s.query(Run).count() == 0 and s.query(Verdict).count() == 0


def test_sandbox_outage_leaves_job_submitted(api, submitted, Session):
    _, _, job_id, sub_id = submitted("honest_full")

    class Down:
        def run_batch(self, *a, **kw):
            raise SandboxUnavailable("e2b down")
    with pytest.raises(SandboxUnavailable):
        grading.grade_submission(Session, api.services.store, Down(), uuid.UUID(sub_id))
    with Session() as s:
        assert s.get(Job, uuid.UUID(job_id)).state == "SUBMITTED"
    assert grading.stale_submissions(Session, now=utcnow() + timedelta(minutes=6)) == \
        [uuid.UUID(sub_id)]
    assert grading.stale_submissions(Session) == []


def test_broken_generator_at_grading_goes_to_human_review(api, submitted, Session):
    _, _, job_id, sub_id = submitted("honest_full")
    with Session() as s:
        row = s.get(Suite, uuid.UUID(job_id))
        api.services.store.put(row.generator_key, b"def gen_input(rng):\n    raise SystemExit\n")
    out = run_grading(api, sub_id)
    assert out.state == "HUMAN_REVIEW"
    with Session() as s:
        v = s.get(Verdict, uuid.UUID(sub_id))
        assert v.settlement == "HUMAN_REVIEW" and "generator failed" in v.policy_reason
        assert ledger.balances(s, uuid.UUID(job_id))["hold_memo"] == 100
