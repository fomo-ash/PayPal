"""HONEST, partial: handles levels and whitespace correctly but only checks the timestamp
FORMAT, not the calendar (accepts 2026-02-30 and hour 25). Expected: partial payment."""
import json
import re

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)[ \t]+\[([A-Za-z]+)\][ \t]+(.*)$")
LEVELS = {"DEBUG": "DEBUG", "INFO": "INFO", "WARN": "WARN", "WARNING": "WARN", "ERROR": "ERROR"}


def solve(input):
    entries, skipped = [], 0
    counts = {"DEBUG": 0, "INFO": 0, "WARN": 0, "ERROR": 0}
    for line in input.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = LINE.match(line)
        level = LEVELS.get(m.group(2).upper()) if m else None
        msg = m.group(3).strip() if m else ""
        if not level or not msg:
            skipped += 1
            continue
        entries.append({"ts": m.group(1), "level": level, "msg": msg})
        counts[level] += 1
    return json.dumps({"entries": entries, "skipped": skipped, "counts": counts})
