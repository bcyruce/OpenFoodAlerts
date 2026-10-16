SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# Local settings; CI passes the same variables through the environment.
-include .env
export

DATABASE_URL ?= postgres://ofa:ofa@localhost:5432/ofa?sslmode=disable
TEST_DATABASE_URL ?= postgres://ofa:ofa@localhost:5432/ofa_test?sslmode=disable
OFA_WEB_PASSWORD ?= ofa_web_local
WEB_DATABASE_URL ?= postgres://ofa_web:$(OFA_WEB_PASSWORD)@localhost:5432/ofa?sslmode=disable
SMOKE_PORT ?= 3004
DBMATE := dbmate --migrations-dir db/migrations --no-dump-schema
UV := uv --directory pipeline
PNPM := pnpm --dir web
# Fixture snapshots for the web, loaded in this order (later snapshots become new versions).
WEB_FIXTURES := $(sort $(wildcard $(CURDIR)/pipeline/tests/fixtures/openfda/*.json)) \
	$(sort $(wildcard $(CURDIR)/web/e2e/fixtures/openfda/*.json)) \
	$(sort $(wildcard $(CURDIR)/pipeline/tests/fixtures/rasff/details/*.json)) \
	$(sort $(wildcard $(CURDIR)/web/e2e/fixtures/rasff/*.json)) \
	$(sort $(wildcard $(CURDIR)/pipeline/tests/fixtures/nvwa/detail/*.html))

.PHONY: help setup db-up migrate seed test-db db-roles db-types web-fixtures lint typecheck test check dev eval eval-refresh eval-example smoke

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: db-up ## Install dependencies, migrate and seed the local database
	$(UV) sync
	$(PNPM) install
	$(MAKE) migrate
	$(MAKE) seed
	$(MAKE) db-roles
	uv run --project pipeline pre-commit install

db-up: ## Start local Postgres 16 and wait until it is healthy
	docker compose up -d --wait db

migrate: ## Apply migrations to DATABASE_URL
	$(DBMATE) --url "$(DATABASE_URL)" --wait up

seed: ## Upsert db/seed/ into DATABASE_URL (idempotent)
	$(UV) run ofa load-seeds

test-db: ## Create, migrate and seed the database used by DB-backed tests
	$(DBMATE) --url "$(TEST_DATABASE_URL)" --wait up
	DATABASE_URL="$(TEST_DATABASE_URL)" $(UV) run ofa load-seeds

db-roles: ## Enable login for ofa_web with OFA_WEB_PASSWORD (roles are cluster-wide)
	$(UV) run ofa role-login ofa_web

# Generated from a throwaway, freshly migrated database: drizzle-kit follows catalog order,
# which only matches between databases that ran the same migrations from scratch.
TYPES_DATABASE_URL ?= postgres://ofa:ofa@localhost:5432/ofa_types?sslmode=disable

db-types: ## Regenerate web/db/generated/ (Drizzle) from a freshly migrated scratch database
	$(DBMATE) --url "$(TYPES_DATABASE_URL)" drop
	$(DBMATE) --url "$(TYPES_DATABASE_URL)" --wait up >/dev/null
	cd web && DATABASE_URL="$(TYPES_DATABASE_URL)" node scripts/db-types.mjs
	$(DBMATE) --url "$(TYPES_DATABASE_URL)" drop

web-fixtures: ## Archive and parse the openFDA, RASFF and NVWA fixtures into DATABASE_URL (dev/CI data)
	$(UV) run ofa load-fixtures $(WEB_FIXTURES)

lint: ## ruff + eslint
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(PNPM) lint

typecheck: ## mypy --strict + tsc
	$(UV) run mypy
	$(PNPM) typecheck

test: ## pytest with coverage gate + vitest (both use TEST_DATABASE_URL)
	$(UV) run pytest
	$(PNPM) test

check: lint typecheck test ## Everything CI runs locally

dev: ## Next.js dev server
	$(PNPM) dev

# Eval split: dev unless test is asked for explicitly (make eval SPLIT=test).
SPLIT ?= dev

eval: ## Offline eval of eval/cache/ + baselines on SPLIT (default dev) -> eval/results/latest.json
	$(UV) run ofa eval-run --split $(SPLIT)

eval-refresh: ## Call the configured classifiers on SPLIT and refresh eval/cache/ (paid API)
	$(UV) run ofa eval-refresh --split $(SPLIT)

eval-example: ## Regenerate the synthetic eval/results/example.json (for the /evaluation page)
	$(UV) run ofa eval-example

smoke: web-fixtures ## Playwright smoke tests: load fixtures, build, start on SMOKE_PORT
	$(PNPM) build
	$(PNPM) exec playwright test
