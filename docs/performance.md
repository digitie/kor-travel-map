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

> **read >> write 확정 (2026-06-10, product owner)**: 본 시스템은 provider 적재
> (1일~수일 주기 cron) 대비 지도 viewport read가 압도적으로 많다. MV 도입의
> 첫째 전제(`read >> write 비율 실측`)는 정성적으로 충족됐다고 본다. 아래는 실제
> read 경로를 코드 기준으로 다시 검토해 **MV 도입 대상을 재타깃**한 결과다.
> 실 latency 수치(P99) 측정은 T-212e live full reload 리포트에서 보강한다.

#### 9.3.0 전제 정정 — "7-way detail JOIN"은 더 이상 없다

원래 §9.3은 "`feature + place_detail + opening_hours` 또는 7개 detail kind union을
MV로 flatten"을 전제했다. **이 전제는 ADR-018로 무효화됐다.** 현재 스키마(alembic
`0002_features_and_source_tables`)에서 detail은 **`feature.features.detail` 단일
JSONB 컬럼**이고 `kind`로 구분된다. `place_details`/`event_details` 같은 per-kind
detail 테이블은 **존재하지 않는다**. 따라서:

- 단건/배치 detail 조회(`_GET_FEATURE_SQL`, `_GET_FEATURES_BY_IDS_SQL`,
  `feature_repo.py`)는 이미 `feature.features` **PK/`ANY(ids)` 단일 테이블 조회 +
  JSONB 인라인**이다. flatten할 JOIN이 없으므로 MV 이득이 **없다**.
- viewport bbox 조회(`_FEATURES_IN_BBOX_SQL`)도 단일 테이블 GIST(`coord`) +
  keyset이라 이미 최적이다.
- 코드에 등장하는 `WITH ... AS MATERIALIZED (…)` CTE(`spatial_candidates` 등)는
  **planner 힌트(쿼리 1회 내 중간결과 고정)**일 뿐 **영속 MV가 아니다.** 혼동 주의.

결론: detail flatten용 `mv_features_place_with_detail`은 **더 이상 1순위가 아니다.**
read >> write 환경에서 실제로 반복 계산되는 비용은 아래 두 곳이다.

#### 9.3.1 read 경로별 MV 적합성 (코드 근거)

| read 경로 | 구조 (`feature_repo.py`) | 반복 비용 | MV 적합성 |
|-----------|--------------------------|-----------|-----------|
| `/features/in-bounds` 개별, `/features` bbox | 단일 테이블 GIST(`coord`) + keyset | 없음(인덱스 only) | ❌ 불필요 |
| `/features/{id}`, `/features/batch` | PK / `ANY(ids)` 단일 테이블 + JSONB detail 인라인 | 없음 | ❌ 불필요 |
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

#### 9.3.3 2순위 — primary-source LATERAL: MV보다 유지(denormalized) 컬럼 우선

`/features/nearby`·`/admin/features`는 feature마다
`source_links(is_primary_source) → source_records`를 LATERAL로 1건 조회해
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

**메커니즘 구현 완료 (2026-06-09, T-102)** — 효과는 도입 조건 충족 시 큼:
- migration `0022_pg_prewarm_extension` (`x_extension.pg_prewarm`).
- 명시적 헬퍼 `krtour.map.infra.prewarm.prewarm_relations`(hot relation buffer warm-up,
  확장 미설치 시 no-op). 부팅 훅/CLI/Dagster가 배포 직후 호출하는 용도.
- docker-compose postgres `shared_preload_libraries=pg_prewarm` + `pg_prewarm.autoprewarm=on`
  (background: 주기적 buffer 목록 dump + 재기동 시 자동 reload = "부팅 후 warm-up").
- `/ops/health-deep`의 `prewarm` 컴포넌트(extension/autoprewarm 상태, 정보용).
- **효과 조건**: 명시적 P99 SLO + 재배포 빈도 높음 + `shared_buffers`가 hot 데이터 fit
  (Odroid 기본 512MB는 일부만). 조건 미충족 시 비용은 낮고(저비용 worker) 이득이 작다.

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

## 14. T-212d hot path baseline (2026-06-08)

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
  - `idx_features_opening_hours_keyset(feature_id)` partial:
    `deleted_at IS NULL AND detail ?| ARRAY['business_hours','opening_hours']`
