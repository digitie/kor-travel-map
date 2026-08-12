"""T-VN-36B provider patch type-fence diagnostic hardening.

Revision ID: 0101_tvn36_patch_hardening
Revises: 0100_tvn36_override_cmds

Provider patch가 registry type fence를 밟을 때 generic error만 내면 64-field source
payload의 원인을 재현할 수 없다. base validator가 canonical path를 포함해 fail-closed
하도록 만든다. validator의 typed predicate는 0098과 byte-locked 입력에서만 재사용한다.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from alembic import op

# DDL source는 byte-exact SQL 조각을 보존한다.
# ruff: noqa: E501

revision: str = "0101_tvn36_patch_hardening"
down_revision: str | Sequence[str] | None = "0100_tvn36_override_cmds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINEAGE_SPINE_SHA256 = "9bb4a71a6d9b0e8718eee6e243d1518ad4696afb4496c3d32202509695e776e8"
_PROVIDER_PATCH_SHA256 = "60875bfded9f56c08aba607b7b404fff288ffd1d036a682af16a2f6d15535deb"
_OVERRIDE_COMMANDS_SHA256 = "355b42c734fcd77bc4f7c5ec9908906a08a2fa1added2ba74b8df5c413254f99"


def _load_lineage_spine() -> ModuleType:
    """0098 validator source가 바뀐 checkout은 DDL을 만들지 않고 중단한다."""

    path = Path(__file__).with_name("0098_tvn36_override_lineage_spine.py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != _LINEAGE_SPINE_SHA256:
        raise RuntimeError("0098 field override validator source changed")
    spec = importlib.util.spec_from_file_location("_tvn36_lineage_spine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load immutable 0098 field override validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_provider_patch() -> ModuleType:
    """0099 static provider procedure source를 byte-locked 입력으로 읽는다."""

    path = Path(__file__).with_name("0099_tvn36_provider_field_patch.py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != _PROVIDER_PATCH_SHA256:
        raise RuntimeError("0099 provider field patch source changed")
    spec = importlib.util.spec_from_file_location("_tvn36_provider_patch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load immutable 0099 provider field patch")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_override_commands() -> ModuleType:
    """0100 operator command source도 byte-locked static input으로 쓴다."""

    path = Path(__file__).with_name("0100_tvn36_field_override_commands.py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != _OVERRIDE_COMMANDS_SHA256:
        raise RuntimeError("0100 field override command source changed")
    spec = importlib.util.spec_from_file_location("_tvn36_override_commands", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load immutable 0100 field override commands")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_lineage_spine = _load_lineage_spine()
_BASE_VALIDATOR_SQL = (
    cast(Any, _lineage_spine._VALIDATE_BASE_VALUE_FUNCTION_SQL)
    .replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    .replace(
        "RAISE EXCEPTION 'base JSON value does not match registry type'",
        "RAISE EXCEPTION 'base JSON value does not match registry type for %', NEW.field_path",
    )
    .replace(
        "       OR (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "       OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "       OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "       OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "       OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.value_json) <> 'number')\n"
        "       OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.value_json) <> 'number')\n"
        "       OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.value_json) <> 'boolean')\n"
        "       OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.value_json) <> 'object')\n"
        "       OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.value_json) <> 'array') THEN",
        "       OR (NEW.value_json <> 'null'::jsonb AND (\n"
        "              (v_registry.value_kind = 'text' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "           OR (v_registry.value_kind = 'uuid' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "           OR (v_registry.value_kind = 'date' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "           OR (v_registry.value_kind = 'timestamptz' AND jsonb_typeof(NEW.value_json) <> 'string')\n"
        "           OR (v_registry.value_kind = 'integer' AND jsonb_typeof(NEW.value_json) <> 'number')\n"
        "           OR (v_registry.value_kind = 'numeric' AND jsonb_typeof(NEW.value_json) <> 'number')\n"
        "           OR (v_registry.value_kind = 'boolean' AND jsonb_typeof(NEW.value_json) <> 'boolean')\n"
        "           OR (v_registry.value_kind = 'json_object' AND jsonb_typeof(NEW.value_json) <> 'object')\n"
        "           OR (v_registry.value_kind IN ('json_array', 'text_array') AND jsonb_typeof(NEW.value_json) <> 'array')\n"
        "       )) THEN",
        1,
    )
    .replace(
        "IF v_registry.value_kind = 'text_array' AND EXISTS (",
        "IF v_registry.value_kind = 'text_array' AND NEW.value_json <> 'null'::jsonb AND EXISTS (",
        1,
    )
)
_provider_patch = _load_provider_patch()
_PROVIDER_PATCH_SQL = (
    cast(Any, _provider_patch._PROVIDER_PATCH_PROCEDURE_SQL)
    .replace("CREATE PROCEDURE", "CREATE OR REPLACE PROCEDURE", 1)
    .replace(
        "            v_value, v_base_revision, clock_timestamp()",
        "            coalesce(v_value, 'null'::jsonb), v_base_revision, clock_timestamp()",
        1,
    )
)
_override_commands = _load_override_commands()
_AUTHOR_OVERRIDE_SQL = (
    cast(Any, _override_commands._AUTHOR_PROCEDURE_SQL)
    .replace("CREATE PROCEDURE", "CREATE OR REPLACE PROCEDURE", 1)
    .replace(
        "               base.value_json, v_value, false, 'active', btrim(p_reason_code),",
        "               base.value_json, coalesce(v_value, 'null'::jsonb), false, 'active', btrim(p_reason_code),",
        1,
    )
)


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_state_procedure_owner")
    op.execute(_BASE_VALIDATOR_SQL)
    op.execute(_PROVIDER_PATCH_SQL)
    op.execute(_AUTHOR_OVERRIDE_SQL)
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0101 is forward-only; rebuild with the T-VN-36 release head")
