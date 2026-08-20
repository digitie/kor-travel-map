"""T-VN-M04 — 범용 Feature 요청 큐와 Map admin 승인 writer.

Revision ID: 0230_m04_feature_request_queue
Revises: 0228_m03_manual_curation

외부 consumer는 이 revision 뒤에도 Feature relation을 직접 쓸 수 없다. service scope는
immutable request만 넣고, 별도 AdminBFF command가 승인한 경우에만 canonical
Feature와 ``manual_request`` origin을 같은 READ COMMITTED transaction으로 만든다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import op

# ruff: noqa: E501

revision: str = "0230_m04_feature_request_queue"
down_revision: str | Sequence[str] | None = "0228_m03_manual_curation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DDL_SQL = r"""
ALTER TABLE feature.feature_creation_origins
    DROP CONSTRAINT ck_feature_creation_origins_kind,
    DROP CONSTRAINT ck_feature_creation_origins_principal,
    DROP CONSTRAINT ck_feature_creation_origins_roles;

ALTER TABLE feature.feature_creation_origins
    ADD CONSTRAINT ck_feature_creation_origins_kind
        CHECK (origin_kind IN ('manual_admin', 'manual_curation', 'manual_request')),
    ADD CONSTRAINT ck_feature_creation_origins_principal
        CHECK (
            (origin_kind = 'manual_admin'
             AND creator_principal_id = 'admin-ui-bff.manual-feature-create.v1')
            OR
            (origin_kind = 'manual_curation'
             AND creator_principal_id = 'admin-ui-bff.manual-curation-feature-create.v1')
            OR
            (origin_kind = 'manual_request'
             AND creator_principal_id = 'feature-request.approval.v1')
        ),
    ADD CONSTRAINT ck_feature_creation_origins_roles
        CHECK (
            (origin_kind = 'manual_admin'
             AND invoker_role = 'ktm_feature_api_runtime'
             AND procedure_definer = 'ktm_manual_feature_procedure_owner')
            OR
            (origin_kind = 'manual_curation'
             AND invoker_role = 'ktm_feature_api_runtime'
             AND procedure_definer = 'ktm_curation_command_owner')
            OR
            (origin_kind = 'manual_request'
             AND invoker_role = 'ktm_feature_api_runtime'
             AND procedure_definer = 'ktm_feature_request_procedure_owner')
        );

CREATE TABLE ops.feature_requests (
    request_id uuid PRIMARY KEY,
    submitted_by_principal text NOT NULL DEFAULT 'service:feature-request',
    request_payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    submitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    submission_command_id bigint NOT NULL REFERENCES ops.domain_commands(command_id),
    resolved_at timestamptz NULL,
    resolved_by_actor text NULL,
    resolution_command_id bigint NULL REFERENCES ops.domain_commands(command_id),
    resolved_feature_id uuid NULL REFERENCES feature.features(feature_uuid),
    rejection_reason text NULL,
    CONSTRAINT ck_feature_requests_principal
        CHECK (submitted_by_principal = 'service:feature-request'),
    CONSTRAINT ck_feature_requests_payload
        CHECK (
            jsonb_typeof(request_payload) = 'object'
            AND jsonb_typeof(request_payload -> 'kind') = 'string'
            AND request_payload ->> 'kind' IN ('place', 'event')
            AND jsonb_typeof(request_payload -> 'name') = 'string'
            AND nullif(btrim(request_payload ->> 'name'), '') IS NOT NULL
            AND char_length(request_payload ->> 'name') <= 200
            AND jsonb_typeof(request_payload -> 'lon') = 'number'
            AND (request_payload ->> 'lon')::numeric BETWEEN 124 AND 132
            AND jsonb_typeof(request_payload -> 'lat') = 'number'
            AND (request_payload ->> 'lat')::numeric BETWEEN 33 AND 39.5
            AND jsonb_typeof(request_payload -> 'categories') = 'array'
            AND jsonb_array_length(request_payload -> 'categories') <= 10
            AND NOT jsonb_path_exists(
                request_payload,
                '$.categories[*] ? (@.type() != "string")'
            )
            AND (
                NOT request_payload ? 'note'
                OR (
                    jsonb_typeof(request_payload -> 'note') = 'string'
                    AND char_length(request_payload ->> 'note') <= 2000
                )
            )
        ),
    CONSTRAINT ck_feature_requests_status
        CHECK (status IN ('pending', 'approved', 'rejected', 'exact_conflict')),
    CONSTRAINT ck_feature_requests_resolution
        CHECK (
            (status = 'pending'
             AND resolved_at IS NULL AND resolved_by_actor IS NULL
             AND resolution_command_id IS NULL AND resolved_feature_id IS NULL
             AND rejection_reason IS NULL)
            OR
            (status IN ('approved', 'exact_conflict')
             AND resolved_at IS NOT NULL AND resolved_by_actor IS NOT NULL
             AND resolution_command_id IS NOT NULL AND resolved_feature_id IS NOT NULL
             AND rejection_reason IS NULL)
            OR
            (status = 'rejected'
             AND resolved_at IS NOT NULL AND resolved_by_actor IS NOT NULL
             AND resolution_command_id IS NOT NULL AND resolved_feature_id IS NULL
             AND nullif(btrim(rejection_reason), '') IS NOT NULL)
        ),
    CONSTRAINT uq_feature_requests_resolution_command
        UNIQUE (resolution_command_id),
    CONSTRAINT uq_feature_requests_submission_command
        UNIQUE (submission_command_id)
);

