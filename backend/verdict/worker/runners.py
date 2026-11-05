"""Pick the sandbox runner from settings. LocalRunner is DEV ONLY (no isolation)."""

from __future__ import annotations

from verdict.config import Settings
from verdict.sandbox.runner import LocalRunner, Runner


def make_runner(cfg: Settings) -> Runner:
    if cfg.sandbox_backend == "e2b":
        from verdict.sandbox.e2b_runner import E2BRunner
        return E2BRunner(cfg.e2b_api_key)
    if cfg.sandbox_backend == "local":
        if cfg.paypal_env == "live":
            raise ValueError("SANDBOX_BACKEND=local runs untrusted code unisolated; not with live")
        return LocalRunner()
    raise ValueError(f"unknown SANDBOX_BACKEND {cfg.sandbox_backend!r} (e2b | local)")
