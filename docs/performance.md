# performance.md — 속도 최적화 설계

본 문서는 `python-krtour-map` v2의 성능 설계 지침이다. **설계 단계부터** 인덱스
사용, 공간 쿼리 패턴, bulk insert 한도, 캐싱 정책을 ADR과 함께 박아 둔다.
"나중에 튜닝" 금지.

## 1. 핵심 원칙

1. **모든 신규 쿼리 패턴은 EXPLAIN 친화적이어야 한다** — raw SQL `text()` +
   통합 테스트에서 인덱스 사용 검증 (ADR-004 + ADR-014).
2. **공간 쿼리 술어에서 좌표 형변환 금지** — 매 행 `ST_Transform`은 GIST
   인덱스 무효화. 입력 좌표는 CTE에서 1회 변환 (ADR-012).
3. **반경 검색은 EPSG:5179 (meter)** — `coord_5179` 컬럼에 적용 (ADR-012).
4. **시계열은 BRIN 인덱스** — `price_values`, `weather_values`, `source_records`,
   `import_jobs` 등.
5. **65,535 파라미터 한도** — `psycopg.copy_*` 우선, 안전 마진 30k (ADR-013).
6. **`pg_trgm.similarity_threshold`은 `SET LOCAL`만** — 전역 변경 금지.
7. **부분 인덱스 적극 활용** — `WHERE deleted_at IS NULL`, `WHERE status='active'`
   등 자주 쓰는 필터를 인덱스에 박는다.
8. **JSONB 인덱스는 generated column으로** — 자주 조회하는 JSONB key는 표현식
   인덱스 `((detail->>'key')::type)` 또는 generated column.

## 2. 공간 쿼리 표준 패턴

### 2.1 반경 검색 — 좋은 패턴

```sql
-- /features/nearby?lon=&lat=&radius_m=&kinds=&limit=
WITH input AS (
  SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 5179) AS pt
)
SELECT
  f.feature_id, f.name, f.kind, f.category,
  ST_X(f.coord) AS lon, ST_Y(f.coord) AS lat,
  ST_Distance(f.coord_5179, (SELECT pt FROM input)) AS dist_m,
  f.marker_icon, f.marker_color
FROM feature.features f
WHERE ST_DWithin(f.coord_5179, (SELECT pt FROM input), :radius_m)
  AND f.deleted_at IS NULL
  AND f.status = 'active'
  AND f.kind = ANY(:kinds)
ORDER BY f.coord_5179 <-> (SELECT pt FROM input)
LIMIT :limit;
```

**기대 EXPLAIN**:
```
Limit
  -> Sort
       -> Bitmap Heap Scan on features f
            Recheck Cond: (coord_5179 && ...)
            Filter: (status = 'active' AND deleted_at IS NULL AND kind = ANY(...))
            -> Bitmap Index Scan on idx_features_coord_5179_gist
```

### 2.2 반경 검색 — 나쁜 패턴 (절대 금지)

```sql
-- 매 행 ST_Transform → GIST 인덱스 못 탐
WHERE ST_DWithin(ST_Transform(f.coord_5179, 4326), :pt_4326, :radius_deg)
```

이런 코드가 PR에 들어오면 EXPLAIN 결과로 `Seq Scan`이 잡혀 CI block 된다.

### 2.3 in-bounds 검색

```sql
-- /features/in-bounds?min_lon=&min_lat=&max_lon=&max_lat=&kinds=
WITH bbox AS (
  SELECT ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326) AS geom
)
SELECT
  f.feature_id, f.name, ST_X(f.coord) AS lon, ST_Y(f.coord) AS lat,
  f.kind, f.category, f.marker_icon, f.marker_color
FROM feature.features f, bbox
WHERE f.coord && bbox.geom                     -- bbox && 인덱스 친화
  AND ST_Within(f.coord, bbox.geom)            -- 정밀 검증
  AND f.deleted_at IS NULL
  AND f.status = 'active'
  AND f.kind = ANY(:kinds)
LIMIT :limit;
```

`&&` 연산자는 GIST 인덱스를 직접 사용한다. `ST_Within`은 후속 정밀 검증.

### 2.4 zoom level별 클러스터링 (SPEC V8 J)

