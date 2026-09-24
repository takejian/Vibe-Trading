#!/usr/bin/env bash
# teardown-env.sh — gracefully stop the harness-managed vibe-trading server.
# Stops only the process recorded in the pidfile; it never removes any
# DuckDB/SQLite data under the runtime root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

VIBE_HOME="${VIBE_TRADING_HOME:-$HOME/.vibe-trading}"
PIDFILE="$VIBE_HOME/logs/harness-server.pid"

info() { printf '\033[0;36m[teardown]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[teardown]\033[0m %s\n' "$*"; }

if [[ ! -f "$PIDFILE" ]]; then
  info "no pidfile at $PIDFILE — nothing harness-managed to stop"
  exit 0
fi

pid="$(cat "$PIDFILE" 2>/dev/null || true)"
if [[ -z "${pid:-}" ]] || ! kill -0 "$pid" 2>/dev/null; then
  warn "pidfile pointed at a non-running process (pid ${pid:-?}); cleaning up"
  rm -f "$PIDFILE"
  exit 0
fi

info "stopping server (pid $pid) with SIGTERM ..."
kill -TERM "$pid" 2>/dev/null || true

for ((i = 1; i <= 10; i++)); do
  if ! kill -0 "$pid" 2>/dev/null; then
    break
  fi
  sleep 1
done

if kill -0 "$pid" 2>/dev/null; then
  warn "server did not exit within 10s — sending SIGKILL"
  kill -KILL "$pid" 2>/dev/null || true
fi

rm -f "$PIDFILE"
info "server stopped; DuckDB/SQLite data under $VIBE_HOME left untouched"
