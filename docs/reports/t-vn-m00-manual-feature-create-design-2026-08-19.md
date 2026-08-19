# T-VN-M00 — 수동 Feature 생성 2차 설계

- 상태: draft — 전문 적대 검토 2명 재심 대기
- 기준: `main` `025be0e638ba`
- 관련: ADR-066, ADR-068, ADR-070, ADR-074, ADR-075, ADR-083, ADR-086,
  ADR-090, ADR-092, ADR-093(proposed)
- 작성일: 2026-08-19

## 1. 결론

T-VN-M01은 새 API를 처음 만드는 작업이 아니다. 현행 `POST /v1/admin/features`와
`feature.create_feature_with_initial_state` 결선은 이미 존재한다. M01은 다음 네 경계를 한 번에
교정하는 clean cutover다.

1. 요청 속성에서 canonical identity를 만들지 않고 UUIDv7을 서버가 발급한다.
2. 이름과 좌표의 exact 중복은 별도 불변 claim의 DB unique 제약으로 막는다.
3. 인증된 admin BFF 전용 경계에서 생성된 신규 행에만 `manual_admin` origin을 기록한다.
4. claim, origin, core, initial state, subtype, field override, domain-command 결과를 한 트랜잭션으로
   원자화한다.

`manual_pinvi`와 `manual_curation`은 M01의 값 도메인에 넣지 않는다. 각 값을 발급할 별도 route 또는
분리된 권한 scope가 실제로 배포되는 M04와 M03에서 제약을 확장한다. provider가 같은 실체를 나중에
발행하는 경우도 M01에서 자동 병합하지 않고 M05의 검토 대상으로 남긴다.

두 검토자가 같은 commit에 P0~P3 잔여 없이 `GO`를 선언하기 전에는 M01 코드를 작성하지 않는다.

## 2. 현행 사실과 1차 초안의 전제 수정

### 2.1 이미 존재하는 생성 경로

현행 코드는 다음 경로를 이미 실행한다.

1. `AdminFeatureCreateRequest`가 body의 `feature_id`, `idempotency_key`, 3축 상태까지 받는다.
2. `_create_feature_id()`가 caller key 또는 `name:lon,lat`로 `user_request` legacy ID를 만든다.
3. `admin.feature.create` domain command를 claim한다.
4. `create_admin_feature_with_field_overrides()`가 generic create procedure, subtype writer, field override를
   같은 트랜잭션에서 실행한다.
5. 외부 응답의 `feature_id`는 이미 canonical UUID 값이다.

따라서 M01의 작업명은 “admin Feature 생성 API 신규 결선”이 아니라 “기존 생성 API의 identity,
provenance, duplicate, auth 계약 교정”으로 읽는다. M01 ADR도 새 `source_type` 추가가 아니라 이
clean cutover와 legacy alias 규칙을 결정한다.

### 2.2 PinVi와 admin BFF는 현재 구분되지 않는다

PinVi `origin/main`의 승인 코드는 같은 `/v1/admin/features`를 호출하며, Map admin BFF와 같은 종류의
proxy 인증 자격 및 caller가 지정하는 actor header를 보낸다. 이 신호만으로 `manual_admin`과
`manual_pinvi`를 구분하면 안 된다. PinVi client가 기대하는 옛 `data.request` 응답과 현행 Map 응답도
이미 갈라져 있다.

M01 cutover 전에는 다음을 모두 만족해야 한다.

- admin UI BFF 전용 proxy credential을 새로 발급하고 Map은 그 credential만 수용한다.
- PinVi runtime에서 admin proxy credential과 직접 create 호출을 제거한다.
- 폐기한 공유 credential로 호출하면 `401` 또는 `403`이고 Feature, claim, origin, command 결과가
  하나도 생기지 않는 통합 증거를 남긴다.
