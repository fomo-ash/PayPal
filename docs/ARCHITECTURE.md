# Architecture

## 1. Components

| Component | Runs on | Responsibility | Talks to |
|---|---|---|---|
| **web** (Next.js) | Render (node) | Buyer: post job, upload suite, see the validation report, fund with PayPal Buttons. Worker: browse, accept, run examples, submit. Verdict page. Admin review queue. `/verify` page. | api |
| **api** (FastAPI) | Render (python) | The ONLY writer of job state. State machine, policy, ledger, webhook receiver, auth. | Postgres, Redis, R2, PayPal (read-only + order creation) |
| **worker** (Celery) | Render (worker) | Suite validation, grading, fresh inputs, scanning, AI judge, money (outbox). | Postgres, Redis, R2, E2B, LLM (Groq / Gemini), PayPal |
| **beat** (Celery Beat) | Render (worker) | Timers: claim deadlines, authorization honor-period checks, outbox sweeper. | Redis |
| **sandbox** | E2B (Firecracker microVMs) | Runs untrusted code. Gets harness + submission only. No network. | nothing |
| **Postgres 16** | Render | Jobs, suites, submissions, runs, verdicts, ledger, outbox, audit, PayPal events. | |
| **Redis** | Render | Celery broker. Nothing important is stored only in Redis. | |
| **R2** | Cloudflare | Sealed suites, submissions, receipts (encrypted at rest). | |
| **MCP server** | inside api (Phase 5) | Agent access: list/get/run_examples/submit/get_verdict. | api |

## 2. End-to-end flow

```
BUYER                    API / WORKER                         PAYPAL                 SANDBOX
  │ POST /jobs + suite      │                                    │                       │
  │────────────────────────►│ validate_suite:                    │                       │
  │                         │  reference vs hidden tests ────────┼──────────────────────►│ (ref runs in its own VM)
  │                         │  AI spec check (LLM)               │                       │
  │◄──── report ────────────│  → AWAITING_FUNDS or INVALID       │                       │
  │ PayPal Buttons          │ POST /v2/checkout/orders AUTHORIZE ►│                       │
  │ approve popup ─────────────────────────────────────────────►│                       │
  │                         │ POST /orders/{id}/authorize ──────►│ hold $100             │
  │                         │ seal suite sha256 → OPEN           │                       │
WORKER                      │                                    │                       │
  │ claim (Log in w/ PayPal)│ → CLAIMED (deadline ≤ 48h)         │                       │
  │ submit ────────────────►│ grade: reject list, AST scan       │                       │
  │                         │  hidden inputs one by one ─────────┼──────────────────────►│ harness → outputs
  │                         │  compare OUTSIDE ◄─────────────────┼───────────────────────│
  │                         │  fresh inputs (ref = oracle)       │                       │
  │                         │  score (Decimal)                   │                       │
  │                         │ judge: LLM → AIDecision enum       │                       │
  │                         │ policy.decide → CAPTURE/VOID/REVIEW│                       │
  │                         │ outbox → capture 81.50 final ─────►│ $18.50 released       │
  │                         │ outbox → payout 77.42 ────────────►│ worker paid           │
  │                         │ webhooks confirm ◄─────────────────│                       │
  │◄── receipt ─────────────│ PAID → CODE_RELEASED (buyer gets code), signed receipt     │
```

## 3. The grading pipeline

Implemented in `backend/verdict/grading/pipeline.py` (Phase 0 runs locally; see `bench/`).

1. **Reject list** (`scanner/reject_list.py`): forbidden names/types, path escapes, size and file-count caps. Any hit means VOID, and the code is never executed.
2. **Static scan** (`scanner/ast_rules.py`, Semgrep later): hard signals (grader injection, network/escape imports, process exit, filesystem probing, file open) and soft signals (big literals, env access, introspection, eval). Hard signal means VOID, and the code is never executed.
3. **Hidden tests**: the runner streams `{id, nonce, input}`. The harness returns `{id, nonce, output|error, ms}`. `compare.outputs_match` decides pass/fail **outside** the sandbox.
4. **Flaky check**: failing tests are re-run with identical inputs. A flip marks the test flaky, and it is excluded from both numerator and denominator.
5. **Fresh inputs**: `gen_input(rng)` produces N small inputs, the reference solution produces the expected outputs, and the submission's outputs are compared outside. `rate = min(hidden, fresh)` for groups with fresh inputs.
6. **Score** (`core/scoring.py`): weighted, minimum score, cents rounded down, fee rounded half-up.
7. **AI judge** (`judge/review.py` + `judge/llm.py`): returns an `AIDecision` enum and cited findings. If every LLM provider fails, the result is HUMAN_REVIEW.
8. **Policy** (`core/policy.py`): hard signal → VOID; zero score → VOID; AI block without a hard signal → HUMAN_REVIEW; otherwise CAPTURE.

## 4. Security boundaries

| Boundary | Rule |
|---|---|
| Untrusted code ↔ everything | Runs only in a microVM: no network, no secrets, no suite, CPU/mem/pid/time/output caps, non-root. |
| Harness ↔ grader | The harness reports outputs only. Pass/fail and money never depend on anything the sandbox *claims*. Bad nonce or extra lines mean a HARNESS_TAMPER signal. |
| AI ↔ money | The AI returns an enum and findings. No amount field exists in its schema. The policy is unit-tested so that the AI cannot raise or solely block a payment. |
| Worker code ↔ AI prompt | Code is wrapped in `<untrusted>` tags. Instructions inside it are treated as evidence. |
| API ↔ PayPal | Only the money worker calls capture/void/payout, always with a `PayPal-Request-Id`. Webhooks are signature-verified and only *confirm*. |
| Browser ↔ secrets | The browser gets the PayPal **client ID** only. The secret lives on the server. |
| Repo ↔ secrets | `.env` is git-ignored. Secrets live in the Render dashboard. The repo is public. |

## 5. Reliability

- **Idempotency:** deterministic `PayPal-Request-Id` per (job, action). Celery tasks are keyed by (job, step).
- **Outbox:** state change + intended PayPal action are committed together. A crash anywhere means a safe retry.
- **Webhook dedupe:** on PayPal event id.
- **Timers:** claims expire back to OPEN. Holds approaching the end of the 3-day honor period trigger a reauthorize (once) or a void with notice.
- **Reconciliation (stretch):** a nightly comparison of the ledger with PayPal Transaction Search.

## 6. Production path (not built for the hackathon)

- PayPal **multiparty** (Commerce Platform): the worker is onboarded as `payee`, the Verdict fee is `platform_fees`, and `disbursement_mode: DELAYED`. Funds go buyer → worker directly and Verdict never holds them.
- Multi-language runners (Node, Go), milestone jobs, reputation, a public verifier.
