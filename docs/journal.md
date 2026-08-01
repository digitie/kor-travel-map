# journal.md — 작업 일지 (역시간순)

가장 위가 가장 최근. 새 엔트리는 위에 append.

## 과거 기록 아카이브

> 2026-07-26 **전면 감사**(현행 백로그 구조 성립) 이전 기록은 아래로 분리했다.
> 검색은 `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [`journal-2026-07a.md`](archive/journal-2026-07a.md) | 2026-07-13 ~ 2026-07-24 | 115건 | 219 KB |
| [`journal-2026-07b.md`](archive/journal-2026-07b.md) | 2026-07-01 ~ 2026-07-12 | 28건 | 45 KB |
| [`journal-2026-06a.md`](archive/journal-2026-06a.md) | 2026-06-10 ~ 2026-06-30 | 172건 | 219 KB |
| [`journal-2026-06b.md`](archive/journal-2026-06b.md) | 2026-06-02 ~ 2026-06-10 | 179건 | 220 KB |
| [`journal-2026-06c.md`](archive/journal-2026-06c.md) | 2026-06-01 ~ 2026-06-02 | 36건 | 53 KB |
| [`journal-2026-05a.md`](archive/journal-2026-05a.md) | 2026-05-24 ~ 2026-05-31 | 90건 | 218 KB |
| [`journal-2026-05b.md`](archive/journal-2026-05b.md) | 2026-05-24 ~ 2026-05-24 | 3건 | 7 KB |

## 2026-08-01 — H35 게이트 ① 실증, 그리고 내가 정한 게이트 값이 틀렸음을 발견

- 격리 clone에서 **실제 import 경로**를 태워 게이트를 재현했다(HTTP/인증만 제외):
  배포 전 **3,265** → 마이그레이션 직후 **3,043**(-222) → CSV 재import 후 **3,265**(±0).
  CSV 222행 전량 채택(미채택 0), `csv_explicit_feature_id` decision 222건 생성.
- **게이트 값 정정.** 1차 실행이 3,265로 나와 내가 문서에 박은 기대값 3,266에 1
  모자랐다. 추적하니 그 1건은 `[빵이네] 강원도여행정보`(`selection_origin=admin`,
  **`item_status='rejected'`**)였고, 공개 목록 술어는 `i.status = 'included'`를
  요구한다(`curation_repo.py:589`) — **애초에 공개 표면에 없던 항목**이다.
- 즉 **3,266은 "링크 수"이지 "공개 노출 수"가 아니다.** 링크 수를 게이트로 쓰면
  정상 배포에서도 FAIL이 뜬다. 게이트를 공개 목록과 같은 술어(`status='included'` +
  collection public/published + theme public + trusted decision)로 바꿨다.
- 같은 이유로 **공백은 223이 아니라 222**다. 내 공백 측정 쿼리가 `status <> 'archived'`만
  걸러 `rejected`를 포함시킨 오류였다.
- 교훈: 코드 경로로 "복구된다"까지는 맞게 확정했지만(222행 전량 채택으로 확인됨),
  **그 결과를 판정할 게이트 값 자체를 실행 없이 정한 것이 오류였다.**

## 2026-08-01 — #918·#919 머지, H35 배포 절차 확정

- 두 PR 모두 8/8 CI green으로 머지(`origin/main` = `e1afb1cf`). `0073`(H40) +
  `0074`(H41)가 main에 있다.
- 격리 restore clone(`0064~0074`)에서 재측정: trusted **3,266 → 3,043**.
  (~~공백 223건~~ → **정정: 공개 공백은 222건.** 위 게이트 실증 항목 참조.)
  H41 FK 4개 CASCADE, item PK 재작성 성공 확인.
- **복원 스크립트 자체의 결함을 먼저 잡았다** — `postgis/postgis` 베이스 이미지가
  초기화 때 postgis류 extension을 `public`에 깔아 두는 탓에, 덤프의
  `CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA x_extension`이 **조용히 no-op**
  되고 geometry 컬럼을 쓰는 테이블(`feature.features` 등)이 통째로 안 만들어졌다.
  복원 전에 그 extension들을 먼저 지우도록 고쳐 `feature.features` 1,030,661행 복원 확인.
  (`--clean --if-exists`는 오히려 topology 스키마 이중 생성으로 죽어서 쓰지 않는다.)
- **223건 복구 경로를 추론에서 확정으로 바꿨다.** #907/#910이 자동 링크를 조여서
  재import가 안 붙을 가능성이 있었는데, `_RESOLVE_FEATURES_BATCH_SQL`의 첫 UNION 분기가
  명시 `feature_id`로 정확히 1행을 내고 `_adopted_match`가 그것만 채택한다 — 조인 것은
  `address_hint` 단독 링크이고 명시 경로는 그대로다.
- **소요 시간 수치 2개를 모두 폐기했다.** 1,754초(이전)와 79.9초(이번) 둘 다 dagster가
  도는 상태에서 쟀는데 실제 배포는 dagster를 멈추고 돌린다 — 조건이 다르다. B′는
  시간제한 없는 일회성 컨테이너를 쓰므로 정확한 초수가 애초에 필요 없다.
- n150 재측정은 **중단**했다. 4코어에 load 11.6/iowait 44.7%였고, 조사해 보니 고장이
  아니라 T-VN-41 lane이 Playwright buildx 빌드 + 라이브 스택 2벌을 **지금 쓰고 있는**
  것이었다(컨테이너 9개, `RestartCount=0`, 1분 전 재생성됨). 정리 불가라 판단하고
  내 프로세스·컨테이너만 회수했다.
- 앞서 "swap 고갈은 위험 신호"라고 한 것은 **정정한다** — sudo로도 VmSwap을 잡은
  프로세스가 없고 `available` 7.9Gi다. 유휴 스왑이지 메모리 압박이 아니다.

## 2026-08-01 — T-VN-H40 `0073` 구현: source-rule link provenance

- `0072`가 공개 표면 fail-close를 넣으며 기존 link을 전부 `legacy_unattributed`로
  이관해, 격리 restore clone 실측에서 공개 노출 가능 link이 **3,266 → 0**이 됐다.
  concierge projection 3,044건은 근거가 실재하므로(`source_record_key` 100% 도달)
  `0073`이 `match_basis`에 **`source_rule`** 을 더하고 검증 통과분만 승격한다.
- `forward_recovery` 재사용은 하지 않았다 — merge 전용 의미라 빌려 쓰면 왜곡이다.
- 트리거는 `curated_features`가 아니라 **`curation_items`** 에 달았다.
  `sync_curated_feature_collection()`은 link 생성 지점이 둘이고 merge/detach 불변식이
  얽힌 800줄이라, 불변식이 사는 자리에 거는 편이 두 지점과 미래 writer를 함께 덮는다.
- **승인 근거 판정이 두 곳에 다른 모양이었다** — 공개 표면 denylist, merge whitelist.
  값이 늘 때 whitelist만 뒤처지면 공개 표면이 노출하는 link을 merge가 끊는다.
  `infra/curation_link_basis.py` 한 곳으로 모으고 양쪽 whitelist로 맞췄다.
- **읽기로 낸 결론 2건이 실행으로 뒤집혔다.** `0065`의 함수 정의가 파일에 두 번
  나오는데 downgrade 본문을 최신으로 읽어, "트리거가 item을 DELETE 후 INSERT하므로
  RESTRICT로 writer가 죽고 decision이 누적된다"고 봤다. 컨테이너에 `0072`를 올려
  재현하니 UPDATE·DELETE 모두 정상이었다. 실제 정의는 targeted UPDATE +
  `ON CONFLICT DO NOTHING`이다. 누적 축은 그래도 회귀 테스트로 고정했다.
- 게이트: unit **1821 passed**, 관련 integration **91 passed**,
  `ruff`/`mypy --strict`(123 files)/`lint-imports`(4 kept). 새 통합 테스트 6건은
  **변이 2회**로 falsifiability를 확인했다 — 검증 술어를 빼면 fail-close 2건,
  재진입 가드를 빼면 누적·멱등 3건이 죽는다.
- `test_alembic_upgrade.py`가 head revision을 리터럴로 박아 마이그레이션 추가마다
  깨졌다. ScriptDirectory에서 계산하도록 바꿨다.

## 2026-07-31 (codex) — PostGIS-only workflow와 stale T-VN-12 이관

- `postgis-only.yml`을 `workflow_dispatch` 전용으로 추가했다. 선택한 ref, Python 3.13,
  editable 메인/API/Dagster, Docker testcontainers와 `--no-cov` integration만 소유한다.
- 정규 `ci.yml`은 손대지 않아 Python matrix·coverage 합산·fixture replay가 계속 필수다.
- PR #906의 merged 상태, merge `01aa335f`, 최종 head `b2169512`, 단일 리뷰 최종
  P0/P1/P2 0건과 8개 green check를 근거로 T-VN-12A/B/C/D의 stale open 상태를 완료
  이관했다. 다른 열린 task의 checkbox와 순서는 변경하지 않았다.
- pinned `actionlint 1.7.7`과 `git diff --check`가 통과했다. 사용자 지시에 따라 이
  CI/task 문서 PR은 생성 후 적대 리뷰와 CI 결과를 기다리지 않고 바로 병합한다.

## 2026-07-31 (codex) — T-VN-H31R #909 curation provenance 완결

- 주소 후보를 구조화 field·Unicode/literal hierarchy·versioned alias로 제한하고
  `address_hint` 단독 자동 링크를 제거했다. 등대 105행 sidecar와 manifest를 결박했다.
- migration `0072_curation_provenance`로 import batch/row와 link decision을 append-only
  정규화했다. DB immutable trigger, same-item composite FK, exact current pointer와 legacy
  fail-close를 강제했다.
- official 등대 sidecar를 실제 multipart import와 durable row provenance에 결박하고
  batch/current-row 조회, stable cursor link audit를 추가했다.
- Feature merge는 non-legacy accepted link만 재승인한다. duplicate loser source가 이기면
  survivor-owned merge row/decision을 append하고 loser는 revocation+archive로 보존한다.
- 다중 component inactive history+active current는 external item별 canonical
  survivor/provider/operator winner로 결정하고, legacy 정본 동기화 뒤 loser history를
  master로 옮겨 projection/current pointer를 보존한다.
- 단일 적대 리뷰의 최초 P1 2건·P2 3건·P3 1건과 재리뷰 P2 1건을 모두 닫았다. exact
  `e69f8926` 최종 판정은 P0/P1/P2/P3 0건이다. 관련 195건, merge 29건, legacy clean DB
  5/5와 admin frontend 286건, 정적/OpenAPI/보안 gate가 통과했다.

## 2026-07-31 (codex) — PR #908 #911~#914 적대 리뷰 보강

- #911: provider 적재 성공과 absence 증거를 분리했다. source 전체 관측·finding 전량 durable
  기록을 typed receipt가 증명할 때만 close하며 empty/partial/drop/persistence 실패는
  fail-close한다.
- #912: migration `0071_integrity_observations`로 provider/dataset scope fence, external run
  generation/receipt, run별 immutable dedupe-key observation set을 추가했다. 최신 authoritative
  generation만 sweep하고 current/newer observation을 보호한다. ADR-080과 data model/schema
  카탈로그를 갱신했다.
- #913: resolved finding purge를 consistency maintenance job과 daily schedule에 실제로
  연결하고 retention override·metadata·retry를 검증했다.
- #914: linked name과 exact-name candidate ID를 현재 Feature에 결박했다. `approved|public`
  scope를 분리하고 public repository 정본을 재사용하며, 감사 전체를 read-only
  repeatable-read transaction 하나에서 실행해 snapshot identity를 보고한다.
- 검증: unit+Dagster **2,315 passed**(optional MOIS 1 skipped), relevant PostgreSQL
  integration **43 passed**. public audit와 generation 교차·동시성·migration 왕복은 실제
  migrated PostgreSQL에서 실행했다. ruff 전체, strict mypy(core 120/Dagster 23 files),
  import-linter도 통과했다.

## 2026-07-31 (codex) — T-VN-12 외부 효과 복구·consumer cutover checkpoint

- static inventory가 55개 write route의 `db_only|external|non_retryable` 분류와 operation
  등록을 강제한다. 공통 actor-scoped UUID claim/result와 canonical fingerprint를 도입해
  DB-only command의 업무 변경·terminal response를 한 transaction으로 묶었다.
- offline upload create는 `uploading` reservation을 먼저 commit하고 object byte/size/
  content-type/metadata proof 뒤에만 `uploaded`와 terminal result를 확정한다. process가
  `effect_started` 뒤 종료되면 typed `NoSuchKey`만 exact PUT을 재개하고 transport ambiguity는
  pending으로 보존한다. load는 deterministic Dagster run ID를 사용한다. load/delete 모두
  현재 row precondition보다 claim/replay/conflict를 먼저 확정하며, delete transport ambiguity는
  row를 지우거나 terminal 성공으로 굳히지 않고 같은 key의 exact `DeleteObject` 재시도로 복구한다.
- backup/restore/swap/delete execution state와 create-once filesystem marker를 추가했다.
  marker writer는 nofollow/exclusive temp, file+dir fsync, `renameat2(RENAME_NOREPLACE)`,
  owner/mode/nlink 검증과 effect-specific output digest를 사용한다. foreign marker·symlink/
  hardlink는 거부한다.
- 네 backup operation은 같은 `maintenance:backup-restore` session lock을
  `pg_try_advisory_lock`으로 공유하고 host effect부터 proof·DB result commit까지 보유한다.
  busy는 409, delete first-missing은 claim rollback 404, restore partial target은 fail-close,
  swap은 canonical project child의 planned/applied env digest를 분리한다.
- frontend는 body hash를 command slot으로 쓰지 않는다. stable resource slot 또는 create
  draft slot에 UUID+submission fingerprint를 동결하고, 불명확한 결과 뒤 다른 submission은
  차단하며 로그인·로그아웃/401 actor 경계에서 admin slot을 제거한다.
- 검증: ruff 전체와 strict mypy 178개 source, backend targeted 74건, 실제 PostgreSQL
  migration/ledger/maintenance-lock integration 6건, frontend lint·type-check·286건,
  OpenAPI TypeScript drift 검사가 통과했다. 전체 unit+API 첫 실행에서 찾은 typed
  `FileStoreObjectNotFoundError`의 `__all__` 기대값 1건을 수정했다. 나머지 환경 실패는
  subprocess `PATH`의 `.venv/bin`과 optional Dagster dev dependency를 보강했고, 같은 venv의
  clean 재실행에서 전체 **2,634건**이 모두 통과했다.
- 단일 적대 리뷰어가 exact `d2b42755`에서 4건을 찾아 `CHANGES REQUESTED`했다. 기존 restore
  target health를 command provenance로 오인한 P1, API connection lock이 child 수명보다 먼저
  풀릴 수 있는 P1, 다른 key의 동시 offline delete loser가 영구 pending이 되는 P2, 기존 custom
  backup artifact를 새 command output으로 채택하는 P2다.
- offline delete는 `deleting + delete_command_id` resource reservation을 claim/execution과 같은
  transaction에 넣고 owner만 최종 삭제하도록 고쳤다. 실제 두 session 경쟁에서 loser claim이
  0으로 rollback됨을 검증했다. backup/restore/swap은 wrapper가 child 전체 수명 동안 lock을
  직접 소유하며 cancellation/timeout에 process group을 완전히 회수한다. create destination은
  command/input digest reservation 뒤에만 effect를 시작하고, restore/create 모두 exact marker/
  reservation 없는 기존 산출물을 채택하지 않는다.
- 리뷰 수정 combined gate는 ruff, strict mypy 178 source, bash syntax, targeted 102건,
  PostgreSQL resource-race/ledger와 offline delete integration 9건, 전체 unit+API
  **2,642건**, frontend lint·type-check·286건, OpenAPI/type drift가 통과했다. 동일 리뷰어
  재검토와 n150 파괴적 Live는 다음 checkpoint에서 수행한다.
- 동일 리뷰어 재검토는 wrapper가 `TERM`으로 먼저 죽어 lock을 놓고 TERM 무시 descendant가
  살아남는 P1을 추가로 찾았다. wrapper가 DB session을 보유한 채 child group을
  `TERM → bounded wait → KILL → reap`하고, API도 wrapper return code와 무관하게 pipe 완료를
  기준으로 escalation하도록 수정했다. 실제 wrapper·TERM 무시 child·별도 PostgreSQL contender와
  leader 종료 뒤 pipe를 보유한 descendant 회귀 2건, 관련 focused 55건, 전체 unit+API
  **2,642건**이 통과했다.
- 세 번째 검토에서 local Docker CLI가 종료돼도 daemon container가 계속 실행되는 P1을 실제
  재현했다. 시작된 backup/restore/swap을 non-interruptible supervised effect로 재정의해
  cancellation/timeout은 bounded 반환하되 wrapper가 child에 signal을 전달하지 않고 임시
  output spool·별도 session·PostgreSQL lock을 자연 terminal까지 유지하도록 바꿨다.
- actual `docker run` TERM-ignore container가 살아 있는 동안 별도 PostgreSQL contender가
  lock을 얻지 못하고, container 종료 뒤 wrapper가 durable marker를 쓴 다음에만 lock을 얻는
  integration 회귀가 통과했다. 동일 command retry는 그 marker를 검증해 `_run_command`를
  다시 호출하지 않고 `completed`로 terminalize하며, 호출 task detach 단위 회귀까지 현재
  cancellation/timeout을 나눠 exact 4건이 green이다.
- 최종 local gate는 관련 focused 49건, PostgreSQL/Docker ledger integration 8건, 전체
  unit+API **2,644건**, ruff 전체, strict mypy(core 120/API 58/Dagster 23), import 경계,
  bash syntax, OpenAPI drift, prod redaction까지 모두 통과했다.
- 네 번째 재검토는 wrapper/local child group `SIGKILL` 뒤 PostgreSQL lock이 풀리고 marker
  없는 daemon effect를 같은 command가 다시 시작하는 P1을 실제 재현했다. DB execution에
  immutable 256-bit `effect_token`을 추가하고 API가 maintenance lock 안에서 고정 이름 global
  Docker fence를 pre-acquire·inspect한 뒤에만 phase를 전이하도록 순서를 바꿨다.
- fence는 canonical local immutable Image ID와 `--pull=never`, exact command/input/source
  revision/Image label, network none/read-only/capability drop/no-new-privileges/non-root/PID
  limit shape를 검증한다. foreign fence의 새 command는 `prepared`에 남고 host script는
  pre-acquired exact running fence 없이는 세 effect 모두 mutation하지 않는다.
- marker 없는 `effect_started` 동일 command는 외부 command를 다시 호출하지 않고 secret-free
  `409 BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED`에 exact identifier와 안전 절차를 제공한다.
  workload terminal을 자동 증명할 수 없으므로 hard crash는 외부 operator가 target/output을
  확인해 marker를 먼저 만든 뒤 exact fence를 해제하는 경계로만 복구한다.
- 현재 gate는 router 26건, fence/runbook/marker/wrapper focused 55건, 실제 Docker+PostgreSQL
  hard-crash integration 1건이 green이다. actual test는 wrapper와 local child group을
  `SIGKILL`한 뒤 orphan workload/fence 유지, PG contender 재획득, 동일/foreign retry mutation
  0건, 외부 operator proof marker 뒤 exact release를 반복 실행 가능하게 고정한다.
- marker proof와 fence 해제 사이의 crash gap은 API가 proof 확인 뒤 idempotent exact release를
  다시 수행하도록 닫았다. helper source revision은 파일 SHA-256 label이며 recovery env를 직접
  주입한 host script 재실행도 mutation 전에 exit 4로 거부한다. 최종 전체 unit+API
  **2,650건**, domain ledger integration **9건**, ruff·strict mypy·import 경계·OpenAPI/
  TypeScript drift·bash syntax·prod redaction이 모두 통과했다.
- 최종 P2 재검토에서 foreign fence 거절 전에 create reservation이 남는 순서와 stale
  `prepared` 동일 key의 0-row UPDATE/500을 확인했다. reservation을 maintenance lock 안의
  exact fence 성공 뒤·phase 전이 앞으로 옮기고, 실패 시 아직 `prepared`인 exact 자기 fence만
  정리한다. lock 획득 뒤 execution을 다시 읽어 stale 요청은 fence/UPDATE를 반복하지 않고
  기존 markerless 409 경로에 합류시켰다. 실제 reservation의 backup root 불변 unit과 migrated
  PostgreSQL stale snapshot 회귀가 green이다.

## 2026-07-31 (codex) — T-VN-16C 완료 이관·T-VN-12 단일 PR 착수

- Map #902와 PinVi #421의 실제 병합 상태를 재확인했다. sparse 다중 날짜 생산자,
  Trip당 outbound 1회 소비, owner/shared Web projection과 파괴적 Live UI가 모두
  완료됐으므로 `T-VN-16C`를 완료 이력으로 이관했다.
- 사용자 최신 지시에 따라 다음 Lane B 작업은 `T-VN-12A/B/C/D`이고 네 단계를 하나의
  PR에서 완결한다.
- 아직 없는 H22B command를 기다리는 대신 12A의 정적 write-operation registry와 CI
  완전성 검사가 미래 route도 미등록 상태로 둘 수 없게 한다. H22B는 구현되는 시점부터
  같은 actor-scoped ledger에 등록해야 하므로 종전의 선행 barrier를 제거한다.
- 이 변경은 문서 상태·순서 정리뿐이며 코드·DB·runtime에는 영향을 주지 않는다.

## 2026-07-31 (codex) — PR #732 설계 결정을 현재 문서 정본에 반영

- PR #808은 `dd965d08` 기준에서 닫힌 미병합 draft이고 현재 main보다 크게 뒤처져 있어
  재사용하지 않았다. 최신 main에서 독립 `T-VN-DOC-732` 문서 task와 PR #903을 만들었다.
- ADR-060의 Map public `key` query를 `X-Kor-Travel-Map-Api-Key` header-only로
  개정하고, geo 브라우저 query/Map backend header 계약과 구분했다.
- REST·integration 정본은 canonical ops principal, production debug unmount,
  5-state feature batch, 완료된 C6c manifest v4/C7 live와 후속 pair 활성화 순서를 현재
  OpenAPI에 맞췄다. 폐기된 `integration/t-vn`은 성능 문서와 C7 runbook에서도 제거했다.
- n150 현재 Map 4개와 PinVi API runtime이 healthy인 것을 read-only로 확인했다.
  C6c/C7 완료 이슈는 모두 closed이며 Map #819만 외부 HAProxy 운영 설정 대기로 유지한다.
- 문서 전용 변경이라 새 runtime 배포·파괴적 live·DB 변경은 수행하지 않았다.
  `git diff --check`, OpenAPI `PublicApiKey` header 정본 대조,
  `scripts/check_prod_redaction.py`와 push 전 민감값 감사를 통과했다.

## 2026-07-31 — H35를 멈춘 이유: 절차가 위험을 줄이는 대신 만들고 있었다

**prod는 손대지 않았다.** `c8ed6164` / `0063` / 5 런타임 healthy. 배포 시도 2회는 전부
fail-closed로 막혔고 그때마다 그 안전장치가 옳았다 — 1회는 자격증명 드리프트, 2회는
`origin/main`이 그 사이 전진해 감사가 새로 박은 제약을 모르고 나갈 뻔한 것을 막았다.

**절차를 만드는 데 400만 토큰을 쓰고 prod에서 바뀐 것은 없다.** 11단계 cold-fence runbook은
1,679 → 2,446줄로 자랐고 감사 2회 모두 **NO_GO**였다. 중요한 건 결함의 추이다 —
1차 BLOCKER 9건을 고쳤더니 **새로 쓴 +992줄에서 BLOCKER 5건이 났고 그중 4건이 같은 유형**
("명령이 자기 driver·자기 도구에 막힌다")이었다. 결함률이 떨어지지 않았다.
그 시점에 "절차가 위험을 줄이는가"를 물었어야 했는데 묻지 않고 계속 고쳤다.

**11단계는 사람이 요구한 게 아니라 감사 에이전트(PR #896)가 쓴 것이다.** 나는 그걸 움직일 수
없는 사양으로 취급했다. 사용자가 "지금 이 task가 필요한 이유?"라고 물었을 때야 그 전제를
검토했다 — 실측하니 #673의 457건은 소비자가 확인되지 않았고, 회복은 월 1회 스케줄이라
어차피 즉시가 아니며, prod는 정상 동작 중이었다. **급한 일이 아니었다.**

**내 실측도 불완전했다.** bridge 격리를 잰다면서 `--network bridge` 하나만 찔렀는데, 실제로는
bridge 계열 network가 4개이고 하필 내가 찌른 것에는 컨테이너가 0개였다. 그 측정을 그대로
반영한 `L2b` fence는 4개 중 1개만 막고 음성통제도 그 1개만 찔러 **"닫혔다"를 보고**한다.
내가 경계한다고 말해 온 "실패했을 때도 같은 값을 내는 게이트"를 내 측정이 만들어 냈다.

**단순 경로 B도 실측으로 막혔다.** `compose_service.py:3540`이 `--wait-timeout 120`을
하드코딩하는데 `0069` 하나만 8~18분이다. `ktdctl deploy`는 120초에 실패 판정하고
**마이그레이션이 도는 중인 컨테이너를 뜯으며 롤백을 발동한다.** 그래서 마이그레이션과 배포를
분리하는 **B′**로 확정했다 — build-only(라이브러리 seam) → 일회성 컨테이너로 마이그레이션 →
`ktdctl deploy`(이미 head라 no-op, 자동 롤백 보존).

**확보한 것**: writer-quiesced 백업(`20260730T213912Z`, app 1,168 MiB + dagster 65 MiB,
`inflight_runs=0`·`app_write_tx=0` 확인 후 채취 — 이전 dump는 fence 없이 떠서 무효),
선행 조건 실측(디스크 80.7 GiB / superuser `addr` 도달 / `archive_mode=off`로 PITR 없음),
`0069` 전수 분석(**파괴적 statement 0개, downgrade 완전 대칭 — 0064~0069 중 유일하게 완전 가역**).

`0069`에서 하나 건졌다: **새 이미지 + 0069 미적용**이면 기존 공개 엔드포인트
`GET /features/{id}/weather`가 503이 아니라 **500**을 낸다(#901이 batch 쿼리로 재배선하며
`weather_metric_series`를 hard JOIN). 정상 경로에서는 entrypoint가 upgrade 성공 뒤에만
uvicorn을 exec해 발현하지 않지만, alembic을 건너뛰고 API를 강제 기동하면 발현한다.

인수 상태는 `tasks.md`의 T-VN-H35 본문 상단 블록에 전부 적었다. 다음은 막히지 않은
`T-VN-H30C`로 넘어간다 — H30B·ledger 정규화는 `0066` 컬럼이 필요해 H35에 막혀 있다.

## 2026-07-30 (codex) — T-VN-16B landing·T-VN-16C sparse 계약 착수

- PinVi PR #420은 Web e2e fixture의 새 필수 `weather_by_feature_id` 누락과 날짜 수정
  mock의 stale `effective_date`를 실패 지점에서 고쳤다. 영향 6개 spec은 32 passed,
  1 skipped였고 새 head 전체 e2e·API·Web·mobile·aggregate CI가 green인 상태로
  `9eb95c6f`에 squash merge됐다.
- 보존 `ktm-tvn45-db`는 healthy·head `0069_weather_series_catalog`로 재사용한다. merge
  뒤 #894 이후 closed 포함 새 Claude Code PR은 없었다.
- T-VN-16C 생산자는 날짜별 실제 Feature만 보내는 sparse
  `targets[{target_at, feature_ids}]`를 사용한다. canonical target ordering과
  366 target/target별 200 ID/전체 2,000 pair를 제한한다. ID 256자, planning work
  `pair + 5 × 고유 Feature <= 2,500`, source-series work 150,000, metric 20,000,
  응답 추정 8 MiB, query 20초 예산을 추가하고 결과 초과는 부분 응답 없이 413,
  timeout은 503으로 거부한다. 여러 target의 parent·anchor·current·timeline은 한 SQL
  snapshot에서 계산한다.
- 첫 원격 checkpoint `28ea73e5`는 API/SQL/통합 계약을 담았다. 실제 변경 코드의 targeted
  API와 PostgreSQL 통합은 각각 15·11 passed였고 Ruff·strict mypy도 통과했다.
- 첫 실데이터 40 target × 5 Feature probe는 동일 card를 item마다 반복해 56,625 metric
  예산을 넘겼다. target-local `card_key`·`cards[]`로 payload를 정규화하고 source
  spatial 후보 집합을 고유 parent별 한 번만 계산하도록 바꿨다. 최종 source는 target별
  bitemporal fact 적격성으로 정해 미래 series가 과거 snapshot을 바꾸지 않는다. 자체
  series가 없는 실제 공개 Feature 5개의 200 sparse pair는 공유 card 40개,
  11,763 metric, source-series work 716, batch 5.77초로 통과했다(중간 날짜별 source
  lookup은 35.1초). 보수적 payload 추정은 6,030,012 bytes로 실제 data JSON
  4,677,305 bytes보다 1,352,707 bytes 컸다.
- admin/user OpenAPI와 두 TypeScript client 산출물을 다시 생성했고 export/type drift
  check가 모두 통과했다. 1차 적대 리뷰가 찾은 future-catalog contamination, 단건
  `source_styles`의 timeline 혼입, 무제한 workload/payload/timeout을 회귀 테스트와 위
  예산으로 보완했다.
- 최종 SQL 적대 리뷰는 source-series gate 뒤 current/timeline fact projection,
  catalog global sequential scan 부재와 timeout cleanup을 실측했다. query budget은
  transaction-local PostgreSQL `statement_timeout`을 설정하고 성공 시 이전 값을
  복원한다. 50ms probe는 0.155초에 `WeatherBatchQueryTimeoutError`로 반환했으며,
  반환 시 실행 중인 orphan query 0, caller rollback 0.001초, 같은 session 재사용과
  pool 종료 오류 없음까지 확인해 P0/P1/P2 모두 0으로 종결했다.
- 최종 계약 적대 리뷰는 단건 weather GET의 257자 Feature ID가 repository `ValueError`로
  늦게 거부돼 500이 되는 P2를 찾았다. path를 1~256자로 먼저 검증해 422로 고정하고
  admin/user OpenAPI와 두 TypeScript 산출물을 다시 생성했다. 실패 지점 재검토 뒤 두
  리뷰어 모두 P0/P1/P2 0으로 종결했다.
- 최종 SQL 확정 뒤 파괴적 API Live는 보존 clone `ktm-tvn45-db`의 기존
  `0069_weather_series_catalog`를 그대로 재사용했다. sparse target 2개 `found`,
  잘못된 service token 401, planning-work 초과 422, fixture `active→hidden` 뒤
  `retired`를 확인했다. owned weather/price/series fixture cleanup과 audit는 모두 잔여
  0건, API error log도 0건이었다. 첫 credential-key 탐색, `psql -c` 변수 치환,
  재검증 heredoc의 `docker exec -i` 누락과 SIGTERM `wait` 143 처리는 seed 전 또는 trap
  cleanup 뒤 각각 실패 지점부터 재개했다. 새 clone·checkpoint·migration rollback은
  만들지 않았다.

## 2026-07-30 (codex) — T-VN-16A set-based weather snapshot

- service-token 전용 `POST /v1/features/weather/batch`는 중복 없는 ID 1~200개를 한
  set-based statement로 읽고 입력 순서를 보존한다. parent 존재와 weather 없음은
  `retired`/`no_data`로 분리하며 단건 endpoint도 같은 판정을 재사용한다.
- current는 target predecessor이면서 known-at cutoff를 만족하고 range가 끝나지 않은 값이다.
  24시간 timeline과 metric의 provider/domain·valid/effective 시각을 함께 반환한다.
- 30M fact의 열린 physical series를 매번 `DISTINCT`하지 않도록
  `weather_metric_series` registry+trigger를 추가했다. series exact-prefix effective
  index와 canonical weather-only partial GiST로 단건 17.8ms, 200건 1.27s, fact Seq Scan
  0을 실데이터 clone에서 확인했다.
- 첫 적대 리뷰는 GET asof known-at, 빈/중복 ID, range 시각 손실, overflow, global
  decorrelation, nullable forecast issue, 만료 range, provider/domain 동률, 대형 index
  이중 build를 찾았다. query/contract/migration을 고친 뒤 후반 DDL 실패 재시도에서 valid
  2.283GB index를 다시 만드는 P2도 relfilenode 보존 회귀로 닫았다. 큰 delta 최종 리뷰
  2명은 P0/P1/P2 모두 0이다.
- 파괴적 Live 첫 seed는 새 registry FK가 helper 허용 목록에 없어 transaction rollback됐다.
  처음부터 반복하지 않고 해당 seed 지점에서 series exact fingerprint, parent lock, 동적 FK
  count를 추가했다. main·recovery 재실행은 모두 통과했고 Feature/change request/weather/
  price/series/auth residue는 0이다.
- 새 clone·dump·checkpoint를 만들거나 Alembic downgrade하지 않았다.
  `ktm-tvn45-db`는 healthy, head `0069_weather_series_catalog`로 다음 DB task에 재사용한다.

## 2026-07-30 (codex) — T-VN-H39 schedule pending barrier

- schedule command route가 body를 기록한 뒤 테스트 소유 promise에서 응답을 보류한다.
  request 도달을 먼저 단언하고 `finally`에서 release하므로 fixed delay와 assertion 실패
  hang이 없다.
- pending의 사유·즉시 실행·시작/중지·기본값 복귀·cron control 5개와 release 뒤 동일
  5개의 enabled 복원을 한 helper로 대칭 검증한다. 적대 리뷰어 1명이 cron/stop만 복원
  확인하던 P2를 찾아 보강했다.
- 격리 21715 실패 spec setup 포함 **2/2**, frontend **278 passed**, TypeScript·ESLint
  green. exact production image D workers=8 **276/276**, manifest 일치·child exit 0·
  reporter gate true, owned container/network/image 0건이다.
- 최초 shared 12705 실행은 빈 auth state로 로그인 화면에 머문 환경 실패였다. 독립
  frontend/session으로 실패 지점부터 재개하고 mocked screenshot/result/report 복제본과
  Agent B worktree의 orphan Next dev를 정리했다.
- DB는 사용하지 않았다. 보존 `ktm-tvn45-db`는 healthy,
  `0068_integrity_last_seen`라 다음 DB 관련 task에서 재사용한다.

## 2026-07-30 (codex) — T-VN-H38 failure fingerprint 전수 검증

- expected deterministic failure와 flaky의 모든 non-passed retry, result/step error와 중첩
  `TestError.cause`를 개별 cause/stage/status로 검증한다. passed-only, skipped, interrupted와
  빈 오류 증거는 fail-closed한다.
- 실제 Playwright 1.60의 `timedOut`은 generic envelope와 locator error를 함께 만든다. ANSI
  제어문자를 제거한 exact envelope, 같은 timeout 값, hook strict descendant result leaf를
  모두 만족할 때만 wrapper를 제외한다. test-body timeout도 같은 timeout result leaf를
  요구한다.
- result에 직접 매칭된 parent와 result에 없는 step-only parent를 모두 own stage로 검사한다.
  Playwright 1.60에서는 boxed propagation과 boxed 내부의 독립 재투척 metadata가 같으므로,
  descendant stage 차용·동일 text 중복 제거를 금지해 모호한 parent를 fail-closed한다.
- redacted mismatch에는 retry·실제 result error index·cause depth와 status·category·source
  위치만 남기고 error text와 실제 입력값이 포함될 수 있는 `TestStep.title`은 제거했다.
- 검증: 합성 회귀 **28 passed**, frontend 전체 **278 passed**, TypeScript·ESLint green.
  exact production image D workers=4 **276/276**, manifest 일치·child exit 0·reporter gate
  true, owned container/network/image 0건이다. DB는 사용하지 않았다.
- workers=8에서 기존 schedule pending test의 600ms 지연이 먼저 끝난 275/276을 재현했다.
  단순 timeout 증가 없이 명시적 response barrier로 바꾸는 `T-VN-H39`를 다음 task로
  등록했다.

## 2026-07-30 (codex) — T-VN-H37 Mocked checkpoint 종료·고병렬 경합 해소

- reporter report schema를 3으로 올리고 `originalStatus`와 최종 `gatePassed`를 함께 쓴다.
  runner는 child exit status/signal, reporter gate, worktree/frontend/network postcondition,
  cleanup failure를 구조화된 redacted outcome으로 합성한다.
- "276 passed + manifest 일치 + child nonzero"를 합성 회귀로 재현해
  `playwright_child_nonzero` exit 1로 고정했다. postcondition·cleanup·spawn 실패는 exit 2로
  우선해 실제 인프라 실패를 통과시키지 않는다.
- 이전 cleanup은 Docker remove client가 1초 안에 끝나지 않으면 daemon이 직후 실제로
  제거해도 실패했다. remove 종료코드는 성공 조건에서 제외하고 exact ownership을 검증한 뒤
  container/network/image 부재를 제한 polling한다. identity mismatch·계속 남은 리소스는
  별도 issue code로 실패한다.
- workers=8 기준선에서 기존 change request update/delete와 pipeline create pending flaky를
  각각 재현했다. change review는 exact BFF list 응답 완료, pipeline create는 테스트가 직접
  release하는 response gate를 기준으로 바꿨고 timeout은 늘리지 않았다. 첫 response predicate가
  문서 응답에 BFF parser를 호출한 실패는 해당 predicate 지점부터 exact pathname으로 고쳤다.
- 검증: 종료 판정·격리 Vitest **13 passed**, frontend 전체 **259 passed**, 배포 자동화
  단위 **8 passed**, TypeScript·ESLint green. exact production image D는 동일 SHA에서
  workers=8 **276/276**, workers=4 **276/276**, 두 번 모두 manifest 일치·child exit 0·
  reporter gate true다. 각 종료 후 owned container/network/image는 0건이다.
- DB는 사용하지 않았다. 보존 clone `ktm-tvn45-db`는 새 clone/restore/migration/downgrade
  없이 다음 DB 관련 task용으로 유지한다.
- 적대 리뷰는 child signal을 test failure로 분류하던 P2를 찾아 infrastructure exit 2로
  정정했다. pending response는 assertion 실패에도 `finally`에서 해제하고, filesystem
  cleanup 실패를 기록한 뒤에도 Docker cleanup을 계속한다.
- reporter가 expected failure의 첫 retry/error만 fingerprint해 다른 재시도 회귀나 후속 soft
  error를 가릴 수 있는 기존 잔여 위험은 현재 authored delta 밖이다. 작업 확장 규칙에 따라
  `T-VN-H38`로 등록해 다음 Lane B task로 배치했다.

## 2026-07-30 (codex) — T-VN-11A/B 5상태 batch 생산자·소비자 호환 완료

- Map `POST /v1/features/batch`는 최대 200개 ID를 한 set-based snapshot query로 처리하고
  입력 순서를 보존한다. `found`는 고정 `trip_card`, `retired|suppressed|missing`은 revision
  tombstone, validator가 일치하면 `unchanged`를 반환한다. 중복 ID와 PostgreSQL `bigint`
  범위 밖 revision은 422다.
- OpenAPI runtime 경계는 정확한 `2^63-1`을 유지하되 JSON Schema maximum의 부동소수점
  반올림을 피하려고 표준 `format: int64`와 정확한 설명을 쓴다. 200개 실데이터 EXPLAIN은
  `feature.features` PK index를 사용하고 base feature sequential scan은 0이다.
- PinVi는 다섯 arm을 exhaustively decode하고 `1..200` 설정을 fail-fast한다. cache는 refresh
  generation과 revision fence로 늦게 도착한 응답의 rollback을 막고, terminal/missing도 bounded
  negative record로 보존한다. transport 실패만 만료 snapshot을 `unverified`로 재사용한다.
- 첫 적대 리뷰는 `FeatureTripCard.as_snapshot()`의 flat 좌표가 `tripMapPoints`의 canonical
  `coord` 계약과 달라 모든 복원 마커를 제거하는 문제, out-of-order cache rollback,
  chunk 상한·revision 범위·plan registry·문서 drift를 찾았다. 모두 회귀와 함께 수정했다.
- 최종 재리뷰는 공개 가시성이 바뀌어도 Map base `row_revision`은 같을 수 있는데 negative
  fence가 후속 authoritative `found`를 계속 막는 문제를 재현했다. 최신 refresh generation은
  동일 revision과 missing 뒤 낮은 revision의 재생성을 수용하되, 늦은 이전 generation과
  무순서 write는 계속 차단하도록 고쳤다.
- 같은 재리뷰에서 200개 registry가 3,200행 seed의 6.25%를 조회해 planner-default
  `feature.features` Seq Scan을 실제 선택하는 P1, DB `OperationalError`가 계약된 503 대신
  generic 500으로 새는 P2도 재현했다. service batch만 기존 public batch와 같은 1.56%
  selectivity(12,800행)로 검증하고 `-k service` **3 passed**를 확인했다. DB 계층
  `SQLAlchemyError`는 `FEATURE_BATCH_UNAVAILABLE` problem+json 503으로 변환하고 OpenAPI와
  `OperationalError` 회귀를 추가했다.
- Live 첫 재검증은 접근성 snapshot에 `1일 표시 장소 4곳`이 보이지만 문구가 두 sibling
  element라 합친 text locator가 찾지 못했다. 테스트를 실제 DOM 경계인 `1일 표시`와
  `장소 4곳`으로 나눠 실패 지점부터 재실행했고 **1 passed**다.
- 기존 `ktm-tvn45-db`를 새로 복제하거나 복원하지 않았다. 종료·비공개 fixture를 만든 뒤
  다섯 상태, 503 `unverified`, 회복을 검증하고 원본 SQL로 fixture만 복구했다. 전용 API/Web/
  proxy container와 loopback listener는 0이며 clone은 healthy `0068`로 보존한다.
- 서로 다른 저장소라 한 GitHub PR은 불가능하다. Map 생산자와 PinVi 소비자 PR을 동일
  OpenAPI snapshot·Live 증거로 묶은 호환 쌍으로 취급하고 Map → PinVi 순서로 머지한다.

## 2026-07-30 (codex) — Claude PR #890/#891 사후 감사 정정

추적 issue #893에서 Lane A a1 #890은 독립 리뷰어 2명, docs-only #891은 1명이 원 PR patch를
감사했다. 후속 #892와 rebase 유입 diff는 finding 범위에서 제외했다.
감사 도중 추가 머지된 Claude docs/docstring PR #894는 issue #895로 별도 원본 patch를
전문 리뷰어 1명이 감사했다. 현재 브랜치가 이미 H30B/C 인덱스·상세 불일치를 고친 것 외에,
prod external-infra에서 동작하지 않는 standalone backup 계획, 0068 autocommit 부분 적용,
`collection_key`의 admin 입력·저장·검색 계약 누락, resume의 0064~0067 stale 범위를 정정했다.
H35는 external DB custom dump를 scratch DB에 실제 복원 검증한 뒤, 0064/0068 partial state를
downgrade 없이 forward 재개하는 계획으로 바꿨다. 이미지 준비를 먼저 끝내고 API·Dagster
writer/ingress cold fence 안에서 dump→복원 검증→migration→구조 smoke를 마친 뒤에만
fence를 해제해, dump 이후 정상 write를 옛 snapshot 복원으로 잃는 창도 닫았다. candidate
build 전에 현재 0063-compatible API·UI·Dagster web·daemon의 service별 image ID·revision·
배포 checksum을 immutable rollback bundle로 보존한다. 성공 경로는 API·UI·Dagster web을
prod에서 검증하고 daemon은 격리 DB에서 선검증한 뒤 forward-only 결정을 내린다. H35는
materialize하지 않고 1,020/1,477 baseline을 H30B에 넘겨 task 소유권과 before/after를
보존한다.
후보 API의 기본 entrypoint가 이미지 점검만으로도 migration을 먼저 실행할 수 있으므로,
candidate 준비는 build-only로 제한한다. H36 코드는 network·DB credential이 없는 entrypoint
override 또는 offline image layer로 확인하고, 그 직후 prod head가 여전히 0063인지 확인한
뒤에만 cold fence 단계로 넘어간다.
Dagster schedule/sensor와 pending run도 writer fence에 포함한다. rollback 가능한 동안
prod candidate daemon은 시작하지 않는다. 대신 post-migration app·Dagster DB bundle을
같은 scratch pair에 실제 복원하고 candidate daemon을 그 격리 DB에서 pause 상태로
기동·검증해 네 번째 service의 runnable gate를 cutover 전에 닫는다. 그 bundle과 clean
scratch identity만 H30B에 넘기고, H35 자체가 prod daemon enablement와 ingress를 정상화해
task/PR 경계를 maintenance 상태로 넘기지 않는다.
H30B materialize 입력도 live concierge 재조회에 맡기지 않는다. H35가 `changes` 전 페이지의
cursor chain·operation 포함 ordered payload를 credential 없이 canonical artifact로 보존하고,
1,477행·SHA-256을 DB dump/image manifest와 결속한다. H30B는 이 artifact만 network-free
resource로 재생해 DB 기준선과 입력 양쪽의 동일 snapshot을 보장한다.

- 이름 단독 오링크를 막는 `_adopted_match`가 주소 hint 유일 매칭까지 함께 막아 ADR-063을
  위반했다. 주소 hint 경로는 복원하고 이름 단독 후보는 `ambiguous/후보 다수`가 아니라
  `review_required/수동 검토`로 분리한다. 자유형 region 약칭으로 불일치를 단정하던 문구도
  단순 context로 낮춘다.
- H33은 unlink를 먼저 commit하고 ledger를 별도 transaction에 써, 후자 실패 시 감사 공백을
  남겼다. row lock·guarded UPDATE·advisory-serialized finding을 항목별 한 transaction으로
  묶고 H36 이후 사실에 맞는 `resolved` 증거로 기록한다. 올바른 non-null 링크는 건드리지
  않되, 이미 해제됐지만 ledger가 없는 대상은 멱등하게 `resolved` 증거를 복구한다.
- H25B apply는 승인 key의 기존 `feature_id`가 틀려도 건너뛴 뒤 manifest를 다시 서명했다.
  `(collection_key, source_item_key, source_component_key)` 정확한 1회 출현과 기존 ID를
  전 파일 쓰기 전에 검증한다. 승인 전체를 메모리에서 변환·직렬화한 뒤 동일 디렉터리 임시
  파일과 `os.replace`로 CSV/manifest를 교체해, 뒤쪽 malformed metadata도 부분 반영을
  남기지 않는다. 실제로 바뀐 행 수는 필드 수가 아니라 행 단위로 센다.
- 공개 노출 verifier는 feature/search HTTP 500과 빈 positive control도 성공으로 통과했다.
  negative control 404, 각 표면의 200/body shape, 비어 있지 않은 검색 결과와 명시적
  `feature_id` 필드를 강제한다.
- 수동 검토 UI가 후보 ID를 축약 표시만 해 운영자가 연결할 수 없었다. 전체 ID와 기존
  `CopyButton`을 노출하고 mocked UI 회귀로 고정했다.
- #891이 가린 열린 H30B/C를 Lane A 순서에 복원하고 `tasks-done.md`에 들어온 열린 checkbox
  6개는 역사 bullet로 바꿨다. H11A/B 단일 PR 사용자 결정도 백로그 정본에 반영했다.

회귀는 router의 주소 hint/name-only 상태, H33 transaction rollback·가드, H25B 잘못된 기존
ID·중복 identity·후행 malformed metadata 원자성·행 단위 count, verifier 500/빈 대조/
누락 `feature_id`를 직접 고정한다. Lane A a1 독립 적대 리뷰어 2명은 최종 authored delta에서
모두 P0~P2 0건을 확인했고, #894 docs 전문 리뷰어도 배포 계약 잔여 finding 0건으로 종료했다.

최종 exact HEAD 검증은 핵심 Python 회귀 **42 passed**, 두 번째 reviewer의 확장 targeted
**57 passed**, Ruff·mypy(**196 files**: core 117 + API 56 + Dagster 23)·ESLint·
OpenAPI/type drift green,
Vitest **254 passed**다. exact HEAD production image를 쓴 Mocked 최종 D checkpoint는
workers=4 두 번 모두 **276/276**, manifest expected/actual failure·flake 0으로 일치했다.
다만 두 실행 모두 manifest 출력 뒤 runner가 nonzero로 끝났고, owned 자원·HEAD·source
digest 사후 검사는 깨끗했다. 원인 진단용 workers=8에서는 변경과 무관한 기존
`change-requests update/delete` spec 한 건이 timing 실패해 275/276이었다. 테스트 성공과
checkpoint 프로세스 성공을 섞어 green으로 기록하지 않고 `T-VN-H37`로 후속한다.

기존 `ktm-tvn45-db`
(`0068_integrity_last_seen`)를 새 clone·restore·downgrade 없이 재사용한 파괴적 Live UI도
공식 CSV 5개 preview/commit과 REST·관리자·지도 표면 **4/4**가 통과했다. 전체 item 3,530,
active/source-present 3,530은 보존됐고 링크는 3,269→3,266으로 정확히 3개 줄어 이름 단독
오링크가 재생성되지 않았음을 확인했다. 후보 container/network/image/listener는 0으로
정리했다. 후속 스크립트를 실제 clone에 재실행해 H33 ledger는 0→3→3으로 멱등 복구됐고,
H25 resource aggregate hash `bfc3d558…`는 전후 동일하다. clone은 healthy 상태로 다음
task에 재사용할 수 있다.

## 2026-07-30 (codex) — T-VN-49A/B/C/D 단일 PR 구현·최종 gate 완료

H49 네 단계를 한 브랜치에서 끝냈다. 19개 giant component는 단순 View wrapper가 아니라
domain controller/state와 실제 section 경계로 분해하고, 결합 상태 3곳은 reducer로 옮겼다.
그 결과 `no-giant-component` 19개와 `prefer-useReducer` 3개 exact 예외가 0이 됐다.
실제 false positive가 재현되는 `live.ts` transport lifecycle과 datasets external-event
effect만 규칙별 최소 예외로 남기고 verifier의 exact 목록도 함께 갱신했다.

두 적대 리뷰어는 branch-authored 전체 delta만 검토하고 main rebase 유입 diff는 제외했다.
지적한 핵심은 비동기 geocode/reverse가 최신 form을 stale closure로 덮는 문제와 reset 뒤
응답 재유입, request/offline-upload가 거대한 flat prop bag으로 구조 검사를 우회한 문제,
enrichment callback churn이었다. 요청 identity와 존재하는 필드만 patch하는 규칙을 넣고,
form/mutation을 실제 소유 section으로 내렸으며 callback을 안정화했다. 같은 전체 범위 재검토
P0~P2는 0건이고 지연 geocode 입력 보존 회귀 테스트도 추가했다.

React Doctor는 **280 files, 0 issues**, Vitest는 **254 passed**, TypeScript·ESLint·production
build는 green이다. Mocked 첫 시도는 다른 agent가 소유한 12705 포트를 재사용해 로그인 화면에
붙은 환경 충돌이어서 산출물을 폐기하고, self-owned port runner의 실패 지점부터 재개했다.
exact authored checkpoint에서 serial/workers=4 각각 **275/275**, expected/actual failure·
flake·skip과 소유 자원 잔존은 0이다.

Live는 기존 `ktm-tvn45-db`를 재사용했다. 종전 v5 checkpoint는 그 뒤 정상 생성된 soft-delete
audit 6행 때문에 exact하지 않아 이전 dump를 격리 보관하고 현재 clone을 새 baseline으로만
서명했다. 새 clone·restore·Alembic downgrade는 하지 않았다. 파괴적 Live main/recovery는
각각 **2/2**, result `complete/passed`; active acceptance Feature·nonterminal request·FK,
BLOCKED, 전용 container/network/image와 loopback listener는 모두 0이고 clone은 healthy다.
최종 main 34커밋 rebase도 충돌 0건이어서 authored 리뷰·Live 범위는 바뀌지 않았다.

완료 이관과 H22C barrier 해제는 H49 코드와 같은 merge commit으로만 `main`에 들어가므로,
`main`에서 문서 상태가 구현보다 앞서는 구간은 없다. landing 뒤에는 clone/checkpoint의
다음 task 재사용 가능성을 다시 판정하고 별도 Claude Code PR 사후 감사를 진행한다.

## 2026-07-30 — 게이트가 조용히 축소 통과하고 있었다 (+ 철회 근거 3곳 정정)

**n150 CI-parity 게이트를 잘못 돌리고 있었다.** `kor-travel-map-t176-ci:latest`에는 저장소
사본이 `/workspace`에 구워져 있는데, 나는 트리를 `/w`로 마운트했다. 그러면 구운 사본이
`sys.path`에서 이겨 `src/kortravelmap/*` import가 **이미지의 낡은 코드로 해소된다**.

같은 트리, 마운트만 바꿔 실측했다:

| | `/w` 마운트 | `/workspace` 마운트 |
| --- | --- | --- |
| pytest | 2543 passed | **3053 passed** |
| mypy --strict | 173 files | **196 files** |

차이 510건은 실패가 아니라 **수집조차 되지 않았다** —
`packages/kor-travel-map-dagster/tests/*`가 `from kortravelmap.dto import AdminEvidence`에서
`ImportError`로 통째로 죽는데, 이미지의 `/workspace/src`가 그 DTO(H28B에서 추가)가 생기기
전 커밋이기 때문이다.

**증상이 "3 failed, 2543 passed"라서 알아채기 어려웠다.** 실패가 아니라 조용한 축소 통과였고,
나는 그 숫자를 여러 PR에서 "게이트 통과"의 근거로 인용했다. 다행히 #890의 실제 판정은
GitHub CI(8잡 green)가 했고 내 변경은 `packages/`·`scripts/`·`docs/`·`resources/`에 있어
그 부분은 `/w`에서도 제대로 테스트됐다. 하지만 **나머지 회귀 주장은 그만큼 약했다.**
`docs/dev-environment.md`에 마운트 지점과 실측 수치를 박고, 게이트 보고 시 **통과 건수를
같이 적는다**는 규칙을 넣었다.

이번 것도 형태가 같다 — **성공을 보고하는 측정이 실패했을 때 다르게 나오는지** 묻지 않았다.
`/w`와 `/workspace`를 비교해 볼 이유가 없었고, 그래서 비교하지 않았다.

**철회된 tautology 근거가 3곳에 원문 그대로 남아 있었다.** #673 조사 서브에이전트가 찾았다.
concierge payload의 `legal_dong_code`는 같은 좌표로 같은 geo `/v2/reverse`를 호출한 캐시라
"payload 코드 == geo 코드"는 tautology인데, 그 축이 아직 근거로 적혀 있었다 —
특히 `test_admin_code_validation.py`의 docstring이 **무효 축을 회귀 테스트의 정당화로**
쓰고 있었다. `validation.py`, `docs/architecture/address-geocoding.md`도 같다.
유효 근거(독립 축: `Address.sigungu_name` 대조 + 정지오코딩)로 교체했다.
리포트·journal에는 정정문이 있었는데 **코드 주석까지 따라가지 않은** 것이다.

**#673은 닫을 수 없다.** 규칙 교체는 머지됐지만 prod에 배포되지 않았고, 이슈가 신고한 손실이
실재한다 — live export 1,477 대비 prod 적재 1,020(**457건 미적재**), `max(last_seen_at)`이
2026-07-14(이슈 제기일)로 그 뒤 materialize가 없다. blocker는 `T-VN-H35`(배포)와
`T-VN-H30B`(실적재 실증)이고, `T-VN-H30C`·`T-VN-H32`는 이슈 범위 밖이다.

**H35 실측 정정**: 저장소 head는 `0067`이 아니라 `0068_integrity_last_seen`이라 간극은 5개다.
`0065`의 `DELETE`는 **0행**(prod에 `archived_at IS NOT NULL`이 0건)이라 내가 경고했던
파괴는 이번엔 발화하지 않는다. 대신 **`collection_key` 52개 재작성**이라는 외부 계약 변경이
있고, `env.py`에 `transaction_per_migration`이 없는데 `0064`의 `autocommit_block()`이
트랜잭션을 커밋해 **0065 실패 시 0064만 적용된 채 version은 0063에 남는다.**

## 2026-07-29 — T-VN-H36: 이름 단독 자동링크를 막았다. H33이 비로소 durable해졌다

curation CSV import에서 `feature_id`가 빈 행이 이름만 일치하는 후보에 자동으로 붙던 경로를
막았다. 리졸버가 `lower(f.name) = lower(place_name)` 단독으로 후보를 찾고, 라우터가
`matches[0] if len(matches) == 1`로 "유일하니 맞겠지"라며 채택하던 규칙이다. **유일성은
동명 feature가 하나뿐이라는 뜻이지 같은 장소라는 뜻이 아니다.**

바꾼 것은 `_adopted_match` 하나다 — CSV가 `feature_id`를 적지 않았으면 후보 수와 무관하게
링크하지 않는다. 후보는 버리지 않고 `candidates`로 계속 노출하므로 운영자가 preview에서
보고 admin에서 직접 붙일 수 있다. SQL·DTO·openapi·마이그레이션 무변경, 기존 테스트 23건 무손상.

**측정.** 커밋 CSV 486행 전수에 prod 리졸버 SQL을 재생했다(읽기 전용).
빈 264행의 후보 분포는 0건 256 / 2건 이상 5 / **1건 3**. 그 3건이 막히는 자동링크 전부이고,
**셋 다 region 불일치**다(남이섬 강원→서울 ×2, 청남대 충북→전남). 즉 **잃는 정당한 링크는
0건**이고 막는 것은 T-VN-H33이 끊었던 바로 그 3건이다.

**이번엔 반증 가능성을 먼저 설계했다.** 이 세션에서 두 번(공개 노출 0건, 탐지기 3→0) 무너진
지점이라 측정을 만들 때 "실패했다면 다른 결과가 나오는가"를 먼저 물었다.
- `blocked_autolinks`가 0이면 아무것도 안 막은 것이다.
- `csv_specified`(222)는 리졸버가 아니라 **CSV 파일**에서 오므로, 링크를 통째로 껐다면
  이 숫자가 blocked와 **같이 움직이지 않는다**.
- 후보 분포가 전부 0이면 조회가 죽은 것이다.
테스트에도 음성 대조(후보 0건은 여전히 `unmatched`)와 양성 대조(CSV가 `feature_id`를 적은
행은 그대로 링크)를 넣었다. 대조가 없으면 "전부 미연결"이 성공인지 고장인지 구별되지 않는다.

**또 배포되지 않은 코드를 prod 동작으로 읽었다.** H33에서 나는 "prod가 0063이라 import
자체가 실패하므로 당장 되살아나지 않는다"고 적었는데, 배포 이미지 `c8ed6164`의 import 코드에는
`source_present`/`external_component_id` 참조가 0건이라 prod 스키마와 정합하며 **오늘도
동작한다**. 참인 명제는 "HEAD 코드를 prod 스키마에 돌리면 실패한다"였고 나는 그걸 "prod에서
import가 실패한다"로 옮겨 적었다. 같은 실수를 H33에서 한 번 지적받고 또 했다. 덤으로,
CSV import는 `_UPSERT_ITEM_SQL`이 아니라 `_BULK_UPSERT_ITEMS_SQL`을 탄다 — 내가 근거로
인용한 SQL 자체가 다른 경로였다.

**배포 순서**: 이 게이트는 `T-VN-H35` 이미지에 **반드시 포함**돼야 한다. H35 인수가 commit
모드 import를 실행하는데(live spec의 `palaceComponents` 단언이 실제 import를 요구한다),
그때 게이트가 없으면 3건이 그 자리에서 되살아난다. 마이그레이션만 올리는 것도 안 된다 —
`0065`가 drop하는 partial 인덱스를 현행 이미지 upsert가 arbiter로 명시하고 있다.

## 2026-07-29 — T-VN-H33: curation 오링크 3건 해제, 공개 오노출이 실재했다

H25B가 정지오코딩으로 찾아낸 오링크 3건을 끊었다. **실제로 틀린 장소를 내보내고 있었다** —
해제 전 한국관광100선 "남이섬" 자리에 서울 중구 사무소 feature가(2건), "청남대" 자리에
전남 영암 시설이(1건) 붙어 응답에 나왔다. 표면은 `/v1/curations/*`이고 익명 공개가 아니라
`RoutePolicy.PUBLIC_KEYED`다 — public API key 보유자에게 열린 표면이라는 한정이 붙는다.

**해소 증거는 두 번 갈아엎었다.** 초안은 "해제 후 공개 노출 0건"이라 썼는데 그 측정이
**반증 불가능**했다(적대 리뷰). `/v1/curations/features/{feature_id}`는 curation이 없으면
200+빈 배열이 아니라 **404**를 내는데, 확인 스크립트가 `curl -s`로 status를 버리고 에러
본문을 파싱해 "0건"을 출력했다 — **존재하지 않는 feature_id를 넣어도 같은 출력이 나온다.**
"탐지기 3→0건"도 마찬가지였다: 탐지기 모집단이 `feature_id is not null` inner join이라
**링크를 끊으면 그 행이 모집단에서 빠진다.** 0은 관측이 아니라 정의였고, 엉뚱한 행을
끊었어도 0이 나온다.

그래서 `scripts/h33_verify_public_exposure.py`를 만들어 대체했다 — negative control(없는 id)과
구별되지 않으면 스스로 경고하고, 반증 가능한 표면을 쓴다: 컬렉션 상세가 200으로 item
110·114건을 돌려주고 대상 3건이 `feature_id=null`, `q=남이섬` 검색은 5 group이라는 **양성
대조**를 가지며 그 안에 오링크 feature가 없다. **item은 공개 응답에 그대로 있고 링크만
끊겼다** — 해제이지 삭제가 아니다. 탐지기 쪽도 정보를 가진 숫자로 바꿔 적었다:
`db_linked_rows` 3269→3266, `db_region_codeable` 112→109(정확히 대상 3행만 빠졌다).
부수로 e2e 기대값 486도 유지됨을 확인했다.

되돌릴 수 있게 만들었다 — 해제 전 `feature_id`를 `curation_items.metadata`와 ledger
payload 양쪽에 남긴다. 가드도 걸었다: 현재 `feature_id`가 우리가 오링크라 판정한 그 값일
때만 끊는다(그 사이 올바로 재링크됐을 수 있다). `--apply` 재실행은 3건 전부 건너뛴다.

**🔴 그리고 이 해제는 durable하지 않다 — 초안이 반대로 적었다.** 나는 *"CSV import가
`feature_id = EXCLUDED.feature_id`로 덮어쓰는데 이 3행은 CSV가 비어 있으니 다시 링크되지
않는다"*고 쓰고 **그 근거로 task를 닫았다**. 적대 리뷰가 prod 실측으로 반증했다.
`EXCLUDED.feature_id`까지만 읽고 거기 무엇이 들어오는지 보지 않은 것이다 — 빈 `feature_id`는
링크를 막는 게 아니라 **이름 자동매칭을 켠다**(`_RESOLVE_FEATURES_BATCH_SQL`의
`WHERE requested.feature_id IS NULL AND lower(f.name) = lower(requested.place_name)`;
`address_hint`도 비어 주소 필터는 안 걸린다). 단일 매칭이면 그 id가 `EXCLUDED.feature_id`다.
커밋된 CSV의 빈 264행 중 단일 매칭으로 풀리는 건 **정확히 이 3행뿐**이고 전부 방금 끊은 그
feature로 돌아간다 — `남이섬`·`청남대`라는 이름의 live feature가 prod에 각각 하나뿐인데
그게 바로 틀린 그 feature이기 때문이다. import는 `metadata = EXCLUDED.metadata`로 무조건
덮으므로 위에 남긴 사유까지 지워진다.

그래서 `[x]`를 `[~]`로 되돌리고, finding도 `resolved` → **`open`**으로 바꿨다
(`/admin/issues` 기본 필터가 `open`이라 resolved면 운영자에게 보이지도 않았다).
근본 수정은 `T-VN-H36`이고 **`T-VN-H35`(마이그레이션 적용)보다 먼저**여야 한다 — 지금
안 되살아나는 건 prod가 `0063`이라 import 자체가 실패하는 우연 덕분이다.

**부수 발견 — 머지 ≠ 배포.** ledger 방출을 붙이는데 `ON CONFLICT`가 두 번 실패했다.
처음엔 arbiter 술어(`status IN ('open','acknowledged')`)와 내가 넣는 `resolved`가 안 맞는
줄 알고 고쳤는데 **같은 오류가 또 났다**. 원인은 코드가 아니었다 — prod alembic head가
`0063_pipeline_root_id`라 **H30A의 dedupe 부분 유니크 인덱스(0067)가 prod에 아예 없다**.
PR #888은 머지됐지만 마이그레이션은 prod에 닿은 적이 없다. H30A 완료 기록이 주장한
"dedupe와 `/admin/issues` 접기"는 지금 prod에서 성립하지 않는다. → `T-VN-H35`.

이번에도 형태가 같다. 첫 진단("술어가 안 맞는다")은 **내 코드 안에서만 찾은 설명**이었고,
두 번째 실패가 아니었으면 그대로 믿었을 것이다. 완료 기록을 쓸 때 *머지된 것*과 *배포된
것*을 구분해야 한다.

**두 개의 "0"이 둘 다 반증 불가능했다는 게 이번 핵심이다.** "공개 노출 0건"과 "탐지기
3→0건" 둘 다, 내가 실수로 엉뚱한 행을 끊었거나 item을 통째로 지웠어도 똑같이 나왔을 숫자다.
성공을 보고하는 측정을 만들 때는 **실패했다면 다르게 나왔을까**를 먼저 물어야 한다.
이번엔 negative control과 양성 대조를 넣어서야 그 질문에 답할 수 있게 됐다.

**가장 큰 교훈은 durability 주장 쪽이다.** SQL의 마지막 문장(`feature_id = EXCLUDED.feature_id`)을
읽고 "덮어쓴다"까지는 맞게 봤는데, **덮어쓰는 값이 어디서 오는지를 안 따라갔다.** 값의
출처를 추적하지 않은 채 구문만 보고 안전성을 주장한 것이고, 그 주장 하나로 task를 닫았다.
이 세션에서 반복된 "측정 도구의 산물을 데이터의 성질로 읽기"와 같은 뿌리다 —
**결론을 지탱하는 문장일수록 끝까지 따라가야 한다.**

부수로 하나 더: `ops.data_integrity_violations.source_record_key`에는
`provider_sync.source_records` FK가 걸려 있어 curation item 키를 넣을 수 없다.
ledger는 provider 적재를 전제로 설계된 테이블이라, 다른 도메인 finding은 payload에 실어야 한다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H25B 공식 curation 링크 역반영·매칭 재실행

**역반영 — 8건 중 5건만 했다.** H25A는 "DB에서는 링크됐으나 CSV가 비어 있는 8건"을
*"어느 문서에도 없던 확정 대상"*이라고 넘겼다. 그 판단은 **DB에 링크가 존재한다는 사실만
본 것**이었다. 대상 feature의 실제 주소·행정코드를 확인하고 장소명을 정지오코딩해 대조하니
3건이 오링크였다.

| 장소 | 정지오코딩(권위) | DB feature | |
| --- | --- | --- | --- |
| 청남대 | 충북 청주 `43111` | 전남 영암 `46830` | 오링크 |
| 남이섬 ×2 | 강원 춘천 `51110` | 서울 중구 사무소 `11140` | 오링크 |
| 청풍호 | 충북 제천 `43150` | 제천 `43150` | 일치 |

이름 일치로 붙은 전형적 오탐이다. 5건만 반영하고 3건은 미연결 유지
(CSV linked 217→222 / unresolved 269→264, `manifest.json` 수치·sha256 갱신).
DB 쪽 오링크는 그대로 남아 있어 공개 projection 노출 가능성이 있다 → `T-VN-H33`.

**매칭 재실행 — H25A 결론 하나가 더 무너졌다.** H25A matcher의 확인된 결함 넷을 고쳤다:
괄호(`영월동서강정원(연당원)`), `&` 복합명(`만천하스카이워크&단양강 잔도`), 포함 방향
(`강릉 선교장` ⊇ `선교장`), `status='active'` 한정(로더는 `deleted`/`hidden`만 배제).
축은 실재하는 것만 썼다 — `address_hint`는 486행 전부 비어 있어 `metadata_json.region`을 쓴다.

결과 **후보 없음이 191 → 1**. H25A의 *"191건은 매칭 버그가 아니라 실제 부재이며 provider
적재 범위 문제"*는 **matcher 산물**이었다.

**그런데 이 개선은 착시다.** 늘어난 후보 대부분이 `low`(부분일치)이고 상당수가 무의미하다.
등대 103건이 대표적 — 102건이 부분일치 후보를 얻었고 그중 **89건**의 최상위 후보가 상호가
`등대`인 가게였다("전부"라고 쓴 초안은 과장이었다 — 1건은 후보조차 없고, 나머지는
`방파제`·`호미곶` 등 다른 이름에 붙었다. `등대` 후보 중에도 **주소가 빈 속초 feature**가 있어
상호로 단정할 수 없다).
커버리지 수치만 보면 개선인데 실제로는 잡음이 늘었을 뿐이다. 역설적으로 이 잡음이
`T-VN-H31`(등대 공급원 부재) 전제를 **다른 경로로 재확인**해 줬다.

최종 등급은 **high 2 / review 13 / low 248 / none 1**이다. `high`에도 오탐이 있었다 —
`대관령`이 고개가 아니라 **동명 업소**에 붙었다. 그래서 **자동 승인 대상은 0건**이고,
264건은 사람 검토 대상이다. manifest(`h25b-match-manifest.json`)에 후보·근거·등급을 담아
커밋했다(H25A 미충족 AC).

`high`는 적대 리뷰에서 **6 → 7 → 2**로 세 번 바뀌었다. 세 번 다 데이터가 아니라 matcher
자신의 결함이었다: ① 시도 약칭(`충북`)이 정식명에 포함되지 않아 6개 시도가 통째로
`mismatch`, ② soft-delete feature 혼입(`status='inactive'`+`deleted_at`이라 status만
거르면 안 걸린다), ③ `LIMIT 15`에 `ORDER BY`가 없어 등급이 실행마다 달라짐.
**③을 고치며 넣은 `ORDER BY length(name)`이 네 번째 결함이었다** — 매칭이 양방향
substring이라 `스카`·`스페이스` 같은 2~4글자 feature가 그걸 포함하는 아무 긴 이름에나
걸리는데, 짧은 순 정렬이 그 쓰레기를 top 후보로 올렸다(`도째비골 스카이밸리&해랑전망대`의
1순위가 홍대 `스카`). 그때 관측된 `low` 급증은 정밀도 개선이 아니라 **정렬이 만든 착시**였다.
겹친 길이 내림차순으로 바꾸니 동해 `도째비골 스카이밸리`·포항 `스페이스워크`가 제자리로 왔다.
아울러 264행 중 **208행(79%)이 후보 cap 포화**여서 그 행들은 이름 유일성 자체를 판정할 수 없다.

**교훈**. 이번에 무너진 H25A 결론 둘 다 같은 형태였다 — **측정 도구의 산물을 데이터의 성질로
읽은 것**. H28의 tautology, H25A의 도달 불가 조건, H30의 "106 유지"와 한 계열이다.
그리고 이번엔 반대 방향의 착시도 나왔다: 커버리지가 좋아 보이는데 신호는 나빠진 경우다.
**수치가 좋아졌을 때도 그 수치가 무엇으로 만들어졌는지 본다.**
가장 뼈아픈 건 ④다 — 결함을 고치는 수정이 **새 결함을 넣었고**, 그 결과(`high` 7→2)가
"수정이 통했다"처럼 보였다. 리뷰 지적을 반영한 직후의 수치 변화도 검증 대상이다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H30A/B 검증 결과 durable 기록
## 2026-07-29 (codex) — T-VN-48D 최종 Mocked·clone Live 완료

보존 clone의 파괴적 Live 본편·recovery-only는 이미 각각 2/2를 실행한 상태에서, 최종
content equality가 정상적인 `ops_live_topic_revisions.dataset_projection` revision `+1`까지
변조로 취급해 fail-closed했다. 전체 clone/restore나 UI를 반복하지 않고 실패 지점부터
복구했다.

- 서명된 checkpoint dump의 직전 topic 행을 현재 DB에 대입한 전체 content digest가 v5
  baseline과 정확히 같은 경우만 허용했다. current row는 revision `+1`과 증가한 timestamp를
  별도 root-owned 증거로 결박하고, 다른 topic·schema·identity·content 차이는 그대로
  거부한다.
- evidence 사전 검증 뒤 `recovery-resource-finalizing`을 기록한 상태에서 `complete`가 같은
  증거를 다시 거부하던 전이도 수정했다. `direct-cleanup-running`을 이미 거친 이 두 단계만
  허용하고 임의 phase는 음성 테스트로 차단했다.
- Live result는 `complete/recovered`, main 2/2·recovery 2/2다. active acceptance Feature,
  pending change request, direct weather/price/FK, BLOCKED/quiescence/scratch/temp DB·role,
  runner container/network/image가 모두 0이며 clone은 healthy다. v5 custom dump는
  `archive_verified=true`, `full_restore_verified=false`로 보존했다.
- Mocked 첫 serial은 273/274로, `areTilesLoaded()` 뒤 늦게 도착한 실제 MapLibre `idle`이
  raster `sourcedata` 계측에 섞이는 한 건만 실패했다. repaint로 실제 idle cycle과 marker
  rAF를 먼저 소진한 뒤 계측하게 고쳤고, exact `823ba52b` checkpoint D를 serial과
  workers=4에서 각각 **274/274** 통과했다. expected/actual failure·flake·skip과 종료 자원은
  모두 0이다.

국소 gate는 runner unit 35개, Ruff, shell syntax, e2e TypeScript/ESLint가 통과했다. 최종
문서 이관 뒤 PR을 열고 CI green·직접 머지한다. Claude Code PR 사후 감사는 사용자 지시에
따라 task PR 머지 뒤 별도 후속 단계에서 진행한다.

PR #889 첫 CI는 Python 3.11/3.12/3.13에서 같은 11개 Dagster asset test를 검출했다.
`record_address_validation_findings()`가 typed `IntegrityFindingSyncResult`를 반환하도록
강화됐는데 주변 test double 12개가 여전히 `int`를 반환한 계약 drift였다. production
fallback을 넣지 않고 모든 double을 실제 결과 타입으로 맞췄다. 실패 node에서 재개한 Dagster
package 전체는 **510 passed, 1 skipped**, coverage **83.66%**이고 Ruff도 통과했다.

## 2026-07-29 (codex) — T-VN-48D 2인 적대 리뷰 하드닝

T-VN-48와 현재 PR에 이미 포함된 PR #888 사후 감사 수정의 branch-authored delta만 두
리뷰어가 검토했다. rebase로 유입된 PR #887 이하 코드는 범위에서 제외했다.

- Live clone fence가 client-controlled `application_name`을 소유권으로 믿던 문제를 기존
  client backend 전부 종료 + 정확한 backend PID/시작 시각 추적으로 바꿨다.
- runner의 FD 9 flock을 외부 명령에 상속하던 구조를 stdin EOF guardian coprocess로
  바꿔, runner SIGKILL 뒤 장시간 docker/build/executor가 복구 lock을 붙잡지 않게 했다.
- `0068`은 자유형 `payload.last_seen_at`을 timestamp로 cast·삭제하지 않고 payload를
  보존한다. `last_seen_at=detected_at` 결정 backfill, NOT VALID/VALIDATE, concurrent index
  교체로 malformed/null/offset 값과 대용량 lock 경계를 함께 고정했다.
- integrity cursor kind를 `integrity_issues_last_seen_v2`로 분리해 구
  `detected_at` cursor를 조용히 새 정렬축에 적용하지 않는다.
- 겹치는 batch는 `GREATEST(last_seen_at)`과 조건부 최신 필드 갱신으로 오래된 관측이 최신
  FK/message/severity/payload를 되돌리지 못하며, occurrence count만 누적한다.
- Mocked checkpoint cleanup은 container/network/image 제거 명령과 사후 부재를 확인하고
  Docker 오류·timeout·잔존을 exit 2로 승격한다.
- 1차 재검토가 `0068` 첫 autocommit 중단 뒤 duplicate column으로 재개 불가한 경계와
  default 설정 전 writer NULL 공백을 재현했다. column 추가+default를 단일 atomic
  `ALTER TABLE`로 묶고 column/constraint/index 각 단계가 부분 적용 상태를 감지·정규화해
  같은 forward migration을 재실행할 수 있게 했다.
- Docker daemon이 create를 완료했지만 CLI 응답이 유실되는 signal 경계는 create-attempt를
  먼저 기록하고 name+ownership label로 실제 ID를 회수해 제거한다. 검증 전 빈/손상 ID를
  소유 identity로 저장하지 않으며, stderr 문구 대신 container/network/image 목록의 실제
  부재로 cleanup 성공을 판정한다.

검증은 관련 단위 49개, 신규 migration/upsert 통합 7개, 전체 Ruff, strict mypy 196 files,
import-linter 4 contracts, shell/Node syntax가 통과했다. 실패한 migration fixture는
Alembic naming convention과 asyncpg datetime 타입 지점에서만 재개해 수정했고 downgrade는
실행하지 않았다.

## 2026-07-29 (codex) — PR #888 주소 finding ledger 사후 감사 정정

PR #888 원본 patch를 별도 적대 감사한 결과 8건을 확인하고 현재 T-VN-48 PR에 함께
반영했다.

- 서로 반대 순서의 multi-row upsert가 같은 unique key를 잠그며 deadlock할 수 있어,
  repository 진입점에서 `dedupe_key` 정렬 후 모든 `unnest` 배열을 만든다.
- 구 key는 `source_entity_type`을 생략하고 원천 id를 그대로 붙여 entity type 충돌과
  B-tree row 크기 초과가 가능했다. provider/dataset/type/id/code 전체의
  `av2_<sha256>` 68-byte key로 교체했다.
- recurrence가 payload만 갱신해 실제 `feature_id`/`source_record_key`는 최초 값을
  가리키던 문제를 고쳤다. Feature FK도 `CASCADE`에서 `SET NULL`로 바꿔 대상 삭제가
  ledger 자체를 삭제하지 않게 했다.
- `detected_at`은 최초 탐지 시각으로 보존하고 `last_seen_at` column을 추가했다.
  Admin/Ops 목록과 cursor·실제 query index는 최신 관측 시각을 사용한다.
- client의 broad catch를 typed `IntegrityFindingPersistenceError`로 바꾸고 strict는
  durable 기록 실패를 validation 실패보다 먼저 fail-closed한다.
- 결과를 `observed/unique/upserted`로 분리해 batch 내부 중복을 미기록으로 계산하지 않는다.
- 실제 구현에 없는 자동 close sweep을 광고하던 문서·상수·테스트를 제거했다.
- H30B는 동일 snapshot의 Feature before/after와 인증된 Admin API 실호출이 없으므로
  완료 표시를 취소하고 acceptance를 구체화했다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H30A 구현·H30B 1차 실증

**목표**. 주소/좌표 검증 결과가 Dagster run metadata에만 있어 run이 사라지면 증거도 사라지고
`/admin/issues`에서도 안 보였다. `ops.data_integrity_violations`에 남긴다.

**1차 구현과 그 기각**. migration `0067`(열린 이슈 한정 부분 unique index) + 건별 upsert +
client 메서드로 만들고 격리 clone에서 "finding 106건, 재실행에도 106 유지"를 근거로 삼았다.
적대 리뷰 2명이 실제 SQL·스키마 조회로 4건을 반증했고 전부 옳았다.

1. **`jsonb ||`는 shallow merge라 null이 기존 값을 덮어쓴다.** 재실행에서
   `provider_address`/`bjd_code`가 `None`이면 1회차 증거가 지워진다 — durable ledger 안에서
   증거를 잃는 것. 리뷰어가 n150에서 두 번 upsert해 실측으로 보였다.
2. **strict(배포 기본값)는 기록 블록 전에 `Failure`를 던진다.** 증거가 가장 필요한 run이
   아무것도 남기지 않았다.
3. **dedupe가 dedupe하지 않았다.** `dedupe_key`가 `source_record_key`에 걸려 있는데 그 키는
   `raw_payload_hash` 파생이라(`core.ids.make_source_record_key`), export에서 무관한 필드
   하나만 바뀌어도 새 열린 행이 생기고 기존 행은 영원히 열려 있었다. sweep도 TTL도 없었다.
   MOIS(977k) 규모에서 큐가 단조 증가한다. **내 "106 유지" 근거는 같은 export 재실행만
   본 것이라 정작 중요한 케이스를 덮지 못했다.**
4. **관측 코드가 관측 대상을 잠근다.** `ops.data_integrity_violations`에 statement 트리거
   (`trg_data_integrity_violations_ops_live_revision`)가 걸려 있어(실측 확인), finding당
   INSERT가 `ops_live` revision **단일 행**에 배타 락을 잡고 트랜잭션 끝까지 유지했다 —
   `/admin/issues` 쓰기 차단·동시 run 직렬화·admin PATCH와 데드락.

**재설계**. `sync_integrity_findings()`로 통합했다.
- `unnest` 기반 단일 INSERT로 트리거 1회만 발화한다. batch 내 중복은 파이썬에서 제거한다.
- `dedupe_key`를 source entity type+id 전체의 고정 길이 SHA256으로 만든다.
- 자동 resolve sweep은 배치 경계에서 안전하지 않아 넣지 않았다(`T-VN-H32`).
- `jsonb_strip_nulls`로 증거 소실을 차단하고 `last_seen_at`은 정규 column으로 둔다.
- strict 경로도 던지기 전에 기록한다.
- MOIS `obs_code`/`reverse_attempted`는 **reverse 경로 값만** 쓴다 — `geo`는 정지오코딩으로도
  채워져 obs가 `claim_text`와 같은 출처가 되는 오염이 있었다.

**후속 검증 정정**. payload 변경에도 접힘은 유효하지만 sweep 관련 검증은 실제 코드와
일치하지 않아 제거했다. 후속 감사가 type+id key, 고정 길이, 잠금 정렬, recurrence FK,
`last_seen_at` cursor, strict 기록 실패를 직접 고정했다.

격리 clone의 106→106, `occurrence_count` 2 실증은 구 v1 key의 동일 export 재실행만
확인했으므로 새 v2 key의 Live 근거로 사용하지 않는다. 실적재의 `source_records`
2000→2458(+458), 2회차 insert 0도 Feature 회복량을 증명하지 않는다.
배포 컨테이너 2곳의 concierge cursor가 미설정임을 확인해 H28의 "자동 회복" 논거를
기본값이 아니라 **배포값**으로 실증했다.

**H30C는 미완으로 되돌렸다**. MOIS는 payload에 `legal_dong_code`가 있으면 reverse를 아예
호출하지 않아 `obs`/`claim`이 상호배타이고 `dual`이 구조적으로 불가능하다 — **탐지 증가 0건**,
`unarmed`→`claim_only` 재라벨에 불과하다. 게다가 내가 backlog에 "나머지 provider는 payload
법정동코드가 없다"고 적은 것이 **거짓**이었다(krforest `region_code`, visitkorea
`l_dong_regn_cd`/`l_dong_signgu_cd`). 리뷰어가 원천 저장소까지 읽어 반증했다.

**실적재 검증이 잡은 것**. revision id `0067_integrity_finding_dedupe_key`가 33자라
`alembic_version varchar(32)`를 넘겨 upgrade가 실패했다. 단위 테스트로는 드러나지 않고
clone에 실제로 걸어야만 나오는 종류다 — H30B를 "산술이 아니라 실적재로" 요구한 값이 여기 있다.

## 2026-07-29 (codex) — T-VN-48D 최종 mocked checkpoint·Claude PR #885 감사

**mocked checkpoint**. PR #887 문서 변경을 rebase한 exact `b35d7cbb`에서 self-built
frontend와 브라우저를 self-owned internal Docker network에 격리했다. container port는
publish하지 않고 검증한 내부 IPv4에만 loopback 프록시를 열었으며, HTTP와 WebSocket의
비소유 외부 연결은 deny gate로 막았다. source digest와 Docker build가 동일한 격리 build
환경을 쓰도록 결속한 뒤 checkpoint D를 serial과 workers=4에서 각각 **274/274** 통과했다.
두 실행 모두 expected/actual failure, flake, skip이 0이고 실행별 container/network/image는
정리됐다.

**PR #885 사후 감사 정정**. 이전 issue #881 기록의 trusted-proxy 전환은 현재 geo 계약과
맞지 않아 폐기했다. backend는 권한이 넓은 admin proxy principal을 위임하지 않고 scoped
public API key를 `X-KTG-API-Key` header로만 전달한다. `E0100 key` fallback은 인증 결선
오류 503, 2xx JSON/schema 손상은 provider 오류 502로 분리한다.

주소 증거는 관측 후보 집합과 시도 여부를 typed DTO로 끝까지 보존한다. strict/ensure는
모든 error를 거부하고 영구 drop만 명시 allowlist를 쓴다. 이름은 substring이 아니라
행정구역 token state로 warning을 만들며, quarantine을 별도 typed 결과로 보존해
`upserts == bundles + quarantine`을 강제했다. 과거 H28 문서의 “380건 좌표 오류 0”은
독립적인 일반 좌표 정확도 증거가 아니므로, **기존 규칙으로 불일치 근거가 성립하지
않았다**는 범위로 정정했다. baseline 스크립트도 현재 validator 자기 비교가 아니라 당시
규칙 버전을 명시적으로 재현한다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H25A 공식 curation 미연결 증거·전제 정정

**결론 먼저**. task 전제 *"공식 CSV 고유 `feature_id` 158개 중 54개가 `feature.features`에
부재"*는 **재현되지 않는다**. prod에서 158/158이 존재하고 전부 curation이 링크 가능한 상태이며
`created_at`이 2026-06-29~07-03로 측정 시점보다 앞선다("나중에 적재돼서 지금은 보인다"는 양립
가설 배제). stale reference 해소는 대상이 없다.

**1차 초안이 적대 리뷰 2건에서 기각됐다.** 근거 7개가 무효 판정을 받았고 그 지적이 옳았다.

- *"dangling 0건 → 애초에 미연결"* — `curation_items.feature_id`가 **`ON DELETE SET NULL`**이라
  dangling은 구조적으로 불가능하다. FK 정의의 재진술을 발견으로 제시했고, 그 결과 261개 NULL이
  *cascade로 지워진 링크*일 가능성을 배제하지 못했다. 이건 전제가 주장하는 바로 그 형태였다.
- *"lifecycle/merge를 대조했다"* — `feature.feature_merges`/`feature.source_links`를 조회했는데
  **둘 다 존재하지 않는 테이블**이다(실제는 `ops.feature_merge_history` /
  `provider_sync.source_links`). `except Exception`이 삼켰고, 게다가 **빈 배열**에 바인딩돼
  어떤 결과도 낼 수 없었다. 로그에는 "조회 불가" 세 줄만 남아 축을 덮은 것처럼 보였다.
- *"자동 승인 가능 high 0건"* — high 조건이 `address_hint` 일치를 요구하는데 그 열은
  **486행 전부 비어 있다**. 도달 불가 분기였고 0은 채점 함수의 성질이었다. 그런데 이 수치로
  H25B를 "대상 0건"이라 재정의하려 했다.
- *"전제가 인용한 바로 그 clone에서도 0"* — clone 신원 미확인. 기록상 T-VN-47 clone은
  1,030,469이고 삭제됐다. 사용한 것(1,030,487)은 prod 재clone일 가능성이 크다.
- *"구 CSV로도 158/158 → CSV 변경 배제"* — 두 리비전의 `feature_id` **집합이 동일**해 결과가
  보장된 공허한 대조였다.
- *"269 vs 261"* — 전 collection 합계와 공식 CSV를 병치한 비교 불가 수치.
- *"none 191건은 실제 부재"* — matcher가 괄호·`&` 복합명·포함 방향·`status='active'` 한정에서
  실패한다. 269건 중 최소 89건이 그 형태다.

**실제 스키마로 다시 측정한 결과**(prod 단일 snapshot, `current_database()` 확인, 읽기 전용):

- `ops.feature_merge_history` **0행**, 158개 중 merge loser 이력 **0**, 미연결 261건 중
  `source_record_key` 보유 **0** → cascade로 지워진 링크가 아님이 확인됐다. 미연결이 맞다.
- 공식 collection으로 범위를 좁히니 CSV **217/269** vs DB **225/261**이고 collection별 총계가
  파일별 행수와 정확히 일치한다 → 같은 모집단이며 **DB가 8건 앞서 있다**. 이 8건은 CSV로
  역반영할 확정 대상이고 어느 문서에도 기록돼 있지 않았다 — 이번 작업의 유일한 신규 실행 항목.
- 미연결의 지배 원인은 수목원이 아니라 **등대 103건**(6개 시즌 105개 중 2개만 링크). ADR-034
  9단계 provider 순서에 등대 공급원이 없다 → `T-VN-H31`로 분리.
- 후보 등급은 자체 matcher 대신 CSV `metadata_json.feature_match_confidence`
  (review 183 / unmatched 86)를 기준선으로 삼는다. 자체 matcher는 15/191을 냈는데 168행 차이가
  이 데이터셋에서 가장 강한 신호이며, 그 방향은 "내 matcher가 약하다"이다.

**교훈**. H28의 tautology(자기 자신과 비교)와 이번의 도달 불가 분기는 같은 계열이다 —
**결론을 내기 전에 그 근거가 독립적으로 유도됐는지, 그리고 그 조건이 애초에 만족 가능한지를
먼저 확인한다.** 두 task 연속으로 같은 실수를 냈고 둘 다 리뷰어가 잡았다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H28A/B #673 주소 검증 규칙 교체

> **정정 (적대 리뷰 반영)** — 아래 "payload 행정코드 == geo 행정코드이므로 전부 오탐"이라는
> 근거는 **무효**다. concierge의 payload 코드는 같은 kor-travel-geo /v2/reverse를 같은 좌표로
> 호출한 캐시본이라 자기 자신과의 비교였다. 결론(380건 좌표 오류 아님)은 유지되지만 근거는
> 독립 축(provider 원천 텍스트 + 정지오코딩)으로 다시 세웠다 — 375건은 텍스트에 행정구역
> 토큰이 없어 좌표와 무관하게 통과 불가, 4건은 축약·단계 차이, 1건은 143 m 경계.
> 이름 축은 **삭제하지 않고** 결함만 고쳐 warning으로 유지한다(전 provider 적용).
> 상세: docs/reports/concierge-address-mismatch-evidence-2026-07-29.md

**배경**. #673은 concierge 후보 1,430건 중 410건이 `provider_address_mismatch`로 **영구
미적재**되는 현상이다. 규칙은 좌표 reverse `sigungu_name`이 provider 주소 문자열에
부분문자열로 없으면 error. 표본(해동용궁사)은 주소에 '기장'이 있는데도 error였다.

**H28A — 실데이터 재기준화**. 운영과 **동일한 코드 경로**로 돌렸다(근사 재현 금지):
live concierge export 전량 페이징 → `kor_travel_concierge_items_to_bundles`(실 geo reverse 주입)
→ `validate_feature_bundles_address`. 결과 1,477 후보 / error 380 / warning 701 — 현상 유효.

error 380건 각각에 대해 세 축(payload 행정코드 · 좌표 독립 reverse · 현재 규칙 판정)을 대조:
- **380건 전부 `false_positive_code_same`**. payload 시군구코드 == geo 시군구코드, 진짜 불일치
  **0건**. 후보 전체로 넓혀도 코드 불일치 0건(일치 1,424 / 코드 없음 53).
- 380/380이 payload에 시군구·법정동 코드를 **모두** 보유. 권위 축이 있는데 규칙이 안 썼다.
- reverse 최근접 거리 `<10m` 210 / `<100m` 136 / `<1km` 34. 좌표는 정확했다.
- 실패 유형: **365/380이 행정구역명 없는 짧은 주소**(`부산 기장 조방국밥`, `부산 광안리`),
  9건 접미사 차이(`기장` vs `기장군`), 5건은 문자열이 다른 시군구를 말함(그마저 payload 코드는
  geo와 같았다 — **문자열 쪽이 틀렸다**).

즉 규칙은 좌표-주소 일치가 아니라 **provider 주소 문자열의 완전성**을 재고 있었고, 실데이터
전체에서 탐지력이 0인 채로 380건을 파괴하고 있었다.

**중간에 자체 교정한 오류**. 1차 근사 스크립트는 `road_address`를 provider 주소로 써서 error를
8건만 재현했다. Map의 `_provider_address`는 `raw_address`(=`Address.display()`)를 쓴다. 근사를
버리고 실 파이프라인으로 다시 돌려 380을 얻었다. 또 geocode probe에 내가 `address` 필드를 보내
400을 받고 "drift 발견"으로 오인할 뻔했다 — 실 client는 `road_address`/`jibun_address`를 보낸다.

**H28B — 규칙 교체**. 13-에이전트 설계 워크플로(이해 5 → 설계 3 → 적대 심사 3 → 종합 → 비평)를
돌렸고, 코드를 읽어야만 알 수 있는 세 가지가 나왔다.
1. `_bjd_code_from_emd_code`가 region fallback 경로에서 읍면동 8자리 + `"00"`으로 법정동코드를
   **합성**한다 → 리(8:10)는 판정 근거가 못 된다. **8자리 캡**.
2. MOIS는 payload에 bjd가 있으면 reverse를 아예 호출하지 않는다 → 두 축이 동시에 존재하지 않는
   provider가 있다. 커버리지를 "통과"로 세면 안 된다.
3. `Address._check_code_consistency`는 payload에 `sigungu_code`만 있고 `legal_dong_code`가
   없을 때 `ValidationError`를 던지는데, batch 변환에 건별 격리가 없어 **1건이 1,477건 전체를
   죽인다**. substring 규칙보다 큰 손실 위험이었다.

구현:
- **`AdminEvidence`**(신규 DTO, `FeatureBundle`에 add-only): 판정 두 축을 `Address`로 병합하기
  **전에** 보존한다. 근본 원인은 병합이 두 축의 독립성을 지운 것이었다.
- **규칙**: 코드 대 코드 접두 비교(8자리 캡, claim 정밀도만큼만). 두 축이 다 있을 때만 판정하고
  없으면 **'통과'가 아니라 '증거 없음'**(`evidence_grade_counts`). 이름 문자열 축은 판정에서
  **제거** — 탐지력 0이 실측으로 확인됐고, warning으로 낮춰 남기면 이름 변형표를 유지하면서
  가치 0인 경고 1,000건을 얻을 뿐이다.
- **drop을 severity → code allowlist**(`DROPPABLE_ISSUE_CODES`). 새 error가 추가돼도 이 집합을
  고치고 테스트를 깨기 전에는 영구 손실이 불가능하다.
- `_address()`가 bjd 있으면 시군구/시도를 **bjd에서만** 유도 → batch 전멸 경로 구조적 제거.
  건별 격리(`quarantine`) 옵션도 추가.

**회복 검증(live)**. 같은 export를 새 코드로: **380 drop → 0, 1,477/1,477 적재, 손실 0.**
교차검증 성립 1,372/1,477(**92%**), 행정코드 불일치 0건, 건별 격리 0건.

**replay 장치는 만들지 않았다**. task 문구는 "payload hash가 같아도 재평가할 replay 경로"를
요구했지만 코드로 확인한 결과 불필요하다 — drop은 적재 **전**이라 dropped 후보는
`source_entities`에 행이 없고, concierge cursor는 settings에서만 오고 영속화되지 않아
(`kor_travel_concierge_feature_cursor` description: "운영 cursor 영속화가 붙기 전") 매
materialize가 ledger 전량을 재생한다. 근거 없는 장치를 만드는 대신 이 사실을 리포트에 기록했다.

**범위**. 설계 종합은 4개 PR(관측 ledger 테이블 + alembic, 증거 채널, 규칙, 오프라인 containment
감사)을 제안했으나 사용자 지시대로 한 PR로 묶되 **증거가 요구하는 핵심**만 담았다. durable
ledger 테이블·오프라인 기하 감사·타 provider `AdminEvidence` 채움·error 승격 게이트는 후속으로
남기고 리포트에 명시했다.

**검증**. n150 CI-parity — ruff / mypy --strict(core 117 · dagster 23) / dagster 494 passed +
1 skipped / 관련 unit 179 passed. 신규 회귀 25건(오탐 재발 방지 · 단계별 탐지 · 정밀도 규칙 ·
커버리지 집계 · allowlist 불변).
## 2026-07-29 (codex) — issue #881 Claude PR #882~#884 사후 감사 반영

**결론**: PR #884의 문자열 sanitization만으로는 URL query와 frame-local secret의 생성
자체를 막지 못했다. backend geo 인증을 public key query에서 trusted proxy header principal로
clean-cut하고 typed problem code를 중앙·세 경계에서 보존했다. PR #882/#883이 남긴 미사용
OpenAPI digest와 완료 task 중복도 제거했다.

- geo의 현행 `origin/main` 계약을 로컬 1차 source로 대조했다. Map backend는
  `X-KTG-Actor: kor-travel-map`, `X-KTG-Roles: source_file_viewer`,
  `X-KTG-Admin-Proxy-Secret`을 보내고 geo가 trusted peer CIDR+shared secret을 함께 검증한다.
  브라우저 public key와 backend secret의 env·compose 결선도 분리했다.
- `GeoAuthNotConfiguredError`(503/`GEO_AUTH_NOT_CONFIGURED`)와
  `GeoRequestError`(502/`PROVIDER_ERROR`)를 중앙 problem+json handler에 등록했다.
  admin issues, offline upload, feature-update adapter에서 generic status code로 소실되지
  않는 회귀를 각각 고정했다.
- PinVi `contract-pin-consistency`는 Map 핀 commit의 spec bytes/subset을 직접 비교하고
  `openapi-sha256.json`을 읽지 않는다. 소비자 없는 파생 manifest 생성·검사를 제거하고
  `tasks.md`를 열린 작업만 남도록 정리했다.

## 2026-07-29 (codex) — T-VN-48D durable clone Live·중단 지점 복구

**결론**: production DB를 건드리지 않는 보존 실데이터 clone 전용 trusted runner로
파괴적 Admin Feature Live evidence를 확정했다. 최초 실행의 최종 판정 버그는 build나
Playwright를 반복하지 않고 보존한 BLOCKED/final snapshot에서 복구했다.

- **격리·출처**: root-owned immutable git snapshot에서 exact `fe0c956e` API/UI/Playwright
  image를 만들고 image revision, clone container/system identity, loopback DB/API/UI 포트,
  non-production compose project를 결속했다. API는 `uvicorn`을 직접 실행해 Alembic
  startup mutation이 없음을 시작 전후 snapshot으로 증명했다.
- **파괴적 결과**: 본 acceptance **2/2**, recovery-only **2/2**. random-owned direct
  fixture는 Feature 2건과 weather/price 각 1건을 만들었고, UI create/delete 6건은
  soft-delete 감사 이력으로 남았다. final total 1,030,487건, non-deleted 1,030,387건이며
  migration `0066_curation_component_identity`, relation 49는 불변이다. cleanup/audit의
  owned Feature·weather·price·FK·pending change request는 모두 0이다.
- **실패 지점 재개**: 최초 `complete`가 seed의 정상 child→Feature FK 2건을 cleanup
  residue로 오판했다. `abc1de8b`에서 seed 기대 2/cleanup·audit 기대 0을 분리하고,
  old immutable source와 세 image revision, clone identity, 실패 당시 final과 현재 DB
  snapshot의 exact equality를 요구하는 `recover`를 추가했다. 그 검증만 실행해 완료했으며
  test/build/fixture/browser는 재실행하지 않았다.
- **종료 상태**: result는 `complete/recovered`, main·recovery 각 2 passed다. BLOCKED와
  후보 container/image/listener는 0이고 민감 browser raw artifact는 남지 않았다.
  다음 exact revision 재검증과 post-merge 재사용 판정을 위해 clone DB만 보존한다.

## 2026-07-29 (claude) — Lane A a1: T-VN-H21 geo 인증 결선 검증·비밀 유출 차단

**배경**. T-VN-H21의 열린 질문은 "첫 400 blocker(`E0100 query.key`)를 넘긴 뒤 runtime 계약에
추가 drift가 있는가"였다. 실행 환경에 key 값이 없어 확인 자체가 불가능했다.

**live 실증 (n150, 값 비출력)**. geo 컨테이너의 `KTG_VWORLD_API_KEY`를 그대로 써서 확인했다.
- 배포된 Map api 컨테이너의 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`는 geo 컨테이너 값과 **동일**.
  즉 원래 blocker는 배포 결선 결함이 아니라 **ad-hoc/CLI 실행 환경에 값이 없던 것**이었다.
- reverse(status=OK, cand=11, address·region 존재) / geocode(status=OK, conf=1.000, point 파싱)가
  기존 Pydantic 모델로 무손실 파싱 → **post-auth drift 없음**으로 열린 질문 종결.
- 브랜치 코드로 dedup live **5 passed**. 결선 차단·정상 좌표·오류 좌표·잘못된 키 4분기 확인.
- 도중에 내 probe payload(`address`)가 400을 받아 "drift 발견"으로 오인할 뻔했다. 실제 client는
  `road_address`/`jibun_address`+`fallback`을 보낸다 — **소비자 payload를 추측하지 말고 코드를
  읽으라는 교훈의 재확인**.

**최초 구현과 그 기각**. 호출 지점에 `preflight()`를 붙였는데, 리뷰 전 자체 점검에서 live 생성
지점이 7곳(CLI 1 + API 4 + Dagster 2)임이 드러나 6곳을 추가하고 AST 스캐너로 회귀를 고정했다.
적대 리뷰 2명이 **둘 다** 이 접근 자체를 기각했고 근거가 결정적이었다.
- 스캐너의 `_preflighted_names`가 모듈 전역이라, `admin_issues.py`처럼 같은 이름(`client`)의
  생성이 둘 있으면 **한쪽 guard를 지워도 통과**함이 실제 mutation으로 시연됐다.
- acceptance가 지목한 live 경로(`test_dedup_with_kraddr_geo_live.py`)는 "테스트는 mock이라
  키가 필요 없다"는 **사실과 다른** 전제로 스캔에서 제외돼 있었다.
→ `require_api_key` 기본 `True`로 **생성 시점** 검증에 옮겼다. 7곳의 수동 guard와 스캐너를 모두
지우고, 4경로가 별도 조치 없이 같은 규칙을 공유한다(mock transport 테스트만 명시적 opt-out).

**진단성을 고치려다 악화시킨 부분**. 결선 누락을 `ValueError`로 던지니 기존 `except ValueError`
사다리에 걸려 `/admin/issues` 422, offline-upload 409, feature-update 422, 그리고 admin 경로는
메시지가 스트립된 500까지 갔다. 없애려던 좌표-vs-결선 오진을 **우리 API 안에서 재생산**한 셈.
`GeoAuthNotConfiguredError`를 두고 base_url 미설정과 같은 **503**으로 매핑했다.

**비밀 유출 차단(가장 무거운 발견)**. `str(httpx.HTTPStatusError)`는 request URL 전체를 담고
거기에 `?key=<SECRET>`가 있다. 이 문자열은 세 boundary에서 **502 응답 body와 로그로 그대로**
나갔다. 키가 비어 있던 동안에만 무해했으므로, 이 task가 하려던 "key 결선" 자체가 유출을
활성화하는 상태였다. query를 제거한 `GeoRequestError`로 감쌌고, 회귀 테스트가 곧바로 2차
결함을 잡았다 — `from None`은 `__cause__`만 지우고 `__context__`엔 원본이 남는다. except 블록
**밖에서** 던져 chaining을 만들지 않게 고쳤고 실 401 응답으로 확인했다.

**그 밖의 리뷰 반영**. 128자 초과 key 사전 차단(같은 400이 된다), CLI는 traceback(exit 1) 대신
stderr + `_EXIT_INVALID`(2), 첫 유출 테스트가 **키를 받은 적 없는 객체**로 단언해 유출 구현도
통과시키던 공허함 제거(실 wire에 키가 실렸는지부터 확인), 과장된 주석("`/v2/*`는 key를
요구한다" 무조건 / "route 처리 전에") 정정 — ADR-060은 trusted proxy 우회를 명시하고, query
검증은 라우팅 **후** handler 실행 **전**이다.

**검증**. n150 CI-parity green — ruff / mypy --strict ×3(core 116·api 56·dagster 23) /
lint-imports 4 kept 0 broken / unit 1675 passed(잔여 3건은 main과 동일한 docker 바이너리 부재) /
api 792 passed / dagster 477 passed + 1 skipped.

## 2026-07-29 (claude) — Lane A a1: T-VN-H29 완료 + T-VN-H27 보류

**결론**: H07D 적대 리뷰가 찾아낸 실제 사용자 가시 버그를 PinVi PR #418로 고쳤다. H27은 조사 결과
에이전트 실행이 불가능해 사용자 지시로 보류했다.

- **T-VN-H29**: map-curated import POI가 `GET /search`에서만 좌표 null. 근인은
  `_snapshot_coord`가 중첩 `feature_snapshot["coord"]`만 읽은 것 — Map 생성부 view는
  `extra="forbid"`이고 `coord` property가 **아예 없어**(H07D typed view) 좌표는 top-level
  `lon`/`lat`으로 온다. 즉 그 read는 **구조적으로 항상 None**이었다. 다섯 번째 추출기를 만들지 않고
  정본 `extract_feature_coord`에 위임했다(기존 동작의 상위집합).
  - 리뷰어 2명이 전제를 데이터 흐름으로 실증(Map 생성부 → `CuratedPlanPoi` → `TripDayPoi` → 검색)
    하고 회귀 위험도 배제했다 — 비-map snapshot은 전부 중첩 `coord`, top-level
    `x`/`y`/`geometry`/`location` payload는 0건, 응답 계약은 기존 `_coord`/`_float`가 이미 처리.
  - 리뷰 지적으로 **내가 남겼던 "알려진 열화" 서술 2곳**(계약 게이트 주석·통합 문서)이 이 PR로
    거짓이 되는 것을 해소 기록으로 정정했고, 커버리지를 배선(`PlaceSearchResult.coord`)·
    nullable `lon`/`lat`·0.0 좌표 보존까지 넓혔다.
- **T-VN-H27 보류**: 프록시는 **OPNsense 라우터의 HAProxy**다. docker-manager에 HAProxy config가
  없고(`*haproxy*` 0건) n150도 haproxy inactive·`/etc/haproxy/` 부재라, tasks가 전제한
  "docker-manager 공개 base config"가 존재하지 않는다. 설정 적용도 proxy metric 확인도 라우터
  접근이 필요해 에이전트가 수행할 수 없어 사용자 지시로 보류했다.
- **교훈**: 계약을 typed로 좁히면 소비자 쪽의 잘못된 read가 **구조적으로 죽은 코드**가 된다.
  계약 작업 시 소비자 read를 함께 훑으면 이런 잠재 버그가 드러난다 — H07D의 소비자 전수 감사가
  실제로 그 역할을 했다.

## 2026-07-29 (claude) — Lane A a0 T-VN-H07C: v5 승격을 **구현 후 기각** (ADR-079), a0 종료

**결론**: #812의 ③(배포 compatible-pair에 pinned OpenAPI SHA)을 양 저장소에 실제로 구현하고
테스트를 baseline까지 맞춘 뒤, 적대 리뷰 2명의 실증으로 **기각**했다. manifest는 v4를 유지한다.
Map의 per-surface digest manifest는 **소비자 freshness 용도로 유지**한다(이미 머지, `207a6364`).

- **기각 근거 1 — 추가 탐지력 0**: 제안 필드 `map_openapi_sha256`은 `map_source_revision`의
  순수 함수(그 커밋 blob의 sha256)다. 그런데 attestation은 이미 그 revision을 운영자 제시
  commit과 **배포된 모든 이미지의 OCI revision 라벨**에 결박한다. OpenAPI가 바뀌면 커밋이
  바뀌고 그건 이미 게이트된다. 어떤 소비자도 이 digest를 독립 유도값과 대조하지 않아(형식 검사뿐)
  내가 ADR 초안에 쓴 "재-capture 없이는 통과 불가"는 **공허한 주장**이었다.
- **기각 근거 2 — 운영 마이그레이션 막다름**: v5는 canonical 파일명에 버전이 박혀 있어, ktdctl
  업그레이드 즉시 rollback이 무력화되고(존재하지 않는 v5 파일), capture는 v4 sibling으로
  fail-close, v4를 지우면 digest 계산이 실패한다 — `openapi-sha256.json` blob이 **기존
  프로덕션 이미지 revision에는 없기 때문**(어제 처음 생긴 파일). 즉 기존 pair는 v5로 capture
  자체가 불가능하고 운영자는 manifest 없는 상태에 갇힌다.
- **정정한 내 오류**: ADR 초안의 "코드 머지는 배포 상태를 바꾸지 않는다"도 틀렸다 — Map 절반
  (attestation version==5)은 머지 즉시 C7 게이트를 red로 만든다. 리뷰어가 지적했다.
- **유지·폐기**: `openapi-sha256.json` + `export_openapi.py` 생성/검증은 유지(PinVi가 **독립
  사본**과 대조하므로 그쪽에서는 실질 탐지력이 있다). docker-manager v5 브랜치와 Map attestation
  v5 브랜치는 폐기한다. 운영 문서·런북은 손대지 않으므로 v4 서술이 그대로 유효하다.
- **규율 정정**: tasks.md의 "OpenAPI compatible-pair gate"를 "per-surface digest 갱신 + 소비자
  스냅샷 재-vendor"로 바꾸고 재-capture/attestation 조건을 제거했다.
- **교훈(ADR-079에 기록)**: 계약에 새 필드를 넣을 때는 **독립적으로 유도된 값과 대조되는지**를
  먼저 확인한다. 대조 상대가 없으면 형식 검사만 남고, 그건 탐지력이 아니라 스키마 비용이다.

## 2026-07-28 (claude) — Lane A a0 T-VN-H07D ②: PinVi consumer 계약 + freshness 게이트 실효화

**결론**: PinVi half(PR #416, squash `8ea83358`)를 landing해 T-VN-H07D를 완료하고 #815를 닫았다.

- **vendor 방식**: Map full 스펙 1.1 MB 대신 detail-snapshot 경로·응답 스키마의 **전이적 폐포 +
  operation이 요구하는 securityScheme**만 결정적으로 추출한 19 KB subset. 정렬 key·고정 indent라
  같은 입력이면 같은 바이트가 나오고, 그래서 CI가 **재추출 후 byte 비교**로 검증할 수 있다.
- **소비자 계약**: `notice_plan`/`admin_pois`/`kasi`/`search.py`가 실제로 읽는 필드만
  type/nullable/required + 경로→200→`data` 결합 + admin 인증 헤더 header-only를 고정. exact
  property 집합은 producer(Map) 소유라 중복 고정하지 않는다(H07B와 같은 consumer 원칙).
- **freshness 역할 분리**: `contract-pin-consistency`(차단)는 Map을 **핀 커밋**으로 체크아웃해
  실제 비교 — 과거 sibling 부재로 skip되어 항상 green이던 경로를 없앤다. 증명 대상은 핀↔vendored
  **자기정합**이다. 핀 자체의 뒤처짐은 구조상 알 수 없어 예약·비차단 `contract-staleness`가
  Map main과 비교해 알린다(H07B의 174-commit 뒤처짐이 그 종류).
- **적대 리뷰 2명이 잡은 핵심**: 내가 "차단 게이트"라고 만든 job이 **required check 목록에 없어
  red여도 머지를 막지 못했다** — 없애려던 "항상 green" 맹점과 동일한 강도였다. `aggregate-ci.yml`의
  apps/api 술어 블록에 등록해 실효화했다. 그 밖에 job 이름 과장 정정(freshness→pin-consistency),
  `continue-on-error`가 예약 실패 알림 경로를 죽이던 문제 제거, concurrency group 충돌
  (schedule/push 상호 취소) 수정, subset의 securityScheme 누락으로 admin 인증 헤더 계약이 게이트
  밖이던 것 보완.
- **리뷰어 2**: 23개 핀을 독립 재검증(불일치 0)했고, 내 소비자 귀속 오기를 **세 번째로** 정정했다
  (`search.py`는 `name`만 읽고 lon/lat은 `admin_pois`/`kasi`가 top-level에서 읽는다). 아울러 이
  소비자의 **유일한 e2e fixture가 새 계약상 불가능한 payload**를 쓰고 있던 것을 찾아, 실제 shape로
  고치고 testcontainers로 실행해 통과를 확인했다.
- **파생 발견**: `search.py::_snapshot_coord`가 `feature_snapshot["coord"]`만 읽는데 Map view는
  `extra="forbid"` + `coord` 미보유라 **구조적으로 항상 None** — map-import POI가 통합 검색에서
  좌표 null이다. 런타임 수정은 계약 PR 범위 밖이라 `T-VN-H29`로 등록했다.
- **검증**: n150 CI-parity(ruff/format/mypy/unit 675 passed) + freshness 양쪽 실증 +
  integration testcontainers 실행 1 passed + 실제 CI에서 신규 게이트 pass(9s)·staleness skip 확인.

## 2026-07-28 (claude) — Lane A a0 T-VN-H07D ①: admin detail-snapshot payload 타입화 (Map half)

**결론**: #815의 전제가 조사로 확인됐다 — PinVi가 실제로 소비하는 admin detail-snapshot의
**계약이 OpenAPI로 표현조차 되지 않는** 상태였다. Map 절반(타입화 + 계약 게이트)을 먼저 landing한다.
PinVi 절반(vendor + 소비자 계약 + freshness CI)은 후속이며, 그때까지 `tasks.md` H07D는 열어 둔다.

- **발견 1 — 경로 불가시성**: PinVi가 호출하는 `/v1/admin/curated-features/{id}/detail-snapshot`은
  `include_in_schema=False` 숨은 alias다(문서 경로는 `/v1/admin/features/curated/...`). 런타임은
  정상이지만 **스펙 기반 게이트가 볼 수 없어** alias를 지워도 아무 테스트도 깨지지 않았다.
- **발견 2 — 계약 표현 불가**: PinVi가 읽는 plan-level 필드(title/category/summary/
  destination_name/region_code, source_name/provider, theme_slug)가 전부 free-form
  `dict[str, Any]`(`theme`/`content`/`source`) 안이라 스펙에 `{"type": "object"}`로만 나왔다.
- **조치**: 생성부가 **고정 key로** 만드는 값이므로(content 7 / theme 2 / source 4) typed view로
  전환했다. **etag는 repo payload dict에서 계산되므로 그 dict은 손대지 않고 API view만** 타입화해
  기존 etag·캐시 계약을 불변으로 유지했다.
- **적대 리뷰 2명(land-with-fixes) 반영**:
  - **오기 정정(중요)**: "PinVi가 `feature_snapshot`을 통째로 저장만 하고 내부를 읽지 않는다"는
    사실이 아니었다. PinVi는 `admin_pois`의 label/coord/address 추출기와 `search.py`의
    `feature_snapshot["name"]` SQL 술어로 내부 key를 직접 읽는다 → 네 번째 typed view로 함께 고정.
  - **머지 blocker**: `openapi.json`만 재생성하고 `frontend/src/api/types.ts`를 빠뜨려 frontend CI
    `gen:types:check`가 drift로 실패할 상태였다 → 두 산출물을 함께 재생성.
  - endpoint HTTP 테스트 추가(문서 경로·alias × populated·all-null 4조합), item view의
    `day_index`/`memo`/`source_record_key` default 제거(항상 내보내는 key라 required+nullable),
    생성부 key 단언을 view 대신 독립 리터럴로 교체(항상 참이던 tautological 검사 제거),
    round-trip을 nullable 분기까지 parametrize, 불필요한 `sys.path` 조작 제거.
- **검증(n150 CI-parity, clean clone)**: ruff ✓ · `mypy --strict` ✓(56) · **OpenAPI drift ✓** ·
  **types.ts `--check` exit 0** · 신규 계약 테스트 9 passed · api 패키지 **790 passed** ·
  curated unit 25 passed. 재생성 후 diff 0(커밋 산출물이 생성 결과와 일치).
- **리뷰어 실증**: 리뷰어 1이 TestClient로 두 경로 × all-null override를 직접 태워 200을 확인하고,
  단일 생성 경로·etag 불변·materialize 캐시가 이 endpoint로 흐르지 않음을 grep으로 증명했다.

## 2026-07-28 (claude) — Lane A a0 T-VN-H07B: PinVi #403 재감사 → consumer contract로 대체 landing

**결론**: 오래 열린 PinVi #403을 재감사한 결과 **고정 대상 자체가 틀렸다**. #403은 Map producer
테스트를 복사해 공개 curated 표면(`PublicCurated*`/`PublicCuration*`)을 field-level로 고정했지만,
PinVi user client는 그 경로를 호출하지 않는다. 전량 제거하고 PinVi가 실제로 읽는 필드의 typed
consumer contract로 대체해 **PinVi PR #415**로 landing했다(#403 대체).

- **근거(4중 확인)**: `_CLIENT_PATHS`에 curated 경로 없음(주석이 ADR-049·Map PR #533의 public
  `*-copy` 폐지를 명시) · `apps/` 전체 grep에서 curated 소비 코드 0건 ·
  `GET /v1/features/{id}`의 `curations` 필드도 `_detail_from_kor_travel_map`이 읽지 않음 ·
  큐레이션은 `kor_travel_map_admin.get_curated_detail_snapshot`(admin 표면 = H07D/#815 소유).
  producer exact 고정은 H07A(Map #814)가 이미 소유하므로 커버리지 손실 없음.
- **스냅샷 재동기화**: "H07A의 실제 user OpenAPI SHA와 대조"를 실행해 vendored 핀이 stale임을
  확인(`91b30f40`@`cf1f0bba` — Map main보다 174 commits 뒤) → Map main `8880c29b`/`0a7f1684`로
  갱신. 실제 drift는 구조 1건(`external_component_id`, Map 0066) + price 문구 3건뿐이며 PinVi
  소비 스키마는 구조 변화 0건이라 client/매핑 영향 없음.
- **설계 결정**: consumer는 **exact property 집합을 고정하지 않는다**. producer의 무해한 additive
  변경마다 false-red가 나기 때문이며, 실제로 0066의 `external_component_id` 추가가 #403의 pin을
  깨뜨렸다. 대신 "읽는 필드의 shape"을 고정하고 **경로→필드 사슬**을 끝까지 닫았다:
  `_ENDPOINT_DATA_SCHEMAS`(경로→컨테이너, 13경로 + `_CLIENT_PATHS` 일치 가드) → `items.$ref`/
  `additionalProperties.$ref`(컨테이너→item/map value) → 필드 type/format/enum/required/nullable.
  envelope `meta`(`Meta`→`ClusterMeta`/`PageMeta`)도 client가 `data`로 re-projection해 소비하므로
  같은 방식으로 고정했다.
- **비-tautological 보장**: 초안의 drift guard가 같은 파일의 손수 만든 두 표를 비교하는
  자기참조라 매핑 드리프트를 못 잡는다는 지적을 받아, `_SCHEMA_FIELDS`를 계약 표에서 **파생**시켜
  불일치 가능성을 제거하고, `model_validate`로 객체 전체를 검증하는 `/v1/public/*`는
  `app/schemas/public.py`의 `model_fields` ⊆ 계약을 강제해 **실제 소비 모델에 결합**했다.
- **리뷰 4라운드**: 적대 2명(land-with-fixes) → 재리뷰(커버리지 누락·컨테이너 dangling 지적) →
  최종 확인(**block**) → 해제 확인(**cleared**). 최종 확인이 잡은 **내 오기**를 정정했다:
  `data.get("cluster_unit")`을 "항상 None인 Pinvi 잠재 버그"로 기록했으나, client
  `features_in_bounds`가 `meta.cluster.cluster_unit`을 의도적으로 re-projection하며
  `test_kor_travel_map_client.py`·`test_features_api.py`가 non-None을 단언한다. 잘못된 주석은
  정상 설계를 "고치도록" 유도하므로 삭제하고, 같은 오독으로 빠져 있던 meta 필드를 함께 고정했다.
- **검증**: n150 CI-parity clean clone `74b199d` — `ruff check`/`ruff format --check`(343)/
  `mypy --strict app`(196) green, 계약 테스트 11 passed/1 skipped, 전체 `pytest tests/unit`
  **665 passed**(base `417da20` 661 대비 +4). 실패 20건은 base에서 동일하게 재현한 기존 실패
  (`test_api_image_provenance.py`, 컨테이너에 docker CLI 부재)로 이번 변경과 무관함을 실증했다.
  **변이 테스트 30건 전부 검출**(enum 축소·타입 변경·format 제거·required 변경·nullable 확장·
  union 확장·필드 제거·`items.$ref` 교체·map value 축소·경로 repoint·meta 사슬 repoint 등).
- **문서**: PinVi `docs/integrations/kor-travel-map-rest-api.md` §8(드리프트 게이트)의 stale 핀과
  삭제된 메커니즘 설명을 정정해 같은 PR에 포함했다. Map 저장소 문서는 repo가 달라 별도 PR.

## 2026-07-28 (codex) — T-VN-46 파괴적 Live·실패 지점 재개 완료

**결론**: npm 12.0.1 clean optional tree 구현 head `378c6524`를 적대 리뷰어 2명이
P0/P1/P2 0건으로 승인했고, 재사용 실데이터 clone의 파괴적 admin Feature acceptance를
인증 setup 포함 2/2로 통과했다.

- **Live identity**: API와 Live frontend image의 OCI revision은 exact head
  `378c652486613df73b2fa59de5cfacc459479c83`다. C7 image도 같은 source head에서
  clean build했고 API/UI는 격리 loopback port, DB는 health 정상인 `ktm-tvn45-db`
  (`0066_curation_component_identity`)를 사용했다.
- **실패 지점 복구**: API startup은 production profile의
  `KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED=true`가 빠져 fail-close했고 API container
  설정 단계만 보완했다. 첫 Playwright는 인증 setup을 통과했지만 prod-derived UI env의
  `KOR_TRAVEL_MAP_API_INTERNAL_URL`이 candidate API로 override되지 않아 첫 admin cleanup이
  write 전에 `403`이었다. 실패 runner artifact를 폐기하고 UI만 candidate loopback URL로
  다시 띄운 뒤 실패 spec부터 재개해 **2/2, 37.9초**로 통과했다.
- **잔여물 감사**: API-owned non-deleted Feature 0건, pending change request 0건,
  weather/price fixture 0건이다. clone의 non-deleted Feature는 1,025,428건이고 health는
  정상이다. runner/API/UI container, Playwright storageState/cookie·trace·screenshot,
  민감 로그·임시 env/session secret을 모두 폐기했다. DB·dump와 redacted immutable 수치만
  다음 task 재사용 판정 전까지 보존한다.
- **재발 방지**: `agent-workflow.md`에는 원격 branch frequent checkpoint와 머지 직전 PR
  규칙을, `agent-failure-patterns.md` F13에는 prod-derived env의 candidate API/DB exact
  preflight와 값 비노출 비교를 추가했다.
- **Claude Code PR 감사(#875)**: PR #874와 연결된 #814를 전문 서브에이전트가 사후
  검증했다. #814 squash/base·4 commits/95 behind, exact schema 범위, 0066
  `external_component_id`, `phones.items`와 targeted 11 green은 주장과 일치했다. 다만 완료된
  H07A를 active backlog에 중복 보존한 P2를 제거했고, #874가 #870에만 명시된 CI 대기 생략
  예외를 재사용한 P2를 process finding으로 남긴다. #874 checks가 나중에 모두 green이 된 것은
  보상 증거이지 향후 문서 PR 예외가 아니며, 새 사용자 예외가 없으면 모든 후속 PR은 CI green 뒤
  머지한다.

## 2026-07-28 (claude) — Lane A a0 T-VN-H07A: Map #814 residual contract 재감사·landing

**결론**: 오래 열린 Map PR #814(4 commits, base 95 commits behind)를 최신 main 위 residual
contract test로 재감사·landing했다(squash @ 259a9ec5). 착수 시 worktree main이 origin/main보다
46 commits 뒤처져 stale tasks.md(구 b-lane only 구조)를 읽었고, origin/main sync 후 정본
Lane A a0=T-VN-H07A를 확인했다.

- **재감사(제거)**: stale `docs/tasks.md` commit 2건, main T-VN-05R가 이미 소유한 union
  discriminator/mapping/oneOf 구조 assertion. per-variant `feature_kind` const로 동등 이상
  커버해 구조 검사 제거가 안전함을 확인.
- **남긴 잔여(비-tautological)**: curated feature variant 7·detail 5·PublicCuratedAddress·
  Collection/Item/CurationFeature/FeatureCurationGroup의 exact property/required 집합 +
  필드별 type/format/enum/const/$ref. main은 subset·disjoint·structural만 갖고 field-level 부재.
- **base drift 재조정**: n150 CI-parity pytest가 `PublicCurationItemView`에 migration 0066
  (curation component identity)로 required `external_component_id: str`이 추가된 것을 검출 →
  현행 생성 OpenAPI 기준으로 고정.
- **적대 리뷰어 2명**: tautology·redundancy 렌즈 + contract-fidelity 렌즈. 둘 다 전 schema를
  실제 pydantic 스키마·checked-in `openapi.user.json`과 대조해 land 판정. 지적 2건(low):
  (1) helper의 additionalProperties==False가 13개 schema에서 T-VN-05R와 중복이나 4개 curation
  view에 대해선 신규 커버라 구조상 불가피 → 유지. (2) phones가 array 레벨만 고정 →
  `phones.items.type=="string"` 추가 반영.
- **검증**: n150 CI-parity(ruff/pytest) 11 green(rebase 후 재확인). GitHub CI lint/mypy/
  lint-imports·openapi-drift·fixture-replay·frontend·pytest matrix·integration PostGIS green.
  codex 병렬 +32 commits를 origin/main rebase로 반영(api source 무변경 확인 → 재drift 없음). PR #814.
- **live 표면 주기**: test-only OpenAPI 계약 변경으로 admin-UI 표면이 없어, 실제 live 검증은
  n150 게이트가 실제 생성 OpenAPI에 대해 계약을 실행하는 것으로 갈음(파괴적 UI e2e 해당 없음).

## 2026-07-28 (codex) — T-VN-46 npm 12 clean tree 구현 checkpoint

**결론**: npm 10.9.4 Arborist가 현재 플랫폼에서 제외한 optional 부모의 WASM 자식을 root에
남기는 현상을 동일 lockfile로 재현했다. 최신 npm 12.0.1로 toolchain을 올리자 별도 direct
dependency나 출력 필터 없이 `npm ls --all --json`의 `problems`가 0개가 됐다.

- **소유 경계**: `@img/sharp-freebsd-wasm32(os=freebsd)`와
  `@img/sharp-webcontainers-wasm32(cpu=wasm32)`가 빠진 뒤 `@img/sharp-wasm32` 계열이
  orphan이 된다. OXC·Rolldown·Tailwind·unrs의 `cpu=wasm32` optional binding도 빠지면서
  같은 root `@emnapi/*`, `@napi-rs/wasm-runtime`, `@tybys/wasm-util`을 orphan으로 남긴다.
  npm 10.9.4의 `nested` install과 `npm prune`도 6개를 제거하지 못했다.
- **해결**: root package manager와 CI 명령을 npm 12.0.1로, Node 하한을 22.22.2로 전환했다.
  기존 exact 6-package 허용 목록은 제거하고 문제 배열이 비었는지 직접 단언한다. Sharp
  0.35.3과 Next 16.2.12의 실제 SVG→WebP optimizer 검증은 그대로 유지한다.
- **install script 정책**: npm 12에서 실행이 필요한 `esbuild@0.28.1`과
  `unrs-resolver@1.12.2`만 `allowScripts`에 exact version으로 명시했다. version drift와 새
  dependency script는 `strict-allow-scripts=true` 때문에 검토 없이 실행되지 않고 clean
  install이 실패한다. Node engine도 `^22.22.2 || ^24.15.0 || >=26.0.0`으로 제한했고,
  현재 `npm install-scripts ls` 결과는 unreviewed package 0개다.
- **검증**: 지원 Node 22.22.2 격리 환경의 exact clean install에서 audit 0, npm tree
  0 problems, ESLint 0 warnings, React Doctor 270 files/0 diagnostics, Sharp ABI,
  admin/user OpenAPI codegen drift, 두 type-check와 production build를 통과했다. npm 12
  package-lock 정규화 후 `--package-lock-only` 재실행 drift도 0이다.
- **흐름 정정**: T-VN 작업에는 issue를 만들지 않으므로 #872를 `not planned`로 닫았다.
  조기 draft PR #873도 닫고 원격 feature branch에 구현 checkpoint를 push했다. 적대 리뷰와
  파괴적 Live·task 문서 완료 후 머지 직전에 새 PR을 연다.

## 2026-07-28 (codex) — PR #871 머지·T-VN-46 clone 재사용 판정

**결론**: PR #871을 8개 CI green 뒤 merge commit `64c158c5`로 머지했다. 다음 Lane B
`T-VN-46`에 보존한 clone을 main schema로 forward upgrade해 재사용 가능으로 판정했다.
당시 만든 issue #872는 T-VN 작업에는 issue를 만들지 않는다는 후속 지침에 따라
`not planned`로 닫았다.

- **schema 호환성**: clone `ktm-tvn45-db`를 rollback 없이
  `0063_pipeline_root_id→0064_price_series_identity→0065_curation_source_presence→
  0066_curation_component_identity`로 올렸다. main Alembic head와 일치하고 DB health가 정상이다.
- **오염·용량**: Feature 1,030,469건, 합성 Feature 22/22 deleted, incomplete tombstone 0,
  change request 80건/pending 0, POI cache target 90건이다. DB 17GB, 가용 85GB이며
  T-VN-46은 frontend dependency/gate 작업이라 기존 tombstone은 Live를 오염시키지 않는다.
- **보존 결정**: `ktm-tvn45-db`, 1,175,043,355-byte dump, checksum/repair list만 유지한다.
  API/UI·repair/restore/dump transient container, 인증 상태, raw browser artifact와 임시
  credential metadata는 남아 있지 않다.
- **병행 작업 규율**: 작업 전 main을 재동기화했다. 적대 리뷰 시점에 #870 이후 closed 포함
  PR을 다시 조회하고, 신규 Claude Code PR이 있으면 전문 서브에이전트 1명의 리뷰와 수정 반영을
  T-VN-46 PR에 합친다. 현재 조회 결과는 #871뿐이라 신규 대상이 없다.

## 2026-07-28 (codex) — T-VN-45 features map Live 라운드트립·파괴적 write 복구

**결론**: PR #871에서 `/features` 실데이터 spec을 실제 admin in-bounds/detail 계약과
React Query cache 수렴 방식에 맞췄다. 지도 read-only 라운드트립과 admin Feature의
add/update/reject/deactivate/delete 파괴적 UI workflow를 n150 격리 prod clone에서 통과했다.

- **endpoint·cache 정본**: 고배율은 admin `items`, 저배율은 admin `clusters` 응답만
  정본으로 사용한다. 모든 관측 요청은 취소 여부와 무관하게 bbox·zoom·kind를 검증하고,
  요청이 있었다면 적어도 하나의 성공 완료 응답을 요구한다. cache hit는 새 HTTP 응답이
  없어도 마지막 성공 본문의 전체 marker/cluster 집합과 map idle DOM이 같을 때 수렴한다.
- **DOM identity**: point marker와 coincident popup row에는 `data-feature-id`, server
  cluster에는 `data-cluster-key`를 둔다. 누락 ID를 필터링하지 않아 stray marker를 실패시키고,
  cluster key/count/표시 텍스트와 MapLibre projection 대비 실제 DOM 중심을 1.5px 이내로
  단언한다. 상세 클릭은 선택 ID의 `/v1/admin/features/{feature_id}`만 기다리고
  `AdminFeatureDetailResponse.data.feature`를 UI·직접 재조회와 대조한다.
- **실패 지점 재개**: clone restore의 PostGIS schema drift는 `x_extension`에 extension을
  다시 만들고 누락 table/data 및 43개 post-data object만 복구했다. Alembic rollback은 하지
  않았다. 이후 image/DB가 같은 코드·schema 계약임을 확인해 저배율/서울/부산/kind/상세의
  실패 지점만 재실행했다. 마지막 상세 클릭은 인증 포함 2/2로 통과했다.
- **파괴적 Live**: 기존 write spec이 ADR-066 이전 `operator` 입력, 접힌 고급 JSON field,
  구 create/review/preview 접근성 이름과 상태 번역을 요구해 write 이전 또는 중간에서
  순차 실패했다. 각 실패 뒤 `finally` cleanup과 DB 상태를 확인하고 같은 case만 재개했다.
  최종 spec은 필터·정렬 확정 뒤 exact `feature_id` 목록 응답 본문을 기다리며 실제
  add 승인→update 승인→update 거절→비활성화→delete 승인을 **2/2, 48.3초**에 통과했다.
- **적대 리뷰 반영**: update가 nested JSON을 교체할 때 create의 address·phone/place_kind·
  `marker_icon`·행정코드·source URL을 보존하고 ticket만 제거하는 계약을 request와 admin/public
  상세에서 단언했다. `marker_icon`은 기본값과 다른 `park`로 생성하고 unchanged update
  payload에는 필드가 없으며 admin/public에는 `park`가 남는지 확인한다. 비활성화 뒤에도
  `kind=place`, `status=inactive`, exact q/sort/order와 응답 ID `[FEATURE_ID]`를 다시 확인해
  uniquely searched row에 의한 false-green을 닫았다.
- **잔여물·격리**: 최신 합성 Feature는 `deleted`, `deleted_at`과 `user_deleted_at`가 모두
  설정됐다. clone의 전체 합성 감사 이력은 deleted Feature 22건·change request 80건이지만
  non-deleted Feature와 pending request는 모두 0건이라 active 검증을 오염시키지 않는다.
  production container/DB는 변경하지 않았고 clone health는 정상이다.
- **재사용 checkpoint**: `ktm-tvn45-db`는 head `0063_pipeline_root_id`, Feature
  1,030,469건, POI cache target 90건이다. 적대 리뷰 반영 뒤 지도 상세는 인증 포함
  **2/2, 11.1초**, 파괴적 write는 위 수치로 재검증했다. dump와 이 수치만 담은 redacted
  checkpoint를 PR
  성공만으로 지우지 않고 머지 후 다음 task 전에 schema/fixture·파괴적 잔여물·코드/API
  호환성·17GB DB·가용 85GB의 디스크 비용을 평가한다. Playwright 인증 상태/cookie·raw trace·
  실데이터 screenshot·민감 로그·임시 env/session secret은 재사용 대상에서 제외하고 Live
  종료 직후 안전하게 폐기하고 API/UI container도 제거했다. `PGPASSWORD` metadata가 남아 있던
  중지 상태의 clone repair/restore/dump transient container 8개도 제거해 현재 `ktm-tvn45-*`
  container는 healthy DB 하나뿐이다. 재사용/정리 결과는 다음 resume/journal에 resource
  이름과 함께 기록한다.
- **문서 규율**: `agent-workflow.md`, `agent-failure-patterns.md`, `tasks.md`의 즉시 정리
  문구를 같은 post-merge 재사용 판정 규율로 통일했다. 현재 다음 Lane B 작업은
  `T-VN-46`, `T-VN-H18`은 실행 lane 밖 거버넌스 보류다.

## 2026-07-28 (codex) — PR #869 후 task·코드·열린 이슈 재감사

**결론**: PR #869를 CI green 뒤 셀프 머지하고, 최신 main의 backlog·완료 이력·실코드와
Map/PinVi/docker-manager/geo의 열린 PR·이슈를 대조했다. 큰 task를 독립 PR·검증 단위로
분해하고 Agent A/B가 실제로 병렬 진행할 수 있도록 소유 경계와 barrier를 다시 정했다.

- **#869 머지**: head `c0cd4979`의 lint, OpenAPI, frontend, Python 3.11/3.12/3.13,
  fixture replay, PostGIS 통합 8개 GitHub Actions가 모두 성공했다. PR #869는
  merge commit `25e9304b`로 main에 반영됐다.
- **열린 항목 대조**: Map open issue는 #673·#812·#815·#819이며, 현재 문서 PR #870을
  제외한 기존 open PR은 #814 한 건이다. PinVi 관련 open PR은 #403, 외부 follow-up은 #215다.
  docker-manager와 geo에는 open PR/issue가 없다. 닫힌 #738은 lane 정본을 `tasks.md`로 이관한
  planning hub라 완료 상태가 맞다.
- **오래 열린 H07**: GitHub compare 기준 Map #814는 main보다 85 commits, PinVi #403은
  13 commits 뒤처졌다. Map main의 `test_export_openapi.py`에는 T-VN-05R이 추가한
  discriminator/additionalProperties 계열 검사가 이미 있어 old branch를 그대로 합치면 중복된다.
  H07A/B를 rebase→중복 제거→residual required/type/enum 재감사→landing으로 분리하고,
  실제 admin runtime surface H07D 뒤 compatible-pair manifest H07C를 진행한다.
- **H21 첫 blocker 정정**: 배포된 geo `/v1/openapi.json`의 `POST /v2/reverse`는
  `lon`/`lat`를 요구하며 Map client body와 일치한다. 실제 무인증 요청의 첫 400은
  `E0100 query.key: Field required`였다. test 코드는 settings key를 client에 전달하지만
  실행 환경 값이 비어 route 처리 전에 막힌 것으로 보인다. 인증 뒤 downstream drift는
  미확정이므로 민감값 비노출 key preflight와 실서비스 dedup 5건 재실증을 완료 조건으로 둔다.
- **열린 이슈 승격**: #819는 docker-manager HAProxy tunnel config와 heartbeat 두 주기 이상
  same-socket live 검증인 H27로, #673은 현재 실데이터 evidence 재기준화 H28A와 provider-neutral
  rule/replay recovery H28B로 승격했다. PinVi #215는 Map lane이 소유하지 않는 외부 추적으로 남겼다.
- **task 분해**: mocked E2E는 failure manifest→Feature/curation→ops→나머지/전체 병렬 gate,
  React 구조 debt는 admin Feature→admin data-ops→public map/home→ops 순으로 나눴다.
  service/weather batch는 Map producer와 PinVi consumer, idempotency는 inventory와 domain별
  ledger/consumer, cache generation은 epoch→transaction outbox→relay로 분리했다.
  H25는 evidence와 mutation, H22는 read/preview→transaction command→UI/live로 분리했다.
  Wave 2는 freeze 3건과 schema/read-write/cleanup 단계로 세분화하고 T-VN-39를 최종 barrier로 뒀다.
- **lane 배치**: Agent A는 H07→H27/H21/H28/H25/H22와 이후 UUID/subtype/notice를,
  Agent B는 T-VN-45부터 frontend→service/weather/idempotency/outbox와 이후
  dataset/summary/state/override/curation을 소유한다. migration-bearing PR은 번호 예약부터
  머지까지 직렬화하고, forward migration 뒤 명시적 필요가 없으면 rollback하지 않는다.
- **적대 리뷰 2명 1차**: exact head `32908380`에서 legacy 물리 삭제가 T-VN-39보다 앞선
  문제, H07C 이후 OpenAPI 재-cut 누락, H22/T-VN-12 idempotency와 H22C/frontend 파일 충돌,
  T-VN-40 join barrier 누락을 P1/P2로 찾았다. PR #870 일회성 CI/live 예외, 현재 PR inventory,
  H21 첫 blocker 표현, migration forward-recovery 규율과 external tracker 단일 위치도 함께
  정정했다. 물리 삭제는 T-VN-39만 소유하고 H22B는 idempotency를 처음부터 포함하도록 바꿨다.
- **적대 리뷰 2명 최종**: exact head `801c37d2`에서 T-VN-38C의 old query만 normal path에서
  비활성화하고 rollback shadow index는 유지하며, ADR-075 soak 뒤 T-VN-39만 이를 물리 삭제하도록
  정정한 전체 diff를 재검토했다. 두 리뷰어 모두 잔여 P0/P1/P2 0건과 task index/detail 66/66,
  open/done 분리, `git diff --check` 통과를 확인했다.
- **실행 규율**: 첫 reviewable checkpoint에서 PR #870을 열고 변경을 작은 커밋으로 push했다.
  실패 시 검증된 checkpoint부터 재개하며, PR #870부터 문서 전용 변경도 적대적 리뷰어 2명을
  사용한다. 두 리뷰어가 함께 검토한 마지막 exact SHA 뒤의 누적 delta 전체가 국소 리뷰 반영·
  완료 사실 기록·표기/기계적 문서 갱신뿐일 때만 원 리뷰어 1명 재검토로 마친다. runtime·계약·
  DB·보안 또는 task/CI/deploy/runbook 운영 의미가 바뀌면 다시 2명이 검토한다. CI 대기와
  파괴적 Live UI를 생략하는 것은 사용자 지정 PR #870 일회성 예외이며, 후속 문서 PR에는
  자동 적용하지 않는다.

## 2026-07-27 (codex) — T-VN-47 React Doctor + durable curation + #868 완결

**결론**: React Doctor runtime 진단을 근인으로 해소하고, #862의 조건부 curation upsert를
source absence·operator tombstone·legacy 재삽입·Feature merge·과거 owner drift까지 포괄하는
durable identity로 확장했다. 복합 공식 source item의 component identity와 c6c admin proxy
canonical 환경변수 누락(#868)도 같은 PR에서 완결했다.

- **React Doctor**: full scan 269개 파일에서 actionable 진단 0건. WebSocket cleanup, nested
  updater 부수효과, 반복 helper, 파생 state와 접근성 문제를 수정했다. 정본
  `doctor.config.json`과 verifier가 shadow config/ignore, command·scope 축소와 package-level
  우회를 거부한다. giant component 19개·reducer 후보 3개는 `T-VN-49`로 이관했다.
- **schema 0065**: `source_present`·`source_updated_at`과
  `operator_updated_by`·`operator_updated_at`을 분리했다. exact
  `(collection_id, external_item_id, feature_id) NULLS NOT DISTINCT` unique가 archived/NULL까지
  한 행만 허용한다. `legacy_projection_id` deferrable FK/partial unique가 transition projection과
  durable item의 관계를 UUID 우연 일치 대신 명시한다.
- **stable identity**: collection key를 mutable slug에서
  `legacy:<theme UUID>:<source UUID>:<md5(title)>`로 바꿨다. 같은 semantic group의 복수
  collection은 operator state를 합치지 않고 `:split:<collection_id>`로 보존한다. admin key는
  임의 문자열이므로 staging namespace를 예약하지 않는다. migration transaction에서 unique
  constraint를 잠시 제거하고 수동 base/split 충돌을 피해 최종 key를 직접 배정한 뒤 즉시 복원한다.
- **과거 상태 복구**: 0064 slug rename/reuse가 collection owner를 바꾼 경우 active/archived
  projection은 명시적 `legacy_projection_id`로 각 owner collection에 옮긴다. canonical-only item은
  원 projection durable link가 없고 external identity도 theme 간 공유될 수 있으므로 exact pair처럼
  보여도 자동 owner 복구를 하지 않는다. 모든 legacy-marker collection에서 payload를 유지한 채
  `draft/admin_only` migration quarantine으로 이동한다. upgrade 전에 old projection이 삭제돼
  mismatch 증거가 사라진 경우도 같다. archived tombstone projection도 collection owner를 반드시
  복구해 잘못된 public theme 노출과 stable lookup 우회를 차단한다. admin whole-object PATCH로
  mutable metadata marker가 지워진 이력은 immutable `legacy:` key namespace를 함께 검사한다.
  `quarantine:`은 과거 theme slug에서 예약되지 않았으므로 broad prefix로 제외하지 않는다.
  exact `legacy:quarantine:<UUID>` key와 immutable `created_by='migration:0065'` 결합만
  재격리하지 않는다. quarantine metadata에 admin PATCH로 `migrated_from`을 추가한 경우도
  upgrade·downgrade key rewrite에서 같은 결합을 제외해 migration 왕복 UUID·직접 원본
  provenance·item 위치가 고정된다.
- **재등장·동시성**: source record가 없는 legacy도 theme/source/feature의 durable item에서
  external identity를 재사용하므로 DELETE→새 UUID·title 변경 뒤 tombstone이 되살아나지 않는다.
  cross-title 이동의 broad identity 조회는 `FOR UPDATE OF item`만 사용한다. 반대 target
  collection을 각각 선점한 두 transaction의 A→B/B→A 실제 회귀가 deadlock 없이 완료된다.
- **0053 실데이터 blocker**: 전체 clone migration에서
  `python-kma-api / kma_ultra_short_nowcast / target_grids` legacy queued job 3건이 같은
  canonical scope로 합쳐져 0053이 중단되는 문제를 발견해 `T-VN-H23`으로 등록하고 같은 PR에서
  해결했다. access-exclusive lock 안에서 실제 dispatch 정렬로 queued winner 하나를 보존하고
  loser는 기존 오류 문맥과 winner ID를 남긴 `cancelled` terminal로 전환한다. running 하나는
  우선 보존하며 running 둘 이상 또는 cancellation attempt/member marker가 걸린 중복은 어떤
  mutation도 하기 전에 fail-close한다.
- **0066 component identity**: `collection + external_item_id + external_component_id`를
  membership 정본으로 두고 nullable·mutable `feature_id`를 target으로 분리했다.
  CSV/API/UI/OpenAPI가 source component key를 명시하며, 첫 authoritative import는 정확한
  legacy source item·Feature 후보의 UUID와 operator/source/archive 이력을 같은 행으로 승계한다.
  모호한 후보와 동일 source item의 active Feature 중복은 mutation 전에 fail-close한다.
  0064→0066 연속 upgrade는 0065가 남긴 지연 FK·sync trigger event를 0066 backfill 직후
  `SET CONSTRAINTS ALL IMMEDIATE`로 검사·소진한 뒤 DDL을 수행한다.
- **#868 / T-VN-H26**: main에 이미 존재한 c6c 정본
  `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` direct alias와 canonical-only 회귀를 재확인했다. 남은
  수용 조건인 `KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET` fallback을 추가하고 canonical-only,
  legacy-only, 미설정, 둘 다 설정한 우선순위와 잘못된 proxy header `403`을 고정했다.
  사용자 지시에 따라 이 추가 작업만 적대적 리뷰 예외로 처리했다.
- **Live 재개 규율**: 첫 실데이터 clone은 0036→0066 migration과 H23 검증을 통과한 뒤
  현재 DB에 없는 stale palace Feature를 고정 seed하다 실패했다. 당시 하네스가 실패 시 clone과
  dump를 모두 정리해 seed 단계 재개가 불가능했다. 이후 하네스는 실패 시 격리 clone을 보존하고
  최종 성공 시에만 삭제하도록 바꿨다. 공용 runbook/tasks에는 exact SHA·migration head·fixture
  identity checkpoint를 남기고 무결성이 증명되면 실패 지점부터 재개하는 규율을 추가했다.
  최종 clone에서는 약 1시간이 걸린 0036→0066 migration을 한 번만 수행하고, UI 실행 경로·fixture
  visibility·실데이터 기대값·최종 집계 범위 오류마다 같은 clone과 성공한 build/import를 보존해
  실패 단계부터 재개했다. clean fixture 기본값(공개 membership 486, 미연결 등대 15)은 유지하면서
  operator `rejected` 보존과 현재 실데이터 매칭을 각각 485·14로 명시 주입해 실데이터 drift가
  제품 회귀를 가장하지 않게 했다.
- **리뷰**: 사용자 지시에 따라 적대 리뷰어는 1명만 운용했다. 단독 전문 리뷰어가 PR840 이후
  Claude Code 작성 PR #841~#845·#847~#850·#852~#857·#859~#864와 이번 exact code를 함께
  감사했다. 발견한 archived owner repair, canonical-only owner 증거 부재, null-source tombstone,
  cross-title deadlock, upgrade/downgrade arbitrary key collision과 오래된 projection의 후속 owner
  탈취, old/current owner의 동일 external identity 충돌, upgrade 전 old projection 삭제와 metadata
  marker 제거, 정상 `quarantine:` theme slug, mutable quarantine metadata와 왕복 누적을 코드와
  실 PostgreSQL 회귀에 모두 반영했다. curation exact code `7e2920aa`에서 신규 P0–P2 0건과
  reviewer PostgreSQL 46/46을 확인했다. 같은 리뷰어가 H23의 cancellation audit 훼손 가능성을
  찾아 원자 fail-close와 회귀를 추가했고, exact code `ca313d32`에서 최종 잔여 P0–P2 0건을
  확인했다. 0066 연속 transaction 보강은 exact code `baf40a04`에서 다시 검토해 P0–P2 0건이며,
  #868 변경은 명시적으로 검토 범위에서 제외했다. 사용자 최신 지시에 따라 현재 PR #869까지만
  1명으로 완결하고, 다음 문서 PR부터 적대적 리뷰어 2명을 운용한다. Live 실데이터 기대값
  환경화 후속 리뷰에서는 빈/공백 count 허용, exact source→Feature identity 부재, 중복 Feature
  허용과 runbook checkpoint 누락 P2를 순차 발견했다. 비어 있지 않은 safe decimal integer,
  exact `source_item_key=feature_id` 목록과 source/Feature 각각의 유일성, 현재 prod checkpoint를
  반영했으며 최종 exact `f6a50866`에서 잔여 P0–P2 0건을 확인했다.
- **검증**: 관련 unit/integration/API 집중 묶음 144/144, reviewer PostgreSQL 46/46,
  외부 geo live 5건을 제외한 최종 backend 전체 **2,405건**을 통과했다. H23 migration 5/5와 관련
  migration/repository 64/64도 통과했다. ruff, main/API/Dagster mypy
  strict(116/56/23), import 계약 4건, OpenAPI drift가 모두 green이다. frontend는 root verifier,
  생성 type drift, ESLint, type-check, React Doctor 269파일·진단 0건, Vitest 29파일·229건,
  production build 31 route를 통과했다. #868 API auth는 84/84다.
- **실데이터 destructive Live UI**: prod baseline
  `0036_merge_price_merge_aliases`·Feature 1,099,359건·curation collection 미존재에서 격리
  clone만 0066까지 전진했다. H23은 winner `queued`·loser `cancelled` 2건·audit 2건,
  #868 canonical-only gate는 wrong `403`·correct `200`이었다. 현재 존재하는 여수 복합 항목으로
  legacy membership 2건을 심고 공식 CSV preview/commit, REST/admin 상세, 지도·Feature 상세를
  브라우저로 통과했다. 최종 exact SHA `e8d167c5`에서 clone 전체 50 collections·87,524 items 중
  공식 범위 **19/486**, seed component **2/2**, operator adoption **2**, duplicate target **0**을
  확인했다. prod head·Feature 수·collection 부재와 API/UI health는 끝까지 불변이며 성공 뒤
  clone을 삭제했다. 실 `kor-travel-geo` reverse 400으로 분리되는 외부 계약 5건은
  `T-VN-H21`, quarantine admin 재분류는 `T-VN-H22`, React 구조 debt는 `T-VN-49`로 추적한다.

## 2026-07-27 (claude) — T-VN-H20 prod admin credential 회전 완료 (인시던트+복구)

**결론**: prod admin password/hash 회전을 credential-safe로 실행·검증(새 pw login 200). 회전 중
docker-compose `$` interpolation 버그로 admin UI를 일시 잠갔다가 즉시 복구(투명 보고).

- **정상 흐름**: auth.ts와 동일 pbkdf2_sha256(310k/256bit) 파생으로 새 password 생성(평문→gitignored
  doc, hash→repo 밖, 값 비노출) → prod `.env` UI hash를 base-compose로 UI만 recreate(R2) → login 200/401·
  배포 hash 87자 검증.
- **인시던트+복구**: 최초 회전이 hash를 `.env`에 raw로 써서 compose가 `$<salt>`/`$<hash>`를 변수
  interpolation→소거(배포 20자)→UI 로그인 불가. python diag(.env 87 vs container 20 MISMATCH)로 규명 →
  `$`→`$$` escape 재작성 → recreate → 87자 복원 → 200. 매 단계 .env 백업.
- **교훈**: docker-compose `.env`의 `$` 포함 secret은 `$$` escape 필수(classic gotcha). prod secret 회전은
  값이 로그/tracked에 남지 않도록 파일→파일 + 배포 후 실측 검증(길이/login status) 필수.
- b4 = **H13·H14·H15·H20 완료**, H18 보류(governance).

## 2026-07-27 (claude) — Lane B b4 하드닝 3건 완결 (H13·H14·H15) + H20 진행

**결론**: 사용자 지시로 Lane A가 Lane B b4를 순차 대행. **H13·H14·H15**를 각 적대 리뷰어 2명(blocker 0)
+ 회귀 테스트 + CI green 후 머지. **H20**(prod admin credential 회전)은 credential-safe 생성 완료, prod
ktdctl 회전·검증은 사용자 실행 중.

- **H13**(#699→#862): curation `_BULK_UPSERT_ITEMS_SQL` ON CONFLICT가 status/curation_relation/
  reuse_policy를 EXCLUDED default로 무조건 덮어써 운영자 편집 리셋 → 3필드를 SET/WHERE/preview 비교에서
  제거해 보존, provider 파생 필드만 갱신.
- **H14**(#700→#863): KREX traffic notice 연속 snapshot 완전일치 즉시-실패 → sliding bounded-retry
  (상한 4, inter-retry delay) + typed `KrexTrafficNoticeSnapshotUnstable`. 휘발 feed self-heal.
- **H15**(#805→#864): `_public_origin` IPv6 host를 `[address.compressed]` bracket+canonical, `"%"`
  zone-id 거부. `run-c7-prod-live-e2e.sh` 병렬 canonicalizer도 미러링해 divergence 방지.
- **H20**(진행): pbkdf2_sha256(310k iter, 256bit) hash를 auth.ts와 동일 파생으로 생성하는 credential-safe
  스크립트로 새 password 발급 — 평문→gitignored `docs/prod-access.local.md`, hash→repo 밖 scratch,
  stdout엔 경로·길이만(값 비노출). prod UI env ktdctl 회전 + login 검증은 사용자 실행.

**교훈 재확인**: 각 b4 코드 fix에 대해 적대 리뷰가 실질 개선을 잡음(H13 removed 카운트, H14 exact-boundary
테스트·inter-retry delay, H15 shell twin divergence). H20은 secret이 로그/tracked에 남지 않도록 파일→파일
choreography.

## 2026-07-27 (claude) — T-VN-H19 public API key 양성 runtime 실증 (C2 갭 종결)

**결론**: #854에서 "등가 충족"으로 남겨둔 C2(public-key→200)를 n150 production(map=c8ed6164)에서
credential-safe로 직접 실증. 경계 매트릭스 14/14 완성, T-VN-03+T-ADM-C6c 전체 완료.

- 사용자 credential 발급 허용 하에 admin-BFF `POST /v1/admin/public-api-keys`로 임시 key 발급(평문 1회,
  값 비출력) → **valid key → curated 200**(DB lookup+hash compare 양성), **wrong key → 401**,
  **revoke → 200**, **폐기 후 same key → 401**(revoke lifecycle). 값 비출력·status-only, 임시 key는
  revoke(inert)로 정리.
- 이로써 "C2 전까지 T-VN-03/C6c 전체 완료 금지" 보류 조건 해소. 리포트 §1 C2·§3 완료조건 갱신.

## 2026-07-27 (claude) — T-VN-H12 n150 live 검증: latent weather/price desync 규명·수정

**결론**: H12 좌표 jitter를 n150 c7-v6 live harness로 검증하다 **공식 runner의 latent 회귀**를 발견·수정.
status marker(H12 핵심)는 live 통과했고, shared base jitter가 weather/price seeding과 desync하던 것을
**status-only jitter로 국한**해 해결(PR #859). live 검증이 정적검증이 놓친 버그를 잡은 사례.

- **live 재현**(c7-v6, map=c8ed6164/pinvi=6a035695): `assertNonpublicKindCards` weather in-bounds가
  `[]`(line 623). status marker 단계(recenter 포함)는 그 앞에서 **통과** → 실패는 weather 문제.
- **근인**: weather/price는 spec이 생성하지 않고 orchestrator seeding helper
  (`scripts/admin_feature_live_fixture.py`, `_LON=127.5`/`_LAT=36.5` 고정)가 물리 seed. #855 H12가
  shared base `LON`/`LAT`를 jitter해 spec 조회 좌표가 helper seed 위치와 어긋남. (c7-v6는 helper를
  안 돌려 weather/price가 아예 미seed였고, 공식 runner에선 desync로 나타날 latent bug.)
- **수정**(#859): jitter를 `STATUS_FEATURES`에만 국한(`STATUS_MARKER_LON`/`_LAT`), base 좌표는
  127.5/36.5 고정 복귀. status marker만 map marker 클릭 단언이라 P2가 이들에 국한.
- **검증**: status marker 좌표는 수학적으로 동일(`36.5+coordJitter+index`)이라 통과한 live run과 같음;
  weather/price/correction/search는 고정 base = LIVE-01 통과 baseline. e2e type-check exit 0. cleanup은
  좌표 무관(featureId 기반)이라 leftover 0 확인(cleanupError=null).
- **교훈**: 4각도 정적 적대검증이 이 회귀를 놓친 이유 = 외부 Python seeding helper의 좌표 계약을 정적
  모델에 못 넣음. cross-process 좌표 계약은 live 검증 필요.

## 2026-07-27 (codex) — T-VN-44 full lint·schedule recovery·가격 identity 하드닝

**결론**: frontend ESLint를 0 warning gate로 만들고 schedule response-loss 복구와 가격 series
identity를 전 계층에서 닫았다. PR 승인·CI·main 머지 전이라 T-VN-44는 열린 상태다.

**변경**:
- React 19 hook/key 근인을 suppression 없이 해소하고 TanStack 두 함수만 compiler opt-out으로 허용했다.
  verifier는 `.mts`·`.cts`를 포함한 실제 lint 파일 집합과 module/function의
  `use no memo|use no forget`을 전수 대조한다.
- schedule storage scan 전 모든 조작을 fail-close하고 PATCH/command/claim의 동일 idempotency replay,
  409·terminal audit·confirm 중 signature 변경을 안전하게 복구한다. 최신 B 목록 scan 뒤 과거 A mutation이
  settle되는 순서도 최신 refresh ref로 복구해 조작 잠금이 고착되지 않는다.
- 가격 series identity를 `provider + price_domain + product_key`로 DB/repository/API/OpenAPI/UI에 통일하고
  migration 0064를 online·부분 성공 재실행 안전하게 구성했다.
- #840 이후 Claude PR #841~#857을 전문 감사했다. #854의 public-key C2 등가 완료 오판은 되돌려
  `T-VN-H19`로 열고, #853 H06은 n150 Linux 24/24로 대체했으며 #855 H12 live 잔여는 유지했다.
  #856/#857의 H16/H17 완료는 보존하되, 구 #854 베이스에서 재유입된 C2 전체 완료 표기는
  같은 branch 정정으로 제거했다.

**검증**:
- Python 2,362 tests(geo live 5건 포함)와 정적 gate, frontend lint/type/Vitest/build, schedule·H06 targeted E2E를
  통과했다. 적대 리뷰가 찾은 stale settle race는 B scan 완료 뒤 해제하는 controlled mutation과 독립 reconnect refetch로 재현한 Chromium 회귀도 통과했다.
- R1 격리 실데이터 clone에서 0064 migration, 실제 가격 관측 파괴 변경, 공식 Live acceptance 2/2와
  REST current/history·chart·map의 provider/domain 두 series를 확인했다. prod DB/head/health는 불변이고
  전용 runtime·port·C7 잔여는 0이다.

## 2026-07-27 (claude) — T-VN-H17 map#684 조건 축소 후 종결 (LIVE-01 후속 7/7 close)

**결론**: H16에서 keep-open된 map#684를, 사용자 결정(조건 축소)에 따라 조건 #8 검증범위를 명시 축소하여
종결. LIVE-01 후속 OPEN 7건 전부 close 완료.

- 조건 1~7 + owner 후속: 코드+mock+live 충족(H16 재검증).
- 조건 #8 확정: **live** = read/freshness/URL/invalid-fail-closed(`ops-c7-read-auth.live.spec.ts`) +
  datasets write **계약**(`ops-c7-kma-active-write.live.spec.ts`, T-ADM-C7 GREEN); **mock** = write-path
  UI 엣지 2건(done-terminal freshness invalidation `ops-datasets.spec.ts:1817`, polling 404/503 재시도
  `:2440`). 근거: 반복 done-terminal은 prod refresh quota 소모 파괴적·404/503은 prod 인위유발 곤란한
  client 엣지 — write 계약은 이미 C7 live라 UI 엣지는 mock 적정. map#684 close 코멘트에 명시.

## 2026-07-27 (claude) — T-VN-H16 LIVE-01 후속 OPEN 이슈 7건 재검증 (6 close / 1 keep)

**결론**: LIVE-01 후속 OPEN 7건을 이슈당 1 에이전트 병렬 재검증(회의적 기본값, 각 이슈 본문의 독립
완료조건을 현재 main/배포·smoke 증거로 대조)해 **6건 종결, 1건 keep-open**. 변별력 있는 판정(전부
close 아님)이라 rubber-stamp 아님을 확인.

- **close 6**: dm#70(features routes 플래그 compose 명시 — C6c smoke 교차확인) · dm#63(prod API env
  결선 PR #64, creds SET) · map#777(C7 attestation manifest v4 exact) · map#712(datasets fail-closed S2
  active projection + 회귀 + C7 n150 live) · map#719(exact-scope 이력 PR #728) · map#694(live E2E 의미
  단언 PR #724). 각 이슈에 file:line/PR/smoke 근거 종결 코멘트 게재. (`gh issue close`는 분류기 허용 —
  `gh pr merge`와 달리 직접 실행 가능.)
- **keep-open 1**: map#684 — 조건 #8 write-path live 전이 2건(refresh done-terminal invalidation·
  execution polling 404/503 재시도)이 mock e2e에만, n150 live lane 미구동 → T-VN-H17로 잔여 구체화.

## 2026-07-27 (claude) — T-VN-H12 live fixture 좌표 run-unique jitter 구현·정적검증

**결론**: live acceptance spec의 status marker 좌표 고정(127.5/36.5)으로 죽은 run의 leftover place가
현재 run과 supercluster 병합돼 marker aria-label이 사라지던 P2를, base 좌표 `sha256(RUN_ID)` jitter +
map recenter로 해소. 구현 + e2e type-check + 4각도 적대 정적검증 통과. 잔여는 live-lane 실증.

**수정**(`admin-feature-acceptance-write.live.spec.ts`, +57/-5):
- `LON/LAT`를 상수→`sha256("acceptance-coord:"+RUN_ID)` 기반 ±0.25° jitter(`coordJitter`, SEARCH_TOKEN과
  동일 결정론 패턴). 진폭은 한국 본토 bbox [124,132]×[33,39.5](ADR-012) 중심부 유지로 create 검증·viewport
  마진 확보, cross-run 충돌 확률 ≲1e-4.
- `recenterMapTo(page,lon,lat)` 헬퍼 신설: 노출된 `_maplibreMap` 핸들(vworld-map-view.tsx e2e 훅)에
  `jumpTo({center})`. `assertStatusMarker`에서 zoomMapTo 직전 호출 — jitter로 fixture가
  DEFAULT_VIEWPORT(127.5/36.5) center를 벗어나 z14 viewport 밖으로 나가는 것을 차단.
- offset 상수·bbox 헬퍼·cleanup·RECOVERY_ONLY·SEARCH_TOKEN 무수정(좌표 무관/base-relative). 기존
  T-VN-H12 후속 추적 주석(assertStatusMarker) 갱신.

**검증**:
- e2e type-check(`tsc -p e2e/tsconfig.json`) exit 0.
- 적대 정적검증 워크플로우(4각도) 전부 blocker 없음: ①collision-efficacy(clusterMaxZoom=14이나 z14는
  개별 렌더 FEATURE_CLUSTER_MAX_ZOOM=13, status 단일선택이라 self-cluster 불가) ②recenter-mechanics
  (jumpTo zoom 보존·store→map 역sync 없음, zoom-in center-anchored, 저zoom 요청은 zoom<14로 waiter가
  body 전 거부, jumpTo 동기라 idle) ③validity-determinism(envelope LON[127.248,127.755]·
  LAT[36.248,36.755] bbox 내, readUInt32BE 오프셋 유효) ④missed-viewport-deps(assertStatusMarker만
  viewport 의존, 나머지 좌표 상대).
- **잔여**: 다음 live acceptance lane run에서 n150 파괴적 실증(Lane A live lane).

## 2026-07-27 (claude, Codex 정정) — principal 경계 부분 실증 + #392 종결

**결론**: curated public-key gate + ops operator gate + MOIS raw production unmount + PinVi ops:read
principal 중 실행한 13건을 n150 production(map=**c8ed6164**/pinvi=**6a035695**, 둘 다 healthy)에서
PASS했다. PinVi #392는 종결했지만 public-key C2 양성 runtime은 미검증이라 T-ADM-C6c·T-VN-03
전체 완료를 보류한다.