- `manual_admin`은 route 상수로 정한다. actor header나 body 값으로 origin을 선택하지 않는다.
- principal은 전용 credential을 가진 trusted BFF가 인증해 전달한 actor와 domain-command ledger의
  actor가 일치할 때만 저장한다.

M04 전까지 PinVi 신규 장소 승인은 기능상 닫힌다. 서비스 전 단계에서는 거짓 immutable origin을
남기는 것보다 이 fail-close가 우선한다.

## 3. 범위와 단계 소유권

| 단계 | 이 단계가 소유하는 것 | 이 단계에 넣지 않는 것 |
|---|---|---|
| M01 | 기존 admin create clean cutover, UUID 발급, exact claim, `manual_admin`, 전용 BFF 인증, 고정 initial state | PinVi·curation origin, fuzzy dedup |
| M02 | origin/claim read model, patch·state·backup·restore·purge 불변 검증, 복원 epoch 연계 | 도달 불가능한 origin 값 사전 등록 |
| M03 | T-VN-40 command 경계에서 동시 Feature+curation 생성, 그때 `manual_curation` 도메인 추가 | 일반 admin route에서 curation 추론 |
| M04 | PinVi 요청 접수와 Map admin 승인 경계, 그때 `manual_pinvi` 도메인 추가 | PinVi의 `/v1/admin/features` 직접 호출 |
| M05 | provider/manual fuzzy 후보 생성과 운영자 판정 | 자동 병합, identity 자동 교체 |

T-VN-41 cache-target streaming과 직접 결합하지 않는다. 다만 M02의 backup/restore 검증은 동일한
restore epoch 규칙을 재사용하고 새 epoch 정본을 만들지 않는다.

## 4. Identity와 멱등성

### 4.1 canonical identity

- canonical Feature ID는 ADR-068·083의 서버 발급 UUIDv7이다.
- `name`, `category`, 주소, 좌표, origin은 canonical ID의 재료가 아니다.
- 이름·분류·좌표를 나중에 수정해도 UUID와 생성 claim은 변하지 않는다.
- exact replay는 `(actor, operation='admin.feature.create', Idempotency-Key)` ledger가 같은 UUID,
  response status, body, `ETag`, `Location`을 재생한다.
- 같은 key에 다른 body를 보내면 `409 IDEMPOTENCY_KEY_REUSED`다.

현행 text PK가 남아 있는 동안에만 UUIDv7을 먼저 만든 뒤 다음 opaque natural key로 legacy alias를
만든다.

```text
source_type = user_request
source_natural_key = manual::<canonical-feature-uuid>
```

이 legacy alias는 내부 이행 장치일 뿐 외부 응답이나 의미 기반 identity가 아니다. T-VN-39 physical
re-key 뒤에도 alias table의 조회 별칭으로만 보존한다.

### 4.2 exact duplicate와 semantic duplicate를 분리한다

M01 admin UI는 좌표를 필수로 받는다. DB procedure가 caller가 만든 key를 받지 않고 다음 값을
직접 계산한다.

```text
kind_key = kind
name_key = lower(normalize(btrim(name), NFC))
lon_e6 = round(lon * 1_000_000)
lat_e6 = round(lat * 1_000_000)
```

`(kind_key, name_key, lon_e6, lat_e6)`는 exact identity reservation이다. category는 identity에
넣지 않는다. 같은 장소의 분류 수정이 새 실체를 만들면 안 되기 때문이다.

- 서로 다른 Idempotency-Key 두 건이 exact key가 같으면 DB unique 제약이 하나만 허용한다.
- loser는 기존 canonical UUID를 포함한 `409 MANUAL_FEATURE_EXACT_DUPLICATE`를 받는다.
- 이름 표기나 좌표가 이 exact 규칙 밖에서 다른 유사 실체는 M05 후보일 뿐 M01이 자동 차단하거나
  병합하지 않는다.
- provider 경로는 이 claim을 발급하지 않는다. provider/manual 중복은 M05에서 사람이 판정한다.

