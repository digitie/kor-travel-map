# tripmate-rest-api.md — TripMate ↔ krtour-map 연계 REST API (params/returns)

ADR-045 기준 TripMate가 krtour-map **OpenAPI(HTTP)** 로 호출하는 사용자/서비스 API의
엔드포인트·파라미터·리턴값 구체화. admin API 전체 계약은 `docs/openapi-admin-contract.md`,
admin UI 워크플로는 `docs/debug-ui-admin-workflows.md`가 정본 — **본 문서는 TripMate가
실제로 쓰는 부분 집합 + 사용자 공개 응답 형태**를 확정한다.

> 상태: **계약 초안(1차)** — 구현(Phase 3 `/features/*` 라우터, T-207e) 시 OpenAPI와
> 동기. 미확정 부분은 `docs/adr045-open-decisions.md`(D-7 admin↔사용자 응답 분리,
> D-1 인증, D-3 schema 이원화)에 표시.

## 1. 공통 규약

- **Base URL**: `https://<krtour-map-host>` (로컬 `http://127.0.0.1:8087`). TripMate는
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
- **버전**: `GET /version` 으로 OpenAPI/패키지 버전 확인(드리프트 게이트, D-3). 응답
  필드 추가는 minor, 제거/의미변경은 major(D-3 versioning 정책).

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
  `zoom`(int, 선택 — 클러스터 단위 결정), `limit`(int, 기본 1000, ≤5000).
- **200**: `{ "data": { "count": int, "items": [FeatureSummary], "cluster_unit":
  str|null } }`. (현재 `feature_repo.features_in_bbox` 재사용; 클러스터는 D-7 후속.)
- **422** `INVALID_BBOX`(min>max). GIST(`coord`) 인덱스 사용, `deleted_at IS NULL`.

### 3.2 `GET /features/{feature_id}` — 상세
- **목적**: POI 상세 카드.
- **path**: `feature_id`.
- **200**: `{ "data": FeatureDetail }`. **404** `FEATURE_NOT_FOUND`.

### 3.3 `POST /tripmate/features/batch` — 다건 상세 batch
- **목적**: trip에 붙은 여러 POI를 한 번에 조회(N+1 방지).
- **body**: `{ "feature_ids": ["...", "..."] }` (≤200, 초과 422 `TOO_MANY_IDS`).
- **200**: `{ "data": { "items": { "<feature_id>": FeatureDetail }, "missing":
  ["<feature_id>"] } }` — 없는 id는 `missing`에.

### 3.4 `GET /features/search` — 검색
- **목적**: 사용자 feature 검색(이름 + 공간).
- **query**: `q`(str, 선택 — name trgm), `kind`(반복), `category`(반복),
  `bbox`(`min_lon,min_lat,max_lon,max_lat` CSV, 선택), `limit`(기본 50, ≤200),
  `cursor`(keyset, 선택).
- **200**: `{ "data": { "items": [FeatureSummary], "next_cursor": str|null,
  "total_count": int|null } }`. (`q`/`bbox` 둘 다 없으면 422 `SEARCH_SCOPE_REQUIRED`.)

### 3.5 `GET /features/nearby/by-target` — 외부 POI key 기준 주변 조회
- **목적**: TripMate가 보유한 외부 POI(kakao/naver/google place id 등) 기준 주변
  feature summary. 정본: `poi-cache-update-targets.md`.
- **query**: `external_system`(str, req — kakao|naver|google|…), `target_key`(str,
  req), `radius_km`(float, 기본 1.0), `kind`(반복), `limit`(기본 50).
- **200**: `{ "data": { "target": {external_system,target_key,lon,lat},
  "items": [FeatureSummary] } }`. **404** target 미등록 시.

### 3.6 `GET /providers/{provider}/last-sync` — 데이터 신선도
- **목적**: 상세 카드 "n시간 전 갱신" 표시.
- **path**: `provider`(예: `python-mois-api`). **query**: `dataset_key`(선택),
  `sync_scope`(선택, 기본 default).
- **200**: `{ "data": { "provider", "dataset_key", "sync_scope",
  "last_success_at", "last_failure_at", "cursor" } }`(`provider_sync_state`).
  **404** 미존재 scope.

### 3.7 `POST /admin/feature-update-requests` — 지역 refresh 요청 (운영/TripMate)
- **목적**: TripMate 운영 화면에서 "이 지역 데이터 즉시 갱신". admin API 재사용.
- **body/응답**: `openapi-admin-contract.md §5.1` 그대로 — scope(center_radius/bbox/
  sigungu_by_radius/provider_dataset/feature_ids/cache_target_keys) + update_policy +
  `run_mode`(queued|now) + `dry_run`. 응답: `{ data: { request_id, job_id, state,
  matched_scope: { feature_count, sigungu_codes } , status_url } }`.
- **dry_run=true**: 실행 없이 `matched_scope`만(영향 feature 수 미리보기).
- **409** `LOCK_BUSY`(run_mode=now + 동일 scope lock 점유, D-6 정책).

### 3.8 `GET /admin/feature-update-requests/{request_id}` — 진행 상태
- **목적**: TripMate가 refresh 완료 폴링.
- **200**: `{ data: { request_id, state(queued|running|done|failed|cancelled),
  matched_scope, job_id, started_at, finished_at, error_message } }`.

### 3.9 `GET /health` / `GET /version`
- `/health`: `{ data: { status, db, rustfs? } }` — TripMate liveness.
- `/version`: `{ data: { version, openapi_version, commit? } }` — 클라이언트 호환.

## 4. (후속) 시계열·미디어
- `kind=price`/`weather`는 feature 본문 대신 `GET /features/{id}/prices` /
  `/weather`(시계열) 별도 — 사용자 노출 범위는 후속 결정. media는 `FeatureDetail.urls`
  + RustFS 공개 URL.

## 5. 마이그레이션 (TripMate 측, 별도 repo)
- 구(ADR-003): `AsyncKrtourMapClient` 직접 import → feature 조회.
- 신(ADR-045): `httpx` client로 위 엔드포인트 호출. TripMate `apps/api`에
  `integrations/krtour_map_client.py`(timeout/retry/error 변환) 신규.
- TripMate는 `feature_id`만 외부 참조로 저장(FK 없음, ADR-045 §2).

## 6. 미확정 (→ adr045-open-decisions.md)
- D-7: `/features/{id}` 응답을 admin/사용자 동일로 둘지, admin은 `/admin/features/*`
  로 분리할지(원문 source_records·dedup·consistency 필드 노출 여부).
- D-1: 인증 헤더 규약(서비스 토큰/API key 이름).
- D-3: OpenAPI versioning + admin/사용자 schema 이원화 + client 생성 시점(D-4).
- D-6: feature-update run_mode=now lock 충돌 시 409 vs queued fallback.
- 클러스터링(`cluster_unit`) 알고리즘/줌 매핑.
