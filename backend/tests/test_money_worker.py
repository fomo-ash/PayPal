"""Money worker against a mocked PayPal (respx). No network, no keys."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
import respx
from sqlalchemy import select

from verdict.core import ledger
from verdict.core.outbox import Action, idempotency_key
from verdict.core.policy import AIDecision, HardSignal, decide
from verdict.core.policy import resolve_review as policy_review
from verdict.core.scoring import GroupResult, compute_payout
from verdict.core.state_machine import JobState as S
from verdict.db.models import Claim, Job, Outbox, Submission, User, Verdict
from verdict.db.repo import move_job, verify_audit_chain
from verdict.paypal.client import PayPalClient
from verdict.worker import money

BASE = "https://api-m.sandbox.paypal.com"
AUTH = "AUTH-1"
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def pp():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/v1/oauth2/token").respond(json={"access_token": "t", "expires_in": 3600})
        client = PayPalClient(BASE, "id", "secret")
        client.mock = mock
        yield client
        client.close()


def honest_payout():   # README example: 81.5% → capture 81.50, fee 4.08, worker 77.42
    return compute_payout("100.00", [
        GroupResult("core", D("0.60"), 9, 10, 196, 200),
        GroupResult("edge", D("0.25"), 4, 8), GroupResult("perf", D("0.15"), 2, 2)],
        "0.50", 500)


def job_in_judging(Session, make_job, payer_id="WORKERPAYER1"):
    job_id = make_job(S.AWAITING_FUNDS)
    with Session.begin() as s:
        money.record_authorization(s, job_id, order_id="ORDER-1", authorization_id=AUTH,
                                   amount="100.00", now=T0)
        worker = User(email="w@example.com", paypal_payer_id=payer_id, role="worker")
        s.add(worker)
        s.flush()
        claim = Claim(job_id=job_id, worker_id=worker.id, deadline_at=T0 + timedelta(hours=24))
        s.add(claim)
        s.flush()
        sub = Submission(claim_id=claim.id, job_id=job_id, worker_id=worker.id, r2_key="k",
                         sha256="0" * 64)
        s.add(sub)
        s.flush()
        for a, b in [(S.FUNDED, S.OPEN), (S.OPEN, S.CLAIMED), (S.CLAIMED, S.SUBMITTED),
                     (S.SUBMITTED, S.GRADING), (S.GRADING, S.JUDGING)]:
            move_job(s, job_id, a, b)
        return job_id, sub.id


def mock_capture_and_payout(pp, payout_status="SUCCESS"):
    cap = pp.mock.post(f"/v2/payments/authorizations/{AUTH}/capture").respond(
        json={"id": "CAP-1", "status": "COMPLETED"})
    pay = pp.mock.post("/v1/payments/payouts").respond(
        201, json={"batch_header": {"payout_batch_id": "BATCH-1", "batch_status": "PENDING"}})
    pp.mock.get("/v1/payments/payouts/BATCH-1").respond(
        json={"batch_header": {"batch_status": "SUCCESS"},
              "items": [{"transaction_status": payout_status}]})
    return cap, pay


def state(Session, job_id):
    with Session() as s:
        return s.get(Job, job_id).state


def run_until_idle(Session, pp, now=T0):
    out = []
    for _ in range(10):
        step = money.process_outbox(Session, pp, now=now)
        if not step:
            return out
        out += step
    return out


def test_happy_path_capture_release_payout(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    cap, pay = mock_capture_and_payout(pp)
    p = honest_payout()
    with Session.begin() as s:
        assert money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.CLEAR)) \
            is S.CAPTURING
    outcomes = run_until_idle(Session, pp)
    assert [o.result for o in outcomes] == ["done", "done", "done"]
    assert state(Session, job_id) == "PAID"

    body = json.loads(cap.calls.last.request.content)
    assert body["amount"] == {"currency_code": "USD", "value": "81.50"}
    assert body["final_capture"] is True                        # remainder released
    assert cap.calls.last.request.headers["PayPal-Request-Id"] == \
        idempotency_key(job_id, Action.CAPTURE)
    item = json.loads(pay.calls.last.request.content)["items"][0]
    assert item["amount"]["value"] == "77.42"
    assert (item["recipient_type"], item["receiver"]) == ("PAYPAL_ID", "WORKERPAYER1")

    with Session() as s:
        ledger.check_finished(s, job_id, worker_paid=True)
        assert ledger.balances(s, job_id)[ledger.FEE] == D("-4.08")
        assert verify_audit_chain(s, job_id)
        v = s.scalar(select(Verdict).where(Verdict.job_id == job_id))
        assert (v.capture, v.fee, v.worker_amount, v.released) == \
            (D("81.50"), D("4.08"), D("77.42"), D("18.50"))


def test_paypal_5xx_retries_with_the_same_idempotency_key(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    cap = pp.mock.post(f"/v2/payments/authorizations/{AUTH}/capture").mock(side_effect=[
        httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"}),
        httpx.Response(201, json={"id": "CAP-1", "status": "COMPLETED"}),
    ])
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.CLEAR))
    first = money.process_outbox(Session, pp, now=T0, limit=1)
    assert first[0].result == "retry" and state(Session, job_id) == "CAPTURING"
    assert money.process_outbox(Session, pp, now=T0, limit=1) == []     # backed off, not due
    second = money.process_outbox(Session, pp, now=T0 + timedelta(minutes=5), limit=1)
    assert second[0].result == "done" and state(Session, job_id) == "PAYING_OUT"
    keys = {c.request.headers["PayPal-Request-Id"] for c in cap.calls}
    assert keys == {idempotency_key(job_id, Action.CAPTURE)}           # same key both times


def test_crash_after_paypal_call_rolls_back_and_retries_safely(Session, make_job, pp,
                                                              monkeypatch):
    job_id, sub_id = job_in_judging(Session, make_job)
    cap, _ = mock_capture_and_payout(pp)
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.CLEAR))
    real_post = ledger.post
    monkeypatch.setattr(ledger, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    out = money.process_outbox(Session, pp, now=T0, limit=1)
    assert out[0].result == "retry" and "disk" in out[0].detail
    with Session() as s:          # nothing half-written: no ledger entries, state unchanged
        assert state(Session, job_id) == "CAPTURING"
        assert ledger.balances(s, job_id)[ledger.CASH] == 0
    monkeypatch.setattr(ledger, "post", real_post)
    run_until_idle(Session, pp, now=T0 + timedelta(hours=1))
    assert state(Session, job_id) == "PAID"
    assert len({c.request.headers["PayPal-Request-Id"] for c in cap.calls}) == 1


def test_hard_signal_voids_the_hold(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    void = pp.mock.post(f"/v2/payments/authorizations/{AUTH}/void").respond(204)
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [HardSignal.GRADER_INJECTION],
                                                  AIDecision.CLEAR))
    run_until_idle(Session, pp)
    assert state(Session, job_id) == "VOIDED" and void.called
    with Session() as s:
        ledger.check_finished(s, job_id, worker_paid=True)
        assert all(v == 0 for v in ledger.balances(s, job_id).values())


def test_void_of_an_already_voided_hold_counts_as_done(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    pp.mock.post(f"/v2/payments/authorizations/{AUTH}/void").respond(
        422, json={"name": "UNPROCESSABLE_ENTITY"})
    pp.mock.get(f"/v2/payments/authorizations/{AUTH}").respond(json={"status": "VOIDED"})
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [HardSignal.NETWORK_ATTEMPT],
                                                  AIDecision.CLEAR))
    run_until_idle(Session, pp)
    assert state(Session, job_id) == "VOIDED"


def test_refused_capture_goes_to_a_person_not_stuck(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    pp.mock.post(f"/v2/payments/authorizations/{AUTH}/capture").respond(
        422, json={"name": "UNPROCESSABLE_ENTITY",
                   "details": [{"issue": "AUTHORIZATION_EXPIRED"}]})
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.CLEAR))
    out = run_until_idle(Session, pp)
    assert out[0].result == "failed" and state(Session, job_id) == "HUMAN_REVIEW"
    with Session() as s:
        assert ledger.balances(s, job_id)[ledger.CASH] == 0      # nothing was captured


def test_unclaimed_payout_is_flagged(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    mock_capture_and_payout(pp, payout_status="UNCLAIMED")
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.CLEAR))
    run_until_idle(Session, pp)
    assert state(Session, job_id) == "PAYOUT_FAILED"
    with Session() as s:   # we still owe the worker 77.42: visible in the ledger
        assert ledger.balances(s, job_id)[ledger.PAYABLE] == D("-77.42")


def test_pending_payout_is_polled_until_final(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    mock_capture_and_payout(pp)
    pp.mock.get("/v1/payments/payouts/BATCH-1").mock(side_effect=[
        httpx.Response(200, json={"items": [{"transaction_status": "PENDING"}]}),
        httpx.Response(200, json={"items": [{"transaction_status": "SUCCESS"}]}),
    ])
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.CLEAR))
    run_until_idle(Session, pp)
    assert state(Session, job_id) == "PAYING_OUT"
    run_until_idle(Session, pp, now=T0 + timedelta(minutes=2))
    assert state(Session, job_id) == "PAID"


def test_ai_block_waits_for_a_person_who_can_only_lower(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    cap, pay = mock_capture_and_payout(pp)
    p = honest_payout()
    with Session.begin() as s:
        assert money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.BLOCK_RECOMMENDED)) \
            is S.HUMAN_REVIEW
    assert money.process_outbox(Session, pp, now=T0) == []           # no money moves
    with Session.begin() as s:
        money.resolve_review(s, job_id, policy_review(p, "50.00"), reviewer="admin@verdict")
    run_until_idle(Session, pp)
    assert json.loads(cap.calls.last.request.content)["amount"]["value"] == "50.00"
    assert json.loads(pay.calls.last.request.content)["items"][0]["amount"]["value"] == "47.50"
    with Session() as s:
        v = s.scalar(select(Verdict).where(Verdict.job_id == job_id))
        assert (v.decided_by, v.fee, v.released) == ("human", D("2.50"), D("50.00"))


def test_authorization_amount_must_match_the_job(Session, make_job):
    job_id = make_job(S.AWAITING_FUNDS)
    with pytest.raises(money.MoneyError), Session.begin() as s:
        money.record_authorization(s, job_id, order_id="O", authorization_id="A",
                                   amount="10.00")
    assert state(Session, job_id) == "AWAITING_FUNDS"


def test_email_receiver_used_when_no_payer_id(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job, payer_id=None)
    _, pay = mock_capture_and_payout(pp)
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.CLEAR))
    run_until_idle(Session, pp)
    item = json.loads(pay.calls.last.request.content)["items"][0]
    assert (item["recipient_type"], item["receiver"]) == ("EMAIL", "w@example.com")


@pytest.mark.parametrize("amount", ["100.00", "37.13", "0.99", "12345.67"])
def test_split_capture_matches_scoring(amount):
    for passed in range(11):
        p = compute_payout(amount, [GroupResult("all", D("1"), passed, 10)], "0", 500)
        assert money.split_capture(p.capture, 500) == (p.fee, p.worker)


def test_no_outbox_row_is_ever_left_pending_forever(Session, make_job, pp):
    job_id, sub_id = job_in_judging(Session, make_job)
    pp.mock.post(f"/v2/payments/authorizations/{AUTH}/capture").respond(503)
    p = honest_payout()
    with Session.begin() as s:
        money.settle(s, job_id, sub_id, p, decide(p, [], AIDecision.CLEAR))
    now = T0
    for _ in range(money.MAX_ATTEMPTS + 2):
        money.process_outbox(Session, pp, now=now)
        now += timedelta(hours=2)
    with Session() as s:
        row = s.scalar(select(Outbox).where(Outbox.job_id == job_id))
        assert row.status == "failed" and row.attempts == money.MAX_ATTEMPTS
    assert state(Session, job_id) == "HUMAN_REVIEW"          # handed to a person, not stuck
