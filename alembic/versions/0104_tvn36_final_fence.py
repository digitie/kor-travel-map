"""T-VN-36D forward-only whole-row freeze removal.

Revision ID: 0104_tvn36_final_fence
Revises: 0103_tvn36_legacy_freeze_replay

The T-VN-36 A--C commands have materialized every effective user/provider
field into the registry, base ledger, and override history.  This revision
therefore removes the temporary whole-row provenance bridge instead of leaving
an executable compatibility path behind.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

# Frozen SQL signatures are deliberately kept verbatim for PostgreSQL.
# ruff: noqa: E501

revision: str = "0104_tvn36_final_fence"
down_revision: str | Sequence[str] | None = "0103_tvn36_freeze_replay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATE_CUTOVER_SHA256 = "bfb460f0446ea4656479d8262e00347918e24a1681b32c56f301a5d2e23b06a6"
_OVERRIDE_COMMAND_SHA256 = "49488c977c31fe290ae43ff05d8ca344de65a1b7f8fb57a3f627b68f6704ed1b"


def _load_source_module(filename: str, expected_sha256: str) -> ModuleType:
    """Use a checked predecessor only to retain its static typed assignment map.

    0100 owns the exhaustive registry-to-column SQL.  Recopying it here would
    create a second mutable allow-list.  The checksum turns an accidental
    predecessor edit into a migration failure rather than silently changing
    the final destructive fence.
    """

    path = Path(__file__).with_name(filename)
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise RuntimeError(f"{filename} changed after the T-VN-36 final-fence freeze")
    spec = importlib.util.spec_from_file_location(f"_tvn36_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _replace_exact(source: str, old: str, new: str, *, count: int = 1) -> str:
    if source.count(old) != count:
        raise RuntimeError("T-VN-36 final-fence predecessor SQL shape changed")
    return source.replace(old, new)


def _final_create_procedure(state_cutover: ModuleType) -> str:
    source = str(state_cutover._CREATE_PROCEDURE_SQL)
    source = _replace_exact(
        source,
        """        raw_refs, lifecycle_state, publication_state, quality_state,
        data_origin, data_version, created_at, updated_at
""",
        """        raw_refs, lifecycle_state, publication_state, quality_state,
        created_at, updated_at
""",
    )
    return _replace_exact(
        source,
        """        p_publication_state, p_quality_state, 'provider', 0,
        clock_timestamp(), clock_timestamp()
""",
        """        p_publication_state, p_quality_state,
        clock_timestamp(), clock_timestamp()
""",
    )


_AUTHOR_REQUEST_GUARD = """    IF (v_operation LIKE 'user.%') <> (p_request_id IS NOT NULL) THEN
        RAISE EXCEPTION 'user override {verb} requires exactly one request receipt'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_request';
    END IF;
    IF p_request_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM ops.feature_change_requests AS request
        WHERE request.request_id = p_request_id
          AND request.feature_id = p_feature_id
          AND request.state = 'applied'
        FOR SHARE
    ) THEN
        RAISE EXCEPTION 'override request receipt is not an applied request for Feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_request';
    END IF;
"""

_REVOKE_REQUEST_GUARD = """    IF (v_operation LIKE 'user.%') <> (p_request_id IS NOT NULL) THEN
        RAISE EXCEPTION 'user override revoke requires exactly one request receipt'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_request';
    END IF;
    IF p_request_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM ops.feature_change_requests AS request
        WHERE request.request_id = p_request_id
          AND request.feature_id = p_feature_id
          AND request.state = 'applied'
        FOR SHARE
    ) THEN
        RAISE EXCEPTION 'override request receipt is not an applied request for Feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_override_request';
    END IF;
"""


def _final_author_procedure(commands: ModuleType) -> str:
    source = str(commands._AUTHOR_PROCEDURE_SQL)
    source = _replace_exact(
        source,
        """    IN p_command_id bigint,
    IN p_request_id uuid,
    IN p_values jsonb,
""",
        """    IN p_command_id bigint,
    IN p_values jsonb,
""",
    )
    source = _replace_exact(
        source,
        """    IF NOT FOUND OR v_operation NOT IN ('admin.feature.override.author', 'user.feature.override.author') THEN
""",
        """    IF NOT FOUND OR v_operation <> 'admin.feature.override.author' THEN
""",
    )
    source = _replace_exact(source, _AUTHOR_REQUEST_GUARD.format(verb="author"), "")
    source = _replace_exact(
        source,
        """            prevent_provider_reactivation, status, reason, command_id, request_id,
            base_revision, created_by, created_at
""",
        """            prevent_provider_reactivation, status, reason, command_id,
            base_revision, created_by, created_at
