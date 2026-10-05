SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# Local settings; CI passes the same variables through the environment.
-include .env
export

DATABASE_URL ?= postgres://ofa:ofa@localhost:5432/ofa?sslmode=disable
TEST_DATABASE_URL ?= postgres://ofa:ofa@localhost:5432/ofa_test?sslmode=disable
DBMATE := dbmate --migrations-dir db/migrations --no-dump-schema
UV := uv --directory pipeline
PNPM := pnpm --dir web

.PHONY: help setup db-up migrate test-db lint typecheck test check dev eval smoke

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: db-up ## Install dependencies, migrate and seed the local database
	$(UV) sync
	$(PNPM) install
	$(MAKE) migrate
	uv run --project pipeline pre-commit install

db-up: ## Start local Postgres 16 and wait until it is healthy
	docker compose up -d --wait db

migrate: ## Apply migrations to DATABASE_URL
	$(DBMATE) --url "$(DATABASE_URL)" --wait up

test-db: ## Create and migrate the database used by DB-backed tests
	$(DBMATE) --url "$(TEST_DATABASE_URL)" --wait up

lint: ## ruff + eslint
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(PNPM) lint

typecheck: ## mypy --strict + tsc
	$(UV) run mypy
	$(PNPM) typecheck

test: ## pytest with coverage gate
	$(UV) run pytest

check: lint typecheck test ## Everything CI runs locally

dev: ## Next.js dev server
	$(PNPM) dev

eval: ## Offline eval from cached model outputs (enabled by ticket 15)
	@echo "make eval: not implemented yet (ticket 15)"

smoke: ## Playwright smoke tests (enabled by ticket 04)
	@echo "make smoke: not implemented yet (ticket 04)"
