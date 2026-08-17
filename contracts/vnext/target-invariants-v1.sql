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

-- [INV-069-02c] 실행 scope는 refresh operation의 정규 child이며 문법·operation kind가
-- 일치한다. capability JSON은 산출 metadata만 소유하므로 control-plane 이중 정본이 없다.
SELECT count(*)
FROM provider_sync.provider_dataset_operation_scopes AS scope
LEFT JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
 AND operation.operation_kind = scope.operation_kind
WHERE operation.provider_dataset_id IS NULL
   OR scope.operation_kind <> 'refresh'
   OR NOT provider_sync.is_valid_provider_dataset_sync_scope(scope.sync_scope); -- expect: 0 -- phase: both

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
        count(DISTINCT head.source_entity_key) AS head_count
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_records AS record
      ON record.source_entity_key = entity.source_entity_key
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    GROUP BY entity.source_entity_key
    HAVING (count(record.source_record_key) = 0 AND count(DISTINCT head.source_entity_key) <> 0)
        OR (count(record.source_record_key) > 0 AND count(DISTINCT head.source_entity_key) <> 1)
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
-- ADR-090 — 직교 3축 상태 + full-tuple append-only audit (T-VN-34A)
-- -----------------------------------------------------------------------------

-- [INV-067-01] 3축 값 domain 위반 없음 (CHECK VALIDATE 전 preflight).
SELECT count(*)
FROM feature.features
WHERE lifecycle_state NOT IN ('active', 'retired')
   OR publication_state NOT IN ('draft', 'published', 'suppressed')
   OR quality_state NOT IN ('valid', 'quarantined'); -- expect: 0 -- phase: both

-- [INV-090-01] retired는 반드시 suppressed다. active의 여섯 tuple과
-- retired/suppressed의 두 tuple만 남는다.
SELECT count(*)
FROM feature.features
WHERE lifecycle_state = 'retired'
  AND publication_state <> 'suppressed'; -- expect: 0 -- phase: both

-- [INV-090-02] state audit의 old/new full tuple, reason/principal/revision은
-- 모두 유효하다. old tuple NULL은 initial/legacy/provider initial만 허용한다.
SELECT count(*)
FROM feature.feature_state_transitions
WHERE btrim(reason_code) = ''
   OR btrim(principal) = ''
   OR row_revision < 1
   OR to_lifecycle_state NOT IN ('active', 'retired')
   OR to_publication_state NOT IN ('draft', 'published', 'suppressed')
   OR to_quality_state NOT IN ('valid', 'quarantined')
   OR (to_lifecycle_state = 'retired' AND to_publication_state <> 'suppressed')
   OR (
       from_lifecycle_state IS NULL
       AND transition_kind NOT IN ('initial', 'legacy_backfill', 'provider_sync')
   )
   OR (
       from_lifecycle_state IS NOT NULL
       AND transition_kind IN ('initial', 'legacy_backfill')
   ); -- expect: 0 -- phase: both

-- [INV-090-03] purge-preserving audit에는 Feature FK/cascade가 없어야 한다.
SELECT count(*)
FROM pg_catalog.pg_constraint AS constraint_row
WHERE constraint_row.conrelid = 'feature.feature_state_transitions'::regclass
  AND constraint_row.contype = 'f'; -- expect: 0 -- phase: both

-- [INV-090-04] 한 transition의 audit identity 세 축은 비어 있지 않다.
SELECT count(*)
FROM feature.feature_state_transitions
WHERE btrim(invoker_role) = ''
   OR btrim(state_procedure_definer) = ''
   OR btrim(audit_writer_definer) = ''; -- expect: 0 -- phase: both

-- [INV-090-05] provider_sync audit은 purge 뒤에도 dataset/entity/record 및
-- authoritative receipt을 한 행에 immutable evidence로 함께 남긴다. transition
-- procedure가 write 시 current head·dataset·link·raw hash를 검증한다. audit은 raw
-- history retention 정책과 독립적으로 purge 뒤에도 남으므로 여기서 live source를
-- 다시 join해 존재를 요구하지 않는다.
SELECT count(*)
FROM feature.feature_state_transitions
WHERE (
        transition_kind = 'provider_sync'
        AND (
            provider_dataset_id IS NULL
            OR btrim(source_entity_key) = ''
            OR btrim(source_record_key) = ''
            OR jsonb_typeof(provider_evidence) <> 'object'
            OR jsonb_typeof(provider_evidence -> 'authoritative_receipt') <> 'string'
            OR btrim(provider_evidence ->> 'authoritative_receipt') = ''
        )
      ) OR (
        transition_kind <> 'provider_sync'
        AND (
            provider_dataset_id IS NOT NULL
            OR source_entity_key IS NOT NULL
            OR source_record_key IS NOT NULL
            OR provider_evidence IS NOT NULL
        )
      ); -- expect: 0 -- phase: both

