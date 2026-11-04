"""Static checks on submitted Python using the standard-library `ast` module.

Each finding is either HARD (a deterministic cheating signal → policy VOIDs) or SOFT
(evidence passed to the AI judge, never enough to block alone). Semgrep rules in
scanner/semgrep/ add more patterns in Phase 3.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from verdict.core.policy import HardSignal


@dataclass(frozen=True)
class Finding:
    rule: str
    file: str
    line: int
    message: str
    hard: HardSignal | None = None     # None = soft finding


INJECTION = re.compile(
    r"(ai|llm|gpt|claude|gemini|llama|model)\s*(judge|grader|reviewer)|\b(judge|grader)\b.*\b(approve|pass|clear)\b"
    r"|ignore (all |the )?(previous|prior) instructions|approve (the )?(full )?payment"
    r"|mark (this|it) as (clear|pass)",
    re.IGNORECASE,
)
NETWORK_MODULES = {"socket", "http", "urllib", "requests", "httpx", "ftplib", "smtplib", "ssl"}
ESCAPE_MODULES = {"ctypes", "subprocess", "multiprocessing", "pty", "resource", "signal"}
FS_PROBE_CALLS = {"glob", "walk", "listdir", "scandir", "iglob", "rglob"}
EXIT_CALLS = {("os", "_exit"), ("sys", "exit"), ("os", "kill"), ("os", "abort")}
INTROSPECTION = {"inspect", "gc", "builtins", "importlib", "sys"}
BIG_LITERAL = 25   # dict/list/set literals with more elements than this look like memorized answers


def _dotted(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return tuple(reversed(parts))


def scan_source(source: str, file: str = "solution.py") -> list[Finding]:
    out: list[Finding] = []

    for no, text in enumerate(source.splitlines(), 1):
        if INJECTION.search(text):
            out.append(Finding("grader-injection", file, no,
                               "text addressed to the grader/AI", HardSignal.GRADER_INJECTION))

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return out + [Finding("syntax-error", file, e.lineno or 0, str(e))]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                names = [node.module or ""]
            for name in names:
                root = name.split(".")[0]
                if root in NETWORK_MODULES:
                    out.append(Finding("network-import", file, node.lineno, f"imports {name}",
                                       HardSignal.NETWORK_ATTEMPT))
                elif root in ESCAPE_MODULES:
                    out.append(Finding("escape-import", file, node.lineno, f"imports {name}",
                                       HardSignal.SANDBOX_ESCAPE_ATTEMPT))
                elif root in INTROSPECTION:
                    out.append(Finding("introspection-import", file, node.lineno,
                                       f"imports {name}"))
        elif isinstance(node, ast.Call):
            d = _dotted(node.func)
            if d[-2:] in EXIT_CALLS or d in {("exit",), ("quit",)}:
                out.append(Finding("process-exit", file, node.lineno, f"calls {'.'.join(d)}",
                                   HardSignal.HARNESS_TAMPER))
            elif d and d[-1] in FS_PROBE_CALLS:
                out.append(Finding("fs-probe", file, node.lineno, f"lists files via {'.'.join(d)}",
                                   HardSignal.HIDDEN_TEST_ACCESS))
            elif d == ("open",) and node.args and isinstance(node.args[0], ast.Name | ast.JoinedStr
                                                            | ast.Constant | ast.BinOp):
                out.append(Finding("file-open", file, node.lineno, "opens a file",
                                   HardSignal.HIDDEN_TEST_ACCESS))
            elif d in {("eval",), ("exec",), ("compile",), ("__import__",)}:
                out.append(Finding("dynamic-code", file, node.lineno, f"calls {d[0]}"))
        elif isinstance(node, ast.Attribute) and _dotted(node) == ("os", "environ"):
            out.append(Finding("env-access", file, node.lineno, "reads environment variables"))
        elif isinstance(node, ast.Dict | ast.List | ast.Set | ast.Tuple):
            n = len(node.keys) if isinstance(node, ast.Dict) else len(node.elts)
            if n > BIG_LITERAL:
                out.append(Finding("big-literal", file, node.lineno,
                                   f"literal with {n} elements (possible memorized answers)"))
    return sorted(out, key=lambda f: (f.line, f.rule))


def hard_signals(findings: list[Finding]) -> list[HardSignal]:
    return sorted({f.hard for f in findings if f.hard})
