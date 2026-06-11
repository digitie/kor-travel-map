# krtour-map REST API — 전 표면 카탈로그 + 정합성 표준

> **상태**: 2026-06-10. PR #317(T-214/T-215)의 `/v1` 1차 정리 위에 ADR-048(admin/ops
> versioning 확장 + envelope/pagination/parameter/response 정합성 표준 + 코드/DB 명명 전파
> T-216a~g)을 얹은 기준선.
> **범위**: krtour-map **전 표면**(user/TripMate + admin + ops + debug)의 **단일 계약 정본**
> (ADR-048 #9). `docs/tripmate-rest-api.md`는 TripMate **소비 매핑 view**로 수렴하고 계약
> 세부는 본 문서로 위임한다(수렴 작업 T-216g).
> **정본 우선순위**: 기계 정본 = `packages/krtour-map-admin/openapi.json`·`openapi.user.json`.
> 충돌 시 **OpenAPI 우선**. 결정 = ADR-048.
> **전환 정책(ADR-048)**: 호환성 미고려 — `/v1` clean cut, 구 경로/alias 없음.
> **표기**: 🆕 신규 · 🔁 변경 · ⚠️ 제거 · ✅#317 = #317로 이미 구현.

---

## 0. 한눈에 — #317이 한 것 vs ADR-048 delta

| 영역 | #317(T-214/T-215) | ADR-048 보강 |
|------|-------------------|-------------|
| versioning | 외부(`/features`·`/tripmate`·`/categories`·`/providers`) `/v1`, **admin/ops 비버저닝** | **admin/ops/debug도 `/v1`**(사용자 지시, T-214b §2.1 supersede) |
| 인증 | `ServiceToken`(#314), 공용 read 비강제 | 유지 |
| feature-update-request | `/tripmate/*` alias 제거 → `/admin/*` 단일 ✅ | 유지(중복 C2 해소됨) |
| 단건 feature add/edit/delete | `/admin/features` POST/PATCH/DELETE + change-requests ✅(K-15) | 유지 |
| envelope | `{data,meta}`(라우터별 `*Meta`) | 공유 `Meta` + **`meta.page{page_size,next_cursor,total}`**, `data`=payload만, `count` 폐기, 성공 meta `request_id` |
| pagination | cursor/page_size(고수준) | `page_size` 단일·2-티어 캡·`total` opt-in·`/features` cursor |
| parameter | bbox 분리 float 권고 | bbox 통일·`state`→`status`·issue noun·다중 반복 |
| error | header 규약(T-214g) | RFC7807 `application/problem+json` body |
| 응답 식별자 | — | surrogate `*_id` / 자연·복합키 `*_key` **전면(본질 기준)**. `cluster_key`(행정코드 자연키) 유지 |
| 전환 | dual-support alias | **무-호환 clean cut**(구 경로/`/debug/health|version` 제거) |
| 코드/DB 명명 | — | 내부 소유 end-to-end 정렬(테이블별 migration) |

---

## 1. 공통 규약 (전 엔드포인트)

### 1.1 Base URL · 포트 (ADR-047)
- API `http://127.0.0.1:9011`(admin UI `9012`, Dagster `9013`, Postgres host `15433`,
  RustFS `9003`/`9004`). `TRIPMATE_KRTOUR_MAP_API_BASE_URL`은 host root까지만 포함하고,
  모든 REST path가 `/v1` prefix를 명시한다(예: base `http://127.0.0.1:9011` +
  path `/v1/features/search`). base와 path 양쪽에 `/v1`를 중복 삽입하지 않는다.

### 1.2 Versioning (ADR-048 — #317 확장)
- **전 표면 `/v1`**: `/v1/features/*`·`/v1/categories`·`/v1/providers/*`
  **+ `/v1/admin/*`·`/v1/ops/*`·`/v1/debug/*`**(ADR-048이 #317의 admin 비버저닝을 supersede).
  `/tripmate/*` namespace는 **제거**(krtour-map은 TripMate에만 묶이지 않음) — batch는
  `/v1/features/batch`로 일반화.
- **비버저닝 고정**: `/health`·`/version`. 경로별 shim 금지(ADR-046) — mount 1곳 전환.
- **무-호환 clean cut(ADR-048, 사용자 지시)**: 호환성은 고려하지 않는다. 구 unprefixed
  경로·호환 alias를 유지하지 않고 `/v1`로 **즉시 단일 전환**한다(이중 코드경로 제거). 소비자
  (TripMate)는 안정 spec commit 기준으로 lockstep 추종(T-181) — 별도 dual-support 창 없음.
- **`/vN` major 거버넌스(ADR-048 #13)**: **pre-1.0(현재)** = `/v1` 가변, in-place breaking
  허용(위 clean cut). **v1.0.0 GA에서 `/v1` 동결** → 이후 breaking = `/v2` + N-1 동시지원
  (`Deprecation`/`Sunset` 헤더), OpenAPI major별 분리 export. 즉 "지금은 깨도 되고, GA 후엔
  `/v2`로만 깬다"를 규칙화.

### 1.3 인증 (ADR-005 / ADR-045 D-1, #314)
- `POST /v1/features/batch`(service read): `ServiceToken`(`X-Krtour-Service-Token`, 미설정 시
  비강제, 상수시간) route-level gate. 나머지 `/v1/features/*` GET은 공용 read.
- `/v1/features/*`(GET)·`/v1/categories`·`/v1/providers/*`: 공용 read, 앱 토큰 비강제(인프라 SSO).
- `/v1/admin/*`·`/v1/ops/*`·`/v1/debug/*`: 인프라 SSO + IP allowlist. 파괴적 admin은
  `admin_destructive_enabled` kill-switch.

### 1.4 응답 envelope (🔁 ADR-048 — payload/meta 완전 분리)
- 성공 `{ "data": <payload>, "meta": <Meta> }`. **`data`는 payload만**:
  단건=`<object>`, 목록=`{items:[…]}`, in-bounds=`{clusters:[…],items:[…]}`,
  batch=`{found:{feature_id:Feature},missing:[…]}`. list의 `items`는 항상 배열이고,
  id-keyed map은 `found`처럼 별도 키를 쓴다.
- **페이지네이션·추적·뷰 해석 메타는 `meta`로 일원화**:
  `meta = { duration_ms, request_id, page?: { page_size, next_cursor, total },
  cluster?: { cluster_unit } }`(`page`는 pageable 목록에만, `total`은 opt-in `null` 기본,
  `cluster`는 in-bounds에만). `data.next_cursor`/`data.total_count`/`data.cluster_unit`/
  파생 `count`는 **폐기**.
- 라우터별 `FeatureListMeta`/`FeatureDetailMeta`/… 중복 → 공유 `Meta` 1개 + `data` payload
  모델. 확장 시 `meta.page`만 늘리면 됨(payload 불변). 성공 응답에도 `request_id`(추적 대칭).

### 1.5 에러 — RFC 7807 `application/problem+json` (🔁 ADR-048 / T-214g)
```json
{ "type":"https://krtour-map/errors/feature-not-found", "title":"Feature not found",
  "status":404, "detail":"…", "code":"FEATURE_NOT_FOUND", "request_id":"01J…",
  "errors":[{"field":"feature_id","message":"…"}] }
```
- `Content-Type: application/problem+json` + `X-Request-ID`. 중앙 핸들러(`app.py`
  `_error_response`)가 통일. `code`·`request_id`는 **top-level 확장 멤버**(소비자 파싱 위치
  고정), 코드 enum(§4)을 확장 `code`로 유지.

### 1.6 페이지네이션 (🔁 ADR-048, T-214e 심화)
**실측 불일치**: page-size 파라미터 3종(`limit` features 평면/in-bounds/search ·
`page_size` 그 외 · `run_limit`/`event_limit` dagster), 캡 3종(`le=5000`/`500`/`200`),
`search`는 cursor인데 `limit`.
**표준**:
- `page_size`(정수)+opaque `cursor`(base64 keyset)로 통일. `limit`/`run_limit`/`event_limit`
  **폐기**. 응답은 `meta.page.next_cursor`(null=마지막, §1.4). page_size+1 fetch.
- 2-티어 캡: 기본(detail/admin/ops) 50/최대 200, 지도(`nearby`·`by-target`) 100/최대 500.
- `/v1/features` 평면: `page_size`+`cursor`(`limit le=5000` 폐기). `/v1/features/in-bounds`:
  cursor 없이 `max_items` 하드캡 5000→2000 + 결정적 `feature_id` 정렬(T-212d).
- `meta.page.total`은 `?include_total=true` opt-in(기본 `null`; 현재 `search`는 항상 COUNT).

### 1.7 idempotency · rate limit (T-214g)
- 변경 호출(admin mutation 등) POST: `Idempotency-Key` 허용. rate limit `429`+`RateLimit-*`+
  `Retry-After`, lock 경합 `409 LOCK_BUSY`+`Retry-After: 15`.

### 1.8 좌표 · datetime
- WGS84 lon,lat. bbox=`min_lon,min_lat,max_lon,max_lat`. 목록 좌표는 평면 `lon`/`lat`.
  datetime ISO 8601 KST-aware.

### 1.9 파라미터 규약 (🔁 ADR-048)
- **bbox 분리 float 4개로 통일**(`search`의 CSV `bbox` 제거 — clean cut).
- 다중값 필터는 단수 반복(`?kind=a&kind=b`/`category`/`provider`/`status`).
- lifecycle 상태 필드 `status`로 통일(`import-jobs`/`offline-uploads`/`feature-update-requests`
  의 `state` 개명; `severity` 별개 축). issue/violation noun은 외부 표면에서 `issue_*`.
- 범위 `min_*`/`max_*`, 시각 `*_from`/`*_to`, 정렬 `sort`(+`order`).

---

## 2. 엔드포인트 카탈로그 (목표 `/v1` 전 표면, #317 반영)

> 본 문서가 전 표면 계약 정본이다. `docs/tripmate-rest-api.md`는 TripMate 소비 매핑 view이며
> 계약 세부는 이 문서를 따른다.

### 2.1 Liveness (비버저닝)
```
GET /health        GET /version
```

### 2.2 `/v1/features/*` — 조회 (user+admin 공용)
```
GET /v1/features                        # 🔁 page_size+cursor (현재 limit-only)
GET /v1/features/search                 # q|bbox, page_size+cursor, meta.page.total opt-in
GET /v1/features/in-bounds              # clusters[](cluster_key=행정코드)/items[], max_items cap
GET /v1/features/nearby                 # 반경, page_size+cursor, distance_m
GET /v1/features/nearby/by-target       # 등록 POI cache target 주변
GET  /v1/features/{feature_id}          # 단건 상세
GET  /v1/features/{feature_id}/weather  # 날씨 카드(metric + forecast_style)
POST /v1/features/batch                 # 배치 조회 {feature_ids[]} cap≤200 → {found{},missing[]} (ServiceToken)
```
- ⚠️ `/tripmate/*` namespace **제거**(krtour-map은 TripMate 전용이 아니다). batch는
  `POST /v1/features/batch`(service read, ServiceToken)로 일반화, `/tripmate/
  feature-update-requests*`는 #317로 `/v1/admin/*`에 이미 이전(중복 C2 해소).

### 2.4 참조 데이터
```
GET /v1/categories                       GET /v1/providers/{provider}/last-sync
GET /v1/providers                        # 전 provider×dataset 신선도 목록 (T-217g, D-07)
```
- `GET /v1/providers`(T-217g): `provider_sync_state` 전량을 `data={items:[...]}`로 반환
  (provider/dataset_key/sync_scope/status/last_success_at/last_failure_at/
  consecutive_failures, 내부 cursor 비노출). provider×dataset 조합이 유한해
  `/v1/categories`처럼 비페이지네이션 bounded reference 패턴. 운영 신선도 대시보드
  (`admin UI /ops/providers`)와 TripMate Admin 상태판용. 빈 환경은 200 + 빈 `items`.

### 2.4.1 `/v1/public/*` — 공개 뷰 후보 (TripMate T-130, 아직 OpenAPI 미포함)

TripMate T-130(`/public/*`)이 요구하는 해수욕장/축제 공개 조회 뷰의 제안 사양은
[`docs/public-views-api.md`](public-views-api.md)를 따른다. 이 표면은 아직
`openapi.user.json`에 포함하지 않는다. 구현 시 사용자 profile에 추가하고
`@krtour/map-user-client` 타입을 재생성한다.

제안 엔드포인트:

```
GET /v1/public/beaches
GET /v1/public/beaches/map-markers
GET /v1/public/beaches/{feature_id}
GET /v1/public/festivals/monthly
GET /v1/public/festivals/map-markers
GET /v1/public/festivals/{feature_id}
```

핵심 결정 전제:

- 해수욕장 판별은 category 단일값이 아니라 `detail.place_kind='beach'`를 1차로 쓴다.
  현재 문서(`01050100`)와 provider 코드(`01020300`)의 category drift를 구현 task에서
  별도 정리한다.
- 수질/KHOA index는 `/v1/features/{feature_id}/weather` metric 확장 또는 별도 marine
  표면 중 하나로 확정한다.
- 축제 월별 뷰는 `EventDetail.starts_on`/`ends_on` 기간 겹침으로 집계한다.

### 2.4.2 `/v1/curated-features*` — 테마형 큐레이션 후보 (문서 계약, 아직 OpenAPI 미포함)

세계음식점, 독립서점, 카페가 있는 서점, 도서관, 무장애 관광지 같은 테마형 source는
[`docs/curated-features.md`](curated-features.md)의 `feature.curated_*` overlay 계약을
따른다. TripMate는 이 표면을 읽어 `app.curated_trip_plans` /
`app.curated_plan_pois`로 1:1 복사한다. TripMate의 `/notice-plans`는 호환 API alias일
뿐 신규 정본명이 아니다.

제안 엔드포인트:

```
GET /v1/curated-themes
GET /v1/curated-sources
GET /v1/curated-features
GET /v1/curated-features/{curated_feature_id}
GET /v1/curated-features/{curated_feature_id}/tripmate-copy
```

구현 시 사용자 profile에 추가하고 `openapi.user.json` 및 `@krtour/map-user-client` 타입을
재생성한다. write/admin 표면은 `/v1/admin/curated-*`로 둔다.

### 2.5 `/v1/admin/*` — 운영자 (인프라 SSO + kill-switch)
```
GET    /v1/admin/features                              # 목록(page_size+cursor)
GET    /v1/admin/features/{feature_id}                 # 상세
POST   /v1/admin/features                              # ✅#317 단건 생성(K-15)
PATCH  /v1/admin/features/{feature_id}                 # ✅#317 수정
DELETE /v1/admin/features/{feature_id}                 # ✅#317 soft delete
POST   /v1/admin/features/{feature_id}/deactivate      # 비활성(kill-switch)
POST   /v1/admin/features/change-requests/{request_id}/approve   # ✅#317
POST   /v1/admin/features/change-requests/{request_id}/reject    # ✅#317
GET    /v1/admin/features/change-requests              # 변경요청 큐(T-215b UI 대상)
GET/POST /v1/admin/feature-update-requests             # 재적재(admin 단일, tripmate alias 제거됨)
GET    /v1/admin/feature-update-requests/{request_id}
POST   /v1/admin/feature-update-requests/{request_id}/cancel
POST   /v1/admin/feature-update-requests/{request_id}/run-now    # kill-switch
GET/POST /v1/admin/offline-uploads  (+ {upload_id}[/preview|/validate|/validation|/load])
DELETE /v1/admin/offline-uploads/{upload_id}           # 🆕 정리 lifecycle
GET    /v1/admin/poi-cache-targets
GET/PUT/DELETE /v1/admin/poi-cache-targets/{external_system}/{target_key}  # 복합 자연키
# T-214f 결정: POI cache target write(PUT/DELETE)는 admin/operator flow 전용.
# TripMate 직접 write 미허용 — service-safe /v1/poi-cache-targets/* write 경로 안 둠.
# TripMate는 등록된 target 기준 read(GET /v1/features/nearby/by-target)만 소비.
GET/POST /v1/admin/backups   GET /v1/admin/backups/{backup_id}
DELETE /v1/admin/backups/{backup_id}                   # 🆕 정리 lifecycle
POST   /v1/admin/restore/{backup_id}[/swap]            # kill-switch
GET    /v1/admin/dedup-reviews   PATCH /v1/admin/dedup-reviews/{review_id}        # 🔁 복수+param
GET    /v1/admin/enrichment-reviews   PATCH /v1/admin/enrichment-reviews/{review_id} # 🔁
GET    /v1/admin/issues   GET/PATCH /v1/admin/issues/{issue_id}                  # 🔁 noun 일치
```
- **version 0/1 모델(#317)**: provider 적재=`data_origin='provider', data_version=0`,
  사용자 요청=`'user_request', data_version=1`, `feature.feature_versions` snapshot +
  `ops.feature_change_requests`. `KRTOUR_MAP_ADMIN_FEATURE_CHANGE_REVIEW_MODE=require_review|
  immediate`. provider 재적재는 version 1/ soft delete를 덮거나 되살리지 않는다.

### 2.6 `/v1/ops/*` — 옵저버빌리티
```
GET /v1/ops/health-deep · metrics · import-jobs[/{job_id}] · consistency/{reports,issues}
  · system-logs · api-call-logs · dagster/{summary,runs/{run_id}}   POST /v1/ops/dagster/nux-seen
```

### 2.7 `/v1/debug/*`
```
GET /v1/debug/etl/providers · etl/{provider}/datasets · mois-license/{license_id}
POST /v1/debug/etl/{provider}/{dataset}/preview
✅ /debug/health · /debug/version 제거됨(T-214h, clean cut). 상태확인은 /health·/version·
   /v1/ops/health-deep로 수렴. (나머지 debug 표면은 dev 전용, debug_routes_enabled로 gate.)
```
- **action sub-resource 규약(ADR-048 #8)**: 부수효과 상태전이는 `POST {col}/{id}/{verb}`
  (`deactivate`/`cancel`/`run-now`/`approve`/`reject`/`load`/`validate`/`swap`), 순수 수정은
  `PATCH {id}`, 생성 `POST {col}`, 조회 `GET`. 신규 action도 같은 형태로 확장.

---

## 3. 데이터 계약 핵심

| 항목 | 정본 | 비고 |
|------|------|------|
| feature_id | `f_{bjd\|global}_{kind[0]}_{sha1[:16]}` 문자열 | UUID 아님. **값 불변식**(아래) |
| 표시명 | `name`(not `title`) | |
| 좌표(목록) | 평면 `lon`/`lat`(cross-repo 정본, ADR-048 #10) | TripMate DEC-07도 `lon`/`lat`로 정렬 |
| 주소 | 구조화 `address`+`*_code` | |
| category | 8자리 코드 + `/v1/categories` label | |
| 날씨 | metric 목록 + `forecast_style` | |
| envelope | `{data,meta}`, 목록 `data={items}` + `meta.page{page_size,next_cursor,total}`, batch `data={found,missing}` | §1.4 |

### 3.1 응답 필드 명명 규약 (🔁 ADR-048 — 의미/본질 기준 전면 적용)
- **식별자(외부 read 포함)**: 시스템 단일 surrogate = `*_id`, **복합/자연키 = `*_key`**.
  응답 본문 전체에 적용 — surrogate `review_id`→`review_id`, `issue_id`→`issue_id`,
  ops 로그/내부 키 `*_key`→`*_id`. **`*_key` 유지(본질이 자연/복합키)**: `cluster_key`
  (**행정구역 코드 sido/sigungu/eupmyeondong = 자연키 → 유지**; 2차의 `cluster_id` 개명 철회,
  #316 재리뷰 C), 복합 자연키 `target_key`(+`external_system`), provider/source 어휘
  (`dataset_key` 등 ADR-044), canonical `feature_id`. 호환 동기의 "동결" 버킷은 두지 않고
  본질로 분류한다.
- **상태**: `status`로 통일(`state` 개명). `severity` 별개 축.
- **timestamp**: `*_at`(ISO 8601 KST). 목록 길이용 `count`는 폐기(=`len(items)`), 전체 수는
  `meta.page.total`(opt-in).

### 3.2 `feature_id` 값 불변식 (안정성, ADR-048 #11)
외부 `feature_id` **값**은 provider 재적재·사용자 편집(#317 v0/v1)·버전 승급·soft delete에도
**바뀌지 않는다**. 정체성이 바뀌는 사건(bjd 변경 등)은 id 변경이 아니라 **새 feature + link**로
모델링한다. 소비자(TripMate)가 FK·snapshot 키로 영속화하므로 값 안정성을 계약으로 보장.

### 3.3 envelope 불변식 (안정성, ADR-048 #12)
- `meta`는 **모든 응답에 항상 present**(단건 GET 포함). 성공 `meta`/에러 problem+json 모두
  `request_id`를 싣는다.
- `meta.page.next_cursor`는 **항상 키로 존재**, 소진 시 `null`(omit 금지) — 페이지 종료 신호.
- in-bounds의 `cluster_unit`처럼 payload 해석에 필요한 view metadata는 `data`가 아니라
  `meta.cluster`에 둔다. `data`는 `items`/`clusters` 같은 실제 payload만 담는다.

---

## 4. 표준 에러 코드
`FEATURE_NOT_FOUND`(404) · `INVALID_BBOX`(422) · `TOO_MANY_IDS`(422) · `VALIDATION_ERROR`(422)
· `RATE_LIMITED`(429) · `LOCK_BUSY`(409,`Retry-After:15`) · `DESTRUCTIVE_DISABLED`(403) ·
`UNAUTHORIZED`(401) · `UPSTREAM_UNAVAILABLE`(503).

### 4.1 표준 헤더 규약 (T-214g)
| 헤더 | 방향 | 의미 | 상태 |
|------|------|------|------|
| `X-Request-ID` | 응답(전체) | 요청 상관추적. `meta.request_id`/problem+json `request_id`와 동일 | **구현됨** |
| `Retry-After` | 응답(429/409) | `RATE_LIMITED`/`LOCK_BUSY` 재시도 지연(초). LOCK_BUSY=15 | **구현됨**(LOCK_BUSY) |
| `Idempotency-Key` | 요청(변경 POST) | 동일 key 재시도 = 동일 결과 | 규약(구현 T-216) |
| `RateLimit-Limit`/`RateLimit-Remaining`/`RateLimit-Reset` | 응답(429) | rate limit 상태 | 규약(구현 T-216) |
| `Deprecation`/`Sunset` | 응답 | GA 후 `/v1`→`/v2` 전환 예고(ADR-048 #13). pre-1.0 clean cut에선 미사용 | 규약(GA 후) |

에러 본문은 RFC 7807 `application/problem+json`(§1.5), 머신 코드는 위 enum을 확장 `code`로.

---

## 5. 현재 → 목표 매핑 (ADR-048 delta; #317 항목은 ✅)
| 현재 | 목표 | 종류 |
|------|------|------|
| `/admin/*`·`/ops/*`·`/debug/*` 비버저닝 | `/v1/…`(clean cut, alias 없음) | 🔁 ADR-048 |
| 라우터별 `*Meta`, `data.next_cursor`/`count` | 공유 `Meta` + `meta.page{page_size,next_cursor,total}` | 🔁 envelope |
| page-size `limit`/`run_limit`/`event_limit` | `page_size`(2-티어 캡) | 🔁 |
| `limit le=5000`(features), in-bounds | `page_size`+`cursor` / `max_items` 2000 | 🔁 |
| `search` 항상 COUNT | `meta.page.total` opt-in | 🔁 |
| `search` bbox CSV | 분리 float | 🔁 |
| in-bounds `data.cluster_unit` | `meta.cluster.cluster_unit` | 🔁 |
| batch `data.items` id-keyed map | `data.found` id-keyed map + `data.missing[]` | 🔁 |
| `state`(jobs/uploads/requests) | `status` | 🔁 |
| 응답 surrogate `*_key`(review/violation/log…) | `*_id` (`cluster_key` 등 자연키는 유지) | 🔁 |
| 좌표 `lon`/`lat` ↔ TripMate `longitude`/`latitude` | `lon`/`lat`로 cross-repo 정렬 | 🔁 #10 |
| `{issue_id}`/`{review_id}` | `{issue_id}`/`{review_id}`, `*-reviews` 복수 | 🔁 |
| `{error:{…}}` | problem+json(`code`/`request_id` 확장) | 🔁 |
| `/debug/health`·`/debug/version` | 제거(clean cut) | 🔁 |
| 2개 계약 doc | `rest-api.md` 단일 정본 + tripmate-rest-api.md 소비 view | 🔁 수렴(T-216g) |
| `/tripmate/feature-update-requests*` | `/admin/*` | ✅#317 |
| `POST /tripmate/features/batch` | `POST /features/batch`(ServiceToken) | ✅ `/tripmate` namespace 제거 |
| `POST /admin/features` 등 add/edit/delete | (구현됨) | ✅#317 K-15 |

---

## 6. 미해결 / 결정 로그
- **K-15(단건 add API)**: #317로 `POST /admin/features` 구현 → 해소. TripMate T-179 의존 풀림.
- **DEC-05**: 재적재(admin)와 사용자 제안(TripMate→승인→`/admin/features`) 분리(확정).
- **정본 수렴(T-216g)**: 본 문서를 전 표면 단일 계약 정본으로, `docs/tripmate-rest-api.md`는
  소비 매핑 view로 축소(ADR-048 #9, drift 회피).
- **Batch 응답 키**: `items`는 list array 전용으로 고정하고, batch id-keyed map은 `found`로
  둔다(TripMate 3차 리뷰 반영).
- **codegen(T-210e)**: `/v1` 안정 commit에서 진행.
- **TripMate T-130 공개 뷰**: 해수욕장/축제 공개 뷰 후보 사양을
  `docs/public-views-api.md`에 추가했다. 구현 전까지 `openapi.user.json`에는 포함하지 않는다.
- **curated_features**: 테마형 큐레이션 후보 사양을
  `docs/curated-features.md`에 추가했다. 구현 전까지 `openapi.user.json`에는 포함하지 않는다.

---

## 7. 코드/DB 레벨 명명 전파 (내부 어휘 정렬, ADR-048 #7)
REST 단 명명 통일(`*_key`→`*_id`, `state`→`status`)을 **내부 소유 식별자/상태는 물리 컬럼·
ORM·repo까지 end-to-end 정렬**(ADR-046 무-shim), provider/복합키는 경계 보존(ADR-044).

| 식별자/필드 | 출처 | 전파 | 목표 | blast |
|---|---|---|---|---|
| `review_id` | 내부 ops | ✅ | `review_id` | 291 |
| `issue_id` | 내부 ops | ✅ | `issue_id` | 118 |
| `coord_key`/`system_log_id`/`api_call_log_id`/`override_id`/`step_id` | 내부 | ✅ | `*_id` | 28/28/26/13/5 |
| `state`(import_jobs/offline_uploads/feature_update_requests) | 내부 | ✅ | `status` | 3 테이블 |
| `dataset_key`/`source_record_key`/`source_entity_id` | provider/source(ADR-044) | ❌ | 유지 | 859/398/234 |
| `cluster_key` | 행정구역 코드 = 자연키 | ❌ | 유지(규칙상 `*_key`) | — |
| `target_key`(+`external_system`) | 복합 자연키(근거 있음) | ❌ | 유지 | 130 |
| `feature_id` | canonical | ❌ | 불변 | — |

전략: edge projection(`AS …`) / ORM attr 개명 / **물리 컬럼 개명(migration)** 중, 내부 소유는
물리 개명을 **테이블별 1-PR**(migration+ORM+repo raw SQL+테스트+OpenAPI/frontend regen,
codegraph impact 선행). raw `text()` SQL이 물리명을 써서 ORM attr만으로는 부분 정렬.

---

## 8. 변경 이력
- 2026-06-09: #317(T-214/T-215) `/v1` 1차 정리 위에 ADR-048(admin/ops versioning 확장 +
  envelope/pagination/parameter/response 정합성 표준 + 코드/DB 명명 전파)을 반영.
- 2026-06-09(2차, #316 무-호환 재검토): 외부 read 동결 carve-out 제거, envelope
  페이지네이션을 `meta.page`로 분리(`data`=payload만, `count` 폐기), dual-support 제거 →
  `/v1` clean cut + `/debug/health|version` 제거, action sub-resource 규약, 단일 정본 수렴.
- 2026-06-09(3차, #316 TripMate 재리뷰 A–F 반영): (B) 좌표명 cross-repo 정렬 = `lon`/`lat`
  (ADR-048 #10), (C) **`cluster_key`는 행정코드 자연키라 유지**(2차 `cluster_id` 철회),
  (D) `feature_id` **값 불변식** 명문화(§3.2), (E) envelope 불변식 lock(§3.3 — `meta` 항상
  present·`request_id`·`next_cursor` null-not-omit), (F) `/vN` major 거버넌스(§1.2, #13).
  실행 T-216a~g.
- 2026-06-09(4차, #316 TripMate 3차 잔여 반영): batch id-keyed map은 `items`가 아니라
  `found`로 분리하고, in-bounds `cluster_unit`은 payload에서 `meta.cluster.cluster_unit`로 이동.
  base URL은 host root만 포함하고 path가 `/v1`를 명시한다고 고정.
