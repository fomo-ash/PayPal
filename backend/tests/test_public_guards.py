"""Guards for a public deployment: dev login behind a token, and per-user rate limits."""

import pytest
from fastapi import HTTPException

from verdict.api.deps import RateLimiter


@pytest.fixture
def token_api(api):
    api.services.settings.dev_auth_token = "s3cret"  # noqa: S105 - test value
    return api


def test_dev_users_need_the_token_when_set(token_api):
    assert token_api.post("/dev/users", json={"role": "admin"}).status_code == 401
    bad = token_api.post("/dev/users", json={"role": "admin"}, headers={"X-Dev-Token": "nope"})
    assert bad.status_code == 401
    ok = token_api.post("/dev/users", json={"role": "buyer"}, headers={"X-Dev-Token": "s3cret"})
    assert ok.status_code == 201


def test_x_user_id_needs_the_token_when_set(token_api):
    uid = token_api.post("/dev/users", json={"role": "buyer"},
                         headers={"X-Dev-Token": "s3cret"}).json()["id"]
    assert token_api.get("/jobs/mine", headers={"X-User-Id": uid}).status_code == 401
    ok = token_api.get("/jobs/mine", headers={"X-User-Id": uid, "X-Dev-Token": "s3cret"})
    assert ok.status_code == 200


def test_no_token_configured_keeps_local_dev_open(api, user):
    assert api.get("/jobs/mine", headers=user("buyer")).status_code == 200


def test_rate_limiter_window():
    now = [0.0]
    lim = RateLimiter(clock=lambda: now[0])
    for _ in range(3):
        lim.hit("validate", "u1", 3, 60)
    with pytest.raises(HTTPException) as e:
        lim.hit("validate", "u1", 3, 60)
    assert e.value.status_code == 429 and e.value.headers["Retry-After"] == "61"
    lim.hit("validate", "u2", 3, 60)          # other users are not affected
    now[0] = 61.0
    lim.hit("validate", "u1", 3, 60)          # window slid


def test_validate_is_rate_limited(api, draft_job):
    h, jid = draft_job(validate=False)
    api.services.settings.validate_per_hour = 1
    first = api.post(f"/jobs/{jid}/validate", headers=h)
    assert first.status_code == 200, first.text
    again = api.post(f"/jobs/{jid}/validate", headers=h)
    assert again.status_code == 429
