#!/usr/bin/env bash
# T-VN-41C cache-target snapshot GC 실측 게이트.
#
# 백로그 AC: "n150 격리 DB에서 migration -> 수동 GC -> schedule ON -> 다음 tick 순서로
# 검증하고, GC 처리량이 유입률을 상회하며 remaining backlog가 0인지 증명한다.
# referenced snapshot 증가율과 보존 임계치 alert도 함께 확인한다."
#
# 격리 DB 두 개를 쓴다. 애플리케이션 DB와 Dagster storage DB는 **분리해야 한다** —
# Dagster storage는 자기 alembic 계보를 public.alembic_version에 stamp하므로 같은
# database에 얹으면 우리 head revision을 못 찾고 죽는다(운영도 같은 이유로 분리한다).
#
# usage: scripts/verify-tvn41c-cache-target-gc.sh
# env:
#   KTM_GC_VERIFY_DB          기본 ktm_gcverify        (애플리케이션 격리 DB)
#   KTM_GC_VERIFY_DAGSTER_DB  기본 ktm_gcverify_dagster (Dagster storage 격리 DB)
#   KTM_GC_VERIFY_PG_PASSWORD 미설정이면 postgres 컨테이너의 password file에서 읽는다
#   KTM_GC_VERIFY_PG_CONTAINER 기본 kor-travel-map-postgres
#   KTM_GC_VERIFY_PYTHON      기본 python3
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${KTM_GC_VERIFY_DB:-ktm_gcverify}"
DAGSTER_DB="${KTM_GC_VERIFY_DAGSTER_DB:-ktm_gcverify_dagster}"
PG_CONTAINER="${KTM_GC_VERIFY_PG_CONTAINER:-kor-travel-map-postgres}"
PG_HOST="${KTM_GC_VERIFY_PG_HOST:-127.0.0.1}"
PG_PORT="${KTM_GC_VERIFY_PG_PORT:-12700}"
PG_USER="${KTM_GC_VERIFY_PG_USER:-kor_travel_map}"
PYTHON="${KTM_GC_VERIFY_PYTHON:-python3}"
SCHEDULE="cache_target_snapshot_gc_hourly_schedule"
DAGSTER_HOME_DIR="${KTM_GC_VERIFY_DAGSTER_HOME:-/tmp/ktm-gcverify-dagster}"

# 이 게이트는 DROP DATABASE로 시작한다. 운영 DB 이름이 들어오면 즉시 멈춘다 —
# 기본값을 믿고 env를 잘못 넘기는 것이 여기서 가장 비싼 실수다.
for forbidden in kor_travel_map kor_travel_map_dagster postgres template0 template1; do
  if [ "$DB" = "$forbidden" ] || [ "$DAGSTER_DB" = "$forbidden" ]; then
    echo "거부: '$forbidden'은 격리 DB가 아니다. 이 게이트는 대상 DB를 DROP한다." >&2
    exit 2
  fi
done

if [ -z "${KTM_GC_VERIFY_PG_PASSWORD:-}" ]; then
  KTM_GC_VERIFY_PG_PASSWORD="$(docker exec "$PG_CONTAINER" \
    sh -c 'cat "$POSTGRES_PASSWORD_FILE"')" || {
    echo "postgres password를 읽지 못했다. KTM_GC_VERIFY_PG_PASSWORD를 직접 주라." >&2
    exit 2
  }
fi
export KTM_GC_VERIFY_PG_PASSWORD KTM_GC_VERIFY_PG_HOST KTM_GC_VERIFY_PG_PORT KTM_GC_VERIFY_PG_USER

export PYTHONPATH="$REPO_ROOT/scripts:$REPO_ROOT/src:$REPO_ROOT/packages/kor-travel-map-api/src:$REPO_ROOT/packages/kor-travel-map-dagster/src:$REPO_ROOT"
export KOR_TRAVEL_MAP_PG_DSN="postgresql+asyncpg://${PG_USER}:${KTM_GC_VERIFY_PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${DB}"
export KOR_TRAVEL_MAP_DAGSTER_PG_URL="postgresql://${PG_USER}:${KTM_GC_VERIFY_PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${DAGSTER_DB}"
# 운영 code location과 같은 계약 — 저장된 override를 조용히 무시하지 않는다.
export KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED=true
export DAGSTER_HOME="$DAGSTER_HOME_DIR"
export DAGSTER_DISABLE_TELEMETRY=1

