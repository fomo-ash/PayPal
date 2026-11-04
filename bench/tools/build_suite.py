"""Builds examples.json + hidden_tests.json for a bench task by running the reference solution,
and generates the 'leaked tests' memorizer cheat. Run: python bench/tools/build_suite.py

In the real product the BUYER uploads hidden tests with expected outputs; Verdict then checks
that the reference solution reproduces them (B1 defence). Here we generate expected outputs
from the reference so the bench is self-consistent.
"""

import hashlib
import importlib.util
import json
import random
from pathlib import Path

TASK = Path(__file__).resolve().parents[1] / "tasks" / "log_parser"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ref = load(TASK / "reference.py", "reference")
gen = load(TASK / "gen_input.py", "gen_input")

EXAMPLES = [
    "2026-11-01T10:00:00Z [INFO] server started",
    "2026-11-01T10:00:01Z [error] db timeout\nnot a log line\n2026-11-01T10:00:02Z [WARNING] retrying",
    "",
]

CORE = [
    "2026-11-01T09:00:00Z [DEBUG] cache warm",
    "2026-11-01T09:00:00Z [INFO] a\n2026-11-01T09:00:01Z [INFO] b\n2026-11-01T09:00:02Z [ERROR] c",
    "garbage\nmore garbage",
    "2026-11-01T09:00:00Z [WARN] disk 91%\n2026-11-01T09:00:05Z [WARN] disk 95%",
    "2026-11-01T09:00:00Z [INFO] payment ok id=42\nhello\n2026-11-01T09:00:00Z [FATAL] boom",
    "2026-01-31T23:59:59Z [ERROR] end of month",
    "2026-11-01T09:00:00Z [INFO] user login\n2026-11-01T09:00:00Z [INFO] user logout\n2026-11-01T09:00:00Z [DEBUG] gc pause 12ms",
    "[INFO] missing timestamp\n2026-11-01T09:00:00Z INFO missing brackets",
    "2026-11-01T09:00:00Z [ERROR] x\n" * 5,
    "2024-02-29T12:00:00Z [INFO] leap day is valid",
]

EDGE = [
    "   2026-11-01T09:00:00Z [info]    padded message   ",
    "2026-11-01T09:00:00Z\t[Warning]\ttabs everywhere",
    "\n\n   \n2026-11-01T09:00:00Z [INFO] blank lines ignored\n\n",
    "2026-02-30T09:00:00Z [INFO] impossible date",
    "2026-11-01T09:00:00Z [INFO]    ",
    "2026-11-01T24:00:00Z [INFO] hour 24",
    "2026-11-01T09:00:00Z [INFO] brackets [inside] message ]",
    "2026-11-01T09:00:00+05:30 [INFO] offset not allowed\n2026-11-01T09:00:00Z [info] ünïcode → ok",
]


def perf_input(seed: int) -> str:
    rng = random.Random(seed)
    return "\n".join(gen._line(rng) for _ in range(3000))


def main() -> None:
    examples = [{"input": x, "expected": ref.solve(x)} for x in EXAMPLES]
    hidden = []
    for group, inputs in (("core", CORE), ("edge", EDGE),
                          ("perf", [perf_input(1), perf_input(2)])):
        for i, x in enumerate(inputs):
            hidden.append({"id": f"{group}-{i + 1}", "group": group, "input": x,
                           "expected": ref.solve(x)})
    suite = {"task": "log_parser", "groups": {"core": "0.60", "edge": "0.25", "perf": "0.15"},
             "fresh": {"core": 200}, "min_score": "0.50", "tests": hidden}
    blob = json.dumps(suite, sort_keys=True, ensure_ascii=False).encode()
    suite_hash = hashlib.sha256(blob).hexdigest()
    (TASK / "examples.json").write_text(json.dumps(examples, indent=1, ensure_ascii=False))
    (TASK / "hidden_tests.json").write_bytes(blob)
    (TASK / "suite.sha256").write_text(suite_hash + "\n")

    # 'Leaked tests' cheat: answers hard-coded for every hidden input.
    table = {t["input"]: t["expected"] for t in hidden if t["group"] != "perf"}
    (TASK / "submissions" / "cheat_memorizer" / "solution.py").write_text(
        '"""CHEAT: memorized the hidden answers (as if the tests leaked)."""\n'
        f"ANSWERS = {table!r}\n\n"
        "def solve(input):\n"
        "    if input in ANSWERS:\n"
        "        return ANSWERS[input]\n"
        '    return \'{"entries": [], "skipped": 0, "counts": {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0}}\'\n'
    )
    print(f"examples: {len(examples)}  hidden: {len(hidden)}  sha256: {suite_hash[:16]}…")


if __name__ == "__main__":
    main()
