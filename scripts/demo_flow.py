"""Walk one job through the running API on localhost, with real PayPal sandbox + E2B.

    terminal 1:  make local                      (API on http://localhost:8000, docs at /docs)
    terminal 2:  make demo                       (honest worker, gets paid)
                 make demo SUB=cheat_memorizer   (cheater, buyer's hold is voided)
                 make demo SUB=cheat_timebomb    (passes every test; AI flags it → you review)

You approve the payment in the browser as the sandbox BUYER, like in the spike.
"""

from __future__ import annotations

import json
import os
import sys
import time
import webbrowser
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from verdict.config import get_settings  # noqa: E402

API = os.environ.get("VERDICT_API_URL", "http://localhost:8000").rstrip("/")
TASK = Path(__file__).resolve().parents[1] / "bench" / "tasks" / "log_parser"
DONE = {"PAID", "CODE_RELEASED", "VOIDED", "HUMAN_REVIEW", "PAYOUT_FAILED"}


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


def call(c: httpx.Client, method: str, path: str, who: dict | None = None, **kw) -> dict:
    r = c.request(method, path, headers=who or {}, **kw)
    if r.status_code >= 400:
        sys.exit(f"{method} {path} → {r.status_code}: {r.text}")
    return r.json()


def files(name: str) -> dict:
    root = TASK / "submissions" / name
    return {"files": {p.relative_to(root).as_posix(): p.read_text()
                      for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts}}


def main() -> None:
    sub_name = sys.argv[1] if len(sys.argv) > 1 else "honest_full"
    worker_email = get_settings().sandbox_worker_email
    with httpx.Client(base_url=API, timeout=120) as c:
        try:
            c.get("/health").raise_for_status()
        except httpx.HTTPError:
            sys.exit("API not running. Start it first in another terminal:  make local")

        step("1. users (dev login)")
        buyer = {"X-User-Id": call(c, "POST", "/dev/users", json={
            "role": "buyer", "email": "buyer@example.com", "display_name": "Demo buyer"})["id"]}
        worker = {"X-User-Id": call(c, "POST", "/dev/users", json={
            "role": "worker", "email": worker_email or "worker@example.com",
            "display_name": f"Demo worker ({sub_name})"})["id"]}
        print("buyer", buyer["X-User-Id"], "\nworker", worker["X-User-Id"],
              "→ paid to", worker_email or "worker@example.com")

        step("2. buyer posts a $100 job and uploads the sealed tests")
        job = call(c, "POST", "/jobs", buyer, json={
            "title": "Parse application logs into JSON",
            "spec_md": (TASK / "spec.md").read_text(), "amount": "100.00",
            "min_score": "0.50", "deadline_hours": 24})
        jid = job["id"]
        hidden = json.loads((TASK / "hidden_tests.json").read_text())
        suite = {"groups": hidden["groups"], "fresh": hidden["fresh"], "tests": hidden["tests"],
                 "examples": json.loads((TASK / "examples.json").read_text()),
                 "reference": (TASK / "reference.py").read_text(),
                 "generator": (TASK / "gen_input.py").read_text()}
        up = call(c, "PUT", f"/jobs/{jid}/suite", buyer, json=suite)
        print(f"job {jid}\nsuite: {up['tests']} hidden tests, sha256 {up['sha256'][:16]}…")

        step("3. validate: reference passes every test (sandbox) + AI spec check")
        t = time.time()
        v = call(c, "POST", f"/jobs/{jid}/validate", buyer)
        fair = sum(x["implied"] for x in v["spec_check"])
        print(f"{v['state']} in {time.time() - t:.1f}s · spec check: "
              f"{fair}/{len(v['spec_check'])} tests follow from the spec",
              *(v["problems"] + v["warnings"]))
        if v["state"] != "AWAITING_FUNDS":
            sys.exit("validation failed")

        step("4. fund: PayPal authorization hold (approve as the sandbox BUYER)")
        order = call(c, "POST", f"/jobs/{jid}/fund", buyer)
        print("order", order["order_id"], "\napprove here:", order["approve_url"])
        webbrowser.open(order["approve_url"])
        input("After approving (you'll land on the return page), press Enter… ")
        f = call(c, "POST", f"/jobs/{jid}/fund/confirm", buyer)
        print(f"{f['state']}: hold {f.get('authorization_id')} · suite sealed "
              f"{f['suite_sha256'][:16]}…")

        step(f"5. worker claims, tries the public examples, submits ({sub_name})")
        call(c, "POST", f"/jobs/{jid}/claim", worker)
        ex = call(c, "POST", f"/jobs/{jid}/examples-run", worker, json=files(sub_name))
        print(f"examples: {ex['passed']}/{ex['total']} passed")
        s = call(c, "POST", f"/jobs/{jid}/submit", worker, json=files(sub_name))
        sid = s["submission_id"]
        print("submission", sid)

        step("6. grading in E2B → verdict → capture/void → payout (watch terminal 1)")
        last = None
        for _ in range(150):
            view = call(c, "GET", f"/submissions/{sid}", buyer)
            if view["job_state"] != last:
                last = view["job_state"]
                print(f"  {time.strftime('%H:%M:%S')}  {last}")
            if last in DONE:
                break
            time.sleep(4)

        step("7. result")
        for r in view["runs"]:
            print(f"  {r['kind']:6} {r['group']:5} {r['passed']}/{r['total']}")
        v = view["verdict"]
        if v:
            print(f"  score {float(v['score']):.1%} · settlement {v['settlement']} · "
                  f"capture ${v['capture']} (fee ${v['fee']}, worker ${v['worker_amount']}) · "
                  f"released to buyer ${v['released']}\n  reason: {v['reason']}")
        ai = view.get("ai_review")
        if ai:
            print(f"  AI review ({ai['model']}): {ai['decision']} · {ai['explanation']}")
            for f in ai["findings"]:
                print(f"    {f['file']}:{f['line']} {f['category']}: {f['evidence']}")
        if last == "HUMAN_REVIEW":
            view, last = review(c, jid, sid, buyer, v)
        if last == "PAID":
            code = call(c, "GET", f"/submissions/{sid}/code", buyer)
            print("  buyer downloaded:", ", ".join(code["files"]), "→ CODE_RELEASED")
        print(f"\nOpen {API}/docs to explore · job {jid}")


def review(c: httpx.Client, jid: str, sid: str, buyer: dict, v: dict) -> tuple[dict, str]:
    step("8. human review: you are the admin (can lower or void, never raise)")
    admin = {"X-User-Id": call(c, "POST", "/dev/users", json={
        "role": "admin", "email": "admin@example.com", "display_name": "Demo admin"})["id"]}
    print(f"  max you can approve: ${v['capture']}  (0 = void, buyer keeps everything)")
    amount = input("  capture amount [0]: ").strip() or "0"
    r = call(c, "POST", f"/admin/reviews/{jid}", admin,
             json={"capture": amount, "note": "decided in the demo"})
    print(f"  → {r['settlement']} ${r['capture']} · {r['state']}")
    last, view = r["state"], {}
    for _ in range(150):
        view = call(c, "GET", f"/submissions/{sid}", buyer)
        if view["job_state"] != last:
            last = view["job_state"]
            print(f"  {time.strftime('%H:%M:%S')}  {last}")
        if last in DONE - {"HUMAN_REVIEW"}:
            break
        time.sleep(4)
    vv = view["verdict"]
    print(f"  final: capture ${vv['capture']} (worker ${vv['worker_amount']}) · "
          f"released to buyer ${vv['released']} · decided by {vv['decided_by']}")
    return view, last


if __name__ == "__main__":
    main()
