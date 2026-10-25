# Snapshot 등록·quota 미호출 조각

기준 ccc4234에서 별도 worktree/branch로 신규 SQL만 준비한다. Root의 저장·dispatcher·lease,
공유 migration/ACL/ORM/startup/dump 파일은 변경하지 않는다. 이 조각은 아직 실행되지 않으며
단독 PR·설치·RC 전환·collector 활성화 대상이 아니다.

## 현재 SQL 계약

P SH를 먼저 얻고 실제 parent SHARE → own whole ops scope UPDATE를 거친다. root/source child/member
UUID에서 dataset/triple/run을 DB가 해석한다. root는 running/STARTED, child는 기존 queued/running과
single membership만 허용한다. 취소·quarantine·비활성 dataset/operation을 거부하며 L을 뒤늦게 취득하지 않는다.
최초 등록은 artifact FK의 자동 tuple 잠금을 고려해 root→child→member KEY SHARE를 quota 전에
선취득한다. duplicate/claim/renew/apply의 tracking tuple 잠금0과 이 최초 등록 예외는 다르다. single membership의 기존 DB topology 계약을 재사용한다.

입력 artifact/context는 각각1MiB/8KiB로 제한한 뒤 JSON header를 검사한다. 기존 artifact6/pins9와
W observation context12키를 그대로 사용한다. provider/dataset/entity, 원 run/generation,
실제 artifact SHA, native digest 및 true EOF/strict/dropped0/source수=tuple항목수를 대조한다.
전체 DTO·fieldset·clock·validation/Geo 의미나 code/SDK 출처 권위를 이 SQL이 증명하지 않는다.
후속 apply가 canonical decode와 고정 code/SDK 및 actual evidence를 재검증해야 한다.

같은 member의 동일 immutable bytes/context/root/domain은 기존 snapshot만 반환하고 gen/fence는
NULL이다. lease 갱신도 quota 접근도 없다. 다른 입력은 부재나 새 snapshot으로 취급하지 않는다.
신규 등록만 global key0 → 양수 dataset key 순서로 명시 quota행을 잠근다. 미설정/소진은53000으로
backpressure하며 default quota를 만들지 않는다. payload+context+결과4KiB+후속4KiB를 예약한다.
quota 양쪽 계수·artifact·gen1/DB nonce/control·작은 reservation은 같은 TX에서 기록한다.
lease5..300초는 caller가 명시한다. commit 응답 유실 뒤 lookup/만료 claim은 Root 후속 API의 책임이다.

## 소유권·미완

최종 wrapper는 SchemaOwner table owner, 기존 CurationCommandOwner SD owner와 필요한
private table SELECT/INSERT/UPDATE·scope helper 의존 EXEC를 배선해야 한다. PUBLIC/runtime raw권한0과
기존 provider executor만 등록 EXEC를 허용하며 삭제권한을 추가하지 않는다. CommandOwner의 기존
provider parent SELECT/UPDATE(PK) 및 tracking SELECT/UPDATE 권한을 재사용한다. 추가 private 의존
EXEC는 `_arm_scoped_feature_write_deadline()`와 `_lock_scoped_feature_write_scope(bigint,jsonb,boolean)`다. 현재 SQL의 role 검사는 session LOGIN의 기존 executor membership을
확인하며, 관리자의 명시 SET ROLE/임의 SQL 전체를 물리 신원으로 증명하지 않는다.

quota 설정·GC 반환은 별도 typed/admin 경계다. active/applying/unsealed GC0, apply/renew/finish의
quota 접근0과 실제 paired lock/rollback 시험이 필요하다. logical quota는 WAL/TOAST/RSS/디스크
물리 상한이 아니다. storage/controller 입력과 후속 결과 권위 연결, 원본 재사용·SDK0 자동 복구,
8target/전체 writer closure와 두 수집기 운영은 아직 미완이다.

첫 checkpoint4780은 SQL source만 보존했다. 다음 통합 source는 실제 service LOGIN 정상등록·중복의
quota 미접근·원 lease/fence 불변, immutable 입력거부, header/queued root 거부, 관리자 quota 장애
주입의 전체 rollback, 실제 L-only leaf root 보유 중 등록의 유한 대기/완료를 준비한다. private raw
관찰은 관리자만 하며 runtime SELECT/INSERT/UPDATE/DELETE를 허용하지 않는다. 관리자 quota 오류
주입은 실제 LOGIN 성공 증명과 구분한다. 최초 문법/형식 점검의 스타일 오류는 고쳤으며,
collect-only 외 실제 PG·SQL실행/공유430 migration·원자 복구 수용은 아직0이다.

첫4780 초안의 operation kind 추가 제한을 기존 schema와 다시 대조했다. 정본 membership scope는
`refresh_only` CHECK/FK를 가지므로 Dagster job kind와 registry operation kind를 혼동한
`feature_load` 조건은 source 단계에서 `refresh`로 정렬했다. 원 초안은 보존하며 실제 PG 실패나
수용 결과로 세지 않는다. 최초 FK의 tracking tuple 잠금0 설명도 root→child→member 선취득으로
정정했다. FK를 삭제하거나 공유 fixture/기존 CHECK를 바꾸지 않았다.

후속 source checkpoint의 정적 확인은 Ruff/format·redaction·diff 통과와 통합15개 collect-only
1.16초다. collection은 fixture/SQL 실행 또는 정상 등록 수용이 아니다. 두 source 리뷰·공유430
배선과 별도 owned PG gate 전 실제 실행하지 않는다.
