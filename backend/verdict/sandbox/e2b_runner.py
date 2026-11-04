"""E2B microVM runner (production).

Per run_batch call:
  1. Sandbox.create(..., allow_internet_access=False): a fresh Firecracker VM, no network.
  2. Upload harness.py + the submission files ONLY. Never the suite, never expected outputs.
  3. Run `timeout <wall> python3 -I harness.py ...` as the unprivileged user, requests on stdin.
     The in-VM `timeout` enforces the wall clock, so stdout produced so far is still returned.
  4. Kill the VM (always), cap the output size, parse with runner.parse_responses.
Pass/fail is decided by the caller, outside the VM.

Live check:  make e2b   (needs E2B_API_KEY; proves network is blocked)
Measured 2026-11-05: honest bench solution 18/18 in the VM, ~3-5s per batch incl. cold start.
Network note: with allow_internet_access=False a TCP connect still "succeeds" (E2B's egress
proxy accepts it) but zero bytes come back and DNS never resolves. So the smoke test checks
for returned bytes, not for a refused connection.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

from verdict.sandbox.runner import HARNESS, RunResult, build_requests, parse_responses

WORK = "/home/user/work"
MAX_STDOUT_BYTES = 8 * 1024 * 1024        # a submission printing gigabytes gets cut off here
MAX_FILES = 50


class SandboxUnavailable(Exception):
    """E2B could not create or reach a VM. The grading task retries later; nothing is graded."""


class E2BRunner:
    def __init__(self, api_key: str, *, template: str | None = None,
                 sandbox_factory: Callable[..., Any] | None = None,
                 startup_s: float = 30.0):
        if not api_key and sandbox_factory is None:
            raise ValueError("E2B_API_KEY missing; see README → Sandbox runner")
        self._api_key = api_key
        self._template = template
        self._factory = sandbox_factory
        self._startup_s = startup_s

    def _create(self, lifetime_s: int) -> Any:
        if self._factory is not None:
            return self._factory(lifetime_s)
        from e2b import Sandbox

        try:
            return Sandbox.create(template=self._template, timeout=lifetime_s,
                                  allow_internet_access=False, api_key=self._api_key,
                                  metadata={"purpose": "verdict-grading"})
        except Exception as exc:  # noqa: BLE001 - any SDK/network failure means "try later"
            raise SandboxUnavailable(f"{type(exc).__name__}: {exc}") from exc

    def run_batch(self, submission_dir: Path, inputs: list[tuple[str, str]],
                  timeout_s: float) -> list[RunResult]:
        stdin, nonces = build_requests(inputs)
        wall = int(timeout_s * len(inputs) + 10)
        files = [p for p in sorted(submission_dir.rglob("*")) if p.is_file()]
        if len(files) > MAX_FILES:
            raise ValueError(f"submission has {len(files)} files (max {MAX_FILES})")

        sbx = self._create(lifetime_s=wall + int(self._startup_s) + 30)
        try:
            sbx.files.write(f"{WORK}/harness.py", HARNESS.read_text())
            for p in files:
                rel = p.relative_to(submission_dir).as_posix()
                sbx.files.write(f"{WORK}/submission/{rel}", p.read_bytes())
            sbx.files.write(f"{WORK}/requests.jsonl", stdin)
            cmd = (f"cd {WORK} && VERDICT_TEST_TIMEOUT_S={timeout_s} timeout -s KILL {wall} "
                   f"python3 -I harness.py {shlex.quote(WORK + '/submission')} solution solve "
                   f"< requests.jsonl")
            stdout = _run(sbx, cmd, wall + 15)
        finally:
            try:
                sbx.kill()
            except Exception:  # noqa: BLE001, S110 - the VM also dies at its own timeout
                pass
        return parse_responses(_cap(stdout), inputs, nonces, timeout_s)


def _run(sbx: Any, cmd: str, timeout_s: float) -> str:
    """Run and return stdout even when the command exits non-zero (killed, os._exit, crash)."""
    try:
        res = sbx.commands.run(cmd, timeout=timeout_s, user="user")
        return res.stdout or ""
    except Exception as exc:  # noqa: BLE001
        out = getattr(exc, "stdout", None)
        if out is not None:                  # CommandExitException carries the output
            return out
        if type(exc).__name__ == "TimeoutException":
            return ""                        # every unanswered test counts as failed
        raise SandboxUnavailable(f"{type(exc).__name__}: {exc}") from exc


def _cap(stdout: str) -> str:
    if len(stdout.encode()) <= MAX_STDOUT_BYTES:
        return stdout
    cut = stdout.encode()[:MAX_STDOUT_BYTES].decode(errors="ignore")
    return cut.rsplit("\n", 1)[0]            # drop the partial last line
