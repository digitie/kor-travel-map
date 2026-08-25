"""``test_alembic_upgrade`` — `alembic upgrade head` 적용 후 schema 검증.

PR#28 (Sprint 2 prep) — Alembic 첫 revision (0001 + 0002)이 testcontainers
PostGIS에서 깨끗하게 적용되는지 확인 + 4 schema / 3 extension / 4 신규 테이블
존재 확인.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.infra.alembic_exclusions import (
    UNCOMPARED_INDEXES,
    UNMAPPED_APP_TABLES,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


pytestmark = pytest.mark.integration


_UNMAPPED_TABLE_COLUMNS: dict[
    tuple[str, str],
    set[tuple[str, str, bool]],
] = {
    ("feature", "feature_weather_values"): {
        ("weather_value_key", "text", True),
        ("feature_id", "text", True),
        ("provider_dataset_id", "bigint", True),
        ("weather_domain", "text", True),
        ("forecast_style", "text", True),
        ("timeline_bucket", "text", False),
        ("metric_key", "text", True),
        ("metric_name", "text", False),
        ("source_metric_key", "text", False),
        ("source_metric_name", "text", False),
        ("value_number", "numeric(14,4)", False),
        ("value_text", "text", False),
        ("unit", "text", False),
        ("severity", "text", False),
        ("issued_at", "timestamp with time zone", False),
        ("valid_at", "timestamp with time zone", False),
        ("valid_during", "tstzrange", False),
        ("observed_at", "timestamp with time zone", False),
        ("target_at", "timestamp with time zone", True),
        ("known_at", "timestamp with time zone", True),
        ("normalization_version", "text", False),
        ("payload", "jsonb", True),
        ("source_entity_key", "text", True),
        ("source_record_key", "text", True),
        ("created_at", "timestamp with time zone", True),
    },
    ("feature", "feature_price_values"): {
        ("price_value_key", "text", True),
        ("feature_id", "text", True),
        ("provider_dataset_id", "bigint", True),
        ("price_domain", "text", True),
        ("product_key", "text", True),
        ("product_name", "text", False),
        ("source_product_key", "text", False),
        ("source_product_name", "text", False),
        ("observed_at", "timestamp with time zone", True),
        ("known_at", "timestamp with time zone", True),
        ("value_number", "numeric(14,4)", True),
        ("unit", "text", True),
        ("normalization_version", "text", False),
        ("payload", "jsonb", True),
        ("source_entity_key", "text", True),
        ("source_record_key", "text", True),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "current_summary_runs"): {
        ("summary_run_id", "bigint", True),
        ("projection_kind", "text", True),
        ("run_kind", "text", True),
        ("status", "text", True),
        ("started_at", "timestamp with time zone", True),
        ("finished_at", "timestamp with time zone", False),
        ("input_count", "bigint", True),
        ("inserted_count", "bigint", True),
        ("updated_count", "bigint", True),
        ("deleted_count", "bigint", True),
        ("scope", "jsonb", True),
        ("detail", "jsonb", True),
    },
    ("feature", "current_weather_summary"): {
        ("feature_id", "text", True),
        ("provider_dataset_id", "bigint", True),
        ("weather_domain", "text", True),
        ("forecast_style", "text", True),
        ("metric_key", "text", True),
        ("weather_value_key", "text", True),
        ("summary_run_id", "bigint", True),
        ("selected_at", "timestamp with time zone", True),
        ("refresh_after", "timestamp with time zone", True),
        ("projection_kind", "text", True),
        ("receipt_status", "text", True),
    },
    ("feature", "current_price_summary"): {
        ("feature_id", "text", True),
        ("provider_dataset_id", "bigint", True),
        ("price_domain", "text", True),
        ("product_key", "text", True),
        ("price_value_key", "text", True),
        ("summary_run_id", "bigint", True),
        ("projection_kind", "text", True),
        ("receipt_status", "text", True),
    },
    ("ops", "system_log"): {
        ("system_log_id", "uuid", True),
        ("level", "text", True),
        ("source", "text", True),
        ("event", "text", True),
        ("message", "text", True),
        ("detail", "jsonb", True),
        ("request_id", "text", False),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "api_call_log"): {
        ("api_call_log_id", "uuid", True),
        ("method", "text", True),
        ("path", "text", True),
        ("status_code", "integer", True),
        ("duration_ms", "integer", True),
        ("request_id", "text", False),
        ("error_code", "text", False),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "public_api_keys"): {
        ("public_api_key_id", "uuid", True),
        ("key_hash", "text", True),
        ("key_hint", "text", True),
        ("label", "text", False),
        ("state", "text", True),
        ("created_at", "timestamp with time zone", True),
        ("created_by", "text", False),
        ("revoked_at", "timestamp with time zone", False),
        ("revoked_by", "text", False),
    },
    ("ops", "admin_auth_events"): {
        ("auth_event_id", "uuid", True),
        ("event_type", "text", True),
        ("outcome", "text", True),
        ("attempted_username", "text", False),
        ("actor", "text", False),
        ("reason", "text", False),
        ("next_path", "text", False),
        ("client_ip", "text", False),
        ("user_agent", "text", False),
        ("request_id", "text", False),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "ops_live_ticket_claims"): {
        ("nonce_hash", "bytea", True),
        ("actor", "text", True),
        ("expires_at", "timestamp with time zone", True),
        ("claimed_at", "timestamp with time zone", True),
    },
    ("ops", "ops_live_topic_revisions"): {
        ("topic", "text", True),
        ("revision", "bigint", True),
        ("updated_at", "timestamp with time zone", True),
    },
    # 0103 legacy freeze replay의 fail-closed preflight 결과. 애플리케이션이 읽지
    # 않는 일회성 감사 기록이라 ORM에 매핑하지 않고, 구조는 여기서 고정한다.
    ("ops", "tvn36_legacy_freeze_preflight_manifest"): {
        ("feature_id", "text", True),
        ("request_id", "uuid", False),
        ("violation_code", "text", True),
        ("detail", "text", True),
        ("recorded_at", "timestamp with time zone", True),
    },
    ("feature", "curation_import_plans"): {
        ("import_plan_id", "uuid", True),
        ("preview_command_id", "bigint", True),
        ("actor", "text", True),
        ("content_sha256", "text", True),
        ("provenance_sha256", "text", False),
        ("plan_sha256", "text", True),
        ("summary", "jsonb", True),
        ("row_count", "integer", True),
        ("revision_count", "integer", True),
        ("expires_at", "timestamp with time zone", True),
        ("created_at", "timestamp with time zone", True),
    },
    ("feature", "curation_import_plan_rows"): {
        ("import_plan_id", "uuid", True),
        ("row_number", "integer", True),
        ("normalized_payload", "jsonb", False),
        ("response_payload", "jsonb", True),
    },
    ("feature", "curation_import_plan_revisions"): {
        ("import_plan_id", "uuid", True),
        ("resource_kind", "text", True),
        ("resource_key", "text", True),
        ("expected_revision", "bigint", False),
    },
    ("ops", "curation_catalog_command_effects"): {
        ("command_id", "bigint", True),
        ("operation", "text", True),
        ("resource_kind", "text", True),
        ("resource_id", "uuid", True),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "curation_concierge_legacy_owner_manifest"): {
        ("entity_kind", "text", True),
        ("entity_id", "uuid", True),
        ("before_row_revision", "bigint", True),
        ("before_input_hash", "text", True),
        ("captured_at", "timestamp with time zone", True),
    },
    ("ops", "curation_import_collection_effects"): {
        ("command_id", "bigint", True),
        ("collection_id", "uuid", True),
        ("operation", "text", True),
        ("created", "boolean", True),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "curation_import_collection_touches"): {
        ("command_id", "bigint", True),
        ("collection_id", "uuid", True),
        ("touched_at", "timestamp with time zone", True),
    },
    ("ops", "curation_import_plan_claims"): {
        ("import_plan_id", "uuid", True),
        ("command_id", "bigint", True),
        ("plan_sha256", "text", True),
        ("claimed_at", "timestamp with time zone", True),
    },
    ("ops", "curation_import_plan_commits"): {
        ("import_plan_id", "uuid", True),
        ("command_id", "bigint", True),
        ("import_batch_id", "uuid", True),
        ("result_payload", "jsonb", True),
        ("committed_at", "timestamp with time zone", True),
    },
    ("ops", "curation_provider_root_receipts"): {
        ("root_job_id", "uuid", True),
        ("child_receipt_count", "bigint", True),
        ("child_receipt_set_hash", "text", True),
        ("generation_count", "bigint", True),
        ("generation_set_hash", "text", True),
        ("completed_at", "timestamp with time zone", True),
    },
    ("ops", "curation_provider_snapshot_receipts"): {
        ("source_job_id", "uuid", True),
        ("root_job_id", "uuid", True),
        ("provider_dataset_id", "bigint", True),
        ("sync_scope", "text", True),
        ("operation_key", "text", True),
        ("observed_at", "timestamp with time zone", True),
        ("source_entity_count", "bigint", True),
        ("input_member_count", "bigint", True),
        ("last_source_modified_at", "date", False),
        ("source_input_set_hash", "text", True),
    },
    ("ops", "curation_source_observation_receipts"): {
        ("source_id", "uuid", True),
        ("import_job_id", "uuid", True),
        ("observed_at", "timestamp with time zone", True),
        ("source_revision", "bigint", True),
        ("observation_revision", "bigint", True),
        ("row_count", "integer", True),
        ("last_source_modified_at", "date", False),
        ("source_input_set_hash", "text", True),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "application_schema_operation_receipts"): {
        ("operation_id", "uuid", True),
        ("operation", "text", True),
        ("result_schema", "text", True),
        ("result_sha256", "text", True),
        ("map_candidate_commit", "text", True),
        ("map_candidate_image_id", "text", True),
        ("postgres_image_id", "text", True),
        ("writer_fence_receipt_sha256", "text", True),
        ("journal_sha256", "text", True),
        ("journal_generation", "bigint", True),
        ("destination_head", "text", True),
        ("database_name", "text", True),
        ("database_oid", "bigint", True),
        ("database_owner", "text", True),
        ("postgres_system_identifier", "text", True),
        ("result_payload", "jsonb", True),
        ("committed_at", "timestamp with time zone", True),
    },
}

_UNMAPPED_TABLE_CONSTRAINTS: dict[tuple[str, str], set[tuple[str, str]]] = {
    ("feature", "feature_weather_values"): {
        ("feature_weather_values_pkey", "p"),
        ("fk_weather_value_source_lineage", "f"),
        ("fk_weather_value_source_dataset", "f"),
        ("ck_weather_value_present", "c"),
        ("ck_weather_value_valid_during_not_empty", "c"),
        ("ck_weather_value_payload_object", "c"),
        ("ck_weather_value_bitemporal_order", "c"),
        ("uq_weather_value_identity", "u"),
    },
    ("feature", "feature_price_values"): {
        ("feature_price_values_pkey", "p"),
        ("fk_price_value_source_lineage", "f"),
        ("fk_price_value_source_dataset", "f"),
        ("ck_price_value_nonnegative", "c"),
        ("ck_price_value_payload_object", "c"),
        ("uq_price_value_identity", "u"),
    },
    ("ops", "current_summary_runs"): {
        ("current_summary_runs_pkey", "p"),
        ("uq_current_summary_runs_receipt_state", "u"),
        ("ck_current_summary_runs_projection_kind", "c"),
        ("ck_current_summary_runs_run_kind", "c"),
        ("ck_current_summary_runs_status", "c"),
        ("ck_current_summary_runs_finished_at", "c"),
        ("ck_current_summary_runs_counts_nonnegative", "c"),
        ("ck_current_summary_runs_scope_object", "c"),
        ("ck_current_summary_runs_detail_object", "c"),
    },
    ("feature", "current_weather_summary"): {
        ("pk_current_weather_summary", "p"),
        ("fk_current_weather_summary_fact", "f"),
        ("fk_current_weather_summary_successful_run", "f"),
        ("ck_current_weather_summary_projection_kind", "c"),
        ("ck_current_weather_summary_receipt_status", "c"),
        ("ck_current_weather_summary_refresh_after", "c"),
    },
    ("feature", "current_price_summary"): {
        ("pk_current_price_summary", "p"),
        ("fk_current_price_summary_fact", "f"),
        ("fk_current_price_summary_successful_run", "f"),
        ("ck_current_price_summary_projection_kind", "c"),
        ("ck_current_price_summary_receipt_status", "c"),
    },
    ("ops", "system_log"): {
        ("system_log_pkey", "p"),
        ("ck_system_log_level", "c"),
    },
    ("ops", "api_call_log"): {("api_call_log_pkey", "p")},
    ("ops", "public_api_keys"): {
        ("public_api_keys_pkey", "p"),
        ("public_api_keys_key_hash_key", "u"),
        ("public_api_keys_key_hash_check", "c"),
        ("public_api_keys_key_hint_check", "c"),
        ("public_api_keys_label_check", "c"),
        ("public_api_keys_state_check", "c"),
        ("public_api_keys_check", "c"),
    },
    ("ops", "admin_auth_events"): {
        ("admin_auth_events_pkey", "p"),
        ("admin_auth_events_event_type_check", "c"),
        ("admin_auth_events_outcome_check", "c"),
        ("admin_auth_events_attempted_username_check", "c"),
        ("admin_auth_events_actor_check", "c"),
        ("admin_auth_events_reason_check", "c"),
        ("admin_auth_events_next_path_check", "c"),
        ("admin_auth_events_client_ip_check", "c"),
        ("admin_auth_events_user_agent_check", "c"),
        ("admin_auth_events_request_id_check", "c"),
    },
    ("ops", "ops_live_ticket_claims"): {
        ("pk_ops_live_ticket_claims", "p"),
        ("ck_ops_live_ticket_claims_nonce_hash_length", "c"),
        ("ck_ops_live_ticket_claims_actor_length", "c"),
    },
    ("ops", "ops_live_topic_revisions"): {
        ("pk_ops_live_topic_revisions", "p"),
        ("ck_ops_live_topic_revisions_topic", "c"),
        ("ck_ops_live_topic_revisions_revision", "c"),
    },
    ("ops", "tvn36_legacy_freeze_preflight_manifest"): {
        ("tvn36_legacy_freeze_preflight_manifest_pkey", "p"),
    },
    ("feature", "curation_import_plans"): {
        ("curation_import_plans_pkey", "p"),
        ("curation_import_plans_preview_command_id_fkey", "f"),
        ("curation_import_plans_preview_command_id_key", "u"),
        ("curation_import_plans_plan_sha256_key", "u"),
        ("curation_import_plans_actor_check", "c"),
        ("curation_import_plans_content_sha256_check", "c"),
        ("curation_import_plans_provenance_sha256_check", "c"),
        ("curation_import_plans_plan_sha256_check", "c"),
        ("curation_import_plans_summary_check", "c"),
        ("curation_import_plans_row_count_check", "c"),
        ("curation_import_plans_revision_count_check", "c"),
        ("curation_import_plans_check", "c"),
    },
    ("feature", "curation_import_plan_rows"): {
        ("curation_import_plan_rows_pkey", "p"),
        ("curation_import_plan_rows_import_plan_id_fkey", "f"),
        ("curation_import_plan_rows_row_number_check", "c"),
        ("curation_import_plan_rows_normalized_payload_check", "c"),
        ("curation_import_plan_rows_response_payload_check", "c"),
    },
    ("feature", "curation_import_plan_revisions"): {
        ("curation_import_plan_revisions_pkey", "p"),
        ("curation_import_plan_revisions_import_plan_id_fkey", "f"),
        ("curation_import_plan_revisions_resource_kind_check", "c"),
        ("curation_import_plan_revisions_resource_key_check", "c"),
        ("curation_import_plan_revisions_expected_revision_check", "c"),
    },
    ("ops", "curation_catalog_command_effects"): {
        ("curation_catalog_command_effects_pkey", "p"),
        ("curation_catalog_command_effects_command_id_fkey", "f"),
        ("curation_catalog_command_effects_resource_kind_check", "c"),
    },
    ("ops", "curation_concierge_legacy_owner_manifest"): {
        ("curation_concierge_legacy_owner_manifest_pkey", "p"),
        ("curation_concierge_legacy_owner_manifest_entity_kind_check", "c"),
        ("curation_concierge_legacy_owner_manif_before_row_revision_check", "c"),
        ("curation_concierge_legacy_owner_manifes_before_input_hash_check", "c"),
    },
    ("ops", "curation_import_collection_effects"): {
        ("curation_import_collection_effects_pkey", "p"),
        ("curation_import_collection_effects_command_id_fkey", "f"),
        ("curation_import_collection_effects_collection_id_fkey", "f"),
        ("curation_import_collection_effects_operation_check", "c"),
    },
    ("ops", "curation_import_collection_touches"): {
        ("curation_import_collection_touches_pkey", "p"),
        ("curation_import_collection_touche_command_id_collection_id_fkey", "f"),
    },
    ("ops", "curation_import_plan_claims"): {
        ("curation_import_plan_claims_pkey", "p"),
        ("curation_import_plan_claims_import_plan_id_fkey", "f"),
        ("curation_import_plan_claims_command_id_fkey", "f"),
        ("curation_import_plan_claims_command_id_key", "u"),
        ("curation_import_plan_claims_import_plan_id_command_id_key", "u"),
        ("curation_import_plan_claims_plan_sha256_check", "c"),
    },
    ("ops", "curation_import_plan_commits"): {
        ("curation_import_plan_commits_pkey", "p"),
        ("curation_import_plan_commits_import_plan_id_fkey", "f"),
        ("curation_import_plan_commits_command_id_fkey", "f"),
        ("curation_import_plan_commits_import_batch_id_fkey", "f"),
        ("curation_import_plan_commits_import_plan_id_command_id_fkey", "f"),
        ("curation_import_plan_commits_import_batch_id_command_id_fkey", "f"),
        ("curation_import_plan_commits_command_id_key", "u"),
        ("curation_import_plan_commits_import_batch_id_key", "u"),
        ("curation_import_plan_commits_result_payload_check", "c"),
    },
    ("ops", "curation_provider_root_receipts"): {
        ("curation_provider_root_receipts_pkey", "p"),
        ("curation_provider_root_receipts_root_job_id_fkey", "f"),
        ("curation_provider_root_receipts_child_receipt_count_check", "c"),
        ("curation_provider_root_receipts_child_receipt_set_hash_check", "c"),
        ("curation_provider_root_receipts_generation_count_check", "c"),
        ("curation_provider_root_receipts_generation_set_hash_check", "c"),
    },
    ("ops", "curation_provider_snapshot_receipts"): {
        ("curation_provider_snapshot_receipts_pkey", "p"),
        ("curation_provider_snapshot_receipts_source_job_id_fkey", "f"),
        ("curation_provider_snapshot_receipts_root_job_id_fkey", "f"),
        ("curation_provider_snapshot_receipts_provider_dataset_id_fkey", "f"),
        ("curation_provider_snapshot_re_root_job_id_provider_dataset__key", "u"),
        ("curation_provider_snapshot_receipts_source_entity_count_check", "c"),
        ("curation_provider_snapshot_receipts_input_member_count_check", "c"),
        ("curation_provider_snapshot_receipts_source_input_set_hash_check", "c"),
    },
    ("ops", "curation_source_observation_receipts"): {
        ("curation_source_observation_receipts_pkey", "p"),
        ("curation_source_observation_receipts_source_id_fkey", "f"),
        ("curation_source_observation_receipts_import_job_id_fkey", "f"),
        ("curation_source_observation_receipts_source_revision_check", "c"),
        ("curation_source_observation_receipts_observation_revision_check", "c"),
        ("curation_source_observation_receipts_row_count_check", "c"),
        ("curation_source_observation_receipt_source_input_set_hash_check", "c"),
    },
    ("ops", "application_schema_operation_receipts"): {
        ("pk_application_schema_operation_receipts", "p"),
        ("ck_application_schema_operation_receipts_operation", "c"),
        ("ck_application_schema_operation_receipts_result_schema", "c"),
        ("ck_application_schema_operation_receipts_result_sha256", "c"),
        ("ck_application_schema_operation_receipts_map_commit", "c"),
        ("ck_application_schema_operation_receipts_map_image", "c"),
        ("ck_application_schema_operation_receipts_postgres_image", "c"),
        ("ck_application_schema_operation_receipts_fence", "c"),
        ("ck_application_schema_operation_receipts_journal", "c"),
        ("ck_application_schema_operation_receipts_generation", "c"),
        ("ck_application_schema_operation_receipts_head", "c"),
        ("ck_application_schema_operation_receipts_database_name", "c"),
        ("ck_application_schema_operation_receipts_database_oid", "c"),
        ("ck_application_schema_operation_receipts_database_owner", "c"),
        ("ck_application_schema_operation_receipts_system_identifier", "c"),
        ("ck_application_schema_operation_receipts_payload", "c"),
    },
}

_UNMAPPED_TABLE_INDEXES: dict[tuple[str, str], set[str]] = {
    ("feature", "feature_weather_values"): {
        "feature_weather_values_pkey",
        "uq_weather_value_identity",
        "uq_weather_value_summary_reference",
        "idx_weather_values_feature_target_known",
    },
    ("feature", "feature_price_values"): {
        "feature_price_values_pkey",
        "uq_price_value_identity",
        "idx_price_values_feature_observed_identity",
        "uq_price_value_summary_reference",
    },
    ("ops", "current_summary_runs"): {
        "current_summary_runs_pkey",
        "uq_current_summary_runs_receipt_state",
        "idx_current_summary_runs_projection_finished",
    },
    ("feature", "current_weather_summary"): {
        "pk_current_weather_summary",
        "idx_current_weather_summary_fact",
    },
    ("feature", "current_price_summary"): {
        "pk_current_price_summary",
        "idx_current_price_summary_fact",
    },
    ("ops", "system_log"): {
        "system_log_pkey",
        "idx_system_log_keyset",
        "idx_system_log_level",
        "idx_system_log_source",
    },
    ("ops", "api_call_log"): {
        "api_call_log_pkey",
        "idx_api_call_log_keyset",
        "idx_api_call_log_status",
    },
    ("ops", "public_api_keys"): {
        "public_api_keys_pkey",
        "public_api_keys_key_hash_key",
        "idx_public_api_keys_active_hash",
        "idx_public_api_keys_created_at",
    },
    ("ops", "admin_auth_events"): {
        "admin_auth_events_pkey",
        "idx_admin_auth_events_created_at",
        "idx_admin_auth_events_outcome_time",
    },
    ("ops", "ops_live_ticket_claims"): {
        "pk_ops_live_ticket_claims",
        "ix_ops_live_ticket_claims_expires_at",
    },
    ("ops", "ops_live_topic_revisions"): {"pk_ops_live_topic_revisions"},
    ("ops", "tvn36_legacy_freeze_preflight_manifest"): {
        "tvn36_legacy_freeze_preflight_manifest_pkey",
    },
    ("feature", "curation_import_plans"): {
        "curation_import_plans_pkey",
        "curation_import_plans_preview_command_id_key",
        "curation_import_plans_plan_sha256_key",
    },
    ("feature", "curation_import_plan_rows"): {
        "curation_import_plan_rows_pkey",
    },
    ("feature", "curation_import_plan_revisions"): {
        "curation_import_plan_revisions_pkey",
    },
    ("ops", "curation_catalog_command_effects"): {
        "curation_catalog_command_effects_pkey",
    },
    ("ops", "curation_concierge_legacy_owner_manifest"): {
        "curation_concierge_legacy_owner_manifest_pkey",
    },
    ("ops", "curation_import_collection_effects"): {
        "curation_import_collection_effects_pkey",
    },
    ("ops", "curation_import_collection_touches"): {
        "curation_import_collection_touches_pkey",
    },
    ("ops", "curation_import_plan_claims"): {
        "curation_import_plan_claims_pkey",
        "curation_import_plan_claims_command_id_key",
        "curation_import_plan_claims_import_plan_id_command_id_key",
    },
    ("ops", "curation_import_plan_commits"): {
        "curation_import_plan_commits_pkey",
        "curation_import_plan_commits_command_id_key",
        "curation_import_plan_commits_import_batch_id_key",
    },
    ("ops", "curation_provider_root_receipts"): {
        "curation_provider_root_receipts_pkey",
    },
    ("ops", "curation_provider_snapshot_receipts"): {
        "curation_provider_snapshot_receipts_pkey",
        "curation_provider_snapshot_re_root_job_id_provider_dataset__key",
    },
    ("ops", "curation_source_observation_receipts"): {
        "curation_source_observation_receipts_pkey",
    },
    ("ops", "application_schema_operation_receipts"): {
        "pk_application_schema_operation_receipts",
    },
}

_TVN40_RAW_SQL_TABLES = frozenset(
    {
        ("feature", "curation_import_plans"),
        ("feature", "curation_import_plan_rows"),
        ("feature", "curation_import_plan_revisions"),
        ("ops", "curation_catalog_command_effects"),
        ("ops", "curation_concierge_legacy_owner_manifest"),
        ("ops", "curation_import_collection_effects"),
        ("ops", "curation_import_collection_touches"),
        ("ops", "curation_import_plan_claims"),
        ("ops", "curation_import_plan_commits"),
        ("ops", "curation_provider_root_receipts"),
        ("ops", "curation_provider_snapshot_receipts"),
        ("ops", "curation_source_observation_receipts"),
    }
)

# pg_get_constraintdef/pg_get_indexdef 기반 exact catalog 계약. 이름만 같고 CHECK/FK
# 의미나 index key/predicate가 달라지는 drift도 digest가 바뀐다. 값 갱신은 migration
# DDL을 의도적으로 바꾼 PR에서만 허용한다.
_TVN40_RAW_SQL_CATALOG_SHA256: dict[tuple[str, str], str] = {
    ("feature", "curation_import_plan_revisions"): (
        "38b184a208713fe52e9a3007bf98fa972c95a21c673205fe7eaa3880e5381e78"
    ),
    ("feature", "curation_import_plan_rows"): (
        "8f3f66e85eca459f67f82d5fbb12ece3c0c5ce1f970376596f46a046e6d41f33"
    ),
    ("feature", "curation_import_plans"): (
        "0ecff9d4d7253e6ae466feb782a0c941ab50673293c61f23e91d3fdef1fc5047"
    ),
    ("ops", "curation_catalog_command_effects"): (
        "e6e19c6c0a02c44bcaa7632597d0f2ba3f4e3e4404cd67ca010f202e52137920"
    ),
    ("ops", "curation_concierge_legacy_owner_manifest"): (
        "b035b26d83adb06bed61284f4a31beca80b46a2856f7b68ae07b17e976046afc"
    ),
    ("ops", "curation_import_collection_effects"): (
        "489a7b22da0e46582609c066b19cea59dcc621dae33f59913a53dbda0f757984"
    ),
    ("ops", "curation_import_collection_touches"): (
        "b55dea3a3fdd17744281cc1fdadd16000251db76d3052fac855310eb0c868214"
    ),
    ("ops", "curation_import_plan_claims"): (
        "1a1e40ea9f266833facf386e56968e9391b6c14a313afd668ede4525a9d75bdc"
    ),
    ("ops", "curation_import_plan_commits"): (
        "3cfdb8dea520650d4bd4d53dc4903b80694ebc909f167e92e4ff82ef8667bd10"
    ),
    ("ops", "curation_provider_root_receipts"): (
        "f3e030279289d8e865e32577a95e6cc795280a321395df6573d7d154db26dfc2"
    ),
    ("ops", "curation_provider_snapshot_receipts"): (
        "c50c9f1e4bf814d61767930f90684f0e67326e58e0d577ba9ed32b8839c4dceb"
    ),
    ("ops", "curation_source_observation_receipts"): (
        "be6d2e4da5248443e0a69ec8a3783c7ea9dd57016a47b579bdc32fe20a9cd0b3"
    ),
}

_UNCOMPARED_INDEX_CONTRACTS: dict[
    tuple[str, str],
    tuple[bool, tuple[str, ...], str],
] = {
    # T-VN-33(0091)이 ``idx_source_records_kma_alert_history``를 대체 없이 drop했다
    # — 술어가 잡던 provider/dataset_key/source_entity_type 사본이 모두 사라져
    # partial index 자체가 성립하지 않는다. 계약도 함께 사라진다.
    #
    # T-VN-34(0096/0097)로 ``idx_features_dedup_refresh_keyset``도 이 ledger를
    # 떠났다. 이 index가 따로 있었던 이유는 0020의 ``idx_features_updated_keyset``이
    # **술어 없는** 전체 index였기 때문이다 — 같은 정렬축에 "살아 있고 공개된 행"
    # 필터를 얹으려면 별도 partial index가 필요했다. 0096이 그
    # ``idx_features_updated_keyset``을 3축 술어(``lifecycle_state='active' AND
    # publication_state='published' AND quality_state='valid'``, 즉 legacy
    # ``deleted_at IS NULL AND status='active'``의 등가물) partial index로 다시
    # 만들면서 정렬축·술어가 그대로 흡수됐고, 남는 차이는 ``coord IS NOT NULL``
    # 한 항뿐이라 같은 키를 가진 두 번째 index를 유지할 근거가 사라졌다. 0097이
    # 술어가 이름을 부르던 ``status``/``deleted_at``을 제거하며 물리 index도 함께
    # 사라진다. 후속 index는 ORM(``models.py``)이 선언하므로 **비교 대상**이고,
    # 비교 제외 ledger에 들어갈 자리가 아니다.
    #
    # 결과적으로 이 dict는 비었지만 계약은 살아 있다: 아래 테스트가
    # ``UNCOMPARED_INDEXES``와의 동치를 계속 확인하므로, 검증 없는 새 제외 항목은
    # 여전히 추가될 수 없다.
}


def _canonical_pg_sql(value: str | None) -> str:
    if value is None:
        return ""
    without_casts = value.replace("::text[]", "").replace("::text", "")
    return re.sub(r'[\s()"]+', "", without_casts).lower()


async def _run_alembic_upgrade(dsn: str) -> None:
    """``alembic.command.upgrade``를 worker thread에서 실행.

    alembic은 sync API + 자체 asyncio.run(env.py)을 호출하므로 현재 pytest
    event loop과 충돌. ``asyncio.to_thread``로 별도 thread에서 alembic의
    asyncio 호출이 자기 event loop을 만들도록 분리.

    env.py는 ``Config.get_main_option("sqlalchemy.url")``을 우선 사용하므로
    여기서 박은 DSN이 적용됨 (KOR_TRAVEL_MAP_PG_DSN env var 불필요).
    """
    from pathlib import Path

    from alembic.config import Config


    project_root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240  # sync IO is trivial path-arith here
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    # 배포와 같은 경로로 돈다 — final bootstrap 후 migrator 자격으로 upgrade.
    from tests.integration._application_300_bootstrap import (
        upgrade_head_with_application_300_bootstrap,
    )

    await upgrade_head_with_application_300_bootstrap(cfg, dsn)


def _alembic_head_revision() -> str:
    """현재 script directory의 head revision.

    이 값을 리터럴로 박으면 마이그레이션을 하나 추가할 때마다 무관한 테스트가
    깨진다(`0073`에서 실제로 그랬다). 검사하려는 것은 "재시도 후 head까지
    올라왔는가"이지 특정 revision 이름이 아니다.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    project_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head() or ""


