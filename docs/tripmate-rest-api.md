# krtour-map REST API 계약 — TripMate 소비 + v1 정리

본 문서는 ADR-045 이후 TripMate가 krtour-map을 HTTP/OpenAPI로 소비할 때의
**정본 REST API 계약**이다. admin 전체 계약은
[`docs/openapi-admin-contract.md`](openapi-admin-contract.md), POI cache target 상세는
[`docs/poi-cache-update-targets.md`](poi-cache-update-targets.md)를 함께 따른다.

기준 검토:

- krtour-map 내부 검토:
  [`docs/reports/api-endpoint-review-2026-06-08.md`](reports/api-endpoint-review-2026-06-08.md)
- TripMate 소비자 문서:
  `F:\dev\tripmate-codex\docs\integrations\krtour-map-rest-api.md`
- 현재 구현 spec:
  `packages/krtour-map-admin/openapi.user.json`

- **Base URL**: `https://<krtour-map-host>` (로컬 `http://127.0.0.1:9011`). TripMate는
  `KRTOUR_MAP_API_URL` env로 주입. **직접 DB 연결·라이브러리 import 금지**(ADR-045).
- **인증**: 운영 1차 인증은 network/infra 계층(Cloudflare Tunnel SSO / IP allowlist,
  D-1). 추가로 **앱 레벨 defense-in-depth**(D-1 B안, 2026-06-08): `KRTOUR_MAP_ADMIN_
  SERVICE_TOKEN` 설정 시 **`/tripmate/*`** 호출은 `X-Krtour-Service-Token` 헤더가 그 값과
  일치(상수시간 비교)해야 한다(불일치/누락 → 401). 미설정이면 강제 안 함(하위호환).
  공용 read(`/features`·`/categories`·`/providers`)는 브라우저 admin UI 공용이라 앱 토큰을
  강제하지 않는다(proxy SSO). OpenAPI `securitySchemes.ServiceToken`으로 계약 명시.
- **응답 봉투**: `{ "data": <payload>, "meta": { "duration_ms": int, ... } }`
  (admin API와 동일, `openapi-admin-contract.md`). list는 `data.items[]` + `data.
  next_cursor`(keyset, D-10).
- **에러**: HTTP status + `{ "error": { "code", "message", "request_id",
  "retry_after_seconds"? } }`. code 예: `FEATURE_NOT_FOUND`(404) /
  `INVALID_BBOX`(422) / `RATE_LIMITED`(429) / `LOCK_BUSY`(409) /
  `UPSTREAM_UNAVAILABLE`(503).
- **좌표**: 모두 WGS84(4326), 순서는 `lon, lat`(ADR-012). bbox는 `min_lon/min_lat/
  max_lon/max_lat`.
- **버전**: 현재는 debug 라우터의 `/debug/version`만 있다. TripMate/user-facing
  `GET /version`은 `T-213h`에서 OpenAPI/패키지/commit 버전 확인 표면으로 추가한다.
  응답 필드 추가는 minor, 제거/의미변경은 major(D-3 versioning 정책).

> **중요 결정(2026-06-08)**:
> `POST/GET /tripmate/feature-update-requests*`는 TripMate 사용자/서비스 표면이 아니라
> **admin 운영 표면으로 이동**한다. Feature update request는 provider 호출, Dagster
> run, rate limit, lock, consistency/dedup 후처리를 동반하는 운영 트리거이므로 정본
> 경로는 `/admin/feature-update-requests*`다. TripMate의 "사용자 제안" 큐는 TripMate
> app DB가 소유하고, 운영자 승인 뒤 admin API로 refresh scope를 실행한다.

## 1. 구현 상태와 목표 계약

현재 `openapi.user.json`은 unversioned 경로와 `/tripmate/*` 일부를 포함한다. Sprint 5
종료 전 REST 표면은 다음 목표 계약으로 정리한다.

