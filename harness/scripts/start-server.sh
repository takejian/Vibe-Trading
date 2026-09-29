#!/usr/bin/env bash
# start-server.sh — start the vibe-trading API server under harness lifecycle
# management, wait for /live, and record a pidfile under the runtime root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8899}"
VIBE_HOME="${VIBE_TRADING_HOME:-$HOME/.vibe-trading}"
LOG_DIR="$VIBE_HOME/logs"
PIDFILE="$LOG_DIR/harness-server.pid"
LOGFILE="$LOG_DIR/harness-server.log"
VIBE_BIN="$ROOT/.venv/bin/vibe-trading"
PROBE_URL="http://HOST:$PORT/live"

mkdir -p "$LOG_DIR"

info() { printf '\033[0;36m[serve]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[serve]\033[0m %s\n' "$*"; }
fail() { printf '\033[0;31m[serve]\033[0m %s\n' "$*" >&2; exit 1; }

pid_alive() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

health_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 2 "$PROBE_URL" >/dev/null 2>&1
  else
    "$ROOT/.venv/bin/python" - "$PROBE_URL" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

urllib.request.urlopen(sys.argv[1], timeout=2).read(1)
PY
  fi
}

# 1. A live pidfile means the harness-managed server is already up.
if [[ -f "$PIDFILE" ]]; then
  existing_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$existing_pid" ]] && pid_alive "$existing_pid"; then
    info "server already running (pid $existing_pid) — $PROBE_URL"
    exit 0
  fi
  warn "removing stale pidfile (pid ${existing_pid:-?} not alive)"
  rm -f "$PIDFILE"
fi

# 2. A foreign process may already serve the port (e.g. scripts/dev or Docker):
#    never kill it; treat the occupied port as success.
if health_ok; then
  info "something is already serving $PROBE_URL (not harness-managed) — leaving it alone"
  exit 0
fi

# 3. Warn exactly like the application itself: non-loopback bind without a key
#    stays possible (peer-IP guard), it is not a hard stop.
case "$HOST" in
  127.0.0.1|localhost|::1) ;;
  *)
    if [[ -z "${API_AUTH_KEY:-}" ]]; then
      warn "binding non-loopback host '$HOST' with empty API_AUTH_KEY — set API_AUTH_KEY for remote access"
    fi
    ;;
esac

if [[ ! -x "$VIBE_BIN" ]]; then
  fail "missing $VIBE_BIN — run: bash harness/scripts/setup-env.sh"
fi

# 4. Launch detached and record the pid.
info "starting vibe-trading serve on $HOST:$PORT (log: $LOGFILE)"
nohup "$VIBE_BIN" serve --host "$HOST" --port "$PORT" >>"$LOGFILE" 2>&1 &
server_pid=$!
echo "$server_pid" >"$PIDFILE"

# 5. Poll /live for up to ~30s; fail fast if the process exits meanwhile.
info "waiting for $PROBE_URL"
ready=0
for ((i = 1; i <= 30; i++)); do
  if health_ok; then
    ready=1
    break
  fi
  if ! pid_alive "$server_pid"; then
    warn "server process exited before becoming healthy"
    rm -f "$PIDFILE"
    tail -n 40 "$LOGFILE" >&2 || true
    exit 1
  fi
  printf '.'
  sleep 1
done
printf '\n'

if [[ "$ready" -ne 1 ]]; then
  warn "server not healthy after 30s — tail of $LOGFILE:"
  tail -n 40 "$LOGFILE" >&2 || true
  exit 1
fi

info "server is up: http://$HOST:$PORT/live (pid $server_pid)"
