# tasks-done.md — 완료/아카이브 task 이력

> 완료(`[x]`)·폐기·머지 history 아카이브. **진행 중/예정 task는 [`docs/tasks.md`](tasks.md)**.
> (2026-06-09 분리 — tasks.md 길이 축소. 분리 기준: 열린 `[ ]` 항목이 없는 섹션·Phase는 여기로.)

## 2026-07-30 — Lane B b0 T-VN-49A/B/C/D React 구조 debt 완결

사용자 지시에 따라 네 단계는 브랜치와 PR을 나누지 않고 한 번에 구현·검증했다. 이 완료
아카이브도 H49 코드와 같은 merge commit으로만 `main`에 들어간다.

- [x] **T-VN-49A — Feature·review admin 상태기계 분해**

  dedup/enrichment/admin features/change requests/new feature를 query·mutation·form·panel
  책임으로 나눴다. dedup/new feature의 결합 상태는 reducer로 옮겼다.

- [x] **T-VN-49B — admin data-ops 상태기계 분해**

  curation collections/files/issues/offline uploads/POI cache targets를 분해하고 issues의
  결합 상태를 reducer로 옮겼다. offline upload form은 파일·form·create mutation을 직접
  소유해 상위 controller의 거대 prop 전달을 제거했다.

- [x] **T-VN-49C — public map·home 분해**

  curated feature map/features map/home에서 domain state와 표현 section을 분리했다.
  지도 adapter나 단순 전달 wrapper를 새로 만들지 않았다.

- [x] **T-VN-49D — ops pipeline·datasets 분해와 구조 예외 제거**

  datasets/logs/execution detail/timeline/request/schedule을 분해했다. request dialog는
  scope·target·execution form 경계와 좁은 memoized section으로 재구성했고 render 중
  상태 변경을 파생 상태로 대체했다. `no-giant-component` 19개와
  `prefer-useReducer` 3개 exact 예외는 모두 제거했다. 실제 transport lifecycle인
  `live.ts`와 외부 event effect인 datasets의 규칙별 최소 예외만 남겼으며 verifier가
  그 exact 목록을 고정한다.

적대 리뷰어 2명이 authored 전체 delta를 검토했다. 늦은 geocode/reverse 응답이 최신 입력을
덮는 문제, reset 뒤 stale 응답 재유입, request/offline-upload의 flat prop-bag 우회,
enrichment callback identity churn을 찾아 모두 수정했고 전체 재검토 P0~P2는 0건이다.
지연 geocode가 사용자가 나중에 바꾼 도로명 코드를 보존하는 Playwright 회귀도 추가했다.

검증은 React Doctor **280 files, 0 issues**, Vitest **254 passed**, TypeScript·ESLint·production
build green이다. Mocked checkpoint D는 serial과 workers=4에서 각각 **275/275**, expected/
actual failure·flake·skip과 종료 자원 모두 0이다. 보존 clone을 새로 복제하거나 복원하지 않고
`ktm-tvn45-db`를 재사용한 파괴적 Live UI는 main/recovery 각각 **2/2**, `complete/passed`다.
active acceptance Feature·nonterminal request·FK와 runner container/network/image/listener/
BLOCKED는 모두 0이고 clone은 healthy다. 기존 v5 checkpoint가 정상 soft-delete audit 6행
때문에 더는 exact하지 않아 현 상태로 baseline만 다시 서명했으며 Alembic downgrade와 full
restore는 실행하지 않았다.

## 2026-07-30 — Lane A a1 T-VN-H30A/H33/H36: curation 오링크 해소와 자동링크 금지

PR #888(H30A) · PR #890(H33/H36). 세 task 모두 적대 리뷰로 **결론이 되돌아간** 이력이
본문에 남아 있다 — 특히 H33은 `[x]` → `[~]` → `[x]`로 두 번 움직였고, 그 원인이
"측정 도구의 산물을 데이터의 성질로 읽은 것"이었다. 그 기록을 지우지 않고 옮긴다.

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

- [x] T-VN-H33 — **curation_items 오링크 3건 정리 (H25B 파생)**

  **`[x]` → `[~]` → `[x]`로 두 번 움직였다.** 처음 닫은 근거("import가 재링크하지 않는다")가
  적대 리뷰 실측으로 반증돼 되돌렸고(아래 "철회"), `T-VN-H36`이 그 재링크 경로를 실제로
  막은 뒤에야 닫았다. **지금 닫는 근거는 "안 될 것이다"가 아니라 "막았고 측정했다"다** —
  `T-VN-H36`이 커밋 CSV 486행 전수 재생으로 이 3건이 자동 링크 대상에서 빠지는 것을
  확인했다(`reports/h36-link-impact-2026-07-29.json`).

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

