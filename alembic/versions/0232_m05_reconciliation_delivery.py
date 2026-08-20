"""T-VN-M05 delivery extension — deployed 0231 DB의 forward-only repair.

0231을 이미 적용한 database에도 admin reader, subscription activation, ACK
serialization을 안전하게 추가한다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import op

# ruff: noqa: E501

revision: str = "0232_m05_reconciliation_delivery"
down_revision: str | Sequence[str] | None = "0231_m05_manual_provider_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DDL_SQL = r"""
CREATE PROCEDURE feature.lease_feature_reference_reconciliation_event_v2(
    IN p_principal_id text,
    IN p_worker_id uuid,
    OUT o_outcome text,
    OUT o_lease_epoch bigint,
    OUT o_lease_expires_at timestamptz,
    OUT o_event_id uuid,
    OUT o_event_sequence bigint,
    OUT o_case_id uuid,
    OUT o_resolution_id uuid,
    OUT o_action text,
    OUT o_event_payload jsonb,
    OUT o_event_sha256 text,
    OUT o_occurred_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $m05_lease_event_v2$
BEGIN
    -- Activation is explicit. A valid token before provisioning is retryable,
    -- never an opaque P0002 that leaks through the HTTP boundary as a 500.
    PERFORM 1
    FROM ops.feature_reference_reconciliation_subscriptions AS subscription
    WHERE subscription.principal_id = p_principal_id
      AND subscription.read_scope = 'feature-reference-reconciliation:read'
    FOR SHARE;
    IF NOT FOUND THEN
        o_outcome := 'not_ready';
        RETURN;
    END IF;
    CALL feature.lease_feature_reference_reconciliation_event(
        p_principal_id, p_worker_id, o_outcome, o_lease_epoch,
        o_lease_expires_at, o_event_id, o_event_sequence, o_case_id,
        o_resolution_id, o_action, o_event_payload, o_event_sha256, o_occurred_at
    );
END
$m05_lease_event_v2$;

CREATE FUNCTION feature.preflight_feature_reference_reconciliation_ack_v2(
    p_principal_id text,
    p_event_id uuid,
    p_event_sha256 text,
    p_local_receipt_sha256 text
)
RETURNS TABLE(o_outcome text, o_acked_through_sequence bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $m05_ack_preflight_v2$
BEGIN
    -- Fresh-key semantic preflight and the writer hold this same lock through
    -- transaction commit.  A later request therefore re-reads the durable ACK.
    PERFORM 1
    FROM ops.feature_reference_reconciliation_leases AS lease
    WHERE lease.principal_id = p_principal_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription is absent'
            USING ERRCODE = 'P0002';
    END IF;
    RETURN QUERY
    SELECT *
    FROM feature.preflight_feature_reference_reconciliation_ack(
        p_principal_id, p_event_id, p_event_sha256, p_local_receipt_sha256
    );
END
$m05_ack_preflight_v2$;

CREATE PROCEDURE feature.ack_feature_reference_reconciliation_event_v2(
    IN p_principal_id text,
    IN p_event_id uuid,
    IN p_worker_id uuid,
    IN p_lease_epoch bigint,
    IN p_event_sha256 text,
    IN p_local_receipt_sha256 text,
    IN p_domain_command_id bigint,
    OUT o_outcome text,
    OUT o_acked_through_sequence bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $m05_ack_event_v2$
BEGIN
    -- The old 0231 writer remains callable only by this definer.  Preserve its
    -- exact validation/receipt behavior while adding the common lease lock.
    PERFORM 1
    FROM ops.feature_reference_reconciliation_leases AS lease
    WHERE lease.principal_id = p_principal_id
    FOR UPDATE;
    IF NOT FOUND THEN
        CALL feature.ack_feature_reference_reconciliation_event(
            p_principal_id, p_event_id, p_worker_id, p_lease_epoch, p_event_sha256,
            p_local_receipt_sha256, p_domain_command_id,
            o_outcome, o_acked_through_sequence
        );
        RETURN;
    END IF;
    CALL feature.ack_feature_reference_reconciliation_event(
        p_principal_id, p_event_id, p_worker_id, p_lease_epoch, p_event_sha256,
        p_local_receipt_sha256, p_domain_command_id,
        o_outcome, o_acked_through_sequence
    );
END
$m05_ack_event_v2$;

CREATE PROCEDURE feature.provision_feature_reference_reconciliation_subscription(
    IN p_principal_id text,
    IN p_initial_event_sequence bigint,
    IN p_actor text,
    IN p_domain_command_id bigint,
    OUT o_outcome text,
    OUT o_initial_event_sequence bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $m05_provision_subscription$
DECLARE
    v_max_event_sequence bigint;
    v_command ops.domain_commands%ROWTYPE;
    v_subscription ops.feature_reference_reconciliation_subscriptions%ROWTYPE;
    v_lease ops.feature_reference_reconciliation_leases%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription provision requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_subscription_provision_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(
           session_user, 'ktm_manual_provider_dedup_admin_executor', 'member'
       ) THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription provision requires the admin executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_subscription_provision_executor';
    END IF;
    IF p_principal_id <> 'service:feature-reference-reconciliation'
       OR p_initial_event_sequence IS DISTINCT FROM 0
       OR nullif(btrim(p_actor), '') IS NULL OR char_length(p_actor) > 200
       OR p_domain_command_id IS NULL OR p_domain_command_id < 1 THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription provision input is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_subscription_provision_input';
    END IF;
    -- There is exactly one paired-consumer activation receipt.  A row-level
    -- lock cannot serialize concurrent inserts while the row is absent.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('feature-reference-reconciliation-subscription', 0)
    );
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_domain_command_id
    FOR SHARE;
    IF NOT FOUND
       OR v_command.actor <> p_actor
       OR v_command.operation <> 'admin.feature-reference-reconciliation-subscription.provision.v1'
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_domain_command_id
       ) THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription provision command is not open'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_subscription_provision_command';
    END IF;
    SELECT coalesce(max(event.event_sequence), 0) INTO v_max_event_sequence
    FROM ops.feature_reference_reconciliation_events AS event;
    IF p_initial_event_sequence > v_max_event_sequence THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription cursor exceeds current event frontier'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_subscription_provision_input';
    END IF;
    SELECT subscription.* INTO v_subscription
    FROM ops.feature_reference_reconciliation_subscriptions AS subscription
    WHERE subscription.principal_id = p_principal_id
    FOR UPDATE;
    IF FOUND THEN
        SELECT lease.* INTO v_lease
        FROM ops.feature_reference_reconciliation_leases AS lease
        WHERE lease.principal_id = p_principal_id
        FOR SHARE;
        IF NOT FOUND OR v_lease.acked_through_sequence < v_subscription.initial_event_sequence THEN
            RAISE EXCEPTION 'feature reference reconciliation subscription lease state is inconsistent'
                USING ERRCODE = '55000';
        END IF;
        o_outcome := 'already_provisioned';
        o_initial_event_sequence := v_subscription.initial_event_sequence;
        RETURN;
    END IF;
    INSERT INTO ops.feature_reference_reconciliation_subscriptions (
        principal_id, initial_event_sequence, read_scope, ack_scope
    ) VALUES (
        p_principal_id, p_initial_event_sequence,
        'feature-reference-reconciliation:read',
        'feature-reference-reconciliation:ack'
    );
    INSERT INTO ops.feature_reference_reconciliation_leases (
        principal_id, acked_through_sequence, worker_id, lease_epoch, lease_expires_at
    ) VALUES (
        p_principal_id, p_initial_event_sequence, NULL, 0, NULL
    );
    o_outcome := 'provisioned';
    o_initial_event_sequence := p_initial_event_sequence;
END
$m05_provision_subscription$;

CREATE PROCEDURE feature.resolve_manual_provider_dedup_case_v2(
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
SET search_path = pg_catalog, feature, ops
AS $m05_resolve_case_v2$
BEGIN
    -- An immutable cursor-zero subscription is the paired-consumer activation
    -- receipt. No M05 resolution (including "kept") can predate it.
    PERFORM 1
    FROM ops.feature_reference_reconciliation_subscriptions AS subscription
    JOIN ops.feature_reference_reconciliation_leases AS lease
      ON lease.principal_id = subscription.principal_id
    WHERE subscription.principal_id = 'service:feature-reference-reconciliation'
      AND subscription.initial_event_sequence = 0
      AND subscription.read_scope = 'feature-reference-reconciliation:read'
      AND subscription.ack_scope = 'feature-reference-reconciliation:ack'
      AND lease.acked_through_sequence >= 0
    FOR SHARE OF subscription, lease;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription is not provisioned'
            USING ERRCODE = 'P0002';
    END IF;
    CALL feature.resolve_manual_provider_dedup_case(
        p_case_id, p_decision, p_expected_case_fingerprint,
        p_expected_manual_row_revision, p_expected_provider_row_revision,
        p_survivor_feature_id, p_reason, p_actor, p_domain_command_id,
        o_outcome, o_resolution_id, o_event_id, o_manual_feature_id,
        o_manual_feature_row_revision
    );
END
$m05_resolve_case_v2$;

-- A preview 0231 may already own these readers with the dedicated routine
-- owner.  The migration runs before the post-upgrade owner-repair phase, so
-- borrow CREATE only for this replacement and return the schema ACL to its
-- pre-repair state before continuing.  Creating as the schema owner would
-- fail on that preview because CREATE OR REPLACE may only replace a routine
-- owned by the current role.
GRANT USAGE, CREATE ON SCHEMA feature TO ktm_manual_provider_dedup_procedure_owner;
SET LOCAL ROLE ktm_manual_provider_dedup_procedure_owner;

CREATE OR REPLACE FUNCTION feature.list_manual_provider_dedup_cases(
    p_status text,
    p_after_created_at timestamptz,
    p_after_case_id uuid,
    p_limit integer
)
RETURNS TABLE(
    o_case_id uuid,
    o_status text,
    o_created_at timestamptz,
    o_evidence_fingerprint text,
    o_manual_feature jsonb,
    o_provider_feature jsonb,
    o_scores jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $m05_list_cases$
BEGIN
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(
           session_user, 'ktm_manual_provider_dedup_admin_executor', 'member'
       ) THEN
        RAISE EXCEPTION 'manual/provider dedup case read requires the admin-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_case_read_executor';
    END IF;
    IF p_status NOT IN ('pending', 'terminal') AND p_status IS NOT NULL
       OR p_limit IS NULL OR p_limit < 1 OR p_limit > 100
       OR (p_after_created_at IS NULL) <> (p_after_case_id IS NULL) THEN
        RAISE EXCEPTION 'manual/provider dedup case list input is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_case_read_input';
    END IF;

    RETURN QUERY
    SELECT
        candidate.case_id,
        CASE WHEN resolution.case_id IS NULL THEN 'pending' ELSE 'terminal' END,
        candidate.created_at,
        candidate.evidence_fingerprint,
        jsonb_build_object(
            'feature_id', candidate.manual_feature_id,
            'feature_uuid', candidate.manual_feature_uuid,
            'row_revision', candidate.manual_feature_row_revision,
            'snapshot', candidate.manual_feature_snapshot
        ),
        jsonb_build_object(
            'feature_id', candidate.provider_feature_id,
            'feature_uuid', candidate.provider_feature_uuid,
            'row_revision', candidate.provider_feature_row_revision,
            'snapshot', candidate.provider_feature_snapshot
        ),
        jsonb_build_object(
            'scorer_id', candidate.scorer_id,
            'scorer_input_sha256', candidate.scorer_input_sha256,
            'name_score', candidate.name_score,
            'spatial_score', candidate.spatial_score,
            'category_score', candidate.category_score,
            'total_score', candidate.total_score,
            'distance_meters', candidate.distance_meters
        )
    FROM ops.manual_provider_dedup_cases AS candidate
    LEFT JOIN ops.manual_provider_dedup_resolutions AS resolution
      ON resolution.case_id = candidate.case_id
    WHERE (
        (p_status IS NULL)
        OR (p_status = 'pending' AND resolution.case_id IS NULL)
        OR (p_status = 'terminal' AND resolution.case_id IS NOT NULL)
    )
      AND (
          p_after_created_at IS NULL
          OR (candidate.created_at, candidate.case_id) < (p_after_created_at, p_after_case_id)
      )
    ORDER BY candidate.created_at DESC, candidate.case_id DESC
    LIMIT p_limit;
END
$m05_list_cases$;

CREATE OR REPLACE FUNCTION feature.read_manual_provider_dedup_case(p_case_id uuid)
RETURNS TABLE(o_data jsonb)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, ops
AS $m05_read_case$
BEGIN
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(
           session_user, 'ktm_manual_provider_dedup_admin_executor', 'member'
       ) THEN
        RAISE EXCEPTION 'manual/provider dedup case read requires the admin-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_case_read_executor';
    END IF;
    IF p_case_id IS NULL THEN
        RAISE EXCEPTION 'manual/provider dedup case id is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_case_read_input';
    END IF;

    RETURN QUERY
    SELECT jsonb_build_object(
        'case_id', candidate.case_id,
        'status', CASE WHEN resolution.case_id IS NULL THEN 'pending' ELSE 'terminal' END,
        'created_at', candidate.created_at,
        'evidence_fingerprint', candidate.evidence_fingerprint,
        'manual_feature', jsonb_build_object(
            'feature_id', candidate.manual_feature_id,
            'feature_uuid', candidate.manual_feature_uuid,
            'row_revision', candidate.manual_feature_row_revision,
            'creation_command_id', candidate.manual_creation_command_id,
            'snapshot', candidate.manual_feature_snapshot
        ),
        'provider_feature', jsonb_build_object(
            'feature_id', candidate.provider_feature_id,
            'feature_uuid', candidate.provider_feature_uuid,
            'row_revision', candidate.provider_feature_row_revision,
            'dataset_id', candidate.provider_dataset_id,
            'source_entity_key', candidate.source_entity_key,
            'source_record_key', candidate.source_record_key,
            'source_record_raw_payload_hash', candidate.source_record_raw_payload_hash,
            'source_head_observed_at', candidate.source_head_observed_at,
            'snapshot', candidate.provider_feature_snapshot
        ),
        'scores', jsonb_build_object(
            'scorer_id', candidate.scorer_id,
            'scorer_input_sha256', candidate.scorer_input_sha256,
            'name_score', candidate.name_score,
            'spatial_score', candidate.spatial_score,
            'category_score', candidate.category_score,
            'total_score', candidate.total_score,
            'distance_meters', candidate.distance_meters,
            'detector_causation', candidate.detector_causation
        ),
        'resolution', CASE WHEN resolution.case_id IS NULL THEN NULL ELSE jsonb_build_object(
            'resolution_id', resolution.resolution_id,
            'decision', resolution.decision,
            'command_id', resolution.command_id,
            'actor', resolution.actor,
            'reason', resolution.reason,
            'superseded_by_case_id', resolution.superseded_by_case_id,
            'resolved_at', resolution.resolved_at
        ) END,
        'event', event.event_payload,
        'subscriptions', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'principal_id', subscription.principal_id,
                'initial_event_sequence', subscription.initial_event_sequence,
                'acked_through_sequence', lease.acked_through_sequence,
                'lease_epoch', lease.lease_epoch,
                'lease_expires_at', lease.lease_expires_at,
                'oldest_unacked_at', (
                    SELECT min(unacked_event.occurred_at)
                    FROM ops.feature_reference_reconciliation_events AS unacked_event
                    WHERE unacked_event.event_sequence > lease.acked_through_sequence
                ),
                'ack', CASE WHEN ack.event_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'event_id', ack.event_id,
                    'event_sha256', ack.event_sha256,
                    'local_receipt_sha256', ack.local_receipt_sha256,
                    'command_id', ack.command_id,
                    'acked_at', ack.acked_at
                ) END
            ) ORDER BY subscription.principal_id)
            FROM ops.feature_reference_reconciliation_subscriptions AS subscription
            JOIN ops.feature_reference_reconciliation_leases AS lease
              ON lease.principal_id = subscription.principal_id
            LEFT JOIN ops.feature_reference_reconciliation_acks AS ack
              ON ack.principal_id = subscription.principal_id
             AND ack.event_id = event.event_id
        ), '[]'::jsonb)
    )
    FROM ops.manual_provider_dedup_cases AS candidate
    LEFT JOIN ops.manual_provider_dedup_resolutions AS resolution
      ON resolution.case_id = candidate.case_id
    LEFT JOIN ops.feature_reference_reconciliation_events AS event
      ON event.resolution_id = resolution.resolution_id
    WHERE candidate.case_id = p_case_id;
END
$m05_read_case$;

RESET ROLE;
SET LOCAL ROLE ktm_feature_schema_owner;
REVOKE CREATE ON SCHEMA feature FROM ktm_manual_provider_dedup_procedure_owner;
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
    raise RuntimeError("0232_m05_reconciliation_delivery is forward-only")
