"""Agent API keys: an agent acts as its PayPal-identified owner and is recorded on the claim."""

import uuid

from conftest import bench_files

from verdict.db.models import Agent, Claim


def worker_with_paypal(user):
    return user("worker", email="owner@example.com", paypal_payer_id="OWNERPAYER1")


def test_key_is_shown_once_and_stored_hashed(api, user, Session):
    owner = worker_with_paypal(user)
    r = api.post("/agents", json={"name": "solver-1"}, headers=owner)
    assert r.status_code == 201
    key = r.json()["api_key"]
    assert key.startswith("vk_") and len(key) > 40
    with Session() as s:
        stored = s.query(Agent).one()
        assert stored.api_key_hash != key and len(stored.api_key_hash) == 64
    listed = api.get("/agents", headers=owner).json()
    assert listed[0]["name"] == "solver-1" and "api_key" not in listed[0]


def test_agent_acts_as_owner_and_claim_records_it(api, user, open_job, Session):
    owner = worker_with_paypal(user)
    key = api.post("/agents", json={"name": "solver-1"}, headers=owner).json()["api_key"]
    agent = {"Authorization": f"Bearer {key}"}
    me = api.get("/me", headers=agent).json()
    assert me["id"] == owner["X-User-Id"] and me["has_paypal"] is True
    _, job_id = open_job()
    assert api.post(f"/jobs/{job_id}/claim", headers=agent).status_code == 201
    r = api.post(f"/jobs/{job_id}/submit", json=bench_files("honest_full"), headers=agent)
    assert r.status_code == 201
    with Session() as s:
        claim = s.query(Claim).filter_by(job_id=uuid.UUID(job_id)).one()
        assert claim.agent_id is not None
        assert str(claim.worker_id) == owner["X-User-Id"]


def test_owner_and_agent_share_one_submission(api, user, open_job):
    owner = worker_with_paypal(user)
    key = api.post("/agents", json={"name": "a"}, headers=owner).json()["api_key"]
    _, job_id = open_job()
    api.post(f"/jobs/{job_id}/claim", headers=owner)
    api.post(f"/jobs/{job_id}/submit", json=bench_files("honest_full"), headers=owner)
    again = api.post(f"/jobs/{job_id}/claim", headers={"Authorization": f"Bearer {key}"})
    assert again.status_code == 409


def test_rules_for_creating_agents(api, user):
    assert api.post("/agents", json={"name": "x"}, headers=user("buyer")).status_code == 403
    no_paypal = user("worker", email="np@example.com")
    assert api.post("/agents", json={"name": "x"}, headers=no_paypal).status_code == 409
    owner = worker_with_paypal(user)
    for i in range(5):
        assert api.post("/agents", json={"name": f"a{i}"}, headers=owner).status_code == 201
    assert api.post("/agents", json={"name": "a6"}, headers=owner).status_code == 409


def test_unknown_key_is_refused(api):
    r = api.get("/me", headers={"Authorization": "Bearer vk_" + "x" * 43})
    assert r.status_code == 401
