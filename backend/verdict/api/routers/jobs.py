"""Jobs.

POST /jobs                       buyer creates a DRAFT (spec, amount, min score, deadline)
GET  /jobs                       open jobs (public view: spec, examples, weights, suite hash)
GET  /jobs/mine                  the buyer's own jobs, any state
GET  /jobs/{id}                  public view (drafts: owner only)
PUT  /jobs/{id}/suite            hidden tests + examples + reference (+ generator), DRAFT only
POST /jobs/{id}/validate         reference must pass every test → AWAITING_FUNDS, else INVALID
POST /jobs/{id}/edit             INVALID → DRAFT
POST /jobs/{id}/cancel           DRAFT | INVALID | AWAITING_FUNDS → CANCELLED (nothing is held)
"""

from __future__ import annotations

import json
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from verdict.api.deps import DB, CurrentUser, Svc
from verdict.core.scoring import CENT
from verdict.core.state_machine import JobState as S
from verdict.db.models import Job, Suite, TestGroup, User, utcnow
from verdict.db.repo import append_audit, move_job
from verdict.grading import oracle
from verdict.grading.compare import outputs_match
from verdict.grading.suite import SuiteUpload, parse_upload
from verdict.storage import BlobStore

router = APIRouter(prefix="/jobs", tags=["jobs"])

MIN_AMOUNT, MAX_AMOUNT = Decimal("1.00"), Decimal("10000.00")
GENERATOR_CHECK_N = 20          # generated inputs the reference must answer before funding


# ── request models ───────────────────────────────────────────────────────────
def _money(v: Any) -> Decimal:
    if not isinstance(v, str):
        raise ValueError('amount must be a string like "100.00" (never a float)')
    try:
        d = Decimal(v)
    except InvalidOperation as e:
        raise ValueError("bad amount") from e
    if not d.is_finite() or d != d.quantize(CENT) or not MIN_AMOUNT <= d <= MAX_AMOUNT:
        raise ValueError(f"amount must be {MIN_AMOUNT}..{MAX_AMOUNT} with 2 decimals")
    return d


class NewJob(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    spec_md: str = Field(min_length=1, max_length=50_000)
    amount: str
    currency: str = "USD"
    min_score: str = "0.50"
    deadline_hours: int = Field(default=24, ge=1)

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: str) -> str:
        return str(_money(v))

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        if v != "USD":
            raise ValueError("only USD for now")
        return v

    @field_validator("min_score")
    @classmethod
    def _min_score(cls, v: str) -> str:
        try:
            d = Decimal(v)
        except InvalidOperation as e:
            raise ValueError("bad min_score") from e
        if not d.is_finite() or not 0 <= d <= 1 or d != d.quantize(Decimal("0.0001")):
            raise ValueError("min_score must be 0..1 with at most 4 decimals")
        return str(d)


# ── helpers ──────────────────────────────────────────────────────────────────
def get_job(s: Session, job_id: uuid.UUID, *, for_update: bool = False) -> Job:
    q = select(Job).where(Job.id == job_id)
    job = s.scalar(q.with_for_update() if for_update else q)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


def owned_job(s: Session, job_id: uuid.UUID, user: User) -> Job:
    job = get_job(s, job_id)
    if job.buyer_id != user.id:
        raise HTTPException(404, "job not found")
    return job


def require_state(job: Job, *states: S) -> None:
    if job.state not in {st.value for st in states}:
        raise HTTPException(409, f"job is {job.state}; this needs {' or '.join(states)}")


def suite_keys(job_id: uuid.UUID, sha: str) -> dict[str, str]:
    base = f"suites/{job_id}/{sha}"
    return {"tests": f"{base}/tests.json", "reference": f"{base}/reference.py",
            "generator": f"{base}/generator.py"}


def load_suite(store: BlobStore, row: Suite) -> SuiteUpload:
    doc = json.loads(store.get(row.r2_key))
    gen = store.get(row.generator_key).decode() if row.generator_key else None
    return SuiteUpload(doc, store.get(row.reference_key).decode(), gen, row.sha256)