@pytest.fixture(scope="session")
async def pg_engine_with_migrations(pg_container: object) -> object:
    """``pg_engine``과 동일하지만 alembic 적용 후 yield.

    ``pg_engine``의 schema/extension 직접 생성 fixture를 우회 — alembic가
    혼자 만들어내는지 확인하기 위함.
    """
    from uuid import uuid4

    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    async_dsn = normalize_async_dsn(raw_dsn)
    database_name = f"alembic_upgrade_{uuid4().hex}"
    database_dsn = make_url(async_dsn).set(database=database_name).render_as_string(
        hide_password=False
    )

    admin_engine = make_async_engine(async_dsn, pool_size=1)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await admin_engine.dispose()

    engine = None
    try:
        # alembic은 본인이 schema/extension 생성하므로 pg_engine의 setup은 건너뛴다.
        await _run_alembic_upgrade(database_dsn)
        engine = make_async_engine(database_dsn)
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        admin_engine = make_async_engine(async_dsn, pool_size=1)
        try:
            async with admin_engine.connect() as connection:
                autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
                await autocommit.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        finally:
            await admin_engine.dispose()


async def test_alembic_creates_4_schemas(pg_engine_with_migrations: AsyncEngine) -> None:
    """0001 revision이 4 schema 생성."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('feature','provider_sync','ops','x_extension') "
                "ORDER BY nspname"
            )
        )
        schemas = [row[0] for row in result]
    assert schemas == ["feature", "ops", "provider_sync", "x_extension"]


async def test_alembic_creates_3_extensions_in_x_extension(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0001 revision이 3 extension을 ``x_extension``에 격리 생성 (ADR-008)."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT e.extname, n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON e.extnamespace = n.oid "
                "WHERE e.extname IN ('postgis','pg_trgm','pgcrypto') "
                "ORDER BY e.extname"
            )
        )
        rows = list(result)
    assert len(rows) == 3
    for ext_name, schema in rows:
        assert schema == "x_extension", (
            f"{ext_name} in {schema}, expected x_extension (ADR-008)"
        )


async def test_alembic_creates_features_table(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0002 revision이 ``feature.features`` 테이블 생성 (head 기준 core 축).

    T-VN-35(ADR-086, alembic 0086): ``detail``/``geom``은 **core 컬럼이 아니다**.
    kind별 값과 geometry의 정본은 subtype 5종이고 응답용 두 값은 조립 SQL이
    만든다(0097 이후로는 ``feature.public_features``와 snapshot writer가 core +
    subtype을 직접 조립한다). core에 그 컬럼이 되살아나면 "값이 두 곳에 있다"는
    회귀이므로 부재도 함께 고정한다.

    T-VN-34(alembic 0095~0097): 상태도 같은 이유로 정본이 한 곳이어야 한다.
    단일 ``status``와 ``deleted_at`` soft delete는 서로 다른 세 질문("살아 있나 /
    공개되나 / 값을 믿을 만한가")을 한 열에 눌러 담고 있었고, 0095가 그것을
    ``lifecycle_state``/``publication_state``/``quality_state`` 세 축으로 푼 뒤
    0097이 legacy 열을 물리 제거했다. 그래서 여기서 존재를 요구하는 것은 세 축이고,
    사라진 legacy 상태 열 8개는 부재를 함께 고정한다 — 되살아나면 같은 상태가 두
    표기로 공존하는 회귀다.
    """
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='feature' AND table_name='features' "
                "ORDER BY ordinal_position"
            )
        )
        columns = [row[0] for row in result]
    # 핵심 컬럼 존재 확인.
    for required in (
        "feature_id", "kind", "name", "category", "coord", "coord_5179",
        "coord_precision_digits", "address",
        "lifecycle_state", "publication_state", "quality_state",
        "created_at", "updated_at",
    ):
        assert required in columns, f"missing column: {required}"
    for removed in ("detail", "geom"):
        assert removed not in columns, f"core column {removed!r} came back (ADR-086)"
    for legacy_state in (
        "status", "deleted_at",
        "user_deleted_at", "user_deleted_by",
        "user_change_kind", "user_change_status",
        "user_change_request_id", "user_change_reason",
    ):
        assert legacy_state not in columns, (
            f"legacy state column {legacy_state!r} came back (T-VN-34, 0097)"
        )


