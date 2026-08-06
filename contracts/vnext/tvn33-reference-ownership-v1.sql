-- =============================================================================
-- T-VN-33 reference ownership target — target-schema-v1.sql 다음에 적용한다.
-- =============================================================================
-- 이 파일은 provider/dataset 문자열을 storage identity로 소유하던 Wave 2 전수 참조의
-- T-VN-33 도착점이다. weather/price fact 및 typed notice_states는 각각 T-VN-38/T-VN-37
-- 소관이라 여기 만들지 않는다.

CREATE TABLE provider_sync.provider_sync_state (
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_success_at timestamptz,
    next_run_after timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_sync_state PRIMARY KEY (provider_dataset_id, sync_scope),
    CONSTRAINT fk_provider_sync_state_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_provider_sync_state_scope CHECK (
        sync_scope IN ('dataset_wide', 'target_grids')
        OR sync_scope ~ '^external_system:[^[:space:]][^[:space:]]{0,111}$'
    ),
    CONSTRAINT ck_provider_sync_state_status CHECK (
        status IN ('active', 'paused', 'disabled', 'failed')
    ),
    CONSTRAINT ck_provider_sync_state_cursor CHECK (jsonb_typeof(cursor) = 'object')
);
CREATE INDEX idx_provider_sync_state_next_run
    ON provider_sync.provider_sync_state (next_run_after)
    WHERE status = 'active';
