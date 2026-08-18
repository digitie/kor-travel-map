# postgres-schema.md — PostgreSQL 스키마 reference 카탈로그

본 문서는 `docs/architecture/data-model.md`의 DDL을 빠른 참조용 카탈로그로 정리한다. 모든 표준
table/column/index/constraint를 한눈에. 자세한 의미·근거·인덱스 설계는
`docs/architecture/data-model.md`와 `docs/architecture/performance.md`를 본다.

> 본 문서는 **참조 카드**다. DDL 원본은 `docs/architecture/data-model.md`. 둘이 충돌하면
> `data-model.md`가 정답.

> **T-VN-36 final head 주의**: 아래의 `data_origin`/`data_version`,
> `feature.feature_versions`, `ops.feature_change_requests` 설명은 T-VN-36D 이전 bridge의
> 이력이다. final schema에서는 모두 물리 삭제됐고, field registry·provider base lineage·active
> `ops.feature_overrides`가 effective 값의 유일한 정본이다. executable 확인은
> `contracts/vnext/tvn36-post-cutover-invariants-v1.sql`과 Alembic `0104`를 따른다.

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
| `feature` | feature 도메인 본체 + 큐레이션 collection/item overlay | 핵심 14+ |
| `provider_sync` | provider entity/current payload + immutable 이력 + sync state | 4 |
| `ops` | 운영 (작업 큐, 검수, 정합성, 사용자 변경 요청, api 로그) | 17 |
| `x_extension` | 확장 (postgis 등) | extensions only |

## vNext 목표 schema (미구현, 재설계 정본 §3)

아래는 ADR-067~075가 고정한 **목표 구조**다. 번호가 붙은 §3 이하는 현재 `main`의 현행 catalog이며,
T-VN-31 target freeze와 각 shadow migration이 완료되기 전에는 목표 이름을 현재 DDL로 오해하지
않는다. 기존 계약 보존보다 정본 단일화와 DB 무결성을 우선하되, live PinVi 전환은 ADR-075의
consumer-first/write-fence 절차를 따른다.

| schema.object | 목표 책임과 핵심 제약 | 전환 task |
|---|---|---|
| `provider_sync.provider_datasets` | DB 소유 provider×dataset identity/capability; 자연 identity UNIQUE | T-VN-33 |
| `provider_sync.source_entities` | `provider_dataset_id` + source-native identity UNIQUE; 검증된 current head | T-VN-33 |
| `provider_sync.source_records` | entity FK 아래 immutable payload/hash/known time; denormalized provider identity 없음 | T-VN-33 |
| `feature.features` | UUID PK, 공통 필드, category FK, 3축 상태, `row_revision`; mutable 속성은 identity 입력 아님 | T-VN-32·34 |
| `feature.feature_aliases` | legacy `f_*` → UUID의 명시적 alias; 전환/복구용 | T-VN-32 |
| `feature.feature_{point,event,notice,route,area}_*` | core와 1:1 typed subtype; geometry type/SRID·kind 일치 CHECK/FK | T-VN-35·37 |
| `feature.public_features` | `active AND published AND valid` 단일 공개 projection | T-VN-04·34 |
| `ops.feature_overrides` + effective projection | `(feature_id, field_path)` active UNIQUE; provider base와 override 분리 | T-VN-36 |
| weather facts/current summary | `target_at`/`known_at`, native semantic UNIQUE, range/FK; current는 재생성 가능한 projection | T-VN-17·38 |
| domain command ledgers/outbox | `(principal, operation, Idempotency-Key)` replay, body fingerprint, 저장 결과, generation/restore epoch, 멱등 relay | T-VN-12·41 |
| `feature.curation_collections/items` | 유일한 curation write 정본; legacy flat writer/trigger 없음 | T-VN-40 |

정규화가 기본이며 JSONB는 provider 원문과 확장 metadata에만 쓴다. 모든 FK 참조 열은 실제 join
계획에 필요한 인덱스를 갖고, 공간 열은 subtype에 맞는 SRID/type을 강제한다. GiST·BRIN은
[`performance.md`](performance.md)의 실측 gate를 통과한 hot path에만 둔다. DDL 적용 방식과
rollback 조건은 ADR-075와 [`../deploy.md`](../deploy.md)를 따른다.

## 3. 현행 테이블 카탈로그 (alphabetical by schema)

### 3.1 `feature.*`

| 테이블 | PK | 핵심 컬럼 / 비고 |
|--------|----|---------------|
| `features` | `feature_id` | kind/name/category/coord/coord_precision_digits/coord_5179(generated)/address/legal_dong_code/marker_*/parent/sibling_group_id/raw_refs/status/data_origin/data_version/user_change_*; `UNIQUE (feature_id, kind)`는 아래 subtype 배타 arc의 참조 대상. kind별 detail과 선·면 geometry는 core에 없고 typed subtype이 정본이다 (ADR-086) |
| `feature_places` | `feature_id` | place_kind (NOT NULL), phones `text[]` (≤3), biz_number, license_date, business_hours, facility_info, reviews_link, payload |
| `feature_events` | `feature_id` | event_kind (NOT NULL), starts_on/ends_on (CHECK), timezone, opening_hours, venue_name, tel, content_id, content_type_id, area_code, sigungu_code, payload |
| `feature_notices` | `feature_id` | notice_type (NOT NULL), severity (0-5 CHECK), valid_start/end_time `timestamptz`, source_agency, officer_name, payload |
| `feature_routes` | `feature_id` | geom `MULTILINESTRING(4326)` NOT NULL, route_type (NOT NULL), geometry_source/status, total_distance_meters, expected_duration_minutes, difficulty, begin_*/end_*, payload |
| `feature_areas` | `feature_id` | geom `MULTIPOLYGON(4326)` NOT NULL, area_kind (NOT NULL), boundary_source, area_square_meters, regulation_scope, administrative_office, description, payload |
| `features_detailed` (view) | — | core + subtype 5종에서 `detail`/`geom`을 조립하는 단일 정본. `public_features`는 이 뷰 위의 `active AND deleted_at IS NULL` projection이다 |
| `feature_versions` | `(feature_id, version)` | provider version 0과 user_request version 1 snapshot 보존; payload JSONB |
| `feature_files` | `file_id` | feature_id FK CASCADE; UNIQUE (storage_backend,bucket,object_key); file_type CHECK |
| `feature_opening_periods` | `(feature_id, period_index)` | start_weekday (0-6), start_time (HHMM regex), duration_minutes (1~10080) |
| `feature_special_days` | `(feature_id, special_date)` | is_closed, periods JSONB |
| `feature_weather_values` | `weather_value_key` | immutable fact; canonical `provider_dataset_id`와 non-null source entity/record revision, `target_at`/`known_at`를 가진다. UNIQUE (feature_id,provider_dataset_id,weather_domain,forecast_style,metric_key,target_at,source_record_key) |
| `current_weather_summary` | `(feature_id,provider_dataset_id,weather_domain,forecast_style,metric_key)` | 값을 복제하지 않는 current fact pointer; selected fact와 successful projection receipt를 복합 FK로 참조하고 `refresh_after`를 보관한다 |
| `feature_price_values` | `price_value_key` | immutable fact; canonical `provider_dataset_id`와 non-null source entity/record revision, `observed_at`/`known_at`; UNIQUE (feature_id,provider_dataset_id,price_domain,product_key,observed_at,source_record_key) |
| `current_price_summary` | `(feature_id,provider_dataset_id,price_domain,product_key)` | 값을 복제하지 않는 current fact pointer; selected fact와 successful projection receipt를 복합 FK로 참조한다 |
| `curation_collections` | `collection_id UUID` | UNIQUE collection_key; theme/source/title/edition/status/visibility; legacy key는 theme/source UUID+title hash, 중복 group은 split identity; created_by/updated_by |
| `curation_items` | `curation_item_id UUID` | collection FK; nullable·mutable feature_id; current import row/accepted decision exact pointer; external item+component stable identity; source 누락·재등장과 운영자 tombstone 이력 |
| `curation_import_batches` | `import_batch_id UUID` | content SHA-256, csv/normalized/recovery 종류, 행 수, actor, imported_at의 append-only receipt |
| `curation_import_rows` | `import_row_id UUID` | batch/item FK; 원 행 번호·canonical row SHA-256·normalized payload·구조화 provenance |
| `curation_link_decisions` | `decision_id UUID` | item/target, accepted/revoked, explicit/admin/legacy/recovery basis, resolver version, evidence, actor/time, supersedes chain |

