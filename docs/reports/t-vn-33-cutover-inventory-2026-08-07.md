# T-VN-33 cutover 인벤토리 (2026-08-07)

- 상태: 조사 완료, 구현 착수 전
- 기준: PR #966 `feat/tvn33-provider-datasets` @ `e7501204`
- 정본 설계: [`t-vn-33-provider-datasets-single-pr-plan-2026-08-06.md`](t-vn-33-provider-datasets-single-pr-plan-2026-08-06.md)
- 목적: 설계는 얼었으나 구현 표면이 문서에 없다. **무엇을 얼마나 고쳐야 하는지**를
  파일·줄 단위로 고정해, 착수 시 탐색을 반복하지 않게 한다.

## 0. 먼저 읽을 것 — 문서가 말하지 않는 사실 4개

1. **브랜치는 계약뿐이다.** codex의 5개 커밋(`23b2afc4`..`e7501204`)은 `src/`,
   `alembic/`, `packages/` 아래 **0개 파일**을 건드린다. alembic head는
   `0087_route_area_subtypes`이고 `0088`~`0090`은 없다. 이름만
   `docs/removal-manifests/t-vn-33-source-lineage.md:31-34`에 예약돼 있다.
2. **`tvn33-reference-ownership-v1.sql`은 production DDL이 아니라 소유권 계약이다.**
   그 파일의 `ops.import_jobs`(`:307-320`)는 5개 열을 선언하지만 실제 테이블은
   ~30개다(`models.py:2609-2676`). **가산적 단언**("이 열·FK·트리거가 있어야 한다")으로
   읽어야 하며, 그대로 적용하면 ops 스키마 대부분이 사라진다.
3. **완전 신규 relation 6개**: `provider_datasets`, `provider_dataset_operations`,
   `provider_dataset_operation_scopes`, `source_entity_heads`, `import_job_datasets`,
   `feature_update_request_datasets` — `contracts/vnext/`와 freeze 테스트 밖에서
   출현 0건.
4. **규모.** production Python 95개 파일에 `dataset_key` 1,684회, 34개 파일에
   `is_primary_source` 91회. 테스트 355개 중 194개 영향. frontend 44개 파일.
   `(provider, dataset_key)`는 ops 표면 전체의 **주소 체계**다 — 단순 rename이 아니다.

## 1. 착수 전에 사람이 결정해야 할 것 (설계 문서에 없음)

| # | 결정 항목 | 왜 막히는가 |
| --- | --- | --- |
| 1 | `sync_scope 'default' → 'dataset_wide'` 매핑 | `provider_catalog`의 58개 중 55개가 `default`인데 DB CHECK(`target-schema-v1.sql:99-109`)는 `dataset_wide`/`target_grids`/`external_system:*`만 받는다 |
| 2 | `source_kind` 우선순위 | `curated_sources.source_kind`(5값, `models.py:1144`)와 `provider_refresh_policies.source_kind`(4값, `:5570`)가 같은 pair에서 **불일치 가능**. 목표는 6값 합집합 |
| 3 | `observed_at` backfill 출처 | head 승격 축인데, 자연스러운 출처가 **폐기 대상인** `source_records.last_seen_at`이다 |
| 4 | `is_active` 의미 | **"쓰기를 받을 수 있다"여야 한다.** "operation이 있다"로 derive하면 아래 §5 사고가 난다 |
| 5 | `python-datagokr-api/standard_special_streets` | provider 오귀속(`0025:340,390`). 실제 loader는 `data.go.kr-standard`. inactive seed vs 데이터 수정 |
| 6 | `integrity_observation_scopes.latest_authoritative_generation` | 계약이 **삭제**한다(`models.py:3906`). 의도인지 확인 필요 |
| 7 | `enrichment_review_queue.source_entity_key` backfill | 이 테이블은 `source_entity_type`을 **저장하지 않는다**(`models.py:2230-2232`). entity key를 저장 열에서 유도할 수 없어 `(provider, dataset_key, source_entity_id)`로 조인해야 하고, 다중/무매치 행의 처리(중단 vs 삭제)를 정해야 한다 |
| 8 | `consumer-rollout-v1.json`의 `user: no re-vendor` | user spec **바이트가 바뀐다**(§4). 계약과 사실을 맞춰야 한다 |

