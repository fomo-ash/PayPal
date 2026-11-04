"""Double-entry ledger. Every money event posts a BALANCED set of entries (Σ debit == Σ credit).

Accounts (all amounts in the job's currency):
  hold_memo          the buyer's authorization (memo: money PayPal is holding for us)
  buyer_commitment   the other side of the memo; cleared by capture, release or void
  paypal_cash        money actually captured into the platform's PayPal balance
  worker_payable     what we owe the worker
  platform_fee       Verdict's revenue

Postings for a $100 job, 81.5% score, 5% fee (capture 81.50 = worker 77.42 + fee 4.08):

  authorize 100.00   Dr hold_memo 100.00          Cr buyer_commitment 100.00
  capture    81.50   Dr buyer_commitment 81.50    Cr hold_memo 81.50
                     Dr paypal_cash 81.50         Cr worker_payable 77.42, platform_fee 4.08
  release    18.50   Dr buyer_commitment 18.50    Cr hold_memo 18.50
  payout     77.42   Dr worker_payable 77.42      Cr paypal_cash 77.42
  void      100.00   Dr buyer_commitment 100.00   Cr hold_memo 100.00

Invariants once a job is finished (tested):
  hold_memo = buyer_commitment = worker_payable = 0
  paypal_cash (debit balance) == platform_fee (credit balance) == the fee we kept
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from verdict.core.scoring import CENT, ZERO

HOLD, COMMIT, CASH, PAYABLE, FEE = (
    "hold_memo", "buyer_commitment", "paypal_cash", "worker_payable", "platform_fee",
)
ACCOUNTS = (HOLD, COMMIT, CASH, PAYABLE, FEE)


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    account: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO


def _money(x: Decimal | str) -> Decimal:
    if isinstance(x, float):
        raise LedgerError("ledger amounts must be Decimal or str, not float")
    d = Decimal(str(x))
    if d < ZERO or d != d.quantize(CENT):
        raise LedgerError(f"bad amount {x!r}: must be >= 0 with at most 2 decimals")
    return d


def authorize(amount: Decimal | str) -> list[Line]:
    a = _money(amount)
    return [Line(HOLD, debit=a), Line(COMMIT, credit=a)]


def capture(capture: Decimal | str, worker: Decimal | str, fee: Decimal | str) -> list[Line]:
    c, w, f = _money(capture), _money(worker), _money(fee)
    if w + f != c:
        raise LedgerError(f"capture {c} != worker {w} + fee {f}")
    return [Line(COMMIT, debit=c), Line(HOLD, credit=c),
            Line(CASH, debit=c), Line(PAYABLE, credit=w), Line(FEE, credit=f)]


def release(amount: Decimal | str) -> list[Line]:
    """Remainder returned to the buyer by capture(final_capture=true)."""
    r = _money(amount)
    return [Line(COMMIT, debit=r), Line(HOLD, credit=r)]


def void(amount: Decimal | str) -> list[Line]:
    v = _money(amount)
    return [Line(COMMIT, debit=v), Line(HOLD, credit=v)]


def payout(amount: Decimal | str) -> list[Line]:
    p = _money(amount)
    return [Line(PAYABLE, debit=p), Line(CASH, credit=p)]


def check_balanced(lines: list[Line]) -> None:
    for ln in lines:
        if ln.account not in ACCOUNTS:
            raise LedgerError(f"unknown account {ln.account!r}")
        if ln.debit < ZERO or ln.credit < ZERO or (ln.debit > ZERO and ln.credit > ZERO):
            raise LedgerError("each line must be a debit OR a credit")
    dr = sum((ln.debit for ln in lines), ZERO)
    cr = sum((ln.credit for ln in lines), ZERO)
    if dr != cr:
        raise LedgerError(f"unbalanced posting: debit {dr} != credit {cr}")


def post(session: Session, job_id: uuid.UUID, ref: str, lines: list[Line]) -> None:
    """Write one balanced posting. `ref` is unique per event (e.g. '<job>:capture'): posting the
    same ref twice is a no-op, so a retried worker step can never double-count money."""
    from verdict.db.models import LedgerEntry

    check_balanced(lines)
    exists = session.scalar(select(LedgerEntry.id).where(LedgerEntry.ref == ref).limit(1))
    if exists is not None:
        return
    nonzero = [ln for ln in lines if ln.debit or ln.credit]
    for ln in nonzero:
        session.add(LedgerEntry(job_id=job_id, account=ln.account, debit=ln.debit,
                                credit=ln.credit, ref=ref))
    session.flush()


def balances(session: Session, job_id: uuid.UUID) -> dict[str, Decimal]:
    """Net balance per account as debit − credit."""
    from verdict.db.models import LedgerEntry

    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    rows = session.execute(select(LedgerEntry.account, LedgerEntry.debit, LedgerEntry.credit)
                           .where(LedgerEntry.job_id == job_id))
    for account, debit, credit in rows:
        out[account] += Decimal(debit) - Decimal(credit)
    return {a: out[a] for a in ACCOUNTS}


def check_finished(session: Session, job_id: uuid.UUID, *, worker_paid: bool) -> None:
    """Invariant for a job in a terminal state. Raises LedgerError if money does not add up."""
    b = balances(session, job_id)
    if b[HOLD] != ZERO or b[COMMIT] != ZERO:
        raise LedgerError(f"hold not cleared: {b}")
    if worker_paid and b[PAYABLE] != ZERO:
        raise LedgerError(f"worker_payable not settled: {b}")
    if b[CASH] + b[PAYABLE] != -b[FEE]:          # cash we hold − what we still owe == our fee
        raise LedgerError(f"cash does not equal fee + unpaid worker balance: {b}")
