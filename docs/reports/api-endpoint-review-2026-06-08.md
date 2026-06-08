# krtour-map REST API 엔드포인트 검토 (2026-06-08)

> 목적: krtour-map가 노출하는 REST 엔드포인트를 **정합성·일관성·누락·중복·versioning**과
> 일반 REST best practice 기준으로 점검한다. TripMate 소비 측을 확인해 필요 기능 충족 여부도
> 본다. **본 문서는 검토 결과만 기록한다(코드 수정 없음).**
>
> 점검 대상 = `packages/krtour-map-admin/openapi.json`(admin/full, **55 paths**) +
> `openapi.user.json`(user/TripMate, **13 paths**). 두 spec 모두 `info.version = 0.2.0-dev`.
> 소비 측 = `tripmate/apps/api/app/etl_bridge/krtour_map.py`(`KrtourMapClient` Protocol).

> **후속 결정(2026-06-08)**: 본 리포트는 당시 spec 기준으로
> `/tripmate/feature-update-requests*`를 TripMate 외부 계약으로 분류했지만, 이후 사용자
> 결정으로 feature update request는 **admin 영역으로 이동**한다. 정본 정리 문서는
> `docs/tripmate-rest-api.md`이며, 목표 경로는 `/admin/feature-update-requests*`다.
> TripMate 사용자 제안 큐는 TripMate app DB가 소유한다.

---

## 1. 엔드포인트 인벤토리 (namespace별)

| namespace | 대표 경로 | 비고 |
|-----------|-----------|------|
| `/features/*` | `/features`, `/features/search`, `/features/in-bounds`, `/features/nearby`, `/features/nearby/by-target`, `/features/{feature_id}`, `/features/{feature_id}/weather` | TripMate + admin 공용(조회) |
| `/tripmate/*` | `POST /tripmate/feature-update-requests`, `GET /tripmate/feature-update-requests/{request_id}`, `POST /tripmate/features/batch` | TripMate 전용 외부 계약 |
| `/categories`, `/providers/{provider}/last-sync` | 참조 데이터 | user profile 포함 |
| `/admin/*` | `features`, `issues`, `dedup-review`, `enrichment-review`, `feature-update-requests`, `offline-uploads`, `poi-cache-targets`, `backups`, `restore` | 운영자 전용 |
| `/ops/*` | `metrics`, `health-deep`, `import-jobs`, `consistency/{issues,reports}`, `system-logs`, `api-call-logs`, `dagster/*` | 옵저버빌리티 |
| `/debug/*` | `health`, `version`, `etl/*`, `mois-license/{license_id}` | 개발자용 |
| 최상위 | `/health`, `/version` | public |

전체 경로 표는 §6 부록 참조.

## 2. TripMate 소비 surface 확인 (필요 기능)

`KrtourMapClient` Protocol(7개 메서드) ↔ user-profile 엔드포인트 매핑:

| TripMate 클라이언트 메서드 | krtour-map 엔드포인트 | 충족 |
|---|---|---|
| `features_in_bounds(bbox,kinds,zoom,limit)` | `GET /features/in-bounds` | ✅ |
| `features_nearby(lng,lat,radius_m,kinds,limit)` | `GET /features/nearby` | ✅ |
| `get_feature(feature_id)` | `GET /features/{feature_id}` | ✅ |
| `features_by_ids(feature_ids)` | `POST /tripmate/features/batch` | ✅ |
| `build_weather_card(feature_id,asof)` | `GET /features/{feature_id}/weather` | ✅ |
| `search(q,kinds,bbox,limit)` | `GET /features/search` | ✅ |
| `request_feature(user_id,kind,title,coord,note)` | `POST /tripmate/feature-update-requests` | ✅(스키마 정합 확인 필요, §4-C2) |

