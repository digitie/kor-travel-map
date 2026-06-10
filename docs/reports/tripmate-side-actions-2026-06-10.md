# TripMate 측 반영 항목 (2026-06-10)

> **상태**: 검토 산출물 — 본 repo(python-krtour-map)에 보관하며, 추후 TripMate repo에서
> 참고·이관한다. TripMate 정본 문서에는 아직 미반영 (사용자 승인 후 반영).
> **기준**: TripMate `origin/main` `4a10a5b`, krtour-map `origin/main` `0e45bd7`.
> **근거 상세**: [`service-completeness-review-2026-06-10.md`](service-completeness-review-2026-06-10.md) §2·§4·§6.

krtour-map 측 짝 작업은 T-210b~e(`docs/tasks.md` Phase 6)로 이미 추적 중이다. 아래
TM-번호를 TripMate 백로그(task) 체계로 이관해 등록할 것을 권고한다.

## A. 즉시 (문서 — 코드 변경 없이 P0 착시 해소)

- **TM-04 — DEC-01 폐기 + krtour 연동 문서 전면 갱신** 🔴
  - `docs/krtour-map-integration.md` L7~16의 "krtour-map은 운영급 HTTP 표면 미구현
    (debug-ui 8087뿐)" 전제를 삭제. 2026-06-10 현재 krtour-map은 :9011 `/v1` 전 표면
    (사용자 read 8종 + admin/ops/debug 계 61 엔드포인트) + `openapi.json`/`openapi.user.json`
    기계 정본 + `X-Krtour-Service-Token`(batch)을 제공한다.
  - `docs/audit/2026-06-06-doc-impl-audit.md`의 DEC-01 항목에 해소 주석 추가.
  - v0.1.0 게이트 결정(DEC-06 "snapshot-only vs 연동 대기")을 재평가 — 외부 블로커가
    사라졌으므로 "연동 후 출시" 옵션의 비용이 크게 줄었다.
    ✅ D-09 **권고안 채택 (2026-06-10)**: "연동 후 출시"로 재평가 진행.
- **TM-05 — `docs/integrations/krtour-map-rest-api.md` 재작성** 🔴
  - 제거된 `/tripmate/features/batch` namespace, batch `items` 필드 등 노후 표기를
    krtour `docs/rest-api.md` + `openapi.user.json` 기준으로 교체.
  - 문서 머리에 "정본은 krtour-map `docs/rest-api.md`·OpenAPI, 본 문서는 소비 매핑 view"
    를 명시 (krtour `docs/tripmate-rest-api.md`와 거울 구조).

## B. 계약 수정 (코드 — 소규모, 배선 전이라도 선행 가능)

- **TM-01 — batch 응답 필드 `items` → `found`** 🔴
  - `apps/api/app/clients/krtour_map.py:196` `data.get("items")` → `data.get("found")`.
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
  - `apps/api/app/api/v1/features.py`가 구모델 `app.etl_bridge.krtour_map`(항상 None
    stub, docstring에 ADR-002 잔재)에 묶여 있다. `app.clients.krtour_map.KrtourMapClient`
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
  - YouTube 발 feature(provider `tripmate-agent-youtube`, marker P-13)에 출처 배지 +
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
    (사용자 결정). 단 "자체 ETL"의 범위가 krtour T-210c(구 `apps/etl` krtour 적재
    레거시 삭제)와 어떻게 갈리는지는 미확인 — D-13 확인 후 화면 범위 확정.
  - `/admin/seed`·`/admin/reset` placeholder 제거.
  - `/admin/category-mapping` 제거 또는 `GET /v1/categories` read-only 뷰로 대체
    (카테고리 정본 이원화 방지).
- **TM-13 — FeatureSuggestion 릴레이 경로** ✅ D-02 **(a) 확정 + 2단 검토 보정 (2026-06-10)**
  - 설계된 2단 검토 유지: 사용자 요청 → **TripMate admin 1차 검토**(`/admin/feature-requests`
    큐 — 기존 화면 유지·강화 대상, 제거 아님) → 1차 **승인분만** krtour 수신 API
    `POST /v1/features/suggestions`(가칭, ADR-051 + T-217c)로 자동 릴레이 → krtour-map
    admin change-requests에서 최종 반영.
  - 릴레이 시점 = TripMate admin 승인 액션 (사용자 제보 발생 시점 아님). krtour 측
    구현 전까지 UI에 "운영 검토 후 반영" 안내 명시.
  - 페이로드의 사용자 식별 정보 범위는 D-11(PIPA) 결정 대기 — 권고는 익명 참조 ID만.
  - krtour 최종 거절의 역방향 통지(TripMate 큐 상태 갱신)는 1차 범위 외 (ADR-051 결과 절).

## F. 추적 체계

- **TM-14 — krtour T-210b~e의 짝 task를 TripMate 백로그에 등록**하고, 본 문서의
  TM-01~13을 TripMate task 번호로 이관. cross-repo 의존(T-066, KR-06, D-02/05/06)을
  task 본문에 명시.