| 구분 | 현재 구현 | 목표 계약 | 후속 |
|------|-----------|-----------|------|
| Versioning | `/features/...`, `/categories`, `/providers/...` | 사용자/서비스 리소스는 `/v1/...` | `T-214b` |
| Batch 조회 | `POST /tripmate/features/batch` | `POST /v1/features/batch` | `T-214d` |
| Feature update request | `/admin/feature-update-requests*`만 유지 | `/admin/feature-update-requests*` | `T-214c` 완료 |
| Health/version | `/health`, `/version`, `/debug/*` 중복 | `/health` liveness, `/version` build info, `/ops/health-deep` readiness | `T-214g` 일부 |
| Envelope | 대부분 `{data, meta}` | 성공/목록/단건/mutation 전부 `{data, meta}` | 유지 |
| 페이지네이션 | `cursor/page_size`와 `limit` 혼용 | 페이지 가능한 목록은 `cursor/page_size`, bounded 조회만 `limit` | `T-214e` |
| External write | cache target write가 `/admin/poi-cache-targets`에 있음 | TripMate 직접 write 허용 여부는 별도 결정. 허용 시 `/v1/poi-cache-targets` | `T-214f` |

## 2. 공통 규약

### 2.1 Base URL과 versioning

- 로컬 API: `http://127.0.0.1:9011`
- 운영 API: `https://<krtour-map-api-host>`
- 사용자/서비스 리소스 목표 prefix: `/v1`
- 내부 운영 리소스: `/admin`, `/ops`, `/debug`도 `/v1` 아래 둔다 — **ADR-048로 확장**
  (사용자 지시 "admin도 versioning"; 당초 비버저닝 결정을 supersede). 전 표면 카탈로그와
  정합성 표준은 `docs/rest-api.md` 참조.
- `/health`와 `/version`은 배포 확인용 top-level(비버저닝) 경로로 유지한다.

Breaking change는 `/v2`로 이동한다. 같은 `/v1` 안에서는 필드 추가, enum 값 추가,
optional 필드 추가만 허용한다. 필드 제거, 필수화, 의미 변경, 응답 envelope 변경은
major breaking change다.

현재 unversioned 사용자 경로는 호환 기간에만 유지하고, `/v1` 구현 후 OpenAPI에는
`deprecated: true`로 표기한다.

### 2.2 인증 경계

운영 1차 인증은 Cloudflare Tunnel, SSO 게이트웨이, IP allowlist 같은 인프라 계층이
담당한다(ADR-005). 2026-06-08 D-1 B안 이후 앱 레벨 defense-in-depth도 선택적으로
적용한다.

- `KRTOUR_MAP_ADMIN_SERVICE_TOKEN`이 설정되면 `/tripmate/*` service-to-service 경로는
  `X-Krtour-Service-Token` header가 같은 값이어야 한다.
- 토큰 미설정 환경에서는 하위호환을 위해 강제하지 않는다.
- `/features`, `/categories`, `/providers` 같은 공용 read surface는 브라우저 admin UI도
  사용하므로 앱 토큰을 강제하지 않고 infra/proxy 인증에 맡긴다.

TripMate는 사용자 JWT를 krtour-map으로 전달하지 않는다. 필요한 경우 TripMate server가
service token header를 붙여 호출한다.

### 2.3 성공 envelope

모든 성공 응답은 다음 형식이다.

```json
{
  "data": {},
  "meta": {
    "duration_ms": 12
  }
}
```

목록 응답은 `data.items`와 `data.next_cursor`를 사용한다. `meta.count`는 이번 응답의
item 수를 뜻하고, 전체 개수가 필요한 검색만 `data.total_count`를 선택적으로 둔다.

```json
{
  "data": {
    "items": [],
    "next_cursor": null
  },
  "meta": {
    "count": 0,
    "duration_ms": 12
  }
}
```

### 2.4 오류 envelope

오류 응답은 HTTP status와 다음 envelope를 함께 쓴다.

```json
{
  "error": {
    "code": "FEATURE_NOT_FOUND",
    "message": "Feature를 찾을 수 없습니다.",
    "details": {},
    "request_id": "019f3d5c-..."
  }
}
```

표준 코드:

| code | status | 의미 |
|------|--------|------|
| `VALIDATION_ERROR` | 422 | 요청 스키마 또는 query parameter 오류 |
| `FEATURE_NOT_FOUND` | 404 | feature 없음 또는 삭제됨 |
| `SEARCH_SCOPE_REQUIRED` | 422 | 검색에 `q`와 `bbox`가 모두 없음 |
| `TOO_MANY_IDS` | 422 | batch feature id가 200개 초과 |
| `TARGET_NOT_FOUND` | 404 | POI cache target 없음 |
| `LOCK_BUSY` | 409 | admin update request 즉시 실행 lock 충돌 |
| `RATE_LIMITED` | 429 | provider 또는 API rate limit |
| `UPSTREAM_UNAVAILABLE` | 503 | provider, DB, Dagster, kraddr-geo 등 upstream 장애 |

