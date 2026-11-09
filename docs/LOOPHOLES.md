# Threat model: loopholes and defences

Every row lists the attack, the defence, where it lives in code, and how we prove it (test or bench case).
"Hard" means a deterministic signal: the policy voids without needing the AI.

## Worker attacks

| ID | Attack | Defence | Code | Proof |
|---|---|---|---|---|
| W1 | Memorize expected answers (or leaked tests) | Fresh random inputs, reference solution as oracle; `rate = min(hidden, fresh)` | `core/scoring.py`, `grading/pipeline.py` | `bench: cheat_memorizer` (10/10 hidden, 23/200 fresh → VOID); `test_memorizer_is_capped_by_fresh_inputs` |
| W2 | Read hidden tests / expected outputs | Expected outputs never enter the sandbox; file listing/open is a hard signal | `sandbox/runner.py`, `scanner/ast_rules.py` | `bench: cheat_env_sniff` |
| W3 | Fake results: conftest/pytest hooks, `sys.exit(0)`, `os._exit` | No test framework in the sandbox; pass/fail computed outside; reject list; exit calls are hard | `scanner/reject_list.py`, `sandbox/harness.py` | `bench: cheat_conftest`, `cheat_exit`; `test_harness_survives_exit_and_timeout` |
| W4 | Prompt-inject the AI judge | AI has no amount input; text addressed to the grader is hard; code wrapped as untrusted | `core/policy.py`, `scanner/ast_rules.py`, `judge/prompts/review.md` | `bench: cheat_injection`; `test_ai_has_no_way_to_supply_an_amount` |
| W5 | Detect grading environment, behave differently | Hidden and fresh inputs go through the same harness; env access flagged (soft); no network | `scanner/ast_rules.py` | `bench: cheat_env_sniff` |
| W6 | Probe hidden tests via repeated submissions | One graded submission per PayPal identity per job; only group scores before the verdict; examples-only runs unlimited | `api/routers/submissions.py` | `test_api_submissions.py` (second submit and re-claim refused) |
| W7 | Network, fork bomb, memory or CPU abuse, huge output | microVM no network; pid/mem/CPU/time/output caps; network/escape imports hard | `sandbox/e2b_runner.py`, `docker_runner.py` | `make e2b`: DNS + raw IP probes return no bytes (verified Nov 5) |
| W8 | Sybil accounts to probe | Log in with PayPal required; one graded submission per `payer_id` | `paypal/identity.py` (Phase 4) | |
| W11 | Code that passes every test but misbehaves later (time bomb, backdoor) | AI review of any paying result; it can only send the job to a person, who can lower or void | `worker/grading.py::ai_review`, `api/routers/admin.py` | `bench: cheat_timebomb` (CAPTURE without AI, HUMAN_REVIEW with `make bench-ai`); `test_ai_review.py`, `test_admin_review.py` |
| W10 | Predict the fresh inputs (known seed + public generator) | Secret 64-bit seed per submission, drawn after submission and stored with the verdict for replay | `grading/pipeline.py::new_seed` | `test_seed_is_secret_and_recorded` |
| W9 | Forge protocol lines from inside the harness process | Per-request random nonce, unknown/duplicate ids mean HARNESS_TAMPER; and forging gains nothing because comparison is outside | `sandbox/runner.py::parse_responses` | unit test (Phase 2) |

## Buyer attacks

| ID | Attack | Defence | Code |
|---|---|---|---|
| B1 | Impossible tests so nothing is ever paid | Reference solution must pass 100% of hidden tests before funding | `api/routers/jobs.py::validate` (reference runs in the sandbox; generator checked too) · `test_api_jobs.py` |
| B2 | Tests not implied by the spec | AI spec check per test; flagged tests block funding until fixed; worker sees which tests were excluded after the verdict | `judge/spec_check.py`, run in `api/routers/jobs.py::validate`; buyer text fenced as untrusted · `test_spec_check.py` (live: 20/20 bench tests fair, planted unfair test caught) |
| B3 | Change tests after seeing the code | Suite sealed by SHA-256 at funding; hash shown to the worker before accepting; grader refuses mismatches | `grading/suite.py::seal` (tests + examples + reference + generator), sealed in `fund/confirm`, `worker/grading.py` refuses a mismatch · `test_suite_and_oracle.py` |
| B4 | Take the code without paying | Code released only in state `CODE_RELEASED`, reachable only from `PAID` | `core/state_machine.py`; `test_code_only_released_after_payment` |
| B5 | Chargeback after delivery | Evidence auto-submitted via Disputes API; delayed payouts and limits for new buyers; platform loss reserve. **Reduced, not eliminated.** | `paypal/disputes.py` (Phase 5) |
| B6 | Let the hold expire mid-job | Deadline of 48h or less (inside the 3-day honor period); reauthorize once (days 4–29) or milestones | `core/state_machine.py`, beat timers |
| B7 | Generator that produces inputs the spec doesn't cover | Generator accepted only if the reference handles all inputs; generator code visible to the worker after the verdict; appeals go to human review | `grading/fresh_inputs.py` |

## Platform failures

| ID | Failure | Defence |
|---|---|---|
| P1 | AI false positive | AI alone means HUMAN_REVIEW, never VOID (`test_ai_alone_cannot_block`, `test_ai_alone_only_sends_to_a_person`); honest bench submissions reviewed CLEAR live |
| P2 | Flaky tests | Re-run failures; flips excluded from both sides |
| P3 | Double capture or payout on retry | `PayPal-Request-Id` per (job, action) + outbox; spike checks retry idempotency |
| P4 | Naive linear payment | Weighted groups + minimum score (`test_readme_example_honest_worker`) |
| P5 | Regulatory ("escrow") | Called "conditional payment"; production path is PayPal multiparty delayed disbursement |
| P6 | Unclaimed payouts | Payout to `PAYPAL_ID` from Log in with PayPal |
| P7 | Human reviewer overpays | `resolve_review` cannot exceed the deterministic capture; reviewers cannot decide their own jobs (`test_reviewer_cannot_raise_or_send_nonsense`, `test_admin_cannot_review_own_job`) |
| P8 | LLM down or rate-limited | Review: fails safe to HUMAN_REVIEW. Spec check: warns, does not block funding (reference validation still applies) |
| P9 | AI decision read back from the DB as a plain/unknown string pays out | `decide()` coerces to the enum; anything unknown becomes HUMAN_REVIEW | `test_plain_or_unknown_ai_value_never_captures` |
| P10 | Job stuck after PayPal refuses a capture or payout | `CAPTURING → HUMAN_REVIEW`, `PAYING_OUT → PAYOUT_FAILED`, `SUBMITTED → VOIDING` | `test_every_state_can_reach_a_terminal_state` |
| P11 | Two workers move the same job at once | Compare-and-set state update (`UPDATE … WHERE state = :old`) | `db/repo.py`, `test_concurrent_transition_only_one_wins` |
| P8 | Long fresh inputs make partial work earn $0 | Generators produce small inputs (found by the bench, documented in `grading/fresh_inputs.py`) |

## Known limits (say these honestly in the pitch)
- Chargeback risk is reduced, not removed.
- Static rules can be evaded by obfuscation. That's why fresh inputs (behavioural, not textual) carry the main weight against memorization, and the AI plus human review cover the rest.
- Python-only in the MVP.