0045 큐레이션 write는 다음 불변식을 지킨다.

- actor 값은 인증된 admin proxy context에서만 받고 collection/item 양쪽에 감사값을 남긴다.
  public projection에서는 이 필드를 제거하고 admin projection에서만 반환한다.
- public link는 item의 `accepted_link_decision_id`가 같은 item·Feature를 가리키고 basis가
  `legacy_unattributed`가 아닌 경우에만 승인한다. migration 0072는 기존 link를 근거 있는
  승인으로 추정하지 않고 legacy 감사 대상으로 backfill한다.
- import는 성공 batch와 각 normalized row를 append-only로 기록한다. item의
  `current_import_row_id`와 `accepted_link_decision_id`는 composite deferrable FK로 exact
  item/target을 강제한다. 세 history table의 immutable trigger는 직접 `UPDATE`/`DELETE`를
  거부하고 batch→row FK도 `RESTRICT`한다. decision의 import row와 supersedes target은
  같은 item만 허용하며 self-supersede를 거부한다.
- 선택적 `forward_recovery`와 Feature merge는 이미 non-legacy accepted인 link만 새
  decision으로 재승인한다. legacy/NULL/revoked link는 공개 불가 상태를 유지한다. duplicate
  loser source가 이기면 survivor 소유 merge row를 append해 projection/current pointer를
  함께 전진시키고 loser item은 물리 삭제하지 않는다.
- 수동 item 추가·수정·보관은 parent collection row를 먼저 잠그고 collection의
  `updated_by`/`updated_at`도 함께 갱신한다.
- CSV authoritative replace는 transaction advisory lock으로 직렬화한 뒤 대상 collection을
  UUID 순서로 `FOR UPDATE`한다. source에서 빠진 item은 삭제 대신 `source_present=false`로
  보존하고, 재등장 시 제공자 파생 필드만 갱신해 운영자 `status`·relation·reuse override를
  유지한다. 운영자가 보관한 exact identity tombstone은 자동 재생성하지 않는다. dry-run은
  쓰기 없이 source 누락 예정 item까지 계산하며, 동일 CSV를 다시 반영하면 모든 변경 수가
  0이고 관련 `updated_at`도 바뀌지 않는다.
- source item과 펼쳐진 membership component를 분리한다. exact identity는
  `(collection_id, external_item_id, external_component_id)`이고 Feature 연결은 변경 가능한
  target이다. 같은 source item의 연결·미연결 component 공존은 허용하되, active component가
  동일 non-null Feature를 중복 참조하는 것은 partial unique로 차단한다.
- 0064→0066 연속 migration은 0065의 지연 FK·sync trigger event를 0066 backfill 직후
  `SET CONSTRAINTS ALL IMMEDIATE`로 검사·소진한 뒤 DDL을 수행한다. 실패하면 같은 Alembic
  transaction 전체가 원자적으로 중단된다.
- source 파생 변경은 `source_updated_at`, 운영자 상태·relation·reuse 변경은
  `operator_updated_at`/`operator_updated_by`로 독립 기록한다. Feature merge는 이 두
  revision으로 각 필드군 승자를 따로 정하고, 먼저 영향 collection을 UUID 순서로 잠가
  import/admin writer와 같은 parent→child lock order를 지킨다. 운영 중 revision은 실제 쓰기
  순서를 보존하도록 `clock_timestamp()`로 기록한다.
- 전환기 legacy `curated_features`도 operator provenance를 소유한다. legacy↔canonical
  동기화는 provenance가 전진한 필드군만 반영하고, 안정적인 source identity의 DELETE→새 UUID
  재삽입은 기존 source-absent membership을 복원한다. source record가 없어도 durable external
  identity를 재사용하며 archived tombstone은 항상 우선한다.
  Feature merge가 충돌 해소용으로 archive한 detached legacy projection은 이후 trigger source가
  될 수 없다.
- legacy cross-title 이동은 target collection을 잡은 뒤 source parent를 역순 잠그지 않고
  `curation_items` row만 잠근다. migration 0065는 과거 mutable slug 재사용으로 탈취된
  active/archived projection을 명시적 `legacy_projection_id`로 자동 복구한다. durable owner link가
  없는 canonical-only item은 external identity가 일치해도 추정하지 않고 모든 legacy-marker
  collection에서 `draft/admin_only` quarantine에 보존한다. upgrade 전 old projection이 삭제된
  경우도 같은 규칙을 적용한다. mutable metadata marker가 지워진 이력은 immutable `legacy:`
  collection key namespace를 함께 검사해 우회를 막는다.
  migration 생성 exact `legacy:quarantine:<UUID>` key와 immutable
  `created_by='migration:0065'` 결합만 재격리 대상에서 제외해 왕복 identity를 보존한다. 과거
  `quarantine:` theme slug가 만든 정상 legacy key는 제외하지 않는다. quarantine metadata에
  `migrated_from`이 추가돼도 upgrade·downgrade stable-key rewrite는 generated 결합만 제외한다.
- 0045 downgrade는 구 flat overlay로 재구성할 수 없는 신규·수정 데이터나 감사값이 있으면
  `P0001`로 중단한다. export 또는 명시적 정리 없이 풍부한 데이터를 삭제하지 않는다.
- 0044 downgrade는 연결된 source entity에 immutable record가 둘 이상이면 구 record별
  link metadata를 정확히 복원할 수 없으므로 `P0001`로 중단한다.

### 3.2 `provider_sync.*`

| 테이블 | PK | 핵심 컬럼 / 비고 |
|--------|----|---------------|
| `source_entities` | `source_entity_key` | **legacy(0087 이전)** UNIQUE(provider,dataset_key,type,id), current pointer. T-VN-33 최종형은 provider_dataset_id FK와 head 분리 |
| `source_records` | `source_record_key` | **legacy(0087 이전)** denormalized pair/raw-derived row. T-VN-33 최종형은 entity FK 아래 immutable payload/hash |
| `source_links` | `(feature_id, source_entity_key)` | T-VN-33 최종형은 source_role만 primary 정본으로 사용 |
| `provider_sync_state` | `(provider_dataset_id, sync_scope)` | T-VN-33 target: dataset FK, status/cursor/last success/next run |

