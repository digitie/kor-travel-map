# ADR-034: Provider 구현 순서 — MOIS-독립 먼저, MOIS bulk, MOIS-sibling 후

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: 사용자 (구현 순서 명시) + claude (Sprint 매핑)
- **컨텍스트**: 본 라이브러리는 14+ provider를 적재한다. provider별 구현
  순서가 정해져 있지 않으면 dedup 룰 검증이 흐트러진다. 특히 `python-mois-api`
  의 인허가 데이터는 **가장 큰 bulk** (195 슬러그 × 시군구 다수)이고, 산림청
  휴양림/수목원·표준데이터 박물관/미술관 등과 **카테고리/슬러그 중복**이
  많다. MOIS를 먼저 적재하고 다른 provider를 들이면 `dedup_review_queue`가
  폭증 + Record Linkage 가중치 검증이 large dataset에서 시작 → 디버깅 비용
  ↑.

  사용자가 다음 구현 순서를 명시:
  > 축제 → 날씨 → 유가 → 휴게소 → 국립공원/트래킹코스
  >   (인허가와 무관한 정보들)
  > → 국가유산 → **MOIS 인허가** → 수목원/휴양림 → 박물관/미술관

  핵심 통찰: MOIS-독립 provider를 먼저 적재해 dedup 룰을 작은 dataset에서
  검증 → MOIS bulk 진입 시점에 정합성 게이트가 안정 → MOIS-sibling provider
  (휴양림/수목원/박물관 — MOIS와 중복 가능)는 이미 검증된 룰로 진입.

- **결정**:

  **9단계 구현 순서** (Sprint 2~5 매핑):

  | 순서 | provider / source | Feature.kind | 적재 단계 (Sprint) | MOIS와 dedup 가능성 |
  |------|------------------|--------------|------------------|---------------------|
  | 1 | 축제 (`python-visitkorea-api`) | event | Sprint 2 | 없음 (event는 PROMOTED 슬러그 없음) |
  | 2 | 날씨 (`python-kma-api`) | weather | Sprint 2 | 없음 |
  | 3 | 유가 (`python-opinet-api`) | place + price | Sprint 2 | 없음 (주유소 ≠ MOIS 슬러그) |
  | 4 | 휴게소 (`python-krex-api`) | place + price + weather + notice | Sprint 2 | 없음 (휴게소 ≠ MOIS 슬러그) |
  | 5 | 국립공원/트래킹 (`python-knps-api`) | area + route + place + notice + weather | Sprint 3 | 없음 (KNPS area/route는 MOIS 슬러그와 무관) |
  | 6 | 국가유산 (`python-krheritage-api`) | place + area + event | Sprint 3 | **부분** (사찰/한옥은 MOIS `hanok_experience` 등과 sibling 가능 — Sprint 3 시점엔 MOIS 미적재라 dedup queue 미발생) |
  | 7 | **MOIS 인허가** (`python-mois-api`) | place (대량) | Sprint 4 | (자기 자신) — 4단계 lifecycle, dedup 룰 본격 검증 |
  | 8 | 휴양림/수목원 (`python-krforest-api`) | place + area | Sprint 5 | **있음** (휴양림 = MOIS `condo_resorts`/`tourist_accommodations` sibling, 수목원 = MOIS `botanical_gardens` sibling) |
  | 9 | 박물관/미술관 (`data.go.kr-standard`) | place | Sprint 5 | **있음** (`standard_museums` ≅ MOIS `museums_art_galleries`) |

  **MOIS 외 보조 dataset도 위 순서를 따른다**:
  - `python-khoa-api` (해수욕장 + 해양공지) — Sprint 2 (날씨와 같이, MOIS sibling 약함)
  - `python-airkorea-api` (대기질) — Sprint 2 (날씨와 같이)
  - `python-krairport-api` (공항) — Sprint 3 (krex와 같이, MOIS와 중복 없음)
  - `python-krforest-api` 산악기상 — Sprint 2 (날씨), 산악 trails는 Sprint 3 (knps와 같이)
  - `python-knps-api` 시설(visitor_centers/restrooms/cultural_resources) — Sprint 3 (area와 같이, MOIS 약한 중복 → 시점상 무관)
  - `data.go.kr-standard` 관광지/주차장/관광길/문화축제 — Sprint 5 (박물관과 같이)
  - `place_phone_enrichment` (Kakao Local / NAVER / Google Places) — Sprint 4~5 백그라운드 (MOIS 적재 후 전화번호 보강)

