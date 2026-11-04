"""Hash-chained audit log (Phase 4).

Each row stores sha256(prev_hash || canonical_json(event)). Changing any past event breaks
every later hash. The final hash goes into the signed receipt.
"""

import hashlib
import json


def chain_hash(prev_hash: str, event: dict) -> str:
    blob = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev_hash + blob).encode()).hexdigest()