### 3.3 `ops.*`

| 테이블 | PK | 핵심 컬럼 / 비고 |
|--------|----|---------------|
| `import_jobs` | `job_id UUID` | kind, `load_batch_id`, `parent_job_id` self-FK, payload, status/progress, heartbeat, `dagster_run_id`; 0051은 provider/dataset exact pair·trigger·registry/raw status, 0052는 격리 표식, 0053은 direct update job의 effective `sync_scope`와 `dispatch_requested_at`을 추가한다 |
| `pipeline_cancellation_members` | `(cancellation_id, job_id)` | frozen import job 결과; `job_id → ops.import_jobs(job_id) ON DELETE RESTRICT`, `operation_kind`, `requires_run_termination`으로 run-backed queued와 generic queued를 구분 |
| `pipeline_cancellation_runs` | `(cancellation_id, dagster_run_id)` | run terminate reservation/result 정본; 0051은 authoritative nullable `engine_started_at`/`engine_finished_at`을 terminal observation과 함께 영속 |
| `c6c_cancel_probe_fixtures` | `transaction_id UUID` | **T-VN-41F1J 목표(ADR-086)** — Map-owned C6c fixture; unique job/cancellation FK와 `armed|consumed|finalized` CHECK로 cancellation history를 보존한 lifecycle을 강제 |
| `dedup_review_queue` | `review_id UUID` | feature_id_a < feature_id_b canonical pair UNIQUE, total_score/name/spatial/category (0-100), status, decision_reason |
| `feature_overrides` | `override_id UUID` | **구현됨(alembic 0010, ADR-045 T-207c)** — feature_id FK, field_path, source_value/override_value JSONB, prevent_provider_reactivation, status |
| `feature_merge_history` | `merge_id UUID` | master_feature_id FK, loser_feature_id FK (둘 다 CASCADE), score, review_id FK (SET NULL), merged_by, reason, merged_at (alembic 0007, ADR-016) |
| `integrity_observation_scopes` | `(provider, dataset_key)` | migration 0071; scope별 `latest_generation`과 `latest_authoritative_generation` monotonic close fence |
| `integrity_observation_runs` | `observation_run_id BIGINT IDENTITY` | scope FK; external run UNIQUE, generation UNIQUE, collecting/authoritative/superseded 상태와 source/finding receipt |
| `integrity_finding_observations` | `(observation_run_id, dedupe_key)` | run FK CASCADE; run이 실제 관측한 `av2_<sha256>` 집합을 payload와 분리해 불변 저장 |
| `data_integrity_violations` | `issue_id UUID` | **구현됨(alembic 0009, ADR-045 T-205c)** — provider/dataset/source_record/feature 연결, violation_type, severity (info/warning/error/critical), payload, status |
| `poi_cache_targets` | `target_id UUID` | **구현됨(alembic 0009+0053, ADR-045 T-205c)** — trimmed non-empty 112자 이하 external_system+target_key active UNIQUE, lon/lat, coord/coord_5179, radius_km, refresh_policy, provider_overrides, soft delete |
| cache target source control/head/event | source/natural/event identity | **T-VN-41 producer foundation 목표(ADR-081)** — Map-owned positive restore epoch, durable natural-key generation+tombstone, immutable source replay ledger |
| cache target result outbox/delivery | event/relay/claim identity | **T-VN-41 producer foundation 목표(ADR-081)** — same-transaction typed outbox, global delivery order, lease/retry/dead/replay와 contiguous ACK |
| `poi_cache_target_feature_links` | `(target_id, feature_id)` | **구현됨(alembic 0009, ADR-045 T-205c)** — target 주변 feature link, provider/dataset, distance_m, relation, active |
| `poi_cache_target_snapshot_gc_observations` | `observation_id BIGINT IDENTITY` | **구현됨(alembic 0078, T-VN-41C)** — acquired Dagster run UNIQUE, referenced count, immutable 직전 acquired/growth baseline copy, eligible 승격과 run별 최소 간격; 기본 90일 파생 관측 |
| `provider_refresh_policies` | `(provider, dataset_key)` | **구현됨(alembic 0009 + 0049, ADR-045 T-205c)** — source_kind, targeted_policy, interval/rate-limit/max_concurrent, 명시적 `stale_after_minutes`, rate_limit_source, enabled |
| `api_call_log` | `id BIGSERIAL` | provider, endpoint, status, latency_ms, occurred_at; BRIN(occurred_at) |
| `feature_consistency_reports` | `report_id UUID` | ADR-033 Phase 1; batch_id, started_at/finished_at, severity_max CHECK(OK/WARN/ERROR), cases/summary JSONB |
| `feature_update_requests` | `request_id UUID` | **구현됨(alembic 0008+0052+0053)** — immutable requested scope/filter/policy/run mode/priority/audit, mutable `matched_scope`, 양수 `generation`, non-null canonical `job_id` RESTRICT FK. status/Dagster/cancellation/error/timeline/effective scope/dispatch는 linked job 단일 정본이다 |
| `feature_change_requests` | `request_id UUID` | **구현됨(alembic 0021)** — place/event 사용자 요청 add/update/delete queue. review_mode(require_review/immediate), state(pending/applied/rejected), payload JSONB, reviewer/applied timestamp |
| `current_summary_runs` | `summary_run_id BIGINT IDENTITY` | T-VN-38 weather/price ingest·reconcile·backfill·restore receipt. terminal receipt immutable, `(summary_run_id,projection_kind,status)`가 current pointer의 successful receipt FK target |

## 4. 인덱스 카탈로그

`ops.poi_cache_target_snapshot_gc_observations`는 retention scan용
`idx_cache_target_snapshot_gc_observations_time(observed_at)`와 마지막 적격 기준선 탐색용 partial
`idx_cache_target_snapshot_gc_observations_growth_baseline(observation_id) WHERE growth_baseline_eligible`
를 가진다. count는 0 이상, 최소 간격은 1~86,400초이며 직전 acquired와 growth baseline의 각 네
컬럼은 모두 NULL이거나 모두 채워져야 한다. 첫 관측만 growth baseline 없이 eligible일 수 있고,
그 밖의 `growth_baseline_eligible`은 DB가 `observed_at > growth baseline`,
`observed_at > previous acquired` 및 최소 간격 식과 일치하도록 강제한다.
앱 rollback은 0078 DB를 보존하고 forward
recovery하며, 명시적 0077 downgrade는 파생 관측 테이블을 버리고 0078 재-upgrade가 빈 표본부터 재개한다.

### 4.1 `feature.features`

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_features_coord_gist` | GIST(coord) | partial WHERE deleted_at IS NULL |
| `idx_features_coord_5179_gist` | GIST(coord_5179) | 반경 검색 핵심 (ADR-012). STORED 값 PROJ drift·REINDEX: [runbook](../runbooks/coord-5179-proj-pin.md) (T-VN-H04) |
| `idx_features_kind_category` | (kind, category) | partial active |
| `idx_features_status_updated` | (status, updated_at) | admin |
| `idx_features_dedup_refresh_keyset` | (updated_at DESC, feature_id DESC) | partial active+coord, dedup refresh paging |
| `idx_features_legal_dong_code` | (legal_dong_code) | 행정구역 필터 |
| `idx_features_sigungu` | (sigungu_code, kind) | partial active |
| `idx_features_parent` | (parent_feature_id) | partial NOT NULL |
| `idx_features_sibling` | (sibling_group_id) | partial NOT NULL |
| `idx_features_name_trgm` | GIN(name gin_trgm_ops) | pg_trgm 부분 문자열 |
| `idx_features_data_origin` | (data_origin, data_version) | provider/user_request effective row 필터 |
| `idx_features_user_deleted` | (user_deleted_at) | partial user_deleted_at IS NOT NULL |

kind별 필터·geometry 인덱스는 core가 아니라 subtype이 갖는다 (§4.4).

### 4.1.1 `feature.feature_versions`

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_feature_versions_request` | (request_id) | 사용자 변경 요청에서 snapshot 역추적 |

