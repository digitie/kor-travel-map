# T-VN-M00 — 수동 Feature 생성 2차 설계 초안

- 상태: draft — 적대 리뷰 2명 GO 전에는 M01 구현 금지
- 기준: `main` `025be0e6`
- 관련: ADR-048, ADR-074, ADR-075, ADR-083, ADR-086, ADR-090, ADR-092,
  ADR-093(proposed)
- 작성일: 2026-08-19

## 1. 범위

M00은 구현 PR이 아니라 M01의 설계 gate다. 목표는 provider ETL이 만들지 않는 장소를
admin/API로 만들 수 있게 하되, 같은 실체 중복·origin 사칭·HTTP 500 누수·freeze drift를
M01 전에 닫는 것이다.

M01은 기존 `POST /v1/admin/features`와 `admin.feature.create` domain command를 고친다.
새 public/provider 경로, PinVi 직접 생성, curation 동시 생성, provider 발행 뒤 병합 판정은 각각
M02~M05에서 다룬다.

## 2. 요구사항과 위험 등급

| 등급 | 반드시 반영할 요구사항 / 위험 | M00 GO 기준 |
|---|---|---|
| P0 | 서버가 구분할 수 없는 origin을 영구 기록하면 이후 복구가 불가능하다. | M01 origin은 `manual_admin` 단일 값이고, body/header로 `manual_pinvi`·`manual_curation`을 받지 않는다. |
| P0 | HTTP replay key를 entity natural key로 쓰면 같은 실체를 새 UUID마다 만들 수 있다. | `Idempotency-Key`와 manual natural key가 분리되어 있고, natural key는 서버 정규화 산출물이다. |
| P0 | 같은 실체 중복을 application precheck만으로 막으면 동시 생성에서 깨진다. | exact duplicate는 unique constraint, fuzzy duplicate는 lock+procedure guard+409 테스트로 막는다. |
| P0 | 새 DB CHECK/UNIQUE/serialization error가 HTTP 500으로 새면 admin UI/PinVi가 복구할 수 없다. | 모든 새 SQLSTATE/constraint가 409/422로 allow-list 매핑되고 역방향 fail-close 테스트가 있다. |
| P1 | `transition_kind='initial'` 의미를 origin으로 확장하면 기존 fixture와 provider initial create가 깨진다. | state audit은 `initial`을 유지하고 origin은 별도 relation이 소유한다. |
| P1 | current migration만 바꾸면 `contracts/vnext` freeze가 거짓 정본이 된다. | freeze DDL/fingerprint/violation/expected/test sha를 같은 M01 PR에서 갱신한다. |
| P1 | published 기본값을 draft로 바꾸면 기존 admin 승인·PinVi 후보 노출 흐름이 조용히 후퇴한다. | 기본값은 `active/published/valid` 유지, 단 `published`에는 좌표와 region을 요구한다. |
| P2 | manual origin table을 public DTO에 즉시 노출하면 M02 product 결정을 앞지른다. | M01은 write-side 보존만 하고 read/API 노출은 M02 결정으로 남긴다. |
| P2 | 좌표 fuzzy window는 같은 건물/단지 안 다중 POI를 과차단할 수 있다. | M01은 100m 이내를 자동 병합하지 않고 409로 admin 판단을 요구한다. |
| P3 | 기존 `docs/architecture/rest-api.md`의 `user_request` 설명이 M01 후 drift가 된다. | M01 PR에서 해당 절을 ADR-093 규칙으로 교체하고 OpenAPI를 재생성한다. |

## 2. 1차 초안 붕괴 항목 반영

### 2.1 origin은 M01에서 `manual_admin` 하나만 발급한다

현재 admin BFF와 PinVi는 같은 endpoint, 같은 proxy 인증 경계, 검증 없는 actor header를 쓴다.
서버가 `manual_admin`과 `manual_pinvi`를 구별할 신호가 없다. 따라서 M01은 origin domain에
`manual_pinvi`와 `manual_curation` 값을 추가하지 않는다.

M01의 생성 origin은 항상 `manual_admin`이다. PinVi 요청 origin은 별도 route 또는 별도
운영 권한 scope가 생긴 M04에서만 추가한다. curation 중 자동 생성 origin도 T-VN-40 인수 뒤 M03의
별도 command에서만 추가한다.

### 2.2 `Idempotency-Key`는 자연키가 아니다

HTTP `Idempotency-Key`는 ADR-074의 replay key다. 같은 actor가 같은 요청을 재전송했을 때 최초
terminal 결과를 재생할 뿐, 같은 실체를 두 번 만드는 것을 막는 source natural key가 아니다.

M01은 body의 `idempotency_key`를 `source_natural_key`로 쓰지 않는다. 명시 `feature_id`도 admin
create body에서 거부한다. `feature_id`는 서버가 다음 입력으로만 만든다.