- `ops.import_jobs`
  - `idx_import_jobs_created_keyset(created_at DESC, job_id DESC)`
  - `idx_import_jobs_state(state, created_at, queue_sequence)` — claim FIFO tie-breaker
  - `idx_import_jobs_kind_state(kind, state, created_at DESC, job_id DESC)`
- `ops.feature_consistency_reports`
  - `idx_reports_started(started_at DESC, report_id DESC)`
  - `idx_reports_severity_started(severity_max, started_at DESC, report_id DESC)`
- `ops.data_integrity_violations`
  - `idx_violations_status_detected(status, detected_at DESC, violation_key DESC)`
  - `idx_violations_provider_status_detected(provider, status, detected_at DESC, violation_key DESC)`
  - `idx_violations_feature_detected(feature_id, detected_at DESC, violation_key DESC)`
- review queue
  - `idx_dedup_status_score(status, total_score DESC, review_key DESC)`
  - `idx_enrichment_review_status_score(status, name_score DESC, review_key DESC)`
  - `idx_enrichment_review_provider_status_score(source_provider, status, name_score DESC, review_key DESC)`

### 14.2 쿼리 패턴 변경

- `/features/in-bounds`: bbox 조건을 `spatial_candidates AS MATERIALIZED` CTE에 먼저
  적용해 `idx_features_coord_gist` 사용을 고정한다. `LIMIT`으로 잘리는 subset이 호출마다
  흔들리지 않도록 후보 materialize 뒤 `feature_id ASC`로 결정적 정렬을 유지한다.
- `/features/search`: q 검색 경로는 `name % :q` 후보를 먼저 materialize해 기존
  `idx_features_name_trgm` full GIN을 탄 뒤, `deleted_at`/bbox/kind/category 필터와
  score keyset을 적용한다. count query도 같은 q 전용 CTE를 사용한다.
- dedup/enrichment review list: cursor tie-breaker를 `review_key::text`가 아니라 UUID
  그대로 비교하고, queue 후보를 materialize한 뒤 feature/source 정보를 붙인다.
- consistency F6/F7: F6은 `?| ARRAY[...]`와 partial index로 opening-hours 후보만 읽고,
  F7은 pending dedup 후보를 score keyset CTE로 먼저 고정한다.

### 14.3 회귀 테스트

`tests/integration/test_t212d_perf_explain.py`는 3,200 feature, source/link, import job,
consistency report/violation, dedup/enrichment review queue를 live-like 분포로 seed한다.
EXPLAIN JSON에서 다음 hot path가 기대 인덱스를 쓰는지 검증한다. 기본 케이스는
`enable_seqscan=off`로 인덱스 적격성을 고정하고, 대표 hot path는 seqscan hint 없이도
planner가 base table `Seq Scan`을 선택하지 않는지 별도 가드한다.

- `/features/nearby`, `/features/in-bounds`, `/features/search`
- `/admin/features`, `/ops/import-jobs`, consistency report/issue 목록
- dedup refresh, dedup/enrichment review list
- consistency F4/F6/F7/F8
- `/admin/features` `sort=name`의 `idx_features_lower_name_keyset`
- dedup/enrichment review cursor 전체 순회 gap/중복 없음

제약: `feature.feature_files`는 아직 Alembic 테이블이 없으므로 F8 테스트는 임시 DDL로
실행 계획 형태만 확인한다. `0020`의 `CREATE INDEX`는 일반 Alembic transaction DDL이며,
T-212e empty reload 전제에서는 무해하지만 데이터가 찬 운영 DB에 직접 적용하면 쓰기 잠금을
동반할 수 있다. `idx_import_jobs_state(state, created_at, queue_sequence)`는 FIFO queue
claim에 맞춘 인덱스이고 list keyset의 `job_id` tie-breaker와 완전히 같지는 않으므로,
import job 대량화 뒤 `idx_import_jobs_state_created_keyset(state, created_at DESC, job_id DESC)`
필요성을 다시 EXPLAIN으로 확인한다.

## 15. 운영 체크리스트 (Sprint 5 진입 전)

- [ ] 모든 hot path SQL에 EXPLAIN 통합 테스트
- [ ] `pg_stat_statements` 활성화 및 Grafana 패널
- [ ] `log_min_duration_statement` 설정
- [ ] BRIN 인덱스 효율 측정 (1주 운영 후)
- [ ] 인덱스 hit ratio 95%+ 확인
- [ ] 부분 인덱스 vs 전체 인덱스 비교 (디스크 사용량)
- [ ] `VACUUM ANALYZE` cron + autovacuum 튜닝
