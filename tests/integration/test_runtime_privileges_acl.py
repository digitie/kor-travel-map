"""`_FEATURE_TABLE_PRIVILEGES` ACL 표가 실제 DB와 맞는지.

T-VN-40C가 `tests/integration/test_tvn40a_legacy_write_fence_acl.py`를 legacy
`curated_features` 표와 함께 지웠는데, 그 파일에는 **fence와 무관한** 검사가 둘
섞여 있었다. 표의 phantom 항목을 잡는 검사와, catalog(theme/source/rule)가 fence
대상이 아님을 못박는 검사다. 둘 다 40C 이후에도 지켜야 하므로 여기로 옮긴다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_every_declared_feature_relation_exists(
    migrated_session: AsyncSession,
) -> None:
    """ACL 표에 선언된 feature relation이 전부 실제로 존재한다.

    reconcile은 DB에 **있는** relation만 순회하므로 표의 phantom 항목(예: legacy 0032가
    rename해 사라진 `curated_tripmate_copy_snapshots`)은 아무 것도 지키지 않으면서 표를
    읽는 사람에게 "권한이 관리된다"는 인상만 준다. 40C처럼 표를 통째로 지우는 작업
    직후가 phantom이 가장 생기기 쉬운 시점이다.
    """
    from kortravelmap.infra import runtime_privileges

    rows = await migrated_session.execute(
        text(
            "SELECT relname FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'feature' AND c.relkind IN ('r', 'p', 'v')"
        )
    )
    existing = {row[0] for row in rows}
    declared = set(runtime_privileges._FEATURE_TABLE_PRIVILEGES)  # noqa: SLF001
    phantom = sorted(declared - existing)
    assert not phantom, f"ACL 표에 있지만 DB에 없는 feature relation: {phantom}"


async def test_theme_catalog_procedure_stays_executable(
    migrated_session: AsyncSession,
) -> None:
    """theme/source/rule catalog는 legacy가 아니다 — executor가 계속 써야 한다.

    plan:28이 그 셋을 "catalog input만 유지"로 정했고 T-VN-40의 procedure가 그 표에 쓴다.
    그 procedure의 EXECUTE는 `ktm_feature_runtime`이 아니라 **`ktm_curation_admin_executor`**가
    갖는다(`0207_tvn40_theme_catalog.py:533`). principal을 잘못 짚으면 이 테스트는 늘 red다.
    """
    result = await migrated_session.execute(
        text(
            """
            SELECT has_function_privilege(
                'ktm_curation_admin_executor',
                'feature.create_curated_theme_command(text,text,text,text,text,jsonb,bigint,text)',
                'EXECUTE'
            )
            """
        )
    )
    assert result.scalar_one() is True, "theme catalog procedure까지 막혔다 — plan:28 위반"
