import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from verdict.core.policy import Settlement
from verdict.grading import oracle
from verdict.grading.pipeline import grade
from verdict.grading.suite import SuiteError, parse_upload
from verdict.sandbox.runner import LocalRunner
from verdict.storage import LocalBlobStore

BENCH = Path(__file__).resolve().parents[2] / "bench" / "tasks" / "log_parser"


def test_bench_suite_parses_and_seal_is_stable(bench_upload):
    a = parse_upload(bench_upload)
    b = parse_upload(copy.deepcopy(bench_upload))
    assert a.sha256 == b.sha256 and len(a.sha256) == 64
    assert a.doc["groups"] == {"core": "0.60", "edge": "0.25", "perf": "0.15"}


@pytest.mark.parametrize("change", [
    lambda u: u["tests"][0].update(expected="tampered"),
    lambda u: u.update(reference=u["reference"] + "\n# edited\n"),
    lambda u: u.update(generator=u["generator"] + "\n# edited\n"),
    lambda u: u["examples"].append({"input": "x", "expected": "y"}),
])
def test_any_change_breaks_the_seal(bench_upload, change):
    before = parse_upload(bench_upload).sha256
    changed = copy.deepcopy(bench_upload)
    change(changed)
    assert parse_upload(changed).sha256 != before


@pytest.mark.parametrize("change, msg", [
    (lambda u: u["groups"].update(core="0.61"), "sum to exactly 1"),
    (lambda u: u["groups"].update(core=0.60), "decimal string"),
    (lambda u: u["tests"].append(dict(u["tests"][0])), "duplicate test id"),
    (lambda u: u["tests"][0].update(group="nope"), "unknown group"),
    (lambda u: u["tests"][0].update(id="fresh-1"), "bad test id"),
    (lambda u: u.update(tests=[t for t in u["tests"] if t["group"] != "perf"]), "without tests"),
    (lambda u: u.update(generator=None), "need a generator"),
    (lambda u: u["fresh"].update(core=5000), "fresh count"),
    (lambda u: u.update(reference="def other(x):\n    return x\n"), "solve()"),
    (lambda u: u.update(reference="def solve(:"), "syntax error"),
])
def test_bad_uploads_rejected(bench_upload, change, msg):
    change(bench_upload)
    with pytest.raises(SuiteError, match=msg):
        parse_upload(bench_upload)


def test_reference_runs_in_runner_and_matches_expected(bench_upload):
    tests = bench_upload["tests"][:5]
    out = oracle.run_reference(LocalRunner(), bench_upload["reference"],
                               [(t["id"], t["input"]) for t in tests], 2.0)
    assert out == {t["id"]: t["expected"] for t in tests}


def test_generator_is_deterministic_per_seed_and_group(bench_upload):
    gen = bench_upload["generator"]
    a = oracle.generate_inputs(LocalRunner(), gen, 42, {"core": 20, "edge": 3})
    b = oracle.generate_inputs(LocalRunner(), gen, 42, {"core": 20, "edge": 3})
    c = oracle.generate_inputs(LocalRunner(), gen, 43, {"core": 20, "edge": 3})
    assert a == b and a != c
    assert [fid for fid, _ in a["core"]][:2] == ["fresh-core-0", "fresh-core-1"]
    assert a["core"][:3] != a["edge"]


def test_broken_generator_raises(bench_upload):
    with pytest.raises(oracle.OracleError):
        oracle.generate_inputs(LocalRunner(), "def gen_input(rng):\n    return 1\n", 1, {"g": 2})


@pytest.mark.parametrize("name, settlement", [("honest_full", Settlement.CAPTURE),
                                              ("cheat_memorizer", Settlement.VOID)])
def test_sandboxed_fresh_inputs_catch_the_memorizer(bench_upload, name, settlement):
    up = parse_upload(bench_upload)
    runner = LocalRunner()
    build = oracle.fresh_builder(runner, up.generator, up.reference, {"core": 40}, 2.0)
    r = grade(BENCH / "submissions" / name, up.pipeline_suite(Decimal("0.50")), runner,
              None, None, "100.00", 500, fresh_builder=build)
    assert r.decision.settlement is settlement
    assert r.fresh["core"][1] == 40


def test_blob_store_round_trip_and_rejects_escape(tmp_path):
    store = LocalBlobStore(tmp_path)
    store.put("suites/j1/tests.json", json.dumps({"a": 1}).encode())
    assert json.loads(store.get("suites/j1/tests.json")) == {"a": 1}
    for bad in ["../x", "a/../../x", "/etc/passwd", "a//b", ""]:
        with pytest.raises(ValueError):
            store.put(bad, b"x")