```sql
-- zoom <7 (sido), <11 (sigungu), <14 (eupmyeondong), else 개별 마커
-- 클러스터링 쿼리 — sigungu 예시
WITH bbox AS (
  SELECT ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326) AS geom
)
SELECT
  f.sigungu_code,
  COUNT(*) AS feature_count,
  ST_X(ST_Centroid(ST_Collect(f.coord))) AS lon,
  ST_Y(ST_Centroid(ST_Collect(f.coord))) AS lat
FROM feature.features f, bbox
WHERE f.coord && bbox.geom
  AND f.deleted_at IS NULL
  AND f.status = 'active'
  AND f.kind = ANY(:kinds)
  AND f.sigungu_code IS NOT NULL
GROUP BY f.sigungu_code;
```

`coord && bbox` 인덱스 사용 + `GROUP BY sigungu_code` (인덱스 `idx_features_sigungu`
보조). 큰 zoom out에서는 결과 row 수가 적어 빠르다.

### 2.5 LINESTRING/POLYGON 교차

```sql
-- route 교차 — 입력 polygon과 교차하는 route 찾기
SELECT f.feature_id, f.name
FROM feature.features f
WHERE f.kind = 'route'
  AND ST_Intersects(f.geom, ST_GeomFromGeoJSON(:input_polygon_geojson))
  AND f.deleted_at IS NULL
LIMIT :limit;
```

`idx_features_geom_gist`가 잡힌다.

## 3. pg_trgm 검색

### 3.1 부분 문자열 검색

```sql
-- 트랜잭션 내부에서만 SET LOCAL (전역 변경 금지)
BEGIN;
SET LOCAL pg_trgm.similarity_threshold = 0.3;

SELECT
  f.feature_id, f.name, f.kind, f.category,
  similarity(f.name, :q) AS score
FROM feature.features f
WHERE f.name % :q                              -- pg_trgm operator (GIN 인덱스 사용)
  AND f.deleted_at IS NULL
ORDER BY similarity(f.name, :q) DESC
LIMIT :limit;
COMMIT;
```

**기대 EXPLAIN**: `Bitmap Index Scan on idx_features_name_trgm`.

### 3.2 자동완성 (prefix)

```sql
-- 짧은 prefix는 trgm이 비효율 → 전용 인덱스 또는 ILIKE prefix
SELECT f.feature_id, f.name FROM feature.features f
WHERE f.name ILIKE :prefix || '%'
  AND f.deleted_at IS NULL
LIMIT 10;
```

prefix가 짧으면 `idx_features_name_text_pattern_ops` 추가 고려.

## 4. 시계열 BRIN 인덱스

### 4.1 사용 케이스

- `price_values.observed_at`
- `feature_weather_values.valid_at`, `collected_at`
- `source_records.imported_at`, `fetched_at`
- `import_jobs.created_at` (B-Tree)
- `ops.api_call_log.occurred_at`

### 4.2 BRIN이 효율적이려면

- **시간순 insert가 누적되어야 한다** — bulk upsert 시 `ORDER BY observed_at`.
- 무작위 insert 패턴은 BRIN 효율을 떨어뜨림.
- 시계열 read는 범위 (`WHERE valid_at BETWEEN ...`) 위주.

### 4.3 쿼리 예시

```sql
-- 특정 주유소의 최근 가격 추세
SELECT pv.observed_at, pv.item_key, pv.value
FROM feature.price_values pv
WHERE pv.feature_id = :feature_id
  AND pv.observed_at >= now() - interval '30 days'
ORDER BY pv.observed_at;

-- weather metric의 최신값
SELECT DISTINCT ON (metric_key)
  wv.metric_key, wv.value_number, wv.unit, wv.valid_at, wv.provider
FROM feature.feature_weather_values wv
WHERE wv.feature_id = :feature_id
  AND wv.valid_at >= now() - interval '24 hours'
ORDER BY wv.metric_key, wv.valid_at DESC NULLS LAST;
```

## 5. bulk insert / upsert

### 5.1 작은 batch (< 30k 파라미터)

