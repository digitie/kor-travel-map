# resume.md — 현재 진척도와 다음 한 작업

## 과거 기록 아카이브

> 2026-07-26 **전면 감사**(현행 백로그 구조 성립) 이전 기록은 아래로 분리했다.
> 검색은 `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [`resume-2026-07.md`](archive/resume-2026-07.md) | 2026-07-01 ~ 2026-07-24 | 128건 | 162 KB |
| [`resume-2026-06.md`](archive/resume-2026-06.md) | 2026-06-13 ~ 2026-06-30 | 76건 | 86 KB |

## 2026-07-30 (codex) — Lane B b1 T-VN-H39 schedule pending barrier 완료

H38 workers=8에서 재현한 schedule pending test의 600ms 시간 추정을 제거했다.
`scheduleActionResponseGate`는 route가 command body를 기록한 뒤 응답을 보류하며, 테스트는
request 도달을 확인한 다음 같은 5개 schedule control이 모두 disabled인지 검사한다.
`finally`에서 응답을 해제한 뒤 결과와 동일 control 5개의 enabled 복원을 대칭 검증하므로,
고병렬 부하와 assertion 실패 모두에서 gate가 남지 않는다. timeout 증가는 없다.

적대 리뷰어 1명이 release 뒤 2개 control만 확인하던 P2를 찾아 동일 locator 집합을 상태
인자로 재사용하도록 반영했다. 격리 실패 spec은 setup 포함 **2/2**, frontend 전체
**278 passed**, TypeScript·ESLint가 green이다. exact production image D workers=8은
**276/276**, manifest 일치, child exit 0·reporter gate true, owned
container/network/image 0건으로 끝났다.

첫 표적 실행은 공유 12705의 인증 없는 storage state 때문에 로그인 화면에서 멈췄다. 제품
실패로 재시작하지 않고 독립 21715 frontend+session으로 해당 지점부터 재개했으며, 7월
29일부터 Agent B worktree에 남아 있던 orphan Next dev와 생성된 mocked failure artifact를
정리했다. DB는 사용하지 않았고 보존 `ktm-tvn45-db`는
healthy·`0068_integrity_last_seen`라 재사용 가능하다.

**다음 한 작업**: 보안 gate 뒤 H39 PR을 열어 CI green 후 셀프 머지한다. 머지 뒤 새 Claude
Code PR 사후 감사를 확인하고, Lane B `T-VN-16A` Map set-based weather batch로 이동한다.

## 2026-07-30 (codex) — Lane B b1 T-VN-H38 failure fingerprint 완전성 완료

Mocked failure reporter가 첫 attempt/error만 보던 경로를 제거했다. deterministic failure와
expected flaky 모두에서 non-passed retry, result error와 중첩 `cause`, step-only error를
전수 검사하며 passed-only expected failure·skipped·interrupted는 원인 증거 누락으로
거부한다. 정상
Playwright timeout은 `failed|timedOut`으로 수용하되, ANSI 제거 뒤 exact timeout envelope와
같은 timeout 값의 result leaf를 attempt/hook ancestry로 결속한다. 따라서 caught locator 뒤
별도 hang, beforeEach 뒤 afterEach timeout, soft assertion 뒤 body hang은 통과하지 않는다.

parent 오류는 result에 직접 있거나 step-only인 경우 모두 own stage를 유지한다. Playwright
1.60은 boxed propagation과 boxed 내부에서 같은 오류를 독립 재투척한 경우의 reporter
metadata를 구별할 수 없으므로, descendant stage 차용과 동일 text 중복 제거를 금지해
fail-closed한다. redacted report는 retry·실제 result error index·cause depth와
category/location만 쓰고 error text와 raw step title을 제거했다.

적대 리뷰어 2명이 실제 Playwright 1.60 probe와 합성 반례로 찾은 retry·flaky·timeout·parent·
redaction 결함을 모두 반영했다. 관련 회귀 **28 passed**, frontend 전체 **278 passed**,
TypeScript·ESLint가 통과했다. exact production image D workers=4도 **276/276**, manifest
일치, child exit 0·reporter gate true, owned container/network/image 0건이다. DB 작업은 없어
보존 clone을 그대로 유지했다.

workers=8에서 schedule command의 600ms 응답이 pending 단언 전에 끝난 기존 시간 의존
테스트 1건은 `T-VN-H39`로 분리했다.

**다음 한 작업**: 보안 gate 뒤 H38 PR을 열어 CI green 후 셀프 머지한다. 머지 뒤 새 Claude
Code PR 사후 감사를 확인하고, Lane B `T-VN-H39`의 명시적 schedule response barrier로
이동한다.

## 2026-07-30 (codex) — Lane B b1 T-VN-H37 Mocked checkpoint 결정성 완료

Mocked checkpoint의 종료 판정을 reporter manifest 한 신호에 맡기지 않고 Playwright
`result.status`·reporter gate·child exit status/signal·postcondition·cleanup으로 분리했다.
276개와 manifest가 모두 맞아도 child nonzero면 `playwright_child_nonzero`가 남는 합성 회귀를
고정했고, 모든 진단은 경로·자격증명 대신 제한된 issue code와 count/status만 출력한다.
Docker cleanup은 client 명령의 1초 종료보다 daemon state가 늦게 수렴한 경우 exact 소유
리소스 부재를 확인해 성공하고, identity가 다르거나 끝까지 남은 리소스는 계속 실패한다.

workers=8에서 기존 change review spec은 BFF list 응답 완료 barrier로, 새로 재현된 pipeline
pending create spec은 700ms 지연 대신 명시적 response release barrier로 바꿨다. 실패한
predicate 지점부터 exact workers=8을 다시 실행해 **276/276**, 이어 workers=4도
**276/276**를 통과했다. 두 실행 모두 manifest 일치, child exit 0, reporter gate true,
owned container/network/image 0건이다. frontend Vitest 전체 **259 passed**, TypeScript·
ESLint, 배포 자동화 단위 **8 passed**도 green이다. DB 작업은 없어 보존
`ktm-tvn45-db`를 clone·restore·migration·downgrade 없이 그대로 유지했다.

적대 리뷰는 child signal의 test/infra 오분류를 찾아 exit 2로 정정했고, response gate의
`finally` 해제와 filesystem cleanup 실패 격리도 보강했다. 첫 retry/error만 검사하는 기존
reporter 잔여 위험은 별도 `T-VN-H38`로 등록했다.

**다음 한 작업**: 보안 gate 뒤 PR을 열어 CI green 후 셀프 머지한다. 머지 뒤 새 Claude Code
PR 사후 감사를 확인한 다음 Lane B `T-VN-H38` manifest retry/error fingerprint 완전성으로
이동한다.

## 2026-07-30 (codex) — Lane B b1 T-VN-11A/B 5상태 batch 호환 쌍 완료

Map은 service-token 전용 `POST /v1/features/batch`를
`found|retired|suppressed|missing|unchanged` discriminated union으로 전환했다. 최대 200개
요청을 순서 보존 `unnest` 단일 snapshot query로 처리하고, 공개 projection·종료·비공개·
tombstone 판정을 같은 statement 안에서 분리한다. 요청과 응답 revision은 PostgreSQL
`bigint` 범위를 런타임에서 정확히 제한하고 OpenAPI에는 `int64`로 고정했다. 200개 plan
registry는 기존 50개/3,200행 gate와 같은 1.56% selectivity가 되도록 12,800행을 seed해
planner-default `feature.features` PK index 사용과 응답 shape를 고정한다. DB read 실패는
`FEATURE_BATCH_UNAVAILABLE` RFC7807 503으로 명시한다.

PinVi 호환 소비자는 정확히 같은 OpenAPI snapshot을 vendor하고 5상태 typed decode,
`1..200` chunk 경계, generation/revision fence를 가진 bounded LRU cache, Web·Map·Mobile 공용
표시 resolver로 전환했다. 적대 리뷰에서 flat `lon/lat` snapshot 때문에 지도 마커가 사라지는
문제, out-of-order 응답이 최신 revision/tombstone을 되돌리는 문제, 200개 초과 설정과
PostgreSQL 범위 밖 revision, 같은 revision의 비공개→공개 복구를 막는 negative fence,
작은 seed에서 실제로 실패한 planner-default gate, DB 장애의 generic 500 누출을 찾아 모두
보강했다. 저장소가 서로 달라
물리적으로 한 PR이 될 수 없으므로 생산자와 소비자 두 PR을 하나의 호환 쌍으로 묶고
Map → PinVi 순서로 머지한다.

재사용 `ktm-tvn45-db`에서 새 clone·migration·downgrade 없이 실데이터 다섯 상태와 강제
upstream 장애·복구를 만들었다. 파괴적 Live UI는 5상태 문구·broken count·저장 snapshot
fallback·복구와 지도 포인트 **4곳**을 통과했다. 변형한 fixture는 원복하고 격리
container/listener는 모두 제거했으며 clone은 `0068_integrity_last_seen`, healthy 상태라 다음
task에 재사용할 수 있다.

**다음 한 작업**: 두 호환 PR을 Map → PinVi 순서로 CI green·셀프 머지한다. 머지 뒤 별도
Claude Code PR 사후 감사를 수행하고, Lane B `T-VN-H37`의 Mocked checkpoint 종료 판정과
고병렬 flaky 진단으로 이동한다.

## 2026-07-30 (codex) — Claude PR #890/#891 사후 감사 정정 → H11A/B

Lane A a1 PR #890은 사용자 최신 규칙에 따라 독립 적대 리뷰어 2명, docs-only #891은
1명이 원 authored patch를 감사했다. #890에서는 이름 단독 자동링크를 막으면서 ADR-063의
이름+주소 유일 매칭까지 막은 회귀, H33 unlink와 ledger의 transaction 분리, stale open
finding 재생성, H25B apply의 잘못된 기존 링크 승인, public verifier의 HTTP 500/빈 양성
대조 false-pass를 확인했다. #891에서는 열린 H30B를 상단에서 완료로 가린 상태·순서 모순과
`tasks-done.md`의 열린 checkbox 6개 유입을 확인했다.

같은 감사 PR에서 이름 단독 행을 `review_required`로 분리하고 주소 hint 유일 매칭은 복원한다.
H33은 row lock·guarded unlink·resolved finding을 항목별 한 transaction으로 묶고, H25B는
DB active identity 3-tuple의 정확한 1회 출현·기존 ID를 쓰기 전에 fail-closed 검증한다.
후속 적대 리뷰에서 이미 해제된 H33 대상의 누락 ledger 복구, H25B 전체 사전
변환·직렬화와 원자 교체, 행 단위 변경 수, verifier의 명시적 `feature_id`, 수동 검토 후보의
전체 ID·복사 동작까지 보강했다. H30B/C와 Lane A 순서를 다시 열고 완료 아카이브 checkbox도
일반 역사 bullet로 바꾼다. 이 전체 authored delta는 독립 Lane A a1 리뷰어 2명의 최종
재검토에서 각각 P0~P2 0건이다.
함께 감사한 #894의 H35 배포 계획은 current 0063-compatible 네 service rollback bundle,
external DB 복원 검증, cold writer fence, 네 candidate service의 identity·health 확인을
하나의 순서로 결속했다. candidate API 기본 entrypoint가 fence 전에 migration을 실행하지
못하도록 준비를 build-only로 제한하고, H36 image 검사는 network·DB credential 없는
entrypoint override/offline layer로 수행한 뒤 prod head가 여전히 0063인지 다시 확인한다.
Dagster daemon은 rollback 가능한 구간과 H30B baseline 서명까지 정지하고 app DB write
schedule/sensor도 pause한다. post-migration app·Dagster DB bundle을 같은 scratch pair에
복원해 candidate daemon을 실제 선검증한 뒤에만 forward-only cutover를 확정한다. H35가
prod daemon enablement와 ingress를 정상화하고, H30B는 signed bundle/clean scratch만
인수해 격리 DB에서 실적재를 검증한다. concierge 입력도 H35가 cursor chain·operation을
포함한 ordered 1,477행 canonical artifact로 서명하며, H30B는 live endpoint 없이 그
artifact만 resource override로 재생한다.

핵심 Python 회귀 **42 passed**, 확장 targeted **57 passed**, Ruff·mypy **196 files**
(core 117 + API 56 + Dagster 23)·ESLint·OpenAPI/type drift, Vitest **254**는 green이다.
Mocked D workers=4 두 번은 모두
**276/276**와 manifest expected/actual
failure·flake 0이었지만 runner가 manifest 뒤 nonzero로 끝나 checkpoint 전체 green으로
부르지 않는다. owned 자원·HEAD·source digest는 깨끗했고, workers=8 진단에서는 기존
`change-requests update/delete` timing 한 건이 실패했다. runner 종료 판정과 고병렬 flaky는
`T-VN-H37`로 기록했다.

기존 `ktm-tvn45-db`를 새 clone/restore/downgrade 없이
재사용한 파괴적 curation Live UI도 공식 CSV preview/commit 포함 **4/4** 통과했다. item
3,530과 active/source-present는 보존되고 링크만 3,269→3,266으로 줄어 오링크 3건의
비재생성을 실증했다. 후속 H33 실제 적용은 누락 ledger를 0→3으로 복구하고 재실행도 3을
유지했으며 H25 resource aggregate hash `bfc3d558…`는 동일하다. 후보 자원은 모두 제거했고
clone은 `0068`, healthy라 다음 task에 재사용 가능하다.

**다음 한 작업**: 감사 수정 PR의 CI green·셀프 머지와 issue #893 close를 끝낸다. 이어
사용자 지시대로 `T-VN-11A/B`를 한 브랜치·한 PR로 구현한다.

## 2026-07-30 (codex) — Lane B b0 T-VN-49A/B/C/D 완료 → post-merge 재사용 판정

**완료**: H49 A/B/C/D를 한 브랜치에서 구현했다. 19개 giant component를 domain
controller/state와 실제 section으로 분해하고 결합 상태 3곳을 reducer로 옮겨,
`no-giant-component` 19개와 `prefer-useReducer` 3개 exact 예외를 모두 제거했다.
적대 리뷰어 2명의 전체 재검토 P0~P2는 0건이다. stale geocode/reverse가 최신 입력을 덮거나
reset 뒤 재유입하는 문제, request/offline-upload의 flat prop-bag 우회, enrichment callback
churn도 반영했고 지연 geocode 입력 보존 회귀를 추가했다.

React Doctor **280 files, 0 issues**, Vitest **254 passed**, TypeScript·ESLint·production build
green이다. Mocked serial/workers=4는 각각 **275/275**이며 expected/actual failure·flake·skip과
종료 자원은 0이다. 기존 `ktm-tvn45-db`를 새 clone/restore 없이 재사용한 파괴적 Live UI도
main/recovery **2/2**, `complete/passed`다. active acceptance Feature·nonterminal request·FK,
BLOCKED와 전용 container/network/image/listener는 0이고 clone은 healthy다. 정상 soft-delete
audit 6행으로 무효가 된 종전 v5 대신 현재 clone baseline만 다시 서명했으며 Alembic downgrade와
full restore는 실행하지 않았다. 이후 main 34커밋을 충돌 없이 rebase했다.

이 완료 이관과 H22C barrier 해제는 H49 코드와 같은 merge commit으로만 `main`에 들어가므로
문서 상태가 구현보다 앞서는 구간은 없다.

**다음 한 작업**: landing 뒤 clone/checkpoint의 head·schema/content identity·잔여물·디스크
여유를 읽기 전용으로 확인해 다음 task 재사용 여부를 기록한다. 이어 다음 T-VN task 전에
별도 Claude Code PR 사후 감사를 진행한다.

## 2026-07-30 (claude) — Lane A a1: T-VN-H25B/H33/H36 완료 → 다음은 T-VN-H35

**다음 한 작업**: `T-VN-H35`(prod 마이그레이션 0064~0068 + **이미지 동시 배포**).
이후 `T-VN-H30B` → `T-VN-H30C` → `T-VN-H34` → `T-VN-H31` → `T-VN-H32` →
`T-VN-H22A/B/C`.

- **완료**: `T-VN-H36` — CSV `feature_id`가 빈 행은 이름 단독 일치로 **자동 링크하지 않는다**.
  커밋 CSV 486행 전수 + prod 리졸버 재생 결과 **막히는 자동링크는 정확히 3건이고 전부
  region 불일치**(강원→서울 ×2, 충북→전남), **정당한 링크 손실 0건**. 빈 264행 후보 분포는
  0건 256 / 2건이상 5 / 1건 3. SQL·DTO·openapi·마이그레이션 무변경, 기존 테스트 23건 무손상.
  **이 게이트는 H35 이미지에 반드시 포함돼야 한다** — H35 인수가 commit 모드 import를
  실행하는데, 그때 게이트가 없으면 3건이 그 자리에서 되살아난다.
- **또 배포되지 않은 코드를 prod 동작으로 읽었다**: "prod는 0063이라 import 자체가 실패한다"는
  틀렸다. 배포 이미지 `c8ed6164`의 import 코드는 prod 스키마와 정합해 **오늘도 동작한다**.
  또 CSV import는 `_UPSERT_ITEM_SQL`이 아니라 `_BULK_UPSERT_ITEMS_SQL`을 탄다.

- **부분 완료**: `T-VN-H33` — 오링크 3건 unlink + 공개 노출 실증 + ledger 방출.
  해제 전 공개 REST(`/v1/curations/features/{feature_id}`)가 한국관광100선 "남이섬" 자리에
  **서울 중구 사무소**, "청남대" 자리에 **전남 영암 시설**을 내보내고 있었다(각 2건/1건).
  `--apply` 재실행 멱등. **해소 증거는 리뷰 지적으로 갈아엎었다** — 초안의 "공개 노출 0건"은
  404를 0으로 읽은 것이라 없는 id에도 같은 출력이 났고, "탐지기 3→0"은 링크를 끊으면 그 행이
  모집단에서 빠지므로 정의상 0이었다. 반증 가능한 `scripts/h33_verify_public_exposure.py`로
  대체(negative control + 양성 대조, 컬렉션 표면에서 item 110/114건 생존·링크만 해제 확인).
- **🔴 `[x]`를 `[~]`로 되돌렸다 — durability 주장이 반증됐다**: "CSV가 비어 있으니 import가
  재링크하지 않는다"고 쓰고 그 근거로 닫았는데, 빈 `feature_id`는 링크를 막는 게 아니라
  **이름 자동매칭을 켠다**. 커밋된 CSV의 빈 264행 중 단일 매칭으로 풀리는 건 정확히 그
  3행뿐이고 전부 같은 틀린 feature로 복귀한다(prod 실측). finding도 `resolved`→`open`으로
  정정했다(`/admin/issues` 기본 필터가 `open`이라 resolved면 보이지도 않았다). → `T-VN-H36`.
- **교훈 — 결론을 지탱하는 문장일수록 끝까지 따라간다**: `feature_id = EXCLUDED.feature_id`를
  읽고 "덮어쓴다"까지는 맞았지만 **덮어쓰는 값의 출처를 안 따라갔다**. 구문만 보고 안전성을
  주장했고 그 한 문장으로 task를 닫았다.
- **🔴 부수 발견 — 머지 ≠ 배포**: ledger 방출을 붙이다 `ON CONFLICT`가 두 번 실패했는데
  원인이 코드가 아니었다. **prod alembic head가 `0063_pipeline_root_id`**라 H30A가 만든
  dedupe 부분 유니크 인덱스(`0067`)가 **prod에 없다**. H30A 완료 기록이 주장한 dedupe 효과는
  현재 prod에서 성립하지 않는다. → `T-VN-H35`. 완료 기록을 쓸 때 *머지된 것*과
  *배포된 것*을 구분해야 한다는 교훈이다.

- **교훈 — 게이트를 돌리기 전엔 "머지 가능"을 말할 수 없다**: 리뷰 지적을 다 반영하고
  ruff까지 통과한 뒤에도, n150 게이트가 `manifest.json` sha256 불일치를 잡았다(README를
  고치고 해시를 안 고침). 손으로 유지하던 manifest를 **스크립트가 파생시키도록** 바꿔
  같은 결함이 다시 나지 않게 했다. 리뷰 통과 ≠ 게이트 통과.
- **완료(부분)**: `T-VN-H25B` — 역반영 5건(8건 중 3건은 오링크라 배제), 매칭 재실행 + manifest 커밋.
  근거: [`reports/curation-link-backfill-2026-07-29.md`](reports/curation-link-backfill-2026-07-29.md).
  **미충족 AC 4건**(주소 축 시군구 대조 · provider provenance 조인 · preview/commit·REST/UI
  실데이터 검증 · 정지오코딩 세션 고정)은 `T-VN-H34`로 이관했다. `[x]`는 "AC 전부 충족"이
  아니라 "역반영·매칭 재실행으로 종결"의 뜻이다 — `docs/tasks.md`에 원장이 있다.
- **교훈 — "DB에 있다"는 승인 근거가 아니다**: H25A가 8건을 "확정 대상"이라 한 것은 DB에 링크가
  존재한다는 사실만 본 것이었다. 정지오코딩으로 대조하니 **3건이 오링크**였다 — 청남대는
  전남 영암, 남이섬은 서울 중구 사무소를 가리키고 있었다. 이름 일치로 붙은 전형적 오탐이다.
- **교훈 — 후보가 늘었다고 매칭이 좋아진 게 아니다**: matcher 결함을 고치니 "후보 없음"이
  191 → 1로 떨어졌지만, 늘어난 것 대부분이 무의미한 부분일치다. 등대 103건 중 89건이 상호가
  `등대`인 가게에 붙었다. **커버리지 수치만 보면 개선으로 읽히는 착시**다.
- **교훈 — 리뷰 지적을 고친 직후의 수치 변화도 검증 대상이다**: 최종 등급은
  **high 2 / review 13 / low 248 / none 1**이고, `high`는 리뷰 과정에서 6→7→2로 세 번 바뀌었다.
  세 번 다 데이터가 아니라 matcher 결함이 원인이었는데, **그중 하나는 앞 지적을 고치며 내가
  새로 넣은 것**이다 — `LIMIT`에 `ORDER BY`가 없다는 지적을 `length(name)` 오름차순으로
  고쳤더니, 양방향 substring 매칭에서 2~4글자 feature(`스카`)가 top 후보로 올라왔다.
  그때의 `high` 7→2가 "수정이 통했다"처럼 보였지만 실제로는 **정렬이 만든 착시**였다.
  겹침 길이 내림차순으로 다시 고쳐 해결. 264행 중 **208행(79%)은 후보 cap 포화**라
  애초에 이름 유일성을 판정할 수 없다.
- **H25A 결론 2개가 정정됐다**: "191건은 실제 부재 = provider 적재 범위 문제"는 matcher
  산물이었고(→ 취소), "8건은 즉시 실행 가능한 확정 대상"은 3건이 오링크였다(→ 5건으로 정정).
  다만 `T-VN-H31`(등대 공급원 부재) 전제는 다른 경로로 **재확인**됐다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H30A/B 완료, H30C 미완 → 다음은 T-VN-H25B

**다음 한 작업**: `T-VN-H25B`(CSV 역반영 8건 + 기준선 대조 매칭 재실행).
이후 `T-VN-H30C`(재작업) → `T-VN-H31`(등대 공급원) → `T-VN-H22A/B/C`.

- **완료**: `T-VN-H30A/B` — 주소 검증 결과가 `ops.data_integrity_violations`에 durable하게
  남고 `/admin/issues`에서 보인다. 실적재로 회복 검증, 배포 cursor 미설정 실증.
## 2026-07-29 (codex) — T-VN-48D 최종 gate 완료 → PR·CI·merge

**완료**: 보존 clone Live의 main/recovery 2/2 증거를 전체 restore·브라우저 재실행 없이
실패 지점부터 복구했다. 정상적인 `dataset_projection` revision `+1`은 서명 dump 직전 행을
대입한 전체 digest가 v5 checkpoint와 정확히 같을 때만 정규화하고, raw/normalized snapshot과
revision/timestamp 증거를 함께 남긴다. result는 `complete/recovered`; active acceptance
Feature·pending request·direct fixture/FK와 모든 runner 임시 자원은 0이다.

Mocked 첫 serial은 늦은 실제 MapLibre `idle`이 계측에 섞여 273/274였으며, repaint+idle+rAF
barrier로 실패 spec만 수정했다. exact `823ba52b` checkpoint D는 serial/workers=4 각각
**274/274**, expected/actual failure·flake·skip 0이다. self-owned container/network/image와
loopback listener도 0이다. PR #889 첫 CI가 찾은 Dagster test double의 typed finding 결과
계약 drift도 수정했고 package 전체 **510 passed, 1 skipped**, coverage **83.66%**다.
T-VN-48D/D.1~D.8은 `tasks-done.md`로 이관했다.

**다음 한 작업**: 최신 main을 최종 확인하고 보안 감사를 거쳐 PR을 연다. CI green과 승인
조건을 확인해 직접 머지하고 issue #881을 닫는다. 머지 뒤 `ktm-tvn45-db`와 v5 dump의
migration head·fixture identity·잔여물·디스크 여유를 읽기 전용으로 확인해 다음 task 재사용
가능 여부를 기록한 뒤, 별도 사용자 지시까지 대기한다. 새 Claude Code PR 감사는 이 대기
지시 때문에 자동 시작하지 않는다.

## 2026-07-29 (codex) — T-VN-48D 2인 재리뷰 하드닝 → 최종 exact gate

**방금**: T-VN-48/기반 PR #888 수정 델타의 적대 리뷰 2명이 찾은 Live 세션
`application_name` spoof, foreground 자식의 flock 상속, 자유형 payload timestamp cast,
구 cursor 의미 재사용, 겹치는 batch의 최신 증거 역전, mocked cleanup 실패 은폐를
`5d62cde5`에서 보강했다. 재검토에서 찾은 autocommit 부분 적용 재시도·writer default
공백과 Docker create 응답 유실 cleanup까지 `f28a6a2f`에서 닫았다. migration은 자유형
payload를 보존하고 `detected_at`으로
결정 backfill하며, NOT VALID/VALIDATE와 concurrent index로 장시간 ACCESS EXCLUSIVE 구간을
분리한다. 주소 finding upsert는 statement 관측 시각이 오래된 batch가 최신 FK/payload를
덮지 못하게 하고 발생 횟수만 증가시킨다. Live runner는 guardian flock과 exact backend
PID/start identity를 사용하며 Mocked runner는 소유 container/network/image 제거·사후 부재를
fail-closed로 확인한다.

**검증**: Ruff 전체, strict mypy 196 files, import-linter 4 contracts, shell/Node syntax,
관련 단위 49개와 신규 migration/upsert 통합 7개가 통과했다. 전체 unit의 앞선 실패 node
12개도 실패 지점 재개로 통과했고 frontend OpenAPI/type/lint/Vitest 254개와 production build가
green이다.

**다음 한 작업**: 잔여 P0~P2 0건인 두 리뷰어 재검토와 최종 문서 상태를 커밋한다. 이어
exact final SHA에서 mocked checkpoint D serial/workers=4와 보존 clone의
파괴적 Live를 재검증하고, 머지 직전 PR → CI green → 직접 머지한다. Claude Code PR 감사는
사용자 변경 지시에 따라 task PR 머지 뒤 별도 후속 단계로 옮긴다.

## 2026-07-29 (codex) — PR #888 사후 감사 반영 중 → T-VN-48D 최종 gate

**방금**: PR #888 원본 patch 적대 감사 8건을 반영했다. 주소 finding key를 source entity
type+id 전체의 고정 길이 SHA256으로 바꾸고, batch 잠금 순서를 key 정렬로 고정했다.
`last_seen_at`을 정규 column+keyset 정렬축으로 추가했으며 recurrence의 FK target 갱신,
Feature 삭제 시 ledger 보존, strict durable 기록 fail-closed,
`observed/unique/upserted` 결과를 구현했다. 종전 sweep 문서·테스트는 제거했고 H30B는
실제 Feature before/after와 인증 Admin API 실호출이 없어 다시 열었다.

**다음 한 작업**: OpenAPI·문서 계약을 확정하고 현재 branch exact delta를 적대 리뷰 2명에게
검토시킨다. 이후 exact SHA mocked serial/workers=4와 보존 clone Live를 실패 지점부터 재개한
뒤 PR·CI green·직접 머지한다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H30A 완료, H30B/C 미완

**후속 정정**: PR #888 사후 감사에서 H30B acceptance가 충족되지 않았음을 확인해 다시
열었다. `T-VN-H30B` 재실증 → `T-VN-H30C` 재작업 후 다음 Lane A task로 진행한다.

- **완료**: `T-VN-H30A` — 주소 검증 결과를 `ops.data_integrity_violations`에 durable하게
  남기는 경로와 `/admin/issues` 표면을 구현했다.
- **미완**: `T-VN-H30B` — 실적재 수치는 source record만 보고했으며 동일 snapshot의
  `feature.features` before/after와 인증 Admin API 실호출이 없다.
- **미완**: `T-VN-H30C` — MOIS만 무장했는데 `obs`/`claim`이 상호배타라 **탐지 증가 0건**.
  krforest(`region_code`)·visitkorea(`l_dong_regn_cd`)가 실제 후보임을 리뷰어가 반증했다.
- **교훈 — "dedupe를 넣었다"와 "dedupe가 된다"는 다르다**: 1차 구현의 `dedupe_key`는
  `source_record_key`(=`raw_payload_hash` 파생)에 걸려 있어, export의 무관한 필드 하나만
  바뀌어도 새 열린 행이 생겼다. 같은 export 재실행만 테스트해서 "106 유지"를 근거로 삼았는데,
  **정작 중요한 케이스(payload 변경)는 테스트하지 않았다**. H21의 "게이트를 만들었다 ≠
  게이트가 막는다"와 같은 계열.
- **교훈 — 관측 코드가 관측 대상을 잠글 수 있다**: `ops.data_integrity_violations`에 statement
  트리거가 있어 finding당 INSERT가 `ops_live` revision 단일 행에 배타 락을 잡았다. 관측을
  추가하면서 `/admin/issues` 쓰기를 막고 동시 run을 직렬화할 뻔했다. **쓰기를 추가할 때는 그
  테이블의 트리거를 먼저 본다.** `unnest` 단일 statement로 접어 해소.
- **교훈 — `jsonb ||`는 null로 지운다**: 재실행 payload의 `null`이 1회차 증거를 덮어썼다.
  durable ledger 안에서 증거를 잃는, 목적과 정반대 동작이었다. `jsonb_strip_nulls`로 차단.

## 2026-07-29 (codex) — T-VN-48D mocked 최종 gate 완료 → 리뷰·clone Live

**방금**: PR #887 docs-only 변경을 rebase한 exact `b35d7cbb`에서 checkpoint D를 serial과
workers=4로 각각 **274/274** 통과했다. expected/actual failure·flake·skip은 모두 0이다.
self-built frontend는 internal Docker network에만 두고, 검증한 container IPv4에 연결하는
loopback 전용 HTTP/WS 프록시로 host Playwright를 결속했다. source digest와 build도 동일한
격리 환경변수를 사용한다.

PR #885 감사 수정은 typed reverse 후보·시도 여부, strict/ensure의 모든 error 거부,
drop allowlist, token 단위 이름 warning, typed quarantine 보존과
`upserts == bundles + quarantine` 불변식을 고정했다. 이전 #881 기록의 geo trusted proxy
전환은 폐기하고 scoped `X-KTG-API-Key` 계약으로 정정했다. H28의 일반 좌표 정확도
과장도 baseline 규칙 재현 범위로 좁혔다.

**다음 한 작업**: Claude PR #886 감사 결과와 exact `origin/main...HEAD` 적대 리뷰 2명을
반영한 뒤, 같은 최종 SHA로 보존 clone의 실패 지점에서 파괴적 Live를 재개한다. 완료 문서를
확정하고 PR·CI green·직접 머지한다. 머지 뒤 clone의 migration head·fixture identity·잔여물·
디스크 여유를 읽기 전용으로 확인해 다음 task 재사용 가능성을 기록하고 별도 지시까지 대기한다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H25A 완료(전제 정정) → 다음은 T-VN-H30A

**다음 한 작업**: `T-VN-H30A`(주소 검증 issue를 `ops.data_integrity_violations`에 durable 기록).
이후 `T-VN-H30B/C` → `T-VN-H25B` → `T-VN-H31` → `T-VN-H22A/B/C`.

- **완료**: `T-VN-H25A` — task 전제(*"158개 중 54개가 `feature.features`에 부재"*)가
  **재현되지 않음**을 확정하고, 실제 상태를 다시 측정했다. 근거:
  [`reports/curation-unlinked-reference-evidence-2026-07-29.md`](reports/curation-unlinked-reference-evidence-2026-07-29.md).
  - 158/158 존재 + 전부 curation 링크 가능 + `created_at` 2026-06-29~07-03(측정 시점보다 앞섬).
  - `ops.feature_merge_history` **0행**, 미연결 261건 중 `source_record_key` **0건** →
    `ON DELETE SET NULL` cascade로 링크가 지워진 흔적 없음. 미연결이 맞다.
  - **신규 발견**: CSV 217/269 vs DB 225/261, collection별 총계 일치 → 같은 모집단이며
    **DB가 8건 앞서 있다**(CSV 역반영 대상, 어느 문서에도 없던 항목).
  - **미연결의 지배 원인은 등대 103건**(105 중 2건만 링크). 수목원/krforest가 아니다.
- **교훈 — 조건이 만족 가능한지부터 확인한다**: 1차 초안의 "자동 승인 가능 0건"은
  `address_hint` 일치를 요구했는데 그 열이 **486행 전부 비어** 도달 불가 분기였다. 0은 데이터가
  아니라 채점 함수의 성질이었다. H28의 tautology와 같은 계열의 오류를 **연속으로** 냈다.
- **교훈 — 없는 테이블에 물으면 답이 없는 게 아니라 "확인했다"는 착각이 남는다**: lifecycle 대조가
  `feature.feature_merges`/`feature.source_links`(둘 다 미존재)를 향했고 예외를 삼켰으며 빈 배열에
  바인딩됐다. 로그에는 "조회 불가" 세 줄만 남아 축을 덮은 것처럼 보였다. **스키마를 읽고 쓴다.**
- **교훈 — FK 정의를 발견으로 착각하지 않는다**: `curation_items.feature_id`가
  `ON DELETE SET NULL`이라 "dangling 0건"은 구조적으로 자명하다. 판별에는 lifecycle 축이 필요했다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H28A/B 완료 → 다음은 T-VN-H25A

**다음 한 작업**: Lane A a1 `T-VN-H25A`(공식 curation stale Feature reference 증거 manifest).
이후 `T-VN-H25B` → `T-VN-H22A/B/C`.

- **완료**: `T-VN-H28A/B`(#673, 사용자 지시로 한 PR). 이름 substring 규칙을 행정코드 교차검증으로
  교체하고 영구 손실 경로를 구조적으로 차단했다. **380 drop → 0, 1,477/1,477 적재.**
- **교훈 1 — 규칙이 무엇을 재는지 실데이터로 먼저 확인한다**: 이 규칙은 "좌표-주소 불일치"를
  잰다고 적혀 있었지만 실제로 잰 것은 **provider 주소 문자열의 완전성**이었다. 실측 380건 중
  365건이 `부산 기장 조방국밥`처럼 행정구역명이 없는 짧은 표기였고, 진짜 불일치는 0건이었다.
  탐지력 0인 규칙이 1년 가까이 데이터를 파괴하고 있었다.
- **교훈 2 — 병합은 정보를 지운다**: `_address()`가 payload 코드와 geo 코드를 하나의 `Address`로
  병합하면서 두 축의 독립성이 사라졌고, 그 결과 검증에는 **가능한 조합 중 가장 약한 신호**
  (geo 이름 ↔ provider 문자열)만 남았다. 권위 있는 코드는 같은 객체 안에 있었다.
  교차검증을 하려면 **병합 전 원시 축을 보존**해야 한다(`AdminEvidence`).
- **교훈 3 — 손실은 severity가 아니라 명시적 allowlist가 정해야 한다**: 기존 코드는 severity가
  `error`이기만 하면 code와 무관하게 drop했다. 그래서 규칙 하나가 추가될 때마다 영구 손실
  범위가 조용히 넓어졌다. `DROPPABLE_ISSUE_CODES` 화이트리스트로 바꿔, 손실을 늘리려면
  그 집합을 고치고 테스트를 깨야만 하게 했다. (H21의 "불변식은 구조적으로 강제되는 자리로"와
  같은 교훈의 반복 적용.)
- **교훈 4 — 침묵을 통과로 집계하지 않는다**: 두 축이 다 있을 때만 판정하므로, 판정하지 못한
  건을 "이상 없음"으로 세면 커버리지가 0%여도 완벽해 보인다. `evidence_grade_counts`로
  `dual`(실제 판정) / `claim_only` / `obs_only` / `unarmed`를 분리 집계한다. 현재 92%.
- **다중 에이전트 설계 검토가 유효했던 지점**: 13-에이전트 워크플로가 (a) 리 2자리가 합성될 수
  있어 비교 근거가 못 된다는 점, (b) MOIS는 payload에 bjd가 있으면 reverse를 아예 부르지 않아
  두 축이 동시에 존재하지 않는다는 점, (c) 단건 `ValidationError`가 batch 전체를 죽인다는 점을
  찾아냈다. 셋 다 코드를 읽어야만 알 수 있고 실데이터만으로는 드러나지 않았다.
## 2026-07-29 (codex) — issue #881 Claude PR #882~#884 감사 수정

**방금**: PR #884의 backend geo public-key query를 없애고 geo trusted proxy principal로
전환했다. credential은 `SecretStr`로만 보관하고 request URL에는 query가 없다. status·transport
오류는 원본 httpx request를 chain하지 않는 `GeoRequestError`로 바꾸며, API 중앙 handler와
admin issues/offline upload/feature-update adapter는 typed 503/502 problem code를 보존한다.

PR #882/#883 감사에서는 PinVi가 읽지 않는 `openapi-sha256.json` 생성·검사를 제거했다.
freshness 정본은 PinVi가 실제로 수행하는 핀 commit의 spec bytes/subset 직접 비교다.
`tasks.md`는 완료 H07C/H07D/H21/H29를 제거하고 H27의 OPNsense 운영자 경로를 하나로 합쳤다.

**다음 한 작업**: n150 targeted gate로 이번 감사 수정을 검증하고 원격 checkpoint commit을
남긴 뒤, T-VN-48 exact revision의 mocked·격리 clone Live 검증과 적대 리뷰 2명을 진행한다.

## 2026-07-29 (codex) — T-VN-48D 격리 clone Live 증거·실패 지점 복구

**방금**: R1을 지키는 보존 실데이터 clone 전용 trusted runner를 추가했다. root-owned
immutable source snapshot과 BLOCKED/result를 두고 exact candidate API/UI/Playwright image,
clone container/system identity, loopback 전용 포트, migration head와 시작 전후 row count를
결속한다. API는 entrypoint migration을 우회해 직접 기동하며 production compose project·
기본 prod 포트를 fail-close한다.

exact candidate `fe0c956e`의 본 acceptance **2/2**와 recovery-only **2/2**는 모두
통과했다. direct cleanup/audit 뒤 active owned Feature·weather·price·FK reference와
nonterminal change request가 모두 0이고, startup 전후 migration
`0066_curation_component_identity`·relation 49·Feature count는 동일했다. UI create/delete
감사 이력 6건만 soft-delete로 늘어 final total은 1,030,487건, non-deleted는 시작과 같은
1,030,387건이다.

최초 완료 판정은 seed의 정상 weather/price FK 2건을 residue로 잘못 보아 BLOCKED 상태에서
중단됐다. `abc1de8b`에서 seed 기대 FK 2와 cleanup/audit 기대 0을 분리하고 `recover`를
추가했다. 보존 evidence, 실패 당시 final snapshot과 현재 clone snapshot, old source
snapshot, 세 image revision, clone identity가 모두 정확히 같을 때만 완료하도록 한 뒤
build·fixture·브라우저를 반복하지 않고 실패 지점부터 복구했다. 결과는 `phase=recovered`,
BLOCKED·후보 container/image/listener 0이며 clone DB는 그대로 보존했다.

**다음 한 작업**: 리베이스된 exact revision의 적대 리뷰 2명 지적을 반영하고
mocked serial/CI-parallel 및 격리 clone Live를 다시 확정한다. Claude Code PR 사후 감사까지
마친 뒤 PR을 생성해 CI green·self-approval·직접 머지하고, clone 재사용 가능성을 읽기
전용으로 재확인한 다음 별도 지시까지 대기한다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H21 완료 → 다음은 T-VN-H28A

**다음 한 작업**: Lane A a1 `T-VN-H28A`(#673 concierge 주소 불일치 실데이터 재분류).
이후 `T-VN-H28B` → `T-VN-H25A/B` → `T-VN-H22A/B/C`.

- **완료**: `T-VN-H21` — geo 인증 결선 검증을 `KorTravelGeoRestClient` **생성 시점**으로 옮기고
  (`require_api_key` 기본 `True`), 그 과정에서 드러난 **API key 유출 경로**를 막았다.
  dedup 5건은 브랜치 코드로 실서비스 재통과.
- **열린 질문 종결**: "인증 뒤 runtime drift 있는가" → **없음**. 실 geo 응답이 기존 모델로
  무손실 파싱되고, 배포 Map 컨테이너 key = geo 컨테이너 `KTG_VWORLD_API_KEY`. 원래 blocker는
  배포 결선 결함이 아니라 ad-hoc/CLI 실행 환경에 값이 없던 것이었다.
- **교훈 1 — "guard를 만들었다 ≠ guard가 막는다"의 재발**: 호출 지점마다 preflight를 붙인 최초
  구현은 7곳 중 1곳만 보호했고, 그 회귀를 막으려 만든 AST 스캐너조차 동명 변수 mutation으로
  우회됨이 리뷰어에 의해 **시연**됐다. 규율로 지켜야 하는 불변식은 **구조적으로 강제**되는
  자리(생성자·타입)로 옮긴다. 정적 스캐너로 규율을 대신하려 하면 스캐너의 사각이 곧 구멍이다.
- **교훈 2 — 진단성을 고치는 변경이 진단성을 악화시킬 수 있다**: 결선 누락을 `ValueError`로
  던지자 기존 `except ValueError` 사다리에 걸려 422/409/500으로 나갔다. 없애려던 오진을 우리
  API 안에서 재생산한 것. **새 예외를 추가할 때는 그 예외가 지나갈 except 사다리를 먼저 읽는다.**
- **교훈 3 — 무해해 보이던 경로가 결선과 동시에 유출이 된다**: `str(httpx.HTTPStatusError)`의
  `?key=<SECRET>`는 키가 비어 있는 동안만 무해했다. 회귀 테스트가 2차 결함(`from None`은
  `__cause__`만 지우고 `__context__`엔 원본이 남음)까지 잡았다 — **비밀 관련 단언은 "값이 실제로
  wire에 실렸는지"부터 확인해야 공허해지지 않는다**(첫 시도는 키를 받은 적 없는 객체로
  단언해 유출 구현도 통과시켰고, 리뷰어가 이를 지적했다).

## 2026-07-29 (claude) — Lane A a1: T-VN-H29 완료, H27 보류 → 다음은 T-VN-H21

**다음 한 작업**: Lane A a1 `T-VN-H21`(`kor-travel-geo` live 인증 preflight·dedup 5건 재실증).
이후 `T-VN-H28A/B`(#673) → `T-VN-H25A/B` → `T-VN-H22A/B/C`.

- **완료**: `T-VN-H29`(PinVi PR #418) — map-import POI가 통합검색에서만 좌표 null이던 실제 버그.
  근인은 `_snapshot_coord`가 중첩 `coord`만 읽은 것(Map view는 `extra="forbid"` + `coord` 미보유라
  **구조적으로 항상 None**). 정본 `extract_feature_coord`에 위임해 해소하고 회귀 10건을 추가했다.
- **보류(사용자 지시)**: `T-VN-H27`(#819 HAProxy tunnel). 프록시가 **OPNsense 라우터**에 있어
  저장소에 config가 없고(n150도 haproxy inactive) 설정·검증 모두 라우터 접근이 필요하다.
  에이전트 실행 불가 — 운영자가 적용 후 실증한다.
- **교훈**: H07D 리뷰의 "소비자 전수 감사"가 이 버그를 찾아냈다. 계약을 typed로 좁히면 그
  **소비자 쪽 잘못된 read가 구조적으로 죽은 코드**가 되는데, 계약 작업 시 소비자 read를 함께 훑으면
  이런 잠재 버그가 드러난다.

## 2026-07-29 (claude) — Lane A **a0 종료** (H07C를 ADR-079로 기각), 다음은 a1

**다음 한 작업**: Lane A **a1** 첫 항목 `T-VN-H29`(PinVi 통합검색의 map-import POI 좌표 null 복구
— `search.py::_snapshot_coord`가 `feature_snapshot["coord"]`만 읽는데 Map view에 `coord`가 없어
구조적으로 항상 None; 좌표는 top-level `lon`/`lat`에 있고 `admin_pois`/`kasi`는 정상 해석).
이어서 `T-VN-H27`(#819 HAProxy tunnel) → `T-VN-H21` → `T-VN-H28A/B` → H25 → H22.

- **a0 완료**: `T-VN-H07A`(#814) · `T-VN-H07B`(PinVi #415) · `T-VN-H07D`(Map #878 + PinVi #416) ·
  `T-VN-H07C`(**기각** — ADR-079).
- **H07C 기각 요지**: 제안 필드는 `map_source_revision`의 순수 함수라 **탐지력이 0**이고
  (그 revision은 attestation이 배포 이미지 OCI 라벨까지 이미 결박), v5 승격은 **실재하는 운영
  막다름**(rollback 무력화 + 기존 이미지 revision에 digest blob 부재로 capture 불가)을 만든다.
  구현·테스트를 마친 상태에서 적대 리뷰 2명이 실증해 되돌렸다.
- **유지**: `openapi-sha256.json`은 소비자 freshness 용도로 남는다 — PinVi가 **독립 사본**과
  대조하므로 그쪽에서는 실질 탐지력이 있다(H07B/H07D).
- **규율 정정**: OpenAPI 변경 task의 완료 조건에서 compatible-pair 재-capture·C7 attestation을
  빼고, per-surface digest 갱신 + 소비자 스냅샷 재-vendor로 바꿨다.
- **교훈**: 계약에 새 필드를 넣을 때 **독립 유도값과 대조되는지**를 먼저 본다. 대조 상대가 없으면
  형식 검사만 남고 그건 탐지력이 아니라 스키마 비용이다.

## 2026-07-28 (claude) — Lane A a0 T-VN-H07D 완료 (Map #878 + PinVi #416, #815 close)

**다음 한 작업**: Lane A a0 마지막 항목 **`T-VN-H07C`(#812 compatible-pair manifest v5)** —
docker-manager compatible-pair에 Map per-surface OpenAPI digest manifest SHA를 추가하고
capture·validate·deploy를 v5로 전환, Map export drift와 C7 attestation을 같은 digest에 연결,
ADR-076 개정. 이후 a1(`T-VN-H29` → `T-VN-H27` → …).

- **완료(이번 세션)**: `T-VN-H07A`(#814) · `T-VN-H07B`(PinVi #415) · **`T-VN-H07D`**(Map #878
  `5c0e0cae` + PinVi #416 `8ea83358`). a0에서 H07C만 남았다.
- **H07D 요지**: PinVi가 소비하는 admin detail-snapshot의 계약이 OpenAPI로 **표현조차 안 되던**
  상태(free-form dict + 숨은 alias 경로)를 typed view 4종 + 라우트 등록 테스트로 해소하고,
  PinVi 쪽에 전이적 폐포 subset(19 KB)을 vendor해 소비자 계약을 고정했다.
  freshness는 `contract-pin-consistency`(차단·required check 등록)와 `contract-staleness`
  (예약·비차단)로 역할을 나눴다.
- **주의(반복된 실패 패턴)**: "게이트를 만들었다"와 "게이트가 실제로 막는다"는 다르다. PinVi에서
  차단이라고 만든 job이 required check 목록에 없어 **아무것도 막지 못하는 상태**였고 리뷰어가 잡았다.
  게이트를 추가할 때는 **required check/merge gate에 실제로 연결됐는지**까지 확인할 것.
- **주의(3회 반복)**: 소비자가 어떤 필드를 읽는지 추측으로 단정하지 말 것(H07B `cluster_unit`,
  H07D `feature_snapshot`, H07D `search.py` 귀속). 매번 리뷰어가 소비자 저장소 grep으로 뒤집었다.

## 2026-07-28 (claude) — Lane A a0 T-VN-H07D ① Map half landing (payload 타입화)

**다음 한 작업**: **T-VN-H07D ② PinVi half** — Map admin OpenAPI의 detail-snapshot 스키마를 PinVi에
vendor하고 PinVi가 읽는 필드로 소비자 계약을 고정한 뒤, **snapshot freshness를 CI에서 실제로
비교**해 skip으로 green이 되는 경로를 제거한다(두 저장소 모두 PUBLIC이라 live-compare 가능).
그 뒤 `T-VN-H07C`(#812 manifest v5).

- **H07D는 cross-repo 2 PR**이다. Map half만 landing했으므로 `tasks.md` a0 `T-VN-H07D`는
  **열린 상태 유지** — PinVi half까지 끝나야 완료다.
- **Map half 요지**: PinVi가 읽는 필드가 전부 free-form `dict[str, Any]` 안이라 계약을 고정할
  방법이 없었다 → `theme`/`content`/`source`/`feature_snapshot`을 typed view로 전환.
  **etag는 repo payload dict 기준이라 그 dict을 손대지 않아 etag/캐시 계약 불변.**
  PinVi가 호출하는 경로는 `include_in_schema=False` 숨은 alias라 라우트 등록 자체를 테스트로 고정.
- **교훈(2회 연속 같은 실수)**: 소비자 코드를 끝까지 읽지 않고 "PinVi는 이 값을 안 읽는다"고
  단정했다가 리뷰에서 뒤집혔다(H07B `cluster_unit`, H07D `feature_snapshot`). **소비 여부는
  추측하지 말고 소비자 저장소를 grep으로 확인할 것.**
- **재발 방지**: OpenAPI를 바꾸면 `openapi.json` + `openapi.user.json` + **frontend
  `src/api/types.ts`** 세 산출물을 함께 재생성해야 한다(types.ts 누락 시 frontend CI drift로 머지 불가).

## 2026-07-28 (claude) — Lane A a0 T-VN-H07B 완료: PinVi consumer contract landing

**다음 한 작업**: Lane A a0 다음 항목 **`T-VN-H07D`(#815)** — PinVi 런타임이 실제 소비하는 admin
detail-snapshot의 plan/item required/type/enum을 Map full OpenAPI와 PinVi vendored snapshot 양쪽에
고정하고, admin/user snapshot freshness를 CI에서 실제 비교해 skip으로 green이 되는 경로를 제거한다.
(H07B에서 user 스냅샷은 Map main `8880c29b`로 재동기화됨 — admin 스냅샷도 같은 대조 필요.)
이후 `T-VN-H07C`(#812 manifest v5).

- **완료(이번 세션)**: `T-VN-H07A`(Map #814 → `259a9ec5`) · `T-VN-H07B`(PinVi #415, #403 대체).
- **H07B 요지**: #403이 고정하던 공개 curated 표면은 PinVi가 호출하지 않는 경로였다(admin
  detail-snapshot = H07D 소유, producer exact = H07A 소유) → 전량 제거하고 **실제 소비 필드**의
  typed consumer contract 21 schema로 대체. stale 스냅샷(174 commits 뒤) 재동기화. 경로→컨테이너
  →item·map value·envelope meta·model 결합까지 사슬 전체 고정. 변이 30건 전부 검출.
- **교훈**: consumer 계약에 producer의 exact property 집합을 복사하면 무해한 additive 변경마다
  false-red가 난다(Map 0066 `external_component_id`가 실제 사례). consumer는 "읽는 필드의 shape"만
  고정하고, 대신 경로→필드 사슬을 끝까지 닫는 편이 옳다.
- **주의**: 최종 확인이 제 오기를 잡았다 — `data.get("cluster_unit")`을 "항상 None"으로 단정했으나
  client가 `meta.cluster.cluster_unit`을 의도적으로 re-projection한다. 정적 추론으로 "버그"를
  단정하기 전에 client/테스트를 함께 읽을 것.

## 2026-07-28 (codex) — T-VN-46 파괴적 Live·task 완료

**다음 한 작업**: T-VN-46 최종 문서와 Claude Code PR #874 사후 감사 결과를 원격 branch에
commit/push하고 최신 `origin/main`에 rebase한다. 머지 직전에만 새 PR을 열어 CI green 뒤
셀프 머지한다. 머지 후 `ktm-tvn45-db`·dump의 T-VN-48A 재사용 가능성을 먼저 판정한다.

- exact 구현 head `378c6524`는 적대 리뷰어 2명의 최종 P0/P1/P2 0건 확인을 받았다.
  지원 Node 22.22.2/npm 12.0.1 clean install의 audit·unreviewed script·npm tree가 모두
  0이고, ESLint·React Doctor·Sharp ABI·OpenAPI codegen drift·type-check·production build를
  통과했다.
- `ktm-tvn45-db`를 rollback 없이 `0066_curation_component_identity` 그대로 재사용했다.
  candidate API/UI/C7 image의 revision을 exact head로 확인하고 파괴적
  `admin-feature-acceptance-write.live.spec.ts`를 인증 setup 포함 **2/2, 37.9초** 통과했다.
- 첫 실행은 API production profile의 공개 API key gate 누락을 해당 API container 설정
  단계에서 복구했다. 이어 prod-derived UI env의 internal URL override 누락으로 candidate
  아닌 endpoint가 첫 admin cleanup을 `403`으로 거부했으며, write 전 실패를 확인한 뒤 UI와
  브라우저 artifact를 폐기하고 candidate loopback URL로 다시 띄워 실패한 spec부터 재개했다.
- 최종 감사는 API-owned non-deleted Feature **0건**, pending change request **0건**,
  weather/price fixture **0건**이다. clone의 non-deleted Feature는 **1,025,428건**, health는
  정상이다. 인증 상태/cookie·raw trace·screenshot·민감 로그·임시 env/session secret과
  candidate container는 모두 폐기했고 DB·dump와 redacted immutable 수치만 유지한다.
- Claude Code PR #874 사후 감사 이슈 #875는 #814 구현·landing 근거와 후속 11개 테스트 green을
  확인했지만, 완료된 H07A가 active `tasks.md`에 중복된 P2와 #870 전용 CI 대기 생략 예외를
  #874가 재사용한 P2를 찾았다. H07A는 `tasks-done.md`만 정본으로 남겼고, #874의 사후 CI green은
  보상 근거일 뿐 후속 문서 PR의 예외로 승계하지 않는다.

## 2026-07-28 (claude) — Lane A a0 T-VN-H07A 완료: Map #814 residual contract landing

**다음 한 작업**: Lane A a0 다음 항목 `T-VN-H07B`(PinVi #403 재감사·landing) — 최신 PinVi main에
rebase하고 H07A의 실제 user OpenAPI SHA와 대조해 이미 흡수된 assertion 제거, PinVi가 읽는 필드만
typed consumer contract로 남겨 #403 갱신·머지. 이어 H07D(#815) → H07C(#812).

- **완료(이번 세션)**: `T-VN-H07A` — #814를 최신 main(259a9ec5) 위 residual로 재감사·landing.
  중복(union 구조·stale tasks.md) 제거, field-level 잔여만 유지. 적대 리뷰어 2명 land, n150
  CI-parity 11 green(0066 external_component_id drift 재조정 포함), GitHub CI green. PR #814.
- **주의(재발 방지)**: 착수 시 worktree main이 origin/main보다 46 commits 뒤처져 stale
  tasks.md(구 b-lane only 구조)를 읽고 Lane B를 건드릴 뻔했다. origin/main sync 후 a0/a1 Lane A
  구조가 정본. 작업 중 codex 병렬 진행분(+32 commits)을 origin/main rebase로 최신 유지.
- **워크플로우**: PR은 머지 직전에만 열고 그 전엔 리모트 브랜치에 자주 커밋(사용자 지시).

## 2026-07-28 (codex) — T-VN-46 npm optional tree 0-problem 전환

**다음 한 작업**: 원격 branch `feat/t-vn-46-npm-optional-tree`의 구현 head를 적대적 리뷰하고,
#870 이후 closed 포함 Claude Code PR을 재감사한다. 이어 재사용 DB에서 파괴적 Live UI를
통과시킨 뒤 task 문서를 완료 처리하고 머지 직전에 PR을 연다.

- 동일 lockfile clean install에서 npm 10.9.4는 Linux에서 제외된 `os=freebsd`·`cpu=wasm32`
  optional 부모의 자식 6개를 root에 설치한 뒤 `npm ls`에서 `extraneous`로 판정했다. `nested`
  install과 `npm prune`도 같은 6개를 남겼다.
- 지원 Node 22.22.2에서 최신 npm 12.0.1 clean install은 direct dependency 추가나
  `npm ls` 출력 필터 없이 `problems` **0개**다. exact npm을 12.0.1로 올리고
  `verify:npm-tree`의 기존 허용 목록을 빈 문제 집합 단언으로 교체했다.
- npm 12의 install-script 경계는 검토한 `esbuild@0.28.1`과
  `unrs-resolver@1.12.2`만 root `allowScripts`로 허용하고, version drift와 신규 script는
  `.npmrc`의 `strict-allow-scripts=true`로 fail-close한다. Node engine도 npm 12가 지원하는
  exact union `^22.22.2 || ^24.15.0 || >=26.0.0`으로 제한했다.
- 격리 clean install에서 audit **0**, unreviewed install script **0**, npm tree
  **0 problems**, ESLint·React Doctor **0 diagnostics**, Sharp SVG→WebP ABI, admin/user
  codegen drift, 두 type-check와 production build를 모두 통과했다. npm 12가 정규화한
  lockfile은 재실행 drift도 0이다.
- T-VN 작업에는 issue를 만들지 않는다는 사용자 정정에 따라 #872는 `not planned`로 닫았다.
  조기 draft PR #873도 닫았고, 원격 branch에 자주 커밋한 뒤 검증 완료 시점에 새 PR을 연다.

## 2026-07-28 (codex) — PR #871 머지 후 T-VN-46 재사용 checkpoint

**다음 한 작업**: Lane B `T-VN-46`에서 npm 10.9.4와 최신 npm의 동일
lockfile clean-install을 최소 재현하고 Sharp 0.35.3 optional graph의 Arborist 소유 경계를
확정한다. 작업 중 main을 주기적으로 rebase하고, 적대 리뷰 단계에 #870 이후 closed 포함
Claude Code 신규 PR을 다시 조회해 있으면 전문 서브에이전트 1명의 리뷰·수정을 이 PR에 합친다.

- PR #871은 exact head `944b2563`의 8개 CI가 모두 green인 뒤 merge commit `64c158c5`로
  main에 반영됐다.
- 보존 clone은 main head와의 차이 `0063→0064→0065→0066`을 rollback 없이 forward upgrade했다.
  현재 `0066_curation_component_identity`, Feature **1,030,469건**, 합성 Feature **22/22
  deleted**, incomplete tombstone **0건**, change request **80건/pending 0건**, POI cache target
  **90건**, DB **17GB**, health 정상이다.
- main schema와 호환되고 T-VN-46이 frontend dependency/gate 작업이라 기존 합성 tombstone이
  검증을 오염시키지 않으며 가용 공간도 **85GB**다. 따라서 `ktm-tvn45-db`와
  1,175,043,355-byte dump/redacted checkpoint를 T-VN-46 Live에 재사용한다.
- #870 이후 closed 포함 PR은 현재 #871뿐이며 신규 Claude Code PR은 없다. 당시 생성한
  issue #872는 후속 사용자 정정에 따라 `not planned`로 닫았다.

## 2026-07-28 (codex) — Lane B T-VN-45 구현·파괴적 Live 완료

**다음 한 작업**: PR #871 exact head를 적대적 리뷰어 2명이 재검토하고 전체 gate·GitHub
Actions green 뒤 셀프 머지한다. 머지 후 다음 Lane B task `T-VN-46` 착수 전에
`ktm-tvn45-db`·dump·redacted checkpoint의 migration/schema/fixture·파괴적 잔여물·
코드/API 호환성·디스크 여유를 판정해 재사용 또는 정확한 정리를 기록한다.

- 지도 Live spec은 `/v1/admin/features/in-bounds`의 모든 요청 URL과
  `items`/`clusters` 응답을 검증한다. cache hit는 map idle 뒤 마지막 성공 응답의 전체 point
  `feature_id` 집합과 server cluster key/count/centroid가 실제 DOM과 exact 일치할 때만
  통과한다. marker 식별자 누락, 취소 요청의 URL drift, 다른 feature 상세 응답, 같은 합계의
  ID 상쇄를 모두 false-green으로 허용하지 않는다.
- 실패했던 상세 클릭만 재개해 인증 포함 **2/2**를 통과했다. 이어 실데이터 write workflow가
  add 승인→update 승인→update 거절→비활성화→delete 승인을 모두 수행해 인증 포함
  **2/2, 48.3초**를 통과했다. 최신 합성 Feature는 `deleted`이며 전체 합성 감사 범위의
  non-deleted Feature와 pending change request는 각각 **0건**이다.
- 파괴적 Live 중 드러난 기존 spec drift도 같은 실패 지점에서 복구했다. ADR-066 이후 제거된
  `operator` 입력, 접힌 고급 JSON 필드, 현행 create/review/preview 접근성 이름과 한국어 상태,
  admin 목록의 exact `feature_id` 최종 응답 대기를 반영했다.
- 재개용 clone `ktm-tvn45-db`는 migration head `0063_pipeline_root_id`, Feature
  **1,030,469건**, POI cache target **90건**이며 health가 정상이다. 적대 리뷰의 update nested
  필드·비기본 `marker_icon=park` 보존과 inactive exact 목록 P2를 반영한 뒤 지도 상세는 인증
  포함 **2/2, 11.1초**, 파괴적 write는 위 수치로 다시 통과했다. API/UI container와
  Playwright 인증 상태/cookie·raw trace·실데이터 screenshot·민감 로그·임시 env/session
  secret은 최종 검증 직후 폐기했다. `PGPASSWORD` metadata가 남아 있던 중지 상태의 clone
  repair/restore/dump transient container 8개도 제거했다. DB·dump와 위 수치만 담은 redacted
  checkpoint만 머지 후 재사용 판정 전까지 보존한다.
- `T-VN-H18`은 어떤 Agent A/B 실행 lane에도 속하지 않는 거버넌스 결정 대기 보류 항목이다.
  repo 소유자가 approval enforcement 전환 시점을 정하기 전에는 착수하지 않는다.

## 2026-07-28 (codex) — PR #869 머지 후 task 전면 재감사

**다음 한 작업**: 문서 PR #870은 적대적 리뷰어 2명의 잔여 P0/P1/P2 0건 확인을 마쳤다.
문서 검증·보안 감사를 통과시킨 뒤 사용자 지시에 따른 일회성 예외로 CI를 기다리지 않고
셀프 머지한다. 이어서 Lane A는 `T-VN-H07A`, Lane B는 `T-VN-45`를 각각 시작한다.

- PR #869는 exact head `c0cd4979`의 GitHub Actions 8개가 모두 green인 뒤 merge commit
  `25e9304b`로 main에 반영됐다.
- Map의 열린 이슈는 #673·#812·#815·#819이며, 현재 문서 PR #870을 제외한 기존 열린 PR은
  #814다. PinVi 관련 열린 PR은 #403, 외부 추적 이슈는 #215이며 docker-manager/geo에는
  열린 PR·이슈가 없다.
- Map #814는 main보다 85 commits, PinVi #403은 13 commits 뒤처졌다. Map main에는 유사
  user schema assertion이 이미 있으므로 H07A/B는 rebase 후 중복을 제거하고 residual contract만
  다시 검토하는 landing task로 바꿨다.
- `T-VN-H21`의 실제 `/v2/reverse` 첫 400 body는
  `E0100 query.key: Field required`였다. `lon`/`lat` request schema는 배포 OpenAPI와 일치하지만
  test 코드가 전달하는 settings key가 실행 환경에서 비어 route 처리 전에 막힌 상태다. 인증 뒤
  downstream runtime drift는 5건을 재실증하기 전까지 미확정이다.
- #673과 #819를 각각 `T-VN-H28A/B`, `T-VN-H27`로 승격했다. 큰 frontend/API/curation/Wave 2
  task는 독립 검증 가능한 child task로 분해했다.
- Agent A는 H07 cross-repo 계약→edge/geo/data-quality queue, Agent B는 T-VN-45부터 frontend
  hardening→PinVi 소비 API queue를 순차 소유한다. 두 lane은 병렬 실행하되 migration 번호,
  OpenAPI 정본, compatible pair와 Wave 2 freeze barrier에서만 직렬화한다.
- PR #870은 사용자 지정 일회성 문서 예외라 destructive Live UI와 CI 대기 대상이 아니다.
  적대적 리뷰어 2명, `git diff --check`, task index/detail 정합, prod redaction과 staged
  민감정보 scan은 유지하며 코드/DB/API에는 변경이 없다.

## 2026-07-27 (codex) — T-VN-47 + durable curation + #868 완결

**다음 한 작업**: 본 PR의 CI green·셀프 merge 뒤 전체 열린 task와 실코드·열린 이슈를
재감사한다. 더 작은 실행 단위로 분해하고 의존성 기준으로 Lane A/B 병렬 범위를 다시 배치한
문서 전용 PR을 CI 대기 없이 머지한 뒤, 갱신된 Lane B 순서로 진행한다. 사용자 최신 지시에 따라
그 문서 PR부터 적대적 리뷰어 2명을 운용한다. `T-VN-45`는 그 재감사 전까지 미착수 상태로 유지한다.

- React Doctor full scan은 269개 파일·actionable 진단 0건이다. canonical config와 exact verifier가
  shadow config, command·scope 축소와 package-level 우회를 fail-close한다. runtime correctness
  진단은 근인 수정했고 giant component 19개·reducer 후보 3개는 `T-VN-49`로 이관했다.
- #862의 H13 조건부 upsert를 적대 리뷰한 결과 source 누락 삭제, archived identity 재생성,
  legacy/canonical 단방향 상태, Feature merge의 provider/operator clock 혼합과 parent/item lock
  inversion을 확인했다. migration 0065에서 source/operator revision을 분리하고 archived/NULL
  exact identity를 한 행으로 강제했다.
- `legacy_projection_id`가 projection과 durable item을 명시적으로 연결한다. stable collection key는
  mutable theme slug 대신 theme/source UUID와 title hash를 사용하고 semantic duplicate는
  `:split:<collection_id>`로 보존한다. 0064 slug 재사용으로 탈취된 active/archived projection과
  원 owner 관계는 명시적 `legacy_projection_id`로 복구한다. canonical-only item은 원 projection
  durable link가 없고 external identity도 theme 간 공유될 수 있으므로 자동 owner 복구를 하지
  않는다. upgrade 전 old projection 삭제 여부와 관계없이 모든 legacy-marker collection에서
  `draft/admin_only` quarantine에 보존한다. mutable metadata marker가 지워진 이력은 immutable
  `legacy:` key namespace를 함께 검사한다. exact `legacy:quarantine:<UUID>` key와 immutable
  migration creator가 모두 일치하는 산출물만 재격리하지 않아 정상 `quarantine:` theme slug와
  migration 왕복 identity를 함께 보존한다. mutable quarantine metadata에 `migrated_from`이
  추가돼도 upgrade·downgrade key rewrite에서 같은 결합을 제외한다. 임의 admin key가 base/split/과거 staging
  namespace를 선점해도 upgrade/downgrade가 중단되거나 수동 key를 덮지 않는다.
- `source_record_key IS NULL`인 legacy DELETE→새 UUID 재삽입도 기존 external identity와 operator
  tombstone을 복원한다. cross-title A→B/B→A 동시 이동은 target collection 뒤 source parent를
  잠그지 않고 item만 잠가 교착을 제거했다.
- 단독 적대 리뷰어가 #840 이후 Claude Code 작성 PR 21건과 최신 code SHA를 함께 검토했다.
  migration 왕복·owner repair·오래된 projection의 후속 owner 탈취·null-source tombstone·실제 두
  transaction 교차 이동을 포함한 관련 unit/integration/API 회귀와 외부 geo live 5건을 제외한
  최종 backend 전체 **2,405건**, static·frontend 전체 gate가 통과했다. 격리 실데이터 destructive
  Live UI 결과는 `journal.md`의 같은 날짜 항목을 정본으로 한다. curation exact code `7e2920aa`는 reviewer
  신규 P0–P2 0건·PostgreSQL 46/46이다. Live 기대값 환경화의 빈/공백 입력·exact match·
  중복 identity·runbook checkpoint P2까지 반영한 최종 `f6a50866`에서도 잔여 P0–P2는 0건이다.
- 전체 clone에서 0053이 동일 KMA target-grid legacy queued job 3건을 무차별 거부하는 blocker를
  발견해 `T-VN-H23`으로 등록하고 같은 PR에서 완결했다. queued winner는 runtime dispatch 정렬로
  결정하고 나머지는 감사 가능한 cancelled terminal로 전환한다. running 둘 이상과 cancellation
  marker 중복은 mutation 전에 중단한다. 단독 리뷰어가 cancellation audit 훼손 가능성을 찾아
  보강했으며 exact code `ca313d32`에서 잔여 P0–P2 0건, migration 회귀 5/5·관련 묶음 64/64다.
- `T-VN-H24`는 source item과 펼쳐진 membership component를 분리했다. durable identity는
  `collection + external_item_id + external_component_id`이고 Feature는 nullable·mutable target이다.
  legacy UUID/operator/source/archive 이력을 첫 authoritative import에서 같은 행으로 승계하고,
  모호한 후보와 active Feature 중복은 preview/commit 전에 fail-close한다. 0064→0066 연속
  Alembic transaction은 0065의 지연 FK·trigger event를 0066 DDL 전에 검사·소진한다. 단독
  적대 리뷰어는 exact code `baf40a04`에서 P0–P2 0건을 확인했다. 실제 prod clone의
  0036→0066 연속 migration도 완료돼 이전 pending trigger 오류가 해소됐다. 같은 clone에서
  성공한 migration·build·destructive import를 보존해 실패 단계부터 재개했고, 최종
  `e8d167c5` 기준 공식 collection/item 19/486, component 2/2, operator adoption 2,
  duplicate target 0을 확인했다. prod head `0036`, Feature 1,099,359건, collection 미존재와
  API/UI health는 불변이며 성공 뒤 clone을 삭제했다.
- 작업 중 추가된 `T-VN-H26`/GitHub #868은 main에 이미 있던 canonical
  `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` direct alias를 재확인하고, 남은 수용 조건인 기존
  API-prefixed 이름 fallback을 추가했다. canonical-only/legacy-only/미설정/동시 설정 우선순위와
  잘못된 admin header `403`을 API auth **84건**으로 고정했다. 사용자 지시에 따라 이 변경만
  적대적 리뷰에서 제외했다.
- 작업 중 발견한 giant/reducer 구조 debt는 `T-VN-49`, 실 `kor-travel-geo /v2/reverse` 400
  계약 drift 5건은 `T-VN-H21`, migration quarantine의 admin 재분류 workflow는
  `T-VN-H22`로 등록했다. `T-VN-H23`은 이 PR에서 바로 완료했다. migration head는
  `0066_curation_component_identity`다.

## 2026-07-27 (claude) — 🎯 Lane B b4 대행: H13·H14·H15 완결, H20 진행, H18 예정

**다음 한 작업**: b4 = **H13·H14·H15·H20 완료**, **H18만 보류**(governance — approval 필수화가 self-merge
즉시 차단, repo 소유자가 시점 결정). H18 착수 또는 다른 지시 대기. 사용자 지시로 Lane A가 Lane B b4 대행 완료.

- **H20 완료**: prod admin password/hash 회전 + login 200 검증. 회전 중 compose `$` interpolation으로 UI
  일시 잠김→`$$` escape로 복구(투명). 잔여(사용자): local doc stale 섹션 삭제·session secret 미회전·n150
  .env 백업 정리. 상세 journal/tasks-done 2026-07-27.

- **완료(b4)**: `T-VN-H13`(#699→#862 curation override 보존) · `T-VN-H14`(#700→#863 KREX bounded-retry) ·
  `T-VN-H15`(#805→#864 c7 IPv6 origin). 각 적대 리뷰 2명 + 회귀 + CI green.
- **진행(H20)**: credential-safe hash 생성 완료(평문→gitignored doc, hash→repo 밖 scratch, 값 비노출).
  잔여 = prod UI env ktdctl 회전(R2) + login 200/기존 401/세션 폐기 검증(사용자 실행).
- **직전 완료(세션)**: T-VN-H19(C2 실증→C6c/T-VN-03 전체 종결)·H12·H16·H17·H06.

- **완료(이번 세션 최근)**: `T-VN-H19` — public API key 양성 production runtime 실증(admin-BFF 임시 key
  발급→valid 200·wrong 401·revoke 200·revoked 401, credential-safe). **경계 매트릭스 14/14 완성 →
  T-VN-03+T-ADM-C6c 전체 완료**(C2 보류 조건 해소).
- **완료(이번 세션)**: `T-VN-H12` — status marker 좌표만 `sha256(RUN_ID)` jitter(`STATUS_MARKER_LON/LAT`) +
  `recenterMapTo`. **n150 c7-v6 live 검증**(map=c8ed6164)에서 status marker 통과. #855(shared base jitter)의
  weather/price seeding desync를 live가 잡아 **#859에서 status-only로 국한 수정**(#858 뒤 rebase, merged
  `baa04c08`). weather/price는 고정 base = LIVE-01 baseline이라 무변경. 상세 journal/tasks-done 2026-07-27.
- **교훈**: 정적 적대검증이 외부 Python seeding helper 좌표 계약을 못 모델링 → cross-process 좌표는 live 필요.
- **직전 완료(세션)**: T-VN-H06·T-ADM-C6c+T-VN-03(#392 close)·T-VN-H16/H17(LIVE-01 후속 7/7 close).

## 2026-07-27 (codex) — T-VN-44 완료 (#858)

T-VN-44는 frontend lint·schedule recovery·가격 identity와 R1 격리 실데이터 Live UI를
완료해 #858로 main에 반영했다.

- frontend full ESLint 기준선 1 error/30 warnings를 0 problem으로 내리고 `npm run lint`와 CI를
  `--max-warnings 0`으로 고정했다. TanStack compiler 경계는 `data-table.tsx` 한 파일·두 함수만
  허용하고 verifier가 module/function directive·legacy `use no forget`·inline disable·
  `.mts`/`.cts`를 포함한 실제 lint 파일 집합 drift를 fail-close한다.
- schedule cron 수정은 effect 내부 동기 state 변경과 render당 sessionStorage scan을 제거했다. mutation
  경계에서 dialog를 닫고 storage scan 완료 전 fail-closed 잠금을 유지한다. PATCH 응답 유실·409·terminal
  audit 실패 후 같은 idempotency key/body 복구와 reload 첫 frame 비활성 상태를 mocked E2E로
  고정했다. 최신 B 목록 scan 뒤 과거 A mutation이 늦게 settle되는 순서도 최신 refresh ref와 B scan 완료 barrier를 둔 controlled-response Chromium 회귀로 잠금 고착을 막았다.
- 가격 identity를 DB·repository·REST/OpenAPI·지도·chart 전체에서
  `provider + price_domain + product_key`로 통일했다. migration 0064는 concurrent DDL 부분 성공 뒤
  Alembic stamp만 실패해 재실행돼도 이미 유일한 유효 index를 먼저 지우지 않는 대칭 복구를 제공한다.
- #840 이후 Claude PR 전문 감사 범위를 #841~#857의 Claude 작성 15건으로 확장했다. #854의
  public-key C2 “등가 충족”은 서로 다른 auth branch를 혼동한 완료 오판이라 되돌리고, credential-safe 직접 실증을 `T-VN-H19`로 열었다.
  #853의 H06 증거는 n150 Linux 24/24로 대체했고 #855 H12 live 잔여와 #856/#857 H16/H17 완료를
  보존했다. 최신 main에 재유입된 C2 전체 완료 오기는 같은 정정으로 제거했다.
- **R1 최종 파괴적 live**: 운영 스키마와 실제 가격 feature 1건·관측 20건을 별도 PostGIS 컨테이너로
  읽기 복사하고 실제 관측 1건을 복제본에서 변경했다. branch API가 0063→0064를 적용한 뒤 run-unique
  API/UI/auth에서 로그인 GET/POST 200+cookie, 공식 admin feature acceptance 2/2를 통과했다. 같은
  product의 provider/domain 두 series는 REST current 2/history 4, 상세 chart 2선·4점, 지도 marker 두
  identity로 실제 Chromium에서 확인했다. 운영 DB fixture 0·head 불변·health 200을 재확인하고 전용
  port/container/network/image/C7 runtime 잔여를 0으로 정리했다.
- local-only prod password와 배포 hash 불일치는 별도 `T-VN-H20`로 등록했다. 비밀값은 tracked 문서에
  기록하지 않았다. T-VN-43은 #851로, H06은 #813+#852 후속 검증으로 완료 이관했다.

## 2026-07-27 (claude) — 🎯 T-VN-H12 landing + T-VN-H16/H17 이슈 재검증(LIVE-01 후속 7/7 close)

**Lane A 다음 작업**: `T-VN-H12` live-lane 실증과 `T-VN-H19` public-key 양성 runtime 실증.
`T-VN-H16`/`T-VN-H17`은 #856/#857로 완료했다. tasks.md 인덱스가 정본.

- **완료(이번 세션)**:
  - `T-VN-H12` — status marker 좌표 `sha256(RUN_ID)` jitter + `recenterMapTo`. PR #855 머지 후
    **n150 c7-v6 live 검증**에서 status marker 통과 + shared-base jitter의 weather/price seeding desync
    (공식 runner latent bug) 발견 → **status-only jitter로 수정(PR #859)**. #859는 #858 머지 뒤 rebase 머지.
  - `T-VN-H16` — LIVE-01 후속 OPEN 7건 재검증 → 6 close(dm#63·#70·map#712·#719·#777·#694, 근거 코멘트).
  - `T-VN-H17` — map#684를 조건 #8 검증범위 축소(write/error UI 엣지=mock, read·URL·freshness+write
    계약=live)로 close. → **LIVE-01 후속 OPEN 7건 전부 종결**.
- **직전 실행**: principal 경계 smoke 13건 PASS와 #392 close. public-key C2는 `T-VN-H19`까지
  미검증이므로 T-ADM-C6c/T-VN-03 전체 완료는 보류한다. T-VN-H06은 완료.

## 2026-07-27 (claude, Codex 정정) — principal 경계 부분 실증 + #392 종결

**Lane A 다음 작업**: `T-VN-H12` live 실증·`T-VN-H16` 이슈 재검증과 함께 `T-VN-H19`의
public-key C2 양성 runtime 실증을 진행한다. tasks.md 인덱스가 정본이다.

- **부분 실증**: n150 production에서 실행한 13건은 모두 PASS했다. 배포=**map c8ed6164 /
  pinvi 6a035695**(둘 다 healthy, production) —
  curated(C1 401·C3/C4 200·C4n 401) · ops 6(O1/O2 401·O3/O6 403·O4/O5 200) · MOIS(M1 404) ·
  PinVi #392(P-R1 ops:read 200·P-R2 no-token 401).
- **접근**: 배포 전 정적 감사 워크플로우(`tvn03-c6c-readiness-audit`, 6차원 병렬+적대 반증) →
  go-with-caveats → credential-safe smoke(값 비출력, status만) → #392 실증.
- **C2(public-key 200)**: DB lookup·hash compare 양성 runtime 분기는 미검증이다. C1/C3/C4와 unit test는
  서로 다른 auth branch라 등가 증거가 아니며, `T-VN-H19` 전까지 T-VN-03/C6c 전체 완료를 보류한다.
- **문서 모순 해소**: 배포 image rev label이 `c8ed6164`임을 실측(incident md의 `b0c95672`는 조상·
  docs-only 차이라 런타임 동일). 증거: reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md.
- **완료 범위**: PinVi issue #392 observation-read principal 종결.

## 2026-07-27 (claude) — 🎯 T-VN-H06 완결: keyset cursor 전환 backend #813 + e2e 검증 #852

**다음 한 작업**: Lane A **`T-ADM-C6c` + `T-VN-03`** — pinvi head(#408 포함, 현 배포 6a035695로
이미 반영) principal 경계 smoke(curated 4 GET·ops 6 GET·MOIS 404)를 n150 production에서 실증하고
PinVi #392 close. (map=c8ed6164/pinvi=6a035695 정식 전진 상태 그대로 사용.)

- **완료(이번 세션)**: `T-VN-H06`(admin 목록 keyset+fingerprint cursor 전환). backend #813(merge
  `9d29606e`, 2차 리뷰 P3 반영·pytest integration green) + e2e 검증 #852(merge `3ce99d75`).
- **e2e 검증**: dedup/enrichment mocked Playwright 14 fail → spec-only 수정으로 **24 GREEN**.
  근인 전부 spec drift(client 무변경): reviewed_by 과다기대 제거 · MultiFilterCombobox Enter 커밋 ·
  deferred provider poll. 상세는 tasks-done.md / journal.md 2026-07-27.
- **검증 환경 주의**: 이 cursor e2e는 mocked·CI 미실행이라 CLAUDE.md 정본 Windows Playwright로 확인.
  task 노트의 "n150 Linux" 편차는 mocked·OS-agnostic이라 채택(tasks-done.md에 명시).
- **머지 게이트**: #851(T-VN-43)·#813 선행 머지 확인 후 #852 CI CLEAN → squash 머지.

## 2026-07-27 (codex) — T-VN-43 구현·실데이터 파괴적 live 검증 완료

**다음 한 작업**: T-VN-43 PR의 CI green·실제 GitHub approval·머지를 완료한 뒤 Lane B b0의
`T-VN-44`(admin frontend full ESLint baseline green)를 진행한다.

- clean `npm ci` 기준 16건(low 2, moderate 7, high 7)을 0건으로 내렸다. Next 16.2.12와
  PostCSS 8.5.23·Sharp 0.35.3을 고정하고 CI에 high gate를 추가했다.
- shadcn CLI/MCP와 사용하지 않던 React Hook Form/resolver/Zod를 제거했다. generated UI source가 쓰는
  Tailwind variant 4개만 프로젝트 CSS가 직접 소유하며, lock graph는 약 1,100 package에서 742 package로
  축소됐다.
- exact npm 10.9.4는 Sharp WASM fallback optional 6개를 `extraneous`로 보고하면서 exit 0을 반환한다.
  T-VN-43은 JSON `problems`의 exact package/version allowlist 밖 문제를 fail-close하고 실제 native
  optimizer를 검증한다. upstream/npm 근인을 없애 allowlist 자체를 제거하는 작업은 T-VN-46으로 유지한다.
- 취약 legacy Next ESLint preset을 제거하고 ESLint 10·typescript-eslint 8.65·React Hooks·React-X/
  React-DOM·Next·import-x·jsx-a11y-x flat config를 직접 구성했다. effective config gate가 canonical
  React Hooks 활성·중복 React-X analyzer 비활성·missing-key/anonymous-export severity를 실제로 계산한다.
  강화된 T-VN-44 기준선은 1 error/30 warnings다.
- `openapi-typescript`의 Redocly 1 제약은 안전한 js-yaml/minimatch로 override하고, 바뀐 minimatch
  API 한 곳을 exact version/content 검사 후 적용하는 fail-close postinstall로 보정한다. frontend와
  C7 Docker context 모두 patch·tree-integrity·Sharp smoke script를 install 전에 포함한다.
- frontend Node 22.23.1/npm 10.9.4를 exact pin하고 C7 browser/client Playwright를 1.60.0으로 맞췄다.
  Next private optimizer를 실제 호출하는 2×2 SVG→WebP smoke로 Sharp ABI까지 검증한다.
- React Doctor 0.9.1 full scan은 262개 파일에서 오류 9건·경고 69건이며 T-VN-47에서 근인으로 해소한다.
- 전체 mocked Playwright 진단은 기존 accessible-name/actor/API route drift 52건을 165번째 spec까지
  재현해 중단했다. T-VN-48로 분리했고, T-VN-43의 CSS·폼·지도·업로드 대표 mocked spec은
  격리 UI/C7 container·workers=1에서 24/24 통과했다.
- #840 이후 Claude Code PR #841~#850(닫힌 PR 포함) 전문 감사 1명과 독립 적대 리뷰어 2명이
  최종 exact diff를 재검토했다. #849/#850 재감사에서 완료 task의 열린 백로그 중복·H12 인덱스/owner
  drift·완료 LIVE-01 future tracker(P3)와 C6c의 이미 끝난 배포/pair 잔여 표기(P2)를 찾아 바로잡았다.
  실제 OPEN 7건은 Lane A `T-VN-H16`으로 분리했고, 반영 뒤 P0~P3 finding 0건을 확인했다.
- 전체 Python gate는 2,355 tests·Ruff·strict mypy·4개 import contract가 모두 통과했다. frontend는
  clean install·audit 0·tree/effective-config/Sharp smoke·OpenAPI/admin/user drift·type-check·227 Vitest·
  production build를 통과했고, exact Docker image에서 대표 mocked E2E 24/24가 통과했다.
- PR #847 R1~R4에 따라 branch API/Dagster/DB migration 없이 UI만 host loopback `12715`에 격리했다.
  실제 관리자 UI로 공식 CSV 5종을 preview·commit하는 파괴적 live E2E 4/4가 통과했고 REST·관리자
  상세·지도에서 19 collections·486 memberships를 확인했다. 전용 UI/browser container 제거 뒤
  C7 active process/lock/journal/runtime 잔여는 모두 0, 운영 UI/API는 healthy다.

## 2026-07-27 (claude) — 🎯 T-VN-LIVE-01 완료: live acceptance lane n150 PASSED @ c8ed6164

**다음 한 작업**: **Lane A `T-ADM-C6c` + `T-VN-03`** — pinvi head(#408 포함, 현 배포는 6a035695로
이미 반영됨) principal 경계 smoke(curated 4 GET·ops 6 GET·MOIS 404) n150 실증 + PinVi #392 close.
그 다음 `T-VN-H06`(#813 merge `9d29606e` 반영 완료, n150 Linux cursor runtime 검증 잔여).

- **완료(이번 세션)**: `T-VN-LIVE-01`(+04A #741·58 #785·15) targeted live acceptance lane을 n150
  production(map=c8ed6164/pinvi=6a035695)에서 파괴적 실행 → **PASSED**(rc=0, phase=passed,
  recovery_attempt=0, leftover 0). #741·#785 closed, tasks-done 이관.
- **규명·수정 연쇄**: helper host-network(#842)·map nav/zoom-contract(#843)·Codex PR 리뷰
  DSN/signal(#844)·검색 pg_trgm 격리(#845)·kind=place 격리(#848). 적대 리뷰어 2명 반영, P2는
  T-VN-H12(run-unique 좌표)로 추적.
- **인시던트+복구**: Codex live 컨테이너가 공유 prod pinvi DB를 0040으로 migration → held e60d1711
  기동 불가 → manifest trap. pinvi를 6a035695(#408)로 재빌드 + map-api base-compose 재생성 +
  deploy 가드 임시 우회(성공 후 원복)로 c8ed6164/6a035695 정식 전진. 재발방지 규율 R1~R4(#847).
- **백로그·이슈 정리**: T-VN-42(#846) done, b4 신설(H12/H13#699/H14#700/H15#805), 이슈 종결 추적(#849);
  11개 이슈에 백로그 코멘트. open PR: #833 머지·#831/#811 닫음.

## 2026-07-26 (codex) — T-VN-42 구현·실데이터 파괴적 live 검증 완료

**다음 한 작업**: T-VN-42의 최종 2인 적대 리뷰와 CI green·실제 GitHub approval·머지를 끝낸 뒤
Lane B b0의 `T-VN-43`(admin frontend npm 보안 취약점 0-high)로 진행한다.

- 두 지도 상세 패널의 MapLibre control-safe 여백과 실제 bounding-box 비겹침 assertion을 공용화하고,
  live 전역 reduced-motion 우회를 제거해 실제 zoom click·motion 종료를 검증했다.
- admin in-bounds query key와 HTTP identity를 원본 bbox·정수 zoom·items/clusters mode로 일치시키고,
  UI/server cluster 경계를 공용 함수로 단일화했다.
- #840 이후 Claude Code PR #841~#845 전문 감사 결과를 반영해 BLOCKED/result v3 exact execution
  identity와 recovery pre-mutation fail-close, clear 신호 경쟁 방지를 구현했다.
- n150 실제 데이터에서 feature panel↔scale 20px 비겹침을 확인했고 공식 CSV 5종을 preview·commit한
  파괴적 live UI E2E가 4/4 통과했다(19 collections·486 memberships·지도 상세 재검증).
- 작업 중 발견한 `T-VN-43`(npm audit), `T-VN-44`(full ESLint), `T-VN-45`(live endpoint/cache drift)를
  백로그에 추가했다.

## 2026-07-26 (claude) — 백로그 전면 감사 + A/B lane 재분배 (codex 7~8 : claude 2~3)

**다음 한 작업**: **Lane A `T-VN-LIVE-01`** — merged targeted live acceptance lane(#792)을 n150
production에 파괴적 실행(WSL SSH, 실데이터), cleanup/audit/evidence 0/완결 증명 →
`T-VN-04A`(#741)·`T-VN-58`(#785)·`T-VN-15` live 인수 일괄 종결 + issue #741/#785 close.

- **감사(11-agent 전수)**: 열린 task 전부를 실코드·GitHub·PinVi/manager 상태와 대조. 완료 확정
  이관: SYNC-02(#790)·T-VN-57(#784)·59(#786)·H02R(#796 close 2026-07-26)·H03R(#798)·H08(#799)·
  H09(#797)·51~56(#816 rebase 후 머지) + SCHEDCHURN·POICAUSAL → `tasks-done.md` 2026-07-26 섹션.
- **C6c 확인(사용자 지시)**: 코드 cutover는 완료(#387/#393, legacy 경로 0건)나 **미완** —
  배포 pinvi(e60d1711)가 hardening #408 미포함, issue #392 open, principal 경계 smoke 미실행
  (C7 read-auth는 admin-BFF만 커버). 잔여를 `T-VN-03`과 통합해 Lane A에 배정.
- **Lane 재분배(2026-07-26, codex:claude≈7:3)**: **A(Claude)** = LIVE-01 실행·종결 →
  C6c/T-VN-03 principal smoke·종결 → H06(#813) 2차 리뷰·머지·검증. **B(codex)** = b0 선행
  하드닝(42→43→44→45) · b1 PinVi 결합(11→12→16→41; 08은 PinVi #409로 완료) · b2 H07
  완결(#814+pinvi#403 머지,
  H07C #812 manifest v5, H07D #815) · b3 Wave 2 구조 전환(31→…→40→39) · 보류 T-101.
  규율: A는 적대 리뷰어 2명+파괴적 live E2E,
  설계 우수성·확장성·성능 우선(prod 보전·호환성·최소수정 비제약 — 서비스 전).

## 2026-07-26 (claude) — 🎯 C7 COMPLETE: 공식 6-spec prod 게이트 full GREEN @ d5693269

**다음 한 작업**: **T-VN 트랙** — `T-VN-SYNC-02`(integration/t-vn → main 최종 합류) 등, C7 종결로 unblock.

- **C7 완결**: poi-cache `@c7-causal` 마지막 blocker까지 수정·머지(#839, main `d5693269`) 후 **재-cut(deploy
  e22b751e→d5693269 + rebind: executor 재빌드·attestation 재생성·self-verify PASS)** → 공식 게이트
  (`run-c7-prod-live-e2e.sh`, KST :41 window) **full GREEN**: `status=0 orchestrator_verified=True`, 6 spec 전부
  passed — kma-active 2/2 · kma-cap 2/2 · kma-empty 2/2 · read-auth 7/7 · schedule-write 2/2 ·
  **poi-cache-causal 2/2**. no BLOCKED. prod 클린(active e2e target 0, weather 복원, 5 runtime healthy @ d5693269).
- **poi-cache 근인(참고)**: backend 아님 — **test-side 2중 버그**: (1) `POI_HEADING` 영문 상수가 개편
  B(`d8818994`) 한국어 h1 통일("POI 캐시 대상") 이후 stale → `gotoPoiTargets` 15s timeout; (2)
  `expectCausalDatasetProjectionUpdate`의 `page.evaluate`가 `connectionId` destructure 누락 →
  `ReferenceError`(cbe133c2 이래 상시 실패, heading 버그가 가림). projection-lag 가설은 오진. 상세
  `docs/journal.md` 2026-07-26.

## 2026-07-26 (claude) — C7 SCHEDCHURN 완료: schedule-write 재편입, gate 5-spec 복원

**다음 한 작업**: T-VN 트랙 — `T-VN-SYNC-02`(integration/t-vn → main 최종 합류) 등, C7 종결로 unblock.

- **완료(이번 세션)**: `T-ADM-C7-SCHEDCHURN` 근인 확정·수정. 직전 세션의 "app-side render churn" 진단은 **오진**.
  진짜 근인 = cron 저장 응답 유실 후 frozen-idempotency 복구가 필요해질 때 cron 수정 dialog(Base UI)가 열린 채
  남아 페이지 전체가 inert가 되어 모든 schedule 컨트롤이 접근 불가가 되던 것. fix=`schedule-panel.tsx`(복구 필요
  순간 dialog close) + spec 하드닝(canReset·robustClick·settle-gate·시작 confirm alertdialog locator). 적대 리뷰어
  2명 반영 → **91b822e2(main+fix)** prod 재배포(rollback-guarded, 4 runtime healthy) 후 verbose-iterate 재검증
  **GREEN(2 passed, 37s)** → `scripts/run-c7-prod-live-e2e.sh` SPECS에 schedule-write 재편입(**C7 gate 5-spec**).
  weather 스케줄 매 run 정확 복원. 상세 `docs/journal.md` 2026-07-26.
- **C6c**: PinVi ops-caller cutover는 이미 완료·머지됨(#387/#393), 적대 리뷰어 2명 재검증(correct + fail-safe).
  잔여는 operational activation(compatible-pair manifest-v4 exact Map+PinVi head + N150 live E2E) + #392 bookkeeping뿐.

## 2026-07-26 (claude) — C7 close: schedule-write descope + #837/#74 머지; 다음 = SchedCHURN 후속

**다음 한 작업**: `T-ADM-C7-SCHEDCHURN` — admin `SchedulePanel`의 cron override 반영 후 ~90s render/refetch
churn 규명·수정(`schedule-panel.tsx`) + UI 재빌드/재배포 → schedule-write를 다시 blocking gate에 편입.
spec 측 6-layer fix 재적용 지침은 `docs/journal.md` 2026-07-26.

- **완료(이번 세션)**: C7 gate를 **4-spec**(read-auth·kma-active/empty/cap-write)으로 확정, schedule-write
  descope(`scripts/run-c7-prod-live-e2e.sh` SPECS). test/deploy 근인 6개 규명·수정(canReset·getSchedule·reload
  timeout·frozen-UI dispatchEvent·robustClick·90s timeout); getSchedule+timeout은 **#74 배포됨(b5375a52 prod)**.
  prod 부수효과 2건(uncertain idempotency claim, KMA hourly cron leftover override→비활성) 복구(cron=20, RUNNING).
- **잔여 = app-side render churn**(deterministic app 버그, test로 우회 불가). fresh 환경 재확인 권장(22회 재현이
  dagster DB bloat로 reload/getSchedule을 느리게 했을 가능성).
- **머지**: #837(map, gate descope) + #74(docker-manager, getSchedule public url + reload timeout).
