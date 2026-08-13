# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스 (2026-08-13 T-VN-36 PR #973 머지 후 재대조)

완료한 `T-VN-32`·`T-VN-33`·`T-VN-37`·`T-VN-38`과 선행 운영 task는
[`tasks-done.md`](tasks-done.md)로 이관했다. 아래에는 아직 닫히지 않은 실행 단위만 둔다.

**Lane A (Claude Code)**와 **Lane B (codex)**는 서로 병렬 실행한다. 각 lane 내부는 아래 순서를
지키며, 같은 migration head·OpenAPI 정본·같은 cross-repo pair를 만지는 시점만 공통 규율의
barrier로 직렬화한다.

- **Lane A — cross-repo 계약·운영·데이터 품질**
  - [~] `T-VN-H25B` → [ ] `T-VN-H34`(공식 curation 미연결 membership 잔여 AC)
  - [~] `T-VN-H43` → [~] `T-VN-H44`(백업 정기화·복원 드릴 재개 조건)
  - [ ] `T-VN-H45-후속`(다건 provider fetcher·quota 관찰 확장)
  - [~] `T-VN-H46A`(alembic squash — PR #978 CI 대기) →
    [ ] `T-VN-H46C`(VWorld fallback 사슬 제거) ∥ [ ] `T-VN-H46D`(daemon 스키마 drift)
- **Lane B — frontend hardening·PinVi 소비 API**
  - [ ] `T-VN-41A` → [ ] `T-VN-41B` → [ ] `T-VN-41C`(generation/outbox)
  - [/] `T-VN-41F1D-D` → [ ] `T-VN-41F1D-D2`(격리 리허설·data-dependent live UI E2E)
  - [~] `T-VN-41F1D-E`(v5/v7 attestation 전환) ∥ [ ] `T-VN-41S`
- **Wave 2 barrier 이후**
  - Lane A: [x] `T-VN-35/34/36-deploy`(`0104` prod cutover 완료 2026-08-13) → [ ] `T-VN-37D`
  - Lane B: [x] `T-VN-34A` → [x] `T-VN-34B` → [x] `T-VN-34C` →
    [x] `T-VN-36A` → [x] `T-VN-36B` → [x] `T-VN-36C` → [x] `T-VN-36D` →
    [x] `T-VN-36-live`(격리 clone 인수 완주 — 2026-08-13)
  - 32~38 join barrier 뒤 Lane B: [ ] `T-VN-40A` → [ ] `T-VN-40B` →
    [ ] `T-VN-40C`
    - A/B/C는 logical phase이며 **하나의 forward-only implementation PR/release**로만 구현·병합한다.
      phase별 writer/migration/consumer PR 또는 중간 배포는 금지한다.
    - T-VN-36 PR #973이 `c76ceb7a`로 `main`에 병합돼 join barrier가 해소됐고,
      2026-08-13 사용자가 ADR-092와 40A/B/C 단일 PR 구현을 승인했다. 설계·구현 정본은
      [`t-vn-40-curation-write-model-plan-2026-08-11.md`](reports/t-vn-40-curation-write-model-plan-2026-08-11.md)다.
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
  감사 수정만 유지한다. **Lane A a1 task PR 사후 감사도 독립 적대 리뷰어 1명**을 쓰고,
  docs-only·rebase-only·import 정렬·변수명 교정 같은 기계적 변경은 추가 적대 재리뷰 없이
  진행한다(사용자 지시 2026-07-31).
- 첫 reviewable checkpoint부터 원격 feature branch에 작은 의미 단위로 자주 커밋·push하되,
  PR도 첫 checkpoint에서 열고 후속 commit을 계속 붙인다. PR review comment는 진행 중
  반영하며 실패하면 검증된 직전 checkpoint부터 재개한다.
- **Lane A**: PR #869 다음 PR부터 적대적 리뷰어 **1명** 반영 후 n150 **파괴적 live E2E**
  (실데이터)로 검증하고 PR·CI green·머지. 작업 중 발견 항목은 tasks.md에 즉시 추가.
- **Lane B**: PR #869 다음 PR부터 적대적 리뷰어 **1명** 반영 후 n150 **실데이터 파괴적 Live UI
  E2E**를 통과하고 PR·CI green·머지한다. task 완료 시 상대 lane 2일치 PR 적대 리뷰 관행 유지.
- **일회성 문서 예외**: 사용자 지시에 따라 PR #870은 코드·DB·runtime 변경이 없는 task 재배치
  문서 PR이므로 당시 문서/보안 gate는 유지하되 파괴적 Live UI를 실행하지 않고
  CI 결과를 기다리지 않고 머지한다. 이 예외는 후속 문서 PR에 자동 승계되지 않는다.
- **우선순위(서비스 전 단계 — 사용자 지시 2026-07-26)**: **정확성·보안 최우선은 불변**
  (AGENTS.md), 그 아래 설계적 우수성 > 확장성 > 성능 > 불필요한 코드 반복(래퍼류) 금지.
  **prod 환경 보전·호환성·기존 문서 계약·최소 수정은 비제약** — 필요 시 DB 스키마·문서
  계약 수정 가능. AGENTS.md vNext 우선순위 단락에 동일 취지의 dated note를 둔다.
- migration 정본: 단일 head 유지(2026-08-13 `main` 기준 head
  `0104_tvn36_final_fence`; prod 적용 head는 `0087_route_area_subtypes` —
  2026-08-13 실측, `T-VN-35/34/36-deploy` 참조). 후속 migration 소유자는
  PR 직전 단일 head를 재확인한 뒤 번호를 배정한다. 두 lane의 migration-bearing PR은 번호 예약부터
  머지까지 직렬화한다. forward migration 뒤에는 수용 조건이나 실패 복구가 명시적으로 요구하지 않는
  한 downgrade/rollback하지 않고 fresh clone·새 transaction으로 다음 검증을 이어간다.
- **리뷰어 수(사용자 지시 2026-07-31)**: 코드·runtime·API·DB·migration·보안 동작을
  바꾸는 PR은 적대 리뷰어 **1명**이 전체 누적 delta를 검토한다. 리뷰 뒤 새 일반 코드 변경이
  누적되면 같은 리뷰어가 재검토한다. 리뷰 지적의 국소 반영, 문서 전용 추가 commit,
  rebase-only, import 정렬·변수명 교정 같은 기계적 변경은 추가 적대 재리뷰 없이 진행한다.
- **Wave 2 DB 설계 예외(사용자 지시 2026-08-06)**: T-VN-33부터 T-VN-41 이후의
  schema·migration·API contract 변경은 적대 리뷰어 **2명**이 독립적으로 P0=0을 확인해야
  한다. 이 규율은 위의 일반 1인 규율보다 우선하며, 두 리뷰의 지적을 반영해 추가한 일반
  변경도 두 관점 재리뷰 대상이다.
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
  commit으로 landing한다. PR #906에서 완료한 T-VN-12A의 정적 command registry와 CI
  완전성 검사가 새 write route를 미등록 상태로 둘 수 없게 한다. 미래 H22B reclassification
  command도 생성 시점부터 같은 actor-scoped ledger 계약을 등록해야 하므로 종전의 H22B
  선행 barrier는 없다.
  Wave 2는 T-VN-31A~C freeze가 모두 머지되기 전에 시작하지 않는다.
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
  - **주소 축 시군구 단위 대조** — ~~미충족~~ → **위 도구에 통합(완료)**. 다만 **천장이 실증됐다**:
    전수 8건의 결함이 **행정구역 축으로는 전부 통과**한다(주차장·카페·펜션이 대상과 같은
    시군구에 있다). 시군구 축은 *기각*에 쓸 수 있어도 *확정*의 충분조건이 아니라는 본문 서술이
    맞았고, **카테고리 축이 추가로 필요하다는 것이 새 발견이다.**
    > **문구 정정(2026-07-29)** — 이 항목을 "`metadata.region`을 시군구까지 본다"로 읽으면
    > **실행 불가**다. `region`은 `강원`·`충북` 같은 **시도 약칭뿐**이라 시군구를 담을 수 없다.
    > 실제로 가능한 축은 **정지오코딩 결과의 시군구코드 ↔ feature `sigungu_code` 대조**이며,
    > 청풍호에서 손으로 한 것이 바로 그것이다(제천 `43150` 일치). 따라서 이 항목은 아래
    > "정지오코딩 세션 고정"과 **같은 도구로 함께** 해결된다 — 별개 축이 아니다.
    >
    > **천장도 같이 기록한다**: 시군구까지 내려가도 같은 시군구 안의 다른 대상은 구분되지
    > 않는다(청풍호 vs 청풍호반케이블카). 시군구 축은 *기각*에는 쓸 수 있어도 *확정*의
    > 충분조건이 아니다.
  - **provider provenance** — ~~설계 또는 불가 확정~~ → **불가로 확정(2026-07-31, 실측)**.
    > CSV 5개 486행은 `provider`/`dataset_key`/`source_item_key`/`source_component_key`가
    > **전부 채워져 있다**. 그런데 그 값이 `provider_sync.source_entities`에 **하나도 없다** —
    > 10종 조합 전부 provider 이름조차 **0 hit**다(`korea-tourism-organization`,
    > `korea-heritage-agency`, `korea-arboreta-and-gardens-institute`,
    > `korea-institute-of-aids-to-navigation`). `source_entities`의 provider는 전부
    > `python-*-api` 계열(`python-mois-api` 977,908 / `data.go.kr-standard` 21,102 …)이다.
    > **CSV의 provider는 캠페인 주관기관이고 source_entities의 provider는 수집 라이브러리라
    > 서로 다른 네임스페이스다.** `source_item_key`(`arboretum-2026-001` 등)도
    > `source_entity_id`/`source_entity_key`/`current_source_record_key` 어디에도 0 hit.
    > 공식 CSV는 provider 파이프라인을 거치지 않고 직접 적재되므로 `source_entities`에 대응
    > 행이 **없는 것이 정상**이다. 조인 경로를 만들려면 기관↔라이브러리 매핑을 발명해야 하고
    > 그건 의미가 없다.
    >
    > **본문 전제 정정** — "미연결 행에서 전부 NULL"은 맞지만 전체 모집단으로 읽으면 틀린다.
    > 실측: active 3,530건 중 `source_record_key` 보유 **3,044건**. NULL은 공식 CSV 적재분
    > **486건**뿐이고 링크 222 / 미연결 264로 갈린다.

    > **정정 (2026-07-31, #910/`0072` 반영) — 내가 틀린 것은 실측이 아니라 범위다.**
    > 위 실측(CSV provider = 캠페인 주관기관 / `source_entities` provider = 수집 라이브러리,
    > 서로 다른 네임스페이스)은 **그대로 유효하고 #910도 같은 판단을 한다** — `0072`가 기존
    > link를 `match_basis='legacy_unattributed'` · `resolver_version='pre-0072-unknown'` ·
    > evidence "기존 link의 선택 근거를 안전하게 복구할 수 없음"으로 backfill한다.
    > 즉 "기존 링크의 근거는 추정하지 않는다"는 결론은 동일하다.
    >
    > 틀린 것은 거기서 **"따라서 이 AC는 달성 불가"로 건너뛴 것**이다. AC 원문은
    > "provider provenance — **설계 또는 불가 확정**"이었는데 나는 "설계" 갈래를
    > **기존 스키마 안에서만** 탐색했다("조인 경로를 만들려면 기관↔라이브러리 매핑을
    > 발명해야 한다"). **스키마 변경을 검토 범위에서 뺀 것이 오류다.**
    >
    > #910이 택한 축은 provider 귀속이 아니라 **import 행위(act) 귀속**이다 —
    > `curation_import_batches`(어떤 바이트를 누가 언제) / `curation_import_rows`(그 batch의
    > 어느 행이 어느 item이 됐는가) / `curation_link_decisions`(그 link를 누가 무슨 근거로
    > accept 했는가). 이 축은 provider 파이프라인을 거치지 않는 공식 CSV 적재에도
    > **정의상 항상 존재한다** — 사람이 파일을 올린 행위 자체가 출처다.
    > 내가 "공식 CSV는 provider 파이프라인을 거치지 않으므로 대응 행이 없는 것이 정상"이라고
    > 쓴 그 문장이 **다른 provenance 축이 필요하다는 신호**였는데, 나는 그것을 AC 종료
    > 신호로 읽었다.
    >
    > 따라서 이 항목은 "불가"가 아니라 **"기존 스키마 안에서는 불가 / 새 축으로 해소(#910)"**다.
  - **preview/commit·REST/UI 실데이터 검증** — ~~미충족~~ → **REST는 실증 완료(2026-07-31)**,
    preview는 **prod 미배포로 측정 불가**.
    > `GET /v1/curations/features/{id}` 실측(prod, service token):
    > `국립세종수목원` **6건**(공식 3 + concierge legacy 3) / `진해보타닉뮤지엄` 1건 /
    > `청풍호` 1건. `GET /v1/features/{id}` 200, `GET /v1/curations/collections` 200에
    > 공식 collection **19건** 공개. **링크는 화면·API에 실제로 반영돼 있다** — 그래서 위
    > 카테고리 결함도 공개 표면에 그대로 노출된다(진해보타닉뮤지엄이 카페로, 청풍호가 펜션으로).
    >
    > **import preview의 H36 게이트 동작은 prod에서 잴 수 없다** — 배포 이미지가 `c8ed6164`라
    > `_adopted_match`가 없고 `0066`의 `external_component_id`도 없다.
    >
    > **2026-08-13 갱신**: 이 blocker는 사라졌다. 두 심볼 모두 head에 있고
    > (`curations.py`의 `_adopted_match`, `curation_repo.py`의 `external_component_id`),
    > 가리키던 `T-VN-H35` 배포는 소멸했다(`tasks-done.md` — "이 항목 아래의 cutover
    > 설계는 전부 이력이다. 실행하지 마라"). 현재 배포 소유자는 `T-VN-35/34/36-deploy`이고,
    > 측정은 `T-VN-36-live`의 격리 clone(실 prod 데이터, `0104`)에서 `dry_run=true`
    > preview 한 번으로 가능하다.
    >
    > 측정 실수 기록: ① 원격 셸에서 명령치환이 깨져 토큰이 비었고 401을 엔드포인트 인증
    > 문제로 오독할 뻔했다(스크립트 파일로 해결). ② 응답 구조가 `data.feature`+`data.curations`인데
    > `data`를 리스트로 기대해 **"0건"으로 잘못 보고**했다. 둘 다 그럴듯한 값이 나와 확인하지
    > 않았으면 틀린 결론이 됐다.
  - **정지오코딩 세션 고정** — ~~신설~~ → **완료**: [`scripts/h25b_verify_links.py`](../scripts/h25b_verify_links.py).
    판정 축 3개(행정구역 시도코드 대조 / **카테고리 정합성**(신규) / 동명 유일성).
    현재는 `--scope public`로 운영 public repository 정본을 훑고, 과거 H25B 내부 승인
    5건은 `--scope approved`로 명시 분리한다. 단위 테스트는
    [`tests/unit/test_h25b_verify_links.py`](../tests/unit/test_h25b_verify_links.py).

    **전수 실행 결과(222건 링크, 2026-07-31)**: 모순 **8건** / 무모순 214건.
    8건은 전부 **카테고리 축에서만** 걸린다 — 행정구역 축으로는 10건 전부 통과한다.
    고유 feature 5개:
    | curation | feature category | 판정 |
    | --- | --- | --- |
    | `태화강 국가정원`(2캠페인 3행) | `06010000` TRANSPORT_PARKING | 그 관광지의 **주차장**에 붙음 |
    | `반디랜드&태권도원`(2행) | `06010000` TRANSPORT_PARKING | 동일 |
    | `김해가야테마파크` | `06010000` TRANSPORT_PARKING | 동일 |
    | `진해보타닉뮤지엄` | `02020100` FOOD_CAFE_COFFEE | 카페에 붙음 |
    | `청풍호` | `03050200` LODGING_PENSION_RURAL | 농어촌펜션에 붙음 |

    **장소는 맞고 유형이 틀린 것**이다(좌표·주소가 대상과 일치). H33이 해제한 3건처럼
    *다른 장소*에 붙은 오링크가 아니므로 **링크 해제가 아니라 올바른 feature로 재연결하거나
    카테고리를 고치는 것**이 맞다. 후속 처리는 별도 판단이 필요하다.

    > **판정 로직을 두 번 고쳤다(기록)**. ① 동명 다수를 *모순*으로 셌다 → 222건 중 30건이
    > 모순으로 잡히고 그중 20건이 이 축 단독이었다. 동명 다수는 반증이 아니라 **그 축으로
    > 확정할 수 없다**는 뜻이다(30→10). ② 카테고리 기대를 `01`(TOURISM)만으로 좁혔다 →
    > `장태산자연휴양림`·`거창 항노화힐링랜드`(`03030000` LODGING_RECREATION_FOREST)가
    > 오탐이 됐다. 숙박을 갖춘 휴양림이 그렇게 분류되는 건 정당하다. 축을 "관광이어야 한다"에서
    > **"명백히 대상일 수 없는 유형인가"** 로 뒤집었다(10→8). 두 회귀 모두 단위 테스트로 고정했다.

> **issue #673 판정(2026-07-30) — 아직 닫을 수 없다.** 서브에이전트 조사로 이슈 본문·코멘트를
> 요구사항으로 분해해 대조했다. 3항목 중 둘(오탐 분포 규명 / 규칙 교체)은 충족이고,
> 셋째("다음 materialize에서 자동 회복되는가")는 **코드 논증만 있고 실증이 없다**.
> 결정적 blocker는 **prod 미배포**이며 이슈가 신고한 손실(당시 457건)이 실재한다 →
> ~~`T-VN-H35`~~ **`T-VN-35/34/36-deploy`**(2026-08-13 정정 — H35의 cutover는 소멸했다).
> "457건"은 prod 폐기·재생성(`0078`) **이전** 측정값이라 그대로 쓸 수 없다. prod는 현재
> `0087` / feature 1,008,852이므로 배포 전 재측정이 필요하다.
> **재기준화(2026-07-31, #910/`0072` 반영)** — #673을 "457건 신규 회복"만으로 종결하면 안 된다.
> `0072`가 기존 concierge 공개 표면 **3,044건**을 `legacy_unattributed`로 만들어 공개에서
> 제외하고 복구 경로가 없다(`T-VN-H40`). 따라서 종결 기준은 **두 축**이다 —
> ① 미적재 457건 신규 회복 ② **기존 concierge 공개 표면 보존/복구**. ①만 달성하고 ②를 잃으면
> 순 손실이다.
>
> 남은 실증은 `T-VN-H30B`. **`T-VN-H30C`·`T-VN-H32`는 #673 범위 밖**이다 —
> 이슈는 "concierge provider에 한해" 완화를 요구했고 두 task는 그 파생 개선이다.
> 저장소 열린 이슈는 #673·#819 두 건뿐이고 #673은 epic이 아니다.

### T-VN-H42~H45 — 운영 연속성 (0072 사고 후속: 재적재 수렴 → 강건화 → 백업 → 복원 드릴)

> 2026-08-04 prod 폐기·재생성(head `0078`) 후속. 2026-08-05 이미지 `c0afaa4e` 배포로
> head `0082`(UUID shadow 3종) 적용 완료 — **다만 2026-08-13 실측 prod head는 `0087`이고
> feature는 1,008,852행이다**(이 문단이 5 revision 뒤처져 있었다). 따라서 최신 H43
> baseline `2026-08-05-h43-postdeploy-0083.dump`(731,765행)는 두 head·약 27만 행 뒤처진
> 복구점이며, `0104`가 `feature_versions`/`data_origin`/`feature_change_requests`를
> 물리 삭제하므로 H44의 복원 실증도 `0083` 기준이라는 점을 함께 읽어야 한다.
> prod는 `archive_mode=off`라 **PITR이 없다 — dump가 유일 복구점**이다. codex 소관 41C prod enable은 H42 판정 + docker-manager
> 재pin 뒤(Lane B T-VN-41 절 경계 주석).

- [ ] T-VN-H45-후속 — **다건 provider 호출·quota 관찰 확장**

  완료한 KMA/airkorea 강건화(`T-VN-H45`)의 후속으로 ① khoa 등 다건 루프 fetcher 확대,
  ② python-kma-api resultCode 22 quota `retryable=True` 오분류와 200-body XML envelope
  parse 경로, ③ RetryBudget 비례화/settings 노출 및 `_LOGGER` `python_logs` 결선,
  ④ KMA 4종+airkorea schedule `coalesce_active_runs=True`, ⑤ alembic 1.19 적응을
  실측 우선순위로 분리한다.

- [~] T-VN-H43 — **prod 백업 체계 수립 (정기 dump·sha256·보존·rollback 기준선)**

  절차 정본은 `docs/backup-restore.md` §9(2026-08-05 신설 — n150 수동 기준선,
  TCP 경로 강제·manifest 필수 항목 `ops.public_api_keys` 포함).

  - [x] 기준선 dump — `2026-08-05-h43-baseline.dump`(435MB, sha `717790c0…`,
    manifest·`pg_restore -l` 검증) + 배포 직전 **write-fence rollback 기준점**
    `2026-08-05-prefence-0082.dump`(sha `d367fbd1…`, write path 정지 후 생성 —
    ADR-075 기준점 규칙 정합).
  - [x] 배포 후 기준점 — `2026-08-05-h43-postdeploy-0083.dump`(489MB, 0083
    적용·값 전환 배포 후, manifest: features/aliases/public 731,765 동수 ·
    pair_mismatch 0 · orphan_alias 0)와 **dev box 외부 사본 1회 반출**
    (`~/ktm-h43-external/`, sha256 대조 OK) — 오프박스 사본의 첫 실물.
  - [보류] 정기화 — 보존 정책·주기 실행·2차 외부 사본 자동화는 **현 환경에서
    수행하지 않는다**. n150은 실 production이 아니며 손상 시 재적재가 정책이다
    (사용자 지시 2026-08-06). 복원 가능성 자체는 H44가 실증했으므로 열린
    리스크가 아니다. 실 prod 전환 시 manager **#148**(일 1회 dump+sha256+
    manifest·retention·오프박스 반출·배포 직전 fence dump)로 재개한다.
  - [ ] 신규 DB 프로비저닝 함정 참조 링크 — superuser 확장 4종 사전 생성
    (manager #109 절차)을 restore 문서에서 링크한다.

- [~] T-VN-H44 — **복원 리허설 드릴 정기화 (H30B 하네스 재사용)**

  백업본이 실제로 복원되는지를 반복 가능한 드릴로 정착시킨다. **타이밍: H43 뒤,
  이후 정기.**

  - [x] 드릴 1회차 완주(2026-08-05) — `2026-08-05-h43-postdeploy-0083.dump`
    (489MB) 대상, dev box WSL 격리 PostGIS에서 5단계 전부 통과: 확장 4종
    선생성 → `pg_restore`(예상 오류 1건만) → **manifest 완전 일치**(head
    0083 · features/aliases/public 각 731,765 · pair_mismatch 0 · orphan
    0) → replica 세션 우회로 alias 5건 결손 주입 → `missing_alias=5` 관측
    검출 → 정본 재생성 replay → 4축 0·행수 원복.
  - [x] restore 요령 고정 — `docs/backup-restore.md` **§10**(절차 5단계 +
    함정: 확장 선생성 충돌 오류 1건이 정상, 컨테이너 `/dev/shm` 64MB로
    73만행 병렬 집계 실패 → `max_parallel_workers_per_gather=0` 또는
    `--shm-size`).
  - [ ] 주기화 — "migration 동반 릴리스 뒤 + 최소 월 1회" 규약을 §10에
    명문화했으나 실행 트리거(캘린더/자동화)는 미결선. H43 정기화
    (manager #148)와 함께 묶는다.

## 이슈 종결 추적

> landing task와 완료 조건이 동일한 열린 이슈만 함께 닫는다. LIVE-01 후속 OPEN 7건은 Lane A
> `T-VN-H16`/`T-VN-H17`에서 독립 재검증해 **7건 전부 close**했다. 6건은 H16
> (dm#63·#70·map#712·#719·#777·#694), map#684는 H17에서 조건 #8을 "write/error UI 엣지는
> mock, read·URL·freshness + write 계약은 live"로 명시 축소한 뒤 close했다.

- **task로 승격**: map #673=`T-VN-H28A/B`, map #819=`T-VN-H27`(보류).
- **종결**: map #738은 lane 분배 정본을 본 문서로 이관해 닫혔다. map #930(geo key
  미결선 — dagster job 고착)은 docker-manager compose 결선(#114 트랙) + 3 컨테이너
  env 실측 + krex job 연속 SUCCESS로 2026-08-05 close.
- [ ] T-VN-EXT-PINVI-215 — **PinVi #215 외부 follow-up 추적**

  post-review cleanup 잔여(ADR-045 VWorld 불투명 자격증명 hard-gate 등)는 PinVi 저장소가
  소유한다. Map Agent A/B 실행 queue에는 넣지 않고 PinVi #215가 닫힐 때 상태만 동기화한다.

### T-VN-H46 — alembic squash + 배포 위생 (2026-08-14)

- [~] T-VN-H46A — **alembic squash: 체인 109개 → `0200_schema_baseline`**

  draft PR [#978](https://github.com/digitie/kor-travel-map/pull/978).
  근거·설계는 `alembic/versions/0200_schema_baseline.py` docstring과
  `alembic/legacy_versions/README.md`가 정본. 요지만:
  체인은 prod in-place cutover(2026-08-13) 이후 **어떤 DB에서도 실행되지 않는다.**
  sidecar SQL은 `scripts/build-baseline.sh`의 기계 산출물이고 `0200`이 byte sha로
  잠근다. 빈 DB 적용 4초.

  동등성 증명은 `scripts/compare-schema-catalogs.sh`(변조 7종 자체검증)로 카탈로그
  2486행 전부 일치. ⚠️ `contracts/vnext/target-schema-fingerprints-v1.json`은 이
  증명에 **쓸 수 없다** — 그 기준은 alembic head가 아니라 빈 PostGIS DB다
  (`tests/integration/test_vnext_target_freeze.py:574`).

  중간에 나온 결함이 본론이었다: 소유자가 아닌 GRANT는 오류가 아니라 **경고 후
  무시**라서, baseline이 `exit 0`으로 통과하면서 routine 10개를 PUBLIC EXECUTE로
  남겼다(102 → 112). ACL 블록마다 소유자로 `SET LOCAL ROLE` 하도록 생성기를 고치고,
  적용 성공이 ACL 적용의 증거가 되지 못한다는 사실을 digest 자기검증으로 막았다.

  잔여: CI green 확인 → 머지.

- [x] T-VN-H46B — **prod 지오코딩 복구** (2026-08-14 완료)

  08-13에 `.env`만 고치고 api만 재생성해 dagster/daemon 2개가 401 나는 상류 VWorld
  키를 들고 있었다. fail-open이 아니라 첫 요청에서 asset step이 통째로 실패하는
  형태였고, ETL이 08-07 이후 안 돌아서 아직 안 터졌을 뿐이었다.
  `up -d --no-deps --force-recreate` 후 세 컨테이너 전부 `POST /v2/reverse` HTTP 200.

- [ ] T-VN-H46C — **VWorld fallback 사슬 제거** (H46B 재발 통로)

  `docker-compose.yml:201,326,396`과 `scripts/load-env.sh:119-121`의
  `${KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY:-…:-${NEXT_PUBLIC_VWORLD_API_KEY:-…}}`가
  **정확히 401을 받는 값**으로 떨어진다. `.env.example:152`의 낡은 주석도 같은 통로다.
  `geocoding.py:962-979`의 `preflight()`는 존재·길이만 보므로 잘못된 키를 통과시킨다.

- [ ] T-VN-H46D — **daemon 스키마 drift**: `column request.providers does not exist`

  `kor-travel-map-dagster-daemon-latest` 로그에 반복되는 `asyncpg.UndefinedColumnError`
  (feature_operation 계열 쿼리). prod는 `0104`인데 코드가 없는 컬럼을 질의한다.
  이 경로가 실제 자산 실행 경로면 다음 ETL에서 터진다.

- [x] T-VN-H46E — **공개 data.go.kr 키: 현행 유지 판정** (2026-08-14)

  자격증명 1개를 **17개 별칭 / 8개 파일 / 6개 저장소**가 공유한다("4곳"이 아니었다 —
  provider별 이름으로 갈라져 그렇게 보였다). 노출 정황은 없다: `git log --all -S`와
  `git grep` 전 저장소 0건, prod 비밀 파일 전부 `0600`.

  회전하지 않는다. 트리거가 되는 사건이 없고, data.go.kr 분리 발급은 계정 분리를
  뜻하는데 인증 필요 오픈API가 코드 실측 약 236건이라 전건 재활용신청은 비대칭적으로
  크다. 실제 위험은 키가 아니라 **사본 수**다.

  잔여 위생(별건): ~~`~/kor-travel-docker-manager/.env.bak-*` 정리~~ → **완료(2026-08-14)**,
  `python-krex-api`의 `.env.local` gitignore 규칙 추가, ~~`docs/external-apis.md` §2에
  "동일 키를 쓰는 17개 별칭" 표 추가~~ → **완료(2026-08-14, §2.1)**. ⚠️ data.go.kr
  콘솔 실제 상태(재발급이 기존 활용신청 승인을 유지하는지, 계정당 다중 키 가능 여부)는
  **미확인 추정**이다.

  표를 만들며 개수가 갱신됐다 — 로컬 `F:\dev` 전체를 값의 sha8로 다시 묶으니
  data.go.kr 키는 **별칭 18개 / 파일 18개**다(앞의 "17/8/6"은 스캔 범위가 좁았다).
  같이 나온 것 두 가지:

  - **VWorld 키가 별칭 14개 / 파일 15개**로 퍼져 있고, 그 그룹 안에
    `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`와 `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`가
    **들어 있다**. 즉 로컬 `.env`들에서 geo 소비자 키 자리에 VWorld 값이 들어 있고,
    geo는 그것을 `401 E0401`로 거절한다. 2026-08-13 prod 사고와 같은 형상이 개발
    머신에 그대로 남아 있다는 뜻이다(prod의 소비자 키 자리는 복구 후 정상).
    → 저장소가 고칠 수 있는 부분은 PR #979와 docker-manager
    `fix/map-ui-geo-consumer-key`로 끊었다. `.env` 자체는 운영자/개발자 조치다.
  - 일부 `.env`가 **UTF-8 BOM으로 시작**해 첫 변수 이름이 `\ufeffKMA_SERVICE_KEY`처럼
    깨진다. 순진한 파서는 그 줄을 통째로 놓친다.

  `.env.bak-*` 처리(2026-08-14, 사용자 승인 후 실행). **23개**였다 — 처음 "4개",
  다음 "10개"로 두 번 잘못 셌다. 둘 다 `tail`/`stat` 출력이 잘린 것을 그대로 믿은
  탓이다. 전부 폐기된 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY` 값을 품고 있었고,
  오래된 것들은 `KOR_TRAVEL_MAP_UI_SESSION_SECRET`·`UI_ADMIN_PASSWORD_HASH`·
  `KOR_TRAVEL_CONCIERGE_API_KEYS`의 이전 값도 갖고 있었다. 셋은 권한이 `0664`/`0775`로
  **그룹·타인 읽기 가능**했다 — §1이 규정한 600이 아니었고, T-VN-H46E의 "prod 비밀
  파일 전부 0600"은 이 파일들을 포함하지 않은 판정이었다.

  먼저 전부 `600`으로 고치고, 이어서 **21개를 삭제**했다. 남긴 둘은
  `tvn34`(08-12)·`tvn36`(08-13). 삭제 로그(파일명·크기·변수 수·sha16)는 세션 기록에
  남겼다 — 지운 뒤에는 확인할 방법이 없으므로 그것이 유일한 근거다.

  ⚠️ 한 건은 의도와 어긋났다. `\.env.bak-geokey-20260813T222829Z`(08-13 22:28)는 남긴
  `tvn36`(20:19)보다 **나중** 스냅샷인데 KEEP 목록이 이름 기반이라 삭제됐다. 실질
  손실은 없다 — 그 파일이 담은 것은 geo 키 복구 **이전**의 깨진 형상이고, 되돌릴 이유가
  없는 상태다. 다음에 같은 작업을 하면 KEEP은 이름이 아니라 **mtime 상위 N개**로 잡을 것.

  현재 `.env`는 무사하다(600 / 121개 변수 / 8152B). 정리 직후 map 컨테이너 4개 전부
  Up·healthy 확인.

  `python-krex-api`의 `.env.local` 규칙은 **손대지 않았다.** 그 저장소는
  `fix/incident-realtime-sms`에 29개 파일이 스테이지된 진행 중 작업이라 커밋을 끼워
  넣지 않았다. 노출 위험은 없다 — 그 이름의 파일이 지금 없고, git이 정상 동작하는 전
  저장소를 훑어 **무시되지 않는 비밀 후보 파일은 0건**이다(worktree 포인터가 끊겨
  git 자체가 안 도는 체크아웃이 여럿 있는데, 그런 곳은 애초에 커밋이 불가능하다).
  넣을 규칙은 `.env*` + `!.env.example` 한 쌍.

## Lane B 상세 — b1 PinVi 결합·후속

### T-VN-41 — cache-target generation·outbox 전파

> **41C prod enable 경계(2026-08-04 갱신)** — 41C의 "prod consumer enable + live 증명"은
> docker-manager **재pin(#109 — `2b2dee95`) 완료** + Lane A **`T-VN-H42`**(provider 재적재
> 완주·수렴 + H35 prod live 검증 잔여) **완료 후**에만 진행한다. 그 전 격리 스택 작업은
> 병행 무방(파일 충돌은 의도된 핀 2개뿐 — registry write 수·mocked manifest,
> journal 2026-08-04).

- [ ] T-VN-41A — **source generation·restore epoch**

  existing external identity/exact scope를 유지하면서 source generation과 restore epoch를 schema에
  도입하고 restore/backfill 시 단조성·중복 억제를 고정한다.

- [ ] T-VN-41B — **transaction-coupled outbox writer**

  target/link/update 결과와 같은 transaction에서 generation-bearing outbox event를 기록한다.
  critical write path는 relay I/O를 기다리지 않고 commit/rollback 원자성만 보장한다.

- [ ] T-VN-41C — **relay·reconciliation·consumer enable**

  lease/retry/dead-letter/replay가 있는 relay와 DB 대조 reconciliation을 추가한다. backfill checksum
  뒤 critical path 밖에서 PinVi 소비를 enable하고 누락·중복·restore epoch 전환을 live로 증명한다.
  - [x] source PUT/DELETE·refresh create를 exact `cache-target:command`로 분리하고 기존 consumer umbrella를
    clean cut 제거한다. command→consumer/snapshot/recovery와 consumer exact scope→command 양방향 `403` 회귀,
    exact 4-role binding과 consumer ID 단일 canonical system owner 검증, public API key digest 분리,
    17 operation의 machine-readable/runtime scope와 wrong-role zero-call 계약, service OpenAPI 재export를
    완료한다.
  - [ ] PinVi command writer가 CAS source GET과 refresh `Location` polling에서 consumer credential로
    전환하도록 구현하고 새 service OpenAPI SHA를 compatible pair contract generation 7에 재핀한다.
  - [x] 일반 snapshot first page를 route transaction으로 durable commit하고 실제 만료 시각을 노출한다.
  - [x] source-material watermark reuse와 75분 server handoff/1시간 client receipt gate를 구현한다.
  - [x] stream share barrier와 snapshot 내부 exact material watermark로 lock-wait stale MVCC 누락을 막는다.
  - [x] 모든 outbox writer transaction을 stream → head/target/link 잠금 순서로 직렬화해 system별 relay
    cursor를 해당 stream의 commit-safe contiguous prefix로 만든다.
  - [x] DB trigger가 stream lock 뒤 relay sequence를 배정해 raw/future writer에도 같은 순서를 강제한다.
  - [x] barrier 5초 lock timeout/30초 statement timeout과 retryable `503`으로 hung writer를 bound한다.
  - [x] capture/persist 30초 timeout을 별도 retryable `snapshot_build_timeout`으로 구분한다.
  - [x] system별 미만료 generic snapshot을 2개로 제한하고 동적 `429 + Retry-After` admission을 구현한다.
  - [x] 단일 snapshot 100,000 item ceiling과 초과 `413` fail-close로 process memory를 bound한다.
  - [x] 만료·미참조 snapshot의 reader-safe foreground bounded GC를 구현한다.
  - [x] 전역 mutex·system round-robin·batch commit·시간/statement/no-progress 예산을 가진 hourly
    background GC와 exact 종료 backlog/total/unexpired/referenced metric을 구현한다.
  - [x] acquired GC run별 referenced item/header count를 Map DB에 멱등 영속화하고 직전 적격 baseline
    대비 시간당 증가율·보존 ceiling, 직전 acquired 대비 간격 무관 inventory loss 및 관측 불능을 Dagster metadata와
    warning alert로 노출한다.
  - [ ] n150 격리 DB에서 migration → 수동 GC → schedule ON → 다음 tick 순서로 검증하고,
    GC 처리량이 유입률을 상회하며 remaining backlog가 0인지 증명한다. referenced snapshot 증가율과
    보존 임계치 alert도 함께 확인한다.
  - [ ] Map/PinVi exact head로 n150 isolated live UI recovery와 최종 prod gate를 통과한다.
    PinVi system별 snapshot concurrency 1, `429/503 Retry-After` backoff, `413` non-retry,
    credential별 gateway limit 또는 동등한 외부 rate-limit과 실제 호출 cadence를 증명한다.

- [ ] T-VN-41S — **snapshot materialization streaming·audit compaction 확장 (#922, C enable 비차단)**

  DB-side/bounded streaming Merkle materialization, receipt/material 공유, terminal audit item compaction,
  item/byte admission과 relation bytes/dead-tuple/vacuum metric을 1M+ synthetic/n150 soak로 검증한다.

### T-VN-41F1J — C6c cancel-probe fixture 수명주기 복구

> 2026-08-06 F1D의 `cancel=404`는 Manager/PinVi read·cancel relay 문제가 아니라, 정적
> `KTDM_C6C_CANCEL_PROBE_JOB_ID`에 대응하는 Map import job이 없다는 실측으로 판정했다.
> fixture 생성·소비·종결과 durable 상태는 Map이 소유하고, Manager는 service OpenAPI로
> transaction ID만 전달한다. PinVi에는 기존 `ops:cancel` 외 권한을 주지 않는다(ADR-084).

- [/] **T-VN-41F1D-D1 — 최종 격리 리허설·provenance attestation** *(공동, docs-only)*

  C3가 결선된 새 generation에서 schema head, canonical `409` receipt, finalize와 **데이터
  비의존** 관리자 UI smoke(로그인 포함)를 기록한다. 2026-08-06 n150 rebuild는 committed했고
  Map application `0087_route_area_subtypes`, Map Dagster `29b539ebc72a`, PinVi `20260804_0049`와
  fixture `finalized`/정확한 `409 PIPELINE_CANCELLATION_UNSAFE`를 확인했다.

  **선행**: T-VN-33 merge. 실행 순서는 `T-VN-33 merge → final Map source/image/OpenAPI
  provenance pin·attestation → destructive rebuild-pinned(세 DB 재생성+F1J) → final-schema
  ETL 재적재`까지다. 서비스 전 단계이므로 중간 DB 데이터 복구는 수행하지 않고 final schema에서
  source/ETL을 새로 적재한다. 이전 C3의 pin·smoke는 새 schema acceptance 증거로 재사용하지
  않는다. Manager의 tracked Map source가 병합 SHA와 같고, Map API/UI/Dagster/daemon 및 PinVi
  API/Web/Dagster 일곱 image의 immutable ID·각 schema head·resolved compose/pinset/OpenAPI
  provenance가 candidate에 attest되어야 한다. v5 active generation과 v7 journal만 실행
  authority이며 이전 compatible-pair manifest를 재사용하지 않는다.

- [ ] **T-VN-41F1D-D2 — data-dependent admin/PinVi live E2E** *(공동, docs-only)*

  비어 있는 새 DB에서 **고정 curated/feature ID를 요구하는** admin live UI·PinVi mutating E2E를
  재실행한다. D1이 적재한 final-schema 데이터 위에서 돈다.

  **선행: T-VN-40 완료**(사용자 판단 2026-08-08). T-VN-40B가 admin/public/PinVi consumer를
  `curation_collections/items` 정본만 읽도록 전환하므로, 그 전에 이 suite를 돌리면 증거가
  T-VN-40 머지 즉시 낡는다. 이 acceptance의 비용은 파괴적 rebuild + 전량 ETL 재적재 + 일곱
  image attestation이라 두 번 돌릴 값이 아니다. 반대로 D1은 curation read 경로와 무관하고
  "rebuild-from-scratch가 실제로 되는가"를 보증하므로 join barrier까지 비워두지 않는다.

- [~] **T-VN-41F1D-E — v4 compatible-pair live runner 퇴역·v5/v7 attestation 전환**

  `run-c7-prod-live-e2e.sh`와 `run-admin-feature-live-acceptance.sh`가 요구하는 v4
  `E2E_C7_COMPATIBLE_PAIR_MANIFEST`를 제거한다. root-owned snapshot은 v5
  `PinnedRuntimeManifest.active_generation`, 일곱 immutable image·Map/PinVi revision·세 schema
  head·pinset을 확인하고 v7 journal/host attestation과 함께 발행한다. v4 manifest를 억지 입력해
  통과하는 compatibility 경로는 만들지 않는다. final schema merge/재적재와 독립적으로 unit·script
  contract까지 완료하고, 실제 n150 data-dependent 실행은 위 F1D-D 순서를 따른다.

## Wave 2 상세 — 구조 전환

> 실행 순서는 31A~C(freeze) → 32~38(shadow, 두 lane 병렬) → 40 → 39(cutover 마지막)다.
> ADR-066~075가 목표 스펙 정본이다. 각 migration task는 forward-only 격리 clone에서 검증하고,
> 명시적 downgrade 수용 조건이 없는 한 전진 뒤 rollback하지 않는다.

### T-VN-34 — 직교 상태 모델 전환 (Lane B)

> 정본 계획·상태 진리표·writer ownership·검증 matrix는
> [`reports/t-vn-34-orthogonal-state-plan-2026-08-09.md`](reports/t-vn-34-orthogonal-state-plan-2026-08-09.md),
> 구조 결정은 ADR-090이다. A/B/C는 T-VN-38 parent 위의 stacked draft다. A/B는 단독으로
> 배포·main 병합하지 않고 C final head에서 한 번에 forward-only cutover한다. 서비스 전 단계이므로
> dual-write, shadow/held rollback, old contract 보존은 만들지 않으며 final schema는 ETL로 재적재한다.

- [x] T-VN-34A — **3축 상태 schema·backfill**

  여덟 legal tuple의 typed axis/DB CHECK와 `feature_state_transitions` append-only trigger를
  target contract·actual migration에 고정한다. legacy tuple diagnostics와 one-shot mapping/backfill
  audit, axis context/principal/reason/revision fence, provider/override canonical writer 전환을 소유한다.
  bootstrap owner와 분리된 migrator/API/Dagster runtime role·DSN/preflight까지 함께 전환한다. P0 repair
  `9f16599f`는 provider receipt DB 파생·typed lifecycle override command·provider version materializer와
  실제 runtime `load_bundle` 권한 검증까지 반영했다. 후속 보강은 source head currentness, user-fenced
  provider baseline 보존, Dagster webserver preflight와 target freeze 재동결을 포함한다. `81d04024` 기준
  DB/ACL·contract/runtime 적대 리뷰 2명이 P0/P1 없이 GO를 판정했다. A는 완료됐지만 B/C와 함께만
  final cutover로 배포·병합하는 stack 내부 checkpoint다.

- [x] T-VN-34B — **public projection·partial index cutover**

  명시 열 `public_features` projection과 service 5-state classifier를 3축 정본으로 전환한다.
  route/area subtype-local geometry와 core tuple의 cross-table index 불가를 trigger-owned
  `public_ready` projection flag로 해소한다. 새 subtype attach만 parent `FOR UPDATE`로 current flag를
  산출하고 existing subtype identity는 DB 불변으로 막아 payload UPDATE와 state transition의 역순 lock을
  없앤다. route/area grant는 table UPDATE 없이 mutable business column만 허용하며 identity UPDATE와
  DELETE를 거부한다. core point/category/keyset/text는 exact 3축 partial predicate를, route/area GiST는
  `WHERE public_ready`를 사용한다. `EXPLAIN` gate와 public reader, two-session·direct-flag privilege
  regression을 소유한다. `c54e1807`과 `3a0155e2` 기준 fresh public projection/target freeze 36건,
  runtime API·Dagster LOGIN ACL 3건, artifact/target freeze 18건을 통과했고 DB/동시성·contract/security
  적대 리뷰 2명이 P0/P1 없이 GO를 판정했다. B도 stack 내부 checkpoint다.

- [x] T-VN-34C — **writer/API/UI cutover·legacy status fence**

  admin state command·OpenAPI/generated type·Map/PinVi/admin UI·merge/Dagster/fixture/live runner의
  모든 남은 writer를 cutover한다. admin state HTTP union(`retire` 또는 axis patch)은 strong If-Match,
  `reason_code`, 422/404/409/412/428 semantics와 audit/ETag response를 OpenAPI/UI/E2E로 고정한다. legacy
  deactivate/status default filter는 제거하고 admin axis filter는 AND로 결합한다. `features_detailed`는 leaf view가 아니므로 먼저 public view를 typed
  core+subtype assembly로 재구성하고, non-public reader와 두 security-definer materializer도 같은 typed
  table assembly로 재배선한다. user request retry receipt는 request→receipt→Feature lock order와 request
  역방향 UPDATE/DELETE trigger를 가진 `feature_versions` immutable receipt로 옮겨 exactly-once를 보장한다.
  provider/admin reactivation evidence는 source link/current head를 source→Feature lock order로 고정한다.
  그 뒤에만 current private `features_detailed`와 runtime SELECT grant·closed
  ACL allowlist·startup preflight assertion을 제거한다. 이어 legacy `status`, delete/user-change metadata와
  관련 CHECK/index/trigger/query를 물리 삭제하고 static normal-path gate와 n150 destructive fresh-reload
  live E2E를 통과한다. `data_origin`/`data_version`, `feature_versions`와 materializer bridge는 T-VN-36의
  materialization 입력으로 남기며 T-VN-36D가 제거한다. post-34/pre-36 executable contract와 dedicated
  `0096→C` integration/artifact runner가 legacy catalog zero·ordered public allowlist·typed direct
  dependency·receipt unique/immutability·runtime ACL을 fail-close하고, post-T36 final target contract를
  약화하거나 앞당기지 않는다. Map OpenAPI export 뒤
  clean PinVi worktree에서 C exact Map head를 re-vendor하고 paired SHA/compile/no-legacy gate를 남긴다.
  C만 배포·병합 가능하다.

  Map `fe12e8da` / PinVi `e37eda94` immutable source pair의 n150 fresh `0097` PostGIS·actual
  Dagster runtime ETL·Noble Playwright destructive main/recovery(2/2)·PinVi public probe가 통과했다.
  runner 자동 cleanup 뒤 `BLOCKED.json`, 해당 compose container와 volume이 모두 없음도 확인했다.

  **배포 선행 조건 (2026-08-12 n150 prod 실측)** — T-VN-34는 현행 prod 결선으로는 기동하지
  않는다. 후보 이미지를 올렸더니 api가 **DB에 접속하기도 전에** 거부하고 crashloop에 들어갔다
  (그래서 DB는 무손상이었고 즉시 원상복구했다):

  ```
  ./docker/api-entrypoint.sh: 260: KOR_TRAVEL_MAP_MIGRATOR_PG_DSN: KOR_TRAVEL_MAP_MIGRATOR_PG_DSN is required
  ```

  ADR-090이 단일 `KOR_TRAVEL_MAP_PG_DSN`을 권한 분리된 principal로 쪼갠 결과다. entrypoint는
  `KOR_TRAVEL_MAP_MIGRATOR_PG_DSN`과 `KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN`을 **fallback 없이**
  하드 요구한다 — 한 값으로 둘을 대체하는 경로는 권한 경계를 지우므로 의도적으로 없다.
  DSN을 넣는 것만으로도 부족하고 `docker/postgres-role-bootstrap.sh`의 7롤이 **미리 존재**해야
  한다. n150 map DB는 `kor-travel-geo-postgres`에 geo와 **공유**돼 있어 bootstrap이 공유 서버의
  권한 모델을 바꾸므로, 전용 인스턴스 분리 여부는 Manager 판단 사항이다 —
  docker-manager #171. 이 결선 전까지 tvn34의 live 검증은 격리 clone 스택
  (`scripts/run-admin-feature-clone-live-acceptance.sh`)에서만 가능하다.

### T-VN-35 — kind별 typed subtype 분해 (Lane A) — 배포 잔여

> 코드는 2026-08-06 PR #961(`9efd1f89`)로 **A-D 전부 머지**됐고 완료 상세는
> [`tasks-done.md`](tasks-done.md)에 있다. 남은 것은 prod 배포 하나뿐인데 어느 열린
> task도 소유하고 있지 않아 여기에 명시적으로 둔다(2026-08-07 재대조에서 발견).

- [x] T-VN-35/34/36-deploy — **`0104` prod cutover 완료 (2026-08-13)**

  > **최종 방식(사용자 지시)**: 백업 없는 **in-place 마이그레이션**. 하루 사이에 판단이
  > 두 번 바뀌었으므로 순서대로 남긴다 — ① 처음엔 migrate-in-place 전제 → ② 아래 두
  > 실측으로 "폐기·재생성 + provider 재적재"로 전환 → ③ 최종적으로 사용자가 "어차피
  > 되돌리지 않으므로 측정·리허설 없이 강제로 마이그레이션"으로 확정. 재적재 소요
  > 시간을 재는 비용보다 그냥 밀어붙이는 편이 싸다는 판단이다.

  **실행 결과 (2026-08-13)**

  | 단계 | 결과 |
  |---|---|
  | ADR-090 bootstrap (공유 `kor-travel-geo-postgres`) | exit 0, 7 principal, `kor_travel_map` DB·`public.alembic_version` 소유권 → `ktm_feature_schema_owner`, 비소유 relation 0 |
  | `alembic upgrade head` `0087` → `0104` | **1시간 32분 39초**, feature 1,008,852 손실 0 |
  | 런타임 배포 (api/ui/dagster/daemon) | 4/4 healthy, DB 오류 0 |

  - 마이그레이션은 **독립 컨테이너**로 돌렸다. entrypoint 인라인으로는 완주할 수 없다 —
    `0095` 3축 backfill 하나가 **58분 18초**(전체의 63%)이고 api healthcheck 창은
    `start_period 20s + interval 10s × retries 20` = 약 3.5분이다.
  - 공유 서버 영향 없음: `kor_travel_geo`(33GB) 소유자는 `addr` 그대로다.
  - `0097` fence(`user_request` receipt)와 `0103` replay 대상 모두 prod 0건이라 통과했다.
  - 3축 분포: `active/published/valid` 1,008,848 · `retired/suppressed/valid` 4.
  - **되돌릴 수 없는 지점을 지났다**: bootstrap이 소유권을 넘기면서 기존 런타임 role
    `krtour_map`은 `feature.features`를 읽을 수 없게 됐다(`SELECT = f`). 배포는 선택이
    아니라 필수였다.
  - 배포 중 발견: `dagster`/`daemon`이 `KOR_TRAVEL_MAP_PG_DSN`을 그대로 쓰므로 api와 달리
    entrypoint의 runtime DSN 교체 경로가 없다. `KOR_TRAVEL_MAP_DOCKER_PG_DSN`을
    `ktm_feature_dagster_runtime`으로 바꿔 해결했다. docker-manager #172 브랜치는 이미
    이 문제를 올바르게 풀어둔 형상이다(세 서비스 각자의 runtime principal).

  **후속 처리 (2026-08-13, 같은 날 이어서)**

  - **공개 API 키 재발급 완료** — `ops.public_api_keys`가 0행이라 공개 표면이 401이었다.
    `python-vworld-api/.env`의 `VWORLD_API_KEY`를 등록했다(사용자 지시). 키는 평문 미저장
    (`sha256` + 끝 6자 hint), 발급 경로는 `POST /v1/admin/public-api-keys`뿐인데 그건
    서버가 난수 32자를 **생성**할 뿐 지정 값을 받지 못하므로 직접 INSERT했다.
    검증: `/v1/features` 200(실제 feature 반환) · `/v1/categories` 200 ·
    `/v1/providers` 200 · 키 없음/오류 키 401 유지.
    - `~/.secrets/kor-travel-map-public-api-key`가 401이던 이유가 밝혀졌다 — 그건
      map 자체 공개 키가 아니라 **map→geo 소비자 키**다(`kor_travel_geo`의 active 행과
      일치). `docs/dev-environment.md` §10.7 ①의 서술과 같다.
    - **마찰로 남긴다**: 등록한 값은 4곳(python-vworld-api/.env, map .env ×2, geo
      컨테이너)에서 공유되는 업스트림 자격증명이라 하나가 새면 둘 다 샌다. 설계 의도는
      "UI에서 생성한 전용 키를 DB에 저장"이므로, admin BFF로 난수 전용 키를 발급하고 이
      행을 revoke하는 회전 경로가 열려 있다.
    - **T-VN-40 n150 배포 전 차단 조건**: admin BFF 정식 발급 경로로 Map 전용 public
      key를 생성·안전 보관하고, VWorld 값으로 직접 등록한 임시 행을 revoke한다. 키 원문은
      저장소·로그·채팅에 남기지 않으며 새 key 200 / VWorld key 401 / revoke key 401을
      live probe로 확인한 뒤에만 candidate 배포 fence를 연다.
  - **prod 지오코딩이 죽어 있었다 — 고쳤다.** `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`에
    VWorld 키가 결선돼 있어 geo가 401로 거부했다(실측: VWorld 키 401 / `~/.secrets` 키
    200). 즉 map의 정/역지오코딩 호출이 전부 실패하고 있었다. 올바른 값으로 교체 후
    api 재생성, healthy·DB 오류 0 확인. `docs/dev-environment.md` §10.7 ①이 경고하던
    혼동이 prod에 실제로 박혀 있었다.
  - **H43 기준선 확보** — 백업 없이 마이그레이션했으므로 `0104` 복구점이 없었다.
    §9·§10 규약("migration 동반 릴리스 뒤")대로 만들었다:
    `~/backups/kor-travel-map/2026-08-13-h43-postdeploy-0104.dump`, **586MB / 78초**,
    sha256 `8a9bae95…`, `pg_restore -l` 목차 1197항목, `public_api_keys` TOC 확인.
    manifest: head `0104_tvn36_final_fence` · features 1,008,852 ·
    source_records 1,009,157 · source_links 1,008,852 · public_api_keys 1.
    - **§9 규약 정정 필요**: manifest 필수 항목 `weather_values`는 이제
      `feature.weather_values`가 아니라 **`feature.feature_weather_values`**다
      (T-VN-35 typed subtype 분해에서 개명). 규약대로 조회하면 relation 부재로 실패한다.
      이번 manifest는 새 이름으로 기록했다(값 0, `current_weather_summary`도 0).
    - 백업 **스코프 자체는 이미 올발랐다** — `ops.public_api_keys`는 2026-08-05 소실
      이후 manifest 필수 + TOC 확인 항목이다. 공백은 스코프가 아니라 "최신 기준선이
      `0083` 시절이었다"는 것이었다.

  **잔여**
  - prod는 아직 **공유** PostgreSQL(`kor-travel-geo-postgres:5432`)에 있다. docker-manager
    #172는 전용 인스턴스(`:12703`)를 전제하므로 그 배포 전에 **데이터 이동이 선행**돼야
    한다 — 안 그러면 빈 DB를 보게 된다. 순서는 #172 코멘트에 적었다.
  - 배포 스냅샷(`/home/digitie/kor-travel-docker-manager`)은 git이 아니다. 거기 넣은 임시
    결선은 다음 manager 배포에서 저장소 형상으로 대체된다(그쪽이 더 옳다).

  ---

  아래는 방식 ②(폐기·재생성)를 뒷받침했던 실측이다. in-place로 되돌아갔어도 **`0095`가
  왜 58분인지**와 **base 계보가 왜 비어 있는지**는 그대로 유효하므로 남긴다.
  >
  > **① 마이그레이션 체인에 base lineage backfill이 없다.**
  > `INSERT INTO feature.feature_base_field_values`는 `0099`/`0102`의 **procedure
  > 정의 안**에만 있고 기존 행을 채우는 backfill은 체인 어디에도 없다. 즉
  > `0087→0104`를 완주해도 `feature.features` 100만 행은 3축 컬럼만 얻고
  > `feature_base_field_values`와 `ops.feature_overrides`는 **비어 있다** —
  > T-VN-36의 존재 이유인 base ↔ override ↔ effective 계보가 기존 데이터에는
  > 없는 채로 시작하고, 각 feature가 다음 provider 적재를 거쳐야 채워진다.
  >
  > **② 실측 비교(n150, prod와 같은 호스트)**
  >
  > | 경로 | 소요 | 결과 |
  > |---|---|---|
  > | migrate-in-place `0087→0104` (1,008,852행) | `0095` 3축 backfill **하나가 50분 초과**(중단) | 3축 컬럼만, base 계보 없음 |
  > | fresh 빈 DB + `alembic upgrade head` | bootstrap 5s + migration **40s** | `0104` 완비, registry 64행 |
  >
  > 50분+ 구간은 트리거도 서브쿼리도 없는 단순 full-table UPDATE인데
  > `iowait 61%` / 디스크 `%util 87%`로 I/O에 막혔다. MVCC 행 재작성 + 인덱스
  > 전량 갱신이 이 하드웨어의 한계에 닿는다. api healthcheck 창은
  > `start_period 20s + interval 10s × retries 20` = **약 3.5분**이므로,
  > migrate-in-place는 entrypoint 인라인 실행으로는 애초에 성립하지 않는다.

  **prod 실데이터(1,008,852행) 복제본에서 잰 값** — clone은 이후 폐기했으므로 여기가
  유일한 기록이다:
  - ADR-090 bootstrap **2초**, 7 principal 생성, `public.alembic_version` 소유권
    `kor_travel_map` → `ktm_feature_schema_owner`, 비소유 relation 0.
    T-VN-34에서 고친 두 P0(identity 시퀀스 sweep 제외 / `alembic_version` 이전)가
    100만 행 규모에서도 성립한다. fresh DB에서는 무증상이던 축이다.
  - `0097` fence 대상(`feature_versions.origin='user_request'`) **0건**
  - `0103` replay 대상(`features.data_origin='user_request'`) **0건**
  - `ops.public_api_keys` **0행** ← 폐기·재생성 시 재발급이 필요한지 확인할 것.
    2026-08-05 공개 표면 전체 401 사건의 축이다.

  **선행 실측(미완)**: provider 재적재로 1,008,852 feature를 다시 채우는 데
  걸리는 시간. rate limit 포함 실측 전에는 cutover 창을 정할 수 없다.

  **ADR-090 게이트 실측(2026-08-13)** — `scripts/rehearse-adr090-deploy-path.sh`.
  clone-live 인수는 `--entrypoint python -m uvicorn` + 단일 DSN이라 이 축을 영원히
  건드리지 않으므로 별도 리허설이 유일한 증거다. 네 case 전부 fail-close 확인:
  split DSN 누락(exit 2) / runtime DSN 단독(exit 2) / EXPECTED_HEAD 불일치(exit 1) /
  set-but-empty(exit 1).
  첫 실행에서는 네 case 모두 ops profile 검사(ADR-066)에서 **먼저** 죽어 재려던
  게이트에 도달조차 못 했다 — exit code만 봤으면 green으로 오인했을 자리다.

  > 2026-08-13 갱신. 원래 이 항목은 `0087_route_area_subtypes`를 지시했는데, 그 사이
  > T-VN-34(`0098_admin_scope_indexes`)와 T-VN-36(`0104_tvn36_final_fence`)이 main에
  > 들어가 `0087`은 main에서 도달 불가능한 중간 revision이 됐다. 지시대로
  > `0087`을 박으면 api가 DB를 건드리기 전에 exit 1이고 dagster/daemon도 뜨지
  > 않는다 — ADR-090 배포에서 실제로 겪은 crash-loop과 같은 형태다
  > (docs/tasks.md 위 §, journal 2026-08-06 (1)). 그래서 세 배포를 하나로 접는다.

  절차:
  1. 기준점 dump — 폐기 전 `T-VN-H43` runbook §9 규약(manifest 필드 포함)으로
     현행 prod를 받아둔다. 폐기·재생성이므로 이것이 유일한 되돌림 수단이다.
  2. orchestrator `.env`의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
     **`0104_tvn36_final_fence`**로 **선행** 갱신.
  3. DB 폐기·재생성 → ADR-090 bootstrap(7 principal) → `alembic upgrade head`.
     빈 DB 기준 실측은 bootstrap 5s + migration 40s다.
  4. api → dagster/daemon 순으로 재빌드·배포.
  5. provider 재적재로 Feature를 다시 채운다. **이 구간이 cutover 창을 지배한다** —
     선행 실측이 필요하다(위 참조).

  prod에 적용된 head는 **`0087_route_area_subtypes`**다 — 2026-08-13 n150 실측
  (`kor-travel-geo-postgres` / `kor_travel_map`, feature 1,008,852행). 이 문서가
  오래 `0083`이라고 적어둔 것은 사실과 다르다(마지막 배포 journal 2026-08-05
  (7)/(10) 이후 누군가 0087까지 올렸고 기록이 따라오지 않았다). n150 파기형
  rebuild에서 확인된 head는 `T-VN-41F1D-C3`의 격리 generation이며 prod 배포가 아니다.

  `0097` fence(`feature.feature_versions`에 `origin='user_request'`가 있으면
  거부)는 폐기·재생성 경로에서는 애초에 대상이 없다. migrate 경로를 다시 검토할
  경우를 위해 기록해두면, prod 실측에서도 0건이라 걸리지 않았다.

  선행 조건(ADR-090):
  - `KOR_TRAVEL_MAP_MIGRATOR_PG_DSN` / `KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN` 분리
    주입 — 미프로비저닝 상태로 배포하면 api가 `... is required`로 crash-loop한다.
  - `docker/postgres-role-bootstrap.sh`가 7 principal과 `public.alembic_version`
    소유권까지 세운 뒤여야 한다.
  - compose로 띄운다면 ops principal 3종과 `OPS_PRINCIPAL_REQUIRED`는 root
    `.env`/host env에 둔다(`.env.example` 참조 — package env는 compose가 덮는다).

  배포 직전 write-fence 기준점 dump는 `T-VN-H43` runbook §9 관례를 따른다.
  실데이터를 전용 PostgreSQL로 옮기는 경로(docker-manager #171)는 dump/restore이며
  파기형 재생성이 아니다.

### T-VN-36 — field override 단일화 (Lane B, A–D 단일 PR)

> 정본 설계는
> [`reports/t-vn-36-field-override-plan-2026-08-10.md`](reports/t-vn-36-field-override-plan-2026-08-10.md)와
> ADR-091이다. A–D는 `feat/tvn36-abcd-field-overrides` 하나의 forward-only PR/release로만
> 병합한다. intermediate migration head나 old binary를 배포하지 않는다.

- [x] T-VN-36A — **override schema·whole-row freeze backfill**

  field별 value/provenance/revision/tombstone을 저장하는 정본을 만들고 기존 whole-row freeze를
  동일 effective projection으로 backfill한다.

- [x] T-VN-36B — **provider/admin writer cutover**

  provider upsert와 admin patch가 field override를 같은 transaction에서 갱신하도록 전환하고
  concurrency/merge precedence를 DB 제약과 회귀 테스트로 고정한다.

- [x] T-VN-36C — **effective projection 단일화·consumer cutover**

  read model을 한 effective projection으로 통일하고 repository별 중복 `CASE` write/read 분기를
  비활성화한다. typed admin override API/UI·OpenAPI·PinVi admin-detail consumer를 exact Map head로
  전환한다.

- [x] T-VN-36D — **destructive freeze fence·final live**

  base/effective checksum과 runtime ACL을 검증한 뒤에만 whole-row freeze, `data_origin`,
  `data_version`, `feature_versions`와 dependent request receipt/trigger/index를 물리 삭제한다.
  post-36/pre-T39 executable contract, fresh migration, PinVi pair, n150 destructive main/recovery와
  cleanup이 통과해야 한다.

  `0104_tvn36_final_fence`와 final contract/browser direct-state rewrite를 구현했다. n150의
  immutable fresh run은 Map `f7e2e04e` / PinVi `6ab4eaf` pair에서 fresh migration·Dagster
  ETL(Feature/source-link 3건, weather/price 1건씩)·Noble Playwright(2/2)·PinVi public probe와
  자동 cleanup을 통과했다. 앞선 실패 run은 같은 격리 snapshot에서 `recover`로 정리해
  `BLOCKED.json`/container/volume 잔재가 없음을 확인했다.

  **2026-08-13 재배치**: `feat/tvn34-state-model` `693c5355` 위로 T-VN-36 고유 24 commit을
  다시 얹었다(옛 tvn34 67 commit 폐기). alembic 단일 head는 `0104_tvn36_final_fence`이고
  migration graph·OpenAPI·contract SHA는 재생성했다. 같은 자리에서 T-VN-34가 세운 결함
  부류를 전수로 걸어 notice reconcile SQL의 죽은 projection, override procedure arity
  미추종, 죽은 오류 매핑, ledger operation 이름 붕괴, 정적 차단선의 세대 누락,
  frontend type-check/lint red를 닫았다(journal 2026-08-13).

  **2026-08-13 머지** — PR #973(`c76ceb7a`). 머지 전 적대 리뷰 2건이 실 DB에서 재현한
  P1 6건을 전부 닫았다. 셋은 원인이 하나였다 — sha는 predecessor **파일**만 잠그고
  anchor는 아무도 검사하지 않는다:
  - `0102`의 revoke 집계 수정이 anchor 불일치(f-string 소스 표기 `'{{}}'` vs 렌더
    결과 `'{}'`)로 **한 번도 배포된 적이 없었다**.
  - `0104`가 hardening 이전인 `0100` 원문에서 author/revoke를 재생성해 0101/0102를
    되감았다(provider patch는 재생성하지 않아 두 writer가 다른 세대가 됨).
  - `0102`의 notice `first_probe` 보존이 effective 테이블을 읽어 운영자 override를
    provider base ledger로 세탁했다.

  `0102`에 fail-closed 치환을 넣자 즉시 `0104`의 geometry anchor 불일치를 잡아냈다.
  `tests/integration/test_tvn36_final_fence_procedures.py`가 셋을 관측 가능한 동작으로
  고정하고, 변이 검증에서 3건 모두 red를 확인했다.

  나머지 3건: compose가 package env의 ops principal을 빈 문자열로 덮어
  `OPS_PRINCIPAL_REQUIRED=true`를 false로 내려앉히던 문제, 도달 불가능한 `0087`을
  지시하던 배포 task, 폐기된 커밋을 가리켜 live 게이트가 다른 트리를 자기 정합적으로
  인증하던 PinVi receipt. 각각 재발 게이트를 함께 넣었다.

  live clone 인수 하네스는 `0104` typed state 모델로 재작성했다(소유권 key는 name,
  전이는 개수가 아니라 사슬 구조로 검사, 개수는 spec의 create body에서 유도).
  content digest에 `feature_state_transitions` identity sequence 제외를 추가했다 —
  없으면 완료 판정이 항상 실패한다(T-VN-34부터 있던 문제).

  **잔여**: ① n150 live 실행(아래 신규 항목). ② `0027` re-key 정리의
  `data_origin='user_request'` 제외 가드는 head 동등 술어가 없어 재현하지 않기로 했다
  (field override 세대에는 행 단위 소유권이 없다).

- [x] T-VN-36-live — **격리 clone에서 live 인수 완주 (2026-08-13)**

  clone-live 하네스는 clone DB가 **이미 candidate head**여야 동작한다 — 러너는
  migration을 하지 않고 head 불일치면 첫 스냅샷에서 죽는다.

  기존 `ktm-tvn38-db`는 전량 `user_request` fixture(feature 30 / version 64)라
  `0097` fence가 정당하게 막아 재사용할 수 없다. prod 덤프를 옮겨 migrate하는
  경로도 시도했다가 **중단했다** — 위 배포 항목의 실측대로 `0095` backfill 하나가
  50분을 넘겼고, 그렇게 얻는 것이 "빈 base 계보를 가진 3축 컬럼"이었다.

  그래서 clone도 **fresh 경로**로 만든다: `ktm-tvn36-db`(host `18736`)를 빈 DB로
  두고 ADR-090 bootstrap → `alembic upgrade head`(합 45s) → `baseline` → `run`.
  인수 spec은 자기 fixture를 스스로 만들고 정리하므로 대량 실데이터가 전제가
  아니다(소유권 key는 name, feature id는 서버가 정한다).

  세대 전환이므로 기존 checkpoint(`0095` 세대, snapshot version 2)는
  `archive-0104-*`로 보존한다 — 앞선 `archive-0094-*` / `archive-0095-baseline-*`와
  같은 관례이고, `$STATE_ROOT`가 clone 간 공유 고정 경로라 남겨두면 `baseline`이
  죽으므로 위생이 아니라 필수 단계다.

  **실행 중 확인한 하네스 사실 (2026-08-13)**

  - **`run`에는 `baseline`이 아니라 `checkpoint` 모드로 cut한 checkpoint가 필요하다.**
    `baseline`은 dump 복원 인증(`verify_dump_restore`)을 건너뛰는데, `run`은 신뢰
    dump를 복원한 뒤 startup snapshot이 checkpoint baseline과 **정확히** 일치할 것을
    요구한다(`--allow-owned-drift` 없음). 그래서 baseline-only(version 5) checkpoint로
    `run`하면 "현재 clone DB가 trusted checkpoint와 다릅니다"로 죽는다. 그리고
    `checkpoint` 모드는 version 5를 재사용하지 않으므로("full restore certification
    cannot reuse a baseline-only checkpoint") **아카이브 후 재cut**이 유일한 경로다.
    실행 순서는 `checkpoint` → `run`이고 `baseline`은 그 앞 단계가 아니다.
  - 러너는 GitHub 아카이브에서 자체 스냅샷을 설치한다(`$INSTALL_BASE/$SOURCE_COMMIT`,
    root-owned/read-only 검증 포함). 따라서 러너를 고쳤으면 **푸시한 뒤 그 커밋을**
    `E2E_SOURCE_COMMIT`으로 줘야 한다 — 로컬 편집은 반영되지 않는다.
  **완주 결과 (2026-08-13, source `cd5b7470`)**

  `phase: passed` / `status: complete`. Playwright main 2/2 + recovery 2/2.
  `startup_migration_unchanged: true`, `production_compose_project_excluded: true`,
  `foreign_key_references: 0`, `api_owned_active_features: 0`(retire 완료).

  API-owned 감사 수치가 유도값과 정확히 일치했다 — features 1 / field_overrides 7 /
  state_transitions 3 / domain_commands 3. schema digest
  `741b355a…`, content digest는 시작 기준과 일치(완료 판정).

  여기까지 오면서 하네스·배포 경로에서 아홉 건을 꺼냈고 모두 정적 게이트가 green인
  채 숨어 있던 것들이다. 그중 넷은 러너 자체의 결함이고(LOGIN fence / baseline↔run
  선행 관계 / retire override 감사 누락 / schema digest 왕복 불가), 특히 마지막 건은
  **ADR-090 스키마에서 복원 인증이 구조적으로 통과 불가**였다.

  - **fixture 자체가 결함이면 in-band 복구 경로가 없다.** `recover`는 fixture를
    BLOCKED가 기록한 `source_commit`에 고정하는데(`FIXTURE_HELPER=
    "$INSTALL_BASE/$blocked_source/..."`), 결함이 바로 그 버전에 있으면 recover도
    같은 지점에서 죽는다. `abort`는 phase가
    `direct-cleanup-running`/`test-failed-restored`/`failed-resource-finalizing`일
    때만 허용하므로 hard-purge 중 죽은 상태는 받지 못한다. 스냅샷은
    `validate_snapshot`이 지키는 신뢰 경계라 손대서도 안 된다.
    남는 것은 clone DB 재구축(일회용이므로 45s)뿐이고, BLOCKED와 checkpoint는
    지우지 말고 `archive-0104-blocked-*`로 보존한다.
    → 하네스 개선 여지: recover가 **더 새 fixture**를 쓸 수 있게 하거나
    (`--fixture-source-commit`), abort가 hard-purge 단계를 받아들이게 하는 것.

### T-VN-37D — notice empty range 표현 (보류)

> 계보 key 물화·인덱스 probe(`T-VN-37`, PR #968)는 완료 이력으로
> [`tasks-done.md`](tasks-done.md)에 옮겼다. 이 항목은 별도 제품 결정이 필요한 후속이다.

- [ ] T-VN-37D — **empty range 표현 (보류)**

  provider가 미래 시행 공지를 철회하면 `end < start`가 실재한다(실측
  `start=2026-07-13/end=2026-06-02`). 결함이 아니라 "발효 전에 철회됨"이고, 35B가
  CHECK를 두지 않은 이유다. 이를 `tstzrange` empty로 **정확히 표현**하는 것은
  여전히 가치가 있으나, 위 성능 문제와 무관하고 read 술어 변경(=제품 결정)이
  선행돼야 하므로 분리한다. notice_type별 "미래 발효를 보일 것인가" 결정이 먼저다.

### T-VN-40 — curation write model 단일화 (Lane B)

- [ ] T-VN-40A — **legacy writer inventory·write fence**

  `curated_features` overlay를 쓰는 route/job/trigger/repository를 전수 고정하고 신규 legacy write를
  차단한다. canonical curation과 effective projection checksum을 만든다.

- [ ] T-VN-40B — **candidate lifecycle 분리·consumer cutover**

  자동 후보를 `theme_feature_candidates` lifecycle로 분리하고 admin/public/PinVi consumer가
  `curation_collections/items` 정본만 읽도록 전환한다.

- [ ] T-VN-40C — **legacy surface fence·removal manifest**

  checksum과 consumer cutover 뒤 overlay 신규 write와 normal routing을 차단한다. exact removal
  manifest로 legacy repository/trigger/table/API/ACL을 같은 forward-only release에서 물리 삭제하고
  T-VN-39에 catalog-zero receipt를 넘긴다. held component·old binary rollback·신규 호환 shim은
  만들지 않으며 recovery는 fresh clone/reload만 허용한다.

- [ ] T-VN-39 — **KTM·PinVi write-fence cutover**

  consumer-first 배포, write fence와 순차 전환을 수행한다. **T-VN-33C의 legacy
  column/index/route/repository/trigger/table은 서비스 전 단계 원칙에 따라 같은 final-schema
  migration에서 이미 물리 삭제한다.** 따라서 이 task는 T-VN-33 보존·rollback·removal을
  소유하지 않는다. 이후 task가 만든 held component만 그 task의 manifest와 함께 판단하며,
  intermediate data는 backup/restore가 아니라 최종 schema ETL로 재생성한다.

## T-101 — Materialized View 도입 검토 (보류)

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
