import uuid

from verdict.config import Settings


def test_health(api):
    assert api.get("/health").json() == {"ok": True}


def test_dev_user_and_auth_header(api, user):
    h = user("buyer", email="b@example.com")
    assert api.get("/me", headers=h).status_code == 200
    assert api.get("/me").status_code == 401
    assert api.get("/me", headers={"X-User-Id": "nope"}).status_code == 401
    assert api.get("/me", headers={"X-User-Id": str(uuid.uuid4())}).status_code == 401


def test_dev_auth_refused_with_live_paypal(api, user):
    h = user("buyer")
    api.services.settings = Settings(_env_file=None, dev_auth=True, paypal_env="live")
    assert api.get("/me", headers=h).status_code == 401


def test_cors_allows_the_web_app_only(api):
    ok = api.options("/jobs", headers={"Origin": "http://localhost:5180",
                                       "Access-Control-Request-Method": "POST",
                                       "Access-Control-Request-Headers": "authorization"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5180"
    bad = api.options("/jobs", headers={"Origin": "https://evil.example",
                                        "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
