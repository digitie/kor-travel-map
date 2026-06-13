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
  - `T-229` — **T-212e 후속 라이브 검증**. T-225(완료)가 분리한 커버리지 갭을 라이브
    Docker 스택으로 검증한다: curated 오버레이(`curated_features_refresh` +
    admin/사용자 `curated-*` + `tripmate-copy`), post-reload 신규 표면(Prometheus
    `/metrics`, arm64 buildx), smoke breadth(features/batch·by-target, ops/providers,
    ops 관측, governance 리뷰 큐, debug/mois-license).
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

**T-225 closure 재검증은 완료**(2026-06-13, claude — 정본
`docs/reports/t-225-t212e-closure-recheck-2026-06-13.md`)됐고, T-212e closure는
유효로 재확인됐다. 남은 본 저장소 잔여는 T-225가 분리한 라이브 검증 후속 **T-229**다.
과거 상세 완료 묶음(`T-RV-*`, `T-200~T-228`, `T-212a~d`, `T-216`, `T-218` 등)은
`tasks-done.md`에 아카이브한다.

## T-229 — T-212e 후속 라이브 검증

- [ ] T-229 — **T-212e 후속 라이브 검증** (T-225가 분리한 커버리지 갭)

배경: T-225(완료, `docs/reports/t-225-t212e-closure-recheck-2026-06-13.md`)가
T-212e closure를 유효로 재확인하면서, 라이브 검증이 미수행된 커버리지 갭을 후속으로
분리했다. 전부 코드 결함이 아니라 **reload smoke에 미포함된 표면**이며 라이브 Docker
스택이 있어야 검증된다.

목표(우선순위 순):

- (A) **curated 오버레이 라이브 검증**(주요). `curated_features_refresh` job을
  materialize하고, admin `curated-*`(11개)·사용자/공개 `curated-*` read +
  `GET /v1/curated-features/{id}/tripmate-copy`(TripMate 인계 계약, ADR-049/052)를
  실데이터로 검증한다. [T-225: AS-01, API-11/12]
- (B) **reload 이후 신규 표면**. Prometheus `/metrics`(기본 on) 라이브 응답,
  T-108 arm64(Odroid) multi-arch buildx 이미지 build+boot smoke. [T-225: PMI-04/05]
- (C) **smoke breadth 보강**. `/v1/features/batch`·`/features/nearby/by-target`,
  `/v1/ops/providers`(+`/{provider}`), `/v1/ops/{metrics,api-call-logs,system-logs}`,
  governance 리뷰 큐(dedup/enrichment/feature-update-requests),
  `/v1/debug/mois-license/{id}`. [T-225: API-02/14/15/17/19]

완료 조건:

- (A)~(C) 각 표면이 라이브에서 검증되거나, 검증 불가 사유(예: export API 미가동
  guard-skip)가 명시 기록된다. 짧은 결과 리포트를 `docs/reports/`에 남긴다.

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
