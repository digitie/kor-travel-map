# postgres-schema.md — PostgreSQL 스키마 reference 카탈로그

본 문서는 `docs/data-model.md`의 DDL을 빠른 참조용 카탈로그로 정리한다. 모든 표준
table/column/index/constraint를 한눈에. 자세한 의미·근거·인덱스 설계는
`docs/data-model.md`와 `docs/performance.md`를 본다.

> 본 문서는 **참조 카드**다. DDL 원본은 `docs/data-model.md`. 둘이 충돌하면
> `data-model.md`가 정답.

## 1. 환경 / 확장

| 항목 | 값 |
|------|----|
| RDBMS | PostgreSQL 16 |
| 공간 | PostGIS 3.5 + `postgis_topology` |
| 인덱스 보조 | `pg_trgm`, `pgcrypto` |
| 확장 schema | `x_extension` (ADR-008) |
| `search_path` | `public, x_extension` |
| 시간 | 모두 `TIMESTAMPTZ` (KST 저장 권장) |
| JSON | `JSONB`만 (raw `JSON` 금지) |
| SRID | WGS84 (`4326`) + UTM-K (`5179`, meter — 반경 검색용 ADR-012) |

```sql
CREATE EXTENSION postgis           SCHEMA x_extension;
CREATE EXTENSION postgis_topology  SCHEMA x_extension;
CREATE EXTENSION pg_trgm           SCHEMA x_extension;
CREATE EXTENSION pgcrypto          SCHEMA x_extension;
```

## 2. Schema 매핑

| schema | 책임 | 테이블 수 (v2 1차) |
|--------|------|------------------|
| `feature` | feature 도메인 본체 (features + 5 detail + opening_hours + weather + price + files) | 11 |
| `provider_sync` | source 추적 + sync state | 3 |
| `ops` | 운영 (작업 큐, 검수, 정합성, api 로그) | 7 |
| `x_extension` | 확장 (postgis 등) | extensions only |

## 3. 테이블 카탈로그 (alphabetical by schema)

### 3.1 `feature.*`

| 테이블 | PK | 핵심 컬럼 / 비고 |
|--------|----|---------------|
| `features` | `feature_id` | kind/name/category/coord/coord_5179(generated)/geom/address/legal_dong_code/marker_*/parent/sibling_group_id/detail/raw_refs/status |
| `feature_files` | `file_id` | feature_id FK CASCADE; UNIQUE (storage_backend,bucket,object_key); file_type CHECK |
| `feature_place_details` | `feature_id` | place_kind, phones (≤3), reviews_link, business_hours, facility_info, license_date, biz_number |
| `feature_event_details` | `feature_id` | event_kind, starts_on/ends_on (CHECK), venue_name, content_id, area_code |
| `feature_notice_details` | `feature_id` | notice_type, severity (0-5), valid_start/end_time (CHECK), source_agency |
| `feature_area_details` | `feature_id` | area_kind, boundary_source, area_square_meters, regulation_scope, administrative_office |
| `feature_route_details` | `feature_id` | route_type, geometry_source, geometry_status, total_distance_meters (CHECK ≥0), expected_duration_minutes (CHECK >0) |
| `feature_opening_periods` | `(feature_id, period_index)` | start_weekday (0-6), start_time (HHMM regex), duration_minutes (1~10080) |
| `feature_special_days` | `(feature_id, special_date)` | is_closed, periods JSONB |
| `feature_weather_values` | `weather_value_key` | UNIQUE (feature_id, provider, weather_domain, forecast_style, metric_key, issued_at, valid_at, observed_at) |
| `price_points` | `feature_id` | price_category, retention_days (≥1) |
| `price_values` | `(feature_id, item_key, observed_at)` | value Numeric(12,2), currency CHAR(3) |

### 3.2 `provider_sync.*`

| 테이블 | PK | 핵심 컬럼 / 비고 |
|--------|----|---------------|
| `source_records` | `source_record_key` | UNIQUE (provider,dataset_key,source_entity_type,source_entity_id,raw_payload_hash); raw_data JSONB |
| `source_links` | `(feature_id, source_record_key)` | source_role CHECK 8종, confidence 0-100, is_primary_source bool |
| `provider_sync_state` | `(provider, dataset_key, sync_scope)` | status, cursor JSONB, last_success_at, next_run_after |

