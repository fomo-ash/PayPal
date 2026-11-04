# Verdict

> **Pay only for code that works, whether a person or an AI agent wrote it.**
> PayPal holds the money. Verdict holds the code. Neither side can run off with the other's half.

Verdict is a **pay-on-verification** service for software work. A buyer posts a coding job and puts a PayPal **authorization hold** on the payment. A worker (a freelancer or an AI agent) submits code. Verdict runs the code against hidden tests in an isolated sandbox, checks it for cheating, and then tells PayPal to **capture exactly the share the work earned**, **void** the rest, and **pay out** the worker. Every step produces a signed receipt.

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/) (submissions close **Nov 12, 2026, 12:00 PST**).

---

## Table of contents
1. [The problem](#1-the-problem)
2. [How Verdict works](#2-how-verdict-works)
3. [How the payout is calculated](#3-how-the-payout-is-calculated)
4. [Loopholes and how they are closed](#4-loopholes-and-how-they-are-closed)
5. [Architecture](#5-architecture)
6. [Tech stack](#6-tech-stack)
7. [Repository layout](#7-repository-layout)
8. [Getting started](#8-getting-started)
9. [Team workflow (git)](#9-team-workflow-git)
10. [Roadmap and status](#10-roadmap-and-status)
11. [Documentation index](#11-documentation-index)
12. [License](#12-license)

---

## 1. The problem

Every small software deal between strangers has the same awkward question: **who pays first?**

- **The buyer pays first:** the worker may deliver broken code, half-finished code, or nothing. The buyer loses the money.
- **The worker goes first:** the buyer may take the code and never pay. The worker loses the time.

Traditional escrow fixes this with a human reviewer, which takes days and costs too much for $20–$500 jobs. It is also far too slow when **AI agents** do the work in minutes. Agents bring a new problem as well: code that *looks* finished but **games the checks** (memorized answers, tampered test tools, notes telling the AI grader to approve).

Verdict is the neutral middleman, automated and fair to **both** sides.

## 2. How Verdict works

| Step | What happens | PayPal piece |
|---|---|---|
| 1. Post | The buyer writes a description, public examples, **hidden tests in weighted groups**, a **reference solution**, and a minimum score. | none |
| 2. Validate | Verdict runs the reference solution against the hidden tests (it must pass 100%). The AI flags any hidden test the description doesn't imply. Tests are **sealed** with a SHA-256 hash. | none |
| 3. Fund | The buyer approves in the PayPal popup. The money is **authorized, not sent**: a hold, like a hotel deposit. | Orders v2 `intent=AUTHORIZE` |
| 4. Claim | The worker (signed in with PayPal) sees the description, examples, group weights and suite hash, then accepts. Deadline is 48h or less. | Log in with PayPal |
| 5. Submit | One graded submission. Unlimited runs against the public examples. | none |
| 6. Grade | Code runs in a no-network microVM. The harness feeds **one input at a time**; **expected answers never enter the sandbox**, and comparison happens outside. 200 **fresh random inputs** are checked against the reference solution. | none |
| 7. Check | A static scanner looks for known cheats. The AI judge (an open model on Groq's free tier) reviews the evidence and cites exact lines. **The AI can never raise a payment, and cannot block without a deterministic signal.** | none |
| 8. Settle | Capture the earned amount (`final_capture=true` releases the rest), or void everything. Pay the worker. | Payments v2 capture/void, **Payouts** |
| 9. Release | The buyer gets the code **only after the capture completes**. Both sides get a signed receipt. | none |
| 10. Disputes | If the buyer files a chargeback, the evidence pack is submitted automatically. | **Disputes API**, Webhooks |

## 3. How the payout is calculated

```
core_rate  = min(hidden_pass_rate, fresh_input_pass_rate)   # memorizers score ~0 automatically
score      = Σ weight_g × rate_g            (flaky tests excluded from both sides)
if score < min_score: score = 0
capture    = floor_to_cents(job_amount × score)              # PayPal partial capture, final_capture=true
fee        = round_half_up(capture × fee_bps / 10000)
worker     = capture − fee
released   = job_amount − capture                            # PayPal returns it to the buyer
```

**Example: $100 job, minimum score 50%, 5% fee**

| Group | Weight | Result | Rate |
|---|---|---|---|
| Core parsing | 60% | hidden 9/10, fresh 196/200 | min(0.90, 0.98) = 0.90 |
| Edge cases | 25% | 4/8 | 0.50 |
| Performance | 15% | 2/2 | 1.00 |

Score = 0.6×0.90 + 0.25×0.50 + 0.15×1.00 = **0.815**. That gives a **capture of $81.50**, **$18.50 released** to the buyer, a **fee of $4.08**, and **$77.42 to the worker**.
This exact example is a unit test: [`backend/tests/test_scoring.py`](backend/tests/test_scoring.py).

## 4. Loopholes and how they are closed

The full threat model is in [`docs/LOOPHOLES.md`](docs/LOOPHOLES.md). In summary:

| Who | Attack | Defence |
|---|---|---|
| Worker | Memorizes the expected answers | Fresh random inputs checked against the reference solution; `core = min(hidden, fresh)` |
| Worker | Reads the hidden tests | Expected outputs never enter the sandbox |
| Worker | Tampers with the test tool or fakes an exit code | No test framework in the sandbox; pass/fail is decided **outside**; `conftest.py`/`.pth`/`sitecustomize` rejected |
| Worker | Prompt-injects the AI judge | The AI cannot raise a payment; text addressed to the grader is a hard signal |
| Worker | Probes the tests with many submissions | One graded submission per PayPal identity; only group-level feedback before the verdict |
| Worker | Network, fork bombs, resource abuse | No network, CPU/memory/process/time/output limits |
| Buyer | Writes impossible tests | The reference solution must pass 100% before funding |
| Buyer | Writes tests the description doesn't imply | The AI checks each test against the description; flagged tests must be fixed before funding |
| Buyer | Changes tests later | The suite is sealed by SHA-256 hash, shown to the worker before they accept |
| Buyer | Takes the code without paying | Code is released only after the PayPal capture completes |
| Buyer | Chargeback after delivery | Automatic evidence through the Disputes API, delayed payout and limits for new buyers (reduced, not eliminated) |
| Platform | AI false positive | AI alone can only send a case to human review; a BLOCK needs a deterministic signal |
| Platform | Double charge on retry | `PayPal-Request-Id` idempotency, state machine and transactional outbox |
| Platform | Hold expires | Deadline of 48h or less (inside PayPal's 3-day honor period); reauthorize or split into milestones |

## 5. Architecture

```
   Buyer (human)          Worker (human)        Worker agent (any LLM)        
        │ Next.js web + PayPal JS SDK │                 │ MCP server / REST
        ▼                             ▼                 ▼
 ┌─────────────────────────── API (FastAPI) ───────────────────────────────┐
 │ auth (Log in with PayPal) · jobs · submissions · JOB STATE MACHINE      │
 │ policy engine · double-entry ledger · webhook receiver (sig-verified)   │
 └───┬───────────────┬───────────────┬────────────────┬────────────────────┘
     │ SQL           │ enqueue       │ HTTPS          │ put/get
 ┌───▼──────┐   ┌────▼────┐   ┌──────▼─────────┐  ┌──▼───────────────────┐
 │ Postgres │   │  Redis  │   │  PayPal APIs   │  │ R2 object store      │
 │ state,   │   │ (queue) │   │ Orders v2      │  │ sealed test suites,  │
 │ ledger,  │   └────┬────┘   │ Payments v2    │  │ submissions, signed  │
 │ outbox,  │        │        │ Payouts        │  │ receipts             │
 │ audit    │        ▼        │ Disputes       │  └──────────────────────┘
 └──────────┘  ┌─────────────────────────────┐  │ Webhooks · Identity │
               │ Workers (Celery)            │  └─────────────────────┘
               │ 1 suite validator           │
               │ 2 grader ───────────────────┼──► SANDBOX (E2B microVM)
               │ 3 fresh-input generator     │    no network · resource caps
               │ 4 static scanner            │    harness gets ONE input at a
               │ 5 AI judge (LLM via Groq)   │    time, never sees the expected
               │ 6 money worker (outbox)     │    answers
               └─────────────────────────────┘
```

Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · state machine: [`docs/STATE_MACHINE.md`](docs/STATE_MACHINE.md) · data model: [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md).

### Design rules (do not break these)
1. **The AI never computes money.** Amounts come only from `verdict.core.scoring`.
2. **The AI can never raise a payment.** `verdict.core.policy` takes the AI's decision as an enum, never as an amount.
3. **The AI cannot block on its own.** A BLOCK needs a deterministic hard signal; AI suspicion alone means `HUMAN_REVIEW`.
4. **Expected outputs never enter the sandbox.**
5. **Only the money worker calls PayPal's money endpoints**, always with a `PayPal-Request-Id`.
6. **Every state change goes through `verdict.core.state_machine`.**

## 6. Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 15, TypeScript, Tailwind, shadcn/ui, `@paypal/react-paypal-js`, Monaco (read-only code view) |
| API | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, httpx |
| Jobs | Celery + Redis, Celery Beat (deadlines, hold expiry) |
| Database | Postgres 16 |
| Storage | Cloudflare R2 (S3 API) |
| Sandbox | E2B microVMs (Firecracker); fallback Docker + gVisor |
| Checks | Hypothesis, Python `ast`, Semgrep custom rules |
| AI | Free tiers through one OpenAI-compatible client (`verdict/judge/llm.py`): **Groq** `openai/gpt-oss-120b` for the judge and the description check, `llama-3.1-8b-instant` for drafts; **Gemini Flash** (Google AI Studio) as automatic fallback. Any OpenAI-compatible provider can be swapped in via `.env`. See [`docs/LLM_SETUP.md`](docs/LLM_SETUP.md) |
| Agents | MCP Python SDK (FastMCP), demo worker agent using the same free LLM client |
| PayPal | Orders v2, Payments v2 (authorize/capture/void/reauthorize), Payouts, Disputes, Webhooks, Log in with PayPal |
| Receipts | Canonical JSON signed with Ed25519, PDF via WeasyPrint, public `/verify` page |
| Observability | OpenTelemetry, Sentry, Langfuse |
| Testing | pytest, Playwright, judge benchmark (`bench/`) |
| Deploy | Render (`render.yaml`), E2B, GitHub Actions |

## 7. Repository layout

```
paypall/
├─ README.md                  ← you are here
├─ LICENSE                    MIT
├─ .env.example               every environment variable, documented
├─ pyproject.toml             Python package "verdict" (backend) + dev tools
├─ Makefile                   make dev / test / lint / spike
├─ docker-compose.yml         local Postgres + Redis
├─ render.yaml                production deploy (web, api, worker, beat, db, redis)
├─ docs/                      architecture, loopholes, PayPal setup, data model, plan, demo
├─ backend/
│  ├─ verdict/
│  │  ├─ config.py            settings loaded from .env
│  │  ├─ core/                ★ pure logic: scoring, policy, state machine, ledger, outbox, audit
│  │  ├─ paypal/              typed PayPal client: orders, payments, payouts, disputes, webhooks, identity
│  │  ├─ sandbox/             harness (runs inside the VM), E2B + Docker runners
│  │  ├─ grading/             pipeline, fresh inputs, output comparison
│  │  ├─ scanner/             reject list, AST rules, Semgrep rules
│  │  ├─ judge/               AI description check + cheating review, JSON schema, prompts
│  │  ├─ receipts/            Ed25519 signing, canonical JSON
│  │  ├─ db/                  SQLAlchemy models, session
│  │  ├─ api/                 FastAPI app + routers
│  │  ├─ worker/              Celery app + tasks
│  │  └─ mcp/                 MCP server for agents
│  └─ tests/                  unit tests (scoring, policy, state machine, harness, compare)
├─ apps/web/                  Next.js frontend (created in Phase 1; see its README)
├─ agents/                    demo agents: one honest, several cheating
├─ bench/                     judge benchmark: tasks, submissions, expected results
└─ scripts/                   sandbox_spike.py (day-1 PayPal check), check_env.py
```

## 8. Getting started

### Prerequisites
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node 20+ (frontend, Phase 1)
- Docker (local Postgres/Redis)
- A PayPal developer account with sandbox app credentials ([`docs/PAYPAL_SANDBOX_SETUP.md`](docs/PAYPAL_SANDBOX_SETUP.md))
- A free Groq API key (and optionally a free Gemini key as fallback): [`docs/LLM_SETUP.md`](docs/LLM_SETUP.md)
- An E2B API key (Phase 1)

### Setup
```bash
git clone <team-repo-url> paypall && cd paypall
cp .env.example .env            # fill in your sandbox keys; never commit .env
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
make test                       # unit tests + benchmark (no keys needed)
make bench                      # grading pipeline on 2 honest + 5 cheating submissions
python scripts/check_env.py     # confirms which keys are set (never prints them)
python scripts/sandbox_spike.py # day-1: runs authorize → partial capture → void → payout in the sandbox
python scripts/llm_smoke.py     # checks the free LLM judge (needs LLM_API_KEY from Groq)
```

### Local services (Phase 1+)
```bash
docker compose up -d            # Postgres + Redis
make api                        # FastAPI on :8000
make worker                     # Celery worker
ngrok http 8000                 # public URL for PayPal webhooks
```

## 9. Team workflow (git)

- `main` is protected: merge only through pull requests with at least one review.
- One branch per person and area: `<name>/<area>-<short-desc>`, e.g. `anurag/phase-0-scaffold`, `riya/paypal-money-worker`.
- Small PRs. Rebase on `main` before opening one. CI must pass.
- **Never commit `.env`** or any key. The repo is public.
- Full guide: [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

## 10. Roadmap and status

| Phase | Dates | Goal | Status |
|---|---|---|---|
| 0 | Nov 1 | Repo structure, docs, scoring/policy/state machine/harness/scanner with tests, local grading bench (7/7 expected), sandbox spike script | ✅ this commit |
| 1 | Nov 1–2 | Risk spikes: PayPal flow end to end in sandbox, E2B harness | ⏳ |
| 2 | Nov 3–5 | DB, state machine wired to the API, outbox + money worker, grading pipeline, fresh inputs | ⏳ |
| 3 | Nov 6–7 | Scanner, policy engine wiring, AI judge, description check | ⏳ |
| 4 | Nov 8–9 | Web UI, Log in with PayPal, receipts, code release, review queue | ⏳ |
| 5 | Nov 10 | MCP + agent demo, dispute evidence, deploy | ⏳ |
| 6 | Nov 11–12 | Benchmark, end-to-end tests, video, submit by **Nov 12 10:00 PST** | ⏳ |

Day-by-day plan, owners and cut list: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## 11. Documentation index

| Doc | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, data flow, grading pipeline, security boundaries |
| [`docs/LOOPHOLES.md`](docs/LOOPHOLES.md) | Full threat model: worker, buyer and platform attacks and defences |
| [`docs/STATE_MACHINE.md`](docs/STATE_MACHINE.md) | Job states, transitions, timers, outbox |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Postgres tables and the double-entry ledger |
| [`docs/PAYPAL_SANDBOX_SETUP.md`](docs/PAYPAL_SANDBOX_SETUP.md) | Getting keys, test accounts, webhooks, every PayPal call we make |
| [`docs/LLM_SETUP.md`](docs/LLM_SETUP.md) | Free LLM providers (Groq + Gemini), limits, keys, smoke test |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 11-day plan, owners, cut list, day-1 checks |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | The 3-minute video, scene by scene |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Branching, commits, PRs, code style |

## 12. License

[MIT](LICENSE). Use of PayPal APIs is subject to PayPal's own developer terms. "Conditional payment" in this project is a hackathon prototype running in the PayPal **sandbox**; it is not a licensed escrow service.
