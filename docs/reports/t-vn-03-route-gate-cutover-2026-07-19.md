# T-VN-03 잔여 route gate cutover 설계

## 1. 목표와 기준선

T-VN-03은 ADR-066 D-1의 남은 배선 불일치를 호환 계층 없이 닫는다. 구현 기준선은
`integration/t-vn@a45bc3ac401e5675811f1031a4592991498d899f`이고, PinVi 소비자 기준선은
PR #387이 포함된 `main@60bbdd2a8630681e476226d0a8afe6bda154d8a9`다.

삭제된 legacy command/live ETL route를 복원하거나 alias, legacy header fallback, 이중 인증
기간을 만들지 않는다. 이 변경은 route 경계 변경이므로 DB schema 변경은 우월하지 않다.
인증 정책을 DB에 저장하면 기동 전 검증과 OpenAPI 정본이 분산되므로 migration을 추가하지 않는다.

## 2. 현행 inventory와 목표 정책

| 경로 | 현재 배선 | 목표 배선 | 소비자 영향 |
|---|---|---|---|
| `GET /v1/curated-features` | 무의존 | `require_public_api_key` | 공개 key 또는 기존 trusted admin/service 우회 필요 |
| `GET /v1/curated-features/{curated_feature_id}` | 무의존 | `require_public_api_key` | 위와 같음 |
| `GET /v1/curated-sources` | 무의존 | `require_public_api_key` | 위와 같음 |
| `GET /v1/curated-themes` | 무의존 | `require_public_api_key` | 위와 같음 |
| `GET /v1/ops/metrics` | 무의존 | `require_ops_operator` | Admin BFF 또는 `ops:read` principal |
| `GET /v1/ops/health-deep` | 무의존 | `require_ops_operator` | Admin BFF 또는 `ops:read` principal |
| `GET /v1/ops/consistency/reports` | 무의존 | `require_ops_operator` | PinVi 후속 issue #392 선전환 필수 |
| `GET /v1/ops/consistency/issues` | 무의존 | `require_ops_operator` | PinVi 후속 issue #392 선전환 필수 |
| `GET /v1/ops/system-logs` | 무의존 | `require_ops_operator` | PinVi 후속 issue #392 선전환 필수 |
| `GET /v1/ops/api-call-logs` | 무의존 | `require_ops_operator` | PinVi 후속 issue #392 선전환 필수 |
| `GET /v1/debug/mois-license/{license_id}` | local debug flag만 | debug mount + `require_admin_frontend`; policy는 `operator` | PinVi 직접 caller 없음, raw payload는 operator projection으로 제한 |

`/v1/debug/mois-license/*`는 경로 alias를 만들지 않는다. production은 계속
`debug_routes_enabled=false`를 강제하고 route 자체를 mount하지 않는다. 명시적 `local-dev`에서만
debug mount를 허용하되, mount된 raw projection에도 기존 operator dependency를 적용한다. admin
secret이 없는 local-dev의 `local-dev` actor fallback은 `require_admin_frontend`의 기존 격리 규칙만
재사용하며 새 debug token이나 fail-open 분기를 만들지 않는다.

## 3. 코드·계약 경계

- `app.py`: curated router에 public dependency, 두 ops router에 operator dependency, MOIS debug
  router에 admin/operator dependency를 그룹 단위로 주입한다.
- `route_policy.py`: MOIS raw route를 `operator`로 재분류하고 T-VN-03
  `KNOWN_WIRING_EXCEPTIONS` 10개를 모두 삭제한다. registry가 정책 정본이며 stale exception은 0개다.
- `auth.py`/`settings.py`: 기존 `require_public_api_key`, `require_ops_operator`,
  `require_admin_frontend`와 production fail-closed matrix를 그대로 재사용한다. 새 secret/env는 없다.
- OpenAPI: full 계약의 모든 `RoutePolicy.PUBLIC_KEYED` operation은
  `PublicApiKey OR ServiceToken`, ops 관측과 MOIS raw는 실제 runtime과 같은 `AdminBFF` 또는
  `OpsToken+OpsScope`/`AdminBFF` security를 선언한다. user subset은 route policy에서 공개
  operation을 파생하고 ops/debug route는 포함하지 않는다. curated 4개만 열거하는 수기
  allowlist는 T-VN-57/#784에서 제거한다.
