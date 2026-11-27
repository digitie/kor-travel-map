# journal 아카이브 — 2026-10 (k)

[현행 기록](../journal.md)에서 docs/tasks-rule.md §8에 따라 완전한 절을 원문 그대로 분리했다. 읽기 전용 이력이다. 상대 링크만 `docs/archive/` 기준으로 다시 맞췄다.

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
- 최종146 PASS(새PG20/unit10+부모116)·lint377(기존6skip)/Ruff/mypy2/import4 통과, 두 코드리뷰·정확CI·실UI는 미완이다. 총1MiB/manifest8192·협력적30s/입력독점소유 계약과 한계는 [A2 보고서](../reports/2026-10-24-native-scalar-batch.md)에 있다. 기본OFF/seed0/운영0.

## 2026-10-24 — 국가유산 native 적격성 선행 계약(A1, #1390)

- 안정 composite ID의 본체 이름 presence와 저장 typed projection 재정규화·지원 외 불변 진단을 추가했다. eligible은 DB 적용 승인이 아니며 collector/Geo/whole-TX seal·정책은 바꾸지 않는다.
- 격리된 고정SDK public 모델·Map fetcher service fixture 포함98 PASS, native 예산 후속075 합집합116 PASS(실PG 포함), mypy3/import4/Ruff 통과. 정확CI·독립2리뷰는 진행 중이며 PG/실UI/운영 수용으로 세지 않는다. [범위와 실패](../reports/2026-10-24-heritage-native-eligibility.md).
- 기존 EX 진입은 별도 #1389이며 부모 합성 시 양쪽 기록을 보존한다. 기본OFF/seed0/운영0, 내구 artifact/full bundle/실제 collector 배선은 후속이다.

- EX 부모 합성으로 journal225349B가 되어 가장 오래된 2026-10-01 한 절5764B를 [아카이브](journal-2026-10a.md)로 원문 이동했다. 원문 SHA/부모 합집합은 A1 보고서에 기록했다.

## 2026-10-24 — 제한 scalar의 같은 의미 EX 실행 진입

- SH와 같은 source/head→후보→winner→receipt를 기존 protocol EX·curation 전역 fence 아래 수행하는 별도 내부 entry를 추가했다. legacy loader fallback·collector 배선·정책 활성화는 아니다.
- 실제PG/기존native/artifact16 PASS(28.51초): SH/EX 결과 동등·정확 gate 대기·실패/취소 rollback·55P03 복구·완료 replay0DML·mode 대체 거부. 적대리뷰 P2의 legacy장기hint를 소비해 짧은상한을 유지했다. 최종두리뷰·정확CI·최신UI는 후속이다. [범위와 증거](../reports/2026-10-24-scalar-exclusive-semantic-entry.md).
- 선행 #1386·#1387은 각각 두리뷰·정확CI5개·실UI5/18(별도HTTP2) 뒤 main에 머지됐다. 기본OFF/seed0/운영0, 전체수집전환·후속전파는 미완이다.

