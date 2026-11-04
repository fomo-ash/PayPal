"""Smoke test for the free LLM judge: reviews two bench submissions with the real model.

Run:  python scripts/llm_smoke.py
Needs in .env: LLM_API_KEY (Groq). Optional: LLM_FALLBACK_API_KEY (Gemini).
Keys are never printed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from verdict.config import Settings  # noqa: E402
from verdict.judge.llm import LLMUnavailable, client_from_settings  # noqa: E402
from verdict.judge.review import review_submission  # noqa: E402
from verdict.scanner.ast_rules import scan_source  # noqa: E402

TASK = ROOT / "bench" / "tasks" / "log_parser"
CASES = {
    "honest_full": "hidden core 10/10, edge 8/8, perf 2/2; fresh core 200/200",
    "cheat_injection": "hidden core 2/10, edge 1/8, perf 0/2; fresh core 31/200",
}


def main() -> int:
    settings = Settings(_env_file=ROOT / ".env")
    try:
        llm = client_from_settings(settings)
    except LLMUnavailable as e:
        print(f"Not configured: {e}")
        return 2
    print("providers:", ", ".join(f"{p.name}={p.model}" for p in llm.providers))
    spec = (TASK / "spec.md").read_text()
    for i, (name, scores) in enumerate(CASES.items()):
        if i:
            time.sleep(10)   # stay under the free-tier tokens-per-minute limit
        code = (TASK / "submissions" / name / "solution.py").read_text()
        findings = "\n".join(f"{f.file}:{f.line} {f.rule} ({'HARD' if f.hard else 'soft'}): "
                             f"{f.message}" for f in scan_source(code))
        start = time.time()
        out = review_submission(llm, spec, scores, findings, {"solution.py": code})
        print(f"\n== {name}  ({time.time() - start:.1f}s, provider={out.provider})")
        print(f"decision: {out.decision.value}")
        if out.error:
            print(f"error: {out.error[:500]}")
        if out.review:
            for f in out.review.findings:
                print(f"  - {f.file}:{f.line} [{f.category.value}] {f.evidence}")
            print(f"explanation: {out.review.explanation}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