async def test_alembic_creates_typed_subtype_tables_and_assembly_view(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """head가 subtype 5종 + 조립 뷰 1종을 갖는다 (T-VN-35 ADR-086 · T-VN-34 0097).

    0084~0086은 subtype 5종과 조립 뷰 2종(``features_detailed`` +
    ``public_features``)을 만들었지만, ``features_detailed``는 0087이
    ``detail`` 컬럼을 대신하려고 세운 **한시적 read bridge**였다. 0097이 public
    projection과 snapshot writer를 core+subtype 직접 조립으로 옮긴 뒤 그 bridge를
    drop했으므로, head에 남는 조립 뷰는 ``public_features`` 하나다. bridge가 다시
    생기면 detail 조립 정본이 둘이 되는 회귀이므로 부재도 함께 고정한다.
    """
    async with pg_engine_with_migrations.connect() as conn:
        tables = set(
            (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'feature' AND table_type = 'BASE TABLE'"
                    )
                )
            ).scalars()
        )
        views = set(
            (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.views "
                        "WHERE table_schema = 'feature'"
                    )
                )
            ).scalars()
        )
    assert {
        "feature_places",
        "feature_events",
        "feature_notices",
        "feature_routes",
        "feature_areas",
    } <= tables
    assert "public_features" in views
    assert "features_detailed" not in views, (
        "0087 read bridge가 0097 이후 되살아났다 (T-VN-34)"
    )


