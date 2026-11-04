from decimal import Decimal as D

import pytest

from verdict.core import ledger
from verdict.core.ledger import LedgerError, Line


def test_every_posting_is_balanced():
    for lines in (ledger.authorize("100.00"), ledger.capture("81.50", "77.42", "4.08"),
                  ledger.release("18.50"), ledger.void("100.00"), ledger.payout("77.42")):
        ledger.check_balanced(lines)


def test_capture_split_must_add_up():
    with pytest.raises(LedgerError):
        ledger.capture("81.50", "77.42", "4.07")


@pytest.mark.parametrize("bad", [81.5, "-1.00", "1.005"])
def test_amounts_are_exact_non_negative_cents(bad):
    with pytest.raises(LedgerError):
        ledger.authorize(bad)


def test_unbalanced_or_two_sided_lines_rejected():
    with pytest.raises(LedgerError):
        ledger.check_balanced([Line(ledger.CASH, debit=D("1.00"))])
    with pytest.raises(LedgerError):
        ledger.check_balanced([Line(ledger.CASH, debit=D("1.00"), credit=D("1.00"))])
    with pytest.raises(LedgerError):
        ledger.check_balanced([Line("made_up", debit=D("1")), Line(ledger.FEE, credit=D("1"))])


def test_paid_job_nets_to_the_fee(Session, make_job):
    job_id = make_job()
    with Session.begin() as s:
        ledger.post(s, job_id, f"{job_id}:authorize", ledger.authorize("100.00"))
        ledger.post(s, job_id, f"{job_id}:capture", ledger.capture("81.50", "77.42", "4.08"))
        ledger.post(s, job_id, f"{job_id}:release", ledger.release("18.50"))
        ledger.post(s, job_id, f"{job_id}:payout", ledger.payout("77.42"))
        ledger.check_finished(s, job_id, worker_paid=True)
        b = ledger.balances(s, job_id)
    assert b[ledger.CASH] == D("4.08") and b[ledger.FEE] == D("-4.08")
    assert b[ledger.PAYABLE] == 0 and b[ledger.HOLD] == 0 and b[ledger.COMMIT] == 0


def test_voided_job_nets_to_zero(Session, make_job):
    job_id = make_job()
    with Session.begin() as s:
        ledger.post(s, job_id, f"{job_id}:authorize", ledger.authorize("100.00"))
        ledger.post(s, job_id, f"{job_id}:void", ledger.void("100.00"))
        ledger.check_finished(s, job_id, worker_paid=True)
        assert all(v == 0 for v in ledger.balances(s, job_id).values())


def test_reposting_same_ref_is_a_no_op(Session, make_job):
    job_id = make_job()
    with Session.begin() as s:
        for _ in range(3):   # a retried worker step
            ledger.post(s, job_id, f"{job_id}:authorize", ledger.authorize("100.00"))
        assert ledger.balances(s, job_id)[ledger.HOLD] == D("100.00")


def test_unfinished_hold_fails_the_invariant(Session, make_job):
    job_id = make_job()
    with Session.begin() as s:
        ledger.post(s, job_id, f"{job_id}:authorize", ledger.authorize("100.00"))
        with pytest.raises(LedgerError):
            ledger.check_finished(s, job_id, worker_paid=False)
