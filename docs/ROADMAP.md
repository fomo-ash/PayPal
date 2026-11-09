# Roadmap: Nov 1 → Nov 12, 2026 (submit by Nov 12, 10:00 PST; hard deadline 12:00 PST)

## Suggested ownership (adjust to the team)
| Area | Owner | Main folders |
|---|---|---|
| A. PayPal & money (orders, outbox, payouts, webhooks, ledger, identity) | _tbd_ | `backend/verdict/paypal`, `core/ledger.py`, `core/outbox.py` |
| B. Sandbox & grading (E2B runner, pipeline, fresh inputs, bench) | _tbd_ | `sandbox/`, `grading/`, `bench/` |
| C. AI & integrity (scanner, judge, spec check, prompts, Langfuse) | _tbd_ | `scanner/`, `judge/` |
| D. Product (web UI, API routers, MCP, agents, video) | _tbd_ | `apps/web`, `api/`, `mcp/`, `agents/` |

## Plan
| Phase | Day | Date | Deliverable | Done when |
|---|---|---|---|---|
| 0 | 1 | Nov 1 | Repo structure, docs, scoring/policy/state machine/harness/scanner with tests, local bench | `make test` and `make bench` green ✅ |
| 1 | 1–2 | Nov 1–2 | **Risk spikes:** `sandbox_spike.py` all PASS (A); E2B runner runs the bench with network blocked (B) | PayPal 6/6 ✅ · E2B runner + fake-VM tests ✅ · live `make e2b` pending key |
| 2 | 3 | Nov 3 | DB models + Alembic, state machine persisted, outbox + money worker (A, D) | Unit tests with PayPal mocked (respx) ✅ |
| 2 | 4 | Nov 4 | Suite upload, seal hash, reference validation, grading via E2B (B) | A job graded through the API ✅ |
| 2 | 5 | Nov 5 | Fresh-input generator acceptance, flaky handling in prod path, webhooks (A, B) | Memorizer voided via API ✅ (e2e test) |
| 3 | 6 | Nov 6 | Semgrep rules, 3 more cheat agents, AI judge with JSON schema (C) | Judge cites lines; AI-alone → review ✅ (done Nov 9; time-bomb cheat added, Semgrep cut) |
| 3 | 7 | Nov 7 | AI spec check (B2), Langfuse tracing, judge red-team (C) | Unfair test blocked before funding ✅ · admin review API ✅ · Langfuse deferred |
| 4 | 8 | Nov 8 | Web: post/fund (PayPal Buttons), browse/claim/submit, verdict page (D) | Full flow in the browser |
| 4 | 9 | Nov 9 | Log in with PayPal, code release, signed receipt + `/verify`, admin review (A, D) | Every loophole has a working answer |
| 5 | 10 | Nov 10 | MCP server + LLM worker agent, dispute evidence, deploy to Render (D, A) | Agent paid in the hosted demo |
| 6 | 11 | Nov 11 | Bench to 4 tasks × 8 submissions, results table, Playwright e2e, video recorded | 0 honest blocked; video < 3:00 |
| 6 | 12 | Nov 12 AM | Submit: public repo, MIT in About, demo URL, video | Submitted by 10:00 PST |

## Notes from the Phase 0/1 code review (done)
- `decide()` treats unknown/plain-string AI values as HUMAN_REVIEW (they used to fall through to CAPTURE).
- New exits so no job can get stuck: `SUBMITTED → VOIDING`, `CAPTURING → HUMAN_REVIEW`, `PAYING_OUT → PAYOUT_FAILED`.
- Secret per-submission fresh-input seed; strict ASCII timestamps in the reference; generator covers days 29–31.
- State writes are compare-and-set (`db/repo.py`); disputes after `CODE_RELEASED` get their own table in Phase 5.

## Cut list (cut from the top first)
1. Nightly reconciliation with Transaction Search
2. Dispute evidence automation
3. AI-drafted generators (buyer uploads one instead)
4. Admin review UI (resolve via SQL/CLI)
5. MCP server (keep the scripted cheating agents)

## Never cut
Sealed tests · reference-solution validation · expected outputs outside the sandbox · AI cannot raise or solely block · idempotent money calls · the bench table.
