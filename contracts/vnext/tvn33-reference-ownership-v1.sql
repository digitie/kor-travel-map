-- =============================================================================
-- T-VN-33 reference ownership target — target-schema-v1.sql 다음에 적용한다.
-- =============================================================================
-- 이 파일은 provider/dataset 문자열을 storage identity로 소유하던 Wave 2 전수 참조의
-- T-VN-33 도착점이다. weather/price fact 및 typed notice_states는 각각 T-VN-38/T-VN-37
-- 소관이라 여기 만들지 않는다.

-- 실행 scope는 operation의 정규 child다. capability JSON은 산출 metadata만 소유하므로
-- scope/enable과 역방향으로 모순될 수 없다.
CREATE TABLE provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    operation_key text NOT NULL,
    operation_kind text NOT NULL DEFAULT 'refresh',
    CONSTRAINT pk_provider_dataset_operation_scopes PRIMARY KEY (
        provider_dataset_id, sync_scope, operation_key
    ),
    CONSTRAINT fk_provider_dataset_operation_scopes_operation FOREIGN KEY (
        provider_dataset_id, operation_key, operation_kind
    ) REFERENCES provider_sync.provider_dataset_operations (
        provider_dataset_id, operation_key, operation_kind
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_provider_dataset_operation_scopes_refresh_only CHECK (
        operation_kind = 'refresh'
    ),
    CONSTRAINT ck_provider_dataset_operation_scopes_syntax CHECK (
        provider_sync.is_valid_provider_dataset_sync_scope(sync_scope)
    )
);
CREATE INDEX idx_provider_dataset_operation_scopes_operation
    ON provider_sync.provider_dataset_operation_scopes (provider_dataset_id, operation_key);