`LOCK_BUSY`와 `RATE_LIMITED`는 가능하면 `Retry-After` header와
`error.details.retry_after_seconds`를 함께 반환한다.

### 2.5 Parameter 규칙

- 좌표는 WGS84, 순서 `lon`, `lat`.
- bbox는 query parameter `min_lon`, `min_lat`, `max_lon`, `max_lat`를 기본으로 한다.
  검색처럼 단일 parameter가 필요한 경우만 `bbox=min_lon,min_lat,max_lon,max_lat` CSV를
  허용한다.
- 다중 값 query는 반복 parameter를 쓴다. 예: `kind=place&kind=event`.
- 페이지 가능한 목록은 `page_size` + `cursor`를 쓴다.
- 지도 viewport처럼 상한을 둔 bounded 조회는 `limit`만 허용할 수 있다.
- 반경 query는 `radius_m`를 쓴다. 저장 정책이나 cache target 설정처럼 운영자가
  관리하는 값은 기존 DB 계약대로 `radius_km`를 유지한다.
- datetime은 KST aware ISO 8601 문자열이다.

## 3. 사용자/서비스 v1 API

아래가 TripMate가 소비하는 목표 표면이다. 현재 구현의 unversioned 경로는 각 항목의
호환 경로로 본다.

### 3.1 Public status

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | liveness. DB 없이도 200 가능 |
| GET | `/version` | admin package, main lib, OpenAPI, git commit 버전 |

Deep readiness는 admin/ops 표면의 `GET /ops/health-deep`만 사용한다.

### 3.2 Feature read

| Method | Target path | 현재 호환 경로 | 설명 |
|--------|-------------|----------------|------|
| GET | `/v1/features/in-bounds` | `/features/in-bounds` | 지도 bbox feature 또는 행정구역 cluster |
| GET | `/v1/features/nearby` | `/features/nearby` | 좌표 반경 주변 feature |
| GET | `/v1/features/nearby/by-target` | `/features/nearby/by-target` | 등록된 POI cache target 주변 feature |
| GET | `/v1/features/search` | `/features/search` | 이름/bbox 검색 |
| GET | `/v1/features/{feature_id}` | `/features/{feature_id}` | feature 상세 |
| GET | `/v1/features/{feature_id}/weather` | `/features/{feature_id}/weather` | weather metric card |
| POST | `/v1/features/batch` | `/tripmate/features/batch` | feature id batch 상세 조회 |

#### `GET /v1/features/in-bounds`

Query:

- `min_lon`, `min_lat`, `max_lon`, `max_lat` required
- `kind` repeat optional
- `category` repeat optional
- `zoom` optional
- `cluster_unit` optional: `sido`, `sigungu`, `eupmyeondong`
- `limit` optional, default 1000, max 5000

Response:

```json
{
  "data": {
    "count": 1,
    "cluster_unit": null,
    "clusters": [],
    "items": [
      {
        "feature_id": "f_1111014700_p_019c0211c8a5ec4e",
        "kind": "place",
        "name": "경복궁",
        "category": "01070100",
        "lon": 126.977,
        "lat": 37.5796,
        "marker_icon": "monument",
        "marker_color": "P-01",
        "status": "active"
      }
    ]
  },
  "meta": {"duration_ms": 8}
}
```

`cluster_unit`이 있으면 `items=[]`, `clusters[]`를 반환한다.

#### `GET /v1/features/nearby`

Query:

- `lon`, `lat`, `radius_m` required
- `kind`, `category`, `status`, `provider` repeat optional
- `sort` optional: `distance`, `name`, `last_updated_at`
- `page_size` optional
- `cursor` optional

Response `data.items[]`는 `FeatureSummary`에 `distance_m`를 더한 객체다.

#### `GET /v1/features/nearby/by-target`

Query:

- `external_system` required
- `target_key` required
- `radius_km` optional
- `kind`, `category`, `status`, `provider` repeat optional
- `page_size`, `cursor` optional

이 경로는 이미 등록된 target을 읽기만 한다. target 등록/삭제 write 경로는 §5의
후속 결정에 따른다.

#### `GET /v1/features/search`

Query:

- `q` optional
- `bbox` optional CSV: `min_lon,min_lat,max_lon,max_lat`
- `kind`, `category` repeat optional
- `page_size` optional, max 200
- `cursor` optional

`q`와 `bbox` 중 하나 이상이 필요하다.

#### `GET /v1/features/{feature_id}`

