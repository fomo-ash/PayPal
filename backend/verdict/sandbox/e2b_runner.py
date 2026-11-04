"""E2B microVM runner (Phase 1 spike, Phase 2 production).

Per run_batch call:
  1. Sandbox.create(timeout=...)  (Firecracker VM, internet access disabled)
  2. upload harness.py + submission files ONLY. Never the suite, never expected outputs.
  3. run `python -I harness.py /work/submission solution solve` with the requests on stdin
  4. read stdout, kill the VM, return verdict.sandbox.runner.parse_responses(...)
Limits: VERDICT_TEST_TIMEOUT_S per test, wall-clock cap per batch, output size cap.
Check on day 1: cold start time, and that outbound network is really blocked.
"""