**결론: 기능 누락 없음.** user profile 13개 경로가 TripMate가 호출하는 모든 메서드를 덮는다.
다만 `etl_bridge/krtour_map.py`는 **라이브러리 import 모델(ADR-003/005)** 기준 Protocol이고, ADR-045
(HTTP/OpenAPI 연동)로 이행하면 HTTP 클라이언트로 교체돼야 한다. 그 시점에 §4-C2(스키마 정합)와
§4-A(versioning)가 실제 영향이 된다.

## 3. 잘 지켜진 점 (best practice 준수)

- **응답 envelope 100% 일관**: 2xx 응답 61건 전부 `*Response`(=`{data, meta}`) 래핑. bare list/object 응답 0건.
  오류도 `{error:{message,...}}` 통일.
- **cursor 페이지네이션 대부분 일관**: 목록 GET 다수가 `cursor`(15) + `page_size`(14)로 keyset 페이지네이션.
- **profile 분리**: `export_openapi.py --profile {admin,user}`로 외부(TripMate) 노출면을 명시 분리 + drift CI gate(`openapi-drift`).
- **명확한 namespace 규약(ADR-035)**: `/debug` / `/admin` / `/ops` / `/features` 구분.
- **조회/변경 동사 사용 적절**: 대부분 컬렉션 GET, 생성 POST, 부분수정 PATCH.

## 4. 발견 사항 (심각도순)

### A. Versioning 부재 — **[P1]**
- 모든 경로가 **버전 prefix 없음**(`/v1/...` 없음, media-type 버저닝 없음). `info.version`은
  `0.2.0-dev`지만 URL/contract에는 반영되지 않는다.
- ADR-045상 **TripMate가 HTTP로 cross-service 소비**하는 계약인데, breaking change 시 버전 분리
  수단이 없어 소비자가 조용히 깨질 수 있다.
- **대조**: 소비자 TripMate는 자기 API를 `/api/v1/...`로 **버저닝**한다(`apps/api/app/api/v1/`).
  제공자(krtour-map)가 버저닝을 안 하는 비대칭.
- 권고: 외부 노출면(user profile + `/tripmate/*` + `/features/*`)에 최소 `/v1` URL prefix 또는
  명시적 backward-compat 정책 + deprecation 헤더 전략 도입. 내부 `/admin`·`/ops`·`/debug`는 면제 가능.

### B. 인증/인가 스킴 미선언 — **[P1]**
- OpenAPI에 `components.securitySchemes` **전무**, 글로벌/엔드포인트 `security` **0건**.
- `/admin/*`의 **변경 엔드포인트**(`POST /admin/features/{id}/deactivate`,
  `DELETE /admin/poi-cache-targets/...`, `POST /admin/feature-update-requests/{id}/run-now`,
  `POST /admin/restore/{backup_id}` 등 파괴적 작업 포함)와 외부 `/tripmate/*` 변경 엔드포인트가
  계약상 무인증으로 보인다.
- 네트워크/게이트웨이 레벨에서 보호하더라도 **계약(OpenAPI)에 보안 스킴이 문서화되지 않은 것**은
  best practice 위반(소비자가 인증 방식을 알 수 없음).
- 권고: 최소한 `/admin`·`/tripmate` 변경 계열에 securityScheme(예: bearer/mTLS/API key)를 선언하고
  엔드포인트별 `security`를 표기. (실제 인증 구현 여부와 별개로 contract 명세 필요.)

### C. 중복 — **[P2]**
- **C1. health/version 중복**: health 3종(`/health`, `/debug/health`, `/ops/health-deep`),
  version 2종(`/version`, `/debug/version`). public/dev/deep 의도는 이해되나 명명/계층이 중복·혼란.
  → `/health`(liveness) + `/ops/health-deep`(readiness) 2종으로 수렴하고 `/debug/health`·`/debug/version`은
  deprecate, version은 `/version` 단일화 권고.
