#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

manual_create_key_in_root_env() {
  local wanted_key="$1"
  local line key
  [[ -f "$ENV_FILE" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    [[ "$key" == "$wanted_key" ]] && return 0
  done <"$ENV_FILE"
  return 1
}
manual_create_raw="${KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN:-}"
manual_create_digest="${KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256:-}"
reject_exported_manual_feature_create_aliases \
  "$manual_create_raw" \
  "$manual_create_digest"
manual_create_raw=""
manual_create_digest=""

for manual_create_key in \
  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED; do
  if manual_create_key_in_root_env "$manual_create_key"; then
    echo "$manual_create_key must not be configured in root env because build children do not consume M01 credentials" >&2
    exit 1
  fi
  unset "$manual_create_key"
done

export KOR_TRAVEL_MAP_GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"

cd "$ROOT_DIR"
compose=(docker compose --env-file /dev/null)
KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN=manual-feature-create-build-placeholder \
KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256=0000000000000000000000000000000000000000000000000000000000000000 \
KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false \
  "${compose[@]}" build api frontend dagster dagster-daemon
