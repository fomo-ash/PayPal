"""Buyer-side fairness check at validation time, closing loophole B2 (unfair hidden tests).

For each hidden test the judge model answers: "does this input → output follow from the spec
and the public examples alone?" Any test marked not implied sends the job to INVALID with
the model's reason, so the buyer must fix the spec or drop the test before funding.

Long inputs are clipped (the free tier allows ~8K tokens/min); tests are sent in batches.
If the LLM is unavailable the check is reported as skipped. Funding is not blocked in that
case: the reference-solution validation still applies, and the job page shows it unchecked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verdict.judge.llm import LLMClient, LLMUnavailable, untrusted
from verdict.judge.schema import SpecCheck, SpecCheckItem

PROMPT = (Path(__file__).parent / "prompts" / "spec_check.md").read_text()
SYSTEM = ("You are a strict fairness checker for programming test suites. You output exactly "
          "one JSON object and nothing else.")
CLIP = 300                  # chars kept from each test input / expected output
BATCH_CHARS = 9_000         # rough per-call budget for the tests block


@dataclass
class SpecCheckOutcome:
    items: list[SpecCheckItem] = field(default_factory=list)
    error: str | None = None             # set when the check could not run (LLM down)
    model: str | None = None

    @property
    def unfair(self) -> list[SpecCheckItem]:
        return [i for i in self.items if not i.implied_by_spec]


def clip(text: str, n: int = CLIP) -> str:
    return text if len(text) <= n else f"{text[:n]}[... {len(text) - n} more chars]"


def _batches(tests: list[dict[str, Any]]) -> list[list[dict[str, str]]]:
    out: list[list[dict[str, str]]] = []
    size = 0
    for t in tests:
        row = {"id": t["id"], "input": clip(t["input"]), "expected": clip(t["expected"])}
        n = len(json.dumps(row))
        if not out or size + n > BATCH_CHARS:
            out.append([])
            size = 0
        out[-1].append(row)
        size += n
    return out


def build_prompt(spec: str, examples: list[dict[str, Any]], tests: list[dict[str, str]]) -> str:
    ex = [{"input": clip(e["input"]), "expected": clip(e["expected"])} for e in examples[:10]]
    return PROMPT.format(spec=untrusted(spec.strip()),
                         examples=untrusted(json.dumps(ex, indent=1, ensure_ascii=False)),
                         tests=untrusted(json.dumps(tests, indent=1, ensure_ascii=False)))


def check_spec(llm: LLMClient, spec: str, examples: list[dict[str, Any]],
               tests: list[dict[str, Any]]) -> SpecCheckOutcome:
    out = SpecCheckOutcome()
    for batch in _batches(tests):
        try:
            res = llm.chat_json(SYSTEM, build_prompt(spec, examples, batch), SpecCheck,
                                max_tokens=2500)
        except LLMUnavailable as exc:
            return SpecCheckOutcome(error=str(exc))
        out.model = res.model
        answered = {i.test_id: i for i in res.data.items}  # type: ignore[attr-defined]
        for t in batch:
            # A test the model skipped is not held against the buyer, but it is visible.
            out.items.append(answered.get(t["id"]) or SpecCheckItem(
                test_id=t["id"], implied_by_spec=True, reason="not assessed by the checker"))
    return out