-- [INV-067-02] 공개 view와 base 술어의 일치 — view 밖 술어 만족 행 없음.
SELECT count(*)
FROM feature.features AS f
WHERE f.lifecycle_state = 'active'
  AND f.publication_state = 'published'
  AND f.quality_state = 'valid'
  AND NOT EXISTS (
      SELECT 1 FROM feature.public_features AS p WHERE p.feature_id = f.feature_id
  ); -- expect: 0 -- phase: both

-- [INV-067-03] view가 core 3축을 만족하지 않는 행을 노출하지 않는다.
SELECT count(*)
FROM feature.public_features AS p
WHERE NOT EXISTS (
    SELECT 1
    FROM feature.features AS f
    WHERE f.feature_id = p.feature_id
      AND f.lifecycle_state = 'active'
      AND f.publication_state = 'published'
      AND f.quality_state = 'valid'
); -- expect: 0 -- phase: both

-- [INV-067-04] route/area의 public_ready cache는 core 정본 3축과 양방향 일치한다.
SELECT count(*)
FROM (
    SELECT feature_id, public_ready FROM feature.feature_routes
    UNION ALL
    SELECT feature_id, public_ready FROM feature.feature_areas
) AS subtype
JOIN feature.features AS f ON f.feature_id = subtype.feature_id
WHERE subtype.public_ready IS DISTINCT FROM (
    f.lifecycle_state = 'active'
    AND f.publication_state = 'published'
    AND f.quality_state = 'valid'
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
    WHERE status = 'active'
    GROUP BY feature_id, field_path
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-071-02] field_path registry orphan 없음 (ADR-071 결정 4).
SELECT count(*)
FROM ops.feature_overrides AS o
LEFT JOIN ops.feature_override_field_paths AS r ON r.field_path = o.field_path
WHERE r.field_path IS NULL; -- expect: 0 -- phase: both

-- [INV-071-03] tombstone 결합 위반 없음 (status와 revoked_at/by 쌍).
SELECT count(*)
FROM ops.feature_overrides
WHERE status NOT IN ('active', 'revoked')
   OR (status = 'active' AND (revoked_at IS NOT NULL OR revoked_by IS NOT NULL))
   OR (status = 'revoked' AND (revoked_at IS NULL OR revoked_by IS NULL)); -- expect: 0 -- phase: both

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

-- [INV-072-01] immutable source revision당 weather fact identity 중복 없음.
SELECT count(*)
FROM (
    SELECT feature_id, provider_dataset_id, weather_domain, forecast_style,
           metric_key, target_at, source_record_key
    FROM feature.feature_weather_values
    GROUP BY feature_id, provider_dataset_id, weather_domain, forecast_style,
             metric_key, target_at, source_record_key
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
-- 제외). 사실 key를 따로 복제한 summary가 아니라 fact pointer 하나를 보유한다.
SELECT count(*)
FROM (
    SELECT feature_id, provider_dataset_id, weather_domain, forecast_style,
           metric_key
    FROM feature.current_weather_summary
    GROUP BY feature_id, provider_dataset_id, weather_domain, forecast_style,
             metric_key
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-072-07] summary pointer는 정확히 같은 identity의 immutable history fact를
-- 가리킨다 (ADR-089; reconciliation gate).
SELECT count(*)
FROM feature.current_weather_summary AS s
LEFT JOIN feature.feature_weather_values AS w
    ON w.weather_value_key = s.weather_value_key
   AND w.feature_id = s.feature_id
   AND w.provider_dataset_id = s.provider_dataset_id
   AND w.weather_domain = s.weather_domain
   AND w.forecast_style = s.forecast_style
   AND w.metric_key = s.metric_key
WHERE w.weather_value_key IS NULL; -- expect: 0 -- phase: post-backfill

