"""T-VN-M01 manual Feature identity/origin metadata 계약."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

import kortravelmap.infra.models as models
from kortravelmap.infra.alembic_exclusions import UNMAPPED_APP_TABLES
from kortravelmap.infra.models import (
    FeatureCreationOriginRow,
    ManualFeatureIdentityClaimRow,
)


def _named_constraints(
    table: Any,
    constraint_type: type[Any],
) -> dict[str, Any]:
    return {
        str(constraint.name): constraint
        for constraint in table.constraints
        if isinstance(constraint, constraint_type)
    }


def _column_names(constraint: Any) -> tuple[str, ...]:
    return tuple(constraint.columns.keys())


def _foreign_targets(constraint: ForeignKeyConstraint) -> tuple[str, ...]:
    return tuple(element.target_fullname for element in constraint.elements)


def test_manual_feature_identity_claim_metadata_matches_m00_contract() -> None:
    table = ManualFeatureIdentityClaimRow.__table__

    assert table.schema == "feature"
    assert table.name == "manual_feature_identity_claims"
    assert tuple(table.columns.keys()) == (
        "feature_id",
        "feature_kind",
        "name_key",
        "lon_e6",
        "lat_e6",
        "claimed_by_command_id",
        "claim_basis",
        "claimed_at",
    )
    assert all(column.nullable is False for column in table.columns)
    assert table.primary_key.name == "pk_manual_feature_identity_claims"
    assert tuple(table.primary_key.columns.keys()) == ("feature_id",)

    assert isinstance(table.c.feature_id.type, UUID)
    assert table.c.feature_id.type.as_uuid is False
    assert isinstance(table.c.feature_kind.type, Text)
    assert isinstance(table.c.name_key.type, Text)
    assert table.c.name_key.type.collation == "C"
    assert isinstance(table.c.lon_e6.type, Integer)
    assert isinstance(table.c.lat_e6.type, Integer)
    assert isinstance(table.c.claimed_by_command_id.type, BigInteger)
    assert isinstance(table.c.claim_basis.type, Text)
    assert isinstance(table.c.claimed_at.type, DateTime)
    assert table.c.claimed_at.type.timezone is True

    checks = _named_constraints(table, CheckConstraint)
    assert {name: str(constraint.sqltext) for name, constraint in checks.items()} == {
        "ck_manual_feature_identity_claims_kind": ("feature_kind IN ('place','event')"),
        "ck_manual_feature_identity_claims_name_key": (
            "char_length(name_key) BETWEEN 1 AND 200 AND octet_length(name_key) <= 512"
        ),
        "ck_manual_feature_identity_claims_lon_e6": ("lon_e6 BETWEEN 124000000 AND 132000000"),
        "ck_manual_feature_identity_claims_lat_e6": ("lat_e6 BETWEEN 33000000 AND 39500000"),
        "ck_manual_feature_identity_claims_basis": (
            "claim_basis IN ('manual_create','legacy_admin_route')"
        ),
    }

    unique = _named_constraints(table, UniqueConstraint)
    assert {name: _column_names(constraint) for name, constraint in unique.items()} == {
        "uq_manual_feature_identity_claims_exact": (
            "feature_kind",
            "name_key",
            "lon_e6",
            "lat_e6",
        ),
        "uq_manual_feature_identity_claims_command": ("claimed_by_command_id",),
        "uq_manual_feature_identity_claims_feature_command": (
            "feature_id",
            "claimed_by_command_id",
        ),
    }

    foreign_keys = _named_constraints(table, ForeignKeyConstraint)
    assert set(foreign_keys) == {"fk_manual_feature_identity_claims_command"}
    command_fk = foreign_keys["fk_manual_feature_identity_claims_command"]
    assert _column_names(command_fk) == ("claimed_by_command_id",)
    assert _foreign_targets(command_fk) == ("ops.domain_commands.command_id",)
    assert command_fk.ondelete == "RESTRICT"
    assert "feature.features" not in {
        constraint.referred_table.fullname for constraint in foreign_keys.values()
    }


def test_feature_creation_origin_metadata_matches_m00_contract() -> None:
    table = FeatureCreationOriginRow.__table__

    assert table.schema == "feature"
    assert table.name == "feature_creation_origins"
    assert tuple(table.columns.keys()) == (
        "feature_id",
        "origin_kind",
        "creation_command_id",
        "creator_principal_id",
        "created_by_actor",
        "created_at",
        "invoker_role",
        "procedure_definer",
    )
    assert all(column.nullable is False for column in table.columns)
    assert table.primary_key.name == "pk_feature_creation_origins"
    assert tuple(table.primary_key.columns.keys()) == ("feature_id",)

    assert isinstance(table.c.feature_id.type, UUID)
    assert table.c.feature_id.type.as_uuid is False
    assert isinstance(table.c.origin_kind.type, Text)
    assert isinstance(table.c.creation_command_id.type, BigInteger)
    assert isinstance(table.c.creator_principal_id.type, Text)
    assert isinstance(table.c.created_by_actor.type, Text)
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone is True
    assert isinstance(table.c.invoker_role.type, Text)
    assert isinstance(table.c.procedure_definer.type, Text)

    checks = _named_constraints(table, CheckConstraint)
    assert {name: str(constraint.sqltext) for name, constraint in checks.items()} == {
        "ck_feature_creation_origins_kind": (
            "origin_kind IN ('manual_admin', 'manual_curation', 'manual_request')"
        ),
        "ck_feature_creation_origins_principal": (
            "(origin_kind = 'manual_admin' "
            "AND creator_principal_id = 'admin-ui-bff.manual-feature-create.v1') "
            "OR (origin_kind = 'manual_curation' "
            "AND creator_principal_id = 'admin-ui-bff.manual-curation-feature-create.v1') "
            "OR (origin_kind = 'manual_request' "
            "AND creator_principal_id = 'feature-request.approval.v1')"
        ),
        "ck_feature_creation_origins_actor": (
            "btrim(created_by_actor) <> '' AND char_length(created_by_actor) <= 200"
        ),
        "ck_feature_creation_origins_roles": (
            "(origin_kind = 'manual_admin' "
            "AND invoker_role = 'ktm_feature_api_runtime' "
            "AND procedure_definer = 'ktm_manual_feature_procedure_owner') "
            "OR (origin_kind = 'manual_curation' "
            "AND invoker_role = 'ktm_feature_api_runtime' "
            "AND procedure_definer = 'ktm_curation_command_owner') "
            "OR (origin_kind = 'manual_request' "
            "AND invoker_role = 'ktm_feature_api_runtime' "
            "AND procedure_definer = 'ktm_feature_request_procedure_owner')"
        ),
    }

    unique = _named_constraints(table, UniqueConstraint)
    assert {name: _column_names(constraint) for name, constraint in unique.items()} == {
        "uq_feature_creation_origins_command": ("creation_command_id",),
        "uq_feature_creation_origins_feature_command": ("feature_id", "creation_command_id"),
    }

    foreign_keys = _named_constraints(table, ForeignKeyConstraint)
    assert set(foreign_keys) == {
        "fk_feature_creation_origins_command",
        "fk_feature_creation_origins_claim",
    }
    command_fk = foreign_keys["fk_feature_creation_origins_command"]
    assert _column_names(command_fk) == ("creation_command_id",)
    assert _foreign_targets(command_fk) == ("ops.domain_commands.command_id",)
    assert command_fk.ondelete == "RESTRICT"

    claim_fk = foreign_keys["fk_feature_creation_origins_claim"]
    assert _column_names(claim_fk) == ("feature_id", "creation_command_id")
    assert _foreign_targets(claim_fk) == (
        "feature.manual_feature_identity_claims.feature_id",
        "feature.manual_feature_identity_claims.claimed_by_command_id",
    )
    assert claim_fk.ondelete == "RESTRICT"
    assert "feature.features" not in {
        constraint.referred_table.fullname for constraint in foreign_keys.values()
    }


def test_manual_feature_models_are_public_module_exports() -> None:
    assert "ManualFeatureIdentityClaimRow" in models.__all__
    assert "FeatureCreationOriginRow" in models.__all__


def test_manual_feature_tables_are_mapped_not_excluded_from_alembic() -> None:
    expected = {
        ("feature", "manual_feature_identity_claims"),
        ("feature", "feature_creation_origins"),
    }
    metadata_tables = {
        (table.schema, table.name) for table in models.metadata.tables.values()
    }

    assert metadata_tables >= expected
    assert expected.isdisjoint(UNMAPPED_APP_TABLES)


def test_m01_migration_audits_and_backfills_legacy_claims_before_ddl() -> None:
    """old admin create는 검증된 claim만 남기고 origin을 추정하지 않는다."""

    source = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "retired_versions"
        / "0200-0236"
        / "0226_m01_manual_feature_create.py"
    ).read_text(encoding="utf-8")

    assert "CREATE TEMP TABLE pg_temp.m01_legacy_claim_candidates" in source
    assert "feature.feature_state_transitions" in source
    assert "ops.domain_command_results" in source
    assert "ops.feature_overrides" in source
    assert "'legacy_admin_route'" in source
    assert "M01 legacy claim backfill count/root mismatch" in source
    assert "M01 legacy origin backfill is forbidden" in source
    assert "for statement in _top_level_statements(_LEGACY_BACKFILL_SQL):" in source
