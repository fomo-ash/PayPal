"""Shared fixtures.

Database tests run on in-memory SQLite by default (no services needed, so CI stays simple).
Set TEST_DATABASE_URL to a throwaway Postgres to run the same tests there, e.g.
    TEST_DATABASE_URL=postgresql+psycopg://verdict:verdict@localhost:5432/verdict_test pytest
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from verdict.db.models import Base, Job, User
from verdict.db.session import make_engine, make_session_factory

TEST_DB = os.getenv("TEST_DATABASE_URL", "")


@pytest.fixture
def engine():
    if TEST_DB:
        eng = make_engine(TEST_DB)
        Base.metadata.drop_all(eng)
    else:
        eng = make_engine("sqlite://", connect_args={"check_same_thread": False},
                          poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def Session(engine):  # noqa: N802 - it is a factory, named like a class on purpose
    return make_session_factory(engine)


@pytest.fixture
def make_job(Session):
    """Create a buyer + job in the given state and return the job id."""
    def _make(state: str = "DRAFT", amount: str = "100.00", **kw):
        with Session.begin() as s:
            buyer = User(email="buyer@example.com", role="buyer")
            s.add(buyer)
            s.flush()
            job = Job(buyer_id=buyer.id, title="log parser", amount=Decimal(amount),
                      min_score=Decimal("0.50"), fee_bps=500, state=state, **kw)
            s.add(job)
            s.flush()
            return job.id
    return _make


BENCH = Path(__file__).resolve().parents[2] / "bench" / "tasks" / "log_parser"


@pytest.fixture
def bench_upload():
    """The log_parser bench task as a buyer's suite upload document."""
    import json

    hidden = json.loads((BENCH / "hidden_tests.json").read_text())
    return {"groups": hidden["groups"], "fresh": hidden["fresh"], "tests": hidden["tests"],
            "examples": json.loads((BENCH / "examples.json").read_text()),
            "reference": (BENCH / "reference.py").read_text(),
            "generator": (BENCH / "gen_input.py").read_text()}


PAYPAL_BASE = "https://api-m.sandbox.paypal.com"


@pytest.fixture
def pp():
    """A real PayPalClient whose HTTP calls go to a respx mock (pp.mock)."""
    import respx

    from verdict.paypal.client import PayPalClient

    with respx.mock(base_url=PAYPAL_BASE, assert_all_called=False) as mock:
        mock.post("/v1/oauth2/token").respond(json={"access_token": "t", "expires_in": 3600})
        client = PayPalClient(PAYPAL_BASE, "id", "secret")
        client.mock = mock
        yield client
        client.close()


@pytest.fixture
def services(Session, pp, tmp_path):
    from verdict.api.deps import Services
    from verdict.config import Settings
    from verdict.sandbox.runner import LocalRunner
    from verdict.storage import LocalBlobStore

    queued = []
    svc = Services(settings=Settings(_env_file=None, dev_auth=True, sandbox_backend="local",
                                     paypal_webhook_id="WH-1"),
                   Session=Session, store=LocalBlobStore(tmp_path / "blobs"), paypal=pp,
                   runner=LocalRunner(), enqueue_grading=queued.append)
    svc.queued = queued                      # submission ids the API asked to grade
    return svc


@pytest.fixture
def api(services):
    from fastapi.testclient import TestClient

    from verdict.api.main import create_app

    with TestClient(create_app(services)) as client:
        client.services = services
        yield client


@pytest.fixture
def user(api):
    """user("buyer") → headers for a new dev user with that role."""
    def _make(role: str, **kw):
        r = api.post("/dev/users", json={"role": role, **kw})
        assert r.status_code == 201, r.text
        return {"X-User-Id": r.json()["id"]}
    return _make