## 2. 관계별 컬럼 델타

범례: **NEW** 신설 · **+FK** `provider_dataset_id` 추가 후 legacy fence · **LEGACY** C에서
fence, T-VN-39에서 물리 삭제.

### 2.1 canonical core (계약 20개에 없지만 선행 조건)

| relation | 상태 | 비고 |
| --- | --- | --- |
| `provider_sync.provider_datasets` | NEW (`target-schema-v1.sql:111-146`) | `provider_dataset_id bigint IDENTITY` PK, `UNIQUE(provider,dataset_key)`, `is_active`, versioned `capabilities jsonb`, identity immutable 트리거(`:175`) |
| `provider_sync.provider_dataset_operations` | NEW (`:183-205`) | PK `(provider_dataset_id, operation_key)`, kind ∈ `feature_load\|refresh\|preview` |
| `provider_sync.source_entity_heads` | NEW (`:688-705`) | `source_entities.current_source_record_key`를 대체. 복합 FK + deferred completeness 트리거(`:768`) |

### 2.2 계약 20개

| # | relation | 존재 | 추가 | LEGACY |
| --- | --- | --- | --- | --- |
| 1 | `provider_dataset_operation_scopes` (`:10`) | NEW | 전체 | — |
| 2 | `provider_sync_state` (`:95`) | O `models.py:1992` | `provider_dataset_id`, PK→`(provider_dataset_id, sync_scope)` | `provider`,`dataset_key` (둘 다 PK, `:2009-2010`) |
| 3 | `notice_lifecycle_scopes` (`:120`) | O `:844` | 대리 PK + `provider_dataset_id` | PK 3열 (`:856-858`) — **PK 모양 변경** |
| 4 | `notice_lineage_states` (`:202`) | O `:864` | `notice_lifecycle_scope_id` FK | PK 4열 (`:882-885`) + 3열 FK (`:868-878`) |
| 5 | `feature.curated_sources` (`:219`) | O `:1133` | `provider_dataset_id` + UNIQUE | `provider`,`dataset_key` (`:1174-1175`), 인덱스 2개 |
| 6 | `feature.curated_source_rules` (`:289`) | O `:1213` | — | **`dataset_key` 삭제**(`:1260`) — 부모 중복 |
| 7 | `ops.import_jobs` (`:307`) | O `:2399` | `dataset_membership_mode` + deferred 트리거 2 | `provider`,`dataset_key`,`sync_scope`(`:2648-2650`), CHECK 1, 인덱스 3, UNIQUE 1 |
| 8 | `ops.import_job_datasets` (`:322`) | NEW | 전체 | — |
| 9 | `ops.import_job_events` (`:498`) | O `:2748` | `import_job_dataset_id` + 복합 FK | 3열(`:2836-2838`), CHECK 2, 인덱스 3 |
| 10 | `ops.feature_update_requests` (`:517`) | O `:2986` | `dataset_membership_mode` + deferred cardinality | **legacy 표현 3종**: `providers[]`/`dataset_keys[]` ARRAY+GIN(`:3080-3089`), `scope` JSONB(`:2998`), CHECK 4 |
| 11 | `ops.feature_update_request_datasets` (`:531`) | NEW | 전체 | — |
| 12 | `ops.provider_refresh_policies` (`:644`) | O `:5564` | `provider_dataset_id` PK | `provider`,`dataset_key`(둘 다 PK) · ⚠ `source_kind` 4값 vs 목표 6값 |
| 13 | `ops.offline_uploads` (`:662`) | O `:2897` | `provider_dataset_id` + scope FK | 2열, UNIQUE 1, 인덱스 1 |
| 14 | `ops.integrity_observation_scopes` (`:685`) | O `:3877` | 대리 PK + `provider_dataset_id` | PK 2열, CHECK 2 · ⚠ `latest_authoritative_generation` 삭제 |
| 15 | `ops.integrity_observation_runs` (`:761`) | O `:3918` | `integrity_observation_scope_id` FK | 2열, 2열 FK, UNIQUE 2, 인덱스 1 |
| 16 | `ops.data_integrity_violations` (`:779`) | O `:4055` | nullable `provider_dataset_id` + cross-check 트리거 | 2열 |
| 17 | `ops.poi_cache_targets` (`:868`) | O `:4165` | — | — |
| 18 | `ops.poi_cache_target_feature_links` (`:875`) | O `:4316` | nullable `provider_dataset_id` | 2열, 인덱스 1 |
| 19 | `ops.enrichment_review_queue` (`:895`) | O `:2173` | **`source_entity_key` NOT NULL FK** + UNIQUE | `source_provider`,`source_dataset_key`,`source_entity_id`, UNIQUE 1, 인덱스 1 |
| 20 | `ops.managed_files` (`:913`) | O `:5967` | nullable `provider_dataset_id`, `provider_name`, owner CHECK | 2열 + 인덱스 |