### 3.3 `ops.*`

| 테이블 | PK | 핵심 컬럼 / 비고 |
|--------|----|---------------|
| `import_jobs` | `job_id UUID` | kind, payload, state (queued/running/done/failed/cancelled), progress (0-100), heartbeat_at |
| `dedup_review_queue` | `review_key UUID` | (feature_id_a, feature_id_b) UNIQUE, total_score/name/spatial/category (0-100), status, decision_reason |
| `feature_overrides` | `override_key UUID` | feature_id FK, field_path, source_value/override_value JSONB, status |
| `feature_merge_history` | `merge_id UUID` | master_feature_id FK, loser_feature_id FK (둘 다 CASCADE), score, review_key FK (SET NULL), merged_by, reason, merged_at (alembic 0007, ADR-016) |
| `data_integrity_violations` | `violation_key UUID` | violation_type, severity (info/warning/error/critical), payload, status |
| `api_call_log` | `id BIGSERIAL` | provider, endpoint, status, latency_ms, occurred_at; BRIN(occurred_at) |
| `feature_consistency_reports` | `report_id UUID` | ADR-033 Phase 1; batch_id, started_at/finished_at, severity_max CHECK(OK/WARN/ERROR), cases/summary JSONB |
| `feature_update_requests` | `request_id UUID` | **계획(ADR-045, alembic 미구현)** — scope_type/scope JSONB, providers·dataset_keys JSONB, run_mode (queued/now), state (queued/running/done/failed/cancelled — import_jobs와 동일 전이), job_id FK, operator, reason, error_message. DDL 정본: `docs/openapi-admin-contract.md` §6.1 + `docs/data-model.md` §9.8 |

## 4. 인덱스 카탈로그

### 4.1 `feature.features`

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_features_coord_gist` | GIST(coord) | partial WHERE deleted_at IS NULL |
| `idx_features_coord_5179_gist` | GIST(coord_5179) | 반경 검색 핵심 (ADR-012) |
| `idx_features_geom_gist` | GIST(geom) | route/area LINESTRING/MULTIPOLYGON |
| `idx_features_kind_category` | (kind, category) | partial active |
| `idx_features_status_updated` | (status, updated_at) | admin |
| `idx_features_legal_dong_code` | (legal_dong_code) | 행정구역 필터 |
| `idx_features_sigungu` | (sigungu_code, kind) | partial active |
| `idx_features_parent` | (parent_feature_id) | partial NOT NULL |
| `idx_features_sibling` | (sibling_group_id) | partial NOT NULL |
| `idx_features_name_trgm` | GIN(name gin_trgm_ops) | pg_trgm 부분 문자열 |
| `idx_features_event_end` | ((detail->>'ends_on')::date) | partial event |
| `idx_features_notice_valid` | ((detail->>'valid_end_time')::timestamptz) | partial notice |

### 4.2 `provider_sync.*`

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_source_records_provider_dataset_entity` | (provider, dataset_key, source_entity_type, source_entity_id) | |
| `idx_source_records_imported_at_brin` | BRIN(imported_at) | 시계열 |
| `idx_source_records_fetched_at_brin` | BRIN(fetched_at) | |
| `idx_source_records_expires_at` | (expires_at) | partial NOT NULL (purge) |
| `idx_source_links_record` | (source_record_key) | |
| `idx_source_links_role` | (source_role) | |
| `idx_source_links_primary` | (feature_id) | partial is_primary_source |
| `idx_sync_state_next_run` | (next_run_after) | partial status='active' |

### 4.3 `feature.feature_files`

| 인덱스 | 컬럼 |
|--------|------|
| `idx_feature_files_feature_type` | (feature_id, file_type) |
| `idx_feature_files_feature_order` | (feature_id, display_order) |
| `idx_feature_files_provider` | (provider, dataset_key) partial NOT NULL |

### 4.4 detail 테이블

