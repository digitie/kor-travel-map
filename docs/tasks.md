# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스 (2026-07-28 PR #869 후 전면 재감사)

> PR #869 merge `25e9304b` 직후 `tasks.md`·`tasks-done.md`·실코드·Map/PinVi/
> PR #869 당시 전면 감사에서 시작했으며 이후 완료·보류 상태를 매 PR 갱신한다.
> 큰 task는 독립 검증·forward recovery가 가능한 실행 단위로 아래처럼 분해한다.

**Lane A (Claude Code)**와 **Lane B (codex)**는 서로 병렬 실행한다. 각 lane 내부는 아래 순서를
지키며, 같은 migration head·OpenAPI 정본·같은 cross-repo pair를 만지는 시점만 공통 규율의
barrier로 직렬화한다.

- **Lane A — cross-repo 계약·운영·데이터 품질**
  - a0: [x] `T-VN-H07B`(PinVi #403 재감사·landing) →
    [x] `T-VN-H07D`(#815 admin snapshot/freshness) →
    [x] `T-VN-H07C`(#812 — v5 승격 기각, ADR-079)
  - a1: [x] `T-VN-H29`(PinVi 검색 좌표 null 복구 — H07D 파생) →
    [x] `T-VN-H21`(geo live 인증 결선 검증·5건 재실증) →
    [x] `T-VN-H28A/B`(#673 실데이터 오탐 분류 + 검증 규칙·회복 — 한 PR) →
    [x] `T-VN-H25A`(미연결 membership 증거·전제 정정) →
    [x] `T-VN-H30A`(관측 durable화) + [ ] `T-VN-H30B/C`(실적재·provider 재검증) →
    [ ] `T-VN-H25B`(CSV 역반영 8건·매칭 재실행) →
    [x] `T-VN-H30A/B`(관측 durable화·실적재 검증) + [ ] `T-VN-H30C`(재작업 필요) →
    [~] `T-VN-H25B`(CSV 역반영 5건·매칭 재실행 — 3건 오링크 배제, 미충족 AC는 H34) →
    [~] `T-VN-H33`(오링크 3건 해제 — 공개 오노출 해소, durable하지 않음) →
    [ ] `T-VN-H36`(import가 이름만으로 자동 링크 — H33 파생, H35보다 선행) →
    [ ] `T-VN-H35`(prod 마이그레이션 지연 0064~0067 — H33 부수 발견) →
    [ ] `T-VN-H34`(H25A/H25B 미충족 AC 마무리) →
    [ ] `T-VN-H31`(등대 공급원 부재 — H25A 파생) →
    [ ] `T-VN-H32`(주소 검증 finding 자동 close — H30A 후속) →
    [ ] `T-VN-H22A`(quarantine read/preview) →
    [ ] `T-VN-H22B`(원자적 재분류 command) →
    [ ] `T-VN-H22C`(Admin UI·파괴적 live)
- **Lane B — frontend hardening·PinVi 소비 API**
  - b0: [x] `T-VN-48D`(final exact Mocked/Live) →
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
  - [ ] `T-VN-H27` — #819 HAProxy WebSocket tunnel timeout(**보류: 운영자 환경 필요**,
    사용자 지시 2026-07-29). 프록시는 **OPNsense 라우터의 HAProxy**이고 저장소에 config가 없다
    (docker-manager `*haproxy*` 0건, n150은 haproxy inactive·`/etc/haproxy/` 없음). 설정 적용도
    proxy metric 확인도 라우터 접근이 필요해 에이전트가 실행할 수 없다. 라우터에
    `timeout tunnel` 적용 후 quiet 2주기 실증 → #819 close.
  - [ ] `T-VN-H18` — GitHub approval provenance gate(보류: GitHub 자기 PR 승인 불가와
    required-review 운영 주체 결정 필요)
  - [ ] `T-101` — Materialized View 도입 검토(조건 발생 시)
  - [ ] `T-VN-EXT-PINVI-215` — PinVi #215 외부 추적(Map Agent A/B queue 밖)

## 공통 규율 (2026-07-28 개정)

- base는 **main**(`integration/t-vn`은 PR #790 합류로 폐지). 시작·PR 직전·머지 직후
  `origin/main` rebase. PR 하나는 task 하나만 소유.
- **Claude Code PR 감사 순서(사용자 지시 2026-07-29)**: 개별 T-VN task는 자기 구현·적대
  리뷰·Live·CI를 먼저 끝내 PR을 머지한다. Claude Code PR 사후 감사는 task PR 머지 뒤
  별도 후속 단계에서 issue를 만들고 진행하며, 진행 중 task의 PR 생성·머지를 지연시키거나
  그 PR에 새 감사를 합치지 않는다. T-VN-48에는 규칙 변경 전에 완료한 issue #881과 PR #888
  감사 수정만 유지한다.
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
- migration 정본: 단일 head 유지(현재 Lane B 후보 `0068_integrity_last_seen`). 후속 migration 소유자는
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
- **DB 검증 위험 기반 선택(2026-07-29)**: 전체 실데이터 clone 생성은 기존 clone의 출처·
  container/system identity·migration head·schema/content identity가 필요한 계약을 충족하지
  않을 때만 한다. 전체 dump 복원 검증은 migration/schema, backup·restore, checkpoint,
  database ownership처럼 복구 가능성에 직접 영향을 주는 코드가 바뀌었거나 서명된 checkpoint가
  없거나 무효일 때만 1회 수행한다. 동일 migration head + schema/content hash + dump SHA256 +
  checkpoint 계약 버전이 유지되면 다음 task와 최종 비DB 문서 commit에서 재사용하며, exact source
  revision 변경만으로 전체 복원을 반복하지 않는다. 일반 repository/query 변경은 관련 통합
  테스트, frontend/mocked/docs-only 변경은 해당 비DB gate만 수행한다.
- **cross-lane 순서 제약**: C6c pair capture와 #392, H07A~D는 완료됐다.
  H22C는 완료된 T-VN-48B에 이어 같은 curation frontend를 만지는 T-VN-49B가 머지된 뒤
  시작한다. T-VN-12A의 command
  inventory freeze는 H22B의 reclassification command가 머지된 뒤 시작해 curation idempotency가
  누락되지 않게 한다. Wave 2는 T-VN-31A~C freeze가 모두 머지되기 전에 시작하지 않는다.
  T-VN-40은 양 lane의 T-VN-32~38 하위 task가 모두 끝난 join barrier 뒤에 시작하며,
  최종 T-VN-39는 T-VN-32~38·40의 모든 하위 task가 끝난 뒤에만 시작한다.
- **OpenAPI 계약 변경 규율(2026-07-29 개정)**: admin/user OpenAPI를 바꾸는 task는
  두 spec을 재생성하고 실제 소비자가 핀한 Map commit에서 vendored 스냅샷을 다시 추출해
  `contract-pin-consistency`를 통과시킨다. 소비자가 읽지 않는 파생 digest manifest는 만들지
  않는다. compatible-pair 재-capture·C7 attestation은 배포 이미지 revision 결박과 중복이므로
  OpenAPI 변경 완료 조건이 아니다.
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

- [ ] T-VN-H27 — **#819 HAProxy WebSocket tunnel timeout 적용·실증** — **보류(2026-07-29)**

  조사 결과 프록시는 **OPNsense 라우터의 HAProxy**다. docker-manager에 HAProxy config가 없고
  (`*haproxy*` 파일 0건, `timeout tunnel` 언급 0건), n150에서도 haproxy는 inactive이며
  `/etc/haproxy/`가 없다. 즉 tasks가 전제한 "docker-manager 공개 base config"는 존재하지 않고,
  설정 적용과 proxy metric 확인 모두 **라우터 접근**이 필요해 에이전트가 수행할 수 없다.
  사용자 지시로 보류한다 — 운영자가 라우터에 `timeout tunnel`을 적용한 뒤 quiet 2주기 실증으로
  #819를 닫는다.

### T-VN-H30 — 주소 검증 관측 durable화·회복 실적재 검증 (H28 후속, 부분완료)

- [x] T-VN-H30A — **검증 finding을 `ops.data_integrity_violations`에 durable 기록**

  migration `0067_integrity_dedupe_key` + `0068_integrity_last_seen`,
  `sync_integrity_findings()`와 `record_address_validation_findings()`로 구현한다.
  PR #888 사후 감사에서 확인된 결함까지 현재 Lane B PR에서 보강했다.

  - `jsonb ||`는 shallow merge라 재실행 시 `EXCLUDED`의 null이 1회차 증거를 덮어썼다
    (durable ledger 안에서 증거 소실). `jsonb_strip_nulls`로 차단.
  - key는 `source_record_key`나 원천 id 문자열을 직접 싣지 않는다.
    provider/dataset/`source_entity_type`/`source_entity_id`/violation code 전체의
    `av2_<sha256>`(68 bytes)로 고정해 payload 변경·entity type 재사용·B-tree 행 크기 한계를
    함께 차단한다.
  - `ops.data_integrity_violations`에 statement 트리거가 있어(실측) finding당 INSERT가
    `ops_live` revision 단일 행에 배타 락을 잡고 트랜잭션 끝까지 유지했다 — admin 쓰기 차단·
    동시 run 직렬화·데드락. `dedupe_key` 정렬 후 `unnest` 단일 statement로 접어
    트리거 1회·잠금 순서 1개로 고정한다.
  - recurrence는 최초 `detected_at`을 보존하고 별도 `last_seen_at`을 갱신한다.
    `/admin/issues` cursor도 최신 관측 시각을 쓴다. FK target은 최신 recurrence로 갱신하고,
    Feature 삭제는 `ON DELETE SET NULL`이라 ledger 행을 지우지 않는다.
  - client 결과는 `observed/unique/upserted`를 구분해 내부 중복을 미기록으로 오산하지 않는다.
    DB 기록 실패는 typed error이며 strict 경로는 validation `Failure` 전에 fail-closed한다.

  > **자동 close는 없다** — 배치마다 sweep하면 같은 run의 다른 batch finding을 닫고,
  > 부분 unique index 밖으로 밀린 행이 다음 run에 다시 생성되며, 빈 bundle sentinel이 큐를
  > 전부 닫는다. `T-VN-H32`에서 run marker 기반으로 별도 설계한다.

- [ ] T-VN-H30B — **회복을 같은 격리 snapshot의 실제 적재·인증 API로 재검증**

  종전 실증은 bundles 1,477와 `source_records` 2000→2458(+458), 2회차 insert 0만 남겼다.
  acceptance가 요구한 같은 snapshot의 `feature.features` before/after를 보고하지 않았고,
  `/admin/issues`도 코드 경로만 확인했을 뿐 인증된 실호출을 하지 않았다.

  재검증 acceptance:
  - 같은 격리 snapshot identity와 migration head를 기록한다.
  - 적재 직전/직후 `feature.features`의 동일 scope 수와 복구된 feature id 집합을 기록한다.
  - 같은 run의 finding `observed/unique/upserted`, linked/unlinked 수를 함께 기록한다.
  - 인증된 `GET /v1/admin/issues?issue_type=…` 실호출로 최신 `last_seen_at`·최신 FK target을
    확인한다.

- [ ] T-VN-H30C — **타 provider `AdminEvidence` 무장 (미완 — 재작업 필요)**

  MOIS만 무장했으나 **탐지 증가는 0건**이다. MOIS는 payload에 `legal_dong_code`가 있으면
  역지오코딩을 아예 호출하지 않으므로 `obs_code`와 `claim_code`가 **상호배타**이고
  `grade == "dual"`이 구조적으로 불가능하다 — staleness 축이 영원히 발화하지 않는다.
  `unarmed`→`claim_only` 재라벨 이상의 값이 없다.

  > **정정** — 직전 판에 "나머지 provider는 payload 법정동코드가 없어 무장 대상이 아니다"라고
  > 적었으나 **거짓**이다. 적대 리뷰가 반증했다:
  > `providers/krforest.py:182` `ForestSpatialItem.region_code`(원천
  > `python-krforest-api` `_REGION_CODE_KEYS`에 `법정동코드`/`EMD_CD` 포함, 역지오코딩도 함),
  > `python-visitkorea-api` `models.py:90` `l_dong_regn_cd`/`l_dong_signgu_cd`.
  > 두 provider가 실제로 `dual`을 낼 수 있는 후보다.

  재작업 시: krforest·visitkorea를 조사해 무장하고, MOIS는 reverse를 강제하지 않는 한
  staleness 대조가 불가능함을 설계 문서(`docs/architecture/address-geocoding.md`,
  `dto/admin_evidence.py`)에 고정한다. provider 고유 코드(VisitKorea `areaCode` 등)는 넣지 않는다.

### T-VN-H32 — 주소 검증 finding 자동 close (H30A 후속)

H30A가 durable ledger를 붙였으나 **자동 close는 일부러 넣지 않았다**. 1차 설계의 sweep
("이번 run이 보고하지 않는 finding을 닫는다")을 적대 리뷰가 실측으로 기각했다.

- `_load()`는 provider에 따라 **배치마다** 호출된다(MOIS는 1000건 단위 ~977회). 배치 단위
  sweep은 "이 배치에 없는 것"을 닫아, 한 run이 자기 finding 대부분을 스스로 resolved 처리한다.
- sweep이 행을 부분 unique index 밖으로 밀어내 다음 run이 **새 행**을 만든다 — 막으려던
  단조 증가를 재생산한다(3개 논리 finding → 2 run 후 6행, 실측).
- `bundles=[]`인 `_load()`는 OpiNet 일일 스킵·MOIS 무레코드 fallback의 **제어 흐름
  sentinel**이라, 빈 finding 집합이 큐 전체를 닫는다.

- [ ] T-VN-H32 — **run marker 기반 close**

  적재 run id/시각을 finding payload에 남기고 "그 run보다 오래된 것"만 닫는다. 배치 경계와
  무관해지고 `live_keys` 배열(MOIS면 ~977k 원소)도 사라진다. 함께 확인할 것:
  기계가 닫은 행의 `payload.resolution` 스탬프, `acknowledged` 불가침, provider 경계,
  그리고 resolved 행의 보존 기간(현재 retention 정책이 없다).

### T-VN-H25 — 공식 curation 미연결 membership 해소

> **전제 정정 (2026-07-29, T-VN-H25A)** — 기존 전제 *"공식 CSV의 고유 `feature_id` 158개 중
> 54개가 `feature.features`에 존재하지 않았다"*는 **재현되지 않는다**. prod에서 158/158이
> 존재하고 전부 curation 링크 가능한 상태이며 `created_at`이 2026-06-29~07-03로 측정 시점보다
> 앞선다. `ops.feature_merge_history`는 0행이고 미연결 261건 중 `source_record_key` 보유가
> 0건이라, `ON DELETE SET NULL` cascade로 링크가 지워진 흔적도 없다.
> **stale reference 해소는 대상이 없다.** 실제 문제는 처음부터 연결된 적 없는 membership이다.
> 근거: [`reports/curation-unlinked-reference-evidence-2026-07-29.md`](reports/curation-unlinked-reference-evidence-2026-07-29.md).

H24가 stable component 기반 미연결 membership으로 무손실 보존하므로 데이터 손실 위험은 없다.
증거 생성과 mutation을 분리한다.

- [x] T-VN-H25A — **미연결 membership evidence manifest** (전제 정정 포함)

  prod 단일 snapshot에서 존재 여부·lifecycle/merge·공식 collection 범위 정합을 대조했다.
  주요 산출: 전제 반증(§1·§2), CSV 217/269 vs DB 225/261로 **같은 모집단이며 DB가 8건 앞섬**(§3),
  미연결의 지배 원인은 수목원이 아니라 **등대 103건**(105 중 2건만 링크, §4).
  자체 matcher는 결함이 확인돼 후보 등급 산출에는 쓰지 않는다 — CSV `metadata_json`의
  `feature_match_confidence`(review 183 / unmatched 86)가 기준선이다(§5·§6).

  **미충족 AC — 산출물을 바꿔 닫았음을 명시한다.** 전제가 반증된 이상 원래 형태의 후보
  manifest는 의미가 줄었고, 실행 가능한 잔여 작업은 아래 H25B로 이관했다. `[x]`는 "AC 전부
  충족"이 아니라 "전제 반증·재측정으로 종결"의 뜻이다.

  | AC 항목 | 상태 | 이관 |
  | --- | --- | --- |
  | lifecycle/merge history 대조 | 충족 | — |
  | 동일 DB snapshot | 충족 (prod 단일) | — |
  | 좌표 근접만으로 자동 승인 안 함 | 충족 | — |
  | CSV/DB target 미변경 | 충족 | — |
  | provider provenance 대조 | 부분 — `source_record_key` 유무(0건)만 확인, `provider_sync.source_entities` 미조인 | H25B ② |
  | 이름 대조 | 부분 — matcher 결함(괄호·`&` 복합명·포함 방향·`status='active'` 한정) 확인 후 등급 산출에서 배제 | H25B ② |
  | 주소 대조 | **미충족** — `address_hint`가 486행 전부 비어 축이 없음. `region`(118/269 보유)은 미반영 | H25B ② |
  | candidate·confidence·근거 manifest 산출 | **미충족** — JSON 미커밋, 리포트 표로 대체 | H25B ② |

- [~] T-VN-H25B — **CSV 역반영 5건 + 매칭 재실행** (미충족 AC는 아래 표)

  H25A 재정의 결과 실행 가능한 작업은 둘이다.
  1. **CSV 역반영 8건** — DB에서는 링크됐으나 CSV `feature_id`가 비어 있는 항목(H25A §3).
     현재 어느 문서에도 기록돼 있지 않은 확정 대상이다.
  2. **매칭 재실행 + H25A 미충족 AC 인수** — CSV `metadata_json.feature_match_confidence`
     (review 183 / unmatched 86)를 기준선으로 삼고, 괄호·`&` 복합명·포함 방향·`status` 범위
     결함을 고친 matcher로 대조해 **차이를 설명**한다. 자체 수치를 기준선으로 삼지 않는다.
     함께 인수하는 H25A 미충족 항목: **주소 축**(`address_hint`가 비어 있으므로
     `metadata_json.region` 118건 + `features.sigungu_code`를 쓴다), **provider provenance**
     (`curation_items.source_record_key` → `provider_sync.source_records`/`source_entities` 조인;
     CSV의 `provider`/`dataset_key`/`source_item_key`는 269행 전부 채워져 있다),
     그리고 **candidate·confidence·근거 manifest를 JSON으로 커밋**한다.

  좌표 근접만으로 자동 승인하지 않는다. 불확실한 component는 미연결 상태와 근거를 유지한다.
  5개 CSV의 linked/unresolved 수치, preview/commit, REST/UI를 같은 실데이터 snapshot에서 검증한다.

  **결과** ([리포트](reports/curation-link-backfill-2026-07-29.md),
  manifest `reports/h25b-match-manifest.json`):
  - **8건 중 5건만 반영.** 3건은 오링크였다 — 청남대(DB 전남 영암 vs 정지오코딩 충북 청주),
    남이섬 ×2(DB 서울 중구 사무소 vs 강원 춘천). H25A가 "확정 대상"이라 한 것은 **DB에
    링크가 있다는 사실을 승인 근거로 삼은 오류**였다. CSV linked 217→222 / unresolved 269→264.
  - matcher 결함 4종 수정 후 **후보 없음 191 → 1**. H25A의 "191건 실제 부재 = provider 적재
    범위 문제"는 **matcher 산물**이었다.
  - 다만 개선은 착시다 — 늘어난 후보 대부분이 무의미한 부분일치이고, 등대 103건 중 **89건**의
    최상위 후보가 상호가 `등대`인 가게였다(1건은 후보조차 없다). `T-VN-H31` 전제는 유효.
  - 최종 등급 **high 2 / review 13 / low 248 / none 1**. `high`에도 오탐이 있었고
    (`대관령` → 고개가 아닌 동명 업소) → **자동 승인 대상 0건**. 264건은 사람 검토 대상.
  - `high`는 적대 리뷰에서 6→7→**2**로 세 번 바뀌었다. 세 번 다 원인이 데이터가 아니라
    **matcher 자신의 결함**이었다 — 시도 약칭 비교, soft-delete 후보 혼입, 그리고
    `ORDER BY length(name)`(양방향 substring이라 2글자 feature가 top이 됨). 세 번째는
    내가 두 번째를 고치며 **새로 넣은** 결함이다. 264행 중 **208행(79%)이 후보 cap 포화**라
    그 행들은 이름 유일성 자체를 판정할 수 없다.
  - **manifest sha256을 손으로 유지하던 구조를 없앴다.** README를 고치고 sha256을 안 고쳐
    `test_curation_resource_manifest_and_csv_contract`가 깨졌다(n150 게이트가 잡음).
    이제 `scripts/h25b_apply_verified_links.py`가 `manifest.json`의 sha256/rows를 실물에서
    다시 계산한다 — 커밋된 CSV·manifest 전부 그 스크립트 하나의 산출물이다.
  **미충족 AC 원장** — `[x]`는 "AC 전부 충족"이 아니라 "역반영·매칭 재실행으로 종결"이다.

  | AC 항목 | 상태 | 이관 |
  | --- | --- | --- |
  | CSV 역반영 | 충족 (8→5, 3건은 오링크) | — |
  | 기준선 대조 + 차이 설명 | 충족 — 교차표를 manifest `summary.baseline_vs_matcher`에 기록 | — |
  | 주소 축 | **부분** — `region`(115/264)만 사용. `sigungu_code`는 시도코드 비교에만 쓰고 시군구 단위 대조는 미구현 | H25B-후속 |
  | provider provenance 조인 | **미충족** — `source_record_key`가 미연결 261건에서 전부 NULL이라 조인 대상이 없다. CSV의 `provider`/`dataset_key`는 entry에 싣기만 하고 판정에 쓰지 않았다 | H25B-후속 |
  | candidate·근거 manifest 커밋 | 충족 — 스크립트 실제 산출물, `candidates_total`로 잘린 수 공개 | — |
  | linked/unresolved 수치 검증 | 충족 (222/264, manifest sha256 일치) | — |
  | **preview/commit·REST/UI 실데이터 검증** | **미충족** — 읽기 전용 범위를 유지했다 | H25B-후속 |
  | 동일 snapshot 고정 | **부분** — DB는 `current_database()`로 기록했으나 정지오코딩 세션은 미기록 | H25B-후속 |

  위 4개 미충족·부분 항목은 **`T-VN-H34`**로 이관한다(아래).

- [ ] T-VN-H34 — **H25A/H25B 미충족 AC 마무리**

  H25A가 H25B로, H25B가 다시 여기로 넘긴 항목들이다. **어느 열린 task도 소유하지 않는 상태를
  만들지 않기 위해** 명시적으로 모은다.
  - **주소 축 시군구 단위 대조** — 현재는 시도코드까지만 본다.
    > **문구 정정(2026-07-29)** — 이 항목을 "`metadata.region`을 시군구까지 본다"로 읽으면
    > **실행 불가**다. `region`은 `강원`·`충북` 같은 **시도 약칭뿐**이라 시군구를 담을 수 없다.
    > 실제로 가능한 축은 **정지오코딩 결과의 시군구코드 ↔ feature `sigungu_code` 대조**이며,
    > 청풍호에서 손으로 한 것이 바로 그것이다(제천 `43150` 일치). 따라서 이 항목은 아래
    > "정지오코딩 세션 고정"과 **같은 도구로 함께** 해결된다 — 별개 축이 아니다.
    >
    > **천장도 같이 기록한다**: 시군구까지 내려가도 같은 시군구 안의 다른 대상은 구분되지
    > 않는다(청풍호 vs 청풍호반케이블카). 시군구 축은 *기각*에는 쓸 수 있어도 *확정*의
    > 충분조건이 아니다.
  - **provider provenance** — `curation_items.source_record_key`가 미연결 행에서 전부 NULL이라
    현 스키마로는 조인 불가. CSV의 `provider`/`dataset_key`/`source_item_key`를 판정에 쓰는
    설계를 하거나, 불가하다는 결론을 근거와 함께 확정한다.
  - **preview/commit·REST/UI 실데이터 검증** — 역반영 5건이 실제 화면·API에 반영되는지.
  - **정지오코딩 세션 고정** — 승인/기각 근거를 재현 가능하게 남긴다
    (`scripts/h25b_verify_links.py` 신설; 현재는 손으로 친 상수표뿐이다).

- [~] T-VN-H33 — **curation_items 오링크 3건 정리 (H25B 파생)**

  **증상은 제거했으나 durable하지 않다.** `[x]`로 닫았다가 적대 리뷰 실측으로 되돌렸다 —
  아래 "철회" 참조. 근본 수정은 `T-VN-H36`.

  `scripts/h33_unlink_mislinks.py` (dry-run 기본, `--apply`로 쓰기).
  - **노출 실증** — 해제 전 남이섬 feature(서울 중구 사무소)에 한국관광100선 **2건**,
    청남대 feature(전남 영암)에 **1건**이 붙어 응답에 나왔다.
    표면은 `/v1/curations/*`이며 **익명 공개가 아니라 `RoutePolicy.PUBLIC_KEYED`** —
    public API key 보유자에게 열린 표면이라는 한정 아래 읽어야 한다.

    > **🔴 철회 — "해제 후 0건"의 근거가 반증 불가능했다.**
    > 초안 확인 스크립트는 `/v1/curations/features/{feature_id}`만 호출했는데, 이 엔드포인트는
    > curation이 없으면 200+빈 배열이 아니라 **404**를 낸다. 스크립트가 `curl -s`로 status를
    > 버리고 에러 본문을 파싱해 "0건"을 출력했으므로, **존재하지 않는 feature_id를 넣어도
    > 같은 출력이 나온다**(리뷰 실측). 오타·삭제·401이 전부 "해소됨"으로 읽혔다.
    > 이 세션에서 반복된 "측정 도구의 산물을 데이터의 성질로 읽기"와 같은 형태다.
    >
    > 대체 증거는 `scripts/h33_verify_public_exposure.py`다 — negative control(없는 id)과
    > 구별되지 않으면 **스스로 경고**하고, 반증 가능한 표면을 근거로 쓴다:
    > 컬렉션 상세가 200으로 item 110·114건을 돌려주고 그 안의 대상 3건이 `feature_id=null`,
    > `q=남이섬` 검색은 5 group을 내놓는 **양성 대조**를 가지며 그 안에 오링크 feature가 없다.
    > 즉 **item은 공개 응답에 그대로 있고 feature 링크만 끊겼다** — 해제이지 삭제가 아니다.
    > 부수로 e2e 기대값도 확인된다: 공식 19개 컬렉션 public membership 합계 **486 유지**
    > (`item_count`가 미연결 item도 세므로 unlink가 기대값을 깨지 않는다).
  - **탐지기 재실행** ([after 산출물](reports/h33-mislink-after-2026-07-29.json)) —
    `db_linked_rows` **3269→3266**, `db_region_codeable` **112→109**, `db_sido_mismatch` 3→0.

    > **"3→0"만 인용하면 안 된다.** 탐지기 모집단은 `ci.feature_id is not null` inner join이라
    > **링크를 끊으면 그 행이 모집단에서 빠진다** — 0은 관측이 아니라 정의다(리뷰 지적).
    > 엉뚱한 행을 끊었어도, item을 지웠어도 0이 나온다. 정보를 가진 숫자는 오히려
    > `3269→3266`·`112→109`, 즉 **정확히 대상 3행만 빠졌다**는 사실이다.
  - **ledger 방출** — `ops.data_integrity_violations`에 `curation_feature_region_mismatch`
    3건. **`open`이다**(초안은 `resolved`였으나 철회 — 아래). `feature_id` 컬럼은 비우고
    payload에만 남긴다: 이 FK가 `ON DELETE CASCADE`라 문제의 feature를 지우면 "잘못
    링크돼 있었다"는 기록까지 같이 사라진다.
  - **재실행 안전** — `--apply` 재실행은 "이미 해제" 3건으로 끝나고 finding만 갱신한다.
    지목한 오링크 `feature_id`를 가진 행만 대상으로 하며, 형제 행(같은 item의 다른
    component)은 정상으로 보고 경보를 울리지 않는다.

  > **🔴 철회 — "재링크되지 않는다"는 틀렸다.**
  > 초안은 *"공식 CSV import가 `feature_id = EXCLUDED.feature_id`로 덮어쓰는데 이 3행은
  > CSV가 비어 있으니 다시 링크되지 않는다"*고 적고 그 근거로 task를 닫았다.
  > **적대 리뷰가 prod에서 실측으로 반증했다.** `EXCLUDED.feature_id`까지만 읽고 거기
  > 무엇이 들어오는지 보지 않은 것이다 — 빈 `feature_id`는 링크를 막는 게 아니라
  > `curation_repo._RESOLVE_FEATURES_BATCH_SQL`의 **이름 자동매칭을 켠다**
  > (`WHERE requested.feature_id IS NULL AND lower(f.name) = lower(requested.place_name)`,
  > `address_hint`도 비어 있어 주소 필터는 건너뛴다). 단일 매칭이면 그 id가 그대로
  > `EXCLUDED.feature_id`가 된다.
  > **커밋된 CSV의 빈 264행 중 단일 매칭으로 해석되는 건 정확히 이 3행뿐이고, 전부 방금
  > 끊은 그 feature로 되돌아간다** — prod에 `남이섬`·`청남대`라는 이름의 live feature가
  > 각각 하나뿐이고 그게 바로 틀린 그 feature이기 때문이다.
  > 게다가 import는 `metadata = EXCLUDED.metadata`로 무조건 덮으므로 위에서 남긴 사유도
  > 지워진다. 그래서 finding을 `resolved`가 아니라 `open`으로 되돌렸다.
  > 지금 당장 되살아나지는 않는다 — prod가 `0063`이라 HEAD의 import SQL이 참조하는 컬럼이
  > 없어 import 자체가 실패한다. **`T-VN-H35`가 마이그레이션을 적용하는 순간 되살아나므로
  > H36이 H35보다 먼저여야 한다.**
  >
  > **덧붙인 정정 — 나는 배포되지 않은 코드로 prod 동작을 주장했다.** 위 인용
  > (`feature_id = EXCLUDED.feature_id`)은 **브랜치 코드**다. 배포 중인 이미지
  > (`kor-travel-map-api-latest`, revision `c8ed6164`, 2026-07-27)의 `_UPSERT_ITEM_SQL`은
  > `ON CONFLICT (collection_id, external_item_id, feature_id) WHERE archived_at IS NULL`이고
  > **SET 절에 `feature_id`가 아예 없다** — 그 코드에서는 재링크가 안 일어난다.
  > 즉 "지금 prod는 안전하다"는 맞지만 **내가 댄 이유는 prod에 존재하지 않는 코드였다.**
  > 같은 커밋에서 "머지 ≠ 배포"를 교훈으로 적어 놓고 마이그레이션에만 적용하고
  > **코드 주장에는 적용하지 않았다**(리뷰 지적).

  > **부수 발견 — prod가 마이그레이션 4개 뒤처져 있다.** ledger 방출을 붙이다가
  > `ON CONFLICT`가 두 번 실패했다. 원인은 코드가 아니라 **prod alembic head가
  > `0063_pipeline_root_id`**라는 것이었다 — H30A가 만든 dedupe 부분 유니크 인덱스(`0067`)가
  > **prod에 존재하지 않는다**. H30A의 dedupe 효과는 현재 prod에서 작동하지 않는다.
  > → `T-VN-H35`로 분리한다. 또 `source_record_key`에는 `provider_sync.source_records`
  > FK가 걸려 있어 curation 키를 넣을 수 없다(ledger가 provider 적재 전제로 설계됨).

- [ ] T-VN-H36 — **curation import가 이름만으로 자동 링크한다 (H33 파생, H35보다 선행)**

  `curation_repo._RESOLVE_FEATURES_BATCH_SQL`은 CSV `feature_id`가 비면
  `lower(f.name) = lower(place_name)` 단독으로 후보를 찾고, 단일 매칭이면 그대로 링크한다.
  `address_hint`가 비면 주소 필터도 걸리지 않는다. **지역 교차검증이 없다.**
  H33이 끊은 3건이 정확히 이 경로로 되살아난다(prod 실측: 빈 264행 중 단일 매칭 3행 =
  H33 대상 3건, 전부 틀린 feature로 복귀).
  또 `metadata = EXCLUDED.metadata`가 무조건 덮어써서 "링크 금지" 사유를 남길 자리도 없다.

  선택지: (a) 리졸버에 시도/시군구 교차검증 추가, (b) import가 존중하는 명시적 "링크 금지"
  표식, (c) 이름 단독 매칭 시 자동 링크 대신 `review`로 떨어뜨리기.
  **H35(마이그레이션 적용)보다 먼저 해야 한다** — 지금은 prod가 `0063`이라 import 자체가
  실패해 우연히 막혀 있을 뿐이다.

- [ ] T-VN-H35 — **prod 마이그레이션 지연 해소 (0064~0067)**

  prod alembic head `0063_pipeline_root_id` vs 저장소 head `0067_integrity_dedupe_key`
  (0063→0064→0065→0066→0067 단일 체인, 분기 없음). H30A(`0067` dedupe 부분 유니크 인덱스)를
  포함해 **머지된 마이그레이션이 prod에 반영되지 않았다**. H30A가 주장한
  dedupe·`/admin/issues` 접기는 현재 prod에서 성립하지 않는다.

  > **⚠ 마이그레이션만 올리면 안 된다 — 이미지도 함께 올려야 한다.**
  > prod는 "DB만 뒤처진 불일치"가 아니라 **코드·스키마가 일관되게 0063에 고정된 상태**다
  > (배포 이미지 revision `c8ed6164`). 벌어진 간극은 DB↔코드가 아니라 **저장소↔배포**다.
  > 특히 `0065`는 `uq_curation_items_active_identity`(partial, `WHERE archived_at IS NULL`)를
  > drop하고 partial이 아닌 `uq_curation_items_identity`를 만드는데, **지금 도는 이미지의
  > upsert는 `ON CONFLICT (…) WHERE archived_at IS NULL`을 명시**하므로 이미지를 둔 채
  > 마이그레이션만 적용하면 arbiter 추론이 실패해 curation import·admin item 쓰기가 깨진다.
  > `0065`에는 중복 정리용 `DELETE FROM feature.curation_items`도 들어 있다.

  할 일: 0064~0067 각각의 내용·위험 평가 → **마이그레이션과 이미지 배포의 순서·원자성 확정**
  → 적용 → dedupe 인덱스 실측 확인.
  **머지 = 배포가 아니라는 점을 문서에도 반영한다** — H30A 완료 기록이 prod 상태를
  주장하는 것으로 읽히지 않게. (H36이 이 task보다 **먼저**다.)

  <details><summary>원래 정의 (완료 전)</summary>

  H25B가 정지오코딩으로 확인한 오링크가 **DB에는 그대로 남아 있다**(`status=included`,
  archived 아님). `/admin/curations` 계열 화면과 공개 projection이 남이섬 자리에 서울 중구
  사무소를, 청남대 자리에 전남 영암 시설을 노출하고 있을 수 있다.
  대상: `kt100-2023-2024-025`, `kt100-2025-2026-024`(남이섬), `kt100-2025-2026-036`(청남대).

  **전수 확인 결과 이 축으로 잡히는 오링크는 3건이다** (`scripts/h33_mislink_detect.py`, 재현 가능).
  CSV 링크 222행 시도 불일치 **0건**, DB `curation_items` 링크 전수 **3건**(남이섬 ×2, 청남대).
  근거 산출물: [`reports/h33-mislink-2026-07-29.json`](reports/h33-mislink-2026-07-29.json)
  (`db_linked_rows` 3269 / `db_region_codeable` 112 / `db_sido_mismatch` 3).
  CSV 쪽이 0건인 것은 **그 3건을 역반영에서 뺐기 때문**이지, 축이 안 도는 게 아니다.

  > **정정** — H25B 리포트 초안은 호미곶·오륙도를 들어 "오탐이 계통적이니 유형 전수를
  > 대상으로 하라"고 적었으나 **철회했다**. 그 이름의 서울 소재 feature가 *존재할 뿐*
  > curation에 링크돼 있지 않다. *실제 오링크*(고칠 데이터, 3건)와 *매칭 함정*(방어할 대상,
  > 다수)을 뭉갠 것이다.

  **스키마 변경은 권고하지 않는다** — 탐지 축인 `metadata.region`이 DB 링크 3,269건 중
  **112건(3%)**에만 있어, 그걸로 만든 제약·뷰는 97%를 검사하지 못하면서 검사한 것처럼 보인다.
  CHECK는 교차 테이블이라 애초에 불가하고, 실제 결함도 3건이다. 대신 H30A의
  `ops.data_integrity_violations` ledger에 finding으로 방출하면 migration 없이 dedupe와
  `/admin/issues` 노출을 얻는다.

  할 일: 3건 unlink + 공개 projection 노출 여부 실증 + ledger 방출.
  **커버리지 한계를 함께 기록한다** — region 없는 링크는 이 축으로 판정되지 않는다.

  </details>

  **남는 커버리지 한계**(고친 3건이 전부라는 뜻이 아니다): `region`이 있는 링크만 본다 —
  해제 후 기준 **3,266건 중 109건(3.3%)**. 즉 **96.7%인 3,157행은 이 축으로 아예 검사되지
  않는다.** 시도는 맞고 시군구만 다른 오링크도 안 잡히고, `sido_code`가 NULL인 2건은
  건너뛴다. "0건"은 부재의 증명이 아니다.

  > 초안은 여기에 "존재하지 않는 feature를 가리키는 링크는 세지 않는다"도 한계로 적었으나
  > **뺐다** — `curation_items_feature_id_fkey`가 `ON DELETE SET NULL`이라 그런 행은 애초에
  > 생길 수 없고 prod 실측도 0건이다(리뷰 지적). 존재할 수 없는 위험을 한계 목록에 얹으면
  > 불확실성의 모양이 실제와 달라진다.

- [ ] T-VN-H31 — **등대 공급원 부재 해소 (H25A 파생, 전제 재확인됨)**

  공식 curation 미연결 261건 중 **103건이 등대**이며 105개 중 2개만 링크됐다. ADR-034 9단계
  provider 순서에 등대를 공급하는 provider가 없다 — curation 매칭으로는 해소되지 않는다.
  공급원(해양수산부/KHOA 계열 등)을 조사해 적재 경로를 만들거나, 불가능하면 미연결 유지 근거를
  문서로 확정한다.

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

- **task로 승격**: map #673=`T-VN-H28A/B`, map #819=`T-VN-H27`(보류).
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
