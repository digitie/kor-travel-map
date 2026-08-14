# ruff: noqa: E501
"""T-VN-34A Feature 직교 상태·전이 감사 DB spine.

Revision ID: 0095_tvn34_state_spine
Revises: 0095_tvn33_tvn38_head_merge

서비스 전 단계의 stacked draft다. legacy ``status``/soft-delete 열의 물리 제거는
T-VN-34C final cutover가 맡는다. 이 revision은 새 세 축과 DB 강제 write/audit
경계를 먼저 만들고, 기존 상태를 한 번만 mapping해 append-only audit으로 보존한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0095_tvn34_state_spine"
down_revision: str | Sequence[str] | None = "0095_tvn33_tvn38_head_merge"
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
    v_source_entity_key text;
    v_source_record_key text;
    v_provider_receipt text;
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
            'provider_dataset_id', 'source_entity_key', 'source_record_key',
            'reactivation_evidence'
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
           OR p_context ? 'principal'
           OR jsonb_typeof(p_context -> 'source_entity_key') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'source_entity_key') = ''
           OR jsonb_typeof(p_context -> 'source_record_key') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'source_record_key') = '' THEN
                RAISE EXCEPTION 'provider state context must derive its principal from a dataset'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        v_dataset_id := (p_context ->> 'provider_dataset_id')::bigint;
        v_source_entity_key := btrim(p_context ->> 'source_entity_key');
        v_source_record_key := btrim(p_context ->> 'source_record_key');
        SELECT 'provider:' || dataset.provider || '/' || dataset.dataset_key
          INTO v_principal
          FROM provider_sync.provider_datasets AS dataset
         WHERE dataset.provider_dataset_id = v_dataset_id
           AND dataset.is_active;
        IF v_principal IS NULL THEN
            RAISE EXCEPTION 'active provider dataset % is required for state transition', v_dataset_id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        SELECT record.raw_payload_hash
          INTO v_provider_receipt
          FROM provider_sync.source_records AS record
          JOIN provider_sync.source_entities AS entity
            ON entity.source_entity_key = record.source_entity_key
          JOIN provider_sync.source_entity_heads AS head
            ON head.source_entity_key = entity.source_entity_key
           AND head.current_source_record_key = record.source_record_key
         WHERE record.source_record_key = v_source_record_key
           AND record.source_entity_key = v_source_entity_key
           AND entity.provider_dataset_id = v_dataset_id;
        IF v_provider_receipt IS NULL OR btrim(v_provider_receipt) = '' THEN
            RAISE EXCEPTION 'provider state context source does not belong to the active dataset'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
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
        v_context := v_context || jsonb_build_object(
            'provider_dataset_id', v_dataset_id,
            'source_entity_key', v_source_entity_key,
            'source_record_key', v_source_record_key,
            'provider_evidence', jsonb_build_object(
                'authoritative_receipt', v_provider_receipt
            )
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
        transition_kind, reason_code, principal, causation_ref,
        provider_dataset_id, source_entity_key, source_record_key, provider_evidence,
        occurred_at,
        row_revision, invoker_role, state_procedure_definer, audit_writer_definer
    ) VALUES (
        NEW.feature_id, NEW.feature_uuid,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.lifecycle_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.publication_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.quality_state END,
        NEW.lifecycle_state, NEW.publication_state, NEW.quality_state,
        v_context ->> 'transition_kind', v_context ->> 'reason_code',
        v_context ->> 'principal', v_context ->> 'causation_ref',
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN (v_context ->> 'provider_dataset_id')::bigint END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context ->> 'source_entity_key' END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context ->> 'source_record_key' END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context -> 'provider_evidence' END,
        clock_timestamp(),
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
    v_feature_id text;
    v_feature_uuid uuid;
    v_kind text;
    v_name text;
    v_category text;
    v_coord feature.features.coord%TYPE;
BEGIN
    IF jsonb_typeof(p_feature) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'feature payload must be an object'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    -- 허용 목록 밖의 key는 무시하지 않는다. 특히 legacy state/deletion 및 user
    -- provenance key를 받으면 runtime이 procedure 경계를 우회하게 되므로 fail-close다.
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_feature) AS key_name(key_name)
        WHERE key_name NOT IN (
            'feature_id', 'feature_uuid', 'kind', 'name', 'category',
            'lon', 'lat', 'coord_precision_digits', 'address',
            'legal_dong_code', 'road_name_code', 'road_address_management_no',
            'admin_dong_code', 'sido_code', 'sigungu_code', 'urls',
            'marker_icon', 'marker_color', 'parent_feature_id', 'sibling_group_id',
            'raw_refs'
        )
    ) OR p_feature ?| ARRAY[
        'status', 'deleted_at', 'user_deleted_at', 'user_deleted_by',
        'user_change_kind', 'user_change_status', 'user_change_request_id',
        'user_change_reason', 'lifecycle_state', 'publication_state', 'quality_state'
    ] THEN
        RAISE EXCEPTION 'feature create payload contains a forbidden or unknown field'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF (p_feature ? 'address' AND jsonb_typeof(p_feature -> 'address') IS DISTINCT FROM 'object')
       OR (p_feature ? 'urls' AND jsonb_typeof(p_feature -> 'urls') IS DISTINCT FROM 'object')
       OR (p_feature ? 'raw_refs' AND jsonb_typeof(p_feature -> 'raw_refs') IS DISTINCT FROM 'array') THEN
        RAISE EXCEPTION 'feature create payload has an invalid JSON field shape'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    v_feature_id := nullif(btrim(p_feature ->> 'feature_id'), '');
    v_kind := nullif(btrim(p_feature ->> 'kind'), '');
    v_name := nullif(btrim(p_feature ->> 'name'), '');
    v_category := nullif(btrim(p_feature ->> 'category'), '');
    IF v_feature_id IS NULL OR v_kind IS NULL OR v_name IS NULL OR v_category IS NULL THEN
        RAISE EXCEPTION 'feature create payload lacks required core fields'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF p_feature ? 'feature_uuid' THEN
        v_feature_uuid := nullif(btrim(p_feature ->> 'feature_uuid'), '')::uuid;
    END IF;
    IF (p_feature ? 'lon') <> (p_feature ? 'lat') THEN
        RAISE EXCEPTION 'feature coordinate requires both lon and lat'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF p_feature ? 'lon' THEN
        v_coord := x_extension.st_setsrid(
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
        v_feature_id, v_feature_uuid, v_kind, v_name,
        v_category, v_coord, (p_feature ->> 'coord_precision_digits')::smallint,
        coalesce(p_feature -> 'address', '{}'::jsonb), p_feature ->> 'legal_dong_code',
        p_feature ->> 'road_name_code', p_feature ->> 'road_address_management_no',
        p_feature ->> 'admin_dong_code', p_feature ->> 'sido_code', p_feature ->> 'sigungu_code',
        coalesce(p_feature -> 'urls', '{}'::jsonb), p_feature ->> 'marker_icon', p_feature ->> 'marker_color',
        p_feature ->> 'parent_feature_id', nullif(p_feature ->> 'sibling_group_id', '')::uuid,
        coalesce(p_feature -> 'raw_refs', '[]'::jsonb), p_lifecycle_state,
        p_publication_state, p_quality_state,
        'provider', 0,
        NULL, NULL, NULL, NULL, NULL, NULL,
        clock_timestamp(), clock_timestamp()
    ) ON CONFLICT (feature_id) DO NOTHING
    RETURNING feature_id, feature_uuid, row_revision
         INTO o_feature_id, o_feature_uuid, o_row_revision;

    o_inserted := FOUND;
    IF NOT o_inserted THEN
        SELECT feature_id, feature_uuid, row_revision
          INTO o_feature_id, o_feature_uuid, o_row_revision
          FROM feature.features
         WHERE feature_id = v_feature_id;
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

    IF p_context ->> 'transition_kind' = 'provider_sync'
       AND (
            (v_current.lifecycle_state = 'active' AND p_lifecycle_state = 'retired')
            OR (v_current.lifecycle_state = 'retired' AND p_lifecycle_state = 'active')
       )
       AND NOT EXISTS (
            SELECT 1
            FROM provider_sync.source_links AS link
            JOIN provider_sync.source_entities AS entity
              ON entity.source_entity_key = link.source_entity_key
            JOIN provider_sync.source_records AS record
              ON record.source_entity_key = entity.source_entity_key
            JOIN provider_sync.source_entity_heads AS head
              ON head.source_entity_key = entity.source_entity_key
             AND head.current_source_record_key = record.source_record_key
            WHERE link.feature_id = p_feature_id
              AND link.source_entity_key = p_context ->> 'source_entity_key'
              AND entity.provider_dataset_id = (p_context ->> 'provider_dataset_id')::bigint
              AND record.source_record_key = p_context ->> 'source_record_key'
       ) THEN
        RAISE EXCEPTION 'provider lifecycle transition requires linked authoritative source evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
    END IF;

    IF v_current.lifecycle_state = 'retired' AND p_lifecycle_state = 'active' THEN
        IF p_context ->> 'transition_kind' <> 'provider_sync'
           AND (p_context ->> 'transition_kind' NOT IN ('admin', 'user_request', 'system')
           OR coalesce(btrim(p_context ->> 'reactivation_evidence'), '') = '') THEN
            RAISE EXCEPTION 'retired feature may be reactivated only by explicit reingest'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_reactivation_explicit';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM ops.feature_overrides AS override
            WHERE override.feature_id = p_feature_id
              AND override.field_path = 'lifecycle_state'
              AND override.status = 'active'
              AND override.override_value = '"retired"'::jsonb
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
           -- T-VN-34C가 legacy status를 제거하기 전까지 merge loser의
           -- terminal projection은 typed ``merge`` operation에서만 파생한다.
           -- Runtime caller는 여전히 feature row status를 직접 쓰지 못한다.
           status = CASE WHEN p_context ->> 'transition_kind' = 'merge'
                         THEN 'deleted' ELSE status END,
           deleted_at = CASE WHEN p_context ->> 'transition_kind' = 'merge'
                             THEN COALESCE(deleted_at, clock_timestamp())
                             ELSE deleted_at END,
           updated_at = clock_timestamp()
     WHERE feature_id = p_feature_id
     RETURNING feature_id, row_revision INTO o_feature_id, o_row_revision;
END;
$$;
"""


