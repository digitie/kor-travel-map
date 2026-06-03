#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

"$ROOT_DIR/scripts/stop-fixed-ports.sh" \
  "$KRTOUR_MAP_ADMIN_PORT" "$KRTOUR_MAP_ADMIN_WEB_PORT" "$KRTOUR_MAP_DAGSTER_PORT" \
  "$KRTOUR_MAP_RUSTFS_API_PORT" "$KRTOUR_MAP_RUSTFS_CONSOLE_PORT"

cd "$ROOT_DIR"
docker compose up -d --build postgres rustfs rustfs-init api frontend dagster
docker compose ps
