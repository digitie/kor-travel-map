# ruff: noqa: E501
"""T-VN-34A Feature 직교 상태·전이 감사 DB spine.

Revision ID: 0095_tvn34_state_spine
Revises: 0094_drop_weather_metric_series

서비스 전 단계의 stacked draft다. legacy ``status``/soft-delete 열의 물리 제거는
T-VN-34C final cutover가 맡는다. 이 revision은 새 세 축과 DB 강제 write/audit
경계를 먼저 만들고, 기존 상태를 한 번만 mapping해 append-only audit으로 보존한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0095_tvn34_state_spine"
down_revision: str | Sequence[str] | None = "0094_drop_weather_metric_series"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STATE_CONTEXT_FUNCTION_SQL = r"""
CREATE FUNCTION feature.prepare_feature_state_context(
    p_context jsonb,
    p_mode text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_kind text;
    v_reason text;
    v_principal text;
    v_dataset_id bigint;
    v_context jsonb;
BEGIN
    IF jsonb_typeof(p_context) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'feature state context must be an object'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_object_keys(p_context) AS key_name(key_name)
        WHERE key_name NOT IN (
            'transition_kind', 'reason_code', 'principal', 'causation_ref',
            'provider_dataset_id', 'source_record_key', 'reactivation_evidence'
        )
    ) THEN
        RAISE EXCEPTION 'feature state context contains an unknown key'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    v_kind := p_context ->> 'transition_kind';
    v_reason := p_context ->> 'reason_code';
    IF v_kind NOT IN (
        'initial', 'legacy_backfill', 'provider_sync', 'admin', 'user_request',
        'merge', 'quality_validation', 'system'
    ) OR v_reason IS NULL OR btrim(v_reason) = '' THEN
        RAISE EXCEPTION 'feature state context has invalid kind or reason'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    IF (p_mode = 'create' AND v_kind NOT IN ('initial', 'legacy_backfill', 'provider_sync'))
       OR (p_mode = 'transition' AND v_kind IN ('initial', 'legacy_backfill')) THEN
        RAISE EXCEPTION 'feature state transition kind is invalid for %', p_mode
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;

    -- provider initial creation도 ``provider_sync`` kind를 보존한다. 이때도
    -- principal은 dataset에서만 파생하고 old tuple은 NULL이다.
    IF v_kind = 'provider_sync' THEN
        IF (p_context ->> 'provider_dataset_id') !~ '^[1-9][0-9]*$'
           OR p_context ? 'principal' THEN
                RAISE EXCEPTION 'provider state context must derive its principal from a dataset'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        v_dataset_id := (p_context ->> 'provider_dataset_id')::bigint;
        SELECT 'provider:' || dataset.provider || '/' || dataset.dataset_key
          INTO v_principal
          FROM provider_sync.provider_datasets AS dataset
         WHERE dataset.provider_dataset_id = v_dataset_id
           AND dataset.is_active;
        IF v_principal IS NULL THEN
            RAISE EXCEPTION 'active provider dataset % is required for state transition', v_dataset_id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
    ELSE
        IF p_context ? 'provider_dataset_id'
           OR jsonb_typeof(p_context -> 'principal') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'principal') = '' THEN
            RAISE EXCEPTION 'non-provider state context requires an authenticated principal'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        v_principal := btrim(p_context ->> 'principal');
    END IF;

    IF p_context ? 'causation_ref'
       AND jsonb_typeof(p_context -> 'causation_ref') NOT IN ('string', 'null') THEN
        RAISE EXCEPTION 'causation_ref must be a string or null'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    v_context := jsonb_build_object(
        'transition_kind', v_kind,
        'reason_code', btrim(v_reason),
        'principal', v_principal,
        'causation_ref', p_context -> 'causation_ref'
    );
    IF v_dataset_id IS NOT NULL THEN
        v_context := v_context || jsonb_build_object('provider_dataset_id', v_dataset_id);
    END IF;
    IF p_context ? 'source_record_key' THEN
        v_context := v_context || jsonb_build_object(
            'source_record_key', p_context -> 'source_record_key'
        );
    END IF;
    IF p_context ? 'reactivation_evidence' THEN
        v_context := v_context || jsonb_build_object(
            'reactivation_evidence', p_context -> 'reactivation_evidence'
        );
    END IF;

    PERFORM set_config('feature.state_transition_context', v_context::text, true);
    PERFORM set_config('feature.state_procedure_definer', current_user::text, true);
