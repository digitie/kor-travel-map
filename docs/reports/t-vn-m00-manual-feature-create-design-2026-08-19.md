# T-VN-M00 — 수동 Feature 생성 2차 설계

- 상태: draft — 전문 리뷰 2차 finding 반영, 동일 SHA 최종 재심 대기
- 기준: `main` `025be0e638ba`
- 관련: ADR-066, ADR-068, ADR-070, ADR-074, ADR-075, ADR-083, ADR-086,
  ADR-090, ADR-092, ADR-093(proposed)
- 작성일: 2026-08-19

## 1. 결론과 구현 관문

T-VN-M01은 새 API를 처음 만드는 작업이 아니다. 현행 `POST /v1/admin/features`와
`feature.create_feature_with_initial_state` 결선은 이미 존재한다. M01은 다음 경계를 한 번에 바꾸는
clean cutover다.

1. canonical identity는 요청 속성으로 만들지 않고 서버가 UUIDv7을 발급한다.
2. 생성 시점 이름·좌표의 exact 중복은 별도 불변 claim의 DB unique 제약으로 막는다.
3. 기존 AdminBFF 인증과 생성 전용 2차 자격을 모두 통과한 admin UI BFF만
   `manual_admin` origin을 만들 수 있다.
4. claim, origin, core, initial state, subtype, field override, domain-command 결과를 한 트랜잭션으로
   원자화한다.
5. claim/origin을 포함하는 최소 backup·restore·ACL·hard-purge 안전망도 M01 활성화 전에 끝낸다.

`manual_pinvi`와 `manual_curation`은 M01 값 도메인에 넣지 않는다. 각 값을 발급할 별도 route와 권한
scope가 실제로 배포되는 M04와 M03에서 제약을 확장한다. provider가 같은 실체를 나중에 발행하는
경우도 M01에서 자동 병합하지 않고 M05의 검토 대상으로 남긴다.

두 전문 검토자가 **동일 commit SHA**에 P0~P3 잔여 없이 `GO`를 선언하기 전에는 M01 코드를
작성하지 않는다. 구현 뒤에도 다음 세 조건을 모두 만족하기 전에는
`KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true`로 바꾸지 않는다.

- PinVi의 `new_place` 직접 create 제거 commit이 먼저 배포됨
- M01 DB/API/admin UI와 최소 backup·restore·ACL reconciliation이 배포됨
- 전용 BFF 자격 성공, PinVi·일반 AdminBFF 거부, DB zero-write smoke가 통과함

## 2. 현행 사실과 clean cutover 범위

### 2.1 이미 존재하는 생성 경로

현행 코드는 다음 경로를 실행한다.

1. `AdminFeatureCreateRequest`가 body의 `feature_id`, `idempotency_key`, `operator`, 3축 상태와
   nullable `coord`까지 받는다.
2. `_create_feature_id()`가 caller key 또는 `name:lon,lat`로 `user_request` legacy ID를 만든다.
3. `admin.feature.create` domain command를 claim한다.
4. `create_admin_feature_with_field_overrides()`가 generic create procedure, subtype writer,
   field override를 같은 외부 트랜잭션에서 실행한다.
5. 현재 성공은 `200`, terminal replay header는 `ETag` 하나이며 외부 `data.feature_id`에는 이미
   canonical UUID를 넣는다.

따라서 M01은 “admin Feature 생성 API 신규 결선”이 아니라 기존 생성 API의 identity, provenance,
duplicate, auth, 201 replay 계약 교정이다. 기존 `admin.feature.create` terminal result는 수정하거나
재해석하지 않는다.

### 2.2 PinVi와 admin BFF는 현재 구분되지 않는다

PinVi `origin/main`의 `apps/api/app/api/v1/admin/feature_requests.py`는 `new_place` 승인 때
`KorTravelMapAdminClient.create_feature()`를 부른다. client 구현
`apps/api/app/clients/kor_travel_map_admin.py`는 Map admin UI와 같은 종류의
`X-Kor-Travel-Map-Admin-Proxy-Secret` 및 caller 지정 actor를 보낸다. PinVi client가 기대하는
`data.request`와 현재 Map 생성 응답도 이미 갈라져 있다.

기존 AdminBFF 자격이나 actor 문자열만으로 origin을 정하면 PinVi가 `manual_admin`으로 영구
오분류된다. M01은 기존 인증을 폐기하지 않고 생성 route에 전용 2차 자격을 추가한다. PinVi에는 그
자격을 배포하지 않는다.

### 2.3 current와 final target은 물리 키가 다르다

current DB는 `feature.features.feature_id text`와 `feature_uuid uuid`를 함께 가진다. T-VN-39 target은
`feature_id uuid` 하나가 정본이고 `f_*`는 `feature.feature_aliases`의
`alias_kind='legacy_feature_id'`로 남는다. M01 claim/origin relation은 처음부터 UUID만 저장하여
T-VN-39에서 재작성하지 않는다. procedure의 current/target 출력 차이는 §7.4의 명시적 bridge로
검증하고 두 catalog가 같다고 가정하지 않는다.

## 3. 단계 소유권과 배포 순서

| 단계 | 이 단계가 소유하는 것 | 이 단계에 넣지 않는 것 |
|---|---|---|
| M01 | 기존 admin create clean cutover, UUID, exact claim, `manual_admin`, 전용 BFF 2차 인증, 최소 backup·restore·ACL·hard-purge fence | PinVi·curation origin, fuzzy dedup |
| M02 | origin/claim read model, patch·state·purge의 전체 불변 검증, 운영 restore drill | M01 이전의 안전하지 않은 purge 허용 |
| M03 | T-VN-40 command 경계에서 동시 Feature+curation 생성, 그때 `manual_curation` 추가 | 일반 admin route에서 curation 추론 |
| M04 | PinVi 요청 queue와 Map 승인 경계, 그때 `manual_pinvi` 추가 | PinVi의 `/v1/admin/features` 직접 호출 |
| M05 | provider/manual fuzzy 후보 생성과 운영자 판정 | 자동 병합, identity 자동 교체 |

배포는 다음 순서를 바꾸지 않는다.

1. PinVi paired commit을 먼저 배포해 `new_place` 승인에서 Map 호출과 상태 변경을 모두 막는다.
2. Map migration, API, admin UI, role bootstrap, backup/restore manifest를 route flag `false`로 배포한다.
3. admin UI BFF에만 생성 token을 주입하고 API에는 그 token의 SHA-256 digest만 주입한다.
4. startup catalog/ACL preflight와 restore dry-run을 통과한다.
5. route flag를 `true`로 바꾸고 §4.2 auth matrix와 §11 smoke를 수행한다.

