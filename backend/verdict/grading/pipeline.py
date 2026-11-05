"""Grading pipeline: reject list → static scan → hidden tests → fresh inputs → score → policy.

Phase 0 runs fully locally (LocalRunner) with the AI judge stubbed as CLEAR, which is enough
to validate the deterministic half of the system on the bench. Phase 2 swaps in E2BRunner and
Phase 3 adds the real AI judge (verdict.judge.review) between scoring and policy.
"""

from __future__ import annotations

import random
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from verdict.core.policy import AIDecision, HardSignal, PolicyResult, Settlement, decide
from verdict.core.scoring import GroupResult, Payout, compute_payout
from verdict.grading.compare import outputs_match
from verdict.sandbox.runner import Runner, RunResult, TamperDetected
from verdict.scanner.ast_rules import Finding, hard_signals, scan_source
from verdict.scanner.reject_list import check_files


@dataclass
class Suite:
    groups: dict[str, Decimal]                 # name → weight
    fresh: dict[str, int]                      # name → number of fresh inputs
    min_score: Decimal
    tests: list[dict]                          # {"id","group","input","expected"}


@dataclass
class GradeReport:
    rejected: list[str]
    findings: list[Finding]
    signals: list[HardSignal]
    hidden: dict[str, tuple[int, int]] = field(default_factory=dict)   # group → (passed, total)
    fresh: dict[str, tuple[int, int]] = field(default_factory=dict)
    flaky: list[str] = field(default_factory=list)
    payout: Payout | None = None
    decision: PolicyResult | None = None
    seed: int | None = None          # stored with the verdict so the grading can be replayed


FreshBuilder = Callable[[int], tuple[dict[str, list[tuple[str, str]]], dict[str, str]]]


def new_seed() -> int:
    """Secret per-submission seed, drawn AFTER the code is submitted. A fixed or guessable seed
    would let a worker generate the fresh inputs in advance and hard-code the answers."""
    return secrets.randbits(64)


def _passed(results: list[RunResult], expected: dict[str, str]) -> dict[str, bool]:
    return {r.id: r.error is None and outputs_match(expected[r.id], r.output) for r in results}


def grade(
    submission_dir: Path,
    suite: Suite,
    runner: Runner,
    reference_solve: Callable[[str], str] | None,
    gen_input: Callable[[random.Random], str] | None,
    amount: str,
    fee_bps: int,
    timeout_s: float = 2.0,
    seed: int | None = None,
    ai_decision: AIDecision = AIDecision.CLEAR,
    fresh_builder: FreshBuilder | None = None,
) -> GradeReport:
    """Bench/dev: pass reference_solve + gen_input (in-process). Production: pass
    fresh_builder (grading.oracle), which runs the buyer's code in its own sandbox."""
    files = {str(p.relative_to(submission_dir)): p.stat().st_size
             for p in submission_dir.rglob("*") if p.is_file()}
    rejected = check_files(files)
    findings: list[Finding] = []
    for rel in files:
        if rel.endswith(".py"):
            findings += scan_source((submission_dir / rel).read_text(errors="replace"), rel)
    signals = hard_signals(findings) + ([HardSignal.REJECTED_FILE] if rejected else [])
    report = GradeReport(rejected, findings, sorted(set(signals)))
    report.seed = new_seed() if seed is None else seed

    if rejected:   # never execute a submission that failed the reject list
        report.decision = PolicyResult(Settlement.VOID, Decimal(0),
                                       "rejected files: " + "; ".join(rejected))
        return report
    if report.signals:   # a hard signal voids regardless of tests; don't spend sandbox time
        report.decision = decide(zero_payout(suite, amount, fee_bps), report.signals, ai_decision)
        return report

    expected = {t["id"]: t["expected"] for t in suite.tests}
    inputs = [(t["id"], t["input"]) for t in suite.tests]
    try:
        first = _passed(runner.run_batch(submission_dir, inputs, timeout_s), expected)
        # Re-run failures with identical inputs; a flip means nondeterminism → exclude the test.
        failed = [(tid, x) for tid, x in inputs if not first[tid]]
        if failed:
            second = _passed(runner.run_batch(submission_dir, failed, timeout_s), expected)
            report.flaky = [tid for tid in second if second[tid]]

        fresh_cases: dict[str, list[tuple[str, str]]] = {}
        fresh_expected: dict[str, str] = {}
        if fresh_builder is not None:
            fresh_cases, fresh_expected = fresh_builder(report.seed)
        elif suite.fresh:
            if gen_input is None or reference_solve is None:
                raise ValueError("fresh inputs need gen_input + reference_solve or fresh_builder")
            rng = random.Random(report.seed)  # noqa: S311 - seed is secret; Random only expands it
            for g, n in suite.fresh.items():
                fresh_cases[g] = []
                for i in range(n):
                    x = gen_input(rng)
                    fid = f"fresh-{g}-{i}"
                    fresh_cases[g].append((fid, x))
                    fresh_expected[fid] = reference_solve(x)
        fresh_pass: dict[str, bool] = {}
        all_fresh = [c for cases in fresh_cases.values() for c in cases]
        if all_fresh:
            fresh_pass = _passed(runner.run_batch(submission_dir, all_fresh, timeout_s),
                                 fresh_expected)
    except TamperDetected:
        report.signals = sorted(set(report.signals) | {HardSignal.HARNESS_TAMPER})
        report.decision = decide(zero_payout(suite, amount, fee_bps), report.signals, ai_decision)
        return report

    by_group: dict[str, list[bool]] = {g: [] for g in suite.groups}
    for t in suite.tests:
        if t["id"] not in report.flaky:
            by_group[t["group"]].append(first[t["id"]])
    report.hidden = {g: (sum(v), len(v)) for g, v in by_group.items()}
    report.fresh = {g: (sum(fresh_pass[f] for f, _ in cases), len(cases))
                    for g, cases in fresh_cases.items() if cases}

    groups = [GroupResult(g, w, *report.hidden[g],
                          *(report.fresh[g] if g in report.fresh else (None, None)))
              for g, w in suite.groups.items()]
    report.payout = compute_payout(amount, groups, suite.min_score, fee_bps)
    report.decision = decide(report.payout, report.signals, ai_decision)
    return report


def zero_payout(suite: Suite, amount: str, fee_bps: int) -> Payout:
    groups = [GroupResult(g, w, 0, 1) for g, w in suite.groups.items()]
    return compute_payout(amount, groups, suite.min_score, fee_bps)