| 테이블 | 인덱스 |
|--------|--------|
| `feature_place_details` | (place_kind), (biz_number) partial |
| `feature_event_details` | (starts_on, ends_on), (event_kind), (content_id) partial |
| `feature_notice_details` | (notice_type), (notice_type, valid_start_time, valid_end_time), (valid_start_time), (source_agency) partial |
| `feature_area_details` | (area_kind), (boundary_source) partial |
| `feature_route_details` | (route_type), (geometry_status), (geometry_source) |
| `feature_opening_periods` | (start_weekday, start_time) |
| `feature_special_days` | (special_date) |

### 4.5 weather/price

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_weather_feature_metric_time` | (feature_id, metric_key, valid_at DESC NULLS LAST) | `build_weather_card` 핵심 |
| `idx_weather_provider_domain` | (provider, weather_domain, valid_at DESC NULLS LAST) | admin |
| `idx_weather_valid_at_brin` | BRIN(valid_at) | 시계열 |
| `idx_weather_collected_at_brin` | BRIN(collected_at) | 시계열 |
| `idx_price_points_category` | (price_category) | |
| `idx_price_values_observed_at_brin` | BRIN(observed_at) | 시계열 |
| `idx_price_values_item_observed` | (item_key, observed_at DESC) | 종목별 최신 |

### 4.6 ops

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_import_jobs_state` | (state, created_at) | scheduler |
| `idx_import_jobs_kind_state` | (kind, state, created_at DESC) | admin |
| `idx_import_jobs_heartbeat` | (heartbeat_at) | partial state='running' |
| `idx_dedup_status_score` | (status, total_score DESC) | partial pending |
| `idx_overrides_feature` | (feature_id, status) | |
| `idx_overrides_field` | (field_path) | |
| `idx_merge_history_master` | (master_feature_id, merged_at DESC) | |
| `idx_merge_history_loser` | (loser_feature_id) | "이 feature가 어디로 병합됐나" 역추적 |
| `idx_violations_type_status` | (violation_type, status) | |
| `idx_violations_feature` | (feature_id) | partial NOT NULL |
| `idx_violations_detected_brin` | BRIN(detected_at) | |
| `idx_api_call_occurred_brin` | BRIN(occurred_at) | |
| `idx_api_call_provider_time` | (provider, occurred_at DESC) | |
| `idx_reports_batch` | (batch_id) | feature_consistency_reports (ADR-033) |
| `idx_reports_started` | (started_at DESC) | feature_consistency_reports |

## 5. CHECK constraint 카탈로그

| 테이블 | 제약 | 정의 |
|--------|------|------|
| `features` | `ck_features_kind` | kind ∈ FeatureKind 7종 |
| `features` | `ck_features_status` | status ∈ FeatureStatus 6종 |
| `features` | `ck_features_coord_pair` | coord NULL이거나 한국 영역 안 (lon 124-132, lat 33-39.5) |
| `feature_files` | `ck_feature_files_file_type` | image/video/audio/document/file |
| `feature_files` | `ck_feature_files_display_order` | ≥ 0 |
| `feature_files` | `ck_feature_files_byte_size` | NULL or ≥ 0 |
| `feature_files` | `ck_feature_files_width/height` | NULL or > 0 |
| `feature_place_details` | `ck_place_phones_len` | jsonb_array_length ≤ 3 |
| `feature_event_details` | `ck_event_dates` | starts_on ≤ ends_on |
| `feature_notice_details` | `ck_notice_severity` | NULL or 0-5 |
| `feature_notice_details` | `ck_notice_time_range` | valid_start ≤ valid_end |
| `feature_route_details` | `ck_route_distance` | NULL or ≥ 0 |
| `feature_route_details` | `ck_route_duration` | NULL or > 0 |
| `feature_opening_periods` | `ck_opening_weekday` | 0-6 |
| `feature_opening_periods` | `ck_opening_time` | regex `^([01]\d|2[0-3])[0-5]\d$` |
| `feature_opening_periods` | `ck_opening_duration` | 0 < n ≤ 10080 |
| `source_links` | `ck_source_links_confidence` | 0-100 |
| `source_links` | `ck_source_links_role` | SourceRole 8종 |
| `price_points` | `ck_price_points_retention` | ≥ 1 |
| `import_jobs` | `ck_import_jobs_state` | queued/running/done/failed/cancelled |
| `import_jobs` | `ck_import_jobs_progress` | 0-100 |
| `dedup_review_queue` | `ck_dedup_status` | pending/accepted/rejected/merged/ignored |
| `dedup_review_queue` | `ck_dedup_scores` | 각 점수 0-100 |
| `feature_overrides` | `ck_overrides_status` | active/inactive/superseded |
| `data_integrity_violations` | `ck_violations_severity` | info/warning/error/critical |
| `data_integrity_violations` | `ck_violations_status` | open/acknowledged/resolved/ignored |

