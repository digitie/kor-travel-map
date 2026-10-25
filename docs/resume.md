## 2026-10-25 — 공항 snapshot 원자적 후처리 구현 중

원 발견사항·sync cursor·stale 정리를 한 fenced RC transaction과 receipt로 연결하고, 종결된 임시 입력의 7일/최대16개 정리를 추가했다. 순수 transaction/backend 회귀10 PASS이며 실제 PG·전체430·두 리뷰·CI·live UI·운영은 미완이다. [범위와 검증](reports/2026-10-25-airport-snapshot-durable-postprocess.md).

## 2026-10-25 비활성 strict SH guard429 owned 검증

- 46666 CI 원결과를 보존하고 검토된428 cac89의 ORM metadata/반사식 수정과 원 fresh300 검사1 PASS를 상속한다. 429 SQL·공식dump·role trace는 유지하며 새 합성 CI는 별도다.
- ac441 CI의 마지막 role 추출 실패를 보존하고 실제 receipt/마지막 SET ROLE tuple 배선을 정렬했다. 양28/26 execute trace는 같고 lint 전체+전용 unit381 PASS/기존6 SKIP이다. 새 CI는 미완이다.
- 별도 source의 실제30/새11과 공식oracle1 PASS·정리를 확인했다. 원25 PASS/5 FAIL은 보존하며 단일41 실행으로 세지 않는다.
- 검토된 root428c98·최신 main/공항427 부모와 실제429 dump를 상속한다. 제품 SQL·공유 fixture는 유지한다. 최종 두 검토/정확 CI·성능·취소/pool·전체 closure·RC/복구/SH 운영은 미완이다. [범위·근거](reports/2026-10-25-strict-sh-data-guard-foundation.md).

## 2026-10-25 — 427 metadata 수정의 428 상속

세 인덱스의 ORM 선언을 실제 PG 반사 표현식에 맞춘 부모를 상속했다. fresh300 원 metadata 검사 1 PASS/17.172초를 확인했으며, 원 실패는 보존한다. 428의 SQL·oracle은 그대로이고 합성 CI·취소 복구·실제 동시 수집은 미완이다.

### 2026-10-25 공항 인덱스 PG 반사 표현식 보완

- 4bd 실제 autogen 1 FAIL/정확 정리를 보존하고 metadata CASE를 PG canonical 반사와 맞췄다. 기존 comparator 순수 회귀3 FAIL→equal·migration 포함8 PASS, 새 실제 검사는 미실행이다. [보고서](reports/2026-10-25-transport-airport-evidence-reader.md).

### 2026-10-25 공항 reader ORM 인덱스 metadata 보완

- 70cb 양 PG CI의 autogen 단일 실패/원 로그를 보존하고 canonical metadata에 기존 인덱스3만 등록했다. 생성 SQL 전체 대조와 migration 회귀8 PASS, 실제 autogen/새 exact CI는 미실행이다. [보고서](reports/2026-10-25-transport-airport-evidence-reader.md).

## 2026-10-25 — capture 권한 인벤토리 CI 정정

c98 CI의 signature literal 검사 실패1개를 보존하고, 존재 검사를 pg_catalog 이름 조회·GRANT를 카탈로그 서명 치환으로 정렬한다. 역할/SQL/oracle은 유지하며 새 정확 CI는 미완이다. [근거](reports/2026-10-25-bounded-curation-capture.md).

## 2026-10-25 — 제한된 현재집합 capture(428, 구현 중)

실제 PG16.14에서 통합37 PASS/15.798초, fresh bootstrap 공식 oracle1 PASS/22.897초를 확인했다. 덤프를 갱신했으며 기존 실패와 시험 수정 기록을 보존한다. 검토된 최신 공항427·main을 상속했으며 최종 CI, SH/RC/복구 연결과 운영 배포는 미완이다. [범위·예산·검증](reports/2026-10-25-bounded-curation-capture.md).

### 2026-10-25 공항427 준비 경계 소스

정본 converter/loader 기반 공항1→15·R1/R2/Geo 시험1개와 비활성 준비 함수를 추가했다.
순수12 PASS 뒤 첫 실제1FAIL을 보존했다. N1 단언 후 EX plan을 SH entry로 호출한
시험1곳을 EX entry로 정정하고 b3b synthetic15 실제1 PASS·공식oracle1을 확인했다.
R2/R3 비이름 의미 P2 반례2FAIL→순수157 PASS로 보강하고 두 source/binding 리뷰 뒤
c63 재검증1 PASS15.246s·complete15와 정리를 확인했다. 운영15fit·collector·SH·EXPLAIN/
peak·최종CI는 미완이며 현재PG0다.

## 2026-10-25 공항427 key/index 보강

- 논리CASE index3·caller 서버상한·area EXISTS, provenance P2 정정. 순수143 PASS.
- 실제 설치/oracle/EXPLAIN·Geo/native 준비·수집/SH는 미완, 두 source gate 전 PG0.

## 2026-10-25 공항427 SQL/decoder source

- 426 부모 보존, STABLE3함수·51가변열·RR decoder 배선. 순수108 PASS/mypy4.
- 실제 PG/oracle·provider 준비/native 연결·15 fit·collector/SH/운영은 미완.

## 2026-10-25 — 공항 reader Geo 계약(427, 부분)

- 원천 hash32/Geo digest64 혼동을 정정하고 원실패를 보존했다. 순수 Geo28개 경계이며 SD/DB·수집은 미완이다. [범위](reports/2026-10-25-transport-airport-evidence-reader.md).

## 2026-10-25 — 가격 추이 본문 읽기 Low 3건(#1365 리뷰 후속)

- gzip 끝 뒤 bytes(두 번째 member 포함)를 `upstream_contract`로 거부하고, `aiter_raw`에서 나지 않는 `httpx.DecodingError` catch를 지웠다. 503 problem 본문을 읽다 끊기면(timeout·연결 끊김) 상태 코드대로 `upstream_unavailable`이다(200 본문은 기존대로 `upstream_timeout`/`upstream_unavailable`). 테스트 `_as_wire` 주의 문구 추가.

## 2026-10-25 — 현행 기록 크기 경계 재분리

journal의 10월1~12일28절을 [10c](archive/journal-2026-10c.md)로 보존하고 상대 링크만 재기준화했다. 본문 누락 없이 220 KiB 경계를 확보했다.

## 2026-10-25 — 공개 provider patch P-first(426)

실제25·공식 oracle1 PASS와 정리를 확인했다. 원실패를 보존한다. [근거·미완](reports/2026-10-25-provider-patch-protocol-entry.md). CI·운영·실제 SH는 미완이다.
## 2026-10-25 — Provider base UPDATE-first 후보(425, 미수용)

- 실제15·oracle1·EX18·제한 A/B를 정산했다. 원 실패를 보존하며 최종 CI·운영은 미완이다. [범위·한계](reports/2026-10-25-provider-base-update-first.md).

## 2026-10-25 — tracking P→L prefix(424, 부분)

- 기존 SER/capture/kernel/SH OFF를 보존했다. 직접25·정본oracle1·기존 client4와 별도 ASGI1(503→새요청200→재요청200)·fresh triple7을 검증했다. 공유 cutover DB의 통합11 원실패(9 PASS/2 FAIL)는 보존·합산하지 않는다. 정확 CI 양 PostGIS lane의28 FAIL/1 ERROR를 보존·분석 중이며 운영·whole snapshot은 미완이다. [범위·근거](reports/2026-10-25-tracking-protocol-prefix.md).
## 2026-10-25 — Place projection 예산 검사 추출

- Heritage 사전 검사를 core로 이동하고 기존 wrapper·9DTO·본문을 보존했다. 순수 회귀114 PASS이며 DB/수집 연결은 없다. [범위·미완](reports/2026-10-25-place-projection-budget-extraction.md).

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

- PG transport **유가·돌발** 적재(asset·job·schedule 셋, 큐 runner spec·handler binding·preview fixture)를 지우고 migration
  `419_retire_pg_transport_values`가 그 operation을 끄고 Feature 약 1.4만 건을 `system` 퇴역한다(soft-delete,
  데이터는 남김). 장소(주유소·휴게소·공항)는 PinVi 일반 검색·근처와 C7 공항 job이 기대므로 ②단계로 미뤘다. API 표면 변화
  없음. 배포 영향: Map API·Dagster code location(같은 pair) + migration 419.
- 적대 리뷰 2회 반영(2026-10-24): 409→417 한 트랜잭션 거부(410~416 잠금을 퇴역 내내 쥐지 않게 — 배포는 A head 416 → B 411), 대상
  member 표 둘 `SHARE` 잠금으로 검사·끄기·도중 INSERT 경주 차단(재리뷰: 행 단위는 BEFORE 가드 뒤라 못 막는다)·operation 먼저 끔, timeout 명시, link 역할 무관 seal 검사, 대상 dataset 셋 고정·옛
  provider 잔여 fail closed, 상태 문맥 GUC 정리.
- **다음 한 작업: CI green → 머지 판단 → A: head 416 pair 배포 → B: 세 dataset 갱신 정책 `enabled=false` 필수·schedule 확인·진행 중
  job 0·큐 sensor 정지 → 417 pair 배포 → 전이 수·in-bounds 확인(ADR-114 "①의 운영 runbook"). 그 뒤 ②의 해제 조건(PinVi in-bounds 기본 kind·장소 검색 대체, C7
  안전 대상 이동)을 PinVi·C7 쪽에 건다.**
## 2026-10-24 — 한 sealed attempt의 scalar 원자 batch(A2)

- 같은 dataset의 기존 primary place 여러 개를 한 TX/finish1회로 적용하는 별도 entry를 추가했다. snapshot seal·실제 collector 배선·same-dataset 병렬 수용은 아니다.
- 최종146 PASS(새PG20/unit10+부모116)·lint377(기존6skip)/Ruff/mypy2/import4 통과, 두 코드리뷰·정확CI·실UI는 미완이다. 총1MiB/manifest8192·협력적30s/입력독점소유 계약과 한계는 [A2 보고서](reports/2026-10-24-native-scalar-batch.md)에 있다. 기본OFF/seed0/운영0.

## 2026-10-24 — 국가유산 native 적격성 선행 계약(A1, #1390)

- 안정 composite ID의 본체 이름 presence와 저장 typed projection 재정규화·지원 외 불변 진단을 추가했다. eligible은 DB 적용 승인이 아니며 collector/Geo/whole-TX seal·정책은 바꾸지 않는다.
- 격리된 고정SDK public 모델·Map fetcher service fixture 포함98 PASS, native 예산 후속075 합집합116 PASS(실PG 포함), mypy3/import4/Ruff 통과. 정확CI·독립2리뷰는 진행 중이며 PG/실UI/운영 수용으로 세지 않는다. [범위와 실패](reports/2026-10-24-heritage-native-eligibility.md).
- 기존 EX 진입은 별도 #1389이며 부모 합성 시 양쪽 기록을 보존한다. 기본OFF/seed0/운영0, 내구 artifact/full bundle/실제 collector 배선은 후속이다.

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

## 2026-10-24 — ADR-114 2단계(T-STATE-02): 브랜치 `feat/adr114-valkey-weather`

- weather W1·W2·W3·W5 export를 위치 단위 Valkey 세대로 싣는 Dagster job 7개(기본 STOPPED)와 `/v1/service/weather/*` 5
  route를 더했다(2026-10-24 정확성·운영 리뷰 반영 — 부분별 nearest·배치·partial 재계산·ETag 304 등, ADR-114 W 절). migration 없음. admin·service OpenAPI 변경(**PinVi 재vendor 필요**). 배포 영향: Map API·Dagster code
  location. weather live(odroid `3a0ae398`)에는 아직 W1~W5가 없다.
- **다음 한 작업: 소유자 적대 리뷰 → PR CI green → 머지 판단 → weather W1~W5 배포·export 활성화 → Manager가 Map
  code-server에 `KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_{BASE_URL,SERVICE_TOKEN}` 추가 → PinVi 재vendor → Map 배포 → 하한
  대조 후 schedule enable(acceptance §T-STATE-02).**

## 2026-10-24 — 공용 지도 작업면 채택 후보

Feature 지도의 종류 필터에 아이콘을 결합하고 필터·보기 탭·건수/실제 좌표·줌·상세 오버레이를 공통 컴포넌트로 소비한다. Map의 기본 종류·소스·상태 필터와 조회 동작은 보존한다.

후속 UI에서 설명은 제목의 정보 버튼, 상태 필터는 `추가 필터`로 접고 select를 176×30px로 통일했다. 지도 높이를 유지하면서 375px 지도 시작을 651.75→439.25px로 앞당겼다. 다른 화면의 기본 여백·도움말·모바일 메뉴는 유지한다.

main `0b2dc53d0`을 추가 통합하고 두 작업 기록을 양쪽 보존했다. 독립 리뷰의 상세 키보드 포커스 이탈을 수정했다: 진입 포커스·예약 프레임 취소·Escape/닫기 후 마커/지도 탭 복원, point/가격 DOM 마커 Enter·Space 활성화. WSL 타입·frontend 49파일 400건·전체 ESLint PASS. n150 Playwright 1.64.1 지도 E2E 6건(375/1440px 키보드 2건 포함) PASS, 기존 실측·GeoJSON 검증의 레이아웃/worker 계약도 유지한다. Python/API/계약은 최신 main 그대로이며 lock 변화는 없다. [정산](reports/2026-10-24-shared-map-ui.md). 다음은 통합 담당자의 CI·두 독립 재리뷰이며 자체 운영 빌드·배포는 하지 않는다.

## 2026-10-24 — 가격 추이 프록시 transport T4 정렬(T-STATE-01-T4): 브랜치 `feat/transport-fuel-price-history-t4`

- `/v1/service/transport/fuel-stations/{feature_id}/price-history`가 transport T4 실제 계약을 읽는다(질의 변환·불투명
  cursor·cursor 요청의 transport 409 → HTTP 409 `TRANSPORT_PRICE_HISTORY_CURSOR_EXPIRED`·이유 enum 4개 추가·유한 가격·
  요청 대비 행 검증·본문 상한·행별 시각 nullable). migration·설정 변화 없음. service·admin OpenAPI 변경(**PinVi service·admin
  재vendor 필요 — ADR-114 D6 체크리스트**). 배포 영향: Map API. 적대 리뷰 2회 반영 완료.
- **다음 한 작업: CI green → 소유자 머지 판단 → PinVi 재vendor PR → Manager compose PR(`kor-travel-map-api`에 transport
  주소·토큰·`KOR_TRAVEL_MAP_TRANSPORT_PRICE_HISTORY_ENABLED`) → pair 회전 → 배포 뒤 실제 주유소로 `available`·두 페이지 확인.**

## 2026-10-24 — ADR115 T-CWRITE-01: 격리 쓰기 기준선 runner

- 고정 synthetic fixture와 전용 PostGIS container/template clone으로 native load_bundles→seal/commit의 cold/warm 3회 runner를 구현했다. CPU/RSS/WAL·실제 DML 구간/잠금 샘플·CI artifact를 남기며 전체 T01/동시 쓰기 완료로 세지 않는다.
- 첫 실제 PG에서 post-upgrade runtime ACL 조정 누락을 확인해 정본 routine/setup pool 폐기·fresh worker 최소권한 preflight/login 검증을 보완했다. GRANT 추가/owner 측정 우회 없이 두 lane을 재수용한다.
- 기존 global fence/FeatureRepo/winner/API는 변경하지 않는다. 외부 DSN·운영 접속·새 로컬 DB/container0. [범위·미완](reports/2026-10-24-scoped-write-baseline.md).

## 2026-10-24 — ADR115 shadow 실제 수집 연결: 명시 scope·MCST 이름

- revision+provider/dataset allowlist가 모두 있을 때만 기존 native TX 안에서 shadow를 기록한다. 실제 MCST 이름만 supplied로 선언하며 Geo/파생값/DTO null은 추측하지 않는다.
- 기본OFF/정책seed0/운영0. 기존 Feature ID/effective/전역 잠금 의미를 유지한다. [연결·실패·미완 gate](reports/2026-10-24-provider-field-shadow-hook.md).
- 실제client PG/기존MCST·대기 집중검증을 진행하며 CI/두 리뷰/HTTPUI는 별도 수용한다. 전체 membership/winner/Geo/scope 분할은 미완이다.

## 2026-10-24 — ADR115 T-CWRITE-02: 불변 정책과 shadow 후보 기반

- 완결 fieldset을 원자 등록하는 불변 정책 header와 source별 typed shadow recorder/ACL을410에 추가한다. 등록은 global-first이며 RR에서 새 revision이 보이지 않으면 실패한다.
- 실제 native 수집 hook/settings는 별도 후속으로 분리했다. 공개 winner/effective/전역 잠금 범위는 유지하며 기본OFF/운영0이다. [범위·교착/RR·미완 gate](reports/2026-10-24-provider-field-shadow.md).
- 정책/전체 membership·Geo·winner 활성·scope/epoch/manifest와 최종 CI/두 리뷰·HTTP/UI 수용은 미완이다. 첫 기반 단위를 전체 동시 쓰기 완료로 세지 않는다.

## 2026-10-24 — ADR115 선행: 같은 transaction fence 재진입 SQL 절감

- 실제 root session/connection transaction·오류 stamp가 유효한 동안만 전역 fence를 재사용한다. savepoint 획득은 캐시하지 않는다. 전역 충돌 범위·병합 의미는 유지한다.
- 기존 집중27/새 실제PG10 PASS, 변경 Ruff/strict mypy PASS. [범위·실패 규약·검증 한계](reports/2026-10-24-curation-fence-reentry.md).
- T-CWRITE-01 전체 기준선 및02~09는 미완이다. 다음은 두 독립 리뷰·CI·실제 HTTP/UI 수용 후 후보/winner와 scope gate의 작은 코드 단위를 이어간다. 운영 미배포.

## 2026-10-24 — 수집 PR #1358의 Next 보안 CI 선행 복구

- Next/직접env/ESLint 플러그인16.4.1, 배포 audit 취약점0. 기존 OpenAPI admin 타입 산출물
  drift를 공식 generator로 정합화했다. 수집/화면/API 구현/DB 제품 소스는 변경하지 않았다.
- admin395/marker4·타입/lint·Sharp실변환·production build PASS.
- 다음: 두 독립 리뷰 → 정확 CI 통과 후 CI 복구 PR을 먼저 머지하고
  #1358이 최신 main을 통합해 CI를 재실행한다. 운영 미배포.
- [범위와 검증 기록](reports/2026-10-24-next-security-gate.md).

## 2026-10-24 — 멈춤 진단 오탐 정정: 브랜치 `fix/stall-watchdog-progress`

