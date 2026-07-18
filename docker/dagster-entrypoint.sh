#!/usr/bin/env sh
set -eu

api_ops_name="$(
  python -c '
import os

print(
    next(
        (
            name
            for name in os.environ
            if name.startswith(
                ("KOR_TRAVEL_MAP_API_OPS_", "KOR_TRAVEL_MAP_OPS_")
            )
        ),
        "",
    ),
    end="",
)
'
)"
if [ -n "$api_ops_name" ]; then
  echo "API-only ops principal key must not enter Dagster process: $api_ops_name" >&2
  exit 1
fi

exec "$@"
