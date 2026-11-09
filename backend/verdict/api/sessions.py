"""Stateless signed tokens: login sessions and the OAuth `state` value.

token = base64url(json payload) "." base64url(HMAC-SHA256(SESSION_SECRET, payload))
The payload carries a kind ("session" or "state"), so a login state can never be replayed as
a session, and an expiry, so a stolen token stops working.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

SESSION_TTL = 7 * 24 * 3600
STATE_TTL = 10 * 60


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(secret: str, kind: str, data: dict[str, Any], ttl: int, now: float | None = None) -> str:
    if not secret:
        raise ValueError("SESSION_SECRET is not set")
    body = {"k": kind, "e": int((now or time.time()) + ttl), "n": secrets.token_hex(8), **data}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(sig)}"


def read(secret: str, kind: str, token: str, now: float | None = None) -> dict[str, Any] | None:
    if not secret or not token or token.count(".") != 1:
        return None
    raw_b64, sig_b64 = token.split(".")
    try:
        raw, sig = _unb64(raw_b64), _unb64(sig_b64)
        body = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    if not hmac.compare_digest(sig, hmac.new(secret.encode(), raw, hashlib.sha256).digest()):
        return None
    if not isinstance(body, dict) or body.get("k") != kind:
        return None
    if int(body.get("e", 0)) < (now or time.time()):
        return None
    return body