```python
from sqlalchemy import text

await session.execute(
    text("""
        INSERT INTO feature.features (feature_id, kind, name, category, coord, address, status, created_at, updated_at)
        VALUES (:feature_id, :kind, :name, :category,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                CAST(:address AS jsonb), :status, now(), now())
        ON CONFLICT (feature_id) DO UPDATE SET
          name = EXCLUDED.name,
          category = EXCLUDED.category,
          coord = EXCLUDED.coord,
          address = EXCLUDED.address,
          updated_at = now()
    """),
    rows,
)
```

`executemany` 형태로 처리된다.

### 5.2 큰 batch (>= 30k 파라미터)

```python
import psycopg

async with await psycopg.AsyncConnection.connect(pg_dsn) as conn:
    async with conn.cursor() as cur:
        async with cur.copy(
            "COPY feature.price_values (feature_id, item_key, observed_at, value, currency, payload_hash) FROM STDIN"
        ) as copy:
            async for row in row_iter_sorted_by_observed_at:
                await copy.write_row(row)
    await conn.commit()
```

**주의**:
- COPY는 `ON CONFLICT` 미지원. 중복 가능성 있으면 staging 테이블에 COPY →
  INSERT SELECT + ON CONFLICT로 swap.
- COPY 전에 `observed_at`로 정렬해 BRIN 효율 유지.
- `psycopg.AsyncConnection`은 SQLAlchemy session과 별도로 관리한다.
- 대용량 트랜잭션은 `SET LOCAL synchronous_commit = OFF` 고려 (운영 정책 결정).

### 5.3 SHP / GeoJSON (krheritage area boundary 등)

```python
from osgeo import gdal

# PG_USE_COPY=YES로 COPY 사용
gdal.VectorTranslate(
    "PG:" + pg_dsn,
    "/data/krheritage/gis_spca.shp",
    options=[
        "-f", "PostgreSQL",
        "-nln", "staging.krheritage_spca_raw",
        "-t_srs", "EPSG:4326",
        "-lco", "GEOMETRY_NAME=geom",
        "-lco", "PG_USE_COPY=YES",
        "-lco", "FID=heritage_id",
        "-overwrite",
    ],
)
```

CP949 SHP는 `open_options=["ENCODING=CP949"]` 명시 (kraddr-geo ADR-005 동일).

## 6. 부분 인덱스

자주 쓰는 필터를 인덱스에 박으면 인덱스 크기 + 검색 속도 모두 개선.

```sql
-- 활성 feature만 검색
CREATE INDEX idx_features_kind_category
  ON feature.features (kind, category)
  WHERE deleted_at IS NULL;

-- 진행중 행사
CREATE INDEX idx_features_event_end
  ON feature.features (((detail->>'ends_on')::date))
  WHERE kind='event' AND deleted_at IS NULL;

-- 유효 공지
CREATE INDEX idx_features_notice_valid
  ON feature.features (((detail->>'valid_end_time')::timestamptz))
  WHERE kind='notice' AND deleted_at IS NULL;

-- 실행중 job (heartbeat 만료 검사)
CREATE INDEX idx_import_jobs_heartbeat
  ON ops.import_jobs (heartbeat_at)
  WHERE state='running';

-- pending dedup
CREATE INDEX idx_dedup_pending_score
  ON ops.dedup_review_queue (total_score DESC)
  WHERE status='pending';
```

## 7. JSONB 인덱싱

### 7.1 자주 조회하는 필드는 generated column으로

```sql
ALTER TABLE feature.features
  ADD COLUMN bjd_code_cached CHAR(10)
  GENERATED ALWAYS AS (address->>'legal_dong_code') STORED;

CREATE INDEX idx_features_bjd_cached ON feature.features (bjd_code_cached);
```

이미 `legal_dong_code` 컬럼이 별도로 있으므로 위는 예시. detail JSON의 자주
쓰는 필드(`detail->>'place_kind'`)도 동일 패턴 가능.

### 7.2 GIN on JSONB

```sql
-- detail 자유 검색 (admin 디버그 페이지에서 사용)
CREATE INDEX idx_features_detail_gin
  ON feature.features USING GIN (detail jsonb_path_ops);
```

비용이 크므로 admin 검색이 자주 일어나는 경우에만.

