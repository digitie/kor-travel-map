# openapi-admin-contract.md - Admin 우선 OpenAPI와 Dagster feature update queue

본 문서는 ADR-045 이후 krtour-map 독립 프로그램의 OpenAPI 기준이다. 1차 계약은
admin UI가 실제로 사용하는 API를 기준으로 작성한다. TripMate 연동 API는 이 계약을
바탕으로 필요한 공개 필드, batch 조회, 캐시 정책을 후속으로 확장한다.

외부 POI 기반 캐시 갱신 타깃(`external_system + target_key + 좌표 + 반경`)과
provider별 refresh policy/rate limit 상세는
[`docs/poi-cache-update-targets.md`](poi-cache-update-targets.md)를 함께 따른다.

## 1. 운영 모델

```
┌────────────────────────────────────────────────────────────────────┐
│ TripMate                                                           │
│  - 사용자/여행계획/POI 도메인                                      │
│  - krtour-map DB 직접 접근 금지                                    │
│  - OpenAPI client로 feature 조회/업데이트 요청                     │
└───────────────────────────────┬────────────────────────────────────┘
                                │ HTTP / OpenAPI
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ krtour-map 독립 프로그램                                           │
│                                                                    │
│  api        FastAPI + OpenAPI (`/features`, `/admin`, `/ops`)       │
│  frontend   Next.js admin UI                                       │
│  dagster    provider sync / feature update / consistency jobs       │
│  postgres   독립 PostgreSQL + PostGIS (`krtour_map`)                │
│  rustfs     선택 S3 호환 객체 저장소                                │
└────────────────────────────────────────────────────────────────────┘
```

운영 원칙:

- TripMate는 krtour-map을 Python package로 import하지 않는다.
- TripMate는 krtour-map PostgreSQL에 직접 연결하지 않는다.
- krtour-map OpenAPI가 유일한 프로세스 간 계약이다.
- `python-krtour-map` 메인 패키지의 `AsyncKrtourMapClient`는 krtour-map API/Dagster
  내부 구현에서 사용한다.

## 2. Docker 서비스

초기 Docker Compose 논리 서비스:

| 서비스 | 역할 |
|--------|------|
| `krtour-map-api` | FastAPI backend, OpenAPI 제공 |
| `krtour-map-frontend` | Next.js admin UI |
| `krtour-map-dagster-webserver` | Dagster UI |
| `krtour-map-dagster-daemon` | schedules/sensors/runs |
| `krtour-map-postgres` | 독립 PostgreSQL 16 + PostGIS 3.5 |
| `krtour-map-rustfs` | 선택 객체 저장소. 로컬 표준 포트는 S3 API `9003`, console `9004` |

PostgreSQL 기본 DB:

- app DB: `krtour_map`
- Dagster metadata DB: `krtour_map_dagster`

같은 Postgres container를 써도 DB는 분리한다. migration은 app DB에 Alembic,
Dagster DB에는 Dagster가 자체 schema를 관리한다.

## 3. OpenAPI 작성 원칙

- OpenAPI 산출물은 admin/debug/ops를 포함한 전체 admin spec
  `packages/krtour-map-admin/openapi.json`과 TripMate/user-facing subset spec
  `packages/krtour-map-admin/openapi.user.json` 두 개다.
- admin 전체 scope는 admin UI가 쓰는 `/features`, `/admin`, `/ops`, `/debug` API다.
- user subset은 TripMate가 호출하는 `/features/*`, `/tripmate/*`,
  `/admin/feature-update-requests` 일부 method만 포함한다.
- 모든 응답은 debug/admin backend의 HTTP 응답 셰입을 쓴다.

성공:

```json
{
  "data": {},
  "meta": {
    "duration_ms": 12
  }
}
```