CREATE TRIGGER trg_provider_sync_state_active_dataset_write
    BEFORE INSERT OR UPDATE ON provider_sync.provider_sync_state
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE TABLE provider_sync.notice_lifecycle_scopes (
    notice_lifecycle_scope_id bigint GENERATED ALWAYS AS IDENTITY,
    provider_dataset_id bigint NOT NULL,
    source_entity_type text NOT NULL,
    mode text NOT NULL,
    applied_at timestamptz NOT NULL,
    state_fingerprint text NOT NULL,
    CONSTRAINT pk_notice_lifecycle_scopes PRIMARY KEY (notice_lifecycle_scope_id),
    CONSTRAINT uq_notice_lifecycle_scopes_identity UNIQUE (
        provider_dataset_id, source_entity_type
    ),
    CONSTRAINT fk_notice_lifecycle_scopes_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_notice_lifecycle_scopes_mode CHECK (mode IN ('snapshot', 'event'))
);
CREATE TRIGGER trg_notice_lifecycle_scopes_active_dataset_write
    BEFORE INSERT OR UPDATE ON provider_sync.notice_lifecycle_scopes
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.reject_inactive_notice_lifecycle_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM provider_sync.notice_lifecycle_scopes AS scope
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE scope.notice_lifecycle_scope_id = NEW.notice_lifecycle_scope_id
      AND dataset.is_active
    FOR SHARE OF dataset;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive notice lineage writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE provider_sync.notice_lineage_states (
    notice_lifecycle_scope_id bigint NOT NULL,
    lineage_key text NOT NULL,
    present boolean NOT NULL,
    changed_at timestamptz NOT NULL,
    valid_until timestamptz,
    CONSTRAINT pk_notice_lineage_states PRIMARY KEY (notice_lifecycle_scope_id, lineage_key),
    CONSTRAINT fk_notice_lineage_states_scope FOREIGN KEY (notice_lifecycle_scope_id)
        REFERENCES provider_sync.notice_lifecycle_scopes (notice_lifecycle_scope_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_notice_lineage_states_scope_present
    ON provider_sync.notice_lineage_states (notice_lifecycle_scope_id, present, changed_at DESC);
CREATE TRIGGER trg_notice_lineage_states_active_dataset_write
    BEFORE INSERT OR UPDATE ON provider_sync.notice_lineage_states
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_notice_lifecycle_scope();

CREATE TABLE feature.curated_sources (
    source_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    provider_dataset_id bigint NOT NULL,
    source_name text NOT NULL,
    source_kind text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_curated_sources PRIMARY KEY (source_id),
    CONSTRAINT uq_curated_sources_dataset UNIQUE (provider_dataset_id),
    CONSTRAINT fk_curated_sources_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_curated_sources_metadata CHECK (jsonb_typeof(metadata) = 'object')
);
CREATE TRIGGER trg_curated_sources_active_dataset_write
    BEFORE INSERT OR UPDATE ON feature.curated_sources
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.reject_inactive_curated_source_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM feature.curated_sources AS source
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = source.provider_dataset_id
    WHERE source.source_id = NEW.source_id
      AND dataset.is_active
    FOR SHARE OF dataset;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive curation rule writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE feature.curated_source_rules (
    rule_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    theme_id uuid NOT NULL,
    source_id uuid NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    priority integer NOT NULL DEFAULT 0,
    CONSTRAINT pk_curated_source_rules PRIMARY KEY (rule_id),
    CONSTRAINT fk_curated_source_rules_theme FOREIGN KEY (theme_id)
        REFERENCES feature.curated_themes (theme_id) ON DELETE CASCADE,
    CONSTRAINT fk_curated_source_rules_source FOREIGN KEY (source_id)
        REFERENCES feature.curated_sources (source_id) ON DELETE CASCADE
);
CREATE INDEX idx_curated_source_rules_source_enabled
    ON feature.curated_source_rules (source_id, enabled, priority DESC);
CREATE TRIGGER trg_curated_source_rules_active_dataset_write
    BEFORE INSERT OR UPDATE ON feature.curated_source_rules
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_curated_source_dataset();

CREATE TABLE ops.import_jobs (
    job_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    kind text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_import_jobs PRIMARY KEY (job_id),
    CONSTRAINT ck_import_jobs_status_target CHECK (
        status IN ('queued', 'running', 'done', 'failed', 'cancelled')
    )
);

CREATE TABLE ops.import_job_datasets (
    import_job_dataset_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    job_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_import_job_datasets PRIMARY KEY (import_job_dataset_id),
    CONSTRAINT uq_import_job_datasets_identity UNIQUE (job_id, provider_dataset_id, sync_scope),
    CONSTRAINT uq_import_job_datasets_job_member UNIQUE (job_id, import_job_dataset_id),
    CONSTRAINT fk_import_job_datasets_job FOREIGN KEY (job_id)
        REFERENCES ops.import_jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT fk_import_job_datasets_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id)
);
CREATE INDEX idx_import_job_datasets_dataset_job
    ON ops.import_job_datasets (provider_dataset_id, job_id);
CREATE TRIGGER trg_import_job_datasets_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.import_job_datasets
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.reject_inactive_import_job_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.import_job_dataset_id IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM 1
    FROM ops.import_job_datasets AS member
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = member.provider_dataset_id
    WHERE member.import_job_dataset_id = NEW.import_job_dataset_id
      AND dataset.is_active
    FOR SHARE OF dataset;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive import job event writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE ops.import_job_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY,
    job_id uuid NOT NULL,
    import_job_dataset_id uuid,
    event_kind text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_import_job_events PRIMARY KEY (event_id),
    CONSTRAINT fk_import_job_events_job FOREIGN KEY (job_id)
        REFERENCES ops.import_jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT fk_import_job_events_job_member FOREIGN KEY (job_id, import_job_dataset_id)
        REFERENCES ops.import_job_datasets (job_id, import_job_dataset_id) ON DELETE RESTRICT
);
CREATE INDEX idx_import_job_events_member_time
    ON ops.import_job_events (import_job_dataset_id, occurred_at DESC)
    WHERE import_job_dataset_id IS NOT NULL;
CREATE TRIGGER trg_import_job_events_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.import_job_events
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_import_job_dataset();

CREATE TABLE ops.feature_update_requests (
    request_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    status text NOT NULL DEFAULT 'queued',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_feature_update_requests PRIMARY KEY (request_id),
    CONSTRAINT ck_feature_update_requests_status_target CHECK (
        status IN ('queued', 'running', 'done', 'failed', 'cancelled')
    )
);

CREATE TABLE ops.feature_update_request_datasets (
    feature_update_request_dataset_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    request_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    CONSTRAINT pk_feature_update_request_datasets PRIMARY KEY (feature_update_request_dataset_id),
    CONSTRAINT uq_feature_update_request_datasets_identity UNIQUE (
        request_id, provider_dataset_id, sync_scope
    ),
    CONSTRAINT fk_feature_update_request_datasets_request FOREIGN KEY (request_id)
        REFERENCES ops.feature_update_requests (request_id) ON DELETE CASCADE,
    CONSTRAINT fk_feature_update_request_datasets_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id)
);
CREATE INDEX idx_feature_update_request_datasets_dataset_request
    ON ops.feature_update_request_datasets (provider_dataset_id, request_id);