_USER_PROVENANCE_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.materialize_user_feature_change_provenance(
    IN p_feature_id text,
    IN p_change_kind text,
    IN p_request_id uuid,
    IN p_reason text,
    IN p_operator text,
    IN p_expected_row_revision bigint,
    OUT o_feature_id text,
    OUT o_row_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
    v_request_state text;
    v_next_version integer;
BEGIN
    IF p_change_kind NOT IN ('add', 'update', 'delete')
       OR p_request_id IS NULL
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason), '') = ''
       OR coalesce(btrim(p_operator), '') = '' THEN
        RAISE EXCEPTION 'user feature provenance has invalid typed arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_user_provenance';
    END IF;

    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    SELECT request.state INTO v_request_state
      FROM ops.feature_change_requests AS request
     WHERE request.request_id = p_request_id
       AND request.feature_id = p_feature_id
       AND request.action = p_change_kind;
    IF NOT FOUND OR v_request_state NOT IN ('pending', 'applied') THEN
        RAISE EXCEPTION 'user feature provenance request is not pending or applied for this feature/action'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_user_provenance_request';
    END IF;
    -- immediate request는 state='applied'로 먼저 표시된다. 이미 이 exact request의
    -- provenance/snapshot을 materialize한 재호출은 stale expected revision에도
    -- 안전한 receipt를 반환한다.
    IF v_request_state = 'applied'
       AND v_current.user_change_request_id = p_request_id
       AND v_current.user_change_kind = p_change_kind
       AND v_current.user_change_status = 'applied' THEN
        o_feature_id := v_current.feature_id;
        o_row_revision := v_current.row_revision;
        RETURN;
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    -- ``review_mode=immediate`` marks the request applied before its core write
    -- and this typed provenance materialization run.  ``pending`` and
    -- ``applied`` therefore both identify an authorized request here; row-lock
    -- plus expected revision makes a stale second materialization conflict.
    IF p_change_kind = 'delete'
       AND (v_current.lifecycle_state <> 'retired'
            OR v_current.publication_state <> 'suppressed') THEN
        RAISE EXCEPTION 'delete provenance requires a retired suppressed feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_user_provenance_delete_state';
    END IF;

    SELECT greatest(
        v_current.data_version,
        coalesce((SELECT max(version) + 1
                  FROM feature.feature_versions
                 WHERE feature_id = p_feature_id), 1)
    )::integer
      INTO v_next_version;

    UPDATE feature.features
       SET data_origin = 'user_request',
           data_version = v_next_version,
           user_change_kind = p_change_kind,
           user_change_status = 'applied',
           user_change_request_id = p_request_id,
           user_deleted_at = CASE WHEN p_change_kind = 'delete' THEN clock_timestamp()
                                  ELSE user_deleted_at END,
           user_deleted_by = CASE WHEN p_change_kind = 'delete' THEN btrim(p_operator)
                                  ELSE user_deleted_by END,
           user_change_reason = btrim(p_reason),
           updated_at = clock_timestamp()
     WHERE feature_id = p_feature_id
     RETURNING feature_id, row_revision INTO o_feature_id, o_row_revision;

    -- Runtime에는 detailed view/version table의 직접 권한을 주지 않는다. Typed
    -- provenance write 이후의 동일 row lock에서 immutable response-shape snapshot을
    -- 남겨 core/subtype 변경과 version evidence가 분리되지 않게 한다.
    INSERT INTO feature.feature_versions (
        feature_id, version, origin, change_kind, payload, request_id, created_by
    )
    SELECT
        detailed.feature_id,
        v_next_version,
        'user_request',
        p_change_kind,
        jsonb_build_object(
            'feature_id', detailed.feature_id,
            'kind', detailed.kind,
            'name', detailed.name,
            'category', detailed.category,
            'lon', x_extension.ST_X(detailed.coord),
            'lat', x_extension.ST_Y(detailed.coord),
            'coord_precision_digits', detailed.coord_precision_digits,
            'address', detailed.address,
            'legal_dong_code', detailed.legal_dong_code,
            'road_name_code', detailed.road_name_code,
            'road_address_management_no', detailed.road_address_management_no,
            'admin_dong_code', detailed.admin_dong_code,
            'sido_code', detailed.sido_code,
            'sigungu_code', detailed.sigungu_code,
            'urls', detailed.urls,
            'marker_icon', detailed.marker_icon,
            'marker_color', detailed.marker_color,
            'parent_feature_id', detailed.parent_feature_id,
            'sibling_group_id', detailed.sibling_group_id,
            'detail', detailed.detail,
            'status', detailed.status,
            'data_origin', detailed.data_origin,
            'data_version', detailed.data_version,
            'user_change_kind', detailed.user_change_kind,
            'user_change_status', detailed.user_change_status,
            'user_deleted_at', detailed.user_deleted_at,
            'deleted_at', detailed.deleted_at,
            'updated_at', detailed.updated_at
        ),
        p_request_id,
        btrim(p_operator)
    FROM feature.features_detailed AS detailed
    WHERE detailed.feature_id = p_feature_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % has no detailed snapshot', p_feature_id
            USING ERRCODE = 'P0002';
    END IF;
