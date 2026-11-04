"""Output comparison. Runs OUTSIDE the sandbox, so submitted code can never influence pass/fail.

The default rule: if both sides parse as JSON, compare the parsed values;
otherwise compare strings with trailing whitespace on each line removed.
Jobs may choose a stricter mode later (exact bytes) or a float tolerance.
"""

from __future__ import annotations

import json
import math
from typing import Any


def _normalise_text(s: str) -> str:
    return "\n".join(line.rstrip() for line in s.strip().splitlines())


def _close(a: Any, b: Any, rel_tol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=rel_tol)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y, rel_tol) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], rel_tol) for k in a)
    return a == b


def outputs_match(expected: str, actual: str | None, rel_tol: float = 0.0) -> bool:
    if actual is None:
        return False
    try:
        return _close(json.loads(expected), json.loads(actual), rel_tol)
    except (json.JSONDecodeError, TypeError):
        return _normalise_text(expected) == _normalise_text(actual)
