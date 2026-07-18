# ADR-066: Route policy fail-closed와 principal actor

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-1·D-2

## 컨텍스트

REST와 WebSocket 인증이 router별 dependency와 설정 기본값에 흩어져 있다. 미분류 route,
비-Docker production profile, raw provider payload, body의 `operator`/`actor` 필드는 각각
인증 누락과 감사 주체 위조를 허용한다. listener를 세 개로 나누는 것은 현재 운영 규모에서
배포 단위와 장애 지점을 늘리지만 이 누락 자체는 막지 못한다.

## 결정

1. 모든 HTTP route와 WebSocket을 `public-unauthenticated`, `public-keyed`, `service`,
   `operator`, `debug`, `metrics` 중 하나로 분류하는 route policy matrix를 코드 정본으로 둔다.
   미분류 route가 있으면 애플리케이션 구성 검사와 CI를 실패시킨다.
2. production profile은 fail-closed다. 필요한 service/operator/admin secret이 없거나 인증 없는
   debug route가 활성화되면 기동하지 않는다. 인증 우회 fallback은 non-production profile에만
   명시적으로 둔다.
3. `/metrics`는 scrape identity 또는 management 경계로 제한한다. raw provider payload는
   operator/debug projection에서만 반환한다. 공개 경로는 별도 read-only DB role을 사용한다.
4. 단일 FastAPI app과 그룹별 dependency를 유지한다. 물리 listener/process 분리는 실측이
   도입 조건을 충족할 때만 별도 결정한다.
5. 모든 write의 감사 actor는 인증 principal에서만 파생한다. request body의 `operator`,
   `actor`, `created_by`, `reviewed_by`는 제거하고 비동기 작업은 제출·승인 principal을 각각
   저장한다.
6. ops 관측 route의 정책 변경은 PinVi service/operator principal 선배포 뒤 같은 cutover에서
   수행한다. 삭제된 legacy command와 live ETL route는 되살리지 않는다.

## 근거

배선 누락을 기계적으로 거부하고 actor 원천을 하나로 만들면 app 수를 늘리지 않고도 실제
위협을 닫는다. 이는 정확성·보안을 최우선으로 하고 1~2인 운영의 단순성을 보존한다.

## 결과

- **긍정**: 신규 route의 인증 누락과 body actor 위조가 CI·기동 단계에서 차단된다.
- **부정**: production 환경변수와 PinVi principal을 준비하지 않으면 의도적으로 기동·호출이
  실패한다.
- **전환/rollback**: route 그룹과 actor schema를 독립 PR로 전개한다. route별 rollback은 이전
  authenticated principal mapping으로 되돌리되 production fail-open과 body actor 신뢰는
  복원하지 않는다. PinVi smoke 실패 시 새 gate 적용 전 상태에서 write fence를 유지한다.

## 기존 결정과의 관계

ADR-005의 "debug/admin 코드 인증 없음" 결정을 supersede한다. ADR-060의 로그인·same-origin
frontend proxy·public API key 구조는 유지하되 production opt-out과 actor 원천은 이 ADR로
개정한다. ADR-064의 ops-live HMAC ticket은 route matrix가 검사하는 WebSocket 인증 구현으로
유지한다.
