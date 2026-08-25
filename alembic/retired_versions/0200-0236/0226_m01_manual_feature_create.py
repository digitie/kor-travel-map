"""T-VN-M01 — 수동 Feature 생성 claim/origin의 물리 경계.

Revision ID: 0226_m01_manual_feature_create
Revises: 0232_tvn37d_notice_empty_range

0200/0202는 frozen role membership graph를 exact 검증한다. 따라서 이 revision은
별도 deployment phase가 0225 뒤에 M01 role을 provision한 경우에만 적용된다. #1029
rebase 중 독립 40B/C05/41S revision이 먼저 main에 착지했으므로,
이 migration은 그 최신 application head를 base로 다시 결박한다.
legacy route가 남긴 증거는 정해진 원자적 패턴만 감사 가능한 claim으로 백필한다. old
route는 0226 뒤에는 author override writer에서도 제거되며, 신규 writer만 evidence를 만든다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import op

# ruff: noqa: E501

revision: str = "0226_m01_manual_feature_create"
down_revision: str | Sequence[str] | None = "0232_tvn37d_notice_empty_range"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PRECHECK_SQL = r"""
LOCK TABLE
    ops.domain_commands,
    ops.domain_command_results,
    feature.features,
    feature.feature_state_transitions,
    ops.feature_overrides
IN SHARE MODE;

