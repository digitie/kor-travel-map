# T-VN-03 / T-ADM-C6c principal 경계 n150 production live smoke 증거 (2026-07-27)

설계 정본: [t-vn-03-route-gate-cutover-2026-07-19.md](t-vn-03-route-gate-cutover-2026-07-19.md)
§5 검증 순서 · §6 완료 조건. 본 문서는 n150 production 경계 smoke의 **status-only 증거**다
(설계 §5-5: credential 값은 출력·기록하지 않으며 설정 여부와 HTTP status/ops error code만 남긴다).

## 0. 배포 단위 (attribution)

| 요소 | 값 | 근거 |
|---|---|---|
| map-api 컨테이너 | `kor-travel-map-api-latest`, network=**host** | `docker inspect` |
| map rev | **`c8ed6164`** (`org.opencontainers.image.revision`) | image label |
| pinvi 컨테이너 | `pinvi-api-latest`, health=**healthy** | `docker inspect` |
| pinvi rev | **`6a035695`** | image label |
| profile | **production** | 컨테이너 env |
| trusted_cidr | `["127.0.0.1/32","::1/128"]` | 컨테이너 env |

> **문서 모순 해소**: incident-2026-07-27 §3은 복구 결과를 `map=b0c95672`로 기록했으나, 배포 image의
> revision label이 `c8ed6164`임을 실측 확인했다(b0c95672는 c8ed6164의 조상, 둘 다 route gate 포함 —
> 차이는 docs-only). 따라서 정본은 **`map=c8ed6164 / pinvi=6a035695`**이며 resume.md/tasks.md 기록이 맞다.

## 1. 경계 매트릭스 (14/14 PASS — 실행 13건 + C2 양성 T-VN-H19)

호출은 n150 host에서 curl(negatives·token positives), admin-frontend/pinvi 경로는 각 컨테이너에서 실행.
credential 값은 map 컨테이너 env에서 조달해 변수로만 사용, 응답 body·헤더는 기록하지 않음.

### curated (`require_public_api_key`, PUBLIC_KEYED)

| ID | principal | 경로 | 기대 | 실측 | 판정 |
|---|---|---|---|---|---|
| C1 | keyless | `GET /v1/curated-features` | 401 | 401 `UNAUTHORIZED` | PASS |
| C3 | service-token | `GET /v1/curated-features` | 200 | 200 | PASS |
| C4 | admin-bff (actor+secret) | `GET /v1/curated-features` | 200 | 200 | PASS |
| C4n | admin secret, actor 누락 | `GET /v1/curated-features` | 401 | 401 `UNAUTHORIZED` | PASS |

- **C2 (public-key → 200)**: **`T-VN-H19`에서 production runtime 직접 실증 완료**(2026-07-27,
  map=c8ed6164). credential-safe 절차로 admin-BFF `POST /v1/admin/public-api-keys`로 임시 key 발급(평문
  1회, 값 비출력) → `GET /v1/curated-features`에 valid key **200 PASS**(DB lookup+hash compare 양성 분기),
  wrong key **401 PASS**, `POST .../{id}/revoke` **200**, 폐기 후 same key **401 PASS**(revoke lifecycle).
  key 값은 출력·기록하지 않고 key_id·status만 증거로 남김. 이로써 C2 미검증 갭이 닫혔다.

### ops 관측 6경로 (`require_ops_operator`, OPERATOR)

대표 경로 `GET /v1/ops/metrics`(음성)·`GET /v1/ops/health-deep`(양성)에서 검증, 나머지 4경로는
동일 `observability_dependencies` + wiring gate로 일반화.

| ID | principal | 기대 | 실측 | 판정 |
|---|---|---|---|---|
| O1 | keyless | 401 | 401 `OPS_TOKEN_REQUIRED` | PASS |
| O2 | service-token only | 401 | 401 `OPS_TOKEN_REQUIRED` | PASS |
| O3 | cancel-token (scope=ops:read, GET) | 403 | 403 `OPS_SCOPE_FORBIDDEN` | PASS |
| O4 | admin-bff | 200 | 200 | PASS |
| O5 | ops:read token+scope | 200 | 200 | PASS |
| O6 | invalid ops token (scope=ops:read) | 403 | 403 `OPS_TOKEN_INVALID` | PASS |

