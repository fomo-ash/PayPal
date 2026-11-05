"""The whole product through the API, PayPal mocked, sandbox = LocalRunner:
post → suite → validate → fund → claim → submit → grade → capture/void → payout → code."""

import json
import uuid
from decimal import Decimal

from test_money_worker import mock_capture_and_payout

from verdict.core import ledger
from verdict.db.repo import verify_audit_chain
from verdict.sandbox.runner import LocalRunner
from verdict.worker import grading, money


def grade_and_settle(api, sub_id):
    svc = api.services
    out = grading.grade_submission(svc.Session, svc.store, LocalRunner(), uuid.UUID(sub_id))
    steps = []
    for _ in range(10):
        step = money.process_outbox(svc.Session, svc.paypal)
        if not step:
            break
        steps += step
    return out, steps


def test_honest_worker_is_paid_and_buyer_gets_the_code(api, submitted, pp, Session):
    buyer, worker, job_id, sub_id = submitted("honest_full")
    cap, pay = mock_capture_and_payout(pp)
    out, steps = grade_and_settle(api, sub_id)
    assert out.state == "CAPTURING" and [s.result for s in steps] == ["done"] * 3

    view = api.get(f"/submissions/{sub_id}", headers=worker).json()
    assert view["job_state"] == "PAID"
    assert view["verdict"]["capture"] == "100.00"
    assert view["verdict"]["fee"] == "5.00" and view["verdict"]["worker_amount"] == "95.00"
    assert json.loads(cap.calls.last.request.content)["amount"]["value"] == "100.00"
    item = json.loads(pay.calls.last.request.content)["items"][0]
    assert item["recipient_type"] == "PAYPAL_ID" and item["amount"]["value"] == "95.00"

    code = api.get(f"/submissions/{sub_id}/code", headers=buyer)
    assert code.status_code == 200 and "def solve" in code.json()["files"]["solution.py"]
    assert api.get(f"/jobs/{job_id}", headers=buyer).json()["state"] == "CODE_RELEASED"

    with Session() as s:
        jid = uuid.UUID(job_id)
        ledger.check_finished(s, jid, worker_paid=True)
        assert ledger.balances(s, jid)["platform_fee"] == Decimal("-5.00")
        assert verify_audit_chain(s, jid)


def test_memorizer_is_voided_and_buyer_keeps_everything(api, submitted, pp, Session):
    buyer, worker, job_id, sub_id = submitted("cheat_memorizer")
    void = pp.mock.post("/v2/payments/authorizations/AUTH-1/void").respond(204)
    out, steps = grade_and_settle(api, sub_id)
    assert out.state == "VOIDING" and void.call_count == 1
    view = api.get(f"/submissions/{sub_id}", headers=buyer).json()
    assert view["job_state"] == "VOIDED" and view["verdict"]["capture"] == "0.00"
    fresh = [r for r in view["runs"] if r["kind"] == "fresh"][0]
    assert fresh["total"] == 200 and fresh["passed"] < 50
    assert api.get(f"/submissions/{sub_id}/code", headers=buyer).status_code == 409
    with Session() as s:
        ledger.check_finished(s, uuid.UUID(job_id), worker_paid=False)
        assert verify_audit_chain(s, uuid.UUID(job_id))


def test_partial_work_gets_partial_pay(api, submitted, pp):
    buyer, _, job_id, sub_id = submitted("honest_partial")
    mock_capture_and_payout(pp)
    grade_and_settle(api, sub_id)
    v = api.get(f"/submissions/{sub_id}", headers=buyer).json()["verdict"]
    capture = Decimal(v["capture"])
    assert Decimal("50.00") <= capture < Decimal("100.00")
    assert Decimal(v["released"]) == Decimal("100.00") - capture
