# Feature 생성 SQL의 첫 protocol EX와 요청 승인 복구

> **정오표(2026-10-27).** 아래 "수동 생성·요청 승인 내부 owner 2개에 함수 EXECUTE를 추가"는
> migration에서 실제로 일어나지 않았다. 418은 `SET ROLE ktm_feature_schema_owner` 뒤에
> `GRANT EXECUTE ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean)`을 실행한다. 그 함수의
> owner는 `ktm_feature_state_procedure_owner`이고 schema owner에는 grant option이 없다. PostgreSQL은
> 경고만 내고 아무것도 부여하지 않는다. 그래서 migration만으로 만든 oracle의 ACL
> (`head-schema.sql`)에 두 GRANT가 없다. 두 프로시저는 첫 문장에서 이 gate를 호출하는데도
> 운영이 동작한 것은 post-migration `runtime_privileges` reconcile이 같은 권한을 다시 주기
> 때문이다. 공용 통합 fixture(`tests/integration/conftest.py`)도 migration 뒤 같은 reconcile을
> 돌리므로 시험이 이 누락을 드러내지 못했다. 함수 owner 역할로 GRANT하는 forward migration이
> 2026-10-27 Codex PR 통합 리뷰 PR(WI-3)에서 이것을 바로잡는다.

## 범위와 잠금 순서

migration418은 다음4개 SQL의 첫 BEGIN 직후 기존 protocol EX를 획득한다.

| SQL | 앞당긴 경계 | owner |
| --- | --- | --- |
| create_feature_with_initial_state | source evidence/Feature INSERT 전 | ktm_feature_state_procedure_owner |
| create_provider_feature_with_initial_state | provider identity claim 전 | ktm_feature_state_procedure_owner |
| create_admin_manual_feature_with_initial_state | command/수동 identity claim 전 | ktm_manual_feature_procedure_owner |
| approve_feature_request_with_initial_state | command/request/수동 identity claim 전 | ktm_feature_request_procedure_owner |

core만 바꾸면 세 외부 writer가 이미 identity·행을 선점하므로 함께 보강한다. 다른 직접 core
caller인 M03 manual curation SQL은413에서 이미 첫 EX를 획득한다. DECLARE는 타입 선언뿐이고
잠금/쓰기 initializer가 없다. fresh416의 실제 catalog와 동일한417 oracle의 signature/prosrc
SHA를 확인하고 `pg_get_functiondef` 본문에 진입 한 줄만 추가한다. 원문·owner·ACL·설정은
보존하며 승인 writer의 고유 search_path와 `lock_timeout=5s`를 임의 변경하지 않는다.

protocol 함수를 호출해야 하는 수동 생성·요청 승인 내부 owner2개에만 해당 함수 EXECUTE를
추가하고 정본 runtime ACL에도 반영한다. 새 테이블 DML·PUBLIC·executor 역할 membership을
부여하지 않는다. 원래 feature schema CREATE를 보유한 세 owner의 권한도 유지한다. migration
DDL은 기존 EX 아래 한정 deadline을 사용하고 기존 GUC·CREATE 상태를 복구한다. receipt 허용
head·정본 graph·실제 head oracle을 함께 갱신한다. downgrade는 forward-only로 거부한다.

## 오류 처리와 재시도

요청 승인 repository의 기존 closed mapper는 `55P03`을 내부 오류로 바꿨다. 승인 호출의 catch에
정본 SQLSTATE helper로55P03만 재전파하는 두 줄을 추가해 기존 전역 `503 LOCK_TIMEOUT`과
`Retry-After: 5`로 전달한다. 다른SQLSTATE·submit/reject/read의 mapper·DTO·인증은 유지한다.
실패 transaction과 command claim은 rollback되며 같은 Idempotency-Key로 새 요청을 보낼 수 있다.

이전 함수 비교에서는 정확 선행fc9의 승인 함수 하나를 원문 AST로 읽어 현재 module의 동일
class/globals 위에 올렸다. **동일한 실제418 DB gate**에서 그 함수는500, 수정 함수는503을
반환했고 매번 request/command rollback 뒤 같은 key로200·replay200을 확인했다(별도 실제PG/
ASGI1 PASS/25.97초). 이는 parent417 전체 binary의 end-to-end 재현은 아니며 새 gate와 이전
mapper의 조합을 비교한 증거다. SQLSTATE를 가짜 예외로 대체하지 않았다.

## 검증