## 8. ORDER BY + LIMIT 최적화

- `ORDER BY ... LIMIT n`은 인덱스를 그대로 탈 수 있게 컬럼 순서 맞추기.
- `idx_weather_feature_metric_time (feature_id, metric_key, valid_at DESC NULLS
  LAST)` 같은 복합 인덱스로 "feature별 metric별 최신값 N개"를 인덱스만으로
  scan.

```sql
-- 인덱스만으로 scan (Index Only Scan)
SELECT feature_id, metric_key, valid_at, value_number
FROM feature.feature_weather_values
WHERE feature_id = :fid AND metric_key = 'T1H'
ORDER BY valid_at DESC NULLS LAST
LIMIT 1;
```

## 9. 캐싱 정책 (Postgres 외)

### 9.1 라이브러리 레벨 캐시 — 사용하지 않는다

- 라이브러리는 stateless. in-memory 캐시 두지 않는다 (lifespan 복원 복잡, 다중
  워커 일관성 깨짐). 정식 결정은 **ADR-030** (accepted) — `functools.cache`
  한정 narrow 예외 (PlaceCategoryCode 카탈로그, `pyproj.Transformer` singleton).
  `import-linter` 계약으로 `cachetools` / `async_lru` / `aiocache` /
  `diskcache` 의존 차단.
- 호출자(TripMate)가 필요 시 자체 캐시(Redis/in-process LRU). 단 캐시 무효화
  책임은 호출자.

### 9.2 PostgreSQL 자체 캐시

- `effective_cache_size = 2GB` (Odroid 기본) — SPEC V8 v8_0 참고.
- 자주 쓰는 인덱스는 OS cache에 상주.
- `pg_prewarm` extension으로 부팅 후 warm-up 고려 (운영 결정 — **T-102**,
  §9.5).

### 9.3 PostGIS MV (Materialized View, T-101)

자주 쓰는 join 결과(예: `feature + place_detail + opening_hours` 또는 7개
detail kind union)는 MV로. `REFRESH MATERIALIZED VIEW CONCURRENTLY`로 lock
없이 갱신.

**v2 1차 범위에서는 미사용** — 실 부하 보고 결정 (T-101 보류 항목).

**도입 시 장점**:
- viewport/`features_in_bounds` 쿼리에서 7-way JOIN이 단일 table scan으로
  단순화 → P99 latency 감소 + EXPLAIN plan 안정화 (JOIN order optimizer
  의존 제거).
- GiST(`coord_5179`) + detail 컬럼 필터를 단일 plan으로 묶을 수 있어 zoom
  레벨 클러스터 응답 시간 단축 (디버그 UI + TripMate 사용자 UI 모두 이득).
- detail kind별 partial MV (`mv_features_place`, `mv_features_event` 등)로
  cold path 격리 가능. zoom 8 미만에서 자주 쓰는 컬럼만 추출하면 메모리도
  절약.

**도입 조건 (모두 충족 시)**:
- read >> write 비율이 실측으로 확인 (Sprint 5 이후 24h 운영 로그 기준).
- `REFRESH CONCURRENTLY` lag (수십 초~수 분) 허용 가능.
- 디스크 사용량 ×2 수용 (Odroid SSD 여유 확인).
- 일관성 게이트 (ADR-033 Phase 2)가 이미 swap 직전에 적용되어 있을 것 —
  비정상 데이터가 MV로 새는 것을 차단해야 함.

**도입 시 부작용**:
- `REFRESH CONCURRENTLY`는 UNIQUE 인덱스 필수 → MV 정의에 `feature_id`
  UNIQUE 보장 필요.
- DDL 변경(컬럼 추가/타입 변경)이 무거워짐 — alembic revision에 MV `DROP +
  CREATE` 동반.
- MV가 stale인 상태에서 디버그 UI/TripMate가 조회하면 "유저는 갱신했는데
  지도엔 안 보임" 혼동 — `mv_last_refreshed_at` 컬럼 노출 + `/health`에
  포함 권장.

