"""Signed receipts (Phase 4).

receipt = canonical JSON {job, suite_sha256, submission_sha256, results, ai_findings,
          decision, paypal: {order_id, authorization_id, capture_id, payout_batch_id},
          audit_head_hash, issued_at}
signature = Ed25519(private_key, canonical_bytes). Anyone verifies on /verify with the public key.
"""

import json


def canonical_bytes(receipt: dict) -> bytes:
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(receipt: dict, private_key_b64: str) -> str:
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    return base64.b64encode(key.sign(canonical_bytes(receipt))).decode()
