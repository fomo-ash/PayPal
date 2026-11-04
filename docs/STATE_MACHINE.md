# Job state machine

Source of truth: `backend/verdict/core/state_machine.py` (tested in `backend/tests/test_state_machine.py`).

```
DRAFT ──► VALIDATING ──► AWAITING_FUNDS ──► FUNDED ──► OPEN ──► CLAIMED ──► SUBMITTED ──► GRADING ──► JUDGING
  │            │                │              │         │  ▲       │                          │           │
  ▼            ▼                ▼              │         │  └───────┘ deadline missed          │           ├──► CAPTURING ──► PAYING_OUT ──► PAID ──► CODE_RELEASED ✔
CANCELLED   INVALID ──► DRAFT  CANCELLED       │         │                                     │           ├──► HUMAN_REVIEW ──► CAPTURING / VOIDING
                                               └─────────┴──────────► VOIDING ◄──────────────────┘           └──► VOIDING ──► VOIDED ✔
                                              (buyer withdraws / hold expiring / hard signal / zero score)

Failure exits:  SUBMITTED ──► VOIDING          (hold expiring while grading is unavailable)
                CAPTURING ──► HUMAN_REVIEW     (PayPal refused the capture)
                PAYING_OUT ──► PAYOUT_FAILED ──► PAYING_OUT   (receiver fixed, payout retried)
```

| State | Hold active? | Entered by | Side effect (via outbox) |
|---|---|---|---|
| DRAFT | no | buyer | none |
| VALIDATING | no | buyer submits suite | run reference, AI spec check |
| INVALID | no | validation failed | report to buyer |
| AWAITING_FUNDS | no | validation passed | create PayPal order (AUTHORIZE) |
| FUNDED | **yes** | authorization succeeded | seal suite hash |
| OPEN | yes | after sealing | visible to workers |
| CLAIMED | yes | worker accepts | deadline timer (≤ 48h) |
| SUBMITTED / GRADING / JUDGING | yes | worker submits | grading + AI tasks |
| HUMAN_REVIEW | yes | policy | notify reviewer |
| CAPTURING | yes | policy CAPTURE | `capture(amount, final_capture=true)` |
| PAYING_OUT | no | capture completed | `payouts(worker, amount − fee)` |
| PAYOUT_FAILED | no | payout refused / returned | admin alert; retry after the receiver is fixed |
| PAID | no | payout succeeded | build signed receipt |
| CODE_RELEASED | no | receipt done | buyer can download code |
| VOIDING | yes | policy VOID / withdraw / expiry | `void(authorization)` |
| VOIDED | no | void succeeded | receipt for both sides |

## Timers (Celery Beat)
- **Claim deadline:** CLAIMED past its deadline goes back to OPEN (the worker gets nothing; the job can be re-claimed while the hold is valid).
- **Honor period:** PayPal guarantees funds for 3 days after authorization; the authorization is valid for 29 days. At day ~2.5, a job still OPEN is VOIDED (MVP). Reauthorization is a Phase 5+ option.
- **Outbox sweeper:** every 30s, retry outbox rows that are not done.

## Invariants (tested)
- `CODE_RELEASED` is reachable only from `PAID`.
- Every state (not only those with a hold) can reach a terminal state: no job can get stuck.
- `transition()` accepts plain strings from the DB, returns a `JobState`, and treats unknown names as illegal.
- No path goes from SUBMITTED to CAPTURING without GRADING and JUDGING.
- Every state with an active hold can reach a terminal state.

## Concurrency (Phase 2)
`transition()` only validates a move. The database write is a compare-and-set, so two workers
can never both move the same job:
```sql
UPDATE jobs SET state = :new WHERE id = :id AND state = :old   -- 0 rows → someone else moved it
```
Implemented in `backend/verdict/db/repo.py`.