async def test_alembic_coord_5179_is_generated_stored(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """ADR-012 — ``coord_5179``는 STORED generated column."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT is_generated, generation_expression "
                "FROM information_schema.columns "
                "WHERE table_schema='feature' AND table_name='features' "
                "AND column_name='coord_5179'"
            )
        )
        row = result.one()
    assert row.is_generated == "ALWAYS"
    # PostgreSQL은 generation_expression을 재파싱하며 함수명을 소문자 +
    # 스키마 한정으로 정규화한다 (예: ``x_extension.st_transform(coord, 5179)``).
    # 따라서 대소문자 무시하고 ``st_transform`` 참조만 확인 (ADR-008 + ADR-012).
    assert "st_transform" in (row.generation_expression or "").lower()


async def test_alembic_coord_precision_trigger_defaults_for_coord(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """T-RV-16 — coord가 있으면 DB trigger가 precision 기본값을 보강."""
    async with pg_engine_with_migrations.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category, coord
                    ) VALUES (
                        'feature:precision-trigger',
                        'place',
                        'precision trigger',
                        '01070100',
                        x_extension.ST_SetSRID(
                            x_extension.ST_MakePoint(129.3320, 35.7900),
                            4326
                        )
                    )
                    """
                )
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT coord_precision_digits "
                        "FROM feature.features "
                        "WHERE feature_id = 'feature:precision-trigger'"
                    )
                )
            ).one()
        finally:
            await tx.rollback()
    assert row.coord_precision_digits == 6