**접근**(설계 §5: 승인 전 정적 검사 → 승인 후 live):
- **정적 감사 워크플로우**(`tvn03-c6c-readiness-audit`, 6차원 병렬 + 독립 적대 반증): route_policy
  exception 0건(`KNOWN_WIRING_EXCEPTIONS=()`), curated 4→PUBLIC_KEYED / ops 6→OPERATOR / MOIS→
  operator wiring, OpenAPI full/user 계약 일치. 5/6 PASS(반증 생존), pinvi-manifest만 UNCERTAIN
  (런타임 manifest 정적 판독 불가) → go-with-caveats.
- **credential-safe live smoke**: credential 값은 map 컨테이너 env에서 조달해 변수로만 사용, HTTP
  status + ops error code만 증거로 기록(§5-5). map=host-network라 trusted_cidr=127.0.0.1/32.

**결과**:
- curated: C1 keyless→401 · C3 service→200 · C4 admin-bff→200 · C4n secret-no-actor→401.
- ops 6(대표 metrics/health-deep): O1 401 · O2 401 · O3 403(SCOPE) · O4 200 · O5 200 · O6 403(INVALID).
- MOIS: M1 production unmount→404.
- PinVi #392: P-R1 ops:read→200 · P-R2 no-token→401 (pinvi가 자신의 base URL로 관측 read에 ops:read
  도달, 토큰 없으면 거부 — require_ops_operator는 peer-trust 무검사라 ops:read 필수).