CREATE TRIGGER trg_feature_update_request_datasets_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.feature_update_request_datasets
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE TABLE ops.provider_refresh_policies (
    provider_dataset_id bigint NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    min_interval_seconds integer,
    max_concurrent integer NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_refresh_policies PRIMARY KEY (provider_dataset_id),
    CONSTRAINT fk_provider_refresh_policies_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_provider_refresh_policy_interval CHECK (
        min_interval_seconds IS NULL OR min_interval_seconds > 0
    ),
    CONSTRAINT ck_provider_refresh_policy_concurrent CHECK (max_concurrent > 0)
);
CREATE TRIGGER trg_provider_refresh_policies_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.provider_refresh_policies
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE TABLE ops.offline_uploads (
    upload_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    checksum_sha256 text NOT NULL,
    status text NOT NULL DEFAULT 'registered',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_offline_uploads PRIMARY KEY (upload_id),
    CONSTRAINT uq_offline_uploads_dataset_scope_checksum UNIQUE (
        provider_dataset_id, sync_scope, checksum_sha256
    ),
    CONSTRAINT fk_offline_uploads_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_offline_uploads_checksum CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX idx_offline_uploads_dataset_created
    ON ops.offline_uploads (provider_dataset_id, created_at DESC);
CREATE TRIGGER trg_offline_uploads_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.offline_uploads
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE TABLE ops.integrity_observation_scopes (
    integrity_observation_scope_id bigint GENERATED ALWAYS AS IDENTITY,
    provider_dataset_id bigint NOT NULL,
    latest_generation bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_integrity_observation_scopes PRIMARY KEY (integrity_observation_scope_id),
    CONSTRAINT uq_integrity_observation_scopes_dataset UNIQUE (provider_dataset_id),
    CONSTRAINT fk_integrity_observation_scopes_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_integrity_observation_scopes_generation CHECK (latest_generation >= 0)
);
CREATE TRIGGER trg_integrity_observation_scopes_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.integrity_observation_scopes
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.reject_inactive_integrity_observation_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM ops.integrity_observation_scopes AS scope
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE scope.integrity_observation_scope_id = NEW.integrity_observation_scope_id
      AND dataset.is_active
    FOR SHARE OF dataset;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive integrity writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE ops.integrity_observation_runs (
    integrity_observation_run_id bigint GENERATED ALWAYS AS IDENTITY,
    integrity_observation_scope_id bigint NOT NULL,
    generation bigint NOT NULL,
    external_run_id text NOT NULL,
    status text NOT NULL DEFAULT 'collecting',
    CONSTRAINT pk_integrity_observation_runs PRIMARY KEY (integrity_observation_run_id),
    CONSTRAINT uq_integrity_observation_runs_generation UNIQUE (
        integrity_observation_scope_id, generation
    ),
    CONSTRAINT fk_integrity_observation_runs_scope FOREIGN KEY (integrity_observation_scope_id)
        REFERENCES ops.integrity_observation_scopes (integrity_observation_scope_id)
        ON DELETE CASCADE
);
CREATE TRIGGER trg_integrity_observation_runs_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.integrity_observation_runs
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_integrity_observation_scope();

CREATE TABLE ops.data_integrity_violations (
    issue_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    provider_dataset_id bigint,
    source_record_key text,
    violation_type text NOT NULL,
    status text NOT NULL DEFAULT 'open',
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_data_integrity_violations PRIMARY KEY (issue_id),
    CONSTRAINT fk_data_integrity_violations_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT fk_data_integrity_violations_source_record FOREIGN KEY (source_record_key)
        REFERENCES provider_sync.source_records (source_record_key) ON DELETE SET NULL,
    CONSTRAINT ck_data_integrity_violations_status CHECK (
        status IN ('open', 'acknowledged', 'resolved', 'ignored')
    )
);
CREATE INDEX idx_data_integrity_violations_dataset_status
    ON ops.data_integrity_violations (provider_dataset_id, status, last_seen_at DESC)
    WHERE provider_dataset_id IS NOT NULL;
CREATE TRIGGER trg_data_integrity_violations_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.data_integrity_violations
    FOR EACH ROW WHEN (NEW.provider_dataset_id IS NOT NULL)
    EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.validate_data_integrity_violation_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.provider_dataset_id IS NOT NULL AND NEW.source_record_key IS NOT NULL THEN
        PERFORM 1
        FROM provider_sync.source_records AS record
        JOIN provider_sync.source_entities AS entity
          ON entity.source_entity_key = record.source_entity_key
        WHERE record.source_record_key = NEW.source_record_key
          AND entity.provider_dataset_id = NEW.provider_dataset_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'integrity violation dataset must match source record dataset'
                USING ERRCODE = '23514',
                    CONSTRAINT = 'ck_data_integrity_violations_dataset_source_record';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_data_integrity_violations_dataset_source_record
    BEFORE INSERT OR UPDATE ON ops.data_integrity_violations
    FOR EACH ROW EXECUTE FUNCTION provider_sync.validate_data_integrity_violation_dataset();

CREATE TABLE ops.poi_cache_targets (
    target_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    external_system text NOT NULL,
    target_key text NOT NULL,
    CONSTRAINT pk_poi_cache_targets PRIMARY KEY (target_id),
    CONSTRAINT uq_poi_cache_targets_identity UNIQUE (external_system, target_key)
);
CREATE TABLE ops.poi_cache_target_feature_links (
    target_id uuid NOT NULL,
    feature_id uuid NOT NULL,
    provider_dataset_id bigint,
    active boolean NOT NULL DEFAULT true,
    CONSTRAINT pk_poi_cache_target_feature_links PRIMARY KEY (target_id, feature_id),
    CONSTRAINT fk_poi_cache_target_feature_links_target FOREIGN KEY (target_id)
        REFERENCES ops.poi_cache_targets (target_id) ON DELETE CASCADE,
    CONSTRAINT fk_poi_cache_target_feature_links_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_poi_cache_target_feature_links_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id)
);
CREATE INDEX idx_poi_cache_target_feature_links_dataset
    ON ops.poi_cache_target_feature_links (provider_dataset_id)
    WHERE active AND provider_dataset_id IS NOT NULL;
