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

- **문서 정합성 후속(독립 docs PR)**
  - [ ] `T-VN-DOC-732` — PR #732의 인증·canonical ops·C6c/C7 설계 결정을 현재
    OpenAPI와 완료된 production cutover 기준으로 ADR·REST·cross-repo 정본에 반영
- **Lane A — cross-repo 계약·운영·데이터 품질**
  - a0: [x] `T-VN-H07B`(PinVi #403 재감사·landing) →
    [x] `T-VN-H07D`(#815 admin snapshot/freshness) →
    [x] `T-VN-H07C`(#812 — v5 승격 기각, ADR-079)
  - a1: [x] `T-VN-H29`(PinVi 검색 좌표 null 복구 — H07D 파생) →
    [x] `T-VN-H21`(geo live 인증 결선 검증·5건 재실증) →
    [x] `T-VN-H28A/B`(#673 실데이터 오탐 분류 + 검증 규칙·회복 — 한 PR) →
    [x] `T-VN-H25A`(미연결 membership 증거·전제 정정) →
    [x] `T-VN-H30A`(관측 durable화) →
    [~] `T-VN-H25B`(CSV 역반영 5건·매칭 재실행 — 3건 오링크 배제, 미충족 AC는 H34) →
    [x] `T-VN-H33`(오링크 3건 해제 — 공개 오노출 해소, H36으로 durable) →
    [x] `T-VN-H36`(import 이름 단독 자동링크 금지 — H35 이미지에 포함 필수) →
    [ ] `T-VN-H35`(prod 마이그레이션 지연 0064~0068 + 이미지 동시 배포 — #673 blocker) →
    [ ] `T-VN-H30B`(같은 snapshot 실적재·인증 API 재검증) →
    [ ] `T-VN-H30C`(타 provider evidence 재작업) →
    [ ] `T-VN-H34`(H25A/H25B 미충족 AC 마무리) →
    [ ] `T-VN-H31`(등대 공급원 부재 — H25A 파생) →
    [ ] `T-VN-H32`(주소 검증 finding 자동 close — H30A 후속) →
    [ ] `T-VN-H22A`(quarantine read/preview) →
    [ ] `T-VN-H22B`(원자적 재분류 command) →
    [ ] `T-VN-H22C`(Admin UI·파괴적 live)
- **Lane B — frontend hardening·PinVi 소비 API**
  - b0: [x] `T-VN-48D`(final exact Mocked/Live) →
    [x] `T-VN-49A/B/C/D`(React 구조 debt, 단일 PR)
  - b1: [x] `T-VN-11A/B`(service batch, 저장소별 호환 PR 쌍) →
    [x] `T-VN-H37`(Mocked checkpoint 종료 판정·고병렬 flaky 진단) →
    [x] `T-VN-H38`(failure manifest retry/error fingerprint 완전성) →
    [x] `T-VN-H39`(schedule command pending barrier) →
    [x] `T-VN-16B`(weather batch 소비) →
    [ ] `T-VN-16C`(sparse 다중 날짜 weather batch) →
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

> T-VN-49의 `[x]` 이관은 H49 코드와 같은 merge commit으로만 `main`에 들어간다. 따라서
> `main`에서 구현보다 완료 표시가 먼저 보이거나 H22C barrier만 먼저 풀리는 구간은 없다.

## 공통 규율 (2026-07-28 개정)

- base는 **main**(`integration/t-vn`은 PR #790 합류로 폐지). 시작·PR 직전·머지 직후
  `origin/main` rebase. PR 하나는 task 하나만 소유.
- **Claude Code PR 감사 순서(사용자 지시 2026-07-29)**: 개별 T-VN task는 자기 구현·적대
  리뷰·Live·CI를 먼저 끝내 PR을 머지한다. Claude Code PR 사후 감사는 task PR 머지 뒤
  별도 후속 단계에서 issue를 만들고 진행하며, 진행 중 task의 PR 생성·머지를 지연시키거나
  그 PR에 새 감사를 합치지 않는다. T-VN-48에는 규칙 변경 전에 완료한 issue #881과 PR #888
  감사 수정만 유지한다. **Lane A a1 task PR 사후 감사는 독립 적대 리뷰어 2명**을 쓰고,
  docs-only PR은 작은 delta 규칙에 따라 1명으로 한다(사용자 지시 2026-07-30, issue #893부터).
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
  H22C의 curation frontend 선행 작업 T-VN-48B·T-VN-49B는 모두 완료됐다. H22A/B가
  끝나면 최신 구조에서 H22C를 시작한다. T-VN-49B 코드와 이 barrier 해제는 같은 merge
  commit으로 landing한다. T-VN-12A의 command
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

- [x] T-VN-H30A — 검증 finding을 `ops.data_integrity_violations`에 durable 기록 (#888, dedupe 부분 유니크 인덱스 0067 — **prod 미적용, H35 참조**) → [`tasks-done.md`](tasks-done.md)

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
  - H35가 서명한 post-migration app·Dagster DB bundle을 격리 scratch DB pair에 복원해
    검증한다. H35 daemon preflight 뒤에도 두 DB의 서명 identity가 그대로면 같은 scratch
    pair를 재사용하고, 다르면 새 clone을 만들지 말고 그 pair를 같은 bundle로 reset한다.
    prod DB·schedule/sensor·ingress는 이 task에서 변경하지 않는다.
  - 같은 bundle의 concierge `changes` export artifact를 SHA-256·page/cursor chain·행 수까지
    검증하고, live endpoint credential/network 없이 resource override로 ordered item을
    재생한다. 이 artifact 외 입력을 섞거나 H30B 시점의 live export를 다시 조회하지 않는다.

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

- [x] T-VN-H33 — curation_items 오링크 3건 해제 + 공개 오노출 실증 + ledger 방출 (#890, H36으로 durable해짐) → [`tasks-done.md`](tasks-done.md)

- [x] T-VN-H36 — curation import의 이름 단독 자동링크 금지 (#890, 막힌 자동링크 3건 전부 오링크 / 정당한 손실 0건) → [`tasks-done.md`](tasks-done.md)

> **issue #673 판정(2026-07-30) — 아직 닫을 수 없다.** 서브에이전트 조사로 이슈 본문·코멘트를
> 요구사항으로 분해해 대조했다. 3항목 중 둘(오탐 분포 규명 / 규칙 교체)은 충족이고,
> 셋째("다음 materialize에서 자동 회복되는가")는 **코드 논증만 있고 실증이 없다**.
> 결정적 blocker는 **prod 미배포**이며 이슈가 신고한 손실(현재 457건)이 실재한다 → `T-VN-H35`.
> 남은 실증은 `T-VN-H30B`. **`T-VN-H30C`·`T-VN-H32`는 #673 범위 밖**이다 —
> 이슈는 "concierge provider에 한해" 완화를 요구했고 두 task는 그 파생 개선이다.
> 저장소 열린 이슈는 #673·#819 두 건뿐이고 #673은 epic이 아니다.

- [ ] T-VN-H35 — **prod 마이그레이션 지연 해소 (0064~0068)**

  prod alembic head `0063_pipeline_root_id` vs 저장소 head **`0068_integrity_last_seen`**
  (0063→0064→0065→0066→0067→0068 단일 체인, 분기 없음). 즉 간극은 **5개**다.
  H30A(`0067` dedupe 부분 유니크 인덱스)를 포함해 **머지된 마이그레이션이 prod에 반영되지
  않았다**. H30A가 주장한 dedupe·`/admin/issues` 접기는 현재 prod에서 성립하지 않는다.

  > **정정(2026-07-30)** — 이 항목은 처음에 `0064~0067`(4개)로 적혀 있었다. 실제 head는
  > `0068_integrity_last_seen`(`down_revision=0067`)이라 **0064~0068 5개**다.
  > `ops.data_integrity_violations.last_seen_at` 컬럼이 prod에 없는 것도 그래서다.

  **이 task는 issue #673의 유일한 결정적 blocker다.** #673("concierge 후보 410건 영구
  미적재")의 규칙 교체는 `T-VN-H28A/B`로 머지됐지만 **prod에 배포되지 않았다** —
  실측으로 prod dagster 컨테이너는 아직 옛 규칙(`provider_address_mismatch`)을 담고 있고,
  live export **1,477**건 대비 prod 적재는 **1,020**건(**457건 미적재**)이다.
  `max(last_seen_at)`이 2026-07-14(이슈 제기일)로 그 뒤 materialize가 돈 적이 없다.
  배포해도 회복은 즉시가 아니다 — 스케줄이 월 1회(`40 3 3 * *`)라 **2026-08-03** 또는
  수동 트리거 시점이다. #673의 남은 절반(실적재 before/after 실증)은 `T-VN-H30B`가 담당한다.

  > **⚠ 마이그레이션만 올리면 안 된다 — 이미지도 함께 올려야 한다.**
  > prod는 "DB만 뒤처진 불일치"가 아니라 **코드·스키마가 일관되게 0063에 고정된 상태**다
  > (배포 이미지 revision `c8ed6164`). 벌어진 간극은 DB↔코드가 아니라 **저장소↔배포**다.
  > 특히 `0065`는 `uq_curation_items_active_identity`(partial, `WHERE archived_at IS NULL`)를
  > drop하고 partial이 아닌 `uq_curation_items_identity`를 만드는데, **지금 도는 이미지의
  > upsert는 `ON CONFLICT (…) WHERE archived_at IS NULL`을 명시**하므로 이미지를 둔 채
  > 마이그레이션만 적용하면 arbiter 추론이 실패해 curation import·admin item 쓰기가 깨진다.
  > `0065`에는 중복 정리용 `DELETE FROM feature.curation_items`도 들어 있다.

  **실측으로 위험도가 재평가됐다(읽기 전용 조사, 2026-07-30)**:
  - `0065`의 `DELETE FROM feature.curation_items`는 **0행**이다. tombstone dedupe가
    `archived_at IS NOT NULL`을 요구하는데 prod에 그런 행이 **0건**이고, 직전 statement가
    새로 만드는 tombstone도 0건(`status='archived'` 0행)이다. 이번 적용에서는 발화하지 않는다.
    다만 **의미론은 위험하다** — tombstone이 하나라도 있는 identity 그룹에서 survivor는
    tombstone이고 같은 그룹의 **active membership까지 삭제**되며, 백업 테이블을 만들지 않는다.
  - 새 유니크 인덱스 `uq_curation_items_identity`의 충돌 그룹 **0개** → 생성 성공한다.
  - `0065`가 `curation_collections.collection_key` **52개를 재작성**한다
    (`legacy:<theme_uuid>:<source_uuid>:<md5(title)>` 형태, 전부 `published`/`public`).
    실체는 concierge YouTube 장소 후보이고 그 안의 공개 item이 3,044건이다.

    > **정정** — 나는 이걸 "외부 계약이 바뀐다 — PinVi 등 소비자가 참조하면 깨진다"고
    > 적었다. **현재 runtime identity lookup 소비자는 없어 52행 재작성으로 깨지는 호출은
    > 확인되지 않았다.** 위험을 확인하지 않고 단정했다.
    > - `collection_key`를 **조회 키로 받는 엔드포인트가 0개**다 — 전부 `collection_id`
    >   UUID 경로다. 다만 admin collection 생성의 필수 입력·저장 필드이고 목록 검색 대상이므로
    >   단순 출력 필드라는 종전 설명은 틀렸다.
    > - e2e live의 하드코딩 `OFFICIAL_COLLECTION_KEYS` 19개와 재작성 52개의
    >   **교집합 0개**다. 19개는 `created_by='admin'`이고 `migrated_from` metadata가 없어
    >   0065의 `WHERE metadata @> '{"migrated_from":…}'`에서 아예 제외된다.
    > - CSV import는 `ON CONFLICT (collection_key)`로 upsert하지만 CSV의 키
    >   (`korean-tourism-100:2023-2024` 등)가 재작성 대상이 아니라 그대로 매칭된다 —
    >   **중복 collection 생성 없음**.
    > - PinVi runtime client·kor-travel-concierge·kor-travel-docker-manager에는
    >   `collection_key` identity lookup이 없다. PinVi pinned OpenAPI snapshot의 schema
    >   field hit는 소비 호출이 아니며 0 hit 주장에 포함하지 않는다. dagster asset/CLI도
    >   runtime lookup이 없다.
    > - 재계산은 **멱등**이다(`(theme_id, source_id, md5(title))` 기반, prod에 NULL/blank
    >   title 0건, base_key 중복 0건이라 `:split:`/`:conflict:` 접미사 미발생).
    >
    > 남는 것은 계약 **문서화** 권고뿐이다(blocker 아님): `collection_key`는 0045→0065에서
    > 형식이 두 번 바뀐 **불안정 business key**다. admin create·저장·검색과 CSV upsert에는
    > 쓰지만 외부의 장기 참조·path identity는 `collection_id`를 써야 한다.
    > `docs/integration-map.md`에 이 경계를 명시한다.
  - `0065` 후반 quarantine 블록도 **no-op**이다 — canonical-only item(`legacy_projection_id
    IS NULL`)이 prod에 0건이다. 새 유니크 인덱스 위반 행도 0건.
  - `0065`의 대량 UPDATE: `source_updated_at` **3,530행 전량**(WHERE 없음),
    `operator_updated_*` 3,044행, `legacy_projection_id` 3,044행.
  - **트랜잭션 경계 함정**: `alembic/env.py`에 `transaction_per_migration`이 **없어**
    0064~0068이 원래 한 트랜잭션이지만, `0064`의 `autocommit_block()`(CREATE/DROP INDEX
    CONCURRENTLY)이 그 트랜잭션을 커밋한다. 따라서 0065가 실패하면 **0064만 적용된 채
    `alembic_version`은 0063에 남는다**. 0068도 column/default 추가와 constraint validate/
    concurrent index 단계에 `autocommit_block()`을 쓰므로, 실패 시 **version은 0067인데
    0068의 column·constraint·candidate index 일부가 남는 상태**가 가능하다. 0064와 0068은
    이 부분 상태를 감지해 forward 재실행하도록 작성됐고 integration test가 0068/0067
    재개를 고정한다.
  - `0064`는 인덱스만 바꾸고 DML 0건, `downgrade()`도 대칭이라 **완전 가역**이다.

  **선행 조사에서 constraint/data blocker는 확인되지 않았다.** 그러나 0065의 52행 key
  재작성·3,530행 UPDATE와 0066 backfill은 비가역이며, 0064/0068 autocommit은 부분 적용
  상태를 만든다. `collection_key` 재작성으로 깨지는 runtime lookup 소비자는 확인되지 않았다.

  **배포 역학 실측(2026-07-30)**:
  - **`docker/api-entrypoint.sh:216`이 `alembic upgrade head`를 재시도 루프로 직접 돌린다**
    (uvicorn 기동 **전**). 이는 부분 migration 상태에서 새 API가 serving되는 것을 막는
    **기동 gate**이지 DB migration을 원자화하지 않는다. 새 이미지로 API를 recreate하면
    entrypoint가 0064~0068을 forward 재시도하고 head에 도달한 뒤에만 서비스한다.
  - **`docker/dagster-entrypoint.sh`는 마이그레이션을 하지 않는다**(`alembic upgrade` 0 hit).
    dagster는 스키마를 소비만 하므로 API 뒤에 올린다.
  - prod는 external-infra 모드라 local `postgres` service를 띄우지 않는다.
    `scripts/docker-backup.sh`는 standalone compose의 `postgres`를 하드코딩하므로 prod
    복구 수단이 아니다. H35는 배포 전에 external DB용 백업·복원 검증 경로를 먼저 만든다.

  남은 할 일:
  1. **rollback image set 고정** — candidate build 전에 현재 API·UI·Dagster web·Dagster
     daemon 네 service의 실제 container image ID·OCI source revision과 배포
     manifest/compose의 redacted checksum을 기록한다(두 Dagster service가 같은 image ID여도
     service별 결속을 생략하지 않는다). 기존 image ID에 rollback 전용 immutable tag를 붙여
     prune 대상에서 제외하고, 현재 `alembic_version=0063`과 login/API/Dagster smoke를 같은
     manifest에 결속한다. env 비밀 원문이나 `docker compose config`의 비밀 확장 결과는
     산출물에 넣지 않는다.
  2. **candidate 이미지 build-only** — main 최신(H36 게이트 포함)으로 API/dagster/UI를
     기존 rollback tag와 다른 immutable candidate tag에 준비한다. compose 기본 tag를 덮어
     이전 pair를 잃는 build는 금지한다. 이 단계에서는 candidate service의
     `docker compose create/run/up`을 모두 금지한다. 특히 API 기본
     `docker/api-entrypoint.sh`는 serving 전에 `alembic upgrade head`를 실행하므로,
     cold fence와 verified dump보다 먼저 candidate 기본 entrypoint/CMD를 단 한 번도
     시작하지 않는다.
  3. **H36 게이트를 DB와 단절해 확인** — 커밋 라벨만 보지 말고 image layer를 offline으로
     검사하거나, DB credential/env를 주입하지 않은 `--network none --entrypoint` override로만
     candidate image 안의 `_adopted_match` 존재를 확인한다. candidate API의 기본
     entrypoint/CMD를 쓰거나 prod network에 붙여 검사하지 않는다. 검사 직후 현재 배포
     도구 또는 pinned PostgreSQL client의 read-only query로 prod
     `alembic_version=0063_pipeline_root_id`가 그대로인지 확인하고, 달라졌다면 step 4로
     진행하지 말고 비인가 migration으로 취급해 상태를 보존·조사한다. 라벨은 빌드 컨텍스트를
     증명하지 않는다.
  4. **cold writer fence** — prod ingress를 maintenance 상태로 두고 기존 app DB write
     schedule/sensor의 enablement를 기록한 뒤 모두 pause하고, pending/running run 0건을
     확인한다. 기존 API·Dagster web·Dagster daemon을 정지하고 map 소유 writer
     container/process 0건과 app 역할의 active write transaction 0건을 확인한 시점부터
     dump·migration·구조 smoke가 끝날 때까지 fence를 유지한다. dump 뒤 정상 write가 생길
     수 있는 상태에서는 복원을 복구 경로라고 부르지 않는다.
  5. **prod external DB 백업·복원 gate 실행** — 비밀을 argv/log에 싣지 않는
     `PGSERVICEFILE`/`PGPASSFILE` 기반의 pinned PostgreSQL client로 app·Dagster DB를 custom
     dump한다. SHA-256과 `pg_restore --list`만 확인하고 끝내지 않고, 격리 scratch DB에
     실제 복원해 pre-migration head·핵심 schema/row count를 대조한다. standalone
     `scripts/docker-backup.sh`를 prod에서 호출하지 않는다.
  6. **API candidate recreate** → fence 안에서 entrypoint가 0064~0068을 forward 적용한다.
     실패하면 downgrade하지 않고 `alembic_version`과 0064/0068 partial-state probe를
     기록해 같은 image/command로 재개한다.
  7. **fence 안 구조 실증(반증 가능해야 한다)**:
     - `alembic_version = 0068_integrity_last_seen`
     - 0068의 `last_seen_at` column/default/NOT NULL·FK·세 concurrent index가 모두 최종
       shape이며 invalid/candidate index와 임시 constraint가 남지 않음
     - `uq_violations_open_dedupe_key` 인덱스 존재 / `last_seen_at` 컬럼 존재
       (둘 다 지금은 **없음**이 확인돼 있어 before/after가 갈린다)
     - curation import **preview**가 오링크 3건을 여전히 미연결로 두는지
       (H36 게이트 실효 확인. 실패했다면 `resolved_feature_id`가 채워져 값이 달라진다)
  8. **post-migration 격리 bundle·daemon preflight** — candidate API를 다시 정지해
     prod app·Dagster DB writer 0건을 재확인한 뒤, 0068 상태의 app·Dagster DB를 H30B용
     immutable custom dump bundle로 만든다. SHA-256·`pg_restore --list`와
     pre-materialize Feature **1,020**, head·schema/content identity를 기록한다. 실제
     concierge `changes` export도 cursor 없이 시작해 끝까지 한 번 수집하고, ordered page
     envelope마다 request cursor·`next_cursor`·`has_more`와 item 원문(operation 포함)을
     credential/header 없이 canonical JSON artifact로 보존한다. cursor chain의 전진·종료와
     전체 **1,477행**을 확인하고 payload SHA-256을 DB dump·candidate image manifest와
     하나로 결속한다. producer에는 durable snapshot/version identity가 없으므로 count만
     기록한 live 재조회는 같은 입력으로 인정하지 않는다. step 5에서 쓴 같은 scratch DB pair를
     reset·복원해 DB identity를 대조하고, candidate Dagster daemon을 prod credential·network
     없이 이 scratch pair에만 연결해 모든 app DB write schedule/sensor pause·pending/running
     run 0 상태에서 실제 기동한다. image ID·OCI revision·heartbeat/health 검증 뒤 정지하고,
     preflight가 scratch metadata를 바꿨다면 같은 pair를 signed DB bundle로 다시 reset해
     H30B 인수 identity를 복구한다. 별도 clone은 만들지 않는다.
  9. **prod 비-daemon candidate recreate·health** — API·UI·Dagster web을 각 service에
     고정한 immutable candidate image ID로 recreate한다. 세 service의 실제 container
     image ID·OCI revision과 login POST·API·Dagster web health를 candidate manifest에
     대조한다. prod Dagster daemon과 app DB write schedule/sensor는 계속 정지·pause한다.
     old container를 단순 start하거나 UI만 이전 image로 남긴 상태에서는 다음 단계로 가지
     않는다.
  10. **cutover 전 실패 복구 분기** — forward 재개가 불가능해 verified dump를 복원할 때는
     fence를 유지한 채 candidate를 모두 내린다. DB를 0063 dump로 복원하고 step 1의 exact
     rollback service image ID·manifest/compose checksum으로 API·UI·Dagster web을
     recreate한다. 이전 set의 `alembic_version=0063`, 세 실행 service identity와
     login/API/Dagster web smoke가 green임을 확인해 rollback을 확정한 뒤 exact 이전 daemon을
     시작하고 step 4에 기록한 schedule/sensor enablement를 복원한다. daemon identity·health가
     green인 뒤에만 fence를 해제한다. 새 candidate entrypoint를 복원 DB에 다시 실행하는
     절차는 rollback이 아니다.
  11. **forward-only cutover·prod 정상화·H30B handoff** — 구조·세 prod service health와
      step 8의 isolated daemon runnable gate가 모두 green이면 forward-only cutover를
      확정한다. 이 시점부터 옛 dump 복원을 금지하고 실패를 forward 수정으로만 처리한다.
      prod candidate daemon을 writer pause 상태로 시작해 실제 image ID·OCI revision·health를
      확인한 뒤 step 4에 기록한 schedule/sensor enablement와 API·Dagster/UI ingress를
      복원한다. H35에서는 concierge materialize를 실행하지 않는다. prod를 정상 상태로
      돌려놓고 step 8의 signed post-migration DB·concierge export bundle과 clean scratch
      identity만 H30B에 넘긴다. 실제 1,020→1,477 회복과 authenticated `/admin/issues`
      검증은 export artifact를 network-free로 재생하고 격리 DB만 사용하는 다음 단일 소유
      task `T-VN-H30B`가 수행한다.

  > **⚠ 비가역 지점** — 사람 승인이 필요하다.
  > - `0065`의 `collection_key` 52행 재작성과 `source_updated_at` 3,530행 UPDATE,
  >   `0066`의 `external_component_id` backfill은 **downgrade로 복구되지 않는다**.
  >   검증된 external DB dump와 0063-compatible rollback image set·배포 manifest를 함께
  >   보존한 bundle이 유일한 복구 경로다.
  > - `0064`와 `0068`의 `autocommit_block()` 때문에 **부분 적용 상태가 가능하다**.
  >   entrypoint가 실패 시 재시도하므로 forward recovery를 우선하고 꼭 필요한 경우가
  >   아니면 Alembic downgrade하지 않는다. 계속 실패하면 API가 기동하지 않아 장애가
  >   조용히 숨지는 않지만, DB가 자동으로 원상복구되는 것도 아니다.
  > - 이미지 교체는 다운타임을 만든다.
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

  **범위 확인(2026-07-30)**: 등대 **스탬프투어 자체는 이미 들어 있다** —
  `resources/curations/lighthouse-stamp-tour.csv`에 6시즌 105행
  (아름다운 15 / 역사 16 / 재미있는 18 / 풍요로운 17 / 힐링 16 / 해돋이 23).
  빠진 것은 스탬프투어가 아니라 **등대 feature 공급원**이다. 이름 매칭으로는 103건 중 89건이
  상호가 `등대`인 **가게**에 붙는데, 그게 실제 등대 데이터가 DB에 없다는 증거다.

  **결정(사용자 지시, 2026-07-30) — 등대는 API가 없다. 저장소 CSV가 정본이고 불변값으로 읽는다.**
  갱신은 파이프라인 밖에서 **사람이 CSV를 직접 편집**한다. 이건 기존 provider 패턴과 다르므로
  아래를 지켜야 한다.

  - **새 소스 종류다.** 기존 `src/kortravelmap/providers/*`는 전부 외부 `python-*-api`
    레코드를 받는 **순수 변환 함수**이고(ADR-006), 저장소 상주 CSV를 feature 공급원으로 쓰는
    선례가 없다 — `resources/`에는 `curations/`뿐이다. **API가 존재하지 않기 때문에** 두는
    의도적 예외이며, ADR로 남긴다(다음 후보 **ADR-080**).
  - **변환은 순수 함수로.** `providers/`에는 `Mapping` → `FeatureBundle` 변환만 두고
    **파일 읽기는 호출자(cli/dagster)가** 한다 — 기존 provider 모듈과 같은 모양을 유지하고
    의존 방향(`… → geocoding → providers → client → cli`)을 지킨다.
  - **feature_id가 재적재마다 흔들리면 안 된다.** 사람이 좌표를 보정하는 편집이 예상되므로
    `make_feature_id`의 자연키를 **좌표가 아닌 안정 식별자**(항로표지번호 등 CSV의 불변 열)로
    잡는다. 좌표를 키에 넣으면 편집 한 번에 링크가 전부 끊긴다 —
    `T-VN-H33`/`T-VN-H36`에서 겪은 문제와 같은 계열이다.
  - CSV의 `provider` 열은 이미 `korea-navigation-aids-agency`로 적혀 있다. 그 이름을 쓸지,
    정적 소스임을 드러내는 이름을 쓸지 확정한다.
  - **CSV 자체의 무결성 게이트**를 둔다 — `resources/curations/manifest.json`이 sha256을
    갖는 것처럼, 손편집이 조용히 깨지지 않게 행 수·필수 열·좌표 범위를 검사한다.
    (H25B에서 manifest sha를 손으로 유지하다 게이트가 깨진 전례가 있다.)
  - 링크는 **자동으로 붙이지 않는다** — `T-VN-H36`이 이름 단독 자동링크를 금지했다.
    등대 feature가 적재되면 CSV `feature_id`를 채우는 것은 별도 판정 절차다.

  할 일: 등대 원천 데이터 확보·CSV 스키마 확정 → 변환 함수 + 적재 경로 → 무결성 게이트 →
  ADR-080 → 링크 판정(별도).

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
  collection 정리를 파괴적으로 검증한다. 같은 `curation-collections-client.tsx`와 mocked spec의
  선행 작업 T-VN-48B·49B는 모두 완료됐으므로 H22A/B 뒤 최신 구조 위에서 시작한다. 49B 코드와
  이 선행 조건 해제는 같은 merge commit으로 `main`에 반영한다.

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

## Lane B 상세 — b1 PinVi 결합·후속

### T-VN-16 — weather batch와 부모 404

단일 날짜 생산자와 날짜별 PinVi 소비는 완료됐다. 16B 적대 리뷰에서 확인한 날짜 fan-out과
31일 조회 상한을 sparse 다중 날짜 계약으로 제거한다.

- [ ] T-VN-16C — **sparse 다중 날짜 weather batch**

  Map은 날짜별 실제 Feature ID만 받는 `targets[{target_at, feature_ids}]`를 한
  PostgreSQL snapshot statement로 읽는다. target/group/pair/전체 metric row budget,
  canonical ordering, 중복 거부와 전량 성공·실패를 계약으로 고정한다. PinVi는 한 Trip
  view를 호출 한 번으로 소비해 31일 `not_requested` 상태와 worker/time budget fan-out을
  제거한다. Map query plan·OpenAPI와 PinVi 장기 여행 파괴적 Live UI가 완료 조건이다.

  - [x] Map 생산자: 고유 parent별 spatial 후보를 한 번 계산하고 target별 bitemporal
    fact로 최종 source를 결정한 뒤 같은 target/source bundle을 `card_key`·`cards[]`로
    정규화한다. 요청·계획·series·metric·payload·timeout 예산을 전량
    성공·실패 계약으로 고정했다. 실데이터 40 target × 5 Feature는 200 pair·공유 card
    40개·11,763 metric을 5.77초에 반환한다(본 PR landing으로 완료).
  - [ ] PinVi 소비자: Trip view당 sparse batch 호출 한 번, 장기 여행 UI와 실패 상태를
    새 공유 card 계약으로 전환한다(Map 생산자 merge 뒤 별도 호환 PR).

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
