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

이 인벤토리는 **두 스키마 상태**에서 돈다 — ``0236 → 300`` handoff는 baseline
root로 stamp한 직후, finalize/API entrypoint는 head에서. 그래서 루틴은 이름으로만
지목하고 인자 목록은 적용 시점에 ``pg_proc``에서 읽는다. 근거와 fail-closed 규칙은
아래 "routine 참조 해석" 절에 있다.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from kortravelmap.infra.db import make_async_engine

__all__ = [
    "RuntimePrivilegeReconciliationError",
    "reconcile_runtime_privileges",
    "reconcile_runtime_privileges_in_transaction",
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
        column for column in columns if column not in {"feature_id", "kind"}
    )
    for relation, columns in _ROUTE_AREA_RUNTIME_INSERT_COLUMNS.items()
}

#: shadow 컬럼 ``feature_uuid``에 걸던 INSERT 권한 — **컬럼이 있을 때만** 건다.
#:
#: 이 조정기는 head에서만 도는 것이 아니다. `0236 → 300` handoff 실행자
#: (`docker/transition-application-schema-0236-to-300.py`)가 **revision 300에서**
#: 이것을 돌리고, 그 직후의 catalog를 image에 봉인된 immutable reference와
#: sha256으로 대조한다. 그 catalog에는 **컬럼 단위 ACL이 들어 있다.**
#:
#: 309가 shadow 컬럼을 지우면서 이 자리의 `feature_uuid`를 목록에서 뺐더니,
#: 컬럼이 아직 살아 있는 300에서 ACL 두 줄이 사라져 destination catalog가 어긋났다
#: (2026-09-10 실측: `feature_areas`·`feature_routes`의
#: `{ktm_feature_runtime=a/ktm_feature_schema_owner}` 두 행). handoff는
#: "300 destination catalog or seed does not match the immutable reference"로 멎는다.
#:
#: reference는 release 절차(`scripts/build-baseline.sh`)만 다시 만들 수 있고 그것은
#: 살아 있는 0236 컨테이너와 source certificate를 요구한다. 그러므로 **바꿀 수 없는
#: 쪽은 reference이고, 맞춰야 하는 쪽은 조정기다.**
#:
#: 표 단위 선례(`manual_feature_purge_records`의 `to_regclass` 판정)와 같은 형태로
#: 조건부로 만든다. 컬럼은 `to_regclass`로 물을 수 없어 `pg_attribute`를 본다.
_SHADOW_COLUMN_GRANTS = tuple(
    "DO $shadow$ BEGIN"
    " IF EXISTS ("
    "   SELECT 1 FROM pg_catalog.pg_attribute AS attribute"
    "   JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid"
    "   JOIN pg_catalog.pg_namespace AS namespace"
    "     ON namespace.oid = relation.relnamespace"
    "   WHERE namespace.nspname = 'feature'"
    f"     AND relation.relname = '{relation}'"
    "     AND attribute.attname = 'feature_uuid'"
    "     AND attribute.attnum > 0 AND NOT attribute.attisdropped"
    " ) THEN"
    f" EXECUTE 'GRANT INSERT (feature_uuid) ON feature.{relation}"
    " TO ktm_feature_runtime';"
    " END IF; END $shadow$"
    for relation in _ROUTE_AREA_RUNTIME_INSERT_COLUMNS
)

_ROUTE_AREA_RUNTIME_GRANTS = tuple(
    statement
    for relation, insert_columns in _ROUTE_AREA_RUNTIME_INSERT_COLUMNS.items()
    for statement in (
        f"GRANT SELECT ON feature.{relation} TO ktm_feature_runtime",
        f"GRANT INSERT ({', '.join(insert_columns)}) ON feature.{relation} TO ktm_feature_runtime",
        f"GRANT UPDATE ({', '.join(_ROUTE_AREA_RUNTIME_UPDATE_COLUMNS[relation])}) "
        f"ON feature.{relation} TO ktm_feature_runtime",
        f"GRANT SELECT (feature_id, public_ready), UPDATE (public_ready) "
        f"ON feature.{relation} "
        "TO ktm_feature_state_procedure_owner",
    )
) + _SHADOW_COLUMN_GRANTS

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
    # application schema root/finalize의 DB-atomic immutable outbox다. runtime은
    # 직접 읽거나 쓰지 않고 restricted migrator의 recovery command만 조회한다.
    "application_schema_operation_receipts": (),
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
    "curation_import_manual_feature_children": (),
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
        # purge의 복구점. 런타임 role에는 보이지 않는다 — 지워진 Feature의 payload를
        # 통째로 들고 있으므로 origin/claim과 같은 등급이다.
        "manual_feature_purge_records",
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

#: 이 조정기가 관장하는 schema. 아래 SQL과 실패 메시지의 안내가 **같은 값**을 봐야
#: 한다 — 집합이 넓어지는데 안내가 그대로면 "public에 두면 된다"가 거짓이 된다.
_GOVERNED_SCHEMAS: tuple[str, ...] = ("feature", "provider_sync", "ops")
_GOVERNED_SCHEMA_SQL_LIST = ", ".join(f"'{schema}'" for schema in _GOVERNED_SCHEMAS)