### 4.1.2 `feature.curation_*`

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_curation_collections_theme_status_edition` | (theme_id, status, edition_key, collection_id) | 테마·공개 회차 목록 |
| `idx_curation_collections_source_status` | (source_id, status, collection_id) | 출처별 collection 목록 |
| `uq_curation_items_component_identity` | UNIQUE (collection_id, external_item_id, external_component_id) | active·source 누락·archived tombstone을 통틀어 stable component 1행 강제 |
| `uq_curation_items_active_source_feature` | UNIQUE (collection_id, external_item_id, feature_id) WHERE source_present AND archived_at IS NULL AND feature_id IS NOT NULL | 한 source item의 current active component가 동일 Feature를 중복 참조하지 못하게 함 |
| `idx_curation_items_collection_status_order` | (collection_id, source_present, status, sort_order, curation_item_id) | source에 존재하는 collection 상세 정렬 |
| `idx_curation_items_feature_status_collection` | (feature_id, source_present, status, collection_id) | source에 존재하는 Feature별 큐레이션 조회 |

collection 목록 API는 `updated_at DESC, collection_id DESC` keyset cursor를 사용하고
`page_size`를 최대 500으로 제한한다. Feature group 목록은 먼저 `feature_id` key를 page한 뒤
membership을 batch로 붙여 fan-out이 page 경계를 바꾸지 않게 한다.

### 4.2 `provider_sync.*`

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_source_entities_current_record` | (current_source_record_key) | **legacy**; T-VN-33 head 분리로 제거 |
| `idx_source_records_provider_dataset_entity` | (provider, dataset_key, source_entity_type, source_entity_id) | **legacy**; entity→dataset join으로 교체 |
| `idx_source_records_entity_history` | (source_entity_key, fetched_at DESC, imported_at DESC, source_record_key DESC) | T-VN-33 immutable payload 이력 cursor |
| `idx_source_records_imported_at_brin` | BRIN(imported_at) | 시계열 |
| `idx_source_records_fetched_at_brin` | BRIN(fetched_at) | |
| `idx_source_records_last_seen_at_brin` | BRIN(last_seen_at) | **legacy**; re-observation은 head.observed_at |
| `idx_source_records_expires_at` | (expires_at) | **legacy**; expiry는 head 소유 |
| `idx_source_links_entity` | (source_entity_key) | entity→Feature 역조회 |
| `idx_source_links_role` | (source_role) | |
| `idx_source_links_primary` | (feature_id) | `source_role = 'primary'` partial predicate |
| `idx_sync_state_next_run` | (next_run_after) | partial status='active' |

### 4.3 `feature.feature_files`

| 인덱스 | 컬럼 |
|--------|------|
| `idx_feature_files_feature_type` | (feature_id, file_type) |
| `idx_feature_files_feature_order` | (feature_id, display_order) |
| `idx_feature_files_provider` | (provider, dataset_key) partial NOT NULL |

