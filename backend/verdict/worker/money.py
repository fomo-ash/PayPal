"""Money worker: the only code that moves money.

Three entry points, each running inside ONE database transaction:
  record_authorization  AWAITING_FUNDS → FUNDED     (buyer approved; hold exists at PayPal)
  settle                JUDGING → CAPTURING | VOIDING | HUMAN_REVIEW   (writes the verdict)
  resolve_review        HUMAN_REVIEW → CAPTURING | VOIDING             (a person decided)
and the outbox processor:
  process_outbox        performs due PayPal actions and advances the job

Safety rules:
  * Every PayPal POST uses the outbox row's deterministic idempotency key, so a crash + retry
    returns PayPal's original result instead of charging or paying twice.
  * Amounts come only from the stored verdict (computed by core.scoring). Nothing here does
    percentage maths except splitting a reviewer-lowered capture with the same rounding rules.
  * Transient errors (network, 5xx, 429) back off and retry; permanent errors move the job to a
    state a person can act on. Nothing is ever left silently stuck.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from verdict.core import ledger
from verdict.core.outbox import Action, enqueue, jsonable
from verdict.core.policy import PolicyResult, Settlement
from verdict.core.scoring import CENT, ZERO, Payout
from verdict.core.state_machine import JobState as S
from verdict.db.models import Job, Outbox, Submission, User, Verdict, utcnow
from verdict.db.repo import OutboxItem, move_job
from verdict.paypal.client import PayPalError

log = logging.getLogger(__name__)

HONOR_PERIOD = timedelta(days=3)          # PayPal guarantees the funds for 3 days
MAX_ATTEMPTS = 8                          # transient-error retries before a person is alerted
MAX_PAYOUT_POLLS = 120                    # ~2h of polling a pending payout item
PAYOUT_POLL_EVERY = timedelta(minutes=1)
TRANSIENT_HTTP = {408, 409, 429}
TRANSIENT_NAMES = {"INSUFFICIENT_FUNDS", "INTERNAL_SERVER_ERROR", "RATE_LIMIT_REACHED"}
PAYOUT_OK = {"SUCCESS"}
PAYOUT_PENDING = {"PENDING", "UNCLAIMED_PENDING", "ONHOLD", "NEW"}
# Anything else (FAILED, RETURNED, BLOCKED, REFUNDED, REVERSED, DENIED, UNCLAIMED) → a person.

# Where a job goes when its PayPal action fails for good (VOIDING has no exit: a failed void
# leaves the row 'failed' and the job in VOIDING, which the admin page lists as an alert).
ON_FAILURE = {
    "capture": (S.CAPTURING, S.HUMAN_REVIEW),
    "payout": (S.PAYING_OUT, S.PAYOUT_FAILED),
    "payout_status": (S.PAYING_OUT, S.PAYOUT_FAILED),
}


class PayPalLike(Protocol):
    def capture_authorization(self, auth_id: str, *, amount: str, currency: str,
                              final_capture: bool, idempotency_key: str,
                              invoice_id: str | None = None) -> dict: ...
    def void_authorization(self, auth_id: str, idempotency_key: str) -> None: ...
    def get_authorization(self, auth_id: str) -> dict: ...
    def create_payout(self, *, batch_id: str, receiver: str, recipient_type: str,
                      amount: str, currency: str, note: str) -> dict: ...
    def get_payout_batch(self, payout_batch_id: str) -> dict: ...


class MoneyError(Exception):
    pass


# ── entry points that change state ───────────────────────────────────────────
def record_authorization(session: Session, job_id: uuid.UUID, *, order_id: str,
                         authorization_id: str, amount: Decimal | str,
                         now: datetime | None = None) -> None:
    """Called after PayPal authorized the buyer's order. Checks the amount matches the job."""
    now = now or utcnow()
    job = session.get(Job, job_id)
    if job is None:
        raise MoneyError(f"job {job_id} not found")
    if Decimal(str(amount)) != job.amount:
        raise MoneyError(f"authorized {amount} but job amount is {job.amount}")
    move_job(session, job_id, S.AWAITING_FUNDS, S.FUNDED, reason="authorized",
             data={"authorization_id": authorization_id, "amount": job.amount},
             fields={"paypal_order_id": order_id, "authorization_id": authorization_id,
                     "authorized_at": now, "honor_expires_at": now + HONOR_PERIOD})
    ledger.post(session, job_id, f"{job_id}:authorize", ledger.authorize(job.amount))


