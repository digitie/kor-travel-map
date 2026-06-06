"""``/ops/health-deep`` 컴포넌트 점검 SQL 통합 테스트 (T-212c).

라우터 단위 테스트는 ``_check_database``/``_check_postgis``를 monkeypatch하므로
실제 ``SELECT 1`` / ``pg_extension`` 쿼리는 PostGIS에서만 실측된다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from krtour.map_admin.routers.ops import _check_database, _check_postgis

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_check_database_ok(migrated_session: AsyncSession) -> None:
    check = await _check_database(migrated_session)
    assert check.component == "database"
    assert check.status == "ok"
    assert check.detail is None


async def test_check_postgis_reports_version(migrated_session: AsyncSession) -> None:
    check = await _check_postgis(migrated_session)
    assert check.component == "postgis"
    assert check.status == "ok"
    assert check.detail  # 설치된 PostGIS 확장 버전 문자열.
