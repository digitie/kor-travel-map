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

-- dataset 활성 가드의 DELETE 면제 — alembic 0092가 같은 본문으로 재정의한다.
-- target-schema-v1.sql 판은 `IF TG_OP <> 'INSERT'`로 UPDATE와 DELETE 양쪽에서 OLD쪽
-- 활성 검사를 돌았다. 그래서 dataset을 비활성화하면 이 가드가 붙은 테이블들의 행을
-- **지울 수도** 없었고, 위 scope 행이 그 대표다(FK ON DELETE RESTRICT 사슬의 위쪽).
-- DELETE는 새 실행을 거는 write가 아니라 정리이므로 OLD쪽 검사를 건너뛴다. UPDATE의
-- OLD쪽 검사는 그대로다 — violation-fixtures-v1.sql의
-- `inactive_dataset_existing_operation_update`가 그 거부를 못박고 있다.
CREATE OR REPLACE FUNCTION provider_sync.reject_inactive_provider_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id
    THEN
        RAISE EXCEPTION 'provider dataset ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_ownership_immutable';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        PERFORM provider_sync.assert_active_provider_dataset(OLD.provider_dataset_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_active_provider_dataset(NEW.provider_dataset_id);
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- 실행 membership 4테이블(provider_sync_state / import_job_datasets /
-- feature_update_request_datasets / offline_uploads)의 활성 가드.
--
-- 이 자리에는 원래 pair 시절 guard 한 쌍
-- (`assert_active_provider_dataset_scope(bigint,text)` /
--  `reject_inactive_provider_dataset_scope()`)이 있었고 4테이블이 그것을 공유했다.
-- 그 술어는 행의 `operation_key`를 보지 않아서, 같은 (dataset, scope)에 형제
-- operation이 있으면 **하나라도 enabled면** disabled operation에 결박된 행이
-- 통과했다. T-VN-33이 identity를 triple로 올린 이상 가드도 triple이어야 하므로
-- alembic 0091이 테이블마다 자기 축을 보는 가드로 분리했다(0092가 offline upload
-- 정리 write 예외를 덧붙였다). 계약은 그 head 정의를 그대로 옮긴다 —
-- `test_frozen_contract_matches_alembic_head`가 두 정의를 기계 대조한다.

CREATE FUNCTION provider_sync.reject_inactive_sync_state_operation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE target_dataset_id bigint :=
    COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
    target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
    target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM provider_sync.provider_dataset_operation_scopes AS scope
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = scope.provider_dataset_id
         AND operation.operation_key = scope.operation_key
         AND operation.operation_kind = scope.operation_kind
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = scope.provider_dataset_id
        WHERE scope.provider_dataset_id = target_dataset_id
          AND scope.sync_scope = target_scope
          AND scope.operation_key = target_operation_key
          AND scope.operation_kind = 'refresh'
          AND dataset.is_active
          AND operation.is_enabled
    ) THEN
        RAISE EXCEPTION 'inactive refresh operation cannot receive sync state writes'
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_import_job_dataset_membership()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE target_dataset_id bigint :=
    COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
    target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
    target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM provider_sync.provider_dataset_operation_scopes AS scope
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = scope.provider_dataset_id
         AND operation.operation_key = scope.operation_key
         AND operation.operation_kind = scope.operation_kind
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = scope.provider_dataset_id
        WHERE scope.provider_dataset_id = target_dataset_id
          AND scope.sync_scope = target_scope
          AND scope.operation_key = target_operation_key
          AND dataset.is_active
          AND operation.is_enabled
    ) THEN
        RAISE EXCEPTION 'inactive dataset member cannot receive import job writes'
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_feature_update_request_dataset_membership()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE target_dataset_id bigint :=
    COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
    target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
    target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM provider_sync.provider_dataset_operation_scopes AS scope
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = scope.provider_dataset_id
         AND operation.operation_key = scope.operation_key
         AND operation.operation_kind = scope.operation_kind
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = scope.provider_dataset_id
        WHERE scope.provider_dataset_id = target_dataset_id
          AND scope.sync_scope = target_scope
          AND scope.operation_key = target_operation_key
          AND dataset.is_active
          AND operation.is_enabled
    ) THEN
        RAISE EXCEPTION 'inactive dataset member cannot receive update request writes'
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_offline_upload_membership()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE target_dataset_id bigint :=
    COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
    target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
    target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
    requires_active boolean;