END;
$$;
"""


_LIFECYCLE_OVERRIDE_AUTHOR_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.author_lifecycle_override(
    IN p_feature_id text,
    IN p_source_lifecycle_state text,
    IN p_override_lifecycle_state text,
    IN p_prevent_provider_reactivation boolean,
    IN p_reason text,
    IN p_principal text,
    IN p_expected_row_revision bigint,
    OUT o_row_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    IF p_source_lifecycle_state NOT IN ('active', 'retired')
       OR p_override_lifecycle_state NOT IN ('active', 'retired')
       OR p_prevent_provider_reactivation IS NULL
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1
       OR coalesce(btrim(p_reason), '') = ''
       OR coalesce(btrim(p_principal), '') = '' THEN
        RAISE EXCEPTION 'lifecycle override has invalid typed arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;
    -- A lifecycle override can only describe the tuple that is currently
    -- authoritative.  In particular a caller cannot pre-authorize a future
    -- provider reactivation by choosing an arbitrary override value.
    IF v_current.lifecycle_state <> p_override_lifecycle_state THEN
        RAISE EXCEPTION 'lifecycle override value must equal the current lifecycle state'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    -- ``source_value`` is evidence, never caller-authored history.  It is
    -- either the currently observed lifecycle (for an existing retired
    -- feature) or the ``from`` side of the exact audited state transition
    -- which produced ``p_expected_row_revision``.  The latter is what allows
    -- an active -> retired lifecycle command to retain its authoritative
    -- source state without opening a generic override write boundary.
    IF p_source_lifecycle_state <> v_current.lifecycle_state
       AND NOT EXISTS (
            SELECT 1
            FROM feature.feature_state_transitions AS transition
            WHERE transition.feature_id = p_feature_id
              AND transition.row_revision = p_expected_row_revision
              AND transition.from_lifecycle_state = p_source_lifecycle_state
              AND transition.to_lifecycle_state = v_current.lifecycle_state
       ) THEN
        RAISE EXCEPTION 'lifecycle override source must match current state or exact audited transition'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    INSERT INTO ops.feature_overrides (
        feature_id, source_record_key, field_path,
        source_value, override_value, prevent_provider_reactivation,
        status, reason, created_by
    ) VALUES (
        p_feature_id, NULL, 'lifecycle_state',
        to_jsonb(p_source_lifecycle_state), to_jsonb(p_override_lifecycle_state),
        p_prevent_provider_reactivation,
        'active', btrim(p_reason), btrim(p_principal)
    ) ON CONFLICT (feature_id, field_path) WHERE status = 'active'
    DO UPDATE SET
        source_value = EXCLUDED.source_value,
        override_value = EXCLUDED.override_value,
        prevent_provider_reactivation = EXCLUDED.prevent_provider_reactivation,
        reason = EXCLUDED.reason,
        created_by = EXCLUDED.created_by,
        created_at = clock_timestamp();

    o_row_revision := v_current.row_revision;
END;
$$;
"""


