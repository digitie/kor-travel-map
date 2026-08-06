-- =============================================================================
-- contracts/vnext/target-invariants-v1.sql — T-VN-31A 데이터 불변식 freeze
-- =============================================================================
-- target-schema-v1.sql이 적용된 DB에서 실행하는 assertion 질의 집합이다. 모든
-- 질의는 count(*)를 반환하고 결과는 0이어야 한다.
--
-- 실행 계약(machine-readable): 각 assertion은 단일 `SELECT count(*) ...`이며
-- trailer는 정확히 <semicolon> <dash-dash> expect: 0 <dash-dash> phase: <phase>
-- 형식이다. phase는 실행 시점을 태그한다:
--   * pre-backfill  — shadow 구조 적재 직후·제약 VALIDATE/UNIQUE 연결 전
--     preflight에서만 의미 있는 검사
--   * post-backfill — backfill 완료를 전제하는 완전성 검사(cutover gate)
--   * both          — 두 시점 모두 실행하는 검사
-- tests/integration/test_vnext_target_freeze.py는 빈 DB에서 전 phase를 실행한다
-- (빈 DB에서는 전부 0). tests/unit이 trailer 문법·개수를 fail-close한다.
--
-- 패턴 출처:
--   * H35 preflight 6종 — identity(null/blank/중복)·NFC·trim·길이·CHECK 위반·
--     FK orphan (src/kortravelmap/cli/_h35_schema.py `_preflight_counts`,
--     docs/runbooks/h35-prod-migration-cutover.md §5.1)
--   * 각 ADR의 데이터 불변식 (ADR-067~072, ADR-078)
--
-- 길이 상한은 H35 preflight 상수(112/512)를 재사용한다 — 목표 스키마 자체의
-- 길이 CHECK 채택 여부는 미정(각 구현 task 소관)이므로 여기서는 preflight
-- assertion으로만 고정한다.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- ADR-068 — Feature UUID identity + legacy alias (T-VN-32)
-- -----------------------------------------------------------------------------

-- [INV-068-01] backfill 후 모든 feature는 alias를 1개 이상 가진다
-- (T-VN-32B — 신규 write는 UUID와 alias를 원자 생성).
SELECT count(*)
FROM feature.features AS f
LEFT JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id
WHERE a.alias IS NULL; -- expect: 0 -- phase: post-backfill

-- [INV-068-02] alias 전역 중복 없음 (UNIQUE 연결 전 preflight).
SELECT count(*)
FROM (
    SELECT alias
    FROM feature.feature_aliases
    GROUP BY alias
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-068-03] alias FK orphan 없음 (FK VALIDATE 전 preflight).
SELECT count(*)
FROM feature.feature_aliases AS a
LEFT JOIN feature.features AS f ON f.feature_id = a.feature_id
WHERE f.feature_id IS NULL; -- expect: 0 -- phase: both

-- [INV-068-04] alias identity canonical — null/blank·trim·NFC·길이(H35 512).
SELECT count(*)
FROM feature.feature_aliases
WHERE alias IS NULL
   OR alias = ''
   OR alias <> btrim(alias)
   OR alias IS DISTINCT FROM normalize(alias, NFC)
   OR length(alias) > 512; -- expect: 0 -- phase: both