async def test_alembic_creates_source_tables(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """provider sync의 catalog / entity / observation / link / cursor 테이블.

    T-VN-33(0089~0091): dataset identity 정본이 ``provider_datasets`` 3종 catalog로
    올라오고, entity의 현재 record 포인터는 ``source_entity_heads``로 분리됐다.
    """
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='provider_sync' "
                "ORDER BY table_name"
            )
        )
        tables = [row[0] for row in result]
    assert tables == [
        "notice_lifecycle_scopes",
        "notice_lineage_states",
        "provider_dataset_operation_scopes",
        "provider_dataset_operations",
        "provider_datasets",
        "provider_sync_state",
        "source_entities",
        "source_entity_heads",
        "source_links",
        "source_records",
    ]


async def test_alembic_features_indexes_exist(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """핵심 GIST/GIN/partial 인덱스 존재.

    T-VN-35(alembic 0086): geometry GiST는 core가 아니라 route/area **subtype**에
    있다 — 술어가 subtype 인덱스를 타야 bbox 후보 판정이 seq scan으로 퇴화하지
    않는다(``_bbox_candidate_predicate_sql``).
    """
    async with pg_engine_with_migrations.connect() as conn:
        idx = {
            (row[0], row[1])
            for row in (
                await conn.execute(
                    text(
                        "SELECT tablename, indexname FROM pg_indexes "
                        "WHERE schemaname='feature'"
                    )
                )
            )
        }
    required = {
        ("features", "idx_features_coord_gist"),
        ("features", "idx_features_coord_5179_gist"),
        ("features", "idx_features_kind_category"),
        ("features", "idx_features_name_trgm"),
        ("feature_routes", "idx_feature_routes_geom_gist"),
        ("feature_areas", "idx_feature_areas_geom_gist"),
    }
    missing = required - idx
    assert not missing, f"missing indexes: {missing}"
    assert ("features", "idx_features_geom_gist") not in idx


async def test_alembic_creates_feature_price_values_table(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """T-VN-38 price fact table이 canonical dataset/source identity를 보존한다."""
    async with pg_engine_with_migrations.connect() as conn:
        columns = [
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='feature' "
                        "AND table_name='feature_price_values' "
                        "ORDER BY ordinal_position"
                    )
                )
            )
        ]
        indexes = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname='feature' "
                        "AND tablename='feature_price_values'"
                    )
                )
            )
        }

    for required in (
        "price_value_key",
        "feature_id",
        "provider_dataset_id",
        "price_domain",
        "product_key",
        "observed_at",
        "known_at",
        "value_number",
        "source_entity_key",
        "source_record_key",
    ):
        assert required in columns
    assert {
        "idx_price_values_feature_observed_identity",
        "uq_price_value_summary_reference",
    } <= indexes


