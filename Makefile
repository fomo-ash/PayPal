.PHONY: install test lint fmt api worker beat mcp spike env services bench

install:
	uv pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	ruff check backend scripts agents bench
	mypy backend/verdict/core

fmt:
	ruff format backend scripts agents bench

services:
	docker compose up -d

api:
	uvicorn verdict.api.main:app --reload --port 8000 --app-dir backend

worker:
	cd backend && celery -A verdict.worker.celery_app worker -l info

beat:
	cd backend && celery -A verdict.worker.celery_app beat -l info

mcp:
	python -m verdict.mcp.server

env:
	python scripts/check_env.py

spike:
	python scripts/sandbox_spike.py

bench:
	python bench/run_bench.py
