#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

API_ENV_FILE="${KOR_TRAVEL_MAP_API_ENV_FILE:-$ROOT_DIR/packages/kor-travel-map-api/.env}"
if [[ ! -f "$API_ENV_FILE" ]]; then
  echo "required API env file is missing: $API_ENV_FILE" >&2
  echo "copy packages/kor-travel-map-api/.env.example and configure it first" >&2
  exit 1
fi

COMMON_PROCESS_ENV=(
  "PATH=$PATH"
  "HOME=${HOME:-$ROOT_DIR}"
  "LANG=${LANG:-C.UTF-8}"
  "PYTHONUNBUFFERED=1"
)
for name in \
  LC_ALL LC_CTYPE TZ VIRTUAL_ENV PYTHONPATH LD_LIBRARY_PATH SSL_CERT_FILE \
  REQUESTS_CA_BUNDLE CURL_CA_BUNDLE HTTP_PROXY HTTPS_PROXY NO_PROXY \
  http_proxy https_proxy no_proxy; do
  if [[ -v "$name" ]]; then
    COMMON_PROCESS_ENV+=("$name=${!name}")
  fi
done

API_SHARED_ENV=()
FRONTEND_PROCESS_ENV=()
DAGSTER_PROCESS_ENV=()
while IFS= read -r name; do
  case "$name" in
    KOR_TRAVEL_MAP_PG_* | KOR_TRAVEL_MAP_OBJECT_STORE_* | KOR_TRAVEL_MAP_OFFLINE_UPLOAD_* | KOR_TRAVEL_MAP_FILE_REGISTRY_* | KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS)
      API_SHARED_ENV+=("$name=${!name}")
      ;;
  esac
  case "$name" in
    NEXT_PUBLIC_* | KOR_TRAVEL_MAP_API_INTERNAL_URL | KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET | KOR_TRAVEL_MAP_UI_*)
      FRONTEND_PROCESS_ENV+=("$name=${!name}")
      ;;
  esac
  case "$name" in
    KOR_TRAVEL_MAP_API_* | KOR_TRAVEL_MAP_ADMIN_* | KOR_TRAVEL_MAP_UI_*)
      ;;
    KOR_TRAVEL_MAP_* | DAGSTER_*)
      DAGSTER_PROCESS_ENV+=("$name=${!name}")
      ;;
  esac
done < <(compgen -A variable)

