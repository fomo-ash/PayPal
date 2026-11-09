"""Signed receipts.

receipt   = canonical JSON {job, suite_sha256, submission_sha256, results, ai, decision,
            paypal: {order_id, authorization_id, capture_id, payout_batch_id},
            audit_head_hash, issued_at, key_id}
signature = Ed25519(private_key, canonical_bytes(receipt)), base64.

Anyone can check a receipt with POST /receipts/verify or offline with the public key from
GET /receipts/public-key. Changing any field, even one cent, breaks the signature.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from verdict.db.models import AIReview, AuditLog, Job, Run, Submission, Verdict


class ReceiptKeyError(ValueError):
    pass


def canonical_bytes(receipt: dict) -> bytes:
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def generate_private_key_b64() -> str:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode()


def _private(private_key_b64: str) -> Ed25519PrivateKey:
    try:
        raw = base64.b64decode(private_key_b64, validate=True)
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (ValueError, TypeError) as e:
        raise ReceiptKeyError("RECEIPT_SIGNING_KEY_B64 is not a base64 Ed25519 private key") from e


def public_key_b64(private_key_b64: str) -> str:
    pub = _private(private_key_b64).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(pub).decode()


def key_id(public_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(public_b64)).hexdigest()[:16]


def sign(receipt: dict, private_key_b64: str) -> str:
    return base64.b64encode(_private(private_key_b64).sign(canonical_bytes(receipt))).decode()


def verify(receipt: dict, signature_b64: str, public_b64: str) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64, validate=True))
        key.verify(base64.b64decode(signature_b64, validate=True), canonical_bytes(receipt))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def build(s: Session, job: Job, public_b64: str, now: datetime | None = None) -> dict:
    """Everything a third party needs to check what happened to this job's money."""
    verdict = s.scalar(select(Verdict).where(Verdict.job_id == job.id))
    sub = s.get(Submission, verdict.submission_id) if verdict else None
    runs = (s.scalars(select(Run).where(Run.submission_id == sub.id)
                      .order_by(Run.kind, Run.group_name)).all() if sub else [])
    ai = (s.scalar(select(AIReview).where(AIReview.submission_id == sub.id)
                   .order_by(AIReview.created_at.desc()).limit(1)) if sub else None)
    head = s.scalar(select(AuditLog.hash).where(AuditLog.job_id == job.id)
                    .order_by(AuditLog.seq.desc()).limit(1))
    return {
        "version": 1,
        "job": {"id": str(job.id), "title": job.title, "amount": f"{job.amount:.2f}",
                "currency": job.currency, "min_score": str(job.min_score), "state": job.state},
        "suite_sha256": job.suite_sha256,
        "submission_sha256": sub.sha256 if sub else None,
        "results": [{"kind": r.kind, "group": r.group_name, "passed": r.passed, "total": r.total}
                    for r in runs],
        "ai": None if ai is None else {"decision": ai.decision, "model": ai.model,
                                       "findings": len(ai.findings or [])},
        "decision": None if verdict is None else {
            "settlement": verdict.settlement, "score": str(verdict.score),
            "capture": f"{verdict.capture:.2f}", "fee": f"{verdict.fee:.2f}",
            "worker": f"{verdict.worker_amount:.2f}", "released": f"{verdict.released:.2f}",
            "decided_by": verdict.decided_by, "reason": verdict.policy_reason},
        "paypal": {"order_id": job.paypal_order_id, "authorization_id": job.authorization_id,
                   "capture_id": job.capture_id, "payout_batch_id": job.payout_batch_id},
        "audit_head_hash": head,
        "issued_at": (now or datetime.now(UTC)).replace(microsecond=0).isoformat(),
        "key_id": key_id(public_b64),
    }