def public_view(s: Session, store: BlobStore, job: Job, *, owner: bool) -> dict[str, Any]:
    groups = s.scalars(select(TestGroup).where(TestGroup.job_id == job.id)
                       .order_by(TestGroup.name)).all()
    row = s.get(Suite, job.id)
    examples = json.loads(store.get(row.r2_key))["examples"] if row else []
    view: dict[str, Any] = {
        "id": str(job.id), "title": job.title, "spec_md": job.spec_md, "state": job.state,
        "amount": str(job.amount), "currency": job.currency, "min_score": str(job.min_score),
        "fee_bps": job.fee_bps, "deadline_hours": job.deadline_hours,
        "groups": [{"name": g.name, "weight": str(g.weight), "tests": g.n_tests,
                    "fresh_inputs": g.fresh_count} for g in groups],
        "examples": examples,
        "suite_sha256": job.suite_sha256,            # sealed at funding; None before
        "created_at": job.created_at.isoformat(),
    }
    if owner:
        view["uploaded_suite_sha256"] = row.sha256 if row else None
        view["validated"] = bool(row and row.validated_at)
        view["paypal_order_id"] = job.paypal_order_id
        view["honor_expires_at"] = (job.honor_expires_at.isoformat()
                                    if job.honor_expires_at else None)
    return view


# ── endpoints ────────────────────────────────────────────────────────────────
@router.post("", status_code=201)
def create_job(body: NewJob, user: CurrentUser, s: DB, svc: Svc) -> dict:
    if user.role != "buyer":
        raise HTTPException(403, "only buyers can post jobs")
    if body.deadline_hours > svc.settings.max_job_deadline_hours:
        raise HTTPException(422, f"deadline_hours max is {svc.settings.max_job_deadline_hours}")
    job = Job(buyer_id=user.id, title=body.title, spec_md=body.spec_md,
              amount=Decimal(body.amount), currency=body.currency,
              min_score=Decimal(body.min_score), fee_bps=svc.settings.platform_fee_bps,
              deadline_hours=body.deadline_hours, state=S.DRAFT.value)
    s.add(job)
    s.flush()
    append_audit(s, job.id, "created", {"amount": job.amount, "buyer": user.id})
    s.commit()
    return public_view(s, svc.store, job, owner=True)


@router.get("")
def list_open(s: DB, svc: Svc, limit: int = 50) -> list[dict]:
    jobs = s.scalars(select(Job).where(Job.state == S.OPEN.value)
                     .order_by(Job.created_at.desc()).limit(min(max(limit, 1), 200))).all()
    return [public_view(s, svc.store, j, owner=False) for j in jobs]


@router.get("/mine")
def list_mine(user: CurrentUser, s: DB, svc: Svc) -> list[dict]:
    jobs = s.scalars(select(Job).where(Job.buyer_id == user.id)
                     .order_by(Job.created_at.desc()).limit(200)).all()
    return [public_view(s, svc.store, j, owner=True) for j in jobs]


@router.get("/{job_id}")
def get_one(job_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc) -> dict:
    job = get_job(s, job_id)
    owner = job.buyer_id == user.id
    if not owner and job.state in {S.DRAFT, S.VALIDATING, S.INVALID, S.AWAITING_FUNDS,
                                   S.CANCELLED}:
        raise HTTPException(404, "job not found")
    return public_view(s, svc.store, job, owner=owner)


@router.put("/{job_id}/suite")
def upload_suite(job_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc,
                 raw: Annotated[dict[str, Any], Body()]) -> dict:
    job = owned_job(s, job_id, user)
    require_state(job, S.DRAFT)
    up = parse_upload(raw)                         # SuiteError → 422
    keys = suite_keys(job.id, up.sha256)
    svc.store.put(keys["tests"], json.dumps(up.doc, ensure_ascii=False).encode())
    svc.store.put(keys["reference"], up.reference.encode())
    if up.generator:
        svc.store.put(keys["generator"], up.generator.encode())

    get_job(s, job_id, for_update=True)            # serialize concurrent uploads
    row = s.get(Suite, job.id) or Suite(job_id=job.id)
    row.r2_key, row.reference_key, row.sha256 = keys["tests"], keys["reference"], up.sha256
    row.generator_key = keys["generator"] if up.generator else None
    row.validated_at = None                        # a new upload must be validated again
    s.add(row)
    s.execute(delete(TestGroup).where(TestGroup.job_id == job.id))
    counts: dict[str, int] = {}
    for t in up.doc["tests"]:
        counts[t["group"]] = counts.get(t["group"], 0) + 1
    for g, w in up.doc["groups"].items():
        s.add(TestGroup(job_id=job.id, name=g, weight=Decimal(w), n_tests=counts[g],
                        fresh_count=up.doc["fresh"].get(g, 0)))
    append_audit(s, job.id, "suite_uploaded", {"sha256": up.sha256, "tests": len(up.doc["tests"])})
    s.commit()
    return {"sha256": up.sha256, "tests": len(up.doc["tests"]), "groups": counts}