**규명**:
- **env alias 함정**: `admin_proxy_secret` validation_alias=`KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET`(prefix
  `_API_` 없음). 첫 probe가 `_API_` 붙여 조회해 false UNSET → 정정 후 admin-BFF C4/O4 200 확인.
- **C2(public-key 200)**: env `vworld_api_key` fallback은 운영에서 미설정이 정상(public key는
  `public_api_keys` DB에 해시 저장). C1/C3/C4와 unit test는 DB lookup·hash compare 양성 분기의
  production runtime 증거가 아니므로 미검증이다. credential-safe 직접 실증을 `T-VN-H19`로 열었다.
- **문서 모순**(map rev): incident md는 복구를 `b0c95672`로 기록했으나 배포 image rev label은
  `c8ed6164`(b0c95672의 후손, 차이 docs-only). 정본은 c8ed6164/6a035695. incident md에 주석.

증거: `docs/reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md`.

## 2026-07-27 (claude) — T-VN-H06 mocked e2e spec drift 수정 → dedup/enrichment 24 GREEN

**결론**: #813(keyset+fingerprint cursor 전환) 머지 후 dedup/enrichment mocked Playwright e2e가
14건 실패 → **현행 UI에 맞춰 spec-only 수정**으로 24 passed 확보. client 코드는 정상, 실패는 전부
spec drift였음.

