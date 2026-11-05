import json
import uuid
from decimal import Decimal

from conftest import mock_order

from verdict.core import ledger
from verdict.db.models import Job


def test_fund_and_confirm_opens_job_with_sealed_suite(api, draft_job, pp, Session):
    h, job_id = draft_job()
    sha = api.get(f"/jobs/{job_id}", headers=h).json()["uploaded_suite_sha256"]
    authorize = mock_order(pp, job_id)
    r = api.post(f"/jobs/{job_id}/fund", headers=h).json()
    assert r == {"order_id": "ORDER-1", "status": "PAYER_ACTION_REQUIRED",
                 "approve_url": "https://sandbox.paypal.test/ORDER-1"}
    sent = json.loads(pp.mock.calls[-1].request.content)
    assert sent["intent"] == "AUTHORIZE"
    assert sent["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "100.00"}
    assert sent["purchase_units"][0]["reference_id"] == job_id

    r = api.post(f"/jobs/{job_id}/fund/confirm", headers=h).json()
    assert r["state"] == "OPEN" and r["suite_sha256"] == sha
    assert authorize.calls.last.request.headers["PayPal-Request-Id"] == \
        f"verdict-{job_id}-authorize"
    # a second confirm is harmless
    assert api.post(f"/jobs/{job_id}/fund/confirm", headers=h).json()["state"] == "OPEN"
    assert authorize.call_count == 1

    assert [j["id"] for j in api.get("/jobs").json()] == [job_id]
    with Session() as s:
        job = s.get(Job, uuid.UUID(job_id))
        assert job.authorization_id == "AUTH-1" and job.suite_sha256 == sha
        assert ledger.balances(s, job.id)["hold_memo"] == Decimal("100.00")


def test_confirm_before_approval_is_409(api, draft_job, pp):
    h, job_id = draft_job()
    mock_order(pp, job_id)
    api.post(f"/jobs/{job_id}/fund", headers=h)
    pp.mock.post("/v2/checkout/orders/ORDER-1/authorize").respond(422, json={
        "name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_NOT_APPROVED"}]})
    r = api.post(f"/jobs/{job_id}/fund/confirm", headers=h)
    assert r.status_code == 409 and "not approved" in r.json()["detail"]


def test_wrong_amount_or_other_jobs_order_refused(api, draft_job, pp):
    h, job_id = draft_job()
    mock_order(pp, job_id, amount="1.00")
    api.post(f"/jobs/{job_id}/fund", headers=h)
    r = api.post(f"/jobs/{job_id}/fund/confirm", headers=h)
    assert r.status_code == 409 and "amount" in r.json()["detail"]

    h2, job2 = draft_job()
    mock_order(pp, job_id)          # order references the FIRST job
    api.post(f"/jobs/{job2}/fund", headers=h2)
    r = api.post(f"/jobs/{job2}/fund/confirm", headers=h2)
    assert r.status_code == 409 and "another job" in r.json()["detail"]


def test_pending_authorization_is_not_funding(api, draft_job, pp):
    h, job_id = draft_job()
    mock_order(pp, job_id, status="PENDING")
    api.post(f"/jobs/{job_id}/fund", headers=h)
    assert api.post(f"/jobs/{job_id}/fund/confirm", headers=h).status_code == 409


def test_fund_reuses_a_live_order(api, draft_job, pp):
    h, job_id = draft_job()
    mock_order(pp, job_id)
    api.post(f"/jobs/{job_id}/fund", headers=h)
    pp.mock.get("/v2/checkout/orders/ORDER-1").respond(json={
        "id": "ORDER-1", "status": "PAYER_ACTION_REQUIRED", "links": []})
    assert api.post(f"/jobs/{job_id}/fund", headers=h).json()["order_id"] == "ORDER-1"
    assert pp.mock.routes[1].call_count == 1          # create order called once


def test_fund_needs_validation(api, draft_job, pp):
    h, job_id = draft_job(validate=False)
    assert api.post(f"/jobs/{job_id}/fund", headers=h).status_code == 409
