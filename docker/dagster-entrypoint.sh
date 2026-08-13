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

case "${1:-}" in
  # Compose는 exec-form으로 webserver를 전달한다.
  dagster-webserver)
    python -m kortravelmap.dagster.runtime_preflight
    ;;
  # daemon의 실제 runtime subcommand만 DB를 사용한다. help/version 등은
  # metadata 또는 application runtime DSN 없이도 정상 동작해야 한다.
  dagster-daemon)
    if [ "${2:-}" = "run" ]; then
      python -m kortravelmap.dagster.runtime_preflight
    fi
    ;;
  # Dockerfile 기본 CMD는 port env를 확장하려고 `/bin/sh -c`를 쓴다. command
  # 문자열이 실제 runtime executable로 시작할 때만 같은 preflight를 적용한다.
  # `sh -c 'echo dagster-webserver'` 같은 maintenance command는 건드리지 않는다.
  sh | /bin/sh)
    if [ "${2:-}" = "-c" ]; then
      case "${3:-}" in
        dagster-webserver\ * | exec\ dagster-webserver\ *)
          python -m kortravelmap.dagster.runtime_preflight
          ;;
        dagster-daemon\ run\ * | exec\ dagster-daemon\ run\ *)
          python -m kortravelmap.dagster.runtime_preflight
          ;;
      esac
    fi
    ;;
esac

exec "$@"