중간 상태에서 route는 `503 MANUAL_FEATURE_CREATE_NOT_READY`이며 어떠한 command·claim·Feature도
쓰지 않는다.

## 4. HTTP와 인증 계약

### 4.1 생성 전용 transport principal

기존 `AdminBFF` gate를 1차 인증으로 유지하고 생성 route에만 다음 2차 자격을 추가한다.

| 항목 | 고정값 |
|---|---|
| header | `X-Kor-Travel-Map-Admin-Feature-Create-Token` |
| OpenAPI security scheme | `AdminFeatureCreateBFF` (`apiKey`, `header`) |
| API digest env | `KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256` |
| admin UI server-only raw env | `KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN` |
| transport principal ID | `admin-ui-bff.manual-feature-create.v1` |
| authorization scope | `admin:feature:create` |
| dependency | `require_admin_manual_feature_create` |

OpenAPI의 route security는 OR 배열 두 개가 아니라 정확히 다음 **한 requirement object의 AND**다.

```yaml
security:
  - AdminBFF: []
    AdminFeatureCreateBFF: []
```

API는 raw token을 설정·로그·응답·OpenAPI에 저장하지 않는다. production에서 digest는 lowercase
64자리 hex여야 하고, token이 없거나 다음 자격 중 하나와 같으면 startup을 거부한다.

- 기존 admin proxy secret
- service/ops/metrics/curation/cache-target credential의 raw SHA-256 또는 설정된 digest

admin UI BFF는 browser가 보낸 두 인증 header를 모두 폐기한 뒤 server-side 값과 로그인 session에서
검증한 actor를 주입한다. dependency가 반환하는 context는
`principal_id='admin-ui-bff.manual-feature-create.v1'`, 검증된 `actor`,
`scopes=frozenset({'admin:feature:create'})`다. route와 DB writer는 body/header 문자열로 principal이나
origin을 선택하지 않는다.

### 4.2 인증 행렬과 zero-write

| caller | 기존 AdminBFF | 생성 token | 결과 |
|---|---:|---:|---|
| 공식 admin UI BFF | 유효 | 유효 | route 실행 가능 |
| 공식 admin UI BFF | 유효 | 누락/오류 | `403 ADMIN_FEATURE_CREATE_SCOPE_REQUIRED` |
| PinVi admin client | 유효 | 없음 | `403 ADMIN_FEATURE_CREATE_SCOPE_REQUIRED` |
| PinVi service token만 | 없음 | 없음 | 기존 AdminBFF `403` |
| 생성 token만 보유한 caller | 없음 | 유효 | 기존 AdminBFF `403` |
| 일반 AdminBFF의 다른 read/patch/delete | 유효 | 불필요 | 기존 계약 유지 |

실패 네 경우는 `ops.domain_commands`, claim, origin, core, subtype, transition, override, result가 모두
0행 증가임을 두 connection에서 검증한다. 인증 dependency와 route flag는 domain-command decorator보다
먼저 실행되어야 한다.

### 4.3 요청

`POST /v1/admin/features`는 UUID 형식 `Idempotency-Key` header와 다음 body를 받는다.

```json
{
  "kind": "place",
  "name": "태화강 국가정원",
  "category": "01010101",
  "coord": {"lon": 129.3077165, "lat": 35.5493385},
  "marker_icon": "garden",
  "marker_color": "P-03",
  "reason": "공식 관리자 수동 등록",
  "detail": {}
}
```

현행 typed address, URL, detail 필드는 유지하되 다음 caller-owned 필드는 제거하고 `extra=forbid`로
거부한다.

- `feature_id`
- body `idempotency_key`
- `operator`
- `lifecycle_state`, `publication_state`, `quality_state`

`coord`는 required이면서 non-null object다. `lon`/`lat`는 JSON number만 허용하고 string, boolean,
NaN, infinity를 거부한다. 범위는 각각 `124.0..132.0`, `33.0..39.5`다. `name`은 trim 전후를
구분해 저장하되 exact key 정규화 뒤 1..200자이면서 UTF-8 512 byte 이하여야 한다.

- missing/null/type/out-of-Korea는 Pydantic 또는 DB named validation으로 `422 VALIDATION_ERROR`다.
- exact key의 반올림은 §5.2의 DB `numeric` 연산만 사용한다. 유효 type/range에서 반올림은 total
  function이다. 예기치 않은 cast/rounding 예외는 wrapper가
  `ck_manual_feature_identity_coord_rounding` 23514로 바꿔 422로 낸다.
- half tie `129.3077165 → 129307717`, `35.5493385 → 35549339`를 current/target fixture로 고정한다.

### 4.4 domain command와 201 replay

route registry를 다음처럼 바꾼다.

```python
_domain(
    "admin.feature.create.manual-v1",
    _MUTATION_RESULT,
    success_status=201,
    replay_headers=("ETag", "Location"),
    transaction_isolation="read-committed",
)
```

operation rename은 기존 `admin.feature.create`의 200 terminal result와 새 201 body를 절대 replay하지
않기 위한 breaking-version 경계다. old operation은 read-only history로 보존하고 어떤 route도 새
command를 claim하지 않는다. old key를 새 route에 보내도 old result를 replay하지 않으며, legacy
backfill claim과 exact key가 같으면 기존 UUID를 담은 409를 받는다.

route는 terminal result를 기록하기 전에 `response.status_code=201`, strong
`ETag=revision_etag(row_revision)`, 상대 canonical URI
`Location=/v1/admin/features/{canonical-uuid}`를 설정한다. registry/decorator는 body와 두 header를
같은 transaction의 terminal result에 저장한다.

`CommandPolicy`가 허용하는 isolation 값에 `read-committed`를 추가하고 service는 transaction을 연
직후, domain-command claim보다 먼저 `SET TRANSACTION ISOLATION LEVEL READ COMMITTED`를 실행한다.
ambient DB·role default에는 의존하지 않는다. §5.3의 loser UUID 회수는 이 명시적 policy가 있어야만
유효하다.

### 4.5 성공 body와 replay

신규 response model은 `AdminManualFeatureCreateResponse`이며 기존 override response를 재사용하지
않는다. OpenAPI `data.feature_id`는 `type=string, format=uuid`; legacy `f_*`는 노출하지 않는다.

```http
HTTP/1.1 201 Created
ETag: "2"
Location: /v1/admin/features/0198d9f1-7a31-7e52-8ea8-cb2548d3a891
X-Request-ID: 6af0b664-3df1-4c57-8871-a170a75d2ed4
```