""",
        count=2,
    )
    source = _replace_exact(
        source,
        """               p_command_id, p_request_id, COALESCE(base.base_revision, v_feature.row_revision),
""",
        """               p_command_id, COALESCE(base.base_revision, v_feature.row_revision),
""",
    )
    return _replace_exact(
        source,
        """               btrim(p_reason_code), p_command_id, p_request_id,
               COALESCE(base.base_revision, v_feature.row_revision), btrim(p_principal),
""",
        """               btrim(p_reason_code), p_command_id,
               COALESCE(base.base_revision, v_feature.row_revision), btrim(p_principal),
""",
    )


def _final_revoke_procedure(commands: ModuleType) -> str:
    source = str(commands._REVOKE_PROCEDURE_SQL)
    source = _replace_exact(
        source,
        """    IN p_command_id bigint,
    IN p_request_id uuid,
    IN p_field_paths text[],
""",
        """    IN p_command_id bigint,
    IN p_field_paths text[],
""",
    )
    source = _replace_exact(
        source,
        """    IF NOT FOUND OR v_operation NOT IN ('admin.feature.override.revoke', 'user.feature.override.revoke') THEN
""",
        """    IF NOT FOUND OR v_operation <> 'admin.feature.override.revoke' THEN
""",
    )
    return _replace_exact(source, _REVOKE_REQUEST_GUARD, "")


def upgrade() -> None:
    state_cutover = _load_source_module(
        "0097_tvn34c_final_state_cutover.py", _STATE_CUTOVER_SHA256
    )
    override_commands = _load_source_module(
        "0100_tvn36_field_override_commands.py", _OVERRIDE_COMMAND_SHA256
    )

    # Procedure-only field writes keep their frozen static field assignment
    # map, but no longer carry a whole-row request UUID or inspect its table.
    op.execute("SET ROLE ktm_feature_state_procedure_owner")
    for statement in (
        "DROP PROCEDURE feature.author_feature_field_overrides(text, bigint, text, text, bigint, uuid, jsonb, jsonb)",
        "DROP PROCEDURE feature.revoke_feature_field_overrides(text, bigint, text, text, bigint, uuid, text[])",
        _final_create_procedure(state_cutover),
        _final_author_procedure(override_commands),
        _final_revoke_procedure(override_commands),
        "ALTER PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) OWNER TO ktm_feature_state_procedure_owner",
        "ALTER PROCEDURE feature.author_feature_field_overrides(text, bigint, text, text, bigint, jsonb, jsonb) OWNER TO ktm_feature_state_procedure_owner",
        "ALTER PROCEDURE feature.revoke_feature_field_overrides(text, bigint, text, text, bigint, text[]) OWNER TO ktm_feature_state_procedure_owner",
        "REVOKE ALL ON PROCEDURE feature.author_feature_field_overrides(text, bigint, text, text, bigint, jsonb, jsonb) FROM PUBLIC",
        "REVOKE ALL ON PROCEDURE feature.revoke_feature_field_overrides(text, bigint, text, text, bigint, text[]) FROM PUBLIC",
        "GRANT EXECUTE ON PROCEDURE feature.author_feature_field_overrides(text, bigint, text, text, bigint, jsonb, jsonb) TO ktm_feature_runtime",
        "GRANT EXECUTE ON PROCEDURE feature.revoke_feature_field_overrides(text, bigint, text, text, bigint, text[]) TO ktm_feature_runtime",
    ):
        op.execute(statement)
    op.execute("SET ROLE ktm_feature_schema_owner")

    # All input was consumed by 0103 before this migration.  Drop the two
    # materializers before their legacy relations, then erase the exact
    # columns/constraints/indexes rather than retaining a nullable shadow.
    for statement in (
        "DROP PROCEDURE feature.replay_legacy_whole_row_freezes(boolean)",
        "DROP PROCEDURE feature.materialize_user_feature_change_provenance(text, text, uuid, text, text, bigint)",
        "DROP PROCEDURE feature.materialize_provider_feature_version(text)",
        "ALTER TABLE ops.feature_overrides DROP CONSTRAINT IF EXISTS fk_feature_overrides_request",
        "ALTER TABLE ops.feature_overrides DROP COLUMN IF EXISTS request_id",
        "DROP TABLE feature.feature_versions",
        "DROP TABLE ops.feature_change_requests",
        "ALTER TABLE feature.features DROP CONSTRAINT IF EXISTS ck_features_data_origin",
        "ALTER TABLE feature.features DROP CONSTRAINT IF EXISTS ck_features_data_version",
        "DROP INDEX IF EXISTS feature.idx_features_data_origin",
        "ALTER TABLE feature.features DROP COLUMN data_origin",
        "ALTER TABLE feature.features DROP COLUMN data_version",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0104 is forward-only; rebuild with the T-VN-36 release head")
