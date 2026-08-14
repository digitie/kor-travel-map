#!/usr/bin/env bash
# 두 DB의 카탈로그를 행 단위로 대조한다. alembic squash 동등성 증명의 오라클이다.
#
# 왜 새로 만들지 않고 추출하는가:
#   비교 SQL은 `run-admin-feature-clone-live-acceptance.sh`의 `schema_sha256()`이
#   이미 갖고 있다(304줄). 손으로 복사하면 두 사본이 조용히 어긋난다 — 이 저장소가
#   2026-08-13에만 세 번 겪은 결함 부류다(0102 anchor 불일치, 0104가 hardening 이전
#   원문에서 재생성, live fixture 감사 누락). 그래서 **런타임에 추출**해 정본을 하나로 둔다.
#
# 왜 해시가 아니라 행을 내는가:
#   해시만 비교하면 "다르다"까지만 알 수 있다. squash 검증은 "무엇이 다른가"가 필요하고,
#   그 차이가 의미 있는 것인지(스키마 변경) 표현 차이인지(dump/restore 왕복 불안정)를
#   사람이 판정해야 한다. 실제로 2026-08-13에 그 판정이 `proacl` 물화 문제를 찾아냈다.
#
# 사용:
#   scripts/compare-schema-catalogs.sh <container> <db-a> <db-b> [--admin-user U]
#   scripts/compare-schema-catalogs.sh --self-test <container> <db> [--admin-user U]
#
# `--self-test`는 **오라클을 먼저 증명한다**. 스크래치 DB를 두 벌 만들고 한쪽에만
# 알려진 변조를 주입해, 비교기가 그것을 실제로 잡는지 확인한다. 검사기가 검사 대상을
# 안 보는데 초록인 상태가 이 저장소의 지배적 실패 양식이므로, 어떤 초록도 이 검증
# 없이는 근거가 아니다.
set -euo pipefail

die() { printf 'compare-schema-catalogs: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
RUNNER="$SCRIPT_DIR/run-admin-feature-clone-live-acceptance.sh"
[ -f "$RUNNER" ] || die "digest SQL 원본을 찾지 못했다: $RUNNER"

ADMIN_USER=""
SELF_TEST=0
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --self-test) SELF_TEST=1; shift ;;
    --admin-user) ADMIN_USER="${2:?--admin-user needs a value}"; shift 2 ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

extract_digest_sql() {
  # `schema_sha256() { ... query="$(cat <<'SQL' ... SQL ... }` 에서 SQL 본문만.
  python3 - "$RUNNER" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
try:
    body = src[src.index("schema_sha256() {"):]
    start = body.index("<<'SQL'\n") + len("<<'SQL'\n")
    end = body.index("\nSQL\n", start)
except ValueError:
    raise SystemExit("schema_sha256()의 SQL 헤어독 경계를 찾지 못했다")
sql = body[start:end]
if "COPY (" not in sql or "pg_catalog.pg_class" not in sql:
    raise SystemExit("추출한 SQL이 카탈로그 질의로 보이지 않는다")
print(sql)
PY
}

supplementary_sql() {
  # 추출한 digest SQL이 **보지 않는** 축. 그 SQL의 namespace 필터는 pg_dump의 `-n`
  # 스코프(feature/provider_sync/ops)와 정확히 같아서, **baseline이 재현하지 못하는
  # 것은 오라클도 검사하지 못한다.** 검사기와 검사 대상이 맹점을 공유하는 구조다.
  #
  # 실제로 그 틈으로 결함이 새어 나왔다(2026-08-14): 체인이 `0095`에서 주던
  # `GRANT USAGE ON SCHEMA x_extension TO ktm_feature_runtime`이 baseline에 없어
  # 새 DB의 runtime이 PostGIS를 통째로 잃었는데, 카탈로그는 2486행 전부 일치였다.
  #
  # 그래서 스코프 **밖**을 본다: 모든 스키마의 소유자·ACL, `public`에 남은 객체,
  # event trigger, database 소유자·ACL. 그리고 스코프 안이지만 축이 빠져 있던
  # 제약 **정의**(원본 SQL은 이름·유형·컬럼만 본다).
  #
  # database 이름은 넣지 않는다 — 비교 대상 두 DB는 이름이 다르므로 항상 어긋난다.
  cat <<'SQL'
;
COPY (
  SELECT 'schemaacl' || nsp.nspname || ':' || pg_catalog.pg_get_userbyid(nsp.nspowner) || ':' ||
         COALESCE((SELECT string_agg(entry::text, ',' ORDER BY entry::text)
                     FROM unnest(nsp.nspacl) AS entry), '')
    FROM pg_catalog.pg_namespace AS nsp
   WHERE nsp.nspname NOT LIKE 'pg\_%' AND nsp.nspname <> 'information_schema'
  UNION ALL
  SELECT 'publicrel' || cls.relkind::text || ':' || cls.relname || ':' ||
         pg_catalog.pg_get_userbyid(cls.relowner)
    FROM pg_catalog.pg_class AS cls
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = cls.relnamespace
   WHERE nsp.nspname = 'public'
  UNION ALL
  SELECT 'publicproc' || pro.proname || '(' ||
         pg_catalog.pg_get_function_identity_arguments(pro.oid) || ')'
    FROM pg_catalog.pg_proc AS pro
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = pro.pronamespace
   WHERE nsp.nspname = 'public'
  UNION ALL
  SELECT 'evttrigger' || evt.evtname || ':' || evt.evtevent || ':' || evt.evtenabled::text || ':' ||
         pg_catalog.pg_get_userbyid(evt.evtowner)
    FROM pg_catalog.pg_event_trigger AS evt
  UNION ALL
  SELECT 'dbacl' || pg_catalog.pg_get_userbyid(db.datdba) || ':' ||
         COALESCE((SELECT string_agg(entry::text, ',' ORDER BY entry::text)
                     FROM unnest(db.datacl) AS entry), '')
    FROM pg_catalog.pg_database AS db
   WHERE db.datname = current_database()
  UNION ALL
  SELECT 'constraintdef' || nsp.nspname || '.' || rel.relname || '.' || con.conname || ':' ||
         pg_catalog.pg_get_constraintdef(con.oid)
    FROM pg_catalog.pg_constraint AS con
    JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid
    JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace
   WHERE nsp.nspname IN ('feature', 'provider_sync', 'ops')
  ORDER BY 1
) TO STDOUT
SQL
}

