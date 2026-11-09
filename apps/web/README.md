# apps/web: Next.js frontend (Phase 4)

Create it (from the repo root):
```bash
npx create-next-app@15 apps/web --ts --tailwind --eslint --app --src-dir --no-import-alias
cd apps/web && npx shadcn@latest init && npm i @paypal/react-paypal-js @monaco-editor/react
```

## Pages
| Route | Who | What |
|---|---|---|
| `/` | everyone | pitch + open jobs |
| `/jobs/new` | buyer | spec, examples, weighted groups, min score, amount; upload hidden tests + reference (+ generator) |
| `/jobs/[id]/validate` | buyer | reference result, AI spec-check flags, suite hash |
| `/jobs/[id]/fund` | buyer | `PayPalButtons` with `intent: "authorize"`; createOrder → `POST /jobs/{id}/fund`, onApprove → `/fund/confirm` |
| `/jobs/[id]` | worker | spec, examples, weights, suite hash, Accept (Log in with PayPal) |
| `/jobs/[id]/work` | worker | run public examples, submit once |
| `/jobs/[id]/verdict` | both | group scores, fresh vs hidden, scanner + AI findings with highlighted lines (Monaco), PayPal IDs, receipt |
| `/admin/review` | admin | human-review queue: approve ≤ deterministic amount, or void |
| `/verify` | anyone | paste a receipt and check its Ed25519 signature |

Only `NEXT_PUBLIC_PAYPAL_CLIENT_ID` and `NEXT_PUBLIC_API_URL` reach the browser. Never the secret.

## API contract the pages use (all live in the backend now)

**Login (Log in with PayPal).**
1. Button → `GET /auth/paypal/login?role=buyer|worker` → `{url}` → `window.location = url`.
2. PayPal redirects to `/auth/callback?code=…&state=…` (this page).
3. That page posts `{code, state}` to `POST /auth/paypal/callback` → `{token, expires_at, user}`.
4. Keep the token (memory or `sessionStorage`) and send `Authorization: Bearer <token>`.
   `GET /me` returns the user. In dev you can still send `X-User-Id` instead.

**Pages → endpoints.**

| Page | Calls |
|---|---|
| `/jobs/new` | `POST /jobs`, `PUT /jobs/{id}/suite` |
| `/jobs/[id]/validate` | `POST /jobs/{id}/validate` → `state`, `problems`, `warnings`, `spec_check[]` |
| `/jobs/[id]/fund` | `POST /jobs/{id}/fund` (createOrder), `POST /jobs/{id}/fund/confirm` (onApprove) |
| `/jobs/[id]` | `GET /jobs/{id}`, `POST /jobs/{id}/claim` |
| `/jobs/[id]/work` | `POST /jobs/{id}/examples-run`, `POST /jobs/{id}/submit` |
| `/jobs/[id]/verdict` | `GET /submissions/{id}` → `runs`, `verdict`, `scan_findings[]`, `ai_review` (file + line per finding); `GET /submissions/{id}/code` (buyer, after PAID); `GET /receipts/{job_id}` |
| `/admin/review` | `GET /admin/reviews`, `GET /admin/reviews/{job_id}`, `POST /admin/reviews/{job_id}` `{capture, note}` |
| `/verify` | `POST /receipts/verify` `{receipt, signature}`, `GET /receipts/public-key` (no login) |
| settings | `POST /agents` (shows the key once), `GET /agents` |

CORS allows `CORS_ORIGINS` (default `http://localhost:3000`). Full schemas: `http://localhost:8000/docs`.