- [x] T-VN-H36 — **curation import가 이름만으로 자동 링크한다 (H33 파생, H35보다 선행)**

  **완료(2026-07-29)**. `_adopted_match`로 **CSV `feature_id`가 빈 행은 후보 수와 무관하게
  링크하지 않는다**. 후보는 버리지 않고 `candidates`로 계속 노출하므로 운영자가 preview에서
  보고 admin에서 직접 링크할 수 있다 — 자동으로 붙는 것만 없앴다.

  **AC 결과**

  | AC | 결과 |
  | --- | --- |
  | H33의 3건이 import 후에도 미연결 | ✅ 막히는 자동링크가 **정확히 그 3건** |
  | 정당한 링크 손실 수치 | ✅ **0건**. 막히는 3건 전부 region 불일치(강원→서울 ×2, 충북→전남) |
  | 미연결 사유 구분 | ✅ `unmatched`(후보 없음) vs `name_only_match`(이름만 맞는 후보 있음). 사유 문장에 후보 소재 시도명이 들어간다 |
  | e2e 기대값 | ✅ 486 불변 — `item_count`가 미연결 item도 세므로(실측) 링크가 줄어도 membership은 안 바뀐다. 기대값 갱신 불필요 |
  | 반증 가능성 | ✅ 아래 |
  | 배포 순서 | ✅ **H35 이미지에 반드시 포함**. 아래 |

  근거 산출물: [`reports/h36-link-impact-2026-07-29.json`](reports/h36-link-impact-2026-07-29.json)
  (`scripts/h36_link_impact.py`, 커밋 CSV 486행 전수 + prod 리졸버 SQL 재생, 읽기 전용).
  빈 264행의 후보 분포는 **0건 256 / 2건 이상 5 / 1건 3**이다.

  **반증 가능성** — 이 세션에서 반복해 무너진 지점이라 명시한다.
  - 변경이 아무것도 안 막았다면 `blocked_autolinks`가 0으로 나온다.
  - 링크를 통째로 껐다면 `csv_specified`(222)가 0이 된다 — 이 값은 리졸버가 아니라
    **CSV 파일**에서 오므로 두 숫자가 같이 움직이지 않는다.
  - 리졸버 조회가 죽었다면 후보 분포가 전부 0이 된다.
  - 테스트에도 대조를 넣었다: **음성 대조**(후보 0건은 여전히 `unmatched` — 리졸버가 통째로
    죽은 것과 구분), **양성 대조**(CSV가 `feature_id`를 적은 행은 그대로 링크 — "링크 기능을
    껐다"면 실패). 대조 없이 "전부 미연결"만 보면 성공과 고장이 구별되지 않는다.

  **배포 순서 — 이 변경은 `T-VN-H35` 이미지에 포함돼야 한다.**
  H35의 인수에는 commit 모드 import 실행이 들어간다(live spec의 `palaceComponents`
  단언은 `0066` backfill이 `legacy:<uuid>`로 채우는 값을 실제 import로 덮어야 성립한다).
  그 실행 시점에 이 게이트가 이미지에 없으면 3건이 그 자리에서 되살아난다.

  **표면 비용 0** — SQL·DTO·openapi·마이그레이션 무변경. `code`는 openapi에서 자유
  문자열(`CurationImportIssueView.code: str`)이라 새 코드를 늘려도 생성 타입·프런트
  수기 union·배지 맵이 안 바뀐다. `ImportRowStatus`(enum) 확장은 그 5지점 연쇄를 부르므로
  **일부러 피했다**. 후보 시도명은 `FeatureMatch.address` jsonb에 이미 있어(리졸버가 이미
  SELECT한다) 리졸버 SQL을 넓히지 않았다.
  기존 테스트 **23건 무손상**(27 passed) — 라우터 import 테스트 중 비어 있지 않은 후보를
  돌려주는 것은 하나뿐이고 그건 `feature_id` 명시 경로다.

  <details><summary>원래 정의 (완료 전)</summary>

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

  **AC**
  - [ ] 이름 단독 일치만으로는 자동 링크되지 않는다. H33이 끊은 3건이 import 후에도
        미연결로 남는 것을 **실데이터로** 확인한다(preview 경로로, prod 쓰기 없이).
  - [ ] 정당한 링크를 과도하게 잃지 않는다 — 현재 링크 222건 중 이 변경으로
        재현되지 않는 건이 몇 건인지 **수치로** 제시한다. 0이 아니어도 되지만 밝혀야 한다.
  - [ ] 자동 링크되지 않은 행에 **왜**가 남는다(import 리포트 issue 또는 metadata).
        운영자가 "그냥 안 붙었다"와 "지역이 어긋나 막았다"를 구분할 수 있어야 한다.
  - [ ] e2e 라이브 기대값(공식 19컬렉션 membership 486, `OFFICIAL_FILES` 행 수)에 대한
        영향을 밝힌다. 바뀐다면 기대값도 같은 PR에서 갱신한다.
  - [ ] 검증이 **반증 가능**하다 — 변경이 실패했다면 다른 결과가 나오는 측정인지
        (negative control / 양성 대조) 명시한다. 이 세션에서 반복된 실수다.
  - [ ] 배포 순서: prod가 `0063`/이미지 `c8ed6164`라는 사실이 이 변경의 적용 순서에
        미치는 영향을 기록하고, H35와의 선후를 확정한다.

  **비목표**: 미연결 264건을 사람이 링크하는 작업 자체(그건 `T-VN-H34`/`T-VN-H31`).
  여기서는 **잘못 붙는 것을 막는 것**까지만 한다.

  </details>

  > **부수 정정 — "prod는 import 자체가 실패한다"는 틀렸다.** H33 작업 중 나는
  > *prod가 `0063`이라 HEAD의 import SQL이 참조하는 컬럼이 없어 import가 실패하므로 3건이
  > 당장 되살아나지는 않는다*고 적었다. 조사 결과 **배포된 이미지(`c8ed6164`)의 import
  > 코드에는 `source_present`/`external_component_id` 참조가 0건**이라 prod 스키마와
  > 정합하며 **오늘도 정상 동작한다**. 또 CSV import는 `_UPSERT_ITEM_SQL`이 아니라
  > `_BULK_UPSERT_ITEMS_SQL`을 탄다(전자는 admin 단건 POST 전용). 즉 "HEAD 코드를 prod
  > 스키마에 돌리면 실패한다"가 참일 뿐, 내가 그걸 "prod에서 import가 실패한다"로 옮겨
  > 적은 것이다. **또 배포되지 않은 코드를 prod 동작으로 읽었다.**

## 2026-07-29 — Lane B b0 T-VN-48 mocked drift·격리 clone Live 완료

- [x] **T-VN-48A~C** — 최초 273-test baseline의 deterministic drift 89건을
  Feature·검토 15건, ops 5건, auth/shell 69건으로 고정하고 단계별로 제거했다.
- [x] **T-VN-48D** — checkpoint D를 exact `823ba52b`에서 serial과 workers=4로 각각
  **274/274** 통과했다. expected/actual failure·flake·skip은 모두 0이고, 종료 뒤 self-owned
  container/network/image와 loopback listener도 0건이다.
  - [x] **D.1~D.3** — restore 전용 owner를 정규화하되 원본 owner invariant는 별도 검증하고,
    fail-closed dump를 정확히 하나일 때만 재사용하며, PostGIS `extconfig` OID를 안정적인
    schema+relation identity로 바꿨다. 실제 schema-only restore에서 extension digest
    동등성을 확인했다.
  - [x] **D.4** — 경량 v5 baseline과 선택적 full restore certification을 분리했다. v5는
    custom archive 구조·dump SHA256·clone snapshot·write fence를 서명하고
    `full_restore_verified=false`를 명시한다. 이번 최종 gate는 migration/schema/복구 계약이
    바뀌지 않아 이미 보유한 dump와 clone을 재사용하고 전체 restore를 반복하지 않았다.
  - [x] **D.5~D.6** — Feature 승인으로 정상 증가한
    `ops.ops_live_topic_revisions.dataset_projection` 한 행을 시작값으로 정규화하되,
    서명 dump의 직전 행을 대입한 전체 digest가 checkpoint와 정확히 같고 revision이 `+1`인
    경우만 허용했다. `direct-cleanup-running → recovery-resource-finalizing`의 정확한
    forward-recovery만 인정해 UI·fixture를 반복하지 않고 기존 evidence에서 완료했다.
  - [x] **D.7** — production MapLibre의 늦은 실제 `idle` event가 raster `sourcedata`
    계측에 섞이던 Mocked race를 repaint+idle+rAF barrier로 제거했다. 최초 serial은 이 한 건만
    실패한 273/274였고, 실패 spec 수정 뒤 같은 gate를 재개해 serial/parallel 모두 통과했다.
  - [x] **D.8** — PR CI가 `record_address_validation_findings()`의 typed
    `IntegrityFindingSyncResult` 계약과 Dagster asset 테스트 double 12개의 구 `int` 반환
    drift를 세 Python 버전에서 공통 검출했다. 모든 double을 실제 결과 타입으로 맞추고 Dagster
    package 전체 **510 passed, 1 skipped**, coverage **83.66%**와 Ruff를 통과했다.
- [x] **파괴적 Live** — 보존 clone의 본 acceptance와 recovery-only가 각각 **2/2**다.
  result는 `complete/recovered`, raw→normalized 전체 content 증명과 topic revision `+1`을
  기록했다. active acceptance Feature·pending change request·direct weather/price/FK,
  BLOCKED/quiescence/scratch/temp DB·role, runner container/network/image는 전부 0이다.
  v5 custom dump는 다음 task 재사용 판정 대상으로 보존했다.
- [x] **리뷰·감사** — branch-authored delta는 적대 리뷰 2인과 국소 후속 검토에서 P0~P2
  0건이며, 규칙 변경 전에 완료한 issue #881의 Claude Code PR #888 사후 감사 수정도 같은
  변경 집합에 포함했다.

## 2026-07-29 — Lane A a1 T-VN-H28A/B: #673 주소 검증 규칙 교체 (한 PR)

> **정정 (적대 리뷰 반영)** — 아래 "payload 행정코드 == geo 행정코드이므로 전부 오탐"이라는
> 근거는 **무효**다. concierge의 payload 코드는 같은 kor-travel-geo /v2/reverse를 같은 좌표로
> 호출한 캐시본이라 자기 자신과의 비교였다. 결론(380건 좌표 오류 아님)은 유지되지만 근거는
> 독립 축(provider 원천 텍스트 + 정지오코딩)으로 다시 세웠다 — 375건은 텍스트에 행정구역
> 토큰이 없어 좌표와 무관하게 통과 불가, 4건은 축약·단계 차이, 1건은 143 m 경계.
> 이름 축은 **삭제하지 않고** 결함만 고쳐 warning으로 유지한다(전 provider 적용).
> 상세: docs/reports/concierge-address-mismatch-evidence-2026-07-29.md

- [x] **T-VN-H28A** — 운영과 동일한 코드 경로(live concierge export → 실 geo reverse 주입 변환
  → `validate_feature_bundles_address`)로 재기준화했다. 증거:
  [`reports/concierge-address-mismatch-evidence-2026-07-29.md`](reports/concierge-address-mismatch-evidence-2026-07-29.md).
  - 1,430/410 → **1,477/380** (현상 유효).
  - drop 380건이 **전부 오탐**: payload 시군구코드 == geo 시군구코드 380/380. 진짜 불일치 **0건**.
    후보 전체(1,477)로 넓혀도 코드 불일치 0건.
  - 380/380이 payload에 시군구·법정동 코드를 **모두** 보유 — 권위 축이 있는데 규칙이 안 썼다.
  - 실패의 365/380은 `부산 기장 조방국밥`처럼 **행정구역명이 없는 짧은 주소**. 규칙이 잰 것은
    좌표-주소 일치가 아니라 provider 주소 문자열의 완전성이었다.
  - reverse 최근접 거리 `<10m` 210 / `<100m` 136 / `<1km` 34 — 좌표는 정확했다.
- [x] **T-VN-H28B** — 이름 축을 판정에서 제거하고 행정코드 교차검증으로 교체했다.
  - `AdminEvidence`(신규 DTO): 판정 두 축(좌표 reverse 코드 / payload 선언 코드)을 `Address`로
    **병합하기 전에** 보존한다. 병합 후에는 출처를 알 수 없어 교차검증이 원천 불가능했다.
  - 규칙: 코드 대 코드 접두 비교. 두 축이 모두 있을 때만 판정하고 없으면 **'통과'가 아니라
    '증거 없음'**으로 집계(`evidence_grade`). 리(8:10)는 `_bjd_code_from_emd_code`가 합성할 수
    있어 비교하지 않는다(8자리 캡).
  - **drop을 severity가 아니라 code allowlist로 전환**. 새 error 규칙이 추가돼도
    `DROPPABLE_ISSUE_CODES`를 명시적으로 고치기 전에는 영구 손실이 구조적으로 불가능하다.
    (`provider_address_mismatch`가 바로 그 방식으로 380건을 조용히 파괴했다.)
  - **batch 전멸 위험 제거**: payload에 `sigungu_code`만 있고 `legal_dong_code`가 없으면
    `Address._check_code_consistency`가 `ValidationError`를 던져 **1건이 1,477건 전체를**
    죽일 수 있었다(건별 격리 없음). `_address()`가 bjd에서만 유도하도록 바꿔 구조적으로
    불가능하게 하고, 건별 격리 옵션도 추가했다.
  - **회복 검증(live)**: 같은 export를 새 코드로 → **380 drop → 0, 1,477/1,477 적재, 손실 0.**
    교차검증 성립 1,372/1,477(92%), 행정코드 불일치 0건.
  - **replay 장치는 만들지 않았다** — 코드로 확인한 결과 불필요하다. drop은 적재 **전** 단계라
    dropped 후보는 `source_entities`에 행이 없고, concierge cursor는 영속화되지 않아 매
    materialize가 ledger 전량을 재생한다. 규칙만 고치면 자동 회복된다.
  - 검증: n150 CI-parity — ruff / mypy --strict(core 117·dagster 23) / dagster 494 passed +
    1 skipped / 관련 unit 179 passed. 신규 회귀 25건.
## 2026-07-29 — issue #881: Claude Code PR #882~#884 사후 감사

- [x] **PR #884 geo 인증·오류 계약 재감사** — backend가 VWorld public key를 URL query로
  계속 전송해 httpx INFO URL과 traceback frame에서 비밀이 노출될 수 있던 구조를 제거했다.
  Map API/Dagster/CLI는 geo public endpoint에 `X-KTG-API-Key` header만 사용하며
  credential은 `SecretStr`로 보관한다. admin trusted-proxy principal을 위임하지 않고
  transport/status 원본 예외도 연결하지 않는다.
- [x] **typed problem code 보존** — `GeoAuthNotConfiguredError`와 `GeoRequestError`가
  `/admin/issues`, offline-upload validation, feature-update HTTP adapter를 지나도 각각
  `GEO_AUTH_NOT_CONFIGURED`(503), `PROVIDER_ERROR`(502)로 유지되게 중앙 handler와 경계별
  problem+json 회귀 테스트를 추가했다.
- [x] **PR #882/#883 문서·계약 재감사** — PinVi가 읽지 않는
  `openapi-sha256.json`은 탐지력 없는 파생 산출물이므로 export/test/file을 제거했다.
  소비자 freshness는 실제 핀 commit의 spec/subset 비교만 정본으로 유지한다.
  완료된 H07C/H07D/H21/H29는 active backlog에서 제거하고 H27은 OPNsense 운영자 작업과
  quiet 2주기 검증 한 경로로만 정리했다.

## 2026-07-29 — Lane A a1 T-VN-H21: geo 인증 결선 검증·비밀 유출 차단

- [x] **T-VN-H21** — kor-travel-geo live 인증 결선을 검증 가능하게 만들고, 그 과정에서 드러난
  API key 유출 경로를 막았다. dedup 5건은 **브랜치 코드로** 실서비스에서 재통과(5 passed).
  후속 issue #881 감사에서 URL query 자체가 남긴 2차 유출 경로를 확인해 위 trusted proxy
  header 계약으로 교체했다. 아래는 PR #884 최초 landing 당시의 검증 이력이다.
  - 열린 질문이었던 "인증 뒤 runtime drift"는 **없음**으로 종결: 실 geo에 대해 reverse
    (status=OK, cand=11)·geocode(status=OK, conf=1.000) 응답이 기존 Pydantic 모델로 무손실
    파싱됐고, 배포된 Map api 컨테이너의 key가 geo 컨테이너 `KTG_VWORLD_API_KEY`와 동일함을 확인했다.
    → 원래 blocker는 배포 결선 결함이 아니라 **ad-hoc/CLI 실행 환경에 값이 없던 것**이었다.
  - **설계 전환(적대 리뷰 2명 합치)**: 호출 지점마다 preflight를 붙이는 최초 구현은 7곳 중 1곳만
    보호해 사실상 장식이었고, 이를 막으려 둔 AST 스캐너조차 같은 모듈 내 동명 변수 mutation으로
    우회됨이 **실제로 시연**됐다. `require_api_key` 기본 `True`로 **생성 시점** 검증에 옮겨
    CLI/API/Dagster/live test 4경로가 별도 조치 없이 보호된다(ADR-060 결과 절에 반영).
  - **오분류 수정**: 결선 누락을 `ValueError`로 던지면 기존 `except ValueError` 사다리에 걸려
    `/admin/issues`는 422, offline-upload는 409, feature-update는 422로 나갔다 — 없애려던
    좌표-vs-결선 오진을 API 안에서 재생산하는 상태였다. `GeoAuthNotConfiguredError` → 503
    (base_url 미설정과 동일 등급)으로 정정.
  - **비밀 유출 차단**: `str(httpx.HTTPStatusError)`가 `?key=<SECRET>` URL을 담고 그 문자열이
    502 detail·로그로 나갔다. query 제거한 `GeoRequestError`로 wrap. 회귀 테스트가 곧바로
    2차 결함을 잡아냄 — `from None`은 `__cause__`만 지우고 `__context__`에 원본이 남는다.
    except 블록 **밖에서** 던져 chaining 자체를 만들지 않게 고쳤고, 실 401 응답으로 확인했다.
  - 그 밖에: 128자 초과 key 사전 차단, CLI는 traceback(exit 1) 대신 stderr + `_EXIT_INVALID`(2),
    과장된 주석("요구한다" 무조건 / "route 처리 전에") 정정.
  - 검증: n150 CI-parity green — ruff / mypy --strict ×3(core·api·dagster) / lint-imports 4 kept,
    unit 1675 passed(잔여 3건은 main과 동일한 docker 바이너리 부재), api 792 passed,
    dagster 477 passed. live: 결선 차단·정상 좌표·오류 좌표·잘못된 키 4분기 + dedup 5 passed.

## 2026-07-29 — Lane A a1 T-VN-H29: 통합검색 map-import POI 좌표 null 복구

- [x] **T-VN-H29** (PinVi PR #418) — kor-travel-map curated import POI가 GET /search에서만 좌표
  null이던 실제 사용자 가시 버그를 고쳤다. 발견 경위는 T-VN-H07D 적대 리뷰의 소비자 전수 감사.
  - 근인: search.py::_snapshot_coord가 중첩 feature_snapshot["coord"]만 읽었는데, Map
    CuratedFeatureDetailFeatureSnapshotView는 extra=forbid이고 coord property가 아예 없어
    (H07D typed view) 좌표는 top-level lon/lat으로 온다 → 구조적으로 항상 None.
  - 비대칭이 힌트: 같은 payload를 admin_pois/kasi는 정상 해석해, admin·일출입 화면은 좌표가
    보이는데 통합검색만 null이었다.
  - 수정: 다섯 번째 추출기를 만들지 않고 정본 extract_feature_coord에 위임(기존 동작의 상위집합).
  - 회귀 위험 실증(리뷰어 2명): 비-map snapshot은 전부 중첩 coord이고 top-level
    x/y/geometry/location payload는 0건. 응답 계약도 기존 _coord/_float가 이미 처리. 같은 컬럼에
    admin/trips.py가 이미 같은 추출기를 써 표면 간 해석이 오히려 일치하게 됐다.
  - 리뷰 반영: 계약 게이트 주석·통합 문서의 "알려진 열화" 서술이 이 PR로 거짓이 되어 해소 기록으로
    정정. 커버리지도 배선(결과 dict→PlaceSearchResult.coord)·nullable lon/lat·0.0 좌표 보존까지 확장.
  - 검증: n150 CI-parity green(ruff/format/mypy), 신규 회귀 10 passed, 전체 unit 685 passed.

## 2026-07-29 — Lane A a0 T-VN-H07C: v5 승격 기각으로 종결 (a0 완료)

- [x] **T-VN-H07C** (#812) — 배포 compatible-pair에 pinned OpenAPI SHA를 넣는 v5 승격을 양
  저장소에 구현하고 테스트를 baseline까지 맞춘 뒤, 적대 리뷰 2명의 실증으로 **기각**했다
  (ADR-079). manifest는 v4 유지.
  - 근거 1: 제안 필드는 map_source_revision의 순수 함수라 추가 탐지력이 0이다. attestation은
    이미 그 revision을 운영자 제시 commit과 배포 이미지 OCI revision 라벨에 결박한다.
  - 근거 2: v5 전환 즉시 rollback이 무력화되고, 기존 프로덕션 이미지 revision에는 digest 파일
    blob이 없어 capture 자체가 불가능하다 — 운영자가 manifest 없는 상태에 갇힌다.
  - 유지: Map per-surface digest manifest(map#880, 207a6364)는 소비자 freshness 용도로 남는다.
    PinVi가 독립 사본과 대조하므로 그쪽에서는 실질 탐지력이 있다(H07B/H07D).
  - 폐기: docker-manager v5 브랜치, Map attestation v5 브랜치. 운영 문서·런북 무변경.
  - 규율 정정: OpenAPI 변경 완료 조건에서 재-capture/attestation 제거, per-surface digest 갱신 +
    소비자 스냅샷 재-vendor로 대체.

## 2026-07-28 — Lane A a0 T-VN-H07D: admin detail-snapshot 계약 + freshness 게이트 실효화

- [x] **T-VN-H07D** (#815 close) — cross-repo 2 PR. **① Map** PR #878(`5c0e0cae`), **② PinVi**
  PR #416(`8ea83358`).
  - **문제**: PinVi 큐레이션 import 런타임이 소비하는 admin detail-snapshot의 계약이 **OpenAPI로
    표현조차 되지 않았다**. PinVi가 읽는 plan-level 필드가 전부 free-form `dict[str, Any]`
    (`theme`/`content`/`source`/`feature_snapshot`) 안이라 스펙에 `{"type":"object"}`로만 나왔고,
    PinVi가 호출하는 경로는 `include_in_schema=False` 숨은 alias라 스펙 기반 게이트가 볼 수 없었다.
  - **① Map**: 생성부가 고정 key로 만드는 payload를 **typed view 4종**으로 전환.
    **etag는 repo payload dict 기준이라 그 dict을 손대지 않아 etag·캐시 계약 불변.**
    계약 게이트 9건(필드 핀 / 컨테이너 `$ref` 결합 / **alias 라우트 등록** / 생성부↔view 정합
    populated·all-null / **endpoint HTTP** 문서경로·alias × populated·all-null).
    `openapi.json` + frontend `types.ts` 동시 재생성.
  - **② PinVi**: 경로·응답 스키마의 **전이적 폐포 + securityScheme**만 결정적으로 추출한 subset
    (19 KB, full 1.1 MB 대비)을 vendor하고, 실제 소비 필드의 consumer 계약과 admin 인증 헤더
    header-only 계약을 고정. exact property 집합은 producer 소유라 중복 고정하지 않는다.
  - **freshness(핵심)**: 기존 live-compare는 sibling 체크아웃 부재로 skip되어 CI에서 항상
    green이었다. `contract-pin-consistency`(차단, `aggregate-ci.yml` required check 등록)가 Map을
    **핀 커밋**으로 체크아웃해 user는 byte, admin은 재추출로 **실제 비교**한다. 핀 자체의 뒤처짐은
    매일 도는 비차단 `contract-staleness`가 Map main과 비교해 알린다(H07B의 174-commit 사례).
  - **적대 리뷰 각 2명**. Map: 재생성 산출물 `types.ts` 누락(머지 blocker)과 `feature_snapshot`
    소비 여부 오판을 잡아 네 번째 typed view로 확장. PinVi: **"차단"이라던 job이 required check에
    없어 실제로는 아무것도 막지 못하던 것**을 잡아 실효화하고, job 이름을 증명 대상에 맞게
    `contract-pin-consistency`로 정정, `continue-on-error`가 죽이던 예약 알림 경로 복구,
    subset의 securityScheme 누락 보완, 계약상 불가능해진 e2e fixture 교정.
  - **검증**: 양쪽 n150 CI-parity green(Map api 790 passed / PinVi unit 675 passed),
    freshness 양쪽 실증, PinVi integration을 testcontainers로 실제 실행(1 passed),
    실제 CI에서 신규 게이트 pass(9s) 확인.
  - **파생 등록**: `T-VN-H29`(PinVi 통합검색의 map-import POI 좌표 null — `_snapshot_coord`가
    `coord`만 읽는데 Map view에 `coord`가 없어 구조적으로 항상 None).

## 2026-07-28 — Lane A a0 T-VN-H07B: PinVi consumer contract landing

- [x] **T-VN-H07B** — 오래 열린 PinVi #403(base 13 commits 뒤)을 재감사해 residual만 남기고
  **PinVi PR #415**로 landing했다(#403은 대체·종결). 재감사 핵심: #403은 Map producer 테스트를
  복사해 **공개 curated 표면**을 고정했으나 PinVi user client는 그 경로를 호출하지 않는다
  (`_CLIENT_PATHS`에 curated 없음, ADR-049/Map PR #533이 public `*-copy` 폐지, 큐레이션 런타임
  표면은 admin `/v1/admin/curated-features/{id}/detail-snapshot` = H07D 소유, producer exact
  고정은 H07A 소유). curated pin을 전량 제거하고 **PinVi가 실제로 읽는 필드**의 typed consumer
  contract(21 schema)로 대체했다.
  - **스냅샷 재동기화**: H07A의 실제 user OpenAPI SHA와 대조해 vendored 핀이 stale임을 확인
    (`91b30f40`@`cf1f0bba`, Map main보다 174 commits 뒤) → Map main `8880c29b`(H07A `259a9ec5`
    포함)/`0a7f1684`로 갱신. 실제 drift는 구조 1건(`external_component_id`, Map 0066) + 설명
    3건뿐이고 PinVi 소비 스키마는 구조 변화 0건.
  - **사슬 전체 고정**: 경로→컨테이너(`_ENDPOINT_DATA_SCHEMAS` 13경로 + `_CLIENT_PATHS` 일치
    가드) → 컨테이너→item(`items.$ref`)·map value(`found`→`FeatureDetailResponse`) → 필드
    type/format/enum/required/nullable. envelope `meta`(`Meta`/`ClusterMeta`/`PageMeta`)도
    client가 `data`로 re-projection해 소비하므로 함께 고정. `/v1/public/*`는 `model_validate`로
    객체 전체를 검증해 `app/schemas/public.py` `model_fields` ⊆ 계약을 강제(자기참조 검사 제거).
    `_SCHEMA_FIELDS`는 계약 표에서 파생. **exact property 집합은 의도적으로 비고정**(consumer가
    producer의 additive 변경에 false-red 나면 안 됨 — 0066이 실제 사례).
  - **검증**: n150 CI-parity clean clone `74b199d` — ruff/ruff format(343)/mypy --strict(196)
    green, 계약 11 passed, 전체 unit **665 passed**(base 661 대비 +4; 실패 20건은 base
    `417da20`에서 동일 실증된 기존 docker 의존 실패). **변이 테스트 30건 전부 검출**.
  - **리뷰**: 적대 2명 → 재리뷰 → 최종 확인(block) → 해제 확인(cleared). 최종 확인이 잡은 오기
    (`data.get("cluster_unit")`을 "항상 None인 잠재 버그"로 기록)를 정정 — client가
    `meta.cluster.cluster_unit`을 의도적으로 re-projection하며 기존 green 테스트가 non-None을
    단언한다. 같은 오독으로 빠졌던 meta 필드도 함께 고정했다.
  - PinVi 문서(`docs/integrations/kor-travel-map-rest-api.md` §8)는 같은 PR에 포함.

## 2026-07-28 — Lane B T-VN-46 npm optional tree 무결성 완결

- [x] **T-VN-46** — npm 10.9.4가 제외된 FreeBSD/WASM optional parent의 자식 6개를
  root `extraneous`로 남기는 Arborist 현상을 동일 lockfile에서 재현했다. npm 12.0.1과
  지원 Node 하한 22.22.2로 전환해 direct dependency 추가나 `npm ls` 출력 필터 없이
  `problems` 0건으로 만들고 기존 6-package allowlist를 제거했다.
- root `allowScripts`는 실제 install script가 필요한 `esbuild@0.28.1`과
  `unrs-resolver@1.12.2`만 exact version으로 허용한다. `.npmrc`의
  `strict-allow-scripts=true`와 `engine-strict=true`가 신규 script와 미지원 Node/npm을
  fail-close한다. workflow와 frontend/C7 Docker image도 같은 npm 12.0.1 계약을 사용한다.
- n150 clean install에서 audit 0, unreviewed install script 0, npm tree 0 problems,
  ESLint·React Doctor 0 diagnostics, Sharp SVG→WebP, admin/user OpenAPI codegen drift,
  두 type-check와 production build를 통과했다. npm 12 package-lock-only 재실행 drift도 0이다.
- 적대 리뷰어 2명이 exact 구현 head `378c6524`를 검토해 stale unit/doc, bare
  `allowScripts`, 과도하게 넓은 Node engine을 보강했고 최종 P0/P1/P2 0건을 확인했다.
- 재사용 실데이터 clone에서 candidate API/UI/C7 image로 파괴적 admin Feature acceptance를
  인증 setup 포함 **2/2, 37.9초** 통과했다. API-owned non-deleted Feature와 pending change
  request, weather/price fixture는 모두 0건이다. clone은
  `0066_curation_component_identity`, health 정상이고 다음 task 재사용 판정 전까지 보존한다.
  Playwright 상태/cookie·raw trace·screenshot·민감 로그·임시 env/session secret과 candidate
  container는 실행 직후 폐기했다.

## 2026-07-28 — Lane A a0 T-VN-H07A: Map #814 residual contract landing

- [x] **T-VN-H07A** — 오래 열린 Map #814(base 95 commits behind)를 최신 main 위 residual로
  재감사·landing했다(squash @ 259a9ec5). stale `docs/tasks.md` commit 2건과 main T-VN-05R가
  이미 소유한 union discriminator/mapping/oneOf 구조 assertion을 제거하고, main에 없는
  field-level 잔여만 남겼다: PinVi가 REST로 소비하는 curated feature variant 7·detail 5·
  PublicCuratedAddress·PublicCurationCollection/Item/CurationFeature/FeatureCurationGroup
  schema의 exact property/required 집합, 필드별 JSON type/format/enum/discriminator const/$ref
  대상을 생성 OpenAPI 기준으로 고정. n150 CI-parity가 base drift(migration 0066
  `external_component_id` required 추가)를 검출해 현행 계약으로 재조정했다. 적대적 리뷰어 2명
  (tautology·redundancy / contract-fidelity)이 전 schema를 실제 pydantic 생성 스키마·
  `openapi.user.json`과 대조해 land 판정했고, phones array element type 고정(nit)을 반영했다.
  n150 pytest 11 green + GitHub CI(lint/mypy/lint-imports·openapi-drift·pytest matrix·
  integration PostGIS) green. test-only OpenAPI 계약이라 admin-UI 표면 없음 — live 검증은 n150
  게이트가 실제 생성 OpenAPI에 대해 계약을 실행하는 것으로 갈음. PR #814.

## 2026-07-28 — PR #869 후 task 전면 재감사

- [x] **T-VN-REAUDIT-0728** — `tasks.md`·완료 이력·실코드와 Map/PinVi/
  docker-manager/geo의 열린 PR·이슈를 대조하고, 큰 task를 독립 PR·검증 단위로 분해했다.
  Agent A/B 소유 경계, migration·OpenAPI·frontend 충돌 barrier, Wave 2 freeze/join/final
  cutover 순서와 실패 지점 재개 규율을 고정했다. 적대적 리뷰어 2명이 legacy 조기 물리 삭제,
  compatible-pair 재-capture, idempotency·frontend ordering, H21 첫 blocker 표현과 문서 예외
  범위를 바로잡은 뒤 잔여 P0/P1/P2 0건을 확인했다.

## 2026-07-28 — Lane B T-VN-45 features map Live 라운드트립 완결

- [x] **T-VN-45 (#871)** — `/features` 실데이터 input-roundtrip을 실제
  `/v1/admin/features/in-bounds`의 `items`/`clusters` 계약으로 전환했다. 모든 새 query key의
  요청 bbox·kind·zoom과 성공 응답 본문을 검증하고, 취소된 요청도 URL 계약 검사를 건너뛰지
  않는다. cache hit는 새 HTTP 응답을 강제하지 않고 map idle 뒤 마지막 성공 응답의 전체
  point `feature_id` 집합·server cluster key/count/centroid와 실제 DOM이 일치할 때만
  수렴한다.
- **false-green 제거**: point marker, server cluster, coincident popup row에 각각
  `data-feature-id`/`data-cluster-key`를 노출했다. 식별자가 없는 marker도 빈 값으로 exact
  비교에 남겨 실패시키고, cluster는 표시 count와 MapLibre projection 기준 DOM 중심 좌표를
  1.5px 이내로 검증한다. 상세 클릭은 선택한 ID의
  `/v1/admin/features/{feature_id}`와 `AdminFeatureDetailResponse.data.feature`만 허용한다.
- **파괴적 Live UI**: n150 격리 prod clone에서 지도 저배율 cluster·서울/부산 items·kind
  필터·상세 클릭을 실패 지점별로 재개해 통과했다. 별도 write workflow는 실제 add 승인,
  update 승인, update 거절, 비활성화, delete 승인을 모두 수행해 인증 setup 포함 **2/2**
  (**48.3초**)를 통과했다. 최신 합성 Feature는 `deleted`이고 `deleted_at`/
  `user_deleted_at`가 모두 채워졌으며, 전체 합성 감사 범위는 non-deleted Feature **0건**,
  pending change request **0건**이다.
- **Live spec 동반 복구**: 파괴적 검증 중 확인한 ADR-066 이전 `operator` 입력, 접힌 고급
  JSON 섹션, 구 create/review/preview 접근성 이름과 번역 상태, 동시 필터 변경의 비결정적
  이름 검색을 현행 UI 계약에 맞췄다. admin 목록은 필터·정렬을 먼저 확정한 뒤 exact
  `feature_id` PK 검색 응답 본문과 row를 함께 단언한다. 적대 리뷰 뒤 update nested field
  보존, 비기본 `marker_icon=park`의 unchanged PATCH omission/결과 보존과 inactive exact 목록
  요청/응답까지 추가로 고정했다.
- **재개용 resource**: clone `ktm-tvn45-db`, dump와 redacted checkpoint는 PR 머지 뒤 다음
  task 착수 전 재사용 판정을 위해 보존했다. Playwright 인증 상태/cookie·raw trace·실데이터
  screenshot·민감 로그·임시 env/session secret은 재사용하지 않고 Live 종료 직후 폐기했다.
  `PGPASSWORD` metadata가 남아 있던 중지 상태의 clone transient container 8개도 제거했다.
  clone migration head는
  `0063_pipeline_root_id`, Feature **1,030,469건**, POI cache target **90건**이며 파괴적
  실행 후 clone health는 정상이다. 호환성·오염·디스크 판정 결과는 다음
  `resume.md`/`journal.md` 갱신에 기록한다.

## 2026-07-27 — Lane B T-VN-47 React Doctor + durable curation 완결

- [x] **T-VN-47** — React Doctor full scan을 269개 파일·actionable 진단 0건으로 만들었다.
  WebSocket cleanup·nested updater 부수효과·반복 helper·상태 파생·접근성 진단을 근인으로
  정리했다. frontend root의 `doctor.config.json`과 exact verifier가 shadow config·ignore,
  command/scope 축소와 package-level 우회를 거부한다. giant component 19개·reducer 후보 3개는
  별도 구조 설계가 필요해 exact scoped debt `T-VN-49`로 이관했다.
- [x] **T-VN-H13 후속 완결** — #862의 조건부 upsert를 source 누락·삭제→재등장·Feature merge까지
  확장했다. migration 0065가 `source_present`/`source_updated_at`과
  `operator_updated_by`/`operator_updated_at`을 분리하고 archived/NULL까지 포함한 exact identity
  unique를 강제한다. legacy projection은 `legacy_projection_id`로 durable item과 연결하며, stable
  collection key는 mutable slug 대신 theme/source UUID와 title hash를 사용한다. 중복 semantic
  collection은 `:split:<collection_id>`로 보존하고 임의 admin key 충돌도 migration 양방향에서
  덮어쓰지 않는다.
- **과거 drift 복구**: 0064 theme slug 재사용으로 collection owner가 탈취된 active/archived
  projection은 명시적 `legacy_projection_id`로 원 theme에 복구한다. canonical-only item은 원
  projection durable link가 없고 external identity도 theme 간 공유될 수 있으므로 자동 owner
  복구를 하지 않는다. upgrade 전 old projection 삭제 여부와 관계없이 모든 legacy-marker
  collection에서 `draft/admin_only` quarantine에 보존한다. admin PATCH로 mutable marker가 지워진
  이력도 immutable `legacy:` key namespace로 판별한다. exact `legacy:quarantine:<UUID>` key와
  immutable migration creator가 모두 일치하는 산출물만 재격리하지 않아 정상 `quarantine:` theme
  slug와 migration 왕복 identity를 함께 보존한다. mutable quarantine metadata에
  `migrated_from`이 추가돼도 upgrade·downgrade key rewrite에서 같은 결합을 제외한다.
  `source_record_key IS NULL`인 DELETE→새 UUID 재삽입도 기존 external identity와 operator
  tombstone을 재사용한다. legacy cross-title 이동은 target collection 뒤 source parent를
  잠그지 않고 item만 잠가 A→B/B→A 교착을 제거한다.
- **리뷰·검증**: 사용자 지시에 따라 단독 적대 리뷰어 1명이 PR840 이후 Claude Code 작성 PR
  #841~#845·#847~#850·#852~#857·#859~#864와 이번 exact code를 함께 감사했다. migration
  upgrade→downgrade→re-upgrade, 수동 base/split/staging key 선점, archived owner repair,
  canonical-only owner 증거 부재, 오래된 projection의 후속 owner 탈취, owner 간 동일 external identity,
  upgrade 전 old projection 삭제, metadata marker 제거, 정상 `quarantine:` theme slug,
  mutable quarantine metadata와 왕복 identity, null-source tombstone, 실제 두
  transaction 교차 이동을 포함한 관련 unit/integration/API 144건과 외부 geo live 5건을 제외한
  backend 전체 2,392건이 통과했다. static·frontend 전체 gate와 격리 실데이터 destructive Live UI
  근거는 같은 날짜 `journal.md` 항목을 정본으로 한다. curation exact code `7e2920aa`의 최종
  리뷰는 신규 P0–P2 0건·reviewer PostgreSQL 46/46이다.
- [x] **T-VN-H23** — T-VN-47 전체 실데이터 clone에서 발견한 0053 legacy active scope 중복
  blocker를 같은 PR에서 해결했다. 동일 scope의 queued job은 실제 dispatch 정렬로 winner 하나를
  보존하고 나머지를 기존 오류 문맥과 winner ID가 남는 `cancelled` terminal 상태로 전환한다.
  running 하나는 우선 보존하되 running 둘 이상 또는 cancellation audit marker가 걸린 중복은
  mutation 전에 fail-close한다. 실데이터와 같은 queued/now/now, running+queued, multiple-running,
  cancellation attempt/member 원자 보존과 downgrade/re-upgrade를 PostgreSQL 회귀로 고정했다.
  같은 단독 적대 리뷰어가 cancellation audit 훼손 가능성을 찾아 보강했으며 exact code
  `ca313d32`에서 잔여 P0–P2 0건을 확인했다.
- [x] **T-VN-H24** — 복합 공식 source item의 durable identity를 Feature target과 분리했다.
  `(collection_id, external_item_id, external_component_id)`가 membership을 식별하고
  `feature_id`는 nullable·mutable target으로만 둔다. CSV/API/UI/OpenAPI에 component key를
  전파하고 legacy UUID·operator/source/archive 이력을 첫 authoritative import에서 같은 행으로
  승계한다. 모호한 legacy 후보와 같은 source item의 active Feature 중복은 mutation 전에
  fail-close한다. 0064→0066 연속 업그레이드는 0065의 지연 FK·trigger event를 0066 첫 DDL 전에
  명시적으로 검사·소진해 단일 Alembic transaction에서도 안전하게 전진한다. n150 prod 격리
  clone에서 0036→0066 forward migration, 실제 UI CSV preview/commit과 REST/admin/지도 검증,
  공식 19 collections·486 source-present memberships, component 2/2, operator adoption 2,
  duplicate target 0, prod 불변을 확인했다. 실패 시 clone/build/import checkpoint를 보존해
  처음부터 반복하지 않고 실패 단계부터 재개했으며 성공 뒤 clone을 삭제했다.
- [x] **T-VN-H26 / #868** — main에 이미 반영된 c6c canonical
  `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` direct alias와 회귀를 재확인했다. 남은 수용 조건인 기존
  `KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET` fallback을 추가했다. 두 값이 함께 있으면 canonical이
  우선하며, 어느 값도 없으면 `None`, canonical로 로드된 secret에 잘못된 admin 헤더는 `403`이다.
  사용자 지시에 따라 이 추가 작업만 적대적 리뷰 예외로 처리했다.

## 2026-07-27 — Lane B T-VN-44 frontend lint·schedule recovery·가격 identity

- [x] **T-VN-44 (#858)** — frontend full ESLint를 0 warning gate로 고정하고 schedule 응답 유실
  복구, 가격 series identity `provider + price_domain + product_key`, migration 0064와 격리
  실데이터 Live UI를 완료했다. 세부 구현·검증은 같은 날짜 `journal.md` 항목과 CHANGELOG를 따른다.

## 2026-07-27 — T-VN-H20 prod admin credential 회전 완료 (login 200 검증)

- [x] **T-VN-H20** — prod admin password/hash 회전. credential-safe 스크립트(auth.ts와 동일 pbkdf2_sha256
  310k iter/256bit 파생)로 새 강한 password 생성 — 평문→gitignored `docs/prod-access.local.md`, hash→repo
  밖 scratch, stdout엔 경로·길이만(값 비노출). prod `.env`의 `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH`를
  base-compose로 UI만 recreate(R2: `-f docker-compose.yml --no-deps --force-recreate`, override 배제)해
  회전. **검증**: 새 pw→login 200 + 오키/기존→401, 배포 컨테이너 hash 87자, UI healthy.
  - **인시던트+복구(투명)**: 최초 회전에서 hash를 `.env`에 raw로 써서 docker-compose가 `$310000$salt$hash`의
    `$<salt>`/`$<hash>`를 변수 interpolation→salt/hash 소거(배포 20자)→admin UI 일시 로그인 불가.
    python diag(.env 87 vs container 20 MISMATCH)로 규명→`$`→`$$` escape 재작성→recreate→87자 복원→200 확인.
    매 단계 `.env` 타임스탬프 백업(롤백 가능). **교훈**: compose `.env`의 `$` 포함 값은 `$$` escape 필수.
  - 잔여(사용자 판단): local doc stale 섹션(초기 미배포 gen) 삭제, session secret 미회전(기존 세션 만료까지
    유효 — 완전 폐기 시 별도 회전), n150 `.env.h20-*bak.*` 롤백 백업 정리.

## 2026-07-27 — Lane B b4 하드닝 3건 완결 (H13·H14·H15)

각 항목 적대 리뷰어 2명(blocker 0) + 회귀 테스트 + CI green(pytest/dagster/PostGIS) 후 머지.
(Lane A가 Lane B b4를 사용자 지시로 순차 대행.)

- [x] **T-VN-H13** — curation authoritative 재적재가 운영자 override 보존 (#699 → PR #862).
  `_BULK_UPSERT_ITEMS_SQL` ON CONFLICT DO UPDATE·WHERE + `_PREVIEW_IMPORT_COUNTS_SQL` 비교에서
  status/curation_relation/reuse_policy 제거 → CSV 재적재가 운영자 admin PATCH 편집을 리셋하지 않고
  provider 파생 필드만 갱신. 회귀 테스트(편집 보존 + provider 갱신 + preview/removed 카운트).
- [x] **T-VN-H14** — KREX traffic notice snapshot bounded retry self-heal (#700 → PR #863).
  연속 2 snapshot 완전일치 즉시-실패 → sliding bounded-retry(상한 4, 총 최대 5 snapshot, inter-retry
  delay 0.5s) + typed `KrexTrafficNoticeSnapshotUnstable`. 휘발성 feed 일시 불일치를 self-heal해 run
  반복 실패·notice 신선도 정체 완화. 안정 feed는 2 snapshot 즉시 yield(무변경). 테스트 3종(transient/
  persistent/exact-boundary).
- [x] **T-VN-H15** — c7 attestation IPv6 public origin bracket 정규화 + zone-id 거부 (#805 → PR #864).
  `_public_origin`이 IPv6 host를 bracket 없이 `f"{host}{port}"`로 재구성(모호)하고 zone-id 미거부하던
  것을 `[address.compressed]` bracket+canonical + `"%"` scope 거부로 수정. `run-c7-prod-live-e2e.sh`의
  병렬 canonicalizer도 동일 미러링(divergence 방지). domain/IPv4 무변경(기존 해시 보존).

## 2026-07-27 — T-VN-H19 public API key 양성 production runtime 실증 (C2 갭 종결)

- [x] **T-VN-H19** — #854에서 "등가 충족"으로 처리했던 C2(public-key→curated 200)의 DB lookup+hash
  compare 양성 분기를 n150 production(map=c8ed6164)에서 credential-safe 직접 실증. admin-BFF
  `POST /v1/admin/public-api-keys`로 임시 key 발급(평문 1회, 값 비출력) → **valid key 200 PASS**,
  wrong key **401 PASS**, `POST .../{id}/revoke` **200**, 폐기 후 same key **401 PASS**(revoke lifecycle).
  key 값은 출력·기록 안 하고 key_id·status만 증거. → **경계 매트릭스 14/14, T-VN-03+T-ADM-C6c 전체
  완료**("C2 전까지 완료 금지" 조건 해소). 증거: reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md §1 C2.

## 2026-07-27 — T-VN-H12 live acceptance status marker 좌표 run-unique jitter (live 검증 완료)

- [x] **T-VN-H12** — `admin-feature-acceptance-write.live.spec.ts`의 status marker 좌표를 `sha256(RUN_ID)`
  ±0.25° run-unique jitter(`STATUS_MARKER_LON/LAT`) + `recenterMapTo`로 전환해 죽은 run leftover의
  supercluster 병합(marker aria-label 소실, P2)을 제거. base `LON`/`LAT`는 127.5/36.5 고정 유지
  (weather/price/correction/search는 seeding helper `admin_feature_live_fixture.py` `_LON`/`_LAT` 고정과
  좌표 동기 필요 — featureId/query 단언이라 supercluster 무관).
  - **경과**: #855(shared base jitter, merged) → **n150 c7-v6 live 검증에서 weather/price seeding desync
    발견**(공식 runner latent bug: helper 고정 seed vs spec jitter 조회) → #859에서 **status-only jitter로
    국한 수정**(rebase over #858, merged `baa04c08`).
  - **검증**: n150 c7-v6 live(map=c8ed6164/pinvi=6a035695) status marker 단계 통과(recenter 실증) +
    e2e type-check + 4각도 적대 정적검증. weather/price는 고정 base = LIVE-01 통과 baseline이라 무변경
    (full official-lane 재검증 불필요 — behavioral 변경은 status marker에 국한). cleanup featureId 기반이라
    leftover 0.
  - **교훈**(journal 2026-07-27): 정적 적대검증이 이 회귀를 놓친 이유 = 외부 Python seeding helper의 좌표
    계약을 정적 모델에 못 넣음. cross-process 좌표 계약은 live 검증 필요.

## 2026-07-27 — T-VN-H17 map#684 조건 #8 검증범위 축소 후 종결 (LIVE-01 후속 7/7 close)

- [x] **T-VN-H17** — H16에서 keep-open된 map#684를 **조건 #8 검증범위 명시 축소**로 종결(사용자 결정:
  조건 축소). #684 조건 1~7 + owner 후속은 코드+mock+live로 충족. 조건 #8("mock e2e와 n150 live e2e에서
  검증")을 다음으로 확정: **live(n150)** = read/freshness/URL-복원/invalid-fail-closed
  (`ops-c7-read-auth.live.spec.ts`) + datasets **write 계약**(effective-scope refresh POST·active projection·
  reused_active_request, `ops-c7-kma-active-write.live.spec.ts`, T-ADM-C7 GREEN); **mock** = write-path
  **UI 엣지 전이 2건**(refresh done-terminal freshness invalidation `ops-datasets.spec.ts:1817`,
  polling 404/503 재시도 `:2440`). 근거: 반복 done-terminal은 prod Dagster refresh quota 소모 파괴적,
  404/503은 prod 인위 유발 곤란한 client-state 엣지 — write **계약**은 이미 C7 live 실증이라 UI 엣지는
  mock 적정. map#684 close. → **LIVE-01 후속 OPEN 7건 전부 종결**.

## 2026-07-27 — T-VN-H16 LIVE-01 후속 OPEN 이슈 7건 재검증 → 6 close / 1 keep

- [x] **T-VN-H16** — LIVE-01 후속 OPEN 7건의 독립 완료조건을 현재 main/배포·smoke 증거로 재검증
  (이슈당 1 에이전트 병렬 + 회의적 기본값). **6건 close, 1건 keep-open**:
  - **close**: `dm#70`(features routes 플래그 compose 명시, C6c smoke 교차확인) · `dm#63`(prod API env
    결선 PR #64, creds SET) · `map#777`(C7 attestation manifest v4 exact 강제 `c7_prod_attestation.py:423`) ·
    `map#712`(datasets fail-closed S2 active projection + 회귀 테스트 + C7 n150 live) · `map#719`(exact-scope
    이력 PR #728 filter-before-limit + continuation) · `map#694`(live E2E 의미 단언, PR #724 결함 surface 제거).
    각 이슈에 근거(file:line/PR/smoke) 포함 종결 코멘트 게재.
  - **keep-open**: `map#684` — 조건 1~7 충족이나 조건 #8의 write-path **live** 전이 2건(refresh done-terminal
    freshness invalidation·execution polling 404/503 재시도 UI)이 mock e2e에만 존재, n150 live lane 미구동
    → `T-VN-H17`로 잔여 구체화.

## 2026-07-27 — principal 경계 부분 실증 + PinVi #392 종결

- [x] **PinVi #392 observation-read principal** — PinVi 관측 caller가 ops:read로 200에 도달하고
  no-token은 401로 거부됨을 production에서 직접 실증했다. 배포=**map c8ed6164 / pinvi 6a035695**
  (둘 다 healthy, production profile).
- **부분 증거(T-VN-03/T-ADM-C6c 전체 완료 아님)**: 실행한 경계 smoke 13건은 모두 PASS했다.
  - curated: C1 keyless→401 · C3 service→200 · C4 admin-bff→200 · C4n secret-no-actor→401.
    C2 public-key→200은 DB lookup·hash compare 양성 runtime 분기를 직접 실행하지 않았으므로 미검증이다.
  - ops 6: O1 keyless→401 · O2 service-only→401 · O3 cancel-token→403 · O4 admin-bff→200 ·
    O5 ops:read→200 · O6 invalid→403.
  - MOIS: M1 production unmount→404.
  - 배포 전 정적 감사(워크플로우 `tvn03-c6c-readiness-audit`, 6차원 병렬+적대 반증): route policy
    exception 0, curated/ops/MOIS wiring, OpenAPI full/user 계약 일치 확인.
  - 증거: [t-vn-03-c6c-boundary-smoke-2026-07-27.md](reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md).
  - C2는 열린 `T-VN-H19`에서 credential-safe 임시 key로 직접 실증한다. 그 전까지
    T-VN-03/T-ADM-C6c를 완료로 이관하지 않는다.

## 2026-07-27 — Lane B b0 T-VN-43 admin frontend npm 보안 0건 전환

- [x] **T-VN-43 (#851, merge `d0e7077ffb0cee4139997b8143371b1418bfd784`)** — clean npm audit의
  low 2·moderate 7·high 7을 모두 제거하고 Node/npm·Next/PostCSS/Sharp·Playwright를 exact pin했다.
  사용하지 않는 shadcn CLI/MCP·form graph를 제거하고 npm tree/effective ESLint/Redocly patch/실제
  Next-Sharp optimizer를 fail-close gate로 고정했다. Python 2,355 tests와 frontend type/build/Vitest,
  격리 Docker mocked 24/24, 운영 API에 연결한 공식 CSV 5종 파괴적 Live UI 4/4를 n150에서 통과했다.
  #840 이후 Claude PR 전문 감사 1명과 독립 적대 리뷰어 2명의 최종 finding은 P0~P3 0건이었다. 상세
  `docs/journal.md` 2026-07-27(codex).

## 2026-07-27 — T-VN-H06 admin 목록 keyset 런타임 검증 완결

- [x] **T-VN-H06** — admin dedup/enrichment 목록을 OFFSET → keyset+fingerprint cursor로 전환.
  - **backend**(#813, merge `9d29606e`): `admin_feature_repo.py` keyset 술어
    `(total_score, review_id) < (:cursor_score::numeric, :cursor_review_id::uuid)`,
    `_REVIEW_CURSOR_VERSION` fingerprint, composite index `idx_dedup_status_score`/
    `idx_enrichment_review_status_score`. 2차 적대 리뷰 P3 반영(가변 score 재스캔 재정렬 tradeoff
    docstring + active-cursor EXPLAIN 케이스 `test_t212d_perf_explain.py`, seq-scan 회귀 가드).
    CI `pytest integration (PostGIS)` green.
  - **e2e 검증**(#852 + 후속 Codex 보강): 현행 UI에 맞춘 spec drift 수정에 더해 네 deferred filter의
    원자적 수렴과 decision PATCH의 `reviewed_by` 비전송을 전 경로에서 음성 단언했다. n150 Linux
    Playwright에서 dedup 14 + enrichment 9 + auth setup 1, 합계 **24/24**를 통과해 기존 Windows-only
    증거를 대체했다. network-mocked 목록 검증이라 task의 파괴적 live 예외를 적용하며, keyset 실백엔드
    동작은 #813의 pytest integration(PostGIS) EXPLAIN 가드가 커버한다.

## 2026-07-27 — T-VN-LIVE-01 targeted live acceptance lane n150 PASSED (04A/58/15 종결)

- [x] **T-VN-LIVE-01 (+T-VN-04A #741·T-VN-58 #785·T-VN-15)** — targeted admin-feature live
  acceptance lane(#792 구현)을 n150 production(map=c8ed6164/pinvi=6a035695)에서 파괴적 실행 →
  **PASSED**(rc=0, phase=passed, recovery_attempt=0, BLOCKED/ACTIVE 없음, active leftover 0).
  검증 범위: inactive/draft/hidden marker + hidden weather/price 카드 + public 비누출 + T-VN-15
  search total/continuation/CURSOR_QUERY_MISMATCH·FEATURE_SEARCH_CURSOR_TAMPERED 422 + #785 stale
  raw If-Match 412·dirty draft 보존·명시적 reload. **규명·수정 연쇄**(비-redact c7-v6 재현):
  helper host-network(#842) · map nav/zoom-contract·panel(#843) · Codex PR 리뷰 DSN/signal(#844) ·
  검색 pg_trgm 격리 32-hex(#845) · kind=place 격리(#848, cross-kind seed weather cluster). 인시던트
  복구(공유 pinvi DB migration → manifest trap) 후 c8ed6164로 재-cut. issue #741·#785 closed.
  적대 리뷰어 2명 반영(#848 P3 정정·P2→T-VN-H12 추적). 상세 `docs/journal.md` 2026-07-27.

## 2026-07-27 — Lane B b0 T-VN-42 지도 control·query identity·live recovery 하드닝

- [x] **T-VN-42 (#846)** — `/features`·`/curated-features` 상세 패널의 bottom-right `ScaleControl`
  비겹침 계약(공용 Playwright bounding-box assertion), live 전역 `reducedMotion` 제거 후 MapLibre
  `moveend`까지 클릭마다 대기하는 zoom helper, items/clusters in-bounds query key를 HTTP와 동일한
  정수 zoom·원본 bbox·명시적 mode로 통일, 서버 정수 zoom 기준과 UI cluster/items 분기 단일 함수화.
  #840 이후 Claude Code PR(#841~#845) 재감사로 #844 BLOCKED clear 신호 경쟁과 #845 cross-version
  recovery 가능성을 BLOCKED v3(source commit·API/Playwright image·pair·attestation hash 기록 +
  recovery runtime exact 대조로 mutation 전 cross-version cleanup 거부) 계약으로 차단. 상세
  `docs/journal.md` 2026-07-26(codex).

## 2026-07-26 전면 감사 정리 — C7 종결 + vNext Wave 0/1 합류 + 독립 하드닝 + Wave 3 측정

11-agent 전수 감사(2026-07-26)로 실코드 기준 완료 확정한 항목. C7 COMPLETE @ d5693269
(공식 6-spec prod gate full GREEN, `docs/journal.md` 2026-07-26).
- [x] **T-VN-08 — PinVi false-broken 수정** — PinVi PR #409(merge `423a8a3`): 외부 Feature
  해석을 `found|missing|unverified|not_linked`로 분리하고 transport·typed Map 실패는 마지막 snapshot을
  유지하는 `unverified`로 처리했다. opaque feature ID를 그대로 strict batch 계약에 전달해 구분자
  parsing을 제거했다. n150 실데이터 파괴적 live UI E2E는 web Map popup의 연결 장애→복구를
  검증했고, mobile 소비자는 TypeScript/type-check로 계약을 검증했다. 적대 리뷰어 2명 P0/P1/P2
  없음, CI 6-check green 후 squash merge. 5-state producer 계약은 별도 `T-VN-11`로 계속한다.

- [x] **T-ADM-C7-SCHEDCHURN** — 근인은 render churn이 아니라(오진), cron 저장 응답 유실 후
  frozen-idempotency 복구가 필요해질 때 cron 수정 dialog(Base UI)가 열린 채 남아 페이지 전체가
  inert가 되어 모든 schedule 컨트롤이 접근 불가가 되던 것. fix=`schedule-panel.tsx`(복구 필요
  순간 dialog close) + spec 하드닝(canReset·robustClick·settle-gate·시작 confirm alertdialog
  locator). 적대 리뷰어 2명 반영 → prod 재배포 후 재검증 GREEN → schedule-write blocking gate
  재편입. PR #838. 상세 `docs/journal.md` 2026-07-26.
- [x] **T-ADM-C7-POICAUSAL** — C7 게이트가 항상 poi-cache `@c7-causal`에서 red였던 원인은
  backend가 아니라 test-side 2중 버그: (1) `POI_HEADING` 영문 상수가 개편 B(`d8818994`) 한국어
  h1 통일 이후 stale → `gotoPoiTargets` 15s timeout; (2) `expectCausalDatasetProjectionUpdate`의
  `page.evaluate` 콜백 `connectionId` destructure 누락 → 상시 `ReferenceError`(cbe133c2 이래,
  heading 버그가 가림). PR #839(main d5693269) → 재-cut → 공식 게이트 full GREEN(6 spec 전부
  passed). **C7 COMPLETE at d5693269.**
- [x] **T-VN-SYNC-02 — integration/t-vn → main 최종 합류** — PR #790(2026-07-19, merge commit
  d93cb16e, base=main/head=integration/t-vn ancestry 보존, CI 8-check green). T-VN-57(#787) 선행
  머지 gate 준수. compatible-pair v4 activation은 2026-07-26 C7 재-cut으로 완결(map=d5693269 /
  pinvi=e60d1711, attestation self-verify PASS, 공식 6-spec gate GREEN). `integration/t-vn`
  통합 브랜치 규율은 본 합류로 폐지(이후 base=main).
- [x] **T-VN-57 — public route policy·OpenAPI security·user surface 단일 정본** (#784 closed) —
  PR #787: `_PUBLIC_CURATED_PATHS`/`USER_OPERATIONS` 수기 정본 제거, `build_route_policy_matrix`
  단일 정본화, runtime↔full↔user 양방향 전수 대조 CI(`test_export_openapi.py` — drift는
  ValueError로 거부), PUBLIC_KEYED=[PublicApiKey,ServiceToken]/PUBLIC_UNAUTHENTICATED=[]/
  SERVICE=[ServiceToken] 정확 선언, user-client TS 재생성.
- [x] **T-VN-59 — public weather·curation raw lineage 계약 분리** (#786 closed) — PR #788:
  public/operator DTO 분리(`PublicWeatherAlertHistoryItem` vs `AdminWeatherAlertHistoryItem`,
  `PublicCurationItemView` vs `AdminCurationItemView` — 상속 없음), user OpenAPI 재귀
  reachable-schema 금지 게이트(`USER_RESPONSE_FORBIDDEN_PROPERTIES` fail-closed, cycle/allOf/
  oneOf negative 테스트 포함), 수기 public curation client 동시 갱신.
- [x] **T-VN-H02R — standalone destructive fail-close·backup principal 감사 완결** (#796
  closed 2026-07-26) — PR #804 + companion docker-manager #68: compose 기본
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED:-false`, backup create/delete/restore/swap actor =
  `AdminProxyContext.actor`만, `RestoreSwapRequest.operator` 제거(+422 회귀), principal별
  registry 이벤트·resolved-compose default false/explicit true 회귀. migration 없음(요구대로).
- [x] **T-VN-H03R — route wiring startup gate·public CORS exact preflight 완결** (#798 closed) —
  PR #803: `create_app()`에서 `assert_route_policy_wiring()` fail-closed, `PUBLIC_CORS_REQUEST_HEADERS`
  닫힌 allowlist(CORS safelist + If-None-Match + X-Kor-Travel-Map-Api-Key), route별 exact-method
  CORS, 비허용 preflight 400 + ACAO 미방출, `KNOWN_WIRING_EXCEPTIONS == ()` 회귀.
- [x] **T-VN-H08 — Tier-2 p95 nearest-rank 산식 정확화** (#799 closed) — PR #801:
  `_nearest_rank_percentile` = `sorted(values)[ceil(p×n)-1]` 공용 helper(실행시간·shared read
  blocks 공용), n=1/20/30/100 fixture로 index·값 고정. release evidence 재생성은 이전 evidence가
  존재하지 않아 vacuous — 실제 1M+ 실분포 측정은 cutover(T-VN-39) 시 release 리포트로 수행.
- [x] **T-VN-H09 — weather semantic upsert collected_at 단조성** (#797 closed) — PR #802:
  `weather_repo.py` upsert `WHERE EXCLUDED.collected_at >= … AND ROW(…) IS DISTINCT FROM ROW(…)`
  (ADR-072 0060 승자 규칙 정합), current-row 선택 근거 ADR-072에 기록, NULL(비허용)/동률(내용
  다르면 later-write wins)/no-op(동일 replay 물리 UPDATE 없음) 정책 문서화, T1→T2/T2→T1/동률/
  backfill 통합 회귀.
- [x] **T-VN-51~56 — Wave 3 도입-조건 측정** — PR #816: 여섯 확장 후보(MVT/범용 batch/cursor
  rotation/weather partition·hypertable/물리 listener/대규모 fixture 주기) 전부 측정·판정 완료.
  T-VN-51~55는 명시 트리거로 유예, T-VN-56은 현행 2계층(per-PR tier-1 + release tier-2) 확정.
  정본 `performance.md` §8.4 + `reports/t-vn-51-56-adoption-measurement-2026-07-21.md`.

## C7 prod-live 게이트 확정 · schedule-write descope (2026-07-26, `T-ADM-C7`·`T-ADM-C7RUN`)

- [x] **T-ADM-C7 — live e2e 재작성 + n150 prod-live 검증 완결.** C7 prod-live 게이트를
  **read-auth·kma-active-write·kma-empty-write·kma-cap-write 4-spec**로 확정(green)하고 n150
  production에 대해 파괴적 live로 실행했다(현 prod: cron=20, RUNNING; 실행 부수효과 2건 복구 완료).
  WS 인증 close saga(C7W/X/Y/Z, read-auth 7/7), kma-write 계약(C7PV/C7PW), detail perf·running-race
  (#829)까지 실 코드 blocker를 모두 해결·머지했다. `ops-c7-schedule-write`는 app-side render churn
  때문에 blocking gate에서 **descope**했다(후속 열린 task `T-ADM-C7-SCHEDCHURN`). Map PR #837 +
  docker-manager PR #74 squash-merge. 상세: `docs/journal.md` 2026-07-26.
- [x] **T-ADM-C7RUN — 공식 러너 GREEN 확정 (2026-07-26 CLOSED).** "외부 data.go.kr KMA 502가 유일
  blocker" 진단은 폐기(오류)됐고, verbose-iterate(non-redacting reporter + browserFetch DIAG 계측)로
  masked blocker를 순차 규명·수정했다: preview provider_dataset 노출(#824), create-body `update_policy`
  과명세(#825), detail `/v1/ops/datasets/detail` O(roots²) timeout recency-bound(#828/#829),
  running-race fast-completion tolerate(#829), root_id lineage(#834), gate restructure(#835),
  empty-write queue-sensor UI-gate flake 하드닝(#837). 후반 flaky UI/timing까지 통과 확정. Map PR #837
  + docker-manager PR #74 머지.

## C7 kma-write live 계약 수정 (2026-07-22~23, `T-ADM-C7PV`·`T-ADM-C7PW`)

- [x] **T-ADM-C7PV — kma-active-write preview provider_dataset WYSIWYG(sync_scope)** (PR #824) —
  preview가 0-feature dataset(`kma_ultra_short_nowcast`)에서 `matched_scope.provider_datasets`를
  생략해 C7 `assertExactKmaPreviewBody`가 throw + 다음 UI `toContainText(sync_scope)`도 실패했다.
  `scope_repo` provider_dataset 브랜치가 요청 pair를 0-feature 포함 항상, 요청 `sync_scope`와 함께
  노출하도록 executor `_provider_dataset_scopes`와 parity를 맞췄다. verbose-iterate live harness로 검증.
- [x] **T-ADM-C7PW — kma-active-write create-body update_policy 테스트 과-명세** (PR #825) —
  UI는 create body에 `update_policy`를 안 보내는데(계약상 optional, absent≡{}) 테스트가 `{}` 기대 →
  `_ops-c7-admin-api.ts` `buildKmaRequest`의 `update_policy: {},` 삭제. clean v6 harness가
  kma-active-write 전 flow(create→run-now→terminal→grids→fingerprint→overflow×49) 통과 검증(2 passed).

## C7 ops-live WS 인증 close saga (2026-07-20~22, `T-ADM-C7W`·`T-ADM-C7X`·`T-ADM-C7Y`·`T-ADM-C7Z`·`T-VN-H11`)

- [x] **T-ADM-C7W — Chromium ops-live 인증 거절 close code 4401 복구** (#806 closed · PR #807) —
  변조된 subprotocol을 제시한 실제 Chromium이 handshake 실패 `1006` 대신 application close `4401`을
  관측하도록 transport-level subprotocol selector를 두고, 인증·nonce·application loop 미진입 상태로
  data frame 없이 `4401` close. selector 없음/단일/복수/길이초과 회귀 고정.
- [x] **T-ADM-C7X — ops-live subscribe-after-hello로 만료 ticket 4408 clean 전달** (#817 closed · PR #818).
- [x] **T-ADM-C7Y — ops-live reject-close accept↔close settle env-tunable 0.25s** (PR #821).
- [x] **T-ADM-C7Z — C7 live e2e 복구-leg passthrough를 route.continue로 (Sec-Fetch 보존)** (PR #823).
- [x] **T-VN-H11 — ops-live 인증 close의 proxy 전달 경계 분리** (#809 closed · PR #807/#810) —
  Uvicorn accept 101과 close frame coalescing에 대해 accept 성공 뒤 bounded settle window(배포 조합
  한정 best-effort)와 accept~close 단일 bounded child task 보호를 두었다. 위 4개 WS auth saga와 함께
  공식 러너 `ops-c7-read-auth` 7/7 통과로 검증. 별건 HAProxy WS 백엔드 `timeout tunnel` 미설정
  운영버그는 issue #819로 분리 등록.

## C7 manifest v4 provenance · PostGIS topology check 오탐 (2026-07-19, `T-ADM-C7P`·`T-ADM-C7F`)

- [x] **T-ADM-C7P — C6c manifest v4·Map 4-image C7 provenance 동기화** (issue #777 · PR #778,
  `d2104f15`) — compatible-pair manifest를 v4로 clean-cut하고 active/rollback pair에 Map API·UI·
  Dagster web·daemon 네 immutable image ID와 하나의 Map source revision을 결박했다. C7 attestation이
  네 Map image ID를 실제 compose runtime role과 각각 exact 비교하고, manager manifest v3는 거부한다.
  2026-07-26 C7 prod-live 게이트 green(runtime attestation 통과)으로 활성 검증됨.
- [x] **T-ADM-C7F — prod PostGIS topology 객체의 Alembic check 오탐 제거** (PR #791, `6fa914c2`) —
  shared Postgres infra owner의 `postgis_topology`(`topology.layer`·`topology.topology`)를
  `include_schemas=True` autogenerate가 삭제 대상으로 오인하던 `alembic check` 오탐을, extension-owned
  객체만 명시 제외하고 head migration 뒤 topology extension을 설치한 production-equivalent integration
  gate로 함께 고정했다.

## vNext 독립 하드닝 — public API key header 전환 (2026-07-20, `T-VN-H01`, integration/t-vn)

- [x] **T-VN-H01 public API key를 URL query에서 header로 이동** (#794) — 공개 REST API key를
  `?key=` 쿼리에서 clean-cut하고 `X-Kor-Travel-Map-Api-Key` 헤더로만 받는다(access log·Referer
  유출 차단, breaking change). OpenAPI `PublicApiKey` security scheme을 apiKey-in-header로 바꾸고
  `openapi.json`/`openapi.user.json`과 admin·user-client `types.ts`를 재생성했다. route policy
  분류(PUBLIC_KEYED)는 불변. PinVi·admin consumer는 헤더 전송으로 전환해야 한다(cross-repo
  coordination — T-VN-20 PinVi 패턴).

## destructive admin 기본값 fail-closed (2026-07-20, `T-VN-H02`)

- [x] **T-VN-H02 — destructive admin 기본값 fail-closed.** `admin_destructive_enabled`
  기본값을 `True`→`False`(fail-closed)로 내리고, 문서화된 env alias
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED`가 실제로 바인딩되도록 `validation_alias`를 추가했다.
  Docker compose는 컨테이너 기본 true를 주입해 기존 배포를 유지한다(배포 전제: 파괴적 작업이
  필요한 배포는 host env로 이 값을 유지). PR #793.
  이후 standalone compose까지 default false로 닫는 `T-VN-H02R`(#796)이 이 배포 예외를
  clean-cut으로 대체한다.

## surface별 CORS 분리 (2026-07-20, `T-VN-H03`)

- [x] **T-VN-H03 — surface별 CORS를 표면 정책으로 분리.** route policy matrix(T-VN-02)의
  분류를 재사용해 browser-facing public 표면(public-unauthenticated·public-keyed)에만 CORS를
  적용하고, service(server-to-server token)·operator(admin BFF same-origin proxy)·metrics·debug
  표면은 `Access-Control-Allow-Origin`을 내보내지 않는다. app-global `CORSMiddleware`를 route
  policy로 게이트하는 표면 범위 미들웨어(`kortravelmap.api.cors.SurfaceScopedCORSMiddleware`)로
  구현했고, 경로 판정은 비-public 매칭 시 무조건 제외하는 security-safe 규칙을 쓴다. CORS는
  미들웨어라 OpenAPI spec 무관(drift 없음). PR #795.

## coord_5179 PROJ pin · INVALID index 복구 runbook (2026-07-20, `T-VN-H04`·`T-VN-H05`)

- [x] **T-VN-H04 — `coord_5179` PROJ 버전 고정·drift 검사·REINDEX runbook.** `docs/runbooks/coord-5179-proj-pin.md` 추가 — PROJ-bound STORED generated 컬럼의 drift 탐지 SQL(저장 `coord_5179` vs 현재 PROJ `ST_Transform(coord,5179)` 비교), `SET coord=coord` keyset batch 재계산, `REINDEX INDEX CONCURRENTLY idx_features_coord_5179_gist`. image tag `postgis/postgis:16-3.5-alpine`가 PROJ를 pin. performance.md §7.1·postgres-schema.md §4.1·runbooks README에서 링크. SQL은 postgis 16-3.5 컨테이너로 검증. PR #800.
- [x] **T-VN-H05 — CONCURRENTLY 실패 INVALID index 탐지·drop runbook.** `docs/runbooks/invalid-index-recovery.md` 추가 — `pg_index.indisvalid=false` 탐지 SQL(pg_class/pg_namespace join으로 index·table 이름), `DROP INDEX CONCURRENTLY IF EXISTS` + 원 DDL 재실행, 0061 self-heal·0060 non-concurrent 원자성 맥락. performance.md §8.3(§6.6 dangling ref 대체)·postgres-schema.md §8.2·runbooks README에서 링크. SQL은 postgis 16-3.5 컨테이너로 검증. PR #800.

## vNext main 동기화 (2026-07-20, `T-VN-SYNC-01`)

- [x] **T-VN-SYNC-01 — latest main을 integration/t-vn에 동기화.**
  `main@d2104f15`를 `integration/t-vn@22bf35a5` 위 전용 branch에서 merge하고, 양쪽 문서 이력,
  API image OCI revision label과 production profile, 완료/미완 task 정본을 함께 보존했다.
- [x] **migration과 CI 계약 확인.** Alembic `0058 → 0059 → 0060 → 0061 → 0062` 단일 chain을
  유지했고 lint, OpenAPI drift, Python 3.11/3.12/3.13, fixture replay, PostGIS integration,
  frontend type-check/build의 CI 8개를 모두 통과했다.
- [x] **PR #781 병합 완료.** PR head `aa976f13ae747d75fe67318d9c41fb2bddfddb04`를 merge commit
  `a45bc3ac401e5675811f1031a4592991498d899f`로 `integration/t-vn`에 반영했다. 이후 최종
  integration→main 합류는 열린 `T-VN-SYNC-02`가 담당한다.

## C7 prod runner attestation·복구 경계 (2026-07-19, `T-ADM-C7H`)

- [x] **T-ADM-C7H — 파괴적 live 실행 전 runtime을 exact attestation에 결박.** C6c compatible-pair,
  clean source commit과 OCI revision, Map API/UI/Dagster web·daemon/PinVi API의 실제
  image·command·environment, compose project, 단일 Alembic head/check, UI login을 read-only로
  대조한 뒤에만 `BLOCKED.json`과 mutation journal을 만든다.
- [x] **root 실행 파일과 복구 증거를 fail-closed로 고정.** runner/helper/attestation 모듈/상태
  감사기 네 파일을 exact Git archive와 root-owned SHA-256에 묶었다. 실패·signal 경로는
  runtime/journal/sentinel을 보존하고 INT/TERM은 130/143으로 종료한다. Playwright container는
  bridge/private IPC, durable creator/outcome/CID와 별도 검증형 stop 도구만 사용한다.
- [x] **단일 적대 리뷰와 실행형 gate 완료.** 최종 P0~P3 잔여 없음 판정 뒤 C7 대상 55건,
  전체 unit 1,529건, Ruff, strict mypy, import 계약, exact-commit immutable executor build를
  통과했다. PR #754와 보안 후속 PR #762는 각각 CI 8개가 모두 성공한 뒤 merge commit
  `b9f23a42`, `bece2c32`로 `main`에 반영됐다. 실제 배포·파괴적 browser 증거는 열린
  `T-ADM-C7` n150 gate가 담당한다.

## C7 mocked UI projection·pagination 수용 증거 (2026-07-19, `T-ADM-C7M`)

- [x] **T-ADM-C7M — datasets summary를 이름 있는 영역의 exact projection으로 검증.**
  `/ops/datasets` mocked E2E는 행·실패·SLA 초과·미실행·이슈 요약을 summary landmark 안에서
  검증한다. 같은 문자열로 표 행을 오염해도 summary 영역에 잘못 투영되지 않는 negative fixture를
  포함해 페이지 전역 문자열 검색으로 생기는 거짓 양성을 차단했다.
- [x] **pipeline continuation의 요청·응답·DOM 경계를 함께 고정.** 실행과 전역 event를 각각
  6+6 두 페이지로 주입하고 exact provider/dataset/scope/page size와 null/expected cursor 요청,
  페이지별 전체 DOM identity 배열, 전체 정렬, 페이지 간 서로소와 마지막 continuation 종료를
  검증한다.
- [x] **mock 증거와 live 수용 범위를 분리.** 6+6 fixture는 `page_size=50`의 실제 overflow가 아니라
  cursor plumbing 증거다. canonical page size를 넘는 51건 이상의 실제 continuation은 열린
  `T-ADM-C7` n150 live E2E가 담당한다.
- [x] **PR #755 병합 완료.** 단일 적대적 리뷰의 query-scope 지적을 exact validator와 cursor 관측
  검증으로 반영한 뒤 targeted mocked E2E 3건을 통과했다. 문구·fixture 설명 후속까지 포함한
  PR #755는 CI 8개 게이트가 모두 통과한 뒤 merge commit `54150c91`로 `main`에 반영됐다.

## vNext 재설계 Wave 0~1 (2026-07-19, `T-VN-*`, integration/t-vn)

> C7 종결 전까지 `integration/t-vn` 통합 브랜치에 누적. 각 task는 적대 리뷰(실전 결함 반영)
> + GitHub CI + n150 CI-parity 게이트를 거쳐 병합. 세부는 각 PR diff와 journal.

- [x] **T-VN-01 production fail-closed** (#740) — production profile secret 누락 시 기동 거부.
- [x] **T-VN-02 route policy matrix + 미분류 CI gate + /metrics 경계** (#747, +#742 수렴).
- [x] **T-VN-04 공개 predicate 단일화** (#743) — `feature.public_features` view, F-1 양방향 봉인.
- [x] **T-VN-05 raw payload 경계 제거** (#752) — 공개 DTO raw/lineage를 operator 표면으로.
- [x] **T-VN-06 notice 방어적 cast** (#746) — 오염 timestamp의 공개 read 500 차단.
- [x] **T-VN-07 no-op 옵션 삭제 + actor principal 1차** (#748).
- [x] **T-VN-13 Feature row_revision + If-Match/ETag** (#772, 리뷰 후속 #776) — 낙관적 동시성(428/412/304).
- [x] **T-VN-14 지도 completeness + exact ST_Intersects** (#763) — mode/truncated/coverage.
- [x] **T-VN-17 weather 무결성 제약** (#756) — semantic UNIQUE와 writer cutover 기반 도입.
- [x] **T-VN-18 중복 GiST 제거 + BRIN 감사** (#759) — write 1.2~1.3x 개선 실측.
- [x] **T-VN-19 Alembic metadata 정합 CI** (#753) — 빈 DB upgrade→check 게이트.
- [x] **T-VN-20 principal actor 전면 전환** (#757) — body actor 위조 경로 제거.
- [x] **T-VN-21 3단 성능 gate** (#760) — planner-default EXPLAIN·N+1·shape 회귀.
- codex 후속 병합: #745(curation), #749(metrics), #750(beach doc), #751(manual-link, main).

## vNext 적대 리뷰 후속 (2026-07-19, `T-VN-*R`, integration/t-vn)

- [x] **T-VN-05R public curated raw lineage 우회 차단** (#774, issue #765) — 공개 전용
  allowlist DTO/projection과 strict kind별 detail로 admin raw 계약과 공개 계약을 분리했다.
- [x] **T-VN-14R cluster/items exact 후보집합 단일화** (#773, issue #768) — PR #763 후속으로
  교차 geometry의 cluster count/items universe와 canonical 행정코드 귀속을 일치시켰다.
- [x] **T-VN-17R weather UNIQUE writer race 봉인** (#771, issue #766) — migration 0060을
  transactional non-concurrent UNIQUE cutover로 정정해 dedup과 writer fence를 원자화했다.
- [x] **T-VN-21R release benchmark 측정 정확성** (#775, issue #767) — 실제 public batch
  cardinality, matched/returned 구분과 top-level shared read 단일 합산을 고정했다.

## POI target causal receipt·조건부 삭제 (2026-07-18, `T-ADM-C7C`)

- [x] **T-ADM-C7C — mutation과 live invalidation을 transaction-coupled receipt로 결박.** POI target
  PUT/DELETE는 원본 transaction에서 증가한 `dataset_projection_revision`을 반환한다. C7 live
  E2E는 같은 기존 socket의 새 update frame에서 `live_revision >= receipt`만 causal 증거로 인정하며
  snapshot·top-level fingerprint revision은 제외한다.
- [x] **server-owned version과 exact `If-Match`로 재생성 경쟁을 차단.** Alembic 0058의 양수
  BIGINT `lock_version` trigger와 target UUID로 strong `ETag`/body `entity_tag`를 만든다. DELETE는
  누락 `428`, weak·wildcard·결합/중복/malformed `422`, stale UUID/version `412`, 실제 부재 `404`를
  구분하고 active natural-key row lock 뒤 UUID+version이 모두 같은 행만 soft-delete한다.
- [x] **parent→link lock order와 UI retry를 완결.** executor는 모든 active parent를 UUID 순서로
  `FOR KEY SHARE` 잠근 뒤 link를 교체한다. UI/BFF는 `If-Match`/`ETag`를 보존하고 stale `412`에서
  list·nearby·datasets·pipeline을 refetch해 같은 target UUID의 최신 tag로만 재시도한다.
- [x] **적대 리뷰·로컬 gate 완료.** 두 독립 리뷰어가 최종 기능 diff를 승인했다. root unit
  1,435건, API 520건, 실제 PostgreSQL migration/up-down·2-session 경쟁 8건, frontend unit
  212건, mocked POI E2E 10건을 통과했다. Ruff, strict mypy 115+52파일, import 계약 4/4,
  admin/user OpenAPI·생성 타입 drift, type-check·lint(오류 0)와 31-route production build도 green이다.
  실제 same-socket causal 증거와 destructive cleanup은 최종 `T-ADM-C7` n150 live E2E에서 수행한다.

## Admin exact-scope 조작·이력 UI 소비 (2026-07-18, `T-ADM-C7B-UI`)

- [x] **T-ADM-C7B-UI — exact provider/dataset/scope를 조작과 이력의 단일 정본으로 소비.**
  `/ops/datasets`는 잘못되거나 사라진 dataset/scope deep link를 다른 행으로 폴백하지 않고
  fail-closed한다. provider-only URL은 실제 선택 tuple로 canonicalize한 뒤에만 갱신·정책
  mutation을 허용한다.
- [x] **활성 실행·최근 종료·이력 continuation을 독립 표시.** `active_execution`과 최근 terminal
  `latest_execution`을 분리하고, exact scope의 `run_history`·`event_history`와 서버가 반환한
  `canonical_url`을 그대로 사용한다. scope 전환 중 정책 draft를 보존하며 orphan 또는
  `mutable=false` 행은 draft를 표시하되 저장을 차단한다.
- [x] **pipeline filter를 URL controlled state로 완결.** provider/dataset tuple이 불완전해지거나
  상위 축이 바뀌면 stale dataset/scope와 cursor를 같은 전이에서 제거한다. browser
  Back/Forward도 exact filter state에 반영하며 dataset-wide capability에는 명시적
  `sync_scope` 입력을 막고 서버 정규화에 맡긴다.
- [x] **적대 리뷰와 frontend gate 완료.** 독립 리뷰어 2인이 P0/P1/P2/P3 잔여 0건으로 승인했다.
  Vitest 26 files·210 tests, 앱·E2E type-check, lint 오류 0건과 31-route production build를
  통과했다. Playwright와 issue #712/#719 종결은 최종 `T-ADM-C7` n150 live E2E에 남긴다.

## Admin active projection·exact-scope 이력 API (2026-07-18, `T-ADM-C7B-API`)

- [x] **T-ADM-C7B-API — 활성 실행과 마지막 종료 실행을 독립 projection으로 완결.**
  datasets grid/detail은 같은 DB statement snapshot에서 exact
  `(provider,dataset_key,sync_scope)`별 queued/running `active_execution`과 최근 terminal
  `latest_execution`을 각각 선택한다. 논리 `dataset_wide`는 typed scope와 과거 NULL scope를
  같은 total order로 비교하고, `target_grids`·`external_system:*`에는 unscoped 실행을 추측하지
  않는다.
- [x] **Alembic 0057로 event identity와 exact-scope access path를 고정.** visible event의
  provider/dataset을 immutable owning job에서 복구하고 canonical direct update event에만 typed
  `sync_scope`를 backfill한다. INSERT trigger와 check constraint가 owner pair/scope를
  복사·불변화하며, `(provider,dataset_key,sync_scope,occurred_at DESC,event_id DESC)` partial
  index가 scope 조건을 cursor·`ORDER BY`·`LIMIT` 전에 적용한다. provider namespace 밖에서 의미가
  없는 dataset-only event filter는 REST/repository에서 `422`/`ValueError`로 거부하고, 읽기 경로가
  사라진 `idx_import_job_events_dataset_time`은 제거했다.
- [x] **실행·event continuation 계약을 typed cursor로 완결.** dataset detail은 `run_history`와
  `event_history`를 각각 `{items,next_cursor,canonical_url}`로 반환하고 pipeline 목록·event stream도
  같은 canonical URL을 사용한다. run/event cursor는 전체 filter fingerprint에 묶어 다른
  job/level/provider/dataset/scope에서 재사용하면 DB 조회 전에 typed `422`로 닫고, strict parser가
  거부하는 scope와 불완전한 provider/dataset tuple도 fail-closed한다.
- [x] **적대 리뷰와 로컬 gate 완료.** DB/API 적대 리뷰어 2인이 테스트 전에 최종 변경을 검토해
  P0/P1/P2/P3 잔여 0건으로 승인했다. migration 0057·수정 EXPLAIN·pipeline/jobs/dataset
  projection·feature executor·ORM metadata/repository의 실제 PostgreSQL 순차 gate 81건,
  root unit/lint 1,430건, API 504건과 frontend unit 210건을 모두 통과했다. Ruff, strict
  mypy 167개 소스, frontend type-check·lint, admin/user OpenAPI·생성 타입 drift도 green이다.
  issue #712/#719는 최종 `T-ADM-C7` n150 live 증거 뒤 종결한다.

## Admin 갱신 정책 동시성 완결 (2026-07-18, `T-ADM-AUD-718`)

- [x] **T-ADM-AUD-718 — BIGINT revision CAS를 DB부터 UI까지 완결.** Alembic 0056으로
  `ops.provider_refresh_policies.revision`을 양수 BIGINT로 추가했다. 신규 생성은
  `expected_revision=null`, 기존 갱신은 정확한 revision 일치가 필수이며 성공할 때만 원자적으로
  1 증가한다. `source_kind`는 생성 뒤 불변이고 최댓값은 overflow 전에 typed 소진 `409`로 닫는다.
- [x] **충돌 복구와 JavaScript 정밀도 경계를 고정.** HTTP revision은 정규화된 10진 문자열이며
  불일치 응답은 현재 정책과 revision을 포함한다. UI는 작성 기준·최신 관측값·지연 응답 세대를
  분리해 background refetch와 다른 scope cache가 초안을 덮지 못하게 하고, 명시적 3-way 조정 뒤
  최신 revision으로만 다시 저장한다.
- [x] **적대 리뷰와 로컬 gate 완료.** DB/API와 frontend 리뷰어가 최종 제품 SHA
  `b7b600447368d8ed79bc1a8b56772af881104bf3`을 S1/S2/S3 0건으로 승인했다. root unit
  1,411건, API 489건, 실제 PostGIS migration/schema 14건·CAS 저장소/API 23건·집중 10건과
  독립 row-lock 경쟁 3회, Ruff, strict mypy 115+52파일, import 계약 4/4를 통과했다. 같은 SHA의
  frontend Vitest 212건, type-check, lint 오류 0건, OpenAPI/admin type drift와 31-route production
  build도 통과했다. issue #718은 PR #727의 수용조건과 CI를 재확인한 뒤 2026-07-18 닫았다.

## KMA 빈 target fail-closed·exact-scope event (2026-07-18, `T-ADM-AUD-686`)

- [x] **T-ADM-AUD-686 — 유효 target 0건을 provider I/O 전에 종결.** 직접 runner와 정규
  Dagster KMA grid asset 3종은 target mapping·dedupe·cap·cursor preflight를 통과한 뒤에만
  credential·provider import·public client를 사용한다. 유효 target이 없으면 feature/weather와
  provider sync state를 변경하지 않고 canonical operation을 실패시키며, 같은 transaction에
  `kma.target_scope_empty` event를 정확히 한 번 기록한다.
- [x] **원자성·이력 경계를 회귀 계약으로 고정.** active duplicate loser와 terminal replay는
  operation/event를 늘리지 않고, event 기록 실패는 request/job/event 전체를 rollback한다.
  dataset event는 canonical event→job→request JOIN에서 effective `sync_scope`를
  cursor·`ORDER BY`·`LIMIT` 전에 제한하며 다음 cursor와 canonical history URL을 반환한다.
  migration은 추가하지 않았고 이 join-derived 경계는 후속 C7B-API/0057이 승계한다.
- [x] **적대 리뷰와 로컬 gate 완료.** 두 독립 리뷰어가 제품 SHA `c07259fb`를 S1/S2/S3
  0건으로 승인했다. 테스트 격리·generated type 동기화를 반영한 최종 SHA에서 root unit
  1,413건, API 485건, Dagster 475건(1 skip), 실제 PostGIS 집중 6건, frontend Vitest
  185건을 통과했다. Ruff, strict mypy 115+52+23파일, import 계약 4/4,
  OpenAPI admin/user·generated type drift, frontend type-check·lint(오류 0, 기존 경고 6),
  31-route production build도 통과했다. #686은 #701/#726/#728/#729의 전체 수용조건과
  CI를 재확인한 뒤 2026-07-18 닫았다.

## Admin ops-live 인증·무효화 완결 (2026-07-17, `T-ADM-C7A`)

- [x] **T-ADM-C7A — same-origin 실시간 갱신 경계를 완결.** 로그인 session과
  `Origin`·Fetch Metadata를 모두 검사하는 ticket BFF, HMAC 서명 subprotocol ticket, DB nonce
  단일 소비와 60초 연결 lease를 구현했다. 없음·변조 ticket은 `4401`, handshake 전 만료는
  data frame 없이 `4408`로 닫으며 공유 secret은 local launcher와 API container에서 앞뒤
  공백 없이 32자 이상이어야 기동한다.
- [x] **transaction-coupled invalidation과 복구 상태 모델 고정.** Alembic 0055로
  `ops.ops_live_ticket_claims`와 `ops.ops_live_topic_revisions`를 추가했다. provider 상태·정책,
  schedule override·audit·claim resolution, integrity issue·POI cache target 변경을 원본
  transaction과 함께 topic revision에 반영하고 pipeline/datasets canonical query key를
  무효화한다. malformed·비단조 frame은 오염 socket을 폐기하고 새 ticket/socket에서 exact
  `replace`를 다시 보낸다. 연속 두 번 실패는 standby, 세 번째부터 polling fallback으로 전환한다.
- [x] **적대 리뷰와 로컬 gate 완료.** backend/DB/security와 frontend 상태 모델 리뷰어가 제품
  변경을 테스트 전에 승인했다. 정확한 최종 제품 SHA에서 root unit 1,411건, API 484건,
  실제 PostGIS migration/schema 14건과 C7A 집중 9건, frontend unit 185건, Ruff, strict mypy
  115+52파일, import 계약 4/4, OpenAPI/admin/user type drift, base·host Compose rendering과
  production build를 통과했다. 실제 browser의 close code·재연결은 최종 `T-ADM-C7` n150
  파괴적 live E2E에서 검증한다.

## Admin legacy surface clean-cut (2026-07-17, `T-ADM-C6b`)

- [x] **T-ADM-C6b — 운영 표면을 pipeline/datasets 두 화면으로 clean-cut.** legacy REST
  operation 28개와 `/ops/import-jobs*`, `/ops/providers`, `/admin/features/update-requests*`,
  `/admin/dagster`, `/etl` UI를 redirect·호환 shim 없이 삭제했다. canonical
  `/v1/ops/pipeline/*`, `/v1/ops/datasets/*`, 관측 read와 public provider read 2종만 유지했다.
- [x] **provider credential과 BFF 런타임 경계 분리.** API/frontend는 process별 env allowlist와
  package-scoped API env를 사용하고 provider 비밀은 Dagster에만 둔다. bridge mode는 전용
  control-plane network의 frontend 고정 주소 `/32`만 신뢰하며 host mode는 loopback으로
  덮어쓴다. root raw env 예제의 inline comment와 API package secret 중복은 fail-closed한다.
- [x] **계약·검증 완료.** 두 독립 적대 리뷰어가 최종 제품 및 테스트 보강을 S1/S2/S3 0건으로
  승인했다. root unit 1,410건, API 450건, Dagster 457건(1 skip), 실제 PostGIS 92건,
  frontend unit 142건, Ruff, strict mypy 115+51파일, import 계약 4/4, OpenAPI/admin/user type
  drift, base·host Compose rendering과 production build를 통과했다. live UI는 최종
  `T-ADM-C7` n150 gate에서 검증한다.

## Admin datasets 이슈 의미 통일 (2026-07-17, `T-ADM-C7B-720`)

- [x] **T-ADM-C7B-720 — dataset/provider open issue를 단일 행 의미로 통합.** `이슈 있음`
  필터·정렬·행 badge는 dataset 또는 provider open issue가 하나라도 있으면 선택한다. 요약은
  dataset을 `(provider,dataset)`, provider를 provider 단위로 중복 제거해 scope 반복 행을
  한 번만 집계한다.
- [x] **네 소유 조합과 frontend-only 경계를 고정.** provider-only, dataset-only, both,
  neither를 unit과 mocked E2E 계약에 추가했고 API·OpenAPI·DB는 변경하지 않았다. 두 독립
  리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했으며 unit 5건, type-check, lint와 production
  build를 통과했다. #720은 본문 수용조건을 재확인한 뒤 2026-07-18 닫았다.

## Admin 통합 화면 링크 정본화 (2026-07-17, `T-ADM-C6a`)

- [x] **T-ADM-C6a — 존치 화면과 API 링크를 두 운영 화면으로 재배선.** import job,
  update request, load batch, provider/dataset과 홈·Feature·큐레이션·로그의 링크를
  `/ops/pipeline`·`/ops/datasets`로 전환했다. provider/dataset/scope와 canonical root
  identity를 보존하고 caller query가 엔티티 identity를 덮어쓰지 못하게 했다.
- [x] **선택 조회와 실시간 갱신 계약 보강.** load batch와 parent UUID deep link는 전용
  partial index에서 member를 먼저 선택한 뒤 root component를 확장한다. ops-live query key,
  import job HATEOAS와 live scenario catalog도 두 통합 화면 계약으로 맞췄다.
- [x] **적대 리뷰·회귀 검증.** 두 독립 리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했다.
  root unit 18건, API 140건, 실제 Postgres 통합 22건, frontend unit 27건과 Ruff, strict
  mypy 115파일, import 계약 4/4, type-check, lint, production build를 통과했다.

## Admin pipeline 통합 화면 (2026-07-17, `T-ADM-C5`)

- [x] **T-ADM-C5 — `/ops/pipeline` 실행·스케줄 조작 단일 표면.** canonical root 기준
  상태 strip·타임라인·Dagster run·전역 event·schedule audit/claim·feature update 요청을
  한 화면에 통합했다. provider/dataset pair와 request root/projected job을 분리해 표시하고,
  URL 상태·1페이지 자동 갱신·신규 실행 배지·degraded 경계를 일관되게 적용했다.
- [x] **멱등·동시성·불확실 결과 폐루프.** Alembic 0054로 feature update idempotency와
  schedule command audit/active claim/resolution ledger를 append-only로 고정했다. DB clock 기반
  lease와 advisory lock, 120초 operation timeout, mutation guard를 사용하며 응답 유실 뒤에도
  동일 command/request를 복원한다. mutation 이후 결과가 불확실하면 claim을 보존하고 운영자가
  audit 근거로 명시 해소하기 전 재실행하지 않는다.
- [x] **적대 리뷰와 회귀 검증.** 의미 있는 최종 제품 커밋과 session 복원 변경을 backend/UI
  적대 리뷰어 2명이 각각 재검토해 S1/S2/S3 0건으로 승인했다. append-only cleanup은 테스트
  transaction에만 제한하고 실제 trigger 검증은 유지했다. #693·#716의 지적을 구현과 회귀
  테스트로 흡수했다.

## Admin datasets 통합·scope 폐루프 (2026-07-17, `T-ADM-C45X-B`·`C4R`·`C4`)

- [x] **T-ADM-C45X-B — sync_scope·active request 백엔드 정본.** PR #701에서 direct
  update의 typed scope·dispatch intent, active 유일성·멱등 재사용, KMA exact target과
  scope별 cursor/failure를 완결하고 병합했다.
- [x] **T-ADM-C4R / C45X-U — C4 UI 소비 계약과 scope 폐루프.** PR #698에서
  datasets projection과 pipeline history를 exact 3원 scope로 정렬하고, dataset-wide 기본
  state와 orphan/stale scope를 구분했다. active `external_system:*` 첫 실행, 기존 active
  operation 재사용 링크, 정책·preview·freshness·schedule degrade를 fail-closed UI에 연결했다.
- [x] **T-ADM-C4 — `/ops/datasets` 통합 화면.** 검색·상태 그리드, URL/history 기반 drawer,
  정책 편집, fixture preview, 지금 갱신과 scope별 이력을 한 화면에 구현했다. 두 적대 리뷰어의
  최종 판정은 S1/S2/S3 0건이고 mocked production UI E2E 47건이 통과했다. #684/#686/#712의
  운영 종결은 `T-ADM-C7` n150 live 증거 뒤 수행한다.

## C3e n150 운영 종결 (2026-07-16, `T-ADM-C3e-I2`)

- [x] **T-ADM-C3e-I2 — migration·sensor/cursor·4종 동일-root·live UI 검증.** 배포 전
  pg_dump(259,608,395 bytes, SHA-256
  `0c01693808a0cc94dcbe1dce9a04c5996364c642ac4fa3f1df77d87c08667167`) 뒤 n150 prod에
  0051/0052를 일방향 적용했고 Alembic single head와 0048 재수렴 `updated=0`, 예상 밖 exact
  untyped `0`, request validation/identity/quarantine 불일치 `0`을 확인했다. tracking sensor
  8개와 update sensor 2개는 모두 RUNNING이며 reconciliation cursor는 maintenance anchor
  `storage_id=5160`에서 `5175`로 전진하고 최근 5개 tick이 관측 오류 0으로 끝났다. 스케줄은
  기존 snapshot인 34 RUNNING·3 STOPPED로 정확히 복원했다. 일정·수동·갱신·standalone import가
  datasets/pipeline 상세에서 같은 `(kind,id)` root를 반환했고 모두 terminal이다. 공식 Playwright
  1.60.0 컨테이너로 provider consistency, Dagster/update request, offline upload, import action,
  home dashboard를 실제 prod에 실행해 138건 통과·전제 미충족 2건 skip을 기록했다. 최종 DB와
  Dagster active run은 0이고 이슈 #679에 전체 증거를 남긴 뒤 완료로 닫았다.

## C3e B2→B3 실제 PostGIS 교차 회귀 (2026-07-16, `T-ADM-C3e-I1`)

- [x] **T-ADM-C3e-I1 — public wrapper 결과와 terminal sensor의 단일 lifecycle 검증.** 실제
  migration 0001→0052를 적용한 PostGIS에서 단일 provider wrapper 성공과 MCST 부분 성공·실패를
  B2 public 경계로 기록한 뒤 B3 terminal record로 닫았다. 단일 성공은 root/member 완료·진행률
  100·engine 시각과 수동 trigger를, MCST 실패는 13개 exact pair의 identity·job·완료 시각 보존,
  active pair만 실패 처리, redacted attempt event 보존과 raw 오류 비노출을 고정했다. 두 적대
  리뷰어의 최종 판정은 각각 S1/S2/S3 0건이다. focused 32건, live 제외 전체 1,902건(5 deselected),
  Ruff, strict mypy 136개 소스, import 계약 4/4를 통과했다. raw 전체 실행에서는 외부
  `kor-travel-geo` reverse endpoint가 HTTP 400을 반환해 live 5건만 실패했으며 C3e seam 실패와
  분리했다. n150 migration·sensor/cursor·4종 동일-root 증거와 이슈 #679 종결은
  `T-ADM-C3e-I2`에 남겼다.

## C3e Dagster provider guard·public wrapper tracking (2026-07-16, `T-ADM-C3e-B2`)

- [x] **T-ADM-C3e-B2 — authoritative provider guard와 exact-pair tracking.** 모든 live
  provider resource가 I/O 전에 실제 Dagster run record의 job·asset selection·run config·tag와
  B1 registry identity를 대조하고, 각 public asset/KMA wrapper가 마지막 ensure와 자기 exact pair
  완료를 소유하게 했다. MCST는 nullable pair-completion callback으로 부분 성공을 보존하며 direct
  `FeatureUpdateAssetRunner`는 tracking 0을 유지한다. 취소 marker·identity drift·naive timestamp는
  fail-closed하고, 비기본 KNPS point/geometry 설정은 provider fetcher와 asset resource가 같은
  `model_copy` snapshot을 사용한다. 적대 리뷰어 2명의 최종 판정은 S1/S2/S3 0건이다. focused
  260건(1 skip), 실제 PostGIS canonical operation 30건, Dagster 전체 428건(1 skip), main unit
  1,366건과 Ruff·strict mypy 136개 소스·import 계약 4/4를 통과했다. B2→B3 실제 terminal DB
  연쇄는 `T-ADM-C3e-I1`에서 완료했고, 이슈 #679 종결과 n150 증거는 `T-ADM-C3e-I2`에 남겼다.

## C3e Dagster run sensor·양방향 복구 (2026-07-16, `T-ADM-C3e-B3`)

- [x] **T-ADM-C3e-B3 — active/terminal sensor·양방향 reconcile.** QUEUED부터
  CANCELED까지 7개 run-status sensor와 NOT_STARTED/MANAGED·누락 event를 복구하는 30초
  periodic sensor를 기본 RUNNING으로 등록했다. public Dagster insertion cursor는 300초
  settle lag와 연속 settled prefix를 사용하고, DB active-root keyset은 마지막 page에서 처음으로
  wrap한다. cursor anchor 삭제·변조, 비어 있지 않은 storage의 무cursor 시작, scan/list/write
  실패는 fail-closed하며 cursor를 전진시키지 않는다. terminal trigger·selection 불변식 위반은
  같은 transaction에서 root/child를 `tracking_invariant`로 닫는다. 적대 리뷰어 2명 최종
  S1/S2/S3 0건 승인 뒤 focused 101건과 수정 후 52건, 실제 PostGIS 27건, Dagster 전체
  342건(1 skip), main unit 1,366건, Ruff·strict mypy·import 계약 4/4를 통과했다.

## C3e Dagster operation registry (2026-07-16, `T-ADM-C3e-B1`)

- [x] **T-ADM-C3e-B1 — immutable registry·run identity.** 33개 feature-load job과
  53개 exact provider/dataset 선택지를 canonical manifest와 내용 기반 digest version으로
  고정했다. KNPS launch snapshot, fileData 4종의 두 resource config, MCST 13-pair identity,
  trigger 분리와 exact coalescing을 schedule/admin/projection 경계에 연결했다. 등록 job의
  누락·교차 identity는 fail-closed하고 비등록 job만 panel-only로 유지한다. 적대 리뷰 2인
  S1/S2 0건 승인 뒤 main unit 1,366건, API 513건, Dagster 308건(1 skip), focused 159건,
  Ruff·strict mypy·import 계약 4/4를 통과했다. 실제 Dagster context의 override guard와
  provider tracking은 B2로 이관했다.
## C3e REST canonical 교차 통합 (2026-07-16, `T-ADM-C3e-C`)

- [x] **T-ADM-C3e-C — datasets/pipeline 실제 DB·REST 교차 증거.** 실제 migration을 적용한
  PostgreSQL에 canonical operation을 commit하고 요청별 새 FastAPI session으로 datasets grid/detail과
  pipeline 2페이지가 같은 root·member·상태·engine 시각·projected job을 반환함을 고정했다.
  exact-pair decoy, 인증, cursor, schedule, slash·예약문자 복합키도 검증한다. detail/preview/
  refresh-policy는 고정 path와 `provider`/`dataset_key` query로 clean-cut 전환했으며 OpenAPI와
  admin 생성 타입을 함께 갱신했다. 적대 리뷰 2인 S1/S2 0건 승인 뒤 API 503건, router 13건,
  실제 DB 통합 1건, Ruff·strict mypy·OpenAPI/type drift·frontend type/lint gate를 통과했다.
## C3e 실행 재분할 문서화 (2026-07-16, `T-ADM-C3e-D2`)

- [x] **T-ADM-C3e-D2 — C3e-B 복구 감사와 병렬 PR 재분할.** Claude Code의 branch,
  reflog, stash, remote와 고아 worktree blob을 감사해 C3e-B 고유 구현이 없음을 확인했다.
  B를 registry/run identity, guard/wrapper/MCST, sensor/reconcile의 B1/B2/B3 PR로 나누고,
  A2에서 제품 구현이 끝난 C는 실제 DB/FastAPI REST 교차 통합 증거 PR로 축소했다. 문서-only
  변경이므로 사용자 지시에 따라 추가 적대 리뷰 없이 rebase·CI green 뒤 병합한다.

## Admin ops 통합 기반 (2026-07-14~15, `T-ADM-C1`~`C3c`)

- [x] **T-ADM-C1 — 플랜·ADR-064·task 분해.** Dagster job/provider 운영 표면을
  `/ops/pipeline`과 `/ops/datasets` 두 페이지로 통합하는 정본 계획과 병렬 PR 경계를 확정했다.
- [x] **T-ADM-C2 / C2R — datasets backend와 차단 계약 보강** (PR #676/#688,
  issue #678). 그리드·상세·refresh policy·typed preview, 서버 계산 freshness,
  schedule 시각 분리, canonical latest batch, provider/dataset 이슈 분리, orphan mutation
  차단을 완결했다.
- [x] **T-ADM-C3 — pipeline backend** (PR #677). overview·root execution·detail/cancel·
  event·Dagster run·schedule·request API와 `dagster_run_id` 실컬럼을 추가했다.
- [x] **T-ADM-C3a — 공용 application service/schema 추출** (issue #682, PR #687).
  삭제 예정 router의 private symbol 의존을 제거하고 신·구 표면의 공용 경계를 만들었다.
- [x] **T-ADM-C3b — canonical root projection** (issue #679, PR #689). recursive lineage,
  nearest request owner, standalone partition, deterministic projected job과 keyset cursor를
  구현했다. C3e가 typed identity 정본으로 후속 강화한다.
- [x] **T-ADM-C3c — Dagster run detail/failure 계약 이식** (issue #681, PR #687/#690).
  opaque event cursor, failure 구조, 404/502/503 RFC7807과 공용 query service를 완결했다.

## C3e canonical operation 영속화 (2026-07-15, `T-ADM-C3e-A1`)

- [x] **T-ADM-C3e-A1 — 0051·operation repository frozen 계약**.
  `ops.import_jobs`에 exact pair·trigger·registry version·raw Dagster status와 feature operation
  구조 제약·partial index를 추가하고, payload를 읽지 않는 보수적 backfill을 적용했다. frozen
  repository/client lifecycle, direct writer identity, feature operation의 authoritative engine 시각,
  C3d run-backed queued 취소 경계를 적대 리뷰 2회와 전체 로컬 gate로 고정했다. 상세 구현·검증
  기록은 `docs/journal.md`와 `docs/resume.md`의 2026-07-15 A1 항목을 따른다.

## C3e 공용 projection·request/job 단일 정본 (2026-07-16, `T-ADM-C3e-A2`)

- [x] **T-ADM-C3e-A2 — canonical root/exact-pair projection과 0052 clean-cut.**
  pipeline/grid/detail/overview를 같은 cycle-safe root와 typed pair member에 연결하고,
  feature update request lifecycle을 canonical import job 한 행으로 통합했다. request/job 양방향
  1:1, 6종 scope·typed filter·update policy, 격리 component, 전용 writer/CAS를 DB와 Python에서
  함께 강제한다. event 감사 부분 index와 statement-level live revision clock을 추가했으며,
  두 적대 리뷰어 승인 뒤 전체 Python/DB/frontend gate와 n150 mocked E2E 501건을 통과했다.

## C3e canonical operation 문서 gate (2026-07-15, `T-ADM-C3e-D`)

- [x] **T-ADM-C3e-D — canonical provider operation 문서 계약** (#679, PR #696).
  Claude Code worktree의 설계 기록을 C3d 정본 위에서 복구하고, Dagster run root 한 건과 exact
  provider/dataset child, retry/terminal 소유권, frozen client 계약, 0051 migration·backfill/down,
  C3d queued run-backed 취소, 공용 projection·mixed-version 순서를 구현 전에 고정했다. 적대 리뷰
  2인의 S1/S2 0건 승인과 CI green 뒤 문서 PR을 병합해 C3e-A1/A2/B/C의 compile target으로 삼았다.

## Pipeline 계층형 취소 완결 (2026-07-15, `T-ADM-C3d`)

- [x] **T-ADM-C3d — 실제 계층형 취소·Dagster terminate** (#680, PR #695).
  C3b canonical root의 frozen scope, base marker, 정규화 attempt/member/run, run별
  at-most-once terminate reservation, crash resume, authenticated audit, marker CAS와
  `Retry-After`/RFC7807/OpenAPI/admin types를 완결했다. pre-start generation 복구,
  browser invalidation/live E2E 계약, production bound-client DB 탈출 차단까지 하위
  `T-ADM-C3d-P1R`·`R2A`·`R2B`·`R2C`로 반영했다. 두 적대 리뷰와 로컬 전체 gate,
  GitHub Actions 8/8 green 뒤 merge commit
  `28dfe224dee9c7a09775293b37be6795edb92651`로 main에 반영했고, 수용 증거를 남긴 뒤
  이슈 #680을 닫았다.

## 최근 2일 Claude Code PR 사후 적대 리뷰 (2026-07-15, `T-ADM-RV-CLAUDE-2D`)

- [x] **T-ADM-RV-CLAUDE-2D — 닫힘 여부와 무관한 Claude Code PR 상세 리뷰·이슈화.**
  공동작성 trailer와 Claude session 근거가 있는 PR #672, #674, #675, #676, #677,
  #683, #691, #692를 각각 상세 리뷰했다. review-fix 전용 PR은 없었고, Claude 근거가 없는
  #664, #666~#671, #687~#690은 제외했다. pipeline UI 상태 격리·sensor fail-closed·URL
  복원은 #693, live UI E2E 의미 단언은 #694로 묶어 새 이슈를 만들었다. 기존 #682,
  #684, #685, #686에는 재현 근거와 보강 수용 기준을 남겼으며, #687로 완료되지 않은
  actor/problem/schedule 범위 때문에 #682를 다시 열었다.

## 지도 신선도·provider 실행·고zoom 성능 반복 장애 수정 (2026-07-13, `T-231`)

- [x] **T-231 — notice/OpiNet 반복 장애 근본 수정과 지도 응답성 보강.** KREX notice를
  strict pagination·lineage 검증을 거친 동일한 2회 연속 snapshot으로만 반영하고, 부재 공지
  종료·재등장 복원·공개 active 필터를 일관 적용했다. Dagster 고착 run 슬롯 고갈은 monitoring,
  provider pool·DB advisory lock, KREX tick coalescing으로 차단했다. OpiNet raw/변환 0건과
  전일·혼합 가격 성공 오인, scope를 무시한 targeted 전국 재조회도 실패/skip/cursor 계약으로
  교정했다. AirKorea/KMA marker, 과거 유가 표기·단일 시계열 점, Feature/큐레이션 고zoom
  로딩을 함께 보강했다. KREX upstream 수정은 `python-krex-api` PR #11에 선반영했다. 적대적
  리뷰 2회 후 S1/S2 잔여 0건이며 전체 로컬 Python/API/Dagster/frontend/OpenAPI 게이트를
  통과했다. PR merge·n150 운영 복구와 live E2E 인수 결과는 `docs/resume.md`의 다음 작업으로
  추적한다.

## 큐레이션 CSV·다중 관측 aggregate 계약 (2026-07-13, `T-230`)

- [x] **T-230 — 큐레이션 CSV·다중 source/연도 aggregate 계약 구현** (#665, PR #666).
  provider entity/current record와 immutable observation 이력, 회차형 collection/item schema를
  Alembic 0044/0045로 구현했다. admin 수동 입력·CSV 양식·preview·원자적 멱등 import와
  지도·목록·상세·REST의 다중 관측/다중 membership 표시를 추가하고 등대 category도 등록했다.
  공식 CSV 5종은 collection 19개·membership 486행이며, n150 기존 Feature에 225행을 연결하고
  261행은 원천 안정키·장소명·주소 hint를 가진 미연결 item으로 보존했다. 전체 로컬 게이트와
  적대적 리뷰(HIGH/MEDIUM 잔여 0), n150 Alembic 0045, 로그인, 실제 DB/REST, prod live Playwright
  4건, 동일 CSV 두 번째 dry-run 변경 0건을 통과했다. 정본 계획·결과는
  `docs/reports/t-230-curation-multi-observation-plan.md`다.

## UI live e2e 재실행 (2026-06-21, `T-UI-E2E-LIVE-20260621`)

- [x] **T-UI-E2E-LIVE-20260621 — UI live e2e 재실행 + 하네스 안정화.**
  live stack 기준 전체 Playwright e2e를 재실행했다. 1차는 629 passed / 1 failed였고,
  실패는 `home-density-matrix.spec.ts`의 공통 `gotoHome()`이 full `load` 이벤트를 기다리다
  live static asset 지연에 걸린 하네스 문제였다. `waitUntil: "domcontentloaded"`로 조정 후
  `npm run type-check:e2e`, 실패 케이스 단독 재현, 리베이스 후 현재 브랜치 별도 live stack에서
  전체 live UI e2e **631 passed**로 닫았다.
  정본 `docs/reports/ui-live-e2e-rerun-2026-06-21.md`.

## maplibre-vworld-js dependency 제거 (2026-06-18, `T-MAP-VWORLD-04`)

- [x] **T-MAP-VWORLD-04 — `maplibre-vworld-js` dependency 제거** (#475).
  `digitie/maplibre-vworld-react` `a7cb0f8` 기준으로 admin web 지도 경계를
  `vworld-map-core`/`vworld-map-web` 모델에 맞췄다. admin frontend와
  `@kor-travel-map/map-marker-react`에서 `maplibre-vworld` package dependency,
  `maplibre-vworld/style.css` import, Vite external/global 선언을 제거하고,
  `package-lock.json`에서 `maplibre-vworld` 및 전용 transitive를 제거했다.
  `VWorldMapView`는 maxZoom clamp, redacted error logging, stable marker click
  callback을 보강했다. 검증: admin type-check, marker typecheck/build,
  admin vitest 27 passed, ESLint 0 errors(기존 warnings 6), Next build, Windows
  Playwright 지도 e2e 5 passed. 정본 리포트:
  `docs/reports/maplibre-vworld-js-dependency-removal-2026-06-18.md`.

## OpenAPI 에러 본문 RFC7807 problem+json 기계 계약 보강 (2026-06-18, `T-452`)

- [x] **T-452-openapi-problem-json — OpenAPI 4xx/5xx problem+json 선언.**
  생성 `openapi.json`/`openapi.user.json`이 에러 응답을 `422 application/json`
  (`HTTPValidationError`)로만 선언하던 under-spec(#452/#444 잔여)을 해소했다. `create_app`의
  custom `app.openapi()`가 모든 operation의 4xx/5xx·`default` 응답을 `application/problem+json`
  (`ProblemDetail`/`ProblemDetailError`, `code`·`request_id` 확장 멤버 포함)으로 선언하고, FastAPI
  자동 422도 problem+json으로 대체하며 orphan 검증 schema를 제거한다. 핸들러별 `responses=`
  대신 중앙 핸들러(`_error_response`)와 대칭인 중앙 openapi 주입을 택했다. 산출물 재생성
  (`export_openapi.py --profile all`) + frontend/user-client `gen:types` 동반, `--check` drift
  gate·`gen:types:check`로 고정. 정본 `docs/architecture/rest-api.md §1.5`,
  회귀 테스트 `test_export_openapi.py::test_openapi_declares_rfc7807_problem_json_error_responses`.

## admin TanStack 테이블 이행 후속 종결 (2026-06-18, `T-ADMIN-TANSTACK`)

- [x] **T-ADMIN-TANSTACK — admin UI TanStack 테이블 이행 후속 종결.**
  이행 본체는 PR #454(정본 `docs/reports/admin-tanstack-table-migration-2026-06-17.md`). 잔여
  2건이 모두 해소되어 종결한다.
  - **(a) backend-의존 e2e 라이브 실행 ✅**: 라이브 Docker 스택(api :12701 / dagster :12702 /
    migrated frontend :12705)에서 전 spec 실행 → PR #458/#459 후 **57 passed / 0 failed**
    (2026-06-17, `docs/resume.md`). admin-ops/curated/features-new 포함 backend-의존 표면 무회귀
    확인. (사용자 결정: 이미 검증됨 → 재실행 생략.)
  - **(b) bulk 동작 정책 가드 ✅**: main에 이미 구현됨 — dedup bulk는
    `enableRowSelection` pending-only + `decideBulk` 방어적 필터로 **완료 review 재결정 차단**,
    curated bulk archive는 `window.confirm("선택한 N건을 보관할까요?")` **일괄 confirm**.
    enrichment는 단일 행 pending-only(bulk 표면 없음 — 가드 불필요).

## 외부/보류 task won't-do 종결 (2026-06-18)

사용자 지시로 아래 task를 **진행하지 않음(won't-do)** 으로 종결했다. 산출물 없이 백로그에서만
정리한다(`docs/tasks.md` 외부 추적 섹션 제거 + 보류에서 T-103 제거).

- [x] **T-019 — PinVi Kakao Maps → maplibre-vworld 교체 / SPEC supersede 추적** (won't-do, PinVi repo 외부).
  본 저장소 책임은 ADR-026/043 reference와 `@kor-travel-map/map-marker-react` 계약 유지로 한정한다.
- [x] **T-210b — PinVi 문서 supersede** (won't-do, PinVi repo 외부).
- [x] **T-210c — PinVi `apps/etl` 레거시 Dagster 이관/삭제** (won't-do, PinVi repo 외부).
- [x] **T-210d — PinVi httpx OpenAPI client 신규** (won't-do, PinVi repo 외부).
  PinVi-side 정렬 작업으로 본 저장소는 OpenAPI 계약(정본 `docs/integration-map.md`)만 책임진다.
- [x] **T-103 — streaming ETL(Kafka/Redpanda) 대응** (won't-do).
  `docs/architecture/performance.md §9.4` 기준 — 초 단위 latency를 실제로 요구하는 provider 증거가
  없어 도입하지 않는다. 필요 신호가 생기면 신규 task로 재개한다.

## maplibre-vworld-react 지도 전환 (2026-06-17, `T-MAP-VWORLD`)

- [x] **T-MAP-VWORLD-01 — 계획 및 Task 생성** (#465, PR #468).
  `digitie/maplibre-vworld-react` `a7cb0f8` 기준으로 admin `features` 지도 전환 범위를
  정했다. 전체 외부 모노레포 vendoring 없이 필요한 `VWorldMapView`/React marker 모델만
  admin UI 내부에 얇게 이식하는 방향이다. 정본 계획은
  `docs/reports/maplibre-vworld-react-migration-plan-2026-06-17.md`.
- [x] **T-MAP-VWORLD-02 — admin features 지도를 VWorldMapView 기반으로 전환** (#466).
  직접 `maplibre-gl` 인스턴스와 marker 배열을 관리하던 `features-client.tsx`를
  `VWorldMapView`/`VWorldMarker` 컴포넌트 모델로 전환했다. bbox 동기화, kind 필터
  refetch, marker/table 선택 상세 패널, VWorld key 미설정 fallback을 유지했다.
  Windows localhost forwarding이 실패하는 e2e 환경을 위해 `NEXT_ALLOWED_DEV_ORIGINS`
  기반 dev origin 추가 허용도 넣었다.
- [x] **T-MAP-VWORLD-03 — 지도 e2e 라이브 검증 및 후속 수정** (#467).
  PR #469 merge 후 main 기준으로 Windows Playwright 지도 e2e를 재실행했다.
  `features-map-interactions.spec.ts`는 **5 passed / 0 failed**였고 추가 수정할
  회귀는 없었다. 정본 리포트는
  `docs/reports/maplibre-vworld-react-e2e-2026-06-17.md`.

## T-212e 후속 라이브 검증 (2026-06-14, `T-229`)

- [x] **T-229 — T-212e 후속 라이브 검증** (arm64 buildx만 잔여).
  T-225가 분리한 커버리지 갭을 실데이터(features 1,095,665)로 라이브 검증했다. T-212e
  데이터가 옛 claude postgres(15433)에 잔존 + 격리 복원본 `krtour_map_restore` 존재라
  복원 불필요했고, 운영 데이터 무손상 원칙으로 **복원본에만** 검증했다. **curated
  오버레이 완전 검증**: `curated_features_refresh` 4-asset RUN_SUCCESS → curated_features
  0→**86,341** 후보(테마 7종, MCST source 카운트 정합), admin API 실제 서빙, 사용자
  표면은 미선택 후보 숨김(선택 게이트), curated-themes/sources 200, tripmate-copy는
  선택 시 생성(0). `/metrics` 200, smoke breadth 전 표면 응답(200/정상404). AS-01/
  API-11/12 실데이터 해소. arm64 multi-arch buildx는 당시 환경 제약으로 검증하지 못했으나,
  2026-06-29 사용자 결정으로 추가 추적하지 않는다. codex 스택은 사용자 지시로
  강제종료 후 external-infra 재기동. 정본 `docs/reports/t-229-curated-live-verify-2026-06-14.md`.

## T-212e closure 재검증 (2026-06-13, `T-225`)

- [x] **T-225 — T-212e closure 재검증.**
  라이브 full reload 재실행 없이 현재 main(`25b286b`, #434 포함) 기준 문서/코드 증거
  대조로 닫았다(인수기준 충족). 5개 차원 교차검증 + 각 gap 반증(서브에이전트 18).
  **T-212e closure 유효**: 실패 provider 6건 수정 전부 main 존재(pin SHA 일치),
  리포트 무결성 정합(MCST 13종 102,121, 이슈 #397/#407/#409 close + 보강 PR 머지,
  broken link 없음), identity는 #429가 리포트까지 재작성해 이미 post-rename,
  패키지 분리(#430)·#434 포트 재기준은 데이터 closure에 영향 없음. 착수 가정이던
  "구 이름 drift"는 실재하지 않았다. 남은 라이브 검증 커버리지 갭(curated 오버레이,
  Prometheus `/metrics`/arm64 buildx, smoke breadth)은 후속 **T-229**로 분리.
  정본 `docs/reports/t-225-t212e-closure-recheck-2026-06-13.md`.

## 운영 배포 자동화 (2026-06-13, `T-108`)

- [x] **T-108 — 운영 배포 자동화 (pinvi T-108 이식).**
  pinvi 원문은 Odroid M1S + N150 16GB 양쪽, multi-platform Docker build,
  streaming replication을 포함했으나, 사용자 재지시에 따라 kor-travel-map에서는
  **streaming replication은 하지 않는다**. 본 저장소 범위는 N150 16GB(`linux/amd64`)와
  Odroid M1S(`linux/arm64`)에 같은 image tag를 배포할 수 있는 buildx 자동화로 닫았다.
  `scripts/docker-buildx.sh`, `npm run docker:buildx`, `.env.example`,
  `docs/deploy.md`, `docs/runbooks/docker-app.md`, ADR-056이 정본이다.

## 태스크 문서 정리 (2026-06-13, Codex)

- [x] **태스크 문서 전반 정리.**
  `docs/tasks.md`를 열린 `[ ]` task만 남기는 백로그로 축소하고,
  `docs/resume.md`를 현재 상태 + 다음 한 작업 중심으로 다시 정리했다.
  중복 완료 체크박스와 오래된 Sprint 2/3 미완료 표기가 현재 인수인계에 노출되지
  않도록 완료 묶음은 이 파일에 요약 아카이브한다.

## 패키지 정체성 / 메트릭 후속 (2026-06-13, `T-226`/`T-227`)

- [x] **T-226 — 배포명/임포트명 재정의: `kor-travel-map` / `kortravelmap`.**
  ADR-054와 `docs/package-identity-rename.md` 기준으로 public distribution
  `kor-travel-map`, Python import root `kortravelmap`, 권장 예시
  `import kortravelmap as ktm`, CLI `ktmctl`, DB `kor_travel_map`,
  Dagster metadata DB `kor_travel_map_dagster`, RustFS bucket/prefix
  `kor-travel-map` 계열로 clean cut했다. `T-226a` 문서 정본,
  `T-226b` 실행계획, `T-226c/d/e` 코드·runtime·소비자 문서 전파가 모두 완료됐다.
- [x] **T-227 — Prometheus 성능 메트릭 표면.**
  `kortravelmap.api` FastAPI app에 `GET /metrics`를 추가했다. HTTP 요청 total/duration,
  in-progress, response size, exception count, DB query count/duration,
  process/runtime metrics를 Prometheus exposition format으로 제공하고
  `surface=public/admin/ops/debug/system/other` label로 공개 REST와 운영 REST를 분리했다.

## API/admin 패키지 분리 (2026-06-13, `T-228`)

- [x] **T-228 — `kor-travel-map-api` backend와 `kor-travel-map-admin` frontend 분리.**
  FastAPI/OpenAPI backend를 `packages/kor-travel-map-api/`로 이동하고,
  `kor-travel-map-admin`은 Next.js admin frontend만 소유하도록 정리했다.
  `KOR_TRAVEL_MAP_API_*`, `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`,
  `packages/kor-travel-map-api/openapi*.json` 기준으로 Docker/CI/scripts/docs를 갱신했다.

## Admin UI 접근성/e2e 보강 (2026-06-10, `T-218`)

- [x] **T-218 — admin UI 상세 구현 점검 + a11y/e2e 완비.**
  화면별 상세 점검과 a11y/e2e 보강을 완료했다. 정본은
  `docs/reports/t-218-admin-ui-hardening-plan-2026-06-10.md`와
  `docs/runbooks/admin-ui-screen-checklist.md`.
  - [x] `T-218a` — 공통 폼 a11y wrapper와 `validateForm` util 도입.
  - [x] `T-218b` — 좌표 scope, offline upload, issue manual override 폼에
        visible label/error/focus 경로 적용.
  - [x] `T-218c` — `/admin/backups` e2e 신설로 admin/ops 16/16 화면 커버 달성.
  - [x] `T-218d` — 위험 액션 음성 경로 e2e 보강.
  - [x] `T-218e` — `Alert` live-region 정합성 보강.
  - [x] `T-218f` — 화면별 상세 회귀 점검 체크리스트 작성.

## Sprint 5 운영 진입 완료 묶음 (2026-06-07~10)

- [x] **T-200~T-204 — 운영 진입 기반.**
  Batch DAG + 정합성 게이트, `ops.feature_consistency_reports`, pre-commit hook,
  PR CI workflow, branch protection 가이드를 완료했다.
- [x] **T-212a~d — ADR-045 전체점검/튜닝 선행 묶음.**
  전체 inventory + Playwright/e2e gap matrix, admin UI 완결성, API endpoint/error/log
  contract, DB/API/frontend 성능 튜닝과 read-heavy 재측정을 완료했다.
- [x] **T-216a~g — REST API 정합성 심화.**
  `/v1` clean cut, pagination 단일화, envelope payload/meta 분리,
  parameter/error/좌표 정합성, 명명 통일, 코드/DB surrogate 명명 전파,
  단일 정본과 버전 거버넌스를 완료했다.
- [x] **T-RV-50~55 — T-RV-04b provider/admin 후속 프로그램.**
  `maplibre-vworld-js` v0.1.3 정합, dedup 수동처리 UI/기본 scope,
  visitkorea 축제 enrichment, krforest 휴양림/수목원, datagokr 박물관/미술관,
  관광지·주차장·KHOA 해수욕장·AirKorea 대기질·공항 provider 후속을 완료했다.

## 실데이터 full reload 최종 검증 (2026-06-12, `T-212e`)

- [x] **T-212e — 실데이터 전체 재적재 + offline upload 실데이터 검증 + 최종 리포트.**
  정본은 `docs/reports/t-212e-live-full-reload-final-2026-06-12.md`.
  - 빈 DB(WSL 재설치로 환경 전체 재구축)에서 전 provider Dagster 적재
    **1,095,665 features**(MOIS bulk 980,970 / MCST CSV 13종 102,121 /
    주차장 18,294 / knps_trails 618 등) + weather values 92,923.
  - `full_load_batch_consistency_gate` 최종 report `99159eea` severity_max
    OK, `ops.data_integrity_violations` 0.
  - offline upload 실데이터 CSV/TSV/JSONL 3포맷 종단 `loaded` + #397→#417
    DELETE lifecycle live 검증(좀비 2건 삭제 → 동일 checksum 재업로드 201).
  - Windows Playwright e2e **33/33**, API smoke 17/17, backup→staging
    restore 검증값 운영 정확 일치(1,095,665), 대표 read P99 수집
    (in-bounds 442ms — 클러스터 MV ADR 재판단 입력).
  - 실측 적발 수정: krtour #392/#393/#400/#408/#410/#411/#413/#416/#417/
    #420/#424 + provider 5 repo(datagokr·krheritage·kma·mcst·knps)
    이슈→PR→머지. 이슈 #397/#407/#409 close.

## curated_features + TripMate import (2026-06-12, `T-223`)

- [x] **T-223 — curated_features + TripMate curated_trip_plans import 계약/구현.**
  T-223a~d 전부 완료. 정본은 `docs/curated-features.md`.
  - [x] **T-223a — 문서 계약 정리.**
    책/음식 테마 source 조사, overlay DB 모델, REST/Admin UI/Dagster,
    TripMate 1:1 복사 계약을 정리했다.
  - [x] **T-223b — provider 보강.**
    `python-mcst-api` 중고서점 CSV(provider PR#11),
    `python-datagokr-api` 서울 책방·무슬림 친화 음식점·안산 세계맛집·제주 향토음식점
    fileData + 전국지역특화거리 표준데이터 서비스(provider PR#10)를 반영하고,
    kor-travel-map 변환 함수와 단위 테스트를 추가했다.
  - [x] **T-223c — kor-travel-map DB/API/Dagster/Admin UI.**
    `feature.curated_*` 테이블, seed source/rule, `/v1/curated-*`,
    `/v1/admin/curated-*`, source rule apply, TripMate copy snapshot, OpenAPI/user-client,
    Dagster `curated_features` group, `/admin/curated-features` UI를 구현했다.
  - [x] **T-223d — TripMate 연동.**
    TripMate PR #184(`5966628192a1f7b0c359a6435011f3e2f3f04469`)에서
    krtour REST snapshot을 `app.curated_trip_plans` / `app.curated_plan_pois`로
    복사하고 source version/etag/item provenance를 저장하는 admin import를 머지했다.
    `kor-travel-concierge`는 curated trip plan 생성에 관여하지 않는다.

## TripMate T-130 공개 해수욕장/축제 뷰 API (2026-06-12, `T-222`)

- [x] **T-222 — TripMate T-130 공개 해수욕장/축제 뷰 API.**
  T-222a~c 전부 완료. 정본은 `docs/public-views-api.md`와 TripMate PR#183.
  - [x] **T-222a — API 사양 초안.**
    `/v1/public/beaches*`, `/v1/public/festivals*`, 스키마, category drift,
    KHOA index/축제 월별 집계 결정점을 정리했다.
  - [x] **T-222b — kor-travel-map 백엔드/OpenAPI/user-client 구현.**
    `/v1/public/beaches*`, `/v1/public/festivals*`를 추가하고 user OpenAPI와
    `@kor-travel-map/map-user-client` 타입을 재생성했다. 해수욕장은
    `detail.place_kind='beach'`를 1차 판별로 쓰며, KHOA provider category
    `01020300`은 보조 정보로 유지한다.
  - [x] **T-222c — TripMate 소비 문서/픽스처 동기화.**
    TripMate `/public/beaches*`와 `/public/festivals*`가 krtour
    `openapi.user.json` 기반 schema/client를 소비하도록 연결했다(TripMate PR#183).

## Admin UI/UX 연결성 + 실시간성 (2026-06-12, `T-221`)

- [x] **T-221 — admin UI/UX 시나리오 연결성 + 실시간성 보강.**
  T-221a~e 전부 완료. 정본 점검은
  `docs/reports/admin-ui-scenario-linkage-recheck-2026-06-11.md`.
  - [x] **T-221a — feature 상세/수동 작성 흐름.**
    `/features/[feature_id]` 1급 상세 route와 `GET /v1/admin/features/{feature_id}`,
    `/admin/features/new` 수동 feature 작성 화면(지도 좌표 선택, kor-travel-geo
    geocode/reverse, kind별 form, nearby 중복 후보)을 구현했다.
  - [x] **T-221b — import job 상세/event/cancel.**
    `ops.import_job_events`, `/ops/import-jobs/[job_id]`, job event timeline,
    `POST /v1/ops/import-jobs/{job_id}/cancel`을 연결했다.
  - [x] **T-221c — admin live signal channel.**
    `WS /v1/ops/live` topic 다중화와 frontend TanStack Query invalidation을 구현했다.
  - [x] **T-221d — provider 상세/refresh policy.**
    `/ops/providers` 상세, `provider_dataset` update request, `provider_refresh_policies`
    편집 UI/API를 구현했다. 중복 provider run endpoint는 만들지 않는다.
  - [x] **T-221e — ops logs + debug 재판정.**
    `/ops/logs`에 job event stream을 붙이고, `/debug/explain`·`/debug/fixtures` REST/UI는
    만들지 않는 것으로 정리했다.

## Provider Dagster 완결 — KMA/MCST (2026-06-11, `T-219`/`T-220`)

- [x] **T-219 — KMA weather Dagster 파이프라인 완결.**
  T-219a~c 전부 완료. asset 5종(실황/초단기/단기/중기/특보) + KST schedule +
  cursor/credential guard를 구현했다. 정본은
  `docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2.
  - [x] **T-219a — weather 대상 격자/feature 매핑 조회 기반.**
    `parse_weather_extra_points`(lon,lat;… 파서 + 한국 bbox 검증)와
    `kma_weather_extra_points`/`kma_weather_max_grids_per_run` 설정,
    `list_active_target_coords`(poi_cache_targets),
    `list_active_place_coords`(deleted_at IS NULL — D-12 read 정합)를 추가했다.
    LGT 메트릭은 기등록 확인 후 노후 docstring만 정정했다.
  - [x] **T-219b — 초단기실황/초단기예보/단기예보 asset+schedule.**
    `map_dagster.kma_weather` asset 3종, KST cron(45분/20·50분/02~23시 8회),
    `kma_weather_client` resource(credential guard), cursor `base_datetime` skip/failure 기록,
    fake client 테스트 12종을 추가했다. `python-kma-api@ab1a0b8` 핀 활성화.
  - [x] **T-219c — 중기 + 특보.**
    mid asset(설정 주입 `kma_mid_region_features` JSON — 육상/기온 reg_id 분리,
    미설정 skip, `kma_datagokr_client` resource)과 특보 record resource
    `kma_weather_alert_records`(전국 108, rolling window)→notice 적재를 구현했다.
    ASOS/해수욕장(beach_*)/APIHub 표면 + 특보 구역별 fan-out·좌표 enrichment는
    1차 범위 밖 백로그 비고로 남겼다.
- [x] **T-220 — MCST(python-mcst-api) 신규 provider 풀스택.**
  T-220a~c 전부 완료. 변환/Dagster/fixture·문서를 구현했고 marker `P-12`,
  `DATA_GO_KR_SERVICE_KEY` 공유 기준을 문서화했다. 정본은 같은 리포트 §3과
  `docs/mcst-feature-etl.md`.
  - [x] **T-220a — `providers/mcst.py`.**
    slug 메타표 16종(`MCST_CULTURE_DATASETS` 14 + `MCST_LIBRARY_DATASETS` 2,
    dataset_key `mcst_<slug>`), 공용 `culture_records_to_bundles`,
    `library_records_to_bundles`(한국어 컬럼 방언 관대 조회), 단위 테스트 11종을 추가했다.
    category 신설 없이 기존 코드 매핑과 `place_kind` 세부 구분을 사용한다.
  - [x] **T-220b — Dagster 배선.**
    fetch 2종(`(slug, record)` 튜플 스트림, dataset당 `mcst_max_items_per_dataset` 상한),
    record resource 2종(live), `mcst_features.py` asset 2종(slug별 분리 `_load`,
    `McstLoadResult` 합산 metadata), 주 1회 schedule 2종, definitions 배선을 구현했다.
  - [x] **T-220c — fixture/문서.**
    ETL preview fixture 2종(공용 변환 대표 — independent_bookstores/public_libraries),
    `docs/mcst-feature-etl.md`, external-apis §3.14, provider-contract §3/§12,
    `python-mcst-api@d06e8d2` 핀, CHANGELOG를 갱신했다. dedup pair는 실데이터
    매칭 품질 확인 후 재검토한다.

## Phase 6.7 — Feature 사용자 요청 CRUD/versioning (2026-06-08, `T-215`)

- [x] **T-215a — place/event feature 추가·수정·삭제 admin API + versioning.**
  `/admin/features`에 `POST`, `/admin/features/{feature_id}`에 `PATCH`/`DELETE`,
  `/admin/features/change-requests*` 승인/거절 API를 추가했다.
  `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE=require_review|immediate` 설정에 따라
  요청을 `pending`으로 보관하거나 같은 transaction에서 바로 적용한다. provider 적재는
  `data_origin='provider', data_version=0`, 사용자 요청은
  `data_origin='user_request', data_version=1`로 구분하고
  `feature.feature_versions` snapshot을 남긴다. 사용자 요청 삭제는 soft delete이며
  provider 재적재나 snapshot 누락 정리로 되살리지 않는다.
- [x] **T-215b — admin UI feature change queue 화면.** (2026-06-09)
  `/admin/features/change-requests` 화면을 추가해 `GET /admin/features/change-requests`
  목록, add/update/delete 요청 form, approve/reject 동작을 연결했다. 목록 meta에
  `review_mode`를 추가해 `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE` 현재값을 빈 큐에서도
  표시한다. 기존 정본 mutation endpoint만 사용하며 새 중복 REST 표면은 만들지 않았다.
- [x] **T-215c — frontend generated type/e2e workflow 보강.** (2026-06-09)
  OpenAPI 생성 schema 타입 기반 route mock으로 pending→approve→applied, immediate mode
  create, update/delete 요청 생성, soft delete 적용 표시와 action delete 필터 e2e를 추가했다.
  Next RSC prefetch는 mock 범위에서 제외해 document/API 요청을 분리했다.


## Phase 6.6 — REST API v1 정리 후속 (2026-06-08, `T-214`)

전 표면 계약 정본은 `docs/rest-api.md`, TripMate 소비 view는 `docs/tripmate-rest-api.md`.
기준 입력은 `docs/reports/api-endpoint-review-2026-06-08.md`와 TripMate
`docs/integrations/kor-travel-map-rest-api.md`. 사용자 결정으로 `/tripmate/feature-update-requests*`는
admin 영역으로 이동한다.

- [x] **T-214a — REST API 정본 문서 작성.**
  Versioning, envelope, parameter 규약, endpoint naming, 중복 처리, 누락 API를
  종합해 `docs/tripmate-rest-api.md`를 목표 `/v1` 계약과 현재 구현 gap 중심으로
  재작성했다. `docs/openapi-admin-contract.md`, `docs/tripmate-integration.md`,
  `docs/poi-cache-update-targets.md`, `docs/architecture.md`의 충돌 문구도 정리했다.
- [x] **T-214b — 사용자/서비스 API `/v1` prefix 도입.** (2026-06-09)
  `features`/`categories`/`providers` 라우터를 `application.include_router(..., prefix="/v1")`로
  `/v1/*` 노출(`/features/*`(batch 포함)·`/categories`·`/providers/{provider}/last-sync`).
  구 unversioned 경로는 유지하지 않는다(clean cut, alias 없음). liveness `/health`·`/version`은
  비버저닝 유지. `USER_OPERATIONS`·OpenAPI 두 profile·frontend 호출부(`api/features.ts`·
  `api/poiCacheTargets.ts`)·generated type·e2e mock·테스트 일괄 갱신. admin/ops/debug의
  `/v1` 이동은 ADR-048/T-216a에서 처리한다.
- [x] **T-214c — `/tripmate/feature-update-requests*` 제거, admin-only 전환.**
  user OpenAPI와 `USER_OPERATIONS`에서 `POST/GET /tripmate/feature-update-requests*`를
  제거하고 `/admin/feature-update-requests*`만 정본으로 남긴다. TripMate 사용자 제안 큐는
  TripMate app DB 소유로 문서화하고, 운영자 승인 뒤 admin API 호출로 연결한다.
- [x] **T-214d — `/tripmate/*` namespace 제거, batch를 `POST /features/batch`로 일반화.**
  (2026-06-09, 사용자 지시 — kor-travel-map은 TripMate 전용이 아니다.) `tripmate_router` 제거,
  batch를 `features_router`의 `POST /features/batch`로 옮기고 service-token을 route-level
  gate로 유지(ServiceToken scheme 보존). `USER_OPERATIONS`·OpenAPI 두 profile·frontend
  generated type·테스트·문서 일괄 갱신. `/v1` prefix 부여는 T-214b/T-216a에서. 응답은 list
  `items[]`와 충돌하지 않게 `data={found:{feature_id:Feature},missing[]}`로 정렬(후속).
- [x] **T-214e — pagination/parameter 일관성 정리.** (2026-06-09)
  규약 확정: **페이지 가능한 목록 = `page_size`+`cursor`**(search·nearby·admin/ops),
  **bounded 지도 조회 = `limit`**(`/features` flat·`/features/in-bounds` — 뷰포트 로드),
  다중 값 = 단수 반복 query parameter, bbox = `min_lon/min_lat/max_lon/max_lat` 4-float.
  코드: `/v1/features/search`의 CSV `bbox` 제거 → 4-float, `limit`→`page_size`,
  `_parse_bbox_csv` 삭제. `/features` flat은 bounded map이라 `limit` 유지(admin/지도 호환).
  (envelope `meta.page`·`total` opt-in·2-티어 캡 등 심화는 T-216b/c, ADR-048.)
- [x] **T-214f — POI cache target write 표면 결정.** (2026-06-09)
  **결정: TripMate 직접 write 미허용 — admin/operator flow만.** POI cache target
  upsert/delete는 `/admin/poi-cache-targets*`(인프라 SSO + kill-switch)로만 수행하고,
  service-safe `/v1/poi-cache-targets/*` write 경로는 **추가하지 않는다**. TripMate는 등록된
  target 기준 read(`GET /v1/features/nearby/by-target`)만 소비. (rest-api.md·
  tripmate-rest-api.md 명시.)
- [x] **T-214g — error/idempotency/rate-limit/deprecation header 규약 명시.** (2026-06-09)
  규약을 `docs/rest-api.md`에 단일 표로 고정: `X-Request-ID`(구현됨 — 모든 응답),
  problem+json `code` enum(§4), `Retry-After`(LOCK_BUSY/RATE_LIMITED), `Idempotency-Key`·
  `RateLimit-*`·`Deprecation`/`Sunset`(규약 정의 + 적용 시점 명시; idempotency/rate-limit
  구현은 T-216 외부 변경 호출에서). 실제 problem+json 본문 전환은 T-216d.
- [x] **T-214h — endpoint naming cleanup.** (2026-06-09)
  `/debug/health`·`/debug/version` **제거**(ADR-048 clean cut — 공용 `/health`·`/version`과
  중복). `health.py`/`version.py` 라우터 삭제, app.py/__init__ 정리, 상태확인은
  `/health`·`/version`(public_status) + `/ops/health-deep`(readiness)로 수렴. frontend
  `useHealth`/`useVersion`을 public `/health`·`/version`(envelope) 소비로 repoint.
  `dedup-review`/`enrichment-review` **복수화는 T-216e(major 컷)로 이월** — 본 task에선
  결정만(소비자 영향 큰 path 개명은 ADR-048 명명 묶음에서 일괄).


## 문서 정합성 백로그 (T-DA, 2026-06-06)

문서 전수 정합성 감사 결과. 전체 지적·근거·파일위치·의사결정은
**`docs/reports/docs-consistency-audit-2026-06-06.md`** 가 정본. task id는 `T-DA-NN`,
사용자 결정은 `DA-D-NN`. 사용자 결정(DA-D-01 포인터 대체 / DA-D-02 한 PR 반영)에
따라 T-DA-01~10은 **본 배치에서 반영 완료**.

- ~~**T-DA-01** CLAUDE.md §2 "현 단계" 전면 stale(PR#149/Sprint4 완료)~~ ✅ DA-D-01(A)
  포인터 대체.
- ~~**T-DA-02** CLAUDE.md geocoding 로컬 포트 `8888`~~ ✅ → `12201`(`.env.example` 정합).
- ~~**T-DA-03** CLAUDE.md ADR "001~046 / 다음 047"~~ ✅ → "001~047 / 다음 **048**".
- ~~**T-DA-04** AGENTS.md "코드 작성 단계"(PR#156) stale~~ ✅ 포인터 대체.
- ~~**T-DA-05** sprints/README "현 위치"(PR#149) + Sprint5 "🟡 진입 준비"~~ ✅ 포인터
  대체 + "🟢 진행 중".
- ~~**T-DA-06** category 개수 "141건" 표기(코드=144)~~ ✅ category.md/debug-ui-package.md/
  decisions.md 라벨을 **144**로 통일(§4 트리는 이미 ADR-027 3건 포함 완성 상태였음).
- ~~**T-DA-07** architecture.md 큰그림 의존체인에서 `category` 누락~~ ✅ 추가.
- ~~**T-DA-08** decisions.md ADR-025 "Next.js 15"/"port 8610" 현행 교차참조 없음~~ ✅
  현행 기준 note 추가(역사 본문 보존).
- ~~**T-DA-09** decisions.md ADR-002 체인이 `api` 포함·`category` 누락~~ ✅ 현행 체인
  note 추가.
- ~~**T-DA-10** decisions.md ADR-036 제목 `v0.1.0`~~ ✅ 현행 핀 v0.1.2 note 추가.
- ~~**T-DA-12** CLAUDE.md §5 "전체 22개 룰은 SKILL.md §4"(실제 26개)~~ ✅ → **26개**.
- ~~**SKILL.md 2차 스윕**: §8 ADR "001~046/047" + §9 "코드 작성 단계" 상태 블록
  (PR#149/Sprint4 완료)~~ ✅ T-DA-01/03과 동일 처리(포인터 대체 + 001~047/048).
- ~~**README.md 3차 스윕**: 상단 "현재 상태"(PR#155/#156/Sprint4 완료) 블록 + "빠른 시작
  (Sprint 4 완료…)" 헤더~~ ✅ T-DA-01과 동일 처리(DA-D-01(A) 포인터 대체, 기준값만
  유지). entry doc 4종(CLAUDE/AGENTS/SKILL/README) 상태 블록 drift 모두 정리 완료.
- **T-DA-11** `openapi-admin-contract.md` ↔ 구현 endpoint/error/log 전수 대조 —
  외부 노출 API 한정으로 **수행함**(감사 §8 = 아래 T-DA-13~17). 라우터별 세부
  contract 전수는 계속 `T-212a`/`T-212c`로 위임.

### 외부 노출 API 일관성/완결성 (감사 §8, 2026-06-06 추가)

생성 spec(`openapi.json` 35 path / `openapi.user.json` 7 path) ↔ contract 문서 대조.
코드 영향이 있어 본 문서 PR과 분리(결정 DA-D-03/04 확정 후 반영).

- ~~**T-DA-13** (MED, 빠진 기능, **DA-D-04 = T-212 묶음**) `/admin/issues`
  GET/GET{id}/PATCH(resolve/ignore/reopen/retry_geocode/retry_reverse_geocode/
  apply_kor_travel_geo_address/manual_override)~~ ✅ **구현 완료(2026-06-07)**. ADR-046
  주소/좌표 이슈 운영자 수동 처리 API. `routers/admin_issues.py`(목록 keyset cursor +
  단건 detail + PATCH 7 action) + 신규 `infra/feature_address_repo.py`(feature.features
  UPDATE + `ops.feature_overrides` upsert) + kor-travel-geo `geocoding` 정/역지오코딩.
  `{data, meta}` envelope. 단위 14 + PostGIS 통합 3 테스트. 목록 `q`(message/feature_id/
  source_record_key ILIKE) + `bbox`(연결 feature 4326 GiST `&&`) 필터도 구현 완료
  (`ops_repo` 확장 + 통합 테스트). admin UI(승인/거절 화면)는 **T-212b** 별도 에이전트
  후속.
- ~~**T-DA-14** (LOW, doc) contract §4 표 `admin-providers` 미구현 표기 누락~~ ✅
  "(미구현 — T-207b 취소, feature-update-requests provider_dataset scope 대체)" 표기.
- ~~**T-DA-15** (MED, API 일관성, **DA-D-03 = 전면 통일**) list 응답 셰입 이원화
  (`{data,meta}` vs `{count,items,next_cursor}`) → 전면 envelope 통일~~ ✅ 3 flat list
  라우터 모두 `data.{items,next_cursor}` + `meta.{count,duration_ms}`로 통일.
  - [x] `/admin/feature-update-requests` (#250, 2026-06-06).
  - [x] `/admin/offline-uploads` (#251, 2026-06-06).
  - [x] `/admin/poi-cache-targets` (2026-06-06).
- ~~**T-DA-16** (MED, API 일관성, **DA-D-03 = 전면 통일**) 단건 응답 envelope 불일치
  (bare object 6종 + import-jobs/{id} `{data}`만) → `{data,meta}` 통일~~ ✅ 감사 열거
  단건 전부 통일 완료(추가 발견 nux-seen은 T-DA-18로 분리).
  - [x] `/admin/feature-update-requests/{id}`·`/tripmate/feature-update-requests/{id}`
    → `{data, meta}` (#250, 2026-06-06).
  - [x] `/admin/offline-uploads/{id}` → `{data, meta}` (#251, 2026-06-06).
  - [x] `/admin/poi-cache-targets/{id}` → `{data, meta}` (#252, 2026-06-06).
  - [x] `/ops/metrics` → `{data: OpsMetricsData, meta:{duration_ms}}`,
    `/ops/import-jobs/{job_id}` → `meta.duration_ms` 추가 (#253, 2026-06-06).
  - [x] `/ops/dagster/summary` → `{data: DagsterSummaryData, meta}`,
    `/debug/mois-license/{id}` → `{data, meta(cached, duration_ms)}` (2026-06-06).
- ~~**T-DA-18** (LOW, API 일관성, **DA-D-03 추가 발견**) `POST /ops/dagster/nux-seen`
  flat bare → `{data, meta}`~~ ✅ `DagsterNuxSeenData` + envelope, 4 return을
  `_nux_seen_response` 헬퍼로 wrap. 프런트 `useMarkDagsterNuxSeen` 본문 미소비라
  소비측 무변(2026-06-06). **DA-D-03 전면 통일(T-DA-15/16/18) 코드 전환 완료.**
- ~~**T-DA-17** (INFO) contract 문서 구현/미구현 혼재 표기~~ ✅ §4 표·§4.1 미구현 배지
  반영(전체 endpoint 상태 컬럼화는 T-212c).
- **DA-D-03 = 전면 통일** (확정) — 코드 전환은 별도 PR(T-DA-15/16). 본 PR은 표준 문서화.
- **DA-D-04 = T-212 묶음** (확정) — `/admin/issues`는 T-212b/c. 본 PR은 미구현 배지.


## 코드 리뷰 후속 백로그 (PR#181~#233, 2026-06-06)

직전 리뷰(#153~#179) 이후 머지된 비-T-RV 실질 PR(정합성 Phase 2 F5~F8 / T-200
batch gate / 운영 게이트 T-202~204 / T-208i 등)을 상세 리뷰한 결과. T-RV-\* 구현
PR과 T-DA 문서 PR(#227/#230)은 리뷰 생략. 정본은
**`docs/reports/pr-181-233-review-2026-06-06.md`**. 신규 지적은 **전부 LOW**(관측
전용 WARN 케이스의 count 의미/성능) — 운영 진입을 막지 않는다. (검토 중 세운 F5
join fan-out·F7 score 스케일 risk는 schema PK/CHECK로 해소 = 결함 아님.)

- ~~**T-RV-38** (LOW, consistency F8) `infra/consistency.py:529-557` — file row가
  `feature_missing` + `metadata_missing_object` 동시 충족 시 count 2 증가(distinct
  orphan보다 과다).~~ ✅ `count`는 distinct metadata/object row 기준으로 dedup하고,
  세부 문제유형은 `sample_ids`와 `metadata`에 보존한다.
- ~~**T-RV-39** (LOW, consistency F4/WARN) `infra/consistency.py:400-410` — F4 임계
  초과 시 `count=pending`(백로그 전체 수)이 `total_violations`/`by_severity.WARN`에
  혼입.~~ ✅ 임계 초과형 `count=1`, 실제 pending/threshold는
  `metadata.pending_count`/`summary.case_metadata.F4`에 분리한다.
- ~~**T-RV-40** (LOW perf, consistency F6) `infra/consistency.py:146-185` — F6가
  `feature.features`를 LATERAL `jsonb_path_query`로 4회 풀스캔.~~ ✅
  `candidate_features` CTE로 삭제되지 않고 detail 후보가 있는 feature를 한 번만 읽고,
  4개 JSONPath period 추출은 단일 `CROSS JOIN LATERAL` 안으로 모았다.
- ~~**T-RV-41** (LOW 전제, batch_dag) `infra/batch_dag.py:454-460` — `CONCURRENTLY`
  refresh는 MV UNIQUE 인덱스 + 사전 populate 전제. 현재 MV 없어 latent.~~ ✅
  **`T-101`** MV 도입 체크리스트와 performance/Dagster 문서에 UNIQUE 인덱스 +
  최초 비-concurrent populate 전제를 고정했다.


## 코드 리뷰 후속 백로그 (PR#153~#179, 2026-06-04)

리뷰 없이 머지된 ADR-045 구현 배치(#153~#179)를 영역별 상세 리뷰한 결과.
전체 지적·근거·파일위치는 **`docs/reports/pr-153-179-review-2026-06-04.md`** 가
정본. task id는 `T-RV-NN`. 권장 처리 순서는 리포트 §5.

**HIGH (운영/계약/보안 — 선반영):**
- ~~**T-RV-01/02** Dagster 운영 형상 (D-2): metadata를 별도 `kor_travel_map_dagster`
  Postgres DB로 (현재 SQLite 폴백) + `dagster dev`→webserver/daemon 분리.~~
  ✅ `dagster-db-init`, `dagster` webserver, `dagster-daemon`,
  `docker/dagster.yaml` Postgres storage, `dagster-postgres` dependency와 compose
  회귀 테스트를 추가했다.
- ~~**T-RV-03** Dagster `kor_travel_map_client` resource engine dispose 누수.~~
  ✅ generator resource로 전환해 run/tick 종료 시 `AsyncEngine.dispose()`를 호출하고,
  running event loop 안에서도 teardown이 동작하는 회귀 테스트를 추가했다.
- **T-RV-04** Dagster provider 서비스키 resource 미구현(D-15, feature-load asset
  provider fetcher 기본 wiring 미완료).
  - ✅ **T-RV-04a**: provider record key별 guard resource와
    `KOR_TRAVEL_MAP_*` credential env mapping을 등록했다. 기본 `defs`는 더 이상 generic
    `_missing_resource`로 죽지 않고, resource materialize 시 provider/package/env
    안내를 내며 secret 값을 숨긴다.
  - **T-RV-04b**(✅ 완료 2026-06-08, provider 순차 wiring): provider public client live fetcher를
    실제 record iterable로 연결. 패턴 = `provider_fetchers.fetch_<provider>(settings)`
    (lazy provider import, credential 없으면 guard 메시지) + `resources.
    build_provider_record_live_resource(spec, fetch)`로 해당 resource_key만 guard→live 교체.
    - [x] **datagokr_cultural_festivals**(festival, #261) — `DataGoKrClient.festival.
      iter_all()`. dagster 단위 테스트(fake client) + 37 dagster suite green.
    - **나머지 6종은 설계 결정 선행 필요** — 적합성 감사
      `docs/reports/t-rv-04b-provider-fetcher-audit-2026-06-07.md`. 요약:
      - [x] **krheritage_events**(2026-06-07) — **ADR-044 재조정 + wiring**. 검증 결과
        `HeritageEvent` 필드명(starts_on/ends_on/place/tel_name/address)이 krtour Protocol
        (start_date/venue_name/...)과 불일치 + `raw` 부재. 조치: **upstream PR**
        `python-krheritage-api#4`(HeritageEvent.raw 주입, sibling 모델 정합, merged) +
        krtour `KrHeritageEvent` Protocol/transform을 provider 필드명에 맞춰 재정렬(+테스트).
        fetcher = `HeritageClient.event.iter_months()`(provider 기본 rolling window
        months_back=1/ahead=12). dagster fetcher 단위(fake) + 39 dagster suite green.
      - [x] **krex_rest_areas**(2026-06-07) — ADR-044 재정렬 + **option 2 파생 자연키**.
        `RestArea`에 안정 id·address 없음(사용자 결정: 안정키 있으면 사용·없으면 파생) →
        `_rest_area_natural_key`=`name::route_name::direction`(`|`는 ADR-009 예약 → `::`).
        Protocol을 RestArea 필드명(route_name/lat/lon/phone_number)으로 재정렬, uni_id/address
        제거. admin etl_fixtures/etl_live 어댑터도 갱신. provider 측 안정 id/address 노출은
        **upstream 이슈 `python-krex-api#7`**로 분리(AI agent 작업용). fetcher=`restarea.
        list_all` 페이지네이션, dagster 단위 + 통합 green.
      - [x] **krex_traffic_notices**(2026-06-07) — ADR-044 재정렬: Protocol을 `Incident`
        실제 shape(route_no/incident_type/message/started_at/ended_at/raw)로, krtour-side
        파생(notice_id=`::` 복합키+payload_hash, title 합성, notice_type=normalize, valid_from·
        until=방어적 파싱, severity=None, source_agency="한국도로공사", coord=None).
        coordless notice는 raw_address=route로 strict 검증 통과. fetcher=`traffic.incident`
        페이지네이션(`krex_ex_api_key`). **잔여(krtour follow-up)**: EX `incidentType`
        숫자코드→notice_type 매핑 테이블(현재 대부분 "traffic" 기본값). 일시적 incident의
        영속 Feature 적재 = 재실행 갱신 + `valid_until` 만료(설계 메모).
      - [x] **opinet_stations** — provider 보강 + krtour wiring(bbox+POI-타깃) 완료(2026-06-08).
        조사 결론(2026-06-07): OpiNet OpenAPI에 지역/전국 bulk 주유소 목록 엔드포인트가
        **물리적으로 없음**(station 반환은 aroundAll 반경≤5km/lowTop10 top20/detailById 단건뿐,
        나머지는 코드/가격 집계). `python-opinet-api#7` 코멘트로 결론 기록.
        - [x] **provider 보강**(`python-opinet-api#8` merged, **v0.2.0**): `iter_stations_in_bbox()`
          (sync+async) — bbox를 aroundAll 반경 격자(`radius*√2`)로 덮고 `uni_id` dedup하는
          **근사 enumeration**. 한계(면적 비례 호출수 급증→bounded 권장, tel/lpg_yn 부재→detail
          N+1) README/docstring 명시.
        - **krtour wiring 후속** — 사용자 결정(2026-06-08): **bbox + POI-타깃 둘 다 지원**. 3 PR:
          - [x] **opinet-1 ADR-044 재정렬**(2026-06-08) `OpinetStationItem` Protocol을 provider
            `Station` 필드명(uni_id/name/brand/address_road/address_jibun/lon·lat float)에 정렬,
            `tel`/`lpg_yn`은 `StationDetail` 한정이라 Protocol 필수에서 빼고 transform이 `getattr`로
            보강(`Station`이 그대로 만족). `stations_to_bundles`/ETL fixture/etl_live 어댑터/단위·통합
            테스트 갱신. 게이트: ruff/mypy(map 85/admin 26)/unit+lint 965(coverage 81%)/full 1168 green.
          - [x] **opinet-2 bbox fetcher**(2026-06-08): settings `opinet_scope_mode`(disabled/bbox/
            poi_cache_target) + `opinet_scope_bbox` + `opinet_scope_radius_m` + `fetch_opinet_stations`
            (`OpinetClient.iter_stations_in_bbox`, uni_id dedup, finally close) + resource guard→live
            (기존 `feature_place_opinet_stations` asset 그대로 소비). poi_cache_target 모드는 명확
            guard로 opinet-3 대기. 게이트: ruff/mypy(map 85/dagster 13/admin 26)/lint-imports/unit+lint
            965(coverage 81%)/full 1168/dagster 85 green.
          - [x] **opinet-3 POI-타깃**(2026-06-08): `fetch_opinet_stations`의 `poi_cache_target`
            분기 연결. `_opinet_poi_target_bboxes`가 `settings.pg_dsn`(async)→sync psycopg DSN으로
            `ops.poi_cache_targets`의 opinet 활성 target(lon/lat/radius_km, update_enabled,
            non-deleted) 조회 → `_center_radius_to_bbox`(위경도 근사)로 bbox 변환 → 기존
            `_enumerate_opinet_stations`로 enumerate(target 간 uni_id dedup). 단위(math/enumerate/
            empty) + 통합(`test_opinet_poi_scope` 실 PostGIS seed→조회) 테스트. **→ T-RV-04b 완전 종료.**
            - **리뷰 수정(#304, 2026-06-08)**: `external_system`은 provider명이 아니라 외부 호출자
              (tripmate 등) — `='opinet'` 필터 제거(실제 등록 target 누락 P1). active 정의를
              `scope_repo`와 동일하게(`deleted_at` 없음 + `update_enabled` + `refresh_policy<>'disabled'`
              P2) + opinet `provider_overrides` `targeted_policy='disabled'` 옵트아웃 제외. 통합
              테스트를 tripmate/kakao + disabled/update-off/deleted/optout seed로 회귀 보강.
              게이트: ruff/mypy(3pkg)/lint-imports/dagster 87/coverage 81%/POI 통합 green.
      - [x] **mois_license_records**(Phase B, 2026-06-07) — clean match(provider `PlaceRecord`이
        `MoisLicensePlaceRecord` Protocol 전부 충족, 재조정 불요). fetcher
        `fetch_mois_license_records`가 미리 sync된 MOIS 소스 SQLite DB(설정
        `mois_source_db_path`, env `KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH`)에 sqlite Session 열고
        `mois.db.iter_open_place_records(service_slugs=PROMOTED_SERVICE_SLUGS)` stream. DB
        부재 시 명확 실패. dagster 단위(temp-DB 실측 + guard) green.
        - [x] **mois Phase A(소스 DB sync)**(2026-06-07) — `mois_source_sync.py`:
          순수 helper `sync_mois_source_db(settings, service_slugs=None)` + Dagster op
          `mois_localdata_source_sync` + job + 주간 schedule(STOPPED, `0 4 * * 1` KST).
          provider `mois.create_sqlite_schema` → keyless `LocalDataFileClient` →
          `sync_localdata_source_db(service_slugs=PROMOTED_SERVICE_SLUGS, commit=True)`로
          LOCALDATA 다운로드→소스 DB 적재. **정정: 공개 파일 포털(`file.localdata.go.kr`)
          이라 API key 불요(네트워크만 필요)** — provider `LocalDataFileClient`에 key
          파라미터 없음. dagster 단위(fake mois 5 + op + schedule) green. 실데이터 검증은
          T-212e.
      - [x] **knps_point/geometry**(2026-06-07) — **provider 보강**으로 해결. 사용자
        지시(적극 수정)대로 `python-knps-api#7`(merged, v0.2.0)에 헤더 정규화 typed
        record(`KnpsPlaceRecord`/`KnpsGeoRecord`) + `read_place_records`/`read_geo_records`
        추가. krtour는 best-guess 컬럼 매핑 폐기, provider typed record 직접 소비.
        fetcher는 **async generator**(다운로드/파싱 async)이고 live builder를
        `Iterable | AsyncIterator`로 확장. dataset key(`knps_visitor_centers`/`knps_trails`)는
        settings 값을 fetcher/asset이 공유(`SETTINGS_VALUE_RESOURCES`). keyless라 credential
        불요. dagster 단위(fake knps client) green. 실 fetch 검증은 T-212e.


## 최근 완료 (2026-05-31~2026-06-03)

- **T-208h** (2026-06-03): `/admin/offline-uploads*` backend와 admin UI 기본
  upload 화면을 추가했다. JSON/JSONL `FeatureBundle` 파일을 RustFS/S3 store에 쓰고,
  `ops.offline_uploads` row 생성/list/detail, Dagster GraphQL
  `offline_upload_load` launch까지 연결했다. CSV/TSV validation/column mapping은
  T-208i로 남긴다. WSL live smoke에서 upload → Dagster `SUCCESS` → DB
  `loaded/done/progress=100`을 확인했고, Windows Playwright `admin-ops.spec.ts`는 새
  `/admin/offline-uploads` route 포함 6/6 통과했다.
- **T-208b 후속** (2026-06-03): RustFS/S3 호환 `offline_upload_store` resource와
  Docker RustFS bucket init을 구현했다. API `12101`, console `12105`, bucket
  `kor-travel-map`/`krtour-uploads` 기준으로 실제 put/get smoke를 확인했다.
- **T-208f** (2026-06-03): `consistency_dedup_refresh` Dagster maintenance job을
  추가했다. DB에 적재된 provider/dataset scope를 다시 읽어 pair/sibling dedup 후보를
  큐에 upsert하고, 이어서 F1~F4 consistency report를 저장한다. schedule은
  `consistency_dedup_refresh_daily_schedule`이며 기본 `STOPPED`다.
- **T-211b** (2026-06-03): admin frontend 전역 app shell/navigation, 운영 홈
  dashboard, `/ops/import-jobs`, `/ops/consistency`, `/admin/dedup-review`,
  `/admin/feature-update-requests`, `/admin/poi-cache-targets` 화면을 최신 REST/Dagster
  계약에 맞춰 구현했다. `/admin/dagster`는 Dagster webserver embed와 자체 summary
  UI를 함께 보여주며 schedules/sensors 정보를 노출한다.
- **T-211a** (2026-06-03): admin UI 최신화 선행 gap audit과 typed frontend API
  layer를 추가했다. `/ops/import-jobs` 정본, `/features/nearby/by-target` 범위,
  backend gap을 문서화하고 화면 구현 선행 조건을 정리했다.
- **T-208d** (2026-06-03): `packages/kor-travel-map-dagster`에 Feature 적재 asset 9개의
  KST schedule과 asset job을 등록했다. 모든 schedule은 `Asia/Seoul` 기준이고,
  외부 API 호출 분산을 위해 분/요일을 나눴으며 기본 status는 `STOPPED`다.
- **T-207g** (2026-06-03): OpenAPI export를 admin 전체
  `packages/kor-travel-map-api/openapi.json`과 TripMate/user subset
  `packages/kor-travel-map-api/openapi.user.json`으로 이원화했다. CI drift gate는
  `--profile all --check`로 두 산출물을 함께 검증한다.
- **T-207e** (2026-06-03): `GET /features/in-bounds`, `GET /features/search`,
  `GET /features/{feature_id}` envelope 상세, `POST /tripmate/features/batch`를
  연결. 기존 `GET /features` bbox raw 응답은 admin frontend 호환용으로 유지하고,
  TripMate/public 응답은 `{data, meta}` envelope로 분리했다.
- **T-207d** (2026-06-03): `/ops/metrics`, `/ops/import-jobs`,
  `/ops/import-jobs/{job_id}`, `/ops/consistency/reports`,
  `/ops/consistency/issues` backend를 연결. `infra.ops_repo`는 import job,
  consistency report, data integrity issue를 read-only keyset cursor로 조회한다.
- **T-207c** (2026-06-03): `/admin/features` 목록/비활성화, `ops.feature_overrides`
  `prevent_provider_reactivation`, provider upsert status 보호, `/admin/dedup-review`
  목록/결정/merge backend를 연결. 이후 T-215a에서 사용자 요청 기반 place/event
  추가·수정·soft delete API를 붙였다. hard delete와 별도 audit log는 여전히 후속이다.
- **PR#168** (merged 2026-06-03): Dagster `feature_update_request_queue_sensor` +
  `feature_update_request_worker` + failure sensor. queued/now request를
  `AsyncKorTravelMapClient.execute_feature_update_request()`로 실행하고, 실패 시
  request/import job 실패 전이와 notifier payload를 보강.
- **PR#167** (merged 2026-06-03): `/admin/poi-cache-targets` admin API와
  `/features/nearby/by-target` summary 조회. target CRUD/list/detail/delete,
  PostGIS `coord_5179` 거리 조회, filter/sort/cursor, OpenAPI export, unit/integration
  테스트.
- **PR#166** (merged 2026-06-03): `/admin/feature-update-requests` admin API. POST(dry-run/actual),
  GET(list/detail), cancel, run-now 재큐잉, OpenAPI export, list filter 통합 테스트.
- **PR#165** (merged 2026-06-03): `infra.feature_update_executor`, `cache_target_keys`
  resolver, target link 재계산, provider refresh policy skip, runner 기반 DB 적재 통합
  테스트.
- **PR#164** (merged 2026-06-03): `alembic 0009`로
  `ops.data_integrity_violations`, `ops.poi_cache_targets`,
  `ops.poi_cache_target_feature_links`, `ops.provider_refresh_policies`를 추가하고,
  ORM row + raw SQL repo + PostGIS 통합 테스트를 구현.
- **PR#163** (merged 2026-06-03): T-206a-geo 검증 완료 문서화 +
  RustFS dev compose 예시 host port `12101`/`12105` 정렬.
- **PR#162** (merged 2026-06-03): `AsyncKorTravelMapClient` feature update request
  메서드 4종 + top-level client export + RustFS 포트 12101/12105 문서 정렬.
- **T-206a-geo 확인** (2026-06-03): `kor-travel-geo` main의
  `/v2/regions/within-radius` 구현과 optional 실제 PostGIS 테스트를 재검증.
  WSL targeted test `15 passed, 1 skipped`, 로컬 12201 server smoke는 `sigungu`
  `11650`(서초구) contains 응답 확인.
- **PR#161** (merged 2026-06-03): `infra.feature_update_repo` request/import job
  lifecycle repository + kor-travel-geo REST API 로컬 포트 12201 문서/설정 정렬.
- **PR#160** (merged 2026-06-03): `infra.scope_repo` scope resolver.
- **PR#159** (merged 2026-06-03): `ops.feature_update_requests` Alembic 0008 +
  ORM 매핑 + DDL 계약 통합 테스트.
- **PR#158** (merged 2026-06-02): Docker API 컨테이너의 Dagster URL을
  `KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL` 기본값(`http://dagster:12302`)로 분리.
- **PR#157** (merged 2026-06-02): admin UI `/admin/dagster` + backend
  `GET /ops/dagster/summary` + Dagster webserver embed.
- **PR#156** (merged 2026-06-02): Docker 이미지/compose, API `12301`, admin UI
  `12305`, Dagster `12302` 고정 포트, `.env` key mapping, 기동/포트 종료 스크립트.
- **PR#155** (merged 2026-06-02): kor-travel-map-owned Dagster Feature ETL 1차.
  `packages/kor-travel-map-dagster/` code location과 9개 Feature asset runner, PostGIS
  적재 통합 테스트.
- **PR#114** (merged 2026-05-31): geocoding live 기본 포트 정합(현재 12201),
  Next.js 16 + `maplibre-vworld-js#v0.1.2`, GDAL 3.8.4 고정, Windows Playwright
  e2e 14/14, 관련 문서 갱신.
- **PR#110~#112**: Windows Git + NTFS source-of-truth 정책, WSL 실행/Playwright
  분리, journal/resume 정책 로그 보강.
- **PR#96~#100**: Sprint 4 prep, `/features` UX 보강, map-marker-react 구현,
  direct-main push revert와 통합 검증 보고서 재적용.


## 완료 이력 (Sprint 2)

- **PR#49** (merged 2026-05-28): `maplibre-vworld` v0.1.0 의존 핀 정합 — 기존
  `^1.0.0`은 이중 오류(버전 미존재 + npm 미게시) → `github:digitie/maplibre-
  vworld-js#v0.1.0` git URL+tag 핀 + `zod ^4.4.3`(peer) + ADR-036 amendment.
- **PR#48** (merged 2026-05-28): agent worktree 접두사 `geo-*` → `kor-travel-map-*`
  일괄 rename (7 normative docs) + 본 `tasks.md` 최신화 (PR#19~#47 반영).
- **PR#47** (merged 2026-05-28): 디버그 UI ETL preview `?source=live` 활성화 +
  8 provider API key(`SecretStr`) settings + `.env.example`. KMA 3 dataset
  (short/nowcast/ultra_short_forecast) 실 호출, 나머지 8은 framework(501).
  `etl_live.py` httpx async loader + LIVE_LOADER_REGISTRY. **CI red 3종 동반
  해소**: httpx dep 누락 / Alembic 1.18 `path_separator` deprecation /
  Alembic 1.18 async migration commit 안 됨(env.py) / coord_5179 assert
  대소문자. 450+21 green.
- **PR#46** (merged): KMA weather_alerts → notice FeatureBundle (alert×region
  fan-out) + krex TRAFFIC_NOTICE_CATEGORY 99000000 정정 + ETL preview registry
  11 dataset.
- **PR#45** (merged): Sprint 2 §2.4 krex 휴게소 multi-kind — 4 Protocol + 4
  변환(rest_areas place / prices food|fuel / weather observed / traffic notice)
  + 동일 feature_id 통합 검증.
- **PR#44** (merged): 디버그 UI ETL preview 라우터 3종 (`providers`/`{provider}/
  datasets`/`{provider}/{dataset}/preview`) + frontend `etl/page.tsx`. dry-run.
- **PR#43** (merged): Sprint 2 §2.3 마무리 — opinet `stations_to_bundles`
  (gas station place Feature, category 06020000).
- **PR#42** (merged): Sprint 2 §2.3 진입 — `PriceValue` DTO + `PriceDomain` +
  `make_price_value_key` + opinet `prices_to_values`.
- **PR#41** (merged): KMA `ultra_short_forecast_to_weather_values`
  (getUltraSrtFcst) + LGT(낙뢰) metric.
- **PR#40** (merged): `python-*-api` 라이브러리 status sweep — pyproject
  `[providers]` extra Sprint 그룹화 + provider-contract §12 git URL/sha 표.
- **PR#39** (merged): KMA `ultra_short_nowcast_to_weather_values` + `core/
  weather.py` pure 헬퍼 5종.
- **PR#38** (merged): Sprint 2 §2.2 진입 — `WeatherValue` DTO + 3 enum
  (WeatherDomain/ForecastStyle/TimelineBucket, ADR-010) + `make_weather_value_
  key` + KMA `short_forecast_to_weather_values`.
- **PR#37** (merged): ADR-041 본격 구현 — `python-kraddr-base` 의존 제거,
  `Address` DTO 보강 + `core/address.py` (bjd/phone/한글 정규화 utility).
- **PR#36** (merged): 디버그 UI frontend skeleton — Next.js 15 + React 19 +
  TanStack Query + Zustand (ADR-037) + map-marker-react `private:true` (ADR-043).
- **PR#35** (merged): 디버그 UI backend 첫 라우터 — `create_app` factory +
  `/debug/health` + `/debug/version` + `openapi.json` drift gate 활성 (ADR-031).
- **PR#34** (merged): Sprint 2 §2.1 datagokr 표준데이터 축제 1차 source
  (`cultural_festivals_to_bundles`, ADR-042).
- **PR#30~33** (merged): agent worktree + codegraph 룰 docs / codegraph MCP /
  거버넌스 보강 + ADR-035~043 proposed→accepted 일괄 전환.
- **PR#28~29** (merged): Sprint 2 prep — `infra/models.py` + Alembic 첫 2
  revision / `core/scoring.py`(ADR-016) + `core/providers.py`.
- **PR#19~27** (merged): Sprint 1 scaffolding (dto/core/infra) + review P0/P1
  해소. 상세는 `docs/journal.md`.
- **upstream knps-api PR#1** (https://github.com/digitie/python-knps-api/pull/1):
  maki icon 정정 (shelter / barrier).


**Phase 1 — DB 스키마 (alembic/models)**
- [x] T-205a — `alembic 0008` + `FeatureUpdateRequestRow` (`ops.feature_update_requests`,
  DDL은 `openapi-admin-contract.md §6.1`). 본 PR은 schema/ORM/DDL 검증까지만 포함하고
  scope resolver/repository는 T-206에서 분리.
- [~] T-205b — ~~`feature.sigungu_boundaries`~~ **취소**(D-11: 경계는 kor-travel-geo
  소유, kor-travel-map은 REST 호출). → T-206a-geo로 대체.
- [x] T-205c — (Phase 2) `ops.data_integrity_violations`
  (F5~F8) / `ops.poi_cache_targets` + `_feature_links` /
  `ops.provider_refresh_policies`. 본 PR에서 `alembic 0009`, ORM row, raw SQL repo,
  PostGIS schema/repo 통합 테스트를 추가했다. `cache_target_keys` scope와 provider별
  update 주기/rate limit enforcement는 T-206d 실행 본체에서 사용한다.
- [x] T-205d — `import_jobs` batch 컬럼(`load_batch_id`/`parent_job_id`, T-200 연계, D-6).
  `alembic 0012`, ORM, `jobs_repo`, `/ops/import-jobs` 조회·필터, admin UI 목록
  표시, migrated PostGIS 통합 테스트를 추가했다.


**Phase 2 — 로직 (scope resolver + 큐 브리지)**
- [x] T-206a — `infra/scope_repo.py` (resolve feature_ids/center_radius/bbox/
  sigungu_by_radius/provider_dataset + `count_features_matching_scope` dry_run).
  `sigungu_by_radius`는 kor-travel-geo `/v2/regions/within-radius` 호출(D-11).
  DB repo는 kor-travel-geo client를 직접 import하지 않고 async resolver를 주입받는다.
  `cache_target_keys` resolver는 T-206d에서 `ops.poi_cache_targets` 기반으로 완료.
- [x] T-206a-geo — (형제 repo `kor-travel-geo`) `POST
  /v2/regions/within-radius` 엔드포인트와 optional PostGIS 실데이터 테스트가
  `kor-travel-geo` main(PR #114/#115 계열)에 반영됨을 재검증했다. kor-travel-map은
  REST v2 계약/로컬 포트 `12201`/resolver 주입 경계를 유지한다.
- [x] T-206b — `infra/feature_update_repo.py` (enqueue/claim/start/finish/get/list/cancel,
  advisory lock + SKIP LOCKED, keyset cursor D-10).
- [x] T-206c — `AsyncKorTravelMapClient` feature-update 메서드 4종.
- [x] T-206d — request 실행 본체(scope→provider/dataset 역추적 refresh, D-6/D-8).
  runner 주입형 `infra.feature_update_executor`, `cache_target_keys` resolver, target
  link 재계산, provider refresh policy skip, `AsyncKorTravelMapClient` 실행 메서드.


**Phase 3 — FastAPI 라우터 (`kor-travel-map-admin` 패키지)**
- [x] T-207a — `/admin/feature-update-requests` CRUD + cancel + run-now (§5).
  실제 provider/Dagster 직접 실행 대신 `run_mode='now'` request 재큐잉까지 연결했다.
- [x] T-207f — `/admin/poi-cache-targets` + `/features/nearby/by-target` (Phase 2,
  PR#167). target CRUD/list/detail/delete와 by-target summary/cursor 조회를 연결했다.
- [x] T-207b — `/admin/providers/{p}/datasets/{d}/runs` (§7). 사용자 결정에 따라
  구현하지 않음으로 닫는다. provider run 상세는 T-207d `/ops/*`와 Dagster UI/summary
  경로에서 필요한 만큼 다룬다.
- [x] T-207c — `/admin/features` 검토/병합/override/deactivate (D-8).
  `/admin/features` 목록과 deactivate, active status override, provider upsert
  재활성화 방지, `/admin/dedup-review` 목록/accepted/rejected/ignored/merged 전이를
  연결했다. 이후 T-215a에서 `POST /admin/features`, `PATCH`/`DELETE /admin/features/{id}`
  사용자 요청 API를 추가했다. `DELETE`는 user-request soft delete이며, hard delete와
  별도 admin audit log는 후속 작업으로 남긴다.
- [x] T-207d — `/ops/*` consistency/jobs/metrics. `GET /ops/metrics`,
  `GET /ops/import-jobs`, `GET /ops/import-jobs/{job_id}`,
  `GET /ops/consistency/reports`, `GET /ops/consistency/issues`를 연결했다.
- [x] T-207e — `/features/*` + `/tripmate/features/batch` (사용자, `tripmate-rest-api.md`, D-7).
  `GET /features/in-bounds`, `GET /features/search`, envelope 상세, TripMate batch
  상세 조회를 연결했다. 기존 `GET /features` raw bbox 응답은 admin frontend 호환용으로
  유지한다.
- [x] T-207g — OpenAPI export 이원화(admin/user) + drift gate (ADR-031 amend, D-3).
  `scripts/export_openapi.py --profile all`이 admin 전체 spec과 TripMate/user subset
  spec을 함께 생성하고, CI drift gate도 두 산출물을 모두 비교한다.


**Phase 4 — Dagster (kor-travel-map 독립 구현)**
- [x] T-208a — `packages/kor-travel-map-dagster/` 골격 + definitions. 메인
      `kortravelmap`은 Dagster를 import하지 않고 별도 `kortravelmap.dagster`
      package가 code location을 제공.
- [~] T-208b — resources(DB/client/provider 9 + kor-travel-geo/rustfs, D-15). 1차:
      `kor_travel_map_client`, `reverse_geocoder`, `fetched_at`, provider record iterable
      resource 계약 구현. `offline_upload_store` resource key는 T-208g에서 추가한다.
      RustFS/S3 호환 `offline_upload_store` 기본 resource와 Docker RustFS bucket init은
      후속 T-208b 작업으로 구현했다. 실제 provider client resource wiring은 남는다.
- [x] T-208c — provider load asset 9종(이미 구현·검증된 Feature provider 변환 함수
      연결) + 주소/좌표 검증 + `AsyncKorTravelMapClient.load_feature_bundles` PostGIS
      적재 통합 테스트.
- [x] T-208d — schedules(KST cron, 부하 분산).
      현재 구현된 Feature 적재 asset 9개의 provider별 `ScheduleDefinition`과 asset job을
      등록했다. 기본 status는 `STOPPED`.
- [x] T-208e — sensors(feature_update_requests 폴링 + run_failure → 알림, D-6).
      `feature_update_request_queue_sensor`는 `peek_next_update_request()`로 queued/now
      request를 감지하고, `feature_update_request_worker`가 request id별 실행을 맡는다.
- [x] T-208f — consistency/dedup refresh job.
      `consistency_dedup_refresh` job이 `refresh_dedup_candidates` →
      `run_consistency_check` 순서로 실행된다. dedup refresh는 pair/sibling scope config를
      받고, consistency report는 `ops.feature_consistency_reports`에 저장한다.
- [x] T-208g — offline upload load job (D-14).
      `ops.offline_uploads`(alembic 0011), `infra.offline_upload_repo`,
      `kortravelmap.offline_upload` JSON/JSONL `FeatureBundle` parser/load
      orchestration, `AsyncKorTravelMapClient.run_offline_upload_load_job`,
      Dagster `offline_upload_load` job을 추가했다.


**Phase 4.2 — Offline upload admin UI 선행**
- [x] T-208h — `/admin/offline-uploads*` API + 기본 upload 화면.
      RustFS/S3 store에 JSON/JSONL `FeatureBundle` 파일을 저장하고,
      `ops.offline_uploads` row 생성/list/detail/load 실행까지 admin UI에서 연결한다.
- [x] T-208i — CSV/TSV validation + column mapping wizard.
      CSV/TSV 업로드 허용, preview/header/sample endpoint, validation import job,
      column mapping, kor-travel-geo address geocode/reverse 보강, load 전 validation gate,
      admin UI validation panel, Dagster load parser 연계를 추가했다. `bjd_code`가 없는
      provider/offline row는 resolver가 있으면 kor-travel-geo REST v2 geocode/reverse 결과로
      보강한다.


**Phase 4.5 — Admin UI 최신화 (사용자 지시로 T-208d 이후 최우선)**
- [x] T-211a — admin UI 최신 문서/현재 구현 gap audit + 선행 API/데이터 계약 보강.
      `docs/admin-ui-modernization-gap-audit.md`를 추가하고, frontend에
      `/admin/features`, `/ops/import-jobs`, `/ops/metrics`, `/ops/consistency`,
      `/admin/dedup-review`, `/admin/feature-update-requests`,
      `/admin/poi-cache-targets`, `/features/nearby/by-target` typed hook layer를
      추가했다. `/admin/import-jobs` 과거 표기는 `/ops/import-jobs` 정본으로
      정리했다.
- [x] T-211b — admin UI 최신화 구현. Dagster 관리 화면 embed와 별개로 자체 UI에서
      schedule/sensor/job/run/asset 상태를 꾸며 보여주고, feature/update request/ops
      화면을 최신 문서 기준으로 보완한다. React Doctor 검증 필수.


**Phase 5 — Docker / 배포**
- [x] T-209a — `docker-compose.yml` 1차(api/frontend/dagster/postgres) + 고정 포트
  API `12301`, frontend `12305`, Dagster `12302`, Postgres host `5432`.
- [x] T-209b — 기동 순서 1차(postgres health → API `alembic upgrade head` →
  api/frontend/dagster). 2026-06-04 Codex 후속으로 `scripts/run-admin-stack.sh`가
  시작 전 `alembic upgrade head`를 실행하고, `setsid` detached 실행 + URL 기준
  readiness로 API/frontend/Dagster를 유지하도록 보정했다. Dagster metadata DB 분리/init와
  daemon/schedule 운영은 `T-209b-a`에서 완료했다.
- [x] **T-209b-a — Dagster schedule/run/event storage PostgreSQL 강제 전환.**
  Docker standalone과 로컬 admin-stack 모두 `docker/dagster.yaml`의 unified
  `storage.postgres` instance config를 사용한다. Dagster 공식 instance config 기준에서
  이 key는 run/event/schedule-sensor tick metadata를 함께 PostgreSQL에 저장하므로,
  `KOR_TRAVEL_MAP_DAGSTER_PG_URL`이 단일 source다.
  - Docker 이미지는 기존처럼 `docker/dagster.yaml`을 포함하고, `dagster` webserver와
    `dagster-daemon`이 같은 `DAGSTER_HOME`/`KOR_TRAVEL_MAP_DAGSTER_PG_URL`을 공유한다.
  - `scripts/run-admin-stack.sh`는 시작 전 `kor_travel_map_dagster` DB 존재를 확인/생성하고,
    `docker/dagster.yaml`을 `$DAGSTER_HOME/dagster.yaml`로 설치한다.
  - 로컬 admin-stack도 `dagster dev` 대신 `dagster-webserver`와 `dagster-daemon`을
    분리 실행하고, daemon pid가 살아 있는지 readiness 뒤 확인한다.
  - `$DAGSTER_HOME/schedules/schedules.db*` 생성은 회귀로 문서화했고,
    compose/local script 회귀 테스트를 추가했다.
- [x] T-209c — Dockerfile 3종(api/frontend/dagster).
  frontend Dockerfile은 T-RV-28에서 root `package-lock.json` 기반 `npm ci`로 전환했다.
- [x] T-209d — `docs/runbooks/docker-app.md` + `docs/deploy.md`.
- [x] T-209e — backup/restore 독립 DB 묶음(ADR-040 amend, D-5).
  `T-209e-a`에서 `npm run docker:backup`과 `docs/backup-restore.md`를 추가해
  `kor_travel_map` app DB + `kor_travel_map_dagster` Dagster metadata DB + RustFS volume cold
  backup 산출물과 검증 절차를 고정한다. `T-209e-b`에서 `npm run docker:restore`와
  `scripts/docker-restore.sh`를 추가해 backup 산출물을 staging DB/volume
  (`kor_travel_map_restore`, `kor_travel_map_dagster_restore`, `kor-travel-map-rustfs-restore`)으로
  복원하는 비파괴 cold restore 자동화를 고정한다. `T-209e-c`에서
  `/admin/backups`, `/admin/restore/{backup_id}` router와 `/admin/backups` UI를 추가해
  artifact 목록과 backup/restore/swap command plan을 노출한다. 최종 잔여로
  `scripts/with-pg-advisory-lock.py` 기반 `maintenance:backup-restore` mutex,
  `scripts/docker-restore-verify.sh` staging smoke/count 검증,
  `scripts/docker-restore-swap.sh` restore hot-swap env 전환을 추가했다.


**Phase 6.5 — TripMate 요구사항 대조 후속 (2026-06-06, `T-213`)**

정본 리포트는 `docs/reports/tripmate-requirements-reconcile-2026-06-06.md`. TripMate
문서의 기준 kor-travel-map commit이 `b775c74`라 현재 `origin/main`과 차이가 크므로, 단순
호환 shim이나 최소 수정이 아니라 ADR-045 OpenAPI 독립 프로그램 모델 기준으로 완성도,
안정성, 확장성, 성능을 우선한다.

- [x] **T-213a — TripMate 요구사항 대조 리포트 작성.**
  TripMate `docs/kor-travel-map-requirements.md` K-1~K-14를 현재 user OpenAPI 7개 path,
  repo/client 구현, ADR-045/046 경계와 대조해 이미 충족/부분 충족/신규 task를 분리한다.
- [x] **T-213b — 일반 좌표 기준 `/features/nearby` 구현.** (claude, 2026-06-06)
  `GET /features/nearby`(`lon`/`lat`/`radius_m`≤100km/`kind[]`/`category[]`/`status[]`/
  `provider[]`/`sort`/`page_size`/`cursor`) + repo `features_nearby` + client
  `features_nearby`를 추가했다. 입력 좌표를 `origin` CTE에서 1회만 5179로 변환하고
  술어는 STORED `coord_5179`에 `ST_DWithin`/거리 정렬(ADR-012, by-target nearby와 동일
  candidates CTE — row/cursor/page helper 재사용). 응답 `{data:{origin,items,
  next_cursor}, meta}`, user OpenAPI subset 포함(`export_openapi.py` USER_OPERATIONS).
  검증: 격리 WSL sandbox에서 OpenAPI 재생성/drift green, ruff/mypy/lint-imports,
  admin router unit(검증 422 + spec presence), client unit, **PostGIS 통합 4건**
  (필터/거리·cursor·invalid·EXPLAIN ADR-012 stored-coord_5179 술어 확인). 참고: 소량
  테스트 데이터에서 planner가 GiST 대신 seqscan을 고를 수 있어 인덱스 *이름*은
  단언하지 않고 술어 대상 컬럼/per-row transform 부재로 ADR-012를 검증한다.
- [x] **T-213c — bbox clustering(`cluster_unit`) 설계/구현.** (claude, 2026-06-06)
  **설계 결정: 서버 행정구역 rollup**(client-side·grid bucket 대신) — feature에 이미
  있는 `sido_code`/`sigungu_code`/`legal_dong_code`를 GROUP BY해 geometry 계산 없이
  region별 count + 평균 좌표(대표 마커 위치)를 낸다. repo `cluster_features_in_bbox`
  (cluster_unit allowlist→고정 코드 컬럼, bbox는 stored `coord` GIST `&&`, ADR-012
  술어 변환 없음) + `/features/in-bounds`에 `cluster_unit`(sido|sigungu|eupmyeondong)
  쿼리 추가, 미지정 시 `zoom`으로 유도(≤7=sido/≤10=sigungu/≤13=eupmyeondong/≥14=개별).
  응답 `data.clusters[]`(cluster_unit None이면 `items`, 아니면 `clusters`,`items=[]`).
  검증: router unit 4(cluster/zoom 유도/고줌 개별/invalid 422), PostGIS rollup 통합 2
  (sigungu·sido count+centroid, invalid), 격리 sandbox에서 OpenAPI drift/frontend
  types/ruff/mypy/lint-imports green.
- [x] **T-213d — `AsyncKorTravelMapClient` read parity 보강.** (claude, 2026-06-06)
  `get_features`(→`get_feature_rows_by_ids`), `search_features`(→repo
  `search_features`), `features_nearby_poi_cache_target`(→repo 동명 함수) 3개 read
  메서드를 `AsyncKorTravelMapClient`에 추가했다. 기존 repo 함수에 위임만 하므로 새 SQL/
  스키마 없음. TripMate 운영은 계속 OpenAPI만 쓰지만, API/Dagster 내부와 테스트가
  admin `/features/{batch,search,nearby-by-target}`와 같은 read path를 재사용한다.
  DB 미접근 unit test 3건(repo/세션 monkeypatch pass-through). **T-213b/e/g의 선행
  기반.**
- [x] **T-213e — weather card/시계열 사용자 API.** (claude, 2026-06-06)
  `feature.feature_weather_values` 테이블 신설(**alembic 0017**, PK=결정적
  `weather_value_key` ADR-010, card 복합 인덱스 + valid_at BRIN ADR-013, feature FK
  CASCADE). `infra/weather_repo.py`: `load_weather_values`(멱등 upsert) +
  `build_weather_card(feature_id, asof, freshness_seconds)` — (forecast_style,
  metric_key)별 `COALESCE(valid_at,observed_at,issued_at)` 최신 DISTINCT ON, asof 필터,
  `source_styles` trace, `is_stale`(기본 6h). `GET /features/{feature_id}/weather` user
  spec 포함 + client `build_weather_card`/`load_weather_values`. 검증: PostGIS 통합 2
  (load/card/asof/freshness/idempotent/empty) + alembic upgrade 0017 체인 + router unit 2.
  격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports green.
  **→ T-213a~h 전부 완료.**
- [x] **T-213f — category catalog HTTP/runtime 표면.** (claude, 2026-06-06)
  `GET /categories`(`routers/categories.py`) — 144건 정적 카탈로그(code/depth/tier/
  label/path/maki_icon/...)를 노출. `include_counts`/`active_only`면 repo
  `category_feature_counts`로 DB 분포(`db_feature_count`/`db_active`) 합침. 정적
  카탈로그는 모듈 로드 시 1회 구성(ADR-030). user OpenAPI subset 포함, frontend
  types 재생성. drift gate는 `@kor-travel-map/map-marker-react` `maki.ts`가 **name→glyph**
  구조라 ADR-029 원안의 category↔TS 1:1이 아니라 **완화형**(TS maki name kebab 유효성
  + 핵심 provider maki 글리프 커버 + Python 카탈로그 self-consistency)으로 적용
  (`tests/unit/test_category_catalog_contract.py`). 부수: `category/__init__.py`
  docstring tier 개수(34/73/29)·`category.md` icon 개수(57) 코드 기준 reconcile.
  검증: 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports +
  admin router 3·main contract 3·PostGIS counts 1건 green.
- [x] **T-213g — provider export + sync state/last-sync 표면.** (claude, 2026-06-06)
  `kortravelmap.providers`에 knps/krheritage 변환 함수·dataset/provider 상수 re-export.
  `AsyncKorTravelMapClient`에 `get_sync_state`/`list_sync_states`(read) +
  `record_sync_success`/`record_sync_failure`(write, 1 transaction) helper 추가.
  `GET /providers/{provider}/last-sync`(`routers/providers.py`) — `sync_state_repo.
  list_sync_states`(provider + dataset_key/sync_scope 필터) 기반, `items[]`(dataset/
  scope/status/last_success_at/last_failure_at/consecutive_failures) 반환, **내부
  cursor 비노출**, 매칭 0건이면 404. user OpenAPI subset 포함, frontend types 재생성.
  검증: router unit 3(spec/404/200 cursor-exclude), providers export unit 1, PostGIS
  list 통합 1, client unit, 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/
  lint-imports green.
- [x] **T-213h — public health/version.** (claude, 2026-06-06)
  `GET /health`(liveness, 의존 없는 정적 200, `{data:{status,service},meta}`) +
  `GET /version`(`{data:{version, kor_travel_map_version, openapi_version, commit},meta}`,
  commit=env `KOR_TRAVEL_MAP_GIT_COMMIT`)를 `routers/public_status.py`로 추가. liveness는
  DB 장애에도 동작해야 하므로 `features_routes_enabled`와 무관하게 **항상 mount**.
  user OpenAPI subset 포함, frontend types 재생성. router unit 5(spec presence/
  liveness/version/env commit/feature-off 시에도 mount). **deep readiness**(DB/RustFS/
  Dagster `/ops/health-deep`)는 후속 — liveness를 DB-free로 유지하기 위해 분리.


## 완료

- [x] T-000 — git v1 보존 + main orphan 재시작 (완료: 2026-05-24)
- [x] T-001 — v2 핵심 docs 작성 (완료: 2026-05-24)
  - AGENTS.md, README.md, SKILL.md, CLAUDE.md
  - .env.example, pyproject.toml, .gitignore, .gitattributes, LICENSE
  - docs/architecture.md
  - docs/decisions.md (ADR-001 ~ ADR-019)
  - docs/data-model.md, performance.md, test-strategy.md
  - docs/backend-package.md, agent-guide.md, dev-environment.md
  - docs/windows-reinstall-recovery.md
  - docs/feature-model.md, provider-contract.md, external-apis.md
- [x] T-001b — ADR-020 + 디버그 UI 별도 패키지로 분리 (완료: 2026-05-24)
  - decisions(ADR-020), architecture, backend-package, debug-ui-package(신규),
    AGENTS, SKILL, CLAUDE, README, pyproject(`[api]` 제거 + forbidden 계약 추가),
    .env.example, test-strategy 갱신
  - `packages/kor-travel-map-admin/` pyproject + README skeleton
- [x] T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전 (완료: 2026-05-24, PR#2)
  - 14개 신규 docs (weather/files-rustfs/opening-hours/kraddr-base-types/
    address-geocoding/dagster-boundary/postgres-schema/debug-fixture-workflow/
    feature-db-initialization/tripmate-integration + provider ETL 10건)
- [x] T-001c — ADR-021/022/023 + PR-only workflow + `kortravelmap` namespace +
      kraddr-base category 이전 (완료: 2026-05-24, PR#1)
  - AGENTS/SKILL/CLAUDE/architecture/agent-guide 일괄 갱신
  - `docs/category.md` 신설
  - import-linter 계약 placeholder
- [x] T-016 — `python-mois-api` 활용 feature 적재 4단계 lifecycle docs +
      ADR-024 canonical name 정정 (완료: 2026-05-24, PR#3)
  - `docs/mois-feature-etl.md` 신설 + 195 슬러그 카탈로그
  - 일괄 krmois→mois rename (`mois-license-feature-etl.md` 등)
- [x] T-015 — forest rename + category Tier 1~4 catalog + KNPS data.go.kr
      카탈로그 + 모든 ETL doc category 정보 audit (완료: 2026-05-25, PR#5)
  - `outdoor-feature-etl.md` → `forest-feature-etl.md` (git mv)
  - `docs/category.md` Tier 1~4 상세 테이블 (141건)
  - KNPS dataset 7건 카탈로그 + 옵션 A/B 비교 (옵션 B 권고)
- [x] T-017a — ADR-025 디버그 UI frontend = `maplibre-vworld-js` + ADR-025
      사용자 보강 (key 공유 + upstream 직접 PR) + ADR-026 TripMate 사용자 UI도
      maplibre-vworld 통일 (완료: 2026-05-25, PR#6 merged)
  - `docs/decisions.md` ADR-025 + ADR-026
  - `docs/debug-ui-package.md` §14 frontend 사양
  - `packages/kor-travel-map-admin/frontend/` skeleton
  - `docs/tripmate-integration.md` §14.5 사용자 UI 지도 stack
  - `docs/external-apis.md` Kakao Maps SDK 미사용 처리
  - `docs/forest-feature-etl.md` §11.6 ADR-026 → ADR-027 후보 재번호
- [x] T-017b — ADR-025 2차 사용자 보강 (frontend 빌드 도구 Vite → **Next.js**
      정정) (완료: 2026-05-25, PR#11 merged)
  - `docs/decisions.md` ADR-025 §사용자 보강 2차 추가
  - `docs/debug-ui-package.md` §14 Next.js 전환 + 운영 옵션 3가지
  - `packages/kor-travel-map-admin/frontend/` skeleton 일괄 Next.js 전환
    (package.json / .env.example / .gitignore / README / **next.config.js**
    신설), `VITE_*` → `NEXT_PUBLIC_*`
  - `docs/external-apis.md` / `docs/tripmate-integration.md` §14.5 / `docs/
    tasks.md` (T-100 재해석) 동기
- [x] T-013 — `CHANGELOG.md` 초기 엔트리 정리 (완료: 2026-05-25, PR#10 merged)
  - ADR-024~033 + T-101~103 + 명명 일치화 + 코드 변경 모두 inline
- [x] T-013b — 잔존 `krmois` → `mois` 명명 sweep (완료: 2026-05-25, PR#10
      merged) — 4건 정리 (forest §11.1 / mois-license §payload / journal 2건),
      ADR-024 narrative 등 역사 기록 컨텍스트는 유지
- [x] T-014a — Sprint 1 진입 계획 작성 (완료: 2026-05-25, PR#10 merged)
  - `docs/sprints/README.md` (Sprint 1~5 표 + 공통 진입 게이트)
  - `docs/sprints/SPRINT-1.md` (진입 조건 + 산출물 + DoD + Sprint 2 진입)
  - 실제 Sprint 1 진입 PR은 T-014 본체로 계속 pending (사용자 승인 필요)
- [x] T-017c — ADR-029 (proposed) + `@kor-travel-map/map-marker-react` skeleton
      (완료: 2026-05-25, PR#10 merged)
  - `docs/decisions.md` ADR-029 본문 (MIT, monorepo 위치, peer deps,
    drift gate, 배포 정책)
  - `packages/map-marker-react/` skeleton (`package.json` / `README.md` /
    `vite.config.ts` / `.gitignore`)
  - 실 코드는 T-017 본체 (Sprint 2)
- [x] T-018a — `python-knps-api` upstream scaffold 모니터링 + 본 라이브러리
      ADR-028 (proposed) 작성 (완료: 2026-05-25, PR#12 merged)
  - upstream `digitie/python-knps-api` `6e36990` scaffold 확인
  - `docs/decisions.md` ADR-028 본문
  - `docs/knps-feature-etl.md` 신설 (feature 적재 계약)
  - `docs/forest-feature-etl.md §11` 갱신 (외부 API 표면 + 채택 ✅ 표기)
  - `docs/provider-contract.md` / `docs/external-apis.md` / `pyproject.toml`
    동기
- [x] T-018b — upstream knps-api 측 PR — maki icon 정정 (완료: 2026-05-25,
      knps-api PR#1 open, https://github.com/digitie/python-knps-api/pull/1)
  - `docs/knps-feature-etl.md §4` shelter / barrier 정정 (본 라이브러리
    ADR-027 정합 + Maki 표준 호환)
  - 양방향 PR 워크플로 적용 사례 (ADR-028 §D)
- [x] T-012a — T-101~103 상세 분석을 `docs/performance.md`에 inline (완료:
      2026-05-25, PR#10 merged)
  - §9.3 T-101 (PostGIS MV), §9.4 T-103 (streaming ETL), §9.5 T-102
    (pg_prewarm) — 도입 조건, 부작용, ROI, 절차
- [x] T-012b — ADR-030/031/032/033 enforcement 코드 (완료: 2026-05-25, PR#10
      merged)
  - `pyproject.toml`: import-linter 차단 계약 (cachetools/async_lru/
    aiocache/diskcache + kafka/aiokafka/confluent_kafka/faust), coverage
    Sprint별 schedule 주석
  - `packages/kor-travel-map-api/scripts/export_openapi.py` skeleton
    (ADR-031, `--check` drift gate)


## 폐기 / 재해석

- ~~T-100~~ — "디버그 UI 별도 Next.js 패키지 분리" — **부분 재해석** (PR#11
  2026-05-25):
  - 원래 의도 = Next.js로 별도 패키지화. 실제 구현 = Python 패키지로 분리
    (T-001b, ADR-020) + frontend는 그 안의 `frontend/` 하위에 **Next.js**
    (ADR-025 2차 보강).
  - 즉 "Next.js 미채택"이라고 한 PR#7의 기록은 잘못됨 — ADR-025 2차 보강
    으로 Next.js 채택 확정.


## 머지 history (참조)

| PR | branch | 머지 일자 | 핵심 |
|----|--------|----------|------|
| #1 | `chore/pr-workflow-namespace-rename-category-migration` | 2026-05-24 | ADR-021/022/023 |
| #2 | `docs/v1-to-v2-feature-ports` | 2026-05-24 | T-002~T-011 (14 docs) |
| #3 | `feat/mois-feature-etl` | 2026-05-24 | ADR-024 + mois-feature-etl.md |
| #4 | (merged via #3 lineage) | 2026-05-24 | 동일 |
| #5 | `feat/forest-knps-category` | 2026-05-25 | T-015 (forest rename + KNPS 카탈로그 + category Tier 1~4) |
| #6 | `feat/debug-ui-maplibre-vworld` | 2026-05-25 | ADR-025 + ADR-025 사용자 보강 + ADR-026 |
| #7 | `chore/tasks-md-update` | 2026-05-25 | tasks.md 백로그 |
| #8 | `docs/adr-030-031-032-033-proposed` | 2026-05-25 | ADR-030/031/032/033 proposed |
| #9 | `docs/adr-027-forest-category-expansion` | 2026-05-25 | ADR-027 proposed |
| #10 | `docs/pr10-t012-t018-codify` | 2026-05-25 | ADR-029 + T-013/14a/17c/12a/12b + 명명 sweep + 코딩 |
| #11 | `docs/pr11-debug-ui-nextjs` | 2026-05-25 | ADR-025 2차 보강 (Vite → Next.js) |
| #12 | `docs/pr12-knps-api-integration` | 2026-05-25 | ADR-028 + knps-feature-etl.md |
| #13 | `chore/tasks-md-pr12-merged-update` | 2026-05-25 | tasks.md 백로그 갱신 (PR#12 머지 후) |
| #14 | `docs/pr14-impl-order-sprint-plans` | 2026-05-25 | ADR-034 provider 9단계 + Sprint 2~5 plan |
| #15 | `docs/pr15-governance-sweep` | 2026-05-25 | governance docs sweep + DO NOT bug fix 3건 |
| #16 | `feat/sprint1-entry-adr-accepted` | 2026-05-25 | T-014 Sprint 1 진입 — ADR 027~034 일괄 accepted + fail_under=50 |
| #17 | `feat/sprint1-pr17-scaffolding` | 2026-05-25 | `src/kortravelmap/` PEP 420 scaffolding + `settings.py` + smoke |
| #18 | `feat/sprint1-pr18-category-migration` | 2026-05-25 | `category/` 144건 (kraddr-base 이전 + ADR-027 3건) + 16 tests |
| #19 | `feat/sprint1-pr19-dto-foundation` | 2026-05-25 | `dto/` Feature + 5 detail + NOTICE_TYPES 14 (ADR-027) + AreaDetail hazard_zone + KST + 27 tests |
| #20 | `feat/sprint1-pr20-core-exceptions-id` | 2026-05-25 | `core/` exceptions 7종 + `make_feature_id` (ADR-009) + 42 tests |
| #21 | `feat/sprint1-pr21-infra-skeleton` | 2026-05-25 | `infra/crs.py` + `infra/db.py` + testcontainers PostGIS conftest |
| #22 | `feat/sprint1-pr22-ci-import-linter` | 2026-05-25 | CI workflows + import-linter 4 계약 + ADR-002 위반 해소 (dto/_time.py) |
| #23 | `docs/pr23-review-report` | 2026-05-25 | `docs/reports/pr-1-21-review.md` 종합 리뷰 |
| #24 | `fix/pr24-dto-strictness-p0` | 2026-05-25 | review P0-1/2/3 — detail dict 거부 + datetime aware + category 정규식 |
| #25 | `docs/pr25-knps-keyless-sync` | 2026-05-25 | python-knps-api keyless(`06da125f`) 반영 + ADR-028 amendment §H |
| #26 | `feat/pr26-source-record-bundle-dto` | 2026-05-25 | review P0-4 — ID helper 2종 + SourceRecord/Link/FeatureBundle DTO |
| #27 | `docs/pr27-p1-docs-drift-sweep` | 2026-05-25 | review P1 docs drift sweep |
| #28 | `feat/pr28-infra-models-alembic` | 2026-05-26 | `infra/models.py` + Alembic 첫 2 revision (0001/0002) + 통합 테스트 6 |
| #29 | `feat/pr29-core-scoring-providers` | 2026-05-26 | `core/scoring.py`(ADR-016) + `core/providers.py` (canonical 18종) |
| #30~31 | `docs/pr30-31-codegraph-worktree` | 2026-05-27 | agent worktree + codegraph 룰 docs + MCP 등록 |
| #32~33 | `docs/pr32-33-adr-035-043` | 2026-05-27 | 거버넌스 보강 + ADR-035~043 proposed→accepted |
| #34 | `feat/pr34-datagokr-festivals` | 2026-05-27 | Sprint 2 §2.1 datagokr 축제 1차 source (ADR-042) |
| #35 | `feat/pr35-debug-ui-routers` | 2026-05-27 | 디버그 UI `create_app` + health/version + openapi drift gate |
| #36 | `feat/pr36-frontend-skeleton` | 2026-05-27 | Next.js 15 frontend skeleton + TanStack/Zustand (ADR-037) |
| #37 | `feat/pr37-kraddr-base-absorb` | 2026-05-28 | ADR-041 — Address DTO 보강 + `core/address.py` |
| #38 | `feat/pr38-kma-short-forecast` | 2026-05-28 | `WeatherValue` DTO + 3 enum + KMA 단기예보 1차 |
| #39 | `feat/pr39-kma-nowcast` | 2026-05-28 | KMA 초단기실황 + `core/weather.py` pure 헬퍼 5종 |
| #40 | `docs/pr40-provider-status-sweep` | 2026-05-28 | `python-*-api` 라이브러리 status sweep |
| #41 | `feat/pr41-kma-ultra-short-forecast` | 2026-05-28 | KMA 초단기예보 (getUltraSrtFcst) + LGT |
| #42 | `feat/pr42-pricevalue-opinet` | 2026-05-28 | `PriceValue` DTO + opinet 가격 1차 |
| #43 | `feat/pr43-opinet-stations` | 2026-05-28 | opinet `stations_to_bundles` (gas station Feature) |
| #44 | `feat/pr44-etl-preview-router` | 2026-05-28 | 디버그 UI ETL preview 라우터 (fixture dry-run) |
| #45 | `feat/pr45-krex-multi-kind` | 2026-05-28 | Sprint 2 §2.4 krex 휴게소 4 dataset multi-kind |
| #46 | `feat/pr46-kma-weather-alerts` | 2026-05-28 | KMA weather_alerts → notice + krex category fix + ETL 11 dataset |
| #47 | `feat/pr47-etl-live-source` | 2026-05-28 | ETL preview `?source=live` (KMA 3) + 8 provider key + CI red 3종 해소 |
| #48 | `docs/pr48-worktree-rename-tasks-sweep` | 2026-05-28 | worktree `geo-*`→`kor-travel-map-*` rename + tasks.md 최신화 |
| #49 | `feat/pr49-maplibre-vworld-v010` | 2026-05-28 | maplibre-vworld v0.1.0 의존 핀 정합 (git URL+tag, zod ^4.4.3, ADR-036 amendment) |
| #50 | `docs/pr50-sprint-task-resume-consolidation` | 2026-05-28 | Sprint/task/resume 일관성 재정비 |
| #51~#95 | (Sprint 2 잔여 + Sprint 3) | 2026-05-28~30 | visitkorea enrichment / KMA mid_forecast / ETL live 11 / KNPS·krheritage provider / geocoding REST / `feature_repo` 적재 / consistency F1~F3 / `AsyncKorTravelMapClient` / `/features` debug UI + frontend / dedup queue |
| #96~#114 | (Sprint 4 prep) | 2026-05-30~31 | `/features` UX / `map-marker-react` / geocoding v2 회귀 / NTFS+Windows Git 정책 / Next.js 16 + `maplibre-vworld-js#v0.1.2` |
| #115~#132 | (Sprint 4a) | 2026-05-31~06-01 | MOIS Step A bulk + Step B incremental(cursor) / advisory lock + `ops.import_jobs` / CLI mutex + `status` / `ktmctl import mois`(NDJSON) / dedup self-sibling / geocoder live 재검증 |
| #133 | `feat/cli-dedup-merge` | 2026-06-01 | `ktmctl dedup-merge` + merge primitive + `ops.feature_merge_history`(alembic 0007) + `core.scoring.select_master` (ADR-016) |
| #134 | `feat/step-b-incremental` | 2026-06-01 | MOIS Step B 증분 적재 + `infra/sync_state_repo`(cursor) |
| #135 | `chore/dedup-fp-measurement` | 2026-06-01 | dedup FP 측정 리포트 + 회귀 가드 (가중치 변경 없음) |
| #136 | `feat/step-c-closed` | 2026-06-01 | MOIS Step C 폐업/취소 → feature inactive |
| #137 | `feat/step-d-detail-router` | 2026-06-01 | MOIS Step D on-demand 상세 (debug-ui `/debug/mois-license/{id}`, 캐시만) |
| #138 | `feat/dedup-fp-ops-stats` | 2026-06-01 | dedup 운영 FP 통계 (`status_repo.dedup_fp_stats` + `ktmctl status`) |
| #139 | `feat/consistency-f4` | 2026-06-01 | ADR-033 F4 — dedup 백로그 baseline WARN |
| #140 | `feat/place-phone-enrichment` | 2026-06-01 | Place 전화번호 보강 (`kortravelmap.enrichment`) |
| #141 | `chore/coverage-bar-80` | 2026-06-01 | coverage gate 75→80 (실측 94.12%) — Sprint 4 종료 |
| #142 | `docs/agent-runbooks` | 2026-06-01 | 에이전트 공용 runbook (`docs/runbooks/` agent-workflow + failure-patterns) |
| (post) | (main) | 2026-06-01 | admin OpenAPI cache 문서 (ADR-045 후속) |
| knps-api #1 | `docs/knps-feature-maki-icons` | **open** | maki icon 정정 (shelter / barrier) |
