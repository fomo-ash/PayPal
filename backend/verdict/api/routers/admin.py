"""Human review queue (admin only).

GET  /admin/reviews              jobs waiting in HUMAN_REVIEW, oldest first
GET  /admin/reviews/{job_id}     everything a reviewer needs: scores, findings, AI review, code
POST /admin/reviews/{job_id}     {"capture": "50.00", "note": "..."}: approve up to the scored
                                 capture, or "0" to void. A reviewer can never raise the amount.

A reviewer may not decide a job they are the buyer or worker on.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from verdict.api.deps import DB, CurrentUser, Svc
from verdict.api.routers.jobs import get_job, require_state
from verdict.api.routers.submissions import submission_view
from verdict.core.policy import resolve_review
from verdict.core.state_machine import JobState as S
from verdict.db.models import Job, Submission, User, Verdict
from verdict.db.repo import append_audit
from verdict.worker import money

router = APIRouter(prefix="/admin", tags=["admin"])


def admin_user(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, "admins only")
    return user


Admin = Annotated[User, Depends(admin_user)]


class Decision(BaseModel):
    capture: str = Field(max_length=12)        # decimal string; "0" voids
    note: str = Field(default="", max_length=500)


def _case(s: Session, job_id: uuid.UUID) -> tuple[Job, Verdict, Submission]:
    job = get_job(s, job_id)
    verdict = s.scalar(select(Verdict).where(Verdict.job_id == job.id))
    sub = s.get(Submission, verdict.submission_id) if verdict else None
    if verdict is None or sub is None:
        raise HTTPException(404, "no verdict for this job")
    return job, verdict, sub


@router.get("/reviews")
def queue(_: Admin, s: DB) -> list[dict]:
    rows = s.execute(select(Job, Verdict).join(Verdict, Verdict.job_id == Job.id)
                     .where(Job.state == S.HUMAN_REVIEW.value)
                     .order_by(Verdict.decided_at)).all()
    return [{"job_id": str(j.id), "title": j.title, "amount": str(j.amount),
             "max_capture": str(v.capture), "score": str(v.score), "reason": v.policy_reason,
             "submission_id": str(v.submission_id), "since": v.decided_at.isoformat()}
            for j, v in rows]


@router.get("/reviews/{job_id}")
def case(job_id: uuid.UUID, _: Admin, s: DB, svc: Svc) -> dict:
    job, verdict, sub = _case(s, job_id)
    return {"job": {"id": str(job.id), "title": job.title, "spec_md": job.spec_md,
                    "amount": str(job.amount), "state": job.state},
            "max_capture": str(verdict.capture),
            "submission": submission_view(s, sub, job),
            "code": json.loads(svc.store.get(sub.r2_key))["files"]}


@router.post("/reviews/{job_id}")
def decide_case(job_id: uuid.UUID, body: Decision, user: Admin, s: DB, svc: Svc) -> dict:
    job = get_job(s, job_id, for_update=True)
    require_state(job, S.HUMAN_REVIEW)
    _, verdict, sub = _case(s, job_id)
    if user.id in {job.buyer_id, sub.worker_id}:
        raise HTTPException(403, "you cannot review a job you are part of")
    max_capture = verdict.capture
    result = resolve_review(max_capture, body.capture)         # ReviewError → 422
    reviewer = user.email or str(user.id)
    state = money.resolve_review(s, job.id, result, reviewer=reviewer)
    append_audit(s, job.id, "human_review", {"reviewer": str(user.id), "capture": result.capture,
                                             "max_capture": max_capture, "note": body.note})
    s.commit()
    svc.kick_money(job.id)
    return {"state": state.value, "settlement": result.settlement.value,
            "capture": str(result.capture)}