### 2.3 source lineage

| relation | 추가 | LEGACY |
| --- | --- | --- |
| `source_entities` (`:799`) | `provider_dataset_id` FK + UNIQUE | `provider`,`dataset_key`, `current_source_record_key`, UNIQUE 1, FK 1, 인덱스 1 |
| `source_records` (`:891`) | immutability 트리거, 새 history 인덱스 | 11개 열(`:961-990`), UNIQUE 1, 인덱스 3 |
| `source_links` (`:998`) | `source_role='primary'` predicate 인덱스 | `is_primary_source`(`:1053`), boolean predicate 인덱스(`:1026`) |

## 3. write 지점 — 93개

**ORM write 0건.** `SourceEntityRow`/`SourceRecordRow`/`SourceLinkRow`는 테스트에서만
생성된다. production write는 전부 raw `text(...)`이고 전부 `src/kortravelmap/infra/`
안에 있다. **Dagster 패키지에는 이 테이블들에 대한 SQL이 아예 없다**(kwargs 전달 ~90줄).

### 3.1 `provider_sync.*` writer — 13개 문장, 2개 파일

`feature_repo.py`가 진앙이다:

| SQL 상수 | 실행 지점 | 쓰는 것 |
| --- | --- | --- |
| `_UPSERT_SOURCE_ENTITY_SQL:330` | `_upsert_source_record_state():2194` | `provider`,`dataset_key`,`source_entity_type`,`last_seen_at` |
| `_UPSERT_SOURCE_RECORD_SQL:361` | `:2196` | 위 3열 + `source_version`,`expires_at`, **`last_seen_at` in DO UPDATE** |
| `_REFRESH_SOURCE_ENTITY_CURRENT_SQL:382` | `:2199` | `current_source_record_key`, `first/last_seen_at` |
| `_UPSERT_SOURCE_LINK_SQL:409` | `upsert_source_link():2241` | `is_primary_source` |
| notice 5종 (`:2429`,`:2439`,`:2448`,`:2471`,`:2623`) | `:2559`~`:2752` | 계보 3열 |

`sync_state_repo.py:87/106`, `merge_repo.py:119/132`(feature_id만 — 안전).

### 3.2 반드시 **쪼개야 할** writer

`feature_repo._upsert_source_record_state():2189-2206`은 이미 3문장이지만 **틀린** 3문장이다.

- `:2194` entity upsert → 3열 비정규화 대신 `provider_dataset_id` FK
- `:2196` record insert → `ON CONFLICT DO UPDATE SET last_seen_at = GREATEST(...)`
  (`:374-378`)가 **immutability 트리거가 거부할 변경**이다. `DO NOTHING`이어야 한다
