"""Fresh-input generator: random inputs from the same distribution as the spec.
Accepted only if the reference solution runs on all generated inputs without error."""

import calendar
import random

LEVELS = ["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "info", "Warn", "error", "TRACE", "FATAL"]
WORDS = ["user", "login", "failed", "cache", "miss", "db", "timeout", "retry", "ok", "payment",
         "order", "shipped", "disk", "full", "gc", "pause", "ms", "id=42", "→", "ünïcode"]


def _ts(rng: random.Random) -> str:
    if rng.random() < 0.1:   # sometimes an invalid date or format
        return rng.choice(["2026-02-30T10:00:00Z", "2026-13-01T00:00:00Z", "2026-11-01 10:00:00",
                           "2026-11-01T25:00:00Z", "yesterday", "2026-11-01T10:00:00+05:30"])
    year, month = rng.randint(2020, 2028), rng.randint(1, 12)
    day = rng.randint(1, calendar.monthrange(year, month)[1])     # includes 29-31 and Feb 29
    return (f"{year:04d}-{month:02d}-{day:02d}"
            f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z")


def _line(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.05:
        return " " * rng.randint(0, 3)
    if r < 0.12:
        return " ".join(rng.choices(WORDS, k=rng.randint(1, 6)))       # garbage
    sep = lambda: rng.choice([" ", "  ", "\t", " \t"])                  # noqa: E731
    msg = " ".join(rng.choices(WORDS, k=rng.randint(0, 8)))
    pad = rng.choice(["", " ", "  "])
    return f"{pad}{_ts(rng)}{sep()}[{rng.choice(LEVELS)}]{sep()}{msg}{pad}"


def gen_input(rng: random.Random) -> str:
    # Keep fresh inputs SMALL (0-6 lines). Long inputs almost always contain every feature,
    # so one missing rule would fail nearly every input and honest partial work would earn $0.
    # Small inputs isolate rules, so the fresh pass rate tracks how much of the spec is done.
    return "\n".join(_line(rng) for _ in range(rng.randint(0, 6)))