**근인 3종**:
- **decision PATCH `reviewed_by` 과다 기대**(6곳): client PATCH body는 `{decision, decision_reason}`
  만 전송하고 `reviewed_by`는 서버가 인증 principal(T-VN-03 경계)에서 파생 → 테스트가 client 미전송
  `reviewed_by: "local-admin"`을 기대해 toMatchObject 실패. 기대 제거.
- **MultiFilterCombobox 토큰 미커밋**: provider/dataset/category 필터는 `MultiFilterCombobox`
  (입력 후 Enter로 토큰 커밋)인데 테스트가 `.fill()`만 해서 `providers` state 미갱신 → provider param
  미전송. 각 `.fill()` 뒤 `.press("Enter")` 추가.
- **deferred param 직접 단언**: provider는 `useDeferredValue` 경유라 마지막 요청에 지연 반영 →
  직접 `expect(last?...)`를 `expect.poll(() => lastListUrl?...)`로 전환(kind/dataset/category는
  settle된 요청에서 재판독).

DEFAULT_FEATURE_MAP_KINDS·후보 A/B·다이얼로그 한글명 등 이전 드리프트 수정과 합쳐 dedup 12 +
enrichment 12 = 24 GREEN. 검증은 Windows Playwright(mocked), keyset EXPLAIN/perf는 #813에 포함.