**도입 절차 (예상)**:
1. 하나의 hot path만 시범 도입 (예: `mv_features_place_with_detail`).
2. 1주일 운영 + EXPLAIN diff 비교 → 회귀 추적.
3. 다른 kind 확장 여부 판단.
4. ADR 신설 — `feature_*` MV 카탈로그 + refresh schedule + DDL 정책.

### 9.4 별도 streaming ETL (Kafka/Redpanda) — T-103

**v2 1차 범위에서는 미사용** — 본 라이브러리 자체가 streaming consumer를
의존할 가치 없음 (함수 라이브러리, ADR-003).

**도입이 의미 있는 시나리오**:
- KNPS 산불경보 / 도로공사 사고 / KMA 특보처럼 *초 단위 latency*가 필요한
  notice 도메인.
- 멀티 컨슈머 fan-out (ETL + TripMate 알림 + 분석)이 분 단위 cron으로 처리
  불가한 경우.
- Provider가 webhook/push를 지원해서 폴링 → push 전환이 가능한 경우.

**도입 시 장점**:
- 분 단위 cron보다 빠른 응답 (수 초 이내).
- offset 기반 replay/backpressure — 다운스트림 일시 중단 시 재처리 안전.
- 다중 컨슈머가 동일 stream을 공유 (notice가 ETL 적재 + TripMate 알림 +
  분석으로 동시에 분기).

**도입 시 부작용 / 진입 비용**:
- Kafka/Redpanda 클러스터 운영 (broker, ZK or KRaft, monitoring) — Odroid
  단일 노드에서 비현실적, TripMate가 별도 인프라로 운영해야 함.
- exactly-once vs at-least-once trade-off, idempotency 키 설계.
- 디버깅이 Dagster batch보다 어려움 (consumer lag, offset 추적).

**krtour-map 위치**:
- ADR-045 이후 provider ingestion consumer를 도입한다면 krtour-map 독립 프로그램
  경계 안(`packages/krtour-map-dagster` 또는 별도 worker)에서 소유한다. TripMate
  `apps/etl`에 consumer를 두지 않는다.
- 메인 라이브러리(`krtour.map`)에 Kafka client 의존 추가 금지
  (`pyproject.toml` import-linter 계약). 필요한 경우 별도 worker/Dagster 패키지와
  ADR로 다룬다.
- schema (Avro/Protobuf if used)는 `dto/` Pydantic 모델과 동기 유지하되,
  TripMate는 OpenAPI consumer일 뿐 Python DTO를 직접 import하지 않는다.

**판단 권고**: 특정 provider가 진짜 초 단위 latency를 요구한다는 증거가
잡힐 때만 ADR 작성 + krtour-map 운영 인프라 추가. 추측만으로 도입 금지.

### 9.5 pg_prewarm 부팅 후 warm-up — T-102

**v2 1차 범위에서는 미사용** — 운영 결정 (T-102 보류 항목).

**도입 시 장점**:
- 컨테이너 재시작/장애 복구 직후 cold-start cliff 제거. 첫 1~2분 P99
  outlier 사라짐 → TripMate가 부팅 직후 호출해도 정상 SLO.
- `feature_coord_5179_gist`, `feature_kind_idx`, `ops.import_jobs`,
  `feature_place_details` 같은 핫 path 인덱스/테이블을 부팅 시
  `shared_buffers`에 강제 로드.
- `pg_prewarm` extension은 PostgreSQL 표준 (contrib), 추가 클러스터 인프라
  불필요.

**도입 조건 (모두 충족 시)**:
- 운영 환경에 명시적 SLO가 있을 것 (예: P99 < 100ms for `features_in_bounds`).
- 재배포/재시작 빈도가 높을 것 (CI/CD 일/주 단위).
- dataset이 RAM에 충분히 fit (`shared_buffers` 충분 — Odroid 기본 512MB는
  핫 데이터 일부만 가능).

**도입 시 부작용**:
- 부팅 시간 늘어남 (10만 row 인덱스 1개당 1~5초 + 인덱스 수 만큼). 헬스
  체크 그레이스 기간 확장 필요.
- `shared_buffers`가 작으면 evict 압력 → 의미 없음. `shared_buffers` 산정
  먼저 (RAM의 25% 권장).