READ COMMITTED check-then-act 프리체크는 정합성 장치로 사용하지 않는다. unique insert가 경합의
단일 승자를 정하고, claim과 Feature insert가 같은 트랜잭션이므로 loser의 core·subtype·감사 행은
전부 rollback된다. 이 경계에는 SERIALIZABLE과 advisory lock을 중복 적용하지 않는다.

## 5. 저장 모델

origin과 duplicate claim은 의미와 과거 이관 규칙이 다르므로 한 테이블에 섞지 않는다.

### 5.1 `feature.manual_feature_identity_claims`

이 관계는 exact 중복 예약이며 origin이 아니다.

| 열 | 계약 |
|---|---|
| `feature_id uuid` | PK. 현행에서는 `features.feature_uuid`, T-VN-39 뒤에는 `features.feature_id` 값 |
| `feature_kind text` | M01은 `place`, `event`만 허용 |
| `name_key text` | DB가 계산한 NFC·trim·lower 생성 시점 snapshot |
| `lon_e6 integer`, `lat_e6 integer` | DB가 계산한 대한민국 범위 6자리 정수 좌표 |
| `claimed_by_command_id bigint` | 신규 생성은 NOT NULL, legacy 예약은 NULL 가능 |
| `claimed_at timestamptz` | DB 시각 |

필수 제약은 다음과 같다.

- PK `pk_manual_feature_identity_claims(feature_id)`
- unique `uq_manual_feature_identity_claims_exact(feature_kind, name_key, lon_e6, lat_e6)`
- partial unique `uq_manual_feature_identity_claims_command(claimed_by_command_id) WHERE ... IS NOT NULL`
- kind, canonical name, 좌표 범위 CHECK
- UPDATE, DELETE, TRUNCATE를 거부하는 append-only trigger

Feature FK를 의도적으로 두지 않는다. Feature purge 뒤에도 같은 수동 실체를 조용히 다시 발급하지
않고 reservation을 보존해야 하며, T-VN-39 text→UUID 전환 때 이 테이블을 재작성하지 않기 위함이다.

### 5.2 `feature.feature_creation_origins`

이 관계는 검증된 생성 provenance만 보존한다.

| 열 | 계약 |
|---|---|
| `feature_id uuid` | PK이자 identity claim FK |
| `origin_kind text` | M01 DDL에서는 오직 `manual_admin` |
| `creation_command_id bigint` | unique, 생성 command causation |
| `created_by_principal text` | domain-command actor에서 DB가 복사 |
| `created_at timestamptz` | DB 시각 |
| `invoker_role text`, `procedure_definer text` | 실행 경계 감사 |

`feature_id`는 claim에 `ON DELETE RESTRICT` FK를 둔다. `ops.domain_commands`에는 FK를 두지 않고,
procedure가 command 존재·operation·actor를 검증한 뒤 값을 복사한다. 이는 Feature purge 뒤에도 FK
cascade 없이 감사 evidence를 보존하는 `feature_state_transitions` 패턴과 같다.

origin relation도 UPDATE, DELETE, TRUNCATE를 모두 거부한다. M03/M04는 각 인증 경계와 writer가 실제로
생기는 migration에서만 CHECK를 각각 확장한다. API body, actor 문자열, reason prefix로 값을 바꾸는
경로는 만들지 않는다.

### 5.3 과거 행 이관

과거 origin은 추정하지 않는다.

1. 첫 transition이 `initial`, reason이 `admin_feature_create`, causation이
   `domain-command:<id>`이고 command operation이 `admin.feature.create`인 행만 legacy manual claim
   후보로 찾는다.
2. 후보의 생성 시점 이름·좌표를 복구해 UUID와 함께 claim을 backfill한다. 생성 시점 값을 복구할
   수 없거나 exact key가 충돌하면 migration을 중단하고 운영자 판정을 요구한다.
