# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스 (2026-08-18 전면 재대조)

완료한 `T-VN-32`·`T-VN-33`·`T-VN-37`·`T-VN-38`과 선행 운영 task는
[`tasks-done.md`](tasks-done.md)로 이관했다. 아래에는 아직 닫히지 않은 실행 단위만 둔다.

**Lane A (Claude Code)**와 **Lane B (codex)**는 서로 병렬 실행한다. 각 lane 내부는 아래 순서를
지키며, 같은 migration head·OpenAPI 정본·같은 cross-repo pair를 만지는 시점만 공통 규율의
barrier로 직렬화한다.

- **Lane A — cross-repo 계약·운영·데이터 품질**
  - [~] `T-VN-H34`(공식 curation 미연결 membership 잔여 AC — `T-VN-M01`~`M03` 선행 필요)
  - [~] `T-VN-H43` → [~] `T-VN-H44`(백업 정기화·복원 드릴 재개 조건)
  - [~] `T-VN-H45-후속`(①~④ 완료 / ⑤ alembic 1.19 적응 잔여)
  - [~] `T-VN-H46F`(admin UI geo proxy 구현·로컬 검증, 적대 리뷰/CI 대기) ∥ [ ] `T-VN-H46G`(buildx image commit provenance label)
  - [~] `T-VN-H49`(Map baseline·절차 완료 / docker-manager #177의 외부 인스턴스 주기화 잔여)
- **Lane B — frontend hardening·PinVi 소비 API**
  - [~] `T-VN-41A` → [~] `T-VN-41B` → [~] `T-VN-41C`(generation/outbox — 상세 AC 일부 완료, #975 rebase·regression 수정·새 exact-pair CI/E2E 재검증 중)
  - [~] `T-VN-41F1D-D1` → [ ] `T-VN-41F1D-D2`(격리 리허설·data-dependent live UI E2E; #967 closed)
  - [~] `T-VN-41F1D-E`(v5/v7 attestation 전환) ∥ [~] `T-VN-41S`(#922 1차 구현·리뷰 GO,
    `0225+` migration/compactor·n150 1M 검증 잔여)
- **Lane M — 수동 Feature 생성 (2026-08-18 결정, T-VN-40 인수 뒤)**
  - [ ] `T-VN-M00`(설계 초안 2차·적대 검증) → [ ] `T-VN-M01`(admin Feature 생성 API — **ADR 필요**) → [ ] `T-VN-M02`(origin 보존·불변)
  - [ ] `T-VN-M03`(curated 동시 생성 — T-VN-40 인수 뒤) ∥ [ ] `T-VN-M04`(PinVi 요청 큐 — cross-repo)
  - [ ] `T-VN-M05`(provider 발행 시 중복 판정 — 자동 병합 금지)
- **Lane C — 사문화 정리·미구현 dataset (다른 lane과 무관, 아무 때나)**
  - [~] `T-VN-C02`(arm64 — registry 자격증명 필요, 정적 점검만 완료) ∥ [~] `T-VN-C03`(표 drift 완료 / dataset 5종은 제품 결정)
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
  - ⚠️ **T-VN-40 인수 실태 재조사(2026-08-18, 조사 1 + 적대 검증 2)** — "인수만 남았다"가
    아니다. 아래 `T-VN-40 인수 — 실태` 절 참조. 사전 구현/병합(40A fence·identity mapping·40C
    manifest 작성) → prod migration·enable → import/backfill → live/receipt → 물리 삭제 실행 순이다.
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

> **T-VN-H25B 완료 이력** — CSV 역반영 5건과 매칭 재실행은 2026-08-18에 종결했고
> [`tasks-done.md`](tasks-done.md)에 이관했다. 아래는 열린 `T-VN-H34`의 판단 근거만 보존한다.

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
  | 주소 축 | **충족(2026-08-18)** — 시군구 축 신설. 아래 ①. | — |
  | provider provenance 조인 | **불가로 종결(2026-08-18)** — 데이터 부재가 아니라 **축이 다르다**. 아래 ②. | — |

  #### ① 주소 축 — 시군구 단위 대조 신설 (2026-08-18)

  **이 항목의 전제가 낡아 있었다.** "`address_hint`가 비어 있으므로 `metadata_json.region`을
  쓴다"고 적혀 있는데, 실측하니 **105건에 `address_hint`가 채워져 있고** 시도가 아니라
  시군구·읍면동까지 있다.

  ```
  간절곶등대   울산광역시 울주군 서생면 대송리
  독도등대     경상북도 울릉군 울릉읍 독도리
  마라도등대   제주특별자치도 서귀포시 대정읍 가파리
  ```

  그리고 그게 **매칭이 가장 나빴던 등대 캠페인**이다 — 103건 중 89건의 최상위 후보가
  상호에 `등대`가 든 가게였다. 시도 축만으로는 같은 시도의 가게를 못 걸러낸다.
  feature 쪽은 이미 `address.sigungu_name`을 갖고 있었다 — **양쪽 신호가 다 있는데
  축만 없었다.**

  - 추출: `address_hint` 105/105 성공(보류 0).
  - ⚠️ **단순 `==` 비교는 맞는 링크를 죽인다.** `경상남도 창원시 진해구 장천동`에서
    hint는 `창원시`인데 feature는 `창원시 진해구`다. 일반구를 둔 시(창원·수원·성남·
    고양·용인·청주·천안·전주·포항·안산·안양)가 전부 해당한다. 한쪽이 다른 쪽의
    **접두(공백 경계)**면 같은 곳으로 본다. 이 축은 반증으로 쓰이므로 오판이 그대로
    링크를 죽인다 — 이 관용이 없으면 축을 넣는 것이 손해다.
  - 애매하면 판정하지 않는다(`n/a`). `세종특별자치시 조치원읍`처럼 시군구가 없는 표기,
    두 번째 토큰이 시/군/구로 끝나지 않는 표기가 그렇다.

  #### ② provider provenance 조인 — 불가로 종결 (2026-08-18)

  **원래 사유("`source_record_key`가 전부 NULL")도 낡았다.** 실측: prod
  `feature.curation_items`의 `source_record_key`는 **NULL 0 / NOT NULL 4,424**이고,
  `provider_sync.source_records`와 **4,424/4,424 전부 조인된다.**

  그런데도 이 AC는 달성할 수 없다. 이유가 둘이고 **둘 다 데이터 부재가 아니다.**

  1. **미연결 항목은 DB에 행이 없다.** `curation_items`에서 `feature_id IS NULL`인 행은
     **0건**이다. "미연결 261건"은 저장소 CSV 쪽 개념이고, 그 행들은 import되지 않는다.
     즉 조인을 **시작할 행**이 없다.
  2. **CSV의 `provider`는 적재 provider가 아니다.** 값은 `korea-arboreta-and-gardens`·
     `korea-tourism-100`·`lighthouse-stamp-tour`·`heritage-visit-campaign` —
     **캠페인 발행처**다. `provider_sync.provider_datasets`에 등록된 것은
     `python-*-api` 계열 18종이고 **교집합 0**이다. 같은 이름의 다른 축이다.

  → 이 AC는 "아직 안 했다"가 아니라 **질문이 잘못 세워진 것**이다. 미연결 항목의
  provenance를 provider_sync에서 찾을 수 없다 — 그 항목은 애초에 provider가 발행한
  것이 아니다. 후속으로 넘기지 않고 여기서 닫는다.
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
    → **처리 완료(2026-08-18)** — 아래 표 뒤 「처리 결과」 참조.
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
    카테고리를 고치는 것**이 맞다.

    ### 처리 결과 (2026-08-18)

    사용자 승인은 **"올바른 Feature로 재연결"**이었다. prod에서 후보를 전수 조사한 결과
    **재연결이 가능한 것은 5개 중 1개뿐**이었다. 승인에 "맞는 Feature가 DB에 없으면 결국
    해제로 떨어진다"가 명시돼 있어 그 fallback을 따랐고, 한 건은 **어느 쪽도 아닌 것**으로
    판정했다.

    | 항목 | 조사 결과 | 처리 |
    |---|---|---|
    | `김해가야테마파크` | `f_global_p_54ab91…` **`01010400`(관광지)** 존재 | **재연결** |
    | `태화강 국가정원` | 정원 자체가 DB에 없다 — 주차장 6개와 "…태화강국가정원점" 식당들뿐 | 해제(3행) |
    | `반디랜드&태권도원` | 후보 0건(질의 결과 빈 집합) | 해제(2행) |
    | `청풍호` | 전망대(`01050300`)·케이블카(`01080200`)는 호수가 아니라 호수의 **시설** | 해제(1행) |
    | `진해보타닉뮤지엄` | **링크가 맞다** — 이름·주소가 정확히 그 박물관이고 Feature가 하나뿐 | **유지** |

    `01010400`이 관광지 축인 근거(prod place 표본): 죽성드림성당세트장 · 연미산 자연 미술
    공원 · 머루 와인 동굴 · 깡깡이 예술마을 · 메타버스 체험관. 후보였던 `01000000`은
    관광지가 아니다 — place 표본이 사계절즉석국수 · 부전동촌국수 · 서가원이다.

    **진해보타닉뮤지엄을 해제하지 않은 이유.** 해제는 "이 항목에 맞는 Feature가 없다"는
    뜻인데 여기서는 맞는 Feature가 **있고 링크도 그것을 가리킨다**. 틀린 것은 그 Feature의
    category다(MOIS가 휴게음식점으로 인허가). 해제하면 맞는 링크를 지우고 문제는 그대로
    남는다.
    - [ ] **T-VN-H34A — Feature category 보정** — MOIS 인허가 업종이 실제 시설 성격과 다른 경우.
      같은 형태가 더 있는지 조사가 선행돼야 한다(박물관·미술관이 부속 카페 인허가로
      `02020100`에 묶이는 패턴).

    **부수로 고친 것 — manifest 카운트가 파생되지 않았다.** `refresh_manifest`의 docstring이
    "손으로 유지하면 CSV를 고칠 때마다 어긋난다, 그러니 **파생시킨다**"고 하는데 실제로
    파생하는 것은 `sha256`·`rows`뿐이었다. `linked_rows`/`unresolved_rows`는 손으로
    유지됐고, CSV 7행을 고친 뒤 스크립트를 돌려도 카운트가 **222 그대로**였다. 그 값이
    `_h35_csv5.py`의 `csv5_manifest_counts_mismatch` 게이트 입력이라 방치하면 게이트가
    거짓말을 한다. CSV에서 파생하도록 고쳤고(216/270) `EXPECTED_CSV_ACCEPTED`도
    222 → **216**으로 맞췄다 — 적대 검증이 "이 상수와 충돌해 shipped 코드가 죽는다"고
    지목한 지점이다.

    - [ ] **T-VN-H34B — prod curation import 반영.** CSV는 저장소 정본이고 실제 링크는 curation import가
      반영한다. import를 돌려야 공개 표면(3,265건)에서 사라진다.

    > **판정 로직을 두 번 고쳤다(기록)**. ① 동명 다수를 *모순*으로 셌다 → 222건 중 30건이
    > 모순으로 잡히고 그중 20건이 이 축 단독이었다. 동명 다수는 반증이 아니라 **그 축으로
    > 확정할 수 없다**는 뜻이다(30→10). ② 카테고리 기대를 `01`(TOURISM)만으로 좁혔다 →
    > `장태산자연휴양림`·`거창 항노화힐링랜드`(`03030000` LODGING_RECREATION_FOREST)가
    > 오탐이 됐다. 숙박을 갖춘 휴양림이 그렇게 분류되는 건 정당하다. 축을 "관광이어야 한다"에서
    > **"명백히 대상일 수 없는 유형인가"** 로 뒤집었다(10→8). 두 회귀 모두 단위 테스트로 고정했다.

> **issue #673 이력** — 이슈는 2026-08-07에 닫혔다. 당시의 457건·`0072` 관련 판정은
> 현 prod 상태를 설명하는 기준이 아니며, 남은 Feature category 보정·저장소 CSV의 prod import는
> 열린 `T-VN-H34A/B`가, 새 Feature 생성 경로는 `T-VN-M00`~`M03`이 소유한다.

### T-VN-H42~H45 — 운영 연속성 (0072 사고 후속: 재적재 수렴 → 강건화 → 백업 → 복원 드릴)

> 2026-08-04 prod 폐기·재생성(head `0078`) 후속. 2026-08-05 이미지 `c0afaa4e` 배포로
> head `0082`(UUID shadow 3종) 적용 완료 — **다만 2026-08-13 실측 prod head는 `0087`이고
> feature는 1,008,852행이다**(이 문단이 5 revision 뒤처져 있었다). 따라서 최신 H43
> baseline `2026-08-05-h43-postdeploy-0083.dump`(731,765행)는 두 head·약 27만 행 뒤처진
> 복구점이며, `0104`가 `feature_versions`/`data_origin`/`feature_change_requests`를
> 물리 삭제하므로 H44의 복원 실증도 `0083` 기준이라는 점을 함께 읽어야 한다.
> prod는 `archive_mode=off`라 **PITR이 없다 — dump가 유일 복구점**이다. codex 소관 41C prod enable은 H42 판정 + docker-manager
> 재pin 뒤(Lane B T-VN-41 절 경계 주석).

- [~] T-VN-H45-후속 — **다건 provider 호출·quota 관찰 확장**

  완료한 KMA/airkorea 강건화(`T-VN-H45`)의 후속 5축.

  - [x] ① **khoa 등 다건 루프 fetcher 확대(2026-08-18)** — KHOA 시도×페이지 경계를
    공용 재시도·run 예산으로 감싸고 timeout·내부 재시도 정산값을 client에 주입했다. upstream
    [python-khoa-api PR #8](https://github.com/digitie/python-khoa-api/pull/8)에서
    `serviceKey` 기본 전송 URL도 HTTPS로 전환했다.
  - [x] ② **python-kma-api resultCode 22 오분류 수정(2026-08-18)** —
    [python-kma-api PR #24](https://github.com/digitie/python-kma-api/pull/24).
    `22`는 data.go.kr 일일 한도 초과이고 그 한도는 **자정에 리셋**된다. `retryable` 축은
    같은 파일이 auth(20/30/31)=False · server(04/99)=True로 정한 대로 "**즉시 재시도가
    성공할 만한가**"이지 "언젠가 성공할 수 있는가"가 아니다. `True`면 호출자가 성공할
    수 없는 것에 retry budget을 태운다.
    - **테스트가 왜 못 잡았나**: `test_result_codes_raise_typed_exceptions`가 `12`와 `22`를
      한 묶음으로 돌리면서 `failure_kind`도 `retryable`도 단언하지 않았다(provider·endpoint만).
      `22`를 분리해 셋 다 단언하도록 고쳤다.
    - HTTP 200 XML `OpenAPI_ServiceResponse/cmmMsgHeader`도 같은 result-code 정책을 쓰며,
      `03`은 빈 결과, `22`는 비재시도 quota다. 임의 XML의 같은 태그는 parse error로 fail-close한다.
  - [x] ③ **RetryBudget 비례화/settings 노출 및 `_LOGGER`↔`python_logs` 결선(2026-08-18)** —
    예상 경계 수의 5%를 올림하되 최소 8·최대 32로 제한하고 두 값을 env/settings로 노출했다.
    KMA·DataGoKr·AirKorea·KHOA의 다건 경계에 공유 예산을 전달하며 provider logger WARNING을
    Dagster event stream에 결선했다. 예외 본문과 개행은 로그에 싣지 않는다.
  - [x] ④ **KMA 5종 + airkorea schedule에 `coalesce_active_runs=True`(2026-08-18)** —
    같은 job의 미종료 run이 있으면 tick을 건너뛴다.
    - ⚠️ **혼자 켜면 안 된다.** 상한이 없으면 hung run 하나가 그 스케줄을 **영구
      차단**하고, 증상이 "스케줄이 조용하다"로 나타나 고장처럼 안 보인다. 기존에
      coalesce를 쓰는 유일한 스케줄(`feature_notice_krex_traffic_notices`)이
      `max_runtime_seconds`와 짝인 이유다. 6개 모두 상한이 **없었으므로** 둘을 함께 넣었다
      (`_FRESHNESS_RUN_MAX_RUNTIME_SECONDS` = 7,200초, `MAX_RUNTIME_SECONDS_TAG`로 강제).
  - [ ] ⑤ alembic 1.19 적응

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
  - [x] 신규 DB 프로비저닝 함정 참조 링크 — superuser 확장 4종 사전 생성
    (manager #109 절차)을 restore 문서에서 링크한다.
    **해소(2026-08-18)**: `docs/backup-restore.md` **§2.2**를 신설했다 — 빈 DB 재생성이 n150의 1차 복구 경로("손상 시 재적재가 정책")이므로 그 첫 단계인 superuser 확장 선생성 SQL을 넣고 #109를 링크했다. 그 이슈의 **본문은 이미지↔pin 사고**이고 절차는 2026-08-04 코멘트에 있어 본문만 보면 놓친다는 점, 원문 식별자(`krtour_map`)가 낡았다는 점도 적었다. GRANT grantee는 정본(`docker/postgres-role-bootstrap.sh:521-522`)에서 직접 읽어 `ktm_feature_state_procedure_owner, ktm_feature_runtime`으로 썼다 — 조사 초안은 `ktm_feature_migrator`로 틀렸다.

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

### T-VN-H50 — CI integration flake: `test_t212d_perf_explain.py:546` planner 인덱스 선택

- [ ] **재현되는 flake다** — `test_t212d_dedup_refresh_and_consistency_checks_are_index_compatible`의
  첫 gate(`_assert_uses_index(dedup_refresh, 'idx_source_entities_provider_dataset',
  'idx_features_dedup_refresh_keyset')`)가 CI에서 간헐 실패한다. 2026-08-18까지 PR #975·#996·#998
  세 번 모두 **재실행 한 번으로 통과**했다(코드와 무관). 실패 시 planner가 `idx_source_links_…`로
  진입한다 — `enable_seqscan=off`라 인덱스는 타지만 gate가 받는 이름 집합에 없다.
- 원인 가설: `_seed_live_like_perf_data` 뒤 `ANALYZE` 표본이 실행마다 달라 동치 진입 경로 중
  하나를 고른다. 성능 축(선두 컬럼 selectivity)은 같지만 gate가 이름으로 고정한다.
- **재현 실험(2026-08-18, n150)**: 같은 테스트 6회 연속 전부 pass(13~15s). 즉 로컬에서는 재현되지
  않고 **CI 러너에서만** 뒤집힌다 — 코어 수·메모리·PostGIS 이미지 차이에서 오는 cost 추정 차이가
  유력하다. 따라서 (c) seed 결정화는 로컬에서 검증할 수 없다.
- **다음 발생 시 반드시 할 것**: 실패 로그의 `used={...}` 전문을 **잘리지 않게** 저장한다
  (`gh run view <id> --log-failed | grep -A2 'expected one of'`). 지금까지 확보된 조각은
  `used={'idx_source_lin…` 하나뿐이라 어떤 진입 경로였는지 확정하지 못했다.
- 고칠 방향(택1, 근거 필요): (a) 진입 경로 동치 집합을 근거와 함께 넓힌다(왜 동치인지 주석 필수 —
  기존 `_FEATURES_PK_ACCESS` 선례), (b) gate를 "driving relation에 Seq Scan 없음"으로 바꾼다,
  (c) seed 통계를 결정적으로 만든다(`default_statistics_target`·행 수 상향). **PR마다 재실행이
  필요하므로 머지 위생 비용이 실재한다.**

### T-VN-H46 — 완료 이력과 남은 배포 위생 follow-up

> `T-VN-H46B`~`E`의 완료 요약은 [`tasks-done.md`](tasks-done.md)에 이관했다. 아래에는
> 남은 `T-VN-H46F`·`G`의 근거를 함께 둔다.

**T-VN-H46B 완료 — prod 지오코딩 복구(2026-08-14).**

  08-13에 `.env`만 고치고 api만 재생성해 dagster/daemon 2개가 401 나는 상류 VWorld
  키를 들고 있었다. fail-open이 아니라 첫 요청에서 asset step이 통째로 실패하는
  형태였고, ETL이 08-07 이후 안 돌아서 아직 안 터졌을 뿐이었다.
  `up -d --no-deps --force-recreate` 후 세 컨테이너 전부 `POST /v2/reverse` HTTP 200.

**T-VN-H46C 완료 — VWorld fallback 사슬 제거 + geo key 의미 검증.**

  - [x] **fallback 사슬은 PR #979에서 이미 끊겼다.** 저장소 전체에
    `…GEO_API_KEY:-${NEXT_PUBLIC_VWORLD_API_KEY…}` 형태가 0건이고
    `tests/unit/test_geo_key_provenance.py`가 정적으로 지키며
    `test_deploy_automation.py:132-138`이 그 문자열의 부재를 직접 단언한다.
    `.env.example`도 `# (낡음)` 경고가 붙었다(`9bbb74d99`). **이 항목 본문이 낡았던
    것**이고, 남아 있던 축은 아래 하나뿐이었다.
  - [x] **`preflight()`가 의미를 안 봤다 → `verify_credentials()` 추가(2026-08-18).**
    `preflight()`는 (1) None (2) 공백 (3) 128자 초과만 본다 — 값이 무엇인지는 안 본다.
    2026-08-13 사고가 정확히 그 구멍이었다(VWorld 키가 결선돼 geo가 401로 거부했고,
    정/역지오코딩이 전부 실패하는 동안 preflight는 초록).
    `verify_credentials()`가 1회 호출로 geo가 **실제로 받아들이는지** 확인한다.
    판정은 의도적으로 비대칭이다 — **키 거부는 fail-close**(400 `E0100 field=key` /
    401 `E0401`), **도달 불가·5xx는 fail-open**(geo는 별도 stack이라 그쪽 지연이
    map 부팅 교착이 되면 안 된다).
    - 설계 제약: `geocoding.py`는 httpx를 **런타임 의존으로 갖지 않는다**
      (`pyproject.toml` 주석 + ADR-002/006/044 — client 수명은 호출자 책임).
      조사 초안은 이 모듈에서 `httpx.AsyncClient(...)`를 생성해 **런타임 `NameError`**가
      나는 코드였다(적대 검증이 잡음). 주입된 클라이언트를 쓰는 메서드로 바꿔
      새 의존도 ADR 개정도 없앴다.
    - 테스트 8종은 네트워크 없이 돈다. 그중 하나는 **probe가 키 헤더를 싣는지**를
      본다 — 안 실으면 geo가 거부할 수 없어 이 검사기가 *무엇도 검사하지 않으면서
      초록*이 된다.
  - [x] **호출 결선 완료(2026-08-18).** api lifespan에 붙였다. 기존
    `runtime_db_preflight_required`와 같은 형태 — 새 플래그
    `kor_travel_geo_preflight_required`(기본 False, 배포 compose가 True 주입)라
    라이브러리 단위 테스트는 영향받지 않는다. `base_url`이 없으면(보강 비활성) 건너뛴다.
    - 테스트 6종이 **결선 자체**를 본다: 플래그 off면 네트워크 0회, base_url 없으면 0회,
      키 거부면 기동 거부, 도달 불가·5xx면 경고 남기고 진행, client를 닫는지.
  - [x] **커버리지 한계를 코드에 박았다(2026-08-18).** 이 검증은 주입된 클라이언트를 쓰는
    python 경로만 본다. 2026-08-14 사고의 실제 통로였던 **Next.js admin UI 프록시**
    (`packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts`)는
    별개 축이고 이 검사가 **못 본다**. 그 사실을 `_verify_kor_travel_geo_credentials`
    docstring에 경고로 넣었다 — tasks.md에만 적으면 코드를 읽는 사람이 못 본다.
  - [~] **T-VN-H46F — admin UI geo proxy 결선.** Node 런타임은 server-only
    `KOR_TRAVEL_GEO_API_KEY`만 읽고, browser query의 `key`를 버린 뒤
    `X-KTG-API-Key` header로 전송한다. geo의 401 또는 400 `E0100 field=key`는
    `503 GEO_API_KEY_REJECTED`로 변환해 입력 오류와 구분하고 fail-close한다. Manager
    PR #173의 의도는 최신 Manager `main`에 재배치해 source
    `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY` → UI server-only alias 결선과 정확한 service
    격리 계약으로 흡수한다. root Compose·frontend Docker build/fingerprint·buildx·
    load-env·live/mocked E2E의 browser-global credential alias도 제거해 bundle 잔존 경로를
    닫았다. 구현·로컬 검증 뒤 독립 적대 리뷰와 CI가 남았다.

**T-VN-H46D 완료 — daemon 스키마 drift: `column request.providers does not exist`.**
  (2026-08-18 실측으로 종결 — **배포 이미지 lag이 맞았다**)

  ### 하마터면 틀린 근거로 닫을 뻔했다

  처음에 배포 컨테이너 안에서 `grep -r "request.providers"`를 돌려 0건을 받고 "코드에
  없다"고 결론지으려 했다. **그 grep은 애초에 못 찾는 형태다** — `request.providers`는
  PostgreSQL 오류 문자열이고 `request`는 **테이블 별칭**이라, 별칭과 컬럼이 SQL에서 따로
  조립되면 소스에 그 문자열이 통째로 존재하지 않는다. 0건이 "없다"가 아니라 "이 방법으로는
  안 보인다"였다.

  ### 실제로 확인한 것

  1. **grep 대상이 비어 있지 않은지 먼저 양성 대조.** 배포 경로
     `/usr/local/lib/python3.12/site-packages/kortravelmap`에 `.py` 172개, 확실히 있는
     문자열(`feature_operation`) 41히트 — 검사 자체는 동작한다.
  2. **DB에 그 컬럼이 없다.** `ops` 스키마 전체에 `providers` 컬럼 **0건**.
     `ops.feature_update_requests`의 실제 컬럼은 `request_id, scope_type, scope,
     update_policy, run_mode, priority, matched_scope, job_id, operator, reason,
     created_at, generation, dataset_membership_mode`다.
  3. **배포 코드가 그 컬럼을 질의하지 않는다.** `AS request` 별칭을 쓰는 파일들
     (`feature_update_repo`·`feature_update_active_repo`·`ops_repo`·`pipeline_repo`)에서
     `providers` 참조 **각각 0건**.
  4. **로그에도 없다.** daemon 재기동(2026-08-17T10:02) 이후 75,158줄에서 0건.

  ### 한계 — 이걸로 "고쳤다"고는 말할 수 없다

  로그는 **2026-08-17 10:02 이후만** 남아 있다(DB 4분할 때 컨테이너를 재생성했다). 즉
  "재발하지 않았다"의 관측 창은 약 12시간뿐이다. 닫는 근거는 로그가 아니라 **(2)+(3)**
  이다 — 지금 도는 코드가 없는 컬럼을 질의하지 않는다.

  배포 이미지는 `2026-08-13T20:23` 생성이고 revision label이 `development`다(빌드에 커밋이
  안 박혔다). 그래서 "어느 커밋에서 고쳐졌는지"는 이 경로로 특정할 수 없다.
  - [ ] **T-VN-H46G — buildx image commit provenance label.** buildx가
    `KOR_TRAVEL_MAP_GIT_COMMIT`을 실제 커밋으로 채우게 한다. 지금은 prod 3개 컨테이너가
    `development`라 배포된 것이 무엇인지 이미지에서 알 수 없다.

**T-VN-H46E 완료 — 공개 data.go.kr 키 현행 유지 판정(2026-08-14).**

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

## Lane A 상세 — 운영 위생 (2026-08-17 신설)

> 2026-08-17 DB 4분할 작업에서 드러났고 **소유 task가 없던** 것들이다. 셋 다 이슈가
> 정본이고 여기서는 실행 단위만 잡는다.

### T-VN-H49 — 4분할 인스턴스 백업 주체 (docker-manager #177 추적)

Map 인스턴스의 baseline 3건과 절차 문서화는 완료했다. 남은 소관은 docker-manager #177의
외부 인스턴스 주기화이며, 이 저장소는 **의존만** 추적한다.

- [ ] geo(`12500`, **33GB, 백업 0건**) · concierge(`12600`) · pinvi(`12800`)의 dump·
  sha256·manifest·retention 결선. map만 절차가 있다.
- [ ] 결선 후 `docs/backup-restore.md` §1의 "다른 세 인스턴스도 각자 백업 주체가
  필요하다 — 현재 미비이고 별건이다" 경고를 갱신한다.

AC: 세 인스턴스 각각의 최신 dump + sha256 + manifest가 존재하고 절차가 문서화됨.

## Lane C 상세 — 사문화 정리·미구현 dataset (2026-08-17 신설)

> 다른 lane과 barrier를 공유하지 않는다. 아무 때나 착수할 수 있다.

### T-VN-C02 — T-229-buildx arm64 multi-arch 배포 검증

**정적 점검 완료(2026-08-18), 실행은 막힘.**

- Dockerfile에 **아키텍처 하드코딩 0건**(`amd64`/`x86_64`/`aarch64`/`--platform` 없음).
- `scripts/docker-buildx.sh`의 `PLATFORMS` 기본값이 이미 `linux/amd64,linux/arm64`다.
- 남은 위험은 **바이너리 휠**이다 — `asyncpg` · `psycopg[binary,pool]` · `shapely` ·
  `geopandas`. 넷 다 manylinux aarch64 휠을 내지만, 그건 빌드해 봐야 확정된다.
- **실행이 막힌 이유**: ghcr.io push에 `GITHUB_TOKEN`이 필요하고, registry에 이미지를
  올리는 것은 외부로 나가는 동작이라 임의로 하지 않는다.

```bash
# 자격증명이 있는 환경에서 1회:
KOR_TRAVEL_MAP_DOCKER_PLATFORMS=linux/arm64 bash scripts/docker-buildx.sh
# 볼 것: 위 4개 패키지가 소스 빌드로 떨어지지 않는지(떨어지면 빌드가 매우 길어지거나 실패)
```

`docs/sprints/README.md`가 "본 저장소 잔여는 `T-229-buildx` 하나뿐"이라고 하는데
tasks.md에 항목이 없었다. `tasks-done.md`는 `[x]`인데 본문은 "arm64 buildx만 잔여"다.

- [ ] `GITHUB_TOKEN` 있는 환경에서 arm64 multi-arch buildx 배포 1회 검증.
- [ ] 결과에 따라 `tasks-done.md`의 `[x]`를 정정하거나 잔여 문구를 제거한다.

AC: arm64 이미지가 registry에 올라가고 n150/Odroid 중 arm64에서 기동 확인.

### T-VN-C03 — ADR-034 보조 dataset 5종 미구현 + provider 표 drift

`docs/architecture/provider-contract.md`가 다섯을 "**(계획 — 미구현)**"으로 둔다:
`krforest_trails`(숲길/등산로 route), `krforest_mountain_weather`,
`krforest_safety_notices`, `forest_fire_risk`, `khoa_coastal_notices`.

- [ ] 착수 여부는 **제품 결정**이다. 하지 않기로 하면 문서에서 "계획"을 빼고 그렇게 적는다.
- [x] **표 drift 해소(2026-08-18)** — `providers/__init__.py` docstring이 2026-05
  Sprint 계획표로 굳어 존재하지 않는 모듈 **3개**(`krforest_weather`·`krforest_trails`·
  `khoa_weather`)를 나열하고 실재하는 **6개**(`mcst`·`datagokr_file_data`·`krairport`·
  `kor_travel_concierge`·`feature_operation_registry`·`knps_name_translations`)를
  빠뜨리고 있었다. 실제 인벤토리로 교체했다.
  - 고쳐 적는 것만으로는 또 어긋나므로 **`tests/lint/test_providers_docstring_inventory.py`**를
    신설해 "표 + 예외 목록 = 디렉터리의 모든 모듈"을 강제한다. 새 provider를 넣고
    docstring을 안 고치면 red다.
  - 조사 초안은 "이 표는 디렉터리와 1:1"이라 단언하면서 표가 15행/실제 17개라
    **새 거짓 주장을 만들 뻔했다**(적대 검증이 잡음). 보조 모듈 2개를 예외로 명시하고
    그 예외 집합까지 테스트가 고정한다.
  - R2-15는 `provider-contract.md` 대상이고 이미 적용 완료다 — 이 drift는 별건이었다.

AC: 표와 실제 모듈이 일치. dataset 구현은 결정에 따라 별도 task로 분기.

### T-VN-40 인수 — 실태 (2026-08-18 재조사)

`resume.md`·이 문서 상단이 "구현 병합 완료 → n150 인수 + receipt complete + 물리 삭제만
남음"으로 서술한다. **저장소 실측은 다르다.** 조사 1명 + 적대 검증 2명(contract/ops lens)이
독립으로 확인했고, 검증자 둘 다 조사 초안의 일부를 뒤집었다. 아래는 **검증을 통과한 사실**만이다.

#### 사전 구현과 prod 실행을 분리한 여섯 단계

| # | 일 | 실태 | 근거 |
|---|---|---|---|
| 사전 | **40A write fence** | **미구현.** `curated_repo.py`의 legacy `INSERT/UPDATE`를 DB·ACL·static 3층에서 차단하는 migration/검사를 먼저 구현·병합한다 | `src/kortravelmap/infra/curated_repo.py`, `alembic/baseline/schema.sql` |
| 사전 | **identity mapping** | `ops.curation_cutover_identity_mappings` 적재 migration을 구현·병합한다. PinVi backfill의 입력이다 | 상세 설계 §6.2 step 3 |
| 사전 | **40C removal manifest 작성** | 삭제 대상·순서·검증을 manifest와 migration으로 먼저 review 가능하게 만든다. 실행은 receipt 뒤다 | 설계 §6.2 step 6-7 |
| ① | prod migration·fence enable | 사전 구현을 포함한 `0202~0221` 이후 migration을 prod head `0104`에 forward 적용한다 | `alembic/versions/` |
| ② | mapping 소비 (PinVi) | **Map DB mutation 없음**(2026-08-18 실측 정정 — 아래 ② 항목). PinVi가 identity-mappings 4,424건을 전량 읽어 mapping receipt를 봉인한다. Map admin CSV import(`preview`→`commit`)를 legacy projection 위에 돌리면 0223이 동결한 bucket B 전제가 깨지므로 **돌리지 않는다** | `docs/reports/t-vn-40-curation-write-model-detailed-design-2026-08-11.md` §6.3, PinVi `apps/api/app/services/curation_cutover_mapping_receipt.py` |
| ③ | live 인수 + soak | sanctioned `c7-prod-live-e2e.md`로 origin 검증·증거 redaction·백업/PITR 복구점을 확인한다 | `playwright.live.config.ts` |
| ④ | receipt complete | 9키 exact·`blocking_reason` 제거·freeze 상수를 함께 갱신한다 | `contracts/vnext/consumer-rollout-v1.json` |
| ⑤ | **40C 물리 삭제 실행** | ④ 뒤 manifest가 선언한 legacy repository/trigger/table/API/ACL을 forward-only로 제거한다 | ADR-075 결정 4 |

**순서 — ADR-075 결정 4가 정한다**: soak·reconciliation 전에는 legacy column/table/alias를
제거하지 않는다. 따라서 사전 구현·병합 → ① → ② → ③ → ④ → ⑤이며, 물리 삭제를 먼저 하거나
import 중 legacy write를 허용하지 않는다.

#### 검증자가 뒤집은 것 (초안이 틀렸던 곳)

- "40A는 병합 완료" → **아니다.** write fence가 없다. legacy와 canonical이 **양쪽 다 쓰기
  가능**한 상태로 prod에 나갈 참이었다.
- "`/v1/admin/curated-features*` 5개가 openapi.json에 있다" → **없다.** 실체는 curated 경로
  16개이고 path family가 다르다.
- "`ops.curation_cutover_identity_mappings`가 0건이면 설계상 불필요" → 설계 문서
  (`…detailed-design…md:895-897,951`)가 **명시적으로 migration이 적재한다**고 했다.
  적재 코드가 없는 것이지 필요 없는 것이 아니다. 지금 `GET /v1/service/curation-cutover/
  identity-mappings`는 count 0 / empty Merkle root라 PinVi backfill이 소비할 것이 없다.
- "`map_commit`에 무엇을 넣을지 모른다" → 러너가 정한다. 인수를 **실행한 그 커밋**이고
  `install-tvn34c-n150-fresh-live-e2e.sh:98-112`가 동치를 검사한다.

#### "전용 canonical principal"의 정체

DB role이 **아니라** ServiceToken principal 둘이다 — `service:pinvi`
(`pinvi:curation-snapshot:read`)와 `service:pinvi:curation-cutover`
(`pinvi:curation-cutover:read`). digest만 Map이 받고 원문은 docker-manager C6c(PR #174)가
주입한다. `.env.example`에 키가 없다(주입 주체가 다르다). DB role 쪽은 별도로
`ktm_curation_command_owner` 등 4개.

- [x] **T-VN-40A-fence** — legacy write 차단 (PR #994 → main `3e0732b3`, 2026-08-18). 3층 구현·검증 완료:
  **ACL**(`runtime_privileges` 표에서 `curated_features` write 제거 → DB가 거부, 통합
  테스트가 `SET ROLE ktm_feature_runtime`으로 실측) · **static**(`infra/legacy_write_fence.py`,
  repo write 4함수 첫 줄) · **route**(legacy admin write route 410 Gone).
  - 범위를 한 번 잘못 잡았다 — theme/source/rule catalog까지 막았다가 plan:28("catalog
    input만 유지")과 `0207_tvn40_theme_catalog.py`(T-VN-40이 새로 만든 procedure가 그 표에
    쓴다)를 확인하고 `curated_features` 하나로 좁혔다. 이름이 `curated_`로 시작한다고
    전부 legacy가 아니다.
  - legacy write가 **된다**를 단언하던 테스트를 **막힌다**로 뒤집었다(지우면 회귀를 잡을
    자리가 없다). read 경로 fixture는 test-only raw INSERT helper로.
  - **적대 리뷰(2명) 결과와 조치** — 둘 다 `holds=False`, P1 1건 + P2 4건. 전부 반영했다.
    - **P1 — merge가 runtime role로 죽는다.** `apply_feature_merge`가 legacy 표를 `FOR
      UPDATE`+UPDATE 3문으로 mirror하는데 fence가 그 권한을 뺐다 → 42501. 새
      `tests/integration/test_merge_under_runtime_role.py`(`as_api_runtime`)로 red 확인.
      **그 테스트가 하나 더 드러냈다**: legacy 다음으로 canonical `curation_collections`
      `FOR UPDATE`에서 42501 — **fence 이전부터의 결함**(20fa752d). 모든 merge 테스트가
      superuser라 CI가 못 잡았고 prod dedup 병합은 이미 깨져 있었다. 해결(0204/0214 패턴):
      `0222_tvn40a_merge_runtime_role` — command_owner 소유 SECURITY DEFINER procedure 5개
      (legacy lock/archive/sync/move + canonical collections lock)를 CALL. runtime에 표
      권한을 주지 않는다. 행 잠금은 트랜잭션 범위라 반환 뒤에도 유지된다. legacy 4개는 40C에서
      사라지고 collections lock은 남는다.
    - P2 inventory — lint가 `curated_repo.py` 이름 규칙만 봤다 → `infra/*.py` 전체를 SQL
      문자열 수준(상수+인라인)에서 훑어 감싸는 함수를 찾고 fence 호출 또는 allowlist
      (`update_curation_item`·`_lock_legacy_projections_for_item` — 0214 이전 Python writer,
      **어떤 runtime 진입점에도 연결돼 있지 않음**을 별도 테스트로 고정)를 요구.
    - P2 snapshot 표 — `curated_feature_detail_snapshots`는 읽는 코드도 쓰는 코드도 없는데
      RW였다 → SELECT만. 덤으로 ACL 표의 **phantom 항목 2개** 발견·삭제
      (`curated_tripmate_copy_snapshots` — legacy 0032가 rename, `weather_metric_series` —
      baseline에 없음). reconcile은 DB에 없는 표를 조용히 건너뛰므로 phantom은 아무 것도
      지키지 않으면서 "관리된다"는 인상만 준다. "표에 선언된 relation이 DB에 실재한다"
      통합 테스트 추가.
    - P2 spoof 422 — 삭제한 legacy 라우터 테스트의 canonical 대응: item POST/PATCH가
      body의 actor/selected_by/operator_updated_by/updated_by/created_by를 422로 거부하고
      repo command에 닿지 않음(ADR-066 D-2).
    - P2 admin UI — legacy detail 화면의 채택/해제/보관/편집이 410을 맞는다 → write 컨트롤·
      mutation 4개·FeatureEditor·CuratedPlaceSearchPanel 제거, fence 안내로 교체. read
      패널은 40C까지 유지(plan §40B의 write 절반을 지금, read는 40C에서).
  - **2차 적대 리뷰(2명, 수정분 대상)** — coverage 렌즈 `holds=True`(P2만), DB 렌즈
    `holds=False` P1 2건. 전부 반영.
    - P1 — **runtime preflight allowlist 미등록**: `infra/db.py`가 runtime 로그인이 EXECUTE할
      수 있는 procedure를 fail-closed로 대조하는데 0222의 5개가 없어 **API/Dagster가 기동을
      거부**했다(`test_tvn34_runtime_privilege_preflight` red — 1차 통합 선택에 빠져 있었다).
      `_ADMIN_CURATION_FEATURE_PROCEDURES`에 등록.
    - P1 — **EXECUTE 대상이 공유 그룹**: `ktm_feature_runtime`에 줘서 provider ETL identity
      (dagster runtime)까지 legacy row를 옮길 수 있었고 본문에 executor 게이트가 없었다(0214
      패턴의 절반만). 0214 형태 전체로: REVOKE FROM PUBLIC+runtime 로그인 전부, EXECUTE는
      `ktm_curation_admin_executor`(api runtime 상속)에만, 본문에 `session_user` 게이트.
      dagster runtime이 CALL하면 42501인 음성 테스트 추가. **그 결과 `test_merge_repo.py`의
      merge 호출 21곳을 전부 `as_api_runtime`으로 감쌌다** — superuser는 게이트에 걸리고,
      애초에 superuser 세션은 ACL 회귀를 못 잡는다.
    - P2 — trigger `sync_curated_feature_collection`이 command_owner로 돌 때 INSERT하는
      `curation_collections.created_at`이 0213 column grant에 없었다(0214부터 잠복) → 0222에서
      부여. splitter는 0214 사본을 그대로(`''` escape). route fence는 substring→segment
      regex. lint 정규식은 회피형(ONLY/MERGE/TRUNCATE/alias 없는 lock/FOR SHARE·KEY SHARE —
      넷 다 UPDATE 권한 필요) 전수 + ORM `CuratedFeatureRow` 가드. `postgres-schema.md`
      head→0222.
    - **배포 선행(잊지 말 것)**: orchestrator(docker-manager) `.env`의
      `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를 그때의 head(0223 뒤로는 `0223_tvn40_identity_mappings`)로 올려야
      `api-entrypoint.sh`가 fail-closed로 막지 않는다. T-VN-40 인수 실행 ①의 첫 줄.
    - 3차(재검증) P1 — executor 게이트가 superuser도 거부하는데 `test_cli_dedup_merge`(superuser
      DSN)와 `test_tvn35_typed_subtypes`(migrated_session) 2건이 여전히 superuser로 merge를 몰았다
      → CLI 테스트는 API runtime DSN(prod와 같음), tvn35는 `as_api_runtime`. `ktmctl dedup-merge`
      help에 "DSN은 API runtime 로그인" 명시(superuser/migrator DSN은 42501).
  - 머지됨(적대 리뷰 2명 hold · CI 4 workflow green · n150 전체 통합 931 passed/env-only 6 failed).
    **①~② 전에 머지돼야 한다**는 조건 충족.
- [x] **T-VN-40-mapping** — `ops.curation_cutover_identity_mappings` 적재 migration `0223_tvn40_identity_mappings`
  (설계 §6.2 step 3·§6.3 · [설계 문서](reports/t-vn-40-identity-mapping-loader-design-2026-08-18.md), 적대 리뷰 2명 hold).
  PinVi backfill의 입력이다. **PR #996 → main `fbc31f2f`(2026-08-18)** — 코드 적대 리뷰 2명(data/SQL · ops/deploy) 둘 다 hold, P2 반영:
  `SET LOCAL lock_timeout='30s'` · `api-entrypoint.sh` loader 중단 시 즉시 종료(30회 재시도 없음) ·
  `scripts/tvn40_identity_mapping_precheck.sql`(prod 실측 전부 0 · TEMP 권한 ok) · merge guard 회귀 · 0104에서
  seed된 중단 형태가 0202~0223 전체를 롤백함을 dedicated DB로 실측. 통합 13 · 유닛(entrypoint 포함).
  prod 실측(2026-08-18): legacy 4,424 전부 bucket B(1:1 projection). merge_repo는 mapping이 잡은 item의
  detach rekey를 명시 MergeConflictError로 막는다.
- [~] **T-VN-40C-manifest** — physical removal manifest와 migration을 사전에 작성·검토한다.
  legacy 물리 삭제 실행은 receipt complete 뒤다. **초안 작성(2026-08-18)**:
  `docs/reports/t-vn-40c-physical-removal-manifest-2026-08-18.md`(선행조건 P1~P6 · DB 삭제 순서 D1~D12 ·
  코드/프론트/계약 삭제 · static zero gate · 열린 결정 Q1~Q4) + 기계 판독본
  `contracts/vnext/t-vn-40c-removal-manifest-v1.json` + migration 초안
  `docs/reports/tvn40c/0224_tvn40c_physical_removal.py.draft`(alembic 밖). **적대 리뷰 2명 2라운드 완료(v2.2)**:
  DB 렌즈가 n150 시뮬레이션(prod-shaped·fresh)으로 D1~D9 + postcheck 통과 확인, P1 반영(D3b legacy_component_identity
  trigger·D4 0214 patch/archive procedure 재작성·prosrc 검사·splitter); code/contract 렌즈 hold(Q5 public catalog 제거·
  P7 PinVi lockstep·static zero 식별자/allowlist·누락 테스트/e2e/docs). 남은 구현: 40C PR에서 D4 본문·코드/프론트/계약
  삭제·static zero gate 테스트. 실행은 ①~④ 뒤.
- [~] **T-VN-40 인수 실행** — ① 완료 · ②~⑤ 남음.
  - [x] **① prod migration (2026-08-18)** — precheck 전부 0 → `pg_dump -Fc` 복구점
    (`~/backups/kor_travel_map_0104_pre-tvn40-1_20260818T082752Z.dump` + `.sha256`) + `.env` 백업 →
    소스 스냅샷 `~/ktm-src-14ec2368…` + `.env` 3키(REPO_DIR/GIT_COMMIT/EXPECTED_HEAD=`0223_tvn40_identity_mappings`)
    → 이미지 4개 빌드 → api 재생성으로 `0104→0223` **단일 트랜잭션** 성공. manifest
    `total=4424 by_kind={'legacy_projection': 4424}`. 사후: legacy 4424 = mapping 4424 ·
    `source_row_hash` 재계산 불일치 0 · dangling 0 · 포인터 불일치 0 · 0222 5 procedure
    owner=command_owner/SECDEF·dagster EXECUTE=false · legacy 표 SELECT only · 4 서비스 healthy.
    절차·선행조건은 `docs/deploy.md` §T-VN-40 prod 배포. **선행조건 2개가 새로 드러났다**:
    (a) `0202`가 요구하는 `ktm_curation_*` NOLOGIN role 4개 → bootstrap profile one-shot 선행,
    (b) manager compose가 항상 주입하는 빈 `KOR_TRAVEL_MAP_API_PINVI_CURATION_*_TOKEN_SHA256` →
    Map이 기동을 거부했다(`fix/api-settings-empty-pinvi-digest`로 수정, PinVi raw pair도 prod `.env`에 설정).
  - [~] **② mapping 소비 (2026-08-18 조사로 범위 정정)** — ①~④ 동안 dedup merge 금지.
    - **Map 쪽에 남은 데이터 mutation은 없다.** 설계 §6.3 표는 legacy `source_rule`+`curated` 행의
      target을 "promoted candidate + 기존 item 유지"로 못박는데 prod legacy 4,424는 **전부 `curated`**라
      archive 대상이 0건이고, canonical item 4,424는 import row 0 / created_by 0 / operator 0 /
      legacy_projection_id 4,424로 **bucket C·D(official/manual membership)에 해당하는 행이 하나도 없다**.
      여기에 admin CSV import를 돌리면 `current_import_row_id`·operator 필드가 붙어 0223이 immutable로
      동결한 `legacy_projection` 전제가 사후에 깨진다 — **돌리지 않는다.**
    - **실행 순서 정본: [`docs/runbooks/tvn40-pinvi-cutover.md`](runbooks/tvn40-pinvi-cutover.md)** (적대 검증 2명이 초안에서 P1 14건을 잡은 뒤의 수정본).
    - [ ] **PinVi prod 재배포가 선행이다.** prod `pinvi-api-latest`는 image revision `3b87c19c`(#434)로
      T-VN-40 소비자 코드가 **아예 없다**(client 모듈 없음 · config token 필드 0건 · OpenAPI curation route 0개).
      PinVi DB head는 `20260804_0049`로 `0050~0059` 미적용. 소비자 구현 자체는 PinVi `main` `dc8a683f`(#444,
      2026-08-18)에 이미 들어와 있다 → 필요한 것은 재빌드 + `pinvi-admin-bootstrap` one-shot(alembic upgrade)
      + 컨테이너 재생성이며, **`ktdctl pinvi-pair rebuild-pinned`는 3 DB 파기형이라 금지**.
      raw token pair는 manager `.env`에 이미 있고 Map digest와 일치한다(2026-08-18 설정).
    - [ ] **mapping receipt 봉인 = ②의 실질 완료** — `POST /api/v1/admin/notice-plans/curation-cutover/mapping-receipts`.
      성공 판정: `mapping_root=69eb85ecb178569bc87665ee1100b0a34ade4274512e5492e358c50a19140710` ·
      `mapping_root_version=ktm-curation-cutover-mapping-v1` · `mapping_count=4424` · `_items` 4,424행.
      **append-only + unique + advisory lock이라 되돌릴 수 없다** — 직전 백업이 유일한 복구 수단.
    - [ ] cutover **backfill 자체는 prod no-op**이다: PinVi prod `curated_trip_plans`/`curated_plan_pois`가
      0행이라 전환할 legacy plan이 없다. `GET …/curation-cutover/legacy-preflight`로 `ready=true`만 기록한다.
    - [ ] **canonical collection 59개 → PinVi notice plan import** (2026-08-18 사용자 결정: **한다**).
      `POST /api/v1/admin/notice-plans/imports/kor-travel-map-curation-collections`,
      body `{collection_id, mode:"create", is_published?}`, `Idempotency-Key`(UUID) 필수, 201/200(replay).
      ④ receipt 요건은 아니고 제품 결정이며, S3 배포 뒤 S4·S5와 함께 실행한다.
      **59개 구성**(prod 실측, 전부 `published/public`·빈 컬렉션 0·합계 4,424): concierge 채널
      (`concierge-yt-*`) 26개/1,481 · 재생목록(`concierge-pl-*`) 13개/1,462 · `media-places` 20개/1,481.
      같은 채널이 채널·재생목록·미디어촬영지 세 축으로 각각 한 컬렉션을 갖는다(둘시네아 440×3축,
      키다리짬뽕아저씨 362×3축, 여행작가 봄비 328×3축, 감성 국내여행지 97, 킴스트래블 83 …).
      최대 440 item < PinVi 상한 2,000이라 413 없음. 되돌리기 = plan soft delete + 백업 복원.
  - [ ] **③ sanctioned live/soak** (`docs/runbooks/c7-prod-live-e2e.md`)
  - [ ] **④ receipt complete** — 선행: PinVi 재-vendor PR. PinVi가 vendor한 user spec은 Map `73a9a246`
    (2026-08-05) 시절 바이트(`66fc83b3…`)인데 Map user spec은 `4672aa96`~`main` 전 구간에서 `6a2ee0f9…`로
    불변이다 → 순수 refresh(신규 path 2 · 변경 9 · 삭제 0). 이 불일치를 잡는 것은 Map의
    `tests/unit/test_vnext_contract_artifacts.py`뿐이고 PinVi CI는 못 잡는다. receipt는 **정확히 9키**로
    바꾸고 `blocking_reason`을 지우며 freeze 상수(`ARTIFACT_SHA256`)를 같은 커밋에서 갱신한다(LF 전용).
  - [ ] **⑤ 40C manifest physical removal 실행**(0224)

## Lane B 상세 — b1 PinVi 결합·후속

### T-VN-41 — cache-target generation·outbox 전파

> **41C prod enable 경계(2026-08-04 갱신)** — 41C의 "prod consumer enable + live 증명"은
> docker-manager **재pin(#109 — `2b2dee95`) 완료** + Lane A **`T-VN-H42`**(provider 재적재
> 완주·수렴 + H35 prod live 검증 잔여) **완료 후**에만 진행한다. 그 전 격리 스택 작업은
> 병행 무방(파일 충돌은 의도된 핀 2개뿐 — registry write 수·mocked manifest,
> journal 2026-08-04).
>
> **#975 후보 증거 상태(2026-08-18)** — 당시 `main` `0e26a232`의 후손 Map `77821001`과 PinVi
> `e8e0fecf`의 정확한 source archive를 n150의 별도 Docker project·volume에서만 실행했다. 실제 관리자 UI 로그인·
> BFF-only dead-letter replay·reconciliation 뒤 같은 stream의 `blocked`/consumer disabled/dead-letter
> 1/pending 1이 종결 reconciliation의 `ready`/consumer enabled/모든 delivery 0으로 수렴했다. 증거는
> stream 식별자·blocked event·snapshot epoch/count/Merkle와 request 종결 tuple을 회귀 test로 실패 폐쇄
> 결박했고, 두 적대 재리뷰의 P0/P1은 없다. 이 pair는 현재 `main` `142a1c12`의 후손이 아니므로
> rebase된 Map과 다시 pin한 PinVi archive/image에는 증거를 승계하지 않는다. 기존 PostGIS CI에서 예전
> direct replay test 2건이 consumer disable 계약과 충돌했으므로, reconciliation 재개 경로로 고친 뒤 새
> exact pair CI와 n150 Live UI E2E를 다시 통과해야 한다. 후보 receipt는 final main C7, production consumer
> enable 또는 `complete` 근거가 아니며 #975는 사용자 머지 지시 전까지 미병합이다.
>
> **머지 결정(2026-08-18, 사용자 지시)** — #975를 `main` `3e0732b3`(#994 fence 포함) 위로 rebase(head
> `a78f55dc`)하고 **CI green + 독립 적대 재리뷰 2명**을 게이트로 머지한다. **새 exact pair(rebased Map +
> 재pin PinVi)의 n150 isolated Live UI E2E 증거는 이번 머지에서 재생성하지 않는다** — 그 격리 pair 러너
> (`ktm41r778-*` 이미지·`tvn41-live-*` 스택을 만든 것)는 저장소에 없어 재구성 비용이 크고, 머지 자체는
> candidate 경계(`final_c7_required=true`, PinVi startup sync 거부)라 prod enable이 없다. 기존
> `77821001`/`e8e0fecf` 후보 증거는 그 pair의 이력으로만 남고(`t-vn-41-candidate-map` tag로 고정), 새 pair
> 증거는 **final C7 인수 때** 만든다. PinVi #444의 Map pin 갱신도 그때 함께.

- [~] T-VN-41A — **source generation·restore epoch**

  existing external identity/exact scope를 유지하면서 source generation과 restore epoch를 schema에
  도입하고 restore/backfill 시 단조성·중복 억제를 고정한다.

- [~] T-VN-41B — **transaction-coupled outbox writer**

  target/link/update 결과와 같은 transaction에서 generation-bearing outbox event를 기록한다.
  critical write path는 relay I/O를 기다리지 않고 commit/rollback 원자성만 보장한다.

- [~] T-VN-41C — **relay·reconciliation·consumer enable**

  lease/retry/dead-letter/replay가 있는 relay와 DB 대조 reconciliation을 추가한다. backfill checksum
  뒤 critical path 밖에서 PinVi 소비를 enable하고 누락·중복·restore epoch 전환을 live로 증명한다.
  - [x] source PUT/DELETE·refresh create를 exact `cache-target:command`로 분리하고 기존 consumer umbrella를
    clean cut 제거한다. command→consumer/snapshot/recovery와 consumer exact scope→command 양방향 `403` 회귀,
    exact 4-role binding과 consumer ID 단일 canonical system owner 검증, public API key digest 분리,
    17 operation의 machine-readable/runtime scope와 wrong-role zero-call 계약, service OpenAPI 재export를
    완료한다.
  - [~] PinVi command writer가 CAS source GET과 refresh `Location` polling에서 consumer credential로
    전환하고, restore clone은 sync disabled 상태에서 immutable pre-CAS receipt를 써 응답 유실 exact replay까지
    완료한다. 동일 key의 병렬 `201`/`200`도 terminal payload·ETag가 같으면 한 durable receipt로 수렴한다.
    T-VN-41S로 Map service OpenAPI SHA가 바뀌어 PinVi exact vendor를 새 Map head에 다시 고정한다.
    active paired receipt는 `pending`으로 되돌렸으며, 기존 `77821001`/`e8e0fec` 후보 archive·image·Live UI
    증거는 이전 service bytes의 이력일 뿐이다. PinVi vendor PR 병합과 새 exact pair의 적대 재리뷰·n150
    isolated evidence를 통과한 뒤에만 `candidate_verified` 승격과 후속 reconciliation/cutover로 진행한다.
  - [x] 일반 snapshot first page를 route transaction으로 durable commit하고 실제 만료 시각을 노출한다.
  - [x] source-material watermark reuse와 75분 server handoff/1시간 client receipt gate를 구현한다.
  - [x] stream share barrier와 snapshot 내부 exact material watermark로 lock-wait stale MVCC 누락을 막는다.
  - [x] 모든 outbox writer transaction을 stream → head/target/link 잠금 순서로 직렬화해 system별 relay
    cursor를 해당 stream의 commit-safe contiguous prefix로 만든다.
  - [x] DB trigger가 stream lock 뒤 relay sequence를 배정해 raw/future writer에도 같은 순서를 강제한다.
  - [x] barrier 5초 lock timeout/5분 statement timeout과 retryable `503`으로 hung writer를 bound한다.
  - [x] server cursor의 per-FETCH timeout과 별도로 두 scan/모든 INSERT의 누적 5분 deadline을 두고
    capture/persist 초과를 retryable `snapshot_build_timeout`으로 구분한다.
  - [x] system별 미만료 generic snapshot을 2개로 제한하고 동적 `429 + Retry-After` admission을 구현한다.
  - [x] 단일 snapshot 1,000,000 item/512 MiB 독립 ceiling과 초과 `413` fail-close로 process
    memory와 canonical material 크기를 bound한다.
  - [x] 만료·미참조 snapshot의 reader-safe foreground bounded GC를 구현한다.
  - [x] 전역 mutex·system round-robin·batch commit·시간/statement/no-progress 예산을 가진 hourly
    background GC와 exact 종료 backlog/total/unexpired/referenced metric을 구현한다.
  - [x] acquired GC run별 referenced item/header count를 Map DB에 멱등 영속화하고 직전 적격 baseline
    대비 시간당 증가율·보존 ceiling, 직전 acquired 대비 간격 무관 inventory loss 및 관측 불능을 Dagster metadata와
    warning alert로 노출한다.
  - [ ] n150 격리 DB에서 migration → 수동 GC → schedule ON → 다음 tick 순서로 검증하고,
    GC 처리량이 유입률을 상회하며 remaining backlog가 0인지 증명한다. referenced snapshot 증가율과
    보존 임계치 alert도 함께 확인한다.
  - [ ] (#975 적대 재리뷰 P2, 후속) relay 종결성 보강 — (a) run 중 source generation 변경으로 실패할 때
    stale generation tuple에도 `failed` status event를 내는 것이 안전하다(`_append_result_event`는
    generation을 검사하지 않음) → 억제 대신 emit; (b) running member의 operator cancel 전이
    (`_TRANSITION_JOB_MEMBER_SQL`)에도 queued 경로처럼 savepoint-guarded status event append.
    (c) 실패/취소 append의 violation 삼킴은 epoch precheck(또는 typed reason)로 gate해 향후
    `_append_result_event`에 검사가 추가돼도 조용히 삼키지 않게. (d) 통합 suite 순서 의존
    (`test_cache_target_stream_repo` commit 잔여 → `test_feature_update_repo`)은 main부터의 기존 문제.
  - [~] Map/PinVi exact head로 n150 isolated live UI recovery와 최종 prod gate를 통과한다.
    후보 Live UI recovery와 `blocked → ready` stream/replay/reconciliation 결박은 통과했다. 최종 prod
    gate는 별도 final main C7·production consumer enable 경계이며, PinVi system별 snapshot concurrency 1,
    `429/503 Retry-After` backoff, `413` non-retry, credential별 gateway limit 또는 동등한 외부 rate-limit과
    실제 호출 cadence를 함께 증명한다.

- [~] T-VN-41S — **snapshot materialization streaming·audit compaction 확장 (#922, C enable 비차단)**

  DB-side/bounded streaming Merkle materialization, receipt/material 공유, terminal audit item compaction,
  item/byte admission과 relation bytes/dead-tuple/vacuum metric을 1M+ synthetic/n150 soak로 검증한다.

  **이번 PR 종료선(완료)** — migration 없는 bounded streaming/admission·현재 스키마에서 안전한 단방향
  material 재사용·관측 metric·typed future error 계약까지다. 독립 적대 리뷰 2명은 최종 head에서 P0~P3
  잔여 없음으로 GO했고, 단위/API/Dagster 집중 231개와 PostGIS stream repository 37개를 통과했다.

  **후속 종료선(미완료, #922 유지)** — `0224` 착지 뒤 `0225+` 물리 모델, 양방향 공유, 실제 compactor와
  repository 410, migration/ACL/EXPLAIN 및 n150 1M+ 증거까지다. 이 항목들이 끝나기 전에는 #922 또는
  T-VN-41S 전체 완료로 표시하지 않는다.

  **이번 PR 완료 항목**

  - [x] PostgreSQL server cursor 2-pass scan, incremental Merkle v1, 1,000행 INSERT batch와 first-page만
    보관하는 process-memory bounded 경로를 구현한다.
  - [x] item 1,000,000/canonical material 512 MiB admission을 header INSERT 전에 검사하고 typed `413`으로
    fail-close한다.
  - [x] 유효 generic material을 two-phase reconciliation seal이 같은 snapshot으로 재사용하고,
    relation/index bytes·dead tuple·vacuum lag Dagster metric/alert를 추가한다.
  - [x] future terminal compaction page의 non-retryable `410 SNAPSHOT_MATERIAL_COMPACTED` API 계약과
    번호 없는 receipt/material DDL·upgrade/downgrade 설계를 고정한다.

  **후속 항목**

  - [ ] T-VN-40C 예약 `0224` 착지 뒤 `0225+`로 receipt/material/item 정규화 migration, 양방향 material
    공유, terminal retention compactor와 실제 repository 410 경로를 구현한다.
  - [ ] migration upgrade/downgrade·ACL/catalog·EXPLAIN과 n150 PostGIS 1M admitted/1M+ rejection,
    concurrent mutation safe lower cursor, compaction/vacuum soak evidence를 통과한다.

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
> receipt는 `pending`이다. #974가 lifecycle·consumer 전환의 기반을 병합했더라도 40A write
> fence·identity mapping·40C physical removal manifest는 아직 구현되지 않았고, 그 뒤 n150
> canonical import/backfill·live receipt·물리 삭제 실행도 남아 있다. 따라서 아래 A/B/C는
> release 관점에서 완료되지 않은 `[~]` 상태다.

- [~] T-VN-40A — **legacy writer inventory·write fence**

  `curated_features` overlay를 쓰는 route/job/trigger/repository를 전수 고정하고 신규 legacy write를
  차단한다. canonical curation과 effective projection checksum을 만든다.

- [~] T-VN-40B — **candidate lifecycle 분리·consumer cutover**
  - [ ] §6.2 step 3 후반 잔여(40-mapping에서 분리): legacy source_rule → candidate `legacy_backfill`
    transition, `default_action='curated'` 퇴역 + `ck_curated_source_rules_action` VALIDATE. ② blocker
    아님(candidate는 admin 전용, PinVi 입력 아님).

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

### T-VN-H34 잔여 — "없는 것은 Feature로 추가" (2026-08-18 조사)

사용자 지시: 재연결 대상이 없던 3건을 **Feature로 추가**하라. 조사 결과 **지금 바로는
못 한다** — 그 경로가 저장소에 없다.

**실측.** 세 항목은 prod에 **축제(event)로만** 존재하고 장소 자체는 어떤 provider
dataset에도 없다(kind·lifecycle·publication 무관 전수 검색).

| 항목 | prod에 있는 것 |
|---|---|
| 태화강 국가정원 | `태화강 국가정원 봄꽃축제`·`태화강 대숲 납량축제` 등 event 6건 + 주차장 6건 |
| 반디랜드&태권도원 | **0건**(place/event/area 어디에도 없다) |
| 청풍호 | `제30회 제천청풍호벚꽃축제` event 1건 + 호수 시설(전망대·케이블카) |

**왜 못 만드나.** `Feature`는 provider ETL이 만드는 것이 계약이다. 큐레이션이 Feature를
만드는 경로는 없고, `T-VN-40`의 write model도 **기존 public Feature에 링크**만 한다
(`docs/reports/t-vn-40-…-plan-2026-08-11.md:161` — "public Feature만 반환").

만들려면 새 표면이 필요하다:

- **새 `source_type`**(예: `curation_manual`) — `make_feature_id`의 입력이라 ID 체계에 들어간다
- **writer 경로와 소유권** — 누가 갱신하나? provider가 나중에 그 실체를 발행하면 dedup은?
- **lifecycle** — 3축(`lifecycle_state`/`publication_state`/`quality_state`)을 누가 정하나
- **T-VN-40과 충돌** — 그 릴리스가 지금 curation write model을 바꾸는 중이고, 사용자가
  이번 PR에서 **제외**하라고 한 범위다

### 결정 (2026-08-18, 사용자) — ETL 무관 Feature는 admin/API로 만든다

1. **ETL과 무관한 Feature는 admin UI/API로 추가할 수 있다.** provider가 발행하지 않는
   실체(국가정원·테마파크 복합·호수 등)가 대상이다.
2. **PinVi의 Feature 생성 요청도 같은 API를 쓴다.** PinVi가 직접 만들지 않고 **요청**하며
   admin이 승인한다.
3. **curated Feature를 추가할 때 대상 Feature가 없으면** 이 API로 Feature를 만들고
   curation에도 함께 넣는다.
4. **origin(누가 만들었나)을 구분해 보존한다** — admin 직접 / PinVi 요청 승인 / curation
   추가 중 생성. **Feature가 나중에 수정돼도 origin은 바뀌지 않는다.** ETL이 같은 실체를
   발행하는 상황이 되면 admin이 따로 판정한다.

#### 실측으로 보완한 것

**① 표면은 이미 있다. 결선이 없을 뿐이다.**
`ktm_feature_runtime`은 `feature.features`에 **SELECT만** 갖는다(INSERT 없음) — 직접
INSERT는 불가능하다. 그런데 procedure
`feature.create_feature_with_initial_state(p_feature jsonb, p_lifecycle_state,
p_publication_state, p_quality_state, p_context jsonb)`가 **이미 존재하고
`ktm_feature_runtime`에 EXECUTE가 이미 부여돼 있다.** admin 상태 전이용
`transition_admin_feature_state`·`reactivate_admin_feature_state`도 마찬가지다.
→ 새 쓰기 경로를 만드는 일이 아니라 **기존 procedure를 admin API에 잇는 일**이다.

**② "ETL이 엎어쓴다"는 일어나지 않는다 — 진짜 위험은 중복이다.**
`make_feature_id`는 `source_type`을 해시 입력에 넣는다(ADR-009). 수동 Feature와 provider
Feature는 **애초에 다른 `feature_id`**라 ETL이 그 행을 덮어쓸 수 없다. 실제로 생기는 문제는
**같은 실체에 Feature가 둘**이 되는 것이고, 그건 덮어쓰기가 아니라 **dedup/merge** 판정
영역이다. 결정 4의 "ETL이 엎어쓰는 상황"을 그 의미로 새긴다.

**③ curation과 함께 만드는 것은 구조적으로 가능하다.**
`curation_items.source_record_key`는 **nullable**이고 `feature.features`에는 source 쪽 FK가
없다(부모 Feature 자기참조 FK만 있다). 즉 provider source record 없이도 Feature와 curation
item을 만들 수 있다.

#### T-VN-41과의 관계 (2026-08-18 확인 — **직접 겹치지 않는다**)

사용자 질문 "H34 개선이 T-VN-41과 관련 없는지"에 대한 확인. 저장소와 PinVi main을 대조했다.

- **T-VN-41은 cache-target 표면이다.** `(external_system, target_key)` = **PinVi가 등록한 POI**를
  Map Feature에 링크하고, 그 링크·refresh 결과의 순서를 generation·outbox로 보존한다(ADR-081).
  대상 relation은 `poi_cache_targets`·`cache_target_*`이고 `feature.features`를 **쓰지 않는다**
  (`cache_target_outbox_repo.py`에 `feature.features` 참조 0건).
- **H34/M01은 `feature.features`를 만드는 표면이다.** `create_feature_with_initial_state`
  procedure를 admin API에 잇는다. cache-target을 건드리지 않는다.
- **PinVi의 Feature 생성 요청(M04)은 이미 별도 경로다.** PinVi main의
  `feature_requests.py:254`가 `admin_client.create_feature(payload)`로 **`POST /v1/admin/features`**를
  친다(`kor_travel_map_admin.py:3` — "`/v1/admin/features*` change API"). cache-target을 만지지
  않는다(`grep cache_target` 0건). 즉 M04는 41의 outbox를 타지 않고 admin API를 탄다.

**간접 접점 하나 — 미결.** 수동 Feature가 만들어진 뒤 PinVi가 그것을 POI로 **링크**하려면
cache-target 경로를 탄다. 그때 41C의 outbox가 그 링크를 전파한다. 이건 41의 정상 동작이지
H34가 41을 바꾸는 것이 아니다. 다만 **origin이 `manual_*`인 Feature를 41의 reconciliation이
provider Feature와 다르게 취급해야 하는지**(예: provider 재적재로 사라질 수 있는 Feature와
달리 수동 Feature는 restore epoch에서 어떻게 보이나)는 M02(origin 불변)와 41A(restore epoch)를
함께 볼 때 정해야 한다. 지금은 41A가 미착수라 정할 수 없다 — **M02 설계 시 41A 소유자와
확인 항목**으로 남긴다.

#### 아직 안 정해진 것

- **`source_type` / `source_natural_key`** — `make_feature_id`의 입력이라 ID 체계에 들어간다.
  origin 3종을 `source_type`으로 가를지(`manual_admin`/`manual_pinvi`/`manual_curation`),
  아니면 `source_type`은 하나로 두고 origin은 별도 컬럼에 둘지. **전자면 origin이 ID에 박혀
  불변이 공짜로 얻어지지만 origin을 정정할 수 없다.** 후자면 정정이 가능하지만 불변을 따로
  강제해야 한다.
- **natural key의 안정성** — 같은 실체를 두 번 만들면 같은 ID여야 하고, 이름을 고쳐도 ID가
  바뀌면 안 된다(`trg_features_identity_fence`가 `feature_id` UPDATE를 막는다).
- **3축 초기 상태** — 만들자마자 공개인가, 검토 후인가.
- **PinVi 요청 큐** — 접수 → 승인 → 생성. 요청 자체의 저장 위치와 상태 모델.
- **좌표** — `features.coord`는 nullable이지만, 지도에 안 찍히는 Feature가 공개 표면에
  나가도 되는지.
- **provider가 나중에 같은 실체를 발행하면** — 자동 병합하지 않는다까지는 정해졌다.
  admin에게 무엇을 보여주고 어떤 선택지를 주는지는 미정.
- **공개 표면 노출** — public API/PinVi snapshot에 수동 Feature가 나가는지, 나간다면 소비자가
  origin을 알 수 있어야 하는지.

#### 설계 초안 1차 — 적대 검증에서 무너진 것 (2026-08-18)

설계 초안을 검증자 2명(contract lens / ops lens)이 독립 검토했고 **둘 다 `holds=false`**다.
P1 6건 중 셋이 설계 방향을 바꾼다. 실측 근거가 붙어 있어 그대로 채택한다.

**① "origin은 호출 경로/principal에서 파생한다"는 실행 불가능하다.**
초안은 body로 origin을 받으면 사칭이 영구화되니 서버가 호출 경로에서 파생하자고 했다.
그런데 **PinVi와 admin BFF는 같은 endpoint(`POST /v1/admin/features`)·같은 proxy secret·
검증 없는 `X-Kor-Travel-Map-Actor` 헤더**를 쓴다(`auth.py:205,272-279`; PinVi
`kor_travel_map_admin.py:248-257,518-522`). 서버가 구별할 신호가 **없다.** 이대로 가면 PinVi
승인으로 생긴 Feature가 전부 `manual_admin`으로 **영구·불변** 각인된다 — 초안이 스스로
"불변 컬럼에 추정값을 넣으면 그 추정이 영구 기록"이라며 M01/M02 분리를 반대한 논거가
자기 자신에게 적용된다.
→ **M01은 origin을 `manual_admin` 단일 값으로만 발급한다.** `manual_pinvi`/`manual_curation`은
인증 경계가 실제로 갈린 뒤(별도 route 또는 별도 ops-token scope)에만 값 도메인에 넣는다.
도달 불가능한 값을 미리 등록하면 "구분되고 있다"는 오해까지 영구 기록된다.

**② 자연키를 opaque로 바꾸면 유일한 하드 중복 방지가 사라진다.**
현행은 `feature_id` unique + `ON CONFLICT DO NOTHING`(`schema.sql:1341`) → 409로 같은 실체를
막는다. 초안은 이름·좌표를 자연키에서 빼서 매 요청이 다른 `feature_id`가 되게 했고, 중복
방지를 READ COMMITTED 하의 check-then-act 프리체크로 대체했다 — 동시 요청 2건이 모두 통과한다
(TOCTOU). 게다가 판정 워크플로는 M05로 미뤄져 있어 **M01 머지 시점에 방어가 0**이다.
→ 자연키 opaque화와 **동시에** DB 제약을 둔다: origin `manual_%` 부분 unique index(`lower(name)`,
`sigungu_code`) 또는 `ST_DWithin` EXCLUDE, 또는 `admin.feature.create`에 `serializable`
(`domain_command_registry.py:164-168`이 지원, 40001 재시도 루프 있음).

**③ 새 CHECK가 `PATCH /state`에서 500으로 샌다 — 2026-08-12에 이미 한 번 겪은 유형이다.**
`admin_feature_repo.py:2186-2211`의 23514→도메인 오류 매핑이 **constraint 이름 allow-list**라,
새 CHECK 이름이 거기 없으면 raw re-raise → catch-all 500. 초안의 테스트는 "DB CHECK로 실패"만
요구해 **500이어도 초록**이다. 그리고 근거로 든 fail-close 테스트
`test_admin_state_error_mapping_names_exist_in_ddl`은 **저장소에 없다**(docstring 언급 1건뿐).
→ 새 CHECK 이름을 `_ADMIN_STATE_CONFLICT_CONSTRAINTS`에 넣고, 테스트는 **HTTP status를 단언**한다
(409/422이지 500 아님). "features의 모든 CHECK 이름이 두 집합 중 하나에 있다"는 역방향 fail-close
테스트를 **실제로 만든다.**

**④ `transition_kind='initial'` ⇒ origin 필수 규칙이 기존 integration 테스트 4곳을 즉시 red로 만든다.**
`initial`은 provider 경로가 아니라 비-provider 일반 create kind이고(`schema.sql:1807`),
`test_tvn34c_post_cutover_contract.py:84` 등 fixture 4곳이 origin 없이 CALL한다.
→ 규칙을 "origin이 있으면 `initial`이어야 한다"(역방향)로 약화하거나, fixture 4곳 수정을 구현
순서에 명시한다.

**⑤ `contracts/vnext/*` freeze 갱신이 통째로 빠졌다 — 그런데 freeze 스위트는 green을 유지한다.**
`target-schema-v1.sql:730`이 `create_feature_with_initial_state`를 선언하고 fingerprint는 계약
파일로 만든 DB를 본다(`test_vnext_target_freeze.py:16-18` — "계약이 실제 migration과 갈라져도
green"). 컬럼 축은 의도적으로 닫혀 있다(`:1723-1760`). 즉 **CI가 초록인 채 vNext 목표 계약이
실제 스키마를 서술하지 않게 된다** — 이 저장소가 반복 경계한 바로 그 형태.
→ 구현 순서에 `target-schema-v1.sql` · `target-schema-fingerprints-v1.json` 4카테고리 재계산 ·
`violation-fixtures-v1.sql` + `expected-rejections-v1.json`(신규 거부 케이스) 갱신을 넣는다.
`test_vnext_contract_artifacts.py`의 sha256 상수도.

**⑥ P2 중 결정에 걸리는 것**: `publication_state` 기본값 `published→draft`는 PinVi의 사용자
제보 승인 흐름(`feature_requests.py:242-251`)에 무음 회귀를 낸다 · 3단계 backfill의 전건 UPDATE가
`row_revision` trigger를 100만 번 밟는다 · procedure OWNER 전환과 migration graph artifact 재생성이
선행 조건에 없다 · back-out을 한 줄도 안 다뤘다(forward-only 저장소).

**다음**: 위 ①~⑤를 반영한 **설계 초안 2차**를 쓰고 같은 검증자 2명에게 다시 건다.
2차가 `holds=true`를 받기 전에는 코딩하지 않는다.

#### 후속 task

- [ ] **T-VN-M00 — 설계 초안 2차 + 적대 검증 2명 통과** (위 ①~⑤ 반영). 이것이 M01의 선행이다.
- [ ] **T-VN-M01 — admin Feature 생성 API** (결정 1). `create_feature_with_initial_state`를
  admin OpenAPI에 잇는다. `source_type`/natural key 규칙과 3축 초기 상태를 함께 정한다.
  **ADR 필요** — ID 체계에 새 `source_type`이 들어간다.
- [ ] **T-VN-M02 — origin 보존과 불변** (결정 4). origin 3종을 구분해 저장하고 Feature
  수정에도 불변임을 스키마·테스트로 고정한다. `trg_features_identity_fence`가 이미
  `feature_id`/`feature_uuid`에 같은 일을 하므로 그 패턴을 따른다.
- [ ] **T-VN-M03 — curated 동시 생성** (결정 3). curation import/admin 편집에서 대상 Feature가
  없을 때 M01을 호출해 만들고 `curation_items`에 잇는다. **T-VN-40의 write model과 같은
  표면**이라 그 인수 뒤에 얹는다.
- [ ] **T-VN-M04 — PinVi 요청 큐** (결정 2). PinVi가 HTTP로 요청하고 admin이 승인한다. 승인
  시 M01을 호출하고 origin을 `manual_pinvi`로 남긴다. cross-repo 계약이라
  `docs/integration-map.md`에도 추가한다.
- [ ] **T-VN-M05 — provider 발행 시 중복 판정** (결정 4 후단). 수동 Feature와 같은 실체를
  provider가 발행하면 dedup 후보로 올리고 **자동 병합하지 않는다.** admin이 병합/유지/수동본
  폐기를 고른다.
- [ ] **T-VN-H34 잔여** — M01~M03이 서면 태화강 국가정원·반디랜드&태권도원·청풍호를 Feature로
  만들고 curation을 재연결한다. 그때까지는 해제 상태를 유지한다.
