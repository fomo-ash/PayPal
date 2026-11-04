"""Day-1 risk spike: proves the whole Verdict money flow works in YOUR PayPal sandbox.

Run:  python scripts/sandbox_spike.py
Needs in .env: PAYPAL_CLIENT_ID, PAYPAL_SECRET, SANDBOX_WORKER_EMAIL

What it checks (README "Check these on day 1"):
  A. create order (intent=AUTHORIZE) → you approve as the sandbox BUYER in the browser
  B. authorize → authorization id
  C. partial capture $81.50 of $100 with final_capture=true → is the remaining $18.50 released?
  D. a second order, authorized then VOIDED → buyer pays nothing
  E. payout $77.42 to the sandbox WORKER → batch status
Secrets are never printed.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from verdict.paypal.client import PayPalClient, PayPalError  # noqa: E402

BASE = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
RUN = uuid.uuid4().hex[:8]


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


def approve_and_authorize(pp: PayPalClient, label: str) -> str:
    order = pp.create_authorize_order(
        amount="100.00", currency="USD", reference_id=f"spike-{RUN}-{label}",
        description=f"Verdict spike {label}",
        return_url="https://example.com/verdict/return", cancel_url="https://example.com/verdict/cancel",
        idempotency_key=f"spike-{RUN}-{label}-order")
    link = pp.approve_link(order)
    print(f"order {order['id']} status={order['status']}")
    print(f"Approve as the sandbox BUYER (personal account) here:\n  {link}")
    try:
        webbrowser.open(link)
    except Exception:  # noqa: BLE001
        pass
    input("After approving (you'll land on example.com), press Enter… ")
    for _ in range(10):
        if pp.get_order(order["id"])["status"] == "APPROVED":
            break
        time.sleep(1.5)
    authorized = pp.authorize_order(order["id"], idempotency_key=f"spike-{RUN}-{label}-auth")
    auth_id = pp.authorization_id(authorized)
    a = pp.get_authorization(auth_id)
    print(f"authorization {auth_id} status={a['status']} amount={a['amount']['value']} "
          f"expires={a.get('expiration_time')}")
    return auth_id


def main() -> int:
    env = os.getenv("PAYPAL_ENV", "sandbox")
    if env != "sandbox":
        print("Refusing to run against live. Set PAYPAL_ENV=sandbox.")
        return 2
    worker = os.getenv("SANDBOX_WORKER_EMAIL", "")
    pp = PayPalClient(BASE[env], os.getenv("PAYPAL_CLIENT_ID", ""), os.getenv("PAYPAL_SECRET", ""))
    results: dict[str, str] = {}
    try:
        step("0. OAuth token")
        pp.token()
        print("token OK")
        results["token"] = "PASS"

        step("A–C. authorize $100, capture $81.50 with final_capture=true")
        auth1 = approve_and_authorize(pp, "capture")
        cap = pp.capture_authorization(auth1, amount="81.50", currency="USD", final_capture=True,
                                       idempotency_key=f"spike-{RUN}-capture",
                                       invoice_id=f"spike-{RUN}")
        print(f"capture {cap['id']} status={cap['status']}")
        again = pp.capture_authorization(auth1, amount="81.50", currency="USD", final_capture=True,
                                         idempotency_key=f"spike-{RUN}-capture",
                                         invoice_id=f"spike-{RUN}")
        results["idempotent capture retry"] = "PASS" if again["id"] == cap["id"] else "CHECK"
        a = pp.get_authorization(auth1)
        print(f"authorization after capture: status={a['status']}")
        results["partial capture"] = "PASS" if cap["status"] in ("COMPLETED", "PENDING") else "CHECK"
        results["remainder released (status CAPTURED)"] = "PASS" if a["status"] == "CAPTURED" else f"CHECK ({a['status']})"

        step("D. authorize a second $100 and VOID it")
        auth2 = approve_and_authorize(pp, "void")
        pp.void_authorization(auth2, idempotency_key=f"spike-{RUN}-void")
        a2 = pp.get_authorization(auth2)
        print(f"authorization {auth2} status={a2['status']}")
        results["void"] = "PASS" if a2["status"] == "VOIDED" else f"CHECK ({a2['status']})"

        step("E. payout $77.42 to the sandbox worker")
        if not worker:
            results["payout"] = "SKIPPED (set SANDBOX_WORKER_EMAIL)"
        else:
            batch = pp.create_payout(batch_id=f"spike-{RUN}-payout", receiver=worker,
                                     recipient_type="EMAIL", amount="77.42", currency="USD",
                                     note="Verdict sandbox spike")
            bid = batch["batch_header"]["payout_batch_id"]
            status = batch["batch_header"]["batch_status"]
            for _ in range(10):
                if status in ("SUCCESS", "DENIED", "CANCELED"):
                    break
                time.sleep(3)
                status = pp.get_payout_batch(bid)["batch_header"]["batch_status"]
            print(f"payout batch {bid} status={status}")
            results["payout"] = "PASS" if status == "SUCCESS" else f"CHECK ({status})"
    except PayPalError as e:
        print(f"\nPayPal error: HTTP {e.status} debug_id={e.debug_id}\n{e.body}")
        results["error"] = f"HTTP {e.status}"
    finally:
        pp.close()

    step("RESULTS")
    for k, v in results.items():
        print(f"  {k:<42} {v}")
    print("\nLog in at https://www.sandbox.paypal.com as buyer/worker to see the balances.")
    return 0 if all(v == "PASS" for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
