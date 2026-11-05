"""PayPal webhook handling.

1. The router verifies every event with POST /v1/notifications/verify-webhook-signature.
   Unverified events are refused and never stored.
2. The event is stored in paypal_events; the PayPal event id is the primary key, so a
   redelivered event is recognised and ignored.
3. The event is matched to a job (authorization, order, capture or payout batch id) and
   written to that job's audit chain. Webhooks CONFIRM what the money worker did; they never
   move money or change a job's state themselves, so a forged or replayed event cannot pay
   anyone. Payout items that bounce after PAID are recorded as alerts for a person.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from verdict.db.models import Job, PayPalEvent
from verdict.db.repo import append_audit

SUBSCRIBED_EVENTS = [
    "CHECKOUT.ORDER.APPROVED",
    "PAYMENT.AUTHORIZATION.CREATED",
    "PAYMENT.AUTHORIZATION.VOIDED",
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.PAYOUTSBATCH.SUCCESS",
    "PAYMENT.PAYOUTSBATCH.DENIED",
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
    "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED",
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.UPDATED",
    "CUSTOMER.DISPUTE.RESOLVED",
]
ALERTS = {"PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REFUNDED", "PAYMENT.PAYOUTSBATCH.DENIED",
          "PAYMENT.PAYOUTS-ITEM.FAILED", "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
          "PAYMENT.PAYOUTS-ITEM.RETURNED", "CUSTOMER.DISPUTE.CREATED"}


class BadEvent(ValueError):
    pass


def related_ids(event: dict[str, Any]) -> list[str]:
    """Every PayPal id in the event that could point at one of our jobs."""
    r = event.get("resource") or {}
    related = (r.get("supplementary_data") or {}).get("related_ids") or {}
    ids = [r.get("id"), r.get("payout_batch_id"), (r.get("batch_header") or {})
           .get("payout_batch_id"), related.get("authorization_id"), related.get("order_id")]
    for t in r.get("disputed_transactions") or []:
        ids.append(t.get("seller_transaction_id"))
    return [i for i in ids if isinstance(i, str) and i]


def find_job(s: Session, ids: list[str]) -> Job | None:
    if not ids:
        return None
    return s.scalar(select(Job).where(or_(
        Job.authorization_id.in_(ids), Job.paypal_order_id.in_(ids),
        Job.capture_id.in_(ids), Job.payout_batch_id.in_(ids))).limit(1))


def record_event(s: Session, event: dict[str, Any]) -> str:
    """Store + audit a VERIFIED event. Returns 'stored', 'duplicate' or 'unmatched'."""
    eid, etype = event.get("id"), event.get("event_type")
    if not isinstance(eid, str) or not eid or len(eid) > 64 or not isinstance(etype, str):
        raise BadEvent("event needs id and event_type")
    if s.get(PayPalEvent, eid) is not None:
        return "duplicate"
    ids = related_ids(event)
    s.add(PayPalEvent(id=eid, type=etype[:80], resource_id=(ids[0][:64] if ids else None),
                      raw=event, verified=True))
    try:
        s.flush()
    except IntegrityError:                 # the same event delivered twice at the same time
        s.rollback()
        return "duplicate"
    job = find_job(s, ids)
    if job is None:
        return "unmatched"
    status = (event.get("resource") or {}).get("status") or \
        ((event.get("resource") or {}).get("transaction_status"))
    append_audit(s, job.id, f"webhook:{etype}"[:60],
                 {"event_id": eid, "status": status, "job_state": job.state,
                  "alert": etype in ALERTS})
    return "stored"