CREATE TRIGGER trg_provider_dataset_operation_scopes_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.provider_dataset_operation_scopes
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.assert_active_provider_dataset_scope(
    dataset_id bigint,
    scope_value text
)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM provider_sync.provider_dataset_operation_scopes AS scope
    JOIN provider_sync.provider_dataset_operations AS operation
      ON operation.provider_dataset_id = scope.provider_dataset_id
     AND operation.operation_key = scope.operation_key
     AND operation.operation_kind = scope.operation_kind
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE scope.provider_dataset_id = dataset_id
      AND scope.sync_scope = scope_value
      AND operation.is_enabled
      AND dataset.is_active
    FOR SHARE OF dataset, operation;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'dataset scope is absent or disabled for normal writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_scope_active_write';
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_provider_dataset_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND (OLD.provider_dataset_id, OLD.sync_scope)
           IS DISTINCT FROM (NEW.provider_dataset_id, NEW.sync_scope)
    THEN
        RAISE EXCEPTION 'provider dataset scope ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_scope_ownership_immutable';
    END IF;
    IF TG_OP <> 'INSERT' THEN
        PERFORM provider_sync.assert_active_provider_dataset_scope(
            OLD.provider_dataset_id, OLD.sync_scope
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_active_provider_dataset_scope(
            NEW.provider_dataset_id, NEW.sync_scope
        );
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE provider_sync.provider_sync_state (
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    operation_key text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_success_at timestamptz,
    next_run_after timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_sync_state PRIMARY KEY (
        provider_dataset_id, sync_scope, operation_key
    ),
    CONSTRAINT fk_provider_sync_state_exact_operation_scope FOREIGN KEY (
        provider_dataset_id, sync_scope, operation_key
    ) REFERENCES provider_sync.provider_dataset_operation_scopes (
        provider_dataset_id, sync_scope, operation_key
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
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.provider_sync_state
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset_scope();

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
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.notice_lifecycle_scopes
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.assert_active_notice_lifecycle_scope(scope_id bigint)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM provider_sync.notice_lifecycle_scopes AS scope
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE scope.notice_lifecycle_scope_id = scope_id
      AND dataset.is_active
    FOR SHARE OF dataset;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive notice lineage writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_notice_lifecycle_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.notice_lifecycle_scope_id IS DISTINCT FROM NEW.notice_lifecycle_scope_id
    THEN
        RAISE EXCEPTION 'notice lineage ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_notice_lineage_ownership_immutable';
    END IF;
    -- The scope row has already been removed when this DELETE comes from the
    -- declared FK action.  A standalone child DELETE cannot observe that
    -- state: its non-deferrable FK requires the parent to exist.  Therefore a
    -- missing parent is precisely the active parent cascade path; checking it
    -- through the normal indirect lookup would misclassify it as inactive.
    IF TG_OP = 'DELETE'
       AND NOT EXISTS (
           SELECT 1
           FROM provider_sync.notice_lifecycle_scopes
           WHERE notice_lifecycle_scope_id = OLD.notice_lifecycle_scope_id
       )
    THEN
        RETURN OLD;
    END IF;
    IF TG_OP <> 'INSERT' THEN
        PERFORM provider_sync.assert_active_notice_lifecycle_scope(
            OLD.notice_lifecycle_scope_id
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_active_notice_lifecycle_scope(
            NEW.notice_lifecycle_scope_id
        );
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
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
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.notice_lineage_states
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
    BEFORE INSERT OR UPDATE OR DELETE ON feature.curated_sources
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.assert_active_curated_source_dataset(source_uuid uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM feature.curated_sources AS source
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = source.provider_dataset_id
    WHERE source.source_id = source_uuid
      AND dataset.is_active
    FOR SHARE OF dataset;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive curation rule writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_curated_source_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.source_id IS DISTINCT FROM NEW.source_id THEN
        RAISE EXCEPTION 'curated source ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_curated_source_rule_ownership_immutable';
    END IF;
    -- `source_id` has a non-deferrable ON DELETE CASCADE FK.  Once the source
    -- row disappeared, this is the FK cascade, not a standalone child write.
    IF TG_OP = 'DELETE'
       AND NOT EXISTS (
           SELECT 1 FROM feature.curated_sources WHERE source_id = OLD.source_id
       )
    THEN
        RETURN OLD;
    END IF;
    IF TG_OP <> 'INSERT' THEN
        PERFORM provider_sync.assert_active_curated_source_dataset(OLD.source_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_active_curated_source_dataset(NEW.source_id);
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
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
    BEFORE INSERT OR UPDATE OR DELETE ON feature.curated_source_rules
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_curated_source_dataset();

CREATE TABLE ops.import_jobs (
    job_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    kind text NOT NULL,
    dataset_membership_mode text NOT NULL DEFAULT 'root',
    status text NOT NULL DEFAULT 'queued',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_import_jobs PRIMARY KEY (job_id),
    CONSTRAINT ck_import_jobs_membership_mode CHECK (
        dataset_membership_mode IN ('root', 'single', 'multiple')
    ),
    CONSTRAINT ck_import_jobs_status_target CHECK (
        status IN ('queued', 'running', 'done', 'failed', 'cancelled')
    )
);

CREATE TABLE ops.import_job_datasets (
    import_job_dataset_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    job_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    operation_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_import_job_datasets PRIMARY KEY (import_job_dataset_id),
    CONSTRAINT uq_import_job_datasets_identity UNIQUE (
        job_id, provider_dataset_id, sync_scope, operation_key
    ),
    CONSTRAINT uq_import_job_datasets_job_member UNIQUE (job_id, import_job_dataset_id),
    CONSTRAINT fk_import_job_datasets_job FOREIGN KEY (job_id)
        REFERENCES ops.import_jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT fk_import_job_datasets_exact_operation_scope FOREIGN KEY (
        provider_dataset_id, sync_scope, operation_key
    ) REFERENCES provider_sync.provider_dataset_operation_scopes (
        provider_dataset_id, sync_scope, operation_key
    )
);
CREATE INDEX idx_import_job_datasets_dataset_job
    ON ops.import_job_datasets (provider_dataset_id, job_id);
CREATE TRIGGER trg_import_job_datasets_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_datasets
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset_scope();

CREATE FUNCTION provider_sync.assert_import_job_members_active(target_job_id uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM ops.import_job_datasets AS member
    JOIN provider_sync.provider_dataset_operation_scopes AS scope
      ON scope.provider_dataset_id = member.provider_dataset_id
     AND scope.sync_scope = member.sync_scope
     AND scope.operation_key = member.operation_key
    JOIN provider_sync.provider_dataset_operations AS operation
      ON operation.provider_dataset_id = scope.provider_dataset_id
     AND operation.operation_key = scope.operation_key
     AND operation.operation_kind = scope.operation_kind
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE member.job_id = target_job_id
    FOR SHARE OF dataset, operation;
    IF EXISTS (
        SELECT 1
        FROM ops.import_job_datasets AS member
        JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = member.provider_dataset_id
         AND scope.sync_scope = member.sync_scope
         AND scope.operation_key = member.operation_key
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = scope.provider_dataset_id
         AND operation.operation_key = scope.operation_key
         AND operation.operation_kind = scope.operation_kind
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = scope.provider_dataset_id
        WHERE member.job_id = target_job_id
          AND (NOT dataset.is_active OR NOT operation.is_enabled)
    ) THEN
        RAISE EXCEPTION 'inactive dataset member cannot receive import job writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_import_job_members()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM provider_sync.assert_import_job_members_active(OLD.job_id);
    RETURN OLD;
END;
$$;

CREATE FUNCTION provider_sync.assert_import_job_membership_complete()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    target_job_id uuid := COALESCE(NEW.job_id, OLD.job_id);
    mode_value text;
    member_count bigint;
BEGIN
    SELECT dataset_membership_mode INTO mode_value
    FROM ops.import_jobs WHERE job_id = target_job_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO member_count
    FROM ops.import_job_datasets WHERE job_id = target_job_id;
    IF (mode_value = 'root' AND member_count <> 0)
       OR (mode_value = 'single' AND member_count <> 1)
       OR (mode_value = 'multiple' AND member_count = 0)
    THEN
        RAISE EXCEPTION 'import job membership cardinality does not match mode'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_import_job_membership_complete';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_import_jobs_membership_complete
    AFTER INSERT OR UPDATE OF dataset_membership_mode OR DELETE ON ops.import_jobs
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_import_job_membership_complete();
CREATE CONSTRAINT TRIGGER trg_import_job_datasets_membership_complete
    AFTER INSERT OR UPDATE OR DELETE ON ops.import_job_datasets
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_import_job_membership_complete();
CREATE TRIGGER trg_import_jobs_active_member_write
    BEFORE UPDATE OR DELETE ON ops.import_jobs
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_import_job_members();

CREATE FUNCTION provider_sync.assert_import_job_event_member(
    target_job_id uuid,
    target_member_id uuid
)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    mode_value text;
BEGIN
    SELECT dataset_membership_mode INTO mode_value
    FROM ops.import_jobs WHERE job_id = target_job_id;
    IF target_member_id IS NULL THEN
        IF mode_value <> 'root' THEN
            RAISE EXCEPTION 'dataset job event requires a dataset member'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_import_job_event_member_required';
        END IF;
        RETURN;
    END IF;
    IF mode_value = 'root' THEN
        RAISE EXCEPTION 'root import job event cannot carry a dataset member'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_import_job_event_member_root';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ops.import_job_datasets
        WHERE job_id = target_job_id AND import_job_dataset_id = target_member_id
    ) THEN
        PERFORM provider_sync.assert_import_job_members_active(target_job_id);
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_import_job_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND (OLD.job_id, OLD.import_job_dataset_id)
           IS DISTINCT FROM (NEW.job_id, NEW.import_job_dataset_id)
    THEN
        RAISE EXCEPTION 'import job event ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_import_job_event_ownership_immutable';
    END IF;
    IF TG_OP <> 'INSERT' THEN
        PERFORM provider_sync.assert_import_job_event_member(
            OLD.job_id, OLD.import_job_dataset_id
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_import_job_event_member(
            NEW.job_id, NEW.import_job_dataset_id
        );
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
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
    BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_events
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_import_job_dataset();

CREATE TABLE ops.feature_update_requests (
    request_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    dataset_membership_mode text NOT NULL DEFAULT 'single',
    status text NOT NULL DEFAULT 'queued',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_feature_update_requests PRIMARY KEY (request_id),
    CONSTRAINT ck_feature_update_requests_membership_mode CHECK (
        dataset_membership_mode IN ('single', 'multiple')
    ),
    CONSTRAINT ck_feature_update_requests_status_target CHECK (
        status IN ('queued', 'running', 'done', 'failed', 'cancelled')
    )
);

CREATE TABLE ops.feature_update_request_datasets (
    feature_update_request_dataset_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    request_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    operation_key text NOT NULL,
    CONSTRAINT pk_feature_update_request_datasets PRIMARY KEY (feature_update_request_dataset_id),
    CONSTRAINT uq_feature_update_request_datasets_identity UNIQUE (
        request_id, provider_dataset_id, sync_scope, operation_key
    ),
    CONSTRAINT fk_feature_update_request_datasets_request FOREIGN KEY (request_id)
        REFERENCES ops.feature_update_requests (request_id) ON DELETE CASCADE,
    CONSTRAINT fk_feature_update_request_datasets_exact_operation_scope FOREIGN KEY (
        provider_dataset_id, sync_scope, operation_key
    ) REFERENCES provider_sync.provider_dataset_operation_scopes (
        provider_dataset_id, sync_scope, operation_key
    )
);
CREATE INDEX idx_feature_update_request_datasets_dataset_request
    ON ops.feature_update_request_datasets (provider_dataset_id, request_id);
CREATE TRIGGER trg_feature_update_request_datasets_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON ops.feature_update_request_datasets
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset_scope();

CREATE FUNCTION provider_sync.assert_feature_update_request_members_active(target_request_id uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM ops.feature_update_request_datasets AS member
    JOIN provider_sync.provider_dataset_operation_scopes AS scope
      ON scope.provider_dataset_id = member.provider_dataset_id
     AND scope.sync_scope = member.sync_scope
     AND scope.operation_key = member.operation_key
    JOIN provider_sync.provider_dataset_operations AS operation
      ON operation.provider_dataset_id = scope.provider_dataset_id
     AND operation.operation_key = scope.operation_key
     AND operation.operation_kind = scope.operation_kind
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE member.request_id = target_request_id
    FOR SHARE OF dataset, operation;
    IF EXISTS (
        SELECT 1
        FROM ops.feature_update_request_datasets AS member
        JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = member.provider_dataset_id
         AND scope.sync_scope = member.sync_scope
         AND scope.operation_key = member.operation_key
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = scope.provider_dataset_id
         AND operation.operation_key = scope.operation_key
         AND operation.operation_kind = scope.operation_kind
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = scope.provider_dataset_id
        WHERE member.request_id = target_request_id
          AND (NOT dataset.is_active OR NOT operation.is_enabled)
    ) THEN
        RAISE EXCEPTION 'inactive dataset member cannot receive update request writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_feature_update_request_members()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM provider_sync.assert_feature_update_request_members_active(OLD.request_id);
    RETURN OLD;
END;
$$;

CREATE FUNCTION provider_sync.assert_feature_update_request_membership_complete()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    target_request_id uuid := COALESCE(NEW.request_id, OLD.request_id);
    mode_value text;
    member_count bigint;
BEGIN
    SELECT dataset_membership_mode INTO mode_value
    FROM ops.feature_update_requests WHERE request_id = target_request_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO member_count
    FROM ops.feature_update_request_datasets WHERE request_id = target_request_id;
    IF (mode_value = 'single' AND member_count <> 1)
       OR (mode_value = 'multiple' AND member_count = 0)
    THEN
        RAISE EXCEPTION 'feature update request membership cardinality does not match mode'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_update_request_membership_complete';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_feature_update_requests_membership_complete
    AFTER INSERT OR UPDATE OF dataset_membership_mode OR DELETE ON ops.feature_update_requests
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_feature_update_request_membership_complete();
CREATE CONSTRAINT TRIGGER trg_feature_update_request_datasets_membership_complete
    AFTER INSERT OR UPDATE OR DELETE ON ops.feature_update_request_datasets
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_feature_update_request_membership_complete();
CREATE TRIGGER trg_feature_update_requests_active_member_write
    BEFORE UPDATE OR DELETE ON ops.feature_update_requests
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_feature_update_request_members();

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
    BEFORE INSERT OR UPDATE OR DELETE ON ops.provider_refresh_policies
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE TABLE ops.offline_uploads (
    upload_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    provider_dataset_id bigint NOT NULL,
    sync_scope text NOT NULL,
    operation_key text NOT NULL,
    checksum_sha256 text NOT NULL,
    status text NOT NULL DEFAULT 'registered',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_offline_uploads PRIMARY KEY (upload_id),
    -- 멱등 키는 operation을 포함하지 않는다: 같은 (dataset, scope)에 같은 파일은
    -- 한 번만 올린다. 반면 FK는 scope PK와 같은 triple이어야 한다.
    CONSTRAINT uq_offline_uploads_dataset_scope_checksum UNIQUE (
        provider_dataset_id, sync_scope, checksum_sha256
    ),
    CONSTRAINT fk_offline_uploads_exact_operation_scope FOREIGN KEY (
        provider_dataset_id, sync_scope, operation_key
    ) REFERENCES provider_sync.provider_dataset_operation_scopes (
        provider_dataset_id, sync_scope, operation_key
    ),
    CONSTRAINT ck_offline_uploads_checksum CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX idx_offline_uploads_dataset_created
    ON ops.offline_uploads (provider_dataset_id, created_at DESC);
CREATE TRIGGER trg_offline_uploads_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON ops.offline_uploads
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset_scope();

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
    BEFORE INSERT OR UPDATE OR DELETE ON ops.integrity_observation_scopes
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.assert_active_integrity_observation_scope(scope_id bigint)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM ops.integrity_observation_scopes AS scope
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE scope.integrity_observation_scope_id = scope_id
      AND dataset.is_active
    FOR SHARE OF dataset;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive integrity writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_integrity_observation_scope()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.integrity_observation_scope_id
           IS DISTINCT FROM NEW.integrity_observation_scope_id
    THEN
        RAISE EXCEPTION 'integrity observation ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_integrity_observation_ownership_immutable';
    END IF;
    -- See the notice lineage equivalent: the non-deferrable ON DELETE CASCADE
    -- FK makes an absent parent an unambiguous referential-action DELETE.
    IF TG_OP = 'DELETE'
       AND NOT EXISTS (
           SELECT 1
           FROM ops.integrity_observation_scopes
           WHERE integrity_observation_scope_id = OLD.integrity_observation_scope_id
       )
    THEN
        RETURN OLD;
    END IF;
    IF TG_OP <> 'INSERT' THEN
        PERFORM provider_sync.assert_active_integrity_observation_scope(
            OLD.integrity_observation_scope_id
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_active_integrity_observation_scope(
            NEW.integrity_observation_scope_id
        );
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
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
    BEFORE INSERT OR UPDATE OR DELETE ON ops.integrity_observation_runs
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
CREATE FUNCTION provider_sync.assert_active_source_record_dataset(record_key text)
RETURNS bigint
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    resolved_dataset_id bigint;
BEGIN
    IF record_key IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT entity.provider_dataset_id INTO resolved_dataset_id
    FROM provider_sync.source_records AS record
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = record.source_entity_key
    WHERE record.source_record_key = record_key;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    PERFORM provider_sync.assert_active_provider_dataset(resolved_dataset_id);
    RETURN resolved_dataset_id;
END;
$$;

CREATE FUNCTION provider_sync.validate_data_integrity_violation_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    new_record_dataset_id bigint;
    old_record_dataset_id bigint;
BEGIN
    IF TG_OP = 'UPDATE'
       AND (OLD.provider_dataset_id, OLD.source_record_key)
           IS DISTINCT FROM (NEW.provider_dataset_id, NEW.source_record_key)
    THEN
        RAISE EXCEPTION 'integrity violation ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_data_integrity_violation_ownership_immutable';
    END IF;
    IF TG_OP <> 'INSERT' THEN
        PERFORM provider_sync.assert_active_provider_dataset(OLD.provider_dataset_id);
        old_record_dataset_id := provider_sync.assert_active_source_record_dataset(
            OLD.source_record_key
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_active_provider_dataset(NEW.provider_dataset_id);
        new_record_dataset_id := provider_sync.assert_active_source_record_dataset(
            NEW.source_record_key
        );
        IF NEW.provider_dataset_id IS NOT NULL
           AND new_record_dataset_id IS NOT NULL
           AND NEW.provider_dataset_id <> new_record_dataset_id
        THEN
            RAISE EXCEPTION 'integrity violation dataset must match source record dataset'
                USING ERRCODE = '23514',
                    CONSTRAINT = 'ck_data_integrity_violations_dataset_source_record';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_data_integrity_violations_dataset_source_record
    BEFORE INSERT OR UPDATE OR DELETE ON ops.data_integrity_violations
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
    BEFORE INSERT OR UPDATE OR DELETE ON ops.poi_cache_target_feature_links
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

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
    BEFORE INSERT OR UPDATE OR DELETE ON ops.enrichment_review_queue
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
    BEFORE INSERT OR UPDATE OR DELETE ON ops.managed_files
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