async def test_alembic_creates_feature_merge_history(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0007 revision이 ``ops.feature_merge_history`` 생성 (ADR-016)."""
    async with pg_engine_with_migrations.connect() as conn:
        exists = (
            await conn.execute(
                text("SELECT to_regclass('ops.feature_merge_history')")
            )
        ).scalar_one()
    assert exists is not None


async def _tvn40_raw_sql_catalog_sha256(
    conn: AsyncConnection,
) -> dict[tuple[str, str], str]:
    """T-VN-40 raw-SQL relation의 constraint/index 의미를 정규화해 해시한다."""

    result = await conn.execute(
        text(
            """
            SELECT
                namespace.nspname AS schema_name,
                relation.relname AS table_name,
                'constraint' AS object_kind,
                constraint_.conname AS object_name,
                jsonb_build_object(
                    'type', constraint_.contype,
                    'definition', pg_catalog.pg_get_constraintdef(
                        constraint_.oid,
                        true
                    ),
                    'validated', constraint_.convalidated,
                    'deferrable', constraint_.condeferrable,
                    'deferred', constraint_.condeferred
                ) AS contract
            FROM pg_catalog.pg_constraint AS constraint_
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = constraint_.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE (namespace.nspname, relation.relname) IN (
                SELECT * FROM unnest(
                    CAST(:schema_names AS text[]),
                    CAST(:table_names AS text[])
                )
            )
            UNION ALL
            SELECT
                namespace.nspname AS schema_name,
                relation.relname AS table_name,
                'index' AS object_kind,
                index_relation.relname AS object_name,
                jsonb_build_object(
                    'definition', pg_catalog.pg_get_indexdef(index_.indexrelid),
                    'unique', index_.indisunique,
                    'primary', index_.indisprimary,
                    'valid', index_.indisvalid,
                    'ready', index_.indisready,
                    'live', index_.indislive
                ) AS contract
            FROM pg_catalog.pg_index AS index_
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = index_.indrelid
            JOIN pg_catalog.pg_class AS index_relation
              ON index_relation.oid = index_.indexrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE (namespace.nspname, relation.relname) IN (
                SELECT * FROM unnest(
                    CAST(:schema_names AS text[]),
                    CAST(:table_names AS text[])
                )
            )
            ORDER BY schema_name, table_name, object_kind, object_name
            """
        ),
        {
            "schema_names": [key[0] for key in sorted(_TVN40_RAW_SQL_TABLES)],
            "table_names": [key[1] for key in sorted(_TVN40_RAW_SQL_TABLES)],
        },
    )
    contracts: dict[tuple[str, str], list[dict[str, object]]] = {
        key: [] for key in _TVN40_RAW_SQL_TABLES
    }
    for row in result:
        contracts[(row.schema_name, row.table_name)].append(
            {
                "kind": row.object_kind,
                "name": row.object_name,
                "contract": row.contract,
            }
        )
    return {
        key: hashlib.sha256(
            json.dumps(
                contracts[key],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for key in sorted(contracts)
    }


async def test_alembic_unmapped_tables_keep_structural_contract(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """metadata 제외 table의 전체 column과 핵심 constraint/index를 고정한다."""

    assert set(_UNMAPPED_TABLE_COLUMNS) == UNMAPPED_APP_TABLES
    assert set(_UNMAPPED_TABLE_CONSTRAINTS) == UNMAPPED_APP_TABLES
    assert set(_UNMAPPED_TABLE_INDEXES) == UNMAPPED_APP_TABLES
    assert set(_TVN40_RAW_SQL_CATALOG_SHA256) == _TVN40_RAW_SQL_TABLES

    async with pg_engine_with_migrations.connect() as conn:
        column_rows = await conn.execute(
            text(
                """
                SELECT
                    namespace.nspname AS schema_name,
                    relation.relname AS table_name,
                    attribute.attname AS column_name,
                    pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
                        AS formatted_type,
                    attribute.attnotnull AS not_null
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname IN ('feature', 'ops')
                  AND relation.relname = ANY(CAST(:table_names AS text[]))
                  AND relation.relkind IN ('r', 'p')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                """
            ),
            {"table_names": sorted({table for _, table in _UNMAPPED_TABLE_COLUMNS})},
        )
        constraint_rows = await conn.execute(
            text(
                """
                SELECT
                    namespace.nspname AS schema_name,
                    relation.relname AS table_name,
                    constraint_.conname AS constraint_name,
                    constraint_.contype AS constraint_type
                FROM pg_catalog.pg_constraint AS constraint_
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = constraint_.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname IN ('feature', 'ops')
                  AND relation.relname = ANY(CAST(:table_names AS text[]))
                """
            ),
            {"table_names": sorted({table for _, table in _UNMAPPED_TABLE_COLUMNS})},
        )
        index_rows = await conn.execute(
            text(
                """
                SELECT schemaname AS schema_name, tablename AS table_name, indexname
                FROM pg_catalog.pg_indexes
                WHERE schemaname IN ('feature', 'ops')
                  AND tablename = ANY(CAST(:table_names AS text[]))
                """
            ),
            {"table_names": sorted({table for _, table in _UNMAPPED_TABLE_COLUMNS})},
        )
        exact_catalog_sha256 = await _tvn40_raw_sql_catalog_sha256(conn)

    actual_columns: dict[tuple[str, str], set[tuple[str, str, bool]]] = {
        key: set() for key in _UNMAPPED_TABLE_COLUMNS
    }
    for row in column_rows:
        key = (row.schema_name, row.table_name)
        if key in actual_columns:
            actual_columns[key].add(
                (row.column_name, row.formatted_type, row.not_null)
            )

    actual_constraints: dict[tuple[str, str], set[tuple[str, str]]] = {
        key: set() for key in _UNMAPPED_TABLE_CONSTRAINTS
    }
    for row in constraint_rows:
        key = (row.schema_name, row.table_name)
        if key in actual_constraints:
            constraint_type = row.constraint_type
            if isinstance(constraint_type, bytes):
                constraint_type = constraint_type.decode("ascii")
            actual_constraints[key].add((row.constraint_name, constraint_type))

    actual_indexes: dict[tuple[str, str], set[str]] = {
        key: set() for key in _UNMAPPED_TABLE_INDEXES
    }
    for row in index_rows:
        key = (row.schema_name, row.table_name)
        if key in actual_indexes:
            actual_indexes[key].add(row.indexname)

    assert actual_columns == _UNMAPPED_TABLE_COLUMNS
    for key, required in _UNMAPPED_TABLE_CONSTRAINTS.items():
        assert required <= actual_constraints[key], f"{key} constraint drift"
    for key, required in _UNMAPPED_TABLE_INDEXES.items():
        assert required <= actual_indexes[key], f"{key} index drift"
    assert exact_catalog_sha256 == _TVN40_RAW_SQL_CATALOG_SHA256


async def test_tvn40_raw_sql_contract_rejects_same_name_semantic_drift(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """같은 이름의 무효 CHECK로 바꿔도 exact catalog 계약은 반드시 실패한다."""

    async with pg_engine_with_migrations.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(
                text(
                    """
                    ALTER TABLE feature.curation_import_plans
                      DROP CONSTRAINT curation_import_plans_content_sha256_check
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE feature.curation_import_plans
                      ADD CONSTRAINT curation_import_plans_content_sha256_check
                      CHECK (true)
                    """
                )
            )
            mutated = await _tvn40_raw_sql_catalog_sha256(conn)
            assert mutated != _TVN40_RAW_SQL_CATALOG_SHA256
            assert (
                mutated[("feature", "curation_import_plans")]
                != _TVN40_RAW_SQL_CATALOG_SHA256[
                    ("feature", "curation_import_plans")
                ]
            )
        finally:
            await transaction.rollback()


async def test_alembic_uncompared_indexes_keep_exact_semantics(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """비교 제외 index의 UNIQUE·키 순서·predicate를 catalog로 고정한다."""

    assert set(_UNCOMPARED_INDEX_CONTRACTS) == UNCOMPARED_INDEXES

    async with pg_engine_with_migrations.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT
                    namespace.nspname AS schema_name,
                    index_relation.relname AS index_name,
                    index_.indisunique AS is_unique,
                    ARRAY(
                        SELECT
                            pg_get_indexdef(
                                index_.indexrelid,
                                key_position,
                                true
                            )
                            || CASE
                                WHEN (
                                    index_.indoption[key_position - 1] & 1
                                ) = 1 THEN ' DESC'
                                ELSE ' ASC'
                            END
                            || CASE
                                WHEN (
                                    index_.indoption[key_position - 1] & 2
                                ) = 2 THEN ' NULLS FIRST'
                                ELSE ' NULLS LAST'
                            END
                        FROM generate_series(1, index_.indnkeyatts) AS key_position
                        ORDER BY key_position
                    ) AS key_expressions,
                    pg_get_expr(index_.indpred, index_.indrelid, true) AS predicate
                FROM pg_catalog.pg_index AS index_
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_.indexrelid
                JOIN pg_catalog.pg_class AS table_relation
                  ON table_relation.oid = index_.indrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = table_relation.relnamespace
                WHERE index_relation.relname = ANY(CAST(:index_names AS text[]))
                """
            ),
            {
                "index_names": sorted(
                    index_name for _, index_name in _UNCOMPARED_INDEX_CONTRACTS
                )
            },
        )

    actual = {
        (row.schema_name, row.index_name): (
            row.is_unique,
            tuple(_canonical_pg_sql(value) for value in row.key_expressions),
            _canonical_pg_sql(row.predicate),
        )
        for row in rows
    }
    expected = {
        key: (
            is_unique,
            tuple(_canonical_pg_sql(value) for value in key_expressions),
            _canonical_pg_sql(predicate),
        )
        for key, (is_unique, key_expressions, predicate) in (
            _UNCOMPARED_INDEX_CONTRACTS.items()
        )
    }

    assert actual == expected


