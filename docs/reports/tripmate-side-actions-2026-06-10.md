# TripMate 측 반영 항목 (2026-06-10)

> **상태 (2026-06-10 갱신)**: 의사결정 D-01~13 전 항목 종결. 사용자 지시에 따라
> **TripMate repo에 직접 문서 반영 진행** (TripMate 측 PR — 머지는 사용자 검토 후).
> 본 문서는 kor-travel-map 측 보관본/추적용.
> **기준**: TripMate `origin/main` `4a10a5b`, kor-travel-map `origin/main` `0e45bd7`.
> **근거 상세**: [`service-completeness-review-2026-06-10.md`](service-completeness-review-2026-06-10.md) §2·§4·§6.

kor-travel-map 측 짝 작업은 T-210b~e(`docs/tasks.md` Phase 6)로 이미 추적 중이다. 아래
TM-번호를 TripMate 백로그(task) 체계로 이관해 등록할 것을 권고한다.

> **2026-06-10 재독 보정 — 기존 TripMate task 매핑**: TripMate
> `docs/integrations/kor-travel-map-rest-api.md`(2026-06-08~09 갱신)가 이미 대부분의 항목을
> 자체 task로 추적 중임을 확인했다. 신규 등록이 아니라 **기존 task의 unblock/잔여 마감**
> 으로 처리할 것: TM-01(batch `found`)·TM-02(`max_items`)·TM-03(meta.cluster)은
> **T-181 잔여**(krtour T-216 머지 대기였음 — 0e45bd7로 머지 완료, **대기 해제**),
> TM-06(라우터 재배선)은 **T-172~T-176**, TM-07은 **T-210e codegen + T-181 lockstep**,
> TM-13은 **T-179/T-180**(아래 보정 참조). 순수 신규는 TM-08(출처 배지 UX)·TM-09(kind
> 화이트리스트)·TM-10(공유 뷰 권한)·TM-11(지도 성능 정책)·admin base 12301 정정 정도다.

## A. 즉시 (문서 — 코드 변경 없이 P0 착시 해소)

- **TM-04 — DEC-01 폐기 + krtour 연동 문서 전면 갱신** 🔴
  - `docs/kor-travel-map-integration.md` L7~16의 "kor-travel-map은 운영급 HTTP 표면 미구현
    (debug-ui 8087뿐)" 전제를 삭제. 2026-06-10 현재 kor-travel-map은 :12301 `/v1` 전 표면
    (사용자 read 8종 + admin/ops/debug 계 61 엔드포인트) + `openapi.json`/`openapi.user.json`
    기계 정본 + `X-Kor-Travel-Map-Service-Token`(batch)을 제공한다.
  - `docs/audit/2026-06-06-doc-impl-audit.md`의 DEC-01 항목에 해소 주석 추가.
  - v0.1.0 게이트 결정(DEC-06 "snapshot-only vs 연동 대기")을 재평가 — 외부 블로커가
    사라졌으므로 "연동 후 출시" 옵션의 비용이 크게 줄었다.
    ✅ D-09 **권고안 채택 (2026-06-10)**: "연동 후 출시"로 재평가 진행.
- **TM-05 — `docs/integrations/kor-travel-map-rest-api.md` 재작성** 🔴
  - 제거된 `/tripmate/features/batch` namespace, batch `items` 필드 등 노후 표기를
    krtour `docs/rest-api.md` + `openapi.user.json` 기준으로 교체.
  - 문서 머리에 "정본은 kor-travel-map `docs/rest-api.md`·OpenAPI, 본 문서는 소비 매핑 view"
    를 명시 (krtour `docs/tripmate-rest-api.md`와 거울 구조).

## B. 계약 수정 (코드 — 소규모, 배선 전이라도 선행 가능)

- **TM-01 — batch 응답 필드 `items` → `found`** 🔴
  - `apps/api/app/clients/kor_travel_map.py:196` `data.get("items")` → `data.get("found")`.
    현재는 모든 batch 결과가 조용히 missing 처리된다 (krtour ADR-048: list=`items`,
    id-keyed map=`found`).
  - 같은 파일 `:187` docstring과 `:202` wrapper 반환 키도 `found`로 정렬해 명명 혼선 제거 (구 C-7).
- **TM-02 — in-bounds cap 파라미터 `limit` → `max_items`** 🟡
  - `features_in_bounds()`가 `params["limit"]`를 보내지만 krtour는 `max_items`
    (ge=1, le=2000, 기본 1000)만 받는다 — 현재 cap 지정이 no-op.
- **TM-03 — `meta.cluster` optional 처리** 🟡
  - `meta.cluster.cluster_unit`은 cluster 응답 경로에서만 존재. 매핑 시 optional로.

## C. 배선 (코드 — 사용자 가치 사슬 완결, v0.1.0 게이트)

- **TM-06 — feature 라우터를 신규 HTTP client로 재배선** 🔴
  - `apps/api/app/api/v1/features.py`가 구모델 `app.etl_bridge.kor_travel_map`(항상 None
    stub, docstring에 ADR-002 잔재)에 묶여 있다. `app.clients.kor_travel_map.KorTravelMapClient`
    (lifespan 주입)로 교체하고 `etl_bridge`는 삭제 (krtour ADR-045/TripMate ADR-026 정합,
    호환 shim 금지 철학 동일 적용).
  - DTO 매핑 재작성: krtour 응답은 평면 `lon`/`lat`/`marker_color`/`marker_icon` —
    현재 `_summary_from_dto`/`_cluster_from_dto`는 중첩 `coord.longitude`/`center.longitude`
    를 기대 (`features.py:80, 92`). in-bounds의 `clusters[]/items[]` 분기, `next_cursor`,
    `distance_m`(nearby) 포함해 krtour `openapi.user.json` 기준으로 재정의.
  - 5xx/타임아웃 시 `feature_snapshot` fallback 동작은 설계대로 유지.