3. 이 행에는 origin row를 만들지 않는다. 과거 PinVi와 admin BFF가 같은 경계였으므로
   `creation_origin=null`이 유일하게 정직한 값이다.
4. backfill은 새 claim 관계에만 INSERT한다. `features`를 UPDATE하지 않으므로 `row_revision`,
   `updated_at`, field lineage trigger를 건드리지 않는다.

## 6. DB write 경계와 원자성

generic `feature.create_feature_with_initial_state`의 signature와 일반 `initial` 의미는 바꾸지 않는다.
대신 M01 전용 SECURITY DEFINER procedure를 추가한다.

```text
feature.create_admin_manual_feature_with_initial_state(
    p_feature_payload jsonb,
    p_domain_command_id bigint,
    OUT o_inserted boolean,
    OUT o_feature_id text,       -- current bridge only
    OUT o_feature_uuid uuid,
    OUT o_row_revision bigint
)
```

procedure는 schema-qualified relation만 사용하고 `search_path=pg_catalog`로 고정한다.

1. `ops.domain_commands`에서 command를 잠그고 operation이 `admin.feature.create`이며 terminal result가
   아직 없음을 확인한다. principal은 이 row의 actor만 사용한다.
2. payload의 UUIDv7, kind, name, 좌표를 검증하고 exact key를 계산한다.
3. identity claim을 먼저 INSERT한다. unique 경합 loser는 typed duplicate 오류가 된다.
4. generic procedure를 고정 tuple `active/published/valid`와 `transition_kind=initial`,
   `reason_code=admin_feature_create`, ledger actor, `domain-command:<id>`로 호출한다.
5. origin을 `manual_admin`으로 INSERT한다.
6. Python repository가 subtype과 field override를 쓰고 domain-command terminal 결과를 같은 외부
   트랜잭션에서 완료한다.

어느 단계든 실패하면 claim부터 terminal result까지 전부 rollback한다. `published`를 유지하는 이유는
admin 직접 생성의 현행 의미를 보존하고 PinVi 회귀를 state default로 숨기지 않기 위해서다. PinVi
요청은 M04 queue에서 pending/approval을 소유하며 M01 initial state를 caller가 고르지 않는다.

origin 관련 규칙은 “origin이 있으면 이 전용 initial create에서 왔다” 방향으로 강제한다.
“모든 `transition_kind=initial`은 origin 필수”라는 역규칙을 generic procedure에 추가하지 않는다.
따라서 provider·fixture의 기존 initial 호출 네 곳은 origin 없이 계속 유효하다.

## 7. HTTP 계약

### 7.1 요청

`POST /v1/admin/features`는 전용 admin BFF 인증과 UUID `Idempotency-Key` header가 필수다.

body에는 `kind`, `name`, `category`, `coord`, `marker_icon`, `marker_color`, `reason`과 현행 typed
address, URL, detail 필드만 둔다. 다음 caller-owned 필드는 clean cutover에서 제거한다.

- `feature_id`
- body `idempotency_key`
- `operator`
- `lifecycle_state`, `publication_state`, `quality_state`

`coord`는 M01의 `place/event` 생성에서 필수이며 대한민국 범위 검증을 그대로 적용한다.

### 7.2 성공과 재생

- 신규 성공: `201 Created`
- header: canonical detail URL의 `Location`, row revision `ETag`
- body: 현행 field-override command 결과에 canonical UUID와 `creation_origin=manual_admin`을 명시
- exact replay: 최초와 같은 `201`, body, `ETag`, `Location`; 새 DB row 없음

### 7.3 실패

| status | code | 조건 |
|---|---|---|
| 401/403 | 기존 인증 오류 | 전용 admin BFF 경계 실패 |
| 409 | `IDEMPOTENCY_KEY_REUSED` | 같은 ledger key, 다른 body |
| 409 | `MANUAL_FEATURE_EXACT_DUPLICATE` | 다른 command가 exact claim을 선점; 기존 UUID 포함 |
| 409 | `FEATURE_IDENTITY_CONFLICT` | UUID/legacy bridge의 불가능한 충돌 |
| 422 | `VALIDATION_ERROR` | kind, category, 좌표, subtype, field registry 입력 오류 |
| 500 | generic internal error | 알려지지 않은 DB 제약 또는 invariant 위반; 로그에는 constraint만 남기고 응답은 비밀 비노출 |

