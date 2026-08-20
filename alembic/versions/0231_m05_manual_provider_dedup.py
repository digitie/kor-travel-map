"""T-VN-M05 — 수동/provider dedup evidence와 참조 재결합 delivery 기반.

Revision ID: 0231_m05_manual_provider_dedup
Revises: 0230_m04_feature_request_queue

M05는 기존 generic dedup queue/merge writer와 완전히 분리된 append-only evidence
relation을 만든다. executable writer/ACL은 이 revision 안에서 추가하되, runtime
activation은 paired consumer cutover가 끝날 때까지 별도 flag로 막는다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import op

# ruff: noqa: E501

revision: str = "0231_m05_manual_provider_dedup"
down_revision: str | Sequence[str] | None = "0230_m04_feature_request_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DDL_SQL = r"""
ALTER TABLE feature.feature_creation_origins
    ADD CONSTRAINT uq_feature_creation_origins_feature_command
    UNIQUE (feature_id, creation_command_id);

CREATE TABLE ops.manual_provider_dedup_cases (
    case_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
    manual_feature_id text NOT NULL,
    manual_feature_uuid uuid NOT NULL,
    manual_creation_command_id bigint NOT NULL,
    manual_feature_row_revision bigint NOT NULL,
    provider_feature_id text NOT NULL,
    provider_feature_uuid uuid NOT NULL,
    provider_feature_row_revision bigint NOT NULL,
    provider_dataset_id bigint NOT NULL,
    source_entity_key text NOT NULL,
    source_record_key text NOT NULL,
    source_record_raw_payload_hash text NOT NULL,
    source_head_observed_at timestamptz NOT NULL,
    manual_feature_snapshot jsonb NOT NULL,
    provider_feature_snapshot jsonb NOT NULL,
    scorer_id text NOT NULL,
    scorer_input_sha256 text NOT NULL,
    name_score numeric(9, 8) NOT NULL,
    spatial_score numeric(9, 8) NOT NULL,
    category_score numeric(9, 8) NOT NULL,
    total_score numeric(9, 8) NOT NULL,
    distance_meters numeric(14, 3) NOT NULL,
    evidence_fingerprint text NOT NULL,
    detector_causation jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_manual_provider_dedup_cases_scorer
        CHECK (scorer_id = 'manual-provider-v1'),
    CONSTRAINT ck_manual_provider_dedup_cases_revisions
        CHECK (
            manual_feature_row_revision >= 1
            AND provider_feature_row_revision >= 1
            AND distance_meters >= 0
        ),
    CONSTRAINT ck_manual_provider_dedup_cases_scores
        CHECK (
            name_score BETWEEN 0 AND 1
            AND spatial_score BETWEEN 0 AND 1
            AND category_score BETWEEN 0 AND 1
            AND total_score BETWEEN 0 AND 1
        ),
    CONSTRAINT ck_manual_provider_dedup_cases_hashes
        CHECK (
            evidence_fingerprint ~ '^[0-9a-f]{64}$'
            AND scorer_input_sha256 ~ '^[0-9a-f]{64}$'
            AND source_record_raw_payload_hash ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_manual_provider_dedup_cases_json
        CHECK (
            jsonb_typeof(manual_feature_snapshot) = 'object'
            AND jsonb_typeof(provider_feature_snapshot) = 'object'
            AND jsonb_typeof(detector_causation) = 'object'
        ),
    CONSTRAINT fk_manual_provider_dedup_cases_manual_identity
        FOREIGN KEY (manual_feature_id, manual_feature_uuid)
        REFERENCES feature.features(feature_id, feature_uuid) ON DELETE RESTRICT,
    CONSTRAINT fk_manual_provider_dedup_cases_provider_identity
        FOREIGN KEY (provider_feature_id, provider_feature_uuid)
        REFERENCES feature.features(feature_id, feature_uuid) ON DELETE RESTRICT,
    CONSTRAINT fk_manual_provider_dedup_cases_manual_origin
        FOREIGN KEY (manual_feature_uuid, manual_creation_command_id)
        REFERENCES feature.feature_creation_origins(feature_id, creation_command_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_manual_provider_dedup_cases_manual_claim
        FOREIGN KEY (manual_feature_uuid, manual_creation_command_id)
        REFERENCES feature.manual_feature_identity_claims(feature_id, claimed_by_command_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_manual_provider_dedup_cases_provider_link
        FOREIGN KEY (provider_feature_id, source_entity_key)
        REFERENCES provider_sync.source_links(feature_id, source_entity_key)
        ON DELETE RESTRICT,
    CONSTRAINT fk_manual_provider_dedup_cases_source_record
        FOREIGN KEY (source_entity_key, source_record_key)
        REFERENCES provider_sync.source_records(source_entity_key, source_record_key)
        ON DELETE RESTRICT,
    CONSTRAINT fk_manual_provider_dedup_cases_provider_dataset
        FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets(provider_dataset_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_manual_provider_dedup_cases_manual_pending
    ON ops.manual_provider_dedup_cases (manual_feature_id, created_at DESC);
CREATE INDEX idx_manual_provider_dedup_cases_provider_pending
    ON ops.manual_provider_dedup_cases (provider_feature_id, created_at DESC);

CREATE TABLE ops.manual_provider_dedup_resolutions (
    resolution_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
    case_id uuid NOT NULL,
    decision text NOT NULL,
    command_id bigint NULL,
    actor text NULL,
    reason text NULL,
    superseded_by_case_id uuid NULL,
    detector_causation jsonb NULL,
    resolved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_manual_provider_dedup_resolutions_decision
        CHECK (decision IN ('kept', 'merged', 'manual_retired', 'superseded')),
    CONSTRAINT ck_manual_provider_dedup_resolutions_causation
        CHECK (
            (decision = 'superseded'
             AND command_id IS NULL AND actor IS NULL AND reason IS NULL
             AND superseded_by_case_id IS NOT NULL
             AND jsonb_typeof(detector_causation) = 'object')
            OR
            (decision IN ('kept', 'merged', 'manual_retired')
             AND command_id IS NOT NULL AND nullif(btrim(actor), '') IS NOT NULL
             AND nullif(btrim(reason), '') IS NOT NULL
             AND superseded_by_case_id IS NULL AND detector_causation IS NULL)
        ),
    CONSTRAINT uq_manual_provider_dedup_resolutions_case UNIQUE (case_id),
    CONSTRAINT uq_manual_provider_dedup_resolutions_command UNIQUE (command_id),
    CONSTRAINT fk_manual_provider_dedup_resolutions_case
        FOREIGN KEY (case_id)
        REFERENCES ops.manual_provider_dedup_cases(case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_manual_provider_dedup_resolutions_command
        FOREIGN KEY (command_id)
        REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
    CONSTRAINT fk_manual_provider_dedup_resolutions_superseded_case
        FOREIGN KEY (superseded_by_case_id)
        REFERENCES ops.manual_provider_dedup_cases(case_id) ON DELETE RESTRICT
);

CREATE TABLE ops.feature_reference_reconciliation_events (
    event_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
    event_sequence bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
    case_id uuid NOT NULL,
    resolution_id uuid NOT NULL,
    action text NOT NULL,
    old_feature_id text NOT NULL,
    old_feature_uuid uuid NOT NULL,
    old_feature_row_revision_before_transition bigint NOT NULL,
    replacement_feature_id text NULL,
    replacement_feature_uuid uuid NULL,
    replacement_feature_row_revision bigint NULL,
    manual_retire_transition_id bigint NOT NULL,
    manual_retire_row_revision_after_transition bigint NOT NULL,
    command_id bigint NOT NULL,
    payload_schema_version integer NOT NULL,
    event_payload jsonb NOT NULL,
    event_sha256 text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_feature_reference_reconciliation_events_action
        CHECK (action IN ('rebind', 'detach')),
    CONSTRAINT ck_feature_reference_reconciliation_events_payload
        CHECK (
            payload_schema_version = 1
            AND event_sha256 ~ '^[0-9a-f]{64}$'
            AND jsonb_typeof(event_payload) = 'object'
        ),
    CONSTRAINT ck_feature_reference_reconciliation_events_revisions
        CHECK (
            old_feature_row_revision_before_transition >= 1
            AND manual_retire_row_revision_after_transition >= 2
        ),
    CONSTRAINT ck_feature_reference_reconciliation_events_replacement
        CHECK (
            (action = 'rebind'
             AND replacement_feature_id IS NOT NULL
             AND replacement_feature_uuid IS NOT NULL
             AND replacement_feature_row_revision IS NOT NULL)
            OR
            (action = 'detach'
             AND replacement_feature_id IS NULL
             AND replacement_feature_uuid IS NULL
             AND replacement_feature_row_revision IS NULL)
        ),
    CONSTRAINT uq_feature_reference_reconciliation_events_resolution UNIQUE (resolution_id),
    CONSTRAINT uq_feature_reference_reconciliation_events_sequence UNIQUE (event_sequence),
    CONSTRAINT fk_feature_reference_reconciliation_events_resolution
        FOREIGN KEY (resolution_id)
        REFERENCES ops.manual_provider_dedup_resolutions(resolution_id) ON DELETE RESTRICT,
    CONSTRAINT fk_feature_reference_reconciliation_events_case
        FOREIGN KEY (case_id)
        REFERENCES ops.manual_provider_dedup_cases(case_id) ON DELETE RESTRICT,
    CONSTRAINT fk_feature_reference_reconciliation_events_command
        FOREIGN KEY (command_id)
        REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
    CONSTRAINT fk_feature_reference_reconciliation_events_transition
        FOREIGN KEY (manual_retire_transition_id)
        REFERENCES feature.feature_state_transitions(transition_id) ON DELETE RESTRICT,
    CONSTRAINT fk_feature_reference_reconciliation_events_old_identity
        FOREIGN KEY (old_feature_id, old_feature_uuid)
        REFERENCES feature.features(feature_id, feature_uuid) ON DELETE RESTRICT,
    CONSTRAINT fk_feature_reference_reconciliation_events_replacement_identity
        FOREIGN KEY (replacement_feature_id, replacement_feature_uuid)
        REFERENCES feature.features(feature_id, feature_uuid) ON DELETE RESTRICT
);

CREATE INDEX idx_feature_reference_reconciliation_events_sequence
    ON ops.feature_reference_reconciliation_events (event_sequence);

CREATE TABLE ops.feature_reference_reconciliation_subscriptions (
    principal_id text PRIMARY KEY,
    initial_event_sequence bigint NOT NULL,
    read_scope text NOT NULL,
    ack_scope text NOT NULL,
    activated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_ref_recon_subscriptions_initial_cursor
        CHECK (initial_event_sequence >= 0),
    CONSTRAINT ck_feature_reference_reconciliation_subscriptions_principal
        CHECK (btrim(principal_id) <> '' AND char_length(principal_id) <= 200)
);

CREATE TABLE ops.feature_reference_reconciliation_acks (
    event_id uuid NOT NULL,
    principal_id text NOT NULL,
    event_sha256 text NOT NULL,
    local_receipt_sha256 text NOT NULL,
    command_id bigint NOT NULL,
    acked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_feature_reference_reconciliation_acks PRIMARY KEY (event_id, principal_id),
    CONSTRAINT ck_feature_reference_reconciliation_acks_hashes
        CHECK (
            event_sha256 ~ '^[0-9a-f]{64}$'
            AND local_receipt_sha256 ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT uq_feature_reference_reconciliation_acks_command UNIQUE (command_id),
    CONSTRAINT fk_feature_reference_reconciliation_acks_event
        FOREIGN KEY (event_id)
        REFERENCES ops.feature_reference_reconciliation_events(event_id) ON DELETE RESTRICT,
    CONSTRAINT fk_feature_reference_reconciliation_acks_principal
        FOREIGN KEY (principal_id)
        REFERENCES ops.feature_reference_reconciliation_subscriptions(principal_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_feature_reference_reconciliation_acks_command
        FOREIGN KEY (command_id)
        REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT
);

CREATE TABLE ops.feature_reference_reconciliation_leases (
    principal_id text PRIMARY KEY,
    acked_through_sequence bigint NOT NULL,
    worker_id uuid NULL,
    lease_epoch bigint NOT NULL,
    lease_expires_at timestamptz NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_feature_reference_reconciliation_leases_cursor
        CHECK (acked_through_sequence >= 0 AND lease_epoch >= 0),
    CONSTRAINT fk_feature_reference_reconciliation_leases_principal
        FOREIGN KEY (principal_id)
        REFERENCES ops.feature_reference_reconciliation_subscriptions(principal_id)
        ON DELETE RESTRICT
);

CREATE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $m05_reject_evidence_mutation$
BEGIN
    RAISE EXCEPTION 'manual/provider dedup evidence is append-only'
        USING ERRCODE = '55000', CONSTRAINT = 'ck_manual_provider_dedup_append_only';
END
$m05_reject_evidence_mutation$;

CREATE TRIGGER trg_manual_provider_dedup_cases_append_only
    BEFORE UPDATE OR DELETE ON ops.manual_provider_dedup_cases
    FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_manual_provider_dedup_cases_no_truncate
    BEFORE TRUNCATE ON ops.manual_provider_dedup_cases
    FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_manual_provider_dedup_resolutions_append_only
    BEFORE UPDATE OR DELETE ON ops.manual_provider_dedup_resolutions
    FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_manual_provider_dedup_resolutions_no_truncate
    BEFORE TRUNCATE ON ops.manual_provider_dedup_resolutions
    FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_feature_reference_reconciliation_events_append_only
    BEFORE UPDATE OR DELETE ON ops.feature_reference_reconciliation_events
    FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_feature_reference_reconciliation_events_no_truncate
    BEFORE TRUNCATE ON ops.feature_reference_reconciliation_events
    FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_feature_reference_reconciliation_acks_append_only
    BEFORE UPDATE OR DELETE ON ops.feature_reference_reconciliation_acks
    FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_feature_reference_reconciliation_acks_no_truncate
    BEFORE TRUNCATE ON ops.feature_reference_reconciliation_acks
    FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_feature_reference_reconciliation_subscriptions_append_only
    BEFORE UPDATE OR DELETE ON ops.feature_reference_reconciliation_subscriptions
    FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();
CREATE TRIGGER trg_feature_reference_reconciliation_subscriptions_no_truncate
    BEFORE TRUNCATE ON ops.feature_reference_reconciliation_subscriptions
    FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_manual_provider_dedup_evidence_mutation();

CREATE PROCEDURE feature.record_manual_provider_dedup_candidate(
    IN p_manual_feature_id text,
    IN p_provider_feature_id text,
    IN p_scores jsonb,
    IN p_detector_causation jsonb,
    OUT o_case_id uuid,
    OUT o_outcome text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $m05_record_candidate$
DECLARE
    v_manual feature.features%ROWTYPE;
    v_provider feature.features%ROWTYPE;
    v_origin feature.feature_creation_origins%ROWTYPE;
    v_source record;
    v_manual_snapshot jsonb;
    v_provider_snapshot jsonb;
    v_input jsonb;
    v_fingerprint text;
    v_name_score numeric;
    v_spatial_score numeric;
    v_category_score numeric;
    v_total_score numeric;
    v_distance_meters numeric;
    v_scorer_input_sha256 text;
    v_primary_source_count integer;
    v_prior_case_id uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'manual/provider dedup detector requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_detector_isolation';
    END IF;
    IF session_user <> 'ktm_feature_dagster_runtime'
       OR NOT pg_has_role(session_user, 'ktm_manual_provider_dedup_detector_executor', 'member')
       OR pg_has_role(session_user, 'ktm_manual_provider_dedup_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_feature_reference_reconciliation_service_executor', 'member') THEN
        RAISE EXCEPTION 'manual/provider dedup detector requires the Dagster-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_detector_executor';
    END IF;
    IF p_manual_feature_id IS NULL OR btrim(p_manual_feature_id) = ''
       OR p_provider_feature_id IS NULL OR btrim(p_provider_feature_id) = ''
       OR p_manual_feature_id = p_provider_feature_id
       OR jsonb_typeof(p_scores) IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_detector_causation) IS DISTINCT FROM 'object'
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_scores) AS key_name(key_name)
           WHERE key_name NOT IN (
               'name_score', 'spatial_score', 'category_score', 'total_score',
               'distance_meters', 'scorer_input_sha256'
           )
       )
       OR jsonb_typeof(p_scores -> 'name_score') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'spatial_score') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'category_score') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'total_score') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'distance_meters') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'scorer_input_sha256') IS DISTINCT FROM 'string'
       OR p_scores ->> 'scorer_input_sha256' !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'manual/provider dedup candidate input is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_input';
    END IF;
    BEGIN
        v_name_score := (p_scores ->> 'name_score')::numeric;
        v_spatial_score := (p_scores ->> 'spatial_score')::numeric;
        v_category_score := (p_scores ->> 'category_score')::numeric;
        v_total_score := (p_scores ->> 'total_score')::numeric;
        v_distance_meters := (p_scores ->> 'distance_meters')::numeric;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'manual/provider dedup score is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_input';
    END;
    IF v_name_score NOT BETWEEN 0 AND 1 OR v_spatial_score NOT BETWEEN 0 AND 1
       OR v_category_score NOT BETWEEN 0 AND 1 OR v_total_score NOT BETWEEN 0 AND 1
       OR v_distance_meters < 0 THEN
        RAISE EXCEPTION 'manual/provider dedup score is outside its canonical range'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_input';
    END IF;
    v_scorer_input_sha256 := p_scores ->> 'scorer_input_sha256';

    -- event publication·decision과 같은 global fence가 case episode도 직렬화한다.
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-m05', 0));
    PERFORM 1
    FROM feature.features AS locked
    WHERE locked.feature_id IN (p_manual_feature_id, p_provider_feature_id)
    ORDER BY locked.feature_uuid
    FOR UPDATE;
    SELECT * INTO v_manual
    FROM feature.features WHERE feature_id = p_manual_feature_id FOR UPDATE;
    SELECT * INTO v_provider
    FROM feature.features WHERE feature_id = p_provider_feature_id FOR UPDATE;
    IF NOT FOUND
       OR v_manual.lifecycle_state <> 'active' OR v_manual.publication_state <> 'published'
       OR v_manual.quality_state <> 'valid' OR v_provider.lifecycle_state <> 'active'
       OR v_provider.publication_state <> 'published' OR v_provider.quality_state <> 'valid'
       OR v_manual.coord IS NULL OR v_provider.coord IS NULL THEN
        RAISE EXCEPTION 'manual/provider candidate Feature proof is not eligible'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_feature_proof';
    END IF;
    SELECT * INTO v_origin
    FROM feature.feature_creation_origins AS origin
    WHERE origin.feature_id = v_manual.feature_uuid
      AND origin.origin_kind IN ('manual_admin', 'manual_curation', 'manual_request');
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM feature.manual_feature_identity_claims AS claim
        WHERE claim.feature_id = v_manual.feature_uuid
          AND claim.claimed_by_command_id = v_origin.creation_command_id
    ) THEN
        RAISE EXCEPTION 'manual Feature lacks immutable creation evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_manual_origin';
    END IF;
    SELECT count(*) INTO v_primary_source_count
    FROM provider_sync.source_links AS link
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = link.source_entity_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS source
      ON source.source_entity_key = head.source_entity_key
     AND source.source_record_key = head.current_source_record_key
    WHERE link.feature_id = v_provider.feature_id
      AND link.source_role = 'primary';
    IF v_primary_source_count <> 1 THEN
        RAISE EXCEPTION 'provider Feature lacks one current primary source proof'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_provider_source';
    END IF;
    SELECT
        link.source_entity_key,
        head.current_source_record_key AS source_record_key,
        head.observed_at AS source_head_observed_at,
        source.raw_payload_hash AS source_record_raw_payload_hash,
        entity.provider_dataset_id
    INTO v_source
    FROM provider_sync.source_links AS link
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = link.source_entity_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS source
      ON source.source_entity_key = head.source_entity_key
     AND source.source_record_key = head.current_source_record_key
    WHERE link.feature_id = v_provider.feature_id
      AND link.source_role = 'primary'
    FOR SHARE OF link, entity, head, source;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'provider Feature lacks one current primary source proof'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_provider_source';
    END IF;

    v_manual_snapshot := jsonb_build_object(
        'feature_id', v_manual.feature_id,
        'feature_uuid', v_manual.feature_uuid,
        'row_revision', v_manual.row_revision,
        'kind', v_manual.kind,
        'name', v_manual.name,
        'category', v_manual.category,
        'lon', ST_X(v_manual.coord),
        'lat', ST_Y(v_manual.coord)
    );
    v_provider_snapshot := jsonb_build_object(
        'feature_id', v_provider.feature_id,
        'feature_uuid', v_provider.feature_uuid,
        'row_revision', v_provider.row_revision,
        'kind', v_provider.kind,
        'name', v_provider.name,
        'category', v_provider.category,
        'lon', ST_X(v_provider.coord),
        'lat', ST_Y(v_provider.coord)
    );
    v_input := jsonb_build_object(
        'manual', v_manual_snapshot,
        'manual_creation_command_id', v_origin.creation_command_id,
        'provider', v_provider_snapshot,
        'provider_dataset_id', v_source.provider_dataset_id,
        'source_entity_key', v_source.source_entity_key,
        'source_record_key', v_source.source_record_key,
        'source_record_raw_payload_hash', v_source.source_record_raw_payload_hash,
        'source_head_observed_at', v_source.source_head_observed_at,
        'scorer_id', 'manual-provider-v1',
        'scores', p_scores
    );
    v_fingerprint := encode(
        x_extension.digest(convert_to(v_input::text, 'UTF8'), 'sha256'), 'hex'
    );
    SELECT candidate.case_id INTO o_case_id
    FROM ops.manual_provider_dedup_cases AS candidate
    LEFT JOIN ops.manual_provider_dedup_resolutions AS resolution
      ON resolution.case_id = candidate.case_id
    WHERE candidate.evidence_fingerprint = v_fingerprint
      AND resolution.case_id IS NULL
    FOR SHARE OF candidate;
    IF FOUND THEN
        o_outcome := 'idempotent';
        RETURN;
    END IF;
    INSERT INTO ops.manual_provider_dedup_cases (
        manual_feature_id, manual_feature_uuid, manual_creation_command_id,
        manual_feature_row_revision, provider_feature_id, provider_feature_uuid,
        provider_feature_row_revision, provider_dataset_id, source_entity_key,
        source_record_key, source_record_raw_payload_hash, source_head_observed_at,
        manual_feature_snapshot, provider_feature_snapshot, scorer_id,
        scorer_input_sha256, name_score, spatial_score, category_score, total_score,
        distance_meters, evidence_fingerprint, detector_causation
    ) VALUES (
        v_manual.feature_id, v_manual.feature_uuid, v_origin.creation_command_id,
        v_manual.row_revision, v_provider.feature_id, v_provider.feature_uuid,
        v_provider.row_revision, v_source.provider_dataset_id, v_source.source_entity_key,
        v_source.source_record_key, v_source.source_record_raw_payload_hash,
        v_source.source_head_observed_at, v_manual_snapshot, v_provider_snapshot,
        'manual-provider-v1', v_scorer_input_sha256, v_name_score, v_spatial_score,
        v_category_score, v_total_score, v_distance_meters, v_fingerprint,
        p_detector_causation
    ) RETURNING case_id INTO o_case_id;
    FOR v_prior_case_id IN
        SELECT candidate.case_id
        FROM ops.manual_provider_dedup_cases AS candidate
        LEFT JOIN ops.manual_provider_dedup_resolutions AS resolution
          ON resolution.case_id = candidate.case_id
        WHERE candidate.manual_feature_uuid = v_manual.feature_uuid
          AND candidate.provider_feature_uuid = v_provider.feature_uuid
          AND candidate.case_id <> o_case_id
          AND resolution.case_id IS NULL
        FOR UPDATE OF candidate
    LOOP
        INSERT INTO ops.manual_provider_dedup_resolutions (
            case_id, decision, superseded_by_case_id, detector_causation
        ) VALUES (
            v_prior_case_id, 'superseded', o_case_id, p_detector_causation
        );
    END LOOP;
    o_outcome := 'created';
