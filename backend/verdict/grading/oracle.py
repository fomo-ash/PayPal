"""Run the BUYER's code (reference solution, fresh-input generator) in the sandbox.

Buyer code is untrusted too, so it goes through the same Runner as worker code, in its own
VM, never inside the worker's. The generator is wrapped as a `solve(request) -> str` so the
normal harness can run it: request {"seed", "n"} → JSON list of n inputs.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from verdict.sandbox.runner import Runner

GEN_WRAPPER = '''

import json as _verdict_json
import random as _verdict_random


def solve(_request):
    _r = _verdict_json.loads(_request)
    _rng = _verdict_random.Random(_r["seed"])
    return _verdict_json.dumps([gen_input(_rng) for _ in range(_r["n"])])
'''
GEN_TIMEOUT_S = 20.0


class OracleError(Exception):
    """The buyer's own code failed: the job cannot be validated or graded as uploaded."""


def run_reference(runner: Runner, reference: str, inputs: list[tuple[str, str]],
                  timeout_s: float) -> dict[str, str | None]:
    """id → reference output, or None where the reference raised or timed out."""
    if not inputs:
        return {}
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "solution.py").write_text(reference)
        results = runner.run_batch(Path(d), inputs, timeout_s)
    return {r.id: (r.output if r.error is None else None) for r in results}


def group_seed(seed: int, group: str) -> int:
    """Independent stream per group, all derived from the one secret submission seed."""
    return int.from_bytes(hashlib.sha256(f"{seed}:{group}".encode()).digest()[:8], "big")


def generate_inputs(runner: Runner, generator: str, seed: int,
                    counts: dict[str, int]) -> dict[str, list[tuple[str, str]]]:
    """group → [(fresh id, input)]. Raises OracleError if the generator misbehaves."""
    wanted = {g: n for g, n in counts.items() if n > 0}
    if not wanted:
        return {}
    reqs = [(g, json.dumps({"seed": group_seed(seed, g), "n": n})) for g, n in wanted.items()]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "solution.py").write_text(generator + GEN_WRAPPER)
        results = {r.id: r for r in runner.run_batch(Path(d), reqs, GEN_TIMEOUT_S)}
    out: dict[str, list[tuple[str, str]]] = {}
    for g, n in wanted.items():
        r = results.get(g)
        if r is None or r.error is not None or r.output is None:
            raise OracleError(f"generator failed for group {g}: {r.error if r else 'no result'}")
        try:
            items = json.loads(r.output)
        except json.JSONDecodeError as e:
            raise OracleError(f"generator output for {g} is not JSON") from e
        if not isinstance(items, list) or len(items) != n or not all(
                isinstance(x, str) for x in items):
            raise OracleError(f"generator must return {n} strings for group {g}")
        out[g] = [(f"fresh-{g}-{i}", x) for i, x in enumerate(items)]
    return out


def fresh_builder(runner: Runner, generator: str, reference: str, counts: dict[str, int],
                  timeout_s: float):
    """For grading.pipeline.grade(fresh_builder=...): seed → (cases by group, expected)."""
    def build(seed: int) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
        cases = generate_inputs(runner, generator, seed, counts)
        flat = [c for cs in cases.values() for c in cs]
        expected = run_reference(runner, reference, flat, timeout_s)
        # an input the reference itself cannot answer is dropped, never counted against anyone
        kept = {g: [(fid, x) for fid, x in cs if expected.get(fid) is not None]
                for g, cs in cases.items()}
        return kept, {k: v for k, v in expected.items() if v is not None}
    return build
