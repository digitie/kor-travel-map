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

-- case: weather_source_revision_identity_duplicate
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
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'weather-identity-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'weather-response', 'identity-revision', '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'weather-identity-record', 'weather-identity-entity', '{}'::jsonb, 'd1',
    '2026-01-01T00:00:00+00'
);
-- 동일 source-record revision을 다시 저장하면 fact key가 달라도 immutable identity가
-- 충돌한다. correction은 새 record와 새 fact를 append해야 한다(ADR-089).
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number,
    target_at, known_at, source_entity_key, source_record_key
) VALUES (
    'weather-identity-1', '00000000-0000-0000-0000-000000000005',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00',
    'weather-identity-entity', 'weather-identity-record'
);
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number,
    target_at, known_at, source_entity_key, source_record_key
) VALUES (
    'weather-identity-2', '00000000-0000-0000-0000-000000000005',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'forecast', 'short', 'TMP', 2.0,
    '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00',
    'weather-identity-entity', 'weather-identity-record'
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
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'weather-bitemporal-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'weather-response', 'bitemporal-revision', '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'weather-bitemporal-record', 'weather-bitemporal-entity', '{}'::jsonb, 'd2',
    '2026-01-01T00:00:00+00'
);

-- issued_at > known_at — 미래지식 누출 (보고서 D-8-3) 거부.
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number,
    issued_at, target_at, known_at, source_entity_key, source_record_key
) VALUES (
    'weather-value-1', '00000000-0000-0000-0000-000000000006',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'fixture'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-02T00:00:00+00', '2026-01-02T03:00:00+00', '2026-01-01T00:00:00+00',
    'weather-bitemporal-entity', 'weather-bitemporal-record'
);

-- case: provider_dataset_capability_invalid
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind, capabilities
) VALUES (
    'fixture', 'invalid-capability', 'invalid capability dataset', 'manual',
    '{"schema_version":1,"produces":[],"refresh":{"enabled":false,"allowed_sync_scopes":[],"target_selector":"none"},"preview":{"kind":"unsupported"},"extensions":{}}'::jsonb
);

-- case: provider_dataset_capability_version_type_invalid
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind, capabilities
) VALUES (
    'fixture', 'invalid-capability-version', 'invalid capability version', 'manual',
    '{"schema_version":"1","produces":[],"extensions":{}}'::jsonb
);

-- case: provider_dataset_operation_scope_invalid
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'operation-scope-invalid', 'operation scope invalid dataset', 'manual');
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'operation-scope-invalid'),
    'refresh', 'refresh'
);
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'operation-scope-invalid'),
    'not a canonical scope', 'refresh'
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

-- case: inactive_dataset_existing_operation_update
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-operation', 'inactive operation dataset', 'manual');
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-operation'),
    'refresh', 'refresh'
);
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-operation';
UPDATE provider_sync.provider_dataset_operations
SET is_enabled = false
WHERE operation_key = 'refresh';

-- case: inactive_dataset_source_record_write
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-record', 'inactive record dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'inactive-record-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-record'),
    'place', 'inactive-record-natural', now(), now()
);
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-record';
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES ('inactive-record', 'inactive-record-entity', '{}'::jsonb, 'a5', now());

-- case: inactive_dataset_source_head_update
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-head', 'inactive head dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'inactive-head-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-head'),
    'place', 'inactive-head-natural', now(), now()
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES ('inactive-head-record', 'inactive-head-entity', '{}'::jsonb, 'a6', now());
INSERT INTO provider_sync.source_entity_heads (
    source_entity_key, current_source_record_key, observed_at
) VALUES ('inactive-head-entity', 'inactive-head-record', now());
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-head';
UPDATE provider_sync.source_entity_heads
SET observed_at = observed_at + interval '1 second'
WHERE source_entity_key = 'inactive-head-entity';

-- case: inactive_dataset_source_link_write
INSERT INTO feature.categories (kind, code) VALUES ('place', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000007', 'place', 'inactive link parent', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-link', 'inactive link dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'inactive-link-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-link'),
    'place', 'inactive-link-natural', now(), now()
);
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-link';
INSERT INTO provider_sync.source_links (
    feature_id, source_entity_key, source_role, match_method, confidence
) VALUES (
    '00000000-0000-0000-0000-000000000007', 'inactive-link-entity',
    'primary', 'fixture', 100
);