CREATE PROCEDURE feature.submit_feature_request(
    IN p_request_id uuid,
    IN p_request_payload jsonb,
    IN p_domain_command_id bigint,
    OUT o_status text,
    OUT o_submitted_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $feature_request_submit$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
    v_existing ops.feature_requests%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Feature request submission requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_feature_request_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_feature_request_service_executor', 'member') THEN
        RAISE EXCEPTION 'Feature request submission requires service executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_request_executor';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command WHERE command.command_id = p_domain_command_id FOR UPDATE;
    IF NOT FOUND OR v_command.operation <> 'service.feature-request.submit.v1'
       OR btrim(v_command.actor) <> 'service:feature-request'
       OR EXISTS (SELECT 1 FROM ops.domain_command_results AS result WHERE result.command_id = p_domain_command_id) THEN
        RAISE EXCEPTION 'Feature request submission command does not match writer'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_command';
    END IF;
    IF p_request_id IS NULL OR jsonb_typeof(p_request_payload) IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_request_payload -> 'kind') IS DISTINCT FROM 'string'
       OR p_request_payload ->> 'kind' NOT IN ('place', 'event')
       OR jsonb_typeof(p_request_payload -> 'name') IS DISTINCT FROM 'string'
       OR nullif(btrim(p_request_payload ->> 'name'), '') IS NULL
       OR char_length(p_request_payload ->> 'name') > 200
       OR jsonb_typeof(p_request_payload -> 'lon') IS DISTINCT FROM 'number'
       OR (p_request_payload ->> 'lon')::numeric NOT BETWEEN 124 AND 132
       OR jsonb_typeof(p_request_payload -> 'lat') IS DISTINCT FROM 'number'
       OR (p_request_payload ->> 'lat')::numeric NOT BETWEEN 33 AND 39.5
       OR jsonb_typeof(p_request_payload -> 'categories') IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_request_payload -> 'categories') > 10
       OR jsonb_path_exists(
            p_request_payload,
            '$.categories[*] ? (@.type() != "string")'
       )
       OR (
            p_request_payload ? 'note'
            AND (
                jsonb_typeof(p_request_payload -> 'note') IS DISTINCT FROM 'string'
                OR char_length(p_request_payload ->> 'note') > 2000
            )
       )
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_request_payload) AS key_name(key_name)
                  WHERE key_name NOT IN ('kind', 'name', 'lon', 'lat', 'categories', 'note')) THEN
        RAISE EXCEPTION 'Feature request payload is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_requests_payload';
    END IF;
    INSERT INTO ops.feature_requests (request_id, request_payload, submission_command_id)
    VALUES (p_request_id, p_request_payload, p_domain_command_id)
    ON CONFLICT (request_id) DO NOTHING
    RETURNING status, submitted_at INTO o_status, o_submitted_at;
    IF o_status IS NULL THEN
        SELECT request.* INTO v_existing
        FROM ops.feature_requests AS request WHERE request.request_id = p_request_id;
        IF NOT FOUND OR v_existing.request_payload IS DISTINCT FROM p_request_payload THEN
        RAISE EXCEPTION 'Feature request id conflicts with a different payload'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_idempotency';
        END IF;
        o_status := v_existing.status;
        o_submitted_at := v_existing.submitted_at;
    END IF;
END
$feature_request_submit$;

