"""Airport 한정 영속 snapshot·strict guard·RC finalization을 한 forward schema로 배선한다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "430_provider_snapshot_recovery"
down_revision: str | None = "429_strict_sh_data_guards"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA_OWNER: Final = "ktm_feature_schema_owner"
_STATE_OWNER: Final = "ktm_feature_state_procedure_owner"
_COMMAND_OWNER: Final = "ktm_curation_command_owner"
_EXECUTOR: Final = "ktm_curation_provider_executor"
_RESTRICTED: Final = "PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_executor"

# filename→(exact routine name, kind, IN signature, owner, newly_created, public_typed)다.
# owner를 실행 후 ALTER로 추측하지 않는다. frozen body의 CREATE 경계만 분리하고 재결합은 exact다.
_SIDECARS: Final = (
    (
        "_430_snapshot_recovery_storage.sql",
        (
            (
                "ops.reject_provider_snapshot_artifact_update",
                "FUNCTION",
                "()",
                _SCHEMA_OWNER,
                True,
                False,
            ),
        ),
    ),
    (
        "_430_snapshot_registration.sql",
        (
            (
                "ops.register_provider_snapshot_artifact",
                "FUNCTION",
                "(uuid,uuid,uuid,bytea,bytea,text,integer)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_parent_scope_order.sql",
        (
            (
                "ops._lock_scoped_feature_write_scope",
                "FUNCTION",
                "(bigint,jsonb,boolean)",
                _STATE_OWNER,
                False,
                False,
            ),
            (
                "ops.begin_scoped_feature_write",
                "FUNCTION",
                "(uuid,uuid,text)",
                _STATE_OWNER,
                False,
                False,
            ),
        ),
    ),
    (
        "_430_tracking_prefix_guards.sql",
        (
            (
                "ops.reject_provider_feature_operation_raw_dml",
                "FUNCTION",
                "()",
                _SCHEMA_OWNER,
                False,
                False,
            ),
            (
                "ops.reject_provider_feature_membership_raw_dml",
                "FUNCTION",
                "()",
                _SCHEMA_OWNER,
                False,
                False,
            ),
            (
                "ops.reject_provider_feature_event_raw_dml",
                "FUNCTION",
                "()",
                _SCHEMA_OWNER,
                False,
                False,
            ),
            (
                "ops.reject_pipeline_cancellation_prefix",
                "FUNCTION",
                "()",
                _SCHEMA_OWNER,
                True,
                False,
            ),
        ),
    ),
    (
        "_430_snapshot_curation_dispatch.sql",
        (
            (
                "feature._member_provider_curation_input_set",
                "FUNCTION",
                "(uuid,bigint,text,text,text)",
                _SCHEMA_OWNER,
                True,
                False,
            ),
        ),
    ),
    (
        "_430_snapshot_executor_lease.sql",
        (
            (
                "ops.claim_provider_snapshot_executor",
                "FUNCTION",
                "(uuid,text,text,integer,bigint,uuid)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_snapshot_recovery_read.sql",
        (
            (
                "ops.read_provider_snapshot_for_member",
                "FUNCTION",
                "(uuid,uuid,uuid)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_snapshot_apply_receipt.sql",
        (
            (
                "ops._lock_provider_snapshot_executor",
                "FUNCTION",
                "(uuid,bigint,uuid)",
                _COMMAND_OWNER,
                True,
                False,
            ),
            (
                "ops.bind_provider_snapshot_plan",
                "FUNCTION",
                "(uuid,bigint,uuid,uuid,uuid,text,text)",
                _COMMAND_OWNER,
                True,
                True,
            ),
            (
                "ops.begin_provider_snapshot_apply",
                "FUNCTION",
                "(uuid,bigint,uuid,uuid,uuid,text,text)",
                _COMMAND_OWNER,
                True,
                True,
            ),
            (
                "ops.finish_provider_snapshot_apply",
                "FUNCTION",
                "(uuid,bigint,uuid,bytea)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_snapshot_apply_counter_state.sql",
        (
            (
                "ops.provider_snapshot_scalar_counter_state",
                "FUNCTION",
                "(uuid,bigint,uuid,jsonb)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_snapshot_expired_plan_reset.sql",
        (
            (
                "ops.reset_expired_provider_snapshot_plan",
                "FUNCTION",
                "(uuid,bigint,uuid,uuid,uuid,text)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_snapshot_postprocess.sql",
        (
            (
                "ops._provider_snapshot_postprocess_receipt",
                "FUNCTION",
                "(uuid,bytea)",
                _COMMAND_OWNER,
                True,
                False,
            ),
            (
                "ops.begin_provider_snapshot_postprocess",
                "FUNCTION",
                "(uuid,bigint,uuid,bytea)",
                _COMMAND_OWNER,
                True,
                True,
            ),
            (
                "ops.finish_provider_snapshot_postprocess",
                "FUNCTION",
                "(uuid,bigint,uuid,bytea)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_snapshot_terminal_gc.sql",
        (
            (
                "ops.collect_expired_provider_snapshots",
                "FUNCTION",
                "(integer)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_snapshot_guard_inventory.sql",
        (
            (
                "feature._assert_strict_sh_data_guard_inventory",
                "FUNCTION",
                "(boolean)",
                _SCHEMA_OWNER,
                True,
                False,
            ),
        ),
    ),
    (
        "_430_snapshot_member_seal.sql",
        (
            (
                "ops.seal_provider_snapshot_member",
                "PROCEDURE",
                "(uuid,text,text,bigint,uuid,text,text)",
                _COMMAND_OWNER,
                True,
                True,
            ),
        ),
    ),
    (
        "_430_snapshot_finalization.sql",
        (
            (
                "ops.lock_provider_feature_tracking_protocol",
                "FUNCTION",
                "(boolean)",
                _COMMAND_OWNER,
                False,
                False,
            ),
            (
                "feature.seal_provider_curation_snapshot_receipt",
                "PROCEDURE",
                "(uuid,bigint,text,text,bigint,text)",
                _COMMAND_OWNER,
                False,
                False,
            ),
            (
                "feature.finalize_provider_curation_root",
                "PROCEDURE",
                "(uuid)",
                _COMMAND_OWNER,
                False,
                False,
            ),
            (
                "feature.purge_manual_feature",
                "PROCEDURE",
                "(uuid,text,boolean,text,bigint)",
                _SCHEMA_OWNER,
                False,
                False,
            ),
            (
                "ops.finish_provider_feature_membership_command",
                "PROCEDURE",
                "(uuid,bigint,text,text,boolean,timestamp with time zone)",
                _COMMAND_OWNER,
                False,
                False,
            ),
        ),
    ),
    (
        "_430_activate_strict_guards.sql",
        (
            (
                "feature.activate_provider_field_policy",
                "PROCEDURE",
                "(uuid,bigint,text[])",
                _STATE_OWNER,
                False,
                False,
            ),
        ),
    ),
)
_CREATE = re.compile(r"^CREATE (?:OR REPLACE )?(FUNCTION|PROCEDURE) ([a-z_]+\.[a-z_]+)\(", re.M)


def _sections(
    filename: str, declarations: tuple[tuple[str, str, str, str, bool, bool], ...]
) -> tuple[tuple[str, str], ...]:
    """고정 sidecar의 CREATE 경계만 owner창으로 나눈다. SQL 문법 parser 대체가 아니다."""
    raw = Path(__file__).with_name(filename).read_text(encoding="utf-8")
    markers = list(_CREATE.finditer(raw))
    if [(m[2], m[1]) for m in markers] != [(row[0], row[1]) for row in declarations]:
        raise ValueError("snapshot sidecar declarations changed: " + filename)
    result: list[tuple[str, str]] = []
    # storage/registration의 첫 CREATE 전 table DDL만 schema owner다.
    first = markers[0].start()
    prefix = raw[:first]
    if "CREATE TABLE" in prefix:
        if filename not in ("_430_snapshot_recovery_storage.sql", "_430_snapshot_registration.sql"):
            raise ValueError("unexpected snapshot table prefix")
        result.append((_SCHEMA_OWNER, prefix))
    else:
        first = 0
    for index, declaration in enumerate(declarations):
        start = first if index == 0 else markers[index].start()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(raw)
        result.append((declaration[3], raw[start:end]))
    if "".join(body for _, body in result) != raw:
        raise ValueError("snapshot sidecar bytes were not preserved")
    return tuple(result)


_RECEIPT_HEAD_CHECK_SQL: Final = """
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
        '430_provider_snapshot_recovery'
    ))
