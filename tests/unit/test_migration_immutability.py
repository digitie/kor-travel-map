"""이미 병합된 migration 파일 불변성 회귀."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, CheckConstraint

from kortravelmap.infra.models import PoiCacheTargetRow

pytestmark = pytest.mark.unit


def test_0056_provider_refresh_policy_migration_is_immutable() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/0056_provider_refresh_policy_revision.py"
    )

    assert hashlib.sha256(migration.read_bytes()).hexdigest() == (
        "6afd8208489dbc5a6844cf00278b073e0e5463e9db07a15ca9fd5c4454d48a54"
    )


def test_poi_cache_target_metadata_matches_0058_lock_version() -> None:
    table = PoiCacheTargetRow.__table__
    column = table.c.lock_version

    assert isinstance(column.type, BigInteger)
    assert column.nullable is False
    assert column.server_default is not None
    assert str(column.server_default.arg) == "1"
    assert any(
        isinstance(constraint, CheckConstraint)
        and "lock_version >= 1" in str(constraint.sqltext)
        for constraint in table.constraints
    )
