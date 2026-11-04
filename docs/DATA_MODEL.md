# Data model (Postgres 16)

Source of truth: `backend/verdict/db/models.py`; migration `backend/migrations/versions/0001_initial_schema.py`
(`make migrate`). A test checks the migration matches the models exactly.

Money: `NUMERIC(12,2)`, never float. Timestamps: `timestamptz`. IDs: UUID v7 (time-ordered).
Unit tests run the same models on in-memory SQLite; set `TEST_DATABASE_URL` to run them on Postgres.

```sql
users           (id, paypal_payer_id UNIQUE, email, display_name, role[buyer|worker|admin], created_at)
agents          (id, owner_user_id → users, name, api_key_hash, created_at)          -- every agent has an accountable human

jobs            (id, buyer_id → users, title, spec_md, amount, currency, min_score NUMERIC(5,4),
                 fee_bps INT, deadline_hours INT, state, suite_sha256,
                 paypal_order_id, authorization_id UNIQUE, authorized_at, honor_expires_at,
                 capture_id, payout_batch_id, created_at)
test_groups     (id, job_id → jobs, name, weight NUMERIC(5,4), n_tests, fresh_count)
suites          (job_id PK → jobs, r2_key, sha256, reference_key, generator_key, validated_at)
spec_checks     (id, job_id, test_id, implied BOOL, reason)

claims          (id, job_id, worker_id → users, agent_id → agents NULL, accepted_at, deadline_at, status)
submissions     (id, claim_id → claims, job_id, worker_id, r2_key, sha256, grading_seed, submitted_at)
                                                                     -- UNIQUE(job_id, worker_id)
runs            (id, submission_id, kind[examples|hidden|fresh], group_name, passed, total, flaky_ids JSONB, details JSONB)
scan_findings   (id, submission_id, rule, file, line, message, hard_signal NULL)
ai_reviews      (id, submission_id, model, decision, findings JSONB, explanation, langfuse_trace_id, created_at)
verdicts        (submission_id PK, job_id UNIQUE, raw_score, score, capture, fee, worker_amount, released,
                 settlement[CAPTURE|VOID|HUMAN_REVIEW], policy_reason, decided_by[policy|human], decided_at)

outbox          (id, job_id, action[capture|void|payout|payout_status|reauthorize], idempotency_key UNIQUE,
                 payload JSONB, status[pending|done|failed], attempts, next_attempt_at, last_error,
                 response JSONB, created_at, done_at)
paypal_events   (id PK = PayPal event id, type, resource_id, raw JSONB, verified BOOL, received_at)

ledger_entries  (id, job_id, account, debit, credit, ref, created_at)       -- Σdebit = Σcredit per ref
audit_log       (id, job_id, seq, event, payload JSONB, prev_hash, hash, created_at)   -- UNIQUE(job_id, seq)
receipts        (job_id PK, json_key, pdf_key, signature, public_key_id, issued_at)
```

## Ledger accounts and postings ($100 job, 81.5% score, 5% fee)

Code: `backend/verdict/core/ledger.py`. Every posting is balanced; re-posting the same `ref` is a no-op.

| Event | Debit | Credit | Amount |
|---|---|---|---|
| Authorize | hold_memo | buyer_commitment | 100.00 |
| Capture | buyer_commitment | hold_memo | 81.50 |
| | paypal_cash 81.50 | worker_payable 77.42, platform_fee 4.08 | |
| Release (final_capture) | buyer_commitment | hold_memo | 18.50 |
| Payout | worker_payable | paypal_cash | 77.42 |
| Void (instead of capture) | buyer_commitment | hold_memo | 100.00 |

Invariants for a finished job (tested): `hold_memo = buyer_commitment = worker_payable = 0`, and
`paypal_cash = platform_fee` = the fee Verdict kept. A failed payout leaves `worker_payable` showing
exactly what is still owed to the worker.
