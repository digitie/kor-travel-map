#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

ports=("$@")
if [[ "${#ports[@]}" -eq 0 ]]; then
  ports=(
    "$KRTOUR_MAP_ADMIN_PORT"
    "$KRTOUR_MAP_ADMIN_WEB_PORT"
    "$KRTOUR_MAP_DAGSTER_PORT"
    "$KRTOUR_MAP_RUSTFS_API_PORT"
    "$KRTOUR_MAP_RUSTFS_CONSOLE_PORT"
  )
fi

find_pids_for_port() {
  local port="$1"
  local ss_pids=""
  if command -v ss >/dev/null 2>&1; then
    ss_pids="$(
      ss -ltnp 2>/dev/null \
        | awk -v port="$port" '{ n=split($4, a, ":"); if (a[n] == port) print $0 }' \
        | sed -nE 's/.*pid=([0-9]+).*/\1/p'
    )"
  fi
  local fuser_pids=""
  if command -v fuser >/dev/null 2>&1; then
    fuser_pids="$(fuser -n tcp "$port" 2>/dev/null || true)"
  fi
  printf "%s\n%s\n" "$ss_pids" "$fuser_pids" | tr ' ' '\n' | sed '/^$/d' | sort -u
}

find_windows_pids_for_port() {
  local port="$1"
  if ! command -v powershell.exe >/dev/null 2>&1; then
    return 0
  fi
  powershell.exe -NoProfile -Command \
    "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess" \
    2>/dev/null \
    | tr -d '\r' \
    | sed '/^$/d' \
    | sort -u
}

find_docker_containers_for_port() {
  local port="$1"
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  docker ps --filter "publish=$port" --format "{{.ID}}" 2>/dev/null \
    | sed '/^$/d' \
    | sort -u
}

find_wsl_root_pids_for_port() {
  local port="$1"
  if [[ -z "${WSL_DISTRO_NAME:-}" ]] || ! command -v wsl.exe >/dev/null 2>&1; then
    return 0
  fi
  wsl.exe -d "$WSL_DISTRO_NAME" -u root -- sh -lc \
    "fuser -n tcp '$port' 2>/dev/null || true" \
    2>/dev/null \
    | tr -d '\r' \
    | tr ' ' '\n' \
    | sed '/^$/d' \
    | sort -u
}

stop_wsl_root_pids() {
  if [[ "${#}" -eq 0 ]]; then
    return 0
  fi
  if [[ -z "${WSL_DISTRO_NAME:-}" ]] || ! command -v wsl.exe >/dev/null 2>&1; then
    return 0
  fi
  local quoted_pids=""
  local pid
  for pid in "$@"; do
    quoted_pids="$quoted_pids '$pid'"
  done
  wsl.exe -d "$WSL_DISTRO_NAME" -u root -- sh -lc \
    "kill $quoted_pids 2>/dev/null || true; sleep 0.5; kill -9 $quoted_pids 2>/dev/null || true" \
    >/dev/null 2>&1 || true
}

for port in "${ports[@]}"; do
  mapfile -t pids < <(find_pids_for_port "$port")
  if [[ "${#pids[@]}" -eq 0 ]]; then
    echo "port $port: no listener"
  else
    echo "port $port: stopping ${pids[*]}"
    for pid in "${pids[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    sleep 0.5
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
  fi

  mapfile -t docker_containers < <(find_docker_containers_for_port "$port")
  if [[ "${#docker_containers[@]}" -gt 0 ]]; then
    echo "port $port: stopping Docker containers ${docker_containers[*]}"
    docker stop "${docker_containers[@]}" >/dev/null 2>&1 || true
  fi

  mapfile -t root_pids < <(find_wsl_root_pids_for_port "$port")
  if [[ "${#root_pids[@]}" -gt 0 ]]; then
    echo "port $port: stopping WSL root listeners ${root_pids[*]}"
    stop_wsl_root_pids "${root_pids[@]}"
    sleep 0.5
    mapfile -t remaining_root_pids < <(find_wsl_root_pids_for_port "$port")
    if [[ "${#remaining_root_pids[@]}" -gt 0 ]]; then
      echo "port $port: WSL root listeners still present ${remaining_root_pids[*]}" >&2
    fi
  fi

  mapfile -t win_pids < <(find_windows_pids_for_port "$port")
  if [[ "${#win_pids[@]}" -gt 0 ]]; then
    echo "port $port: stopping Windows listeners ${win_pids[*]}"
    for pid in "${win_pids[@]}"; do
      taskkill.exe /PID "$pid" /F >/dev/null 2>&1 || true
    done
    sleep 0.5
    mapfile -t remaining_win_pids < <(find_windows_pids_for_port "$port")
    if [[ "${#remaining_win_pids[@]}" -gt 0 ]]; then
      echo "port $port: Windows listeners still present ${remaining_win_pids[*]}" >&2
    fi
  fi
done