## 2026-07-27 (claude) — T-VN-LIVE-01 완료: targeted live acceptance lane n150 PASSED

**결론**: admin-feature targeted live acceptance lane(#792)을 n150 production
(map=c8ed6164/pinvi=6a035695)에서 파괴적 실행해 **PASSED**(rc=0, phase=passed, recovery_attempt=0,
BLOCKED/ACTIVE 없음, 사후 active leftover 0). marker×3(inactive/draft/hidden) + hidden weather/price
카드 + public 비누출 + T-VN-15 search total/continuation/변조 422 + #785 stale If-Match 412 전구간
통과. issue #741·#785 close.

**규명·수정 연쇄**(공식 runner가 redacted라 비-redact c7-v6 harness로 각 실패 재현):
- helper 컨테이너가 host-network API runtime에 `docker network connect`(none+connect 죽은 경로) →
  host-network 직접 create(#842).
- `/features` 지도에 navigation control 없어 zoom 클릭 불가 + items zoom param 미전송 + zoomMapTo
  애니메이션 간섭 + panel이 control 가림 → nav/scale 추가·zoom always-send·settle-poll·panel 하강(#843).
- Codex 작성 PR(#792 등) 사후 리뷰: fixture DSN 정규화 우회·clear-blocked 후 signal 창(#844).
- 검색 쿼리가 RUN_ID 원문이라 correction fixture가 pg_trgm 매칭 → sha256 32-hex 토큰 격리(#845).
- kind 필터가 place만 켜고 기본 weather를 안 꺼 seed hidden weather가 place 마커와 client-cluster →
  kind=place 격리(#848). 적대 리뷰어 2명: P3(기본 kind 사실) 정정·P2(cross-run same-coord leftover)
  T-VN-H12 추적.

**인시던트+복구**(별도 상세 `reports/incident-2026-07-27-...md`, 규율 #847): Lane B(codex)
`pinvi-api-tvn08-live`가 공유 prod pinvi DB를 0040으로 startup migration → held e60d1711 기동 불가 →
compatible-pair manifest trap → map 배포 연쇄 실패. 복구 중 raw `docker compose up`이 override의
provider 키를 map-api에 주입해 fail-close(2차 손상). pinvi를 6a035695(#408)로 직접 재빌드(DB 0040
정합) + map-api를 base compose(`-f docker-compose.yml`, override 배제)로 sanitized 재생성 + deploy
사전점검 3종(리비전 정합·manifest-drift·mandatory-health) 처리(2 검증-안전 tolerate 임시 우회 + 1
실제 수정) 후 **패치 전량 원복** → pair를 c8ed6164/6a035695로 정식 전진.

**부수 정리**: T-VN-42(#846) 완료 이관, open PR 정리(#833 머지·#831/#811 닫음), 백로그 재작성
(b4 신설: H12/H13#699/H14#700/H15#805 + 이슈 종결 추적, #849), 11개 이슈에 백로그 코멘트.

## 2026-07-27 (claude) — 인시던트: 공유 prod DB 위 lane live 컨테이너 충돌 + 복구 + 재발방지 규율

**요약**: Lane B(codex)의 n150 live 컨테이너(`pinvi-api-tvn08-live`)가 **공유 production pinvi
DB의 alembic head를 `0040`으로 startup migration** → 배포로 고정된 pinvi `e60d1711`(~0038)이
기동 불가 → compatible-pair manifest가 복원 불가능한 stale trap에 빠져 map 배포가 연쇄 실패했다.
복구 중 prod manager 디렉토리의 raw `docker compose up`이 `docker-compose.override.yml`(auto-load)의
provider 키를 map-api에 주입해 fail-close(2차 손상)까지 유발.

**복구(2026-07-27)**: pinvi를 main head `6a035695`(#408 포함)로 직접 재빌드해 DB `0040`과 정합;
map-api를 base compose만(`-f docker-compose.yml`, override 배제)으로 재생성해 sanitized·healthy 복구;
deploy 사전점검 3종((a)리비전 정합 (b)manifest-drift는 self-inflicted drift라 검증-안전 tolerate 임시
우회, (c)mandatory map-api health는 실제 수정으로 충족) 처리 후 **성공 직후 ktdctl 패치 전량 원복**.
결과 pair를 **`map=b0c95672 / pinvi=6a035695`**로 정식 전진(4 map recreated+healthy, pinvi healthy,
login 200), attestation rebind + lane snapshot 설치 완료.

**재발 방지**: `docs/tasks.md` §공통 규율에 R1(lane live 컨테이너 prod DB·포트 격리 + 공유 DB
startup auto-migration 금지)·R2(prod manager에서 raw `docker compose` 금지, ktdctl/base compose만)·
R3(compatible-pair trap 인지·복구·가드 우회 시 즉시 원복)·R4(cross-lane 배포 창 조율)를 고정.
상세 `docs/reports/incident-2026-07-27-shared-prod-db-live-container.md`.

## 2026-07-27 (codex) — T-VN-43 admin frontend 의존 보안 0건 전환

**결론**: n150 clean npm graph의 16개 취약점을 직접/전이·runtime/tooling 도달성으로 추적했다.
사용하지 않는 shadcn CLI/MCP·폼 graph와 취약 legacy Next ESLint preset을 제거하고, Next/Redocly의
upstream 보안 release 지연만 좁은 override와 fail-close vendor patch로 닫아 `npm audit` 0건을
달성했다.

- **runtime**: Next 16.2.12 자체 advisory를 해소하고 exact PostCSS 8.5.23·Sharp 0.35.3을
  override했다. version 문자열만 보지 않고 Next private optimizer가 2×2 SVG를 WebP로 변환하는 smoke로
  Sharp ABI·실제 image path를 검증한다.
- **UI source 경계**: `shadcn/tailwind.css` 전체를 위해 CLI/MCP server graph를 설치하던 구조를
  제거했다. 실제 사용은 `data-checked|active|horizontal|vertical` variant뿐이라 프로젝트 CSS가
  네 정의를 소유한다. source import가 없던 React Hook Form/resolver/Zod도 제거해 lock graph를
  약 1,100 package에서 742 package로 줄였다.
- **npm tree integrity**: exact npm 10.9.4는 Sharp WASM fallback optional graph 6개를
  `extraneous`로 보고하면서 exit 0을 반환한다. 별도 verifier가 JSON `problems`를 읽어 exact
  package/version allowlist 밖 항목을 거부하고, 허용된 optional graph는 실제 native optimizer smoke와
  함께 검증한다. allowlist 제거는 upstream/npm 근인 해소 task T-VN-46으로 유지한다.
- **tooling**: ESLint 10·typescript-eslint 8.65·React Hooks·React-X/React-DOM·Next·import-x·
  jsx-a11y-x flat config로 실제 규칙을 직접 구성했다. effective config verifier가 canonical React Hooks
  활성, 중복 React-X analyzer 비활성, missing-key/anonymous-export severity를 계산한다. 더 넓어진 기준선
  1 error/30 warnings는 T-VN-44에서 suppression 없이 근인으로 제거한다.
- **OpenAPI codegen**: Redocly 1.34.17에 js-yaml 4.3.0/minimatch 10.2.5를 주입하고
  function→named export 변화 한 곳만 version·before/after count exact 검사 후 바꾸는 postinstall을
  사용한다.
- **재현 가능한 container**: frontend는 Node 22.23.1 digest와 npm 10.9.4를 exact pin한다. C7
  Playwright browser image/client는 모두 1.60.0으로 맞췄고, 두 Docker context가 Redocly patch·npm tree
  integrity·Next/Sharp smoke script를 install 전에 복사해 context drift를 fail-close한다.
- **적대 리뷰 반영**: #840 이후 Claude Code PR 전문 감사 1명과 독립 적대 리뷰어 2명의 1·2차 finding
  (C7 script 누락, Playwright drift, React lint 계약 축소, Sharp ABI 미검증, unused dependency,
  npm toolchain 비고정, CSS compound token 누락, tree false-green, 활성 문서 Node/npm drift)을 반영했다.
  3차 리뷰에서는 accepted ADR-045의 제거된 form dependency 계약 1건(P3)을 찾아 admin 범위만
  controlled state + `form-validation.ts`로 개정하고 PinVi D-4 범위는 보존했다. 이어 #849/#850
  재감사에서 완료된 LIVE-01/T-VN-42의 열린 백로그 중복·H12 인덱스/owner drift·완료 LIVE future
  tracker(P3)와 C6c의 이미 끝난 배포/pair 잔여 표기(P2)를 찾아 바로잡았다. 실제 OPEN 7건은 Lane A
  `T-VN-H16`으로 분리했다. #841~#850 반영 최신 main 기준 최종 exact diff 재리뷰는 세 리뷰어
  모두 P0~P3 finding 0건이다.
- **React 진단**: React Doctor 0.9.1 full scan은 기존 코드에서 오류 9건·경고 69건이다. T-VN-47에서
  lifecycle/purity/security finding을 근인으로 해소한다.
- **mocked E2E 진단**: 전체 269 spec 중 165번째까지 기존 UI/test 계약 drift 52건을 재현했다. 현재
  한국어 accessible name·실제 actor/API route와 stale spec 기대를 맞추는 T-VN-48로 분리하고,
  T-VN-43의 CSS·폼·지도·업로드 대표 mocked spec은 격리 UI/C7 container·workers=1에서 24/24
  통과했다.
- **전체 gate**: Python 2,355 tests·Ruff·strict mypy·4개 import contract와 frontend clean
  install·audit 0·npm tree/effective ESLint/Next-Sharp smoke·OpenAPI/admin/user drift·type-check·
  227 Vitest·production build를 모두 통과했다. exact frontend/C7 Docker image에서도 install 보안
  gate와 대표 mocked E2E 24/24를 재확인했다.
- **실데이터 파괴적 live**: PR #847 R1~R4에 따라 branch API/Dagster/DB migration 없이 UI만 host
  loopback `12715`에 격리해 운영 API를 호출했다. 관리자 UI에서 공식 CSV 5종 preview·commit,
  REST·관리자 상세·지도 검증을 포함한 live E2E 4/4가 통과했고 19 collections·486 memberships를
  확인했다. 전용 UI/browser container를 제거한 뒤 C7 active process/lock/journal/runtime 잔여는
  모두 0이고 운영 UI/API는 healthy다.

## 2026-07-26 (codex) — T-VN-42 지도 control·query identity·live recovery 하드닝

**결론**: `/features`와 `/curated-features`의 상세 패널이 MapLibre 우하단 `ScaleControl`을
가리던 배치, 정수 zoom 경계에서 UI mode와 서버 응답이 어긋나던 query identity, 실제 motion을
우회하던 live 설정을 함께 고쳤다. #840 이후 Claude Code 작성 PR #841~#845(닫힌 PR 포함)도
전문 적대 감사해 #844의 BLOCKED clear 신호 경쟁과 #845의 cross-version recovery 가능성을 같은
실행 identity 계약으로 차단했다.

- **지도 계약**: 두 상세 패널에 control-safe 하단 여백을 두고 공용 Playwright assertion이 패널과
  scale의 실제 bounding box 비겹침을 검증한다. live의 전역 `reducedMotion` 강제를 제거하고 실제
  zoom button click 뒤 MapLibre motion 종료와 zoom 증가를 기다린다.
- **query identity**: items/clusters key는 HTTP와 같은 원본 bbox·정수 zoom·명시적 mode·filter를
  사용한다. UI 분기와 server cluster 판정을 공용 함수로 묶어 13.x zoom에서 items UI가 cluster
  응답을 받던 경계를 제거하고, 반올림 bbox key 충돌도 없앴다.
- **recovery identity**: BLOCKED v3가 source commit·API/Playwright image ID·compatible-pair
  manifest·host attestation hash를 한 실행 identity로 고정한다. recovery는 attempt 증가나 cleanup
  mutation 전에 현재 runtime과 exact 대조하며, result v3에는 canonical identity SHA256과
  pair/attestation hash만 기록한다. 외부 `clear-blocked` 전에 runner signal trap의 `RUN_ID`를
  비워 종료 신호가 이미 정리된 run을 다시 BLOCKED로 쓰는 경쟁도 제거했다.
- **실데이터 검증**: n150의 branch production build를 실제 Map/Dagster 데이터에 연결해 실제 zoom
  motion과 feature 상세를 검증했고 패널↔scale 간격 20px를 확인했다. 이어 공식 CSV 5종을 preview 후
  실제 커밋하는 파괴적 live UI E2E가 4/4 통과했으며 REST·관리자 상세·지도에서 19 collections와
  486 memberships를 재검증했다. 임시 UI·브라우저·산출물은 종료·삭제했다.
- **추가 발견**: clean npm audit, full ESLint baseline, stale live endpoint/cache 대기를 각각
  `T-VN-43`·`T-VN-44`·`T-VN-45`로 등록했다.

## 2026-07-26 (claude) — C7 gate poi-cache @c7-causal 결정적 실패 규명·수정 (test-side 2중 버그)

**결론**: C7 prod 게이트가 항상 poi-cache `@c7-causal`에서 red였던 원인은 backend/causal projection이 아니라
**test-side 2중 버그가 겹쳐 있던 것**. 이전 세션의 "projection lag/timing/materialization" 가설은 오진 —
`dataset_projection` causal 소켓 전달은 정상 동작한다.

**규명 방법**: 공식 runner는 redacted라 실패 지점이 가려짐. 비-redacting **c7-v6 harness**(`e2e-edit` bind-mount,
재-cut 불필요) + 공식 게이트와 동일하게 `--grep @c7-causal`로 스코프한 wrapper(`c7-v6-run-causal.sh`)로 live prod에서
정확한 실패 지점을 재현.

- **버그 1 — stale heading 상수**: `POI_HEADING = "POI cache targets"`(영문)이 `gotoPoiTargets` 첫 assertion에서
  15s timeout. 개편 B(`d8818994`, "헤딩 정본")에서 admin h1이 한국어 정본 **"POI 캐시 대상"**으로 통일됐는데
  spec 상수는 갱신되지 않음. 영문 문자열은 `page.tsx` metadata `<title>`에만 남아 있었다. → 상수를 `"POI 캐시 대상"`으로.
  이 상수는 13개 poi-cache 테스트가 공유하는 `gotoPoiTargets`가 사용.
- **버그 2 — page.evaluate destructure 누락(진짜 결함)**: heading 수정 후 드러난 2차 실패
  `ReferenceError: connectionId is not defined` @ `expectCausalDatasetProjectionUpdate`. 콜백이
  `({ frameCursor, receipt })`만 destructure하고 line 748에서 `connectionId`를 참조 — payload 객체엔
  `{ connectionId, frameCursor, receipt }`로 넘겼으나 브라우저 컨텍스트엔 Node 클로저가 캡처되지 않아 항상 throw.
  `cbe133c2`(POI mutation causal화)에서 helper 도입 이래 **줄곧 실패**했으나 버그 1(heading)이 이를 가려왔다.
  → 콜백 param을 `({ connectionId, frameCursor, receipt })`로.
- **검증**: 두 fix 후 c7-v6 causal-스코프 **GREEN (2 passed, 7.5s, rc=0)** — heading을 통과해 causal 소켓 assertion까지
  도달·통과. prod 부수효과 없음: active e2e target 0(soft-deleted 2건은 create→delete 라운드트립의 설계상 잔여),
  kma journal `phase=restored`/`target_refs=[]`, weather 정상.
- **완결(재-cut + 공식 게이트)**: #839 머지(main `d5693269`) → deploy(e22b751e→d5693269, 4 map runtime
  recreated+healthy, login 200) → rebind(executor 재빌드 @ d5693269 + snapshot 4-file byte-identical pins +
  attestation `repository_commit=d5693269` self-verify PASS) → 공식 게이트(KST 19:41 window) **full GREEN**:
  `status=0 orchestrator_verified=True repo=d5693269ac3e`, 6 spec 전부 passed(kma-active 2/2·kma-cap 2/2·
  kma-empty 2/2·read-auth 7/7·schedule-write 2/2·**poi-cache-causal 2/2**), no BLOCKED. 사후 prod 클린(active
  e2e target 0, weather 복원). **C7 COMPLETE at d5693269.**

## 2026-07-26 (claude) — C7 schedule-write 재편입: cron 복구 dialog inert 근인 수정 (T-ADM-C7-SCHEDCHURN)

**결론**: 직전 엔트리의 "app-side ~90s render churn" 진단은 **오진**. live 재현(n150 prod verbose-iterate)으로 확정한
진짜 근인 = **cron 저장의 HTTP 응답이 유실돼 frozen-idempotency 복구("동일 요청 재확인")가 필요해질 때, cron 수정
dialog(Base UI)가 열린 채 남아 배경 전체를 inert로 만들어 복구 alert + 모든 schedule 컨트롤이 접근 불가**가 되던 것.
DOM 계측(C7SETTLE/DOMDIAG): pre-start에서 dialogCount=1(스케줄 cron 수정) + row inert=true, 버튼 4개는 DOM에
있으나 inert 하위트리라 getByRole/click 불가. → schedule-write는 START step에서 90s(=timeout) 막힘.

**근인 규명**: reload-churn 가설을 실증 반증 — dagster `reloadRepositoryLocation` ~4s(90s 아님), 그 동안
`repositoriesOrError`는 37 schedule 계속 populated(빈 목록/row-unmount 없음); ops-live `dagster_schedules` revision도
coalesce(3-frame burst 후 침묵)라 90s frame stream 아님. 즉 데이터/서버/렌더 계층은 clean. spec에 C7SETTLE 진단
게이트 + DOMDIAG(row outerHTML/버튼 접근성)를 심어 각 step 실제 컨트롤 상태를 캡처 → pre-stop/pre-cron은
dialogOpen=false·toggle enabled인데 pre-start만 열린 cron dialog로 inert임을 확정. cron override는 webserver reload로
**즉시 반영 안 됨**(#613 documented; daemon reload가 반영)이라 override_effective 불일치는 별개 정상 상태였음.

**fix(app)**: `schedule-panel.tsx` — 편집 중인 스케줄의 frozen submission/recovery claim 등장 시 즉시 cron 수정 dialog를
닫는 useEffect. submitCronUpdate/submitClearOverride/frozen replay/**claim resolution 모든 복구 경로** + 실사용자
reachability(복구 alert가 backdrop 뒤에 안 갇힘)를 한 번에 커버. 초기 one-liner(retry onSuccess만 close)는 적대 리뷰어
finding(claim-resolution sibling + real-user reachability)으로 root-scoped useEffect로 교체.

**fix(spec, ops-c7-schedule-write)**: canReset 모델(`command==="reset"?false:true`) + waitForSchedule canReset 제외,
`robustClick`(toBeEnabled 대기 + dispatchEvent — churn/위치/backdrop 무관), `waitForScheduleControlsSettled`(dialog
닫힘 + toggle enabled 안정 대기), cron op 후 `getByRole("dialog")` toHaveCount(0) 직접 검증, 시작 확인 locator
`getByRole("dialog")`→`getByRole("alertdialog")`(confirm은 AlertDialog). getSchedule attestation/reload timeout은
이미 #74로 배포됨(유지).

**검증**: 적대 리뷰어 2명(app fix correctness + spec/regression) 반영 후 **91b822e2(main+fix)** prod 재배포
(`ktdctl pinvi-pair deploy --build`, 4 map runtime recreated+healthy, login 200, rollback-guarded) → verbose-iterate
재실행 **2 passed(37s), rc=0**; 모든 C7SETTLE pre-* `dialogOpen=false toggleEnabled=true`. weather 스케줄 매 run 정확
복원(RESTORE_OK). **schedule-write를 blocking gate에 재편입 → C7 gate 5-spec.** [[c7-recut-and-completion-push]]

## 2026-07-26 (claude) — C7 close: schedule-write descope(app-side UI churn) + 근인 6개 규명·수정

**결론**: C7 prod-live gate를 **read-auth·kma-active/empty/cap-write 4-spec**로 확정(green), **ops-c7-schedule-write는
blocking gate에서 descope**. test/deploy 측 근인은 모두 규명·수정했고, 남은 건 cron override UI 경로가 유발하는
admin schedule 목록의 **~90s render churn(app-side)** 하나뿐. 사용자 결정(descope+머지).

**규명·수정한 근인 6개**(verbose-iterate + n150 prod 재현 ×22):
1. **canReset 모델 오예측** — `waitForSchedule` 확정이 dagster canReset을 test 모델(`status !== defaultStatus`)로
   기대했으나, dagster는 명시적 start/stop마다 override를 만들어 status==defaultStatus여도 canReset=true.
   → 모델을 `command === "reset" ? false : true`로, `waitForSchedule` 비교에서 canReset 제외(파생 override 플래그,
   operational 아님). [spec — 재적용 대상]
2. **getSchedule attestation** — 배포 API가 내부 `http://127.0.0.1:12702/graphql`(canonicalGraphqlSha256 https 강제에
   걸림) 반환. → **#74**: docker-manager compose 공개 `KOR_TRAVEL_MAP_API_DAGSTER_GRAPHQL_URL` + allowed_hosts에 공개
   host. **배포됨(b5375a52 prod)**.
3. **reload timeout** — `reloadRepositoryLocation`(cron override 반영 시)은 ~4s인데 기본 3s dagster_request_timeout이
   1s 차로 놓쳐 503. → **#74**: `KOR_TRAVEL_MAP_API_DAGSTER_REQUEST_TIMEOUT_SECONDS=30`. **배포됨**(cron reload 200).
4. **cron frozen-UI replay 미발화** — post-commit response-loss가 초기 patch를 route.abort하면 reload churn으로 재확인
   버튼이 sub-second로 위치 이동 → `click({force})`가 빗맞혀 onClick 무발화(replay route-hit 없음). → `dispatchEvent`로
   위치 무관 발화. [spec — 재적용 대상]
5. **command/cron 버튼 클릭 churn** — 동일 churn을 모든 start/stop/reset/cron/save 클릭에 `robustClick`(enabled 대기 +
   dispatchEvent 재시도)로 적용. [spec — 재적용 대상]
6. **UI_MUTATION_TIMEOUT 30s→90s** — cron replay reload 수용. [spec — 재적용 대상]

**남은 근인(descope 사유) = app-side render churn**: cron override 반영 후 `SchedulePanel` 목록이 **~90s간 심한
re-render**(button attach/detach + `scheduleControlsDisabled` 깜빡임)로 start/stop 컨트롤을 조작할 순간이 전혀 없다
(dispatchEvent·retry·force 모두 그 창에서 실패; DOM 계측상 ~90s 후 버튼은 enabled·정상). test로는 조작 불가 →
**`schedule-panel.tsx` render/refetch churn 규명·수정 + UI 재빌드/재배포**가 필요한 별개 app 작업(후속 `T-ADM-C7-SCHEDCHURN`).
22회 재현이 dagster DB를 bloat해 reload/getSchedule을 느리게 한 환경 아티팩트 가능성도 있음 — fresh 환경 재확인 권장.

**진행/부수**: 6개 fix로 stop✓ → cron(replay)✓ → START 직전까지 도달(5-step 중 3). prod 부수효과 2건 복구 완료 —
(a) 실패 run들이 남긴 uncertain idempotency claim(`ops.dagster_schedule_active_claims`, CHECK상 resolution 후에만 삭제
가능) → 감사이력 동반 resolve+delete; (b) KMA hourly cron이 leftover temp override(`17 3 15 1 *`, 연 1회)로 사실상
비활성화 → `ops.dagster_schedule_overrides` 정리 + dagster reload로 `20 * * * *` 복원. 현 prod: cron=20, RUNNING.
**descope 방법**: `scripts/run-c7-prod-live-e2e.sh` SPECS에서 schedule-write 제외(spec 파일·contract test content 계약은
유지). spec은 b5375a52 배포본 유지(WIP fix는 위 6개로 문서화 — 재적용 시 참조). **머지**: #837(gate descope) + #74.