#: 이 fence가 배포를 막을 때 운영자가 무엇을 해야 하는지 메시지가 직접 말해야 한다.
#: 예전 문구는 관계 이름만 나열했다 — 새벽에 그것만 보면 "코드를 고쳐 재배포한다" 말고는
#: 길이 없어 보이고, 하필 위험한 migration 직전이 그 상황이다.
#:
#: 탈출구는 **fence를 여는 것이 아니라 관장 밖에 두는 것**이다. 이 조정기는
#: `feature`/`provider_sync`/`ops` 세 schema만 훑으므로(`_APPLICATION_RELATIONS_SQL`),
#: 운영자가 만드는 임시·백업 표는 `public`에 만들면 애초에 걸리지 않는다. env로 여는
#: allowlist는 채택하지 않았다 — fence를 약하게 만들고, 한 번 열면 닫혔는지 아무도
#: 확인하지 않는다.
_UNDECLARED_RELATION_REMEDY = (
    "이 relation들이 애플리케이션 소유라면 이 모듈의 선언 목록에 명시적 정책을 "
    "추가하라(런타임 role이 무엇을 할 수 있는지 한 줄로 적는 것이 이 fence의 목적이다). "
    "위험한 migration 앞에서 만든 임시·백업 표라면 삭제하거나 `public` schema로 옮겨라 "
    "— 이 조정기가 관장하는 것은 "
    + "/".join(_GOVERNED_SCHEMAS)
    + " 뿐이므로 `public`의 표는 배포를 막지 않는다. "
    "`public`은 database owner 소유이므로 migrator 세션에서는 "
    "`SET ROLE ktm_feature_schema_owner` 뒤에 만들거나 옮겨야 한다."
)


def _undeclared_relation_message(unknown_relations: Sequence[str]) -> str:
    return (
        "new relation has no deliberate runtime ACL policy: "
        + ", ".join(unknown_relations)
        + ". "
        + _UNDECLARED_RELATION_REMEDY
    )


