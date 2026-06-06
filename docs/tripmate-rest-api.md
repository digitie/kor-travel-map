# tripmate-rest-api.md — TripMate ↔ krtour-map 연계 REST API (params/returns)

ADR-045 기준 TripMate가 krtour-map **OpenAPI(HTTP)** 로 호출하는 사용자/서비스 API의
엔드포인트·파라미터·리턴값 구체화. admin API 전체 계약은 `docs/openapi-admin-contract.md`,
admin UI 워크플로는 `docs/debug-ui-admin-workflows.md`가 정본 — **본 문서는 TripMate가
실제로 쓰는 부분 집합 + 사용자 공개 응답 형태**를 확정한다.

> 상태: **1차 계약 구현됨 (2026-06-03, T-207e/T-207g)** — TripMate/user-facing
> 정본 spec은 `packages/krtour-map-admin/openapi.user.json`이다. `GET
> /features/in-bounds`, `GET /features/{feature_id}`, `GET /features/search`,
> `GET /features/nearby`(T-213b), `GET /features/nearby/by-target`,
> `POST /tripmate/features/batch`,
> `POST /tripmate/feature-update-requests`,
> `GET /tripmate/feature-update-requests/{request_id}`가
> user spec과 동기화됐다. D-1~D-16은 전부 확정됨
> (`docs/adr045-open-decisions.md`). 시군구 반경 해석(D-11)의 kraddr-geo
> `POST /v2/regions/within-radius` 정본은 `docs/regions-within-radius.md`.
> TripMate `docs/krtour-map-requirements.md` 대조 후속은
> `docs/reports/tripmate-requirements-reconcile-2026-06-06.md`와 `docs/tasks.md`
> `T-213a~h`에 등록했다. **구현됨**(user spec 포함): 일반 좌표 `/features/nearby`
> (T-213b), category catalog `GET /categories`(T-213f), public `GET /health`/
> `GET /version`(T-213h), provider last-sync `GET /providers/{provider}/last-sync`
> (T-213g), weather card `GET /features/{feature_id}/weather`(T-213e). **T-213a~h
> 전부 구현 완료** — user spec은 `/features/*`(in-bounds/search/nearby/{id}/weather),
> `/categories`, `/providers/{provider}/last-sync`, `/health`, `/version`,
> `/tripmate/*`다.

## 1. 공통 규약

- **Base URL**: `https://<krtour-map-host>` (로컬 `http://127.0.0.1:9011`). TripMate는
  `KRTOUR_MAP_API_URL` env로 주입. **직접 DB 연결·라이브러리 import 금지**(ADR-045).
- **인증**: 코드에 인증 로직 없음(ADR-005). 운영은 network/infra 계층(Cloudflare
  Tunnel SSO / IP allowlist / API key header pass-through, D-1). TripMate는 서비스
  토큰을 헤더로 전달하되 krtour-map은 "인증된 요청만 도달" 가정.
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

## 2. Feature 공개 응답 형태

`/features/*`(사용자) 응답의 feature 객체. admin 전용 필드(source_records 원문,
dedup history, consistency 참조)는 **제외**(D-7 — 분리 확정 시 admin은 `/admin/
features/*`로). 기존 `routers/features.py` 응답을 사용자용으로 정제한 형태.

### 2.1 `FeatureSummary` (목록/지도용 경량)
```json
{
  "feature_id": "f_1111014700_p_019c0211c8a5ec4e",
  "kind": "place",
  "name": "경복궁",
  "category": "01070100",
  "lon": 126.9770, "lat": 37.5796,
  "marker_icon": "monument", "marker_color": "P-01",
  "status": "active"
}
```

### 2.2 `FeatureDetail` (상세 카드용)
```json
{
  "feature_id": "f_1111014700_p_019c0211c8a5ec4e",
  "kind": "place",
  "name": "경복궁",
  "category": "01070100",
  "lon": 126.9770, "lat": 37.5796,
  "address": { "road": "...", "admin": "...", "bjd_code": "1111014700",
               "sido_code": "11", "sigungu_code": "11110" },
  "detail": { "place_kind": "heritage", "phones": ["02-3700-3900"], "...": "..." },
  "urls": { "homepage": "...", "image": ["..."] },
  "marker_icon": "monument", "marker_color": "P-01",
  "status": "active",
  "updated_at": "2026-06-01T08:30:00+09:00"
}
```
- `detail`은 kind별 DTO(`PlaceDetail`/`EventDetail`/`NoticeDetail`/…, ADR-018) JSON.
- `kind=price`/`weather`는 시계열이라 별도 엔드포인트(§4)로 노출; feature 본문엔 미포함.

