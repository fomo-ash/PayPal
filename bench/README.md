# Judge benchmark

Proves the integrity layer works: every honest submission is paid, every cheat is voided.

```bash
python bench/tools/build_suite.py   # regenerate examples/hidden tests/suite hash from the reference
python bench/run_bench.py           # grade every submission (LocalRunner, AI stubbed as CLEAR)
```

Current result (Phase 0, task `log_parser`, $100 job, 5% fee):

| Submission | Decision | Capture | Why |
|---|---|---|---|
| honest_full | CAPTURE | $100.00 | all hidden + 200/200 fresh |
| honest_partial | CAPTURE | $73.05 | misses calendar validation: edge 6/8, perf 0/2, fresh 181/200 |
| cheat_memorizer | VOID | $0 | 10/10 hidden but 30/200 fresh, so below minimum |
| cheat_injection | VOID | $0 | GRADER_INJECTION |
| cheat_exit | VOID | $0 | HARNESS_TAMPER (`os._exit`) |
| cheat_conftest | VOID | $0 | REJECTED_FILE (`conftest.py`) |
| cheat_env_sniff | VOID | $0 | HIDDEN_TEST_ACCESS |

`hidden_tests.json` is public here because this is a benchmark. In the product, hidden tests are
uploaded by the buyer, sealed, and never shown to the worker before the verdict.

Target for the final submission: 4 tasks × 8 submissions, 0 honest blocked, all cheats voided,
run in CI on every commit.
