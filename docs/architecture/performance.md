# performance.md — 속도 최적화 설계

본 문서는 `kor-travel-map` v2의 성능 설계 지침이다. **설계 단계부터** 인덱스
사용, 공간 쿼리 패턴, bulk insert 한도, 캐싱 정책을 ADR과 함께 박아 둔다.
"나중에 튜닝" 금지.

## 1. 핵심 원칙

1. **모든 신규 쿼리 패턴은 EXPLAIN 친화적이어야 한다** — raw SQL `text()` +
   통합 테스트에서 인덱스 사용 검증 (ADR-004 + ADR-014).
2. **공간 쿼리 술어에서 좌표 형변환 금지** — 매 행 `ST_Transform`은 GIST
   인덱스 무효화. 입력 좌표는 CTE에서 1회 변환 (ADR-012).
3. **반경 검색은 EPSG:5179 (meter)** — `coord_5179` 컬럼에 적용 (ADR-012).
4. **시계열 access path는 실제 read를 따른다** — immutable weather/price fact는 canonical
   identity와 newest rank B-tree, normal current read는 summary fact pointer를 쓴다. 무측정 BRIN을
   관성으로 두지 않는다.
5. **65,535 파라미터 한도** — `psycopg.copy_*` 우선, 안전 마진 30k (ADR-013).
6. **`pg_trgm.similarity_threshold`은 `SET LOCAL`만** — 전역 변경 금지.
7. **부분 인덱스 적극 활용** — `WHERE deleted_at IS NULL`, `WHERE status='active'`
   등 자주 쓰는 필터를 인덱스에 박는다.
8. **JSONB 인덱스는 generated column으로** — 자주 조회하는 JSONB key는 표현식
   인덱스 `((payload->>'key')::type)` 또는 generated column. kind별 필드는
   subtype의 typed 컬럼이라 애초에 이 패턴이 필요 없다 (ADR-086).

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

관리 Feature 지도는 zoom 13 이하에서 위 region rollup만 조회한다. 개별 feature로
전환하는 고zoom에서는 현재 화면을 Web Mercator tile로 나누되 다음 규칙을 지킨다.

- 카메라 zoom에 맞춰 최대 zoom 15 tile을 사용해 고zoom 요청이 고정 zoom 12의 넓은
  후보 집합을 반복 읽지 않게 한다.
- 한 화면의 tile fan-out은 최대 8개다. 그보다 많으면 한 단계씩 낮추고, 비정상적으로
  큰 bbox는 single-bbox 요청으로 되돌아가 API 4-core를 병렬 요청으로 포화시키지 않는다.
- 정상 tile 경로의 query key는 실제 tile key 집합으로만 정한다. 같은 tile 안의 작은
  pan은 outer merge와 GeoJSON `setData`를 다시 수행하지 않는다.
- 기본 `weather`/`notice`처럼 point만 선택했으면 `include_geometry=false`다. `route`, 또는
  표시 zoom 이상의 `area`, 전체 kind 선택일 때만 geometry를 요청한다.

MapLibre의 DOM marker 갱신은 해당 GeoJSON source가 완전히 적재된 `sourcedata`와
`moveend`에서만 수행한다. VWorld raster source의 tile 이벤트와 중복 `idle`/`zoomend`
구독은 marker 전체 순회를 유발하므로 사용하지 않으며, tile 경계에서 중복 반환된
feature/cluster는 겹침 계산 전에 식별자로 제거한다.

큐레이션 지도는 viewport를 power-of-two grid에 맞춘 padded bbox로 정규화해 query key와
실제 요청에 함께 쓴다. 작은 pan은 같은 cache를 재사용하고 새 응답 중에도 이전 marker를
유지한다. padding 밖으로 이동하면 새 bbox를 요청하므로 화면 밖의 stale marker만 남는
오류는 허용하지 않는다.

### 2.5 LINESTRING/POLYGON 교차

```sql
-- route 교차 — 입력 polygon과 교차하는 route 찾기
SELECT f.feature_id, f.name
FROM feature.feature_routes r
JOIN feature.features f ON f.feature_id = r.feature_id
WHERE ST_Intersects(r.geom, ST_GeomFromGeoJSON(:input_polygon_geojson))
  AND f.deleted_at IS NULL
LIMIT :limit;
```

`idx_feature_routes_geom_gist`가 잡힌다. area는 `feature.feature_areas`로 같은
모양이다. subtype 테이블 자체가 kind로 갈리므로 `kind='route'` 술어는 필요 없다.

**공간 술어는 조립 뷰를 쓰지 않는다** (ADR-086). `feature.features_detailed`의
`geom`은 `COALESCE(routes.geom, areas.geom)` 산출 컬럼이라 인덱스가 없고, 그대로
술어에 넣으면 features 73만 행 seq scan이 된다. 뷰는 응답 조립용이고, 술어는 GiST가
붙어 있는 subtype을 직접 참조한다.

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

## 4. immutable 시계열 fact와 current projection

### 4.1 사용 케이스

- `feature_price_values(feature_id, observed_at DESC, known_at DESC, provider_dataset_id, price_domain, product_key)`
- `feature_weather_values(feature_id, target_at DESC, known_at DESC)`
- `current_{weather,price}_summary`의 selected immutable fact pointer
- `source_records.imported_at`, `fetched_at`
- `import_jobs.created_at` (B-Tree)
- `ops.api_call_log.occurred_at`

### 4.2 BRIN이 효율적이려면

- current projection은 각 projection-kind advisory lock을 desired set 계산 전에 취한다.
  새 writer가 commit한 winner를 먼저 계산한 오래된 writer가 되돌릴 수 없다.
- history/timeline은 fact rank index로 `(feature_id, temporal order)`를 제한한다. normal
  card/map/bbox는 ranked raw fact를 feature마다 반복하지 않고 current summary set join을 쓴다.
- source revision은 immutable fact identity의 일부이므로 같은 payload 재수집과 correction은
  upsert가 아니라 source record/fact append 또는 no-op으로 구분한다.

### 4.3 쿼리 예시

```sql
-- 특정 주유소의 최근 가격 추세
SELECT pv.observed_at, pv.product_key, pv.value_number, pv.unit
FROM feature.feature_price_values pv
WHERE pv.feature_id = :feature_id
  AND pv.observed_at >= now() - interval '30 days'
ORDER BY pv.observed_at;

-- normal weather card: value를 복제하지 않는 summary pointer를 fact에 set join
SELECT wv.metric_key, wv.value_number, wv.unit, wv.target_at
FROM feature.current_weather_summary cws
JOIN feature.feature_weather_values wv
  ON wv.weather_value_key = cws.weather_value_key
WHERE cws.feature_id = :feature_id
  AND cws.refresh_after > clock_timestamp();
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
            "COPY feature.feature_price_values (price_value_key, feature_id, provider_dataset_id, price_domain, product_key, observed_at, known_at, value_number, unit, source_entity_key, source_record_key) FROM STDIN"
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

CP949 SHP는 `open_options=["ENCODING=CP949"]` 명시 (kor-travel-geo ADR-005 동일).

## 6. 부분 인덱스

자주 쓰는 필터를 인덱스에 박으면 인덱스 크기 + 검색 속도 모두 개선.

```sql
-- 활성 feature만 검색
CREATE INDEX idx_features_kind_category
  ON feature.features (kind, category)
  WHERE deleted_at IS NULL;