-- [INV-068-05] provider identity 3-tuple 중복 없음 (UNIQUE 연결 전 preflight).
SELECT count(*)
FROM (
    SELECT provider_dataset_id, source_entity_type, source_entity_id
    FROM provider_sync.source_entities
    GROUP BY provider_dataset_id, source_entity_type, source_entity_id
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- -----------------------------------------------------------------------------
-- ADR-069 — provider_datasets 정본 + immutable lineage (T-VN-33)
-- -----------------------------------------------------------------------------

-- [INV-069-01] provider_datasets identity canonical — blank·trim·NFC·길이(H35 112).
SELECT count(*)
FROM provider_sync.provider_datasets
WHERE provider = ''
   OR provider <> btrim(provider)
   OR provider IS DISTINCT FROM normalize(provider, NFC)
   OR length(provider) > 112
   OR dataset_key = ''
   OR dataset_key <> btrim(dataset_key)
   OR dataset_key IS DISTINCT FROM normalize(dataset_key, NFC)
   OR length(dataset_key) > 112; -- expect: 0 -- phase: both

-- [INV-069-02] provider_datasets natural identity 중복 없음.
SELECT count(*)
FROM (
    SELECT provider, dataset_key
    FROM provider_sync.provider_datasets
    GROUP BY provider, dataset_key
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-069-02a] capability는 versioned 최소 shape를 따른다.
SELECT count(*)
FROM provider_sync.provider_datasets
WHERE NOT provider_sync.is_valid_provider_dataset_capabilities(capabilities); -- expect: 0 -- phase: both

-- [INV-069-02b] operation은 실제 dataset에만 속하며 handler binding 전 검증 대상이다.
SELECT count(*)
FROM provider_sync.provider_dataset_operations AS operation
LEFT JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = operation.provider_dataset_id
WHERE dataset.provider_dataset_id IS NULL; -- expect: 0 -- phase: both

-- [INV-069-03] source_entities → provider_datasets FK orphan 없음.
SELECT count(*)
FROM provider_sync.source_entities AS e
LEFT JOIN provider_sync.provider_datasets AS d
    ON d.provider_dataset_id = e.provider_dataset_id
WHERE d.provider_dataset_id IS NULL; -- expect: 0 -- phase: both

-- [INV-069-04] source_entities identity canonical — blank·trim·NFC·길이(H35 512).
SELECT count(*)
FROM provider_sync.source_entities
WHERE source_entity_type = ''
   OR source_entity_type <> btrim(source_entity_type)
   OR source_entity_type IS DISTINCT FROM normalize(source_entity_type, NFC)
   OR length(source_entity_type) > 512
   OR source_entity_id = ''
   OR source_entity_id <> btrim(source_entity_id)
   OR source_entity_id IS DISTINCT FROM normalize(source_entity_id, NFC)
   OR length(source_entity_id) > 512; -- expect: 0 -- phase: both

-- [INV-069-05] source_records → source_entities FK orphan 없음.
SELECT count(*)
FROM provider_sync.source_records AS r
LEFT JOIN provider_sync.source_entities AS e
    ON e.source_entity_key = r.source_entity_key
WHERE e.source_entity_key IS NULL; -- expect: 0 -- phase: both

-- [INV-069-06] head는 같은 entity의 record만 가리킨다 (composite FK preflight —
-- cross-entity lineage 차단, ADR-069 결정 3).
SELECT count(*)
FROM provider_sync.source_entity_heads AS h
LEFT JOIN provider_sync.source_records AS r
    ON r.source_entity_key = h.source_entity_key
   AND r.source_record_key = h.current_source_record_key
WHERE r.source_record_key IS NULL; -- expect: 0 -- phase: both

-- [INV-069-06a] record가 있으면 head는 정확히 하나, record가 없으면 head도 없다.
SELECT count(*)
FROM (
    SELECT
        entity.source_entity_key,
        count(record.source_record_key) AS record_count,
        count(head.source_entity_key) AS head_count
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_records AS record
      ON record.source_entity_key = entity.source_entity_key
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    GROUP BY entity.source_entity_key
    HAVING (count(record.source_record_key) = 0 AND count(head.source_entity_key) <> 0)
        OR (count(record.source_record_key) > 0 AND count(head.source_entity_key) <> 1)
) AS incomplete; -- expect: 0 -- phase: both

-- [INV-069-07] source_links의 is_primary_source 잔재 없음 — primary 판정은
-- source_role 단일 필드(D-5-4). CHECK 위반(허용 role 밖) 카운트.
SELECT count(*)
FROM provider_sync.source_links
WHERE source_role NOT IN (
    'primary', 'base_address', 'base_coordinate', 'enrichment',
    'correction', 'duplicate_candidate', 'media', 'weather_context'
); -- expect: 0 -- phase: both

-- [INV-069-08] source_records payload CHECK 위반 없음 (object 아님).
SELECT count(*)
FROM provider_sync.source_records
WHERE jsonb_typeof(raw_data) IS DISTINCT FROM 'object'; -- expect: 0 -- phase: both

-- [INV-069-09] raw payload hash는 canonical lowercase hex prefix다.
SELECT count(*)
FROM provider_sync.source_records
WHERE raw_payload_hash !~ '^[0-9a-f]{1,64}$'; -- expect: 0 -- phase: both

-- -----------------------------------------------------------------------------
-- ADR-067 — 직교 3축 상태 + 단일 공개 정본 (T-VN-34)
-- (불가능 조합의 집합은 정본이 열거하지 않아 미정 — T-VN-34A 무손실 매핑
-- 소관이므로 여기에는 조합 assertion을 두지 않는다.)
-- -----------------------------------------------------------------------------

-- [INV-067-01] 3축 값 domain 위반 없음 (CHECK VALIDATE 전 preflight).
SELECT count(*)
FROM feature.features
WHERE lifecycle_state NOT IN ('active', 'retired')
   OR publication_state NOT IN ('draft', 'published', 'suppressed')
   OR quality_state NOT IN ('valid', 'quarantined'); -- expect: 0 -- phase: both

-- [INV-067-02] 공개 view와 base 술어의 일치 — view 밖 술어 만족 행 없음.
SELECT count(*)
FROM feature.features AS f
WHERE f.lifecycle_state = 'active'
  AND f.publication_state = 'published'
  AND f.quality_state = 'valid'
  AND NOT EXISTS (
      SELECT 1 FROM feature.public_features AS p WHERE p.feature_id = f.feature_id
  ); -- expect: 0 -- phase: both

-- -----------------------------------------------------------------------------
-- ADR-070 — typed subtype (T-VN-35)
-- -----------------------------------------------------------------------------

-- [INV-070-01] point kind(place/price/weather) feature는 subtype row를 가진다
-- (backfill 후 1:1 완전성).
SELECT count(*)
FROM feature.features AS f
LEFT JOIN feature.feature_points AS s ON s.feature_id = f.feature_id
WHERE f.kind IN ('place', 'price', 'weather')
  AND s.feature_id IS NULL; -- expect: 0 -- phase: post-backfill

-- [INV-070-02] event feature의 subtype 완전성.
SELECT count(*)
FROM feature.features AS f
LEFT JOIN feature.feature_events AS s ON s.feature_id = f.feature_id
WHERE f.kind = 'event'
  AND s.feature_id IS NULL; -- expect: 0 -- phase: post-backfill

-- [INV-070-03] notice feature의 subtype 완전성.
SELECT count(*)
FROM feature.features AS f
LEFT JOIN feature.feature_notices AS s ON s.feature_id = f.feature_id
WHERE f.kind = 'notice'
  AND s.feature_id IS NULL; -- expect: 0 -- phase: post-backfill

-- [INV-070-04] route feature의 subtype 완전성.
SELECT count(*)
FROM feature.features AS f
LEFT JOIN feature.feature_routes AS s ON s.feature_id = f.feature_id
WHERE f.kind = 'route'
  AND s.feature_id IS NULL; -- expect: 0 -- phase: post-backfill

-- [INV-070-05] area feature의 subtype 완전성.
SELECT count(*)
FROM feature.features AS f
LEFT JOIN feature.feature_areas AS s ON s.feature_id = f.feature_id
WHERE f.kind = 'area'
  AND s.feature_id IS NULL; -- expect: 0 -- phase: post-backfill

-- [INV-070-06] subtype geometry invalid 없음 (CHECK VALIDATE 전 preflight).
SELECT count(*)
FROM (
    SELECT geom FROM feature.feature_points
    UNION ALL SELECT geom FROM feature.feature_events
    UNION ALL SELECT geom FROM feature.feature_routes
    UNION ALL SELECT geom FROM feature.feature_areas
) AS g
WHERE NOT x_extension.st_isvalid(g.geom); -- expect: 0 -- phase: both

-- [INV-070-07] subtype geometry empty 없음.
SELECT count(*)
FROM (
    SELECT geom FROM feature.feature_points
    UNION ALL SELECT geom FROM feature.feature_events
    UNION ALL SELECT geom FROM feature.feature_routes
    UNION ALL SELECT geom FROM feature.feature_areas
) AS g
WHERE x_extension.st_isempty(g.geom); -- expect: 0 -- phase: both

-- [INV-070-08] route/area anchor-envelope 위반 없음 (구판 325km 이격 재발 차단).
SELECT count(*)
FROM (
    SELECT geom, anchor FROM feature.feature_routes
    UNION ALL SELECT geom, anchor FROM feature.feature_areas
) AS g
WHERE NOT x_extension.st_intersects(
    x_extension.st_envelope(g.geom), g.anchor
); -- expect: 0 -- phase: both

-- [INV-070-09] category FK orphan 없음 (FK VALIDATE 전 preflight).
SELECT count(*)
FROM feature.features AS f
LEFT JOIN feature.categories AS c ON c.kind = f.kind AND c.code = f.category_code
WHERE c.code IS NULL; -- expect: 0 -- phase: both

-- [INV-070-10] core name 비어 있지 않음 (non-empty CHECK preflight).
SELECT count(*)
FROM feature.features
WHERE btrim(name) = ''; -- expect: 0 -- phase: both

-- -----------------------------------------------------------------------------
-- ADR-071 — field-level override (T-VN-36)
-- -----------------------------------------------------------------------------

-- [INV-071-01] `(feature_id, field_path)` active 중복 없음 (partial UNIQUE preflight).
SELECT count(*)
FROM (
    SELECT feature_id, field_path
    FROM ops.feature_overrides
    WHERE revoked_at IS NULL
    GROUP BY feature_id, field_path
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-071-02] field_path registry orphan 없음 (ADR-071 결정 4).
SELECT count(*)
FROM ops.feature_overrides AS o
LEFT JOIN ops.feature_override_field_paths AS r ON r.field_path = o.field_path
WHERE r.field_path IS NULL; -- expect: 0 -- phase: both

-- [INV-071-03] tombstone 결합 위반 없음 (revoked_at ↔ revoked_by 쌍).
SELECT count(*)
FROM ops.feature_overrides
WHERE (revoked_at IS NULL) <> (revoked_by IS NULL); -- expect: 0 -- phase: both

-- -----------------------------------------------------------------------------
-- T-VN-37 — typed notice state
-- -----------------------------------------------------------------------------

-- [INV-037-01] lineage당 current 중복 없음 (partial UNIQUE preflight).
SELECT count(*)
FROM (
    SELECT provider_dataset_id, source_entity_type, lineage_key
    FROM provider_sync.notice_states
    WHERE is_current
    GROUP BY provider_dataset_id, source_entity_type, lineage_key
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-037-02] 빈 valid_during 없음 (오염 timestamp 격리 — T-VN-37A).
SELECT count(*)
FROM provider_sync.notice_states
WHERE isempty(valid_during); -- expect: 0 -- phase: both

-- -----------------------------------------------------------------------------
-- ADR-072 — weather bitemporal + current summary (T-VN-38A)
-- -----------------------------------------------------------------------------

-- [INV-072-01] native semantic tuple 중복 없음 — NULLS NOT DISTINCT 의미
-- (GROUP BY는 NULL을 동일 그룹으로 묶는다; UNIQUE 연결 전 preflight).
SELECT count(*)
FROM (
    SELECT feature_id, provider_dataset_id, weather_domain, forecast_style,
           metric_key, issued_at, valid_at, observed_at
    FROM feature.feature_weather_values
    GROUP BY feature_id, provider_dataset_id, weather_domain, forecast_style,
             metric_key, issued_at, valid_at, observed_at
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-072-02] bitemporal 역전 없음 — issued_at <= known_at (보고서 D-8-3).
SELECT count(*)
FROM feature.feature_weather_values
WHERE issued_at IS NOT NULL
  AND issued_at > known_at; -- expect: 0 -- phase: both

-- [INV-072-03] 빈 valid_during 없음 — 기간은 range type이 순서를 강제하므로
-- (ADR-072 결정 2) 역전은 표현 불가, 빈 range만 차단한다.
SELECT count(*)
FROM feature.feature_weather_values
WHERE valid_during IS NOT NULL
  AND isempty(valid_during); -- expect: 0 -- phase: both

-- [INV-072-04] payload shape 위반 없음.
SELECT count(*)
FROM feature.feature_weather_values
WHERE jsonb_typeof(payload) IS DISTINCT FROM 'object'; -- expect: 0 -- phase: both

-- [INV-072-05] weather source record FK orphan 없음 (FK VALIDATE 전 preflight).
SELECT count(*)
FROM feature.feature_weather_values AS w
LEFT JOIN provider_sync.source_records AS r
    ON r.source_record_key = w.source_record_key
WHERE w.source_record_key IS NOT NULL
  AND r.source_record_key IS NULL; -- expect: 0 -- phase: both

-- [INV-072-06] current summary identity 중복 없음 (non-null 축 — timeline_bucket
-- 제외, 0060 정본).
SELECT count(*)
FROM (
    SELECT feature_id, provider_dataset_id, weather_domain, forecast_style,
           metric_key
    FROM feature.current_weather_summary
    GROUP BY feature_id, provider_dataset_id, weather_domain, forecast_style,
             metric_key
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-072-07] summary orphan 없음 — summary는 원본 이력에서 재생성 가능해야
-- 하므로 대응 history 행이 존재한다 (ADR-072 결정 4; reconciliation gate).
SELECT count(*)
FROM feature.current_weather_summary AS s
WHERE NOT EXISTS (
    SELECT 1
    FROM feature.feature_weather_values AS w
    WHERE w.feature_id = s.feature_id
      AND w.provider_dataset_id = s.provider_dataset_id
      AND w.weather_domain = s.weather_domain
      AND w.forecast_style = s.forecast_style
      AND w.metric_key = s.metric_key
); -- expect: 0 -- phase: post-backfill

-- -----------------------------------------------------------------------------
-- ADR-078 — price series identity (T-VN-38B)
-- -----------------------------------------------------------------------------

-- [INV-078-01] observation identity 중복 없음 (series identity + observed_at).
SELECT count(*)
FROM (
    SELECT feature_id, provider, price_domain, product_key, observed_at
    FROM feature.feature_price_values
    GROUP BY feature_id, provider, price_domain, product_key, observed_at
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-078-02] 음수 가격 없음 (CHECK preflight).
SELECT count(*)
FROM feature.feature_price_values
WHERE value_number < 0; -- expect: 0 -- phase: both

-- [INV-078-03] price current summary는 series 최신 관측과 일치할 수 있는
-- history 행을 가진다 (reconciliation gate).
SELECT count(*)
FROM feature.current_price_summary AS s
WHERE NOT EXISTS (
    SELECT 1
    FROM feature.feature_price_values AS p
    WHERE p.feature_id = s.feature_id
      AND p.provider = s.provider
      AND p.price_domain = s.price_domain
      AND p.product_key = s.product_key
      AND p.observed_at = s.observed_at
); -- expect: 0 -- phase: post-backfill

-- -----------------------------------------------------------------------------
-- T-VN-40 — curation 단일 write model
-- -----------------------------------------------------------------------------

-- [INV-040-01] archive 상태·archived_at 결합 위반 없음 (F-16 CHECK preflight).
SELECT count(*)
FROM feature.curation_collections
WHERE (status = 'archived') <> (archived_at IS NOT NULL); -- expect: 0 -- phase: both

-- [INV-040-02] theme_feature_candidates identity 중복 없음.
SELECT count(*)
FROM (
    SELECT theme_id, feature_id
    FROM feature.theme_feature_candidates
    GROUP BY theme_id, feature_id
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-040-03] candidate FK orphan 없음 (theme·feature 양쪽).
SELECT count(*)
FROM feature.theme_feature_candidates AS c
LEFT JOIN feature.curated_themes AS t ON t.theme_id = c.theme_id
LEFT JOIN feature.features AS f ON f.feature_id = c.feature_id
WHERE t.theme_id IS NULL
   OR f.feature_id IS NULL; -- expect: 0 -- phase: both