- `:2199` head 재계산 → `source_entity_heads` upsert로 이동. 현재 정렬은
  `last_seen_at DESC, fetched_at DESC, imported_at DESC, source_record_key DESC`
  (`:387-391`)이고 목표는 `(observed_at, source_record_key)`뿐 — §1 결정 3

### 3.3 key 유도 3중 복제 위험

| 함수 | 위치 | 식 |
| --- | --- | --- |
| `make_source_record_key` | `core/ids.py:298-360` | `sr_ + sha1(p\|d\|t\|id\|hash)[:20]` — 호출 27곳 |
| `_make_source_entity_key` | `feature_repo.py:2083-2093` | `se_ + sha256(p\|d\|t\|id)` — **private, `core/ids.py`에 공개 대응물 없음** |
| (동일 식, SQL) | `alembic/legacy_versions/0044_source_entities.py:20-29` | 손으로 복제됨 |

⇒ `_make_source_entity_key`를 이번 PR에서 `core/ids.py`로 올리지 않으면 `0088`에
**세 번째 사본**이 생긴다.

### 3.4 그 외 25개 문장 · DTO 생성자 55곳

`jobs_repo`, `feature_operation_repo`, `offline_upload_repo`, `integrity_violation_repo`,
`file_registry`, `poi_cache_target_repo`, `provider_refresh_policy_repo`, `curated_repo`,
`curation_repo`, `weather_repo`, `price_repo`. `SourceRecord(...)` × 27,
`SourceLink(...)` × 28 — kwargs가 `_source_record_params`를 거쳐 그대로 컬럼에 간다.

## 4. read 지점 — SQL 120개 + 소비 표면 33개

전부 raw SQL이고 전부 `src/kortravelmap/infra/`다. API·Dagster 패키지에
`provider_sync.source_*` SQL은 **없다**.

### 4.1 hot path (EXPLAIN gate 대상, 위험순)

| 지점 | 이유 |
| --- | --- |
| `feature_repo.py:330/382/409` | `load_bundles():2289` 루프에서 **record당 3문장**. record마다 `provider_datasets` 조회를 넣으면 **ETL 처리량 직접 회귀** — job당 1회 resolve해서 넘겨야 한다 |
| `admin_feature_repo.py:1250` LATERAL + `:1309-1315` | 페이지네이션 admin 목록, 행당 LATERAL. 이미 #639의 병목 경로 |
| `admin_feature_repo.py:1189` ILIKE | `raw_name`/`raw_address`/`source_entity_id` — **전부 폐기 대상**. 이 검색 기능은 목표 스키마에 대응물이 없다 |
| `feature_repo.py:629` notice 필터 | bbox·cluster·nearby 5곳에 박힌 **최다 사용 fragment** |
| `curated_repo.py:857` | `source_records`를 pair로 전수 LEFT JOIN — 현재 최대 절대 스캔 |
| `weather_repo.py:1410` | `provider='python-kma-api'` 하드코딩 + partial 인덱스 `idx_source_records_kma_alert_history`. 인덱스와 `alembic_exclusions.py:25` 원장 **둘 다** 다시 써야 한다 |
| `status_repo.py:105` | `GROUP BY provider` 전수 스캔, `/ops/status` |
| `scope_repo.py:752/792` | target × matched feature (10⁴+), 무제한 |
| `observation_repo.py:95/111/128` | **폐기 대상 열 전부**를 읽는다 |

### 4.2 컬럼 sweep으로 안 잡히는 것

`ops.poi_cache_targets.provider_overrides` JSONB가 **문자열 `f"{provider}:{dataset_key}"`를
키로** 쓴다 — `feature_update_executor.py:308`, `provider_fetchers.py:1452`,
raw SQL `_OPINET_POI_TARGETS_SQL`.

## 5. ⚠ 가장 위험한 발견 — `is_active` 유도 방식