@pytest.fixture
def draft_job(api, user, bench_upload):
    """draft_job(validate=True) → (buyer headers, job id) with the bench suite uploaded."""
    def _make(validate: bool = True, **kw):
        h = user("buyer", email="buyer@example.com")
        body = {"title": "Parse logs", "spec_md": "see spec", "amount": "100.00", **kw}
        r = api.post("/jobs", json=body, headers=h)
        assert r.status_code == 201, r.text
        job_id = r.json()["id"]
        assert api.put(f"/jobs/{job_id}/suite", json=bench_upload, headers=h).status_code == 200
        if validate:
            r = api.post(f"/jobs/{job_id}/validate", headers=h)
            assert r.json()["state"] == "AWAITING_FUNDS", r.text
        return h, job_id
    return _make


def mock_order(pp, job_id, *, amount="100.00", status="CREATED", order_id="ORDER-1",
               auth_id="AUTH-1"):
    """Mock create order + authorize for one job; returns the authorize route."""
    pp.mock.post("/v2/checkout/orders").respond(201, json={
        "id": order_id, "status": "PAYER_ACTION_REQUIRED",
        "links": [{"rel": "payer-action", "href": f"https://sandbox.paypal.test/{order_id}"}]})
    return pp.mock.post(f"/v2/checkout/orders/{order_id}/authorize").respond(201, json={
        "id": order_id, "status": "COMPLETED",
        "purchase_units": [{"reference_id": str(job_id), "payments": {"authorizations": [{
            "id": auth_id, "status": status,
            "amount": {"currency_code": "USD", "value": amount}}]}}]})


@pytest.fixture
def open_job(api, draft_job, pp):
    """open_job() → (buyer headers, job id) for a funded, OPEN job (PayPal mocked)."""
    def _make(**kw):
        h, job_id = draft_job(**kw)
        mock_order(pp, job_id)
        assert api.post(f"/jobs/{job_id}/fund", headers=h).status_code == 200
        r = api.post(f"/jobs/{job_id}/fund/confirm", headers=h)
        assert r.json()["state"] == "OPEN", r.text
        return h, job_id
    return _make


def bench_files(name: str) -> dict:
    """A bench submission as an API upload body."""
    root = BENCH / "submissions" / name
    return {"files": {p.relative_to(root).as_posix(): p.read_text()
                      for p in sorted(root.rglob("*")) if p.is_file()
                      and "__pycache__" not in p.parts}}


@pytest.fixture
def submitted(api, user, open_job):
    """submitted("honest_full") → (buyer, worker, job id, submission id) through the API."""
    def _make(name: str, **kw):
        import uuid as _uuid

        buyer, job_id = open_job(**kw)
        w = user("worker", email=f"{name}@example.com",
                 paypal_payer_id=f"P{_uuid.uuid4().hex[:10].upper()}")
        assert api.post(f"/jobs/{job_id}/claim", headers=w).status_code == 201
        r = api.post(f"/jobs/{job_id}/submit", json=bench_files(name), headers=w)
        assert r.status_code == 201, r.text
        return buyer, w, job_id, r.json()["submission_id"]
    return _make


class FakeLLM:
    """Stands in for judge.llm.LLMClient. `reply(prompt, schema)` returns the JSON object the
    model would send, or raises (e.g. LLMUnavailable). Every prompt is kept in .prompts."""

    def __init__(self, reply):
        self.reply = reply
        self.prompts: list[str] = []

    def chat_json(self, system, user, schema, **kw):
        from verdict.judge.llm import LLMResult

        self.prompts.append(user)
        data = self.reply(user, schema)
        return LLMResult(schema.model_validate(data), "fake", "fake-model", "")


def spec_reply(unfair=()):
    """FakeLLM reply for the spec check: every test in the prompt is implied unless listed."""
    import re

    def reply(prompt, schema):
        tests = prompt.rsplit("<tests>", 1)[1]
        ids = re.findall(r'"id": "([^"]+)"', tests)
        return {"items": [{"test_id": i, "implied_by_spec": i not in unfair,
                           "reason": "not in the spec" if i in unfair else "follows from spec"}
                          for i in ids]}
    return reply