async def test_alembic_security_table_checks_reject_invalid_rows(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """인증/운영 제외 table의 핵심 CHECK가 이름만 남은 퇴행을 막는다."""

    invalid_inserts = (
        "INSERT INTO ops.system_log "
        "(level, source, event, message) VALUES ('invalid', 'test', 'test', 'test')",
        "INSERT INTO ops.public_api_keys (key_hash, key_hint) "
        "VALUES ('not-a-sha256', '123456')",
        "INSERT INTO ops.admin_auth_events (event_type, outcome) "
        "VALUES ('invalid', 'succeeded')",
        "INSERT INTO ops.ops_live_ticket_claims (nonce_hash, actor, expires_at) "
        "VALUES (decode('00', 'hex'), 'test', now())",
        "INSERT INTO ops.ops_live_topic_revisions (topic, revision) "
        "VALUES ('review-contract', -1)",
    )
    async with pg_engine_with_migrations.connect() as conn:
        for statement in invalid_inserts:
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(text(statement))


async def test_alembic_head_primary_keys_match_orm_declarations(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """모든 mapped table의 ORM PK가 alembic head의 PK와 **열 집합까지 같다**.

    ORM이 DB보다 **좁은** PK를 선언하면 SQLAlchemy identity map이 빠진 열만
    다른 두 행을 같은 객체로 접어, 뒤에 읽은 행이 앞의 행을 조용히 덮는다.
    실측 사례: ``provider_dataset_operation_scopes``의 DB PK는 triple인데 ORM은
    ``(provider_dataset_id, sync_scope)`` 2열만 선언하고 있었다 — 그 조합을
    막아 주던 것은 같은 테이블의 refresh-only CHECK뿐이었고, 그 의존은 어디에도
    적혀 있지 않았다.

    반대로 ORM이 **넓은** PK를 선언해도 flush 시 DB가 거부하지 않아 조용히
    어긋나므로, 포함이 아니라 동치로 잡는다.
    """

    from kortravelmap.infra.models import Base

    mapped = {
        (table.schema, table.name): {
            column.name for column in table.primary_key.columns
        }
        # ``sorted_tables``는 topological 정렬을 시도하다 상호 FK 순환에서
        # SAWarning을 낸다(이 저장소는 경고를 오류로 승격한다). PK 비교에 순서는
        # 필요 없으므로 정렬하지 않은 매핑을 그대로 쓴다.
        for table in Base.metadata.tables.values()
    }
    assert mapped, "ORM metadata에 mapped table이 없다"

    async with pg_engine_with_migrations.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT namespace.nspname AS schema_name,
                           relation.relname AS table_name,
                           attribute.attname AS column_name
                    FROM pg_catalog.pg_constraint AS constraint_row
                    JOIN pg_catalog.pg_class AS relation
                      ON relation.oid = constraint_row.conrelid
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    JOIN LATERAL unnest(constraint_row.conkey) AS key(attnum) ON true
                    JOIN pg_catalog.pg_attribute AS attribute
                      ON attribute.attrelid = relation.oid
                     AND attribute.attnum = key.attnum
                    WHERE constraint_row.contype = 'p'
                    """
                )
            )
        ).all()

    live: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        live.setdefault((row.schema_name, row.table_name), set()).add(row.column_name)

    mismatched = {
        f"{schema}.{name}": {"orm": sorted(columns), "db": sorted(live[(schema, name)])}
        for (schema, name), columns in mapped.items()
        if (schema, name) in live and live[(schema, name)] != columns
    }
    assert mismatched == {}, f"ORM PK가 DB PK와 다르다: {mismatched}"