END;
$$;
"""


_AUDIT_TRIGGER_FUNCTION_SQL = r"""
CREATE FUNCTION feature.write_feature_state_transition()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_context_text text;
    v_context jsonb;
    v_state_definer text;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.lifecycle_state IS NOT DISTINCT FROM NEW.lifecycle_state
       AND OLD.publication_state IS NOT DISTINCT FROM NEW.publication_state
       AND OLD.quality_state IS NOT DISTINCT FROM NEW.quality_state THEN
        RETURN NULL;
    END IF;

    v_context_text := current_setting('feature.state_transition_context', true);
    v_state_definer := current_setting('feature.state_procedure_definer', true);
    IF v_context_text IS NULL
       OR v_state_definer <> 'ktm_feature_state_procedure_owner'
       OR current_user <> 'ktm_feature_audit_writer' THEN
        -- schema/migration owner는 runtime trust boundary 밖이다. existing DDL
        -- migration과 fixture seeding은 이 privileged identity로만 direct write를
        -- 수행할 수 있고, application runtime login은 아래 privilege fence에서
        -- 이 분기에 도달하기 전에 거부된다.
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles AS role_row
            WHERE role_row.rolname = session_user
              AND role_row.rolsuper
        ) THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'feature state mutation requires the state procedure context'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    v_context := v_context_text::jsonb;
    IF jsonb_typeof(v_context) IS DISTINCT FROM 'object'
       OR (v_context ->> 'transition_kind') NOT IN (
            'initial', 'legacy_backfill', 'provider_sync', 'admin', 'user_request',
            'merge', 'quality_validation', 'system'
       )
       OR coalesce(btrim(v_context ->> 'reason_code'), '') = ''
       OR coalesce(btrim(v_context ->> 'principal'), '') = '' THEN
        RAISE EXCEPTION 'feature state mutation has malformed context'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    IF TG_OP = 'INSERT' AND (v_context ->> 'transition_kind') NOT IN (
        'initial', 'legacy_backfill', 'provider_sync'
    ) THEN
        RAISE EXCEPTION 'feature insert needs initial or provider-sync state transition kind'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;
    IF TG_OP = 'UPDATE' AND (v_context ->> 'transition_kind') IN ('initial', 'legacy_backfill') THEN
        RAISE EXCEPTION 'feature update cannot use initial state transition kind'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;

    INSERT INTO feature.feature_state_transitions (
        feature_id, feature_uuid,
        from_lifecycle_state, from_publication_state, from_quality_state,
        to_lifecycle_state, to_publication_state, to_quality_state,
        transition_kind, reason_code, principal, causation_ref, occurred_at,
        row_revision, invoker_role, state_procedure_definer, audit_writer_definer
    ) VALUES (
        NEW.feature_id, NEW.feature_uuid,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.lifecycle_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.publication_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.quality_state END,
        NEW.lifecycle_state, NEW.publication_state, NEW.quality_state,
        v_context ->> 'transition_kind', v_context ->> 'reason_code',
        v_context ->> 'principal', v_context ->> 'causation_ref', clock_timestamp(),
        NEW.row_revision, session_user::text, v_state_definer, current_user::text
    );
    RETURN NULL;
END;
$$;
"""


_AUDIT_GUARD_FUNCTION_SQL = r"""
CREATE FUNCTION feature.reject_feature_state_transition_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'feature state transitions are append-only'
        USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_state_transitions_append_only';
