# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스 (2026-07-28 PR #869 후 전면 재감사)

> PR #869 merge `25e9304b` 직후 `tasks.md`·`tasks-done.md`·실코드·Map/PinVi/
> docker-manager/geo의 열린 PR·이슈를 다시 대조했다. Map의 열린 이슈는 #673·#812·#815·#819,
> 열린 PR은 #814 한 건이며, PinVi의 관련 열린 PR은 #403이다. `T-VN-H21`의 실서비스 400은
> reverse payload drift가 아니라 보호 endpoint에 `key`가 결선되지 않은 test preflight 오류로
> 재분류했다. 큰 task는 독립 검증·독립 rollback이 가능한 실행 단위로 아래처럼 분해한다.

**Lane A (Claude Code)**와 **Lane B (codex)**는 서로 병렬 실행한다. 각 lane 내부는 아래 순서를
지키며, 같은 migration head·OpenAPI 정본·같은 cross-repo pair를 만지는 시점만 공통 규율의
barrier로 직렬화한다.

- **Lane A — cross-repo 계약·운영·데이터 품질**
  - a0: [ ] `T-VN-H07A`(Map #814 재감사·landing) →
    [ ] `T-VN-H07B`(PinVi #403 재감사·landing) →
    [ ] `T-VN-H07D`(#815 admin snapshot/freshness) →
    [ ] `T-VN-H07C`(#812 manifest v5)
  - a1: [ ] `T-VN-H27`(#819 HAProxy tunnel) →
    [ ] `T-VN-H21`(geo live 인증 preflight·5건 재실증) →
    [ ] `T-VN-H28A`(#673 실데이터 오탐 분류) →
    [ ] `T-VN-H28B`(#673 검증 규칙·회복 경로) →
    [ ] `T-VN-H25A`(stale reference 증거 manifest) →
    [ ] `T-VN-H25B`(검토된 reference 적용) →
    [ ] `T-VN-H22A`(quarantine read/preview) →
    [ ] `T-VN-H22B`(원자적 재분류 command) →
    [ ] `T-VN-H22C`(Admin UI·파괴적 live)
- **Lane B — frontend hardening·PinVi 소비 API**
  - b0: [ ] `T-VN-45`(live endpoint/cache drift) →
    [ ] `T-VN-46`(npm optional tree) →
    [ ] `T-VN-48A` → [ ] `T-VN-48B` → [ ] `T-VN-48C` →
    [ ] `T-VN-48D`(mocked E2E drift) →
    [ ] `T-VN-49A` → [ ] `T-VN-49B` → [ ] `T-VN-49C` →
    [ ] `T-VN-49D`(React 구조 debt)
  - b1: [ ] `T-VN-11A` → [ ] `T-VN-11B`(service batch) →
    [ ] `T-VN-16A` → [ ] `T-VN-16B`(weather batch) →
    [ ] `T-VN-12A` → [ ] `T-VN-12B` → [ ] `T-VN-12C` →
    [ ] `T-VN-12D`(domain idempotency) →
    [ ] `T-VN-41A` → [ ] `T-VN-41B` → [ ] `T-VN-41C`(generation/outbox)
- **Wave 2 barrier 이후**
  - freeze(Lane A): [ ] `T-VN-31A` → [ ] `T-VN-31B` → [ ] `T-VN-31C`
  - Lane A: [ ] `T-VN-32A`~[ ] `T-VN-32C` →
    [ ] `T-VN-35A`~[ ] `T-VN-35D` →
    [ ] `T-VN-37A`~[ ] `T-VN-37C`
  - Lane B: [ ] `T-VN-33A`~[ ] `T-VN-33C` →
    [ ] `T-VN-38A`~[ ] `T-VN-38C` →
    [ ] `T-VN-34A`~[ ] `T-VN-34C` →
    [ ] `T-VN-36A`~[ ] `T-VN-36C` →
    [ ] `T-VN-40A`~[ ] `T-VN-40C`
  - 최종 단일 cutover: [ ] `T-VN-39`
- **보류/외부 추적**
  - [ ] `T-VN-H18` — GitHub approval provenance gate(보류: GitHub 자기 PR 승인 불가와
    required-review 운영 주체 결정 필요)
  - [ ] `T-101` — Materialized View 도입 검토(조건 발생 시)
  - PinVi #215는 PinVi 저장소 소유의 외부 추적이며 Map Agent A/B 실행 queue에 넣지 않는다.

## 공통 규율 (2026-07-28 개정)

- base는 **main**(`integration/t-vn`은 PR #790 합류로 폐지). 시작·PR 직전·머지 직후
  `origin/main` rebase. PR 하나는 task 하나만 소유.
- 첫 reviewable checkpoint를 바로 push해 PR을 먼저 열고, 구현·리뷰 반영·실데이터 검증을
  작은 의미 단위로 자주 커밋한다. 실패하면 검증된 직전 checkpoint부터 재개한다.
- **Lane A**: PR #869 다음 PR부터 적대적 리뷰어 **2명** 반영 후 n150 **파괴적 live E2E**
  (실데이터)로 검증하고 PR·CI green·머지. 작업 중 발견 항목은 tasks.md에 즉시 추가.
- **Lane B**: PR #869 다음 PR부터 적대적 리뷰어 **2명** 반영 후 n150 **실데이터 파괴적 Live UI
  E2E**를 통과하고 PR·CI green·머지한다. task 완료 시 상대 lane 2일치 PR 적대 리뷰 관행 유지.
- **우선순위(서비스 전 단계 — 사용자 지시 2026-07-26)**: **정확성·보안 최우선은 불변**
  (AGENTS.md), 그 아래 설계적 우수성 > 확장성 > 성능 > 불필요한 코드 반복(래퍼류) 금지.
  **prod 환경 보전·호환성·기존 문서 계약·최소 수정은 비제약** — 필요 시 DB 스키마·문서
  계약 수정 가능. AGENTS.md vNext 우선순위 단락에 동일 취지의 dated note를 둔다.
- migration 정본: 단일 head 유지(현 head `0066_curation_component_identity`). 후속 migration 소유자는
  PR 직전 단일 head를 재확인한 뒤 번호를 배정한다. 두 lane의 migration-bearing PR은 번호 예약부터
  머지까지 직렬화한다. forward migration 뒤에는 수용 조건이나 실패 복구가 명시적으로 요구하지 않는
  한 downgrade/rollback하지 않고 fresh clone·새 transaction으로 다음 검증을 이어간다.
- **리뷰어 수 전환(사용자 지시 2026-07-27)**: 현재 PR #869는 기존 지시대로 1명으로
  완결한다. 그다음 PR부터 문서 전용·rebase-only·기계적 변경을 포함해 적대적 리뷰어
  2명을 운용한다.
- pytest와 Playwright를 포함한 모든 검증은 n150 WSL SSH에서 실행한다. mocked e2e도 n150
  Linux가 정본이며, n150에서 실행할 수 없는 브라우저 제약이 확인될 때만 Windows를 fallback으로
  사용한다. live e2e는 항상 n150 파괴적 lane으로 실행한다.
- **실패 지점 재개**: 대용량 migration·실데이터 clone·build·fixture·Live E2E는 안전한
  checkpoint와 exact code/data identity를 기록한다. 실패한 단계 이전 산출물의 무결성을
  증명할 수 있으면 처음부터 반복하지 않고 실패 지점부터 재개한다. 무결성을 증명할 수 없거나
  선행 단계가 실패 원인에 영향받았을 때만 처음부터 실행하며, 보존한 격리 자원은 최종 성공 뒤
  정리한다.
- **cross-lane 순서 제약**: C6c pair capture와 #392는 이미 완료됐다. H07은 오래 열린
  #814/#403을 최신 main에 재배치하고 중복 assertion을 제거한 뒤 H07D→H07C 순서로 진행한다.
  Wave 2는 T-VN-31A~C freeze가 모두 머지되기 전에 시작하지 않으며, 최종 T-VN-39는
  T-VN-32~38·40의 모든 하위 task가 끝난 뒤에만 시작한다.
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

- [ ] T-VN-45 — **features map 실데이터 input-roundtrip endpoint·cache 대기 drift 제거**

  T-VN-42 live 중 `features-map-input-roundtrip.live.spec.ts`의 점 마커 시나리오가 UI가 이미
  `/v1/admin/features/in-bounds`로 전환된 뒤에도 public `/v1/features` bbox 응답만 기다려 5분
  timeout하는 drift를 확인했다. admin items/clusters 응답을 정본으로 추적하고 React Query cache hit로
  새 HTTP 응답이 없는 경우에도 map idle+실제 marker 상태로 수렴하도록 고쳐 false-red를 제거한다.

- [ ] T-VN-46 — **admin frontend npm optional tree 무결성 완결**

  T-VN-43의 exact npm 10.9.4 clean install은 audit 0과 exit 0이지만 `npm ls --all --json`의
  `problems`에 Sharp 0.35.3 WASM fallback optional graph 6개(`@emnapi/*`, `@img/sharp-wasm32`,
  `@napi-rs/wasm-runtime`, `@tybys/wasm-util`)를 `extraneous`로 남긴다. T-VN-43은 exact allowlist 밖
  문제를 fail-close하고 실제 native optimizer를 검증한다. 2026-07-28 실측 최신 npm은 12.0.1,
  Sharp 최신은 이미 사용 중인 0.35.3이다. pinned/latest npm의 동일 lockfile clean-install
  최소 재현으로 Arborist/Sharp 소유 경계를 확정하고 allowlist 자체를 제거한다. 쓰지 않는 direct
  dependency를 추가하거나 `npm ls` 출력을 숨기는 방식은 금지한다.

### T-VN-48 — mocked Playwright drift 단계별 제거

T-VN-43 gate에서 전체 269개 파일 중 165번째까지 52건의 기존 drift를 재현했다. 한 PR에서
전체 contract를 동시에 바꾸지 않고 실패 목록을 고정한 뒤 기능 경계별로 줄인다.

- [ ] T-VN-48A — **실패 manifest·runner 고정**

  exact main SHA, spec/test title, 최초 실패 단계, request/accessible-name/actor 차이를
  machine-readable artifact로 고정한다. retry로 사라지는 flake와 deterministic contract drift를
  분리하고 각 후속 PR이 자기 소유 실패만 줄였는지 fail-close한다.

- [ ] T-VN-48B — **Feature·큐레이션·검토 mocked 계약 정렬**

  `후보 A/B` 대 `feature A/B`, 한국어 dialog name, 실제 principal actor와 Feature/curation
  API route·payload drift를 현행 UI 계약에 맞춘다.

- [ ] T-VN-48C — **ops datasets·pipeline mocked 계약 정렬**

  `/v1/ops/datasets` list/detail/preview와 pipeline continuation·schedule recovery route mock을
  현행 canonical URL·principal 계약에 맞추고, stale legacy route가 다시 등록되면 실패시킨다.

- [ ] T-VN-48D — **나머지 shell/auth/files 계약과 전체 병렬 gate**

  앞 단계 소유 밖의 navigation/auth/files/offline drift를 정리한다. 전체 mocked suite를 n150
  Linux에서 workers=1과 CI 병렬 모드 모두 green으로 만들고 manifest 잔여를 0으로 닫는다.

### T-VN-49 — React Doctor 구조 debt 단계별 제거

`doctor.config.json`의 `no-giant-component` 19개와 `prefer-useReducer` 3개를 책임 경계별로 줄인다.
각 PR은 자기 파일의 예외를 같은 커밋에서 제거하고 기존 UI 계약을 보존한다.

- [ ] T-VN-49A — **Feature·review admin 상태기계 분해**

  dedup/enrichment/admin features/change requests/new feature 5개 giant component를
  query/mutation/form/panel 책임으로 분해하고 dedup/new feature의 reducer 후보를 상태기계로 옮긴다.

- [ ] T-VN-49B — **admin data-ops 상태기계 분해**

  curation collections/files/issues/offline uploads/POI cache targets 5개 giant component를
  분해하고 issues reducer 후보를 함께 제거한다.

- [ ] T-VN-49C — **public map·home 분해**

  curated feature map/features map/home 3개 giant component에서 지도 adapter가 아닌
  domain hook·표현 component 경계를 추출한다.

- [ ] T-VN-49D — **ops pipeline·datasets 분해와 예외 0**

  datasets/logs/execution detail/timeline/request/schedule 6개 giant component를 분해한다.
  완료 시 giant/reducer exact allowlist를 0개로 만들되 `live.ts` transport lifecycle과
  datasets external-event effect의 규칙별 최소 예외는 실제 false-positive 재현이 유지되는 동안
  별도 규칙 예외로 남긴다.


## Lane A 상세 — 열린 이슈·데이터 품질 하드닝

> 2026-07-27 open-PR·이슈 전수 확인에서 main에 잔존하는 미수정 버그/하드닝을 백로그화.
> 각 항목은 GitHub 이슈에 tasks.md 백로그 링크를 함께 기록한다.

- [ ] T-VN-H18 — **GitHub 실제 approval provenance gate 강제** — **보류(governance 결정, 2026-07-27)**:
  approval 필수화는 이후 모든 PR의 merge 경로를 바꾸므로 repo 소유자가 워크플로우 전환 시점을
  정해 착수한다. 현황: main branch protection 없음 확인, gh admin 권한 있음.
  구현 옵션 = branch protection(approval 1·last-push-approval·dismiss-stale·CI checks required) 또는
  merge 전 CI verifier(head SHA APPROVED≥1 + 회귀 테스트).

  Claude Code가 작성한 PR #841~#845·#847~#850·#852~#857·#859~#864를 전문 적대 감사한 결과 21건 모두
  GitHub `reviews: []` 상태로 머지돼 AGENTS의 "1 review approval" 계약을 충족하지 못했다. 과거
  approval provenance는 복구할 수 없으므로 후속 PR부터 branch protection 또는 merge 전 verifier가
  최신 head SHA에 대한 `APPROVED` review 1건 이상을 강제하도록 한다. 사용자 지시에 따라 self-review도
  GitHub가 `APPROVED`로 기록하면 유효하게 인정하되, 일반 comment나 bot status를 approval로 오인하지
  않고 required check·관리자 우회 경로까지 회귀 테스트한다.

- [ ] T-VN-H27 — **#819 HAProxy WebSocket tunnel timeout 적용·실증**

  docker-manager의 공개 가능한 base config에 `timeout tunnel`을 명시하고 local prod 값은
  gitignored runbook에서 결선한다. quiet 상태를 heartbeat 두 주기 이상 유지해 같은 ops-live
  socket이 재연결 없이 유지되는지 브라우저와 proxy metric 양쪽에서 확인한 뒤 #819를 닫는다.

- [ ] T-VN-H21 — **`kor-travel-geo` live 인증 preflight·dedup 5건 재실증**

  2026-07-28 실서비스 OpenAPI와 실제 400 body를 대조한 결과 Map client의 `lon`/`lat` payload는
  정합하고 실패 원인은 `E0100 query.key: Field required`였다. live test가 endpoint reachability만
  보고 보호 endpoint credential readiness를 검사하지 않은 것이 근인이다. 비밀을 출력·커밋하지
  않는 key 결선과 preflight를 추가하고 정상/오류 좌표 및 map dedup 5건을 실제 서비스에서
  통과시킨다. 인증 실패를 계약 drift로 오분류하거나 wrapper/fallback으로 우회하지 않는다.

- [ ] T-VN-H28A — **#673 concierge 주소 불일치 실데이터 재분류**

  H21의 인증된 reverse 경계 위에서 현재 후보 전체를 다시 실행해 과거 1,430/410 수치가 유효한지
  재기준화한다. provider 주소/행정코드, reverse 후보·거리·경계/해상 여부, 최종 drop 원인을
  재현 가능한 evidence manifest로 남기고 true-positive와 false-positive를 분리한다.

- [ ] T-VN-H28B — **#673 검증 규칙·재적재 회복 경로**

  H28A 증거를 기준으로 이름 substring 대신 authoritative 행정코드와 거리/경계 의미를 사용하는
  provider-neutral 규칙을 설계한다. payload hash가 같아도 과거 validation drop을 재평가할 수 있는
  replay 경로와 관측 metric을 추가하고 실제 후보 복구를 검증한 뒤 #673을 닫는다.

### T-VN-H25 — 공식 curation stale Feature reference 재해소

T-VN-47 격리 실데이터 clone에서 공식 CSV의 고유 `feature_id` 158개 중 54개가 현재
`feature.features`에 존재하지 않았다. H24가 stable component 기반 미연결 membership으로
무손실 보존하므로 증거 생성과 mutation을 분리한다.

- [ ] T-VN-H25A — **stale reference evidence manifest**

  provider provenance·이름·주소·Feature lifecycle/merge history를 동일 DB snapshot에서 대조해
  candidate·confidence·근거와 unresolved 사유를 manifest로 만든다. 좌표 근접만으로 자동 승인하지
  않고 이 단계에서는 CSV/DB target을 바꾸지 않는다.

- [ ] T-VN-H25B — **검토된 high-confidence reference 적용**

  H25A에서 승인된 항목만 공식 CSV의 `feature_id`에 반영하고, 불확실한 component는 미연결 상태와
  근거를 유지한다. 5개 CSV의 linked/unresolved 수치, preview/commit, REST/UI를 같은 실데이터
  snapshot에서 검증한다.

### T-VN-H22 — 0065 curation owner quarantine 재분류

migration 0065가 원 projection durable link 없는 canonical-only item을 보존한 quarantine은
read/decision/write/UI를 한 PR에 몰지 않는다.

- [ ] T-VN-H22A — **quarantine read model·conflict preview**

  원본 collection·후보 theme/source·격리 근거와 exact identity conflict를 side effect 없이
  조회하는 repository/API projection을 만든다. 자동 target 추정은 하지 않는다.

- [ ] T-VN-H22B — **원자적 reclassification command**

  운영자가 target collection 이동 또는 별도 collection 확정을 선택하는 command를 구현한다.
  parent collection→item lock, revision/actor 감사, conflict fail-close, 빈 quarantine 정리를
  한 transaction에서 보장한다.

- [ ] T-VN-H22C — **Admin UI·실데이터 파괴적 수용**

  H22A/B 계약만 소비하는 검토 UI를 만들고 격리 clone에서 충돌 preview·이동·별도 확정·빈
  collection 정리를 파괴적으로 검증한다.

## 이슈 종결 추적

> landing task와 완료 조건이 동일한 열린 이슈만 함께 닫는다. LIVE-01 후속 OPEN 7건은 Lane A
> `T-VN-H16`/`T-VN-H17`에서 독립 재검증해 **7건 전부 close**했다. 6건은 H16
> (dm#63·#70·map#712·#719·#777·#694), map#684는 H17에서 조건 #8을 "write/error UI 엣지는
> mock, read·URL·freshness + write 계약은 live"로 명시 축소한 뒤 close했다.

- **task로 승격**: map #673=`T-VN-H28A/B`, map #819=`T-VN-H27`,
  map #812/#815=`T-VN-H07C/D`.
- **종결**: map #738은 lane 분배 정본을 본 문서로 이관해 닫혔다.
- **외부 추적**: PinVi #215(post-review cleanup 잔여 — ADR-045 VWorld 불투명 자격증명
  hard-gate 등).

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