-- 진행중 행사 (subtype typed 컬럼 — kind 술어가 테이블로 대체돼 부분 조건이 없다)
CREATE INDEX idx_feature_events_period
  ON feature.feature_events (starts_on, ends_on);

-- 유효 공지
CREATE INDEX idx_feature_notices_validity
  ON feature.feature_notices (valid_end_time, valid_start_time);

-- 실행중 job (heartbeat 만료 검사)
CREATE INDEX idx_import_jobs_heartbeat
  ON ops.import_jobs (heartbeat_at)
  WHERE state='running';

-- batch DAG root/child 조회
CREATE INDEX idx_import_jobs_load_batch_created
  ON ops.import_jobs (load_batch_id, created_at DESC, job_id DESC)
  WHERE load_batch_id IS NOT NULL;

CREATE INDEX idx_import_jobs_parent_created
  ON ops.import_jobs (parent_job_id, created_at DESC, job_id DESC)
  WHERE parent_job_id IS NOT NULL;

-- pending dedup
CREATE INDEX idx_dedup_pending_score
  ON ops.dedup_review_queue (total_score DESC)
  WHERE status='pending';

-- dedup refresh 입력 keyset (T-RV-16)
CREATE INDEX idx_features_dedup_refresh_keyset
  ON feature.features (updated_at DESC, feature_id DESC)
  WHERE deleted_at IS NULL AND status='active' AND coord IS NOT NULL;
```

### 6.1 dedup refresh keyset

T-RV-16 이전 dedup refresh 입력 조회는 `DISTINCT ON (feature_id)` 뒤
`ORDER BY feature_id ... LIMIT :limit` 구조라, 같은 provider/dataset scope를 limit으로
반복 실행하면 사전식 앞부분만 계속 재조회할 수 있었다. 이후 구조는
`updated_at DESC, feature_id DESC` 정렬과 `(cursor_updated_at, cursor_feature_id)`
row-tuple cursor를 사용한다.

개선 효과:
- **진행성**: 다음 페이지 조건이 `(updated_at, feature_id) < (:cursor_updated_at,
  :cursor_feature_id)`라 같은 앞부분 반복 스캔을 피한다.
- **master 선정 신호 보존**: `updated_at`과 `coord_precision_digits`를 함께 읽어
  ADR-016 master 선정/운영 검토가 같은 입력을 쓴다.
- **인덱스 보조**: `idx_features_dedup_refresh_keyset` partial index가 active,
  좌표 보유 feature만 keyset 순서로 훑도록 돕는다.

### 6.2 POI target entity version과 link/delete 잠금

Alembic 0058의 `ops.poi_cache_targets.lock_version`은 인덱스에 넣지 않는다. DELETE는 active
natural key partial unique index로 row를 찾고 `FOR UPDATE` 한 뒤 heap의 UUID+version을 비교한다.
version을 인덱싱하면 모든 target UPDATE가 불필요한 index churn을 만들고 HOT update 기회를 줄인다.

target UPDATE는 row-level version trigger와 `dataset_projection` topic row lock을 함께 사용하므로 같은
topic writer가 많은 경우 직렬화 비용이 생긴다. 이는 stale mutation 방지와 causal live receipt를 위한
의도된 비용이다. 특히 0055의 statement trigger는 `ops.data_integrity_violations` write도 같은
`dataset_projection` revision row에 결박하므로, 그 테이블을 쓰는 장기 ETL transaction이 열려 있는 동안
admin POI mutation latency는 해당 writer의 commit까지 직렬화되어 지연될 수 있다. link snapshot sync는 모든 active parent UUID를 정렬해 `FOR KEY SHARE`로 먼저
잠그고, 그 뒤 link를 `(target_id, feature_id)` 순서로 비활성화/upsert한다. 각 parent lock은 target
DELETE의 `FOR UPDATE`와 직렬화되지만 일반 active parent read는 막지 않는다. multi-target sync와
delete 모두 parent target → feature link 순서를 지켜 교착을 피한다.

## 7. JSONB 인덱싱

### 7.1 자주 조회하는 필드는 generated column으로

> **STORED generated 컬럼과 PROJ 버전**: `coord_5179`처럼 `ST_Transform`으로 만든 STORED
> generated 컬럼 값은 PROJ 버전에 종속한다. PostGIS/PROJ image tag 상향 시 drift 검사·재계산·
> REINDEX 절차는 [`../runbooks/coord-5179-proj-pin.md`](../runbooks/coord-5179-proj-pin.md)(T-VN-H04).

```sql
ALTER TABLE feature.features
  ADD COLUMN bjd_code_cached CHAR(10)
  GENERATED ALWAYS AS (address->>'legal_dong_code') STORED;

CREATE INDEX idx_features_bjd_cached ON feature.features (bjd_code_cached);
```

이미 `legal_dong_code` 컬럼이 별도로 있으므로 위는 예시. kind별 필드
(`place_kind` 등)는 subtype의 typed 컬럼이라 이 패턴 자체가 필요 없고, 남은 JSONB는
subtype의 `payload`뿐이다 (ADR-086).

### 7.2 GIN on JSONB

```sql
-- provider 원문 payload 자유 검색 (admin 디버그 페이지에서 사용)
CREATE INDEX idx_feature_places_payload_gin
  ON feature.feature_places USING GIN (payload jsonb_path_ops);
```

비용이 크므로 admin 검색이 자주 일어나는 경우에만. 조립 뷰
(`feature.features_detailed`)의 `detail`은 산출 컬럼이라 인덱스를 걸 수 없다 —
인덱스는 항상 subtype 실컬럼에 건다.

## 8. ORDER BY + LIMIT 최적화

- `ORDER BY ... LIMIT n`은 인덱스를 그대로 탈 수 있게 컬럼 순서 맞추기.
- `idx_weather_values_feature_target_known`과
  `idx_price_values_feature_observed_identity`는 raw timeline/snapshot candidate를 정렬한다.
  normal current card는 summary pointer를 fact에 join하므로 feature별 winner scan을 반복하지 않는다.

```sql
-- 인덱스만으로 scan (Index Only Scan)
SELECT wv.feature_id, wv.metric_key, wv.target_at, wv.value_number
FROM feature.current_weather_summary cws
JOIN feature.feature_weather_values wv
  ON wv.weather_value_key = cws.weather_value_key
WHERE cws.feature_id = :fid
  AND cws.refresh_after > clock_timestamp();
