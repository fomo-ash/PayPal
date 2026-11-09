"""Claims and submissions.

POST /jobs/{id}/claim            worker accepts the job; the deadline starts
POST /jobs/{id}/examples-run     run code on the PUBLIC examples only, as often as wanted
POST /jobs/{id}/submit           the ONE graded submission → SUBMITTED, grading queued
GET  /submissions/{id}           status, verdict, scores, scanner + AI findings (both sides)
GET  /submissions/{id}/code      buyer only, once paid (PAID → CODE_RELEASED)
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from verdict.api.deps import DB, CurrentUser, Svc
from verdict.api.routers.jobs import get_job, load_suite, require_state
from verdict.core.state_machine import JobState as S
from verdict.db.models import (
    AIReview,
    Claim,
    Job,
    Run,
    ScanFinding,
    Submission,
    Suite,
    User,
    Verdict,
    as_utc,
    utcnow,
)
from verdict.db.repo import append_audit, move_job
from verdict.grading.compare import outputs_match
from verdict.grading.files import FilesError, files_sha256, parse_files, write_tree
from verdict.scanner.reject_list import check_files

router = APIRouter(tags=["submissions"])
MAX_SHOWN_OUTPUT = 2_000


def _files(raw: dict[str, Any]) -> dict[str, str]:
    try:
        files = parse_files(raw.get("files"))
    except FilesError as e:
        raise HTTPException(422, str(e)) from e
    rejected = check_files({p: len(src.encode()) for p, src in files.items()})
    if rejected:
        raise HTTPException(422, "rejected files: " + "; ".join(rejected))
    return files


def active_claim(s: Session, job: Job, user: User) -> Claim:
    claim = s.scalar(select(Claim).where(Claim.job_id == job.id, Claim.worker_id == user.id,
                                         Claim.status == "active"))
    if claim is None or job.state != S.CLAIMED.value:
        raise HTTPException(409, "you do not hold an active claim on this job")
    if as_utc(claim.deadline_at) <= utcnow():
        raise HTTPException(409, "your claim deadline has passed")
    return claim


@router.post("/jobs/{job_id}/claim", status_code=201)
def claim(job_id: uuid.UUID, user: CurrentUser, s: DB) -> dict:
    job = get_job(s, job_id, for_update=True)
    if user.role != "worker":
        raise HTTPException(403, "only workers can claim jobs")
    if job.buyer_id == user.id:
        raise HTTPException(403, "you cannot claim your own job")
    if not (user.paypal_payer_id or user.email):
        raise HTTPException(409, "connect PayPal first so you can be paid")
    already = s.scalar(select(Submission.id).where(Submission.job_id == job.id,
                                                   Submission.worker_id == user.id))
    if already is not None:
        raise HTTPException(409, "you already submitted to this job (one graded try)")
    require_state(job, S.OPEN)
    c = Claim(job_id=job.id, worker_id=user.id,
              deadline_at=utcnow() + timedelta(hours=job.deadline_hours))
    s.add(c)
    s.flush()
    move_job(s, job.id, S.OPEN, S.CLAIMED, reason="claimed",
             data={"worker": user.id, "claim": c.id, "deadline": c.deadline_at})
    s.commit()
    return {"claim_id": str(c.id), "deadline_at": c.deadline_at.isoformat(),
            "state": S.CLAIMED.value}


@router.post("/jobs/{job_id}/examples-run")
def examples_run(job_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc,
                 raw: Annotated[dict[str, Any], Body()]) -> dict:
    """Public examples only. Hidden tests are never run here, so this cannot leak them."""
    job = get_job(s, job_id)
    active_claim(s, job, user)
    files = _files(raw)
    row = s.get(Suite, job.id)
    assert row is not None
    examples = load_suite(svc.store, row).doc["examples"]
    s.rollback()
    cases = [(f"example-{i}", e["input"]) for i, e in enumerate(examples)]
    with tempfile.TemporaryDirectory() as d:
        results = svc.runner.run_batch(write_tree(files, Path(d)), cases,
                                       svc.settings.sandbox_test_timeout_ms / 1000)
    out = []
    for (cid, _), r, e in zip(cases, results, examples, strict=True):
        out.append({"id": cid, "passed": r.error is None and outputs_match(e["expected"],
                                                                           r.output),
                    "output": (r.output or "")[:MAX_SHOWN_OUTPUT], "error": r.error,
                    "ms": round(r.ms, 1)})
    return {"passed": sum(x["passed"] for x in out), "total": len(out), "results": out}


@router.post("/jobs/{job_id}/submit", status_code=201)
def submit(job_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc,
           raw: Annotated[dict[str, Any], Body()]) -> dict:
    job = get_job(s, job_id, for_update=True)
    c = active_claim(s, job, user)
    files = _files(raw)
    sha = files_sha256(files)
    key = f"submissions/{job.id}/{user.id}/{sha}.json"
    svc.store.put(key, json.dumps({"files": files}, ensure_ascii=False).encode())
    sub = Submission(claim_id=c.id, job_id=job.id, worker_id=user.id, r2_key=key, sha256=sha)
    s.add(sub)
    s.flush()
    c.status = "submitted"
    move_job(s, job.id, S.CLAIMED, S.SUBMITTED, reason="submitted",
             data={"submission": sub.id, "sha256": sha})
    s.commit()
    svc.enqueue_grading(sub.id)        # after commit; a sweeper re-queues if this is lost
    return {"submission_id": str(sub.id), "sha256": sha, "state": S.SUBMITTED.value}


def _visible_submission(s: Session, sub_id: uuid.UUID, user: User) -> tuple[Submission, Job]:
    sub = s.get(Submission, sub_id)
    job = s.get(Job, sub.job_id) if sub else None
    if sub is None or job is None or user.id not in {sub.worker_id, job.buyer_id}:
        raise HTTPException(404, "submission not found")
    return sub, job


@router.get("/submissions/{sub_id}")
def get_submission(sub_id: uuid.UUID, user: CurrentUser, s: DB) -> dict:
    sub, job = _visible_submission(s, sub_id, user)
    v = s.get(Verdict, sub.id)
    runs = s.scalars(select(Run).where(Run.submission_id == sub.id)).all()
    scans = s.scalars(select(ScanFinding).where(ScanFinding.submission_id == sub.id)).all()
    ai = s.scalar(select(AIReview).where(AIReview.submission_id == sub.id)
                  .order_by(AIReview.created_at.desc()).limit(1))
    return {
        "id": str(sub.id), "job_id": str(job.id), "job_state": job.state,
        "sha256": sub.sha256, "submitted_at": sub.submitted_at.isoformat(),
        "runs": [{"kind": r.kind, "group": r.group_name, "passed": r.passed, "total": r.total,
                  "flaky": r.flaky_ids} for r in runs],
        "verdict": None if v is None else {
            "score": str(v.score), "raw_score": str(v.raw_score), "capture": str(v.capture),
            "fee": str(v.fee), "worker_amount": str(v.worker_amount),
            "released": str(v.released), "settlement": v.settlement,
            "reason": v.policy_reason, "decided_by": v.decided_by},
        "scan_findings": [{"rule": f.rule, "file": f.file, "line": f.line, "message": f.message,
                           "hard_signal": f.hard_signal} for f in scans],
        "ai_review": None if ai is None else {
            "decision": ai.decision, "model": ai.model, "findings": ai.findings,
            "explanation": ai.explanation},
    }


@router.get("/submissions/{sub_id}/code")
def get_code(sub_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc) -> dict:
    sub, job = _visible_submission(s, sub_id, user)
    if user.id != job.buyer_id:
        raise HTTPException(403, "only the buyer receives the code")
    if job.state == S.PAID.value:
        move_job(s, job.id, S.PAID, S.CODE_RELEASED, reason="code released to buyer")
        append_audit(s, job.id, "code_downloaded", {"submission": sub.id})
        s.commit()
    elif job.state != S.CODE_RELEASED.value:
        raise HTTPException(409, "code is released only after the worker is paid")
    return json.loads(svc.store.get(sub.r2_key))
