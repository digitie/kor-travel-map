#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

export KOR_TRAVEL_MAP_GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"

cd "$ROOT_DIR"
compose=(docker compose --env-file /dev/null)
"${compose[@]}" build api frontend dagster dagster-daemon
