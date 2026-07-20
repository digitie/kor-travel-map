# Runbook — CONCURRENTLY 실패로 남은 INVALID index 탐지·drop (T-VN-H05)

`CREATE INDEX CONCURRENTLY`(및 `REINDEX ... CONCURRENTLY`)가 실패하거나 도중에 중단되면
**INVALID index**(`pg_index.indisvalid = false`)가 남는다. 이 index는 조회에 쓰이지 않으면서
write 비용만 유발하고, 같은 이름의 재빌드를 막는다. **조용히** 서지 않으므로 명시적으로
탐지·검증·drop해야 한다. 이 runbook은 그 일반 운영 절차다.

관련: [ADR-075](../adr/075-cutover-and-ddl-discipline.md) §6 · alembic
`0061_gist_brin_index_audit.py`(CONCURRENTLY self-heal) · `0060_weather_integrity.py`(원자성
우선 non-concurrent build) · [`../architecture/performance.md`](../architecture/performance.md)
§8.3 Tier 3 · [`docker-app.md`](./docker-app.md) §8(cutover DDL 기록).

## 1. 왜 INVALID index가 남는가

- `CREATE INDEX CONCURRENTLY`는 여러 스캔 단계로 나뉘고, 각 단계에서 lock 대기·timeout·
  deadlock·수동 취소·연결 끊김이 나면 **롤백되지 않고** index가 `indisvalid = false`(때로
  `indisready = false`)로 남는다.
- INVALID index는 planner가 **선택하지 않으므로** 조회는 seq-scan/다른 index로 조용히 fallback
  한다 — 성능 저하가 서지 않고, 정합성 문제로 오인되기 쉽다.
- 그런데도 INSERT/UPDATE는 그 index를 유지하려 시도하므로 write 비용은 그대로 든다.
- 같은 이름으로 재빌드하려면 leftover를 먼저 제거해야 한다.

## 2. 탐지 (Detection)

`pg_index.indisvalid = false`를 `pg_class`/`pg_namespace` join으로 index·table 이름과 함께 본다.

```sql
-- 모든 INVALID index (schema·table·index 이름과 크기).
SELECT
    n.nspname                                AS schema_name,
    t.relname                                AS table_name,
    c.relname                                AS index_name,
    i.indisvalid,
    i.indisready,
    pg_size_pretty(pg_relation_size(c.oid))  AS index_size
FROM pg_index i
JOIN pg_class c     ON c.oid = i.indexrelid
JOIN pg_class t     ON t.oid = i.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE i.indisvalid = false
  AND c.relkind = 'i'
ORDER BY n.nspname, t.relname, c.relname;
```

- `indisvalid = false` : 조회에 쓰이지 않는(INVALID) index. 항상 정리 대상.
- `indisready = false` : 아직 write 반영도 시작 못 한 상태. 역시 실패 잔재.
- 0 rows면 clean. 배포/cutover 게이트에서 이 쿼리가 **0 rows**임을 확인한다
  ([`docker-app.md`](./docker-app.md) §8, [`../architecture/performance.md`](../architecture/performance.md) §8.3).
- `_ccnew`/`_ccold` suffix가 붙은 이름은 실패한 `REINDEX CONCURRENTLY`의 임시 잔재다.

> 검증: 위 탐지 쿼리와 §3 drop을 `postgis/postgis:16-3.5` 컨테이너에서 실행 확인했다.
> `indisvalid`를 강제로 false로 만든 index를 정확히 탐지하고, `DROP INDEX CONCURRENTLY IF
> EXISTS`로 제거 후 탐지 쿼리가 0 rows로 돌아옴을 확인했다.

## 3. drop 후 재빌드 (Recovery)

INVALID index는 `DROP INDEX CONCURRENTLY`로 제거한다(다른 조회의 lock을 막지 않는다).

```sql
-- transaction 밖(autocommit)에서 실행. IF EXISTS로 재실행 안전.
DROP INDEX CONCURRENTLY IF EXISTS feature.<invalid_index_name>;
```

- `DROP INDEX CONCURRENTLY`는 **transaction block 안에서 실행 불가** — 반드시 autocommit으로.
  alembic migration은 `op.get_context().autocommit_block()` 안에서 `op.execute(...)`로 감싼다
  (0061 예시).
- drop 뒤, 그 index가 **의도된 index면 원래 migration/DDL을 재실행**해 valid하게 재빌드한다.
  재빌드 자체도 CONCURRENTLY면 실패 시 다시 leftover가 남을 수 있으므로 §2로 재확인한다.
- CONCURRENTLY를 쓸 수 없어야 하는 짧은 유지보수 창에서는 명시적 lock 아래 원자 정리를 쓴다
  ([`docker-app.md`](./docker-app.md) §8.2의 `SHARE ROW EXCLUSIVE` + `DROP INDEX` 패턴):

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
LOCK TABLE feature.<table> IN SHARE ROW EXCLUSIVE MODE;
DROP INDEX IF EXISTS feature.<invalid_index_name>;
COMMIT;
```

## 4. 예방 / 맥락 (마이그레이션 self-heal)

신규 migration은 이 수동 절차에 의존하지 않도록 **self-heal**을 내장한다 — 이 runbook은
그 밖의 일반적(수동) 케이스와 배포 게이트용이다.

- **`0061_gist_brin_index_audit.py`(T-VN-18)** — 모든 DROP/CREATE를 `autocommit_block`의
  `CONCURRENTLY`로 하고, 각 `CREATE INDEX CONCURRENTLY` **전에** 같은 이름의 leftover를
  `DROP INDEX CONCURRENTLY IF EXISTS`로 먼저 제거해 재실행을 안전하게 만든다. weather
  source-record 지원 index(T-VN-17 이월)도 같은 self-heal 패턴이다.
- **`0060_weather_integrity.py`(T-VN-17)** — dedup과 semantic UNIQUE 사이에 writer race가
  있어 성능보다 **원자성**을 우선한다. table writer lock 아래 **non-concurrent** build를 한
  transaction으로 묶으므로 실패 시 함께 롤백돼 INVALID index를 남기지 않는다(그 대신 lock
  대기·보유 시간을 기록한다). 즉 0060은 이 runbook의 대상이 아니다.

migration이 아닌 수술형/운영 DDL, 또는 self-heal 없는 과거 잔재가 배포 게이트에서 검출되면
이 runbook의 §2 탐지 → §3 drop → 원 DDL 재실행 순서를 따른다. DDL 유형별 lock 규율은
ADR-075 §6, cutover 절차는 [`docker-app.md`](./docker-app.md) §8이 정본이다.

## 5. 관련 문서

- [ADR-075](../adr/075-cutover-and-ddl-discipline.md) §6 — 수술형 DDL·실패한 concurrent index 관리.
- [`../architecture/performance.md`](../architecture/performance.md) §8.3 Tier 3 — index/DDL 변경 PR 게이트(INVALID 0건 확인).
- [`../architecture/postgres-schema.md`](../architecture/postgres-schema.md) §8.2 — migration 기준 DDL 유형.
- [`docker-app.md`](./docker-app.md) §8 — production cutover DDL 기록·원자 정리.
- [`coord-5179-proj-pin.md`](./coord-5179-proj-pin.md) — REINDEX CONCURRENTLY 실패 시 이 runbook을 참조(T-VN-H04).
