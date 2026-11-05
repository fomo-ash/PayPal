import uuid

from verdict.db.models import AuditLog, PayPalEvent

VERIFY = "/v1/notifications/verify-webhook-signature"


def event(eid="WH-EVT-1", etype="PAYMENT.CAPTURE.COMPLETED", auth="AUTH-1"):
    return {"id": eid, "event_type": etype, "resource": {
        "id": "CAP-9", "status": "COMPLETED",
        "supplementary_data": {"related_ids": {"authorization_id": auth}}}}


def test_verified_event_is_stored_once_and_audited(api, open_job, pp, Session):
    _, job_id = open_job()
    verify = pp.mock.post(VERIFY).respond(json={"verification_status": "SUCCESS"})
    headers = {"PAYPAL-TRANSMISSION-ID": "t1", "PAYPAL-AUTH-ALGO": "SHA256withRSA"}
    assert api.post("/webhooks/paypal", json=event(), headers=headers).json() == \
        {"result": "stored"}
    assert api.post("/webhooks/paypal", json=event(), headers=headers).json() == \
        {"result": "duplicate"}
    sent = verify.calls[0].request
    assert b'"webhook_id":"WH-1"' in sent.content.replace(b" ", b"")
    assert b'"transmission_id":"t1"' in sent.content.replace(b" ", b"")
    with Session() as s:
        assert s.query(PayPalEvent).count() == 1
        last = s.query(AuditLog).filter_by(job_id=uuid.UUID(job_id)).order_by(
            AuditLog.seq.desc()).first()
        assert last.event == "webhook:PAYMENT.CAPTURE.COMPLETED"
        assert last.payload["status"] == "COMPLETED"


def test_unverified_event_is_refused_and_not_stored(api, pp, Session):
    pp.mock.post(VERIFY).respond(json={"verification_status": "FAILURE"})
    r = api.post("/webhooks/paypal", json=event())
    assert r.status_code == 400
    with Session() as s:
        assert s.query(PayPalEvent).count() == 0


def test_webhook_never_changes_job_state(api, open_job, pp):
    buyer, job_id = open_job()
    pp.mock.post(VERIFY).respond(json={"verification_status": "SUCCESS"})
    for i, t in enumerate(["PAYMENT.AUTHORIZATION.VOIDED", "PAYMENT.CAPTURE.COMPLETED",
                           "PAYMENT.PAYOUTS-ITEM.SUCCEEDED"]):
        api.post("/webhooks/paypal", json=event(f"E{i}", t))
    assert api.get(f"/jobs/{job_id}", headers=buyer).json()["state"] == "OPEN"


def test_unknown_resource_is_stored_unmatched(api, pp):
    pp.mock.post(VERIFY).respond(json={"verification_status": "SUCCESS"})
    assert api.post("/webhooks/paypal", json=event(auth="NOPE")).json() == \
        {"result": "unmatched"}


def test_malformed_events(api, pp):
    pp.mock.post(VERIFY).respond(json={"verification_status": "SUCCESS"})
    assert api.post("/webhooks/paypal", content=b"not json").status_code == 400
    assert api.post("/webhooks/paypal", json=[1, 2]).status_code == 400
    assert api.post("/webhooks/paypal", json={"event_type": "X"}).status_code == 400
