# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는 [`docs/tasks-done.md`](tasks-done.md),
진척·"다음 한 작업"은 [`docs/resume.md`](resume.md)가 정본. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md).

## 진행 중인 작업 인덱스

- **다음**
  - [ ] `T-MAP-VWORLD-02` — **admin features 지도를 VWorldMapView 기반으로 전환** (#466).
    `digitie/maplibre-vworld-react`의 `VWorldMapView`/React marker 모델을 admin `features`
    지도에 얇게 이식한다. 정본 계획은
    `docs/reports/maplibre-vworld-react-migration-plan-2026-06-17.md`.
  - [ ] `T-MAP-VWORLD-03` — **지도 e2e 라이브 검증 및 후속 수정** (#467). 지도 전환 후
    WSL 서버 + Windows Playwright 흐름으로 지도 e2e를 실행하고 실패를 후속 PR로 수정한다.
  - [ ] `T-229-buildx` — **arm64 multi-arch buildx 배포 검증** (T-229 잔여). T-229의
    나머지(curated 오버레이·`/metrics`·smoke breadth)는 라이브 검증 완료. arm64
    (Odroid) 이미지 build+boot smoke만 `GITHUB_TOKEN`이 있는 배포 환경에서 수행한다.
  - [ ] `T-ADMIN-TANSTACK` — **admin UI TanStack 테이블 이행 후속** (이행 자체는 PR #454 종결, 정본
    `docs/reports/admin-tanstack-table-migration-2026-06-17.md`). 잔여: (a) backend-의존 e2e 라이브
    실행(admin-ops/curated/features-new — Python venv+Postgres 환경; 정적 audit+grep상 무변경 호환),
    (b) bulk 동작 정책 가드(완료 review 재결정 차단·bulk archive confirm — 선택).
  - [ ] `T-AUDIT-0616` — **2026-06-16 전체 정합성 감사 후속** (정본
    `docs/reports/full-consistency-audit-2026-06-16.md`). 문서 충돌은 본 감사 PR에서 정정
    완료, 아래는 코드/검증 후속:
    - **F-01 (HIGH)** — **✅ 1차 해소(ADR-058, 옵션 B)**: geocoder 의존 ~11 provider feature_id
      비멱등(bjd 늦은 바인딩 → geocoder 유무로 분기). `reverse_geocoder_resource`를 base URL
      미설정 시 **실패**시켜 geocoder를 필수화(re-key 없이 결정성 보장). **잔여(옵션 A 후속)**:
      완전 결정성(geocoder 출력 drift까지)은 식별자에서 bjd 제거가 필요 — 전 feature DB re-key
      + provider별 natural_key 전역유일성 검증 동반, 별도 시점 결정.
    - **F-02 (MED)** — **✅ 해소(옵션 B)**: `reverse_geocode_failed` producer 구현 —
      `validation.py`가 좌표-있음+bjd-없음을 `missing_bjd_code`→`reverse_geocode_failed`로
      relabel(reverse 호출이 bjd를 못 낸 실패). `geocode_failed`(forward, 주소→좌표)는 적재에
      forward-geocode 경로가 없어 정의만(경로 생기면 연결).
    - ~~**C-04 / DA-D-07**: KHOA 해수욕장 category~~ **✅ 해소** — 전용 `01050100 TOURISM_NATURE_BEACH`로
      코드+문서 정렬(2026-06-16, 후속 PR). `01020300`(COAST_ISLAND)은 오분류였다.
      - ~~**re-key 중복 정리(#452/#445)**~~ **✅ 해소** — category가 feature_id 해시 입력이라
        재import 시 구 `01020300` KHOA feature가 신 `01050100`과 중복 active로 남는다. alembic
        `0027_khoa_recategorize_cleanup`(신 sibling 존재 시에만 구 feature inactive, 멱등)
        + 회귀 테스트(unit re-key 불변, integration sweep 가드)로 해소.
    - **e2e (HIGH)** — **✅ ZERO 5페이지 1차 spec 추가**: curated-features(라이브 smoke:
      렌더/필터/구조), features/new(라이브 smoke + 클라 검증), 3 detail 페이지
      (feature-update-request·import-job·feature — mocked-route, OpenAPI 타입 바인딩).
      `tsc -p e2e/tsconfig.json`·ESLint 통과, **Windows Playwright 라이브 검증은 잔여**(본
      환경 미실행). **잔여(depth)**: 전 페이지 mutation/error/cursor depth(§2 얇은 커버 14페이지),
      curated 시드 후보 기반 mutation flow(select/archive/source-rule apply), features/new
      실제 생성→422·409·지오코딩 mocked flow — `docs/reports/e2e-scenario-coverage-2026-06-16.md`
      §3 우선순위 순.
  - [ ] `T-452-openapi-problem-json` — **OpenAPI 에러 본문 RFC7807 정합**(#452/#444 잔여). 현재
    `openapi(.user).json`에 `application/problem+json` 응답 스키마가 없고(`docs/architecture/rest-api.md`
    §1.5가 산문으로 에러 계약 정본을 유지하는 의도적 한계), 4xx/5xx 응답이 generated client
    관점에서 under-spec다. 핸들러별 `responses=`로 problem+json 스키마를 선언하고
    `export_openapi.py --profile all`로 재생성 + `--check`로 검증한다. 산문 정본(§1.5)은
    유지하되 기계 계약을 보강하는 방향.
  - [ ] `T-019` — PinVi 측 Kakao Maps → maplibre-vworld 교체와 SPEC 문서 supersede 추적.
  - [ ] `T-210b` — PinVi 문서 supersede.
  - [ ] `T-210c` — PinVi `apps/etl` 레거시 Dagster 이관/삭제.
  - [ ] `T-210d` — PinVi httpx OpenAPI client 신규.
- **보류**
  - [ ] `T-101` — Materialized View 도입 검토.
  - [ ] `T-103` — streaming ETL(Kafka/Redpanda) 대응.

## 현재 상태

진척·"다음 한 작업"의 정본은 [`docs/resume.md`](resume.md). 과거 완료 묶음(`T-RV-*`,
`T-200`~`T-228`, `T-212a`~`d`, `T-216`, `T-218` 등)은 [`docs/tasks-done.md`](tasks-done.md).

## T-MAP-VWORLD-02 — admin features 지도를 VWorldMapView 기반으로 전환

- [ ] T-MAP-VWORLD-02 — **admin features 지도를 VWorldMapView 기반으로 전환** (#466)

`digitie/maplibre-vworld-react`의 `VWorldMapView`/React marker 모델을 기준으로 admin
`features` 지도의 직접 `maplibre-gl` 초기화와 marker 배열 수동 관리를 내부 React
컴포넌트 계층으로 전환한다. bbox 동기화, kind 필터 refetch, marker 선택, 상세 패널,
table/map 상태 공유, VWorld key 미설정 fallback은 유지한다.

완료 조건: frontend type-check/lint/vitest와 route-mocked 지도 e2e가 통과하고,
정본 계획 [`docs/reports/maplibre-vworld-react-migration-plan-2026-06-17.md`](reports/maplibre-vworld-react-migration-plan-2026-06-17.md)
의 전환 범위를 충족한다.

## T-MAP-VWORLD-03 — 지도 e2e 라이브 검증 및 후속 수정

- [ ] T-MAP-VWORLD-03 — **지도 e2e 라이브 검증 및 후속 수정** (#467)

지도 전환 PR이 main에 반영된 뒤 WSL 서버 + Windows Playwright 흐름으로 지도 관련 e2e를
실행한다. canvas/container 렌더링, bbox 조회, kind 필터 refetch, marker 또는 table 선택을
통한 상세 패널 노출을 확인하고, 실패가 있으면 후속 수정 PR로 반영한다.

완료 조건: `features-map-interactions.spec.ts` 또는 동등한 지도 e2e 결과를 기록하고, 발견한
회귀 수정이 main에 반영된다.

## T-229-buildx — arm64 multi-arch buildx 배포 검증 (T-229 잔여)

- [ ] T-229-buildx — **arm64(Odroid) 이미지 build+boot smoke**

T-229 라이브 검증은 완료됐다(curated 오버레이 0→86,341 후보 실데이터 검증, admin API
서빙 + 선택 게이트 동작, `/metrics` 200, smoke breadth — 정본
`docs/reports/t-229-curated-live-verify-2026-06-14.md`). 유일 잔여는 T-108/ADR-056의
arm64 multi-arch buildx 이미지 build+boot smoke로, private provider pin 빌드에
`GITHUB_TOKEN`이 필요해 **토큰이 주입된 배포 환경**에서만 수행 가능하다.

완료 조건: `scripts/docker-buildx.sh`로 linux/arm64 이미지를 빌드해 단일 platform
부팅 smoke가 통과하거나, 불가 사유가 명시 기록된다.

## 외부 추적

- [ ] T-019 — **PinVi 측 후속 작업 추적** (ADR-026 + ADR-043 후속, 본 저장소 외)

  PinVi `apps/web` Kakao Maps → maplibre-vworld 교체와 SPEC 문서의 Kakao Maps
  섹션 supersede를 추적한다. 본 저장소는 ADR-026/043 reference와
  `@kor-travel-map/map-marker-react` 계약만 책임진다.

- [ ] T-210b — **PinVi 문서 supersede** (PinVi repo, 외부)

  직접 import, 공유 DB, PinVi-owned Dagster 표현을 ADR-045 OpenAPI 연동 모델로
  supersede한다. 대상 문서와 치환 문구는 PinVi PR 본문에 남기고, 이 저장소에는
  링크/요약만 반영한다.

- [ ] T-210c — **PinVi `apps/etl` 레거시 Dagster 이관/삭제** (PinVi repo, 외부)

  kor-travel-map-owned Dagster(T-208 이후)를 기준으로 PinVi 쪽 레거시 ETL 문서와
  스켈레톤을 제거하거나 이관한다.

- [ ] T-210d — **PinVi httpx OpenAPI client 신규** (PinVi repo, 외부)

  PinVi가 `kor-travel-map` Python 패키지를 직접 import하지 않고 OpenAPI/httpx
  client로만 호출하도록 정렬한다.

## 보류

- [ ] T-101 — **Materialized View 도입 검토** (재타깃: 클러스터 rollup MV)

  `docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위 후보는
  `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를 시범 PR에서
  먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용 `UNIQUE`
  인덱스와 batch gate 연결을 함께 설계한다.

- [ ] T-103 — **streaming ETL(Kafka/Redpanda) 대응**

  `docs/architecture/performance.md §9.4` 기준. 특정 provider가 초 단위 latency를 실제로 요구하는
  증거가 생길 때까지 도입하지 않는다. 필요해지면 `packages/kor-travel-map-dagster`
  또는 별도 worker가 consumer를 소유하고, 메인 라이브러리는 message → DTO 변환 →
  `load_feature_bundles()` 호출 함수만 제공한다.

## 완료 이력 위치

- 최근 완료와 오래된 Sprint/Phase 이력은 [`docs/tasks-done.md`](tasks-done.md)를 본다.
- 작업 일지는 [`docs/journal.md`](journal.md), 현재 인수인계는
  [`docs/resume.md`](resume.md)를 본다.
