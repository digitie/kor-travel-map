# Snapshot 등록·quota 미호출 조각

기준 ccc4234에서 별도 worktree/branch로 신규 SQL만 준비한다. Root의 저장·dispatcher·lease,
공유 migration/ACL/ORM/startup/dump 파일은 변경하지 않는다. 이 조각은 아직 실행되지 않으며
단독 PR·설치·RC 전환·collector 활성화 대상이 아니다.

## 현재 SQL 계약

P SH를 먼저 얻고 실제 parent SHARE → own whole ops scope UPDATE를 거친다. root/source child/member
UUID에서 dataset/triple/run을 DB가 해석한다. root는 running/STARTED, child는 기존 queued/running과
single membership만 허용한다. 취소·quarantine·비활성 dataset/operation을 거부하며 tracking 행을
새로 잠그거나 L을 뒤늦게 취득하지 않는다. single membership의 기존 DB topology 계약을 재사용한다.

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

최종 wrapper는 SchemaOwner table/SD owner와 PUBLIC/runtime raw권한0, 기존 provider executor만
등록 EXEC를 정확히 배선해야 한다. 현재 SQL의 role 검사는 session LOGIN의 기존 executor membership을
확인하며, 관리자의 명시 SET ROLE/임의 SQL 전체를 물리 신원으로 증명하지 않는다.

quota 설정·GC 반환은 별도 typed/admin 경계다. active/applying/unsealed GC0, apply/renew/finish의
quota 접근0과 실제 paired lock/rollback 시험이 필요하다. logical quota는 WAL/TOAST/RSS/디스크
물리 상한이 아니다. storage/controller 입력과 후속 결과 권위 연결, 원본 재사용·SDK0 자동 복구,
8target/전체 writer closure와 두 수집기 운영은 아직 미완이다.

첫 checkpoint는 SQL source 보존만이다. 관련 integration source와 독립 두 리뷰·실제 owned PG,
공유430 migration 합성은 다음 단계이며 현재 실제 PG 실행0이다.
