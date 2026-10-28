"""435: ADR-117 — SH 스냅샷·스칼라 정책 경로(411~433)를 퇴역하고 P를 배타 전용으로 남긴다.

prod 측정(2026-10-27)에서 이 경로는 한 번도 돌지 않았다(flag OFF, 정책 0, attempt·artifact 0,
schedule run 0). 이 revision은 그 경로만 지운다.

- 보존 루틴 15개를 다시 쓴다. 434 head의 본문 SHA-256·소유자·종류·SECURITY DEFINER를 고정하고,
  하나라도 다르면 아무것도 바꾸지 않는다.
  - 단건·관리 writer 10개: 434의 regime 진입 줄을 지운다(epoch 표가 없으므로 P를 잡지 않는다).
  - P(`ops.lock_scoped_feature_write_protocol`): 공유 모드를 23514로 거부한다.
  - seal 입력(`_member_provider_curation_input_set`), 권위 finish, shadow 기록기, stamp SD writer:
    스냅샷·활성 정책 분기를 뺀다.
- 그 밖의 SH 전용 루틴 74개, 표 10개, 427 expression index 3개를 지운다(CASCADE 없음).
- 430이 스냅샷 후처리용으로만 준 표 권한을 회수한다.
- prod 사전 조건: 활성 정책 0행, epoch 0, attempt·artifact·control·quota 예약 0행. 아니면 실패.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from sqlalchemy import text

from alembic import op

revision: str = "435_retire_sh_snapshot_path"
down_revision: str | None = "434_protocol_entry_narrowing"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA_OWNER: Final = "ktm_feature_schema_owner"
_STATE_OWNER: Final = "ktm_feature_state_procedure_owner"
_COMMAND_OWNER: Final = "ktm_curation_command_owner"
_REQUEST_OWNER: Final = "ktm_feature_request_procedure_owner"
_MANUAL_OWNER: Final = "ktm_manual_feature_procedure_owner"
#: canonical advisory_lock_key('kortravelmap:pipeline-lineage:mutation')(424와 같다).
_LINEAGE_KEY: Final = 6832465333779826081
_VERSIONS: Final = Path(__file__).parent


class _Routine:
    """434 head의 보존 루틴 하나. 시그니처는 regprocedure로, 본문은 SHA-256으로 고정한다.

    ``replacement``가 있으면 본문 전체를 그 사이드카로 바꾸고, 없으면 ``edits``의 바늘만
    바꾼다. dataclass를 쓰지 않는 이유는 434와 같다(lint가 sys.modules 없이 읽는다).
    """

    __slots__ = (
        "body_sha256",
        "edits",
        "kind",
        "owner",
        "replacement",
        "security_definer",
        "signature",
    )

    def __init__(
        self,
        signature: str,
        owner: str,
        kind: str,
        body_sha256: str,
        *,
        edits: tuple[tuple[str, str], ...] = (),
        replacement: str | None = None,
    ) -> None:
        self.signature = signature
        self.owner = owner
        self.kind = kind
        self.security_definer = True
        self.body_sha256 = body_sha256
        self.edits = edits
        self.replacement = replacement


class _Drop:
    """지울 루틴 하나. identity 인자(pg_get_function_identity_arguments)와 소유자를 고정한다."""

    __slots__ = ("identity", "kind", "name", "owner")

    def __init__(self, name: str, kind: str, owner: str, identity: str) -> None:
        self.name = name
        self.kind = kind
        self.owner = owner
        self.identity = identity


_SINGLE_WRITER_OLD: Final = "\nBEGIN\n  PERFORM ops.lock_single_feature_writer_protocol();\n"
_SINGLE_WRITER_NEW: Final = (
    "\nBEGIN\n  -- 435 ADR-117: 단건 writer는 P를 잡지 않는다(행 잠금과 ADR-111 gate).\n"
)


def _single_writer(signature: str, owner: str, body_sha256: str) -> _Routine:
    return _Routine(
        signature, owner, "p", body_sha256, edits=((_SINGLE_WRITER_OLD, _SINGLE_WRITER_NEW),)
    )


def _sidecar(name: str) -> str:
    return (_VERSIONS / ("_435_" + name + ".sql")).read_text(encoding="utf-8")


#: 434 head에서 산출한 정본. 하나라도 다르면 아무것도 바꾸지 않고 실패한다.
_ROUTINES: Final[Mapping[str, _Routine]] = {
    "feature.approve_feature_request_with_initial_state": _single_writer(
        "feature.approve_feature_request_with_initial_state(uuid,jsonb,bigint)",
        _REQUEST_OWNER,
        "6d2042468d195b521d37384885bbf0f5786e875a407bfc023c50ac1b52d83874",
    ),
    "feature.author_feature_field_overrides": _single_writer(
        "feature.author_feature_field_overrides(uuid,bigint,text,text,bigint,jsonb,jsonb)",
        _STATE_OWNER,
        "e719e68a03186b89834989236c9a0ab9bb00b9f7c5c19b8cb9c5016b90fd58d4",
    ),
    "feature.author_lifecycle_override": _single_writer(
        "feature.author_lifecycle_override(uuid,text,text,boolean,text,text,bigint)",
        _STATE_OWNER,
        "c5cfc756d3bd0dea591ca592a7d300113bc0ce05d7e2a3b50dec0c4febdd718d",
    ),
    "feature.create_admin_manual_feature_with_initial_state": _single_writer(
        "feature.create_admin_manual_feature_with_initial_state(jsonb,bigint)",
        _MANUAL_OWNER,
        "e7d596c613aa11dfb29d0a95589e5a38a44530f7efe0c9168b89770643e819aa",
    ),
    "feature.create_feature_with_initial_state": _single_writer(
        "feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)",
        _STATE_OWNER,
        "aff0297e4a0c6a8fd57a9acadcde909d3466e08f69bb1f32be8dafa8b17ac9fb",
    ),
    "feature.create_provider_feature_with_initial_state": _single_writer(
        "feature.create_provider_feature_with_initial_state(jsonb,jsonb,text,text,text,jsonb)",
        _STATE_OWNER,
        "b6dbaceeeae2da9cd6c3c38c4fdb9cbe9c61aa44c0b5d1fd107e11d6defc27fd",
    ),
    "feature.revoke_feature_field_overrides": _single_writer(
        "feature.revoke_feature_field_overrides(uuid,bigint,text,text,bigint,text[])",
        _STATE_OWNER,
        "93b6e5fe936f14fd7c204cd07aad8f6b4a6956e4c88f502455b0ea5939a0a639",
    ),
    "feature.revoke_lifecycle_override": _single_writer(
        "feature.revoke_lifecycle_override(uuid,text,bigint)",
        _STATE_OWNER,
        "b43febb829fccdd6ae32ead87c205bf2eb28ed7a68c1cd314c0b842b9a8377ff",
    ),
    "feature.transition_admin_feature_state": _single_writer(
        "feature.transition_admin_feature_state(uuid,text,text,text,bigint,text,text,text)",
        _STATE_OWNER,
        "6073e9dae538703c301cbe0076e88e2c14ab420f5274695a5ec331c969ef7bff",
    ),
    "feature.transition_feature_state": _single_writer(
        "feature.transition_feature_state(uuid,text,text,text,bigint,jsonb)",
        _STATE_OWNER,
        "6ea48a04a5dee964554a7c54c1e032576b8de3a41681bb2747ba45858c126515",
    ),
    "ops.lock_scoped_feature_write_protocol": _Routine(
        "ops.lock_scoped_feature_write_protocol(boolean)",
        _STATE_OWNER,
        "f",
        "87678c6dcd2a4a8835809e082ed3df6f8186558ec705d62f1c89c28dc4d63266",
        replacement=_sidecar("lock_scoped_feature_write_protocol"),
    ),
    "feature._member_provider_curation_input_set": _Routine(
        "feature._member_provider_curation_input_set(uuid,bigint,text,text,text)",
        _SCHEMA_OWNER,
        "f",
        "8b22039a4e256e22936a761194417cda04601f7b0ac717975f13972f381139e1",
        replacement=_sidecar("member_provider_curation_input_set"),
    ),
    "feature._record_provider_field_candidates": _Routine(
        "feature._record_provider_field_candidates("
        "uuid,uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb)",
        _STATE_OWNER,
        "p",
        "b4390e3dc5d712c77ba1a6db817b20f37fa59a8b77cb4ae4a8823c32d035a728",
        replacement=_sidecar("record_provider_field_candidates"),
    ),
    "ops.finish_provider_feature_membership_command": _Routine(
        "ops.finish_provider_feature_membership_command("
        "uuid,bigint,text,text,boolean,timestamp with time zone)",
        _COMMAND_OWNER,
        "p",
        "7cc046506cd8b64078f3ecb0fca2a976e6f9da826f8b4ef9adb254b1f4994e73",
        replacement=_sidecar("finish_provider_feature_membership_command"),
    ),
    "feature.upsert_provider_geocode_stamps_ex": _Routine(
        "feature.upsert_provider_geocode_stamps_ex(uuid[],text[],text,text)",
        _STATE_OWNER,
        "f",
        "1d4cfc428f96750f87c8a76d1cfa1f5cd9fa67479375785301867dc30afd55cd",
        replacement=_sidecar("upsert_provider_geocode_stamps_ex"),
    ),
}

#: 434 head에 있고 이 revision이 지우는 루틴. 이름 하나에 오버로드가 더 있으면 실패한다.
_DROPS: Final[tuple[_Drop, ...]] = (
    _Drop("feature._assert_provider_field_projection", "FUNCTION", _STATE_OWNER, "p_feature uuid"),
    _Drop(
        "feature._assert_stamp_projection_guard_inventory",
        "FUNCTION",
        _SCHEMA_OWNER,
        "p_boundary boolean",
    ),
    _Drop(
        "feature._assert_strict_sh_data_guard_inventory",
        "FUNCTION",
        _SCHEMA_OWNER,
        "p_require_all boolean",
    ),
    _Drop("feature._bounded_curation_string_object", "FUNCTION", _SCHEMA_OWNER, "p_value jsonb"),
    _Drop(
        "feature._bounded_provider_curation_input_set",
        "FUNCTION",
        _SCHEMA_OWNER,
        "p_provider_dataset_id bigint",
    ),
    _Drop(
        "feature._exclusive_provider_refresh_context",
        "FUNCTION",
        _STATE_OWNER,
        "p_feature uuid, p_dataset bigint",
    ),
    _Drop(
        "feature._heritage_evidence_inventory",
        "FUNCTION",
        _STATE_OWNER,
        "p_dataset bigint, p_entities text[]",
    ),
    _Drop(
        "feature._heritage_evidence_metadata_bytes",
        "FUNCTION",
        _STATE_OWNER,
        "p_sizes bigint[], p_compressed boolean[], p_caps integer[], p_nullable boolean[]",
    ),
    _Drop("feature._heritage_evidence_retire0", "FUNCTION", _STATE_OWNER, "p_dataset bigint"),
    _Drop(
        "feature._heritage_evidence_shape",
        "FUNCTION",
        _STATE_OWNER,
        "p_raw jsonb, p_base jsonb, p_coord_json jsonb, p_geometry x_extension.geometry",
    ),
    _Drop(
        "feature._heritage_evidence_string_object",
        "FUNCTION",
        _STATE_OWNER,
        "p_value jsonb, p_keys text[]",
    ),
    _Drop("feature._install_provider_field_projection_guards", "FUNCTION", _SCHEMA_OWNER, ""),
    _Drop("feature._install_strict_sh_data_guards", "FUNCTION", _SCHEMA_OWNER, ""),
    _Drop("feature._project_provider_field_candidates", "FUNCTION", _STATE_OWNER, "p_feature uuid"),
    _Drop(
        "feature._provider_field_projection_dependency_active",
        "FUNCTION",
        _STATE_OWNER,
        "p_relation text, p_key text",
    ),
    _Drop("feature._strict_sh_data_context", "FUNCTION", _STATE_OWNER, "p_allow_shared boolean"),
    _Drop("feature._strict_sh_data_statement_guard", "FUNCTION", _STATE_OWNER, ""),
    _Drop("feature._strict_sh_feature_row_guard", "FUNCTION", _STATE_OWNER, ""),
    _Drop("feature._strict_sh_source_row_guard", "FUNCTION", _STATE_OWNER, ""),
    _Drop(
        "feature._transport_airport_evidence_inventory",
        "FUNCTION",
        _STATE_OWNER,
        "p_dataset bigint, p_entities text[]",
    ),
    _Drop(
        "feature._transport_airport_evidence_shape",
        "FUNCTION",
        _STATE_OWNER,
        "p_raw jsonb, p_base jsonb, p_coord_json jsonb, p_geometry x_extension.geometry",
    ),
    _Drop(
        "feature._transport_rest_evidence_inventory",
        "FUNCTION",
        _STATE_OWNER,
        "p_dataset bigint, p_entities text[]",
    ),
    _Drop(
        "feature._transport_rest_evidence_shape",
        "FUNCTION",
        _STATE_OWNER,
        "p_raw jsonb, p_base jsonb, p_coord_json jsonb, p_geometry x_extension.geometry",
    ),
    _Drop(
        "feature._validate_scoped_provider_geocode_stamps",
        "FUNCTION",
        _STATE_OWNER,
        (
            "p_attempt uuid, p_owner uuid, p_manifest_digest text, p_input_digest text, "
            "p_targets jsonb, p_after_source boolean"
        ),
    ),
    _Drop(
        "feature.activate_provider_field_policy",
        "PROCEDURE",
        _STATE_OWNER,
        "IN p_feature uuid, IN p_revision bigint, IN p_fields text[]",
    ),
    _Drop(
        "feature.assert_scoped_candidate_write",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_feature uuid",
    ),
    _Drop(
        "feature.assert_scoped_provider_scalar_target",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_feature uuid, p_dataset bigint, p_entity text, p_revision bigint",
    ),
    _Drop("feature.guard_provider_field_projection", "FUNCTION", _STATE_OWNER, ""),
    _Drop("feature.guard_stamp_writer_entry", "FUNCTION", _STATE_OWNER, ""),
    _Drop("feature.lock_provider_field_policy_epoch", "FUNCTION", _STATE_OWNER, ""),
    _Drop(
        "feature.lock_scoped_provider_geocode_stamps",
        "FUNCTION",
        _STATE_OWNER,
        (
            "p_attempt uuid, p_owner uuid, p_manifest_digest text, p_input_digest text, "
            "p_targets jsonb"
        ),
    ),
    _Drop("feature.provider_field_policy_statement_barrier", "FUNCTION", _STATE_OWNER, ""),
    _Drop(
        "feature.provider_field_scalar_winners",
        "FUNCTION",
        _STATE_OWNER,
        "p_feature_id uuid, p_policy_revision bigint, p_field_paths text[]",
    ),
    _Drop(
        "feature.read_heritage_name_refresh_evidence",
        "FUNCTION",
        _STATE_OWNER,
        "p_dataset bigint, p_entities text[]",
    ),
    _Drop(
        "feature.read_transport_airport_snapshot_evidence",
        "FUNCTION",
        _STATE_OWNER,
        "p_dataset bigint",
    ),
    _Drop(
        "feature.read_transport_rest_snapshot_evidence",
        "FUNCTION",
        _STATE_OWNER,
        "p_dataset bigint",
    ),
    _Drop(
        "feature.recompute_provider_field_candidates",
        "PROCEDURE",
        _STATE_OWNER,
        "IN p_attempt uuid, IN p_feature uuid, IN p_policy_revision bigint",
    ),
    _Drop(
        "feature.record_scoped_provider_field_candidates",
        "PROCEDURE",
        _STATE_OWNER,
        (
            "IN p_attempt uuid, IN p_feature_id uuid, IN p_provider_dataset_id bigint, "
            "IN p_source_entity_key text, IN p_source_record_key text, "
            "IN p_policy_revision bigint, IN p_normalizer_revision text, "
            "IN p_presence_proven boolean, IN p_values jsonb, IN p_geometry_wkt jsonb, "
            "OUT o_field_count integer, OUT o_unresolved_count integer"
        ),
    ),
    _Drop("feature.reject_unsupported_active_scalar_mutation", "FUNCTION", _STATE_OWNER, ""),
    _Drop(
        "feature.reobserve_scoped_provider_geocode_stamps",
        "FUNCTION",
        _STATE_OWNER,
        (
            "p_attempt uuid, p_owner uuid, p_manifest_digest text, p_input_digest text, "
            "p_targets jsonb"
        ),
    ),
    _Drop("feature.validate_active_provider_base_field_value", "FUNCTION", _STATE_OWNER, ""),
    _Drop(
        "feature.validate_exclusive_provider_snapshot",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_dataset bigint, p_targets jsonb, p_entities text[]",
    ),
    _Drop("ops._arm_scoped_feature_write_deadline", "FUNCTION", _STATE_OWNER, ""),
    _Drop("ops._guard_scoped_feature_write_completion", "FUNCTION", _STATE_OWNER, ""),
    _Drop(
        "ops._lock_provider_snapshot_executor",
        "FUNCTION",
        _COMMAND_OWNER,
        "p_snapshot uuid, p_generation bigint, p_fence uuid",
    ),
    _Drop(
        "ops._lock_scoped_feature_write_scope",
        "FUNCTION",
        _STATE_OWNER,
        "p_dataset bigint, p_regions jsonb, p_exclusive boolean",
    ),
    _Drop("ops._lock_snapshot_postprocess_topic_revisions", "FUNCTION", _SCHEMA_OWNER, ""),
    _Drop(
        "ops._locked_scoped_feature_write_attempt",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_owner uuid",
    ),
    _Drop(
        "ops._provider_snapshot_postprocess_receipt",
        "FUNCTION",
        _COMMAND_OWNER,
        "p_snapshot uuid, p_receipt bytea",
    ),
    _Drop(
        "ops.append_scoped_feature_write_manifest",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_owner uuid, p_members jsonb",
    ),
    _Drop(
        "ops.begin_provider_snapshot_apply",
        "FUNCTION",
        _COMMAND_OWNER,
        (
            "p_snapshot uuid, p_generation bigint, p_fence uuid, p_attempt uuid, p_owner uuid, "
            "p_manifest text, p_artifact_sha text"
        ),
    ),
    _Drop(
        "ops.begin_provider_snapshot_postprocess",
        "FUNCTION",
        _COMMAND_OWNER,
        "p_snapshot uuid, p_generation bigint, p_fence uuid, p_receipt bytea",
    ),
    _Drop(
        "ops.begin_scoped_feature_write",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_owner uuid, p_manifest_digest text",
    ),
    _Drop(
        "ops.bind_provider_snapshot_plan",
        "FUNCTION",
        _COMMAND_OWNER,
        (
            "p_snapshot uuid, p_generation bigint, p_fence uuid, p_attempt uuid, p_owner uuid, "
            "p_manifest text, p_kernel_input text"
        ),
    ),
    _Drop(
        "ops.cancel_scoped_feature_write",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_owner uuid",
    ),
    _Drop(
        "ops.capture_provider_snapshot_apply_input_set",
        "FUNCTION",
        _COMMAND_OWNER,
        "p_snapshot uuid, p_generation bigint, p_fence uuid",
    ),
    _Drop(
        "ops.claim_provider_snapshot_executor",
        "FUNCTION",
        _COMMAND_OWNER,
        (
            "p_snapshot uuid, p_artifact_sha text, p_context_sha text, p_lease_seconds integer, "
            "p_generation bigint, p_fence uuid"
        ),
    ),
    _Drop(
        "ops.claim_scoped_feature_write",
        "FUNCTION",
        _STATE_OWNER,
        (
            "p_attempt uuid, p_owner uuid, p_dataset bigint, p_key text, p_regions jsonb, "
            "p_input_digest text, p_expected_members integer, p_lease_seconds integer, "
            "p_exclusive boolean"
        ),
    ),
    _Drop("ops.collect_expired_provider_snapshots", "FUNCTION", _COMMAND_OWNER, "p_limit integer"),
    _Drop("ops.expire_scoped_feature_write_attempt", "FUNCTION", _STATE_OWNER, "p_attempt uuid"),
    _Drop(
        "ops.finish_provider_snapshot_apply",
        "FUNCTION",
        _COMMAND_OWNER,
        "p_snapshot uuid, p_generation bigint, p_fence uuid, p_result bytea",
    ),
    _Drop(
        "ops.finish_provider_snapshot_postprocess",
        "FUNCTION",
        _COMMAND_OWNER,
        "p_snapshot uuid, p_generation bigint, p_fence uuid, p_receipt bytea",
    ),
    _Drop(
        "ops.finish_scoped_feature_write",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_owner uuid, p_result_digest text",
    ),
    _Drop("ops.lock_single_feature_writer_protocol", "FUNCTION", _STATE_OWNER, ""),
    _Drop(
        "ops.provider_snapshot_scalar_counter_state",
        "FUNCTION",
        _COMMAND_OWNER,
        "p_snapshot uuid, p_generation bigint, p_fence uuid, p_items jsonb",
    ),
    _Drop(
        "ops.prune_scoped_feature_write_attempts",
        "FUNCTION",
        _STATE_OWNER,
        "p_before timestamp with time zone, p_limit integer",
    ),
    _Drop(
        "ops.read_provider_snapshot_for_member",
        "FUNCTION",
        _COMMAND_OWNER,
        "p_root uuid, p_child uuid, p_member uuid",
    ),
    _Drop(
        "ops.register_provider_snapshot_artifact",
        "FUNCTION",
        _COMMAND_OWNER,
        (
            "p_root uuid, p_source_job uuid, p_member uuid, p_payload bytea, p_context bytea, "
            "p_native_digest text, p_lease_seconds integer"
        ),
    ),
    _Drop("ops.reject_provider_snapshot_artifact_update", "FUNCTION", _SCHEMA_OWNER, ""),
    _Drop(
        "ops.reset_expired_provider_snapshot_plan",
        "FUNCTION",
        _COMMAND_OWNER,
        (
            "p_snapshot uuid, p_generation bigint, p_fence uuid, p_expected_attempt uuid, "
            "p_expected_owner uuid, p_expected_manifest text"
        ),
    ),
    _Drop(
        "ops.reset_ready_provider_snapshot_plan",
        "FUNCTION",
        _COMMAND_OWNER,
        (
            "p_snapshot uuid, p_generation bigint, p_fence uuid, p_expected_attempt uuid, "
            "p_expected_owner uuid, p_expected_manifest text"
        ),
    ),
    _Drop("ops.scoped_feature_write_membership_digest", "FUNCTION", _STATE_OWNER, "p_feature uuid"),
    _Drop(
        "ops.seal_provider_snapshot_member",
        "PROCEDURE",
        _COMMAND_OWNER,
        (
            "IN p_snapshot uuid, IN p_artifact_sha text, IN p_context_sha text, "
            "IN p_generation bigint, IN p_fence uuid, IN p_result_sha text, "
            "IN p_postprocess_sha text, OUT o_observed_at timestamp with time zone, "
            "OUT o_replayed boolean"
        ),
    ),
    _Drop(
        "ops.seal_scoped_feature_write_manifest",
        "FUNCTION",
        _STATE_OWNER,
        "p_attempt uuid, p_owner uuid",
    ),
)

#: 지우는 표. FK 의존 순서(자식 먼저)다. 표의 trigger는 표와 함께 사라진다.
_TABLES: Final[tuple[str, ...]] = (
    "ops.provider_snapshot_controls",
    "ops.provider_snapshot_quota_reservations",
    "ops.provider_snapshot_quota_limits",
    "ops.provider_snapshot_artifacts",
    "ops.feature_write_manifests",
    "ops.feature_write_attempts",
    "ops.feature_write_region_scopes",
    "ops.feature_write_dataset_scopes",
    "feature.provider_field_active_policies",
    "feature.provider_field_policy_epoch",
)

#: 427 bounded reader 전용 expression index. prod 측정 idx_scan=0(ADR-117 §1).
_INDEXES: Final[tuple[str, ...]] = (
    "provider_sync.ix_source_entity_heads_bounded_evidence_key",
    "provider_sync.ix_source_links_bounded_evidence_key",
    "provider_sync.ix_source_records_bounded_evidence_key",
)

#: prod 사전 조건. 한 번이라도 쓰인 DB를 조용히 끊지 않는다(ADR-117 §3-2).
_PRECONDITION_SQL: Final = """SELECT
 (SELECT count(*) FROM feature.provider_field_active_policies) AS active_policies,
 (SELECT COALESCE(max(epoch),0) FROM feature.provider_field_policy_epoch) AS epoch,
 (SELECT count(*) FROM ops.feature_write_attempts) AS attempts,
 (SELECT count(*) FROM ops.provider_snapshot_artifacts) AS artifacts,
 (SELECT count(*) FROM ops.provider_snapshot_controls) AS controls,
 (SELECT count(*) FROM ops.provider_snapshot_quota_reservations) AS reservations,
 (SELECT count(*) FROM ops.feature_write_manifests) AS manifests,
 (SELECT count(*) FROM ops.feature_write_region_scopes WHERE owner IS NOT NULL) AS region_leases,
 (SELECT count(*) FROM pg_catalog.pg_trigger trigger_row
   JOIN pg_catalog.pg_proc routine ON routine.oid=trigger_row.tgfoid
   JOIN pg_catalog.pg_namespace namespace ON namespace.oid=routine.pronamespace
   WHERE namespace.nspname||'.'||routine.proname = ANY(CAST(:routines AS text[]))
     AND trigger_row.tgrelid <> ALL(CAST(:tables AS regclass[]))) AS activation_triggers