def settle(session: Session, job_id: uuid.UUID, submission_id: uuid.UUID, payout: Payout,
           decision: PolicyResult) -> S:
    """Store the verdict and queue the PayPal action the policy decided on."""
    job = session.get(Job, job_id)
    if job is None:
        raise MoneyError(f"job {job_id} not found")
    void = decision.settlement is Settlement.VOID
    # For HUMAN_REVIEW the stored amounts are the MAXIMUM a reviewer may approve.
    session.add(Verdict(
        submission_id=submission_id, job_id=job_id,
        raw_score=payout.raw_score.quantize(Decimal("0.0001")),
        score=payout.score.quantize(Decimal("0.0001")),
        capture=ZERO if void else payout.capture, fee=ZERO if void else payout.fee,
        worker_amount=ZERO if void else payout.worker,
        released=job.amount if void else payout.released,
        settlement=decision.settlement.value, policy_reason=decision.reason,
    ))
    if decision.settlement is Settlement.CAPTURE:
        if decision.capture != payout.capture:
            raise MoneyError("policy capture differs from the scored capture")
        return _start_capture(session, job_id, S.JUDGING, submission_id, payout.capture,
                              payout.fee, payout.worker, decision.reason)
    if decision.settlement is Settlement.VOID:
        return move_job(session, job_id, S.JUDGING, S.VOIDING, reason=decision.reason,
                        outbox=[OutboxItem(Action.VOID)])
    return move_job(session, job_id, S.JUDGING, S.HUMAN_REVIEW, reason=decision.reason,
                    data={"max_capture": decision.capture})


def resolve_review(session: Session, job_id: uuid.UUID, result: PolicyResult,
                   reviewer: str) -> S:
    """Apply core.policy.resolve_review's result (already capped at the scored capture)."""
    job = session.get(Job, job_id)
    verdict = session.scalar(select(Verdict).where(Verdict.job_id == job_id))
    if job is None or verdict is None:
        raise MoneyError("job or verdict missing")
    if result.capture > verdict.capture:
        raise MoneyError("review cannot raise the capture")
    if result.settlement is Settlement.VOID:
        verdict.capture = verdict.fee = verdict.worker_amount = ZERO
        verdict.released, verdict.settlement = job.amount, Settlement.VOID.value
        verdict.decided_by, verdict.policy_reason = "human", f"{reviewer}: {result.reason}"
        return move_job(session, job_id, S.HUMAN_REVIEW, S.VOIDING, reason=result.reason,
                        data={"reviewer": reviewer}, outbox=[OutboxItem(Action.VOID)])
    fee, worker = split_capture(result.capture, job.fee_bps)
    verdict.capture, verdict.fee, verdict.worker_amount = result.capture, fee, worker
    verdict.released = job.amount - result.capture
    verdict.settlement, verdict.decided_by = Settlement.CAPTURE.value, "human"
    verdict.policy_reason = f"{reviewer}: {result.reason}"
    return _start_capture(session, job_id, S.HUMAN_REVIEW, verdict.submission_id,
                          result.capture, fee, worker, result.reason)


def split_capture(capture: Decimal, fee_bps: int) -> tuple[Decimal, Decimal]:
    """Same rounding as core.scoring: fee ROUND_HALF_UP to the cent, worker gets the rest."""
    fee = (capture * Decimal(fee_bps) / Decimal(10_000)).quantize(CENT, rounding=ROUND_HALF_UP)
    return fee, capture - fee


def _start_capture(session: Session, job_id: uuid.UUID, frm: S, submission_id: uuid.UUID,
                   capture: Decimal, fee: Decimal, worker: Decimal, reason: str) -> S:
    receiver, rtype = _payout_receiver(session, submission_id)
    return move_job(session, job_id, frm, S.CAPTURING, reason=reason,
                    data={"capture": capture, "fee": fee, "worker": worker},
                    outbox=[OutboxItem(Action.CAPTURE, {
                        "capture": capture, "fee": fee, "worker": worker,
                        "receiver": receiver, "recipient_type": rtype})])


def _payout_receiver(session: Session, submission_id: uuid.UUID) -> tuple[str, str]:
    """Prefer the PayPal payer id from Log in with PayPal (cannot be mistyped or go unclaimed)."""
    sub = session.get(Submission, submission_id)
    if sub is None:
        raise MoneyError(f"submission {submission_id} not found")
    user = session.get(User, sub.worker_id)
    if user is not None and user.paypal_payer_id:
        return user.paypal_payer_id, "PAYPAL_ID"
    if user is not None and user.email:
        return user.email, "EMAIL"
    raise MoneyError("worker has no PayPal payer id or email")


# ── outbox processor ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Outcome:
    key: str
    action: str
    result: str          # done | retry | failed | skipped
    detail: str = ""