## 6. FK CASCADE 정책

| 관계 | 정책 | 이유 |
|------|------|------|
| `feature_files.feature_id` → `features` | CASCADE | feature 삭제 시 파일 메타도 |
| `feature_files.source_record_key` → `source_records` | SET NULL | source 정리해도 파일은 유지 |
| `feature_*_details.feature_id` → `features` | CASCADE | detail은 feature 종속 |
| `feature_opening_periods.feature_id` → `features` | CASCADE | |
| `feature_special_days.feature_id` → `features` | CASCADE | |
| `feature_weather_values.feature_id` → `features` | CASCADE | |
| `feature_weather_values.source_record_key` → `source_records` | SET NULL | |
| `price_points.feature_id` → `features` | CASCADE | |
| `price_values.feature_id` → `price_points` | CASCADE | |
| `source_links.feature_id` → `features` | CASCADE | |
| `source_links.source_record_key` → `source_records` | CASCADE | |
| `features.parent_feature_id` → `features` | SET NULL | 부모 삭제 시 고아 허용 |
| `dedup_review_queue.feature_id_*` → `features` | CASCADE | |
| `feature_overrides.feature_id` → `features` | CASCADE | |
| `feature_overrides.source_record_key` → `source_records` | SET NULL | |
| `feature_merge_history.master_feature_id` → `features` | CASCADE | |
| `feature_merge_history.loser_feature_id` → `features` | CASCADE | loser는 soft-delete(ADR-017)라 행 잔존 → FK 유효 |
| `feature_merge_history.review_key` → `dedup_review_queue` | SET NULL | 큐 행 삭제돼도 이력 보존 |
| `data_integrity_violations.feature_id` → `features` | CASCADE | |

## 7. 보관 정책 (ADR-017) → purge SQL

```sql
-- weather_values: +30일 (참조 trip 0건은 TripMate trip_pois 조인으로 별도 검증)
DELETE FROM feature.feature_weather_values WHERE valid_at < now() - interval '30 days';

-- notice: 종료일/발표일 +1년
DELETE FROM feature.feature_notice_details d USING feature.features f
WHERE d.feature_id=f.feature_id
  AND f.kind='notice' AND d.valid_end_time < now() - interval '1 year';

-- event: 종료일 +20년
DELETE FROM feature.feature_event_details d USING feature.features f
WHERE d.feature_id=f.feature_id
  AND f.kind='event' AND d.ends_on < (now() - interval '20 years')::date;

-- price_values: 카테고리별 retention_days (price_points에서)
DELETE FROM feature.price_values pv USING feature.price_points pp
WHERE pv.feature_id=pp.feature_id
  AND pv.observed_at < now() - (pp.retention_days * interval '1 day');

-- orphan source_records
DELETE FROM provider_sync.source_records sr
WHERE NOT EXISTS (SELECT 1 FROM provider_sync.source_links sl WHERE sl.source_record_key=sr.source_record_key)
  AND (sr.expires_at IS NULL OR sr.expires_at < now() - interval '30 days');
```

## 8. Alembic 마이그레이션 가이드

### 8.1 환경 설정

`alembic/env.py`에서:

