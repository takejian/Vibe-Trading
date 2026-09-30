# Development Guide

> How to set up, lint, test, run, and configure Vibe-Trading on a local machine. Every command below is runnable from the repository root unless noted; `make` targets wrap the raw commands shown next to them.

## Prerequisites

- Python **>= 3.11** (`requires-python` in `pyproject.toml:5`; CI runs 3.11 and 3.14). The repo's local `.venv` uses Python 3.12.
- Node.js **>= 22.22.0** (`frontend/package.json` engines; Node 22 in CI).
- For PDF report generation only: Pango/Cairo/Fontconfig system libraries (required by `weasyprint>=60.0`). They are already installed in the `Dockerfile`; on a bare host without them the rest of the app works and only PDF rendering is affected.
- No database server is required: persistence is embedded DuckDB/SQLite under `~/.vibe-trading`.

## Install

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Common optional extras (all from `[project.optional-dependencies]` in `pyproject.toml:113-273`):

- Data sources: `ashare` (baostock), `stats` (statsmodels/arch), `krx` (pykrx), `openbb`.
- LLM providers: `anthropic`, `deepseek`, `copilot`.
- Brokers: `ibkr`, `longbridge`, `mt5` (Windows only), `zerodha`, `upbit`.
- IM channels: `telegram`, `discord`, `feishu`, `slack`, `channels` (umbrella).
- Signals/misc: `harmonic`, `smc`, `keyring`.

CI installs `-e ".[dev,openbb,stats,anthropic]"` (`.github/workflows/test.yml:98`).

Lock files:

- `agent/requirements.txt` — hand-maintained, categorized, `>=`-bounded source manifest; the source of truth for the lock.
- `requirements-lock.txt` — uv-compiled production lock with `--generate-hashes` (py3.11); Docker installs it via `pip install --require-hashes`.
- `agent/requirements-channels.txt` / `requirements-channels-lock.txt` — the same pair for channel SDKs.

`make install` runs the editable install with the `dev` extra (it uses `.venv/bin/pip`, so create the venv first). `bash harness/scripts/setup-env.sh` is the idempotent alternative: it verifies the venv, installs `.[dev]` if needed, seeds `agent/.env` from `agent/.env.example` once, and only prints hints for the network steps (DuckDB ingest, frontend install).

## Lint

```bash
make lint          # = make lint-deps, then make lint-quality
```

