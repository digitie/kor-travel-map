# tasks-done.md — 완료/아카이브 task 이력

## 2026-10-15 — geo 재지오코딩·odroid 이전 묶음의 doc-only 선행 둘

- [x] T-GR-00-LEDGER — **journal·tasks-done 다음 경계 분리.** [#1323](https://github.com/digitie/kor-travel-map/pull/1323)이
  journal 2026-09-20~25 8건을 `archive/journal-2026-09e.md`로, tasks-done 2026-08-04~05 2절을 `archive/tasks-done-2026-08a.md`로
  옮겼다(바이트 보존 검산 — journal 209,356 = 182,096 + 27,260, tasks-done 200,699 = 89,636 + 111,063; 예외는 상대 링크 4개
  `../` 재기준화와 끝 빈 줄). 머지가 조건이라 다음 doc-only PR(ADR-110 사실 갱신)이 `[x]`·이관을 싣는다. 해제 조건 전문은
  [acceptance §T-GR-00-LEDGER](tasks-acceptance.md#t-gr-00-ledger).
- [x] T-GR-00 — **`tasks-acceptance.md` 원장 분리 선행.** [#1315](https://github.com/digitie/kor-travel-map/pull/1315)
  (`f7affea8`, 2026-10-13 머지, lint.yml 초록)가 `scripts/archive_task_ledger_section.py --apply`로 닫힌 절 7개를
  `docs/archive/tasks-acceptance-*.md`로 옮기고(216,950 → 166,931 B, 매 이동 다중집합 검산 통과) ADR-109를 함께 실었다.
  머지가 조건이라 그 PR 안에서 못 한 `[x]`·이관을 T-GR-00-LEDGER PR이 싣는다. 해제 조건 전문은
  [acceptance §T-GR-00](tasks-acceptance.md#t-gr-00).
- [x] T-MAP-01 — **ADR-110·연동 문서·CLAUDE.md 포인터.** [#1316](https://github.com/digitie/kor-travel-map/pull/1316)
  (`463453bf`, 2026-10-13 머지, lint.yml 초록)이 ADR-110(proposed)·README 카운터 111·`integration-map.md` §1~§4·CLAUDE.md
  geocoding 줄·ADR-109 역포인터를 실었다. 단일 종결 소유자인 T-GR-00-LEDGER PR이 `[x]`·이관을 싣는다. 2026-10-14~15
  실제 호스트 이전 뒤의 사실 갱신은 별도 doc-only PR이다(ADR-110 날짜 붙은 사실). 해제 조건 전문은
  [acceptance §T-MAP-01](tasks-acceptance.md#t-map-01).

## 2026-10-06 — Common Dagster·Map/PinVi paired 완료

- [x] T-COMMON-DAGSTER — 공통 복구·메모리 제한·Admin UI 및 Map/PinVi 실제 paired 재구축·live 수용을 완료했다. [Common #28](https://github.com/digitie/kor-travel-common/pull/28) → [Map #1303](https://github.com/digitie/kor-travel-map/pull/1303) → [PinVi #576](https://github.com/digitie/pinvi/pull/576)의 exact CI와 병합 결과(Common·Map merge commit, PinVi squash)를 확인하고 머지 후 여섯 운영 서비스 healthy/설치 bytes/배포 identity가 유지됨을 재확인했다. [검증·실패·리뷰](reviews/common-dagster-2026-10-05/README.md), [머지 후 증거](reviews/common-dagster-2026-10-05/evidence/final-postmerge-runtime-attestation.json). 공유 운영 worker fault·RSS 실측 및 외부 task 완료는 포함하지 않는다.
  원 작업의 [적용 가이드](runbooks/common-dagster.md)와 [해제 조건](tasks-acceptance.md#t-common-dagster)은 이 완료 항목에 보존한다.

> 완료(`[x]`)·폐기·머지 history 아카이브. **진행 중/예정 task는 [`docs/tasks.md`](tasks.md)**.
> (2026-06-09 분리 — tasks.md 길이 축소. 분리 기준: 열린 `[ ]` 항목이 없는 섹션·Phase는 여기로.)

> **과거 기록 아카이브** (규약 §8 — 과거 검색은 `rg <패턴> docs/archive/`)
>
> | 기간 | 파일 |
> | --- | --- |
> | 2026-08-04 ~ 2026-08-05 (재생성 수렴·Wave 2 UUID 착지 일괄) | [archive/tasks-done-2026-08a.md](archive/tasks-done-2026-08a.md) |
> | 2026-07-27 ~ 2026-07-31 | [archive/tasks-done-2026-07a.md](archive/tasks-done-2026-07a.md) |
> | ~ 2026-07-26 (C7·Admin) | [archive/tasks-done-2026-07b.md](archive/tasks-done-2026-07b.md) |

## 2026-09-16 — 분모를 재고, 그래서 짓지 않기로 했다

- [x] T-VN-LEDGER-ARCHIVE — **원장 분리가 안전해졌고, 오늘 실전에서 그것을 썼다.**
  조문 1은 2026-09-14에, 조문 2·3은 #1239가 도구
  (`scripts/archive_task_ledger_section.py`)와 게이트의 아카이브 감시를 넣으며 닫혔는데
  원장 표기만 열려 있었다. 오늘 원장이 다시 220 KiB를 넘어 **그 도구를 실제로 썼고**,
  코드가 있다는 것보다 강한 근거가 생겼다: 닫힌 절 둘을 다중집합 보존 검산을 통과한
  뒤에만 옮겼고(228,917 → 216,718 bytes), 넷은 이유를 이름으로 대며 거절했으며
  (`T-FE-MOCK-FLAKE`는 들어내면 숨은 항목이 드러나는 바로 그 모양이었다), 삭제 게이트는
  아카이브가 커밋되기 전 `T-VN-39-DEPLOY#1~#4`를 "감시 대상 어디에도 없다"로 잡았다가
  커밋 후 통과했다 — 아카이브를 실제로 보고 있다는 뜻이다. 그 과정에서 도구의 **거절
  경로가 `TypeError`로 죽던 결함**도 고치고 회귀로 결박했다(거절이 스택 트레이스로
  보이면 손으로 자르게 되고, 그것이 이 task가 막으려는 경로다). 해제 조건 전문은
  acceptance §T-VN-LEDGER-ARCHIVE.

- [x] T-VN-M02 — **한 번도 실행된 적 없던 live acceptance spec을 격리 스택에서
  완주시켰다 — 첫 실행이 초록이다.**
  구현 축은 2026-09-07에 이미 전부 충족이었고 purge 정책·backup/restore는 `T-VN-H49`
  계열로 이관돼, 남은 조문은 "spec이 격리 스택에서 완주한다" 하나였다. live301
  (api `13711` · web `13712` · dagster `13714`)에서 `E2E_MANUAL_CREATE_WRITE=1`로
  **2 passed (47.9s)**. 검사가 초록인 것과 DB가 그렇게 된 것은 다른 사실이라 따로 셌다 —
  `feature.features` 1 → 2, `feature_creation_origins`에 `origin_kind=manual_admin` ·
  `created_by_actor=e2e-admin` · `invoker_role=ktm_feature_api_runtime` ·
  `procedure_definer=ktm_manual_feature_procedure_owner` ·
  `creator_principal_id=admin-ui-bff.manual-feature-create.v1`. 이 절이 요구한
  "origin이 단건 admin 경로의 principal/role 계약을 정확히 싣는다"가 그것이다.
  **원장이 "스택이 없다"고 적은 것은 낡은 기록이었다**(2026-09-08자) — pg는 5일째 떠
  있었고 앱 DB head도 저장소와 같았다. 실제로 막던 것은 Dagster 메타DB 부재와 체크아웃
  이동 시 사라지는 `scripts/*.sh` 실행권한 둘이었고, 둘 다 해소했다. 해제 조건 전문은
  acceptance §T-VN-M02.

- [x] T-VN-CURATION-SEAL-ACL — **적재 login이 seal 함수를 실행하지 못해 snapshot이
  아닌 모든 provider 적재가 prod에서 멈춰 있던 것을 닫았다.**
  2026-09-11에 `permission denied for function current_provider_curation_input_set`로
  박물관 적재가 섰다. 좁은 `ktm_curation_provider_executor`에 EXECUTE를 주도록
  `runtime_privileges.py` 렌더링 모델에 넣었고(넓은 `ktm_feature_runtime`에 주면 API
  login까지 열린다 — 멤버십 경유 권한은 `REVOKE`로 걷히지 않는다), `infra/db.py`의
  per-login 허용목록에도 등록했다(이 경로로 오는 첫 SECURITY DEFINER 함수라 빠뜨리면
  모든 Dagster 프로세스가 기동 preflight에서 죽는다).
  닫은 근거는 셋 다 **실측**이다: (1) 현 prod에서 `feature_place_standard_museums_job`
  run `0f70d0d5`가 `SUCCESS`로 끝나고 `features 1047 · source_entities 1047 ·
  seal 영수증 1건`(영수증은 seal이 실제로 실행돼 해시를 돌려준 뒤에만 쓰인다),
  (2) 배포가 DB를 새로 만든 뒤에도 `dagster_seal=true / api_seal=false`,
  (3) 실 login으로 적재 경로를 태우는 회귀를 추가하고 변이로 빨강을 확인했다 —
  EXECUTE는 두고 표 SELECT만 걷으면 **옛 카탈로그 술어 검사는 초록이고 새 검사만
  빨갛다**. 해제 조건 전문은 acceptance §T-VN-CURATION-SEAL-ACL.

- [x] T-VN-D2-RESIDUE — **이미 고쳐져 있었다: #1218이 purge를 lane 안으로 들였고,
  오늘 prod에서 `feature.features` 0행을 확인했다.**
  D2가 소유 Feature를 은퇴까지만 끌고 가 run마다 prod에 은퇴 행이 하나씩 쌓이던
  문제다. `fc6e7efb`(2026-09-12)가 `purge`를 러너 호출부와 supervisor 허용목록
  양쪽에 들이고 모든 게이트 뒤에서 돌게 했으며, `test_lane_operations_are_declared_once`
  (10 passed)가 선언이 세 군데에서 갈라지지 않는 것을 결박한다.
  **조문은 그 뒤로 나흘간 열린 채 남아 있었다** — 고쳐도 원장이 닫히지 않으면 열린
  항목이 실제보다 많아 보이고, 그 상태로 "다음 한 작업"을 고르면 끝난 일을 다시
  연다. 오늘 그럴 뻔했고, 실측(prod 0행)으로 갈렸다.

- [x] T-VN-KREX-TPS-FANOUT — **krex 상한을 프로세스 사이까지 넓혔다: advisory lock
  gate + 교대 간격, t44a로 배포하고 prod에서 읽어 확인했다.**
  라이브러리 상한(초당 5건)은 **프로세스당**인데 큐가 worker run을 4개까지 동시에
  띄워 합계가 최대 20 TPS였다 — 적대 리뷰어 둘이 독립적으로 짚었고, 그전까지 나는
  문서에 "합계 5 TPS"라고 **틀리게** 적어 두었다. `feature_update_runner`의
  `provider_rate_gate`(Postgres advisory lock + `1/max_rps` 교대 간격)로 닫았다.
  **직렬화만으로는 부족하다** — lock을 즉시 놓으면 다음 프로세스의 첫 요청이 이전
  마지막 요청 뒤에 붙어 이음매에서 넘친다. 검사는 **동시 run을 흉내 내야** 의미가
  있다(한 프로세스 안에서만 재면 구멍이 안 보인다). gate 간격과 라이브러리
  `DEFAULT_MAX_RPS`가 서로를 모른 채 각자 `5`를 들고 있던 drift도 AST 검사로 결박했다.
  `provider_refresh_policies`로 옮기지 **않기로** 했다 — 그 테이블은 prod에서 0행이고
  없으면 fail-open이라 코드 상수보다 나빠진다.

- [x] T-VN-QUEUE-QUOTA — **큐 경로 upstream 쿼터: 분모·분자를 다 재고 여섯 조문을 닫았다. 일일 예산 장치는 만들지 않기로 결론.**
  분모는 포털에서 확인했고(data.go.kr 한도는 **오퍼레이션당**이다 — `opinet`은
  300/일로 저장소가 알던 1,500의 1/5였다), 분자는 코드에서 세고 전국표준데이터
  총건수는 실제로 조회했다(최대 `parking` 18,883). **하루를 넘기려면 166,000이
  필요해 한 자릿수 아래이므로 일일 예산 장치를 만들지 않기로 했다** — 가장 좁은
  `opinet`은 이미 run당 예산이 있다. 대신 구멍 셋을 닫았다: khoa 페이지 절대 상한 +
  stall 지문, `opinet_run_call_budget`의 `le` 300→150(설정 한 줄로 200%가 가능했다),
  그리고 그 구멍을 보는 검사. `krex`는 분모가 미공개라 축을 바꿔 TPS 5로 막았고 그
  후속은 `T-VN-KREX-TPS-FANOUT`이 갖는다. 근거는
  `docs/etl/upstream-quota.md`, 조문은 `docs/tasks-acceptance.md` §T-VN-QUEUE-QUOTA.

## 2026-09-13 — 배포된 세대가 run을 완주시키는지 재게 됐다

- [x] T-VN-QUOTA-DENOMINATORS — **회수(2026-09-14). 완료가 아니라 ID 합침이다.**
  같은 날 만들었다가 같은 날 되돌렸다 — 주제가 `T-VN-QUEUE-QUOTA`와 같고(큐 경로의
  쿼터) 별도 ID로 둘 이유가 없었다. **작업이 사라진 것이 아니다**: 남은 provider 넷의
  분모를 포털에서 확인하는 일은 `docs/tasks-acceptance.md` §T-VN-QUEUE-QUOTA의 1~4번
  조문으로 그대로 있고, 큐 예산 장치는 그 뒤 5번으로 내려갔다("측정 전에 상한 숫자를
  바꾸지 않는다").

- [x] T-VN-QUOTA-ARITHMETIC — **쿼터에 대해 저장소가 하는 진술 대부분이 근거가 없다**
  (**2026-09-14 완료**). 분모를 data.go.kr에서 실측해 전제 하나를 뒤집었고(일일
  트래픽은 서비스가 아니라 **오퍼레이션마다** 걸린다), 분자를 `upstream_requests_min`
  으로 asset/op metadata까지 이었으며(#1229), 쿼터성 실패가 step 재시도를 사지 않게
  하고(#1227), 선언 없는 증폭기를 없애고, UI의 근거 없는 보증을 지웠다. 여섯 조문
  전부 `[x]`. prod 배포 t41a·t42a 두 사이클 모두 GREEN(D1 live Playwright 통과).
  적대 리뷰 여섯 판이 이 task를 만들었고 3·4·5차 blocker는 전부 직전 판의 수정이
  만든 것이었다 — 서사는 `docs/journal.md` 2026-09-13/14. 상세는
  `docs/tasks-acceptance.md` §T-VN-QUOTA-ARITHMETIC, 정본 수치는
  `docs/etl/upstream-quota.md`.

- [x] T-VN-DAGSTER-STORAGE — **run은 완주한다. 그 사실을 재는 검사와 UI 로그가 없다**
  (**2026-09-13 완료**). 다섯 조문 전부 닫혔다(#1216 · #1219 · #1224 · #1225 · #1226).

  **조문 3 — 재는 검사가 생겼다.** `scripts/dagster_run_completion_gate.py`가 다섯
  축을 독립으로 판정한다: live config(컨테이너 안 `$DAGSTER_HOME/dagster.yaml`),
  metadata 표 실재, daemon heartbeat 신선도, **능동 탐침 run 완주**, 멈춘 run 0건.
  prod 실측으로 2026-09-11 사고 config를 되돌리면 red가 되는 것까지 확인했다
  (config 변이 5종 + daemon tolerance 변이 전부 red, 대조군 0/15).

  **조문 2 — 세대가 바뀌어도 유지된다.** t41a 배포에서 generation이
  `b71cbefc` → `bae61363`으로 바뀐 뒤 같은 게이트가 15/15로 통과했다. 한 번의
  관측이 아니라 두 세대의 비교다.

  **조문 5 — 고치기 전에 재고, 재고 나서 고치지 않았다.** webserver와 daemon이
  compute log를 공유하지 않는 것은 맞았지만, 그 자리에 있는 파일 286개가 **전부
  0바이트**였다(1,047건을 적재한 provider job의 것 포함). 진단 내용은 event
  log(postgres)에 있고 두 컨테이너가 같은 DB를 본다. 공유 volume은 빈 파일을
  공유하면서 ~31 MB/일을 무한히 쌓는 교환이었다.

  **이 task가 남긴 규칙.** 검사가 초록인 것과 결함이 없는 것은 다른 사실이다 —
  이 게이트의 첫 판도 초록이었지만 네 자리에서 아무것도 재지 않았다
  (`floor/runs-observed`가 탐침 때문에 항진명제, stuck이 큐 대기 시간을 섞어 잼,
  daemon 하한이 상수 1, 신선도 분모가 꺼진 daemon 때문에 영구 red). 두 차례
  적대 리뷰가 하나씩 잡았고 전부 prod에서 다시 쟀다.

## 2026-09-11 — feature_id 재키가 착지했다

- [x] T-VN-39-DEPLOY — **재키 착지본 prod Map 배포와 D2 재핀**
  (**2026-09-12 완료**). 다섯 조문이 전부 실측으로 성립한다 — prod head
  `309_t39_feature_id_rekey`에 `feature_id`가 uuid, D2 `phase: passed`,
  PinVi rebind 없음, provider 적재 1047건, 정본↔실물 image 불일치 0.

  **재키의 핵심 축이 운영 데이터에서 성립한다.** `entities/heads/links/features/
  claims/aliases`가 전부 1047로 맞물리고 고아·불일치 여섯 검사가 0이다. claim은
  `(provider_dataset_id, feature_kind, natural_key) → feature_id`로 발급되고
  (`ON CONFLICT (feature_id)`를 대신하는 ADR-098 앵커), legacy `f_*`는
  `f_1111010600_p_98434503e9869507 → 01a092b7…`처럼 **주소로 생존**한다.

  **배포가 드러낸 결함이 넷이었고 전부 재키와 무관한 선재 결함이었다** —
  정본/실물 드리프트, seal 함수 ACL 유실(`T-VN-CURATION-SEAL-ACL`), D2 fixture의
  다섯 겹(`T-VN-39-D2-FIXTURE`), Dagster 로컬 쓰기 경로(`T-VN-DAGSTER-STORAGE`).
  prod `features`가 0행이었다는 것이 그 넷을 한 문장으로 설명한다 — 이 prod에서
  provider 적재가 한 번도 완주한 적이 없었고, 그래서 아무도 그 길을 걸어보지
  않았다.

- [x] T-VN-39-D2-FIXTURE — **D2 fixture의 소유 핸들을 재키 뒤 앵커로 옮긴다**
  (**2026-09-11 완료**, #1207 `0ad47253` · #1210 `54136ac7` · #1211 `3891f632`).
  D2 lane이 재키 뒤 세계에서 **다섯 겹**으로 막혀 있었다:

  1. legacy `f_global_*` 주소를 `CAST(:feature_ids AS uuid[])`에 바인드 —
     질의는 uuid 축으로 옮겼는데 값의 출처는 안 옮긴 자리. alias도 안 생기고
     (ADR-098 결정 6) 후보 uuid는 비파생 랜덤 v7이라 재계산도 불가 → run별
     provider dataset에서 primary link로 **재현**한다.
  2. create payload의 `feature_uuid` 슬롯 — 309가 계약에서 지웠다. 같은 값으로
     맞추는 것으로는 `ck_feature_create_payload`를 통과하지 못한다.
  3. `CAST(feature_uuid AS text)` 투영 — 309가 지운 컬럼. 바깥 별칭은 두고 값의
     출처만 정본 키로.
  4. legacy id 재현과의 대조 — 서버가 그 규칙을 버렸다. 대상을 canonical UUIDv7
     발급과 두 표기 일치로 옮긴다.
  5. raw `DELETE FROM feature.features` — 306이 봉인했다. 감사되는
     `feature.purge_manual_feature`로.

  **마지막 두 겹은 적대 리뷰(36 에이전트)가 사이클 전에 잡았다.** 그 둘은 내가
  고친 파일이 아니라 형제 검사기(`admin_feature_live_state.py`)에 있었고 —
  legacy 정규식과 `foreign_key_references == 8`(309가 없앤 alias 행을 센다) —
  재키 전에는 api-audit이 더 일찍 죽어 **도달조차 못 하던** 줄이었다. 내 수정이
  처음 도달 가능하게 만들었으니 낡은 줄이어도 이 변경군의 회귀다.

  실측: D2 `phase: passed`/`status: complete`, `validation.json`
  `evidence-validated`, prod 잔여물 0.

- [x] T-VN-39-PROVIDER-PAGINATION — **provider 종료 조건 퇴화를 upstream에서 고친다**
  (**2026-09-11 완료**, Map #1204 `7b2e9ecf`). 두 provider의 `iter_pages`가 `total`
  권위를 잃고 짧은 페이지 휴리스틱만 남겨, **행 하나가 검증에서 걸러진 만재 페이지**를
  스트림의 끝으로 읽었다. 절단이 예외를 내지 않으므로 소비자는 알 방법이 없고, Map은
  그것을 `authoritative_snapshot_complete=True`로 봉인한다.

  upstream에서 고쳤다(ADR-044 — 정합성 1차 책임은 provider) — datagokr `fd099b2`
  (PR#16)는 짧은 페이지 종료를 declared total로 조건화했고, krheritage `545a016`
  (PR#10)는 되돌릴 가드가 아예 없어 새로 세우되 **행이 아니라 페이지 수**로 센다
  (`page >= ceil(total/page_size)`) — 걸러진 행이 있어도 정확히 끝나므로 행을 세는
  것보다 엄밀히 낫다. 회귀 8건 + 기존 82건 통과, Map 핀 3자리 상향(표면 manifest는
  `pinned_sha` 둘만 바뀌어 공개 표면 불변이 증거다).

  Map 쪽 우회(`_iter_datagokr_standard`, `iter_paginated_items`)는 걷지 않았다 —
  같은 성질을 두 층이 각각 보장하는 것은 중복이지 모순이 아니다.

- [x] T-VN-39-ECHO — **API 패키지 conftest의 echo-resolve를 재키 뒤 세계로**
  (**2026-09-11 완료**). autouse echo가 `feature_id=ref`로 재키 **이전** 세계를
  모사해, "legacy 주소가 정본 uuid로 바뀌어 repo로 내려가는가"를 이 패키지에서
  관측 불가로 만들고 있었다. `canonical_ref()`가 그 사상을 세우고, 함께 움직인
  자리가 27곳이다 — fake의 kwargs, 존재 확인, 응답 본문, 그리고 weather batch가
  snapshot을 되찾는 조회 키(단언이 아니라 fake의 **반환값**이라 안 고치면 라우터가
  RuntimeError로 죽었다). n150 전량 **1223 passed / 0 failed**.

  **조문 하나를 삭제했다.** "자체 resolver 설치가 제거된다"는 echo가 할 수 없는
  일을 요구한다 — 전역 echo는 모든 참조를 해석 성공으로 만들어 "미해석 422" 축을
  표현할 수 없고, 그 축을 재는 세 테스트가 재키 적대 리뷰 마지막 결함
  (`22P02`→`DataError`→500)의 단위 커버리지다. 규약을 반대로 고정했다 — **echo는
  해석의 값을, 각 테스트는 해석의 실패를 모사한다.**

- [x] T-VN-39 — **KTM·PinVi write-fence cutover / legacy TEXT `feature_id` PK 제거**
  (**2026-09-11 완료**, #1197 `e8c66c47`). 본체는 재타입이 아니라 **멱등 앵커 교체**였다 —
  재키가 `ON CONFLICT (feature_id)`의 결정적 축을 없애므로 그 자리를
  `provider_sync.provider_feature_identities` claim이 대신한다(ADR-098). legacy `f_*`는
  사라지지 않고 `feature_aliases.alias`의 **주소 등록부**로 옮겼다. 착지 실측:
  feature_id류 컬럼 52개가 uuid이고 text로 남은 셋은 정당한 생존자
  (`legacy_feature_id` 2표 + plpgsql 변수), shadow `feature_uuid` 0개.
  **바깥 이름은 하나도 바뀌지 않았다.**
  근본원인은 "범위를 오라클이 아니라 프록시에서 유도했다"였고(다섯 번 유도·다섯 번
  오답), 제품 SQL을 head에 직접 물리는 Parse 오라클이 첫 실행 33초에 여덟을 찾았다.
  적대 리뷰 두 라운드(12 + 85 에이전트)의 최대 수확은 결함이 아니라 **결함을 가리는
  구조**였다 — 항진명제 FK 검사, 개수만 세던 lint, 해석 축을 통째로 가리던 autouse
  echo-resolve. 상세는 `docs/reports/t-vn-39-routine-open-defects.md`.
  후속은 `T-VN-39-DEPLOY`·`T-VN-39-ECHO`·`T-VN-39-PROVIDER-PAGINATION`.
- [x] T-VN-39-SECURITY — **배포 의존성 권고 셋**(#1198 `f8c11239`). maplibre-gl 6.9.0 ·
  Next 16.3.4 · sharp 0.35.4. maplibre 메이저는 default export 제거 한 줄이 전부였고,
  실브라우저 e2e를 두 버전에 같은 조건으로 돌려 실패 집합이 **완전히 동일**함을 확인한
  뒤 머지했다. 같은 숫자를 네 자리가 들고 있던 과결박도 함께 걷어냈다.
- [x] T-VN-39-PINS — **provider 핀 8종 상향**. breaking은 khoa 하나(asyncio 전용 전환)
  였고, 무거운 것은 datagokr·krheritage의 **조용한 절단**이었다 — 기형 행 하나가
  18,000건을 999건으로 만들고 Map이 그것을 완전 스냅샷으로 봉인할 수 있었다.
  두 경로를 Map의 `total` 권위 페이지네이터로 옮겨 provider 종료 조건에 대한 위임을
  끊었다. upstream 근본 수정은 `T-VN-39-PROVIDER-PAGINATION`이 소유한다.

## 2026-09-08 (2) — 승격 검증이 durable 기록을 남긴다

- [x] T-VN-M05-VERIFY-RECEIPT — **승격 검증이 durable 기록을 남기게 한다**
  (**2026-09-08 완료**, Manager #335). V1·V2·V4는 코드로, V3는 승격 정의 개정(소유자
  승인)과 n150 실측으로 닫았다. `--verify-leaf`는 정말로 아무것도 쓰지 않았고, V2가
  요구하는 값은 전부 이미 지역변수로 살아 있다가 print 문자열에만 들어가고 버려지고
  있었다. 가장 날카로운 지점은 신뢰 경계 거부 경로였다 — 한 문장만 인쇄하고 축을 하나도
  남기지 않아, receipt를 붙였어도 내용이 비었을 것이다.
  상세는 `docs/tasks-acceptance.md` §T-VN-M05-VERIFY-RECEIPT.

## 2026-09-08 — purge 개방·TRUNCATE fence·소비 기록

- [x] T-VN-H49(hard purge 정책) — **manual Feature hard purge를 감사되는 운영 명령으로
  연다**(migration 306). fence의 이름은 처음부터 `_not_ready`였고 ADR-093도 "M02 purge
  계약 **전**에는 닫는다"고 적었다 — 정책이 아니라 임시 마개였는데 그 술어가 항상 참인
  조건이었다. purge가 **자기 복구점을 들고 다녀** H43 보류에 묶이지 않는다. claim의 두
  역할을 갈라 tombstone을 관리 가능하게 했다. 상세는 acceptance §T-VN-H49.
- [x] T-VN-M02-TRUNCATE-FENCE — **(a) `ENABLE ALWAYS` 트리거**(migration 307). 원장의
  "통째로 우회"와 "테스트 24곳"이 둘 다 틀렸고, 진짜 결함은 진단이 엉뚱한 이유를 대는
  것이었다. 원장이 몰랐던 `ops.feature_requests` 구멍도 함께 닫는다.
- [x] T-VN-M05-ONESHOT-CONSUME — **성공이 scoped phase로 실행권을 소비한다**
  (Manager #335). 소각으로 남기면 방금 성공한 leaf가 L8에서 죽는다. 적대 리뷰가 내
  변이 검증이 놓친 축(필터 **약화**)을 잡았다.

## 2026-09-08 — M05 계약 완주

- [x] T-VN-M05 — **provider 발행 Feature 중복 판정 계약(ADR-097)**
  (**2026-09-08 완료**). 조문 M05-1~M05-7 전부 충족. 마지막으로 닫힌 둘은 M05-5(전용
  admin 라우트, #1193)와 M05-2다. M05-2는 evidence를 canonical JSONL로 뽑고(A) 번들을
  검증하고(B) 리허설이 소유권·ACL 복원을 증명하고(C) **복원본 DB의 lease를 무효화하고
  cursor를 재구축한다**(D). 2026-09-07의 "300 baseline 정책이 바뀌어야 판정 가능"은
  틀린 판정이었다 — 정책을 바꾸지 않고도 조문이 요구하는 것을 지을 수 있었고,
  restore/swap은 여전히 닫혀 있다. 상세는 `docs/tasks-acceptance.md` §T-VN-M05.

## 2026-09-08 — M05 재심 차단

- [x] T-VN-M05-RELITIGATION — **admin이 판정한 쌍이 다시 올라오지 않게 한다**
  (**2026-09-08 완료**, migration 305). 프로시저의 멱등성이 미해결 case에만 성립해
  `kept` 판정 쌍이 매 실행 새 case가 됐다 — #1189의 탐지 job에 스케줄을 못 단 이유다.
  판정을 좌우하는 것만 넣은 `decision_fingerprint`로 차단하고, R5로 일간 스케줄
  (04:20 KST, 기본 `STOPPED`)을 붙였다. **변이 검증이 설계를 고쳤다** — 처음 넣었던
  `source_record_key`는 같은 내용의 재fetch로도 바뀌어 churn 원인이었다.
  상세는 `docs/tasks-acceptance.md` §T-VN-M05-RELITIGATION.


## 2026-09-08 — M05 활성화 승격

- [x] T-VN-M05-ACTIVATION — **M04/M05 live acceptance attestation 승격**
  (**2026-09-08 완료**). 승격 정의를 "문서 행위"에서 "Manager `--verify-leaf`가 해시
  사슬과 살아 있는 pin registry를 다시 계산해 대조한다"로 바꾸고, 그 명령이 `ktdctl`
  설치본에서 두 승격 후보 leaf에 대해 exit 0을 내는 것을 실측했다(P1). 전문 적대 리뷰가
  **5라운드** 돌아 5차에서 두 건 모두 GO였다(P2). 상세는 `docs/tasks-acceptance.md`
  §T-VN-M05-ACTIVATION — 정의표 15축, 프로그램 출력 원문, 재현 절차, 승격 근거의 수명.

  **매 라운드 실제 결함이 나왔고 검증기는 8축 → 15축이 됐다.** 1·2차는 "승격이 문서
  행위였다"와 "검증기가 정의의 근거를 확인하지 않았다"(leaf 소유자·권한을 한 번도 안 봐
  아무 디렉터리나 받았고, 대조값이 전부 world-readable이었으며, M04를 해시만 하고 열지
  않았다)를 잡았다. 3·4·5차가 잡은 것 중 **둘은 앞 라운드 수정이 만든 회귀**였고
  **셋은 픽스처가 결함을 가린 것**이었다.

  **잔여를 이름 붙여 넘겼다**: `T-VN-M05-VERIFY-RECEIPT`(검증이 durable 기록을 남기지
  않아 승격 근거가 pin 회전·history 링·identity 소각 중 무엇에도 재현 불가가 된다),
  `T-VN-M05-ONESHOT-CONSUME`(성공이 execution identity를 소비하지 않는다).
  위조 문턱은 "root"까지이며 그 이상을 주장하지 않는다.


## 2026-09-07 — M04와 H49 자식 셋

- [x] T-VN-M04 — 범용 Feature 요청 큐 (**2026-09-07 완료**). 위임("41C가 완료한다")이
  **dangling pointer**였다 — §T-VN-41C 어디에도 M04가 없고 41C는 보류라 잔여도 세지
  않는다. 위임을 걷고 판정 가능한 조문 다섯을 세웠다. 넷은 이미 산출된 증거로 충족이고
  (`/root/pairv2-e2e-03`의 두 서명이 같은 `feature_request_id`로 서로를 가리킨다),
  **다섯째는 이 조사가 만들었다** — reject가 라우터·프로시저·ACL·OpenAPI에 전부 있는데
  호출하는 테스트가 없었다. 통합 테스트로 상태 전이·사유 보존·Feature 부재를 결박했고
  CI `pytest integration (PostGIS)`가 통과했다(#1185).
세 자식은 한 원인으로 같이 막혀 있었다. `rehearse-restore`는 **한 번도 성공한 적이
없었다** — `docker cp`가 호스트 소유권(`root:root 0600`)을 보존하는데 `pg_restore`는
`--user postgres`(uid 999)로 돌아 덤프를 읽지 못했다. Manager #324가 `docker exec --user
root chown` 인계를 넣어 셋 다 처음으로 통과했다. 기록 위치는 Manager
`docs/docker-management.md` §복원 리허설 실측 기록.

- [x] T-VN-H49-PINVI — PinVi standalone backup 복원 검증 (**2026-09-07 완료**).
  복원 리허설 `verified: true`, 덤프 12.1MB. 셋 중 가장 작아 소유권 인계 수정을 처음
  실측한 대상이었다.
- [x] T-VN-H49-GEO-DAGSTER — geo Dagster standalone backup 복원 검증 (**2026-09-07 완료**).
  복원 리허설 `verified: true`, 덤프 59.8MB. 이 자식은 백업 자체가 12일간 멈춰 있었고
  원인은 "막힌 행"이 아니라 **디스크 고갈**이었다(2026-08-26 `insufficient disk space`
  7연속, 44.1GB 필요 대비 29.8~36GB 여유). 98GB 회수 후 새 job이 정상 진입했다.
- [x] T-VN-H49-CONCIERGE — concierge standalone backup 복원 검증 (**2026-09-07 완료**).
  복원 리허설 `verified: true`, 덤프 78.9MB. 셋 중 가장 크며 같은 소유권 인계 수정으로
  통과했다.


## 2026-09-07 — 소유자 판정으로 닫은 둘

- [x] T-FE-MOCK-FLAKE — admin UI logs acceptance (**2026-09-07 완료**). mocked 절반은
  PR #1045·#1059·#1077로 해소됐고 HEAD에서 manifest 결박을 재계산해 확인했다(284 tests,
  `testInventorySha256` exact 일치). live 절반은 `logs.live.spec.ts` 2건이 배포 스택에서
  **4회** 통과했다(`workers=1`, `retries=0`). 마지막까지 열려 있던 AC7("승인된 읽기 전용
  자격증명")은 **소유자 판정으로 `T-VN-41F1D-D1` 실측이 갚는다.**
  **잔여 위험(감추지 않는다)**: AC3·AC5의 receipt는 현 HEAD보다 frontend/src 커밋 5개
  뒤 체크아웃 것이고 mocked checkpoint는 CI job이 아니라 수동 게이트다. CI `type-check`가
  mock↔생성 타입 drift는 매 PR 잡는다. 상세는 `docs/tasks-acceptance.md` §T-FE-MOCK-FLAKE.
- [x] T-VN-H34 — 공식 curation 미연결 membership (**2026-09-07 완료, 범위: 저장소 CSV**).
  소유자 판정으로 범위를 저장소 CSV까지로 한정했다 — prod 데이터를 전제하던 조건들은
  **pinned rebuild가 매번 DB를 새로 만들어** 구조적으로 닫히지 않는다. CSV 범위 4개 조건
  전부 충족(주소 축 시군구 대조 도구화, provider provenance는 #910 import-act로 해소,
  판정 축 3개 도구화, 카테고리 모순 8건 처리 + manifest linked 216 / unresolved 270).
  **범위 밖으로 밀려난 넷**(preview/commit 실데이터 검증, H34A 전수화, H34B prod import,
  "없는 것은 Feature로 추가" 3건)은 지우지 않고 acceptance 절에 남겼다 — 재개하려면
  lifecycle 판정이 선행한다.


## 2026-09-07 — T-VN-PAIR-V2

- [x] T-VN-PAIR-V2 — PinVi M05 pair 계약 v2 이행 (**2026-09-07 완료**). 계약에서
  `source_revision`·`runtime_image_digests`를 걷어 **Map revision·image digest의 이중
  선언**을 없앴다(`AGENTS.md` DO NOT 15). 값의 정본은 Manager pin registry와 PinVi
  service-provenance 계약이고, 표면마다 생산자를 이름 대어 배선했다.
  **성과**: Map 문서 한 줄이 PinVi 커밋 → 새 pinset → 71분 rebuild를 부르던 연쇄가
  끊겼다(2026-09-01 이후 재핀 12건 중 10건은 상류 OpenAPI 바이트 무변경).
  **실증**: pinset `b229446a`에서 회전 → rebuild(`phase: committed`) → 격리 M05 e2e
  `status: passed`. 회전 preflight가 Map 5커밋 전진을 **PinVi 커밋 없이** 수용.
  **적대 리뷰 2라운드**가 P0 2건을 잡았고(v2로 receipt 생성 불가 / service revision
  생산자 오지목 → 71분 뒤 기동 실패) 픽스처가 둘 다 가리고 있었다. 변이 검증 PinVi
  9건 · Manager 12건 전부 red. 상세는 `docs/tasks-acceptance.md` §T-VN-PAIR-V2.
  PR: PinVi #538 #539, Manager #321 #322 #323, Map #1181 #1182.

## T-VN-D2-API-AUDIT — helper의 api-audit 경로 활성화 (2026-09-06 완료)

- [x] T-VN-D2-API-AUDIT — 러너가 `api-audit`을 실제로 부르고 배포 스택에서 통과했다
  (`ktdm-d2-008`, pinset Map `631f1abc` + PinVi `b9637375`, `phase: passed`, runner exit 0).

  **고친 결함.** `_admin_fixture_feature_id`가 `{name}:{lon:.6f},{lat:.6f}`를 자연키로
  `feature_id`를 **재계산**했다. M01 뒤로 서버는 `manual::{feature_uuid}`를 쓰고 그 uuid는
  서버 발급 랜덤 UUIDv7이라 밖에서 재계산할 수 없다 — 그 대조는 **항상 실패**했고, lane이
  `api-audit`을 한 번도 부르지 않아 잠복해 있었다. 이제 관측된 행의 uuid로 서버 규칙을
  **재현**한다.

  **배포 DB 실측으로 세 번 확인**했다(서로 다른 실행이 만든 Feature):

    | uuid | 실제 feature_id | 새 규칙 |
    |---|---|---|
    | `01a07464-b352-…` | `f_global_p_fb718cf7406d30e8` | MATCH |
    | `01a07721-91d6-…` | `f_global_p_bf5e63b1f78c76f7` | MATCH |
    | `01a07766-37d6-…` | `f_global_p_cbf498eb3eed8553` | MATCH |

  구 규칙은 셋 다 다른 값을 냈다.

  **최종 실행(`ktdm-d2-008`).**

    lifecycle    56 = 7 operation × 8 phase   (helper-api-audit 8개)
    evidence     phase=evidence-validated, 파일 집합 exact, FK 제약 18, 리포트 2
    api-audit    counts 3·1·7·3, FK constraints 18 / references 8
                 feature_ids ["f_global_p_cbf498eb3eed8553"]
                 feature_uuids ["01a07766-37d6-76cb-a619-5bc43013c4bd"]
    lane         BLOCKED·RESULT·ACTIVE 모두 없음

  **clone 러너의 계약도 함께 옮겼다.** place id를 재계산하지 않고 api-audit 증거에서
  읽는다 — 같은 파일의 `owned_feature_uuids_sql`이 "UUID는 서버가 발급하므로 재계산할 수
  없다"는 같은 이유로 이미 그렇게 하고 있었다. 두 파생 일치 단언도 새 규칙으로 다시 썼다.

  **다섯째 결선 지점을 배포 실행이 찾아냈다.** 착수 전 acceptance 노트는 "네 곳"이라
  적었는데 `admin_feature_live_supervisor.py`의 `--helper-action` argparse **choices**가
  다섯째였다. 빠지면 argparse가 exit 2로 죽는데 그것은 lifecycle도 출력도 쓰기 **전**이라
  lane에 아무 흔적이 없고, 실패가 "owned fixture cleanup left residue"라는 **엉뚱한 곳**을
  가리킨다(`ktdm-d2-007`에서 실측: lifecycle 48개, api-audit 0개, 실제 잔여물은 0).
  `tests/lint/test_supervisor_accepts_every_helper_action.py`가 러너 호출부에서 유도해
  세 쪽을 결박한다. 해제 조건의 표를 다섯 줄로 고쳤다.

  **남은 것 없음.** `purge`는 여전히 러너가 부르지 않는다 — hard purge는 `T-VN-M02`가
  fence하고 있고, supervisor 허용 목록도 호출자가 생길 때 함께 여는 것이 계약이다
  (게이트가 그것을 단언한다).

## T-VN-41F1D-E — 구 generation 퇴역·v6/v8 attestation 전환 (2026-09-06 완료)

- [x] T-VN-41F1D-E — 저장소측은 2026-08-25에 끝났고, 남았다고 적힌 "n150 data-dependent
  실행"은 **D2가 pinset `48166bd2`에서 이미 수행했다**(2026-09-06).

  | 요구 | 결과 |
  |---|---|
  | 두 러너의 v4 `E2E_C7_COMPATIBLE_PAIR_MANIFEST` 제거 | 완료. 저장소 전체에서 그 이름은 **부재를 단언하는 테스트 한 줄**로만 남는다(`tests/unit/test_admin_feature_live_acceptance.py`) |
  | v6 manifest + v8 journal 요구 | `run-c7-prod-live-e2e.sh`와 `run-admin-feature-live-acceptance.sh`가 `E2E_C7_PINNED_RUNTIME_MANIFEST`·`E2E_C7_REBUILD_JOURNAL`을 `require_env`로 요구 |
  | v4/v5/v7 억지 입력 compatibility 경로 부재 | 러너 계약 테스트가 단언 |
  | **n150 data-dependent 실행** | D2 lane이 snapshot의 `c7_prod_attestation.py`를 `validate-c7-module`로 봉인 확인한 뒤 v6 manifest·v8 journal·host attestation을 넘겨 검증하고, 세 해시를 `result.json`에 남긴다 — `pinned_runtime_manifest_sha256 6ed900f5…`, `rebuild_journal_sha256 4cf269c4…`, `host_attestation_sha256 5b7f91ea…`. lane은 `phase: passed`로 닫혔다 |
  | 구 generation 퇴역 | v4/v5/v7 **포맷**이 `/etc/kor-travel-map/retired-de5206dc/`로 퇴역했다(`c7-compatible-pair-v4.json`, `…-v5-pr197.json`, `…-v7-pr197.json`) |

  **검증기가 대조하는 축**이 해제 조건의 열거와 일치한다 — generation shape·image·source
  revision·schema head·pinset·candidate evidence(digest/git tree/PostgreSQL image), journal의
  Dagster metadata identity·role·privilege·membership·owner, PinVi DB identity·owner,
  operation plan/identity/digest/generation, application execution evidence.

  **수행하지 않은 것과 그 이유.** `run-c7-prod-live-e2e.sh`(6-spec C7 prod gate)는 v6/v8
  전환 이후 돈 적이 없다(증거 디렉터리 최종 기록 2026-08-23). 그 러너의 운영 순서를 정의하는
  `docs/runbooks/c7-prod-live-e2e.md`가 스스로 **`[보존 이력 · 실행 금지]`**이고 "300
  baseline의 n150 배포에는 사용하지 않는다"고 적는다. 즉 이 축은 `T-VN-M01`의 restore 축과
  같은 계열 — **수행 가능한 형태가 아니다.** 되살릴 조건도 같다: 300 baseline에 맞는 C7 prod
  gate 운영 순서가 생기면 그때 다시 세운다. 그 전까지 v6/v8 전환의 live 증거는 D2 lane의
  매 실행이 낸다.

  **남은 것(퇴역 아님).** `/etc/kor-travel-map/`의 v6/v8 pinset 쌍 여섯은 **같은 포맷의
  이력**이고 활성은 `48166bd2`다. repin 주기마다 한 쌍이 생기는 설계이므로 이력 보존이
  정상이며, 롤백 입력이라 지우지 않는다.

## T-VN-M01 — admin Feature 생성 API clean cutover (2026-09-06 완료)

- [x] T-VN-M01 — 활성화 전제 셋이 전부 닫혔고 route가 live다.
  `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true`
  (`/opt/kor-travel-docker-manager/.env`, 2026-09-05T20:27:59Z, 백업
  `.env.bak-pre-m01-activation-20260905T202759Z`).

  | 전제 | 결과 |
  |---|---|
  | PinVi `new_place` 직접 create 제거 | 완료 ([PinVi #458](https://github.com/digitie/pinvi/pull/458)) |
  | DB/API/admin UI + ACL reconciliation | 완료(#1029). ACL 축 **55/55**, 활성화 rebuild 앞뒤로 두 번 측정 — §8.2가 "restore 뒤 동일"을 요구하기 때문 |
  | restore 축 | **수행 가능한 형태가 아니다** — 설계(2026-08-19) 이후의 300 baseline 결정이 `docker-restore*.sh` 셋을 본문 없이 종료시켰다. 소유자 판정(2026-09-06)으로 전제에서 뺐다 |
  | 전용 BFF 자격 성공 | `POST /v1/admin/features` → **201**(2026-09-05 배포 스택). D2 lane이 매 실행 재관측한다 |
  | PinVi·일반 AdminBFF 거부 | `scripts/m01_activation_live_gate.py` — 잘못된 자격 조합 넷 전부 **403**(자격 없음 / proxy secret만 / create token만 / proxy secret + 틀린 token). body는 유효한 것을 보내 자격 검증이 body 검증보다 먼저 도는 것까지 확인 |
  | DB zero-write smoke | 같은 스크립트가 거부 실행 전후로 witness 8관계 count 대조 — **증분 0** |

  **되살릴 조건.** 300 baseline에 맞는 검증된 restore 경로가 생기면 설계 §10.3을 그대로
  다시 세운다. 그때 §8.3 재통과는 `scripts/m01_activation_preflight.py`가 그대로 수행한다 —
  그 스크립트를 남긴 이유가 이것이다.

  **위임한 것.** backup 축은 저장소에 구현돼 있으나 이 배포에는 backup root 설정도
  산출물도 없다(2026-09-06 실측). 활성화 전제로 세지 않으며 `T-VN-H49` 계열이 소유한다.
  origin/provenance 보존·불변성과 hard purge 정책은 `T-VN-M02`가 소유한다 — 2026-09-05
  격리 probe가 만든 Feature 1건이 `suppressed`로 남아 있고 hard purge는 그때까지 fence다.

## T-VN-41F1D-D2 — data-dependent admin live E2E (2026-09-06 완료)

- [x] T-VN-41F1D-D2 — 배포 스택에서 lane이 `phase: passed` / `status: complete`로 닫혔다
  (2026-09-06T01:47:03Z, runner exit 0, 1분 43초). pinset `48166bd2…` = Map `ab3640f8` +
  PinVi `f72eedf1`, host attestation `5b7f91ea…`, C7 executor 이미지 `sha256:337d9f77…`
  (라벨 `ab3640f8`), pinned runtime manifest `6ed900f5…`, rebuild journal `4cf269c4…`.

  | 축 | 값 |
  |---|---|
  | 스펙 | main·recovery 각 `{"counts":{"passed":2},"result":"passed"}`, 2/2 planned=observed |
  | evidence | `phase: evidence-validated` — 파일 집합 exact(10), lifecycle 48, FK 제약 18, 리포트 2 |
  | cleanup | `direct-cleanup`/`direct-audit` 모두 features·price_values·weather_values 0, FK reference 0 |
  | 잔여물 | lane 종료 후 **독립 측정**: acceptance 소유 row 0(features/aliases/places), acceptance 라벨 컨테이너 0, `kor-travel-map-afla-*` 0 |
  | lane 상태 | `BLOCKED.json`·`RESULT.json`·`ACTIVE.json` 모두 없음 |

  선행 축도 같은 pinset에서 재측정했다 — M01 ACL preflight **55/55**, D1 **11 passed**(29.9초).

  **왜 오래 걸렸나.** 두 겹이었다. (1) 해제 조건에 없던 `T-VN-M01` 활성화 의존 —
  스펙의 첫 write가 `POST /v1/admin/features`인데 kill-switch가 `false`였다.
  (2) `_validate_evidence`가 **스펙 통과 뒤에만** 도는 구조 — 계약 위반이 병렬로
  보이지 않고 배포 스택 실행 한 번에 하나씩 직렬로 드러난다. 그렇게 결함 열둘을
  지났고 그때마다 `tests/lint/`에 유도-결박-탐지 게이트를 남겼다. 상세는
  `docs/journal.md` 2026-09-06.

  **남긴 debt.** 수동 생성 Feature 1건(내 2026-09-05 422 격리 probe가 만든 것)이
  `suppressed`로 남아 있다 — hard purge는 `T-VN-M02`까지 fence돼 있어 지우지 않는다.
  helper의 `api-audit`/`purge` 경로는 여전히 이 lane이 부르지 않으며
  `T-VN-D2-API-AUDIT`가 소유한다.

## T-VN-41F1D-D1 — 최종 격리 리허설·provenance attestation (2026-09-04 완료)

- [x] T-VN-41F1D-D1 — 여섯 요구가 전부 현 candidate `e6b52db4`에서 충족됐다.
  일곱 image ID가 실행 중 컨테이너와 일치(전부 healthy), 세 schema head
  (`303_m05_payload_hash_domain`·`29b539ebc72a`·`20260824_0101`), v8 `cancel_probe`의
  canonical `409 PIPELINE_CANCELLATION_UNSAFE`/`finalized`, `fresh_finalize_operation_plan`,
  `resolved_compose_sha256 b8a504d6…`·`pinset e6b52db4…`·`e2e025`의 OpenAPI exact 대조,
  그리고 데이터 비의존 admin UI smoke **11 passed**(2026-09-04, 배포 스택).
  격리 M04/M05 attestation은 `e2e025`가 `status: passed`로 발행했다. 상세는
  `docs/journal.md` 2026-09-04.

## T-VN-FINAL-REBUILD — 최종 acceptance 배리어 (2026-09-04 해제)

- [x] T-VN-FINAL-REBUILD — B4를 재판정해 최종 acceptance 배리어를 **열었다**. 소유자 서명 2026-09-04.
  근거는 선언이 아니라 재계산 대조다 — v8 journal이 담은 `environment_sha256`·
  `compose_sha256`을 n150에서 재계산해 동일함을 확인했고,
  `resolved_compose_sha256`은 원본 compose·`.env`가 동일하고 렌더링을 소유하는 네 모듈
  (`compose_service.py`·`c6c_deployment.py`·`pinned_runtime_generation.py`·
  `runtime_execution_registry.py`)이 무변경이므로 구성상 불변이다. 상세는
  [`docs/tasks-acceptance.md`](tasks-acceptance.md)의 B4 절과 `docs/journal.md` 2026-09-04.
- 이 배리어가 푸는 순서: `T-VN-41F1D-D1` → `T-VN-41F1D-E` → `T-VN-41F1D-D2` → `T-VN-41C`.

## T-CI-DOCKERFILE-BUILD — 프로덕션 Dockerfile을 CI에서 실제로 빌드한다 (2026-09-04 완료)

- [x] 신설한 `docker-images.yml` job이 실제 PR에서 초록으로 도는 것을 확인했다 —
  #1142에서 `production Dockerfiles build` 13분 55초 pass, `cac35134`로 머지.
  해제 조건 C1~C6은 [`docs/tasks-acceptance.md`](tasks-acceptance.md)가 소유한다.

## 2026-08-31 — T-VN-M03 import child·격리 live acceptance 완료 이관

- [x] **T-VN-M03 — curated 동시 생성의 import 및 live acceptance 완료.**
  `302_m03_child_issuance`가 writer operation 확장·apply의 manual-skip/행별 좌표
  반환·linkage SECURITY DEFINER 기록기를 만들고, `curation_repo`가 결정적 child
  identity(§6.2)로 lock→claim→writer→apply→linkage→child result를 한 SERIALIZABLE
  transaction에 배선했다(PR #1127). 판정 근거: (1) 실 PostGIS 통합
  `test_tvn_m03_import_child_issuance.py` 2/2 — linkage 5축·decision
  종류(accepted/manual_feature_child)·item feature 결박 생존·child terminal result,
  (2) 사상 첫 manual-create 격리 live harness
  (`curation-import-manual-child.live.spec.ts`)가 n150 스택(302 head)에서 UI CSV
  업로드→preview→commit→admin REST 관측을 완주(2 passed). acceptance가 노출한
  feature 상세의 잠복 500(빈 tuple mock에 숨음)도 함께 수리했다.

## 2026-08-31 — 수리 완료·관측 의무 귀속으로 두 M05 task 이관

`T-VN-M05-MAP-HEALTH-TRANSPORT`와 `T-VN-M05-ADMISSION-TERMINAL`은 수리 측
조건(B1~B3, C1~C2)이 전부 `[x]`였고, 남은 한 칸(B4·C3)은 둘 다 "M05 성공 종료
receipt"라는 **같은 사건 하나**에 종속된 중복 부기였다. 그 관측 의무를 사건을 소유한
`T-VN-M05-ACTIVATION`의 A3에 귀속시키고 두 task를 닫는다
(`docs/reports/map-stall-root-cause-2026-08-31.md` §3 I-6, 적대 검증 CONFIRMED).

- [x] **T-VN-M05-MAP-HEALTH-TRANSPORT — `map_health_transport_failed` terminal 원인
  규명·보정 완료.** 원인은 Compose override의 `ports: !reset`(빈 값으로 되돌리는 태그,
  의도는 `!override`) 한 줄. host publish socket이 애초에 존재하지 않아 네 candidate가
  서로 다른 revision에서 동일 지점에 멈췄다 — source와 무관한 정적 결함이므로 source
  회전으로는 통과 불가능했다. 보정 후 phase가 PinVi 경계까지 전진했다.

- [x] **T-VN-M05-ADMISSION-TERMINAL — admission terminal 두 사례 보존·경계 통과 확인
  완료.** `7035b0b1`·`3d8d63e1`을 재실행 금지 목록과 함께 보존했고, 보정 후 후속
  candidate가 admission을 넘어 Map subscription·PinVi runtime까지 도달했다.

## 2026-08-31 — 원장이 이미 충족으로 판정한 두 M05 task 이관

`docs/tasks-acceptance.md`가 두 task를 각각 **판정: 충족**으로 기록하고 하나는 명시적으로
"`tasks-done.md` 이관 대상"이라고 적어 두었는데, `docs/tasks.md`에는 `[~]`로 남아 있고
완료 원장에는 엔트리가 없었다. 새 판정을 내리는 것이 아니라 그 드리프트를 해소한다.

- [x] **T-VN-M05-EXECUTION-IDENTITY-V6 — v6 execution identity 도입 완료**

  A1~A4 모두 충족(`docs/tasks-acceptance.md` 해당 절). 판정 근거는 A4다 —
  2026-08-29~30에 같은 Map/PinVi pair(`3916ebfd`/`b6af59f2`) 위에서 **Map 커밋 0개로
  9개 candidate**가 실행되고 phase가 단조 전진했다. v5 시대에는 candidate마다 의미 없는
  Map 문서 커밋이 nonce로 필요했고, 그것을 없애는 것이 이 task의 목적이었다.
  수용 판정문은 "남은 것은 문서 이관뿐이다"라고 적고 있었다 — 이 항목이 그 이관이다.

- [x] **T-VN-M05-ROLE-CATALOG-RESET — terminal 셋 보존 선언 완료**

  D1/D2 모두 충족. `31fe73ad`·`b22bfb8c`·`c6c73cdf` 세 candidate를 각각
  `target_not_isolated`·`foreign_membership`·`foreign_membership` terminal로 보존하고
  재시도하지 않는다는 것이 문서로 선언돼 있다. 수용 판정문은 "실행 잔여 없음 —
  `tasks-done.md` 이관 대상"이며, 왜 열려 있었는지는 문서에 근거가 없다고 적고 있었다.

## 2026-08-30 — T-VN-M05-MANAGER-PIN-ROTATION 완료 이관

- [x] **T-VN-M05-MANAGER-PIN-ROTATION — Manager pin rotation 단회 실행 완료**

  `030b12fc…` committed generation과 `6269138f…`·`53d4639f…` 단회 시도는 재실행하지 않는다. `53d4639f…`은 installed launcher execute bit 미보존으로 admission 이전에 종료했고 durable output·ledger·raw stderr가 없다. PinVi `41a36ee6…`·Map `9c64e862…`와 Manager canonical pinset `c1ad5a3e…`은 root-owned structured result launcher로 정확히 한 번 실행돼 `committed` 됐다(generation `8eedf171…`, Map application `300`, Map Dagster `29b539ebc72a`, PinVi `20260824_0101`).

  이 항목은 `tasks.md`에 `[x]`로 남아 있었으나 완료 원장에 엔트리가 없었다
  (`7fdad44c`가 `[/]`→`[x]`로 바꿨을 뿐 이관하지 않았다). `docs/tasks-rule.md` §4와
  `tasks.md` 서문("완료되지 않은 작업만 나열한다")에 맞춰 여기로 옮긴다. 내용 자체는
  `docs/resume.md`의 generation `8eedf171…` 기록이 뒷받침한다.

  같은 정합성 점검에서 `T-VN-FINAL-REBUILD`의 `[x]`도 발견했으나 그쪽은 **이관하지
  않았다** — 해제 조건 B1~B4가 충족된 것이 아니라 평면화(`6d671ef1`)로 삭제된 뒤
  완료 처리된 것이어서, `tasks.md`에서 열린 상태로 되돌렸다. 근거는
  [`docs/tasks-acceptance.md`](tasks-acceptance.md)가 소유한다.

## 2026-08-26 — T-VN-H46H application `300` 최종 수락

- [x] **T-VN-H46H — `0236` archive 기반 `300` 단일 root baseline·fresh rebuild 완료**

  Map PR #1066 exact head `cc81081ff2e540a6ad9c428a296515e1d79bc316`와 Docker-manager PR #207
  merge `ecfbddb7b3d1afbd74646abbaa4082dd70b53a42`를 고정한 paired candidate를 사용했다. PinVi
  `27fe2043b7b8e747fbb42d91e461ea462f930bb7`를 포함한 canonical pinset digest는
  `14a9a512836a48489146dc2bb0a04de309cf451b274b934d79805d171f83a193`다.

  n150에서 승인된 `ktdctl pinvi-pair rebuild-pinned --confirm`을 trusted Manager 설치본으로
  재개했고, durable journal `version=8`, generation `32`, transaction
  `5121a6d2-692d-4bd9-a5b0-d572d58c0f8f`, 최종 `phase=committed`를 확인했다. Map·PinVi
  runtime과 세 DB의 identity/provenance/readiness를 확인하고, 실제 브라우저에서 scenario
  catalog·backup-only 정책·운영 홈·운영 로그의 data-independent live UI 11개 테스트를 통과했다.

  사용자가 정한 정책에 따라 기존 application row의 내용·건수·업무상 무결성은 검증하지 않았고,
  이전 revision/기존 DB restore도 수행하지 않았다. 필요하면 fresh `300` schema에 source/ETL을
  처음부터 재적재한다. Features의 고정 ID·두 번째 페이지·컬렉션을 요구하는 data-dependent
  시나리오는 이 baseline 수락 범위에 포함하지 않는다. 전체 운영 acceptance는
  `T-VN-FINAL-REBUILD` 후속 barrier → `T-VN-41F1D-D1`/`T-VN-41F1D-E` →
  `T-VN-41F1D-D2` → `T-VN-41C` 순서로 별도 진행하며, M01~M05·최종 cutover의 독립 운영
  잔여도 이 task의 완료로 닫지 않는다.

## 2026-08-25 — active backlog 완료 하위 항목 정합성 이관

- [x] **범용 Feature 갱신 식별자에서 PinVi 전용 이름 제거** — 일반 feature-update,
  service-owned cache-target writer guard와 refresh protocol 검사는 relay-owned/service-owned
  용어로 통일했다. 실제 외부 시스템 값과 PinVi 전용 인증·curation 계약은 그대로 유지하되,
  범용 함수·상수·SQL 식별자에는 `pinvi`를 넣지 않는다.

- [x] **T-VN-H43 완료 하위 항목** — 2026-08-05 기준선·write-fence dump와 배포 후
  `0083` dump를 manifest/`pg_restore -l`/SHA-256으로 검증했고, 개발 장비 밖 사본도 대조했다.
  신규 빈 DB에서 필요한 superuser extension 선생성 절차와 실제 grantee는
  `docs/backup-restore.md` §2.2에 정본화했다. 현 n150은 손상 시 재적재 정책이므로 자동 주기화는
  완료 항목이 아니며, 실 production 전환 시 Manager #148로 재개한다.
- [x] **T-VN-41C 완료 하위 항목** — `cache-target:command` exact scope 분리와 양방향
  wrong-role `403`, snapshot first-page transaction·material watermark·share barrier, outbox lock
  order/DB relay sequence, bounded timeout·admission·foreground/hourly GC, inventory metric·alert를
  구현했다. n150 격리 검증에서 처리량 65,214 items/s, 유입 12,951 items/s, backlog 0/0과
  schedule 성공을 확인했고, 근거는
  `docs/reports/t-vn-41c-cache-target-gc-verification-2026-08-20.md` 및
  `scripts/verify-tvn41c-cache-target-gc.sh`가 소유한다.
- [x] **T-VN-41C relay 종결성 보강** — PR #1026(`b2e9c43a`)에서 typed violation reason,
  running cancel status event, stale generation 실패 event와 통합 테스트 격리를 완료했다. 열린
  `T-VN-41C`에는 새 exact pair의 isolated live acceptance·reconciliation·production consumer
  enable만 남긴다.
- [x] **T-VN-40 잔여 재확인** — T-VN-40A·mapping·40B·40C·인수 ①~⑤는 아래
  2026-08-19~21 완료 이력이 이미 소유하며, active backlog에는 독립 T-VN-40 실행 항목이 없다.
  T-VN-40을 언급하는 남은 문장은 T-VN-41C와 Lane M의 선행 계약·과거 조사 맥락일 뿐이다.

## 2026-08-22 — T-VN-H27 OPNsense HAProxy WebSocket tunnel timeout

- [x] **T-VN-H27 — #819 HAProxy WebSocket tunnel timeout 적용 완료**

  운영자 확인에 따라 OPNsense HAProxy의 Map·Geo·PinVi 등 외부 노출 API backend에
  `timeout tunnel 1h`를 적용했다. H27은 저장소 코드나 PR 변경이 아닌 edge 설정 task이며,
  적용 완료를 #819에 기록하고 이슈를 닫았다. OPNsense 설정은 저장소 외부에 있으므로
완료 근거는 운영자 확인으로 남긴다.

## 2026-08-22 — #990 planner cost 경계 false-fail 종결

- [x] **#990** — H50 dedup EXPLAIN gate의 relation별 semantic allowlist 수정은
  [PR #1036](https://github.com/digitie/kor-travel-map/pull/1036)에서 병합됐다. 이번 후속
회귀 단언은 작은 `source_entities` dimension의 정상 Seq Scan은 허용하고 대량
`features` Seq Scan은 거부해 planner 비용 경계의 재발을 막는다.

## 2026-08-22 — T-VN-41S / #922 snapshot materialization 확장 완료

- [x] **T-VN-41S — snapshot materialization streaming·audit compaction 확장.** PostgreSQL
  server cursor 2-pass·incremental Merkle·bounded memory 경로, `0231` receipt/material/item
  정규화와 양방향 material 공유, terminal `410` repository 경로를 완료했다.
  `0236_tvn41s_compaction_drained`의 `compaction_drained_at`·partial index로 GC backlog를
  배출 중인 material로 한정하고, 마지막 receipt 삭제 trigger의 `orphaned_at`·partial index로
  orphan backlog도 상태 조회로 한정했다. one-way fence·fail-closed `ops` ACL remediation을 고정했다.
  item 500,000/material 56 MiB admission과 EXPLAIN·n150 soak evidence도 반영했다.
  후속 DB 적대 리뷰에서 발견한 live material item DELETE 우회도 `0236` 부모 row-lock
  trigger로 차단했다. compaction 표시 전 DELETE는 거부하고 표시된 material만
  compactor의 ordered·bounded batch가 배출한다(표시 후 raw DELETE 자체는 상태상 허용).
- [x] 검증 근거: snapshot repository·migration boundary unit 44건, material fence
  integration 5건, compaction-drained integration 10건, ACL/metadata integration 14건,
  cache-target stream integration 40건,
  EXPLAIN integration 1건, API router targeted 14건 통과. `ruff`, `mypy --strict`
  (147 source files), `lint-imports`, migration graph check 및 redaction check 통과.
- [x] service spec의 도달 가능한 `410` 선언과 실제 admission 상한 설명을 Map 쪽에서
  반영했다. `openapi.service.json`/`openapi.json`/admin 타입을 재생성했고, PinVi
  cross-repo re-vendor와 paired acceptance는 `T-VN-41C`가 소유하므로 관련 receipt는
  재검증 전까지 `pending`으로 유지한다.
  후속 orphan/DELETE 무결성 게이트는 [PR #1051](https://github.com/digitie/kor-travel-map/pull/1051),
  merge `db319a4798229098d04e68e3ac64338183ad547f`로 병합했다(CI 8/8, 전문 적대 리뷰 P0/P1=0).

## 2026-08-22 — T-VN-M01~M05 구현 병합 이관

- [x] **T-VN-M01~M05 구현 — Map PR #1029 (`57c9d99a`)**

  `0226_m01_manual_feature_create`부터 `0227` provenance, `0228` curation combined
  writer, `0233` 범용 Feature 요청 큐, `0234`~`0235` 수동/provider dedup evidence·delivery까지
  단일 migration head로 병합됐다. API·Admin BFF·service OpenAPI/generated types·ACL/restore
  manifest·ORM/repository와 M01/M03/M04/M05 통합 회귀가 같은 PR에 포함됐다.

  구현 게이트는 fresh migration graph, immutable claim/origin 및 hard-purge fence, M03
  SERIALIZABLE 원자성/exact conflict, M04 submit→approve/reject command, M05 event/lease/ACK
  계약으로 고정됐다. 관련 PinVi direct-create fail-close와 최초 consumer 준비는
  [PinVi #458](https://github.com/digitie/pinvi/pull/458)에서 병합됐다.

  아래 잔여는 구현 미완료가 아니라 운영 활성화·교차 저장소 재결박·격리 live acceptance다.
  `tasks.md`의 M01~M05 부분완료 항목과 `T-VN-41C`가 route flag, restore/purge 실측, import
  child-command, paired request→approval/reconciliation receipt를 각각 소유한다.

## 2026-08-21 — T-VN-40·C7 완료 잔재를 진행 백로그에서 이관

- [x] `T-VN-40A`·mapping·40B·40C와 인수 ①~⑤의 완료 근거는 이 파일의 2026-08-19~21
  엔트리에 모두 보존했다. 진행 백로그에 중복돼 있던 Wave 2 완료 서술은 제거해, `tasks.md`에는
  열린 `T-VN-39`와 Lane M/41 작업만 남겼다.
- [x] `T-C7-BROWSER-EVIDENCE`·`T-C7-SCOPE-REGISTRY`·`T-C7-LIVE-SERIAL`·
  `T-FE-MOCK-MANIFEST`의 완료 근거도 아래 2026-08-21 정리 엔트리가 정본이다. 남은
  `T-FE-MOCK-FLAKE`만 진행 백로그에서 추적한다.

## 2026-08-21 — `0229`~`0232` prod 배포로 T-VN-40B·T-VN-C05-CATALOG-KEY 종결

- [x] **`T-VN-40B` — source rule `curated` action 퇴역. prod 적용까지 완료.**
  코드 착지 `fa22d0fe`(PR #1035, 2026-08-20) → **prod 적용 2026-08-21**. `0229`·`0230`·
  `0231`·`0232`가 한 배포로 올라가 prod head = `0232_tvn37d_notice_empty_range`이고
  manager `.env`의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`도 같다.
  `feature.curated_source_rules` 53행이 전부 `default_action='candidate'`이고 `'curated'`는
  0행, CHECK는 `('candidate','ignore')`만 허용한다.
  `GET /v1/admin/curated-source-rules`는 **500 → 200**(53항목 전부 `candidate`)으로 회복했다.
  1차 시도가 `0230`에서 중단·롤백된 건은 아래 `T-VN-C05-CATALOG-KEY`가 해소했다.

- [x] **`T-VN-C05-CATALOG-KEY` — `0230`이 대리키를 계약으로 적었다.**
  `provider_dataset_id`는 `Identity(always=True)` 대리키인데 `0230`이 70~74를 SQL에
  하드코딩했다. 정본 identity는 자연키 `uq_provider_datasets_identity (provider,
  dataset_key)`이고 번호는 환경마다 다르다 — baseline seed는
  `python-datagokr-api/standard_special_streets`를 69번으로, prod는 73번으로 들고 있었다.
  그래서 prod 배포가 이 migration에서 멈췄고, alembic이 전체를 한 transaction으로 감싸므로
  30회 재시도가 매번 전량 롤백됐다.

  가드가 없었다면 dataset은 `ON CONFLICT (provider_dataset_id) DO NOTHING`으로 건너뛰고
  operation·scope만 같은 숫자로 들어가 **남의 dataset에 달라붙었을** 것이다. CI가 늘
  초록이었던 이유는 통합 테스트 DB가 `0200`의 `seed.sql`로 만들어져 C05가 이미 70~74로 서
  있는 DB만 봤기 때문이다 — 그 DB에서 이 migration은 순수 no-op이었다.

  PR #1042(main `e47a389f`)로 자연키 기준 재작성. dataset은 identity sequence가 번호를 매기고
  operation·scope는 자연키 JOIN으로 되찾는다. `_SEQUENCE_SQL`은 되감지 않고 INSERT보다 먼저
  돈다. 사후 단언 4가지(dataset·operation·scope 존재 / 기존 dataset 계약 일치 / operation
  `is_enabled`)를 둔다.

  규칙 정본은 [ADR-096](adr/096-catalog-identity-is-the-natural-key.md).
  게이트는 `tests/integration/test_tvn_c05_catalog_migration.py`(10건)과
  `tests/lint/test_alembic_surrogate_identity_literals.py`(재발 차단).
  prod 덤프 587M 사본으로 전 구간 리허설(runtime ACL 조정 포함 exit 0) 후 배포했고,
  실배포 실측이 리허설 예측과 한 항목도 어긋나지 않았다. prod C05는 **104~108**을 받았고
  `provider_dataset_id 73` 선점자는 자식 0으로 무사하다.

## 2026-08-21 — 완료 task 백로그 정리

- [x] `T-VN-H50` — planner 인덱스 선택 CI flake를 semantic SQL join gate로 안정화했다.
  PR [#1036](https://github.com/digitie/kor-travel-map/pull/1036), merge
  `2f122e9b3e2358668ffe4a4cbc49051bb53a6838`; Python 3.11~3.13, fixture replay,
  PostGIS integration, frontend, lint, OpenAPI drift 등 8개 검사가 모두 성공했다.
- [x] `T-VN-C05A`~`T-VN-C05D` — 산림청 route·산악기상·산불위험 V2·산사태 예보발령
  dataset 연결을 완료했다. PR [#1037](https://github.com/digitie/kor-travel-map/pull/1037),
  merge `739bf2fcb8c891c14cad9081db44be9f8ab01599`; provider pin과 `0230` catalog를
  포함한 8개 검사가 모두 성공했다.
- [x] `T-C7-BROWSER-EVIDENCE` — #995 잔여 browser-only C7 소유권·preflight 증거를
  이식했다. PR [#1038](https://github.com/digitie/kor-travel-map/pull/1038), merge
  `cf4e3d3bb7b95856c07d233f9b2e2a01e3cf3ac1`; C7 cleanup ownership, KMA preflight와
  mocked checkpoint를 포함한 8개 검사가 모두 성공했다.
- [x] `T-C7-SCOPE-REGISTRY`·`T-C7-LIVE-SERIAL` — scope 선언·조회 정본화와
  `external_system:c7-e2e` cross-worker 잠금을 완료했다(PR #1038).
- [x] `T-FE-MOCK-MANIFEST` — mocked checkpoint manifest를 실측 인벤토리 285,
  baseline `5c647f69…`, `expected-failures=0`으로 재고정했다(PR #1038). 남은
  `/v1/ops/logs` 간헐 실패는 `T-FE-MOCK-FLAKE`로 분리해 `tasks.md`에서 추적한다.
  여기의 285와 `5c647f69…`는 PR #1038 당시 suite 기준의 역사적 완료 증거이며 현재
  manifest 값이 아니다. baseline 경계 정리 뒤의 현행 284개·`0905c853…` 관측값은 PR #1077에서
  별도 재고정했고, 실제 logs acceptance의 잔여 인증 blocker는 계속 `T-FE-MOCK-FLAKE`가
  소유한다.

## 2026-08-21 — T-VN-37D notice empty range 표현

- [x] T-VN-37D — **notice 발효 전 철회를 empty range로 표현**

  `feature.feature_notices.valid_during`을 `valid_start_time`/`valid_end_time`에서
  파생하는 stored `tstzrange`로 추가했다. 정상 범위는 `[start, end)`, `end < start`인
  발효 전 철회는 `empty`, 두 경계가 모두 없으면 NULL이다. provider가 만드는 실재
  상태에 순서 CHECK를 추가하지 않았고, writer가 파생 컬럼을 직접 쓸 수 없도록
  generated column으로 고정했다.

  제품 의미는 기존 read contract를 보존하는 것으로 결정했다. 미래 발효 공지는
  계속 노출하고 active/admin read는 `valid_end_time <= now()` 비교를 유지한다.
  `NoticeDetail`/OpenAPI 응답은 변경하지 않았다. ADR-095, migration
  `0232_tvn37d_notice_empty_range`, ORM metadata와 integration regression이 정본이다.
  적대 리뷰에서 발견한 admin candidate JSON 누출은 내부 `valid_during` 제외로 고쳤고,
  notice timestamp는 KST 고정으로 직렬화해 세션 timezone에 따른 representation ETag
  변동도 막았다. migration lock timeout과 NULL/one-sided/equal/admin 회귀도 추가했다.

## 2026-08-20 — T-VN-40C 및 인수 ③~⑤ 종결

> **2026-08-20 정정(사용자 지시)**: 이 절은 원래 `T-VN-40B`를 함께 종결로 적었으나,
> 40B에는 실측으로 확인된 잔여가 있어 `tasks.md`로 되돌렸다. 종결 근거였던 "candidate
> lifecycle 전환"은 맞지만, **source rule의 `curated` action 퇴역**은 그 문장이 다루지
> 않는다 — 2026-08-20 시점 prod에는 `default_action='curated'` 35행이 남아 있었고 CHECK도 그 값을
> 허용한다(write 경로는 이미 거부). 아래 서술은 40C 범위로 읽는다.

- [x] T-VN-40C — **legacy surface 물리 제거**

  40C의 legacy overlay·snapshot·trigger·`legacy_projection_id`·
  rekey 예외·legacy ACL 제거를 한 흐름으로 닫았다. PR [#1023](https://github.com/digitie/kor-travel-map/pull/1023),
  merge `4c50fe86`의 `0225_tvn40c_physical_removal`이 정본이며, static-zero/runtime 검증과
  PinVi user spec 재-vendor를 포함한 paired receipt 후속은 아래 인수 항목에서 봉인했다.

- [x] T-VN-40 인수 ③~⑤ — **live/soak·exact receipt·prod 적용**

  ③은 `f00e7f48`에서 6-spec/17-case strict live를 통과했고, ④는 PR [#1024](https://github.com/digitie/kor-travel-map/pull/1024),
  merge `294db534`와 PinVi #459의 재-vendor 뒤 exact receipt `complete`를 봉인했다. ⑤는 prod head
  `0225_tvn40c_physical_removal` 적용과 legacy zero·보존 mapping 4,424건·collection 59개·API 표면
  smoke까지 확인했다. mocked manifest·C7 scope registry·live serial은 PR #1038에서
  완료 이관했고, `/v1/ops/logs` 간헐 실패만 `tasks.md`의 `T-FE-MOCK-FLAKE`로 계속 추적한다.

## 2026-08-19 — backlog 전면 재대조·완료 이관

- [x] T-VN-C03 — **보조 dataset 5종 제품 범위·authoritative source 결정**

  `python-krforest-api@f9254e6`, `python-khoa-api@20c7207`과 공공데이터포털 현행
  계약을 대조했다. 산림청 등산로·둘레길은 `forest.go.kr` 파일 `PBD0000041` /
  `PBD0000031`의 route 2종으로 구현하고, 산악기상은 `15084696`, 산불위험은 현행
  V2 `15084817`, 산림 notice는 실제 발령·해제 source인 산사태 예보발령
  `15074798`로 한정한다. 각각 열린 `T-VN-C05A`~`C05D`로 분리했다.

  `python-khoa-api@20c7207`의 46개 KHOA ODMI public catalog에는 공지 사건 API나
  typed notice model이 없다. 해양 지수·관측값에서 임의 threshold로 공지를 합성하지
  않으며 `khoa_coastal_notices` 계획은 **미구현 폐기**했다. 새 authoritative event
  source가 생기면 기존 이름을 되살리지 않고 별도 제품 결정으로 다시 진입한다.
  산림청 등산로 source도 통제·폐쇄 여부가 실시간이 아니라고 명시하므로 route
  geometry에만 쓰고 안전 notice나 이용 가능 상태로 승격하지 않는다.

- [x] T-VN-H44 — **복원 리허설 드릴 정착**

  `0083` 백업은 별도 PostGIS에서 확장 선생성 → restore → manifest 일치 → 결손
  감지 → 재생성까지 5단계를 통과했고, `0104` 백업도 341초 restore와 예상된
  `x_extension` 오류 1건 외 manifest 6개 항목 일치를 통과했다. 3차 드릴은
  restore·manifest를 다시 통과했으나 24시간 이상 단일 transaction 전량 replay와
  필드 24개를 잃는 부분 raw replay가 둘 다 복구 경로가 아님을 확정했다.

  반복 절차와 함정은 [`backup-restore.md`](backup-restore.md) §10이 소유한다.
  최소 월 1회 트리거는 현 n150을 실 production으로 보지 않고 손상 시 재적재하는
  2026-08-06 정책에 따라 H43/manager #148의 **실 production 전환 조건**으로 남긴다.
  이 보류는 백업본이 실제로 복원되는지를 실증하는 H44를 더 이상 열어두지 않는다.

- [x] T-VN-H45-후속 — **Alembic 1.19 CHECK 비교 적응**

  PR [#1019](https://github.com/digitie/kor-travel-map/pull/1019), merge `82fbe2f6`.
  Alembic 1.19.1 fresh PostGIS에서 재현한 named CHECK removed 208건 / added 167건을
  comparator 비활성화 없이 해소했다. PostgreSQL의 실제 63-byte 절단 이름까지 포함해
  DB catalog와 ORM CHECK 373개를 1:1로 정렬하고, raw SQL migration이 소유하던 43개
  CHECK도 metadata에 명시했다. 이 과정에서 `curation_rule_reconcile` revision 식이
  후속 migration보다 뒤처진 실제 의미 drift 1건도 찾아 DB 정본에 맞췄다.

  Alembic 의존성은 column-bound fix가 포함된 `>=1.19.1,<1.20`으로 전환했다. fresh
  `upgrade head → alembic check`뿐 아니라 ORM 식을 임시 table에 설치해
  `pg_get_constraintdef`로 live catalog와 비교하는 의미 gate를 추가했다. CHECK 전체
  제외나 by-name plugin 전역 비활성화는 도입하지 않았다. CI 8개를 통과했다.

- [x] T-VN-H45-후속-①~④ — **provider 다건 재시도·quota·schedule 강건화**

  PR [#999](https://github.com/digitie/kor-travel-map/pull/999), merge `284fd10c`. KHOA
  시도×페이지와 KMA/DataGoKr/AirKorea 다건 경계에 비례형 공유 `RetryBudget`을
  적용하고, data.go.kr `resultCode=22`를 비재시도 quota로 정정했다. provider
  WARNING을 비밀 노출 없이 Dagster event에 결선했고 KMA 5종·airkorea schedule에
  active-run coalescing과 7,200초 runtime 상한을 같이 고정했다. Alembic 1.19 적응은
  당시 독립 `T-VN-H45-후속`으로 분리했고 위 항목에서 완료했다.

- [x] T-VN-C03-doc-drift — **provider module 인벤토리 표·회귀 lint 정렬**

  PR [#991](https://github.com/digitie/kor-travel-map/pull/991)이 stale provider 3개를 제거하고
  누락 모듈 6개와 보조 예외 2개를 정확히 구분했다.
  `tests/lint/test_providers_docstring_inventory.py`가 "표 + 명시적 예외 = 실제 모듈"을
  계속 강제한다. 보조 dataset 5종의 제품·source 결정은 열린 C03이 소유한다.

- [x] T-VN-40A / T-VN-40A-fence — **curation canonical 기반·legacy write 3층 차단**

  기반 구현 PR #974 뒤 PR [#994](https://github.com/digitie/kor-travel-map/pull/994),
  merge `3e0732b3`가 `curated_features` legacy write를 ACL·static inventory·route `410`으로
  차단했다. runtime-role merge를 command-owner `SECURITY DEFINER` procedure로 복구하고
  API runtime에만 executor를 제한했으며, 적대 리뷰 2명과 CI 8개를 통과했다.

- [x] T-VN-40-mapping — **identity mapping loader·prod mapping 4,424건**

  PR [#996](https://github.com/digitie/kor-travel-map/pull/996), merge `fbc31f2f`. `0223` loader가
  legacy projection 4,424건을 불변 mapping으로 적재했고, precheck·lock timeout·merge
  guard·migration 전체 rollback을 검증했다.

- [x] T-VN-40-인수-①/② — **prod migration·PinVi mapping 봉인·59 collection import**

  PR #1001의 prod `0104→0223` 단일 transaction migration과 PR #1006의 PinVi
  mapping receipt(root `69eb85ec…`, 4,424 item), legacy preflight `ready=true`, canonical
  collection 59개/POI 4,424 import를 완주했다. **2026-08-19 당시** 활성 잔여였던 ③
  live/soak → ④ exact receipt → ⑤ 40C physical removal도 다음 날 완료 이관했다.

- [x] T-VN-41A / T-VN-41B — **source generation·restore epoch·transaction-coupled outbox**

  PR [#975](https://github.com/digitie/kor-travel-map/pull/975), merge `4672aa96`, CI 8/8.
  source generation·restore epoch와 target/link/update transaction 내 outbox writer를 병합했다.
  final exact-pair evidence·production consumer enable·reconciliation은 열린 `T-VN-41C`가 소유한다.

- [x] T-VN-EXT-PINVI-215 — **PinVi 외부 follow-up 종결 동기화**

  PinVi #215는 PR #446 병합과 Android Dev Client smoke 뒤 2026-08-19 닫혔다.
  위치 동의 gate 등 남은 사항은 PinVi T-320 등으로 분기됐으며 Map lane이
  더 이상 #215를 추적하지 않는다.

- [x] T-VN-C02 — **폐기(won't-do): arm64 multi-arch 실배포 검증**

  Dockerfile 하드코딩 없음·`linux/amd64,linux/arm64` 기본값·aarch64 wheel 가용성
  정적 점검만 완료했다. registry push와 arm64 기동은 실행하지 않았고,
  2026-08-19 사용자 결정으로 추가 추적을 폐기했다. 이는 2026-06-29의
  T-229 종결 결정을 재확인한 것이며 실행 검증 성공을 의미하지 않는다.

- [x] T-VN-H18 — **폐기(won't-do): GitHub approval provenance 자동 강제**

  branch protection 또는 merge 전 verifier로 latest-head `APPROVED` review를 강제하는
  자동화 task를 2026-08-19 사용자 결정으로 폐기했다. 과거 PR의 없는 approval
  provenance를 복구했다거나 보호 규칙을 설정했다고 기록하지 않는다.

## 2026-08-19 — T-VN-M00 수동 Feature 생성 설계 완료

- [x] T-VN-M00 — **수동 Feature 생성 2차 설계·전문 검토 완료**

  [`설계 보고서`](reports/t-vn-m00-manual-feature-create-design-2026-08-19.md)와
  [ADR-093](adr/093-manual-feature-origin-and-identity.md)이 서버 UUIDv7, exact identity claim,
  검증된 `manual_admin` origin, 생성 전용 BFF 자격, 원자적 DB writer, current→target bridge,
  forward-only migration·backup/restore·ACL·오류 계약을 고정한다. ADR은 M01 구현·계약 검증 전까지
  `proposed`를 유지한다.

  API 계약과 DB/동시성 전문 검토자는 네 차례 검토 끝에 같은 exact checkpoint
  `2aa17c27d4f09701a9639ea0ea449abbfefc0be2`에 각각 P0~P3 0건 최종 GO를 선언했다. 설계와 완료
  이관은 draft PR [#1012](https://github.com/digitie/kor-travel-map/pull/1012)이 소유했다.
  구현 병합은 아래 T-VN-M01~M05 이관 엔트리가 소유하며, 활성화·paired acceptance 잔여는
  진행 백로그의 부분완료 항목으로 추적한다.

## 2026-08-19 — T-VN-H46G buildx image commit provenance 완료

- [x] T-VN-H46G — **runtime image 입력·revision을 exact source commit에 결박**

  API·admin·Dagster web·daemon의 공통 build 경계가 exact 40자 commit을 build arg와 OCI
  `org.opencontainers.image.revision` label에 강제한다. 상태를 검증할 수 없거나 dirty인
  worktree는 builder mutation 전에 거부하고, 실제 입력은 commit의 단일 `git archive` tar로
  고정해 ignored 파일 혼입과 순차 build TOCTOU를 차단한다.

  OCI 로컬 출력은 API·admin·Dagster별 archive로 분리하고, 제거된 단일 파일 env는 조용히
  무시하지 않고 migration 오류를 낸다. archive 생성 중 INT/TERM에도 writer를 회수하고 임시
  tar를 지운다. 새 provenance 정본은 만들지 않고 기존 C6c/C7의 네 role image ID·revision →
  `map_source_revision` 비교를 그대로 쓴다.

  전문 적대 리뷰어 2명은 exact head `84349b4c`에 P0~P3 잔여 없이 GO했다. 실제 32.7 MB
  tar-stdin BuildKit 3종과 Dagster web·daemon 동일 OCI digest, signal·실패 cleanup을 독립
  재현했다. 로컬 root unit 2,300개, focused 15개, 인접 C7 포함 독립 95개, Ruff·strict mypy
  3패키지·import-linter를 통과했다. 구현·완료 이관은 draft PR
  [#1007](https://github.com/digitie/kor-travel-map/pull/1007)이 소유한다.

## 2026-08-19 — T-VN-H46F admin UI Geo 자격증명 경계 완료

- [x] T-VN-H46F — **admin UI Geo proxy를 server-only 자격증명 경계로 결선**

  Next.js `/api/geo` BFF가 server-only `KOR_TRAVEL_GEO_API_KEY`만 읽고 browser query의
  `key`를 제거한 뒤 `X-KTG-API-Key`로 전송한다. 키 형식 오류와 Geo의 401 또는 400
  `E0100 field=key`는 원문을 숨긴 typed 503으로 fail-close한다. root Compose·frontend
  Docker build/fingerprint·buildx·load-env·live/mocked E2E에서 browser-global
  `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY` 운반 경로를 제거했다.

  Docker Manager는 충돌한 draft #173을 PR #183(merge `4f5cbb44`)으로 supersede해 root
  source → UI server-only alias와 C6c service 격리를 결선했다. Map 변경은 admin redesign
  PR #1003 merge `da2c740a` 위에 재배치했다. 전문 적대 리뷰어 2명 GO, frontend unit
  336개·Map 집중 37개·BFF route 14개와 원격 CI 8개를 모두 통과했고, PR #1004는
  merge `817cfeae`로 병합됐다.
  별도 buildx OCI commit provenance label은 열린 `T-VN-H46G`가 소유한다.

## 2026-08-18 — backlog 전면 재대조 완료 이력 이관

- [x] T-VN-H25B — **공식 curation CSV 역반영·매칭 재실행**

  검증 가능한 5건만 CSV에 반영하고, matcher·manifest를 재생성했다. 주소 축은 시군구 대조로
  보강했고 provider provenance의 기존 축 한계는 import-act provenance로 분리했다. 남은
  Feature 생성·prod import는 열린 `T-VN-H34`와 `T-VN-M00`~`M03`이 소유한다.

- [x] T-VN-H46B/C/D/E — **geo 자격증명 복구·의미 검증·daemon drift·공개 키 현행 유지**

  VWorld fallback을 제거하고 API 기동의 geo credential 의미 검증을 결선했으며, daemon의
  schema drift는 image lag으로 판정·종결했다. data.go.kr 키는 노출 정황이 없어 현행 유지로
  결정했다. 당시 남긴 Node geo proxy는 2026-08-19 `T-VN-H46F`로 완료했고, buildx commit
  provenance label만 열린 `T-VN-H46G`가 소유한다.

- [x] T-VN-H47/H48 — **prod dump 위생·n150 임시 DB 정리**

  dump 권한·0바이트 산출물·보관 위치를 정리하고, 일회성 DB는 `tmp-` 접두어와 `--rm`을
  기본으로 하는 규약을 문서화했다.

- [x] T-VN-C01 — **사문화된 H35 cutover helper 퇴역**

  H35 helper 17개를 제거하고 살아 있는 `h35-db-identity-v1` 계산은
  `core/database_identity.py`와 golden-vector 검증으로 보존했다. 퇴역 경로 재도입을 막는
  image contract와 dangling 인용 정정도 포함한다.

- [x] T-VN-C04 — **SPRINT 헤더·원격 브랜치 정합**

  SPRINT 상태 헤더를 정본과 맞추고 미개봉 npm 브랜치를 정리했으며, 오래된 원격 브랜치를
  382개 정리했다.

## 2026-08-16 — T-VN-H46A alembic squash 병합

- [x] T-VN-H46A — **alembic squash: 체인 109개 → `0200_schema_baseline`**

  PR [#978](https://github.com/digitie/kor-travel-map/pull/978)이 `main`에 병합됐다. 정본은
  `alembic/versions/0200_schema_baseline.py` docstring과
  `alembic/legacy_versions/README.md`이며, 빈 PostGIS DB catalog 동등성·ACL digest·legacy
  execution/build artifact 차단을 CI로 고정한다. 당시 후속 H46B~E도 2026-08-18에 종결했고,
  당시 남은 `T-VN-H46F`는 2026-08-19 완료했고, 현재 열린 후속은 `T-VN-H46G`다.

## 2026-08-13 — T-VN-34/35/36 Wave 2 최종 배포·인수 완료

> 2026-08-13 n150 prod에서 `0087_route_area_subtypes` →
> `0104_tvn36_final_fence` forward migration과 runtime 배포를 완료했다. 이력·정확한
> 측정값은 [`resume.md`](resume.md)의 같은 날짜 기록과
> [`journal.md`](journal.md)의 배포 기록이 정본이다. squash 후 실행 정본은
> `0200_schema_baseline`과 bridge다.

- [x] T-VN-34A/B/C — **직교 상태 schema·public projection·writer/API/UI cutover**

  final stacked cutover와 fresh clone live 인수를 마쳤다. 3축 상태 계약, public
  projection, runtime principal 분리는 이후 legacy write-fence까지 유지한다.

- [x] T-VN-36A/B/C/D·live — **field override 단일화·destructive fence·격리 clone 인수**

  effective projection 단일화와 기존 field-level freeze 경로 제거를 완료했고,
  candidate-head clone live 인수도 통과했다.

- [x] T-VN-35/34/36-deploy — **`0104` prod cutover**

  1,008,852 feature를 보존한 in-place migration(1시간 32분 39초) 뒤 api/ui/dagster/daemon
  4개 런타임이 healthy 상태로 전환됐다. post-deploy baseline dump와 manifest를 남겼다.
  여기서 남겨뒀던 "공유 PostgreSQL에서 전용 인스턴스로의 이전"은 **2026-08-17에
  완료**됐다 — prod PostgreSQL을 프로젝트별 전용 instance 4개로 나눴고(geo `12500` ·
  concierge `12600` · **map `12700`** · pinvi `12800`, 전부 loopback) `5432`를 듣는 것은
  이제 없다. 근거는 docker-manager **ADR-37**, 경과는 `docs/resume.md` 2026-08-17 항목.

## 2026-08-12 — T-VN-38 weather·price current summary 병합

> PR [#971](https://github.com/digitie/kor-travel-map/pull/971), merge
> `8dc2b24a`. 최종 source `bef509d` 기준 CI 8개와 n150 전용 clone live를 다시
> 통과한 뒤 머지했다. 남은 held-component 제거는 `T-VN-39`가 소유한다.

- [x] T-VN-38A — **weather current summary**

  bitemporal 원본 이력을 유지하면서 canonical dataset/source revision 기준의 current
  weather summary와 reconciliation을 도입했다.

- [x] T-VN-38B — **price current summary**

  `provider + price_domain + product_key` identity의 current price summary와
  restore/backfill generation 구분을 도입했다. weather와 같은 transaction advisory lock으로
  전역 projection의 오래된 winner 역전을 막았다.

- [x] T-VN-38C — **bbox/detail set-based cutover**

  weather/price read를 summary set join으로 전환하고, freshness·cardinality·EXPLAIN 및
  9개 frozen artifact의 CRLF byte guard를 고정했다. Dagster raw provider response는
  `date`·`time`·`Decimal`과 immutable mapping을 JSON 보존 가능 형태로 정규화한다.

  검증: GitHub CI 8/8 green(3 Python unit matrix, PostGIS integration, fixture replay,
  lint, OpenAPI, frontend), 적대 리뷰 2인 P0/P1=0. n150 전용
  `ktm-tvn38-db:18732` clone에서 main/recovery Live UI E2E 각각 2/2, `phase=passed`,
  BLOCKED 없음, startup migration 불변과 production compose 제외를 실증했다.

## 2026-08-12 — T-VN-33 provider dataset 삼중 identity 정본 전환 병합

> PR [#966](https://github.com/digitie/kor-travel-map/pull/966), merge
> `9bbb74d`. 상세 설계·결함 회고는
> [`reports/t-vn-33-provider-datasets-single-pr-plan-2026-08-06.md`](reports/t-vn-33-provider-datasets-single-pr-plan-2026-08-06.md)와
> `journal.md` 2026-08-11 기록이 정본이다.

- [x] T-VN-33 — **provider dataset·operation 정본과 immutable observation/head 전환**

  `33-A`~`33-E`를 하나의 forward-only PR로 완료했다. versioned dataset/operation seed,
  canonical `(provider_dataset_id, sync_scope, operation_key)` membership, immutable source
  entity/record/head, writer·reader·admin projection cutover 및 legacy physical fence를
  `0089`~`0092`로 일괄 적용했다.

  검증: 로컬 CI mirror 25/25와 GitHub CI 8/8 green, 적대 리뷰 3렌즈 P0/P1=0. n150
  격리 DB에서 fresh migration·API live 12/12·admin UI live 10/10을 확인했다.

## 2026-08-12 — T-VN-37 notice 계보 key 물화 병합

> PR [#968](https://github.com/digitie/kor-travel-map/pull/968), merge `490a2482`.
> empty range 표현은 별도 보류 task `T-VN-37D`로 남긴다.

- [x] T-VN-37 — **계보 key 물화 + 인덱스 probe**

  notice scope의 `source_records.lineage_key`를 DB 트리거로 파생하고 표현식 인덱스와
  materialized reconcile CTE로 JSON 재계산 병목을 제거했다. 결과 집합과 reconcile 종료
  상태를 유지하면서 대규모 목록과 reconcile 시간을 각각 20.4초→0.19초,
  118.4초→0.36초로 줄였다.

## 2026-08-12 — T-VN-H45 KMA/airkorea 호출 강건화 완료 이관

- [x] T-VN-H45 — **KMA/airkorea 대량 순차 upstream 호출 강건화**

  간헐 오류율과 N격자 all-or-nothing 재시도로 생기던 생존확률 붕괴를 단건 호출 경계의
  유한 재시도로 고쳤다. 평문 HTTP 종료는 upstream 정본 HTTPS 전환과 pin 갱신으로
  해결했고 KMA 4종 SUCCESS·55,755 값 유입을 실증했다. airkorea 504는 upstream
  `SERVICETIMEOUT_ERROR`로 분류해 관찰만 한다. 다건 fetcher와 quota telemetry 확장은
  열린 `T-VN-H45-후속`으로 분리했다.

## 2026-08-06 — T-VN-41F1D-C3 Manager dynamic fixture n150 결선

- [x] **T-VN-41F1D-C3 — Map fixture lifecycle의 v5 durable transaction 결선**

  Manager PR #167의 최신 Map typed-subtype pin으로 n150 파기형 `rebuild-pinned` generation을
  committed했다. Map application `0087_route_area_subtypes`, Map Dagster `29b539ebc72a`, PinVi
  `20260804_0049` schema head 및 일곱 runtime container health를 확인했다. Manager v7 journal은
  Map fixture `armed → consumed → finalized`와 PinVi canonical cancel의 정확한
  `409 PIPELINE_CANCELLATION_UNSAFE` outcome을 기록했다.

  Map UI 로그인 POST는 `200`과 session cookie를 반환했고, n150 data-independent live UI E2E는 운영 홈·
  파이프라인 catalog 6건, Feature 목록·지도 초기 surface 10건을 통과했다. 새 DB에 source/ETL data를
  의도적으로 적재하지 않았으므로 고정 curated/feature ID를 요구한 suite 실패는 C3 runtime failure와
  분리해 F1D-D에서 final-schema ETL 재적재 뒤 재실행한다.

## 2026-08-06 — T-VN-35 A-D kind별 typed subtype 분해 병합

> 2026-08-06 A-D 단일 PR로 종결(ADR-086). 원안 대비 **재해석 2건**이 있고, 근거는
> 실측이다 — 아래 각 항에 적었다. 정본 설계는 `docs/adr/086-typed-feature-subtypes.md`.

- [x] T-VN-35A — **feature core·point subtype** → *배타 arc + place subtype*

  `UNIQUE(feature_id, kind)` + subtype의 `kind` 상수 CHECK + `(feature_id, kind)` 복합 FK로
  배타 arc를 만들고 `feature_places`를 분리했다(alembic 0085). shadow 병행은 하지 않는다 —
  subtype이 단일 정본이다.

  **재해석**: point subtype은 만들지 않고 `coord` 3컬럼을 core에 남겼다. coord는 4개 kind가
  공유해 kind 상수 CHECK를 걸 수 없어 배타 arc가 깨지고, place 96.6%·event 82%가 non-null이라
  거의 모든 read가 조인을 강제당하며, bbox/nearby 술어가 `idx_features_coord_gist` 너머로
  밀린다. 대신 geometry 계약 강화(35C)로 목적을 달성했다.

- [x] T-VN-35B — **event·notice subtype**

  `feature_events`/`feature_notices`(alembic 0086). notice 유효기간이 typed `timestamptz`가
  되어 read 필터의 문자열 파싱 + `pg_input_is_valid` 방어 cast가 사라졌다. "혼합 kind row
  거부"는 배타 arc가 선언적으로 구현한다 — subtype 행이 있는 동안 core `kind` 변경이 FK
  위반으로 막힌다.

  **주의**: DB CHECK로 `valid_end_time >= valid_start_time`을 걸지 않았다. provider가 미래
  시행 공지를 철회하면 end < start인 **실재 상태**가 나오고(실측: start 2026-07-13 /
  end 2026-06-02), CHECK를 걸면 KREX notice ETL asset이 죽는다. 불변식은 DTO가 선언값에
  대해 유지하고, DB 표현은 T-VN-37A의 `tstzrange`(empty range 허용)가 맡는다.

- [x] T-VN-35C — **route·area subtype**

  `feature_routes`(MULTILINESTRING NOT NULL)/`feature_areas`(MULTIPOLYGON NOT NULL),
  core `geom` 제거(alembic 0087). "geometry가 필수인 kind"와 "없어야 하는 kind"가 술어가
  아니라 테이블 구조로 갈린다. prod route/area 0행이라 이관 비용·회귀 위험 모두 0.

  **재해석**: `parent_feature_id`·`sibling_group_id`는 core에 남겼다 — prod 사용 0행이고
  place도 장래 부모를 가질 수 있어 route/area 전용으로 내릴 근거가 없다.

- [x] T-VN-35D — **repository/API projection cutover**

  core `detail` JSONB 제거 + `feature.features_detailed` 조립 뷰 신설. writer는 subtype에만
  쓰고 reader는 뷰를 읽는다 — 값이 두 곳에 있지 않으므로 drift라는 개념이 사라진다.
  merge 경로에 cross-kind 거부를 신설했다(종전 부재).

  검증: 조립 detail이 원본과 place·event·price·weather **731,620행 md5 바이트 동일**(notice도 `valid_start_time` 145/145 동일)(이 대조가
  `jsonb_strip_nulls` null 소실과 `EventDetail.sigungu_code` 누락 2건을 잡았다).
  플랜은 술어가 subtype GiST를 타도록 hot path만 UNION ALL로 직접 참조한다(뷰 컬럼을
  술어에 쓰면 Hash Left Join 2단 퇴화 — admin bbox 4158ms → 411ms 실측).

## 2026-08-06 — T-VN-41F1J-A Map-owned cancel-probe fixture 병합

- [x] **T-VN-41F1J-A — Map fixture schema·service API·격리**

  PR #960에서 `ops.c6c_cancel_probe_fixtures`와 fixture 전용 repository/service API를 병합했다.
  Map은 transaction ID마다 running/no-Dagster-run import job을 멱등 생성하고, 일반 PinVi 취소가
  만든 canonical cancellation 뒤 consume/finalize를 원자적으로 기록한다. `armed → consumed →
  finalized` receipt는 exact unsafe outcome을 포함하며, fixture kind는 worker·stale recovery·일반
  ops projection과 직접 event 삽입에서 격리된다. `ops:fixture` capability는 Map API와 Docker
  Manager에만 결박한다. 새 v5 Manager transaction에서 이 lifecycle을 실제 실행한 F1D-C3의 n150
  receipt는 상단 완료 이력에 기록한다.

## 2026-08-06 — T-VN-41F1D-C0a 후보 Map application schema head artifact 병합

- [x] **T-VN-41F1D-C0a — 설치 package 기반 정적 application head 계약**

  PR #963에서 후보 API image의 `ktm-application-schema head`가 installed package의 immutable graph
  artifact만 읽어 단일 Alembic head를 JSON으로 attest하게 했다. cwd/source mount/Alembic 실행/DB/application
  import는 경계 밖이며, AST generator equality·cycle·side-effect·ambiguous head 회귀를 고정했다.
  Docker Manager는 이 application head를 Dagster storage/PinVi head와 함께 reset 전에 attest한다.

## 2026-08-06 — T-VN-41F1D-C0 후보 Dagster storage migration artifact 완료

- [x] **T-VN-41F1D-C0 — 후보 Dagster storage migration artifact**

  `ktm-dagster-storage head`가 후보 이미지에 실제 설치된 Dagster package의 storage
  graph 단일 head를 JSON으로 attest하고, `migrate`가 동일 image의
  `DAGSTER_HOME`/`dagster.yaml`/metadata DSN으로 `dagster instance migrate`를 실행한
  뒤 `public.alembic_version`의 정확히 한 `version_num`을 strict 대조한다. Map
  application Alembic·source SHA·lock pin은 어느 경로에서도 storage head가 아니다.
  Compose one-shot 성공을 webserver/daemon의 선행 조건으로 연결했고, 외부 DB·infra·host
  overlay도 같은 순서를 유지한다. 실제 후보 image의 빈 격리 PostgreSQL 검증에서 head,
  migration 결과, `public.alembic_version`이 모두 `29b539ebc72a`로 일치했다. Docker
  Manager F1D-C2는 이 image command만 호출해 candidate를 attest·migrate한다.

## 2026-08-05 — T-VN-H42 provider 재적재 완주·수렴 검증 (41C 선행 조건 충족)

> 2026-08-07 `tasks.md`↔실상태 재대조에서 이관. 판정 자체는 2026-08-05
> (journal 2026-08-05 (5) — 최종 수치 고정) 완료됐고 열린 하위 항목이 남아 있지 않다.
> 함께 신설됐던 H43/H44는 열린 잔여가 있어 `tasks.md`에 남는다.

- [x] T-VN-H42 — **provider 재적재 완주·수렴 검증 (+ H35 prod live 검증 잔여)**
      — **2026-08-05 판정 완료** (journal (5) — 최종 수치 고정·41C 선행 조건 충족)

  **41C prod consumer enable의 선행 조건**. 완료 실측(2026-08-05): MOIS 702,955
  3중 일치(source=links=features)·opinet 934(용인·수원 bbox — 전국 bbox quota 소진
  재발 금지 준수)·unlinked 0건·공개 API/admin/quarantine live smoke green·소실됐던
  공개 API key 재발급. KMA 4종+airkorea 만성 실패는 구조 결함으로 **H45 분리**.

  - [x] 잔여 provider 로드 — MOIS bulk(dedup 룰 검증 후)·opinet bbox 완주.
    KMA/airkorea 축은 H45 판정으로 연동, khoa 등 잔여 transport 실패군은 스케줄
    수렴 감시 지속.
  - [x] CSV 재import(authoritative replace) — 486행 재통과, 미해석 290→270
    (구성: H31 구조 확정 103 + visitkorea/khoa 스케줄 수렴 대기 — 상시 운영).
  - [x] 공개 표면 **최종 수치 고정**(2026-08-05 00:30Z): features 731,724 =
    public = aliases · weather_values 56,310 · curation 4,910/링크 4,640.
