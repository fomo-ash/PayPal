"""Signed receipts.

GET  /receipts/public-key     the Ed25519 public key anyone can verify with (no login)
GET  /receipts/{job_id}       the signed receipt, issued once the money has settled
                              (PAID, CODE_RELEASED or VOIDED); buyer, worker or admin
POST /receipts/verify         {"receipt": {...}, "signature": "..."} → valid or not (no login)
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from verdict.api.deps import DB, CurrentUser, Svc
from verdict.api.routers.jobs import get_job
from verdict.core.state_machine import JobState as S
from verdict.db.models import Receipt, Submission, Verdict
from verdict.db.repo import append_audit
from verdict.receipts import signing

router = APIRouter(prefix="/receipts", tags=["receipts"])
SETTLED = {S.PAID.value, S.CODE_RELEASED.value, S.VOIDED.value}


def _keys(svc: Any) -> tuple[str, str]:
    private = svc.settings.receipt_signing_key_b64
    if not private:
        raise HTTPException(503, "receipts are not configured (RECEIPT_SIGNING_KEY_B64)")
    try:
        return private, signing.public_key_b64(private)
    except signing.ReceiptKeyError as e:
        raise HTTPException(503, str(e)) from e


@router.get("/public-key")
def public_key(svc: Svc) -> dict:
    _, pub = _keys(svc)
    return {"algorithm": "Ed25519", "public_key": pub, "key_id": signing.key_id(pub)}


class VerifyBody(BaseModel):
    receipt: dict[str, Any]
    signature: str


@router.post("/verify")
def verify(body: VerifyBody, svc: Svc) -> dict:
    _, pub = _keys(svc)
    valid = signing.verify(body.receipt, body.signature, pub)
    return {"valid": valid, "key_id": signing.key_id(pub),
            "signed_by_this_key": body.receipt.get("key_id") == signing.key_id(pub),
            "job_id": body.receipt.get("job", {}).get("id") if valid else None}


@router.get("/{job_id}")
def get_receipt(job_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc) -> dict:
    job = get_job(s, job_id)
    verdict = s.scalar(select(Verdict).where(Verdict.job_id == job.id))
    sub = s.get(Submission, verdict.submission_id) if verdict else None
    parties = {job.buyer_id, sub.worker_id if sub else None}
    if user.id not in parties and user.role != "admin":
        raise HTTPException(404, "receipt not found")
    row = s.get(Receipt, job.id)
    if row is not None:
        return json.loads(svc.store.get(row.json_key))
    if job.state not in SETTLED:
        raise HTTPException(409, "a receipt is issued once the money has settled")
    private, pub = _keys(svc)
    receipt = signing.build(s, job, pub)
    doc = {"receipt": receipt, "signature": signing.sign(receipt, private)}
    key = f"receipts/{job.id}.json"
    try:
        s.add(Receipt(job_id=job.id, json_key=key, signature=doc["signature"],
                      public_key_id=receipt["key_id"]))
        s.flush()
    except IntegrityError:                 # another request issued it first: return that one
        s.rollback()
        row = s.get(Receipt, job.id)
        assert row is not None
        return json.loads(svc.store.get(row.json_key))
    svc.store.put(key, json.dumps(doc, ensure_ascii=False).encode())
    append_audit(s, job.id, "receipt_issued", {"key_id": receipt["key_id"],
                                               "signature": doc["signature"][:16]})
    s.commit()
    return doc
