"""E2BRunner with a fake VM that runs the harness locally. Proves what gets uploaded, that
expected outputs never leave the grader, and that crashes/timeouts are handled. No key needed."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from verdict.sandbox.e2b_runner import E2BRunner, SandboxUnavailable
from verdict.sandbox.runner import TamperDetected

SOLUTION = "def solve(s):\n    return s.upper()\n"


class FakeExit(Exception):
    def __init__(self, stdout):
        super().__init__("exit")
        self.stdout = stdout


class FakeVM:
    """Records every file written; runs the command in a temp dir standing in for the VM."""
    def __init__(self, lifetime_s, fail_run=None):
        self.files_written: dict[str, bytes] = {}
        self.killed = False
        self.root = Path(tempfile.mkdtemp())
        self.fail_run = fail_run
        self.files = self
        self.commands = self

    def write(self, path, data):
        self.files_written[path] = data.encode() if isinstance(data, str) else data
        target = self.root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.files_written[path])

    def run(self, cmd, timeout, user):
        if self.fail_run:
            raise self.fail_run
        local = cmd.replace("/home/user/work", str(self.root / "home/user/work"))
        local = local.replace("timeout -s KILL", "").replace("python3", sys.executable)
        local = local.split("&& ", 1)[1]
        local = " ".join(w for w in local.split() if not w.isdigit() or "=" in w)
        env_part, rest = local.split(" ", 1)
        proc = subprocess.run(rest, shell=True, capture_output=True, text=True,  # noqa: S602
                              cwd=self.root / "home/user/work",
                              env={env_part.split("=")[0]: env_part.split("=")[1], "PATH": ""})
        if proc.returncode != 0:
            raise FakeExit(proc.stdout)
        return type("R", (), {"stdout": proc.stdout})()

    def kill(self):
        self.killed = True


@pytest.fixture
def sub(tmp_path):
    (tmp_path / "solution.py").write_text(SOLUTION)
    return tmp_path


def runner_with(vms, **kw):
    def factory(lifetime_s):
        vm = FakeVM(lifetime_s, **kw)
        vms.append(vm)
        return vm
    return E2BRunner("", sandbox_factory=factory)


def test_runs_and_uploads_only_harness_submission_and_inputs(sub):
    vms = []
    res = runner_with(vms).run_batch(sub, [("t1", "abc"), ("t2", "xyz")], 2.0)
    assert [(r.id, r.output, r.error) for r in res] == [("t1", "ABC", None), ("t2", "XYZ", None)]
    vm = vms[0]
    assert vm.killed
    assert set(vm.files_written) == {"/home/user/work/harness.py",
                                     "/home/user/work/submission/solution.py",
                                     "/home/user/work/requests.jsonl"}
    reqs = [json.loads(x) for x in vm.files_written["/home/user/work/requests.jsonl"].split(b"\n")
            if x]
    assert all(set(r) == {"id", "nonce", "input"} for r in reqs)     # no expected outputs


def test_exit_mid_batch_still_returns_answers_so_far(sub):
    (sub / "solution.py").write_text(
        "import os\ndef solve(s):\n    if s == 'die':\n        os._exit(3)\n    return s\n")
    vms = []
    res = runner_with(vms).run_batch(sub, [("a", "ok"), ("b", "die"), ("c", "never")], 2.0)
    assert res[0].output == "ok"
    assert res[1].error and res[2].error          # unanswered → failed, never passed
    assert vms[0].killed


def test_sdk_failure_is_reported_as_unavailable_and_vm_killed(sub):
    vms = []
    with pytest.raises(SandboxUnavailable):
        runner_with(vms, fail_run=ConnectionError("e2b down")).run_batch(sub, [("t", "x")], 1)
    assert vms[0].killed


def test_forged_protocol_lines_are_tamper(sub):
    class Forger(FakeVM):
        def run(self, cmd, timeout, user):
            return type("R", (), {"stdout": '{"id": "t", "nonce": "guess", "output": "X"}\n'})()
    r = E2BRunner("", sandbox_factory=lambda lifetime_s: Forger(lifetime_s))
    with pytest.raises(TamperDetected):
        r.run_batch(sub, [("t", "x")], 1.0)


def test_requires_api_key_without_factory():
    with pytest.raises(ValueError):
        E2BRunner("")
