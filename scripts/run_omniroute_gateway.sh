#!/usr/bin/env bash
set -euo pipefail
umask 077

ORIGINAL_HOME="$HOME"
GCH_ROOT="$ORIGINAL_HOME/.local/share/gch/omniroute"
RUNTIME="$GCH_ROOT/runtime"
BIN="$RUNTIME/node_modules/.bin/omniroute"
WRAPPER="$ORIGINAL_HOME/.local/bin/gch-omniroute"
SECRET_FILE="$ORIGINAL_HOME/.config/gch/omniroute.env"
DATA_DIR="$GCH_ROOT/data"
ISOLATED_HOME="$GCH_ROOT/home"
EVIDENCE_DIR="$GCH_ROOT/evidence"
PID_FILE="$DATA_DIR/omniroute.pid"
ACTION="${1:-status}"

require_secret_file() {
  test -f "$SECRET_FILE" && test ! -L "$SECRET_FILE"
  test "$(stat -c '%a' "$SECRET_FILE")" = "600"
  local content_lines
  content_lines="$(grep -Ev '^[[:space:]]*(#|$)' "$SECRET_FILE" || true)"
  test "$(printf '%s\n' "$content_lines" | grep -c '=')" -eq 4
  grep -Eq '^OMNIROUTE_API_KEY=[A-Za-z0-9_-]{32,}$' "$SECRET_FILE"
  grep -Eq '^API_KEY_SECRET=[A-Za-z0-9_-]{32,}$' "$SECRET_FILE"
  grep -Eq '^JWT_SECRET=[A-Za-z0-9_-]{32,}$' "$SECRET_FILE"
  grep -Eq '^STORAGE_ENCRYPTION_KEY=[A-Za-z0-9_-]{32,}$' "$SECRET_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$SECRET_FILE"
  set +a
}

export_safe_env() {
  export HOME="$ISOLATED_HOME"
  export XDG_CACHE_HOME="$ISOLATED_HOME/.cache"
  export OMNIROUTE_CLI_SKIP_REPO_ENV=1
  export DATA_DIR="$DATA_DIR"
  export PORT=20128 API_PORT=20128 DASHBOARD_PORT=20128
  export OMNIROUTE_SERVER_HOST=127.0.0.1
  export REQUIRE_API_KEY=true
  export OMNIROUTE_EMERGENCY_FALLBACK=false
  export PROXY_AUTO_SELECT_ENABLED=false
  export OMNIROUTE_CONTROL_PLANE_PROXY_DIRECT_FALLBACK=false
  export OMNIROUTE_ENABLE_LIVE_WS=false
  export OMNIROUTE_DISABLE_BACKGROUND_SERVICES=true
}

record_event() {
  local event="$1" detail="${2:-}"
  mkdir -p "$EVIDENCE_DIR"
  printf '{"event":"%s","detail":"%s","utc":"%s"}\n' \
    "$event" "$detail" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    >> "$EVIDENCE_DIR/lifecycle.jsonl"
}

is_running() {
  test -f "$PID_FILE" || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

start_gateway() {
  test -x "$BIN"
  require_secret_file
  mkdir -p "$DATA_DIR" "$EVIDENCE_DIR" "$ISOLATED_HOME/.cache"
  export_safe_env
  if is_running; then
    printf 'RUNNING pid=%s\n' "$(cat "$PID_FILE")"
    return 0
  fi
  local stamp log pid
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log="$EVIDENCE_DIR/omniroute-$stamp.log"
  (cd "$DATA_DIR" && exec nohup "$BIN" serve --port 20128 --no-open --no-tray --no-recovery) >"$log" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  record_event "start" "pid=$pid log=$(basename "$log")"
  printf 'STARTED pid=%s log=%s\n' "$pid" "$log"
}

stop_gateway() {
  if ! is_running; then
    rm -f "$PID_FILE"
    record_event "stop" "already_stopped"
    printf 'STOPPED\n'
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill -TERM "$pid"
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid"
  fi
  rm -f "$PID_FILE"
  record_event "stop" "pid=$pid"
  printf 'STOPPED pid=%s\n' "$pid"
}

rollback_gateway() {
  local backup="${2:-}"
  test -n "$backup"
  case "$backup" in
    "$GCH_ROOT/runtime.rollback-"*) ;;
    *) printf 'unsafe rollback path\n' >&2; return 2 ;;
  esac
  test -d "$backup" && test ! -L "$backup"
  stop_gateway
  local failed="$RUNTIME.failed-$(date -u +%Y%m%dT%H%M%SZ)"
  if [ -d "$RUNTIME" ]; then mv "$RUNTIME" "$failed"; fi
  mv "$backup" "$RUNTIME"
  record_event "rollback" "restored=$(basename "$backup") failed=$(basename "$failed")"
  printf 'ROLLED_BACK runtime=%s\n' "$RUNTIME"
}

doctor_gateway() {
  require_secret_file
  mkdir -p "$DATA_DIR" "$EVIDENCE_DIR" "$ISOLATED_HOME/.cache"
  export_safe_env
  local stamp log rc
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log="$EVIDENCE_DIR/doctor-$stamp.log"
  set +e
  (cd "$DATA_DIR" && timeout --kill-after=2s 15s env SHELL=/bin/false "$BIN" doctor --host 127.0.0.1) >"$log" 2>&1
  rc=$?
  set -e
  record_event "doctor" "rc=$rc log=$(basename "$log")"
  cat "$log"
  return "$rc"
}

case "$ACTION" in
  start) start_gateway ;;
  stop) stop_gateway ;;
  status) if is_running; then printf 'RUNNING pid=%s\n' "$(cat "$PID_FILE")"; else printf 'STOPPED\n'; fi ;;
  doctor) doctor_gateway ;;
  rollback) rollback_gateway "$@" ;;
  *) printf 'usage: %s {start|stop|status|doctor|rollback <backup>}\n' "$0" >&2; exit 2 ;;
esac
