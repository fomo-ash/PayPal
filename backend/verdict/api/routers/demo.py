"""Demo login for the hosted sandbox, so a visitor can try every role without our PayPal
accounts. Mounted only when DEMO_LOGIN=true, and refused when PAYPAL_ENV=live.

POST /auth/demo {"role": "buyer" | "worker" | "admin"} → {"token", "expires_at", "user"}

Every call makes a fresh user, so visitors never share one. The demo worker is paid at the
sandbox worker account (SANDBOX_WORKER_EMAIL). A demo admin can only lower a capture or void
it, never raise one, and cannot review a job it is part of.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from verdict.api import sessions
from verdict.api.deps import DB, Svc
from verdict.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

NAMES = {"buyer": "Demo buyer", "worker": "Demo worker", "admin": "Demo reviewer"}


class DemoLogin(BaseModel):
    role: Literal["buyer", "worker", "admin"]


@router.post("/demo")
def demo_login(body: DemoLogin, request: Request, s: DB, svc: Svc) -> dict:
    cfg = svc.settings
    if not cfg.demo_login or cfg.paypal_env == "live" or not cfg.session_secret:
        raise HTTPException(404, "demo login is off")
    # Render's proxy puts the visitor first in X-Forwarded-For; a forged value only gets that
    # caller its own bucket, and the overall cap below still holds.
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip = fwd or (request.client.host if request.client else "?")
    svc.limiter.hit("demo-login", ip, cfg.demo_logins_per_hour)
    svc.limiter.hit("demo-login", "*", cfg.demo_logins_per_hour * 10)
    tag = secrets.token_hex(3)
    email = (cfg.sandbox_worker_email if body.role == "worker" else None) or \
        f"demo-{body.role}-{tag}@example.com"
    user = User(role=body.role, email=email, display_name=f"{NAMES[body.role]} {tag}")
    s.add(user)
    s.commit()
    token = sessions.issue(cfg.session_secret, "session", {"u": str(user.id)},
                           sessions.SESSION_TTL)
    expires = datetime.fromtimestamp(sessions.read(cfg.session_secret, "session", token)["e"],
                                     UTC)
    return {"token": token, "expires_at": expires.isoformat(),
            "user": {"id": str(user.id), "role": user.role, "email": user.email,
                     "display_name": user.display_name, "has_paypal": False}}
