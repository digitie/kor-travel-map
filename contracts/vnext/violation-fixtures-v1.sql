-- =============================================================================
-- contracts/vnext/violation-fixtures-v1.sql — T-VN-31C 제약 위반 fixture freeze
-- =============================================================================
-- target-schema-v1.sql의 제약을 **위반**하는 fixture INSERT 집합이다. 각 case는
-- `-- case: <case_id>` 헤더로 구분되며, 독립 transaction에서 실행돼 마지막
-- INSERT가 expected-rejections-v1.json의 SQLSTATE·제약명으로 거부되어야 한다.
-- (tests/integration/test_vnext_target_freeze.py가 case별로 실행·rollback한다.)
--
-- case 앞부분의 INSERT는 위반을 재현하기 위한 최소 부모 행이며 성공해야 한다.
--
-- (3축 불가능 조합 case는 없다 — 불가능 조합의 집합은 정본이 열거하지 않아
-- CHECK 자체가 미정(T-VN-34A 구현 소관)이다. 구현이 CHECK를 확정하면 그
-- PR에서 case를 추가한다.)
-- =============================================================================

-- case: alias_duplicate
INSERT INTO feature.categories (kind, code) VALUES ('place', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000001', 'place', 'alias 중복 부모', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO feature.feature_aliases (alias, feature_id, alias_kind)
VALUES ('f_duplicate_alias', '00000000-0000-0000-0000-000000000001', 'legacy');
INSERT INTO feature.feature_aliases (alias, feature_id, alias_kind)
VALUES ('f_duplicate_alias', '00000000-0000-0000-0000-000000000001', 'legacy');

-- case: provider_identity_tuple_duplicate
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'fixture', 'fixture dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'entity-1',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'place', 'natural-1', now(), now()
);
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'entity-2',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'place', 'natural-1', now(), now()
);

-- case: geometry_invalid
INSERT INTO feature.categories (kind, code) VALUES ('area', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000002', 'area', 'invalid geometry 부모', 'fixture',
    'active', 'published', 'valid'
);
-- 자기교차 bowtie polygon — ST_IsValid = false (anchor는 envelope 안이라 통과).
INSERT INTO feature.feature_areas (feature_id, kind, geom, anchor)
VALUES (
    '00000000-0000-0000-0000-000000000002', 'area',
    x_extension.st_geomfromtext('MULTIPOLYGON(((0 0,1 1,1 0,0 1,0 0)))', 4326),
    x_extension.st_setsrid(x_extension.st_makepoint(0.5, 0.5), 4326)
);

-- case: geometry_empty
INSERT INTO feature.categories (kind, code) VALUES ('place', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000003', 'place', 'empty geometry 부모', 'fixture',
    'active', 'published', 'valid'
);
-- POINT EMPTY — ST_IsValid = true이지만 NOT ST_IsEmpty CHECK가 거부한다.
INSERT INTO feature.feature_points (feature_id, kind, geom)
VALUES (
    '00000000-0000-0000-0000-000000000003', 'place',
    x_extension.st_geomfromtext('POINT EMPTY', 4326)
);

-- case: override_active_duplicate
INSERT INTO feature.categories (kind, code) VALUES ('place', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000004', 'place', 'override 중복 부모', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO ops.feature_override_field_paths (field_path, value_type)
VALUES ('name', 'string');
INSERT INTO ops.feature_overrides (
    feature_id, field_path, override_value, created_by
) VALUES (
    '00000000-0000-0000-0000-000000000004', 'name', '"수동 보정 1"'::jsonb, 'operator-a'
);
INSERT INTO ops.feature_overrides (
    feature_id, field_path, override_value, created_by
) VALUES (
    '00000000-0000-0000-0000-000000000004', 'name', '"수동 보정 2"'::jsonb, 'operator-b'
);

-- case: notice_is_current_duplicate
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'fixture', 'fixture dataset', 'manual');
INSERT INTO provider_sync.notice_states (
    provider_dataset_id, source_entity_type, lineage_key, present,
    valid_during, is_current
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'notice', 'lineage-1', true,
    tstzrange('2026-01-01+00', '2026-02-01+00', '[)'), true
);
INSERT INTO provider_sync.notice_states (
    provider_dataset_id, source_entity_type, lineage_key, present,
    valid_during, is_current
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'notice', 'lineage-1', false,
    tstzrange('2026-02-01+00', '2026-03-01+00', '[)'), true
);

