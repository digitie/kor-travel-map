# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스 (2026-08-21 완료 이관)

완료한 `T-VN-32`·`T-VN-33`·`T-VN-37`·`T-VN-38`·`T-VN-40`과 선행 운영 task는
[`tasks-done.md`](tasks-done.md)로 이관했다. 이후 완료된 `T-VN-H50`·`T-VN-C05A`~`C05D`·
`T-C7-BROWSER-EVIDENCE`·`T-C7-SCOPE-REGISTRY`·`T-C7-LIVE-SERIAL`·`T-FE-MOCK-MANIFEST`·
`T-VN-37D`도 같은 곳에 있다. **2026-08-21 `0229`~`0232` 묶음 prod 배포로 종결된
`T-VN-40B`·`T-VN-C05-CATALOG-KEY`도 이관했다.** 아래에는 아직 닫히지 않은 실행 단위만 둔다.

**Lane A (Claude Code)**와 **Lane B (codex)**는 서로 병렬 실행한다. 각 lane 내부는 아래 순서를
지키며, 같은 migration head·OpenAPI 정본·같은 cross-repo pair를 만지는 시점만 공통 규율의
barrier로 직렬화한다.

- **Lane A — cross-repo 계약·운영·데이터 품질**
  - [~] `T-VN-H34`(공식 curation 미연결 membership 잔여 AC — `T-VN-M01`~`M03` 선행 필요)
  - [~] `T-VN-H43`(실 production 전환 시 manager #148로 정기화 재개)
  - [~] `T-VN-H49`(4분할 baseline·primitive 완료 / 주기 실행·보존·off-box 증거 잔여)
- **Lane B — frontend hardening·PinVi 소비 API**
  - [~] `T-VN-41C`(#975 병합 / final exact-pair·prod consumer enable 잔여)
  - [~] `T-VN-41F1D-E`(v5/v7 attestation 전환 — **저장소측 완료 2026-08-20**, live 실행은 배리어 대기)
  - **배리어**: [ ] `T-VN-FINAL-REBUILD`(주요 개발 완료 후 파괴적 재구축 — 사용자 결정 2026-08-20)
  - [ ] `T-FE-MOCK-FLAKE`(`/v1/ops/logs`)
  - [~] `T-VN-41F1D-D1` → [ ] `T-VN-41F1D-D2` → `T-VN-41C` receipt 승격
- **Lane M — 수동 Feature 생성 (2026-08-18 결정)**
  - [~] `T-VN-M01`(admin Feature 생성 API foundation 병합, `0226` DB/ACL/route 잔여) → [ ] `T-VN-M02`(origin 보존·불변)
  - [ ] `T-VN-M03`(curated 동시 생성) ∥ [ ] `T-VN-M04`(범용 Feature 요청 큐 — 첫 consumer는 PinVi)
  - [~] `T-VN-M05`(provider 발행 시 중복 판정 — 자동 병합 금지, paired consumer reconciliation 설계 진행)
- **Lane C — 사문화 정리·미구현 dataset (다른 lane과 무관, 아무 때나)**
- **최종 cutover**
  - [ ] `T-VN-39`
- **보류/외부 추적**
  - [ ] `T-101` — Materialized View 도입 검토(조건 발생 시)

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
- **문서 전용 PR 예외**(사용자 지시 2026-08-19): 코드·DB·runtime·생성 산출물 변경이 없는
  순수 문서 PR은 문서 링크·형식과 보안/redaction gate를 로컬에서 통과하면 원격 CI 결과를
  기다리지 않고 바로 머지한다. 코드가 섞인 PR의 마지막 commit만 문서 변경인 경우에는
  이 예외를 적용하지 않고 PR 전체 CI를 끝까지 확인한다.
- **우선순위(서비스 전 단계 — 사용자 지시 2026-07-26)**: **정확성·보안 최우선은 불변**
  (AGENTS.md), 그 아래 설계적 우수성 > 확장성 > 성능 > 불필요한 코드 반복(래퍼류) 금지.
  **prod 환경 보전·호환성·기존 문서 계약·최소 수정은 비제약** — 필요 시 DB 스키마·문서
  계약 수정 가능. AGENTS.md vNext 우선순위 단락에 동일 취지의 dated note를 둔다.
- migration 정본: 단일 head 유지. `origin/main`은
  `0232_tvn37d_notice_empty_range`까지이며, draft #1029는 그 위에
  `0226`(M01)→`0227`(M02)→`0228`(M03)→`0233`(M04)→`0234`·`0235`(M05)를 직렬로
  연결한다.
  prod 적용 head는 배포 직전 live DB에서 다시 확인한다. 후속 migration 소유자는
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
  Wave 2 join barrier는 완료됐으며, 최종 `T-VN-39`만 남았다.
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

## Lane A 상세 — 열린 이슈·데이터 품질 하드닝

> 2026-07-27 open-PR·이슈 전수 확인에서 main에 잔존하는 미수정 버그/하드닝을 백로그화.
> 각 항목은 GitHub 이슈에 tasks.md 백로그 링크를 함께 기록한다.

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

## 이슈 종결 추적

> landing task와 완료 조건이 동일한 열린 이슈만 함께 닫는다. LIVE-01 후속 OPEN 7건은 Lane A
> `T-VN-H16`/`T-VN-H17`에서 독립 재검증해 **7건 전부 close**했다. 6건은 H16
> (dm#63·#70·map#712·#719·#777·#694), map#684는 H17에서 조건 #8을 "write/error UI 엣지는
> mock, read·URL·freshness + write 계약은 live"로 명시 축소한 뒤 close했다.

- **task로 승격**: map #673=`T-VN-H28A/B`, map #819=`T-VN-H27`(2026-08-22 종결·`tasks-done.md` 이관).
- **종결**: map #738은 lane 분배 정본을 본 문서로 이관해 닫혔다. map #930(geo key
  미결선 — dagster job 고착)은 docker-manager compose 결선(#114 트랙) + 3 컨테이너
  env 실측 + krex job 연속 SUCCESS로 2026-08-05 close.
### T-VN-H49 — 4분할 인스턴스 백업 운영 잔여

- [~] T-VN-H49 — **주기 실행·bounded retention·off-box 증거 완성**

Map 인스턴스의 baseline 3건과 절차 문서화, Docker Manager #177의
6-role standalone backup primitive, Geo application DB의 앱 레벨 schedule env 결선
(PR #181, merge `969eff18`)까지 완료했고 #177도 닫혔다. 그러나 이 task의
운영 AC인 주기 실행·bounded retention·off-box 증거는 남아 있다.

- [~] Geo application DB 첫 자동 백업은 4.71 GB artifact와 sha256 verify까지 성공했다.
  다만 `scheduled_backup`과 retention janitor가 계속 RUNNING이며 최근 성공·bounded retention으로
  수렴하는지는 운영 증거가 더 필요하다. application DB에 standalone cron을 중복 설치하지 않는다.
- [ ] 별도 `geo_dagster` metadata DB와 concierge(`12600`)·pinvi(`12800`)에 standalone
  create → sha256 검증 → list → GC를 실행하고 cron/systemd timer 및 최신 dump + sha256 +
  manifest 증거를 남긴다.
- [ ] off-box 사본 자동화를 결선한다. Map application/Dagster 주기화는 #148의 재적재 정책
  결정을 따르며 이 task가 임의로 활성화하지 않는다.
- [ ] 위 운영 AC를 닫은 뒤 `docs/backup-restore.md` §1의 외부 instance 경고를 현행화한다.

AC: 필요한 외부 DB마다 최신 dump + sha256 + manifest, 주기 실행과 보존 GC, off-box 사본
증거가 있고 절차가 문서화되어야 한다. PR #181 병합만으로 H49를 완료 처리하지 않는다.

## Lane C 상세 — 사문화 정리·미구현 dataset (2026-08-17 신설)

> 다른 lane과 barrier를 공유하지 않는다. 아무 때나 착수할 수 있다.

### C7 후속 검증 잔여

- [~] **T-FE-MOCK-FLAKE** — `e2e/admin-ops.spec.ts::admin/ops pages › /v1/ops/logs` 간헐 실패

  System logs 표의 첫 columnheader `생성`이 15초 안에 보이지 않는다(`admin-ops.spec.ts:744`).
  앞선 filter control 단언은 모두 통과하므로 표 mount 전에 header를 단언하는 순서 문제로
  보인다. n150 5회 실행 중 2회 실패 — 부하가 높을 때 재현된다. mocked config가
  `retries: process.env.CI ? 1 : 0`이라 **로컬은 재시도가 없어** 느린 렌더가 곧 실패가 된다.

  이 spec은 완료된 C7 browser evidence 이식이 건드리지 않았고 mocked checkpoint는 CI 잡이
  아니라 수동 게이트다 — 즉 **기존 flake**다. 표/행이 도착한 뒤 header를 단언하도록
  고쳐야 하며, 재시도로 덮지 않는다.
  2026-08-21 PR #1045에서 표별 locator scope와 body row 준비 대기, `aria-busy` 해제 대기를
  추가했다(`09d47cf7` → `d208b76a`). 전문 리뷰어 2명이 누적 diff를 재검토해 P0/P1/P2
  0건을 확인했다. n150 mocked checkpoint A는 281/285 passed였고 이 spec은 self-owned
  mock backend의 응답 부재로 `aria-busy=true`가 15초 유지되어 실패했다. 나머지 3건도
  기존 실패 표면이다. PR head `14db3b5c`의 CI 4개(`ci`, `lint`, `frontend`, `openapi`)는
  모두 green이다. n150 live GET-only logs 스펙은 현재 local-only 자격증명과 prod credential
  불일치로 재시도에서도 auth setup 401에서 중단되어, 최신 자격증명 확인 뒤 재개해야 한다.
- `T-C7-SCOPE-REGISTRY`와 `T-C7-LIVE-SERIAL`은 PR #1038에서 완료했다. scope 선언
  주체·조회 표면을 `integration-map.md` §3.7과 ADR-088 결과에 정본화했고,
  `external_system:c7-e2e` live write 3종에는 cross-worker `mkdir` 잠금을 결선했다.

## Lane B 상세 — b1 PinVi 결합·후속

### T-VN-41 — cache-target generation·outbox 전파

> PR [#975](https://github.com/digitie/kor-travel-map/pull/975)는 merge
> `4672aa966cd473f17fd4f69ee8066276f7be900d`로 병합됐고 CI 8개가 모두 성공했다.
> source generation·restore epoch(`T-VN-41A`)과 transaction-coupled outbox writer
> (`T-VN-41B`)는 독립 완료로 이관했다. 남은 `T-VN-41C`는 final exact-pair evidence와
> production consumer enable·reconciliation 종결 AC를 소유한다.

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

    **조사 기록(2026-08-21) — service spec `410` 선언(T-VN-41S에서 이월)과 당시 대응안.**
    아래의 “아직/막는 것” 표현은 조사 당시 상태를 기록한 것이며, 현재 반영 상태는 마지막 문단을 따른다.

    - 바뀌는 산출물은 **셋**이다. `openapi.service.json`, `openapi.json`(전체 spec도 service
      route를 담는다), 그리고 그 둘에서 생성되는 admin frontend `src/api/types.ts`
      (`.github/workflows/frontend.yml`의 `gen:types:check`가 gate한다). `openapi.user.json`은
      그대로다.
    - 재생성은 서버·DB 없이 된다:
      `python packages/kor-travel-map-api/scripts/export_openapi.py --profile all --output ... --user-output ... --service-output ...`
      `openapi-drift` CI가 같은 명령을 `--check`로 돌려 문자열 비교하므로 재생성본을 함께 커밋해야 한다.
    - **PinVi를 먼저 머지한다.** PinVi의 `contract-pin-consistency`는 `map_release_revision`을
      full SHA로 checkout하므로 **미머지 Map 브랜치에서도 vendoring이 성립한다**(실제로 PinVi가
      Map main에 없는 `037e2469`를 핀하고 있다). Map을 먼저 올리면 `pinvi_service_vendor_sha256`에
      PinVi main이 갖고 있지 않은 해시를 적게 되어 계약이 거짓이 된다.
    - **당시 함께 고쳐야 할 것 — spec이 거짓을 말했다.** `0229`~ 이후 코드가 강제하는 admission
      상한은 `item 500,000 / material 56 MiB`인데, route docstring 3곳
      (`routers/cache_target_streams.py`)과 거기서 생성된 두 spec은 당시
      `1,000,000 / 512 MiB`라고 적었다. 누락이 아니라 **틀린 서술**이었고, 소비자가 읽을 수 있는
      유일한 문서였다. 이 문제는 #1051에서 `410` 선언과 함께 Map service/full spec 및 admin
      타입을 재생성해 해소했다.
    - **당시 막힘 셋(현재 반영 상태는 마지막 문단 참조).** 당시 (1)만 truthfulness 문제였고
      (2)(3)은 spec bytes가 움직이는 순간 바로 red가 되는 hard gate였다.
      1. `contracts/vnext/tvn40-live-acceptance-v1.json`이 T-VN-40 receipt의
         `map_commit`/`pinvi_commit`과 결박돼 있는데 당시 `pending` 가드가 없었다. receipt는
         `complete`이고 `map_commit`의 spec 해시는 옛 값이라, spec을 바꾸면 그 주장이 거짓이 됐다.
         대응안은 (a) 새 pair로 n150 paired live acceptance를 재실행해 재봉인하거나 (b) 교차 결박에
         `state == "complete"` 가드를 두고 T-VN-40을 `pending`으로 되돌리는 것이었다.
      2. 당시 `tests/unit/test_vnext_contract_artifacts.py`가 세 spec 파일 해시를 T-VN-40
         deployment receipt와 대조했으므로 spec 변경 시 receipt 갱신이 필요했다.
      3. 당시 같은 파일이 T-VN-41 receipt의 `map_service_openapi_sha256`를 현재 tree 해시 및
         `pinvi_service_vendor_sha256`와 **`pending` 갈래에서도** 등치시켰다. 그래서 PinVi를
         먼저 머지해야 한다고 판단했다.

    active paired receipt는 `pending`으로 되돌렸으며, 기존 `77821001`/`e8e0fec` 후보 archive·image·Live UI
    증거는 이전 service bytes의 이력일 뿐이다. Map 쪽은 이번 PR에서 실제 runtime 410 선언과 상한 설명을
    service/full spec에 반영했고, PinVi vendor PR 병합과 새 exact pair의 적대 재리뷰·n150
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
  - [x] n150 격리 DB에서 migration → 수동 GC → schedule ON → 다음 tick 순서로 검증하고,
    GC 처리량이 유입률을 상회하며 remaining backlog가 0인지 증명한다. referenced snapshot 증가율과
    보존 임계치 alert도 함께 확인한다.
    → 6개 축 전부 PASS. 처리량 65,214 items/s vs 유입 12,951 items/s, tick t+21초 생성·t+26초
    SUCCESS, backlog 0/0, alert는 조인 임계치에서 발화·기본값에서 침묵.
    실측 기록 `docs/reports/t-vn-41c-cache-target-gc-verification-2026-08-20.md`,
    재실행 게이트 `scripts/verify-tvn41c-cache-target-gc.sh`(일회성 절차로 두지 않았다 —
    스키마·GC 예산이 바뀌면 다시 돌려야 한다). Dagster storage DB는 애플리케이션 DB와
    분리해야 한다(storage가 자기 alembic 계보를 같은 `public.alembic_version`에 stamp한다).
  - [x] (#975 적대 재리뷰 P2) relay 종결성 보강 — PR #1026(merge `b2e9c43a`). 착수 전 조사에서
    넷 다 미구현으로 확인됐고, (c)는 '향후 위험'이 아니라 이미 현재 위험이었다. typed reason
    도입 + 억제/삼킴을 `epoch_moved`에만 한정, running 취소 전이에 relay event 추가, 생산자
    모듈의 autouse truncate로 순서 의존 제거. 적대 리뷰 2명이 NO_GO를 냈고, 검증을 통과한
    P1(내 변경이 `done`을 `failed`로 접던 것)과 공허했던 새 테스트를 고쳐 재검증했다.
    원래 항목 서술: (a) run 중 source generation 변경으로 실패할 때
    stale generation tuple에도 `failed` status event를 내는 것이 안전하다(`_append_result_event`는
    generation을 검사하지 않음) → 억제 대신 emit; (b) running member의 operator cancel 전이
    (`_TRANSITION_JOB_MEMBER_SQL`)에도 queued 경로처럼 savepoint-guarded status event append.
    (c) 실패/취소 append의 violation 삼킴은 epoch precheck(또는 typed reason)로 gate해 향후
    `_append_result_event`에 검사가 추가돼도 조용히 삼키지 않게. (d) 통합 suite 순서 의존
    (`test_cache_target_stream_repo` commit 잔여 → `test_feature_update_repo`)은 main부터의 기존 문제.
  - [~] Map/PinVi exact head로 n150 isolated live UI recovery와 최종 prod gate를 통과한다.
    **선행: `T-VN-FINAL-REBUILD`** — v5/v7 문서가 없으면 새 live runner가 읽을 attested
    input 자체가 없다(사용자 결정 2026-08-20으로 주요 개발 완료 후로 미뤘다).
    후보 Live UI recovery와 `blocked → ready` stream/replay/reconciliation 결박은 통과했다. 최종 prod
    gate는 별도 final main C7·production consumer enable 경계이며, PinVi system별 snapshot concurrency 1,
    `429/503 Retry-After` backoff, `413` non-retry, credential별 gateway limit 또는 동등한 외부 rate-limit과
    실제 호출 cadence를 함께 증명한다.

### T-VN-41F1J — C6c cancel-probe fixture 수명주기 복구

> 2026-08-06 F1D의 `cancel=404`는 Manager/PinVi read·cancel relay 문제가 아니라, 정적
> `KTDM_C6C_CANCEL_PROBE_JOB_ID`에 대응하는 Map import job이 없다는 실측으로 판정했다.
> fixture 생성·소비·종결과 durable 상태는 Map이 소유하고, Manager는 service OpenAPI로
> transaction ID만 전달한다. PinVi에는 기존 `ops:cancel` 외 권한을 주지 않는다(ADR-084).

- [~] **T-VN-41F1D-D1 — 최종 격리 리허설·provenance attestation** *(공동, docs-only)*

  > **착수 보류 (사용자 결정 2026-08-20)**: 파괴적 rebuild는 모든 주요 개발이 끝난 뒤에
  > 실행한다. 실행 시점·선행조건은 `T-VN-FINAL-REBUILD`가 소유한다.

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

  > D1을 따라 `T-VN-FINAL-REBUILD` 뒤로 밀린다(사용자 결정 2026-08-20).

  비어 있는 새 DB에서 **고정 curated/feature ID를 요구하는** admin live UI·PinVi mutating E2E를
  재실행한다. D1이 적재한 final-schema 데이터 위에서 돈다.

  **선행: T-VN-40 완료**(사용자 판단 2026-08-08). T-VN-40B가 admin/public/PinVi consumer를
  `curation_collections/items` 정본만 읽도록 전환하므로, 그 전에 이 suite를 돌리면 증거가
  T-VN-40 머지 즉시 낡는다. 이 acceptance의 비용은 파괴적 rebuild + 전량 ETL 재적재 + 일곱
  image attestation이라 두 번 돌릴 값이 아니다. 반대로 D1은 curation read 경로와 무관하고
  "rebuild-from-scratch가 실제로 되는가"를 보증하므로 join barrier까지 비워두지 않는다.

- [~] **T-VN-41F1D-E — v4 compatible-pair live runner 퇴역·v5/v7 attestation 전환**

  > 2026-08-20 — **저장소측(unit·script contract) 완료**. 남은 것은 F1D-D 순서를 따르는
  > n150 data-dependent 실행뿐이다. `E2E_C7_COMPATIBLE_PAIR_MANIFEST`가
  > `E2E_C7_PINNED_RUNTIME_MANIFEST` + `E2E_C7_REBUILD_JOURNAL`로 바뀌었고, runtime role은
  > 다섯에서 **일곱**으로(PinVi web/dagster 추가), host attestation은 version 3 → 4로,
  > 세 schema head와 pinset이 generation 값과 exact 대조된다. journal은 phase
  > `committed` + candidate 전체 동등 + cancel probe `finalized`를 요구한다. v4를 억지로
  > 넣어 통과하는 경로는 만들지 않았고, runner 계약 테스트가 v4 env 부재를 단언한다.
  > 변이 8종(phase/candidate/cancel probe/schema head/journal digest/pinset/image 대조/
  > manifest version)이 전부 red임을 실측했다. 실행 전제: v5/v7은
  > `require_rebuildable_mode`가 걸려 rehearsal/rebuildable에서만 생성된다(n150은 해당).
  > **2026-08-20 정정**: 앞서 "n150에 두 파일이 없다"고 적었으나 틀렸다. `digitie` 홈만
  > 봤고 실제로는 **root 홈**(`/root/.local/state/kor-travel-docker-manager/…`)에
  > `pinned-runtime-generation-v5.json`·`pinned-runtime-rebuild-v7-93dd4ac0….json`이
  > root:root `0600`으로 실재한다 — runner의 소유권 요구는 이미 만족한다. 다만 그
  > generation은 `map_application_head=0087_route_area_subtypes`인 2026-08-06 리허설
  > 세대라 현 prod head `0225`와 exact 대조에서 red다. **재사용할 수 없을 뿐 없는 것이
  > 아니다.** 현 세대 문서는 D1의 파괴적 rebuild가 만든다.

  `run-c7-prod-live-e2e.sh`와 `run-admin-feature-live-acceptance.sh`가 요구하는 v4
  `E2E_C7_COMPATIBLE_PAIR_MANIFEST`를 제거한다. root-owned snapshot은 v5
  `PinnedRuntimeManifest.active_generation`, 일곱 immutable image·Map/PinVi revision·세 schema
  head·pinset을 확인하고 v7 journal/host attestation과 함께 발행한다. v4 manifest를 억지 입력해
  통과하는 compatibility 경로는 만들지 않는다. final schema merge/재적재와 독립적으로 unit·script
  contract까지 완료하고, 실제 n150 data-dependent 실행은 위 F1D-D 순서를 따른다
  (그 순서는 `T-VN-FINAL-REBUILD` 배리어 뒤에 열린다).

### T-VN-FINAL-REBUILD — 주요 개발 완료 후 파괴적 재구축 배리어 (2026-08-20 신설)

> **사용자 결정 2026-08-20**: `T-VN-41F1D-D1`의 파괴적 rebuild는 **모든 주요 개발이 끝난 뒤에**
> 실행한다. 그 실행 시점과 선행조건을 이 task가 소유하고, D1/D2와 F1D-E의 live 실행은 여기에
> 매단다.

- [ ] **T-VN-FINAL-REBUILD — 파괴적 재구축 + 전량 재적재 배리어**

  `ktdctl pinvi-pair rebuild-pinned --confirm`은 Map application·Map Dagster·PinVi **세 DB를
  파기형으로 재생성**하고 일곱 runtime을 고정 candidate로 재기동한 뒤 v5
  `pinned-runtime-generation-v5.json`과 v7 `pinned-runtime-rebuild-v7-<pinset>.json`을 남긴다.
  이어서 final schema 위로 provider source·ETL을 전량 재적재한다.

  **왜 미루는가.** v5 generation은 Map/PinVi source revision과 일곱 image ID에 결박된다. 개발이
  계속되는 동안 실행하면 (a) 다음 머지 즉시 세대가 낡아 attestation 증거가 무효가 되고,
  (b) 전량 재적재 비용을 그때마다 다시 낸다. 이 acceptance는 두 번 돌릴 값이 아니다.

  **배리어 해제 조건 (전부 참이어야 착수).** "주요 개발 완료"를 사람 판단에 맡기지 않고
  아래 셋으로 판정한다 — 셋 다 "세대를 낡게 만드는 변경"의 정의다.
  - [ ] B1. **migration head를 올리는 열린 task가 없다.** 현재 걸려 있는 것은
    `T-VN-41C`의 cross-repo exact-pair 재검증, `T-VN-M01`~`M05` 중 DB를 바꾸는 것,
    `T-VN-C05A`~`C05D`(provider dataset 신설), `T-VN-39`(최종 cutover).
  - [ ] B2. **service/user OpenAPI 정본을 바꾸는 열린 task가 없다.** PinVi exact vendor가
    재-vendor를 요구하는 변경이 남아 있으면 pair가 다시 어긋난다.
  - [ ] B3. **일곱 image 중 하나라도 바꾸는 열린 task가 없다** (Map API/UI/Dagster web·daemon,
    PinVi API/web/dagster). frontend·Dockerfile·의존 pin 변경 포함.

  **선행 준비.**
  - [ ] 세 DB의 백업/복구점 확보. 파기형이므로 되돌리기는 백업뿐이다(`ktdctl db-backup create`).
  - [ ] n150 디스크 여유 — 일곱 image 재빌드 분. 2026-08-20 기준 101G free(78%)이고
    dangling volume 52GB·구 playwright image 약 43GB가 추가 회수 가능하다.
  - [ ] 고정 release candidate(Map/PinVi 커밋과 일곱 image)를 먼저 확정한다.

  **이 배리어가 푸는 것 (순서대로).**
  1. **현 세대 기준의** v5/v7 문서가 생긴다. (2026-08-20 정정 — 앞선 "두 파일 모두 부재"는
     틀렸다. `digitie` 홈만 봤고 실제로는 **root 홈**에 있다:
     `/root/.local/state/kor-travel-docker-manager/kor-travel-docker-manager/`에
     `pinned-runtime-generation-v5.json`과 `pinned-runtime-rebuild-v7-93dd4ac0….json`이
     root:root `0600`으로 실재한다.) 다만 그 generation은
     `map_application_head=0087_route_area_subtypes`인 2026-08-06 리허설 세대라 현 prod
     head `0225`와 exact 대조에서 red다 — **재사용할 수 없을 뿐 없는 것이 아니다.**
  2. `T-VN-41F1D-D1` — 일곱 image·세 schema head·pinset attestation과 데이터 비의존 UI smoke.
  3. `T-VN-41F1D-E`의 n150 data-dependent 실행(저장소측 계약은 2026-08-20 완료).
  4. `T-VN-41F1D-D2` — 고정 ID를 요구하는 admin/PinVi mutating live E2E.
  5. `T-VN-41C` receipt `pending → candidate_verified` → 최종 prod gate·production
     consumer enable.

  **실행 전제.** v5/v7은 `require_rebuildable_mode` 아래에서만 생성된다(n150은
  `rehearsal`/`rebuildable`이라 해당). ktdm의 state root는 Manager owner 소유 `0700`이라
  runner가 요구하는 root 소유 `0600`을 그대로 만족하지 않으므로, 두 문서의 root 소유 사본을
  만들어 `E2E_C7_PINNED_RUNTIME_MANIFEST`/`E2E_C7_REBUILD_JOURNAL`로 넘긴다(runbook 참조).

## Wave 2 상세 — 구조 전환

> 실행 순서는 31A~C(freeze) → 32~38(shadow, 두 lane 병렬) → 40 → 39(cutover 마지막)다.
> ADR-066~075가 목표 스펙 정본이다. 각 migration task는 forward-only 격리 clone에서 검증하고,
> 명시적 downgrade 수용 조건이 없는 한 전진 뒤 rollback하지 않는다.

### T-VN-37D — notice empty range 표현 (완료)

> 계보 key 물화·인덱스 probe(`T-VN-37`, PR #968)는 완료 이력으로
> [`tasks-done.md`](tasks-done.md)에 옮겼다. 이 후속은 ADR-095에서 제품 의미를
> 확정하고 구현했다.

- [x] T-VN-37D — **empty range 표현**

  provider가 미래 시행 공지를 철회하면 `end < start`가 실재한다(실측
  `start=2026-07-13/end=2026-06-02`). 결함이 아니라 "발효 전에 철회됨"이고, 35B가
  CHECK를 두지 않은 이유다. `feature_notices.valid_during` generated column이
  정상 범위는 `[start, end)`, 발효 전 철회는 `empty`로 표현한다. 모든 notice
  유형의 미래 발효 공지는 계속 노출하고, active read는 기존 `valid_end_time`
  술어를 유지한다(ADR-095, migration `0232_tvn37d_notice_empty_range`).

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
2. **외부 consumer의 Feature 생성 요청도 같은 API를 쓴다.** PinVi를 포함한 consumer는 직접 만들지 않고 **요청**하며
   admin이 승인한다.
3. **curated Feature를 추가할 때 대상 Feature가 없으면** 이 API로 Feature를 만들고
   curation에도 함께 넣는다.
4. **origin(누가 만들었나)을 구분해 보존한다** — admin 직접 / 외부 요청 승인 / curation
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
- **Feature 생성 요청(M04)은 별도 경로다.** 첫 consumer인 PinVi main의
  `feature_requests.py:254`가 `admin_client.create_feature(payload)`로 **`POST /v1/admin/features`**를
  친다(`kor_travel_map_admin.py:3` — "`/v1/admin/features*` change API"). cache-target을 만지지
  않는다(`grep cache_target` 0건). 즉 M04는 41의 outbox를 타지 않고 admin API를 탄다.

**간접 접점 하나 — 미결.** 수동 Feature가 만들어진 뒤 PinVi가 그것을 POI로 **링크**하려면
cache-target 경로를 탄다. 그때 41C의 outbox가 그 링크를 전파한다. 이건 41의 정상 동작이지
H34가 41을 바꾸는 것이 아니다. 다만 **origin이 `manual_*`인 Feature를 41의 reconciliation이
provider Feature와 다르게 취급해야 하는지**(예: provider 재적재로 사라질 수 있는 Feature와
달리 수동 Feature는 restore epoch에서 어떻게 보이나)는 M02(origin 불변)와 41A(restore epoch)를
함께 볼 때 정해야 한다. **`T-VN-41A`/`T-VN-41B`는 PR #975(merge `4672aa96`)로 완료돼
[`tasks-done.md`](tasks-done.md)로 이관됐다** — 따라서 이 항목은 대기가 아니라 **M02 설계의
입력**이다. restore epoch 계약과 ADR-093을 직접 읽어 판정한다.

#### 아직 안 정해진 것

> **2026-08-20 정리**: 아래 7건 중 5건은 ADR-093(proposed, 2026-08-19)과 M04가 이미 닫았다 —
> `source_type=user_request`·`source_natural_key=manual::<uuid>`와 identity claim(§1),
> 초기 3축 상태 제거·좌표 required(§4), command isolation `read-committed`(§5), 범용 Feature
> 요청 큐의 immutable submit·admin resolve 분리(M04)다. 닫힌 것을 "미정"으로 두면 같은 논의를
> 다시 하게 되므로 지웠다. 남은 것은 둘이다.
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
→ **M01은 origin을 `manual_admin` 단일 값으로만 발급한다.** `manual_request`/`manual_curation`은
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

**M00 해소 정본**: 위 finding은
[`T-VN-M00 설계 보고서`](reports/t-vn-m00-manual-feature-create-design-2026-08-19.md)와
proposed ADR-093에서 닫았고, exact checkpoint `2aa17c27`에 API·DB 전문 리뷰 P0~P3 0건 GO를
받았다. 완료 이력은 [`tasks-done.md`](tasks-done.md)가 소유하며 다음 실행 단위는 M01이다.

#### 후속 task

- [~] **T-VN-M01 — admin Feature 생성 API clean cutover** (결정 1, 구현 진행). 이미 존재하는
  `POST /v1/admin/features`를 서버 발급 UUIDv7, exact identity claim, `manual_admin` 단일 origin,
  고정 initial state와 admin BFF 전용 인증 경계로 교정한다. **ADR-093 필요**.
  Map PR #1016은 `14792385`로 병합되어 API/ORM foundation, Admin UI BFF/form/generated types와
  runtime raw/digest 격리를 main에 반영했다. PinVi direct-create fail-close는 별도 paired PR
  [#458](https://github.com/digitie/pinvi/pull/458)의 cross-repo 경계로 추적한다.
  T-VN-34C 격리 fresh-live runner도 #1028(`021b20fc`)에서 raw UI token·API digest·off flag를 생성하고
  `docker-compose.yml`의 모든 `:?` 필수 환경변수와의 집합 차이를 테스트하도록 보강했다.
  이 보강은 runner preflight만 닫은 것이며 route flag는 계속 false다. DB/ACL/backup tranche는
  `0226_m01_manual_feature_create`로만 잇고 실제 활성화·완료 이관은 그 검증 뒤에 한다.
- [ ] **T-VN-M02 — origin 보존과 불변** (결정 4). origin/claim read model과 Feature 수정·purge,
  backup/restore에서의 불변을 스키마·테스트로 고정한다. `manual_request`/`manual_curation` 값은 각
  인증 writer가 생기는 M04/M03 전에는 등록하지 않는다.
- [ ] **T-VN-M03 — curated 동시 생성** (결정 3). curation import/admin 편집에서 대상 Feature가
  없을 때 M01을 호출해 만들고 `curation_items`에 잇는다. **T-VN-40의 write model과 같은
  표면**이라 그 인수 뒤에 얹는다.
- [ ] **T-VN-M04 — 범용 Feature 요청 큐** (결정 2). 외부 consumer가 HTTP로 요청하고 admin이 승인한다. 승인
  시 Map이 Feature를 만들고 origin을 `manual_request`로 남긴다. PinVi는 첫 consumer이며 cross-repo 계약은
  `docs/integration-map.md`에도 추가한다.
- [~] **T-VN-M05 — provider 발행 시 중복 판정** (결정 4 후단). 수동 Feature와 같은 실체를
  provider가 발행하면 dedup 후보로 올리고 **자동 병합하지 않는다.** admin이 병합/유지/수동본
  폐기를 고른다. 2026-08-21 사용자 선택은 paired cutover이며, ADR-097과
  `t-vn-m05-manual-provider-dedup-design-2026-08-21.md`가 immutable evidence·service event/ack·첫
  consumer rebind 계약을 소유한다.