```json
{
  "data": {
    "feature_id": "0198d9f1-7a31-7e52-8ea8-cb2548d3a891",
    "creation_origin": "manual_admin",
    "row_revision": 2,
    "command_id": 1842,
    "applied_field_count": 5
  },
  "meta": {
    "duration_ms": 12,
    "request_id": "6af0b664-3df1-4c57-8871-a170a75d2ed4",
    "page": null,
    "cluster": null
  }
}
```

같은 actor/operation/key/body replay는 status, body, ETag, Location, 원래 `X-Request-ID`가 byte-equivalent다.
응답에만 `Idempotency-Replayed: true`를 추가한다. 같은 key의 다른 fingerprint는
`409 IDEMPOTENCY_KEY_REUSED`이며 최초 result를 바꾸지 않는다.

### 4.6 실패 body와 안정 필드

전용 scope 실패는 다음 shape다.

```json
{
  "type": "https://kor-travel-map/errors/admin-feature-create-scope-required",
  "title": "수동 Feature 생성 권한이 없습니다.",
  "status": 403,
  "detail": "수동 Feature 생성 권한이 없습니다.",
  "code": "ADMIN_FEATURE_CREATE_SCOPE_REQUIRED",
  "request_id": "<request-id>",
  "errors": [],
  "details": {"required_scope": "admin:feature:create"}
}
```

exact duplicate는 기존 UUID의 위치를 `details.existing_feature_id`로 고정한다.

```json
{
  "type": "https://kor-travel-map/errors/manual-feature-exact-duplicate",
  "title": "같은 수동 Feature가 이미 존재합니다.",
  "status": 409,
  "detail": "같은 수동 Feature가 이미 존재합니다.",
  "code": "MANUAL_FEATURE_EXACT_DUPLICATE",
  "request_id": "<request-id>",
  "errors": [],
  "details": {
    "constraint": "uq_manual_feature_identity_claims_exact",
    "existing_feature_id": "0198d9f1-7a31-7e52-8ea8-cb2548d3a891"
  }
}
```

validation은 `errors[].field`와 가능한 경우 `details.constraint`를 함께 고정한다. 예를 들어 null
coord는 `field='coord'`, DB 범위 실패는 `field='coord.lon'`과
`constraint='ck_manual_feature_identity_coord_range'`다. 알 수 없는 DB 오류의 response에는
SQLSTATE, constraint, SQL, payload를 싣지 않고 request ID만 노출한다.

### 4.7 PinVi paired cutover

M01 완료 receipt에는 PinVi `origin/main` 기준 다음 변경의 merge SHA를 반드시 기록한다.

1. `apps/api/app/api/v1/admin/feature_requests.py`: `suggestion_type='new_place'` 승인에서
   `admin_client.create_feature()`를 호출하지 않는다. suggestion은 `pending`, audit/ref/status는
   미변경이며 PinVi가 `503 MAP_FEATURE_REQUEST_QUEUE_UNAVAILABLE`를 반환한다.
2. `apps/api/app/clients/kor_travel_map_admin.py`: `create_feature()` method와 create용 old response
   parsing을 제거한다. correction/closure용 일반 AdminBFF 결선은 이 단계에서 유지할 수 있다.
3. `apps/api/tests/contract/kor-travel-map-openapi-admin.json`: Map admin spec의 breaking subset을
   재-vendor하고 `POST /v1/admin/features`를 PinVi callable inventory에서 제거한다.
4. `docs/integrations/kor-travel-map-rest-api.md`와 Map `docs/integration-map.md`: direct create를
   M04 queue 이전 disabled로 표시한다.

배포 증거는 source scan 0건, PinVi new-place 승인 503/상태 불변/Map outbound 0건, PinVi 일반
credential로 Map create 403/DB zero-write, 공식 BFF 두 자격으로 Map 201을 포함한다. PinVi commit과
vendored admin OpenAPI SHA가 없으면 Map route flag를 켜지 않는다.

## 5. canonical identity와 exact duplicate

### 5.1 canonical UUID와 current legacy alias

- canonical Feature ID는 ADR-068·083의 서버 발급 UUIDv7이다.
- `name`, category, 주소, 좌표, origin, idempotency key는 canonical ID 재료가 아니다.
- UUID 후보는 domain command가 처음 claim된 뒤 한 번 생성하고 terminal result에 봉인한다.
- 이름·분류·좌표를 나중에 수정해도 UUID와 생성 claim은 변하지 않는다.

current text PK가 남아 있는 동안 UUID를 먼저 만든 뒤 다음 opaque natural key로 legacy ID를 만든다.

```text
bjd_code = None                  # make_feature_id에서는 global
kind = validated request kind    # place|event
category = manual_feature_v1     # 실제 category가 아닌 bridge 상수
source_type = user_request
source_natural_key = manual::<canonical-feature-uuid>
content_hash = None
```

생성 위치는 DB wrapper가 아니라 Python repository다. domain command가 claim된 뒤 repository가 기존
`candidate_feature_uuid()`로 UUIDv7을 한 번 만들고, lowercase hyphenated UUID 문자열과 위 여섯
인자를 `make_feature_id()`에 넣는다. 실제 `category`, `legal_dong_code`, 이름, 좌표,
`Idempotency-Key`는 이 bridge 입력에 넣지 않는다. repository가 만든 `feature_id`와
`feature_uuid`는 request model이 아닌 server-only internal payload에 추가해 wrapper로 보낸다.

고정 golden vector는 다음과 같다.

```text
uuid = 0198d9f1-7a31-7e52-8ea8-cb2548d3a891
place -> f_global_p_9f9480adb6abef69
event -> f_global_e_a221cb848390f739
```

`kind`는 legacy prefix와 hash에 남는 생성 시점 immutable snapshot일 뿐 canonical identity 재료가
아니다. old route의 `_create_feature_id(body)`는 삭제하고 manual-v1 call graph에서 참조 0건을
static test로 고정한다. unit test는 helper 인자가 UUID/kind뿐임과 name/coord/category/legal-dong/key를
바꿔도 같은 UUID에 같은 bridge ID가 나옴을 단언한다.

T-VN-39 뒤 그 exact `f_*` 값은
`feature.feature_aliases(alias_kind='legacy_feature_id')`에만 남는다. current→target migration은
golden vector로 만든 alias가 같은 canonical UUID를 가리키는지 검증한다.

### 5.2 DB 단일 exact-key 함수

