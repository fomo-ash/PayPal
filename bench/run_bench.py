"""Runs every bench submission through the deterministic grading pipeline and checks the outcome.

Phase 0: LocalRunner (not isolated: bench code only!) and the AI judge stubbed as CLEAR.
Run: python bench/run_bench.py      (or: make bench)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from verdict.core.policy import Settlement  # noqa: E402
from verdict.grading.pipeline import Suite, grade  # noqa: E402
from verdict.sandbox.runner import LocalRunner  # noqa: E402

# submission → expected settlement (and optionally a capture range)
EXPECTED = {
    "honest_full": (Settlement.CAPTURE, Decimal("100.00"), Decimal("100.00")),
    "honest_partial": (Settlement.CAPTURE, Decimal("50.00"), Decimal("99.99")),
    "cheat_memorizer": (Settlement.VOID, None, None),
    "cheat_injection": (Settlement.VOID, None, None),
    "cheat_exit": (Settlement.VOID, None, None),
    "cheat_conftest": (Settlement.VOID, None, None),
    "cheat_env_sniff": (Settlement.VOID, None, None),
}


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
    ref = load(task / "reference.py", "reference")
    gen = load(task / "gen_input.py", "gen_input")

    ok_all = True
    print(f"{'submission':<18} {'decision':<13} {'capture':>8}  hidden / fresh / signals")
    for name, (want, lo, hi) in EXPECTED.items():
        r = grade(task / "submissions" / name, suite, LocalRunner(), ref.solve, gen.gen_input,
                  amount="100.00", fee_bps=500, timeout_s=2.0, seed=42)
        d = r.decision
        ok = d.settlement is want and (lo is None or lo <= d.capture <= hi)
        ok_all &= ok
        hidden = " ".join(f"{g}:{p}/{t}" for g, (p, t) in r.hidden.items()) or "-"
        fresh = " ".join(f"{g}:{p}/{t}" for g, (p, t) in r.fresh.items()) or "-"
        sig = ",".join(s.value for s in r.signals) or "-"
        print(f"{name:<18} {d.settlement.value:<13} {d.capture:>8}  {hidden} / {fresh} / {sig}"
              f"  {'✓' if ok else '✗ expected ' + want.value}")
    print("\nALL EXPECTED" if ok_all else "\nMISMATCH: see ✗ rows")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
