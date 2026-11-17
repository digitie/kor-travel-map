"""453 — ``feature.features``의 표 단위 autovacuum 문턱(읽기 성능 계획 T-READ-08).

표의 reloptions가 migration 상수와 같다 — 설정이 빠지거나 값이 바뀌면 빨갛다.
(``ALTER TABLE … SET (autovacuum_…)``은 PostgreSQL에서 표를 다시 쓰지 않는다 — 시험으로는
항진명제라 두지 않는다.)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "453_features_autovacuum.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ktm_rev_453", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _features_reloptions(session: AsyncSession) -> list[str]:
    row = (
        await session.execute(
            text(
                "SELECT coalesce(reloptions, ARRAY[]::text[]) "
                "FROM pg_catalog.pg_class WHERE oid = 'feature.features'::regclass"
            )
        )
    ).one()
    return [str(option) for option in row[0]]


async def test_features_table_carries_autovacuum_options(
    migrated_session: AsyncSession,
) -> None:
    module = _load_migration()
    expected = [f"{name}={value}" for name, value in module.FEATURES_AUTOVACUUM_OPTIONS]
    assert expected, "migration 상수가 비었다"

    options = await _features_reloptions(migrated_session)

    assert sorted(options) == sorted(expected)