current migration과 target freeze는 동일한
`feature.manual_feature_identity_key(text,text,numeric,numeric)` 함수와 fixture를 사용한다. Python은
exact key를 계산하거나 비교하지 않는다. 함수는 UTF-8 DB에서 다음 순서를 고정한다.

1. `feature_kind`는 `place|event`인지 확인한다.
2. `btrim(name)`에 PostgreSQL `normalize(..., NFC)`를 적용한다.
3. locale case fold를 사용하지 않고 ASCII `A..Z`만 `translate`로 `a..z`로 바꾼다. relation 열과
   unique index는 `COLLATE "C"`다. 한국어와 비 ASCII 문자는 NFC byte 그대로다.
4. key가 1..200자, UTF-8 512 byte 이하인지 확인한다.
5. JSON number를 먼저 PostgreSQL `numeric`으로 옮기고 finite/type/range를 확인한다.
6. `round(value * 1000000, 0)::integer`를 계산한다. PostgreSQL numeric half tie의 0에서 먼 방향을
   정본으로 삼는다.

결과는 다음 tuple이다.

```text
(feature_kind, name_key, lon_e6, lat_e6)
```

category는 넣지 않는다. 같은 실체의 분류 보정이 새 identity를 만들면 안 된다. name/coord가 exact
규칙 밖에서 다른 유사 실체는 M05 후보일 뿐 M01이 병합하지 않는다.

### 5.3 동시 exact claim

READ COMMITTED check-then-act 프리체크는 정합성 장치로 쓰지 않는다. §4.4 policy가 transaction의
첫 DB statement로 READ COMMITTED를 설정한 뒤 wrapper는
`current_setting('transaction_isolation') = 'read committed'`를 확인한다. 다르면 claim INSERT 전에
25001 / `ck_manual_feature_create_isolation`으로 fail-close한다. wrapper는 다음 statement를 사용한다.

```sql
INSERT INTO feature.manual_feature_identity_claims (...)
VALUES (...)
ON CONFLICT ON CONSTRAINT uq_manual_feature_identity_claims_exact DO NOTHING
RETURNING feature_id;
```

반환 행이 없으면 다음 PL/pgSQL statement의 새 READ COMMITTED snapshot에서 exact tuple을 다시
조회한다. PostgreSQL은 concurrent uncommitted winner가 끝날 때까지 `ON CONFLICT`를 기다리므로,
다음 SELECT는 committed winner UUID를 본다. wrapper는 raw 23505를 밖으로 던지지 않고
`outcome='exact_conflict'`, `existing_feature_uuid=<winner>`를 반환한다.

PK·command unique 충돌은 exact conflict와 다른 invariant이므로 `ON CONFLICT`가 잡지 않는다.
그 named 23505는 `FEATURE_IDENTITY_CONFLICT`로 분류한다. exact loser의 외부 transaction은 rollback되어
loser command/core/subtype/transition/claim/origin/override/result가 모두 0행이다.

integration test는 database와 두 login의 ambient default를 각각 `repeatable read`로 바꿔도 HTTP
service의 첫 statement가 READ COMMITTED로 덮어쓰는지 확인한다. 반대로 wrapper를 repeatable-read
transaction에서 직접 부르면 stable 25001로 거부되어 winner SELECT가 오래된 snapshot을 쓰지 못한다.

## 6. 저장 모델과 legacy backfill

### 6.1 `feature.manual_feature_identity_claims`

이 relation은 exact 중복 예약이며 origin이 아니다.

| 열 | 계약 |
|---|---|
| `feature_id uuid` | PK. current `features.feature_uuid`, target `features.feature_id` 값 |
| `feature_kind text` | `place|event` |
| `name_key text COLLATE "C"` | §5.2 함수가 만든 생성 시점 snapshot |
| `lon_e6 integer`, `lat_e6 integer` | §5.2 함수가 만든 대한민국 범위 좌표 |
| `claimed_by_command_id bigint` | NOT NULL, `ops.domain_commands` FK |
| `claim_basis text` | `manual_create|legacy_admin_route` |
| `claimed_at timestamptz` | 신규는 DB 시각, legacy는 command `created_at` |

명시적 제약은 다음과 같다.

- `pk_manual_feature_identity_claims(feature_id)`
- `uq_manual_feature_identity_claims_exact(feature_kind,name_key,lon_e6,lat_e6)`
- `uq_manual_feature_identity_claims_command(claimed_by_command_id)`
- `uq_manual_feature_identity_claims_feature_command(feature_id,claimed_by_command_id)`
- `fk_manual_feature_identity_claims_command(... ops.domain_commands ON DELETE RESTRICT)`
- `ck_manual_feature_identity_claims_kind`
- `ck_manual_feature_identity_claims_name_key`
- `ck_manual_feature_identity_claims_lon_e6`
- `ck_manual_feature_identity_claims_lat_e6`
- `ck_manual_feature_identity_claims_basis`

### 6.2 `feature.feature_creation_origins`

이 relation은 검증된 생성 provenance만 보존한다.

| 열 | 계약 |
|---|---|
| `feature_id uuid` | PK, claim과 composite FK |
| `origin_kind text` | M01 DDL에서는 오직 `manual_admin` |
| `creation_command_id bigint` | NOT NULL·unique, command FK |
| `creator_principal_id text` | `admin-ui-bff.manual-feature-create.v1` 상수 |
| `created_by_actor text` | locked domain-command actor에서 복사 |
| `created_at timestamptz` | DB 시각 |
| `invoker_role text` | `session_user` 감사 |
| `procedure_definer text` | wrapper owner 감사 |

명시적 제약은 다음과 같다.

- `pk_feature_creation_origins(feature_id)`
- `uq_feature_creation_origins_command(creation_command_id)`
- `fk_feature_creation_origins_command(... ops.domain_commands ON DELETE RESTRICT)`
- `fk_feature_creation_origins_claim(feature_id,creation_command_id)` → claim의
  `(feature_id,claimed_by_command_id)` `ON DELETE RESTRICT`
- `ck_feature_creation_origins_kind`
- `ck_feature_creation_origins_principal`
- `ck_feature_creation_origins_actor`
- `ck_feature_creation_origins_roles`

origin이 claim과 다른 command를 가리키거나 dangling command를 가리키는 상태는 선언적으로
불가능하다. M03/M04는 실제 auth/writer가 생기는 migration에서만 `origin_kind` CHECK를 확장한다.

