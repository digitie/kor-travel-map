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

- [ ] `T-VN-H12` — **live acceptance fixture 좌표 run-unique화** (T-VN-LIVE-01 kind-격리 후속).
  **구현·정적검증 완료 (PR 대기/머지)**, 잔여 = **live-lane 실증**뿐.

  `admin-feature-acceptance-write.live.spec.ts`의 status marker 좌표가 고정(LON=127.5/LAT=36.5)이라
  죽은 run의 leftover place가 현재 run과 0.000° 거리로 supercluster 병합돼 marker aria-label 소실(적대
  리뷰 P2). 수정: base 좌표를 `sha256(RUN_ID)` ±0.25° jitter(한국 본토 bbox 중심부) + `recenterMapTo`
  헬퍼로 marker 단계에서 map을 fixture 좌표로 jumpTo(jitter로 fixture가 DEFAULT_VIEWPORT center를 벗어나
  viewport 이탈하는 것을 차단). offset/bbox/cleanup/RECOVERY_ONLY는 좌표 무관이라 무수정. e2e type-check
  통과 + 4개 각도 적대 정적검증 통과(collision-efficacy/recenter-mechanics/validity-determinism/
  missed-viewport-deps). **잔여**: 다음 live acceptance lane run에서 n150 실증(Lane A live lane).

**Lane B (codex)** — 병렬 wide lane. 규율: 각 코드 PR은 테스트 전 적대 리뷰어 2명 반영 후
n150 실데이터 파괴적 Live UI E2E를 통과한다.

- b0 (선행 하드닝, 순차): [ ] `T-VN-43`(npm 보안) →
  [ ] `T-VN-44`(frontend lint baseline) → [ ] `T-VN-47`(React Doctor) →
  [ ] `T-VN-45`(live endpoint·cache drift) → [ ] `T-VN-46`(npm optional tree) →
  [ ] `T-VN-48`(mocked E2E drift)
