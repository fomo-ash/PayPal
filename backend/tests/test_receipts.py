"""Signed receipts: issued once money settles, verifiable by anyone, tamper-evident."""

import copy
import uuid

import pytest
from test_e2e_api import grade_and_settle
from test_money_worker import mock_capture_and_payout

from verdict.receipts import signing


@pytest.fixture
def keyed(api):
    api.services.settings.receipt_signing_key_b64 = signing.generate_private_key_b64()
    return api


def paid_job(api, submitted, pp):
    buyer, worker, job_id, sub_id = submitted("honest_full")
    mock_capture_and_payout(pp)
    grade_and_settle(api, sub_id)
    return buyer, worker, job_id


def test_paid_job_gets_a_valid_receipt(keyed, submitted, pp):
    api = keyed
    buyer, worker, job_id = paid_job(api, submitted, pp)
    doc = api.get(f"/receipts/{job_id}", headers=buyer).json()
    r = doc["receipt"]
    assert r["job"]["id"] == job_id and r["decision"]["settlement"] == "CAPTURE"
    assert r["decision"]["capture"] == "100.00" and r["decision"]["worker"] == "95.00"
    assert r["paypal"]["authorization_id"] == "AUTH-1" and r["paypal"]["capture_id"]
    assert r["suite_sha256"] and r["submission_sha256"] and r["audit_head_hash"]
    v = api.post("/receipts/verify", json=doc).json()
    assert v == {"valid": True, "key_id": r["key_id"], "signed_by_this_key": True,
                 "job_id": job_id}
    assert api.get(f"/receipts/{job_id}", headers=worker).json() == doc   # issued once


def test_changing_one_cent_breaks_the_signature(keyed, submitted, pp):
    api = keyed
    buyer, _, job_id = paid_job(api, submitted, pp)
    doc = api.get(f"/receipts/{job_id}", headers=buyer).json()
    forged = copy.deepcopy(doc)
    forged["receipt"]["decision"]["worker"] = "95.01"
    assert api.post("/receipts/verify", json=forged).json()["valid"] is False
    junk = {"receipt": doc["receipt"], "signature": "not-base64!"}
    assert api.post("/receipts/verify", json=junk).json()["valid"] is False


def test_offline_verification_with_the_public_key(keyed, submitted, pp):
    api = keyed
    buyer, _, job_id = paid_job(api, submitted, pp)
    doc = api.get(f"/receipts/{job_id}", headers=buyer).json()
    pub = api.get("/receipts/public-key").json()
    assert pub["key_id"] == doc["receipt"]["key_id"]
    assert signing.verify(doc["receipt"], doc["signature"], pub["public_key"])


def test_voided_job_receipt(keyed, submitted, pp):
    api = keyed
    buyer, _, job_id, sub_id = submitted("cheat_memorizer")
    pp.mock.post("/v2/payments/authorizations/AUTH-1/void").respond(204)
    grade_and_settle(api, sub_id)
    r = api.get(f"/receipts/{job_id}", headers=buyer).json()["receipt"]
    assert r["decision"]["settlement"] == "VOID" and r["decision"]["released"] == "100.00"
    assert {x["kind"] for x in r["results"]} == {"hidden", "fresh"}


def test_no_receipt_before_settlement_or_for_strangers(keyed, submitted, user):
    api = keyed
    buyer, _, job_id, _ = submitted("honest_full")
    assert api.get(f"/receipts/{job_id}", headers=buyer).status_code == 409
    stranger = user("buyer", email="stranger@example.com")
    assert api.get(f"/receipts/{job_id}", headers=stranger).status_code == 404
    assert api.get(f"/receipts/{uuid.uuid4()}", headers=buyer).status_code == 404


def test_not_configured(api):
    api.services.settings.receipt_signing_key_b64 = ""
    assert api.get("/receipts/public-key").status_code == 503
