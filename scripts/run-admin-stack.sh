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

DAGSTER_WEBSERVER_BIN="${DAGSTER_WEBSERVER_BIN:-"$ROOT_DIR/.venv/bin/dagster-webserver"}"
if [[ ! -x "$DAGSTER_WEBSERVER_BIN" ]]; then
  DAGSTER_WEBSERVER_BIN="$(command -v dagster-webserver)"
fi

DAGSTER_DAEMON_BIN="${DAGSTER_DAEMON_BIN:-"$ROOT_DIR/.venv/bin/dagster-daemon"}"
if [[ ! -x "$DAGSTER_DAEMON_BIN" ]]; then
  DAGSTER_DAEMON_BIN="$(command -v dagster-daemon)"
fi

echo "alembic upgrade head"
(
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m alembic upgrade head
)

echo "ensure dagster metadata database: $KRTOUR_MAP_DAGSTER_POSTGRES_DB"
(
  "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

import psycopg
from psycopg import sql


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


dagster_url = os.environ["KRTOUR_MAP_DAGSTER_PG_URL"]
dagster_db = urlsplit(dagster_url).path.lstrip("/").split("?", 1)[0]
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dagster_db):
    raise SystemExit(f"invalid KRTOUR_MAP_DAGSTER_PG_URL database name: {dagster_db!r}")

app_dsn = _psycopg_dsn(os.environ["KRTOUR_MAP_PG_DSN_SYNC"])
with psycopg.connect(app_dsn, autocommit=True) as conn:
    exists = conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s",
        (dagster_db,),
    ).fetchone()
    if exists is None:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dagster_db)))
        print(f"Dagster metadata DB created: {dagster_db}")
    else:
        print(f"Dagster metadata DB exists: {dagster_db}")
PY
)

DAGSTER_HOME_DIR="${DAGSTER_HOME:-"$ROOT_DIR/.dagster"}"
mkdir -p "$DAGSTER_HOME_DIR"
install -m 0644 "$ROOT_DIR/docker/dagster.yaml" "$DAGSTER_HOME_DIR/dagster.yaml"

ADMIN_BIND_HOST="${KRTOUR_MAP_ADMIN_BIND_HOST:-0.0.0.0}"
WEB_BIND_HOST="${KRTOUR_MAP_ADMIN_WEB_BIND_HOST:-0.0.0.0}"
DAGSTER_BIND_HOST="${KRTOUR_MAP_DAGSTER_BIND_HOST:-0.0.0.0}"

stop_logged_pid() {
  local name="$1"
  local pid_file="$LOG_DIR/$name.pid"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    echo "$name pid=$pid stopping"
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

stop_logged_pid dagster-daemon

start_bg() {
  local name="$1"
  shift
  local log_file="$LOG_DIR/$name.log"
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" >"$log_file" 2>&1 </dev/null &
  else
    nohup "$@" >"$log_file" 2>&1 </dev/null &
  fi
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
    KRTOUR_MAP_DAGSTER_PG_URL="$KRTOUR_MAP_DAGSTER_PG_URL" \
    "$DAGSTER_WEBSERVER_BIN" -m krtour.map_dagster.definitions \
    -h "$DAGSTER_BIND_HOST" -p "$KRTOUR_MAP_DAGSTER_PORT"
)

(
  cd "$ROOT_DIR"
  start_bg dagster-daemon env \
    TMPDIR=/tmp TEMP=/tmp TMP=/tmp \
    DAGSTER_HOME="$DAGSTER_HOME_DIR" \
    DAGSTER_DISABLE_TELEMETRY="$DAGSTER_DISABLE_TELEMETRY" \
    KRTOUR_MAP_DAGSTER_PG_URL="$KRTOUR_MAP_DAGSTER_PG_URL" \
    "$DAGSTER_DAEMON_BIN" run -m krtour.map_dagster.definitions
)

wait_url() {
  local name="$1"
  local url="$2"
  local pid_file="$LOG_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"
  local pid
  pid="$(cat "$pid_file")"
  local pid_exited=""
  for _ in $(seq 1 60); do
    if url_ready "$url"; then
      echo "$name ready: $url"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      pid_exited="yes"
    fi
    sleep 1
  done
  echo "$name did not become ready. log: $log_file" >&2
  if [[ "$pid_exited" == "yes" ]]; then
    echo "$name launcher pid $pid exited before readiness." >&2
  fi
  tail -n 80 "$log_file" >&2 || true
  return 1
}

url_ready() {
  local url="$1"
  if curl -fsS "$url" >/dev/null 2>&1; then
    return 0
  fi
  if command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c curl.exe -fsS "$url" -o NUL >/dev/null 2>&1 && return 0
  fi
  return 1
}

ensure_bg_alive() {
  local name="$1"
  local pid_file="$LOG_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name running: pid=$pid"
    return 0
  fi
  echo "$name exited before readiness. log: $log_file" >&2
  tail -n 80 "$log_file" >&2 || true
  return 1
}

wait_url api "http://127.0.0.1:${KRTOUR_MAP_ADMIN_PORT}/debug/health"
wait_url web "http://127.0.0.1:${KRTOUR_MAP_ADMIN_WEB_PORT}/"
wait_url dagster "http://127.0.0.1:${KRTOUR_MAP_DAGSTER_PORT}/"
ensure_bg_alive dagster-daemon

echo "api=http://127.0.0.1:${KRTOUR_MAP_ADMIN_PORT}"
echo "web=http://127.0.0.1:${KRTOUR_MAP_ADMIN_WEB_PORT}"
echo "dagster=http://127.0.0.1:${KRTOUR_MAP_DAGSTER_PORT}"
