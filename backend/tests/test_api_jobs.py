import copy

import pytest

from verdict.db.models import AuditLog, Job
from verdict.db.repo import verify_audit_chain


def test_create_validate_and_views(api, user, draft_job):
    h, job_id = draft_job()
    mine = api.get(f"/jobs/{job_id}", headers=h).json()
    assert mine["state"] == "AWAITING_FUNDS" and mine["validated"] is True
    assert mine["amount"] == "100.00" and isinstance(mine["amount"], str)
    assert {g["name"]: g["weight"] for g in mine["groups"]} == {
        "core": "0.6000", "edge": "0.2500", "perf": "0.1500"}
    assert len(mine["examples"]) > 0
    assert "tests" not in mine and "expected" not in str(mine["groups"])

    worker = user("worker")
    assert api.get(f"/jobs/{job_id}", headers=worker).status_code == 404   # not funded yet
    assert api.get("/jobs").json() == []
    assert [j["id"] for j in api.get("/jobs/mine", headers=h).json()] == [job_id]


def test_hidden_tests_never_leave_the_server(api, draft_job, bench_upload):
    h, job_id = draft_job()
    body = api.get(f"/jobs/{job_id}", headers=h).text
    hidden_only = [t["expected"] for t in bench_upload["tests"]
                   if t["expected"] not in {e["expected"] for e in bench_upload["examples"]}]
    assert hidden_only and not any(x in body for x in hidden_only)


def test_wrong_reference_makes_job_invalid_then_editable(api, draft_job, bench_upload):
    h, job_id = draft_job(validate=False)
    bad = copy.deepcopy(bench_upload)
    bad["tests"][0]["expected"] = '{"entries": []}'
    assert api.put(f"/jobs/{job_id}/suite", json=bad, headers=h).status_code == 200
    r = api.post(f"/jobs/{job_id}/validate", headers=h).json()
    assert r["state"] == "INVALID"
    assert r["problems"] == ["core-1: reference output differs from expected"]
    assert api.put(f"/jobs/{job_id}/suite", json=bench_upload, headers=h).status_code == 409
    assert api.post(f"/jobs/{job_id}/edit", headers=h).json()["state"] == "DRAFT"
    assert api.put(f"/jobs/{job_id}/suite", json=bench_upload, headers=h).status_code == 200
    assert api.post(f"/jobs/{job_id}/validate", headers=h).json()["state"] == "AWAITING_FUNDS"


def test_broken_generator_is_caught_before_funding(api, draft_job, bench_upload):
    h, job_id = draft_job(validate=False)
    bad = copy.deepcopy(bench_upload)
    bad["generator"] = "def gen_input(rng):\n    return 7\n"
    api.put(f"/jobs/{job_id}/suite", json=bad, headers=h)
    r = api.post(f"/jobs/{job_id}/validate", headers=h).json()
    assert r["state"] == "INVALID" and r["problems"][0].startswith("generator:")


@pytest.mark.parametrize("body, status", [
    ({"amount": 100.0}, 422),            # float money refused
    ({"amount": "100.001"}, 422),
    ({"amount": "0.50"}, 422),
    ({"min_score": "1.5"}, 422),
    ({"currency": "EUR"}, 422),
    ({"deadline_hours": 500}, 422),
])
def test_job_input_validation(api, user, body, status):
    h = user("buyer")
    full = {"title": "Parse logs", "spec_md": "x", "amount": "100.00", **body}
    assert api.post("/jobs", json=full, headers=h).status_code == status


def test_only_buyers_post_and_only_owner_edits(api, user, draft_job, bench_upload):
    assert api.post("/jobs", json={"title": "abc", "spec_md": "x", "amount": "5.00"},
                    headers=user("worker")).status_code == 403
    h, job_id = draft_job(validate=False)
    other = user("buyer")
    assert api.put(f"/jobs/{job_id}/suite", json=bench_upload, headers=other).status_code == 404
    assert api.post(f"/jobs/{job_id}/validate", headers=other).status_code == 404


def test_bad_suite_is_422(api, draft_job, bench_upload):
    h, job_id = draft_job(validate=False)
    bad = copy.deepcopy(bench_upload)
    bad["groups"]["core"] = "0.70"
    r = api.put(f"/jobs/{job_id}/suite", json=bad, headers=h)
    assert r.status_code == 422 and "sum to exactly 1" in r.json()["detail"]


def test_cancel_and_audit_chain(api, draft_job, Session):
    h, job_id = draft_job()
    assert api.post(f"/jobs/{job_id}/cancel", headers=h).json()["state"] == "CANCELLED"
    assert api.post(f"/jobs/{job_id}/cancel", headers=h).status_code == 409
    with Session() as s:
        job = s.get(Job, __import__("uuid").UUID(job_id))
        events = [a.event for a in s.query(AuditLog).filter_by(job_id=job.id).order_by("seq")]
        assert events == ["created", "suite_uploaded", "DRAFT->VALIDATING",
                          "VALIDATING->AWAITING_FUNDS", "AWAITING_FUNDS->CANCELLED"]
        assert verify_audit_chain(s, job.id)
