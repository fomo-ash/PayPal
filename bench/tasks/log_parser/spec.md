# Job: Parse application logs into clean JSON

**Budget:** $100.00 · **Minimum score:** 50% · **Deadline:** 24h · **Language:** Python 3.12

## Function to implement
```python
def solve(input: str) -> str:
    """Return a JSON string (any formatting) as described below."""
```
File name: `solution.py`. Standard library only. No network, no files, no environment access.

## Input
A string containing zero or more lines separated by `\n`.

## A valid line
```
<timestamp> [<LEVEL>] <message>
```
- **timestamp**: `YYYY-MM-DDTHH:MM:SSZ` (UTC) and a real calendar date/time (`2026-02-30T…` is invalid).
- **LEVEL**: one of `DEBUG`, `INFO`, `WARN`, `WARNING`, `ERROR`, case-insensitive. `WARNING` is normalised to `WARN`. Output levels are upper-case.
- Between the parts: one or more spaces or tabs.
- **message**: everything after the level, with leading/trailing whitespace removed. It must not be empty.
- Leading/trailing whitespace on the whole line is ignored.

## Output
```json
{
  "entries": [{"ts": "2026-11-01T10:00:00Z", "level": "INFO", "msg": "server started"}],
  "skipped": 0,
  "counts": {"DEBUG": 0, "INFO": 1, "WARN": 0, "ERROR": 0}
}
```
- `entries`: valid lines, in input order.
- `skipped`: number of non-blank lines that are not valid.
- Blank (whitespace-only) lines are ignored and **not** counted as skipped.
- `counts`: always contains all four levels.

## Test groups (hidden tests are sealed; counts and weights are public)
| Group | Weight | Hidden tests | Fresh random inputs |
|---|---|---|---|
| core | 60% | 10 | 200 |
| edge | 25% | 8 | none |
| perf | 15% | 2 (3,000 lines each, 2s limit) | none |