## 2026-10-24 — 생성 SQL의 protocol-first 진입과 승인 복구(418)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — protocol EX 재진입 비용 개선(417)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 큐레이션 import의 protocol-first 진입

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — field override 진입 보강(416)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 파일 레지스트리의 백업 링크 복구

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — state/lifecycle SQL first-entry 폐포(415)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 통합 전체 CI의 시험 격리 보완(#1379)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 구현 합집합 수용(#1379)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — M05 중복 후보·판정의 protocol-first 보강(414)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 제한 native scalar 비용 실측(#1376)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 구현과 전체 수용 범위 구분

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 SQL 직접 진입 413 실제 검증

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 기존 SQL 직접 호출의 잠금 순서 보강 착수

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 제한 native scalar 실제 DML 중첩

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 제한 scalar winner·정합성 검증(#1373)

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 운영·관리 다중 reader 후속

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 순수 다중 조회의 snapshot 고정

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 범위 커널·기존 writer fence 통합

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 실제 동시 쓰기 구현 착수

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR-114 2단계 재리뷰 Low·main 재기반(#1365 뒤): 브랜치 `feat/adr114-valkey-weather`

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR-114 2단계 리뷰 반영(#1367): 브랜치 `feat/adr114-valkey-weather`

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR-114 2단계: weather 현재·예보·세 구간 요약 Valkey·service REST: 브랜치 `feat/adr114-valkey-weather`

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 T-CWRITE-01: 격리 쓰기 기준선 runner

[완전한 원문](journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 공용 지도 작업면 채택 후보

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 가격 추이 프록시 transport T4 정렬(T-STATE-01-T4): 브랜치 `feat/transport-fuel-price-history-t4`

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — geo 재시도에 ReadError·WriteError 추가: 브랜치 `fix/geo-retry-readerror`

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 shadow 실제 수집 연결: 명시 scope·MCST 이름

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 T-CWRITE-02: 불변 정책과 shadow 후보 기반

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 선행: 같은 transaction fence 재진입 SQL 절감

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 수집 CI 선행 Next 보안 게이트 복구

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 멈춤 진단 오탐 정정: 브랜치 `fix/stall-watchdog-progress`

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 여섯 프로젝트 npm 보안·버전 정합

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-23 — MCST 6시간 상한·멈춤: 브랜치 `fix/mcst-geo-stall`

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-23 — geo 부하 줄이기 0단계(ADR-116, T-GEOLOAD-00): 브랜치 `feat/skip-geocode-unchanged`

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-23 — ADR-114 1단계: transport 현재 상태 Valkey·service REST: 브랜치 `feat/adr114-valkey-transport`

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-23 — ADR-115 실제 동시 쓰기 설계·작업 원장

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-22 — T-LOAD-LOCK-WAIT 2안(ADR-113): 스트리밍 snapshot은 다 받은 뒤 짧게 쓴다: 브랜치 `fix/short-curation-lock-hold`

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-22 — T-LOAD-LOCK-WAIT 1안: 적재가 fence를 길게 기다린다: 브랜치 `fix/load-curation-lock-wait`

[완전한 원문](journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-22 — prod 첫 적재 실패 2건: 브랜치 `fix/highway-evidence-krheritage-address`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-21 — T-RECONCILE-RETRY 하위 단계 2: reconcile sensor 결정 1~7(ADR-112 accepted): 브랜치 `feat/reconcile-retry-alert-close`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-20 — T-RECONCILE-RETRY 하위 단계 1: 완결을 sensor 밖으로(ADR-112 결정 0-1): 브랜치 `feat/finalize-out-of-sensor`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-20 — weather 잔재 정리 2건(T-WX-NOTICE-CLOSE·T-WX-VNEXT-FREEZE): 브랜치 `chore/wx-notice-close-vnext-freeze`

- 소유자 지시("4 진행"). `close_notice_features`(client·repo)와 그 함수만 쓰던 통합 테스트 1건을 지웠다. 공유 헬퍼
  `_persist_notice_lineage_events`·`_reconcile_persisted_notice_scope`는 event-bundle 경로가 계속 쓴다.
- vNext 동결 계약은 재동결하지 않고 rev 300 당시 기록으로 둔다(ADR-105 후속 한 줄, freeze 테스트 docstring 범위 절).

## 2026-10-20 — T-RECONCILE-RETRY 설계안 ADR-112(doc-only): 브랜치 `docs/t-reconcile-retry`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-20 — T-TEST-PLANNER-INDEX 원장 이관(doc-only)

- PR #1336(`e937b38d`, main 반영 완료)이 통합 planner flake 고정(REINDEX in test txn + 25k draft rows + lock_timeout 30s,
  20/20 n150 연속 통과)을 실었으나 `tasks.md`→`tasks-done.md` 이관이 그 PR을 못 탔다. 이번 doc-only PR이 그 이관을
  싣는다 — 코드 변경 없음, acceptance §T-TEST-PLANNER-INDEX는 그대로 둔다.

## 2026-10-19 — production MapLibre worker asset 누락 복구 (PR #1340)

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-19 MOIS 장애 격리 수용

PR1340: 실제 SYN DROP/native retry 기본값으로 FAILURE308.365초(<1440), 복구500행·재수집HTTP0 PASS. REST/prefetch/loader173검사와 namespace4검사 PASS. 운영 전체job/실DB 검증은 아니며 daemonOFF 유지. [범위와 한계](../reports/2026-10-19-mois-network-drill.md).

## 2026-10-19 — MOIS 연결 실패 조기 전파

- 500행 typed 오류 선조회 지연을 재현하고 실행중 task 취소·회수를 보강했다. 관련89회귀 PASS이며 실제 네트워크/native retry 수용은 준비 중이다. [근거](../reports/2026-10-19-mois-network-drill.md).

## 2026-10-19 — T-MAP-02 현재 설치 세대 수용

- T-MAP-02 — timeout 구현523d98cc가 포함된 e937b38d의 API/CS 설치3파일 hash와
  현재 image/CID/StartedAt을 확인했다. 과거 첫 generation UUID는 미회수이며
  현재 설치세대 묶음으로 수용한다. 불필요 재배포·운영 변경0.
  Map API/CS·PinVi API 실제 기존 키 reverse3/3 PASS, PinVi CS 직접 역할은 제외.
  [범위와 증거](../reports/2026-10-19-installed-timeout-acceptance.md).
  전원단절 drill·자동 실행·운영 변경토큰 전량 수용은 별도다.

## 2026-10-18 — Geo 기준점 실제 UI 수용

- 실제 관리자 UI 8/8 PASS: 최초 baseline plan 1/상세 items 0, 동일 토큰 감지에서 같은 기준점 유지.
- 실행 중 세 이미지의 revision label e937b38d와 DB head 409를 관찰했다.
- daemon OFF·현재 run/물리 worker 0·컨테이너 lifecycle 유지. 실제 변경 토큰 replay/resume·자동 실행은 미검증.
- [검증 기록](../reports/2026-10-18-geo-baseline-live.md). 문서만 변경하며 사용자 지시로 CI를 생략한다.

## 2026-10-17 — T-MAP-02 timeout 설명 정합(문서만): 브랜치 docs/track2-http-timeout-contract-20261017

- tasks.md의 낡은 connect 2 s를 실제 기본 4 s로 정정했다. read·write·pool 기본은 geo 10 s·transport 30 s다
  (settings.py, geocoding.geo_http_timeout, dagster/provider_fetchers.transport_http_timeout).
- transport의 요청 재시도는 upstream_retry.DEFAULT_UPSTREAM_ATTEMPTS=2·
  PROVIDER_BOUNDARY_BASE_DELAY_SECONDS=15.0 및 run 예산을 따르며, 이 숫자들은 요청 전체 deadline이 아니다.
- 구현 커밋 523d98ccf36f90aaead9ac33ab353a0839293621(#1325)은 최신 main
  e937b38d176cfeb759daca629395f51c1a6a4d5f(#1336)의 조상이다. 제품 중복 패치는 하지 않았다.
- 실제 배포·장애 drill은 수행하지 않았다. T-MAP-02는 acceptance의 첫 prod 배포 generation 근거를 확인할 때까지 열린다.

## 2026-10-17 — 통합 planner flake 결정화(T-TEST-PLANNER-INDEX): 브랜치 `fix/t-test-planner-index`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — geo 릴리스 재지오코딩 구현 반영 문서(T-GR-07, doc-only): 브랜치 `docs/t-gr-07-geo-release-docs`

- **무엇.** ADR-109 accepted(구현 기록 표·열린 결정 13개 결론), runbook `geo-release-regeocode.md` 신규, 정본 문서의
  "ADR-109 proposed, 미구현" 표식 제거, T-GR-01~06·08 `tasks-done.md` 이관(T-GR-07은 머지가 조건).
- **문서가 코드와 달랐던 자리.** `address-geocoding.md` §5의 센서 위치(`sensors.py` → `geo_release_sensor.py`)·커서(없음 —
  기준선은 계획 표 행)·`kor_travel_geo_client` resource(만들지 않음 — `open_geo_client`)·run_key 다섯째 칸(`provider_dataset_id`
  → `position`)·상수 이름, ADR-108의 "릴리스 센서가 MOIS 이어 달리기를 대신한다"(MOIS는 이제 센서가 내지 않는다).
  geo ADR-069는 그 저장소에서 2026-10-13 accepted(GitHub 원문 확인).

## 2026-10-16 — admin UI geo 릴리스 화면(T-GR-06, ADR-109 결정 8): 브랜치 `feat/t-gr-06-geo-releases-ui`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — records resource replay 모드(T-GR-08, ADR-109 결정 7): 브랜치 `feat/t-gr-08-replay-mode`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — geo 릴리스 센서(T-GR-05, ADR-109 결정 5): 브랜치 `feat/t-gr-05-geo-release-sensor`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — geo 릴리스 계획 표·계획 함수·admin API(T-GR-04, ADR-109 결정 5·8): 브랜치 `feat/t-gr-04-geo-release-plan`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — 적재 경로의 geo 재해석(T-GR-03, ADR-109 결정 4·6): 브랜치 `feat/t-gr-03-stale-stamps`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — `docker-buildx.sh`의 `$!` 경주(고아 tar writer): 브랜치 `fix/buildx-archive-pid-race`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — run-scoped geo 현재 토큰 resource·`geo_applied` 배선(T-GR-02): 브랜치 `feat/t-gr-02-geo-dataset-resource`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-15 — 지오코딩 스탬프 표·geo 데이터셋 토큰(T-GR-01, ADR-109 결정 1~3): 브랜치 `feat/t-gr-01-geocode-stamps`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-15 — geo·transport client connect timeout 분리(T-MAP-02, ADR-110 결정 3): 브랜치 `feat/t-map-02-connect-timeout`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-15 — ADR-110 사실 갱신: geo·weather·transport가 실제로 odroid로 갔다: 브랜치 `docs/adr-110-odroid-facts`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-15 — journal·tasks-done 다음 경계 분리(T-GR-00-LEDGER): 브랜치 `docs/t-gr-00-ledger`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-14 — D2 fixture `Alembic revision confirmation mismatch`: 확인 키를 repin이 API 이미지 head에서 유도: 브랜치 `fix/d2-fixture-alembic-head`

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-14 — chain16 D1 판정이 ANSI 커서 제어 때문에 11/11 통과를 실패로 읽음: 브랜치 `fix/chain16-d1-ansi`

- 증상: 배포(Map 4931f9c0 + PinVi 2fa1c166) 뒤 chain16 F(D1)가 `11 passed (32.2s)`를 냈는데 `!! D1: 목록 11건이 전부 passed가 아니다`로 중단.
- 원인: Playwright line reporter가 진행 줄을 `ESC[1A ESC[2K`로 덮어써 마지막 줄이 `^[[1A^[[2K  11 passed`가 되고, #1318의 판정 `grep -qE "^ *$D1EXPECT passed"`가 줄머리 앵커에서 실패.
- 수정: `scripts/n150/chain16.sh` D1 출력에서 ANSI CSI 시퀀스를 `sed`로 걷어낸 뒤 판정. 판정 규칙(목록 수 == passed, skipped/did not run도 실패)은 그대로.

## 2026-10-14 — chain16 C단계(C7 executor 이미지) 실패 원인 규명 + `file:` 의존성 COPY 게이트: 브랜치 `fix/c7-executor-vendor-tgz` (PR #1320)

[완전한 원문](journal-2026-10g.md)은 크기 상한에 따라 분리했다.
