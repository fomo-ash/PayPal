"""Deterministic payout maths. The ONLY place money amounts are computed.

Rules (see README §3):
    rate_g   = hidden pass rate of group g (flaky tests excluded)
               if the group has fresh inputs: min(hidden rate, fresh rate)
    score    = Σ weight_g × rate_g
    score    = 0 if score < min_score
    capture  = floor_to_cents(amount × score)
    fee      = round_half_up(capture × fee_bps / 10_000)
    worker   = capture − fee
    released = amount − capture

All money uses Decimal. Floats are rejected so rounding can't drift.
The AI judge never calls this module and never supplies an amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ONE = Decimal(1)
ZERO = Decimal(0)


class ScoringError(ValueError):
    """Raised for invalid job configuration or results."""


@dataclass(frozen=True)
class GroupResult:
    """Results for one weighted test group.

    passed/total count hidden tests with flaky tests already removed from BOTH sides.
    fresh_passed/fresh_total are set only for groups that use fresh random inputs.
    """

    name: str
    weight: Decimal
    passed: int
    total: int
    fresh_passed: int | None = None
    fresh_total: int | None = None

    def hidden_rate(self) -> Decimal:
        if self.total <= 0:
            raise ScoringError(f"group {self.name!r} has no non-flaky tests")
        if not 0 <= self.passed <= self.total:
            raise ScoringError(f"group {self.name!r}: passed out of range")
        return Decimal(self.passed) / Decimal(self.total)

    def fresh_rate(self) -> Decimal | None:
        if self.fresh_total is None:
            return None
        if self.fresh_total <= 0 or self.fresh_passed is None:
            raise ScoringError(f"group {self.name!r}: invalid fresh-input counts")
        if not 0 <= self.fresh_passed <= self.fresh_total:
            raise ScoringError(f"group {self.name!r}: fresh_passed out of range")
        return Decimal(self.fresh_passed) / Decimal(self.fresh_total)

    def rate(self) -> Decimal:
        hidden = self.hidden_rate()
        fresh = self.fresh_rate()
        return hidden if fresh is None else min(hidden, fresh)


@dataclass(frozen=True)
class Payout:
    score: Decimal          # 0..1, after the minimum-score rule
    raw_score: Decimal      # 0..1, before the minimum-score rule
    capture: Decimal        # amount PayPal captures from the authorization
    fee: Decimal            # platform fee taken from the capture
    worker: Decimal         # amount paid out to the worker
    released: Decimal       # amount returned to the buyer (released by final_capture)
    group_rates: dict[str, Decimal]


def _require_decimal(name: str, value: object) -> Decimal:
    if isinstance(value, float):
        raise ScoringError(f"{name} must be Decimal or str, not float")
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise ScoringError(f"{name} is not a number: {value!r}") from exc


def validate_weights(groups: list[GroupResult]) -> None:
    if not groups:
        raise ScoringError("at least one test group is required")
    names = [g.name for g in groups]
    if len(set(names)) != len(names):
        raise ScoringError("group names must be unique")
    for g in groups:
        w = _require_decimal("weight", g.weight)
        if not ZERO < w <= ONE:
            raise ScoringError(f"group {g.name!r}: weight must be in (0, 1]")
    total = sum((_require_decimal("weight", g.weight) for g in groups), ZERO)
    if total != ONE:
        raise ScoringError(f"weights must sum to exactly 1, got {total}")


def compute_payout(
    amount: Decimal | str,
    groups: list[GroupResult],
    min_score: Decimal | str,
    fee_bps: int,
) -> Payout:
    amt = _require_decimal("amount", amount)
    if amt <= ZERO or amt != amt.quantize(CENT):
        raise ScoringError("amount must be positive with at most 2 decimals")
    min_s = _require_decimal("min_score", min_score)
    if not ZERO <= min_s <= ONE:
        raise ScoringError("min_score must be in [0, 1]")
    if not isinstance(fee_bps, int) or not 0 <= fee_bps <= 10_000:
        raise ScoringError("fee_bps must be an int in [0, 10000]")
    validate_weights(groups)

    rates = {g.name: g.rate() for g in groups}
    raw = sum((Decimal(str(g.weight)) * rates[g.name] for g in groups), ZERO)
    raw = min(max(raw, ZERO), ONE)
    score = raw if raw >= min_s else ZERO

    capture = (amt * score).quantize(CENT, rounding=ROUND_DOWN)
    fee = (capture * Decimal(fee_bps) / Decimal(10_000)).quantize(CENT, rounding=ROUND_HALF_UP)
    worker = capture - fee
    released = amt - capture

    # Explicit checks, not `assert`: asserts disappear under `python -O`.
    if not ZERO <= capture <= amt:
        raise ScoringError(f"invariant broken: capture {capture} outside [0, {amt}]")
    if worker < ZERO or capture + released != amt:
        raise ScoringError("invariant broken: amounts do not reconcile")
    return Payout(score, raw, capture, fee, worker, released, rates)
