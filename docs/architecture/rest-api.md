# kor-travel-map REST API — 전 표면 카탈로그 + 정합성 표준

> **상태**: 2026-07-13. PR #317(T-214/T-215)의 `/v1` 1차 정리 위에 ADR-048(admin/ops
> versioning 확장 + envelope/pagination/parameter/response 정합성 표준 + 코드/DB 명명 전파
> T-216a~g)을 얹은 기준선. **T-216a~g는 구현 완료**(런타임 envelope = 공유 `Meta`,
> `page_size`+`cursor`, RFC7807 problem+json) — 아래 본문의 "🔁 변경"·"현재→목표" 표기는
> **이미 반영된 변경 이력**으로 읽는다(구 `limit`/CSV-bbox/`count` 형태는 더는 존재하지 않음).
> **범위**: kor-travel-map **전 표면**(공개/user + admin + ops + debug)의 **단일 계약 정본**
> (ADR-048 #9).
> **정본 우선순위**: 기계 정본 = `packages/kor-travel-map-api/openapi.json`·`openapi.user.json`.
> 충돌 시 **OpenAPI 우선**. 결정 = ADR-048.
> **전환 정책(ADR-048)**: 호환성 미고려 — `/v1` clean cut, 구 경로/alias 없음.
> **표기**: 🆕 신규 · 🔁 변경 · ⚠️ 제거 · ✅#317 = #317로 이미 구현.

---

## vNext 단계적 전환 표면 (ADR-066·067·072~074, 부분 구현)

기계 정본 OpenAPI는 **현재 구현 계약**이다. 공개 조회·검색, route policy 기반 security,
raw lineage 분리와 principal actor, 5-state feature batch와 sparse weather batch는
main에 반영됐다. 아래 표에는 현재 계약과 cache target·refresh 같은 후속 목표를 함께 표시한다.
PinVi가 소비하는 변경은 [`integration-map.md`](../integration-map.md)의 consumer-first 조건을
통과한 compatible pair에서만 활성화한다. 호환 alias는 만들지 않는다.

| 표면 | 목표 resource | 핵심 계약 |
|---|---|---|
| public-keyed | `GET /v1/features/{feature_id}` | kind-discriminated typed detail, `ETag(row_revision)` |
| public-keyed | `GET /v1/features/{search,nearby,in-bounds}` | fingerprint cursor, total opt-in, 지도 mode/truncated/coverage/cluster key |
| public-keyed | `GET /v1/categories` | catalog revision ETag |
| public-keyed | `GET /v1/collections`, `GET /v1/collections/{id}` | collection/item 단일 curation read 정본 |
| service | `POST /v1/features/batch` | `found|retired|suppressed|missing|unchanged` + revision; transport 503 분리 |
| service | `POST /v1/features/weather/batch` | sparse `targets[]`/`known_at` 다중 시각 bitemporal query |
| service | `PUT/DELETE /v1/service/cache-targets/{system}/{key}` | 단조 `source_generation`, ETag/If-Match |
| service | `POST/GET /v1/service/refresh-requests[/{id}]` | Idempotency-Key, 202 operation resource |
| operator | `/v1/features/{id}/sources|observations` | raw lineage의 유일한 REST 표면 |
| operator | `/v1/feature-change-requests` | principal actor, revision 재검사 |
| operator | `/v1/ops/datasets/*`, `/v1/ops/pipeline/*` | ADR-064 canonical control plane 유지 |
| operator | `/v1/provider-datasets` | ADR-069 DB-owned dataset 관리 |

공개 DTO에는 `raw_data`, `raw_payload_hash`, `source_record_key`, provider payload passthrough와
ingestion timestamp(`fetched_at`/`imported_at`/`last_seen_at`)가 없다. 공개 operation의 response
root에서 재귀적으로 도달 가능한 모든 component에 같은 규칙을 적용한다. public DTO와
admin/operator raw DTO는 상속하지 않으며 서로 독립된 projection이다.
공개 curated list/detail도 admin overlay DTO와 분리한 명시적 allowlist를 사용한다.
`PublicCuratedFeatureView`는 `feature_kind`로 판별하는 7종
`place|event|notice|area|route|price|weather` union이다. 주소와 kind별 detail은 strict
중첩 DTO이며, place의 시설·영업시간·전화·리뷰 링크도 검토된 키와 값만 새로 조립한다.
따라서 `detail.payload`, concierge YouTube/transcript/evidence 미러, 알 수 없는 nested raw,
DB/source identity, 선정 감사 필드는 직렬화되지 않고 `/v1/admin/features/curated*`에만
남는다. 알 수 없는 kind는 공개 목록에서 제외하고 상세는 404다(T-VN-05R).
`include_geometry`는 동일 candidate set의 serialization만 바꾸고, `include_total=false`이면 COUNT를
실행하지 않는다. search cursor는 version과 정규화 query fingerprint를 검증하고 HMAC-SHA256으로
payload 무결성을 보호한다. 다른 query 재사용은 `CURSOR_QUERY_MISMATCH`, 변조는
`FEATURE_SEARCH_CURSOR_TAMPERED`로 거부한다. body actor, 동작하지 않는 beach 옵션, 수기 OpenAPI allowlist는
제거하고 route policy에서 public/service/operator profile을 생성한다.

MVT tile, 범용 `feature-context` batch, 물리 listener 분리는 목표 계약이 아니라
T-VN-51~55의 실측 결과가 채택 조건을 충족할 때만 새 결정을 연다.

route policy matrix는 문서·OpenAPI 분류 입력에 그치지 않는다. `create_app()`은 조립된 모든
route의 실제 enforcing dependency가 정책과 일치하는지 startup에서 검증하며, 미분류 route,
PUBLIC_KEYED/OPERATOR 오배선, stale exception ledger는 서버가 listen하기 전에 실패한다.

브라우저 CORS는 public 표면에만 적용하고 route별 실제 HTTP method를 허용한다. request header는
CORS safelist(`Accept`, `Accept-Language`, `Content-Language`, `Content-Type`), conditional GET의
`If-None-Match`, `X-Kor-Travel-Map-Api-Key`만 허용한다. public conditional GET 응답은 `ETag`를
browser JavaScript에 노출한다. 다른 method나 admin/service credential header의
preflight는 400이며 `Access-Control-Allow-Origin`을 내보내지 않는다. service/operator/metrics/
debug 표면은 origin이 허용 목록에 있어도 CORS를 광고하지 않는다(T-VN-H03R).

## 0. 한눈에 — #317이 한 것 vs ADR-048 delta

| 영역 | #317(T-214/T-215) | ADR-048 보강 |
|------|-------------------|-------------|
| versioning | 외부(`/features`·`/curated-*`·`/categories`·`/providers`) `/v1`, **admin/ops 비버저닝** | **admin/ops/debug도 `/v1`**(사용자 지시, T-214b §2.1 supersede) |
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
- API `http://127.0.0.1:12701`(admin UI `12705`, Dagster `12702`; PC 개발 host
  `5432`는 docker-manager가 구동하는 공유 PostgreSQL/PostGIS **인스턴스/컨테이너**이나,
  kor-travel-map은 그 안의 **소유 독립 DATABASE `kor_travel_map`**을 쓴다(공유 DB 아님, ADR-045);
  RustFS `12101`/`12105`). `TRIPMATE_KOR_TRAVEL_MAP_API_BASE_URL`은 host root까지만 포함하고,
  모든 REST path가 `/v1` prefix를 명시한다(예: base `http://127.0.0.1:12701` +
  path `/v1/features/search`). base와 path 양쪽에 `/v1`를 중복 삽입하지 않는다.

### 1.2 Versioning (ADR-048 — #317 확장)
- **전 표면 `/v1`**: `/v1/features/*`·`/v1/categories`·`/v1/providers/*`
  **+ `/v1/admin/*`·`/v1/ops/*`·`/v1/debug/*`**(ADR-048이 #317의 admin 비버저닝을 supersede).
  `/tripmate/*` namespace는 **제거**(kor-travel-map은 PinVi에만 묶이지 않음) — batch는
  `/v1/features/batch`로 일반화.
- **비버저닝 고정**: `/health`·`/version`. 경로별 shim 금지(ADR-046) — mount 1곳 전환.
- **무-호환 clean cut(ADR-048, 사용자 지시)**: 호환성은 고려하지 않는다. 구 unprefixed
  경로·호환 alias를 유지하지 않고 `/v1`로 **즉시 단일 전환**한다(이중 코드경로 제거). 소비자
  (PinVi)는 안정 spec commit 기준으로 lockstep 추종(T-181) — 별도 dual-support 창 없음.
- **`/vN` major 거버넌스(ADR-048 #13)**: **pre-1.0(현재)** = `/v1` 가변, in-place breaking
  허용(위 clean cut). **v1.0.0 GA에서 `/v1` 동결** → 이후 breaking = `/v2` + N-1 동시지원
  (`Deprecation`/`Sunset` 헤더), OpenAPI major별 분리 export. 즉 "지금은 깨도 되고, GA 후엔
  `/v2`로만 깬다"를 규칙화.

### 1.3 인증 (ADR-066·T-VN-57)
- `RoutePolicy.PUBLIC_KEYED`로 분류된 모든 public operation은 production에서 VWorld 호환
  `X-Kor-Travel-Map-Api-Key` header 또는 `ServiceToken` 중 하나를 요구한다.
  URL `key` query는 T-VN-H01에서 clean-cut으로 폐기했다. OpenAPI도 두 scheme을 OR
  대안으로 선언한다. trusted admin BFF 우회는 same-origin UI용 내부 경계이며 public
  consumer security에는 노출하지 않는다.
- `POST /v1/features/batch`와 `POST /v1/features/weather/batch`는
  `RoutePolicy.SERVICE`이며 `ServiceToken`(`X-Kor-Travel-Map-Service-Token`) 전용이다.
  `/health`·`/version`·기계 판독 `/openapi.json`만 public-unauthenticated다.
- `/v1/admin/*`는 trusted Admin BFF, `/v1/ops/*`는 경로·method별 Admin BFF 또는 제한된
  ops principal, `/metrics`는 metrics token을 사용한다. production은 필요한 secret이나 public
  key gate가 빠진 구성을 기동 전에 거부한다.
- route 추가·삭제 시 runtime policy, full OpenAPI, user OpenAPI를 각각 수기로 갱신하지 않는다.
  `ROUTE_POLICIES`와 조립된 route method metadata에서 파생하고 양방향 전수 drift gate로 고정한다.

### 1.4 응답 envelope (🔁 ADR-048 — payload/meta 완전 분리)
- 성공 `{ "data": <payload>, "meta": <Meta> }`. **`data`는 payload만**:
  단건=`<object>`, 목록=`{items:[…]}`, in-bounds=`{clusters:[…],items:[…]}`,
  batch=`{found:{feature_id:Feature},missing:[…]}`. list의 `items`는 항상 배열이고,
  id-keyed map은 `found`처럼 별도 키를 쓴다.
- **페이지네이션·추적·뷰 해석 메타는 `meta`로 일원화**:
  `meta = { duration_ms, request_id, page?: { page_size, next_cursor, total },
  cluster?: { cluster_unit, drill_down_unit } }`(`page`는 pageable 목록에만,
  `total`은 opt-in `null` 기본,
  `cluster`는 in-bounds에만). `data.next_cursor`/`data.total_count`/`data.cluster_unit`/
  파생 `count`는 **폐기**.
- 라우터별 `FeatureListMeta`/`FeatureDetailMeta`/… 중복 → 공유 `Meta` 1개 + `data` payload
  모델. 확장 시 `meta.page`만 늘리면 됨(payload 불변). 성공 응답에도 `request_id`(추적 대칭).

#### 1.4.1 in-bounds cluster 귀속 규칙

- `meta.cluster`가 존재하면 `cluster_unit`은 필수 enum(`sido | sigungu |
  eupmyeondong`)이고, `drill_down_unit`도 필수 필드이되 값은 같은 enum 또는 `null`이다.
  `eupmyeondong`의 다음 단계는 개별 feature이므로 `null`을 반환한다.
- cluster 귀속 정본은 feature에 저장된 canonical 행정코드(`sido_code` / `sigungu_code` /
  `legal_dong_code`)다. bbox와 교차하는 route/area가 행정 경계를 가로질러도 선택한 단위의
  저장 코드 **하나에 정확히 한 번** 귀속하며, 교차 영역별로 여러 cluster에 분할·복제하지
  않는다. 따라서 `feature_count` 합계는 해당 단위 코드가 보강된 items 후보 수와 일치한다.
- geometry의 bbox 교차 부분은 지도 marker 위치를 계산할 때만 사용한다. marker 위치가
  cluster 귀속 코드를 바꾸지 않는다. 선택 단위의 저장 코드가 `null`인 feature는 items에는
  남지만 해당 cluster rollup에서는 제외된다.
- 이 규칙은 본 DB가 feature-level canonical 주소 코드를 보유하고 행정경계 polygon을
  소유하지 않는 현재 구조에 맞춘 것이다. 공간 분할 귀속이 필요해지면 경계 polygon과
  중복 집계 의미를 별도 데이터/API 계약으로 먼저 도입해야 한다.

### 1.5 에러 — RFC 7807 `application/problem+json` (🔁 ADR-048 / T-214g)
```json
{ "type":"https://kor-travel-map/errors/feature-not-found", "title":"Feature not found",
  "status":404, "detail":"…", "code":"FEATURE_NOT_FOUND", "request_id":"01J…",
  "errors":[{"field":"feature_id","message":"…"}] }
```
- `Content-Type: application/problem+json` + `X-Request-ID`. 중앙 핸들러(`app.py`
  `_error_response`)가 통일. `code`·`request_id`는 **top-level 확장 멤버**(소비자 파싱 위치
  고정), 코드 enum(§4)을 확장 `code`로 유지.
- **기계 계약 반영(T-452, ✅ 적용)**: `create_app`의 custom `app.openapi()`가 모든 operation의
  4xx/5xx와 `default` 응답을 RFC7807 `application/problem+json`(`ProblemDetail` schema)으로
  선언한다. FastAPI 자동 `422 application/json`(`HTTPValidationError`)도 problem+json으로
  대체하고, orphan이 된 검증 schema는 제거한다. **본 §1.5 산문 계약과 generated `openapi.json`의
  `ProblemDetail`이 함께 정본**이며, 기계 계약도 `code`·`request_id` 확장 멤버와 `errors[]`
  (`ProblemDetailError`)를 포함한다. `ProblemDetail`은 `extra=allow`라 핸들러가 싣는 추가 키
  (`details` 등)와 검증 오류 원형(`loc`/`msg`)을 모두 허용한다. 산출물은
  `export_openapi.py --check` drift gate(ADR-031)로 고정한다.

### 1.6 페이지네이션 (🔁 ADR-048, T-214e 심화)
**해소된 실측 불일치(T-216 이전)**: 과거에는 page-size 파라미터 3종(`limit` features 평면/
in-bounds/search · `page_size` 그 외 · `run_limit`/`event_limit` dagster), 캡 3종
(`le=5000`/`500`/`200`)이 공존하고 `search`는 cursor인데 `limit`을 썼다. **T-216b/c로
아래 표준으로 통일 완료** — cursor 페이지네이션 표면의 page-size 파라미터(`limit`/`run_limit`/
`event_limit`)는 `page_size`로 통일됐다. **단 예외**: bounded top-N list 엔드포인트
(`/v1/{curated-themes,curated-sources}` 등 curated read + admin curated 미러)는 cursor가
아니라 결과 상한 cap으로서 `limit`(`le=500`, 기본 200)을 명시적으로 유지한다.
**표준(현행)**:
- cursor 페이지네이션 표면은 `page_size`(정수)+opaque `cursor`(base64 keyset)로 통일.
  `limit`/`run_limit`/`event_limit`은 cursor 표면에서 **폐기**(bounded top-N의 `limit` cap은
  위 예외로 유지). 응답은 `meta.page.next_cursor`(null=마지막, §1.4). page_size+1 fetch.
- 2-티어 캡: 기본(detail/admin/ops) 50/최대 200, 지도(`nearby`·`by-target`) 100/최대 500.
- `/v1/features` 평면: `page_size`+`cursor`(`limit le=5000` 폐기). `/v1/features/in-bounds`:
  cursor 없이 `max_items` 하드캡 5000→2000 + 결정적 `feature_id` 정렬(T-212d).
- `meta.page.total`은 `?include_total=true` opt-in(기본 `null`). `/v1/features/search`는
  `include_total=false`일 때 COUNT SQL을 만들거나 실행하지 않고 page-size+1 keyset 조회 한 번만
  수행한다. `true`일 때만 같은 정규화 filter의 별도 COUNT를 실행한다.

#### 1.6.1 feature search cursor v1

- cursor는 `base64url(canonical_payload).base64url(hmac_sha256)`의 opaque token이다. payload는
  `v=1`, cursor kind, query fingerprint, 마지막 keyset(`score`+`feature_id` 또는
  `feature_id`)만 가진다. 서명은 payload 원문과 cursor kind domain separator를 함께 덮고
  `hmac.compare_digest`로 검증한다. 원 검색어·secret은 cursor에 넣지 않는다.
- query fingerprint는 repository가 실제 SQL에 사용하는 정규화 계약을 canonical JSON으로 만든 뒤
  SHA-256한다. `q`는 trim 후 빈 문자열을 `null`, bbox는 유한한 WGS84 float 4개, `kind`/`category`는
  중복 제거·사전순 정렬(빈 배열은 `null`)한다. 여기에 q 유무로 결정되는 sort
  (`score DESC, feature_id ASC` 또는 `feature_id ASC`), `page_size`, `include_total`을 포함한다.
  따라서 필터 순서만 바꾼 요청은 같은 계약이고, 결과집합·정렬·page metadata를 바꾸는 요청은
  다른 계약이다.
- 디코드 순서는 형식/길이 → HMAC → version/kind → fingerprint → keyset type·finite score다.
  malformed는 `FEATURE_SEARCH_CURSOR_INVALID`, 서명이 맞지만 알 수 없는 version은
  `FEATURE_SEARCH_CURSOR_VERSION_UNSUPPORTED`, 서명 불일치는
  `FEATURE_SEARCH_CURSOR_TAMPERED`, 현재 query와 fingerprint가 다르면
  `CURSOR_QUERY_MISMATCH`인 RFC7807 422다. 어느 실패도 DB query 전에 끝난다.
- HMAC key는 server-only `KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET`이며 public API key,
  service token, admin proxy secret, ops token, metrics token과 공유하지 않는다. production에서 feature search surface가
  켜져 있으면 공백 없는 최소 32자 secret이 없을 때 기동을 거부한다. `local-dev` 미설정 시에만
  process-local 난수 key를 허용하며 재시작·다중 worker 사이 cursor 지속성을 보장하지 않는다.
  운영 rotation은 새 key 배포와 동시에 기존 cursor를 의도적으로 무효화하는 clean cut이다.

### 1.7 idempotency · rate limit (T-214g)
- 일반 변경 POST는 endpoint 계약에 따라 `Idempotency-Key`를 사용할 수 있다. canonical
  feature update 생성 `POST /v1/ops/pipeline/requests`는 UUID 형식
  `Idempotency-Key`가 **필수**다. 같은 인증 actor namespace에서 같은 key와 동일한
  정규화 body를 보내면 최초 결과를 `200`으로 재생하고 `idempotent_replay=true`, 최초
  생성은 `201`과 `idempotent_replay=false`를 반환한다. 같은 actor가 같은 key를 다른
  body에 재사용하면 `409 FEATURE_UPDATE_IDEMPOTENCY_CONFLICT`다. 다른 actor의 key 공간은
  독립되어 서로의 결과를 조회·재생·충돌시키지 않는다.
- rate limit은 `429`+`RateLimit-*`+`Retry-After`, lock 경합은
  `409 LOCK_BUSY`+`Retry-After: 15`를 사용한다.

#### Admin domain command ledger (T-VN-12)

- 정적 route inventory가 모든 write operation을 `db_only|external|non_retryable`로
  분류한다. retryable command는 UUID `Idempotency-Key`가 필수이며 actor·operation과 함께
  key 공간을 이룬다. body natural key나 client-side body hash는 command identity가 아니다.
- 최초 요청은 canonical path/body fingerprint를 `ops.domain_commands`에 claim한다. 같은
  actor/operation/key와 같은 fingerprint는 저장된 terminal status/body/header를 그대로
  재생하고, 다른 fingerprint는 `409 IDEMPOTENCY_FINGERPRINT_CONFLICT`다. 다른 actor는 같은
  UUID를 독립적으로 쓸 수 있다.
- DB-only command는 domain 변경과 terminal result를 한 transaction에서 commit/rollback한다.
  외부 효과 command는 도메인 execution row를 먼저 `prepared`, 실행 직전
  `effect_started`, 효과별 proof 확정 뒤 `effect_succeeded`로 전진시킨다. claim만 있거나
  proof가 불충분한 상태는 `409 IDEMPOTENCY_RESULT_PENDING`이며 성공을 합성하지 않는다.
- offline upload create는 DB에 `uploading` reservation과 object identity를 먼저 고정하고
  S3 write 뒤 byte/size/content-type/metadata proof와 `uploaded` 전이를 terminal result와
  함께 commit한다. authoritative `NoSuchKey`만 exact PUT 재개를 허용하고 transport/5xx
  ambiguity는 fail-close한다. delete는 `deleting + delete_command_id`를 원자 예약하므로
  다른 key의 경쟁 요청은 claim까지 rollback된 `409`로 끝난다.
- backup/restore/swap은 host wrapper가 `maintenance:backup-restore` session lock을
  `pg_try_advisory_lock`으로 잡고 child process 전체 수명 동안 보유한다. 그 전에 API는 같은
  lock 안에서 execution의 immutable `effect_token`에 묶인 고정 이름 global Docker fence를
  생성·inspect한 뒤에만 `effect_started`로 전이한다. fence는 canonical compose service의
  local immutable Image ID와 `--pull=never`, network none, read-only rootfs, capability 제거,
  `no-new-privileges`, 비 root user를 사용한다. command/operation/input digest/source revision/
  Image ID label과 runtime shape가 exact하지 않으면 새 command는 `prepared`에 남는다. wrapper가
  `TERM`/`INT`를 받으면 호출자 detach만 기록하고 daemon effect와 연결된 child에는 전달하지
  않는다. child output은 API pipe와 분리된 임시 spool에 저장하며 direct child와 process
  group이 자연 terminal에 도달한 뒤에만 lock을 해제한다. API cancellation은 호출자에게
  응답하지 못한 채 bounded하게 반환하고 timeout은 `504 BACKUP_COMMAND_TIMEOUT`으로
  bounded 반환하지만, execution row는 `effect_started`로 남고 wrapper supervision은 계속된다.
  wrapper와 local child group이 hard crash로 사라지면 session lock은 풀릴 수 있지만 daemon의
  global fence는 남는다. marker 없는 `effect_started` 동일 command는 script 호출 전에
  `409 BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED`로 차단하고, 다른 command도 fence
  preflight에서 mutation 없이 `prepared`로 남긴다. 문제 응답은 secret이 아닌 command ID,
  operation, effect token, input digest, fence name과 안전한 수동 절차를 제공한다. missing/
  foreign/mismatched fence나 marker는 자동 채택하지 않는다. API 내부 backup delete는 같은 lock을
  effect·proof·terminal DB commit까지 직접 보유한다. exact command marker/reservation 없는
  기존 backup artifact나 restore target은 새 command 결과로 채택하지 않는다. wrapper가
  exact marker를 만든 뒤 동일 command를 재시도하면 외부 효과를 반복하지 않고 marker proof로
  terminal result를 확정한다. hard crash 뒤 marker는 외부 운영자가 실제 workload terminal과
  output identity를 확인한 경우에만 만들며, marker proof 전에 fence를 해제하지 않는다.
- admin UI는 resource command slot 또는 create draft slot에 UUID와 submission fingerprint를
  함께 동결한다. response-loss/transport ambiguity에서는 같은 submission만 같은 UUID로
  재시도하며 내용이 달라지면 로컬에서 차단한다. 성공·확정 실패·인증 actor 전환 때 slot을
  해제한다.

### 1.8 좌표 · datetime
- WGS84 lon,lat. bbox=`min_lon,min_lat,max_lon,max_lat`. 목록 좌표는 평면 `lon`/`lat`.
  datetime ISO 8601 KST-aware.

### 1.9 파라미터 규약 (🔁 ADR-048 — T-216f 적용 완료)
- **bbox 분리 float 4개로 통일**(`search`의 CSV `bbox` 제거 — clean cut, 적용 완료).
- 다중값 필터는 단수 반복(`?kind=a&kind=b`/`category`/`provider`/`status`).
- lifecycle 상태 필드 `status`로 통일(`import-jobs`/`offline-uploads`/`feature-update-requests`
  의 `state` 개명; `severity` 별개 축). issue/violation noun은 외부 표면에서 `issue_*`.
- 범위 `min_*`/`max_*`, 시각 `*_from`/`*_to`, 정렬 `sort`(+`order`).

---

## 2. 엔드포인트 카탈로그 (목표 `/v1` 전 표면, #317 반영)

> 본 문서가 전 표면 계약 정본이다.

### 2.1 Liveness (비버저닝)
```
GET /health        GET /version
```

### 2.2 `/v1/features/*` — 조회 (user+admin 공용)
```
GET /v1/features                        # page_size+cursor (T-216b 적용 완료; 구 limit-only 폐기)
GET /v1/features/search                 # q|bbox, page_size+cursor, meta.page.total opt-in
GET /v1/features/in-bounds              # clusters[](cluster_key=행정코드)/items[], max_items cap
GET /v1/features/nearby                 # 반경, page_size+cursor, distance_m
GET /v1/features/nearby/by-target       # 등록 POI cache target 주변
GET  /v1/features/{feature_id}          # 단건 상세
GET  /v1/features/{feature_id}/observations/{source_entity_key}/history
GET  /v1/features/{feature_id}/weather  # 날씨 카드(metric + forecast_style)
POST /v1/features/batch                 # trip_card 5-state batch, cap≤200 (ServiceToken)
POST /v1/features/weather/batch         # sparse targets[]/known_at weather snapshots (ServiceToken)
```
- 단건과 batch의 각 Feature 상세는 `curations[]`와 `observations[]`를 함께 반환한다.
  `observations[]`는 Feature에 연결된 provider entity별 **현재 immutable payload 전부**이며,
  여러 `is_primary_source=true` 관측도 버리지 않는다. payload의 과거 version은
  `/{feature_id}/observations/{source_entity_key}/history`에서 `page_size`(기본 50, 최대 200)+
  `cursor`로 최신순 조회한다.
- 관측 DTO는 entity/record 식별자, `raw_data`와 hash, 원천 이름·주소·좌표, entity/record
  관측 시각, Feature link의 role·match method·confidence·primary 여부를 함께 반환한다.
  history 정렬 키는 `record_last_seen_at DESC`, `fetched_at DESC`, `imported_at DESC`,
  `source_record_key DESC`이고 cursor는 해당 `feature_id`/`source_entity_key`에 묶인다.
  잘못되거나 다른 관측에 재사용한 cursor는 422, 첫 page에 해당 link가 없으면 404이며,
  마지막 cursor 다음은 200과 빈 `items`다.

#### Weather batch 계약(T-VN-16A/C)

- service-token 전용 `POST /v1/features/weather/batch`가 set-based 조회의 정본이다.
- 요청은 `targets=[{target_at, feature_ids}]` sparse group과 timezone-aware
  `known_at`을 받는다. target은 중복 없이 `target_at` 오름차순이며 최대 366개,
  group별 Feature ID는 입력 순서를 보존하는 256자 이하 고유값 1~200개, 전체 실제
  `target_at×feature_id` pair는 2,000개 이하다. DB 진입 전
  `pair 수 + 5 × 전체 고유 Feature 수 <= 2,500`도 강제해 spatial 후보 계획 비용을
  제한한다. 날짜별로 필요하지 않은 Feature를 Cartesian product로 조회하지 않는다.
- `target_at`은 해당 group의 날씨가 설명하는 시각이고, 모든 group이 같은
  `known_at` 지식 cutoff를 공유한다. current-row fact에서는 `collected_at`을
  `known_at` 대리값으로 사용하며 forecast는 `issued_at <= known_at`도 강제한다.
- 부모 공개 판정, nearest weather source tier, `current`, 각 `target_at` 뒤 24시간
  `timeline`을 group 수와 무관하게 PostgreSQL statement 1회에서 읽는다. 고유
  parent별 own/nearby spatial 후보 집합은 한 번만 계산하되, 최종 source의 series와
  fact 적격성은 각 `target_at` 및 공통 `known_at` cutoff로 판정한다. 따라서 미래에
  추가된 series가 과거 snapshot의 `found|no_data` 또는 source를 바꾸지 않으며,
  가용한 weather가 달라지면 target마다 source가 달라질 수 있다.
- 응답 `targets[]`와 각 `items[]`는 요청 순서를 그대로 보존하며 target마다
  `timeline_until`을 명시한다. `found` item은 target-local `card_key`만 가지며 같은
  target/source bundle의 metric은 `cards[]`에 한 번만 둔다. `no_data`와 `retired`는
  card를 참조하지 않는다. `target_at + 24시간`을 표현할 수 없는 최댓값 부근 시각은
  422로 거부한다.
- fact projection 전에 공유 card×physical series 작업량 150,000을 제한한다.
  정규화된 `cards[]`의 전체 current/timeline metric은 최대 20,000행이며 item/card/metric
  구조를 포함한 보수적 전체 JSON 응답 추정치는 최대 8 MiB다. SQL이 이 예산을 같은
  snapshot에서 계산하며 초과하면 부분 item을 반환하지 않고
  `413 WEATHER_BATCH_RESULT_LIMIT_EXCEEDED`로 전량 거부한다. query는 transaction-local
  PostgreSQL `statement_timeout` 20초를 적용하고 성공 시 이전 값을 복원한다. timeout은
  DB의 statement 취소가 끝난 뒤 응답하며, DB/transport 실패와 함께 item 상태로
  축약하지 않고 전체 `503 WEATHER_BATCH_UNAVAILABLE`다.
- source 선택은 요청 Feature 자체의 weather를 먼저 쓰고, 없으면 공개·활성
  `kind='weather'` anchor 후보만 거리순으로 사용한다. 후보는 series catalog로
  좁히지만 실제 선택은 해당 target의 bitemporal fact 적격성까지 만족해야 한다.
  `kind='place'` 등에 결합된 weather는 해당 Feature의 자체 값일 뿐 다른 Feature가
  공유하는 anchor가 아니다.
- physical series는
  `(feature_id, provider, weather_domain, forecast_style, metric_key)`다. 응답 metric은
  `provider`·`weather_domain`, 원래의 `valid_at`/`valid_from`/`valid_until`과 current
  선택에 사용한 `effective_at`을 함께 반환한다. range 값은 `valid_from <= target_at <=
  valid_until`일 때만 `current`이며, 미래 구간은 24시간 지평선의 `timeline`에 남는다.
- item state는 `found|no_data|retired`다. `no_data`는 공개 parent는 있으나 cutoff에
  맞는 날씨가 없음, `retired`는 현재 공개 projection에 parent가 없어 단건에서 404가
  되는 상태다.
- `GET /v1/features/{feature_id}/weather`도 같은 batch repository를 ID 1개로 호출한다.
  따라서 parent 404와 빈 날씨 판정이 단건/batch에서 달라지지 않는다.
- ⚠️ `/tripmate/*` namespace **제거**(kor-travel-map은 PinVi 전용이 아니다). batch는
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
  `/v1/categories`처럼 비페이지네이션 bounded reference 패턴. 외부 소비자 상태판용이며,
  admin 운영 화면은 더 완결된 `/ops/datasets` 계약을 사용한다. 빈 환경은 200 + 빈 `items`.

### 2.4.1 `/v1/public/*` — 공개 해수욕장/축제 뷰 (PinVi T-130)

PinVi T-130(`/public/*`)이 요구하는 해수욕장/축제 공개 조회 뷰의 제안 사양은
[`docs/architecture/public-views-api.md`](public-views-api.md)를 따른다. T-222b(2026-06-12)부터
이 표면은 `openapi.user.json` 사용자 profile과 `@kor-travel-map/map-user-client` 생성 타입에
포함한다.

엔드포인트:

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
  KHOA provider category는 DA-D-07로 `01050100`(`TOURISM_NATURE_BEACH`)로 정렬됐다
  (구 `01020300`은 오분류, 구 feature는 alembic 0027로 정리).
- 수질/KHOA index/latest weather 필드는 schema에 nullable/빈 배열로 열어 두되,
  값 projection은 후속 marine/weather 확정 후 채운다.
- 축제 월별 뷰는 `EventDetail.starts_on`/`ends_on` 기간 겹침으로 집계한다.

### 2.4.2 `/v1/features/*/weather*` — 공개 weather forecast/history API (ADR-062)

`/v1/features/{feature_id}/weather`는 feature 상세 카드용 최신 요약으로 유지한다.
외부 시스템이 예보 timeline과 과거 발표 snapshot을 비교할 때도 별도 weather API가 아니라
feature API의 weather subresource를 쓴다.

```
GET /v1/features/weather/forecast                # lon/lat 기준 nearest weather anchor forecast
GET /v1/features/{feature_id}/weather/forecast   # feature 좌표 기준 nearest weather anchor forecast
GET /v1/features/weather/alerts                  # KMA 기상특보 typed 공개 이력
GET /v1/admin/features/weather/alerts            # 원문·lineage 포함 operator 이력
```

핵심 계약:

- 기본 조회 보존 지평선은 3년(`history_days<=1095`)이다.
- forecast 응답 row는 `issued_at`, `valid_at`, `valid_from`, `valid_until`,
  `observed_at`을 함께 내려 3시간 전/1일 전 발표 예보와 현재 발표 예보를 같은
  유효시각 기준으로 비교할 수 있게 한다.
- 좌표 기반 forecast는 반경 내 가장 가까운 KMA 예보 anchor를 사용한다. anchor가 없으면
  200 + 빈 `items`로 반환한다.
- 중기예보는 `forecast_style=mid`, `weather_domain=kma_mid_forecast`로 포함한다.
- 공개 forecast row는 원천 record identity를 반환하지 않는다. 공개 기상특보 이력은
  `provider_sync.source_records`에서 도메인 필드와 발표·유효 시각만 typed projection하고,
  원문 payload·source record identity·ingestion timestamp는 반환하지 않는다.
- operator 기상특보 이력은 admin BFF 인증 아래 원문 payload와 lineage/ingestion timestamp를
  보존한다. 별도 alert history table은 만들지 않는다. forecast의 상세 lineage는 기존
  `/v1/features/{feature_id}/sources|observations` operator 표면에서 조회한다.

### 2.4.3 `/v1/curated-features*` — 테마형 큐레이션 후보 (T-223c-1 구현)

세계음식점, 독립서점, 카페가 있는 서점, 도서관, 무장애 관광지 같은 테마형 source는
[`docs/curated-features.md`](../curated-features.md)의 `feature.curated_*` overlay 계약을
따른다. PinVi는 이 표면을 읽어 `app.curated_trip_plans` /
`app.curated_plan_pois`로 1:1 복사한다. PinVi의 `/notice-plans`는 호환 API alias일
뿐 신규 정본명이 아니다.

T-223c-1부터 다음 read 표면은 `openapi.user.json` 사용자 profile과
`@kor-travel-map/map-user-client` 타입에 포함한다.

```
GET /v1/curated-themes
GET /v1/curated-sources
GET /v1/curated-features
GET /v1/curated-features/{curated_feature_id}
GET /v1/curated-features/{curated_feature_id}/pinvi-copy
```

공개 목록은 `theme_slug`, 표시 텍스트(`q`, `feature_name`, `display_title`), 행정구역·bbox와
cursor만 받는다. `theme_id`, `source_id`, `provider`, `dataset_key` 같은 내부 identity
필터는 `/v1/admin/features/curated`에만 둔다. 응답의 7종 판별 union과 strict nested
projection은 알 수 없는 kind/필드를 fail-closed 처리한다(T-VN-05R).

write/admin 표면은 `/v1/admin/curated-*`로 둔다. T-223c-1은 DB/API foundation과
rule apply endpoint까지 제공하며, Dagster 자동 실행과 Admin UI는 T-223c-2/c-3 후속이다.

### 2.4.4 `/v1/curations*` — collection/item 큐레이션 (ADR-063)

연도별 한국관광 100선, 국가유산 방문 캠페인, 스탬프투어처럼 같은 Feature가 여러
회차·코스·공식 목록에 포함되는 데이터의 정본 read 표면이다. 하나의 Feature marker/목록
행에 관련 membership을 `curations[]`로 모두 묶어 반환한다.

```
GET /v1/curations                            # Feature별 group, page_size+cursor
GET /v1/curations/collections                # 공개 collection 목록, page_size+cursor
GET /v1/curations/collections/{collection_id}# collection + included item 전체
GET /v1/curations/features/{feature_id}      # Feature + 공개 membership 전체
```

`GET /v1/curations`는 `theme_slug`, `edition_key`, `provider`, `q`, 분리 bbox 4개,
`page_size`(기본 100, 최대 500), `cursor`를 받는다. 필터는 반환할 Feature group을 고르는
조건이고, 선택된 group의 `curations[]`는 그 Feature의 관련 공개 active membership을
모두 보존한다. 응답 item은 `{feature, curations, curation_count}`다. marker 수와
membership 수를 구분하므로 같은 장소가 2023~2024·2025~2026 회차에 모두 속해도 marker는
하나이고 상세 정보는 둘 다 보인다.

`GET /v1/curations/collections`는 `theme_slug`, `edition_key`, `provider`, `q`,
`page_size`(기본 200, 최대 500), `cursor`를 받는다. 정렬과 cursor 경계는
`updated_at DESC, collection_id DESC`이고 잘못된 cursor는 422다. public 목록·상세는
`status=published`, `visibility=public`, 미보관 collection만 대상으로 하며 상세 item도
미보관 `status=included`만 반환한다.

collection 상세의 item은 `feature_id`가 nullable이다. 기존 Feature와 안전하게 연결하지
못한 공식 항목도 `place_name`, `address_hint`, 원천키와 함께 반환한다. 미연결 항목에는
Feature 좌표·category가 없으며 임의 인접 위치로 대체하지 않는다. Feature별 group과
Feature 상세에는 연결된 item만 나타난다. 공개 item은 source record identity와 자유형
`metadata`를 반환하지 않는다. 동일 저장 row를 쓰더라도 admin collection/item DTO는 별도
타입으로 `source_record_key`와 `metadata`를 보존한다. public DTO가 admin DTO의 base class가
되거나 그 반대가 되는 상속 구조는 금지한다. public collection summary의 `item_count`는 실제
반환 가능한 active `included` item 수만 뜻하며 후보·거절 건수와 `public_item_count`는
노출하지 않는다. admin summary는 전체 active `item_count`와 공개 가능한
`public_item_count`를 함께 반환한다. 연결 Feature가 hidden/deleted로 바뀐 public
collection item은 공식 `place_name`/`address_hint`는 보존하되 Feature ID·본문·좌표·주소·
source record 연결을 제거한 미연결 item으로 투영한다.

### 2.5 `/v1/admin/*` — 운영자 (인프라 SSO + kill-switch)
```
GET    /v1/admin/features                              # 목록(page_size+cursor)
GET    /v1/admin/features/in-bounds                    # raw bbox items/cluster(status 반복 필터)
GET    /v1/admin/features/{feature_id}                 # 상세
GET    /v1/admin/features/{feature_id}/revision        # row_revision + raw strong ETag 편집 기준
GET    /v1/admin/features/{feature_id}/weather         # 비공개 포함 admin weather card
GET    /v1/admin/features/{feature_id}/price           # 비공개 포함 admin price card
POST   /v1/admin/features                              # ✅#317 단건 생성(K-15)
PATCH  /v1/admin/features/{feature_id}                 # ✅#317 수정
DELETE /v1/admin/features/{feature_id}                 # ✅#317 soft delete
POST   /v1/admin/features/{feature_id}/deactivate      # 비활성(kill-switch)
POST   /v1/admin/features/change-requests/{request_id}/approve   # ✅#317
POST   /v1/admin/features/change-requests/{request_id}/reject    # ✅#317
GET    /v1/admin/features/change-requests              # 변경요청 큐(T-215b UI 대상)
GET/POST /v1/admin/offline-uploads  (+ {upload_id}[/preview|/validate|/validation|/load])
DELETE /v1/admin/offline-uploads/{upload_id}           # ✅#397 정리 lifecycle(진행중 409·객체 best-effort 삭제)
GET    /v1/admin/poi-cache-targets
GET/PUT/DELETE /v1/admin/poi-cache-targets/{external_system}/{target_key}  # 복합 자연키 + ETag/If-Match 삭제
# T-214f 결정: POI cache target write(PUT/DELETE)는 admin/operator flow 전용.
# PinVi 직접 write 미허용 — service-safe /v1/poi-cache-targets/* write 경로 안 둠.
# PinVi는 등록된 target 기준 read(GET /v1/features/nearby/by-target)만 소비.
GET/POST /v1/admin/backups   GET /v1/admin/backups/{backup_id}
DELETE /v1/admin/backups/{backup_id}                   # 🆕 정리 lifecycle
POST   /v1/admin/restore/{backup_id}[/swap]            # kill-switch
GET    /v1/admin/features/dedup-reviews   PATCH /v1/admin/features/dedup-reviews/{review_id}        # 🔁 복수+param
GET    /v1/admin/features/enrichment-reviews   PATCH /v1/admin/features/enrichment-reviews/{review_id} # 🔁
GET    /v1/admin/issues   GET/PATCH /v1/admin/issues/{issue_id}                  # 🔁 noun 일치

GET    /v1/admin/curations                              # collection 목록/필터
POST   /v1/admin/curations                              # theme·title·edition 포함 수동 생성
GET    /v1/admin/curations/{collection_id}              # 미연결 포함 item 전체
PATCH  /v1/admin/curations/{collection_id}              # 제목/회차/상태/공개범위 수정
DELETE /v1/admin/curations/{collection_id}              # collection soft archive
POST   /v1/admin/curations/{collection_id}/items        # Feature 연결 또는 미연결 item 수동 추가
PATCH  /v1/admin/curations/{collection_id}/items/{curation_item_id} # item 부분 수정/Feature 연결 해소
DELETE /v1/admin/curations/{collection_id}/items/{curation_item_id} # item soft archive
GET    /v1/admin/curations/import-template.csv          # UTF-8 BOM CSV 양식 다운로드
POST   /v1/admin/curations/import?dry_run=true|false    # CSV preview/원자적 authoritative replace
```

PATCH/DELETE correction UI는 `GET .../{feature_id}/revision`의 body `row_revision`과 응답 header
`ETag`를 먼저 읽고, 이어서 `GET .../{feature_id}` detail의 `feature.row_revision`과 같을 때만
불변 `CorrectionBasis`를 확정한다. 둘이 다르면 경쟁 갱신이므로 제한 횟수만 다시 읽고 실패 시
쓰기 조작을 닫는다. `ETag`는 따옴표를 포함한 raw header 문자열을 그대로 보존해 `If-Match`로
전달하며 mutation 직전에 revision을 재조회하거나 최신값으로 자동 rebasing하지 않는다.

stale basis의 PATCH/DELETE는 `412 Precondition Failed`다. consumer는 draft를 보존하고 자동
재시도하지 않으며, 운영자의 명시적 reload가 성공한 경우에만 최신 detail과 새 basis로 교체한다.
이 규칙은 기존 REST/OpenAPI request·response schema와 DB schema를 변경하지 않는다.
- **backup/restore 감사 actor**: backup create/delete/restore/swap의 managed-file registry
  event actor는 router body가 아니라 admin BFF 인증에서 얻은 `AdminProxyContext.actor`만
  사용한다. `RestoreSwapRequest`는 실행 계획 필드와 `note`만 받고 `operator`/`actor`를 받지
  않으며 포함하면 `422 VALIDATION_ERROR`다. standalone compose는 destructive enablement를
  기본 `false`로 해석하고 shell/root project interpolation 환경의 명시적 `true`만 허용한다.
  package API `env_file`은 compose opt-in 근거가 아니다. 승인된 Manager production 형상은
  별도 canonical literal `true`와 raw/resolved/runtime attestation을 소유한다(T-VN-H02R, #796).
- **admin 공간·카드 read**: admin 지도는 공개 `/v1/features*`를 재사용하지 않는다.
  `/v1/admin/features/in-bounds`는 `feature.features` base row에서 삭제 전 운영 상태를
  직접 조회하며, `status` 미지정 시 `draft|active|inactive|hidden|broken` 전체를 대상으로 한다.
  반복 `status`를 지정하면 item과 cluster에 동일하게 적용한다. 응답의 `items`와 `clusters`는
  양 mode에서 모두 필수 배열이며 사용하지 않는 쪽을 `[]`로 반환한다. bbox 후보는 point의 `coord`와
  route/area의 exact geometry 교차를 함께 사용하고, cluster 귀속은 저장 canonical 행정코드로
  feature당 한 번만 계산한다. `/weather`와 `/price` admin subresource도 삭제 전 base Feature
  존재 여부를 검사하므로 비공개 Feature를 404로 오분류하지 않되, `deleted_at`·
  `user_deleted_at`·`status=deleted` target은 fail-closed 404로 처리한다. public endpoint와
  `feature.public_features`의 공개 술어는 변경하지 않는다(T-VN-04A, #741).
- **Feature update 감사 actor**: create와 run-now body는 `operator`/`actor` override를
  받지 않으며 포함하면 422다. 저장 `operator`는 인증된 admin proxy의
  `AdminProxyContext.actor`에서만 파생한다. 실행 계획 필드 외에 create body만 `reason`을
  받는다. run-now body는 빈 strict object이며 priority/reason을 바꾸거나 새 요청을 만들지 않고
  기존 canonical job의 최초 `dispatch_requested_at`만 기록한다. queued 재호출과 running 조회는
  같은 request를 `200`으로 반환하고 terminal 상태는 `409`다.
- **target-selector scope**: KMA grid 3종은 `provider_dataset` scope에서만
  `target_grids` 또는 `external_system:<name>`으로 선택한다. 이 pair를
  provider/dataset filter로 지정한 non-direct 요청은 `422`로 거절한다.
  non-direct 요청은 provider 또는 dataset_key filter를 하나 이상 요구해
  source record의 비지원 pair가 worker에서 늦게 실패하는 경로를 차단한다.
- **version 0/1 모델(#317)**: provider 적재=`data_origin='provider', data_version=0`,
  사용자 요청=`'user_request', data_version=1`, `feature.feature_versions` snapshot +
  `ops.feature_change_requests`. `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE=require_review|
  immediate`. provider 재적재는 version 1/ soft delete를 덮거나 되살리지 않는다.
- **큐레이션 수동 입력**: collection 생성은 기존 `theme_id` 또는 inline
  `theme_slug`+`theme_name`+`theme_group` 전체 중 하나를 요구하고 `title`, `edition_key`,
  source/status/visibility/metadata를 받는다. item은 `feature_id` 또는 `place_name` 중 하나가
  필요하다. DB 식별자인 collection/item/theme/source ID는 OpenAPI `uuid`이며 잘못된 값은
  DB까지 보내지 않고 422로 거절한다. 생성·`PATCH`는 active 상태만 받고 보관 전환은
  `DELETE`로 단일화한다. item `POST`는 create-only라 같은 active identity가 있으면 409다.
  item `PATCH`는 모든 표시·관계·상태 필드와 명시적 `feature_id=null`을 지원한다. 표시·
  identity·상태·metadata 같은 non-null 필드의 명시적 `null`은 422이며 주소 hint·item 설명·
  source record와 `feature_id`처럼 계약상 nullable인 필드만 연결 해소할 수 있다.
  `DELETE`는 `status=archived`와 `archived_at`을 기록한다. 같은 `external_item_id`를 여러
  Feature에 연결할 수 있지만, 같은 collection과 `external_item_id`의 연결 행과 미연결 행을
  동시에 두는 것은 422로 거절한다. admin collection 목록도
  `page_size`(기본 200, 최대 500)+`cursor`를 쓰며 status/visibility/theme/edition/provider/
  검색어와 `include_archived`를 지원한다. admin collection 상세는 보관 item까지 모두
  반환하고, admin Feature 상세의 `sources[]`는 entity별 현재 record 전부,
  `curations[]`는 보관되지 않은 collection/item의 연결 membership을 공개 상태와 무관하게
  모두 반환한다.
- **감사 필드 경계**: collection과 item의 `created_by`/`updated_by`는 요청 body/query가
  아니라 인증된 admin proxy context에서 정한다. admin collection/item DTO와 admin
  Feature 상세에는 이 두 필드를 노출하고, public collection/item DTO와 public Feature
  상세에는 노출하지 않는다.
- **CSV import**: UTF-8/BOM, 최대 2 MiB·2,000행·셀 10,000자. 정확한 20개 header는
  `resources/curations/template.csv`와 다운로드 endpoint가 정본이다. `dry_run=true`는
  구조 검증과 Feature 후보뿐 아니라 예상 `inserted`/`updated`/`removed`, 삭제 예정 item
  전체인 `removals[]`(`AdminCurationItemView`)를 반환한다. 형식 오류(`invalid_rows>0`)는
  commit 전체를 막고, 0건/복수 Feature 후보(`unmatched`/`ambiguous`)는
  `unresolved_rows`로 보고하되 공식 item을
  nullable `feature_id`로 저장한다. 이름 후보는 batch query로 찾는다. commit은 파일에
  포함된 collection을 원자적으로 replace하고 `inserted`/`updated`/`removed`를 반환하므로
  삭제·A→B·연결↔미연결 변경을 반영한다. 같은 파일을 다시 올리면 세 변경 수가 모두 0이고
  collection/theme/source/item의 `updated_at`도 불필요하게 바꾸지 않는다. 동시 import는
  transaction advisory lock으로 직렬화하고 대상 collection row lock을 UUID 순서로 잡는다.
  후보 해소 뒤 같은 source item이 연결·미연결로 섞이거나 같은 membership이 중복되면
  dry-run 행 오류로 표시하고 commit 전체를 422로 막는다. commit의 `removals[]`는 사전
  preview가 아니라 lock 안의 실제 `DELETE ... RETURNING` 결과이므로 `removed`와 항상 같다.

### 2.6 `/v1/ops/*` — 옵저버빌리티
```
GET  /v1/ops/health-deep · metrics · consistency/{reports,issues}
GET  /v1/ops/system-logs · api-call-logs
GET  /v1/ops/datasets · datasets/detail
PUT  /v1/ops/datasets/refresh-policy
POST /v1/ops/datasets/preview                        # fixture-only, 외부 호출 budget 0
GET  /v1/ops/pipeline/overview · executions · events · dagster-runs · schedules
GET  /v1/ops/pipeline/executions                     # root 목록 + current cancellation summary
GET  /v1/ops/pipeline/executions/{kind}/{execution_id}
                                                      # root 상세 + current member/run 결과
POST /v1/ops/pipeline/executions/import_job/{execution_id}/cancel
POST /v1/ops/pipeline/executions/update_request/{execution_id}/cancel
                                                      # root 계층 취소(kind=import_job|update_request)
POST /v1/ops/pipeline/requests                        # 필수 UUID Idempotency-Key; 생성(201)/재생·활성 재사용(200)
POST /v1/ops/pipeline/requests/preview                # 비영속 실행 계획 미리보기(200)
POST /v1/ops/pipeline/requests/{request_id}/run-now   # 동일 canonical job 우선 dispatch(200)
WS   /v1/ops/live                                    # admin UI 실시간 invalidation 채널(WebSocket)
```

Dagster 실행·스케줄 조작, import job/event, 갱신 요청, provider 상태·정책은 위 두
canonical 그룹만 사용한다. C6B clean-cut 이후 `/ops/dagster*`, `/ops/import-jobs*`,
`/ops/import-job-events`, `/ops/providers*`, `/admin/features/update-requests*`,
`/admin/provider-refresh-policies*`는 존재하지 않는다.

`GET /v1/ops/{metrics,health-deep,system-logs,api-call-logs,consistency/*}`는
canonical 조작 표면과 동일하게 trusted admin BFF 또는 read token과 `ops:read` scope의
AND 결합만 허용한다. service token, cancel token, headerless 요청은 권한을 얻지 못한다.
OpenAPI full profile은 각 GET에 `AdminBFF OR (OpsToken AND OpsScope)`를 선언하고 user
profile에서는 ops 전체를 제외한다. PinVi 관측 consumer는 issue #392에서 같은 read
principal을 선전환하며, Map/PinVi exact heads는 C6c manifest v4의 동일 source pair로만
활성화한다.

`POST /v1/ops/pipeline/requests`의 응답에는 서로 다른 두 멱등성 결과를 항상 함께 둔다.
`idempotent_replay`는 동일 `Idempotency-Key` 요청 재생 여부이고,
`reused_active_request`는 새 key로 제출한 계획이 이미 실행 중인 같은 canonical 계획을
재사용했는지 여부다. 따라서 두 필드는 서로 대체하지 않는다. 같은 인증 actor namespace에서
같은 key의 body가 최초 요청과 다르면 기존 결과를 반환하지 않고
`409 FEATURE_UPDATE_IDEMPOTENCY_CONFLICT`로 거절한다. 다른 actor의 동일 key는 별도 요청이다.

- **Canonical provider operation(T-ADM-C3e, #679)**: schedule/manual/sensor/backfill
  feature-load는 Dagster run당 `import_job` root 한 건과 exact provider/dataset pair child로
  영속한다. correlation은 `(kind,id)`이고 `dagster_run_id`나 GraphQL 응답을 목록 cursor로
  쓰지 않는다. pipeline overview/timeline, datasets grid latest, datasets detail recent는 같은 C3b
  lineage/root projection을 소비한다. overview의 `operations_by_status`, `active_operations`,
  `failed_operations_24h`도 raw member가 아니라 canonical root를 한 번만 센다. provider와
  dataset filter를 함께 주면 같은 child pair가
  두 값을 모두 만족해야 하며 독립 배열의 cross-product는 금지한다.
- **Execution 응답 어휘**: root와 pair child lifecycle은 각각
  `queued|running|done|failed|cancelled`, C3d cancellation workflow/result, raw Dagster status,
  freshness, `trigger_kind`는 별도 필드다. `provider_datasets[]`는 exact pair와 nullable selected
  `sync_scope`, non-null selected member id와 status를 보존한다. feature-load run의
  `projected_job`은 root 자체로 고정하고 pair별 상태는 이 배열에서만 읽는다. datasets coverage는
  `db_recorded_canonical_operations`다. grid/detail은 같은 DB snapshot에서 가장 최근 terminal
  `latest_execution`과 queued/running 우선 `active_execution`을 따로 계산한다. 따라서 더 최신
  terminal root가 있어도 기존 active root를 가리지 않는다. detail의 `run_history`는
  `{items,next_cursor,canonical_url}`이고 URL은 `provider`·`dataset_key`·`sync_scope`를 함께 전달하며,
  일반 dataset과 orphan 기본 state는 선택 scope·typed `dataset_wide`·NULL pair를 같은 이력으로
  이어 간다. `sync_scope`만 단독으로 pipeline 목록에 전달하는 요청은 422다.
  상세 계약은 `docs/architecture/openapi-admin-contract.md` §7.2.1이다.
  raw status 필드명은 nullable `dagster_run_status`이며 engine create/start/finish 시각을 응답
  시각으로 사용한다. root progress는 완료 pair 비율, exact SUCCESS는 100이고 partial
  failure/cancel은 완료 비율을 보존한다.
- **Provider dataset scope 갱신(T-ADM-C45X-B, #686)**: request JSON의 nullable
  `sync_scope`는 운영자가 보낸 requested 값만 보존하고, 실제 실행 identity는 연결 canonical
  job의 non-null `effective_sync_scope`다. 일반 dataset은 명시 scope를 거부하고
  `dataset_wide`, KMA grid 3종은 기본 `target_grids` 또는 활성 target이 있는
  `external_system:<exact-name>`만 허용한다. 생성 응답은 `requested_sync_scope`,
  `effective_sync_scope`, `reused_active_request`를 함께 반환한다. 같은
  provider/dataset/effective scope의 queued/running 요청은 계획이 완전히 같을 때만 `200`으로
  재사용하고 priority/operator/reason/policy 등이 다르면 기존 request 링크를 포함한 `409`다.
  `/v1/ops/datasets`의 `catalog.scope_refresh`가 selector/effect/default/allowed scopes/reason을
  서버 정본으로 제공한다. KMA runner는 선택 scope의 active target만
  조회하고 target/grid membership fingerprint와 base cursor가 둘 다 같을 때만
  skip한다. `target_grids`와 `external_system:*` 모두 target 해석·격자 dedupe·상한 적용 뒤
  유효 격자가 0개면 `KmaWeatherTargetScopeEmptyError`로 operation을 실패시킨다. 이
  preflight 실패는 provider 호출·적재와 `provider_sync_state` 생성/수정 없이 canonical
  operation의 terminal failure만 남긴다. credential 확인·provider module import·public client
  생성은 target read → grid mapping/dedupe → cap → empty 판정 및 cursor skip 뒤에만 수행한다.
  terminal 전이와 같은 transaction에 구조화 event code `kma.target_scope_empty`를 정확히 1건
  기록하고, `/v1/ops/pipeline/executions/update_request/{request_id}`의 `events[].code`와
  `/v1/ops/datasets/detail`의 `event_history.items[].code`에 그대로 노출한다. terminal 재실행은 기존
  operation/event를 재사용한다. 격자 상한을 넘으면 provider I/O 전 전체 실패하여 partial cursor
  전진을 금지하고, 실패 카운터는 provider transaction rollback 후 별도
  transaction으로 영속한다. 일반 provider 실패는 성공 writer와 같은 `default` state
  namespace에 기록하고, KMA grid 3종만 선택된 effective scope를 state namespace로 사용한다.
  정규 schedule asset도 `kma_weather_client_factory`를 받아 target mapping/dedupe/cap/empty와
  cursor skip 뒤에 동기 생성하며, close 실패가 기존 typed failure나 cancellation을 덮지 않는다.
- **Dataset exact-scope event 이력(AUD-686/C7B-API)**:
  `/v1/ops/datasets/detail`의 `event_history`는
  `{items,next_cursor,canonical_url}`을 반환하고 각 item은 non-null `sync_scope`를 가진다.
  `GET /v1/ops/pipeline/events`는 `provider`·`dataset_key`와 함께 nullable `sync_scope` filter를
  받고 각 event에 nullable effective scope를 반환한다. scope 조건은 ORDER/LIMIT 전에 적용한다.
  migration 0057부터 event의 canonical effective scope는 typed `ops.import_job_events.sync_scope`
  열과 partial access index가 정본이다. run/event cursor에는 모든 filter fingerprint를 묶어 다른
  job/level/provider/dataset/scope에서 재사용하면 422로 거절한다. API scope는
  `dataset_wide|target_grids|external_system:<exact-name>`만 허용하며 내부 state namespace
  `default`는 URL에 노출하지 않는다. `dataset_key`는 provider namespace 안의 값이므로
  provider 없는 dataset-only event filter도 422로 거절한다.
- **Pipeline 계층 취소(T-ADM-C3d, #680)**: body는 최대 500자의 nullable `reason`만 허용한다.
  `operator`/`actor`를 포함한 알 수 없는 필드는 422이며, actor는 admin 인증의
  `AdminProxyContext.actor`에서만 파생한다. `import_job`이 request branch 안에 있으면
  request root로 canonicalize하고, request owner branch/duplicate non-owner request/
  standalone 미소유 partition/nested request 경계는
  `docs/architecture/data-model.md` §9.8.1과 동일하다.
- **조회 overlay**: executions 목록과 상세의 root에는 nullable
  `cancellation {cancellation_id,status,requested_at,requested_by,reason,retryable,
  unresolved_member_count}`를 싣는다. current attempt는 active attempt 우선, 없으면 최신
  attempt다. 이 overlay와 상세 결과는 cancellation 테이블만 읽는 DB-only projection이며
  조회 시 Dagster를 호출하지 않는다. root/request/projected job의 base `status`는 그대로 두며
  cancellation status로 덮지 않는다. 상세의 cancellation은 current attempt `members[]`와
  `dagster_runs[]`도 포함하므로 502/503 뒤 reload해도 대상별 결과와 오류가 보존된다.
  member 결과가 `cancel_failed`여도 attempt `status='retryable'`이면 transient 외부 실패라
  재시도 action을 활성화하고, `status='failed'`이면 권위 있는 reconcile 불가라
  비활성화한다. attempt status는 workflow의
  `in_progress`/`retryable`/`completed`/`failed`이고, 실제
  `cancelled`/`already_terminal`/`cancel_failed`는 member/run `result`에만 나타난다.
- **응답 정본**: 200 `data`는 `cancellation_id`, `previous_cancellation_id`, canonical
  `root {kind,id}`, attempt `status`, `members[]`, `dagster_runs[]`,
  `committed_data_rolled_back:false`, `warnings[]`를 반환한다. 각 member/run은
  member는 canonical import job을 가리키는 `job_id`, nullable `operation_kind`,
  `requires_run_termination`, nullable `dagster_run_id`, `initial_status`,
  `result`(`pending`/`cancelled`/`already_terminal`/`cancel_failed`), `terminal_status`, nullable
  structured `error`를 갖는다. run은 `dagster_run_id`, nullable `initial_status`, nullable
  `termination_reserved_at`, 같은 `result`/`terminal_status`/`error`를 갖고, Dagster 첫 조회가 실패한 run의
  `initial_status`는 null이다. root가 terminal이어도 active descendant가 있으면 root 결과만
  `already_terminal`로 두고 descendant 취소를 계속한다.
  이미 commit된 scope 데이터와 외부 provider 효과는 rollback하지 않으며 이 사실을
  boolean과 warning으로 항상 드러낸다. cancel action의 200은 attempt
  `status='completed'`이고 모든 member/run result가 `cancelled`/`already_terminal`, 즉
  `pending`/`cancel_failed`가 하나도 없을 때만 허용한다.
- **실행 순서**: 짧은 DB transaction에서 frozen scope·정규화 member/run·base marker와
  durable audit를 먼저 commit한 뒤 transaction 밖에서 Dagster terminate를 호출한다.
  preliminary canonical resolve 뒤 전용 `AsyncConnection`으로 canonical root별 nonblocking
  coordinator lease를 먼저 획득·commit하고, 그 다음 marker/audit prepare transaction을 시작한다.
  lease 획득 전 attempt/marker 생성은 금지하며 lease connection은 exact unlock까지 물리적으로
  pin하되 외부 phase에서는 열린 transaction을 유지하지 않는다.
  lease 경합은 `409 PIPELINE_CANCELLATION_IN_PROGRESS`로 반환한다. lease 획득 뒤 남아 있는
  `in_progress` attempt는 crash 복구로 재개한다. active run은 외부 호출 전에
  `termination_reserved_at` NULL CAS·첫 권위 `initial_status`·audit를 같은 transaction에
  commit하며, CAS 패자는 외부 mutation을 호출하지 않는다. 이미 값이 있으면 같은 attempt에서
  `terminateRun`을 재호출하지 않고 terminal poll만 수행한다. 이 경계는 attempt별 at-most-once
  dispatch를 보장한다. mutation HTTP timeout이나 응답 유실도 같은 attempt에서 재호출하지 않고
  terminal poll을 먼저 수행한 뒤에만 retryable 여부를 정한다. 반대로 명시적인 HTTP status
  오류나 해석 가능한 GraphQL/protocol 거절은 dispatch 불명으로 바꾸지 않고 원래 502 원인을
  즉시 보존한다. poll까지 실패한 응답 유실도 최초 transport 원인을 detail에 유지한다.
  취소 snapshot과 child attach/enqueue는 같은 canonical root transaction lock을 공유한다.
  terminal 재조회 뒤 같은 attempt/marker/run임을 확인한 짧은 transaction에서만 base
  상태를 확정한다. marker로 claim이 차단된 generic queued member는 DB CAS로 `cancelled`다.
  단, C3e의 feature-load kind이면서 non-NULL `dagster_run_id`를 가진 queued member는 run-backed
  active로 분류해 같은 run을 한 번 reserve/terminate하고 authoritative `CANCELED` 확인 뒤
  `cancelled`로 확정한다. QUEUED→STARTED 경쟁도 같은 poll 경로로 처리한다. running member는
  `CANCELED` 확인 때만 `cancelled`다. 권위 있는 `SUCCESS`/`FAILURE`는 정확한
  member-run mapping일 때만 `done`/`failed`로 reconcile한다. 종료 확인 전이나 terminate
  실패 때 running member를 `cancelled`로 반환하거나 기록하지 않는다.
- **no-op/멱등성**: terminal root에 active descendant가 없고 취소 이력이 없으면
  `already_terminal` member와 `status='completed'`인 durable attempt를 새로 만들고 200을
  반환하며 Dagster를 호출하지 않는다. marker와 최신 `status='completed'` attempt가 이미 있으면
  새 attempt/audit을 만들지 않고 같은 member/run 결과를 200으로 replay하며 terminate도
  재호출하지 않는다. 최신 retryable attempt는 no-op보다 먼저 미해결 frozen member만
  재시도하고, terminal root 아래 active descendant가 있으면 일반 취소를 계속한다.
- **재시도**: retryable 응답의 `details.cancellation_id`를 기준으로 같은 action을 다시
  호출한다. 서버는 이전 frozen scope의 미해결 member만 새 attempt로 복사하며 hierarchy를
  다시 탐색하지 않는다. 같은 Dagster run은 attempt당 한 번만 terminate한다. marker는
  terminal 뒤에도 durable하게 남아 worker claim/write와 새 descendant 생성을 막고, retry
  CAS만 이전 attempt id를 새 id로 바꾼다.
  `termination_reserved_at` commit 직후 실제 HTTP 전 crash가 난 run은 orphan attempt에서
  poll만 한 뒤 미종결이면 `DAGSTER_TERMINATION_TIMEOUT` retryable·503으로 닫고, 다음 attempt에서
  새 dispatch 기회를 얻는다.
- **오류**: root 부재는 404 `PIPELINE_EXECUTION_NOT_FOUND`, 동시 active attempt는 409
  `PIPELINE_CANCELLATION_IN_PROGRESS`, Dagster run id가 없는 active local job이나
  marker/run mapping 불일치처럼 안전하게 중단을 증명할 수 없는 경우는 409
  `PIPELINE_CANCELLATION_UNSAFE`다. GraphQL protocol 오류·`TerminateRunFailure`·
  `RunNotFound`는 502 `DAGSTER_TERMINATE_FAILED`, 연결 불가/timeout은 503
  `DAGSTER_UNAVAILABLE`/`DAGSTER_TERMINATION_TIMEOUT`이다. 모든 오류는
  `application/problem+json`이고, retry 가능한 502/503과 concurrent 409에는
  `Retry-After`를 포함한다. 세 공개 cancellation operation의 OpenAPI 409/502/503 response
  header에도 optional integer seconds로 선언하며 admin generated type과 browser error 객체가
  RFC7807 본문·재시도 초를 보존한다. Next same-origin BFF는 response header allowlist에
  `Retry-After`를 포함하되 임의 upstream header는 전달하지 않는다. 409/502/503도 durable
  attempt/marker를 기록할 수 있으므로 UI는 성공 여부와 무관하게 root 목록/detail을
  invalidate하고 다시 읽는다. 오류 응답에서 연결 member를 알 수 없으면 import job detail/event와
  feature update request detail의 singular query-key prefix 전체를 무효화한다. lease loser는
  winner의 prepare commit을 짧게 bounded DB-only
  reload하며, current attempt가 보이면 `details.cancellation_id`/미해결 member/run을 포함한다.
  bounded reload 뒤에도 pre-marker winner라 current attempt가 보이지 않으면 409 details는 canonical
  `root`와 `cancellation:null`을 명시한다. GET detail의
  in-progress overlay와 5xx `details.members[]`/`dagster_runs[]`는 같은 result enum을
  사용하므로 `pending`을 반환할 수 있다. 실패 attempt와 대상별 error는 응답 전에 영속되며
  marker는 유지된다.
- **mutator 차단**: pipeline cancellation은 reason-only body와 endpoint의
  `AdminProxyContext.actor`, 단일 coordinator/DTO/error adapter를 사용한다. direct
  `cancel_import_job`/`cancel_update_request`를 호출하지 않는다. main-library
  `AsyncKorTravelMapClient.cancel_update_request`는 Dagster HTTP 경계가 아니므로 marker-guarded
  low-level API로만 남고 REST coordinator로 사용하지 않는다.
  cancel/requeue, payload update, stale recovery, batch/load-batch attach를 포함한 모든 base
  status·payload·lineage mutation은 marker guard를 적용하며 event/system audit append만
  허용한다. 따라서 구 endpoint나 내부 repository 호출로 marker를 우회해 상태를 바꿀 수
  없다.

- **`WS /v1/ops/live`(ops_live.py)**: admin frontend의 TanStack Query invalidation signal
  전용 WebSocket. 로그인 session을 검증한 same-origin `POST /api/auth/live-ticket`이
  60초 signed ticket을 발급하고, browser는 이를 `Sec-WebSocket-Protocol`로 보내며 FastAPI는
  운영 data 전송 전에 HMAC 검증과 DB nonce 원자 소비를 끝낸다. 서명/인증 실패는
  data 없는 최소 handshake 뒤 `4401`, handshake 전 signed-expired ticket은 data 0건 +
  `4408`로 닫는다. 이미 frame을 보낸 연결의 lease 만료도 `4408`이지만 data 0건 계약은
  적용되지 않는다. frontend는 healthy 전 `4408`을 backoff 실패로, 중복 없는 exact topic set
  구독 ack 뒤 v1·단조 sequence·요청 topic·revision·object data 검증을 통과한 frame을 받은
  healthy 연결의 `4408`만 즉시 lease rotation으로 처리한다. wire topic 배열 순서는 의미가
  없으며 형식 오류는 watchdog을 갱신하지 않고 socket 폐기 + `standby` 재연결로 전환한다.
  ticket fetch,
  handshake, heartbeat watchdog이 silent network failure에서도 active 실행 polling과
  background reconnect를 유지하고, 3회 연속 실패부터 inactive grid/detail도 REST polling
  fallback으로 전환한다. BFF는 `Origin`과
  `Sec-Fetch-Site: same-origin`을 모두 요구한다. secret·ticket은 query string에 두지 않는다.
  초기 topic은 빈 집합이며 query `topics`는 받지 않고 client command JSON
  (`subscribe`/`unsubscribe`/`replace`)으로 구독하고, topic별 snapshot revision 변화만
  push한다(연결 직후 topic은 빈 집합이며 `replace`로 구독. base topic =
  `import_jobs`/`feature_update_requests`/`offline_uploads`/`dagster_runs`/`provider_sync`/
  `dataset_projection`/`dagster_schedules`, `import_job_events:{job_id}` 등 prefix topic 지원).
  DB resource id는
  canonical UUID, `dagster_run:{run_id}`는 trim한 비어 있지 않은 255자 이하 opaque id다.
  topic은 JSON 문자열 배열이므로 comma가 든 run ID도 그대로 보존한다.
  Dagster id는 ASCII로 제한하지 않고 C0 control만 거절한다. WebSocket이라
  `provider_sync`/`dataset_projection`/`dagster_schedules` 변경 감지는 source transaction과
  함께 증가하는 `ops.ops_live_topic_revisions` statement-trigger clock을 snapshot에 포함해
  timestamp/MAX tail 동률과 늦은 commit을 놓치지 않는다. `dataset_projection`은
  `ops.data_integrity_violations`와 `ops.poi_cache_targets` 변경을 포괄한다.
  생성 `openapi.json` `paths`에는 **포함되지 않으며**
  (REST DTO 정본은 위 `/v1/ops/*` endpoint), 본 §2.6와 `docs/architecture/openapi-admin-contract.md`
  §`WS /ops/live`가 산문 계약 정본이다. 인증·상태·무효화 adapter 상세는
  `docs/reports/admin-ops-c7a-live-contract-2026-07-17.md`를 따른다.

### 2.7 `/v1/debug/*`
```
GET /v1/debug/mois-license/{license_id}
✅ /debug/health · /debug/version 제거됨(T-214h, clean cut). 상태확인은 /health·/version·
   /v1/ops/health-deep로 수렴. dataset preview는 `/v1/ops/datasets/preview` fixture-only다.
```
MOIS route는 원본 provider payload를 포함하므로 `local-dev`에서
`debug_routes_enabled=true`일 때만 mount하고, mount 뒤에도 trusted admin BFF를 요구한다.
production은 `debug_routes_enabled=false`를 기동 조건으로 강제해 route 자체가 없으며,
debug token·legacy header·경로 alias는 제공하지 않는다.

`GET /v1/curated-features*`, `/v1/curated-sources`, `/v1/curated-themes`를 포함한 모든
public-keyed operation은 같은 `require_public_api_key` 경계다. production keyless 요청은
401이고 public key 또는 service principal만 public OpenAPI 계약에 선언한다. trusted admin
BFF의 내부 우회는 기존 same-origin UI 동작을 위한 runtime 경계이며 user OpenAPI principal로
노출하지 않는다.
- **action sub-resource 규약(ADR-048 #8)**: 부수효과 상태전이는 `POST {col}/{id}/{verb}`
  (`deactivate`/`cancel`/`run-now`/`approve`/`reject`/`load`/`validate`/`swap`), 순수 수정은
  `PATCH {id}`, 생성 `POST {col}`, 조회 `GET`. 신규 action도 같은 형태로 확장.

---

## 3. 데이터 계약 핵심

| 항목 | 정본 | 비고 |
|------|------|------|
| feature_id | `f_{bjd\|global}_{kind[0]}_{sha1[:16]}` 문자열 | UUID 아님. **값 불변식**(아래) |
| 표시명 | `name`(not `title`) | |
| 좌표(목록) | 평면 `lon`/`lat`(cross-repo 정본, ADR-048 #10) | PinVi DEC-07도 `lon`/`lat`로 정렬 |
| 주소 | 구조화 `address`+`*_code` | |
| category | 8자리 코드 + `/v1/categories` label | |
| 날씨 | metric 목록 + `forecast_style` | |
| provider 관측 | Feature 상세 `observations[]`; entity별 현재 record, 별도 history cursor | payload version을 Feature link로 중복하지 않음 |
| 큐레이션 | Feature 상세 `curations[]`; collection 상세는 nullable `feature_id` item 포함 | theme/title/edition/source를 membership마다 완전 보존 |
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
모델링한다. 소비자(PinVi)가 FK·snapshot 키로 영속화하므로 값 안정성을 계약으로 보장.

### 3.3 envelope 불변식 (안정성, ADR-048 #12)
- `meta`는 **모든 응답에 항상 present**(단건 GET 포함). 성공 `meta`/에러 problem+json 모두
  `request_id`를 싣는다.
- `meta.page.next_cursor`는 **항상 키로 존재**, 소진 시 `null`(omit 금지) — 페이지 종료 신호.
- in-bounds의 `cluster_unit`처럼 payload 해석에 필요한 view metadata는 `data`가 아니라
  `meta.cluster`에 둔다. `data`는 `items`/`clusters` 같은 실제 payload만 담는다.

---

## 4. 표준 에러 코드
`FEATURE_NOT_FOUND`(404) · `INVALID_BBOX`(422) · `TOO_MANY_IDS`(422) · `VALIDATION_ERROR`(422) ·
`FEATURE_SEARCH_CURSOR_INVALID`(422) · `FEATURE_SEARCH_CURSOR_VERSION_UNSUPPORTED`(422) ·
`FEATURE_SEARCH_CURSOR_TAMPERED`(422) · `CURSOR_QUERY_MISMATCH`(422)
· `RATE_LIMITED`(429) · `LOCK_BUSY`(409,`Retry-After:15`) · `DESTRUCTIVE_DISABLED`(403) ·
`UNAUTHORIZED`(401) · `UPSTREAM_UNAVAILABLE`(503) ·
`PIPELINE_EXECUTION_NOT_FOUND`(404) · `PIPELINE_CANCELLATION_IN_PROGRESS`(409) ·
`PIPELINE_CANCELLATION_UNSAFE`(409) · `DAGSTER_TERMINATE_FAILED`(502) ·
`DAGSTER_UNAVAILABLE`(503) · `DAGSTER_TERMINATION_TIMEOUT`(503).

### 4.1 표준 헤더 규약 (T-214g)
| 헤더 | 방향 | 의미 | 상태 |
|------|------|------|------|
| `X-Request-ID` | 응답(전체) | 요청 상관추적. `meta.request_id`/problem+json `request_id`와 동일 | **구현됨** |
| `Retry-After` | 응답(429/409/502/503) | rate limit·lock 경합·pipeline 취소 재시도 지연(초). LOCK_BUSY=15 | **부분 구현**(LOCK_BUSY, pipeline은 T-ADM-C3d) |
| `Idempotency-Key` | 요청(변경 POST) | endpoint별 멱등 key. `/ops/pipeline/requests`는 actor-scoped UUID 필수이며 같은 actor+body만 재생 | **구현됨** |
| `RateLimit-Limit`/`RateLimit-Remaining`/`RateLimit-Reset` | 응답(429) | rate limit 상태 | 규약(구현 T-216) |
| `Deprecation`/`Sunset` | 응답 | GA 후 `/v1`→`/v2` 전환 예고(ADR-048 #13). pre-1.0 clean cut에선 미사용 | 규약(GA 후) |

에러 본문은 RFC 7807 `application/problem+json`(§1.5), 머신 코드는 위 enum을 확장 `code`로.

---

## 5. 변경 이력: 구 형태 → 현행 (ADR-048 delta; T-216a~g + #317 모두 적용 완료)
> 아래 "구 형태" 열은 **이미 폐기된 과거 상태**다(T-216a~g·#317로 "현행" 열로 전환 완료).
> 신규 소비자는 "현행" 열만 계약으로 본다 — 구 `limit`/CSV-bbox/`count`/`state` 형태는 더는 응답에 없다.

| 구 형태(폐기) | 현행 | 종류 |
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
| 좌표 `lon`/`lat` ↔ PinVi `longitude`/`latitude` | `lon`/`lat`로 cross-repo 정렬 | 🔁 #10 |
| `{issue_id}`/`{review_id}` | `{issue_id}`/`{review_id}`, `*-reviews` 복수 | 🔁 |
| `{error:{…}}` | problem+json(`code`/`request_id` 확장) | 🔁 |
| `/debug/health`·`/debug/version` | 제거(clean cut) | 🔁 |
| 2개 계약 doc | `rest-api.md` 단일 정본으로 통합 | ✅ 단일화 |
| `/tripmate/feature-update-requests*` | `/admin/*` | ✅#317 |
| `POST /tripmate/features/batch` | `POST /features/batch`(ServiceToken) | ✅ `/tripmate` namespace 제거 |
| `POST /admin/features` 등 add/edit/delete | (구현됨) | ✅#317 K-15 |

---

## 6. 미해결 / 결정 로그
- **K-15(단건 add API)**: #317로 `POST /admin/features` 구현 → 해소. PinVi T-179 의존 풀림.
- **DEC-05**: 재적재(admin)와 사용자 제안(PinVi→승인→`/admin/features`) 분리(확정).
- **정본 수렴(T-216g)**: 본 문서가 전 표면 단일 계약 정본이다(ADR-048 #9). 구 소비 매핑 view 문서는 제거됐다.
- **Batch 응답 키**: `items`는 list array 전용으로 고정하고, batch id-keyed map은 `found`로
  둔다(PinVi 3차 리뷰 반영).
- **codegen(T-210e)**: `/v1` 안정 commit에서 진행.
- **PinVi T-130 공개 뷰**: 해수욕장/축제 공개 뷰는
  `docs/architecture/public-views-api.md`와 `openapi.user.json`을 따른다(T-222b).
- **curated_features**: 테마형 큐레이션 후보는
  `docs/curated-features.md`와 `openapi.user.json`을 따른다(T-223c-1 read 표면).
- **curation collections**: 신규 공식·수동 목록은 ADR-063의 `/v1/curations*` 계약을
  사용한다. 구 source-rule 후보 계약은 유지하지만 서로 다른 회차 정보를 대표 1행으로
  접는 용도로 사용하지 않는다.

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

## 8. 이관된 결정 (구 ADR)

도메인/process/운영 성격이라 ADR에서 빼고 본 REST API 정본으로 이관한 결정들이다.

- **OpenAPI export 정책 — 첫 라우터부터 활성화 + 이원 drift gate** (구 ADR-031): FastAPI 첫
  라우터 등장 PR부터 `packages/kor-travel-map-api/openapi.json`(admin profile)과
  `openapi.user.json`(사용자 profile)을 저장소에 커밋하고, `scripts/export_openapi.py
  --profile all --check`를 `.github/workflows/openapi.yml` CI drift gate로 돌린다. 라우터/DTO
  변경 PR은 반드시 openapi diff를 동반(누락 시 CI fail)하므로, 라우터 변경의 외부 효과(frontend
  type·외부 도구)가 PR diff에서 즉시 가시화되고 frontend 도입 시 type drift 부담이 0이 된다.
  메인 라이브러리 `kortravelmap`은 FastAPI 미의존(ADR-020)이라 본 정책은 항상 api/admin 패키지
  한정이다.
- **OpenAPI 이원화 + SemVer 버저닝** (구 ADR-031, ADR-045 D-3 amendment): API가 admin과
  사용자(공개) 양쪽에 서비스되므로 OpenAPI를 admin schema(`/admin`·`/ops`·`/debug`·`/features`
  admin 뷰)와 사용자 schema(`/features` 공개 뷰)로 별도 export + 별도 drift gate(CI 2개)한다.
  spec 버저닝은 SemVer(필드 추가=minor / 제거·의미변경=major), 변경은 CHANGELOG `### API`
  섹션에 기록하고 frontend client는 `openapi-typescript` codegen으로 생성한다. (기계 정본 우선순위는
  §0 헤더 참조 — 충돌 시 OpenAPI 우선.)
- **외부 사용자 feature 제안 = 기존 admin change API 재사용(신규 수신 endpoint 미신설)** (구
  ADR-051): 외부 소비자의 검토된 feature 추가/수정/삭제 제안은 별도 `suggestions` API를 만들지
  않고 기존 `/v1/admin/features*` change API(#317, §2.5)를 수신 구간으로 재사용한다 — 별도 수신
  API는 #317 설계와 기능 중복이라 철회했다. 수신된 제안은 `change-requests` 큐로 들어가
  `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE`(기본 `require_review`)에 따라 운영자 최종
  승인 또는 immediate 적용된다(DEC-05, §6과 동일 결정). 동작 합의 5건(T-217c, 코드 실측 기반):
  멱등은 `make_feature_id(source_type="user_request", source_natural_key=idempotency_key)`로
  결정적 feature_id 생성(같은 key 재시도 = 같은 feature_id), 출처 태깅은 전용 필드 없이
  `operator` 고정 + `reason` 머리에 `[suggestion:<ref_id>]` prefix(D-11 익명 — 불투명 참조 ID만
  저장, 개인정보 비저장), admin 인증은 12701 `/v1/admin/*`의 `admin_destructive_enabled`
  kill-switch + 인프라 SSO/IP allowlist(§1.3), closure는 영구 폐업/사용자 삭제 = soft `DELETE`
  (provider 재적재 부활 차단, #332) / 일시 중단 = `POST .../deactivate`(§2.5)다. 거절/반려는
  change-request `request_id`/`status`로 노출되어 외부 소비자가 폴링 조회한다.

---

## 9. 변경 이력
- 2026-07-13: ADR-063에 따라 Feature provider entity/current observation과 immutable
  history를 분리하고, collection/item 큐레이션 public/admin API·수동 입력·CSV
  preview/commit 계약을 추가했다. Feature 단건/batch/admin 상세는 모든 현재 관측과
  연결 큐레이션 membership을 배열로 반환한다.
- 2026-06-09: #317(T-214/T-215) `/v1` 1차 정리 위에 ADR-048(admin/ops versioning 확장 +
  envelope/pagination/parameter/response 정합성 표준 + 코드/DB 명명 전파)을 반영.
- 2026-06-09(2차, #316 무-호환 재검토): 외부 read 동결 carve-out 제거, envelope
  페이지네이션을 `meta.page`로 분리(`data`=payload만, `count` 폐기), dual-support 제거 →
  `/v1` clean cut + `/debug/health|version` 제거, action sub-resource 규약, 단일 정본 수렴.
- 2026-06-09(3차, #316 PinVi 재리뷰 A–F 반영): (B) 좌표명 cross-repo 정렬 = `lon`/`lat`
  (ADR-048 #10), (C) **`cluster_key`는 행정코드 자연키라 유지**(2차 `cluster_id` 철회),
  (D) `feature_id` **값 불변식** 명문화(§3.2), (E) envelope 불변식 lock(§3.3 — `meta` 항상
  present·`request_id`·`next_cursor` null-not-omit), (F) `/vN` major 거버넌스(§1.2, #13).
  실행 T-216a~g.
- 2026-06-09(4차, #316 PinVi 3차 잔여 반영): batch id-keyed map은 `items`가 아니라
  `found`로 분리하고, in-bounds `cluster_unit`은 payload에서 `meta.cluster.cluster_unit`로 이동.
  base URL은 host root만 포함하고 path가 `/v1`를 명시한다고 고정.
