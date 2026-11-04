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
