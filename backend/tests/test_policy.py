from decimal import Decimal as D
import inspect

import pytest

from verdict.core import policy
from verdict.core.policy import AIDecision, HardSignal, ReviewError, Settlement, decide, resolve_review
from verdict.core.scoring import GroupResult, compute_payout


def payout(passed=8, total=10):
    return compute_payout("100.00", [GroupResult("all", D("1"), passed, total)], "0.5", 500)


def test_clear_captures_deterministic_amount():
    r = decide(payout(), [], AIDecision.CLEAR)
    assert r.settlement is Settlement.CAPTURE and r.capture == D("80.00")


def test_hard_signal_voids_even_if_ai_says_clear():
    r = decide(payout(), [HardSignal.GRADER_INJECTION], AIDecision.CLEAR)
    assert r.settlement is Settlement.VOID and r.capture == 0


def test_ai_alone_cannot_block():
    r = decide(payout(), [], AIDecision.BLOCK_RECOMMENDED)
    assert r.settlement is Settlement.HUMAN_REVIEW
    assert r.capture == D("80.00")          # hold kept at the deterministic maximum


def test_zero_score_voids():
    r = decide(payout(passed=1), [], AIDecision.CLEAR)
    assert r.settlement is Settlement.VOID


def test_ai_has_no_way_to_supply_an_amount():
    params = inspect.signature(decide).parameters
    assert list(params) == ["payout", "hard_signals", "ai"]
    assert set(AIDecision) == {AIDecision.CLEAR, AIDecision.HUMAN_REVIEW, AIDecision.BLOCK_RECOMMENDED}
    assert "amount" not in inspect.getsource(policy.AIDecision)


def test_reviewer_cannot_raise_payment():
    with pytest.raises(ReviewError):
        resolve_review(payout(), "80.01")


def test_reviewer_can_lower_or_void():
    assert resolve_review(payout(), "50.00").capture == D("50.00")
    assert resolve_review(payout(), "0").settlement is Settlement.VOID


@pytest.mark.parametrize("raw", ["BLOCK_RECOMMENDED", "HUMAN_REVIEW", "BLOCK", "", None, "clear"])
def test_plain_or_unknown_ai_value_never_captures(raw):
    # Values come back from the DB as strings; anything not exactly CLEAR must not pay.
    assert decide(payout(), [], raw).settlement is Settlement.HUMAN_REVIEW


def test_plain_string_clear_still_captures():
    assert decide(payout(), [], "CLEAR").settlement is Settlement.CAPTURE


def test_hard_signal_as_plain_string_voids():
    assert decide(payout(), ["NETWORK_ATTEMPT"], "CLEAR").settlement is Settlement.VOID


@pytest.mark.parametrize("bad", ["50.005", "NaN", "Infinity", "abc", 50.0])
def test_reviewer_amount_must_be_exact_cents(bad):
    with pytest.raises(ReviewError):
        resolve_review(payout(), bad)
