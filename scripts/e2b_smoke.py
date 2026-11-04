"""Phase 1 spike: run real code in an E2B microVM. Needs E2B_API_KEY in .env (free tier).

Checks:
  1. cold start + run time for a batch
  2. the honest bench solution gets the right answers inside the VM
  3. outbound network is BLOCKED inside the VM (the most important check)
Run:  python scripts/e2b_smoke.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from verdict.config import get_settings  # noqa: E402
from verdict.grading.compare import outputs_match  # noqa: E402
from verdict.sandbox.e2b_runner import E2BRunner  # noqa: E402

NET_PROBE = '''
import socket
def solve(host):
    try:
        socket.create_connection((host, 443), timeout=3).close()
        return "OPEN"
    except OSError as exc:
        return "BLOCKED " + type(exc).__name__
'''


def main() -> int:
    key = get_settings().e2b_api_key
    if not key:
        print("E2B_API_KEY is empty. Get a free key at https://e2b.dev/dashboard → API Keys.")
        return 1
    runner = E2BRunner(key)
    task = ROOT / "bench" / "tasks" / "log_parser"
    tests = json.loads((task / "hidden_tests.json").read_text())["tests"]
    core = [t for t in tests if t["group"] in ("core", "edge")]

    t0 = time.perf_counter()
    res = runner.run_batch(task / "submissions" / "honest_full",
                           [(t["id"], t["input"]) for t in core], 2.0)
    secs = time.perf_counter() - t0
    expected = {t["id"]: t["expected"] for t in core}
    passed = sum(r.error is None and outputs_match(expected[r.id], r.output) for r in res)
    print(f"honest_full in E2B: {passed}/{len(core)} passed, batch took {secs:.1f}s "
          f"(includes VM cold start)")

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "solution.py").write_text(NET_PROBE)
        net = runner.run_batch(Path(d), [("n1", "example.com"), ("n2", "1.1.1.1")], 6.0)
    for r in net:
        print(f"network probe {r.id}: {r.output or r.error}")

    ok = passed == len(core) and all((r.output or "").startswith("BLOCKED") for r in net)
    print("\nRESULT:", "PASS" if ok else "CHECK ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
