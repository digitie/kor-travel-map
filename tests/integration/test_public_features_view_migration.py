"""0059 ``feature.public_features`` VIEW migration 회귀 (ADR-067, T-VN-04).

CREATE VIEW만 있는 Wave 0 migration이 가역인지 확인한다: upgrade → view 존재
(술어 = status='active' AND deleted_at IS NULL), downgrade → view 삭제,
재-upgrade → 복원. 전용 인덱스는 T-VN-34 소유이므로 여기서 검증하지 않는다.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0058_poi_target_lock_version"
_TARGET_REVISION = "0059_public_features_view"

_VIEW_EXISTS_SQL = """
SELECT count(*)
FROM information_schema.views
WHERE table_schema = 'feature' AND table_name = 'public_features'
"""


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_public_features_view_upgrade_downgrade_roundtrip(pg_container: Any) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"public_features_view_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = None
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            assert await connection.scalar(text(_VIEW_EXISTS_SQL)) == 1
            viewdef = await connection.scalar(
                text("SELECT pg_get_viewdef('feature.public_features'::regclass, true)")
            )
            assert viewdef is not None
            # pg_get_viewdef는 text 캐스트를 명시한다: status::text = 'active'::text
            assert re.search(r"status(::text)? = 'active'(::text)?", viewdef)
            assert "deleted_at IS NULL" in viewdef

            # 술어의 실효 검증: 상태 조합 3종 중 active+미삭제만 통과.
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.features (feature_id, kind, name, category, status)
                    VALUES
                      ('mig:active', 'place', 'a', '06020000', 'active'),
                      ('mig:draft', 'place', 'b', '06020000', 'draft')
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category, status, deleted_at
                    )
                    VALUES ('mig:retired', 'place', 'c', '06020000', 'inactive', now())
                    """
                )
            )
            rows = await connection.execute(
                text("SELECT feature_id FROM feature.public_features ORDER BY feature_id")
            )
            assert [row.feature_id for row in rows] == ["mig:active"]
        await target_engine.dispose()
        target_engine = None

        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION, downgrade=True)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            assert await connection.scalar(text(_VIEW_EXISTS_SQL)) == 0
        await target_engine.dispose()
        target_engine = None

        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            assert await connection.scalar(text(_VIEW_EXISTS_SQL)) == 1
    finally:
        if target_engine is not None:
            await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()