`feature_id`는 UUID가 아니라 opaque string이다. TripMate는 파싱하지 않고 그대로 저장한다.

응답 `data` 핵심 필드:

- `feature_id`
- `kind`
- `name`
- `category`
- `lon`, `lat`
- `address`
- `legal_dong_code`, `sido_code`, `sigungu_code`
- `marker_color`, `marker_icon`
- `urls`
- `detail`
- `status`
- `updated_at`

#### `POST /v1/features/batch`

Request:

```json
{
  "feature_ids": ["f_1111014700_p_019c0211c8a5ec4e"]
}
```

`feature_ids`는 최대 200개다. 초과 trip은 TripMate client가 chunking한다.

Response:

```json
{
  "data": {
    "items": {
      "f_1111014700_p_019c0211c8a5ec4e": {}
    },
    "missing": []
  },
  "meta": {"duration_ms": 12}
}
```

없는 id와 soft-deleted feature는 `missing`에 넣는다.

### 3.3 Catalog / provider status

| Method | Target path | 현재 호환 경로 | 설명 |
|--------|-------------|----------------|------|
| GET | `/v1/categories` | `/categories` | category catalog |
| GET | `/v1/providers/{provider}/last-sync` | `/providers/{provider}/last-sync` | provider sync state |

`GET /v1/categories`는 `include_counts`, `active_only` query를 받는다.
`GET /v1/providers/{provider}/last-sync`는 `dataset_key`, `sync_scope` filter를 받는다.

## 4. Admin API

Admin API는 운영자 전용이다. TripMate 사용자 flow나 public web client가 직접 호출하지
않는다. 인증은 코드가 아니라 인프라 계층에서 강제한다.

### 4.1 Feature update request

정본 경로:

| Method | Path | 설명 |
|--------|------|------|
| GET | `/admin/feature-update-requests` | update request 목록 |
| POST | `/admin/feature-update-requests` | update request 생성 또는 dry-run |
| GET | `/admin/feature-update-requests/{request_id}` | 상태 조회 |
| POST | `/admin/feature-update-requests/{request_id}/cancel` | 취소 |
| POST | `/admin/feature-update-requests/{request_id}/run-now` | 즉시 실행 재큐잉 |

`/tripmate/feature-update-requests*`는 제거됐다. 같은 기능을 두 namespace에 동시에
노출하지 않는다.

TripMate에서 사용자가 "새 장소 추가" 또는 "정보 수정"을 제안하는 경우:

1. TripMate app DB의 사용자 제안 큐에 저장한다.
2. TripMate/Admin 운영자가 검토한다.
3. 승인된 제안만 krtour-map admin API의 `scope`로 변환해
   `POST /admin/feature-update-requests`를 호출한다.

### 4.2 Feature 사용자 요청 추가·수정·삭제

사용자 요청으로 krtour-map DB에 feature를 직접 추가·수정·삭제해야 하는 경우 정본은
`/admin/features*`다. TripMate public client가 직접 호출하지 않고, TripMate app DB의
사용자 제안 큐나 운영 화면을 거친 뒤 admin API로 전달한다.

처리 모드는 krtour-map admin backend 설정
`KRTOUR_MAP_ADMIN_FEATURE_CHANGE_REVIEW_MODE`로 제어한다.

| 값 | 의미 |
|----|------|
| `require_review` | 기본값. 요청을 `ops.feature_change_requests.state='pending'`으로 저장하고 승인 후 반영 |
| `immediate` | 요청 transaction에서 바로 반영하고 `state='applied'`로 저장 |

엔드포인트:

| Method | Path | 설명 |
|--------|------|------|
| GET | `/admin/features/change-requests` | add/update/delete 요청 목록 |
| POST | `/admin/features` | `place` 또는 `event` feature 추가 요청 |
| PATCH | `/admin/features/{feature_id}` | `place` 또는 `event` feature 수정 요청 |
| DELETE | `/admin/features/{feature_id}` | `place` 또는 `event` feature 사용자 요청 soft delete |
| POST | `/admin/features/change-requests/{request_id}/approve` | pending 요청 승인·적용 |
| POST | `/admin/features/change-requests/{request_id}/reject` | pending 요청 거절 |

버전/재적재 규칙:

- provider 적재 데이터는 `data_origin='provider'`, `data_version=0`이다.
- 사용자 요청으로 추가·수정·삭제된 데이터는 `data_origin='user_request'`,
  `data_version=1`이다.