```python
from krtour.map.infra.models import metadata as target_metadata

# search_path 강제
def run_migrations_online():
    connectable = ...
    with connectable.connect() as connection:
        connection.execute(text("SET search_path = public, x_extension"))
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

### 8.2 backward-compatible 우선

1. **컬럼 추가** — nullable + default. 별도 마이그레이션에서 백필 후 NOT NULL
   tighten.
2. **인덱스 추가** — `CREATE INDEX CONCURRENTLY` (운영 중 lock 회피). Alembic
   `op.execute()`로 직접 SQL 작성 (autogen은 CONCURRENTLY 모름).
3. **인덱스 삭제** — `DROP INDEX CONCURRENTLY IF EXISTS`.
4. **컬럼 타입 변경** — `USING` cast + downtime 또는 새 컬럼 + 백필 + swap.

### 8.3 마이그레이션 net 검증

```python
# tests/integration/test_alembic_upgrade_head.py
@pytest.mark.integration
async def test_alembic_upgrade_then_downgrade_then_upgrade(pg_engine):
    await alembic_upgrade(pg_engine, "head")
    await alembic_downgrade(pg_engine, "base")
    await alembic_upgrade(pg_engine, "head")
    # schema가 idempotent
```

### 8.4 명명 규약

실제 저장소 컨벤션: **`NNNN_<descriptive_name>.py`** (4자리 순번 + 설명).

```
alembic/versions/0001_initial_schemas_and_extensions.py   # revision id: 0001_initial
alembic/versions/0002_features_and_source_tables.py       # revision id: 0002_features_source
alembic/versions/0003_feature_consistency_reports.py      # revision id: 0003_consistency_reports
alembic/versions/0004_fix_source_links_role_check.py      # revision id: 0004_fix_source_role_check
```

- **파일명과 revision id가 반드시 동일할 필요는 없다** (위 4건 모두 파일명은
  서술형 길게, revision id는 짧게). `down_revision`은 revision **id**로 잇는다.
- 4자리 순번(`0001`~)으로 적용 순서를 가시화한다.
- revision message(파일 docstring 첫 줄)는 commit summary와 일치시킨다.

## 9. EXPLAIN 통합 테스트

모든 hot path SQL은 `tests/integration/`에서 EXPLAIN 결과로 인덱스 사용 검증.
자세한 패턴은 `docs/performance.md` §10 + `docs/test-strategy.md` §4.2.

차단 사유:
- `Seq Scan on features` 검출 (10만 행 이상)
- 기대 인덱스 미사용 (e.g. `idx_features_coord_5179_gist`)

## 10. 운영 모니터링

`pg_stat_statements` extension 활성화 (`postgresql.conf`):
```
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all
```

질의:
```sql
-- top 10 slowest
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- top 10 most called
SELECT query, calls, mean_exec_time
FROM pg_stat_statements
ORDER BY calls DESC
LIMIT 10;
```

slow query log:
```
log_min_duration_statement = 1000  -- 1초 이상
```

Grafana Loki에서 LogQL로 추적 (TripMate 측 wiring).

## 11. 백업 / 복구

```bash
# 일 1회 custom format (SPEC V8 v8_0)
pg_dump --format=custom --no-owner --no-privileges \
        --schema=feature --schema=provider_sync --schema=ops \
        krtour_map > /backup/krtour_map_$(date +%F).dump

# PITR: wal-g + BackBlaze B2 (TripMate 측 운영)
```

복구:
```bash
pg_restore --no-owner --no-privileges -d krtour_map_new krtour_map_2026-05-24.dump
```

## 12. 운영 체크리스트 (Sprint 5 진입 전)

- [ ] 모든 hot path SQL에 EXPLAIN 통합 테스트
- [ ] `pg_stat_statements` 활성화 + Grafana 패널
- [ ] `log_min_duration_statement=1000` 설정
- [ ] `pg_dump` cron + retention 7일
- [ ] `VACUUM ANALYZE` cron + autovacuum 튜닝 (Odroid 임계값은 SPEC V8 v8_0)
- [ ] BRIN 인덱스 효율 측정 (1주 운영 후)
- [ ] 인덱스 hit ratio 95%+ 확인
- [ ] 부분 인덱스 vs 전체 인덱스 디스크 비교
- [ ] Alembic upgrade/downgrade round-trip 통합 테스트 통과
