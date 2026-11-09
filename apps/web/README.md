# apps/web: the Verdict web app

Vite + React + TypeScript, built to static files and served by Render (`verdict-web` in
`render.yaml`). Tables use **AG Grid**; funding uses the **PayPal JS SDK** (`intent=authorize`).

```bash
cd apps/web
npm install
npm run dev            # http://localhost:5180, calls the API at http://localhost:8000
VITE_API_URL=https://verdict-api-zyaa.onrender.com npm run dev   # against the hosted API
npm run build          # → dist/
```

Run the API with `DEMO_LOGIN=true make local` so the "Try as buyer / worker / reviewer" buttons
work. The PayPal client id comes from `GET /public-config` (public by design); the secret never
reaches the browser.

## Pages
| Route | Who | What |
|---|---|---|
| `/` | everyone | pitch, the five steps, open jobs (AG Grid) |
| `/login` | everyone | demo login per role, or Log in with PayPal when enabled |
| `/jobs/new` | buyer | description, budget, min score; the bench sample suite or an uploaded JSON suite |
| `/jobs/:id` | buyer | validation report (reference + AI spec check), PayPal Buttons for the hold, link to the verdict |
| `/jobs/:id` | worker | take the job, edit `solution.py` (or load an honest/cheating sample), run public examples, submit once |
| `/submissions/:id` | both | live progress, score, the hold split (worker / fee / back to buyer), hidden vs fresh per group, scanner + AI findings, code with flagged lines (buyer, after payment), signed receipt with PayPal IDs |
| `/review` | reviewer | human-review queue (AG Grid), the case with flagged lines, approve ≤ scored amount or void |
| `/me` | buyer, worker | my jobs / my work (including jobs an AI agent took for me) |
| `/verify` | anyone | paste or open a receipt and check its Ed25519 signature |
| `/auth/callback` | everyone | return page for Log in with PayPal |

The sample task (`bench/tasks/log_parser`) is bundled at build time, so a visitor can post a
real job and play an honest or cheating worker without writing code.

## API contract the pages use (all live in the backend now)

**Login (Log in with PayPal).**
1. Button → `GET /auth/paypal/login?role=buyer|worker` → `{url}` → `window.location = url`.
2. PayPal redirects to `/auth/callback?code=…&state=…` (this page).
3. That page posts `{code, state}` to `POST /auth/paypal/callback` → `{token, expires_at, user}`.
4. Keep the token (memory or `sessionStorage`) and send `Authorization: Bearer <token>`.
   `GET /me` returns the user. The hosted sandbox also offers `POST /auth/demo {role}` (DEMO_LOGIN).

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

CORS allows `CORS_ORIGINS` (default `http://localhost:5180`). Full schemas: `http://localhost:8000/docs`.