-- case: inactive_dataset_sync_state_update
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-sync-state', 'inactive sync state dataset', 'manual');
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-sync-state'),
    'refresh', 'refresh'
);
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-sync-state'),
    'dataset_wide', 'refresh'
);
INSERT INTO provider_sync.provider_sync_state (
    provider_dataset_id, sync_scope
, operation_key) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-sync-state'),
    'dataset_wide'
, 'refresh');
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-sync-state';
UPDATE provider_sync.provider_sync_state
SET status = 'paused'
WHERE sync_scope = 'dataset_wide';

-- case: dataset_scope_unregistered_write
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'unregistered-scope', 'unregistered scope dataset', 'manual');
INSERT INTO provider_sync.provider_sync_state (
    provider_dataset_id, sync_scope
, operation_key) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'unregistered-scope'),
    'dataset_wide'
, 'refresh');

-- case: inactive_dataset_notice_lineage_write
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-notice-lineage', 'inactive notice lineage dataset', 'manual');
INSERT INTO provider_sync.notice_lifecycle_scopes (
    provider_dataset_id, source_entity_type, mode, applied_at, state_fingerprint
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-notice-lineage'),
    'notice', 'snapshot', now(), 'fixture-notice-state'
);
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-notice-lineage';
INSERT INTO provider_sync.notice_lineage_states (
    notice_lifecycle_scope_id, lineage_key, present, changed_at
) VALUES (
    (SELECT notice_lifecycle_scope_id FROM provider_sync.notice_lifecycle_scopes
     WHERE source_entity_type = 'notice'),
    'fixture-lineage', true, now()
);

-- case: inactive_dataset_curated_rule_write
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-curation', 'inactive curation dataset', 'manual');
INSERT INTO feature.curated_sources (
    provider_dataset_id, source_name, source_kind
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-curation'),
    'fixture curated source', 'manual'
);
INSERT INTO feature.curated_themes (theme_key, title)
VALUES ('fixture-inactive-curation', 'fixture inactive curation');
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-curation';
INSERT INTO feature.curated_source_rules (theme_id, source_id)
VALUES (
    (SELECT theme_id FROM feature.curated_themes
     WHERE theme_key = 'fixture-inactive-curation'),
    (SELECT source_id FROM feature.curated_sources
     WHERE source_name = 'fixture curated source')
);

-- case: inactive_dataset_import_event_write
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-import-event', 'inactive import event dataset', 'manual');
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-import-event'),
    'refresh', 'refresh'
);
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-import-event'),
    'dataset_wide', 'refresh'
);
INSERT INTO ops.import_jobs (kind, dataset_membership_mode) VALUES ('fixture', 'single');
INSERT INTO ops.import_job_datasets (job_id, provider_dataset_id, sync_scope, operation_key)
VALUES (
    (SELECT job_id FROM ops.import_jobs WHERE kind = 'fixture'),
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-import-event'),
    'dataset_wide'
, 'refresh');
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-import-event';
INSERT INTO ops.import_job_events (job_id, import_job_dataset_id, event_kind)
VALUES (
    (SELECT job_id FROM ops.import_jobs WHERE kind = 'fixture'),
    (SELECT import_job_dataset_id FROM ops.import_job_datasets),
    'fixture'
);

-- case: inactive_dataset_import_job_parent_update
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-import-parent', 'inactive import parent dataset', 'manual');
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-import-parent'),
    'refresh', 'refresh'
);
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-import-parent'),
    'dataset_wide', 'refresh'
);
INSERT INTO ops.import_jobs (kind, dataset_membership_mode)
VALUES ('fixture-inactive-import-parent', 'single');
INSERT INTO ops.import_job_datasets (job_id, provider_dataset_id, sync_scope, operation_key)
VALUES (
    (SELECT job_id FROM ops.import_jobs WHERE kind = 'fixture-inactive-import-parent'),
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-import-parent'),
    'dataset_wide'
, 'refresh');
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-import-parent';
UPDATE ops.import_jobs
SET status = 'running'
WHERE kind = 'fixture-inactive-import-parent';