- 생성 TypeScript: full/admin과 user client를 재생성한다. 경로·DTO는 바뀌지 않고 security 계약만
  바뀌므로 호출 API shape 호환 shim은 두지 않는다.
- Admin UI: same-origin proxy가 operator header를 주입하므로 ops 화면 route 문자열은 유지한다.
  MOIS raw 직접 소비자는 현재 없다.

CodeGraph 영향도는 `app.py` 38 symbols/관련 API router test 전반, `require_ops_operator` caller
10개, `require_public_api_key` caller 3개, route wiring gate caller 5개로 확인했다. 따라서 변경은
mount/route-policy/OpenAPI와 해당 인증 회귀에 제한하고 repository/DTO signature는 바꾸지 않는다.

## 4. PinVi와 C6c 동일 배포 단위

PinVi PR #387은 canonical datasets/pipeline에는 `_ops_headers("ops:read")`를 적용했지만, 관측
client 네 메서드는 일반 `_send()`를 사용한다. 이 상태에서 Map gate를 먼저 활성화하면 PinVi API
container는 trusted frontend `/32`가 아니므로 `403`이 된다. PinVi issue
[#392](https://github.com/digitie/pinvi/issues/392)가 네 메서드와 `/v1/ops/metrics`/
`health-deep` direct caller inventory를 소유한다.

배포 가능 조건은 다음 exact pair가 모두 준비된 때뿐이다.

1. PinVi PR #393 구현 head가 모든 실제 관측 read에 `ops:read`만 전송하고 direct caller가 없는 두
   경로는 새 호출을 만들지 않았음을 contract test로 고정한다.
2. Map T-VN-03 head가 route policy exception 0건, full/user OpenAPI와 admin 생성 타입 일치를
   증명한다.
3. docker-manager C6c manifest v4의 PinVi source revision과 Map 공통 source revision이 위 두
   exact head를 가리킨다. PinVi PR #387만 가리키는 pair는 전환 불가다.
4. consumer image를 먼저 준비하고 Map gate image와 같은 maintenance cutover에서 활성화한다.
   실패 시 alias를 열지 않고 v4 rollback의 이전 exact image pair로 되돌린다.

## 5. 검증 순서

동일 전문 리뷰어 1명이 Map+PinVi exact heads를 테스트 전에 교차 검토한다. 승인 전에는
테스트·lint·build를 실행하지 않고 diff, route inventory, OpenAPI 정적 계약, secret/redaction만
검사한다. 승인 뒤 다음을 실행한다.

1. Map route policy/auth/router 단위 회귀와 full API gate.
2. route policy ↔ full OpenAPI ↔ user OpenAPI의 path/method/security 양방향 전수 대조,
   OpenAPI full/user 재생성 및 admin/user TypeScript drift/typecheck.
3. PinVi admin client unit/contract와 API 전체 정적 gate.
4. C6c manifest v4 exact pair capture 뒤 n150 production에서 public key 음성/양성,
   ops BFF/`ops:read` 음성/양성, MOIS production unmounted, live Admin UI를 검증한다.
5. 실제 credential 값은 출력·커밋하지 않고 설정 여부와 응답 status만 증거로 남긴다.

## 6. 완료 조건

- route policy exception 0건, 삭제 route 복원 0건, compatibility shim 0건
- 모든 public-keyed operation의 `PublicApiKey OR ServiceToken` 기계 계약과 runtime 배선 일치,
  대표 경로의 keyless 요청 거부와 public/admin/service 허용 경계 검증
- ops 6경로의 headerless/service-only/cancel-token 거부와 BFF/read-token 허용 검증
- MOIS raw의 production unmount와 local-dev operator gate 검증
- full/user OpenAPI와 생성 TypeScript 소비 계약 일치
- PinVi PR #393 head와 Map head가 C6c manifest v4 exact pair source에 결박
- 단일 리뷰 승인 뒤 로컬 gate와 n150 production live E2E 통과
