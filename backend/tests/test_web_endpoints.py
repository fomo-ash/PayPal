"""Endpoints the web app needs: demo login, public config, my work, a job's submission."""

import pytest


@pytest.fixture
def demo_api(api):
    cfg = api.services.settings
    cfg.demo_login = True
    cfg.session_secret = "x" * 32
    cfg.sandbox_worker_email = "worker-sandbox@example.com"
    return api


def login(api, role):
    r = api.post("/auth/demo", json={"role": role})
    assert r.status_code == 200, r.text
    return r.json()


def test_demo_login_is_off_by_default(api):
    assert api.post("/auth/demo", json={"role": "buyer"}).status_code == 404


def test_demo_login_issues_a_session_per_visitor(demo_api):
    a, b = login(demo_api, "buyer"), login(demo_api, "buyer")
    assert a["user"]["id"] != b["user"]["id"]
    me = demo_api.get("/me", headers={"Authorization": f"Bearer {a['token']}"}).json()
    assert me["role"] == "buyer" and me["id"] == a["user"]["id"]


def test_demo_worker_is_paid_at_the_sandbox_account(demo_api):
    assert login(demo_api, "worker")["user"]["email"] == "worker-sandbox@example.com"


def test_demo_login_never_on_live(demo_api):
    demo_api.services.settings.paypal_env = "live"
    assert demo_api.post("/auth/demo", json={"role": "admin"}).status_code == 404


def test_demo_login_is_rate_limited(demo_api):
    demo_api.services.settings.demo_logins_per_hour = 2
    login(demo_api, "buyer")
    login(demo_api, "worker")
    assert demo_api.post("/auth/demo", json={"role": "buyer"}).status_code == 429


def test_public_config_has_no_secrets(api):
    body = api.get("/public-config").json()
    assert set(body) == {"paypal_client_id", "paypal_env", "demo_login", "paypal_login"}
    assert "secret" not in str(body).lower()


def test_my_work_and_job_submission(api, user, submitted):
    buyer, worker, job_id, sub_id = submitted("honest_full")
    work = api.get("/submissions/mine", headers=worker).json()
    assert [w["job_id"] for w in work] == [job_id] and work[0]["submission_id"] == sub_id
    for who in (buyer, worker):
        r = api.get(f"/jobs/{job_id}/submission", headers=who)
        assert r.status_code == 200 and r.json()["id"] == sub_id
    stranger = user("worker", email="s@example.com")
    assert api.get(f"/jobs/{job_id}/submission", headers=stranger).status_code == 404
    assert api.get("/submissions/mine", headers=stranger).json() == []
