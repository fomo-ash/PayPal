# Use the project virtualenv when it exists, so `make` never picks up a global Python.
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python)

.PHONY: install test lint fmt api worker beat mcp spike e2b env services bench bench-ai secrets agent cheat migrate local demo

install:
	uv pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

lint:
	ruff check backend scripts agents bench
	mypy backend/verdict/core backend/verdict/db backend/verdict/worker

fmt:
	ruff format backend scripts agents bench

services:
	docker compose up -d

api:
	uvicorn verdict.api.main:app --reload --port 8000 --app-dir backend

migrate:
	alembic upgrade head

# Whole flow on one laptop: SQLite file + grading/payouts in-process (no Postgres/Redis).
LOCAL_DB := sqlite:///data/verdict.db
local:
	mkdir -p data
	DATABASE_URL=$(LOCAL_DB) $(PY) -m alembic -x url=$(LOCAL_DB) upgrade head
	DATABASE_URL=$(LOCAL_DB) INLINE_WORKER=true DEMO_LOGIN=true $(PY) -m uvicorn verdict.api.main:app --port 8000 --app-dir backend

SUB ?= honest_full
demo:
	$(PY) scripts/demo_flow.py $(SUB)

worker:
	cd backend && celery -A verdict.worker.celery_app worker -Q money,grading,judge -l info

beat:
	cd backend && celery -A verdict.worker.celery_app beat -l info

mcp:
	$(PY) -m verdict.mcp.server

agent:
	$(PY) agents/honest_agent.py $(JOB)

cheat:
	$(PY) agents/cheat_agent.py $(if $(filter cheat_%,$(SUB)),$(SUB),cheat_memorizer) $(JOB)

env:
	$(PY) scripts/check_env.py

spike:
	$(PY) scripts/sandbox_spike.py

e2b:
	$(PY) scripts/e2b_smoke.py

bench:
	$(PY) bench/run_bench.py

secrets:
	$(PY) scripts/gen_secrets.py

bench-ai:
	$(PY) bench/run_bench.py --ai
