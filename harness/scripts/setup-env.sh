#!/usr/bin/env bash
# setup-env.sh — idempotent local harness environment preparation.
#
# Safe to run repeatedly. Never writes secrets and never blocks on prompts:
# network-backed steps (DuckDB ingest, frontend install) only print the
# commands to run manually.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"

info() { printf '\033[0;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[setup]\033[0m %s\n' "$*"; }
fail() { printf '\033[0;31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Virtualenv must already exist; creating interpreters is the user's choice.
if [[ ! -x "$PY" ]]; then
  fail "no .venv interpreter found at .venv/bin/python — create it with: python3 -m venv .venv && .venv/bin/python -m pip install -U pip"
fi
info "using interpreter $("$PY" --version 2>&1) ($PY)"

# 2. Editable install of the project (idempotent: pip no-ops when satisfied).
#    A configured PIP_INDEX_URL/mirror is honored naturally; no mirror is hardcoded.
if "$PY" -c 'import cli' >/dev/null 2>&1 || "$PY" -m pip show vibe-trading-ai >/dev/null 2>&1; then
  info "vibe-trading-ai already installed (editable)"
else
  info "installing vibe-trading-ai in editable mode with [dev] extras ..."
  "$PIP" install -e ".[dev]"
fi

# 3. Dev tooling presence — warn only, never force a reinstall.
for tool_spec in "ruff:ruff" "pytest:pytest"; do
  tool="${tool_spec%%:*}"
  module="${tool_spec##*:}"
  if "$PY" -m "$module" --version >/dev/null 2>&1; then
    info "$tool present"
  else
    warn "$tool not found in .venv — install dev extras with: $PIP install -e '.[dev]'"
  fi
done

# 4. Local env file: seed from the documented template once, then never touch it.
if [[ ! -f "$ROOT/agent/.env" ]]; then
  if [[ -f "$ROOT/agent/.env.example" ]]; then
    cp "$ROOT/agent/.env.example" "$ROOT/agent/.env"
    warn "created agent/.env from agent/.env.example — review/edit it, then restart serve"
  else
    warn "agent/.env missing and agent/.env.example not found; copy a template manually"
  fi
else
  info "agent/.env exists — left untouched"
fi

# 5. Network/long-running steps stay manual so setup never blocks or fetches data.
if [[ ! -f "$HOME/.vibe-trading/data/market.duckdb" ]]; then
  info "local DuckDB warehouse not populated yet — run: make db-init"
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  info "frontend dependencies not installed — run: make fe-install (npm ci)"
fi

cat <<'NEXT'

[setup] done. Next steps:
  make serve       start the API server on 127.0.0.1:8899
  make db-init     populate the local DuckDB market warehouse (needs network)
  make fe-build    build the frontend bundle into frontend/dist
NEXT