@router.post("/{job_id}/validate")
def validate(job_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc) -> dict:
    """Runs the buyer's reference (in the sandbox) on every hidden test and the examples, and
    checks the generator. Runs while the job is still DRAFT; the result is applied with a
    compare-and-set, so two concurrent calls cannot both change the job."""
    job = owned_job(s, job_id, user)
    require_state(job, S.DRAFT)
    row = s.get(Suite, job.id)
    if row is None:
        raise HTTPException(409, "upload a suite first")
    up = load_suite(svc.store, row)
    sha = row.sha256
    s.rollback()                                   # no transaction held during sandbox runs

    problems = check_suite(svc, up)

    job = get_job(s, job_id, for_update=True)
    row = s.get(Suite, job.id)
    if row is None or row.sha256 != sha:
        raise HTTPException(409, "suite changed during validation; validate again")
    move_job(s, job.id, S.DRAFT, S.VALIDATING, reason="validate", data={"sha256": sha})
    if problems:
        move_job(s, job.id, S.VALIDATING, S.INVALID, reason="reference failed",
                 data={"problems": problems[:20]})
    else:
        row.validated_at = utcnow()
        move_job(s, job.id, S.VALIDATING, S.AWAITING_FUNDS, reason="validated")
    s.commit()
    return {"state": S.INVALID.value if problems else S.AWAITING_FUNDS.value,
            "problems": problems[:20]}


def check_suite(svc: Any, up: SuiteUpload) -> list[str]:
    timeout = svc.settings.sandbox_test_timeout_ms / 1000
    problems: list[str] = []
    cases = [(t["id"], t["input"]) for t in up.doc["tests"]]
    cases += [(f"example-{i}", e["input"]) for i, e in enumerate(up.doc["examples"])]
    expected = {t["id"]: t["expected"] for t in up.doc["tests"]}
    expected |= {f"example-{i}": e["expected"] for i, e in enumerate(up.doc["examples"])}
    got = oracle.run_reference(svc.runner, up.reference, cases, timeout)
    for tid, _ in cases:
        out = got.get(tid)
        if out is None:
            problems.append(f"{tid}: reference raised an error or timed out")
        elif not outputs_match(expected[tid], out):
            problems.append(f"{tid}: reference output differs from expected")
    if up.generator and any(up.doc["fresh"].values()):
        counts = {g: min(n, GENERATOR_CHECK_N) for g, n in up.doc["fresh"].items() if n}
        try:
            gen = oracle.generate_inputs(svc.runner, up.generator, secrets.randbits(64), counts)
        except oracle.OracleError as e:
            return [*problems, f"generator: {e}"]
        flat = [c for cs in gen.values() for c in cs]
        ref = oracle.run_reference(svc.runner, up.reference, flat, timeout)
        bad = [fid for fid, _ in flat if ref.get(fid) is None]
        if bad:
            problems.append(f"reference failed on {len(bad)}/{len(flat)} generated inputs")
    return problems


@router.post("/{job_id}/edit")
def edit(job_id: uuid.UUID, user: CurrentUser, s: DB) -> dict:
    job = owned_job(s, job_id, user)
    move_job(s, job.id, job.state, S.DRAFT, reason="buyer edits")   # only INVALID → DRAFT
    s.commit()
    return {"state": S.DRAFT.value}


@router.post("/{job_id}/cancel")
def cancel(job_id: uuid.UUID, user: CurrentUser, s: DB) -> dict:
    job = owned_job(s, job_id, user)
    require_state(job, S.DRAFT, S.INVALID, S.AWAITING_FUNDS)
    move_job(s, job.id, job.state, S.CANCELLED, reason="buyer cancelled")
    s.commit()
    return {"state": S.CANCELLED.value}


# ── funding (PayPal Orders v2, intent AUTHORIZE) ─────────────────────────────
REUSABLE_ORDER = {"CREATED", "PAYER_ACTION_REQUIRED", "APPROVED", "SAVED"}


def _paypal(svc: Any) -> Any:
    if svc.paypal is None:
        raise HTTPException(503, "PayPal is not configured on this server")
    return svc.paypal