def process_outbox(Session: sessionmaker, paypal: PayPalLike, *, limit: int = 20,  # noqa: N803
                   now: datetime | None = None) -> list[Outcome]:
    """Process up to `limit` due rows, each in its own transaction.

    If anything unexpected happens while handling a row (a bug, a concurrent state change), the
    whole transaction rolls back, so no half-written ledger or state is ever committed, and the
    error is recorded on the row for a backed-off retry.
    """
    outcomes: list[Outcome] = []
    for _ in range(limit):
        row_id = None
        try:
            with Session.begin() as s:
                q = (select(Outbox).where(Outbox.status == "pending",
                                          Outbox.next_attempt_at <= (now or utcnow()))
                     .order_by(Outbox.next_attempt_at, Outbox.created_at).limit(1)
                     .with_for_update(skip_locked=True))
                row = s.scalar(q)
                if row is None:
                    break
                row_id = row.id
                outcomes.append(_handle(s, paypal, row, now or utcnow()))
        except Exception as exc:  # noqa: BLE001 - rolled back above; record and back off
            if row_id is None:
                raise
            log.exception("outbox row %s crashed", row_id)
            with Session.begin() as s:
                row = s.get(Outbox, row_id)
                job = s.get(Job, row.job_id) if row is not None else None
                assert row is not None and job is not None
                row.attempts += 1
                outcomes.append(_retry(s, row, job, now or utcnow(),
                                       f"{type(exc).__name__}: {exc}"))
    return outcomes


def _handle(s: Session, paypal: PayPalLike, row: Outbox, now: datetime) -> Outcome:
    job = s.get(Job, row.job_id)
    assert job is not None
    handlers = {Action.CAPTURE: _do_capture, Action.VOID: _do_void,
                Action.PAYOUT: _do_payout, Action.PAYOUT_STATUS: _do_payout_status}
    handler = handlers.get(Action(row.action))
    if handler is None:
        return _fail(s, row, job, f"no handler for {row.action}", move=None)
    row.attempts += 1
    try:
        return handler(s, paypal, row, job, now)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        return _retry(s, row, job, now, f"network: {exc}")
    except PayPalError as exc:
        if _is_transient(exc):
            return _retry(s, row, job, now, str(exc))
        return _permanent(s, paypal, row, job, exc)


def _do_capture(s: Session, pp: PayPalLike, row: Outbox, job: Job, now: datetime) -> Outcome:
    if job.state != S.CAPTURING:
        return _skip(row, now, f"job is {job.state}, not CAPTURING")
    p = row.payload
    capture, fee, worker = Decimal(p["capture"]), Decimal(p["fee"]), Decimal(p["worker"])
    res = pp.capture_authorization(job.authorization_id or "", amount=str(capture),
                                   currency=job.currency, final_capture=True,
                                   idempotency_key=row.idempotency_key,
                                   invoice_id=row.idempotency_key)
    if res.get("status") not in ("COMPLETED", "PENDING"):
        raise PayPalError(422, {"name": f"CAPTURE_{res.get('status')}"}, None)
    ledger.post(s, job.id, f"{job.id}:capture", ledger.capture(capture, worker, fee))
    ledger.post(s, job.id, f"{job.id}:release", ledger.release(job.amount - capture))
    move_job(s, job.id, S.CAPTURING, S.PAYING_OUT, reason="captured",
             data={"capture_id": res.get("id"), "status": res.get("status")},
             fields={"capture_id": res.get("id")},
             outbox=[OutboxItem(Action.PAYOUT, {"amount": worker, "receiver": p["receiver"],
                                                "recipient_type": p["recipient_type"]})])
    return _done(row, now, res, f"captured {capture}")


def _do_void(s: Session, pp: PayPalLike, row: Outbox, job: Job, now: datetime) -> Outcome:
    if job.state != S.VOIDING:
        return _skip(row, now, f"job is {job.state}, not VOIDING")
    pp.void_authorization(job.authorization_id or "", idempotency_key=row.idempotency_key)
    _finish_void(s, job, "voided")
    return _done(row, now, {}, "voided")


def _finish_void(s: Session, job: Job, reason: str) -> None:
    if job.authorization_id:      # a job voided before funding never had a hold
        ledger.post(s, job.id, f"{job.id}:void", ledger.void(job.amount))
    move_job(s, job.id, S.VOIDING, S.VOIDED, reason=reason)


