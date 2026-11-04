"""Files a submission may never contain. Any hit is a REJECTED_FILE hard signal."""

from __future__ import annotations

from pathlib import PurePosixPath

REJECTED_NAMES = {"conftest.py", "sitecustomize.py", "usercustomize.py", "pytest.ini",
                  "setup.cfg", "tox.ini", "pyproject.toml", "__main__.py"}
REJECTED_SUFFIXES = {".pth", ".so", ".dylib", ".dll", ".pyc", ".pyd", ".egg", ".whl"}
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 20


def check_files(files: dict[str, int]) -> list[str]:
    """files: relative path → size in bytes. Returns human-readable problems (empty = OK)."""
    problems: list[str] = []
    if len(files) > MAX_FILES:
        problems.append(f"too many files ({len(files)} > {MAX_FILES})")
    for rel, size in files.items():
        p = PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts:
            problems.append(f"{rel}: path escapes the submission folder")
        if p.name in REJECTED_NAMES:
            problems.append(f"{rel}: forbidden file name")
        if p.suffix in REJECTED_SUFFIXES:
            problems.append(f"{rel}: forbidden file type")
        if size > MAX_FILE_BYTES:
            problems.append(f"{rel}: larger than {MAX_FILE_BYTES} bytes")
    return problems
