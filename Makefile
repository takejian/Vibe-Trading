# Vibe-Trading — unified local task entry point.
# Run `make help` for the annotated target list.

PY := .venv/bin/python
PIP := $(PY) -m pip

.PHONY: help install lint lint-deps lint-quality lint-manifest test test-fast test-safety test-cov serve db-init fe-install fe-build fe-test eval-tests check

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install package editable with dev extras
	$(PIP) install -e '.[dev]'

lint: lint-deps lint-quality ## Run architecture/ruff/safety hard gates (reports stay non-blocking)
	@echo "[lint] all gates passed"

lint-deps: ## Enforce agent/src package-layer rules against harness/config/layer-map.json
	$(PY) scripts/lint-deps

lint-quality: ## Run ruff bug-rule hard gate, safety grep/AST gates and non-blocking debt reports
	bash scripts/lint-quality

lint-manifest: ## Report pyproject vs agent/requirements.txt dependency drift (use ARGS=--strict to fail)
	$(PY) scripts/lint-manifest $(ARGS)

test: ## Run default pytest suite with coverage (same ignores as CI)
	$(PY) -m pytest --ignore=agent/tests/e2e_backtest --ignore=agent/tests/test_e2e_harness_v2.py --cov=agent --cov-report=term-missing --tb=short -q agent/tests

test-fast: ## Run only tests marked 'unit' (zero collected is acceptable)
	$(PY) -m pytest -m unit -q agent/tests

test-safety: ## Run existing order-gate/mandate/killswitch/readonly safety tests
	@for f in agent/tests/test_sdk_order_gate.py agent/tests/test_mandate_enforcement.py agent/tests/test_killswitch_blocks_orders.py agent/tests/test_readonly_default.py; do \
		if [ -f "$$f" ]; then \
			echo "[test-safety] $$f"; \
			$(PY) -m pytest -q "$$f" || exit 1; \
		else \
			echo "[test-safety] skip missing file: $$f"; \
		fi; \
	done

test-cov: ## Like 'test', additionally write coverage.xml
	$(PY) -m pytest --ignore=agent/tests/e2e_backtest --ignore=agent/tests/test_e2e_harness_v2.py --cov=agent --cov-report=term-missing --cov-report=xml --tb=short -q agent/tests

serve: ## Start API server via harness lifecycle script (HOST/PORT overridable)
	bash harness/scripts/start-server.sh

db-init: ## Populate local DuckDB warehouse (~/.vibe-trading/data/market.duckdb)
	cd agent && $(PY) scripts/local_db/init_local_db.py

fe-install: ## Install frontend dependencies with npm ci
	cd frontend && npm ci

fe-build: ## Build frontend production bundle
	cd frontend && npm run build

fe-test: ## Run frontend vitest suite once
	cd frontend && npx vitest run

eval-tests: ## Run offline harness artifact-verifier contract tests
	$(PY) -m pytest agent/tests/harness_eval -q

check: lint test ## Run lint gates and the default test suite