### 4.4 kind별 subtype / 영업시간

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_feature_places_opening_hours` | (feature_id) | partial `business_hours IS NOT NULL` |
| `idx_feature_events_period` | (starts_on, ends_on) | 공개 festival 범위·keyset·정렬이 `starts_on` 선두를 요구 |
| `idx_feature_events_opening_hours` | (feature_id) | partial `opening_hours IS NOT NULL` |
| `idx_feature_notices_validity` | (valid_end_time, valid_start_time) | typed `timestamptz` 유효기간 필터 |
| `idx_feature_routes_geom_gist` | GIST(geom) | route MULTILINESTRING 교차 |
| `idx_feature_areas_geom_gist` | GIST(geom) | area MULTIPOLYGON 교차/포함 |

subtype 테이블 자체가 kind로 갈리므로 `WHERE kind=...` 부분 조건이 필요 없다. 공간 술어는
조립 뷰(`features_detailed`)의 산출 `geom`이 아니라 GiST가 붙은 subtype을 직접 참조해야 한다.

| 테이블 | 인덱스 |
|--------|--------|
| `feature_opening_periods` | (start_weekday, start_time) |
| `feature_special_days` | (special_date) |

### 4.5 weather/price current projection

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `uq_weather_value_identity` | UNIQUE(feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key, target_at, source_record_key) | immutable weather fact identity |
| `idx_weather_values_feature_target_known` | (feature_id, target_at DESC, known_at DESC) | timeline/current candidate 접근 |
| `uq_weather_value_summary_reference` | UNIQUE(weather fact key + summary natural identity) | summary→fact composite FK target |
| `pk_current_weather_summary` | (feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key) | current pointer natural identity |
| `uq_price_value_identity` | UNIQUE(feature_id, provider_dataset_id, price_domain, product_key, observed_at, source_record_key) | immutable price fact identity |
| `idx_price_values_feature_observed_identity` | (feature_id, observed_at DESC, known_at DESC, provider_dataset_id, price_domain, product_key) | feature별 immutable history |
| `uq_price_value_summary_reference` | UNIQUE(price fact key + summary natural identity) | summary→fact composite FK target |
| `pk_current_price_summary` | (feature_id, provider_dataset_id, price_domain, product_key) | current pointer natural identity |
| `idx_current_{weather,price}_summary_fact` | selected fact key | fact purge/cascade와 pointer 역추적 |
| `idx_current_summary_runs_projection_finished` | (projection_kind, finished_at DESC) partial succeeded | rebuild receipt 조회 |

### 4.6 ops

| 인덱스 | 컬럼 | 비고 |
|--------|------|------|
| `idx_import_jobs_status` | (status, created_at) | scheduler |
| `idx_import_jobs_kind_status` | (kind, status, created_at DESC) | admin |
| `idx_import_jobs_heartbeat` | (heartbeat_at) | partial status='running' |
| `idx_import_jobs_load_batch_created` | (load_batch_id, created_at DESC, job_id DESC) | partial `load_batch_id IS NOT NULL`, T-200 batch 조회 |
| `idx_import_jobs_parent_created` | (parent_job_id, created_at DESC, job_id DESC) | partial `parent_job_id IS NOT NULL`, root/child 조회 |
| `idx_import_jobs_dagster_run_id` | (dagster_run_id) | partial `dagster_run_id IS NOT NULL`, `/ops/live` dagster run 연결 조회 (alembic 0048) |
| `uq_import_jobs_feature_run` | UNIQUE (dagster_run_id) | partial feature-load run root, Dagster run 멱등성 (0051) |
| `uq_import_jobs_feature_run_pair` | UNIQUE (parent_job_id, provider, dataset_key) | partial feature-load pair child 멱등성 (0051) |
| `idx_import_jobs_provider_dataset_created` | (provider, dataset_key, created_at DESC, job_id DESC) | exact pair timeline/latest (0051) |
| `idx_import_jobs_dataset_created` | (dataset_key, created_at DESC, job_id DESC) | dataset-only timeline/latest (0051) |
| `idx_import_jobs_provider_created` | (provider, created_at DESC, job_id DESC) | provider-only timeline/latest (0051) |
| `idx_import_jobs_quarantined` | (quarantined_at DESC, job_id DESC) WHERE quarantined_at non-NULL | 격리 component 감사 조회 (0052) |
| `uq_import_jobs_active_feature_update_scope` | UNIQUE (provider, dataset_key, sync_scope) | queued/running direct feature update canonical 작업의 effective scope 유일성 (0053) |
| `idx_import_job_events_time` | (occurred_at DESC, event_id DESC) WHERE `quarantined_at IS NULL` | 무필터 감사 polling (0052) |
| `idx_import_job_events_job_time` | (job_id, occurred_at DESC, event_id DESC) WHERE `quarantined_at IS NULL` | job 감사 타임라인과 bounded live snapshot (0052에서 partial 전환) |
| `idx_import_job_events_provider_time` | (provider, occurred_at DESC, event_id DESC) WHERE provider non-NULL AND `quarantined_at IS NULL` | provider-only 감사 타임라인 (0052에서 partial 전환) |
| `idx_import_job_events_provider_dataset_time` | (provider, dataset_key, occurred_at DESC, event_id DESC) WHERE pair non-NULL AND `quarantined_at IS NULL` | exact pair 감사 타임라인 (0052, identity projection에는 사용 금지) |
| `idx_import_job_events_level_time` | (level, occurred_at DESC, event_id DESC) WHERE `quarantined_at IS NULL` | level 감사 타임라인 (0052에서 partial 전환) |
| `idx_import_job_events_provider_dataset_scope_time` | (provider, dataset_key, sync_scope, occurred_at DESC, event_id DESC) WHERE pair/scope non-NULL AND `quarantined_at IS NULL` | canonical exact-scope 감사 타임라인 (0057; dataset-only 인덱스 대체) |
| `idx_feature_update_providers_gin` | GIN(providers) | request provider `TEXT[]` membership selective seed (0052) |
| `idx_feature_update_dataset_keys_gin` | GIN(dataset_keys) | request dataset `TEXT[]` membership selective seed (0052) |
| `uq_feature_update_requests_job_id` | UNIQUE (job_id) | request→job 유일성과 역추적 B-tree; deferred 양방향 trigger와 함께 canonical 1:1 보장 (0052) |
| `idx_dedup_status_score` | (status, total_score DESC) | partial pending |
| `idx_overrides_feature` | (feature_id, status) | |
| `idx_overrides_field` | (field_path) | |
| `idx_merge_history_master` | (master_feature_id, merged_at DESC) | |
| `idx_merge_history_loser` | (loser_feature_id) | "이 feature가 어디로 병합됐나" 역추적 |
| `idx_integrity_observation_runs_scope_status` | (provider, dataset_key, status, generation DESC) | scope별 collecting/authoritative run 감사 |
| `idx_integrity_finding_observations_key_run` | (dedupe_key, observation_run_id) | stale sweep의 current/newer generation anti-join |
| `idx_violations_type_status` | (violation_type, status) | |
| `idx_violations_feature` | (feature_id) | partial NOT NULL |
| `idx_violations_detected_brin` | BRIN(detected_at) | |
| `idx_api_call_occurred_brin` | BRIN(occurred_at) | |
| `idx_api_call_provider_time` | (provider, occurred_at DESC) | |
| `idx_reports_batch` | (batch_id) | feature_consistency_reports (ADR-033) |
| `idx_reports_started` | (started_at DESC) | feature_consistency_reports |
| `idx_feature_change_state_created` | (state, created_at DESC, request_id DESC) | pending/applied/rejected 목록 |
| `idx_feature_change_feature` | (feature_id) | feature별 사용자 변경 요청 |

## 5. CHECK constraint 카탈로그

| 테이블 | 제약 | 정의 |
|--------|------|------|
| `features` | `ck_features_kind` | kind ∈ FeatureKind 7종 |
| `features` | `ck_features_status` | status ∈ FeatureStatus 6종 |
| `features` | `ck_features_data_origin` | provider/user_request |
| `features` | `ck_features_data_version` | ≥ 0 |
| `features` | `ck_features_user_change_kind` | NULL 또는 add/update/delete |
| `features` | `ck_features_user_change_status` | NULL 또는 pending/applied/rejected |
| `features` | `ck_features_coord_pair` | coord NULL이거나 한국 영역 안 (lon 124-132, lat 33-39.5) |
| `feature_versions` | `ck_feature_versions_version` | ≥ 0 |
| `feature_versions` | `ck_feature_versions_origin` | provider/user_request |
| `feature_versions` | `ck_feature_versions_change_kind` | load/add/update/delete |
| `curation_collections` | `ck_curation_collections_status` | draft/published/archived |
| `curation_collections` | `ck_curation_collections_visibility` | admin_only/public |
| `curation_items` | `ck_curation_items_status` | candidate/included/rejected/archived |
| `curation_items` | `ck_curation_items_sort_order` | ≥ 0 |
| `curation_items` | `ck_curation_items_relation` | primary_stop/food_stop/cafe_stop/bookstore_stop/nearby_option/accessibility_support/pet_support/family_support/theme_area_anchor |
| `curation_items` | `ck_curation_items_reuse_policy` | allowed/blocked/manual_review |
| `curation_items` | `ck_curation_items_external_component_id_canonical` | component key는 trimmed non-empty |
| `curation_items` | `uq_curation_items_component_identity` | `(collection_id, external_item_id, external_component_id)` exact identity 중복 금지 |
| `curation_items` | `uq_curation_items_active_source_feature` | active non-null Feature target 중복 금지 |
| `feature_files` | `ck_feature_files_file_type` | image/video/audio/document/file |
| `feature_files` | `ck_feature_files_display_order` | ≥ 0 |
| `feature_files` | `ck_feature_files_byte_size` | NULL or ≥ 0 |
| `feature_files` | `ck_feature_files_width/height` | NULL or > 0 |
| `features` | `uq_features_identity_kind` | `(feature_id, kind)` — subtype 배타 arc의 참조 대상 |
| `feature_{places,events,notices,routes,areas}` | `ck_feature_*_kind` | 각 subtype의 kind 상수 (`kind = 'place'` 등) |
| `feature_events` | `ck_feature_events_period` | starts_on ≤ ends_on (NULL 허용) |
| `feature_notices` | `ck_feature_notices_severity` | NULL or 0-5 |
| `feature_opening_periods` | `ck_opening_weekday` | 0-6 |
| `feature_opening_periods` | `ck_opening_time` | regex `^([01]\d|2[0-3])[0-5]\d$` |
| `feature_opening_periods` | `ck_opening_duration` | 0 < n ≤ 10080 |
| `source_links` | `ck_source_links_confidence` | 0-100 |
| `source_links` | `ck_source_links_role` | SourceRole 8종 |
| `source_entities` | `ck_source_entities_seen_order` | first_seen_at ≤ last_seen_at |
| `source_entities` | `uq_source_entities_key_dataset` | source entity key와 canonical dataset의 복합 FK target |
| `source_records` | `uq_source_records_record_entity_fetched` | immutable source revision 복합 FK target |
| `feature_weather_values` | `ck_weather_value_present` / `ck_weather_value_bitemporal_order` | 값은 하나 이상, issued_at ≤ known_at |
| `feature_weather_values` | `uq_weather_value_identity` | immutable weather fact natural identity |
| `feature_price_values` | `ck_price_value_nonnegative` | value_number ≥ 0 |
| `feature_price_values` | `uq_price_value_identity` | feature_id/dataset/domain/product/observed/source revision 중복 방지 |
| `current_summary_runs` | terminal immutable trigger + receipt state UNIQUE | rebuild/reconcile receipt를 결과 pointer와 분리 |
| `current_{weather,price}_summary` | projection kind/succeeded receipt CHECK | current pointer는 selected immutable fact와 successful run만 참조 |
| `import_jobs` | `ck_import_jobs_status` | queued/running/done/failed/cancelled |
| `import_jobs` | `ck_import_jobs_progress` | 0-100 |
| `import_jobs` | `ck_import_jobs_provider_dataset_pair` | provider/dataset 둘 다 NULL 또는 trim된 non-empty exact pair |
| `import_jobs` | `ck_import_jobs_feature_tracking_shape` | feature run root와 pair child의 parent/pair/trigger/registry/raw status shape |
| `import_jobs` | `ck_import_jobs_feature_engine_timeline` | feature root/child의 create ≤ start ≤ finish 순서(NULL 허용) |
| `import_jobs` | `ck_import_jobs_dagster_run_status` | feature run root의 raw Dagster status 허용값 |
| `import_jobs` | feature operation trigger 2종 | child parent kind/run 일치와 root/child identity update 금지 |
| `source_records` | `trg_source_record_lineage_key` | `provider_sync.notice_lineage_key(NEW)`로 `lineage_key`를 파생한다. BEFORE INSERT/UPDATE OF (raw_data, provider, dataset_key, source_entity_type, source_entity_id, **lineage_key**) — 자신을 포함해야 파생 컬럼 직접 쓰기도 되돌려진다. `ENABLE ALWAYS`라 `session_replication_role=replica`에서도 돈다 (0088) |
| `import_jobs` | `trg_import_jobs_identity_immutable` | 모든 generic/feature job의 kind/provider/dataset과 direct update effective sync scope identity는 insert 뒤 변경 금지 (0052+0053) |
| `import_jobs` | `ck_import_jobs_update_request_shape` | direct update job은 pair+trimmed non-empty sync scope, non-direct는 세 identity 컬럼 모두 NULL (0053) |
| `import_jobs` | `ck_import_jobs_dispatch_requested_at` | dispatch 시각은 feature update job에만 저장 (0053) |
| `poi_cache_targets` | `ck_poi_cache_targets_external_system_identity` | `external_system`은 trimmed non-empty 112자 이하이며 실행 scope prefix를 포함한 최종 identity는 128자 이하 (0053) |
| `import_jobs` | `ck_import_jobs_quarantine_shape` | 두 격리 컬럼이 모두 NULL이거나 시각과 고정 사유 `unlinked_feature_update_component`가 함께 존재 (0052) |
| `import_jobs` | `trg_import_jobs_quarantine_immutable` | runtime 격리 표식 생성·변경, 격리 행 UPDATE/DELETE와 격리 parent 아래 child attach 금지 (0052) |
| `import_job_events` | `quarantined_at` + `trg_import_job_events_quarantine_immutable` | 0052 migration이 parent 격리 시각을 backfill하며 runtime marker INSERT/UPDATE, 격리 job의 기존 event UPDATE/DELETE와 신규 event append를 금지 |
| `import_job_event_clock` | singleton PK/CHECK + nonnegative revision CHECK | event DML AFTER STATEMENT trigger 내부의 statement당 revision+1만 허용하는 bounded live projection; 직접 UPDATE/DELETE/TRUNCATE 금지 (0052) |
| `import_job_events` | `trg_import_job_events_clock` | INSERT/UPDATE/DELETE/TRUNCATE statement마다 event clock revision을 한 번 증가 (0052) |
| `pipeline_cancellation_members` | `trg_pipeline_cancellation_members_reject_quarantine` | 격리 job을 신규/변경 cancellation member로 연결하지 못하게 차단 (0052) |
| `feature_update_requests` | `ck_feature_update_requests_scope_shape` | immutable `ops.is_valid_feature_update_scope`로 6종 scope의 exact key/type/길이/범위·`scope.type=scope_type`을 OpenAPI와 동일하게 강제하며 cache-target `external_system`은 112자 이하 (0052+0053) |
| `feature_update_requests` | `ck_feature_update_requests_providers_shape` | 1차원 unique `TEXT[]`, 최대 32개, 각 항목 trimmed non-empty string 128자 이하를 강제 (0052) |
| `feature_update_requests` | `ck_feature_update_requests_dataset_keys_shape` | 1차원 unique `TEXT[]`, 최대 64개, 각 항목 trimmed non-empty string 128자 이하를 강제 (0052) |
| `feature_update_requests` | `ck_feature_update_requests_update_policy_shape` | `mode='refresh_existing'`와 strict boolean override 5개만 가진 sparse canonical JSON object를 강제 (0052) |
| `feature_update_requests` | `trg_feature_update_requests_job_identity` | linked kind, direct pair/effective scope, non-direct unpaired/null scope를 교차테이블로 강제 (0052+0053) |
| `pipeline_cancellation_members` | `ck_pipeline_cancellation_members_operation_kind` | nullable operation kind가 있으면 trimmed non-empty 문자열 |
| `pipeline_cancellation_members` | `ck_pipeline_cancellation_members_run_termination` | frozen boolean = running+run-id 또는 queued feature kind+run-id |
| `pipeline_cancellation_runs` | `ck_pipeline_cancellation_runs_engine_times` | legacy/generic의 두 시각 NULL은 허용; 하나라도 저장하면 terminal 성공 결과+finish가 필수이고 start가 있으면 start ≤ finish |
| `dedup_review_queue` | `ck_dedup_status` | pending/accepted/rejected/merged/ignored |
| `dedup_review_queue` | `ck_dedup_pair_order` | feature_id_a < feature_id_b |
| `dedup_review_queue` | `ck_dedup_scores` | 각 점수 0-100 |
| `feature_overrides` | `ck_overrides_status` | active/inactive/superseded |
| `feature_overrides` | `uq_overrides_active_feature_field` | active override는 feature_id+field_path당 1건 |
| `features` | `ck_features_coord_precision` | coord 없으면 NULL, coord 있으면 3-8 |
| `data_integrity_violations` | `ck_violations_severity` | info/warning/error/critical |
| `data_integrity_violations` | `ck_violations_status` | open/acknowledged/resolved/ignored |
| `poi_cache_targets` | `ck_poi_cache_targets_scope_mode` | center_radius/sigungu_by_radius |
| `poi_cache_targets` | `ck_poi_cache_targets_refresh_policy` | provider_default/follow_system/allow_targeted/disabled |
| `poi_cache_targets` | `ck_poi_cache_targets_radius` | 0 < radius_km ≤ 100 |
| `poi_cache_targets` | `ck_poi_cache_targets_coord` | 한국 영역 안 (lon 124-132, lat 33-39.5) |
| `poi_cache_targets` | `ck_poi_cache_targets_precision` | 3-8 |
| `poi_cache_target_feature_links` | `ck_poi_cache_link_relation` | within_radius/same_sigungu/manual |
| `provider_refresh_policies` | `ck_provider_refresh_source_kind` | openapi/filedata/manual/system |
| `provider_refresh_policies` | `ck_provider_refresh_targeted_policy` | follow_system/allow_targeted/disabled |
| `provider_refresh_policies` | `ck_provider_refresh_*` | interval/rate-limit/max_concurrent/burst/`stale_after_minutes` 양수 |
| `feature_change_requests` | `ck_feature_change_action` | add/update/delete |
| `feature_change_requests` | `ck_feature_change_state` | pending/applied/rejected |
| `feature_change_requests` | `ck_feature_change_review_mode` | require_review/immediate |

## 6. FK CASCADE 정책

| 관계 | 정책 | 이유 |
|------|------|------|
| `feature_files.feature_id` → `features` | CASCADE | feature 삭제 시 파일 메타도 |
| `feature_files.source_record_key` → `source_records` | SET NULL | source 정리해도 파일은 유지 |
| `feature_{places,events,notices,routes,areas}.(feature_id, kind)` → `features.(feature_id, kind)` | CASCADE | 배타 arc — subtype 행이 있는 동안 core kind 변경을 막는다 |
| `feature_{places,events,notices,routes,areas}.(feature_id, feature_uuid)` → `features.(feature_id, feature_uuid)` | CASCADE | identity 사본 일치 (`feature_aliases`와 같은 규칙) |
| `feature_opening_periods.feature_id` → `features` | CASCADE | |
| `feature_special_days.feature_id` → `features` | CASCADE | |
| `feature_weather_values.feature_id` → `features` | CASCADE | |
| `feature_weather_values.(source_record_key,source_entity_key,known_at)` → `source_records` | RESTRICT | immutable weather fact가 exact raw revision을 보존 |
| `feature_weather_values.(source_entity_key,provider_dataset_id)` → `source_entities` | RESTRICT | fact producer의 canonical dataset 소유 보존 |
| `current_weather_summary` → selected weather fact / successful run | CASCADE / RESTRICT | pointer는 fact 삭제와 함께 사라지고 receipt가 winner를 증명 |
| `feature_price_values.feature_id` → `features` | CASCADE | price anchor 삭제 시 시계열도 삭제 |
| `feature_price_values.(source_record_key,source_entity_key,known_at)` → `source_records` | RESTRICT | immutable price fact가 exact raw revision을 보존 |
| `feature_price_values.(source_entity_key,provider_dataset_id)` → `source_entities` | RESTRICT | fact producer의 canonical dataset 소유 보존 |
| `current_price_summary` → selected price fact / successful run | CASCADE / RESTRICT | pointer는 fact 삭제와 함께 사라지고 receipt가 winner를 증명 |
| `source_links.feature_id` → `features` | CASCADE | |
| `source_links.source_entity_key` → `source_entities` | RESTRICT | Feature link가 있는 provider entity 삭제 금지 |
| `source_records.source_entity_key` → `source_entities` | RESTRICT | immutable payload의 자연 entity 보존 |
| `source_entities.(source_entity_key,current_source_record_key)` → `source_records` | RESTRICT, deferred | 현재 포인터가 같은 entity의 record만 가리킴 |
| `curation_collections.theme_id` → `curated_themes` | RESTRICT | collection의 theme 의미 보존 |
| `curation_collections.source_id` → `curated_sources` | SET NULL | source metadata 삭제 후에도 공식 collection 보존 |
| `curation_items.collection_id` → `curation_collections` | CASCADE | collection archive는 soft 처리, 물리 삭제 시 membership 함께 삭제 |
| `curation_items.feature_id` → `features` | SET NULL | Feature 삭제 후에도 공식 항목명·원천키 보존 |
| `curation_items.source_record_key` → `source_records` | SET NULL | 원천 record 정리 후에도 큐레이션 membership 보존 |
| `features.parent_feature_id` → `features` | SET NULL | 부모 삭제 시 고아 허용 |
| `dedup_review_queue.feature_id_*` → `features` | CASCADE | |
| `feature_overrides.feature_id` → `features` | CASCADE | |
| `feature_overrides.source_record_key` → `source_records` | SET NULL | |
| `feature_merge_history.master_feature_id` → `features` | CASCADE | |
| `feature_merge_history.loser_feature_id` → `features` | CASCADE | loser는 soft-delete(ADR-017)라 행 잔존 → FK 유효 |
| `feature_merge_history.review_id` → `dedup_review_queue` | SET NULL | 큐 행 삭제돼도 이력 보존 |
| `data_integrity_violations.feature_id` → `features` | CASCADE | |
| `data_integrity_violations.source_record_key` → `source_records` | SET NULL | source 정리해도 이슈 이력 보존 |
| `feature_update_requests.job_id` → `import_jobs` | RESTRICT | request의 canonical job/typed identity를 고아로 만들지 않음 (0052) |
| `poi_cache_target_feature_links.target_id` → `poi_cache_targets` | CASCADE | target 삭제 시 link 제거 |
| `poi_cache_target_feature_links.feature_id` → `features` | CASCADE | feature 삭제 시 link 제거 |

## 7. 보관 정책 (ADR-017) → purge SQL

```sql
-- weather_values: 기본 3년 보존(ADR-062). 예보 발표 이력 비교용이므로
-- 별도 승인된 purge 작업 전에는 삭제하지 않는다.