두 relation에는 `feature.features` FK를 의도적으로 두지 않는다. 물리 purge 뒤에도 reservation과
provenance를 보존하고 T-VN-39 때 재작성하지 않기 위해서다. 대신 M02 purge 계약이 완료될 때까지
manual claim/origin이 있는 Feature의 hard purge는 DB procedure와 CLI/API 양쪽에서
`409 MANUAL_FEATURE_PURGE_NOT_READY`로 막는다. soft retire는 이 fence와 무관하다.

### 6.3 append-only trigger

각 relation은 전용 reject function 하나와 trigger 두 개를 가진다.

| relation | row trigger | statement trigger | stable diagnostic |
|---|---|---|---|
| claims | `BEFORE UPDATE OR DELETE FOR EACH ROW` | `BEFORE TRUNCATE FOR EACH STATEMENT` | 42501 / `ck_manual_feature_identity_claims_append_only` |
| origins | `BEFORE UPDATE OR DELETE FOR EACH ROW` | `BEFORE TRUNCATE FOR EACH STATEMENT` | 42501 / `ck_feature_creation_origins_append_only` |

함수는 `SECURITY DEFINER SET search_path=pg_catalog`, owner
`ktm_feature_audit_writer`이며 PUBLIC, shared runtime, API/Dagster login, 두 executor, manual procedure
owner의 direct EXECUTE를 모두 revoke한다. violation fixture는 UPDATE, DELETE, TRUNCATE 세 동작을 각각
검증한다.

### 6.4 legacy claim backfill의 정본 SQL

과거 origin은 추정하지 않는다. legacy **claim**만 durable evidence로 복구한다. migration은 route가
fenced된 상태에서 기존 네 relation을 안정적으로 읽고, 다음 조건을 모두 만족하는 행을 candidate로
삼는다.

1. `feature.feature_state_transitions`에서 feature별 최소 `transition_id`가
   `from_* IS NULL`, `transition_kind='initial'`, `reason_code='admin_feature_create'`,
   `causation_ref='domain-command:<positive bigint>'`다.
2. parse한 command가 `ops.domain_commands.command_id`와 같고 operation은 old
   `admin.feature.create`, actor는 transition principal과 같다.
3. 같은 command에 `ops.domain_command_results`가 정확히 1행이고 status는 old success `200`,
   response `data.feature_id` UUID는 transition `feature_uuid`와 같다.
4. `ops.feature_overrides`에는 `feature_uuid` 열이 없다. 따라서
   `override.feature_id=transition.feature_id`, `override.command_id=command.command_id`,
   `field_path='core.name'`으로 연결한 행이 정확히 1개여야 한다. `override_value`는 JSON string,
   `value_geometry IS NULL`, `created_by=command.actor`다.
5. 같은 실제 두 열 `(feature_id,command_id)`과 `field_path='core.coord'`로 연결한 행이 정확히
   1개여야 한다. `value_geometry`는 finite SRID 4326 Point,
   `override_value IS NULL`, `created_by=command.actor`다.
6. creation override의 현재 status는 판정에 쓰지 않는다. 후속 patch로 superseded/revoked되어도 같은
   command의 original row가 생성 시점 snapshot이다.
7. UUID parity는 override에서 읽지 않는다. transition `feature_uuid`가 canonical UUIDv7이고 old
   result `data.feature_id`와 같은지 별도로 확인한다. 같은 command·feature의 중복 evidence가 없고
   §5.2 key로 묶은 candidate 간 exact 충돌도 없어야 한다.

read-only preflight는 permanent DDL/INSERT보다 먼저 실행한다. missing, duplicate, malformed,
operation/actor/UUID 불일치, exact 충돌이 하나라도 있으면 migration 전체를 중단하고 offender
command/feature ID만 출력한다. route fence와 transaction-level relation lock으로 preflight와 INSERT
사이 신규 old create를 막는다.

preflight가 0건 실패일 때만 테이블을 만들고, candidate마다 다음 claim을 넣는다.

```text
feature_id              = transition.feature_uuid
claimed_by_command_id   = parsed command_id
claim_basis             = legacy_admin_route
claimed_at              = domain_commands.created_at
name/coord exact key     = creation command의 두 override
```

origin backfill은 0건이다. 과거 PinVi/admin 공유 경계를 구분할 수 없기 때문이다. backfill은 기존
Feature·transition·override를 UPDATE하지 않아 `row_revision`, timestamp, lineage를 바꾸지 않는다.

## 7. DB writer와 원자성

### 7.1 current wrapper signature

current text bridge에는 다음 SECURITY DEFINER procedure를 추가한다. OUT parameter는 procedure
identity에 포함되지 않지만 repository row shape로 exact 검증한다.

```text
feature.create_admin_manual_feature_with_initial_state(
    IN  p_feature_payload jsonb,
    IN  p_domain_command_id bigint,
    OUT o_outcome text,                 -- created|exact_conflict
    OUT o_feature_id text,              -- current legacy f_* only
    OUT o_feature_uuid uuid,            -- canonical success UUID
    OUT o_row_revision bigint,
    OUT o_existing_feature_uuid uuid    -- exact_conflict에서만 non-null
)
```

### 7.2 wrapper algorithm

wrapper는 `search_path=pg_catalog`이고 모든 relation/function을 schema-qualified로 부른다.

1. §4.4가 설정한 isolation과 §8의 `session_user`/membership gate를 claim보다 먼저 검사한다.
2. `ops.domain_commands` row를 `FOR UPDATE`로 잠근다. command가 존재하고 operation이
   `admin.feature.create.manual-v1`이며 result가 아직 없고 actor가 canonical인지 검사한다.
3. payload가 object인지, unknown/forbidden key가 없는지, caller UUID·상태·origin·principal을 싣지
   않았는지 검사한다. 서버가 넣은 UUIDv7, `place|event`, name, required coord를 named 23514로
   검증한다.
4. §5.2 exact key를 계산하고 claim을 `ON CONFLICT ON CONSTRAINT ... DO NOTHING`으로 넣는다.
5. exact conflict면 새 statement에서 winner UUID를 읽어 outcome을 반환한다. core/origin을 부르지
   않는다.
6. winner면 generic `feature.create_feature_with_initial_state`를 고정 tuple
   `active/published/valid`, `transition_kind=initial`, `reason_code=admin_feature_create`, locked actor,
   `causation_ref=domain-command:<id>`로 호출한다.
7. generic 결과가 `o_inserted IS TRUE`이고 returned legacy ID/UUID가 payload·claim과 정확히 같은지
   검사한다. false/mismatch면 origin 전에 23514
   `ck_manual_feature_create_core_identity`로 실패한다.
8. origin을 `manual_admin`, 전용 principal 상수, locked actor로 INSERT하고 성공 OUT을 반환한다.