END
$m05_record_candidate$;

CREATE PROCEDURE feature.resolve_manual_provider_dedup_case(
    IN p_case_id uuid,
    IN p_decision text,
    IN p_expected_case_fingerprint text,
    IN p_expected_manual_row_revision bigint,
    IN p_expected_provider_row_revision bigint,
    IN p_survivor_feature_id text,
    IN p_reason text,
    IN p_actor text,
    IN p_domain_command_id bigint,
    OUT o_outcome text,
    OUT o_resolution_id uuid,
    OUT o_event_id uuid,
    OUT o_manual_feature_id text,
    OUT o_manual_feature_row_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $m05_resolve_case$
DECLARE
    v_case ops.manual_provider_dedup_cases%ROWTYPE;
    v_manual feature.features%ROWTYPE;
    v_provider feature.features%ROWTYPE;
    v_origin feature.feature_creation_origins%ROWTYPE;
    v_source record;
    v_primary_source_count integer;
    v_command ops.domain_commands%ROWTYPE;
    v_transition_feature_id text;
    v_transition_row_revision bigint;
    v_transition_id bigint;
    v_action text;
    v_payload jsonb;
    v_event_sha256 text;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'manual/provider dedup decision requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_decision_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_manual_provider_dedup_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_manual_provider_dedup_detector_executor', 'member') THEN
        RAISE EXCEPTION 'manual/provider dedup decision requires the admin-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_decision_executor';
    END IF;
    IF p_case_id IS NULL
       OR p_decision NOT IN ('kept', 'merged', 'manual_retired')
       OR p_expected_case_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_expected_manual_row_revision IS NULL OR p_expected_manual_row_revision < 1
       OR p_expected_provider_row_revision IS NULL OR p_expected_provider_row_revision < 1
       OR nullif(btrim(p_reason), '') IS NULL
       OR nullif(btrim(p_actor), '') IS NULL
       OR p_domain_command_id IS NULL OR p_domain_command_id < 1
       OR (p_decision = 'merged' AND nullif(btrim(p_survivor_feature_id), '') IS NULL)
       OR (p_decision <> 'merged' AND p_survivor_feature_id IS NOT NULL) THEN
        RAISE EXCEPTION 'manual/provider dedup decision input is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_decision_input';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_domain_command_id
    FOR SHARE;
    IF NOT FOUND
       OR v_command.actor <> p_actor
       OR v_command.operation <> 'admin.manual-provider-dedup-case.resolve.v1'
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_domain_command_id
       ) THEN
        RAISE EXCEPTION 'manual/provider dedup decision command is not open'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_decision_command';
    END IF;

    -- A sequence is allocated only while this fence is held.  Thus its commit
    -- visibility order is the same as the reconciliation action order.
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-m05', 0));
    SELECT candidate.* INTO v_case
    FROM ops.manual_provider_dedup_cases AS candidate
    WHERE candidate.case_id = p_case_id
    FOR UPDATE;
    IF NOT FOUND
       OR EXISTS (
           SELECT 1 FROM ops.manual_provider_dedup_resolutions AS resolution
           WHERE resolution.case_id = p_case_id
       )
       OR v_case.evidence_fingerprint <> p_expected_case_fingerprint
       OR v_case.manual_feature_row_revision <> p_expected_manual_row_revision
       OR v_case.provider_feature_row_revision <> p_expected_provider_row_revision THEN
        o_outcome := 'stale';
        RETURN;
    END IF;

    PERFORM 1
    FROM feature.features AS locked
    WHERE locked.feature_uuid IN (v_case.manual_feature_uuid, v_case.provider_feature_uuid)
    ORDER BY locked.feature_uuid
    FOR UPDATE;
    SELECT * INTO v_manual
    FROM feature.features
    WHERE feature_id = v_case.manual_feature_id
      AND feature_uuid = v_case.manual_feature_uuid
    FOR UPDATE;
    SELECT * INTO v_provider
    FROM feature.features
    WHERE feature_id = v_case.provider_feature_id
      AND feature_uuid = v_case.provider_feature_uuid
    FOR UPDATE;
    IF NOT FOUND
       OR v_manual.row_revision <> v_case.manual_feature_row_revision
       OR v_provider.row_revision <> v_case.provider_feature_row_revision
       OR v_manual.lifecycle_state <> 'active' OR v_manual.publication_state <> 'published'
       OR v_manual.quality_state <> 'valid' OR v_provider.lifecycle_state <> 'active'
       OR v_provider.publication_state <> 'published' OR v_provider.quality_state <> 'valid'
       OR v_manual.coord IS NULL OR v_provider.coord IS NULL THEN
        o_outcome := 'stale';
        RETURN;
    END IF;
    SELECT origin.* INTO v_origin
    FROM feature.feature_creation_origins AS origin
    WHERE origin.feature_id = v_manual.feature_uuid
      AND origin.creation_command_id = v_case.manual_creation_command_id
      AND origin.origin_kind IN ('manual_admin', 'manual_curation', 'manual_request');
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM feature.manual_feature_identity_claims AS claim
        WHERE claim.feature_id = v_manual.feature_uuid
          AND claim.claimed_by_command_id = v_origin.creation_command_id
    ) THEN
        o_outcome := 'stale';
        RETURN;
    END IF;
    SELECT count(*) INTO v_primary_source_count
    FROM provider_sync.source_links AS link
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = link.source_entity_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS source
      ON source.source_entity_key = head.source_entity_key
     AND source.source_record_key = head.current_source_record_key
    WHERE link.feature_id = v_provider.feature_id
      AND link.source_role = 'primary';
    IF v_primary_source_count <> 1 THEN
        o_outcome := 'stale';
        RETURN;
    END IF;
    SELECT entity.provider_dataset_id, link.source_entity_key,
           head.current_source_record_key AS source_record_key,
           source.raw_payload_hash, head.observed_at
    INTO v_source
    FROM provider_sync.source_links AS link
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = link.source_entity_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS source
      ON source.source_entity_key = head.source_entity_key
     AND source.source_record_key = head.current_source_record_key
    WHERE link.feature_id = v_provider.feature_id
      AND link.source_role = 'primary'
    FOR SHARE OF link, entity, head, source;
    IF NOT FOUND
       OR v_source.provider_dataset_id <> v_case.provider_dataset_id
       OR v_source.source_entity_key <> v_case.source_entity_key
       OR v_source.source_record_key <> v_case.source_record_key
       OR v_source.raw_payload_hash <> v_case.source_record_raw_payload_hash
       OR v_source.observed_at <> v_case.source_head_observed_at THEN
        o_outcome := 'stale';
        RETURN;
    END IF;
    IF p_decision = 'merged' AND p_survivor_feature_id <> v_provider.feature_id THEN
        o_outcome := 'stale';
        RETURN;
    END IF;

    INSERT INTO ops.manual_provider_dedup_resolutions (
        case_id, decision, command_id, actor, reason
    ) VALUES (
        v_case.case_id, p_decision, p_domain_command_id, p_actor, btrim(p_reason)
    ) RETURNING resolution_id INTO o_resolution_id;
    o_manual_feature_id := v_manual.feature_id;
    IF p_decision = 'kept' THEN
        o_outcome := 'kept';
        o_manual_feature_row_revision := v_manual.row_revision;
        RETURN;
    END IF;

    CALL feature.transition_admin_feature_state(
        v_manual.feature_id, NULL, NULL, NULL, v_manual.row_revision,
        'manual-provider-dedup', p_actor, 'retire',
        v_transition_feature_id, v_transition_row_revision, v_transition_id
    );
    IF v_transition_feature_id <> v_manual.feature_id
       OR v_transition_row_revision <> v_manual.row_revision + 1
       OR v_transition_id IS NULL THEN
        RAISE EXCEPTION 'manual/provider dedup retirement transition is inconsistent'
            USING ERRCODE = '55000';
    END IF;
    v_action := CASE WHEN p_decision = 'merged' THEN 'rebind' ELSE 'detach' END;
    o_event_id := x_extension.gen_random_uuid();
    v_payload := jsonb_build_object(
        'payload_schema_version', 1,
        'event_id', o_event_id,
        'case_id', v_case.case_id,
        'resolution_id', o_resolution_id,
        'action', v_action,
        'old_feature', jsonb_build_object(
            'feature_id', v_manual.feature_id,
            'feature_uuid', v_manual.feature_uuid,
            'row_revision', v_manual.row_revision
        ),
        'replacement_feature', CASE WHEN v_action = 'rebind' THEN jsonb_build_object(
            'feature_id', v_provider.feature_id,
            'feature_uuid', v_provider.feature_uuid,
            'row_revision', v_provider.row_revision
        ) ELSE NULL END,
        'manual_retire_transition_id', v_transition_id,
        'manual_retire_row_revision_after_transition', v_transition_row_revision,
        'command_id', p_domain_command_id
    );
    v_event_sha256 := encode(
        x_extension.digest(convert_to(v_payload::text, 'UTF8'), 'sha256'), 'hex'
    );
    INSERT INTO ops.feature_reference_reconciliation_events (
        event_id, case_id, resolution_id, action,
        old_feature_id, old_feature_uuid, old_feature_row_revision_before_transition,
        replacement_feature_id, replacement_feature_uuid, replacement_feature_row_revision,
        manual_retire_transition_id, manual_retire_row_revision_after_transition,
        command_id, payload_schema_version, event_payload, event_sha256
    ) VALUES (
        o_event_id, v_case.case_id, o_resolution_id, v_action,
        v_manual.feature_id, v_manual.feature_uuid, v_manual.row_revision,
        CASE WHEN v_action = 'rebind' THEN v_provider.feature_id END,
        CASE WHEN v_action = 'rebind' THEN v_provider.feature_uuid END,
        CASE WHEN v_action = 'rebind' THEN v_provider.row_revision END,
        v_transition_id, v_transition_row_revision, p_domain_command_id,
        1, v_payload, v_event_sha256
    );
    o_manual_feature_row_revision := v_transition_row_revision;
    o_outcome := p_decision;
END
$m05_resolve_case$;
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
    raise RuntimeError("T-VN-M05 evidence migration is forward-only")