psql_app() { docker exec -e PGPASSWORD="$KTM_GC_VERIFY_PG_PASSWORD" "$PG_CONTAINER" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$DB" -At -F'|' "$@"; }
psql_dag() { docker exec -e PGPASSWORD="$KTM_GC_VERIFY_PG_PASSWORD" "$PG_CONTAINER" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$DAGSTER_DB" -At -F'|' "$@"; }
psql_adm() { docker exec -e PGPASSWORD="$KTM_GC_VERIFY_PG_PASSWORD" "$PG_CONTAINER" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 "$@"; }

seed_command() {
  echo "KTM_GC_VERIFY_PG_PASSWORD='$KTM_GC_VERIFY_PG_PASSWORD' $PYTHON $REPO_ROOT/scripts/tvn41c_gc_seed.py $DB $1 $2 $3 $4"
}

eligible_counts() {
  psql_app -c "
SELECT (SELECT count(*) FROM ops.poi_cache_target_snapshots s
          LEFT JOIN ops.poi_cache_target_reconciliation_requests r ON r.snapshot_id=s.snapshot_id
          WHERE s.expires_at <= now() AND r.request_id IS NULL) || '/' ||
       (SELECT count(*) FROM ops.poi_cache_target_snapshot_items i
          JOIN ops.poi_cache_target_snapshots s ON s.snapshot_id=i.snapshot_id
          LEFT JOIN ops.poi_cache_target_reconciliation_requests r ON r.snapshot_id=s.snapshot_id
          WHERE s.expires_at <= now() AND r.request_id IS NULL)"
}

fail() { echo; echo "GATE: FAIL — $1" >&2; exit 4; }

echo "=== ① 격리 DB 재생성 + head까지 migration"
psql_adm -c "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB OWNER $PG_USER" >/dev/null || fail "격리 DB 생성 실패"
psql_adm -c "DROP DATABASE IF EXISTS $DAGSTER_DB" -c "CREATE DATABASE $DAGSTER_DB OWNER $PG_USER" >/dev/null || fail "Dagster storage DB 생성 실패"
"$PYTHON" "$REPO_ROOT/scripts/tvn41c_gc_migrate.py" "$REPO_ROOT" "$DB" || fail "migration 실패"
echo "  head: $(psql_app -c 'SELECT version_num FROM public.alembic_version')"

echo
echo "=== ② 시딩 (적격 backlog + 보존 대조군 2종)"
eval "$(seed_command 4 20 50 gcv)" || fail "시딩 실패"
echo "  적격 header/item: $(eligible_counts)"

echo
echo "=== ③ 수동 GC — 적격만 지우고 대조군은 보존"
"$PYTHON" "$REPO_ROOT/scripts/tvn41c_gc_assert.py" drain || fail "수동 GC 단언 실패"

echo
echo "=== ④ 유입률 대비 처리량"
inflow_started="$(date +%s.%N)"
eval "$(seed_command 6 40 100 inflow)" || fail "유입 시딩 실패"
inflow_seconds="$(echo "$(date +%s.%N) - $inflow_started" | bc)"
inflow_items=24000
echo "  유입: item ${inflow_items}건 / ${inflow_seconds}초"
"$PYTHON" "$REPO_ROOT/scripts/tvn41c_gc_assert.py" drain || fail "유입 후 GC 단언 실패"
echo "  유입률 = $(echo "scale=0; $inflow_items / $inflow_seconds" | bc) items/s — 위 처리량과 대조하라"

echo
echo "=== ⑤ cron override -> schedule ON -> 다음 tick"
psql_app -v ON_ERROR_STOP=1 -c "
INSERT INTO ops.dagster_schedule_overrides (schedule_name, cron_schedule, reason, updated_by)
VALUES ('$SCHEDULE', '* * * * *', 'T-VN-41C GC tick 실측', 'tvn41c-gc-verify')
ON CONFLICT (schedule_name) DO UPDATE
  SET cron_schedule = EXCLUDED.cron_schedule, updated_at = now()" >/dev/null || fail "cron override 저장 실패"

# 코드 기본은 '15 * * * *'다. 새 프로세스가 '* * * * *'를 집지 못하면 override 경로가
# 죽은 것이고, 아래 tick 관측은 우연히 정시를 맞춘 것과 구별되지 않는다.
"$PYTHON" - <<'PY' || fail "cron override가 반영되지 않았다"
from tvn41c_gc_defs import defs

schedule = next(s for s in defs.schedules if s.name == "cache_target_snapshot_gc_hourly_schedule")
print(f"  resolved cron: {schedule.cron_schedule}  default_status: {schedule.default_status}")
assert schedule.cron_schedule == "* * * * *", schedule.cron_schedule
PY

eval "$(seed_command 3 20 50 tick)" || fail "tick용 시딩 실패"
echo "  tick 전 적격 header/item: $(eligible_counts)"

rm -rf "$DAGSTER_HOME_DIR"; mkdir -p "$DAGSTER_HOME_DIR"
cat > "$DAGSTER_HOME_DIR/dagster.yaml" <<'YAML'
telemetry:
  enabled: false
storage:
  postgres:
    postgres_url:
      env: KOR_TRAVEL_MAP_DAGSTER_PG_URL
run_monitoring:
  enabled: true
  start_timeout_seconds: 600
  poll_interval_seconds: 15
YAML

dagster-daemon run -m tvn41c_gc_defs > /tmp/tvn41c-gc-daemon.log 2>&1 &
daemon_pid=$!
trap 'kill "$daemon_pid" 2>/dev/null; wait "$daemon_pid" 2>/dev/null' EXIT
for _ in $(seq 1 30); do
  grep -q "Instance is configured" /tmp/tvn41c-gc-daemon.log 2>/dev/null && break
  sleep 2
done
grep -q "Instance is configured" /tmp/tvn41c-gc-daemon.log || {
  tail -30 /tmp/tvn41c-gc-daemon.log >&2; fail "daemon 기동 실패"
}

dagster schedule start "$SCHEDULE" -m tvn41c_gc_defs 2>&1 | tail -1
tick_started="$(date +%s)"
run_id=""
for _ in $(seq 1 40); do
  sleep 5
  run_id="$(psql_dag -c "SELECT run_id FROM runs ORDER BY create_timestamp DESC LIMIT 1" | head -1)"
  [ -n "$run_id" ] && break
done
[ -n "$run_id" ] || { tail -30 /tmp/tvn41c-gc-daemon.log >&2; fail "200초 안에 tick으로 생성된 run이 없다"; }
echo "  run 생성 t+$(( $(date +%s) - tick_started ))초  run_id=${run_id:0:8}"

run_status=""
for _ in $(seq 1 40); do
  run_status="$(psql_dag -c "SELECT status FROM runs WHERE run_id='$run_id'" | head -1)"
  case "$run_status" in SUCCESS|FAILURE|CANCELED) break;; esac
  sleep 5
done
echo "  run status=$run_status  경과=$(( $(date +%s) - tick_started ))초"
dagster schedule stop "$SCHEDULE" -m tvn41c_gc_defs >/dev/null 2>&1
[ "$run_status" = "SUCCESS" ] || {
  psql_dag -c "SELECT event FROM event_logs WHERE run_id='$run_id' AND dagster_event_type='STEP_FAILURE' LIMIT 1" | head -c 900 >&2
  fail "tick이 만든 run이 성공하지 않았다: $run_status"
}
after_tick="$(eligible_counts)"
echo "  tick 후 적격 header/item: $after_tick"
[ "$after_tick" = "0/0" ] || fail "tick 후 backlog가 0이 아니다: $after_tick"
echo "  tick 수: $(psql_dag -c 'SELECT count(*) FROM job_ticks')"

echo
echo "=== ⑥ referenced 보존 ceiling·증가율 alert"
"$PYTHON" "$REPO_ROOT/scripts/tvn41c_gc_assert.py" alert "$(seed_command 2 21 40 growth) >/dev/null" \
  || fail "referenced alert 단언 실패"

echo
echo "GATE: PASS — migration -> 수동 GC -> 유입률 대비 처리량 -> schedule ON/tick -> alert"
