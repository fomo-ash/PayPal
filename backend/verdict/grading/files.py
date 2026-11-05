"""Worker code uploads: {"files": {"solution.py": "<source>", "helpers/x.py": "..."}}.

Paths are checked here (no absolute paths, no "..", no hidden files) before anything touches
disk; the reject list (scanner.reject_list) then runs on the result like on any submission.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*")
MAX_FILES = 50
MAX_TOTAL_BYTES = 1_000_000
ENTRY = "solution.py"


class FilesError(ValueError):
    pass


def parse_files(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise FilesError('files must be a non-empty object {"path": "source"}')
    if len(raw) > MAX_FILES:
        raise FilesError(f"at most {MAX_FILES} files")
    total = 0
    out: dict[str, str] = {}
    for path, src in raw.items():
        if not isinstance(path, str) or not PATH.fullmatch(path) or len(path) > 200 \
                or ".." in path.split("/"):
            raise FilesError(f"bad file path {path!r}")
        if not isinstance(src, str):
            raise FilesError(f"{path}: content must be text")
        total += len(src.encode())
        out[path] = src
    if total > MAX_TOTAL_BYTES:
        raise FilesError(f"submission is larger than {MAX_TOTAL_BYTES} bytes")
    if ENTRY not in out:
        raise FilesError(f"{ENTRY} with solve(input) -> str is required")
    return dict(sorted(out.items()))


def files_sha256(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False)
                          .encode()).hexdigest()


def write_tree(files: dict[str, str], root: Path) -> Path:
    for rel, src in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)
    return root
