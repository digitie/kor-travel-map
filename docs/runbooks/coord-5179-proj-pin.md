# Runbook — `coord_5179` PROJ 버전 고정 · drift 검사 · REINDEX (T-VN-H04)

`feature.features.coord_5179`는 `coord`(EPSG:4326)에서 EPSG:5179(meter)로 변환한
**STORED generated column**이고, 반경 검색의 핵심 index `idx_features_coord_5179_gist`
(GiST)가 이 컬럼을 색인한다. 변환 결과는 PROJ 라이브러리 버전에 종속하므로, PROJ/PostGIS
upgrade는 저장값과 index를 **조용히** stale로 만들 수 있다. 이 runbook은 그 버전을 고정하고,
drift를 탐지하고, 검출 시 재계산 + REINDEX 하는 운영 절차다.

관련: [ADR-075](../adr/075-cutover-and-ddl-discipline.md)(DDL 규율) ·
[`../architecture/performance.md`](../architecture/performance.md) §7.1(generated column) ·
[`../architecture/postgres-schema.md`](../architecture/postgres-schema.md) §4.1(index 카탈로그) ·
alembic `0002_features_and_source_tables.py`(컬럼·index 정의).

## 1. 왜 (배경)

`coord_5179`의 정의는 alembic 0002가 만든 그대로다(정본):

```sql
-- feature.features.coord_5179 (STORED generated)
coord_5179 geometry(Point, 5179)
    GENERATED ALWAYS AS (
        CASE WHEN coord IS NULL THEN NULL
             ELSE ST_Transform(coord, 5179) END
    ) STORED
```

```sql
-- 반경 검색 핵심 index (partial GiST)
CREATE INDEX idx_features_coord_5179_gist ON feature.features
    USING GIST (coord_5179) WHERE deleted_at IS NULL;
```

- `ST_Transform(coord, 5179)`의 수치 출력은 PROJ의 좌표 변환 grid·알고리즘에 종속한다.
  PROJ major/minor upgrade(때로는 patch)에서 5179 변환 결과가 sub-meter 수준으로 바뀔 수 있다.
- `coord_5179`는 **STORED**라 값이 물리적으로 heap에 박혀 있다 → row가 다시 쓰이기 전에는
  옛 PROJ로 계산된 값이 그대로 남는다. GiST index도 그 옛 값으로 build돼 있다.
- 따라서 PROJ upgrade 후에는 (1) 새로 insert/update된 행은 새 PROJ 값, (2) 손대지 않은 기존
  행은 옛 PROJ 값이 섞여, 반경 경계 근처에서 `ST_DWithin`/`<->` 결과가 미세하게 어긋난다.
  index recheck는 저장된(=옛) 값을 쓰므로 오차가 **드러나지 않고** 조회에 반영된다.

## 2. 버전 고정 (Pin)

- PostGIS 버전은 배포 image tag **`postgis/postgis:16-3.5-alpine`** 이 이미 고정한다
  (테스트: testcontainers, ADR-007; 참고 [`../test-strategy.md`](../test-strategy.md)).
  **PROJ 버전은 그 image에 번들된 값에 결박**되며, tag를 바꾸지 않는 한 고정이다.
- 이 tag를 올리는 것은 **PROJ upgrade와 동치**다. §3 drift 검사 + §4 재계산/REINDEX 없이는
  image tag(PostGIS/PROJ)를 올리지 않는다. tag 상향은 ADR-075 cutover 절차를 따르는 별도
  변경으로 다루고, 상향 전후로 §3을 반드시 실행한다.
- 현재 고정 baseline(참고값, `postgis/postgis:16-3.5` 계열 실측):
  PostGIS `3.5.2`, PROJ `7.2.1`. 실 배포 DB에서 정확한 baseline을 캡처해 배포 기록에 남긴다:

```sql
SELECT postgis_full_version();   -- POSTGIS/PROJ/GEOS 전체 문자열
SELECT postgis_proj_version();   -- PROJ 버전만
```

배포마다 위 두 값을 release 기록에 남겨, 다음 upgrade에서 before/after를 비교할 수 있게 한다.

## 3. drift 검사 (Detection)

저장된 `coord_5179`를 **현재 PROJ로 재계산한** `ST_Transform(coord, 5179)`와 비교한다.
두 지오메트리 사이 거리(meter)가 임계 초과면 drift다. 먼저 요약, 그다음 offender 목록.

```sql
-- 요약: 검사 대상 수 / drift 행 수 / 최대 drift(m). drifted=0 이면 clean.
SELECT
    count(*)                                                          AS checked,
    count(*) FILTER (
        WHERE ST_Distance(f.coord_5179, ST_Transform(f.coord, 5179)) > 0.001
    )                                                                 AS drifted,
    coalesce(
        max(ST_Distance(f.coord_5179, ST_Transform(f.coord, 5179))), 0
    )                                                                 AS max_drift_m
FROM feature.features AS f
WHERE f.coord IS NOT NULL;
```