- **C2. admin vs tripmate feature-update-requests 동일 계약**:
  `POST /admin/feature-update-requests`와 `POST /tripmate/feature-update-requests`가 **같은 요청
  스키마**(`FeatureUpdateRequestCreateRequest`)를 쓰고, `GET .../{request_id}`도 쌍으로 중복.
  prefix/tag만 다른 사실상 동일 생성 계약. (admin에는 `cancel`/`run-now` 추가 액션이 있어 tripmate가
  부분집합.) → 의도(외부 caller vs 운영자 scope 분리)는 타당하나, **동일 스키마 중복**은 표면을
  하나로 두고 인증·scope로 구분하거나, 최소한 두 경로가 동일 핸들러/검증을 공유함을 문서화 권고.

### D. 일관성 — **[P2]**
- **D1. 페이지네이션 혼용**: 관리 목록은 `cursor`+`page_size`(keyset)인데
  `GET /features`·`GET /features/in-bounds`는 **`limit`만**(cursor 없음) 사용. 사용자 목록면이
  cursor 미지원 → 일관성·확장성 저하(§E1과 연결).
- **D2. 단수/복수 혼용**: 컬렉션은 대부분 복수(`/features`, `/categories`, `/admin/issues`)인데
  `/admin/dedup-review`, `/admin/enrichment-review`는 **단수**(리소스 컬렉션인데 단수형). →
  `dedup-reviews`/`enrichment-reviews` 권고(이미 배포돼 호환성 고려 필요).
- **D3. path 파라미터 명명 혼용**: `{feature_id}`/`{request_id}`/`{backup_id}`/`{upload_id}`/`{job_id}`/
  `{run_id}`/`{license_id}`(=`_id`) vs `{review_key}`/`{violation_key}`/`{target_key}`(=`_key`) 혼재.
  특히 컬렉션 `/admin/issues`인데 파라미터는 `{violation_key}`(noun 불일치: issue vs violation).
- **D4. action-style 서브리소스 다수**: `POST .../deactivate`, `.../cancel`, `.../run-now`,
  `.../load`, `.../validate`, `.../swap`, `POST /ops/dagster/nux-seen`. RPC 스타일이라 자체로 위반은
  아니나(허용 패턴), 일부는 RESTful 대안(예: deactivate→`PATCH`로 status 전이) 가능. 일관 규약(언제
  action sub-resource를 쓰는지) 문서화 권고.

### E. 누락 — **[P3]**
- **E1. `/features` flat 목록 cursor 미지원**: `limit` 캡만 있고 다음 페이지 수단 없음. bbox 한정인
  `in-bounds`/`nearby`는 수용 가능하나, 전역 `/features`는 keyset 페이지네이션 부재가 확장 누락.
- **E2. 리소스 lifecycle 비대칭**: `offline-uploads`·`backups`는 생성/조회는 있으나 **DELETE(정리)**
  계약 부재. `feature-update-requests`도 `cancel`만 있고 표준 DELETE 없음(설계 선택일 수 있음 —
  의도면 문서화).
- **E3. 표준 오류 형식 미채택**: 오류 envelope가 자체 `{error:{message}}`. RFC 7807
  `application/problem+json` 미사용 — 외부 소비(TripMate) 관점에서 표준 오류 스키마/`type`/`code`
  부재. (현행 envelope가 일관적이라 critical은 아님.)
- **E4. rate limit/idempotency 계약 부재**: 외부 `/tripmate/*` 변경 호출에 idempotency key
  헤더나 rate-limit 응답 헤더 규약이 contract에 없음(전국 단위 요청·재시도 안전성 관점).

## 5. 권고 우선순위 요약

