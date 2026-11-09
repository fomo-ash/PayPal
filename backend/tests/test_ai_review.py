"""AI review inside grading: it can send a paying result to a person, never raise or block."""

import uuid

import pytest
from conftest import FakeLLM

from verdict.db.models import AIReview, Verdict
from verdict.judge.llm import LLMUnavailable
from verdict.sandbox.runner import LocalRunner
from verdict.worker import grading


def says(decision, findings=()):
    return FakeLLM(lambda prompt, schema: {
        "decision": decision, "explanation": f"model says {decision}",
        "findings": [{"file": "solution.py", "line": 3, "category": "other", "evidence": e}
                     for e in findings]})


def down(prompt, schema):
    raise LLMUnavailable("groq: 429; fallback: 503")


def grade(api, sub_id, llm):
    return grading.grade_submission(api.services.Session, api.services.store, LocalRunner(),
                                    uuid.UUID(sub_id), llm=llm)


def stored(Session, sub_id):  # noqa: N803
    with Session() as s:
        return (s.query(AIReview).filter_by(submission_id=uuid.UUID(sub_id)).one_or_none(),
                s.get(Verdict, uuid.UUID(sub_id)))


def test_clear_keeps_the_capture(api, submitted, Session):
    buyer, _, _, sub_id = submitted("honest_full")
    assert grade(api, sub_id, says("CLEAR")).state == "CAPTURING"
    review, verdict = stored(Session, sub_id)
    assert review.decision == "CLEAR" and review.model == "fake-model"
    assert verdict.settlement == "CAPTURE" and verdict.capture == 100
    view = api.get(f"/submissions/{sub_id}", headers=buyer).json()
    assert view["ai_review"]["decision"] == "CLEAR"


@pytest.mark.parametrize("decision", ["BLOCK_RECOMMENDED", "HUMAN_REVIEW"])
def test_ai_alone_only_sends_to_a_person(api, submitted, Session, decision):
    buyer, _, _, sub_id = submitted("honest_full")
    llm = says(decision, findings=["looks hard-coded"])
    assert grade(api, sub_id, llm).state == "HUMAN_REVIEW"
    review, verdict = stored(Session, sub_id)
    assert verdict.settlement == "HUMAN_REVIEW" and verdict.capture == 100   # cap, not paid
    view = api.get(f"/submissions/{sub_id}", headers=buyer).json()
    assert view["ai_review"]["findings"][0] == {
        "file": "solution.py", "line": 3, "category": "other", "evidence": "looks hard-coded"}


def test_ai_down_fails_safe_to_a_person(api, submitted, Session):
    _, _, _, sub_id = submitted("honest_full")
    assert grade(api, sub_id, FakeLLM(down)).state == "HUMAN_REVIEW"
    review, _ = stored(Session, sub_id)
    assert review.decision == "HUMAN_REVIEW" and review.model == "unavailable"
    assert "unavailable" in review.explanation


@pytest.mark.parametrize("name", ["cheat_memorizer", "cheat_injection"])
def test_ai_is_not_asked_when_the_result_is_already_void(api, submitted, Session, name):
    _, _, _, sub_id = submitted(name)
    llm = says("CLEAR")
    assert grade(api, sub_id, llm).state == "VOIDING"
    assert llm.prompts == [] and stored(Session, sub_id)[0] is None


def test_no_llm_configured_skips_the_review(api, submitted, Session):
    buyer, _, _, sub_id = submitted("honest_full")
    assert grade(api, sub_id, None).state == "CAPTURING"
    assert api.get(f"/submissions/{sub_id}", headers=buyer).json()["ai_review"] is None


def test_prompt_has_scores_and_code_but_no_money(api, submitted):
    _, _, _, sub_id = submitted("honest_partial")
    llm = says("CLEAR")
    grade(api, sub_id, llm)
    prompt = llm.prompts[0]
    assert "hidden core:" in prompt and "fresh core:" in prompt
    assert "   1 | " in prompt                                    # line-numbered code
    assert "100.00" not in prompt and "$" not in prompt.split("<untrusted>")[0]
