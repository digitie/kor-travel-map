# krtour-map REST API — 전 표면 카탈로그 + 정합성 표준

> **상태**: 2026-06-09. PR #317(T-214/T-215)의 `/v1` 1차 정리 위에 ADR-048(admin/ops
> versioning 확장 + envelope/pagination/parameter/response 정합성 표준 + 코드/DB 명명 전파)을
> 얹은 기준선.
> **범위**: krtour-map **전 표면**(user/TripMate + admin + ops + debug). **외부(TripMate)
> `/v1` 계약의 정본은 `docs/tripmate-rest-api.md`(#317)** — 본 문서는 거기에 admin/ops를
> 포함한 전 표면 카탈로그와 cross-cutting 정합성 표준을 더한다(외부 필드 세부는
> tripmate-rest-api.md 우선).
> **정본 우선순위**: 기계 정본 = `packages/krtour-map-admin/openapi.json`(admin/full)·
> `openapi.user.json`(user). 충돌 시 **OpenAPI 우선**. 결정 = ADR-048.
> **표기**: 🆕 신규 · 🔁 변경 · ⚠️ deprecate · ✅#317 = #317로 이미 구현.

---

## 0. 한눈에 — #317이 한 것 vs ADR-048 delta

| 영역 | #317(T-214/T-215) | ADR-048 보강 |
|------|-------------------|-------------|
| versioning | 외부(`/features`·`/tripmate`·`/categories`·`/providers`) `/v1`, **admin/ops 비버저닝** | **admin/ops/debug도 `/v1`**(사용자 지시, T-214b §2.1 supersede) |
| 인증 | `ServiceToken`(#314), 공용 read 비강제 | 유지 |
| feature-update-request | `/tripmate/*` alias 제거 → `/admin/*` 단일 ✅ | 유지(중복 C2 해소됨) |
| 단건 feature add/edit/delete | `/admin/features` POST/PATCH/DELETE + change-requests ✅(K-15) | 유지 |
| envelope | `{data,meta}`(라우터별 `*Meta`) | 공유 `Meta{duration_ms,request_id}`+`ListData[T]`, 성공 meta `request_id` |
| pagination | cursor/page_size(고수준) | `page_size` 단일·2-티어 캡·`total_count` opt-in·`/features` cursor |
| parameter | bbox 분리 float 권고 | bbox 통일·`state`→`status`·issue noun·다중 반복 |
| error | header 규약(T-214g) | RFC7807 `application/problem+json` body |
| 응답 식별자 | — | `*_id`(단일)/`*_key`(복합), `*_key`→`*_id` |
| 코드/DB 명명 | — | 내부 소유 end-to-end 정렬(테이블별 migration) |

---

## 1. 공통 규약 (전 엔드포인트)

### 1.1 Base URL · 포트 (ADR-047)
- API `http://127.0.0.1:9011`(admin UI `9012`, Dagster `9013`, Postgres host `15433`,
  RustFS `9003`/`9004`). `TRIPMATE_KRTOUR_MAP_API_BASE_URL`은 `/v1`까지 포함.

### 1.2 Versioning (ADR-048 — #317 확장)
- **전 표면 `/v1`**: `/v1/features/*`·`/v1/tripmate/*`·`/v1/categories`·`/v1/providers/*`
  **+ `/v1/admin/*`·`/v1/ops/*`·`/v1/debug/*`**(ADR-048이 #317의 admin 비버저닝을 supersede).
- **비버저닝 고정**: `/health`·`/version`. breaking은 `/v1`→`/v2`. deprecate 시
  `Deprecation`/`Sunset` 헤더, 경로별 shim 금지(ADR-046) — mount 1곳 전환.

### 1.3 인증 (ADR-005 / ADR-045 D-1, #314)
- `/v1/tripmate/*`: `ServiceToken`(`X-Krtour-Service-Token`, 미설정 시 비강제, 상수시간).
- `/v1/features/*`·`/v1/categories`·`/v1/providers/*`: 공용 read, 앱 토큰 비강제(인프라 SSO).
- `/v1/admin/*`·`/v1/ops/*`·`/v1/debug/*`: 인프라 SSO + IP allowlist. 파괴적 admin은
  `admin_destructive_enabled` kill-switch.

### 1.4 응답 envelope (🔁 ADR-048)
- 성공 `{ "data": <payload>, "meta": <Meta> }`. 단건 `data=<object>`, 목록
  `data={items[],next_cursor,total_count}`(in-bounds는 `{clusters[],items[],cluster_unit,count}`).
- **공유 모델 통일**: 라우터별 `FeatureListMeta`/`FeatureDetailMeta`/… 중복 → 공유
  `Meta{duration_ms, request_id}` + 제네릭 `ListData[T]{items,next_cursor,total_count}`.
  **성공 응답 meta에도 `request_id`**(오류 envelope와 추적 대칭).

### 1.5 에러 — RFC 7807 `application/problem+json` (🔁 ADR-048 / T-214g)
```json
{ "type":"https://krtour-map/errors/feature-not-found", "title":"Feature not found",
  "status":404, "detail":"…", "code":"FEATURE_NOT_FOUND", "request_id":"01J…",
  "errors":[{"field":"feature_id","message":"…"}] }
```
- `Content-Type: application/problem+json` + `X-Request-ID`. 중앙 핸들러(`app.py`
  `_error_response`)가 통일.

### 1.6 페이지네이션 (🔁 ADR-048, T-214e 심화)
**실측 불일치**: page-size 파라미터 3종(`limit` features 평면/in-bounds/search ·
`page_size` 그 외 · `run_limit`/`event_limit` dagster), 캡 3종(`le=5000`/`500`/`200`),
`search`는 cursor인데 `limit`.
**표준**:
- `page_size`(정수)+opaque `cursor`(base64 keyset)로 통일. `limit`/`run_limit`/`event_limit`
  deprecate. 응답 `data.next_cursor`(null=마지막). page_size+1 fetch.
- 2-티어 캡: 기본(detail/admin/ops) 50/최대 200, 지도(`nearby`·`by-target`) 100/최대 500.
- `/v1/features` 평면: `page_size`+`cursor`(`limit le=5000` 폐기). `/v1/features/in-bounds`:
  cursor 없이 `max_items` 하드캡 5000→2000 + 결정적 `feature_id` 정렬(T-212d).
- `total_count`는 `?include_total=true` opt-in(기본 `null`; 현재 `search`는 항상 COUNT).

### 1.7 idempotency · rate limit (T-214g)
- `/v1/tripmate/*` POST: `Idempotency-Key` 허용. rate limit `429`+`RateLimit-*`+`Retry-After`,
  lock 경합 `409 LOCK_BUSY`+`Retry-After: 15`.

### 1.8 좌표 · datetime
- WGS84 lon,lat. bbox=`min_lon,min_lat,max_lon,max_lat`. 목록 좌표는 평면 `lon`/`lat`.
  datetime ISO 8601 KST-aware.

### 1.9 파라미터 규약 (🔁 ADR-048)
- **bbox 분리 float 4개로 통일**(`search`의 CSV `bbox` deprecate).
- 다중값 필터는 단수 반복(`?kind=a&kind=b`/`category`/`provider`/`status`).
- lifecycle 상태 필드 `status`로 통일(`import-jobs`/`offline-uploads`/`feature-update-requests`
  의 `state` 개명; `severity` 별개 축). issue/violation noun은 외부 표면에서 `issue_*`.
- 범위 `min_*`/`max_*`, 시각 `*_from`/`*_to`, 정렬 `sort`(+`order`).

---

## 2. 엔드포인트 카탈로그 (목표 `/v1` 전 표면, #317 반영)

> 외부 표면 필드 세부는 `docs/tripmate-rest-api.md` §3·§4 정본 우선.

### 2.1 Liveness (비버저닝)
```
GET /health        GET /version
```

### 2.2 `/v1/features/*` — 조회 (user+admin 공용)
```
GET /v1/features                        # 🔁 page_size+cursor (현재 limit-only)
GET /v1/features/search                 # q|bbox, page_size+cursor, total_count opt-in
GET /v1/features/in-bounds              # clusters[]/items[], max_items cap
GET /v1/features/nearby                 # 반경, page_size+cursor, distance_m
GET /v1/features/nearby/by-target       # 등록 POI cache target 주변
GET /v1/features/{feature_id}           # 단건 상세
GET /v1/features/{feature_id}/weather   # 날씨 카드(metric + forecast_style)
```

### 2.3 `/v1/tripmate/*` — 외부 service-to-service (ServiceToken)
```
POST /v1/tripmate/features/batch        # 배치 조회 {feature_ids[]} cap≤200 → {items{},missing[]}
```
- ⚠️ `/tripmate/feature-update-requests*`는 **#317로 제거**(→ `/v1/admin/*`). 중복 C2 해소.
  batch 경로의 `/v1/features/batch` 이동은 #317 T-214d 진행 중.

### 2.4 참조 데이터
```
GET /v1/categories                       GET /v1/providers/{provider}/last-sync
```

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
⚠️ /v1/debug/health · /v1/debug/version → /health·/version로 수렴(deprecate, T-214h)
```

---

## 3. 데이터 계약 핵심

| 항목 | 정본 | 비고 |
|------|------|------|
| feature_id | `f_{bjd\|global}_{kind[0]}_{sha1[:16]}` 문자열 | UUID 아님 |
| 표시명 | `name`(not `title`) | |
| 좌표(목록) | 평면 `lon`/`lat` | |
| 주소 | 구조화 `address`+`*_code` | |
| category | 8자리 코드 + `/v1/categories` label | |
| 날씨 | metric 목록 + `forecast_style` | |
| envelope | `{data,meta}` / `{data:{items,next_cursor,total_count}}` | §1.4 |

### 3.1 응답 필드 명명 규약 (🔁 ADR-048)
- **식별자**: 시스템 단일 `*_id`(feature_id/request_id/upload_id/backup_id/job_id/run_id/
  report_id/신규 review_id/issue_id), 복합/자연키만 `*_key`(`target_key`+`external_system`,
  `dataset_key`, provider/source 어휘 ADR-044). 응답 UUID `*_key`→`*_id`(T-216f).
- **상태**: `status`로 통일(`state` 개명). `severity` 별개 축.
- **timestamp**: `*_at`(ISO 8601 KST). `count`(페이지 길이)/`total_count`(전체, opt-in) 분리.

---

## 4. 표준 에러 코드
`FEATURE_NOT_FOUND`(404) · `INVALID_BBOX`(422) · `TOO_MANY_IDS`(422) · `VALIDATION_ERROR`(422)
· `RATE_LIMITED`(429) · `LOCK_BUSY`(409,`Retry-After:15`) · `DESTRUCTIVE_DISABLED`(403) ·
`UNAUTHORIZED`(401) · `UPSTREAM_UNAVAILABLE`(503).

---

## 5. 현재 → 목표 매핑 (ADR-048 delta; #317 항목은 ✅)
| 현재 | 목표 | 종류 |
|------|------|------|
| `/admin/*`·`/ops/*`·`/debug/*` 비버저닝 | `/v1/…` | 🔁 ADR-048(admin versioning) |
| 라우터별 `*Meta` | 공유 `Meta`+`ListData` | 🔁 envelope |
| page-size `limit`/`run_limit`/`event_limit` | `page_size`(2-티어 캡) | 🔁 |
| `limit le=5000`(features), in-bounds | `page_size`+`cursor` / `max_items` 2000 | 🔁 |
| `search` 항상 COUNT | `total_count` opt-in | 🔁 |
| `search` bbox CSV | 분리 float | 🔁 |
| `state`(jobs/uploads/requests) | `status` | 🔁 |
| 응답 `*_key`(UUID 단일) | `*_id` | 🔁 |
| `{violation_key}`/`{review_key}` | `{issue_id}`/`{review_id}`, `*-reviews` 복수 | 🔁 |
| `{error:{…}}` | problem+json | 🔁 |
| `/tripmate/feature-update-requests*` | `/admin/*` | ✅#317 |
| `POST /admin/features` 등 add/edit/delete | (구현됨) | ✅#317 K-15 |

---

## 6. 미해결 / 결정 로그
- **K-15(단건 add API)**: #317로 `POST /admin/features` 구현 → 해소. TripMate T-179 의존 풀림.
- **DEC-05**: 재적재(admin)와 사용자 제안(TripMate→승인→`/admin/features`) 분리(확정).
- **codegen(T-210e)**: `/v1` 안정 commit에서 진행.

---

## 7. 코드/DB 레벨 명명 전파 (내부 어휘 정렬, ADR-048 #7)
REST 단 명명 통일(`*_key`→`*_id`, `state`→`status`)을 **내부 소유 식별자/상태는 물리 컬럼·
ORM·repo까지 end-to-end 정렬**(ADR-046 무-shim), provider/복합키는 경계 보존(ADR-044).

| 식별자/필드 | 출처 | 전파 | 목표 | blast |
|---|---|---|---|---|
| `review_key` | 내부 ops | ✅ | `review_id` | 291 |
| `violation_key` | 내부 ops | ✅ | `issue_id` | 118 |
| `coord_key`/`system_log_key`/`api_call_log_key`/`override_key`/`step_key` | 내부 | ✅ | `*_id` | 28/28/26/13/5 |
| `state`(import_jobs/offline_uploads/feature_update_requests) | 내부 | ✅ | `status` | 3 테이블 |
| `dataset_key`/`source_record_key`/`source_entity_id` | provider/source(ADR-044) | ❌ | 유지 | 859/398/234 |
| `target_key`(+`external_system`) | 복합 자연키 | ❌ | 유지 | 130 |
| `feature_id` | canonical | ❌ | 불변 | — |

전략: edge projection(`AS …`) / ORM attr 개명 / **물리 컬럼 개명(migration)** 중, 내부 소유는
물리 개명을 **테이블별 1-PR**(migration+ORM+repo raw SQL+테스트+OpenAPI/frontend regen,
codegraph impact 선행). raw `text()` SQL이 물리명을 써서 ORM attr만으로는 부분 정렬.

---

## 8. 변경 이력
- 2026-06-09: #317(T-214/T-215) `/v1` 1차 정리 위에 ADR-048(admin/ops versioning 확장 +
  envelope/pagination/parameter/response 정합성 표준 + 코드/DB 명명 전파)을 반영. 실행은
  `docs/tasks.md` Phase 6.8 / T-216a~f.