Python repository는 success에만 subtype과 initial field override를 같은 외부 transaction에서 쓴다.
`feature.author_feature_field_overrides`의 open-command allow-list는 old
`admin.feature.create`를 제거하고 `admin.feature.create.manual-v1`을 허용한다. 따라서 새 command는
override까지 진행할 수 있고, 폐기한 old operation으로 신규 write를 재개할 수 없다.
route는 최종 row revision과 override count를 받은 뒤 §4.4 header를 설정하고 decorator가 terminal
result를 기록한다. claim 뒤, generic 뒤, origin 뒤, subtype 뒤, override 뒤, terminal 직전의 fault
injection은 전부 transaction rollback을 단언한다.

### 7.3 exact loser와 typed repository result

repository result는 union으로 고정한다.

- `Created(feature_uuid,row_revision,command_id,applied_field_count)`
- `ExactDuplicate(existing_feature_uuid,constraint='uq_manual_feature_identity_claims_exact')`

exact duplicate를 raw DB exception으로 바꾸지 않는다. route가 typed duplicate를 409로 바깥에
던지면 domain-command outer transaction도 rollback한다. 같은 loser key 재시도는 terminal replay가
아니라 같은 winner UUID의 deterministic 409다.

### 7.4 T-VN-39 target signature와 semantic bridge

target freeze에는 같은 IN signature와 다음 UUID-only output을 선언한다.

```text
feature.create_admin_manual_feature_with_initial_state(
    IN  p_feature_payload jsonb,
    IN  p_domain_command_id bigint,
    OUT o_outcome text,
    OUT o_feature_id uuid,
    OUT o_row_revision bigint,
    OUT o_existing_feature_id uuid
)
```

T-VN-39 migration은 current procedure를 drop/recreate하고 current `o_feature_uuid`를 target
`o_feature_id`에 매핑한다. current `o_feature_id text`는 output에서 사라지고 기존 `f_*`는 alias trigger가
`feature.feature_aliases`에 보존한다. claim/origin relation과 command ID는 rewrite하지 않는다.

parity gate는 catalog equality가 아니라 다음 의미 mapping을 검사한다.

- current canonical `o_feature_uuid` = target canonical `o_feature_id`
- current `o_existing_feature_uuid` = target `o_existing_feature_id`
- operation, exact-key vector, claim/origin rows, command causation, initial tuple, 201 body/header가 동일
- current `category` → target `category_code` payload mapping 외 API body 의미가 동일
- current legacy text output만 target에서 제거되고 §5.1 golden alias lookup은 유지

## 8. DB 역할과 닫힌 ACL

### 8.1 신규 역할과 generic create 분리

| role | 속성/멤버십 | 목적 |
|---|---|---|
| `ktm_manual_feature_procedure_owner` | NOLOGIN NOINHERIT; schema owner가 SET 가능 | wrapper·normalizer owner와 call-chain 최소 권한 |
| `ktm_manual_feature_admin_executor` | NOLOGIN NOINHERIT; API login만 INHERIT, SET 불가 | wrapper EXECUTE |
| `ktm_feature_create_provider_executor` | NOLOGIN NOINHERIT; Dagster login만 INHERIT, SET 불가 | generic create 직접 EXECUTE |

bootstrap은 API가 admin executor의 member이면서 provider executor의 non-member이고, Dagster는 그
반대임을 fail-close한다. wrapper 본문도 다음을 다시 검사한다.

```text
session_user = ktm_feature_api_runtime
pg_has_role(session_user, ktm_manual_feature_admin_executor, member) = true
pg_has_role(session_user, ktm_feature_create_provider_executor, member) = false
```

불일치는 42501 `ck_manual_feature_create_executor`다.

기존 generic create의 EXECUTE는 PUBLIC과 `ktm_feature_runtime`에서 revoke한다. 직접 grant 대상은
provider executor와 manual procedure owner뿐이다. 따라서 API login은 wrapper 밖에서 generic create를
부를 수 없고 Dagster는 generic create만 부를 수 있으며 `manual_admin` origin을 만들 수 없다.

bootstrap membership은 다음 exact option을 갖는다.

```text
ktm_manual_feature_procedure_owner -> ktm_feature_schema_owner:
    ADMIN false, INHERIT false, SET true
ktm_manual_feature_admin_executor -> ktm_feature_api_runtime:
    ADMIN false, INHERIT true, SET false
ktm_feature_create_provider_executor -> ktm_feature_dagster_runtime:
    ADMIN false, INHERIT true, SET false
```

### 8.2 relation·function ACL

- claim/origin은 `_FEATURE_TABLE_PRIVILEGES`에 넣지 않고 `_PROTECTED_FEATURE_TABLES`에 넣는다.
  M01 runtime login은 direct SELECT/DML/TRUNCATE가 모두 없다. 생성 response는 procedure OUT을 쓴다.
- claim/origin relation owner는 `ktm_feature_schema_owner`다. manual procedure owner만 두 relation의
  `SELECT, INSERT`를 가진다. schema owner/migrator의 migration 권한 외 direct writer는 없다.
- wrapper/normalizer의 target owner인 manual procedure owner에는 ownership 이전에 필요한
  `USAGE, CREATE ON SCHEMA feature`와 `USAGE ON SCHEMA ops`를 bootstrap이 준다. NOLOGIN이고 API는
  이 owner role을 상속하거나 SET할 수 없다.
- wrapper call chain에는
  `SELECT ON ops.domain_commands, ops.domain_command_results`,
  `UPDATE(command_id) ON ops.domain_commands`(row lock에 필요한 현행 최소 패턴),
  `EXECUTE ON feature.create_feature_with_initial_state(...)`만 추가한다. command/result DML이나
  다른 generic procedure 권한은 주지 않는다.
- wrapper와 normalizer는 PUBLIC/shared/Dagster에서 revoke하고 admin executor에 wrapper EXECUTE만
  grant한다. normalizer는 manual owner와 migration owner만 실행한다.
- append-only 함수 두 개는 `_AUDIT_WRITER_FUNCTION_ACL`, wrapper/generic split은
  `_STATE_OWNER_FUNCTION_ACL` 또는 동등한 닫힌 manifest에 exact signature로 넣는다.
- `src/kortravelmap/infra/db.py`의 login별 executable procedure allow-list는 API에서 generic을 빼고
  manual wrapper를 넣으며, Dagster에는 generic만 남긴다. unexpected routine 하나도 startup 실패다.
