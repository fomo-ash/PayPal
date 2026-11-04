"""Job state machine. Every state change in the system goes through `transition()`.

See docs/STATE_MACHINE.md for the diagram, timers and which component owns each step.
In Phase 2 `transition()` is called inside the same DB transaction that writes the
outbox row for any PayPal action the new state requires.
"""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"            # reference solution + spec check running
    INVALID = "INVALID"                  # buyer must fix tests/spec → back to DRAFT
    AWAITING_FUNDS = "AWAITING_FUNDS"    # PayPal order created, waiting for buyer approval
    FUNDED = "FUNDED"                    # authorization exists, suite hash sealed
    OPEN = "OPEN"                        # visible to workers
    CLAIMED = "CLAIMED"                  # one worker accepted, deadline running
    SUBMITTED = "SUBMITTED"
    GRADING = "GRADING"                  # hidden tests + fresh inputs + scanner
    JUDGING = "JUDGING"                  # AI review
    HUMAN_REVIEW = "HUMAN_REVIEW"        # hold kept, waiting for a person
    CAPTURING = "CAPTURING"              # outbox: capture(final_capture=true)
    PAYING_OUT = "PAYING_OUT"            # outbox: payout to worker
    PAID = "PAID"
    CODE_RELEASED = "CODE_RELEASED"      # terminal (success)
    VOIDING = "VOIDING"                  # outbox: void authorization
    VOIDED = "VOIDED"                    # terminal (no payment)
    CANCELLED = "CANCELLED"              # terminal (never funded)


S = JobState

TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    S.DRAFT: frozenset({S.VALIDATING, S.CANCELLED}),
    S.VALIDATING: frozenset({S.AWAITING_FUNDS, S.INVALID}),
    S.INVALID: frozenset({S.DRAFT, S.CANCELLED}),
    S.AWAITING_FUNDS: frozenset({S.FUNDED, S.CANCELLED}),
    S.FUNDED: frozenset({S.OPEN, S.VOIDING}),
    S.OPEN: frozenset({S.CLAIMED, S.VOIDING}),              # buyer withdraws / hold expiring
    S.CLAIMED: frozenset({S.SUBMITTED, S.OPEN, S.VOIDING}),  # deadline missed → OPEN again
    S.SUBMITTED: frozenset({S.GRADING}),
    S.GRADING: frozenset({S.JUDGING, S.VOIDING}),           # hard signal can void immediately
    S.JUDGING: frozenset({S.CAPTURING, S.VOIDING, S.HUMAN_REVIEW}),
    S.HUMAN_REVIEW: frozenset({S.CAPTURING, S.VOIDING}),
    S.CAPTURING: frozenset({S.PAYING_OUT}),
    S.PAYING_OUT: frozenset({S.PAID}),
    S.PAID: frozenset({S.CODE_RELEASED}),
    S.VOIDING: frozenset({S.VOIDED}),
    S.CODE_RELEASED: frozenset(),
    S.VOIDED: frozenset(),
    S.CANCELLED: frozenset(),
}

TERMINAL = frozenset(s for s, nxt in TRANSITIONS.items() if not nxt)

# States in which buyer money is held by a PayPal authorization.
HOLD_ACTIVE = frozenset({
    S.FUNDED, S.OPEN, S.CLAIMED, S.SUBMITTED, S.GRADING, S.JUDGING, S.HUMAN_REVIEW,
    S.CAPTURING, S.VOIDING,
})


class IllegalTransition(Exception):
    def __init__(self, current: JobState, target: JobState):
        super().__init__(f"illegal transition {current} → {target}")
        self.current, self.target = current, target


def can_transition(current: JobState, target: JobState) -> bool:
    return target in TRANSITIONS[current]


def transition(current: JobState, target: JobState) -> JobState:
    if not can_transition(current, target):
        raise IllegalTransition(current, target)
    return target