-- notice: 종료일/발표일 +1년. subtype이 kind='notice'만 담으므로 kind 술어가 없고,
-- core row를 지우면 subtype row는 복합 FK CASCADE로 함께 사라진다.
DELETE FROM feature.features f
USING feature.feature_notices n
WHERE n.feature_id = f.feature_id
  AND n.valid_end_time < now() - interval '1 year';

-- event: 종료일 +20년
DELETE FROM feature.features f
USING feature.feature_events e
WHERE e.feature_id = f.feature_id
  AND e.ends_on < (now() - interval '20 years')::date;

-- feature_price_values: 초기 유가 보관 기준 10년. domain별 세분화는 purge asset에서 관리.
DELETE FROM feature.feature_price_values pv
WHERE pv.observed_at < now() - interval '10 years';

-- current가 아닌 명시 만료 payload history
DELETE FROM provider_sync.source_records sr
WHERE NOT EXISTS (
    SELECT 1 FROM provider_sync.source_entities se
    WHERE se.current_source_record_key = sr.source_record_key
  )
  AND sr.expires_at IS NOT NULL
  AND sr.expires_at < now();
```

## 8. Alembic 마이그레이션 가이드

### 8.1 환경 설정

`alembic/env.py`에서:

```python
from kortravelmap.infra.models import metadata as target_metadata