-- case: inactive_dataset_feature_update_request_parent_update
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-update-parent', 'inactive update parent dataset', 'manual');
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-update-parent'),
    'refresh', 'refresh'
);
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-update-parent'),
    'dataset_wide', 'refresh'
);
INSERT INTO ops.feature_update_requests (dataset_membership_mode)
VALUES ('single');
INSERT INTO ops.feature_update_request_datasets (
    request_id, provider_dataset_id, sync_scope
, operation_key) VALUES (
    (SELECT request_id FROM ops.feature_update_requests),
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-update-parent'),
    'dataset_wide'
, 'refresh');
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-update-parent';
UPDATE ops.feature_update_requests
SET status = 'running'
WHERE request_id = (SELECT request_id FROM ops.feature_update_request_datasets);

-- case: inactive_dataset_integrity_run_write
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-integrity', 'inactive integrity dataset', 'manual');
INSERT INTO ops.integrity_observation_scopes (provider_dataset_id)
VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-integrity')
);
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-integrity';
INSERT INTO ops.integrity_observation_runs (
    integrity_observation_scope_id, generation, external_run_id
) VALUES (
    (SELECT integrity_observation_scope_id FROM ops.integrity_observation_scopes),
    1, 'fixture'
);

-- case: inactive_dataset_source_record_derived_violation
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-derived-violation', 'inactive derived violation dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'inactive-derived-violation-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-derived-violation'),
    'place', 'inactive-derived-violation', now(), now()
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'inactive-derived-violation-record', 'inactive-derived-violation-entity',
    '{}'::jsonb, 'c2', now()
);
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-derived-violation';
INSERT INTO ops.data_integrity_violations (source_record_key, violation_type)
VALUES ('inactive-derived-violation-record', 'fixture');

-- case: inactive_dataset_managed_file_owner_clear
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-managed-file', 'inactive managed file dataset', 'manual');
INSERT INTO ops.managed_files (
    provider_dataset_id, storage_backend, location, path
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-managed-file'),
    'fixture', 'fixture', '/fixture'
);
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-managed-file';
UPDATE ops.managed_files
SET provider_dataset_id = NULL, provider_name = 'fixture'
WHERE location = 'fixture';

-- case: import_job_single_member_missing
INSERT INTO ops.import_jobs (kind, dataset_membership_mode)
VALUES ('fixture-single-member-missing', 'single');
SET CONSTRAINTS ALL IMMEDIATE;

-- case: feature_update_request_single_member_missing
INSERT INTO ops.feature_update_requests (dataset_membership_mode)
VALUES ('single');
SET CONSTRAINTS ALL IMMEDIATE;

-- case: inactive_dataset_source_record_delete
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'inactive-record-delete', 'inactive record delete dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'inactive-record-delete-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'inactive-record-delete'),
    'place', 'inactive-record-delete', now(), now()
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'inactive-record-delete-record', 'inactive-record-delete-entity', '{}'::jsonb, 'c3', now()
);
UPDATE provider_sync.provider_datasets
SET is_active = false
WHERE provider = 'fixture' AND dataset_key = 'inactive-record-delete';
DELETE FROM provider_sync.source_records
WHERE source_record_key = 'inactive-record-delete-record';

-- case: import_event_cross_job_member
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'cross-job-member', 'cross job member dataset', 'manual');
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'cross-job-member'),
    'refresh', 'refresh'
);
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'cross-job-member'),
    'dataset_wide', 'refresh'
);
INSERT INTO ops.import_jobs (kind, dataset_membership_mode)
VALUES ('fixture-cross-job-a', 'single'), ('fixture-cross-job-b', 'single');
INSERT INTO ops.import_job_datasets (job_id, provider_dataset_id, sync_scope, operation_key)
VALUES (
    (SELECT job_id FROM ops.import_jobs WHERE kind = 'fixture-cross-job-a'),
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'cross-job-member'),
    'dataset_wide'
, 'refresh');
INSERT INTO ops.import_job_events (job_id, import_job_dataset_id, event_kind)
VALUES (
    (SELECT job_id FROM ops.import_jobs WHERE kind = 'fixture-cross-job-b'),
    (SELECT import_job_dataset_id FROM ops.import_job_datasets),
    'fixture'
);

-- case: integrity_violation_cross_dataset
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES
    ('fixture', 'integrity-source', 'integrity source dataset', 'manual'),
    ('fixture', 'integrity-other', 'integrity other dataset', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'integrity-source-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'integrity-source'),
    'place', 'integrity-source', now(), now()
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'integrity-source-record', 'integrity-source-entity', '{}'::jsonb, 'c1', now()
);
INSERT INTO ops.data_integrity_violations (
    provider_dataset_id, source_record_key, violation_type
) VALUES (
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'integrity-other'),
    'integrity-source-record', 'fixture'
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

