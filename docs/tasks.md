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
  - `T-225` — **T-212e closure 재검증**. T-224/T-221/T-222/T-223/T-226/T-227/T-228
    이후 main 기준으로 T-212e 실데이터 full reload/offline upload 결과를 한 번 더
    대조한다.
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

즉시 실행 가능한 본 저장소 잔여는 **T-225 closure 재검증**뿐이다. 과거 상세 완료
묶음(`T-RV-*`, `T-200~T-228`, `T-212a~d`, `T-216`, `T-218` 등)은
`tasks-done.md`에 아카이브한다.

## T-225 — T-212e closure 재검증

- [ ] T-225 — **T-212e closure 재검증**

목표:

- `docs/reports/t-212e-live-full-reload-final-2026-06-12.md` 결과가 최신 main의
  provider/API/admin 표면과 충돌하지 않는지 확인한다.
- 다른 agent의 T-212e 결과가 충분하면 full reload를 재실행하지 않고 증거 대조로
  닫는다.

확인 항목:

- live full reload row 수: 1,095,665 features, weather values 92,923.
- consistency gate 최종 report: `99159eea`, `severity_max=OK`.
- offline upload 실데이터 CSV/TSV/JSONL 3포맷 + DELETE lifecycle 증거.
- Windows Playwright e2e 33/33, API smoke 17/17, backup/restore smoke.
- 대표 read P99: search 86ms, nearby 102ms, categories 9ms, in-bounds 442ms.
- T-221/T-222/T-223/T-224/T-226/T-227/T-228 이후 새 API/provider/admin 표면이
  T-212e 최종 리포트의 closure 조건에서 빠지지 않았는지.

산출물:

- 필요 시 `docs/reports/`에 짧은 재검증 리포트 추가.
- `docs/resume.md`와 `docs/journal.md`에 결과 반영.
- 충분히 닫혔으면 `tasks-done.md`로 T-225 이동.

완료 조건:

- 최신 main 기준 evidence 링크와 수치가 재대조되어 drift가 없거나, 남은 drift가
  명시적 후속 task로 분리된다.

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
