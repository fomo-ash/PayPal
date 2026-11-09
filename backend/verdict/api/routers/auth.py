"""Log in with PayPal.

GET  /auth/paypal/login?role=worker   → {"url"}: send the browser there
POST /auth/paypal/callback            {"code", "state"} from PayPal's redirect → {"token", "user"}

The token goes in `Authorization: Bearer <token>` on every later request. New users get the
role they chose at login (buyer or worker); returning users keep theirs. Admin is never
granted here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from verdict.api import sessions
from verdict.api.deps import DB, Svc
from verdict.db.models import User
from verdict.paypal import identity
from verdict.paypal.client import PayPalError

router = APIRouter(prefix="/auth/paypal", tags=["auth"])


def _ready(svc: Any) -> None:
    if not svc.settings.session_secret or svc.paypal is None:
        raise HTTPException(503, "Log in with PayPal is not configured "
                                 "(SESSION_SECRET, PayPal keys)")


@router.get("/login")
def login(svc: Svc, role: Literal["buyer", "worker"] = "buyer") -> dict:
    _ready(svc)
    cfg = svc.settings
    state = sessions.issue(cfg.session_secret, "state", {"role": role}, sessions.STATE_TTL)
    return {"url": identity.authorize_url(cfg.paypal_web_url, cfg.paypal_client_id,
                                          cfg.paypal_login_redirect_uri, state)}


class Callback(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=2048)


@router.post("/callback")
def callback(body: Callback, s: DB, svc: Svc) -> dict:
    _ready(svc)
    st = sessions.read(svc.settings.session_secret, "state", body.state)
    if st is None:
        raise HTTPException(400, "login expired or was not started here; try again")
    try:
        tok = svc.paypal.exchange_auth_code(body.code)
        prof = identity.profile(svc.paypal.userinfo(tok["access_token"]))
    except PayPalError as e:
        raise HTTPException(401, f"PayPal refused the login ({e.status})") from e
    except (KeyError, ValueError) as e:
        raise HTTPException(401, str(e)) from e
    user = s.scalar(select(User).where(User.paypal_payer_id == prof.payer_id))
    if user is None:
        user = User(paypal_payer_id=prof.payer_id, email=prof.email,
                    display_name=prof.name or (prof.email or "PayPal user").split("@")[0],
                    role=st["role"])
        s.add(user)
    elif prof.email and user.email != prof.email:
        user.email = prof.email
    s.commit()
    token = sessions.issue(svc.settings.session_secret, "session", {"u": str(user.id)},
                           sessions.SESSION_TTL)
    expires = datetime.fromtimestamp(sessions.read(svc.settings.session_secret, "session",
                                                   token)["e"], UTC)
    return {"token": token, "expires_at": expires.isoformat(),
            "user": {"id": str(user.id), "role": user.role, "email": user.email,
                     "display_name": user.display_name, "has_paypal": True,
                     "verified": prof.verified}}