- b4 (열린 이슈 버그·하드닝, 2026-07-27 추가): [ ] `T-VN-H13`(#699 curation upsert) →
  [ ] `T-VN-H14`(#700 KREX retry) → [ ] `T-VN-H15`(#805 IPv6 origin) (상세는 아래 b4 섹션)
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

- [ ] T-VN-43 — **admin frontend npm 보안 취약점 0-high 전환**

  n150 clean `npm ci`의 `npm audit` 기준 16건(low 2, moderate 7, high 7)을 해소한다. 직접 의존
  `next` high와 `shadcn` moderate, transitive `sharp`/`hono`/`js-yaml`/`fast-uri` 등을 runtime·tooling
  도달성으로 분류하되 서비스 전 단계에서는 high 0을 필수 계약으로 둔다. 사용하지 않는 폼 의존성을
  제거하고, npm 10이 `extraneous`로 분류하는 exact Sharp WASM optional 6개 외 문제를 거부하는 integrity
  gate를 둔다. lockfile을 의도적으로 갱신하고 type-check·build·실제 Next/Sharp optimizer·대표 mocked
  및 실데이터 파괴적 Live UI E2E로 cutover를 검증한다.

- [ ] T-VN-44 — **admin frontend full ESLint baseline green**

  T-VN-43에서 modern React-X/React-DOM 권장 규칙을 직접 구성한 뒤 `npm run lint`가 보고하는
  1 error/30 warnings를 suppression 없이 제거한다. canonical React Hooks와 겹치는 분석기는 중복
  실행하지 않는다. 우선 blocker는
  `schedule-panel.tsx` recovery dialog의 effect 내부 동기 `setEditing(null)`이며, recovery claim을
  렌더 파생 상태 또는 command 경계로 재설계해 cascading render를 없앤다. 나머지 unused·hook
  dependency·incompatible-library 경고는 실동작과 React Compiler 경계를 보존하면서 각각 근인으로
  해소하고 full lint 0 problem을 회귀 게이트로 둔다.

- [ ] T-VN-47 — **admin frontend React Doctor 진단 근인 해소**

  T-VN-43에서 React Doctor 0.9.1로 갱신한 full scan은 262개 파일에서 78건(오류 9, 경고 69)을
  보고한다. WebSocket effect cleanup 3건과 nested state updater side effect 5건은 실제 lifecycle·
  purity 위반 여부를 재현해 근인으로 해소하고, GET proxy의 `Headers.set()` 보안 진단은 요청 부수효과가
  아닌 응답 구성임을 코드 흐름·upstream rule과 대조해 오탐이면 좁은 근거 기반 설정으로 표현한다.
  성능·접근성·유지보수 경고도 generated UI 여부와 runtime 도달성을 분류하되 blanket suppression 없이
  full scan green 또는 명시적 검증 예외만 허용하며, CI 회귀 게이트를 추가한다.

- [ ] T-VN-45 — **features map 실데이터 input-roundtrip endpoint·cache 대기 drift 제거**

  T-VN-42 live 중 `features-map-input-roundtrip.live.spec.ts`의 점 마커 시나리오가 UI가 이미
  `/v1/admin/features/in-bounds`로 전환된 뒤에도 public `/v1/features` bbox 응답만 기다려 5분
  timeout하는 drift를 확인했다. admin items/clusters 응답을 정본으로 추적하고 React Query cache hit로
  새 HTTP 응답이 없는 경우에도 map idle+실제 marker 상태로 수렴하도록 고쳐 false-red를 제거한다.

- [ ] T-VN-46 — **admin frontend npm optional tree 무결성 완결**

  T-VN-43의 exact npm 10.9.4 clean install은 audit 0과 exit 0이지만 `npm ls --all --json`의
  `problems`에 Sharp 0.35.3 WASM fallback optional graph 6개(`@emnapi/*`, `@img/sharp-wasm32`,
  `@napi-rs/wasm-runtime`, `@tybys/wasm-util`)를 `extraneous`로 남긴다. T-VN-43은 exact allowlist 밖
  문제를 fail-close하고 실제 native optimizer를 검증한다. 후속에서는 npm Arborist/Sharp upstream
  원인을 해결해 allowlist 자체를 제거하며, 쓰지 않는 direct dependency를 추가해 숨기지 않는다.

- [ ] T-VN-48 — **admin mocked Playwright UI 계약 drift 정리**

  T-VN-43 gate에서 전체 269 mocked spec 중 165번째까지 52건의 기존 drift를 재현했다. 현재 UI가
  `후보 A/B`·한국어 dialog accessible name·실제 로그인 actor를 쓰는데 spec은 `feature A/B`·영문
  accessible name·`local-admin`을 기다리는 사례와 `/ops/datasets` route mock drift가 누적됐다.
  main 기준으로 실패 집합을 freeze하고 accessible-name/actor/API route 계약을 현재 UI와 맞춘 뒤,
  전체 suite를 Linux C7 image·workers=1/병렬 모드 모두 green으로 만든다.


## Lane B 상세 — b4 열린 이슈 버그·하드닝 (2026-07-27 추가)

> 2026-07-27 open-PR·이슈 전수 확인에서 main에 잔존하는 미수정 버그/하드닝을 백로그화.
> 각 항목은 GitHub 이슈에 tasks.md 백로그 링크를 함께 기록한다.

- [ ] T-VN-H13 — **curation upsert ON CONFLICT 조건부 덮어쓰기** (#699)

  `curation_repo.py`의 ON CONFLICT가 `status`/`curation_relation`/`reuse_policy = EXCLUDED.*`를
  무조건 덮어써, 운영자가 조정한 상태를 재수집이 되돌린다. 조건부 갱신(제공자 파생 필드만, 운영자
  override 보존) 또는 명시적 병합 규칙으로 재설계하고 회귀 테스트를 둔다.

- [ ] T-VN-H14 — **KREX snapshot set-mismatch retry 상한** (#700)

  `provider_fetchers.py` KREX가 snapshot set 불일치에서 retry cap 없이 `RuntimeError`를 raise한다.
  bounded retry + 명확한 typed 실패로 전환해 일시 불일치가 파이프라인을 중단시키지 않게 한다.

- [ ] T-VN-H15 — **c7 attestation IPv6 public origin 정규화** (#805)

  `scripts/lib/c7_prod_attestation.py:_public_origin`가 `f"{host}{port}"`로 IPv6 bracket 복원/zone-id
  거부를 안 한다. IPv6 host bracket 정규화 + zone-id 거부로 origin 계약을 정확화(이슈 자체가 C7
  blocker 아닌 후속 하드닝으로 명시).

## 이슈 종결 추적

> landing task와 완료 조건이 동일한 열린 이슈만 함께 닫는다. LIVE-01 후속 OPEN 7건은 Lane A
> `T-VN-H16`/`T-VN-H17`에서 독립 재검증 완료(2026-07-27): **7건 전부 close**. 6건은 H16
> (dm#63·#70·map#712·#719·#777·#694), map#684는 H17에서 조건 #8을 "write/error UI 엣지는 mock,
> read·URL·freshness + write 계약은 live"로 명시 축소 후 close.

- **T-ADM-C6c + T-VN-03 landing 시**: PinVi #392 (관측 API ops read principal 실증).
- **추적/관측(코드 미확정)**: map #738(lane 분배 hub)·#673(validation rule 재검토)·#819(HAProxy
  timeout tunnel 적용) · PinVi #215(post-review cleanup 잔여 — ADR-045 VWorld opaque-token hard-gate 등).

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
