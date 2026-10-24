# M05 후보 기록·판정의 protocol-first 보강

## 실제 결함과 수정 범위

M05 후보 기록과 판정의 기존 본문은 Feature 두 행을 UUID 순서로 `FOR UPDATE`한 뒤
provider source/entity/head/link를 `FOR SHARE`했다. scoped kernel은 source/head를 먼저
잠그고 Feature를 잠그므로, 공유 kernel writer와 교차하면 ABBA가 가능했다.

414는 `record_manual_provider_dedup_candidate`, private
`resolve_manual_provider_dedup_case`, 공개 `resolve_manual_provider_dedup_case_v2`의 첫
BEGIN에 protocol EX 한 줄만 넣는다. v2는 subscription/lease를 잡기 전부터 진입한다.
private inner도 원래 owner의 직접 호출에서 순서를 보장하며 재진입은 같은 EX다.
명시 owner/type/SECURITY DEFINER/PLpgSQL 및 413 oracle의 signature·본문 SHA256을 검증하고
원래 정의를 재사용한다. 검증하지 않는 procedure 설정과 기존 ACL은 보존한다.

기존 M05 내부 owner에 protocol EXECUTE만 추가하고 정본 ACL reconcile에 반영한다.
새 공개 routine·runtime 테이블 권한·정책 seed·자동 shared 수집 연결은 없다. 임시 CREATE,
짧은 caller 상한을 보존하는 lock/statement timeout과 최종 schema owner를 원복한다.
receipt의 과거 허용 집합에 414만 추가한다. 배포는 기존 worker drain과 mixed binary 점검 뒤다.
EX를 먼저 잡는 것은 배타 fallback 정렬이며 전체 동시 쓰기나 정책 활성화 완료가 아니다.
지원하지 않는 active-policy mutation을 허용하는 변경은 하지 않는다.

## 재현과 검증

UUID/name/label을 검증하는 소유 PostGIS 한 개씩만 사용했다. memory 1536MiB·memory+swap
1536MiB(추가 swap0)·2CPU·PID256이다. 공유/운영 DB, 외부 DSN, provider HTTP는 사용하지 않았다.
실제 application bootstrap·정본 ACL reconcile·fresh runtime 로그인으로 검사했다.

컨트롤러 C가 Feature를 잠가 실행 순서만 고정한다. A는 정상 protocol SH 뒤 실제 전체
`begin_scoped_feature_write`를 호출하고 B는 유효한 실제 M05 CALL을 호출한다. 기존 본문에서는
B가 먼저 Feature 대기열에 선 뒤 A가 실제 head를 잡고 같은 Feature를 기다리게 한다.
C를 해제하면 B의 Feature→head와 A의 head→Feature가 충돌한다. 제품 함수에 pause hook이나
복제 SQL을 삽입하지 않았다. 진단만 결정적으로 하기 위해 이 소유 container의 deadlock
검출 주기를 100ms로 낮췄으며 제품 begin의 1초 lock timeout과 모든 ACL은 그대로다.

- 기존 413에서 실제 `40P01`을 검출했다. 재현 기대값 통과 1건/13.98초이며 정상 쓰기 성공을
  뜻하지 않는다. 앞선 관측 실패 2회는 soft queue PID 차이와 1초 lock timeout 선발화였고
  별도 로그로 남겼다.
- 수정 뒤 B는 protocol EX를 먼저 기다려 Feature를 선점하지 않는다. C 해제 후 A의 실제
  begin/finish/commit과 B의 후보 `created`가 완료됐다(첫 검사 1 passed/13.93초).
- 이후 실제 공개 v2 판정 `kept` 경합, 3개 owner/원 ACL·첫 BEGIN, 3개 SH→EX 승격의 validation
  앞 거부와 순수 본문 보존 검사를 함께 실행해 **12 passed/14.23초**였다.
- 관측은 `pg_blocking_pids`의 실제 차단 PID로 확인하며 단순히 task가 오래 실행된 것을
  잠금 증거로 세지 않는다. 컨트롤러는 인위적인 순서 경계이므로 운영 처리량 증거가 아니다.

원본 로그는 `audit-reports/2026-10-24-operations/map414-{old-deadlock-repro-3,fixed-pg-1,fixed-pg-2}.log`
에 보존했다. codegraph는 record 경로9개, resolve 경로2개 영향 심볼을 보고했고 정확 413
소스의 직접 SQL·Python 호출도 함께 대조했다. 서명/API/DTO/화면 계약은 바꾸지 않는다.

공식 실제 head oracle 재기록은 의도된 skip 1건이며, 재비교·metadata는 2 passed/22.93초다.
전체 lint는 373 passed/기존 skip6/29.56초, 변경 Ruff와 migration strict mypy도 통과했다.
최종 두 독립 리뷰·정확 CI와 최종 수용은 별도 gate다.
운영 배포/정책 활성화0이며 전체 writer 전환·Geo·대량/운영 ARM 성능·Weather/Transport 전파는
이 변경의 완료로 세지 않는다.