- `docker/postgres-role-bootstrap.sh`는 role 속성, membership option, owner repair, routine owner,
  schema grant, call-chain ACL, PUBLIC revoke를 모두 재실행 가능하게 맞춘다. runtime privilege
  reconciler와 startup/restore closed manifest도 같은 grant 집합을 exact 비교한다.

M02가 read model을 만들 때 table SELECT를 넓히지 않고 view 또는 별도 typed reader를 설계한다.

### 8.3 startup·restore preflight

두 runtime login을 실제 DSN으로 접속해 다음을 각각 확인한다.

- API: wrapper 실행 가능, generic 직접 실행 불가, claim/origin direct SELECT·DML·TRUNCATE 불가
- Dagster: generic 실행 가능, wrapper 실행 불가, claim/origin direct 접근 불가
- 둘 다 owner/SET ROLE/PUBLIC 우회 불가
- procedure/function/table owner가 closed manifest와 정확히 같음

권한 probe는 rollback-only payload 또는 catalog `has_*_privilege`를 사용하고 실제 Feature를 남기지
않는다.

## 9. DB 오류의 HTTP 분류

### 9.1 constraint/result mapping

| DB/result identity | HTTP | code | details |
|---|---:|---|---|
| wrapper `exact_conflict` | 409 | `MANUAL_FEATURE_EXACT_DUPLICATE` | constraint + `existing_feature_id` |
| claim PK/command/composite unique, `pk_features`, `uq_features_feature_uuid`, alias identity, origin PK/command unique | 409 | `FEATURE_IDENTITY_CONFLICT` | stable constraint, known UUID만 |
| 23514 `ck_manual_feature_create_core_identity`(`o_inserted=false` 또는 returned ID mismatch) | 409 | `FEATURE_IDENTITY_CONFLICT` | constraint + attempted canonical UUID |
| request/exact-key named 23514, subtype/field/category/parent typed input constraint/FK | 422 | `VALIDATION_ERROR` | field + stable constraint |
| Pydantic missing/null/type/range | 422 | `VALIDATION_ERROR` | `errors[]` field path |
| `ck_manual_feature_create_executor` | startup fail; route 도달 시 500 | `INTERNAL_SERVER_ERROR` | constraint 비노출 |
| 25001 `ck_manual_feature_create_isolation` | 500 | `INTERNAL_SERVER_ERROR` | request ID만 |
| claim/origin command/composite FK, append-only 42501, audit NOT NULL 등 내부 causation 위반 | 500 | `INTERNAL_SERVER_ERROR` | request ID만 |
| 미등록 SQLSTATE/constraint | 500 | `INTERNAL_SERVER_ERROR` | request ID만 |

`FEATURE_IDENTITY_CONFLICT` example의 `details.constraint`은 allow-list에 있는 이름만 노출한다. raw SQL,
driver message, token, actor는 노출하지 않는다.

### 9.2 cast·NOT NULL·FK·explicit RAISE reverse inventory

wrapper는 JSON type을 확인하기 전에 `::uuid`, `::numeric`, `::smallint`, geometry cast를 하지 않는다.
도달 가능한 `22P02`, `22003`, `22023`은 PL/pgSQL exception block에서 field별 named 23514로 바꾼다.
input에서 유래한 `23502`와 `23503`은 column/constraint allow-list로 422에만 매핑한다. command/claim/origin
causation에서 유래한 같은 SQLSTATE는 500이다.

CI reverse inventory는 CHECK·UNIQUE만 세지 않는다. current migration과 target SQL에서 다음을 모두
추출해 정확히 한 분류에 속하는지 검사한다.

- wrapper/generic/subtype/override call graph의 CHECK, PK, UNIQUE, FK
- route-reachable NOT NULL column
- explicit `RAISE ... ERRCODE/CONSTRAINT`
- JSON/UUID/numeric/date/geometry cast path와 exception translation
- procedure result outcome enum
- `ck_manual_feature_create_core_identity`가 validation 집합이 아닌 identity-conflict 집합에만 있는지
- `ck_manual_feature_create_isolation`이 internal 집합에만 있는지

새 이름이나 SQLSTATE가 분류 없이 추가되면 CI가 실패한다. 실제 DB exception과 HTTP response를 함께
검사하고 문자열 message matching은 사용하지 않는다.

## 10. migration, freeze, backup·restore, backout

### 10.1 migration 번호와 단계

T-VN-40C가 `0224`를 예약했다. M01은 번호를 지금 선점하지 않고 main rebase 때 T-VN-41S와 조정해
`0225+` 실제 head를 배정한다.

1. old route flag false와 PinVi paired receipt 확인
2. 수정된 bootstrap을 먼저 실행해 NOLOGIN owner/executor와 schema ownership grant를 생성·검증
3. read-only legacy preflight와 relation lock
4. normalizer, table, FK/check/unique, append-only function/trigger, wrapper 생성과 owner 이전
5. legacy claim INSERT, candidate count/ordered SHA-256 root 검증, origin backfill 0 단언
6. owner·ACL reconciliation과 두 login preflight
7. API/admin UI/OpenAPI clean cutover, registry operation/status/header/isolation 변경
8. backup/restore manifest 및 hard-purge fence 검증
9. 전용 token 배포 뒤 route flag와 auth/201/replay smoke

### 10.2 vNext freeze

구현 PR은 다음을 한 묶음으로 갱신한다.

- `contracts/vnext/target-schema-v1.sql`
- `target-schema-fingerprints-v1.json`의 현행 7축
  (`columns`, `constraints`, `functions`, `indexes`, `relations`, `sequence`, `triggers`)
- `violation-fixtures-v1.sql`
- `expected-rejections-v1.json`
- `tests/unit/test_vnext_contract_artifacts.py`의 artifact SHA-256 상수
- current/target procedure semantic bridge fixture
- admin OpenAPI export와 frontend generated types

빈 target DB와 실제 migration DB의 catalog를 각각 검증하되 §7.4의 의도된 text/UUID 차이를 직접
catalog equality로 오판하지 않는다.

### 10.3 backup·restore와 cache-target epoch 분리

claim, origin, 그들이 참조하는 command/result는 한 `pg_dump` consistent snapshot에 들어간다. backup
manifest는 다음 relation별 row count와 PK 순 canonical JSONL SHA-256 root를 기록한다.

- `feature.manual_feature_identity_claims`
- `feature.feature_creation_origins`
- claim/origin이 참조하는 `ops.domain_commands`
- 해당 command의 `ops.domain_command_results`

