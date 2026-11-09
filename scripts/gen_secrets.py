"""Fill RECEIPT_SIGNING_KEY_B64 and SESSION_SECRET in .env if they are empty.

Prints key names and the receipt key id only, never a secret value.
Run: python scripts/gen_secrets.py   (or: make secrets)
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from verdict.receipts import signing  # noqa: E402

ENV = ROOT / ".env"


def main() -> int:
    if not ENV.exists():
        print(".env not found; copy .env.example to .env first")
        return 1
    text = ENV.read_text()
    made = {
        "RECEIPT_SIGNING_KEY_B64": signing.generate_private_key_b64,
        "SESSION_SECRET": lambda: secrets.token_urlsafe(48),
    }
    for name, make in made.items():
        m = re.search(rf"^{name}=(.*)$", text, flags=re.M)
        current = (m.group(1).split("#")[0].strip() if m else "")
        if current:
            print(f"{name}: already set, left alone")
            continue
        value = make()
        if m:
            text = text[:m.start()] + f"{name}={value}" + text[m.end():]
        else:
            text = text.rstrip("\n") + f"\n{name}={value}\n"
        print(f"{name}: generated")
    ENV.write_text(text)
    key = re.search(r"^RECEIPT_SIGNING_KEY_B64=(\S+)", text, flags=re.M)
    if key:
        print("receipt key id:", signing.key_id(signing.public_key_b64(key.group(1))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