psql_file() { # container db file
  docker exec -i "$1" psql -U "${ADMIN_USER:-postgres}" -d "$2" -tA -f "$3" 2>&1
}

catalog_of() { # container db out
  docker cp "$QUERY_FILE" "$1":/tmp/ktm-catalog-query.sql >/dev/null
  docker exec "$1" psql -U "${ADMIN_USER:-postgres}" -d "$2" -tA -f /tmp/ktm-catalog-query.sql > "$3" 2>&1
  docker exec "$1" rm -f /tmp/ktm-catalog-query.sql >/dev/null 2>&1 || true
  if grep -qE '^(psql:|ERROR:)' "$3"; then
    printf '카탈로그 질의 실패 (%s/%s):\n' "$1" "$2" >&2
    head -5 "$3" >&2
    return 1
  fi
}

QUERY_FILE="$(mktemp)"
trap 'rm -f "$QUERY_FILE" "${TMP_A:-}" "${TMP_B:-}"' EXIT
extract_digest_sql > "$QUERY_FILE"
printf '추출한 digest SQL: %s줄\n' "$(wc -l < "$QUERY_FILE")"
supplementary_sql >> "$QUERY_FILE"
printf '보강 축 추가: 스키마 ACL(전 스키마) · public 잔여 객체 · event trigger · DB ACL · 제약 정의\n'

if [ "$SELF_TEST" = "1" ]; then
  CONTAINER="${ARGS[0]:?container required}"
  BASE_DB="${ARGS[1]:?db required}"
  A="ktm_oracle_control_$$"
  B="ktm_oracle_mutant_$$"
  admin() { docker exec "$CONTAINER" psql -U "${ADMIN_USER:-postgres}" -d postgres -c "$1" >/dev/null 2>&1; }

  printf '\n=== 오라클 자체 검증 ===\n'
  printf '기준 DB %s 를 두 벌 복제한다.\n' "$BASE_DB"
  for db in "$A" "$B"; do
    admin "DROP DATABASE IF EXISTS $db WITH (FORCE)"
    admin "CREATE DATABASE $db TEMPLATE $BASE_DB"
  done

  TMP_A="$(mktemp)"; TMP_B="$(mktemp)"
  catalog_of "$CONTAINER" "$A" "$TMP_A"
  catalog_of "$CONTAINER" "$B" "$TMP_B"
  if ! diff -q "$TMP_A" "$TMP_B" >/dev/null; then
    printf 'FAIL 변조 전인데 두 사본이 다르다 — 비교기가 결정론적이지 않다\n' >&2
    diff "$TMP_A" "$TMP_B" | head -5 >&2
    exit 1
  fi
  printf 'PASS 변조 전 두 사본 동일 (%s행)\n' "$(wc -l < "$TMP_A")"

  # 알려진 변조 7종. 각각이 카탈로그의 **다른 축**을 건드린다 — 하나라도 안 잡히면
  # 그 축은 squash 검증에서 무방비다.
  MUTATIONS=(
    "컬럼 추가|ALTER TABLE feature.features ADD COLUMN ktm_oracle_probe text"
    "NOT NULL 제거|ALTER TABLE provider_sync.source_records ALTER COLUMN raw_payload_hash DROP NOT NULL"
    "인덱스 삭제|DROP INDEX IF EXISTS feature.idx_features_admin_updated_keyset"
    "CHECK 추가|ALTER TABLE feature.features ADD CONSTRAINT ktm_oracle_ck CHECK (row_revision >= 0)"
    "기본값 변경|ALTER TABLE feature.features ALTER COLUMN created_at SET DEFAULT '2000-01-01T00:00:00Z'::timestamptz"
    "소유권 이전|ALTER TABLE ops.feature_overrides OWNER TO ${ADMIN_USER:-postgres}"
    "함수 본문 변경|CREATE OR REPLACE FUNCTION feature.derive_subtype_public_ready() RETURNS trigger LANGUAGE plpgsql AS \$\$BEGIN RETURN NEW; END;\$\$"
  )
  caught=0; missed=0
  for entry in "${MUTATIONS[@]}"; do
    label="${entry%%|*}"; sql="${entry#*|}"
    admin "DROP DATABASE IF EXISTS $B WITH (FORCE)"
    admin "CREATE DATABASE $B TEMPLATE $BASE_DB"
    if ! docker exec "$CONTAINER" psql -U "${ADMIN_USER:-postgres}" -d "$B" -c "$sql" >/dev/null 2>&1; then
      printf 'SKIP %s (변조 SQL이 이 스키마에 적용되지 않는다)\n' "$label"
      continue
    fi
    catalog_of "$CONTAINER" "$B" "$TMP_B"
    if diff -q "$TMP_A" "$TMP_B" >/dev/null; then
      printf 'FAIL %s — 비교기가 잡지 못했다\n' "$label"
      missed=$((missed + 1))
    else
      printf 'PASS %s (%s행 차이)\n' "$label" "$(diff "$TMP_A" "$TMP_B" | grep -c '^[<>]')"
      caught=$((caught + 1))
    fi
  done

  admin "DROP DATABASE IF EXISTS $A WITH (FORCE)"
  admin "DROP DATABASE IF EXISTS $B WITH (FORCE)"
  printf '\n잡음 %s / 놓침 %s\n' "$caught" "$missed"
  [ "$missed" = "0" ] ||
    die "오라클이 카탈로그 축 $missed개를 보지 못한다 — 이 비교기로는 squash를 증명할 수 없다"
  printf '오라클 검증 통과 — 이 비교기의 초록은 근거로 쓸 수 있다.\n'
  exit 0