"""


# 이 forward migration의 고정 typed ACL. runtime inventory와 정본unit에서 대조한다.
_SNAPSHOT_PRIVILEGE_WINDOWS: Final = (
    (
        "ktm_feature_schema_owner",
        (
            (
                "DO $snapshot_tables$ BEGIN IF to_regclass('ops.provider_snapshot_artifacts') I"
                "S NOT NULL THEN REVOKE ALL ON TABLE ops.provider_snapshot_artifacts,ops.provid"
                "er_snapshot_controls,ops.provider_snapshot_quota_limits,ops.provider_snapshot_"
                "quota_reservations FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_cur"
                "ation_provider_executor; GRANT SELECT,INSERT,DELETE ON TABLE ops.provider_snap"
                "shot_artifacts TO ktm_curation_command_owner; GRANT SELECT,INSERT,UPDATE,DELET"
                "E ON TABLE ops.provider_snapshot_controls TO ktm_curation_command_owner; GRANT"
                " SELECT,UPDATE ON TABLE ops.provider_snapshot_quota_limits TO ktm_curation_com"
                "mand_owner; GRANT SELECT,INSERT,DELETE ON TABLE ops.provider_snapshot_quota_re"
                "servations TO ktm_curation_command_owner; GRANT SELECT ON TABLE ops.feature_wr"
                "ite_attempts,ops.feature_write_manifests,provider_sync.source_entities,provide"
                "r_sync.source_links,provider_sync.source_records,feature.features,provider_syn"
                "c.provider_sync_state,ops.integrity_finding_observations TO ktm_curation_comma"
                "nd_owner; GRANT UPDATE(provider_dataset_id) ON TABLE provider_sync.provider_sy"
                "nc_state TO ktm_curation_command_owner; GRANT UPDATE(attempt_id) ON TABLE ops."
                "feature_write_attempts TO ktm_curation_command_owner; GRANT SELECT,UPDATE ON T"
                "ABLE ops.integrity_observation_scopes,ops.integrity_observation_runs TO ktm_cu"
                "ration_command_owner; END IF; END $snapshot_tables$"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.reject_provider_snapshot_artifact_update() FROM PUB"
                "LIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.reject_pipeline_cancellation_prefix() FROM PUBLIC,k"
                "tm_feature_runtime,ktm_feature_service,ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION feature._member_provider_curation_input_set(uuid, bigin"
                "t, text, text, text) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_c"
                "uration_provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION feature._member_provider_curation_input_set(uuid, bi"
                "gint, text, text, text) TO ktm_curation_command_owner"
            ),
            (
                "GRANT EXECUTE ON FUNCTION feature._bounded_provider_curation_input_set(bigint)"
                " TO ktm_curation_command_owner"
            ),
            (
                "REVOKE ALL ON FUNCTION feature._assert_strict_sh_data_guard_inventory(boolean)"
                " FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_exe"
                "cutor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION feature._assert_strict_sh_data_guard_inventory(boole"
                "an) TO ktm_curation_command_owner,ktm_feature_service"
            ),
            (
                "DO $snapshot_activation$ BEGIN IF to_regclass('ops.provider_snapshot_artifacts"
                "') IS NOT NULL THEN GRANT EXECUTE ON FUNCTION feature._install_strict_sh_data_"
                "guards() TO ktm_feature_state_procedure_owner; END IF; END $snapshot_activatio"
                "n$"
            ),
        ),
    ),
    (
        "ktm_feature_state_procedure_owner",
        (
            (
                "DO $snapshot_kernel$ BEGIN IF to_regclass('ops.provider_snapshot_artifacts') I"
                "S NOT NULL THEN GRANT EXECUTE ON FUNCTION ops._arm_scoped_feature_write_deadli"
                "ne(),ops._lock_scoped_feature_write_scope(bigint, jsonb, boolean),ops.begin_sc"
                "oped_feature_write(uuid, uuid, text),ops.cancel_scoped_feature_write(uuid, uui"
                "d) TO ktm_curation_command_owner; END IF; END $snapshot_kernel$"
            ),
        ),
    ),
    (
        "ktm_curation_command_owner",
        (
            (
                "REVOKE ALL ON FUNCTION ops.register_provider_snapshot_artifact(uuid, uuid, uui"
                "d, bytea, bytea, text, integer) FROM PUBLIC,ktm_feature_runtime,ktm_feature_se"
                "rvice,ktm_curation_provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.register_provider_snapshot_artifact(uuid, uuid, "
                "uuid, bytea, bytea, text, integer) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.read_provider_snapshot_for_member(uuid, uuid, uuid)"
                " FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_exe"
                "cutor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.read_provider_snapshot_for_member(uuid, uuid, uu"
                "id) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.claim_provider_snapshot_executor(uuid, text, text, "
                "integer, bigint, uuid) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm"
                "_curation_provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.claim_provider_snapshot_executor(uuid, text, tex"
                "t, integer, bigint, uuid) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.bind_provider_snapshot_plan(uuid, bigint, uuid, uui"
                "d, uuid, text, text) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_c"
                "uration_provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.bind_provider_snapshot_plan(uuid, bigint, uuid, "
                "uuid, uuid, text, text) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.begin_provider_snapshot_apply(uuid, bigint, uuid, u"
                "uid, uuid, text, text) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm"
                "_curation_provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.begin_provider_snapshot_apply(uuid, bigint, uuid"
                ", uuid, uuid, text, text) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.finish_provider_snapshot_apply(uuid, bigint, uuid, "
                "bytea) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provid"
                "er_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.finish_provider_snapshot_apply(uuid, bigint, uui"
                "d, bytea) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.provider_snapshot_scalar_counter_state(uuid, bigint"
                ", uuid, jsonb) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curatio"
                "n_provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.provider_snapshot_scalar_counter_state(uuid, big"
                "int, uuid, jsonb) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.reset_expired_provider_snapshot_plan(uuid, bigint, "
                "uuid, uuid, uuid, text) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,kt"
                "m_curation_provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.reset_expired_provider_snapshot_plan(uuid, bigin"
                "t, uuid, uuid, uuid, text) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.begin_provider_snapshot_postprocess(uuid, bigint, u"
                "uid, bytea) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_p"
                "rovider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.begin_provider_snapshot_postprocess(uuid, bigint"
                ", uuid, bytea) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.finish_provider_snapshot_postprocess(uuid, bigint, "
                "uuid, bytea) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_"
                "provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.finish_provider_snapshot_postprocess(uuid, bigin"
                "t, uuid, bytea) TO ktm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops.collect_expired_provider_snapshots(integer) FROM PU"
                "BLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_executor"
            ),
            (
                "GRANT EXECUTE ON FUNCTION ops.collect_expired_provider_snapshots(integer) TO k"
                "tm_curation_provider_executor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops._lock_provider_snapshot_executor(uuid, bigint, uuid"
                ") FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_ex"
                "ecutor"
            ),
            (
                "REVOKE ALL ON FUNCTION ops._provider_snapshot_postprocess_receipt(uuid, bytea)"
                " FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,ktm_curation_provider_exe"
                "cutor"
            ),
            (
                "REVOKE ALL ON PROCEDURE ops.seal_provider_snapshot_member(uuid, text, text, bi"
                "gint, uuid, text, text) FROM PUBLIC,ktm_feature_runtime,ktm_feature_service,kt"
                "m_curation_provider_executor"
            ),
            (
                "GRANT EXECUTE ON PROCEDURE ops.seal_provider_snapshot_member(uuid, text, text,"
                " bigint, uuid, text, text) TO ktm_curation_provider_executor"
            ),
        ),
    ),
)

# Root가 정한 첫 Airport profile의 명시 logical reservation 정책이다. 다른 DS 기본값0.
_GLOBAL_QUOTA_BYTES: Final = 16777216
_GLOBAL_QUOTA_ROWS: Final = 256
_AIRPORT_QUOTA_BYTES: Final = 4194304
_AIRPORT_QUOTA_ROWS: Final = 64
_QUOTA_STATEMENTS: Final = (
    "INSERT INTO ops.provider_snapshot_quota_limits(quota_key,max_bytes,max_rows) "
    "VALUES(0,16777216,256)",
    "INSERT INTO ops.provider_snapshot_quota_limits(quota_key,max_bytes,max_rows) "
    "SELECT provider_dataset_id,4194304,64 FROM provider_sync.provider_datasets "
    "WHERE provider='kor-travel-transport' AND dataset_key='transport_airports' AND is_active",
)


def _upgrade_statements() -> tuple[str, ...]:
    statements = ["SET ROLE " + _SCHEMA_OWNER]
    for filename, declarations in _SIDECARS:
        for owner, body in _sections(filename, declarations):
            statements.extend(("SET ROLE " + owner, body))
    for owner, privileges in _SNAPSHOT_PRIVILEGE_WINDOWS:
        statements.append("SET ROLE " + owner)
        statements.extend(privileges)
    statements.append("SET ROLE " + _SCHEMA_OWNER)
    statements.extend(_QUOTA_STATEMENTS)
    statements.extend((_RECEIPT_HEAD_CHECK_SQL, "SET ROLE " + _SCHEMA_OWNER))
    return tuple(statements)


_UPGRADE_STATEMENTS: Final = _upgrade_statements()
_CREATE_WINDOWS: Final = tuple(
    (owner, schema) for owner in (_STATE_OWNER, _COMMAND_OWNER) for schema in ("feature", "ops")
)


def upgrade() -> None:
    bind = op.get_bind()
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings WHERE name IN "
                "('lock_timeout','statement_timeout')"
            )
        ).all()
    }
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    bind.execute(text("SET ROLE " + _STATE_OWNER))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))
    creates = {}
    for owner, schema in _CREATE_WINDOWS:
        had_create = bool(
            bind.scalar(
                text("SELECT has_schema_privilege(:owner,:schema,'CREATE')"),
                {"owner": owner, "schema": schema},
            )
        )
        creates[owner, schema] = had_create
        if not had_create:
            bind.execute(text("GRANT CREATE ON SCHEMA " + schema + " TO " + owner))
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    for (owner, schema), had_create in creates.items():
        if not had_create:
            bind.execute(text("REVOKE CREATE ON SCHEMA " + schema + " FROM " + owner))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
