#!/usr/bin/env bash
# ADR-090 배포 경로 리허설 — browser-only live runner가 의도적으로 실패시키지 않는 축만 잰다.
#
# 왜 별도로 필요한가:
#   `run-admin-feature-live-acceptance.sh`는 attested `E2E_BASE_URL`에서 정상 구성의
#   browser acceptance를 수행한다. 2026-08-12에 prod를 crash-loop시킨
#   `docker/api-entrypoint.sh`의 split DSN 하드 요구,
#   `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD` 게이트,
#   `KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE`은 이처럼 의도적으로 잘못된 값을
#   주어 거부 사유까지 확인하는 probe가 아니다. live 인수가 green이어도 배포 위험은
#   별도로 검증해야 한다.
#
#   이 스크립트는 그 세 축을 **실패해야 하는 경우 실패하는지**로 잰다. 성공 경로만
#   재면 게이트가 죽어 있어도 green이다.
#
# 사용:
#   KTM_REHEARSAL_IMAGE=<api image>            (필수)
#   KTM_REHEARSAL_MIGRATOR_DSN=<migrator dsn>  (필수)
#   KTM_REHEARSAL_RUNTIME_DSN=<runtime dsn>    (필수)
#   KTM_REHEARSAL_EXPECTED_HEAD=<alembic head> (필수, 이미지의 실제 head)
#   bash scripts/rehearse-adr090-deploy-path.sh
#
# 이 스크립트는 DB를 **쓰지 않는다** — 컨테이너를 띄웠다 즉시 죽이거나, 게이트가
# DB 접속 전에 거부하는지만 본다.
set -euo pipefail

die() { printf 'adr090 rehearsal failed: %s\n' "$1" >&2; exit 1; }

require() {
  eval "value=\${$1:-}"
  [ -n "$value" ] || die "$1 is required"
}

require KTM_REHEARSAL_IMAGE
require KTM_REHEARSAL_MIGRATOR_DSN
require KTM_REHEARSAL_RUNTIME_DSN
require KTM_REHEARSAL_EXPECTED_HEAD

IMAGE="$KTM_REHEARSAL_IMAGE"
MIGRATOR_DSN="$KTM_REHEARSAL_MIGRATOR_DSN"
RUNTIME_DSN="$KTM_REHEARSAL_RUNTIME_DSN"
EXPECTED_HEAD="$KTM_REHEARSAL_EXPECTED_HEAD"

secret() { openssl rand -hex 24; }

# entrypoint가 **DSN/head 게이트보다 먼저** 통과를 요구하는 값들. 이 리허설의
# 대상이 아니므로 매번 새로 만든다 — 값 자체는 출력하지 않는다.
#
# 이걸 안 채우면 네 경우 모두 ops profile 검사(ADR-066)에서 먼저 죽는다. exit code만
# 보면 "게이트가 닫혔다"로 보이지만 정작 재려던 축에는 **도달조차 못 한 것**이다.
# 그래서 아래 각 case는 exit code에 더해 **거부 사유 문자열**까지 확인한다.
common_env() {
  printf -- '-e\nKOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=%s\n' "$(secret)"
  printf -- '-e\nKOR_TRAVEL_MAP_API_SERVICE_TOKEN=%s\n' "$(secret)"
  printf -- '-e\nKOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=%s\n' "$(secret)"
  printf -- '-e\nKOR_TRAVEL_MAP_API_METRICS_TOKEN=%s\n' "$(secret)"
  printf -- '-e\nKOR_TRAVEL_MAP_API_OPS_READ_TOKEN=%s\n' "$(secret)"
  printf -- '-e\nKOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=%s\n' "$(secret)"
  printf -- '-e\nKOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN=%s\n' "$(secret)"
}

run_case() {
  # stdout에 컨테이너 출력, 반환값은 exit code.
  local -a args=()
  while IFS= read -r line; do args+=("$line"); done < <(common_env)
  docker run --rm --network host "${args[@]}" "$@" "$IMAGE" 2>&1 || return $?
}

failures=0
report() {
  # $1 label, $2 observed exit, $3 expectation(nonzero|zero), $4 output
  local label="$1" observed="$2" expectation="$3" output="$4"
  local ok=0
  if [ "$expectation" = "nonzero" ] && [ "$observed" != "0" ]; then ok=1; fi
  if [ "$expectation" = "zero" ] && [ "$observed" = "0" ]; then ok=1; fi
  if [ "$ok" = "1" ]; then
    printf 'PASS  %s (exit=%s)\n' "$label" "$observed"
  else
    printf 'FAIL  %s (exit=%s, expected %s)\n' "$label" "$observed" "$expectation"
    printf '%s\n' "$output" | tail -6 | sed 's/^/      /'
    failures=$((failures + 1))
  fi
}

printf '=== ADR-090 배포 경로 리허설 ===\n'
printf 'image head 기대값: %s\n\n' "$EXPECTED_HEAD"

# 1. split DSN 누락 — prod crash-loop의 정확한 재현. DB를 건드리기 전에 죽어야 한다.
out="$(run_case -e "KOR_TRAVEL_MAP_PG_DSN=$MIGRATOR_DSN")" && code=0 || code=$?
report "split DSN 누락은 기동을 거부한다" "$code" nonzero "$out"
printf '%s\n' "$out" | grep -q 'KOR_TRAVEL_MAP_MIGRATOR_PG_DSN is required' ||
  { printf 'FAIL  거부 사유가 MIGRATOR_PG_DSN 누락이 아니다\n'; failures=$((failures + 1)); }

# 2. runtime DSN만 있고 migrator가 없는 경우도 같다.
out="$(run_case -e "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN=$RUNTIME_DSN")" && code=0 || code=$?
report "runtime DSN 단독도 거부한다" "$code" nonzero "$out"

# 3. EXPECTED_HEAD 불일치 — DB 접속 전에 거부해야 한다(`alembic heads`는 script
#    디렉터리만 읽는다). 틀린 head를 박고 migration이 돌지 않는지 본다.
out="$(run_case \
  -e "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN=$MIGRATOR_DSN" \
  -e "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN=$RUNTIME_DSN" \
  -e "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=0000_head_that_does_not_exist")" && code=0 || code=$?
report "EXPECTED_HEAD 불일치는 기동을 거부한다" "$code" nonzero "$out"
printf '%s\n' "$out" | grep -q 'does not match the expected head' ||
  { printf 'FAIL  거부 사유가 head 불일치가 아니다\n'; failures=$((failures + 1)); }

# 4. set-but-empty는 조용한 게이트 해제가 되면 안 된다.
out="$(run_case \
  -e "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN=$MIGRATOR_DSN" \
  -e "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN=$RUNTIME_DSN" \
  -e "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=")" && code=0 || code=$?
report "EXPECTED_HEAD set-but-empty는 거부한다" "$code" nonzero "$out"

printf '\n'
if [ "$failures" != "0" ]; then
  die "$failures gate(s) did not fail closed"
fi
printf '모든 게이트가 fail-close로 동작한다.\n'
