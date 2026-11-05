# ADR-119 — 미확정 Feature 명령 조정과 필드 존재를 보존하는 지문

상태: 제안·구현 검증 중 (2026-11-05, Pinvi #668 / Map #1451).

## 배경

Pinvi는 Map Feature 수정/삭제 payload와 If-Match를 먼저 보존하지만 응답을 잃으면 결과가 미확정이다. 조회 시 부재였더라도 나중에 도착한 원래 요청이 실행될 수 있으므로 단순 조회 뒤 소비자 상태를 해제하면 안 된다.

기존 v1 PATCH 지문은 typed body의 미지정 기본값도 직렬화한다. 반면 실제 mutation은 exclude_unset=True이므로 생략한 coord와 명시적 coord:null이 같은 지문인데 다른 변경을 뜻한다. 과거 원장에는 원래 HTTP 필드 존재가 남아 있지 않아 엄밀하게 역산할 수 없다.

## 결정

- 새 operator 전용 조정 POST는 기존 actor/operation/key 잠금 아래 terminal 결과·claim-only pending·부재를 구분한다. 기존 actor namespace를 대신 선택하지 않으며 expected_actor는 인증 context와 비교하는 assertion이다.
- 원래 PATCH/DELETE의 경로 문자열·typed body·If-Match를 같은 canonical builder로 계산한다. 조정 사유와 actor assertion은 원 명령 지문에서 제외한다. alias를 재해석하거나 deprecated operator를 제거해서 지문을 바꾸지 않는다.
- 부재는 기존 원장에 claim+terminal409 DOMAIN_COMMAND_ABANDONED를 한 트랜잭션으로 커밋한다. 그 뒤에만 소비자가 해제할 수 있고, 늦은 원 요청은 mutation 없이 중단 결과 또는 지문 충돌을 받는다.
- PATCH만 fingerprint_version=2를 쓴다. v2는 재귀적으로 생략 필드만 제외하고 명시적 NULL/False/0/빈 배열을 보존한다. 다른 명령은 v1 그대로다. 잠금·UNIQUE identity에 버전을 추가하지 않는다.
- begin/preflight 모두 지문·terminal 판단 전에 버전을 검사한다. 기존 v1 PATCH claim은 LEGACY_FINGERPRINT_UNVERIFIABLE409이며 자동 확정·재실행·해제 근거가 아니다. 기존 원장을 v2로 재표기하지 않는다. 일부 override 이력은 수동 조사 자료이며 원래 HTTP 전체 입력의 일반적 증명으로 간주하지 않는다.
- Pinvi 소비자는 원래 actor를 보존·검증하고, 해제 뒤 새 승인에는 새 attempt 키를 영속화한다. 같은 중단 키를 재사용하지 않는다. 인증/네트워크/계약 오류·claim-only·legacy 불확정은 dispatch를 보존한다.

## 구현과 검증

437 forward migration은 기존 행을 바꾸지 않고 CHECK의 지원 버전을1/2로 늘리며 receipt head를 확장한다. 기존 스키마 소유자·제한된 lock/statement timeout·forward-only 규율을 따른다. 새 테이블·운영 스위치는 만들지 않는다.

실제 PostgreSQL·HTTP/auth로 부재 중단의 커밋 시점, 늦은 원 요청, terminal 회수, pending, actor/input 격리와 응답 유실·양방향 경합을 검사한다. owner Map 계약을 먼저 두 리뷰/CI 후 머지하고 Pinvi를 연결한다. 운영 적용·최종 운영 검증은 Claude Code 담당이다.