| # | 항목 | 심각도 | 권고 |
|---|------|--------|------|
| 1 | API versioning 도입 | P1 | 외부 노출면에 `/v1` 또는 명시 호환 정책. 소비자 TripMate(`/api/v1`)와 정합. |
| 2 | OpenAPI 보안 스킴 선언 | P1 | `/admin`·`/tripmate` 변경 계열에 securityScheme + `security` 표기. |
| 3 | health/version 중복 정리 | P2 | `/health`+`/ops/health-deep`로 수렴, `/debug/*`·중복 version deprecate. |
| 4 | admin/tripmate update-request 중복 | P2 | 동일 스키마 → 핸들러 공유 명시 또는 단일 표면+scope 분리. |
| 5 | `/features` cursor 페이지네이션 | P2 | admin과 동일한 cursor+page_size 규약으로 통일. |
| 6 | 단수/복수·param 명명 통일 | P3 | `*-reviews` 복수화, `_id`/`_key` 규약 통일(호환성 고려, 차기 메이저). |
| 7 | RFC7807 오류·idempotency·rate-limit 헤더 | P3 | 외부 계약 표준화. |

> P1 2건(versioning·보안 스킴)은 **외부 cross-service 계약 안정성**의 핵심이라 ADR-045 운영 진입 전
> 정책 결정을 권고한다. 나머지는 차기 메이저(예: `/v1`) 도입 시 함께 정리하면 호환성 부담이 작다.

## 6. 부록 — 전체 엔드포인트 (admin/full 55, user 13)

### 6.1 user profile (TripMate 외부 노출, 13)
```
GET   /health
GET   /version
GET   /categories
GET   /providers/{provider}/last-sync
GET   /features/search
GET   /features/in-bounds
GET   /features/nearby
GET   /features/nearby/by-target
GET   /features/{feature_id}
GET   /features/{feature_id}/weather
POST  /tripmate/features/batch
POST  /tripmate/feature-update-requests
GET   /tripmate/feature-update-requests/{request_id}
```

### 6.2 admin/full 추가분 (42, user profile 외)
```
GET/POST           /admin/backups
GET                /admin/backups/{backup_id}
POST               /admin/restore/{backup_id}
POST               /admin/restore/{backup_id}/swap
GET                /admin/features
POST               /admin/features/{feature_id}/deactivate
GET                /admin/issues
GET/PATCH          /admin/issues/{violation_key}
GET                /admin/dedup-review
PATCH              /admin/dedup-review/{review_key}
GET                /admin/enrichment-review
PATCH              /admin/enrichment-review/{review_key}
GET/POST           /admin/feature-update-requests
GET                /admin/feature-update-requests/{request_id}
POST               /admin/feature-update-requests/{request_id}/cancel
POST               /admin/feature-update-requests/{request_id}/run-now
GET/POST           /admin/offline-uploads
GET                /admin/offline-uploads/{upload_id}
GET                /admin/offline-uploads/{upload_id}/preview
POST               /admin/offline-uploads/{upload_id}/validate
GET                /admin/offline-uploads/{upload_id}/validation
POST               /admin/offline-uploads/{upload_id}/load
GET                /admin/poi-cache-targets
GET/PUT/DELETE     /admin/poi-cache-targets/{external_system}/{target_key}
GET                /features                 (limit only)
GET                /ops/metrics
GET                /ops/health-deep
GET                /ops/import-jobs
GET                /ops/import-jobs/{job_id}
GET                /ops/consistency/issues
GET                /ops/consistency/reports
GET                /ops/system-logs
GET                /ops/api-call-logs
GET                /ops/dagster/summary
GET                /ops/dagster/runs/{run_id}
POST               /ops/dagster/nux-seen
GET                /debug/health
GET                /debug/version
GET                /debug/etl/providers
GET                /debug/etl/{provider}/datasets
POST               /debug/etl/{provider}/{dataset}/preview
GET                /debug/mois-license/{license_id}
POST               /tripmate/features/batch   (admin profile에도 노출)
```

---

*작성: Claude (2026-06-08). 본 검토는 OpenAPI 두 profile + TripMate `etl_bridge/krtour_map.py` 기준.
실제 인증/게이트웨이 구현은 인프라 레벨에 있을 수 있으나 본 검토는 **OpenAPI 계약 표면**을 기준으로 한다.*