```text
make_feature_id(
  bjd_code=<10자리 legal_dong_code 또는 None>,
  kind=<kind>,
  category=<category>,
  source_type="manual_admin",
  source_natural_key=<manual natural key v1>
)
```

`manual natural key v1`은 서버 정규화 산출물이다.

```text
manual-admin-v1::<region_key>::<kind>::<category>::<normalized_name>::<coord_cell_key>
```

- `normalized_name`: NFKC, trim, 내부 공백 1칸, 한글 정규화와 같은 규칙.
- `region_key`: `legal_dong_code`가 있으면 그것, 없으면 `sigungu_code`, 없으면 `global`.
- `coord_cell_key`: 좌표가 있으면 EPSG:5179 기준 100m grid key, 없으면 `no_coord`.
- `published` 생성은 좌표와 `legal_dong_code` 또는 `sigungu_code`가 필수다.
  좌표 없는 Feature는 `draft` 또는 `suppressed`까지만 허용한다.

`make_feature_id`의 `bjd_code`에는 10자리 법정동코드만 넣는다. `sigungu_code`와 `global`은
`source_natural_key`의 `region_key`에는 들어가지만 legacy `feature_id` prefix에는 넣지 않는다.
법정동코드가 없으면 `bjd_code=None`으로 호출해 `f_global_*` prefix를 쓰고, 지역 차이는 digest 입력인
`source_natural_key`가 담당한다.

### 2.3 중복 방지는 side relation + serializable command가 함께 맡는다

M01은 `feature.features`에 origin 컬럼을 직접 늘리지 않고, 수동 생성 identity만 보존하는
side relation을 둔다.

```sql
CREATE TABLE feature.manual_feature_origins (
    feature_id text PRIMARY KEY
    feature_uuid uuid NOT NULL,
    FOREIGN KEY (feature_id, feature_uuid)
        REFERENCES feature.features(feature_id, feature_uuid) ON DELETE RESTRICT,
    origin text NOT NULL CHECK (origin = 'manual_admin'),
    source_type text NOT NULL CHECK (source_type = 'manual_admin'),
    source_natural_key text NOT NULL,
    kind text NOT NULL,
    category text NOT NULL,
    region_key text NOT NULL,
    normalized_name text NOT NULL,
    coord x_extension.geometry(Point, 4326),
    coord_5179 x_extension.geometry(Point, 5179),
    coord_cell_key text NOT NULL,
    command_id bigint NOT NULL
        REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_manual_feature_origin_key UNIQUE (origin, source_natural_key),
    CONSTRAINT uq_manual_feature_region_name_cell UNIQUE (
        origin, kind, category, region_key, normalized_name, coord_cell_key
    )
);

CREATE INDEX idx_manual_feature_origins_region_name
    ON feature.manual_feature_origins (origin, kind, category, region_key, normalized_name);

CREATE INDEX idx_manual_feature_origins_coord_5179
    ON feature.manual_feature_origins
    USING gist (coord_5179)
    WHERE coord_5179 IS NOT NULL;
```

table 직접 DML은 runtime에 주지 않는다. `feature.register_manual_feature_origin(...)`
security-definer procedure만 실행한다.

Procedure는 다음 순서를 지킨다.

1. `ops.domain_commands`에서 `command_id`가 `admin.feature.create`이고 actor가 요청 actor와 같은지
   잠가 확인한다.
2. `pg_advisory_xact_lock(hashtextextended('manual-feature:' || origin || ':' || region_key || ':' ||
   normalized_name, 0))`를 잡아 같은 이름·지역 생성 precheck를 직렬화한다.
3. 기존 `manual_feature_origins`에서 같은 region/name/category이고 좌표가 100m 이내인 행을 찾으면
   `23514 / ck_manual_feature_duplicate_window`로 거부한다.
4. `manual_feature_origins`를 INSERT한다. exact duplicate는 unique constraint가 막는다.
5. 같은 transaction에서 subtype write와 field override authoring이 이어진다. 어느 단계든 실패하면
   core Feature와 origin row가 함께 rollback된다.

`coord_5179`는 generated column으로 두지 않는다. M01 procedure가 입력 좌표를 한 번만
`x_extension.ST_Transform`해 저장한다. 이렇게 해야 generated column의 volatility 제약에 기대지 않고,
spatial predicate에서는 indexed column 쪽에 `ST_Transform`을 걸지 않는 규칙을 지킬 수 있다.

`admin.feature.create`의 command policy는 `transaction_isolation="serializable"`로 올린다. 기존
domain command service는 serializable 40001을 최대 3회 재시도하므로, M01은 마지막 40001이
HTTP 500으로 새지 않도록 route-level mapping도 추가한다.