_LIFECYCLE_OVERRIDE_REVOKE_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.revoke_lifecycle_override(
    IN p_feature_id text,
    IN p_principal text,
    IN p_expected_row_revision bigint,
    OUT o_row_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    IF coalesce(btrim(p_principal), '') = ''
       OR p_expected_row_revision IS NULL OR p_expected_row_revision < 1 THEN
        RAISE EXCEPTION 'lifecycle override revoke has invalid typed arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_lifecycle_override_command';
    END IF;

    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature % revision changed', p_feature_id USING ERRCODE = '40001';
    END IF;

    UPDATE ops.feature_overrides
       SET status = 'superseded',
           created_by = btrim(p_principal),
           created_at = clock_timestamp()
     WHERE feature_id = p_feature_id
       AND field_path = 'lifecycle_state'
       AND status = 'active';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % has no active lifecycle override', p_feature_id
            USING ERRCODE = 'P0002';
    END IF;
    o_row_revision := v_current.row_revision;
END;
$$;
"""


_PROVIDER_VERSION_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.materialize_provider_feature_version(
    IN p_feature_id text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    SELECT * INTO v_current
      FROM feature.features
     WHERE feature_id = p_feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % does not exist', p_feature_id USING ERRCODE = 'P0002';
    END IF;

    -- The runtime supplies only a Feature identifier.  The immutable provider
    -- version is assembled from the locked DB row and the canonical detailed
    -- projection, never from a caller-controlled JSON snapshot.
    INSERT INTO feature.feature_versions (
        feature_id, version, origin, change_kind, payload, request_id, created_by
    )
    SELECT
        detailed.feature_id,
        0,
        'provider',
        'load',
        jsonb_build_object(
            'feature_id', detailed.feature_id,
            'feature_uuid', detailed.feature_uuid,
            'kind', detailed.kind,
            'name', detailed.name,
            'category', detailed.category,
            'lon', x_extension.ST_X(detailed.coord),
            'lat', x_extension.ST_Y(detailed.coord),
            'coord_precision_digits', detailed.coord_precision_digits,
            'address', detailed.address,
            'legal_dong_code', detailed.legal_dong_code,
            'road_name_code', detailed.road_name_code,
            'road_address_management_no', detailed.road_address_management_no,
            'admin_dong_code', detailed.admin_dong_code,
            'sido_code', detailed.sido_code,
            'sigungu_code', detailed.sigungu_code,
            'urls', detailed.urls,
            'marker_icon', detailed.marker_icon,
            'marker_color', detailed.marker_color,
            'parent_feature_id', detailed.parent_feature_id,
            'sibling_group_id', detailed.sibling_group_id,
            'raw_refs', detailed.raw_refs,
            'detail', detailed.detail,
            'status', detailed.status,
            'data_origin', detailed.data_origin,
            'data_version', detailed.data_version,
            'created_at', detailed.created_at,
            'updated_at', detailed.updated_at
        ),
        NULL,
        'provider'
    FROM feature.features_detailed AS detailed
    WHERE detailed.feature_id = p_feature_id
    ON CONFLICT (feature_id, version) DO UPDATE SET
        payload = EXCLUDED.payload,
        origin = EXCLUDED.origin,
        change_kind = EXCLUDED.change_kind,
        request_id = EXCLUDED.request_id,
        created_by = EXCLUDED.created_by,
        created_at = clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature % has no detailed snapshot', p_feature_id
            USING ERRCODE = 'P0002';
    END IF;
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
            -- Dedicated migrator runs ``SET LOCAL ROLE ktm_feature_schema_owner``.
            -- That restricted role has no ADMIN OPTION over routine owners. Bootstrap
            -- must establish membership before Alembic; 0095 never self-grants it.
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
                WHERE granted_role.rolname = 'ktm_feature_state_procedure_owner'
                  AND member_role.rolname = 'ktm_feature_schema_owner'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
                WHERE granted_role.rolname = 'ktm_feature_audit_writer'
                  AND member_role.rolname = 'ktm_feature_schema_owner'
            ) THEN
                RAISE EXCEPTION
                    '0095 requires bootstrap membership of schema owner in state/audit owners'
                    USING ERRCODE = '42501';
            END IF;
        END;
        $$
        """
    )
    # LOGIN migrator/runtime identities와 schema-owner membership은 deployment
    # bootstrap가 pre-provision한다. 위 DO block은 CREATEROLE bootstrap만 보완하고,
    # restricted migrator는 membership을 검증만 한다.
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
            provider_dataset_id bigint,
            source_entity_key text,
            source_record_key text,
            provider_evidence jsonb,
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
            CONSTRAINT ck_feature_state_transitions_provider_provenance CHECK (
                (
                    transition_kind = 'provider_sync'
                    AND provider_dataset_id IS NOT NULL
                    AND btrim(source_entity_key) <> ''
                    AND btrim(source_record_key) <> ''
                    AND jsonb_typeof(provider_evidence) = 'object'
                    AND jsonb_typeof(provider_evidence -> 'authoritative_receipt') = 'string'
                    AND btrim(provider_evidence ->> 'authoritative_receipt') <> ''
                ) OR (
                    transition_kind <> 'provider_sync'
                    AND provider_dataset_id IS NULL
                    AND source_entity_key IS NULL
                    AND source_record_key IS NULL
                    AND provider_evidence IS NULL
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
    op.execute(_USER_PROVENANCE_PROCEDURE_SQL)
    op.execute(_LIFECYCLE_OVERRIDE_AUTHOR_PROCEDURE_SQL)
    op.execute(_LIFECYCLE_OVERRIDE_REVOKE_PROCEDURE_SQL)
    op.execute(_PROVIDER_VERSION_PROCEDURE_SQL)
    op.execute("ALTER FUNCTION feature.prepare_feature_state_context(jsonb, text) OWNER TO ktm_feature_state_procedure_owner")
    op.execute("ALTER PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) OWNER TO ktm_feature_state_procedure_owner")
    op.execute("ALTER PROCEDURE feature.transition_feature_state(text, text, text, text, bigint, jsonb) OWNER TO ktm_feature_state_procedure_owner")
    op.execute(
        "ALTER PROCEDURE feature.materialize_user_feature_change_provenance("
        "text, text, uuid, text, text, bigint) OWNER TO ktm_feature_state_procedure_owner"
    )
    op.execute(
        "ALTER PROCEDURE feature.author_lifecycle_override("
        "text, text, text, boolean, text, text, bigint) "
        "OWNER TO ktm_feature_state_procedure_owner"
    )
    op.execute(
        "ALTER PROCEDURE feature.revoke_lifecycle_override(text, text, bigint) "
        "OWNER TO ktm_feature_state_procedure_owner"
    )
    op.execute(
        "ALTER PROCEDURE feature.materialize_provider_feature_version(text) "
        "OWNER TO ktm_feature_state_procedure_owner"
    )
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
        # 0080 UUID fill trigger는 procedure owner가 호출한다. Runtime의 normal
        # core update SQL도 typed coordinate expression을 parse하므로 schema USAGE만
        # 준다(Feature/provenance DML이나 helper EXECUTE 권한은 주지 않는다).
        "GRANT USAGE ON SCHEMA x_extension TO ktm_feature_state_procedure_owner, ktm_feature_runtime",
        "GRANT SELECT, INSERT ON feature.features TO ktm_feature_state_procedure_owner",
        "GRANT SELECT ON feature.feature_state_transitions TO ktm_feature_state_procedure_owner",
        # 전이 procedure는 세 축과 server-owned `updated_at` timestamp만 쓴다.
        "GRANT UPDATE (lifecycle_state, publication_state, quality_state, "
        "status, deleted_at, updated_at) "
        "ON feature.features TO ktm_feature_state_procedure_owner",
        # 0080 alias trigger의 INSERT .. ON CONFLICT DO NOTHING은 alias probe를
        # 수행하므로 SELECT와 INSERT가 모두 필요하다.
        "GRANT SELECT, INSERT ON feature.feature_aliases TO ktm_feature_state_procedure_owner",
        "GRANT SELECT ON provider_sync.provider_datasets, provider_sync.source_entities, "
        "provider_sync.source_records, provider_sync.source_entity_heads, provider_sync.source_links "
        "TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, INSERT, UPDATE (source_value, override_value, "
        "prevent_provider_reactivation, status, reason, created_by, created_at) "
        "ON ops.feature_overrides TO ktm_feature_state_procedure_owner",
        "GRANT SELECT ON ops.feature_change_requests TO ktm_feature_state_procedure_owner",
        "GRANT SELECT, INSERT, UPDATE ON feature.feature_versions "
        "TO ktm_feature_state_procedure_owner",
        "GRANT SELECT ON feature.features_detailed TO ktm_feature_state_procedure_owner",
        "GRANT UPDATE (data_origin, data_version, user_change_kind, user_change_status, "
        "user_change_request_id, user_deleted_at, user_deleted_by, user_change_reason, updated_at) "
        "ON feature.features TO ktm_feature_state_procedure_owner",
        "GRANT INSERT ON feature.feature_state_transitions TO ktm_feature_audit_writer",
        "GRANT USAGE, SELECT ON SEQUENCE feature.feature_state_transitions_transition_id_seq "
        "TO ktm_feature_audit_writer",
        # runtime의 기존 normal core write는 C cutover까지 유지한다. 상태축 및 legacy
        # state surrogate(status/deleted*)는 포함하지 않아 procedure 경계를 우회할 수 없다.
        "GRANT SELECT, UPDATE ("
        "kind, name, category, coord, coord_precision_digits, address, legal_dong_code, "
        "road_name_code, road_address_management_no, admin_dong_code, sido_code, sigungu_code, "
        "urls, marker_icon, marker_color, parent_feature_id, sibling_group_id, raw_refs, "
        "created_at, updated_at"
        ") ON feature.features TO ktm_feature_runtime",
        "GRANT SELECT, INSERT, UPDATE ON ops.feature_change_requests TO ktm_feature_runtime",
        "GRANT SELECT ON feature.feature_state_transitions TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) "
        "TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.transition_feature_state(text, text, text, text, bigint, jsonb) "
        "TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.materialize_user_feature_change_provenance("
        "text, text, uuid, text, text, bigint) TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.author_lifecycle_override("
        "text, text, text, boolean, text, text, bigint) TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.revoke_lifecycle_override(text, text, bigint) "
        "TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.materialize_provider_feature_version(text) "
        "TO ktm_feature_runtime",
        "REVOKE INSERT, DELETE, TRUNCATE ON feature.features FROM ktm_feature_runtime",
        "REVOKE ALL ON feature.feature_versions FROM ktm_feature_runtime",
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
        "REVOKE ALL ON PROCEDURE feature.materialize_user_feature_change_provenance("
        "text, text, uuid, text, text, bigint) FROM PUBLIC",
        "REVOKE ALL ON PROCEDURE feature.author_lifecycle_override("
        "text, text, text, boolean, text, text, bigint) FROM PUBLIC",
        "REVOKE ALL ON PROCEDURE feature.revoke_lifecycle_override(text, text, bigint) "
        "FROM PUBLIC",
        "REVOKE ALL ON PROCEDURE feature.materialize_provider_feature_version(text) FROM PUBLIC",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0095 is forward-only; rebuild with provider ETL")