## 3. 엔드포인트 (TripMate 사용)

### 3.1 `GET /features/in-bounds` — 지도 뷰포트 로드
- **목적**: TripMate 지도 화면 bbox 안 feature 경량 목록(+줌별 클러스터).
- **query**: `min_lon`(float, req), `min_lat`, `max_lon`, `max_lat`(req),
  `kind`(반복, 선택 — place/event/notice/route/area), `category`(반복, 선택),
  `zoom`(int, 선택 — `cluster_unit` 미지정 시 유도), `cluster_unit`(선택 —
  `sido`|`sigungu`|`eupmyeondong`), `limit`(int, 기본 1000, ≤5000).
- **클러스터링(T-213c — 구현됨)**: `cluster_unit`이 지정되거나 `zoom`으로
  유도되면(zoom ≤7=sido / ≤10=sigungu / ≤13=eupmyeondong / ≥14=개별) **서버
  행정구역 rollup**으로 응답한다. (설계 결정: client-side·grid 대신 **행정코드
  rollup** — feature에 이미 있는 `sido_code`/`sigungu_code`/`legal_dong_code`를
  GROUP BY해 geometry 계산 없이 region별 count + 평균 좌표를 낸다.)
- **200**: `{ "data": { "count": int, "items": [FeatureSummary],
  "clusters": [{ "cluster_key", "feature_count", "lon", "lat" }],
  "cluster_unit": str|null }, "meta": { "duration_ms": int } }`. `cluster_unit`이
  None이면 `items`(개별 feature), 아니면 `clusters`(rollup, `items=[]`). `lon`/`lat`은
  region 내 feature 평균 좌표(대표 마커 위치), region code 없는 feature는 제외.
- **422** bbox min>max / 잘못된 `cluster_unit`. GIST(`coord`) 인덱스 사용
  (ADR-012, 술어에 변환 없음), `deleted_at IS NULL`.

### 3.2 `GET /features/{feature_id}` — 상세
- **목적**: POI 상세 카드.
- **path**: `feature_id`.
- **200**: `{ "data": FeatureDetail, "meta": { "duration_ms": int } }`.
  **404** `FEATURE_NOT_FOUND`.

### 3.3 `POST /tripmate/features/batch` — 다건 상세 batch
- **목적**: trip에 붙은 여러 POI를 한 번에 조회(N+1 방지).
- **body**: `{ "feature_ids": ["...", "..."] }` (≤200, 초과 422 `TOO_MANY_IDS`).
- **200**: `{ "data": { "items": { "<feature_id>": FeatureDetail }, "missing":
  ["<feature_id>"] }, "meta": { "duration_ms": int } }` — 없는 id와 soft-deleted
  id는 `missing`에.

### 3.4 `GET /features/search` — 검색
- **목적**: 사용자 feature 검색(이름 + 공간).
- **query**: `q`(str, 선택 — name trgm), `kind`(반복), `category`(반복),
  `bbox`(`min_lon,min_lat,max_lon,max_lat` CSV, 선택), `limit`(기본 50, ≤200),
  `cursor`(keyset, 선택).
- **200**: `{ "data": { "items": [FeatureSummary], "next_cursor": str|null,
  "total_count": int|null }, "meta": { "duration_ms": int } }`. (`q`/`bbox` 둘 다
  없으면 422 `SEARCH_SCOPE_REQUIRED`.) `total_count`는 현재 keyset 최적화 우선으로
  `null`이다.

### 3.5 `GET /features/nearby/by-target` — 외부 POI key 기준 주변 조회
- **목적**: TripMate가 보유한 외부 POI(kakao/naver/google place id 등) 기준 주변
  feature summary. 정본: `poi-cache-update-targets.md`.
- **query**: `external_system`(str, req — kakao|naver|google|…), `target_key`(str,
  req), `radius_km`(float, 기본 1.0), `kind`(반복), `limit`(기본 50).
- **200**: `{ "data": { "target": {external_system,target_key,lon,lat},
  "items": [NearbyFeatureSummary] } }`. **404** target 미등록 시.
- `NearbyFeatureSummary`는 `FeatureSummary` 경량 필드에 `distance_m`만 더한다.
  `primary_provider`, `primary_dataset_key`, target `refresh_policy`, `target_id` 같은
  운영/내부 필드는 사용자 응답에 노출하지 않는다(D-7).

