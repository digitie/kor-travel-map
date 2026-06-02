#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

ports=("$@")
if [[ "${#ports[@]}" -eq 0 ]]; then
  ports=("$KRTOUR_MAP_ADMIN_PORT" "$KRTOUR_MAP_ADMIN_WEB_PORT" "$KRTOUR_MAP_DAGSTER_PORT")
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

for port in "${ports[@]}"; do
  mapfile -t pids < <(find_pids_for_port "$port")
  if [[ "${#pids[@]}" -eq 0 ]]; then
    echo "port $port: no listener"
    continue
  fi

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
done
