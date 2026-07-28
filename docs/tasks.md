# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스 (2026-07-28 PR #869 후 전면 재감사)

> PR #869 merge `25e9304b` 직후 `tasks.md`·`tasks-done.md`·실코드·Map/PinVi/
> docker-manager/geo의 열린 PR·이슈를 다시 대조했다. Map의 열린 이슈는 #673·#812·#815·#819,
> 본 감사 PR #870을 제외한 기존 열린 PR은 #814 한 건이며, PinVi의 관련 열린 PR은 #403이다.
> `T-VN-H21`의 실서비스 400에서 보호 endpoint `key` 결선 누락을 첫 blocker로 확인했다.
> 인증 뒤 downstream drift 존재 여부는 아직 미검증이다. 큰 task는 독립 검증·forward recovery가
> 가능한 실행 단위로 아래처럼 분해한다.

**Lane A (Claude Code)**와 **Lane B (codex)**는 서로 병렬 실행한다. 각 lane 내부는 아래 순서를
지키며, 같은 migration head·OpenAPI 정본·같은 cross-repo pair를 만지는 시점만 공통 규율의
barrier로 직렬화한다.

- **Lane A — cross-repo 계약·운영·데이터 품질**
  - a0: [x] `T-VN-H07B`(PinVi #403 재감사·landing) →
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
  - b0: [ ] `T-VN-48A` → [ ] `T-VN-48B` → [ ] `T-VN-48C` →
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
  - Lane A: [ ] `T-VN-32A` → [ ] `T-VN-32B` → [ ] `T-VN-32C` →
    [ ] `T-VN-35A` → [ ] `T-VN-35B` → [ ] `T-VN-35C` → [ ] `T-VN-35D` →
    [ ] `T-VN-37A` → [ ] `T-VN-37B` → [ ] `T-VN-37C`
  - Lane B shadow: [ ] `T-VN-33A` → [ ] `T-VN-33B` → [ ] `T-VN-33C` →
    [ ] `T-VN-38A` → [ ] `T-VN-38B` → [ ] `T-VN-38C` →
    [ ] `T-VN-34A` → [ ] `T-VN-34B` → [ ] `T-VN-34C` →
    [ ] `T-VN-36A` → [ ] `T-VN-36B` → [ ] `T-VN-36C`
  - 32~38 join barrier 뒤 Lane B: [ ] `T-VN-40A` → [ ] `T-VN-40B` →
    [ ] `T-VN-40C`
  - 최종 단일 cutover: [ ] `T-VN-39`
- **보류/외부 추적**
  - [ ] `T-VN-H18` — GitHub approval provenance gate(보류: GitHub 자기 PR 승인 불가와
    required-review 운영 주체 결정 필요)
  - [ ] `T-101` — Materialized View 도입 검토(조건 발생 시)
  - [ ] `T-VN-EXT-PINVI-215` — PinVi #215 외부 추적(Map Agent A/B queue 밖)

## 공통 규율 (2026-07-28 개정)

- base는 **main**(`integration/t-vn`은 PR #790 합류로 폐지). 시작·PR 직전·머지 직후
  `origin/main` rebase. PR 하나는 task 하나만 소유.
- 첫 reviewable checkpoint부터 원격 feature branch에 작은 의미 단위로 자주 커밋·push하되,
  PR은 구현·적대 리뷰 반영·실데이터 검증·최종 main rebase를 모두 마친 뒤 **머지 직전**에만
  연다. 실패하면 검증된 직전 checkpoint부터 재개한다.
- **Lane A**: PR #869 다음 PR부터 적대적 리뷰어 **2명** 반영 후 n150 **파괴적 live E2E**
  (실데이터)로 검증하고 PR·CI green·머지. 작업 중 발견 항목은 tasks.md에 즉시 추가.
- **Lane B**: PR #869 다음 PR부터 적대적 리뷰어 **2명** 반영 후 n150 **실데이터 파괴적 Live UI
  E2E**를 통과하고 PR·CI green·머지한다. task 완료 시 상대 lane 2일치 PR 적대 리뷰 관행 유지.
- **일회성 문서 예외**: 사용자 지시에 따라 PR #870은 코드·DB·runtime 변경이 없는 task 재배치
  문서 PR이므로 적대적 리뷰어 2명과 문서/보안 gate는 유지하되 파괴적 Live UI를 실행하지 않고
  CI 결과를 기다리지 않고 머지한다. 이 예외는 후속 문서 PR에 자동 승계되지 않는다.
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
  2명을 운용한다. 다만 두 리뷰어가 본 변경의 전체 diff를 함께 검토한 마지막 exact SHA 이후
  누적 후속 delta 전체가 기존 지적의 국소 반영, 완료 사실 기록 또는 표기·기계적 문서 갱신뿐이면
  원 리뷰어 1명의 재검토로 마친다. runtime·API 계약·DB schema·migration·보안 동작뿐 아니라
  task 범위·순서·완료 조건과 CI·deploy·runbook 운영 의미를 바꾸거나 범위가 애매한 변경이 누적
  delta에 하나라도 섞이면 다시 2명이 전체 누적 delta를 검토하고 기준 SHA를 갱신한다.
- pytest와 Playwright를 포함한 모든 검증은 n150 WSL SSH에서 실행한다. mocked e2e도 n150
  Linux가 정본이며, n150에서 실행할 수 없는 브라우저 제약이 확인될 때만 Windows를 fallback으로
  사용한다. live e2e는 항상 n150 파괴적 lane으로 실행한다.
- **실패 지점 재개**: 대용량 migration·실데이터 clone·build·fixture·Live E2E는 안전한
  checkpoint와 exact code/data identity를 기록한다. 실패한 단계 이전 산출물의 무결성을
  증명할 수 있으면 처음부터 반복하지 않고 실패 지점부터 재개한다. 무결성을 증명할 수 없거나
  선행 단계가 실패 원인에 영향받았을 때만 처음부터 실행한다. 최종 성공 뒤 API/UI process는
  정지하되 격리 DB·dump와 migration head·checksum·row count·fixture identity처럼 명시적으로
  허용한 redacted immutable checkpoint는 PR 성공만으로 즉시 삭제하지 않는다. Playwright
  `storageState`/cookie, raw trace, 실데이터 screenshot, 민감 로그, 임시 env·session secret은
  재사용하지 않고 성공·실패와 무관하게 실행 직후 안전하게 폐기한다. PR 머지 후 다음 task
  착수 전에 migration head·schema/fixture 계약·파괴적 실행 잔여물·코드/API 호환성·디스크
  여유를 확인해 재사용 가능하면 이름·head·fixture identity와 근거를 `resume.md`/
  `journal.md`에 기록하고, 불가능할 때만 해당 격리 resource를 정확히 정리한다.
- **cross-lane 순서 제약**: C6c pair capture와 #392, H07A의 Map #814 landing
  (`259a9ec5`)은 이미 완료됐다. H07B는 오래 열린 PinVi #403을 최신 main에 재배치하고 중복
  assertion을 제거한 뒤 H07D→H07C 순서로 진행한다.
  H22C는 같은 curation frontend를 만지는 T-VN-48B·49B 뒤에 시작한다. T-VN-12A의 command
  inventory freeze는 H22B의 reclassification command가 머지된 뒤 시작해 curation idempotency가
  누락되지 않게 한다. Wave 2는 T-VN-31A~C freeze가 모두 머지되기 전에 시작하지 않는다.
  T-VN-40은 양 lane의 T-VN-32~38 하위 task가 모두 끝난 join barrier 뒤에 시작하며,
  최종 T-VN-39는 T-VN-32~38·40의 모든 하위 task가 끝난 뒤에만 시작한다.
- **OpenAPI compatible-pair gate**: H07C 이후 admin/user OpenAPI를 바꾸는 모든 task는
  per-surface digest 갱신, docker-manager compatible-pair 재-capture, C7 attestation을 같은
  완료 조건으로 갖는다. stale manifest 상태로 다음 task나 배포를 시작하지 않는다.
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


## 보류 — 실행 lane 외 거버넌스 결정 대기

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

## Lane A 상세 — 열린 이슈·데이터 품질 하드닝

> 2026-07-27 open-PR·이슈 전수 확인에서 main에 잔존하는 미수정 버그/하드닝을 백로그화.
> 각 항목은 GitHub 이슈에 tasks.md 백로그 링크를 함께 기록한다.

- [ ] T-VN-H27 — **#819 HAProxy WebSocket tunnel timeout 적용·실증**

  docker-manager의 공개 가능한 base config에 `timeout tunnel`을 명시하고 local prod 값은
  gitignored runbook에서 결선한다. quiet 상태를 heartbeat 두 주기 이상 유지해 같은 ops-live
  socket이 재연결 없이 유지되는지 브라우저와 proxy metric 양쪽에서 확인한 뒤 #819를 닫는다.

- [ ] T-VN-H21 — **`kor-travel-geo` live 인증 preflight·dedup 5건 재실증**

  2026-07-28 실서비스 OpenAPI와 실제 400 body를 대조한 결과 Map client의 `lon`/`lat` payload는
  정합하고 첫 400 blocker는 `E0100 query.key: Field required`였다. test 코드는 settings key를
  client에 전달하지만 실행 환경에 값이 없어 route 처리 전에 막혔으므로, 인증 뒤 runtime 계약에
  추가 drift가 있는지는 아직 알 수 없다. 비밀을 출력·커밋하지 않는 key 결선과 preflight를
  추가하고 정상/오류 좌표 및 map dedup 5건을 실제 서비스에서 통과시킨다. 첫 blocker만으로
  downstream 정상까지 추정하거나 wrapper/fallback으로 우회하지 않는다.

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
  한 transaction에서 보장한다. actor-scoped `Idempotency-Key`, body fingerprint와 terminal
  result replay를 처음부터 포함하고 T-VN-12A가 이 계약을 inventory 기준선으로 승계한다.

- [ ] T-VN-H22C — **Admin UI·실데이터 파괴적 수용**

  H22A/B 계약만 소비하는 검토 UI를 만들고 격리 clone에서 충돌 preview·이동·별도 확정·빈
  collection 정리를 파괴적으로 검증한다. 같은 `curation-collections-client.tsx`와 mocked spec을
  만지는 T-VN-48B·49B가 모두 머지된 뒤 최신 구조 위에서 시작한다.

## 이슈 종결 추적

> landing task와 완료 조건이 동일한 열린 이슈만 함께 닫는다. LIVE-01 후속 OPEN 7건은 Lane A
> `T-VN-H16`/`T-VN-H17`에서 독립 재검증해 **7건 전부 close**했다. 6건은 H16
> (dm#63·#70·map#712·#719·#777·#694), map#684는 H17에서 조건 #8을 "write/error UI 엣지는
> mock, read·URL·freshness + write 계약은 live"로 명시 축소한 뒤 close했다.

- **task로 승격**: map #673=`T-VN-H28A/B`, map #819=`T-VN-H27`,
  map #812/#815=`T-VN-H07C/D`.
- **종결**: map #738은 lane 분배 정본을 본 문서로 이관해 닫혔다.
- [ ] T-VN-EXT-PINVI-215 — **PinVi #215 외부 follow-up 추적**

  post-review cleanup 잔여(ADR-045 VWorld 불투명 자격증명 hard-gate 등)는 PinVi 저장소가
  소유한다. Map Agent A/B 실행 queue에는 넣지 않고 PinVi #215가 닫힐 때 상태만 동기화한다.

## Lane B 상세 — b1 PinVi 결합

### T-VN-11 — service batch 5-state 계약

현재 `features.py` batch는 `found/missing` 2-state이고 코드 주석도 5-state를 후속으로
명시한다. producer 계약과 consumer cutover를 분리한다.

- [ ] T-VN-11A — **Map 5-state batch projection**

  `found|retired|suppressed|missing|unchanged` item과 row revision을 한 set-based query snapshot에서
  반환한다. 공개 projection과 tombstone/visibility 판정을 분리하고 upstream transport 실패를
  `503`으로 모델링한다.

- [ ] T-VN-11B — **PinVi typed consumer cutover**

  PinVi가 5-state/revision을 exhaustively 처리하고 이전 2-state 추측을 제거한다. vendored
  OpenAPI/consumer contract와 실제 compatible pair live를 같은 cutover에서 고정한다.

### T-VN-16 — weather batch와 부모 404

현재 단건 forecast만 존재한다. Map set-based API와 PinVi 소비를 분리한다.

- [ ] T-VN-16A — **Map set-based weather batch**

  feature ID 집합과 `target_at`/`known_at`을 받아 한 snapshot에서 timeline/current를 반환한다.
  존재하지 않는 parent를 빈 weather 결과와 구분하고 단건도 같은 parent existence 판정을 재사용한다.

- [ ] T-VN-16B — **PinVi weather batch 소비 cutover**

  PinVi의 단건 N+1을 batch 호출로 교체하고 parent 404·weather 없음·transport 실패를 각각 처리한다.
  query count와 field-level contract를 회귀 테스트로 고정한다.

### T-VN-12 — domain-owned Idempotency-Key 전개

기존 feature-update·pipeline/schedule ledger를 기준 구현으로 두고, 모든 write endpoint가 아니라
네트워크 재시도 가능한 command만 대상으로 한다.

- [ ] T-VN-12A — **retryable command inventory·계약 freeze**

  OpenAPI write operation을 domain/actor/transaction/advisory-lock/현재 dedupe 의미로 분류하고
  idempotency 적용·비적용 근거를 고정한다. `admin_features`의 `natural_key` 같은 body surrogate를
  ledger로 오인하지 않는다.

- [ ] T-VN-12B — **Feature·curation·review command ledger**

  T-VN-12A에서 retryable로 분류된 Feature/curation/review command에 actor-scoped key,
  canonical body fingerprint, terminal result replay, 다른 body 재사용 `409`를 구현한다.

- [ ] T-VN-12C — **import·offline·backup/restore command ledger**

  write mutex가 있는 import/offline/backup/restore command의 기존 advisory lock과 같은 transaction
  경계에 ledger를 결합한다. 응답 유실과 process 재시작 뒤에도 결과를 재생하고 destructive command가
  두 번 실행되지 않음을 증명한다.

- [ ] T-VN-12D — **consumer cutover·surrogate 제거**

  UI/CLI가 명시적 `Idempotency-Key`를 생성·재사용하도록 전환하고 body natural-key나 client-side
  dedupe 중복을 제거한다. 적용 대상 전체의 key reuse/replay matrix를 n150에서 검증한다.

### T-VN-41 — cache-target generation·outbox 전파

- [ ] T-VN-41A — **source generation·restore epoch**

  existing external identity/exact scope를 유지하면서 source generation과 restore epoch를 schema에
  도입하고 restore/backfill 시 단조성·중복 억제를 고정한다.

- [ ] T-VN-41B — **transaction-coupled outbox writer**

  target/link/update 결과와 같은 transaction에서 generation-bearing outbox event를 기록한다.
  critical write path는 relay I/O를 기다리지 않고 commit/rollback 원자성만 보장한다.

- [ ] T-VN-41C — **relay·reconciliation·consumer enable**

  lease/retry/dead-letter/replay가 있는 relay와 DB 대조 reconciliation을 추가한다. backfill checksum
  뒤 critical path 밖에서 PinVi 소비를 enable하고 누락·중복·restore epoch 전환을 live로 증명한다.

## Lane A 상세 — T-VN-H07 cross-repo 계약 완결

Map #814 residual은 `259a9ec5`로 landing해 `tasks-done.md`에 보존했다. 남은 PinVi #403은
재감사 기준 시점 최신 main보다 13 commits 뒤처졌고, 오래된 task 문서 commit을 재생하지 않고
H07A의 실제 user OpenAPI SHA와 대조한 residual consumer contract만 남긴다.

- [x] T-VN-H07B — **PinVi #403 residual contract 재감사·landing** (PinVi PR #415, #403 대체)

  재감사 결과 #403의 pin 대상(공개 curated 표면)은 PinVi가 **호출하지 않는** 경로였다 —
  `_CLIENT_PATHS`에 curated 없음, 큐레이션 런타임 표면은 admin detail-snapshot(H07D 소유),
  producer exact 고정은 H07A 소유. curated pin 전량 제거 후 **PinVi가 실제로 읽는 필드**의
  typed consumer contract(21 schema)로 대체했다. H07A의 실제 user OpenAPI SHA와 대조해 stale
  스냅샷(`91b30f40`@`cf1f0bba`, 174 commits 뒤)을 Map main `8880c29b`/`0a7f1684`로 재동기화.
  경로→컨테이너→item·map value·envelope `meta` 사슬과 `model_validate` 표면의 model 결합까지
  고정. 상세는 tasks-done 2026-07-28.

- [ ] T-VN-H07D — **#815 admin detail-snapshot field-level contract·freshness**
  (① Map half **완료** — payload 타입화 + 계약 게이트. ② PinVi half(vendor·소비자 계약·freshness
  CI) 남음. cross-repo 2 PR이라 둘 다 landing해야 완료.)

  PinVi 런타임이 실제 소비하는 admin detail-snapshot의 plan/item required/type/enum을 Map full
  OpenAPI와 PinVi vendored snapshot 양쪽에서 고정한다. admin/user snapshot freshness를 CI에서
  실제 비교해 skip으로 green이 되는 경로를 제거한다.

- [ ] T-VN-H07C — **#812 compatible-pair manifest v5**

  docker-manager compatible-pair에 Map per-surface OpenAPI digest manifest의 SHA를 추가하고
  capture·validate·deploy를 모두 v5로 전환한다. Map export drift와 C7 attestation을 같은 digest에
  연결하고 ADR-076을 개정한다.

## Wave 2 상세 — 구조 전환

> 실행 순서는 31A~C(freeze) → 32~38(shadow, 두 lane 병렬) → 40 → 39(cutover 마지막)다.
> ADR-066~075가 목표 스펙 정본이다. 각 migration task는 forward-only 격리 clone에서 검증하고,
> 명시적 downgrade 수용 조건이 없는 한 전진 뒤 rollback하지 않는다.

### T-VN-31 — vNext target freeze

ADR은 존재하지만 목표 DDL/OpenAPI diff/실행 제약 artifact는 없다. 구현과 freeze를 분리한다.

- [ ] T-VN-31A — **목표 DDL·데이터 불변식 freeze**

  schema/table/column/type/FK/CHECK/index/view/trigger와 backfill 전후 불변식을 실행 가능한 SQL
  artifact로 고정한다. migration 번호와 구현 SQL은 아직 넣지 않는다.

- [ ] T-VN-31B — **목표 OpenAPI·consumer diff freeze**

  admin/user/PinVi surface별 추가·삭제·rename·enum/status/error 변화를 machine-readable diff로
  고정하고 consumer-first 배포 순서와 호환을 버릴 시점을 명시한다.

- [ ] T-VN-31C — **제약 test·복구 preflight freeze**

  목표 DDL/OpenAPI를 위반하는 fixture와 shadow checksum, forward recovery, write-fence preflight를
  executable contract로 만든다. 31A/B artifact drift를 CI에서 fail-close한다.

### T-VN-32 — UUID identity shadow 전환 (Lane A)

- [ ] T-VN-32A — **UUID schema·deterministic backfill**

  UUID identity와 legacy alias table을 추가하고 같은 snapshot에서 deterministic backfill·UNIQUE/FK
  불변식을 고정한다. 기존 문자열 ID는 아직 제거하지 않는다.

- [ ] T-VN-32B — **Map consumer-first dual read/write**

  repository/API/notice lineage를 UUID 정본으로 읽고 alias를 경계에서만 해석한다. 신규 write는 UUID와
  alias를 원자 생성하고 legacy-only 신규 행을 차단한다.

- [ ] T-VN-32C — **PinVi alias-map cutover·legacy write fence**

  PinVi consumer를 UUID+alias contract로 전환하고 양 저장소 checksum을 맞춘다. legacy write를
  fence하되 legacy ID 제거는 T-VN-39 soak 뒤로 남긴다.

### T-VN-33 — provider dataset 정본 전환 (Lane B)

- [ ] T-VN-33A — **provider_datasets schema·backfill**

  provider/dataset 정본 row와 composite identity를 만들고 현재 policy/source/operation 참조를
  중복·orphan 없이 backfill한다.

- [ ] T-VN-33B — **writer·reader FK cutover**

  참조 table과 writer를 canonical dataset FK로 전환하고 전환 중 entity-record identity 불일치를
  composite FK로 차단한다.

- [ ] T-VN-33C — **canonical query cutover·legacy 제거 manifest**

  read/query를 canonical dataset FK로 전환하고 중복 column을 read-only로 fence한다. EXPLAIN과
  checksum을 고정하되 column/index의 물리 삭제는 soak 뒤 T-VN-39가 수행하도록 removal manifest에
  남긴다.

### T-VN-34 — 직교 상태 모델 전환 (Lane B)

- [ ] T-VN-34A — **3축 상태 schema·backfill**

  lifecycle/publication/quality를 별도 typed column으로 추가하고 기존 status를 무손실 매핑한다.
  허용되지 않는 결합을 DB CHECK로 거부한다.

- [ ] T-VN-34B — **public projection·partial index cutover**

  `public_features` view를 3축 predicate 정본으로 바꾸고 실제 hot predicate와 일치하는 partial
  index를 추가한다.

- [ ] T-VN-34C — **writer/API/UI cutover·legacy status fence**

  provider/admin writer와 admin/user DTO/UI를 3축으로 전환하고 old status 신규 write를 차단한다.
  legacy column/index는 held component rollback을 위해 유지하고 T-VN-39 removal manifest에 넣는다.

### T-VN-35 — typed subtype 분해 (Lane A)

- [ ] T-VN-35A — **feature core·point subtype**

  공통 core와 point geometry/category 제약을 분리하고 기존 place/price/weather point row를
  shadow backfill한다.

- [ ] T-VN-35B — **event·notice subtype**

  event/notice 전용 column과 시간/lineage 불변식을 typed table로 옮기고 혼합 kind row를 거부한다.

- [ ] T-VN-35C — **route·area subtype**

  route/area geometry type·SRID·category 제약과 parent/sibling 관계를 typed table로 옮긴다.

- [ ] T-VN-35D — **repository/API projection cutover**

  kind별 repository/read model을 subtype join으로 전환하고 nullable mega-row 분기를 제거한다.
  subtype별 checksum·query plan을 독립 검증한다.

### T-VN-36 — field override 단일화 (Lane B)

- [ ] T-VN-36A — **override schema·whole-row freeze backfill**

  field별 value/provenance/revision/tombstone을 저장하는 정본을 만들고 기존 whole-row freeze를
  동일 effective projection으로 backfill한다.

- [ ] T-VN-36B — **provider/admin writer cutover**

  provider upsert와 admin patch가 field override를 같은 transaction에서 갱신하도록 전환하고
  concurrency/merge precedence를 DB 제약과 회귀 테스트로 고정한다.

- [ ] T-VN-36C — **effective projection 단일화·legacy freeze fence**

  read model을 한 effective projection으로 통일하고 repository별 중복 `CASE` write/read 분기를
  비활성화한다. whole-row freeze column/trigger는 rollback shadow로 유지하고 물리 삭제 목록을
  T-VN-39에 넘긴다.

### T-VN-37 — typed notice state (Lane A)

- [ ] T-VN-37A — **notice range schema·backfill**

  유효 기간과 lineage/current state를 typed range/FK/CHECK로 표현하고 오염 timestamp를 격리한다.

- [ ] T-VN-37B — **notice writer/read query cutover**

  notice provider writer와 public/admin history/current query를 range/index 기반으로 전환한다.

- [ ] T-VN-37C — **방어 cast·lineage anti-join 제거**

  T-VN-06의 잠정 cast와 공개 hot path anti-join을 제거하고 동등 결과·EXPLAIN·오염 입력 거부를
  검증한다.

### T-VN-38 — weather·price current summary (Lane B)

- [ ] T-VN-38A — **weather current summary**

  bitemporal 원본 이력을 보존하면서 identity당 current weather를 원자 유지하는 summary와
  reconciliation을 추가한다.

- [ ] T-VN-38B — **price current summary**

  `provider + price_domain + product_key` identity당 current price summary와 reconciliation을
  추가하고 restore/backfill generation을 구분한다.

- [ ] T-VN-38C — **bbox/detail set-based cutover**

  per-row LATERAL을 weather/price summary set join으로 바꾸고 old query를 normal path에서
  비활성화한다. rollback shadow index는 보존해 T-VN-39 removal manifest로 넘기고,
  cardinality·freshness·EXPLAIN을 실데이터로 고정한다.

### T-VN-40 — curation write model 단일화 (Lane B)

- [ ] T-VN-40A — **legacy writer inventory·write fence**

  `curated_features` overlay를 쓰는 route/job/trigger/repository를 전수 고정하고 신규 legacy write를
  차단한다. canonical curation과 effective projection checksum을 만든다.

- [ ] T-VN-40B — **candidate lifecycle 분리·consumer cutover**

  자동 후보를 `theme_feature_candidates` lifecycle로 분리하고 admin/public/PinVi consumer가
  `curation_collections/items` 정본만 읽도록 전환한다.

- [ ] T-VN-40C — **legacy surface fence·removal manifest**

  checksum과 consumer cutover 뒤 overlay 신규 write와 normal routing을 차단한다. held component
  rollback에 필요한 repository/trigger/table은 soak 동안 보존하고 exact removal manifest를
  T-VN-39에 넘긴다. 신규 호환 shim은 만들지 않는다.

- [ ] T-VN-39 — **KTM·PinVi write-fence cutover**

  보존 분류, restore/PITR 또는 journal 검증, shadow checksum, consumer-first 배포, write fence,
  순차 전환과 soak를 ADR-075 절차대로 수행한다. held component rollback 창이 닫힌 뒤
  T-VN-33C·34C·36C·38C·40C removal manifest의 legacy column/index/route/repository/trigger/table과
  T-VN-38C의 rollback shadow index를 이 task에서만 물리 삭제한다. T-VN-32~38·40 완료 뒤
  마지막이다.

## T-101 — Materialized View 도입 검토 (보류)

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