### 3.6 `GET /providers/{provider}/last-sync` — 데이터 신선도 (T-213g — 구현됨)
- **목적**: 상세 카드 "n시간 전 갱신" 표시.
- **path**: `provider`(예: `python-mois-api`). **query**: `dataset_key`(선택),
  `sync_scope`(선택) — 필터.
- **200**: `{ "data": { "provider", "items": [{ "dataset_key", "sync_scope",
  "status", "last_success_at", "last_failure_at", "consecutive_failures" }],
  "count" }, "meta": { "count", "duration_ms" } }`(`provider_sync_state` 기반).
  내부 **cursor(provider 증분 상태)는 응답에 노출하지 않는다**(운영 내부 값).
  provider가 여러 dataset/scope를 가지므로 `items` 목록으로 반환한다.
- **404**: provider에 매칭되는 sync state 행이 없을 때(필터 결과 0건 포함).
- `AsyncKrtourMapClient`에 `get_sync_state`/`list_sync_states`(read) +
  `record_sync_success`/`record_sync_failure`(write) helper, `krtour.map.providers`
  에 knps/krheritage 변환 함수·상수 re-export 동반(T-213g).

### 3.7 `POST /tripmate/feature-update-requests` — 지역 refresh 요청
- **목적**: TripMate 운영 화면에서 "이 지역 데이터 즉시 갱신".
  krtour-map admin 내부 경로(`/admin/feature-update-requests`)와 같은 queue에 적재하지만,
  TripMate/user OpenAPI에는 `/tripmate` prefix만 노출한다.
- **body/응답**: `openapi-admin-contract.md §5.1` 그대로 — scope(center_radius/bbox/
  sigungu_by_radius/provider_dataset/feature_ids/cache_target_keys) + update_policy +
  `run_mode`(queued|now) + `dry_run`. 응답: `{ data: { request_id, job_id, state,
  matched_scope: { feature_count, sigungu_codes } , status_url } }`.
- **dry_run=true**: 실행 없이 `matched_scope`만(영향 feature 수 미리보기).
- **409** `LOCK_BUSY`(run_mode=now + 동일 scope lock 점유, D-6 정책). 응답은
  `{error:{code:"LOCK_BUSY", message, details:{retry_after_seconds:15}}}`이며 HTTP
  header `Retry-After: 15`를 함께 보낸다.

### 3.8 `GET /tripmate/feature-update-requests/{request_id}` — 진행 상태
- **목적**: TripMate가 refresh 완료 폴링.
- **200**: `{ data: { request_id, state(queued|running|done|failed|cancelled),
  matched_scope, job_id, started_at, finished_at, error_message } }`.

### 3.9 `GET /health` / `GET /version` (T-213h — 구현됨)
- `/health`(**liveness**): `{ data: { status: "ok", service: "krtour-map" },
  meta: { duration_ms } }`. 의존 없는 정적 200 — `features_routes_enabled`와 무관하게
  항상 mount(DB 없는 부팅에서도 동작). DB/RustFS/Dagster **deep readiness**는 후속
  (`/ops/health-deep` 계열) — liveness probe가 DB 장애에도 동작해야 하므로 분리.
- `/version`: `{ data: { version, krtour_map_version, openapi_version,
  commit }, meta }`. `version`=배포 프로그램(admin) 버전, `krtour_map_version`=메인
  lib, `commit`=env `KRTOUR_MAP_GIT_COMMIT`(없으면 null). 클라이언트 호환 확인용.
- 기존 `/debug/health`, `/debug/version`은 debug gate 하에 그대로 유지.
  TripMate/user spec의 public liveness/readiness 표면은 `T-213h`에서 분리해 추가한다.

### 3.10 `GET /categories` — PlaceCategory 카탈로그 (T-213f)
- **목적**: TripMate/admin frontend의 marker·필터용 정적 category 카탈로그(144건,
  ADR-023/027) + 선택적 현재 DB 분포.
- **query**: `include_counts`(bool, 기본 false — true면 category별 DB feature 수 포함),
  `active_only`(bool, 기본 false — counts를 `status='active'` feature만으로).
- **200**: `{ "data": { "items": [CategorySummary], "count": 144,
  "include_counts": bool }, "meta": { "count", "duration_ms" } }`.
  `CategorySummary` = `code`/`depth`/`tier1~4_code`·`name`/`label`/`path[]`/
  `parent_code`/`sort_order`/`is_active`/`maki_icon`(+ `include_counts`면
  `db_feature_count`/`db_active`). 정적 카탈로그는 immutable이라 모듈 로드 시 1회 구성
  (ADR-030). 카탈로그 정본은 `krtour.map.category`(`docs/category.md`).