END;
$$;
"""


_CREATE_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.create_feature_with_initial_state(
    IN p_feature jsonb,
    IN p_lifecycle_state text,
    IN p_publication_state text,
    IN p_quality_state text,
    IN p_context jsonb,
    OUT o_feature_id text,
    OUT o_feature_uuid uuid,
    OUT o_row_revision bigint,
    OUT o_inserted boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_feature feature.features%ROWTYPE;
BEGIN
    IF jsonb_typeof(p_feature) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'feature payload must be an object'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    -- Legacy status는 의도적으로 읽지도 쓰지도 않는다. 34A producer는 in-process
    -- status를 세 축으로 map한 뒤 여기에는 axes만 전달한다.
    v_feature := jsonb_populate_record(
        NULL::feature.features,
        p_feature - 'status' - 'lifecycle_state' - 'publication_state' - 'quality_state'
    );
    IF v_feature.feature_id IS NULL OR v_feature.kind IS NULL OR v_feature.name IS NULL
       OR v_feature.category IS NULL THEN
        RAISE EXCEPTION 'feature create payload lacks required core fields'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF (p_feature ? 'lon') <> (p_feature ? 'lat') THEN
        RAISE EXCEPTION 'feature coordinate requires both lon and lat'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF p_feature ? 'lon' THEN
        v_feature.coord := x_extension.st_setsrid(
            x_extension.st_makepoint(
                (p_feature ->> 'lon')::double precision,
                (p_feature ->> 'lat')::double precision
            ),
            4326
        );
    END IF;

    PERFORM feature.prepare_feature_state_context(p_context, 'create');
    INSERT INTO feature.features (
        feature_id, feature_uuid, kind, name, category,
        coord, coord_precision_digits,
        address, legal_dong_code, road_name_code, road_address_management_no,
        admin_dong_code, sido_code, sigungu_code,
        urls, marker_icon, marker_color, parent_feature_id, sibling_group_id,
        raw_refs, lifecycle_state, publication_state, quality_state,
        data_origin, data_version, user_change_kind, user_change_status,
        user_change_request_id, user_deleted_at, user_deleted_by, user_change_reason,
        created_at, updated_at
    ) VALUES (
        v_feature.feature_id, v_feature.feature_uuid, v_feature.kind, v_feature.name,
        v_feature.category, v_feature.coord, v_feature.coord_precision_digits,
        coalesce(v_feature.address, '{}'::jsonb), v_feature.legal_dong_code,
        v_feature.road_name_code, v_feature.road_address_management_no,
        v_feature.admin_dong_code, v_feature.sido_code, v_feature.sigungu_code,
        coalesce(v_feature.urls, '{}'::jsonb), v_feature.marker_icon, v_feature.marker_color,
        v_feature.parent_feature_id, v_feature.sibling_group_id,
        coalesce(v_feature.raw_refs, '[]'::jsonb), p_lifecycle_state,
        p_publication_state, p_quality_state,
        coalesce(v_feature.data_origin, 'provider'), coalesce(v_feature.data_version, 0),
        v_feature.user_change_kind, v_feature.user_change_status,
        v_feature.user_change_request_id, v_feature.user_deleted_at,
        v_feature.user_deleted_by, v_feature.user_change_reason,
        coalesce(v_feature.created_at, clock_timestamp()),
        coalesce(v_feature.updated_at, clock_timestamp())
    ) ON CONFLICT (feature_id) DO NOTHING
    RETURNING feature_id, feature_uuid, row_revision
         INTO o_feature_id, o_feature_uuid, o_row_revision;

    o_inserted := FOUND;
    IF NOT o_inserted THEN
        SELECT feature_id, feature_uuid, row_revision
          INTO o_feature_id, o_feature_uuid, o_row_revision
          FROM feature.features
         WHERE feature_id = v_feature.feature_id;
    END IF;
END;
$$;
"""


