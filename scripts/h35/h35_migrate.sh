#!/usr/bin/env bash
# T-VN-H35 step 3 — **일회성 컨테이너로 0064~0072(9개)를 적용한다.** ⛔ 여기부터 비가역.
#
# 왜 deploy에 맡기지 않나: api-entrypoint.sh가 uvicorn 기동 전에 `alembic upgrade head`를
# 돌리는데, compose의 `--wait-timeout 120`(compose_service.py 하드코딩)에 걸려
# **마이그레이션이 도는 중인 컨테이너를 뜯으며 자동 롤백이 발동한다.** 0069만 8~18분이다.
# 먼저 head에 도달시켜 두면 배포 때 entrypoint의 upgrade가 no-op이라 120초 안에 healthy가 된다.
#
# 비가역 내용(0069 분석 기준):
#   0065 collection_key 52행 재작성 + source_updated_at 3,530행 UPDATE(WHERE 없음)
#   0066 external_component_id backfill
#   -> downgrade로 복구되지 않는다. archive_mode=off라 PITR도 없다.
#   -> 복구 경로는 방금 뜬 dump 하나뿐이다.
#
#   0072 backfill: 기존 link 3,266건에 curation_link_decisions 행 생성 + curation_items UPDATE.
#     downgrade가 그 테이블을 drop하므로 cutover 이후 기록된 진짜 provenance까지 함께 사라진다.
#
# 부분 적용 창은 **0064·0068·0069에만** 있다(autocommit_block 사용). 0070·0071·0072는
# autocommit_block을 쓰지 않아 **all-or-nothing**이다 — 0072 도중 죽으면 DB는 0071에
# 깨끗이 남고 재실행은 처음부터 다시 한다.
# 실패 시 downgrade하지 말고 **같은 명령을 다시** 돌린다(upgrade()가 재진입 가능하다).
#
# ⚠ 0072는 0065가 만드는 operator_updated_by/operator_updated_at을 COALESCE 체인에서 쓴다.
#   0065 없이 0072만 돌리면 컬럼 자체가 없어 실패한다 — head까지 한 번에 올리는 이유다.
set -Eeuo pipefail
umask 077

IMAGE="${1:-}"
[ -n "$IMAGE" ] || { echo "사용법: $0 <candidate api image id>" >&2; exit 1; }

BACKUP=/home/digitie/h35/backup/krtour_map-20260731T065308Z.dump
[ -f "$BACKUP" ] || { echo "** 백업이 없다: $BACKUP — 중단" >&2; exit 1; }
echo "복구 경로 확인: $BACKUP ($(stat -c %s "$BACKUP" | numfmt --to=iec))"

DSN='postgresql+asyncpg://krtour_map:krtour_map_dev_password@127.0.0.1:5432/krtour_map'

echo
echo "=== 적용 전 상태 ==="
docker run --rm --network host -e PGPASSWORD=krtour_map_dev_password postgres:16 \
  psql -h 127.0.0.1 -U krtour_map -d krtour_map -At \
  -c "select 'alembic=' || version_num from alembic_version"

echo
echo "=== writer 정지 (dagster-daemon) ==="
docker stop kor-travel-map-dagster-daemon-latest >/dev/null
echo "  daemon=$(docker inspect kor-travel-map-dagster-daemon-latest --format '{{.State.Status}}')"

# ⚠ **실패 경로에서만** 되살린다. 성공했는데 daemon을 켜면 구 이미지(c8ed6164)가
# 새 스키마 위에서 쓰기를 재개한다 — step3→step4 사이는 writer가 멈춰 있어야 하는 창이고,
# 그 뒤 `ktdctl deploy`가 새 이미지로 recreate한다.
restore_daemon() {
  echo "  ** 실패 — daemon 재기동(구 스키마 상태로 복귀)"
  docker start kor-travel-map-dagster-daemon-latest >/dev/null 2>&1 || true
}
trap restore_daemon ERR

echo
echo "=== alembic upgrade head (일회성 컨테이너, 시간 제한 없음) ==="
S=$(date +%s)
docker run --rm --network host \
  -e KOR_TRAVEL_MAP_PG_DSN="$DSN" \
  --entrypoint sh "$IMAGE" \
  -c 'cd /app && alembic upgrade head' 2>&1 | tail -40
E=$(date +%s)
echo "  소요: $((E-S))초"

echo
echo "=== 적용 후 상태 ==="
docker run --rm --network host -e PGPASSWORD=krtour_map_dev_password postgres:16 \
  psql -h 127.0.0.1 -U krtour_map -d krtour_map -At \
  -c "select 'alembic=' || version_num from alembic_version
      union all select 'dedupe_idx=' || count(*) from pg_indexes
        where schemaname='ops' and indexname='uq_violations_open_dedupe_key'
      union all select 'last_seen_at=' || count(*) from information_schema.columns
        where table_schema='ops' and table_name='data_integrity_violations'
          and column_name='last_seen_at'
      union all select 'ext_component_id=' || count(*) from information_schema.columns
        where table_schema='feature' and table_name='curation_items'
          and column_name='external_component_id'
      union all select 'weather_series=' || count(*) from information_schema.tables
        where table_schema='feature' and table_name='weather_metric_series'
      union all select 'invalid_idx=' || count(*) from pg_index i
        join pg_class c on c.oid=i.indexrelid
        join pg_namespace n on n.oid=c.relnamespace
        where not i.indisvalid and n.nspname in ('feature','ops','provider_sync')
      -- 0070/0071/0072 (배포 전 baseline은 전부 0 — 반증 가능)
      union all select 'domain_commands=' || count(*) from information_schema.tables
        where table_schema='ops' and table_name='domain_commands'
      union all select 'observation_runs=' || count(*) from information_schema.tables
        where table_schema='ops' and table_name='integrity_observation_runs'
      union all select 'link_decisions_tbl=' || count(*) from information_schema.tables
        where table_schema='feature' and table_name='curation_link_decisions'
      union all select 'append_only_triggers=' || count(*) from pg_trigger
        where not tgisinternal and tgname like 'trg_curation_%_append_only'
      -- backfill 정합: decision 수 == 링크된 item 수, 전부 legacy_unattributed
      union all select 'legacy_decisions=' || count(*) from feature.curation_link_decisions
        where match_basis='legacy_unattributed'
      union all select 'linked_items=' || count(*) from feature.curation_items
        where feature_id is not null
      union all select 'items_wo_decision=' || count(*) from feature.curation_items
        where feature_id is not null and accepted_link_decision_id is null"