-- [INV-089-01] weather summary는 selected_at에서 eligible한 winner를 정확히 가리킨다.
SELECT count(*)
FROM (
    WITH actual AS (
        SELECT feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
               weather_value_key, selected_at
        FROM feature.current_weather_summary
    ), policy_facts AS (
        SELECT
            fact.*,
            policy.stale_after_minutes
        FROM feature.feature_weather_values AS fact
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = fact.provider_dataset_id
         AND dataset.is_active
        JOIN ops.provider_refresh_policies AS policy
          ON policy.provider_dataset_id = fact.provider_dataset_id
         AND policy.enabled
         AND policy.stale_after_minutes IS NOT NULL
    ), actual_series AS (
        SELECT
            feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
            max(selected_at) AS selected_at
        FROM actual
        GROUP BY feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key
    ), missing_series AS (
        SELECT DISTINCT
            fact.feature_id, fact.provider_dataset_id, fact.weather_domain,
            fact.forecast_style, fact.metric_key
        FROM policy_facts AS fact
        WHERE NOT EXISTS (
            SELECT 1
            FROM actual_series AS actual_series
            WHERE actual_series.feature_id = fact.feature_id
              AND actual_series.provider_dataset_id = fact.provider_dataset_id
              AND actual_series.weather_domain = fact.weather_domain
              AND actual_series.forecast_style = fact.forecast_style
              AND actual_series.metric_key = fact.metric_key
        )
    ), series_clocks AS (
        SELECT
            feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
            selected_at
        FROM actual_series
        UNION ALL
        SELECT
            missing.feature_id, missing.provider_dataset_id, missing.weather_domain,
            missing.forecast_style, missing.metric_key, clock.selected_at
        FROM missing_series AS missing
        CROSS JOIN (SELECT clock_timestamp() AS selected_at) AS clock
    ), ranked AS (
        SELECT
            series.feature_id, series.provider_dataset_id, series.weather_domain,
            series.forecast_style, series.metric_key, fact.weather_value_key,
            row_number() OVER (
                PARTITION BY series.feature_id, series.provider_dataset_id,
                             series.weather_domain, series.forecast_style, series.metric_key
                ORDER BY fact.target_at DESC,
                         fact.known_at DESC,
                         upper(fact.valid_during) DESC NULLS LAST,
                         fact.issued_at DESC NULLS LAST,
                         fact.valid_at DESC NULLS LAST,
                         fact.observed_at DESC NULLS LAST,
                         fact.weather_value_key DESC
            ) AS row_number
        FROM series_clocks AS series
        JOIN policy_facts AS fact
          ON fact.feature_id = series.feature_id
         AND fact.provider_dataset_id = series.provider_dataset_id
         AND fact.weather_domain = series.weather_domain
         AND fact.forecast_style = series.forecast_style
         AND fact.metric_key = series.metric_key
        WHERE fact.known_at <= series.selected_at
          AND fact.target_at <= series.selected_at
          AND (fact.valid_during IS NULL OR fact.valid_during @> series.selected_at)
          AND fact.known_at + (fact.stale_after_minutes * interval '1 minute')
                > series.selected_at
    ), expected AS (
        SELECT feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
               weather_value_key
        FROM ranked
        WHERE row_number = 1
    )
    (
        SELECT feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
               weather_value_key
        FROM expected
        EXCEPT ALL
        SELECT feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
               weather_value_key
        FROM actual
    )
    UNION ALL
    (
        SELECT feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
               weather_value_key
        FROM actual
        EXCEPT ALL
        SELECT feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
               weather_value_key
        FROM expected
    )
) AS difference; -- expect: 0 -- phase: post-backfill

-- [INV-089-02] selected weather fact는 eligible하고 refresh deadline은 미래다.
SELECT count(*)
FROM feature.current_weather_summary AS s
JOIN feature.feature_weather_values AS w
  ON w.weather_value_key = s.weather_value_key
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = w.provider_dataset_id
 AND dataset.is_active
JOIN ops.provider_refresh_policies AS policy
  ON policy.provider_dataset_id = w.provider_dataset_id
 AND policy.enabled
 AND policy.stale_after_minutes IS NOT NULL
WHERE w.known_at > s.selected_at
   OR w.target_at > s.selected_at
   OR (w.valid_during IS NOT NULL AND NOT (w.valid_during @> s.selected_at))
   OR w.known_at + (policy.stale_after_minutes * interval '1 minute') <= s.selected_at
   OR s.refresh_after <= s.selected_at; -- expect: 0 -- phase: post-backfill

