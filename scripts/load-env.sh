#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${KRTOUR_MAP_ENV_FILE:-"$ROOT_DIR/.env"}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export KRTOUR_MAP_ADMIN_HOST="${KRTOUR_MAP_ADMIN_HOST:-127.0.0.1}"
export KRTOUR_MAP_ADMIN_PORT="${KRTOUR_MAP_ADMIN_PORT:-9011}"
export KRTOUR_MAP_ADMIN_WEB_PORT="${KRTOUR_MAP_ADMIN_WEB_PORT:-9012}"
export KRTOUR_MAP_DAGSTER_PORT="${KRTOUR_MAP_DAGSTER_PORT:-9013}"

default_admin_cors_allow_origins() {
  local web_port="$KRTOUR_MAP_ADMIN_WEB_PORT"
  local origins=(
    "http://localhost:$web_port"
    "http://127.0.0.1:$web_port"
  )
  local wsl_ip="${KRTOUR_MAP_WSL_HOST_IP:-}"
  if [[ -z "$wsl_ip" ]] && [[ -n "${WSL_DISTRO_NAME:-}" ]] && command -v hostname >/dev/null 2>&1; then
    wsl_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [[ -n "$wsl_ip" ]]; then
    origins+=("http://$wsl_ip:$web_port")
  fi

  local json="["
  local origin
  for origin in "${origins[@]}"; do
    if [[ "$json" != "[" ]]; then
      json+=","
    fi
    json+="\"$origin\""
  done
  json+="]"
  printf '%s' "$json"
}

export KRTOUR_MAP_ADMIN_CORS_ALLOW_ORIGINS="${KRTOUR_MAP_ADMIN_CORS_ALLOW_ORIGINS:-$(default_admin_cors_allow_origins)}"
export KRTOUR_MAP_ADMIN_KRADDR_GEO_BASE_URL="${KRTOUR_MAP_ADMIN_KRADDR_GEO_BASE_URL:-http://127.0.0.1:9001}"
export KRTOUR_MAP_ADMIN_DAGSTER_URL="${KRTOUR_MAP_ADMIN_DAGSTER_URL:-http://127.0.0.1:${KRTOUR_MAP_DAGSTER_PORT}}"
export KRTOUR_MAP_DOCKER_ADMIN_DAGSTER_URL="${KRTOUR_MAP_DOCKER_ADMIN_DAGSTER_URL:-http://dagster:${KRTOUR_MAP_DAGSTER_PORT}}"
export DAGSTER_DISABLE_TELEMETRY="${DAGSTER_DISABLE_TELEMETRY:-yes}"
export NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API="${NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API:-http://127.0.0.1:${KRTOUR_MAP_ADMIN_PORT}}"
export NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL="${NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL:-http://127.0.0.1:${KRTOUR_MAP_DAGSTER_PORT}}"

export_first() {
  local target="$1"
  shift
  local current="${!target:-}"
  if [[ -n "$current" ]]; then
    export "$target=$current"
    return 0
  fi

  local name value
  for name in "$@"; do
    value="${!name:-}"
    if [[ -n "$value" ]]; then
      export "$target=$value"
      return 0
    fi
  done
}

export_first KRTOUR_MAP_ADMIN_KMA_SERVICE_KEY \
  DATA_GO_KR_SERVICE_KEY KMA_SERVICE_KEY KMA_API_KEY PUBLIC_DATA_SERVICE_KEY SERVICE_KEY
export_first KRTOUR_MAP_ADMIN_KMA_APIHUB_KEY \
  KMA_APIHUB_AUTH_KEY KMA_APIHUB_KEY
export_first KRTOUR_MAP_ADMIN_OPINET_SERVICE_KEY \
  OPINET_API_KEY OPINET_SERVICE_KEY
export_first KRTOUR_MAP_ADMIN_DATAGOKR_SERVICE_KEY \
  DATA_GO_KR_SERVICE_KEY DATAGOKR_API_KEY PUBLIC_DATA_SERVICE_KEY SERVICE_KEY
export_first KRTOUR_MAP_ADMIN_VISITKOREA_SERVICE_KEY \
  KTO_DATA_GO_KR_SERVICE_KEY VISITKOREA_SERVICE_KEY DATA_GO_KR_SERVICE_KEY
export_first KRTOUR_MAP_ADMIN_KREX_SERVICE_KEY \
  KEX_GO_API_KEY KREX_API_KEY KREX_SERVICE_KEY
export_first KRTOUR_MAP_ADMIN_KNPS_SERVICE_KEY \
  KNPS_SERVICE_KEY KNPS_API_KEY
export_first KRTOUR_MAP_ADMIN_AIRKOREA_SERVICE_KEY \
  AIRKOREA_SERVICE_KEY AIRKOREA_API_KEY DATA_GO_KR_SERVICE_KEY
export_first KRTOUR_MAP_ADMIN_KRFOREST_SERVICE_KEY \
  KRFOREST_SERVICE_KEY KRFOREST_API_KEY DATA_GO_KR_SERVICE_KEY
export_first NEXT_PUBLIC_VWORLD_API_KEY \
  KRADDR_GEO_VWORLD_API_KEY VWORLD_API_KEY