```

### 8.3 vNext 3단 성능·DDL gate (ADR-075 D-12-4) — **본 절이 정본**

성능 최적화는 도입 전 budget과 재현 fixture를 고정하고 다음 세 계층으로 검증한다. T-VN-21이
이 세 계층을 CI/release 절차에 연결했다. 각 계층의 **무엇이·어디서·어떻게** 실행되는지가 아래
정본이다.

#### Tier 1 — 매 PR (CI ``integration`` job에서 상시)

`tests/integration/test_perf_gate_tier1.py` (`@pytest.mark.perf_gate`)가 testcontainers
PostGIS에서 다음 셋을 검사한다. 기존 integration job(`pytest tests/integration`)이 그대로
실행하므로 `main` 대상 모든 PR에서 돈다.

1. **planner-default EXPLAIN smoke**: `tests/integration/perf_gate.py`의 `HOT_QUERIES`
   registry(public bbox/in-bounds·nearby·search·detail·batch·category counts·cluster
   rollup 3종)를 **`enable_seqscan`을 건드리지 않고** EXPLAIN해 `feature.features`
   base-table `Seq Scan`이 없고 기대 index를 타는지 확인한다. `enable_seqscan=off` 결과는
   회귀 감시(=index 적격성 확인)에만 쓰고 **채택 근거로 삼지 않는다**.
2. **query 수 ≠ batch item 수 가드**: public batch read를 item 50개·100개로 호출해 발생 SQL
   statement 수가 item 수에 비례하지 않고 1건으로 일정한지 확인한다(N+1 회귀 차단).
3. **response-shape 회귀**: hot query 결과 컬럼 집합을 frozen snapshot과 비교해 우발적 필드
   추가/삭제를 잡는다(OpenAPI drift gate와 별개 — SQL 컬럼 계약 회귀).

**hot query 추가 절차**: `perf_gate.HOT_QUERIES`에 `HotQuery(name, sql, params,
expected_indexes, no_seq_scan_on=…)` 한 줄을 더한다. 정본 SQL 상수는 `feature_repo`에서
**읽기만** 하고 재구현하지 않는다. small-fixture에서 planner가 index를 선호하도록
`seed_hot_query_features`가 features + primary source lineage를 3,200행 규모로 seed·ANALYZE한다.

> **집계 hot query 주의**: category counts처럼 활성 전 행을 훑는 full aggregate는, 공개 notice
> 감산 필터의 `source_links` NOT EXISTS anti-join이 populated 여야 index를 탄다. 그래서 seed가
> source lineage를 함께 채운다. `feature_price_values`/`feature_weather_values`는 tier-1 seed에
> 넣지 않으므로 bbox의 price/weather LATERAL은 빈 aux 테이블을 seq-scan한다(`features` 아님) —
> 이는 fixture-size 산물이고 aux 테이블 index 실효는 tier-2 실분포에서 잰다.

#### Tier 2 — release/cutover (수동, **CI 아님**)

`scripts/perf_tier2_release_harness.py`가 100만+ 실분포 fixture에서 대표 viewport를
`EXPLAIN (ANALYZE, BUFFERS)`로 재고 n150 기준 p50/p95, shared read blocks p95, 응답 bytes를
JSON으로 기록한다. **CI에서 절대 돌리지 않는다**(대용량 fixture는 CI 시간/자원 초과).

- 대표 viewport: 서울 밀집 in-bounds, 전국 low-zoom cluster, 100km nearby, 상용 검색어 search,
  200건 batch.
- 실행: `KOR_TRAVEL_MAP_PG_DSN=… python scripts/perf_tier2_release_harness.py --rows 1000000
  --iterations 30`(alembic head 적용된 빈 DB에). 이미 적재된 DB는 `--skip-seed`.
- `--skip-seed`는 `feature.public_features`에서 non-notice `feature_id` 200개를 정렬해
  실제 batch 파라미터로 사용한다. notice는 공개 list가 추가 lifecycle 감산을 적용하므로
  batch 후보에서 제외해 selector와 응답 visibility 의미를 일치시킨다. 후보가 200건
  미만이거나 대표 viewport가 각 최소 cardinality(일반 1행, batch 200행)를 만족하지
  못하면 성공 JSON을 출력하지 않고 종료 코드 2로 실패한다.
- 각 viewport는 terminal `LIMIT` 전 별도 count의 `matched_rows`와 실제 응답의
  `returned_rows`/`minimum_returned_rows`를 기록해 truncation을 보존한다. EXPLAIN
  최상위 Plan 행 수는 LIMIT 적용 뒤 `returned_rows`와 같아야 한다. count는 p95 측정
  loop 밖에서 한 번만 실행한다.
  `shared_read_blocks_p95`는 child 누적값을 재귀 합산하지 않고 최상위 Plan의
  query 전체 누적값만 사용한다.
- percentile 표본은 오름차순 정렬하고 nearest-rank를 사용한다. 표본 수가 `n`이고
  percentile 비율이 `p`이면 1-based rank는 `ceil(p × n)`, 0-based index는
  `ceil(p × n) - 1`이다. 보간하지 않으며 실행시간 p50·p95와 shared read blocks p95를
  모두 같은 helper로 계산한다. 따라서 값이 `1..n`인 p95 표본은 `n=1/20/30/100`에서
  각각 index `0/18/28/94`, 값 `1/19/29/95`를 선택한다.
- 결과는 release 리포트(`docs/reports/`)에 첨부하고, budget 초과 viewport는 index/쿼리 재설계
  근거로 쓴다.

#### Tier 3 — index/DDL 변경 PR (정책 + helper, 리뷰 enforce)

index/DDL을 바꾸는 PR은 변경 **전후 write 비용·index 크기**(및 필요 시 WAL·lock 획득/보유
시간)를 측정해 PR에 첨부해야 한다. 하드 CI gate로 만들 수 없다(변경별 index가 달라 generic
게이트 불가) — **리뷰가 첨부 여부를 확인**한다.

- 재사용 helper: `perf_gate.measure_index_write_cost(session, label=…, insert_sql=…,
  row_batches=…, index_relation=…)`가 write 소요 시간과 `pg_relation_size(index)`를 반환한다.
  index 생성/삭제(migration)는 호출자가 하고, helper는 순수 측정만 한다.
- GiST/BRIN은 실제 predicate·시간 정렬을 지원할 때만 채택한다. GiST 6→partial 정리의 write
  **~1.6× 개선** 실측이 선례다(§13, T-VN-18 계열이 이 helper로 before/after를 첨부한다).
- concurrent build 실패 뒤 INVALID index가 0건인지 확인한다([`../runbooks/invalid-index-recovery.md`](../runbooks/invalid-index-recovery.md), T-VN-H05). dedup과
  UNIQUE 사이 writer race가 있는 0060은 성능보다 원자성을 우선해 table writer lock 아래
  non-concurrent build를 사용하므로 lock 대기·보유 시간과 fence 범위를 대신 기록한다.

MVT, 범용 batch, cursor HMAC, weather partition/hypertable, 물리 listener, 대규모 fixture 주기는
T-VN-51~56에서 먼저 채택 기준을 측정하며, "확장 가능해 보인다"는 이유만으로 구현하지 않는다. **측정 결과·판정 정본은 §8.4다.**

### 8.4 Wave 3 도입-조건 측정 결과 (T-VN-51~56) — **본 절이 판정 정본**

§8.3이 유예한 여섯 확장 후보의 채택 기준·근거·판정을 고정한다. 상세 측정 부록은
[`docs/reports/t-vn-51-56-adoption-measurement-2026-07-21.md`](../reports/t-vn-51-56-adoption-measurement-2026-07-21.md).
측정은 n150 CI-parity(2026-07-21) 기준이며, tier-1 소규모 gate **12 passed / ~30s**,
tier-2 100만+ harness **수 분~수십 분(CI 아님)** 을 실측·재확인했다.

| Task | 주제 | 판정 | 트리거(재측정/개방 조건) |
|---|---|---|---|
| T-VN-51 | MVT tile | 유예 | low-zoom 개별 point 요구 발생 + tier-2 응답 >256KiB(gzip) 또는 p95 >200 ms |
| T-VN-52 | 범용 batch | 유예 | weather 외 2번째 per-row 왕복 실측(PinVi trace) |
| T-VN-53 | cursor key rotation | 유예(clean-cut) | 실 rotation에서 무효화 통증이 grace window 우위 입증 |
| T-VN-54 | weather partition/hypertable | 유예 | 활성 행 >50M, retention p95 >100 ms, 또는 T-VN-38 append 전환 |
| T-VN-55 | 물리 listener 분리 | 유예 | read 부하 상호간섭 >20% 또는 장애 전파 인시던트 |
| T-VN-56 | 대규모 fixture 주기 | 확정(2계층) | tier-2 전용 planner 회귀 반복 시 nightly 10만행 신설 |

- **T-VN-51 MVT / T-VN-52 batch**: low-zoom 계약이 이미 cluster rollup(§9.3.2)이라 내려보내는
  개별 point가 없고, batch는 200-id·N+1 가드(§8.3 tier-1)로 상한된다. 두 항목 모두 표의 트리거
  전에는 구현하지 않는다.
- **T-VN-53 cursor rotation**: T-VN-15가 versioned HMAC keyset을 clean-cut으로 채택했다. cursor는
  단명이라 rotation 시 진행 cursor만 422→재조회(무손실)된다. 운영 절차는 "secret compromise
  또는 정기(분기) 교체 시 단일 활성 key clean-cut 교체". grace window는 트리거 전 미구현.
- **T-VN-54 weather 볼륨**: T-VN-38부터 `feature_weather_values`는 source revision을 포함한
  immutable append fact다. `current_weather_summary`는 값 복제 없이 hot read를 고정하지만 history
  retention은 계속 증가한다. 활성 fact가 50M을 넘거나 retention p95가 100 ms를 넘으면 partition/
  hypertable을 재평가한다.
- **T-VN-55 listener 분리**: API/Dagster는 이미 물리 분리돼 있고 내부 listener는 read 지배
  비대칭이라 분리 이득이 배포 복잡성을 넘지 못한다.
- **T-VN-56 fixture 주기**: tier-2(100만+)는 release 주기가 정확하다(비용 수십 분, 결함 검출은
  소규모 tier-1 담당, tier-2 역할은 release budget 증거). nightly 중간 계층은 트리거 전 미신설.

## 9. 캐싱 정책 (Postgres 외)

### 9.1 라이브러리 레벨 캐시 — 사용하지 않는다

- 라이브러리는 stateless. in-memory 캐시 두지 않는다 (lifespan 복원 복잡, 다중
  워커 일관성 깨짐). 정식 결정은 **ADR-030** (accepted) — `functools.cache`
  한정 narrow 예외 (PlaceCategoryCode 카탈로그, `pyproj.Transformer` singleton).
  `import-linter` 계약으로 `cachetools` / `async_lru` / `aiocache` /
  `diskcache` 의존 차단.
- 호출자(PinVi)가 필요 시 자체 캐시(Redis/in-process LRU). 단 캐시 무효화
  책임은 호출자.

### 9.2 PostgreSQL 자체 캐시

- `effective_cache_size = 2GB` (Odroid 기본) — SPEC V8 v8_0 참고.
- 자주 쓰는 인덱스는 OS cache에 상주.
- `pg_prewarm` extension으로 부팅 후 warm-up 고려 (운영 결정 — **T-102**,
  §9.5).

### 9.3 PostGIS MV (Materialized View, T-101)

> **read >> write 확정 (2026-06-10, product owner)**: 본 시스템은 provider 적재
> (1일~수일 주기 cron) 대비 지도 viewport read가 압도적으로 많다. MV 도입의
> 첫째 전제(`read >> write 비율 실측`)는 정성적으로 충족됐다고 본다. 아래는 실제
> read 경로를 코드 기준으로 다시 검토해 **MV 도입 대상을 재타깃**한 결과다.
> 실 latency 수치(P99) 측정은 T-212e live full reload 리포트에서 보강한다.

#### 9.3.0 전제 정정 — detail 조립은 MV 대상이 아니다

원래 §9.3은 "`feature + place_detail + opening_hours` 또는 7개 detail kind union을
MV로 flatten"을 전제했다. **이 전제는 성립하지 않는다.** kind별 값의 정본은
ADR-086의 typed subtype 5종이고, 응답의 `detail`/`geom`은 뷰
`feature.features_detailed`가 조립한다. 조립은 core PK ↔ subtype PK LEFT JOIN
5개이며 배타 arc 때문에 한 feature는 그중 최대 하나에만 행을 갖는다. 따라서:

- 단건/배치 detail 조회(`_GET_FEATURE_SQL`, `_GET_FEATURES_BY_IDS_SQL`,
  `feature_repo.py`)는 **PK/`ANY(ids)`로 이미 좁혀진 행에만 PK join**이 붙는다.
  사전조립으로 줄일 비용이 없으므로 MV 이득이 **없다**.
- viewport bbox 조회(`_FEATURES_IN_BBOX_SQL`)는 detail을 조립하지 않고 core
  GIST(`coord`) + subtype GiST 후보 + keyset이라 이미 최적이다.
- 코드에 등장하는 `WITH ... AS MATERIALIZED (…)` CTE(`spatial_candidates` 등)는
  **planner 힌트(쿼리 1회 내 중간결과 고정)**일 뿐 **영속 MV가 아니다.** 혼동 주의.

결론: detail flatten용 `mv_features_place_with_detail`은 **더 이상 1순위가 아니다.**
read >> write 환경에서 실제로 반복 계산되는 비용은 아래 두 곳이다.

#### 9.3.1 read 경로별 MV 적합성 (코드 근거)

| read 경로 | 구조 (`feature_repo.py`) | 반복 비용 | MV 적합성 |
|-----------|--------------------------|-----------|-----------|
| `/features/in-bounds` 개별, `/features` bbox | 단일 테이블 GIST(`coord`) + keyset | 없음(인덱스 only) | ❌ 불필요 |
| `/features/{id}`, `/features/batch` | PK / `ANY(ids)` + `features_detailed` subtype PK join 조립 | 없음 | ❌ 불필요 |
| `/features/search` | trgm GIN + `similarity()` 동적 채점 | 쿼리마다 결과 변동 | ❌ 사전계산 불가 |
| **클러스터 rollup** (`_cluster_bbox_sql`, sido/sigungu/eupmyeondong) | viewport bbox 내 **`GROUP BY {code_col}` 집계 매 pan/zoom 재계산** | **viewport 이동마다 전체 후보 재집계** | ✅ **1순위** |
| `/features/nearby`, `/nearby/by-target` | GIST `ST_DWithin(coord_5179)` + **primary-source LATERAL** | per-row `source_links→source_records` lateral | ⚠️ 2순위(대안 有) |
| `/admin/features` | LEFT JOIN issues + source LATERAL | admin 전용, 저빈도 | ⚠️ 낮음 |

#### 9.3.2 1순위 후보 — 클러스터 rollup MV (`mv_feature_cluster_counts`)

zoom-out 클러스터링은 **viewport를 이동할 때마다** bbox 내 전체 feature를
`GROUP BY sido_code|sigungu_code|legal_dong_code`로 재집계한다(`_cluster_bbox_sql`).
read >> write에서 이 집계 결과는 적재 사이에 거의 불변이므로 **사전집계가 가장 큰
이득**이다.

```sql
-- 후보 정의 (예시 — 시범 시 확정)
CREATE MATERIALIZED VIEW feature.mv_feature_cluster_counts AS
SELECT
    cu.cluster_unit,                       -- 'sido' | 'sigungu' | 'eupmyeondong'
    cu.region_code,
    f.kind, f.category,
    count(*)                       AS feature_count,
    x_extension.ST_Centroid(x_extension.ST_Collect(f.coord)) AS centroid,  -- 대표 마커
    x_extension.ST_Envelope(x_extension.ST_Collect(f.coord)) AS region_bbox -- viewport 교차용