_TRANSITION_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.transition_feature_state(
    IN p_feature_id text,
    IN p_lifecycle_state text,
    IN p_publication_state text,
    IN p_quality_state text,
    IN p_expected_row_revision bigint,
    IN p_context jsonb,
    OUT o_feature_id text,
    OUT o_row_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_dataset_id bigint;
BEGIN
    IF p_expected_row_revision IS NULL OR p_expected_row_revision < 1 THEN
        RAISE EXCEPTION 'expected feature row revision is required'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_expected_revision';
    END IF;
    PERFORM feature.prepare_feature_state_context(p_context, 'transition');
    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id
            USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id
            USING ERRCODE = '40001';
    END IF;
    IF (v_current.lifecycle_state, v_current.publication_state, v_current.quality_state)
       IS NOT DISTINCT FROM (p_lifecycle_state, p_publication_state, p_quality_state) THEN
        RAISE EXCEPTION 'feature state transition must change at least one axis'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_non_noop';
    END IF;

    IF v_current.lifecycle_state = 'retired' AND p_lifecycle_state = 'active' THEN
        IF p_context ->> 'transition_kind' = 'provider_sync' THEN
            IF coalesce(btrim(p_context ->> 'reactivation_evidence'), '') = ''
               OR coalesce(btrim(p_context ->> 'source_record_key'), '') = '' THEN
                RAISE EXCEPTION 'provider reactivation requires source evidence'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_reactivation_evidence';
            END IF;
            v_dataset_id := (p_context ->> 'provider_dataset_id')::bigint;
            IF NOT EXISTS (
                SELECT 1
                FROM provider_sync.source_records AS record
                JOIN provider_sync.source_entities AS entity
                  ON entity.source_entity_key = record.source_entity_key
                WHERE record.source_record_key = p_context ->> 'source_record_key'
                  AND entity.provider_dataset_id = v_dataset_id
            ) THEN
                RAISE EXCEPTION 'provider reactivation source does not belong to dataset'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_reactivation_evidence';
            END IF;
        ELSIF p_context ->> 'transition_kind' NOT IN ('admin', 'user_request', 'system')
           OR coalesce(btrim(p_context ->> 'reactivation_evidence'), '') = '' THEN
            RAISE EXCEPTION 'retired feature may be reactivated only by explicit reingest'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_reactivation_explicit';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM ops.feature_overrides AS override
            WHERE override.feature_id = p_feature_id
              AND override.field_path = 'lifecycle_state'
              AND override.status = 'active'
              AND override.prevent_provider_reactivation
        ) AND p_context ->> 'transition_kind' = 'provider_sync' THEN
            RAISE EXCEPTION 'provider reactivation is fenced by lifecycle override'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_reactivation_override';
        END IF;
    END IF;

    UPDATE feature.features
       SET lifecycle_state = p_lifecycle_state,
           publication_state = p_publication_state,
           quality_state = p_quality_state,
           updated_at = clock_timestamp()
     WHERE feature_id = p_feature_id
     RETURNING feature_id, row_revision INTO o_feature_id, o_row_revision;