### 2.4 DB constraint는 HTTP 의미로 반드시 매핑한다

M01에서 새로 생기는 constraint/procedure error는 allow-list로 분류한다.

| SQLSTATE / constraint | HTTP | 의미 |
|---|---:|---|
| `23505 / uq_manual_feature_origin_key` | 409 | 같은 manual natural key 이미 존재 |
| `23505 / uq_manual_feature_region_name_cell` | 409 | 같은 region/name/category/cell 이미 존재 |
| `23514 / ck_manual_feature_duplicate_window` | 409 | 같은 region/name/category에서 100m 이내 후보 존재 |
| `23514 / ck_manual_feature_origin_payload` | 422 | origin payload 자체가 잘못됨 |
| `23514 / ck_manual_feature_published_location` | 422 | published인데 좌표 또는 region 없음 |
| `40001` 최종 실패 | 409 | 동시 생성 경쟁, 재조회 후 재시도 필요 |

라우터 테스트는 DB 예외 타입이 아니라 최종 HTTP status와 problem code를 단언한다. 통합 테스트는
실제 constraint 이름을 단언한다. 또한 `feature.features`와 `feature.manual_feature_origins`에서
M01 create 경로가 사용할 모든 새 constraint 이름이 라우터 매핑 집합에 포함되는 역방향
fail-close 테스트를 만든다.

### 2.5 `transition_kind='initial'`은 유지한다

`feature.feature_state_transitions.transition_kind`는 닫힌 enum이고 기존 fixture들이
`initial`을 사용한다. M01은 manual origin을 `transition_kind`에 넣지 않는다. initial state audit은
기존처럼 `transition_kind='initial'`, `reason_code='admin_feature_create'`,
`principal=<authenticated actor>`, `causation_ref='domain-command:<id>'`를 쓴다.

Origin 정본은 `manual_feature_origins`가 소유한다. M02는 이 relation을 확장하거나 별도
origin relation으로 승격해 `manual_pinvi`와 `manual_curation`까지 불변 보존한다.

### 2.6 freeze artifact를 실제 schema와 같이 움직인다

M01은 current migration만 고치면 안 된다. 다음을 같은 PR에 포함한다.

- `contracts/vnext/target-schema-v1.sql`
- `contracts/vnext/target-schema-fingerprints-v1.json`의 4축 fingerprint
- `contracts/vnext/violation-fixtures-v1.sql`
- `contracts/vnext/expected-rejections-v1.json`
- `tests/unit/test_vnext_contract_artifacts.py` sha256 상수
- `tests/integration/test_vnext_target_freeze.py`의 새 rejection/constraint 단언

Freeze suite가 current migration drift를 자동으로 잡지 못한다는 점이 1차 리뷰의 핵심 실패였으므로,
M01 PR 본문에는 "current migration DDL"과 "freeze DDL"의 같은 변경 항목을 나란히 적는다.

## 3. M01 구현 경계

### 3.1 수정 파일 후보

| 영역 | 파일 |
|---|---|
| ADR | `docs/adr/093-manual-feature-origin-and-identity.md` |
| migration | 새 `alembic/versions/0224+...` 또는 T-VN-40C 착지 뒤 다음 번호 |
| API router | `packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_features.py` |
| repo | `src/kortravelmap/infra/admin_feature_repo.py` |
| command registry | `packages/kor-travel-map-api/src/kortravelmap/api/domain_command_registry.py` |
| runtime preflight | `src/kortravelmap/infra/db.py` |
| OpenAPI | `packages/kor-travel-map-api/openapi*.json` |
| freeze | `contracts/vnext/*`, `tests/integration/test_vnext_target_freeze.py` |
| tests | `packages/kor-travel-map-api/tests/test_admin_features_router.py`, `tests/integration/test_admin_feature_repo.py`, `tests/integration/test_alembic_upgrade.py` |

### 3.2 route contract

- `POST /v1/admin/features`는 `Idempotency-Key` header를 계속 요구한다.
- body `operator`는 계속 무시한다.
- body `feature_id`는 신규 manual create에서는 `422`다.
- body `idempotency_key`는 제거하거나 deprecated ignored로 바꾸고, source natural key에 참여하지
  않는다.
- default state는 기존 승인 흐름 회귀를 막기 위해 `active/published/valid`를 유지한다.
- `lifecycle_state='retired'` create는 거부한다. 생성 직후 숨김이 필요하면 `publication_state='draft'`
  또는 `suppressed`를 쓴다.
- `published`는 좌표와 region을 요구한다.