FROM feature.features f
CROSS JOIN LATERAL (VALUES
    ('sido', f.sido_code), ('sigungu', f.sigungu_code), ('eupmyeondong', f.legal_dong_code)
) AS cu(cluster_unit, region_code)
WHERE f.deleted_at IS NULL AND f.coord IS NOT NULL AND cu.region_code IS NOT NULL
GROUP BY cu.cluster_unit, cu.region_code, f.kind, f.category;

-- REFRESH CONCURRENTLY identity (필수)
CREATE UNIQUE INDEX uq_mv_cluster_counts
  ON feature.mv_feature_cluster_counts (cluster_unit, region_code, kind, category);
CREATE INDEX idx_mv_cluster_counts_bbox
  ON feature.mv_feature_cluster_counts USING GIST (region_bbox);
```

viewport 클러스터 쿼리는 이후 작은 rollup row만 합산한다:

```sql
SELECT region_code, sum(feature_count) AS feature_count,
       x_extension.ST_X(x_extension.ST_Centroid(x_extension.ST_Collect(centroid))) AS lon,
       x_extension.ST_Y(x_extension.ST_Centroid(x_extension.ST_Collect(centroid))) AS lat
FROM feature.mv_feature_cluster_counts
WHERE cluster_unit = :unit
  AND region_bbox && x_extension.ST_MakeEnvelope(:min_lon,:min_lat,:max_lon,:max_lat,4326)
  AND (:kinds IS NULL OR kind = ANY(:kinds))
  AND (:categories IS NULL OR category = ANY(:categories))
