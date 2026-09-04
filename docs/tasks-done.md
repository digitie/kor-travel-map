# tasks-done.md — 완료/아카이브 task 이력

> 완료(`[x]`)·폐기·머지 history 아카이브. **진행 중/예정 task는 [`docs/tasks.md`](tasks.md)**.
> (2026-06-09 분리 — tasks.md 길이 축소. 분리 기준: 열린 `[ ]` 항목이 없는 섹션·Phase는 여기로.)

> **과거 기록 아카이브** (규약 §8 — 과거 검색은 `rg <패턴> docs/archive/`)
>
> | 기간 | 파일 |
> | --- | --- |
> | 2026-07-27 ~ 2026-07-31 | [archive/tasks-done-2026-07a.md](archive/tasks-done-2026-07a.md) |
> | ~ 2026-07-26 (C7·Admin) | [archive/tasks-done-2026-07b.md](archive/tasks-done-2026-07b.md) |

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
||||||| parent of c7360b8e (docs(ledger): T-VN-M03 완료 이관 — import child·격리 live acceptance 판정 근거)

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

## 2026-08-05 — 재생성 수렴·Wave 2 UUID 착지 일괄 아카이브 (배포 c0afaa4e)

> prod 재생성 수렴(H42)·`0082` 배포 완료 시점의 일괄 정리. H30/H32/H22/T-VN-31 절 전체와
> H25A/H34R/H40/H35/H31/32A/32B 상세를 이관했다(각 항목의 완료 근거·수치는 본문 보존).
> H35는 2026-08-04 재정의판(폐기·재생성 대체)으로 종결 — 아래 본문 중 cutover 설계는 이력이다.

### T-VN-H30 — 주소 검증 관측 durable화·회복 실적재 검증 (H28 후속, 부분완료)

