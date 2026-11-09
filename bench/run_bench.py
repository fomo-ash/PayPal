"""Runs every bench submission through the deterministic grading pipeline and checks the outcome.

LocalRunner (not isolated: bench code only!). The AI judge is stubbed as CLEAR unless --ai is
given, in which case the real judge (LLM key from .env) reviews every submission that would be
paid. Module docstrings label the bench files ("HONEST", "CHEAT"), so they are stripped first.
Run: python bench/run_bench.py [--ai]      (or: make bench / make bench-ai)
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from verdict.core.policy import Settlement, decide  # noqa: E402
from verdict.grading.pipeline import Suite, grade  # noqa: E402
from verdict.sandbox.runner import LocalRunner  # noqa: E402
from verdict.worker.grading import ai_review  # noqa: E402

# submission → expected settlement (and optionally a capture range)
EXPECTED = {
    "honest_full": (Settlement.CAPTURE, Decimal("100.00"), Decimal("100.00")),
    "honest_partial": (Settlement.CAPTURE, Decimal("50.00"), Decimal("99.99")),
    "cheat_memorizer": (Settlement.VOID, None, None),
    "cheat_injection": (Settlement.VOID, None, None),
    "cheat_exit": (Settlement.VOID, None, None),
    "cheat_conftest": (Settlement.VOID, None, None),
    "cheat_env_sniff": (Settlement.VOID, None, None),
    # passes every test; only the AI can see it, and it can only send it to a person
    "cheat_timebomb": (Settlement.CAPTURE, Decimal("100.00"), Decimal("100.00")),
}
AI_EXPECTED = {
    "cheat_timebomb": (Settlement.HUMAN_REVIEW, Decimal("100.00"), Decimal("100.00")),
}


def without_docstring(src: str) -> str:
    body = ast.parse(src).body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        return "\n".join(src.splitlines()[body[0].end_lineno:])
    return src


def code_of(sub: Path) -> dict[str, str]:
    return {p.relative_to(sub).as_posix(): without_docstring(p.read_text())
            for p in sorted(sub.rglob("*.py")) if "__pycache__" not in p.parts}


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    task = ROOT / "bench" / "tasks" / "log_parser"
    raw = json.loads((task / "hidden_tests.json").read_text())
    suite = Suite(groups={g: Decimal(w) for g, w in raw["groups"].items()},
                  fresh=raw["fresh"], min_score=Decimal(raw["min_score"]), tests=raw["tests"])
    llm = None
    if "--ai" in sys.argv:
        from verdict.config import get_settings
        from verdict.judge.llm import client_from_settings
        llm = client_from_settings(get_settings())
    spec = (task / "spec.md").read_text()
    ref = load(task / "reference.py", "reference")
    gen = load(task / "gen_input.py", "gen_input")

    ok_all = True
    print(f"{'submission':<18} {'decision':<13} {'capture':>8}  hidden / fresh / signals"
          + (" / AI" if llm else ""))
    for name, (want, lo, hi) in EXPECTED.items():
        sub = task / "submissions" / name
        r = grade(sub, suite, LocalRunner(), ref.solve, gen.gen_input,
                  amount="100.00", fee_bps=500, timeout_s=2.0, seed=42)
        d, ai_note = r.decision, ""
        if llm is not None:
            want, lo, hi = AI_EXPECTED.get(name, (want, lo, hi))
            ai = ai_review(llm, spec, code_of(sub), r, suite.min_score)
            ai_note = " / " + (ai.decision.value if ai else "not asked")
            if ai is not None and r.payout is not None:
                d = decide(r.payout, r.signals, ai.decision)
        ok = d.settlement is want and (lo is None or lo <= d.capture <= hi)
        ok_all &= ok
        hidden = " ".join(f"{g}:{p}/{t}" for g, (p, t) in r.hidden.items()) or "-"
        fresh = " ".join(f"{g}:{p}/{t}" for g, (p, t) in r.fresh.items()) or "-"
        sig = ",".join(s.value for s in r.signals) or "-"
        print(f"{name:<18} {d.settlement.value:<13} {d.capture:>8}  {hidden} / {fresh} / {sig}"
              f"{ai_note}  {'✓' if ok else '✗ expected ' + want.value}")
    print("\nALL EXPECTED" if ok_all else "\nMISMATCH: see ✗ rows")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