"""

#: 430이 스냅샷 후처리(sync cursor·integrity 관측)용으로만 준 표 권한. baseline에 없고 보존
#: 루틴은 쓰지 않는다. features·source_* SELECT는 baseline에도 있으므로 그대로 둔다.
_SNAPSHOT_TABLE_REVOKES: Final[tuple[str, ...]] = (
    "REVOKE SELECT,UPDATE ON TABLE provider_sync.provider_sync_state FROM " + _COMMAND_OWNER,
    "REVOKE SELECT ON TABLE ops.integrity_finding_observations FROM " + _COMMAND_OWNER,
    "REVOKE SELECT,UPDATE ON TABLE ops.integrity_observation_scopes,"
    "ops.integrity_observation_runs FROM " + _COMMAND_OWNER,
)

_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK(destination_head IN (
        '300',
        '301_m03_import_children',
        '302_m03_child_issuance',
        '303_m05_payload_hash_domain',
        '304_m05_detector_manuals',
        '305_m05_relitigation_fence',
        '306_m02_manual_feature_purge',
        '307_m02_truncate_fence',
        '308_t39_provider_identities',
        '309_t39_feature_id_rekey',
        '310_seoul_source_move',
        '311_seal_member_digest',
        '312_route_geometry_sidecar',
        '313_single_service_role',
        '400',
        '401_retire_map_kma_refresh',
        '402_remove_map_weather_data',
        '403_drop_kma_notice_lineage',
        '404_transport_provider_identity',
        '405_mois_freshness_sla',
        '406_feature_write_gate',
        '407_feature_geocode_stamps',
        '408_kor_travel_geo_releases',
        '409_geo_release_item_reasons',
        '410_provider_field_shadow',
        '411_scoped_feature_write_kernel',
        '412_provider_scalar_projection',
        '413_legacy_sql_protocol_entry',
        '414_manual_dedup_protocol',
        '415_state_lifecycle_protocol',
        '416_field_override_protocol',
        '417_protocol_ex_reentry',
        '418_creation_protocol',
        '419_retire_pg_transport_values',
        '420_exclusive_provider_refresh',
        '421_stamp_writer_boundary',
        '422_heritage_evidence_reader',
        '423_exclusive_context_select',
        '424_tracking_protocol_prefix',
        '425_provider_base_update_first',
        '426_provider_patch_protocol',
        '427_transport_airport_reader',
        '428_bounded_curation_capture',
        '429_strict_sh_data_guards',
        '430_provider_snapshot_recovery',
        '431_transport_rest_reader',
        '432_rest_snapshot_atomic',
        '433_snapshot_ready_plan_reset',
        '434_protocol_entry_narrowing',
        '435_retire_sh_snapshot_path'
    ))
"""