CREATE PROCEDURE feature.approve_feature_request_with_initial_state(
    IN p_request_id uuid,
    IN p_feature_payload jsonb,
    IN p_domain_command_id bigint,
    OUT o_outcome text,
    OUT o_feature_id text,
    OUT o_feature_uuid uuid,
    OUT o_row_revision bigint,
    OUT o_existing_feature_uuid uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $feature_request_approve$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
    v_request ops.feature_requests%ROWTYPE;
    v_feature_id text;
    v_feature_uuid uuid;
    v_feature_kind text;
    v_feature_name text;
    v_lon numeric;
    v_lat numeric;
    v_key record;
    v_claimed_feature_uuid uuid;
    v_created_feature_id text;
    v_created_feature_uuid uuid;
    v_created_row_revision bigint;
    v_created boolean;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Feature request approval writer requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_feature_request_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_feature_request_admin_executor', 'member') THEN
        RAISE EXCEPTION 'Feature request approval writer requires admin executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_request_executor';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command WHERE command.command_id = p_domain_command_id FOR UPDATE;
    IF NOT FOUND OR v_command.operation <> 'admin.feature-request.approve.v1'
       OR btrim(v_command.actor) = ''
       OR EXISTS (SELECT 1 FROM ops.domain_command_results AS result WHERE result.command_id = p_domain_command_id) THEN
        RAISE EXCEPTION 'Feature request approval command does not match writer'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_command';
    END IF;
    SELECT request.* INTO v_request FROM ops.feature_requests AS request
    WHERE request.request_id = p_request_id FOR UPDATE;
    IF NOT FOUND OR v_request.status <> 'pending' THEN
        RAISE EXCEPTION 'Feature request is not pending'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_pending';
    END IF;
    IF jsonb_typeof(p_feature_payload) IS DISTINCT FROM 'object'
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_feature_payload) AS key_name(key_name)
                  WHERE key_name NOT IN ('feature_id','feature_uuid','kind','name','category','lon','lat','coord_precision_digits','address','legal_dong_code','road_name_code','road_address_management_no','admin_dong_code','sido_code','sigungu_code','urls','marker_icon','marker_color','parent_feature_id','sibling_group_id','raw_refs'))
       OR jsonb_typeof(p_feature_payload -> 'feature_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'feature_uuid') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'kind') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'name') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'category') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'lon') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_feature_payload -> 'lat') IS DISTINCT FROM 'number'
       OR p_feature_payload ->> 'kind' IS DISTINCT FROM v_request.request_payload ->> 'kind'
       OR p_feature_payload ->> 'name' IS DISTINCT FROM v_request.request_payload ->> 'name'
       OR p_feature_payload ->> 'lon' IS DISTINCT FROM v_request.request_payload ->> 'lon'
       OR p_feature_payload ->> 'lat' IS DISTINCT FROM v_request.request_payload ->> 'lat' THEN
        RAISE EXCEPTION 'Feature request approval payload is not canonical request projection'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_payload';
    END IF;
    v_feature_id := nullif(btrim(p_feature_payload ->> 'feature_id'), '');
    v_feature_kind := nullif(btrim(p_feature_payload ->> 'kind'), '');
    v_feature_name := nullif(btrim(p_feature_payload ->> 'name'), '');
    IF v_feature_id IS NULL OR v_feature_kind IS NULL OR v_feature_name IS NULL
       OR nullif(btrim(p_feature_payload ->> 'category'), '') IS NULL THEN
        RAISE EXCEPTION 'Feature request approval Feature lacks required core values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_payload';
    END IF;
    BEGIN
        v_feature_uuid := (p_feature_payload ->> 'feature_uuid')::uuid;
        v_lon := (p_feature_payload ->> 'lon')::numeric;
        v_lat := (p_feature_payload ->> 'lat')::numeric;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'Feature request approval Feature identity is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_payload';
    END;
    IF substring(v_feature_uuid::text FROM 15 FOR 1) <> '7' THEN
        RAISE EXCEPTION 'Feature request approval Feature UUID must be UUIDv7'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_feature_id, 0));
    SELECT * INTO v_key FROM feature.manual_feature_identity_key(v_feature_kind, v_feature_name, v_lon, v_lat);
    INSERT INTO feature.manual_feature_identity_claims (feature_id, feature_kind, name_key, lon_e6, lat_e6, claimed_by_command_id, claim_basis, claimed_at)
    VALUES (v_feature_uuid, v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6, p_domain_command_id, 'manual_create', clock_timestamp())
    ON CONFLICT ON CONSTRAINT uq_manual_feature_identity_claims_exact DO NOTHING RETURNING feature_id INTO v_claimed_feature_uuid;
    IF v_claimed_feature_uuid IS NULL THEN
        SELECT claim.feature_id INTO o_existing_feature_uuid FROM feature.manual_feature_identity_claims AS claim
        WHERE (claim.feature_kind, claim.name_key, claim.lon_e6, claim.lat_e6) = (v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6);
        IF o_existing_feature_uuid IS NULL THEN
            RAISE EXCEPTION 'Feature request exact winner disappeared' USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
        END IF;
        UPDATE ops.feature_requests SET status = 'exact_conflict', resolved_at = clock_timestamp(),
            resolved_by_actor = v_command.actor, resolution_command_id = p_domain_command_id,
            resolved_feature_id = o_existing_feature_uuid WHERE request_id = p_request_id;
        o_outcome := 'exact_conflict';
        RETURN;
    END IF;
    CALL feature.create_feature_with_initial_state(p_feature_payload, 'active', 'published', 'valid',
        jsonb_build_object('transition_kind','initial','reason_code','feature_request_approved',
            'principal',v_command.actor,'causation_ref','domain-command:' || p_domain_command_id::text),
        v_created_feature_id, v_created_feature_uuid, v_created_row_revision, v_created);
    IF v_created IS DISTINCT FROM true OR v_created_feature_id IS DISTINCT FROM v_feature_id
       OR v_created_feature_uuid IS DISTINCT FROM v_feature_uuid OR v_created_row_revision IS NULL OR v_created_row_revision < 1 THEN
        RAISE EXCEPTION 'Feature request approval core result does not match claim' USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    INSERT INTO feature.feature_creation_origins (feature_id, origin_kind, creation_command_id, creator_principal_id, created_by_actor, created_at, invoker_role, procedure_definer)
    VALUES (v_feature_uuid, 'manual_request', p_domain_command_id, 'feature-request.approval.v1', v_command.actor, clock_timestamp(), session_user, current_user);
    UPDATE ops.feature_requests SET status = 'approved', resolved_at = clock_timestamp(),
        resolved_by_actor = v_command.actor, resolution_command_id = p_domain_command_id,
        resolved_feature_id = v_feature_uuid WHERE request_id = p_request_id;
    o_outcome := 'created'; o_feature_id := v_created_feature_id; o_feature_uuid := v_created_feature_uuid; o_row_revision := v_created_row_revision;