- provider 재적재가 같은 `feature_id`를 다시 적재하면 provider snapshot은 version 0에
  갱신하되, 적용 중인 사용자 version 1 필드를 덮어쓰지 않는다.
- 사용자 요청 삭제는 soft delete다. `status='deleted'`, `deleted_at`,
  `user_deleted_at`, `user_deleted_by`, `user_change_request_id`를 남기며 provider
  재적재나 snapshot 누락 정리로 다시 살아나지 않는다.
- 사용자 요청 추가 데이터는 재적재 snapshot 미포함 정리에서 삭제하지 않는다.

### 4.3 POI cache target

현재 구현 정본:

| Method | Path | 설명 |
|--------|------|------|
| GET | `/admin/poi-cache-targets` | target 목록 |
| GET | `/admin/poi-cache-targets/{external_system}/{target_key}` | target 상세 |
| PUT | `/admin/poi-cache-targets/{external_system}/{target_key}` | target upsert |
| DELETE | `/admin/poi-cache-targets/{external_system}/{target_key}` | target 삭제 |

TripMate가 POI 생성/수정/삭제 때 target을 직접 write해야 한다면 `/admin`을 노출하지
말고 service-safe 경로를 별도로 만든다. 후보는
`/v1/poi-cache-targets/{external_system}/{target_key}`다. 이 결정과 구현은 `T-214f`로
분리한다.

### 4.4 기타 admin/ops/debug

아래 경로는 admin 전체 OpenAPI에만 포함한다.

- `/admin/features`
- `/admin/issues`
- `/admin/dedup-review`
- `/admin/enrichment-review`
- `/admin/offline-uploads`
- `/admin/backups`, `/admin/restore`
- `/ops/metrics`, `/ops/import-jobs`, `/ops/consistency/*`
- `/ops/system-logs`, `/ops/api-call-logs`
- `/ops/dagster/*`
- `/debug/*`

`/debug/health`와 `/debug/version`은 개발자 호환 경로로 유지하되, TripMate/public
상태 확인은 `/health`와 `/version`만 사용한다.

## 5. TripMate 소비 매핑

| TripMate 기능 | krtour-map 목표 API | 비고 |
|---------------|---------------------|------|
| 지도 viewport | `GET /v1/features/in-bounds` | 서버 cluster 사용 |
| 주변 feature | `GET /v1/features/nearby` | cursor 페이지네이션 |
| POI target 주변 | `GET /v1/features/nearby/by-target` | target write API는 `T-214f` 결정 |
| feature 상세 | `GET /v1/features/{feature_id}` | `feature_id` opaque string |
| trip view batch | `POST /v1/features/batch` | 기존 `/tripmate/features/batch` 대체 |
| 검색 | `GET /v1/features/search` | 주소/내 POI 검색은 TripMate가 합성 |
| 날씨 카드 | `GET /v1/features/{feature_id}/weather` | `forecast_style`별 grouping은 TripMate 표현 계층 |
| 카테고리 | `GET /v1/categories` | 긴 TTL 캐시 가능 |
| provider 신선도 | `GET /v1/providers/{provider}/last-sync` | 사용자 표시 또는 admin 상태판 |
| 사용자 장소 제안 | 없음 | TripMate app DB 큐가 소유 |
| 운영 feature 추가/수정/삭제 | `/admin/features*` | admin review mode에 따라 pending 또는 즉시 반영 |
| 운영 refresh 실행 | `/admin/feature-update-requests*` | admin/operator flow만 |

## 6. 누락/정리 backlog

REST 표면을 위 목표 계약으로 맞추기 위한 후속 task는 `docs/tasks.md`의 `T-214` 묶음이
정본이다. 핵심은 다음 순서다.

1. `/v1` prefix 도입과 unversioned 호환 경로 deprecation.
2. `/tripmate/feature-update-requests*` 제거, admin-only 전환. (완료)
3. `POST /tripmate/features/batch`를 `POST /v1/features/batch`로 이동.
4. pageable list parameter를 `cursor/page_size`로 정렬.
5. POI cache target write를 external service API로 열지 admin-only로 둘지 결정.
6. idempotency/rate-limit header, error code, deprecation header 규약을 OpenAPI에 명시.

가격 시계열(`GET /v1/features/{feature_id}/prices`), 검색 자동완성,
route/path GeoJSON, webhook/SSE 알림은 Sprint 5 운영 진입 이후 별도 제품 요구로
분리한다.