에러:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "요청 값이 올바르지 않습니다.",
    "details": {}
  }
}
```

메인 라이브러리 DTO에는 `data/meta/error` 래핑을 넣지 않는다. 래핑은 API 패키지
책임이다.

## 4. API tag 구조

| Tag | Prefix | 용도 |
|-----|--------|------|
| `features` | `/features` | 지도/상세 공통 read |
| `admin-features` | `/admin/features` | feature 검색/비활성화/override. 수동 추가/영구 삭제는 audit log 설계 후 후속 |
| `admin-providers` | `/admin/providers` | provider 상태/강제 실행 |
| `admin-jobs` | `/admin/import-jobs` | queue/job 조회/취소 |
| `admin-update-requests` | `/admin/feature-update-requests` | 지리 범위 기반 feature 업데이트 요청 |
| `admin-poi-cache-targets` | `/admin/poi-cache-targets` | 외부 POI/cache target 등록, 삭제, 주변 조회 |
| `admin-dedup` | `/admin/dedup-review` | 중복 검토 |
| `admin-issues` | `/admin/issues` | 결측/정합성 이슈 |
| `admin-offline` | `/admin/offline-uploads` | 오프라인 파일 업로드/검증/적재 |
| `ops` | `/ops` | 에러 로그, metrics, consistency |
| `dagster` | `/ops/dagster` | Dagster webserver GraphQL 기반 운영 요약 |
| `debug` | `/debug` | fixture, ETL preview, EXPLAIN |

### 4.1 Admin issues / 주소 검토

`/admin/issues`는 결측/정합성 이슈를 한 건 단위로 처리하는 운영 API다. 특히
kraddr-geo REST v2 적용 중 발생한 주소/좌표 이슈를 admin UI에서 수동 처리할 수
있어야 한다.

#### 주소 이슈 타입

| issue_type | 의미 |
|------------|------|
| `provider_address_mismatch` | provider 주소와 좌표 기준 kraddr-geo 주소가 다른 장소로 보임 |
| `provider_address_partial_match` | 시군구/읍면동은 맞지만 상세 주소가 불완전하거나 다름 |
| `geocode_failed` | provider 주소 문자열로 좌표를 찾지 못함 |
| `reverse_geocode_failed` | 좌표로 주소를 찾지 못함 |
| `missing_address` | provider/kraddr-geo 양쪽 주소 없음 |
| `missing_bjd_code` | kraddr-geo 결과에 법정동코드 없음 |

#### 필수 엔드포인트

| Method | Path | 용도 |
|--------|------|------|
| GET | `/admin/issues` | 이슈 목록. `issue_type`, `provider`, `dataset_key`, `severity`, `status`, `bbox`, `q`, `cursor` 지원 |
| GET | `/admin/issues/{issue_key}` | 이슈 상세. provider raw 주소, kraddr-geo 후보, 좌표, 지도 표시 데이터 포함 |
| PATCH | `/admin/issues/{issue_key}` | `resolve`, `ignore`, `reopen`, `retry_geocode`, `retry_reverse_geocode`, `apply_kraddr_geo_address`, `manual_override` |

`manual_override`는 `feature.features`의 `address`/`coord`/행정코드 컬럼을 갱신하고
`ops.feature_overrides`에 같은 값을 기록해 provider 재적재가 덮어쓰지 않게 한다.
`apply_kraddr_geo_address`는 좌표 기준 kraddr-geo reverse 결과를 정본 주소로 채택한다.

T-207c 구현분은 `/admin/features` 목록, deactivate status override, `/admin/dedup-review`
목록/결정/merge다. `POST /admin/features` 수동 생성과 `DELETE /admin/features/{id}`
영구 삭제는 `ops.admin_audit_log` 설계 후 별도 작업으로 남긴다.

## 5. Feature update request

Feature update request는 OpenAPI로 Dagster feature update job을 제어하는 표준
엔드포인트다. 운영자는 admin UI에서, TripMate는 필요 시 OpenAPI client로 호출한다.

POI/cache target 기반 요청의 목적은 캐싱이다. 외부 앱이 저장한 POI 주변에서 자주
바뀌는 값(날씨, 유가, 휴일, 경고, 유고정보 등)을 전체 재적재 없이 갱신하고, 여러
POI 반경이 겹칠 때 교집합 feature/provider scope는 한 번만 업데이트한다. POI가
삭제되면 해당 key의 targeted update도 중단해야 하므로 좌표와 별도의 고유 key를
항상 함께 받는다.

### 5.1 생성

#### `POST /admin/feature-update-requests`

요청:

```json
{
  "scope": {
    "type": "center_radius",
    "center": {"lon": 126.978, "lat": 37.5665},
    "radius_km": 3.0
  },
  "providers": ["python-mois-api", "python-krheritage-api"],
  "dataset_keys": [],
  "update_policy": {
    "mode": "refresh_existing",
    "include_inactive": false,
    "force_provider_call": true,
    "dedup_after_load": true,
    "consistency_check_after_load": true
  },
  "run_mode": "queued",
  "priority": 50,
  "dry_run": false,
  "operator": "local-admin",
  "reason": "광화문 주변 데이터 즉시 갱신"
}
```

응답:

```json
{
  "data": {
    "request_id": "uuid",
    "job_id": "uuid",
    "state": "queued",
    "matched_scope": {
      "feature_count": 134,
      "sigungu_codes": ["11110"]
    },
    "status_url": "/admin/feature-update-requests/uuid"
  },
  "meta": {"duration_ms": 34}
}
```

### 5.2 Scope 타입

#### `feature_ids`

특정 feature 목록을 업데이트한다.

```json
{
  "type": "feature_ids",
  "feature_ids": ["f_1111010100_p_...", "f_1111010100_e_..."]
}
```

처리:

- feature_id 존재 여부를 검증한다.
- feature별 primary source/provider를 찾아 해당 provider refresh를 시도한다.
- provider가 on-demand detail을 지원하지 않으면 source 기반 재검증만 수행한다.

#### `center_radius`

특정 좌표 중심 반경 `n` km 안의 feature를 업데이트한다.

```json
{
  "type": "center_radius",
  "center": {"lon": 126.978, "lat": 37.5665},
  "radius_km": 5.0
}
```

처리:

- `(lon, lat)`를 CTE에서 EPSG:5179로 한 번 변환한다.
- `coord_5179` + `ST_DWithin`으로 대상 feature를 찾는다.
- provider/dataset별로 feature를 group한다.
- provider가 지역 파라미터를 지원하면 해당 scope로 provider call을 줄인다.
- 지원하지 않으면 feature의 source id 기반 detail refresh 또는 dataset queue로
  fallback한다.

#### `sigungu_by_radius`

특정 좌표 중심 반경 `n` km와 교차하거나 그 안에 있는 시군구를 계산하고, 해당 시군구의
feature를 업데이트한다.

```json
{
  "type": "sigungu_by_radius",
  "center": {"lon": 126.978, "lat": 37.5665},
  "radius_km": 10.0,
  "match": "intersects"
}
```

`match`:

- `intersects`: 반경 원과 조금이라도 교차하는 시군구.
- `contains_center`: 중심점이 속한 시군구만.
- `feature_sigungu`: 현재 feature들의 `sigungu_code` 중 반경 안 feature가 속한
  시군구.

처리:

- 행정경계 polygon은 krtour-map DB가 아니라 kraddr-geo가 소유한다.
- krtour-map은 kraddr-geo REST v2 `POST /v2/regions/within-radius`를 호출해
  반경과 교차하는 `sigungu.code` 목록을 받는다.
- kraddr-geo가 반환하는 `sigungu.code`/`sig_cd`는 krtour-map `sigungu_code`와
  같은 5자리 체계이므로 별도 매핑 없이 사용한다.
- 계산된 `sigungu_code` 목록을 request payload에 고정 저장해 재실행 시 결과 drift를
  줄인다.

#### `bbox`

지도 bbox 안 feature를 업데이트한다.

```json
{
  "type": "bbox",
  "min_lon": 126.8,
  "min_lat": 37.4,
  "max_lon": 127.1,
  "max_lat": 37.7
}
```

#### `provider_dataset`

특정 provider/dataset/scope 자체를 업데이트한다.

```json
{
  "type": "provider_dataset",
  "provider": "python-mois-api",
  "dataset_key": "mois_license_features_bulk",
  "sync_scope": "kr"
}
```

#### `cache_target_keys`

외부 앱이 등록한 POI/cache target key 목록을 기준으로 업데이트한다. 삭제된 target은
제외하고, 여러 target 반경의 교집합 feature/provider scope는 한 번만 queue한다.

```json
{
  "type": "cache_target_keys",
  "external_system": "tripmate",
  "target_keys": ["poi_123", "poi_456"],
  "radius_km": 5.0,
  "scope_mode": "center_radius"
}
```

`scope_mode`:

- `center_radius`: 각 target 좌표 중심 반경 `radius_km` 안 feature.
- `sigungu_by_radius`: 각 target 좌표 중심 반경 `radius_km`에 걸치는 시군구의
  feature.

응답의 `matched_scope`에는 `target_count`, `active_target_count`,
`skipped_deleted_keys`, `skipped_missing_keys`, `feature_count`,
`deduped_provider_scopes`를 포함한다.

### 5.3 실행 모드

| 값 | 의미 |
|----|------|
| `queued` | queue에 넣고 Dagster worker/sensor가 순서대로 실행 |
| `now` | 높은 우선순위/즉시 실행 의도를 가진 request. Dagster sensor가 같은 queue에서 감지해 worker run을 생성 |

`dry_run=true`이면 대상 수, provider/dataset group, 예상 job만 반환하고 run을 만들지
않는다.

구현 상태: T-206a에서 `infra.scope_repo.count_features_matching_scope`가
`feature_ids`, `center_radius`, `bbox`, `sigungu_by_radius`, `provider_dataset`의
read-only dry-run 해석을 제공한다. T-206d에서 `cache_target_keys`도 active
`ops.poi_cache_targets` 기반으로 해석하고, missing/deleted/disabled key를
`matched_scope`에 기록한다.

### 5.4 조회

#### `GET /admin/feature-update-requests`

Query:

- `state`
- `scope_type`
- `provider`
- `dataset_key`
- `created_from`
- `created_to`
- `page_size`
- `cursor`

#### `GET /admin/feature-update-requests/{request_id}`

응답에는 연결된 import job, Dagster run id, 대상 feature count, resolved sigungu,
최근 events를 포함한다.

### 5.5 취소와 재실행

#### `POST /admin/feature-update-requests/{request_id}/cancel`

queued 또는 running 요청을 취소 요청 상태로 둔다. running job은 cooperative cancel이다.

#### `POST /admin/feature-update-requests/{request_id}/run-now`

기존 request payload로 즉시 실행을 재요청한다. 이미 running이면 409.

## 6. Dagster 큐잉 방식

권장 기본 방식:

1. API가 `ops.feature_update_requests`와 `ops.import_jobs`를 같은 transaction에 생성.
2. Dagster sensor가 `state='queued'` request를 peek해 request id별 run을 생성.
3. Dagster worker run은 request/import job을 `running`으로 바꾸고 progress를 갱신.
4. 완료 시 `feature_update_requests.state`와 `import_jobs.state`를 같이 terminal로
   갱신.

즉시 실행(`run_mode=now`)도 request와 job row를 먼저 저장한다. 현재 구현은 API가
Dagster run을 직접 만들지 않고, sensor가 같은 queue에서 감지해 worker run을 만든다.

### 6.1 테이블

```sql
CREATE TABLE ops.feature_update_requests (
  request_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  scope_type TEXT NOT NULL,
  scope JSONB NOT NULL,
  providers JSONB NOT NULL DEFAULT '[]'::jsonb,
  dataset_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
  update_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  run_mode TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50,
  state TEXT NOT NULL DEFAULT 'queued',
  dry_run BOOLEAN NOT NULL DEFAULT FALSE,
  matched_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  job_id UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  dagster_run_id TEXT,
  operator TEXT,
  reason TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_feature_update_scope CHECK (
    scope_type IN (
      'feature_ids','center_radius','sigungu_by_radius','bbox','provider_dataset',
      'cache_target_keys'
    )
  ),
  CONSTRAINT ck_feature_update_run_mode CHECK (run_mode IN ('queued','now')),
  CONSTRAINT ck_feature_update_state CHECK (
    state IN ('queued','running','done','failed','cancelled')
  )
);