BEGIN
    -- 소유권 비교는 triple이다 — operation_key만 갈아끼워 어느 실행에 결박됐는지를
    -- 바꾸는 write는 정리 경로에서도 허용하지 않는다.
    IF TG_OP = 'UPDATE'
       AND (OLD.provider_dataset_id, OLD.sync_scope, OLD.operation_key)
           IS DISTINCT FROM
           (NEW.provider_dataset_id, NEW.sync_scope, NEW.operation_key) THEN
        RAISE EXCEPTION 'offline upload membership ownership is immutable'
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_provider_dataset_scope_ownership_immutable';
    END IF;
    -- 활성 검사는 새 작업을 여는 write에만 건다 — 정리(DELETE·종료 상태로의 UPDATE)는
    -- 비활성 membership에서도 빠져나갈 수 있어야 한다(alembic 0092).
    IF TG_OP = 'INSERT' THEN
        requires_active := true;
    ELSIF TG_OP = 'UPDATE' THEN
        requires_active := NEW.status IN ('validating', 'loading');
    ELSE
        requires_active := false;
    END IF;
    IF requires_active AND NOT EXISTS (
        SELECT 1
        FROM provider_sync.provider_dataset_operation_scopes AS scope
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = scope.provider_dataset_id
         AND operation.operation_key = scope.operation_key
         AND operation.operation_kind = scope.operation_kind
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = scope.provider_dataset_id
        WHERE scope.provider_dataset_id = target_dataset_id
          AND scope.sync_scope = target_scope
          AND scope.operation_key = target_operation_key
          AND dataset.is_active
          AND operation.is_enabled
    ) THEN
        RAISE EXCEPTION 'dataset scope is absent or disabled for normal writes'
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_provider_dataset_scope_active_write';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
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
    ) ON DELETE RESTRICT,
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
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_sync_state_operation();

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
-- 이 두 index는 alembic 0025가 만든 것을 그대로 옮긴 것이다. T-VN-33은 curated rule의
-- 접근 경로를 바꾸지 않으므로 여기서 열 순서를 다시 정하지 않는다 — 앞 판이 선언하던
-- `idx_curated_source_rules_source_enabled (source_id, enabled, priority DESC)`는
-- migration에도 `infra/models.py`에도 없는 이름이었고, index 대조 축을 켜자
-- only-in-contract로 드러났다.
CREATE INDEX idx_curated_source_rules_enabled
    ON feature.curated_source_rules (enabled, source_id, priority DESC);
CREATE INDEX idx_curated_source_rules_theme
    ON feature.curated_source_rules (theme_id, enabled, priority DESC);
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
    ) ON DELETE RESTRICT
);
-- membership 조회의 선두 열은 identity triple이다. alembic 0090이 이 이름·이 열
-- 집합으로 만든다. 앞 판은 `idx_import_job_datasets_dataset_job
-- (provider_dataset_id, job_id)`라는 pair 시절 모양을 들고 있었다 — scope PK가
-- triple로 올라간 뒤에도 index만 pair에 남아 있던 자리다.
CREATE INDEX idx_import_job_datasets_exact_operation_job
    ON ops.import_job_datasets (provider_dataset_id, sync_scope, operation_key, job_id);
CREATE TRIGGER trg_import_job_datasets_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_datasets
    FOR EACH ROW EXECUTE FUNCTION
        provider_sync.reject_inactive_import_job_dataset_membership();

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
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
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
    -- `level`·`quarantined_at`은 아래 index를 여기서 선언하기 위해 있다. 이 파일은
    -- events 테이블의 전체 열 형태를 선언하지 않는다 — 대조 축에 columns가 없는
    -- 이유는 `test_frozen_contract_matches_alembic_head` docstring에 있다.
    level text,
    quarantined_at timestamptz,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_import_job_events PRIMARY KEY (event_id),
    CONSTRAINT fk_import_job_events_job FOREIGN KEY (job_id)
        REFERENCES ops.import_jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT fk_import_job_events_job_member FOREIGN KEY (job_id, import_job_dataset_id)
        REFERENCES ops.import_job_datasets (job_id, import_job_dataset_id) ON DELETE RESTRICT
);
-- alembic 0090이 만드는 정의 그대로다. keyset tiebreak(`event_id DESC`)·covering
-- (`INCLUDE (level)`)·격리 행 제외(`quarantined_at IS NULL`)까지 튜닝된 쪽이 T-VN-33의
-- 도착점이다(근거는 0090의 해당 실행문 주석 — member 당 상위 limit scan을 index-only로
-- 유지한다). 앞 판은 `(import_job_dataset_id, occurred_at DESC)` +
-- `WHERE import_job_dataset_id IS NOT NULL`만 들고 있었다.
CREATE INDEX idx_import_job_events_member_time
    ON ops.import_job_events (import_job_dataset_id, occurred_at DESC, event_id DESC)
    INCLUDE (level)
    WHERE import_job_dataset_id IS NOT NULL AND quarantined_at IS NULL;
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
    ) ON DELETE RESTRICT
);
CREATE INDEX idx_feature_update_request_datasets_dataset_request
    ON ops.feature_update_request_datasets (provider_dataset_id, request_id);
