"""Harness that runs INSIDE the sandbox. Standard library only.

Protocol (JSON Lines):
  stdin  → {"id": "t1", "nonce": "a1b2", "input": "<string>"}
  stdout ← {"id": "t1", "nonce": "a1b2", "output": "<string>", "ms": 3.1}
        or {"id": "t1", "nonce": "a1b2", "error": "TypeError: ...", "ms": 0.4}

Security model:
  * The harness never sees expected outputs and never reports pass/fail. Comparison
    happens outside the sandbox (verdict.grading.compare), so tampering with this
    process cannot turn a failure into a pass. It can only break its own outputs.
  * The protocol is written to a duplicate of the original stdout fd taken BEFORE the
    submission is imported, and the submission's own prints are swallowed, so they
    cannot inject protocol lines.
  * The nonce lets the runner detect out-of-order or forged lines (a HARNESS_TAMPER signal).
  * Per-test time limits are enforced here (SIGALRM) and again by the runner (wall clock).

Usage inside the sandbox:  python harness.py /work/submission solution solve
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import signal
import sys
import time


class _Timeout(Exception):
    pass


def _alarm(_signum, _frame):
    raise _Timeout()


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: harness.py <submission_dir> <module> <function>", file=sys.stderr)
        return 2
    sub_dir, module_name, func_name = argv[1], argv[2], argv[3]
    timeout_s = float(os.environ.get("VERDICT_TEST_TIMEOUT_S", "2"))

    proto = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    stdin = sys.stdin
    sys.path.insert(0, sub_dir)

    def emit(obj: dict) -> None:
        proto.write(json.dumps(obj) + "\n")
        proto.flush()

    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink):
            fn = getattr(importlib.import_module(module_name), func_name)
    except BaseException as exc:  # noqa: BLE001 - report every import failure
        emit({"id": None, "nonce": None, "error": f"import failed: {type(exc).__name__}: {exc}"})
        return 1

    signal.signal(signal.SIGALRM, _alarm)
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        msg = json.loads(raw)
        rid, nonce = msg["id"], msg["nonce"]
        start = time.perf_counter()
        try:
            signal.setitimer(signal.ITIMER_REAL, timeout_s)
            with contextlib.redirect_stdout(sink):
                out = fn(msg["input"])
            signal.setitimer(signal.ITIMER_REAL, 0)
            ms = (time.perf_counter() - start) * 1000
            if not isinstance(out, str):
                emit({"id": rid, "nonce": nonce, "error": f"returned {type(out).__name__}, expected str", "ms": ms})
            else:
                emit({"id": rid, "nonce": nonce, "output": out, "ms": ms})
        except _Timeout:
            emit({"id": rid, "nonce": nonce, "error": "timeout", "ms": timeout_s * 1000})
        except BaseException as exc:  # noqa: BLE001 - SystemExit etc. count as a failed test
            signal.setitimer(signal.ITIMER_REAL, 0)
            ms = (time.perf_counter() - start) * 1000
            emit({"id": rid, "nonce": nonce, "error": f"{type(exc).__name__}: {exc}", "ms": ms})
        sink.seek(0)
        sink.truncate()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
