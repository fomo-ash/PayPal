"""Grading worker: SUBMITTED → GRADING → JUDGING → (money.settle) CAPTURING | VOIDING | REVIEW.

The slow part (sandbox runs) happens with NO transaction open and the job still SUBMITTED.
The results are then written in ONE transaction that starts with a compare-and-set
SUBMITTED → GRADING, so if two workers grade the same submission only one result is kept,
and a crash mid-grading simply leaves the job SUBMITTED for the sweeper to retry.

AI review (Phase 3) slots in between scoring and settle; until then the AI input is CLEAR,
which can never raise a payout or block on its own.
"""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from verdict.core.policy import AIDecision, PolicyResult, Settlement
from verdict.core.state_machine import JobState as S
from verdict.db.models import Job, Run, ScanFinding, Submission, Suite, as_utc, utcnow
from verdict.db.repo import StaleState, move_job
from verdict.grading import oracle
from verdict.grading.files import write_tree
from verdict.grading.pipeline import GradeReport, grade, new_seed, zero_payout
from verdict.grading.suite import SuiteUpload, to_pipeline_suite
from verdict.sandbox.runner import Runner
from verdict.storage import BlobStore
from verdict.worker import money

log = logging.getLogger(__name__)
STALE_AFTER = timedelta(minutes=5)       # SUBMITTED longer than this → sweeper re-queues


@dataclass(frozen=True)
class GradeOutcome:
    result: str            # graded | skipped | lost_race
    state: str | None = None


def grade_submission(Session: sessionmaker, store: BlobStore, runner: Runner,  # noqa: N803
                     submission_id: uuid.UUID, *, timeout_s: float = 2.0,
                     seed: int | None = None) -> GradeOutcome:
    with Session() as s:
        sub = s.get(Submission, submission_id)
        job = s.get(Job, sub.job_id) if sub else None
        row = s.get(Suite, sub.job_id) if sub else None
        if sub is None or job is None or row is None or job.state != S.SUBMITTED.value:
            return GradeOutcome("skipped", job.state if job else None)
        files = json.loads(store.get(sub.r2_key))["files"]
        suite = SuiteUpload(json.loads(store.get(row.r2_key)),
                            store.get(row.reference_key).decode(),
                            store.get(row.generator_key).decode() if row.generator_key else None,
                            row.sha256)
        job_id, amount, fee_bps, min_score = job.id, str(job.amount), job.fee_bps, job.min_score
        if job.suite_sha256 != row.sha256:
            raise RuntimeError(f"job {job_id}: stored suite does not match the sealed hash")

    seed = new_seed() if seed is None else seed
    report, override = _run(files, suite, runner, amount, fee_bps, min_score, timeout_s, seed)

    with Session() as s:
        try:
            move_job(s, job_id, S.SUBMITTED, S.GRADING, reason="graded",
                     data={"seed_recorded": True})
        except StaleState:
            s.rollback()
            return GradeOutcome("lost_race")
        _store_results(s, submission_id, report)
        payout = report.payout or zero_payout(to_pipeline_suite(suite.doc, min_score),
                                              amount, fee_bps)
        decision = override or report.decision
        assert decision is not None
        move_job(s, job_id, S.GRADING, S.JUDGING, reason=decision.reason,
                 data={"score": payout.score, "signals": [str(x) for x in report.signals]})
        state = money.settle(s, job_id, submission_id, payout, decision)
        s.commit()
    return GradeOutcome("graded", state.value)


def _run(files: dict[str, str], suite: SuiteUpload, runner: Runner, amount: str, fee_bps: int,
         min_score, timeout_s: float, seed: int) -> tuple[GradeReport, PolicyResult | None]:
    psuite = to_pipeline_suite(suite.doc, min_score)
    with tempfile.TemporaryDirectory() as d:
        sub_dir = write_tree(files, Path(d) / "submission")
        build = (oracle.fresh_builder(runner, suite.generator, suite.reference, psuite.fresh,
                                      timeout_s) if suite.generator and psuite.fresh else None)
        try:
            report = grade(sub_dir, psuite, runner, None, None, amount, fee_bps,
                           timeout_s=timeout_s, seed=seed, ai_decision=AIDecision.CLEAR,
                           fresh_builder=build)
            return report, None
        except oracle.OracleError as e:
            # The BUYER's generator broke at grading time. Grade on hidden tests only and let
            # a person decide; the capture can still only go down from here.
            log.warning("fresh inputs failed, grading without them: %s", e)
            psuite.fresh = {}
            report = grade(sub_dir, psuite, runner, None, None, amount, fee_bps,
                           timeout_s=timeout_s, seed=seed, ai_decision=AIDecision.CLEAR)
            if report.decision and report.decision.settlement is Settlement.CAPTURE:
                return report, PolicyResult(Settlement.HUMAN_REVIEW, report.decision.capture,
                                            f"fresh-input generator failed: {e}")
            return report, None


def _store_results(s: Session, submission_id: uuid.UUID, report: GradeReport) -> None:
    sub = s.get(Submission, submission_id)
    assert sub is not None
    sub.grading_seed = str(report.seed)
    for g, (passed, total) in report.hidden.items():
        s.add(Run(submission_id=submission_id, kind="hidden", group_name=g, passed=passed,
                  total=total, flaky_ids=report.flaky))
    for g, (passed, total) in report.fresh.items():
        s.add(Run(submission_id=submission_id, kind="fresh", group_name=g, passed=passed,
                  total=total))
    for f in report.findings:
        s.add(ScanFinding(submission_id=submission_id, rule=f.rule, file=f.file, line=f.line,
                          message=f.message, hard_signal=f.hard.value if f.hard else None))
    for r in report.rejected:
        s.add(ScanFinding(submission_id=submission_id, rule="reject_list", file="", line=0,
                          message=r, hard_signal="REJECTED_FILE"))


def stale_submissions(Session: sessionmaker, now: datetime | None = None) -> list[uuid.UUID]:  # noqa: N803
    """Submissions whose job has sat in SUBMITTED too long (lost task, sandbox outage)."""
    cutoff = (now or utcnow()) - STALE_AFTER
    with Session() as s:
        rows = s.execute(select(Submission.id, Submission.submitted_at)
                         .join(Job, Job.id == Submission.job_id)
                         .where(Job.state == S.SUBMITTED.value)).all()
    return [sid for sid, at in rows if as_utc(at) <= cutoff]
