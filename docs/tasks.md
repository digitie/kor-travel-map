# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스 (2026-08-16 T-VN-40 PR #974 머지 후 재대조)

완료한 `T-VN-32`·`T-VN-33`·`T-VN-37`·`T-VN-38`과 선행 운영 task는
[`tasks-done.md`](tasks-done.md)로 이관했다. 아래에는 아직 닫히지 않은 실행 단위만 둔다.

**Lane A (Claude Code)**와 **Lane B (codex)**는 서로 병렬 실행한다. 각 lane 내부는 아래 순서를
지키며, 같은 migration head·OpenAPI 정본·같은 cross-repo pair를 만지는 시점만 공통 규율의
barrier로 직렬화한다.

- **Lane A — cross-repo 계약·운영·데이터 품질**
  - [~] `T-VN-H25B` → [ ] `T-VN-H34`(공식 curation 미연결 membership 잔여 AC)
  - [~] `T-VN-H43` → [~] `T-VN-H44`(백업 정기화·복원 드릴 재개 조건)
  - [ ] `T-VN-H45-후속`(다건 provider fetcher·quota 관찰 확장)
  - [ ] `T-VN-H46C`(VWorld fallback 사슬 제거) ∥ [ ] `T-VN-H46D`(daemon 스키마 drift)
- **Lane B — frontend hardening·PinVi 소비 API**
  - [ ] `T-VN-41A` → [ ] `T-VN-41B` → [ ] `T-VN-41C`(generation/outbox)
  - [~] `T-VN-41F1D-D` → [ ] `T-VN-41F1D-D2`(격리 리허설·data-dependent live UI E2E)
  - [~] `T-VN-41F1D-E`(v5/v7 attestation 전환) ∥ [ ] `T-VN-41S`
- **Wave 2 barrier 이후**
  - Lane A: [ ] `T-VN-37D`(notice empty range 표현 — 제품 결정 대기)
  - 32~38 join barrier 뒤 Lane B: [~] `T-VN-40A` → [~] `T-VN-40B` →
    [~] `T-VN-40C`
    - A/B/C는 logical phase이며 **하나의 forward-only implementation PR/release**로만 구현·병합한다.
      phase별 writer/migration/consumer PR 또는 중간 배포는 금지한다.
    - T-VN-36 PR #973이 `c76ceb7a`로 `main`에 병합돼 join barrier가 해소됐고,
      2026-08-13 사용자가 ADR-092와 40A/B/C 단일 PR 구현을 승인했다. Map 구현 PR
      [#974](https://github.com/digitie/kor-travel-map/pull/974)는 `170ddf57`로 병합됐고,
      PinVi [#445](https://github.com/digitie/pinvi/pull/445) 및 Docker Manager
      [#174](https://github.com/digitie/kor-travel-docker-manager/pull/174)도 병합됐다. 다만
      n150 canonical import/backfill 실운영 인수·연동 receipt complete·물리 삭제는 아직
      실행하지 않았으므로 A/B/C는 release 관점에서 부분 완료다. 설계·구현 정본은
      [`t-vn-40-curation-write-model-plan-2026-08-11.md`](reports/t-vn-40-curation-write-model-plan-2026-08-11.md)다.
    - PR #978 최신 baseline+bridge를 T-VN-40 branch에 재배치했다. active chain은
      `0200_schema_baseline→0104_tvn36_final_fence(bridge)→0202…0220` 단일 head이며,
      과거 `0001~0104` 파일은 read-only legacy 증거다. n150 현행 `0104` DB는 bridge가
      그대로 인식하므로 stamp나 baseline 재실행 없이 `0202…0220`만 forward upgrade한다.
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

- [~] **T-VN-41F1D-D1 — 최종 격리 리허설·provenance attestation** *(공동, docs-only)*

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

> Map 구현 PR [#974](https://github.com/digitie/kor-travel-map/pull/974)는
> `170ddf57`로 병합됐고 CI 8개가 모두 녹색이다. 연동 소비자 PinVi
> [#445](https://github.com/digitie/pinvi/pull/445)와 Docker Manager
> [#174](https://github.com/digitie/kor-travel-docker-manager/pull/174)도 병합됐다. 그러나
> receipt는 `pending`이며 n150 canonical import/backfill 실운영 인수와 그 증거에 따른
> final legacy 물리 삭제가 남아 있다. 따라서 아래 A/B/C는 구현은 병합됐지만 release는 아직
> 완료되지 않은 `[~]` 상태다.

- [~] T-VN-40A — **legacy writer inventory·write fence**

  `curated_features` overlay를 쓰는 route/job/trigger/repository를 전수 고정하고 신규 legacy write를
  차단한다. canonical curation과 effective projection checksum을 만든다.

- [~] T-VN-40B — **candidate lifecycle 분리·consumer cutover**

  자동 후보를 `theme_feature_candidates` lifecycle로 분리하고 admin/public/PinVi consumer가
  `curation_collections/items` 정본만 읽도록 전환한다.

- [~] T-VN-40C — **legacy surface fence·removal manifest**

  checksum과 consumer cutover 뒤 overlay 신규 write와 normal routing을 차단한다. exact removal
  manifest로 legacy repository/trigger/table/API/ACL을 같은 forward-only release에서 물리 삭제하고
  T-VN-39에 catalog-zero receipt를 넘긴다. held component·old binary rollback·신규 호환 shim은
  만들지 않으며 recovery는 fresh clone/reload만 허용한다.

  Docker Manager PR #174가 PinVi raw snapshot/mapping pair→Map digest pair의 C6c 결선을
  구현해 병합됐다. n150 canonical import/backfill live receipt를 남기기 전에는 legacy surface
  물리 삭제나 T-VN-40 receipt complete를 수행하지 않는다.

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
