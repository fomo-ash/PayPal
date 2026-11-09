"""Log in with PayPal (OpenID Connect).

Flow: the web app sends the user to authorize_url() → PayPal redirects back to the web app
with ?code&state → the web app posts both to /auth/paypal/callback → the API exchanges the
code (POST /v1/oauth2/token, grant_type=authorization_code) and reads
GET /v1/identity/oauth2/userinfo?schema=paypalv1.1 → payer_id, email.

payer_id becomes users.paypal_payer_id and is the Payouts receiver (recipient_type
PAYPAL_ID), so payouts always land in a real account (no "unclaimed" money). One graded
submission per payer_id per job stops fake-account probing (loophole W8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

SCOPE = "openid email https://uri.paypal.com/services/paypalattributes"


@dataclass(frozen=True)
class Profile:
    payer_id: str
    email: str | None
    name: str
    verified: bool


def authorize_url(web_url: str, client_id: str, redirect_uri: str, state: str) -> str:
    q = urlencode({"flowEntry": "static", "client_id": client_id, "response_type": "code",
                   "scope": SCOPE, "redirect_uri": redirect_uri, "state": state})
    return f"{web_url}/connect?{q}"


def profile(info: dict[str, Any]) -> Profile:
    payer_id = info.get("payer_id")
    if not payer_id or not isinstance(payer_id, str):
        raise ValueError("PayPal did not share the payer ID; enable it in the app's "
                         "Log in with PayPal settings")
    emails = info.get("emails") or []
    primary = next((e.get("value") for e in emails if e.get("primary")), None)
    email = primary or (emails[0].get("value") if emails else None) or info.get("email")
    return Profile(payer_id=payer_id, email=email, name=str(info.get("name") or "")[:80],
                   verified=str(info.get("verified_account", "")).lower() == "true")
