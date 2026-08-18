"""T-VN-40A legacy write fence — **ACL 층**이 실제 DB에서 막는지.

`tests/lint/test_legacy_write_fence.py`는 `_FEATURE_TABLE_PRIVILEGES` **표**에 write가 없다는
것만 본다. 표가 곧 GRANT라는 전제는 `reconcile_runtime_privileges`가 지키지만, 그 전제가
깨져도(예: 다른 migration이 GRANT를 넣거나 reconcile이 어긋나면) lint는 초록이다.
"검사한다고 주장하는 것을 실제로는 안 보는" 형태를 피하려면 **DB에게 물어야** 한다.

여기서는 `SET ROLE ktm_feature_runtime`으로 앱 role이 돼서 legacy 표에 직접 INSERT/UPDATE/
DELETE를 시도하고, PostgreSQL이 `permission denied`로 거부하는지 본다. static 층·route
층을 우회한 raw SQL이라 이 셋 중 ACL만 남은 상황을 정확히 재현한다.

각 검사가 별도 테스트인 이유: `migrated_session`은 트랜잭션 fixture라 권한 오류 뒤 같은
세션에서 다음 SQL을 낼 수 없다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_INSERT = """
INSERT INTO feature.curated_features (
    theme_id, feature_id, source_id, curation_status,
    selection_origin, curation_relation, reuse_policy, metadata, updated_at
) VALUES (
    gen_random_uuid(), 'f_fence_probe', gen_random_uuid(), 'curated',
    'admin', 'nearby_option', 'manual_review', '{}'::jsonb, now()
)
"""


async def _expect_permission_denied(session: AsyncSession, sql: str) -> None:
    with pytest.raises(DBAPIError) as info:
        await session.execute(text(sql))
    message = str(info.value.orig)
    assert "permission denied" in message.lower(), (
        f"거부는 됐지만 이유가 권한이 아니다: {message[:160]}"
    )


async def test_runtime_role_cannot_insert_into_legacy_curated_features(
    migrated_session: AsyncSession,
) -> None:
    """앱 role의 raw INSERT를 DB가 거부한다.

    static 층(`assert_legacy_write_allowed`)과 route 층(410)은 코드 경로다 — 우회 코드가
    있으면 뚫린다. ACL은 코드가 아니라 DB가 막으므로 마지막 방어선이다.
    """
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await _expect_permission_denied(migrated_session, _INSERT)
    finally:
        await migrated_session.rollback()


async def test_runtime_role_cannot_update_legacy_curated_features(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await _expect_permission_denied(
            migrated_session,
            "UPDATE feature.curated_features SET updated_at = now() WHERE false",
        )
    finally:
        await migrated_session.rollback()


async def test_runtime_role_cannot_delete_legacy_curated_features(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await _expect_permission_denied(
            migrated_session,
            "DELETE FROM feature.curated_features WHERE false",
        )
    finally:
        await migrated_session.rollback()


async def test_runtime_role_can_still_read_legacy_curated_features(
    migrated_session: AsyncSession,
) -> None:
    """읽기는 살아 있어야 한다 — soak 동안 legacy를 읽어 canonical과 대조한다(ADR-075 결정 4).

    이 테스트가 없으면 "REVOKE ALL을 했더니 SELECT까지 사라졌다"를 못 잡는다.
    """
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        result = await migrated_session.execute(
            text("SELECT count(*) FROM feature.curated_features")
        )
        assert result.scalar_one() >= 0
    finally:
        await migrated_session.rollback()


async def test_theme_catalog_is_not_fenced_at_acl_layer(
    migrated_session: AsyncSession,
) -> None:
    """theme/source/rule catalog는 legacy가 아니다 — executor가 계속 써야 한다.

    plan:28이 그 셋을 "catalog input만 유지"로 정했고 T-VN-40의 procedure가 그 표에 쓴다.
    그 procedure의 EXECUTE는 `ktm_feature_runtime`이 아니라 **`ktm_curation_admin_executor`**가
    갖는다(`0207_tvn40_theme_catalog.py:533`) — 처음에 runtime으로 검사했다가 False를 받고
    확인했다. principal을 잘못 짚으면 이 테스트는 fence와 무관하게 늘 red다.
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
