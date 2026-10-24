# ADR115 기존 primary 장소의 제한 native scalar refresh

## 범위

411 커널과 412 scalar 정책 뒤의 실험용 내부 진입점이다. 기존 Feature와 기존 primary
membership의 이름·전화만 지원한다. 자동 수집에는 연결하지 않는다. dataset 전체 범위만
허용하며 지역 coverage·신규 identity/link·Geo·retire/merge·파일은 지원하지 않는다.
여러 entity/provider→한 Feature는 정책에 따라 지원하지만 한 entity→여러 Feature는 거부한다.
운영 정책 seed·활성화·배포는 0건이다. 전체 T-CWRITE-01~09 완료가 아니다.

## transaction과 재시도

원천 fetch와 sealed manifest 준비는 apply 밖에서 완료한다. 적용 artifact는 typed bundle,
정본 Feature UUID, dataset, 명시 policy revision의 결정적 SHA256으로 claim에 묶는다.
입력은 1 MiB 이하이며 presence 집합은 정렬한다. manifest owner/digest와 artifact가 다르면
source DML 전에 거부한다. protocol 공유→policy epoch 공유→begin의 정렬 잠금→target
preflight→기존 source entity/record/head upsert→scoped 후보→winner→finish 순서다.
모두 caller의 같은 READ COMMITTED transaction이며 helper는 commit하지 않는다.

실패·취소는 transaction 전체를 rollback한다. 같은 공유 transaction에서 legacy 경로로
승격하지 않는다. 재계획은 새 transaction/attempt에서 하고 검증한 원천 artifact를 재사용한다.
완료된 동일 attempt의 재호출은 source DML 없이 저장 receipt를 반환한다. 오래된 artifact는
실제 canonical current head를 확인해 현재 후보와 winner를 되돌리지 않는다.

기존 source entity upsert의 first_seen_at=LEAST는 immutable 생성 시각 guard와 충돌해
과거 artifact에서 23514를 발생시켰다. first_seen_at 갱신만 제거하고 last_seen_at의
GREATEST와 immutable raw 이력·head의 시간 순서 조건은 유지했다. codegraph 영향도는
13개 심볼이며 기존 lineage 회귀도 함께 실행했다.

## 실제 검증

첫 owned full-bootstrap PG 검사에서 독립 dataset 두 세션의 실제 source DML 후 barrier와
중간 실패 rollback→동일 artifact 복구→완료 receipt 재호출 무 DML은 통과했다.
과거 artifact 1건은 위 first_seen 오류로 실패했고 수정 후 제한 native 3개+기존 lineage
1개가 26.39초에 모두 통과했다. 단순 fetch 중첩이 아니라 두 별도 backend PID가 source
DML을 완료한 뒤 어느 쪽도 commit하기 전에 barrier에 함께 도착해야 통과한다.
이 synthetic 소규모 결과는 운영 ARM CPU/RAM 개선율이나 전체 provider 경로 검증이 아니다.

정확한 최종 후보의 두 적대 리뷰·CI·실제 HTTP/UI·대량/장애 주입·모든 writer 전환은 남아 있다.
412를 먼저 수용한 뒤 main에 재기준하여 검증한다. Weather·Transport 전파는 Map 수용 뒤다.
