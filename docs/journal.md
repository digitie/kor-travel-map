## 2026-10-25 — 공개 provider patch P-first(초안)

기존 본문 앞 protocol EX를 보강했다. [검증·미완](reports/2026-10-25-provider-patch-protocol-entry.md). 실제 PG·운영은 미완이다.
## 2026-10-25 — Provider base UPDATE-first 후보(425, 미수용)

- materializer 두 루프만 분리했다. 첫 fixture 실패를 보존하고 테스트만 고쳐 실제15 PASS/14.129초·정확 정리를 확인했다. 활성 정책20·공식 oracle·비용·최종 CI는 미완이다. [범위·미완](reports/2026-10-25-provider-base-update-first.md).

## 2026-10-25 — tracking P→L prefix(424, 부분)

- 기존 SER/capture/kernel/SH OFF를 보존했다. 직접25·정본oracle1·기존 client4와 별도 ASGI1(503→새요청200→재요청200)·fresh triple7을 검증했다. 공유 cutover DB의 통합11 원실패(9 PASS/2 FAIL)는 보존·합산하지 않는다. 정확 CI·운영·whole snapshot은 미완이다. [범위·근거](reports/2026-10-25-tracking-protocol-prefix.md).
## 2026-10-25 — 첫 동시 수집 후보 설계(미구현)

- 공항15·휴게소215를 읽기 전용으로 확인하고 기존 fetch/Geo 차이를 반영한 [구현 순서](reports/2026-10-25-transport-small-native-pair-design.md)를 정리했다. 전체 크기·적격성·실제 두 worker·복구·운영은 미완, T-CWRITE-04/06/07 체크는 유지한다.

## 2026-10-25 — EX context 단일 조회(423)

- 기존 검증·권한을 보존하고 실제9 PASS, 별도 공식 oracle1 PASS/ACL보존, schema423 API startup1 PASS/고정GET3을 확인했다. 초기 감사 실패는 보존한다. 함수A/B6회는 뚜렷한 전체 CPU 개선을 입증하지 못했다. 최종 정확CI·collector/운영은 미완이다. [근거·한계](reports/2026-10-25-exclusive-context-single-select.md).

## 2026-10-25 — scalar batch 내부 실행 단계 분리

- 기존 begin/manifest 검증/항목 적용/finish를 구체 private 함수로 나누고 실행 AST·SQL·공개 계약·전체30초·완료 조기반환을 보존했다. 두 소스 리뷰와 기존 실제 PG20 PASS/23.57초·정확 정리를 확인했다.
- main1395/1397 문서를 통합했다. 초기 CI의 부모 tasks04 길이 실패를 보존하며 새 정확 CI는 별도다. collector/coordinator·운영 변경0. [범위와 증명](reports/2026-10-25-scoped-provider-batch-phases.md).

## 2026-10-25 — 전체 snapshot 동시 쓰기·복구 설계(미구현)

전체 입력·capture·동일 run 복구의 남은 문턱을 [설계](reports/2026-10-25-full-snapshot-coordination-design.md)에 정리했다. 작은 비용과 [schema422 API startup](reports/2026-10-25-schema422-api-startup-observation.md)은 별도 관측했으며, 실제 SH collector·운영 동시 쓰기·후속 전파는 미완이다.

## 2026-10-25 — Heritage bounded evidence reader 입력 계약(부분)

- 422 source 두 리뷰 뒤 SDK/권한/입력/snapshot20 PASS(15.11초)와 별도 새raw부정3 PASS(14.29초), 공식 fresh oracle1 PASS(14.68초)를 확인했다. 초기 실패는 보존하며 단일최종23 실행으로 세지 않는다. 추가 의미부정·메모리/비용·schema API startup/SH 운영은 미완이다. [근거·범위](reports/2026-10-25-heritage-bounded-evidence-reader.md).


## 2026-10-25 — SH 운영 후보 크기 실측

- 국가유산/세계음식점 current head와 active primary place가 각각4,279/9,494로 기존 SH 한도를 넘음을 읽기 전용으로 확인했다. 작은 조회·시험을 운영 전체 동시성으로 세지 않는다. [실측·후속 범위](reports/2026-10-25-sh-operating-scope-measurement.md).
- 문서만 변경하며 정책·상한·운영 활성화0, T-CWRITE-04는 미완이다.

## 2026-10-25 — Geo stamp SQL writer 권한 경계(421)

- 일반 runtime raw stamp 쓰기를 회수하고 EX/SH 전용 SD와 SI 진입 검증·기존 active full-context/정렬 잠금을 유지했다. 실제 SH collector 배선/운영 활성화는0이다.
- 장수 backend 비용 회귀와 실패 원본을 보존하고 UPSERT 한 문장만 계획하는 후보를 검증 중이다. 집중115·lint373/기존6skip·문서4 통과, 최종 비용·정확 CI/UI는 별도 수용이며 [구현·제한](reports/2026-10-25-stamp-writer-boundary.md)에 정산한다.

## 2026-10-25 — 실제 SH 수집 연결의 설계 초안(A4)

- Heritage 이름 변경과 MCST 동일 key 반복 입력의 최소 범위를 나누고 현재 normalizer/Geo stamp·dataset retire0·full capture/후속 receipt를 필수 조건으로 정리했다.
- 실제 두 dataset DML 중첩·worker 복구/Geo pool은 별도 수용이며 구현/정책/운영 변경0, 전체 T 체크는 미완이다. [설계와 필수 반례](reports/2026-10-25-sh-collector-integration-design.md).

## 2026-10-25 — main 419 보존과 EX 적재 연결 420 재검증