END
$feature_request_approve$;

CREATE PROCEDURE feature.reject_feature_request(
    IN p_request_id uuid, IN p_reason text, IN p_domain_command_id bigint,
    OUT o_status text
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, feature, ops, x_extension
AS $feature_request_reject$
DECLARE v_command ops.domain_commands%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' OR session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_feature_request_admin_executor', 'member') THEN
        RAISE EXCEPTION 'Feature request rejection requires admin executor at READ COMMITTED' USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_request_executor';
    END IF;
    SELECT command.* INTO v_command FROM ops.domain_commands AS command WHERE command.command_id = p_domain_command_id FOR UPDATE;
    IF NOT FOUND OR v_command.operation <> 'admin.feature-request.reject.v1' OR btrim(v_command.actor) = '' OR EXISTS (SELECT 1 FROM ops.domain_command_results AS result WHERE result.command_id = p_domain_command_id) THEN
        RAISE EXCEPTION 'Feature request rejection command does not match writer' USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_command';
    END IF;
    UPDATE ops.feature_requests SET status = 'rejected', resolved_at = clock_timestamp(), resolved_by_actor = v_command.actor,
        resolution_command_id = p_domain_command_id, rejection_reason = nullif(btrim(p_reason), '')
    WHERE request_id = p_request_id AND status = 'pending' RETURNING status INTO o_status;
    IF o_status IS NULL THEN RAISE EXCEPTION 'Feature request is not pending' USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_pending'; END IF;
END
$feature_request_reject$;

