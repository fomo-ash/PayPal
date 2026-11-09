"""Minimal typed PayPal REST client (sync, httpx).

* OAuth2 client-credentials token, cached until shortly before expiry.
* Every POST carries a `PayPal-Request-Id` so retries are idempotent.
  Callers pass a deterministic key such as f"{job_id}:capture" so a crash + retry
  can never capture or pay out twice.
* Only verdict.worker money tasks and scripts/sandbox_spike.py may call the money methods.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


class PayPalError(Exception):
    def __init__(self, status: int, body: Any, debug_id: str | None):
        super().__init__(f"PayPal HTTP {status} (debug_id={debug_id}): {body}")
        self.status, self.body, self.debug_id = status, body, debug_id


@dataclass
class _Token:
    value: str
    expires_at: float


class PayPalClient:
    def __init__(self, base_url: str, client_id: str, secret: str, timeout: float = 30.0):
        if not client_id or not secret:
            raise ValueError("PayPal client id/secret missing; see docs/PAYPAL_SANDBOX_SETUP.md")
        self._base = base_url.rstrip("/")
        self._auth = (client_id, secret)
        self._http = httpx.Client(timeout=timeout)
        self._token: _Token | None = None

    # ── auth ──────────────────────────────────────────────────────────────────
    def token(self) -> str:
        if self._token and time.time() < self._token.expires_at - 60:
            return self._token.value
        r = self._http.post(f"{self._base}/v1/oauth2/token", auth=self._auth,
                            data={"grant_type": "client_credentials"})
        self._raise(r)
        body = r.json()
        self._token = _Token(body["access_token"], time.time() + int(body.get("expires_in", 300)))
        return self._token.value

    # ── Log in with PayPal (the USER's token, not the app's) ──────────────────
    def exchange_auth_code(self, code: str) -> dict:
        r = self._http.post(f"{self._base}/v1/oauth2/token", auth=self._auth,
                            data={"grant_type": "authorization_code", "code": code})
        self._raise(r)
        return r.json()

    def userinfo(self, user_access_token: str) -> dict:
        r = self._http.get(f"{self._base}/v1/identity/oauth2/userinfo",
                           params={"schema": "paypalv1.1"},
                           headers={"Authorization": f"Bearer {user_access_token}"})
        self._raise(r)
        return r.json()

    # ── low level ─────────────────────────────────────────────────────────────
    def request(self, method: str, path: str, *, json: Any = None,
                idempotency_key: str | None = None, params: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json",
                   "Prefer": "return=representation"}
        if method.upper() == "POST":
            headers["PayPal-Request-Id"] = idempotency_key or str(uuid.uuid4())
        r = self._http.request(method, f"{self._base}{path}", json=json, headers=headers,
                               params=params)
        self._raise(r)
        return r.json() if r.content else None

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = r.text
            raise PayPalError(r.status_code, body, r.headers.get("Paypal-Debug-Id"))

    # ── Orders v2 ─────────────────────────────────────────────────────────────
    def create_authorize_order(self, *, amount: str, currency: str, reference_id: str,
                               description: str, return_url: str, cancel_url: str,
                               idempotency_key: str) -> dict:
        body = {
            "intent": "AUTHORIZE",
            "purchase_units": [{
                "reference_id": reference_id,
                "description": description[:127],
                "amount": {"currency_code": currency, "value": amount},
            }],
            "payment_source": {"paypal": {"experience_context": {
                "return_url": return_url, "cancel_url": cancel_url,
                "user_action": "CONTINUE", "shipping_preference": "NO_SHIPPING",
            }}},
        }
        return self.request("POST", "/v2/checkout/orders", json=body,
                            idempotency_key=idempotency_key)

    def get_order(self, order_id: str) -> dict:
        return self.request("GET", f"/v2/checkout/orders/{order_id}")

    def authorize_order(self, order_id: str, idempotency_key: str) -> dict:
        return self.request("POST", f"/v2/checkout/orders/{order_id}/authorize", json={},
                            idempotency_key=idempotency_key)

    @staticmethod
    def approve_link(order: dict) -> str:
        for link in order.get("links", []):
            if link.get("rel") in ("payer-action", "approve"):
                return link["href"]
        raise KeyError("no approve link in order response")

    @staticmethod
    def authorization_id(authorized_order: dict) -> str:
        return authorized_order["purchase_units"][0]["payments"]["authorizations"][0]["id"]

    # ── Payments v2 (authorizations) ──────────────────────────────────────────
    def get_authorization(self, auth_id: str) -> dict:
        return self.request("GET", f"/v2/payments/authorizations/{auth_id}")

    def capture_authorization(self, auth_id: str, *, amount: str, currency: str,
                              final_capture: bool, idempotency_key: str,
                              invoice_id: str | None = None) -> dict:
        body: dict[str, Any] = {"amount": {"currency_code": currency, "value": amount},
                                "final_capture": final_capture}
        if invoice_id:
            body["invoice_id"] = invoice_id
        return self.request("POST", f"/v2/payments/authorizations/{auth_id}/capture",
                            json=body, idempotency_key=idempotency_key)

    def void_authorization(self, auth_id: str, idempotency_key: str) -> None:
        self.request("POST", f"/v2/payments/authorizations/{auth_id}/void",
                     idempotency_key=idempotency_key)

    def reauthorize(self, auth_id: str, *, amount: str, currency: str,
                    idempotency_key: str) -> dict:
        return self.request("POST", f"/v2/payments/authorizations/{auth_id}/reauthorize",
                            json={"amount": {"currency_code": currency, "value": amount}},
                            idempotency_key=idempotency_key)

    # ── Payouts v1 ────────────────────────────────────────────────────────────
    def create_payout(self, *, batch_id: str, receiver: str, recipient_type: str,
                      amount: str, currency: str, note: str) -> dict:
        """recipient_type: 'PAYPAL_ID' (preferred, from Log in with PayPal) or 'EMAIL'."""
        body = {
            "sender_batch_header": {"sender_batch_id": batch_id,
                                    "email_subject": "You've been paid by Verdict"},
            "items": [{"recipient_type": recipient_type, "receiver": receiver,
                       "amount": {"value": amount, "currency": currency},
                       "note": note, "sender_item_id": batch_id}],
        }
        return self.request("POST", "/v1/payments/payouts", json=body, idempotency_key=batch_id)

    def get_payout_batch(self, payout_batch_id: str) -> dict:
        return self.request("GET", f"/v1/payments/payouts/{payout_batch_id}")

    # ── Webhooks ──────────────────────────────────────────────────────────────
    def verify_webhook_signature(self, *, headers: dict[str, str], event: dict,
                                 webhook_id: str) -> bool:
        h = {k.lower(): v for k, v in headers.items()}
        body = {
            "auth_algo": h.get("paypal-auth-algo"),
            "cert_url": h.get("paypal-cert-url"),
            "transmission_id": h.get("paypal-transmission-id"),
            "transmission_sig": h.get("paypal-transmission-sig"),
            "transmission_time": h.get("paypal-transmission-time"),
            "webhook_id": webhook_id,
            "webhook_event": event,
        }
        res = self.request("POST", "/v1/notifications/verify-webhook-signature", json=body)
        return res.get("verification_status") == "SUCCESS"

    # ── Disputes v1 ───────────────────────────────────────────────────────────
    def get_dispute(self, dispute_id: str) -> dict:
        return self.request("GET", f"/v1/customer/disputes/{dispute_id}")

    # provide-evidence is multipart (JSON + files); implemented in Phase 5 (paypal/disputes.py).

    def close(self) -> None:
        self._http.close()
