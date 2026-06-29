#!/usr/bin/env bash
set -euo pipefail

app_db="${KOR_TRAVEL_MAP_RESTORE_APP_DB:-}"
dagster_db="${KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB:-}"
rustfs_volume="${KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME:-}"
apply="${KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY:-0}"

if [[ "$apply" == "1" ]]; then
  echo "n150 live-e2e runner refuses automatic swap apply" >&2
  exit 2
fi

cat <<SUMMARY
Restore swap env file generated:
  app_db=${app_db}
  dagster_db=${dagster_db}
  rustfs_volume=${rustfs_volume}
SUMMARY