- **TM-07 — openapi-typescript / httpx OpenAPI client 도입** (krtour T-210d·e의 짝)
  - krtour T-212e(실데이터 full reload) 후 API shape 안정 시점에 `openapi.user.json`으로
    web/api 클라이언트 타입 생성 — 수기 Zod 스키마와 실계약의 drift 원천 차단.

## D. 사용자 UX 보강 (기획 + 코드)

- **TM-08 — 장소 출처/신뢰도 표시 UX** 🟡
  - YouTube 발 feature(provider `kor-travel-concierge-youtube`, marker P-13)에 출처 배지 +
    영상 링크(+타임스탬프) 카드. 데이터는 krtour feature detail의 `urls`/`detail`로
    공급 예정 (krtour 측 KR-06에서 노출 형태 확정 후 진행).
  - 노출 정책: ✅ D-05 **(a) 확정 (2026-06-10)** — 검수 통과 후보만 export되므로
    TripMate에 도달하는 YouTube feature는 전부 검수 통과분. UI는 출처 표시에 집중하면 됨.
- **TM-09 — kind별 카드 화이트리스트 정의** 🟡
  - krtour 7-kind 중 v0.1에서 표시할 kind와 각 카드 형태(event 기간, price 유가,
    notice 공지, route 라인)를 기획 문서에 명시.
- **TM-10 — 공유 읽기전용 뷰의 feature proxy 권한 점검**
  - `/shared/[tripId]/[token]` 비로그인 흐름에서 TripMate api의 feature proxy가
    share token으로 인가되는지 확인 (krtour 호출 자체는 서버측이므로 ServiceToken 영역).
- **TM-11 — 지도 성능 정책**: in-bounds 디바운스 + TanStack Query 캐시 + zoom별
  `cluster_unit` 활용 기준 명시.

## E. 축소/제거 (R&R 정렬)

- **TM-12 — admin 표면 축소** ✅ D-06 **수정 승인됨 (2026-06-10)**
  - `/admin/features` 편집(placeholder) → read-only 조회 + "krtour admin으로 갱신요청
    릴레이" 동선으로 축소. krtour가 TripMate의 `/v1/admin/features*` 직접 호출을 금지함
    (krtour `docs/tripmate-rest-api.md` §2).
  - **`/admin/etl`은 유지** — TripMate 자체 ETL 관리 로직의 관제 화면으로 존치
    (사용자 결정). ✅ D-13 확인 완료(2026-06-10): 자체 ETL은 **KASI(일출/일몰)류
    TripMate 고유 데이터 잡만** 관리, kor-travel-map 적재와 중복 없음 → T-210c(구
    `apps/etl` krtour 적재 레거시 이관/삭제)와 양립. 화면 범위 = 고유 잡 관제로 확정.
  - `/admin/seed`·`/admin/reset` placeholder 제거.
  - `/admin/category-mapping` 제거 또는 `GET /v1/categories` read-only 뷰로 대체
    (카테고리 정본 이원화 방지).
- **TM-13 — FeatureSuggestion 릴레이 경로** ✅ D-02 확정 + **2차 보정 (2026-06-10 재독)**
  - **신규 수신 API 철회** — TripMate 기존 설계(DEC-05 확정, T-177 완료/T-179/T-180)가
    이미 정답: 사용자 요청 → TripMate admin 1차 검토(`/admin/feature-requests`) →
    승인 시 **krtour `/v1/admin/features*` feature change API**(#317) 호출 →
    krtour change-requests 큐에서 최종 반영. TripMate는 기존 T-179/T-180을 그대로
    진행하면 된다 (ADR-051 보정으로 krtour 측이 이 흐름을 공식 승인).
  - krtour 측 T-217c가 잔여 합의 5건(review_mode/idempotency/출처 태깅/admin 인증/
    closure — TripMate `docs/integrations/kor-travel-map-rest-api.md` §7 질의 목록)을
    확정해 회신 예정.
  - **정정 필요(TripMate 측 오류)**: admin client base를 12305로 가정하나 **12305는
    krtour admin UI(Next.js)**이고 admin **API는 12301 `/v1/admin/*`** — T-180 설계와
    `TRIPMATE_KOR_TRAVEL_MAP_API_BASE_URL` 의미(기본 12305)를 12301 기준으로 재정의.
  - 출처 태깅의 사용자 식별 정보: ✅ D-11 확정 — **익명**, TripMate 측 불투명 참조
    ID(suggestion_id)만 (kor-travel-map 개인정보 비저장, 역추적은 TripMate admin에서).

## F. 추적 체계

- **TM-14 — krtour T-210b~e의 짝 task를 TripMate 백로그에 등록**하고, 본 문서의
  TM-01~13을 TripMate task 번호로 이관. cross-repo 의존(T-066, KR-06, D-02/05/06)을
  task 본문에 명시.
