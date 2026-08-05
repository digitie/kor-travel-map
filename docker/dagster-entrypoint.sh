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

# api-entrypoint와 같은 규약 — 제거된 스위치가 설정돼 있으면 조용히 무시하지
# 않고 거부한다(두 컨테이너가 같은 env 블록에서 다른 판정을 내면 안 된다).
if [ "${KOR_TRAVEL_MAP_MIGRATION_MODE+x}" = "x" ]; then
  echo "KOR_TRAVEL_MAP_MIGRATION_MODE was removed; startup migration is always on" >&2
  exit 1
fi

# ── DB 세대 기계 인터록 (NEW-5, ADR-083 유예 해소) ──────────────────────────
#
# api-entrypoint의 EXPECTED_HEAD 게이트와 같은 규약이되 이 스크립트는 **읽기
# 전용**이다 — schema migration은 api-entrypoint 소유이며 여기서는 절대
# 실행하지 않는다. dagster 이미지를 api보다 먼저 재배포하면 코드(신세대)와
# DB(구세대)가 어긋난 채 조용히 기동하던 공백(0083 배포 때 "api 먼저" 순서를
# 사람이 지켜야 했던 이유)을 기계로 막는다: DB revision이 이 이미지의 alembic
# head와 일치할 때만 기동한다.
#
# set-but-empty는 거부한다 — api-entrypoint와 같은 규약. compose `${HOST:-}`
# 패턴에서 host env 누락이 조용한 게이트 해제가 되면 안 된다.
if [ "${KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD+x}" = "x" ]; then
  expected_head="$KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD"
  if [ -z "$expected_head" ]; then
    echo "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD is set but empty; refusing to silently disable the head gate" >&2
    exit 1
  fi
else
  expected_head=""
fi

# `alembic heads`는 script 디렉터리만 읽는다 — DB 연결 전에 판정할 수 있다.
# EXPECTED_HEAD 유무와 무관하게 항상 읽는다: DB↔이미지 세대 대조가 이 게이트의
# 존재 이유고, 그 기준값이 이미지 head다. EXPECTED_HEAD는 설정된 경우에만
# 추가로 대조한다.
# 주의: alembic은 CommandError를 **stdout**에 쓰고 비정상 종료한다(stderr 아님).
# 출력 내용이 아니라 exit code로 실행 실패를 먼저 판정해야 오진 메시지가 나가지 않는다.
if ! heads_raw="$(alembic heads 2>/dev/null)"; then
  echo "alembic heads failed; the image alembic configuration is broken" >&2
  echo "(cannot evaluate the dagster DB generation gate; nothing was started)" >&2
  # 1차 실행은 파싱 청정성 위해 stderr를 버렸다 — 증거(import/traceback 계열은
  # stderr로 나간다)를 재실행으로 통째 표출한다 (리뷰 F2).
  alembic heads >&2 2>&1 || true
  exit 1
fi
image_heads="$(printf '%s\n' "$heads_raw" | awk 'NF {print $1}')"
if [ -z "$image_heads" ]; then
  echo "alembic heads printed nothing (cannot evaluate the dagster DB generation gate)" >&2
  exit 1
fi
head_count="$(printf '%s\n' "$image_heads" | grep -c '^')"
if [ "$head_count" != "1" ]; then
  echo "the image has more than one alembic head: $(printf '%s' "$image_heads" | tr '\n' ' ')" >&2
  exit 1
fi
if [ -n "$expected_head" ] && [ "$image_heads" != "$expected_head" ]; then
  echo "the image alembic head does not match the expected head" >&2
  echo "  expected: ${expected_head}" >&2
  echo "  image:    ${image_heads}" >&2
  echo "the deployed image was not built with the intended migration chain; the DB was not touched" >&2
  exit 1
fi

# DB 세대 게이트 — `alembic current`(읽기 전용)로 DB revision을 읽는다.
#   - DB revision이 이미지 chain 밖(stale 이미지 재배포): `alembic current`가
#     "Can't locate revision"으로 실패한다. 영구 오류이므로 retry로 두드리지
#     않고 즉시 죽는다 — api-entrypoint의 stale-이미지 판정과 동일.
#   - DB revision이 chain 안이지만 head가 아님(빈 DB 포함): api가 아직
#     migration을 돌리지 않았다 — api를 먼저 배포하라는 메시지로 즉시 죽는다.
#   - 연결 일시 오류만 retry한다(api-entrypoint와 같은 env, 기본 30회/2초).
# alembic.ini가 로그를 stderr로 보내므로 stdout에는 revision(또는 CommandError
# 원문)만 남는다. stderr는 그대로 컨테이너 로그로 흘려 운영자가 원인을 본다.
retries="${KOR_TRAVEL_MAP_MIGRATION_RETRIES:-30}"
sleep_seconds="${KOR_TRAVEL_MAP_MIGRATION_RETRY_SLEEP_SECONDS:-2}"
attempt=1
while :; do
  if current_out="$(alembic current)"; then
    break
  fi
  case "$current_out" in
    *"Can't locate revision"*)
      echo "the DB alembic revision is not part of this image's migration chain" >&2
      echo "(the image is older than the DB — a stale image was deployed; the DB was not touched)" >&2
      printf '%s\n' "$current_out" >&2
      exit 1
      ;;
  esac
  if [ "$attempt" -ge "$retries" ]; then
    echo "alembic current failed after $attempt attempts; cannot evaluate the dagster DB generation gate" >&2
    printf '%s\n' "$current_out" >&2
    exit 1
  fi
  echo "alembic current failed; retrying ($attempt/$retries)" >&2
  attempt=$((attempt + 1))
  sleep "$sleep_seconds"
done

db_revision="$(printf '%s\n' "$current_out" | awk 'NF {print $1}')"
if [ -n "$db_revision" ]; then
  db_line_count="$(printf '%s\n' "$db_revision" | grep -c '^')"
  if [ "$db_line_count" != "1" ]; then
    echo "the DB reports multiple alembic revisions (branched alembic_version):" >&2
    printf '%s\n' "$db_revision" >&2
    echo "resolve the branched alembic_version rows before starting dagster" >&2
    exit 1
  fi
fi
if [ "$db_revision" != "$image_heads" ]; then
  echo "the DB alembic revision does not match this image's migration head" >&2
  echo "  image head: ${image_heads}" >&2
  echo "  db:         ${db_revision:-<empty>}" >&2
  echo "the DB is behind the image — deploy the api container first (api-entrypoint owns the schema migration; the dagster container never migrates)" >&2
  exit 1
fi

exec "$@"