CREATE TRIGGER trg_feature_update_request_datasets_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON ops.feature_update_request_datasets
    FOR EACH ROW EXECUTE FUNCTION
        provider_sync.reject_inactive_feature_update_request_dataset_membership();

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
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
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
    -- 멱등 키도 identity triple이다 — operation을 교체(A disable → B enable)한 뒤
    -- 같은 파일을 다시 올릴 때 없어진 operation에 결박된 옛 행이 UNIQUE를 막지
    -- 않는다. 형제 membership 테이블도 4열이다(alembic 0092).
    CONSTRAINT uq_offline_uploads_dataset_scope_checksum UNIQUE (
        provider_dataset_id, sync_scope, operation_key, checksum_sha256
    ),
    CONSTRAINT fk_offline_uploads_exact_operation_scope FOREIGN KEY (
        provider_dataset_id, sync_scope, operation_key
    ) REFERENCES provider_sync.provider_dataset_operation_scopes (
        provider_dataset_id, sync_scope, operation_key
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_offline_uploads_checksum CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX idx_offline_uploads_dataset_created
    ON ops.offline_uploads (provider_dataset_id, created_at DESC);
CREATE TRIGGER trg_offline_uploads_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON ops.offline_uploads
    FOR EACH ROW EXECUTE FUNCTION
        provider_sync.reject_inactive_offline_upload_membership();

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
    observation_run_id bigint GENERATED ALWAYS AS IDENTITY,
    integrity_observation_scope_id bigint NOT NULL,
    generation bigint NOT NULL,
    external_run_id text NOT NULL,
    status text NOT NULL DEFAULT 'collecting',
    CONSTRAINT pk_integrity_observation_runs PRIMARY KEY (observation_run_id),
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
    -- Ownership is the dataset alone. source_record_key is a *pointer* to the record
    -- that currently exhibits the finding, and it must stay mutable: the
    -- ON DELETE SET NULL FK nulls it when the record is purged, and recurrence upserts
    -- re-point it at the newest record for the same dedupe_key. Re-parenting is still
    -- blocked because the dataset agreement check below runs on every write, so the
    -- pointer can only move inside the owning dataset (or to NULL).
    IF TG_OP = 'UPDATE'
       AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id
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
-- registry는 storage 객체의 거울이다. dataset을 비활성화해도 그 dataset이 남긴
-- 파일은 그대로 있고, 삭제·orphan·missing 기록은 새 실행이 아니라 정리와 감사다.
-- alembic 0091은 이 테이블에도 `reject_inactive_provider_dataset`을 걸어 비활성
-- dataset의 파일 상태 변화를 INSERT/UPDATE/DELETE 어느 쪽으로도 적을 수 없게 했고,
-- 호출부가 `file_registry.registry_guard`(`except Exception`)로 감싸므로 그 실패는
-- 로그 한 줄만 남기고 사라진다. 0092가 활성 검사를 떼고 소유권 immutable만 남겼다 —
-- violation-fixtures-v1.sql의 `inactive_dataset_managed_file_owner_clear`가 그
-- 거부를 계속 못박는다. 그 fixture가 못박는 것은 **값 → NULL**(귀속 해제)이다.
-- **NULL → 값**은 rebinding이 아니라 최초 귀속이라 거부하지 않는다 —
-- `file_registry._UPSERT_SQL`의 `ON CONFLICT ... DO UPDATE`가 재등록 시 소유자를
-- 붙이는 CASE를 명시적으로 구현하고 있고, `file_registry_scan.scan_s3_location`은
-- 소유 upload 행이 아직 없는 객체를 `provider_dataset_id=NULL`로 먼저 등록한다.
CREATE FUNCTION provider_sync.reject_managed_file_dataset_rebinding()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.provider_dataset_id IS NOT NULL
       AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id
    THEN
        RAISE EXCEPTION 'provider dataset ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_ownership_immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_managed_files_dataset_ownership
    BEFORE INSERT OR UPDATE OR DELETE ON ops.managed_files
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_managed_file_dataset_rebinding();