# search_path 강제
def run_migrations_online():
    connectable = ...
    with connectable.connect() as connection:
        connection.execute(text("SET search_path = public, x_extension"))
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

### 8.2 현행 migration 기준

호환성 자체는 설계 목표가 아니다. 데이터 보존과 lock 특성에 따라 ADR-075의 DDL 유형을 고른다.

1. **FK/CHECK** — 가능한 경우 `NOT VALID`로 추가하고 별도 transaction에서 `VALIDATE`한다.
2. **UNIQUE/인덱스** — 일반 online index는 `CREATE INDEX CONCURRENTLY`로 build하고 lock
   acquisition/보유 시간과 실패한 INVALID index를 관리한다([탐지·drop runbook](../runbooks/invalid-index-recovery.md), T-VN-H05). 그러나 기존 행 dedup과 semantic
   UNIQUE 사이에 writer가 다시 중복을 만들 수 있는 cutover는 예외다. 호환성보다 원자성이
   우선이면 table writer lock을 먼저 잡고 dedup + non-concurrent UNIQUE를 한 transaction으로
   묶는다(0060). UNIQUE writer conflict target은 같은 배포 cutover에서 전환한다. dedup처럼
   역연산으로 원본을 복원할 수 없는 migration은 거짓 downgrade를 제공하지 않고 검증된
   backup/PITR과 구 writer image를 함께 복원하도록 fail-closed한다.