- 최종 합집합 집중 **51 PASS/44.12초**: 신규4 SQL의 실제 PG17, 기존 M01 생성/중복·M04
  승인/거절3, 실제PG/ASGI4, 순수5, graph18, 문서 cap/link4다. 앞선22·3·4의 별도 실행을
  이 결과에 중복 합산하지 않는다.
- 실제 native manifest/SH와4개 유효 CALL을 경합시켜 정확 key/PID/blocker에서 EX 대기를
  관측했다. command/request NOWAIT와 동일 core/provider/manual unique identity의 실제
  INSERT/rollback으로 선점0을 확인했다. MVCC count만으로 미커밋 부재를 주장하지 않는다.
  대기 동안 기존 global gate 미선점과 역 EX→다른 backend의 protocol SH 대기도
  확인했다. 역방향은 gate 직접 호출이며 전체 native manifest 실행으로 세지 않는다.
- SH→EX23514·55P03 뒤 전체 rollback·동일 identity/command의 fresh TX 재시도, 원문 역치환
  SHA/고유config/기존4 ACL·CREATE·정확2 owner 추가 권한을 확인했다.
- 원래 auth/session/transaction/handler에서 engine만 owned runtime에 결박한 실제 ASGI는
  인증403/GET200→실제 SH 대기503→상태·claim rollback→같은 key200/replay→다른 key의
  재승인409와 origin/audit1을 확인했다. 입력 If-Match가 없는 계약에 stale412를 만들지 않았다.
  별도 실제PG fault 주입23514/40001/XX000은 기존422/비식별500/500과 복구를 검증한 것이며
  실제 직렬화 실패의 동시성 재현으로 세지 않는다.
- 정본 oracle 기록1skip/14.33초와 별도 metadata/oracle4 PASS/33.28초를 구분한다.
  전체 lint373 PASS/기존6skip(31.11초), 변경 Ruff·strict mypy3·import4계약 PASS다.
  CI 정본 Pydantic2.13.5/core2.46.5를 별도 target에 설치한 all-profile OpenAPI check도
  PASS이며 checked-in spec 변경0이다. 공유 venv는 수정하지 않았다. 로컬2.14.1에서는 기존
  좌표 Decimal의3개 스키마가 drift했지만 같은 환경에서 부모417/후보418의 전체 생성 결과는
  같았다. 이 도구 버전 차 실패도 보존하며 로컬2.14 결과로 정본 spec을 바꾸지 않았다.

초기 시험 오류도 보존한다. J의 기존CREATE=false 가정·aclitem 문자열 codec·승인 config를
다른 루틴과 같다고 가정한3회 실패는 실제 catalog와 대조해 fixture를 고친 것이며 제품을
바꾸지 않았다. root HTTP의 최초4FAIL은 정본 service actor 대신 임의 actor를 쓴 seed 오류,
다음3PASS/1FAIL은 Location을 public URI로 기대한 오류였다. 실제 정본 admin URI로 고쳤다.
원로그와 고유 CID·UUID 정리 증거는 로컬 감사 `map418-*`에 보존한다.

## 남은 수용

root 소유 제품·HTTP·문서는 J/W, J 소유 경계 시험은 root/W 검토를 통과했다.
정확 CI·최신418 실제 UI는 후속 gate다. 선행417의 UI18+별도HTTP2는418
생성/승인 UI 증거가 아니다. 기본 OFF·정책 seed0·운영 변경0이며 mixed binary 전환 전
관련 writer drain이 필요하다. 모든 domain command 선점·catalog/Geo·지역 이동·전체 collector
배선과 의미 지원, 대량/운영 ARM의 CPU·메모리 수용, Weather/Transport 전파는 미완이다.

## 433 이후(2026-10-27)

- GRANT 누락(머리말 정오표)은 433이 함수 소유자(`ktm_feature_state_procedure_owner`)로 다시
  부여해 고친다.
- 433부터 이 네 루틴의 첫 줄은 무조건 P EX가 아니라 regime 진입
  (`ops.lock_single_feature_writer_protocol()`)이다. 정책 활성화 전(epoch=0)에는 P를 잡지 않으므로
  위 "실제 SH 대기 503" 관측은 epoch>0에서만 성립한다(ADR-115 §11.3).
- 상수 ACL을 다시 적던 단위 시험은 지우고, head의 SECURITY DEFINER 호출자가 진입 함수를
  실행할 수 있는지 계산하는 `tests/lint/test_protocol_entry_acl_oracle.py`로 바꿨다.