- `make lint-deps` runs `scripts/lint-deps`, a stdlib-AST package-layer gate over `agent/src` (no imports executed). The layer assignments for all 31 nodes, the eight frozen reverse edges (`grandfathered_reverse_edges`), and the 17 registered bidirectional debt pairs live in `harness/config/layer-map.json`; see [ARCHITECTURE.md](ARCHITECTURE.md#dependency-rules). Unregistered nodes/import targets are ERRORs (no blind spots); reverse edges are ERRORs unless frozen; same-layer bidirectional pairs are WARNINGs (`--strict` turns WARNINGs into failure). The composition roots `agent/cli`, `agent/api_server.py`, `agent/mcp_server.py`, and `agent/backtest` are intentionally not scanned.
- `make lint-quality` runs `scripts/lint-quality`, four segments in order: (1) the layer gate again; (2) the ruff hard gate; (3) non-blocking style-debt statistics; (4) the six repository safety scanners plus the env-var gate self-test.

Ruff configuration lives in `pyproject.toml:283-314`: `target-version = "py311"`, `line-length = 120`, `select = ["E", "F", "W"]`, `ignore = ["E501"]`, with F401 relaxed for `agent/src/factors/zoo/**`. The hard gate runs with `--select F821,F706,F522,F523,F525,B006,B002,B015,B016,B018,B020,F823` over `agent/src agent/cli agent/backtest agent/evals agent/api_server.py agent/mcp_server.py` and is calibrated to zero violations. Current state:

- Hard-gate rules (including `F821` undefined-name) **block**; promote more rules here once they reach zero.
- The remaining E/F/W style debt is only **reported**, not blocked: **246** findings across the full lint scope, of which **234** are in `agent/src` (legacy style debt; mostly F401/E741/W291).
- The six safety scanners in `tools/ci_grep_gates.sh` always block: (a) no unsafe `yaml.load`; (b) no "WorldQuant" trademark string; (c) no per-stock-code data in `wiki/alpha-library`; (d) no `datetime.utcnow()`/bare `datetime.now()` in listed files; (e) no raw `os.getenv`/`os.environ` reads outside `agent/src/config/` (AST scanner `tools/ci_env_var_gate.py`); (f) no process-wide `os` patching in tests.
- The env-var gate has its own self-test: `pytest tools/test_ci_env_var_gate.py`.

Whole-tree black/ruff was historically only a local convention (`CONTRIBUTING.md:149-150`); the harness lint gate is the first mechanical enforcement.

## Test

```bash
make test
```

The `make test` target runs:

```bash
.venv/bin/python -m pytest --ignore=agent/tests/e2e_backtest \
       --ignore=agent/tests/test_e2e_harness_v2.py \
       --cov=agent --cov-report=term-missing --tb=short -q agent/tests
```

The CI test job (`.github/workflows/test.yml:129`) runs the same command without the explicit path and adds `--cov-report=xml`; `make test-cov` matches that form.

Guard-ignore note: both paths are absent from the tracked tree today, so the flags are currently no-ops — but they are deliberate guards, not stale typos. `.gitignore` excludes `agent/tests/e2e_backtest/` and `agent/tests/e2e_*.py` / `agent/tests/test_e2e_*.py` so developers can keep credential/LLM-dependent e2e suites locally without ever leaking into CI collection; `test_e2e_harness_v2.py` is the real-LLM e2e gated by `VIBE_TRADING_RUN_LIVE_E2E`. The same paths are referenced in `AGENT_CONTRIBUTOR_GUIDE.md` and the PR template.

Other suites:

```bash
make test-fast      # .venv/bin/python -m pytest -m unit -q agent/tests (unit marker only)
make eval-tests     # the harness_eval contract tests only (21 collected items)
make test-cov       # like make test, additionally writes coverage.xml

make test-safety    # live/order gate suite, all four files verified present:
pytest agent/tests/test_sdk_order_gate.py \
       agent/tests/test_mandate_enforcement.py \
       agent/tests/test_killswitch_blocks_orders.py \
       agent/tests/test_readonly_default.py -q

# Factor purity / look-ahead gates (sockets disabled):
pytest agent/tests/factors/test_alpha_purity.py \
       agent/tests/factors/test_lookahead.py -q

# Frontend:
cd frontend && npm run build   # tsc -b && vite build
npx vitest run                 # or: npm run test:run
```

The test sandbox requires no real credentials: `agent/tests/conftest.py:57-156` redirects `HOME`/`USERPROFILE` to a temp directory before collection and fails the session if real `~/.vibe-trading` ledgers were touched; an autouse fixture snapshots/restores `os.environ` and resets the `EnvConfig` singleton (`agent/tests/conftest.py:176-203`). Factor tests force `disable_socket()` (`agent/tests/factors/conftest.py:25-34`).

## Run Locally

```bash
make serve        # bash harness/scripts/start-server.sh
```

- The harness script starts `.venv/bin/vibe-trading serve --host 127.0.0.1 --port 8899` detached (override with `HOST`/`PORT`), waits up to ~30s for the `/live` probe, and writes `harness-server.pid`/`harness-server.log` under `~/.vibe-trading/logs` (or `$VIBE_TRADING_HOME/logs`). An already-serving port is left untouched. A companion teardown lives at `harness/scripts/teardown-env.sh`.
- Liveness: `GET http://127.0.0.1:8899/live` (route at `agent/src/api/system_routes.py:242`). The built SPA is served from `frontend/dist`; a missing build prints a warning.
- Dev mode with the Vite dev server: `vibe-trading serve --dev` spawns Vite on `http://localhost:5173` (`agent/api_server.py:359-368`).
- Both servers plus a frontend dev server at once: `scripts/dev up` — backend `127.0.0.1:8899`, frontend `127.0.0.1:5899`, state under `.vibe-dev/` (`scripts/dev status|logs|stop`).
- MCP server: `vibe-trading-mcp [--transport stdio|sse|http] [--host 127.0.0.1] [--port 8900]` (defaults: stdio, 8900; argparse at `agent/mcp_server.py:3041-3061`). Shell tools (`bash`, `background_run`, `cancel_background`) are off for every transport unless `--enable-shell-tools` / `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` is set.
- Binding a non-loopback interface without `API_AUTH_KEY` prints a warning; remote peers are rejected by the loopback peer-IP guard (`agent/api_server.py:348-353`).

## Local DuckDB Market Warehouse

```bash
make db-init      # cd agent && python scripts/local_db/init_local_db.py
```

- Database file: `~/.vibe-trading/data/market.duckdb` (default at `agent/scripts/local_db/init_local_db.py:48`; override with `--db`).
- The script fills six streams from free, keyless endpoints (Tencent HK with Eastmoney backup, Eastmoney A/US raw bars, Frankfurter/ECB FX, Eastmoney F10 shares/valuation): `instrument_master`, `daily_bar` (raw prices), `trading_calendar`, `fx_rate`, `shares_outstanding`, `valuation_daily`. The DDL in `agent/scripts/local_db/schema.sql` defines ten tables (additionally `adj_factor`, `financial_statement`, `corporate_action`, `ingest_log`).
- Idempotent: all writes are `INSERT OR REPLACE`, safe to re-run for daily increments. Options: `--symbols 01810.HK,00700.HK --start 2023-01-01 --end ... --skip-fx --skip-shares`. Must be run from the `agent/` directory.
- Read-back: add an entry to `~/.vibe-trading/data-bridge/config.yaml` mapping a symbol to a CSV/Parquet/DuckDB source (loader at `agent/backtest/loaders/local_loader.py:46`), then query with the `local:` prefix, e.g. `local:01810.HK`. Explicit `local:` requests never fall back to network sources (`agent/backtest/loaders/registry.py:155-157`).

## Configuration & Environment

- Single source of truth: `agent/src/config/env_schema.py` (typed pydantic models, ~93 variables); access via `agent/src/config/accessor.py`. Raw `os.getenv`/`os.environ` reads outside `agent/src/config/` fail CI gate (e).
- Template: `agent/.env.example`. Interactive setup: `vibe-trading init` (writes `~/.vibe-trading/.env`). Runtime root: `~/.vibe-trading`, overridable only with an exported `VIBE_TRADING_HOME` (read before `.env`).
- Changing `.env` requires restarting `serve` (the web Settings page applies values to the running process, but file edits do not hot-reload).

Key variables by category (names only; secrets belong in `.env`, never in the tree):

- LLM: `LANGCHAIN_PROVIDER`, `LANGCHAIN_MODEL_NAME`, `LANGCHAIN_TEMPERATURE`, `TIMEOUT_SECONDS`, `MAX_RETRIES`, `OPENAI_API_KEY`/`OPENAI_BASE_URL`, `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`, `DEEPSEEK_API_KEY`, `OLLAMA_BASE_URL`, `OPENROUTER_API_KEY`, `DASHSCOPE_API_KEY`, plus the other provider keys listed in `agent/.env.example`.
- Market data: `TUSHARE_TOKEN`, `MARKET_DATA_ORDER_A_SHARE` / `_HK_EQUITY` / `_US_EQUITY` / `_INDIA_EQUITY` / `_KR_EQUITY` / `_CA_EQUITY` / `_AR_EQUITY` / `_UK_EQUITY` / `_VIETNAM_EQUITY` / `_CRYPTO` / `_FUTURES` / `_FUND` / `_MACRO` / `_FOREX` / `_INDEX` (each value must be a permutation of that market's default chain), `CCXT_EXCHANGE`, `FMP_API_KEY`, `FINNHUB_API_KEY`, `ALPHAVANTAGE_API_KEY`, `TIINGO_API_KEY`, `FRED_API_KEY`, `GILDATA_TOKEN`, `TICKERALL_API_KEY`/`TICKERALL_ACCOUNT_ID`.
- Service auth: `API_AUTH_KEY` (required for non-loopback binds), `CORS_ORIGINS`, `VIBE_TRADING_EXTRA_CORS_ORIGINS`, `API_ALLOWED_HOSTS`, `VIBE_TRADING_ENABLE_SHELL_TOOLS`.
- Brokers (names only; most credentials live as files under `~/.vibe-trading/live/<broker>/`): `FUTU_HOST`/`FUTU_PORT`/`FUTU_TRADE_PWD_MD5`, `LONGBRIDGE_APP_KEY`/`LONGBRIDGE_APP_SECRET`/`LONGBRIDGE_ACCESS_TOKEN`, `TAP_AGENT_KEY`/`TAP_PROXY_URL`, plus broker onboarding for ibkr/alpaca/binance/okx/robinhood/etc.
- Paths: `VIBE_TRADING_HOME`, `VIBE_TRADING_STRATEGY_STORE_DB_PATH`, `VIBE_TRADING_GOAL_DB_PATH`.
- Memory/feature flags: `VT_MEMORY` (`off`|`on`|`full` plus `VT_MEMORY_*` quality knobs), `VIBE_TRADING_ENABLE_ADVISORY`, `VIBE_TRADING_ENABLE_SCHEDULER`, `VIBE_TRADING_CHANNELS_AUTO_START`.
- Swarm/tuning: `SWARM_WORKER_TIMEOUT`, `SWARM_WORKER_MAX_ITER`, `SWARM_SKILL_TRIAL_TIMEOUT` (default 900), `SWARM_SKILL_TRIAL_MAX_ITER` (default 40), `SWARM_MAX_WORKERS`, `VIBE_TRADING_TOOL_TIMEOUT_SECONDS`, `VIBE_TRADING_LLM_TIMEOUT_SECONDS`, `VIBE_TRADING_SSE_TIMEOUT`.

## Eval Harness

The offline, deterministic, read-only run-artifact verifier lives in `agent/evals/harness/` (it never calls an LLM, executes tools, or uses the network):

```bash
cd agent
python -m evals.harness.runner \
  --case evals/harness/cases/identity/explicit_a_share.json \
  --run-dir <run-artifact-dir> [--trace-dir <session-dir>] [--output report.json]
```

Exit codes (`agent/evals/harness/runner.py:70-85`): `0` all verdicts pass; `1` at least one FAIL; `2` INVALID_ARTIFACT / unreadable or invalid case. `NOT_EVALUABLE` verdicts (missing instrumentation) do not count as failure. Its contract tests — 17 test functions expanding to 21 collected items (`agent/tests/harness_eval/test_runner.py` = 12 functions, `test_schema_and_artifacts.py` = 5) — run with the ordinary pytest suite. Known gaps: only one case/scenario exists, and the runner is not wired into any CI workflow yet. See `agent/evals/harness/README.md`.

## CI

- `.github/workflows/test.yml`: hash-lock verification on Linux/macOS/Windows (Python 3.11); the `test` job on Python **3.11 and 3.14** installs `[dev,openbb,stats,anthropic]`, verifies the extras import, runs the six grep gates, the env-gate self-test, syntax compilation, and the pytest command shown above; a separate `frontend` job does `npm ci && npm run build && npx vitest run` on Node 22; Windows-only background/bash tests and a 30-minute Electron lifecycle job run separately.
- `.github/workflows/harness.yml` (added with this harness): the lint gate — on Python 3.11 it installs `ruff`/`pytest` and runs `bash scripts/lint-quality` (layer gate, ruff hard rules, safety scanners). This closes the previously missing Python lint enforcement.
- Other workflows: `docker-build.yml` (image validation/publish), `wiki.yml` + `wiki-deploy.yml` (wiki checks/Cloudflare deploy), `desktop-windows.yml` (Electron packaging).

## Runtime Root Layout

`~/.vibe-trading/` (or `$VIBE_TRADING_HOME`) holds all local state:

- `agent.json|yaml|yml`, `.env` — user configuration.
- `sessions.db` — SQLite sessions/FTS5/goals; `strategy_store.db` — strategy storage.
- `runs/` — per-run artifacts (`<timestamp>_<id>/{logs,code,artifacts}`); `swarm/` (and `agent/.swarm/runs/`) — swarm runs.
- `live/<broker>/` — broker profiles, mandate files, append-only audit ledgers; `live/audit.jsonl`, `live/audit_chain.jsonl` must never be written by tests.
- `data/market.duckdb` — local market warehouse; `data-bridge/config.yaml` — local source mappings; `cache/loaders/` — data cache.
- `memory/` — persistent cross-session memory; `uploads/`, `workspace/`, `reports/`, `portfolio.json`, `sessions/`, `logs/`.
