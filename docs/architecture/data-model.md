# data-model.md — PostgreSQL + PostGIS 스키마 reference

이 문서는 `kor-travel-map` v2의 데이터 모델 reference다. 모든 컬럼/인덱스/
CHECK constraint가 여기에 박혀 있고, Alembic migration 작성 시 본 문서를 기준으로
한다. 인덱스 설계 근거는 `docs/architecture/performance.md`와 ADR을 참고한다.

## 0. 공통

- **DB**: PostgreSQL 16
- **확장**: `postgis`, `postgis_topology`, `pg_trgm`, `pgcrypto`
  → 모두 `x_extension` schema에 설치 (ADR-008). `search_path = public, x_extension`.
- **schema 분리**:
  - `feature` — feature 도메인 본체
  - `provider_sync` — source 추적과 sync state
  - `ops` — 운영 (작업 큐, 검수, 정합성 위반)
  - `x_extension` — 확장
- **시간**: 모두 `TIMESTAMPTZ` (KST 저장 권장). `created_at`, `updated_at` 표준.
  모든 feature와 관련 데이터는 API에서 KST aware `last_updated_at`을 반환할 수
  있어야 한다. 기존 row에 `updated_at`이 없으면 `imported_at`/`observed_at`/
  `valid_at`으로 임시 계산하되, 운영 API 확장 시 `updated_at` 추가를 우선 검토한다.
- **JSON**: PostgreSQL `JSONB` 강제. `JSON` 타입 사용 금지.
- **좌표계**: WGS84 (EPSG:4326) 외 EPSG:5179 (UTM-K, meter)를 동시 보유.
  반경 검색은 항상 EPSG:5179 (ADR-012).
- **PK 명명**: `feature_id`, `source_record_key`, `job_id` 등 의미 있는 prefix.
  raw UUID 단독 사용은 `dedup_review_queue`, `import_jobs` 같은 운영 테이블에만.
- **외래키 정책**: 도메인 cascade 명시 — `source_links.feature_id ON DELETE CASCADE`,
  `source_links.source_entity_key ON DELETE RESTRICT`,
  `curation_items.feature_id ON DELETE SET NULL`,
  `feature_files.source_record_key ON DELETE SET NULL` 등.

### 0.1 vNext 목표 모델과 현행 경계

