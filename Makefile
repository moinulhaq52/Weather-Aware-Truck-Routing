# Convenience commands. Run `make setup` once, then `make dev` (two processes) or the individual targets.
PY := backend/.venv/bin/python
VENV_BIN := backend/.venv/bin

.PHONY: setup dev backend frontend test test-backend test-frontend lint format build docker

setup:
	python3 -m venv backend/.venv
	$(VENV_BIN)/pip install -r backend/requirements-dev.txt
	cd frontend && npm ci
	[ -f backend/.env ] || cp backend/.env.example backend/.env

backend:
	cd backend && .venv/bin/python manage.py runserver 8000

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

test: test-backend test-frontend

test-backend:
	cd backend && .venv/bin/pytest

test-frontend:
	cd frontend && npm test

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run lint && npm run typecheck && npm run format:check

format:
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
	cd frontend && npm run format

build:
	cd frontend && npm run build

docker:
	docker build -t weather-truck-routing .
