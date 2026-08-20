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
