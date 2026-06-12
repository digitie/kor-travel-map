# 서비스 완성도·정합성 종합 검토 — krtour-map · TripMate · tripmate-agent (2026-06-10)

> **상태 (2026-06-10 갱신)**: 검토 보고서 — 의사결정 D-01~13 전 항목 종결, 결정분은
> 정본 반영 완료 (ADR-050~052, tasks T-217a~g, TripMate/tripmate-agent 측 문서).
> 결정 이력은 [`decisions-needed-2026-06-10.md`](decisions-needed-2026-06-10.md) 참조.
> **검토 기준 커밋**:
> - python-krtour-map `origin/main` `0e45bd7` (T-216 REST naming + TripMate-agent provider)
> - TripMate `origin/main` `4a10a5b` (#149 공유 trip 읽기전용 뷰)
> - tripmate-agent `origin/main` `a443ca0` (#55 PostgreSQL/PostGIS + YouTube source 정규화)
>
> **검토 원칙**: 최소변경·호환성 확보보다 **안정성·확장성·일관성·완결성·성능** 우선
> (krtour ADR-046 "호환 shim 금지"와 동일 철학). 형제 레포는 stale 함정 회피를 위해
> origin/main 임시 워크트리로 실측했다.
>
> **연관 문서**: 액션 플랜 [`consistency-uplift-plan-2026-06-10.md`](consistency-uplift-plan-2026-06-10.md) ·
> 의사결정 [`decisions-needed-2026-06-10.md`](decisions-needed-2026-06-10.md) ·
> TripMate 측 반영 항목 [`tripmate-side-actions-2026-06-10.md`](tripmate-side-actions-2026-06-10.md) ·
> tripmate-agent 측 반영 항목은 해당 repo `docs/cross-repo-consistency-actions-2026-06-10.md`.

---

## 1. 시스템 목적·데이터 흐름·R&R 지도

세 시스템의 문서(각 repo CLAUDE.md/AGENTS.md/decisions.md/architecture.md)를 종합하면
역할 분담은 아래와 같고, **R&R 자체는 세 레포 문서가 모두 같은 그림을 그리고 있다**
(좋은 상태). 문제는 그 그림의 **구현 도달도와 계약 세부의 drift**다.

```
[공공 API 9단계 provider]──┐
                           ▼
[tripmate-agent] ──(REST export: /api/v1/krtour/features/{snapshot|changes})──▶ [python-krtour-map]
  YouTube 수집·Gemini POI 추출·     ▲ pull (krtour Dagster fetcher, X-API-Key)    Feature 정본 owner
  지오코딩·후보 검수(자체 UI/MCP)   │                                             feature_id 생성·dedup·
                                    │                                             정합성·PostGIS 조회
                                    │                                                  │
                                    │                       (OpenAPI :12301, /v1, {data,meta} envelope)
                                    │                                                  ▼
[TripMate] ◀──(사용자 UX: trip 계획·POI 첨부·feature_snapshot 캐시·공유·협업)── [TripMate api :9021]
```

- **krtour-map** = feature **owner**: 정규화·`make_feature_id`·dedup/merge·정합성 게이트·
  공간 조회. 외부 경계는 OpenAPI(:12301)뿐 (ADR-045).
- **tripmate-agent** = 후보 **provider**: YouTube → 장소 후보 추출·검수. DB에 FeatureBundle을
  직접 쓰지 않고 export API만 제공 (tripmate-agent `docs/youtube-feature-pipeline-plan.md` §2.3, krtour ADR-049).
- **TripMate** = feature **consumer**: `trip_day_pois.feature_id TEXT` + `feature_snapshot JSONB`
  캐시, FK 없음. feature 편집은 하지 않고 krtour admin flow로 위임
  (krtour `docs/tripmate-rest-api.md` §2 "운영 feature 추가/수정/삭제 → TripMate public client 직접 호출 금지").

**결론**: R&R 설계는 건전하고 세 레포 합의가 명확하다. 단 §5의 4건(RustFS 버킷 소유권,
사용자 제보 릴레이, tombstone 라이프사이클, 계약 정본 위치)은 경계가 미정의/침범 상태다.

---

## 2. 사용자 UX 검토 (TripMate 관점, 기획자 시각)

### 2.1 사용 시나리오별 도달도

| 시나리오 | TripMate 구현 | krtour-map 준비도 | 판정 |
|---|---|---|---|
| 회원가입/로그인/프로필 (Google OAuth, PIPA) | ✅ | — | 완료 |
| trip 생성/메타 편집/복사/삭제/목록 | ✅ (#147~#148) | — | 완료 |
| 공유 읽기전용 뷰 (`/shared/[tripId]/[token]`) | ✅ (#149) | — | 완료 (단, feature proxy 권한 경로 점검 필요 → TM-09) |
| **지도에서 장소 탐색 (viewport in-bounds)** | ⚠️ 라우터가 구모델 stub(`etl_bridge`)에 묶여 503 | ✅ `GET /v1/features/in-bounds` (cluster, max_items≤2000) | **P0 갭** |
| **장소 검색 (q/bbox)** | ⚠️ 미배선 | ✅ `GET /v1/features/search` | **P0 갭** |
| **주변 장소 (nearby)** | ⚠️ 미배선 | ✅ `GET /v1/features/nearby` (+`/by-target`) | P1 갭 |
| **POI 상세/배치 조회 (trip 화면)** | ⚠️ 신규 HTTP client는 있으나 응답 필드 불일치(§4 C-1) | ✅ `POST /v1/features/batch` (ServiceToken, cap 200) | **P0 갭** |
| 날씨 카드 | ⚠️ 미배선 | ✅ `GET /v1/features/{id}/weather` | P1 갭 |
| 실시간 협업 (WebSocket presence/충돌) | 설계만 (Sprint 5) | — | 계획대로 |
| 추천 여행 템플릿 (curated plan) | ✅ 목록/복제 | feature_id 참조 모델 합의됨 | 완료 |
| YouTube 발 장소를 계획에 추가 | ⚠️ 출처 표시 UX 없음 | ✅ provider `tripmate-agent-youtube` (marker P-13) | P1 갭 (아래 2.2-b) |

핵심 판정: **TripMate의 사용자 가치 사슬에서 "장소 데이터" 구간 전체가 미배선**이다.
중요한 것은 TripMate 내부 감사 문서(`docs/audit/2026-06-06-doc-impl-audit.md` DEC-01,
`docs/krtour-map-integration.md` L7~16)가 그 원인을 "krtour-map에 HTTP 표면이 없다
(debug-ui 8087뿐)"로 기술하고 있는데, **이 전제는 2026-06-10 현재 사실이 아니다** —
krtour-map은 :12301 `/v1` 61개 엔드포인트 + OpenAPI 기계 정본 + ServiceToken까지 완비했다.
즉 TripMate의 P0 갭은 외부 블로커가 아니라 **자기 문서 노후로 인한 착시 + 배선 작업
잔여**다. (→ TripMate DEC-01 폐기, `tripmate-side-actions` TM-04)

### 2.2 누락 — 추가해야 할 사용자 UX와 구현 위치

각 항목에 "어디까지 어느 시스템에서 구현해야 하는지"를 명시한다.

**(a) P0 — feature 데이터 배선 완결** (TripMate 내부만으로 충분, krtour 추가 작업 불필요)
- `/features/in-bounds·search·nearby·{id}·{id}/weather` 라우터를
  `apps/api/app/clients/krtour_map.py`(신규 httpx client)로 재배선. 구 `etl_bridge` stub
  (`apps/api/app/api/v1/features.py:1-12`의 ADR-002 잔재 docstring 포함) 제거.
- DTO 매핑 재작성: krtour 응답은 평면 `lon`/`lat`(ADR-048 #10)인데 TripMate 매핑은
  중첩 `dto["coord"]["longitude"]`를 기대 (`features.py:80`). cluster 매핑도 동일 계열.

**(b) P1 — 장소 "출처/신뢰도" 표시 UX** (TripMate UI + krtour 응답 필드 확인)
- YouTube 발 후보 feature가 공공데이터 feature와 같은 지도에 노출된다. 사용자에게
  "이 장소는 OO 영상에서 추출됨(영상 링크, 타임스탬프)"을 보여주는 배지/카드가 없으면
  신뢰도 구분이 불가능하다. tripmate-agent export에는 `youtube.video_url`,
  `evidence.timestamp_*`, `confidence_score`가 이미 있다
  (`docs/youtube-feature-pipeline-plan.md` §7.1).
- 구현 분담: **krtour-map** — feature detail(`detail`/`urls`/`raw_refs`)에 영상 근거가
  소비 가능한 형태로 노출되는지 확인·보강(KR-06). **TripMate** — 상세 카드에 출처 배지 +
  영상 링크 UI(TM-06). **tripmate-agent** — 추가 작업 없음(이미 공급).
- 노출 정책 자체(검수 전 후보를 사용자에게 보일지)는 의사결정 D-05.

**(c) P1 — kind별 카드 UX 정의** (TripMate 내부)
- krtour는 7-kind(place/event/notice/price/weather/route/area)를 공급하는데 TripMate
  화면 정의는 place 중심이다. event(축제 기간), price(유가), notice(교통 공지),
  route(트래킹 라인) 표시 방식이 기획 문서에 없다. 최소한 v0.1 범위에서 "표시하는
  kind 화이트리스트"라도 명시 필요.

**(d) P2 — 성능 UX** (TripMate 내부)
- viewport 이동마다 in-bounds 호출 → TanStack Query 캐시 + 디바운스 + zoom별
  `cluster_unit` 활용 정책. krtour는 cap(2000)과 cluster 응답으로 이미 준비됨.

### 2.3 빼야 할/축소할 부분 (TripMate)

- **`/admin/features` 편집 기능(placeholder)**: feature 쓰기는 krtour-map admin의 책임이며
  krtour 문서가 "TripMate public client의 `/v1/admin/features*` 직접 호출 금지"를 명시한다
  (`docs/tripmate-rest-api.md` §2). TripMate admin은 **read-only 조회 + 갱신요청 릴레이**로
  축소 권고. (→ D-06)
- **`/admin/etl`, `/admin/seed`, `/admin/reset` placeholder**: `apps/etl` 레거시 Dagster는
  krtour T-210c에서 이관/삭제 추적 중. placeholder 페이지는 혼동만 유발 — 제거 권고.
- **`/admin/category-mapping`**: 카테고리 정본은 krtour `GET /v1/categories`(8자리 코드).
  TripMate에 별도 매핑 관리 화면을 두면 정본이 둘이 된다 — 제거하거나 read-only 뷰로.

---

## 3. Admin UX 검토 (krtour-map 운용 관점, 개발리더 시각)

### 3.1 현황 — 양호

admin UI 15페이지 + API 61 엔드포인트로 운영 표면(feature CRUD/change-request 승인,
이슈 큐, dedup/enrichment 검수, offline upload, 갱신요청 큐, 백업/restore/swap,
Dagster 관제, 정합성 리포트, import job, 로그)이 일관된 envelope/cursor 규약 아래
갖춰져 있다. ADR-048 정합성 표준이 실제 코드에 반영됐음을 확인했다.

### 3.2 누락/보완 (우선순위순)

| # | 항목 | 내용 | 근거 |
|---|---|---|---|
| A-1 | **tombstone/reject 라이프사이클 처리** | `tripmate_agent_items_to_bundles()`가 `operation != upsert`를 건너뛰기만 함 (`src/krtour/map/providers/tripmate_agent.py:76,87`). tripmate-agent에서 검수 철회(reject)·폐기(tombstone)된 후보가 krtour feature로 **영구 잔존**. MOIS Step C(폐업→inactive)와 동형의 비활성 경로 필요 | 완결성 결함, D-03 |
| A-2 | **provider 동기화 대시보드** | `GET /v1/providers/{provider}/last-sync`는 단건뿐. 20+ provider×dataset의 last-sync/실패를 한눈에 보는 목록 API+admin 화면 부재. Dagster 페이지가 run 단위라 "데이터 신선도" 관점이 없음 | 운영 가시성 |
| A-3 | **tripmate-agent 후보 provenance 가시성** | admin features에서 provider=`tripmate-agent-youtube` 필터로 조회는 가능하나, 영상 근거(원본 링크·confidence)를 보여주는 칸과 tripmate-agent 검수 UI로의 cross-link 부재. 운영자가 "이 후보 왜 들어왔나"를 추적하려면 두 시스템을 수동 왕복 | 운영 동선 |
| A-4 | **feature 단건 화면의 merge history** | `feature_merge_history`(alembic 0007)가 API/화면에 노출되는지 불명확. dedup 사고 조사 시 필수 | 감사 추적 |
| A-5 | admin 지도 시각화 | 이슈/후보를 지도 위에서 보는 화면 (백로그 외) | 보조적 |

### 3.3 빼야 할 부분

- 없음. `/v1/debug/*`는 이미 비노출 정책이며 T-214h에서 구 `/debug/health|version`
  clean cut 완료 — 유지.

---

## 4. API 계약 정합성 — 불일치 전수 (코드 재검증 완료)

| ID | 심각도 | 불일치 | 공급자 측 근거 | 소비자 측 근거 | 수정 방향 |
|---|---|---|---|---|---|
| C-1 | 🔴 | batch 응답 id-keyed map 필드명: krtour `found` vs TripMate가 `items` 파싱 → 모든 POI 상세가 **조용히 missing 처리** | krtour `routers/features.py` batch(`{found, missing}`), `docs/rest-api.md` §"목록 data={items}, map={found}" | TripMate `apps/api/app/clients/krtour_map.py:196` `data.get("items")`; `docs/integrations/krtour-map-rest-api.md:109` | **TripMate 수정** (`found`). ADR-048 명명이 정본 |
| C-2 | 🔴 | TripMate feature 라우터가 구모델(라이브러리 직접 호출, ADR-002) stub에 배선 — 신규 HTTP client 미사용, DTO도 구 라이브러리 모양(`coord.longitude` 중첩) | krtour 응답 평면 `lon`/`lat` (`FeatureSummary`, ADR-048 #10) | TripMate `apps/api/app/api/v1/features.py:1-12` docstring "ADR-002", `:80` `dto["coord"]["longitude"]`, `etl_bridge` 항상 None | **TripMate 재배선** + 매핑 재작성 |
| C-3 | 🔴 | TripMate 문서가 "krtour HTTP 표면 미존재(debug-ui 8087, `/tripmate/features/batch` 없음)"로 현실 차단 (DEC-01) — **노후 전제**. krtour는 :12301 `/v1` 완비 | krtour `docs/rest-api.md`(2026-06-10), `openapi.json` | TripMate `docs/krtour-map-integration.md:7-16`, `docs/audit/2026-06-06-doc-impl-audit.md` §2 | **TripMate 문서 갱신**, DEC-01 폐기 |
| C-4 | 🔴 | tripmate-agent export 엔드포인트 `GET /api/v1/krtour/features/{snapshot\|changes}` — krtour fetcher는 구현 완료, **tripmate-agent backend 미구현(T-066 대기)** | krtour `packages/krtour-map-dagster/.../provider_fetchers.py:63-124` (X-API-Key, `{items,has_more,next_cursor}`) | tripmate-agent `backend/app/api/routes.py`에 `/krtour` 라우트 없음; 계약 스펙은 `docs/youtube-feature-pipeline-plan.md` §7 (정확히 일치) | **tripmate-agent T-066 구현** (계약 스펙·krtour fetcher 기대치 이미 정렬됨 — 순서 의존일 뿐 충돌 아님) |
| C-5 | 🟡 | in-bounds 페이지 cap 파라미터: krtour `max_items`(≤2000) vs TripMate client가 `limit` 전송 → FastAPI가 무시, **cap 지정이 조용히 no-op** | krtour `routers/features.py:419` `max_items` | TripMate `clients/krtour_map.py` `features_in_bounds()` `params["limit"]` | **TripMate 수정** (`max_items`) |
| C-6 | 🟡 | TripMate 통합 문서의 경로/필드 표기 노후: `/tripmate/features/batch`(제거된 namespace), batch `items` 등 | krtour `docs/tripmate-rest-api.md` §1 "`/tripmate/*` namespace 제거됨" | TripMate `docs/integrations/krtour-map-rest-api.md` | **TripMate 문서 재작성** — krtour `docs/rest-api.md`+`openapi.user.json`을 정본으로 명시 |
| C-7 | 🟡 | client docstring/반환값이 `{"items": ...}`로 wrapper 내부 명명 — API 명명(`found`)과 혼선 | — | TripMate `clients/krtour_map.py:187,202` | TripMate 내부 정리 (C-1과 함께) |
| C-8 | 🟡 | `meta.cluster.cluster_unit`은 cluster 경로에서만 존재 — 소비자는 optional 취급 필수 | krtour `routers/features.py:342-359` | TripMate 매핑 미작성 (C-2에서 흡수) | TripMate 매핑 시 optional 처리 |
| C-9 | ⚪ | 인증 방식 이원화: krtour `X-Krtour-Service-Token`(batch) vs tripmate-agent `X-API-Key` | 각 repo 정책 문서 | — | 통일 불요(시스템별 정책), 단 cross-repo 문서에 한 표로 명시 (KR-04) |
| C-10 | ⚪ | envelope 3종: krtour `{data,meta}`+RFC7807 / tripmate-agent export `{items,has_more,next_cursor}` 무-envelope / TripMate 자체 `Envelope` | 각 코드 | — | 통일 비권장(공용 read vs 내부 export vs 자체 표면) — 결정 D-08로 명문화 |

> **재독 보정 (2026-06-10, 2차)**: TripMate `docs/integrations/krtour-map-rest-api.md`
> (2026-06-08~09 갱신)를 재정독한 결과 위 표의 뉘앙스를 보정한다.
> ① **C-3 축소**: "krtour HTTP 미존재" 전제는 `docs/krtour-map-integration.md` 경고
> 블록·audit 문서에만 남은 잔재이고, TripMate DEC-01은 이미 (B)로 확정(2026-06-08)
> 됐으며 integrations 문서는 "krtour 구축 완료, 공은 TripMate"를 기록하고 있다.
> 남은 갱신 대상은 그 잔재 블록 + "krtour T-216 미머지라 T-181 대기" 전제(이제 머지됨
> — **대기 해제**)다. ② **C-1/C-5는 TripMate가 이미 자체 식별·추적 중**(T-181 잔여 —
> batch `found`는 TripMate 3차 검토가 제안해 krtour가 수용한 것). 결함이 아니라
> lockstep 대기 항목이었다. ③ **C-2의 라우터 재배선도 T-172~T-176으로 추적 중**.
> ④ 신규 발견: TripMate의 "admin base = 12305" 가정은 **실오류**(12305는 admin UI,
> admin API는 12301 `/v1/admin/*`). ⑤ §5 R-2의 2차 보정은 ADR-051 참조(신규 API 철회,
> 기존 #317 change API 승인).

**bbox/좌표 순서**(min_lon,min_lat,max_lon,max_lat 분리 4-float, lon-first)는 양측 정합 확인.
batch chunk(200) = krtour cap(200), retry/backoff + Retry-After 존중, fetcher의
cursor 무한루프 가드(`next_cursor == cursor` 검출)도 확인 — 이 부분 설계 품질은 좋다.

---

## 5. R&R 검토 — 경계가 미정의/침범인 4건

| ID | 사안 | 현황 | 평가 |
|---|---|---|---|
| R-1 | **RustFS 버킷 소유권** | tripmate-agent가 미디어 원본(영상/자막/전사/프레임)을 **krtour-map 소유 버킷**(`RUSTFS_BUCKET_*=krtour-map`, prefix `features/`)에 직접 저장 (tripmate-agent `config.py`) | 경계 침범 소지. krtour rustfs는 "선택" 구성요소이고 offline upload 용도인데, 타 시스템의 무기한 보존 미디어가 같은 버킷에 들어가면 백업/복원·수명주기·용량 관리 책임이 모호해짐 → **D-01** |
| R-2 | **사용자 장소 제보 릴레이** | TripMate에 `FeatureSuggestion` 모델/일일limit까지 있으나(`features.py:48`), krtour `admin/features/change-requests`로 흘러가는 공식 경로 없음 | 갭. 옵션: ① 운영자 수동 ② TripMate api가 krtour admin API 호출(관리망 인증 필요 — 권장 안 함) ③ krtour에 서비스용 suggestion 수신 API 신설 → **D-02** |

> **R-2 보정 (2026-06-10, 사용자 확인)**: "공식 경로 없음"은 과대 기술. 설계는 **2단
> 검토**로 이미 존재 — TripMate 사용자 요청(추가/수정/삭제) → TripMate admin 1차 검토
> (`/admin/feature-requests` 큐) → krtour-map admin 최종 반영(`/v1/admin/features*`·
> `/v1/admin/feature-update-requests*`, krtour `docs/tripmate-rest-api.md` §2 "제안
> 원본은 TripMate app DB 소유, 운영자 승인 후 전달"). 실제 갭은 **1차 승인분의 자동
> 전송 구간**인데, 2차 재독 결과 그 구간도 krtour PR #317 admin feature change API +
> TripMate DEC-05/T-179/T-180으로 **이미 설계·구현돼 있었다** — ADR-051은 신규 API
> 신설 없이 이 기존 흐름을 공식 승인하고 잔여 합의 5건만 T-217c로 확정한다.
| R-3 | **후보 철회 라이프사이클** | reject/tombstone을 krtour가 skip (§3.2 A-1) — "후보 검수 권한은 tripmate-agent, feature 생명주기는 krtour" 합의의 마지막 고리 누락 | krtour 측 비활성 경로 구현 필요 → **D-03** |
| R-4 | **export 계약 정본 위치** | 계약 전문이 tripmate-agent `docs/youtube-feature-pipeline-plan.md` §7(계획 문서)에만 존재. krtour 측은 ADR-049 + fetcher 코드 | 계획 문서는 계약 정본으로 부적합(완료 후 동결·이동됨). 정본 1곳 + 상대 repo는 링크 → **D-04** |

적절하게 배치된 것들(변경 불요): feature_id 생성·dedup·정합성=krtour / YouTube 후보
검수 UI·MCP=tripmate-agent / 일출일몰(KASI)·예산·협업=TripMate / geocoding —
tripmate-agent의 VWorld/Kakao/Naver 후보 지오코딩과 krtour 변환부의 kraddr-geo
reverse 재검증은 "후보 제안 vs 정본 확정"으로 역할이 달라 중복이 아님(단 문서에 1줄 명시 권장, KR-05).

---

## 6. 문서 정합성

### 6.1 repo별

- **krtour-map**: 가장 건강. 2026-06-06 docs-consistency-audit 이후 drift 방지 체계
  (resume/tasks 정본화, CLAUDE.md에 가변값 배제)가 작동 중. 경미 2건 —
  CLAUDE.md에 REST 버전 거버넌스(GA 후 `/v2` N-1) 1줄 부재, architecture.md 포트 미기재.
- **TripMate**: **노후가 P0 갭의 직접 원인**. ① `docs/krtour-map-integration.md`와
  audit 문서의 "krtour HTTP 미존재" 전제(C-3) ② `docs/integrations/krtour-map-rest-api.md`의
  제거된 경로/필드(C-6) ③ 코드 docstring의 ADR-002 잔재(C-2) ④ OAuth 3종/Kakao Maps
  잔재(자체 T-143~149로 추적 중) — ①②③은 즉시 갱신 대상.
- **tripmate-agent**: 일관성 양호(ADR-1~26, T-001~062 정렬). 누락: TripMate 소비 계약
  상세(T-068 범위), category 매핑 기준(T-065), 계약 정본 선언(R-4).

### 6.2 cross-repo

- 세 시스템의 포트·역할·연동 방식을 한 장에 담은 **통합 지도 문서가 없다**. 각 repo가
  자기 관점 단편만 보유 → 이번처럼 한쪽 갱신(krtour /v1 완비)이 타 repo 전제(DEC-01)에
  전파되지 않는 사고가 구조적으로 재발한다. → uplift-plan §4 "cross-repo 연동 정본
  + 분기별 상호 검증" 제안.
- 외부 추적 task의 짝이 안 맞는 곳: krtour T-210b~e(TripMate 외부 추적)는 있으나
  TripMate 백로그에 대응 항목 미확인 — TripMate 측 task 등록 필요(TM-13).

---

## 7. 안정성·확장성·성능 관전 포인트

1. **fetcher live 전환 검증**: T-066 완료 후 krtour Dagster live fetch의 cursor 영속
   (`provider_sync_state`)·재시도·부분 실패 시 멱등성 smoke가 필요 (uplift-plan M3).
2. **TripMate 지도 부하**: krtour T-212d(read≫write 전제 MV 검토)와 TripMate 실사용
   패턴(뷰포트 이동 빈도)이 같은 가정을 공유하는지 — TripMate 배선 후 실측 1회 권장.
3. **batch 경로의 N+1 회피**: trip 화면은 batch(≤200/chunk)로 설계돼 있어 적절.
   feature_snapshot fallback(krtour 5xx 시)도 설계돼 있음 — 배선 시 그대로 유지할 것.
4. **tripmate-agent 쿼터**: YouTube 일일 10k units, source_scan 주기화(T-063 진행 중)와
   krtour pull 주기가 독립이라 충돌 없음 — export는 DB read뿐이므로 쿼터 무관. 양호.

---

## 8. 종합 평가

| 축 | krtour-map | TripMate | tripmate-agent | cross-repo |
|---|---|---|---|---|
| 목적 대비 완결성 | **상** (61 API + 15 admin 화면, 9단계 provider 완주) | **중하** (계정/trip/공유는 완성, 장소 데이터 사슬 미배선) | **중상** (수집~검수 파이프라인 완성, export만 미구현) | — |
| 문서 정합성 | 상 | **하** (P0 갭의 원인) | 상 | 중하 (통합 정본 부재) |
| API 계약 정합성 | 정본 역할 수행 | 🔴 3건(C-1,2,5) | C-4 순서 의존 1건 | C-9,10 명문화 필요 |
| R&R | 적절 | 축소 필요 2건(§2.3) | 적절 | 미정의 4건(§5) |

**한 줄 결론**: 공급자(krtour-map)는 준비가 끝났고, 병목은 ① TripMate의 노후 문서·구모델
잔재 청산과 배선(C-1/2/3/5/6), ② tripmate-agent T-066, ③ 경계 4건의 의사결정(D-01~04)이다.
실행 순서와 세부는 `consistency-uplift-plan-2026-06-10.md` 참조.