## 4. 시계열·미디어
### 4.1 `GET /features/{feature_id}/weather` — weather card (T-213e — 구현됨)
- **목적**: POI 상세 카드의 날씨 — forecast_style별 최신 metric + freshness.
- **path**: `feature_id`(weather kind feature). **query**: `asof`(선택 — 이 시점 이하
  weather만, 미래 예보 제외).
- **200**: `{ "data": { "feature_id", "asof", "source_styles": [str],
  "metrics": [{ "forecast_style", "metric_key", "metric_name", "timeline_bucket",
  "value_number"(float), "value_text", "unit", "severity", "issued_at", "valid_at",
  "observed_at" }], "latest_at", "is_stale": bool }, "meta": { "duration_ms" } }`.
  각 (forecast_style, metric_key)에서 `COALESCE(valid_at, observed_at, issued_at)`
  최신 1건(DISTINCT ON). `source_styles`는 source trace(nowcast/ultra_short/short/mid/
  observed/advisory 등). `is_stale`은 최신 weather가 `asof`(또는 now) 기준 기본 6h를
  넘으면 true. weather 없으면 빈 card(200). 적재 정본은 `feature.feature_weather_values`
  (alembic 0017, ADR-010 — `make_weather_value_key` PK).
- `kind=price`는 별도 `GET /features/{id}/prices`(후속). media는 `FeatureDetail.urls`
  + RustFS 공개 URL.

## 5. 마이그레이션 (TripMate 측, 별도 repo)
- 구(ADR-003): `AsyncKrtourMapClient` 직접 import → feature 조회.
- 신(ADR-045) — **kraddr-geo 동일방식(D-4)**:
  - **backend(Python `apps/api`)**: 수기 httpx wrapper
    `integrations/krtour_map_client.py`(krtour-map의 `KraddrGeoRestClient`처럼,
    codegen 아님; timeout/retry/error 변환). 직접 import 제거.
  - **frontend(Next.js/TS)**: krtour-map `openapi.user.json` →
    `openapi-typescript` codegen + 수동 Zod mirror + CI diff 게이트.
- TripMate는 `feature_id`만 외부 참조로 저장(FK 없음, ADR-045 §2).

## 6. 결정 반영 / 미확정 (→ adr045-open-decisions.md)

**결정됨 (2026-06-01~02, 전부 adr045-open-decisions.md 반영)**:
- **D-7 분리** — 본 문서의 `/features/*`는 공개(정제 필드). 원문 source_records·
  provider/dataset 식별자, dedup·consistency·target refresh policy는
  `/admin/features/*` 또는 `/admin/poi-cache-targets/*`(별도). 사용자 응답엔 미노출.
- **D-6** — `run_mode=now` + 동일 scope lock 점유 시 **409 + `retry_after`**(§3.7,
  queued fallback 아님). request:job=1:1.
- **D-1** — infra(reverse proxy) 인증 + `X-Krtour-Service-Token` pass-through.
- **D-3** — SemVer + admin/사용자 OpenAPI schema 이원화 (client 생성은 D-4).
- **D-11** — 시군구 반경 해석은 kraddr-geo `POST /v2/regions/within-radius`,
  `sig_cd`(5자리) = `features.sigungu_code`. 정본: `docs/regions-within-radius.md`.

**잔여(ADR-045 결정 대상 아님)**:
- ~~일반 좌표 기준 `/features/nearby`~~ ✅ **구현됨(T-213b)** — `GET /features/nearby`
  (`lon`/`lat`/`radius_m`(≤100km)/`kind[]`/`category[]`/`status[]`/`provider[]`/
  `sort`(distance|name|last_updated_at)/`page_size`/`cursor`). 응답은
  `{data:{origin, items[NearbyFeatureSummary], next_cursor}, meta:{count, duration_ms}}`,
  user subset(`openapi.user.json`)에 포함. ADR-012: 입력 좌표를 CTE에서 1회만 5179로
  변환하고 술어는 STORED `coord_5179`에 적용(by-target nearby와 동일 candidates CTE).
- 클러스터링(`cluster_unit`) 알고리즘/줌 매핑 — `T-213c`.
- provider last-sync, public health/version, weather card/category catalog —
  `T-213e~h`.
