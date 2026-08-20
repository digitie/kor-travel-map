#!/usr/bin/env bash
# T-VN-41S `0231` 격리 DB 리허설 게이트.
#
# 본문은 scripts/tvn41s_material_rehearsal.py에 있다 — 왜 빈 DB로는 검증이 안 되는지도
# 그 docstring에 적혀 있다. 이 파일은 격리 DB를 만들고 자격증명을 넘긴 뒤 지우는
# 드라이버다. 대상 DB를 DROP하므로 운영 DB 이름이 들어오면 즉시 멈춘다.
#
# usage: scripts/verify-tvn41s-snapshot-material.sh
# env:
#   KTM_41S_DB           기본 ktm_tvn41s_rehearsal (격리 DB)
#   KTM_41S_PG_CONTAINER 기본 kor-travel-map-postgres
#   KTM_41S_PYTHON       기본 python3
set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${KTM_41S_DB:-ktm_tvn41s_rehearsal}"
PG_CONTAINER="${KTM_41S_PG_CONTAINER:-kor-travel-map-postgres}"
PG_HOST="${KTM_41S_PG_HOST:-127.0.0.1}"
PG_PORT="${KTM_41S_PG_PORT:-12700}"
PG_USER="${KTM_41S_PG_USER:-kor_travel_map}"
PYTHON="${KTM_41S_PYTHON:-python3}"

for forbidden in kor_travel_map kor_travel_map_dagster postgres template0 template1; do
  [ "$DB" = "$forbidden" ] && { echo "거부: '$forbidden'은 격리 DB가 아니다"; exit 2; }
done

cd "$SRC" || exit 1

PGPW="$(docker exec "$PG_CONTAINER" sh -c 'cat "$POSTGRES_PASSWORD_FILE"')" || {
  echo "postgres password를 읽지 못했다"; exit 2; }

psql_adm() {
  docker exec -e PGPASSWORD="$PGPW" "$PG_CONTAINER" \
    psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 "$@"
}

psql_adm -c "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB OWNER $PG_USER" \
  >/dev/null || { echo "격리 DB 생성 실패"; exit 1; }

export PYTHONPATH="$SRC/src:$SRC/packages/kor-travel-map-api/src:$SRC/packages/kor-travel-map-dagster/src:$SRC"
export KOR_TRAVEL_MAP_PG_DSN="postgresql+asyncpg://${PG_USER}:${PGPW}@${PG_HOST}:${PG_PORT}/${DB}"

"$PYTHON" "$SRC/scripts/tvn41s_material_rehearsal.py" "$SRC"
status=$?

psql_adm -c "DROP DATABASE IF EXISTS $DB" >/dev/null 2>&1
echo "리허설 DB 정리 완료 (exit=$status)"
exit $status
