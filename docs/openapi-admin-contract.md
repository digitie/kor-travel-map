# openapi-admin-contract.md - Admin 우선 OpenAPI와 Dagster feature update queue

> **상태/역할**: 전 표면 REST 계약의 단일 정본은 [`docs/rest-api.md`](rest-api.md)
> (ADR-048 §9 / T-216a~g)이고, 기계 정본은 `packages/kor-travel-map-api/openapi.json`
> / `openapi.user.json`이다. **본 문서는 admin 부가 뷰**이며, envelope/pagination/
> parameter/error 셰입이 충돌하면 `docs/rest-api.md`와 OpenAPI를 우선한다.

본 문서는 ADR-045 이후 kor-travel-map 독립 프로그램의 OpenAPI 기준이다. 1차 계약은
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
│  - kor-travel-map DB 직접 접근 금지                                    │
│  - OpenAPI client로 feature 조회/업데이트 요청                     │
└───────────────────────────────┬────────────────────────────────────┘
                                │ HTTP / OpenAPI
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ kor-travel-map 독립 프로그램                                           │
│                                                                    │
│  api        FastAPI + OpenAPI (`/features`, `/admin`, `/ops`)       │
│  frontend   Next.js admin UI                                       │
│  dagster    provider sync / feature update / consistency jobs       │
│  postgres   독립 PostgreSQL + PostGIS (`kor_travel_map`)                │
│  rustfs     선택 S3 호환 객체 저장소                                │
└────────────────────────────────────────────────────────────────────┘
```

운영 원칙:

- TripMate는 kor-travel-map을 Python package로 import하지 않는다.
- TripMate는 kor-travel-map PostgreSQL에 직접 연결하지 않는다.
- kor-travel-map OpenAPI가 유일한 프로세스 간 계약이다.
- `kor-travel-map` 메인 패키지의 `AsyncKorTravelMapClient`는 kor-travel-map API/Dagster
  내부 구현에서 사용한다.

## 2. Docker 서비스

초기 Docker Compose 논리 서비스:

| 서비스 | 역할 |
|--------|------|
| `kor-travel-map-api` | FastAPI backend, OpenAPI 제공 |
| `kor-travel-map-frontend` | Next.js admin UI |
| `kor-travel-map-dagster-webserver` | Dagster UI |
| `kor-travel-map-dagster-daemon` | schedules/sensors/runs |
| `kor-travel-map-postgres` | 독립 PostgreSQL 16 + PostGIS 3.5 |
| `kor-travel-map-rustfs` | 선택 객체 저장소. 로컬 표준 포트는 S3 API `12101`, console `12105` |

PostgreSQL 기본 DB:

- app DB: `kor_travel_map`
- Dagster metadata DB: `kor_travel_map_dagster`

같은 Postgres container를 써도 DB는 분리한다. migration은 app DB에 Alembic,
Dagster DB에는 Dagster가 자체 schema를 관리한다.

## 3. OpenAPI 작성 원칙

- OpenAPI 산출물은 admin/debug/ops를 포함한 전체 admin spec
  `packages/kor-travel-map-api/openapi.json`과 TripMate/user-facing subset spec
  `packages/kor-travel-map-api/openapi.user.json` 두 개다.
- admin 전체 scope는 admin UI가 쓰는 `/features`, `/admin`, `/ops`, `/debug` API다.
- user subset은 TripMate가 호출하는 사용자/서비스 read API(`/features/*`,
  `/categories`, `/providers/*`, `/health`, `/version`)와 batch read API만 포함한다.
  전 표면이 `/v1/*` prefix 하에 있다 — ADR-048 무-호환 clean cut(구 unprefixed
  경로/alias 없음). liveness용 `/health`·`/version`만 비버저닝으로 유지한다(정본:
  `docs/rest-api.md` §1, ADR-048 #1). **본 문서의 경로 표기(`/features`, `/admin/*`,
  `/ops/*`, `/debug/*` 등)는 가독성을 위해 `/v1` prefix를 생략한 약기이며 실제 경로는
  모두 `/v1/...`이다.** admin write/read 경로(`/admin/*`)는 admin 전체 spec에만 남긴다.
- `/tripmate/*` 경로는 이미 제거됐다. feature update request의 정본 경로는
  `/admin/feature-update-requests*`이며(본 문서 §6 등 하단 설명과 일치),
  TripMate/user subset에는 존재하지 않는다.
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

에러는 RFC7807 `application/problem+json`이다(정본 `docs/rest-api.md`, ADR-048 §9 /
T-216a~g).

```json
{
  "type": "https://kor-travel-map/errors/validation-error",
  "title": "요청 값이 올바르지 않습니다.",
  "status": 422,
  "detail": "요청 값이 올바르지 않습니다.",
  "code": "VALIDATION_ERROR",
  "request_id": "uuid",
  "errors": []
}
```

메인 라이브러리 DTO에는 `data/meta` 또는 problem+json 래핑을 넣지 않는다. 래핑은 API
패키지 책임이다. admin API는 `X-Request-ID` 요청 헤더가 있으면 같은 값을 problem+json
응답의 `request_id`와 응답 헤더 `X-Request-ID`로 되돌려주고, 없으면 UUID를 생성한다.

### 3.1 응답 셰입 표준 — 전면 통일 (DA-D-03; ADR-048 §9 / T-216a~g로 갱신)

모든 성공 응답(list / 단건 / mutation)은 위 `{data, meta}` envelope를 **단일
표준**으로 쓴다. **예외 없음.** 페이지네이션은 `data`가 아니라 `meta.page`에 둔다:
list는 `meta.page = {page_size, next_cursor, total}`를 담고(`next_cursor`는 keyset,
소진 시 `null`이지만 키는 항상 존재, `total`은 `?include_total=true` opt-in으로 기본
`null`), `count`는 **폐기**한다. in-bounds처럼 payload 해석에 필요한 view metadata는
`meta.cluster = {cluster_unit}`에 둔다. `data`는 `items`/`clusters` 같은 실제
payload만 담는다. `{count, items, next_cursor}` flat 셰입과 bare object 단건은 모두
이 envelope로 수렴한다(정본 `docs/rest-api.md`).

list 성공 예:

```json
{
  "data": {"items": []},
  "meta": {
    "duration_ms": 12,
    "request_id": "uuid",
    "page": {"page_size": 50, "next_cursor": null, "total": null}
  }
}
```

> 단건 meta 비고: `/ops/metrics`는 metric 본문이 `data` + `meta.duration_ms`.
> `/debug/mois-license/{id}`는 cache hit 플래그가 `meta.cached`로 이동.

## 4. API tag 구조

| Tag | Prefix | 용도 |
|-----|--------|------|
| `features` | `/features` | 지도/상세 공통 read |
| `admin-features` | `/admin/features` | feature 검색/비활성화/override, place/event 사용자 요청 추가·수정·soft delete와 검토 queue |
| `admin-providers` | `/admin/providers` | **미구현** — T-207b 취소. provider 강제 실행은 `/admin/feature-update-requests`의 `provider_dataset` scope로 대체(§ 아래) |
| `admin-update-requests` | `/admin/feature-update-requests` | 지리 범위 기반 feature 업데이트 요청 |
| `admin-poi-cache-targets` | `/admin/poi-cache-targets` | 외부 POI/cache target 등록, 삭제, 주변 조회 |
| `admin-dedup` | `/admin/dedup-reviews` | 중복 검토 |
| `admin-issues` | `/admin/issues` | 주소/정합성 이슈 운영 처리(목록/단건/PATCH 7 action). T-DA-13 구현 완료. admin UI는 T-212b 후속 |
| `admin-offline` | `/admin/offline-uploads` | 오프라인 파일 업로드/검증/적재 |
| `admin-backups` | `/admin/backups`, `/admin/restore` | standalone backup artifact 조회, backup/restore command plan, manual-required hot-swap 경계 |
| `ops` | `/ops` | import job 조회, metrics, consistency, `GET /ops/health-deep`(DB/PostGIS readiness; public `/health` liveness와 분리), `GET /ops/system-logs`·`GET /ops/api-call-logs`·`GET /ops/import-job-events`(운영 로그 조회, keyset cursor). api-call-log 적재는 `KOR_TRAVEL_MAP_API_API_CALL_LOG_ENABLED` opt-in middleware(기본 off, best-effort) |
| `dagster` | `/ops/dagster` | Dagster webserver GraphQL 기반 운영 요약 |
| `debug` | `/debug` | ETL preview. `/debug/explain`·`/debug/fixtures` REST/UI는 T-221e에서 제외 결정 |

라우터 노출은 `ApiSettings` flag로 제어한다. `/debug/*`는
`debug_routes_enabled`, `/features/*`는 `features_routes_enabled`,
`/admin/*`는 `admin_routes_enabled`, `/ops/*`와 `/ops/dagster/*`는
`ops_routes_enabled`가 담당한다. `admin_routes_enabled`와
`ops_routes_enabled`가 `None`이면 `features_routes_enabled` 값을 따른다. 따라서 DB 없는
부팅 검증에서는 `features_routes_enabled=False`만으로 features/admin/ops surface가 함께
닫히며, admin/ops만 따로 열어야 하는 특수 검증은 명시 flag로 opt-in한다.

### 4.1 Admin issues / 주소 검토

> **상태: 구현 완료(T-DA-13, 2026-06-07).** `routers/admin_issues.py`가 아래
> 엔드포인트를 모두 제공한다. 목록/단건 읽기는 `ops_repo`/`integrity_violation_repo`,
> kor-travel-geo 정/역지오코딩 + 주소·좌표 덮어쓰기는 `geocoding` + 신규
> `feature_address_repo`(feature.features UPDATE + `ops.feature_overrides` upsert)를
> 쓴다. 모든 성공 응답은 `{data, meta}` envelope. 목록 필터는 `issue_type`/`provider`/
> `dataset_key`/`severity`/`status`/`feature_id` + **`q`**(message/feature_id/
> source_record_key ILIKE) + **bbox**(연결 feature 좌표 4326 GiST `&&`, 네 개의 float
> query 파라미터 `min_lon`/`min_lat`/`max_lon`/`max_lat`; feature_id 없는 이슈는 bbox
> 적용 시 제외) + keyset `cursor`를 지원한다. admin UI(승인/거절 화면)는 T-212b 후속.

`/admin/issues`는 결측/정합성 이슈를 한 건 단위로 처리하는 운영 API다. 특히
kor-travel-geo REST v2 적용 중 발생한 주소/좌표 이슈를 admin UI에서 수동 처리할 수
있어야 한다.

#### 주소 이슈 타입

| issue_type | 의미 |
|------------|------|
| `provider_address_mismatch` | provider 주소와 좌표 기준 kor-travel-geo 주소가 다른 장소로 보임 |
| `provider_address_partial_match` | 시군구/읍면동은 맞지만 상세 주소가 불완전하거나 다름 |
| `geocode_failed` | provider 주소 문자열로 좌표를 찾지 못함 |
| `reverse_geocode_failed` | 좌표로 주소를 찾지 못함 |
| `missing_address` | provider/kor-travel-geo 양쪽 주소 없음 |
| `missing_bjd_code` | kor-travel-geo 결과에 법정동코드 없음 |

#### 필수 엔드포인트

| Method | Path | 용도 |
|--------|------|------|
| GET | `/v1/admin/issues` | 이슈 목록. `issue_type`, `provider`, `dataset_key`, `severity`, `status`, `bbox`, `q`, `cursor` 지원 |
| GET | `/v1/admin/issues/{issue_id}` | 이슈 상세. provider raw 주소, kor-travel-geo 후보, 좌표, 지도 표시 데이터 포함 |
| PATCH | `/v1/admin/issues/{issue_id}` | `resolve`, `ignore`, `reopen`, `retry_geocode`, `retry_reverse_geocode`, `apply_kor_travel_geo_address`, `manual_override` |

`manual_override`는 `feature.features`의 `address`/`coord`/행정코드 컬럼을 갱신하고
`ops.feature_overrides`에 같은 값을 기록해 provider 재적재가 덮어쓰지 않게 한다.
`apply_kor_travel_geo_address`는 좌표 기준 kor-travel-geo reverse 결과를 정본 주소로 채택한다.

T-207c 구현분은 `/admin/features` 목록, deactivate status override, `/admin/dedup-reviews`
목록/결정/merge다. 2026-06-08 추가 구현으로 `/admin/features` 아래에 place/event
사용자 요청 추가·수정·soft delete API가 붙었다. 이 API는 영구 삭제가 아니라
`ops.feature_change_requests`와 `feature.feature_versions`에 audit 가능한 version 1
변경을 남긴다.

### 4.1.1 Feature 사용자 요청 추가·수정·삭제

사용자 요청으로 직접 관리할 수 있는 feature kind는 `place`, `event`만이다. `notice`,
`price`, `weather`, `route`, `area`는 provider 적재 또는 별도 운영 workflow가 정본이다.

처리 모드는 `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE`로 정한다.

| 값 | 의미 |
|----|------|
| `require_review` | 기본값. 요청을 `pending`으로 저장하고 admin 승인 후 적용 |
| `immediate` | 같은 transaction에서 바로 적용하고 `applied`로 저장 |

엔드포인트:

| Method | Path | 설명 |
|--------|------|------|
| GET | `/admin/features/change-requests` | 사용자 요청 변경 목록. `state`, `action`, `q`, `limit` 필터 |
| POST | `/admin/features` | `place`/`event` feature 추가 요청 |
| PATCH | `/admin/features/{feature_id}` | `place`/`event` feature 수정 요청 |
| DELETE | `/admin/features/{feature_id}` | `place`/`event` feature 사용자 요청 soft delete |
| POST | `/admin/features/change-requests/{request_id}/approve` | pending 요청 승인·적용 |
| POST | `/admin/features/change-requests/{request_id}/reject` | pending 요청 거절 |

공통 응답은 `{data: {request}, meta}` envelope다. `request.state`가 `pending`이면 아직
`feature.features`에는 반영되지 않았고, `applied`이면 반영이 끝난 상태다.

저장 우선순위:

- provider 재적재 snapshot은 `data_origin='provider'`, `data_version=0`,
  `feature.feature_versions(version=0)`에 저장한다.
- 사용자 요청 추가·수정·삭제는 `data_origin='user_request'`, `data_version=1`,
  `user_change_kind='add'|'update'|'delete'`,
  `feature.feature_versions(version=1)`에 저장한다.
- provider 재적재가 같은 `feature_id`를 다시 upsert해도 기존 version 1의 유효 필드는
  덮지 않는다. provider payload는 version 0 snapshot으로만 갱신한다.
- 사용자 요청 삭제는 `status='deleted'`, `deleted_at`, `user_deleted_at`,
  `user_deleted_by`, `user_change_request_id`를 기록하는 soft delete다. 이후 provider
  재적재나 snapshot 미포함 정리 작업은 이 row를 되살리지 않는다.

## 4.2 Offline uploads

T-208i 기준 admin UI가 쓰는 offline upload API는 admin 전체 OpenAPI에만 포함한다.
TripMate/user subset에는 포함하지 않는다.

| Method | Path | 용도 |
|--------|------|------|
| POST | `/admin/offline-uploads` | JSON/JSONL `FeatureBundle` 또는 CSV/TSV tabular 파일을 RustFS/S3 `kor-travel-map-uploads` bucket에 저장하고 `ops.offline_uploads` row 생성 |
| GET | `/admin/offline-uploads` | state/provider/dataset keyset 목록 |
| GET | `/admin/offline-uploads/{upload_id}` | 단건 metadata 조회 |
| GET | `/admin/offline-uploads/{upload_id}/preview` | CSV/TSV header/sample preview |
| POST | `/admin/offline-uploads/{upload_id}/validate` | CSV/TSV column mapping validation job 실행 |
| GET | `/admin/offline-uploads/{upload_id}/validation` | validation job payload 조회 |
| POST | `/admin/offline-uploads/{upload_id}/load` | Dagster GraphQL `launchRun`으로 `offline_upload_load` job 실행 |

지원 업로드 포맷은 JSON/JSONL `FeatureBundle` dump와 CSV/TSV tabular 원본이다.
`POST /admin/offline-uploads`는 `KOR_TRAVEL_MAP_OFFLINE_UPLOAD_MAX_BYTES` 상한을
초과하면 `413`을 반환한다. 기본값은 `104857600` bytes(100 MiB)이며,
`Content-Length` 선차단과 실제 file read 상한을 함께 적용한다.
object write 후 `ops.offline_uploads` row 생성이 실패하면 같은 요청에서 방금 쓴
object를 보상 삭제한다. 정상 등록된 offline upload 원본은 D-14 기준으로 계속
무기한 보존한다.
CSV/TSV는 load 전에 validation job이 저장한 column mapping과 성공 상태가 필요하다.
행에 `bjd_code`가 없으면 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL`로 주입한 kor-travel-geo REST v2
`POST /v2/geocode` 또는 좌표 reverse 결과를 사용해 법정동코드를 보강한다. resolver가
없거나 결과에도 법정동코드가 없으면 validation issue로 남기고 load를 막는다.
offline upload `cancelled`는 현재 cancel API가 붙기 전까지 reserved terminal state다.

## 4.3 Backup/restore

T-209e-c 기준 admin UI가 쓰는 backup/restore API는 admin 전체 OpenAPI에만 포함한다.
TripMate/user subset에는 포함하지 않는다. API는 standalone Docker app의 cold backup
산출물을 읽고 command plan을 반환한다. host command 실행은 기본 비활성이며,
`KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED=true`와 요청 body `execute=true`가 모두 있어야
실행된다.

| Method | Path | 용도 |
|--------|------|------|
| GET | `/admin/backups` | `data/backups/<backup_id>` artifact 목록. manifest status, created time, size, checksum count 포함 |
| GET | `/admin/backups/{backup_id}` | artifact 단건 상세 |
| POST | `/admin/backups` | cold backup command plan 생성 또는 opt-in 실행 |
| POST | `/admin/restore/{backup_id}` | staging restore command plan 생성 또는 opt-in 실행 |
| POST | `/admin/restore/{backup_id}/swap` | 운영 DSN/volume switch 자동 실행 없이 manual-required hot-swap 승인 경계 반환 |

`POST /admin/backups`와 `POST /admin/restore/{backup_id}`의 성공 응답은
`{data, meta}` envelope다. `data.command`는 `cwd`, `command`, `env`, `enabled`를 담아
운영자가 실행 전 실제 host command를 감사할 수 있게 한다. `execute=true`인데 서버
설정이 비활성이면 `503 BACKUP_COMMAND_DISABLED` error envelope를 반환한다.
`/admin/restore/{backup_id}/swap`은 staging restore smoke/count 검증 후 operator가
수동으로 운영 DSN/volume switch를 승인해야 함을 알리는 `manual_required` 상태만
반환한다.

## 5. Feature update request

Feature update request는 OpenAPI로 Dagster feature update job을 제어하는 표준
엔드포인트다. 운영자는 admin UI나 내부 운영 automation에서 호출한다. TripMate
사용자/서비스 표면에는 노출하지 않는다.

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

`run_mode="now"`에서 동일 scope advisory lock이 이미 점유되어 있으면 queued fallback
없이 `409`를 반환한다. 응답은 공통 RFC7807 `application/problem+json`을 사용한다(§3).

```json
{
  "type": "https://kor-travel-map/errors/lock-busy",
  "title": "동일 feature update scope가 이미 실행 중입니다.",
  "status": 409,
  "detail": "동일 feature update scope가 이미 실행 중입니다.",
  "code": "LOCK_BUSY",
  "request_id": "uuid",
  "errors": [],
  "details": {"retry_after_seconds": 15}
}
```

HTTP header에도 `Retry-After: 15`를 포함한다.

요청 schema는 엄격하다.

- `scope`는 `type` discriminator를 가진 union이며, 정의되지 않은 scope field는
  `422 VALIDATION_ERROR`로 거절한다. `center_radius`/`sigungu_by_radius`는 root
  `lon`/`lat`가 아니라 `center: {"lon": ..., "lat": ...}`만 허용한다.
- 좌표 범위는 `lon=-180..180`, `lat=-90..90`, `radius_km`은 `0 < radius_km <= 500`
  으로 제한한다. `bbox`는 `min_lon <= max_lon`, `min_lat <= max_lat`를 요구한다.
- `feature_ids`는 최대 1000개, `cache_target_keys.target_keys`는 최대 500개다.
  `providers`는 최대 32개, `dataset_keys`는 최대 64개다.
- `update_policy`는 `mode`, `include_inactive`, `force_provider_call`,
  `dedup_after_load`, `consistency_check_after_load`,
  `prevent_provider_reactivation`만 허용한다. 알 수 없는 key는 queue 생성 전에
  거절한다.

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

- 행정경계 polygon은 kor-travel-map DB가 아니라 kor-travel-geo가 소유한다.
- kor-travel-map은 kor-travel-geo REST v2 `POST /v2/regions/within-radius`를 호출해
  반경과 교차하는 `sigungu.code` 목록을 받는다.
- kor-travel-geo가 반환하는 `sigungu.code`/`sig_cd`는 kor-travel-map `sigungu_code`와
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
2. Dagster sensor가 `status='queued'` request를 peek해 request id별 run을 생성.
3. Dagster worker run은 request/import job을 `running`으로 바꾸고 progress를 갱신.
4. 완료 시 `feature_update_requests.status`와 `import_jobs.status`를 같이 terminal로
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
  status TEXT NOT NULL DEFAULT 'queued',
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
  CONSTRAINT ck_feature_update_status CHECK (
    status IN ('queued','running','done','failed','cancelled')
  )
);

CREATE INDEX idx_feature_update_status_priority
  ON ops.feature_update_requests (status, priority DESC, created_at);
CREATE INDEX idx_feature_update_created
  ON ops.feature_update_requests (created_at DESC);
CREATE INDEX idx_feature_update_job
  ON ops.feature_update_requests (job_id) WHERE job_id IS NOT NULL;
```

구현 상태: Alembic `0008_feature_update_requests`와
`FeatureUpdateRequestRow`가 이 DDL을 반영한다. `infra.feature_update_repo`는
dry-run preview, request/import job enqueue, priority claim, start/finish/cancel,
단건 조회, keyset 목록 조회를 구현했다(T-206b). `AsyncKorTravelMapClient`는
enqueue/get/list/cancel 메서드와 transaction 경계를 노출한다(T-206c). T-206d의
`infra.feature_update_executor`는 runner 주입형 request 실행 본체를 제공한다. T-207a는
admin HTTP router와 OpenAPI schema export를 연결했다. T-208e는
`feature_update_request_queue_sensor`와 `feature_update_request_worker`로 queued/now
request 실행을 Dagster에 연결했다.

## 7. Provider 실행 API와의 관계

`POST /admin/providers/{provider}/datasets/{dataset_key}/runs`는 T-207b 후보였지만
사용자 결정에 따라 별도 구현하지 않는다. provider/dataset 직접 실행이 필요하면
운영자는 `POST /admin/feature-update-requests`의 `provider_dataset` scope를 사용한다.
TripMate 사용자/서비스 표면에는 feature update request를 노출하지 않는다.

feature update request는 운영자가 쓰기 쉬운 높은 수준 API다.
지리 scope를 provider/dataset/job으로 분해하고 필요한 Dagster run을 큐잉한다.

결과적으로 `ops.import_jobs`와 Dagster run을 사용한다.

T-221d 구현 상태:

- `GET /ops/providers`: provider×dataset×scope sync state와
  `ops.provider_refresh_policies` 요약을 함께 반환한다. 사용자 표면 `GET /providers`와
  달리 ops 전용 next_run/policy link를 포함하되 cursor는 목록에서 숨긴다.
- `GET /ops/providers/{provider}`: provider별 dataset 상세. 이 endpoint는 ops 전용이라
  `sync_states[].cursor`, refresh policy, 최근 `provider_dataset` update request summary,
  관련 link를 포함한다.
- `GET /admin/provider-refresh-policies`: query `provider`, `enabled`, `limit`으로 policy
  목록을 반환한다.
- `GET /admin/provider-refresh-policies/{provider}/{dataset_key}`: policy 단건 조회.
- `PUT /admin/provider-refresh-policies/{provider}/{dataset_key}`: policy full upsert.
  `system_interval_seconds`/`optimal_interval_seconds`는 `min_interval_seconds`와
  선언된 request/min/hour/day floor보다 짧을 수 없다.

`GET /admin/feature-update-requests`의 `provider`/`dataset_key` filter는
`providers`/`dataset_keys` JSON array뿐 아니라 `scope.type='provider_dataset'`의
`scope.provider`/`scope.dataset_key`도 매칭한다.

## 7.1 Ops 조회 API

T-207d 구현 상태: `kor-travel-map-admin`은 운영 화면이 필요한 DB 기반 summary와 목록을
`/ops/*`로 제공한다. import job 조회 정본은 `/ops/import-jobs`이며, active job
취소는 `POST /ops/import-jobs/{job_id}/cancel`로 제공한다.

실시간 signal 채널 `WS /ops/live`는 WebSocket이므로 `openapi.json` `paths`에는
포함되지 않는다. REST DTO source of truth는 계속 아래 endpoint이며, live frame은
admin frontend의 query invalidation signal로만 사용한다.

### `GET /ops/metrics`

운영 홈/대시보드용 summary metric을 반환한다.

응답 주요 필드:

- `features_total`, `features_active`, `features_inactive`
- `features_by_kind`
- `source_records_by_provider`
- `import_jobs_by_status`
- `dedup_queue_by_status`
- `dedup_fp_stats`
- `data_integrity_issues`
- `latest_consistency_report`

### `GET /ops/import-jobs`

`ops.import_jobs` 목록을 `created_at DESC, job_id DESC` keyset cursor로 반환한다.

Query:

- `status`: `queued` / `running` / `done` / `failed` / `cancelled`
- `kind`
- `load_batch_id`: UUID. T-200 full-load batch 단위 조회.
- `parent_job_id`: UUID. root import job 아래 child job 조회.
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

각 item은 `job_id`, `kind`, `load_batch_id`, `parent_job_id`, `payload`, `status`,
`progress`, `current_stage`, `source_checksum`, `error_message`, timestamp 4종,
`status_url`, `links`를 포함한다. `links`는 `self`, `events`, `cancel`(active 상태만),
`parent_job`, `load_batch`, `feature_update_request`, `offline_upload`, `dagster_run`
같은 관련 API/운영 링크를 best-effort로 제공한다.

### `GET /ops/import-jobs/{job_id}`

`ops.import_jobs` 단건을 반환한다. 없으면 `404`.

### `GET /ops/import-job-events`

`ops.import_job_events` 전역 event stream을 `occurred_at DESC, event_id DESC` keyset
cursor로 반환한다. `/ops/logs`의 Job events 탭은 이 표면을 사용해 provider 실패를
한 화면에서 훑고, item의 `job_id`를 `/ops/import-jobs/{job_id}` 상세로 연결한다.

Query:

- `job_id`: UUID. 특정 job으로 좁힐 때 사용.
- `level`: `debug` / `info` / `warning` / `error` / `critical`
- `provider`
- `dataset_key`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

각 item은 `event_id`, `job_id`, `provider`, `dataset_key`, `feature_id`, `stage`,
`level`, `code`, `message`, `payload`, `occurred_at`을 포함한다.

### `GET /ops/import-jobs/{job_id}/events`

`ops.import_job_events` event timeline을 `occurred_at DESC, event_id DESC` keyset
cursor로 반환한다. job이 없으면 `404`.

Query:

- `level`: `debug` / `info` / `warning` / `error` / `critical`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

각 item은 `event_id`, `job_id`, `provider`, `dataset_key`, `feature_id`, `stage`,
`level`, `code`, `message`, `payload`, `occurred_at`을 포함한다.

### `POST /ops/import-jobs/{job_id}/cancel`

queued/running job을 best-effort로 `cancelled` 전이한다. 이미 `done` / `failed` /
`cancelled`인 job은 `409`, 없는 job은 `404`를 반환한다. 실행 중인 외부 프로세스를
강제 종료하지 못할 수 있으므로 cancel event payload에는 `best_effort=true`가 남는다.

요청 body(선택):

- `operator`
- `reason`

응답은 갱신된 `OpsImportJobRecord` envelope다.

### `WS /ops/live` (OpenAPI 제외)

Admin UI 내부망 전용 WebSocket signal 채널이다. query `topics`는 comma-separated이며,
client command는 JSON object `{ "type": "subscribe" | "unsubscribe" | "replace" | "ping",
"topics": [...] }`다. `poll_interval_ms`는 `1000..30000` 범위로 clamp된다.

지원 topic:

- `import_jobs`
- `import_job:{job_id}`
- `import_job_events:{job_id}`
- `feature_update_requests`
- `feature_update_request:{request_id}`
- `offline_uploads`
- `offline_upload:{upload_id}`
- `dagster_runs`
- `dagster_run:{run_id}`

서버 frame:

- `hello`: 연결 직후 현재 topic과 poll 간격.
- `snapshot`: 최초 또는 topic 변경 직후 전체 topic snapshot.
- `update`: revision이 바뀐 topic만 전송.
- `heartbeat`: 변경이 없어도 연결 생존을 알림.
- `error`: live snapshot 조회/command 오류.

frontend는 frame `data`를 화면 상태로 직접 저장하지 않고, topic에 해당하는 TanStack
Query key를 invalidate한다. WebSocket이 막힌 환경에서는 기존 REST polling이 fallback이다.

### `GET /ops/consistency/reports`

`ops.feature_consistency_reports` 목록을 `started_at DESC, report_id DESC` keyset
cursor로 반환한다. 기존 F1~F4 batch report 조회 표면이다.

Query:

- `severity_max`: `OK` / `WARN` / `ERROR`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

### `GET /ops/consistency/issues`

`ops.data_integrity_violations` 목록을 `detected_at DESC, issue_id DESC` keyset
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
읽어 정규화한 다음 endpoint를 사용한다.

Dagster GraphQL 호출 대상은 SSRF 방지를 위해 backend 설정에서 검증한다.
`KOR_TRAVEL_MAP_API_DAGSTER_URL`과 `KOR_TRAVEL_MAP_API_DAGSTER_GRAPHQL_URL`은
`http`/`https` scheme만 허용하고, host는
`KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS` allowlist에 있어야 한다. 기본 allowlist는
로컬/Docker 내부 host(`127.0.0.1`, `localhost`, `::1`, `dagster`)다.
GraphQL endpoint는 `/graphql` path로 끝나야 한다.
offline upload load GraphQL launch selector의 repository 이름은
`KOR_TRAVEL_MAP_API_DAGSTER_REPOSITORY_NAME`, repository location 이름은
`KOR_TRAVEL_MAP_API_DAGSTER_REPOSITORY_LOCATION_NAME`으로 명시 override할 수 있다.

#### `GET /ops/dagster/summary`

Dagster repository, asset, schedule/sensor, recent run 정보를 조회한다. 이 endpoint는
GET 안전성을 지키기 위해 Dagster mutation을 호출하지 않는다.

Query:

- `run_limit` (`1..50`, 기본 `10`)

응답(`data` 발췌):

```json
{
  "data": {
    "status": "ok",
    "dagster_url": "http://127.0.0.1:12702",
    "graphql_url": "http://127.0.0.1:12702/graphql",
    "version": "1.13.7",
    "repository_count": 1,
    "job_count": 10,
    "asset_count": 9,
    "schedule_count": 9,
    "sensor_count": 2,
    "run_counts": {"SUCCESS": 3},
    "repositories": [
      {
        "name": "__repository__",
        "location_name": "kortravelmap.dagster.definitions",
        "schedules": [
          {
            "name": "nightly_feature_refresh",
            "status": "RUNNING",
            "recent_ticks": [
              {
                "tick_id": "1",
                "status": "SUCCESS",
                "timestamp": 1710000000.0,
                "run_ids": ["run-1"]
              }
            ]
          }
        ],
        "sensors": []
      }
    ],
    "recent_runs": [],
    "errors": []
  },
  "meta": {"duration_ms": 12}
}
```

`repositories[].schedules[].recent_ticks`와 `repositories[].sensors[].recent_ticks`는
Dagster schedule/sensor tick history의 최근 3건이다. tick은 `status`, `timestamp`,
`run_ids`, `run_keys`, `skip_reason`, `error`를 포함할 수 있고, run id가 있으면
`GET /ops/dagster/runs/{run_id}`로 실패 상세를 조회한다.

`status`:

| 값 | 의미 |
|----|------|
| `ok` | Dagster GraphQL 조회와 파싱 성공 |
| `unavailable` | Dagster webserver 연결 실패 또는 HTTP 오류. UI는 장애 상태를 표시 |
| `error` | GraphQL 응답은 받았지만 repository/run 조회가 오류를 반환 |

이 endpoint는 Dagster run/job을 제어하지 않는다. feature update request는
`/admin/feature-update-requests`, import job progress는 `/ops/import-jobs` 계약으로
분리한다. job cancel은 아직 별도 backend task가 필요하다.

#### `GET /ops/dagster/runs/{run_id}`

Dagster `runOrError`와 event log를 조회한다. schedule/sensor tick 또는 recent run에서
선택한 run의 실패 원인과 최근 event를 admin UI에 표시하기 위한 읽기 전용 endpoint다.

Path:

- `run_id`

Query:

- `event_limit` (`1..200`, 기본 `50`)

응답(`data` 발췌):

```json
{
  "data": {
    "status": "ok",
    "dagster_url": "http://127.0.0.1:12702",
    "graphql_url": "http://127.0.0.1:12702/graphql",
    "checked_at": "2026-06-07T09:00:00Z",
    "run": {
      "run_id": "run-1",
      "job_name": "__ASSET_JOB",
      "status": "FAILURE",
      "tags": {"dagster/job": "__ASSET_JOB"}
    },
    "events": [
      {
        "event_type": "RunFailureEvent",
        "dagster_event_type": "RUN_FAILURE",
        "message": "run failed",
        "level": "ERROR",
        "error": {"message": "boom", "stack": [], "class_name": "RuntimeError"}
      }
    ],
    "event_cursor": "cursor",
    "event_has_more": false,
    "errors": []
  },
  "meta": {"duration_ms": 15}
}
```

`status`는 `ok`, `not_found`, `unavailable`, `error` 중 하나다. 이 endpoint도
Dagster run 재실행, cancel, mutation을 수행하지 않는다.

#### `POST /ops/dagster/nux-seen`

embedded Dagster 화면이 로컬 첫 실행 커뮤니티 모달로 가려지지 않도록 Dagster GraphQL
`setNuxSeen` mutation을 호출한다. summary GET의 부수효과를 없애기 위해 명시 POST로
분리했다. Admin UI는 `/admin/dagster` summary가 정상 조회되면 이 endpoint를 한 번
호출한다.

응답:

```json
{
  "status": "ok",
  "dagster_url": "http://127.0.0.1:12702",
  "graphql_url": "http://127.0.0.1:12702/graphql",
  "checked_at": "2026-06-05T09:00:00Z",
  "seen": true,
  "errors": []
}
```

`status` 의미는 summary와 동일하다. 설정 오류나 GraphQL 오류는 `error`, 연결 실패는
`unavailable`이다.

## 7.3 POI/cache target API

외부 앱은 POI 좌표만 보내지 않고 고유 key와 좌표를 함께 등록한다. 좌표 precision
차이로 동일 POI가 여러 개 생기는 것을 막기 위해 `external_system + target_key`를
정본 식별자로 사용한다.

### `PUT /admin/poi-cache-targets/{external_system}/{target_key}`

Cache target을 idempotent하게 등록/갱신한다. 같은 key가 같은 normalized 좌표로
들어오면 upsert, 다른 normalized 좌표로 들어오면 기본 409다. 이동을 의도한 경우
`on_conflict="move"`를 명시한다.

요청 body의 `provider_overrides`는 provider 또는 `provider:dataset_key` 문자열 key
최대 64개만 허용한다. 각 값은 `targeted_policy`, interval/rate-limit 계열 숫자,
`max_concurrent`, `note`만 받을 수 있고 unknown key는 `422`다. `metadata`는 Pydantic
내부에서 `metadata_` 필드+alias로 다루며, 외부 JSON 필드명은 계속 `metadata`다.
허용 metadata key는 `tripmate_poi_id`, `external_ref`, `source_url`, `labels`, `note`
뿐이다.

### `GET /admin/poi-cache-targets`

Cache target 목록을 반환한다. `external_system`, `update_enabled`,
`include_deleted`, `page_size`, `cursor` 필터를 지원한다. 목록 정렬은
`updated_at DESC, target_id DESC`이며 응답의 `next_cursor`를 다음 요청 `cursor`로
전달하는 keyset pagination이다. cursor decode 실패는 DB 조회 전에 `422`로 응답한다.

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

D-7 공개 응답 분리에 따라 응답 `target`은 `external_system`, `target_key`, `lon`,
`lat`만 포함한다. 주변 feature item은 경량 feature 필드와 `distance_m`만 포함하고,
`primary_provider`, `primary_dataset_key`, target `target_id`, `refresh_policy`,
`update_enabled`, `next_eligible_refresh_at` 같은 운영/내부 필드는 노출하지 않는다.

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
| `POST /features/batch` | 여러 feature_id 상세 batch 조회(service read, ServiceToken). `feature_ids<=200`, missing 목록 반환 |
| `PUT /admin/poi-cache-targets/{external_system}/{target_key}` | 외부 POI cache target 등록/갱신 |
| `DELETE /admin/poi-cache-targets/{external_system}/{target_key}` | 외부 POI 삭제 반영 |
| `GET /features/nearby/by-target` | 외부 POI key 기준 주변 feature summary 조회 |

Feature update request는 더 이상 TripMate/public 표면에 포함하지 않는다.
정본 운영 경로는 `/admin/feature-update-requests*`다. TripMate 사용자 제안 큐는
TripMate app DB가 소유하고, 운영자 승인 후 admin API로 refresh scope를 실행한다.

TripMate 사용자-facing 응답에는 raw payload, provider key 상태, provider/dataset 내부
식별자, dedup/sibling linkage, target refresh policy, 내부 error detail, admin audit log를
노출하지 않는다. `/tripmate/*` namespace는 제거됐다(kor-travel-map은 TripMate 전용이 아니다) —
batch 같은 service read는 `POST /features/batch`(ServiceToken route-level gate)로 일반화한다.

상세 응답에는 aware `updated_at`을 포함한다. 목록 API는 JSONB detail/raw payload를
반환하지 않고, 특정 feature 상세 API에서만 `address`/`detail`/`urls` JSON 데이터를
반환한다.

### 8.1 TripMate T-130 공개 뷰

TripMate T-130(`/public/*`)은 현재 사용자 subset에 없는 해수욕장/축제 전용 뷰를
요구한다. 계약은 [`docs/public-views-api.md`](public-views-api.md)에 둔다.
T-222b(2026-06-12)부터 다음 표면은 `openapi.user.json` 사용자 profile에 포함한다.

- `GET /v1/public/beaches`
- `GET /v1/public/beaches/map-markers`
- `GET /v1/public/beaches/{feature_id}`
- `GET /v1/public/festivals/monthly`
- `GET /v1/public/festivals/map-markers`
- `GET /v1/public/festivals/{feature_id}`

### 8.2 curated_features read profile

T-223c-1(2026-06-12)부터 테마형 큐레이션 read 표면은 TripMate import용
사용자 profile에 포함한다. write/admin 표면(`/v1/admin/curated-*`)은 내부 운영
profile에만 둔다.

- `GET /v1/curated-themes`
- `GET /v1/curated-sources`
- `GET /v1/curated-features`
- `GET /v1/curated-features/{curated_feature_id}`
- `GET /v1/curated-features/{curated_feature_id}/tripmate-copy`

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
- `@kor-travel-map/map-marker-react`: category/maki marker.

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
cd packages/kor-travel-map-admin/frontend
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
python packages/kor-travel-map-api/scripts/export_openapi.py \
  --profile all

python packages/kor-travel-map-api/scripts/export_openapi.py \
  --profile all --check
```

기본 `--profile admin`은 기존 `packages/kor-travel-map-api/openapi.json`만 생성/검증한다.
TripMate/user subset만 갱신할 때는 다음을 쓴다.

```bash
python packages/kor-travel-map-api/scripts/export_openapi.py \
  --profile user \
  --output packages/kor-travel-map-api/openapi.user.json
```

Frontend 타입 생성:

```bash
cd packages/kor-travel-map-admin/frontend
npm run gen:types
```

TripMate client 생성은 TripMate 저장소에서 별도 관리한다. kor-travel-map은
`openapi.user.json`, OpenAPI version, changelog, backward compatibility note를
제공한다.
