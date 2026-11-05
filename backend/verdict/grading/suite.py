"""Buyer suite upload: validation, canonical form and the sealed hash.

Upload document (JSON):
    {
      "groups":   {"core": "0.60", "edge": "0.25", "perf": "0.15"},   weights, sum exactly 1
      "fresh":    {"core": 200},                                      optional, needs generator
      "tests":    [{"id": "core-1", "group": "core", "input": "...", "expected": "..."}],
      "examples": [{"input": "...", "expected": "..."}],               PUBLIC, shown to workers
      "reference": "<python source defining solve(input) -> str>",
      "generator": "<python source defining gen_input(rng) -> str>"   optional
    }

The seal is sha256 over the canonical JSON of tests + groups + fresh + examples + the sha256 of
the reference and generator. It is fixed when the job is funded and printed on the receipt, so
the buyer cannot change a test after a worker has started.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from verdict.grading.pipeline import Suite

NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
TEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
MAX_TESTS = 2000
MAX_EXAMPLES = 50
MAX_FRESH_PER_GROUP = 1000
MAX_TEXT = 1_000_000            # one input or expected output
MAX_SOURCE = 200_000            # reference / generator source


class SuiteError(ValueError):
    pass


@dataclass(frozen=True)
class SuiteUpload:
    doc: dict[str, Any]          # canonical tests/groups/fresh/examples (stored as tests.json)
    reference: str
    generator: str | None
    sha256: str

    def pipeline_suite(self, min_score: Decimal) -> Suite:
        return to_pipeline_suite(self.doc, min_score)


def parse_upload(raw: Any) -> SuiteUpload:
    if not isinstance(raw, dict):
        raise SuiteError("suite must be a JSON object")
    groups = _groups(raw.get("groups"))
    tests = _tests(raw.get("tests"), groups)
    fresh = _fresh(raw.get("fresh", {}), groups)
    examples = _examples(raw.get("examples", []))
    reference = _source(raw.get("reference"), "reference", "solve")
    gen_raw = raw.get("generator")
    generator = _source(gen_raw, "generator", "gen_input") if gen_raw else None
    if any(fresh.values()) and generator is None:
        raise SuiteError("fresh inputs need a generator")
    doc = {"groups": {g: str(w) for g, w in groups.items()}, "fresh": fresh,
           "tests": tests, "examples": examples}
    return SuiteUpload(doc, reference, generator, seal(doc, reference, generator))


def seal(doc: dict[str, Any], reference: str, generator: str | None) -> str:
    body = {**doc, "reference_sha256": _sha(reference),
            "generator_sha256": _sha(generator) if generator else None}
    return _sha(canonical(body))


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def to_pipeline_suite(doc: dict[str, Any], min_score: Decimal) -> Suite:
    return Suite(groups={g: Decimal(w) for g, w in doc["groups"].items()},
                 fresh={g: int(n) for g, n in doc.get("fresh", {}).items() if int(n) > 0},
                 min_score=min_score, tests=doc["tests"])


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _groups(raw: Any) -> dict[str, Decimal]:
    if not isinstance(raw, dict) or not raw:
        raise SuiteError("groups must be a non-empty object of name → weight")
    out: dict[str, Decimal] = {}
    for name, w in raw.items():
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise SuiteError(f"bad group name {name!r}")
        if not isinstance(w, str | int) or isinstance(w, bool):
            raise SuiteError(f"weight of {name} must be a decimal string like \"0.25\"")
        try:
            d = Decimal(str(w))
        except InvalidOperation as e:
            raise SuiteError(f"bad weight for {name}: {w!r}") from e
        if not d.is_finite() or not Decimal(0) < d <= 1 or d != d.quantize(Decimal("0.0001")):
            raise SuiteError(f"weight of {name} must be in (0, 1] with at most 4 decimals")
        out[name] = d
    if sum(out.values()) != 1:
        raise SuiteError(f"group weights must sum to exactly 1 (got {sum(out.values())})")
    return out


def _text(v: Any, what: str) -> str:
    if not isinstance(v, str):
        raise SuiteError(f"{what} must be a string")
    if len(v) > MAX_TEXT:
        raise SuiteError(f"{what} is too long")
    return v


def _tests(raw: Any, groups: dict[str, Decimal]) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise SuiteError("tests must be a non-empty list")
    if len(raw) > MAX_TESTS:
        raise SuiteError(f"at most {MAX_TESTS} tests")
    seen: set[str] = set()
    out = []
    for t in raw:
        if not isinstance(t, dict):
            raise SuiteError("each test must be an object")
        tid = t.get("id")
        if not isinstance(tid, str) or not TEST_ID.fullmatch(tid) or tid.startswith("fresh-"):
            raise SuiteError(f"bad test id {tid!r}")
        if tid in seen:
            raise SuiteError(f"duplicate test id {tid}")
        seen.add(tid)
        if t.get("group") not in groups:
            raise SuiteError(f"test {tid}: unknown group {t.get('group')!r}")
        out.append({"id": tid, "group": t["group"], "input": _text(t.get("input"), f"{tid}.input"),
                    "expected": _text(t.get("expected"), f"{tid}.expected")})
    empty = set(groups) - {t["group"] for t in out}
    if empty:
        raise SuiteError(f"groups without tests: {sorted(empty)}")
    return out


def _fresh(raw: Any, groups: dict[str, Decimal]) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise SuiteError("fresh must be an object of group → count")
    out = {}
    for g, n in raw.items():
        if g not in groups:
            raise SuiteError(f"fresh: unknown group {g!r}")
        if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= MAX_FRESH_PER_GROUP:
            raise SuiteError(f"fresh count for {g} must be 0..{MAX_FRESH_PER_GROUP}")
        out[g] = n
    return out


def _examples(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or len(raw) > MAX_EXAMPLES:
        raise SuiteError(f"examples must be a list of at most {MAX_EXAMPLES}")
    return [{"input": _text(e.get("input") if isinstance(e, dict) else None, "example input"),
             "expected": _text(e.get("expected"), "example expected")} for e in raw]


def _source(raw: Any, what: str, func: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SuiteError(f"{what} source is required")
    if len(raw) > MAX_SOURCE:
        raise SuiteError(f"{what} source is too long")
    try:
        tree = ast.parse(raw)
    except SyntaxError as e:
        raise SuiteError(f"{what} has a syntax error on line {e.lineno}") from e
    if not any(isinstance(n, ast.FunctionDef) and n.name == func for n in tree.body):
        raise SuiteError(f"{what} must define a top-level function {func}()")
    return raw