_APPLICATION_RELATIONS_SQL = text(
    f"""
    SELECT namespace.nspname AS schema_name, relation.relname AS relation_name,
           relation.relkind AS relation_kind
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ({_GOVERNED_SCHEMA_SQL_LIST})
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
    # ADR-098 claim 축 해석기(309). provider 적재가 "이 원천이 이미 Feature를 갖고
    # 있나"를 묻는 유일한 통로다 — runtime은 `provider_sync`의 표를 직접 못 읽으므로
    # 이 SECURITY DEFINER 함수의 EXECUTE가 그 질문의 전부다.
    "REVOKE ALL ON FUNCTION feature.resolve_provider_feature_id(...) "
    "FROM PUBLIC, ktm_feature_api_runtime, ktm_manual_feature_procedure_owner, "
    "ktm_manual_feature_admin_executor",
    # 생성 wrapper와 **같은 집합**에 준다. 둘은 한 쌍으로 쓰이므로 — claim을 풀어
    # 존재를 묻고, 없으면 wrapper로 만든다 — 한쪽만 부를 수 있는 롤이 있으면 적재가
    # 반쪽으로 죽는다.
    "GRANT EXECUTE ON FUNCTION feature.resolve_provider_feature_id(...) "
    "TO ktm_feature_runtime, ktm_feature_create_provider_executor",
    "REVOKE ALL ON FUNCTION feature.prepare_feature_state_context(...) "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON PROCEDURE feature.create_feature_with_initial_state(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime",
    "REVOKE ALL ON PROCEDURE feature.transition_feature_state(...) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.author_lifecycle_override(...) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.revoke_lifecycle_override(...) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.apply_provider_feature_field_patch(...) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.author_feature_field_overrides(...) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.revoke_feature_field_overrides(...) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.transition_admin_feature_state(...) FROM PUBLIC",
    "REVOKE ALL ON PROCEDURE feature.reactivate_admin_feature_state(...) FROM PUBLIC",
    "GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state(...) "
    "TO ktm_feature_create_provider_executor, ktm_manual_feature_procedure_owner",
    "GRANT EXECUTE ON PROCEDURE feature.transition_feature_state(...) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.author_lifecycle_override(...) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.revoke_lifecycle_override(...) TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.apply_provider_feature_field_patch(...) "
    "TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.author_feature_field_overrides(...) "
    "TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.revoke_feature_field_overrides(...) "
    "TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.transition_admin_feature_state(...) "
    "TO ktm_feature_runtime",
    "GRANT EXECUTE ON PROCEDURE feature.reactivate_admin_feature_state(...) "
    "TO ktm_feature_runtime",
)

_AUDIT_WRITER_FUNCTION_ACL = (
    "REVOKE ALL ON FUNCTION feature.write_feature_state_transition(...) "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON FUNCTION feature.reject_feature_state_transition_mutation(...) "
    "FROM PUBLIC, ktm_feature_runtime",
    # 이 trigger function의 owner는 audit writer다. manual procedure owner가
    # revoke하면 별도 grantor ACL은 지워도 owner/public ACL은 지우지 못해 API/Dagster
    # preflight에서 unexpected SECURITY DEFINER function으로 잡힌다.
    "REVOKE ALL ON FUNCTION feature.reject_manual_feature_evidence_mutation(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_feature_procedure_owner, "
    "ktm_manual_feature_admin_executor, ktm_feature_create_provider_executor",
    # 307의 TRUNCATE 가드 둘. trigger function은 발화 시 EXECUTE 권한을 보지 않으므로
    # 회수해도 fence는 그대로 돈다 — 회수하지 않으면 `db.py`의 startup preflight가
    # "unexpected SECURITY DEFINER function"으로 배포를 막는다(실측으로 잡혔다).
    #
    # 307이 만드므로 baseline root(`300`)에서 도는 이 조정기는 이 둘을 못 볼 수 있다.
    # 그 판정은 종전의 `to_regprocedure` DO block이 아니라 `_OPTIONAL_ROUTINES`가 한다 —
    # DO block은 head에서도 무조건 조용했고, 조용한 건너뜀에는 증인이 없다.
    "REVOKE ALL ON FUNCTION feature.reject_manual_feature_truncate(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_feature_procedure_owner, "
    "ktm_manual_feature_admin_executor, ktm_feature_create_provider_executor",
    "REVOKE ALL ON FUNCTION feature.reject_feature_request_evidence_mutation(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_feature_procedure_owner, "
    "ktm_manual_feature_admin_executor, ktm_feature_create_provider_executor",
)

_MANUAL_FEATURE_TABLE_ACL = (
    "REVOKE ALL ON TABLE feature.manual_feature_identity_claims, "
    "feature.feature_creation_origins FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_api_runtime, ktm_feature_dagster_runtime",
    # `manual_feature_purge_records`는 306이 만든다. 이 조정기는 `300` head에서도
    # 도는데(0236 → 300 handoff 검증), 그 시점에는 표가 없어 이름을 그대로 쓰면
    # `UndefinedTable`로 죽는다 — 304의 함수 REVOKE가 pre-304 DB에서 42883으로 죽은
    # 것과 같은 부류다. 존재할 때만 적용한다.
    #
    # relation은 routine과 달리 시그니처가 없어 이름만으로 정확히 지목된다. 그래서
    # 여기는 `_OPTIONAL_ROUTINES` 경로가 아니라 `to_regclass` 판정을 그대로 둔다.
    "DO $$ BEGIN"
    " IF to_regclass('feature.manual_feature_purge_records') IS NOT NULL THEN"
    " EXECUTE 'REVOKE ALL ON TABLE feature.manual_feature_purge_records"
    " FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime,"
    " ktm_feature_dagster_runtime';"
    " EXECUTE 'GRANT SELECT, INSERT ON TABLE feature.manual_feature_purge_records"
    " TO ktm_manual_feature_procedure_owner';"
    " END IF; END $$",
    "GRANT SELECT, INSERT ON TABLE feature.manual_feature_identity_claims, "
    "feature.feature_creation_origins TO ktm_manual_feature_procedure_owner",
    # purge 프로시저는 schema owner가 definer다(306) — 이 명령이 본질적으로
    # `feature.features`의 cascade 자식 전부를 읽고 지우기 때문이다. 그래서 여기서
    # 좁은 owner에게 추가 권한을 주지 않는다. 좁히는 축은 권한이 아니라 **도달 가능성**이다:
    # 프로시저의 EXECUTE가 PUBLIC에서 회수돼 있고 아무에게도 부여되지 않는다.
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
    "GRANT SELECT ON TABLE ops.domain_command_results TO ktm_feature_request_procedure_owner",
)

_FEATURE_REQUEST_MANUAL_OWNER_DEPENDENCY_ACL = (
    "GRANT EXECUTE ON FUNCTION feature.manual_feature_identity_key(...) "
    "TO ktm_feature_request_procedure_owner",
)

_FEATURE_REQUEST_STATE_OWNER_DEPENDENCY_ACL = (
    "GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state(...) "
    "TO ktm_feature_request_procedure_owner",
)

# M05 owner is a SECURITY DEFINER principal, not a relation owner.  These
# grants are intentionally reconstructed by the schema owner after every
# migration so a ``pg_restore --no-owner --no-privileges`` cannot leave the
# candidate/decision writers callable but unable to revalidate their proof.
_M05_SCHEMA_OWNER_DEPENDENCY_ACL = (
    "GRANT USAGE ON SCHEMA feature, provider_sync, ops, x_extension "
    "TO ktm_manual_provider_dedup_procedure_owner",
    "GRANT SELECT, UPDATE ON TABLE feature.features TO ktm_manual_provider_dedup_procedure_owner",
    "GRANT SELECT ON TABLE feature.manual_feature_identity_claims, "
    "feature.feature_creation_origins "
    "TO ktm_manual_provider_dedup_procedure_owner",
    "GRANT SELECT, UPDATE ON TABLE provider_sync.source_links, "
    "provider_sync.source_entities, provider_sync.source_entity_heads, "
    "provider_sync.source_records "
    "TO ktm_manual_provider_dedup_procedure_owner",
    "GRANT SELECT, UPDATE ON TABLE ops.domain_commands "
    "TO ktm_manual_provider_dedup_procedure_owner",
    "GRANT SELECT ON TABLE ops.domain_command_results TO ktm_manual_provider_dedup_procedure_owner",
    "GRANT SELECT, INSERT, UPDATE ON TABLE ops.manual_provider_dedup_cases, "
    "ops.manual_provider_dedup_resolutions, "
    "ops.feature_reference_reconciliation_events, "
    "ops.feature_reference_reconciliation_subscriptions, "
    "ops.feature_reference_reconciliation_acks "
    "TO ktm_manual_provider_dedup_procedure_owner",
    "GRANT SELECT, INSERT, UPDATE ON TABLE ops.feature_reference_reconciliation_leases "
    "TO ktm_manual_provider_dedup_procedure_owner",
    "GRANT USAGE ON SEQUENCE ops.feature_reference_reconciliation_events_event_sequence_seq "
    "TO ktm_manual_provider_dedup_procedure_owner",
)

_M05_STATE_OWNER_DEPENDENCY_ACL = (
    "GRANT EXECUTE ON PROCEDURE feature.transition_admin_feature_state(...) "
    "TO ktm_manual_provider_dedup_procedure_owner",
)

_M05_WRITER_ACL = (
    "REVOKE ALL ON FUNCTION feature.reject_manual_provider_dedup_evidence_mutation(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime",
    "REVOKE ALL ON FUNCTION feature.assert_feature_reference_reconciliation_lease_cursor(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime",
    "REVOKE ALL ON FUNCTION feature.preflight_feature_reference_reconciliation_ack(...) "
    "FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_provider_dedup_detector_executor, "
    "ktm_manual_provider_dedup_admin_executor, "
    "ktm_feature_reference_reconciliation_service_executor",
    "REVOKE ALL ON FUNCTION feature.preflight_feature_reference_reconciliation_ack_v2(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_provider_dedup_detector_executor, ktm_manual_provider_dedup_admin_executor",
    "GRANT EXECUTE ON FUNCTION feature.preflight_feature_reference_reconciliation_ack_v2(...) "
    "TO ktm_feature_reference_reconciliation_service_executor",
    "REVOKE ALL ON FUNCTION feature.list_manual_provider_dedup_cases(...), "
    "feature.read_manual_provider_dedup_case(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_provider_dedup_detector_executor, "
    "ktm_feature_reference_reconciliation_service_executor",
    "GRANT EXECUTE ON FUNCTION feature.list_manual_provider_dedup_cases(...), "
    "feature.read_manual_provider_dedup_case(...) "
    "TO ktm_manual_provider_dedup_admin_executor",
    "REVOKE ALL ON PROCEDURE feature.record_manual_provider_dedup_candidate(...) "
    "FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_provider_dedup_admin_executor, "
    "ktm_feature_reference_reconciliation_service_executor",
    "GRANT EXECUTE ON PROCEDURE feature.record_manual_provider_dedup_candidate(...) "
    "TO ktm_manual_provider_dedup_detector_executor",
    # T-VN-M05-3(migration 304). detector가 manual origin 대상을 여는 유일한
    # 경로다. 함수 본문의 session_user 검사와 이 ACL이 **둘 다** 막는다 — 하나가
    # 지워졌을 때 다른 하나가 남게 하려는 것이고, 그래서 본문 검사를 가리지
    # 않도록 owner role로 호출하는 게이트를 따로 둔다.
    #
    # **304의 산물이라 없을 수 있다.** 이 조정기는 baseline root(`300`)에서 올라오는
    # DB에서도 돌고(`docker/transition-application-schema-0236-to-300.py`), 304를 되돌린
    # DB에서도 돈다. 이름을 무조건 쓰면 그런 DB에서 42883이 나 **ACL 재조정 트랜잭션
    # 전체가 무효화된다** — 이 두 문장과 무관한 grant까지 같이 날아간다. 그 판정은
    # 종전의 `to_regprocedure` DO block이 아니라 `_OPTIONAL_ROUTINES`가 한다.
    "REVOKE ALL ON FUNCTION feature.list_manual_provider_dedup_detector_manuals(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_provider_dedup_admin_executor, "
    "ktm_feature_reference_reconciliation_service_executor",
    "GRANT EXECUTE ON FUNCTION feature.list_manual_provider_dedup_detector_manuals(...) "
    "TO ktm_manual_provider_dedup_detector_executor",
    "REVOKE ALL ON PROCEDURE feature.resolve_manual_provider_dedup_case(...), "
    "feature.resolve_manual_provider_dedup_case_v2(...) FROM PUBLIC, "
    "ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_provider_dedup_detector_executor, "
    "ktm_manual_provider_dedup_admin_executor, "
    "ktm_feature_reference_reconciliation_service_executor",
    "GRANT EXECUTE ON PROCEDURE feature.resolve_manual_provider_dedup_case_v2(...) "
    "TO ktm_manual_provider_dedup_admin_executor",
    "REVOKE ALL ON PROCEDURE "
    "feature.provision_feature_reference_reconciliation_subscription(...) "
    "FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_provider_dedup_detector_executor, "
    "ktm_feature_reference_reconciliation_service_executor",
    "GRANT EXECUTE ON PROCEDURE "
    "feature.provision_feature_reference_reconciliation_subscription(...) "
    "TO ktm_manual_provider_dedup_admin_executor",
    "REVOKE ALL ON PROCEDURE feature.lease_feature_reference_reconciliation_event(...), "
    "feature.lease_feature_reference_reconciliation_event_v2(...), "
    "feature.ack_feature_reference_reconciliation_event(...), "
    "feature.ack_feature_reference_reconciliation_event_v2(...) FROM PUBLIC, "
    "ktm_feature_runtime, ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_provider_dedup_detector_executor, "
    "ktm_manual_provider_dedup_admin_executor, "
    "ktm_feature_reference_reconciliation_service_executor",
    "GRANT EXECUTE ON PROCEDURE feature.lease_feature_reference_reconciliation_event_v2(...), "
    "feature.ack_feature_reference_reconciliation_event_v2(...) "
    "TO ktm_feature_reference_reconciliation_service_executor",
)

_MANUAL_FEATURE_WRITER_ACL = (
    "REVOKE ALL ON PROCEDURE feature.create_admin_manual_feature_with_initial_state(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_feature_create_provider_executor",
    "GRANT EXECUTE ON PROCEDURE feature.create_admin_manual_feature_with_initial_state(...) "
    "TO ktm_manual_feature_admin_executor",
    "REVOKE ALL ON FUNCTION feature.read_admin_manual_feature_provenance(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_feature_create_provider_executor",
    "GRANT EXECUTE ON FUNCTION feature.read_admin_manual_feature_provenance(...) "
    "TO ktm_manual_feature_admin_executor",
    "REVOKE ALL ON FUNCTION feature.manual_feature_identity_key(...) "
    "FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_api_runtime, ktm_feature_dagster_runtime",
    "REVOKE ALL ON FUNCTION feature.reject_manual_feature_hard_purge(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime, ktm_manual_feature_procedure_owner, "
    "ktm_manual_feature_admin_executor, ktm_feature_create_provider_executor",
)

_MANUAL_CURATION_WRITER_ACL = (
    "REVOKE ALL ON PROCEDURE "
    "feature.create_manual_curation_item_with_feature_command(...) "
    "FROM PUBLIC, ktm_feature_runtime, "
    "ktm_feature_api_runtime, ktm_feature_dagster_runtime, "
    "ktm_curation_provider_executor, ktm_manual_feature_admin_executor",
    "GRANT EXECUTE ON PROCEDURE "
    "feature.create_manual_curation_item_with_feature_command(...) "
    "TO ktm_curation_admin_executor",
)

_FEATURE_REQUEST_WRITER_ACL = (
    "REVOKE ALL ON PROCEDURE feature.submit_feature_request(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_feature_admin_executor, ktm_curation_admin_executor, "
    "ktm_feature_request_admin_executor",
    "GRANT EXECUTE ON PROCEDURE feature.submit_feature_request(...) "
    "TO ktm_feature_request_service_executor",
    "REVOKE ALL ON PROCEDURE feature.approve_feature_request_with_initial_state(...), "
    "feature.reject_feature_request(...) "
    "FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime, "
    "ktm_manual_feature_admin_executor, ktm_curation_admin_executor, "
    "ktm_feature_request_service_executor",
    "GRANT EXECUTE ON PROCEDURE feature.approve_feature_request_with_initial_state(...), "
    "feature.reject_feature_request(...) "
    "TO ktm_feature_request_admin_executor",
    "REVOKE ALL ON FUNCTION feature.read_feature_request(...) FROM PUBLIC, "
    "ktm_feature_runtime, ktm_feature_dagster_runtime",
    "GRANT EXECUTE ON FUNCTION feature.read_feature_request(...) "
    "TO ktm_feature_request_admin_executor",
    "REVOKE ALL ON FUNCTION feature.list_feature_requests(...) FROM PUBLIC, "
    "ktm_feature_runtime, ktm_feature_dagster_runtime",
    "GRANT EXECUTE ON FUNCTION feature.list_feature_requests(...) "
    "TO ktm_feature_request_admin_executor",
)

_SUBTYPE_READY_FUNCTION_ACL = (
    "REVOKE ALL ON FUNCTION feature.derive_subtype_public_ready(...) "
    "FROM PUBLIC, ktm_feature_runtime",
    "REVOKE ALL ON FUNCTION feature.sync_subtype_public_ready(...) "
    "FROM PUBLIC, ktm_feature_runtime",
)

#: `SET ROLE` 창별 ACL 문장. routine ownership은 relation ownership과 의도적으로
#: 갈라져 있다 — runtime identity는 이 `SET ROLE` 경로를 하나도 받지 않는다.
#:
#: 첫 창의 evidence table은 schema owner 소유로 남고, manual SECURITY DEFINER owner는
#: 좁게 부여된 INSERT 경로만 갖는다.
#: provider 적재가 자기 transaction이 쓴 source head/link 집합의 causal seal을 읽는
#: 통로. 함수는 `STABLE SECURITY DEFINER`이고 한 dataset의 집계 넷
#: (entity 수·member 수·마지막 수정일·input set hash)만 돌려준다 — 행 내용은 나오지
#: 않으며, 그 집계의 원천은 같은 transaction이 방금 쓴 데이터다.
#:
#: **이것은 권한 확대가 아니라 유실 복구다.** 은퇴한 `0209_tvn40_provider_curation_seal`
#: 이 `TO ktm_feature_runtime, ktm_curation_command_owner`로 주었는데, 그 문장이
#: baseline으로 접히면서 앞의 하나가 사라졌고 이 모델은 함수를 아예 몰랐다. 그래서
#: 2026-09-11 prod 첫 provider 적재가 `permission denied for function
#: current_provider_curation_input_set`로 멈췄다 — `curation_dataset`을 받는 모든
#: 적재(= snapshot이 아닌 전부)가 이 경로를 지난다.
#:
#: 수여 대상은 새 role이 아니라 **같은 축의 자매 함수가 이미 갖는 그룹**이다.
#: `resolve_provider_feature_id`(ADR-098 claim 해석기)가 `ktm_feature_runtime`에
#: 부여돼 있고, 적재 login `ktm_feature_dagster_runtime`은 그 그룹의 멤버로
#: (`inherit_option=true`, `set_option=false`) 그것을 실행한다. 둘은 한 쌍으로 쓰인다 —
#: claim으로 존재를 묻고, 적재 뒤 seal로 무엇을 썼는지 봉인한다.
_PROVIDER_CURATION_SEAL_ACL = (
    "REVOKE ALL ON FUNCTION feature.current_provider_curation_input_set(...) "
    "FROM PUBLIC, ktm_feature_api_runtime",
    "GRANT EXECUTE ON FUNCTION feature.current_provider_curation_input_set(...) "
    "TO ktm_feature_runtime, ktm_curation_command_owner",
)


_ACL_ROLE_WINDOWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        _SCHEMA_OWNER_ROLE,
        _CORE_FEATURE_GRANTS
        + _ROUTE_AREA_RUNTIME_GRANTS
        + _MANUAL_FEATURE_TABLE_ACL
        + _FEATURE_REQUEST_TABLE_ACL
        + _FEATURE_REQUEST_SCHEMA_OWNER_DEPENDENCY_ACL
        + _M05_SCHEMA_OWNER_DEPENDENCY_ACL
        + _PROVIDER_CURATION_SEAL_ACL,
    ),
    (
        "ktm_feature_state_procedure_owner",
        _STATE_OWNER_FUNCTION_ACL
        + _SUBTYPE_READY_FUNCTION_ACL
        + _FEATURE_REQUEST_STATE_OWNER_DEPENDENCY_ACL
        + _M05_STATE_OWNER_DEPENDENCY_ACL,
    ),
    ("ktm_feature_audit_writer", _AUDIT_WRITER_FUNCTION_ACL),
    (
        "ktm_manual_feature_procedure_owner",
        _MANUAL_FEATURE_WRITER_ACL + _FEATURE_REQUEST_MANUAL_OWNER_DEPENDENCY_ACL,
    ),
    ("ktm_curation_command_owner", _MANUAL_CURATION_WRITER_ACL),
    ("ktm_feature_request_procedure_owner", _FEATURE_REQUEST_WRITER_ACL),
    ("ktm_manual_provider_dedup_procedure_owner", _M05_WRITER_ACL),
)


# ── routine 참조 해석 (ADR-090 inventory × T-VN-39 재키) ──────────────────────
#
# 위 인벤토리는 루틴을 `feature.transition_feature_state(...)`로 지목한다. 인자 목록을
# 적지 않는 것이 **의도**다.
#
# 같은 인벤토리가 두 스키마 상태에서 돈다. `0236 → 300` handoff는 baseline root(`300`)로
# stamp한 직후 이것을 부르고(`docker/transition-application-schema-0236-to-300.py`),
# finalize·API entrypoint·local-dev fresh-300은 head에서 부른다. T-VN-39 재키가 feature
# 식별자를 text에서 uuid로 옮기면서 두 시점의 시그니처가 갈라졌다 — 인벤토리 42개 이름
# 중 11개다. 리터럴 한 벌로는 두 상태를 다 만족시킬 수 없다.
#
# 문장을 두 벌 두는 길은 택하지 않았다. "두 벌이 실제로 두 시점을 서술한다"를 아무 것도
# 강제하지 못하고, `300` 경로는 handoff 테스트 하나로만 밟히므로 한쪽에만 들어간 grant가
# **조용히** 지나간다. 대신 닫히는 축을 시그니처에서 **이름**으로 한 칸 옮긴다.
#
# 인벤토리는 그대로 닫혀 있다 — schema·이름·object 종류·회수 대상·부여 대상이 전부 이
# 파일의 리터럴이고, DB에서 오는 것은 인자 타입 목록 하나뿐이다. 이름이 둘 이상으로
# 해석되면(오버로드) 어느 쪽에 주는지 모호하므로 **부여하지 않고 실패한다**.

#: 인벤토리가 루틴을 지목하는 자리. schema alternation과 이 문자 집합이 곧 이름의
#: 안전성 논증이다 — 여기서 나오는 이름은 정의상 `[a-z_][a-z0-9_]*` 두 조각이다.
_ROUTINE_REFERENCE = re.compile(r"\b(feature|ops|provider_sync)\.([a-z_][a-z0-9_]*)\(\.\.\.\)")

#: 문장이 스스로 선언하는 object 종류. DB의 `prokind`와 대조해 어긋나면 실패한다.
#: 파생하지 않고 대조하는 이유는 소스만 읽어도 무엇에 주는지 보여야 하기 때문이다.
_OBJECT_KEYWORD = re.compile(r"\bON (FUNCTION|PROCEDURE)\b")

#: `prokind` → GRANT/REVOKE가 받는 object 종류. 닫힌 사상이라 값 집합이 둘뿐이다.
#: aggregate(`a`)·window(`w`)는 이 인벤토리의 대상이 아니므로 실패로 떨어진다.
_ROUTINE_KIND_KEYWORD: Mapping[str, str] = {"f": "FUNCTION", "p": "PROCEDURE"}

#: `format_type`이 낸 인자 목록에 허용하는 형태. 이 문자열이 이 조정기가 실행하는 SQL
#: 중 **유일한 DB 파생 텍스트**이므로 실행 전에 화이트리스트로 검증한다. 따옴표·
#: 세미콜론·괄호가 문자 집합에 아예 없다. schema 한정 접두는 미래 대비다 — 오늘
#: governed 3개 schema에 `CREATE DOMAIN`은 0건이고 인자 타입은 전부 `pg_catalog` 내장이다.
_ARGUMENT_TYPE = r"(?:[a-z_][a-z0-9_]*\.)?[a-z][a-z0-9_ ]*(?:\[\])*"
_ARGUMENT_TYPES = re.compile(rf"(?:{_ARGUMENT_TYPE}(?:, {_ARGUMENT_TYPE})*)?")

#: 이 조정기가 도는 시점에 **아직 없을 수 있는** 루틴과 그것을 만드는 revision.
#: 닫힌 집합이고, 이름이 느는 것 자체가 리뷰 신호다.
#:
#: `0236 → 300` handoff는 `300`에 stamp한 직후 이 조정기를 부른다. 301~309는 그 뒤
#: 평범한 `alembic upgrade`가 올리므로 그 시점에는 아래 셋이 없다.
#:
#: 여기 **없는** 이름이 해석되지 않으면 조용히 넘어가지 않고 실패한다. 그리고 이 셋이
#: head에는 반드시 있어야 한다는 것은 런타임의 추측이 아니라
#: `tests/lint/test_db_procedure_signatures_exist_in_head.py`가 head 오라클에 대고
#: 정적으로 고정한다 — 배포가 아니라 머지를 막는 쪽이 더 이르다.
_OPTIONAL_ROUTINES: Mapping[str, str] = {
    "feature.list_manual_provider_dedup_detector_manuals": "304_m05_detector_manual_listing",
    "feature.reject_feature_request_evidence_mutation": "307_m02_truncate_fence",
    "feature.reject_manual_feature_truncate": "307_m02_truncate_fence",
    "feature.resolve_provider_feature_id": "309_t39_feature_id_rekey",
}

#: 인벤토리가 지목하는 루틴 전부. `db.py`의 head 전용 preflight 목록과 달리 이것은
#: **이 조정기가 ACL을 거는 대상**이고, lint가 두 오라클에 이름으로 묶는다.
_DECLARED_ROUTINES: frozenset[str] = frozenset(
    f"{schema}.{name}"
    for _role, _statements in _ACL_ROLE_WINDOWS
    for _statement in _statements
    for schema, name in _ROUTINE_REFERENCE.findall(_statement)
)

_STALE_OPTIONAL_ROUTINES = tuple(sorted(set(_OPTIONAL_ROUTINES) - _DECLARED_ROUTINES))
if _STALE_OPTIONAL_ROUTINES:  # pragma: no cover - import 시점 fence
    raise RuntimePrivilegeReconciliationError(
        "`_OPTIONAL_ROUTINES`가 인벤토리에 없는 이름을 들고 있다: "
        + ", ".join(_STALE_OPTIONAL_ROUTINES)
        + ". 문장을 지웠다면 이 예외 목록에서도 지워라 — 남아 있으면 '없어도 된다'는 "
        "판정만 남고 지킬 대상이 없다."
    )

#: 선언된 이름의 이 시점 실체를 카탈로그에서 읽는다. 바인드도 보간도 없다 — schema
#: 목록은 이 모듈의 `_GOVERNED_SCHEMAS` 상수이고, 이름 필터는 Python에서 한다.
#:
#: `proargtypes`는 IN/INOUT/VARIADIC만 담는다(OUT은 `proallargtypes`에 있다). 그것이
#: PostgreSQL의 routine identity이자 GRANT/REVOKE가 받는 인자 목록이다.
_ROUTINE_SIGNATURES_SQL = text(
    f"""
    SELECT namespace.nspname AS schema_name,
           routine.proname AS routine_name,
           routine.prokind AS routine_kind,
           COALESCE(
               (
                   SELECT string_agg(
                              pg_catalog.format_type(argument.type_oid, NULL),
                              ', ' ORDER BY argument.arg_position
                          )
                   FROM unnest(routine.proargtypes::oid[])
                       WITH ORDINALITY AS argument(type_oid, arg_position)
               ),
               ''
           ) AS argument_types
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname IN ({_GOVERNED_SCHEMA_SQL_LIST})
    """
)


@dataclass(frozen=True, slots=True)
class _ResolvedRoutine:
    """카탈로그가 말하는 루틴의 실체 — object 종류와 IN 인자 타입 목록."""

    keyword: str
    argument_types: str


def _resolve_declared_routines(
    rows: Sequence[Mapping[str, object]],
) -> Mapping[str, _ResolvedRoutine]:
    """카탈로그 행에서 선언된 이름만 골라 이 시점의 시그니처를 확정한다.

    이름 하나가 둘 이상으로 해석되면(오버로드) 어느 쪽에 주는지 모호하므로 **실패한다.**
    이것은 편의가 아니라 방어다 — governed schema에 CREATE를 가진 자가 오버로드를 심으면
    이름 해석이 그쪽으로 갈 수 있고, 이 규칙이 그 포획을 원천 차단한다.
    """

    candidates: dict[str, list[_ResolvedRoutine]] = {}
    for row in rows:
        qualified = f"{row['schema_name']!s}.{row['routine_name']!s}"
        if qualified not in _DECLARED_ROUTINES:
            continue
        raw_kind = row["routine_kind"]
        # asyncpg는 PostgreSQL ``char``(여기서는 ``prokind``)를 build에 따라 bytes로
        # 준다 — ``relkind``와 같은 부류다(`_runtime_relation_grants` 참조).
        kind = raw_kind.decode("ascii") if isinstance(raw_kind, bytes) else str(raw_kind)
        keyword = _ROUTINE_KIND_KEYWORD.get(kind)
        if keyword is None:
            raise RuntimePrivilegeReconciliationError(
                f"declared routine {qualified} has an unsupported pg_proc.prokind {kind!r}; "
                "this inventory only governs plain functions and procedures"
            )
        argument_types = str(row["argument_types"])
        if _ARGUMENT_TYPES.fullmatch(argument_types) is None:
            raise RuntimePrivilegeReconciliationError(
                f"catalog-derived argument list for {qualified} is not a plain type list: "
                f"{argument_types!r}"
            )
        candidates.setdefault(qualified, []).append(
            _ResolvedRoutine(keyword=keyword, argument_types=argument_types)
        )
    ambiguous = sorted(
        f"{name} → "
        + ", ".join(f"({resolved.argument_types})" for resolved in sorted(found, key=_signature))
        for name, found in candidates.items()
        if len(found) > 1
    )
    if ambiguous:
        raise RuntimePrivilegeReconciliationError(
            "routine name resolves to more than one overload and the ACL target is ambiguous: "
            + "; ".join(ambiguous)
            + ". 이 인벤토리는 이름당 루틴 하나를 전제한다. 오버로드를 의도했다면 "
            "인벤토리를 시그니처로 분기해 선언하라. 의도하지 않았다면 남은 쪽을 DROP하라 "
            "— 모호한 채로 EXECUTE를 주지는 않는다."
        )
    return {name: found[0] for name, found in candidates.items()}


def _signature(resolved: _ResolvedRoutine) -> str:
    return resolved.argument_types


def _render_acl_statement(statement: str, routines: Mapping[str, _ResolvedRoutine]) -> str | None:
    """인벤토리 문장의 routine 참조를 이 시점의 시그니처로 채운다.

    아직 만들어지지 않은 optional 루틴만 지목하는 문장은 ``None``(건너뜀)이다.
    """

    references = [f"{schema}.{name}" for schema, name in _ROUTINE_REFERENCE.findall(statement)]
    if not references:
        return statement
    missing = sorted({name for name in references if name not in routines})
    if missing:
        undeclared = [name for name in missing if name not in _OPTIONAL_ROUTINES]
        if undeclared:
            raise RuntimePrivilegeReconciliationError(
                "declared routine does not exist in this database: "
                + ", ".join(undeclared)
                + ". 이름이 바뀌었거나 오타이거나, 아직 만들어지지 않은 것이라면 "
                "`_OPTIONAL_ROUTINES`에 그것을 만드는 revision과 함께 적어라."
            )
        present = sorted({name for name in references if name in routines})
        if present:
            raise RuntimePrivilegeReconciliationError(
                f"one ACL statement mixes absent optional routines {missing} with "
                f"present ones {present}. 문장을 통째로 건너뛰면 present 쪽 ACL이 "
                "조용히 사라진다 — 루틴별로 문장을 나눠 선언하라."
            )
        return None
    declared_keyword = _OBJECT_KEYWORD.search(statement)
    if declared_keyword is None:
        raise RuntimePrivilegeReconciliationError(
            "ACL statement names a routine but does not declare FUNCTION or PROCEDURE: "
            f"{statement!r}"
        )
    keyword = declared_keyword.group(1)
    mismatched = sorted(
        f"{name} is declared {keyword} but the catalog has {routines[name].keyword}"
        for name in set(references)
        if routines[name].keyword != keyword
    )
    if mismatched:
        raise RuntimePrivilegeReconciliationError(
            "ACL statement declares the wrong routine kind: "
            + "; ".join(mismatched)
            + ". 사이드카가 종류를 바꿨다면 이 인벤토리도 같이 바꿔라 — 리터럴 키워드가 "
            "조용히 틀리는 경로를 막으려고 대조한다."
        )

    def _fill(match: re.Match[str]) -> str:
        qualified = f"{match.group(1)}.{match.group(2)}"
        return f"{qualified}({routines[qualified].argument_types})"

    return _ROUTINE_REFERENCE.sub(_fill, statement)


def _render_acl_statements(
    statements: Sequence[str], routines: Mapping[str, _ResolvedRoutine]
) -> tuple[str, ...]:
    """한 `SET ROLE` 창의 문장 전부를 rendering한다 — 첫 실행 전에 끝난다."""

    rendered = (_render_acl_statement(statement, routines) for statement in statements)
    return tuple(statement for statement in rendered if statement is not None)


async def _resolve_routine_signatures(
    connection: AsyncConnection,
) -> Mapping[str, _ResolvedRoutine]:
    """인벤토리 이름을 이 DB 시점의 시그니처로 해석한다.

    ``search_path``를 고정하고 읽는다. ``format_type``은 타입 이름을 schema 한정할지를
    ``search_path``로 정하는데 이 조정기의 호출 경로들은 서로 다른 ``search_path``를
    갖는다(전환 스크립트는 ``public, x_extension``, 나머지는 기본값). 고정하지 않으면
    같은 인벤토리가 경로마다 다른 문자열을 낼 수 있다. ``pg_catalog``는 누구나 읽으므로
    추가 권한이 필요 없고, ``is_local``이라 이 transaction 밖으로 새지 않는다.
    """

    previous_search_path = str(
        (await connection.execute(text("SELECT current_setting('search_path')"))).scalar_one()
    )
    await connection.execute(text("SELECT set_config('search_path', 'pg_catalog', true)"))
    result = await connection.execute(_ROUTINE_SIGNATURES_SQL)
    rows = [cast(Mapping[str, object], row) for row in result.mappings().all()]
    await connection.execute(
        text("SELECT set_config('search_path', :previous, true)"),
        {"previous": previous_search_path},
    )
    return _resolve_declared_routines(rows)


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
                grants.append(_grant_sql(schema=schema, relation=relation, privileges=privileges))
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


async def reconcile_runtime_privileges_in_transaction(
    connection: AsyncConnection,
) -> None:
    """호출자가 소유한 transaction 안에서 exact runtime ACL을 적용한다."""

    identity = (await connection.execute(text("SELECT session_user::text"))).scalar_one()
    if identity != _MIGRATOR_ROLE:
        raise RuntimePrivilegeReconciliationError(
            "runtime ACL reconciliation requires the dedicated "
            f"{_MIGRATOR_ROLE} login, not {identity!r}"
        )
    await connection.execute(text(f"SET ROLE {_SCHEMA_OWNER_ROLE}"))
    # 해석·검증·존재 판정을 **첫 ACL 문장 전에** 전부 끝낸다. 이 조정기는 호출자의
    # transaction 안에서 돌므로 어떤 실패든 결국 rollback되지만, 여기서 먼저 끝내면
    # 실패가 "무엇이 어긋났는가"를 들고 나오지 "어디까지 적용됐는가"를 남기지 않는다.
    routines = await _resolve_routine_signatures(connection)
    role_windows = tuple(
        (role, _render_acl_statements(statements, routines))
        for role, statements in _ACL_ROLE_WINDOWS
    )
    # Clear stale broad grants left by the pre-ADR-090 bootstrap owner before
    # applying the closed inventory. This also makes an existing 0236 → 300
    # handoff atomic with the least-privilege destination catalog.
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
            _undeclared_relation_message(unknown_relations)
        )
    for statement in grants:
        await connection.execute(text(statement))
    for role, statements in role_windows:
        await connection.execute(text(f"SET ROLE {role}"))
        for statement in statements:
            await connection.execute(text(statement))
    # 호출자는 이어서 destination catalog receipt를 같은 transaction에서 읽는다.
    await connection.execute(text(f"SET ROLE {_SCHEMA_OWNER_ROLE}"))


async def reconcile_runtime_privileges() -> None:
    """migrator session에서 state/audit 안전 ACL을 atomic하게 재조정한다."""

    migrator_dsn = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    if not migrator_dsn:
        raise RuntimePrivilegeReconciliationError(
            "KOR_TRAVEL_MAP_PG_DSN migrator DSN is required for runtime ACL reconciliation"
        )
    engine = make_async_engine(migrator_dsn, pool_size=1)
    try:
        async with engine.begin() as connection:
            await reconcile_runtime_privileges_in_transaction(connection)
    finally:
        await engine.dispose()


def main() -> None:
    """API entrypoint가 Alembic 직후 호출하는 CLI module entrypoint."""

    asyncio.run(reconcile_runtime_privileges())


if __name__ == "__main__":  # pragma: no cover - shell entrypoint가 호출
    main()