#: 지우는 표의 trigger가 부르는 함수. 표가 먼저 사라져야 지울 수 있다.
_TRIGGER_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"ops._guard_scoped_feature_write_completion", "ops.reject_provider_snapshot_artifact_update"}
)


def _drop_routine(drop: _Drop) -> str:
    return "DROP " + drop.kind + " " + drop.name + "(" + drop.identity + ")"


def _drop_statements() -> tuple[str, ...]:
    """소유자 창마다 루틴을 지우고, 스키마 소유자 창에서 표·index·trigger 함수를 지운다.

    루틴을 표보다 먼저 지운다 — SQL 함수 본문이 표에 의존할 수 있다. trigger 함수만 표 뒤다.
    """
    statements: list[str] = []
    for owner in (_STATE_OWNER, _COMMAND_OWNER, _SCHEMA_OWNER):
        statements.append("SET ROLE " + owner)
        statements.extend(
            _drop_routine(drop)
            for drop in _DROPS
            if drop.owner == owner and drop.name not in _TRIGGER_FUNCTIONS
        )
    statements.extend("DROP TABLE " + table for table in _TABLES)
    statements.extend("DROP INDEX " + index for index in _INDEXES)
    for owner in (_STATE_OWNER, _SCHEMA_OWNER):
        statements.append("SET ROLE " + owner)
        statements.extend(
            _drop_routine(drop)
            for drop in _DROPS
            if drop.owner == owner and drop.name in _TRIGGER_FUNCTIONS
        )
    return tuple(statements)


