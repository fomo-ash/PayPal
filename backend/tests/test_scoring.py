from decimal import Decimal as D

import pytest

from verdict.core.scoring import GroupResult, ScoringError, compute_payout


def readme_groups(core_hidden=9, core_fresh=196, edge=4, perf=2):
    return [
        GroupResult("core", D("0.60"), core_hidden, 10, fresh_passed=core_fresh, fresh_total=200),
        GroupResult("edge", D("0.25"), edge, 8),
        GroupResult("perf", D("0.15"), perf, 2),
    ]


def test_readme_example_honest_worker():
    p = compute_payout("100.00", readme_groups(), "0.50", fee_bps=500)
    assert p.score == D("0.815")
    assert p.capture == D("81.50")
    assert p.released == D("18.50")
    assert p.fee == D("4.08")          # 4.075 rounds half-up
    assert p.worker == D("77.42")
    assert p.group_rates["core"] == D("0.9")   # min(9/10, 196/200)


def test_memorizer_is_capped_by_fresh_inputs():
    # 10/10 hidden, but only 23/200 fresh → core rate 0.115, total below minimum
    p = compute_payout("100.00", readme_groups(core_hidden=10, core_fresh=23, edge=0, perf=0),
                       "0.50", fee_bps=500)
    assert p.group_rates["core"] == D("0.115")
    assert p.raw_score < D("0.50")
    assert p.capture == D("0.00") and p.released == D("100.00") and p.worker == D("0.00")


def test_perfect_score_captures_everything():
    p = compute_payout("100.00", readme_groups(10, 200, 8, 2), "0.50", fee_bps=500)
    assert p.capture == D("100.00") and p.released == D("0.00")
    assert p.worker == D("95.00")


def test_capture_rounds_down_never_overcharges():
    groups = [GroupResult("all", D("1"), 1, 3)]          # 33.33...%
    p = compute_payout("10.00", groups, "0", fee_bps=0)
    assert p.capture == D("3.33")
    assert p.capture + p.released == D("10.00")


def test_score_exactly_at_minimum_is_paid():
    groups = [GroupResult("all", D("1"), 1, 2)]
    assert compute_payout("50.00", groups, "0.5", 0).capture == D("25.00")


@pytest.mark.parametrize("bad", [
    dict(amount=10.0),                      # float money rejected
    dict(amount="0"),
    dict(amount="1.001"),
    dict(min_score="1.5"),
    dict(fee_bps=20_000),
])
def test_rejects_bad_config(bad):
    args = dict(amount="10.00", groups=[GroupResult("a", D("1"), 1, 1)], min_score="0", fee_bps=0)
    args.update(bad)
    with pytest.raises(ScoringError):
        compute_payout(**args)


def test_weights_must_sum_to_one():
    groups = [GroupResult("a", D("0.5"), 1, 1), GroupResult("b", D("0.4"), 1, 1)]
    with pytest.raises(ScoringError):
        compute_payout("10.00", groups, "0", 0)


def test_group_without_tests_is_rejected():
    with pytest.raises(ScoringError):
        compute_payout("10.00", [GroupResult("a", D("1"), 0, 0)], "0", 0)


def test_invariants_are_checked_without_assert():
    import inspect

    from verdict.core import scoring
    assert "assert " not in inspect.getsource(scoring.compute_payout)
