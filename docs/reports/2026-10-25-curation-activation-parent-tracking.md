# 430 activation·parent·tracking 경계 합성 조각

## 현재 범위

기준619a6d4f1의 별도 worktree에서 A/B/C SQL sidecar3개, unit2개, integration1개와 이 보고서만
준비했다. 이 조각만 먼저 배포하거나 활성화하지 않는다. Root의 RC/fresh capture·영속 profile과
전체 결과 복구(D)와 같은 수용 단위다. 공통 migration wrapper는 아직 없고 runtime_privileges/
db.py/models/head-schema와 T의 cancellation service는 변경하지 않았다. 기존429 CI source도 고정했다.

## A/B의 실행 순서

`activate_provider_field_policy`의 첫 P EX 뒤, epoch/Feature/source 선점 전에 private strict
installer를 호출한다. 그 외 기존 activation body는 그대로다.33개 설치·검증과 기존 winner/
pointer/epoch 갱신은 같은 TX이므로 중간 실패 시 함께 rollback한다.

common scope는 실제 provider dataset parent를 SHARE로 잡은 뒤 ops scope를 건드린다. begin은
P 취득 뒤 frozen plan/participant를 새 statement로 다시 읽고 protocol mode 변화를 거부한다.
전체 participant actual parent를 정렬 SHARE로 선취득한 뒤 기존 ops scope·attempt·source/head→
link→Feature 순서를 유지한다. completed/동일TX applying/lease/32participant/manifest 검증 tail은
원문 그대로이며, own whole은 실제 parent UPDATE가 아니라 기존 ops scope UPDATE로 직렬화한다.

## C의 허용 경계

기존 SchemaOwner 소유 INVOKER typed guard3개의 owner/superuser 우회 앞에서 OLD/NEW provider
분류와 현재DB/PID/subid의 held L을 검사한다. job의 OLD/NEW terminal·삭제, membership/event
UPDATE·DELETE는 P EX+L을 요구한다. leaf INSERT는 noP+L을 허용하되 P SH+L은 거부한다.
새 잠금 취득/GUC 변경은 없다. 기존 operation/membership owner·typed authorization tail은 정확히
보존한다. event는 OLD provider→generic job 이동도 기존 typed42501 거부에 포함하도록 좁게 보강했다.
generic import job과 무관한 sync_state에 새 P를 요구하지 않는다.

전용 cancellation3에는 INVOKER prefix checker1개와 BEFORE STATEMENT3개가 있다. import job의
provider 분류는 row 단계의 읽기 검사이며 여기서 잠금을 잡지 않는다. 데이터25관계 statement의
tuple 전 보장과 혼동하지 않는다. pg_locks 관찰은 현재 보유만 확인하며 session/xact의 과거
취득 순서를 attest하지 않는다. 공식 prefix의 xact 잠금과 임의 관리 SET ROLE/수동 advisory
unlock까지의 보장을 구분한다. 새로운 nonce/proof table이나 runtime 권한 확대는 없다.

## Root 합성에 필요한 권한·startup 계약

A가 부르는 SchemaOwner 소유 strict installer에는 StateProcedureOwner dependency EXEC를 정확히
부여해야 한다. C 새 INVOKER trigger 함수는 SchemaOwner 소유·PUBLIC EXEC 회수/runtime 직접
EXEC0로 배선한다. 기존3함수의 owner/INVOKER/ACL은 유지한다. trigger 자동 실행을 runtime 직접
함수 실행 권한으로 넓히지 않는다. 일반 runtime/PUBLIC/CREATE 권한을 추가하지 않는다.

startup은 실제 activation 뒤33개 enabled 정의·argument·함수·행/문장 순서를 확인해야 하며,
기본 bootstrap의 자동 설치0 계약과 구분한다. migration430 wrapper·역할 창·graph/oracle·D의
capture/result domain은 Root 소유이며 이 checkpoint에는 없다.

## 검증과 미완

source-preservation unit13 PASS/0.16초, Ruff·redaction·diff 검사를 확인했다. 첫 A/B5 PASS/0.12초는
초기 checkpoint 기록이며 현재13개에 합산하지 않는다. 최초 inverse 시험의 공백1줄 관찰 오류는
시험에서 정정했고 제품 body 비교의 정확성 기준은 유지했다. 실제 integration은16개 수집만 했다.

paired source에는 같은 DS actual applying 유지 중 ensure/event 진행, actual parent 대기 중
ops scope·Feature NOWAIT, 공식 activation의 partial inventory 거부/DDL·policy·epoch rollback,
typed owner prefix 누락, cancellation3/generic job 보존과 OLD provider event 이동 거부가 있다.
42501은 prefix guard 성공으로 세지 않고 typed authorization의 별도 반례로만 단언한다.

소스 검사는 실제 PG·normal full collector·취소 cleanup·RC/SSI 제거·whole writer closure·영속 결과
복구의 증거가 아니다. 공통 migration/ACL/D가 없어 전체 lint/PR·배포 수용도 미완이다.
Root와 두 source 리뷰 뒤 전체 수용 단위에서만 실제 시험하며, 현재 PG/HTTP·migration 호출·
실제 activation·새 PR 생성은0이다.
