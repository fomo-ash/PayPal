import uuid
from datetime import timedelta

import pytest
from conftest import bench_files

from verdict.db.models import Claim, Submission, utcnow


@pytest.fixture
def claimed(api, user, open_job):
    def _make():
        buyer, job_id = open_job()
        w = user("worker", email="w@example.com", paypal_payer_id=f"P{uuid.uuid4().hex[:10]}")
        r = api.post(f"/jobs/{job_id}/claim", headers=w)
        assert r.status_code == 201, r.text
        return buyer, w, job_id
    return _make


def test_claim_rules(api, user, open_job):
    buyer, job_id = open_job()
    assert api.post(f"/jobs/{job_id}/claim", headers=buyer).status_code == 403
    assert api.post(f"/jobs/{job_id}/claim", headers=user("worker")).status_code == 409  # no PayPal
    w1 = user("worker", email="a@example.com")
    w2 = user("worker", email="b@example.com")
    assert api.post(f"/jobs/{job_id}/claim", headers=w1).status_code == 201
    assert api.post(f"/jobs/{job_id}/claim", headers=w2).status_code == 409
    assert api.get("/jobs").json() == []                       # no longer listed as open


def test_examples_run_shows_only_public_examples(api, claimed):
    _, w, job_id = claimed()
    r = api.post(f"/jobs/{job_id}/examples-run", json=bench_files("honest_full"), headers=w)
    body = r.json()
    assert r.status_code == 200 and body["passed"] == body["total"] > 0
    assert all(x["id"].startswith("example-") for x in body["results"])
    r = api.post(f"/jobs/{job_id}/examples-run", json=bench_files("cheat_memorizer"), headers=w)
    assert r.json()["passed"] < r.json()["total"]


def test_examples_run_needs_the_claim(api, user, claimed):
    _, _, job_id = claimed()
    other = user("worker", email="o@example.com")
    assert api.post(f"/jobs/{job_id}/examples-run", json=bench_files("honest_full"),
                    headers=other).status_code == 409


def test_submit_once_queues_grading(api, claimed, Session):
    buyer, w, job_id = claimed()
    r = api.post(f"/jobs/{job_id}/submit", json=bench_files("honest_full"), headers=w)
    assert r.status_code == 201, r.text
    sub_id = r.json()["submission_id"]
    assert api.services.queued == [uuid.UUID(sub_id)]
    assert api.post(f"/jobs/{job_id}/submit", json=bench_files("honest_full"),
                    headers=w).status_code == 409
    view = api.get(f"/submissions/{sub_id}", headers=buyer).json()
    assert view["job_state"] == "SUBMITTED" and view["verdict"] is None
    with Session() as s:
        assert s.get(Submission, uuid.UUID(sub_id)).sha256 == r.json()["sha256"]


def test_code_is_not_released_before_payment(api, claimed):
    buyer, w, job_id = claimed()
    sub_id = api.post(f"/jobs/{job_id}/submit", json=bench_files("honest_full"),
                      headers=w).json()["submission_id"]
    assert api.get(f"/submissions/{sub_id}/code", headers=buyer).status_code == 409
    assert api.get(f"/submissions/{sub_id}/code", headers=w).status_code == 403


@pytest.mark.parametrize("files, msg", [
    ({"files": {"../evil.py": "x"}}, "bad file path"),
    ({"files": {"/abs.py": "x"}}, "bad file path"),
    ({"files": {"other.py": "x"}}, "solution.py"),
    ({"files": {"solution.py": "x", "conftest.py": "x"}}, "rejected"),
    ({"files": {}}, "non-empty"),
])
def test_bad_uploads_refused(api, claimed, files, msg):
    _, w, job_id = claimed()
    r = api.post(f"/jobs/{job_id}/submit", json=files, headers=w)
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_submit_after_deadline_refused(api, claimed, Session):
    _, w, job_id = claimed()
    with Session.begin() as s:
        c = s.query(Claim).filter_by(job_id=uuid.UUID(job_id)).one()
        c.deadline_at = utcnow() - timedelta(seconds=1)
    r = api.post(f"/jobs/{job_id}/submit", json=bench_files("honest_full"), headers=w)
    assert r.status_code == 409 and "deadline" in r.json()["detail"]