-- Permanent relation을 만들기 전에 legacy create가 남긴 4개의 증거만으로
-- candidate를 만든다. temporary relation은 Alembic transaction과 함께 사라지며,
-- 아래 validation이 실패하면 DDL/INSERT까지 전부 rollback된다.
CREATE TEMP TABLE pg_temp.m01_legacy_claim_candidates ON COMMIT DROP AS
WITH first_transition AS (
    SELECT DISTINCT ON (transition.feature_id)
        transition.transition_id,
        transition.feature_id,
        transition.feature_uuid,
        transition.from_lifecycle_state,
        transition.from_publication_state,
        transition.from_quality_state,
        transition.transition_kind,
        transition.reason_code,
        transition.principal,
        transition.causation_ref
    FROM feature.feature_state_transitions AS transition
    ORDER BY transition.feature_id, transition.transition_id
), old_command AS (
    SELECT command.command_id, command.actor, command.created_at
    FROM ops.domain_commands AS command
    WHERE command.operation = 'admin.feature.create'
), linked AS (
    SELECT
        command.command_id,
        command.actor,
        command.created_at AS claimed_at,
        transition.transition_id,
        transition.feature_id,
        transition.feature_uuid,
        transition.from_lifecycle_state,
        transition.from_publication_state,
        transition.from_quality_state,
        transition.transition_kind,
        transition.reason_code,
        transition.principal,
        transition.causation_ref,
        count(transition.transition_id) OVER (
            PARTITION BY command.command_id
        ) AS transition_count
    FROM old_command AS command
    LEFT JOIN first_transition AS transition
      ON transition.causation_ref = 'domain-command:' || command.command_id::text
), orphan_initial AS (
    -- old command 없이 남은 admin-create transition도 provenance를 추정하지
    -- 않는다. feature ID만 보이는 fail-loud candidate로 만든다.
    SELECT
        NULL::bigint AS command_id,
        NULL::text AS actor,
        NULL::timestamptz AS claimed_at,
        transition.transition_id,
        transition.feature_id,
        transition.feature_uuid,
        transition.from_lifecycle_state,
        transition.from_publication_state,
        transition.from_quality_state,
        transition.transition_kind,
        transition.reason_code,
        transition.principal,
        transition.causation_ref,
        0::bigint AS transition_count
    FROM first_transition AS transition
    WHERE transition.transition_kind = 'initial'
      AND transition.reason_code = 'admin_feature_create'
      AND NOT EXISTS (
          SELECT 1
          FROM old_command AS command
          WHERE transition.causation_ref = 'domain-command:' || command.command_id::text
      )
), input AS (
    SELECT * FROM linked
    UNION ALL
    SELECT * FROM orphan_initial
), evidence AS (
    SELECT
        input.*,
        core.kind::text AS feature_kind,
        core.feature_uuid AS core_feature_uuid,
        result.response_status,
        result.response_body,
        name_override.name_count,
        name_override.valid_name_count,
        name_override.name_value,
        coord_override.coord_count,
        coord_override.valid_coord_count,
        coord_override.coord_geometry
    FROM input
    LEFT JOIN feature.features AS core
      ON core.feature_id = input.feature_id
     AND core.feature_uuid = input.feature_uuid
    LEFT JOIN ops.domain_command_results AS result
      ON result.command_id = input.command_id
    LEFT JOIN LATERAL (
        SELECT
            count(*) AS name_count,
            count(*) FILTER (
                WHERE jsonb_typeof(override_value) = 'string'
                  AND value_geometry IS NULL
                  AND created_by = input.actor
            ) AS valid_name_count,
            (array_agg(override_value #>> '{}') FILTER (
                WHERE jsonb_typeof(override_value) = 'string'
                  AND value_geometry IS NULL
                  AND created_by = input.actor
            ))[1] AS name_value
        FROM ops.feature_overrides
        WHERE feature_id = input.feature_id
          AND command_id = input.command_id
          AND field_path = 'core.name'
    ) AS name_override ON true
    LEFT JOIN LATERAL (
        SELECT
            count(*) AS coord_count,
            count(*) FILTER (
                WHERE override_value IS NULL
                  AND created_by = input.actor
                  AND value_geometry IS NOT NULL
                  AND x_extension.st_srid(value_geometry) = 4326
                  AND x_extension.geometrytype(value_geometry) = 'POINT'
                  AND NOT x_extension.st_isempty(value_geometry)
                  AND x_extension.st_x(value_geometry) BETWEEN 124 AND 132
                  AND x_extension.st_y(value_geometry) BETWEEN 33 AND 39.5
            ) AS valid_coord_count,
            (array_agg(value_geometry) FILTER (
                WHERE override_value IS NULL
                  AND created_by = input.actor
                  AND value_geometry IS NOT NULL
                  AND x_extension.st_srid(value_geometry) = 4326
                  AND x_extension.geometrytype(value_geometry) = 'POINT'
                  AND NOT x_extension.st_isempty(value_geometry)
                  AND x_extension.st_x(value_geometry) BETWEEN 124 AND 132
                  AND x_extension.st_y(value_geometry) BETWEEN 33 AND 39.5
            ))[1] AS coord_geometry
        FROM ops.feature_overrides
        WHERE feature_id = input.feature_id
          AND command_id = input.command_id
          AND field_path = 'core.coord'
    ) AS coord_override ON true
), shaped AS (
    SELECT
        evidence.*,
        translate(
            normalize(btrim(name_value), NFC),
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
            'abcdefghijklmnopqrstuvwxyz'
        ) COLLATE "C" AS name_key,
        round((x_extension.st_x(coord_geometry)::numeric) * 1000000, 0)::integer AS lon_e6,
        round((x_extension.st_y(coord_geometry)::numeric) * 1000000, 0)::integer AS lat_e6,
        CASE
            WHEN jsonb_typeof(response_body -> 'data') = 'object'
             AND response_body #>> '{data,feature_id}' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN (response_body #>> '{data,feature_id}')::uuid
        END AS response_feature_uuid
    FROM evidence
)
SELECT
    command_id,
    feature_id,
    feature_uuid,
    feature_kind,
    name_key,
    lon_e6,
    lat_e6,
    claimed_at,
    (
        command_id IS NOT NULL
        AND transition_count = 1
        AND feature_id IS NOT NULL
        AND core_feature_uuid = feature_uuid
        AND from_lifecycle_state IS NULL
        AND from_publication_state IS NULL
        AND from_quality_state IS NULL
        AND transition_kind = 'initial'
        AND reason_code = 'admin_feature_create'
        AND causation_ref = 'domain-command:' || command_id::text
        AND causation_ref ~ '^domain-command:[1-9][0-9]*$'
        AND principal = actor
        AND feature_kind IN ('place', 'event')
        AND response_status = 200
        AND response_feature_uuid = feature_uuid
        AND substring(feature_uuid::text FROM 15 FOR 1) = '7'
        AND name_count = 1
        AND valid_name_count = 1
        AND name_key IS NOT NULL
        AND char_length(name_key) BETWEEN 1 AND 200
        AND octet_length(name_key) <= 512
        AND coord_count = 1
        AND valid_coord_count = 1
        AND lon_e6 BETWEEN 124000000 AND 132000000
        AND lat_e6 BETWEEN 33000000 AND 39500000
    ) AS is_valid
