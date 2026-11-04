"""Buyer's reference solution. Must pass 100% of hidden tests before the job can be funded.
It is also the oracle for fresh random inputs. It never enters the worker's sandbox."""

import json
import re
from datetime import datetime

LINE = re.compile(r"^(\S+)[ \t]+\[([A-Za-z]+)\][ \t]+(.*)$")
LEVELS = {"DEBUG": "DEBUG", "INFO": "INFO", "WARN": "WARN", "WARNING": "WARN", "ERROR": "ERROR"}


def _valid_ts(ts: str) -> bool:
    if len(ts) != 20:
        return False
    try:
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def solve(input: str) -> str:
    entries, skipped = [], 0
    counts = {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0}
    for raw in input.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = LINE.match(line)
        level = LEVELS.get(m.group(2).upper()) if m else None
        msg = m.group(3).strip() if m else ""
        if not m or not level or not msg or not _valid_ts(m.group(1)):
            skipped += 1
            continue
        entries.append({"ts": m.group(1), "level": level, "msg": msg})
        counts[level] += 1
    return json.dumps({"entries": entries, "skipped": skipped, "counts": counts})
