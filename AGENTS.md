# AGENTS.md — Vibe-Trading Agent Map

> Navigation map for AI/automation agents: where code lives, how to build/test it, and where the authoritative safety rules are. It is a map, not a manual — follow the links.

Vibe-Trading is a natural-language finance research / backtesting / trading AI agent with a Python backend, a React web UI, and an MCP server. Distributed package: `vibe-trading-ai` **0.1.15** (`pyproject.toml:3`).

## 1. Repository Layout

- `agent/src/` — backend Python: 31 top-level packages/modules (the layer map below).
- `agent/cli/` — CLI package behind the `vibe-trading` command.
- `agent/api_server.py` — FastAPI server (runs, sessions, live, swarm, SSE, SPA).
- `agent/mcp_server.py` — MCP server behind `vibe-trading-mcp` (stdio/sse/http).
- `agent/backtest/` — backtest engines, optimizers and 28 market-data loaders.
- `agent/tests/` — pytest suite; `agent/evals/` — offline run-artifact eval harness.
- `agent/skills/` — bundled finance skill packs; `agent/scripts/` — local DuckDB init and dev scripts.
- `frontend/` — React 19 + Vite + TypeScript web UI.
- `wiki/` — Cloudflare Pages documentation site source (separate CI checks).
- `tools/` — repo-level CI safety gates (grep/AST scanners).
- `desktop/` — Electron desktop shell; `scripts/` — dev orchestration (`scripts/dev`).

## 2. Architecture Layers

| Layer | Contents |
| --- | --- |
| L0 | Base: `config`, `core`, `entities`, `governance`, `security`, `utils` |
| L1 | Data & primitives: `factors`, `market_data.py`, `memory`, `providers`, `quantlib` |
| L2 | Tools & business: `tools`, `trading`, `live`, `channels`, `skills` + 8 more |
| L3 | Agent orchestration: `agent`, `session`, `swarm` |
| L4 | Entry/API: `api`, `openbb_bridge`, `preflight.py`, `ui_services.py` |

Full graph, package table, critical paths and debt register: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 3. Entry Points

Console scripts (`pyproject.toml:85-86`):

- `vibe-trading` → `cli:main` — CLI/TUI; major subcommands include `serve`, `run`, `init`, `provider`, `data`, `channels`.
- `vibe-trading-mcp` → `mcp_server:main` — MCP server, stdio default, sse/http on 127.0.0.1:8900, shell tools off by default.

Both servers bind loopback by default; a non-loopback bind requires `API_AUTH_KEY`.

## 4. Common Commands

The Makefile is the canonical task entry point; raw equivalents are documented in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

- `make install` — `pip install -e .[dev]` into the existing `.venv` (create it once with `python3 -m venv .venv`; `bash harness/scripts/setup-env.sh` does the install and seeds `agent/.env` from the template).
- `make lint` — `lint-deps` (AST layer gate) + `lint-quality` (layer gate, ruff hard rules, safety scanners).
- `make test` — full pytest suite with the same two e2e guard-ignores as CI (gitignored, credential/real-LLM dependent paths).
- `make test-fast` — tests marked `unit` only; `make test-safety` — live/order safety gate tests only; `make eval-tests` — eval-harness contract tests.
- `make serve` — detached API server on 127.0.0.1:8899 via `harness/scripts/start-server.sh` (waits for `GET /live`; pidfile/log under `~/.vibe-trading/logs`).
- `make db-init` — initialize/incrementally fill the local DuckDB market warehouse.
- `make fe-build` — `npm run build` in `frontend/`.
- `make check` — full local gate (lint + tests); run before pushing.
- `scripts/dev up` — start backend (127.0.0.1:8899) and frontend (127.0.0.1:5899) together.

## 5. Testing Facts

