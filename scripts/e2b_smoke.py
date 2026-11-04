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

# A TCP handshake alone proves nothing: E2B's egress proxy accepts the connection and then
# drops it. The real test is whether any bytes come BACK from the internet.
NET_PROBE = '''
import socket
def solve(target):
    if target == "dns":
        try:
            socket.getaddrinfo("example.com", 80)
            return "OPEN dns resolves"
        except OSError as exc:
            return "BLOCKED dns " + type(exc).__name__
    try:
        s = socket.create_connection((target, 80), timeout=3)
        s.settimeout(3)
        s.sendall(b"GET / HTTP/1.0\\r\\nHost: one.one.one.one\\r\\n\\r\\n")
        data = s.recv(64)
        s.close()
    except OSError as exc:
        return "BLOCKED " + type(exc).__name__
    return f"OPEN got {data[:16]!r}" if data else "BLOCKED no bytes returned"
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
        net = runner.run_batch(Path(d), [("dns", "dns"), ("ip-1.1.1.1", "1.1.1.1"),
                                         ("ip-8.8.8.8", "8.8.8.8")], 10.0)
    def blocked(r) -> bool:   # a lookup that hangs until the harness kills it is also blocked
        return (r.output or "").startswith("BLOCKED") or "timeout" in (r.error or "")

    for r in net:
        print(f"network probe {r.id:<11} {'BLOCKED' if blocked(r) else 'OPEN!'}  "
              f"({r.output or r.error})")

    ok = passed == len(core) and all(blocked(r) for r in net)
    print("\nRESULT:", "PASS" if ok else "CHECK ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