CREATE TRIGGER trg_poi_cache_target_feature_links_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.poi_cache_target_feature_links
    FOR EACH ROW WHEN (NEW.provider_dataset_id IS NOT NULL)
    EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE TABLE ops.enrichment_review_queue (
    review_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    target_feature_id uuid NOT NULL,
    source_entity_key text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    CONSTRAINT pk_enrichment_review_queue PRIMARY KEY (review_id),
    CONSTRAINT uq_enrichment_review_queue_identity UNIQUE (
        target_feature_id, source_entity_key
    ),
    CONSTRAINT fk_enrichment_review_queue_feature FOREIGN KEY (target_feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_enrichment_review_queue_source_entity FOREIGN KEY (source_entity_key)
        REFERENCES provider_sync.source_entities (source_entity_key) ON DELETE RESTRICT
);
CREATE TRIGGER trg_enrichment_review_queue_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.enrichment_review_queue
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();

CREATE TABLE ops.managed_files (
    file_id bigint GENERATED ALWAYS AS IDENTITY,
    provider_dataset_id bigint,
    provider_name text,
    storage_backend text NOT NULL,
    location text NOT NULL,
    path text NOT NULL,
    checksum_sha256 text,
    CONSTRAINT pk_managed_files PRIMARY KEY (file_id),
    CONSTRAINT uq_managed_files_location_path UNIQUE (storage_backend, location, path),
    CONSTRAINT fk_managed_files_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_managed_files_owner CHECK (
        (provider_dataset_id IS NOT NULL AND provider_name IS NULL)
        OR (provider_dataset_id IS NULL AND provider_name IS NOT NULL)
        OR (provider_dataset_id IS NULL AND provider_name IS NULL)
    )
);
CREATE TRIGGER trg_managed_files_active_dataset_write
    BEFORE INSERT OR UPDATE ON ops.managed_files
    FOR EACH ROW WHEN (NEW.provider_dataset_id IS NOT NULL)
    EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