CREATE FUNCTION feature.read_feature_request(p_request_id uuid)
RETURNS TABLE(request_id uuid, request_payload jsonb, status text, submitted_at timestamptz, submission_command_id bigint, resolved_at timestamptz, resolved_by_actor text, resolved_feature_id uuid, rejection_reason text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $feature_request_read$
    SELECT request_id, request_payload, status, submitted_at, submission_command_id, resolved_at, resolved_by_actor, resolved_feature_id, rejection_reason
    FROM ops.feature_requests WHERE request_id = p_request_id
$feature_request_read$;

CREATE FUNCTION feature.list_feature_requests(p_status text, p_limit integer)
RETURNS TABLE(request_id uuid, request_payload jsonb, status text, submitted_at timestamptz, submission_command_id bigint, resolved_at timestamptz, resolved_by_actor text, resolved_feature_id uuid, rejection_reason text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $feature_request_list$
    SELECT request_id, request_payload, status, submitted_at, submission_command_id, resolved_at, resolved_by_actor, resolved_feature_id, rejection_reason
    FROM ops.feature_requests
    WHERE p_status IS NULL OR status = p_status
    ORDER BY submitted_at ASC, request_id ASC
    LIMIT greatest(1, least(coalesce(p_limit, 50), 100))
$feature_request_list$;

ALTER TABLE ops.feature_requests OWNER TO ktm_feature_schema_owner;
ALTER PROCEDURE feature.submit_feature_request(uuid, jsonb, bigint) OWNER TO ktm_feature_request_procedure_owner;
ALTER PROCEDURE feature.approve_feature_request_with_initial_state(uuid, jsonb, bigint) OWNER TO ktm_feature_request_procedure_owner;
ALTER PROCEDURE feature.reject_feature_request(uuid, text, bigint) OWNER TO ktm_feature_request_procedure_owner;
ALTER FUNCTION feature.read_feature_request(uuid) OWNER TO ktm_feature_request_procedure_owner;
ALTER FUNCTION feature.list_feature_requests(text, integer) OWNER TO ktm_feature_request_procedure_owner;
SET ROLE ktm_manual_feature_procedure_owner;
GRANT EXECUTE ON FUNCTION feature.manual_feature_identity_key(text, text, numeric, numeric) TO ktm_feature_request_procedure_owner;
SET ROLE ktm_feature_state_procedure_owner;
GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) TO ktm_feature_request_procedure_owner;
SET ROLE ktm_feature_schema_owner;
GRANT SELECT, INSERT ON TABLE feature.manual_feature_identity_claims, feature.feature_creation_origins TO ktm_feature_request_procedure_owner;
GRANT SELECT, INSERT, UPDATE(status, resolved_at, resolved_by_actor, resolution_command_id, resolved_feature_id, rejection_reason) ON TABLE ops.feature_requests TO ktm_feature_request_procedure_owner;
GRANT SELECT, UPDATE(command_id) ON TABLE ops.domain_commands TO ktm_feature_request_procedure_owner;
GRANT SELECT ON TABLE ops.domain_command_results TO ktm_feature_request_procedure_owner;
SET ROLE ktm_feature_request_procedure_owner;
REVOKE ALL ON PROCEDURE feature.submit_feature_request(uuid, jsonb, bigint), feature.approve_feature_request_with_initial_state(uuid, jsonb, bigint), feature.reject_feature_request(uuid, text, bigint) FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, ktm_manual_feature_admin_executor, ktm_curation_admin_executor, ktm_feature_request_service_executor, ktm_feature_request_admin_executor;
GRANT EXECUTE ON PROCEDURE feature.submit_feature_request(uuid, jsonb, bigint) TO ktm_feature_request_service_executor;
GRANT EXECUTE ON PROCEDURE feature.approve_feature_request_with_initial_state(uuid, jsonb, bigint), feature.reject_feature_request(uuid, text, bigint) TO ktm_feature_request_admin_executor;
REVOKE ALL ON FUNCTION feature.read_feature_request(uuid) FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime;
GRANT EXECUTE ON FUNCTION feature.read_feature_request(uuid) TO ktm_feature_request_admin_executor;
REVOKE ALL ON FUNCTION feature.list_feature_requests(text, integer) FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime;
GRANT EXECUTE ON FUNCTION feature.list_feature_requests(text, integer) TO ktm_feature_request_admin_executor;
SET ROLE ktm_feature_schema_owner;
"""


def _top_level_statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    current: list[str] = []
    delimiter: str | None = None
    cursor = 0
    while cursor < len(sql):
        if sql[cursor] == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[cursor:])
            if match is not None:
                token = match.group(0)
                if delimiter is None:
                    delimiter = token
                elif delimiter == token:
                    delimiter = None
                current.append(token)
                cursor += len(token)
                continue
        if sql[cursor] == ";" and delimiter is None:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(sql[cursor])
        cursor += 1
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return tuple(statements)


def upgrade() -> None:
    bind = op.get_bind()
    for statement in _top_level_statements(_DDL_SQL):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("0230_m04_feature_request_queue is forward-only")
