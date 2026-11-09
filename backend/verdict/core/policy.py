"""Policy engine: turns deterministic results + the AI's opinion into ONE settlement decision.

Hard rules (README "Design rules"):
  * The AI's input is an enum. It never supplies an amount, so it cannot raise a payment.
  * The AI cannot block on its own: BLOCK needs at least one deterministic hard signal.
  * A hard signal always wins, even if the AI says CLEAR.
  * A human reviewer may lower the amount or void, never raise it above the deterministic capture.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from verdict.core.scoring import CENT, ZERO, Payout


class AIDecision(StrEnum):
    CLEAR = "CLEAR"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    BLOCK_RECOMMENDED = "BLOCK_RECOMMENDED"


class Settlement(StrEnum):
    CAPTURE = "CAPTURE"            # capture payout.capture, release the rest, pay the worker
    VOID = "VOID"                  # void the whole authorization; the buyer pays nothing
    HUMAN_REVIEW = "HUMAN_REVIEW"  # keep the hold, queue for a person


class HardSignal(StrEnum):
    """Deterministic evidence of cheating, produced by the scanner/grader, never by the AI."""

    REJECTED_FILE = "REJECTED_FILE"                  # conftest.py, sitecustomize, .pth, ...
    HARNESS_TAMPER = "HARNESS_TAMPER"                # protocol violation / nonce mismatch
    HIDDEN_TEST_ACCESS = "HIDDEN_TEST_ACCESS"        # tried to read files outside its workspace
    GRADER_INJECTION = "GRADER_INJECTION"            # text addressed to an AI/grader/judge
    SANDBOX_ESCAPE_ATTEMPT = "SANDBOX_ESCAPE_ATTEMPT"
    NETWORK_ATTEMPT = "NETWORK_ATTEMPT"


@dataclass(frozen=True)
class PolicyResult:
    settlement: Settlement
    capture: Decimal          # 0 for VOID; the held maximum for HUMAN_REVIEW
    reason: str


def _as_ai_decision(ai: object) -> AIDecision:
    """DB values arrive as plain strings. Anything unknown fails SAFE (human review)."""
    try:
        return AIDecision(str(ai)) if isinstance(ai, str) else AIDecision.HUMAN_REVIEW
    except ValueError:
        return AIDecision.HUMAN_REVIEW


def decide(payout: Payout, hard_signals: list[HardSignal], ai: AIDecision) -> PolicyResult:
    ai = _as_ai_decision(ai)
    hard_signals = [HardSignal(s) for s in hard_signals]
    if hard_signals:
        names = ", ".join(sorted(s.value for s in set(hard_signals)))
        return PolicyResult(Settlement.VOID, ZERO, f"hard signal(s): {names}")
    if payout.capture == ZERO:
        return PolicyResult(Settlement.VOID, ZERO, "score below minimum or zero")
    if ai is AIDecision.BLOCK_RECOMMENDED:
        return PolicyResult(
            Settlement.HUMAN_REVIEW, payout.capture,
            "AI recommended block without a deterministic signal; human must decide",
        )
    if ai is AIDecision.HUMAN_REVIEW:
        return PolicyResult(Settlement.HUMAN_REVIEW, payout.capture, "AI requested human review")
    return PolicyResult(Settlement.CAPTURE, payout.capture, "clear")


class ReviewError(ValueError):
    pass


def resolve_review(max_capture: Decimal, reviewer_capture: Decimal | str) -> PolicyResult:
    """A human reviewer's final call. They may lower the amount or void, never raise it above
    max_capture (the deterministic capture stored on the verdict)."""
    if isinstance(reviewer_capture, float):
        raise ReviewError("capture must be Decimal or str, not float")
    try:
        amount = Decimal(str(reviewer_capture))
    except InvalidOperation as exc:
        raise ReviewError(f"not a number: {reviewer_capture!r}") from exc
    if not amount.is_finite() or amount != amount.quantize(CENT):
        raise ReviewError("capture must be a finite amount with at most 2 decimals")
    if amount < ZERO:
        raise ReviewError("capture cannot be negative")
    if amount > max_capture:
        raise ReviewError(f"reviewer cannot raise payment above {max_capture}")
    if amount == ZERO:
        return PolicyResult(Settlement.VOID, ZERO, "voided by human reviewer")
    return PolicyResult(Settlement.CAPTURE, amount, "approved by human reviewer")
