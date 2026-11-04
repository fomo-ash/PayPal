"""Runner interface + the local DEV runner.

A runner executes `harness.py` next to the submission and streams inputs to it.
It returns raw outputs only. Pass/fail is computed by the caller (verdict.grading),
outside the sandbox. Expected outputs are NEVER given to a runner.

Backends:
  LocalRunner  dev/bench only: a plain subprocess, NOT isolated. Never use on untrusted code
               outside your own machine.
  E2BRunner    production: Firecracker microVM, no network (sandbox/e2b_runner.py, Phase 1)
  DockerRunner fallback: docker + gVisor runsc, --network none (sandbox/docker_runner.py)
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

HARNESS = Path(__file__).with_name("harness.py")


@dataclass(frozen=True)
class RunResult:
    id: str
    output: str | None
    error: str | None
    ms: float


class TamperDetected(Exception):
    """Protocol violation: wrong nonce, unknown id, or forged/duplicated lines."""


class Runner(Protocol):
    def run_batch(self, submission_dir: Path, inputs: list[tuple[str, str]],
                  timeout_s: float) -> list[RunResult]: ...


def build_requests(inputs: list[tuple[str, str]]) -> tuple[str, dict[str, str]]:
    nonces = {tid: secrets.token_hex(8) for tid, _ in inputs}
    lines = "".join(json.dumps({"id": tid, "nonce": nonces[tid], "input": x}) + "\n"
                    for tid, x in inputs)
    return lines, nonces


def parse_responses(stdout: str, inputs: list[tuple[str, str]], nonces: dict[str, str],
                    per_test_timeout_s: float) -> list[RunResult]:
    got: dict[str, RunResult] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            raise TamperDetected(f"non-protocol line on harness stdout: {line[:80]!r}") from e
        rid = msg.get("id")
        if rid is None:                       # import failure: every test fails
            err = msg.get("error", "import failed")
            return [RunResult(tid, None, err, 0.0) for tid, _ in inputs]
        if rid not in nonces or msg.get("nonce") != nonces[rid] or rid in got:
            raise TamperDetected(f"bad id/nonce/duplicate for {rid!r}")
        got[rid] = RunResult(rid, msg.get("output"), msg.get("error"), float(msg.get("ms", 0)))
    # Missing responses (process died, os._exit, wall-clock kill) count as failures.
    return [got.get(tid, RunResult(tid, None, "no response (process exited or killed)",
                                   per_test_timeout_s * 1000)) for tid, _ in inputs]


class LocalRunner:
    """DEV ONLY. Runs untrusted code as a normal process on your machine."""

    def run_batch(self, submission_dir: Path, inputs: list[tuple[str, str]],
                  timeout_s: float) -> list[RunResult]:
        stdin, nonces = build_requests(inputs)
        with tempfile.TemporaryDirectory() as work:
            sub = Path(work) / "submission"
            shutil.copytree(submission_dir, sub)
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", str(HARNESS), str(sub), "solution", "solve"],
                    input=stdin, capture_output=True, text=True, cwd=work,
                    timeout=timeout_s * len(inputs) + 10,
                    env={"VERDICT_TEST_TIMEOUT_S": str(timeout_s), "PATH": ""},
                )
                stdout = proc.stdout
            except subprocess.TimeoutExpired as e:
                stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return parse_responses(stdout, inputs, nonces, timeout_s)
