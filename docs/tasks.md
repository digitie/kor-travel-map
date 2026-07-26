# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스 (2026-07-26 전면 감사 재정리)

> 2026-07-26 11-agent 전수 감사로 백로그를 실코드 기준으로 재정리했다. `integration/t-vn`에
> 누적됐던 C7·Wave 0/1 코드는 전부 main 합류 완료(`T-VN-SYNC-02`=PR #790, C7 COMPLETE @
> d5693269 — PinVi 결합 task 중 08은 PinVi PR #409로 완료, 11/12/16은 Lane B에 잔존). 완료 이관:
> T-VN-08·SCHEDCHURN·POICAUSAL·SYNC-02·T-VN-57·59·H02R·H03R·H08·H09·51~56 → `tasks-done.md`
> 2026-07-26 섹션. 감사 근거는 각 완료 항목에 기록. 추적 제외 결정(T-229-buildx,
> T-AUDIT-0616 F-01 옵션 A — ADR-058 옵션 B 채택)은 `journal.md` 2026-06-29 결정 그대로 유지.

**Lane A (Claude Code)** — 순차 실행. 규율: 코드 변경 시 적대 리뷰어 2명 + n150 파괴적
live E2E(실데이터) 후 PR·CI green·머지. Lane A 항목은 잔여가 실행 위주라 하위 상세 섹션
없이 **인덱스 상주가 정본**(tasks-rule §5의 "상세 위치 하나"를 인덱스로 충족).

- [ ] `T-VN-LIVE-01` — **targeted live acceptance lane n150 실행·종결**. 구현은 PR #792로
  main 합류 완료(spec 957줄 + fixture/state/supervisor + runbook:
  [admin-feature-live-acceptance](runbooks/admin-feature-live-acceptance.md), 설계:
  [t-vn-live-acceptance-741-785-2026-07-20](reports/t-vn-live-acceptance-741-785-2026-07-20.md)).
  잔여 = WSL SSH n150 production **파괴적 실행**으로 cleanup/audit/container/evidence 0/완결
  증명 + 증거 기록. 완료 시 아래 3개 task의 live 인수가 동시 종결된다(issue #741·#785 close).
  - [ ] `T-VN-04A`(#741) — 코드 main 합류 완료. 잔여 = lane 실행 내 inactive/draft/hidden
    marker·weather/price 카드·public 비누출 검증뿐(별도 작업 없음).
  - [ ] `T-VN-58`(#785) — 코드 main 합류 완료. 잔여 = lane 실행 내 competing update 후
    최초 raw `If-Match` 412·dirty draft 보존·명시적 reload 검증뿐(별도 작업 없음).
  - [ ] `T-VN-15` — 코드 main 합류 완료. 잔여 = lane 실행 내 signing secret fail-closed
    기동·정상 continuation·변조/query-mismatch 422 검증뿐(별도 작업 없음).
- [ ] `T-ADM-C6c` + `T-VN-03` — **principal 경계 smoke + pair 완결**(두 task 잔여가 동일
  실행으로 종결). 코드 양측 머지 완료(PinVi #387/#393, Map #782→#790, manager #64).
  잔여 = ① pinvi head(**hardening #408 포함** — 현 배포 e60d1711은 #408 이전) 재배포 +
  compatible-pair capture(**현행 manifest 버전으로** — 현 v4, `T-VN-H07C`가 v5를 먼저 land하면
  v5), ② n150 경계 smoke: curated 4 GET(keyless 거부/public-key·service-token 허용), ops 6
  GET(headerless/service-only/cancel-token 401·403 + admin-BFF·ops:read 양성 — PinVi principal
  실증), MOIS debug 404(unmount), ③ PinVi issue #392 close. 설계 정본:
  [t-vn-03-route-gate-cutover-2026-07-19.md](reports/t-vn-03-route-gate-cutover-2026-07-19.md)
  §5 항목 4 + §6 완료 조건. C7 게이트 read-auth는 admin-BFF만 커버하므로 대체 불가(2026-07-26
  감사 확정).
- [ ] `T-VN-H06` — **admin 목록 keyset 전환 완결**. 구현 완료 = PR #813(OPEN, CI green,
  1차 적대 리뷰 반영 커밋 포함; "C7 종결 후 진행" hold는 C7 COMPLETE로 해제). 잔여 =
  2차 적대 리뷰 → 머지 → dedup/enrichment cursor e2e 런타임 검증(n150 Linux Playwright).
  **Lane A 규율 명시 예외**: 파괴적 n150 live E2E 대상 아님(admin 목록 read 표면) — 런타임
  검증은 머지 후 n150 Linux Playwright e2e로 수행(PR #813 본문의 시나리오 순서 유지).

**Lane B (codex)** — 병렬 wide lane. 규율: 각 코드 PR은 테스트 전 적대 리뷰어 2명 반영 후
n150 실데이터 파괴적 Live UI E2E를 통과한다.

- b0 (선행 하드닝, 순차): [ ] `T-VN-42` → [ ] `T-VN-43`(npm 보안) →
  [ ] `T-VN-44`(frontend lint baseline) → [ ] `T-VN-45`(live endpoint·cache drift)
- b1 (PinVi 결합, 순차): [ ] `T-VN-11` → [ ] `T-VN-12` → [ ] `T-VN-16` →
  [ ] `T-VN-41`
- b2 (계약·manifest): [ ] `T-VN-H07`(+`H07C` #812·`H07D` #815) — PinVi field-level
  contract·pinned OpenAPI SHA manifest 완결(상세는 아래 b2 섹션).
- b3 (Wave 2 구조 전환): [ ] `T-VN-31` 선행 → [ ] `T-VN-32`~[ ] `T-VN-38`(순서 자유·독립
  rollback; 개별 checkbox는 아래 b3 섹션) → [ ] `T-VN-40` → [ ] `T-VN-39`(cutover 마지막)
- 보류: [ ] `T-101` — Materialized View 도입 검토(조건 발생 시)

## 공통 규율 (2026-07-26 개정)

- base는 **main**(`integration/t-vn`은 PR #790 합류로 폐지). 시작·PR 직전·머지 직후
  `origin/main` rebase. PR 하나는 task 하나만 소유.
- **Lane A**: 각 코드 task는 적대적 리뷰어 **2명** 반영 후 n150 **파괴적 live E2E**
  (실데이터)로 검증하고 PR·CI green·머지. 작업 중 발견 항목은 tasks.md에 즉시 추가.
- **Lane B**: 각 코드 task는 적대적 리뷰어 **2명** 반영 후 n150 **실데이터 파괴적 Live UI
  E2E**를 통과하고 PR·CI green·머지한다. task 완료 시 상대 lane 2일치 PR 적대 리뷰 관행 유지.
- **우선순위(서비스 전 단계 — 사용자 지시 2026-07-26)**: **정확성·보안 최우선은 불변**
  (AGENTS.md), 그 아래 설계적 우수성 > 확장성 > 성능 > 불필요한 코드 반복(래퍼류) 금지.
  **prod 환경 보전·호환성·기존 문서 계약·최소 수정은 비제약** — 필요 시 DB 스키마·문서
  계약 수정 가능. AGENTS.md vNext 우선순위 단락에 동일 취지의 dated note를 둔다.
- migration 정본: 단일 head 유지(현 head `0063_pipeline_root_id`). 후속 migration 소유자는
  PR 직전 단일 head를 재확인한 뒤 번호를 배정한다.
- 문서 전용·rebase-only·기계적 변경(변수명·import 정렬)은 적대 재리뷰 면제.
- pytest와 Playwright를 포함한 모든 검증은 n150 WSL SSH에서 실행한다. mocked e2e도 n150
  Linux가 정본이며, n150에서 실행할 수 없는 브라우저 제약이 확인될 때만 Windows를 fallback으로
  사용한다. live e2e는 항상 n150 파괴적 lane으로 실행한다.
- **cross-lane 순서 제약**: `T-VN-H07C`(manifest v5)는 Lane A의 C6c pair capture·#392 close
  **이후** 착수(같은 docker-manager pair-capture 도구·ADR-076 정본을 두 lane이 동시에 만지는
  충돌 방지). 그 전까지 b2는 #814/pinvi#403 머지와 H07D를 진행한다.
- **prod 격리 규율(2026-07-27 인시던트 재발 방지 —
  [리포트](reports/incident-2026-07-27-shared-prod-db-live-container.md))**: 아래 4개는
  두 lane 공통 필수.
  - **R1 lane live/dev 컨테이너 prod 격리**: 어떤 lane이든 n150에서 띄우는 live/dev
    컨테이너는 **production DB·포트와 격리**한다(전용 DB/schema 또는 폐기용 복제본).
    **공유 prod DB에 대한 startup auto-migration 금지** — 공유 DB alembic head 전진은
    조율된 배포 단계에서만. (인시던트: Lane B `pinvi-api-tvn08-live`가 공유 pinvi DB를
    `0040`으로 migration → held `e60d1711` 기동 불가 → manifest trap.)
  - **R2 prod manager 디렉토리에서 raw `docker compose` 금지**: auto-load되는
    `docker-compose.override.yml`이 provider 키를 주입해 map-api가 fail-close된다. prod
    런타임 변경은 **ktdctl(base compose, sanitized)**로만. 단일 서비스 재생성이
    불가피하면 **`-f docker-compose.yml`(base만)** 명시로 override 배제.
  - **R3 compatible-pair 함정**: 공유 DB가 held 컴포넌트 head를 넘어 migration되면 held
    컴포넌트가 기동 불가가 되어 manifest가 trap된다. 복구 = held 컴포넌트를 runnable
    revision으로 전진 + 재-cut. deploy 가드(리비전 정합·manifest-drift·mandatory-health)
    임시 우회 시 **성공 직후 즉시 원복**.
  - **R4 cross-lane 배포 조율**: 두 lane이 같은 prod 페어/공유 DB를 동시에 만질 때는
    재-cut·live 실행 창을 겹치지 않게 하고, 한 lane의 live 컨테이너가 다른 lane의 배포
    대상 DB를 공유하지 않도록 lane 소유자가 사전 확인한다.

## Lane B 상세 — b0 선행 하드닝

- [ ] T-VN-42 — **지도 상세 패널·실모션 zoom·items query key 하드닝**

  PR #843 이후 전문 적대 리뷰에서 확인된 잔여를 한 번에 해소한다. `/features`와
  `/curated-features`의 우측 상세 패널이 bottom-right `ScaleControl`을 덮지 않도록 고정 하단
  여백을 계약화하고 mocked·실데이터 E2E에서 실제 bounding box 비겹침을 검증한다. live 전역
  `reducedMotion: "reduce"` 의존을 제거하고 MapLibre의 실제 `moveend`까지 클릭마다 기다리는 zoom
  helper로 전환한다. items/clusters in-bounds query key는 HTTP 요청과 동일한 정수 zoom과 원본 bbox,
  명시적 mode를 사용하고, 서버의 정수 zoom 기준과 UI cluster/items 분기를 하나의 함수로 통일한다.
  PR 전 #840 이후 Claude Code PR(닫힌 PR 포함) 재감사에서 발견한 #844의 BLOCKED clear 신호 경쟁
  조건과 #845의 복구 실행 identity 증거 누락도 같은 변경에 반영한다. BLOCKED v3는 최초 실행의
  source commit·API/Playwright image ID·compatible-pair manifest·host attestation hash를 기록하고,
  recovery runtime과 exact 대조해 cross-version cleanup을 mutation 전에 거부한다. 성공 result v3에는
  canonical identity SHA256과 pair/attestation hash만 영속화한다.

- [ ] T-VN-43 — **admin frontend npm 보안 취약점 0-high 전환**

  n150 clean `npm ci`의 `npm audit` 기준 16건(low 2, moderate 7, high 7)을 해소한다. 직접 의존
  `next` high와 `shadcn` moderate, transitive `sharp`/`hono`/`js-yaml`/`fast-uri` 등을 runtime·tooling
  도달성으로 분류하되 서비스 전 단계에서는 high 0을 필수 계약으로 둔다. lockfile을 의도적으로
  갱신하고 type-check·build·mocked 및 실데이터 파괴적 Live UI E2E로 cutover를 검증한다.

- [ ] T-VN-44 — **admin frontend full ESLint baseline green**

  현재 `npm run lint`의 1 error/8 warnings를 suppression 없이 제거한다. 우선 blocker는
  `schedule-panel.tsx` recovery dialog의 effect 내부 동기 `setEditing(null)`이며, recovery claim을
  렌더 파생 상태 또는 command 경계로 재설계해 cascading render를 없앤다. 나머지 unused·hook
  dependency·incompatible-library 경고는 실동작과 React Compiler 경계를 보존하면서 각각 근인으로
  해소하고 full lint 0 problem을 회귀 게이트로 둔다.

- [ ] T-VN-45 — **features map 실데이터 input-roundtrip endpoint·cache 대기 drift 제거**

  T-VN-42 live 중 `features-map-input-roundtrip.live.spec.ts`의 점 마커 시나리오가 UI가 이미
  `/v1/admin/features/in-bounds`로 전환된 뒤에도 public `/v1/features` bbox 응답만 기다려 5분
  timeout하는 drift를 확인했다. admin items/clusters 응답을 정본으로 추적하고 React Query cache hit로
  새 HTTP 응답이 없는 경우에도 map idle+실제 marker 상태로 수렴하도록 고쳐 false-red를 제거한다.

## Lane B 상세 — b1 PinVi 결합

- [ ] T-VN-11 — **service batch 5-state 계약**

  `found|retired|suppressed|missing|unchanged`와 revision을 반환하고 transport 실패를 503으로
  분리한다(`features.py` batch가 현재 2-state found/missing — in-code TODO가 본 task를 지목).
  PinVi typed consumer contract test를 같은 cutover 산출물로 둔다.

- [ ] T-VN-12 — **domain-owned Idempotency-Key 전개**

  기존 pipeline/schedule ledger를 회귀 기준선으로 두고 남은 retryable command에 body fingerprint,
  result replay, key reuse 409를 domain별로 구현한다(admin_features의 natural_key는 ledger 계약이
  아님 — 대상 조사부터).

- [ ] T-VN-16 — **weather batch와 부모 404**

  set-based weather batch와 `target_at`/`known_at` parameter를 제공해 PinVi N+1을 없애고 존재하지
  않는 parent feature를 빈 결과가 아닌 404로 구분한다(현재 단건 GET만 존재).

- [ ] T-VN-41 — **cache-target generation·outbox 전파**

  기존 external identity와 exact scope를 유지하면서 source generation/restore epoch, outbox relay,
  backfill·reconciliation을 설치하고 critical path 밖에서 enable한다.

## Lane B 상세 — b2 T-VN-H07 완결

- [ ] T-VN-H07 — **PinVi field-level contract와 OpenAPI SHA 검증**

  양 저장소 contract test를 required/type/enum 필드까지 강화하고 배포 compatible pair에 pinned
  OpenAPI SHA manifest를 요구한다. 진행 상태: Map측 PR #814·PinVi측 PR #403 모두 OPEN(머지 필요).
  - [ ] `T-VN-H07C`(#812) — docker-manager compatible-pair **manifest v5**: pinned OpenAPI SHA
    enforcement(`c6c_deployment.py` `_PAIR_MANIFEST_VERSION=4→5`) + ADR-076 v5 개정.
  - [ ] `T-VN-H07D`(#815) — admin curated detail-snapshot field-level contract(PinVi runtime 표면).

## Lane B 상세 — b3 Wave 2 구조 전환

> 실행 순서는 31(freeze) → 32~38(shadow 병렬 가능·독립 rollback) → 40 → 39(cutover 마지막).
> ADR-066~075가 목표 스펙 정본. 서비스 전 단계이므로 drop/recreate 자유(ADR-075의 보존
> ceremony는 실데이터 보호 필요 범위로 최소화).

- [ ] T-VN-31 — **vNext target freeze**

  ADR-066~075(존재)·목표 OpenAPI diff·목표 DDL·제약 테스트를 실행 전 고정한다. ADR 문서는
  #736으로 존재하나 freeze 산출물(목표 DDL/OpenAPI diff artifact + 제약 테스트)은 미생성.
  이 task는 구현 변경을 섞지 않고 소비자·복구 preflight의 입력을 확정한다.

- [ ] T-VN-32 — **UUID identity shadow 전환**

  UUID column과 legacy alias를 backfill하고 FK·notice lineage·PinVi alias-map의 consumer-first
  전환을 준비한다. legacy ID 제거는 soak 뒤 별도 단계다.

- [ ] T-VN-33 — **provider dataset 정본 전환**

  `provider_datasets`를 신설하고 참조 table을 FK화하며 source record denormalization을 제거한다.
  전환기에는 composite FK로 entity-record identity 불일치를 먼저 막는다.

- [ ] T-VN-34 — **직교 상태 모델 전환**

  lifecycle/publication/quality 3축과 결합 CHECK를 backfill하고 `public_features` view
  (0059는 CREATE VIEW만 — partial index는 본 task)를 새 정본으로 전환한다.

- [ ] T-VN-35 — **typed subtype 분해**

  core와 point/event/notice/route/area subtype을 typed table·geometry/category 제약으로 분리한다.
  subtype별 독립 shadow 전환과 rollback을 증명한다.

- [ ] T-VN-36 — **field override 단일화**

  whole-row freeze를 field override로 이관하고 effective projection을 대조한 뒤 provider upsert의
  중복 `CASE`를 제거한다. T-VN-35와 독립 rollback 가능해야 한다.

- [ ] T-VN-37 — **typed notice state**

  notice 유효 기간을 typed range와 DB 제약으로 재설계하고 공개 hot path의 cast·lineage anti-join을
  제거한다(T-VN-06 방어 cast는 잠정 — typed 재설계는 본 task 소유).

- [ ] T-VN-38 — **weather·price current summary**

  원본 이력을 보존하는 current summary projection을 만들고 bbox/detail의 per-row LATERAL 조회를
  set-based join으로 바꾼다.

- [ ] T-VN-40 — **curation write model 단일화**

  `curation_collections/items`만 write 정본으로 남기고 legacy table·trigger·route
  (`curated_features` overlay 일체)를 제거한다. 자동 후보는 `theme_feature_candidates`처럼 별도
  lifecycle로 분리한다.

- [ ] T-VN-39 — **KTM·PinVi write-fence cutover**

  보존 분류, restore/PITR 또는 journal 검증, shadow checksum, consumer-first 배포, write fence,
  순차 전환, soak, legacy 제거를 ADR-075 절차대로 수행한다. T-VN-32~38·40 완료 뒤 마지막.

## T-101 — Materialized View 도입 검토 (보류)

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
