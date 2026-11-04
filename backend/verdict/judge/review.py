"""AI cheating review.

Input: spec, deterministic results, scanner findings, and the submitted code with line numbers
(wrapped as untrusted data). Output: judge.schema.Review. The only thing the rest of the system
uses is the AIDecision enum (verdict.core.policy) plus the cited findings for the verdict page.

Safety:
  * The AI never sees or returns an amount.
  * If the LLM is unavailable or returns garbage, the decision is HUMAN_REVIEW (fail safe).
  * Code is truncated to fit the free-tier token budget (Groq gpt-oss-120b: ~8K tokens/min).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from verdict.core.policy import AIDecision
from verdict.judge.llm import LLMClient, LLMUnavailable
from verdict.judge.schema import Review

PROMPT = (Path(__file__).parent / "prompts" / "review.md").read_text()
SYSTEM = ("You are a careful code-integrity reviewer. You output exactly one JSON object and "
          "nothing else.")
MAX_CODE_CHARS = 12_000   # ≈ 3-4K tokens, leaves room for the rest under an 8K TPM limit


@dataclass(frozen=True)
class ReviewOutcome:
    decision: AIDecision
    review: Review | None
    provider: str | None
    error: str | None = None


def number_lines(code: str) -> str:
    return "\n".join(f"{i:>4} | {line}" for i, line in enumerate(code.splitlines(), 1))


def build_prompt(spec: str, scores: str, findings: str, files: dict[str, str]) -> str:
    parts, budget = [], MAX_CODE_CHARS
    for name, code in files.items():
        block = f"--- file: {name} ---\n{number_lines(code)}"
        if len(block) > budget:
            block = block[:budget] + "\n[... truncated ...]"
        parts.append(block)
        budget -= len(block)
        if budget <= 0:
            break
    return PROMPT.format(spec=spec.strip(), scores=scores.strip(),
                         findings=findings.strip() or "none",
                         code_with_line_numbers="\n\n".join(parts))


def review_submission(llm: LLMClient, spec: str, scores: str, findings: str,
                      files: dict[str, str]) -> ReviewOutcome:
    try:
        res = llm.chat_json(SYSTEM, build_prompt(spec, scores, findings, files), Review)
    except LLMUnavailable as exc:
        return ReviewOutcome(AIDecision.HUMAN_REVIEW, None, None, str(exc))
    review: Review = res.data  # type: ignore[assignment]
    return ReviewOutcome(AIDecision(review.decision), review, res.provider)
