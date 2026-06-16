# tasks.md — 백로그

이 문서는 **진행 중/예정(`[ ]`) task만** 두는 백로그다. 완료·아카이브 task는
[`docs/tasks-done.md`](tasks-done.md)에 둔다. 현재 진척과 "다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다.

## 운영 규칙

- 완료된 task를 이 파일에 길게 남기지 않는다. 완료 확인 후 `tasks-done.md`로 옮긴다.
- 상단 인덱스와 상세 섹션의 열린 `[ ]` 항목은 서로 일치해야 한다.
- 외부 저장소 작업은 본 저장소에서 직접 실행하지 않는 한 "외부 추적"으로만 둔다.
- 보류 항목은 도입 조건이 충족되기 전까지 Sprint 잔여로 계산하지 않는다.

## 진행 중인 작업 인덱스

- **다음**
  - `T-229-buildx` — **arm64 multi-arch buildx 배포 검증** (T-229 잔여). T-229의
    나머지(curated 오버레이·`/metrics`·smoke breadth)는 라이브 검증 완료. arm64
    (Odroid) 이미지 build+boot smoke만 `GITHUB_TOKEN`이 있는 배포 환경에서 수행한다.
  - `T-AUDIT-0616` — **2026-06-16 전체 정합성 감사 후속** (정본
    `docs/reports/full-consistency-audit-2026-06-16.md`). 문서 충돌은 본 감사 PR에서 정정
    완료, 아래는 코드/검증 후속:
    - **F-01 (HIGH)**: geocoder 의존 ~10 provider(knps/krheritage/mcst/krforest/
      datagokr_file_data/khoa/airkorea/krairport/opinet/standard_data)의 **feature_id 비멱등**
      (bjd가 늦게 바인딩 → geocoder 유무로 global↔code 분기). ADR-057 anchoring 패턴(안정
      source key + 고정 identity category, bjd는 가변 속성) 적용 provider 범위 결정 + 코드.
    - **F-02 (MED)**: `geocode_failed`/`reverse_geocode_failed` admin issue **producer 신설**
      (validate_feature_bundle_address가 미방출) 또는 ADR-046 contract에서 제거 결정.
    - **C-04 / DA-D-07 (⚖️ 결정)**: KHOA 해수욕장 category 코드 `01020300`(COAST_ISLAND) vs
      전용 `01050100` — 코드 정렬 여부 결정(본 패스는 문서를 코드값에 맞추고 divergence 명기).
    - **e2e (HIGH)**: ZERO 커버 5페이지(curated-features 1192줄 콘솔·features/new·3 detail
      페이지) + 전 페이지 mutation/error/cursor depth — `docs/reports/e2e-scenario-coverage-
      2026-06-16.md` 우선순위 순으로 spec 추가.
- **외부 추적**
  - `T-019` — TripMate 측 Kakao Maps → maplibre-vworld 교체와 SPEC 문서 supersede 추적.
  - `T-210b` — TripMate 문서 supersede.
  - `T-210c` — TripMate `apps/etl` 레거시 Dagster 이관/삭제.
  - `T-210d` — TripMate httpx OpenAPI client 신규.
- **보류**
  - `T-101` — Materialized View 도입 검토.
  - `T-103` — streaming ETL(Kafka/Redpanda) 대응.

## 현재 상태

Sprint 5 운영 진입 마무리 단계다. `T-212e` 실데이터 full reload는 완료됐고,
이후 `T-221` admin UI/UX, `T-222` 공개 해수욕장/축제 뷰 API, `T-223`
curated feature/TripMate import, `T-224` concierge provider 경계, `T-226`
패키지/runtime identity clean cut, `T-227` Prometheus 메트릭, `T-228`
API/admin 패키지 분리까지 닫혔다.

**T-225 closure 재검증**(2026-06-13)과 **T-229 라이브 검증**(2026-06-14 — curated
오버레이 86,341 후보 실데이터 검증, `/metrics` 200, smoke breadth; 정본
`docs/reports/t-229-curated-live-verify-2026-06-14.md`)이 모두 완료됐다. 본 저장소에서
즉시 실행 가능한 큰 트랙은 없고, 유일 잔여는 **arm64 buildx 배포 검증**(`GITHUB_TOKEN`
필요)이다. 과거 상세 완료 묶음(`T-RV-*`, `T-200~T-228`, `T-212a~d`, `T-216`, `T-218`
등)은 `tasks-done.md`에 아카이브한다.

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

- [ ] T-019 — **TripMate 측 후속 작업 추적** (ADR-026 + ADR-043 후속, 본 저장소 외)

  TripMate `apps/web` Kakao Maps → maplibre-vworld 교체와 SPEC 문서의 Kakao Maps
  섹션 supersede를 추적한다. 본 저장소는 ADR-026/043 reference와
  `@kor-travel-map/map-marker-react` 계약만 책임진다.

- [ ] T-210b — **TripMate 문서 supersede** (TripMate repo, 외부)

  직접 import, 공유 DB, TripMate-owned Dagster 표현을 ADR-045 OpenAPI 연동 모델로
  supersede한다. 대상 문서와 치환 문구는 TripMate PR 본문에 남기고, 이 저장소에는
  링크/요약만 반영한다.

- [ ] T-210c — **TripMate `apps/etl` 레거시 Dagster 이관/삭제** (TripMate repo, 외부)

  kor-travel-map-owned Dagster(T-208 이후)를 기준으로 TripMate 쪽 레거시 ETL 문서와
  스켈레톤을 제거하거나 이관한다.

- [ ] T-210d — **TripMate httpx OpenAPI client 신규** (TripMate repo, 외부)

  TripMate가 `kor-travel-map` Python 패키지를 직접 import하지 않고 OpenAPI/httpx
  client로만 호출하도록 정렬한다.

## 보류

- [ ] T-101 — **Materialized View 도입 검토** (재타깃: 클러스터 rollup MV)

  `docs/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위 후보는
  `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를 시범 PR에서
  먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용 `UNIQUE`
  인덱스와 batch gate 연결을 함께 설계한다.

- [ ] T-103 — **streaming ETL(Kafka/Redpanda) 대응**

  `docs/performance.md §9.4` 기준. 특정 provider가 초 단위 latency를 실제로 요구하는
  증거가 생길 때까지 도입하지 않는다. 필요해지면 `packages/kor-travel-map-dagster`
  또는 별도 worker가 consumer를 소유하고, 메인 라이브러리는 message → DTO 변환 →
  `load_feature_bundles()` 호출 함수만 제공한다.

## 완료 이력 위치

- 최근 완료와 오래된 Sprint/Phase 이력은 [`docs/tasks-done.md`](tasks-done.md)를 본다.
- 작업 일지는 [`docs/journal.md`](journal.md), 현재 인수인계는
  [`docs/resume.md`](resume.md)를 본다.
