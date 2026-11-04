import pytest

from verdict.core.state_machine import (
    HOLD_ACTIVE, TERMINAL, TRANSITIONS, IllegalTransition, JobState as S, transition,
)

HAPPY_PATH = [S.DRAFT, S.VALIDATING, S.AWAITING_FUNDS, S.FUNDED, S.OPEN, S.CLAIMED,
              S.SUBMITTED, S.GRADING, S.JUDGING, S.CAPTURING, S.PAYING_OUT, S.PAID,
              S.CODE_RELEASED]


def test_happy_path():
    state = HAPPY_PATH[0]
    for nxt in HAPPY_PATH[1:]:
        state = transition(state, nxt)
    assert state in TERMINAL


def test_cannot_capture_before_grading():
    with pytest.raises(IllegalTransition):
        transition(S.SUBMITTED, S.CAPTURING)


def test_cannot_pay_out_before_capture():
    with pytest.raises(IllegalTransition):
        transition(S.JUDGING, S.PAYING_OUT)


def test_code_only_released_after_payment():
    sources = [s for s, nxt in TRANSITIONS.items() if S.CODE_RELEASED in nxt]
    assert sources == [S.PAID]


def test_every_state_with_a_hold_can_reach_a_terminal_state():
    for start in HOLD_ACTIVE:
        seen, frontier = {start}, [start]
        while frontier:
            for n in TRANSITIONS[frontier.pop()]:
                if n not in seen:
                    seen.add(n)
                    frontier.append(n)
        assert seen & {S.VOIDED, S.CODE_RELEASED}, start


def test_every_state_is_defined():
    assert set(TRANSITIONS) == set(S)
