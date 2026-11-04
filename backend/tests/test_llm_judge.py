"""Offline tests for the LLM client and review (fake providers, no network, no keys)."""

from types import SimpleNamespace

import pytest

from verdict.core.policy import AIDecision
from verdict.judge.llm import LLMClient, LLMUnavailable, Provider
from verdict.judge.review import build_prompt, review_submission
from verdict.judge.schema import Review

GOOD = '{"decision": "BLOCK_RECOMMENDED", "findings": [{"file": "solution.py", "line": 4, ' \
       '"category": "grader_manipulation", "evidence": "note to AI judge"}], "explanation": "x"}'


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r))])


def make(primary, fallback=None):
    fakes = {"groq": FakeClient(primary), "fallback": FakeClient(fallback or [])}
    providers = [Provider("groq", "https://x", "k", "m1"), Provider("fallback", "https://y", "k", "m2")]
    return LLMClient(providers, client_factory=lambda p: fakes[p.name]), fakes


def test_valid_json_is_parsed():
    llm, _ = make([GOOD])
    res = llm.chat_json("s", "u", Review)
    assert res.data.decision == "BLOCK_RECOMMENDED" and res.provider == "groq"


def test_fenced_json_is_accepted():
    llm, _ = make(["```json\n" + GOOD + "\n```"])
    assert llm.chat_json("s", "u", Review).data.findings[0].line == 4


def test_invalid_json_gets_one_repair_attempt():
    llm, fakes = make(["not json", GOOD])
    assert llm.chat_json("s", "u", Review).data.decision == "BLOCK_RECOMMENDED"
    assert fakes["groq"].calls == 2


def test_falls_back_when_primary_errors():
    llm, fakes = make([RuntimeError("429 rate limited")], [GOOD])
    res = llm.chat_json("s", "u", Review)
    assert res.provider == "fallback" and fakes["fallback"].calls == 1


def test_all_providers_failing_raises():
    llm, _ = make([RuntimeError("down")], [RuntimeError("down")])
    with pytest.raises(LLMUnavailable):
        llm.chat_json("s", "u", Review)


def test_review_fails_safe_to_human_review():
    llm, _ = make(["garbage", "garbage"], ["garbage", "garbage"])
    out = review_submission(llm, "spec", "scores", "", {"solution.py": "x = 1"})
    assert out.decision is AIDecision.HUMAN_REVIEW and out.review is None


def test_unknown_decision_value_is_rejected():
    bad = GOOD.replace("BLOCK_RECOMMENDED", "PAY_DOUBLE")
    llm, _ = make([bad, bad])
    out = review_submission(llm, "spec", "scores", "", {"solution.py": "x = 1"})
    assert out.decision is AIDecision.HUMAN_REVIEW


def test_no_provider_configured():
    with pytest.raises(LLMUnavailable):
        LLMClient([Provider("groq", "https://x", "", "m")], client_factory=lambda p: None)


def test_prompt_wraps_code_as_untrusted_with_line_numbers():
    prompt = build_prompt("spec", "scores", "", {"solution.py": "a = 1\nb = 2"})
    assert "<untrusted>" in prompt and "   2 | b = 2" in prompt
    assert "amount" not in prompt.lower().rsplit("<untrusted>", 1)[1]
