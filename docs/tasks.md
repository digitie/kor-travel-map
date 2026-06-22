# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는 [`docs/tasks-done.md`](tasks-done.md),
진척·"다음 한 작업"은 [`docs/resume.md`](resume.md)가 정본. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md).

## 진행 중인 작업 인덱스

- **다음**
  - [ ] `T-229-buildx` — **arm64 multi-arch buildx 배포 검증** (T-229 잔여). T-229의
    나머지(curated 오버레이·`/metrics`·smoke breadth)는 라이브 검증 완료. arm64
    (Odroid) 이미지 build+boot smoke만 `GITHUB_TOKEN`이 있는 배포 환경에서 수행한다.
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
    - **e2e (HIGH)** — **✅ 해소(라이브 검증 완료)**: ZERO 5페이지 1차 spec + depth 확장
      Wave 1~3(route-mock 6페이지 +32 시나리오)까지 라이브 frontend :12705에서 전수 실행 green —
      전체 스위트 **209 passed**(2026-06-17, `docs/journal.md`). backend-의존 e2e(admin-ops/
      curated/features-new)도 라이브 Docker 스택에서 **57 passed / 0 failed**로 검증됐다.
    - **잔여 = F-01 옵션 A 1건뿐**: 전 feature DB re-key + provider별 natural_key 전역유일성
      검증을 동반하는 big-bang으로, **별도 시점 결정**(deferred). 나머지 감사 항목은 모두 ✅.
- **보류**
  - [ ] `T-101` — Materialized View 도입 검토.

## 현재 상태

진척·"다음 한 작업"의 정본은 [`docs/resume.md`](resume.md). 과거 완료 묶음(`T-RV-*`,
`T-200`~`T-228`, `T-212a`~`d`, `T-216`, `T-218` 등)은 [`docs/tasks-done.md`](tasks-done.md).

## T-229-buildx — arm64 multi-arch buildx 배포 검증 (T-229 잔여)

- [ ] T-229-buildx — **arm64(Odroid) 이미지 build+boot smoke**

T-229 라이브 검증은 완료됐다(curated 오버레이 0→86,341 후보 실데이터 검증, admin API
서빙 + 선택 게이트 동작, `/metrics` 200, smoke breadth — 정본
`docs/reports/t-229-curated-live-verify-2026-06-14.md`). 유일 잔여는 T-108/ADR-056의
arm64 multi-arch buildx 이미지 build+boot smoke다. provider repo(`python-*-api`)가
2026-06-22부로 전부 public 전환되어 `GITHUB_TOKEN` 없이도 `.[providers]`를 빌드할 수
있으므로, arm64 빌더(QEMU/네이티브)가 있는 환경이면 어디서든 수행 가능하다.

완료 조건: `scripts/docker-buildx.sh`로 linux/arm64 이미지를 빌드해 단일 platform
부팅 smoke가 통과하거나, 불가 사유가 명시 기록된다.

## 보류

- [ ] T-101 — **Materialized View 도입 검토** (재타깃: 클러스터 rollup MV)

  `docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위 후보는
  `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를 시범 PR에서
  먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용 `UNIQUE`
  인덱스와 batch gate 연결을 함께 설계한다.

## 완료 이력 위치

- 최근 완료와 오래된 Sprint/Phase 이력은 [`docs/tasks-done.md`](tasks-done.md)를 본다.
- 작업 일지는 [`docs/journal.md`](journal.md), 현재 인수인계는
  [`docs/resume.md`](resume.md)를 본다.