## 8. DB 오류 분류의 fail-close

새 CHECK를 기존 `PATCH /state` allow-list에 억지로 넣지 않는다. core `features`에도 origin CHECK를
추가하지 않으므로 state procedure 의미와 기존 fixture를 건드리지 않는다.

create 전용 mapper에는 이름 기반 두 집합을 둔다.

- conflict: exact unique, core identity unique, origin/claim 중복
- validation: payload, kind, canonical name, 좌표 범위, subtype·field 제약

통합 테스트는 실제 HTTP status와 typed code를 단언한다. 또한 target/current DDL에서 M01 wrapper가
도달 가능한 모든 CHECK·UNIQUE 제약명을 추출해 정확히 한 집합에만 속하는지 역방향으로 검사한다.
새 제약이 분류 없이 추가되면 CI가 실패한다. 기존 state mapper에도 실제로 존재하지 않았던
“모든 `features` CHECK가 conflict 또는 validation 중 하나에 있다” 역방향 테스트를 추가하고,
PATCH state의 알려진 제약은 `409/422`이지 `500`이 아님을 HTTP 수준에서 고정한다.

## 9. 인증·권한

- admin UI BFF만 새 proxy credential을 가진다. 인증 자격과 trusted proxy 조건을 모두 만족해야 한다.
- origin은 route/writer가 hard-code하고 principal은 ledger actor에서 읽는다.
- runtime login은 두 테이블에 SELECT만 가진다. INSERT/UPDATE/DELETE/TRUNCATE는 모두 없다.
- runtime login은 새 procedure EXECUTE만 가진다. table INSERT는 전용 NOLOGIN procedure owner만 가진다.
- procedure owner, owner 전환, PUBLIC revoke, runtime grant, sequence 권한, startup privilege preflight,
  `runtime_privileges.py`의 닫힌 inventory를 같은 migration/PR에서 갱신한다.
- migration role 외의 raw backfill과 origin 교정 명령은 제공하지 않는다.

## 10. migration, freeze, backout

### 10.1 번호와 순서

T-VN-40C가 `0224`를 예약했다. M01은 지금 번호를 선점하지 않고, main rebase 시 T-VN-41S와 순서를
조정해 `0225+` 실제 head를 배정한다.

1. read-only preflight: legacy 후보 수, 좌표 결손, exact 충돌 그룹, PinVi 직접 credential/호출 잔존
2. 테이블·제약·append-only trigger·owner·procedure·ACL 생성
3. legacy claim INSERT 및 수량/root 검증; origin backfill은 0건임을 단언
4. admin API와 UI generated type clean cutover
5. 전용 BFF credential 활성화, 폐기 shared credential 거부 smoke

### 10.2 vNext freeze

구현 PR은 다음을 한 묶음으로 갱신한다.

- `contracts/vnext/target-schema-v1.sql`
- `target-schema-fingerprints-v1.json`의 현행 **7개** catalog 축
  (`columns`, `constraints`, `functions`, `indexes`, `relations`, `sequence`, `triggers`)
- `violation-fixtures-v1.sql`
- `expected-rejections-v1.json`
- `tests/unit/test_vnext_contract_artifacts.py`의 artifact SHA-256 상수
- admin OpenAPI export와 frontend generated types

1차 초안이 말한 “4개 fingerprint”도 현행 계약과 다르므로 7개를 재실측한다. 계약 SQL로 만든 빈
DB와 실제 migration DB의 catalog를 별도로 대조해 한쪽만 green인 drift를 허용하지 않는다.