END;
$$;
"""


def upgrade() -> None:
    # 별도 NOLOGIN owner가 routine privilege와 audit DML을 분리한다. role은 cluster
    # scope라 이미 존재하는 developer/test cluster에서도 재실행 가능해야 한다.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT (SELECT rolsuper OR rolcreaterole FROM pg_catalog.pg_roles WHERE rolname = current_user)
               AND (
                   NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_schema_owner')
                   OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_state_procedure_owner')
                   OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_audit_writer')
                   OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_runtime')
               ) THEN
                RAISE EXCEPTION
                    '0095 requires CREATEROLE or pre-provisioned ktm_feature_* roles'
                    USING ERRCODE = '42501';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_schema_owner') THEN
                CREATE ROLE ktm_feature_schema_owner NOLOGIN NOINHERIT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_state_procedure_owner') THEN
                CREATE ROLE ktm_feature_state_procedure_owner NOLOGIN NOINHERIT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_audit_writer') THEN
                CREATE ROLE ktm_feature_audit_writer NOLOGIN NOINHERIT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_runtime') THEN
                CREATE ROLE ktm_feature_runtime NOLOGIN NOINHERIT;
            END IF;
        END;
        $$
        """
    )
    # LOGIN migrator/runtime identities는 deployment bootstrap가 password 없이 이
    # migration에 남지 않도록 만든다. schema owner는 state/audit NOLOGIN owner의
    # member여야 final ownership transfer와 ALTER OWNER를 수행할 수 있다.
    op.execute(
        "GRANT ktm_feature_state_procedure_owner, ktm_feature_audit_writer "
        "TO ktm_feature_schema_owner"
    )
    op.execute(
        """
        ALTER TABLE feature.features
            ADD COLUMN lifecycle_state text NOT NULL DEFAULT 'active',
            ADD COLUMN publication_state text NOT NULL DEFAULT 'published',
            ADD COLUMN quality_state text NOT NULL DEFAULT 'valid'
        """
    )

    # legacy 값의 단 한 번 mapping. 이 UPDATE는 audit trigger보다 먼저 수행하고,
    # 아래 INSERT가 NULL old tuple의 legacy_backfill evidence를 남긴다.
    op.execute(
        """
        UPDATE feature.features
           SET quality_state = CASE WHEN status = 'broken' THEN 'quarantined' ELSE 'valid' END,
               lifecycle_state = CASE
                   WHEN user_deleted_at IS NOT NULL OR deleted_at IS NOT NULL
                     OR status IN ('inactive', 'deleted') THEN 'retired'
                   ELSE 'active'
               END,
               publication_state = CASE
                   WHEN user_deleted_at IS NOT NULL OR deleted_at IS NOT NULL
                     OR status IN ('inactive', 'deleted') THEN 'suppressed'
                   WHEN status = 'draft' THEN 'draft'
                   WHEN status = 'hidden' THEN 'suppressed'
                   ELSE 'published'
               END
        """
    )
    op.execute(
        """
        ALTER TABLE feature.features
            ADD CONSTRAINT ck_features_lifecycle_state
                CHECK (lifecycle_state IN ('active', 'retired')),
            ADD CONSTRAINT ck_features_publication_state
                CHECK (publication_state IN ('draft', 'published', 'suppressed')),
            ADD CONSTRAINT ck_features_quality_state
                CHECK (quality_state IN ('valid', 'quarantined')),
            ADD CONSTRAINT ck_features_state_tuple
                CHECK (lifecycle_state = 'active' OR publication_state = 'suppressed')
        """
    )
    op.execute(
        """
        CREATE TABLE feature.feature_state_transitions (
            transition_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            feature_id text NOT NULL,
            feature_uuid uuid NOT NULL,
            from_lifecycle_state text,
            from_publication_state text,
            from_quality_state text,
            to_lifecycle_state text NOT NULL,
            to_publication_state text NOT NULL,
            to_quality_state text NOT NULL,
            transition_kind text NOT NULL,
            reason_code text NOT NULL,
            principal text NOT NULL,
            causation_ref text,
            occurred_at timestamptz NOT NULL,
            row_revision bigint NOT NULL,
            invoker_role text NOT NULL,
            state_procedure_definer text NOT NULL,
            audit_writer_definer text NOT NULL,
            CONSTRAINT ck_feature_state_transitions_kind CHECK (
                transition_kind IN (
                    'initial', 'legacy_backfill', 'provider_sync', 'admin',
                    'user_request', 'merge', 'quality_validation', 'system'
                )
            ),
            CONSTRAINT ck_feature_state_transitions_reason CHECK (btrim(reason_code) <> ''),
            CONSTRAINT ck_feature_state_transitions_principal CHECK (btrim(principal) <> ''),
            CONSTRAINT ck_feature_state_transitions_old_tuple CHECK (
                (from_lifecycle_state IS NULL AND from_publication_state IS NULL AND from_quality_state IS NULL)
                OR (
                    from_lifecycle_state IN ('active', 'retired')
                    AND from_publication_state IN ('draft', 'published', 'suppressed')
                    AND from_quality_state IN ('valid', 'quarantined')
                    AND (from_lifecycle_state = 'active' OR from_publication_state = 'suppressed')
                )
            ),
            CONSTRAINT ck_feature_state_transitions_new_tuple CHECK (
                to_lifecycle_state IN ('active', 'retired')
                AND to_publication_state IN ('draft', 'published', 'suppressed')
                AND to_quality_state IN ('valid', 'quarantined')
                AND (to_lifecycle_state = 'active' OR to_publication_state = 'suppressed')
            ),
            CONSTRAINT ck_feature_state_transitions_initial_old_tuple CHECK (
                (
                    from_lifecycle_state IS NULL
                    AND transition_kind IN ('initial', 'legacy_backfill', 'provider_sync')
                ) OR (
                    from_lifecycle_state IS NOT NULL
                    AND transition_kind NOT IN ('initial', 'legacy_backfill')
                )
            ),
            CONSTRAINT ck_feature_state_transitions_row_revision CHECK (row_revision >= 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_feature_state_transitions_feature_occurred "
        "ON feature.feature_state_transitions (feature_id, occurred_at, transition_id)"
    )

    # mapping evidence에는 현행 text business key와 final UUID identity를 함께 남긴다.
    # Feature hard purge 뒤에도 T39 UUID cutover에 필요한 identity가 남아야 하므로
    # Feature FK를 두지 않는다. request가 없거나 delete provenance가 반쪽이면 추정하지
    # 않고 migration 전체를 fail-closed한다.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM feature.features AS feature_row
                WHERE feature_row.user_change_request_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM ops.feature_change_requests AS request
                      WHERE request.request_id = feature_row.user_change_request_id
                  )
            ) OR EXISTS (
                SELECT 1
                FROM feature.features AS feature_row
                WHERE (feature_row.user_deleted_at IS NULL) <> (feature_row.user_deleted_by IS NULL)
            ) THEN
                RAISE EXCEPTION 'T-VN-34 legacy state provenance is contradictory'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_backfill_provenance';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        INSERT INTO feature.feature_state_transitions (
            feature_id, feature_uuid,
            from_lifecycle_state, from_publication_state, from_quality_state,
            to_lifecycle_state, to_publication_state, to_quality_state,
            transition_kind, reason_code, principal, causation_ref, occurred_at,
            row_revision, invoker_role, state_procedure_definer, audit_writer_definer
        )
        SELECT
            feature_id, feature_uuid,
            NULL, NULL, NULL,
            lifecycle_state, publication_state, quality_state,
            'legacy_backfill',
            CASE
                WHEN user_deleted_at IS NOT NULL THEN 'legacy_user_delete'
                WHEN deleted_at IS NOT NULL THEN 'legacy_provider_retire'
                WHEN status IN ('inactive', 'deleted') THEN 'legacy_status_retire'
                ELSE 'legacy_status_map'
            END,
            coalesce(user_deleted_by, 'migration:tvn34'),
            user_change_request_id::text,
            coalesce(user_deleted_at, deleted_at, updated_at),
            row_revision, session_user::text, 'migration:0095', 'migration:0095'
        FROM feature.features
        """
    )

    # status override를 typed lifecycle override로만 옮긴다. 그 밖의 값을 억지로
    # 추정하면 provider 재적재 권한이 달라지므로 fail-closed한다.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM ops.feature_overrides
                WHERE field_path = 'status'
                  AND (
                    jsonb_typeof(override_value) IS DISTINCT FROM 'string'
                    OR override_value #>> '{}' NOT IN ('active', 'inactive', 'deleted')
                  )
            ) THEN
                RAISE EXCEPTION 'legacy status override cannot map to lifecycle_state'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_backfill';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        UPDATE ops.feature_overrides
           SET field_path = 'lifecycle_state',
               source_value = CASE
                   WHEN jsonb_typeof(source_value) = 'string'
                    AND source_value #>> '{}' IN ('inactive', 'deleted') THEN '"retired"'::jsonb
                   WHEN jsonb_typeof(source_value) = 'string'
                    AND source_value #>> '{}' = 'active' THEN '"active"'::jsonb
                   ELSE source_value
               END,
               override_value = CASE
                   WHEN override_value #>> '{}' IN ('inactive', 'deleted') THEN '"retired"'::jsonb
               ELSE '"active"'::jsonb
           END
         WHERE field_path = 'status';
        """
    )
    op.execute(
        """
        ALTER TABLE ops.feature_overrides
            ADD CONSTRAINT ck_feature_overrides_lifecycle_state_value
            CHECK (
                field_path <> 'lifecycle_state'
                OR (
                    jsonb_typeof(override_value) = 'string'
                    AND override_value #>> '{}' IN ('active', 'retired')
                )
            );
        """
    )

    op.execute(_STATE_CONTEXT_FUNCTION_SQL)
    op.execute(_AUDIT_TRIGGER_FUNCTION_SQL)
    op.execute(_AUDIT_GUARD_FUNCTION_SQL)
    op.execute(_CREATE_PROCEDURE_SQL)
    op.execute(_TRANSITION_PROCEDURE_SQL)
    op.execute("ALTER FUNCTION feature.prepare_feature_state_context(jsonb, text) OWNER TO ktm_feature_state_procedure_owner")
    op.execute("ALTER PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) OWNER TO ktm_feature_state_procedure_owner")
    op.execute("ALTER PROCEDURE feature.transition_feature_state(text, text, text, text, bigint, jsonb) OWNER TO ktm_feature_state_procedure_owner")
    op.execute("ALTER FUNCTION feature.write_feature_state_transition() OWNER TO ktm_feature_audit_writer")
    op.execute("ALTER FUNCTION feature.reject_feature_state_transition_mutation() OWNER TO ktm_feature_audit_writer")

    op.execute(
        "CREATE TRIGGER trg_features_state_transition_audit "
        "AFTER INSERT OR UPDATE OF lifecycle_state, publication_state, quality_state "
        "ON feature.features FOR EACH ROW "
        "EXECUTE FUNCTION feature.write_feature_state_transition()"
    )
    op.execute(
        "CREATE TRIGGER trg_feature_state_transitions_append_only_row "
        "BEFORE UPDATE OR DELETE ON feature.feature_state_transitions "
        "FOR EACH ROW EXECUTE FUNCTION feature.reject_feature_state_transition_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_feature_state_transitions_append_only_truncate "
        "BEFORE TRUNCATE ON feature.feature_state_transitions "
        "FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_feature_state_transition_mutation()"
    )

    # 실제 runtime은 feature INSERT/axis UPDATE/audit DML을 얻지 않는다. state
    # procedure owner와 audit writer만 필요한 최소권한을 갖고, direct trigger helper
    # EXECUTE는 PUBLIC/runtime에서 모두 제거한다.
    for statement in (
        "GRANT USAGE ON SCHEMA feature, provider_sync, ops "
        "TO ktm_feature_state_procedure_owner, ktm_feature_audit_writer, ktm_feature_runtime",
        # 0080 UUID fill trigger가 feature INSERT 경로에서 x_extension UUID
        # generator를 호출한다. runtime에는 주지 않고 SECURITY DEFINER owner만 쓴다.
        "GRANT USAGE ON SCHEMA x_extension TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, INSERT ON feature.features TO ktm_feature_state_procedure_owner",
        # 전이 procedure는 세 축과 server-owned `updated_at` timestamp만 쓴다.
        "GRANT UPDATE (lifecycle_state, publication_state, quality_state, updated_at) "
        "ON feature.features TO ktm_feature_state_procedure_owner",
        # 0080 alias trigger의 INSERT .. ON CONFLICT DO NOTHING은 alias probe를
        # 수행하므로 SELECT와 INSERT가 모두 필요하다.
        "GRANT SELECT, INSERT ON feature.feature_aliases TO ktm_feature_state_procedure_owner",
        "GRANT SELECT ON provider_sync.provider_datasets, provider_sync.source_entities, "
        "provider_sync.source_records, ops.feature_overrides "
        "TO ktm_feature_state_procedure_owner",
        "GRANT INSERT ON feature.feature_state_transitions TO ktm_feature_audit_writer",
        "GRANT USAGE, SELECT ON SEQUENCE feature.feature_state_transitions_transition_id_seq "
        "TO ktm_feature_audit_writer",
        # runtime의 기존 normal core write는 C cutover까지 유지한다. 상태축 및 legacy
        # state surrogate(status/deleted*)는 포함하지 않아 procedure 경계를 우회할 수 없다.
        "GRANT SELECT, UPDATE ("
        "kind, name, category, coord, coord_precision_digits, address, legal_dong_code, "
        "road_name_code, road_address_management_no, admin_dong_code, sido_code, sigungu_code, "
        "urls, marker_icon, marker_color, parent_feature_id, sibling_group_id, raw_refs, "
        "data_origin, data_version, created_at, updated_at"
        ") ON feature.features TO ktm_feature_runtime",
        "GRANT SELECT ON feature.feature_state_transitions TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) "
        "TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.transition_feature_state(text, text, text, text, bigint, jsonb) "
        "TO ktm_feature_runtime",
        "REVOKE INSERT, DELETE, TRUNCATE ON feature.features FROM ktm_feature_runtime",
        "REVOKE UPDATE (lifecycle_state, publication_state, quality_state, status, deleted_at, "
        "user_deleted_at, user_deleted_by, user_change_kind, user_change_status, user_change_request_id) "
        "ON feature.features FROM ktm_feature_runtime",
        "REVOKE ALL ON feature.feature_state_transitions FROM PUBLIC, ktm_feature_runtime",
        "GRANT SELECT ON feature.feature_state_transitions TO ktm_feature_runtime",
        "REVOKE ALL ON FUNCTION feature.prepare_feature_state_context(jsonb, text) "
        "FROM PUBLIC, ktm_feature_runtime",
        "REVOKE ALL ON FUNCTION feature.write_feature_state_transition() "
        "FROM PUBLIC, ktm_feature_runtime",
        "REVOKE ALL ON FUNCTION feature.reject_feature_state_transition_mutation() "
        "FROM PUBLIC, ktm_feature_runtime",
        "REVOKE ALL ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) "
        "FROM PUBLIC",
        "REVOKE ALL ON PROCEDURE feature.transition_feature_state(text, text, text, text, bigint, jsonb) "
        "FROM PUBLIC",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0095 is forward-only; rebuild with provider ETL")
