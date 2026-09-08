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
    # 306이 셋을 더했다 — purge 승인 둘과 예약 해제 하나. claim의 두 역할을 가르는
    # 컬럼들이고, 증거 컬럼과 **성질이 다르다**(아래 nullable 단언 참조).
    assert tuple(table.columns.keys()) == (
        "feature_id",
        "feature_kind",
        "name_key",
        "lon_e6",
        "lat_e6",
        "claimed_by_command_id",
        "claim_basis",
        "claimed_at",
        "purged_by_command_id",
        "purged_at",
        "identity_released",
    )
    # **증거 컬럼은 전부 NOT NULL이고 불변이다.** 그것이 M00 계약의 핵심이고 306이
    # 건드리지 않았다. 새 셋만 성질이 다르다 — purge 승인 둘은 "아직 purge되지 않았다"를
    # NULL로 표현해야 하고, 해제 플래그는 기본 false다.
    _EVIDENCE_COLUMNS = (
        "feature_id",
        "feature_kind",
        "name_key",
        "lon_e6",
        "lat_e6",
        "claimed_by_command_id",
        "claim_basis",
        "claimed_at",
    )
    assert all(table.c[name].nullable is False for name in _EVIDENCE_COLUMNS)
    assert table.c.purged_by_command_id.nullable is True
    assert table.c.purged_at.nullable is True
    assert table.c.identity_released.nullable is False
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
        # 306 — 두 컬럼은 항상 함께 채워지고, 살아 있는 Feature의 identity는 놓을 수 없다.
        "ck_manual_feature_identity_claims_purge_pair": (
            "(purged_by_command_id IS NULL) = (purged_at IS NULL)"
        ),
        "ck_manual_feature_identity_claims_release_needs_purge": (
            "NOT identity_released OR purged_by_command_id IS NOT NULL"
        ),
    }

    unique = _named_constraints(table, UniqueConstraint)
    # `uq_..._exact`는 306에서 **부분 유니크 인덱스**가 됐으므로 UniqueConstraint가 아니다
    # — 해제된 claim은 증거로 남되 같은 이름·좌표의 재생성을 막지 않아야 한다.
    assert {name: _column_names(constraint) for name, constraint in unique.items()} == {
        "uq_manual_feature_identity_claims_command": ("claimed_by_command_id",),
        "uq_manual_feature_identity_claims_feature_command": (
            "feature_id",
            "claimed_by_command_id",
        ),
    }

    exact = next(
        index for index in table.indexes
        if index.name == "uq_manual_feature_identity_claims_exact"
    )
    assert exact.unique is True
    assert tuple(exact.columns.keys()) == ("feature_kind", "name_key", "lon_e6", "lat_e6")
    assert "NOT identity_released" in str(
        exact.dialect_options["postgresql"]["where"]
    )

    foreign_keys = _named_constraints(table, ForeignKeyConstraint)
    assert set(foreign_keys) == {
        "fk_manual_feature_identity_claims_command",
        "fk_manual_feature_identity_claims_purge_command",
    }
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
            "AND creator_principal_id IN ("
            "'admin-ui-bff.manual-curation-feature-create.v1', "
            "'admin-ui-bff.curation-import.manual-feature-row.v1')) "
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