-- case: weather_identity_nulls_not_distinct_duplicate
INSERT INTO feature.categories (kind, code) VALUES ('weather', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000005', 'weather', 'NND 중복 부모', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'fixture', 'fixture dataset', 'manual');
-- nullable 시간축(issued_at/valid_at/observed_at) 전부 NULL 2건 — NULLS NOT
-- DISTINCT UNIQUE(uq_weather_value_identity)가 "NULL끼리 같은 행"으로 묶어
-- 거부한다 (ADR-072 결정 3, 0060 정본).
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number,
    issued_at, valid_at, observed_at, target_at, known_at
) VALUES (
    'weather-nnd-1', '00000000-0000-0000-0000-000000000005',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'forecast', 'short', 'TMP', 1.0,
    NULL, NULL, NULL, '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number,
    issued_at, valid_at, observed_at, target_at, known_at
) VALUES (
    'weather-nnd-2', '00000000-0000-0000-0000-000000000005',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'forecast', 'short', 'TMP', 2.0,
    NULL, NULL, NULL, '2026-01-02T00:00:00+00', '2026-01-02T00:00:00+00'
);

-- case: weather_bitemporal_inversion
INSERT INTO feature.categories (kind, code) VALUES ('weather', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000006', 'weather', 'bitemporal 역전 부모', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'fixture', 'fixture dataset', 'manual');

-- issued_at > known_at — 미래지식 누출 (보고서 D-8-3) 거부.
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number,
    issued_at, target_at, known_at
) VALUES (
    'weather-value-1', '00000000-0000-0000-0000-000000000006',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-02T00:00:00+00', '2026-01-02T03:00:00+00', '2026-01-01T00:00:00+00'
);

-- case: provider_dataset_capability_invalid
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind, capabilities
) VALUES (
    'fixture', 'invalid-capability', 'invalid capability dataset', 'manual',
    '{"schema_version":1,"produces":[],"refresh":{"enabled":false,"allowed_sync_scopes":[],"target_selector":"none"},"preview":{"kind":"unsupported"},"extensions":{}}'::jsonb
);

-- case: inactive_dataset_source_entity_write
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind, is_active
) VALUES ('fixture', 'inactive', 'inactive fixture dataset', 'manual', false);
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'inactive-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive'),
    'place', 'inactive-natural-1', now(), now()
);

-- case: source_record_immutable_update
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'immutable', 'immutable fixture dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'immutable-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'immutable'),
    'place', 'immutable-natural-1', now(), now()
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES ('immutable-record', 'immutable-entity', '{}'::jsonb, 'a1', now());
UPDATE provider_sync.source_records
SET raw_data = '{"changed":true}'::jsonb
WHERE source_record_key = 'immutable-record';

-- case: source_head_cross_entity
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'head', 'head fixture dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES
    ('head-entity-a', (SELECT provider_dataset_id FROM provider_sync.provider_datasets
        WHERE provider = 'fixture' AND dataset_key = 'head'), 'place', 'head-a', now(), now()),
    ('head-entity-b', (SELECT provider_dataset_id FROM provider_sync.provider_datasets
        WHERE provider = 'fixture' AND dataset_key = 'head'), 'place', 'head-b', now(), now());
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES
    ('head-record-a', 'head-entity-a', '{}'::jsonb, 'a2', now()),
    ('head-record-b', 'head-entity-b', '{}'::jsonb, 'a3', now());
INSERT INTO provider_sync.source_entity_heads (
    source_entity_key, current_source_record_key, observed_at
) VALUES ('head-entity-a', 'head-record-b', now());

-- case: source_head_missing
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'head-missing', 'head missing fixture dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'head-missing-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'head-missing'),
    'place', 'head-missing', now(), now()
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES ('head-missing-record', 'head-missing-entity', '{}'::jsonb, 'a4', now());
SET CONSTRAINTS ALL IMMEDIATE;