-- [INV-089-03] summary는 성공한 같은 projection receipt만 참조한다.
SELECT count(*)
FROM (
    SELECT summary_run_id, projection_kind, receipt_status
    FROM feature.current_weather_summary
    UNION ALL
    SELECT summary_run_id, projection_kind, receipt_status
    FROM feature.current_price_summary
) AS s
LEFT JOIN ops.current_summary_runs AS r
    ON r.summary_run_id = s.summary_run_id
   AND r.projection_kind = s.projection_kind
   AND r.status = s.receipt_status
WHERE r.summary_run_id IS NULL OR r.status <> 'succeeded'; -- expect: 0 -- phase: post-backfill

-- -----------------------------------------------------------------------------
-- ADR-078 — price series identity (T-VN-38B)
-- -----------------------------------------------------------------------------

-- [INV-078-01] immutable source revision당 observation identity 중복 없음.
SELECT count(*)
FROM (
    SELECT feature_id, provider_dataset_id, price_domain, product_key, observed_at, source_record_key
    FROM feature.feature_price_values
    GROUP BY feature_id, provider_dataset_id, price_domain, product_key, observed_at, source_record_key
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-078-02] 음수 가격 없음 (CHECK preflight).
SELECT count(*)
FROM feature.feature_price_values
WHERE value_number < 0; -- expect: 0 -- phase: both

-- [INV-078-03] price current summary pointer는 같은 canonical series의 immutable
-- history fact를 가리킨다 (ADR-089 reconciliation gate).
SELECT count(*)
FROM feature.current_price_summary AS s
LEFT JOIN feature.feature_price_values AS p
    ON p.price_value_key = s.price_value_key
   AND p.feature_id = s.feature_id
   AND p.provider_dataset_id = s.provider_dataset_id
   AND p.price_domain = s.price_domain
   AND p.product_key = s.product_key
WHERE p.price_value_key IS NULL; -- expect: 0 -- phase: post-backfill

