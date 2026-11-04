import json
import subprocess
import sys
from pathlib import Path

from verdict.grading.compare import outputs_match

HARNESS = Path(__file__).resolve().parents[1] / "verdict" / "sandbox" / "harness.py"


def test_json_comparison_ignores_formatting():
    assert outputs_match('[{"a": 1}]', '[ {"a":1} ]')
    assert not outputs_match('[{"a": 1}]', '[{"a": 2}]')
    assert not outputs_match("x", None)


def test_text_comparison_ignores_trailing_whitespace():
    assert outputs_match("a\nb", "a  \nb\n")
    assert not outputs_match("a\nb", "a\nc")


def run_harness(tmp_path, code, inputs):
    (tmp_path / "solution.py").write_text(code)
    stdin = "".join(json.dumps({"id": f"t{i}", "nonce": f"n{i}", "input": x}) + "\n"
                    for i, x in enumerate(inputs))
    proc = subprocess.run([sys.executable, str(HARNESS), str(tmp_path), "solution", "solve"],
                          input=stdin, capture_output=True, text=True, timeout=20,
                          env={"VERDICT_TEST_TIMEOUT_S": "0.5", "PATH": ""})
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def test_harness_returns_outputs_and_swallows_prints(tmp_path):
    code = "def solve(s):\n    print('FAKE PASS LINE')\n    return s.upper()\n"
    out = run_harness(tmp_path, code, ["ab", "cd"])
    assert [o["output"] for o in out] == ["AB", "CD"]
    assert [o["nonce"] for o in out] == ["n0", "n1"]


def test_harness_survives_exit_and_timeout(tmp_path):
    code = ("import sys, time\n"
            "def solve(s):\n"
            "    if s == 'exit': sys.exit(0)\n"
            "    if s == 'slow': time.sleep(5)\n"
            "    return s\n")
    out = run_harness(tmp_path, code, ["exit", "slow", "ok"])
    assert "SystemExit" in out[0]["error"]
    assert out[1]["error"] == "timeout"
    assert out[2]["output"] == "ok"