- pytest config: `testpaths = ["agent/tests"]`, `pythonpath = ["agent"]`, markers `unit` / `integration` (`pyproject.toml:275-281`).
- `agent/tests/conftest.py:57-156` redirects `HOME`/`USERPROFILE` to a temp sandbox before collection and fails the session if real `~/.vibe-trading` ledgers were touched; an autouse fixture snapshots/restores `os.environ` and resets the config singleton (`agent/tests/conftest.py:176-203`).
- Factor tests force `disable_socket()` via pytest-socket (`agent/tests/factors/conftest.py:25-34`); other suites mock HTTP. No real API keys are needed.
- Live/order safety suite: `test_sdk_order_gate.py`, `test_mandate_enforcement.py`, `test_killswitch_blocks_orders.py`, `test_readonly_default.py` (`make test-safety`).
- The eval-harness contract tests under `agent/tests/harness_eval/` (17 test functions, 21 parametrized items) run with the regular pytest suite (`make eval-tests`).
- CI runs Python 3.11 and 3.14 (`.github/workflows/test.yml:82`), plus a separate frontend vitest job. The harness lint workflow (`.github/workflows/harness.yml`) runs `scripts/lint-quality` on Python 3.11.

## 6. Configuration

- The single source of truth for environment variables is `agent/src/config/env_schema.py` (typed pydantic models; accessor `agent/src/config/accessor.py`).
- Reading `os.getenv`/`os.environ` outside `agent/src/config/` is forbidden and mechanically enforced by `tools/ci_env_var_gate.py` (gate (e) in `tools/ci_grep_gates.sh`).
- Template: `agent/.env.example`; interactive setup: `vibe-trading init`. Runtime root: `~/.vibe-trading` (override with exported `VIBE_TRADING_HOME`). Editing `.env` requires restarting `serve`.
- `MARKET_DATA_ORDER_*` vars reorder per-market source fallback chains; `VT_MEMORY` (off/on/full) and the `VIBE_TRADING_ENABLE_*` feature flags are schema-defined too. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the categorized list.

## 7. High-Risk Surfaces

[AGENT_CONTRIBUTOR_GUIDE.md](AGENT_CONTRIBUTOR_GUIDE.md) is the **sole authority** on high-risk work: broker order placement/cancellation, mandate authorization, the kill switch (halt), MCP/remote credentials, and externally reachable listeners. Read it before touching any of these. Source anchors: the live order gate `agent/src/live/order_guard.py:101` and broker-tool registration/wrapping `agent/src/live/registry.py:184`. Never run live-trading flows during routine PR validation.

## 8. Documentation Map

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers, 31-package table, dependency rules, critical paths, debt register.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local setup, lint/test/run commands, DuckDB, env vars, CI.
- [docs/design-docs/tool-system.md](docs/design-docs/tool-system.md) — BaseTool/registry, auto-discovery, MCP and live wrapping.
- [docs/design-docs/market-data-pipeline.md](docs/design-docs/market-data-pipeline.md) — source detection, fallback chains, local DuckDB bridge.
- [docs/design-docs/agent-runtime.md](docs/design-docs/agent-runtime.md) — sessions, AgentLoop ReAct, SSE, swarm, governance ledger.
- [AGENT_CONTRIBUTOR_GUIDE.md](AGENT_CONTRIBUTOR_GUIDE.md) — safety rules for AI/automation contributors.
- [CONTRIBUTING.md](CONTRIBUTING.md) — DCO/sign-off, Alpha Zoo PR checklist, code style.
- [agent/evals/harness/README.md](agent/evals/harness/README.md) — how to run the offline artifact verifier.
- [agent/SKILL.md](agent/SKILL.md) — MCP plugin descriptor for external agent hosts (not contributor docs).
- [wiki/](wiki/) — end-user documentation site source.

## 9. Known Architecture Debt

The import graph contains 17 pairs of bidirectional package dependencies (see the register in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)); the most significant inversion is `tools` ↔ `agent` (the tool base class physically lives in `agent/src/agent/tools.py` while 82 tool modules live in `agent/src/tools/`). Today this causes no runtime failure because reverse edges use function-local lazy imports plus `try/except` fallbacks. The eight existing reverse (lower→higher layer) edges are frozen in `grandfathered_reverse_edges` in `harness/config/layer-map.json` and mechanically enforced by `scripts/lint-deps` — **do not add new reverse edges**; same-layer bidirectional edges are reported as WARNINGs. The harness lint workflow (`.github/workflows/harness.yml`) runs `scripts/lint-quality`; its ruff hard rules (F821 and other already-clean bug rules) block, while the remaining style debt — 246 findings across the lint scope (234 in `agent/src`) — is only reported, not blocked, until cleaned.