_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    *_drop_statements(),
    "SET ROLE " + _SCHEMA_OWNER,
    *_SNAPSHOT_TABLE_REVOKES,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def _edited_body(name: str, body: str) -> str:
    """검토한 바늘(또는 사이드카 전체)로만 바꾼다. 하나라도 어긋나면 이 revision은 멈춘다."""
    routine = _ROUTINES[name]
    if hashlib.sha256(body.encode()).hexdigest() != routine.body_sha256:
        raise RuntimeError("434 body changed: " + name)
    if routine.replacement is not None:
        return routine.replacement
    changed = body
    for old, new in routine.edits:
        if changed.count(old) != 1:
            raise RuntimeError("435 edit anchor is not unique: " + name)
        changed = changed.replace(old, new, 1)
    return changed


def _planned_replacements(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """카탈로그 행을 검증하고 ``(name, owner, CREATE OR REPLACE 정의)`` 목록을 돌려준다."""
    if len(rows) != len(_ROUTINES) or {str(r["name"]) for r in rows} != set(_ROUTINES):
        raise RuntimeError("435 routine inventory differs from revision 434")
    replacements: list[tuple[str, str, str]] = []
    for row in rows:
        name = str(row["name"])
        routine = _ROUTINES[name]
        if (
            row["owner"] != routine.owner
            or row["kind"] != routine.kind
            or bool(row["prosecdef"]) is not routine.security_definer
            or row["language"] != "plpgsql"
            or row["definition"].count(row["body"]) != 1
        ):
            raise RuntimeError("435 owner/kind/security/definition changed: " + name)
        changed = _edited_body(name, str(row["body"]))
        replacements.append(
            (name, routine.owner, row["definition"].replace(row["body"], changed, 1))
        )
    return replacements


_CATALOG_SQL: Final = """SELECT n.nspname||'.'||p.proname AS name,p.oid::bigint AS oid,
 r.rolname AS owner,p.prokind::text AS kind,p.prosecdef,l.lanname AS language,
 p.provolatile::text AS volatility,p.proconfig AS config,p.proacl::text[] AS acl,
 p.prosrc AS body,pg_get_functiondef(p.oid) AS definition,
 pg_get_expr(p.proargdefaults,0) AS defaults,p.proargnames AS names,p.proargmodes::text[] AS modes
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 JOIN pg_roles r ON r.oid=p.proowner JOIN pg_language l ON l.oid=p.prolang
 WHERE p.oid=ANY(CAST(:oids AS oid[]))
 ORDER BY n.nspname COLLATE "C",p.proname COLLATE "C"
"""
_PRESERVED: Final = (
    "name",
    "oid",
    "owner",
    "kind",
    "prosecdef",
    "language",
    "volatility",
    "config",
    "acl",
    "defaults",
    "names",
    "modes",
)

#: 지울 이름의 실제 카탈로그(오버로드 포함). 고정 목록과 정확히 같아야 한다.
_DROP_CATALOG_SQL: Final = """SELECT n.nspname||'.'||p.proname AS name,
 CASE p.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END AS kind,
 r.rolname AS owner,pg_get_function_identity_arguments(p.oid) AS identity
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner
 WHERE n.nspname||'.'||p.proname = ANY(CAST(:names AS text[]))
"""


def _assert_preconditions(bind: Any) -> None:
    """정책 활성화(설치된 trigger 포함)나 scope·스냅샷 상태가 하나라도 있으면 지우지 않는다."""
    row = (
        bind.execute(
            text(_PRECONDITION_SQL),
            {
                "routines": sorted({drop.name for drop in _DROPS}),
                "tables": list(_TABLES),
            },
        )
        .mappings()
        .one()
    )
    used = {str(key): int(value) for key, value in row.items() if int(value) != 0}
    if used:
        raise RuntimeError(
            "435 ADR-117 precondition failed — the SH/snapshot path has state: "
            + ", ".join(f"{key}={value}" for key, value in sorted(used.items()))
        )


def _drop_catalog(bind: Any) -> set[tuple[str, str, str, str]]:
    """지울 이름의 실제 카탈로그. identity 문자열은 search_path에 따라 schema 한정이 달라지므로
    (``x_extension.geometry`` 대 ``geometry``) pg_dump와 같은 빈 경로(``pg_catalog``)에서 읽고
    호출자 값으로 되돌린다."""
    prior = str(bind.scalar(text("SELECT current_setting('search_path')")))
    bind.execute(text("SELECT set_config('search_path','pg_catalog',true)"))
    try:
        rows = (
            bind.execute(text(_DROP_CATALOG_SQL), {"names": sorted({d.name for d in _DROPS})})
            .mappings()
            .all()
        )
    finally:
        bind.execute(text("SELECT set_config('search_path',:prior,true)"), {"prior": prior})
    return {(str(r["name"]), str(r["kind"]), str(r["owner"]), str(r["identity"])) for r in rows}


def _assert_drop_inventory(bind: Any) -> None:
    actual = _drop_catalog(bind)
    planned = {(d.name, d.kind, d.owner, d.identity) for d in _DROPS}
    if len(planned) != len(_DROPS) or actual != planned:
        raise RuntimeError(
            "435 drop inventory differs from revision 434: "
            + ", ".join(sorted(item[0] for item in actual ^ planned))
        )


def upgrade() -> None:
    bind = op.get_bind()
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    }
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    # 데이터 writer(P)와 tracking writer(L)를 모두 비운 뒤 지운다. 순서는 P 다음 L이다.
    bind.execute(text("SET ROLE " + _STATE_OWNER))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SELECT pg_advisory_xact_lock(CAST(:key AS bigint))"), {"key": _LINEAGE_KEY})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))
    _assert_preconditions(bind)
    _assert_drop_inventory(bind)
    signatures = [routine.signature for routine in _ROUTINES.values()]
    resolved = bind.execute(
        text(
            "SELECT signature,to_regprocedure(signature)::oid::bigint AS oid "
            "FROM unnest(CAST(:signatures AS text[])) AS signature"
        ),
        {"signatures": signatures},
    ).all()
    missing = sorted(str(signature) for signature, oid in resolved if oid is None)
    if missing:
        raise RuntimeError("435 signature not found in revision 434: " + ", ".join(missing))
    oids = [int(oid) for _signature, oid in resolved]
    rows = bind.execute(text(_CATALOG_SQL), {"oids": oids}).mappings().all()
    replacements = _planned_replacements(rows)

    # 보존 루틴을 먼저 다시 쓴다 — 지울 객체를 부르는 본문이 남지 않게 한다.
    needs_create = sorted(
        {(routine.owner, name.split(".", 1)[0]) for name, routine in _ROUTINES.items()}
    )
    granted: list[tuple[str, str]] = []
    for owner, schema in needs_create:
        if owner == _SCHEMA_OWNER:
            continue
        has_create = bool(
            bind.scalar(
                text("SELECT has_schema_privilege(:owner,:schema,'CREATE')"),
                {"owner": owner, "schema": schema},
            )
        )
        if not has_create:
            # owner/schema는 위 고정 whitelist에서만 온다.
            bind.execute(text("GRANT CREATE ON SCHEMA " + schema + " TO " + owner))
            granted.append((owner, schema))
    for _name, owner, definition in replacements:
        bind.execute(text("SET ROLE " + owner))
        bind.execute(text(definition))
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))
    after = bind.execute(text(_CATALOG_SQL), {"oids": oids}).mappings().all()
    if len(after) != len(rows):
        raise RuntimeError("435 replacement inventory changed")
    for prior_row, updated_row in zip(rows, after, strict=True):
        for key in _PRESERVED:
            if prior_row[key] != updated_row[key]:
                raise RuntimeError("435 replacement metadata changed: " + key)
        name = str(updated_row["name"])
        if updated_row["body"] != _edited_body(name, str(prior_row["body"])):
            raise RuntimeError("435 replacement body differs from its plan: " + name)
    for owner, schema in granted:
        bind.execute(text("REVOKE CREATE ON SCHEMA " + schema + " FROM " + owner))

    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    if _drop_catalog(bind):
        raise RuntimeError("435 left retired routines behind")
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