-- case: weather_source_lineage_required
INSERT INTO feature.categories (kind, code) VALUES ('weather', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000008', 'weather', 'source 없는 weather fact', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'weather-source-required', 'weather source required', 'manual');
-- source-less fact write는 NOT NULL에서 즉시 거부된다. loader의 fallback/upsert로
-- provenance를 추정하는 우회는 허용하지 않는다(ADR-089 결정 1).
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number, target_at, known_at
) VALUES (
    'weather-source-required', '00000000-0000-0000-0000-000000000008',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'weather-source-required'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00'
);

-- case: weather_source_dataset_mismatch
INSERT INTO feature.categories (kind, code) VALUES ('weather', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000009', 'weather', 'dataset 불일치 weather fact', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES
    ('fixture', 'weather-source-owner', 'weather source owner', 'manual'),
    ('fixture', 'weather-fact-owner', 'weather fact owner', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'weather-source-owner-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'weather-source-owner'),
    'weather-response', 'weather-source-owner', '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'weather-source-owner-record', 'weather-source-owner-entity', '{}'::jsonb, 'd3',
    '2026-01-01T00:00:00+00'
);
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number, target_at, known_at,
    source_entity_key, source_record_key
) VALUES (
    'weather-source-dataset-mismatch', '00000000-0000-0000-0000-000000000009',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'weather-fact-owner'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00',
    'weather-source-owner-entity', 'weather-source-owner-record'
);

-- case: weather_kma_grid_record_dataset_mismatch
INSERT INTO feature.categories (kind, code) VALUES ('weather', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000010', 'weather', 'KMA grid provenance 거부', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES
    ('kma', 'kma_short_grid', 'KMA short grid', 'openapi'),
    ('kma', 'kma_short_forecast', 'KMA short forecast', 'openapi');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'kma-grid-source-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'kma' AND dataset_key = 'kma_short_grid'),
    'grid', '60:127', '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'kma-grid-source-record', 'kma-grid-source-entity', '{}'::jsonb, 'd4',
    '2026-01-01T00:00:00+00'
);
-- grid Feature source record는 forecast value fact의 raw response가 아니다. forecast
-- producer dataset의 별도 response entity/record가 필요하다(ADR-089 결정 1).
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number, target_at, known_at,
    source_entity_key, source_record_key
) VALUES (
    'kma-grid-record-for-forecast', '00000000-0000-0000-0000-000000000010',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'kma' AND dataset_key = 'kma_short_forecast'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00',
    'kma-grid-source-entity', 'kma-grid-source-record'
);

-- case: weather_fact_immutable_update
INSERT INTO feature.categories (kind, code) VALUES ('weather', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000011', 'weather', 'weather 불변 fact', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'weather-immutable', 'weather immutable', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'weather-immutable-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'weather-immutable'),
    'weather-response', 'weather-immutable', '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'weather-immutable-record', 'weather-immutable-entity', '{}'::jsonb, 'd5',
    '2026-01-01T00:00:00+00'
);
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number, target_at, known_at,
    source_entity_key, source_record_key
) VALUES (
    'weather-immutable-fact', '00000000-0000-0000-0000-000000000011',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'weather-immutable'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00',
    'weather-immutable-entity', 'weather-immutable-record'
);
UPDATE feature.feature_weather_values
SET value_number = 2.0
WHERE weather_value_key = 'weather-immutable-fact';

-- case: price_fact_immutable_delete
INSERT INTO feature.categories (kind, code) VALUES ('price', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000012', 'price', 'price 불변 fact', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'price-immutable', 'price immutable', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'price-immutable-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'price-immutable'),
    'price-response', 'price-immutable', '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'price-immutable-record', 'price-immutable-entity', '{}'::jsonb, 'd6',
    '2026-01-01T00:00:00+00'
);
INSERT INTO feature.feature_price_values (
    price_value_key, feature_id, provider_dataset_id, price_domain, product_key,
    observed_at, known_at, value_number, source_entity_key, source_record_key
) VALUES (
    'price-immutable-fact', '00000000-0000-0000-0000-000000000012',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'price-immutable'),
    'retail', 'B027', '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00', 1500.0,
    'price-immutable-entity', 'price-immutable-record'
);
DELETE FROM feature.feature_price_values
WHERE price_value_key = 'price-immutable-fact';