declare -a API_SCOPED_ENV=()
declare -A API_SCOPED_VALUES=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
  if [[ "$line" == export\ * ]]; then
    line="${line#export }"
  fi
  [[ "$line" == *=* ]] || continue
  key="${line%%=*}"
  value="${line#*=}"
  if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "invalid API env key: $key" >&2
    exit 1
  fi
  case "$key" in
    KOR_TRAVEL_MAP_API_KMA_SERVICE_KEY | KOR_TRAVEL_MAP_API_KMA_APIHUB_KEY | KOR_TRAVEL_MAP_API_OPINET_SERVICE_KEY | KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY | KOR_TRAVEL_MAP_API_VISITKOREA_SERVICE_KEY | KOR_TRAVEL_MAP_API_KREX_SERVICE_KEY | KOR_TRAVEL_MAP_API_KNPS_SERVICE_KEY | KOR_TRAVEL_MAP_API_AIRKOREA_SERVICE_KEY | KOR_TRAVEL_MAP_API_KRFOREST_SERVICE_KEY | KOR_TRAVEL_MAP_API_ETL_LIVE_PREVIEW_ENABLED)
      echo "removed provider runtime key is not allowed in API env: $key" >&2
      exit 1
      ;;
    KOR_TRAVEL_MAP_API_INTERNAL_URL)
      echo "frontend-only key is not allowed in API env: $key" >&2
      exit 1
      ;;
    KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET)
      echo "shared admin proxy secret must be configured only in root env: KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET" >&2
      exit 1
      ;;
    KOR_TRAVEL_MAP_API_* | KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_* | KOR_TRAVEL_MAP_KAKAO_* | KOR_TRAVEL_MAP_NAVER_* | KOR_TRAVEL_MAP_GOOGLE_PLACES_*)
      ;;
    *)
      echo "unsupported key in API env: $key" >&2
      exit 1
      ;;
  esac
  if [[ -v "API_SCOPED_VALUES[$key]" ]]; then
    echo "duplicate key in API env: $key" >&2
    exit 1
  fi
  if [[ ${#value} -ge 2 ]]; then
    first="${value:0:1}"
    last="${value: -1}"
    if [[ "$first$last" == '""' || "$first$last" == "''" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" =~ [[:space:]]# ]]; then
      echo "inline comments are not allowed in API env values: $key" >&2
      exit 1
    fi
  fi
  API_SCOPED_VALUES["$key"]="$value"
  API_SCOPED_ENV+=("$key=$value")
done <"$API_ENV_FILE"

frontend_proxy_secret="${KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET:-}"
trimmed_frontend_proxy_secret="${frontend_proxy_secret#"${frontend_proxy_secret%%[![:space:]]*}"}"
trimmed_frontend_proxy_secret="${trimmed_frontend_proxy_secret%"${trimmed_frontend_proxy_secret##*[![:space:]]}"}"
if [[ "$frontend_proxy_secret" != "$trimmed_frontend_proxy_secret" || ${#frontend_proxy_secret} -lt 32 ]]; then
  echo "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET must be at least 32 characters without surrounding whitespace" >&2
  exit 1
fi

api_backup_root="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_BACKUP_ROOT]:-data/backups}"
if [[ "$api_backup_root" != /* ]]; then
  api_backup_root="$ROOT_DIR/$api_backup_root"
fi

if [[ "${KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY:-0}" == "1" ]]; then
  echo "admin stack environment is valid"
  exit 0
fi

LOG_DIR="${KOR_TRAVEL_MAP_LOG_DIR:-"$ROOT_DIR/.codex_tmp/admin-stack"}"
mkdir -p "$LOG_DIR"

# 고정 포트가 이미 사용 중이면 새 포트로 열지 않고, 강제종료 여부를 묻는다.
# 강제종료하지 않으면 preflight가 exit 1 → set -e로 기동 중지(기존 서비스 보존).
"$ROOT_DIR/scripts/preflight-ports.sh" \
  "$KOR_TRAVEL_MAP_API_PORT" "$KOR_TRAVEL_MAP_ADMIN_WEB_PORT" "$KOR_TRAVEL_MAP_DAGSTER_PORT"

PYTHON_BIN="${PYTHON_BIN:-"$ROOT_DIR/.venv/bin/python"}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

console_script_usable() {
  local bin="$1"
  if [[ ! -x "$bin" ]]; then
    return 1
  fi

  local first_line=""
  IFS= read -r first_line <"$bin" || true
  if [[ "$first_line" != '#!'* || "$first_line" == '#!/usr/bin/env '* ]]; then
    return 0
  fi

  local interpreter="${first_line#\#!}"
  interpreter="${interpreter%% *}"
  [[ -x "$interpreter" ]]
}

dagster_webserver_bin="${DAGSTER_WEBSERVER_BIN:-"$ROOT_DIR/.venv/bin/dagster-webserver"}"
if console_script_usable "$dagster_webserver_bin"; then
  DAGSTER_WEBSERVER_CMD=("$dagster_webserver_bin")
else
  dagster_webserver_bin="$(command -v dagster-webserver || true)"
  if [[ -n "$dagster_webserver_bin" ]] && console_script_usable "$dagster_webserver_bin"; then
    DAGSTER_WEBSERVER_CMD=("$dagster_webserver_bin")
  else
    DAGSTER_WEBSERVER_CMD=(
      "$PYTHON_BIN" -c
      "from dagster_webserver.cli import main; raise SystemExit(main())"
    )
  fi
fi

dagster_daemon_bin="${DAGSTER_DAEMON_BIN:-"$ROOT_DIR/.venv/bin/dagster-daemon"}"
if console_script_usable "$dagster_daemon_bin"; then
  DAGSTER_DAEMON_CMD=("$dagster_daemon_bin")
else
  dagster_daemon_bin="$(command -v dagster-daemon || true)"
  if [[ -n "$dagster_daemon_bin" ]] && console_script_usable "$dagster_daemon_bin"; then
    DAGSTER_DAEMON_CMD=("$dagster_daemon_bin")
  else
    DAGSTER_DAEMON_CMD=(
      "$PYTHON_BIN" -c
      "from dagster._daemon.cli import main; raise SystemExit(main())"
    )
  fi
fi

echo "alembic upgrade head"
(
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m alembic upgrade head
)

echo "ensure dagster metadata database: $KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB"
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


dagster_url = os.environ["KOR_TRAVEL_MAP_DAGSTER_PG_URL"]
dagster_db = urlsplit(dagster_url).path.lstrip("/").split("?", 1)[0]
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dagster_db):
    raise SystemExit(f"invalid KOR_TRAVEL_MAP_DAGSTER_PG_URL database name: {dagster_db!r}")

app_dsn = _psycopg_dsn(os.environ["KOR_TRAVEL_MAP_PG_DSN_SYNC"])
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

# dev 기본은 내부 주소(127.0.0.1) 바인드다. Windows Playwright e2e처럼 WSL 밖에서
# 접근해야 하는 경우에만 KOR_TRAVEL_MAP_*_BIND_HOST=0.0.0.0으로 명시 opt-in한다
# (docs/dev-environment.md §dev/prod 구분).
API_BIND_HOST="${KOR_TRAVEL_MAP_API_BIND_HOST:-127.0.0.1}"
WEB_BIND_HOST="${KOR_TRAVEL_MAP_ADMIN_WEB_BIND_HOST:-127.0.0.1}"
DAGSTER_BIND_HOST="${KOR_TRAVEL_MAP_DAGSTER_BIND_HOST:-127.0.0.1}"
NEXT_DEV_ARGS=(dev)
if (
  cd "$ROOT_DIR/packages/kor-travel-map-admin/frontend"
  npx next dev --help 2>/dev/null | grep -q -- "--webpack"
); then
  NEXT_DEV_ARGS+=(--webpack)
fi

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
  cd "$ROOT_DIR/packages/kor-travel-map-api"
  start_bg api env -i \
    "${COMMON_PROCESS_ENV[@]}" \
    "${API_SHARED_ENV[@]}" \
    "${API_SCOPED_ENV[@]}" \
    KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET="$frontend_proxy_secret" \
    KOR_TRAVEL_MAP_API_HOST="$API_BIND_HOST" \
    KOR_TRAVEL_MAP_API_PORT="$KOR_TRAVEL_MAP_API_PORT" \
    KOR_TRAVEL_MAP_API_BACKUP_ROOT="$api_backup_root" \
    KOR_TRAVEL_MAP_API_BACKUP_PROJECT_ROOT="$ROOT_DIR" \
    "$PYTHON_BIN" -m uvicorn kortravelmap.api.app:app \
    --host "$API_BIND_HOST" --port "$KOR_TRAVEL_MAP_API_PORT"
)

(
  cd "$ROOT_DIR/packages/kor-travel-map-admin/frontend"
  start_bg web env -i \
    "${COMMON_PROCESS_ENV[@]}" \
    "${FRONTEND_PROCESS_ENV[@]}" \
    npx next "${NEXT_DEV_ARGS[@]}" --port "$KOR_TRAVEL_MAP_ADMIN_WEB_PORT" --hostname "$WEB_BIND_HOST"
)

(
  cd "$ROOT_DIR"
  start_bg dagster env -i \
    "${COMMON_PROCESS_ENV[@]}" \
    "${DAGSTER_PROCESS_ENV[@]}" \
    TMPDIR=/tmp TEMP=/tmp TMP=/tmp \
    DAGSTER_HOME="$DAGSTER_HOME_DIR" \
    DAGSTER_DISABLE_TELEMETRY="$DAGSTER_DISABLE_TELEMETRY" \
    KOR_TRAVEL_MAP_DAGSTER_PG_URL="$KOR_TRAVEL_MAP_DAGSTER_PG_URL" \
    "${DAGSTER_WEBSERVER_CMD[@]}" -m kortravelmap.dagster.definitions \
    -h "$DAGSTER_BIND_HOST" -p "$KOR_TRAVEL_MAP_DAGSTER_PORT"
)

(
  cd "$ROOT_DIR"
  start_bg dagster-daemon env -i \
    "${COMMON_PROCESS_ENV[@]}" \
    "${DAGSTER_PROCESS_ENV[@]}" \
    TMPDIR=/tmp TEMP=/tmp TMP=/tmp \
    DAGSTER_HOME="$DAGSTER_HOME_DIR" \
    DAGSTER_DISABLE_TELEMETRY="$DAGSTER_DISABLE_TELEMETRY" \
    KOR_TRAVEL_MAP_DAGSTER_PG_URL="$KOR_TRAVEL_MAP_DAGSTER_PG_URL" \
    "${DAGSTER_DAEMON_CMD[@]}" run -m kortravelmap.dagster.definitions
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

wait_url api "http://127.0.0.1:${KOR_TRAVEL_MAP_API_PORT}/health"
wait_url web "http://127.0.0.1:${KOR_TRAVEL_MAP_ADMIN_WEB_PORT}/"
wait_url dagster "http://127.0.0.1:${KOR_TRAVEL_MAP_DAGSTER_PORT}/"
ensure_bg_alive dagster-daemon

echo "api=http://127.0.0.1:${KOR_TRAVEL_MAP_API_PORT}"
echo "web=http://127.0.0.1:${KOR_TRAVEL_MAP_ADMIN_WEB_PORT}"
echo "dagster=http://127.0.0.1:${KOR_TRAVEL_MAP_DAGSTER_PORT}"