FROM shaped;

DO $m01_legacy_preflight$
DECLARE
    v_command_id bigint;
    v_feature_id text;
BEGIN
    SELECT candidate.command_id, candidate.feature_id
      INTO v_command_id, v_feature_id
      FROM pg_temp.m01_legacy_claim_candidates AS candidate
     WHERE candidate.is_valid IS NOT TRUE
     ORDER BY candidate.command_id NULLS LAST, candidate.feature_id NULLS LAST
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'M01 legacy claim preflight failed for command %, feature %',
            coalesce(v_command_id::text, '<none>'), coalesce(v_feature_id, '<none>')
            USING ERRCODE = 'P0001';
    END IF;

    SELECT candidate.command_id, candidate.feature_id
      INTO v_command_id, v_feature_id
      FROM pg_temp.m01_legacy_claim_candidates AS candidate
      JOIN (
          SELECT feature_kind, name_key, lon_e6, lat_e6
          FROM pg_temp.m01_legacy_claim_candidates
          GROUP BY feature_kind, name_key, lon_e6, lat_e6
          HAVING count(*) > 1
      ) AS duplicate
        USING (feature_kind, name_key, lon_e6, lat_e6)
     ORDER BY candidate.command_id, candidate.feature_id
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'M01 legacy claim exact collision for command %, feature %',
            v_command_id, v_feature_id
            USING ERRCODE = 'P0001';
    END IF;
END
$m01_legacy_preflight$;