-- case: terminal_summary_receipt_immutable
INSERT INTO ops.current_summary_runs (
    projection_kind, run_kind, status, started_at, finished_at
) VALUES (
    'weather', 'reconcile', 'succeeded', '2026-01-01T00:00:00+00', '2026-01-01T00:01:00+00'
);
UPDATE ops.current_summary_runs
SET detail = '{"rewritten":true}'::jsonb
WHERE projection_kind = 'weather' AND status = 'succeeded';

-- case: current_weather_summary_cross_series_fact
INSERT INTO feature.categories (kind, code) VALUES ('weather', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000013', 'weather', 'summary 다른 series fact', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES
    ('fixture', 'summary-fact-a', 'summary fact A', 'manual'),
    ('fixture', 'summary-fact-b', 'summary fact B', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'summary-fact-a-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'summary-fact-a'),
    'weather-response', 'summary-fact-a', '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'summary-fact-a-record', 'summary-fact-a-entity', '{}'::jsonb, 'd7',
    '2026-01-01T00:00:00+00'
);
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number, target_at, known_at,
    source_entity_key, source_record_key
) VALUES (
    'summary-fact-a-value', '00000000-0000-0000-0000-000000000013',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'summary-fact-a'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00',
    'summary-fact-a-entity', 'summary-fact-a-record'
);
INSERT INTO ops.current_summary_runs (
    projection_kind, run_kind, status, started_at, finished_at
) VALUES (
    'weather', 'reconcile', 'succeeded', '2026-01-01T03:00:00+00', '2026-01-01T03:01:00+00'
);
INSERT INTO feature.current_weather_summary (
    feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
    weather_value_key, summary_run_id, selected_at, refresh_after
) VALUES (
    '00000000-0000-0000-0000-000000000013',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'summary-fact-b'),
    'forecast', 'short', 'TMP', 'summary-fact-a-value',
    (SELECT summary_run_id FROM ops.current_summary_runs
     WHERE projection_kind = 'weather' AND status = 'succeeded'),
    '2026-01-01T03:00:00+00', '2026-01-01T04:00:00+00'
);

-- case: current_weather_summary_refresh_after_invalid
INSERT INTO feature.categories (kind, code) VALUES ('weather', 'fixture');
INSERT INTO feature.features (
    feature_id, kind, name, category_code,
    lifecycle_state, publication_state, quality_state
) VALUES (
    '00000000-0000-0000-0000-000000000014', 'weather', 'summary refresh deadline', 'fixture',
    'active', 'published', 'valid'
);
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind
) VALUES ('fixture', 'summary-refresh', 'summary refresh', 'manual');
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    'summary-refresh-entity',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'summary-refresh'),
    'weather-response', 'summary-refresh', '2026-01-01T00:00:00+00', '2026-01-01T00:00:00+00'
);
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
) VALUES (
    'summary-refresh-record', 'summary-refresh-entity', '{}'::jsonb, 'd8',
    '2026-01-01T00:00:00+00'
);
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider_dataset_id, weather_domain,
    forecast_style, metric_key, value_number, target_at, known_at,
    source_entity_key, source_record_key
) VALUES (
    'summary-refresh-value', '00000000-0000-0000-0000-000000000014',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'summary-refresh'),
    'forecast', 'short', 'TMP', 1.0,
    '2026-01-01T03:00:00+00', '2026-01-01T00:00:00+00',
    'summary-refresh-entity', 'summary-refresh-record'
);
INSERT INTO ops.current_summary_runs (
    projection_kind, run_kind, status, started_at, finished_at
) VALUES (
    'weather', 'reconcile', 'succeeded', '2026-01-01T03:00:00+00', '2026-01-01T03:01:00+00'
);
INSERT INTO feature.current_weather_summary (
    feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
    weather_value_key, summary_run_id, selected_at, refresh_after
) VALUES (
    '00000000-0000-0000-0000-000000000014',
    (SELECT provider_dataset_id FROM provider_sync.provider_datasets
     WHERE provider = 'fixture' AND dataset_key = 'summary-refresh'),
    'forecast', 'short', 'TMP', 'summary-refresh-value',
    (SELECT summary_run_id FROM ops.current_summary_runs
     WHERE projection_kind = 'weather' AND status = 'succeeded'),
    '2026-01-01T03:00:00+00', '2026-01-01T03:00:00+00'
);
