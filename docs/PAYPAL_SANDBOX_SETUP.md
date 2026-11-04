# PayPal sandbox setup

The sandbox is PayPal's test copy: same APIs, fake money. Base URL `https://api-m.sandbox.paypal.com`.

## 1. Get keys
1. Go to https://developer.paypal.com and **Log in to Dashboard** (any normal PayPal account; free).
2. **Apps & Credentials**, toggle **Sandbox**, then **Create App**: name `verdict`, type **Merchant**, linked to the sandbox **business** account.
3. Copy the **Client ID** and **Secret** into `.env` (`PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`). Each teammate can use their own app, or share one via a password manager, **never via git or chat**.
4. In the app's **Features**, enable **Payouts** and **Log in with PayPal** (return URL `http://localhost:3000/auth/callback`; scopes: email, account info / PayPal account ID).

## 2. Test accounts (Testing Tools → Sandbox Accounts)
| Role | Type | Country | Balance |
|---|---|---|---|
| Verdict platform | Business (default one) | US | any |
| Buyer | Personal | US | $5,000 |
| Honest worker | Personal | US | $0 |
| Cheating agent owner | Personal | US | $0 |

Put the honest worker's sandbox email in `SANDBOX_WORKER_EMAIL`. See passwords via **⋯ → View/Edit account**. Log in at https://www.sandbox.paypal.com to see balances.

## 3. Webhooks
1. Run the API locally and `ngrok http 8000`.
2. App → **Webhooks → Add Webhook**: URL `https://<ngrok-id>.ngrok-free.app/webhooks/paypal`, events from `backend/verdict/paypal/webhooks.py::SUBSCRIBED_EVENTS`.
3. Copy the **Webhook ID** into `PAYPAL_WEBHOOK_ID`; it's needed for signature verification.

## 4. Smoke test
```bash
python scripts/check_env.py
python scripts/sandbox_spike.py
```
The spike asks you to approve two orders in the browser as the **buyer** sandbox account. Expected output: every line `PASS`.

## 5. Every PayPal call Verdict makes
| Step | Call |
|---|---|
| Token | `POST /v1/oauth2/token` (client credentials) |
| Fund | `POST /v2/checkout/orders` `intent: AUTHORIZE`, then the buyer approves, then `POST /v2/checkout/orders/{id}/authorize` |
| Inspect | `GET /v2/payments/authorizations/{id}` |
| Pay earned share | `POST /v2/payments/authorizations/{id}/capture` `{amount, final_capture: true}` (the remainder is released) |
| Nothing earned | `POST /v2/payments/authorizations/{id}/void` |
| Extend (rare) | `POST /v2/payments/authorizations/{id}/reauthorize` |
| Pay worker | `POST /v1/payments/payouts` (`recipient_type: PAYPAL_ID`) and `GET /v1/payments/payouts/{batch_id}` |
| Webhook check | `POST /v1/notifications/verify-webhook-signature` |
| Disputes | `GET /v1/customer/disputes/{id}`, `POST …/provide-evidence` |
| Identity | Log in with PayPal (OIDC): `/v1/oauth2/token` (authorization_code) and `/v1/identity/oauth2/userinfo` |

All POSTs send `PayPal-Request-Id` (idempotency).

## 6. Facts to confirm on day 1 (record results in the PR)
- [ ] Partial capture with `final_capture: true` leaves the authorization `CAPTURED` (remainder released).
- [ ] Retrying a capture with the same `PayPal-Request-Id` returns the same capture (no double charge).
- [ ] Payouts are enabled for the sandbox business account and succeed.
- [ ] Honor period (3 days) and validity (29 days) match current docs (`expiration_time` on the authorization).
- [ ] E2B: cold start under ~3s, outbound network blocked.

## 7. For judges
The hosted demo already has keys. The README lists a **sandbox buyer** login (fake account, fake money) for clicking through the PayPal popup.