**`is_active`를 "operation handler가 있다"로 derive하면, 실제로 `source_records`
쓰기를 받는 4개 pair가 inactive로 seed되고 cutover 직후 모든 ETL이
`ck_provider_dataset_active_write`로 실패한다**:

`kma_ultra_short_grid`, `kma_short_grid`, `airkorea_stations`,
`mois_license_features_history`.

따름정리: **operation의 dataset_key와 source-record의 dataset_key가 다르다.**
KMA는 operation 4개가 grid record key 2개로, `airkorea_air_quality`(operation)는
`airkorea_stations`(records)로 매핑된다. **operation과 source record를 `dataset_key`로
조인하는 backfill은 이 4개에서 0행을 낸다.**

## 6. seed 데이터 — pair 64개, triple 55개

정본 카탈로그: `packages/kor-travel-map-api/src/kortravelmap/api/provider_catalog.py:292-547`
(58개). 필드가 목표에 직결한다 — `label→display_name`, `feature_kind→capabilities.produces`,
`is_feature_load`/`is_refreshable`/`preview`→operations, `sync_scope`→scopes.

- operation 행 **121개** (feature_load 45 + refresh 53 + preview 23), scope 행 **53개**
- `sync_scope`: `default` 55 → `dataset_wide` 매핑 필요, `target_grids` 3
- **CHECK 전수 통과**: provider 최대 28자, dataset_key 45자, label 60자, 전부 ASCII →
  NFC 항등. trim/NFC 위반 0, NFC 후 충돌 0
- operation이 하나도 없는 4개는 `is_active=false` seed (MOIS 3 + visitkorea 1)

### 6.1 카탈로그가 놓친 6개 pair

| provider | dataset_key | entity_type | 출처 | 놓친 이유 |
| --- | --- | --- | --- | --- |
| `python-kma-api` | `kma_ultra_short_grid` | `kma_grid` | `providers/kma.py:136,144` | dataset_key가 동적 파라미터(`:159`) |
| `python-kma-api` | `kma_short_grid` | `kma_grid` | `providers/kma.py:138` | 동일 |
| `kakao-local-api` | `place_phone_enrichment` | `place_phone` | `enrichment.py:60-61` | provider를 호출자가 준다 |
| `naver-search-api` | `place_phone_enrichment` | `place_phone` | 동일 | 동일 |
| `google-places-api-new` | `place_phone_enrichment` | `place_phone` | 동일 | 동일 |
| `python-datagokr-api` | `standard_special_streets` | — | `0025:340,390` | **provider 오귀속** (§1 결정 5) |

### 6.2 코드로 열거 불가능한 집합

`offline_upload.py:1194-1237`과 JSON/JSONL 경로(`:955-983`)가 **admin 업로드 파일에서
provider/dataset_key/source_entity_type을 그대로 역직렬화**한다. `SourceRecord`는
`min_length=1`만 강제하고(`dto/source.py:40-56`), `ops.offline_uploads.provider`는
CHECK 없는 `sa.Text()`다(`0011:32`).

⇒ **마이그레이션 A는 `SELECT DISTINCT provider, dataset_key`를 각 비정규화 소유
테이블에서 뽑아 seed에 없는 pair가 있으면 hard-fail해야 한다.** 공백/비NFC/112자
초과/NFC 후 충돌도 함께 스캔한다. 코드 합집합은 하한이지 seed가 아니다.

## 7. Dagster

`operation_key → handler` 주 bind 지점:
`packages/kor-travel-map-dagster/src/kortravelmap/dagster/feature_update_runner.py:762-987`
(`_DEFAULT_SPECS` ~28개). 이미 **여러 dataset_key → 하나의 handler** 구조라
(`frozenset[str]`, KMA grid 3종 `:952-965`, MCST `:980-986`) 여러
`provider_dataset_id`가 한 `operation_key`를 공유하는 목표와 자연히 맞는다.
부 bind: `providers/feature_operation_registry.py:422-458` (33 job / 53 pair).