CREATE TEMP TABLE pg_temp.m01_legacy_claim_preflight ON COMMIT DROP AS
SELECT
    count(*)::bigint AS candidate_count,
    encode(
        x_extension.digest(
            convert_to(
                coalesce(
                    string_agg(
                        jsonb_build_array(
                            feature_id, feature_uuid, feature_kind, name_key,
                            lon_e6, lat_e6, command_id, claimed_at
                        )::text,
                        E'\n' ORDER BY command_id
                    ),
                    ''
                ),
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    ) AS candidate_root
FROM pg_temp.m01_legacy_claim_candidates;
"""


_LEGACY_BACKFILL_SQL = r"""
INSERT INTO feature.manual_feature_identity_claims (
    feature_id, feature_kind, name_key, lon_e6, lat_e6,
    claimed_by_command_id, claim_basis, claimed_at
)
SELECT
    candidate.feature_uuid,
    candidate.feature_kind,
    candidate.name_key,
    candidate.lon_e6,
    candidate.lat_e6,
    candidate.command_id,
    'legacy_admin_route',
    candidate.claimed_at
FROM pg_temp.m01_legacy_claim_candidates AS candidate
ORDER BY candidate.command_id;

DO $m01_legacy_backfill_verify$
DECLARE
    v_expected_count bigint;
    v_expected_root text;
    v_actual_count bigint;
    v_actual_root text;
BEGIN
    SELECT candidate_count, candidate_root
      INTO v_expected_count, v_expected_root
      FROM pg_temp.m01_legacy_claim_preflight;

    SELECT
        count(*)::bigint,
        encode(
            x_extension.digest(
                convert_to(
                    coalesce(
                        string_agg(
                            jsonb_build_array(
                                candidate.feature_id,
                                claim.feature_id,
                                claim.feature_kind,
                                claim.name_key,
                                claim.lon_e6,
                                claim.lat_e6,
                                claim.claimed_by_command_id,
                                claim.claimed_at
                            )::text,
                            E'\n' ORDER BY claim.claimed_by_command_id
                        ),
                        ''
                    ),
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
      INTO v_actual_count, v_actual_root
      FROM feature.manual_feature_identity_claims AS claim
      JOIN pg_temp.m01_legacy_claim_candidates AS candidate
        ON candidate.command_id = claim.claimed_by_command_id
     WHERE claim.claim_basis = 'legacy_admin_route';

    IF v_actual_count IS DISTINCT FROM v_expected_count
       OR v_actual_root IS DISTINCT FROM v_expected_root THEN
        RAISE EXCEPTION 'M01 legacy claim backfill count/root mismatch'
            USING ERRCODE = 'P0001';
    END IF;
    IF (SELECT count(*) FROM feature.feature_creation_origins) <> 0 THEN
        RAISE EXCEPTION 'M01 legacy origin backfill is forbidden'
            USING ERRCODE = 'P0001';
    END IF;
END
$m01_legacy_backfill_verify$;
"""


_DDL_SQL = r"""
-- 0200 baseline의 field override writer는 old ``admin.feature.create``만
-- command provenance로 허용한다. frozen baseline을 바꾸지 않고, retired writer를
-- 완전히 제거한 새 versioned manual create operation만 남긴다. 예상 밖 routine body는
-- 추측해 rewrite하지 않고 migration 자체를 중단한다.
SET ROLE ktm_feature_state_procedure_owner;
DO $m01_author_operation$
DECLARE
    v_definition text;
    v_normalized_definition text;
    v_old_operation_set constant text :=
        '''admin.feature.override.author'', ''admin.feature.create'', ''admin.feature.patch''';
    v_new_operation_set constant text :=
        '''admin.feature.override.author'', ''admin.feature.create.manual-v1'', '
        '''admin.feature.patch''';
    v_old_policy constant text :=
        'IF NOT FOUND OR v_operation NOT IN ( ''admin.feature.override.author'', '
        '''admin.feature.create'', ''admin.feature.patch'' ) THEN';
    v_new_policy constant text :=
        'IF NOT FOUND OR v_operation NOT IN ( ''admin.feature.override.author'', '
        '''admin.feature.create.manual-v1'', ''admin.feature.patch'' ) THEN';
BEGIN
    SELECT pg_get_functiondef(
        'feature.author_feature_field_overrides('
        'text,bigint,text,text,bigint,jsonb,jsonb)'::regprocedure
    ) INTO v_definition;
    IF v_definition IS NULL THEN
        RAISE EXCEPTION
            'M01 cannot safely replace field override command operation policy'
            USING ERRCODE = 'P0001';
    END IF;
    v_normalized_definition := regexp_replace(v_definition, '[[:space:]]+', ' ', 'g');
    IF (length(v_definition) - length(replace(v_definition, v_old_operation_set, '')))
          / length(v_old_operation_set) <> 1
       OR (length(v_normalized_definition) - length(replace(
              v_normalized_definition, v_old_policy, ''
          ))) / length(v_old_policy) <> 1 THEN
        RAISE EXCEPTION
            'M01 cannot safely replace field override command operation policy'
            USING ERRCODE = 'P0001';
    END IF;
    v_definition := replace(v_definition, v_old_operation_set, v_new_operation_set);
    EXECUTE v_definition;
    SELECT pg_get_functiondef(
        'feature.author_feature_field_overrides('
        'text,bigint,text,text,bigint,jsonb,jsonb)'::regprocedure
    ) INTO v_definition;
    v_normalized_definition := regexp_replace(v_definition, '[[:space:]]+', ' ', 'g');
    IF position('''admin.feature.create''' IN v_definition) <> 0
       OR (length(v_normalized_definition) - length(replace(
              v_normalized_definition, v_new_policy, ''
          ))) / length(v_new_policy) <> 1 THEN
        RAISE EXCEPTION
            'M01 field override command operation replacement postcondition failed'
            USING ERRCODE = 'P0001';
    END IF;
END
$m01_author_operation$;
SET ROLE ktm_feature_schema_owner;

CREATE TABLE feature.manual_feature_identity_claims (
    feature_id uuid NOT NULL,
    feature_kind text NOT NULL,
    name_key text COLLATE "C" NOT NULL,
    lon_e6 integer NOT NULL,
    lat_e6 integer NOT NULL,
    claimed_by_command_id bigint NOT NULL,
    claim_basis text NOT NULL,
    claimed_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_manual_feature_identity_claims PRIMARY KEY (feature_id),
    CONSTRAINT uq_manual_feature_identity_claims_exact
        UNIQUE (feature_kind, name_key, lon_e6, lat_e6),
    CONSTRAINT uq_manual_feature_identity_claims_command
        UNIQUE (claimed_by_command_id),
    CONSTRAINT uq_manual_feature_identity_claims_feature_command
        UNIQUE (feature_id, claimed_by_command_id),
    CONSTRAINT fk_manual_feature_identity_claims_command
        FOREIGN KEY (claimed_by_command_id)
        REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
    CONSTRAINT ck_manual_feature_identity_claims_kind
        CHECK (feature_kind IN ('place', 'event')),
    CONSTRAINT ck_manual_feature_identity_claims_name_key
        CHECK (char_length(name_key) BETWEEN 1 AND 200 AND octet_length(name_key) <= 512),
    CONSTRAINT ck_manual_feature_identity_claims_lon_e6
        CHECK (lon_e6 BETWEEN 124000000 AND 132000000),
    CONSTRAINT ck_manual_feature_identity_claims_lat_e6
        CHECK (lat_e6 BETWEEN 33000000 AND 39500000),
    CONSTRAINT ck_manual_feature_identity_claims_basis
        CHECK (claim_basis IN ('manual_create', 'legacy_admin_route'))
);

CREATE TABLE feature.feature_creation_origins (
    feature_id uuid NOT NULL,
    origin_kind text NOT NULL,
    creation_command_id bigint NOT NULL,
    creator_principal_id text NOT NULL,
    created_by_actor text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    invoker_role text NOT NULL,
    procedure_definer text NOT NULL,
    CONSTRAINT pk_feature_creation_origins PRIMARY KEY (feature_id),
    CONSTRAINT uq_feature_creation_origins_command UNIQUE (creation_command_id),
    CONSTRAINT fk_feature_creation_origins_command
        FOREIGN KEY (creation_command_id)
        REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
    CONSTRAINT fk_feature_creation_origins_claim
        FOREIGN KEY (feature_id, creation_command_id)
        REFERENCES feature.manual_feature_identity_claims(feature_id, claimed_by_command_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_feature_creation_origins_kind
        CHECK (origin_kind = 'manual_admin'),
    CONSTRAINT ck_feature_creation_origins_principal
        CHECK (creator_principal_id = 'admin-ui-bff.manual-feature-create.v1'),
    CONSTRAINT ck_feature_creation_origins_actor
        CHECK (btrim(created_by_actor) <> '' AND char_length(created_by_actor) <= 200),
    CONSTRAINT ck_feature_creation_origins_roles
        CHECK (
            invoker_role = 'ktm_feature_api_runtime'
            AND procedure_definer = 'ktm_manual_feature_procedure_owner'
        )
);

CREATE FUNCTION feature.manual_feature_identity_key(
    p_feature_kind text,
    p_name text,
    p_lon numeric,
    p_lat numeric
)
RETURNS TABLE(feature_kind text, name_key text, lon_e6 integer, lat_e6 integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $manual_identity$
DECLARE
    v_name_key text;
BEGIN
    IF p_feature_kind NOT IN ('place', 'event') THEN
        RAISE EXCEPTION 'manual Feature kind is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_identity_claims_kind';
    END IF;
    v_name_key := translate(
        normalize(btrim(p_name), NFC),
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        'abcdefghijklmnopqrstuvwxyz'
    );
    IF v_name_key IS NULL
       OR char_length(v_name_key) NOT BETWEEN 1 AND 200
       OR octet_length(v_name_key) > 512 THEN
        RAISE EXCEPTION 'manual Feature exact name is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_identity_claims_name_key';
    END IF;
    IF p_lon IS NULL
       OR p_lat IS NULL
       OR p_lon IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
       OR p_lat IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
       OR p_lon < 124 OR p_lon > 132
       OR p_lat < 33 OR p_lat > 39.5 THEN
        RAISE EXCEPTION 'manual Feature coordinate is outside Korea'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_identity_coord_range';
    END IF;
    BEGIN
        feature_kind := p_feature_kind;
        name_key := v_name_key COLLATE "C";
        lon_e6 := round(p_lon * 1000000, 0)::integer;
        lat_e6 := round(p_lat * 1000000, 0)::integer;
    EXCEPTION WHEN numeric_value_out_of_range THEN
        RAISE EXCEPTION 'manual Feature coordinate cannot be rounded'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_identity_coord_rounding';
    END;
    RETURN NEXT;
END
$manual_identity$;

CREATE FUNCTION feature.reject_manual_feature_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $reject_mutation$
BEGIN
    IF TG_TABLE_NAME = 'manual_feature_identity_claims' THEN
        RAISE EXCEPTION 'manual Feature identity claims are append-only'
            USING ERRCODE = '42501',
                CONSTRAINT = 'ck_manual_feature_identity_claims_append_only';
    END IF;
    RAISE EXCEPTION 'Feature creation origins are append-only'
        USING ERRCODE = '42501',
            CONSTRAINT = 'ck_feature_creation_origins_append_only';
END
$reject_mutation$;

CREATE TRIGGER trg_manual_feature_identity_claims_append_only
    BEFORE UPDATE OR DELETE ON feature.manual_feature_identity_claims
    FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_feature_evidence_mutation();
CREATE TRIGGER trg_manual_feature_identity_claims_no_truncate
    BEFORE TRUNCATE ON feature.manual_feature_identity_claims
    FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_manual_feature_evidence_mutation();
CREATE TRIGGER trg_feature_creation_origins_append_only
    BEFORE UPDATE OR DELETE ON feature.feature_creation_origins
    FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_feature_evidence_mutation();
CREATE TRIGGER trg_feature_creation_origins_no_truncate
    BEFORE TRUNCATE ON feature.feature_creation_origins
    FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_manual_feature_evidence_mutation();

CREATE PROCEDURE feature.create_admin_manual_feature_with_initial_state(
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
SET search_path = pg_catalog
AS $manual_create$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
    v_feature_id text;
    v_feature_uuid uuid;
    v_feature_kind text;
    v_name text;
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
        RAISE EXCEPTION 'manual Feature writer requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_manual_feature_create_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_manual_feature_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_feature_create_provider_executor', 'member') THEN
        RAISE EXCEPTION 'manual Feature writer requires the API-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_manual_feature_create_executor';
    END IF;
    IF p_domain_command_id IS NULL OR p_domain_command_id < 1 THEN
        RAISE EXCEPTION 'manual Feature domain command is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_command';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_domain_command_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_command.operation <> 'admin.feature.create.manual-v1'
       OR btrim(v_command.actor) = ''
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_domain_command_id
       ) THEN
        RAISE EXCEPTION 'manual Feature domain command does not match open writer'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_command';
    END IF;
    IF jsonb_typeof(p_feature_payload) IS DISTINCT FROM 'object'
       OR EXISTS (
           SELECT 1
           FROM jsonb_object_keys(p_feature_payload) AS key_name(key_name)
           WHERE key_name NOT IN (
               'feature_id', 'feature_uuid', 'kind', 'name', 'category',
               'lon', 'lat', 'coord_precision_digits', 'address',
               'legal_dong_code', 'road_name_code', 'road_address_management_no',
               'admin_dong_code', 'sido_code', 'sigungu_code', 'urls',
               'marker_icon', 'marker_color', 'parent_feature_id', 'sibling_group_id',
               'raw_refs'
           )
       )
       OR jsonb_typeof(p_feature_payload -> 'feature_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'feature_uuid') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'kind') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'name') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'category') IS DISTINCT FROM 'string'
       OR jsonb_typeof(p_feature_payload -> 'lon') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_feature_payload -> 'lat') IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'manual Feature payload is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    v_feature_id := nullif(btrim(p_feature_payload ->> 'feature_id'), '');
    v_feature_kind := nullif(btrim(p_feature_payload ->> 'kind'), '');
    v_name := nullif(btrim(p_feature_payload ->> 'name'), '');
    IF v_feature_id IS NULL OR v_feature_kind IS NULL OR v_name IS NULL
       OR nullif(btrim(p_feature_payload ->> 'category'), '') IS NULL THEN
        RAISE EXCEPTION 'manual Feature payload lacks required core values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    BEGIN
        v_feature_uuid := (p_feature_payload ->> 'feature_uuid')::uuid;
        v_lon := (p_feature_payload ->> 'lon')::numeric;
        v_lat := (p_feature_payload ->> 'lat')::numeric;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'manual Feature payload has invalid identity values'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_identity_coord_rounding';
    END;
    IF substring(v_feature_uuid::text FROM 15 FOR 1) <> '7' THEN
        RAISE EXCEPTION 'manual Feature UUID must be UUIDv7'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    SELECT * INTO v_key
    FROM feature.manual_feature_identity_key(v_feature_kind, v_name, v_lon, v_lat);

    INSERT INTO feature.manual_feature_identity_claims (
        feature_id, feature_kind, name_key, lon_e6, lat_e6,
        claimed_by_command_id, claim_basis, claimed_at
    ) VALUES (
        v_feature_uuid, v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6,
        p_domain_command_id, 'manual_create', clock_timestamp()
    ) ON CONFLICT ON CONSTRAINT uq_manual_feature_identity_claims_exact DO NOTHING
    RETURNING feature_id INTO v_claimed_feature_uuid;

    IF v_claimed_feature_uuid IS NULL THEN
        SELECT claim.feature_id INTO o_existing_feature_uuid
        FROM feature.manual_feature_identity_claims AS claim
        WHERE (claim.feature_kind, claim.name_key, claim.lon_e6, claim.lat_e6)
            = (v_key.feature_kind, v_key.name_key, v_key.lon_e6, v_key.lat_e6);
        IF o_existing_feature_uuid IS NULL THEN
            RAISE EXCEPTION 'manual Feature exact winner disappeared'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
        END IF;
        o_outcome := 'exact_conflict';
        RETURN;
    END IF;

    CALL feature.create_feature_with_initial_state(
        p_feature_payload,
        'active',
        'published',
        'valid',
        jsonb_build_object(
            'transition_kind', 'initial',
            'reason_code', 'admin_feature_create',
            'principal', v_command.actor,
            'causation_ref', 'domain-command:' || p_domain_command_id::text
        ),
        v_created_feature_id,
        v_created_feature_uuid,
        v_created_row_revision,
        v_created
    );
    IF v_created IS DISTINCT FROM true
       OR v_created_feature_id IS DISTINCT FROM v_feature_id
       OR v_created_feature_uuid IS DISTINCT FROM v_feature_uuid
       OR v_created_row_revision IS NULL OR v_created_row_revision < 1 THEN
        RAISE EXCEPTION 'manual Feature core result does not match identity claim'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_create_core_identity';
    END IF;
    INSERT INTO feature.feature_creation_origins (
        feature_id, origin_kind, creation_command_id, creator_principal_id,
        created_by_actor, created_at, invoker_role, procedure_definer
    ) VALUES (
        v_feature_uuid,
        'manual_admin',
        p_domain_command_id,
        'admin-ui-bff.manual-feature-create.v1',
        v_command.actor,
        clock_timestamp(),
        session_user,
        current_user
    );
    o_outcome := 'created';
    o_feature_id := v_created_feature_id;
    o_feature_uuid := v_created_feature_uuid;
    o_row_revision := v_created_row_revision;
END
$manual_create$;

ALTER FUNCTION feature.manual_feature_identity_key(text, text, numeric, numeric)
    OWNER TO ktm_manual_feature_procedure_owner;
ALTER FUNCTION feature.reject_manual_feature_evidence_mutation()
    OWNER TO ktm_feature_audit_writer;
ALTER PROCEDURE feature.create_admin_manual_feature_with_initial_state(jsonb, bigint)
    OWNER TO ktm_manual_feature_procedure_owner;

REVOKE ALL ON TABLE feature.manual_feature_identity_claims,
    feature.feature_creation_origins
    FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime;
GRANT SELECT, INSERT ON TABLE feature.manual_feature_identity_claims,
    feature.feature_creation_origins TO ktm_manual_feature_procedure_owner;
REVOKE ALL ON FUNCTION feature.manual_feature_identity_key(text, text, numeric, numeric)
    FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime;
REVOKE ALL ON FUNCTION feature.reject_manual_feature_evidence_mutation()
    FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime,
    ktm_manual_feature_procedure_owner, ktm_manual_feature_admin_executor,
    ktm_feature_create_provider_executor;
REVOKE ALL ON PROCEDURE feature.create_admin_manual_feature_with_initial_state(jsonb, bigint)
    FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime,
    ktm_feature_create_provider_executor;
GRANT EXECUTE ON PROCEDURE feature.create_admin_manual_feature_with_initial_state(jsonb, bigint)
    TO ktm_manual_feature_admin_executor;

REVOKE ALL ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb)
    FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime;
GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb)
    TO ktm_feature_create_provider_executor, ktm_manual_feature_procedure_owner;
"""


def _top_level_statements(sql: str) -> tuple[str, ...]:
    """asyncpg prepared statement마다 최상위 SQL 하나만 전달한다.

    Alembic online은 asyncpg를 쓰므로 ``LOCK; DO ...``나 여러 ``CREATE``를
    단일 prepare에 넣을 수 없다. function/procedure body의 ``;`` 및 dollar quote는
    보존한 채 최상위 terminator만 나눈다. 이 revision의 static DDL에만 쓰며, input
    SQL parser로 일반화하지 않는다.
    """

    statements: list[str] = []
    start = 0
    index = 0
    dollar_tag: str | None = None
    quoted = False
    while index < len(sql):
        char = sql[index]
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
                continue
            index += 1
            continue
        if quoted:
            if char == "'":
                if index + 1 < len(sql) and sql[index + 1] == "'":
                    index += 2
                    continue
                quoted = False
            index += 1
            continue
        if char == "'":
            quoted = True
            index += 1
            continue
        if char == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[index:])
            if match is not None:
                dollar_tag = match.group(0)
                index += len(dollar_tag)
                continue
        if char == ";":
            statement = sql[start : index + 1].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    trailing = sql[start:].strip()
    if trailing:
        statements.append(trailing)
    return tuple(statements)


def upgrade() -> None:
    for statement in _top_level_statements(_PRECHECK_SQL):
        op.execute(statement)
    for statement in _top_level_statements(_DDL_SQL):
        op.execute(statement)
    for statement in _top_level_statements(_LEGACY_BACKFILL_SQL):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0226_m01_manual_feature_create is forward-only")