GROUP BY region_code
ORDER BY feature_count DESC, region_code
LIMIT :limit;
```

**카디널리티**: rollup row 수 = Σ(region 수 × kind × category). eupmyeondong(~3,500) ×
kind(≤7) × category(~수십)라도 feature 본수(10만+)보다 훨씬 작아 메모리에 fit.

**의미 변화 (도입 시 반드시 합의)**: 현재 쿼리는 **coord가 viewport bbox 안에 든
feature만** 세고 마커 위치는 그 부분집합의 `avg(coord)`다. MV 방식은 **region 단위
전체 집계**를 쓰고 viewport 교차는 `region_bbox &&`로 판단하므로,
(a) viewport 경계에 걸친 region은 **전체 count**가 잡혀 가장자리에서 과대계상,
(b) 마커는 viewport-clip 평균이 아니라 region 전체 centroid. zoom-out 클러스터의
"이 지역에 N개" 표시 의미에는 통상 허용되나 **현 동작과 다르다.** exact-viewport
(현행) vs region-total(MV) 중 택일을 시범 PR에서 결정한다.

#### 9.3.3 2순위 — primary-source LATERAL

> 최종 reader는 `source_links.source_role='primary' → source_entities →
> source_entity_heads → source_records → provider_datasets`를 사용한다. denormalized
> primary provider/dataset 유지 열은 새로 만들지 않는다.

`/features/nearby`·`/admin/features`는 feature마다
`source_links(source_role='primary') → source_entities → source_entity_heads → source_records`를
LATERAL로 1건 조회해
`primary_provider`/`primary_dataset_key`를 붙인다(`feature_repo.py`
`features_nearby_*`). read >> write에서 이 lateral은 매 호출 반복된다.

다만 이 비용은 **MV보다 적재/merge 시점에 `feature.features`에 유지하는
denormalized 컬럼**(`primary_provider`, `primary_dataset_key`)으로 더 싸게 제거
가능하다 — stale 윈도우가 없고 별도 refresh job도 불필요하기 때문이다(적재
트랜잭션 안에서 갱신). **권고: 2순위는 MV가 아니라 유지 컬럼으로 처리**하고,
유지 컬럼이 거부될 때에만 MV에 lateral 결과를 접는다. (코드 작업 전 ADR/Task로
별도 결정 — 본 문서는 검토만.)

#### 9.3.4 도입 조건 (1순위 MV 기준, 모두 충족 시)

- read >> write 비율 — **정성 충족(2026-06-10)**, 정량 P99는 T-212e에서 보강.
- `REFRESH CONCURRENTLY` lag (수십 초~수 분) 허용 가능 — 클러스터는 통상 허용.
- 디스크 사용량 증가 수용 (rollup MV는 본 테이블 대비 작음 — detail flatten보다 유리).
- 일관성 게이트 (ADR-033 Phase 2)가 swap 직전 적용되어 비정상 데이터의 MV 유입 차단.
- `REFRESH MATERIALIZED VIEW CONCURRENTLY` identity `UNIQUE` 인덱스(위 `uq_mv_cluster_counts`)
  를 migration에 포함. 생성 직후 1회는 비-concurrent `REFRESH MATERIALIZED VIEW`로 populate.

**도입 시 부작용**:
- `REFRESH CONCURRENTLY`는 UNIQUE 인덱스 필수 (위에서 보장).
- DDL 변경(컬럼/타입)이 무거워짐 — alembic revision에 MV `DROP + CREATE` 동반.
- MV가 stale일 때 "유저는 갱신했는데 지도엔 안 보임" 혼동 → 클러스터 MV는 적재
  주기와 묶여 갱신되므로 영향 작음. 그래도 `mv_last_refreshed_at` 노출 +
  `/ops/health-deep`에 포함 권장(T-102 prewarm 컴포넌트와 동일한 정보용 노출 패턴).

**refresh orchestration**: 이미 batch gate가 `OK/WARN`일 때 `mv_refresh` job을
만들고 현재 MV 카탈로그가 없으면 `skipped:no_materialized_views`로 기록한다
(T-200/T-RV-41, `infra.batch_dag`). 1순위 MV를 카탈로그에 등록하면 적재 batch
직후 자동 refresh로 연결된다 — **신규 orchestration 불필요.**

**도입 절차 (예상)**:
1. **클러스터 rollup MV 1개만** 시범 도입 (`mv_feature_cluster_counts`).
   ~~예전 예시 `mv_features_place_with_detail`은 9.3.0 사유로 폐기.~~
2. MV `CREATE`와 같은 migration에 `UNIQUE`(identity) + GIST(`region_bbox`) 인덱스 정의.
3. 배포 직후 최초 populate는 비-concurrent `REFRESH MATERIALIZED VIEW`로 실행.
4. 최초 populate 성공 후 batch gate/Dagster `mv_refresh`(`concurrently`)에 카탈로그 연결.
5. exact-viewport vs region-total 의미 택일 확정 + 1주 운영 + EXPLAIN diff 회귀 추적.
6. 효과 확인 시 2순위(primary-source 유지 컬럼) 별도 판단.
7. ADR 신설 — MV 카탈로그 + refresh schedule + DDL 정책 + 클러스터 의미 결정 기록.

### 9.4 별도 streaming ETL (Kafka/Redpanda) — T-103

**v2 1차 범위에서는 미사용** — 본 라이브러리 자체가 streaming consumer를
의존할 가치 없음 (함수 라이브러리, ADR-003).

**도입이 의미 있는 시나리오**:
- KNPS 산불경보 / 도로공사 사고 / KMA 특보처럼 *초 단위 latency*가 필요한
  notice 도메인.
- 멀티 컨슈머 fan-out (ETL + PinVi 알림 + 분석)이 분 단위 cron으로 처리
  불가한 경우.
- Provider가 webhook/push를 지원해서 폴링 → push 전환이 가능한 경우.

**도입 시 장점**:
- 분 단위 cron보다 빠른 응답 (수 초 이내).
- offset 기반 replay/backpressure — 다운스트림 일시 중단 시 재처리 안전.
- 다중 컨슈머가 동일 stream을 공유 (notice가 ETL 적재 + PinVi 알림 +
  분석으로 동시에 분기).

**도입 시 부작용 / 진입 비용**:
- Kafka/Redpanda 클러스터 운영 (broker, ZK or KRaft, monitoring) — Odroid
  단일 노드에서 비현실적, PinVi가 별도 인프라로 운영해야 함.
- exactly-once vs at-least-once trade-off, idempotency 키 설계.
- 디버깅이 Dagster batch보다 어려움 (consumer lag, offset 추적).

**kor-travel-map 위치**:
- ADR-045 이후 provider ingestion consumer를 도입한다면 kor-travel-map 독립 프로그램
  경계 안(`packages/kor-travel-map-dagster` 또는 별도 worker)에서 소유한다. PinVi
  `apps/etl`에 consumer를 두지 않는다.
- 메인 라이브러리(`kortravelmap`)에 Kafka client 의존 추가 금지
  (`pyproject.toml` import-linter 계약). 필요한 경우 별도 worker/Dagster 패키지와
  ADR로 다룬다.
- schema (Avro/Protobuf if used)는 `dto/` Pydantic 모델과 동기 유지하되,
  PinVi는 OpenAPI consumer일 뿐 Python DTO를 직접 import하지 않는다.

**판단 권고**: 특정 provider가 진짜 초 단위 latency를 요구한다는 증거가
잡힐 때만 ADR 작성 + kor-travel-map 운영 인프라 추가. 추측만으로 도입 금지.

### 9.5 pg_prewarm 부팅 후 warm-up — T-102

**메커니즘 구현 완료 (2026-06-09, T-102)** — 효과는 도입 조건 충족 시 큼:
- migration `0022_pg_prewarm_extension` (`x_extension.pg_prewarm`).
- 명시적 헬퍼 `kortravelmap.infra.prewarm.prewarm_relations`(hot relation buffer warm-up,
  확장 미설치 시 no-op). 부팅 훅/CLI/Dagster가 배포 직후 호출하는 용도.
- docker-compose postgres `shared_preload_libraries=pg_prewarm` + `pg_prewarm.autoprewarm=on`
  (background: 주기적 buffer 목록 dump + 재기동 시 자동 reload = "부팅 후 warm-up").
- `/ops/health-deep`의 `prewarm` 컴포넌트(extension/autoprewarm 상태, 정보용).
- **효과 조건**: 명시적 P99 SLO + 재배포 빈도 높음 + `shared_buffers`가 hot 데이터 fit
  (Odroid 기본 512MB는 일부만). 조건 미충족 시 비용은 낮고(저비용 worker) 이득이 작다.

**도입 시 장점**:
- 컨테이너 재시작/장애 복구 직후 cold-start cliff 제거. 첫 1~2분 P99
  outlier 사라짐 → PinVi가 부팅 직후 호출해도 정상 SLO.
- `idx_features_coord_5179_gist`, `idx_features_kind_category`, `ops.import_jobs`,
  `feature.feature_places` 같은 핫 path 인덱스/테이블을 부팅 시
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
- 슬로우 쿼리는 Grafana Loki에서 LogQL로 추적 (PinVi 측 wiring).

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

## 14. T-212d hot path baseline (2026-06-08, 2026-06-10 재측정)

T-212d는 실 운영 데이터가 충분하지 않은 상태에서 CI 재현성을 우선해 seeded
PostGIS/testcontainers baseline으로 고정했다. 로컬 live DB 확인 결과는 alembic `0016`,
`features/source_records/source_links/import_jobs` 각 1건, `consistency_reports`와
`dedup_review_queue` 0건이라 planner baseline으로 쓰지 않았다. 실제 provider/offline upload
볼륨 기준 측정은 T-212e live full reload 리포트에서 보강한다.

### 14.1 추가/수정 인덱스

- `feature.features`
  - `idx_features_updated_keyset(updated_at DESC, feature_id DESC)`
  - `idx_features_status_updated(status, updated_at DESC, feature_id DESC)`
  - `idx_features_lower_name_keyset(lower(name), feature_id)`
  - 운영시간 보유 feature keyset partial은 subtype이 갖는다 (ADR-086) —
    `idx_feature_places_opening_hours(feature_id)` partial `business_hours IS NOT NULL`,
    `idx_feature_events_opening_hours(feature_id)` partial `opening_hours IS NOT NULL`
- `ops.import_jobs`
  - `idx_import_jobs_created_keyset(created_at DESC, job_id DESC)`
  - `idx_import_jobs_status(status, created_at, queue_sequence)` — claim FIFO tie-breaker
  - `idx_import_jobs_kind_status(kind, status, created_at DESC, job_id DESC)`
- `ops.import_job_events`
  - `idx_import_job_events_time(occurred_at DESC, event_id DESC)`
  - `idx_import_job_events_job_time(job_id, occurred_at DESC, event_id DESC)`
  - `idx_import_job_events_provider_time(provider, occurred_at DESC, event_id DESC)`
    partial `provider IS NOT NULL AND quarantined_at IS NULL`
  - `idx_import_job_events_provider_dataset_time(provider, dataset_key, occurred_at DESC,
    event_id DESC)` partial
    `provider IS NOT NULL AND dataset_key IS NOT NULL AND quarantined_at IS NULL`
  - `idx_import_job_events_level_time(level, occurred_at DESC, event_id DESC)`
  - `idx_import_job_events_provider_dataset_scope_time(provider, dataset_key,
    sync_scope, occurred_at DESC, event_id DESC)` partial
    `provider IS NOT NULL AND dataset_key IS NOT NULL AND sync_scope IS NOT NULL
    AND quarantined_at IS NULL`

  모든 event 시간순 인덱스는 `quarantined_at IS NULL` partial predicate를 가진다. 0052에서
  격리한 기존 event는 보존하되 marker를 비정규화하므로, 조회 시 parent job을 join하거나 최신
  격리 event를 건너뛰지 않고 visible page만 bounded scan한다. `/ops/live`의 전역 revision은
  최신 event 1건, job event revision은 최근 5건만 읽으며 매 polling마다 exact 전체 건수를
  다시 세지 않는다. late commit과 최근 page 밖 UPDATE/DELETE는 singleton
  `ops.import_job_event_clock.revision`의 transactional 증가로 감지한다. AFTER STATEMENT에서 DML
  statement당 한 번만 global clock을 갱신해 bulk row별 WAL/dead tuple과 교차 row deadlock을
  피하며, timestamp는 진단에만 쓴다.
- `ops.feature_consistency_reports`
  - `idx_reports_started(started_at DESC, report_id DESC)`
  - `idx_reports_severity_started(severity_max, started_at DESC, report_id DESC)`
- `ops.data_integrity_violations`
  - `idx_violations_status_seen(status, last_seen_at DESC, issue_id DESC)`
  - `idx_violations_provider_status_seen(provider, status, last_seen_at DESC, issue_id DESC)`
  - `idx_violations_feature_seen(feature_id, last_seen_at DESC, issue_id DESC)`
- review queue
  - `idx_dedup_status_score(status, total_score DESC, review_id DESC)`
  - `idx_enrichment_review_status_score(status, name_score DESC, review_id DESC)`
  - `idx_enrichment_review_provider_status_score(source_provider, status, name_score DESC, review_id DESC)`

### 14.2 쿼리 패턴 변경

- `/features/in-bounds`: bbox 조건을 `spatial_candidates AS MATERIALIZED` CTE에 먼저
  적용해 `idx_features_coord_gist` 사용을 고정한다. `LIMIT`으로 잘리는 subset이 호출마다
  흔들리지 않도록 후보 materialize 뒤 `feature_id ASC`로 결정적 정렬을 유지한다.
- `/features/search`: q 검색 경로는 `name % :q` 후보를 먼저 materialize해 기존
  `idx_features_name_trgm` full GIN을 탄 뒤, `deleted_at`/bbox/kind/category 필터와
  score keyset을 적용한다. count query도 같은 q 전용 CTE를 사용한다.
- dedup/enrichment review list: cursor tie-breaker를 `review_id::text`가 아니라 UUID
  그대로 비교하고, queue 후보를 materialize한 뒤 feature/source 정보를 붙인다.
- enrichment review list: 단일 `status + provider` 필터는 scalar equality SQL로 분리해
  `idx_enrichment_review_provider_status_score`의 leading column과 정렬축을 안정적으로 탄다.
  후보 CTE 안에서 `LIMIT :limit_plus_one`을 먼저 적용해 feature join 전에 page 크기로 줄인다.
- bbox 클러스터(`_cluster_bbox_sql`): 현재 exact-viewport 의미는 유지한다. `sido`/`sigungu`/
  `eupmyeondong` 모두 bbox 후보 단계에서 `idx_features_coord_gist`를 사용한다.
- consistency F6/F7: F6은 `?| ARRAY[...]`와 partial index로 opening-hours 후보만 읽고,
  F7은 pending dedup 후보를 score keyset CTE로 먼저 고정한다.
- `/ops/pipeline/executions`: `WITH RECURSIVE`가 `parent_job_id` hierarchy를 component로
  접고 각 job의 가장 가까운 request anchor를 선택해 branch/standalone partition을
  만든 뒤 root filter와
  `(created_at DESC, id DESC, kind DESC)` keyset을 적용한다. recursive walk는
  `uuid[] path` cycle guard로 반드시 종료한다. provider/dataset 선택 조회는 typed job과
  request 배열의 indexed seed에서 양방향 parent/child component와 관련 request만
  먼저 좁힌 뒤 같은 root projection을 적용한다. UUID detail도 요청 또는 member가 속한
  component만 투영한다. `load_batch_id`/`parent_job_id` deep link도 각각
  `idx_import_jobs_load_batch_created`/`idx_import_jobs_parent_created`에서 member를 먼저
  선택한 뒤 component를 확장한다. 따라서 selective 조회에서 전체 job/request graph를 먼저 순회하면
  회귀다. 실행 identity는 `import_jobs` typed pair만 사용하고 `import_jobs.payload`와
  `import_job_events`를 projection에서 읽지 않는다.
- C3e canonical provider operation: overview/timeline/datasets grid/detail은 위 root CTE를
  공유한다. exact pair latest/history는
  `idx_import_jobs_provider_dataset_created(provider,dataset_key,created_at DESC,job_id DESC)`,
  dataset-only 조회는 `idx_import_jobs_dataset_created(dataset_key,created_at DESC,job_id DESC)`를
  사용한다. provider-only history는 composite pair index의 두 번째 key 때문에 정렬축을
  만족하지 못하므로 `idx_import_jobs_provider_created(provider,created_at DESC,job_id DESC)`를
  사용한다. direct scope도 linked typed job index로 찾고 별도 JSON expression index는 두지
  않는다. provider-only/dataset-only request 배열만 각 GIN access path를 사용한다.
  provider/dataset 독립 배열의 cross-product와 paginated timeline 첫 page 기반 전 dataset latest
  계산은 금지한다. overview count/24시간 failure는 raw child가 아니라 canonical root를 센다.
  event의 provider/dataset은 감사 API filter 메타데이터다. 감사 목록 SQL은 nullable-OR 한 문장을
  쓰지 않고 실제 입력 filter의 고정 clause만 bind와 함께 조합한다. 대표 REST filter와 인덱스는
  무필터→`idx_import_job_events_time`, job→`idx_import_job_events_job_time`, provider→
  `idx_import_job_events_provider_time`,
  provider+dataset exact pair→`idx_import_job_events_provider_dataset_time`, level→
  `idx_import_job_events_level_time`, canonical exact scope→
  `idx_import_job_events_provider_dataset_scope_time`이다. 모든 조합은 event의
  `quarantined_at IS NULL`을 직접 포함한다. 0057의 scope 조회는 nullable-OR나
  request/job JOIN을 쓰지 않고 `provider/dataset/sync_scope IS NOT NULL` partial predicate를
  그대로 넣은 뒤 `(occurred_at,event_id)` keyset과 LIMIT를 적용한다. job 단건처럼 후보가
  64건 이하인 작은 결과에서는 planner가 같은
  자연키 index의 bounded bitmap scan + bounded sort를 고를 수 있으며 이를 회귀로
  허용한다. exact-scope hot path는 sort 없는 ordered index scan을 유지한다.
  dataset key는 provider namespace에 속하므로 dataset-only event filter는 `422`/`ValueError`로
  거부한다. 0057은 더 이상 읽기 경로가 없는 `idx_import_job_events_dataset_time`을 제거한다.
  projection seed용 event index는 두지 않는다.

### 14.3 회귀 테스트

`tests/integration/test_t212d_perf_explain.py`는 3,200 feature, source/link, import job,
consistency report/violation, dedup/enrichment review queue를 live-like 분포로 seed한다.
EXPLAIN JSON에서 다음 hot path가 기대 인덱스를 쓰는지 검증한다. 기본 케이스는
`enable_seqscan=off`로 인덱스 적격성을 고정하고, 대표 hot path는 seqscan hint 없이도
planner가 base table `Seq Scan`을 선택하지 않는지 별도 가드한다.

- `/features/nearby`, `/features/in-bounds`, `/features/search`
- `/features/in-bounds` 클러스터(`sido`/`sigungu`/`eupmyeondong`)
- `/admin/features`, `/ops/pipeline/executions`, consistency report/issue 목록
- dedup refresh, dedup/enrichment review list
- consistency F4/F6/F7/F8
- `/admin/features` `sort=name`의 `idx_features_lower_name_keyset`
- dedup/enrichment review cursor 전체 순회 gap/중복 없음
- pipeline root projection은 전체 partition에서 `job_id`가 정확히 한 번 귀속되는지,
  canonical request root/standalone/cycle/부모 누락에서도 branch가 섞이지 않는지 검증한다.
  중첩 request root와 동일 job 다중 request는 정상 projection 사례가 아니라 DB constraint 위반
  회귀로 검증한다. EXPLAIN은
  `idx_import_jobs_parent_created`, `idx_import_jobs_created_keyset`,
  `uq_feature_update_requests_job_id` access path와 recursive 비용을 점검한다. selective plan에는
  `import_job_events` relation 자체가 없어야 한다. 소규모 fixture에서 planner 선택이 흔들리는
  index는 억지 assert하지 않되 plan 크기·temp I/O·실측 비용과 base table Seq Scan을 gate로 둔다.
  전체 hierarchy materialization이 page 크기와 무관하게 커지는 plan이면 구현을 중단하고
  schema/index 변경을 다시 판단한다.
- C3e pair/provider-only/dataset-only 조회는 direct typed job seed와 request 배열 GIN seed를
  `UNION ALL` 후보 집합으로 구성한다. 각 전용 index를 EXPLAIN하고, 1,000개
  이상의 root와 multi-pair child에서도 grid latest 누락 0, overview count의 child fan-out 0,
  pipeline/detail cursor 누락·중복 0을 검증한다.
- datasets grid/detail의 실행 상태는 scope마다 별도 쿼리를 보내지 않는다. 공용 root CTE를
  한 번 실행한 snapshot 안에서 exact pair의 활성/종료 boolean partition별 `row_number=1`만
  반환한다. 회귀 테스트는 동일 scope의 종료 root와 더 최신 활성 root가 동시에 보존되고,
  repository 호출이 SQL 한 번으로 끝나는지 검증한다. 실행 이력 후속 cursor는 전체 filter
  fingerprint가 같을 때만 DB에 도달한다.
- feature update queue는 request 테이블에 lifecycle 상태를 복제하지 않는다. partial
  `idx_import_jobs_feature_update_queue`로 queued canonical job만 seed한 뒤 unique `job_id`로 request를
  JOIN하고 priority를 정렬한다. 완료 이력이 늘어나도 request history 전체를 순회하지 않는지 natural
  planner EXPLAIN으로 검증한다.
- event 감사 조회는 same-dataset/different-provider 4,000행과
  same-provider/different-dataset 4,000행을 둔 natural planner에서 무필터·provider-only·exact pair의
  첫/후속 page가 각 시간순 index를 사용하고 Seq Scan·Sort·64행 초과 residual을 만들지 않는지
  검증한다. 0057 exact-scope 회귀는 같은 provider/dataset의 서로 다른 canonical scope를
  각각 4,000행 넣고 첫/후속 page가 scope partial index를 사용하며 Seq Scan·Sort 없이
  64행 이내에서 멈추는지도 별도로 검증한다.

제약: `feature.feature_files`는 아직 Alembic 테이블이 없으므로 F8 테스트는 임시 DDL로
실행 계획 형태만 확인한다. `0020`의 `CREATE INDEX`는 일반 Alembic transaction DDL이며,
T-212e empty reload 전제에서는 무해하지만 데이터가 찬 운영 DB에 직접 적용하면 쓰기 잠금을
동반할 수 있다. `idx_import_jobs_status(status, created_at, queue_sequence)`는 FIFO queue
claim에 맞춘 인덱스이고 list keyset의 `job_id` tie-breaker와 완전히 같지는 않으므로,
import job 대량화 뒤 `idx_import_jobs_status_created_keyset(status, created_at DESC, job_id DESC)`
필요성을 다시 EXPLAIN으로 확인한다.

### 14.4 2026-06-10 read-heavy 재측정 결론

T-216f/g와 PinVi-agent provider 반영 후 T-212d를 다시 실행했다. 전용 EXPLAIN 통합
테스트는 5개에서 6개로 늘었고, seeded PostGIS/testcontainers 기준 `6 passed`다.

- 클러스터 hot path를 새로 baseline에 포함했다. 세 cluster unit 모두 `idx_features_coord_gist`
  적격성을 검증하고, 대표 `sigungu` 경로는 seqscan hint 없이도 base table `Seq Scan`이
  없음을 확인한다.
- `mv_feature_cluster_counts`는 이번 PR에서 도입하지 않았다. 현재 API는 viewport bbox 안의
  feature만 세는 exact-viewport 의미지만, MV 후보는 region-total count/centroid로 바뀐다.
  의미 변경과 edge region 과대계상은 T-212e live full reload의 실제 row 수/P99 측정 뒤
  별도 ADR/PR에서 결정한다.
- enrichment review 단일 `status + provider` 목록은 `ANY(array)` generic plan 대신 scalar
  equality fast path를 사용한다. 다중 provider는 `ANY(array)` 경로를 유지하되 base table
  seq scan이 없는지 회귀로 고정한다.

상세 리포트: `docs/reports/t-212d-read-heavy-rerun-2026-06-10.md`.

### 14.5 cache-target snapshot streaming·physical 관측

T-VN-41S snapshot은 전체 head/item Python list와 한 번의 무제한 `executemany`를 금지한다. DB 정렬
cursor를 `yield_per=1,000`으로 읽고 incremental Merkle level stack만 유지한다. 첫 scan은 admission과
root를 확정하고, 두 번째 scan은 1,000행 INSERT batch와 응답 page만 유지한다. item 1,000,000개와
canonical material 512 MiB는 서로 독립인 fail-close ceiling이다. 두 번째 scan의 count/bytes/root가
다르면 같은 transaction을 rollback한다.

GC 관측은 논리 row count만으로 bloat를 숨기지 않는다. `pg_table_size` 합, `pg_indexes_size` 합,
`pg_stat_user_tables.n_dead_tup` 합, 두 snapshot relation의 최근 vacuum 중 가장 긴 age를 함께 기록한다.
vacuum 이력이 없는 relation은 age 0이 아니라 관측 불능이다. threshold는 초기 운영 guardrail이며
n150 1M admitted materialization/compaction soak에서 처리량, relation 감소, dead tuple 회수와 실제
autovacuum cadence를 측정해 조정한다. final receipt/material schema의 hot path와 compaction 후보 SQL은
`0231_tvn41s_snapshot_material` 뒤 natural planner EXPLAIN으로 index scan과 bounded lock set을 검증했다
(`tests/integration/test_tvn41s_snapshot_material_explain.py`). `enable_seqscan=off`는 쓰지 않는다 —
`disable_cost` 때문에 "Seq Scan 없음" 단언이 반증 불가능해진다.

## 15. 운영 체크리스트 (Sprint 5 진입 전)

- [ ] 모든 hot path SQL에 EXPLAIN 통합 테스트
- [ ] `pg_stat_statements` 활성화 및 Grafana 패널
- [ ] `log_min_duration_statement` 설정
- [ ] BRIN 인덱스 효율 측정 (1주 운영 후)
- [ ] 인덱스 hit ratio 95%+ 확인
- [ ] 부분 인덱스 vs 전체 인덱스 비교 (디스크 사용량)
- [ ] `VACUUM ANALYZE` cron + autovacuum 튜닝

## 16. 이관된 결정 (구 ADR)

- bulk insert는 `psycopg.copy_*` 우선, 안전 마진 30k 파라미터 (구 ADR-013에서
  결정) — §1 원칙 5, §5.2/§5.3 표준 예시, §13 안티패턴 표에 본문이 충분히
  반영되어 있다.