### 7.1 되돌릴 수 없는 부작용

registry re-key는 `FEATURE_OPERATION_REGISTRY_DIGEST` → `..._VERSION`을 바꾼다
(`feature_operation_registry.py:462-491`). `parse_feature_operation_identity_tags():798-805`가
**정확한 버전 일치**를 요구한다. 결과:

- reconcile sensor는 우아하게 저하(로그 + cursor 전진)
- **live guard `feature_operation_tracking.py:336-340`은
  `FeatureOperationGuardUnavailable(reason="registry_conflict")`로 바꿔 provider I/O를
  fail-closed로 만든다.** cutover 전에 큐에 들어가 cutover 후 시작되는 run은 실행을 거부한다

⇒ **Dagster 큐 drain은 권고가 아니라 선행 필수 조건**이다(계획서 `:172`와 일치).

## 8. 깨질 테스트 — 355개 중 194개

| 디렉터리 | 영향 | 전체 |
| --- | --- | --- |
| `tests/integration/` | **76** | ~124 |
| `tests/unit/` | **50** | ~152 |
| API 패키지 | **23** | 49 |
| Dagster 패키지 | **19** | 28 |
| frontend e2e | **26** | ~88 |

원시 hit ~2,500, 실제 손수정 지점 ~1,400–1,600. **38개 integration 파일이
`provider_sync.*`에 raw SQL을 쏘고** `UndefinedColumn`으로 즉시 실패한다.

### 8.1 먼저 고칠 지렛대 5개

1. `tests/integration/perf_gate.py:470-560` — 유일한 공용 source-row seeder
2. `packages/kor-travel-map-api/tests/test_admin_features_router.py:137-260`
3. frontend mock 리터럴 5벌(`feature-detail-sections`, `features-list`,
   `features-map-interactions`, `dedup-reviews-actions`, `enrichment-reviews-actions`)
   → 공용 fixture로 추출
4. `packages/kor-travel-map-api/tests/test_export_openapi.py:174-292,511-523` —
   OpenAPI clean-cut guard. **같은 커밋에 들어가야 CI가 안 막힌다**
5. `packages/kor-travel-map-dagster/tests/test_admin_code_validation.py:82-105`

### 8.2 의도적 동작 변경(rename 아님) 11곳

- `test_feature_repo_load.py:272-333` — 재적재 시 `source_records_inserted == 0`
  **그리고** `max(last_seen_at)` 전진을 단언한다. **두 전제 모두 죽는다**
- `test_notice_lifecycle.py:140-147` `_pin_seen_at` — 유일한
  `UPDATE source_records SET last_seen_at`. immutability 트리거에 즉시 걸린다
- `test_observation_repo.py:89-166`, `test_client_orchestration.py:163,225`,
  `test_curation_repo.py:1014-1052`, `test_dagster_feature_etl.py:544,586,624,630`

### 8.3 모양 참조로 쓸 것 / 건드리면 안 되는 것

`test_vnext_target_freeze.py`는 이미 목표 기준으로 쓰여 있고 20개 relation을
`:55-95`에 열거한다. `test_source_entities_migration.py`와
`alembic/legacy_versions/0044_source_entities.py`가 expand+backfill 선례다.
`tests/unit/test_migration_immutability.py`는 0056/0058 바이트 불변을 단언한다 —
건드리지 말 것.

## 9. API 표면

spec은 **셋**이다 — `openapi.json`(503 schema/150 path), `openapi.user.json`(105/31),
`openapi.service.json`(80/21). 생성기는
`packages/kor-travel-map-api/scripts/export_openapi.py`(`--check`가 CI drift gate).

**user spec도 바뀐다**: (a) 12개 component·9개 path에 `provider`/`dataset_key` 노출,
`GET /v1/providers/{provider}/last-sync`는 **path 파라미터**; (b) 공개
`/v1/features` 쿼리 설명에 `"primary source(provider_sync.is_primary_source) 기준."`이
문자 그대로 들어 있다(`routers/features.py:971-974`).

