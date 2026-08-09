# openapi-admin-contract.md - Admin 우선 OpenAPI와 Dagster feature update queue

> **상태/역할**: 전 표면 REST 계약의 단일 정본은 [`docs/architecture/rest-api.md`](rest-api.md)
> (ADR-048 §9 / T-216a~g)이고, 기계 정본은 `packages/kor-travel-map-api/openapi.json`
> / `openapi.user.json`이다. **본 문서는 admin 부가 뷰**이며, envelope/pagination/
> parameter/error 셰입이 충돌하면 `docs/architecture/rest-api.md`와 OpenAPI를 우선한다.

본 문서는 ADR-045 이후 kor-travel-map 독립 프로그램의 OpenAPI 기준이다. 1차 계약은
admin UI가 실제로 사용하는 API를 기준으로 작성한다. PinVi 연동 API는 이 계약을
바탕으로 필요한 공개 필드, batch 조회, 캐시 정책을 후속으로 확장한다.

외부 POI 기반 캐시 갱신 타깃(`external_system + target_key + 좌표 + 반경`)과
provider별 refresh policy/rate limit 상세는
[`docs/poi-cache-update-targets.md`](../poi-cache-update-targets.md)를 함께 따른다.

## 1. 운영 모델

```
┌────────────────────────────────────────────────────────────────────┐
│ PinVi                                                           │
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

- PinVi는 kor-travel-map을 Python package로 import하지 않는다.
- PinVi는 kor-travel-map PostgreSQL에 직접 연결하지 않는다.
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
  `packages/kor-travel-map-api/openapi.json`과 PinVi/user-facing subset spec
  `packages/kor-travel-map-api/openapi.user.json` 두 개다.
- admin 전체 scope는 admin UI가 쓰는 `/features`, `/admin`, `/ops`, `/debug` API다.
- user subset은 PinVi가 호출하는 사용자/서비스 read API(`/features/*`,
  `/categories`, `/providers/*`, `/health`, `/version`)와 batch read API만 포함한다.
  전 표면이 `/v1/*` prefix 하에 있다 — ADR-048 무-호환 clean cut(구 unprefixed
  경로/alias 없음). liveness용 `/health`·`/version`만 비버저닝으로 유지한다(정본:
  `docs/architecture/rest-api.md` §1, ADR-048 #1). **본 문서의 경로 표기(`/features`, `/admin/*`,
  `/ops/*`, `/debug/*` 등)는 가독성을 위해 `/v1` prefix를 생략한 약기이며 실제 경로는
  모두 `/v1/...`이다.** admin write/read 경로(`/admin/*`)는 admin 전체 spec에만 남긴다.
- `/tripmate/*` 경로는 이미 제거됐다. feature update request의 정본 경로는
  `/ops/pipeline/requests*`이며 PinVi/user subset에는 존재하지 않는다. C6B 이전
  `/ops/import-jobs*`·`/ops/dagster*`를 설명하는 하단 절은 명시된 이전 계약 이력일 뿐
  현행 OpenAPI 계약이 아니다.
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

에러는 RFC7807 `application/problem+json`이다(정본 `docs/architecture/rest-api.md`, ADR-048 §9 /
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
이 envelope로 수렴한다(정본 `docs/architecture/rest-api.md`).

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
| `admin-poi-cache-targets` | `/admin/poi-cache-targets` | 외부 POI/cache target 등록, 삭제, 주변 조회 |
| `admin-dedup` | `/admin/features/dedup-reviews` | 중복 검토 |
| `admin-issues` | `/admin/issues` | 주소/정합성 이슈 운영 처리(목록/단건/PATCH 7 action). T-DA-13 구현 완료. admin UI는 T-212b 후속 |
| `admin-offline` | `/admin/offline-uploads` | 오프라인 파일 업로드/검증/적재 |
| `admin-backups` | `/admin/backups`, `/admin/restore` | standalone backup artifact 조회, backup/restore command plan, manual-required hot-swap 경계 |
| `ops-datasets` | `/ops/datasets` | provider×dataset 상태·정책·fixture preview 통합 |
| `ops-pipeline` | `/ops/pipeline` | 실행·event·Dagster·schedule 조회와 조작 통합 |
| `ops` | `/ops` | metrics, consistency, health-deep, system/API log 관측 read |
| `debug` | `/debug` | MOIS 적재 raw detail read. ETL preview는 ops-datasets로 이동 |

라우터 노출은 `ApiSettings` flag로 제어한다. `/debug/*`는
`debug_routes_enabled`, `/features/*`는 `features_routes_enabled`,
`/admin/*`는 `admin_routes_enabled`, `/ops/*`는
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
| ~~`provider_address_mismatch`~~ | **발행 중단 (T-VN-H28B)** — 이름 substring 축은 실측 탐지력 0. 기존 행은 보존 |
| ~~`provider_address_partial_match`~~ | **발행 중단 (T-VN-H28B)** |
| `provider_address_region_disagreement` | provider 주소 문자열이 지목하는 행정구역이 좌표 reverse 후보 어디에도 없음 |
| `admin_code_stale_{sido,sigungu,emd}` | payload 행정코드가 좌표 reverse 결과와 불일치 — **위치 오류가 아니라 producer 캐시 staleness** |
| `reverse_geocode_unavailable` | 좌표 reverse 실패했으나 provider 행정코드로 적재됨 — 좌표 정합성 미확인 |
| `geocode_failed` | provider 주소 문자열로 좌표를 찾지 못함 |
| `reverse_geocode_failed` | 좌표로 주소를 찾지 못함 |
| `missing_address` | provider/kor-travel-geo 양쪽 주소 없음 |
| `missing_bjd_code` | kor-travel-geo 결과에 법정동코드 없음 |

> `issue_type`에는 allowlist·enum이 없다(`ops_repo`는 정확 일치 필터만, API는 free-form
> `str`). 새 producer가 code를 추가하면 별도 조치 없이 `/admin/issues`에 노출된다.
> 주소 검증 code의 payload·dedupe 규약은 `data-model.md` §9.5 참조 (T-VN-H30A).

#### 필수 엔드포인트

| Method | Path | 용도 |
|--------|------|------|
| GET | `/v1/admin/issues` | 이슈 목록. `issue_type`, `provider`, `dataset_key`, `severity`, `status`, `bbox`, `q`, `cursor` 지원 |
| GET | `/v1/admin/issues/{issue_id}` | 이슈 상세. provider raw 주소, kor-travel-geo 후보, 좌표, 지도 표시 데이터 포함 |
| PATCH | `/v1/admin/issues/{issue_id}` | `resolve`, `ignore`, `reopen`, `retry_geocode`, `retry_reverse_geocode`, `apply_kor_travel_geo_address`, `manual_override` |

`manual_override`는 `feature.features`의 `address`/`coord`/행정코드 컬럼을 갱신하고
`ops.feature_overrides`에 같은 값을 기록해 provider 재적재가 덮어쓰지 않게 한다.
`apply_kor_travel_geo_address`는 좌표 기준 kor-travel-geo reverse 결과를 정본 주소로 채택한다.

T-VN-34C 이후 `/admin/features`는 세 상태 축 AND filter와 `/state` patch/retire,
`/state/reactivate`, `/state/transitions`를 정본으로 둔다. 과거 deactivate status override는
폐기됐다. `/admin/features/dedup-reviews` 목록/결정/merge와 place/event
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
| GET | `/admin/features/{feature_id}/revision` | correction용 현재 `row_revision`과 raw strong `ETag` 조회 |
| POST | `/admin/features` | `place`/`event` feature 추가 요청 |
| PATCH | `/admin/features/{feature_id}` | `place`/`event` feature 수정 요청 |
| DELETE | `/admin/features/{feature_id}` | `place`/`event` feature 사용자 요청 soft delete |
| POST | `/admin/features/change-requests/{request_id}/approve` | pending 요청 승인·적용 |
| POST | `/admin/features/change-requests/{request_id}/reject` | pending 요청 거절 |

공통 응답은 `{data: {request}, meta}` envelope다. `request.state`가 `pending`이면 아직
`feature.features`에는 반영되지 않았고, `applied`이면 반영이 끝난 상태다.

수정·삭제 consumer는 `/revision` 응답 header의 raw `ETag`와 body `row_revision`, 이어서 읽은
feature detail snapshot을 불변 `CorrectionBasis`로 묶는다. revision과 detail의
`feature.row_revision`이 다르면 제한 횟수만 다시 읽고, 일치하지 않는 상태에서는 mutation을
허용하지 않는다. PATCH/DELETE는 그 basis의 raw `ETag`를 `If-Match`에 그대로 전달하며 submit
시점에 `/revision`을 다시 호출해 최신값으로 바꾸지 않는다.

stale basis는 RFC7807 `412 Precondition Failed`로 거부한다. admin UI는 작성 중인 draft를
보존하고 자동 재시도하지 않으며, 운영자가 명시적으로 최신값 다시 불러오기를 선택한 뒤에만
새 detail·basis를 form에 적용한다. T-VN-58은 이 소비 규칙만 교정하며 DB와 OpenAPI schema를
변경하지 않는다.

저장 우선순위:

- provider 재적재 snapshot은 `data_origin='provider'`, `data_version=0`,
  `feature.feature_versions(version=0)`에 저장한다.
- 사용자 요청 추가·수정·삭제는 `data_origin='user_request'`, `data_version=1`,
  `user_change_kind='add'|'update'|'delete'`,
  `feature.feature_versions(version=1)`에 저장한다.
- provider 재적재가 같은 `feature_id`를 다시 upsert해도 기존 version 1의 유효 필드는
  덮지 않는다. provider payload는 version 0 snapshot으로만 갱신한다.
- 사용자 요청 삭제는 lifecycle=`retired`, publication=`suppressed` 상태 전이와 immutable
  request/version receipt를 남긴다. 이후 provider 재적재나 snapshot 미포함 정리 작업은 이 row를
  되살리지 않는다.

## 4.2 Offline uploads

T-208i 기준 admin UI가 쓰는 offline upload API는 admin 전체 OpenAPI에만 포함한다.
PinVi/user subset에는 포함하지 않는다.

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
PinVi/user subset에는 포함하지 않는다. API는 standalone Docker app의 cold backup
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

## 5. Feature update request application service

REST 정본은 생성·preview·run-now가 `/ops/pipeline/requests*`, 목록·상세·취소가
`/ops/pipeline/executions*`다. 이 표면은 admin 전체 spec에만 포함한다.

Feature update request는 OpenAPI로 Dagster feature update job을 제어하는 표준
엔드포인트다. 운영자는 admin UI나 내부 운영 automation에서 호출한다. PinVi
사용자/서비스 표면에는 노출하지 않는다.

POI/cache target 기반 요청의 목적은 캐싱이다. 외부 앱이 저장한 POI 주변에서 자주
바뀌는 값(날씨, 유가, 휴일, 경고, 유고정보 등)을 전체 재적재 없이 갱신하고, 여러
POI 반경이 겹칠 때 교집합 feature/provider scope는 한 번만 업데이트한다. POI가
삭제되면 해당 key의 targeted update도 중단해야 하므로 좌표와 별도의 고유 key를
항상 함께 받는다.

### 5.1 생성

#### `POST /ops/pipeline/requests`

UUID 형식 `Idempotency-Key` header가 필수다. key namespace는 인증 actor별로 격리한다.
최초 요청은 `201`과 `idempotent_replay=false`를 반환한다. 같은 actor가 같은 key와 동일한
정규화 body를 다시 보내면 최초 결과를 `200`으로 재생하고 `idempotent_replay=true`를
반환한다. 같은 actor가 body를 바꾸면 `409 FEATURE_UPDATE_IDEMPOTENCY_CONFLICT`다. 다른
actor의 동일 key는 별도 요청이며 서로의 결과를 조회·재생·충돌시키지 않는다.

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
  "reason": "광화문 주변 데이터 즉시 갱신"
}
```

응답:

```json
{
  "data": {
    "request_id": "uuid",
    "scope_type": "center_radius",
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
    "result_kind": "request",
    "status": "queued",
    "job_id": "uuid",
    "dagster_run_id": null,
    "requested_sync_scope": null,
    "effective_sync_scope": null,
    "dispatch_requested_at": null,
    "operator": "local-admin",
    "reason": "광화문 주변 데이터 즉시 갱신",
    "error_message": null,
    "matched_scope": {
      "feature_count": 134,
      "sigungu_codes": ["11110"]
    },
    "created_at": "2026-07-15T12:00:00Z",
    "started_at": null,
    "finished_at": null,
    "generation": 1,
    "status_url": "/v1/ops/pipeline/executions/update_request/uuid"
  },
  "idempotent_replay": false,
  "reused_active_request": false,
  "meta": {"duration_ms": 34}
}
```

`POST /ops/pipeline/requests`는 새 영속 요청이면 `201`, 같은 direct effective scope의
활성 요청과 전체 계획이 같아 재사용하면 `200`을 반환한다. 두 경우 모두
`data.result_kind="request"`다. `idempotent_replay`는 동일 key의 최초 결과 재생 여부,
`reused_active_request`는 새 key의 계획이 기존 active canonical 요청을 재사용했는지 여부라
서로 대체하지 않는다. 비영속 계산은 같은 실행 계획 본문에서 `reason`을 제외해
`POST /ops/pipeline/requests/preview`로 보내며 `200`과
`data.result_kind="preview"`를 반환한다. preview에는 저장 identity와 lifecycle이 없으므로
`request_id`, `job_id`, `status`,
`dagster_run_id`, `status_url`, DB timestamp 필드가 존재하지 않는다.

create와 run-now 요청 body는 `operator`/`actor`를 받지 않으며 포함하면 extra field로
`422 VALIDATION_ERROR`다. 저장 행과 응답의 `operator`는 서버가 인증된
`AdminProxyContext.actor`에서만 파생한다.

target-selector KMA grid dataset은 `provider_dataset` scope에서만 명시적으로
선택할 수 있다. provider/dataset filter가 이 pair를 포함한 non-direct 요청은
provider I/O 전 `422`로 거절한다. non-direct 요청은 source record의
비지원 pair가 worker에서 늦게 실패하지 않도록 provider 또는 dataset_key filter를
하나 이상 반드시 지정한다.

서로 다른 계획이 같은 direct effective scope의 active identity를 점유하면 기존
`request_id`/상태/상세 링크를 포함한 `409 ACTIVE_SCOPE_CONFLICT`를 반환한다. `run_mode="now"`의
scope advisory lock 경합도 queued fallback 없이 `409`다. 응답은 공통 RFC7807
`application/problem+json`을 사용한다(§3).

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
  `prevent_provider_reactivation`만 허용한다. 각 key는 생략할 수 있지만 존재하면
  `mode='refresh_existing'` 또는 strict JSON boolean이어야 한다. 알 수 없는 key,
  문자열·정수 boolean, 명시적 JSON `null`은 queue 생성 전에 거절한다. 응답도 저장된
  sparse object를 그대로 반환해 생략한 key를 `null`로 팽창시키지 않는다.

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

`match`는 `intersects`만 허용한다. 현재 kor-travel-geo REST v2가 반경 원과
교차하는 시군구 목록을 반환하므로, 실행 의미가 없는 `contains_center`/
`feature_sigungu` 값은 계약에 두지 않는다.

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
  "external_system": "pinvi",
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

`POST /ops/pipeline/requests/preview`는 대상 수와 provider/dataset group을
preview 전용 응답으로 반환하고 request/import job/run을 만들지 않는다. 영속 생성 본문에
`dry_run` 필드는 없고 `ops.feature_update_requests`에도 해당 컬럼이 없다. 생성과 미리보기
응답은 각각 문자열 `result_kind=request|preview`로 판별한다. 저장 응답은 `request_id`, `job_id`,
`status_url`, `created_at`, `generation`이 모두 required이고 preview에는 이 필드가 존재하지 않는다.

구현 상태: T-206a에서 `infra.scope_repo.count_features_matching_scope`가
`feature_ids`, `center_radius`, `bbox`, `sigungu_by_radius`, `provider_dataset`의
read-only preview 해석을 제공한다. T-206d에서 `cache_target_keys`도 active
`ops.poi_cache_targets` 기반으로 해석하고, missing/deleted/disabled key를
`matched_scope`에 기록한다.

### 5.4 조회

#### `GET /ops/pipeline/executions?kind=update_request`

Query:

- `status`
- `scope_type`
- `provider`
- `dataset_key`
- `created_from`
- `created_to`
- `page_size`
- `cursor`

#### `GET /ops/pipeline/executions/update_request/{request_id}`

응답은 `FeatureUpdateRequestRecord` 한 건을 반환한다. `request_id`, scope와 필터,
`update_policy`, `run_mode`, `priority`, `status`, `matched_scope`, 연결 `job_id`, nullable
`dagster_run_id`, 운영자·사유·오류, lifecycle timestamp, 정수 `generation`과 `status_url`이
현재 계약이다.
import job 객체나 recent events 배열은 이 응답에 포함하지 않는다.

### 5.5 취소와 재실행

#### `POST /ops/pipeline/executions/update_request/{request_id}/cancel`

request를 canonical `update_request` pipeline root로 해석하고, 연결된 request/job/run 계층을
공유 C3d coordinator의 frozen scope로 취소한다. body는 nullable `reason`만 허용하며, 응답은
원본 request record가 아니라 canonical root와 durable cancellation attempt의 member/run별
결과를 담은 `PipelineCancellationResponse`다. 상세 상태·멱등·재시도·오류 계약은
`docs/architecture/rest-api.md` §2.6을 따른다.

#### `POST /ops/pipeline/requests/{request_id}/run-now`

선택 요청 body는 빈 strict object다.

```json
{}
```

새 request/job을 만들지 않고 기존 queued canonical job의 `dispatch_requested_at`을 최초 한 번
기록해 일반 queue보다 먼저 선택되게 하고 `200`을 반환한다. 같은 queued 요청 재호출은 원래
timestamp를 보존하고, running은 같은 identity/상태를 그대로 반환한다. terminal 또는 cancellation
요청 중인 작업은 `409 REQUEST_NOT_DISPATCHABLE`이다. priority/reason override는 허용하지 않는다.

## 6. Dagster 큐잉 방식

권장 기본 방식:

1. API가 `ops.feature_update_requests`와 `ops.import_jobs`를 같은 transaction에 생성.
2. Dagster sensor가 canonical job이 `status='queued'`인 request를 JOIN으로 peek해
   `(request_id, generation)`별 run을 생성.
3. Dagster worker run은 trimmed non-empty `dagster_run_id`를 owner로 제시한 generation CAS로
   canonical job만 `running`으로 바꾸고 progress를 갱신. `NULL` run owner는 허용하지 않는다.
4. 완료 시 canonical job만 terminal로 갱신하고 request 응답은 JOIN으로 같은 상태를 읽는다.

최초 생성의 `run_mode=now`와 기존 요청 run-now 모두 canonical job의
`dispatch_requested_at`을 설정한다. API가 Dagster run을 직접 만들지 않고 sensor가
dispatch marker 우선, priority, 생성 순서로 같은 queue에서 worker run을 만든다.

### 6.1 테이블

```sql
CREATE TABLE ops.feature_update_requests (
  request_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  scope_type TEXT NOT NULL,
  scope JSONB NOT NULL,
  providers TEXT[] NOT NULL DEFAULT '{}'::text[],
  dataset_keys TEXT[] NOT NULL DEFAULT '{}'::text[],
  update_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  run_mode TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50,
  matched_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  job_id UUID NOT NULL UNIQUE REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  operator TEXT,
  reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  generation BIGINT NOT NULL DEFAULT 1 CHECK (generation > 0),
  CONSTRAINT ck_feature_update_scope CHECK (
    scope_type IN (
      'feature_ids','center_radius','sigungu_by_radius','bbox','provider_dataset',
      'cache_target_keys'
    )
  ),
  CONSTRAINT ck_feature_update_run_mode CHECK (run_mode IN ('queued','now')),
  CONSTRAINT ck_feature_update_requests_scope_shape CHECK (
    ops.is_valid_feature_update_scope(scope_type, scope)
  ),
  CONSTRAINT ck_feature_update_requests_providers_shape CHECK (
    ops.is_valid_feature_update_filter_array(providers, 32)
  ),
  CONSTRAINT ck_feature_update_requests_dataset_keys_shape CHECK (
    ops.is_valid_feature_update_filter_array(dataset_keys, 64)
  ),
  CONSTRAINT ck_feature_update_requests_update_policy_shape CHECK (
    ops.is_valid_feature_update_policy(update_policy)
  ),
  CONSTRAINT ck_feature_update_requests_direct_filters_empty CHECK (
    scope_type <> 'provider_dataset'
    OR (cardinality(providers) = 0 AND cardinality(dataset_keys) = 0)
  ),
  CONSTRAINT ck_feature_update_requests_priority_range CHECK (
    priority BETWEEN 0 AND 1000
  ),
  CONSTRAINT ck_feature_update_requests_matched_scope_object CHECK (
    jsonb_typeof(matched_scope) = 'object'
  ),
  CONSTRAINT ck_feature_update_requests_reason_shape CHECK (
    reason IS NULL OR (
      reason <> '' AND reason = btrim(reason) AND char_length(reason) <= 500
    )
  )
);

CREATE INDEX idx_feature_update_priority
  ON ops.feature_update_requests (priority DESC, created_at, request_id);
CREATE INDEX idx_feature_update_created
  ON ops.feature_update_requests (created_at DESC, request_id DESC);
CREATE INDEX idx_feature_update_providers_gin
  ON ops.feature_update_requests USING gin (providers);
CREATE INDEX idx_feature_update_dataset_keys_gin
  ON ops.feature_update_requests USING gin (dataset_keys);
```

`ops.is_valid_feature_update_scope`는 immutable DB 함수로 여섯 scope의 필수 키,
추가 키 금지, JSON type, 문자열 trim/길이, 배열 크기, 좌표·반경·bbox 범위를
위 OpenAPI 입력 계약과 동일하게 강제한다. 기본값이 있는 `match`/`scope_mode`는 저장 전
canonical 값으로 채우고, nullable `sync_scope`/`radius_km`는 `NULL` JSON을 저장하지 않고
키를 생략한다. 0053은 cache-target scope의 `external_system`을 POI target natural key와
같은 112자로 제한한다. 0052는 `providers`/`dataset_keys`를 JSONB에서 typed `TEXT[]`로 전환한다.
`ops.is_valid_feature_update_filter_array`는 1차원·중복 없음과 각각 최대 32/64개의
trimmed non-empty string(항목당 128자 이하)을 강제한다.
`ops.is_valid_feature_update_policy`는 object만 허용하고 `mode='refresh_existing'`와
5개 boolean override 외의 키, JSON `null`, 잘못된 값 타입을 거부한다. repository는
입력의 Python `None` 값을 키 생략으로 canonicalize한 뒤 같은 계약을 저장한다.

0052 clean-cut부터 request 테이블은 입력·감사·queue generation metadata만 소유한다.
`status`, `dagster_run_id`, cancellation marker, `error_message`, `started_at`, `finished_at`은
삭제하고 unique `job_id`로 연결된 `ops.import_jobs`가 lifecycle 단일 정본이다. REST 응답은 두
테이블을 JOIN해 화면에 필요한 lifecycle을 한 번만 투영한다. claim/start/finish/requeue와
cancellation도 canonical job 한 행만 변경하므로 부분 성공과 이중 상태가 없다. queue 세대는
timestamp를 논리 토큰으로 쓰지 않고 명시적 `generation` 정수로 관리한다. requeue/pre-start retry만
원자적으로 1 증가시키며 Dagster run key와 CAS도 이 값을 사용한다. canonical job payload는
runtime에서 빈 object이며 relation/scope/policy/matched scope를 복제하지 않는다. migration audit만
source job ID를 별도로 보존한다. request 입력·
감사 필드는 INSERT 뒤 immutable이며 `matched_scope`와 `generation`만 linked job이 active이고
cancellation marker가 없을 때 변경한다. request/canonical job은 cancellation root와 audit correlation을
보존하는 append-only identity라 DELETE할 수 없다.

0053은 `ops.import_jobs`에 nullable `sync_scope`와 `dispatch_requested_at`을 추가한다. direct
`feature_update_request` job은 sync scope가 필수이고 non-direct job은 null이다. queued/running
direct job의 `(provider,dataset_key,sync_scope)`에는 partial unique index가 있어 active identity를
DB에서 최종 방어한다. request JSON은 requested scope, typed job column은 effective scope다.
명시 requested scope가 있으면 둘은 같아야 하지만 생략된 KMA target request는 typed job에
`target_grids`를 저장할 수 있다.
0053의 legacy backfill에서 동일 active identity가 생기면 running 하나 또는 runtime dispatch
정렬상 queued winner 하나만 보존하고 queued loser는 감사 가능한 cancelled terminal로
정규화한다. multiple-running과 cancellation audit marker 중복은 mutation 전에 fail-close한다.

구현 상태: Alembic `0008_feature_update_requests`, `0052_pipeline_projection_access`,
`0053_update_scope_dispatch`,
`FeatureUpdateRequestRow`가 이 DDL을 반영한다. `infra.feature_update_repo`는
preview, request/import job enqueue, priority peek와 generation/owner CAS start/finish,
단건 조회, keyset 목록 조회를 구현했다(T-206b). `AsyncKorTravelMapClient`는
preview/enqueue/get/list/cancel 메서드와 transaction 경계를 노출한다(T-206c). 0052 CHECK와
trigger는 여섯 scope, 두 필터 배열, update policy의 canonical 저장 shape와 연결 job의
`kind=feature_update_request`, parent/load-batch 없는 root/update-request shape,
`queued → run-id NULL`/`running → trimmed non-empty run-id`, typed pair가 정확히 맞고 다른 scope
request는 unpaired job을 가리키도록 강제한다. `job_id` UNIQUE, request→job FK, canonical job
INSERT의 deferred reverse-pair trigger가 commit 시 job↔request 양방향 1:1을 보장하며 generic
job writer는 reserved kind 생성과 lifecycle 변경을 거부한다. request와 canonical job의 DELETE,
job identity/payload 변경도 DB trigger가 거부한다. 기존
jobless·공유·pair 불일치·reserved Dagster kind request는 migration이 request별 canonical job을 만들어
재연결한다. unlinked feature-update job의 연결 component 전체에는 명시적 격리 시각·고정 사유를
기록하되 원래 `kind`·`payload`를 보존하고 pipeline/legacy ops/live/Dagster engine read에서 제외한다.
다른 request와 연결된 component는
격리하지 않고 중단하며 generic writer와 DB trigger가 runtime 격리 표식 변경, 격리 행 mutation/delete,
event 추가와 새 child attach를 거부한다. malformed scope/filter/policy,
persisted dry-run, active connected branch, cancellation 동결
후보가 있으면 request ID를 제시하고 중단한다. dry-run은 DB row 없이 preview 응답만 만든다.
T-206d의 `infra.feature_update_executor`는 runner 주입형 request 실행 본체를 제공한다. T-207a는
admin HTTP router와 OpenAPI schema export를 연결했다. T-208e는
`feature_update_request_queue_sensor`와 `feature_update_request_worker`로 queued/now
request 실행을 Dagster에 연결했다.

## 7. Provider 실행 API와의 관계

`POST /admin/providers/{provider}/datasets/{dataset_key}/runs`는 두지 않는다.
provider/dataset 직접 실행은 `POST /ops/pipeline/requests`의
`provider_dataset` scope를 사용한다.
PinVi 사용자/서비스 표면에는 feature update request를 노출하지 않는다.

feature update request는 운영자가 쓰기 쉬운 높은 수준 API다.
지리 scope를 provider/dataset/job으로 분해하고 필요한 Dagster run을 큐잉한다.

결과적으로 `ops.import_jobs`와 Dagster run을 사용한다.

현행 구현 상태:

- `GET /ops/datasets`: provider×dataset×scope sync state와 정책·스케줄·최신 실행을
  함께 반환한다.
- `GET /ops/datasets/detail`: cursor, 최근 실행·event, 정책과 이슈를 exact scope로
  조회한다.
- `PUT /ops/datasets/refresh-policy`: provider/dataset 정책 full upsert. body의
  `expected_revision`은 필수 nullable 필드다. 행이 없을 때만 `null`로 생성하며,
  기존 행은 응답에서 받은 양수 10진 문자열 revision을 그대로 보내야 한다.
  갱신 성공은 revision을 원자적으로 1 증가시킨다. 기존 행에 `null`, 없는 행에
  정수 문자열, stale revision은 `409 PROVIDER_REFRESH_POLICY_REVISION_CONFLICT`이고
  `details.current_record`, `details.current_revision`, `details.expected_revision`을
  반환한다. conflict는 정책 필드와 revision을 전혀 변경하지 않는다.
  기존 행의 `source_kind` 변경은
  `409 PROVIDER_REFRESH_POLICY_SOURCE_KIND_IMMUTABLE`, BIGINT 최댓값에서 더 갱신하려는
  요청은 `409 PROVIDER_REFRESH_POLICY_REVISION_EXHAUSTED`로 거절하며 둘 다 현재
  record/revision을 반환한다.
  `system_interval_seconds`/`optimal_interval_seconds`는 `min_interval_seconds`와
  선언된 request/min/hour/day floor보다 짧을 수 없다.

`ProviderRefreshPolicyRecord.revision`, 요청 `expected_revision`, conflict의
`expected_revision`/`current_revision`은 JSON number가 아니라 signed BIGINT 범위의
양수 10진 문자열이다. `9007199254740993`처럼 JavaScript 안전 정수를 넘는 값도 문자열
그대로 왕복한다. 브라우저는 작성 시작 시점의 `draftBaseRevision`과 background
refetch/409에서 본 `latestObservedRevision`을 분리한다. 서버 변경을 감지해도 local draft를
덮지 않으며, 저장 conflict에서는 base/local/latest를 필드별 3-way 비교한다. 운영자가
서버 값을 다시 불러오거나 최신 revision 위에 local 변경을 명시적으로 다시 적용한 뒤에만
다음 저장을 수행한다. 그 전에는 저장 버튼과 submit 경로를 모두 차단한다. 정책 panel은
탭 URL의 Back/Forward 전환에도 mount를 유지해 초안·base·conflict를 보존하며, concurrent
create conflict에서 생긴 서버 행의 `source_kind`는 local replay 대상에서 제외한다.

실행 목록·상세·event filter는 `/ops/pipeline`이 canonical operation root와 exact
provider/dataset identity를 기준으로 처리한다.

## 7.1 통합 datasets 운영 계약 (ADR-064, T-ADM-C2R)

`GET /ops/datasets`와
`GET /ops/datasets/detail?provider=...&dataset_key=...&sync_scope=...`은 다음 의미를
명시적으로 분리한다.

- `eligible_after`: `provider_sync_state.next_run_after`의 backoff/rate-limit상 재호출
  가능 시각이다. schedule 시각이 아니다.
- `schedule.next_scheduled_at`: Dagster schedule definition의 canonical
  provider/dataset tag와 RUNNING `futureTicks`에서 얻은 실제 다음 tick이다. 전체
  schedule은 HTTP 요청당 GraphQL 한 번으로 읽으며 실패 시 `basis=unknown`,
  `next_scheduled_at=null`로 degrade해 DB 응답 200을 유지한다.
- `freshness`: 정책의 명시적 `stale_after_minutes`와 마지막 성공으로 서버가 계산한다.
  SLA가 없으면 `unknown`, 성공 이력이 없으면 `never_run`, 정책 비활성이면
  `disabled`다. `system_interval_seconds`나 rate-limit 값에서 SLA를 추론하지 않는다.
- `latest_execution`과 `active_execution`: typed `import_jobs.provider/dataset_key`가 있는
  canonical root projection이다. 둘은 같은 DB statement snapshot에서 각각 가장 최근 terminal
  root와 queued/running root를 고른다. 더 최신 terminal root 때문에 이전 active root가 가려지지
  않는다. 연결 request/job 쌍은 FK와 lineage로 request 한 행에 접고 payload나
  event를 identity/계보 근거로 읽지 않는다. 선택된 pair member 상태와 root/대표 job
  상태·진척은 별도 속성으로 보존한다. direct request는
  `(provider, dataset_key, sync_scope)`별로 최신 root를 계산해 KMA external-system
  행 사이에 active/상세 링크가 섞이지 않게 하고, scope가 없는 일반
  scheduled/import 실행은 해당 dataset 행의 fallback으로만 사용한다. 이 fallback은
  API의 논리 `dataset_wide`와 NULL-scope 실행을 같은 total order로 비교한다.
  `target_grids`와 `external_system:*`에는 unscoped 실행을 추측하지 않는다.
  `execution_coverage=db_recorded_canonical_operations`를 함께 준다.
- `catalog.provider_state_default_scope`는 provider cursor/state namespace의 기본값이고,
  직접 갱신 조작이 제출할 기본 effective scope는
  `catalog.scope_refresh.default_sync_scope`만이 정본이다. 일반 provider의 init/bind/run/
  teardown 실패도 성공 writer와 같은 `default`에 기록하고 KMA grid 3종만 선택된
  effective scope를 실패 namespace로 사용한다. target selector는 catalog 기본 scope와
  활성 `external_system:*` scope를 DB state 유무와 관계없이 grid/detail에 `never_run`으로
  구체화하고, 삭제된 system의 잔존 state도 감사 목적으로 유지한다.
  내부 `default` state는 API에서 `dataset_wide`로 투영한다. strict parser가 거부하는 legacy
  scope는 조작 URL로 노출하지 않으며, 그런 state만 남은 orphan provider/dataset은 비가변
  `dataset_wide` placeholder로 남겨 provider/dataset 자체의 존재는 숨기지 않는다.
- KMA grid 3종은 `target_grids`와 `external_system:*`의 active target을 격자로 해석하고
  cap을 적용한 뒤 유효 격자가 0개면 typed `KmaWeatherTargetScopeEmptyError`로 canonical
  operation을 `failed` 처리한다. provider를 시도하지 않은 preflight 실패이므로 provider
  호출·적재·sync-state failure/success/cursor/timestamp write는 없고 operation 오류가 durable
  증거다. credential 확인·`kma` import·public client 생성도 target read → grid mapping/dedupe →
  cap → empty 판정과 cursor skip 뒤로 지연한다. canonical terminal 전이와 같은 transaction에
  `ops.import_job_events.code=kma.target_scope_empty`를 정확히 1건 기록하며, terminal replay는
  중복 event를 만들지 않는다. UI는 오류 문자열을 파싱하지 않고 pipeline 상세 `events[].code`와
  dataset 상세 `event_history.items[].code`에서 같은 code를 읽는다.
- dataset 상세의 `event_history.items`는 선택한 논리 scope의 canonical effective scope를
  event 쿼리의 ORDER/LIMIT 전에 제한한 결과다. 각 event는 non-null `sync_scope`를 포함한다.
  `event_history={items,next_cursor,canonical_url}`은 같은 exact scope를 끝까지 이어 간다.
  전역 `GET /v1/ops/pipeline/events`도 `provider`·`dataset_key`와 함께 `sync_scope`를 받으며
  응답 event에 nullable `sync_scope`를 싣는다. 0057부터 이 값은 event payload나 runtime JOIN이
  아니라 `ops.import_job_events.sync_scope` typed 열과 partial index로 조회한다.
- integrity issue는 `dataset_issues`와 `provider_issues`를 섞지 않고 따로 반환한다.
- 카탈로그에서 제거됐지만 sync state/policy가 남은 row는 `catalog_state=orphan`,
  `mutable=false`이며 정책 mutation은 `409 ORPHAN_MUTATION_DISABLED`와
  `details.mutation_disabled_reason`으로 거부한다.

`POST /ops/datasets/preview?provider=...&dataset_key=...`는 fixture capability만 제공한다.
요청은 `source=fixture`, `max_items(1..100)`이며 응답은 `total_items`,
`returned_items`, `truncated`, timeout과 `external_call_budget=0`을 포함한다. raw live
HTTP preview는 ADR-044 provider public client/typed model 경계를 만족하지 않으므로 이
제품 API에서 제공하지 않는다. fixture capability가 없으면
`409 PREVIEW_NOT_SUPPORTED`와 `details.capability=none`, catalog와 fixture registry가
어긋나면 `409 PREVIEW_REGISTRY_MISMATCH`와 `details.capability=fixture`를 반환한다.

그리드 조립은 admin 목록 endpoint의 500건 limit을 재사용하지 않고 refresh policy를
전량 조회한다. 따라서 catalog에서 제거된 501번째 이후 orphan policy도 조용히
누락되지 않는다.

## 7.2 Ops 조회 API

`kor-travel-map-admin`은 DB 기반 summary·목록을 `/ops/*`로 제공한다. 실행 root 조회와
event·취소 정본은 `/ops/pipeline/*`다.

실시간 signal 채널 `WS /ops/live`는 WebSocket이므로 `openapi.json` `paths`에는
포함되지 않는다. REST DTO source of truth는 계속 아래 endpoint이며, live frame은
admin frontend의 query invalidation signal로만 사용한다. 현행 REST DTO 정본은
`/ops/pipeline/*`와 `/ops/datasets/*`다. 연결 전 same-origin
`POST /api/auth/live-ticket`이 admin session을 검증해 60초 signed WebSocket subprotocol
ticket을 발급한다. BFF는 `Origin`과 `Sec-Fetch-Site: same-origin`을 모두 요구하고,
FastAPI는 운영 data 전송 전에 HMAC 검증과 nonce 원자 소비를 끝낸다. 서명/인증 실패는
data 없는 최소 handshake 뒤 `4401`, 서명은 유효하지만 handshake 전 만료한 ticket은
data 0건 + `4408`로 닫는다. 이미 frame을 보낸 healthy 연결도 60초 lease가 끝나면
`4408`로 닫지만 이 경우 data 0건 계약은 적용되지 않는다. claim/snapshot의 내부
`TimeoutError`와 기타 DB
장애는 outer lease 만료와 구분해 bounded rollback 후 `1013`으로 닫는다. frame
transport의 독립 `TimeoutError`·`OSError`·`RuntimeError`도 bounded rollback 후
`1013`이다. 정상 disconnect는 close를 중복 전송하지 않는다. invalid,
replay, claim 장애의 accept/close와 rollback은 공통 bounded 경계를 통한다. ticket과
server-only proxy secret은 URL/query/browser bundle에 두지 않는다. transport 상태와
topic→datasets/pipeline query adapter 계약은
`docs/reports/admin-ops-c7a-live-contract-2026-07-17.md`가 정본이다.

### `GET /v1/ops/pipeline/executions`

DB에 기록된 update request와 import job hierarchy를 root 실행 목록으로 반환한다.
각 job은 ancestry의 가장 가까운 request anchor branch 또는 standalone partition 중
정확히 하나에 귀속한다. batch root·미소유 sibling은 최상위 import job 한 행이고,
각 request branch는 request 한 행이다. descendant job을 별도 root로 반환하지 않는다.

정렬과 cursor 비교는 모두 `(created_at DESC, id DESC, kind DESC)`다. cursor v3는
`created_at`·UUID `id`·`kind(update_request|import_job)`와 전체 filter fingerprint를 담는다.
형식·kind가 잘못됐거나 발급 당시 filter와 현재 filter가 다르면 DB 조회 전에 `422`다.
query는 `kind`, root `status`, `provider`,
`dataset_key`, `sync_scope`, `created_from`, `created_to`, `page_size`, `cursor`를 지원한다.
`sync_scope`는 `provider`·`dataset_key`와 함께 써야 하며 단독 사용은 `422`다. 일반 dataset과
orphan 기본 state에서는 선택 scope·typed `dataset_wide`·NULL pair를 같은 논리 이력으로 본다.
provider-only filter는 request 저장 배열 membership과 canonical exact pair를 함께 본다.
`dataset_key`는 provider namespace 안의 식별자라 provider 없이 주면 `422`다. provider와
dataset을 모두 주면 배열을 교차 조합하지 않고 같은 canonical
`provider_datasets[]` member가 정확히 일치할 때만 반환한다. import 실행 identity의 유일한
정본은 typed `import_jobs.provider`/`dataset_key`다. `import_job_events`의 같은 이름 필드는
감사 메타데이터일 뿐 projection·filter·latest의 identity를 만들거나 바꾸지 않는다.

각 item의 공통 root 필드는 `kind`, `id`, `status`, `progress`, `current_stage`,
`dagster_run_id`, `providers[]`, `dataset_keys[]`, `provider_datasets[]`,
`created_at`/시작/종료 시각이다. 표시 배열은 저장 배열과 canonical pair의 유효값을 합쳐
정렬·중복 제거한다. 두 배열은 provider-only/dataset-only 표시·필터용 독립 목록이며,
provider/dataset/sync_scope와 pair별 member/status는 required 배열인
`provider_datasets[]`가 정본이다. pair가 없는 root도 필드를 생략하지 않고 빈 배열을 반환한다.
각 pair의 `operation_member_id`는 필수 UUID이고, nullable `sync_scope`도 필드를 생략하지 않는다.
direct update request pair의 값은 request JSON이 아니라 canonical job의 effective typed column이다.
`projected_job`은 일반 hierarchy에서 `depth DESC, created_at DESC, job_id DESC` 규칙으로 고른
대표 job이며 root와 별도의 status/progress/error/times/Dagster run/detail URL을 가진다. 단,
C3e `provider_feature_load_run`은 임의 pair child를 대표로 고르지 않고 root 자체를
`projected_job`으로 고정한다.
`linked_job_count`는 해당 request branch 또는 standalone partition의 job 수다.

request item은 양방향 1:1 FK인 `requested_job_id`를 필수로 제공한다. canonical request job은
항상 hierarchy root라 request branch는 root와 descendants 전체다. 같은 job을 여러 request가
가리키거나 request job이 다른 job의 child가 되는 상태는 DB가 거부하므로 owner/loser 진단과
`lineage_owner`는 계약에 없다. `projected_job`도 모든 root에서 필수다.

단건 detail과 cancel도 같은 canonical root projection을 필수로 반환한다. 단건의 raw
request/job/event 부속 정보는 유지하되 identity와 root 상태는 목록과 갈라지지 않는다.
Dagster run 상세는 T-ADM-C3c, 계층 취소는 C3d가 소유한다.

## 7.2.1 Canonical operation REST 계약 (T-ADM-C3e)

갱신 조작은 admin 정본과 동일하게 `POST /v1/ops/pipeline/requests` 신규 영속 생성(201) 또는
동일 활성 계획 재사용(200)과
`POST /v1/ops/pipeline/requests/preview` 비영속 미리보기(200)로 분리한다. 생성 본문은
`dry_run`을 받지 않으며 미리보기 응답에는 request/job identity와 lifecycle이 없다.

pipeline overview/timeline, datasets grid latest execution, datasets detail recent runs는 C3b의
같은 lineage/root CTE와 exact pair projection을 소비한다. grid는 전 dataset을 한 번에 읽는
batch query를 사용하며 pipeline 첫 page를 최신값 전체로 오인하지 않는다.

`GET /v1/ops/pipeline/overview`는 raw import job과 update request를 따로 세지 않는다. 응답의
`operations_by_status`, queued+running root 합계 `active_operations`,
`failed_operations_24h`는 timeline과 같은 canonical root를 한 번만
세며 MCST/multi-asset child N개가 count를 N배로 부풀리지 않는다. 이 변경은 기존
`import_jobs_by_status`, `update_requests_by_status`, `failed_import_jobs_24h`,
`failed_update_requests_24h`, `active_import_jobs`, `active_update_requests`와 호환하지 않는다.

공통 execution identity는 `kind=import_job|update_request`와 UUID `id`의 조합이다. 모든
표면은 같은 `detail_url`을 반환한다. provider/dataset query를 함께 주면 같은 typed child
pair가 두 값을 모두 만족해야 하며 다른 event/독립 배열의 교차 조합은 매칭하지 않는다.
`provider_datasets[]` 각 항목은 다음을 가진다.

- `provider`, `dataset_key`
- `operation_member_id`: 선택된 import job member UUID
- `status`: 해당 pair의 `queued|running|done|failed|cancelled`

update request root도 연결된 import job/descendant의 실컬럼 pair만 사용한다. direct
`provider_dataset` scope의 provider/dataset은 연결 typed pair와 같고, optional request
`sync_scope`는 requested metadata다. 실행·active identity·projection은 canonical job의 required
effective `sync_scope`만 사용한다. 독립
provider/dataset 배열은 표시와 단일 필터용일 뿐 exact pair 생성 근거가 아니다.

pair 배열은 `(provider ASC, dataset_key ASC)`로 정렬한다. 같은 pair의 typed member가 여러
개면 canonical branch의 `depth DESC, created_at DESC, job_id DESC` 첫 행을 선택해
그 member id와 status를 반환한다. typed member가 없으면 pair도 없다. event-only 과거
실행은 root timeline에는 남지만 `provider_datasets=[]`이며 dataset latest에서 제외된다. 이
선택·정렬은 pipeline/datasets 양쪽에서 같다.

root `status`도 같은 lifecycle 어휘지만 run 전체 결과다. `projected_job.status`, C3d
cancellation workflow/result, nullable `dagster_run_status`, freshness, `trigger_kind`는 별도 필드이며
서로 덮어쓰지 않는다. API schema와 application service가 쓰는 canonical operation DTO/
HATEOAS mapper는 public 모듈에 두고 datasets service가 router private 함수를 import하지
않는다.

`provider_feature_load_run`의 `projected_job`은 root 자체다. pair child insertion order나 UUID는
projected status/progress/stage를 바꾸지 않으며 pair별 결과는 `provider_datasets[]`만 정본으로
사용한다. root progress는 완료 pair 비율이고 exact SUCCESS는 100이다. partial failure/cancel은
완료 비율을 보존하며 stage는 `queued|loading|completed|failed|cancelled|tracking_invariant`다.
`created_at`/`started_at`/`finished_at`은 Dagster authoritative engine timestamp를 사용한다.

feature-load root는 identity 진단용 nullable `operation_registry_version`도 반환한다. 다른
legacy/update root에서는 NULL이며 이 값은 cursor나 correlation key가 아니다.

`GET /v1/ops/datasets`의 `execution_coverage`와
`GET /v1/ops/datasets/detail?provider=...&dataset_key=...&sync_scope=...`의
`execution_coverage`는 모두
`db_recorded_canonical_operations`다. 이는 0051 이후 DB 기록 범위이며 과거
GraphQL-only run이나 #686의 requested/effective sync scope를 포함한다고 주장하지 않는다.
detail의 `run_history.items`는 요청한 논리 scope를 DB에서 먼저 제한한 뒤 pipeline과 같은
total order로 자른 첫 page다. 일반 dataset의 provider-state 기본 scope는 typed
`dataset_wide`/NULL pair와 같은 논리 범위로 취급한다. 따라서 다른 scope의 최신 실행이
page를 채워도 stale external/orphan exact-scope 이력이 pagination 뒤에서 사라지지 않는다.
`run_history={items,next_cursor,canonical_url}`은 같은 논리 scope 별칭을 적용한다. 다음 cursor는
그 URL에서 다른 scope를 섞지 않고
누락·중복 없이 이어져야 한다.

같은 상세의 `event_history.items`는 run history의 다중 scope 별칭을 그대로 합치지 않는다.
target 선택형 dataset은 선택한 exact scope, 일반 dataset의 기본 논리 scope는 canonical
`dataset_wide` effective scope 하나를 사용한다. `event_history.next_cursor`와
`event_history.canonical_url`은 그 effective scope를 명시하며, 전역 events 화면은 URL의
provider/dataset/scope filter를 그대로 초기화한다.

`GET /v1/ops/pipeline/executions`와 `/events`의 `data.canonical_url`은 cursor를 제거한
첫 page URL이다. provider-only filter는 그 provider만 담은 URL로 정규화한다. 반면 dataset만
있거나 scope에 provider/dataset이 모두 없는 불완전 tuple은 422다. `sync_scope`는 strict canonical
parser를 통과해야 한다. run cursor는 kind/status/provider/dataset/scope/batch/parent/time filter,
event cursor는 job/level/provider/dataset/scope fingerprint에 묶이며 다른 filter에서 재사용하면
`422 VALIDATION_ERROR`다.

Dagster feature-load operation은 run root 하나와 exact pair child들이다. timeline에는 root 한
행만 보이고 datasets는 같은 `(kind,id)` root와 해당 pair child status를 노출한다. 같은 run의
dataset 하나에서 취소해도 root 전체가 C3d frozen scope이므로 응답과 UI는 공유 run의 모든
pair가 영향받는다는 경계를 표시한다.

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

`import_jobs_by_status`는 `ops.import_jobs` physical row 진단값이며 canonical operation 수가 아니다.
홈과 pipeline 작업 상태 위젯은 `/v1/ops/pipeline/overview.operations_by_status`를 사용한다.

### 삭제된 import job REST 이력

> C6B에서 아래 `/ops/import-jobs*`·`/ops/import-job-events`를 삭제했다. 현행
> 목록·상세·event·취소는 `/ops/pipeline` 계약을 사용한다.

#### `GET /ops/import-jobs`

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

#### `GET /ops/import-jobs/{job_id}`

`ops.import_jobs` 단건을 반환한다. 없으면 `404`.

#### `GET /ops/import-job-events`

`ops.import_job_events` 전역 event stream을 `occurred_at DESC, event_id DESC` keyset
cursor로 반환한다. `/ops/logs`의 Job events 탭은 이 표면을 사용해 provider 실패를
한 화면에서 훑고, item의 `job_id`를 `/ops/import-jobs/{job_id}` 상세로 연결한다.

Query:

- `job_id`: UUID. 특정 job으로 좁힐 때 사용.
- `level`: `debug` / `info` / `warning` / `error` / `critical`
- `provider`
- `dataset_key` (`provider` 필수)
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

각 item은 `event_id`, `job_id`, `provider`, `dataset_key`, `feature_id`, `stage`,
`level`, `code`, `message`, `payload`, `occurred_at`을 포함한다.

#### `GET /ops/import-jobs/{job_id}/events`

`ops.import_job_events` event timeline을 `occurred_at DESC, event_id DESC` keyset
cursor로 반환한다. job이 없으면 `404`.

Query:

- `level`: `debug` / `info` / `warning` / `error` / `critical`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

각 item은 `event_id`, `job_id`, `provider`, `dataset_key`, `feature_id`, `stage`,
`level`, `code`, `message`, `payload`, `occurred_at`을 포함한다.

#### `POST /ops/import-jobs/{job_id}/cancel`

queued/running job을 best-effort로 `cancelled` 전이한다. 이미 `done` / `failed` /
`cancelled`인 job은 `409`, 없는 job은 `404`를 반환한다. 실행 중인 외부 프로세스를
강제 종료하지 못할 수 있으므로 cancel event payload에는 `best_effort=true`가 남는다.

요청 body(선택):

- `operator`
- `reason`

응답은 갱신된 `OpsImportJobRecord` envelope다.

### `WS /ops/live` (OpenAPI 제외)

Admin UI 내부망 전용 WebSocket signal 채널이다. 초기 topic은 빈 집합이고 query
`topics`는 받지 않는다. client command는 JSON object
`{ "type": "subscribe" | "unsubscribe" | "replace",
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
- `provider_sync`
- `dataset_projection`
- `dagster_schedules`

prefix topic의 DB resource `{job_id}`·`{request_id}`·`{upload_id}`는 canonical UUID여야
한다. Dagster의 `{run_id}`는 UUID나 ASCII whitelist로 가정하지 않는다. 앞뒤 공백을
제거한 뒤 비어 있지 않은 255자 이하 opaque id를 보존하며 C0 control만 거절한다.
topic은 JSON 문자열 배열에서만 전달하므로 comma가 든 run ID도 분할하지 않는다.
`provider_sync`, `dataset_projection`, `dagster_schedules`는 source transaction과 같은
transaction에서 증가하는 `ops.ops_live_topic_revisions` clock을 snapshot에 포함한다.
provider state/policy, data integrity issue/POI cache target, schedule override는 statement 단위
INSERT/UPDATE/DELETE/TRUNCATE, C5 schedule audit/claim resolution은 INSERT마다 clock을 올린다.
rollback은 clock도 함께 되돌리고, 동시 writer는 topic PK row lock으로 직렬화되어 늦은 commit도
유실되지 않는다. `dagster_schedules` snapshot은 clock과 함께 C5
schedule audit `event_id`, claim resolution `resolution_id` tail도 한 SQL에서 읽는다. C7A는 C5
migration이 먼저 적용된 strict schema를 전제하므로 `to_regclass` degrade를 두지
않는다. 배포 순서는 C5 후 C7A다.

서버 frame:

- `hello`: 연결 직후 현재 topic과 poll 간격.
- `snapshot`: 최초 또는 topic 변경 직후 전체 topic snapshot.
- `update`: revision이 바뀐 topic만 전송.
- `heartbeat`: 변경이 없어도 연결 생존을 알림.
- `error`: client command 검증 오류. snapshot 조회 장애는 frame 대신 `1013`으로 닫는다.

frontend는 frame `data`를 화면 상태로 직접 저장하지 않고, topic에 해당하는 TanStack
Query key를 invalidate한다. `hello`와 `subscribed` ack만으로는 healthy 연결이 아니다.
요청과 문자열 타입·중복 없음·동일 원소인 exact topic set ack를 받은 뒤 유효한
snapshot/update 또는 같은 topic set heartbeat를 받아야 실패 횟수를 초기화한다. wire의
canonical 배열 순서는 표시용이며 JS/Python 정렬 순서에 의미를 부여하지 않는다.
snapshot/update는 `version=1`, 단조 증가하는 safe-integer `sequence`, 요청 `topic`, 비어 있지
않은 `revision`, JSON object `data`를 모두 만족해야 한다. 형식 오류와 거절된 replace는 구독
준비 상태와 현재 protocol 신뢰를 폐기하고 handler를 분리한 뒤 socket을 즉시 닫는다. 새
ticket/socket에서 exact `replace`를 다시 보내고 유효 snapshot 또는 heartbeat를 받아야
healthy에 복귀한다.
ticket fetch, pre-healthy handshake, healthy frame inactivity는
각각 watchdog으로 제한해 close frame이 유실돼도 REST polling + background reconnect로
복구한다. healthy 전
`4408`과 hello 직후 `1013`은 일반 backoff에 포함하고, healthy 후 `4408`만 정상
lease rotation으로 즉시 재연결한다. 3회 연속 실패하면 datasets grid·선택
상세는 active 여부와 관계없이 5초 REST polling을 실행하고 UI badge에 fallback을
표시한다. active 실행은 기존 2초 주기를 유지한다.

### `GET /ops/consistency/reports`

`ops.feature_consistency_reports` 목록을 `started_at DESC, report_id DESC` keyset
cursor로 반환한다. 기존 F1~F4 batch report 조회 표면이다.

Query:

- `severity_max`: `OK` / `WARN` / `ERROR`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

### `GET /ops/consistency/issues`

`ops.data_integrity_violations` 목록을 `last_seen_at DESC, issue_id DESC` keyset
cursor로 반환한다. Phase 2 F5~F8 계열과 주소/좌표 매칭 이슈는 이 큐를 통해 운영
화면에 노출한다. record는 최초 탐지 `detected_at`과 최신 recurrence
`last_seen_at`을 함께 반환한다.

Query:

- `status`: `open` / `acknowledged` / `resolved` / `ignored` (기본 `open`)
- `severity`: `info` / `warning` / `error` / `critical`
- `violation_type`
- `provider`
- `dataset_key`
- `feature_id`
- `page_size` (`1..200`, 기본 `50`)
- `cursor`

## 7.2.2 통합 pipeline Dagster run 상세 API

#### `GET /ops/pipeline/dagster-runs/{run_id}`

`GET /ops/pipeline/dagster-runs`에서 선택한 Dagster run의 event log와 실패 payload를
조회하는 읽기 전용 child resource다. 목록·overview는 Dagster 장애 때도 DB 운영 화면을
보존하도록 `200` graceful degrade하지만, 개별 상세는 성공한 조회만 `200`으로 반환한다.

Path:

- `run_id`: 앞뒤 공백 제거 후 길이 `1..255`. 빈 값이나 초과 길이는 `422`다.

Query:

- `page_size`: `1..200`, 기본 `50`.
- `after`: 이전 성공 응답의 `event_cursor`. 길이 `1..2048`인 Dagster opaque cursor이며
  해석·재인코딩하거나 DB execution cursor와 혼합하지 않는다. 미지정이면 첫 page다.

성공 응답은 `DagsterRunDetailResponse` envelope이며 `data.status`는 항상 `ok`다.
`event_has_more=true`이면 `event_cursor`를 다음 요청의 `after`로 보내 전진한다. backward
pagination이나 서버의 page 간 event 병합은 제공하지 않는다.

`failure_reason`과 `failure_events`는 **현재 event page에서 발견한 실패 event만** 요약한다.
따라서 run 상태가 `FAILURE`여도 현재 page에 실패 event가 없으면 두 필드는 각각 `null`과
빈 배열일 수 있다. 특히 `event_has_more=true`이면 이를 전체 run의 실패 원인 부재로
해석해서는 안 된다. UI는 뒤 page 조회와
`{dagster_url}/runs/{URL-encoded run_id}` 외부 링크를 fallback으로 제공한다.

service의 비성공 상태는 router에서 다음 RFC7807 `application/problem+json`으로
승격한다. 내부 HTTP 오류 payload는 `{code, message, details}`이며 중앙 handler가
`type`/`title`/`status`/`detail`/`code`/`request_id`와 `details`를 갖는 problem으로
직렬화한다.

| service 상태 | HTTP | `code` | 의미 |
|---|---:|---|---|
| `not_found` | 404 | `DAGSTER_RUN_NOT_FOUND` | Dagster가 `RunNotFoundError`를 반환 |
| `unavailable` | 503 | `DAGSTER_UNAVAILABLE` | Dagster 연결·timeout 등 request 전송 실패 |
| `error` | 502 | `DAGSTER_QUERY_FAILED` | upstream HTTP·응답 해석·URL 설정·GraphQL·PythonError 오류 |

`__typename=Run`만으로 성공을 판정하지 않는다. 응답 `runId`가 비어 있거나 요청값과
다르고, `eventConnection`이 객체가 아니거나 `cursor`·`hasMore`·`events` pagination
shape가 잘못됐으면 응답 해석 오류다. `hasMore=true`이면 다음 요청에 그대로 쓸 수 있는
비어 있지 않은 2,048자 이하 cursor가 반드시 있어야 한다.

각 problem의 `details`는 최소 `run_id`와 service의 `errors`를 포함한다. FastAPI path/query
검증 실패는 공통 `422 VALIDATION_ERROR`다.

새 UI는 Dagster iframe을 embed하지 않으므로 NUX mutation endpoint를 제공하지 않는다.

## 7.2.3 삭제된 Dagster 운영 요약 API 이력

> C6B clean-cut에서 `/ops/dagster/*` 전체를 삭제했다. 아래 내용은 이전 계약의
> 변경 이력이며 현행 REST/OpenAPI 계약이 아니다. 현재 조회·조작은 §7.2.1과
> `/ops/pipeline/*`만 사용한다.

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
`/admin/features/update-requests`, import job progress는 `/ops/import-jobs` 계약으로
분리한다. job cancel은 아직 별도 backend task가 필요하다.

#### `GET /ops/dagster/runs/{run_id}`

Dagster `runOrError`와 event log를 조회한다. schedule/sensor tick 또는 recent run에서
선택한 run의 실패 원인과 최근 event를 admin UI에 표시하기 위한 읽기 전용 endpoint다.

Path:

- `run_id`

Query:

- `page_size` (`1..200`, 기본 `50`)
- `after` (이전 응답의 `event_cursor`, 전진 방향)

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

이 구 endpoint는 전환 기간의 legacy 화면 계약이므로 비성공 상태도 `200` envelope에
남긴다. 새 pipeline child resource는 §7.2.1의 strict HTTP 오류 계약을 사용한다.

#### `POST /ops/dagster/nux-seen`

embedded Dagster 화면이 로컬 첫 실행 커뮤니티 모달로 가려지지 않도록 Dagster GraphQL
`setNuxSeen` mutation을 호출한다. summary GET의 부수효과를 없애기 위해 명시 POST로
분리했다. Admin UI는 `/admin/dagster` summary가 정상 조회되면 이 endpoint를 한 번
호출한다. 이 endpoint는 legacy 화면 전용이며 새 `/ops/pipeline` 그룹에는 승계하지 않는다.

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

단건·목록 body는 server canonical `entity_tag="{lowercase_uuid}:{positive_version}"`을 포함하고,
GET/PUT/DELETE 성공 header `ETag`는 body 값과 octet-exact하게 같다. PUT/DELETE 성공 응답의
`meta.dataset_projection_revision`은 같은 source transaction에서 statement trigger가 증가시킨
`dataset_projection` topic revision이다. live consumer는 mutation 전에 열린 같은 socket의
`dataset_projection` update에서 `data.live_revision >= receipt`인 경우만 causal invalidation으로
인정한다. reconnect snapshot과 top-level fingerprint `revision`은 비교하지 않는다.

요청 body의 `provider_overrides`는 provider 또는 `provider:dataset_key` 문자열 key
최대 64개만 허용한다. 각 값은 `targeted_policy`, interval/rate-limit 계열 숫자,
`max_concurrent`, `note`만 받을 수 있고 unknown key는 `422`다. `metadata`는 Pydantic
내부에서 `metadata_` 필드+alias로 다루며, 외부 JSON 필드명은 계속 `metadata`다.
허용 metadata key는 `pinvi_poi_id`, `external_ref`, `source_url`, `labels`, `note`
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

외부 POI 삭제를 반영한다. 목록/직전 GET/PUT body의 `entity_tag`를 합성하지 않고 `If-Match`로
필수 전달한다. 서버는 active natural key를 `FOR UPDATE`로 잠근 뒤 ETag UUID+version이 같은
행만 soft delete한다. concurrent PUT 또는 재생성은 새 target을 건드리지 않고
`412 Precondition Failed`, active target이 실제 없으면 `404`다.
`If-Match` 누락은 RFC7807 `428 Precondition Required`, weak/wildcard/쉼표 결합 multiple/물리적
duplicate line/noncanonical 값은 RFC7807 `422 Unprocessable Entity`다. 성공 DELETE도 삭제한
target UUID의 같은 strong `ETag`를 새로 증가한 version으로 반환한다.
성공한 target은 이후 targeted update에서 제외한다.
admin UI는 선택 target UUID로 refetch된 list row를 다시 파생한다. `412` 응답은 target list/nearby와
관련 dataset/pipeline projection을 모두 refetch한다. refetch 중 삭제 버튼은 비활성화되며 재시도는
갱신된 row의 새 `entity_tag`를 쓴다.

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

## 8. PinVi/public feature read API

T-207e 구현 상태: PinVi에는 다음 public/read API를 제공한다. 기존
`GET /features` raw bbox 응답은 admin frontend 호환용으로 유지하고, 사용자/PinVi
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

Feature update request는 더 이상 PinVi/public 표면에 포함하지 않는다.
정본 운영 경로는 `/ops/pipeline/requests*`다. PinVi 사용자 제안 큐는
PinVi app DB가 소유하고, 운영자 승인 후 admin API로 refresh scope를 실행한다.

PinVi 사용자-facing 응답에는 raw payload, provider key 상태, provider/dataset 내부
식별자, dedup/sibling linkage, target refresh policy, 내부 error detail, admin audit log를
노출하지 않는다. `/tripmate/*` namespace는 제거됐다(kor-travel-map은 PinVi 전용이 아니다) —
batch 같은 service read는 `POST /features/batch`(ServiceToken route-level gate)로 일반화한다.

상세 응답에는 aware `updated_at`을 포함한다. 목록 API는 JSONB detail/raw payload를
반환하지 않고, 특정 feature 상세 API에서만 `address`/`detail`/`urls` JSON 데이터를
반환한다.

### 8.1 PinVi T-130 공개 뷰

PinVi T-130(`/public/*`)은 현재 사용자 subset에 없는 해수욕장/축제 전용 뷰를
요구한다. 계약은 [`docs/architecture/public-views-api.md`](public-views-api.md)에 둔다.
T-222b(2026-06-12)부터 다음 표면은 `openapi.user.json` 사용자 profile에 포함한다.

- `GET /v1/public/beaches`
- `GET /v1/public/beaches/map-markers`
- `GET /v1/public/beaches/{feature_id}`
- `GET /v1/public/festivals/monthly`
- `GET /v1/public/festivals/map-markers`
- `GET /v1/public/festivals/{feature_id}`

### 8.2 curated_features read profile

T-223c-1(2026-06-12)부터 테마형 큐레이션 read 표면은 PinVi import용
사용자 profile에 포함한다. write/admin 표면(`/v1/admin/curated-*`)은 내부 운영
profile에만 둔다.

- `GET /v1/curated-themes`
- `GET /v1/curated-sources`
- `GET /v1/curated-features`
- `GET /v1/curated-features/{curated_feature_id}`
- `GET /v1/curated-features/{curated_feature_id}/pinvi-copy`

### 8.3 legacy curated admin write provenance

전환기 legacy overlay write인 `POST /v1/admin/features/curated`,
`PATCH /v1/admin/features/curated/{curated_feature_id}`,
`DELETE /v1/admin/features/curated/{curated_feature_id}`는 admin proxy가 인증한 principal을
`operator_updated_by`에 기록한다. actor/provenance는 요청 body 계약이 아니며 create body의
`selection_origin`·`selected_by`·`rejected_by`는 `extra="forbid"` 검증으로 거부한다.
status가 `curated`/`rejected`이면 같은 principal을 각각 `selected_by`/`rejected_by`에도 기록한다.

### 8.4 curation component identity

`CurationItemCreateRequest`/`CurationItemPatchRequest`와 admin/public item 응답은
`external_component_id`를 사용한다. 단일 membership의 create 기본값은 `primary`다.
CSV template·preview 응답은 대응하는 `source_component_key`를 필수 열/필드로 제공한다.

durable item identity는 `collection + external_item_id + external_component_id`다.
`feature_id`는 nullable·mutable target이므로 복합 source item의 연결·미연결 component가
공존할 수 있고, 재연결은 같은 item UUID와 operator 상태를 유지한다. 같은 source item의
component가 동일 non-null Feature를 중복 참조하면 preview는 행 identity 오류를 반환하고
commit 전체를 거부한다.

## 9. Frontend stack 계약

Admin frontend 표준:

- Next.js 16 App Router.
- React 19.
- TypeScript.
- TanStack Query: 서버 상태와 mutation.
- Zustand: map viewport, view mode, filter draft, selected feature 같은 UI 상태.
- generated OpenAPI type + explicit response normalization: API 응답 경계.
- controlled React state + `src/lib/form-validation.ts`: form 상태와 좌표/bbox 검증.
- TanStack React Table + React Virtual: 운영 목록/검토 화면의 정렬, 선택, row model,
  큰 목록 가상화. 공용 `DataTable`이 기본 표면이다.
- shadcn/ui: Button, Input, Select, Dialog, Sheet, Tabs, Table, Badge, Toast,
  Form, DropdownMenu 등 UI primitive. `Table` primitive는 DataTable의 표시 계층으로만 쓴다.
- MapLibre GL + VWorld style builder: VWorld 지도. `maplibre-vworld` 패키지 dependency는
  두지 않고 `maplibre-vworld-react` web/core 모델을 내부 포팅한다.
- `@kor-travel-map/map-marker-react`: category/maki marker.
- 디자인 규칙: [`admin-frontend-design-rules.md`](admin-frontend-design-rules.md).

규칙:

- API module은 generated OpenAPI 타입과 명시적 response normalization을 기준으로 작성한다.
- form은 controlled React state와 framework-independent field validator를 기본으로 한다.
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

`doctor` script의 정본 명령은
`react-doctor --scope full --no-score --no-telemetry --no-respect-inline-disables --blocking warning .`이며,
정본 설정은 frontend root의 `doctor.config.json` 하나다.
`scripts/verify-react-doctor-config.mjs`는 명령과 설정 전체를 exact 비교하고 저장소/frontend
root의 shadow config, package manifest 안의 별도 설정, lint/format ignore 파일을 거부한다.
T-VN-47 기준 구조 debt 예외는 `no-giant-component` 19개·`prefer-useReducer` 3개 exact 파일이며
`T-VN-49`가 제거를 소유한다. transport lifecycle과 external event effect의 규칙별 false-positive
예외를 포함해 파일·규칙 범위 추가는 verifier 갱신과 task 근거 없이는 허용하지 않는다.

완료 기준:

- React Doctor 결과를 읽고 실제 위험 항목을 개선한다.
- 의도적으로 제외하는 진단은 정본 `doctor.config.json`에 최소 범위와 근거를 남긴다.
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
PinVi/user subset만 갱신할 때는 다음을 쓴다.

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

PinVi client 생성은 PinVi 저장소에서 별도 관리한다. kor-travel-map은
`openapi.user.json`, OpenAPI version, changelog, backward compatibility note를
제공한다.
