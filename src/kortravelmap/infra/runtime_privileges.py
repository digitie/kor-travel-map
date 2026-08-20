"""ADR-090 runtime table ACL reconciliation after an Alembic upgrade.

The dedicated bootstrap transfers application-object ownership to the NOLOGIN
schema owner *before* Alembic runs.  PostgreSQL default privileges are an
unsafe way to restore old broad writer access: a later state or audit table
would silently become mutable by API/Dagster.  Instead the migrator performs
this explicit, fail-closed reconciliation after every upgrade and before the
API process discards its migrator DSN.

Only the migrator LOGIN can enter ``ktm_feature_schema_owner``.  Runtime
LOGINs merely inherit the resulting table grants and cannot ``SET ROLE`` into
any owner/group role.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import cast

from sqlalchemy import text

from kortravelmap.infra.db import make_async_engine

__all__ = [
    "RuntimePrivilegeReconciliationError",
    "reconcile_runtime_privileges",
]


class RuntimePrivilegeReconciliationError(RuntimeError):
    """migrator가 ADR-090의 명시 ACL inventory를 만족하지 못했을 때의 오류."""


_RUNTIME_ROLE = "ktm_feature_runtime"
_MIGRATOR_ROLE = "ktm_feature_migrator"
_SCHEMA_OWNER_ROLE = "ktm_feature_schema_owner"

# feature schema에는 procedure-only state/audit object가 섞여 있다. 이 map은
# runtime이 직접 접근하는 table만 이름으로 허용한다. 새 feature table은 이 목록을
# 의도적으로 갱신하기 전까지 deployment를 막는다.
_FEATURE_TABLE_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    "curated_source_rules": ("SELECT",),
    "curated_sources": ("SELECT",),
    "curated_themes": ("SELECT",),
    "curation_collections": ("SELECT",),
    "curation_import_batches": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curation_import_rows": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curation_items": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "curation_link_decisions": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "current_price_summary": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "current_weather_summary": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "feature_aliases": ("SELECT",),
    "feature_events": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "feature_notices": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "feature_places": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "feature_price_values": ("SELECT", "INSERT"),
    "feature_weather_values": ("SELECT", "INSERT"),
    # `weather_metric_series`(legacy 0069)는 vNext baseline에 없다 — phantom 항목이라 지웠다.
    # 표에 있어도 DB에 없으면 reconcile이 건너뛰므로 아무 것도 지키지 않는다.
    # phantom은 `tests/integration/test_runtime_privileges_acl.py::
    # test_every_declared_feature_relation_exists`가 잡는다.
}

# Views are included in ``REVOKE ALL ON ALL TABLES`` but PostgreSQL does not
# return them from a table-only catalog inventory.  T-VN-34C leaves exactly
# one runtime view: public readers use ``public_features`` while non-public
# assembly is explicit repository SQL.  A new view therefore fails
# reconciliation until its intended consumer is reviewed.
_FEATURE_VIEW_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    "public_features": ("SELECT",),
}

# Route/area geometry is the sole cross-relation public index case.  Keep the
# runtime grant column-scoped so it cannot make the DB-owned ``public_ready``
# cache stale (T-VN-34B).  These tables intentionally do not use the broad
# feature table inventory above.
# Insert needs the immutable subtype identity, whereas an ordinary runtime
# update must never reattach or delete a subtype row.  Reattachment changes
# the 1:1 core/subtype topology and deletion can make a public route/area
# disappear from geometry readers; neither is a normal provider writer path.
_ROUTE_AREA_RUNTIME_INSERT_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "feature_routes": (
        "feature_id",
        "feature_uuid",
        "kind",
        "geom",
        "route_type",
        "geometry_source",
        "geometry_status",
        "total_distance_meters",
        "expected_duration_minutes",
        "difficulty",
        "begin_name",
        "begin_address",
        "end_name",
        "end_address",
        "payload",
    ),
    "feature_areas": (
        "feature_id",
        "feature_uuid",
        "kind",
        "geom",
        "area_kind",
        "boundary_source",
        "area_square_meters",
        "regulation_scope",
        "administrative_office",
        "description",
        "payload",
    ),
}

_ROUTE_AREA_RUNTIME_UPDATE_COLUMNS: Mapping[str, tuple[str, ...]] = {
    relation: tuple(
        column
        for column in columns
        if column not in {"feature_id", "feature_uuid", "kind"}
    )
    for relation, columns in _ROUTE_AREA_RUNTIME_INSERT_COLUMNS.items()
}

_ROUTE_AREA_RUNTIME_GRANTS = tuple(
    statement
    for relation, insert_columns in _ROUTE_AREA_RUNTIME_INSERT_COLUMNS.items()
    for statement in (
        f"GRANT SELECT ON feature.{relation} TO ktm_feature_runtime",
        f"GRANT INSERT ({', '.join(insert_columns)}) ON feature.{relation} "
        "TO ktm_feature_runtime",
        f"GRANT UPDATE ({', '.join(_ROUTE_AREA_RUNTIME_UPDATE_COLUMNS[relation])}) "
        f"ON feature.{relation} TO ktm_feature_runtime",
        f"GRANT SELECT (feature_id, public_ready), UPDATE (public_ready) "
        f"ON feature.{relation} "
        "TO ktm_feature_state_procedure_owner",
    )
)

# Provider/ops schemas contain ordinary application data, not state/audit
# evidence.  Existing repositories use their complete current table surface;
# granting only DML (never CREATE/ALTER/TRUNCATE/ownership) maintains that
# boundary after ownership transfer.  No ALTER DEFAULT PRIVILEGES is used:
# this reconciler grants a newly-created table only during a deliberate startup
# migration pass, never when a state/audit relation happens to be created.
#: ops 표 선언이 쓰는 "평범한 ops 데이터" 권한. 상수로 두어 여러 선언이 같은 값을
#: 가리키게 한다 — 값이 바뀌면 한 곳만 바뀐다.
_ORDINARY_OPS: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE")

#: `ops`는 여기에 없다. 선언 없는 ops relation은 기본값으로 떨어지는 대신
#: `_OPS_TABLE_PRIVILEGES`에서 막힌다(위 `_ORDINARY_OPS` 주석 참조).
_ORDINARY_SCHEMA_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    "provider_sync": ("SELECT", "INSERT", "UPDATE", "DELETE"),
}

# `ops.feature_overrides` can keep a provider-retired Feature from being
# reactivated.  It is not ordinary ops data: runtime must only observe it
# directly.  A typed state-owner procedure owns author/revoke mutation so a
# provider/admin connection cannot erase that fence through raw SQL.
_OPS_TABLE_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    # 아래 56개는 2026-08-20까지 **선언 없이** full CRUD를 받던 표다. 이 목록은
    # 그때의 유효 권한을 그대로 옮겨 적은 것이지 '좁혀도 되는지'를 심사한 결과가
    # 아니다 — 심사는 후속으로 남긴다. 여기 적힌 이유는 선언하지 않으면 권한이
    # 생기는 경로를 없애기 위해서다.
    #
    # 목록은 `Base.metadata`가 아니라 **migrate된 DB의 `pg_class`**에서 뽑았다.
    # reconcile이 순회하는 것이 DB이지 metadata가 아니고, 실제로 모델에 없는 ops 표가
    # 17개 있다(`tests/integration/test_runtime_privileges_acl.py`가 양방향으로 고정한다).
    "admin_auth_events": _ORDINARY_OPS,
    "api_call_log": _ORDINARY_OPS,
    "backup_command_executions": _ORDINARY_OPS,
    "c6c_cancel_probe_fixtures": _ORDINARY_OPS,
    "cache_target_writer_drain_instigations": _ORDINARY_OPS,
    "cache_target_writer_drain_leases": _ORDINARY_OPS,
    "cache_target_writer_drain_runs": _ORDINARY_OPS,
    "curation_catalog_command_effects": (),
    "curation_concierge_legacy_owner_manifest": (),
    "curation_import_collection_effects": (),
    "curation_import_collection_touches": (),
    "curation_import_plan_claims": (),
    "curation_import_plan_commits": (),
    "curation_provider_root_receipts": (),
    "curation_provider_snapshot_receipts": (),
    "curation_source_observation_receipts": (),
    "current_summary_runs": _ORDINARY_OPS,
    "dagster_schedule_active_claims": _ORDINARY_OPS,
    "dagster_schedule_audit_events": _ORDINARY_OPS,
    "dagster_schedule_claim_resolutions": _ORDINARY_OPS,
    "dagster_schedule_overrides": _ORDINARY_OPS,
    "data_integrity_violations": _ORDINARY_OPS,
    "dedup_review_queue": _ORDINARY_OPS,
    "domain_command_results": _ORDINARY_OPS,
    "domain_commands": _ORDINARY_OPS,
    "enrichment_review_queue": _ORDINARY_OPS,
    "feature_consistency_reports": _ORDINARY_OPS,
    "feature_merge_history": _ORDINARY_OPS,
    "feature_update_request_datasets": _ORDINARY_OPS,
    "feature_update_request_idempotency": _ORDINARY_OPS,
    "feature_update_requests": _ORDINARY_OPS,
    "import_job_datasets": _ORDINARY_OPS,
    "import_job_event_clock": _ORDINARY_OPS,
    "import_job_events": _ORDINARY_OPS,
    "import_jobs": _ORDINARY_OPS,
    "integrity_finding_observations": _ORDINARY_OPS,
    "integrity_observation_runs": _ORDINARY_OPS,
    "integrity_observation_scopes": _ORDINARY_OPS,
    "managed_file_events": _ORDINARY_OPS,
    "managed_files": _ORDINARY_OPS,
    "offline_upload_command_executions": _ORDINARY_OPS,
    "offline_uploads": _ORDINARY_OPS,
    "ops_live_ticket_claims": _ORDINARY_OPS,
    "ops_live_topic_revisions": _ORDINARY_OPS,
    "pipeline_cancellation_members": _ORDINARY_OPS,
    "pipeline_cancellation_runs": _ORDINARY_OPS,
    "pipeline_cancellations": _ORDINARY_OPS,
    "poi_cache_target_feature_links": _ORDINARY_OPS,
    "poi_cache_target_outbox_claim_events": _ORDINARY_OPS,
    "poi_cache_target_outbox_claims": _ORDINARY_OPS,
    "poi_cache_target_outbox_deliveries": _ORDINARY_OPS,
    "poi_cache_target_outbox_events": _ORDINARY_OPS,
    "poi_cache_target_reconciliation_requests": _ORDINARY_OPS,
    "poi_cache_target_refresh_members": _ORDINARY_OPS,
    "poi_cache_target_restore_fences": _ORDINARY_OPS,
    "poi_cache_target_snapshot_gc_observations": _ORDINARY_OPS,
    # 아래 둘은 `0231`이 legacy `poi_cache_target_snapshot_items`를
    # material/receipt로 가르며 생겼다. 그 표의 권한을 물려받았을 뿐이다.
    "poi_cache_target_snapshot_material_items": _ORDINARY_OPS,
    "poi_cache_target_snapshot_materials": _ORDINARY_OPS,
    "poi_cache_target_snapshots": _ORDINARY_OPS,
    "poi_cache_target_source_events": _ORDINARY_OPS,
    "poi_cache_target_source_heads": _ORDINARY_OPS,
    "poi_cache_target_streams": _ORDINARY_OPS,
    "poi_cache_targets": _ORDINARY_OPS,
    "provider_refresh_policies": _ORDINARY_OPS,
    "public_api_keys": _ORDINARY_OPS,
    "system_log": _ORDINARY_OPS,
    "tvn36_legacy_freeze_preflight_manifest": _ORDINARY_OPS,
    # ── 아래는 좁힌 결정(심사 완료) ──
    # T-VN-40C service export is the only runtime reader.  The immutable
    # relation remains write-free for API/Dagster; the maintenance HTTP scope
    # is enforced above the database role boundary.
    "curation_cutover_identity_mappings": ("SELECT",),
    "curation_rule_reconcile_operations": (),
    "curation_rule_reconcile_scope_members": (),
    "feature_override_field_paths": ("SELECT",),
    "feature_overrides": ("SELECT",),
    # T-VN-M04 queue는 service와 admin route가 SECURITY DEFINER routine을
    # 통해서만 접근한다. runtime의 raw queue read/DML은 허용하지 않는다.
    "feature_requests": (),
    # T-VN-M05 evidence/delivery는 전용 SECURITY DEFINER writer만 접근한다.
    # lease까지 default ops grant에서 빼야 runtime이 cursor를 건너뛸 수 없다.
    "manual_provider_dedup_cases": (),
    "manual_provider_dedup_resolutions": (),
    "feature_reference_reconciliation_events": (),
    "feature_reference_reconciliation_acks": (),
    "feature_reference_reconciliation_subscriptions": (),
    "feature_reference_reconciliation_leases": (),
}

_PROTECTED_FEATURE_TABLES = frozenset(
    {
        "curation_import_plan_revisions",
        "curation_import_plan_rows",
        "curation_import_plans",
        "feature_creation_origins",
        "features",
        "feature_base_field_values",
        "feature_state_transitions",
        "manual_feature_identity_claims",
        "theme_candidate_generation_observations",
        "theme_candidate_generations",
        "theme_feature_candidate_transitions",
        "theme_feature_candidates",
    }
)
_PROTECTED_FEATURE_SEQUENCES = frozenset(
    {
        "feature_state_transitions_transition_id_seq",
        "theme_feature_candidate_transitions_transition_id_seq",
    }
)

_APPLICATION_RELATIONS_SQL = text(
    """
    SELECT namespace.nspname AS schema_name, relation.relname AS relation_name,
           relation.relkind AS relation_kind
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
      AND relation.relkind IN ('r', 'p', 'v', 'S')
    ORDER BY namespace.nspname, relation.relkind, relation.relname
    """
)

_CORE_FEATURE_GRANTS = (
    "GRANT USAGE ON SCHEMA feature, provider_sync, ops, x_extension TO ktm_feature_runtime",
    "GRANT SELECT, UPDATE ("
    "kind, name, category, coord, coord_precision_digits, address, "
    "legal_dong_code, road_name_code, road_address_management_no, "
    "admin_dong_code, sido_code, sigungu_code, urls, marker_icon, marker_color, "
    "parent_feature_id, sibling_group_id, raw_refs, created_at, updated_at"
    ") ON feature.features TO ktm_feature_runtime",
    "GRANT SELECT ON feature.feature_state_transitions TO ktm_feature_runtime",
)

_STATE_OWNER_FUNCTION_ACL = (
    "REVOKE ALL ON FUNCTION feature.prepare_feature_state_context(jsonb, text) "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON PROCEDURE feature.create_feature_with_initial_state("
    "jsonb, text, text, text, jsonb) FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_api_runtime",
    "REVOKE ALL ON PROCEDURE feature.transition_feature_state("
    "text, text, text, text, bigint, jsonb) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.author_lifecycle_override("
    "text, text, text, boolean, text, text, bigint) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.revoke_lifecycle_override("
    "text, text, bigint) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.apply_provider_feature_field_patch("
    "text, bigint, text, text, bigint, jsonb, jsonb) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.author_feature_field_overrides("
    "text, bigint, text, text, bigint, jsonb, jsonb) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.revoke_feature_field_overrides("
    "text, bigint, text, text, bigint, text[]) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.transition_admin_feature_state("
    "text, text, text, text, bigint, text, text, text) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.reactivate_admin_feature_state("
    "text, bigint, text, text, bigint, text, text) FROM PUBLIC",
    "GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state("
    "jsonb, text, text, text, jsonb) TO ktm_feature_create_provider_executor, "
    "ktm_manual_feature_procedure_owner",
    "GRANT EXECUTE ON PROCEDURE feature.transition_feature_state("
    "text, text, text, text, bigint, jsonb) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.author_lifecycle_override("
    "text, text, text, boolean, text, text, bigint) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.revoke_lifecycle_override("
    "text, text, bigint) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.apply_provider_feature_field_patch("
    "text, bigint, text, text, bigint, jsonb, jsonb) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.author_feature_field_overrides("
    "text, bigint, text, text, bigint, jsonb, jsonb) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.revoke_feature_field_overrides("
    "text, bigint, text, text, bigint, text[]) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.transition_admin_feature_state("
    "text, text, text, text, bigint, text, text, text) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.reactivate_admin_feature_state("
    "text, bigint, text, text, bigint, text, text) TO ktm_feature_runtime",
)

_AUDIT_WRITER_FUNCTION_ACL = (
    "REVOKE ALL ON FUNCTION feature.write_feature_state_transition() "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON FUNCTION feature.reject_feature_state_transition_mutation() "
    "FROM PUBLIC, ktm_feature_runtime",
    # 이 trigger function의 owner는 audit writer다. manual procedure owner가
    # revoke하면 별도 grantor ACL은 지워도 owner/public ACL은 지우지 못해 API/Dagster
    # preflight에서 unexpected SECURITY DEFINER function으로 잡힌다.
    "REVOKE ALL ON FUNCTION feature.reject_manual_feature_evidence_mutation() "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_feature_procedure_owner, "
    "ktm_manual_feature_admin_executor, ktm_feature_create_provider_executor",
)

_MANUAL_FEATURE_TABLE_ACL = (
    "REVOKE ALL ON TABLE feature.manual_feature_identity_claims, "
    "feature.feature_creation_origins FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_api_runtime, ktm_feature_dagster_runtime",
    "GRANT SELECT, INSERT ON TABLE feature.manual_feature_identity_claims, "
    "feature.feature_creation_origins TO ktm_manual_feature_procedure_owner",
)

_FEATURE_REQUEST_TABLE_ACL = (
    "REVOKE ALL ON TABLE ops.feature_requests FROM PUBLIC, "
    "ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime",
    "GRANT SELECT, INSERT, UPDATE (status, resolved_at, resolved_by_actor, "
    "resolution_command_id, resolved_feature_id, rejection_reason) "
    "ON TABLE ops.feature_requests TO ktm_feature_request_procedure_owner",
)

# M04 procedure owner는 세 owner로 나뉜 기존 writer를 연쇄 호출한다. dump/restore의
# ``--no-owner --no-privileges``는 이 dependent grant를 보존하지 않으므로, relation
# owner/ routine owner별 reconciler가 매 기동 뒤 정확히 복원한다.
_FEATURE_REQUEST_SCHEMA_OWNER_DEPENDENCY_ACL = (
    "GRANT SELECT, INSERT ON TABLE feature.manual_feature_identity_claims, "
    "feature.feature_creation_origins TO ktm_feature_request_procedure_owner",
    "GRANT SELECT, INSERT, UPDATE (status, resolved_at, resolved_by_actor, "
    "resolution_command_id, resolved_feature_id, rejection_reason) "
    "ON TABLE ops.feature_requests TO ktm_feature_request_procedure_owner",
    "GRANT SELECT, UPDATE(command_id) ON TABLE ops.domain_commands "
    "TO ktm_feature_request_procedure_owner",
    "GRANT SELECT ON TABLE ops.domain_command_results "
    "TO ktm_feature_request_procedure_owner",
)

_FEATURE_REQUEST_MANUAL_OWNER_DEPENDENCY_ACL = (
    "GRANT EXECUTE ON FUNCTION feature.manual_feature_identity_key("
    "text, text, numeric, numeric) TO ktm_feature_request_procedure_owner",
)

_FEATURE_REQUEST_STATE_OWNER_DEPENDENCY_ACL = (
    "GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state("
    "jsonb, text, text, text, jsonb) TO ktm_feature_request_procedure_owner",
)

_MANUAL_FEATURE_WRITER_ACL = (
    "REVOKE ALL ON PROCEDURE feature.create_admin_manual_feature_with_initial_state("
    "jsonb, bigint) FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_feature_create_provider_executor",
    "GRANT EXECUTE ON PROCEDURE feature.create_admin_manual_feature_with_initial_state("
    "jsonb, bigint) TO ktm_manual_feature_admin_executor",
    "REVOKE ALL ON FUNCTION feature.read_admin_manual_feature_provenance(uuid) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_feature_create_provider_executor",
    "GRANT EXECUTE ON FUNCTION feature.read_admin_manual_feature_provenance(uuid) "
    "TO ktm_manual_feature_admin_executor",
    "REVOKE ALL ON FUNCTION feature.manual_feature_identity_key("
    "text, text, numeric, numeric) FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_api_runtime, ktm_feature_dagster_runtime",
    "REVOKE ALL ON FUNCTION feature.reject_manual_feature_hard_purge() "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_feature_procedure_owner, "
    "ktm_manual_feature_admin_executor, ktm_feature_create_provider_executor",
)

_MANUAL_CURATION_WRITER_ACL = (
    "REVOKE ALL ON PROCEDURE feature.create_manual_curation_item_with_feature_command("
    "jsonb, jsonb, bigint) FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
    "ktm_curation_provider_executor, ktm_manual_feature_admin_executor",
    "GRANT EXECUTE ON PROCEDURE feature.create_manual_curation_item_with_feature_command("
    "jsonb, jsonb, bigint) TO ktm_curation_admin_executor",
)

_FEATURE_REQUEST_WRITER_ACL = (
    "REVOKE ALL ON PROCEDURE feature.submit_feature_request(uuid, jsonb, bigint) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_feature_admin_executor, ktm_curation_admin_executor, "
    "ktm_feature_request_admin_executor",
    "GRANT EXECUTE ON PROCEDURE feature.submit_feature_request(uuid, jsonb, bigint) "
    "TO ktm_feature_request_service_executor",
    "REVOKE ALL ON PROCEDURE feature.approve_feature_request_with_initial_state("
    "uuid, jsonb, bigint), feature.reject_feature_request(uuid, text, bigint) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_feature_admin_executor, ktm_curation_admin_executor, "
    "ktm_feature_request_service_executor",
    "GRANT EXECUTE ON PROCEDURE feature.approve_feature_request_with_initial_state("
    "uuid, jsonb, bigint), feature.reject_feature_request(uuid, text, bigint) "
    "TO ktm_feature_request_admin_executor",
    "REVOKE ALL ON FUNCTION feature.read_feature_request(uuid) FROM PUBLIC, "
    "ktm_feature_runtime, ktm_feature_dagster_runtime",
    "GRANT EXECUTE ON FUNCTION feature.read_feature_request(uuid) "
    "TO ktm_feature_request_admin_executor",
    "REVOKE ALL ON FUNCTION feature.list_feature_requests(text, integer) FROM PUBLIC, "
    "ktm_feature_runtime, ktm_feature_dagster_runtime",
    "GRANT EXECUTE ON FUNCTION feature.list_feature_requests(text, integer) "
    "TO ktm_feature_request_admin_executor",
)

_SUBTYPE_READY_FUNCTION_ACL = (
    "REVOKE ALL ON FUNCTION feature.derive_subtype_public_ready() "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON FUNCTION feature.sync_subtype_public_ready() "
    "FROM PUBLIC, ktm_feature_runtime",
)


def _quote_identifier(value: str) -> str:
    """closed inventory name을 PostgreSQL identifier로 rendering한다."""

    return '"' + value.replace('"', '""') + '"'


def _grant_sql(*, schema: str, relation: str, privileges: tuple[str, ...]) -> str:
    return (
        f"GRANT {', '.join(privileges)} ON TABLE "
        f"{_quote_identifier(schema)}.{_quote_identifier(relation)} "
        f"TO {_quote_identifier(_RUNTIME_ROLE)}"
    )


def _sequence_grant_sql(*, schema: str, relation: str) -> str:
    return (
        "GRANT USAGE, SELECT ON SEQUENCE "
        f"{_quote_identifier(schema)}.{_quote_identifier(relation)} "
        f"TO {_quote_identifier(_RUNTIME_ROLE)}"
    )


def _runtime_relation_grants(
    rows: list[Mapping[str, object]],
) -> tuple[list[str], list[str]]:
    """catalog relation inventory를 ACL SQL와 fail-closed unknown 목록으로 바꾼다."""

    grants: list[str] = []
    unknown_relations: list[str] = []
    for row in rows:
        schema = str(row["schema_name"])
        relation = str(row["relation_name"])
        raw_relation_kind = row["relation_kind"]
        # PostgreSQL ``char`` (pg_class.relkind) is returned as ``bytes`` by
        # asyncpg on some builds. ``str(b'S')`` would be ``"b'S'"`` and route
        # the audit sequence into the feature-table unknown-policy path.
        relation_kind = (
            raw_relation_kind.decode("ascii")
            if isinstance(raw_relation_kind, bytes)
            else str(raw_relation_kind)
        )
        if relation_kind == "S":
            if schema == "feature" and (
                relation in _PROTECTED_FEATURE_SEQUENCES
                or relation.startswith("feature_state_transitions_")
            ):
                continue
            grants.append(_sequence_grant_sql(schema=schema, relation=relation))
            continue
        if schema == "feature":
            if relation_kind == "v":
                privileges = _FEATURE_VIEW_PRIVILEGES.get(relation)
                if privileges is None:
                    unknown_relations.append(f"feature.{relation}")
                    continue
                grants.append(
                    _grant_sql(schema=schema, relation=relation, privileges=privileges)
                )
                continue
            if relation in _PROTECTED_FEATURE_TABLES:
                continue
            if relation in _ROUTE_AREA_RUNTIME_INSERT_COLUMNS:
                continue
            privileges = _FEATURE_TABLE_PRIVILEGES.get(relation)
            if privileges is None:
                unknown_relations.append(f"feature.{relation}")
                continue
        elif schema == "ops":
            # `feature`와 같은 강도다. 선언이 없으면 권한을 주지 않고 이름을 들고 멈춘다 —
            # 앞판은 여기서 조용히 full CRUD로 떨어졌다(T-VN-41S 선행).
            #
            # `provider_sync`는 아래 기본값을 그대로 쓴다. 그 스키마는 provider 적재가
            # 소유하는 평범한 데이터라 표마다 좁힐 결정이 없고, 여기서 함께 엄격하게
            # 만들면 이 변경의 범위를 넘는다.
            privileges = _OPS_TABLE_PRIVILEGES.get(relation)
            if privileges is None:
                unknown_relations.append(f"{schema}.{relation}")
                continue
            if not privileges:
                continue
        else:
            privileges = _ORDINARY_SCHEMA_PRIVILEGES[schema]
            if not privileges:
                continue
        grants.append(_grant_sql(schema=schema, relation=relation, privileges=privileges))
    return grants, unknown_relations


async def reconcile_runtime_privileges() -> None:
    """migrator session에서 state/audit 안전 ACL을 post-upgrade로 재조정한다."""

    migrator_dsn = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    if not migrator_dsn:
        raise RuntimePrivilegeReconciliationError(
            "KOR_TRAVEL_MAP_PG_DSN migrator DSN is required for runtime ACL reconciliation"
        )
    engine = make_async_engine(migrator_dsn, pool_size=1)
    try:
        async with engine.begin() as connection:
            identity = (await connection.execute(text("SELECT session_user::text"))).scalar_one()
            if identity != _MIGRATOR_ROLE:
                raise RuntimePrivilegeReconciliationError(
                    "runtime ACL reconciliation requires the dedicated "
                    f"{_MIGRATOR_ROLE} login, not {identity!r}"
                )
            await connection.execute(text(f"SET ROLE {_SCHEMA_OWNER_ROLE}"))
            # Clear stale broad grants left by the pre-ADR-090 bootstrap owner
            # before applying the closed inventory.  This makes a bootstrap of
            # an already-migrated DB safe as well as a fresh DB.
            await connection.execute(
                text(
                    "REVOKE ALL ON ALL TABLES IN SCHEMA feature, provider_sync, ops "
                    "FROM ktm_feature_runtime"
                )
            )
            await connection.execute(
                text(
                    "REVOKE ALL ON ALL SEQUENCES IN SCHEMA feature, provider_sync, ops "
                    "FROM ktm_feature_runtime"
                )
            )
            rows = list((await connection.execute(_APPLICATION_RELATIONS_SQL)).mappings().all())
            grants, unknown_relations = _runtime_relation_grants(
                [cast(Mapping[str, object], row) for row in rows]
            )
            if unknown_relations:
                raise RuntimePrivilegeReconciliationError(
                    "new relation has no deliberate runtime ACL policy: "
                    + ", ".join(unknown_relations)
                )
            for statement in grants:
                await connection.execute(text(statement))
            for statement in _CORE_FEATURE_GRANTS:
                await connection.execute(text(statement))
            for statement in _ROUTE_AREA_RUNTIME_GRANTS:
                await connection.execute(text(statement))
            # Evidence tables remain owned by the schema owner.  The manual
            # SECURITY DEFINER owner only has the narrowly granted INSERT
            # path, so it cannot reconcile relation ACLs itself.
            for statement in _MANUAL_FEATURE_TABLE_ACL:
                await connection.execute(text(statement))
            for statement in _FEATURE_REQUEST_TABLE_ACL:
                await connection.execute(text(statement))
            for statement in _FEATURE_REQUEST_SCHEMA_OWNER_DEPENDENCY_ACL:
                await connection.execute(text(statement))

            # Routine ownership is deliberately split from table ownership.
            # The schema owner has SET-only membership in each NOLOGIN routine
            # owner; runtime identities never receive this path.
            await connection.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
            for statement in _STATE_OWNER_FUNCTION_ACL:
                await connection.execute(text(statement))
            for statement in _SUBTYPE_READY_FUNCTION_ACL:
                await connection.execute(text(statement))
            for statement in _FEATURE_REQUEST_STATE_OWNER_DEPENDENCY_ACL:
                await connection.execute(text(statement))
            await connection.execute(text("SET ROLE ktm_feature_audit_writer"))
            for statement in _AUDIT_WRITER_FUNCTION_ACL:
                await connection.execute(text(statement))
            await connection.execute(text("SET ROLE ktm_manual_feature_procedure_owner"))
            for statement in _MANUAL_FEATURE_WRITER_ACL:
                await connection.execute(text(statement))
            for statement in _FEATURE_REQUEST_MANUAL_OWNER_DEPENDENCY_ACL:
                await connection.execute(text(statement))
            await connection.execute(text("SET ROLE ktm_curation_command_owner"))
            for statement in _MANUAL_CURATION_WRITER_ACL:
                await connection.execute(text(statement))
            await connection.execute(
                text("SET ROLE ktm_feature_request_procedure_owner")
            )
            for statement in _FEATURE_REQUEST_WRITER_ACL:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


def main() -> None:
    """API entrypoint가 Alembic 직후 호출하는 CLI module entrypoint."""

    asyncio.run(reconcile_runtime_privileges())


if __name__ == "__main__":  # pragma: no cover - shell entrypoint가 호출
    main()