⇒ **두 곳 regen 필수**(admin frontend `src/api/types.ts` 22,989줄 + user-client
`src/types.ts`), 그리고 `contracts/vnext/openapi-diff-v1.json`이 **세 spec 전부의
sha256**을 고정하므로 재핀 + `revisions[]` 항목이 필요하다.

## 10. 구현 체크리스트 (의존 순서)

크기는 production 순 LOC(테스트 제외).

### Phase 0 — 결정 (코드 없음, §1의 8개)

### Phase 1 — 직렬 기반

| 단계 | 산출물 | 크기 |
| --- | --- | --- |
| 1.1 | `0089_tvn33_expand_seed.py` — 신규 테이블·nullable FK·64 pair seed·121 operation·53 scope·backfill·preflight | **900–1,300** (최대 산출물) |
| 1.2 | `models.py` 미러 (20 + 신규 6) | 400–600 |
| 1.3 | `_make_source_entity_key` → `core/ids.py` 승격 | 30 |
| 1.4 | `_application_migration_graph.json` 재생성 — **빠뜨리기 쉽다**; `test_application_schema_head.py`가 실패한다 | 1 command |

### Phase 2 — 1.1/1.2 이후 병렬

| lane | 범위 | 크기 |
| --- | --- | --- |
| A source lineage writer (**임계 경로**) | `feature_repo.py:330-427,2055-2106,2189-2206` 3분할 + job 단위 id resolve | 250–350 |
| B notice lifecycle | `:2421-2760` 9문장 re-key | 200–300 |
| C hot reader | `feature_repo`(105) + `admin_feature_repo`(47) | 500–700 |
| D ops repo 17개 | integrity·curated·update·scope·jobs·sync·upload·policy·curation·operation·poi·file·consistency·enrichment | 700–1,000 |
| E membership | 신규 2테이블 writer + update 경로의 **pair 표현 4종** 통합 | 300–400 |
| F pipeline projection | `pipeline_repo.py`(75) — `canonical_provider_datasets` CTE(`:525-541`)를 실제 join으로 | 250–350 |
| G Dagster registry | `feature_update_runner.py:762-987` operation_key bind | 200–300 |

### Phase 3 — 직렬

`0090_tvn33_constraints.py`(300–450) → API `GET /v1/provider-datasets` + DTO 3종(300–400)
→ 양쪽 types regen + 3개 sha256 재핀 → frontend 44파일(400–600) →
`0091_tvn33_cutover_fence.py`(250–350, 선례 `0082_legacy_write_fence.py:59-131`) →
static legacy-reader gate **신설**(100–150, `tests/lint/`에 현재 없음) →
`alembic_exclusions.py:25` 갱신.

### Phase 4 — 테스트 (최대 버킷)

지렛대 5개(300–400) → integration 76 → unit 50 → API 23 → Dagster 19 → e2e 26 →
신규 계약 테스트(500–700: seed↔handler exact-set drift, head completeness 동시성,
20+ rejection fixture, EXPLAIN gate).

### 총량과 위험

**production ~5,500–7,500 LOC + 테스트 수정 ~1,400–1,600 지점.** 계획서의 "단일 PR"은
**머지 경계**로는 정확하지만 **작업 경계**는 아니다.

위험 top 3:

1. **§5** — `is_active` 오유도가 cutover 후 KMA/airkorea/MOIS-history ETL을 조용히
   전멸시킨다. 완화 비용 최소, 누락 비용 최대
2. **§7.1** — Dagster registry 버전 변동이 경계를 넘는 run의 provider I/O를
   fail-closed로 만든다. 큐 drain 필수
3. **§4.1 첫 행** — `load_bundles`의 record당 `provider_datasets` 조회는 시스템에서
   가장 뜨거운 루프의 직접적 처리량 회귀