CREATE INDEX idx_feature_update_state_priority
  ON ops.feature_update_requests (state, priority DESC, created_at);
CREATE INDEX idx_feature_update_created
  ON ops.feature_update_requests (created_at DESC);
CREATE INDEX idx_feature_update_job
  ON ops.feature_update_requests (job_id) WHERE job_id IS NOT NULL;
```

구현 상태: Alembic `0008_feature_update_requests`와
`FeatureUpdateRequestRow`가 이 DDL을 반영한다. `infra.feature_update_repo`는
dry-run preview, request/import job enqueue, priority claim, start/finish/cancel,
단건 조회, keyset 목록 조회를 구현했다(T-206b). `AsyncKrtourMapClient`는
enqueue/get/list/cancel 메서드와 transaction 경계를 노출한다(T-206c). T-206d의
`infra.feature_update_executor`는 runner 주입형 request 실행 본체를 제공한다. T-207a는
admin HTTP router와 OpenAPI schema export를 연결했다. T-208e는
`feature_update_request_queue_sensor`와 `feature_update_request_worker`로 queued/now
request 실행을 Dagster에 연결했다.

## 7. Provider 실행 API와의 관계

`POST /admin/providers/{provider}/datasets/{dataset_key}/runs`는 T-207b 후보였지만
사용자 결정에 따라 별도 구현하지 않는다. provider/dataset 직접 실행이 필요하면
`POST /admin/feature-update-requests`의 `provider_dataset` scope를 사용한다.

`POST /admin/feature-update-requests`는 운영자/TripMate가 쓰기 쉬운 높은 수준 API다.
지리 scope를 provider/dataset/job으로 분해하고 필요한 Dagster run을 큐잉한다.

결과적으로 `ops.import_jobs`와 Dagster run을 사용한다.

## 7.1 Ops 조회 API

T-207d 구현 상태: `krtour-map-admin`은 운영 화면이 필요한 DB 기반 summary와 목록을
`/ops/*`로 제공한다. 이 API는 read-only다. import job 취소/재실행 같은 쓰기 작업은
후속 `/admin/import-jobs` 계약에서 다룬다.

### `GET /ops/metrics`

운영 홈/대시보드용 summary metric을 반환한다.

응답 주요 필드:

- `features_total`, `features_active`, `features_inactive`
- `features_by_kind`
- `source_records_by_provider`
- `import_jobs_by_state`
- `dedup_queue_by_status`
- `dedup_fp_stats`
- `data_integrity_issues`
- `latest_consistency_report`

### `GET /ops/import-jobs`

`ops.import_jobs` 목록을 `created_at DESC, job_id DESC` keyset cursor로 반환한다.

Query:

- `state`: `queued` / `running` / `done` / `failed` / `cancelled`
- `kind`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

### `GET /ops/import-jobs/{job_id}`

`ops.import_jobs` 단건을 반환한다. 없으면 `404`.

### `GET /ops/consistency/reports`

`ops.feature_consistency_reports` 목록을 `started_at DESC, report_id DESC` keyset
cursor로 반환한다. 기존 F1~F4 batch report 조회 표면이다.

Query:

- `severity_max`: `OK` / `WARN` / `ERROR`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

### `GET /ops/consistency/issues`

`ops.data_integrity_violations` 목록을 `detected_at DESC, violation_key DESC` keyset
cursor로 반환한다. Phase 2 F5~F8 계열과 주소/좌표 매칭 이슈는 이 큐를 통해 운영
화면에 노출한다.

Query:

- `status`: `open` / `acknowledged` / `resolved` / `ignored` (기본 `open`)
- `severity`: `info` / `warning` / `error` / `critical`
- `violation_type`
- `provider`
- `dataset_key`
- `feature_id`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

## 7.2 Dagster 운영 요약 API

Admin UI는 Dagster webserver 자체 화면을 `/admin/dagster`에서 iframe으로 embed하고,
같은 화면에 자체 운영 요약 UI를 렌더한다. 자체 요약은 FastAPI가 Dagster GraphQL을
읽어 정규화한 다음 endpoint를 사용한다. embedded Dagster 화면이 로컬 첫 실행
커뮤니티 모달로 가려지지 않도록, summary 조회가 성공하면 backend는 Dagster GraphQL
`setNuxSeen` mutation을 best-effort로 1회 호출한다.

#### `GET /ops/dagster/summary`

Query:

- `run_limit` (`1..50`, 기본 `10`)

응답:

```json
{
  "status": "ok",
  "dagster_url": "http://127.0.0.1:9013",
  "graphql_url": "http://127.0.0.1:9013/graphql",
  "version": "1.13.7",
  "repository_count": 1,
  "job_count": 10,
  "asset_count": 9,
  "schedule_count": 9,
  "sensor_count": 2,
  "run_counts": {"SUCCESS": 3},
  "repositories": [],
  "recent_runs": [],
  "errors": []
}
```

`status`:

| 값 | 의미 |
|----|------|
| `ok` | Dagster GraphQL 조회와 파싱 성공 |
| `unavailable` | Dagster webserver 연결 실패 또는 HTTP 오류. UI는 장애 상태를 표시 |
| `error` | GraphQL 응답은 받았지만 repository/run 조회가 오류를 반환 |

이 endpoint는 Dagster run/job을 제어하지 않는다. 단, embedded UI 표시 안정화를 위한
Dagster NUX seen 처리는 부수효과로 허용한다. feature update request, import job
progress, cancel은 `/admin/feature-update-requests`와 `/admin/import-jobs` 계약으로
분리한다.

## 7.3 POI/cache target API

외부 앱은 POI 좌표만 보내지 않고 고유 key와 좌표를 함께 등록한다. 좌표 precision
차이로 동일 POI가 여러 개 생기는 것을 막기 위해 `external_system + target_key`를
정본 식별자로 사용한다.

### `PUT /admin/poi-cache-targets/{external_system}/{target_key}`

Cache target을 idempotent하게 등록/갱신한다. 같은 key가 같은 normalized 좌표로
들어오면 upsert, 다른 normalized 좌표로 들어오면 기본 409다. 이동을 의도한 경우
`on_conflict="move"`를 명시한다.

### `GET /admin/poi-cache-targets`

Cache target 목록을 반환한다. `external_system`, `update_enabled`,
`include_deleted`, `page_size` 필터를 지원한다.

### `GET /admin/poi-cache-targets/{external_system}/{target_key}`

Cache target 단건을 반환한다. 기본은 active target만 조회하고,
`include_deleted=true`에서 soft-deleted target도 조회할 수 있다.

### `DELETE /admin/poi-cache-targets/{external_system}/{target_key}`

외부 POI 삭제를 반영한다. target을 soft delete하고 이후 targeted update에서 제외한다.

### `GET /features/nearby/by-target`

`external_system` + `target_key`를 받아 주변 `n` km feature 목록을 반환한다. 목록 응답은
summary만 포함하고 `feature.detail` JSONB와 raw payload는 포함하지 않는다. filter는
`radius_km`, `kind`, `category`, `status`, `provider`, `page_size`, `cursor`,
`sort(distance|name|last_updated_at)`다.

자세한 요청/응답, DB 스키마, provider refresh policy는
`docs/poi-cache-update-targets.md`.

## 8. TripMate/public feature read API

T-207e 구현 상태: TripMate에는 다음 public/read API를 제공한다. 기존
`GET /features` raw bbox 응답은 admin frontend 호환용으로 유지하고, 사용자/TripMate
지도 응답은 `GET /features/in-bounds`의 envelope를 정본으로 삼는다.

| API | 목적 |
|-----|------|
| `GET /features/in-bounds` | bbox 기반 사용자 지도 feature. `kind`/`category` 반복 필터, `limit<=5000`, `cluster_unit=null` |
| `GET /features/{feature_id}` | feature 상세 envelope. `updated_at` 포함 |
| `GET /features/search` | `q`(pg_trgm) 또는 `bbox` 기반 검색. keyset cursor |
| `POST /tripmate/features/batch` | 여러 feature_id 상세 batch 조회. `feature_ids<=200`, missing 목록 반환 |
| `POST /admin/feature-update-requests` | 운영/관리 화면에서 특정 지역 refresh 요청 |
| `PUT /admin/poi-cache-targets/{external_system}/{target_key}` | 외부 POI cache target 등록/갱신 |
| `DELETE /admin/poi-cache-targets/{external_system}/{target_key}` | 외부 POI 삭제 반영 |
| `GET /features/nearby/by-target` | 외부 POI key 기준 주변 feature summary 조회 |
| `GET /admin/feature-update-requests/{id}` | refresh 진행 상태 표시 |

TripMate 사용자-facing 응답에는 raw payload, provider key 상태, 내부 error detail,
admin audit log를 노출하지 않는다. batch처럼 TripMate 전용 동작이 필요한 경우만
`/tripmate/*` prefix를 사용한다.

상세 응답에는 aware `updated_at`을 포함한다. 목록 API는 JSONB detail/raw payload를
반환하지 않고, 특정 feature 상세 API에서만 `address`/`detail`/`urls` JSON 데이터를
반환한다.

## 9. Frontend stack 계약

Admin frontend 표준:

- Next.js 16 App Router.
- React 19.
- TypeScript.
- TanStack Query: 서버 상태와 mutation.
- Zustand: map viewport, view mode, filter draft, selected feature 같은 UI 상태.
- Zod: API response parsing, form schema, 좌표/bbox 검증.
- React Hook Form: form 상태와 validation 연결.
- shadcn/ui: Button, Input, Select, Dialog, Sheet, Tabs, Table, Badge, Toast,
  Form, DropdownMenu 등 UI primitive.
- `maplibre-vworld-js`: VWorld 지도.
- `@krtour/map-marker-react`: category/maki marker.

규칙:

- API module은 OpenAPI 타입 또는 Zod schema를 기준으로 작성한다.
- form은 React Hook Form + Zod resolver를 기본으로 한다.
- 원격 데이터는 Zustand에 복제하지 않는다. TanStack Query cache가 source of truth다.
- shadcn/ui 컴포넌트는 프로젝트 registry 기준으로 추가하고, 임의 UI primitive를
  중복 구현하지 않는다.

## 10. React Doctor 필수 검증

Frontend 작업을 포함한 PR은 마무리 전에 React Doctor를 실행한다.

권장 명령:

```bash
cd packages/krtour-map-admin/frontend
npm run lint
npm run type-check
npm run build
npm run doctor
```

아직 `doctor` script가 없다면 첫 frontend PR에서 repo 표준 script를 추가한다.
`react-doctor.config.json`은 저장소 루트 설정을 사용한다.

완료 기준:

- React Doctor 결과를 읽고 실제 위험 항목을 개선한다.
- 의도적으로 무시하는 항목은 PR 설명 또는 `docs/journal.md`에 근거를 남긴다.
- React Doctor를 실행하지 못했으면 사유와 대체 검증을 기록한다.
- 단순 실행만 하고 결과를 방치하지 않는다. "실행 후 검토 및 개선"이 필수다.

## 11. OpenAPI drift와 client 생성

Backend 변경 후:

```bash
python packages/krtour-map-admin/scripts/export_openapi.py \
  --profile all

python packages/krtour-map-admin/scripts/export_openapi.py \
  --profile all --check
```

기본 `--profile admin`은 기존 `packages/krtour-map-admin/openapi.json`만 생성/검증한다.
TripMate/user subset만 갱신할 때는 다음을 쓴다.

```bash
python packages/krtour-map-admin/scripts/export_openapi.py \
  --profile user \
  --output packages/krtour-map-admin/openapi.user.json
```

Frontend 타입 생성:

```bash
cd packages/krtour-map-admin/frontend
npm run gen:types
```

TripMate client 생성은 TripMate 저장소에서 별도 관리한다. krtour-map은
`openapi.user.json`, OpenAPI version, changelog, backward compatibility note를
제공한다.
