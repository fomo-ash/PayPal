# Contributing

## Branches
- `main`: always deployable and protected. Changes go in only through a PR with 1 approval and green CI.
- Work branches: `<name>/<area>-<short-desc>`, e.g. `anurag/phase-0-scaffold`, `riya/paypal-outbox`, `dev/e2b-runner`.
- Keep PRs small (under ~400 lines when possible). Rebase on `main` before opening one:
  ```bash
  git fetch origin
  git rebase origin/main
  ```

## Commits
[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, with an optional scope, e.g. `feat(paypal): partial capture with idempotency key`.

## Before you push
```bash
make test        # unit tests + bench
make lint        # ruff + mypy on core
python scripts/check_env.py
git status       # make sure .env is NOT staged
```

## Rules
1. **Never commit secrets.** `.env` is ignored. If a key leaks, rotate it in the PayPal dashboard immediately.
2. Money logic lives only in `core/scoring.py` and `core/policy.py`; any change needs a test.
3. Every state change goes through `core/state_machine.transition`.
4. Only the money worker calls capture, void and payout, with a deterministic `PayPal-Request-Id`.
5. Never pass expected outputs to a runner.
6. New cheat idea? Add it to `bench/tasks/*/submissions/` with an expected outcome in `bench/run_bench.py`.

## Code style
Python 3.12, ruff (line length 100), type hints on public functions, `Decimal` for money. TypeScript strict mode in `apps/web`.