아래 §1~12의 DDL은 현재 `main` 구현 reference다. vNext 목표는 ADR-067~075와
[`postgres-schema.md`의 vNext 목표](postgres-schema.md#vnext-목표-schema-미구현-재설계-정본-3)가 정본이며,
T-VN-31 이후 shadow migration으로 전환한다.

| 직교 책임 | vNext 정본 | 관련 결정 |
|---|---|---|
| identity | UUID Feature PK + provider natural UNIQUE + legacy alias | ADR-068 |
| publication | lifecycle/publication/quality 3축 + `public_features` | ADR-067 |
| lineage | DB-owned provider dataset → source entity → immutable record/head | ADR-069 |
| subtype | 작은 Feature core + typed point/event/notice/route/area table과 geometry/category 제약 | ADR-070 |
| 수동 보정 | provider base + field override + effective projection; whole-row freeze 없음 | ADR-071 |
| weather | `target_at`/`known_at` bitemporal fact + semantic UNIQUE/FK/range + current summary | ADR-072 |
| 쓰기 | resource revision, domain replay ledger, generation/restore epoch, outbox | ADR-074 |

각 축은 다른 축의 상태나 payload를 복제하지 않는다. JSONB는 원문·확장 metadata에만 사용하고,
kind/geometry/category/상태/시간 범위처럼 query와 무결성에 필요한 값은 typed column과 FK/CHECK로
표현한다. 보관 기간은 기존 정책을 유지하지만 보관 여부를 공개 상태로 대신 표현하지 않는다.

### 0.2 feature search cursor는 stateless REST 상태

`/v1/features/search`의 query fingerprint, keyset, version, HMAC은 요청과 응답 사이의 짧은 REST
전송 상태이며 PostgreSQL 도메인 상태가 아니다. cursor table, session row, 만료 row, sequence를
추가하지 않는다. 검색 SQL은 cursor에서 검증된 keyset만 bind하고, `include_total=false`에서는
COUNT SQL을 실행하지 않는다. 서버 재시작을 넘어 cursor를 유지해야 하는 production은 별도
server-only signing secret을 배포해 stateless 검증하며, key rotation 때 진행 중 cursor가
무효화되는 clean cut을 허용한다.

## 1. `feature.features` (기준 테이블)

```sql
CREATE TABLE feature.features (
  feature_id                   TEXT PRIMARY KEY,
  kind                         TEXT NOT NULL,            -- FeatureKind enum
  name                         TEXT NOT NULL,
  category                     TEXT NOT NULL,            -- PlaceCategoryCode value

  -- 좌표 (양 좌표계 보유, ADR-012)
  coord                        geometry(Point, 4326),
  coord_precision_digits       SMALLINT,               -- 원천 좌표 precision, coord 있으면 3~8
  coord_5179                   geometry(Point, 5179)
    GENERATED ALWAYS AS (
      CASE WHEN coord IS NULL THEN NULL
           ELSE ST_Transform(coord, 5179)
      END
    ) STORED,
  -- 선·면 geometry는 core에 없다 — route/area subtype이 정본 (§6, ADR-086)

  -- 주소 (kortravelmap.dto.Address 직렬화)
  address                      JSONB NOT NULL DEFAULT '{}'::jsonb,
  legal_dong_code              CHAR(10),
  road_name_code               TEXT,
  road_address_management_no   TEXT,
  admin_dong_code              CHAR(10),
  sido_code                    CHAR(2),
  sigungu_code                 CHAR(5),

  -- 표시
  urls                         JSONB NOT NULL DEFAULT '{}'::jsonb,
  marker_icon                  TEXT,
  marker_color                 TEXT,                     -- 'P-01' ~ 'P-16'

  -- 관계
  parent_feature_id            TEXT REFERENCES feature.features(feature_id) ON DELETE SET NULL,
  sibling_group_id             UUID,

  -- 상세
  -- kind별 detail도 core에 없다 — typed subtype이 정본이고, 응답이 요구하는
  -- detail/geom은 feature.features_detailed 뷰가 조립한다 (§6, ADR-086)
  raw_refs                     JSONB NOT NULL DEFAULT '[]'::jsonb,
  status                       TEXT NOT NULL DEFAULT 'active',      -- FeatureStatus enum

  -- effective row 출처/version (provider reload vs 사용자 요청)
  data_origin                  TEXT NOT NULL DEFAULT 'provider',    -- provider / user_request
  data_version                 INTEGER NOT NULL DEFAULT 0,          -- provider=0, user_request=1
  user_change_kind             TEXT,                                -- add / update / delete
  user_change_status           TEXT,                                -- pending / applied / rejected
  user_change_request_id       UUID,
  user_deleted_at              TIMESTAMPTZ,
  user_deleted_by              TEXT,
  user_change_reason           TEXT,

  created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at                   TIMESTAMPTZ,

  CONSTRAINT uq_features_identity_kind UNIQUE (feature_id, kind),  -- subtype 배타 arc의 참조 대상 (ADR-086)
  CONSTRAINT ck_features_kind   CHECK (kind IN ('place','event','notice','price','weather','route','area')),
  CONSTRAINT ck_features_status CHECK (status IN ('draft','active','inactive','hidden','broken','deleted')),
  CONSTRAINT ck_features_data_origin CHECK (data_origin IN ('provider','user_request')),
  CONSTRAINT ck_features_data_version CHECK (data_version >= 0),
  CONSTRAINT ck_features_user_change_kind CHECK (
    user_change_kind IS NULL OR user_change_kind IN ('add','update','delete')
  ),
  CONSTRAINT ck_features_user_change_status CHECK (
    user_change_status IS NULL OR user_change_status IN ('pending','applied','rejected')
  ),
  CONSTRAINT ck_features_coord_pair CHECK (
    coord IS NULL OR (
      ST_X(coord) BETWEEN 124.0 AND 132.0 AND ST_Y(coord) BETWEEN 33.0 AND 39.5
    )
  ),
  CONSTRAINT ck_features_coord_precision CHECK (
    (coord IS NULL AND coord_precision_digits IS NULL)
    OR (coord IS NOT NULL AND coord_precision_digits BETWEEN 3 AND 8)
  )
);

CREATE FUNCTION feature.set_feature_coord_precision() RETURNS trigger AS $$
BEGIN
  IF NEW.coord IS NULL THEN
    NEW.coord_precision_digits := NULL;
  ELSIF NEW.coord_precision_digits IS NULL THEN
    NEW.coord_precision_digits := 6;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_features_coord_precision
  BEFORE INSERT OR UPDATE OF coord, coord_precision_digits
  ON feature.features
  FOR EACH ROW
  EXECUTE FUNCTION feature.set_feature_coord_precision();

-- 표준 인덱스 (성능 설계 — docs/architecture/performance.md 참고)
CREATE INDEX idx_features_coord_gist        ON feature.features USING GIST (coord)       WHERE deleted_at IS NULL;
CREATE INDEX idx_features_coord_5179_gist   ON feature.features USING GIST (coord_5179)  WHERE deleted_at IS NULL;
CREATE INDEX idx_features_kind_category     ON feature.features (kind, category)         WHERE deleted_at IS NULL;
CREATE INDEX idx_features_status_updated    ON feature.features (status, updated_at);
CREATE INDEX idx_features_dedup_refresh_keyset
  ON feature.features (updated_at DESC, feature_id DESC)
  WHERE deleted_at IS NULL AND status='active' AND coord IS NOT NULL;
CREATE INDEX idx_features_legal_dong_code   ON feature.features (legal_dong_code);
CREATE INDEX idx_features_sigungu           ON feature.features (sigungu_code, kind)     WHERE deleted_at IS NULL;
CREATE INDEX idx_features_parent            ON feature.features (parent_feature_id)      WHERE parent_feature_id IS NOT NULL;
CREATE INDEX idx_features_sibling           ON feature.features (sibling_group_id)       WHERE sibling_group_id IS NOT NULL;
CREATE INDEX idx_features_name_trgm         ON feature.features USING GIN (name x_extension.gin_trgm_ops);
CREATE INDEX idx_features_data_origin       ON feature.features (data_origin, data_version);
CREATE INDEX idx_features_user_deleted      ON feature.features (user_deleted_at)        WHERE user_deleted_at IS NOT NULL;
```

**인덱스 설계 근거**:
- `coord_gist` — 응답 직렬화용 좌표 추출, in-bounds 빠른 필터링.
- `coord_5179_gist` — 반경 검색 핵심 인덱스 (ADR-012).
- `coord_precision_digits` — provider 원천 좌표 신뢰도/정밀도 신호. `Feature` DTO와
  trigger가 coord 보유 row의 기본값을 6으로 맞추고, coord 제거 시 NULL로 정리한다.
- `data_origin`/`data_version` — provider 재적재 snapshot은 version 0,
  사용자 요청 추가·수정·삭제는 version 1이다. `feature.features`는 조회용 effective
  row이고, snapshot 보존은 `feature.feature_versions`가 맡는다.
- `user_deleted_at` — 사용자 요청 soft delete marker. provider 재적재나 snapshot 미포함
  정리 작업은 이 값이 있는 row를 되살리지 않는다.
- `kind_category WHERE deleted_at IS NULL` — `/features/in-bounds` 주된 필터.
- `idx_features_dedup_refresh_keyset` — dedup refresh가 `(updated_at, feature_id)`
  keyset으로 진행하며 같은 앞부분만 반복 조회하지 않도록 한다.
- `name_trgm GIN` — pg_trgm 부분 문자열 검색 (검색 페이지).
- 진행중 행사/유효 공지, 선·면 geometry 필터는 core가 아니라 §6의 subtype 인덱스가 맡는다.
- `uq_features_identity_kind` — 그 자체로는 아무 것도 강제하지 않고, subtype의 복합 FK가
  참조할 수 있게 만드는 전제다 (§6).

### 1.1 `feature.feature_versions`

provider 적재와 사용자 요청 변경 snapshot을 feature별 version으로 보존한다.
`feature.features`는 조회용 effective row다. provider 재적재는 version 0 snapshot을
갱신하고, 사용자 요청이 적용되면 version 1 snapshot을 갱신한다.

```sql
CREATE TABLE feature.feature_versions (
  feature_id   TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  version      INTEGER NOT NULL,
  origin       TEXT NOT NULL,          -- provider / user_request
  change_kind  TEXT NOT NULL,          -- load / add / update / delete
  payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
  request_id   UUID,
  created_by   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (feature_id, version),
  CONSTRAINT ck_feature_versions_version CHECK (version >= 0),
  CONSTRAINT ck_feature_versions_origin CHECK (origin IN ('provider','user_request')),
  CONSTRAINT ck_feature_versions_change_kind CHECK (
    change_kind IN ('load','add','update','delete')
  )
);

CREATE INDEX idx_feature_versions_request
  ON feature.feature_versions (request_id);
```

우선순위 규칙:

- provider reload는 `version=0`, `origin='provider'`, `change_kind='load'`.
- 사용자 추가·수정·삭제는 `version=1`, `origin='user_request'`.
- 같은 `feature_id`에서 version 1이 effective row면 provider reload가 version 0
  snapshot만 갱신하고 effective row의 사용자 값을 덮지 않는다.
- 사용자 요청 삭제는 version 1 `change_kind='delete'`와 `feature.features` soft delete
  marker를 함께 남긴다.

### 1.2 `feature.curated_*` (테마형 overlay, T-223c-1/T-223c-2 구현)

테마형 큐레이션은 `feature.features`를 복제하지 않고 overlay로 관리한다. 정본 계약은
[`docs/curated-features.md`](../curated-features.md)다. DB schema는 `feature`에 둔다.
T-223c-1에서 Alembic `0025_curated_features`로 4개 테이블과 1차 seed metadata/rule을
추가했고, T-223c-2에서 Alembic `0026_curated_copy_snapshots`로 PinVi copy snapshot
cache를 추가했다.

테이블:

- `feature.curated_themes` — `theme_slug`, `theme_name`, `theme_group`,
  `default_curated`, `visibility`, 표시 metadata.
- `feature.curated_sources` — `provider`, `dataset_key`, `source_name`,
  `source_url`, `source_kind`, `license`, `update_cycle`,
  `last_source_modified_at`, `last_checked_at`, `next_expected_at`, `row_count`,
  `freshness_note`, `provider_status`, source metadata.
- `feature.curated_source_rules` — provider/dataset/category/place_kind 조건을
  `candidate`/`curated`/`ignore` 기본 action으로 매핑한다.
- `feature.curated_features` — `theme_id + feature_id` overlay 본체. 상태와
  PinVi 복사 정책을 저장한다.
- `feature.curated_pinvi_copy_snapshots` — Dagster가 materialize한 PinVi 복사용
  snapshot cache. `curated_feature_id` PK, `copy_version`, `etag`, `snapshot`,
  `materialized_at`, `updated_at`을 가진다.

핵심 상태:

- `curation_status`: `candidate` / `curated` / `rejected` / `archived`
- `selection_origin`: `source_rule` / `admin` / `external_api`
- `pinvi_relation`: `primary_stop` / `food_stop` / `cafe_stop` /
  `bookstore_stop` / `nearby_option` / `accessibility_support` / `pet_support` /
  `family_support` / `theme_area_anchor`

인덱스 기준:

- `UNIQUE (theme_id, feature_id) WHERE archived_at IS NULL`
- `INDEX (curation_status, updated_at DESC, curated_feature_id DESC)`
- `INDEX (theme_id, curation_status, rank_score DESC)`
- `INDEX (source_id, curation_status)`
- `INDEX (feature_id)`
- snapshot cache: `PRIMARY KEY (curated_feature_id)`,
  `INDEX (updated_at DESC, curated_feature_id DESC)`, `INDEX (etag)`

`rejected`/`archived` row는 provider 재적재나 source rule 재적용으로 되살리지 않는다.
PinVi는 REST snapshot을 읽어 `app.curated_trip_plans` /
`app.curated_plan_pois`로 복사하며, kor-travel-map DB에 직접 접근하지 않는다.

### 1.3 `feature.curation_*` (ADR-063, alembic 0045·0065·0066·0072)

공식 목록·회차·캠페인처럼 하나의 Feature가 여러 큐레이션 사실을 동시에 가질 수 있는
데이터는 collection과 membership을 분리한다. 기존 `feature.curated_features`의 source-rule
자동 후보화 표면은 유지하지만, 신규 공식·수동 큐레이션의 정본은 아래 두 테이블이다.
0065 이후 legacy projection용 collection key는
`legacy:<theme UUID>:<source UUID>:<md5(title)>`이며 mutable `theme_slug`를 identity로 쓰지 않는다.
같은 semantic group의 복수 collection은 상태를 강제 병합하지 않고
`:split:<collection_id>` suffix로 각각 보존한다. 수동 collection이 base key를 선점한 runtime
신규 projection은 projection UUID별로 분절하지 않고 group-shared `:split:legacy` fallback을
사용하며, 그 key도 선점됐으면 충돌 없는 `:conflict:<n>`을 선택한다.

```sql
CREATE TABLE feature.curation_collections (
  collection_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  collection_key TEXT NOT NULL UNIQUE,
  theme_id UUID NOT NULL REFERENCES feature.curated_themes(theme_id) ON DELETE RESTRICT,
  source_id UUID REFERENCES feature.curated_sources(source_id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  edition_key TEXT NOT NULL DEFAULT '',
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',          -- draft / published / archived
  visibility TEXT NOT NULL DEFAULT 'admin_only', -- admin_only / public
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by TEXT,
  updated_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  archived_at TIMESTAMPTZ,

  CONSTRAINT ck_curation_collections_key CHECK (btrim(collection_key) <> ''),
  CONSTRAINT ck_curation_collections_title CHECK (btrim(title) <> ''),
  CONSTRAINT ck_curation_collections_status
    CHECK (status IN ('draft','published','archived')),
  CONSTRAINT ck_curation_collections_visibility
    CHECK (visibility IN ('admin_only','public')),
  CONSTRAINT ck_curation_collections_metadata
    CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE feature.curation_items (
  curation_item_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  collection_id UUID NOT NULL
    REFERENCES feature.curation_collections(collection_id) ON DELETE CASCADE,
  feature_id TEXT REFERENCES feature.features(feature_id) ON DELETE SET NULL,
  source_record_key TEXT
    REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  legacy_projection_id UUID
    REFERENCES feature.curated_features(curated_feature_id)
    DEFERRABLE INITIALLY DEFERRED,
  current_import_row_id UUID,
  accepted_link_decision_id UUID,
  external_item_id TEXT NOT NULL,
  external_component_id TEXT NOT NULL DEFAULT 'primary',
  place_name TEXT NOT NULL,
  address_hint TEXT,
  source_present BOOLEAN NOT NULL DEFAULT true,
  source_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'candidate',
  sort_order INTEGER NOT NULL DEFAULT 0,
  item_title TEXT,
  item_summary TEXT,
  curation_relation TEXT NOT NULL DEFAULT 'nearby_option',
  reuse_policy TEXT NOT NULL DEFAULT 'manual_review',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by TEXT,
  updated_by TEXT,
  operator_updated_by TEXT,
  operator_updated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  archived_at TIMESTAMPTZ,

  CONSTRAINT ck_curation_items_external_id CHECK (btrim(external_item_id) <> ''),
  CONSTRAINT ck_curation_items_external_component_id_canonical CHECK (
    external_component_id <> ''
    AND external_component_id = btrim(external_component_id)
  ),
  CONSTRAINT ck_curation_items_place_name CHECK (btrim(place_name) <> ''),
  CONSTRAINT ck_curation_items_status
    CHECK (status IN ('candidate','included','rejected','archived')),
  CONSTRAINT ck_curation_items_sort_order CHECK (sort_order >= 0),
  CONSTRAINT ck_curation_items_relation CHECK (
    curation_relation IN (
      'primary_stop','food_stop','cafe_stop','bookstore_stop','nearby_option',
      'accessibility_support','pet_support','family_support','theme_area_anchor'
    )
  ),
  CONSTRAINT ck_curation_items_reuse_policy
    CHECK (reuse_policy IN ('allowed','blocked','manual_review')),
  CONSTRAINT ck_curation_items_metadata CHECK (jsonb_typeof(metadata) = 'object')
);

ALTER TABLE feature.curation_items
  ADD CONSTRAINT uq_curation_items_component_identity
  UNIQUE (collection_id, external_item_id, external_component_id);
CREATE UNIQUE INDEX uq_curation_items_active_source_feature
  ON feature.curation_items (collection_id, external_item_id, feature_id)
  WHERE source_present AND archived_at IS NULL AND feature_id IS NOT NULL;
CREATE UNIQUE INDEX uq_curation_items_legacy_projection_id
  ON feature.curation_items (legacy_projection_id)
  WHERE legacy_projection_id IS NOT NULL;
CREATE INDEX idx_curation_collections_theme_status_edition
  ON feature.curation_collections (theme_id, status, edition_key, collection_id);
CREATE INDEX idx_curation_collections_source_status
  ON feature.curation_collections (source_id, status, collection_id);
CREATE INDEX idx_curation_items_collection_status_order
  ON feature.curation_items
    (collection_id, source_present, status, sort_order, curation_item_id);
CREATE INDEX idx_curation_items_feature_status_collection
  ON feature.curation_items
    (feature_id, source_present, status, collection_id);

CREATE TABLE feature.curation_import_batches (
  import_batch_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  batch_kind TEXT NOT NULL
    CHECK (batch_kind IN ('csv_upload','normalized_rows','forward_recovery')),
  row_count INTEGER NOT NULL CHECK (row_count >= 0),
  actor TEXT NOT NULL CHECK (actor = btrim(actor) AND actor <> ''),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE feature.curation_import_rows (
  import_row_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  import_batch_id UUID NOT NULL
    REFERENCES feature.curation_import_batches(import_batch_id) ON DELETE RESTRICT,
  curation_item_id UUID NOT NULL
    REFERENCES feature.curation_items(curation_item_id) ON DELETE RESTRICT,
  row_number INTEGER NOT NULL CHECK (row_number > 0),
  source_row_sha256 TEXT NOT NULL CHECK (source_row_sha256 ~ '^[0-9a-f]{64}$'),
  row_payload JSONB NOT NULL,
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (import_batch_id, row_number),
  UNIQUE (import_row_id, curation_item_id)
);

CREATE TABLE feature.curation_link_decisions (
  decision_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  curation_item_id UUID NOT NULL
    REFERENCES feature.curation_items(curation_item_id) ON DELETE RESTRICT,
  feature_id TEXT NOT NULL,
  import_row_id UUID,
  decision_kind TEXT NOT NULL CHECK (decision_kind IN ('accepted','revoked')),
  match_basis TEXT NOT NULL CHECK (
    match_basis IN (
      'csv_explicit_feature_id','admin_review','legacy_unattributed',
      'forward_recovery'
    )
  ),
  resolver_version TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  actor TEXT NOT NULL,
  decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  supersedes_decision_id UUID,
  CHECK (supersedes_decision_id IS DISTINCT FROM decision_id),
  FOREIGN KEY (import_row_id, curation_item_id)
    REFERENCES feature.curation_import_rows(import_row_id, curation_item_id)
    ON DELETE RESTRICT,
  FOREIGN KEY (supersedes_decision_id, curation_item_id)
    REFERENCES feature.curation_link_decisions(decision_id, curation_item_id)
    ON DELETE RESTRICT,
  UNIQUE (decision_id, curation_item_id),
  UNIQUE (decision_id, curation_item_id, feature_id)
);

ALTER TABLE feature.curation_items
  ADD CONSTRAINT fk_curation_items_current_import_row
  FOREIGN KEY (current_import_row_id, curation_item_id)
  REFERENCES feature.curation_import_rows(import_row_id, curation_item_id)
  ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  ADD CONSTRAINT fk_curation_items_accepted_link_decision
  FOREIGN KEY (accepted_link_decision_id, curation_item_id, feature_id)
  REFERENCES feature.curation_link_decisions(
    decision_id, curation_item_id, feature_id
  )
  ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION feature.reject_curation_history_mutation()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
    USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_curation_import_batches_immutable
  BEFORE UPDATE OR DELETE ON feature.curation_import_batches
  FOR EACH ROW EXECUTE FUNCTION feature.reject_curation_history_mutation();
CREATE TRIGGER trg_curation_import_rows_immutable
  BEFORE UPDATE OR DELETE ON feature.curation_import_rows
  FOR EACH ROW EXECUTE FUNCTION feature.reject_curation_history_mutation();
CREATE TRIGGER trg_curation_link_decisions_immutable
  BEFORE UPDATE OR DELETE ON feature.curation_link_decisions
  FOR EACH ROW EXECUTE FUNCTION feature.reject_curation_history_mutation();
```

`feature_id`는 의도적으로 nullable이다. CSV의 공식 항목을 기존 Feature와 안전하게
확정하지 못해도 `place_name`·`address_hint`·원천 안정키를 보존하고, 이후 정확한 Feature가
확인되면 같은 component 행의 `feature_id`를 갱신한다. 좌표는 기존 `feature.features`에서만 읽으며
큐레이션 item이 별도 좌표를 소유하지 않는다. 같은 공식 복합 장소를 여러 Feature에 연결할
때는 `external_item_id`를 공유하고 각 membership에 안정된 `external_component_id`를 둔다.
component exact identity는 archived tombstone까지 포함해 DB unique로 한 행만 허용한다.
`feature_id`는 identity가 아니므로 null→연결·A→B 재연결에도 `curation_item_id`와 운영자
상태가 유지된다. 동일 source item의 active component가 같은 non-null Feature를 중복 참조하는
것은 source에 현재 존재할 때 partial unique가 막는다. source에서 빠진 이력 행은 동일
Feature를 참조하는 새 current component를 막지 않는다. 연결 component와 미연결 component의 공존은 복합 장소를
무손실로 나타내므로 허용한다.
`legacy_projection_id`는 전환기 `curated_features`와 durable item 관계의 정본이다.
`curation_item_id`가 우연히 legacy UUID와 같은지 추론하지 않으며, Feature merge로 canonical-only
item과 projection UUID를 분리해도 관계를 잃지 않는다.
0064의 mutable slug가 재사용된 collection에서 migration은 `legacy_projection_id`가 명시하는
projection owner만 자동 복구한다. canonical-only item은 원 projection durable link가 없고 external
identity도 theme 간 공유될 수 있으므로 exact pair처럼 보여도 owner를 추정하지 않는다. 모든
legacy-marker collection에서 원 payload와 identity를 유지한 `draft/admin_only` quarantine
collection으로 옮겨 명시적 재분류 대상으로 보존한다. 이전 projection 삭제로 mismatch row가 남지
않은 경우도 같다. 과거 admin PATCH가 mutable metadata marker를 지울 수 있었으므로 immutable
`legacy:` collection key namespace도 후보 판정에 함께 사용한다.
`quarantine:`은 과거 theme slug에서 예약되지 않았으므로 broad prefix는 제외하지 않는다.
exact `legacy:quarantine:<UUID>` key와 immutable `created_by='migration:0065'`가 모두 일치하는
migration 산출물만 제외해 왕복 때 빈 quarantine을 누적하거나 `original_collection_id`를 한
단계씩 밀지 않는다. mutable metadata에 `migrated_from`이 추가돼도 upgrade·downgrade key
rewrite가 같은 결합 증거를 제외한다.

collection과 item의 `created_by`/`updated_by`는 인증된 admin proxy actor만 기록한다.
수동 item 추가·수정·보관은 item과 parent collection의 `updated_by`/`updated_at`을 함께
갱신한다. public projection은 actor 필드를 제외하고 게시·공개 collection의 included
item 중 현재 target과 정확히 일치하는 non-legacy accepted decision이 있는 link만 반환한다.
미결정·`legacy_unattributed` link는 admin 감사 대상으로 남고 public에서는 fail-close한다.
admin collection/item projection은 actor 필드를 포함하고 collection
상세에서는 미연결·비공개·보관 item까지 조회할 수 있다.

import batch·row와 link decision은 immutable trigger가 `UPDATE`/`DELETE`를 거부하는
append-only history다. batch 삭제도 row를 cascade하지 않는다. 같은 파일의 멱등 재적재도
별도 receipt를 남기되 current pointer만 새 exact row/decision으로 전진한다. decision의
import row와 supersedes chain은 composite FK로 같은 item에만 속하며 self-supersede를
금지한다.

`forward_recovery`는 선택한 collection/item만 갱신하고 다른 pointer를 되감지 않는다.
Feature merge도 link를 무근거로 바꾸거나 item을 물리 삭제하지 않는다. 현재 decision이
non-legacy accepted인 active link만 master에 재승인한다. legacy/NULL/revoked link는
accepted pointer 없이 audit 대상으로 남는다. duplicate loser source projection이 이기면
survivor item 소유의 merge import row를 append해 current row payload와 projection을
일치시키고, loser는 revocation 뒤 feature 없는 archive tombstone으로 보존한다.
동일 external item의 source-absent 과거 component와 active component가 함께 있을 때는
external item별 canonical survivor/provider winner를 결정적 순서로 각각 하나만 선택한다.
충돌하는 loser current는 일반 move 전에 coalesce하고, 과거 component는 identity·provenance를
유지한 채 master history로 이동한다. 따라서 active
`(collection_id, external_item_id, feature_id)`는 merge 뒤에도 정확히 한 행이고 current
import row/decision은 실제 winner projection과 일치한다.

membership에는 서로 독립인 두 revision 축을 둔다. `source_updated_at`은 source presence와
제공자 파생 필드가 바뀐 시각이고, `operator_updated_at`/`operator_updated_by`는
`status`·`curation_relation`·`reuse_policy`를 마지막으로 바꾼 운영자 의도다. 일반
`updated_at`은 행 감사 시각일 뿐 merge winner 판정에 사용하지 않는다. 두 revision의
운영 중 쓰기는 PostgreSQL transaction 시작 시각인 `now()`가 아니라 실제 쓰기 순서를 나타내는
`clock_timestamp()`를 사용한다. migration backfill만 기존 행의 역사적 `updated_at`을 보존한다.

CSV commit은 파일이 언급한 collection을 한 transaction에서 authoritative replace한다.
0066 전 다중 membership의 `legacy:<UUID>` component는 source 누락 상태까지 포함해 첫 import에서 동일 source item·
동일 non-null Feature target의 incoming component로 원자적으로 identity를 승계한다.
이 경로도 UUID와 operator 필드·감사 이력을 보존하며 dry-run은 insert/removal이 아니라
update로 예고한다. `legacy_projection_id`를 가진 전환기 projection membership은 DB
BEFORE INSERT trigger가 신규 projection에만 projection UUID 기반 component를 부여하므로
authoritative import의 명시적 component 승계를 되감지 않는다. 구 flat writer가 같은 source
record를 여러 Feature에 투영해도 component identity를 공유하지 않는다.
보관된 legacy tombstone은 component key만 승계하고 provider/source/operator/archive 필드는
그대로 둔다. 따라서 preview와 commit 모두 신규 insert가 아니라 identity update로 보고하며
exact tombstone 재사용 금지 계약을 유지한다. 같은 source item·Feature target에 active·archived
legacy 후보가 둘 이상이면 어느 행의 UUID나 operator 이력을 승계할지 추정하지 않는다.
preview와 commit 모두 후보를 명시한 오류로 중단하며 membership을 변경하지 않는다.
theme upsert·collection create·authoritative import는 공통 transaction write-boundary advisory
lock을 가장 먼저 공유한다. 그 안에서 row 존재 전 stable collection key lock을 사용하고,
import는 여러 key를 정렬해 모두 확보한 뒤 Feature를 잠근다. 따라서 admin create의 theme→key,
import의 key→theme 역전이나 미커밋 create+add의 Feature↔collection 잠금 순환이 생기지 않는다.
incoming 안정키에 없는 기존 item은 물리 삭제하지 않고 `source_present=false`로 표시한다.
재등장하면 `source_present=true`와 제공자 파생 필드만 갱신하고, 운영자가 조정한
`status`·`curation_relation`·`reuse_policy`는 보존한다. 운영자가 보관한 정확한
`collection_id + external_item_id + external_component_id` identity는 tombstone으로 남아 같은 CSV가
재등장해도 자동 복원되지 않는다. 기본 admin/public 조회와 collection count는
`source_present=true`인 item만 포함하며, admin의 명시적 `include_archived` 조회는 source에서
사라진 행도 감사 목적으로 반환한다.

dry-run은 동일한 필드 비교 규칙으로 `inserted`/`updated`/`removed`와 source에서 사라질 item
전체를 미리 반환한다. API의 `removed` 의미는 물리 삭제 건수가 아니라 이번 authoritative
source에서 빠져 기본 projection에서 제외되는 건수다. 동일 파일 재업로드는 변경 수가 모두
0이며 theme/source/collection/item의 `updated_at`도 바꾸지 않는다.

동시 authoritative replace는
`pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0))`으로 직렬화한다.
그 직후 참조 active Feature를 정렬 잠근 다음 theme/source/collection을 만들거나 잠그고 item을
쓴다. 여러 대상 collection row도 UUID 정렬 순서로 `FOR UPDATE`하며, 수동 item write는 parent
collection을 먼저 잠가 import와 충돌하지 않게 한다. Feature merge는 master/loser Feature를
정렬 잠근 뒤 legacy→collection→item으로 진행한다. legacy trigger의 cross-title identity 조회는
target collection 뒤 source collection parent를 역순 잠그지 않고 item만 잠근다. 기존
`curated_features` writer는 0045 trigger가 collection item으로 동기화해 전환 중 두 표면이
갈라지지 않게 한다. 0065 이후 legacy writer의 UPDATE/DELETE도 물리 DELETE/INSERT를 하지
않는다. source presence와 제공자 파생 필드는 source revision만 전진시키고 operator
상태·relation·reuse는 별도 provenance가 전진한 경우에만 반영한다. canonical item의 운영자
수정도 같은 transaction에서 legacy row로 역동기화한다. legacy row가 DELETE 후 새 UUID로
재생성돼도 안정적인 `source_record_key` exact identity가 기존 source-absent membership을
복원한다. source record가 없는 projection도 theme/source/feature의 durable external identity를
재사용하며 archived tombstone은 되살리지 않는다. Feature merge가 충돌 해소를 위해 archive한
legacy projection은 제거할 수 없는 detached metadata를 남기고 canonical source에서 영구
분리한다. trigger-wide session bypass는 없으며 canonical UUID mirror 부재·same-theme master
존재·exact archive 전이를 DB가 확인한 경우에만 marker를 허용한다.

0065 downgrade는 `source_present=false`, operator provenance, non-direct legacy mapping 또는
detached marker가 하나라도 있으면 `P0001`로 중단한다. 이전 스키마는 source 누락·독립 revision·
분리 projection을 함께 표현할 수 없어 자동 삭제하면 override를 조용히 잃기 때문이다.
0066 downgrade는 같은 source item의 여러 component가 구
`collection_id + external_item_id + feature_id` identity로 충돌하면 mutation 전에 중단한다.
0045 downgrade도 구 `curated_features`에서
완전히 재구성할 수 있는 legacy 행만 허용한다.
신규 collection/item, 수동 변경, collection actor 또는 legacy `selected_by`와 일치하지 않는
item actor처럼 표현력이 더 큰 데이터가 있으면 PostgreSQL `P0001` 예외로 transaction 전체를
중단한다. 먼저 export 또는 명시적 정리하지 않은 데이터를 조용히 삭제하지 않는다.

0044 downgrade도 연결된 entity에 immutable source record가 둘 이상이면 `P0001`로
거절한다. entity link를 구 record별 link로 임의 복제하면 과거 role·confidence·생성 시각을
복원한 것처럼 보이면서 실제로는 데이터를 조작하게 되므로, 먼저 이력을 export하고 명시적으로
정리해야 한다.

## 2. `provider_sync.source_entities` / `provider_sync.source_records` (legacy, T-VN-33 이전)

> 아래 SQL은 Alembic 0087까지의 historical model이다. T-VN-33 cutover 뒤의 정본은
> ADR-087 및 `contracts/vnext/target-schema-v1.sql`이다. 최종형은
> `provider_datasets` FK identity, immutable `source_records`,
> `source_entity_heads(observed_at, expires_at)`, role-only `source_links`를 사용하며
> provider/dataset·current pointer·raw-derived·legacy primary boolean 열은
> `docs/removal-manifests/t-vn-33-source-lineage.md`에 따라 T-VN-39에서 제거한다.

provider 자연 entity의 identity와 변경 불가능한 payload 관측 이력을 분리한다(ADR-063,
alembic 0044). `source_entities`는 현재 record 포인터와 관측 수명을, `source_records`는
payload hash별 이력을 소유한다.

```sql
CREATE TABLE provider_sync.source_entities (
  source_entity_key TEXT PRIMARY KEY, -- se_ + sha256(provider|dataset|type|id)
  provider TEXT NOT NULL,
  dataset_key TEXT NOT NULL,
  source_entity_type TEXT NOT NULL,
  source_entity_id TEXT NOT NULL,
  current_source_record_key TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,

  CONSTRAINT uq_source_entities_identity UNIQUE (
    provider, dataset_key, source_entity_type, source_entity_id
  ),
  CONSTRAINT ck_source_entities_seen_order CHECK (first_seen_at <= last_seen_at)
);
```

`current_source_record_key`는 아래 `(source_entity_key, source_record_key)` 복합
외래키를 통해 반드시 같은 entity의 record만 가리킨다. 두 테이블의 상호 참조는
`DEFERRABLE INITIALLY DEFERRED`, 삭제는 `RESTRICT`다.

```sql
CREATE TABLE provider_sync.source_records (
  source_record_key      TEXT PRIMARY KEY,            -- make_source_record_key(...)
  source_entity_key      TEXT NOT NULL REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT,
  provider               TEXT NOT NULL,               -- canonical provider name
  dataset_key            TEXT NOT NULL,
  source_entity_type     TEXT NOT NULL,
  source_entity_id       TEXT NOT NULL,
  source_version         TEXT,
  raw_name               TEXT,
  raw_address            TEXT,
  raw_longitude          NUMERIC(12,8),
  raw_latitude           NUMERIC(12,8),
  raw_data               JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw_payload_hash       TEXT NOT NULL,
  fetched_at             TIMESTAMPTZ NOT NULL,
  imported_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at             TIMESTAMPTZ,

  CONSTRAINT uq_source_records UNIQUE (provider, dataset_key, source_entity_type, source_entity_id, raw_payload_hash),
  CONSTRAINT uq_source_records_entity_record UNIQUE (source_entity_key, source_record_key)
);

ALTER TABLE provider_sync.source_entities
  ADD CONSTRAINT fk_source_entities_current_record
  FOREIGN KEY (source_entity_key, current_source_record_key)
  REFERENCES provider_sync.source_records (source_entity_key, source_record_key)
  ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX idx_source_entities_current_record
  ON provider_sync.source_entities (current_source_record_key)
  WHERE current_source_record_key IS NOT NULL;
CREATE INDEX idx_source_records_provider_dataset_entity
  ON provider_sync.source_records (provider, dataset_key, source_entity_type, source_entity_id);
CREATE INDEX idx_source_records_entity_history
  ON provider_sync.source_records (
    source_entity_key, last_seen_at DESC, fetched_at DESC,
    imported_at DESC, source_record_key DESC
  );
CREATE INDEX idx_source_records_imported_at_brin
  ON provider_sync.source_records USING BRIN (imported_at);
CREATE INDEX idx_source_records_fetched_at_brin
  ON provider_sync.source_records USING BRIN (fetched_at);
CREATE INDEX idx_source_records_last_seen_at_brin
  ON provider_sync.source_records USING BRIN (last_seen_at);
CREATE INDEX idx_source_records_expires_at
  ON provider_sync.source_records (expires_at) WHERE expires_at IS NOT NULL;
```

**인덱스 설계**:
- `source_entities.current_source_record_key` — entity별 현재 관측을 record PK 조회로 연결한다.
- `source_records_entity_history` — entity별 과거 payload를 마지막 관측 시각 우선 cursor로
  조회한다. 같은 payload의 재관측도 현재성에 반영해 `A → B → A`를 정확히 표현한다.
- BRIN on `imported_at/fetched_at` — 적재 시계열 누적 패턴에 최적, 디스크 절약.
- partial on `expires_at IS NOT NULL` — purge job에서만 스캔.

### 2.1 `provider_sync.notice_lifecycle_scopes` / `notice_lineage_states`

짧은 수명의 notice는 source 관측 이력과 별도로 계보의 현재 상태를 영속화한다(Alembic
0046). scope는 `(provider, dataset_key, source_entity_type)`별 적용 방식과 watermark를,
member는 사건 계보별 `present` 전이를 저장한다.

```sql
CREATE TABLE provider_sync.notice_lifecycle_scopes (
  provider TEXT NOT NULL,
  dataset_key TEXT NOT NULL,
  source_entity_type TEXT NOT NULL,
  mode TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL,
  state_fingerprint TEXT NOT NULL,
  CONSTRAINT pk_notice_lifecycle_scopes PRIMARY KEY (
    provider, dataset_key, source_entity_type
  ),
  CONSTRAINT ck_notice_lifecycle_scopes_mode
    CHECK (mode IN ('snapshot', 'event'))
);

CREATE TABLE provider_sync.notice_lineage_states (
  provider TEXT NOT NULL,
  dataset_key TEXT NOT NULL,
  source_entity_type TEXT NOT NULL,
  lineage_key TEXT NOT NULL,
  present BOOLEAN NOT NULL,
  changed_at TIMESTAMPTZ NOT NULL,
  valid_until TIMESTAMPTZ,
  CONSTRAINT pk_notice_lineage_states PRIMARY KEY (
    provider, dataset_key, source_entity_type, lineage_key
  ),
  CONSTRAINT fk_notice_lineage_states_scope FOREIGN KEY (
    provider, dataset_key, source_entity_type
  )
    REFERENCES provider_sync.notice_lifecycle_scopes (
      provider, dataset_key, source_entity_type
    ) ON DELETE CASCADE
);
```

`snapshot` mode는 KREX처럼 전체 현재 목록을 제공하는 source에 쓴다. 정렬·중복 제거한
활성 계보 집합의 fingerprint와 `applied_at`을 CAS한다. 더 과거인 snapshot과 같은 시각의
다른 fingerprint는 거부하고, 같은 시각·같은 fingerprint는 멱등 replay로 허용한다. 빈
snapshot도 scope header를 남긴다. member의 `changed_at`은 `present`가 실제로 바뀔 때만
갱신한다.

`event` mode는 KMA처럼 발표·해제 event의 rolling window를 제공하는 source에 쓴다. scope
`applied_at`은 빈 batch도 포함해 `GREATEST`로 전진시키되, 계보 상태는 각 event의
`changed_at`을 기준으로 갱신한다. `present=true`의 `valid_until`은 KMA가 명시한 예정
종료시각이며, open-ended 발표와 명시 해제는 `NULL`이다. 같은 계보의 과거 event는 무시하고
같은 시각의 `present` 또는 `valid_until` 충돌은 거부하므로, 늦게 도착한 다른 계보 event를
batch watermark 때문에 버리지 않는다. DB에 저장된 최신 event와 정확히 일치하는
`present=true` bundle만 Feature/source current에 적재해 늦은 과거 발표가 본문을 되돌리지
못하게 한다.

0046은 기존 source entity를 backfill하지 않는다. member row가 없는 계보는 `unknown`이며
소멸 근거로 쓰지 않는다. notice 상태 적용은 전역 transaction advisory lock
`hashtextextended('kortravelmap:notice-snapshot-reconcile', 0)` 아래에서 bundle 적재, 상태
전이, 중복 정리, Feature 종료·재개를 한 transaction으로 처리한다. 여러 provider/dataset
계보가 한 Feature를 공유하면 계보별 구조적 winner를 전역으로 계산한다. open-ended
`present=true` winner가 하나라도 있으면 열고, finite present만 있으면 가장 늦은
`valid_until`까지 노출한다. `unknown` winner가 섞이면 이미 열린 종료시각을 줄이지 않으며,
명시 finite present가 더 오래 유효할 때만 연장한다. `unknown`만으로 닫힌 Feature를 다시
열지는 않는다. 모든 winner가 `false`일 때만 종료하며 `valid_end_time`은 그 winner들의
마지막 `changed_at`(최댓값)이다. scope/member 상태가 존재하는 0046 downgrade는 이 상태를
source row에서 무손실 복원할 수 없으므로 명시적으로 거부한다.

## 3. `provider_sync.source_links` (legacy, T-VN-33 이전)

```sql
CREATE TABLE provider_sync.source_links (
  feature_id           TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  source_entity_key    TEXT NOT NULL REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT,
  source_role          TEXT NOT NULL,                 -- SourceRole enum
  match_method         TEXT NOT NULL,                 -- 'natural_key', 'reverse_geocode', 'place_phone_search', ...
  confidence           NUMERIC(5,2) NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (feature_id, source_entity_key),
  CONSTRAINT ck_source_links_confidence CHECK (confidence BETWEEN 0 AND 100),
  CONSTRAINT ck_source_links_role CHECK (source_role IN (
    'base_address','base_coordinate','primary','enrichment','correction',
    'duplicate_candidate','media','weather_context'
  ))
);

CREATE INDEX idx_source_links_entity       ON provider_sync.source_links (source_entity_key);
CREATE INDEX idx_source_links_role         ON provider_sync.source_links (source_role);
CREATE INDEX idx_source_links_primary      ON provider_sync.source_links (feature_id)
  WHERE source_role = 'primary';
```

link는 payload version이 아니라 provider entity에 붙는다. 따라서 같은 entity의 payload가
바뀌어도 Feature link 수는 늘지 않는다. `source_role='primary'`는 Feature당 하나라는
제약이 없으며 MOIS와 MCST처럼 서로 다른 primary entity를 모두 보존한다. 기본 Feature 상세는
각 link의 `source_entities.current_source_record_key`를 따라 현재 관측 전부를 반환하고,
과거 payload는 entity별 이력 API에서만 조회한다.

## 4. `provider_sync.provider_sync_state`

실제 구현(alembic 0002 / `infra/models.py` `ProviderSyncStateRow`):

```sql
CREATE TABLE provider_sync.provider_sync_state (
  provider               TEXT NOT NULL,
  dataset_key            TEXT NOT NULL,
  sync_scope             TEXT NOT NULL,                  -- PK 구성요소 (DEFAULT 없음)
  status                 TEXT NOT NULL DEFAULT 'active',
  cursor                 JSONB NOT NULL DEFAULT '{}'::jsonb,  -- Step B 증분 진행 위치 (예: {"last_modified_date": "2026-06-01"}), infra/sync_state_repo.py 가 운영
  last_success_at        TIMESTAMPTZ,
  last_failure_at        TIMESTAMPTZ,
  consecutive_failures   INTEGER NOT NULL DEFAULT 0,
  next_run_after         TIMESTAMPTZ,
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (provider, dataset_key, sync_scope),
  CONSTRAINT ck_provider_sync_state_status
    CHECK (status IN ('active','paused','disabled','failed'))
);

CREATE INDEX idx_sync_state_next_run ON provider_sync.provider_sync_state
  (next_run_after) WHERE status='active';
```

> **후속 후보 (미구현)**: 초기 설계에 있던 `metadata_hash` /
> `last_observed_source_version` / `last_attempt_at` / `last_full_scan_at` /
> `last_error`/`last_error_at` / `extra`는 현재 스키마에서 제외됐다 (간소화).
> 실패 추적은 `last_failure_at` + `consecutive_failures`로 대체. 필요 시 ADR +
> 마이그레이션으로 정식 추가.

## 5. `feature.feature_files`

```sql
CREATE TABLE feature.feature_files (
  file_id              TEXT PRIMARY KEY,
  feature_id           TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  file_type            TEXT NOT NULL,                 -- image, video, audio, document, file
  storage_backend      TEXT NOT NULL DEFAULT 's3',    -- 's3' (RustFS 포함) — backend swap 가능 (ADR-015)
  bucket               TEXT NOT NULL,
  object_key           TEXT NOT NULL,
  source_url           TEXT,
  public_url           TEXT,
  content_type         TEXT,
  byte_size            BIGINT,
  checksum_sha256      CHAR(64),
  width                INTEGER,
  height               INTEGER,
  role                 TEXT NOT NULL DEFAULT 'gallery', -- primary, thumbnail, gallery
  display_order        INTEGER NOT NULL DEFAULT 0,
  alt_text             TEXT,
  provider             TEXT,
  dataset_key          TEXT,
  source_record_key    TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  payload              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT uq_feature_files_storage UNIQUE (storage_backend, bucket, object_key),
  CONSTRAINT ck_feature_files_file_type CHECK (file_type IN ('image','video','audio','document','file')),
  CONSTRAINT ck_feature_files_display_order CHECK (display_order >= 0),
  CONSTRAINT ck_feature_files_byte_size CHECK (byte_size IS NULL OR byte_size >= 0),
  CONSTRAINT ck_feature_files_width CHECK (width IS NULL OR width > 0),
  CONSTRAINT ck_feature_files_height CHECK (height IS NULL OR height > 0)
);

CREATE INDEX idx_feature_files_feature_type   ON feature.feature_files (feature_id, file_type);
CREATE INDEX idx_feature_files_feature_order  ON feature.feature_files (feature_id, display_order);
CREATE INDEX idx_feature_files_provider       ON feature.feature_files (provider, dataset_key) WHERE provider IS NOT NULL;
```

## 6. kind별 typed subtype 테이블

kind별 값의 정본은 core가 아니라 typed subtype 테이블이다(ADR-086). core가
`UNIQUE (feature_id, kind)`를 갖고 각 subtype이 kind 상수 CHECK + `(feature_id, kind)`
복합 FK로 core를 참조하는 **배타 arc**이며, 여기서 두 성질이 구조적으로 따라온다 —
① 한 feature는 최대 한 subtype에만 존재한다(core kind가 단일 값이므로) ② subtype 행이
있는 동안 **core `kind` 변경이 FK 위반으로 막힌다**.

모든 subtype이 공유하는 제약 3종:

- `PRIMARY KEY (feature_id)` — core와 1:1.
- `CHECK (kind = '<해당 kind>')` — 배타 arc의 상수 축.
- `FOREIGN KEY (feature_id, kind)` → `feature.features (feature_id, kind)`와
  `FOREIGN KEY (feature_id, feature_uuid)` → `feature.features (feature_id, feature_uuid)`.
  뒤쪽은 `feature_aliases`와 같은 identity 사본 일치 계약이고, 둘 다 `ON DELETE CASCADE`다.

price/weather subtype은 **두지 않는다** — detail이 비어 있고 값 정본은
`feature.feature_price_values`/`feature_weather_values`가 이미 소유한다(§8). 빈 테이블은
단일 정본 원칙 위반이다.

### 6.1 `feature.feature_places`

```sql
CREATE TABLE feature.feature_places (
  feature_id              TEXT NOT NULL,
  feature_uuid            UUID NOT NULL,
  kind                    TEXT NOT NULL,
  place_kind              TEXT NOT NULL,
  phones                  TEXT[] NOT NULL DEFAULT '{}'::text[],   -- PlaceDetail.phones (≤3)
  biz_number              TEXT,
  license_date            DATE,
  business_hours          JSONB,
  facility_info           JSONB NOT NULL DEFAULT '{}'::jsonb,
  reviews_link            JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT pk_feature_places PRIMARY KEY (feature_id),
  CONSTRAINT ck_feature_places_kind CHECK (kind = 'place'),
  CONSTRAINT fk_feature_places_feature_kind
    FOREIGN KEY (feature_id, kind)
    REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
  CONSTRAINT fk_feature_places_identity_pair
    FOREIGN KEY (feature_id, feature_uuid)
    REFERENCES feature.features (feature_id, feature_uuid) ON DELETE CASCADE
);

CREATE INDEX idx_feature_places_opening_hours
  ON feature.feature_places (feature_id) WHERE business_hours IS NOT NULL;
```

### 6.2 `feature.feature_events`

```sql
CREATE TABLE feature.feature_events (
  feature_id              TEXT NOT NULL,
  feature_uuid            UUID NOT NULL,
  kind                    TEXT NOT NULL,
  event_kind              TEXT NOT NULL,
  starts_on               DATE,
  ends_on                 DATE,
  timezone                TEXT NOT NULL DEFAULT 'Asia/Seoul',
  opening_hours           JSONB,
  venue_name              TEXT,
  tel                     TEXT,
  content_id              TEXT,
  content_type_id         TEXT,
  area_code               TEXT,
  sigungu_code            TEXT,
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT pk_feature_events PRIMARY KEY (feature_id),
  CONSTRAINT ck_feature_events_kind CHECK (kind = 'event'),
  CONSTRAINT ck_feature_events_period
    CHECK (starts_on IS NULL OR ends_on IS NULL OR starts_on <= ends_on)
  -- + 공통 복합 FK 2종 (§6 도입부)
);

CREATE INDEX idx_feature_events_period
  ON feature.feature_events (starts_on, ends_on);
CREATE INDEX idx_feature_events_opening_hours
  ON feature.feature_events (feature_id) WHERE opening_hours IS NOT NULL;
```

`idx_feature_events_period`의 선두는 `ends_on`이 아니라 `starts_on`이다 — 공개 festival
경로가 `starts_on`으로 범위·keyset·`ORDER BY`를 건다. 질의가 `ends_on IS NULL`을 명시적으로
포함하므로 그 행을 빼는 부분 조건도 두지 않는다.

### 6.3 `feature.feature_notices`

```sql
CREATE TABLE feature.feature_notices (
  feature_id              TEXT NOT NULL,
  feature_uuid            UUID NOT NULL,
  kind                    TEXT NOT NULL,
  notice_type             TEXT NOT NULL,
  severity                SMALLINT,
  valid_start_time        TIMESTAMPTZ,
  valid_end_time          TIMESTAMPTZ,
  source_agency           TEXT,
  officer_name            TEXT,
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT pk_feature_notices PRIMARY KEY (feature_id),
  CONSTRAINT ck_feature_notices_kind CHECK (kind = 'notice'),
  CONSTRAINT ck_feature_notices_severity
    CHECK (severity IS NULL OR severity BETWEEN 0 AND 5)
  -- + 공통 복합 FK 2종 (§6 도입부)
);

CREATE INDEX idx_feature_notices_validity
  ON feature.feature_notices (valid_end_time, valid_start_time);
```

유효기간은 typed `timestamptz`다 — read 필터가 문자열 파싱이나 방어용 cast 없이 직접
비교한다. **`valid_start_time <= valid_end_time` CHECK는 두지 않는다**: provider가 미래
발효 공고를 공표한 뒤 발효 전에 내리면 lifecycle이 `valid_end_time=철회시각`을 써
`end < start`가 되며, 이는 "발효 전에 철회됨"이라는 정당한 사실이지 결함이 아니다.
CHECK는 DTO가 실제로 강제하는 불변식(§6.2 event 기간)에만 둔다.

### 6.4 `feature.feature_routes`

```sql
CREATE TABLE feature.feature_routes (
  feature_id                 TEXT NOT NULL,
  feature_uuid               UUID NOT NULL,
  kind                       TEXT NOT NULL,
  geom                       geometry(MultiLineString, 4326) NOT NULL,
  route_type                 TEXT NOT NULL,
  geometry_source            TEXT,
  geometry_status            TEXT,        -- 'provided', 'missing_route_geometry'
  total_distance_meters      NUMERIC,
  expected_duration_minutes  INTEGER,
  difficulty                 TEXT,
  begin_name                 TEXT,
  begin_address              TEXT,
  end_name                   TEXT,
  end_address                TEXT,
  payload                    JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT pk_feature_routes PRIMARY KEY (feature_id),
  CONSTRAINT ck_feature_routes_kind CHECK (kind = 'route')
  -- + 공통 복합 FK 2종 (§6 도입부)
);

CREATE INDEX idx_feature_routes_geom_gist
  ON feature.feature_routes USING GIST (geom);
```

### 6.5 `feature.feature_areas`

```sql
CREATE TABLE feature.feature_areas (
  feature_id              TEXT NOT NULL,
  feature_uuid            UUID NOT NULL,
  kind                    TEXT NOT NULL,
  geom                    geometry(MultiPolygon, 4326) NOT NULL,
  area_kind               TEXT NOT NULL,  -- 'area' | 'national_park' | 'provincial_park' | 'recreation_forest' | 'tourism_district' | 'beach' | 'campsite' | 'heritage_area' | 'natural_heritage_area' | 'buried_heritage_area' | 'hazard_zone' (ADR-027) | 'protected_area' | 'other'
  boundary_source         TEXT,
  area_square_meters      NUMERIC,
  regulation_scope        TEXT,
  administrative_office   TEXT,
  description             TEXT,
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,  -- hazard_zone일 때 {"hazard_type": "rockfall|flash_flood|wildlife|...", "domain": "forest|coastal|..."} (ADR-027)
  CONSTRAINT pk_feature_areas PRIMARY KEY (feature_id),
  CONSTRAINT ck_feature_areas_kind CHECK (kind = 'area')
  -- + 공통 복합 FK 2종 (§6 도입부)
);

CREATE INDEX idx_feature_areas_geom_gist
  ON feature.feature_areas USING GIST (geom);
```

geometry 정본은 route/area subtype뿐이고 두 컬럼 모두 **NOT NULL**이다 — "geometry가
필수인 kind"와 "없어야 하는 kind"가 술어가 아니라 테이블 구조로 갈린다. `Feature` DTO도
같은 계약이라 다른 kind에 `geom`을 실으면 구성 시점에 거부된다.

### 6.6 `feature.features_detailed` (조립 뷰)

응답이 요구하는 `detail`/`geom`은 뷰 `feature.features_detailed`가 core + subtype 5종에서
조립한다. 조립 규칙이 한 곳에만 존재하고 writer는 subtype에만 쓴다. 아래는 구조 요약이고,
kind별 `jsonb_build_object` 전문은 alembic `0087_route_area_subtypes`가 정본이다.

```sql
CREATE VIEW feature.features_detailed AS
SELECT f.*,                                     -- core 전 컬럼
       COALESCE(r.geom, a.geom) AS geom,
       COALESCE(<kind별 jsonb_build_object(...)>, '{}'::jsonb) AS detail
FROM feature.features AS f
LEFT JOIN feature.feature_places  AS p ON p.feature_id = f.feature_id
LEFT JOIN feature.feature_events  AS e ON e.feature_id = f.feature_id
LEFT JOIN feature.feature_notices AS n ON n.feature_id = f.feature_id
LEFT JOIN feature.feature_routes  AS r ON r.feature_id = f.feature_id
LEFT JOIN feature.feature_areas   AS a ON a.feature_id = f.feature_id;

CREATE VIEW feature.public_features AS      -- ADR-067 단일 공개 projection
SELECT * FROM feature.features_detailed
WHERE status = 'active' AND deleted_at IS NULL;
```

- `detail` 조립은 **원본 바이트와 동등**해야 한다(전수 md5 대조로 고정). NULL 키를
  보존하므로 `jsonb_strip_nulls`를 쓰지 않는다 — 재귀적이라 `payload`/`facility_info`
  내부의 정당한 null까지 지운다. price/weather는 CASE 미매치 → `{}`가 된다.
- notice의 시각은 KST 고정 렌더(`to_char … AT TIME ZONE 'Asia/Seoul'`, 마이크로초가 0이면
  생략)로 조립한다. `to_jsonb(timestamptz)`를 그대로 쓰면 문자열이 세션 `TimeZone` GUC에
  의존해 서버 설정이 다른 인스턴스가 같은 공지에 다른 값을 돌려준다.
- read 경로는 `FROM feature.features`를 이 뷰로 바꾸면 종전과 같은 모양을 얻는다. 단
  **공간 술어만은 예외**로 subtype을 직접 참조한다 — 뷰의 `geom`은
  `COALESCE(routes.geom, areas.geom)` 산출 컬럼이라 인덱스가 없고, 술어에 그대로 넣으면
  전체 seq scan이 된다.

## 7. 영업시간

```sql
CREATE TABLE feature.feature_opening_periods (
  feature_id        TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  period_index      SMALLINT NOT NULL,
  start_weekday     SMALLINT NOT NULL,                -- 0=Sunday (Google Places)
  start_time        CHAR(4) NOT NULL,                 -- 'HHMM'
  duration_minutes  INTEGER NOT NULL,
  timezone          TEXT NOT NULL DEFAULT 'Asia/Seoul',
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (feature_id, period_index),
  CONSTRAINT ck_opening_weekday CHECK (start_weekday BETWEEN 0 AND 6),
  CONSTRAINT ck_opening_time CHECK (start_time ~ '^([01]\d|2[0-3])[0-5]\d$'),
  CONSTRAINT ck_opening_duration CHECK (duration_minutes > 0 AND duration_minutes <= 10080)
);

CREATE INDEX idx_opening_start ON feature.feature_opening_periods (start_weekday, start_time);

CREATE TABLE feature.feature_special_days (
  feature_id     TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  special_date   DATE NOT NULL,
  is_closed      BOOLEAN NOT NULL,
  periods        JSONB,
  payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (feature_id, special_date)
);

CREATE INDEX idx_special_date ON feature.feature_special_days (special_date);
```

## 8. weather / price

### 8.1 `feature.feature_weather_values`

```sql
CREATE TABLE feature.feature_weather_values (
  weather_value_key       TEXT PRIMARY KEY,           -- make_weather_value_key(...)
  feature_id              TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  provider                TEXT NOT NULL,
  weather_domain          TEXT NOT NULL,              -- WeatherDomain enum
  forecast_style          TEXT NOT NULL,              -- ForecastStyle enum
  timeline_bucket         TEXT,                       -- ultra_short, short, mid (분류)
  metric_key              TEXT NOT NULL,
  source_metric_key       TEXT,
  source_metric_name      TEXT,
  metric_name             TEXT,
  issued_at               TIMESTAMPTZ,
  valid_at                TIMESTAMPTZ,
  valid_from              TIMESTAMPTZ,
  valid_until             TIMESTAMPTZ,
  observed_at             TIMESTAMPTZ,
  value_number            NUMERIC(14,4),
  value_text              TEXT,
  unit                    TEXT,
  severity                TEXT,
  normalization_version   TEXT,
  source_record_key       TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  collected_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT uq_weather_values UNIQUE (
    feature_id, provider, weather_domain, forecast_style, metric_key, issued_at, valid_at, observed_at
  )
);

CREATE INDEX idx_weather_feature_metric_time
  ON feature.feature_weather_values (feature_id, metric_key, valid_at DESC NULLS LAST);
CREATE INDEX idx_weather_provider_domain
  ON feature.feature_weather_values (provider, weather_domain, valid_at DESC NULLS LAST);
CREATE INDEX idx_weather_valid_at_brin
  ON feature.feature_weather_values USING BRIN (valid_at);
CREATE INDEX idx_weather_collected_at_brin
  ON feature.feature_weather_values USING BRIN (collected_at);

CREATE TABLE feature.weather_metric_series (
  feature_id              TEXT NOT NULL
    REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  provider                TEXT NOT NULL,
  weather_domain          TEXT NOT NULL,
  forecast_style          TEXT NOT NULL,
  metric_key              TEXT NOT NULL,
  PRIMARY KEY (
    feature_id, provider, weather_domain, forecast_style, metric_key
  )
);

CREATE INDEX idx_weather_values_feature_effective
  ON feature.feature_weather_values (
    feature_id,
    provider,
    weather_domain,
    forecast_style,
    metric_key,
    (COALESCE(valid_at, observed_at, valid_from, issued_at)) DESC,
    issued_at DESC NULLS LAST,
    collected_at DESC,
    weather_value_key
  );

CREATE INDEX idx_features_public_weather_coord_5179_gist
  ON feature.features USING gist (coord_5179)
  WHERE status = 'active'
    AND deleted_at IS NULL
    AND kind = 'weather'
    AND coord_5179 IS NOT NULL;
```

**인덱스 설계**:
- 시계열 누적 → BRIN.
- `feature_id + metric_key + valid_at DESC` — `build_weather_card`의 핵심
  쿼리 (각 metric별 최신값).
- `provider + weather_domain + valid_at DESC` — admin 검증.
- `weather_metric_series`는 fact insert와 series identity 변경 trigger가 단조롭게
  유지하는 작은 physical-series registry다. 삭제로 stale row가 남아도 predecessor 조회가
  0행이므로 read 결과는 바뀌지 않으며, 대용량 fact에서 매 요청마다 series를 `DISTINCT`로
  재발견하지 않는다.
- `idx_weather_values_feature_effective`는 physical-series exact prefix 뒤에 effective time과
  결정적 tie-break를 둬 current predecessor와 24시간 timeline을 index range scan으로 읽는다.
  concurrent build 뒤 후속 DDL이 실패해 revision이 미적용으로 남아도, 재시도는 catalog에서
  이미 valid인 index를 재사용하고 invalid 잔재만 제거·재구축한다.
- `idx_features_public_weather_coord_5179_gist`는 공유 가능한 canonical weather anchor만 담는
  partial GiST다. nearest KNN이 일반 place 후보를 훑지 않으며 공간 술어에서
  `ST_Transform`을 사용하지 않는다.

0060 이후 semantic UNIQUE는 위 시간축의 NULL을 같은 값으로 취급하는 `NULLS NOT DISTINCT`다.
같은 semantic tuple의 current row는 `collected_at`이 더 최신인 입력만 갱신한다. 더 오래된
backfill은 no-op이며, 동률은 실제 저장 내용이 다를 때만 후속 write가 이긴다. 완전히 같은 동률
재적재는 heap UPDATE를 만들지 않는다. `collected_at`은 non-null `TIMESTAMPTZ` 계약이다.
known-at correction fact를 행별로 보존하는 full bitemporal 전환은 ADR-072의 별도 current summary와
read cutover를 함께 수행할 때 적용하며, 0060 current-row writer에 부분 도입하지 않는다.

### 8.2 `feature.feature_price_values`

가격 시계열은 별도 `price_points` 테이블을 두지 않고, `feature.features`
의 `kind='price'` anchor feature에 직접 연결한다. anchor feature는 지도/목록에서
가격 데이터가 보이기 위한 표시 단위이고, 실제 제품별 값은
`feature.feature_price_values`에 누적한다.

설계 기준:

- `feature_id`는 `feature.features(feature_id)`를 참조한다. price anchor가 삭제되면
  해당 가격 시계열도 함께 삭제한다.
- `price_value_key`는 `make_price_value_key(...)`가 계산한 결정적 PK다.
- 논리 중복은 `(feature_id, provider, price_domain, product_key, observed_at)`로
  한 번 더 막는다.
- provider raw 추적은 `source_record_key` nullable FK로 보존한다. source record가
  정리되어도 가격 시계열 자체는 유지한다.
- OpiNet처럼 장소 좌표가 있는 provider는 `place` 주유소 feature의
  `parent_feature_id`를 가진 price feature를 만든다. KREX 유가처럼 가격 row에
  좌표가 없는 provider는 좌표 없는 price feature로 저장하고, 주소/이름 기반 보강은
  후속 matching 단계에서 처리한다.

```sql
CREATE TABLE feature.feature_price_values (
  price_value_key       TEXT PRIMARY KEY,
  feature_id            TEXT NOT NULL
    REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  provider              TEXT NOT NULL,
  price_domain          TEXT NOT NULL,
  product_key           TEXT NOT NULL,                -- gasoline / diesel / lpg / ...
  product_name          TEXT,
  source_product_key    TEXT,
  source_product_name   TEXT,
  observed_at           TIMESTAMPTZ NOT NULL,
  value_number          NUMERIC(14,4) NOT NULL,
  unit                  TEXT NOT NULL DEFAULT 'KRW',  -- KRW / KRW/L / KRW/회 ...
  normalization_version TEXT,
  payload               JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_record_key     TEXT
    REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  collected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_price_value_nonnegative CHECK (value_number >= 0),
  CONSTRAINT uq_price_value_identity UNIQUE (
    feature_id, provider, price_domain, product_key, observed_at
  )
);

CREATE INDEX idx_price_values_observed_at_brin
  ON feature.feature_price_values USING BRIN (observed_at);
CREATE INDEX idx_price_values_feature_observed_identity
  ON feature.feature_price_values (feature_id, observed_at DESC, provider, price_domain, product_key);
CREATE INDEX idx_price_values_domain_product_observed
  ON feature.feature_price_values (provider, price_domain, product_key, observed_at DESC);
CREATE INDEX idx_price_values_source_record
  ON feature.feature_price_values (source_record_key)
  WHERE source_record_key IS NOT NULL;
```

**인덱스 설계**:
- `idx_price_values_observed_at_brin` — 장기 누적 시계열의 기간 조건.
- `uq_price_value_identity` — `(feature_id, provider, price_domain, product_key,
  observed_at)` 자연키를 보장하고, all-DESC 역방향 스캔으로 series별 current 조회도
  담당한다. 동일 선두 컬럼 current index를 중복 생성하지 않는다.
- `idx_price_values_feature_observed_identity` — 특정 가격 feature의 전체 series history를
  최신 관측순으로 읽는다.
- `idx_price_values_domain_product_observed` — provider/domain/product별 운영 검증과
  최신 snapshot 확인.
- `idx_price_values_source_record` — provider raw 역추적.


가격 series 식별자는 `feature_id + provider + price_domain + product_key`다. `current`와
지도/admin `price_summary`는 이 series마다 `observed_at` 최신 1건을 유지한다. 같은
`product_key`라도 provider/domain이 다르면 별도 값이며, history는 모든 series를 합쳐
최신 관측순으로 제한한다. 인덱스 교체와 API cardinality 결정은 ADR-078을 따른다.
## 9. 운영 보조 (`ops` schema)


### 9.1 `ops.import_jobs` (ADR-011)

```sql
CREATE TABLE ops.import_jobs (
  job_id            UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  kind              TEXT NOT NULL,                    -- 'visitkorea_festival_full_scan', 'mois_license_full_update', ...
  load_batch_id     UUID,                             -- full-load root/child batch id
  parent_job_id     UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  status            TEXT NOT NULL DEFAULT 'queued',   -- queued, running, done, failed, cancelled
  progress          INTEGER NOT NULL DEFAULT 0,       -- 0~100
  current_stage     TEXT,
  source_checksum   TEXT,
  error_message     TEXT,
  started_at        TIMESTAMPTZ,
  finished_at       TIMESTAMPTZ,
  heartbeat_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_import_jobs_status CHECK (status IN ('queued','running','done','failed','cancelled')),
  CONSTRAINT ck_import_jobs_progress CHECK (progress BETWEEN 0 AND 100)
);

CREATE INDEX idx_import_jobs_status        ON ops.import_jobs (status, created_at);
CREATE INDEX idx_import_jobs_kind_status   ON ops.import_jobs (kind, status, created_at DESC);
CREATE INDEX idx_import_jobs_heartbeat     ON ops.import_jobs (heartbeat_at) WHERE status='running';
CREATE INDEX idx_import_jobs_load_batch_created
  ON ops.import_jobs (load_batch_id, created_at DESC, job_id DESC)
  WHERE load_batch_id IS NOT NULL;
CREATE INDEX idx_import_jobs_parent_created
  ON ops.import_jobs (parent_job_id, created_at DESC, job_id DESC)
  WHERE parent_job_id IS NOT NULL;
```

`load_batch_id`/`parent_job_id`는 ADR-045 T-205d에서 추가했다. T-200 Batch DAG는
root import job에 `load_batch_id`를 만들고, provider별 child job과
`consistency_check` job이 같은 `load_batch_id`와 root `parent_job_id`를 공유한다.

### 9.1.1 `ops.import_job_events` (T-221b)

```sql
CREATE TABLE ops.import_job_events (
  event_id    UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  job_id      UUID NOT NULL REFERENCES ops.import_jobs(job_id) ON DELETE CASCADE,
  provider    TEXT,
  dataset_key TEXT,
  sync_scope  TEXT,
  feature_id  TEXT,
  stage       TEXT,
  level       TEXT NOT NULL, -- debug, info, warning, error, critical
  code        TEXT,
  message     TEXT NOT NULL,
  payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
  quarantined_at TIMESTAMPTZ,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_import_job_events_level
    CHECK (level IN ('debug','info','warning','error','critical')),
  CONSTRAINT ck_import_job_events_provider_dataset_pair CHECK (
    quarantined_at IS NOT NULL OR
    ((provider IS NULL AND dataset_key IS NULL) OR
     (provider IS NOT NULL AND provider = btrim(provider) AND provider <> '' AND
      dataset_key IS NOT NULL AND dataset_key = btrim(dataset_key) AND dataset_key <> ''))
  ),
  CONSTRAINT ck_import_job_events_sync_scope CHECK (
    sync_scope IS NULL OR (
      provider IS NOT NULL AND dataset_key IS NOT NULL AND
      (sync_scope IN ('dataset_wide','target_grids') OR
       (left(sync_scope, 16) = 'external_system:' AND
        char_length(sync_scope) BETWEEN 17 AND 128))
    )
  )
);

CREATE INDEX idx_import_job_events_job_time
  ON ops.import_job_events (job_id, occurred_at DESC, event_id DESC)
  WHERE quarantined_at IS NULL;
CREATE INDEX idx_import_job_events_provider_time
  ON ops.import_job_events (provider, occurred_at DESC, event_id DESC)
  WHERE provider IS NOT NULL AND quarantined_at IS NULL;
CREATE INDEX idx_import_job_events_level_time
  ON ops.import_job_events (level, occurred_at DESC, event_id DESC)
  WHERE quarantined_at IS NULL;
CREATE INDEX idx_import_job_events_provider_dataset_scope_time
  ON ops.import_job_events (
    provider, dataset_key, sync_scope, occurred_at DESC, event_id DESC
  )
  WHERE provider IS NOT NULL AND dataset_key IS NOT NULL
    AND sync_scope IS NOT NULL AND quarantined_at IS NULL;

CREATE TABLE ops.import_job_event_clock (
  clock_id  BOOLEAN PRIMARY KEY DEFAULT true CHECK (clock_id),
  revision  BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
```

`ops.import_job_events`는 `ops.import_jobs` lifecycle과 provider/Dagster/offline upload
작업 단계 event를 저장한다. REST 조회 정렬은 `(occurred_at DESC, event_id DESC)`다. 0052
migration이 격리한 component의 기존 event는 보존하되 같은 시각을 `quarantined_at`에 기록한다.
이 marker는 migration 전용 불변값이며, 운영 조회와 모든 시간순 인덱스는
`quarantined_at IS NULL`인 event만 대상으로 한다.

0057부터 `sync_scope`는 모든 event에 억지 기본값을 붙이는 열이 아니다. 일반 import,
schedule, orchestration event는 `NULL`을 유지한다. canonical direct
`feature_update_request`의 provider/dataset event만 연결 job의 non-null typed
`sync_scope`를 저장한다. BEFORE INSERT trigger가 owning job을 `FOR KEY SHARE`로 읽어
provider/dataset/scope를 한 번에 복사하고 명시값이 다르면 거절한다. event의
`job_id`/provider/dataset/scope identity는 INSERT 뒤 불변이다. 따라서 exact-scope 감사
조회는 request/job을 다시 JOIN하거나 payload를 해석하지 않고 위 partial B-tree에서
조건→keyset→LIMIT 순서로 읽는다. 0057 backfill도 visible canonical request/job pair의
event scope만 채운다. 0052 relink writer가 남긴 visible event의 NULL provider/dataset pair는
immutable owning job pair로 먼저 복구하고, partial pair나 서로 다른 pair는 추측하지 않고
migration을 중단한다. 일반 event의 `sync_scope`와 격리 event는 `NULL`로 보존한다.
0052가 이미 격리한 event는 당시의 비정규 pair를 감사 증거로 그대로 보존해야 하므로 pair
constraint의 유일한 예외다. 신규 격리 marker는 migration 밖에서 만들 수 없고, 모든 visible
INSERT는 trigger와 constraint를 함께 통과한다.
`external_system:` 뒤 이름은 API strict parser와 같은 Unicode canonical whitespace 집합으로
앞뒤 공백이 없는지 검사한다. 위 축약 DDL의 길이 조건만 만족하는 공백 이름도 실제 constraint는
거부한다.

`ops.import_job_event_clock`은 event INSERT/UPDATE/DELETE 성공 statement의 AFTER trigger가
singleton `revision`을 한 번 올리는 live invalidation projection이다. 같은 row update가 동시 event
transaction을 commit 전에 직렬화하므로 transaction 시작 시각이 오래된 late commit도 놓치지
않고, rollback이면 event와 revision 증가가 함께 취소된다. `updated_at=clock_timestamp()`은 진단
정보일 뿐 변경 판정의 정본은 `revision`이다. Row마다 clock을 갱신하지 않고 event row lock을 모두
얻은 statement 끝에서 한 번만 갱신해 bulk WAL/dead tuple과 교차 row deadlock을 피한다. Clock UPDATE는 event
AFTER trigger 안의 정확한 `revision+1`만 허용하며 DELETE/TRUNCATE를 금지한다. Event table
TRUNCATE는 허용하되 같은 AFTER STATEMENT trigger가 revision을 한 번 증가시킨다.

### 9.1.2 `ops.offline_uploads` (ADR-045 D-14 / T-208g)

```sql
CREATE TABLE ops.offline_uploads (
  upload_id         UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  provider          TEXT NOT NULL,
  dataset_key       TEXT NOT NULL,
  sync_scope        TEXT NOT NULL DEFAULT 'default',
  original_filename TEXT NOT NULL,
  storage_backend   TEXT NOT NULL,      -- rustfs / s3 / local-test 등
  storage_key       TEXT NOT NULL,
  byte_size         BIGINT NOT NULL,
  checksum_sha256   CHAR(64) NOT NULL,
  detected_format   TEXT,
  detected_encoding TEXT,
  status            TEXT NOT NULL DEFAULT 'uploaded',
  validation_job_id UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  load_job_id       UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  created_by        TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_offline_uploads_status CHECK (
    status IN (
      'uploaded','validating','validated','validation_failed',
      'loading','loaded','load_failed','cancelled'
    )
  ),
  CONSTRAINT ck_offline_uploads_byte_size CHECK (byte_size >= 0),
  CONSTRAINT ck_offline_uploads_checksum_sha256
    CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_offline_uploads_provider_dataset
  ON ops.offline_uploads (provider, dataset_key, created_at DESC);
CREATE INDEX idx_offline_uploads_status
  ON ops.offline_uploads (status, created_at DESC);
```

첫 load job과 기본 admin API/UI 구현은 JSON/JSONL `FeatureBundle` dump만 지원한다.
CSV/TSV column mapping과 validation wizard는 후속에서 같은 테이블과 `import_jobs`
연결을 사용한다.

### 9.2 `ops.dedup_review_queue` (ADR-016)

```sql
CREATE TABLE ops.dedup_review_queue (
  review_id         UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  feature_id_a       TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  feature_id_b       TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  total_score        NUMERIC(5,2) NOT NULL,
  name_score         NUMERIC(5,2) NOT NULL,
  spatial_score      NUMERIC(5,2) NOT NULL,
  category_score     NUMERIC(5,2) NOT NULL,
  status             TEXT NOT NULL DEFAULT 'pending', -- pending, accepted, rejected, merged, ignored
  decision_reason    TEXT,
  reviewed_by        TEXT,
  reviewed_at        TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_dedup_pair UNIQUE (feature_id_a, feature_id_b),
  CONSTRAINT ck_dedup_pair_order CHECK (feature_id_a < feature_id_b),
  CONSTRAINT ck_dedup_status CHECK (status IN ('pending','accepted','rejected','merged','ignored')),
  CONSTRAINT ck_dedup_scores CHECK (
    total_score BETWEEN 0 AND 100 AND
    name_score BETWEEN 0 AND 100 AND
    spatial_score BETWEEN 0 AND 100 AND
    category_score BETWEEN 0 AND 100
  )
);

CREATE INDEX idx_dedup_status_score ON ops.dedup_review_queue (status, total_score DESC);
```

`feature_id_a`/`feature_id_b`는 항상 lexicographic canonical 방향으로 저장한다.
`dedup_repo`는 upsert 전에 pair를 정렬하고, self-pair는 검토 큐에 넣지 않는다.

### 9.3 `ops.feature_overrides`

구현됨 — **alembic 0010** + `infra/models.py::FeatureOverrideRow` +
`infra/admin_feature_repo.py`. 운영자가 비활성화/수동 보정한 field를 provider 재적재가
덮지 않도록 기록한다. T-207c는 `field_path='status'` +
`prevent_provider_reactivation=true`를 `feature_repo.upsert_feature`에서 존중한다.

```sql
CREATE TABLE ops.feature_overrides (
  override_id         UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  feature_id           TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  source_record_key    TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  field_path           TEXT NOT NULL,                 -- 'name', 'detail.phones[0]', ...
  source_value         JSONB,
  override_value       JSONB,
  prevent_provider_reactivation BOOLEAN NOT NULL DEFAULT false,
  status               TEXT NOT NULL DEFAULT 'active', -- active, inactive, superseded
  reason               TEXT,
  created_by           TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_overrides_status CHECK (status IN ('active','inactive','superseded'))
);

CREATE INDEX idx_overrides_feature  ON ops.feature_overrides (feature_id, status);
CREATE INDEX idx_overrides_field    ON ops.feature_overrides (field_path);
CREATE UNIQUE INDEX uq_overrides_active_feature_field
  ON ops.feature_overrides (feature_id, field_path)
  WHERE status = 'active';
CREATE INDEX idx_overrides_prevent_reactivation
  ON ops.feature_overrides (feature_id, field_path)
  WHERE status = 'active' AND prevent_provider_reactivation;
```

### 9.4 `ops.feature_merge_history`

구현됨 — **alembic 0007** + `infra/models.py::FeatureMergeHistoryRow` +
`infra/merge_repo.py`(`apply_feature_merge`/`merge_from_review`). `kor-travel-map
dedup-merge`가 `dedup_review_queue` 후보 1쌍을 master/loser로 확정(ADR-016
`core.scoring.select_master`)해 병합할 때 1행 INSERT. loser의 `source_links`는
master로 재지정되고 loser feature는 soft-delete(`status='deleted'`)된다.

```sql
CREATE TABLE ops.feature_merge_history (
  merge_id          UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  master_feature_id TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  loser_feature_id  TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  score             NUMERIC(5,2),                     -- dedup total_score (0~100), nullable
  review_id        UUID REFERENCES ops.dedup_review_queue(review_id) ON DELETE SET NULL,
  merged_by         TEXT,                             -- 운영자 ID 등
  reason            TEXT,
  merged_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_merge_history_distinct CHECK (master_feature_id <> loser_feature_id)
);

CREATE INDEX idx_merge_history_loser  ON ops.feature_merge_history (loser_feature_id);
CREATE INDEX idx_merge_history_master ON ops.feature_merge_history (master_feature_id, merged_at DESC);
```

> 설계 메모: master/loser **둘 다** FK(CASCADE) — loser는 하드 삭제가 아니라
> soft-delete(ADR-017)라 행이 남으므로 FK 유효. `review_id` FK는 큐 행 삭제 시
> SET NULL(이력 보존). master 자동 선정은 `select_master`(좌표 보유 → updated_at →
> source 우선순위 행안부>TourAPI>사용자, 동률은 feature_id 사전순).

### 9.5 `ops.data_integrity_violations` (ADR-045 T-205c, alembic 0009)

위반 1건 = 1행인 운영 큐다. ADR-033 Phase 1의
`ops.feature_consistency_reports`(배치 단위 집계)와 달리, admin UI가 개별 이슈를
`open`/`acknowledged`/`resolved`/`ignored`로 관리한다.

```sql
CREATE TABLE ops.data_integrity_violations (
  issue_id       UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  provider            TEXT,
  dataset_key         TEXT,
  source_record_key   TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  feature_id          TEXT REFERENCES feature.features(feature_id) ON DELETE SET NULL,
  violation_type      TEXT NOT NULL,                  -- 'F1_coord_outside_bjd', 'F4_provider_coord_drift', ...
  severity            TEXT NOT NULL,                  -- info, warning, error, critical
  message             TEXT NOT NULL,
  payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
  status              TEXT NOT NULL DEFAULT 'open',
  detected_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at         TIMESTAMPTZ,
  CONSTRAINT ck_violations_severity CHECK (severity IN ('info','warning','error','critical')),
  CONSTRAINT ck_violations_status   CHECK (status IN ('open','acknowledged','resolved','ignored'))
);

CREATE INDEX idx_violations_type_status ON ops.data_integrity_violations (violation_type, status);
CREATE INDEX idx_violations_feature     ON ops.data_integrity_violations (feature_id) WHERE feature_id IS NOT NULL;
CREATE INDEX idx_violations_source_record ON ops.data_integrity_violations (source_record_key) WHERE source_record_key IS NOT NULL;
CREATE INDEX idx_violations_detected_brin ON ops.data_integrity_violations USING BRIN (detected_at);
-- T-VN-H30A (migration 0067): 열린 이슈 한정 dedupe. ON CONFLICT 추론 대상.
CREATE UNIQUE INDEX uq_violations_open_dedupe_key
    ON ops.data_integrity_violations ((payload ->> 'dedupe_key'))
    WHERE status IN ('open', 'acknowledged') AND payload ? 'dedupe_key';
CREATE INDEX idx_violations_status_seen
    ON ops.data_integrity_violations (status, last_seen_at DESC, issue_id DESC);
CREATE INDEX idx_violations_provider_status_seen
    ON ops.data_integrity_violations (provider, status, last_seen_at DESC, issue_id DESC)
    WHERE provider IS NOT NULL;
CREATE INDEX idx_violations_feature_seen
    ON ops.data_integrity_violations (feature_id, last_seen_at DESC, issue_id DESC)
    WHERE feature_id IS NOT NULL;
```

주소/좌표 정합성 위반은 다음 `violation_type`을 우선 지원한다.

| violation_type | 발생 조건 | payload 필수 필드 |
|----------------|-----------|-------------------|
| ~~`provider_address_mismatch`~~ | **발행 중단 (T-VN-H28B, 2026-07-29)** — 이름 substring 축은 실측 탐지력 0으로 확인돼 제거. 기존 행은 보존한다 | — |
| ~~`provider_address_partial_match`~~ | **발행 중단 (T-VN-H28B)** | — |
| `admin_code_stale_{sido,sigungu,emd}` | provider payload 행정코드와 좌표 reverse 행정코드가 해당 단계에서 불일치. **위치 검증이 아니라 producer 캐시 staleness 검출**이다 (T-VN-H28B) | 공통 payload(아래) |
| `provider_address_region_disagreement` | provider 주소 문자열이 지목하는 행정구역이 좌표 reverse 후보 어디에도 없음 (T-VN-H28B) | 공통 payload |
| `reverse_geocode_unavailable` | 좌표 reverse가 결과를 못 냈지만 provider 행정코드로 적재 가능 — 좌표 정합성 **미확인** 표시. drop 사유가 아니다 (T-VN-H30A) | 공통 payload |
| `geocode_failed` | provider 주소 문자열로 `POST /v2/geocode` 후보를 얻지 못함 | `provider_address`, `provider_fields`, `error` |
| `reverse_geocode_failed` | 좌표는 있는데 어떤 출처로도 법정동코드를 얻지 못함 | 공통 payload |
| `missing_address` | provider 주소도 kor-travel-geo 주소도 없음 | 공통 payload |
| `missing_bjd_code` | kor-travel-geo 결과에 10자리 법정동코드가 없음 | `kor_travel_geo_address`, `coord` |

> **주소 검증 공통 payload + dedupe (T-VN-H30A, 2026-07-29)**
>
> `dagster.etl`이 쓰는 주소/좌표 검증 finding은 공통 payload를 갖는다:
> `feature_id`, `source_record_key`, `provider_address`, `bjd_code`, `sigungu_code`,
> `dropped`(적재 전 격리 여부), 그리고 dedupe 메타 `dedupe_key`, `occurrence_count`.
>
> - `dedupe_key`는 provider/dataset/source entity type+id/violation code 전체의
>   `av2_<sha256>` 68-byte 값이다. `source_record_key`는 payload hash에 따라 바뀌고,
>   원천 id 직접 저장은 B-tree key 크기가 무제한이므로 둘 다 쓰지 않는다.
> - 부분 unique index **`uq_violations_open_dedupe_key`**(migration `0067`)가
>   `(payload->>'dedupe_key')`에 걸려 있고 술어는
>   `status IN ('open','acknowledged') AND payload ? 'dedupe_key'`다. 열린 이슈만 접히므로
>   resolved/ignored 이력은 보존되고, 재발하면 새 행이 생긴다.
> - 자동 resolve는 batch 경계에서 수행하지 않는다. `T-VN-H32R`은
>   `ops.integrity_observation_scopes/runs`와
>   `ops.integrity_finding_observations`에 provider/dataset generation과 run별 관측 집합을
>   정규화한다. authoritative·complete typed receipt를 가진 run만 scope row fence 아래에서
>   sweep하며 current generation과 더 새 partial generation의 관측은 닫지 않는다.
> - `detected_at`은 최초 탐지, `last_seen_at`은 최신 recurrence다. recurrence 때 실제
>   `feature_id`/`source_record_key`도 최신 target으로 갱신한다. 적재 전 drop 행은 두 값을
>   payload로만 나르고, 연결 대상 삭제는 `SET NULL`이라 ledger 행을 보존한다.

> **producer 상태(F-02 구현, 2026-06-16)**: `reverse_geocode_failed`는
> `validate_feature_bundle_address`가 **좌표-있음+bjd-없음**(reverse가 bjd를 못 냄)에서
> 발행한다. `geocode_failed`(forward, 주소→좌표)는 적재 경로에 forward-geocode가 없어
> **미발행**(정의만 존재).

admin UI가 수동 수정하면 `status='resolved'`, `resolved_at`, `payload.resolution`
(`field_path`, `old_value`, `new_value`, `operator`, `reason`)을 기록한다. 실제 보정값은
`feature.features` row와 `ops.feature_overrides`에 반영해 provider 재적재가 덮어쓰지
않도록 한다.

### 9.6 `ops.api_call_log` (옵션)

```sql
CREATE TABLE ops.api_call_log (
  id            BIGSERIAL PRIMARY KEY,
  provider      TEXT NOT NULL,
  endpoint      TEXT NOT NULL,
  status        SMALLINT,
  latency_ms    INTEGER,
  error         TEXT,
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_api_call_occurred_brin ON ops.api_call_log USING BRIN (occurred_at);
CREATE INDEX idx_api_call_provider_time ON ops.api_call_log (provider, occurred_at DESC);
```

### 9.7 `ops.feature_consistency_reports` (ADR-033 Phase 1, 구현됨)

정합성 배치 1회 = 1행. F1~F3(orphan source_record / detail 누락 / CRS drift)을
`infra/consistency.py`가 검사해 집계 결과를 적재한다 (관측 모드 — Dagster swap
게이트는 Phase 2/Sprint 5). alembic `0003_consistency_reports`로 도입.

```sql
CREATE TABLE ops.feature_consistency_reports (
  report_id    UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  batch_id     UUID NOT NULL,
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  severity_max TEXT NOT NULL CHECK (severity_max IN ('OK','WARN','ERROR')),
  cases        JSONB NOT NULL,   -- [{code, severity, description, count, sample_ids}]
  summary      JSONB NOT NULL    -- {total_violations, cases_evaluated, by_severity, by_code}
);
CREATE INDEX idx_reports_batch   ON ops.feature_consistency_reports (batch_id);
CREATE INDEX idx_reports_started ON ops.feature_consistency_reports (started_at DESC);
```

### 9.8 `ops.feature_update_requests` (ADR-045 accepted — alembic 0008+0052+0053)

OpenAPI로 들어온 feature update request를 저장한다. `center_radius`,
`sigungu_by_radius`, `provider_dataset`, `cache_target_keys` 같은 scope를 Dagster
run/import job으로 연결한다. 상세 계약은 `docs/architecture/openapi-admin-contract.md`.

핵심 컬럼:

| 컬럼 | 의미 |
|------|------|
| `request_id` | UUID PK, `x_extension.gen_random_uuid()` 기본값 |
| `scope_type` / `scope` | 요청 범위 종류와 JSONB payload |
| `providers` / `dataset_keys` | 제한할 provider/dataset 목록(1차원 unique `TEXT[]`, 최대 32/64개, 항목당 trimmed non-empty 128자 이하) |
| `update_policy` | 허용 키·값 타입을 DB CHECK와 repository가 함께 강제하는 canonical 재적재/중복/정합성 정책 JSONB |
| `run_mode` | `queued` 또는 `now` |
| `priority` | queue 우선순위, 기본 50 |
| `matched_scope` | scope resolver가 계산한 feature/provider/sigungu 요약 |
| `job_id` | non-null unique `ops.import_jobs(job_id)` FK, job 삭제 `RESTRICT`; canonical job과 양방향 1:1 |
| `generation` | 양수 queue 세대; requeue/pre-start retry에서만 증가 |

인덱스:

- `idx_feature_update_priority` — queued canonical job seed와 JOIN한 뒤 priority 순서.
- `idx_feature_update_created` — 최신 요청 목록.
- `uq_feature_update_requests_job_id` — request당 canonical job 한 건과 job당 request 한 건을 위한 unique 역추적.

T-205a는 테이블/ORM 매핑까지만 구현했다. scope resolver, enqueue/claim/peek
repository, client 표면은 T-206a/b/c와 T-208e에서 구현했고, admin API와 Dagster
sensor는 T-207/T-208에서 연결했다.

0052부터 모든 request는 canonical job을 반드시 가지며 canonical
`feature_update_request` job도 정확히 한 request를 가져야 한다. request→job FK와 `job_id`
UNIQUE에 더해 canonical job INSERT의 deferred reverse-pair trigger가 commit 시 request 존재까지
검사한다.
따라서 job/request를 따로 commit하거나 request만 삭제해 orphan을 만드는 경로는 없다. generic
import job writer는 이 kind를 reserved로 거부하고 전용 enqueue 경계만 같은 transaction에서 두 행을
만든다. request 테이블은 scope/filter/policy/run mode/priority/operator/reason/matched scope와
양수 `generation`만 소유한다. status, Dagster run, cancellation marker, error, 시작/종료 시각은
삭제하고 canonical `import_jobs` 한 행을 lifecycle 단일 정본으로 사용한다. request 목록·상세·claim은
unique job JOIN으로 lifecycle을 읽고 cancellation root는 request ID correlation을 유지하되 canonical
job만 member로 동결·종결한다. `generation`은 requeue/pre-start retry에서만 증가하며 timestamp
microsecond hack 없이 Dagster run key와 CAS를 만든다. canonical job runtime payload는 빈 object이고
relation/scope/policy/matched scope를 복제하지 않는다. migration audit만 별도 source job ID를
보존한다. request의 identity/scope/filter/policy/
run mode/priority/operator/reason/created_at은 INSERT 뒤 불변이고 `matched_scope`와 `generation`만
linked job의 active·unmarked 조건 아래 변경할 수 있다. request와 canonical job은 cancellation
root/audit correlation을 보존하기 위해 append-only이며 DELETE를 거부한다. immutable DB 함수
`ops.is_valid_feature_update_scope`는 `feature_ids`, `center_radius`, `sigungu_by_radius`,
`bbox`, `provider_dataset`, `cache_target_keys` 여섯 scope의 exact key, JSON type, 배열
크기, trimmed non-empty 문자열, 좌표·반경·bbox 범위를 OpenAPI와 동일하게 강제한다.
`match`/`scope_mode`는 저장 전 기본값을 채우고 optional `sync_scope`/`radius_km`는
JSON `null` 대신 키를 생략한 canonical shape만 저장한다. `provider_dataset` scope의 pair는
연결 job의 typed pair와 정확히 같아야 하며 다른 scope는 unpaired job만 가리킨다.

0053부터 direct `provider_dataset` canonical job은 `ops.import_jobs.sync_scope`를 non-null
typed identity로 소유한다. request JSON의 optional `sync_scope`는 **requested 값**이므로 생략을
`dataset_wide`로 덮어쓰지 않는다. API/catalog가 계산한 **effective 값**은 job에만 저장하며 일반
dataset은 `dataset_wide`, target 선택형 KMA grid는 `target_grids` 또는
`external_system:<exact-name>`다. pipeline exact pair projection도 request JSON이 아니라 이 typed
column만 읽는다. scope별 최신 실행 projection은
`(provider, dataset_key, sync_scope)`를 identity로 삼고, non-direct request job의
`sync_scope`는 null이다. target 선택형 dataset은 실제 대상 subset이 typed
identity에 반영되지 않는 non-direct scope로 요청할 수 없다.

operation의 `dataset_wide`는 요청 중복 실행을 막는 조작 identity이고,
`provider_sync_state.sync_scope`는 provider cursor/failure namespace다. 일반 provider asset은
성공 writer와 동일한 `default` namespace에 실패를 기록하며, 실제 target subset마다 cursor가
갈리는 KMA grid 3종만 operation effective scope(`target_grids` 또는
`external_system:<name>`)를 provider state namespace로 그대로 사용한다.

KMA grid operation은 선택 scope의 active target과 설정 extra point를 격자로 해석하고 cap을
적용한 결과가 0개면 typed preflight failure로 종료한다. 이때 canonical request/job의 failure는
영속하지만 provider 호출·feature/weather 적재와 `provider_sync_state` row/cursor/성공·실패
timestamp는 만들거나 바꾸지 않는다. active membership과 요청 scope의 교집합이 사라진 경우도
같은 의미다. KMA credential 확인, `kma` module import, public `KmaClient` 생성은 이 preflight와
동일 cursor skip 판정을 모두 통과한 뒤에만 수행하고, 생성한 client만 해당 실행이 닫는다.
preflight failure의 canonical code `kma.target_scope_empty`는 request/job `failed` 전이와 같은
transaction에서 `ops.import_job_events`에 정확히 1건 기록한다. terminal request replay는 새
operation/event/state write 없이 기존 결과를 반환한다.

정규 schedule asset도 선생성 live client가 아니라 `kma_weather_client_factory` resource를
받는다. factory는 resource 초기화 중 credential 검증·provider import·client 생성을 하지 않으며,
세 KMA grid asset 각각이 위 preflight를 통과한 뒤 같은 task에서 동기 생성한다. asset이 소유한
client의 close가 실패해도 이미 발생한 typed provider failure나 `CancelledError` 같은
`BaseException`을 close 오류로 바꾸지 않는다. primary 오류가 없을 때만 close 오류를 전파한다.

0057부터 dataset 상세의 exact-scope event 이력은
`ops.import_job_events.sync_scope` partial B-tree를 직접 읽는다. 이 열은 canonical direct
request event에만 non-null이므로 일반 job과 격리 event를 섞지 않는다. event cursor는
job/level/provider/dataset/scope filter fingerprint를 포함하고, 다른 filter에서 재사용하면
DB 조회 전에 거부한다.

queued/running direct job에는 `(provider, dataset_key, sync_scope)` partial unique index
`uq_import_jobs_active_feature_update_scope`를 적용한다. 같은 identity의 계획이 scope/filter/policy/
priority/operator/reason까지 같으면 API는 기존 request를 재사용하고, 다르면 조용히 덮지 않고
409로 기존 operation을 가리킨다. `dispatch_requested_at`은 run-now가 새 request를 만들지 않고
같은 queued job의 우선 dispatch 의도를 최초 한 번 기록하는 시각이다. queue PEEK는 이 값이 있는
행을 일반 priority queue보다 먼저 선택하며 재호출은 timestamp와 generation을 바꾸지 않는다.
running은 같은 request를 반환하고 terminal/cancellation-requested는 dispatch를 거부한다.

0053 migration은 feature update request/job writer를 같은 `ACCESS EXCLUSIVE NOWAIT` 문장으로 잠근다.
기존 direct row는 raw requested 문자열을 identity로 승격하지 않는다.
`python-kma-api`의 short/ultra-short nowcast/ultra-short forecast 3종은 `target_grids`,
나머지 direct dataset은 `dataset_wide`로 일괄 backfill한다. canonical 매핑 뒤 같은 active
identity가 생기면 running 하나를 queued보다 우선 보존하고, running이 없으면 실제 queue dispatch
정렬(`run_mode=now`, priority 내림차순, 생성 시각, request/job ID)로 queued winner 하나를
보존한다. queued loser는 기존 오류 문맥과 winner ID를 남긴 `cancelled` terminal로 전환한다.
running 둘 이상 또는 cancellation audit marker가 걸린 중복은 mutation 전에 진단과 함께 중단한다.
`run_mode=now`의 dispatch 이력은 direct 여부와 관계없이 분리 backfill한다. job sync
scope와 request/job pair identity는 trigger로 불변이며 raw requested scope는 감사
JSON으로만 보존한다. migration이 보존한 legacy raw alias는 typed identity로
승격하지 않지만, 0053 이후 신규 direct writer가 requested `sync_scope`를 명시하면
canonical linked job scope와 정확히 같아야 한다. POI target과 `cache_target_keys` request의
`external_system`은 trimmed non-empty 112자 이하를 OpenAPI·core·DB·repository 경계에서
강제하고, 기존 위반 행은 자동 정리하지 않고
target ID·값·길이를 진단한 뒤 migration을 중단한다.
0052는 `providers`/`dataset_keys`를 JSONB에서 typed `TEXT[]`로 clean cut한다.
`ops.is_valid_feature_update_filter_array`는 1차원·중복 없음, 32/64개 상한과 trimmed
non-empty string 128자 이하를 강제한다. DB CHECK와 trigger는 연결 job의
`kind=feature_update_request`, `parent_job_id/load_batch_id IS NULL`, `trigger_kind='update_request'`,
registry/raw Dagster status 부재와 `queued → run-id NULL`, `running → trimmed non-empty run-id`까지
강제하며 import job의 kind/provider/dataset은 insert 뒤
불변이다. `update_policy`도 sparse object의 허용 key와 strict non-null 값 타입을 repository와
DB CHECK가 함께 강제한다. migration은 기존 jobless·공유·pair 불일치·reserved Dagster kind
request마다 request별 새 canonical job을 만들어 재연결한다. request와 연결되지 않은 기존
`feature_update_request` job의 양방향 parent/child component 전체에는 `quarantined_at`과
`quarantine_reason='unlinked_feature_update_component'`를 기록한다. 원래 `kind`·`payload`는 변경하지
않으며 filtered/unfiltered/detail projection, legacy import-job list/detail/status/live와 Dagster engine
read에서 제외한다. generic enqueue/lifecycle/payload/batch/event writer, runtime 격리 표식
INSERT/UPDATE, 격리 행 UPDATE/DELETE와 격리 parent 아래 새 child attach를
DB trigger가 거부해 migration 감사 계보를 보존한다. component에 다른 request가
하나라도 연결돼 있으면 terminal이어도 자동 격리하지 않고 migration을 중단한다. request가 running이거나 source job과 양방향 parent/child로 연결된 어떤 job이든
DB/Dagster active 상태이거나 cancellation scope가 동결됐으면 중복 실행·취소 우회를 피하려고
request ID와 함께 중단한다. malformed scope/filter/policy와 persisted `dry_run=true`도 같은 방식으로
중단한다. 0052는 DB `dry_run` 컬럼을 제거한다. HTTP는 실제 생성 endpoint(201)와
비영속 preview endpoint(200)를 분리하고, 각 결과를 `result_kind`로 명시한다.

#### 9.8.1 Pipeline root projection (T-ADM-C3b, 이슈 #679)

`GET /v1/ops/pipeline/executions`는 별도 operation 테이블을 만들기 전의 read model이다.
`ops.import_jobs` hierarchy와 `ops.feature_update_requests`를 Python에서 합치지 않고
하나의 recursive SQL에서 root 단위로 접는다.

- import job은 `parent_job_id`를 위로 따라 component를 만든다. 정상 hierarchy의
  최상위 job이 component root다. parent row가 없으면 현재 job을 self-root로 삼고,
  cycle은 `uuid[] path`로 감지·종료한 뒤 cycle member의 최소 `job_id`를 root로 쓴다.
- canonical request job은 항상 hierarchy root이고 request와 양방향 1:1이다. 따라서 request
  branch는 자기 root와 descendants 전부이며 중첩 request anchor와 같은 anchor의 다중 request는
  정상 저장 상태가 아니다.
- request hierarchy에 속하지 않은 component만 standalone partition에 귀속한다.
- 화면에 대표로 보일 job은 각 partition 안에서
  `anchor/root depth DESC, created_at DESC, job_id DESC` 첫 행이다.
  root 상태와 대표 job 상태는 서로 덮어쓰지 않으며 `linked_job_count`로 해당
  request branch 또는 standalone partition의 job 수를 함께 보존한다.
- C3e 이후 표시용 `providers`/`dataset_keys`는 저장 배열과 canonical exact pair의 유효값을
  합쳐 정렬·중복 제거한다. provider-only/dataset-only filter에는 쓸 수 있지만 두 배열을
  cross-product로 pair 복원하지 않는다. exact pair 정본은 required `provider_datasets[]`다.
  pair 근거는 import member의 typed `ops.import_jobs.provider`/`dataset_key`뿐이다. direct
  `provider_dataset` request scope는 linked pair와 같은 business target/`sync_scope` metadata이며
  독립 identity를 만들지 않는다. `ops.import_job_events`는 감사·타임라인 전용이며
  runtime identity·상관관계·filter에 사용하지 않는다. `ops.import_jobs.payload`도 identity 근거가
  아니다.

이 projection은 read contract만 정의한다. schedule/manual/update/import 실행을 같은
영속 operation row에 기록하는 모델·백필·migration은 T-ADM-C3e 범위다.

#### 9.8.2 Pipeline 계층형 취소 정본 (T-ADM-C3d, 이슈 #680, alembic 0050)

Pipeline 취소는 기존 lifecycle `status`에 중간 상태를 추가하지 않는다. 취소 요청을
base row의 **marker**로 먼저 차단하고, 시도·대상·Dagster run 결과는 정규화한 별도
테이블에 영속한다. 따라서 `ops.import_jobs.status`와
canonical `ops.import_jobs.status`의 기존 CHECK
(`queued`/`running`/`done`/`failed`/`cancelled`)는 그대로 유지한다. request table에는 lifecycle
status나 cancellation marker를 중복 저장하지 않는다.

```sql
CREATE TABLE ops.pipeline_cancellations (
  cancellation_id          UUID PRIMARY KEY
                           DEFAULT x_extension.gen_random_uuid(),
  previous_cancellation_id UUID REFERENCES ops.pipeline_cancellations(cancellation_id)
                           ON DELETE RESTRICT,
  root_kind                TEXT NOT NULL
                           CHECK (root_kind IN ('import_job', 'update_request')),
  root_id                  UUID NOT NULL,
  status                   TEXT NOT NULL DEFAULT 'in_progress'
                           CHECK (status IN
                             ('in_progress', 'retryable', 'completed', 'failed')),
  requested_by             TEXT NOT NULL,
  reason                   TEXT,
  error                    JSONB,
  requested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at              TIMESTAMPTZ,
  CHECK (previous_cancellation_id IS NULL OR
         previous_cancellation_id <> cancellation_id),
  CHECK ((status = 'in_progress' AND finished_at IS NULL) OR
         (status <> 'in_progress' AND finished_at IS NOT NULL)),
  CHECK ((status IN ('in_progress', 'completed') AND error IS NULL) OR
         (status IN ('retryable', 'failed') AND error IS NOT NULL AND
          jsonb_typeof(error) = 'object'))
);

CREATE UNIQUE INDEX uq_pipeline_cancellations_active_root
  ON ops.pipeline_cancellations (root_kind, root_id)
  WHERE status = 'in_progress';
CREATE INDEX idx_pipeline_cancellations_root_history
  ON ops.pipeline_cancellations
     (root_kind, root_id, requested_at DESC, cancellation_id DESC);

CREATE TABLE ops.pipeline_cancellation_runs (
  cancellation_id UUID NOT NULL REFERENCES ops.pipeline_cancellations(cancellation_id)
                  ON DELETE RESTRICT,
  dagster_run_id  TEXT NOT NULL,
  initial_status  TEXT,
  termination_reserved_at TIMESTAMPTZ,
  result          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (result IN
                    ('pending', 'cancelled', 'already_terminal', 'cancel_failed')),
  terminal_status TEXT,
  error           JSONB,
  engine_started_at  TIMESTAMPTZ,
  engine_finished_at TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    (engine_started_at IS NULL AND engine_finished_at IS NULL) OR
    (result IN ('cancelled', 'already_terminal') AND
     engine_finished_at IS NOT NULL AND
     (engine_started_at IS NULL OR engine_started_at <= engine_finished_at))
  ),
  CHECK (
    (termination_reserved_at IS NULL OR initial_status IS NOT NULL) AND (
      (result = 'pending' AND terminal_status IS NULL AND error IS NULL) OR
      (result = 'cancelled' AND terminal_status = 'CANCELED' AND error IS NULL) OR
      (result = 'already_terminal' AND
        (terminal_status IS NULL OR terminal_status IN ('SUCCESS', 'FAILURE')) AND
        error IS NULL) OR
      (result = 'cancel_failed' AND terminal_status IS NULL AND error IS NOT NULL AND
        jsonb_typeof(error) = 'object')
    )
  ),
  PRIMARY KEY (cancellation_id, dagster_run_id)
);

CREATE TABLE ops.pipeline_cancellation_members (
  cancellation_id UUID NOT NULL REFERENCES ops.pipeline_cancellations(cancellation_id)
                  ON DELETE RESTRICT,
  job_id          UUID NOT NULL REFERENCES ops.import_jobs(job_id)
                  ON DELETE RESTRICT,
  dagster_run_id  TEXT,
  initial_status  TEXT NOT NULL,
  result          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (result IN
                    ('pending', 'cancelled', 'already_terminal', 'cancel_failed')),
  terminal_status TEXT,
  error           JSONB,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    (result = 'pending' AND terminal_status IS NULL AND error IS NULL) OR
    (result = 'cancelled' AND terminal_status = 'cancelled' AND error IS NULL) OR
    (result = 'already_terminal' AND
      terminal_status IN ('done', 'failed', 'cancelled') AND error IS NULL) OR
    (result = 'cancel_failed' AND terminal_status IS NULL AND error IS NOT NULL AND
      jsonb_typeof(error) = 'object')
  ),
  PRIMARY KEY (cancellation_id, job_id),
  FOREIGN KEY (cancellation_id, dagster_run_id)
    REFERENCES ops.pipeline_cancellation_runs(cancellation_id, dagster_run_id)
    ON DELETE RESTRICT
);

CREATE INDEX idx_pipeline_cancellation_members_job
  ON ops.pipeline_cancellation_members
     (job_id, updated_at DESC, cancellation_id DESC);

ALTER TABLE ops.import_jobs
  ADD COLUMN cancellation_id UUID
    REFERENCES ops.pipeline_cancellations(cancellation_id) ON DELETE RESTRICT,
  ADD COLUMN cancellation_requested_at TIMESTAMPTZ,
  ADD COLUMN cancellation_requested_by TEXT,
  ADD COLUMN cancellation_reason TEXT,
  ADD CONSTRAINT ck_import_jobs_cancellation_marker CHECK (
    (cancellation_id IS NULL AND cancellation_requested_at IS NULL AND
     cancellation_requested_by IS NULL AND cancellation_reason IS NULL) OR
    (cancellation_id IS NOT NULL AND cancellation_requested_at IS NOT NULL AND
     cancellation_requested_by IS NOT NULL)
  );

```

`pipeline_cancellation_members`가 import job 취소 대상과 대상별 결과의 정본이다.
member 종류는 상수 `import_job`이므로 컬럼으로 중복 저장하지 않고 `job_id` FK로
정체성을 강제한다. 요청은 `pipeline_cancellations.root_kind='update_request'`와
`root_id`로 상관관계만 보존하며 member로 복제하지 않는다.
`pipeline_cancellation_runs`가 실제 terminate 호출과 run별 결과의 정본이다. 같은
`dagster_run_id`를 여러 member가 공유해도 run 행과 terminate 호출은 시도당 하나이며,
그 결과를 연결된 member에 전파한다. 응답용 summary/JSON snapshot은 이 정규화 행에서
계산하는 보조 표현일 뿐 대상 목록이나 결과의 정본으로 저장하지 않는다. member의
`initial_status`는 marker 직전 DB 상태이고, run의 nullable `initial_status`는 marker commit
뒤 첫 권위 있는 Dagster 조회가 성공했을 때 채운다. `error`는 code/message/details만 가진
비밀 제거 구조체이며 upstream raw body를 저장하지 않는다.

목록과 상세 조회는 base lifecycle 상태를 덮어쓰지 않고 다음 **current cancellation
overlay**를 별도 투영한다. current attempt는 같은 canonical root의 `in_progress` 행이 있으면
그 행, 아니면 `(requested_at DESC, cancellation_id DESC)` 최신 행이다. 시도 이력이 없으면
overlay는 `NULL`이다.

| 필드 | 의미 |
|------|------|
| `cancellation_id` | current attempt UUID |
| `status` | attempt workflow `in_progress`/`retryable`/`completed`/`failed` |
| `requested_at` / `requested_by` / `reason` | 인증 actor 기반 요청 감사 정보 |
| `retryable` | attempt `status='retryable'`일 때만 `true` |
| `unresolved_member_count` | current member 중 `pending` 또는 `cancel_failed` 수 |

attempt status는 결과 aggregate가 아니라 coordinator workflow 상태다. 처리 중이면
`in_progress`, 모든 member/run이 `cancelled`/`already_terminal`이면 `completed`, transient
외부 실패로 미해결 member를 다시 호출할 수 있으면 `retryable`, 권위 있는 reconcile
불가처럼 자동 재시도가 안전하지 않으면 `failed`다. 실제 결과는 member/run `result`에만 둔다.

`GET /v1/ops/pipeline/executions`의 각 root는 이 summary overlay를 반환한다. execution
detail은 같은 current attempt의 member/run 행도 함께 읽어 POST 응답을 잃은 reload 뒤에도
대상별 `result`/`terminal_status`/`error`를 복원한다. base `status`와 projected job
`status`는 overlay status로 대체하지 않는다. transient external 실패와 권위 있는
SUCCESS/FAILURE reconcile 불가 모두 member `cancel_failed`일 수 있지만, 전자는 attempt
`retryable`, 후자는 `failed`이므로 UI는 overlay의 `retryable`로 재시도 가능 여부를
판단한다.

취소 scope는 9.8.1의 root projection과 정확히 같다.

- update request는 자기 canonical root와 descendants 전체를 소유한다. request root가 다른
  request 아래에 있거나 같은 job을 공유하는 상태는 DB가 거부한다.
- standalone import root는 component의 미소유 partition만 포함한다. request branch의
  import job에서 취소하면 해당 owner request root로 canonicalize한다.
- cycle은 member 최소 UUID, 부모 누락은 self-root 규칙을 그대로 쓴다. root가 이미
  `done`/`failed`여도 active descendant가 있으면 root member만 `already_terminal`로
  기록하고 descendant 취소를 계속한다.

terminal/no-op은 durable하고 멱등적이다.

- root가 `done`/`failed`이고 active descendant가 없으며 이전 취소가 없다면 frozen terminal
  member를 `already_terminal`, attempt를 `completed`로 기록해 새로 남기고 200을 반환한다.
  외부 Dagster 호출은 없다.
- 같은 canonical root에 marker와 `status='completed'`인 최신 완료 attempt가 있으면 새
  attempt/audit/member를 만들지 않고 그 attempt의 member/run 결과를 그대로 200으로
  재현한다. Dagster terminate도 다시 호출하지 않는다.
- 최신 attempt가 `retryable`이면 no-op 재판정 대신 그 frozen scope의 미해결 member만
  재시도한다. lease 획득 실패만 동시 실행 409이며, lease를 얻은 뒤 발견한 `in_progress`는
  orphan으로 재개한다. definitive `failed`는 안전 조치 전까지 409를 유지한다. terminal root
  아래 active descendant가 있으면 일반 취소 절차를 계속한다.

최초 시도 transaction은 canonical root 키의 transaction advisory lock을 잡고 scope를 한 번만
계산한 뒤 frozen base row를 kind/UUID 순서로 잠근다. attempt, run, member와 terminal root를
포함한 모든 frozen base row marker를 함께 commit한다. child attach/enqueue도 같은 canonical
root lock을 먼저 잡고 ancestor marker를 확인해야 하므로 snapshot 직전·직후 child가 빠지는
창이 없다. ancestor에 marker가 있으면 새 child attach, enqueue, claim을 금지한다. worker의
claim/start/scope write/heartbeat/finish SQL도 모두 `cancellation_requested_at IS NULL` CAS를
요구한다. marker commit 뒤에만 외부 Dagster terminate를 호출하며, 외부 호출 동안 DB
transaction을 열어 두지 않는다.

marker guard는 위 lifecycle 함수 목록에 한정하지 않는다. lifecycle 단일 정본인
`ops.import_jobs`의 **모든 status/progress/stage/heartbeat/payload/run-id/
lineage(`parent_job_id`, `load_batch_id`) mutation**은 marker NULL 또는 취소 coordinator가 소유한
동일 `cancellation_id` CAS를 요구한다. `ops.feature_update_requests`에는 lifecycle·marker가 없으며,
유일한 가변 필드인 `matched_scope`와 `generation`은 연결 job이 active이고 marker가 없을 때만
변경한다. 여기에는
`update_import_job_payload`, `attach_import_jobs_to_batch`, stale recovery,
batch/load-batch attach, legacy cancel/requeue와 feature update의 내부 job start/finish가
포함된다. legacy REST cancel은 계층형 coordinator에 위임하고 직접 base status를 바꿀 수
없다. `ops.import_job_events` append와 cancellation/system audit append는 실행 제어 상태를
바꾸지 않으므로 marker 뒤에도 허용한다.

terminate 뒤에는 Dagster terminal 상태와 marker/attempt를 다시 확인해 짧은 transaction으로
확정한다.

- marker가 commit된 generic `queued` member(`requires_run_termination=false`)는 같은 marker를
  확인하는 finalize CAS로 즉시 DB `status='cancelled'`를 확정한다. C3e feature-load kind의
  `queued + dagster_run_id non-NULL` member는 `requires_run_termination=true`인 run-backed active라
  이 경로에서 제외한다. 이 member와 `running` member는
  Dagster `CANCELED`를 확인한 경우에만 base `status='cancelled'`로 바꾼다.
- Dagster `SUCCESS`/`FAILURE`는 member의 run id가 정확히 같고, marker가 같은
  `cancellation_id`를 가리키며, base row가 아직 active이고, terminal 조회가 권위 있는
  경우에만 reconcile한다. feature run의 `SUCCESS`는 frozen pair가 모두 `done`일 때만 root를
  `done`으로 만든다. non-done pair가 하나라도 있으면 이미 terminal인 pair는 보존하고 known active
  root/pair를 한 transaction에서 `tracking_invariant` failed로 닫으며 raw `SUCCESS`와 engine
  시각은 run/root에 보존한다. 일반 `FAILURE`는 `failed`로 reconcile한다. update request와 연결 job의 frozen
  member/run 대응이 불완전하면 안전하게 reconcile할 수 없는 경우다.
- `cancel_failed`는 frozen `initial_status='running'`이거나
  `requires_run_termination=true`인 member에 허용한다. generic queued member는 전용 DB 취소
  경로만 사용하며 failure로 우회할 수 없지만 run-backed feature queued는 terminate 실패/불명
  응답에서 base queued를 보존한 채 retryable `cancel_failed`가 될 수 있다. running+run-id 또는
  run-backed feature queued의 transient run 실패만 retryable이고, run-id 없는 running은
  definitive failed attempt라 retry에 복사하지 않는다.
  definitive `cancel_failed`는 run id가 없거나, 관측한 marker/status/run이 frozen base와
  다르거나, exact base에 대응하는 run 자체가 definitive 오류 코드와 함께
  `cancel_failed`인 경우만 허용한다. 이 경로는 base와 run을 절대 변경하지 않는다. 특히
  Dagster run id 없는 local/standalone `running` job은
  정지 여부를 증명할 수 없으므로 base 상태를 `running`으로 보존하고 marker도 유지한다.
- GraphQL/HTTP 오류·timeout·`TerminateRunFailure`·`RunNotFound`는 먼저 `cancelled`로 쓰지
  않는다. attempt를 `retryable`, 해당 run-termination-required member/run을 `cancel_failed`로 기록하고
  marker를 유지한다.

일반 coordinator writer는 attempt 행을 `FOR UPDATE`로 먼저 잠그고
`status='in_progress'`를 확인한 뒤 member→해당 run→canonical import job 순서로 잠근다.
성공 결과를 쓰는 범용 member setter는 두지 않는다. run-termination-required member는 먼저 run 행이
`CANCELED`/`SUCCESS`/`FAILURE`로 종결된 뒤에만 각각
`cancelled`/`done`/`failed`로 전이한다. generic queued member만 외부 terminate 호출이 없는 전용
DB 경로로 `cancelled`가 된다. exact frozen base와 terminal `SUCCESS`/`FAILURE`가 있으면
안전 전이가 가능하므로 definitive failure로 닫지 않는다. 예외적으로 계층 전체를 다루는
attempt 종결/retry와
batch phase writer는 교착 방지를 위해
lineage-global→정렬 canonical root→source attempt `FOR UPDATE`→detail reload→정렬 base
행 순서를 사용한다. 이미 닫힌 예전 attempt writer는 상태를 바꾸지 않고 CAS 실패를
반환한다.

`completed`는 marker·base·member·run 전체 대응이 정확하고 pending/cancel_failed가 0일
때만 허용한다. `retryable`은 pending이 없고 exact marker/status/run을 유지한
`requires_run_termination=true`
미해결 member가 하나 이상이며 모든 대응 run/member의 구조화 오류 코드가 재시도 허용
집합일 때만 허용한다. `failed`는 operator 개입이 필요한 definitive attempt 오류가 있을 때
사용한다. 이때 다른 run/member에서 이미 관측한 timeout/unavailable 같은 retryable 오류와
아직 권위 있게 관측하지 못한 pending 결과를 definitive 오류로 덮지 않고 그대로 보존한다.
알려진 base/run mismatch만 해당 member의 definitive `cancel_failed`로 기록하며,
unexpected coordinator 오류도 pending/terminal run을 거짓 `cancel_failed`로 만들지 않는다.

재시도는 `previous_cancellation_id`가 가리키는 이전 시도의 frozen member 중
`requires_run_termination=true AND result='cancel_failed'`인 행만
새 attempt로 복사한다. hierarchy를 다시 탐색하지 않으며, 복사한 base marker의
`cancellation_id`만 새 시도로 CAS 전환한다. 이미 `cancelled`/`already_terminal`인 member와
run은 재호출하지 않는다. 이 규칙과 ancestor marker가 최초 snapshot 뒤에 생성된 child가
취소 scope 밖으로 빠지는 경쟁을 막는다. marker는 terminal 확정 뒤에도 durable audit와
descendant 생성 차단을 위해 지우지 않으며, retry CAS만 새 attempt id로 바꿀 수 있다.

취소 coordinator는 preliminary canonical resolve 뒤 canonical root마다 별도 session-level
advisory lease(`pipeline-cancellation:coordinator:{root_kind}:{root_id}`)를 non-blocking으로
먼저 잡고, 획득 transaction을 commit한 다음 prepare transaction을 시작한다. lease 획득 전에는
attempt/marker를 생성하지 않으며, 순서는 `preliminary resolve → dedicated lease acquire/commit →
prepare(lineage-global→root→scope/marker/audit) → external → finish → unlock`이다. engine에서
전용 `AsyncConnection` 하나를 얻고 `AsyncSession(expire_on_commit=False)`을 bind해 lease 획득부터
exact unlock까지 같은 backend를 물리적으로 pin한다. prepare/queued finalize/reservation/
run-member reconcile/finish는 각각 명시적인 짧은 transaction이고 phase 사이와 GraphQL/poll 동안
`session.in_transaction()`은 false여야 한다. acquire SELECT의 autobegin은 성공/실패 직후
commit/rollback한다. lease 경합만 동시 실행 409이며, lease를 얻은 뒤 발견한
`in_progress` attempt는 process crash가 남긴 orphan으로 보고 같은 frozen detail을 재개한다.
running run의 active 상태를 확인한 뒤에는 외부 호출 전에
`pipeline_cancellation_runs.termination_reserved_at` NULL CAS, 첫 권위 관측 `initial_status`, 감사
로그를 같은 transaction으로 먼저 commit한다. CAS 패자는 외부 mutation을 호출하지 않고
reserved query/poll 경로로 전환한다.
이미 값이 있으면 같은 attempt에서 `terminateRun`을 다시 보내지 않고 terminal poll만 재개한다.
reservation 뒤 mutation HTTP timeout·응답 유실도 재호출하지 않고 같은 poll 경로로 합류한다.
CAS commit 직후 실제 HTTP 호출 전 process가 죽은 경우에도 동일 attempt의 중복 dispatch는 없으며,
poll 미종결을 `DAGSTER_TERMINATION_TIMEOUT` retryable attempt로 닫고 503을 반환한 다음 새
attempt가 다시 시도한다. 따라서 보장 범위는 외부
exactly-once가 아니라 **attempt별 at-most-once dispatch**다. 최초 canonical root 조회와 lease
획득 사이에 root가 바뀌면 lease를 풀고 새 canonical root로 제한된 횟수만 다시 시작하며,
반복 변경은 409 `PIPELINE_CANCELLATION_UNSAFE`로 닫는다. 기존
lineage-global/root transaction lock을 lease로 대체하지 않는다.
lease 해제는 획득한 exact key를 같은 backend에서 `pg_advisory_unlock`하고 true를 확인한 뒤
commit한다. false/예외이면 성공을 반환하지 않는다. async invalidate가 실패하면 pool proxy의
hard invalidate, 마지막으로 physical driver terminate를 시도하고, backend 폐기를 증명하지
못하면 unsafe 오류를 전파한다. lease 상실이나 reservation/base CAS 패배를 감지한 old
coordinator는 후속 외부 호출·결과 write를 중단하고 fresh session에서 exact 과거 attempt보다
canonical root의 current detail을 우선 reload한다.

feature update coordinator는 scope별 commit으로 이미 완료된 데이터와 외부 효과를
rollback하지 않는다. provider scope 동시 실행 창을 만들지 않기 위해 engine에서 얻은 전용
`AsyncConnection` 하나에 session-level scope advisory lock을 잡고 prepare/probe/scope/finalize의
짧은 transaction을 모두 같은 물리 connection에 bind한다. 같은 connection에서 unlock한 뒤
pool에 반환하며, pin하지 않은 pooled `AsyncSession`에서 scope 사이 commit을 반복하지 않는다.
각 scope data transaction은 provider 결과를 쓰기 전에 request와 canonical job을 잠그고 job
marker NULL을 확인한다. scope transaction이 먼저 잠갔다면 그 scope commit까지는 취소가 기다리고,
job marker가 먼저 commit됐다면 scope data write를 시작하지 않는다.
queue sensor는 상태를 바꾸지 않고 peek만 하며, executor가 request별 session lease와 scope
session lease를 얻은 뒤 canonical job을 CAS start한다. scope 경합이면 canonical job의 stale run
identity·progress·timestamp를 초기화해 queued로 돌리고 request의 양수 정수 `generation`을
정확히 1 증가시킨다. request lease 경합의 queued loser도
`(request_id, expected_generation)` CAS에 처음 성공한 한 run만 generation을 1 증가시키며 running
owner는 건드리지 않는다. sensor는 이 정수를 run key·op config·run tag에 고정한다. start 호출은
trimmed non-empty Dagster run owner를 필수로 받고,
`queued + generation 동일 + run-id NULL` 또는 `running + 동일 non-null run owner`만 허용한다. CAS start 전
resource 초기화 실패도 같은 queued generation에서 처음 성공한 호출만 +1하고, 더 최신
generation·terminal·marker 행은 변경하지 않는다. 예전 Dagster run의 지연 failure sensor는 실제
run id를 단일 `owner_dagster_run_id`로 전달하고 canonical job owner가 정확히 같을 때만 failed로
닫는다. 각 provider scope의
data write와 `matched_scope.executed_provider_scopes` checkpoint는 같은 transaction에 commit한다.
production asset이 사용하는 `AsyncKorTravelMapClient`도 executor session의 physical connection에
bind하고 내부 session은 outer transaction을 commit하지 못하게 한다. bind 뒤 원본 client의
engine으로 새 connection을 여는 public 경로는 fail-closed로 거부한다. 따라서 asset chunk
적재·`provider_sync_state`·checkpoint가 하나의 scope transaction이고, checkpoint 전 crash가
data-only commit을 남기지 않는다. 이후 취소·실패·process 종료에도 이미 반영된 scope를
식별할 수 있다. marker 없는 `CancelledError`는 canonical job을 failed로 닫고 원 예외를
재전파하며, marker가 있으면 coordinator가 상태 전이를 우선한다.

full-load batch consistency gate도 같은 원칙을 사용한다. 호출별 전용
`AsyncConnection`에 `AsyncSession(expire_on_commit=False)`을 bind하고
`load_batch_id`별 session advisory mutex를 gate 전체에 유지한다. prepare(root 생성·child
attach·consistency child 생성), 장기 consistency+gate finalize, MV child 시작, 장기 MV
refresh+finalize는 각각 독립 transaction이다. 장기 consistency/MV는 시작 marker guard 뒤
lineage lock 없이 side effect를 만들고, 종료 직전에만 lineage-global→canonical root lock을
얻어 marker guard/CAS와 finalize를 같은 transaction에서 수행한다. MV child 시작(Tx3)과
실패 기록 transaction은 첫 mutation 전에 같은 canonical lock을 얻는다. marker/CAS가
패배하면 내부 sentinel 예외로 현재 transaction의 report/MV write 전체를 rollback하고,
별도 짧은 read transaction에서 cancellation 결과를 reload한다. child row를 먼저 잠근 뒤
global/root lock을 요구하는 순서는 허용하지 않는다. lock과 각 phase는
같은 PostgreSQL backend PID를 사용하고, unlock SELECT 뒤 commit한 다음 connection을 pool에
반환한다.

marker/attempt/member/run 전이는 각각 같은 짧은 transaction에서 append-only
`ops.system_log` 감사 행도 함께 기록한다. 인증 actor가 `requested_by`와
`cancellation_requested_by`의 유일한 출처이며 요청 payload가 이를 덮어쓸 수 없다. 0050
downgrade는 queued/running base row의 marker 또는 `in_progress`/`retryable` 시도가 하나라도
있으면 실패해야 한다. terminal base row와 `completed`/`failed` 시도만 남았을 때 명시적
운영 확인 후 테이블/컬럼을 제거하며, active marker를 조용히 drop해 worker를 재개시키는
downgrade는 금지한다.

#### 9.8.2a C6c cancel-probe fixture 수명주기 (T-VN-41F1J, ADR-086)

C6c/F1D가 검증할 `running` + `dagster_run_id IS NULL` member는 provider workload에서
우연히 얻지 않는다. Map이 fixture transaction ID마다 job을 만들고 canonical cancellation과
연결한다. fixture lifecycle을 Manager 환경변수나 PinVi DB에 저장하면 Map cancellation marker와
별개의 정본이 생기므로 금지한다.

```sql
CREATE TABLE ops.c6c_cancel_probe_fixtures (
  transaction_id UUID PRIMARY KEY,
  job_id UUID NOT NULL UNIQUE
      REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  state TEXT NOT NULL CHECK (state IN ('armed', 'consumed', 'finalized')),
  cancellation_id UUID UNIQUE
      REFERENCES ops.pipeline_cancellations(cancellation_id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  consumed_at TIMESTAMPTZ,
  finalized_at TIMESTAMPTZ,
  CHECK (
    (state = 'armed' AND cancellation_id IS NULL
      AND consumed_at IS NULL AND finalized_at IS NULL)
    OR (state = 'consumed' AND cancellation_id IS NOT NULL
      AND consumed_at IS NOT NULL AND finalized_at IS NULL)
    OR (state = 'finalized' AND cancellation_id IS NOT NULL
      AND consumed_at IS NOT NULL AND finalized_at IS NOT NULL
      AND finalized_at >= consumed_at)
  )
);
```

`job_id`와 `cancellation_id`의 UNIQUE 제약이 두 FK의 lookup index를 겸한다. transaction
ID PK 외에는 이 테이블을 scan하지 않으므로 추가 index를 만들지 않는다. `armed` 생성은
`kind='c6c_cancel_probe'`, `status='running'`, `dagster_run_id=NULL`인 `ops.import_jobs` row와
같은 transaction에서 일어난다. 기존 pipeline cancel은 marker/attempt/member/run을 만든 뒤
fixture row를 `consumed`로 원자 전이한다. `finalized`는 이 canonical history를 보존하면서
job만 fixture 전용 guarded write로 terminal `failed`로 닫는다.

이 kind는 generic worker dispatch/claim, stale recovery, normal lifecycle mutation과
canonical `ops:read` execution projection에서 제외한다. fixture API의 `PUT`은 transaction
ID 멱등 키이고, `GET`과 `POST finalize`는 durable state만 보고 crash 뒤 다음 호출을
결정한다. `consumed` state에서 cancel을 재발행하거나 `finalized` fixture를 re-arm하는 것은
금지한다. API/auth/capability generation은
[`c6c-cancel-probe-fixture.md`](c6c-cancel-probe-fixture.md)가 정본이다.

### 9.8.3 Canonical provider operation 계층 (T-ADM-C3e, 이슈 #679, alembic 0051)

schedule, manual, sensor, backfill로 실행한 Dagster provider asset과 update/import 실행은
제3 operation 테이블을 만들지 않고 기존 `ops.import_jobs` hierarchy와
`ops.feature_update_requests` root를 사용한다. 외부 correlation 정본은 UUID 단독이 아닌
`(kind, id)`다. `dagster_run_id`는 실행 엔진 속성이고 목록 cursor는 C3b의
`(created_at DESC, id DESC, kind DESC)`를 유지한다.

Dagster feature-load run은 다음 두 단계다.

- `kind='provider_feature_load_run'`: Dagster run당 standalone root 한 건. `parent_job_id`,
  `provider`, `dataset_key`는 NULL이고 `dagster_run_id`와 `trigger_kind`는 non-NULL이다.
- `kind='provider_feature_load'`: 선택된 exact provider/dataset pair당 child 한 건.
  `parent_job_id`는 위 root, provider/dataset은 둘 다 non-empty이며 root와 같은
  `dagster_run_id`를 가진다. `trigger_kind`는 root에서 상속하므로 child에서는 NULL이다.

따라서 한 MCST run의 13 dataset이나 multi-asset manual run도 pipeline root는 하나다.
`provider_datasets[]`는 선택된 import job member의 `job_id`, exact pair, pair lifecycle status를
보존하고,
표시용 `providers[]`/`dataset_keys[]`의 cross-product로 만들지 않는다. C3d 취소는 root와
모든 child를 같은 frozen scope에 넣고 공유 Dagster run을 한 번 terminate한다. dataset
하나에서 시작했더라도 같은 run의 다른 pair만 살리는 부분 취소는 지원하지 않는다.
update request root도 owned import member 실컬럼 pair만 사용한다. direct
`scope.type='provider_dataset'`은 DB에서 linked typed pair와 일치하므로 같은 pair의 nullable
`sync_scope` metadata만 보강한다. pair는 항상 non-null member id와 member status를 가진다.

C3b 공용 root projection은 pipeline timeline, datasets grid/detail뿐 아니라 pipeline overview
status count와 최근 24시간 failure도 소유한다. overview는 raw `import_jobs`를 세지 않고 request
branch 또는 standalone partition의 canonical root를 한 번만 세며, MCST 13 child도 operation
1건이다. 기존 import/update 분리 count는 `operations_by_status`, queued+running root 합계
`active_operations`, `failed_operations_24h` canonical 집계로 교체한다.
`provider_feature_load_run`의
`projected_job`은 UUID 순서로 고른 임의 pair child가 아니라 root 자체로 고정하고 pair별 상태는
`provider_datasets[]`에서만 읽는다.

0057의 datasets grid/detail은 이 공용 root projection을 한 SQL snapshot으로 읽고 exact
`(provider, dataset_key, sync_scope)`별 `pair.status`를 `queued|running` 활성 그룹과
`done|failed|cancelled` 종료 그룹으로 나눈다. 각 그룹에서
`(created_at DESC, id DESC, kind DESC)` 첫 행을 선택하므로, 더 최근 종료 실행 때문에 아직
살아 있는 실행이 가려지거나 반대로 활성 실행 때문에 마지막 완료 결과가 사라지지 않는다.
논리 `dataset_wide`만 같은 snapshot의 typed `dataset_wide`와 과거 nullable pair를 각각 비교해
더 최신 값을 고른다. 실행 이력 cursor v3는 kind/status/provider/dataset/scope 집합,
load batch/parent job, created 시간 범위의 fingerprint를 포함한다. 페이지 사이에 어느 filter라도
바뀌면 SQL을 실행하기 전에 typed mismatch로 거부한다.

0051은 다음 nullable 실컬럼과 제약을 추가한다.

```sql
ALTER TABLE ops.import_jobs
  ADD COLUMN provider TEXT,
  ADD COLUMN dataset_key TEXT,
  ADD COLUMN trigger_kind TEXT,
  ADD COLUMN operation_registry_version TEXT,
  ADD COLUMN dagster_run_status TEXT,
  ADD CONSTRAINT ck_import_jobs_provider_dataset_pair CHECK (
    (provider IS NULL AND dataset_key IS NULL) OR
    (provider IS NOT NULL AND provider = btrim(provider) AND provider <> '' AND
     dataset_key IS NOT NULL AND dataset_key = btrim(dataset_key) AND dataset_key <> '')
  ),
  ADD CONSTRAINT ck_import_jobs_trigger_kind CHECK (
    trigger_kind IS NULL OR trigger_kind IN
      ('schedule', 'manual', 'sensor', 'update_request', 'backfill', 'system')
  ),
  ADD CONSTRAINT ck_import_jobs_registry_version_owner CHECK (
    operation_registry_version IS NULL OR kind = 'provider_feature_load_run'
  ),
  ADD CONSTRAINT ck_import_jobs_dagster_run_status CHECK (
    dagster_run_status IS NULL OR (
      kind = 'provider_feature_load_run' AND dagster_run_status IN
      ('QUEUED', 'NOT_STARTED', 'MANAGED', 'STARTING', 'STARTED', 'CANCELING',
       'SUCCESS', 'FAILURE', 'CANCELED')
    )
  ),
  ADD CONSTRAINT ck_import_jobs_feature_tracking_shape CHECK (
    (kind <> 'provider_feature_load_run' OR
      (parent_job_id IS NULL AND provider IS NULL AND dataset_key IS NULL AND
       dagster_run_id IS NOT NULL AND dagster_run_id = btrim(dagster_run_id) AND
       dagster_run_id <> '' AND trigger_kind IS NOT NULL AND
       operation_registry_version IS NOT NULL AND
       dagster_run_status IS NOT NULL AND
       operation_registry_version = btrim(operation_registry_version) AND
       operation_registry_version <> '')) AND
    (kind <> 'provider_feature_load' OR
      (parent_job_id IS NOT NULL AND provider IS NOT NULL AND
       dataset_key IS NOT NULL AND dagster_run_id IS NOT NULL AND
       dagster_run_id = btrim(dagster_run_id) AND dagster_run_id <> '' AND
       trigger_kind IS NULL AND operation_registry_version IS NULL AND
       dagster_run_status IS NULL))),
  ADD CONSTRAINT ck_import_jobs_feature_engine_timeline CHECK (
    kind NOT IN ('provider_feature_load_run', 'provider_feature_load') OR
    ((started_at IS NULL OR created_at <= started_at) AND
     (finished_at IS NULL OR created_at <= finished_at) AND
     (started_at IS NULL OR finished_at IS NULL OR started_at <= finished_at))
  );

ALTER TABLE ops.pipeline_cancellation_runs
  ADD COLUMN engine_started_at TIMESTAMPTZ,
  ADD COLUMN engine_finished_at TIMESTAMPTZ,
  ADD CONSTRAINT ck_pipeline_cancellation_runs_engine_times CHECK (
    (engine_started_at IS NULL AND engine_finished_at IS NULL) OR
    (result IN ('cancelled', 'already_terminal') AND
     engine_finished_at IS NOT NULL AND
     (engine_started_at IS NULL OR engine_started_at <= engine_finished_at))
  );

ALTER TABLE ops.pipeline_cancellation_members
  ADD COLUMN operation_kind TEXT,
  ADD COLUMN requires_run_termination BOOLEAN NOT NULL DEFAULT false;

UPDATE ops.pipeline_cancellation_members AS member
   SET operation_kind = CASE
     WHEN job.kind = btrim(job.kind) AND job.kind <> '' THEN job.kind
     ELSE NULL
  END
  FROM ops.import_jobs AS job
 WHERE member.job_id = job.job_id;

UPDATE ops.pipeline_cancellation_members
   SET requires_run_termination = true
 WHERE dagster_run_id IS NOT NULL
   AND (
     initial_status = 'running' OR (
       initial_status = 'queued' AND operation_kind IN
         ('provider_feature_load_run', 'provider_feature_load')
     )
   );

ALTER TABLE ops.pipeline_cancellation_members
  ADD CONSTRAINT ck_pipeline_cancellation_members_operation_kind CHECK (
    operation_kind IS NULL OR (
      operation_kind = btrim(operation_kind) AND operation_kind <> ''
    )
  ),
  ADD CONSTRAINT ck_pipeline_cancellation_members_run_termination CHECK (
    requires_run_termination = (
      dagster_run_id IS NOT NULL AND (
        initial_status = 'running' OR (
          initial_status = 'queued' AND COALESCE(
            operation_kind IN ('provider_feature_load_run', 'provider_feature_load'),
            false
          )
        )
      )
    )
  );

CREATE FUNCTION ops.check_feature_operation_parent() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  parent_kind TEXT;
  parent_run_id TEXT;
  parent_created_at TIMESTAMPTZ;
BEGIN
  SELECT kind, dagster_run_id, created_at
    INTO parent_kind, parent_run_id, parent_created_at
    FROM ops.import_jobs
   WHERE job_id = NEW.parent_job_id
   FOR KEY SHARE;
  IF NOT FOUND OR parent_kind <> 'provider_feature_load_run'
     OR parent_run_id IS DISTINCT FROM NEW.dagster_run_id
     OR parent_created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'invalid provider feature operation parent/run/create time'
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER ck_import_jobs_feature_operation_parent
  AFTER INSERT OR UPDATE OF kind, parent_job_id, dagster_run_id, created_at
  ON ops.import_jobs
  DEFERRABLE INITIALLY IMMEDIATE
  FOR EACH ROW
  WHEN (NEW.kind = 'provider_feature_load')
  EXECUTE FUNCTION ops.check_feature_operation_parent();

CREATE FUNCTION ops.reject_feature_operation_identity_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.kind IN ('provider_feature_load_run', 'provider_feature_load')
     OR NEW.kind IN ('provider_feature_load_run', 'provider_feature_load') THEN
    IF ROW(OLD.kind, OLD.parent_job_id, OLD.dagster_run_id, OLD.provider,
           OLD.dataset_key, OLD.trigger_kind, OLD.operation_registry_version,
           OLD.created_at)
       IS DISTINCT FROM
       ROW(NEW.kind, NEW.parent_job_id, NEW.dagster_run_id, NEW.provider,
           NEW.dataset_key, NEW.trigger_kind, NEW.operation_registry_version,
           NEW.created_at) THEN
      RAISE EXCEPTION 'provider feature operation identity is immutable'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER ck_import_jobs_feature_operation_identity_immutable
  BEFORE UPDATE OF kind, parent_job_id, dagster_run_id, provider, dataset_key,
                   trigger_kind, operation_registry_version, created_at
  ON ops.import_jobs
  FOR EACH ROW
  EXECUTE FUNCTION ops.reject_feature_operation_identity_mutation();

CREATE UNIQUE INDEX uq_import_jobs_feature_run
  ON ops.import_jobs (dagster_run_id)
  WHERE kind = 'provider_feature_load_run' AND parent_job_id IS NULL;

CREATE UNIQUE INDEX uq_import_jobs_feature_run_pair
  ON ops.import_jobs (parent_job_id, provider, dataset_key)
  WHERE kind = 'provider_feature_load' AND parent_job_id IS NOT NULL;

CREATE INDEX idx_import_jobs_provider_dataset_created
  ON ops.import_jobs (provider, dataset_key, created_at DESC, job_id DESC)
  WHERE provider IS NOT NULL AND dataset_key IS NOT NULL;

CREATE INDEX idx_import_jobs_dataset_created
  ON ops.import_jobs (dataset_key, created_at DESC, job_id DESC)
  WHERE dataset_key IS NOT NULL;

CREATE INDEX idx_import_jobs_provider_created
  ON ops.import_jobs (provider, created_at DESC, job_id DESC)
  WHERE provider IS NOT NULL;
```

0052는 선택적 pipeline list/detail이 전체 graph를 먼저 투영하지 않도록 request
provider/dataset `TEXT[]`에 GIN seed access path를 추가한다. exact/direct pair는 별도
expression index 없이 위 0051 typed job index만 쓴다. seed job에서 `parent_job_id` PK/FK index를 양방향으로 따라
connected component를 만든 뒤 그 component의 request만 공용 canonical projection에 공급한다.
event는 projection에서 읽지 않는다. event의 migration-owned `quarantined_at` marker와
visible-only partial index는 각각 무필터→`idx_import_job_events_time`, job→
`idx_import_job_events_job_time`, provider→`idx_import_job_events_provider_time`, provider+dataset exact pair→
`idx_import_job_events_provider_dataset_time`, level→`idx_import_job_events_level_time` 감사
타임라인을 담당하며 identity seed가 아니다. 모든 조합은 `quarantined_at IS NULL`을 event에
직접 적용한다. Parent 상태를 page-time에 join하지 않으므로 최신 격리 event 수와 무관하게
page 크기만큼 bounded scan을 유지한다. 감사 조회는 filter가 실제로 있을 때만 해당 고정
predicate를 SQL에 넣어 prepared/generic plan에서도 partial index를 쓸 수 있게 한다.
0057부터 provider namespace 밖에서 의미가 없는 dataset-only event 조회를 repository와 REST가
거부하고 `idx_import_job_events_dataset_time`도 제거해 append 쓰기 증폭을 줄인다.

또한 `feature_update_requests.job_id`를 `NOT NULL ON DELETE RESTRICT`로 바꾸고 direct scope와
provider/dataset filter shape CHECK, request/canonical job kind·pair 교차검증 trigger, 전역
import job kind/pair 불변 trigger를 추가한다.
upgrade/downgrade 첫 동작으로 cancellation→request→import job→event→event clock(존재 시)
순서의 `ACCESS EXCLUSIVE` lock을
하나의 `NOWAIT` 문장으로 잡아 repair와 제약 설치 사이에 구 writer/reader가 들어오지 못하게
한다. 일부 relation만 잡힌 시도는 savepoint rollback으로 모두 풀고 30초 안에서 재시도한다.
jobless, scope와 pair가 불일치하거나 reserved Dagster
kind에 연결된 request는 request별 새 canonical job에 재연결하고 이전 job ID를 migration audit
payload에 보존한다. cancellation marker나
frozen member가 있는 후보는 동결 집합을 바꾸지 않고 request ID와 함께 중단한다.
upgrade는 기존 non-unique `idx_feature_update_job`을 제거하고
`uq_feature_update_requests_job_id`의 unique B-tree를 역추적 access path로 사용한다. downgrade는
unique·양방향 trigger·deferred FK를 제거하고 nullable/`SET NULL` 및 원래 partial index를 복원하되
생성된 canonical job과 격리 component의 원래 `kind`·`payload`는 보존한다.

0051의 일회성 backfill만 과거 event를 읽는다. direct request backfill은 연결된 request 전체가
정확히 1건이고 그 행이 string·trimmed non-empty `provider_dataset` exact pair일 때만 허용한다.
연결 request가 없을 때만 identity-bearing event 전체가 같은 완전 pair인 job을 typed column으로
옮긴다. multi-pair·partial·blank·ambiguous 행은 `(NULL,NULL)`로 남으며 runtime에서 되살리지 않는다.

0051은 malformed legacy import kind를 trim해 다른 identity로 바꾸지 않고 NULL로 남기며 그 건수를
migration 진단 로그에 기록한다. 신규 cancellation snapshot writer는 trim된 non-empty
`operation_kind`만 허용한다. running+run-id의 `requires_run_termination=true` 백필은
`operation_kind`가 NULL이어도 유지된다.
0051 이전에는 feature-load reserved kind가 없으므로 legacy queued generic+run-id의 false는 migration으로,
queued feature의 true는 0051 이후 canonical snapshot 경로로 검증한다.

event-backed `QUEUED|STARTING|STARTED|CANCELING` 각각의 run-status sensor 집합이 권위 있는 run selection의
root와 모든 pair child를 provider resource 초기화와 독립된 한 transaction에서 ensure한다.
Dagster event mapping이 없는 `NOT_STARTED|MANAGED`는 periodic scan/guard가 같은 client에
queued-like 관측으로 전달한다. `QUEUED|NOT_STARTED|MANAGED|STARTING` 관측은 base `queued`,
`STARTED|CANCELING` 관측은 marker CAS로 `running`에 전이한다. main package의
raw status type은 문자열 Literal이고 Dagster package를 import하지 않는다. root
`dagster_run_status`는 queued-like→STARTED/CANCELING→terminal 방향으로만 CAS 전이하고 terminal
뒤에는 불변이다. 모든 live provider record
resource는 DB-only `feature_operation_guard` resource에 의존해 provider resource factory보다
먼저 같은 ensure/marker 검사를 수행한다. wrapper 호출은 raw runner 직전의 마지막 멱등
fallback이다. ensure는 `INSERT ... ON CONFLICT`로 동시에 여러 번 호출해도 같은 ID로 수렴한다.
상태 전이는 absent+queued-like→queued, absent/queued+STARTED/CANCELING→running뿐이다. running에
늦게 온 queued-like/STARTED는 noop이고 terminal/marker 행은 blocked이므로 sensor delivery
순서가 뒤집혀도 base 상태가 역전되지 않는다.
기존 root에 child를 붙일 때는 C3d와 같은 lineage-global→canonical root lock과 marker guard를
사용하고 parent kind, child/root run id, root trigger/registry version, terminal 상태를
검증하므로 취소 frozen scope 뒤 새 pair가 빠져나오거나 다른 run parent에 붙지 않는다.
불일치는 부분 write 없이 durable invariant conflict다. wrapper는 자기 pair child
성공만 `done`으로 전이하고 body exception은 event만 남긴다. step retry는 같은 running
child를 재사용한다.
run terminal sensor가 모든 retry 뒤 root terminal을 소유한다. `SUCCESS`는 registry selection과
DB child set이 같고 모든 child가 wrapper/callback에 의해 이미 `done`일 때 root만 `done`으로
바꾼다. child set이 다르면 누락 child를 보정 생성하지 않고 structural conflict를 기록하되
active root와 알려진 active child를 같은 transaction에서 `tracking_invariant` failed로 닫아
terminal Dagster run 아래 active DB 행을 남기지 않는다. set은 같아도 `done`이 아닌
queued/running/failed/cancelled child가 남은 경우 known active root/child를 같은 invariant
`failed`로 닫고 이미 terminal인 child는 보존하며 raw
Dagster `SUCCESS`는 별도 필드에 보존한다. `FAILURE`는 남은 active
`queued|running` child와 root를 `failed`로 바꾼다. C3d marker 없는 외부 `CANCELED`는 row가
없으면 selection 전체를 ensure한 뒤 active `queued|running` child/root를 `cancelled`로 바꾸고,
marker가 있으면 coordinator 결과를
기다리며 base row를 수정하지 않는다. 이미 terminal인 행도 sensor/retry가 다시 열거나 덮지
못한다.

pair child는 queued/running에서 `progress=0`, 성공하면 `progress=100`이다. root progress는 매
pair 완료와 terminal reconcile transaction에서
`floor(100 * done_child_count / total_child_count)`로 재계산한다. exact `SUCCESS`는 100이고 partial
failure/cancel은 완료 pair 비율을 보존한다. `current_stage`는
`queued|loading|completed|failed|cancelled|tracking_invariant`만 사용한다. failure/cancel은
root와 대상 active child의 redacted error, stage, authoritative finish time을 같은 CAS에 쓴다.

constraint trigger 함수는 feature child에만 적용해 parent row의
`kind='provider_feature_load_run'`과 동일한 non-NULL `dagster_run_id`를 검사한다. generic batch
hierarchy는 서로 다른/NULL Dagster run을 합법적으로 연결할 수 있으므로 전역 composite FK를
추가하지 않고 기존 `parent_job_id ... ON DELETE SET NULL` 의미도 바꾸지 않는다. trigger와
함수는 downgrade에서 child/root kind 데이터 안전성 확인 뒤 제거한다. companion identity
trigger는 feature root/child의 kind, parent, run, pair, trigger, registry version, engine create
time을 insert 뒤 바꾸지 못하게 해 parent-side update 우회도 막는다. feature root를 child보다
먼저 삭제하면 기존 `ON DELETE SET NULL`이 child identity trigger에 거부되므로 feature hierarchy
삭제는 child→root 순서만 가능하고 제품 API는 operation 삭제를 제공하지 않는다.

MCST 같은 multi-pair raw runner에는 wrapper가 nullable async pair-completion callback을
주입한다. 빈 입력을 정상 확인했거나 pair `_load`가 성공한 직후 child를 `done`으로 전이한다.
raw runner 자체는 repository를 import하지 않으며 callback 없는 feature-update 경로의 tracking
side effect는 0이다. 후반 pair 실패 시 완료 child는 done을 유지하고 남은 child만 failure
sensor가 failed로 끝낸다.

pre-resource failure로 wrapper가 실행되지 않았으면 sensor가 권위 있는 asset selection과
canonical registry에서 exact pair를 복구할 때만 root/child를 만든다. 복구할 수 없는 비등록
임의 user-code job은 Dagster 보조 패널-only 실행이다. registry에 등록된 feature-load
job/selection의 version, resolved snapshot, run config 또는 identity tag가 누락·불일치하면
guard가 provider resource factory보다 먼저 typed error로 fail-closed한다. 이 경우 provider I/O와
DB load는 0이고 redacted durable conflict를 남긴다. job definition은 identity tag만 가지며
schedule/manual/sensor launch가 각각 trigger tag를 넣어 manual 실행을 schedule로 오분류하지
않는다. actor는 C3d `requested_by`이며 `trigger_kind`와 섞지 않는다.

generic `recover_stale_running_jobs`는 `provider_feature_load_run`과
`provider_feature_load`를 항상 제외한다. 놓친 terminal event와 daemon 재시작은 주기적
provider-resource-free reconciliation sensor가 복구한다. Dagster→DB scan은 등록 run을
`(engine_created_at,run_id)` watermark 뒤부터 읽어 missing root도 ensure/reconcile하고 한 page의
DB commit 뒤에만 명시 sensor cursor를 전진시킨다. DB→Dagster scan은 기존 queued/running root를
`(created_at,root_job_id)` keyset page로 다시 조회한다. 마지막 page의 `next_cursor=NULL`이면 다음
tick은 beginning부터 새 sweep을 시작하므로 장기 active run의 후속 terminal과 scan 도중 과거
engine create 시각으로 늦게 삽입된 root도 다시 관측한다. active/unavailable/not-found run은 heartbeat 시간만으로 failed 처리하지 않고
base 상태와 관측 오류를 보존한다.
generic `claim_next_import_job`도 두 kind를 제외한다. 이 queued/running row의 lifecycle은
Dagster 관측과 tracking client만 소유한다. tracking/reconciliation sensor는
`DefaultSensorStatus.RUNNING`이고, 배포 maintenance 중 reconciliation cursor를 cutover 시각으로
명시 초기화해 첫 tick commit/readback이 끝나기 전에는 feature launch ingress를 열지 않는다.

두 feature-load kind는 tracking client reserved kind다. generic enqueue/start/finish/heartbeat/
cancel/payload update/requeue/batch·load-batch attach와 모든 generic lifecycle/progress/stage writer는
대상 kind를 fail-closed로 거부한다. append-only event/audit와 같은 cancellation id marker를
확인한 C3d terminal writer만 예외다. 0051 구현은 direct-write SQL inventory를 전수한다.

C3d의 generic queued member는 계속 marker 뒤 DB-only cancelled로 끝낸다. 단,
`kind IN ('provider_feature_load_run','provider_feature_load') AND status='queued' AND
dagster_run_id IS NOT NULL`인 member는 run-backed active member다. C3d가 같은 run을 한 번
reserve/terminate하고 authoritative `CANCELED`를 확인한 뒤 base cancelled로 확정한다.
QUEUED→STARTED 경쟁도 같은 reservation/poll 경로가 처리한다. C3e-A1은 이 C3d scope/run 분류와
회귀를 함께 확장한다.

백필은 `feature_update_requests.job_id`와 exact `provider_dataset` scope, 또는 job별 정확히
한 distinct event pair만 사용한다. payload의 scalar/nested identity는 읽지 않는다. 여러 pair,
부분 identity, 빈 문자열은 provider/dataset을 모두 NULL로 남기고 신뢰할 trigger가 없는 legacy
row의 `trigger_kind`도 NULL이다.
기존 `pipeline_cancellation_runs`에는 권위 있는 Dagster 관측 시각 근거가 없으므로
`engine_started_at`/`engine_finished_at`을 추측해 백필하지 않고 NULL로 유지한다. 0051 이후
terminal observation을 기록하는 cancellation writer만 실제 관측값을 채운다.

신규 import job writer는 payload를 해석하지 않고 pair operation과 unpaired orchestration을
repository 경계에서 명시적으로 구분한다. pair operation은 required typed pair와 trigger를
실컬럼에 쓴다. offline validate/load/reserve, MOIS bulk/incremental/closed, exact
provider-dataset update member는 pair를 반드시 넘긴다. multi-scope update, batch aggregate,
consistency/MV처럼 단일 pair가 아닌 행은 NULL이고 batch attach는 child identity를 추론하거나
덮지 않는다. event append는 job 실컬럼 pair를 기본 상속하며 다른 non-NULL pair를 거부한다.
신규 writer는 event-only identity를 만들 수 없다.

feature-load root/child `created_at`은 sensor 기록 시각이 아니라 timezone-aware Dagster run create
timestamp이고 둘이 같다. 늦은 reconcile도 root와 시각이 아직 없는 child의
`started_at`/`finished_at`을 Dagster authoritative timestamp로 채우며 wrapper가 이미 완료한
pair child의 완료 시각은 덮지 않는다. C3d가 marker를 소유한 terminal 경로에서는 cancellation
writer가 같은 cancellation id CAS로 feature member status, child/root progress·stage·redacted
error, root raw status와 engine timestamp를 함께 갱신한다. registry version과 해석된 비민감 identity snapshot은 job/asset
selection·run config/settings와 교차 검증한다. static asset, data.go.kr job별 config, MCST 13 pair,
KNPS catalog 내 resolved dataset을 각각 전수 검증하며 provider resource는 sensor identity 복구에
사용하지 않는다.

downgrade는 feature index/constraint/trigger와 cancellation member CHECK,
`ck_pipeline_cancellation_runs_engine_times`를 먼저 제거하고 cancellation run의
`engine_started_at`/`engine_finished_at`, member의 `operation_kind`/
`requires_run_termination`, import identity/raw-status 컬럼 순서로 제거한다. engine 시각 또는
신규 member/import 필드가 필요한 감사 이력은 downgrade 전에 별도로 export해야 한다.
old C3d가 해석하지 못하는 `initial_status='queued' AND result='cancel_failed'`인 run-backed feature
history가 있으면 export/명시 정리 전 downgrade를 fail-closed한다.
구 API/Dagster image 기동 뒤 실행하지 않는다. rollback은 신규 launch 차단 →
신 API/Dagster 모두 정지 →
0051을 아는 migration image가 active feature root/child와 관련 in-progress/retryable cancellation 0을
확인하고 downgrade → 구 API → 구 Dagster 순서다. upgrade는 API/admin launch maintenance,
schedule/sensor 중지, Dagster UI/manual/backfill ingress 차단 → Dagster
QUEUED/STARTING/STARTED/CANCELING과 DB active feature root/child 0 확인 → 구 webserver/daemon/code
location 정지 → API/0051 → head/CHECK/index 검증·첫 backfill → 신 Dagster 전 구성 재기동 →
tracking sensor RUNNING/cutover cursor/첫 tick readiness → backfill 재실행 → API/Dagster readback
→ UI 재기동·maintenance 해제 순서다.

### 9.9 `ops.feature_change_requests` (alembic 0021)

사용자/admin 요청으로 들어온 place/event feature 추가·수정·삭제 요청을 저장한다.
`review_mode='require_review'`면 `pending`으로 남고, admin 승인이 들어오면 적용된다.
`review_mode='immediate'`면 같은 transaction에서 바로 적용되어 `applied`가 된다.

```sql
CREATE TABLE ops.feature_change_requests (
  request_id   UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  feature_id   TEXT NOT NULL,
  action       TEXT NOT NULL,           -- add / update / delete
  state        TEXT NOT NULL DEFAULT 'pending',
  review_mode  TEXT NOT NULL,           -- require_review / immediate
  payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason       TEXT,
  requested_by TEXT,
  reviewed_by  TEXT,
  reviewed_at  TIMESTAMPTZ,
  applied_at   TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT ck_feature_change_action CHECK (action IN ('add','update','delete')),
  CONSTRAINT ck_feature_change_state CHECK (state IN ('pending','applied','rejected')),
  CONSTRAINT ck_feature_change_review_mode CHECK (
    review_mode IN ('require_review','immediate')
  )
);

CREATE INDEX idx_feature_change_state_created
  ON ops.feature_change_requests (state, created_at DESC, request_id DESC);
CREATE INDEX idx_feature_change_feature
  ON ops.feature_change_requests (feature_id);
```

적용 규칙:

- 대상 kind는 `place`, `event`만 허용한다.
- add/update/delete가 적용되면 `feature.features.data_origin='user_request'`,
  `data_version=1`, `user_change_request_id=request_id`로 effective row를 갱신한다.
- delete는 hard delete가 아니라 `status='deleted'`, `deleted_at`, `user_deleted_at`을
  기록하는 soft delete다.
- provider reload와 snapshot 누락 정리는 `data_origin='user_request'` row를 삭제하거나
  되살리지 않는다.

### 9.10 `ops.poi_cache_targets` / generation·outbox 계열 (ADR-045/065/081)

외부 앱 POI/cache target을 `external_system + target_key + 좌표 + 반경`으로 저장하고,
target 주변 feature와 다대다로 연결한다. 목적은 전체 provider 재적재 없이 저장 POI
주변의 자주 바뀌는 값(날씨, 유가, 경고, 유고정보 등)을 캐싱 갱신하는 것이다.

핵심 규칙:

- `target_key`는 좌표가 아니라 외부 앱이 보장하는 고유 key다.
- 같은 key와 같은 normalized 좌표는 idempotent upsert다.
- 같은 key와 다른 normalized 좌표는 기본 409이며, 이동은 명시적 `move`로 처리한다.
- `lock_version BIGINT NOT NULL DEFAULT 1 CHECK (lock_version >= 1)`은 모든 UPDATE의 BEFORE
  trigger가 `OLD + 1`로 강제한다. UUID+version이 HTTP `entity_tag`의 정본이다.
- soft deleted target은 targeted update에서 제외한다.
- target soft-delete는 parent `FOR UPDATE` 뒤 link를 비활성화한다. executor link sync는 모든 active
  parent를 UUID 순서의 `FOR KEY SHARE`로 먼저 잠근 뒤 link를 비활성화/upsert한다. 두 경로의
  parent → link 순서를 통일해 삭제 뒤 link 재활성화와 multi-target 교착을 막는다.
- 여러 target 반경의 교집합 feature/provider scope는 한 번만 업데이트한다.

상세 DDL은 `docs/poi-cache-update-targets.md` §6과 `alembic 0009/0058`이 정본이다.
repository는 `infra.poi_cache_target_repo`가 제공한다. `infra.scope_repo`의
`resolve_cache_target_keys`와 `infra.feature_update_executor`는 active target 주변
feature를 계산하고 `ops.poi_cache_target_feature_links`를 재계산한다.

T-VN-41 producer foundation은 projection row와 source 순서를 분리한다. 신규 정규화 table은
다음 책임을 각각 하나만 소유한다.

| 상태 | identity | 책임 |
|---|---|---|
| source control/epoch | `external_system`, `(external_system, restore_epoch)` | Map 소유 양의 epoch, restore fence ETag/barrier와 epoch 이력 |
| source head | `(external_system, target_key)` | 마지막 source generation, target UUID 또는 durable tombstone |
| source event | producer `event_id` | Idempotency-Key command, request fingerprint, 적용/replay 결과의 불변 이력 |
| refresh member | `(request_id, target_id)` | request 시작 시 epoch/generation을 캡처한 late-result fence |
| outbox event | `event_id`, unique `relay_order` | target/link/refresh/reconciliation 결과와 같은 transaction에서 만든 불변 typed event |
| delivery/claim | event/claim identity | lease, attempt, retry, contiguous ACK, dead/replay와 epoch supersession 상태 |
| fixed snapshot | `snapshot_id`, `(snapshot_id, row_number)` | 한 MVCC view의 epoch/high-watermark/head set과 Merkle root를 immutable page로 고정 |
| reconciliation | `request_id`, unique `command_id` | checksum receipt, halt/resume와 terminal 성공/실패/복원 대체 이력 |
| GC referenced 관측 | `observation_id`, unique `dagster_run_id` | acquired GC run의 referenced count, 복사된 증가율 기준선과 승격 여부 |

`source_generation`은 target natural key별 PinVi desired-state generation이고,
`target_sequence`는 같은 source generation에서 Map이 만든 결과 순서다. 기존
`feature_update_requests.generation` queue CAS와 target `lock_version` ETag는 그대로 별도다.
soft delete 뒤 새 target UUID가 생겨도 source head/tombstone은 제거하지 않는다.

outbox event의 `event_type`은 ADR-081의 네 strict 값만 허용한다. `event_scope='target'`인
state/link/refresh는 natural key, historical target UUID, generation, target sequence가 모두
필수다. `event_scope='stream'`은 `cache_target.reconciled`만 허용하고 네 target tuple은 모두
`NULL`이다. 따라서 빈/all-tombstone snapshot도 fake target 없이 reconciliation event를 남긴다.
payload는 versioned typed schema와 `source_payload_fingerprint`를 가지며 source event, target,
refresh request, job, domain command와의 linkage를 보존한다. `ops.ops_live_topic_revisions`는
invalidation signal로만 유지하고 event stream으로 사용하지 않는다.

delivery status는 `pending|leased|retry|dead|delivered|superseded`다. restore fence는 새 epoch보다
낮은 모든 non-delivered 상태를 같은 transaction에서 terminal `superseded`로 바꾸고 lease binding을
지운다. `delivered`는 그대로 보존한다. `superseded_at`과 fence별 `superseded_delivery_count`가 audit
근거이며 exact fence replay는 delivery version을 다시 올리지 않는다. stream 상태의
`superseded_count`는 역사적 종결 수이고 backlog/dead 집계에는 포함하지 않는다.

restore fence receipt는 최초 `invalidated_claim_count`, `superseded_delivery_count`,
`superseded_reconciliation_count`와 nullable `superseded_reconciliation_request_id`를 불변 저장한다.
reconciliation의 `(external_system, request_id)` unique key와 fence의
`(external_system, superseded_reconciliation_request_id)` composite FK가 request UUID뿐 아니라
stream 소속까지 같은 DB relation으로 결박한다. nullable request ID는 `MATCH SIMPLE`로 허용하되
기존 count/UUID CHECK가 `0/null`만 허용하므로 부분 참조가 유효한 receipt로 가장할 수 없다.
reconciliation은 stream별 `preparing|running` partial unique index로 active 하나만 허용한다. fence가
active request를 만나면 `status='superseded'`, `error_code='restore_fenced'`, `completed_at=now()`와
증가한 `phase_version`으로 원자 종결한다. preparing 출발은 snapshot/expected root가 `NULL`, running
출발은 둘 다 non-`NULL`인 채 보존하고 두 경우 모두 actual root는 `NULL`이다. 이 shape는 DB CHECK로
강제하며 exact fence replay는 receipt count/UUID나 request phase version을 바꾸지 않는다.

fixed snapshot은 stream epoch, outbox high-watermark, active/tombstone head 전체를 한 SQL MVCC
view에서 읽어 ADR-081 Merkle v1으로 checksum한다. page 중 새 write가 commit돼도 immutable item은
바뀌지 않는다. reconciliation은 먼저 claim을 무효화하고 stream을 halt한다. exact checksum,
동일 epoch, dead-letter 0을 모두 확인해야만 enable하며 mismatch terminal receipt는 다른 checksum으로
resume할 수 없다. legacy target에는 임의 epoch를 백필하지 않으며 첫 권위 snapshot이 head를 채택한다.

`ops.poi_cache_target_snapshot_gc_observations`는 감사 snapshot 자체가 아니라 그 개수를 다시 셀 수
있는 파생 운영 관측이다. 새 행은 직전 acquired 행의 run/time/count와 마지막
`growth_baseline_eligible=true` 행의 run/time/count를 서로 다른 컬럼에 복사한다. 감소 경보는 직전
acquired count와 비교하고 증가율은 적격 baseline과 비교한다. DB 시각이 적격 baseline과 직전 acquired
시각보다 모두 전진했고 run에 영속된 최소
간격을 충족한 행만 다음 기준선으로
승격한다. 따라서 짧은 재실행·동일/역행 DB 시각 표본은 감사할 수 있지만 후속 증가율 기준선을
오염시키지 않는다. count 감소는 간격과 무관한 inventory-loss 경보다. run ID unique는 retry가 최초
관측·두 기준선·최소 간격 분류를 바꾸지 못하게 한다. DB CHECK도 baseline all-or-none과
`growth_baseline_eligible` 시간식을 재계산해 raw writer 우회를 막는다. 기본 90일 retention은 `observed_at` index로
정리하고 partial eligible index로 기준선을 찾는다.

이 테이블은 파생·폐기 가능한 데이터이므로 앱 바이너리만 0077 호환 버전으로 rollback할 때 DB는
0078에 두고 테이블과 관측을 보존한다. 정상 복구는 0078 이상 앱으로 forward 배포하는 것이다.
명시적 Alembic downgrade만 테이블을 파괴하며, 다시 0078로 upgrade하면 빈 테이블로 재생성되어 첫
acquired run이 새 기준선이 된다. snapshot/reconciliation 원본은 이 경로에서 삭제되지 않는다.

### 9.11 `ops.provider_refresh_policies` (ADR-045 T-205c, alembic 0009/0049/0056)

provider/dataset별 update 주기, targeted update 허용 여부, filedata/openapi 구분,
rate limit, 최적 기본값, 출처 문서와 명시적 freshness SLA
`stale_after_minutes`(alembic 0049)를 저장한다.

alembic 0056은 다음 단조 revision을 추가한다.

```sql
revision BIGINT NOT NULL DEFAULT 1
  CHECK (revision >= 1 AND revision <= 9223372036854775807)
```

핵심 규칙:

- filedata provider는 기본적으로 POI 등록 여부와 무관하게 system schedule을 따른다.
- admin UI/설정/DB override는 가능하지만 provider rate limit을 넘을 수 없다.
- `stale_after_minutes`는 호출 주기·rate-limit floor와 다른 운영 SLA다. NULL이면
  서버는 다른 interval에서 추론하지 않고 freshness를 `unknown`으로 계산한다.
- rate limit과 최적값은 provider API 프로젝트의 문서/코드(로컬 `F:\dev\python-*-api`
  우선, ADR-044)를 근거로 저장한다.
- `updated_at`은 표시·진단용이고 동시성 정본이 아니다. 모든 정책 write는
  `expected_revision`을 명시한다. 신규 생성만 `null`을 허용하며 revision 1로 시작한다.
  기존 행 갱신은 현재 양수 revision과 일치할 때만 한 SQL에서 필드를 바꾸고
  `revision = revision + 1`을 수행한다. 기존 행에 `null`, 없는 행에 정수를 보낸 요청,
  stale revision은 모두 write 없이 현재 record/revision을 반환하는 conflict다.
- API에서는 JavaScript 안전 정수 한계를 피하기 위해 DB BIGINT revision을 정규화된
  양수 10진 문자열로 직렬화한다. DB/repository 내부에서만 정수로 비교한다.
- 같은 revision을 읽은 두 transaction 중 정확히 하나만 성공한다. 실패 transaction과
  성공 뒤 rollback한 transaction은 정책 값과 revision을 모두 바꾸지 않는다.
- 기존 행의 `source_kind`는 생성 뒤 불변이다. update SQL은 요청 값과 현재 값이 같을
  때만 실행하고, 다르면 현재 record를 포함한 명시적 conflict로 거절한다.
- revision `9223372036854775806`은 한 번 갱신해 BIGINT 최댓값까지 갈 수 있다. 최댓값
  행은 `+1` 식을 평가하지 않으며 현재 record/revision을 포함한
  `PROVIDER_REFRESH_POLICY_REVISION_EXHAUSTED`로 닫아 overflow 500을 만들지 않는다.

repository는 `infra.provider_refresh_policy_repo`가 제공한다. T-206d request 실행
본체는 `enabled`/`source_kind`/`targeted_policy`를 실행 계획에 적용하고, rate-limit
값을 runner scope metadata로 전달한다. provider 호출 단위의 hard enforcement는
Dagster resource/provider runner가 수행한다.

### 9.12 `ops.ops_live_ticket_claims` (ADR-064 T-ADM-C7A)

admin ops WebSocket의 60초 signed ticket을 한 번만 소비하기 위한 임시 보안 상태다.
로그인 성공/실패를 뜻하지 않으므로 `ops.admin_auth_events`와 분리한다.

```sql
CREATE TABLE ops.ops_live_ticket_claims (
  nonce_hash BYTEA PRIMARY KEY CHECK (octet_length(nonce_hash) = 32),
  actor      TEXT NOT NULL CHECK (char_length(actor) BETWEEN 1 AND 80),
  expires_at TIMESTAMPTZ NOT NULL,
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ix_ops_live_ticket_claims_expires_at
  ON ops.ops_live_ticket_claims (expires_at);
```

원 nonce는 저장하지 않고 SHA-256 hash만 PK insert한다. `ON CONFLICT DO NOTHING`이
동시·순차 replay 중 최초 한 건만 성공시킨다. 각 claim은 `expires_at` index로 찾은
`만료 시각 + 60초 grace` 이전 row를 `FOR UPDATE SKIP LOCKED`로 최대 1,000건 정리한다.
grace는 issuer·verifier·DB clock skew 이상에서도 아직 유효한 claim을 먼저 지우지 않기
위한 하한이다. 이 테이블은 감사 이력이 아니며 정리 대상 row를 장기 보존하지 않는다.

### 9.13 `ops.ops_live_topic_revisions` (ADR-064 T-ADM-C7A)

여러 원본 테이블을 합쳐 만드는 `provider_sync`·`dataset_projection`·`dagster_schedules`
live snapshot의 transaction-coupled 변경 clock이다. timestamp나 독립 identity의 `MAX`만으로는
같은 시각 변경과 늦은 commit 순서를 놓칠 수 있으므로 topic별 단일 `BIGINT` row를 둔다.

```sql
CREATE TABLE ops.ops_live_topic_revisions (
  topic      TEXT PRIMARY KEY CHECK (btrim(topic) <> '' AND char_length(topic) <= 100),
  revision   BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
```

statement trigger는 원본 write와 같은 transaction에서 `revision = revision + 1` upsert를
수행한다. 따라서 원본 rollback은 revision도 되돌리고, 같은 topic의 동시 writer는 PK row lock을
기다린 뒤 각각 한 번씩 증가한다. `provider_sync.provider_sync_state`와
`ops.provider_refresh_policies`의 INSERT/UPDATE/DELETE/TRUNCATE는 `provider_sync`,
`ops.data_integrity_violations`와 `ops.poi_cache_targets`의 같은 네 event는
`dataset_projection`,
`ops.dagster_schedule_overrides`의 같은 네 event와 C5의
`ops.dagster_schedule_audit_events`·`ops.dagster_schedule_claim_resolutions` INSERT는
`dagster_schedules`를 올린다. live snapshot은 원본 projection과 해당 clock을 한 SQL snapshot으로
읽으며 frame data는 여전히 REST query invalidation signal일 뿐 화면 상태 정본이 아니다.

## 10. 보관 정책 (ADR-017) → purge 작업

```sql
-- weather_values: 기본 3년 보존(ADR-062). 예보 발표 이력 비교용이므로
-- 별도 승인된 purge 작업 전에는 삭제하지 않는다.

-- notice: 종료일 또는 발표일 +1년.
-- 기간 판정은 subtype의 typed timestamptz로 한다(문자열 파싱·방어 cast 없음).
-- subtype 자체가 kind='notice'만 담으므로 kind 술어도 필요 없다(§6 배타 arc).
-- core row를 지우면 subtype row는 복합 FK의 ON DELETE CASCADE로 함께 사라진다.
DELETE FROM feature.features f
USING feature.feature_notices n
WHERE n.feature_id = f.feature_id
  AND n.valid_end_time < now() - interval '1 year';

-- event: 종료일 +20년
DELETE FROM feature.features f
USING feature.feature_events e
WHERE e.feature_id = f.feature_id
  AND e.ends_on < (now() - interval '20 years')::date;

-- source_records: 현재 payload 포인터가 아니며 보존기한이 지난 이력만 정리한다.
-- Feature link는 source_entity에 붙으므로 record 삭제가 link를 cascade하지 않는다.
DELETE FROM provider_sync.source_records sr
WHERE NOT EXISTS (
    SELECT 1 FROM provider_sync.source_entities se
    WHERE se.current_source_record_key = sr.source_record_key
  )
  AND sr.expires_at IS NOT NULL
  AND sr.expires_at < now();
```

이 SQL은 Dagster purge asset에서 실행한다. `infra/purge_repo.py`에 상수로 박는다.

## 11. ID 생성 규약 (다른 곳에서도 인용)

```python
make_feature_id(*, bjd_code: str | None, kind: FeatureKind | str, category: str,
                source_type: str, source_natural_key: str,
                content_hash: str | None = None) -> str
# kind는 FeatureKind(StrEnum) 멤버 또는 동등 문자열 ('place'/'event'/...) 모두 허용.
# 포맷: f_{bjd_code or 'global'}_{kind[0]}_{sha1(input)[:16]}
# input: f"{bjd_code or 'global'}|{kind}|{category}|{source_type}|{source_natural_key}|{content_hash or ''}"

make_source_record_key(*, provider: str, dataset_key: str,
                       source_entity_type: str, source_entity_id: str,
                       raw_payload_hash: str) -> str
# 포맷: sr_{sha1(input)[:20]}

_make_source_entity_key(*, provider: str, dataset_key: str,
                        source_entity_type: str, source_entity_id: str) -> str
# provider entity 내부 결정키. 포맷: se_{sha256(input)}, payload hash는 포함하지 않는다.

make_payload_hash(data: Any, *, length: int = 32) -> str
# canonical_json(data) → sha256 → [:length]

make_weather_value_key(*, feature_id: str, provider: str, weather_domain: str,
                       forecast_style: str, metric_key: str,
                       issued_at: datetime | None = None,
                       valid_at: datetime | None = None,
                       observed_at: datetime | None = None) -> str
# 포맷: wv_{sha1(input)[:20]}. WeatherValue.identity() tuple과 동일 input.

make_price_value_key(*, feature_id: str, provider: str, price_domain: str,
                     product_key: str, observed_at: datetime) -> str
# 포맷: pv_{sha1(input)[:20]}. PriceValue.identity() tuple과 동일 input
# (시간 필드는 observed_at 하나 — forecast 없음).
```

## 12. 마이그레이션 가이드

- 모든 schema 변경은 Alembic migration + ADR 동반.
- 마이그레이션은 호환성보다 데이터 보존과 검증 가능한 cutover를 우선한다. 작은 additive 제약은
  `NOT VALID`→backfill→`VALIDATE`, 대형 변경은 shadow/backfill/write-fence/swap으로 수행한다.
- 일반 online 인덱스 추가는 `CREATE INDEX CONCURRENTLY`로 하되 lock acquisition·INVALID
  잔여를 검증한다. dedup 뒤 semantic UNIQUE가 필요한 0060은 writer race를 허용하지 않도록
  `SHARE ROW EXCLUSIVE`→dedup→non-concurrent UNIQUE를 한 transaction으로 수행한다. 삭제된
  loser를 DDL로 복원할 수 없으므로 0060 downgrade는 거부하고 backup/PITR+구 writer image를
  하나의 복구 단위로 사용한다.
- 인덱스 삭제는 `DROP INDEX CONCURRENTLY IF EXISTS`.
- 컬럼 타입 변경은 `USING` cast + downtime 또는 새 컬럼 + 백필 + swap.

## 13. Domain command replay와 외부 효과 실행 상태 (T-VN-12)

### 13.1 공통 claim/result

`ops.domain_commands`는 `(actor, operation, idempotency_key)` UNIQUE identity와
fingerprint version 1, canonical request SHA-256을 저장한다. 행은 생성 뒤 수정·삭제할 수
없다. `ops.domain_command_results`는 command당 하나의 terminal HTTP status/body/header를
append-only로 저장하며 claim 없이 존재할 수 없다. DB-only command는 업무 row 변경과 두
ledger write를 같은 transaction에 둔다.

### 13.2 외부 효과 execution

`ops.offline_upload_command_executions`와 `ops.backup_command_executions`는 공통
`command_id`를 FK/PK로 사용하고 `prepared → effect_started → effect_succeeded`만 허용한다.
효과 identity(upload/object key, backup/target/marker key, deterministic Dagster run ID)와
input digest는 준비 뒤 불변이다. `effect_succeeded`에는 operation별 output digest와 완료
시각이 필수다. backup 계열은 marker SHA-256도 필수이며 delete는 삭제 전 응답 snapshot을
`prepared_result` JSONB로 동결한다.

offline upload는 `uploading`을 명시적 reservation 상태로 추가한다. 이 상태는 삭제·검증·적재
대상이 아니며 create command가 object proof를 확정할 때만 `uploaded`로 전이한다. 따라서
DB reservation 이전의 orphan object나 object write 이전의 terminal success가 생기지 않는다.
삭제는 `deleting` 상태와 `delete_command_id → ops.domain_commands`를 같은 transaction에서
원자 예약한다. owner command만 최종 row 삭제를 수행할 수 있고, 같은 `upload_id`에 다른 key가
경쟁하면 loser의 claim transaction 전체가 rollback되어 복구 불가능한 claim-only 상태를 남기지
않는다.

### 13.3 Filesystem completion proof

backup marker에는 schema version, command/operation/marker key, effect kind/state,
backup/restore target identity, request input digest, effect-specific output proof와 그
canonical SHA-256, UTC completion time을 넣는다. create proof는 manifest와
`SHA256SUMS` logical digest 및 모든 checksum 검증, delete proof는 동결 snapshot digest와
artifact 부재, restore proof는 source checksum과 검증된 target identity, swap proof는
`planned|applied` 구분과 canonical `.env.restore-swap` 파일 digest다.

marker 파일은 root 밖 경로·symlink·hardlink·foreign owner/mode를 거부하고 최초 exact
marker를 덮어쓰지 않는다. restore 재시작은 exact command/source marker가 있을 때만 완료를
채택한다. marker 없는 기존 target은 전부 healthy여도 provenance가 아니므로 자동 복구 성공으로
인증하지 않으며, target 부재면 실행하고 기존/부분 target은 명시적 recreate 또는 운영자
reconciliation으로 보낸다. backup create도 command/input digest가 fsync된 destination
reservation을 effect 전에 선점하고, 다른 artifact나 marker 없는 artifact는 채택하지 않는다.
swap은 고정 project child `.env.restore-swap`만 쓰며 plan-only와 실제 apply proof를 분리한다.

## 이관된 결정 (구 ADR)

ADR에서 빼고 본 문서로 이관한 provider/ETL·도메인·알고리즘·운영 결정이다. 각 항목은
출처 추적을 위해 `(구 ADR-NNN)`을 남긴다.

### Record linkage 가중치·임계값 (구 ADR-016)

같은 장소가 여러 provider에서 다른 이름/좌표로 올라올 때, 자동 병합과 수동 검토
큐(`ops.dedup_review_queue` §9.2)를 가르는 알고리즘 파라미터다. `core/scoring.py`에
박혀 있고, 운영 데이터로 재조정이 필요하면 그때 다시 합의한다(도메인 지식 기반 추정값).

- **Blocking**: `ST_DWithin(coord::geography, 100)` + 같은 `bjd_code` + 같은 `kind`인
  쌍만 후보로 본다.
- **Scoring**: `0.45 * name_sim + 0.35 * spatial_sim + 0.20 * category_sim`.
  name_sim은 `normalize_kr_place_name` 후 Jaro-Winkler 유사도, spatial_sim은
  `exp(-haversine_m / 50.0)`, category_sim은 category tag set Jaccard.
- **임계값**: `THRESHOLD_AUTO=0.85`(자동 병합), `THRESHOLD_MANUAL=0.65`(이 이상 ~ AUTO
  미만은 `ops.dedup_review_queue` 수동 검토). 점수는 DB에 0~100 스케일로 저장한다.
- **마스터 선정**(`core.scoring.select_master`): (1) 좌표 정밀도 → (2) `updated_at`
  최신 → (3) `source_type` 우선순위(행안부 > TourAPI > 사용자 등록) → 동률은 `feature_id`
  사전순. 병합 이력은 `ops.feature_merge_history`(§9.4)에 1행으로 남긴다.

### 보관 정책 per-kind (구 ADR-017)

데이터별 보관 기간 차이가 커서 일률 정책은 DB 비대를 부른다. kind별로 다르게 두고
purge는 Dagster asset에 위임한다(purge SQL 표준 예시는 §10, `infra/purge_repo.py` 상수).

| 데이터 | 보관 기간 |
|--------|-----------|
| `place` | 무기한 (폐업 시 `status='inactive'`) |
| `route` / `area` | 무기한 |
| `event` | 종료일(`ends_on`) +20년 |
| `notice` | 종료일 또는 발표일 +1년 |
| `feature_price_values` | 가격 domain별 기본값(초기 유가 10년 권장, purge asset에서 관리) |
| `weather_values` | 기본 3년(예보 발표 이력 비교용, ADR-062) |
| `source_records` | entity 현재 record는 보존. 과거 payload는 대응 Feature 보존 기간 이상 또는 명시 `expires_at` 정책으로 purge |

### feature 정합성 리포트 단계적 도입 (구 ADR-033)

`ops.feature_consistency_reports`(§9.7) 스키마와 Phase 1(F1~F3) 구현은 §9.7에 정본이
있다. 단계 분할의 핵심 근거만 남긴다.

- **Phase 1 (구현됨, 관측 모드)** — 스키마 + cheap·critical 3건(F1 orphan source /
  F2 detail 누락 / F3 CRS drift). Dagster 게이트 미적용 — 검증만 하고 `mv_refresh` swap을
  차단하지 않는다(상세는 §9.7).
- **Phase 2 (Sprint 5 운영 진입 직전)** — 비용 큰 나머지 케이스 + Dagster 게이트:
  F4(`dedup_review_queue` 미해소 N건 초과, WARN), F5(provider `last_success` SLA 초과,
  WARN), F6(`opening_hours` start>end 모순, ERROR), F7(cross-provider dedup score
  baseline 대비 회귀, WARN), F8(RustFS file_object orphan, WARN). 게이트는 root → child
  적재 → `consistency_check` → `severity_max != ERROR`일 때만 swap 허용, ERROR면 알림 +
  swap 차단(`docs/architecture/dagster-boundary.md §12`). 스키마는 Phase 1에서 이미
  박혀 있어 Phase 2 추가는 케이스 행 추가뿐이다. 게이트를 켜는 PR은 dry-run report
  첨부 후 점진 enable한다(첫 batch가 F4~F8로 일제히 fail할 수 있음).