- MCST 첫 적재 성공(#1357). watchdog 진척 신호에 geo·상류 요청·DB 문장 표시를 더하고 경고를 run당 한 번으로. migration·
  OpenAPI·설정 변화 없음. 배포 영향: Map Dagster code location.
- **다음 한 작업: PR CI green → 머지·배포(등산로 run이 끝난 뒤) → 등산로 결과 journal.**

## 2026-10-24 — 여섯 프로젝트 npm 보안·버전 정합

- 현재 상태: npm 보안·공통 버전 소스 정합 및 WSL 검증 완료. [버전과 예외](npm-security-alignment-2026-10-24.md). 최종 CI·UI·머지 상태의 정본은 [PR](https://github.com/digitie/kor-travel-map/pull/1368)이다.
- 다음 한 작업: 운영 반영을 요청받으면 Manager 정본과 현재 배포 런북에 따라 릴리스를 적용한다. 소스 머지와 운영 배포는 구분한다.

## 2026-10-23 — MCST 6시간 상한·멈춤(T-GEOLOAD-01): 브랜치 `fix/mcst-geo-stall`

- 비-MOIS 역지오코딩 적재 선조회 동시성(env `KOR_TRAVEL_MAP_REVERSE_GEOCODE_CONCURRENCY`, 기본 2), 적재 geo client 일시
  장애 재시도, 적재 step 멈춤 진단. migration·OpenAPI 변화 없음(PinVi 재vendor 불필요). 배포 영향: Map Dagster code location.
- **다음 한 작업: PR CI green → 머지·배포 → MCST 재실행(약 3시간 예상) → 성공 시 등산로(seal 천장은 #1256으로 해소).**

## 2026-10-23 — geo 부하 줄이기 0단계(ADR-116, T-GEOLOAD-00): 브랜치 `feat/skip-geocode-unchanged`

- 비-MOIS 역지오코딩 asset(MCST 포함, MOIS·concierge 제외)이 공통 helper로 변환을 두 번 돌려, payload·좌표가 그대로이고
  스탬프가 `called`·현재 geo 토큰인 행은 geo를 부르지 않고 저장 주소 열을 답으로 쓴다. 결과 bundle은 전량 지오코딩과
  같다(사후 확인). migration·OpenAPI·설정 변화 없음(PinVi 재vendor 불필요). 배포 영향: Map Dagster code location 재배포.
- prod 읽기 전용 실측의 기대: 주차장 reverse 약 17.6k/run → 1~2k, MCST 세계음식점 9.5k → 수백(나머지 MCST 12개·등산로는
  첫 성공 적재 뒤부터).
- **다음 한 작업: PR CI green → 소유자 머지·배포 판단 → 배포 뒤 첫 정기 run의 `저장값 재사용 skipped=… geocoded=…`
  요약 로그를 journal에 남기고 ADR-116 accepted.**

## 2026-10-23 — ADR-114 1단계(T-STATE-01): 브랜치 `feat/adr114-valkey-transport`

- transport 주유소·휴게소·휴게소 유가·돌발·공항의 현재 상태를 Valkey 세대 단위로 교체하는 Dagster job 5개(기본 STOPPED)와
  `/v1/service/transport/*` 10 route를 더했다. migration 없음. admin·service OpenAPI 변경(**PinVi admin 재vendor 필요**).
- **다음 한 작업: PR CI green → 소유자 머지 판단 → Manager Valkey PR 배포·API env(Valkey URL, transport 주소·토큰) →
  PinVi 재vendor → Map 배포 → schedule enable·첫 교체 확인(acceptance §T-STATE-01).**

## 2026-10-23 — Map 실제 동시 쓰기 설계(ADR-115, 문서만)

- 최신 main `cdd2614007a86e8627949cd1176c61eb14c0ce3e`의 전역 3종 gate, source/Feature
  병합·base/effective·seal·Geo token 경계를 대조하고 proposed 설계와 T-CWRITE-01~09를 작성했다.
- 코드·migration·운영 설정 변경/CI 실행 없음. 사용자 요청으로 독립 적대 리뷰 2인 후 doc-only PR을 CI 검토 없이 머지한다.
- **다음 한 작업: 문서 리뷰 지적 반영·머지. Map 구현은 현재 Weather·Transport 작업 완료 뒤
  T-CWRITE-01부터 시작하며, 기존 다른 열린 작업의 상태를 이 설계로 완료 처리하지 않는다.**

## 2026-10-22 — T-LOAD-LOCK-WAIT 2안(ADR-113): 브랜치 `fix/short-curation-lock-hold`

- 스트리밍 snapshot 적재(8개 asset·큐 경로)는 stream을 다 받은 뒤 쓰기 transaction을 연다 — fence 보유가 fetch·지오코딩
  시간(2.5시간+)에서 쓰기 시간(주차장 첫 적재 약 10분·재적재 약 2~3분 추정)으로 준다. migration·OpenAPI·설정 변화 없음
  (PinVi 재vendor 불필요). 배포 영향: Map Dagster code location 재배포.
- **다음 한 작업: PR CI green → 소유자 머지·배포 판단 → 배포 뒤 8개 asset 쓰기 시간 로그를 journal에 남기고 ADR-113 accepted.**

## 2026-10-22 — T-LOAD-LOCK-WAIT 1안: 브랜치 `fix/load-curation-lock-wait`

- provider 적재의 첫 `feature-curation-write` 획득만 900초까지 기다린다(env `KOR_TRAVEL_MAP_FEATURE_LOAD_CURATION_LOCK_WAIT_SECONDS`).
  migration·OpenAPI 변화 없음(PinVi 재vendor 불필요). 배포 영향: Map Dagster code location 재배포.
- 한계: 스트리밍 snapshot 적재는 fence를 1시간 넘게 쥔다(실측) — 그 뒤의 적재는 15분 뒤 실패한다. 근본은 2안.
- **다음 한 작업: PR CI green → 소유자 머지·배포 판단 → 2안(fetch·지오코딩을 쓰기 transaction 밖으로) 설계.**
## 2026-10-22 — prod 첫 적재 실패 2건: 브랜치 `fix/highway-evidence-krheritage-address`

- 고속도로 돌발 10분 경로에 `AdminEvidence`를 실어 미시도 reverse가 drop이 아니라 warning이 되게 했고, 국가유산 행사는
  `sido`/`gugun` 주소 fallback과 `seqNo::시작일::종료일` 자연키를 넣었다. migration·OpenAPI 변화 없음.
- python-krheritage-api 핀을 `e1b346f7`(provider #12, 0.1.1)로 올렸다. 자연키는 provider `occurrence_key`와 글자 그대로 같다.
- **다음 한 작업: PR CI green → 소유자 머지 판단 →
  Map Dagster code location 재배포 후 두 job 첫 적재 확인.**

## 2026-10-21 — T-RECONCILE-RETRY 하위 단계 2(ADR-112 결정 1~7): 브랜치 `feat/reconcile-retry-alert-close`

- ADR-112 accepted. 결정 1~7 구현·적대 리뷰 2회 반영·변이 검사 완료, 원장은 `tasks-done.md`로 이관했다. migration 없음,
  OpenAPI 변화 없음(PinVi 재vendor 불필요). common 핀 `e746e4b8`.
- **다음 한 작업: PR CI green → 소유자 머지 판단 → Map Dagster code location·API 재배포(daemon은 소유자가 켤 때까지
  멈춘 채).** 되돌릴 때는 cursor 선택 키를 먼저 뺀다(ADR-112 결정 7).

## 2026-10-20 — T-RECONCILE-RETRY 하위 단계 1(ADR-112 결정 0-1): 브랜치 `feat/finalize-out-of-sensor`

- SUCCESS root 완결을 sensor tick 밖 `feature_operation_completion` sweep job으로 옮겼다. migration·API·OpenAPI 변화 없음.
- 배포 영향: Map Dagster code location 재배포만 필요하다. 새 job·pool이 생긴다. n150 공용 Dagster daemon은 소유자가
  멈춰 둔 상태라 다시 켜기 전까지 효과가 없다. 켜면 밀린 SUCCESS root를 sweep 하나가 차례로 완결한다. daemon·sensor를
  임의로 켜지 않는다.
- **다음 한 작업: 이 PR CI green → 소유자 머지 판단 → 소유자가 ADR-112 O2~O5를 승인하면 같은 항목에서 결정 1~7 구현.**

## 2026-10-20 — weather 잔재 정리 2건: 브랜치 `chore/wx-notice-close-vnext-freeze` (PR #1343)

- T-WX-NOTICE-CLOSE(`close_notice_features` 삭제)·T-WX-VNEXT-FREEZE(동결 계약은 rev 300 기록) 완료. 다음 한 작업은 아래 ADR-112 항목 그대로다.

## 2026-10-20 — T-RECONCILE-RETRY 설계안 ADR-112: 브랜치 `docs/t-reconcile-retry`

- reconcile sensor의 재시도·멈춤 알림·root 닫기 설계를 ADR-112(proposed)로 냈다. doc-only이고 코드 변경은 없다.
  항목은 열려 있다.
- **다음 한 작업: 소유자가 ADR-112 열린 결정 O1~O5를 승인한다(O1 전에 prod root 완결 소요를 읽기 전용으로 잰다) →
  같은 항목에서 구현하고 적대 리뷰를 받는다.** n150 공용 Dagster daemon은 소유자가 일부러 멈춰 둔 상태다. sensor를 켜지 않는다.

## 2026-10-19 — MapLibre production asset 복구 (PR #1340)

- 원인: production frontend 이미지가 Next standalone와 static만 담고 `public/maplibre` worker/shared 모듈을 빠뜨려, 확대 뷰의 feature marker가 그려지지 않았다.
- 수정 `7d100e3db`: runtime에 `public`을 복사하고 live UI 검사에 worker/shared HTTP 응답 확인을 추가했다. Docker production build·이미지 내부 asset 확인·E2E TypeScript 검사는 통과했다. PR CI와 운영 배포 후 live UI 검증은 진행 중이다.
- **다음 한 작업: PR CI green 확인 → Manager가 관리하는 Map 전환으로 candidate 반영 → 인증된 read-only live UI E2E → PR #1340 머지.**

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

## 2026-10-17 — T-MAP-02 timeout 문서 정합: 브랜치 docs/track2-http-timeout-contract-20261017

**다음 한 작업: 문서 독립 리뷰·CI 후 머지 → coordinator가 T-MAP-02 첫 prod 배포 generation 근거 확인.**

- connect 기본 4 s·geo/transport read 기본 10/30 s와 재시도/전체 deadline의 차이를 현행 소스에 맞췄다.
- 구현 523d98cc는 main e937b38d에 포함됐다. 제품·운영 상태는 변경하지 않았으며 배포 완료로 닫지 않았다.

## 2026-10-17 — 통합 planner flake 결정화(T-TEST-PLANNER-INDEX): 브랜치 `fix/t-test-planner-index`

**다음 한 작업: CI 초록 → 리뷰 → 머지.**

- 바뀐 것: `tests/integration/test_tvn34_public_projection_spine.py` 한 파일(REINDEX·비공개 행 seed·plan 전문), acceptance 구현
  메모. 원인과 재현은 journal 2026-10-17.

## 2026-10-16 — geo 릴리스 구현 반영 문서(T-GR-07, doc-only): 브랜치 `docs/t-gr-07-geo-release-docs`

**다음 한 작업: 즉시 머지(doc-only) → T-TEST-PLANNER-INDEX(통합 planner flake 결정화).**

- 바뀐 것: ADR-109(accepted)·README, runbook 신규·runbooks 인덱스, `address-geocoding.md`·`integration-map.md`·MOIS/concierge
  ETL·`feature-id-determinism.md`·ADR-108 표식, tasks/tasks-done, CHANGELOG.
- 운영 메모: 센서 켜기 전 확인·MOIS 수동 실행 후 skip은 runbook §3·§4.

## 2026-10-16 — admin UI geo 릴리스 화면(T-GR-06): 브랜치 `feat/t-gr-06-geo-releases-ui`

**다음 한 작업: CI 초록 → 리뷰 → 머지 → (배포는 coordinator) → T-GR-07(문서 마감).**

- 바뀐 것: `src/app/admin/ops/geo-releases/*`, `src/api/geoReleases.ts`, nav, mock·live Playwright 스펙, live 시나리오 카탈로그,
  화면 체크리스트 행·메모, `ReplayIncomplete` 문구, `ops_geo_releases.py` 필드 주석(OpenAPI 불변).
- 바뀌지 않은 것: OpenAPI·gen:types, `/admin/issues`·features 목록.
- 운영 메모: replay 뒤에도 stale 주소 finding은 다음 fetch까지 열려 있다(정상).

## 2026-10-16 — records resource replay 모드(T-GR-08): 브랜치 `feat/t-gr-08-replay-mode`

**다음 한 작업: CI 초록 → 리뷰 → 머지 → 배포 → T-GR-06(admin UI `/admin/ops/geo-releases`).**

- 바뀐 것: `dagster/source_replay.py`, records resource 6개의 `source_mode`, asset 6개(provenance·sync state 생략·선읽기),
  `infra/source_replay_repo.py`·client 읽기, core replay 상수(9 operation launchable, MOIS 제외), 테스트, ADR-109 결정 7 결과.
- 바뀌지 않은 것: OpenAPI(이유 값 이름 `replay_not_launchable_before_t_gr_08`은 계약이라 그대로), 스키마, MOIS 적재 경로.
- **운영 주의.** (1) 릴리스 계획의 MOIS 항목은 센서가 내지 않는다 — 운영자가 MOIS job을 수동 실행하고 그 항목을
  skip해야 계획이 끝난다. MOIS fetch는 소스 DB TTL 안에서만 쿼터 0(TTL ≥168 권고). (2) replay run은 sync state·curation
  seal을 쓰지 않는다 — dataset "마지막 성공"이 replay로 갱신되지 않는다. (3) dagster CI job이 `python-datagokr-api`를
  설치한다(replay golden).

## 2026-10-16 — geo 릴리스 센서(T-GR-05): 브랜치 `feat/t-gr-05-geo-release-sensor`

**다음 한 작업: CI 초록 → 리뷰 → 머지 → 배포(센서는 STOPPED로 들어간다 — odroid geo mv_refresh 실측 뒤 켠다) →
T-GR-06(admin UI) / T-GR-08(replay — 게이트를 연다).**

- 바뀐 것: `dagster/geo_release_sensor.py`(센서·tick 규칙), definitions 등록, repo·client 항목 전이 셋, 테스트.
- 바뀌지 않은 것: 계획 규칙(공용 함수), Manager `dagster.yaml`(새 pool·limit 없음).
- 리뷰 반영으로 바뀐 것: migration 409(항목 사유 `superseded`·`canceled`), admin OpenAPI `state_reason` enum(**PinVi 재vendor
  필요**), `geocoding.open_geo_client`, MOIS 이어 달리기 센서가 릴리스 run을 건너뛴다.
- **운영 주의.** (1) **T-GR-08 전에는 replay 항목(MOIS·datagokr fileData·standard_data)이 든 계획이 `running`으로 남는다 —
  센서를 켜도 완료를 기대하지 말 것.** (2) `attempt_seq`는 단조라 sweep 뒤에도 재요청 상한이 누적된다. (3)
  `failed(run_not_launched)`·`failed(canceled)`는 최종 상태다 — 다시 돌리려면 운영자 `replan`.

## 2026-10-16 — geo 릴리스 계획 표·계획 함수·admin API(T-GR-04): 브랜치 `feat/t-gr-04-geo-release-plan`

**다음 한 작업: CI 초록 → 적대 리뷰 → 머지 → PinVi admin 스냅샷 재vendor(Map API 배포 **전**) → 배포(408) → T-GR-05(센서).**

- 바뀐 것: migration 408·head-schema, `infra/geo_release_repo.py`, `coverage()`, core 계획 상수, client 래퍼, admin
  `/v1/ops/geo-releases` 5 operation(`openapi.json`), lint·통합·API 테스트, `DatasetRef` 관측 필드.
- 바뀌지 않은 것: 적재 경로, Dagster 정의(센서는 T-GR-05), user·service OpenAPI.
- T-GR-05에 넘기는 것: `launch_blocked_reason`이 있는 항목은 내지 않는다(replay 게이트 — T-GR-08이
  `SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS`를 채운다), `complete_plan`에 sigungu resolver를 넘긴다, 링크 변경 stream
  이벤트 재검토. 항목은 이미 run 단위다(MCST 항목 1개).

## 2026-10-16 — 적재 경로의 geo 재해석(T-GR-03): 브랜치 `feat/t-gr-03-stale-stamps`

**다음 한 작업: CI 초록 → 적대 리뷰 → 머지 → 배포(롤아웃 첫 run이 스탬프를 채운다 — 격리 스택에서 비용 실측) → T-GR-04(계획 표·
`coverage()`·admin API).**

- 바뀐 것: `GeoLoadContext`·`load_bundle` geo 재해석, client·wrapper 전달, MOIS 토큰 조건·evidence·표식, concierge 규칙·해시,
  run 빈 답 가드(행 단위 최종 빈 답), 토큰 선행 감싸개, 변환 함수 lint, 테스트, ADR-109 결정 2 보강, acceptance 구현 메모.
- 바뀌지 않은 것: 스키마(407 그대로), OpenAPI, price 경로(geo 없음 → 스탬프 0).

## 2026-10-16 — `docker-buildx.sh` `$!` 경주 수정: 브랜치 `fix/buildx-archive-pid-race`

**다음 한 작업: CI 초록 → 리뷰 → 머지.** 이 수정은 Track 1/2와 독립이다(T-GR-03 #1328의 "다음 한 작업"은 그대로).

- 바뀐 것: `scripts/docker-buildx.sh` 정리(`jobs -p`), `tests/unit/test_deploy_automation.py`(스스로 끝나는 가짜 writer·
  고아 단언·결정적 경주 재현), dev 의존성 `pytest-timeout`.

## 2026-10-16 — run-scoped geo 현재 토큰 resource·`geo_applied` 배선(T-GR-02): 브랜치 `feat/t-gr-02-geo-dataset-resource`

**다음 한 작업: CI 초록 → 적대 리뷰 반영 → 머지 → T-GR-03(stale 분기·스탬프·
빈 답 가드·MOIS·concierge — `current_dataset`/`geo_applied`를 client·infra 적재 함수로 넘긴다).**

- 바뀐 것: `fetch_current_dataset`·`geo_dataset_mismatch`, resource `kor_travel_geo_dataset`, asset·MCST `geo_applied`,
  적재 wrapper `geo_*` 메타, offline upload·CLI 팩토리 호출, 테스트 3종, CHANGELOG·acceptance 구현 메모.
- 바뀌지 않은 것: 적재·스탬프 동작, client·infra 시그니처, MOIS 경로, OpenAPI.

## 2026-10-15 — 지오코딩 스탬프 표·geo 데이터셋 토큰(T-GR-01): 브랜치 `feat/t-gr-01-geocode-stamps`

**다음 한 작업: CI(unit 3·integration 2 lane·lint) 초록 → 적대 리뷰 → 머지 → T-GR-02(run-scoped 현재 토큰 resource·
`geo_applied` 배선). 407은 표 하나라 배포는 평소 전진 배포에 실린다.**

- 바뀐 것: migration 407·`head-schema.sql`·migration graph, DTO·repo·geo client(`dataset_version()`·`dataset` 파싱·빈 답
  계수), 런타임 ACL 선언, ADR-109 결정 5 소유자 결정(첫 토큰 = 기준선), acceptance §T-GR-01 구현 메모, CHANGELOG.
- 바뀌지 않은 것: provider 모듈·`Address`·`ReverseGeocoder`·적재 경로(아직 스탬프를 쓰지 않는다)·OpenAPI.

## 2026-10-15 — geo·transport connect timeout 분리(T-MAP-02): 브랜치 `feat/t-map-02-connect-timeout`

**다음 한 작업: CI(unit 3·integration 2 lane·lint) 초록 → 적대 리뷰 → 머지 → 첫 prod 배포(해제 조건, 소유자 결정 2026-10-15) —
배포 generation을 acceptance §T-MAP-02에 적는다. 그다음 T-GR-01(PR-1, migration 407).**

- 바뀐 것: 설정 필드 2개·팩토리 2개, geo 생성 지점 8곳·transport 3곳, 문구(GEO_HEAVY_POOL·MOIS 동시성·transport URL·
  `.env.example`), 테스트 3종(팩토리 값·SYN 드롭 connect 상한·생성 지점 lint), CHANGELOG. 근거는 journal 2026-10-15.
- 바뀌지 않은 것: read timeout 값(geo 10 s·transport 30 s), pool 술어·동시성 값, OpenAPI, Manager compose.

## 2026-10-15 — ADR-110 사실 갱신(odroid 이전 실행됨) + T-GR-00-LEDGER 종결 이관: 브랜치 `docs/adr-110-odroid-facts`

**다음 한 작업: T-MAP-02(connect timeout 분리, 코드 PR) — 해제 조건은 소유자 결정(2026-10-15)으로 "머지 뒤 첫 prod 배포".
그다음 T-GR-01(PR-1, migration 407). Track 1의 '없음 → 첫 data_token = 기준선' 규칙(소유자 결정)은 T-GR-04/05가 구현한다.**

- 바뀐 것: ADR-110 "사실 갱신(2026-10-15)" 절과 포트·머지 상태 갱신, `integration-map.md` §1~§4, CLAUDE.md geocoding 줄,
  ADR README, ADR-109 역포인터(기준선 소유자 결정), T-GR-00-LEDGER `[x]`·이관, acceptance §T-MAP-02 해제 조건(소유자 결정). 실측은 journal 2026-10-15.
- 바뀌지 않은 것: 코드·`.env.example`·OpenAPI·n150(읽기만)·ADR-110의 결정과 열린 결정(전부 proposed 그대로).

## 2026-10-15 — journal·tasks-done 다음 경계 분리(T-GR-00-LEDGER) + T-GR-00·T-MAP-01 종결 이관: 브랜치 `docs/t-gr-00-ledger`

**다음 한 작업: lint.yml 초록 → 머지(doc-only) → ADR-110 사실 갱신 doc-only PR(2026-10-14~15 geo·weather·transport의
odroid 실제 이전·포트 통일·Manager compose 기본값 — 같은 PR이 T-GR-00-LEDGER `[x]`·이관을 싣는다) → T-GR-01(PR-1)·T-MAP-02.**

- 바뀐 것: `journal.md` 2026-09-20~25 8건 → `docs/archive/journal-2026-09e.md`, `tasks-done.md` 2026-08-04~05 2절 →
  `docs/archive/tasks-done-2026-08a.md`(상대 링크 4개 `../` 재기준화), 두 인덱스 표 갱신. T-GR-00(#1315)·T-MAP-01(#1316)
  `[x]`·tasks-done 이관(둘 다 2026-10-13 머지·lint.yml 초록 확인). 실측·검산은 journal 2026-10-15와 acceptance §T-GR-00-LEDGER.
- 바뀌지 않은 것: 코드·테스트·OpenAPI·`tasks-acceptance.md`의 다른 절·n150.

## 2026-10-13 — 공용 PG lock table 고갈(53200) 근본 수정(ADR-111): 브랜치 `fix/bulk-curation-locks` (PR #1319, draft)

**다음 한 작업: CI(PostGIS 두 lane 포함) 초록 → 소유자 머지 → 아래 배포 순서. reconcile sensor는 2026-10-13
12:59:54Z부터 prod에서 꺼져 있다 — `alembic_version`이 `406_feature_write_gate`가 되고 함수 정의를 확인하기
전에는 다시 켜지 않는다.**

배포 runbook(n150, 운영자 — prod는 읽기 외에 이 순서로만 바꾼다):
0. **사전 점검.** `~/preflight.sh`가 PASS일 때만 시작한다. 머지된 main 체크아웃에서 호스트 스크립트 다섯을 다시 맞춘다
   (`scripts/n150/README.md`) — `sudo install -o root -g root -m 0700 scripts/n150/chain17.sh scripts/n150/chain16.sh
   scripts/n150/repin.sh scripts/n150/run-d2.sh scripts/n150/adjudicate.sh /root/` (호스트 `chain16.sh`는 아직 느슨한 D1 게이트다).
1. **pair를 명시해 배포.** ssh 세션에 걸지 않고 systemd-run 유닛으로 띄운다(`chain17.sh` 인자 여섯:
   `MAP REASON REBUILD_UNIT EXECBUILD_UNIT D2_UNIT TAG`):
   `MAP=<merged main sha40>; PINVI=2fa1c166fadc7f744e5179738c97b4b136d08351; T=adr111-$(date -u +%m%d%H%M)`
   `sudo systemd-run --unit=chain17-$T --property=StandardOutput=append:/root/chain17-$T.log --property=StandardError=append:/root/chain17-$T.log env PINVI_OVERRIDE=$PINVI /root/chain17.sh $MAP "ADR-111 gate lock (#1319)" rb-$T eb-$T d2-$T $T`
   → `journalctl -u chain17-$T`·`/root/chain17-$T.log`로 끝까지 본다. 끝나면 `ktdctl pin show`로 원장이 ($MAP, $PINVI)인지 확인한다.
2. **스키마 확인**(Map API 컨테이너 DSN에서 유도한 map DB, 읽기만):
   `SELECT version_num FROM alembic_version;` → `406_feature_write_gate`.
   `SELECT pg_get_functiondef('feature.finalize_provider_curation_root'::regproc)` → `pg_try_advisory_xact_lock(hashtextextended('feature-write-all'`
   포함, `'feature-write:'` 없음. `SELECT proname FROM pg_proc WHERE prosrc LIKE '%feature-write:%' ORDER BY 1;` → 단건 writer
   여섯만(approve·archive/create/patch curation item·manual item·promote). `to_regprocedure('feature.finalize_provider_curation_receipts(bigint,uuid,text,text)')`
   → NULL.
3. **sensor가 아직 꺼져 있는지 확인.** Map Dagster GraphQL(`http://127.0.0.1:11002/graphql`)에서
   `feature_operation_reconciliation_sensor`의 `sensorState.status`가 `STOPPED`인지 본다(2026-10-13 12:59:54Z에 운영자가 껐다).
4. 그 뒤에만 `feature_operation_reconciliation_sensor`를 켠다. root `97ac4e01-…`가 다음 tick에 완결되는지
   (`ops.import_jobs.status='done'`) 본다. sensor는 main 그대로라 실패하면 그 tick을 실패로 두고 30초 뒤 다시 한다 —
   그때는 다시 끄고 원인을 본다(재시도 설계는 `T-RECONCILE-RETRY`).
5. **문제가 생기면** sensor를 멈추고 앞으로 고친다(406은 forward-only — 405 재배포를 약속하지 않는다).

- 바뀐 것: alembic 406(대량 writer 8개 gate 배타 — root 완결만 try-lock·55P03, 단건 6개 gate 공유 +
  `lock_timeout 5s`, 죽은 범위 재검사 제거, 호출자 없는 `finalize_provider_curation_receipts` DROP), API 55P03 → 503
  `LOCK_TIMEOUT`, manifest 해석의 일시 실패를 guard 거부로 감싸지 않음, lint(호출·trigger 전개)·격리 DB 통합 테스트,
  ADR-111. reconcile sensor 재시도 설계는 되돌리고 `T-RECONCILE-RETRY`로 분리. journal 2026-09-16~19 7건 아카이브. OpenAPI 바이트 변경 없음(PinVi 재vendor 불필요).
- 바뀌지 않은 것: Manager `max_locks_per_transaction` 상향(별도 응급조치), prod 컨테이너·DB.

## 2026-10-13 — admin e2e 로드 실패 수정(ESM 전용 `@kor-travel/ui`): 브랜치 `fix/e2e-esm-kor-travel-ui`

**다음 한 작업: draft PR CI 초록 → 적대 리뷰 → 머지 → Map API 배포 → chain16 D1 재실행(11/11 기대) → M05.**
D1은 **Map API 배포 전까지 빨갛다** — `admin-scenario-catalog`의 갱신 요청 dialog는 prod overview가 Dagster tick 조회
시간 초과로 큐 sensor를 신뢰하지 못하는 동안 렌더되지 않는다(배포 전 D1 재실행: 10 passed / 1 failed, 그 하나가 이것).

- 바뀐 것: (1) `SESSION_COOKIE_NAME`을 의존성 없는 `src/lib/session-cookie.ts`로 옮겨 e2e가 ESM 전용
  `@kor-travel/ui/navigation`을 끌어오지 않는다. (2) `frontend.yml`·`scripts/verify-all-gates.sh`에 `e2e:list`(세 config
  `--list` + 커스텀 reporter 로드). (3) Map API Dagster GraphQL 세 문서의 `ticks`에 `afterTimestamp` 창(schedule 2일·sensor
  1시간, 창 안 tick 300 상한을 Definitions에 대조) + 효과 결박 테스트 `tests/unit/test_dagster_tick_window.py`, UI는 빈 창을
  "최근 2일/1시간 tick 없음"으로 표시. (3b) chain16 D1은 `--list` 개수만큼 passed여야 초록. (4) live spec 둘(home 행 찾기, catalog 전제 단언),
  live config `testIgnore` 대체 버그. 원인·실측은 journal 2026-10-13.
- 바뀌지 않은 것: vendored tgz, OpenAPI(PinVi 재vendor 불필요), n150(읽기 전용 live 실행·GraphQL 조회만).

## 2026-10-13 — chain17 B 단계 pair 회전 수정: 브랜치 `fix/chain17-rotate-when-pinvi-changes`

**다음 한 작업: CI(lint·unit) 초록 → 적대 리뷰 → 머지 → n150에서 `sudo install -o root -g root -m 0700
scripts/n150/chain17.sh /root/`로 재복사하고 `/root/chain17-pv.sh`를 치운 뒤, 실패했던 pair(Map `c4d17343`·PinVi `2fa1c166`)를
`PINVI_OVERRIDE=<sha40> /root/chain17.sh …`로 재실행해 B 단계가 회전(또는 이미 수동 회전됐으면 pair 일치로 skip)하는지 본다.**

- 바뀐 것: `scripts/n150/chain17.sh` B 단계 skip 조건이 원장 map·pinvi **둘 다** 일치할 때로 좁혀졌고 회전 뒤 검증도 pair다;
  `PINVI_OVERRIDE`(운영자 `-pv` 변형; 원장과 다른 PinVi를 올릴 때는 같은 Map이든 새 Map이든 준다)를 정본에 흡수;
  원장을 못 읽은 빈 값은 회전 시도 없이 멈춤; launcher 경로 `ROTATE` 변수. 효과 결박 테스트
  `tests/lint/test_chain17_rotates_when_only_pinvi_changes.py`(stub ktdctl·rotate-pinned-pair 위에서 B 단계 실행).
  journal은 §8 상한 초과로 2026-09-14~15 8건을 `docs/archive/journal-2026-09c.md`로 분리했다.
- 바뀌지 않은 것: Manager registry·launcher, chain16 이하, n150 호스트(읽기만). 원인·증거는 journal 2026-10-13.

## 2026-10-13 — geo·transport 호스트 odroid 이전(ADR-110 proposed, Track 2): 브랜치 `docs/adr-110-geo-transport-on-odroid`

**다음 한 작업: 이 doc-only PR을 `lint.yml` 초록 뒤 머지해 `T-MAP-01`을 닫는다(`[x]`·tasks-done 이관은 T-GR-00-LEDGER
PR — 단일 소유) → **T-GR-00-LEDGER(journal 분리)가 어느 코드 PR보다 먼저** → `T-MAP-02`(geo·transport client
connect timeout 분리 — `httpx.Timeout(<기존>, connect=<connect 필드>)` 꼴, 팩토리 하나씩, geo 8곳·transport 3곳)는 Manager·Track 1과 코드 의존이 없어 병렬 착수를
제안하되(ADR-110 열린 결정 6, 설계 §13 사슬과 다름 — 소유자 확인) `geocoding.py`를 T-GR-01과 공유하므로 늦은 PR이
리베이스하고, 배포는 **첫 호스트 플립(transport 4a) 전**이다.**
Map은 n150에 남고 값은 Manager가 갖는다 — Map 쪽에서 기다리는 외부 조건: (a) Manager ADR-58 머지·T-MGR-01b의 compose
`map-api → geo-api` 간선 삭제 뒤 n150 `ensure map` 성공, (b) transport 플립(설계 §11.2 4a/5; T-MGR-01c의 compose 기본값
파생물)은 **odroid plane healthy ∧ `targets validate` transport.host == odroid ∧ odroid `timedatectl` synchronized yes**
(ADR-110 결정 7 '2~4b' 행)가 PASS인 뒤에만 n150 `ensure map`(Map target 전 서비스 재생성, 옛 URL 든 컨테이너 0개) +
transport allow-list에 n150 LAN 주소 `/32`(오늘 파일은 `.env.server14`), (c) geo 플립(8a/9, 메모리 예산 조건 통과 시만)은
풀로드·mv_refresh·키 정책 적용 완료('8a/8b' 행) 뒤 다음 날 n150 `ensure map`(전 서비스) + (풀로드였으면) geo 소비자 키
재발급·root `.env` 재적용 + 키 경로 200 + Track 1 효과 분기(풀로드+수용이고 T-GR-05 배포면 계획 1건 / dump 복원이면
0건 / 센서 미배포면 해당 없음 — 수용 추천, 소유자 결정 대기). geo 키는 오늘도 대조되므로 이전 자체로
키 의미가 바뀌지는 않는다(ADR-110 컨텍스트 4 — `9-전` curl은 선택 smoke). 소유자 결정 — ADR-110 열린 결정 6건(BFF
경로·geo 적재 방식+재계획 수용/skip·키 정책(VWorld 폴백은 Map 가드와 충돌해 불가)·회로차단·task 접두사 `T-MAP-`
임시·T-MAP-02 착수 순서).

- 정본: ADR-110(결정·근거·전환 절차 발췌 — 본문이 정본; Track 2 설계 파일은 세션 scratchpad 출처로 보존되지 않는다).
  연동 문서 `integration-map.md` §1~§4와 CLAUDE.md geocoding 줄에 "계획(ADR-110 proposed, 미구현)" 표식으로 넣었다.
  구현 전까지 모든 서술은 계획이다. LAN 주소 리터럴은 `#508` redaction guard 때문에 호스트 이름으로 썼다. 1차 리뷰
  19 finding + 2차 리뷰 17 finding + 3차 리뷰 17 finding(HIGH 1·MED 5·LOW 11) 전부 반영, 기각 0(journal 2026-10-13
  항목). T-MAP-02 코드 사양은 `httpx.Timeout(<기존>, connect=…)`이다 — `Timeout(connect=, read=)` 둘만은 httpx 0.28.1에서
  ValueError(설계 §13·§9.1 표기는 그 오류, Manager ADR-58·geo ADR-070 작성자에게 전달). 교차 ADR 셋(Manager 58·geo
  070·transport 014)은 병렬 PR에 작성돼 있고 미머지다.
- 코드 변경 없음. `.env.example:198,234` standalone 주석과 `GEO_HEAVY_POOL`/`mois_geocode_concurrency` 근거 문구 갱신은
  T-MAP-02 코드 PR에 싣는다.

## 2026-10-13 — geo 릴리스 재지오코딩 설계(ADR-109 proposed): 브랜치 `docs/adr-109-geo-release-regeocode`

**다음 한 작업: 이 doc-only PR을 docs lint 초록 확인 뒤 즉시 머지해 `T-GR-00`을 닫는다 → `T-GR-00-LEDGER`(journal·
tasks-done 다음 경계 분리, doc-only — `T-GR-00`의 `[x]` 전환·tasks-done 이관을 함께) → `T-GR-01`(스탬프 표
406·`dto/geo_dataset.py`·`dataset_version()`·`GeoCallStats.empty`) 착수.** 실측 `journal.md` 208,660 B·`tasks-done.md`
200,699 B(acceptance §T-GR-00-LEDGER). 소유자 결정 — ADR-109 "열린 결정" 13건, 특히 task 접두사(`T-GR-`
임시)·센서 기본 RUNNING·replay 적용 범위; 미결이면 권장안 기준(결정별 영향 조문은 §T-GR-00). T-GR-01은 결정
비의존이다. 코드는 geo ADR-069 배포와 병렬 가능하고(`dataset` 없는 응답 허용), 활성화 검증은 geo 배포 뒤다.
PR 묶음·의존은 acceptance §T-GR-00.

- 정본: ADR-109(결정·근거) + `docs/etl/address-geocoding.md`(코딩용 상세·테스트 목록). 연동 문서 `integration-map.md`
  §1·§2·§4에 "계획" 표식으로 넣었다. 구현 전까지 모든 서술은 "proposed, 미구현"이다.
- 배포 제약(T-GR-04 뒤): PinVi admin OpenAPI 스냅샷 재vendor가 Map API 배포보다 먼저.

## 2026-10-13 — 고속도로 돌발 job pool 고갈 수정: 브랜치 `fix/highway-incidents-pool`

**다음 한 작업: 적대 리뷰 → PR·CI(통합 두 lane)·머지 → 다음 Map pair 회전 뒤 `feature_notice_transport_highway_incidents_job`
수동 첫 적재 재시도.** PR은 열지 않았고 prod에는 아무것도 하지 않았다. 원인·증거는 journal 2026-10-13.

- `provider_run_lock` 본문이 lock 연결 하나를 순차로 쓴다(Dagster pool 1/0, ADR-107). GC drain도 같은 수정.
- 미결: 큐 경로 strict 실패 증거 client는 실패 경로에서 두 번째 연결을 요구한다(설계 결정 필요).

## 2026-10-13 — weather 잔재 정리: 브랜치 `chore/weather-remnant-cleanup`

**다음 한 작업: CI 전량 green → PR(조정자가 연다)·머지. 배포 영향 없음** — 죽은 코드·주석·문서만 바뀌었고 migration·
OpenAPI·런타임 경로 변화가 없다. 다음 Map pinned-pair 회전 때 이미지에 실린다.

- 지운 것: `make_weather_value_key`(+테스트), `SOURCE_PRIORITY`의 kma/airkorea, api 테스트의 고아 `_CURATED_*` 블록,
  admin UI의 weather 라벨·색. 남긴 것과 이유는 journal 같은 날짜 항목.
- 새 백로그: `T-WX-VNEXT-FREEZE`·`T-WX-SOURCEROLE`·`T-WX-DTO`·`T-WX-NOTICE-CLOSE`(+ Manager KMA env 외부 추적).

## 2026-10-12 — MOIS 재개형 chunk commit 적재(ADR-108): 브랜치 `feat/mois-chunked-resumable-load`

**다음 한 작업: 소유자 결정(ADR-108 "열린 결정") → 적대 리뷰 → PR·CI·머지 → Map pair 회전 → Manager
`feat/map-mois-source-volume` 설치 → `docs/etl/mois-license-feature-etl.md` §13.2의 업종 하나 검증 run.** 전체 적재는 그
검증 뒤 §13.3(이어 달리기 sensor를 켠다). PR은 열지 않았고 prod에는 아무것도 하지 않았다.

- 재개 키 = `(slug::mng_no, raw_payload_hash)` + primary feature active. 이미 그대로인 행은 지오코딩·변환 없이 재관측만,
  chunk(업종 안 500행)마다 transaction 하나. 새 표·마이그레이션 없음.
- 지오코딩: geo에 batch endpoint 없음 → bounded 동시 선조회(기본 2) + run 수명 LRU. 원천 `legal_dong_code` 행·적재된 행은 조회 안 함.
- run 크기: 기본 4시간 상한 → `budget_exhausted` tag → 이어 달리기 sensor(STOPPED). retry 1회. 큐는 MOIS를 건너뛴다.
- 원천 SQLite: 이미지 기본 `/opt/dagster/state/mois/mois_source.db`(appuser). 운영 volume은 Manager 브랜치.
- 설치 순서 주의: **Map 회전이 먼저**, Manager compose가 뒤(새 named volume이 이미지 디렉터리 소유자를 물려받아야 한다).

## 2026-10-07 — entrypoint 봉인에서 `api grpc` 제거: 브랜치 `chore/entrypoint-drop-api-grpc`

**다음 한 작업: CI 전량 → PR(조정자가 연다)·머지. 배포는 하지 않는다 — 다음 Map pinned-pair 회전 때 이미지에 실려
반영된다.** 안전한 이유: 운영 Manager compose(#1295)와 standalone compose(#1304)가 이미 `code-server start`로 띄우므로
최상위 `api grpc`를 띄우는 곳이 없다.

- `docker/dagster-entrypoint.sh` production 봉인은 `/usr/local/bin/dagster code-server start -h 127.0.0.1 -p <port> -m
  kortravelmap.dagster.definitions`(정확한 9-argv) 하나만 받는다. `api grpc`는 다른 모양과 같은 문구("production Dagster
  code server argv does not match the sealed launch contract")로 거부한다. local-dev의 preflight 분기에서도 뺐다.
- proxy가 띄우는 자식(`python -m dagster api grpc --socket …`)은 entrypoint를 지나지 않으므로 영향이 없다(n150 실측).
- 테스트: rejects parametrize에 `api grpc` 추가(먼저 RED 확인), accepts는 `code-server start` 정확한 argv 하나.

## 2026-10-06 — Map·PinVi 공통 Dagster 구현·재구축·live·머지 완료

[Common #28](https://github.com/digitie/kor-travel-common/pull/28) → [Map #1303](https://github.com/digitie/kor-travel-map/pull/1303) → [PinVi #576](https://github.com/digitie/pinvi/pull/576) 순서로 병합했다. Common·Map은 merge commit, PinVi는 main ruleset의 squash-only·linear history 정책에 따라 squash로 병합했다. PinVi 재구축 원본0058369와 검증 HEAD92d0f40는 remote tags codex/pinvi-map-runtime-20261006·codex/pinvi-map-reviewed-20261006 및 유지한 feature branch에 원본 이력을 보존했다. 저장소 설정은 변경하지 않았다. 최종 문서 포함 HEAD의 필수 CI, Common·Map main ancestry와 PinVi 보존 참조, 병합 tree 일치를 확인했다. 실제 paired 재구축, 두 독립 FULL 제품 리뷰·가이드 리뷰·최종 문서 리뷰, Chromium/Firefox×Map/PinVi live UI4건·8캡처, ACL40·D1 11건·D2 normal/attempt0·소유 fixture 정리·잔존0 검증을 완료했다.

머지 후 운영 API/UI/Dagster 여섯 이미지의 healthy 상태·설치 코드·배포 source·committed transaction이 기존 성공 증거와 같음을 실제 read-only 재확인했다. 최종 제품 Common a960bdb/Map1a3c467/PinVi0058369에 문서만 추가됐으며 재구축·장애 주입을 머지 HEAD에서 새로 실행한 것으로 집계하지 않는다. 격리 Map native raise/crash/stall·동시 정상 run·수동 복구는 관련 설치 코드/버전 불변 범위에 한정한다. 공유 운영 worker 장애 주입·운영 RSS 감소율은 미실측이다.

이 요청의 T-COMMON-DAGSTER는 완료 원장으로 이동한다. 기존 외부 transport/HAProxy 및 다른 미완료 task는 유지한다. 다음 작업은 기존 열린 backlog의 우선순위를 따른다.

[머지 후 실제 상태 증거](reviews/common-dagster-2026-10-05/evidence/final-postmerge-runtime-attestation.json), [가이드·실패·리뷰·수용 이력](reviews/common-dagster-2026-10-05/README.md). 아래 문단은 각 작성 시점의 이력이며 이 절이 최신 상태다.

## 2026-10-06 — Map·PinVi 공통 Dagster 실제 재구축·live 수용 완료

Common a960bdb, Map 1a3c467, PinVi 0058369의 제품113파일 두 독립 FULL 리뷰와 가이드 리뷰를 통과했다. 공용 Python은 bounded HTTP·경량 child health·실행 복구 정책을 제공하며 앱의 operation/lease/claim·비멱등 쓰기 계약을 유지한다. 요청별 응답4MiB/10초와 정리50ms, DB pool/step 제한·100개 batch를 적용했다. Map tick 조회의 오래된 batch history 정렬 지연은 상태 조건을 명시하여 native indexed LIMIT 경로로 줄였고 실제 summary/UI 복구를 확인했다.

운영 paired 재구축과 설치 source·관련 Common bytes·실제 이미지 identity·여섯 서비스 healthy를 검증했다. Chromium/Firefox×Map/PinVi 실제 UI4건과 캡처8개를 직접 확인했다. ACL40·D1 11건·D2 정상 수용/validator·소유 fixture purge1/7·잔존0/ACTIVE없음/BLOCKED없음까지 통과했다. Common의 ESM export를 읽기 위한 type=module은 별도 테스트 이미지 package.json에만 추가하고 실제 마지막 layer/semantic delta를 증명했다. 앞선 모든 실패·초기 BLOCK와 수정 후 PASS 원문은 보존한다.

격리 native Dagster에서 실제 raise·worker crash·stall/timeout 뒤 수동 재시도와 동시 정상 job을 확인했다. 최종 Map 운영 Dagster 이미지의 관련 설치 코드와 버전이 이전 격리 이미지와 같은지, 실제 최종 이미지 ID가 배포 기록과 맞는지 독립 검증했다. 이 결과는 해당 불변 코드 범위에 한정해 이어받는다. 공유 운영 DB의 worker 장애 주입이나 운영 RSS 감소율 실측으로 설명하지 않는다. 유한 응답·batch·동시성 구조와 합성 메모리 측정은 운영 RSS와 구분한다. 기존 인간 dirty checkout·외부 transport/HAProxy 후속은 보존한다.

다음 한 작업은 문서 포함 exact HEAD CI 통과 후 Common #28 → Map #1303 → PinVi #576 순서로 merge commit 병합하는 것이다. 제품 Git pin의 ancestry를 보존한다. 이 절이 현재 상태이며 아래의 진행 중/NOT_RUN 문단은 이전 시점의 이력이다.

[실제 검증·리뷰 원문과 실패 이력](reviews/common-dagster-2026-10-05/README.md), [공통 적용 가이드](runbooks/common-dagster.md).

# resume.md — 현재 진척도와 다음 한 작업

## 2026-10-05 — Map·PinVi 공통 Dagster 보강 (진행 중)

ADR-107과 [적용·복구 가이드](runbooks/common-dagster.md)에 따라 공통 Python HTTP/Dagster·로그인·메뉴·대시보드를 채택했다. 요청별 연결·응답/시간 상한·활성 run 별도 조회·step/DB 연결/100개 batch를 적용한다. 쓰기 run 자동 복제 없이 기존 operation/lease/claim 복구 계약을 유지한다. [검증 기록](reviews/common-dagster-2026-10-05/README.md)의 고정 후보 2인 리뷰·운영 재구축·live·CI·merge를 완료해야 한다. 원래 인간 dirty checkout은 보존했다.

## 2026-10-05 — standalone compose code-server `code-server start`: 브랜치 `chore/standalone-compose-code-server-start`

**다음 한 작업: CI 전량 → PR(조정자가 연다)·머지. 배포 영향 없음(standalone compose·주석·문서만, prod는 Manager
compose).** 그 뒤 후속: `docker/dagster-entrypoint.sh` 봉인에서 `api grpc` 분기 제거(+ 수용 테스트 parametrize 정리) — 2026-10-07 `chore/entrypoint-drop-api-grpc`에서 처리.

- standalone healthcheck는 proxy health + 자식 `ListRepositories`(load error면 실패). n150 실측으로 CLI
  `grpc-health-check`는 load error에도 rc=0임을 확인했다.

## 2026-10-05 — 인계: 공용 Dagster 완주 이후 (Codex 등 다음 에이전트는 여기부터)

**다음 한 작업: [`docs/handoff/2026-10-05-shared-dagster-handoff.md`](handoff/2026-10-05-shared-dagster-handoff.md)를
읽고 §3 TODO를 이어간다.** 2b·2c(weather retention·겹침 skip)는 2026-10-07에 완료하고 배포했다. 다음은 2b의 새 retention 첫 run 확인(2026-10-07 16:45Z)이다. n150 변경 작업 전에는 반드시
사전 점검(`docs/handoff/n150-scripts/preflight.sh`)을 통과시킨다.

- prod(2026-10-07): Map `1a3c4673` · PinVi `0058369c` · Manager `b5f4dcfb`(#466 C6c family 규칙) ·
  transport `c6105233` · weather `a44ed9c3`(python-kma-api `12e7f1f1`). concierge까지 6개 location이 모두 공용 Dagster plane에 있다.
- 2026-10-07: Map main frontend `audit:high`가 10-06부터 빨갛던 것을 #1309(sharp 0.35.5 · source-map-js 1.2.2)로 닫았다.
  entrypoint 봉인에서 `api grpc`를 뺐다(#1308). 이 변경은 다음 Map 회전 때 prod에 반영된다.
- 일정: ~10-19 weather DEFAULT purge, ~11-02 옛 Dagster 메타DB 5개 DROP.
- 소유자 확인 대기: OPNsense HAProxy Map UI `timeout server` 30s→120s.

## 2026-10-04 — D2 restored api-audit: 브랜치 `fix/d2-fixture-restored-audit`

**다음 한 작업: PR(조정자가 연다) → CI 전량 → 머지 → 다음 Map pinned pair. 그 전에 현재 BLOCKED
(`live-20261004102457-782ce6e6b79b`)는 n150 `~/d2-adjudicate-782ce6e6.sh --dry-run` → `--execute`로 판정한 뒤
`/root/run-d2.sh`를 다시 돈다.**

- spec이 실패한 run은 이제 `test-failed-restored`로 기록되고 `recover`가 통과할 수 있다(`api-audit --expect restored`).
- **소유자 후속(edge, 저장소 밖):** OPNsense HAProxy의 Map UI backend `timeout server`를 30초에서 늘려라(예: 120초).
  2026-10-04 D2의 admin create가 약 30초 걸려 edge에서 잘린 것으로 보인다. 별도로 그 create가 DB에서 30초 걸린 원인
  (feature insert +12초, override +29초, 당시 load 약 9)도 조사 대상이다.
- a68c2b7d로 다시 도는 D2는 여전히 엄격한 감사를 쓴다 — 같은 절단이 다시 나면 같은 방식으로 BLOCKED된다.

## 2026-10-04 — transport 소비 후속(Low 다섯): 브랜치 `fix/transport-consumer-lows`

**다음 한 작업: CI 전량 + 적대 리뷰 → PR·머지(소유자 지시: PR은 머지 직전에) → 다음 Map pinned pair. 배포 영향 없음
(migration 없음).**

- 재시도 예산은 run 하나에 하나(`upstream_retry.sharing_run_retry_budget`) — 큐 run의 scope들이 나눠 쓴다.
- transport 503은 `retryable=True` step 실패, 공항 0건은 `transport_empty`, 비-JSON 본문은 `transport_malformed_upstream`.
- 가격 feature는 place locator로 bjd·시도·시군구를 이어받는다(`list_primary_place_locator` 행 5-tuple).
- 관리 UI 로그인 감사 fetch 3초 timeout(실패는 `console.warn`). transport 설정 문서는
  `packages/kor-travel-map-dagster/README.md`가 정본.
- 적대 리뷰 반영: locator 지역 코드는 행별 관대 처리, `retryable=False` transport 실패는 asset step 재시도를 끈다,
  큐 경로 503은 재큐잉하지 않는다(결정). 배포 뒤 첫 가격 적재가 가격 feature 주소를 한 번 고쳐 쓴다.

## 2026-10-02 — Dagster entrypoint가 `code-server start`를 받는다: 브랜치 `fix/dagster-entrypoint-code-server`

**다음 한 작업: CI 전량 + 적대 리뷰 → PR·머지 → 다음 Map pinned pair 배포(이 이미지가 핀에 오른다) → 그 뒤에만
Manager `fix/dagster-code-server-reloadable` 설치(Map code-server를 `code-server start`로 바꾼다) → C7 재실행.**

- 순서가 계약이다: 이 이미지 전의 Map은 `code-server start`를 봉인에서 거부하므로 Manager compose를 먼저 설치하면 Map
  code-server가 뜨지 않는다. 이 이미지는 `api grpc`도 받으므로 지금 compose 아래에서 먼저 핀에 올려도 안전하다.
- production exec가 `PYTHONSAFEPATH=1`을 내보낸다 — `-I`가 이어지지 않는 자식 Python의 cwd-on-`sys.path`를 막는다.
- 후속: standalone `docker-compose.yml`의 code-server 전환(+자식에 묶은 probe), 전환이 끝나면 봉인에서 `api grpc` 제거(둘 다 처리: #1304, 2026-10-07 `chore/entrypoint-drop-api-grpc`).

## 2026-10-02 — 주유소·휴게소·돌발·공항 원천 이관(ADR-106): 브랜치 `feat/transport-api-sources`

**다음 한 작업: 배포 순서 — transport `fix/fuel-latest-prices-incremental` → `feat/map-service-exports` 머지·배포(0022·0023,
`TRANSPORT_SERVICE_EXPORT_TOKEN`·`REST_AREA_COLLECTION_ENABLED=true`) → Manager 브랜치(토큰을 Map dagster에) → Map PR
머지 → 다음 Map pinned pair(migration 404 전진) → C7 재실행(`E2E_C7_SCHEDULE=feature_place_transport_airports_monthly_schedule`).**

- Map 이 여섯 dataset의 원천은 transport export다. transport가 내려가 있으면 해당 적재가 실패한다(오래된 값을 새 값처럼
  적재하지 않는다). 돌발은 transport 수집이 30분 넘게 성공하지 못하면 503 → Map run 실패 → notice를 닫지 않는다.
- n150 `.d2-live.env`의 C7 schedule·update operation 이름이 바뀐다(`feature_place_transport_airports_*`).
- transport export 계약은 pin하지 않는다(ADR-106 4번) — Map에 필요한 모양은 transport API를 직접 바꾼다.
- C7 기준 5(공항 operation)는 transport가 떠 있고 token이 맞아야 GREEN이다(`docs/runbooks/c7-prod-live-e2e.md`).
- 남은 것: transport 관리자 UI의 옛 `fuel_latest_prices` 읽기 모델 경고 코드(행이 사라져 표시되지 않음) 정리.

## 2026-10-01 — Map에서 날씨 feature·기상특보 notice 기능 삭제(ADR-105): 브랜치 `feat/remove-map-kma-dagster`

**다음 한 작업: CI 전량(통합 두 leg) + 적대 리뷰 → PR·머지 → 다음 Map pinned pair 배포(migration 401·402 전진, 되돌릴 수
없음, 백업 면제) → n150 `.d2-live.env`의 `E2E_C7_SCHEDULE=feature_place_krairport_airports_monthly_schedule` → C7 재실행.**

- weather kind 기능·KMA 특보 notice 기능을 Dagster·라이브러리·API·UI·DB에서 지웠다. 정의는 남는다. 산사태·교통 notice는 그대로.
- 402는 weather 전용 표 둘·함수 하나·인덱스 하나를 DROP하고 weather/KMA 특보 dataset을 비활성화한다. prod에서 실제로 지워지는
  행은 `ops.current_summary_runs` weather 2,875건뿐이다(feature 0행).
- **PinVi가 다음 짝을 막는다(배포 차단).** Manager `m05_isolated_harness.py`는 OpenAPI hash 불일치를 거부하고, PinVi
  `test_kor_travel_map_contract.py`는 `BeachPublicView.latest_weather`를 단언한다. 그래서 **PinVi PR
  (`chore/map-drop-weather`: Map OpenAPI 재vendor + 계약 테스트) → Map PR → pair 회전** 순서가 필수다. PinVi 날씨 자체는
  이미 kor-travel-weather를 쓴다.
- 같은 브랜치 후속 반영: run gate probe `map_run_heartbeat`, C7 `ops-c7-update-request-write`(krairport 큐 왕복),
  401 in-flight preflight, 403(KMA lineage 분기 제거), 핀 제거. 남은 것: Manager compose `KOR_TRAVEL_MAP_KMA_WEATHER_*`(Manager PR).

## 2026-10-01 — Map Dagster의 KMA 적재 경로 제거(ADR-104): 브랜치 `feat/remove-map-kma-dagster`

**다음 한 작업: CI 전량(통합 두 leg 포함) + 적대 리뷰 뒤 PR·머지 → 다음 Map pinned pair로 배포(migration 401 전진).**

- KMA job·asset·schedule·resource·큐 runner spec·handler binding을 지웠고 `401_retire_map_kma_refresh`가 카탈로그의
  KMA 적재 operation을 끈다. 재도입은 `test_map_dagster_has_no_weather.py`·`test_head_enables_no_kma_load_operation`이 막는다.
- 배포 영향(prod 읽기 전용 실측): Map KMA instigator·run 0(공유·옛 instance 모두), KMA 멤버십 import job·요청 0,
  KMA feature 0. 배포 뒤 Map location의 job 목록에서 KMA 5개가 사라지고 `/ops/datasets`의 KMA 갱신 capability가 없어진다.
- 후속: C7 러너 가족 정리(KMA 기반, 이미 실행 불가), `python-kma-api` 핀 제거, Manager compose `KOR_TRAVEL_MAP_KMA_*` env 제거.

## 2026-10-01 — Map 공유 Dagster plane cutover 완료, flip 전 drain 문서 정정: 브랜치 `docs/shared-plane-drain`

**다음 한 작업: 문서 PR 머지(소유자). 그 뒤 공유 plane soak 관찰(D6) — 옛 Map 전용 Dagster metadata DB는 보존(D1).**

- Map은 2026-10-01 05:54Z cutover로 05:58Z부터 공유 plane에서 돈다. C7 06:02Z GREEN.
- `docs/runbooks/docker-app.md` "공유 Dagster plane으로 옮기기 전의 drain"을 실제 절차로 고쳤다. writer drain은
  reconcile·run-status sensor까지 멈추고 run을 약 15초 뒤 끊으므로 flip 전 drain이 아니다. 절차는 자연 종료 →
  330초 대기 → `ops.import_jobs` 게이트 0 → queue는 열어 둔다(정본은 Manager topology §7·`dagster-shared-cutover.sh`).

## 2026-10-01 — Map shared-plane 차단 항목: 브랜치 `feat/dagster-shared-map-prep`

**다음 한 작업: CI 전량 + 적대 리뷰 뒤 머지 → 다음 Map pinned pair로 배포(Map 전용 instance에서 동작 불변).**

- run 조회(reconcile sensor, coalescing schedule 둘)는 `map_runs_filter()`로 Map code location만 읽는다. run-status
  sensor는 자기 location만 본다.
- API: `KOR_TRAVEL_MAP_API_DAGSTER_INTERNAL_GRAPHQL_URL`(호출) / `…_DAGSTER_GRAPHQL_URL`(보고·C7 hash). flip 때
  Manager가 호출 URL을 `http://127.0.0.1:11002/graphql`, 공개 URL을 `https://<dagster-host>/graphql`로
  렌더하고 allowlist에서 공개 host를 뺄 수 있다.
- n150 `/root/.d2-live.env`: 지금은 새 `repin.sh`(호스트 사본 재설치 뒤)가 `E2E_C7_PINVI_DAGSTER_SERVICE`를
  `pinvi-dagster-code-server`로 고치고 `E2E_C7_MAP_DAGSTER_CONTROL_PLANE=own`을 덧붙인다. flip 값(URL·hash·Basic
  Auth 파일)은 `scripts/n150/README.md`.
- flip 전 drain: 옛 instance에만 run이 있는 active operation을 먼저 끝낸다(`docs/runbooks/docker-app.md`).
  flip 뒤 reconcile은 Map run이 200건 이하면 null cursor로 처음부터 훑는다.

## 2026-09-29 — 공유 Dagster plane Map 준비(stage 0 + 3.1): 브랜치 `feat/dagster-shared-stage0`

**다음 한 작업: 브랜치를 CI 전량으로 확인하고 적대 리뷰 뒤 머지 → 다음 Map+PinVi pinned pair(chain17)로 배포.**

배포 체크리스트:

- [ ] **배포 전제(pool 이름 변경)**: pool을 쓰는 job의 QUEUED·STARTING·STARTED run이 0건이다. 확인은
  `docs/runbooks/docker-app.md` "pool 이름 변경 배포의 전제"의 읽기 전용 검사(exit 0)로 한다. 0건을 못 만들면 writer
  drain 아래에서 배포한다.
- [ ] 배포 뒤: 세 컨테이너의 `site-packages`에서 constraints에 나열한 패키지가 그 버전인지 본다(나열한 것만 고정).
- [ ] 배포 뒤: admin 운영 홈·pipeline 화면(runs 패널·run 상세)이 그대로인지 본다.

- 이미지·CI: `docker/constraints-dagster.txt`(나열한 패키지의 정확한 버전)를 API·Dagster Dockerfile과 CI 설치가
  `-c`로 읽는다. 올릴 때는 공유 host 이미지 먼저, 이 파일 나중.
- API/UI/C7/게이트의 Dagster 조회는 Map code location으로 좁혀졌다(journal 참조). pool은 `kor_travel_map.` 접두사.
- D4: Map은 DB에만 켜진 instigator가 없다(읽기 전용 확인). 남은 판단: run-status sensor의 `monitor_all_code_locations`.

## 2026-09-29 — Map DB 공용 PostgreSQL 이전 완료

**다음 한 작업: 72시간 관찰(~2026-10-02 11:30Z) 뒤 소유자 수락을 받아 12700 컨테이너 은퇴(§4.6, 수동, PGDATA 보존).**
관찰은 n150 `sudo MOVE_DIR=/root/map-db-move-20260929 bash /root/map-db-move-20260929/bin/40-monitor.sh <SINCE>`
(30분마다, ALARM은 기록용). 되돌리기는 같은 디렉터리의 `30-rollback.sh move`.

- Map `kor_travel_map`·`kor_travel_map_dagster`가 이제 `kor-travel-shared-postgres`(11000) 안에 있다(ADR-103, Manager ADR-53).
- Manager: #438 MT(공용 튜닝: shared_buffers 1GB·work_mem 64MB·max_wal_size 2GB·pg_prewarm 모든 DB·shm 1gb),
  #439 M2(이전: S1 — 새 superuser 없이 `shared_admin`을 부트스트랩 one-shot에만 secret 파일로, 백업 role 공용으로, D10).
  설치본 `3b282a7a`. 그 전 #434(stop grace·--no-deps), #435 M1(펜스·격리·연결 상한 38).
- 창(2026-09-29, `F:\dev\handoff\window\` 스크립트): Part A 10:25Z 공용 재생성(A7 20분 게이트 통과, 크래시 0·DSM 0) →
  Part B fence 10:55Z(감사 dump 12700에서) → M2 설치·env(DSN→11000) → rebuild(adopt, 3분, deployed) →
  verify V1~V7 0 FAIL → chain16 V8(ACL 40/40, D1 11, D2 passed) → backup V9(공용에서 dump, sha256 OK). 11:33Z 완료.
- 이전 직후 감시: 0 ALARM(연결 26/97, Map run 32 SUCCESS, prewarm leader 1, 백업 정상).
- Map 데이터는 정책대로 새로 재구축했다(features 0행이었다). 옛 ops·Dagster 이력은 감사 dump와 보존된 12700 PGDATA에 있다.

## 2026-09-28 — MP(Map DB 공용 이전의 Map 쪽 준비): 브랜치 `fix/shared-instance-readiness`

**다음 한 작업: MP를 CI 두 leg(alpine·glibc) 초록 + 적대 리뷰로 머지 → n150 호스트 스크립트를 MP SHA에서
0700 root로 재설치 → `/root/chain17.sh <MP_SHA> …`로 새 pair(MP + PinVi `c5be9eb4`)를 전용 12700 위에서
회전·D1/D2 초록.** 그 뒤 Manager 창(MT·M2)에서 이동한다(ADR-103, Manager ADR-53).

- `COLLATE "C"`: evidence export/backup twin, evidence restore, curation collection lock, cache target capture.
  감사 뒤 그대로 둔 곳과 이유는 커밋 메시지(`fix: glibc-safe text orderings …`)에 있다.
- CI `integration` 두 leg, 이미지 정본 `tests/integration/_postgis_image.py`.
- `scripts/n150/adjudicate.sh`·`repin.sh`는 Map API 컨테이너에서 DB 접근을 유도한다. `/root` 사본은 MP 머지 뒤
  재설치해야 한다(`scripts/n150/README.md` §설치, 0700 root, sha256 대조).
- MP는 OpenAPI 스냅숏을 바꾸지 않는다 — PinVi pair 계약 preflight가 그대로 통과한다.
- 적대 리뷰 반영(journal 참조): adjudicate 양성 대조, n150 스크립트의 API 컨테이너 조회를 D2 러너의 compose
  project로, repin의 source 값 대조, 효과 기반 인스턴스 탐지기, 두 lane의 수동 workflow·로컬 게이트.
  수동 `postgis-only.yml` 두 lane 초록(run 36421797357).
  - PR을 열 때 본문에 CI `integration` 두 leg의 URL을 적는다(required check가 없다).
  - 적대 리뷰 2차(09-29, journal 참조): n150 compose 조회의 stderr 차단(비밀 조각 누출), 탐지기 좁히기·유도
    결박, 판정 도구 읽기 전용 검사, 다섯째 잔여물 줄(fixture dataset), D2 러너의 fixture 대상 대조.
  - 남은 것(Map 밖, 소유자): `/opt/.env`의 `*_UI_ADMIN_PASSWORD_HASH` 넷을 작은따옴표로 감싸거나 `$$`로
    바꾸고, Map UI 관리자 비밀번호를 교체한다(hash 조각이 리뷰 transcript에 찍혔다).
  - 남은 것(Map 밖): 이동 창 사전 점검(스펙 §4.1 A0/A5)에 실행 중인 공용 컨테이너 `.Image`와
    `tests/integration/_postgis_image.py`의 `SHARED_GLIBC_POSTGIS_IMAGE` 대조 한 줄. API 이미지의
    `python -I -c 'import asyncpg'` smoke는 `docker-images.yml`이 OCI만 내보내 따로 load가 필요해 미뤘다.
- Manager ADR 번호: 이 이동은 **ADR-53**이다. ADR-52는 #433(공용 instance의 `init`·exec probe `-t 3`/`timeout 10s`·
  grace 300s·shm 512mb)이고 n150에 설치됐다(Manager `0fe0d97`, 공용 재생성 09-28 13:10:57Z). 아래 (저녁) 절의
  `stop_grace 180s`·`pg_isready -t 2`는 그 전 계획값이다.

## 2026-09-28 (저녁) — transport 개명 완료, 공용 PG 재시작 원인, Map DB 공용 이전 착수

**다음 한 작업: Map DB를 공용 PostgreSQL(11000)로 옮긴다(소유자 결정 C).** 명세·런북을 확정했고, 구현 1차
(Manager M1 펜스·MT 공용 튜닝, Map MP)가 돌고 있다. 그 뒤 M2(이전)와 이전 창이다.

- **소유자 결정**:
  - C: 위험을 받아들이고 옮긴다.
  - superuser S1: 새 superuser 없이 기존 `shared_admin`을 Manager가 돌리는 Map 부트스트랩 one-shot에만 주입한다.
    superuser가 필요한 것은 새 DB 부트스트랩 한 번뿐이다(bootstrap 게이트, untrusted 확장 postgis·pg_prewarm,
    400의 확장 소유자 검사). 런타임은 비-superuser다.
  - Map 정책대로 새로 재구축한다. 감사 dump와 옛 PGDATA는 보존하고, 검증 잔여 DB 4개는 옮기지 않는다.
  - Map 전용 튜닝을 공용에도 적용한다(`shared_buffers` 1GB, work_mem 64MB, max_wal_size 2GB, pg_prewarm이 모든 DB,
    shm 1gb, stop_grace 180s). 공용을 한 번 재시작해야 한다.
  - `kor_travel_map` 연결 상한은 floor(0.4×사용 가능 슬롯) = 38이다.
- **공용 PostgreSQL 반복 재시작 원인(유력, 적대 검증 유지)**:
  - 09-25~28에 5번 "exit code 2" 뒤 전체 재시작이 있었다(각 1~7분).
  - 실제 백엔드 크래시가 아니다. `init`이 없어 postmaster가 PID 1이다. 호스트 정체 때 `CMD-SHELL pg_isready`가
    5초를 넘기면 Docker가 `sh`만 죽이고, 고아가 된 `pg_isready`(exit 2)를 postmaster가 입양한다. PG16은 모르는
    자식의 비정상 종료도 크래시로 보고 클러스터를 리셋한다.
  - 고침은 공용 서비스에 `init: true`와 exec 형식 `pg_isready -t 2`를 두는 것이다. 튜닝 재시작에 같이 넣는다.
- **transport 배포 식별자 개명 cutover 완료**(12:24~12:33Z, transport #49 R=`b75fca1c`, 중단 약 1분).
  - Manager #432(`e2d45d65`)로 target이 `transport`가 됐다.
  - transport 백업은 Manager #430 role(16:50·17:15 UTC)로 옮겼다. 첫 dump 둘을 검증했다.
  - 72시간 관찰 뒤 정리한다(그때까지 n150 prune 금지).
- Manager #431: 백업 API 테스트의 `cancelled` flake를 고쳤다(TestClient가 요청마다 loop를 닫는 문제, 테스트만).

## 2026-09-28 — M05 격리 e2e 통과(p9), PinVi app-dagster 수정, 안 쓰는 전용 PostgreSQL 퇴역

**다음 한 작업: transport 배포 식별자 개명 cutover(창 KST 21:30~23:00) → Manager transport 백업 역할 release →
Manager 개명 release → Map DB를 공용 11000으로 이전(계획·적대 검토 중).** 모두 소유자 지시("남은 것 모두 완주")다.

- **M05 p9 PASSED**: pinset `8c9f9ad1`(Map `a18d9274` + PinVi `c5be9eb4`), Manager `88599eb9`.
  - 리허설 p9r `rehearsed` 뒤 실제 실행. `status: passed`, `phase: completed`, cleanup 실패 없음, `stderr.log` 0바이트.
  - 약 11분(06:10Z 종료). 격리 컨테이너는 모두 정리됐다.
- **막던 것과 고친 것**:
  - PinVi #570(`c5be9eb4`): #558 뒤 PinVi app compose의 `app-dagster`에 `PINVI_DAGSTER_PG_URL`과
    `pinvi_dagster` DB가 없어 항상 unhealthy였다. bootstrap 스크립트와 one-shot `app-dagster-db-init`을 넣었다.
    p9에서 db-init exit 0, dagster는 약 1분 만에 healthy.
  - PinVi #569(`5459b023`): `deploy-node.sh`의 fresh-stack 증명을 compose에서 유도한 서비스로 고쳤다.
  - Manager #428(`e25f105a`): M05 포트를 고정 기준(`28629`)부터 찾아 두 실행이 같은 빌드 입력을 준다(캐시 적중).
  - Dagster healthcheck 폭주: Manager #426 + Map #1284 뒤 운영 Dagster 컨테이너 전부가 exec 형식 probe와
    `init`으로 healthy다. 좀비 565 → 16. transport 스택만 개명 cutover 때 함께 반영한다.
- **chain17 t63b GREEN**(같은 pair): ACL 40/40, D1 11 passed, D2 passed.
  - t63a는 D1 `admin-scenario-catalog.live.spec.ts:76`이 `GET /v1/ops/datasets`를 15초 안에 못 봐 실패했다.
    같은 Map이 t62b·t63b에서 통과해 부하 flake로 본다.
- **안 쓰는 전용 PostgreSQL 퇴역**: Manager #429(`88599eb9`)가 geo·concierge·pinvi 전용 인스턴스와 airport-db를
  compose·target·백업 목록에서 지웠다. n150에서는 접속 0이던 `pinvi-postgres`(12800)만 내렸다(데이터 디렉터리 보존).
  - 백업 gc는 다른 인스턴스의 dump를 지우지 않는다(`INSTANCE_MISMATCH`).
  - n150 Manager 백업 cron(비-git 사본)이 2026-09-20 무렵부터 매일 실패하고 있었다(`compose_binds 절이 없다`).
    cron 사본을 동기화하고 수동 실행으로 확인했다.
  - `CLAUDE.md`·`docs/integration-map.md`의 DB 포트 설명을 실측(공용 11000 + map 12700)으로 고쳤다.
- **공용 PostgreSQL 비정상 재시작(원인 미상)**: 2026-09-28 03:28:57Z에 `kor-travel-shared-postgres`의 백엔드 하나가
  exit code 2로 끝나 postmaster가 전체를 재초기화했다. 복구에 약 2분 걸렸다(디스크 대기 속 pre-fsync 82초).
  OOM은 아니다. transport `/health`가 그 사이 500이었다. Map을 공용으로 옮기면 이런 사건의 영향 범위에 Map도 든다.
- **이어서**:
  - transport: PR #44가 머지돼 개명 브랜치 `chore/rename-deploy-identity-transport`를 #46 위로 rebase했다
    (`d2b7832`, 문서 밖 diff 동일). 창에서 transport 저장소 runbook "운영 식별자 개명 cutover"를 따른다.
  - Manager `feat/transport-backup-roles`: 적대 검토 MED 1건(호스트 단계 순서)을 고치는 중이다.
  - Map DB 이전: 읽기 전용 조사·계획·적대 검토 워크플로가 돌고 있다. 검증 잔여 DB 4개는 옮기지 않는다.

## 2026-09-27 — rustfs-init의 minio/mc 대체, 새 pair 사이클 t62b GREEN, M05는 n150 과부하로 BLOCKED

**다음 한 작업: n150 Dagster healthcheck 폭주를 먼저 잡고 M05를 다시 돌린다(소유자 결정 필요).**
M05 p2~p4는 본문 진입 전 인프라 phase에서 멈췄다(scoped 차단 — 실행권은 소비되지 않았고 같은 identity로 재실행된다).

- **minio/mc 소멸**:
  - Docker Hub의 `minio/mc`·`minio/minio` 저장소가 사라졌다(Hub API 404). digest 핀도 받을 수 없다.
  - M05 port(#424) 뒤 첫 실제 실행 p1이 claim 뒤 Map `rustfs-init` pull 거부로 BLOCKED됐다.
  - Map #1282(`a18d9274`), PinVi #568(`fd07903f`), Manager #425(`cc89ad9f`)로 세 저장소의 `rustfs-init`을 고쳤다.
    - 자기 rustfs 서비스와 같은 이미지의 curl(`--aws-sigv4`)로 버킷을 만든다.
    - 000과 5xx만 재시도한다. RustFS는 health 200 뒤에도 잠시 `503 storage_quorum`을 준다.
    - 요청마다 connect 5초·전체 30초 상한을 둔다.
  - 격리 실행 안에서 Map과 PinVi init 모두 `Exited (0)`을 확인했다. prod Manager `rustfs-init`도 6개 버킷 exit 0이었다.
- **새 pair**: Map `a18d9274` + PinVi `fd07903f`, pinset `ce444e8e`.
  - 회전 preflight OK.
  - chain17 **t62b GREEN**: rebuild `deployed`(Map head 400, PinVi `20260917_0102`), ACL 40/40, D1 11 passed, D2 passed.
  - t62a는 pinvi-web 빌드가 오래 조용하길래 buildx bake를 끊어 실패시켰다. 나중에 보니 레이어 export(gzip) 중이었을 가능성이 크다.
- **M05 p2~p4 (BLOCKED, 모두 `runtime_command_failed`)**:
  - p2: PinVi web 이미지 export가 약 40분 걸려 `commit failed: context deadline exceeded`.
  - p3·p4: PinVi `app-dagster`가 이미지 HEALTHCHECK(시작 60s·10s×3)를 넘겨 unhealthy.
  - 공통 원인은 n150 과부하다(load 최고 137). 운영 Dagster 스택들의 healthcheck(`dagster-daemon liveness-check`,
    `dagster api grpc-health-check`)가 매번 dagster를 import하는 Python을 띄운다. 부하가 오르면 10초를 넘겨 겹치며
    스스로 불어난다(동시 47개).
  - 좀비는 565개였다. PID 1이 자식을 거두지 않는 Dagster 컨테이너들에 있다: geo code-server 261, geo daemon 85,
    weather 78, PinVi 25, Map 20.
- **소유자에게 물을 것**:
  1. Dagster healthcheck를 가볍게 바꾸고(HTTP/grpc 대신 프로세스·포트 확인, 긴 timeout) `init: true`로 좀비를 거둔다.
     운영 스택 전부(Map·PinVi·geo·weather·airport)가 대상이고, Manager compose 재설치와 rebuild가 따른다.
  2. 또는 n150이 한가할 때 M05만 다시 돌린다(재발 가능성 높음).
- **별건**:
  - PinVi `deploy-node.sh`의 `fresh_stack_dependency_image_proof`가 main에서 이미 깨져 있다.
    `api_image_provenance.py compose-image-reference`가 app-api/web/dagster만 받아 exit 2가 난다.
  - prod `.env`의 관리 UI 비밀번호 해시 세 개가 따옴표 없이 `$`를 담고 있다. Manager 경로에서 컨테이너 값은 온전하다(해시 비교).
    다만 호스트에서 `docker compose --env-file .env`를 직접 부르면 잘린다.
  - Map·PinVi dagster-daemon이 healthcheck 타임아웃으로 `unhealthy` 표시다. 기능은 동작한다.

## 2026-09-27 — Manager ADR-51 결정 5(C6c 보호 참조 파생 규칙) 완료

**다음 한 작업: M05 격리 하네스의 Map ADR-100/101 대응.** 핀된 Map은 fresh-init 서비스를 `db-application-schema-fresh`로
부르고, `docker-compose.local-dev.yml`을 지웠고, role을 단일 LOGIN(`ktm_feature_service`)으로 바꿨다. 포팅 전까지
M05는 claim 전에 `runtime_setup_map_config`로 멈추며 실행권은 쓰지 않는다.

- **Manager**:
  - P-1 #422(`eb477467`): 설치기가 git에서 쓴 `.ktdm-release-compose.yml`을 원본으로, 자리별 보호 참조 부분집합 규칙을
    세웠다. 옛 표 검사와 병행이다.
  - P-2/P-3 #423(`784875e2`): 리터럴 표를 지웠다 — 이름 스캔, 허용 경로, sole-consumer, secret 이름 스캔, resolved의
    `.env` 재대조가 사라졌다. 내용 스캔은 값만 본다. resolved 문서에는 값 백스톱을 둔다. 변수 이름은 compose처럼
    ASCII로 읽는다.
- **n150 인수**:
  - 매 단계 `pin verify` 0, M05 preflight 0, 수렴 `converged`, 컨테이너 42개 재생성 0이다.
  - 설치된 compose는 통과한다. 누출 후보 둘은 거부된다.
  - 병합 전에 운영 데이터로 미리 돌려 보다가 bind 내용 스캔의 거짓 양성(배포 전체 차단)을 잡았다.

## 2026-09-27 — Manager ADR-51 잃는 보장 G(실패 출력 스크럽) 완료

**다음 한 작업: Manager ADR-51 compose 파생 규칙(결정 5).** 그 뒤 **M05 격리 하네스의 Map ADR-100/101 대응**. 포팅
전까지 M05는 claim 전에 `runtime_setup_map_config`로 멈춘다. 핀된 Map의 fresh-init 서비스가 `db-application-schema-fresh`인데
driver는 `-300`을 찾기 때문이다. 실행권은 쓰지 않는다.

- **Manager**:
  - G-1 #419(`95c79254`): 스크러버 하나를 CLI·API 출력 경계에 둔다.
  - G-2 #420(`8ff53b59`): 재구축 봉인을 해체하고 명령 원문 tail을 싣는다. `--json`은 `{status, stage?}`이고, claim 해제
    경로는 없앴다.
  - G-3 #421(`03729712`): M05는 항상 캡처하고, 가린 `stderr.log` 한 채널로 낸다. 생성 비밀은 생성 시 등록하고, 닫힌
    어휘는 삭제했다.
  - n150 설치.
- **n150 인수**:
  - 매 단계 `pin verify` 0, M05 preflight 0, 같은 pair 수렴 `converged`, 컨테이너 42개 재생성 0이다.
  - scrub probe 셋 모두 누출 0(비밀 71개 검사)이다.
- **Map**: `scripts/n150/chain17.sh`가 회전 preflight 사유, 회전 실패 출력, 재구축 실패의 stage와 `stderr.log` 끝을 보인다.
  운영자는 `/root/chain17.sh`로 다시 복사한다.

## 2026-09-27 — Manager ADR-51 잃는 보장 E(소스 봉인 제거) 완료

**다음 한 작업: Manager ADR-51 잃는 보장 G(실패 출력 스크럽)** — 닫힌 어휘를 원문 스크럽으로(#399가 1단계).
그 뒤 compose 파생 규칙(결정 5), 그리고 **M05 격리 하네스의 Map ADR-100/101 대응**(아래).

- **Manager**: E-1 #416(`ab20659b`, Map 계약 reader가 git 대신 source 트리 파일을 읽는다) → E-2 #417(`4fd1581e`,
  M05 본문이 실행별 checkout `runtime/{map-src,pinvi-src}`에서 돈다 — PinVi attestation 때문에 archive가 아니다)
  → E-3 #418(`13173cd9`, 재구축 source = `<state_root>/pinned-runtime-sources/<role>-<revision>/{tree,source.json}`,
  없을 때만 depth-1 fetch + `git archive`, 있으면 git 0회, 손상되면 다시 만든다). n150 설치.
- **n150 인수**: 매 단계 `pin verify` 0·M05 preflight 0·같은 pair 수렴 `converged`·컨테이너 42개 재생성 0. E-3 첫 수렴에서
  archive source 둘이 생겼고(tree id = 핀 commit, g/o 쓰기 0, 디렉터리 0755, `.git` 없음) build context 경로가 바뀌었는데도
  재생성 0, 두 번째 수렴은 `source.json`을 건드리지 않았다(git 0회). 옛 `<state_root>/pinned-runtime-sources-v5/`(827M)는
  되돌림 하한용으로 남겼다(삭제 선택, Manager `prod-deployment.md` §8.1).
- **발견 — M05 전체 실행이 Map #1259 이후 불가능하다.** E-2 검증용 실제 M05(`/root/m05-once-e2run`)가
  `runtime_loopback_publish_config_invalid`로 claim 전 거부됐다(`preflight_rejected`, 실행권 소비 없음). 원인은 E-2가 아니라
  Map #1259(2026-09-23, ADR-100 단일 LOGIN role·ADR-101 baseline 400)가 `docker-compose.local-dev.yml`을 지웠는데 M05 driver가
  아직 그 파일과 옛 role(`ktm_feature_migrator`·`ktm_feature_api_runtime`)을 쓰기 때문이다. E-2의 checkout 자체(GitHub depth-1
  fetch)는 n150에서 동작했다. 대응은 별도 작업이다.

## 2026-09-27 — Manager ADR-51 잃는 보장 D(설치기 단순화) 완료

**다음 한 작업: Manager ADR-51 잃는 보장 E(소스 봉인 제거).** pinned runtime 소스의 워크트리 불변화·
symlink·submodule 금지·로컬 origin 확인을 실행마다 `fetch` + `git archive <sha>`로 바꾼다. 그 뒤 G(실패
출력 스크럽 — #399가 1단계), compose 파생 규칙(결정 5) 순서.

- **Manager**: I-1 #414(`f0149db2`, 설치 root symlink의 소비자 이전) → n150 레이아웃 1회 전환 →
  I-2 #415(`58d25ab0`, 설치기 1,887줄 → 196줄) 머지·n150 설치.
- **n150 설치 방식이 바뀌었다**: `/opt/kor-travel-docker-manager` → 상대 symlink `ktdm-release-<sha>`,
  release는 `/opt/ktdm-release-<sha>/`(직전 하나 보존). 설치는 **root 소유 clone**
  `/var/lib/kor-travel-docker-manager/src`에서 `bash ~/install-mgr.sh <sha>`(헬퍼가 clone·checkout·
  installer 실행) → `ktdctl pin rebind-execution` → `pin verify` 0. 설치기가 항상 backend를 재기동한다.
  롤백은 옛 sha 재설치(손으로 symlink 넘기기 금지). 옛 설치기는 symlink 레이아웃을 해 없이 거부한다.
- **n150 인수**: 설치·같은 sha 재설치(5초, 빌드 없음)·I-1 롤백 왕복 모두 `pin verify` 0·M05 preflight 0,
  같은 pair 수렴 `converged`에 Manager 관리 컨테이너 42개 재생성 0, bind에 release 경로 0. release 크기
  83MB(옛 설치본은 헬퍼의 프론트 빌드로 882MB).
- **n150 디스크**: Tier 3(다른 세션 작업 디렉터리) 정리로 여유 102G → 117G. 소유자 판단 대기 항목 해소.

## 2026-09-27 — 봉인·신뢰 릴리스 단순화(Manager ADR-51 / Map ADR-102) 완료

**다음 한 작업: 없음(이 프로그램은 끝났다).** 남은 것은 ADR-51이 "그 뒤 각자"로 둔 별개 항목 —
설치기 단순화(잃는 보장 D), 소스 봉인(E), 실패 출력 스크럽(G), compose 파생 규칙 — 과 선택 정리
(B3 PR-4 launcher claim 해제, D-4 안 읽히는 evidence, Map 자신의 compose에 남은 permit volume).

- **Manager**: B2 #404 → B3 #405~#407 → C #408~#410 → **D #411~#413** 머지·n150 설치(`a3a695fa`).
  D-1 M05·`pin verify`가 `deploy-status.json`을 본다(공개 세대 API 삭제), D-2 v6 쓰기 중단·코드 삭제,
  D-3 Dagster storage permit mount 제거. 문서: PinVi #567, Map #1276.
- **최종 인수(t61a, Map `b4fbde1e` / pinset `fc39eb5c`)**: 새 pair 전체 경로 배포 — 같은 DB(oid 그대로),
  v6 파일 안 씀, permit 없음 → ACL 40/40 → **D1 11 passed → D2 passed(v4)**, lane 깨끗.
- **기록된 손실**: 공개 세대 뷰, 실패한 배포 뒤 한 번 커밋될 때까지 M05 거부, pre-M1 Map pinset으로의
  되돌림 불가(roll-forward), Manager 되돌림 하한 D-1.
- **소유자 판단 대기(유지):** n150 다른 세션 작업 디렉터리 약 18.5GB.

## 2026-09-27 — Manager ADR-51 C(락 통합) 완료: 파일 락은 G 하나

**다음 한 작업: Manager ADR-51 D**(permit mount 제거, v6 manifest 쓰기 중단, M05 driver·`pin verify`·공개 세대
API를 `deploy-status.json`으로). 선택으로 B3 PR-4(launcher claim 해제·실패 분류 이름 정리).

- **C-1 #408** 한 획득 경로(CLI pin 변이의 락 없는 두 갈래 삭제, 실제 자식 프로세스 경합 검사) →
  **C-2 #409** rehearsal의 UI/API·compose·legacy retire·관리자 비밀번호 `.env` 쓰기가 G로(잡혀 있으면 즉시
  409 `MANAGER_MUTATION_ACTIVE`) → **C-3 #410** pinned lease P·env 파생 락·override 삭제.
- n150 설치(`4d324926`) 뒤: 같은 pair 수렴 재구축 중 `lslocks`에 **G 하나만**, G를 쥔 동안 rehearsal 경로 즉시 거절,
  `pin verify` 0. 남은 P 파일은 보유자 없음을 확인하고 지웠다.
- **대가(설계대로):** 재구축·M05·설치 동안 UI 조작과 관리자 비밀번호 변경은 409다. UI가 G를 몇 ms 쥔 순간에
  chain17 launcher가 시작되면 빠르게 실패하므로 다시 돌린다. **G를 손으로 잡을 때는 `flock(1)` 금지**(없는 G를
  0644로 만들어 모든 변경이 멈춘다) — `/opt` venv의 `manager_mutation_lock()`으로만.

## 2026-09-26 (자정 무렵) — Manager B3: v8 journal이 코드에서 사라졌다

**다음 한 작업: Manager ADR-51 C(락 통합)** → D(permit mount 제거, v6 쓰기 중단·M05 driver를
`deploy-status.json`으로). B3의 선택 PR-4(launcher claim 해제 정리·실패 분류 이름)는 C에 합쳐도 된다.

- **B3 PR-1 #405** carry-over·죽은 증거 생산자 삭제(−2.3k줄), **PR-2 #406** v8 journal 모델 삭제·공개 세대
  리더는 v6 manifest만(−4.3k줄, `drift` 없음), **PR-3 #407** journal 시절 관리자 비밀번호 guard·preflight
  상태 퇴역(backend+frontend). 셋 다 적대 리뷰 반영, n150 전체 pytest 초록.
- **n150 설치(`95a82c67`)** 뒤 확인: `pin verify` 0(binding match), 공개 세대 리더 `ok/match/committed`
  (옛 공개 v8 사본은 안 읽음), M05 rotation preflight 통과, 사라진 route 404, 같은 pair `converged` 45초.
- **알려진 후속(B3 밖):** preflight §1이 늘 `EXECUTION_VERIFICATION_REQUIRED`/`LEGACY_SOURCE_TERMINAL`을 더해
  `ok`가 나오지 않는다(잃는 보장 B의 후속). `deployment_readiness`가 더는 주입되지 않는 PinVi
  `PINVI_ROLE_CATALOG_RESET_*`를 요구해 거짓 blocker를 낼 수 있다.

## 2026-09-26 (늦은 밤) — 단순화된 체인으로 첫 새 pair가 D1·D2까지 섰다

**다음 한 작업: Manager B3(v8 journal·phase·evidence 클래스와 journal 전용 코드 삭제, 남은 리더를
`deploy-status.json`으로)** → C(락 통합) → D(permit mount 제거, v6 쓰기 중단). 순서는 Manager ADR-51 §순서.

- **M1 #1270**(storage one-shot 멱등) · **M2 #1272**(C7/D2 attestation 체인 제거 + `scripts/n150/`, `adjudicate.sh`
  포함) 머지. `/root` 호스트 스크립트를 머지 커밋 `031205ff`에서 설치(옛 사본 `/root/host-scripts-pre-m2-*`).
- **t59a(Map `031205ff`, pinset `be344a89`)**: pair 계약 preflight → 회전 → 전진 배포 `deployed`(DB oid 그대로,
  경고 없음) → ADR-069 PASS → repin → ACL 40/40 → **D1 11 passed → D2 passed(v4)**, lane 깨끗.
- **n150 디스크:** 백업·덤프 약 31GB도 정리(소유자 승인) → 여유 111G(76%). geo 백업은 geo janitor로.
- **남은 판단:** 다른 세션 작업 디렉터리 약 18.5GB(지우지 않음).
- **작은 결함 하나 고침(이 PR):** chain16 step E가 공유 체크아웃 `/tmp/ktm-lint`의 fetch 실패를 검사하지 않아
  t59a에서 옛 origin/main 사본의 M01 preflight가 돌았다 → 배포한 SHA에서 꺼내고 실패하면 멈춘다.

## 2026-09-26 (밤) — Manager B2(마이그레이션 전진) 설치, 같은 pair 수렴 확인

**다음 한 작업: Map M1(#1270, storage one-shot 멱등) CI → 머지, M2(C7/D2 attestation 체인 제거 +
`scripts/n150/`) 적대 리뷰 반영 → PR → 머지 → 호스트 스크립트 설치(H1).** 그 뒤 첫 새 pair를 새 체인으로
돌려 D1/D2를 확인한다. 그다음 Manager B3(v8·journal 클래스 삭제) → C → D.

- **Manager B2 #404(`13e744b`)** 머지·n150 설치·`pin rebind-execution` 완료. 적대 리뷰 3회(1차 major 2 +
  2차에서 1차 수정이 만든 major 2 + 3차 minor 2) 반영, 변이 18/18.
- **첫 전진 배포(t58a):** carry-over 대신 기준선 없는 전체 경로(옛 계약 v8 journal 62개가 읽히지 않음) —
  리셋 없음, DB oid 그대로, ADR-069 PASS, D1 11 passed. **t58b: `converged` 45초.**
- **주의:** 새 pair는 아직 chain17로 돌리지 말 것 — B2가 v8 journal을 쓰지 않으므로 chain16의 repin
  (gen_attest)이 실패한다. M2 + H1 뒤다. 같은 pair 재실행은 launcher(`run-pinned-rebuild-once`)로 수렴한다.
- **소유자 판단 대기(유지):** n150 백업·덤프 약 31GB, 다른 세션 작업 디렉터리 약 18.5GB.

## 2026-09-26 (저녁) — ADR-069 배포 완료(t57d): D1·D2 GREEN

**다음 한 작업: ADR-102/Manager ADR-51 단계 PR을 이어 간다** — Manager B2(마이그레이션 전진 본체,
브랜치 `feat/migrate-forward-b2`) 적대 리뷰 → PR·CI·머지·설치 → 같은 pair 수렴 1회 → Map M1(storage
one-shot 멱등) → M2 + 호스트 스크립트(H1) → B3 …. 순서 근거는 아래 2026-09-26(오후) 항목과 ADR-102.

- **배포:** pair Map `6511441f` / PinVi `b227e77b`(pinset `e4909e26`), Manager `e891ec7`(#401).
  chain17 t57d: rebuild success → repin verifier PASS → M01 ACL 40/40 → D1 11 passed → D2 passed.
- **ADR-069 확인:** Map·PinVi code-server/webserver/daemon healthy, companion = owner 이미지, code location
  LOADED(Map 48 jobs / PinVi 9 jobs), gRPC 12703/12803 loopback 전용(`[::ffff:127.0.0.1]`, 비-loopback 29개 거부).
- **t57b·t57c:** 호스트 포화(BuildKit session healthcheck 실패 / 내가 journal 전 중단). 데이터 변경 없음.
- **n150 디스크:** 캐시·재생성 가능 항목만 정리해 42G → 84G(82%), IO `full` 50~60% → 약 3%.
  **소유자 판단 대기:** 백업·덤프 약 31GB, 다른 세션 작업 디렉터리 약 18.5GB.
- **열린 것:** geo code-server `-h 0.0.0.0`(아래 2026-09-26 항목) 그대로.

## 2026-09-26 (오후) — t57a는 디스크 포화에 걸렸다 → 타임아웃 수정 후 재시도, 배포 모델은 마이그레이션 전진으로

**다음 한 작업: Manager #401 설치 → 이 커밋(새 pinset)으로 chain17 → code location 로드 확인 →
D1/D2.** 그다음 ADR-102/Manager ADR-51의 단계별 PR(A → M1 → M2+H1 → B1 → B2 …).

- **t57a(#399 설치본):** 후보 static inspection `ktm-application-schema head`가 60초 타임아웃으로
  죽었다(journal 전, claim 반환). 명령은 정상이다 — n150 SATA SSD가 92% 차 IO 압력 `full`이 상시
  50~60%이고, `docker run --rm /bin/true` 하나가 112초, head가 74초 걸렸다. #399가 봉인된 stage 한
  단어 대신 비밀을 가린 원인 원문을 stderr에 남겨서 재현 없이 바로 짚었다.
- **수정(Manager #401):** static inspection 60→600초, compose `--wait-timeout` 300→900초(ADR-069 뒤 Map은
  code-server → webserver → daemon 직렬 기동).
- **배포 모델 결정(소유자):** 봉인·신뢰 릴리스 단순화의 잃는 보장 A~H 전부 승인, **DB는 배포를
  넘어 보존(마이그레이션 전진)**, 리셋은 명시적 `--restart`만, 쌍 계약 preflight는 게이트 유지,
  M05 유지, n150은 rebuildable 유지, `--restart` 전 백업 강제 안 함, 급하면 구 모델 리셋 1회 허용,
  PinVi에도 forward-only ADR. → [ADR-102](adr/102-migrate-forward-deploys-and-seal-removal.md),
  Manager ADR-51(#400), PinVi ADR-071(pinvi#566).
- **열린 것:** n150 디스크 92%·IO 포화 자체. 타임아웃은 증상 완화다.

## 2026-09-26 — ADR-069 재구축이 code-server를 한 번도 띄운 적이 없었다 → Manager 수정 후 재시도

**다음 한 작업: Manager #399 설치 → 이 커밋(새 pinset)으로
chain17 → Map Dagster GraphQL로 code location 로드 확인 → D1/D2.** 그다음 봉인·신뢰 릴리스
단순화(설계 완료, 잃는 보장 목록은 소유자 승인 대기).

### 원인 (자세히는 journal.md 2026-09-26)

- **t56g·t56h:** 비상 복구 때 `/opt` compose에 손으로 넣은 패치(webserver/daemon `-m`)를
  되돌리지 않은 채 돌렸다. 새 이미지의 봉인 entrypoint가 `-m`을 거부해 compose up에서 죽었다.
  신뢰 릴리스 사본으로 원복·diff 확인 완료. pinset `a7cc0414`는 journal이 패치본 compose sha를
  동결해 재개 불가 — 버린다(이 커밋이 새 pinset이다).
- **더 근본:** pinned rebuild가 `up --no-deps`에 고정 서비스 목록을 줬고, compose는 호출에 이름이
  없는 서비스로의 `depends_on` 간선을 지운다. 그래서 Map code-server는 **어느 재구축에서도 기동된
  적이 없고**, webserver healthcheck는 빈 `RepositoryConnection`도 통과시켜 `--wait`가 초록이었다.
  D1도 code location을 보지 않는다 — 그대로 두면 저장소 0개인 Dagster가 GREEN으로 커밋될 뻔했다.
  PinVi code-server·daemon도 관리 밖이라 DB 리셋을 건너 옛 이미지로 떠 있었다.
- **PinVi:** SQLAlchemy 2.1.0이 bare `postgresql://`의 기본 driver를 psycopg(v3)로 바꿔
  pinvi-dagster가 `ModuleNotFoundError: psycopg`로 죽었다 → pinvi#565(`<2.1`).

### 끝난 것

- Manager #399(generation companion: resolved compose에서 slot 이미지를 공유하는 비-slot 서비스를
  파생해 stop/up/readiness/image 대조에 태움, 영속 포맷 변경 없음) + 실패 원문을 `.env` 비밀을
  가려 stderr로(봉인 단순화 1단계) + PinVi code-server `-h 127.0.0.1`(인증 없는 gRPC LAN 노출 제거).
  적대 리뷰가 "companion 호출처 10곳 중 8곳은 지워도 테스트가 안 깨진다"를 검증해, commit·committed
  재개까지 도는 테스트를 더했다 — 변이 검사로 10곳 + one-shot 제외 + 프로세스 환경 리댁션 12/12가
  각각 빨개지는 것을 확인했다.

### 열린 것

- **geo code-server가 host network에서 `-h 0.0.0.0`**(인증 없는 gRPC가 LAN에 열림). geo 이미지의
  workspace.yaml이 어느 host로 붙는지 확인한 뒤 닫는다. Manager 테스트에 알려진 예외로 등록해
  두었고, 해소되면 그 예외부터 지우라고 빨개진다.

## 2026-09-25 — ADR-069 code-server: PinVi 활성화 완료, Map은 merge+재설치 끝·재구축 진행 중

**다음 한 작업: 이 커밋(새 pinset)으로 n150 chain17.sh 재시도, D1(live e2e UI)까지 확인.**
자세한 경위는 `journal.md` 2026-09-25. 요약: Map #1264 + Manager #397/#398(등록
누락 두 건) 전부 머지·배포 끝, 재구축이 (pinset, Manager revision) 단위 v6
execution terminal에 두 번 막혀 새 커밋으로 pinset을 갈아야만 재시도 가능했다.

### 끝난 것

- PinVi dagster-code-server + webserver(`-w`) + daemon 첫 기동, schedule/sensor
  0개 자동 기동 확인.
- Map도 같은 code-server 분리(Map #1264, Manager #397) — mypy 깨던 SQLAlchemy
  2.1.0 무상한 고정(#1265), C7 attestation 카운트 6→7, Manager
  `compose_service.py`의 별도 protected-scalar 레지스트리 등록 누락(#398).
- n150 Manager `6452a4c…`로 재설치 + 프론트엔드 재빌드 완료.

### 아직

- 이 커밋의 새 pinset으로 chain17.sh(rotate→rebuild→executor image→repin→
  ACL preflight→D1 live e2e→lane 정리→D2) 재시도.
- D1(live Playwright, admin UI)로 code-server 토폴로지가 실제로 code
  location을 서빙하는지, 기존 schedule/sensor/job이 그대로 보이는지 시각
  확인.

## 2026-09-24 — prod 전 사이클 GREEN. ADR-100/101 + PinVi 단일 role, 실사용으로 처음 섰다

**다음 한 작업: 소유자 판단 — D1/D2 spec 재검증을 지금 돌릴지, 아니면 여기서 접을지.**
prod 자체는 안정 상태이므로 급하지 않다(아래 "끝난 상태" 참고). 돌린다면
`docs/integration-map.md`의 D1(live Playwright)·D2(admin acceptance) 절차를
그대로 따른다 — 지금 pinset(`fa6f624e5b06…`)이 첫 실사용 기준선이라 두 레인
모두 **이 번호로는 한 번도 실행된 적이 없다.**

### 끝난 것 — Manager+PinVi 연쇄 네 자리 (자세한 근거는 journal.md 2026-09-24)

어제 남겼던 "빌드 영수증 축 빠짐"은 Manager PR #391/#392/#393으로 닫혔다. 그
뒤 재구축이 Map을 다 통과하고 PinVi 쪽에서 네 번 더 막혔다 — pinvi DB owner
drift(직접 SQL로 수정) · Map `ktm_*` role 19개 정본 이탈(직접 SQL로 수정) ·
PinVi 0101이 요구하는 catalog-lock fence 함수 부재(Manager #394) · PinVi
0101 자신이 자기 migrator 권한을 트랜잭션 안에서 거둬감(pinvi #564). 넷 다
**ADR-46(PinVi M05 다중 role 폐기)이 인프라는 고쳤는데 그 인프라가 떠받치던
자리 일부를 안 고친 것**이 근본이었다.

### 끝난 상태 (2026-09-24 실측)

| | |
|---|---|
| pinset | `fa6f624e5b068713546517d19660e60701913e483565ea21ee11ef73d19a00cc` |
| map revision | `f5703bc676b175fb1b0f9ccbcdd202df02ad71d6` (schema head `400`) |
| pinvi revision | `b60cc8cd601d6236655902337e150bfbd0829719` (schema head `20260917_0102`) |
| Manager | `7fc1a8c94bea5eb5155246a71ddaa731d840a841`(#394), trusted install + execution rebind 완료 |
| 런타임 | 7개 서비스(map-api/ui/dagster/dagster-daemon, pinvi-api/web/dagster) 전부 healthy |
| `.env` | `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=400`(재구축 후 변경, 순서 지킴) |

## 2026-09-23 — ADR-100/101 머지됨, prod는 Manager의 **남은 ADR-101 구간**에 막혀 있다

**다음 한 작업: Manager에서 paired candidate build receipt 장치를 걷어낸다.**
그것 없이는 prod 재구축이 끝나지 않는다.

### 무엇이 막혔나

ADR-101은 Map에서 `scripts/build-application-300-{candidate,paired-candidate}.sh`와
`build-baseline.sh`를 지웠다(ADR 문서 17행이 그 셋을 명시한다). 그런데 Manager의
소비자는 그대로 남아 있다 — 앞선 ADR-101 Manager 작업(#389)이 영수증·fence·phase
기계를 접었지만 **빌드 영수증 축은 범위 밖이었다.**

같은 뿌리에서 두 자리가 어긋나 있다:

1. `compose_service.py:2830` `_run_map_application_300_paired_builder`가 지워진
   `scripts/build-application-300-paired-candidate.sh`를 요구한다.
   → 재구축이 `prejournal_failure` / stage `application_builder`로 죽는다 (실측).
2. `compose_service.py:6098` `DagsterStorageCandidate`가 아직
   `paired_candidate_build_receipt_sha256`을 싣는다. Map의
   `docker/dagster-storage-migrate.py`는 이제 `_CANDIDATE_FIELDS =
   {dagster_image_id, dagster_config_sha256}` **exact** 검사다.
   → 1번을 고쳐도 Dagster storage 단계에서 `dagster_storage_permit_candidate_invalid`
   로 막힌다(코드 대조로 확인, 아직 실측 전).

면적: `map_application_300_candidate.py` 773줄 + 호출부 + `Application300Contract` +
테스트 참조 약 75건.

### prod 현재 상태 (2026-09-23 09:5x 실측)

**더 나빠지지 않았다.** 두 실패 모두 저널 **전**이라 후보가 해제됐고, 새 pinset에는
journal이 없다 — 고착이 아니라 재시도 가능 상태다.

| | |
|---|---|
| pinset | `e8441d96983d…` → map `f5703bc6…`, pinvi `351b4ace…` |
| journal | 없음 (재시도 안전) |
| 컨테이너 | `kor-travel-map-postgres`, `pinvi-postgres`만 Up. 나머지는 여전히 down |
| rebuild t53a | `prejournal_failure` / `prebuild_snapshot` — `.env` 자격증명 부재 (**해결됨**) |
| rebuild t53b | `prejournal_failure` / `application_builder` — 위 1번 (**미해결**) |

### 이번 사이클에서 끝낸 것

- **Manager 설치본을 `e4d4fa55`로 갱신했다** (사용자 1회 허가로 trusted installer 실행).
  이전 설치본은 `2dc633dd`로 머지 여섯 개 뒤처져 있었다.
- **`.env`에 ADR-100 단일 LOGIN 자격증명 쌍을 넣었다** —
  `KOR_TRAVEL_MAP_SERVICE_PASSWORD`, `KOR_TRAVEL_MAP_PG_DSN`. Manager는 M05 폐기와
  함께 이 값을 더는 쓰지 않으므로 운영자 책임이다. 선행 조건을 Manager
  `docs/prod-deployment.md`에 적었다(kor-travel-docker-manager #390).
  백업: `.env.bak-pre-adr100-service-credential-20260923T095230Z`.
- **핀을 회전했다** — 직전 pinset의 journal 영구 고착 탈출구가 새 커밋이었고, 두
  머지가 그것을 만들었다. 회전은 **다시 하면 안 된다**(`rotate-pinned-pair`가 같은
  쌍에 대해 no-op을 거부한다). 재시도는 rebuild 단계부터다.

### 재시도 방법 (Manager 고친 뒤)

```bash
# 회전은 이미 끝났다 — chain17을 통째로 다시 돌리면 B단계에서 죽는다.
sudo systemd-run --no-block --unit=ktdm-rebuild-<새태그> --collect \
  --property=Type=oneshot --property=TimeoutStartSec=7200 \
  /opt/kor-travel-docker-manager/scripts/run-pinned-rebuild-once \
  <설치된 Manager 40-hex> /root/rebuild-ktdm-rebuild-<새태그>
# 성공하면 후반부
sudo /root/chain16.sh <MAP 40-hex> <PINVI 40-hex> <execbuild unit> <d2 unit> <태그>
```

그다음에 `.env`의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를 `400`으로 바꾼다
(지금 `312_route_geometry_sidecar`). **재구축 뒤에** 바꾼다 — 먼저 바꾸면 API가
기동을 거부한다.

## 2026-09-20 (2) — PR #1257 머지 완료, prod 배포가 pinned-rebuild journal에 고착 (outage 진행 중)

**다음 한 작업: PinVi에 실제 커밋 하나를 올려 새 pinset을 만들고 `chain17`을 다시
돌린다.** PR #1257(ADR-099 2단계)은 머지됐고(`b3c217f0`), 회전 → rebuild까지는
진행했으나 **prod의 Map/PinVi 앱 컨테이너가 전부 내려간 채로 멈춰 있다**
(postgres 둘은 healthy, Map DB는 이미 `312_route_geometry_sidecar`로 정확히 재생성됨
— 데이터 손실 없음, 순수 가용성 중단).

**막힌 지점 (n150, Manager `d6c503a0` 기준 실측):**

1. pinset `3705983b`(map `b3c217f0` + pinvi `ed5eb020`)의 rebuild가 compose-up
   단계에서 반복 실패. 원인: **다른 세션이 geo 공용-postgres 온보딩 작업으로
   `.env`에 `KOR_TRAVEL_GEO_SHARED_APP_PASSWORD`를 추가**해 파일 전체 해시가 바뀜
   (`.env.bak-t308-20260920042101`로 확인, 완전히 무해한 동시 작업).
2. 그런데 `_assert_pinvi_role_credential_rebind_admission`(Manager
   `compose_service.py`)이 `journal.phase == "map_runtime_ready"`일 때만 재결박을
   허용한다 — 이 journal은 이미 그보다 진행된 `cancel_probe_finalized`라 **원인이
   무해해도 이 pinset은 설계상 영구 재개 불가**다(`rotate-pinned-pair`도 같은
   map+pinvi 쌍이면 no-op을 거부해 새 pinset을 못 만든다).
3. 알려진 v6 candidate 이미지로 직접 서비스만 복구를 시도했으나 두 관문에 추가로
   걸렸다 — `.env`의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=300`(수 주 전 값,
   **고쳤다** → `312_route_geometry_sidecar`, `.env.bak-pre-migration-head-fix-*`)와
   `application final permit`(`/run/kor-travel-map-application-final-permit/`,
   호스트 마운트가 8월 25일자 무관한 rehearsal 트리를 가리키며 비어 있음 — 이건
   **파이프라인이 끝까지 성공해야만 발급**되는 증빙이라 손으로 만들 수 없다).

**해제 조건:** PinVi에 사소한 실제 커밋(예: 문서 동기화) → `rotate-pinned-pair`로
진짜 새 pinset 생성(고착된 journal 우회) → `chain17.sh` 재실행 → compose up이
끝까지 성공 → final permit 발급 → 서비스 기동 확인.

소유자 결정(2026-09-20): 지금은 보류하고 weather → concierge → geo → pinvi → map
순서의 Dagster 실행구조 개선·DB 인스턴스 통합을 먼저 진행한다. 이 outage 정리는
그 작업과 별도로 재개한다.

## 2026-09-20 — ADR-099 2단계: route geometry가 전용 PostGIS relation으로 갔다

**다음 한 작업(완료, 위 항목 참조):** ~~네 세션 게이트를 초록으로 만들고 머지 →
핀 회전 · DB 재구축 · 전 provider 재적재.~~ 소유자 지시: *"마이그레이션 하지말고
db재설계후 다시데이터 로드해. 지금데이터는 무의미함."*

`312_route_geometry_sidecar`가 `feature.feature_routes.geom`을
`feature.feature_route_geometries`로 옮긴다. **데이터를 이어 나르지 않는다** —
`feature_routes`가 비어 있기를 요구하고, 행이 남아 있으면 마이그레이션이 멎는다.
설계 근거는 ADR-099 §4·§5.

### 이 단계에서 반복해서 터진 결함은 하나의 모양이었다

**"선언을 바꿨는데 그 선언을 얼려 둔 자리를 같이 못 봤다."** geometry 컬럼 하나가
이사했을 뿐인데 그것을 가리키던 자리가 **열여섯 곳**에서 옛 자리에 남아 있었다:
뷰 의존(DROP 실패), plpgsql 프로시저 셋(첫 적재에서 42703), `public_ready` 트리거
누락(route가 오류 없이 공개 bbox에서 0건), NOINHERIT 소유자 검사, 권한 조정기의
fail-close fence, ORM 메타데이터, GiST 인덱스 이름에 결박된 검사 여덟,
`ktm_feature_state_procedure_owner`의 geometry 권한, `ktm_curation_command_owner`의
SELECT, `current_theme_candidate_snapshot`의 `to_jsonb(route)`, override field-path
레지스트리, 무결성 관측 두 축, 역할 창 lint의 309 결박, 롤 유지 lint의 AST 한계,
그리고 head 오라클 자체.

그래서 이 브랜치는 **이름을 옮기는 대신 모델에서 유도하게** 바꿨다 —
`GEOMETRY_RELATIONS`/`EXTERNAL_GEOMETRY_KINDS`가 단일 정본이고, 검사·관측·권한이
거기서 나온다. 다음 이사(area)는 dict 값 하나를 바꾸는 일이어야 한다.

### 적대 리뷰 (opus5 · xhigh 2인 + 반증 패널)

10건 중 8건 생존, 1건 반증, 1건은 API 오류로 미완. 생존분은 전부 닫았다.
반증된 것은 "312가 봉인 member 정의를 바꾸는데 `input_set_formula` 세대를 안
올렸다" — 312가 비어 있기를 **요구**하므로 세대 2로 발급된 구 route arm receipt가
312 DB에 남을 수 없다. 판단 근거는 ADR-099 결과 절에 적었다.

내 자신의 돌연변이 실험도 검사 결함 하나를 더 찾았다 — 롤 유지 lint가 **주석 붙은
`SET ROLE`을 못 봤다**. 사이드카의 여는 창은 거의 언제나 설명 블록 뒤에 오므로,
검사는 닫는 쪽만 보고 있었다.

---

## 2026-09-19 (4) — 등산로가 한 번도 성공한 적 없는 이유를 찾았다. 봉인에 크기 천장이 있다

**다음 한 작업: ADR-099 2단계 — route geometry를 PostGIS 보조 relation으로 분리.**
1단계(`311_seal_member_digest`, fold를 행별 digest로)는 이 PR에서 닫았다.

`feature_route_krforest_mountain_trails_job`이 **4시간18분** 지오코딩을 마치고
적재/봉인에서 죽었다.

```
asyncpg.ProgramLimitExceededError:
  total size of jsonb array elements exceeds the maximum of 268435455 bytes
```

`feature.current_provider_curation_input_set`이 causal seal을 만들 때 **데이터셋
전 행의 feature detail을 하나의 `jsonb_agg` 배열로 모아** 그 text를 sha256한다.
route는 `to_jsonb(route)`라서 geometry가 통째로 들어간다.

**적재는 같은 트랜잭션 안에서 봉인보다 먼저** 일어난다. 그래서 57,060행을 넣고 →
봉인에서 죽고 → **통째로 롤백**한다. `provider_sync.source_entities`의
`mountain_trail_segment`가 0행인 이유가 이것이다 — 이 job은 **한 번도 성공한 적이
없다.** 재시도는 같은 자리에서 죽으며 매번 4시간을 다시 쓴다. 2차 시도는 종료시켰다.

**실측 — geometry가 payload의 98.5%다** (기존 둘레길 26행 기준).

| | route당 | 57,060건 환산 |
|---|---:|---:|
| 현재(geom 포함) | 43 kB | **2.45 GB** ❌ |
| geom 제외 | 633 B | 36 MB ✅ |

현재 천장은 대략 **43 kB 기준 6,200 route**다. 둘레길 26건은 안전하다.

**그런데 geometry만의 문제가 아니다.** `feature.feature_places`는 평균 **323 B**인데
(prod 34,422행 실측) MOIS 980,970행이면 **302 MB**로 geometry 없이도 한계를 넘는다.
즉 geometry를 어디로 옮기든 **fold 자체가 O(행수 × 행당 payload)인 것**이 근본이다.

**소유자 지시**: *"등산로는 postgis 형태로 별도의 보조테이블에 저장"*,
*"등산로와 같은 건 route 에 저장"*. 즉 route 정체성은 유지하고 geometry 저장소만
분리한다. 설계는 ADR-099로 진행 중이다(다음 ADR 후보 번호 확인함).

**설계에 확정된 제약(실측).**

- 보조 테이블 PK는 `feature_id` **1:1**이다 — `forest_trails_to_bundles`가 item
  하나당 bundle 하나를 만들어 57,060 세그먼트 = 57,060 route feature다. 1:N은
  `ktm_feature_runtime`에 **의도적으로 없는** subtype DELETE 권한을 새로 요구한다.
- **area도 같은 구조**다(`MULTIPOLYGON NOT NULL` + 동일한 부분 GiST). 지금 0행이고
  생산자(KNPS 국립공원 경계)는 비활성 목록에도 없이 그냥 실행된 적이 없다 —
  적재되는 순간 같은 사고가 난다.
- 봉인은 기록이 아니라 **게이트**다. 불일치 시 child는 23514, root는 `stale_input`.
  그리고 한 사이클에 **최소 세 번** 호출되며 그중 `finalize_provider_curation_root`는
  **적재와 다른 트랜잭션**이다 — 적재 쪽만 고치면 finalize에서 같은 자리에서 죽는다.
- ADR-086/`0087_route_area_subtypes`가 geometry를 subtype에 넣은 이유는 성능이 아니라
  **불변식**이다: "geometry가 필수인 kind와 없어야 하는 kind가 술어가 아니라 테이블
  구조로 갈린다". 보조 테이블은 그 불변식을 다시 연다 — 대체 fence가 설계의 중심이다.
  (admin 주석의 "0086"은 ADR 번호이고 revision은 `0087`이다.)
- 보조 테이블은 `feature_routes`가 아니라 **`feature.features`에 직접 FK**를 걸어야
  한다. purge 증거 포획이 `confrelid='feature.features'` 한 단계만 훑으므로, 2단
  CASCADE로 지워지면 복구점에 안 남는다.
- provider 경로의 geometry 변경은 geometry를 빼도 계속 감지된다 —
  `krforest.py`가 `geometry_wkt`를 `raw_payload_hash`에 넣고 그 해시가 봉인 배열에
  이미 있다. 다만 **직접 `SET geom` 경로가 셋 실재**한다
  (`_309_{apply_provider_feature_field_patch,author_feature_field_overrides,revoke_feature_field_overrides}.sql`).
- API/OpenAPI는 걸리지 않는다 — route geometry는 GeoJSON(`include_geometry`)으로만
  나가고 저장 표현은 노출되지 않는다.
- **배포 창이 지금 깨끗하다**: snapshot receipt 5건, 진행 중 curation root **0건**.
  봉인 해시 정의를 바꿔도 `stale_input`으로 빠질 in-flight root가 없다.

## 2026-09-19 (3) — 산사태 0행의 이유를 확정했다. 다음은 대량 역지오코딩이다

**다음 한 작업: 대량 역지오코딩이 일시적 실패 한 번에 전체를 버리는 것을 고칠 것.**

`src/kortravelmap/providers/mcst.py`의 `file_rows_to_bundles`는 **행마다 순차로**
`await _resolve_address(...)`를 부르고, 그 예외를 잡는 자리가 provider·dagster
어디에도 없다(저장소 전체에 `except GeoRequestError` 0건). prod 실측:

```
feature_place_mcst_culture_job        4회 시도 / 2h54m / FAILURE
  RetryRequestedFromPolicy: Exceeded max_retries of 3
    <- GeoRequestError: kor-travel-geo transport 실패: ReadTimeout
  마지막 시도는 upstream_requests_min=13 — 13개 dataset을 다 받아 놓고 죽었다
feature_route_krforest_mountain_trails_job
  04:04:24 STEP_START 이후 3시간 dagster 이벤트 0건
호스트: 4코어, load average 17
```

**실측한 분모.** geo reverse를 job과 같은 컨테이너·같은 설정으로 쟀다.

| 방식 | 20건 벽시계 | p50 | p95 |
|---|---:|---:|---:|
| 순차 | 2.6s | 86ms | 515ms |
| 동시 4 | 0.8s (3.3배) | 160ms | 212ms |
| 동시 8 | 0.4s (6.5배) | 134ms | 326ms |

동시성을 올려도 **건당 지연이 나빠지지 않는다** — geo가 병목이 아니라 왕복 직렬화가
병목이다. 그리고 p95가 0.5초인데 timeout은 10초다. ReadTimeout은 20배 이상치이므로
**timeout이 빡빡한 것이 아니라 이상치 한 번에 대한 내성이 0인 것**이 문제다.

**그런데 범인은 geo가 아니었다 — 원인을 다시 쟀다.**

처음에 나는 이 실패를 "geo가 느려서 timeout"으로 읽었다. 적대 리뷰가 그 전제를
의심했고(4코어에 load 17인데 geo는 CPU 0.15%로 유휴), 읽기 전용으로 다시 재니
전제가 틀렸다.

```
/proc/pressure/io   full avg300 = 25.5%   ← 전체 시간의 1/4 동안 모든 태스크가 디스크에 막힘
/proc/pressure/cpu  full avg300 =  0.0%   ← CPU는 병목이 아니다
geo 503 / E0500 (5시간)          0건      ← geo는 포화 신호를 낸 적이 없다
D 상태 프로세스                  postgres
04:05:00 최대 동시 run             8건
```

**04:03~04:05에 내가 feature job 7개를 동시에 띄웠고** weather 상시 run까지 8개가
4코어·단일 회전 디스크에서 겹쳤다. `docker/dagster.yaml`의 주석이 이미 그 사실을
적어 두었다 — *"provider job은 IO-bound이고 n150은 단일 회전 디스크를
weather/concierge/geo/airport와 공유한다. 올려도 수집이 빨라지지 않는다."*
그런데 geo를 대량 소비하는 asset에는 **pool이 붙어 있지 않다.** `concurrency.pools`
(`default_limit: 1, granularity: run`)와 `OPINET_API_POOL`·`KREX_NOTICE_SNAPSHOT_POOL`
이라는 선례가 이미 있는데 쓰이지 않았다.

**그래서 순서가 바뀐다.** 동시성을 *올리는* 것(배치 지오코딩)은 이 호스트에서
악화일 수 있다. 먼저 할 것은 ① geo 중량 asset에 pool을 붙여 **동시 실행을 묶고**,
② reverse/region 왕복을 **따로 세는** 계측을 넣어(오늘 그 수가 이 저장소에도 geo
저장소에도 없다) 분모를 만든 뒤, ③ 그 다음에 벽시계 deadline과 typed 분류를
넣는 것이다. 재시도·동시성 수치는 ②의 실측 없이 고르면 안 된다.

한계도 적어 둔다: pool은 `@asset` 데코레이터에 걸리는데 큐 경로는 그 래퍼를
**우회한다**(`feature_update_runner.py:432-433`). 즉 pool은 예약 경로만 묶는다.

**규모(조사로 정정됨).** MCST는 33,000이 아니라 13 slug 합계 **102,121행**이고,
행 수 1위는 **MOIS 980,970행**인데 그쪽은 단일 트랜잭션이라 90만 번째 행의 timeout이
앞서 적재한 전부를 rollback시킨다. dagster resource가 `region_fallback_radius_km=0.1`을
켜 두어 bjd가 안 나오는 좌표는 **행당 왕복 2회**다.

**OpiNet은 "마지막"이 아니라 "차단"이다.** `providers/opinet.py`도 주유소마다
`await reverse_geocoder(coord)`를 부른다 — 지금 쏘면 일일 쿼터를 태우고 같은
timeout으로 죽는다. 이 수정이 배포된 뒤에 쏜다.

**안전하다고 확인한 것.** MCST는 `retire_absent_from_snapshot`을 넘기지 않고 slug
단위로 커밋하므로 재실행이 안전하다(13개 중 2개 = 33,422행 이미 적재). 등산로는
`mountain_trail_segment`가 **0행**이라 은퇴시킬 것이 없어 지금 도는 run을 끝나게
두어도 파괴적이지 않다.

**runtime 상한이 34개 job 중 21개에 없다** — MOIS·MCST·등산로가 전부 거기 속하고
전역 6시간에만 매달린다. 다만 상한을 일괄로 붙이면 안 된다: MOIS는 순차 130ms ×
98만 = 35시간이라 7,200초를 붙이면 정상 run이 죽는다. 배치화 뒤에 측정해서 정할 것.

---

**이번에 닫은 것 (#1253).** `feature.feature_notices` 0행의 원인이 둘이었다.

1. 변환이 상류의 유일한 위치 단서를 버렸다. `ocrnFrcstIssuInsttNm`을 10,562건
   전수로 재 보니 **98.5%가 행정구역**(97%가 `충청남도 당진시` 꼴)인데
   `landslide_forecast_issues_to_bundles`가 빈 `Address()`를 박았다.
2. **데이터셋이 통째로 사라져도 job은 SUCCESS였다.** 10,467건을 받아 전부 버리고
   notice 0건으로 끝났는데 결과는 초록이었다. 적재율 하한을 두 적재 경로 모두에
   걸었다 — 버린 것이 남긴 것보다 많으면 적재하지 않고 죽는다.

**아직 열린 것.** D2 lane BLOCKED(`admin feature live acceptance: direct fixture
seed failed` — acceptance 하네스, prod 아님), 활용신청 4건(ansan / gyeonggi-muslim /
jeju / special-streets — 소유자 조치).

## 2026-09-19 (2) — 재배포·재실행 완료. 그리고 상한 수정이 가린 것을 드러냈다

**다음 한 작업: 산사태 notice의 위치 해석.** prod에 `feature.feature_notices`가
**0행**이다 — 이 dataset은 한 번도 적재된 적이 없다.

**왜 이제 보이는가.** 종전에는 `ProviderPaginationOverrun`으로 job이 수집 단계에서
죽어 검증까지 가지 못했다. 상한을 40장으로 올리자 처음으로 전량이 도착했고, 그
다음 단계가 **전량을 떨궜다.** 2026-09-19 04:09 실측 materialization:

```
upstream_requests_min              11      ← 상한 수정은 동작했다
address_validation_total        10467
address_validation_error_count  10467
address_validation_dropped_count 10467     ← 받은 것 전부 탈락
```

**원인 가설(미확정).** 이 feed에는 좌표도 도로명주소도 없고 위치 단서가
`ocrnFrcstIssuInsttNm`(예: `충청남도 당진시`) 하나다 — **주소가 아니라 기관명**이다.
주소 파서는 그것을 주소로 읽지 못한다. 고치려면 기관명 → 시군구 코드 경로를
따로 두어야 한다. **먼저 `address_validation_issues`의 실제 사유를 읽어 가설을
확인할 것** — 위 숫자는 "전량 탈락"을 말할 뿐 이유를 말하지 않는다.

**이것은 회귀가 아니다.** 상한 수정이 만든 것이 아니라, 상한 수정이 **처음으로
그 지점까지 도달시켜서** 보이게 된 것이다.

**재배포·재실행으로 확인된 것.** prod `697a1d87a`, migration head `310_seoul_source_move`.

| dataset | 이전 | 지금 |
|---|---:|---:|
| `datagokr_seoul_bookstores` | 0 (odcloud 404) | **606** |
| `krforest_arboretums` | 0 | **212** |
| `krforest_recreation_forests` | 0 | **182** |
| `krforest_dulle_trails` | — | **26** |
| `krforest_landslide_forecast_issues` | job 실패 | 10,467 수신 / 0 적재 |

**아직 열린 것.** MCST 문화·krforest 산악등산로 재실행 결과, OpiNet place/price
재실행(하루 예산 280/300), 그리고 D2 lane BLOCKED
(`admin feature live acceptance: direct fixture seed failed`) — prod 서비스가 아니라
acceptance 하네스 쪽이고 별건이다.

## 2026-09-19 — 원천을 고쳤다. 다음은 재배포와 재실행이다

**다음 한 작업: prod 재배포 후 실패했던 job 재실행.** prod 이미지는 아직 `e9b877b3`라
이번 묶음(provider 핀 · OpiNet 기본 모드 · 서울 책방 원천)이 하나도 실려 있지 않다.
**핀을 올리지 않으면 머지한 provider 수정이 적용되지 않는다** — 재배포 전까지 산림
표준데이터 3종과 MCST 아동서점은 여전히 0건이다.

**닫은 것.**
- provider 핀 상향 — `python-krforest-api@70814c9`(표준데이터 gateway가 response
  래퍼를 벗은 것), `python-mcst-api@0f5a8fe`(아동서점 fileDataNo 282→484).
- OpiNet 기본 모드 `low_top_area`(운영 결정). compose가 안 넘기던 호출량 노브 둘도
  배선. `.env.example`에 남아 있던 180/600(한도를 1,500으로 잘못 알던 시절 값)도
  90/140으로 정정 — 그 파일이 compose 기본값을 덮는다.
- 서울 책방 원천 → 서울 열린데이터광장 OA-21062(`TbSlibBookstoreInfo`), 라이브 606건.
  schedule을 `DISABLED_FEATURE_LOAD_SCHEDULES`에서 뺐다.
- MCST asset이 **시도하지 않은 dataset까지** 적재하던 것(worker 경로에서 12종이 빈
  authoritative 적재 + sync-success를 받았다).
- 페이지 상한 사전 경고 — 여유가 절반 아래로 내려오면 prod가 먼저 말한다.

**오너 작업으로 남은 것(코드로 못 닫는다).** data.go.kr 활용신청 4건 — 안산
세계맛집 · 경기 무슬림 친화 음식점 · 제주 향토음식점 · 지역특화거리 표준데이터.
활용신청은 키가 아니라 **데이터셋 단위**다. 신청이 끝나면
`DISABLED_FEATURE_LOAD_SCHEDULES`에서 그 이름을 빼는 것으로 되살아난다.

**별건으로 남긴 것 (1).** MCST 부분 실패 run에서 **적재에 성공한 dataset의
membership이 완료 처리되지 않는다.** `raise Failure`가 완료 콜백보다 앞에 있고,
콜백 계약(`received_memberships != memberships` → RuntimeError)과 wrapper의
`len(result.results) != len(completed_memberships)` 단언이 부분 완료를 거부한다.
증거 원장과 DB 상태가 어긋나지만 (a) 큐 경로에는 도달하지 않고(scope당 slug 1개
— multi-member run은 수동 launch나 schedule일 때만 생긴다), (b) 이번 변경의
회귀가 아니다(종전에는 실패 하나가 13개를 전멸시켰다). 고치려면 두 결박을 함께
풀어야 한다 — 2026-09-19 적대 리뷰가 확정했다.

**별건으로 남긴 것 (2).** 산사태 예보발령 증분 수집. 이 asset은
`load_authoritative_notice_snapshot`으로 `active_lineage_keys` 전체를 대조하므로,
부분 수집으로 바꾸면 화해 계약부터 다시 설계해야 한다. 지금은 상한 40장(실측 10,562행
대비 약 4배)과 사전 경고로 버틴다.

## 2026-09-16 (4) — 백업 알림은 보류, 대신 진행 중이던 사고를 고쳤다

**다음 한 작업: `T-VN-H49` 또는 `T-VN-H49-OFFBOX`** — `T-VN-H49-BACKUP-STALENESS`
조문 1(알림 경로)은 **소유자 지시로 보류**한다.

**보류 전에 얻은 것.** `geo_dagster`·`concierge`·`pinvi` 백업이 09-12부터 5일째
`Permission denied`로 실패 중이던 것을 찾아 고쳤다(git이 `scripts/*.sh` 실행 비트를
벗겼고 crontab은 경로를 직접 실행한다). 조문이 열려 있는 동안 같은 형태가 세 DB에서
재발한 것이다.

**원장 정정.** 조문 1의 "(a) api 컨테이너만 마운트한다"는 틀렸다 — api·dagster 둘 다
`backup_root`가 없고, Dagster op config schema엔 키 자체가 없으며, 자동 기록되는 F9
행은 예외 없이 `observed=false`다. 그리고 **없는 디렉터리가 진짜 중단과 같은 신호**가
되는 F9 결함은 알림과 독립이라 따로 고칠 수 있다.

**재개할 때 첫 일은 채널 실배달 육안 확인이다.** 설계는 확정돼 있다(소유권 →
`kor-travel-docker-manager`, 채널 → ntfy). 기대치 모델 초안이 그 저장소에 미커밋으로
있다: `config/backup-policy.yml` · `services/backup_policy.py` ·
`services/backup_watchdog.py`. 소비자가 없어 커밋하지 않았다.

**열린 항목(활성 셋):** `T-VN-H49-BACKUP-STALENESS` 조문 1(**보류**) ·
`T-VN-H49` · `T-VN-H49-OFFBOX`. 보류 셋: `T-VN-41C` · `T-VN-H43` · `T-101`.


## 2026-09-16 (3) — M02·LEDGER-ARCHIVE 완주. 활성 항목이 H49 계열 셋만 남았다

**다음 한 작업: `T-VN-H49-BACKUP-STALENESS` 조문 1** — F9는 판정하지만 **사람에게 닿는
경로가 없다**. Dagster 배치에 `backup_root` 볼륨이 없고 `ops.feature_consistency_reports`를
아무도 폴링하지 않는다. 425건이 조용히 실패한 이유가 검사 부재가 아니라 **보는 사람
부재**였으므로, 검사를 더하는 것으로는 닫히지 않는다.

**`T-VN-M02` 완료.** live301에서 `E2E_MANUAL_CREATE_WRITE=1`로 **2 passed (47.9s)**,
DB 실측으로 `manual_admin` / `e2e-admin` / `ktm_feature_api_runtime` /
`ktm_manual_feature_procedure_owner` / `admin-ui-bff.manual-feature-create.v1` 확인.
**이 spec은 한 번도 실행된 적이 없었다** — 첫 실행이 초록이다.

**원장 기록이 또 낡아 있었다.** "격리 스택이 없다"(2026-09-08)는 틀렸고 pg는 5일째 떠
있었다. 실제로 막던 것은 (1) 체크아웃 이동 시 사라지는 `scripts/*.sh` 실행권한,
(2) **Dagster 메타DB 통째 부재**(롤·DB 생성 + `dagster instance migrate` 필요)였다.
spec 자체는 Dagster를 안 쓰지만 `run-admin-stack.sh`에 건너뛰기 경로가 없다.

**`T-VN-LEDGER-ARCHIVE`도 함께 닫았다.** 조문 2·3은 #1239가 이미 넣은 것이었는데 표기만
열려 있었다. 오늘 원장이 다시 220 KiB를 넘어 그 도구를 **실전에서 썼고**, 닫힌 절 둘을
검산 통과 후 옮기고 넷을 이유와 함께 거절했으며, 삭제 게이트가 아카이브 미커밋 상태를
잡아냈다 — 코드가 있다는 것보다 강한 근거다.

**열린 항목(활성 셋, 전부 H49 계열):** `T-VN-H49-BACKUP-STALENESS` 조문 1 ·
`T-VN-H49` · `T-VN-H49-OFFBOX`.
**보류 셋**(잔여로 세지 않음): `T-VN-41C` · `T-VN-H43` · `T-101`.

**오늘 네 번 낡은 기록에 막혔다** — `T-VN-D2-RESIDUE`(나흘), `T-VN-DAGSTER-STORAGE`
조문 1(배포가 증거를 지움), `T-VN-M02`(여드레), `T-VN-LEDGER-ARCHIVE`(사흘). 넷 다
**일이 남아서가 아니라 기록이 따라가지 않아서** 열려 있었다. `docs/tasks-rule.md` §6이
이 형태를 다루지만 규약만으로는 부족하다 — 조문을 닫는 PR이 그 조문을 실제로 닫는지
보는 장치가 없다.


## 2026-09-16 (2) — seal ACL 닫힘, 그리고 prod는 배포마다 새로 태어난다

**다음 한 작업: `T-VN-M02`** — 소유자 판단이 먼저 필요하다. 격리 스택을 다시 세울
것인지, purge를 HTTP로 노출할 것인지. 후자는 원장 기준 **순서 역전**이다(복원 증명은
`T-VN-H49`가 소유한다).

**`T-VN-CURATION-SEAL-ACL` 완료.** 세 조문 전부 실측으로 닫았다 — prod run `0f70d0d5`
`SUCCESS`(`features 1047 · seal 영수증 1건`), 배포 재적용 뒤에도
`dagster_seal=true / api_seal=false`, 실 login으로 적재 경로를 태우는 회귀 추가(변이
빨강 확인). 같은 실행으로 `T-VN-DAGSTER-STORAGE` 조문 1도 현 세대에서 다시 섰다.

**알아 둘 것 — prod DB는 배포가 새로 만든다.** `kor_travel_map` 생성 시각 =
t44a 배포 시각. 그래서 "prod에서 …가 완주한다" 형태의 조문은 다음 배포에서 `[x]`만
남고 근거가 사라진다. 규약은 `docs/tasks-rule.md` §6. 전수 확인상 실제로 그 자리였던
것은 `T-VN-DAGSTER-STORAGE` 조문 1 하나다.

**n150 네 세션 게이트에 mypy가 없다.** `sample_ids=()` 한 줄이 게이트 전부를 초록으로
지나 CI lint에서만 빨개졌다. PR 전에 mypy 3종 + lint-imports를 따로 돌린다.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3, `T-VN-LEDGER-ARCHIVE` 조문 2·3,
`T-VN-M02`, `T-VN-H49`/`-OFFBOX`, `T-VN-H49-BACKUP-STALENESS` 조문 1.


## 2026-09-16 — 일일 예산은 만들지 않는다 (분자를 재서 나온 결론)

**다음 한 작업: `T-VN-LEDGER-ARCHIVE` 조문 2·3** — 원장 분리가 fence parity를
검산하게 하고, 아카이브를 삭제 감시 대상에 넣는 일. 조문 1(220KB 아래)은 닫혔다.

**쿼터 축이 전부 닫혔다.** `T-VN-QUEUE-QUOTA`(6/6)와 `T-VN-KREX-TPS-FANOUT`(4/4)
둘 다 완료로 이관했다. 조문 3의 답은 **"집행하지 않는다"**였다 —
`ops.provider_refresh_policies`가 prod에서 **0행**이고(seed도 0) 행이 없으면
`_skip_reason()`이 fail-**open**한다. gate가 그 테이블을 읽게 만들면 읽을 값이 없어
통과시켜 **코드 상수보다 나빠진다.** **분모가 아니라 분자를 재서** 판단했다 —
전국표준데이터는 하루를 넘기려면 총건수 166,000이 필요한데 실측 최대가 **18,883**
(`parking`)이다. visitkorea 5%, 산림청 0.6~6%, `krairport` **0건**(번들 데이터).
가장 좁은 `opinet`(300/일)은 이미 run당 예산이 있다. (`special_street`가 prod 키로
403인 것은 관측했으나 **평가 대상에서 제외**한다 — 2026-09-16 지시.)

**장치 대신 구멍 셋을 닫았다:** khoa 페이지 절대 상한 + stall 지문(선언 총건수 하나가
틀리면 하루치를 넘길 수 있었다), `opinet_run_call_budget`의 `le` 300→150(2 run × 300
= 600이 **설정 가능**했다).

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3, `T-VN-LEDGER-ARCHIVE` 조문 2·3,
`T-VN-M02`, `T-VN-H49`/`-OFFBOX`, `T-VN-D2-RESIDUE`, `T-VN-CURATION-SEAL-ACL`.


## 2026-09-15 — t44a 배포 완료, async 이관이 prod에서 돈다

**다음 한 작업: `T-VN-QUEUE-QUOTA` 조문 6 — 분모가 *있는* provider에 일일 예산을
둘지 판단.** krex는 TPS로 닫혔고(`T-VN-KREX-TPS-FANOUT` 조문 1·2·4), 남은 것은
분모가 있는 쪽이다.

`#1235`(provider 13개 async-only) 머지 후 t44a 재핀 전 사이클 GREEN — D1 live
Playwright 11 passed, D2 `phase=passed`. **prod에서 직접 읽어** 새 라이브러리(동기
`close` 없음, 전부 coroutine)와 gate(`{'krex': 0.2}`, 4건 선언, 계수기보다 바깥)가
살아 있는 것을 확인했다. **버전 문자열로는 판별되지 않아**(13개 전부 `0.1.0`) 코드의
성질을 물었다.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3(정책 테이블 `max_concurrent` 집행),
`T-VN-QUEUE-QUOTA` 조문 6, `T-VN-LEDGER-ARCHIVE` 조문 2·3, `T-VN-M02`,
`T-VN-H49`/`-OFFBOX`, `T-VN-D2-RESIDUE`, `T-VN-CURATION-SEAL-ACL`.


## 2026-09-15 — provider 13개 async-only 이관 (브랜치 `feat/provider-async-tps-migration`)

**다음 한 작업: n150 4세션 게이트 결과 확인 → PR → 머지.** 그 뒤 prod 재핀
(`/root/chain17.sh`)이 따라온다 — provider 핀이 13개 바뀌었으므로 이미지 재빌드가 필요하다.

형제 `python-*-api` **13개 전부**가 native async only + 공유 TPS 제어로 재작성됐다
(사용자 개편). Map을 그 표면에 맞췄다 — 핀 13개, fetcher 20개 async 전환, 경계 4곳,
manifest 재생성, 계약표 13행.

**어제의 krex TPS 브랜치(`python-krex-api` `feat/http-tps-limit`)는 흡수됐다.** 새
라이브러리가 그 기본값과 검증을 그대로 갖고 있다(실측 확인). 머지하지 않고 접는다.
**Map 쪽 `provider_rate_gate`는 살아남는다** — 새 `rate_limiter=` 주입은 한 이벤트
루프 안에서만 성립하고 Map의 fan-out은 프로세스를 가로지른다.

검증(기준선 비교):

| | 브랜치 | HEAD 기준선 |
|---|---:|---:|
| dagster 세션 | 680 passed / **10 failed** | 675 passed / **같은 10 failed** |
| 실패 집합 | — | **IDENTICAL(회귀 없음)** |

남은 10건은 dagster 버전 환경 문제(`test_storage_migration_command` 9 +
`test_definitions` 1). tests/lint 288 passed(conformance 38 포함), ruff 전 트리 clean.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3·4(정책 테이블 집행 여부, prod 실측),
`T-VN-QUEUE-QUOTA` 조문 6(분모가 있는 provider의 일일 예산),
`T-VN-LEDGER-ARCHIVE` 조문 2·3.


## 2026-09-14 — 분모가 없는 provider를 분모 없이 막았다 (krex TPS 5)

**다음 한 작업: `T-VN-QUEUE-QUOTA` 조문 6 — 분모가 **있는** provider에 일일 예산을
둘지 판단.** 조문 5(`krex`)는 닫혔다.

**`krex`는 일일 한도를 기다리지 않고 축을 바꿨다.** 포털 네 면 어디에도 일일 수치가
없고 남은 길은 문의뿐이었는데, **이 provider에서 실제로 조일 수 있는 것은 간격이다.**
`python-krex-api` `feat/http-tps-limit`이 `KrexHttp`에 token bucket을 넣어 **초당
5건**을 넘기지 않는다(`max_rps` 기본 `5.0`, `KrexClient`/`AsyncKrexClient`로 전달).

세 가지를 일부러 다르게 했고 각각이 그냥 두면 틀렸을 자리다:

- **버스트 없음(capacity=1)** — capacity가 `max_rps`면 가득 찬 버킷에서 5건이 즉시
  나가고 그 초에 지속분이 더해져 **첫 1초에 10건**이다. 상한이지 평균이 아니다.
- **재시도도 요청이다** — 버킷이 재시도 루프 **안**에 있다.
- **락이 `threading.Lock`이다** — `_run_sync`가 호출마다 새 루프를 만들고 러닝 루프가
  있으면 별도 스레드에서 돈다. `asyncio.Lock`은 스레드를 전혀 막지 못하면서 막는 것처럼
  읽히고, 경합하면 처음 본 루프에 묶여 다음 루프에서 `RuntimeError`를 낸다(3.14 재현).

검사기는 일곱 변이로 확인했다(상한 끄기 / capacity 되살리기 / 기본값 / acquire를 루프
밖으로 / client 미전달 / go 포털만 우회 / 우회하는 새 전송 자리) — 각각 다른 테스트가
잡는다. 마지막 것은 AST로 `session.get(...)` 자리가 하나임을 본다. **효과 검사는 지금
있는 경로만 보므로 새 경로는 아무 테스트도 건드리지 않고 상한을 비켜 간다.**

**그리고 Map 쪽에서 내가 틀렸다.** "큐 러너가 순차 처리하므로 합계 5 TPS"라고
적었는데, 적대 리뷰 둘이 **독립적으로** 뒤집었다 — 그 순차성은 run **하나 안에서**의
이야기다. 큐 센서는 틱당 RunRequest를 10개 내고(`RUNNING`, 15초 틱),
`docker/dagster.yaml`이 `tag_concurrency_limits`로 **4를 동시에** 돌린다. run마다
프로세스가 다르니 `KrexClient`도 버킷도 넷 → **최대 20 TPS.** krex를 직렬화하는 것은
아무것도 없다(scope advisory lock은 키가 다르고, Dagster pool은 asset에만 있는데 큐
경로가 asset을 우회하며, `provider_refresh_policies.max_concurrent`는 **읽히기만 하고
집행되지 않는다**).

**닫혔다고 적은 구멍이 현재 설정으로 열려 있었다.** 지금 보증되는 것은 "프로세스당
5 TPS"이고 합계가 아니다. 남은 작업을 `T-VN-KREX-TPS-FANOUT`으로 뺐다 — 고칠 자리는
`max_rps`가 아니라 **provider 단위 동시성 집행**이고, 스키마
(`ops.provider_refresh_policies.max_concurrent`)는 이미 있다.

**아직 Map에 반영되지 않았다** — `pyproject.toml`의 krex 핀이
`c6d8717ec2b712cc952bc566b351f07a7cd3824a`다. krex PR 머지 후 repin이 따라온다.

t43a 배포 완료(`e3fddce81`, 전 사이클 GREEN — D1 live Playwright 11 passed,
D2 phase=passed). prod 실측으로 OpiNet 예산 140/90과 큐 skip 6건이 살아 있는 것을
확인했다.

분모 조회는 끝났다 —
`opinet` **300/일**(저장소가 1,500으로 알고 있었다), `krheritage`·`mois`는 **키가
없어 한도 자체가 없고**(mois는 data.go.kr 파일데이터가 기관 자체 다운로드 URL을
가리킨다 — 이관됐지만 파일 경로는 그대로다), `krex`만 **미공개**라 문의가 남았다.
2026-09-14에 넷을 다 봤고 결과가 갈렸다: **opinet 300/일**(저장소가 1,500으로 알고
예산 600을 세웠다 — 켜면 첫날에 막혔을 값, 140/300/90으로 고침), **krheritage는
인증키가 없어 한도 자체가 없다**(위험은 쿼터가 아니라 차단), **mois도 키가 없다**
(data.go.kr 파일데이터가 기관 자체 다운로드 URL을 가리킨다 — "사이트 무응답으로 확인
실패"라고 적었던 것은 같은 날 뒤집혔다: 죽은 것은 사람용 포털이고 파일 호스트는
살아 있었으며, 깨진 것은 Referer 없는 내 curl이었다), **krex는 일일 한도 미공개라
TPS 5로 막았다**(위 참고).

**급하지 않다.** 2026-09-14 prod 실측 feature asset materialization **0건**이고
feature cron schedule은 전부 꺼져 있다 — 쿼터가 압박받는 상황이 아니다. 큐 예산
장치는 분모를 보고 나서 필요한지 판단한다("측정 전에 상한 숫자를 바꾸지 않는다").
KMA·에어코리아는 평가 대상에서 제외(2026-09-14 지시).

`T-VN-QUOTA-ARITHMETIC`은 여섯 조문 전부 `[x]`로 닫혔다. 분모 실측(오퍼레이션마다
따로 걸린다) · 분자(`upstream_requests_min`, #1229) · 쿼터성 실패의 재시도 차단
(#1227) · 증폭기 선언 · UI 보증 제거 · KMA 재활성화 전제. prod 배포 t41a·t42a 두
사이클 GREEN.

**조사 중에 blocker 하나를 찾아 고쳤다.** `DISABLED_FEATURE_LOAD_SCHEDULES`
(2026-09-09 사용자 지시로 KMA·AirKorea 자동 적재 중지)는 **시계만** 껐다. prod는
cron이 아니라 feature update queue로 도는데(schedule 전부 STOPPED, 큐 센서만
RUNNING) 큐 runner에 꺼진 operation의 spec이 그대로 있었고 정책 게이트는 row가
없으면 fail-open이다 — 즉 **사용자가 끈 provider가 살아 있는 경로로 나가고 있었다.**
지금은 큐 경계가 `DISABLED_FEATURE_LOAD_OPERATION_KEYS`를 읽어 건너뛴다.


## 2026-09-11 — T-VN-39 재키가 착지했다 (#1197, `e8c66c47`)

`feature.features.feature_id`가 uuid다. 서버가 적재 시점에 발급하는 UUIDv7이고 어떤
입력에서도 유도되지 않는다. 예전의 `f_*` 주소는 `feature.feature_aliases.alias`의
**주소 등록부**로 옮겨 갔고, 그 주소로 들어와도 같은 Feature가 나온다(ADR-098).
**바깥 이름은 하나도 바뀌지 않았다** — 바뀐 것은 값의 출처뿐이다.

같은 날 보안 PR #1198(maplibre-gl 6 · Next 16.3.4 · sharp 0.35.4)이 먼저 들어갔고,
재키 PR이 그 위에 얹혔다.

### 착지 시점 게이트

| 층 | 결과 |
|---|---|
| GitHub CI 9종 | 전량 초록 |
| n150 — provider **실제 설치** | dagster 575 · api 1,223 · lint+unit 2,832(환경 실패 14) |
| 제품 SQL 786문 head Parse | 초록 (587 → 786) |
| live — 필터 3갈래 | 200 / 200(빈 목록) / **422** |
| live — DB→API→실제 브라우저 | 통과 |

### 이 작업이 남긴 규칙 다섯

1. **검사가 초록인 것과 결함이 없는 것은 다른 사실이다.** 가르는 방법은 검사에
   결함을 일부러 넣어 보는 것뿐이다 — 그렇게 해서 FK 검사가 **항진명제**였음을
   찾았다(정본을 마이그레이션과 함께 움직이는 덤프에서 읽고 있었다).
2. **하한은 "판단 대상 수"가 아니라 "대상을 실제로 몇 개 보았는가"에 건다.**
   앞의 것은 결함이 고쳐지는 순간 0이 되어 빨개진다.
3. **개수 세기는 전칭 명제가 아니다.** 표면을 열거해야 "변환 안 된 자리"가 보인다 —
   uuid 필터 하나가 그래서 500인 채로 남아 있었다.
4. **쪼개서 빠르게 도는 하네스는 그 자체가 프록시다.** 통합을 9묶음으로 나눠 돌면
   세션 공유 DB에 쌓이는 상태가 보이지 않는다. 머지 전에 한 번은 CI와 같은 방식으로.
5. **결함을 만든 자리와 그것을 가린 자리는 따로 있을 수 있다.** API 패키지의
   autouse echo-resolve가 uuid 해석 축을 구조적으로 관측 불가로 만들고 있었다.

### 열린 후속 둘

- **API 패키지 conftest의 echo-resolve가 재키 이전 세계를 모사한다**
  (`feature_id=ref`). 그 patch가 깔린 채로는 "legacy 주소가 uuid로 바뀌는가"와
  "없는 참조가 422인가"를 관측할 수 없다. 지금은 그 축을 재는 테스트가 자기
  resolver를 설치해 우회한다. echo 자체를 재키 뒤 모양으로 바꾸는 것은 이 패키지
  테스트 47곳이 참조 문자열을 그대로 기대해 별도 작업이다.
- **datagokr/krheritage upstream의 페이지네이션 퇴화.** Map은 위임을 끊어 스스로를
  지켰지만(`total` 권위 페이지네이터), 근본 수정은 provider 쪽이다. 다른 소비자는
  여전히 노출돼 있다.

### 다음 한 작업

**prod Map 배포.** Map revision이 바뀌었으므로 D2 재핀 사이클 전체가 따라온다
(rotate → rebuild → 이미지 → repin → preflight → D1 → D2). `docs/` 안의 prod 배포
절차와 PinVi token pair 규약을 따른다.

그 뒤 **T-VN-34C paired fresh-live 레인**은 여전히 별도다 —
`consumer-rollout-v1.json`의 T-VN-40 paired consumer receipt가 `pending`이고, 그
blocking_reason 자체가 "Map Admin provenance가 opaque feature_id + required
feature_uuid로 바뀌었으니 full-admin artifact를 다시 vendoring하고 PinVi M05
attestation을 붙여 paired acceptance를 다시 돌려라"다.

## 2026-09-08 (3) — 원장이 밀려 있던 둘을 정리하고 계약 하나를 개정했다

두 PR이 머지됐다 — Map #1194(9개 체크 전부 통과), Manager #335.

| 항목 | 상태 |
|---|---|
| `T-VN-M05-VERIFY-RECEIPT` | **완료** — V1~V4 전부. 원장만 밀려 있었다 |
| `T-VN-M02` | 잔여 셋 중 **둘이 이미 해소**됐는데 문장이 안 따라갔다 |
| `T-VN-39` 소유자 판정 | **없어졌다** — 계약 개정으로 |
| 열린 항목 | 8 → **6**(보류 셋 포함) |

**`T-VN-M02`의 잔여는 하나뿐이다.** purge 정책은 306이 닫았고, backup/restore 축은
2026-09-07 판정으로 `T-VN-H49`가 가져갔으며, live acceptance **spec 회수도 끝났다**
(main에 있다). 남은 것은 **실행**이고 그것이 막힌 이유는 셋인데 그중 하나는 306이 절반
풀었다 — "지워지지 않는 write"는 hard-purge fence가 유일한 삭제 경로를 거부해서 생긴
것이었고 이제 감사되는 purge 명령이 있다. 남은 것은 prod UI의 actor 불일치와, 무엇보다
**격리 스택 재구축**이다(`~/ktm-live-301`은 정지가 아니라 사라졌고 302 head다).

**`notice_states` 계약 개정(소유자 승인).** removal manifest에서 (c)를 뺐다 — 대체를
정당화한 "문자열 시각 판정"이 `T-VN-35B`/`T-VN-37D`로 이미 없어졌고, 그 항목의
`fenced_by`(`T-VN-37B`)는 **원장에 존재한 적이 없는 유일한 entry**였다. 목표 상태 DDL은
"채택되지 않음" 표시만 달고 남긴다 — 지우면 같은 논의를 다시 해야 한다.

### 착수 가능 — 소유자 판정 없이

1. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 이제 판정 대기가 없다. 컬럼 37 · FK 34 ·
   인덱스 57의 rekey 공학이고, `feature.features`가 0행이라 데이터 이행 위험이 없다.
2. **`T-VN-M02` live acceptance** — `~/ktm-live-301` 재구축이 선행이다.
3. **`T-VN-H49` 잔여** — `geo` 예약 성공 누적과 문서 갱신.

### 소유자 판정 대기 — 둘

1. `T-VN-H49` **manual Feature hard purge**는 닫혔다. 남은 것은 off-box 목적지 —
   호스트·계정·**root가 쓸 수 있는** ssh 키. 코드는 이미 있다.
2. 없음(`notice_states`가 해소되어 하나로 줄었다).

### 미조치 리뷰 findings

적대 리뷰 23건 중 7건을 고쳤다. 남긴 P2 셋은 동작 결함이 아니라 설계 여백이다 —
second-level cascade가 복구점 밖, `count_rows_dynamic`의 `search_path` 폭, DELETE fence는
여전히 origin.

**오늘 배운 것.** 리뷰 셋이 각각 같은 맹점을 찔렀다 — 변이 축이 "코드를 **지우면**
빨개지나"만 묻고 "이 술어가 덮는 **범위**가 맞나"를 묻지 않았다. 그리고 공유 session DB의
**전역 집계 단언을 여섯 번** 고쳤다(전부 "무엇이 일어났나"가 아니라 "DB가 비어 있나"를
재고 있었다).


## 2026-09-08 (2) — purge를 열고, TRUNCATE fence와 소비 기록을 닫았다

| 항목 | 상태 |
|---|---|
| `T-VN-H49` hard purge 정책 | **완료** — migration 306, 소유자 승인 |
| `T-VN-M02-TRUNCATE-FENCE` | **완료** — migration 307, `ENABLE ALWAYS` |
| `T-VN-M05-ONESHOT-CONSUME` | **완료** — Manager #335 |
| `T-VN-M05-VERIFY-RECEIPT` | V1·V2·V4 완료, **V3만 남음**(소유자 판정 포함) |
| 열린 항목 | 8 → **5**(보류 셋 포함) |

**purge가 자기 복구점을 들고 다닌다.** 소유자가 건 "restore proof 먼저" 전제는 문자
그대로는 아직 안 맞는다(복원 메커니즘은 증명됐지만 복구점이 없다). 지우기 전에 cascade로
사라질 행을 전부 담게 해서 그 전제를 우회했고, 그 우회를 소유자가 승인했다.

**TRUNCATE fence는 `ENABLE ALWAYS`다.** origin이면 `replica` 한 줄로 사라지고, 그 한 줄은
이 표를 TRUNCATE할 수 있는 유일한 행위자가 언제든 쓴다 — 정직한 위협 모델은 적대자가
아니라 실수다.

### 적대 리뷰 둘이 내 변이 검증의 구멍을 잡았다

Manager 리뷰(14건 → 2 확정)의 P1이 결정적이었다 — 소비 검사의 phase 필터를 **약화**하는
변이가 초록이었다. **내 변이 축은 "지우기"만 재고 "약화"를 재지 않았다.** 그 부류를
전부 다시 봐야 한다. Map 306/307 리뷰는 이 글 쓰는 시점에 진행 중이다.

### 착수 가능 — 소유자 판정 없이

1. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 가장 큰 축이고 소유자 판정 대상이 아니다.
   대체 identity와 fence가 이미 prod에 있고 `feature.features`가 0행이라 데이터 이행
   위험이 없다. 컬럼 37 · FK 34 · 인덱스 57의 rekey 공학이다.
2. **`T-VN-M02` live acceptance** — `~/ktm-live-301`을 **재구축**해야 한다(정지가 아니라
   사라졌고, 체크아웃은 302 head이며 spec 자체가 없다). purge가 열려 cleanup 이야기는
   풀렸다.
3. **`T-VN-H49` 잔여** — `geo` 예약 성공 2건 더 쌓이기를 기다리는 것과 문서 갱신.

### 소유자 판정 대기 — 셋

1. `T-VN-M05-VERIFY-RECEIPT` **V3** — receipt 인용이 승격 정의의 "출력을 이 절에
   기록한다"와 충돌한다. 그 문장의 개정이 함께 가야 한다.
2. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·**root가 쓸 수 있는** ssh 키.
3. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가.


## 2026-09-08 — T-VN-M05 완주. 열린 항목은 여섯이고 소유자 판정은 셋이다

| 항목 | 상태 |
|---|---|
| `T-VN-M05` | **완료** — 조문 M05-1~M05-7 전부 충족 |
| M05-2 | evidence export(A)·오프라인 검증(B)·리허설 소유권 증명(C)·**복원본 수리(D)** |
| M05-5 | 전용 admin 라우트 `src/app/admin/manual-provider-dedup/` |
| 실측 | n150 M05 통합 42건, 세 배치 순서 36건, 변이 14축 전부 RED |
| restore 정책 | **변함없이 닫혀 있다**(2026-08-26 소유자 결정) |

M05-2를 닫으면서 판정을 한 번 되돌렸다. "lease를 evidence root에 담지 않으니 fencing
token이 되살아날 자리가 없다"는 **번들에 대해서만** 참이었다 — `pg_dump`는 스키마 전체를
담으므로 복원본에는 lease 행이 dump 시점 `(worker_id, lease_epoch)`를 달고 살아 돌아오고,
복원본은 사본이라 그 토큰이 양쪽에서 동시에 유효하다.

### 착수 가능 — 소유자 판정 없이 지금 할 수 있는 것

1. **`T-VN-M05-VERIFY-RECEIPT`** — V1·V2·V3 미충족. `verify_leaf`는 정말 아무것도 쓰지
   않는다(`m05_isolated_e2e.py:2388-2405`). 다만 **V2가 요구하는 값은 전부 이미 지역변수로
   살아 있다**(pinset·Map/PinVi revision·binding의 Manager revision·claim). 두 갈래 함정:
   신뢰 경계 거부 경로(`:2445`/`:2448`)는 axis를 하나도 안 남기고 `return 1`하므로 "실패도
   남긴다"가 가장 필요한 곳이 비어 있고, V3는 조문 `:1386-1388`이 "출력을 이 절에
   기록한다"고 **명령**하고 있어 조문 정정이 함께 간다.
2. **`T-VN-M05-ONESHOT-CONSUME`** — 성공 분기가 아무것도 안 남긴다. **소비를 scoped
   `phase`로 기록하면 L8 호환이 공짜로 풀린다**(L8은 `entry.phase is None`만 본다).
   **`result.json`에 키를 추가하면 안 된다** — 런처가 정확한 키 집합을 강제해
   (`run-m05-isolated-e2e-once:505-519`) 불일치가 성공한 실행을 무조건 소각한다.
3. **`T-VN-M02-TRUNCATE-FENCE`** — 원장 서술 둘이 틀렸다(아래 §정정). 트리거를 더하는
   비용은 통합 테스트 **0곳**이다.
4. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 소유자 판정 대상이 아니다. 대체 identity
   (`feature_uuid` + unique 둘)와 fence 트리거가 이미 prod에 있고 `feature.features`는 0행이라
   데이터 이행 위험이 없다. 남은 것은 컬럼 37 · FK 34 · 인덱스 57의 rekey 공학이다.
5. **`T-VN-H49` 잔여** — `geo` 예약 성공 2건 더 쌓이기를 기다리는 것과 문서 갱신뿐이다.

### 소유자 판정 대기 — 둘

~~`T-VN-H49` manual Feature hard purge 정책~~ — **2026-09-08 판정·구현 완료**(migration
306). 감사되는 운영 명령으로 열되 UI 버튼이 아니고, purge가 자기 복구점을 담아 H43
보류에 묶이지 않게 했다. claim의 두 역할을 갈라 tombstone을 관리 가능하게 했고 ADR-093에
개정 한 문장을 박았다. 상세는 `docs/tasks-acceptance.md` §T-VN-H49.

1. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·**root가 쓸 수 있는** ssh 키. 코드는 이미 있다
   (`offbox_backup_sync.py`, CLI, 상태 API). `/opt` `.env`에 `KTDM_OFFBOX*` 0개.
2. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가. 새 선행 항목을 세울
   것인가, 아니면 removal manifest에서 (c)를 뺄 것인가(frozen 계약 개정).

**보류/제외 셋**: `T-VN-41C`·`T-VN-H43`·`T-101` — 셋 다 재개 조건이 아직 발화하지 않았다
(41C·H43은 실 production 전환, T-101은 SLO 정의와 ADR-073 의미 택일).
**외부 추적**: `GM-17`(가장 마지막).

### 정정 — 이전 실측 둘이 틀렸다

- **"n150에 예약 백업이 아예 없다"는 틀렸다.** `digitie` crontab에 `geo_dagster`·
  `concierge`·`pinvi` 셋이 매일 돌고 2026-08-21부터 **18일 연속 성공**했다. root로 실행한
  조회가 `/root/backups`를 봤고 cron은 `KTDM_BACKUP_ROOT=/home/digitie/backups`를 쓴다 —
  **다른 디렉터리를 보고 "없다"고 적었다.** `map_application`이 어느 cron에도 없는 것은
  `T-VN-H43`의 의도된 보류다.
- **"TRUNCATE CASCADE가 hard-purge fence를 통째로 우회한다"도 틀렸다.** CASCADE 폐포 30개
  중 10개에 BEFORE TRUNCATE 가드가 켜져 있어 실제로는 중단된다. fence가 그 거부에 기여하지
  않고 진단이 엉뚱한 이유를 대는 것이 진짜 결함이다. "통합 테스트 24곳"도 **14곳**이고,
  `_db_cleanup.py:49`가 이미 `session_replication_role = replica`로 돌아 트리거를 더해도
  **0곳이 깨진다**. 원장이 놓친 더 큰 구멍은 `ops.feature_requests`로, TRUNCATE 가드도
  append-only 가드도 없다.
- **`~/ktm-live-301`은 "정지"가 아니라 사라졌다** — 컨테이너도 볼륨도 없고, 그 체크아웃은
  302 head이며 해당 spec 자체가 없다. `T-VN-M02` live acceptance는 재기동이 아니라 재구축이
  선행이다.


## 2026-09-06 — D2 lane이 api-audit까지 완주했다

| 항목 | 상태 |
|---|---|
| pinset | Map `631f1abc` + PinVi `b9637375` |
| `T-VN-D2-API-AUDIT` | **완료** — `ktdm-d2-008` `phase: passed`, runner exit 0 |
| lifecycle | 56 = 7 operation × 8 phase (`helper-api-audit` 8개) |
| evidence | `phase: evidence-validated`, 파일 집합 exact, FK 제약 18, 리포트 2 |
| api-audit | counts 3·1·7·3, FK 18/8, `feature_ids`·`feature_uuids` 각 1건 |
| 선행 축 | ACL preflight 55/55, D1 11 passed |

`feature_id` 규칙은 서로 다른 실행이 만든 Feature **셋**으로 배포 DB에서 확인했다 —
새 규칙(uuid 재현) 3/3 일치, 구 규칙(run_id 재계산) 3/3 불일치.

### 다음 한 작업

**2026-09-07 소유자 판정 4건이 들어왔다.** 열린 항목은 15 → **11**이 됐다(보류/제외 3 포함).

| 판정 | 결과 |
|---|---|
| 승격 정의 변경 | `T-VN-M05-ACTIVATION` — 문서 행위가 아니라 **재계산 가능한 대조**로 정의. Manager `--verify-leaf`가 해시 사슬과 살아 있는 pin registry를 대조한다. 서명은 근거에서 뺐다(키가 실행마다 새로 생겨 사후 검증 불가) |
| 과대 계상 삭제 | `T-VN-M02`에서 backup/restore 축 제거 — 소유는 `T-VN-H49` 계열 |
| H34는 CSV만 | `T-VN-H34` **완료**. 범위 밖 넷은 지우지 않고 acceptance에 남겼다 |
| D1이 자격증명을 갚음 | `T-FE-MOCK-FLAKE` **완료** |

**착수 가능 — 순서대로.**

1. `T-VN-M02` **spec 회수** — 미병합 브랜치 유실 위험. 판정과 무관하게 먼저.
2. `T-VN-H49` 자식 셋 복원 리허설 — Manager `rehearse-restore` 결함을 고쳐 배포한 뒤
   실행한다(`geo_dagster`·`concierge`는 백업 0건이라 `create` 선행).
3. `T-VN-M04` — 조문을 세웠고 reject 통합 테스트를 더했다. CI green이면 닫힌다.

**소유자 판정 대기 — 여섯.**

1. `T-VN-M05-ACTIVATION` A2 — "실행은 단 한 번"의 기준(기계는 execution identity당 1회를
   강제한다. 한 pinset 아래 leaf가 셋 생겼다).
2. `T-VN-M02` purge 정책 — evidence cascade/orphan·권한·409 계약.
3. `T-VN-H49` 자식 셋의 리허설 **기록 위치**.
4. `T-VN-H49` 부모 — 고착 `load_jobs` 해소를 위한 prod 쓰기 승인.
5. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·ssh 키. **그리고 n150에 예약 백업이 아예 없다**
   (root crontab 없음·timer 없음·logrotate 미설치, geo·geo_dagster·concierge 백업 0건).
6. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가. 가장 큰 축이다.

**보류/제외 셋**: `T-VN-41C`·`T-VN-H43`·`T-101`. **외부 추적**: `GM-17`(가장 마지막).

## 2026-09-06 — D2 통과, receipt 승격

| 항목 | 상태 |
|---|---|
| `T-VN-M01` 활성화 | **완료** — ACL 55/55(rebuild 앞뒤 두 번) · 거부 축 4/4 403 · witness 8관계 zero-write · 성공 축 201 |
| kill-switch | `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true` (2026-09-05T20:27:59Z) |
| D2 스펙 | **in-lane 통과** — main·recovery 각 `{"counts":{"passed":2},"result":"passed"}` |
| `T-VN-41F1D-D2` | **통과** — `phase: passed` / `status: complete` (2026-09-06T01:47:03Z, runner exit 0, 1분 43초) |
| D2 증거 | `phase: evidence-validated` — 파일 집합 exact(10), lifecycle 48, FK 제약 18, 리포트 2 |
| D2 잔여물 | 독립 측정으로 0 — acceptance 소유 row 0, 라벨 컨테이너 0, BLOCKED/ACTIVE/RESULT 없음 |
| 선행 축 | 같은 pinset에서 ACL preflight 55/55 · D1 11 passed(29.9초) |
| 게이트 | 결함마다 `tests/lint/` 탐지기, 전부 변이로 red 확인 |
| pinset | Map `ab3640f8` + PinVi #535 — rebuild `48166bd2…`, generation `56d331a7…` |

### 다음 한 작업

**`T-VN-41C`의 구조적 순환에 대한 소유자 판정.** 선행 배리어는 전부 닫혔다 — D1·D2·
`T-VN-41F1D-E`·`T-VN-M01` 완료. 41C의 relay·reconciliation은 **구현이 끝나 있다**(2026-09-06
재조사가 종전 서술을 정정했다). 남은 셋 중 앞의 둘은 셋째가 풀리기 전에는 착수할 수 없다:

1. **런타임 결선** — 배포 Map 컨테이너에 `..._CACHE_TARGET_SERVICE_PRINCIPALS`가 없어 service
   표면이 401이고 relay 관계 19개가 전부 0행이다.
2. **enable 경계 구현** — PinVi가 production에서 sync enable을 거부하며, 그 조문이 기다리는
   "root-owned final C7 enable boundary"가 Manager에 없다.
3. **구조적 순환** — 켜면 `environment_sha256`이 바뀌어 rebuild가 필요한데, Manager
   `require_rebuildable_mode`는 cache-target 값이 inert여야 rebuild를 허용한다. **현
   lifecycle(rehearsal/rebuildable)에서 enable과 pinned rebuild는 상호배타다.**

셋 중 하나를 골라야 한다 — (a) lifecycle을 옮긴다, (b) Manager가 cache-target 축을
`environment_sha256` 결박에서 분리한다, (c) enable을 실 production 전환 시점까지 미룬다.
(a)는 rebuild 능력을 잃고, (b)는 Manager 계약 변경이며, (c)는 41C를 그때까지 여는 것이다.
`docs/tasks.md`의 41C 줄과 `tasks-acceptance.md` §T-VN-41C가 정본이다.

`GM-17`은 소유자 지시로 **가장 마지막**이다.

그 뒤 순서는 **`T-VN-41F1D-E` → `T-VN-41C`**다(2026-09-06 정정 — 이 줄이 순서를 뒤집어
적고 있었다). `GM-17`은 소유자 지시로 **가장 마지막**이다.
`T-VN-D2-API-AUDIT`(helper의 `api-audit`/`purge` 경로가 한 번도 실행된 적 없음)은 D2 완주와
분리했다 — 고치려면 clone lane의 content digest 계약까지 함께 판단해야 한다.

### 이번에 확인된 운영 사실

- **증거 계약 위반은 스펙이 통과한 뒤에야 드러난다.** `_validate_evidence`가 정확한
  파일명 집합과 action별 키를 요구하는데 그 검증이 스펙 통과 뒤에 돌기 때문이다. 그래서
  결함이 병렬로 안 보이고 배포 스택 실행 한 번에 하나씩 직렬로 나온다 — 열두 번을 그렇게
  썼다. 게이트를 로컬에서 유도해 미리 깨뜨리는 것이 그 비용의 유일한 대안이다.
- **executor 이미지를 같은 `:local` 태그로 다시 빌드하면 핀이 가리키던 이미지가 사라진다.**
  live attestation이 image ID를 exact로 들고 있어 재빌드 순서를 지켜야 한다.
- **`rolinherit=false`라 privilege 확인에 `::regclass`를 쓸 수 없다.** Map 역할 전부가
  NOINHERIT이므로 preflight는 catalog join으로만 판정한다.


## 2026-09-05 — 새 pinset에서 D1 통과, D2는 helper 결함 셋을 고치고 재실행 대기

`af6d7061`(Map `c72456f6` + PinVi `f4401659`)로 rebuild를 마쳤고, attestation을 재발행해
verifier가 PASS했다. D1은 통과했다. D2는 seed에서 죽었고 원인 셋을 전부 고쳐 실 DB에
대고 seed → cleanup → audit을 통과시켰다.

| 항목 | 상태 |
|---|---|
| pinset | **`af6d7061`** = Map `c72456f6` + PinVi `f4401659` |
| rebuild | 성공 (`2acd8e97…`, generation `31622c79…`) |
| host attestation v4 | 재발행 `10ad0f0f…` — **verifier PASS** |
| C7 executor image | `sha256:f760bf6c…` (라벨 `c72456f6`) |
| `T-VN-41F1D-D1` | **통과** — 데이터 비의존 live UI 11/11, 33.2초, 핀 자신의 스펙 바이트로 실행 |
| `T-VN-41F1D-D2` | helper 결함 셋 수정 완료, 실 DB 사이클 통과. **재실행 대기** |
| D2 lane 상태 | `BLOCKED` 해제 — 잔여물 0 실측 후 `clear-blocked`, 증거는 `adjudicated-…`에 보존 |

### 다음 한 작업

**helper 수정을 머지한 뒤 pinset을 한 번 더 돌린다.** 설치 스냅샷 디렉터리 이름이
`E2E_C7_EXPECTED_GIT_COMMIT`에 결박돼 있고 그것이 attestation의 `repository_commit`·
generation의 `map_source_revision`과 exact여야 하므로, Map revision이 바뀌면
rotate-pair → rebuild → attestation 재발행 → 스냅샷 재설치 → executor 이미지 재빌드 →
D1 → D2가 따라온다. 전 과정이 이번에 스크립트로 남았다.

그 뒤 순서는 **`T-VN-41F1D-E` → `T-VN-41C`**다(2026-09-06 정정). `GM-17`(Manager production compose
required-set 완화)은 소유자 지시로 **가장 마지막**이다.

### 이번에 확인된 운영 사실

- **out-of-band DB 패치는 다음 rebuild에 증발한다.** 어제 배포 DB에 손으로 준
  `GRANT SELECT ON public.alembic_version TO ktm_feature_migrator`가 rebuild로 사라졌고,
  그래서 helper의 진짜 결함이 드러났다. DB가 선언된 계약으로 수렴하는 건 좋은 성질이지만
  그런 패치에 기댄 green은 근거가 되지 못한다.
- **rebuild가 `BLOCKED` lane을 가로지르면 `recover`가 구조적으로 불가능하다.**
  `begin-recovery`가 BLOCKED의 execution identity와 현재 identity의 일치를 요구하는데
  rebuild가 여섯 필드를 전부 바꾼다. 이때의 정본 경로는 잔여물을 직접 측정해 0임을 확인한
  뒤 `clear-blocked`로 정리하고 증거를 남기는 것이다.

### 남아 있는 소유자 판정

- `docker/*.py` 여섯 파일이 `mypy --strict` clean인데도 검사 밖이다(n150 실측). 프로덕션
  기동을 막는 `application-schema-final-permit.py`가 그중 하나다. 편입 비용은 0이지만
  `application-schema-fresh-finalize.py`(5건)·`dagster-storage-migrate.py`(4건)는
  정리가 필요해 경계를 어디에 둘지가 판단이다.
- CI의 mypy는 핀이 없다(`mypy>=1.10`). 새 mypy 릴리스가 검사를 조이면 무관한 PR에서
  `lint` job이 붉어질 수 있다 — 기존 세 스텝도 같은 노출을 갖는다.