### 10.3 backout

- 첫 성공 create 전: route를 닫고 migration downgrade로 관계와 procedure를 제거할 수 있다.
- 첫 origin/claim 생성 후: forward-only다. route를 닫고 관계를 읽기 전용으로 보존한 채 후속
  migration으로 고친다. origin/claim을 drop하거나 값을 다시 쓰는 rollback은 금지한다.
- credential rollback이 폐기한 shared PinVi credential을 되살리면 안 된다.
- backup/restore는 두 관계와 command ledger를 같은 restore epoch에서 복원한다. 복원 후 origin,
  claim exact key, principal, command causation의 byte-equivalent 불변을 검사한다.

## 11. 구현 검증 행렬

| 축 | 필수 증거 |
|---|---|
| 인증 | admin BFF 새 credential 성공; 폐기 credential·PinVi 직접 호출 401/403 및 DB zero-write |
| identity | 서버 UUIDv7; body ID/key/actor/state 거부; 이름·분류·좌표 patch 후 UUID·claim·origin 불변 |
| 멱등 | 같은 actor/key/body의 201 exact replay; 같은 key/different body 409 |
| 동시성 | 서로 다른 key의 동일 exact body를 두 connection barrier로 동시 실행해 정확히 1×201, 1×409 |
| 원자성 | subtype/override 단계 fault injection 때 Feature, state, claim, origin, terminal result 모두 0 |
| legacy | legacy manual claim 수량 일치, origin 0, core `row_revision`·timestamp 변화 0 |
| 일반 create | provider/기존 fixture의 generic initial create가 origin 없이 계속 성공 |
| 오류 | 각 named CHECK/UNIQUE의 실제 HTTP status/code, 역방향 constraint inventory gate |
| ACL | runtime direct DML·TRUNCATE 거부, PUBLIC EXECUTE 거부, startup preflight 성공/결손 fail-close |
| freeze | target SQL 적용, violation rejection, 7축 fingerprint, artifact SHA, 실제 migration catalog parity |
| API 소비자 | admin OpenAPI/types/e2e 갱신; user/service OpenAPI byte 불변; PinVi direct path 제거 증거 |
| 복구 | 성공 전 reversible, 성공 후 forward-only disable; backup/restore 뒤 provenance/claim 불변 |

동시성 테스트는 API 응답만 세지 않는다. `features`, subtype, state transition, claim, origin,
field override, domain command/result를 모두 세어 orphan과 이중 감사가 없음을 확인한다.

## 12. M01 구현 파일 점검표

- ADR-093과 `docs/adr/README.md`
- Alembic migration, baseline schema/generated metadata, migration graph artifact
- `src/kortravelmap/infra/{models,admin_feature_repo,runtime_privileges,db}.py`
- `packages/kor-travel-map-api/.../routers/admin_features.py`
- domain command registry의 `admin.feature.create` response header/status replay 계약
- admin OpenAPI export 3종 drift 확인과 frontend generated types/form
- current/target DB constraint error mapper 및 reverse inventory tests
- unit, integration, migration, ACL, concurrent API tests
- PinVi 직접 create client/approval 경로 제거 또는 M04 이전 명시적 disabled 처리
- `docs/integration-map.md`, `CHANGELOG.md`, `docs/tasks.md`, `docs/resume.md`, `docs/journal.md`

## 13. 적대 검토 기록

| 검토자 | 렌즈 | 1차 판정 | 수정 | 재심 |
|---|---|---|---|---|
| 계약 전문 검토자 | API identity, principal, PinVi 경계, replay, OpenAPI | 대기 | 대기 | 대기 |
| DB 전문 검토자 | DDL, concurrency, ACL, migration, freeze, restore | 대기 | 대기 | 대기 |

두 재심은 이 문서의 동일 commit SHA를 대상으로 한다. `조건부 GO`나 P0~P3 잔여가 하나라도 있으면
M00은 완료하지 않는다.
