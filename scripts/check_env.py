"""Shows which environment variables are set, WITHOUT printing their values."""

from pathlib import Path
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    print("(python-dotenv not installed; reading the process environment only)")

GROUPS = {
    "PayPal (needed for Phase 1)": ["PAYPAL_CLIENT_ID", "PAYPAL_SECRET", "SANDBOX_WORKER_EMAIL"],
    "PayPal webhooks / login": ["PAYPAL_WEBHOOK_ID", "PAYPAL_LOGIN_REDIRECT_URI"],
    "AI judge": ["ANTHROPIC_API_KEY"],
    "Sandbox runner": ["E2B_API_KEY"],
    "Storage": ["DATABASE_URL", "REDIS_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"],
}

missing_required = False
for group, keys in GROUPS.items():
    print(group)
    for k in keys:
        ok = bool(os.getenv(k))
        print(f"  {'✓' if ok else '✗'} {k}")
        if not ok and group.startswith("PayPal (needed"):
            missing_required = True
if os.getenv("PAYPAL_ENV", "sandbox") != "sandbox":
    print("\n⚠ PAYPAL_ENV is not 'sandbox'.")
sys.exit(1 if missing_required else 0)
