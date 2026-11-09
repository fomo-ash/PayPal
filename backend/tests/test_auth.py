"""Log in with PayPal: state checked, payer_id becomes the identity, sessions are signed."""

import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from verdict.api import sessions

INFO = {"user_id": "https://www.paypal.com/webapps/auth/identity/user/abc", "name": "Riya W",
        "payer_id": "PAYER7XQ2", "verified_account": "true",
        "emails": [{"value": "riya@example.com", "primary": True, "confirmed": True}]}


@pytest.fixture
def login(api, pp):
    """login(role, info) → the callback response, with PayPal's identity calls mocked."""
    api.services.settings.session_secret = "test-secret-" + "x" * 32
    seen = {}

    def token(request):
        body = parse_qs(request.content.decode())
        seen.setdefault("grants", []).append(body["grant_type"][0])
        if body["grant_type"] == ["authorization_code"]:
            assert body["code"] == ["CODE-1"]
            return httpx.Response(200, json={"access_token": "USER-TOKEN"})
        return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})

    pp.mock.post("/v1/oauth2/token").mock(side_effect=token)

    def _login(role="worker", info=INFO):
        pp.mock.get("/v1/identity/oauth2/userinfo").respond(json=info)
        url = api.get(f"/auth/paypal/login?role={role}").json()["url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        return api.post("/auth/paypal/callback", json={"code": "CODE-1", "state": state})
    _login.seen = seen
    return _login


def test_login_url_points_at_paypal_with_the_right_scope(api):
    api.services.settings.session_secret = "s" * 40
    url = urlparse(api.get("/auth/paypal/login?role=buyer").json()["url"])
    q = parse_qs(url.query)
    assert url.netloc == "www.sandbox.paypal.com" and url.path == "/connect"
    assert q["response_type"] == ["code"] and "openid" in q["scope"][0]
    assert q["redirect_uri"] == ["http://localhost:3000/auth/callback"]


def test_login_creates_a_worker_tied_to_the_payer_id(api, login):
    r = login("worker")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["role"] == "worker" and body["user"]["email"] == "riya@example.com"
    assert login.seen["grants"].count("authorization_code") == 1
    me = api.get("/me", headers={"Authorization": f"Bearer {body['token']}"}).json()
    assert me["id"] == body["user"]["id"] and me["has_paypal"] is True


def test_returning_user_keeps_their_account_and_role(api, login):
    first = login("worker").json()["user"]
    again = login("buyer").json()["user"]
    assert again["id"] == first["id"] and again["role"] == "worker"


def test_worker_logged_in_with_paypal_can_claim(api, login, open_job):
    _, job_id = open_job()
    token = login("worker").json()["token"]
    r = api.post(f"/jobs/{job_id}/claim", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text


def test_forged_or_expired_state_is_refused(api, login):
    secret = api.services.settings.session_secret
    for state in ["nonsense", sessions.issue("other-secret", "state", {"role": "buyer"}, 600),
                  sessions.issue(secret, "state", {"role": "buyer"}, 600, now=time.time() - 3600),
                  sessions.issue(secret, "session", {"u": "x"}, 600)]:
        r = api.post("/auth/paypal/callback", json={"code": "CODE-1", "state": state})
        assert r.status_code == 400


def test_bad_tokens_are_refused(api, login):
    token = login().json()["token"]
    raw, sig = token.split(".")
    for bad in [f"{raw}.{sig[:-2]}AA", "Bearer-less", token + "x"]:
        assert api.get("/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    assert api.get("/me", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_missing_payer_id_is_refused(api, login):
    r = login(info={**INFO, "payer_id": None})
    assert r.status_code == 401 and "payer ID" in r.text


def test_admin_role_cannot_be_requested(api):
    api.services.settings.session_secret = "s" * 40
    assert api.get("/auth/paypal/login?role=admin").status_code == 422


def test_not_configured(api):
    api.services.settings.session_secret = ""
    assert api.get("/auth/paypal/login").status_code == 503


def test_dev_header_refused_in_live(api, user):
    h = user("buyer")
    api.services.settings.paypal_env = "live"
    try:
        assert api.get("/me", headers=h).status_code == 401
    finally:
        api.services.settings.paypal_env = "sandbox"
