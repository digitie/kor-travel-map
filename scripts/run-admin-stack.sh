#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

LOG_DIR="${KRTOUR_MAP_LOG_DIR:-"$ROOT_DIR/.codex_tmp/admin-stack"}"
mkdir -p "$LOG_DIR"

"$ROOT_DIR/scripts/stop-fixed-ports.sh" \
  "$KRTOUR_MAP_ADMIN_PORT" "$KRTOUR_MAP_ADMIN_WEB_PORT" "$KRTOUR_MAP_DAGSTER_PORT"

PYTHON_BIN="${PYTHON_BIN:-"$ROOT_DIR/.venv/bin/python"}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

DAGSTER_BIN="${DAGSTER_BIN:-"$ROOT_DIR/.venv/bin/dagster"}"
if [[ ! -x "$DAGSTER_BIN" ]]; then
  DAGSTER_BIN="$(command -v dagster)"
fi
DAGSTER_HOME_DIR="${DAGSTER_HOME:-"$ROOT_DIR/.dagster"}"
mkdir -p "$DAGSTER_HOME_DIR"
case "${DAGSTER_DISABLE_TELEMETRY,,}" in
  no | false | 0)
    ;;
  *)
    if [[ ! -f "$DAGSTER_HOME_DIR/dagster.yaml" ]]; then
      cat >"$DAGSTER_HOME_DIR/dagster.yaml" <<'YAML'
telemetry:
  enabled: false
YAML
    fi
    ;;
esac

ADMIN_BIND_HOST="${KRTOUR_MAP_ADMIN_BIND_HOST:-0.0.0.0}"
WEB_BIND_HOST="${KRTOUR_MAP_ADMIN_WEB_BIND_HOST:-0.0.0.0}"
DAGSTER_BIND_HOST="${KRTOUR_MAP_DAGSTER_BIND_HOST:-0.0.0.0}"

start_bg() {
  local name="$1"
  shift
  local log_file="$LOG_DIR/$name.log"
  nohup "$@" >"$log_file" 2>&1 &
  local pid="$!"
  echo "$pid" >"$LOG_DIR/$name.pid"
  echo "$name pid=$pid log=$log_file"
}

(
  cd "$ROOT_DIR"
  start_bg api env \
    KRTOUR_MAP_ADMIN_HOST="$ADMIN_BIND_HOST" \
    KRTOUR_MAP_ADMIN_PORT="$KRTOUR_MAP_ADMIN_PORT" \
    "$PYTHON_BIN" -m uvicorn krtour.map_admin.app:app \
    --host "$ADMIN_BIND_HOST" --port "$KRTOUR_MAP_ADMIN_PORT"
)

(
  cd "$ROOT_DIR/packages/krtour-map-admin/frontend"
  start_bg web env \
    NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API="$NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API" \
    NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL="$NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL" \
    NEXT_PUBLIC_VWORLD_API_KEY="${NEXT_PUBLIC_VWORLD_API_KEY:-}" \
    npx next dev --port "$KRTOUR_MAP_ADMIN_WEB_PORT" --hostname "$WEB_BIND_HOST"
)

(
  cd "$ROOT_DIR"
  start_bg dagster env \
    TMPDIR=/tmp TEMP=/tmp TMP=/tmp \
    DAGSTER_HOME="$DAGSTER_HOME_DIR" \
    DAGSTER_DISABLE_TELEMETRY="$DAGSTER_DISABLE_TELEMETRY" \
    "$DAGSTER_BIN" dev -m krtour.map_dagster.definitions \
    -h "$DAGSTER_BIND_HOST" -p "$KRTOUR_MAP_DAGSTER_PORT"
)

wait_url() {
  local name="$1"
  local url="$2"
  local pid_file="$LOG_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"
  local pid
  pid="$(cat "$pid_file")"
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name ready: $url"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "$name exited before readiness. log: $log_file" >&2
      tail -n 80 "$log_file" >&2 || true
      return 1
    fi
    sleep 1
  done
  echo "$name did not become ready. log: $log_file" >&2
  tail -n 80 "$log_file" >&2 || true
  return 1
}

wait_url api "http://127.0.0.1:${KRTOUR_MAP_ADMIN_PORT}/debug/health"
wait_url web "http://127.0.0.1:${KRTOUR_MAP_ADMIN_WEB_PORT}/"
wait_url dagster "http://127.0.0.1:${KRTOUR_MAP_DAGSTER_PORT}/"

echo "api=http://127.0.0.1:${KRTOUR_MAP_ADMIN_PORT}"
echo "web=http://127.0.0.1:${KRTOUR_MAP_ADMIN_WEB_PORT}"
echo "dagster=http://127.0.0.1:${KRTOUR_MAP_DAGSTER_PORT}"