restore는 manifest count/root를 snapshot과 비교한다. 현행 `pg_restore --no-owner --no-privileges` 뒤에는
bootstrap owner repair와 runtime ACL reconciler를 반드시 실행하고 §8.3을 다시 통과해야 service를
연다. 새 table, procedure, normalizer, trigger function을 bootstrap closed owner manifest에 넣는다.

ADR-081의 cache-target `restore_epoch`는 DB restore identity가 아니다. DB snapshot 검증이 끝난 뒤
downstream consumer invalidation fence를 전진시키는 용도로만 사용한다. claim/origin 복원 여부를
epoch 값으로 추정하지 않는다.

### 10.4 backout

- 첫 성공 create 전: route를 닫고 migration downgrade로 관계와 procedure를 제거할 수 있다.
- 첫 claim/origin 후: forward-only다. route를 닫고 relation을 보존한 채 후속 migration으로 고친다.
  claim/origin을 drop/update/delete하는 rollback은 금지한다.
- shared PinVi credential을 되살리는 rollback은 금지한다.
- M02 purge 계약 전에는 hard purge fence를 제거하지 않는다.

## 11. 구현 검증 행렬

| 축 | 필수 증거 |
|---|---|
| 인증 | OpenAPI AND security; 공식 BFF 두 자격 성공; 일반 BFF·PinVi·service token·2차 token 단독 403 및 8관계 zero-write |
| 요청 | `coord` required/non-null; missing/null/string/NaN/range 422; body ID/key/actor/state 거부 |
| identity | 서버 UUIDv7; opaque legacy alias; patch 뒤 UUID·claim·origin 불변 |
| current bridge | §5.1 place/event golden vector; actual category/legal-dong/name/coord/key 무관; old `_create_feature_id` call 0 |
| exact key | NFC/ASCII lower/C collation/name byte bound/numeric half-tie current·target vector |
| 멱등 | 같은 actor/key/body 201 exact replay + original request ID; same key/different body 409 |
| 동시성 | 서로 다른 key의 same exact body를 두 connection barrier로 실행해 1×201, 1×409(existing UUID), loser 8관계 zero-write |
| isolation | ambient repeatable-read에도 service 첫 statement가 READ COMMITTED; wrapper direct repeatable-read는 25001 fail-close |
| generic collision | `o_inserted=false` 또는 returned ID mismatch를 origin 전 409로 rollback |
| fault | claim/generic/origin/subtype/override/result 각 경계 fault injection 전체 rollback |
| legacy | deterministic transition→command/result→name/coord override; missing/duplicate/exact conflict pre-DDL abort; claim 수량/root; origin 0; core 무변경 |
| causation | 두 command FK와 origin→claim composite FK의 mismatch 거부 |
| append-only | 두 relation 각각 UPDATE/DELETE/TRUNCATE stable 42501/constraint |
| ACL | API wrapper-only, Dagster generic-only, owner의 schema/command-lock 최소 ACL exact, direct relation 접근/PUBLIC/SET ROLE 거부, restore 뒤 동일 |
| 오류 | PK/UNIQUE/FK/CHECK/NOT NULL/cast/explicit raise/result outcome reverse inventory와 HTTP code |
| freeze | target apply, violation rejection, 7축 fingerprint, artifact SHA, semantic bridge |
| PinVi | exact caller 2파일 제거, vendored admin spec SHA, 503 pending/no outbound, Map 403 zero-write |
| 복구 | same-snapshot 4관계 count/root, no-owner/no-ACL restore 뒤 owner/ACL repair, cache epoch는 후속 invalidation만 |

동시성 테스트는 API 응답만 세지 않는다. `features`, subtype, state transition, claim, origin,
field override, domain command, domain result를 각각 세어 orphan과 이중 감사가 없음을 확인한다.

## 12. M01 구현 파일 점검표

- ADR-093과 `docs/adr/README.md`
- Alembic migration, baseline schema/generated metadata, migration graph artifact
- `src/kortravelmap/infra/{models,admin_feature_repo,runtime_privileges,db}.py`
- `packages/kor-travel-map-api/.../{auth,settings,domain_command_registry}.py`
- `packages/kor-travel-map-api/.../routers/admin_features.py`
- admin frontend BFF proxy/settings/form/generated types
- backup/restore manifest, bootstrap owner repair, hard-purge fence
- current/target DB error mapper 및 reverse inventory tests
- admin OpenAPI export 3종 drift 확인; user/service OpenAPI byte 불변
- PinVi caller 2파일, vendored admin OpenAPI, integration docs의 paired commit receipt
- unit, integration, migration, ACL, concurrent API, restore tests
- `docs/integration-map.md`, `CHANGELOG.md`, `docs/tasks.md`, `docs/resume.md`, `docs/journal.md`

## 13. 전문 검토 기록

| 검토자 | 1차 판정 | 2차 판정(`56fa3148`) | 2차 finding 반영 위치 | 최종 재심 |
|---|---|---|---|---|
| API 계약 전문 검토자 | `HOLD`: P0 2, P1 3, P2 1 | 기존 6건 닫힘, 신규 P1 1 | §5.1, §7.4, §11 | 대기 |
| DB/동시성 전문 검토자 | `NO-GO`: P1 5, P2 6 | 기존 8건 닫힘, P1 2·P2 2 잔여 | §4.4, §5.3, §6.4, §8, §9, §11 | 대기 |

API finding별 반영은 201 registry/header/old operation 격리(§4.4), 전용 transport principal(§4.1~4.2),
exact response schema(§4.5), constraint error payload(§4.6·§9), PinVi paired fence(§4.7), coord
required/non-null과 rounding 계약(§4.3)이다.

DB finding별 반영은 conflict outcome/기존 UUID(§5.3·§7.3), creation override backfill(§6.4),
API-only executor(§8), 선언적 command/composite FK(§6.1~6.2), current/target bridge(§7.4), generic
`o_inserted` 검증(§7.2), 전체 오류 inventory(§9), 결정적 key(§5.2), 두 append-only trigger(§6.3),
snapshot restore와 cache epoch 분리(§10.3), 닫힌 ACL manifest(§8)다.

2차 API finding은 current legacy bridge의 생성 위치·정확한 인자·golden vector와 target alias parity를
명세해 닫았다. 2차 DB finding은 실제 override 열을 쓰는 backfill join, owner의 전체 call-chain ACL,
core identity 23514의 409 분류, 명시적 READ COMMITTED 설정·검증으로 닫았다.

최종 재심은 이 문서와 ADR의 동일 commit SHA를 대상으로 한다. `조건부 GO`나 P0~P3 잔여가 하나라도
있으면 M00을 완료로 표시하지 않는다.