```sql
-- offender 목록: 임계(1mm) 초과 행만. clean이면 0 rows.
SELECT f.feature_id,
       ST_AsEWKT(f.coord_5179)                                 AS stored_5179,
       ST_AsEWKT(ST_Transform(f.coord, 5179))                  AS recomputed_5179,
       ST_Distance(f.coord_5179, ST_Transform(f.coord, 5179))  AS drift_m
FROM feature.features AS f
WHERE f.coord IS NOT NULL
  AND ST_Distance(f.coord_5179, ST_Transform(f.coord, 5179)) > 0.001
ORDER BY drift_m DESC
LIMIT 50;
```

- 임계 `0.001`(1mm)은 floating-point 잡음 아래, 실제 PROJ 변화 위다. 필요 시 조정한다.
- 대형 테이블에서 전수 스캔이 부담되면 `TABLESAMPLE SYSTEM (1)` 표본이나 최근 갱신분으로
  범위를 좁혀 우선 신호만 본다 — 단, **재계산/REINDEX 판정은 전수 요약**으로 확정한다.
- `drifted = 0` 이고 `max_drift_m ≈ 0` 이면 stale 없음 → §4 불필요.
- `drifted > 0` 이면 §4로 진행한다.

> 검증: 위 세 쿼리(요약·offender·버전)와 §4의 재계산/REINDEX는 `postgis/postgis:16-3.5`
> 컨테이너(PROJ 7.2.1)에서 실행 확인했다. fresh 데이터에서 `drifted=0`.

## 4. 재계산 + REINDEX (Recovery)

drift가 검출되면 (1) STORED 컬럼을 현재 PROJ로 재계산하고 (2) GiST index를 rebuild한다.
STORED generated column은 직접 UPDATE할 수 없으므로, **base 컬럼 `coord`를 건드려**
행을 다시 쓰면 generated `coord_5179`가 현재 PROJ로 재계산된다.

```sql
-- (1) 재계산: base 컬럼을 자기 자신으로 UPDATE → STORED generated 컬럼 재산출.
--     ⚠ 전체 UPDATE는 테이블 rewrite 수준의 WAL·bloat를 만든다. 대형 테이블은 반드시
--        keyset batch로 나눠 실행하고 사이사이 autovacuum/VACUUM을 태운다.
UPDATE feature.features
SET coord = coord
WHERE coord IS NOT NULL
  AND feature_id > :last_id           -- keyset 경계
ORDER BY feature_id
LIMIT :batch;                          -- 예: 5,000~20,000행/배치
```

배치 루프는 `feature_id` 오름차순 keyset으로 마지막 처리 id를 이어받아 반복한다
(paging 패턴은 [`../architecture/performance.md`](../architecture/performance.md) §6.1 참고).
`SET coord = coord`는 값이 바뀌지 않지만 새 row 버전을 만들어 generated 컬럼을 재산출한다
(검증 완료). row-level lock만 잡고 ACCESS EXCLUSIVE는 없다.

```sql
-- (2) REINDEX: coord_5179 GiST를 rebuild. CONCURRENTLY는 짧은 순간만 lock을 잡아
--     조회를 막지 않는다(autocommit / transaction 밖에서 실행).
REINDEX INDEX CONCURRENTLY feature.idx_features_coord_5179_gist;
```

- `REINDEX ... CONCURRENTLY`가 도중 실패하면 `_ccnew` suffix의 **INVALID** leftover index가
  남을 수 있다 — [`invalid-index-recovery.md`](./invalid-index-recovery.md)로 탐지·drop 후
  재실행한다.
- CONCURRENTLY를 쓸 수 없는 상황(예: 강한 정합 필요·짧은 유지보수 창)에서만 plain
  `REINDEX INDEX feature.idx_features_coord_5179_gist`(ACCESS EXCLUSIVE)를 쓰고, lock 획득/보유
  시간과 fence 범위를 기록한다(ADR-075 §6 수술형 DDL 규율).

### maintenance-window / lock 고려

- 재계산 UPDATE는 write fence가 필요 없지만, 진행 중 새 write는 이미 새 PROJ 값을 쓰므로
  batch가 지나간 구간과 아직 안 지난 구간이 잠시 공존한다. 조회 정합이 민감하면 재계산+REINDEX
  전체를 저트래픽 유지보수 창에서 수행하고, 완료 후 §3 요약으로 `drifted=0`을 확인한다.
- 순서는 **재계산 → REINDEX**. index를 먼저 rebuild하면 옛 값 그대로라 의미가 없다.
- 완료 후 반드시 §3 요약을 재실행해 `drifted=0`, `max_drift_m≈0`을 확인하고 배포 기록에 남긴다.

## 5. 관련 문서

- [ADR-075](../adr/075-cutover-and-ddl-discipline.md) — 보존 우선 cutover·DDL 규율(§6 수술형 DDL).
- [`../architecture/performance.md`](../architecture/performance.md) §7.1 — generated column 정책.
- [`../architecture/postgres-schema.md`](../architecture/postgres-schema.md) §4.1 — index 카탈로그.
- [`invalid-index-recovery.md`](./invalid-index-recovery.md) — CONCURRENTLY 실패 INVALID index 복구(T-VN-H05).
- alembic `0002_features_and_source_tables.py` — `coord_5179`·`idx_features_coord_5179_gist` 정본 정의.