정상 응답은 현행 `AdminFeatureFieldOverrideResponse` envelope를 유지한다. 최초 성공과 replay 모두
body schema는 같다. replay는 ADR-074 공통 처리에 따라 저장된 HTTP status와 `ETag`를 재생하고,
`Idempotency-Replayed: true` header만 추가한다.

```http
HTTP/1.1 200 OK
ETag: "feature-row-revision:1"
Content-Type: application/json
```

```json
{
  "data": {
    "feature_id": "f_1111010100_p_0123456789abcdef",
    "row_revision": 1,
    "command_id": 12345,
    "applied_field_count": 8
  },
  "meta": {
    "duration_ms": 12,
    "request_id": "018f2e3c-0000-7000-8000-000000000001"
  }
}
```

대표 실패 응답은 중복 생성이다. `Idempotency-Key` 재사용 오류는 ADR-074 공통 `409`를 그대로 쓴다.

```http
HTTP/1.1 409 Conflict
Content-Type: application/problem+json
```

```json
{
  "type": "https://kor-travel-map/errors/manual-feature-duplicate",
  "title": "같은 수동 Feature가 이미 존재합니다.",
  "status": 409,
  "detail": "같은 region/name/category/coord 기준의 수동 Feature가 이미 존재합니다.",
  "code": "MANUAL_FEATURE_DUPLICATE",
  "request_id": "018f2e3c-0000-7000-8000-000000000002",
  "errors": [
    {
      "loc": ["body", "name"],
      "msg": "중복 후보 feature_id=f_1111010100_p_0123456789abcdef",
      "type": "duplicate"
    }
  ]
}
```

### 3.3 권한과 lock 순서

`feature.register_manual_feature_origin`은 fixed `search_path=pg_catalog`와 schema-qualified
PostGIS 함수를 쓴다. runtime role에는 procedure EXECUTE만 준다. table SELECT는 admin detail/read에
필요해지는 M02 전까지 주지 않는다.

Lock 순서는 다음으로 고정한다.

```text
ops.domain_commands claim row
→ manual identity advisory lock
→ feature.features INSERT
→ manual_feature_origins INSERT
→ subtype row INSERT
→ field override author procedure
```

중복 precheck에서 공간 조건을 쓰는 경우 입력 좌표만 CTE에서 5179로 한 번 변환하고,
predicate는 `manual_feature_origins.coord_5179`를 그대로 쓴다. indexed column에
`ST_Transform`을 걸지 않는다.

## 4. 검증 matrix

| 범주 | GO 기준 |
|---|---|
| replay | 같은 actor/key/body 재시도는 최초 200/409와 ETag를 replay한다 |
| exact duplicate | 서로 다른 Idempotency-Key로 같은 manual natural key 동시 생성 시 1건만 성공하고 나머지는 409 |
| fuzzy duplicate | 같은 region/name/category 100m 이내 후보는 serializable/advisory lock 아래 409 |
| auth/origin | admin BFF/PinVi 공통 endpoint에서 origin은 오직 `manual_admin`; 다른 origin 요청 필드는 없다 |
| state | `active/published/valid` 기본값 유지, retired create 거부, published location/region 누락 422 |
| error mapping | 새 23505/23514/40001이 500으로 새지 않고 409/422로 고정 |
| ACL | runtime raw table DML 42501, procedure EXECUTE만 허용, owner/search_path exact |
| freeze | current migration과 `contracts/vnext` artifact가 같은 object set을 서술 |
| OpenAPI | admin/user/service spec 재생성 및 PinVi vendor 필요 여부 기록 |
| rollback/recovery | migration 실패는 transaction rollback; 적용 뒤 문제는 forward fix 또는 fresh clone/reload, feature row bulk UPDATE 없음 |

## 5. 아직 M00에서 닫지 않는 것

- `manual_pinvi` origin: M04의 별도 auth boundary와 요청 큐가 필요하다.
- `manual_curation` origin: M03에서 curation command와 같은 transaction으로 만든다.
- provider가 같은 실체를 나중에 발행했을 때의 merge/keep/discard UI: M05.
- public response에 origin을 노출할지 여부: M02에서 origin 보존 정본과 함께 결정한다.

## 6. 리뷰 요청 기준

두 전문 리뷰어는 다음 질문에 모두 GO해야 한다.

1. `Idempotency-Key`와 manual natural key가 섞이지 않았는가.
2. origin을 구별할 수 없는 경로에서 `manual_pinvi`/`manual_curation`이 영구 기록되지 않는가.
3. exact/fuzzy duplicate가 READ COMMITTED check-then-act에 의존하지 않는가.
4. 새 DB error가 HTTP 500으로 새는 경로가 없는가.
5. current migration, freeze artifact, OpenAPI, PinVi vendor 판단이 같은 PR에 묶였는가.
6. runtime role이 raw DML 권한 없이 procedure-only 경계를 유지하는가.