- [x] T-VN-H30A — 검증 finding을 `ops.data_integrity_violations`에 durable 기록 (#888, dedupe 부분 유니크 인덱스 0067 — **prod 미적용, H35 참조**) → [`tasks-done.md`](tasks-done.md)

- [x] T-VN-H30B — **회복을 격리 snapshot의 실제 적재·인증 API로 재검증** *(2026-08-04 재정의·완료)*

  ## 완료 기록 (2026-08-04, 재정의판 전 acceptance 충족)

  - **snapshot**: `n150:~/backups/krtour_map_0078_20260804T023104Z.dump` 6.9M,
    sha256 `b5ab83dd…f18ffe`, 2026-08-04T02:31:05Z, head `0078_cache_target_gc_observe`,
    features 7,056 · curation_items 4,910 · source_records 7,097. dev box scratch에 복원
    (pg_restore 오류 0줄, superuser 확장 4종 사전 생성).
  - **artifact**: concierge `/api/v1/features/changes` 전량 8 page / 1,481 rows / 3.37MB,
    cursor chain 검증(내장 has_more/next_cursor 룰) 통과, JSONL sha256 기록. 이후 replay는
    이 파일만 입력(**live concierge 무접촉**).
  - **회복 실증**: scratch에서 concierge scope 1,481건을 `status='inactive'`로 결손 주입
    (active 7,056→5,575) → `build_asset_context` resource override로
    `run_feature_place_kor_travel_concierge_youtube` 직접 호출(network-free replay,
    `strict_address='drop'`, geo reverse만 결선) → **active 1,481 완전 복원, id 집합
    교집합 1,481 / 신규 0 / 미복구 0**. **2회차 replay 변화 0(멱등)**.
  - **finding**: run3 sync 수치 `observed=105 unique=105 upserted=105 unrecorded=0`.
    violation 분포(scratch 전체): reverse_geocode_failed 272(unlinked) /
    reverse_geocode_unavailable 105(linked) / provider_address_region_disagreement 52(linked) /
    admin_code_stale_{sido 51·emd 7·sigungu 2}(전부 linked) — **dual grade 축 실작동 증거**.
    linked = feature_id non-null로 실측.
  - **인증 실호출**: scratch 실 API 서버(local-dev)에서
    `GET /v1/admin/issues?status=open&issue_type=admin_code_stale_sido` — FK target
    (`f_5183032036_p_…` 등) 정상 해석, `last_seen_at` 반환 정합.
  - 정직 각주: replay 세션 중 geo 호출 105건이 간헐 unavailable로 기록됨(1,376건 성공) —
    그 세션의 finding은 unavailable 계열로 관측됐고 stale 계열 `last_seen`은 snapshot
    시대 값이 최신. 판정 왜곡 없음(회복 실증은 feature 축, finding 축은 분포·수치 기록).
  - 하네스: 전용 replay CLI가 저장소에 없어 조사 후 신규 조립
    (`test_concierge_assets.py`의 `build_asset_context` 패턴 + 순수 변환 모듈). 스크립트는
    dev box `~/h30b/`(h30b_replay.py·h30b_final.py)와 세션 scratchpad에 보존.

  ### (이하 재정의 원문)

  ## 재정의 (2026-08-04, 사용자 결정 "b")

  종전 acceptance는 **H35가 서명한 post-migration bundle** 복원을 전제했는데, 그 전제가
  두 겹으로 소멸했다 — H35 재정의로 서명 bundle이 존재하지 않게 됐고, 검증 대상이던
  7/30 격리 snapshot(`0063` 시대)의 데이터 시대가 폐기·재생성으로 끝났다. 회복 실증의
  목적(#673의 남은 절반 — 데이터 유실 후 finding 파이프라인이 실제로 복원되는가)은
  재생성과 무관하게 유효하므로 **현 재생성 prod(`0078`) 기준으로 재정의**한다.

  재검증 acceptance (재정의판):
  - **재생성 prod에서 새 격리 snapshot을 뜬다** — writer-quiesced 필요 없음(스케줄 사이
    창이면 충분), dump identity(sha256)·시각·migration head(`0078_cache_target_gc_observe`)
    를 기록한다. 폐기 전 아카이브(`krtour_map_0072_*.dump`)는 **이 task의 대상이 아니다**
    (구 시대 데이터 — H22C 픽스처 용도로만).
  - 격리 scratch DB에 복원 후(신규 DB는 superuser 확장 4종 사전 생성 — H35 실행 기록
    참조) 같은 scope의 `feature.features` 적재 직전/직후 수와 복구된 feature id 집합을
    기록한다.
  - 같은 run의 finding `observed/unique/upserted`, linked/unlinked 수를 함께 기록한다.
  - 인증된 `GET /v1/admin/issues?issue_type=…` 실호출(격리 스택의 실 API 서버)로 최신
    `last_seen_at`·최신 FK target을 확인한다.
  - concierge `changes` export는 **재생성 시대의 실 export artifact**를 쓴다 —
    SHA-256·page/cursor chain·행 수 검증 후 live credential/network 없이 resource
    override로 ordered item을 재생한다. artifact 외 입력 금지, prod 무변경 원칙 유지.
  - Dagster DB pair 복원·서명 identity 검사 항목은 **삭제** — 서명 주체(H35 helper)가
    사문화됐고, run 이력 DB는 회복 실증의 대상이 아니다.

- [x] T-VN-H30C — **타 provider `AdminEvidence` 무장** (2026-08-03 완료)

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

  ## 결과 (2026-08-03)

  **krforest arboretums만 무장했다. visitkorea는 무장하지 않는 것이 옳다는 판정이다.**

  판정 기준을 "payload에 행정코드가 있는가"에서 **"obs·claim 두 축이 동시에 성립하는가"**로
  바꿨다. `admin_code_stale_*`는 `grade == "dual"`일 때만 발화하므로 그것이 실질 기준이다.

  | provider | dual | 근거 |
  | --- | --- | --- |
  | krforest arboretums | **가능** | `_resolve_address`의 reverse 조건에 payload 코드가 없다 |
  | krforest recreation_forests | 불가 | payload에 행정코드 필드 자체가 없음(제공기관코드뿐) |
  | visitkorea | 불가 | reverse 미호출 + `FeatureBundle` 미생성(enrichment-only) — 실을 자리가 없다 |
  | MOIS | 구조적 불가 | `legal_dong_code`가 있으면 reverse를 건너뛰어 obs/claim 상호배타 |

  **선행 게이트를 prod에서 실측했다** — arboretum 205건 **전량**이 `region_code`를 갖고
  전부 8자리 숫자(`emd`)다. 조사가 우려한 세 리스크(전량 null / 자릿수 혼재 /
  `"4173025000.0"` 형태 오염)가 모두 해소됐다.

  구현:
  - `_resolve_address`가 `(address, reverse_geo, reverse_attempted)`를 반환하도록 바꿨다.
    obs 축은 **좌표 reverse 결과만**이어야 한다 — `address`는 `address_resolver`(주소
    문자열 정지오코딩)로도 채워져 그대로 쓰면 claim_text와 출처가 같아진다(`mois.py` 선례).
  - `_claim_from_region_code`가 숫자·지원 길이(10/8/5/2)만 통과시킨다. 원천이 길이·숫자
    검증을 전혀 하지 않으므로 거르지 않으면 DTO validator의 ValueError로 **asset 전체가
    죽는다**.
  - 휴양림 경로는 `admin_evidence=None` 유지.

  회귀 8종을 추가하고 변이로 falsifiability를 확인했다(무장 제거 시 관련 테스트가 죽는다):
  dual+staleness 발화 / 코드 일치 시 미발화 / 길이 디스패치 4종 / 미지원 형태 12종 무예외
  거부 / obs 오염 금지 / 휴양림 claim 부재 / **무장 부수효과 중립성**(MOIS 무장이
  `reverse_geocode_not_attempted`를 새로 터뜨린 전례가 있어 고정).

  문서 정정도 함께 했다 — `address-geocoding.md` §8 표의 "MOIS reverse **필수**"는 코드와
  정면 모순이라 조건부로 고치고, §8.1에 provider별 무장 조건표를 신설했다. §7.1의
  `providers/visitkorea.py :: festival_to_bundles` 예시는 **실재하지 않는 함수**라
  개념 예시임을 명시했다(그대로 두면 "visitkorea에 이미 bundle 경로가 있다"는 오인이 재발).

### T-VN-H32 — 주소 검증 finding 자동 close (H30A 후속)

H30A가 durable ledger를 붙였으나 **자동 close는 일부러 넣지 않았다**. 1차 설계의 sweep
("이번 run이 보고하지 않는 finding을 닫는다")을 적대 리뷰가 실측으로 기각했다.

- `_load()`는 provider에 따라 **배치마다** 호출된다(MOIS는 1000건 단위 ~977회). 배치 단위
  sweep은 "이 배치에 없는 것"을 닫아, 한 run이 자기 finding 대부분을 스스로 resolved 처리한다.
- sweep이 행을 부분 unique index 밖으로 밀어내 다음 run이 **새 행**을 만든다 — 막으려던
  단조 증가를 재생산한다(3개 논리 finding → 2 run 후 6행, 실측).
- `bundles=[]`인 `_load()`는 OpiNet 일일 스킵·MOIS 무레코드 fallback의 **제어 흐름
  sentinel**이라, 빈 finding 집합이 큐 전체를 닫는다.

- [x] T-VN-H32 — **run marker 기반 close** (2026-07-31, #912로 superseded)

  **marker는 시각이 아니라 `run_id`다.** 처음엔 `last_seen_at < run_started_at`으로 짰는데
  `dagster/definitions.py:99`에서 `fetched_at` resource가 **`None`**이라 `_fetched_at()`이
  **호출할 때마다 새 `now()`**를 반환한다. run-end hook에서 그 값을 marker로 쓰면 이번 run의
  upsert보다 나중 시각이 되어 **자기 finding을 스스로 닫는다** — 기각된 실패모드를 시각 축으로
  재현하는 것이다. `run_id`는 그 시계 함정이 없다.

  upsert가 `payload.observed_run_id`를 찍고, close는
  `COALESCE(payload->>'observed_run_id','') <> :run_id`인 것만 닫는다.
  **빈 `run_id`는 술어가 모든 행에 참이 되므로 `ValueError`로 fail-closed**한다.

  호출 지점은 `assets.py`의 `_record_feature_sync_success` — **8개 asset 공통, 배치 루프 밖,
  run당 1회**이고 MOIS처럼 배치를 도는 asset도 `result is not None`(실제로 배치를 처리함)일
  때만 닿는다. `bundles=[]` sentinel 경로(OpiNet 일일 스킵·MOIS 무레코드 fallback)는 이 hook을
  거치지 않으므로 빈 관측 집합이 큐를 닫는 일이 없다. close 실패는 적재를 되돌리지 않는다 —
  관측 위생이지 적재 계약이 아니다.

  술어별 방어: `status='open'`(**`acknowledged` 불가침**) / `provider`·`dataset_key`(provider 경계)
  / `dedupe_key LIKE 'av2\_%'`(같은 provider의 **다른 subsystem** finding, 예 `curation_mislink:…`를
  쓸어버리지 않음) / **단일 statement**(`trg_data_integrity_violations_ops_live_revision`이
  statement 단위라 finding마다 UPDATE를 돌리면 `ops_live` hot row에 배타 락을 N번 잡아
  `/admin/issues` 쓰기를 막고 데드락까지 만든다 — batch upsert와 같은 이유).

  **retention**: `purge_resolved_integrity_findings(retention='90 days')` +
  dagster op `purge_resolved_integrity_findings`. `feature_repo.purge_expired_notices`(1년)와
  같은 패턴이되 finding은 운영 신호라 분기 회고에 필요한 만큼만 둔다.
  `acknowledged`는 어떤 경우에도 지우지 않는다.

  > **flap은 아직 관측되지 않았다.** close를 켜면 resolved가 쌓이기 시작하고, 재발하는 finding은
  > 부분 유니크 인덱스 밖으로 나갔다 돌아오며 사이클마다 새 행을 남긴다. 지금은 prod finding이
  > 3건뿐이라 flap 비율을 측정할 데이터가 없다. **A(시간 기준)로 시작하고, 첫 몇 run에서
  > resolved 증가율을 재서 dedupe_key별 상한(B)이 필요한지 판단한다** — 관측되지 않은 문제에
  > 선제 대응하지 않는다.

  검증: 통합 테스트 **15 passed**(기각된 3모드 미재현 / `acknowledged` 불가침 / 다른 subsystem
  미침범 / provider 경계 / 빈 `run_id` fail-closed / `resolution` 스탬프·멱등 / retention 양방향),
  n150 CI-parity **2278 passed**, `mypy --strict` **196 files clean**.

- [x] T-VN-H32R — **PR #908 사후 감사의 close·retention 불변식을 보강한다 (#911~#913)**

  exact head `312b1b4b` 적대 리뷰에서 기존 H32 완료 판정을 뒤집는 P1 두 건과 P2 한 건이
  재현됐다. `record_sync_success`는 provider 적재 성공일 뿐 absence를 부정 증거로 쓸 수
  있는 완전한 관측 receipt가 아니다. MOIS empty fallback과 finding 저장 불완전에서도
  close가 호출되고, 단일 mutable `observed_run_id`는 A upsert→B upsert→A close 교차에서
  A가 실제 관측한 finding을 resolved 처리한다. retention op도 어떤 Dagster job에 없었다.

  - [x] **#911** — source snapshot이 authoritative·complete이고 현재 run finding 전량이
    durable하게 기록됐다는 typed receipt가 있을 때만 close한다. empty/partial/transform·load
    일부 실패/finding 저장 실패·`unrecorded_count > 0`은 모두 close 0회로 fail-close한다.
  - [x] **#912** — migration 0071이 provider/dataset scope, external run generation,
    run별 dedupe-key observation set을 정규화한다. scope row lock이 generation 배정과
    authoritative fence를 직렬화하고, current run과 더 새 partial run의 관측은 immutable
    anti-join으로 sweep에서 보호한다. A/B 교차·역순·동시 allocation을 실제 PostgreSQL로
    검증한다.
  - [x] **#913** — resolved purge op을 `MAINTENANCE_JOBS`와 schedule이 실제 실행하는 graph에
    등록하고 Definitions node·execute-in-process의 retention config/metadata를 검증한다.

  migration은 PR #906의 0070 landing 뒤 단일 head를 기준으로
  `0071_integrity_observations`에 추가했다.

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

- [x] T-VN-H34R — **H34 링크 evidence를 linked target·공개 snapshot에 결박한다 (#914)**

  - [x] `place_name`과 linked `feature_name`을 동일 정규화 함수로 exact 비교하고, 동명
    후보 query는 count가 아니라 candidate `feature_id`를 반환해 현재 링크와 결박한다.
    linked-name mismatch는 독립 axis/evidence이며 무관한 동명 Feature로 pass할 수 없다.
  - [x] `--scope public`은 공개 curation 정본(`source_present`, included,
    collection published/public/unarchived, theme public, `feature.public_features`)을
    repository 함수로 재사용한다. H25B 내부 승인 5건은 `--scope approved`로 분리한다.
  - [x] 대상 rows와 name candidate evidence를 read-only repeatable-read transaction
    하나에서 읽고 결과에 scope, 대상 수, snapshot identity를 기록한다.
  - [x] linked-name mismatch와 source removed/excluded/draft/admin-only/private-theme/
    inactive 공개 경계를 회귀 테스트로 고정한다. 실제 migrated PostgreSQL에서 별도
    connection의 committed fixture를 `audit_database()`로 읽어 transaction isolation과
    read-only metadata까지 검증한다.

- [~] T-VN-H40 — **concierge curation provenance 복구 (H35 배포 선행 blocker)**
      — **구현·검증 완료(`0073`+`0074`, PR #919/#925). 남은 것은 H35 배포 시 실행뿐이다.**

  `0072_curation_provenance`가 기존 link를 전부 `accepted + legacy_unattributed`로 이관하고,
  `_trusted_link_sql()`이 `match_basis <> 'legacy_unattributed'`를 요구한다. 이 술어는 public
  collection count/detail·Feature group/detail/list 경로에 **실제로 적용**되므로, 배포 직후
  기존 공개 curation 링크가 공개 표면에서 사라진다. **fail-close 자체는 ADR-063이 명시한
  의도된 동작이다**(legacy/unattributed link는 admin 감사 대상으로만 남긴다).

  문제는 **복구 경로가 없다는 것**이다. 현재 존재하는 경로는 셋뿐이다:
  authoritative CSV 재import(`csv_explicit_feature_id`) / admin 수동 검토(`admin_review`) /
  이미 non-legacy accepted decision이 있던 merge 대상(제한된 `forward_recovery`).

  - **공식 CSV 222건**은 exact CSV + provenance sidecar를 새 계약으로 재import하면 첫 경로로 복원된다.
  - **concierge projection 3,044건은 일괄 복원 경로가 코드에도 `tasks.md`에도 없다.**
    `0065`의 `sync_curated_feature_collection()`은 `curation_items.feature_id`/projection을
    쓰지만 `curation_import_rows`·`curation_link_decisions`를 만들지 않고,
    `apply_curated_source_rules()`도 `feature.curated_features`만 갱신한다.
    → **후속 task로 분리된 것이 아니라 누락이다**(PR #910 작성자 확인).

  > **축소 창은 "최대 한 달"이 아니라 무기한이다.** `40 3 3 * *`는 concierge **원천 Feature
  > 적재** 스케줄이라 실행돼도 trusted decision을 만들지 않는다.
  > `curated_features_refresh_daily_schedule`은 기본 STOPPED이고 수동 실행해도 현재
  > writer/trigger가 decision을 추가하지 않는다. **별도 복구를 구현·실행하기 전까지 회복되지 않는다.**
  > (초안에서 내가 "월 1회 스케줄이라 최대 한 달"이라 적은 것은 스케줄 이름만 보고
  > 자연 회복을 가정한 오류다.)

  ## 조사로 확정된 것 (2026-07-31)

  **`match_basis` 허용값은 4개다**(`0072` `ck_curation_link_decisions_basis`):
  `csv_explicit_feature_id` · `admin_review` · `legacy_unattributed` · **`forward_recovery`**.
  그 생성 경로는 **merge 승인 한 곳뿐**이다(`merge_repo.py:339`, `:451`).
  (이 문단은 처음에 "복구용 축이 이미 있으니 **새 값을 만들 필요가 없다**"고 적었으나
  아래 판정에서 뒤집혔다 — `forward_recovery`는 "합쳐진 대상의 결정을 이어받는다"는
  merge 전용 의미라 projection에 빌려 쓰면 의미가 왜곡된다. `0073`은 `source_rule`을 더한다.)

  **`0065`가 `sync_curated_feature_collection()`의 최신 정의다.** `0066`~`0072` 어느 것도
  이 함수를 갱신하지 않는다(전수 확인). 그 함수가 `curation_items`에 쓰는 어느 경로에도
  `accepted_link_decision_id`가 **없다**. 그래서 트리거가 만드는 projection은 항상
  decision 없이 태어나고, `_trusted_link_sql()`에서 제외된다.
  → **#910 답변의 진단이 코드로 확인됐다.**

  > **정정(2026-07-31 실행 확인)** — 위 문단은 처음에 "`curation_items`를 DELETE 후
  > INSERT한다(`0065:892`)"고 적었는데 **틀렸다.** `0065` 파일에는 이 함수 정의가 두 번
  > 나오고 `:835`는 **downgrade가 되돌리는 옛 본문**이다. 실제 최신 정의(`:28`)는 DELETE 없이
  > targeted UPDATE 여러 개 + `INSERT ... ON CONFLICT DO NOTHING`을 쓴다. 컨테이너에 `0072`를
  > 올리고 직접 확인했다 — projection UPDATE 후 item의 `ctid`는 바뀌지만
  > `accepted_link_decision_id` 포인터는 **살아남는다**(재작성이 아니라 갱신).
  >
  > 이 오독은 결론을 두 개 바꿀 뻔했다: ① `fk_curation_link_decisions_item`이
  > `ON DELETE RESTRICT`라 "0072 배포 후 concierge writer가 통째로 죽는다"고 볼 뻔했다 —
  > 직접 DELETE는 실제로 RESTRICT에 막히지만(확인함) 트리거가 DELETE를 하지 않으므로
  > 그 경로는 발생하지 않는다. ② "재삽입마다 decision이 누적된다"는 우려도 같은 이유로
  > 성립하지 않는다. 그래도 누적 축은 **회귀 테스트로 고정했다** — 미래에 writer가 바뀌면
  > 되살아나는 위험이기 때문이다.

  ## 실증 (2026-07-31, 격리 restore clone — prod 무접촉)

  prod 백업(`20260731T065308Z`)을 포트 노출 없는 임시 컨테이너에 복원하고 `0064~0072`를
  적용해 **직접 셌다.** 그전까지 이 수치는 "코드상 확정·실행 미검증"이었다.

  ```
  배포 전  linked_items(active)          3,266
  배포 후  linked_items(active)          3,266    ← 링크 자체는 남는다
           decision 보유                 3,266
           legacy_unattributed decision  3,266    ← 전부 이 값
           ** 공개 노출 가능(trusted)        0    ← 전멸
  alembic  0064 → 0072  소요 1,754초 (29분)
  ```

  **내 예상치 "3,265 → 264"가 틀렸다.** 264는 `feature_id IS NULL`이라 애초에 링크가 아니었다.
  trusted 링크 기준으로는 **3,266 → 0**이다. 즉 `T-VN-H40` 없이 배포하면 **공개 curation이
  전멸한다.**

  그리고 **마이그레이션 29분은 `ktdctl deploy`의 `--wait-timeout 120`(하드코딩)을 14배
  초과한다** — B′ 경로(마이그레이션을 배포와 분리)의 근거가 추정이 아니라 실측이 됐다.

  > **정정 (2026-08-01) — 이 1,754초는 배포 시간의 근거로 쓸 수 없다.**
  > 같은 절차를 `0074`까지 포함해 다시 재니 개발 환경(WSL)에서 **79.9초**가 나왔다.
  > 22배 차이의 원인을 조사하니 **측정 조건 자체가 배포 조건과 다르다**:
  > `scripts/h35/h35_migrate.sh`는 마이그레이션 **전에 dagster-daemon을 정지시키는데**,
  > 1,754초 측정도 이번 n150 재측정도 **dagster가 도는 상태에서** 쟀다.
  > n150 실측 시도 중 확인한 그 시점 호스트 상태 — 4코어에 load average 11.6,
  > iowait 44.7%, 동시에 T-VN-41 lane의 Playwright buildx 빌드 + 제품 스택 2벌 라이브
  > 검증 + prod dagster ETL이 함께 돌고 있었다(누적 I/O 66GB read/91GB write 유발로
  > 판단해 측정을 중단하고 정리했다).
  >
  > **결론: 두 수치 모두 경합을 잰 것이고 어느 쪽도 배포 시간이 아니다.** 다만
  > **B′ 경로 자체는 유지한다** — 배포 절차가 이미 dagster를 멈추고 시간 제한 없는
  > 일회성 컨테이너로 마이그레이션을 돌리므로, 정확한 초수를 몰라도 `--wait-timeout 120`
  > 리스크가 구조적으로 제거된다. 즉 이 수치는 **B′의 근거로 필요하지 않다.**
  > (하드웨어 무관한 논리 결과 — trusted 3,043/공백 223, H41 FK CASCADE 동작 — 는
  > 격리 clone에서 정상 검증됐다.)

  ## 판정 (2026-07-31 prod 실측) — **근거는 실재한다. `legacy_unattributed`는 틀린 분류다.**

  ```
  curated_features            3,044
    source_record_key   3,044 / 3,044  (100%)  → provider_sync.source_records FK 100% 도달
    selection_origin    3,044 / 3,044  (100%)  → source_rule 3,043 / admin 1
    content_version     3,044 / 3,044  (100%)
  provider              kor-travel-concierge-youtube 3,044
  legacy collection 링크 3,044 (전부 source_record_key 보유)
  ```

  **결손 0건이다.** 각 링크에 대해 "이 provider record에서 이 rule로 나왔다"가 **완전히
  재구성된다**. `0072` backfill의 evidence 문구 *"기존 link의 선택 근거를 안전하게 복구할 수
  없음"* 은 이 3,044건에 대해서는 **사실이 아니다**.

  `0072`가 틀린 게 아니라 **범위를 넓게 잡았다** — `feature_id IS NOT NULL`이면 무조건
  `legacy_unattributed`로 이관했고, 그 안에 근거가 완전한 3,044건이 섞였다.

  > **내 초안 두 가지가 틀렸다.**
  > ① **`forward_recovery` 재사용은 의미 왜곡이다.** 그 값은 merge 경로에서 "합쳐진 대상의
  >    결정을 앞으로 이어받는다"는 뜻인데(`merge_repo.py:325-460`), concierge projection은
  >    merge와 무관하다. 이름을 빌려 쓰는 것이다.
  > ② **"트리거가 자동 발급하면 fail-close가 무력화된다"는 우려는 조건부로만 맞다.**
  >    근거 유무를 구분하지 않고 전부 승격하면 그렇다. 그러나 `selection_origin='source_rule'`과
  >    `source_record_key` FK를 **검증한 것만** 승격하면 게이트는 남는다 — 근거 없는 링크는
  >    여전히 제외된다.

  ## 확정 설계 — `0073`로 `match_basis`에 `source_rule` 추가

  `0072`의 `ck_curation_link_decisions_basis`는 4값(`csv_explicit_feature_id` ·
  `admin_review` · `legacy_unattributed` · `forward_recovery`)만 허용한다. 여기에
  **`source_rule`** 을 더한다. 이유는 위 판정 그대로 — 근거의 성격이 기존 4값 어디에도
  해당하지 않는다.

  `curation_link_decisions`의 NOT NULL 컬럼과 CHECK(실측):

  | 컬럼 | 제약 | `source_rule` decision이 채울 값 |
  | --- | --- | --- |
  | `curation_item_id` | NOT NULL, FK→items RESTRICT | projection의 item |
  | `feature_id` | NOT NULL | `curated_features.feature_id` |
  | `decision_kind` | `IN ('accepted','revoked')` | `accepted` |
  | `match_basis` | CHECK 4값 → **5값으로 확장** | `source_rule` |
  | `resolver_version` | `= btrim() AND <> ''` | `curated_features.content_version` |
  | `evidence` | `jsonb_typeof = 'object'` | `{source_record_key, selection_origin, content_version, provider}` |
  | `actor` | `= btrim() AND <> ''` | `curated_features.selected_by` (없으면 `source_rule:<provider>`) |
  | `supersedes_decision_id` | self와 달라야 함 | 재삽입 시 직전 decision |

  ## 두 갈래

  **① one-shot** — 기존 3,044건에 `source_rule` decision을 append하고 포인터를 채운다.
  **검증 술어를 명시한다**: `selection_origin='source_rule'` **그리고**
  `source_record_key`가 `provider_sync.source_records`에 도달할 것. 둘 중 하나라도 실패하면
  **승격하지 않고 `legacy_unattributed`로 남긴다** — 그게 fail-close를 지키는 지점이다.
  실측상 3,044건 전부 통과하지만, **술어를 조건 없이 통과시키는 게 아니라 실제로 검사한다.**

  **② ongoing** — `sync_curated_feature_collection()`(`0065`가 최신 정의, `0066`~`0072`
  아무도 안 고침)이 `curation_items`를 INSERT할 때 같은 transaction에서 decision도 만든다.
  그 함수는 `NEW`(=`curated_features` 행)를 갖고 있으므로 위 표의 값을 **전부 채울 수 있다** —
  DB 트리거에 actor/evidence 맥락이 없다는 일반론이 여기서는 해당하지 않는다.

  > **누적 축** — `0072`의 append-only 트리거가 decision UPDATE/DELETE를 막으므로, 발급
  > 조건이 느슨하면 decision이 단조 증가한다. 처음엔 "트리거가 item을 DELETE 후 INSERT하니
  > 재삽입마다 쌓인다"고 봤으나 그 전제는 위 정정대로 **틀렸다**. 그래도 갱신 1회마다
  > 1건씩 쌓는 설계는 얼마든지 가능하므로 **회귀 테스트로 고정한다**(`0067` dedupe 계열).
  >
  > **FK 순환** — `curation_items.accepted_link_decision_id` → `curation_link_decisions` →
  > `curation_items`가 서로를 참조한다. `0072`가 그 FK를 DEFERRABLE INITIALLY DEFERRED로
  > 만든 이유가 이것이고, 트리거 안에서 둘을 만들 때 그 성질에 의존한다.

  ## ⚠ 배포 전 남은 것 두 개 (2026-08-01 prod 실측 + 적대 검토)

  `0073`만으로는 H40이 닫히지 않는다. **읽어서 넘길 수 없는 수치가 둘 있다.**

  ### ① 공개 노출 item 3,265 → **3,043**. 222건이 어두워진다 (격리 clone 실증)

  `0073`의 승격 술어는 concierge projection만 통과시킨다. 격리 restore clone에서
  배포 전/후를 **공개 목록 술어 그대로** 셌다:

  ```
  배포 전 (0063, prod 현재)          공개 노출 item  3,265
  마이그레이션 직후 (0064~0074)      공개 노출 item  3,043   ← -222
  ```

  어두워지는 222건 — 전부 **공식 CSV 큐레이션**이다:

  | collection | 건수 |
  | --- | --- |
  | `korean-tourism-100:2025-2026` | 58 |
  | `korean-tourism-100:2023-2024` | 51 |
  | `arboretum-garden-stamp-tour:2026` | 44 |
  | `heritage-visit-campaign:*` (11개 route) | 67 |
  | `lighthouse-stamp-tour:*` | 2 |

  > **정정 — 앞서 "223건"이라고 적은 것은 틀렸다.** 그 223번째는
  > `[빵이네] 강원도여행정보`(`selection_origin=admin`, **`item_status='rejected'`**)인데,
  > 공개 목록 술어가 `i.status = 'included'`를 요구하므로(`curation_repo.py:589`)
  > **애초에 공개 표면에 없던 항목**이다. 내 공백 측정 쿼리가 `status <> 'archived'`만
  > 걸러 `rejected`를 포함시킨 오류였다. 실제 공개 공백은 **222**다.

  이들은 `curated_features` 행이 없고(projection이 아니다) `source_record_key`도
  없다. 대신 `metadata`에 `feature_match_reasons`·`feature_match_partial`·
  `official_place_name`을 갖고 있고, **`resources/curations/*.csv` 5개 파일이 정확히
  222행에 `feature_id`를 채워 두고 있다**(486행 중 222행 — DB 링크 수와 일치).

  > **처음에 `metadata`의 `feature_match_partial=false`(199건)로 승격 대상을 가르려
  > 했는데, 그건 마이그레이션에 휴리스틱을 새기는 것이다.** `0072`는 이미 이 부류를
  > 위해 `csv_explicit_feature_id` basis와 import batch/row 계보를 만들어 뒀다.
  > 정본 CSV를 **재import하면** 설계된 경로로 진짜 import 계보와 함께 근거가 붙는다.

  **결론 — 배포 절차에 단계를 하나 넣는다.** 마이그레이션(`0064~0074`) 직후,
  **새 이미지를 올리기 전에** 공식 curation CSV 5개를 재import한다. 구 이미지는
  `_trusted_link_sql`을 모르므로 그 구간에도 계속 서빙한다 → **공개 표면 공백 0**.
  배포 게이트: 재import 후 **공개 노출 item = 3,265**(배포 전과 동일)인지 확인한다.

  #### 게이트 실증 — 격리 clone에서 재현 완료 (2026-08-01)

  실제 import 경로(`parse_curation_csv` → `resolve_feature_matches` →
  `_adopted_match` → `import_curation_rows`; HTTP/인증만 제외)를 격리 clone에 태웠다:

  ```
  배포 전 baseline                   공개 노출 item  3,265
  마이그레이션 직후 (재import 전)     공개 노출 item  3,043   (-222)
  CSV 재import 후                    공개 노출 item  3,265   (±0)  ← PASS
  ```

  CSV 222행 **전량 채택**(미채택 0), `csv_explicit_feature_id` decision 222건 생성.
  파일별 채택: arboretum 44 / heritage 67 / kt100-2023 51 / kt100-2025 58 / lighthouse 2.

  > **게이트 값으로 "trusted link 수"를 쓰면 안 된다.** 링크 수 기준으로는 3,265가
  > 나오는데(3,043 + 222), 위 `rejected` 1건 때문에 "3,266이어야 한다"는 기대와
  > 어긋나 **정상 배포에서도 FAIL**이 뜬다. 게이트는 반드시 **공개 목록 술어로 센
  > item 수**(`status='included'` + collection public/published + theme public +
  > trusted decision)를 쓴다.

  #### 재import가 정말 복구하는지 — 코드 경로로 확정 (2026-08-01)

  "재import하면 붙는다"는 처음엔 **추론이었다.** #907/#910이 자동 링크를 조였으므로
  조인 resolver가 이 222건을 더 이상 채택하지 않을 가능성이 실재했다. 경로를 따라가
  확정했다:

  1. `_RESOLVE_FEATURES_BATCH_SQL`(`curation_repo.py:1608`)의 UNION 첫 분기는
     `requested.feature_id IS NOT NULL`일 때 **그 feature_id로 정확히 1행**만 낸다
     (`deleted_at IS NULL AND status NOT IN ('deleted','hidden')` 조건). 이름 기반
     후보 탐색(둘째 분기)은 `feature_id IS NULL`일 때만 돈다.
  2. `_adopted_match`(`routers/curations.py:618`)는 *"CSV가 명시한 exact Feature ID만
     자동 채택한다"* — `row.feature_id`가 있고 `len(matches) == 1`이면 채택한다.
  3. 채택되면 `import_curation_rows`가 `match_basis='csv_explicit_feature_id'` decision을
     만들고 `supersedes_decision_id`로 직전 결정을 이으며 `accepted_link_decision_id`를
     채운다(`curation_repo.py:3324` 부근).

  **#907/#910이 제거한 것은 `address_hint` 단독 자동 링크이고, 명시 `feature_id`
  경로는 그대로다.** 따라서 CSV 222행(전부 `feature_id` 보유)은 대상 Feature가 살아
  있는 한 전량 복구된다 — 이것이 `0073`에 휴리스틱을 넣지 않고 재import로 미룬 근거다.

  ### ② 모든 dedup 병합이 abort한다 — `T-VN-H41` (신규, `0072` 결함)

  `merge_repo._DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL`은
  `curation_items.curation_item_id`를 **새 UUID로 재작성**한다. `0072`의
  `fk_curation_link_decisions_item`은 `ON DELETE RESTRICT` + `ON UPDATE NO ACTION`이라,
  decision이 달린 item이면 그 UPDATE가 FK 위반을 내고 **병합 전체가 롤백된다.**

  `0072`만 적용한 컨테이너에서 재현했다 — `0073`이 만든 결함이 아니다. 다만 `0072`가
  미배포라 **이번 배포와 함께 prod에 도달**한다. 그리고 기존 merge 통합 테스트의
  curated 픽스처가 **전부 `selection_origin='admin'`** 이라 0073 트리거가 merge
  경로에서 한 번도 안 돌았고, 그래서 이번 검토에서 나온 merge 결함 3건이 모두 green으로
  통과했다. prod 모양(`source_rule`) 테스트를 추가해 `xfail(strict=True)`로 고정했다 —
  **xfail 제거가 H41의 완료 조건**이다.

  고치는 길은 두 갈래였다:
  - (a) 관련 FK에 `ON UPDATE CASCADE`. append-only 트리거가 RI cascade의 UPDATE를
    막으므로, "`curation_item_id`만 바뀌는 UPDATE는 이력 변경이 아니다"는 예외를
    명시해야 한다.
  - (b) merge의 detach가 PK를 재작성하지 않게 바꾼다. `0045` 전환 트리거의 UUID 충돌을
    피하려고 재작성하는 것이라(주석 `merge_repo.py:770-773`) 대안 설계가 필요하다.

  **(a)로 결정하고 구현 완료** (2026-08-01, `0074_curation_item_rekey_cascade`,
  같은 브랜치·PR #919). 애초 생각한 것보다 관련 FK가 많았다 — `fk_curation_link_decisions_item`
  하나가 아니라 **4개**: `fk_curation_import_rows_item` · `fk_curation_link_decisions_item` ·
  `fk_curation_link_decisions_import_row`(합성 — import row 쪽도 캐스케이드된 뒤에야
  다시 일관됨) · `fk_curation_link_decisions_supersedes`(자기참조 합성 — supersedes 사슬
  전체가 같은 item이라는 불변식을 강제).

  append-only 트리거 예외는 `curation_item_id` **하나만** 바뀐 `UPDATE`만 통과시킨다.
  첫 구현이 `NEW.curation_item_id`를 정적으로 참조해 그 컬럼이 없는
  `curation_import_batches`에서 `UndefinedColumnError`로 죽었는데, **기존** 테스트
  `test_link_provenance_is_append_only_fail_closed_and_recoverable`가 잡았다 — jsonb
  동적 조회로 고쳤다. `models.py`의 ORM FK 선언도 `onupdate="CASCADE"`로 맞췄다(안
  그러면 `alembic check` drift로 걸린다 — 실제로 걸렸다).

  `apply_feature_merge()`를 실제로 부르는 xfail 테스트가 **XPASS로 전환**돼 수정을
  1차 확인했고, 변이 2회(CASCADE 제거 / 예외 무조건 통과로 넓힘)로 falsifiability도
  확인했다. 적대적 리뷰어 2명 + 검증을 붙였다(별도 리포트).

  ## 구현 완료 (2026-08-01, `0073_curation_source_rule`)

  확정 설계대로 넣었다. 설계에서 **바뀐 것 하나**: 트리거를 `curated_features`가 아니라
  **`curation_items`** 에 단다(`trg_curation_items_source_rule_decision`).
  `sync_curated_feature_collection()`은 link을 만드는 지점이 **둘**(신규 item INSERT,
  `source_change` 시 `feature_id` UPDATE)이고 merge/detach 불변식이 얽힌 800줄이라,
  그 안을 두 군데 고치는 것보다 불변식이 실제로 사는 자리 — "feature_id를 가진 item에는
  근거가 있어야 한다" — 에 거는 편이 두 지점을 모두 덮고 앞으로 생길 writer도 덮는다.

  검증 술어는 **4조건**으로 늘렸다(설계의 2조건 + link 정합성 2개):
  `selection_origin='source_rule'` · `projection.feature_id = item.feature_id` ·
  `projection.source_record_key = item.source_record_key` · 그 key가
  `provider_sync.source_records`에 도달. 하나라도 실패하면 `legacy_unattributed`로 남는다.

  **함께 고친 것 — 승인 근거 판정이 두 곳에 다른 모양으로 있었다.** 공개 표면은
  denylist(`<> 'legacy_unattributed'`), merge 재타게팅은 whitelist(3값 열거,
  `merge_repo._MOVE_CURATION_ITEMS_SQL`). 값이 늘 때 whitelist만 뒤처지면 **공개 표면은
  노출하는 link을 merge가 `revoked`로 끊는다** — 어느 쪽도 오류를 내지 않아 "링크가
  언젠가 사라짐"으로만 나타난다. `infra/curation_link_basis.py` 한 곳으로 모으고
  양쪽 다 whitelist로 맞췄다(모르는 근거를 기본 신뢰하지 않는 쪽이 `0072` 원칙과 같은 방향).

  게이트: unit **1821 passed** · 관련 integration **91 passed** ·
  `ruff`/`mypy --strict`(123 files)/`lint-imports`(4 kept). 새 통합 테스트 6건은
  **변이 2회로 falsifiability를 확인**했다 — 검증 술어에서 `selection_origin`을 빼면
  fail-close 테스트 2건이, 재진입 가드를 빼면 누적·멱등 테스트 3건이 죽는다.

  곁가지로 `test_alembic_upgrade.py`가 head revision을 리터럴로 박고 있어 마이그레이션을
  추가할 때마다 깨졌다. ScriptDirectory에서 계산하도록 바꿨다.

  할 일 (2026-08-03 기준 — 4항목 중 3 완료, 1은 H35 실행 대기):

  - [x] **before/after exact count 확정** — 격리 restore clone에서 `0063→0078`을 적용해
        **공개 목록 술어 그대로** 셌다. 예상치 `3,265→264`는 폐기한다.
        `preflight 3,265 → migrate 3,043 → csv5 3,265`. 세부는 runbook §10.1.
  - [x] **one-shot 복구 경로** — `0073_curation_source_rule`. `legacy_unattributed`를 이름만
        바꾸거나 public 술어를 완화하지 **않았다**. `match_basis`에 `source_rule`을 더하고
        **검증 4조건**(`selection_origin='source_rule'` · projection↔item `feature_id` 일치 ·
        `source_record_key` 일치 · 그 key가 `provider_sync.source_records`에 도달)을 통과한
        3,043건만 append했다. `forward_recovery` 재사용은 의미 왜곡이라 하지 않았다.
  - [x] **ongoing writer 연결** — `trg_curation_items_source_rule_decision`을 `curation_items`에
        달았다. `sync_curated_feature_collection()`은 link 생성 지점이 둘이고 merge/detach
        불변식이 얽힌 800줄이라, 불변식이 실제로 사는 자리에 걸어 두 지점과 미래 writer를
        함께 덮는다.
  - [ ] **H35 실행 시**: writer reopen 전에 CSV 재import(3.5 단계)를 돌리고, 공개 표면
        3,265 복원과 #673의 미적재 457 회복을 **각각 별도 기준으로** 검증한다.
        → 재import가 222건을 전량 복원하는 것은 실 prod 데이터로 확인했다(runbook §10.1).

  **파생 발견**: `0072`의 `fk_curation_link_decisions_item`이 `ON UPDATE NO ACTION`이라
  merge의 legacy-conflict detach(`curation_item_id` 재작성)가 FK 위반으로 abort한다.
  `0074_curation_item_rekey_cascade`로 해소했다(`T-VN-H41`).

- [ ] T-VN-H35 — **prod 마이그레이션 지연 해소 (0064~0078)**

  ## ⛔ 재정의 (2026-08-04) — cutover는 사건으로 소멸했다. 폐기·재생성으로 대체한다

  **이 항목 아래의 cutover 설계(0063 전제)는 전부 이력이다. 실행하지 마라.**

  2026-08-03, pin(`map_release_revision=4a764a4f`)과 달리 **7/31 빌드(`0bdecb1f`,
  alembic head `0072`) 이미지가 배포**됐고, `docker/api-entrypoint.sh`의 무조건
  `alembic upgrade head`가 prod를 `0063 → 0072`로 올린 뒤 오류 없이 끝났다. `0073`
  (링크 3,043건 복구)이 이미지에 없어 **공개 큐레이션 표면이 3,265 → 0건**이 됐다.
  이 문서가 경고했던 "공개 curation 표면이 배포 직후 전멸한다(실증)"가 정규 cutover
  절차 **밖에서** 그대로 실현된 것이다. 상세: kor-travel-docker-manager#109.

  **사용자 결정: 데이터를 복구하지 않는다. 폐기 후 재생성한다** (서비스 전이므로 데이터를
  살릴 필요 없음). 빈 DB에 `alembic upgrade head`를 걸면 곧장 `0078`로 생성되고, `0063 →
  0078` 데이터 마이그레이션 위험 구간(0072 전멸 창 포함)이 통째로 사라진다. 이 경로는 CI
  integration(PostGIS) job이 매번 검증한다.

  따라서:
  - **typed cutover helper(`_h35_schema.py`·`_h35_contract.py`·`scripts/h35/`)는 사문화됐다** —
    `PRE_SCHEMA=0063`·`EXPECTED_PRE_PUBLIC=3265`·`EXPECTED_MIGRATED_PUBLIC=3043`이 소스
    상수라 재생성 후 preflight부터 영구 거부된다. (prod가 `0072`가 된 시점에 이미 거부
    상태였다.) 제거/축소는 후속 정리 task로 잡는다.
  - **"결합 barrier" 항목은 취소한다** — cutover 자체가 없어졌다.
  - tvn41(T-VN-41)은 **무영향** — 스택 3개 전부 자체 map-db(`kor_travel_map`)를 쓰고 prod
    무참조, live spec 기대값은 env 주입(2026-08-04 실측). 오히려 재생성 후 prod가 `0078`이
    되면 41C "PinVi consumer enable"의 schema 선행조건이 충족된다.

  ### 남은 실행 (= 현 H35)

  1. [x] 사고 시점 dump 아카이브 — `n150:~/backups/krtour_map_0072_20260803T203706Z.dump`
     1.2G, sha256 `bbba5216…379f`. **복원 검증 완료**(격리 clone, pg_restore 오류 0줄,
     1,817초; postgis 이미지는 init 완료 후 **새 DB를 만들어** 복원해야 한다 — `POSTGRES_DB`
     에는 확장이 미리 심어져 충돌). H22C 파괴적 live e2e의 실데이터 픽스처 후보로도 쓴다.
  2. [x] 재발 방지 게이트 — PR #931(`KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`; 2차 적대
     리뷰 F2로 `MODE=none`은 도입 전 제거 — 명분이던 H35 helper가 사문화돼 소비자 없는
     fail-open 스위치였다). Docker-manager 쪽 image↔pin 일치 검사는 이슈 #109로 요청.
     **주의(2차 리뷰 F1)**: prod compose(manager 소유)는 고정 `environment:` 목록이라
     호스트 export만으로는 이 env가 컨테이너에 **전달되지 않는다** — 게이트를 켜려면
     manager compose에 명시 값 결선이 필요하다(별도 이슈로 요청). 그 전까지 게이트는
     표준 compose·local-dev에서 꺼져 있는 것이 정상이다.
  3. [x] **완료(2026-08-04)** — `main@2b2dee95`로 3 이미지 재빌드(head=`0078` 수동 게이트
     통과) → `krtour_map` DROP/CREATE → compose recreate(→`0078` 10초) → 3컨테이너 healthy.
     실측 함정 2건: manager `.env`가 root 소유(sudo compose), **신규 DB 확장은 superuser
     사전 생성 필요**(`CREATE EXTENSION`은 superuser 전용, CI는 testcontainers superuser라
     못 잡음 — postgis·pg_trgm·pgcrypto·pg_prewarm + `GRANT USAGE`; #109에 절차 기록).
  4. [~] 데이터 재적재 — **concierge 축 완료**: provider job + `curated_features_refresh`
     성공, features 1,481 · curated 4,424 · **공개 표면 4,424건 복구**(전부 `source_rule`).
     geo API key 결선 공백은 `/tmp` override로 해소(영구 결선은 manager #114).
     **CSV5 486행 적재 완료(2026-08-04)** — 공개 표면 trusted **4,620**(source_rule 4,424 +
     csv_explicit 196), 미해석 290행은 대상 feature 적재 후 재import 필요.
     잔여(나머지 provider ETL 일일 스케줄 수렴 + 290행 재import)의 완주·수렴 검증은
     **`T-VN-H42`가 소유**한다.
  5. [ ] 재적재 안정화 후 H34 잔여 실행 해제(H30B는 재정의판으로 완료).
     **prod live 검증(공개 API·admin UI live 스모크·quarantine 0·공개 표면 최종 수치
     고정)은 이번 사이클에 수행하지 못했다 — `T-VN-H42` AC로 이월(2026-08-04).**
     codex 41C "prod consumer enable"은 재pin(#109 — `2b2dee95` 완료) + `T-VN-H42` 완료
     후가 경계(그 전 격리 스택 작업은 병행 무방).

  ---

  ### (이하 이력) H35×T-VN41 cutover 보정 subtask (2026-08-02)

  과거 2,841줄 H35 runbook은 적대 감사 두 번에서 `NO_GO`였고 현재 `scripts/h35/`도
  `0072`/`0078` 일부를 잘못 검증한다. 그대로 실행하지 않는다. 새 정본은
  [`runbooks/h35-prod-migration-cutover.md`](runbooks/h35-prod-migration-cutover.md)다.

  **공통 계약**: Docker-manager가 backup/migrate/CSV/bootstrap/initial/enable/canary/GC/final fence/
  verify/Pin finalize 전체의 one-process global lock과 mode `0600` durable journal을 소유한다.
  canonical 후반 순서는 `csv5 → canary → gc → exact 5-writer final fence → Map verify → PinVi final
  boundary`다. exact writer 5개는 Map API·Map Dagster web·Map Dagster daemon·PinVi API·PinVi
  Dagster다. Map은 credential/path-free
  `preflight`·`migrate`·`csv5`·`gc`·`verify` helper와 typed receipt만 제공하고 runtime을 재기동하지
  않는다. Map API/Dagster와 Pin writer를 모두 fence하며 old daemon 자동 재기동은 금지한다.
  exact gate는 **공개 3,265 → migration 3,043 → CSV5 accepted 222/rejected 0 → 공개 3,265**다.

  문서 exact head 뒤 다음 두 단위는 같은 파일을 소유하지 않아 병렬 가능하다.

  - [x] **Agent A — Map helper**: `scripts/h35/h35_cutover.py`, typed request/receipt, `0064`/`0068`/
    `0069` partial probe, `0070~0078` transactional 확인, CSV5 멱등성, 기존 client 기반 bounded GC,
    PinVi final DB evidence. orchestration·runtime 수정 금지.
  - [x] **Agent B — 검증**: 실제 PostGIS에서 helper `0063→0078→CSV5→GC→verify`, GC replay,
    generation-7 stream/source/snapshot/reconciliation/outbox/delivery/claim을 재현했다. 구조 catalog
    동명이형·drop·invalid/not-ready/disabled/function drift와 stale/expired/mixed/Merkle/backlog/chain-skip를
    mutation 0으로 거부한다. scope validator는 top/0074/0052 exact regprocedure 전체를 fingerprint하고,
    여섯 scope valid/invalid truth table와 delegate별 body/config/속성/signature/result drift를 실제
    PostGIS에서 검증한다. 최신 writer-fenced prod dump clone 리허설은 결합 barrier에 남긴다.
  - [ ] **결합 barrier**: PR #923 merge 뒤 양쪽을 최신 `origin/main`에 rebase하고, Docker-manager
    typed journal/receipt와 결합한 최종 exact HEAD를 적대 리뷰어 1명이 승인한다. 구현·검증·manager
    결합 전에는 리뷰를 요청하지 않으며, 그 전에는 n150 실행 금지.

  `0075` 적용 전 existing-row identity/NFC/trim/length/CHECK/FK 위반이 전부 0이어야 한다.
  `0075~0078`의 schema/index/outbox/source receipt/GC observation을 최종 verify한다. 일반 image-only
  rollback은 불안전하다. forward 경계 전에는 Map app·Dagster·Pin DB와 manager state/env/manifest를
  결합 복원한 뒤 옛 image를 마지막에 올리고, 경계 뒤에는 옛 restore를 거부한다.

  > **범위 갱신 (2026-07-31)** — `0070_domain_command_ledger`·
  > `0071_integrity_observation_generations`가 이미 main에 있고 #910이 `0072_curation_provenance`를
  > 더한다. **간극은 9개**다.
  >
  > **`0070`·`0071`·`0072`는 `autocommit_block()`을 쓰지 않아 all-or-nothing이다** —
  > 부분 적용 창은 `0064`·`0068`·`0069`에만 있다. `0072` 도중 죽으면 DB는 `0071`에 깨끗이
  > 남고 재실행이 처음부터 다시 한다.
  >
  > `0072` 실측(prod `0063` 기준): 파괴적 statement **0개**. backfill은 `feature_id IS NOT NULL`
  > **3,266행**에 decision 행 생성 + `curation_items` UPDATE. `curation_item_id` PK 1:1 조인이라
  > `feature_id IS NULL` 264행은 술어상 도달 불가. append-only 트리거 6개는 **전부 신규
  > 테이블에만** 붙어 기존 쓰기 경로를 깨지 않는다.
  >
  > ⚠ **`0072` downgrade는 단방향 손실이다** — `curation_link_decisions`를 drop하므로
  > cutover 이후 기록된 **진짜 provenance까지** 사라지고 재구성이 불가능하다
  > (#910의 존재 이유가 "0072 이전 상태는 근거를 복구할 수 없다"이기 때문).
  >
  > ⛔ **배포 선행 blocker: `T-VN-H40`(concierge provenance 복구).** PR #910 작성자 확인 결과
  > 복구 경로가 **누락**이고 축소 창이 **무기한**이다. H40 완료 전에는 `0072` 포함 배포를
  > 진행하지 않는다. 이 상태를 "허용 가능한 일시 축소"로 기록해서는 안 된다.
  >
  > ⚠ **공개 curation 표면이 배포 직후 전멸한다(실증).** 격리 restore clone에서
  > `0064~0072` 적용 후 **공개 노출 가능(trusted) 링크 = 0**(배포 전 3,266). 소요 **1,754초**.
  > 자세한 것은 `T-VN-H40` 실증 절.
  >
  > ⚠ **공개 curation 표면이 배포 직후 급감할 수 있다.** `_trusted_link_sql()`이
  > `match_basis <> 'legacy_unattributed'`를 요구하는데 `0072` backfill이 기존 링크를 전부
  > 그 값으로 기록한다. 코드상 확정·실행 미검증이며 #910에 확인 요청을 남겼다
  > (PR #910 코멘트). **#673의 concierge 표면과 겹치므로 배포 전 답을 받아야 한다.**

  > ## 2026-07-31 중단 시점 상태 — **다음 사람이 여기서 이어받는다**
  >
  > **prod는 무손상이다.** `c8ed6164` / alembic `0063` / 5 런타임 healthy. 배포 시도 2회는
  > 전부 fail-closed로 막혔고 마이그레이션은 한 줄도 적용되지 않았다.
  >
  > ### 확보된 것
  > - **writer-quiesced 백업** (복구점 자격 있음 — `inflight_runs=0`·`app_write_tx=0` 확인 후 채취):
  >   - `n150:/home/digitie/h35/backup/krtour_map-20260730T213912Z.dump` 1,168 MiB `sha256=629d1669f8cd3c67…`
  >   - `…/krtour_map_dagster-20260730T213912Z.dump` 65 MiB `sha256=7e331c42b578fdef…`
  >   - `…/baseline-20260730T213912Z.txt` — `alembic=0063` / features 1,030,613 / curation_items 3,530 /
  >     curation_collections 71 / curated_features 3,044 / source_entities 1,035,869 / violations 3
  >   - 그 이전 `20260730T010600Z` dump는 **fence 없이 떠서 무효**다. 쓰지 마라.
  > - **선행 조건 실측 완료**: 디스크 avail **80.7 GiB**(P1 임계 40 통과) / superuser `addr`
  >   자격증명 없이 도달(`addr|t`) / `pg_hba`는 local·127.0.0.1·::1 `trust`, 마지막 줄만
  >   `all all all scram-sha-256` / `archive_mode=off`(**PITR 없음 — dump가 유일 복구점**) / server 16.9.
  > - **자격증명 정합** cache `.env` ↔ live 해시 바이트 동일(지문 `2f2a19e6`).
  > - **runbook** [`runbooks/h35-prod-migration-cutover.md`](runbooks/h35-prod-migration-cutover.md)
  >   — 11단계 절차. **감사 2회 모두 NO_GO**다. 마지막 커밋은 2차 지적을 반영하다 중단한
  >   **미완 상태**이니 그대로 실행하지 마라.
  >
  > ### ⛔ B(단순 `ktdctl deploy`) 경로를 막는 실측
  > `compose_service.py:3540`이 `--wait --wait-timeout 120`을 **하드코딩**한다. 그런데
  > `docker/api-entrypoint.sh:216`이 uvicorn 기동 **전에** `alembic upgrade head`를 돌리고,
  > `0069` 하나만 **8~18분**(1,640만 행 `feature_weather_values`에 CIC 2개, ~3.4 GB)이다.
  > → `ktdctl pinvi-pair deploy`는 120초에 실패 판정하고 **마이그레이션이 도는 중인 컨테이너를
  > 뜯으며 자동 롤백을 발동한다.** `0064`/`0068`/`0069`가 `autocommit_block()`을 쓰므로 그 순간
  > 부분 적용 상태가 남는다. **그대로 실행하면 안 된다.**
  >
  > ### 권고 경로 **B′** (마이그레이션과 배포를 분리)
  > 1. ~~writer-quiesced 백업~~ ✅ 완료
  > 2. **candidate build-only** — 라이브러리 seam `_prepare_c6c_candidate_pair(cfg, build=True, …)`.
  >    실행 컨테이너를 보지 않아 fence 아래에서도 성립한다. ktdctl CLI는 분해 불가
  >    (`cli.py:122`가 `recreate=True` 하드코딩 / `ensure --build`는 production fail-closed /
  >    `capture`는 v4 manifest 존재로 거부).
  > 3. **마이그레이션을 일회성 컨테이너로 적용** — `--entrypoint sh -c 'alembic upgrade head'`,
  >    writer 정지 상태, 시간 제한 없음.
  > 4. **`ktdctl pinvi-pair deploy`** — 이 시점엔 이미 head라 entrypoint의 upgrade가 no-op이고
  >    120초 안에 healthy가 된다. **자동 롤백 기계가 그대로 살아 있다.**
  > 5. 실증(아래 검증 항목).
  >
  > 3→4 사이에 prod가 **새 스키마 + 구 이미지**로 잠깐 돈다. `0069` 방향은 무해하지만
  > **`0065`가 arbiter 인덱스를 바꾸므로 그 창에 curation write가 들어오면 깨진다** — writer를
  > 멈춘 채 곧바로 4로 넘어간다.
  >
  > ### 확정된 최종 순서 (2026-08-01, H40/H41 반영)
  > 범위가 `0064~0072`에서 **`0064~0074`**로 늘었고, 3과 4 **사이에** CSV 재import가 들어간다.
  >
  > | # | 단계 | 왜 이 위치인가 |
  > | --- | --- | --- |
  > | 1 | writer-quiesced 백업 | 유일 복구점(`archive_mode=off`) |
  > | 2 | candidate build-only | fence 아래 성립 |
  > | 3 | `alembic upgrade head` (일회성 컨테이너, dagster 정지, 시간제한 없음) | `--wait-timeout 120` 회피 |
  > | **3.5** | **공식 curation CSV 5개 재import** | `0072`가 어둡게 만든 **223건**을 되살린다. 이 시점엔 구 이미지가 서빙 중이고 구 이미지는 `_trusted_link_sql`을 모르므로 **사용자에게 보이는 공백이 0**이다. 4 이후로 미루면 그 순간부터 223건이 사라진다. |
  > | 4 | `ktdctl pinvi-pair deploy` | 이미 head라 entrypoint upgrade가 no-op |
  > | 5 | 실증 | 아래 게이트 |
  >
  > **3.5의 중단 게이트**: 재import 후 **공개 노출 item = 3,265**(배포 전과 동일)이어야
  > 한다. 3,043이면 재import가 안 붙은 것이고, 그 상태로 4를 진행하면 안 된다.
  > 격리 clone에서 이 세 수(3,265 → 3,043 → 3,265)를 실제로 재현했다.
  >
  > **"trusted link 수"를 게이트로 쓰지 마라** — 링크 수로는 `rejected`인
  > `[빵이네] 강원도여행정보` 1건 때문에 3,265가 나오는데, 그걸 3,266으로 기대하면
  > **정상 배포에서도 FAIL**이 뜬다. 공개 목록과 같은 술어로 센다:
  >
  > ```sql
  > SELECT count(*)
  > FROM feature.curation_items item
  > JOIN feature.curation_collections c ON c.collection_id = item.collection_id
  > JOIN feature.curated_themes t ON t.theme_id = c.theme_id
  > WHERE item.archived_at IS NULL AND c.archived_at IS NULL
  >   AND item.status = 'included'
  >   AND c.status = 'published' AND c.visibility = 'public'
  >   AND t.visibility = 'public'
  >   AND EXISTS (SELECT 1 FROM feature.curation_link_decisions td
  >               WHERE td.decision_id = item.accepted_link_decision_id
  >                 AND td.curation_item_id = item.curation_item_id
  >                 AND td.feature_id = item.feature_id
  >                 AND td.decision_kind = 'accepted'
  >                 AND <trusted_basis_sql('td.match_basis')>)
  > ```
  >
  > `<trusted_basis_sql(...)>`는 `curation_link_basis.trusted_basis_sql()`이 만드는
  > 술어를 그대로 넣는다 — basis 값을 게이트에 하드코딩하면 값이 늘 때 게이트만 뒤처진다.
  > **배포 전 baseline은 `0072` 이전이라 decision이 없으므로** 그 EXISTS 대신
  > `item.feature_id IS NOT NULL`로 센다(같은 3,265가 나온다).
  >
  > ### 배포 target
  > **실행 시점 `origin/main`**(사용자 확정, 0069 포함). main이 계속 전진하므로
  > `/home/digitie/h35/h35b_mkdeploy.sh`가 실행 시점에 target을 확정해 배포 스크립트를 생성한다
  > (검증된 원본에서 **커밋 상수 2줄만** 교체 — flock·자격증명 검증·자동 롤백 보존).
  >
  > ### 실증 항목 (반증 가능해야 한다)
  > `alembic_version = 0069_weather_series_catalog` / `uq_violations_open_dedupe_key` 존재 /
  > `last_seen_at`·`source_present`·`external_component_id` 컬럼 존재 / 이미지에 H36
  > `_adopted_match` 존재 / dagster에 `DROPPABLE_ISSUE_CODES` 존재 / 오링크 3건 미연결 유지 /
  > `GET /v1/curations/collections` 200. 스크립트는 `/home/digitie/h35/h35_verify.sh`
  > (배포 전 baseline에서 6항목이 `★FAIL`로 나오는 것을 확인했다 = 반증 가능).
  > **`features`·`source_entities` 행 수는 고정 통과값으로 쓰지 마라** — 하루 +37 드리프트가 실측됐다.



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

  **`0069_weather_series_catalog` 실측 분석(2026-07-31)** — 배포 target에 새로 포함됐다:
  - **파괴적 statement 0개.** DELETE·TRUNCATE·컬럼 삭제·타입 변경·WHERE 없는 UPDATE 전부 없다.
    `downgrade()`가 **완전 대칭**이라 **0064~0069 중 유일하게 완전 가역**이다.
  - 유일한 DML은 자기가 방금 만든 빈 테이블에 `INSERT … SELECT DISTINCT … ON CONFLICT DO NOTHING`
    (**7,796행**). 기존 테이블에 **행·컬럼 변경 0건**.
  - 기존 구조 게이트 중 통과값이 바뀌는 것은 **`alembic_version` 하나뿐**이다(→ `0069_weather_series_catalog`).
  - 대가는 위험이 아니라 **시간(+8~18분)과 디스크(+3.4 GB)**다. CIC 2개가 1,640만 행
    `feature_weather_values`를 색인한다(ShareUpdateExclusive만 잡아 읽기·쓰기를 막지 않는다).
  - ⚠ **새 이미지 + 0069 미적용** 조합에서 기존 공개 엔드포인트
    `GET /features/{feature_id}/weather`가 503이 아니라 **500**을 낸다(#901이 batch 쿼리로
    재배선했고 그 SQL이 `weather_metric_series`를 hard JOIN한다). 반대 방향(스키마 적용 + 구
    이미지)은 무해하다. entrypoint가 upgrade 성공 뒤에만 uvicorn을 exec하므로 정상 경로에서는
    발현하지 않지만, **alembic을 건너뛰고 API를 강제 기동하면 발현한다.**
  - `autocommit_block()` 2회 + CIC 2개 → 부분 적용 가능 지점이다. `upgrade()`는 재진입 가능하게
    작성됐고(`IF NOT EXISTS`/`ON CONFLICT DO NOTHING`/`indisvalid` 확인 후 재빌드) entrypoint의
    재시도 루프가 자동으로 돌린다. 다만 **재시도마다 16.4M행 DISTINCT 스캔(60~100초)과
    3.4 GB 인덱스 재빌드를 처음부터** 한다.

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

- [x] T-VN-H31 — **등대 공급원 부재 — provider 신설 취소로 종결** (2026-08-03)

  > **`address_hint` 계약 변경 (2026-07-31, #909/#910)**
  > #907이 `address_hint` 매칭을 **공백 토큰 AND**로 고치고(직렬화 jsonb 통짜 substring이라
  > 다중 토큰이 매칭 안 되던 역전을 수정) 등대 105행을 출처 확인해 채웠다.
  > **#910이 그 자동 링크를 fail-close로 막았다** — `address_hint` 단독으로는 자동 채택하지
  > 않고, 구조화 주소 matcher와 행별 provenance(`0072`)를 요구한다.
  >
  > 즉 "주소가 있으면 링크를 연다"는 내 전제가 **근거로 불충분하다**는 판정이다.
  > 채워 넣은 105행의 주소 자체는 버려지지 않고 sidecar provenance
  > (`lighthouse-stamp-tour.provenance.json`)로 옮겨 **행별 근거**를 갖는다.
  >
  > 등대 feature 공급원 부재는 **그대로 남는다** — CSV에 `feature_id`가 2건뿐이라
  > 새 계약으로 재import해도 105 중 2만 복원된다.

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

  ~~할 일: 등대 원천 데이터 확보·CSV 스키마 확정 → 변환 함수 + 적재 경로 → 무결성 게이트 →
  ADR-080 → 링크 판정(별도).~~

  ## 판정 — **provider 신설은 취소됐다 (사용자 지시)**

  > **"등대 etl provider 은 취소, csv 기반 큐레이티드만 남김. 큐레이티드의 미정합 자료는
  > 관광목적의 테마 장소이므로 등대가 아니더라도 문제가 없음. 다른 소스에서 위치 찾아서
  > 반영할 것."**

  이 지시로 위 "할 일"의 핵심(변환 함수 + 적재 경로 = provider 신설)과 **ADR-080이 함께
  취소**된다. 저장소 상주 CSV를 feature 공급원으로 쓰는 새 소스 종류를 만들지 않는다.

  **"다른 소스에서 위치 찾아서 반영"은 이행됐다** — #907이 105행 `address_hint`를 전량
  채웠다(현재 CSV 실측: 105행 중 address_hint 105, feature_id 2).

  그런데 **#910이 그 주소로 자동 링크하는 것을 fail-close로 막았다.** 링크하려면 CSV에
  `feature_id`가 명시돼 있어야 하는데, 그러려면 등대 feature가 DB에 있어야 하고, 그것을
  공급할 provider가 방금 취소된 것이다. 즉 **103건은 구조적으로 미연결로 남는다.**

  그리고 그것이 **문제가 아니라는 것이 위 지시의 요지**다 — 스탬프투어는 관광 테마이지
  항로표지 대장이 아니다.

  실측 재확인(2026-08-03, prod): 이름에 `등대`가 든 active feature는 상당수가
  `02010100`(음식점) 카테고리의 내륙 가게다(대구 동구·시흥·군포 등). 이름 매칭으로
  링크하면 그런 가게에 붙는다 — `T-VN-H36`이 이름 단독 자동링크를 금지한 이유와 같다.

  **남는 것**: 없음. 등대 105행은 CSV 큐레이션으로 존재하고 주소를 갖는다. 링크 2건은
  유지되고 103건은 미연결로 남되 공개 표면에는 큐레이션 항목으로 정상 노출된다.
  (미연결 자체를 finding으로 세는 축은 `T-VN-H25A`/`H34` 소유이며 여기서 다루지 않는다.)

### T-VN-H22 — 0065 curation owner quarantine 재분류

migration 0065가 원 projection durable link 없는 canonical-only item을 보존한 quarantine은
read/decision/write/UI를 한 PR에 몰지 않는다.

#### 선행 실측 (2026-08-03) — **격리 대상은 0건이고, 구조상 0건이다**

착수 전 규모를 재 보니 **격리될 item이 하나도 없다**. 계획을 세울 때 전제한
"canonical-only item이 격리돼 있다"는 상태가 이 DB에는 존재하지 않는다.

- 라이브 prod(`krtour_map`, 읽기 전용) — `curation_items` 3,530건이 **2×2의 대각선만**
  채운다: legacy-marker collection 52개는 `curated_features` 투영본 3,044건만 담고,
  CSV collection은 네이티브 486건(`korean-tourism-100`·`arboretum`·`lighthouse`·
  `heritage`)만 담는다. 격리는 **비대각 칸**(legacy collection 안의 네이티브 item)을
  요구하는데 그 칸이 비어 있다 → 0건. dangling collection 참조도 0.
- 격리 restore clone에 `0065`를 **실제로 적용**해도 quarantine collection 0개 / item 0건.
- `legacy:quarantine`·`migration_quarantine` marker를 쓰는 코드는 `0065` **하나뿐**이다
  (런타임·다른 migration·admin UI 어디에도 생성 경로가 없음). `0065`는 1회성이므로
  **배포 후에도 영구 0건**이다.

  주의: 처음 낸 "legacy 밖 item 0건"은 3값 논리 버그였다 —
  `NOT (metadata->>'migrated_from' = '…' OR key LIKE 'legacy:%')`에서 키가 없는
  collection은 `NULL OR false = NULL` → `NOT NULL = NULL`로 걸러진다. 격리 건수 자체는
  `0065`와 같은 **긍정형** 술어를 써서 영향이 없었다.

**따라서 H22A/B/C는 대상이 없다.** 셋 다 "격리된 item을 운영자가 재분류한다"가 유일한
목적인데 재분류할 것이 영구히 없다. 세 과제를 지금 구현하면 소비자 없는 계약·UI가 남는다.
조사가 함께 지적한 "배포 직후 `[0065 격리]` collection이 admin UI에 설명 없이 등장한다"는
경고도 collection이 생성되지 않으므로 함께 소멸한다.

- ~~**판정 보류 — 사용자 결정 대기.**~~ → **해제(2026-08-04)**: 사용자 지시 "h22까지
  순차적으로 진행", "h22는 하나의 pr로". 대상이 현재 0건이어도 도구를 갖춘다 — preflight
  게이트(`quarantine_candidates_before`)가 0이 아니게 되는 순간 이 UI가 소비처다.
  세 항목 모두 단일 PR로 구현 완료(아래 각 항목 완료 기록).
- **대신 배포 게이트가 이 전제를 스스로 재게 했다**(#929): H35 **preflight**가
  `quarantine_candidates_before`를 0으로 검사한다. 경계 뒤(`migrate`/`verify`)에는
  `quarantine_collections`·`quarantine_items`를 **관측치로만** 남기고 거부하지 않는다.
  이 값이 0이 아니면 H22를 착수해야 한다는 신호다.

  게이트를 preflight에 둔 이유는 적대 리뷰가 내 첫 설계를 반증했기 때문이다. 나는
  "격리가 생기면 어차피 `public_items_verify`가 깨진다"고 적었는데 **틀렸다** — 격리
  조건(`legacy_projection_id IS NULL`)은 `status`·`source_present`·accepted link 어느 것도
  요구하지 않아 공개 집합과 독립이고, 실제 픽스처에서 격리 1건이 생겨도 공개 수는 3,043
  그대로였다. 즉 경계 뒤 hard check는 **기존 게이트가 통과시키던 상태를 새로 거부**하는
  것이고, 그 지점에는 출구가 없다(csv5는 accepted prior receipt 요구 / migrate 재실행은
  `schema_before=0063` 요구인데 DB는 이미 `0078` / `0065` downgrade는 durable state에
  fail-close → PITR 없는 prod에서 dump 복원만 남는다). `#925`에서 index signature로 겪은
  것과 같은 계열의 함정을 내가 다시 만든 것이었다.

계획상 모호함 3건은 구현에서 이렇게 확정했다:

- **"후보 theme/source"** = 추천이 아니라 **병렬 표시**로 확정. 격리 collection이 0065 때
  복사 보관한 theme/source와 원본 collection의 **현재** theme/source를 나란히 내려준다
  ("자동 target 추정 금지"와 정합). 추천으로 읽는 해석은 폐기.
- 격리 근거는 collection marker 정본 술어(`created_by='migration:0065'` AND
  `metadata @> migration_quarantine`) + `original_collection_id` 역참조로 재구성. 이동된
  item과 수동 추가 item의 구분 불가는 그대로 수용(전체가 재분류 대상이므로 실해 없음).
- 페이지네이션은 ADR-048 `meta.page.next_cursor` 봉투. `/admin/link-audit` shape는 위반
  잔재라 따르지 않았다.

- [x] T-VN-H22A — **quarantine read model·conflict preview** *(2026-08-04, H22 단일 PR)*

  `GET /v1/admin/curations/quarantine`(+`/{id}/items`) — marker 정본 술어 기반 목록 +
  원본/격리 theme·source 병렬 + item별 conflict preview. 충돌 판정은 이동이
  `collection_id`만 바꾸는 UPDATE라는 사실에서 도출 — 위반 가능 제약은 정확히 2개:
  (A) `uq_curation_items_component_identity`(비-partial — archived 상대도 충돌),
  (B) `uq_curation_items_active_source_feature`(양쪽 다 partial 술어 충족 시만). 순수
  SELECT, keyset cursor(`{"v":1,...}` 정확 키 검사), 자동 target 추정 없음.

- [x] T-VN-H22B — **원자적 reclassification command** *(2026-08-04, 같은 PR)*

  `POST .../quarantine/{id}/reclassify` — `move`(target 지정 또는 원본, item subset 지원) /
  `confirm_standalone`(marker 2키만 제거, 나머지 metadata 보존). lock 순서: 전역 advisory →
  collection들 id 오름차순 FOR UPDATE → **lock 후 marker 재검증**(TOCTOU) → items 오름차순
  FOR UPDATE → (A)/(B) 재검사 → 충돌 시 409 fail-close(충돌 목록 detail, 무변경) →
  UPDATE/DELETE(빈 격리 정리). `admin.curation-quarantine.reclassify`를 #906 정적
  inventory(registry 68→69)와 route_policy에 등록 — 사전 심어진 quarantine barrier 충족.
  actor 감사는 `updated_by` + domain ledger.

- [x] T-VN-H22C — **Admin UI·실데이터 파괴적 수용** *(2026-08-04, 같은 PR)*

  H22A/B 계약만 소비하는 `curation-quarantine-panel.tsx`(49B controller/view 관용, 기존
  client 파일 수정은 2줄) — 빈 상태 1급(실데이터 0건이 정상), 격리/원본 병렬 표시,
  conflict 배지, item subset 이동 + AlertDialog, 409 충돌 목록 렌더, 별도 확정. mocked
  spec 6건(BFF 강제·`Idempotency-Key` 헤더 단언, manifest 276→284 재고정 — main의 기존
  drift 278 + 기존 실패 7건은 tvn41 잔여로 별도) + live spec 저술
  (`curation-quarantine-write.live.spec.ts`, 격리 clone 전용·env opt-in — 실데이터
  quarantine이 0건이라 러너가 합성 필요).

  **파괴적 수용은 격리 스택(로컬 postgis + 실 API 서버, HTTP 전 경로)에서 9흐름 실증**:
  목록 병렬·preview 진리표·충돌 포함 move 409 fail-close(무변경 검증)·부분 move·terminal
  replay(`Idempotency-Replayed: true`)·fingerprint 409·전량 move 후 빈 격리 DELETE·
  confirm_standalone(marker 2키만 제거, 기타 metadata 보존)·확정 후 재확정 404.
  참고: 사고 시점 dump(`krtour_map_0072_*.dump`, 복원 검증됨)는 향후 실데이터 픽스처로
  쓸 수 있으나 quarantine 행이 없어 이번 검증은 합성 시드를 썼다.

- [x] T-VN-32C — **PinVi alias-map cutover·legacy write fence·응답 값 전환** (2026-08-05 완료)

  PinVi consumer를 UUID+alias contract로 전환하고 양 저장소 checksum을 맞춘다. legacy write를
  fence하되 legacy ID 제거는 T-VN-39 soak 뒤로 남긴다.

  **전반부 착지(본 branch + PinVi 쌍 branch `feat/tvn32c-uuid-alias`)**:
  ① 이관 표면 — ADR-068 결정 4의 "DB-to-DB 이관"을 service read 2종으로 판단
  (`GET /v1/service/feature-alias-maps`(keyset 페이지)+`/checksum`(merkle
  root) — PinVi 소비는 HTTP-only·cache-target snapshot/merkle 선례,
  `require_service_token`·route_policy SERVICE, read-only라 registry 미등록).
  ② `feature-alias-map-v1` checksum 계약(`core/feature_alias_map.py` 순수:
  NFC-거부 alias·canonical uuid·닫힌 kind, 길이 prefix + domain separation
  leaf(`KTMFAMLEAF\0`)·byte-order 정렬·odd-promotion merkle(`KTMFAMNODE\0`/
  `KTMFAMEMPTY\0`), 파생 검증 분리) + 양 저장소 공용 golden
  `contracts/feature-alias-map-v1-golden.json` — PinVi 독립 구현
  (`app/core/feature_alias_contract.py` — namespace를 basis 문자열에서 재파생)
  이 vendored 사본으로 재계산 대조. ③ legacy write fence — alembic
  `0082_legacy_write_fence`: alias map 불변(UPDATE 전면 거부·직접 DELETE
  거부·feature purge CASCADE만 허용 — removal manifest "alias 유지" fence) +
  identity 불변(feature_id/feature_uuid UPDATE 거부) DB 트리거 fail-close,
  0079 트리거 2종은 재평가 후 **유지**(fill은 0080 CHECK가 요구하는 유일값만
  쓸 수 있는 강제 메커니즘의 일부, AFTER alias는 INV-068-01 원자 보장 —
  0079/0081 docstring), `COLLATE "C"` keyset index(+모델 metadata 정합).
  f_* 신규 발급 fence는 비파생 generator 채택과 불가분이라 **의도적으로
  checksum 게이트 뒤 잔여로 순서 고정**(발급 전환은 신규 행 응답에 UUID 값을
  조기 누출 — rollout "checksum 일치 후 응답 전환" 위반 + upsert idempotency
  재결선 필요). ④ PinVi 이관 준비 — UUID shadow 컬럼 migration
  (`20260804_0049`: trip_day_pois/curated_plan_pois.feature_uuid,
  feature_suggestions.target_feature_uuid) + alias-map client
  (`clients/kor_travel_map_alias_map.py` — keyset 전진·계약 위반 fail-close) +
  검증된 이관 실행기(`services/feature_uuid_cutover.py`,
  `pinvi-feature-uuid-cutover` CLI: pull→독립 root/count·파생 검증→매칭 3열
  rewrite·미매칭은 NULL 유지+보고, dry-run 지원). ⑤ artifact — OpenAPI
  admin/service 재생성(user sha 무변경)·`openapi-diff-v1.json` baseline
  재고정+revisions(이관 표면은 목표 diff 항목 아님 — 존치·폐기는 39 소관)·
  unit sha 상수 재고정.

  **쌍 PR 착지(2026-08-04)**: Map #940 merge `e12494bd` + PinVi #428 merge
  `3ff54b8b`(squash). 유예분 완료 — alias golden 핀 `_UPSTREAM_MAP_COMMIT` =
  merge SHA + contract-pin-consistency byte-diff 단계, service snapshot 재추출
  (`144b4335…` — cache-target operation diff 무변경 실측 → codex n150 paired
  live proof 유효), `_ARTIFACT_COMMIT`/`_FUNCTIONAL_OWNER_COMMIT`/config/
  `.env.example` 회전. ⓪ 사전 스캔 완료 — prod 467,697행 중 canonical UUID
  형태 legacy `feature_id` **0건**(L7 shadowing 클리어, TCP read-only 실측).
  배포 결선 예고는 docker-manager#128(EXPECTED_HEAD=`0082_legacy_write_fence`
  + PinVi 계약 env 2종 — sync enable 시 fail-close 주의, Map 먼저 순서 제약).

  **checksum 게이트 통과(2026-08-05)**: PinVi 배포 + cutover dry→real —
  양 저장소 root 일치(`8bd9534a…`, 731,600) + trip_day_pois 26행 shadow 채움.

  **PR-1 + 쌍 PR + 0083 배포 완주(2026-08-05)**: Map #950 merge `2a8642bd`
  (0083 — 파생 CHECK 해제·선언적 사본 일치 CASCADE FK+UNIQUE·비파생 UUIDv7
  generator app `make_feature_uuid`/SQL `feature.uuid_generate_v7()` 동일
  레이아웃·verify 이원화 fail-close·golden nonderived_v1 개정, 적대 리뷰
  2인 GO) + PinVi #430 merge `6325d814`(파생 등식 폐기 수용·cutover 리터럴
  자기-정본화 opt-in·golden 재vendor `dc0a6595…`+merge SHA 핀·staleness
  golden 감시). prod 배포 게이트 순서 완주(PinVi 선배포 → 사전 점검 0/0 →
  Map api 0083 적용 → dagster·daemon), 사후 검증 정상(`derivation_enforced:
  false`, 731,733) — journal 2026-08-05 (7)·dm#128.

  **PR-2 머지(2026-08-05, #952 `8c5bdcf8`)**: 응답 `feature_id` 값 UUID 전환
  코드 완결 — 전 read 표면 치환(cursor legacy 축·echo 예외 보존, ADR-083
  §5-6), write/scope 경계 해석 전수(W1-W8·S1-S13 + bulk 해석기), admin UUID
  fast-path, curated snapshot 빌더 UUID화, h35 CLI pre-uuid 스키마 변형
  (역사 표면 보존). 적대 리뷰 2인 GO(trip_card echo 등식·scope 해석
  트랜잭션 배치 등 H 2건 반영), CI 8/8.

  **배포 완료(2026-08-05, dm#128)**: ①H30B 게이트 기완료 충족 ②`8c5bdcf8`
  4-이미지 배포(사후 검증: 상세 UUID·batch echo·trip_card 등식 정상)
  ③curated snapshot 활성 500 전량 재물질화(멱등 확인, 비활성 334 동결 보존).

  **잔여**: ④ live e2e fixture 재생성(새 표면 기준, n150 per-file 저부하) →
  ⑤ PinVi user 스냅샷 재고정 PR + 유예 동봉(PinVi CLI
  `--accept-uuid-literals`+runner 출력, `derivation_enforced` cutover 사전
  검사 배선) → ⑥ dagster entrypoint EXPECTED_HEAD 기계 인터록(NEW-5, dm base
  compose 기본값 갱신 동타이밍). 관측: 32B 기간 저장 UUID 표기 scope 레코드
  잔존(재실행 조용한 no-op — 리뷰 L4)·quarantine 재-link 프론트 대조(F6).
  legacy ID·FK 체인 물리 제거는 T-VN-39 removal manifest.
  **운영 점검(상시)**: 0079/0081 트리거 보장은 trigger-respecting 세션
  한정이다 — `session_replication_role=replica`(superuser)는 우회 가능하므로
  `count_features_missing_identity` 정기 관측(0,0 확인)이 alias 결측 방어선
  (32C 리뷰 M4).


### T-VN-31 — vNext target freeze

ADR은 존재하지만 목표 DDL/OpenAPI diff/실행 제약 artifact는 없다. 구현과 freeze를 분리한다.

> **미정 표기 원칙(2026-08-04 freeze)**: ADR·보고서·task 정의가 침묵하는 세부는 artifact에서
> 발명하지 않고 SQL `-- 미정(T-VN-XX 구현 소관)` / JSON `"decision":
> "deferred-to-implementation"`으로 남긴다. freeze의 정직성이 완성도보다 우선한다.
> 적대 리뷰 2건(정합성·실행성)을 같은 브랜치에서 반영했다 — 발명분 회수(state 조합
> CHECK·subtype full GiST·summary bucket identity·price known_at), 정본 명시분 반영
> (user status 3축 diff·weather valid_during range·state transition 흡수처·ADR-073
> 배타 열거 removed), 실행성 보강(invariant phase 태그·파서 fail-open 봉합·diff
> counts 2차 방어·summary surrogate PK).

- [x] T-VN-31A — **목표 DDL·데이터 불변식 freeze** (2026-08-04 완료)

  schema/table/column/type/FK/CHECK/index/view/trigger와 backfill 전후 불변식을 실행 가능한 SQL
  artifact로 고정한다. migration 번호와 구현 SQL은 아직 넣지 않는다.

  완료 기록: `contracts/vnext/target-schema-v1.sql`(빈 PostGIS DB 자기완결 적용, ADR-075 규율
  주석) + `contracts/vnext/target-invariants-v1.sql`(H35 preflight 6종 패턴 + ADR별 불변식,
  `expect: 0` assertion 43개 — machine-readable phase 태그 pre-backfill/post-backfill/both)
  + `contracts/vnext/target-schema-fingerprints-v1.json`
  (H35 7 카테고리 catalog canonical SHA-256, PG16/PostGIS 3.5).

- [x] T-VN-31B — **목표 OpenAPI·consumer diff freeze** (2026-08-04 완료)

  admin/user/PinVi surface별 추가·삭제·rename·enum/status/error 변화를 machine-readable diff로
  고정하고 consumer-first 배포 순서와 호환을 버릴 시점을 명시한다.

  완료 기록: `contracts/vnext/openapi-diff-v1.json`(surface×change, 현행 3 spec baseline
  sha256 핀, 항목별 basis 필수, Wave 0/1 기착지분 제외) +
  `contracts/vnext/consumer-rollout-v1.json`(task별 consumer-first 순서·write-fence·호환
  폐기 시점·PinVi 3 snapshot 재-vendor 여부(ADR-079 규율)·T-VN-39 removal manifest).

- [x] T-VN-31C — **제약 test·복구 preflight freeze** (2026-08-04 완료)

  목표 DDL/OpenAPI를 위반하는 fixture와 shadow checksum, forward recovery, write-fence preflight를
  executable contract로 만든다. 31A/B artifact drift를 CI에서 fail-close한다.

  완료 기록: `contracts/vnext/violation-fixtures-v1.sql` + `expected-rejections-v1.json`
  (8 case — alias 중복·provider 3-tuple 중복·geometry invalid/empty·override active 중복·
  notice is_current 중복·weather NULLS NOT DISTINCT 중복·bitemporal 역전, 기대
  SQLSTATE·제약명. 3축 불가능 조합 case는 CHECK 정의 자체가 미정(T-VN-34A)이라 구현
  PR로 이월) + `contracts/vnext/recovery-preflight-v1.json`(H35 runbook §6 writer
  registry·fence 증거 key·ADR-075 결정 3 forward recovery/PITR 판정·Merkle v1 정의) +
  `tests/integration/test_vnext_target_freeze.py`(빈 PostGIS 적용→불변식 0→fixture 거부→
  fingerprint 재계산 일치) + `tests/unit/test_vnext_contract_artifacts.py`(artifact bytes
  sha256 고정 + spec baseline·operation 실존 검증 + JSON shape — 매 PR unit job fail-close).

- [x] T-VN-32A — **UUID schema·deterministic backfill** (2026-08-04 완료)

  UUID identity와 legacy alias table을 추가하고 같은 snapshot에서 deterministic backfill·UNIQUE/FK
  불변식을 고정한다. 기존 문자열 ID는 아직 제거하지 않는다.

  완료 기록: alembic `0080_feature_uuid_shadow` — `feature.features.feature_uuid`
  (backfill 후 NOT NULL + `uq_features_feature_uuid`) + `feature.feature_aliases`
  (alias PK · legacy `feature_id` text FK · `feature_uuid` · `alias_kind`, freeze
  §4 대응 제약명 정합) + INSERT 트리거 2종(BEFORE fill / AFTER legacy alias 원자
  생성 — repo 2곳 + 테스트 직접 seed 37개 파일 등 전 write 경로를 경로별 SQL 수정
  없이 보장). **freeze 미정 3건 결정**(0079 docstring 근거): ① 생성기 =
  `uuid5(uuid5(NAMESPACE_URL, 'kor-travel-map:feature-uuid:v1'), legacy_id)` —
  DB server default 없음(정본 신규 행 generator·UUIDv7 여부는 32B 소관), ②
  alias_kind = 닫힌 CHECK `('legacy_feature_id')`, ③ alias FK ON DELETE =
  CASCADE(alias/uuid는 파생값·재계산 가능). Python 정본
  `core/ids.feature_uuid_from_legacy` + pgcrypto SHA-1 SQL mirror
  `feature.feature_uuid_from_legacy`(고정 벡터 상호 대조).
  `tests/integration/test_feature_uuid_shadow_migration.py` 8건 — backfill
  완전성·UNIQUE/NOT NULL·alias 1:1·freeze INV-068-01~04 그대로 실행(05는
  provider_dataset_id가 33A 소관이라 제외 명시)·별도 DB 재실행 결정론·downgrade
  무손실 왕복·신규 upsert 원자 생성·명시 uuid 존중 + unit 고정 벡터 2개. 읽기
  경로·기존 문자열 ID 무변경(32A 계약).

- [x] T-VN-32B — **Map consumer-first dual read/write** (2026-08-04 완료)

  repository/API/notice lineage를 UUID 정본으로 읽고 alias를 경계에서만 해석한다. 신규 write는 UUID와
  alias를 원자 생성하고 legacy-only 신규 행을 차단한다.

  완료 기록: ① 경계 alias 해석 단일 메커니즘 — `infra/feature_identity.py`
  `resolve_feature_identity(session, ref)`가 legacy `f_*` alias·canonical UUID
  양쪽을 정본 키 쌍 `FeatureIdentity(feature_id, feature_uuid)`로 해석
  (형식 오류 422 · 미해석 404, UUID-정본 우선/alias fallback 결정적 순서) +
  `kortravelmap.api.feature_ref.resolve_feature_ref_or_error` 공용 경계 헬퍼.
  **removal-슬레이트 표면을 제외한 전 feature `{feature_id}` 경로에 적용** —
  user detail·sources·observations history·weather·price·contained-features·
  **weather/forecast(적대 리뷰 F2로 뒤늦게 편입 — 종전엔 이 경로만 해석을
  건너뛰어 형식 오류에도 200+빈 timeline)** / admin detail·revision·weather·
  price·PATCH·DELETE·deactivate. **의도적 제외 3표면**(적대 리뷰 F3 명시):
  `GET /v1/curations/features/{id}`·`GET /v1/public/{beaches,festivals}/{id}` —
  freeze openapi-diff에서 ADR-073 배타 열거로 removed 슬레이트(T-VN-40B/39
  소관)라 변환하지 않으며, 형식 오류가 422가 아닌 404로 떨어지는 비일관을
  포함한 채 제거 시점까지 동결. 내부 전달·조회는 해석된 정본 키로만
  (ADR-068 결정 3). operator lineage의 별도 존재 확인 쿼리
  (`_operator_feature_or_404`)는 해석 성공이 행 존재를 함의하므로 제거.
  ② dual read — alembic `0081_uuid_dual_read`가 `public_features` view에
  `feature_uuid`를 재고정(SELECT * 컬럼 목록, 공개 술어 무변경), repo 단건
  (`_FEATURE_ROW_COLUMNS_SQL`)·bbox/in-bounds·search·nearby(coord/by-target)·
  contained·service batch(`base.feature_uuid`)·admin 목록/상세가
  `feature_uuid`를 select 목록에만 추가(join/술어 무변경 — EXPLAIN 회귀 없음).
  응답 additive 노출: user detail/search/in-bounds/nearby item, service
  `POST /features/batch` item(found/retired/suppressed/unchanged) ·
  `POST /features/weather/batch` item(거대 조회 SQL 무변경 —
  `get_feature_uuid_map` 병행 해석), admin 목록/상세. **응답 `feature_id` 값은
  legacy 유지** — 값 전환은 32C(rollout "checksum 일치 후 Map 응답 UUID 전환",
  consumer-first cutover 규율). ③ notice lineage —
  `public_active_notice_feature_identities`가 `{feature_id: feature_uuid}` 쌍을
  반환하는 단일 표면(기존 `public_active_notice_feature_ids`는 **제거** —
  잔여 호출자 전부 identities로 이행). ④ 신규 write — **dual 기간 정본
  generator 결정: uuid5 파생(`expected_feature_uuid`), UUIDv7은 legacy id
  소멸(32C 이후) 전 미채택**(결정론 = 양 저장소 checksum 전제). 이 규칙을
  app 검사에만 두지 않고 `0080`이 CHECK 2종
  (`ck_features_feature_uuid_dual_derivation` ·
  `ck_feature_aliases_uuid_dual_derivation`)으로 **DB 층에서 강제**(fail-close
  by construction — 32A의 "임의 명시 uuid 존중" 열린 계약을 의도적으로 닫음,
  해당 32A 테스트 재정의). provider upsert·admin add SQL은 `feature_uuid`를
  writer 명시 INSERT + RETURNING 대조(`verify_feature_uuid` →
  `FeatureIdentityInvariantError`) — 관측 계층. 0079 트리거 2종은 raw SQL
  seed 경로 편의 fill로 유지(파생 강제는 CHECK가 담당, 트리거 제거는 32C
  write fence 시점 재평가 — 0079 docstring 갱신). CHECK 2종은 dual 기간 한정
  fence로 32C에서 비파생 generator 채택과 함께 제거한다. ⑤ OpenAPI 3 spec
  재생성 + `openapi-diff-v1.json` baseline sha 재고정·`revisions` 개정 기록
  (diff 항목/counts 무변경 — ADR-068 값 전환 항목은 32C 목표 상태로 존치).
  **32C/39 이월 명시**: 내부 FK 체인(source_links/curation/price/weather 등)의
  UUID 조인 재작성과 referencing table shadow uuid 컬럼(rollout이 legacy FK
  체인 fence를 32C, 제거를 39로 고정), 응답 `feature_id` 값 UUID 전환,
  legacy write fence·트리거/CHECK 제거, PinVi vendored snapshot 재추출(32C 쌍
  PR), service/weather **batch body**의 feature 참조 UUID 해석(경로 참조와의
  비대칭 — 적대 리뷰 F4, 값 전환과 같은 시점), legacy ID 물리 제거(T-VN-39 removal manifest). 검증: unit 1,981(identity
  순수 계약 11 신규) · api 1,069(경계 dual/422/additive/404 재정의) · 신규 통합
  9(`test_feature_identity_boundary.py` — 양형식 해석·미존재·형식 오류·
  view/단건/bbox/batch/notice 병행 노출·upsert/admin-add 원자성·CHECK drift
  거부·alias 결측 invariant 관측) · 32A migration 8(명시 uuid fail-close
  재정의) + feature_repo 26 + freeze 3 + alembic 일관성/공개 view/notice/
  nearby/in-bounds 회귀 73 + perf gate tier1 shape 재고정(feature_uuid 의도적
  계약 변경) + H35 rehearsal(h35 도구의 head 등호 고정을 campaign target 앵커로
  수정 — 32A가 head를 전진시켜 생긴 본 branch 잠복 회귀, h35 81건 green) ·
  전체 통합 suite에서 32B 무관 잔여 실패는 live kor-travel-geo 인증 미결선
  env 5건(base 재현)과 pipeline cancellation lock-poll env 1건(base 재현)·
  suite 부하 flake 1건(단독 green)뿐 · export --check drift 0 · ruff/mypy
  --strict(main+api)/lint-imports clean.


## 2026-08-04 — T-VN-41D Map durable writer-drain control plane

- [x] **T-VN-41D — Map durable writer-drain control plane** (Manager T-049F / issue #115)

  migration `0079`이 Map application DB에 lease·instigation snapshot·owned run CAS를
  정규화했다. frozen Compose one-shot API image의 private `begin|attest|restore` command만
  schedule/sensor pause·late run terminal cancel·exact restore를 수행하며 Manager에는 opaque
  lease와 receipt SHA-256만 전달한다. begin 응답 유실·new owner recovery·backup rollback은
  daemon을 열기 전에 restore receipt와 prior pair attestation을 요구한다. public REST/OpenAPI,
  existing cache-target token, admin/ops command, production/n150은 사용하지 않았다. strict
  command 5건, isolated PostgreSQL 3건, Manager regression 143건, ephemeral Docker Compose
  rehearsal 1건을 통과했다.