def _do_payout(s: Session, pp: PayPalLike, row: Outbox, job: Job, now: datetime) -> Outcome:
    if job.state != S.PAYING_OUT:
        return _skip(row, now, f"job is {job.state}, not PAYING_OUT")
    p = row.payload
    res = pp.create_payout(batch_id=row.idempotency_key, receiver=p["receiver"],
                           recipient_type=p["recipient_type"], amount=str(p["amount"]),
                           currency=job.currency, note=f"Verdict job {job.id}")
    batch_id = res["batch_header"]["payout_batch_id"]
    job.payout_batch_id = batch_id
    # A retried payout (after PAYOUT_FAILED) carries a tag, so it gets its own status row.
    enqueue(s, job.id, Action.PAYOUT_STATUS, {"batch_id": batch_id, "amount": p["amount"]},
            tag=p.get("tag", ""))
    return _done(row, now, res, f"payout batch {batch_id} created")


def _do_payout_status(s: Session, pp: PayPalLike, row: Outbox, job: Job,
                      now: datetime) -> Outcome:
    if job.state != S.PAYING_OUT:
        return _skip(row, now, f"job is {job.state}, not PAYING_OUT")
    res = pp.get_payout_batch(row.payload["batch_id"])
    items = res.get("items") or []
    status = (items[0].get("transaction_status") if items
              else res.get("batch_header", {}).get("batch_status")) or "PENDING"
    if status in PAYOUT_OK:
        ledger.post(s, job.id, f"{job.id}:payout", ledger.payout(row.payload["amount"]))
        move_job(s, job.id, S.PAYING_OUT, S.PAID, reason="payout succeeded",
                 data={"batch_id": row.payload["batch_id"]})
        return _done(row, now, {"status": status}, "worker paid")
    if status in PAYOUT_PENDING or status in ("PROCESSING",):
        if row.attempts >= MAX_PAYOUT_POLLS:
            return _fail(s, row, job, f"payout still {status} after polling",
                         move=(S.PAYING_OUT, S.PAYOUT_FAILED))
        row.next_attempt_at = now + PAYOUT_POLL_EVERY
        row.last_error = f"payout {status}"
        return Outcome(row.idempotency_key, row.action, "retry", f"payout {status}")
    return _fail(s, row, job, f"payout item {status}", move=(S.PAYING_OUT, S.PAYOUT_FAILED))


# ── error handling ───────────────────────────────────────────────────────────
def _is_transient(exc: PayPalError) -> bool:
    name = exc.body.get("name") if isinstance(exc.body, dict) else None
    return exc.status >= 500 or exc.status in TRANSIENT_HTTP or name in TRANSIENT_NAMES


def _permanent(s: Session, pp: PayPalLike, row: Outbox, job: Job, exc: PayPalError) -> Outcome:
    action = Action(row.action)
    if action is Action.VOID and job.authorization_id:
        # Already voided or expired at PayPal: no money is held, so the void goal is met.
        try:
            status = pp.get_authorization(job.authorization_id).get("status")
        except (PayPalError, httpx.HTTPError):
            status = None
        if status in ("VOIDED", "EXPIRED"):
            _finish_void(s, job, f"authorization already {status.lower()}")
            return _done(row, utcnow(), {"status": status}, f"already {status}")
    return _fail(s, row, job, str(exc), move=ON_FAILURE.get(action.value))


def _retry(s: Session, row: Outbox, job: Job, now: datetime, error: str) -> Outcome:
    if row.attempts >= MAX_ATTEMPTS:      # stop retrying and hand the job to a person
        return _fail(s, row, job, f"gave up after {row.attempts} attempts: {error}",
                     move=ON_FAILURE.get(row.action))
    row.next_attempt_at = now + min(timedelta(seconds=30 * 2 ** (row.attempts - 1)),
                                    timedelta(hours=1))
    row.last_error = error
    return Outcome(row.idempotency_key, row.action, "retry", error)


def _fail(s: Session, row: Outbox, job: Job, error: str,
          move: tuple[S, S] | None) -> Outcome:
    row.status, row.last_error, row.done_at = "failed", error, utcnow()
    if move is not None and job.state == move[0]:
        move_job(s, job.id, move[0], move[1], reason=error[:200])
    log.error("outbox %s failed: %s", row.idempotency_key, error)
    return Outcome(row.idempotency_key, row.action, "failed", error)


def _skip(row: Outbox, now: datetime, why: str) -> Outcome:
    row.status, row.last_error, row.done_at = "failed", f"skipped: {why}", now
    return Outcome(row.idempotency_key, row.action, "skipped", why)


def _done(row: Outbox, now: datetime, response: dict[str, Any] | None, detail: str) -> Outcome:
    row.status, row.done_at, row.last_error = "done", now, None
    row.response = jsonable(response or {})
    return Outcome(row.idempotency_key, row.action, "done", detail)