- **근거**:
  - **dedup 룰 검증 순서**: 작은 dataset (축제 < 100k, 유가 ~12k, 휴게소
    ~200, 국립공원 22개 + 탐방로 ~수천)에서 Record Linkage scoring(ADR-016
    가중치 0.45/0.35/0.20)을 먼저 검증. MOIS bulk(수십만~수백만 row) 진입
    시점에는 룰이 이미 stable.
  - **dedup_review_queue 폭증 회피**: MOIS를 먼저 적재하면 후속 provider
    들어올 때 *모든* MOIS row와 새 row를 비교 → queue 폭증. MOIS를 마지막에
    적재하면 후속 provider가 없으므로 queue 안정.
  - **정합성 게이트 (ADR-033) 적용 시점 정렬**: F1~F3 (Sprint 3 도입)는 작은
    dataset에서 검증, F4 (dedup_review 미해소) / F7 (dedup score 회귀)는
    MOIS 진입 시점에 의미 있는 baseline 확보 후 작동.
  - **MOIS sibling provider (8/9)는 MOIS 이후**: MOIS가 먼저 들어가 있어야
    `LODGING_RECREATION_FOREST` / `LODGING_HOTEL` / `TOURISM_BOTANICAL` /
    `01.04.01 박물관` 슬러그에 대한 dedup 비교가 자연. MOIS가 sibling을
    primary로 가져가고, 이후 다른 provider가 enrichment/추가 정보로 join.
  - **사용자 도메인 지식 반영**: 사용자가 한국 관광 API 생태계를 잘 알고
    9단계를 명시 → 본 라이브러리 운영 직관과 일치.

- **결과 (긍정)**:
  - dedup 룰 디버깅이 작은 dataset에서 → MOIS 진입 시점에는 black-box
    문제로만 다룰 수 있음.
  - 각 Sprint별 산출물이 명확 (Sprint 2 = 작은 provider 4개, Sprint 3 = 중간
    + 정합성 Phase 1, Sprint 4 = MOIS bulk, Sprint 5 = sibling + 운영 진입).
  - Sprint 5 운영 진입 시점에 전체 14+ provider가 들어와 있음 → SLO 측정
    baseline 확보.

- **결과 (부정)**:
  - 사용자/TripMate 입장에서 "박물관/미술관"이 가장 흔한 카테고리인데 마지막
    Sprint까지 미적재 → demo/PoC에 미흡. 완화: Sprint 2 끝에 `data.go.kr-
    standard` 박물관만 *임시 sample* 1~2건 manual fixture로 디버그 UI에
    시연 가능하게.
  - MOIS Sprint 4가 다른 어떤 Sprint보다 무겁다 (bulk + 4단계 lifecycle +
    dedup queue 운영 시작) → 일정 risk 큼. 완화: Sprint 4를 길게 잡거나
    Sprint 4a/4b로 분할 (4a = Step A bulk + Step B incremental, 4b = Step C
    closed + Step D detail + dedup queue 운영).

- **후속**:
  - `docs/sprints/SPRINT-2.md` ~ `SPRINT-5.md` 신설 (본 PR#14) — 9단계
    순서를 Sprint 진입 조건/산출물/DoD에 박음.
  - `docs/sprints/SPRINT-1.md` §"비목표" 갱신 — "provider 호출"이 Sprint 2
    부터인 점 명확화.
  - `docs/architecture/dagster-boundary.md §5` asset 명명 표 — Sprint별로 그룹화 가능.
  - `docs/test-strategy.md` §4 통합 테스트 매트릭스 — provider별 fixture가
    위 순서로 추가됨.
  - T-018 Sprint 매핑 명확화 — `kortravelmap.providers.knps`는 Sprint 3,
    `kortravelmap.providers.mois`는 Sprint 4, `kortravelmap.providers.krforest`
    (휴양림/수목원) + standard_data는 Sprint 5.
  - Sprint 4 분할 여부는 Sprint 3 종료 시점에 진척도 보고 결정.