- 머지 직전 main에 들어온 PG transport 퇴역419를 보존하고 미머지 EX 적재 연결만420으로 재배치했다. DDL sidecar 본문과 main 비중복33파일·journal/resume 원문 suffix를 보존했다.
- 새 합집합 집중199 PASS/155.27초·lint373 PASS/기존6skip·CI 대상 Ruff/mypy5/import4 통과. 원419 세대의 CI/UI를 새420 결과로 세지 않으며, 새 정확CI·두리뷰·fresh UI는 별도다. [근거와 경계](reports/2026-10-24-exclusive-provider-full-refresh.md#main-419-병합-뒤-420-재검증).

## 2026-10-24 — 제한 primary place의 명시 EX 전체 적재(A3 checkpoint)

- 최종 converter 입력에서 bounded plan을 만드는 opt-in client/EX 경로를 추가했다. 기존 applying EX manifest·비활성 base/Geo와 활성 winner를 같은 TX로 닫고 기본 선택은 OFF다.
- 최종 집중190건(140+중복 없는 converter50)·oracle/metadata2·lint377/기존6skip·mypy5/import4 통과. 실제 SDK/asset tracking은 격리 시험이며 실제 worker/운영 수집은 아니다. 최종 두리뷰·정확CI·fresh UI는 별도다. [범위와 남은 gate](reports/2026-10-24-exclusive-provider-full-refresh.md).

## 2026-10-24 — ADR-114 결정 7 퇴역 1단계(T-STATE-03): 브랜치 `feat/adr114-retire-pg-transport`

- 소비자 확인(읽기 전용 실측): prod Map transport 출처 Feature 26,293건(주유소 place 11,820·유가 11,822·휴게소 215·휴게소 유가
  219·돌발 2,202·공항 15), 병합·curation·override·POI 링크 0. Valkey 다섯 데이터셋 `loaded`·fresh. PinVi main `ff64b65`은 교통
  레이어를 Map service REST로만 읽지만 일반 in-bounds 기본 kind(`place·event·notice·price`)·검색·근처가 PG transport를 여전히
  돌려받는다(교통 레이어와 중복, 장소 이름 검색은 PG에만 있다). PinVi DB의 Map feature 참조는 전체 0행. C7 운영 게이트가 공항
  job을 안전 대상으로 쓴다.
- 그래서 세 단계로 나눴다(ADR-114 "결정 7 이행"): ① 유가 둘·돌발 하나의 PG 적재 코드 제거 + migration `419`(operation 종류
  불문 끔, Feature `system` 퇴역 = `retired`·`suppressed` + 재활성화 막는 lifecycle override, dataset·lineage·가격 fact는 남김,
  queued/running·공유 primary·기존 lifecycle override preflight) → ② 장소 셋 → ③ 물리 삭제. 장소 적재는 계속 돈다.
- API 표면 변화 없음(OpenAPI 재생성·PinVi 재vendor 불필요). Codex 수집 fence·shadow 원장 코드는 읽기만 했다(퇴역 프로시저는
  advisory lock을 잡지 않는다).
- 검사(n150 일회용 python:3.13): ruff·mypy --strict(279)·lint-imports 초록, unit+lint+api 4,817 passed·29 failed(기준선 환경
  실패 그대로 — docker runtime 23·sealed tree 2·tick window 3·smoke settings 1), 통합(transport·retire·notice·price·mois·
  tvn34c/35·phase2·catalog 등 -k) 290 passed(1 error는 컨테이너에 docker CLI 없음). 첫 실행에서 revision id 40자(>32)와 사후
  조건 SQL의 없는 열(`context`)을 잡아 고쳤다.
- 적대 리뷰 2회(HIGH 1·MED 2·LOW 3·운영 1) 반영: (F1) prod 409→411(현 417)이 한 트랜잭션이면 410 FK 잠금을 퇴역 내내 쥔다 →
  `alembic_version` xmin으로 같은 트랜잭션을 감지해 퇴역 대상이 있을 때 거부, runbook A·B. (F2) 대상 scope 행 `FOR UPDATE`(FK
  KEY SHARE와 충돌) 뒤 preflight, operation 먼저 끔, 사후 in-flight 재확인. (F3) scope 잠금 5초·DDL 1초·퇴역 statement_timeout 0.
  (F4) 공유 출처 검사 역할 무관. (F5) 대상 셋 고정·옛 provider 잔여 fail closed. (F6) 상태 문맥 GUC 정리·docstring. 문서 drift 넷.
- 재리뷰(fix-delta): F2의 scope 행 `FOR UPDATE`는 경주를 닫지 못한다 — BEFORE INSERT 활성 가드가 plain SELECT로 `is_enabled`를
  읽고 FK 대기는 그 뒤라, 411 도중 들어온 INSERT가 켜진 값을 보고 통과해 commit 뒤 성공한다. member 표 둘을 `SHARE`로 잠그도록
  바꿨다(INSERT가 문장 시작에서 기다리고 commit 뒤 가드가 거부). 퇴역 루프 lock_timeout 60초. 두 연결 순서 강제 통합 검사(도중
  INSERT 거부) 추가. runbook B1 upsert 예시·B5 사후 member 0 확인·A 건너뜀 crash-loop 복구.
- main 병합(#1379·#1383·#1385 — ADR-115 revision 411~416): 이 migration을 `417_retire_pg_transport_values`(down 416)로 다시
  번호 매겼다. 415부터 `transition_feature_state`가 scoped write 프로토콜 gate를 배타로 잡으므로 417은 그 gate를 member 표 잠금보다
  **먼저** 잡는다(교착 회피, 돌고 있는 쓰기가 있으면 30초에 실패). runbook A는 head 416 pair, 3a 큐 sensor 정지 명령(공용 daemon)·
  417 창 새 run 실패/503 안내. 경주 검사는 inserter의 미허가 RowExclusiveLock이 `ops.import_job_datasets`에 있음을 잰다.
- main 병합 뒤 journal이 220 KiB를 넘어(228,797 bytes) 가장 오래된 2026-10-01 기록을
  아카이브로 옮겼다(tasks-rule §8 — 섹션 본문 바이트 보존, 상대 링크 없음). diff3 base 마커 줄 셋도 지웠다. (main이 2026-09-30분을 `journal-2026-09h.md`, 가장 오래된 2026-10-01 한 절을 `journal-2026-10a.md`로 따로 옮겨 그것을 따랐고, 남은 2026-10-01 두 절을 `journal-2026-10b.md`로 옮겼다.)
- 두 번째 main 병합(#1386·#1387 — ADR-115 `417_protocol_ex_reentry`): 이 migration을 `418_retire_pg_transport_values`(down
  417)로 다시 번호 매겼다(당시 runbook A는 head 417 pair).
- 세 번째 main 병합(#1388 — ADR-115 `418_creation_protocol`): 이 migration을 `419_retire_pg_transport_values`(down 418)로 다시
  번호 매겼다. runbook A는 head 418 pair.

## 2026-10-24 — 한 sealed attempt의 scalar 원자 batch(A2)

- 같은 dataset의 기존 primary place 여러 개를 한 TX/finish1회로 적용하는 별도 entry를 추가했다. snapshot seal·실제 collector 배선·same-dataset 병렬 수용은 아니다.
- 최종146 PASS(새PG20/unit10+부모116)·lint377(기존6skip)/Ruff/mypy2/import4 통과, 두 코드리뷰·정확CI·실UI는 미완이다. 총1MiB/manifest8192·협력적30s/입력독점소유 계약과 한계는 [A2 보고서](reports/2026-10-24-native-scalar-batch.md)에 있다. 기본OFF/seed0/운영0.

## 2026-10-24 — 국가유산 native 적격성 선행 계약(A1, #1390)

- 안정 composite ID의 본체 이름 presence와 저장 typed projection 재정규화·지원 외 불변 진단을 추가했다. eligible은 DB 적용 승인이 아니며 collector/Geo/whole-TX seal·정책은 바꾸지 않는다.
- 격리된 고정SDK public 모델·Map fetcher service fixture 포함98 PASS, native 예산 후속075 합집합116 PASS(실PG 포함), mypy3/import4/Ruff 통과. 정확CI·독립2리뷰는 진행 중이며 PG/실UI/운영 수용으로 세지 않는다. [범위와 실패](reports/2026-10-24-heritage-native-eligibility.md).
- 기존 EX 진입은 별도 #1389이며 부모 합성 시 양쪽 기록을 보존한다. 기본OFF/seed0/운영0, 내구 artifact/full bundle/실제 collector 배선은 후속이다.

- EX 부모 합성으로 journal225349B가 되어 가장 오래된 2026-10-01 한 절5764B를 [아카이브](archive/journal-2026-10a.md)로 원문 이동했다. 원문 SHA/부모 합집합은 A1 보고서에 기록했다.

## 2026-10-24 — 제한 scalar의 같은 의미 EX 실행 진입

- SH와 같은 source/head→후보→winner→receipt를 기존 protocol EX·curation 전역 fence 아래 수행하는 별도 내부 entry를 추가했다. legacy loader fallback·collector 배선·정책 활성화는 아니다.
- 실제PG/기존native/artifact16 PASS(28.51초): SH/EX 결과 동등·정확 gate 대기·실패/취소 rollback·55P03 복구·완료 replay0DML·mode 대체 거부. 적대리뷰 P2의 legacy장기hint를 소비해 짧은상한을 유지했다. 최종두리뷰·정확CI·최신UI는 후속이다. [범위와 증거](reports/2026-10-24-scalar-exclusive-semantic-entry.md).
- 선행 #1386·#1387은 각각 두리뷰·정확CI5개·실UI5/18(별도HTTP2) 뒤 main에 머지됐다. 기본OFF/seed0/운영0, 전체수집전환·후속전파는 미완이다.

## 2026-10-24 — 생성 SQL의 protocol-first 진입과 승인 복구(418)

- core/provider/manual/요청승인4개를 첫EX로 보강하고 내부owner2개에 함수EXEC만 추가한다. 승인55P03은 기존503/RetryAfter5로 전달한다.
- 실제PG/ASGI·기존M01/M04·unit/graph/docs 집중51 PASS, 별도 이전mapper500→수정503/동일key복구를 확인했다. [범위·실패·검증](reports/2026-10-24-creation-protocol-entry.md).
- 제품J/W·경계시험root/W 검토PASS. 정확CI·최신418 실UI·전체수집전환/후속전파는 미완이다. 기본OFF/seed0/운영0.

## 2026-10-24 — protocol EX 재진입 비용 개선(417)

- 이미 보유한 EX는 xact 소유를 재확보한 뒤 반복 설정 조회를 생략한다. session/xact·savepoint·NULL/SH 승격·timeout 계약은 유지한다.
- 실제PG7+unit4=11·oracle/metadata4·graph18·lint373 PASS(기존6skip). 합성1000회 wall 중앙값584.55→24.95ms이며 운영 CPU 개선율은 아니다.
- 선행 #1379·#1383은 각각 최신CI/실UI16·18 통과 뒤 main에 머지됐다. #1385는 실UI18+별도HTTP2 PASS/정확CI 대기, #1386은 두리뷰 PASS/CI·수집UI 대기다.
- 이번417의 독립2코드리뷰 PASS. 정확CI·실UI와 생성SQL·전체수집전환·후속전파는 미완이다. 기본OFF/seed0/운영0. [범위·실측](reports/2026-10-24-protocol-ex-reentry.md).

## 2026-10-24 — 큐레이션 import의 protocol-first 진입

- 실제 whole M03 import와 direct manual의 역순40P01을 재현하고 normal-head 첫 advisory 전 protocol EX만 추가했다. h35/다른2caller·DDL·권한은 유지한다.
- 최종PG9+기존curation/merge48·관련unit76·lint377 PASS(기존6skip). 두 리뷰·정확CI는 대기이며 기본OFF/seed0/운영0이다. [범위·실패·증거](reports/2026-10-24-curation-import-protocol-entry.md).
- tasks-rule §8에 따라 가장 오래된09-30 한 절3480B를09h로 원문 보존해 분리했다. 옛DB 전체 replay·전체 writer 활성화는 미완이다.

## 2026-10-24 — field override 진입 보강(416)

- SQL author/revoke·patch/create를 조기EX로 맞추고 manualcreate55P03을 기존503/RetryAfter5로 반환한다.
- 실제 PG/ASGI29+순수5=34·unit110·oracle/metadata2·lint373 PASS(기존6skip). native Python helper·수집배선은 제외다.
- 두 코드리뷰 PASS, 정확CI·실UI는 대기다. 기본OFF·seed0·운영0. [실패·범위·검증](reports/2026-10-24-field-override-protocol-entry.md).

## 2026-10-24 — 파일 레지스트리의 백업 링크 복구

- 실제 통합 UI에서 파일 상세의 백업 링크가 없는 상세 route를 prefetch해404를 냈다. 백업 목록 페이지로 연결하고 중첩·공백 파일 경로의 회귀를 추가했다. DB·DTO·프론트·수집/잠금 변경0이다.
- 수정 전 회귀1 FAIL을 보존했고 수정 뒤 router9 PASS·Ruff·strict mypy1·문서 redaction PASS다. 독립2리뷰·정확 CI·최종 실제 UI는 후속 수용이며 기존16case별 PASS를 전체 성공으로 세지 않는다. [원인·범위](reports/2026-10-24-backup-file-link.md).

## 2026-10-24 — state/lifecycle SQL first-entry 폐포(415)

- admin/reactivate/core/lifecycle author·revoke5개를 함께 protocol-first로 보강하며 원래 서명·본문·owner/ACL을 보존한다. Python 업무·field override·identity·정책 seed/운영 변경0이다.
- 실제 PG36+unit5 총41 PASS(16.63초), valid nested state·M05 non-kept·기존 provider retire·SH 거부/rollback·active-policy 거부·닫힌 ACL을 확인했다. 초기 seed 준비 실패는 별도 보존했다.
- 공식 oracle 기록1skip과 별도 비교/metadata2 PASS·전체 lint373 PASS/기존6skip을 구분했다. 독립2리뷰·정확 CI/UI는 미완이며 전체 동시 쓰기 완료가 아니다. [범위·실패·증거](reports/2026-10-24-state-lifecycle-protocol-entry.md).

## 2026-10-24 — 통합 전체 CI의 시험 격리 보완(#1379)

- b460의 두 실제 PG lane는 같은5건 실패였다. 4건의 새 읽기 세션 fixture 누락과 metrics의 앞선 committed행 미고려를 제품 변경 없이 고쳤다. 0/2 sibling 제어군으로기존실패를 재현하고 old/new snapshot·writer commit 단언을 보존했다.
- test-only c5b635363의 실제 PG/ASGI48 PASS(120.45초), 제품/DDL0diff·Ruff/redaction PASS다. 원본 glibc1425/12skip/5FAIL·alpine1419/18skip/5FAIL 및 수정전 제어군 로그를 보존했다. 새 정확 전체 CI·실제 UI·머지는 미완, 기본OFF/seed0/운영0 유지. [원인·수정·제약](reports/2026-10-24-scoped-concurrent-write-integration.md).

## 2026-10-24 — ADR115 구현 합집합 수용(#1379)

- 10개 검토된 구현 부모를 제품 고정점 `ebb62ccb8`로 합쳤다. 유일한 제품 합성은 승인 native 전체에 승인 phone 첫 gate2줄뿐이며 나머지 제품은 승인 부모 blob과 동일하다. 공통 문서의 양쪽 전체 항목도 보존했다.
- 최종 집중175 PASS·공식 oracle/metadata2 PASS·lint373 PASS/기존skip6·Ruff/strict mypy/import4계약 PASS, 독립 교차 리뷰2 PASS. 실제 SIGKILL 복구(#1378)와 M05 old40P01 재현·414 보강(#1381)을 예외 rollback과 구분했다. task 안내 길이 실패는 원인을 고쳐 재검증하고 원본을 보존했다.
- main 정확 CI·최신 실제 HTTP/UI·머지/운영 수용은 미완이다. 기본 OFF·seed0·운영0, 전체 T/collector·Geo/지역/identity·Weather/Transport 전파 및 취소된 export 운영 활성화 재개 없음. [통합 증거·제약](reports/2026-10-24-scoped-concurrent-write-integration.md).

## 2026-10-24 — M05 중복 후보·판정의 protocol-first 보강(414)

- 실제 기존 M05 CALL과 scoped begin의 Feature/head 역순에서 40P01을 재현했다. 414는 후보 기록·판정 public v2/private inner의 첫 BEGIN에 EX만 추가하고 본문·서명·ACL은 보존한다. 기존 내부 owner EXEC만 정본에 더하며 새 공개 권한·정책 활성화는 없다.
- 수정 후 실제 PG8개·순수4개 총12 passed/14.23초, 전체 lint373 passed·기존 skip6, 공식 실제 oracle 재비교+metadata2 passed다. 초기 관측 PID/진단 시간 실패는 분리 보존했다. [재현·상한·범위](reports/2026-10-24-manual-dedup-protocol-entry.md).
- 기본 OFF/정책 seed0/운영 활성화0이며 컨트롤러를 둔 소규모 정확성 시험이다. 전체 writer 전환·Geo·대량/운영 ARM 성능·Weather/Transport 전파·최종 두 리뷰/정확 CI/UI 수용은 미완이다.

## 2026-10-24 — ADR115 제한 native scalar 비용 실측(#1376)

- schema412의 로컬 amd64·2CPU/1536MiB 격리 환경에서 고정 2dataset·2record를 직렬/병렬2 각각 fresh clone 3회로 측정했다. 중앙값 elapsed는 **273.81→158.42ms**였지만 **PG CPU는 +4.2%**여서 CPU 감소를 입증하지 못했다. 전체 수집·운영 ARM·대량/공유 Feature 성능으로 일반화하지 않는다.
- 별도 정확성 probe에서 두 실제 source DML의 미커밋 중첩 79.23ms를 확인했다. 이 강제 barrier는 성능 6회에서 제외했고, 결과/lineage/완료 receipt hash는 모두 같았다. 자체 container의 정확 생성 ID 정리를 확인했으며 운영·provider 호출은 0건이다.
- 실측 source는 `4c9916d0b90406a0613ca8b41434260b6ec85696`의 `tracked_clean=true`이고, 현재 runner SHA256 `64cd3944e648a2be957aee01aec78a3bb845f8585b80770b740e44122d154fc9`와 같다. 원시 JSON SHA256 `f3f33144390854288657d47209dada2c5c5f6092dd4b7fc1b1dad61d2dbd236f`와 로그는 별도 로컬 감사 보관소에 동일 bytes로 보존했다.
- 두 독립 source 리뷰를 통과했으나 정확 CI·전체 T-CWRITE 수용은 별도다. 최신 부모 대비 제품 소스 변경 0, 기본 OFF·정책 seed0·운영0을 유지한다. 후속 413 수용·전체 SQL writer 전환·일반 수집 배선·API p95·Weather/Transport 전파는 이 측정의 완료 범위가 아니다. [수치·실패·제약](reports/2026-10-24-scoped-native-scalar-measurement.md).

## 2026-10-24 — ADR115 구현과 전체 수용 범위 구분

- #1371~#1377의 커널·reader·제한 winner/native·비용·직접 SQL 보강과 증거를 [수용 현황](reports/2026-10-24-scoped-concurrent-write-acceptance-status.md)에 정리했다. 정확 CI가 진행 중이거나 feature base에서 아직 발행되지 않은 PR은 green/머지 완료로 세지 않는다.
- 제한 병렬2의 elapsed 개선과 PG CPU 약4.2% 증가를 분리했다. 예외 rollback을 실제 worker 사망으로 세지 않으며 SIGKILL 검증은 별도다. 모든 T-CWRITE 전체 수용·운영 활성화·Weather/Transport 전파는 미완, 취소된 export 운영 활성화/Map 연동 검증도 재개하지 않는다.

## 2026-10-24 — ADR115 SQL 직접 진입 413 실제 검증

- 기존 SQL 7개의 첫 protocol EX 진입을 원문 signature·본문 SHA-256, 원래 owner/ACL과 함께 검증했다. 공유→배타 승격 거부·실제 두 세션 차단 PID·옛 전역 fence 선점 방지를 포함한 단위/PG/전체 lint **407 PASS/6 기존 skip**, 공식 head oracle·metadata **2 PASS**다.
- receipt 정적 검사에서 드러난 동적 문자열 문제를 명시 전체 head 목록으로 정리했다. 초기 실패도 기록했다. 두 독립 리뷰·정확 CI 수용 전이며 기본 OFF/seed0/운영0, 전체 writer·Geo·지역 전환과 Weather/Transport 전파는 미완이다. [증거와 범위](reports/2026-10-24-legacy-sql-protocol-entry.md).

## 2026-10-24 — ADR115 기존 SQL 직접 호출의 잠금 순서 보강 착수

- Python fence만으로 커버되지 않는 기존 SQL 7개에 첫 protocol EX 진입을 추가한다. 기존 body/owner/search_path/ACL을 유지하고 scalar OFF·seed0·운영0을 지킨다. 전체 writer 전환이 아니다.
- 실제 전체 bootstrap+기존 fence5 PASS(13.85초), 정적 역할 검사7 PASS/1 기존skip. SQL 직접 CALL/경합·head oracle·독립2리뷰/CI 수용은 진행 중이다. [범위·초기 실패·남은 검증](reports/2026-10-24-legacy-sql-protocol-entry.md).

## 2026-10-24 — ADR115 제한 native scalar 실제 DML 중첩

- 기존 primary 장소의 이름·전화만 다루는 명시 helper를 별도 추가했다. claim artifact 검증→protocol/epoch/manifest→source/head→후보/winner→finish를 같은 TX에 묶는다. 자동 수집·지역 분할·운영 활성화는 없다.
- 실제 PG에서 독립 dataset의 두 source DML 동시 미커밋 구간, 실패 rollback/같은 artifact 복구, 완료 receipt의 무 DML 재호출, 오래된 artifact 보존을 확인했다. first_seen 불변식 충돌을 수정한 뒤 native3+기존lineage1 모두 PASS(26.39초).
- 412 선행 수용·최종 두 리뷰/CI/HTTP/UI·대량/전체 writer 전환과 Weather/Transport 전파는 미완이다. [범위·실패·검증](reports/2026-10-24-scoped-native-scalar-refresh.md).

## 2026-10-24 — ADR115 제한 scalar winner·정합성 검증(#1373)

- 412는 기존 Feature/primary source의 name·phones만 명시 정책으로 투영한다. R1 값/R2 검증 head, override/revoke, 실제 순서 반전·old RR·Geo 증거 보호를 확인했다. 기본 OFF/정책 seed0/운영 활성화0이며 mixed legacy writer preflight 전 production cutover는 금지한다.
- 실제16 PG/18 unit 통과, role tuple 정산 뒤 lint369 passed·기존 skip6, 공식 head oracle 재생성 후 비교+metadata2 passed. 초기 revision 길이·ACL inventory·generated 열·fieldset 축소 실패는 수정 후 재검증했다.
- OFF 10k×7표를 411/412 fresh clone 각3회 측정해 scalar trigger0/원래 validator 동일/deferred context 동일을 확인했다. 로컬 관리자 synthetic이며 운영 ARM/실제 collector 성능 개선율이 아니다. [원본 수치·제약·실패 기록](reports/2026-10-24-provider-field-scalar-projection.md).
- 413 기존 SQL 직접 진입점의 protocol-first 보강, 전체 membership/Geo/일반 수집 전환, 두 독립 최종 리뷰·정확 CI·HTTP/UI 수용과 Weather/Transport 전파는 미완이다. 기존 API/UI 동작을 새 native 수집에 자동 연결하지 않았다.

## 2026-10-24 — ADR115 운영·관리 다중 reader 후속

- 초안 #1374는 관리·운영 GET 13개의 DB 읽기 phase를 RR로 고정한다. 외부 Dagster HTTP는 첫 DB 조회 전에 끝내며 외부 상태까지 같은 snapshot이라고 약속하지 않는다.
- reconciliation snapshot의 기존 FOR SHARE는 유지하고 이 1개 경로만 RR/read-write로 분리했다. 나머지 12개는 read-only다. 실제 readonly 제어군의 25006 오류를 재현하고, row lock 경합·응답 종료 뒤 writer 재개·pool의 기본 RC 복귀까지 검증했다.
- 최종 소스 708672f06 실제 PG/ASGI 10 passed, cache 단위 178 passed, 앞선 8 router 단위 510 passed다. 부모 #1372 기반이므로 main 재기준 뒤 CI가 필요하며 두 독립 리뷰·실제 HTTP/UI·운영 적용은 미완이다. [검증과 미완](reports/2026-10-24-api-ops-reader-snapshot-followup.md).

## 2026-10-24 — ADR115 순수 다중 조회의 snapshot 고정

- 초안 #1372는 29개 순수 다중 SELECT를 최초 데이터 조회 전 read-only REPEATABLE READ로 고정한다. 쓰기·lease·외부 HTTP와 별도 요청 페이지의 원자성을 확대하지 않는다.
- cold API key 인증 세션을 hash 조회 직후 반환해 pool size=1 재진입 timeout을 없앴다. 실제 PG/ASGI 13 passed(기존 RC 혼합 반증·RR 일관성·pool 복원·cold 인증 포함), 관련 API 198 passed다. 전체 API 1,344 passed/1 failed는 새 dependency의 테스트 override 누락을 수정한 뒤 auth 93 passed로 재검증했다.
- 소스 b8f6e677a는 독립 리뷰 2인 PASS다. 정확한 최종 문서 포함 후보의 CI·별도 실제 HTTP/UI 검증은 남아 있다. 기존 writer 잠금·운영 정책·배포 변경은 없다. [전체 reader 분류와 경계](reports/2026-10-24-api-reader-snapshot-inventory.md).

## 2026-10-24 — ADR115 범위 커널·기존 writer fence 통합

- #1371에 411 scope/epoch/owner/manifest·membership 재검증과 기존 protocol→전역 fence 순서를 연결했다. runtime 직접 테이블 쓰기는 닫고 기존 writer 배타 경로·기본 OFF를 유지한다.
- 실제 PG 커널·전체 bootstrap·metadata 56 passed/1 오라클 기록 skip, 후속 오라클 비교 포함 40 passed/1 기존 skip. 별도 legacy fence 15 passed. 초기 role/trigger 실패는 수정 후 재실행했다.
- 제한 scalar·reader는 별도 초안 #1373/#1372다. 전체 provider DML 병행·정책 seed·운영 활성화·Weather/Transport 전파는 아직 미완이다. [검증과 한계](reports/2026-10-24-scoped-concurrent-writes-implementation.md).

## 2026-10-24 — ADR115 실제 동시 쓰기 구현 착수

- 기준선 #1370은 정확 `2a53dce7c`의 CI 5개·실제 glibc/alpine·독립 리뷰 2인을 통과해 머지했다. 두 lane의 원본과 checkout/runner/fixture/ACL/12phase를 대조했다. 직렬 synthetic 기준선이며 운영 절감이나 동시 쓰기 완료가 아니다.
- 다음은 후보 완전성/winner·scope/epoch/manifest·순수 reader snapshot을 분리 구현한 뒤 실제 독립 DML 중첩과 공유 Feature·복구를 검증한다. 기존 전역 fence·기본 OFF·정책 seed0·운영0을 유지한다.
- Weather·Transport 전파는 Map의 해당 개선 수용 이후다. [순서·검증·남은 범위](reports/2026-10-24-scoped-concurrent-writes-implementation.md). T-CWRITE-01~09 전체 acceptance는 미완이다.

## 2026-10-24 — ADR-114 2단계 재리뷰 Low·main 재기반(#1365 뒤): 브랜치 `feat/adr114-valkey-weather`

- origin/main(#1365 transport T4·#1368·#1369) 위로 rebase. OpenAPI 3종·admin `types.ts`는 rebase한 트리에서 n150이 다시
  뽑았고, vnext 계약 두 파일은 main 쪽을 받은 뒤 weather 항목(revision·service added 5건)을 다시 얹고 sha를 다시 쟀다.
  문서만 손으로 합쳤다(새 항목 위, 줄머리 충돌·diff3 마커 없음).
- 재리뷰 Low: `/nearest` 예보는 후보 최대 50곳(관측·요약은 10곳 그대로 — 예보 없는 측정소 12곳이 KMA 격자보다 가까운 통합
  검사), 이미 지난 `to`/`forecast_to`는 422, 배치 id는 경로 `feature_id`·weather `location_id`와 같은 모양·길이 검사(docstring은
  "둘 다 가능"으로), `…_DAILY_SUMMARY_DAYS=1`이면 `vs_previous_day`는 언제나 null(ADR W7·설정 설명), 테스트 이름 정정.
- 검사(n150 일회용 python:3.13, origin/main `0b2dc53d0` 위): ruff·mypy --strict(279)·lint-imports·OpenAPI drift 초록, 통합
  (실제 Valkey) 34 passed, unit+lint+api 4,773 passed·24 failed(main 기준선 환경 실패 그대로 — docker runtime 23·
  `test_settings_default_values` 1), dagster 패키지 세션 905 passed.

## 2026-10-24 — ADR-114 2단계 리뷰 반영(#1367): 브랜치 `feat/adr114-valkey-weather`

- origin/main(#1358·#1359)로 rebase. 생성물(OpenAPI 3종·admin `types.ts`·vnext baseline·receipt 핀)은 rebase한 트리에서
  다시 뽑았고 문서만 손으로 합쳤다.
- 정확성 리뷰(차단 없음): 깨진 저장 값 → 부분 `unavailable`(위치 값 503과 같은 판정), `partial`을 읽는 시각으로 다시
  계산(KST 경계 `daily_slot_bounds`, 끝났어도 적재 때 partial이면 유지), partial 구간은 `vs_previous_day=null`(06:30 아침),
  429·5xx(500 포함, 503 제외) 재시도, `|`·제어 문자 location_id는 페이지 전체 계약 위반(재시도 없음 — 행만 빼면 위치가 조용히
  사라진다), 둘째 페이지 이후 422는 처음부터 한 번 재시작(두 번째는 계약 위반), roster `source_status`는 null.
- 운영·소비자 리뷰: `/nearest`는 근처 최대 10곳에서 부분마다 데이터가 있는 가장 가까운 위치(`source{feature_id, location_id,
  distance_m}`, HIGH — 가장 가까운 대기질 측정소가 KMA 예보를 가리던 문제), weather 반경 100 km(weather 전용 상수, transport
  모듈 import 제거 — #1365 충돌 회피, `bbox_search_box`만 남김), `POST /locations/batch`(50곳, weather `location_id` lookup),
  묶음 읽기는 `read_many`로 왕복 두 번, 예보 `from`·`to` 창, ETag `If-None-Match` + 304 시 `checked_at`만 기록, schedule을
  weather 공개 시각 뒤로(관측 :25·:40, 초단기 :48, 단기 하루 8회, 중기 06·07·18·19시, 외부 3시간), `/status` 오류는
  `failure_kind` 코드만, 인증 header 설정(`…_AUTH_HEADER`), ADR W6 벌 수 정정(최악 약 240 MB)·W8 토큰 위험·지속성·회전 순서·
  Manager env.
- weather ETag 확인(main `7aa7e70` `export_snapshots.py`): ETag는 `snapshot_id`를 포함하고 같은 manifest의 snapshot은 TTL
  15분 동안만 재사용된다 — 15분보다 긴 주기의 poll은 내용이 같아도 거의 매번 200이다(관측 :25→:40 같은 짧은 간격에서만
  304 기대). 비용은 주기 정렬로 줄인다.
- 검사(n150 일회용 python:3.13, origin/main `1d01ccbc2` 위 rebase): ruff·mypy --strict(279)·lint-imports·OpenAPI drift 초록,
  통합(실제 Valkey, root `filterwarnings=error` 세션) `test_valkey_{weather,transport}_state.py` 33 passed, unit+lint+api
  4,696 passed·24 failed(전부 main 기준선 환경 실패 — docker runtime 23·`test_settings_default_values` 1), dagster 패키지
  세션 905 passed. 첫 재검사에서 잡은 둘을 고쳤다: rebase가 남긴 diff3 기준 마커 줄(CHANGELOG·journal·resume),
  `POST /locations/batch`의 domain command registry 등록(`_query`, 쓰기 수 79 → 80).

## 2026-10-24 — ADR-114 2단계: weather 현재·예보·세 구간 요약 Valkey·service REST: 브랜치 `feat/adr114-valkey-weather`

- 원천 계약: weather main `7aa7e70`(W1~W5 producer 머지 완료 — #143~#164)의 OpenAPI·라우터·실제 HTTP 예시로 맞췄다.
  `GET /v1/service/exports/{locations,current,forecasts?style=,daily-summaries?days=,status}`, header `X-Admin-Token`
  (weather `KOR_TRAVEL_WEATHER_ADMIN_TOKEN`), `{items, meta}` + 서명 cursor(TTL 15분)·`snapshot_id`·`source_status`,
  503 = 완결 export 없음, 410 = snapshot 만료, 401 = 토큰. 로컬 `F:\dev\kor-travel-weather`는 `9aa0d33`(main보다 1
  커밋 뒤, 문서만 차이) — 읽기 전용 scratch clone으로 대조했다.
- live(읽기 전용): odroid weather API는 `3a0ae398`(weather128)이라 `kortravelweather_api.routers.service_exports`가 없고
  `/v1/service/exports/*`는 404다. n150 Map code-server에는 weather 주소·토큰 env가 없다(Valkey URL·transport env만 있다).
  n150 어떤 컨테이너에도 weather 관리자 토큰이 없다 — Manager가 넣어야 한다.
- 설계(ADR-114 "구현 설계 — 2단계" W0~W8): 데이터셋 7개(`weather.locations`·`current`·`forecast_{ultra_short,short,mid,
  external}`·`daily_summaries`), **값 하나 = 위치 하나**(`make_feature_id(kind="weather", category="99000000",
  bjd_code=None)`), GEO는 위치 데이터셋 하나·다른 데이터셋은 같은 id로 `HMGET`. 매 run 전량(증분 `since`·ETag 미사용),
  410은 처음부터 한 번 재시작, `source_status`(worst)·`source_collected_at`(min, 하나라도 null이면 null)을 세대 메타에
  싣는다. 지난 예보 시각은 읽을 때 뗀다. REST는 `/v1/service/weather/{locations,locations/{id},nearest,status}` — 묶음은
  데이터셋별 `status`로 부분 장애를 알리고 요약은 전날 같은 구간 대비 `vs_previous_day`를 싣는다. 메모리 추정 약 48 MB
  (교체 겹침 최대 약 100 MB, transport 포함 200 MB 미만 / 1 GB).
- ADR-105 재도입 방지 검사(`test_api_serves_no_weather.py`·admin vitest)는 `/v1/service/weather/` 접두사만 예외로 두고
  예외의 실재·폐쇄(전부 service 정책, 예외 스키마는 다른 경로에서 닿지 않음, 빼는 것이 실제로 있음)를 따로 잰다.
  Dagster 쪽 검사(카탈로그 operation·client 쓰기·KMA import)는 그대로 초록이다 — 이 job은 PG를 쓰지 않는다.
- OpenAPI: admin·service에 4 operation·스키마 18개 **추가**(기존 불변, user 불변) → PinVi `apps/api/tests/contract/
  kor-travel-map-openapi-{admin,service}.json` 재vendor 필요. admin TS 타입(`types.ts`)도 재생성했다 — main에서 1단계
  transport route가 빠진 채 drift였던 것도 함께 들어갔다(frontend CI는 main에서 이미 빨갛다 — npm audit).
- 검사(n150 일회용 python:3.13, `-c docker/constraints-dagster.txt`): ruff·mypy --strict(276 파일)·lint-imports·
  OpenAPI drift `--check` 초록. unit+lint+api+dagster 5,536 passed·24 failed — 실패는 전부 main 기준선의 환경 실패
  (`test_docker_dagster_runtime.py` 23·`test_smoke_import.py::test_settings_default_values` 1; safe.directory를 넣어
  sealed tree·tick window는 이번엔 초록). 통합(실제 Valkey 컨테이너) `test_valkey_weather_state.py`+
  `test_valkey_transport_state.py` 30 passed. 첫 통합 실행에서 테스트의 httpx 전역 patch가 API 미들웨어의
  `isinstance(…, httpx.AsyncClient)`를 깨뜨려 고쳤다(적재 op 동안만 patch). dagster 패키지 테스트를 다른 패키지
  테스트와 한 세션에 섞으면 dagster `BetaWarning`이 오류로 승격돼 정의 검사가 빨갛다 — CI처럼 패키지 세션으로 돌리면
  초록(1단계 transport 검사와 같다). admin vitest(`map-ui-has-no-weather.test.ts`)는 n150에 workspace node_modules가
  없어 돌리지 않았다 — 예외 조건만 바꿨다.

## 2026-10-24 — ADR115 T-CWRITE-01: 격리 쓰기 기준선 runner

- 고정 synthetic fixture와 전용 PostGIS container/template clone으로 native load_bundles→seal/commit의 cold/warm 3회 runner를 구현했다. CPU/RSS/WAL·실제 DML 구간/잠금 샘플·CI artifact를 남기며 전체 T01/동시 쓰기 완료로 세지 않는다.
- 첫 실제 PG에서 post-upgrade runtime ACL 조정 누락을 확인해 정본 routine/setup pool 폐기·fresh worker 최소권한 preflight/login 검증을 보완했다. GRANT 추가/owner 측정 우회 없이 두 lane을 재수용한다.
- 기존 global fence/FeatureRepo/winner/API는 변경하지 않는다. 외부 DSN·운영 접속·새 로컬 DB/container0. [범위·미완](reports/2026-10-24-scoped-write-baseline.md).

## 2026-10-24 — 공용 지도 작업면 채택 후보

Feature 지도의 종류 필터에 아이콘을 결합하고 필터·보기 탭·건수/실제 좌표·줌·상세 오버레이를 공통 컴포넌트로 소비한다. Map의 기본 종류·소스·상태 필터와 조회 동작은 보존한다.

후속 UI에서 설명은 제목의 정보 버튼, 상태 필터는 `추가 필터`로 접고 select를 176×30px로 통일했다. 지도 높이를 유지하면서 375px 지도 시작을 651.75→439.25px로 앞당겼다. 다른 화면의 기본 여백·도움말·모바일 메뉴는 유지한다.

main `0b2dc53d0`을 추가 통합하고 두 작업 기록을 양쪽 보존했다. 독립 리뷰의 상세 키보드 포커스 이탈을 수정했다: 진입 포커스·예약 프레임 취소·Escape/닫기 후 마커/지도 탭 복원, point/가격 DOM 마커 Enter·Space 활성화. WSL 타입·frontend 49파일 400건·전체 ESLint PASS. n150 Playwright 1.64.1 지도 E2E 6건(375/1440px 키보드 2건 포함) PASS, 기존 실측·GeoJSON 검증의 레이아웃/worker 계약도 유지한다. Python/API/계약은 최신 main 그대로이며 lock 변화는 없다. [정산](reports/2026-10-24-shared-map-ui.md). 다음은 통합 담당자의 CI·두 독립 재리뷰이며 자체 운영 빌드·배포는 하지 않는다.

## 2026-10-24 — 가격 추이 프록시 transport T4 정렬(T-STATE-01-T4): 브랜치 `feat/transport-fuel-price-history-t4`

- 원인: #1355 프록시는 transport T4가 확정되기 전 가정 모양(top-level `natural_key`·`generated_at`·`truncated`, 행별
  필수 `collected_at`)을 파싱하고 `product_code`·`since`·`until`로 보내 — transport는 그 질의를 무시하고 정상 응답은 모두
  `upstream_contract`가 됐다. transport 정본: origin/main `9974d25`의 `backend/app/services/export_price_history.py`·
  `docs/map-service-price-history.md`(질의 `product`/`from`/`to`/`limit` 기본 1000·최대 5000/`cursor` ≤4096, 창 기본 30일·
  최대 366일·미래 금지, 응답 `meta{generated_at, source_collected_at, source_status, item_count}`·`station_key`·`items[
  product_code, observed_at, price]`·`next_cursor`·`has_more`, cursor HMAC 서명·첫 페이지부터 15분·수집 revision 고정,
  revision 변경·만료 409, 변조/다른 필터 cursor·창 위반 422, 성공 근거 없음 503 + meta, 휴게소 이력 501, 오류는 problem+json).
- 실측(n150 Map Dagster code-server 컨테이너의 transport env로 읽기 전용 GET, odroid `<prod-host-ip>:12301`): 주유소 하나
  30일 5행(유종 5개, null 가격 3), `source_status=stale`(opinet 수집 10-21 이후 미성공 — 주유소 export 목록은 503),
  `limit=2` 두 페이지 cursor 정상(486자), 변조 cursor 422·다른 product cursor 422·미래 `to` 422·naive `from` 422·없는 키
  404·휴게소 501, gzip·weak ETag·`private, no-cache`. **Map API 컨테이너에는 transport 주소·토큰·플래그 env가 아직 없다**
  (Map service `/v1/service/transport/fuel-stations`도 503 — Valkey 미적재).
- 설계: cursor는 불투명 전달(Map이 해석·서명하지 않음), 응답 `history.has_more`·`next_cursor`(+ `meta.page` 미러),
  `truncated`=has_more 호환. 이유 enum에 `upstream_unsupported`(501)·`request_rejected`(422)·`upstream_timeout` 추가.
  (처음엔 cursor 요청의 transport 409를 200 + `reason=cursor_expired`로 했다 — 아래 리뷰 반영에서 HTTP 409로 바꿨다.) 파서는
  `station_key` 일치·`item_count`=행 수·`has_more`⇔`next_cursor`·`observed_at` 내림차순을 확인한다. 행별
  `collected_at`·`provider_updated_at`은 nullable(지금 항상 null, 응답 시각으로 채우지 않음). limit은 페이지 전체 행 수.
- OpenAPI: service·admin 재생성, vnext receipt·diff baseline 재핀(service schema_changes 1건). 관리자 `types.ts` 재생성 —
  main frontend CI가 `npm audit`(next critical)에서 먼저 멈춰 #1355의 `/v1/service/transport/*`가 types에 빠져 있었다.
  user OpenAPI·user-client 타입 불변.
- 검사(n150 일회용 python:3.13, CI 설치 레시피): openapi `--check`·ruff·mypy --strict(271 files)·lint-imports 초록.
  첫 head: unit+lint+api+dagster 5,502 passed·26 failed, Valkey 통합 28 passed + 1 Docker API ReadTimeout(재실행 통과).
  **리뷰 반영·리베이스 뒤 최종 head(`553e9f3f`)**: openapi `--check`·ruff·mypy --strict(272 files)·lint-imports 초록,
  unit+lint+api+dagster 5,524 passed·26 failed — 전부 알려진 환경 실패(docker runtime 23·sealed tree 2·smoke settings 1),
  Valkey 통합 28 passed. router 검사 80개(이 PR 추가분 포함).
- PinVi 영향(읽기만, origin/main `3e1e8bc0`): `apps/api/tests/contract/kor-travel-map-openapi-service.json`을 vendor하고
  `test_kor_travel_map_transport_contract.py::_EXPECTED_QUERY`가 price-history query를 `{product_code, since, until,
  limit}`로 핀한다 → 재vendor 시 `cursor` 추가 필요. `PRICE_HISTORY_REASONS`가 옛 6개라 새 이유는 `upstream_contract`로
  접힌다(깨지진 않음). PinVi는 `since`만 보내 30일을 기본 limit 200(이제 전체 행 수)으로 받고 `truncated`를 그대로 쓴다.
- 적대 리뷰 2회 반영(차단 없음): ① 가격은 JSON number/null·유한만(`_decimal` 공통 유한 검사, NaN 상수 거부) — 전엔
  NaN·`1e400`이 응답 직렬화로 갔다. ② transport 503 problem `meta.source_status=failed` → `upstream_no_collection`.
  ③ 보낸 `product`·`from`·`to`와 다른 행은 `upstream_contract`(보내지 않은 끝은 추측하지 않음). ④ 본문 2 MiB 상한
  (Content-Length·스트리밍)·`RecursionError`. ⑤ 소유자 승인으로 cursor 요청의 transport 409를 HTTP 409
  `TRANSPORT_PRICE_HISTORY_CURSOR_EXPIRED`로(`cursor_expired` 이유 제거; 첫 페이지는 늘 200 + 현재가). ⑥ OpenAPI에
  "unavailable·has_more=false는 끝이 아님", 다음 페이지 `product_code` 동일·`since`/`until` 생략 또는 동일(transport
  코드 확인: 창은 cursor에 고정되고 보낸 값은 같아야 하며 product는 생략도 불일치다). ⑦ 운영: Manager compose
  `kor-travel-map-api`(72ee710 1659행~)에 transport 변수 자체가 없어 compose PR이 필요하고, pair 회전 preflight
  (`_PAIR_SURFACE_PATHS`)가 PinVi 재vendor 전 회전을 거부한다 → Map 머지 → PinVi 재vendor → 회전. #1357·#1360·#1362 위로
  리베이스. 두 페이지 검사의 2쪽 행이 요청과 다른 유종(D047)이어서 새 행 검사가 빨갛게 잡았다 — 검사 자료를 고쳤다.
- 재리뷰 반영(head `58352857` 기준): F1 — httpx `aiter_bytes`는 gzip 조각을 통째로 풀어(64 KiB → 67 MB) 2 MiB 상한이
  뚫렸다 → 요청 `Accept-Encoding: identity`, `aiter_raw`로 붙이기 전 상한, gzip이 와도 출력 상한 `zlib`. N1 — 깨진·잘린
  gzip·모르는 인코딩·`DecodingError`는 `upstream_contract`. N2 — 상태 코드 먼저, 200만 전체·503만 64 KiB, 그 밖은 본문을
  읽지 않아 큰 오류 본문도 상태로(cursor 409 유지). N3 — 200의 `source_status=failed`는 계약 위반, 공개 enum `ok|stale`.
  검사 대역 함정: `httpx.Response(content=…)`는 생성 때 미리 읽혀(gzip이면 그 자리에서 풀어) `aiter_raw`가
  `StreamConsumed`를 낸다 — 원문 stream(`httpx.ByteStream`)으로 다시 싸는 `_mock`을 두었다. #1368 위로 리베이스.

## 2026-10-24 — geo 재시도에 ReadError·WriteError 추가: 브랜치 `fix/geo-retry-readerror`

- 등산로 run `18c4c1d7`(22:12Z)이 선조회 중 `GeoRequestError: transport 실패: ReadError` 한 번으로 두 시도(1h24m·37m)를 잃었다
  (keep-alive 연결이 요청 도중 끊김). #1357 일시 장애 재시도는 ReadTimeout·RemoteProtocolError만 다시 보냈다 —
  ReadError·WriteError도 적재 client(opt-in)에서 총 3회까지 다시 보낸다. 연결 수립 실패는 여전히 제외.

## 2026-10-24 — ADR115 shadow 실제 수집 연결: 명시 scope·MCST 이름

- revision+provider/dataset allowlist가 모두 있을 때만 기존 native TX 안에서 shadow를 기록한다. 실제 MCST 이름만 supplied로 선언하며 Geo/파생값/DTO null은 추측하지 않는다.
- 기본OFF/정책seed0/운영0. 기존 Feature ID/effective/전역 잠금 의미를 유지한다. [연결·실패·미완 gate](reports/2026-10-24-provider-field-shadow-hook.md).
- 실제client PG/기존MCST·대기 집중검증을 진행하며 CI/두 리뷰/HTTPUI는 별도 수용한다. 전체 membership/winner/Geo/scope 분할은 미완이다.

## 2026-10-24 — ADR115 T-CWRITE-02: 불변 정책과 shadow 후보 기반

- 전체 CI의 ORM metadata/runtime preflight 누락을 보완했다. shadow CHECK/FK/index를 metadata에 정합화하고 recorder 정확 signature만 허용한다. 정책 등록/직접 DML 차단과 경고 검사는 유지하며 실패한 테스트 engine 회수도 검증한다.

- 완결 fieldset을 원자 등록하는 불변 정책 header와 source별 typed shadow recorder/ACL을410에 추가한다. 등록은 global-first이며 RR에서 새 revision이 보이지 않으면 실패한다.
- 실제 native 수집 hook/settings는 별도 후속으로 분리했다. 공개 winner/effective/전역 잠금 범위는 유지하며 기본OFF/운영0이다. [범위·교착/RR·미완 gate](reports/2026-10-24-provider-field-shadow.md).
- 정책/전체 membership·Geo·winner 활성·scope/epoch/manifest와 최종 CI/두 리뷰·HTTP/UI 수용은 미완이다. 첫 기반 단위를 전체 동시 쓰기 완료로 세지 않는다.

## 2026-10-24 — ADR115 선행: 같은 transaction fence 재진입 SQL 절감

- 실제 root session/connection transaction·오류 stamp가 유효한 동안만 전역 fence를 재사용한다. savepoint 획득은 캐시하지 않는다. 전역 충돌 범위·병합 의미는 유지한다.
- 기존 집중27/새 실제PG10 PASS, 변경 Ruff/strict mypy PASS. [범위·실패 규약·검증 한계](reports/2026-10-24-curation-fence-reentry.md).
- T-CWRITE-01 전체 기준선 및02~09는 미완이다. 다음은 두 독립 리뷰·CI·실제 HTTP/UI 수용 후 후보/winner와 scope gate의 작은 코드 단위를 이어간다. 운영 미배포.

## 2026-10-24 — 수집 CI 선행 Next 보안 게이트 복구

- Next 및 직접 ESLint 플러그인을 최소 수정 버전 16.4.1로 pin했다. npm12 배포
  audit의 critical 1건이 0건으로 줄었다. 기존 dev moderate2/high6은 변경하지 않았다.
- 기존 정본 OpenAPI와 생성물 drift를 공식 기존 generator로 정합화했다. admin395/marker4
  단위·타입·lint·실제Sharp변환·production build PASS. 독립 리뷰/CI는 진행 중이며 운영 변경은 없다.
  상세: [검증 기록](reports/2026-10-24-next-security-gate.md).

## 2026-10-24 — 멈춤 진단 오탐 정정: 브랜치 `fix/stall-watchdog-progress`

- #1357 배포 뒤 MCST run `c0f91a7c` **성공**(12:04Z 시작, 9,634초): geo 호출 36,905건(reverse 35,852·region 1,053),
  저장값 재사용 skipped=45,930·geocoded=53,276·fallback=21. 이전 실패(6시간 상한)·멈춤 해소.
- 그러나 watchdog이 15분마다 "I/O 없이 멈춤"을 남겼다(스택은 진행 중인 prefetch task). 원인: `/proc/self/io`의
  `rchar`/`wchar`는 소켓 송수신을 세지 않는다. 수정: geo 왕복·상류 요청·SQLAlchemy 문장이 `core.activity`를 표시하고
  watchdog이 그것도 진척으로 본다. 경고는 run당 한 번. 이어서 등산로 적재 시작.

## 2026-10-24 — 여섯 프로젝트 npm 보안·버전 정합

- 이 저장소의 기존 프론트엔드/공용 테스트 399개와 타입·린트·빌드 PASS. [버전·예외·검증 범위](npm-security-alignment-2026-10-24.md).
- Popper 사전 리뷰 P1: Playwright 이미지와 세 실행 helper의 이전 digest 불일치를 수정했다. Docker FROM·버전·digest 길이·helper 동등성 회귀 검사를 보강했고 관련 55개 테스트가 통과했다. James 사전 리뷰의 추가 결함은 없었다.
- 직접/전이 npm 의존성과 잠금 파일을 갱신하고 여섯 프로젝트의 공통 버전을 맞췄다.
- 호환성 예외·미수정 상류 권고·검증 범위는 [정합 기록](npm-security-alignment-2026-10-24.md)을 따른다.
- 소스·잠금 파일 정합과 WSL 검증을 완료했다. 최종 CI·두 독립 확인·N150 후보 UI 게이트와 머지 상태는 [PR](https://github.com/digitie/kor-travel-map/pull/1368)에서 정산하며 통과 확인 전 머지하지 않는다.

## 2026-10-23 — MCST 6시간 상한·멈춤: 브랜치 `fix/mcst-geo-stall`

- prod: MCST run(06:02Z 시작)이 3.5시간 이벤트 0건. step 프로세스 생존, `/proc/<pid>/io` rchar 60초 불변, geo·DB 소켓
  대기 요청 없음, Map DB 비-idle 세션 없음, py-spy main thread는 이벤트 루프 `select`에서 idle → 소유자 승인으로 취소.
  py-spy는 coroutine 스택을 못 보여 멈춘 줄은 미규명.
- 재현(같은 code-server 컨테이너, DB 쓰기 없음): 수집 14초(13 dataset·104,301행·실패 0). 변환은 순차 역지오코딩 초당
  약 4.6건 → 6시간 초과 예상. 445초에 `/v2/regions/within-radius` 504 한 번으로 종료(odroid load 15~17, transport
  code-server 134%·공용 PG 97%·root chrome).
- 수정: 재사용 helper 선조회 동시성(기본 2), 적재 geo client 일시 장애 총 3회 재시도(opt-in, 논리 요청당 1회 계수),
  적재 step I/O 정지 900초 시 task 스택 WARNING. 적대 리뷰 2회 — 반영: watchdog이 자기 읽기로 영원히 안 울리던 결함
  (HIGH), 재시도 범위를 API까지 넓힌 것(opt-in으로 축소), 시도마다 계수(분모 부풀림), 캐시 크기, 로그 실패 격리.
  받아들인 것: 동시 geo 부하 증가·재시도 증폭(env로 1), 토큰 없는 run은 순차. 리뷰가 든 등산로 seal jsonb 천장은 #1256(ADR-099 1단계, 행별 digest)로 이미 해소.

## 2026-10-23 — geo 부하 줄이기 0단계(ADR-116, T-GEOLOAD-00): 브랜치 `feat/skip-geocode-unchanged`

- 소유자 결정(2026-10-23): ADR-108의 "payload가 같은 행은 지오코딩하지 않는다"를 비-MOIS 적재 전부로 넓힌다. prod는
  주차장 17,045 좌표에 run마다 reverse 17,638회·MCST 22~28k·등산로 약 57k를 불러 odroid geo가 ReadTimeout을 냈다.
- prod 읽기 전용 실측(공용 PG `kor_travel_map`, READ ONLY transaction): 비-MOIS dataset별 좌표 있는 active·스탬프
  `called`·현재 토큰 수, 직전 적재들 사이 payload가 바뀐 기존 행(주차장 878/17,795 ≈ 5%, 박물관 24, 축제 51, 관광지 9,
  MCST 세계음식점 8), 6자리 좌표를 나눠 쓰는 행(주차장 1,176, 국가유산 920, MCST 504), 주소 열 override 0건. MCST 13개 중
  적재된 것은 1개, 등산로는 미적재(seal 천장) — 그 dataset들은 첫 성공 적재 뒤부터 준다.
- 설계: 역지오코더는 좌표만 받아 record를 모른다 → 공통 helper가 변환을 두 번 돌린다(빈 답 pass 0으로 identity·payload
  hash·좌표 → fence 없는 조회 → 좌표 표 → 저장값/실제 geo를 섞은 pass 1 → 사후 확인). 조건은 `load_bundle`이 주소 열을
  쓰지 않을 조건과 같다(head payload hash·스탬프 `called`+현재 토큰·좌표 float8 일치·active·주소 override 없음).
- 설계 적대 리뷰 1회(HIGH 0·MED 4·LOW 6), 코드 적대 리뷰 2회(A: HIGH 0·MED 1·LOW 6, B: HIGH 0·MED 2·LOW 6) — 반영과
  받아들인 것은 ADR-116 끝 두 절. 주요 반영: 재시도 답 기억, 옛 저장 jsonb fallback, DTO key 대신 hash 비교, 안전망
  `disabled`·조회 실패 `lookup_failed` 계수, 조회 savepoint 격리, `MATERIALIZED` 입력, 재사용 뒤 현재 geo 데이터셋 재관측
  (run 도중 릴리스), helper 우회 lint.
- 검사(n150 일회용 python:3.13 컨테이너, CI 설치 레시피): ruff·lint-imports·mypy --strict(core·dagster) 초록. unit+lint+dagster
  4,174 passed — 실패 29건은 main `e9d0e53c` 기준선과 같은 환경 실패(docker runtime 23·sealed tree 2·tick window 3·
  smoke settings 1). 통합 66 passed(새 `test_geo_reuse_load_path` 8건 — 조회 술어 6·실제 client spool(연결 1개, Dagster runtime
  login)·큐 결합 client — + 기존 geo 릴리스·spool fence·스탬프·dagster ETL). 처음 돌렸을 때 통합이 빨갛던 원인은 검사 자료가
  같은 좌표를 나눠 쓴 것(저장 원문 주소가 갈려 설계대로 재사용 제외)과 bundle 비교에 생성 시각 필드가 섞인 것이었다.
- 변이 검사 17개 중 16개 빨강(술어 4·안전망·답 기억·토큰·evidence·옛 저장값·사후 확인·검증·재관측·lint). 공유 좌표 두 변이
  (M5·M6)는 처음에 초록이었다 — 사후 확인이 재시도로 덮어 결과가 같았다. 변환 횟수를 세게 고쳐 빨강. pass 1 evidence
  사후 확인(M17)은 그것을 만드는 provider가 없어 대상 검사 없음(잠재 방어).
- prod 읽기 전용 `EXPLAIN (ANALYZE, BUFFERS)`(`plan_cache_mode=force_generic_plan`, 주차장 1,000행 입력): `resolved`
  MATERIALIZED에서 출발해 features·heads·records·stamps 모두 PK 인덱스 nested loop, 재사용 질의 부분 약 80 ms.
- 원장: acceptance §T-GR-01·T-GR-02를 도구로 아카이브(체크박스 111건 보존, 216,928 → 208,855 bytes) 뒤 §T-GEOLOAD-00 추가.

## 2026-10-23 — ADR-114 1단계: transport 현재 상태 Valkey·service REST: 브랜치 `feat/adr114-valkey-transport`

- 설계: ADR-114에 "구현 설계 — 1단계"(D1~D7)를 적었다 — 데이터셋 5개, 세대 키(`ktm:state:v1:{ds}:{gen}:{meta,items,ids,geo,lookup}`)
  와 포인터(`current`·`previous`·`recent_counts`·`lock`), Lua 한 번의 compare-and-set + 개수 검사 교체, build TTL·grace TTL,
  최근 6세대 최대·절대 하한 기준 비정상 집합 거부, 세대별 신선도, service REST·가격 추이 프록시. id는
  `make_feature_id(bjd_code=None)`(VWorld 블록이 와도 바뀌지 않게).
- 설계 적대 리뷰 1회: HIGH 4(같은 id 행이 개수 검사를 영구 실패시킴, BYBOX 폭을 중심 위도로 재면 모서리 누락, 스키마 버전
  교체 뒤 옛 키 잔존, 개수 검사가 교체 밖) · MED 6 · LOW 5 — 가격 추이 플래그 제거 의견 외 전부 반영(ADR 절 끝).
- 구현: `infra/valkey_state.py`·`dto/transport_state.py`·`providers/kor_travel_transport_state.py`·Dagster
  `transport_state.py`(job·schedule 5쌍, 기본 STOPPED)·API `routers/service_transport.py`·`transport_state_service.py`.
  의존성 `redis>=7,<8`(이미지 핀 7.4.1). transport fetcher에 `on_collected_at`. 기존 PG transport 적재는 그대로.
- 코드 적대 리뷰 2회(ADR-114 "코드 리뷰" 절): 1차 HIGH 1(override 한 번으로 거부가 끝나지 않음)·MED 3·LOW 8, 2차 HIGH 0·
  MED 4·LOW 9 — 하한 추정치 실측(배포 시 acceptance) 외 전부 반영.
- OpenAPI: service·admin 재생성(user 불변), vnext `openapi-diff-v1`·`consumer-rollout-v1` receipt 재핀 — **PinVi admin·
  service 재vendor 필요**.
- 검사(n150 일회용 컨테이너, CI 세션 경계): unit·api·dagster·integration 초록(남은 실패는 main `bc5ab503` 기준선과 같은
  환경 실패 — docker runtime 23·sealed tree 2·bootstrap 19·docker ledger 2). 새 통합 검사는 Manager와 같은 digest의
  Valkey 9.0으로 돈다. 변이 검사: 핵심 가드 15개(CAS·개수 대조·PERSIST·grace·최근 최대·빈 집합·cursor 세대·NX 잠금·
  응답 유실 정리·bbox 폭·절대 하한·옛 버전만 정리·override 초기화·세대 재확인) 전부 빨강.
- Manager #544(Valkey) 머지 확인: run worker는 code-server 자식이라 URL을 상속한다. Map API에는 transport 주소·토큰이
  없어 가격 추이는 그 env 전까지 `not_configured`.
- 원장: acceptance §T-GR-05·T-GR-06을 도구로 아카이브(체크박스 100건 보존). `tasks.md`의 번호 없는 outage 보류 항목이
  T-CWRITE-09 본문으로 세어져 main CI가 빨갰다 — entry 앞으로 옮겼다.
- 배포 의존: Manager Map Valkey 서비스 PR(`feat/map-valkey`, 포트 12704, `KOR_TRAVEL_MAP_VALKEY_URL`), API에 transport
  주소·토큰, transport `price-history` export(브랜치 `feat/service-price-history`) 배포 뒤 플래그 켜기.

## 2026-10-23 — ADR-115 실제 동시 쓰기 설계·작업 원장

- 근거: main `cdd2614007a86e8627949cd1176c61eb14c0ce3e`. 단순 dataset별 advisory 교체로는
  공유 Feature·source/link 역순 잠금·root/candidate seal·과거 lock table 고갈 문제가 해결되지 않음을 반영했다.
- 문서: dataset/지역 scope와 Feature 행 충돌 분리, 결정적 provider 후보 winner, override/retire/merge,
  manifest 재검증·epoch fencing·SERIALIZABLE root·호환 gate·원자적 snapshot·롤백·실측 수용을 작성했다.
- 원장: T-CWRITE-01~09 및 각 acceptance를 등록했다. Map 코딩은 진행 중 Weather·Transport 작업 뒤다.
- 독립 적대 리뷰 반영: partial head carry-forward의 값 원문/검증 head 분리, 전체 활성 후보 복원,
  원자적 정책 활성화, 지역 누락과 전역 소실 구분, 다중 SELECT snapshot, Geo 그룹 winner/stamp
  lineage를 설계·해당 acceptance에 함께 보강했다. ADR 색인의 다음 번호를 처음 115로 맞췄고, 아래 main 동기화에서 116으로 갱신했다.
- 재리뷰 반영: 배타 fallback/flag OFF는 잠금만 전역화하며 active 후보/winner 의미를 유지한다.
  직접 base legacy writer는 DB 거부하거나 scope policy cutover를 차단하고 A winner/B fallback/OFF
  fixture를 T-CWRITE-03·04·09에 명시했다. gate만으로 의미 안전성을 주장하던 문장을 제거했다.
- main `952ceb659`(PR #1352, Valkey 설계 문서)와 merge 충돌을 해결하며 선점된 ADR-114를
  보존하고 본 설계를 ADR-115/다음 후보 116으로 변경했다. main의 기능 코드 변경은 0이며
  PG 잔존/퇴역 writer와 별도 Valkey 세대 경계를 설계·T-CWRITE-01 수용 조건에 명시했다.
  후속 main `beec86812`(#1353)의 Weather 반나절 요약 문서도 추가 merge해 보존했다.
- 검증: 문서/코드 근거·링크·원장 정합만 점검한다. 사용자 지시대로 CI를 실행하거나 기다리지 않는다.
  실제 코드·schema·서비스 변경과 성능 실측은 아직 없으며 문서 PR 완료와 구분한다.

## 2026-10-22 — T-LOAD-LOCK-WAIT 2안(ADR-113): 스트리밍 snapshot은 다 받은 뒤 짧게 쓴다: 브랜치 `fix/short-curation-lock-hold`

- 원인(1안 PR 실측): `load_feature_bundle_batches`가 transaction을 먼저 열고 stream을 당겨, 첫 batch가 잡은
  `feature-curation-write`를 나머지 fetch·역지오코딩 내내 쥐었다(주차장 run `71f21b6a` 9,141초+, 대부분 `idle in transaction`).
- 수정: stream을 DB session 없이 끝까지 받아 pickle spool(임시 파일, 메모리는 batch 하나)에 쌓고, 그 뒤 쓰기 transaction
  하나로 같은 batch·같은 순서로 쓰고 같은 transaction에서 seal을 읽는다. 받기 실패는 transaction을 열지 않는다. client 한
  곳이라 Dagster asset 8개와 큐 경로가 함께 고쳐진다. 쓰기 시간·spool 크기는 INFO 로그.
- 설계 리뷰(적대 1회): H1 쓰기 단계 근거 → 실측·로그·재적재 300초 재검토 조건, H2 `provider_run_lock` 표 오류 → 고치고
  같은 dataset 동시 실행 비용을 결정 5로 받아들임, M1 쓰기 재시도 안 함(결정 6), M2 큐 경로 executor transaction은 받는
  동안 `idle in transaction`으로 남음(결정 4·tasks 기록), M3 geo 토큰은 run 전체 관측으로 판정(단위 검사).
- 실측(n150 일회용 PostGIS, 축제 3,000건): 첫 적재 32.4건/초, 재적재 140건/초 → 주차장 1.9만 건 쓰기 약 580초(첫 적재)·
  약 135초(재적재). 그 밖 7개 dataset은 1분 안쪽.
- 검사(n150 일회용 컨테이너): 단위 7(사건 순서·실패 시 transaction 없음·빈 stream seal·geo 토큰·메모리·실 bundle 왕복·spool), 통합 2(받기가 멈춘
  동안 다른 연결이 fence를 2초 안에 잡고 그 연결이 쥐는 동안 쓰기는 기다림·seal = commit된 image seal, 큐 결합 client).
  변이(stream을 transaction 안으로 되돌림): 관련 5건 전부 빨강(통합은 다른 writer 55P03 → 대기 timeout, 큐는 fence 보유).
- 코드 리뷰(적대 2회): HIGH 없음. MED — 로그가 fence 대기까지 보유로 셌다(→ fence를 먼저 잡고 대기·보유 분리, 실패도 기록),
  쓰기가 fence 아래라는 단언이 느린 runner에서 거짓 초록일 수 있다(→ `pg_locks` 미부여 대기 확인). LOW — 메모리 주장
  weakref 검사, 실제 bundle spool 왕복, 실패를 55P03으로 드러냄, tasks 항목 길이, journal 분리.
- 문서 한도: acceptance §T-GR-04를 도구로 아카이브(체크박스 53건 보존, 214,915 → 205,558 bytes). journal 2026-09-28~29
  6건을 `archive/journal-2026-09g.md`로(본문 바이트 보존 — 옮긴 줄 블록이 아카이브에 그대로 있고 live에 없음을 스크립트로 확인).

## 2026-10-22 — T-LOAD-LOCK-WAIT 1안: 적재가 fence를 길게 기다린다: 브랜치 `fix/load-curation-lock-wait`

- 증상: n150에서 동시 적재 다섯(seoul_bookstores·krforest_arboretums·standard_tourist_attractions·krforest_dulle_trails·
  visitkorea_enrichment)이 `feature-curation-write`를 Dagster 엔진 `lock_timeout=30000` 안에 못 얻어 55P03으로 3회 재시도 끝에
  실패했다. 매 재시도가 fetch·역지오코딩(약 5분)을 다시 하고 30초 만에 죽는다.
- 1안(소유자 결정): client 적재 transaction의 **첫 fence 획득 한 문장만** `lock_timeout`을 900초(env, 0=끔)로, 필요하면
  `statement_timeout`을 +60초로, `client_connection_check_interval`을 10초로 `SET LOCAL`하고 직후 되돌린다. 늘리기만 한다.
  무장 대상은 단위 검사의 분류표가 정본이다(적재 12개 무장, 정리·관리·offline upload·MOIS CLI 11개 비무장).
- 적대 리뷰 2명: HIGH 없음. MED — FIFO 잠금 줄이라 적재가 이어 잡으면 단건 writer·root 완결의 틈이 준다(문서화),
  900초는 아래 실측 보유를 못 덮는다(문서화), 무장 범위 검사가 둘뿐(→ 분류표). LOW 반영: 실패 로그, 연결 확인, 통합 holder 회수.
- 2안 입력(읽기 전용 실측, 공용 PG `pg_locks`·Dagster event log): 07:11~ 표본에서 fence 보유자는
  `standard_parking_lots`(run `71f21b6a`) — transaction 06:06:05 시작, 80분 넘게 `idle in transaction`. 스트리밍 snapshot
  경로(`_load_snapshot_batches` → `load_feature_bundle_batches`)가 100건 batch마다 upstream fetch와 역지오코딩을 **열린
  transaction 안에서** 한다(batch 사이 공백 최대 85초, DB 쓰기는 몇 초). 같은 경로가 8개 asset. 그 동안
  `finalize_provider_curation_root`가 30초마다 fence에서 55P03. 2안은 fetch·지오코딩을 transaction 밖으로 빼고 쓰기만 짧게.
- 검사(n150 일회용 컨테이너): 새 단위·통합 초록(40초 holder: 무장 성공·끈 쪽 30초 55P03·5초 writer 5초), api 1251·dagster 826·
  관련 통합 23 초록, mypy·lint-imports 초록. 변이 검사와 unit 세션 main 대조는 PR 본문.
- 문서 한도: acceptance §T-GR-03을 아카이브로 옮겼다(도구 검산 53건 보존).
## 2026-10-22 — prod 첫 적재 실패 2건: 브랜치 `fix/highway-evidence-krheritage-address`

- prod(Map `edffdc8a`)에서 한 번도 성공하지 못한 job 둘을 고쳤다. migration·API·OpenAPI 변화 없음.
- **고속도로 돌발**(`feature_notice_transport_highway_incidents_job`, 10분): 317건 중 231건이 `reverse_geocode_failed`로
  drop되고 손실 하한(#1253)이 run을 실패시켰다. 10분 경로는 일부러 geocoder를 결선하지 않는데(#667), krex 변환이
  `admin_evidence`를 싣지 않아 validator가 "evidence 없음 + 좌표 + bjd 없음"을 reverse 실패로 봤다. mois 패턴대로
  `AdminEvidence(obs_code=reverse bjd, reverse_attempted=좌표 있고 geocoder 결선)`을 싣는다. 미시도는
  `reverse_geocode_not_attempted` warning으로 적재되고, geocoder가 결선됐는데 결과가 없으면 여전히 error다(대조군 검사).
- **국가유산 행사**(`feature_event_krheritage_events_job`): 5306/5306 `missing_address`. provider가 실제 응답 필드
  (`seqNo`·`sDate`·`sido`·`gugun` …) 대신 없는 이름을 파싱해 `sn`·`address`·`starts_on`이 전부 비었다(provider 수정은
  python-krheritage-api에서 별도 진행). Map 쪽 보완: `address`가 비면 `sido`+`gugun`을 `Address.legal`로 쓴다(좌표는
  만들지 않는다). 값은 속성(`getattr`)을 먼저, 없으면 원 payload 키를 본다 — provider bump 전후로 같은 값이 나온다.
- 자연키: 종전 fallback `title::""::""`은 같은 제목의 다른 행사를 한 feature로 접었다. 실 응답에서 `seqNo`는 회차 id가
  **아니다**(같은 응답에 `15720`이 08-29~와 10-17 두 행) — `sn` 단독이면 회차가 접힌다. 그래서 `sn::시작일::종료일`(날짜가
  없으면 `sn`)로 바꿨다 — provider 수정본의 `occurrence_key`와 같은 모양이다. `sn`·시작일도 원 payload `seqNo`·`sDate`로 보충하므로 provider bump 전후 키가 같다. 이 dataset은
  한 번도 적재된 적이 없어 계보 이전이 필요 없다.
- 적대 리뷰 2회(읽기 전용). A(고속도로): HIGH/MED 없음. LOW — 좌표 row마다 `reverse_geocode_not_attempted` warning
  finding이 10분마다 갱신된다(dedupe·stale close로 증식 없음), 돌발은 bjd 없이 적재된다(#667 설계 그대로).
  B(행사): HIGH — 상세(시작/종료일·장소·전화)가 provider 수정 전엔 비고, bump 뒤에도 raw가 같아 payload hash가
  안 바뀌므로 feature가 다시 쓰이지 않는다 → `sDate`/`eDate`/`subDesc`/`contact`/`mainImageTemp`도 같은 방식(속성 →
  원 키)으로 채웠다. MED — `(seqNo, sDate)` 유일성 미확인, provider 수정본은 `(seqNo, sDate, eDate)`로 실측 유일 →
  자연키를 `occurrence_key`와 같은 `sn::시작일::종료일`로 맞췄다. LOW — fallback 키의 place가 bump 전후 달라짐(원
  `subDesc`를 쓰게 해 해소), 세종처럼 sido·gugun 중복 결합(provider와 같은 결합이라 일관, 무해).
- provider 핀 bump: python-krheritage-api `be3a1a28` → `e1b346f7`(provider #12 머지, 0.1.1). provider는 `seqNo`를
  프로그램 id로 보고(실측 2,006행 중 1,378행 공유) `occurrence_key = {sn}::{starts_on}::{ends_on}`을 낸다. Map 자연키를
  그 정의와 글자 그대로 맞췄다 — 날짜가 비어도 `sn::::`(앞 판의 "날짜 없으면 `sn`"은 어긋났다). 표시명 fallback은
  자연키 대신 `sn`. surface manifest 재생성(event 멤버 `occurrence_key`·`sido`·`gugun` 등 추가). n150에서 핀된 실제
  provider 모델로 fixture XML을 파싱해 Map 자연키 == `occurrence_key`, `missing_address` 0을 확인했다.
- 이 엔트리로 journal이 220 KiB를 넘어(`test_every_docs_markdown_stays_within_readable_limit`) 2026-09-26~27 14건을
  `archive/journal-2026-09f.md`로 옮겼다(tasks-rule §8). 섹션 본문은 바이트 그대로(원문 부분 문자열 대조), 상대 링크 없음.

## 2026-10-21 — T-RECONCILE-RETRY 하위 단계 2: reconcile sensor 결정 1~7(ADR-112 accepted): 브랜치 `feat/reconcile-retry-alert-close`

- 소유자가 O2~O5를 권고대로 수락했다(15분·40초 예산·시계당 한 시간 1행·물러섬 없음, 표지, SUCCESS root `failed` 닫기,
  O5(i) acceptance 문구 수정·(ii) log 한 행 = 잃지 않음). 같은 날 sensor `lock_timeout` 상한을 5초로 정했다.
- 구현: Dagster page는 (a)(b)(c)일 때만 지나가고 아니면 머리 시계, tick 40초(page 20/40초, 닫기·알림 몫 6초), 트랜잭션마다
  `set_config` 서버 쪽 상한(SERIALIZABLE은 isolation 다음, 보조 트랜잭션·상태 sensor 포함), storage 1-slot, 모든 분기
  commit, `head`·`db_watch` cursor 선택 키(비면 바이트 동일), `reconcile_stalled` 한 시간 1행, CLOSABLE만 abandon(다섯
  분기 + run 없음 → NULL), `ktmctl reconcile-abandon`, sweep `client_connection_check_interval=10s`.
- kor-travel-common: 핀을 `a960bdb1` → `e746e4b8`(#42·#43)로 올리고 `call_with_deadline`(slots)·`pg_error_info`·
  `StallClock`을 거기서 쓴다. 트랜잭션 SQL·CLOSABLE·표지·cursor 키는 Map에 둔다. migration·OpenAPI 변화 없음.
- 적대 코드 리뷰 2회: A(sensor) HIGH 3 — 실패 호출이 lock_timeout까지 가면 알림이 시간 부족으로 굶음(→ 닫기·알림 몫
  6초), `db_watch` 넘기기가 같은 root로 되돌아감(→ 그 tick 실패 목록의 다음 root에게), active run의 root 가리킨 conflict를
  root 없음으로 봄. MED: 머리 `run_active`는 지나감, storage 실패가 머리 시계를 재시작, quarantine root 로그 문구,
  다중 statement 상한(문서화). B(DB/client) MED: 상태 sensor에 상한 없음(→ 20초 예산), 다중 statement 상한; LOW: gate 표지가
  sweep에서만 쓰임(→ sweep 실패 로그에 분류), 검사 보강(client 메서드별 상한 단위 검사, NULL root 재읽기), CLI 방어.
- delta 리뷰(수정분만): MED — 닫기 실패 뒤 알림이 다시 굶음(→ 머리 닫기·알림은 tick 예산, DB page 몫 13초, 닫기는
  마감 − 5초), 깨진 cursor 시계가 sensor를 영구히 세움(→ 시계만 버림). LOW — 혼자 실패하는 root가 15분마다 알림(→ 시계
  유지), CLI 연결 오류.
- 검사: 해제 조건 줄마다 단위·통합 검사. 변이 21종(22검사)이 모두 결박한 검사를 빨갛게 만들었다 — (b) 느슨하게,
  statement_timeout 제거, isolation 앞 상한, reconcile 상한 누락, lock 상한 30초, 모든 55P03을 gate로(단위·통합), 서명
  변경 시 시계 리셋, 빈 키 쓰기, tick 시작 시각, DB 목록 실패 시 commit 생략, membership 닫기, root 없음 conflict, NULL
  상태 엄격 읽기, storage가 머리 시계 리셋, active conflict, 넘기기 없음, 머리 알림 page 마감, 닫기 전체 마감, 혼자 root
  시계 버림, 깨진 시계 엄격, 상태 sensor 상한 없음(n150 일회용 컨테이너).
- **배포 영향**: Map Dagster code location·API 이미지 재배포(common 핀 변경). migration 없음, Map admin OpenAPI 변화 없음 →
  PinVi 재vendor 불필요. 되돌릴 때는 선택 키(`head`·`db_watch`)를 뺀 cursor를 `dagster sensor cursor --set`으로 먼저 쓴다.
  n150 공용 Dagster daemon은 소유자가 멈춰 둔 상태 그대로다(켜지 않았다).

## 2026-10-20 — T-RECONCILE-RETRY 하위 단계 1: 완결을 sensor 밖으로(ADR-112 결정 0-1): 브랜치 `feat/finalize-out-of-sensor`

- 소유자가 O1 권고를 수락했다(세대 0 root도 tick 6~8초, tick p99 12초). 그래서 결정 1~7보다 먼저 SUCCESS root 완결을
  sensor tick 밖으로 뺐다. O2~O5는 열려 있다.
- 자리는 별도 job `feature_operation_completion`의 sweep run이다. sensor는 SUCCESS에 ensure만 하고, 완결은 sweep이 기존
  reconcile 함수로 한다. repo·SQL·migration·API는 그대로다. "SUCCESS인데 root가 active"가 곧 완결 대기이므로 새 상태가 없다.
- 설계 적대 리뷰 1회에서 초안(root마다 run 하나, 대상 tag, 동시 상한 2, 5분 재시도)이 무너졌다. DB page만 요청하면
  Dagster page 실패가 모든 완결을 세운다(H1). 동시 상한 2는 lineage lock 대기 실패만 만든다(M1). SERIALIZABLE 경쟁은
  `blocked`가 아니라 40001이다(H2). 그래서 sweep 하나 + pool 직렬화 + success sensor 1차 요청 + DB page 15분 뒷받침으로
  줄였다. 결과가 초안보다 단순하다.
- 남는 것: 완결은 여전히 lineage lock을 쥔 채 돈다(큰 완결 동안 run 안 member 완료가 `lock_timeout`에 걸릴 수 있다).
  고칠 수 없는 root의 알림·닫기는 결정 3·4 몫이다.

## 2026-10-20 — weather 잔재 정리 2건(T-WX-NOTICE-CLOSE·T-WX-VNEXT-FREEZE): 브랜치 `chore/wx-notice-close-vnext-freeze`

- 소유자 지시("4 진행"). `close_notice_features`(client·repo)와 그 함수만 쓰던 통합 테스트 1건을 지웠다. 공유 헬퍼
  `_persist_notice_lineage_events`·`_reconcile_persisted_notice_scope`는 event-bundle 경로가 계속 쓴다.
- vNext 동결 계약은 재동결하지 않고 rev 300 당시 기록으로 둔다(ADR-105 후속 한 줄, freeze 테스트 docstring 범위 절).

## 2026-10-20 — T-RECONCILE-RETRY 설계안 ADR-112(doc-only): 브랜치 `docs/t-reconcile-retry`

- 항목 이름이 "설계"이고 #1319가 세 판의 코드에서 매번 새 구멍을 냈다. 그래서 이번에는 코드보다 설계를 먼저 냈다. 이
  PR은 ADR-112(proposed)만 싣고 코드는 바꾸지 않는다. 항목은 열린 채로 둔다. 소유자가 O1~O5를 승인한 뒤 같은 항목에서 구현한다.
- 핵심은 지나가는 규칙 하나다. Dagster watermark는 panel-only run이거나, **tick이 끝났을 때 root가 있는** run이거나,
  내구성 있는 `reconcile_abandoned` 기록을 남긴 run(닫기와 관측 오류)만 지나간다. 그 밖이면 머리에서 멈춘다. 원래 있던 DB page sweep이
  root 있는 run의 재시도 큐 노릇을 하므로 parking 표가 필요 없다.
- 멈춤은 횟수가 아니라 시계로 잰다. 머리는 cursor `head`, DB page의 실패 root 하나는 `db_watch`를 쓰고, 둘 다 처음 본 실패 시각부터 잰다.
  15분이 지나면 알리고, 닫을 수 있는 실패(class 22·23502·23514·invariant conflict)면 그때 닫는다. root 없는 머리는
  system log 한 행을 남기고 지나간다. gate 경합은 기존 message 표지로 가른다(migration 없음). tick 예산은 고정 40초이고,
  상한은 서버 쪽 `SET LOCAL statement_timeout`·`lock_timeout`으로 건다.
- 적대 리뷰 1회에서 HIGH 넷이 나왔고 모두 반영했다. client만 끊는 timeout은 서버의 완결을 멈추지 못했다. 완결은 취소
  coordinator도 부르므로 전용 SQLSTATE가 API를 깨뜨렸다. 항목별 시간 창이 방문 주기와 겹쳐 알림이 영원히 발화하지 않을
  수 있었다. `end_time` 시계가 첫 실패를 이미 15분 지난 것으로 만들었다. 결과적으로 설계가 시계 둘과 cursor 선택 키 셋으로 줄었다.
- 2차 리뷰에서 HIGH 셋이 더 나왔다. 첫째, 서버 쪽 상한이 오래 걸리는 완결을 영영 못 끝내게 한다. 그래서 **구현 전제로
  prod 완결 소요를 먼저 잰다**(결정 0, O1). 둘째, `db_watch` 슬롯 하나를 고칠 수 없는 root가 계속 잡는다. 알림을 낸 뒤
  슬롯을 넘기도록 했다. 셋째, SERIALIZABLE에서 `set_config`를 isolation 문보다 먼저 두면 25001이 난다. 순서를 고정했다.
  MED로 나온 것도 반영했다. 23514는 constraint 다섯으로 좁혔다(membership은 운영자가 dataset을 끄면 나므로 뺐다).
  관측 오류도 머리 시계를 탄다. 알림 throttle은 시계마다 둔다. 실패 횟수 예산은 없앴다.
- 리뷰가 매번 새 구멍을 낸다는 점은 #1319와 같다. 다만 이번에는 문서 단계에서 잡혔다. 구현 전에 한 번 더 적대 리뷰를 받는다.
- #1319 최종 리뷰의 L1~L4는 저장소 어디에도 내용이 적혀 있지 않아 대응 표에서 뺐다.

## 2026-10-20 — T-TEST-PLANNER-INDEX 원장 이관(doc-only)

- PR #1336(`e937b38d`, main 반영 완료)이 통합 planner flake 고정(REINDEX in test txn + 25k draft rows + lock_timeout 30s,
  20/20 n150 연속 통과)을 실었으나 `tasks.md`→`tasks-done.md` 이관이 그 PR을 못 탔다. 이번 doc-only PR이 그 이관을
  싣는다 — 코드 변경 없음, acceptance §T-TEST-PLANNER-INDEX는 그대로 둔다.

## 2026-10-19 — production MapLibre worker asset 누락 복구 (PR #1340)

- **실측 원인.** 인증된 live UI가 `/maplibre/maplibre-gl-worker.mjs`를 404 HTML로 받았다. Map 화면 코드는 worker가 없으면 GeoJSON source가 로드되지 않아 고배율 marker를 표시하지 못한다. Docker runtime stage가 `.next/standalone`과 `.next/static`만 복사하고 `public`은 누락했다.
- **수정.** frontend image에 builder의 `public`을 같은 standalone package 경로로 복사하고, live UI가 worker/shared 두 파일의 HTTP 200·JavaScript content type·비어 있지 않은 본문을 검사한다. marker 시나리오는 데이터가 있는 좌표-bearing `place`에서 실행하고, viewport 안정화는 외부 타일의 무한 `idle` 대기를 피하도록 bounded로 바꿨다.
- **검증.** `docker build -f docker/frontend.Dockerfile` 성공, 결과 이미지에서 worker 19 KB와 shared 502 KB 확인, E2E `tsc` 성공. 운영 UI 반영과 live 브라우저 검증은 PR CI 후 진행한다. Dagster를 import하는 Python unit test는 로컬 개발 환경에 Dagster가 없어 수집 단계에서 실행하지 못했으며, PR CI가 해당 게이트를 담당한다.

## 2026-10-19 MOIS 장애 격리 수용

PR1340: 실제 SYN DROP/native retry 기본값으로 FAILURE308.365초(<1440), 복구500행·재수집HTTP0 PASS. REST/prefetch/loader173검사와 namespace4검사 PASS. 운영 전체job/실DB 검증은 아니며 daemonOFF 유지. [범위와 한계](reports/2026-10-19-mois-network-drill.md).

## 2026-10-19 — MOIS 연결 실패 조기 전파

- 500행 typed 오류 선조회 지연을 재현하고 실행중 task 취소·회수를 보강했다. 관련89회귀 PASS이며 실제 네트워크/native retry 수용은 준비 중이다. [근거](reports/2026-10-19-mois-network-drill.md).

## 2026-10-19 — T-MAP-02 현재 설치 세대 수용

- T-MAP-02 — timeout 구현523d98cc가 포함된 e937b38d의 API/CS 설치3파일 hash와
  현재 image/CID/StartedAt을 확인했다. 과거 첫 generation UUID는 미회수이며
  현재 설치세대 묶음으로 수용한다. 불필요 재배포·운영 변경0.
  Map API/CS·PinVi API 실제 기존 키 reverse3/3 PASS, PinVi CS 직접 역할은 제외.
  [범위와 증거](reports/2026-10-19-installed-timeout-acceptance.md).
  전원단절 drill·자동 실행·운영 변경토큰 전량 수용은 별도다.

## 2026-10-18 — Geo 기준점 실제 UI 수용

- 실제 관리자 UI 8/8 PASS: 최초 baseline plan 1/상세 items 0, 동일 토큰 감지에서 같은 기준점 유지.
- 실행 중 세 이미지의 revision label e937b38d와 DB head 409를 관찰했다.
- daemon OFF·현재 run/물리 worker 0·컨테이너 lifecycle 유지. 실제 변경 토큰 replay/resume·자동 실행은 미검증.
- [검증 기록](reports/2026-10-18-geo-baseline-live.md). 문서만 변경하며 사용자 지시로 CI를 생략한다.

## 2026-10-17 — T-MAP-02 timeout 설명 정합(문서만): 브랜치 docs/track2-http-timeout-contract-20261017

- tasks.md의 낡은 connect 2 s를 실제 기본 4 s로 정정했다. read·write·pool 기본은 geo 10 s·transport 30 s다
  (settings.py, geocoding.geo_http_timeout, dagster/provider_fetchers.transport_http_timeout).
- transport의 요청 재시도는 upstream_retry.DEFAULT_UPSTREAM_ATTEMPTS=2·
  PROVIDER_BOUNDARY_BASE_DELAY_SECONDS=15.0 및 run 예산을 따르며, 이 숫자들은 요청 전체 deadline이 아니다.
- 구현 커밋 523d98ccf36f90aaead9ac33ab353a0839293621(#1325)은 최신 main
  e937b38d176cfeb759daca629395f51c1a6a4d5f(#1336)의 조상이다. 제품 중복 패치는 하지 않았다.
- 실제 배포·장애 drill은 수행하지 않았다. T-MAP-02는 acceptance의 첫 prod 배포 generation 근거를 확인할 때까지 열린다.

## 2026-10-17 — 통합 planner flake 결정화(T-TEST-PLANNER-INDEX): 브랜치 `fix/t-test-planner-index`

- **원인(실측).** keyset 쿼리에 같은 열의 인덱스가 둘이다 — partial `idx_features_updated_keyset`과 술어 없는 admin
  `idx_features_admin_updated_keyset`. 공개 행만 있는 seed에서 partial의 이점은 Filter 비용 하나(약 0.19)라, 인덱스 크기가
  갈리면 뒤집힌다. 크기를 가르는 것은 **LP_DEAD 비대칭**이었다 — admin 목록처럼 admin 인덱스만 훑은 쿼리가 죽은 항목에
  표시를 남기면 다음 insert가 admin 쪽에서만 자리를 다시 쓴다(n150 재현 partial 622~744 page vs admin 127 page, plan은
  CI 실패와 같은 `Index Scan using idx_features_admin_updated_keyset … Filter`).
- **고정.** 테스트 transaction 안 `REINDEX`(keyset 쌍 두 벌, 롤백) + 같은 수의 비공개 행(더 새 `updated_at`, 일부 같은
  이름) + 실패 시 plan 전문. 재시도·skip 없음. 고정을 되돌리면 같은 순서에서 2/2 빨강, 고정 판은 20회 연속 초록.

## 2026-10-16 — geo 릴리스 재지오코딩 구현 반영 문서(T-GR-07, doc-only): 브랜치 `docs/t-gr-07-geo-release-docs`

- **무엇.** ADR-109 accepted(구현 기록 표·열린 결정 13개 결론), runbook `geo-release-regeocode.md` 신규, 정본 문서의
  "ADR-109 proposed, 미구현" 표식 제거, T-GR-01~06·08 `tasks-done.md` 이관(T-GR-07은 머지가 조건).
- **문서가 코드와 달랐던 자리.** `address-geocoding.md` §5의 센서 위치(`sensors.py` → `geo_release_sensor.py`)·커서(없음 —
  기준선은 계획 표 행)·`kor_travel_geo_client` resource(만들지 않음 — `open_geo_client`)·run_key 다섯째 칸(`provider_dataset_id`
  → `position`)·상수 이름, ADR-108의 "릴리스 센서가 MOIS 이어 달리기를 대신한다"(MOIS는 이제 센서가 내지 않는다).
  geo ADR-069는 그 저장소에서 2026-10-13 accepted(GitHub 원문 확인).

## 2026-10-16 — admin UI geo 릴리스 화면(T-GR-06, ADR-109 결정 8): 브랜치 `feat/t-gr-06-geo-releases-ui`

- **무엇.** `/admin/ops/geo-releases` — 현재 geo 데이터셋(`data_token` 없음 = 빨간 상태 + 센서 Skip 사유), 계획 목록, 계획 상세
  (커버리지 게이지·항목 표·Dagster run 링크·건너뛰기·다시 계획), "지금 감지". 기존 Rail-Workbench 체계(AdminShell·SectionCard·
  DataTable·StatStrip·확인 dialog)를 그대로 쓴다. nav "수집 파이프라인"에 넣었고, nav 거울 표(`home-nav.spec`)가 그동안 빠뜨린
  `수동/provider 판정`도 같이 맞췄다.
- **MOIS 문구.** API 사유 값은 하나라 replay 미지원과 MOIS(센서 수동)를 가르지 못한다 — enum을 바꾸면 PinVi 재vendor라
  화면이 operation key로 "수동 실행 후 skip 필요"를 보인다. API 필드에는 docstring이 아니라 주석을 달았다(모델 docstring은
  OpenAPI description이 된다).
- **격리 스택 e2e.** n150에 PostGIS(배포 bootstrap → head 409)·가짜 geo(토큰 전환 제어)·실 API·prod frontend를 띄워, 기준선
  기록 → 토큰 전환 → 실제 계획 생성 → MOIS 안내 → 건너뛰기를 실 API로 돌렸다. mock 스펙은 skip·detect 1회·게이지 수치·
  no_token·replan 확인·375px 가로 넘침 0.

## 2026-10-16 — records resource replay 모드(T-GR-08, ADR-109 결정 7): 브랜치 `feat/t-gr-08-replay-mode`

- **무엇.** 쿼터 민감 records resource에 `source_mode=replay` — 저장된 current 원본을 provider 모델로 되살려 같은 변환기로
  다시 적재한다(provider HTTP 0회). `SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS`를 채워 릴리스 센서가 replay 항목을 낸다.
- **MOIS는 golden에서 떨어졌다.** MOIS `raw_data`는 payload hash 입력용 21개 필드뿐이고 변환기는 우편번호·건물관리번호·
  업종별 시설 필드 24개를 더 읽는다 — 되살린 bundle의 `facility_info`·주소가 달라진다. 결정 7의 가정대로 MOIS는 replay
  목록에서 빼고 fetch로 낸다(로컬 SQLite라 data.go.kr 쿼터 없음). acceptance의 MOIS 술어(N `not_called`·reverse 0·
  `unstamped` 0·두 번째 변환 0)는 fetch 경로 통합 테스트로 확인했다.
- **설계에 없던 것 셋.** (1) `fetched_at`만으로는 부족하다 — head 관측 입력은 `imported_at`이라 replay가 head를 전진시켜
  관측을 꾸민다. 저장된 `observed_at`을 되돌려 head 갱신 자체가 일어나지 않게 했다. (2) Dagster client는 연결 1개이고
  표준데이터 snapshot 적재는 batch stream을 한 transaction 안에서 소비한다 — 적재 중 읽으면 그 연결과 경합하므로 읽기를
  적재 전에 끝낸다(`prefetch_replay`). (3) provider 라이브러리는 CI에 없다(`providers` extra) — 실모델 golden은 설치된
  환경에서만 돌고(importorskip), CI에는 "변환기가 raw에 있는 필드만 읽는다"는 구조 golden lint를 두었다(MOIS 대조군 포함).
  런타임 backstop은 hash 불일치 시 적재 전 실패다.
- **#1333 리뷰 2인 반영.** (R2) 차단이 풀린 MOIS를 센서가 full fetch로 자동 launch하면 전국 Phase A·50만 행 변환·예정
  밖 은퇴가 일어난다 — `SENSOR_MANUAL_OPERATION_KEYS`로 막고 운영자 수동으로(사유 값 재사용, OpenAPI 불변). (R1) 빈·부분
  replay가 성공으로 끝나던 것 — 읽은 건수를 같은 술어의 active entity 수와, 변환 결과를 읽은 레코드와 대조해
  `ReplayIncomplete`. seal 영수증 `observed_at`이 replay에서도 찍히던 것 — replay는 authoritative를 주장하지 않는다
  (operation 경로 통합 테스트). "MOIS fetch는 쿼터 0"은 TTL 안에서만 참이라 문서를 고쳤다. launchable은 replay 목록에서
  파생, 복원 함수는 `REPLAY_FROM_RAW` 하나, CI dagster job에 `python-datagokr-api` 설치(public 핀)로 golden이 CI에서 돈다.
  drift 검사는 hash가 변환기 안에서 나오므로 변환 뒤 — 문서를 "commit 전 실패"로 맞췄다.

## 2026-10-16 — geo 릴리스 센서(T-GR-05, ADR-109 결정 5): 브랜치 `feat/t-gr-05-geo-release-sensor`

- **무엇.** `kor_travel_geo_release_sensor`(기본 STOPPED, 300초) — 공용 계획 함수로 감지·계획하고, 항목(run 단위)을
  하나씩 전용 job으로 낸다. 전이(완료·MOIS 이어 달리기·1회 재요청·무run 3 tick)와 완료 호출(sigungu resolver는 tick의 geo
  client). repo·client에 항목 전이 셋(`mark_item_requested`·`settle_item`·`requeue_item`).
- **판정을 새로 만들지 않았다.** 기준선·멱등·끝난 토큰·롤백 정리는 #1331 함수 그대로라, 센서 테스트는 "공용 함수의 결과를
  따르는가"만 본다. 커서도 쓰지 않는다(기준선이 DB 행).
- **원장 분리.** `tasks-acceptance.md`가 220 KiB 상한을 넘어(226,696 bytes) 닫힌 절 `T-MAP-01`·`T-GR-00-LEDGER`를
  `scripts/archive_task_ledger_section.py`로 `docs/archive/`에 옮겼다(체크박스 다중집합 검산 통과, 221,385 bytes).
- **replay 게이트가 지금은 계획 완료를 막는다.** replay 항목(MOIS·datagokr fileData·standard_data)은 T-GR-08 전까지 내지
  않으므로 그 항목이 남은 계획은 `running`으로 남는다 — Skip 사유가 막힌 항목과 이유를 말한다.

## 2026-10-16 — geo 릴리스 계획 표·계획 함수·admin API(T-GR-04, ADR-109 결정 5·8): 브랜치 `feat/t-gr-04-geo-release-plan`

- **무엇.** migration 408(계획·항목 표), `plan_geo_release`(센서·`/detect` 단일 정본), 항목 생성(core 상수 + DB 정본),
  `coverage()`, skip·replan·완료(1회 sweep → 링크 재동기화), client 래퍼, admin API 5 operation, core 상수와 Dagster 정의의
  동등 lint.
- **실측이 설계를 고친 자리.** (1) 항목 입력의 kind — 설계는 `feature_load`인데 head DB에 그 kind 행이 0건이었다(통합 DB
  덤프로 확인). job을 dataset에 결박하는 것은 `refresh`다. (2) MCST는 job 하나에 dataset 13개라 항목 13개가 run 하나를 나눠
  써야 한다 — T-GR-05 몫으로 기록. (3) prod 활성 cache target은 0개(전체 4, 전부 삭제) — 링크 재동기화의 stream 이벤트를
  지금 만들지 않은 근거. (4) 기준선은 센서 커서가 아니라 DB 행이어야 `/detect`도 같은 판단을 한다 — 상태 `baseline`.
- **적대 리뷰 2인(#1331) 반영.** 끝난 계획이 잔여를 남기면 감지마다 다시 계획해 쿼터를 사이클마다 쓰는 결함(최신 행이 이
  토큰의 `done`이면 멈춤), 롤백 시 B 계획이 활성으로 남는 결함(잔여 0 응답 전에 supersede), 옛 토큰·기준선 replan 허용,
  resolver 없는 완료가 도중에 롤백되던 것(사전 검사)을 고쳤다. 항목은 run 단위(`provider_dataset_ids`)로 바꿨다 —
  MCST 13 dataset이 항목 1개라 센서가 단순하다. replay 게이트는 메모가 아니라 core 상수와 `launch_blocked_reason`이다.
- **lint의 유도.** geo 의존을 `reverse_geocoder=`의 존재로 세면 돌발정보 notice(`=None`)가 들어오고, 함수 본문 전체의 이름을
  보면 price asset이 `deps=[place asset]` 데코레이터 때문에 geo 의존으로 잘못 잡힌다(첫 시제품에서 실제로 났다). None 상수
  제외 + 본문만 + 모듈 횡단 전이로 바꿨다.

## 2026-10-16 — 적재 경로의 geo 재해석(T-GR-03, ADR-109 결정 4·6): 브랜치 `feat/t-gr-03-stale-stamps`

- **무엇.** `load_bundle`이 `GeoLoadContext`를 받아 스탬프·stale 분기·값 동일 무쓰기·빈 답 가드·override finding을 한다.
  MOIS "그대로" 판정에 스탬프 토큰 조건, 행 evidence, 표식 토큰. concierge 토큰 신뢰 규칙·해시 제외. 비-MOIS run 빈 답 가드.
  변환 함수 단위 geo 소비 lint. T-GR-02 이월 넷(client·repo 전달, run 가드, MOIS 배선, price 스탬프 0) 포함.
- **#1327 최종 리뷰 HARD 요구 — 토큰은 지오코딩 전에.** `_load` 경로는 변환이 끝난 뒤 wrapper로 들어가 토큰을 그때 처음
  읽었다 — 전환 run이 옛 데이터를 새 토큰으로 봉인할 수 있었다. 역지오코더를 감싸 처음 불릴 때 handle을 먼저 읽게 했고
  (MOIS·concierge는 run 시작에), 응답이 다른 토큰을 내면 그 적재는 스탬프·stale 분기를 하지 않는다(이중 방어).
- **설계를 고친 자리.** run 빈 답 가드의 분자를 endpoint 빈 답에서 **행 단위 최종 빈 답**으로 — reverse가 비고 region fallback이
  채우는 산악 centroid run이 정상인데 실패할 뻔했다(테스트로 결박). concierge `current_data_token=None`은 acceptance대로 종전
  동작(설계 §4 문구와 모순). 해시 자체 계산은 payload에 토큰이 있을 때만(롤아웃이 전 행을 흔들지 않게). override 테스트에서
  `core.address` jsonb에도 코드가 들어 있어 열 하나의 override로는 "값 동일"이 되지 않는다는 것을 확인했다(문서화).
- **2차 적대 리뷰(같은 날) 반영.** MOIS 롤아웃이 수십만 행이라 행마다 stale·저장값·스탬프를 따로 묻던 것을 chunk 단위로
  바꿨다(선읽기 두 문장 + 스탬프 한 문장; 같은 Feature가 두 번이면 두 번째는 행 단위). concierge 해시에서 최상위
  `updated_at`·`operation`도 뺐다 — producer가 토큰만 바뀌어도 `updated_at`을 새로 찍어 전 행이 매 릴리스 "바뀜"이 될
  뻔했다. stale 분기에서 같은 법정동인데 geo 전용 필드만 사라진 답은 저장값을 지킨다(`geo_partial_kept`). 빈 답 가드가
  `address` override 값을 provider base로 옮겨 적지 않게, 관측 집합이 없으면 토큰을 닫게(fail closed) 했다. 문서는
  포인터가 아니라 본문을 고쳤다(`address-geocoding.md` §4 run 가드 분자·concierge 기본, ADR-109 결정 4).
- **실측은 격리 스택에서.** n150에 별도 PostGIS 컨테이너를 띄우고 배포 bootstrap 경로로 올린 DB에서 MOIS 루프 그대로
  12,000행을 돌렸다(일괄/행 단위 번갈아 2회). 롤아웃 101~103초 대 116~117초. 첫 정상 run이 17초로 튀어 계획을 의심했지만
  EXPLAIN은 스탬프 PK 인덱스(chunk당 9ms)였고 두 번째 run부터 1.1초 — 대량 쓰기 직후 hint bit 비용이었다.
- **게이트·빨강.** 통합 23건(새 파일) + 기존 스탬프 22건. 의도적 빨강 11종을 n150에서 확인(빈 답 가드 끔·판정 집합에 legal·
  override 열 비교·토큰을 해시에·전환 관측 무시·CTE 조건 제거·표식 조건 무시·값 동일 재쓰기·concierge 신뢰 무시·토큰 선행
  제거·run 가드 분자를 endpoint로) — 각각 그 테스트만 빨갰다. 롤아웃 비용 프록시(통합 DB, 300행): 첫 적재 8.31 s, geo 없는
  재적재 2.40 s, 스탬프 롤아웃 재적재 2.04 s(값 동일 무쓰기 300·스탬프 300) — 행당 추가 비용은 잡음 수준.

## 2026-10-16 — `docker-buildx.sh`의 `$!` 경주(고아 tar writer): 브랜치 `fix/buildx-archive-pid-race`

- **무엇이었나.** `test_buildx_cleans_partial_archive_when_materialization_is_terminated`가 n150에서 멈췄다 — 테스트의
  가짜 `git archive`(무한 루프)가 고아로 남아 97% CPU로 2시간 49분 돌았다. **flake가 아니라 경주다.**
  `git archive … &`가 fork된 직후 `archive_pid="$!"`가 실행되기 전에 TERM이 오면 trap이 먼저 돌고, 그때 변수가 비어
  있어 정리가 writer를 죽이지 못한다. 부하가 큰 n150에서만 그 창이 열렸다. #1325~#1327 PR 본문에서 이 실패를
  "n150 부하성 flake"로 부른 것은 틀렸다(각 PR에 정정 코멘트). 같은 실행에서 함께 실패한
  `test_lifecycle_preserves_signal_exit_status[INT-130]`은 다른 원인이다 — 하네스를 `nohup … &`로 띄워 SIGINT가
  ignored-at-entry로 상속됐고 bash는 그 신호를 다시 trap하지 못한다(이 저널의 기존 "환경 실패" 판정이 맞다).
- **고친 것.** 정리는 `$!`를 담은 변수가 아니라 bash job 표(`jobs -p`)로 writer를 찾는다 — job 표는 fork와 같은
  명령 안에서 채워지고 trap은 명령 사이에서만 돌므로 창이 없다. 테스트의 가짜 writer는 부모가 사라지거나 30초가
  지나면 스스로 끝나고, 그렇게 끝났으면(아무도 죽이지 않았으면) 표식을 남겨 테스트가 **고아였음**을 단언한다.
  `pytest-timeout`을 dev 의존성에 더하고 두 테스트에 `timeout(60)`을 건다.
- **결정적 재현.** 스크립트 사본에서 fork 줄 바로 뒤에 `kill -TERM $$`를 넣어 경주 창을 매번 연다
  (`test_buildx_reaps_the_writer_even_when_term_lands_before_the_pid_is_recorded`). 옛 정리로 돌리면 빨갛다.

## 2026-10-16 — run-scoped geo 현재 토큰 resource·`geo_applied` 배선(T-GR-02): 브랜치 `feat/t-gr-02-geo-dataset-resource`

- **무엇.** 팩토리 `fetch_current_dataset`(geocoding — CLI가 dagster를 import할 수 없어 여기), Dagster resource
  `kor_travel_geo_dataset`(asset·큐 runner 공통 키), offline upload·CLI의 같은 팩토리 호출, asset 21곳 + MCST 1곳의
  `geo_applied` 리터럴과 적재 wrapper 메타(`geo_*`, 불일치 WARNING 1건). 적재·스탬프 동작은 바뀌지 않는다.
- **범위를 자른 자리.** client·infra 적재 함수로 `current_dataset`·`geo_applied`를 넘기는 것과 빈 답 비율 가드, MOIS 배선은
  T-GR-03이다 — 지금 넘기면 받는 쪽이 아무것도 하지 않는 인자다. acceptance의 "(T-GR-03 뒤)" 항목도 그때 판정한다.
  설계의 경량 `kor_travel_geo_client` resource는 센서(T-GR-05)가 쓸 때 더한다.
- **#1326 델타 리뷰 후속(이 PR에 함께).** `tasks-rule.md` §8의 아카이브 복구 예외에 "충돌 마커 줄 자체의 삭제"를 정식으로
  더했다(T-GR-01 journal의 '§8 복구 예외' 인용이 가리킬 조문). 마커 lint는 CRLF·CR 줄끝과 첫 줄 UTF-8 BOM을 정규화한 뒤
  보고, `=======`는 같은 파일에 시작·기준·끝 마커가 있을 때만 센다(홀로 있는 setext 제목 밑줄은 통과). CRLF·BOM 임시
  파일로 빨강을 확인했다. `address-geocoding.md` §7 e2e 행을 acceptance와 같은 "첫 tick이 기준선을 기록한 뒤"로.
- **리뷰 A·B 반영.** resource를 lazy handle(`GeoDatasetHandle.current()`, 처음 쓰일 때 1회·동시 호출 1회)로 바꿨다 —
  geo 콜러블이 없는 run(price/notice·visitkorea·MOIS)은 odroid가 꺼져도 connect 상한을 기다리지 않고, sync 초기화의 별도
  loop·무기한 `thread.join()`도 사라졌다. 경고 경로: 팩토리는 `logger=`를 받아 resource는 managed logger
  (`kortravelmap.dagster.resources`), offline upload은 `context.log`로, 불일치 경고는 wrapper가 넘기는 `context.log`로 낸다
  (모듈 logger는 `managed_python_loggers`에 없어 event stream에 닿지 않는다 — 실제 resource 경로를 돌려 managed logger가
  받는지 보는 테스트를 더했다). API key 미설정은 "base URL 미설정"이 아니라 그 원인으로 경고한다. 키 미배선 context는
  WARNING. lint는 `None`이 아닌 `reverse_geocoder=` 인자도 reverse 사용으로 센다. 실제 역지오코더의 `stats`가 wrapper까지
  가는 테스트. T-GR-03·T-GR-05 acceptance와 tasks.md에 이월 항목(client·repo 전달, run 빈 답 가드·MOIS 공유 상수, MOIS 배선,
  price 경로 스탬프 0 검사, 경량 client resource)을 적었다.
- **`test_archive_markdown_relative_links_resolve` 실패의 실제 원인.** 링크가 아니었다 — 로그의 오류는
  `PytestUnraisableExceptionWarning`(앞선 subprocess 테스트가 남긴 `Popen`·`FileIO`가 이 테스트 도중 GC되며 잡힘)이었고,
  n150 clone 두 곳의 `git status --porcelain --ignored docs/archive`는 비어 있다(낯선 아카이브 파일 없음). 격리 재실행은 초록.
- **게이트.** 단위: 팩토리 성공·지문 없음(경고 0)·전송/5xx/키 거부/계약/`available=false`/client 없음(경고 정확히 1건),
  불일치 판정 5분기. dagster: 메타 4키·불일치 WARNING 1건·현재 토큰 None이면 불일치 아님, resource가 base URL 없으면 None,
  있으면 `/v2/dataset/version` 1회. lint: run 함수의 실제 콜러블(`_reverse_geocoder(context)`·`address_resolver=`) ==
  `geo_applied` 리터럴(asset 하나를 False로 바꾸면 빨갛다), 팩토리 호출 지점 3곳·`dataset_version()` 직접 호출 0곳.

## 2026-10-15 — 지오코딩 스탬프 표·geo 데이터셋 토큰(T-GR-01, ADR-109 결정 1~3): 브랜치 `feat/t-gr-01-geocode-stamps`

- **무엇.** migration 407 `feature.feature_geocode_stamps`, DTO `DatasetRef`·`GeoApplied`·`GeoAttemptEvidence`, 스탬프 repo
  (`upsert_stamps`·`is_stale`·`select_stale_feature_ids`·`decide_outcome`), geo client `dataset_version()`·응답 `dataset` 선택
  파싱·`GeoCallStats.empty`/`observed_data_tokens`. 적재 경로 배선은 T-GR-02/03이다 — 이 PR은 아무 행도 스탬프하지 않는다.
- **현실 확인.** odroid geo는 v2 응답 최상위에 `dataset{version_token, data_token}`을 싣는다(geo #573); n150 geo는 토큰을
  가진 적이 없다. 그래서 파싱은 선택이고(없음 → None), 소유자 결정(2026-10-15)으로 '없음 → 첫 토큰'은 기준선이다 —
  ADR-109 결정 5에 기록(구현 T-GR-04/05).
- **설계와 다르게 쓴 것.** acceptance §T-GR-01 "구현 메모" 7항 — `decide_outcome`의 `legal_dong_code_present` 입력,
  `GeoAttemptEvidence`(AdminEvidence diff 0), `upsert_stamps`가 토큰 없음 = 0건을 강제, `coverage()`는 T-GR-04로,
  토큰 형식 CHECK, endpoint 단위 빈 답 계수. 407은 forward-only다 — 처음에 실제 downgrade와 왕복 테스트를
  넣었으나 `alembic/env.py`가 모든 downgrade를 해석 전에 거부해(ADR-021·102) 빨갰다. 정책을 따르고 왕복은 scratch
  DB에서 손으로 확인했다(PR 본문).
- **리뷰 반영(1·2차, main `6e1eb9ed` 위로 리베이스).** ADR-109의 자기모순(결과 "부정·비용"의 롤아웃 첫 tick 전량 계획,
  열린 결정 8)을 소유자 결정(첫 토큰 = 기준선)으로 고쳤고 커서 정의를 "계획했거나 기준선으로 기록한 토큰"으로,
  ADR-110 결정 6·단계 9의 "풀로드 → 센서 계획 1건"을 "커서가 비면 기준선·0건, 그 뒤의 풀로드만 계획"으로 고쳤다.
  `select_stale_feature_ids`에 keyset 커서 `after`(호출자가 geo 의존 dataset으로 한정 — T-GR-04), `GeoAttemptEvidence`의
  `geocode_attempted` 삭제('받았다'가 '시도했다'를 함의 — 판정에 안 쓰이는 필드), `address-geocoding.md` §2 시그니처를
  구현에 맞춤, T-GR-04 acceptance 수정 파일에 스탬프 repo(`coverage()`). 테스트: ①→② 순서·④의 geocode run 조건·
  덮어쓰기의 version token·keyset 페이지.
- **충돌 마커 정리·가드(별도 커밋).** main에 몇 주 전 리베이스가 남긴 `|||||||` 줄 둘(`docs/archive/journal-2026-08d.md`
  `## 2026-08-31 — head 값 고정을…` 앞, `docs/tasks-done.md` `## 2026-08-30 — T-VN-M05-MANAGER-PIN-ROTATION…` 앞)을
  지웠다 — 마커 줄 하나씩만(98 B·121 B), 앞뒤 절은 저장소에 각각 1회뿐이라 중복 본문은 없다. 아카이브는 읽기 전용이지만
  마커는 본문이 아니라 깨진 이관의 잔재라 규약 §8의 복구 예외로 본다. 같은 날 이 PR과 #1325의 리베이스도 journal·
  resume에 같은 줄을 남겼다(리뷰가 잡음). `tests/lint/test_docs_have_no_conflict_markers.py`가 docs·루트 Markdown의
  줄머리 마커를 막는다(UTF-16 보고서 하나는 BOM으로 읽는다) — 정리 전 main에서는 빨갛다.
- **3차 리뷰 반영.** ADR-109 규칙 ②·acceptance §T-GR-03 수정 파일을 `geocode_obtained_code`(시도 필드 없음)로 맞췄고,
  `address-geocoding.md`의 커서 정의·롤아웃 문단(backfill 뒤 첫 토큰 = 기준선, '순서와 무관하게 1회' 문장 삭제)과 §7 센서
  행·acceptance §T-GR-05에 기준선 케이스(빈 커서 + 토큰 → 커서 기록·계획 0)를 더했다. keyset 질의는 첫 페이지와 다음
  페이지를 다른 문장으로 나눴다(`(:after IS NULL OR …)`는 generic plan에서 범위 스캔을 잃을 수 있다).
- **게이트.** 통합: NULL·형식 위반 토큰은 outcome 셋 모두 DB가 거부, 토큰 없음 = 0건, stale 5분기와 "현재 토큰 None →
  0건", primary 링크·활성·dataset 범위, 런타임 role 쓰기·읽기, CASCADE. 단위: 응답 `dataset`
  있음/없음/형식 위반, `dataset_version()` 경로·본문 `{}`·`available=false`·계약 위반 typed 오류, 빈 답 계수(reverse 6 =
  정상 3·빈 답 2·전송 실패 1 → calls 6·failures 1·empty 2), 판정 표 전 행.

## 2026-10-15 — geo·transport client connect timeout 분리(T-MAP-02, ADR-110 결정 3): 브랜치 `feat/t-map-02-connect-timeout`

- **왜 지금.** geo·weather·transport가 2026-10-14~15 odroid로 옮겨졌다(ADR-110 사실 갱신 절). 같은 호스트의
  피호출자가 죽으면 커널이 즉시 RST를 주지만, 다른 호스트가 꺼지면 SYN이 응답 없이 timeout까지 간다. Map geo client는
  timeout 하나(10 s)라 연결 수립에도 그만큼을 썼고, admin 이슈 액션 2곳은 timeout 인자가 없었으며(httpx 기본 5 s)
  offline upload·CLI 2곳은 `10.0` 하드코딩이었다. 원래 순서는 "transport 플립 전 배포"였으나 플립이 먼저 일어났다 —
  소유자 결정(2026-10-15)으로 해제 조건은 "머지 뒤 첫 prod 배포"다.
- **바꾼 것.** 설정 필드 2개(connect, 기본 4 s — 첫 판은 2 s였으나 리뷰에서 올렸다: Linux SYN 재전송이 약 1 s·3 s라
  2 s는 첫 재전송만 기다리고, geo `_post`는 재시도가 없어 과부하 odroid의 느린 수립 한 번이 MOIS run 전체를 죽인다;
  Manager compose는 이 env를 넘기지 않으므로 기본값이 운영 값이다), 팩토리 둘(`geocoding.geo_http_timeout`·`provider_fetchers.
  transport_http_timeout`), geo 8곳·transport 3곳이 팩토리를 쓴다. `httpx.Timeout(connect=…, read=…)` 둘만 주는 꼴은
  httpx 0.28이 `ValueError`로 거부하므로 첫 위치 인자(기존 timeout)가 read·write·pool을 덮는다. 문구: `GEO_HEAVY_POOL`
  근거('n150 디스크 대기' → 'odroid geo CPU 보호'), `mois_geocode_concurrency` 설명, transport base URL 설명,
  `.env.example`의 standalone 주석과 새 키 2개.
- **게이트.** (1) 팩토리 값(필드를 바꾸면 빨강), (2) accept 큐를 미리 채운 `listen(0)` 서버로 SYN을 드롭시켜 geo client와
  실제 transport fetcher가 connect + 0.5 s 안에 실패하는지(전제 — 새 connect가 매달리는지 — 를 먼저 확인), (3) lint:
  `KorTravelGeoRestClient(`·`_transport_connection(`을 부르는 함수 안의 모든 `httpx.AsyncClient(`가 `timeout=<팩토리
  호출>`이 아니면 빨강(리터럴·부재·settings float 직접 전달·그 함수 밖에서 만든 client). 낡은 대역 하나
  (`test_resources.py`의 `http.timeout == 2.5`)를 새 계약으로 고쳤다.
- **관찰(범위 밖).** 2026-10-15 08:3xZ odroid geo `/v2/reverse`가 Map 컨테이너에서 세 번 약 9 s 뒤 504였다가 다음 호출
  1.0 s 200. connect가 아니라 응답 지연이라 이 변경과 무관하고 read 상한(10 s)은 task 범위대로 그대로 뒀다.

## 2026-10-15 — ADR-110 사실 갱신: geo·weather·transport가 실제로 odroid로 갔다: 브랜치 `docs/adr-110-odroid-facts`

- **무엇이 바뀌었나.** ADR-110 초안(2026-10-13)은 "포트·URL 동일, 호스트만 이전"을 전제했지만 소유자가 2026-10-14~15
  Manager ADR-58 "잠정 시행"으로 세 스택을 먼저 옮기고 odroid 소비자 포트를 통일했다 — geo `12501`(UI `12505`), weather
  `12201`, transport **API gateway `12301`**(odroid backend `12302`·frontend `12303`). Map 소비자 값은 Manager #476/#479의
  compose 기본값으로 옮겨졌다(Map 저장소 변경 0 — ADR-110 결정 1이 맞았다). n150 공용 workspace는 concierge·map·pinvi
  세 location, geo Dagster는 odroid 자체 plane.
- **확인한 방법**(2026-10-15 08:34~08:40Z, n150 읽기 전용, 상태 코드만 출력): Map api·code-server env의 geo/transport base가
  odroid; Map API 컨테이너에서 odroid geo `/v2/reverse`·`/v2/dataset/version` 200; code-server에서 transport gateway export
  토큰 200·무토큰 404; n150에 transport·weather 컨테이너 0개, geo-api·ui는 남아 있음(Manager `map → geo` depends_on 때문,
  workspace에는 없음); chain t1015d(Map `4931f9c0` + PinVi `44d8ecc8`) D1 11 passed·D2 `phase=passed`.
- **관찰 하나.** 같은 확인 직전 odroid geo `/v2/reverse`가 세 번 약 9 s 뒤 504였다가 다음 호출은 1.0 s에 200. 원인은 보지
  않았다 — Map 단일 timeout 10 s에 가깝다는 점만 적는다(T-MAP-02가 다루는 것은 connect이지 이 read 지연이 아니다).
- **결정과 어긋난 순서.** T-MAP-02(connect 분리)는 "transport 플립 전 배포"였는데 플립이 먼저 일어났다. 소유자가
  2026-10-15 해제 조건을 "머지 뒤 첫 prod 배포"로 바꿨다(acceptance §T-MAP-02).
- **리뷰 반영.** odroid geo는 2026-10-12 n150 백업의 dump 복원(`pg_restore` rc=0, alembic `0029`)이고 `data_token`은 그
  위에서 처음 저장됐다. Map geo 키는 복원으로 보존됐다(활성 label `kor-travel-map`, 재발급 없음) — geo ADR-070 "실행 기록"
  (geo PR #575). 소유자 결정: '없음 → 첫 data_token'은 기준선이지 재계획이 아니다(ADR-109 역포인터; 구현은 T-GR-04/05).
- **문서.** ADR-110 머리말·"사실 갱신(2026-10-15)" 절 신설·컨텍스트/결정 5/후속의 포트·머지 상태 갱신(교차 ADR 셋은
  2026-10-13 main에 proposed로 머지돼 있었다), `integration-map.md` §1(transport·geo 행, Manager 행의 낡은 관측 포트
  12401/12301/12205 → 12102/12103/12104)·§2(그림의 transport 포트, LAN 단락)·§3(transport export 행)·§4(geocoding 행),
  CLAUDE.md geocoding 줄, ADR README 두 줄, ADR-109 역포인터. T-GR-00-LEDGER(#1323) `[x]`·이관.

## 2026-10-15 — journal·tasks-done 다음 경계 분리(T-GR-00-LEDGER): 브랜치 `docs/t-gr-00-ledger`

- **분리.** `journal.md` 209,356 B에서 가장 오래된 묶음 2026-09-20~25 8건(27,260 B)을 `docs/archive/journal-2026-09e.md`로,
  `tasks-done.md` 200,699 B에서 가장 오래된 두 절(2026-08-05 일괄 아카이브 110,174 B + 2026-08-04 889 B, 합 111,063 B)을
  `docs/archive/tasks-done-2026-08a.md`로 옮겼다. 경계는 fence 밖 `## ` 줄에서만 잡았다(두 경계 모두 fence 홀짝 0).
- **바이트 보존 검산**(분리 스크립트가 assert): journal 209,356 = 잔여 182,096 + 이동 27,260; tasks-done 200,699 = 잔여
  89,636 + 이동 111,063. 아카이브 본문은 이동 바이트와 같고 예외는 둘뿐이다 — tasks-done 쪽 상대 링크 4개(`tasks-done.md`,
  `runbooks/h35-prod-migration-cutover.md` ×2, `reports/h33-mislink-2026-07-29.json`)를 `../`로 재기준화(+12 B, 규약 §8의
  허용 예외)했고, 각 파일 끝 구분 빈 줄 1 B를 뗐다(앞선 아카이브와 같은 끝맺음). 머리말은 journal 161 B·tasks-done 166 B.
- **이름.** acceptance 초안은 `journal-2026-09c.md`라고 적었지만 09c(chain17 B 단계 수정 PR, 09-14~15)와 09d(#1319, 09-16~19)가 이미
  있어 규약 §8의 다음 글자 `09e`를 썼다. tasks-done 아카이브는 08월 첫 파일이라 `2026-08a`.
- **종결 이관.** T-GR-00(#1315 `f7affea8`)·T-MAP-01(#1316 `463453bf`)은 2026-10-13 머지·main lint.yml 초록을 `gh`로 확인하고
  `[x]`로 tasks-done에 옮겼다 — 두 절 모두 이 PR을 종결 소유자로 지정했다. T-GR-00-LEDGER 자신의 `[x]`는 머지가 조건이라
  다음 doc-only PR(ADR-110 사실 갱신)이 싣는다.
- **크기**(분리·이 항목 반영 뒤, 커밋 직전 `wc -c`): `journal.md` 184,071 B · `tasks-done.md` 91,029 B — 둘 다 ≤ 200,000 B.

## 2026-10-14 — D2 fixture `Alembic revision confirmation mismatch`: 확인 키를 repin이 API 이미지 head에서 유도: 브랜치 `fix/d2-fixture-alembic-head`

- 증상: Map 4931f9c0(#1319, head `406_feature_write_gate`) 배포 뒤 chain16 H(unit `d2-adr111h`)의 D2가
  `fixture-seed-failed`로 BLOCKED. `direct-seed.json.stderr`는 `scripts/admin_feature_live_fixture.py`
  `_prepare_fixture_connection`의 `fixture target Alembic revision confirmation mismatch`.
- 원인: 기대값 `E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_ALEMBIC_REVISION`은 `/root/.d2-live.env`의 **손으로 적은** 값
  (`404_transport_provider_identity`)이었다. repin은 이 키를 쓰지 않았고(2026-10-05 인계 문서가 "head가 바뀌면 손으로
  고친다"고 적었다), 405·406이 들어오는 동안 아무도 고치지 않았다. 백업 사본 기록상 이 키는 303→309→400→403→404로
  다섯 번 손으로 바뀌었다. DB(`alembic_version`)는 정상적으로 406이다 — fixture는 mutation 전에 멈췄다(잔여물 없음).
- 수정: `scripts/n150/repin.sh` 5단계가 4단계의 같은 Map API 컨테이너에서 `ktm-application-schema head`(이미지가 설치된
  migration graph만 읽는 attest 명령, API entrypoint head 게이트와 같은 정본)를 읽어 그 줄을 다시 쓴다. schema·revision
  문법·줄 개수 확인, 0600 임시 파일 + source 값 대조 + rename.
- 게이트: `tests/unit/test_n150_repin_derives_fixture_alembic_head.py` — 생산자(`docker/application-schema-head.py`)를 이
  저장소 graph 위에서 실제로 돌린 출력을 repin 프로그램에 넣어 옛 `404_…` 줄이 현재 head로 바뀌는지 본다(리터럴 head
  없음). 거부 경로 11가지, 호출 경로가 `api.Dockerfile`의 설치 자리·schema 상수와 같은지도 본다.
- 재실행: 호스트 `/root/repin.sh` 재설치 → chain16 재실행(D 단계가 새 키를 쓰고, G 단계 `adjudicate.sh`가 이번 BLOCKED를
  잔여물 0 실측 뒤 정리).

## 2026-10-14 — chain16 D1 판정이 ANSI 커서 제어 때문에 11/11 통과를 실패로 읽음: 브랜치 `fix/chain16-d1-ansi`

- 증상: 배포(Map 4931f9c0 + PinVi 2fa1c166) 뒤 chain16 F(D1)가 `11 passed (32.2s)`를 냈는데 `!! D1: 목록 11건이 전부 passed가 아니다`로 중단.
- 원인: Playwright line reporter가 진행 줄을 `ESC[1A ESC[2K`로 덮어써 마지막 줄이 `^[[1A^[[2K  11 passed`가 되고, #1318의 판정 `grep -qE "^ *$D1EXPECT passed"`가 줄머리 앵커에서 실패.
- 수정: `scripts/n150/chain16.sh` D1 출력에서 ANSI CSI 시퀀스를 `sed`로 걷어낸 뒤 판정. 판정 규칙(목록 수 == passed, skipped/did not run도 실패)은 그대로.

## 2026-10-14 — chain16 C단계(C7 executor 이미지) 실패 원인 규명 + `file:` 의존성 COPY 게이트: 브랜치 `fix/c7-executor-vendor-tgz` (PR #1320)

prod pair(Map 4931f9c0 · PinVi 2fa1c166) 배포 뒤 `/root/chain16.sh` C단계(unit `eb-adr111-10132219`)가
`scripts/build-c7-playwright-image.sh`에서 "executor image build failed (values redacted)"로 멈췄다.

- **원인은 소스가 아니라 일시적 네트워크다.** `docker buildx history logs`(BuildKit 이력, 스크립트의 `--quiet`·가림과
  무관하게 남는다)로 본 실패 빌드의 실제 출력은 `npm ci` 49.9초 시점 `npm error code ECONNRESET` / `network aborted`.
  같은 n150에서 같은 커밋 archive를 그대로(기본 umask, 스크립트와 같은 umask 077 둘 다) 다시 빌드하니 `npm ci` ·
  `verify:npm-tree` · `verify:next-sharp` 모두 통과했다. 같은 입력의 빌드 다섯 번 중 둘(둘 다 스크립트 경유, 49.9초·177초)이
  같은 `ECONNRESET`으로 죽고 셋(`--quiet` 포함)은 통과 — 플래그가 아니라 확률이다. 실패 시점 n150은 iowait 64~70%·swap
  in/out 진행(load 15~21)이었다. 재실행 한 번이면 지나가지만 같은 부하에서는 다시 날 수 있다.
- **보이지 않던 이유 둘.** ① 스크립트가 `--quiet`로 빌드하고 실패를 가린다 — 원문은 `docker buildx history logs <id>`에
  남는다(`docker buildx history ls`의 최신 Error 행). ② chain16 C단계가 `Result=success`를 찍었다 — `systemd-run
  --collect`가 실패한 unit을 즉시 회수해 `systemctl show -p Result`가 기본값을 돌려준다. 실제 판정은 뒤의 라벨 대조
  (옛 이미지 c4d17343 ≠ MAP)가 했다.
- **가설(vendor tgz 누락)은 기각.** `c7-playwright.Dockerfile`은 1a3c46737(10-06)부터 `frontend/vendor`를 `npm ci` 전에
  복사하고 `.dockerignore`도 그것을 빼지 않는다. 다만 그 수정에는 게이트가 없었다 — `frontend.Dockerfile`은 72242b1a0에서
  vendor를 복사했는데 C7 쪽은 따라오지 않은 틈이 실제로 있었다.
- **게이트.** `tests/unit/test_dockerfile_workspace_manifest_coverage.py`: 정본은 `npm ci`가 읽는 `package-lock.json`의
  `packages[*].resolved` 중 `file:`(워크스페이스 `link: true` 제외). `npm ci --workspaces`를 도는 모든 Dockerfile이 그
  stage에서 그 RUN **이전** build-context COPY로 각 경로를 WORKDIR/<path>(루트 `package.json`과 같은 자리)에 두고,
  `.dockerignore`가 그것을 빼지 않는지 본다. 하한(file: 의존성 ≥1·실재), `.dockerignore`/COPY 배치 matcher는 인라인
  규칙으로 자기검사. 1a3c46737^의 Dockerfile, vendor를 빼는 `.dockerignore`, 틀린 COPY 목적지 각각에서 빨갛게 된다.
- **재실행.** 소스 수정이 필요 없으므로 chain16을 배포된 같은 MAP/PINVI로 C단계부터 다시 돌리면 된다(핀 변경 없음).

## 2026-10-13 — 공용 PG lock table 고갈(53200) 근본 수정 — Feature advisory fence 전역 gate(ADR-111): 브랜치 `fix/bulk-curation-locks` (PR #1319)

2026-10-12 09:25Z부터 root `97ac4e01-…`의 `feature.finalize_provider_curation_root`가 dataset 99(`transport_fuel_stations`,
11,820 Feature)의 링크 Feature마다 `pg_advisory_xact_lock('feature-write:<id>')`를 잡다가 공용 PG(`max_locks_per_transaction=64`)
lock table을 고갈시켜 SQLSTATE 53200으로 롤백됐고, reconcile sensor가 30초마다 무한 재시도하며 같은 cluster 전 tenant를
깨뜨렸다(12:59:54Z prod sensor 정지 — 운영자 조치, 이 PR 범위 밖). 같은 패턴이 프로시저 여덟 곳에 더 있었다.

- **설계(ADR-111).** 전역 gate `feature-write-all`: 대량 writer 9개(finalize root·receipts, materialize, curated
  source/rule/theme create·patch·archive)는 종전 Feature 잠금 루프 자리에서 gate **배타** 1회, 단건 writer 6개(approve
  request, curation item create/patch/archive, manual item, promote candidate)는 `feature-write:<id>` 바로 앞에 gate **공유**.
  순서 `curation-import → feature-curation-write → feature-write-all → feature-write:<id> → curation-catalog-write`.
  "Feature 잠금을 그냥 지운다"는 기각 — curated theme/source/rule 명령·promote·approve는 `feature-curation-write`를 잡지
  않아 증명이 성립하지 않는다(ADR §3). Python은 `feature-write`를 잡지 않는다.
- **migration `406_feature_write_gate`.** 사이드카 15개(`_406_<루틴>.sql`) = head 원문에서 잠금 몇 줄만 바꾼 사본
  (생성 후 head 원문과 diff해 잠금 줄 외 차이 0 확인). 소유자 창 `ktm_curation_command_owner` →
  `ktm_feature_request_procedure_owner` → `ktm_feature_schema_owner`로 끝남(RESET ROLE 없음). receipt head CHECK에 406.
  head-schema.sql은 n150에서 `KTM_WRITE_HEAD_SCHEMA=1`로 재생성(+25/−121, 잠금 줄과 CHECK만).
- **sensor 하드닝.** 결정적 SQLSTATE(08·40·57 class와 53300·55P03·55006 제외) 실패는 tick을 종전대로 실패시키되
  cursor `last_failure{run_id, SQLSTATE, count}`만 갱신(watermark 불변). 같은 run·같은 SQLSTATE 5연속 + terminal run이면
  `abandon_dagster_feature_run`이 기존 terminal 전이(`failed`/stage `failed`)로 root를 닫고 `feature_operation.reconcile_abandoned`
  error 로그. 새 상태·컬럼 없음(`quarantined_at`은 migration 소유라 쓰지 않음). ledger가 비면 cursor 모양은 종전 그대로.
- **테스트(효과 결박).** `tests/integration/test_feature_write_gate_lock_budget.py` — lock table 칸 수(설정에서 유도)의
  2배 Feature를 한 dataset에 링크하고 root 완결, 그 트랜잭션의 advisory lock 수 < 16. n150 실측: 405 스키마(406 제거)에서
  `asyncpg OutOfMemoryError: out of shared memory`로 **red**, 406에서 green. `tests/lint/test_feature_write_lock_order.py` —
  head 전 루틴(203)을 중첩 CALL까지 펼쳐 Feature 잠금 스칼라·gate 선행·전역 순서·공유→배타 승격 금지; 406 전 head에서
  위반 24건으로 red, 심은 위반 셋으로 탐지기 red 확인. sensor unit 6건(상한 도달·일시 SQLSTATE 미계수·다른 실패 리셋·
  진행 중 run 미닫힘·닫기 실패 재시도·cursor 하위호환).
- **열린 것.** `finalize_provider_curation_receipts`는 호출자 없음(지우지 않고 같이 고침). 서로 다른 dataset 대량 writer는
  이제 직렬화된다. 배포·sensor 재시작은 운영자 몫.
- **적대 리뷰 2건 반영(같은 브랜치, #1318 위로 리베이스).** 둘 다 잠금 순서·교착 결함은 찾지 못했고 CI가
  빨갰다. (1) BLOCKER — 통합 검사가 세션 공유 DB에 1.5만 Feature·active dataset·done job을 남겨 뒤의
  `test_mois_loader.py` 2건(glibc lane)을 깼다 → 그 모듈만의 DB를 같은 컨테이너에 만들어 head까지 올리고 지운다;
  active rule 하나를 걸어 중첩 materialize도 같은 규모로 돌린다(`observed_candidate_count == Feature 수`).
  (2) HIGH — 53200은 cluster의 다른 tenant가 일으킬 수 있으니 세면 안 된다(406 전에 sensor가 켜지면 2분 반 만에
  97ac4e01을 닫는다) → root를 닫는 SQLSTATE는 22/23/P0 허용 목록뿐, 그 밖은 cursor `retry_after`로 30s→15분 backoff.
  (3) MED — root 완결은 `feature-curation-write`를 든 채 gate를 기다리지 않는다(`pg_try_advisory_xact_lock`, 바쁘면 55P03);
  단건 writer 여섯은 `SET lock_timeout TO '5s'`, API는 55P03 → 503 `LOCK_TIMEOUT`(OpenAPI 바이트 불변, openapi-drift 초록).
  abandon 통합 검사(root failed/failed, done member 그대로, 로그 1행에 `provider_dataset_ids`·`action`, 두 번째 호출
  blocked/terminal). rollback 시 cursor 처리 ADR에 기록. (4) LOW — 대량 명령 여섯의 죽은 범위 재검사(두 scan + 40001)
  제거, 호출자 없고 gate 앞에서 행을 갱신하던 `finalize_provider_curation_receipts` DROP, lint가 `ops`·`provider_sync`
  호출과 행 쓰기의 trigger까지 펼친다(심은 trigger 위반으로 red 확인). ADR-111에 새 Feature에도 gate를 잡는 이유.
- **함정.** 시드의 `created_at`·`started_at`을 `clock_timestamp()` 두 번으로 넣어 μs 차이로
  `ck_import_jobs_ck_import_jobs_feature_engine_timeline`에 걸렸다 — 한 문장의 `now()`로.
- **델타 리뷰 반영(00630d19 위).** 마이그레이션·테스트는 GO, 재시도 논리에 HIGH 하나. (H1) 실패한 run 하나가
  tick 전체를 실패시켜 두 cursor가 멈추고 DB page에 닿지 못했다 — 42xxx·54000·SQLSTATE 없는 예외 같은 영구 실패면
  15분 backoff 아래 reconcile 전체가 무기한 선다. → run별 `deferred` 표로 실패한 run만 미뤄 두고 watermark·같은 page·
  DB page를 계속 돌며, 미뤄 둔 run은 시각이 되면 run_id로 다시 집는다(표 최대 200). 변이 확인: 앞 run이 계속 실패해도
  뒤 run과 DB page run이 같은 tick에 반영된다(`test_a_parked_run_does_not_block_the_others`). (M1) 같은 실패 5연속에
  `feature_operation.reconcile_stalled`를 한 번. (M2) 닫기는 `applied`일 때만 표에서 지우고, `blocked`면 표에 남겨 다시
  닫지 않고 멈춘 run으로 올린다(잘못된 "failed로 닫음(outcome=blocked)" 로그 제거). (M3) rollback은 `deferred` 키만 뺀
  cursor `--set`(prod는 null cursor 초기화 거부라 `--delete` 금지), 405 재배포 약속 대신 fix forward. (M4) 55P03은
  30초 고정 backoff, ADR에 "공유 보유자도 try를 막는다". (L) `_sqlstate`/`sqlstate_of`는 `orig`·`__cause__`만;
  API는 typed `DBAPIError` 처리기(55P03만, 나머지는 다시 던져 종전 500); lint는 lock 문장의 어떤 FROM도 scan으로 —
  그래서 `patch_curation_item_command`의 두 Feature 잠금을 `LEAST`/`GREATEST` 두 스칼라 문장으로 바꿨다. CHANGELOG·
  journal·resume에 남아 있던 diff3 base 표지(`|||||||`) 세 줄 제거.
- **3차 리뷰 — 미뤄 두는 표를 걷어내고 단순하게.** run별 `deferred` 표가 새 손실 경로(넘침으로 버린 Dagster 쪽 run은
  watermark가 이미 지나 DB page에도 없으면 영영 사라진다)와 재시도 폭주(tick당 실패하는 무거운 완결 최대 ~600건, 평가
  timeout 60초를 넘겨 cursor가 안 써지는 tick)를 만들었다. 소유자 원칙(단순하게)대로 걷어냈다: Dagster page는 **실패한
  머리 run에서 멈추고** watermark를 마지막으로 반영한 run에 둔다(건너뛰는 것이 없으니 잃는 것도 없다). cursor에는
  `head_failure` 하나, 물러선 동안 Dagster page를 통째로 쉰다. DB page는 매 tick 실패 3회·20초 예산 안에서 돌고 실패는
  기록하지 않는다(keyset이 다시 집는다). 닫기 규칙은 그대로(22/23/P0·머리·terminal·5회), `blocked/terminal`은 지나가고
  `blocked/cancellation`은 다시 한다. 55P03은 멈춤 보고 제외. `reconcile_stalled` 메시지에 이벤트 이름(`q` 검색)과
  running/terminal에 맞는 조치 문구. 실행 manifest 해석은 카탈로그 부재(`FeatureOperationInvariantConflict`)만 guard 거부로
  — 일시 실패가 관측 오류로 둔갑해 watermark를 지나가던 구멍(테스트 대역이 `LookupError`를 던져 가리고 있었다). 변이 확인
  둘: watermark를 지나가게 바꾸면, DB 예산을 없애면 해당 테스트가 빨개진다. journal 2026-09-16~19 7건을 아카이브로(§8,
  분리 전후 본문 sha256 `97fd54c2…` 동일). runbook은 pair 명시·preflight·systemd-run·원장/cursor 확인으로.
- **분할 결정 — sensor 재시도 설계를 되돌리고 후속으로.** 최종 리뷰(6d0ebfc98)가 backpressure 판에서도 HIGH 셋을 더 찾았다
  (DB root 없는 닫을 수 있는 머리의 영구 고착, 모든 lock_timeout 55P03을 gate 바쁨으로 봄, 서명이 번갈아 바뀌면 횟수
  초기화) — 설계가 매 판 새 구멍을 냈다. 406이 고착의 원인을 없애므로 sensor·`abandon_dagster_feature_run`·
  `reconcile_stalled`/`reconcile_abandoned` 로그와 그 테스트·대역을 origin/main으로 되돌렸다. main sensor에서 55P03은
  그냥 tick 실패 → 30초 뒤 재시도이고 닫는 경로가 없다. manifest 해석의 guard 축소는 남겼다 — main sensor에서 일시
  실패가 이제 다른 DB 실패처럼 tick을 실패시킬 뿐 관측 오류로 watermark를 지나가지 않는다. 리뷰 결과는 ADR-111 결정 4와
  `T-RECONCILE-RETRY`(해제 조건: 잃지 않음·tick 시간 유계·경과 시간 알림·gate 전용 SQLSTATE·명시 목록만 닫기)로.
- **migration 번호.** #1319가 406(`406_feature_write_gate`)을 쓰므로 Track 1(ADR-109)의 계획 번호를 하나씩 민다 — `feature_geocode_stamps` 406 → 407, `kor_travel_geo_releases` 407 → 408(tasks·acceptance·ADR-109·address-geocoding).

## 2026-10-13 — admin e2e 전체가 로드 단계에서 죽던 결함(ESM 전용 `@kor-travel/ui`): 브랜치 `fix/e2e-esm-kor-travel-ui`

n150 chain16 D1(Map `c4d17343`)이 테스트를 하나도 돌리기 전에 `Error: Package subpath './navigation' is not defined by
"exports" in …/@kor-travel/ui/package.json`으로 끝났다(require stack `src/lib/auth.ts:1` ← `e2e/auth-session.ts:5` ←
`e2e/live/auth.setup.ts:4`). acde3726(2026-10-06)이 `auth.ts`에 `@kor-travel/ui/navigation` import를 넣었는데, vendored
`kor-travel-ui-0.1.0-dev.6.tgz`는 `"type":"module"`이고 `exports`에 `types`+`import` 조건만 있다. admin frontend는
`"type":"module"`이 아니라 Playwright가 e2e TS를 CJS로 변환해 `require()`하므로 그 subpath를 해석하지 못한다. Next·tsc·
eslint·vitest는 모두 ESM/번들러 해석이라 통과했다.

- **영향 범위(n150 실측, `playwright test --list`).** `c4d17343`에서 mocked(`playwright.config.ts`)·live·cache-target-streams
  세 config 모두 rc=1 — mocked `e2e/auth.setup.ts`도 같은 `auth-session.ts`를 쓴다. 즉 10-06 이후 D1·M05 등 live와 mocked
  checkpoint 모두 로드 불가였다. CI가 못 잡은 이유: GitHub 워크플로 어디서도 Playwright spec을 로드하지 않는다
  (`frontend.yml`은 "e2e는 서비스가 필요해 n150에서 돈다"며 제외).
- **수정.** `SESSION_COOKIE_NAME`을 import 없는 `src/lib/session-cookie.ts`로 옮기고 `auth.ts`는 재export, e2e 두 곳
  (`e2e/auth-session.ts`, `e2e/live/cache-target-streams-isolated.live.spec.ts`)은 새 모듈에서 가져간다. 대안이던 frontend
  `"type":"module"`(Playwright ESM 로드)은 next/eslint/postcss config와 스크립트 전체의 모듈 해석을 바꿔 범위가 크다.
- **재발 방지(효과 결박).** frontend 패키지 `e2e:list` = 세 config의 `playwright test --list`, `frontend.yml`이 vitest 뒤에
  실행한다. 서비스·브라우저 없이 spec import 그래프를 실제로 require한다. n150에서 `c4d17343` 사본은 세 config 모두 rc=1
  (같은 오류), 이 브랜치는 rc=0(mocked 271 tests/28 files, live 1142/28, cache-target-streams 1/1) — 검사가 이 결함에서
  빨갛게 되는 것을 확인했다.
- **첫 live 실행(`bb602ea7`).** n150 prod 대상 읽기 전용 D1 4 spec(`--workers=1`): 11건 중 9 passed, 2 failed — live
  `auth.setup.ts`를 포함해 전부 로드·실행됐다(이전엔 0건). 처음엔 두 실패를 "무관·범위 밖"으로 적었으나 적대 리뷰
  (HIGH-2)가 chain16 D1은 spec 하나만 실패해도 죽으므로 둘을 남기면 D1이 계속 빨갛다고 짚어 **이 PR에서 고쳤다**(아래).
- **리뷰 반영 1 — `home-dashboard-roundtrip`(spec 결함).** 첫 실행 행을 `getByRole("row", {name: kind})`로 찾아 첫 페이지에
  같은 kind가 여럿이면(prod `import_job` 8행) strict mode 위반이었다. id(`shortId`)+kind 필터로 찾고 `toHaveCount(1)`.
- **리뷰 반영 2 — `admin-scenario-catalog` "pipeline live UI calls datasets catalog…"(실제 prod 결함).** 화면에 "Dagster
  연결 불가 — 응답 전체 대기 상한 초과"와 큐 sensor 차단 alert가 떠 `queueOperational=false`, 갱신 요청 dialog(=
  `/v1/ops/datasets` 호출)가 렌더되지 않았다. 원인은 PinVi #581과 같다: overview·schedules·summary 세 GraphQL 문서의
  `ticks(limit: 3)`가 `afterTimestamp` 없이 instigator의 전체 tick 이력을 읽는다(공유 `dagster_shared.job_ticks` 약 40만
  행). 수정: `dagster_graphql`에 `SCHEDULE_TICK_WINDOW_SECONDS`(2일)·`SENSOR_TICK_WINDOW_SECONDS`(1시간)·
  `MAX_TICKS_IN_WINDOW`(300)와 `tick_window_variables()`를 두고 세 문서가 `afterTimestamp: $scheduleTicksAfter|$sensorTicksAfter`를
  싣는다. OpenAPI 변경 없음(PinVi 재vendor 불필요). spec은 전제(overview HTTP 성공, 큐 sensor 차단 alert 부재)를 먼저 단언해
  원인을 메시지로 낸다.
- **실측(n150, 127.0.0.1:11002, 읽기 전용, 문서별).** overview(sensor tick만): 창 없음은 이 시점 4회 모두 **HTTP 500 at
  15.1~15.4초**(webserver statement timeout; 앞서 cold 10.0초·warm 1.3초도 봤다) → 창 있음 **0.08~0.12초**(같은 시각 교차
  측정 4회). 단 디스크 대기가 큰 순간(load 12~14, iowait 44~52%) 창 있음 첫 호출 1회가 27.4초였다 — 창은 읽는 행 수를 줄일 뿐
  n150의 I/O 정체까지 없애지는 못한다. schedules: 창 있음 0.18~0.24초. summary: 창 있음 0.20~0.22초(2일 창 기준; 62일
  창일 때 0.27~0.54초·0.50~0.53초). 오늘은 Map schedule이 전부 STOPPED라 schedule 쪽 행은 거의 없다.
- **schedule 창 2일(리뷰 4라운드 MED).** 처음엔 월간 cron(`10 3 1 * *`)을 덮으려 62일(최장 주기 2배)로 두었으나, Dagster
  `get_ticks`는 `selector_id = X OR (selector_id IS NULL AND origin = Y)`라 인덱스 순서 scan을 못 하고 창 안 전 행을 읽어
  정렬한다 — 비용은 창 안 tick 수에 비례한다. 같은 sensor 하나의 EXPLAIN ANALYZE(`BEGIN READ ONLY`): 창 안 211행 0.45초,
  9,690행 cold **7.4초**, 33,971행 warm 0.14~0.22초. 62일은 schedule이 전부 STOPPED인 오늘만 쌌고, `*/10` schedule
  (`feature_notice_transport_highway_incidents_ten_minute_schedule`) 하나가 켜지면 8,900행 → 7초대로 돌아간다. 검토한
  대안: schedule마다 자기 cron으로 창을 잡는 것(두 번째 요청·별칭 문서·cron 파서가 세 호출 지점에 필요)보다, **창 하나 +
  비용 상한 테스트**가 단순하다 — `test_schedule_window_cost_is_bounded_by_the_densest_cron`이 배포 Definitions의 최단 cron
  간격으로 창 안 tick 수(`*/10` × 2일 = 288)를 `MAX_TICKS_IN_WINDOW` 이하로 강제해, 더 조밀한 schedule을 더하면 창을 줄일지
  상한을 올릴지 고르게 한다(sensor도 같은 상한, 15초 × 1시간 = 240). 대가: 주간·월간 schedule은 마지막 tick이 2일보다
  오래면 `recent_ticks`가 비고, 1시간 넘게 멈춘 sensor도 그렇다. 관리자 UI는 RUNNING인데 비면 "최근 2일/1시간 tick 없음"으로
  표시한다(`src/lib/dagster-tick-window.ts`; 값은 같은 테스트가 API 창과 대조). sensor `typeSpecificData.lastTickTimestamp`로
  멈춤을 드러내는 안은 응답 DTO에 필드를 더해야 해(OpenAPI 변경 → PinVi 재vendor) 이번엔 표지로 그쳤다. 운영자 cron
  override(`load_schedule_cron_overrides`)는 정의에 없어 테스트가 못 본다 — override 간격이 2일보다 길면 같은 빈 목록, `*/10`보다
  조밀하면 비용이 그만큼 커진다.
- **효과 결박 테스트.** `tests/unit/test_dagster_tick_window.py`가 세 문서를 Map code location을 in-process로 실은 Dagster
  (1.13.24)에 실행해 storage `get_ticks`가 받는 `after`를 기록한다. main의 문서로 되돌리면 세 건 모두 빨갛다(n150 실측:
  summary는 `after=None`, overview·schedules는 batch 경로로 빠져 `get_ticks` 0건). 시계를 고정하고 instigator 종류별
  `after` 다중집합을 대조해 두 변수를 바꿔치기해도 빨갛다. 창 비용 상한(위), sensor 창 ≥ 10×최장 최소 간격, tick 선택 문서
  목록(`Assign`·`AnnAssign` 모두), UI 표지 값도 본다. 기존 router·service 테스트는 시계를 고정해 호출 지점 변수까지 대조한다.
- **리뷰 반영 3 — 게이트·config.** `scripts/verify-all-gates.sh`에 `e2e:list` 게이트(빠져서 CI pytest의
  `test_gate_script_covers_every_ci_blocking_command`가 빨갰다, HIGH-1). `e2e:list`의 live 실행은
  `e2e/reporter-load-check.ts`로 커스텀 reporter 둘(C7 redacted, mocked failure)을 **로드만** 한다(인스턴스·훅 없음 — n150에서
  파일 0개 확인, reporter에 ESM 전용 import를 넣으면 rc=1). `playwright.live.config.ts`의 top-level `testIgnore`가 chromium
  project의 `testIgnore`에 대체돼 격리 전용 `cache-target-streams-isolated` spec이 live suite에 들어가 있었다 — project-level로
  옮겨 live 목록이 1142/28 → 1141/27. CI 단계는 `forbidOnly`로 `test.only`도 잡는다(n150에서 `CI=1` 변이로 확인);
  `verify-all-gates.sh`도 `CI=1`로 같은 조건에서 돈다. `scripts/n150/chain16.sh` D1은 `--list` 개수만큼 passed여야 초록이고
  skipped·did not run·interrupted도 실패로 본다(전에는 failed/flaky 줄이 없으면 초록).
- **D1 재실행(브랜치 사본, prod 읽기 전용).** 11건 중 **10 passed, 1 failed**. `home-dashboard-roundtrip`은 이제 통과한다. 남은 1건은 `admin-scenario-catalog`의 새 전제 단언이 "큐 sensor 차단 alert — Dagster 상태 스냅샷을 신뢰할 수 없습니다"로 정확히 원인을 내며 실패한 것이다 — prod Map API가 아직 창 없는 문서를 쓰기 때문이고, 이 PR의 API 수정은 배포 뒤에야 live에 보인다. 배포 전 증명으로 이 브랜치의 세 문서를 그대로 prod Dagster에 보냈다(위 실측). **D1 11/11은 Map API 배포 뒤 재실행으로 확인할 일이다.**

## 2026-10-13 — chain17 B 단계가 같은 Map·새 PinVi 회전을 건너뛰던 결함: 브랜치 `fix/chain17-rotate-when-pinvi-changes`

n150 chain t1013e(2026-10-13 09:11Z)에서 `/root/chain17-pv.sh`(운영자 변형, `PINVI_OVERRIDE` 추가본)가 B 단계에서
`원장 map == MAP`만 보고 "이미 회전됨 — 건너뛴다"를 택했다. 인자로 준 새 PinVi `2fa1c166`은 회전되지 않았고, 원장의
옛 PinVi `97f2baf2`로 재구축·C6c 스모크가 돌아 1분 만에 같은 실패가 재현됐다. 수동 `rotate-pinned-pair c4d17343 2fa1c166
"<reason>"`은 성공했다 — registry는 같은 Map·다른 PinVi 회전을 허용하고 pair 전체가 같을 때만 거부한다. 즉 건너뛰어도
되는 조건은 "원장 map·pinvi 둘 다 인자와 같다" 하나뿐인데 스크립트는 절반만 보고 있었다.

- **수정(`scripts/n150/chain17.sh`, 정본 — ADR-102 결정 6).** (1) B 단계 skip 조건을 `map == MAP && pinvi == PINVI`로,
  하나라도 다르면 `rotate-pinned-pair`를 부른다. 회전 뒤 검증도 map·pinvi 둘 다 원장과 대조한다(map만 보면 같은 구멍이
  거기서 다시 열린다). 원장 읽기는 기존 `ktdctl pin show | awk` 패턴을 `pin <key>` 한 helper로 묶어 0·B 단계가 같이 쓴다.
  (2) 운영자가 `/root/chain17-pv.sh`로 손수 들고 있던 `PINVI_OVERRIDE`를 정본에 흡수했다 — README가 "호스트 사본을 손으로
  고치지 않는다"고 못박는데 변형이 호스트에만 있었고, 이 결함은 그 변형에서만 드러난다(정본은 PinVi를 늘 원장에서 읽어
  map만 봐도 pair가 같았다). 생략하면 원장의 **현재** pinvi를 그대로 다시 핀하므로, 원장과 다른 PinVi를 올릴 때는
  같은 Map이든 새 Map이든 `PINVI_OVERRIDE`가 필요하다 — 헤더·README가 "같은 Map일 때만"으로 좁게 읽히던 것을 적대
  리뷰(MED)가 잡아 그렇게 고쳤다. (3) launcher 경로를 `ROTATE` 변수로 올렸다(`KTDCTL`·`DRIVER`와 같은 꼴) — 테스트가
  stub으로 바꿔 끼우는 자리이고, 리터럴은 상단 한 곳에만 있다. (4) 리뷰 LOW 둘도 반영: 0단계 pinvi 출처 라벨이
  `${X:+..}${X:-..}` 결합으로 override 때 `PINVI_OVERRIDE<sha>`로 붙어 찍히던 것(`-pv` 변형에서 그대로 옮겨온 표시
  결함)을 `PINVI_SOURCE` 한 변수로; B 단계는 원장을 못 읽은 빈 값을 "다른 pair"로 보지 않고 비교 전에 그 사유로 멈춘다
  (전에는 회전을 시도해 '회전 실패'로 원인이 가려졌다).
- **테스트(효과 결박).** 새 `tests/lint/test_chain17_rotates_when_only_pinvi_changes.py`: 스크립트의 B 단계 본문과
  `die`·`say`·`pin` 정의를 잘라 가짜 `ktdctl`(원장 파일)·가짜 `rotate-pinned-pair`(호출 기록 + 원장 갱신) 위에서 bash로
  실행한다. 같은 pair → rotate 호출 0·skip, (같은 map·새 pinvi / 새 map·같은 pinvi / 새 pair) → `rotate MAP PINVI REASON`
  정확히 1회, launcher가 0으로 끝났는데 원장 pinvi가 그대로 → exit 1·C로 가지 않음, 원장이 비어 있거나 pinvi가 없음
  → rotate 호출 0·exit 1. 추출이 빈 본문을 집지 않았는지도 먼저 본다. 기존 `test_n150_host_scripts_drop_attestation_chain.py`의 hard-gate 순서 단언은 launcher **호출** 자리
  (`"$ROTATE" "$MAP" "$PINVI" "$REASON"`)로 옮기고 `ROTATE` 대입값을 대조한다. `bash -n`은 기존 파라미터 테스트가 덮는다.
- **문서.** `scripts/n150/README.md` 표·"무엇이 Manager 쪽인가"에 같은 Map·새 PinVi 사례 한 줄, CHANGELOG `[Unreleased]`.
  ADR-102는 B 단계를 서술하지 않아 손대지 않았다.
- **journal 분리(§8).** 이 엔트리로 `docs/journal.md`가 227,144 B가 되어 상한 225,280 B를 넘었고
  `tests/unit/test_docs_archive_links.py::test_every_docs_markdown_stays_within_readable_limit`이 빨갰다(적대 리뷰 HIGH).
  하단 2026-09-14 6건·2026-09-15 2건(8건, 본문 21,744 B)을 `docs/archive/journal-2026-09c.md`로 옮겼다 — 옮긴 절 본문의
  sha256이 분리 전후 같음(`36527129…`), 상대 링크 없음, 현행 창은 2026-09-16~. 분리 뒤 journal 205 KB.
- **운영 후속(외부).** 머지 뒤 운영자가 `sudo install … scripts/n150/chain17.sh /root/`로 재복사하면 `/root/chain17-pv.sh`는
  필요 없다. 이 PR은 n150을 바꾸지 않았다(`/root/chain17-pv.sh` 읽기만).

## 2026-10-13 — geo·transport 호스트 odroid 이전(Track 2) Map 쪽 문서: 브랜치 `docs/adr-110-geo-transport-on-odroid`

문서만 바뀐 PR(doc-only, origin/main `f7affea8` 위). Track 2 설계(geo·weather·transport 세 스택과 그 PG를 odroid로,
포트·이름 동일·host만 n150 → odroid; 3차 적대 리뷰·2026-10-13 odroid 실측 반영본)에서 **Map 저장소가
책임지는 것**만 ADR-110(proposed, 미구현)으로 옮기고 `T-MAP-01`·`T-MAP-02`를 열었다. 코드·`.env.example`·compose·
CHANGELOG·OpenAPI·테스트는 건드리지 않았다. 호스트 플립 자체는 Manager ADR-58·geo ADR-070·transport ADR-014의 일이다.

- **결정 요약(ADR-110).** (1) Map 저장소는 값을 바꾸지 않는다 — geo·transport origin의 정본은 오늘 Manager compose
  기본값 + root `.env`(geo 기본값은 Map 서비스 **4곳** `:1582,1723,1813,1920`·transport는 code-server `:1732-1733`,
  @08a515e; registry `hosts:` 파생은 Manager ADR-58 R2 — 오늘 registry에 host 필드 없음, 그 뒤 `.env` URL 재정의는
  validate 거부); 플립 뒤 `ensure map`은 Map target 전 서비스 재생성(옛 값 든 컨테이너 0개 게이트);
  `.env.example:198,234`는 standalone 값(주석은 T-MAP-02 코드 PR). (2) UI 재빌드
  없음 — BFF `/api/geo`는 런타임 `KOR_TRAVEL_GEO_INTERNAL_URL` 우선(`route.ts:3-6`), 빌드 인자는 공개 host라 변경 0
  (설계 §14-10은 열린 결정 1 — 설계는 추천 없이 두 선택지). (3) 장애 의미가 RST → timeout으로 바뀐다 — geo 10 s·
  transport 30 s 단일 timeout(`settings.py:159-164,537-542`)을 `httpx.Timeout(<기존>, connect=<connect 필드>)`(기본값이
  read·write·pool을 덮는다 — `Timeout(connect=, read=)` 둘만은 httpx 0.28.1에서 ValueError)으로 팩토리
  하나씩(geo `geocoding.py`·transport `_transport_connection` 옆)으로 분리(T-MAP-02, 코드 후속; **geo 8곳·transport
  3곳** — geo 8곳 중 `admin_issues.py:276,306`은 timeout 인자 없음(httpx 기본 5 s), `dagster/offline_uploads.py:50-53`·
  `cli/main.py:447`은 10.0 하드코딩이라 settings를 읽지 않는다; 적용 범위는 lint로 효과 결박), 회로차단은 Map에
  두지 않음(배치 호출이라 run 실패가 곧 신호; PinVi만), transport ±30 min 시계 검사는 fail-closed 유지. (4) geo
  공개 키는 **오늘도 대조된다** — 이전으로 바뀌는 것 없음(geo 면제는 admin 프록시 컨텍스트만, `security.py:154-170`;
  Map은 `X-KTG-API-Key`만 보냄 `geocoding.py:1289`; 08-13 401 사고가 저장소 안 증거). 위험은 geo 재적재로
  `public_api_keys`가 비는 것뿐 → 키 재발급·root `.env` 재적용·컨테이너 전부 재생성·키 경로 200이 플립 9단계 필수
  (외부 추적). VWorld 폴백은 Map #979 가드와 충돌해 채택 불가(열린 결정 3은 '추천 없음·(나)만 가능'). `9-전` curl은
  선택적 smoke로 격하. (5) transport export allow-list에 n150 LAN 주소 `/32`(transport 쪽 변경; XFF 불가). (6) ADR-109 amend(109 상단에 역포인터 한 줄) — `GEO_HEAVY_POOL`
  유지·근거만 'n150 디스크 대기' → 'odroid geo CPU 보호'; 센서·재지오코딩은 LAN 키 경로(RTT 9.7 ms, 전량 ≈2.5 h+
  추정); odroid 풀로드 뒤 플립 시 전량 재계획 **수용을 추천**(소유자 결정 대기 — 열린 결정 2, 대안은 운영자 UI skip;
  수용이면 mv_refresh 다음 날·야간 창 밖; dump 복원이면 0). (7) 전환 절차에서 Map이 하는 일은 단계 1·5·9-전·9·drill·11
  (설계 §11.2 발췌; 2~4b·8a/8b는 외부 단계로 Map이 확인할 선행 효과만 — odroid plane healthy·`targets validate`
  host·시계 동기) — 게이트는 효과(n150 피호출자 stop 상태에서 export 1회·키 경로 200·peer = n150 LAN 주소 로그·MOIS run
  예산 10 % 안 FAILURE — 유도: 첫 chunk 500행 ÷ 동시성 2 × connect 2 s ≈ ≤502 s, 10 s면 ≈2,502 s로 10 % 초과).
- **odroid 상태(FB §A3, 03:4xZ).** WSL 직접 ssh·NOPASSWD sudo·docker 그룹·NTP 수동 동기 **완료**; timesyncd 부팅
  사이클 drop-in·compose v2/buildx·방화벽·fstab bind·swapfile **미완** — ADR 컨텍스트 7에 완료/미완을 그대로 적었다.
- **설계와 달리 쓴 것(head `f7affea8` 재확인).** `docker/frontend.Dockerfile` 빌드 인자는 `:56`이 아니라 `:57`(ARG)·
  `:62`(ENV); `kor_travel_geo_preflight_required`는 `:164-176`이 아니라 `:165-176`, transport base URL은 `:509-519`
  (초고의 `:165-177`·`:509-520`은 한 줄 초과 — 1차 리뷰 정정); MOIS 동시성 `:364-374`, 예산 `:388-`; transport 시계
  검사는 `kor_travel_transport.py:104`(`INCIDENT_SET_MAX_AGE` 30 min)·`:435-452`(설계 `:441-453`). geo client 생성
  지점은 설계에 없던 file:line을 더한 것인데 초고의 "4곳"이 틀렸다 — 1차 리뷰(HIGH)가 `admin_issues.py:276,306`(timeout
  없음)·`dagster/offline_uploads.py:50-53`·`cli/main.py:447`(10.0 하드코딩)을 찾아 **8곳**으로 고쳤고, 팩토리 자리
  (`geocoding.py` 지역 import / `_transport_connection` 옆)와 lint 결박을 적었다. 설계 §9.1의 Map 행은 connect 분리만
  요구하므로 회로차단은 Map 결정에서 명시적으로 뺐다(ADR-110 결정 3·열린 결정 4). weather는 Map이 호출하지 않아
  (ADR-105) 범위 밖임을 한 줄로 못박았다. 설계 T-MAP-01의 `.env.example` 주석은 이 PR이 `.env.example`을 금지하므로
  T-MAP-02 코드 PR로 옮겼다. 설계 정본 파일은 세션 scratchpad라 ADR 본문을 정본으로 선언하고 §는 출처 표기로 낮췄다.
  **설계 §9.1 키 행·§5.6 ⑥의 "geo 키는 loopback 면제라 검증된 적 없다"는 틀렸다** — geo 면제는 admin 프록시
  컨텍스트(CIDR+proxy secret+actor/roles)만이고 Map 호출은 오늘도 대조된다(ADR 컨텍스트 4에서 정정, geo ADR-070
  작성자에게 전달). **T-MAP-02 착수 순서**를 설계 §13의 MGR → MAP 사슬에서 분리해 병렬을 제안했다(코드 의존 없음 —
  열린 결정 6, 소유자 확인; 선행 T-GR-00-LEDGER·`geocoding.py` T-GR-01 공유). **LAN 주소 리터럴은 쓰지 않았다** —
  `scripts/check_prod_redaction.py`(#508, `lint.yml`·pre-commit)가 docs의 사설 IP를 거부해 호스트 이름(`n150`·`odroid`)
  으로 썼다(설계·지시문은 호스트를 LAN 주소 끝자리로 적지만 여기서는 조각도 쓰지 않는다).
- **1차 리뷰 반영(2건, 19 finding).** 전부 반영: timesyncd 상태를 §A3(수동 동기 완료·drop-in 미완)로, §14-19를
  '수용 추천 + 열린 결정 2'로, CLAUDE.md의 'Manager registry 정본'을 '오늘은 compose 기본값 + root `.env`(registry
  파생은 ADR-58 계획)'·'값 없음'을 'standalone 값'으로, ADR-109에 amend 역포인터를, 제목 3곳 통일(connect 분리 포함),
  열린 결정 1의 추천 출처 표기, 'Map만 끊긴다' → 'n150 consumer', T-MAP-02 동반 문구에 `settings.py:509-519` 설명,
  T-MAP-01 종결 소유자(T-GR-00-LEDGER/T-MAP-02 PR), 'CI 대기 없이' → 'lint.yml 초록 뒤(소유자 지시)', T-GR-00-LEDGER
  수치 갱신.
- **2차 리뷰 반영(2건, 17 finding — 전부 반영).** HIGH 2: geo 키 전제 정정(위; 결정 4를 '재적재 시 키 소실'로 축소,
  `9-전` curl을 선택 smoke로, integration-map·resume·acceptance 동일), `#508` redaction guard 실측 11 hit EXIT=1 →
  IP 리터럴 전부 호스트 이름/placeholder로(EXIT=0 재확인). MED: (가) VWorld 폴백 '추천' 철회(Map #979 가드
  `test_geo_key_provenance:493,506`·`test_compose_geo_key_resolution:143`·`test_deploy_automation:382`와 충돌 → 열린
  결정 3 '추천 없음·(나)만'); `12501:12501` publish 인용 삭제(host network에서 `ports:` 무효 — 실제는
  `KTG_API_HOST: 0.0.0.0` Manager compose `:1089`@08a515e); T-MAP-02 의존을 '선행 없음'에서 'T-GR-00-LEDGER 선행 +
  T-GR-01과 `geocoding.py` 공유(늦은 PR 리베이스)'로 + 열린 결정 6; MockTransport 픽스처 삭제(항진명제 — backlog
  포화 서버만); T-MAP-02 해제를 '(1)(2)(3) 초록 + 머지 + 4a 전 배포'로 한정하고 curl·drill을 종결 조건에서 뺌. LOW:
  lint를 '`timeout=`이 팩토리 호출'로(settings float 직접 전달도 빨강), '설계 파일 보존은 T-MGR-07 몫' 삭제, 교차
  ADR 번호에 '(계획, 미작성)', CLAUDE.md를 한 문장으로, Manager sha 드리프트(origin/main `094d3976`, transport 줄
  `:1736` 부근) 주석, integration-map §2의 file:line·'8곳 중 4곳' 복제 삭제(ADR 포인터만), ADR-110 `## 후속` 절 추가.
  범위 목록 밖 수정 1건: `docs/adr/109-geo-release-regeocode.md` amended-by 3줄(역포인터).
- **3차 리뷰 반영(2건, 17 finding — 전부 반영, 기각 0).** HIGH 1: T-MAP-02의 유일한 코드 사양
  `httpx.Timeout(connect=2.0, read=…)`이 httpx 0.28.1에서 `ValueError`(worktree에서 실행 재확인) → ADR 결정 3·tasks·
  acceptance를 `httpx.Timeout(<기존>, connect=<connect 필드>)`(기본값이 read·write·pool을 덮는다)로, acceptance (1)에
  `write == pool == read` 단언 추가. MED 5: geo base URL이 Manager compose의 Map 서비스 **4곳**(api·code-server·dagster·
  daemon `:1582,1723,1813,1920`@08a515e — 로컬 Manager 체크아웃 `git show`로 두 ref 모두 확인)에 주입되는데 `:1582` 하나만
  적고 단계 9를 'cs·API 재생성'이라 쓴 것을 '전 서비스 재생성 + 옛 값 든 컨테이너 0개 게이트'로 통일(결정 1·4(a)·7);
  결정 7 표에 '2~4b(외부)'·'8a/8b(외부)' 행을 넣어 단계 5·9의 선행 조건(odroid plane healthy·`targets validate`
  host·`timedatectl` synchronized·풀로드/mv_refresh/키 정책 완료)을 결박; 단계 9의 '센서 계획 1건' 게이트를 열린 결정
  2(풀로드+수용 / dump 복원이면 0건 / T-GR-05 미배포면 해당 없음)로 분기; 교차 ADR 셋을 '미작성'에서 '**proposed·병렬
  PR 미머지**'로(로컬 체크아웃 `ktdm-t2docs`·`geo-t2docs`·`transport-t2docs`에 본문 존재, origin/main에는 없음 — 6곳);
  transport env 파일을 계획 이름 `.env.prod`가 아니라 오늘 이름 `.env.server14`(transport `README.md:123-124`)로 적고
  `.env.prod`는 ADR-014 개명 계획으로. LOW 11: backlog 포화 레시피를 '사전 connect ≥3건으로 큐를 채운 뒤 측정, Linux
  전제, non-routable 주소 금지'로; 잔존 `.13`/`.14` 조각(journal (7)·acceptance T-MAP-01)을 호스트 이름으로; T-MAP-01
  종결 소유자를 T-GR-00-LEDGER 단일로(tasks·acceptance·resume); 'T-GR-01과 같은 client 생성 지점' → '같은 모듈, 충돌
  범위는 import·새 함수 자리뿐'; drill 10 % 유도식(prefetch는 예외를 삼키고 `geocoding.py:430-432`, 실시간 조회가
  `GeoRequestError`를 전파해 첫 chunk에서 FAILURE — ≤502 s vs 10 s면 2,502 s); ADR-58 R2 뒤 `.env` URL 재정의가
  validate에서 **거부**됨을 컨텍스트 1·결정 1·integration-map·CLAUDE.md에 명시하고 "후속"에 표식 교체 세 시점을 둠;
  결정 6 셋째 bullet의 'skip 쓰지 않는다/대안은 skip' 모순을 조건부 문장으로; `up{host="odroid"}`에 'ADR-58 파생물
  계획, 오늘 Prometheus에 host 라벨 없음' 표식; 저장소 밖 메모리 파일 인용을 `integration-map.md` §4 포인터로.
- **원장.** `tasks.md`에 `T-MAP-01`·`02`(접두사 임시, ADR-110 열린 결정 5), `tasks-acceptance.md`에 두 절
  (`tests/lint/test_task_ledger_conventions.py`가 열린 task마다 절을 요구한다). `journal.md`는 이 항목 포함 약 224 KB로
  상한 225,280 B 아래라 아카이브 분리는 하지 않았다 — 여유 ≈1.3 KB라 다음 경계 분리(`T-GR-00-LEDGER`)는 어느 PR보다
  먼저다.
- **미결 소유자 결정**: ADR-110 열린 결정 6건(BFF 경로 §14-10·geo 적재 방식 §14-8 + 재계획 수용/skip §14-19·키 정책
  §14-21(재적재 시점의 일)·회로차단·task 접두사·T-MAP-02 착수 순서) + 외부: geo가 실제로 odroid로 가는지(설계 §3.2
  조건 3·§14-12 — 미달이면 ADR-110 geo 절은 발효하지 않는다).

## 2026-10-13 — geo 릴리스 재지오코딩 설계: 브랜치 `docs/adr-109-geo-release-regeocode`

문서만 바뀐 PR(doc-only). geo 주소 데이터셋 릴리스 → Map 반영 설계(Track 1, 2차 적대 리뷰 2명 반영)를 ADR-109
(proposed, 미구현)와 `docs/etl/address-geocoding.md`(코딩용 상세)로 옮기고 구현 task `T-GR-00`~`08`을 열었다.
코드·마이그레이션·OpenAPI·CHANGELOG는 건드리지 않았다.

- **결정 요약(ADR-109).** 스탬프는 별도 표 `feature.feature_geocode_stamps`(outcome `called|geocoded|not_called`
  셋 — 좌표 유무가 아니라 호출자의 `geo_applied` run 신호로 정한다; price/notice asset은 스탬프 없음). 현재 토큰은
  run 단위(`kor_travel_geo_dataset` resource; 실패 시 None = 오늘과 동일, fail-to-current). 재지오코딩은 새 엔진이
  아니라 적재 경로의 unchanged-skip 보강: stale 분기 + 값 동일 무쓰기(**override 열은 비교에서 제외**) + 빈 답
  가드(행: 저장 값 non-NULL인데 새 값 전부 None → 무쓰기·무스탬프·finding; run: MOIS의 비율 가드 공통화) +
  geo-release run 한정 timeout 1회 재시도(ADR-108 예외). 기동은 센서 → 전용 job RunRequest(큐 아님; 큐 worker run이
  있으면 Skip). 계획 identity `plan_id` + `(data_token, plan_seq)`(A→B→A도 다시 돈다), 항목은
  `provider_dataset_operations` DB 정본 + KNPS dataset별 run_config, run_key에 `plan_seq/dataset/attempt_seq`, MOIS
  `budget_exhausted`는 done이 아니라 이어 달리기(`mois_load_continuation_decision` 재사용), 완료 분모에서 skipped
  dataset 제외, 완료 시 `same_sigungu` 링크 재동기화. 쿼터 민감 dataset(MOIS·datagokr·standard_data)은
  `source_records.raw_data` replay 모드. concierge payload 토큰은 run 토큰과 같을 때만 신뢰하고 Map
  `raw_payload_hash`에서는 제외. admin API는 admin 프로필만(PinVi admin 스냅샷 재vendor 선행), 슬래시 동사.
- **설계와 달리 쓴 것(head `c4d17343` 재확인).** `client/__init__.py` 인용을 `load_feature_bundles` :1058·
  `find_unchanged_active_source_entities` :1081·`load_feature_bundles_reobserving` :1104·`find_fresh_open_findings`
  :2654로 정정(설계는 1008/1031/1054/2604); `apply_kor_travel_geo_address`는 `admin_issues.py:576`(설계 :546-662);
  `sync_poi_cache_target_feature_links`는 `poi_cache_target_repo.py:862`(설계 :48); `AdminEvidence`는
  `dto/admin_evidence.py:72`(`reverse_attempted` :102). 나머지 file:line은 일치했다. ADR-108에는 "건별 재시도 없음"
  문장이 없어 재시도 예외 각주를 §2(선조회 실패 뒤 실시간 1회) 아래에 달았다. runbook
  `docs/runbooks/geo-release-regeocode.md`·admin 화면 체크리스트 행은 구현 PR(T-GR-07/06) 몫으로 미뤘다.
- **T-GR-00 원장 분리.** `tasks-acceptance.md` 216,950 B(상한 225,280)에서 `scripts/archive_task_ledger_section.py`로
  닫힌 절 7개(`T-VN-41F1D-D1`·`-E`·`T-VN-M01`·`T-VN-M04`·`T-VN-39`·`T-VN-DAGSTER-STORAGE`·`T-VN-QUOTA-ARITHMETIC`)를
  `docs/archive/tasks-acceptance-*.md`로 옮겼다(166,931 B; 매 이동 다중집합 검산 통과, 상대 링크가 있는 절 셋은
  도구가 거절해 두었다). T-GR 절 9개와 1차 리뷰 반영을 더해 **1차 리뷰 반영 뒤 실측** 185,189 B(§T-GR-00
  실측 줄과 같은 값). 설계 §11 T-GR-00이 요구한 잔여 바이트: `journal.md` 208,660 B(이 항목 포함, HEAD 202,686)·
  `tasks-done.md` 200,699 B — 둘 다 규약 §8 분리 기준(200 KB 근접)을 이미 넘어 PR-1 전 doc-only 분리를 선행
  조건으로 적었다(이 PR 범위 밖).
- **1차 적대 리뷰(2명) 반영.** (HIGH) `address-geocoding.md` §1 "현재 사실" 표를 변환 **함수** 단위로 다시 썼다 —
  `address_resolver=`를 받는 모듈은 7개(mois·standard_data·datagokr_file_data·krforest·krheritage·opinet·krex(미사용))이고
  khoa·krairport·mcst·krforest·datagokr·standard_data·opinet은 geo에서 코드+일부 필드만 취해 자기 `Address`를
  조립하며(knps·krforest route·krheritage만 geo `Address` 그대로), Dagster asset·큐 runner는 어느 것도 `address_resolver=`를
  넘기지 않는다(`assets.py` 0건 → asset 경로 `geo_applied.geocode`는 전부 False) — 호출자 표를 추가했다. (MED)
  outcome 판정에 평가 순서를 박았다(①스탬프 없음 ②MOIS evidence ③reverse 시도 → `called` ④geocode → `geocoded`
  ⑤`not_called`); concierge 좌표 행은 payload 코드를 썼어도 `called`(geo가 채운 빈칸이 비교 대상 — 설계 §6.3의
  `not_called` 정정). geo 의존 유도의 런타임 정본은 `core/feature_operation.py` `GEO_DEPENDENT_OPERATION_KEYS`
  상수 + pool lint AST 유도와의 집합 동등(`/detect`는 API 프로세스라 `kortravelmap.dagster`를 import할 수 없다).
  빈 답 비율 가드는 상수·계산만 공유하고 MOIS는 ADR-108 §3a-2 degraded(실패 아님) 유지. ADR-109 열린 결정에
  11(전용 job vs 큐)·12(`raw_payload_hash` 토큰 제외)·13(범위 밖 drift 백로그)을 더하고 8에 backfill 전 배포 Skip
  승인을 합쳤다; 결정별 영향 조문 표를 §T-GR-00에 두고 timeout 재시도 옵션을 T-GR-01 → T-GR-05로 옮겼다(T-GR-01은
  결정 비의존). 포인터 메모(ADR-108·mois etl·integration-map)에서 복제된 상수(상한 12·5 min·21,600 s)와 Skip 규칙
  본문을 빼 ADR-109 결정 5만 가리키게 했고, `address-geocoding.md` §5도 코딩용 이름만 남겼다. (LOW) README 표에
  ADR-107 행 추가, T-GR-07의 `rg` 조건을 append-only 원장 제외로 한정, runbook 배포 순서에 Manager concierge lane
  추가, `address.py:63-119`·`geocoding.py:935`·`definitions.py:113-120` 정정, 머리말의 head sha를 날짜 기준으로.
- **2차 리뷰(2명) 반영 — HIGH 2·MED 8·LOW 11, 기각 0.** (HIGH) 빈 답 가드(행)의 판정 집합에서 provider 원문
  `address.road/legal/admin`을 빼고 geo에서만 오는 집합 G(`sido_name/sigungu_name/admin_dong_code/road_name_code/zipcode`
  + payload 코드 없을 때의 두 코드 열)로 고정했다 — `legal`을 넣으면 krheritage(`:483`)·standard_data(`:296-297`)·
  concierge(`:548`)에서 가드가 영구히 열리지 않는다(T-GR-03 의도적 빨강 (1)에 세 픽스처 명시). MOIS replay 제외
  술어를 **스탬프** `reverse_outcome='not_called'`(unchanged CTE와 같은 술어, 별도 코드 없음)로 박았다 — `raw_data`
  기준이면 스탬프 없는 payload-bjd 행이 `coverage.unstamped`에 남아 완료 판정이 불가능해진다(열린 결정 8의
  선채움은 시간 단축용 "선택"으로 근거 정정). (MED) concierge 토큰 전달 경로(`kor_travel_concierge_items_to_bundles(…,
  current_data_token=)` additive kwarg, 호출처 `assets.py:1508`)를 T-GR-03에; 비-MOIS 비율 가드 분자·분모를
  `GeoCallStats.empty['reverse']`/`calls['reverse']`로 고정(T-GR-01, 현재는 전송 실패만 센다 `:1140-1146`);
  `data_token=None`인 `DatasetRef`도 fail-to-current(스탬프 쓰지도 덮지도 않음 — 두 토큰 열 NOT NULL, NULL 스탬프
  없음); journal·tasks-done 분리를 `T-GR-00-LEDGER`로 독립(T-GR-01 의존); ADR-108 각주·§4 행에 "열린 결정 6 승인 전 미적용"
  표기; timeout 재시도 판별자를 `trigger_kind=sensor`(MOIS 이어 달리기 run에도 붙는다, `mois_chunked_load.py:1071-1075`)
  에서 run 태그 `kor_travel_map.geo_release_plan_id`로 교체(RunRequest 태그에 추가); 값 동일 비교 "7개"→6개,
  `FeatureAddressSnapshot`(`:104-117`)에 `road_name_code`·`admin_dong_code` 추가를 T-GR-03에; pool lint AST 유도의
  현재 동작(키워드 존재만·asset 이름·같은 모듈만)을 사실대로 적고 T-GR-04가 별도 술어 `_passes_geo_callable`+job 매핑을
  더하도록(pool 술어 불변, 과결박 회피). (LOW) 판정 ②를 결과 기준(`geocode_attempted and bjd_code`)으로 ④와 통일하고
  geocode 실패 행은 `not_called`(열린 결정 1 부류); "chunk 단위 판정"→"행별 evidence, chunk commit bulk";
  `_reverse_geocoder(context)` 22→20곳; `has_active_feature_override` 정의 `:5147`/masking 호출 `:829-883`;
  `apply_provider_feature_field_patch`는 프로시저(`:677`); rest_areas `:533-`; `mois.py:685`/`:827`; API validation job
  (`offline_uploads.py:1503`, 적재 없음) 호출자 표 행; Manager lane 단계는 concierge ADR-49 소속 명시; T-GR-02의
  T-GR-03 결박 항목에 "(T-GR-03 뒤)" 표시; concierge payload 코드 행 `not_called`→`called` 변경을 ADR 결정 6(a)에
  "설계와 다른 점"으로 드러냄. 2차 반영 뒤 최종 실측: `tasks-acceptance.md` 189,627 B · `journal.md` ≈ 211.5 KB ·
  ADR-109 31,807 B · `address-geocoding.md` 31,218 B(전부 225,280 B 아래).
- **미결 소유자 결정**: ADR-109 "열린 결정" 13건(task 접두사 `T-GR-` 임시 포함).

## 2026-10-13 — 고속도로 돌발 job pool 고갈(prod run `bfd18ef5`): 브랜치 `fix/highway-incidents-pool`

- 증상: 2026-10-12 12:09Z 수동 첫 적재가 807초 뒤 실패. 4회 시도 모두 step 시작 30초 만에 `get_notice_snapshot_watermark`
  (lock 안 첫 DB 호출)에서 `QueuePool limit of size 1 overflow 0 reached, timeout 30`. 같은 캠페인의 주유소·휴게소 job은 성공.
- 원인: `provider_run_lock`이 advisory lock용 session으로 pool의 유일한 연결을 끝까지 쥔 채, 본문 client 호출이 각자 새
  session(두 번째 연결)을 열었다. 2026-10-05 ADR-107(acde37264)이 Dagster `kor_travel_map_client`를 `pool_size=1,
  max_overflow=0`으로 줄이면서 드러났다(그 전 기본 5+10에서는 조용했다). 2026-10-03 ADR-106이 주유소 asset의 lock을
  걷어내 lock을 쓰는 asset은 고속도로 돌발 하나만 남았다 — 그래서 그것만 죽었다. 공용 Dagster에서 이 job은 이 run 한 번뿐이고
  성공한 적이 없다. 10분 schedule(STOPPED)의 coalescing은 RunRequest 발행 여부만 정하므로 켜도 매 tick 같은 자리에서 죽는다.
  큐 경로는 client를 executor 연결에 결합하므로 영향 없다.
- 못 잡은 이유: asset 단위 테스트의 fake client lock은 연결을 쥐지 않았고, 통합 테스트는 기본 pool(5+10) engine을 썼다.
- 수정: lock을 잡은 연결에 client의 session factory를 lock 구간 동안 묶는다(객체 identity 유지 — guard identity 대조와
  `context.resources` 재조회 때문에 복사본은 안 된다). 전역 pool 상향은 하지 않았다 — ADR-107 runbook의 "DB 연결 1개" 계약을
  지키고, 본문은 원래 순차다. 같은 결함의 `cache_target_snapshot_gc` drain(prod 미실행, 잠복)도 같은 방식으로 고쳤다.
- 리뷰(PR #1314 @ffa0986e) 반영: H1 — GC drain 수정이 `tests/unit/test_cache_target_snapshot_gc_client.py` 3건을
  깼다(fake connection에 실제 `make_connection_session_factory`가 불림, 내 전체 unit run이 그 commit보다 먼저 시작됐다).
  테스트가 그 함수를 lock 연결일 때만 fake factory를 주도록 바꾸고 engine-bound factory는 호출되면 실패시켜 "lock 연결
  위에서만 session을 연다"를 단언한다. L3 — `connection_advisory_lock`/`discard_connection_on_failure`(infra): 획득·본문
  실패·해제 실패 때 lock 연결을 invalidate해(server가 lock을 푼다) lock을 쥔 채 pool로 돌아가지 않게 한다. 본문 실패 때는
  unlock을 시도하지 않아 원래 예외를 가리지 않는다. L4 — asset 통합 테스트를 Dagster runtime login으로. mutation 5종 RED.
- 남은 것(미수정): 큐 경로 strict 실패 증거(`feature_update_evidence_client`)는 executor 연결 밖에서 별도 commit하려고
  두 번째 연결을 요구한다 — 실패 경로에서만, 설계 결정이 필요하다.
- 검증(로컬 WSL + testcontainers PostGIS): 회귀 테스트 4종(단위 SQLite pool 1/0 2건, 통합 lock·asset 전체·GC drain) 모두
  수정 전 client에서 prod와 같은 TimeoutError로 RED 확인. dagster 패키지 679 passed, 관련 통합 executor·notice·advisory·GC
  통과, ruff·mypy --strict·lint-imports 통과.

## 2026-10-13 — weather 잔재 정리(ADR-104/105 후속): 브랜치 `chore/weather-remnant-cleanup`

소유자 승인 정리. 세 갈래 스캔이 live weather 경로는 없고 죽은 코드와 낡은 문서만 남았다고 봤다. PR·머지·배포는 하지 않았다.

- **지운 코드.** `core.ids.make_weather_value_key`·`WEATHER_VALUE_KEY_HASH_LENGTH`와 `core` 재수출,
  `tests/unit/test_ids_weather.py`(호출자 0, grep 전수). `core.scoring.SOURCE_PRIORITY`의 `python-kma-api`·
  `python-airkorea-api` 항목(읽는 곳은 `source_priority()` 하나, master 선정 후보에 그 provider feature가 402/403 뒤
  남지 않는다). `test_export_openapi.py`의 `_CURATED_*` 상수 다섯 개 — `"weather"` variant만 죽은 게 아니라 #1023이
  소비 테스트를 지운 뒤 블록 전체가 아무도 읽지 않았다. admin frontend `vworld-map-view`·`poi-cache-targets`의
  weather 라벨·색(`Record<string,string>` + `??` fallback이라 kind union과 무관; dedup-review 표는 이미 깨끗했다).
- **남긴 것(결정).** `FeatureKind.WEATHER`·kind CHECK, `WeatherValue` DTO·weather enum(API 재도입 방지 검사가 기댄다),
  provider alias, baseline/seed/legacy migration, frozen H35 SQL(`feature_repo`의 KMA 분기 포함), maki weather 아이콘,
  `SourceRole.WEATHER_CONTEXT`(migration 필요 → 백로그).
- **문서.** ADR-062·072 superseded by ADR-104/105(본문 유지, 머리 노트), README 색인. ADR-105의 소유 참조를 ADR-068
  (Feature UUID)에서 ADR-104로 정정. integration-map(service resource는 `/v1/features/batch`뿐), live 인수 runbook
  (owned ID 7개 = place 6 + price 1, `_owned_ids` 대조), ETL 배너 다섯, architecture·data-model(§8.2 제거 노트,
  `current_summary_runs` CHECK는 402 이후 `'price'`)·feature-model·public-views(`latest_weather` 행)·poi-cache·test-strategy.
  stale 주석: maki.ts·mois.py·client docstring·dto/bundle.py.
- **백로그.** `T-WX-VNEXT-FREEZE`(계약↔계약 대조라 지워진 weather 표를 못 잡는다 — 확인함), `T-WX-SOURCEROLE`,
  `T-WX-DTO`, 그리고 스캔 중 찾은 `T-WX-NOTICE-CLOSE`(`close_notice_features`의 production 호출자 0). Manager compose
  `KOR_TRAVEL_MAP_KMA_*` env 제거는 외부 추적(Manager 저장소에서 진행 중).
- 검증(로컬 WSL ext4 사본 + uv venv, n150은 IO 포화라 쓰지 않았다): ruff check(CI 경로) 통과, mypy --strict
  main 153·api 67·dagster 30 통과, lint-imports 4 kept, `check_prod_redaction` 통과. pytest: core import 단위 704 passed,
  `tests/lint` 303 passed(+ `test_sealed_runtime_tree_ship` 2건은 git이 필요해 실제 worktree에서 2 passed),
  `test_export_openapi.py` 11 passed. frontend: admin type-check·touched ESLint 0 경고·vitest 46파일 391 passed,
  map-marker-react vitest 4 passed·typecheck 통과. 최종 게이트는 GitHub CI다.
- 기존 결함(이번 변경과 무관, 기록만): `make_feature_id` doctest 기대값이 origin/main에서도 틀린다(CI는 doctest를
  돌리지 않는다). 로컬 ruff의 `format --check`는 손대지 않은 줄 다수에 diff를 낸다(CI format step은 `if: false`).
- **journal 분리(규약 §8).** 이 항목으로 `journal.md`가 225,613 bytes가 돼 CI의
  `test_every_docs_markdown_stays_within_readable_limit`(225,280)이 붉었다. 가장 오래된 2026-09-11~09-13 5개 절을
  `archive/journal-2026-09b.md`로 옮겼다(하단 인덱스 표 갱신, 현행 창 2026-09-14~). 옮긴 절에 상대 링크는 없다.
  바이트 보존 검산: 새 live 문서에서 인덱스 행·창 문구를 되돌리고 옮긴 블록을 제자리에 넣으면 원본과 byte 단위로 같다.

## 2026-10-12 — MOIS ADR-108 통합 테스트 resource 누락·직접 호출 tag 실패

- PR CI 통합 두 lane이 `test_dagster_assets_validate_coordinates_and_load_to_postgis` 하나로 붉었다 —
  `Dagster resource 없음: mois_load_plan`. 테스트가 asset을 `build_asset_context`로 직접 부르며 resource dict를
  손으로 만든다. 운영 경로는 빠질 수 없다: `definitions.py`가 resource를 등록하고 asset이
  `required_resource_keys`로 선언하며(누락이면 Dagster가 정의 load에서 거부) 큐 runner도 plan을 넣는다. 그래서
  기본값을 두지 않고 fixture에 운영 기본 plan(전 업종 = 월간 schedule 경로)을 넣었다. 다른 직접 호출은
  `test_mois_assets.py`(이미 plan 제공)뿐이고 scripts에는 없다.
- 그 뒤에 숨은 두 번째 실패: `build_asset_context`의 run id `EPHEMERAL`은 instance에 없어 결과 tag 쓰기가
  `DagsterRunNotFoundError`로 터진다(로컬 probe로 확인). `_tag_run_outcome`이 그 예외만 삼킨다 — 실제 run에서는
  나지 않는다. 진짜 `build_asset_context`로 부르는 단위 테스트를 더했다(mutation RED 확인).
- 검증(로컬): dagster MOIS·assets·definitions·resources·runner 138 passed, ruff·mypy strict. 통합은 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 OpenAPI admin 계약 재핀(description만)

- PR CI의 vnext 계약 테스트 2건이 붉었다 — `openapi.json`(full-admin)이 diff freeze baseline·T-VN-40 receipt와 달랐다.
  merge-base 대비 바뀐 것은 `POST /v1/ops/pipeline/requests`의 409·502·503 응답 description 세 줄뿐이다(schema·
  operation·status code 불변). user/service spec bytes는 그대로라 그 두 핀은 손대지 않았다.
- 생성 스크립트는 없다 — 2026-10-05 ADR-107 선례(acde37264)대로 `openapi-diff-v1.json` admin baseline sha256 +
  revisions 항목, `consumer-rollout-v1.json` T-VN-40 pending receipt의 `map_full_openapi_sha256` + blocking_reason
  문장, 테스트의 `ARTIFACT_SHA256` 두 상수를 갱신했다. 검증(로컬): vnext·contract 단위 135 passed.
- PinVi 측: `apps/api/tests/contract/kor-travel-map-openapi-admin.json`이 full-admin bytes를 vendor한다 — receipt가
  이미 pending(exact re-vendor 대기)이라 이번 bytes도 그 re-vendor에 포함된다. PinVi는 이 operation을 호출하지
  않는다(`/v1/ops/pipeline/*` 읽기만). PinVi 변경은 이 작업 범위 밖이다.

## 2026-10-12 — MOIS ADR-108 narrow 리뷰 MED 1·LOW 3 반영

- **MED-1.** run 전체 비율을 업종 degraded가 있어도 언제나 잰다. 무엇이든 degraded면 조회 50행 미만 업종의 빈 답에도
  표식을 쓰지 않는다 — 큰 업종 하나를 degraded로 만든 지역 장애가 작은 업종들에 남긴 빈 답이 30일 가려지지 않게.
- **L-1.** 다시 풀린 표식 닫기 실패는 `IntegrityFindingPersistenceError`로 정규화해 경고만 남긴다(`transaction_destroyed`면 올린다).
- **L-3.** 연속 degraded 사슬은 최근 500 run까지 보고, 그 안에서 완료 run에 닿지 못하면 degraded로 본다(닫힌 쪽).
- **L-4.** ADR-108 남는 위험에 "문턱 아래·5% 아래 지역 장애는 여전히 표식이 되어 최대 30일 조회되지 않는다"를 되살렸다.
- 검증(로컬): MOIS 적재기 72 passed. mutation 4종(표본 미달 업종 표식·run 전체 판정 생략·사슬 상한 열린 쪽·닫기 실패
  전파) 전부 RED. 통합 테스트는 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 리뷰 MED 1·LOW 3 반영

- **MED-1.** 표식이 문턱 초과(probe 통과) chunk와 degraded 업종에도 쓰여, 실제 지역 장애가 다음 run에서 표식으로 가려져
  봉인·sync 성공이 남고 overdue도 울리지 않았다. 표식은 run 끝에 한 번, degraded가 아닌 업종에서 문턱 초과가 없던 chunk의
  행에만 쓴다(run 전체 degraded면 쓰지 않는다). 그런 행은 표식 없이 매 run 다시 조회돼 geo가 회복될 때까지 degraded가
  지속된다. 연속 degraded 판정은 직전 완료 전체 run까지의 사슬 전체(`budget_exhausted` 포함)를 본다. ADR-108 정정.
- **LOW.** 로그 문구(degraded 업종은 표식 없이 다음 run이 다시 조회; off 모드 주석은 표식 30일 반영). 다시 풀린 행의 열린
  표식을 닫는다(SELECT 뒤 있을 때만 UPDATE — statement trigger hot row 보호). 표식 기록 실패가 `transaction_destroyed`면
  올린다.
- 검증(로컬): ruff·mypy strict·lint-imports·OpenAPI drift. MOIS 적재기 67 + 관련 498(전체 `tests/lint` 포함) + API 240 passed.
  mutation 5종(문턱 초과 chunk 표식·degraded 업종 표식·사슬을 완료 run만·표식 닫기 제거·destroyed 삼킴) 전부 RED — 앞의 둘은
  지역 장애 테스트에서 서로를 가려 각자 전용 테스트를 더했다. 통합 테스트(표식 닫기 SQL 포함)는 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 설계: 역지오코딩 불가 표식·조회 행 분모·연속 degraded·SLA

- **원인.** 해상·매립지·잘못된 TM 좌표는 정상 geo에서도 늘 빈 답이라 적재되지 않고 매 run 다시 조회돼, 정상 상태에서
  조회 창·비율을 지배하고 건강한 업종을 매달 degraded로 만든다(MED-1). degraded는 tag·로그로만 보였다(MED-2). 비율이
  미변경 행으로 희석됐다(LOW-1).
- **표식.** geo가 건강할 때(chunk가 장애 판정 없이 commit) 빈 답을 받은 행을 finding `mois_reverse_geocode_unresolvable`
  (info, dedupe key = slug::mng_no, payload.source_record_key = 현재 payload)로 남기고, 다음 run은 같은 payload의 열린 표식이
  30일 안이면 조회·적재하지 않는다(`mois_known_unresolvable`). 새 표 대신 finding 표를 재사용한 이유는 ADR-108 §3a-3.
- **분모.** degraded 비율은 조회한 행 기준(최소 50) — 업종·run 둘 다.
- **드러내기.** 직전 봉인 자격 전체 run도 degraded면 FAILURE(재시도 없음). migration 405가 MOIS bulk policy에 40일 SLA를
  심어 `/v1/ops/datasets` overdue로 보인다(운영자 값 보존). graph artifact는 생성기로, head-schema는 receipt CHECK만.
- **LOW.** 생성 route 주석 정정(seed의 MOIS refresh operation 넷 중 셋은 handler 없음), 죽은 `ensure_mois_source_sync_*`·
  `MOIS_SOURCE_PRECHECK_ERROR_RESPONSES`·`MoisSourceSyncRequired`·테스트(통합 1파일 포함) 제거 — 운영 화면 precheck는 유지.
  비율 설정 `> 0`. 기준점 서울시청 문서화. run 전체 판정 테스트.
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·graph `--check`·migration lint. 관련
  테스트 249 + 578(전체 `tests/lint` 포함) passed. mutation 5종(표식 무시·분모 원복·연속 실패 제거·run 판정 제거·표식 미기록)
  전부 RED. 표식 SQL 통합 테스트(`test_fresh_open_marker_matches_only_the_same_payload_and_ages_out`)와 migration 405는 로컬에서
  돌리지 않았다 — GitHub CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 델타 리뷰 MED 1·LOW 2 반영

- **MED-1 지역 geo 장애.** probe가 다른 지역 좌표로 통과해 한 시·도가 통째로 빠진 채 봉인될 수 있었다. 빈 답 행은 어느 모드에서도
  적재하지 않고(off 포함 — 빈 bjd commit은 같은 payload에서 영원히 건너뛰어진다), 업종(관측 200행+)·run 빈 답 비율이
  `KOR_TRAVEL_MAP_MOIS_GEOCODE_DEGRADED_RATIO`(기본 5%)를 넘거나 같은 업종에서 "문턱 초과 + probe 통과"가 3회면 degraded로
  표시한다 — 실패시키지 않고(영구 정지 재발 방지) 봉인·sync 성공을 남기지 않는다. tag `kor_travel_map.mois_load.geocode_degraded`,
  metadata `mois_geocode_degraded*`·`mois_reverse_geocode_empty`·`mois_geo_probes`·`mois_geo_probe_passes`, 경고 로그.
  probe는 고정 기준점과 마지막 좋은 좌표 둘 다 묻는다.
- **LOW.** 생성 route는 MOIS source sync precheck를 부르지 않는다(유일한 MOIS operation이 전용 job 전용이라 도달 불가) —
  409 설명·테스트에서 `MOIS_SOURCE_SYNC_REQUIRED` 제거, 우연히 MOIS dict로 문서화되던 502/503은 실제 원인(geo resolver)으로.
  실행된 scope 없이 `dedicated_job_only`가 섞인 빈 계획은 실패(PinVi target을 갱신됐다고 보고하지 않는다).
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·TS 타입(lock 7.13.0) 일치. 지역 장애(drop/off)·off 모드
  재시도·K회 판정·건강한 run 봉인 유지 테스트 포함 296 + 177 passed. mutation 5종(봉인 조건에서 degraded 무시·off 모드 commit·
  K회 판정 제거·probe 좌표 하나·빈 계획 any→all) 전부 RED.

## 2026-10-12 — MOIS ADR-108 델타 리뷰(PR #1312) HIGH 1·MED 1·LOW 4 반영

- **HIGH-1 geo 장애 오판.** drop 모드에서 바다·경계 좌표 행은 적재되지 않아 매 run 다시 변환되고, 재개 run의 조회를 지배해
  비율 판정이 영구 실패를 냈다. 비율이 문턱을 넘으면 `PrefetchingReverseGeocoder.probe_healthy`가 이 run에서 법정동코드를
  받은 마지막 좌표(없으면 서울시청 기준점)를 캐시 없이 다시 묻고, 그것도 빈 답일 때만 장애로 실패한다. 표식 표 대신 probe를
  고른 이유와 대가는 ADR-108 §3a.
- **MED-1 재시도 정체.** run tag에 실제 상한(`…budget_seconds`)과 loop 시작 때 남은 시간(`…budget_available_seconds`)을 남기고,
  0행 정지는 상한 절반 이상을 받은 run에만 적용한다. tag가 없거나 깨지면 이어 달린다.
- **LOW.** (a) 생성 route 409 설명을 실제 409 전부로(dict 병합이 MOIS precheck 설명으로 덮던 것; run-now 설명은 원복),
  OpenAPI·admin 타입은 `openapi-typescript@7.13.0`(lock 버전)로 재생성. (b) plan 선행조건은 큐가 실행할 membership만.
  (c) `policy_disabled`가 먼저, 실패는 건너뛴 것이 전부 `dedicated_job_only`일 때만. (d) `_run_clock_start`가 비숫자·NaN·
  무한·0 이하·미래 start_time을 무시.
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·TS 타입 재생성 일치. 테스트 84(새·수정)
  + 377(API 관련) + 163(dagster·lint 관련) passed. mutation 5종(probe 제거·budget tag 무시·any/all·guard 필터 제거·
  start_time 검사 제거) 전부 RED.

## 2026-10-12 — MOIS ADR-108 적대 리뷰 MED 4건·LOW 반영: 브랜치 `feat/mois-chunked-resumable-load`

- **MED-1 소실 하한.** chunk마다 재던 drop 비율 하한을 끄고(`enforce_loss_guard=False`) 업종 누적·최소 표본 200행에서
  데이터 무효(`missing_address`)만 판정한다. 지오코더 원인(`reverse_geocode_failed`)은 따로 세고(다음 run이 다시 변환),
  geo가 최근 20건+ 중 80%+를 빈 답으로 내면 chunk 적재 전 upstream 장애로 실패한다(`PrefetchingReverseGeocoder`의
  최근 창 50건).
- **MED-2 재관측 충돌.** `ProviderEntityReobservationConflict`를 잡아 그 chunk만 run 안에서 최대 2회 다시 확인·적재.
- **MED-3 시간 기준.** run record `start_time`부터 재고, `min(설정, dagster/max_runtime tag - 30분)`. settings 최대값과
  job run 상한의 관계를 테스트로 고정.
- **MED-4 큐.** 정본 `core.feature_operation.DEDICATED_JOB_ONLY_OPERATION_KEYS`. MOIS뿐인 enqueue는 409
  `PROVIDER_DEDICATED_JOB_ONLY`, 섞인 요청은 실행 계획에서 빼고 `done` + error_message, 실행할 것이 MOIS뿐이면
  `failed` + cache target event `error_code=PROVIDER_DEDICATED_JOB_ONLY`(기존 실패 어휘). OpenAPI 409 설명·admin 타입 갱신.
  router 테스트의 큐 sample operation을 MOIS에서 khoa로 바꿨다(MOIS는 이제 큐로 받지 않는다).
- **LOW.** 이어 달리기: 미종료 run 재확인, 0행 전진이면 정지. sync 성공 = 봉인 조건(`authoritative`).
- 검증(로컬 py3.13 venv, n150 미사용): ruff·mypy strict(core/api/dagster)·lint-imports 통과. 관련 unit/api/dagster/lint
  테스트 MOIS 34·executor+provider+prefetch 52·dagster 관련 109·API router 163·API 관련 249·lint 175 passed.
  mutation 8건(chunk 하한 재활성·충돌 재시도 제거·step 시계·장애 판정 제거·0행 정지 제거·활성 run 재확인 제거 등) 전부 RED.
  통합 테스트는 돌리지 않았다(GitHub CI가 게이트).

## 2026-10-12 — MOIS 재개형 chunk commit 적재(ADR-108): 브랜치 `feat/mois-chunked-resumable-load`

소유자가 2026-10-12에 MOIS 적재 재구성을 승인했다(prod `1a3c4673` 읽기 전용 조사: 42업종 약 98만 행, 순차 역지오코딩
약 35시간 vs run 상한 6시간, 단일 transaction, `/tmp` 원천 SQLite). PR·머지·배포·prod 데이터 실행은 하지 않았다.

- **재개 키 = 원천 내용.** chunk(업종 안 최대 500행)마다 `(slug::mng_no, raw_payload_hash)`를 지오코딩 **전에** 계산해
  "head가 같은 payload이고 primary feature가 active인가"를 묻는다(`find_unchanged_active_source_entities`). 그 행은
  `load_bundle`이 관측 시각 말고 아무것도 바꾸지 않는 행이므로 재관측만 하고(`reobserve_unchanged_source_entities`,
  Phase A marker `synced_at` 기준 — 같은 snapshot 재실행은 다시 쓰지 않는다), 나머지만 변환·적재한다. 둘은 chunk
  transaction 하나(`load_feature_bundles_reobserving`). 새 표·cursor·마이그레이션 없음 — `load_bundle`이 읽는 표·열만 읽는다.
- **지오코딩.** kor-travel-geo에 batch endpoint가 없다(geo origin/main `02a3c2e`: `/v2/reverse`·`/v2/geocode` 단건).
  `PrefetchingReverseGeocoder`가 chunk 좌표를 중복 없이 bounded 동시성(`KOR_TRAVEL_MAP_MOIS_GEOCODE_CONCURRENCY`, 기본 2)으로
  선조회하고 run 수명 LRU(5만)에 둔다. 원천 `legal_dong_code`가 있는 행·이미 적재된 행은 조회하지 않는다. 선조회 실패는
  캐시하지 않는다(변환이 한 번 더 시도, 그래도 실패면 예외).
- **run 크기.** `KOR_TRAVEL_MAP_MOIS_LOAD_RUN_BUDGET_SECONDS`(기본 4시간)에서 새 chunk 시작을 멈추고 tag
  `kor_travel_map.mois_load.outcome=budget_exhausted`. `feature_place_mois_licenses_continuation_sensor`(STOPPED)가 같은
  run_config로 잇는다. retry 1회·5분. 월간 schedule은 활성 run과 합친다. 봉인·sync 성공은 전 업종을 한 run에서 끝까지 본
  run만. 큐 runner는 MOIS를 `dedicated_job_only`로 건너뛴다(큐는 쓰기를 한 transaction에 묶는다).
- **원천 영속.** 이미지가 `/opt/dagster/state/mois`(appuser)를 만들고 기본 경로로 둔다. standalone compose volume도 그리로.
  운영은 Manager 브랜치 `feat/map-mois-source-volume`(internal named volume, 경로·target 같은 변수).
- **검증 경로.** run_config `resources.mois_load_plan.config.{service_slugs, run_budget_seconds}`. 절차는
  `docs/etl/mois-license-feature-etl.md` §13.2.
- 테스트(n150, python:3.13, `-c docker/constraints-dagster.txt`, CI 세션 경계 그대로):
  - 정적: `ruff check`(CI 범위) 통과, `mypy --strict` core 153·api 67·dagster 30 파일 이슈 0, `lint-imports` 4 kept.
  - A unit+lint: 3056 passed / 26 failed — 같은 컨테이너의 main(`bcbd14c2`) 기준선과 실패 집합 동일(docker CLI·node·git 소유권
    환경 25건) + `test_orchestrator_guardian_lock_is_not_inherited_by_external_child` 1건(flock/SIGKILL 타이밍 — 부하 중 같은
    컨테이너에서 2/3 실패, 별도 컨테이너에서 4/4 통과, main도 통과; MOIS 무관).
  - B api: 1236 passed, coverage 78.1%(≥70). C dagster: 626 passed·4 skipped, coverage 82.9%(≥80), `mois_chunked_load.py` 95%.
  - 새 통합 `test_mois_resumable_load_repo.py`: 실 PostGIS 4 passed. 전체 D는 n150 IO 포화(`/proc/pressure/io` full avg300 ≈44%,
    `map-load-phase14` 적재 중)로 PostGIS testcontainer가 120초 안에 뜨지 못해 setup error — 두 번. 부하를 더하지 않으려 중단하고
    IO가 가라앉으면 도는 user unit `mois-gate-d-ready`로 넘겼다(로그 `~/mois-gate-logs/d3-*`). GitHub CI가 정본 게이트다.
  - 실제 python-mois-api(3cdee09)를 깐 상태에서 fetcher 업종 선택 테스트 포함 4 passed(CI는 `providers` extra를 깔지 않아 skip).
  - mutation(일부러 깨기): 재개 건너뛰기 제거 → 4건 RED, 선조회 동시성 1로 → 1건 RED, 시간 상한 제거 → 3건 RED. 모두 원복.

## 2026-10-08 — map-marker-react `roadblock`·`warning` 글리프: 브랜치 `feat/marker-roadblock-symbol`

- **변경.** `packages/map-marker-react/src/maki.ts`의 `MAKI_GLYPH`에 `roadblock`(🚧 U+1F6A7, `construction`과 같은
  글리프 — Unicode 바리케이드는 그것 하나다)과 `warning`(⚠, `alert`와 같음)을 더했다. krex 교통 공지와 krforest_safety
  산사태 예보가 첫 글자 배지("R"·"W")로 떨어지고 있었다. 이 패키지의 "심볼"은 SVG가 아니라 Unicode 글리프 표다.
- **누락 조사.** category catalog 58종은 T-017 gate가 이미 막고 있어 누락 0. catalog 밖 provider 상수 중 표에 없던 것은
  위 둘뿐이었다. 그 경로를 지키는 검사가 없어 `test_provider_direct_marker_icons_are_renderable_by_ts`를 더했다(상수
  값 자체를 import해 대조).
- **CI 사각.** 패키지 자체 vitest(`src/maki.test.ts`)는 admin vitest 범위 밖이라 어떤 워크플로도 돌리지 않았다.
  `frontend.yml`에 `map-marker-react unit tests + typecheck` 단계를 넣고 `scripts/verify-all-gates.sh`에도 미러링했다.
- **테스트(n150, node:22.23.1).** marker vitest 4 passed·typecheck 0; admin vitest 46 files/391 passed(첫 실행 1회 exit 1 —
  출력이 잘려 원인 미확인, 재실행 2회 green), admin type-check·lint 0, next build(CI env) 성공. Python: drift 2파일 6 passed,
  새 provider-direct 검사는 `maki.ts`에서 두 키를 지우면 `['roadblock', 'warning']`으로 RED; workflow·mirror 포함 38 passed;
  ruff 통과. npm 게시 없음(ADR-043). kor-travel-transport의 vendored 사본도 같은 내용으로 다시 복사했다.

## 2026-10-07 — entrypoint 봉인에서 `api grpc` 제거: 브랜치 `chore/entrypoint-drop-api-grpc`

- **변경.** `docker/dagster-entrypoint.sh`의 production `/usr/local/bin/dagster` 봉인이 하위 명령 `code-server start`
  하나만 받는다(9-argv, loopback `-h`, 숫자 `-p`, 고정 `-m` 그대로). 최상위 `api grpc`는 location reload를 무시해서
  전환용으로만 남아 있었고, Manager compose(#1295)·standalone compose(#1304)가 모두 옮겨 쓰는 곳이 없다. 거부 문구는
  다른 모양과 같다. local-dev의 preflight 분기에서도 `api grpc`를 뺐다.
- **테스트.** `test_dagster_production_code_server_rejects_other_shapes`에 `api grpc`를 넣어 n150에서 먼저 RED(1 failed)를
  보고 고쳤다. accepts는 `code-server start` 정확한 argv 하나, runtime-preflight 목록에서 `api grpc` 행을 뺐다.
  n150: `ruff check`(CI 범위) 통과, `test_docker_dagster_runtime.py`+code-location+constraints 332 passed / 14 failed —
  실패 14건은 main(8f9dd1cb) 기준선과 같은 집합(frontend dotenv validator·local admin stack 등 환경 의존).
- **실측(throwaway, 운영 Map code-server 이미지 `197597501a0b`, rev 1a3c467).** 새 entrypoint를 읽기전용 마운트:
  `api grpc` → rc=1 + 봉인 문구, `code-server start` → 35초 안에 `ListRepositories` 610 bytes(정상 응답, 오류 없음).
  proxy의 자식 `python -m dagster api grpc --socket …`은 entrypoint를 지나지 않아 영향이 없음을 프로세스 목록으로 확인.
  이미지 자체 entrypoint는 `api grpc`를 여전히 받는다(대조). 컨테이너·임시 파일 정리 완료.
- **배포.** 하지 않았다. 다음 Map pinned-pair 회전 때 반영되며, 운영은 이미 `code-server start`라 안전하다.

## 2026-10-06 — Map·PinVi 공통 Dagster 구현·재구축·live·머지 완료

[Common #28](https://github.com/digitie/kor-travel-common/pull/28) → [Map #1303](https://github.com/digitie/kor-travel-map/pull/1303) → [PinVi #576](https://github.com/digitie/pinvi/pull/576) 순서로 병합했다. Common·Map은 merge commit, PinVi는 main ruleset의 squash-only·linear history 정책에 따라 squash로 병합했다. PinVi 재구축 원본0058369와 검증 HEAD92d0f40는 remote tags codex/pinvi-map-runtime-20261006·codex/pinvi-map-reviewed-20261006 및 유지한 feature branch에 원본 이력을 보존했다. 저장소 설정은 변경하지 않았다. 최종 문서 포함 HEAD의 필수 CI, Common·Map main ancestry와 PinVi 보존 참조, 병합 tree 일치를 확인했다. 실제 paired 재구축, 두 독립 FULL 제품 리뷰·가이드 리뷰·최종 문서 리뷰, Chromium/Firefox×Map/PinVi live UI4건·8캡처, ACL40·D1 11건·D2 normal/attempt0·소유 fixture 정리·잔존0 검증을 완료했다.

머지 후 운영 API/UI/Dagster 여섯 이미지의 healthy 상태·설치 코드·배포 source·committed transaction이 기존 성공 증거와 같음을 실제 read-only 재확인했다. 최종 제품 Common a960bdb/Map1a3c467/PinVi0058369에 문서만 추가됐으며 재구축·장애 주입을 머지 HEAD에서 새로 실행한 것으로 집계하지 않는다. 격리 Map native raise/crash/stall·동시 정상 run·수동 복구는 관련 설치 코드/버전 불변 범위에 한정한다. 공유 운영 worker 장애 주입·운영 RSS 감소율은 미실측이다.

이 요청의 T-COMMON-DAGSTER는 완료 원장으로 이동한다. 기존 외부 transport/HAProxy 및 다른 미완료 task는 유지한다. 다음 작업은 기존 열린 backlog의 우선순위를 따른다.

[머지 후 실제 상태 증거](reviews/common-dagster-2026-10-05/evidence/final-postmerge-runtime-attestation.json), [가이드·실패·리뷰·수용 이력](reviews/common-dagster-2026-10-05/README.md). 아래 문단은 각 작성 시점의 이력이며 이 절이 최신 상태다.

## 2026-10-06 — Map·PinVi 공통 Dagster 실제 재구축·live 수용 완료

Common a960bdb, Map 1a3c467, PinVi 0058369의 제품113파일 두 독립 FULL 리뷰와 가이드 리뷰를 통과했다. 공용 Python은 bounded HTTP·경량 child health·실행 복구 정책을 제공하며 앱의 operation/lease/claim·비멱등 쓰기 계약을 유지한다. 요청별 응답4MiB/10초와 정리50ms, DB pool/step 제한·100개 batch를 적용했다. Map tick 조회의 오래된 batch history 정렬 지연은 상태 조건을 명시하여 native indexed LIMIT 경로로 줄였고 실제 summary/UI 복구를 확인했다.

운영 paired 재구축과 설치 source·관련 Common bytes·실제 이미지 identity·여섯 서비스 healthy를 검증했다. Chromium/Firefox×Map/PinVi 실제 UI4건과 캡처8개를 직접 확인했다. ACL40·D1 11건·D2 정상 수용/validator·소유 fixture purge1/7·잔존0/ACTIVE없음/BLOCKED없음까지 통과했다. Common의 ESM export를 읽기 위한 type=module은 별도 테스트 이미지 package.json에만 추가하고 실제 마지막 layer/semantic delta를 증명했다. 앞선 모든 실패·초기 BLOCK와 수정 후 PASS 원문은 보존한다.

격리 native Dagster에서 실제 raise·worker crash·stall/timeout 뒤 수동 재시도와 동시 정상 job을 확인했다. 최종 Map 운영 Dagster 이미지의 관련 설치 코드와 버전이 이전 격리 이미지와 같은지, 실제 최종 이미지 ID가 배포 기록과 맞는지 독립 검증했다. 이 결과는 해당 불변 코드 범위에 한정해 이어받는다. 공유 운영 DB의 worker 장애 주입이나 운영 RSS 감소율 실측으로 설명하지 않는다. 유한 응답·batch·동시성 구조와 합성 메모리 측정은 운영 RSS와 구분한다. 기존 인간 dirty checkout·외부 transport/HAProxy 후속은 보존한다.

도구 제한: Map own CodeGraph의 최종 sync/status는 NTFS disk I/O error로 완료하지 못했다. 기존 격리 인덱스와 SQLite immutable quick_check 정상은 보존했으며 원본 인덱스/프로세스의 강제 정리는 하지 않았다. 마지막 제품 변경은 tick 조회 조건과 C7 테스트 Docker COPY 순서이며 공개 Python/DTO 계약은 유지한다.

다음 한 작업은 문서 포함 exact HEAD CI 통과 후 Common #28 → Map #1303 → PinVi #576 순서로 merge commit 병합하는 것이다. 제품 Git pin의 ancestry를 보존한다. 이 절이 현재 상태이며 아래의 진행 중/NOT_RUN 문단은 이전 시점의 이력이다.

[실제 검증·리뷰 원문과 실패 이력](reviews/common-dagster-2026-10-05/README.md), [공통 적용 가이드](runbooks/common-dagster.md).

# journal.md — 작업 일지 (역시간순)

## 2026-10-05 — child health의 reserved metadata marker 차단 채택

Common 경량 probe의 독립 리뷰 반례(pointer/library map의 reserved serdes marker)를 차단하고 정상 default repository __repository__를 허용하는 profile을 API·Dagster 동일 Git revision으로 채택한다. unsupported stateful/custom metadata는 fail-closed하며 가이드에 지원 경계를 명시했다. 두 독립 재리뷰·현재 CI·실제 PinVi/Map paired 재구축/live는 아직 진행 중이다.

## 2026-10-05 — child health의 nested metadata 검증 채택

Common 경량 probe의 독립 리뷰 반례(null/미등록 pointer, 잘못된 executable/entry point 타입)를 반영한 표준 module/file/package profile을 API·Dagster 동일 Git revision으로 채택한다. unsupported stateful/custom metadata는 fail-closed하며 가이드에 지원 경계를 명시했다. 두 독립 재리뷰·현재 CI·실제 PinVi/Map paired 재구축/live는 아직 진행 중이다.

## 2026-10-05 — standalone 자식 저장소 응답 fail-closed 보강

최신 main #1304를 반영한 두 독립 리뷰에서 한 리뷰어가 빈 protobuf/잘못된 JSON이 substring 건강 점검을 통과하는 P2를 실제 reply fixture로 재현했다. 기존 PASS와 BLOCK 원문을 모두 보존한다. Common의 경량 `dagster_health`를 사용하여 proxy 뒤 자식의 정상 class·symbol schema와 wire/JSON을 검증한다. Dagster 전체 import를 피하며 각 RPC 4초·수신 4MiB·channel 정리를 유지한다. standalone은 건강 판정만 하므로 unhealthy 자체를 자동 재시작으로 설명하지 않는다. 새 source pin·두 리뷰·CI·운영 재구축/live는 아직 미완료다.

## 2026-10-05 — 요청 단위 Dagster client의 PostGIS fixture 정렬

Map CI의 glibc·alpine 통합 lane에서 동일한 projection 테스트 한 건이 실패했다. 앱 전역 client 주입을 제거한 뒤 기존 fixture가 실제 연결로 빠진 것이 원인이다. 두 schedule fixture에 요청마다 새 MockTransport client를 주입하고 실제 middleware의 정리를 유지했다. catalog 회귀도 schedule source가 `ok`인지 단언하여 묵시적 degrade를 막는다. 운영 Python·UI 코드는 이전 고정 후보와 동일하다. 실제 PostGIS 관련 22개 검사를 통과했으며 전체 CI를 다시 확인한다.

## 2026-10-05 — Map·PinVi 공통 Dagster 보강 (진행 중)

ADR-107과 [적용·복구 가이드](runbooks/common-dagster.md)에 따라 공통 Python HTTP/Dagster·로그인·메뉴·대시보드를 채택했다. 요청별 연결·응답/시간 상한·활성 run 별도 조회·step/DB 연결/100개 batch를 적용한다. 쓰기 run 자동 복제 없이 기존 operation/lease/claim 복구 계약을 유지한다. [검증 기록](reviews/common-dagster-2026-10-05/README.md)의 고정 후보 2인 리뷰·운영 재구축·live·CI·merge를 완료해야 한다. 원래 인간 dirty checkout은 보존했다.

적대적 원본 리뷰의 실패 상세·event cursor 회귀와 손상 Repository의 정상 빈 snapshot 오인을 보강했다. 선택한 run만 상세 조회하며 Docker deps에 고정 Common vendor를 복사한다. UI 390/API shape 24/strict mypy 96 및 production Next build PASS. React Doctor의 불필요한 mapper export를 제거했다. 후속 리뷰의 repository 소속 불일치도 selector identity와 비교하여 fail-closed하고 다른 location의 행을 제거했다. 정상 empty와 외부 name/location을 실제 HTTP 응답 fixture로 구분한다. 검색으로 선택한 run의 행이 숨겨져도 상세에 job/run identity·상태·시간 상한을 명시하여 다른 작업의 실패로 오인하지 않도록 보강했다. 후속 immutable 2인 FULL 리뷰·exact CI·실제 paired 재구축·live gate는 아직 미완료다.

## 2026-10-05 — standalone compose code-server를 `code-server start`로: 브랜치 `chore/standalone-compose-code-server-start`

- **변경.** `docker-compose.yml`의 `dagster-code-server` command가 `dagster api grpc`에서 운영(Manager)과 같은
  `dagster code-server start -h 127.0.0.1 -p ${PORT} -m kortravelmap.dagster.definitions`가 됐다(#1295 봉인이 받는 모양).
  `api grpc`는 location reload를 무시해서 import 때 읽는 schedule override가 반영되지 않는다. host·external-infra
  overlay는 command를 건드리지 않는다.
- **healthcheck.** 옛 probe(`DagsterApi` health → SERVING)는 `code-server start`에서는 proxy만 본다 — proxy health는 자식이
  load error여도 SERVING이다. proxy health 뒤 자식에 전달되는 `ListRepositories`를 raw bytes로 불러
  `SerializableErrorInfo`면 실패한다(dagster import 없음, 4초 deadline 둘). Manager probe의 PID 1 종료·orphan run 정리는
  standalone에 옮기지 않았다(판정만).
- **테스트.** `test_standalone_compose_code_server_is_reloadable_and_sealed`: compose argv 정확 일치 + 그 argv(포트 기본값
  풀어)를 실제 entrypoint 봉인에 넣어 통과 + probe가 `ListRepositories`/`SerializableErrorInfo`를 본다. dagster 프로세스
  서비스 유도 marker를 `dagster api grpc` → `dagster code-server start`로 바꿨다. 먼저 RED(2 failed: argv 불일치,
  유도 서비스 2개) 확인 후 GREEN.
- **n150 증거.** 영향 파일 3개(`test_docker_dagster_runtime.py`·`test_c7_prod_runtime.py`·
  `test_n150_repin_derives_dagster_services.py`) 368 통과/13 실패 — 13건은 main과 같은 집합(n150 checkout에 frontend
  node_modules 없음). CI 범위 ruff 통과. `docker compose config` base·host·external-infra 셋 다 `code-server start`로 렌더.
  live Map dagster 이미지로 일회용 컨테이너(host network, 빈 loopback 포트): 정상 모듈은 compose probe rc=0(~40초),
  `dagster api grpc-health-check` rc=0, `ListRepositories` 응답이 `ListRepositoriesResponse`. 없는 모듈은 compose probe
  rc=1인데 proxy health는 SERVING, `grpc-health-check`는 rc=0 — CLI probe로는 load error를 못 잡는다는 실측. 컨테이너는 치웠다.
- **남은 것.** entrypoint 봉인에서 `api grpc` 제거(이제 어느 compose도 쓰지 않는다).

## 2026-10-05 — 인계 문서와 n150 보조 스크립트를 저장소에 남김

- 세션 교대(다음 에이전트: Codex)를 위해 `docs/handoff/2026-10-05-shared-dagster-handoff.md`에 상태·진행 중 작업·
  TODO 7개·n150 운영 절차·실제로 밟은 함정을 정리했다. 운영 값은 넣지 않았다(#508).
- `docs/handoff/n150-scripts/`: `preflight.sh`(변경 전 사전 점검), `guarded-rb.sh`(실패 시 즉시 docker start하는
  pinned rebuild), `transport-deploy-unit.sh`, `weather-deploy.sh`, `dagster-job-status.py`. n150 `~/`에 실제 호스트가
  든 사본이 있다.
- 2026-10-03~04 사고 요약: 옛 메타DB 차단 뒤 rebuild가 옛 storage migrate에서 실패(→ Manager #459), 부하 cold start가
  healthcheck 창 초과(→ #460), C6c smoke 첫 요청 timeout(→ #461), D2 fixture가 실패 경로 정리를 거부(→ #1297).

## 2026-10-04 — D2 실패 run이 `cleanup-failed`로 굳던 결함: 브랜치 `fix/d2-fixture-restored-audit`

- **무엇이 일어났나.** D2(run `live-20261004102457-782ce6e6b79b`, a68c2b7d)의 main spec이 create 응답을 받지 못해
  실패했다. create 트랜잭션은 10:36:31.7Z에 시작해 약 10:37:01.4Z에 커밋됐다(약 30초). API access log에는 그 POST가
  없다 — 응답 전에 클라이언트가 떠났다. spec `finally`가 Feature를 `:cleanup`으로 은퇴시켰고, helper api-audit은
  완주 사슬과 `:retire` lifecycle override만 받아 `API-owned field override 소유권이 다릅니다`로 죽었다 → BLOCKED
  `cleanup-failed`(원래 `test-failed-restored`). 같은 감사를 부르는 `recover`와 helper `purge`도 구조적으로 통과 불가였다.
  #1296(transport consumer)은 무관하다 — field override·admin create 경로를 건드리지 않는다. 동시 Map Dagster run도 없었다.
- **고침.** lifecycle override의 reason을 **실제로 은퇴시킨 전이의 reason**(`:retire`|`:cleanup`)에 결박했다.
  `api-audit --expect complete|restored`: 러너가 spec 실패 시와 `recover`에서 `restored`를 넘긴다(생략=complete라
  clone lane은 그대로). 복구 증거 검증기는 restored 모양을 받고 purge `purged`를 감사한 개수와 대조한다.
  `feature_uuids` 길이를 `counts.features`에 결박했다(적대 리뷰 LOW1).
- **테스트.** `tests/unit/test_d2_api_owned_restored_audit.py`는 prod에 남은 행을 그대로 옮겼다. 고치기 전 a68c2b7d 코드가
  같은 행에 prod와 똑같은 오류를 낸다는 것을 n150에서 재현했고, 새 테스트는 먼저 빨갛게 확인했다.
- **~30초 절단은 저장소 밖이다.** Playwright(`page.evaluate` fetch 무제한, test 5분), Next proxy route(timeout 없음,
  abort signal만 전달), API(요청 timeout 없음) 어디에도 30초가 없다. D2는 `https://<map-ui-host>`로 가고
  n150에는 443 listener가 없다 → OPNsense HAProxy edge. H27은 `timeout tunnel 1h`만 바꿨으므로 기본 `timeout server`
  30초가 남아 있을 가능성이 가장 높다(라우터 설정은 직접 읽지 못했다 — 추정).
- **현재 BLOCKED 정리.** a68c2b7d로는 lane 복구가 불가능하므로 n150 `~/d2-adjudicate-782ce6e6.sh`(0600, 미실행)에
  판정 스크립트를 두었다: 잔여물 정확 대조 → `feature.purge_manual_feature`(감사되는 purge 명령) → 정본
  `scripts/n150/adjudicate.sh` → 운영자 메모·run dir 사본 보관. `--dry-run`이 먼저다.

## 2026-10-04 — delta 리뷰 반영: 같은 브랜치 `fix/transport-consumer-lows`

- **MED 회귀.** `_TransportTransientStatus`(HTTP 층 재시도를 다 쓴 502/504)가 부모의 `retryable=False`를 물려받아
  새 경계가 짧은 transport 재기동을 terminal로 만들었다(하루치 유가 손실). `retryable=True`·`failure_kind=
  transport_transient_status`. 다른 하위 클래스(NotCurrent True, Malformed·Empty·Hidden·ContractError False)는 의도대로다.
  경계 테스트에 503·502를 "재시도가 남아야 하는" 경우로 넣었다.
- **LOW** 경계의 원인 추적은 `__cause__`만 따른다(`__context__`는 처리 중 난 다른 실패).
- **LOW** locator 경고 logger(`kortravelmap.infra.feature_repo`)를 `docker/dagster.yaml` `managed_python_loggers`에
  더했다(lint로 결박). 공용 Dagster plane에서는 instance 설정이 Manager 쪽이므로 그쪽 목록에도 있어야 run 로그에 보인다.

## 2026-10-04 — transport 소비 후속 적대 리뷰 반영: 같은 브랜치 `fix/transport-consumer-lows`

- **MED locator 한 행이 전체를 죽였다.** `list_primary_place_locator`가 검증 없는 코드 칼럼으로 엄격한 `Address`를
  만들어, `manual_override` 하나(시군구만·오타)가 목록 전체를 `ValidationError`로 실패시켰다 — 모든 가격 run이
  실패하고 override가 provider 보정을 가리므로 저절로 낫지 않는다. 행마다 만들고 걸리면 빈 주소 + feature id 경고.
- **LOW 2·3 `retryable`이 행동을 바꾸지 않았다.** `FEATURE_LOAD_RETRY_POLICY`는 쿼터 말고 모든 예외를 다시 돈다.
  asset 경계가 `retryable=False` transport 실패(hidden·empty·contract·malformed)를 쿼터 소진과 같은 방식으로
  `Failure(allow_retries=False)`로 바꾼다(`raise_terminal_if_transport_unrecoverable`). 503만 재시도로 남는다.
  테스트는 `run_tracked_feature_asset`를 실제로 돌린다(두 갈래 × 네 종류).
- **LOW 6** 바깥 run 예산이 열린 채 다른 예산을 넘기면 `ValueError`(종전은 조용히 무시).
- **LOW 7** 감사 기록 실패·timeout·비-2xx는 `console.warn`(이벤트 종류·결과·오류 이름/HTTP 상태만, 비밀값 없음).
  테스트는 `vi.restoreAllMocks()`로 spy를 되돌린다.
- **LOW 5(수용, 기록).** 가격 feature가 place의 시군구 코드를 갖게 되어 시군구 범위 refresh가 이제 가격
  dataset도 포함한다. 첫 적재는 기존 가격 feature 주소를 한 번 고쳐 쓴다.
- **큐 경로 503(결정: 유지).** 큐 run의 실패한 update request는 원인과 무관하게 그 request로 끝나고 다시 큐에
  넣지 않는다. 다음 schedule/request가 다시 돈다. dagster README·ADR-106에 적었다.

## 2026-10-04 — transport 소비 후속(적대 리뷰 잔여 Low 다섯): 브랜치 `fix/transport-consumer-lows`

- **재시도 예산은 run 하나에 하나.** ADR-106 리뷰 M8은 "run 예산 공유"라고 적었지만 실제로는 fetcher 호출마다
  `RetryBudget()`을 새로 만들었다. 큐 run 하나는 scope 여러 개(주유소·휴게소·돌발·공항)를 돌므로 transport가
  내려가 있으면 scope 수 × 예산만큼 재시도했다. `upstream_retry.sharing_run_retry_budget()`(ContextVar)를
  asset step(`run_tracked_feature_asset`)·큐 op(`execute_feature_update_request`)·scope runner가 열고, 안쪽은 바깥
  예산을 그대로 쓴다. 테스트: 예산 1에서 세 fetcher가 연결 오류면 요청 4건(종전 6건).
- **failure_kind 분류.** 503·`collection` 어긋남(`transport_not_current`)은 `retryable=True`인 step 실패다 — HTTP
  층에서 바로 다시 부르지 않고 `RetryPolicy`가 step을 다시 돈다(경계는 원 예외를 그대로 낸다). 공항 0건은
  계약 위반이 아니라 `transport_empty`, JSON이 아닌 본문은 미분류 `JSONDecodeError`가 아니라
  `transport_malformed_upstream`(`TransportExportMalformed`)이다. 나머지는 `retryable=False`.
- **가격 feature 지역 코드.** transport 이관 뒤 주유소·휴게소 가격 feature는 `Address(road=...)`만 가져 bjd·시도·
  시군구가 비었다(옛 OpiNet 경로는 주유소 place 주소를 그대로 썼다). transport export에는 지역 코드가 없고 가격 job은
  역지오코딩하지 않으므로(M5) `list_primary_place_locator`가 place의 `legal_dong_code`·`admin_dong_code`·`sido_code`·
  `sigungu_code`·행정동 주소를 함께 싣고 가격 feature가 이어받는다. locator 행은 5-tuple이 됐다.
- **관리 UI 로그인 감사.** `recordAuthAuditEvent`의 fetch에 `AbortSignal.timeout(3000)` — 감사 API가 멈춰도 로그인
  응답이 붙잡히지 않는다(vitest).
- **문서.** transport 설정 표(BASE_URL·SERVICE_TOKEN·PAGE_SIZE·TIMEOUT_SECONDS)와 failure_kind 표를 dagster README에,
  integration-map은 peer 주소 게이트(`Host` 아님)·export별 응답 모양으로, settings 설명의 "Host로 닫는다"를 고쳤다.
  dagster README의 옛 `opinet_*`·`krex_*`·`krairport_*` resource/env/schedule 행과 external-apis의 OpiNet·KREX 키 행을
  정리했다. main의 `docs/resume.md`·`docs/journal.md`에 남아 있던 merge 표식 줄(`||||||| parent of 866d318c6`)도 지웠다.
- **RED → GREEN(n150 `~/ci-scratch/ktm-lows`, Python 3.14).** 테스트 커밋 `1bea708d8`: unit 5 실패, dagster 경계 3
  실패 + fetcher 테스트 collection 오류. 수정 head: 같은 표적 191건 통과. 전량: ruff check·lint-imports(4 kept)·
  mypy --strict 세 패키지 통과, unit+lint 3035 통과/16 실패(`test_docker_dagster_runtime.py` 13건은 main과 같은 집합 —
  n150 checkout 환경, 나머지 3건은 부하 아래 signal/lock 타이밍이라 재실행 통과), api 1217·dagster 582 통과,
  vitest RED(1 실패) → GREEN, tsc·eslint 통과.

## 2026-10-02 — Dagster entrypoint가 `code-server start`를 받는다: 브랜치 `fix/dagster-entrypoint-code-server`

- **원인(n150 prod 2026-10-01 21:52Z).** C7 schedule-write spec은 cron override를 `ops.dagster_schedule_overrides`에
  저장하고 location을 reload한다. Map은 override를 definitions import 때 읽는다. 그런데 code-server가 `dagster api
  grpc`라 reload는 "not currently supported" 경고만 남기고 무시됐다 — override가 반영되지 않아 C7이 빨갛다.
- **변경.** production 봉인의 code-server 분기가 하위 명령 `code-server start`도 받는다. 모양(9 argv, loopback `-h`,
  숫자 `-p`, 고정 `-m kortravelmap.dagster.definitions`)은 그대로 정확 일치다. `api grpc`는 Manager compose가 바뀔
  때까지의 전환용으로 남긴다. local-dev 분기도 같은 두 모양에서 runtime preflight를 돈다.
- **`-I`는 자식에 이어지지 않는다.** `code-server start`의 proxy는 자식을 `sys.executable -m dagster api grpc`로
  띄운다(run worker는 `api grpc` 때부터 같았다). user site는 요구된 `PYTHONNOUSERSITE=1`이, `PYTHONPATH`·`PYTHONHOME`·
  `PYTHONUSERBASE`는 기존 거부가 env로 자식까지 막는다. 남는 cwd-on-`sys.path`(`-P`)는 production exec 직전
  `PYTHONSAFEPATH=1`로 막는다(cwd `/app`은 root 0555라 지금도 쓸 수 없지만 기대지 않는다).
- **n150 실측(Manager 브랜치 `fix/dagster-code-server-reloadable`과 함께).** live Map dagster 이미지(1.13.24)로 일회용
  컨테이너를 빈 loopback 포트에 띄웠다: `api grpc`는 reload를 무시(import 1회), `code-server start`는 새 자식 pid로 다시
  import했다. proxy health는 고정 SERVING이라 Manager probe가 자식에 전달되는 `ListRepositories`를 보고 확정된 실패면
  PID 1을 끝낸다(load error·자식 kill 둘 다 재시작 확인).
- **테스트.** 두 모양 수용(자식 env에 `PYTHONSAFEPATH=1`), 섞인 하위 명령·`-h 0.0.0.0`·다른 `-m`·`-f`·추가 인자 거부,
  runtime preflight 매트릭스에 `code-server start`(production·local-dev) 추가.
- **남은 것.** 저장소 자신의 `docker-compose.yml`(standalone)은 `api grpc` 그대로다 — 바꾸면 Manager처럼 probe를
  자식에 묶어야 한다(후속).

## 2026-10-02 — 주유소·휴게소·돌발·공항 원천을 kor-travel-transport export로 이관(ADR-106): 브랜치 `feat/transport-api-sources`

- 소유자 결정: Map에서 transport로 얻을 수 있는 것은 transport API로 바꾸고, 필요하면 transport API를 고친다. OpiNet은
  transport 브라우저 수집본을 쓴다. 공항도 옮긴다. 새 provider 정체성 `kor-travel-transport`(internal) + identity 재지정
  보험. prod Map DB는 비어 있어(예상) shadow 없이 바로 전환한다.
- transport 쪽(`kor-travel-transport` 브랜치 `fix/fuel-latest-prices-incremental` → `feat/map-service-exports`): 최신 유가
  MV가 60초 timeout으로 영구 stale이던 것을 증분 테이블로 고쳤고(0022), 휴게소 기준정보·휴게소 유가 수집기와
  `GET /v1/service/exports/*`(토큰 + loopback Host, 404 은닉), 돌발 활성 집합(수집 실패·30분 정체면 503), 공항 15곳(KPO
  포함)을 더했다(transport ADR-013).
- Map: `providers/kor_travel_transport.py`(계약·엄격 파서), fetcher 5개(`fetch_transport_*`), asset/job/operation 6개를
  `*_transport_*`로 바꿨다. 정규화는 `opinet.py`·`krex.py`·`krairport.py`에 남고 provider 정체성만 바뀐다. migration
  `404_transport_provider_identity`가 새 dataset·operation·scope를 넣고 옛 identity를 옮기고(옛 돌발 entity가 있으면
  중단) 옛 적재를 끄고 계보 함수의 돌발 분기를 옮긴다.
- 지운 것: OpiNet 호출 예산·scope 모드·KST 일일 coalescing·POI target scope, krex 이중 snapshot 안정성 검사, krex rate
  gate 선언, krex/opinet 쿼터 예외 선언, 세 provider 핀, `KOR_TRAVEL_MAP_OPINET_*`·`KOR_TRAVEL_MAP_KREX_*` env.
- 적대 리뷰 반영(같은 날): 신선도를 두 겹으로 — transport는 이력 없음·실패·stale이면 모든 export에서 503,
  Map은 `collection` 플래그·완전 snapshot 0건·돌발 `collected_at` 30분을 다시 재고 `failure_kind`
  (`transport_not_current`·`transport_empty`·`transport_hidden`)로 실패한다(아무것도 지우거나 닫지 않는다).
  404는 자격증명 부재와 갈랐다. 유가 `observed_at`은 transport `collected_at`(마지막 확인)이다 — 오피넷
  `*_DT`(가격을 바꾼 때)를 쓰면 가격을 유지하는 주유소가 4일 지평선 밖으로 사라진다. 유가 job은 주유소를
  역지오코딩하지 않는다(locator로 부모만). UI "과거 날짜" 표식은 가격 도메인으로 고른다. 404 migration은
  옛 preview operation도 끈다. 페이지 상한·cursor 순환 검출·전송 오류 재시도를 더했다.
- C7: 공항 operation은 이제 transport 내부 export를 한 번 부른다. 계약 테스트를 "외부 provider 호출 0"으로 고쳐 적었다
  (`_transport_get`은 공항 export 상수로만 허용, 다른 경로는 빨강).
- 계약 관계(2026-10-03 소유자 결정): Map은 transport export의 소비자다 — pin·vendoring·repin 절차 없음. Map에
  필요한 필드·모양은 transport API를 직접 바꾼다(같은 PR 쌍, 호환 층 없음). 어긋남은 엄격한 런타임 검증이
  `failure_kind`로 실패시킨다. 대표 응답 5종(`tests/unit/golden/kor-travel-transport/`)이 실 파서를 지난다. 처음
  만들었던 vendored OpenAPI·`PIN.json`·repin 스크립트는 같은 날 지웠다.

## 2026-10-02 — ADR-105 적대 리뷰 반영: 같은 브랜치 `feat/remove-map-kma-dagster`

- **MED-1 PinVi가 다음 짝을 막는다.** Manager M05 harness가 OpenAPI hash 불일치를 거부하고 PinVi 계약 테스트가
  `BeachPublicView.latest_weather`를 단언한다. PinVi 브랜치 `chore/map-drop-weather`에서 재vendor한다. 순서: PinVi PR →
  Map PR → pair 회전.
- **MED-2 probe.** `cache_target_snapshot_gc`는 prod에서 돈 적이 없어(schedule STOPPED) 첫 gate가 GC 적체(최대 2,000
  batch)를 health check 안에서 지울 수 있었다. 전용 no-op job `map_run_heartbeat`를 두고 lint를 성질(resource ⊆
  {io_manager}, kortravelmap import 없음, run config 불필요, operation key 없음, in-process 성공)에 결박했다. 옛 기본값으로
  되돌리면 4개가 빨갛다.
- **MED-3 C7 왕복 복원.** KMA write spec이 덮던 "요청 → queue sensor → worker → 종결"을 krairport(번들 정적 데이터,
  upstream 0)로 되살렸다. 실제 prod write(공항 place 15건 멱등)다. 공유 plane Basic Auth 파일을 다시 읽는다.
- **LOW.** 401에 in-flight preflight(같은 upgrade에서 402의 `is_enabled` 필터를 빠져나가던 구멍; 막지 않으면 통과하는
  통합 케이스 추가), 403으로 lineage 함수의 KMA 분기 제거(앱 식과 DB 함수의 분기 집합 일치 unit 테스트 추가), 핀 제거,
  `.env.example` 키·stale docstring·삭제된 schedule mock 정리. frozen H35 replay의 KMA 텍스트는 해시 고정이라 남겼다.
  매분 schedule의 RUNNING 상태 행은 회전 전 stop(runbook)으로 처리한다 — Map에 RUNNING schedule이 0이어도 gate는
  SCHEDULER daemon heartbeat만 보므로 바닥이 빨갛게 고정되지 않는다.
- **n150 게이트(`9de7630`).** unit+lint 3,047 passed / 14 failed(main도 같은 환경 실패 15건 이하), API 1,217, Dagster 624,
  ruff·mypy 3패키지·lint-imports·graph check 통과. 통합 전량 1,106 passed / 2 failed(main에서도 실패하는 docker effect) /
  25 errors(bootstrap 19 환경, glibc collation 6은 단독 재실행 6/6 통과). `test_weather_removal_migration` 3/3(신규 400→402
  in-flight 중단 포함), `test_notice_lineage_key` 전부 통과, `head-schema.sql`은 재생성과 동일. probe lint는 기본값을
  `cache_target_snapshot_gc`로 되돌리면 4/20 빨강. 첫 실행에서 루트 설정의 경고→오류 때문에 setup ERROR 6건이 났다 —
  ERROR는 빨강이 아니므로 필터를 달고 다시 쟀다.

## 2026-10-01 — Map에서 날씨 feature·기상특보 notice 기능 삭제(ADR-105): 같은 브랜치 `feat/remove-map-kma-dagster`

ADR-104(KMA Dagster 경로 제거) 작업 중 소유자 결정이 넓어졌다: weather kind 기능 전부와 날씨 출처 notice(KMA 특보)만
지우고, UI에서도 지우고, 데이터와 관련 스키마도 지운다. 정의(kind·DTO·enum·`make_feature_id`·DB kind 값)는 남긴다.
산림청 산사태 예보와 KREX 교통공지는 날씨 출처가 아니라 남긴다. **배포 전 백업은 소유자가 명시적으로 면제했고, 삭제는
되돌릴 수 없다.** 정기 백업은 이 결정과 무관하다.

- **prod 읽기 전용 실측(12:00Z 전후).** `feature.features` 0행(모든 kind), weather fact·summary·notice 0,
  `source_entities`·`source_records` 0, `ops.current_summary_runs` weather 2,875(매분 schedule의 receipt)·price 5,
  weather·KMA 카탈로그 dataset 12·operation 18·scope 13. notice provider별 행도 0이라 지워지는 notice도 남는 notice도
  현재는 행이 없다. 그래서 402가 prod에서 실제로 지우는 것은 summary run 2,875행과 카탈로그 상태뿐이다.
- **나눈 작업.** Dagster(W1), 라이브러리·API·OpenAPI(W2), migration 402·스키마 산출물(W4), C7/D1/D2(W5), UI(W3), 교차
  정리(W6)를 파일 소유를 갈라 병렬로 했다. 정본 결정은 `WEATHER-REMOVAL-SPEC`(작업 메모)에 두고 모두 같은 정체성 규칙을
  썼다: weather = 카탈로그 `capabilities.produces ∋ "weather"`, 날씨 notice = notice이면서 provider `python-kma-api`.
- **402가 하는 일과 근거**는 migration docstring과 ADR-105에 있다. 지운 스키마 넷은 `head-schema.sql` 전수 검색으로
  weather 전용임을 확인했다. 공유 표 `ops.current_summary_runs`는 남기고 CHECK만 `price`로 좁혔다.
- **게이트에서 잡은 것.** (1) API guard가 `app.routes`로 경로를 셌는데 n150에서는 sub-app mount 때문에 `/metrics`
  하나만 보여 **빈 집합에서 빨갰다** — main에서의 빨강도 그 이유였을 수 있어, OpenAPI `paths`로 바꾸고 main에서 다시
  잰다. (2) squash 경계 검사가 root(`400`)만 허용해 401·402를 겨누는 통합 테스트를 retired 대상으로 봤다 — active
  graph의 revision을 허용하게 고쳤다. (3) PinVi rollout pending receipt의 OpenAPI sha를 재핀했다(`latest_weather` 소멸 —
  PinVi vendor는 다음 짝에서).
- **C7.** KMA 위에 서 있던 러너를 KMA 없이 돌게 했다: read-auth, schedule-write(allowlist
  `feature_place_krairport_airports_monthly_schedule` — fetcher가 번들 정적 데이터만 읽어 upstream 호출 0), POI
  `@c7-causal`. n150 `.d2-live.env`의 `E2E_C7_SCHEDULE`을 그 값으로 바꿔야 러너가 시작한다. D2는 price feature 하나만
  심는다. 둘 다 prod에서만 돌 수 있어 이번에 실행하지 못했다.
- **n150 게이트(브랜치 소스를 PYTHONPATH로, main과 대조).** unit+lint 3,026 passed / 14 failed — 14건은 main에서도
  같은 환경 실패(`test_docker_dagster_runtime` 13: node 의존, `test_c7_prod_live_runner_process` INT-130 1). API 1,217
  passed, Dagster 624 passed, ruff·mypy --strict 3패키지·lint-imports·migration graph `--check` 통과. frontend
  type-check 통과, vitest 380/381(실패 1은 main과 같은 maplibre worker 파일 부재), lint·build는 n150 node_modules가
  main에서도 깨져 판정 불가(W3가 로컬 eslint 통과를 확인). 통합 테스트는 n150 디스크 대기로 testcontainers PostGIS가
  `pg_ctl` shutdown checkpoint에서 죽어(교체된 이유) 하네스에서만 PGDATA를 tmpfs로 두고 돌렸다: 영향 파일 30개
  307 passed, `head-schema.sql`은 `KTM_WRITE_HEAD_SCHEMA=1` 재생성 결과와 바이트 동일. 통합 전량(glibc 이미지)은
  1,110 passed / 3 failed / 19 errors — 19 errors는 bootstrap 묶음의 알려진 n150 환경 실패, docker effect 2건은 main에서도
  같이 실패, `test_tvn34_public_projection_spine`의 EXPLAIN 1건은 단독 재실행에서 통과(공유 DB 통계 순서 의존).
- **빨강 실측.** 브랜치의 guard를 main 소스에 대고 돌렸다: Dagster 5/7 빨강(나머지 둘은 카탈로그 하한·남는 notice
  양성 검사), API 3/5 빨강(나머지 둘은 축 유도 하한·남는 notice preview 양성 검사), UI 4/6 빨강(W3, HEAD 파일 복원),
  DB는 `test_weather_removal_migration.py`가 401에서 19개 제거 검사가 0이 아님을 먼저 단언한다.
- **배포 영향.** 공유 plane Map location의 instigator 11개 중 `current_weather_summary_refresh_minutely_schedule`
  (RUNNING) 하나가 사라지고 sensor 10은 남는다. 옛 Map 전용 instance(`kor_travel_map_dagster`)의 같은 schedule 상태 행도
  쓰이지 않게 된다. 402의 `DROP INDEX`가 `feature.features`에 ACCESS EXCLUSIVE를 잡으므로 매분 schedule과 겹치지 않게
  배포한다(새 코드에는 그 schedule이 없으니 code server 교체 뒤 migration이면 겹칠 일이 없다).

## 과거 기록 아카이브

> 현행 작업 창(2026-10-01~) 이전 기록은 아래로 분리했다. 검색은
> `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [`journal-2026-10a.md`](archive/journal-2026-10a.md) | 2026-10-01 | 1건 | 6 KB |
| [`journal-2026-09h.md`](archive/journal-2026-09h.md) | 2026-09-30 | 1건 | 4 KB |
| [`journal-2026-09g.md`](archive/journal-2026-09g.md) | 2026-09-28 ~ 2026-09-29 | 6건 | 22 KB |
| [`journal-2026-09f.md`](archive/journal-2026-09f.md) | 2026-09-26 ~ 2026-09-27 | 14건 | 31 KB |
| [`journal-2026-09e.md`](archive/journal-2026-09e.md) | 2026-09-20 ~ 2026-09-25 | 8건 | 27 KB |
| [`journal-2026-09d.md`](archive/journal-2026-09d.md) | 2026-09-16 ~ 2026-09-19 | 7건 | 22 KB |
| [`journal-2026-09c.md`](archive/journal-2026-09c.md) | 2026-09-14 ~ 2026-09-15 | 8건 | 22 KB |
| [`journal-2026-09b.md`](archive/journal-2026-09b.md) | 2026-09-11 ~ 2026-09-13 | 5건 | 26 KB |
| [`journal-2026-09a.md`](archive/journal-2026-09a.md) | 2026-09-01 ~ 2026-09-10 | 23건 | 84 KB |
| [`journal-2026-08d.md`](archive/journal-2026-08d.md) | 2026-08-29 ~ 2026-08-31 | 14건 | 25 KB |
| [`journal-2026-08c.md`](archive/journal-2026-08c.md) | 2026-08-28 ~ 2026-08-28 | 21건 | 20 KB |
| [`journal-2026-08a.md`](archive/journal-2026-08a.md) | 2026-08-14 ~ 2026-08-27 | 124건 | 200 KB |
| [`journal-2026-08b.md`](archive/journal-2026-08b.md) | 2026-08-01 ~ 2026-08-14 | 89건 | 166 KB |
| [`journal-2026-07c.md`](archive/journal-2026-07c.md) | 2026-07-26 ~ 2026-07-31 | 60건 | 167 KB |
| [`journal-2026-07a.md`](archive/journal-2026-07a.md) | 2026-07-13 ~ 2026-07-24 | 115건  | 219 KB |
| [`journal-2026-07b.md`](archive/journal-2026-07b.md) | 2026-07-01 ~ 2026-07-12 | 28건   | 45 KB  |
| [`journal-2026-06a.md`](archive/journal-2026-06a.md) | 2026-06-10 ~ 2026-06-30 | 172건  | 219 KB |
| [`journal-2026-06b.md`](archive/journal-2026-06b.md) | 2026-06-02 ~ 2026-06-10 | 179건  | 220 KB |
| [`journal-2026-06c.md`](archive/journal-2026-06c.md) | 2026-06-01 ~ 2026-06-02 | 36건   | 53 KB  |
| [`journal-2026-05a.md`](archive/journal-2026-05a.md) | 2026-05-24 ~ 2026-05-31 | 90건   | 218 KB |
| [`journal-2026-05b.md`](archive/journal-2026-05b.md) | 2026-05-24 ~ 2026-05-24 | 3건    | 7 KB   |
