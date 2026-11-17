"""453 — ``feature.features``의 표 단위 autovacuum 문턱(읽기 성능 계획 T-READ-08).

head DB에서 두 가지를 본다.

1. 표의 reloptions가 migration 상수와 같다 — 설정이 빠지거나 값이 바뀌면 빨갛다.
2. 같은 ``ALTER TABLE … SET``을 다시 실행해도 relfilenode가 그대로다 — 이 revision이 표를 다시
   쓰지 않는다는 계약(44만 행 표의 배포 시간·잠금)을 효과로 확인한다.
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


async def _features_catalog(session: AsyncSession) -> tuple[int, list[str]]:
    row = (
        await session.execute(
            text(
                "SELECT relfilenode, coalesce(reloptions, ARRAY[]::text[]) "
                "FROM pg_catalog.pg_class WHERE oid = 'feature.features'::regclass"
            )
        )
    ).one()
    return int(row[0]), [str(option) for option in row[1]]


async def test_features_table_carries_autovacuum_options(
    migrated_session: AsyncSession,
) -> None:
    module = _load_migration()
    expected = [f"{name}={value}" for name, value in module.FEATURES_AUTOVACUUM_OPTIONS]
    assert expected, "migration 상수가 비었다"

    _, options = await _features_catalog(migrated_session)

    assert sorted(options) == sorted(expected)


async def test_reapplying_autovacuum_options_does_not_rewrite_features(
    migrated_session: AsyncSession,
) -> None:
    module = _load_migration()
    before, _ = await _features_catalog(migrated_session)

    # 소유자 롤로 같은 문장을 다시 보낸다(fixture가 끝에서 rollback한다).
    await migrated_session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
    await migrated_session.execute(text(module._SET_FEATURES_AUTOVACUUM_SQL))
    after, options = await _features_catalog(migrated_session)

    assert after == before
    assert len(options) == len(module.FEATURES_AUTOVACUUM_OPTIONS)
