# Data model (Postgres 16)

Money: `NUMERIC(12,2)`, never float. Timestamps: `timestamptz`. IDs: UUID v7 (time-ordered).

```sql
users           (id, paypal_payer_id UNIQUE, email, display_name, role[buyer|worker|admin], created_at)
agents          (id, owner_user_id → users, name, api_key_hash, created_at)          -- every agent has an accountable human

jobs            (id, buyer_id → users, title, spec_md, amount, currency, min_score NUMERIC(5,4),
                 fee_bps INT, deadline_hours INT, state, suite_sha256,
                 paypal_order_id, authorization_id, authorized_at, honor_expires_at, created_at)
test_groups     (id, job_id → jobs, name, weight NUMERIC(5,4), n_tests, fresh_count)
suites          (job_id PK → jobs, r2_key, sha256, reference_key, generator_key, validated_at)
spec_checks     (id, job_id, test_id, implied BOOL, reason)

claims          (id, job_id, worker_id → users, agent_id → agents NULL, accepted_at, deadline_at, status)
submissions     (id, claim_id → claims, r2_key, sha256, submitted_at)          -- UNIQUE(job_id, worker payer_id)
runs            (id, submission_id, kind[examples|hidden|fresh], group_name, passed, total, flaky_ids JSONB, details JSONB)
scan_findings   (id, submission_id, rule, file, line, message, hard_signal NULL)
ai_reviews      (id, submission_id, model, decision, findings JSONB, explanation, langfuse_trace_id, created_at)
verdicts        (submission_id PK, raw_score, score, capture, fee, worker_amount, released,
                 settlement[CAPTURE|VOID|HUMAN_REVIEW], policy_reason, decided_by[policy|human], decided_at)

outbox          (id, job_id, action[authorize|capture|void|payout|reauthorize], idempotency_key UNIQUE,
                 payload JSONB, status[pending|done|failed], attempts, last_error, created_at, done_at)
paypal_events   (id PK = PayPal event id, type, resource_id, raw JSONB, verified BOOL, received_at)

ledger_entries  (id, job_id, account, debit, credit, ref, created_at)       -- Σdebit = Σcredit per ref
audit_log       (id, job_id, event, payload JSONB, prev_hash, hash, created_at)
receipts        (job_id PK, json_key, pdf_key, signature, public_key_id, issued_at)
```

## Ledger accounts and postings ($100 job, 81.5% score, 5% fee)

| Event | Debit | Credit | Amount |
|---|---|---|---|
| Capture | platform_clearing | worker_payable | 77.42 |
| | | platform_fee | 4.08 |
| Release (final_capture) | buyer_hold | released | 18.50 |
| Payout | worker_payable | platform_clearing | 77.42 |

Invariant: for a job in a terminal state, `worker_payable` nets to 0.
