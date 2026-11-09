"""Single-process ticker: the beat jobs run without Celery."""

import uuid
from datetime import timedelta

from verdict.db.models import Claim, Submission, utcnow
from verdict.worker import inline


def test_tick_expires_a_lapsed_claim(api, user, open_job, Session):
    _, job_id = open_job()
    w = user("worker", email="w@example.com", paypal_payer_id="PTICK1")
    assert api.post(f"/jobs/{job_id}/claim", headers=w).status_code == 201
    with Session.begin() as s:
        s.query(Claim).one().deadline_at = utcnow() - timedelta(minutes=1)
    assert inline.tick(api.services, {"claims"}) == {"claims": 1}
    assert api.get(f"/jobs/{job_id}", headers=w).json()["state"] == "OPEN"


def test_tick_regrades_a_lost_submission(api, submitted, Session, monkeypatch):
    _, _, _, sub_id = submitted("honest_full")
    with Session.begin() as s:
        s.get(Submission, uuid.UUID(sub_id)).submitted_at = utcnow() - timedelta(minutes=10)
    started = []
    monkeypatch.setattr(inline, "start", lambda svc, sid: started.append(sid))
    assert inline.tick(api.services, {"stale"}) == {"stale": 1}
    assert started == [uuid.UUID(sub_id)]


def test_tick_runs_the_outbox(api, pp):
    assert inline.tick(api.services, {"outbox"}) == {"outbox": 0}
