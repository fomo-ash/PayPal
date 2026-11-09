"""Human review queue: an admin can lower or void, never raise; money moves only after."""

import json
import uuid
from decimal import Decimal

import pytest
from test_ai_review import grade, says
from test_money_worker import mock_capture_and_payout

from verdict.core import ledger
from verdict.db.repo import verify_audit_chain
from verdict.worker import money


@pytest.fixture
def in_review(api, submitted):
    """A job the AI flagged → (buyer, worker, job id, submission id) in HUMAN_REVIEW."""
    buyer, worker, job_id, sub_id = submitted("honest_full")
    assert grade(api, sub_id, says("BLOCK_RECOMMENDED", ["suspicious"])).state == "HUMAN_REVIEW"
    kicked = []
    api.services.kick_money = kicked.append
    api.kicked = kicked
    return buyer, worker, job_id, sub_id


def run_outbox(api):
    for _ in range(10):
        if not money.process_outbox(api.services.Session, api.services.paypal):
            return


def test_only_admins_see_the_queue(api, user, in_review):
    buyer, worker, job_id, _ = in_review
    for h in (buyer, worker, user("worker", email="other@example.com")):
        assert api.get("/admin/reviews", headers=h).status_code == 403
        assert api.post(f"/admin/reviews/{job_id}", json={"capture": "1.00"},
                        headers=h).status_code == 403


def test_queue_and_case_show_what_a_reviewer_needs(api, user, in_review):
    _, _, job_id, sub_id = in_review
    admin = user("admin", email="admin@example.com")
    q = api.get("/admin/reviews", headers=admin).json()
    assert [(c["job_id"], c["max_capture"]) for c in q] == [(job_id, "100.00")]
    c = api.get(f"/admin/reviews/{job_id}", headers=admin).json()
    assert c["submission"]["id"] == sub_id and "def solve" in c["code"]["solution.py"]
    assert c["submission"]["ai_review"]["decision"] == "BLOCK_RECOMMENDED"


def test_reviewer_lowers_the_capture_and_worker_is_paid(api, user, pp, in_review, Session):
    _, worker, job_id, sub_id = in_review
    admin = user("admin", email="admin@example.com")
    cap, pay = mock_capture_and_payout(pp)
    r = api.post(f"/admin/reviews/{job_id}", json={"capture": "60.00", "note": "partly ok"},
                 headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"state": "CAPTURING", "settlement": "CAPTURE", "capture": "60.00"}
    assert api.kicked == [uuid.UUID(job_id)]
    run_outbox(api)
    assert json.loads(cap.calls.last.request.content)["amount"]["value"] == "60.00"
    assert json.loads(pay.calls.last.request.content)["items"][0]["amount"]["value"] == "57.00"
    v = api.get(f"/submissions/{sub_id}", headers=worker).json()
    assert v["job_state"] == "PAID" and v["verdict"]["decided_by"] == "human"
    assert v["verdict"]["released"] == "40.00"
    with Session() as s:
        jid = uuid.UUID(job_id)
        ledger.check_finished(s, jid, worker_paid=True)
        assert ledger.balances(s, jid)["platform_fee"] == Decimal("-3.00")
        assert verify_audit_chain(s, jid)


def test_reviewer_voids(api, user, pp, in_review):
    buyer, _, job_id, _ = in_review
    admin = user("admin", email="admin@example.com")
    void = pp.mock.post("/v2/payments/authorizations/AUTH-1/void").respond(204)
    r = api.post(f"/admin/reviews/{job_id}", json={"capture": "0"}, headers=admin).json()
    assert r["state"] == "VOIDING" and r["settlement"] == "VOID"
    run_outbox(api)
    assert void.call_count == 1
    assert api.get(f"/jobs/{job_id}", headers=buyer).json()["state"] == "VOIDED"


@pytest.mark.parametrize("bad", ["100.01", "250", "-1", "abc", "1.001", "NaN"])
def test_reviewer_cannot_raise_or_send_nonsense(api, user, in_review, bad):
    _, _, job_id, _ = in_review
    admin = user("admin", email="admin@example.com")
    r = api.post(f"/admin/reviews/{job_id}", json={"capture": bad}, headers=admin)
    assert r.status_code == 422
    assert api.get("/admin/reviews", headers=admin).json()[0]["job_id"] == job_id


def test_decided_case_cannot_be_decided_again(api, user, pp, in_review):
    _, _, job_id, _ = in_review
    admin = user("admin", email="admin@example.com")
    mock_capture_and_payout(pp)
    assert api.post(f"/admin/reviews/{job_id}", json={"capture": "10.00"},
                    headers=admin).status_code == 200
    again = api.post(f"/admin/reviews/{job_id}", json={"capture": "5.00"}, headers=admin)
    assert again.status_code == 409


def test_admin_cannot_review_own_job(api, submitted, user):
    buyer, _, job_id, sub_id = submitted("honest_full")
    grade(api, sub_id, says("HUMAN_REVIEW"))
    with api.services.Session() as s:
        from verdict.db.models import User
        u = s.get(User, uuid.UUID(buyer["X-User-Id"]))
        u.role = "admin"
        s.commit()
    r = api.post(f"/admin/reviews/{job_id}", json={"capture": "1.00"}, headers=buyer)
    assert r.status_code == 403 and "part of" in r.text