@router.post("/{job_id}/fund")
def fund(job_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc) -> dict:
    """Create (or reuse) the PayPal order. The web page passes order_id to the PayPal JS SDK;
    approve_url is for scripts and agents."""
    job = owned_job(s, job_id, user)
    require_state(job, S.AWAITING_FUNDS)
    paypal = _paypal(svc)
    if job.paypal_order_id:
        order = paypal.get_order(job.paypal_order_id)
        if order.get("status") in REUSABLE_ORDER:
            return _order_view(paypal, order)
    order = paypal.create_authorize_order(
        amount=str(job.amount), currency=job.currency, reference_id=str(job.id),
        description=f"Verdict job: {job.title}", return_url=svc.settings.paypal_return_url,
        cancel_url=svc.settings.paypal_cancel_url,
        # a fresh key per new order: an old, expired order must not be returned again
        idempotency_key=f"verdict-{job.id}-order-{secrets.token_hex(6)}")
    job = get_job(s, job_id, for_update=True)
    require_state(job, S.AWAITING_FUNDS)
    job.paypal_order_id = order["id"]
    append_audit(s, job.id, "order_created", {"order_id": order["id"]})
    s.commit()
    return _order_view(paypal, order)


def _order_view(paypal: Any, order: dict) -> dict:
    try:
        url = paypal.approve_link(order)
    except KeyError:
        url = None
    return {"order_id": order["id"], "status": order.get("status"), "approve_url": url}


@router.post("/{job_id}/fund/confirm")
def confirm_funding(job_id: uuid.UUID, user: CurrentUser, s: DB, svc: Svc) -> dict:
    """After the buyer approved: authorize the order (the hold), check it, seal the suite, open
    the job. Safe to call twice: the authorize call reuses one idempotency key."""
    from verdict.paypal.client import PayPalError
    from verdict.worker.money import record_authorization

    job = owned_job(s, job_id, user)
    if job.state in {S.FUNDED.value, S.OPEN.value}:
        return {"state": job.state, "suite_sha256": job.suite_sha256}
    require_state(job, S.AWAITING_FUNDS)
    if not job.paypal_order_id:
        raise HTTPException(409, "call /fund first")
    row = s.get(Suite, job.id)
    if row is None or row.validated_at is None:
        raise HTTPException(409, "suite is not validated")
    paypal, order_id = _paypal(svc), job.paypal_order_id
    s.rollback()

    try:
        order = paypal.authorize_order(order_id, idempotency_key=f"verdict-{job_id}-authorize")
    except PayPalError as e:
        issue = _issue(e)
        if issue == "ORDER_NOT_APPROVED":
            raise HTTPException(409, "the buyer has not approved the order in PayPal yet") from e
        if issue != "ORDER_ALREADY_AUTHORIZED":
            raise HTTPException(502, f"PayPal refused the authorization ({issue})") from e
        order = paypal.get_order(order_id)
    auth = _authorization(order, job_id)

    job = get_job(s, job_id, for_update=True)
    if job.state != S.AWAITING_FUNDS.value or job.paypal_order_id != order_id:
        return {"state": job.state, "suite_sha256": job.suite_sha256}
    row = s.get(Suite, job.id)
    assert row is not None
    record_authorization(s, job.id, order_id=order_id, authorization_id=auth["id"],
                         amount=auth["amount"]["value"])
    move_job(s, job.id, S.FUNDED, S.OPEN, reason="suite sealed",
             data={"suite_sha256": row.sha256}, fields={"suite_sha256": row.sha256})
    s.commit()
    return {"state": S.OPEN.value, "suite_sha256": row.sha256,
            "authorization_id": auth["id"], "honor_expires_at": job.honor_expires_at}


def _issue(e: Any) -> str:
    body = e.body if isinstance(e.body, dict) else {}
    details = body.get("details") or [{}]
    return str(details[0].get("issue") or body.get("name") or e.status)


def _authorization(order: dict, job_id: uuid.UUID) -> dict:
    """Check the authorization really is for this job, in USD, and live."""
    try:
        unit = order["purchase_units"][0]
        auth = unit["payments"]["authorizations"][0]
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(502, "PayPal returned no authorization") from e
    if unit.get("reference_id") not in (None, str(job_id)):
        raise HTTPException(409, "this PayPal order belongs to another job")
    if auth.get("status") != "CREATED":   # PENDING = PayPal is still reviewing: not guaranteed
        raise HTTPException(409, f"authorization status is {auth.get('status')}, try later")
    if auth.get("amount", {}).get("currency_code") != "USD":
        raise HTTPException(409, "authorization currency mismatch")
    return auth