3. **소형 ops 수술형** — drain, lock acquisition timeout, 예상 보유 시간을 clone에서 각각 측정한다.
4. **대형 rewrite/타입·identity 변경** — shadow column/table, batch backfill, checksum, write fence,
   swap을 사용한다. rollback window에는 legacy 구조와 delta/PITR 복구 경로를 보존한다.

### 8.3 마이그레이션 net 검증

**`upgrade head → downgrade base → upgrade head` 왕복은 더 이상 성립하지 않는다.**
squash 이후 `versions/`의 모든 노드가 forward-only이고 `downgrade()`가
`RuntimeError`를 던진다(`tests/unit/test_migration_forward_only.py`가 그 선언과 구현이
갈리지 않는지 본다). 왕복은 애초에 "역연산이 존재한다"는 전제 위의 검증이었는데,
파괴적 cutover가 들어온 시점부터 그 전제는 저장소 전체에서 깨져 있었다 — 아래 0044/0045
예외가 그 시작이다.

지금 net 검증의 정본은 **빈 DB에서 head까지 올린 결과가 모델·계약과 일치하는가**다:

- `tests/integration/test_alembic_metadata_consistency.py` — head 스키마 vs SQLAlchemy 모델
- `scripts/compare-schema-catalogs.sh` — 두 DB의 카탈로그 행 단위 대조(변조 7종 자체검증)
- `alembic/baseline/schema.sql` 끝의 routine ACL digest 자기검증

(과거 예외 기록) 0044는 연결된 entity에 immutable record가 둘 이상이면, 0045는
legacy에서 완전히 재구성할 수 없는 collection/item이나 감사값이 있으면 downgrade를
`P0001`로 거절했다. 이는 실패가 아니라 의도한 데이터 손실 방지 gate였다.

### 8.4 명명 규약과 **새 migration 작성 절차 (squash 이후)**

저장소 컨벤션: **`NNNN_<descriptive_name>.py`** (4자리 순번 + 설명).

- **파일명과 revision id가 반드시 동일할 필요는 없다.** 아카이브 109개 중 20개 넘게
  다르다. `down_revision`은 revision **id**로 잇는다. 코드에서 "이 revision이
  아카이브인가"를 판정할 때 **파일명으로 하면 안 된다** — 선언된 id를 읽어라
  (`tests/integration/test_alembic_upgrade.py:_archived_revisions`).
- 4자리 순번으로 적용 순서를 가시화한다.
- revision message(파일 docstring 첫 줄)는 commit summary와 일치시킨다.

#### 지금 `alembic/versions/`에 있는 것

squash(2026-08-14) 이후 baseline과 bridge, T-VN-40 migration만 있다.

- `0200_schema_baseline.py` — revision id `0200_schema_baseline`, `down_revision=None`.
  `alembic/baseline/{schema,seed}.sql`을 byte sha로 잠근 채 적용한다.
- `0201_squash_bridge.py` — revision id는 파일명이 아니라 **`0104_tvn36_final_fence`**다.
  이미 `0104`에 있는 DB가 이 그래프에서도 해석되게 하는 노드다.
- `0202_tvn40_curation_receipts.py`부터 `0222_tvn40a_merge_runtime_role.py`까지 —
  bridge 뒤에 이어지는 T-VN-40 단일 체인이며, 현재 head는
  `0222_tvn40a_merge_runtime_role`다.

`0001~0104` 체인 109개는 `alembic/legacy_versions/`의 실행되지 않는 아카이브다
([README](../../alembic/legacy_versions/README.md)). **`versions/`로 되돌리지 마라** —
bridge와 아카이브가 `0104_tvn36_final_fence`를 둘 다 선언하면 Alembic graph가 손상된다.

#### 다음 migration(`0223`~) 작성

1. 파일은 `alembic/versions/0223_<name>.py`,
   `down_revision = "0222_tvn40a_merge_runtime_role"`(= 현재 head)로 잇는다.
   **`0201`을 쓰지 마라** — 그건 bridge 파일명이고 revision id가 아니다.
2. `0105`~`0199`처럼 아카이브와 겹치는 번호는 쓰지 않는다. 파일 정렬이 `0200`보다
   앞서면서 `down_revision`은 뒤를 가리키는 파일이 생겨 읽는 사람을 오도한다.
3. 파생 산출물을 함께 갱신한다:
   `python scripts/generate_application_migration_graph.py --write`
   (`src/kortravelmap/_application_migration_graph.json`). 게이트는 그 스크립트의
   `--check`가 아니라 unit 테스트
   `tests/unit/test_application_schema_head.py::test_application_graph_artifact_matches_literal_source_graph`
   다 — CI 워크플로에 이 스크립트를 부르는 스텝은 없다.
4. `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`(배포 env pin)를 새 head로 올린다.
   `docker/api-entrypoint.sh`가 이미지 head와 이 값을 대조해 fail-closed한다.
5. baseline 자체는 건드리지 않는다. baseline 갱신은 별도 결정이며 절차는
   `alembic/versions/0200_schema_baseline.py`의 `_SCHEMA_SHA256` 주석에 있다.

> **baseline 파일 명명 규약**: 다음에 squash를 한다면 파일 이름을
> `NNNN_schema_baseline.py`로 지어라. `docker/api-entrypoint.sh`가 "이 이미지가
> squash판인가"를 `alembic/versions/*_schema_baseline.py` 존재로 판별한다.
## 9. EXPLAIN 통합 테스트

모든 hot path SQL은 `tests/integration/`에서 EXPLAIN 결과로 인덱스 사용 검증.
자세한 패턴은 `docs/architecture/performance.md` §10 + `docs/test-strategy.md` §4.2.

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

Grafana Loki에서 LogQL로 추적 (PinVi 측 wiring).

## 11. 백업 / 복구

```bash
# 일 1회 custom format (SPEC V8 v8_0)
pg_dump --format=custom --no-owner --no-privileges \
        --schema=feature --schema=provider_sync --schema=ops \
        kor_travel_map > /backup/kor_travel_map_$(date +%F).dump

# PITR: wal-g + BackBlaze B2 (PinVi 측 운영)
```

복구:
```bash
pg_restore --no-owner --no-privileges -d kor_travel_map_new kor_travel_map_2026-05-24.dump
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
- [ ] Alembic upgrade/downgrade round-trip 및 표현력 손실 downgrade 거절 테스트 통과