fi

CONTAINER="${ARGS[0]:?container required}"
DB_A="${ARGS[1]:?db-a required}"
DB_B="${ARGS[2]:?db-b required}"
TMP_A="$(mktemp)"; TMP_B="$(mktemp)"
catalog_of "$CONTAINER" "$DB_A" "$TMP_A"
catalog_of "$CONTAINER" "$DB_B" "$TMP_B"
printf '%s: %s행 / %s: %s행\n' "$DB_A" "$(wc -l < "$TMP_A")" "$DB_B" "$(wc -l < "$TMP_B")"

# 제약 **정의**(`constraintdef`) 축은 따로 낸다. dump된 식을 다시 파싱하면
# PostgreSQL이 같은 의미를 다르게 deparse한다(AND 평탄화, cast 위치). 그 표현 차이를
# 자동으로 지우려 들면 `A AND (B OR C)` 와 `(A AND B) OR C` 처럼 **의미가 다른**
# 재괄호화까지 함께 지워진다 — 괄호를 떼어 비교하면 두 식의 토큰 열이 같아진다.
# 그래서 지우지 않고 **분리해서 보여 준다.** 사람이 판정하는 것이 이 축의 설계다.
CORE_A="$(mktemp)"; CORE_B="$(mktemp)"
CON_A="$(mktemp)"; CON_B="$(mktemp)"
trap 'rm -f "$QUERY_FILE" "${TMP_A:-}" "${TMP_B:-}" "$CORE_A" "$CORE_B" "$CON_A" "$CON_B"' EXIT
grep -v '^constraintdef' "$TMP_A" > "$CORE_A"; grep '^constraintdef' "$TMP_A" > "$CON_A" || true
grep -v '^constraintdef' "$TMP_B" > "$CORE_B"; grep '^constraintdef' "$TMP_B" > "$CON_B" || true

status=0
if diff -q "$CORE_A" "$CORE_B" >/dev/null; then
  printf '카탈로그 동일 — sha256 %s (%s행)\n' \
    "$(sha256sum < "$CORE_A" | awk '{print $1}')" "$(wc -l < "$CORE_A")"
else
  printf '카탈로그 차이 %s행:\n' "$(diff "$CORE_A" "$CORE_B" | grep -c '^[<>]')"
  diff "$CORE_A" "$CORE_B" | head -40 | cut -c1-200
  status=1
fi

if diff -q "$CON_A" "$CON_B" >/dev/null; then
  printf '제약 정의 동일 (%s행)\n' "$(wc -l < "$CON_A")"
else
  printf '\n제약 정의 차이 %s행 — **판정 필요** (deparse 표현 차이인지 의미 차이인지):\n' \
    "$(diff "$CON_A" "$CON_B" | grep -c '^[<>]')"
  diff "$CON_A" "$CON_B" | cut -c1-220
  printf '판정 결과는 PR/문서에 남겨라. 자동으로 지우지 않는다.\n'
  status=1
fi
exit "$status"
