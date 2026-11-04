# Job state machine

Source of truth: `backend/verdict/core/state_machine.py` (tested in `backend/tests/test_state_machine.py`).

```
DRAFT ──► VALIDATING ──► AWAITING_FUNDS ──► FUNDED ──► OPEN ──► CLAIMED ──► SUBMITTED ──► GRADING ──► JUDGING
  │            │                │              │         │  ▲       │                          │           │
  ▼            ▼                ▼              │         │  └───────┘ deadline missed          │           ├──► CAPTURING ──► PAYING_OUT ──► PAID ──► CODE_RELEASED ✔
CANCELLED   INVALID ──► DRAFT  CANCELLED       │         │                                     │           ├──► HUMAN_REVIEW ──► CAPTURING / VOIDING
                                               └─────────┴──────────► VOIDING ◄──────────────────┘           └──► VOIDING ──► VOIDED ✔
                                              (buyer withdraws / hold expiring / hard signal / zero score)
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
- No path goes from SUBMITTED to CAPTURING without GRADING and JUDGING.
- Every state with an active hold can reach a terminal state.