- prewarm 자체가 I/O 폭주를 유발 — Odroid 단일 SSD에서는 부팅 직후 다른
  서비스에 영향. `pg_prewarm.autoprewarm = on`으로 background 모드 권장.

**도입 절차 (예상)**:
1. `CREATE EXTENSION IF NOT EXISTS pg_prewarm SCHEMA x_extension;` (ADR-008
   schema 정책).
2. `shared_buffers`를 RAM의 25%로 조정 + `effective_cache_size` 75%.
3. `autoprewarm_dump_dir` 설정 → 종료 시점에 핫 buffer 목록 dump.
4. 부팅 시 dump 자동 read → 동일 buffer 채움.
5. `/health` 엔드포인트에 `prewarm_completed: bool` 포함.

**ROI 평가**: 단순 운영(monthly restart)에서는 ROI 낮음. CI/CD 일 단위
배포 + SLO 운영 환경에서만 가치.

## 10. 통합 테스트로 인덱스 사용 검증

모든 raw SQL은 통합 테스트에서 EXPLAIN 결과를 assert.

```python
@pytest.mark.integration
async def test_features_nearby_uses_gist_index(session, sample_features):
    result = await session.execute(
        text("EXPLAIN (FORMAT JSON) " + features_nearby_sql),
        {"lon": 127.0, "lat": 37.5, "radius_m": 1000, "kinds": ["place"], "limit": 50},
    )
    plan = result.scalar_one()[0]["Plan"]
    assert plan["Node Type"] in ("Limit", "Sort", "Bitmap Heap Scan")
    # 인덱스 노드 찾기
    nodes = _collect_node_types(plan)
    assert any("Index" in n for n in nodes), f"expected index scan, got {nodes}"
    assert not any(n == "Seq Scan" for n in nodes), f"seq scan detected: {nodes}"
```

이런 테스트가 모든 hot path 쿼리에 1개 이상 있어야 한다 (`docs/test-strategy.md`).

## 11. 회귀 추적

- 모든 raw SQL은 PR에 EXPLAIN 결과 첨부.
- `infra/*_repo.py` 변경 시 직전 EXPLAIN과 diff (수동).
- 부하 테스트는 nightly CI에서 `pytest -m slow`로 분리.

## 12. 측정 인프라

- PostgreSQL: `pg_stat_statements` extension 활성화.
- 로그: `log_min_duration_statement = 1000` (1초 이상 쿼리 로그).
- 슬로우 쿼리는 Grafana Loki에서 LogQL로 추적 (TripMate 측 wiring).

## 13. 안티패턴 모음 (PR 차단 사유)

| 안티패턴 | 대안 |
|---------|------|
| `ST_Transform(t.coord_5179, 4326)` in WHERE | CTE에서 입력만 1회 변환 |
| `ST_DWithin(t.coord::geography, ..., :rad_m)` | `coord_5179` 컬럼 사용 |
| SQLAlchemy ORM `query.filter()` | `infra/*_repo.py`에 raw SQL `text()` |
| `INSERT ... VALUES (?)` × 50k rows | `psycopg.copy_*` |
| `WHERE jsonb_extract_path(...) = ...` | generated column or `@>` operator |
| 전역 `pg_trgm.similarity_threshold` SET | 트랜잭션 `SET LOCAL` |
| `coord && ST_Buffer(point, deg)` | `coord_5179 && ST_Expand(point_5179, m)` |
| Seq Scan on features (>10만 행) | 인덱스 설계 또는 partial index 추가 |
| BRIN on randomly-inserted column | B-Tree 또는 시간순 정렬 보장 |
| `LIMIT n` + ORDER without matching index | 복합 인덱스 추가 |

## 14. 운영 체크리스트 (Sprint 5 진입 전)

- [ ] 모든 hot path SQL에 EXPLAIN 통합 테스트
- [ ] `pg_stat_statements` 활성화 및 Grafana 패널
- [ ] `log_min_duration_statement` 설정
- [ ] BRIN 인덱스 효율 측정 (1주 운영 후)
- [ ] 인덱스 hit ratio 95%+ 확인
- [ ] 부분 인덱스 vs 전체 인덱스 비교 (디스크 사용량)
- [ ] `VACUUM ANALYZE` cron + autovacuum 튜닝
