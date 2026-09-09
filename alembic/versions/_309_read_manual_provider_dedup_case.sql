-- 이 사이드카는 자기 역할 창을 스스로 연다 — 소유자는 alembic/head-schema.sql이
-- 정본이다. 바깥에서 `SET ROLE`로 묶으면 순서에 결박되고, 자기 창을 가진 사이드카가
-- 끝에서 스키마 소유자로 되돌리는 순간 뒤따르는 파일이 엉뚱한 롤로 실행된다.
-- 이 파일은 소유권을 바꾸지 않으므로 `ALTER ... OWNER TO`가 없다. 그래도 `CREATE OR
-- REPLACE`와 `DROP`은 소유자만 할 수 있고 롤은 NOINHERIT라 창이 필요하다.
SET ROLE ktm_manual_provider_dedup_procedure_owner;

CREATE OR REPLACE FUNCTION feature.read_manual_provider_dedup_case(p_case_id uuid) RETURNS TABLE(o_data jsonb)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
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
            'feature_uuid', CAST(candidate.manual_feature_id AS text),
            'row_revision', candidate.manual_feature_row_revision,
            'creation_command_id', candidate.manual_creation_command_id,
            'snapshot', candidate.manual_feature_snapshot
        ),
        'provider_feature', jsonb_build_object(
            'feature_id', candidate.provider_feature_id,
            'feature_uuid', CAST(candidate.provider_feature_id AS text),
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
$$;

SET ROLE ktm_feature_schema_owner;