### MOIS raw debug (production unmount)

| ID | 경로 | 기대 | 실측 | 판정 |
|---|---|---|---|---|
| M1 | `GET /v1/debug/mois-license/{id}` | 404 | 404 `NOT_FOUND` | PASS |

production은 `debug_routes_enabled=false`(assert_production_ready 강제)라 route 자체가 미마운트.

### PinVi observation-read principal (#392)

PinVi 컨테이너에서 자신의 `PINVI_KOR_TRAVEL_MAP_ADMIN_BASE_URL`로 관측 API 호출.

| ID | principal | 경로 | 기대 | 실측 | 판정 |
|---|---|---|---|---|---|
| P-R1 | ops:read token+scope | `GET /v1/ops/consistency/reports` | 200 | 200 | PASS |
| P-R2 | no token | `GET /v1/ops/consistency/reports` | 401 | 401 | PASS |

`require_ops_operator`는 peer-trust를 검사하지 않으므로(코드 보증) ops 관측은 peer와 무관하게
ops:read principal을 필수화한다. P-R1은 PinVi가 ops:read로 관측 read에 도달함을, P-R2는 토큰 없이는
거부됨을 실증 — **#392(관측 caller를 ops:read로 완결)의 런타임 계약 충족**.

## 2. 정적 감사 (배포 전, 워크플로우 `tvn03-c6c-readiness-audit`)

6개 차원 병렬 정적 검증 + 독립 적대 반증. 5/6 PASS(반증 생존), pinvi-manifest만 UNCERTAIN(런타임
manifest는 정적 판독 불가 — 위 live smoke가 해소). 요지:

- `route_policy.py:313` `KNOWN_WIRING_EXCEPTIONS = ()` (예외 0건), `test_route_policy.py:178`이 고정.
- curated 4 → PUBLIC_KEYED(`route_policy.py:176-179`, `app.py:698/714-718`), ops 6 → OPERATOR
  (`app.py:829-840`, `_OPS_OBSERVABILITY_PATHS` 일치), MOIS raw → OPERATOR/`require_admin_frontend`,
  `if settings.debug_routes_enabled:`(`app.py:737-742`) 하에서만 마운트.
- OpenAPI full은 5 scheme 선언, user subset은 PublicApiKey+ServiceToken으로 축소(ops/admin/debug 누출 0).

## 3. §6 완료 조건 대조

- [x] route policy exception 0건·삭제 route 복원 0건·shim 0건 (정적 감사)
- [x] public-keyed 대표 경로 public-key 허용(C2) — **`T-VN-H19`에서 production runtime 직접 실증 완료**
  (2026-07-27, valid key 200·wrong 401·revoke 200·revoked 401)
- [x] public-keyed 대표 경로 keyless 거부(C1) + service/admin 허용(C3/C4)
- [x] ops 6경로 headerless/service-only/cancel-token 거부(O1/O2/O3) + BFF/read-token 허용(O4/O5) + invalid 거부(O6)
- [x] MOIS raw production unmount(M1)
- [x] full/user OpenAPI·생성 TypeScript 계약 일치 (정적 감사)
- [x] PinVi #393 head·Map head가 C6c pair(map c8ed6164 / pinvi 6a035695)에 결박 (rev label 실측)
- [x] n150 production live smoke 실행 13건 통과 + C2 양성(T-VN-H19) = 14/14

→ **T-VN-03 + T-ADM-C6c 전체 완료.** 경계 매트릭스 14/14(13 + C2), PinVi #392 종결, C2 양성 runtime
실증(T-VN-H19)까지 충족. 완료 보류 조건 해소.
