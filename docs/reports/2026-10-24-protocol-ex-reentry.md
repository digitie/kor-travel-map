# protocol EX 재진입의 제한 비용 개선

## 문제와 변경

기존 `ops.lock_scoped_feature_write_protocol(true)`는 같은 트랜잭션이 EX를 이미 보유해도
SH 승격 검사·`pg_settings` 조회·GUC 복구를 반복한다. 후속 생성 SQL의 core와 외부 wrapper를
모두 protocol-first로 바꾸면 행마다 이 비용이 중첩될 수 있어 별도417로 먼저 줄인다.
생성 SQL4개 자체는 이번 범위가 아니며 기존 함수의 재진입만 보강한다.

NULL 검사를 통과한 뒤 현재 PID의 정확 두 정수 key `(1369104691,115,objsubid=2)`의
부여된 EX를 확인하면 `pg_advisory_xact_lock`을 재획득하고 즉시 반환한다. **확인만 하고
반환하지 않는다.** `pg_locks`는 session과 xact의 소유를 구별하지 않으므로, session EX만
보유한 caller도 xact 소유를 추가해야 session 잠금을 푼 뒤 현재 TX가 계속 보호된다.

그 밖의 본문·서명·owner·SECURITY DEFINER·search_path·ACL은 보존한다. 다른 PID/다른
key의 EX와 SH 단독 보유는 빠른 경로 조건이 아니다. SH→EX 승격23514·NULL23514·첫
진입 timeout·더 짧은 기존 deadline·rollback/savepoint 계약은 유지한다. 새 EXECUTE grant와
정책 seed는 없다. migration은 원문·서명 SHA를 고정해 다른 정의를 거부하고 원래 CREATE
권한·GUC를 복구한다. 정본 graph·receipt 허용 head·실제 생성한 oracle도417로 갱신한다.

## 실측

고유 PostGIS2CPU·1536MiB·PID256에서 runtime service로 한 SELECT당 EX 재진입1000회를
실행했다. 매 회 TX가 EX를 먼저 보유하고 같은 DB에서416/실제 migration417 정의를 세 번
번갈아 설치해 비교했다. 측정 후417 정의를 복구하고 고유 DB를 제거했다.

| 회차 | 기존416(ms) | migration417(ms) |
| --- | ---: | ---: |
| 1 | 516.73 | 24.95 |
| 2 | 605.59 | 27.91 |
| 3 | 584.55 | 24.79 |

중앙값은584.55→24.95ms다. 이는 **단일 연결·합성 AMD64의 호출 wall time**이며 운영 ARM의
CPU/메모리나 전체 수집 처리량 개선율로 세지 않는다. 사전 원본 실측616/610/593ms와 초기
후보501/504/530→24.6/25.4/24.8ms는 별도 실행이고 위 결과에 합산하지 않는다.

## 검증과 남은 gate

- 실제 PG7+순수4=11 PASS(17.77초). 원문 역치환 SHA·owner/ACL/CREATE 복구, session EX를
  해제한 뒤 다른 backend SH의 정확 key/PID 대기, outer/savepoint 잠금 수명, savepoint만의
  EX 해제 후 다른 PID·key가 빠른 반환으로 오인되지 않음, NULL/SH 승격 실패와 새 TX 복구를
  확인했다. GUC0/17ms 보존과 실제 첫 EX 대기의55P03도 확인했다.
- 정본 oracle 기록1skip(14.08초)은 성공 비교가 아니다. 별도 전체 metadata/oracle4 PASS
  (36.49초), 전체 lint373 PASS/기존6skip(31.75초), 변경 Ruff·strict mypy1 PASS다.
- 초기 로컬 Ruff의 줄 길이/복합 assert/인자 이름 지적은 시험 실행 전 수정했고 제품 PG 실패는
  없었다. 감사 자료 복사 명령의 shell/Python 혼동1회는 제품·원격·컨테이너 변경 전에 실패했으며
  정상 명령으로 복구했다.
- 원본·후보·정확417 측정 및 집중 시험의 고유4개 container ID를 SDK NotFound로, 각 UUID
  잔존0으로 재확인했다. 원로그·측정 원문·script·정리 증거는 로컬 감사 `map417-*`에 보존했다.
- 제품 a6097d569의 J/W 독립2코드리뷰 PASS/열린 P0·P1·P2는0이다. 정확 CI·최신417 실제 UI는 후속 gate다. 선행416 UI18/별도HTTP2 결과를 이
  migration의 실제 UI 성공으로 세지 않는다. 문서와 후속 부모 합집합도 최종 검토한다.

기본 OFF·정책 seed0·운영 변경0이다. 신규 identity·catalog/Geo·지역 이동·일반 collector
배선·전체 writer 폐포와 Weather/Transport 전파는 후속이며 이 제한 최적화로 완료 처리하지 않는다.