-- [INV-089-04] price summary는 observed/known/key winner를 정확히 가리킨다.
SELECT count(*)
FROM (
    WITH actual AS (
        SELECT feature_id, provider_dataset_id, price_domain, product_key, price_value_key
        FROM feature.current_price_summary
    ), ranked AS (
        SELECT
            p.feature_id, p.provider_dataset_id, p.price_domain, p.product_key, p.price_value_key,
            row_number() OVER (
                PARTITION BY p.feature_id, p.provider_dataset_id, p.price_domain, p.product_key
                ORDER BY p.observed_at DESC, p.known_at DESC, p.price_value_key DESC
            ) AS row_number
        FROM feature.feature_price_values AS p
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = p.provider_dataset_id
         AND dataset.is_active
    ), expected AS (
        SELECT feature_id, provider_dataset_id, price_domain, product_key, price_value_key
        FROM ranked
        WHERE row_number = 1
    )
    (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
    UNION ALL
    (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
) AS difference; -- expect: 0 -- phase: post-backfill

-- [INV-089-05] 두 fact domain의 source record/entity/dataset lineage는 한 소유자다.
SELECT count(*)
FROM (
    SELECT w.source_record_key, w.source_entity_key, w.provider_dataset_id, w.known_at
    FROM feature.feature_weather_values AS w
    UNION ALL
    SELECT p.source_record_key, p.source_entity_key, p.provider_dataset_id, p.known_at
    FROM feature.feature_price_values AS p
) AS fact
LEFT JOIN provider_sync.source_records AS record
  ON record.source_record_key = fact.source_record_key
 AND record.source_entity_key = fact.source_entity_key
 AND record.fetched_at = fact.known_at
LEFT JOIN provider_sync.source_entities AS entity
  ON entity.source_entity_key = fact.source_entity_key
 AND entity.provider_dataset_id = fact.provider_dataset_id
WHERE record.source_record_key IS NULL OR entity.source_entity_key IS NULL; -- expect: 0 -- phase: both

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
    SELECT rule_id, source_entity_key, feature_id
    FROM feature.theme_feature_candidates
    GROUP BY rule_id, source_entity_key, feature_id
    HAVING count(*) > 1
) AS duplicated; -- expect: 0 -- phase: both

-- [INV-040-03] candidate FK orphan 없음 (rule·entity·record·feature 네 축).
SELECT count(*)
FROM feature.theme_feature_candidates AS c
LEFT JOIN feature.curated_source_rules AS r ON r.rule_id = c.rule_id
LEFT JOIN provider_sync.source_entities AS e ON e.source_entity_key = c.source_entity_key
LEFT JOIN provider_sync.source_records AS sr
  ON sr.source_entity_key = c.source_entity_key
 AND sr.source_record_key = c.source_record_key
LEFT JOIN feature.features AS f ON f.feature_id = c.feature_id
WHERE r.rule_id IS NULL
   OR e.source_entity_key IS NULL
   OR sr.source_record_key IS NULL
   OR f.feature_id IS NULL; -- expect: 0 -- phase: both

-- [INV-040-04] merged tombstone은 exact active winner를 한 단계로 가리킨다.
SELECT count(*)
FROM feature.theme_feature_candidates AS loser
LEFT JOIN feature.theme_feature_candidates AS winner
  ON winner.candidate_id = loser.merged_into_candidate_id
 AND winner.rule_id = loser.rule_id
 AND winner.source_entity_key = loser.source_entity_key
 AND winner.disposition = 'active'
WHERE (loser.disposition = 'active'
       AND (loser.merged_into_candidate_id IS NOT NULL OR loser.retired_at IS NOT NULL))
   OR (loser.disposition = 'merged'
       AND (loser.merged_into_candidate_id IS NULL OR loser.retired_at IS NULL
            OR winner.candidate_id IS NULL)); -- expect: 0 -- phase: both

-- [INV-040-05] reconcile receipt의 durable scope count는 child exact set과 같다.
SELECT count(*)
FROM ops.curation_rule_reconcile_operations AS operation
WHERE operation.scope_member_count <> (
    SELECT count(*)
    FROM ops.curation_rule_reconcile_scope_members AS member
    WHERE member.operation_id = operation.operation_id
); -- expect: 0 -- phase: both

-- [INV-040-06] generation kind별 authoritative origin XOR 위반 없음.
SELECT count(*)
FROM feature.theme_candidate_generations
WHERE NOT (
    (generation_kind = 'provider_full_snapshot'
     AND source_job_id IS NOT NULL AND reconcile_operation_id IS NULL AND command_id IS NULL)
    OR (generation_kind IN ('scoped_reconcile','rule_reconcile')
        AND source_job_id IS NULL AND reconcile_operation_id IS NOT NULL)
    OR (generation_kind = 'legacy_backfill'
        AND source_job_id IS NULL AND reconcile_operation_id IS NULL AND command_id IS NULL)
); -- expect: 0 -- phase: both

-- [INV-040-07] observation은 generation의 rule과 같은 current candidate identity만 가리킨다.
SELECT count(*)
FROM feature.theme_candidate_generation_observations AS observation
JOIN feature.theme_candidate_generations AS generation
  ON generation.generation_id = observation.generation_id
LEFT JOIN feature.theme_feature_candidates AS candidate
  ON candidate.candidate_id = observation.candidate_id
 AND candidate.rule_id = generation.rule_id
 AND candidate.source_entity_key = observation.source_entity_key
 AND candidate.feature_id = observation.feature_id
WHERE candidate.candidate_id IS NULL; -- expect: 0 -- phase: both

-- [INV-040-08] live candidate query는 merged tombstone을 포함하지 않는다.
SELECT count(*)
FROM feature.theme_feature_candidates
WHERE disposition <> 'active'
  AND review_state = 'open'
  AND eligibility_present
  AND candidate_id IN (
      SELECT candidate_id
      FROM feature.theme_feature_candidates
      WHERE disposition = 'active'
  ); -- expect: 0 -- phase: both

-- [INV-040-09] final target에는 legacy overlay relation이 없다.
SELECT count(*)
FROM (SELECT to_regclass('feature.curated_features') AS relation_oid) AS legacy
WHERE relation_oid IS NOT NULL; -- expect: 0 -- phase: post-backfill

-- [INV-040-10] retained catalog ownership은 operator/provider_dataset 두 exact shape뿐이다.
SELECT count(*)
FROM (
    SELECT owner_kind, owner_provider_dataset_id FROM feature.curated_themes
    UNION ALL
    SELECT owner_kind, owner_provider_dataset_id FROM feature.curated_source_rules
) AS catalog
WHERE NOT (
    (owner_kind = 'operator' AND owner_provider_dataset_id IS NULL)
    OR (owner_kind = 'provider_dataset' AND owner_provider_dataset_id IS NOT NULL)
); -- expect: 0 -- phase: both
