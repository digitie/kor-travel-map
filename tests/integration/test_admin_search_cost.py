"""관리자 희소 검색의 원천 JSON 반복 조회 비용과 현재 record 범위를 검증한다."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.admin_feature_repo import list_admin_features
from tests.integration._feature_ids import feature_uuid
from tests.integration.test_admin_feature_repo import _seed_feature

pytestmark = pytest.mark.integration


def _nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result = [plan]
    for child in plan.get("Plans", []):
        result.extend(_nodes(child))
    return result


async def test_korean_feature_scope_does_not_scan_raw_source_candidates(
    migrated_session: AsyncSession,
) -> None:
    for index in range(48):
        await _seed_feature(migrated_session, feature_uuid(f"admin-search-cost-{index}"))

    statements: list[tuple[str, Any]] = []

    def record(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append((statement, parameters))

    bind = migrated_session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        page = await list_admin_features(
            migrated_session,
            q="안동하회마을",
            search_scope="feature",
            page_size=50,
        )
    finally:
        event.remove(bind, "before_cursor_execute", record)

    assert page.items == ()
    assert len(statements) == 1
    connection = await migrated_session.connection()
    statement, parameters = statements[0]
    result = await connection.exec_driver_sql(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
        parameters,
    )
    plan = result.scalar_one()[0]["Plan"]
    raw_source_reads = [
        node.get("Actual Loops", 0)
        for node in _nodes(plan)
        if node.get("Relation Name") == "source_records" and node.get("Actual Loops", 0) > 0
    ]
    assert raw_source_reads == [], (
        "이름·주소·ID 검색은 비일치 후보의 원천 JSON을 읽지 않아야 합니다."
    )


async def test_source_scope_preserves_full_search_and_default(
    migrated_session: AsyncSession,
) -> None:
    feature_id = feature_uuid("admin-source-scope")
    await _seed_feature(
        migrated_session,
        feature_id,
        source_payload={"operator_note": "원천전용명칭"},
    )
    bounded = await list_admin_features(
        migrated_session,
        q="원천전용명칭",
        search_scope="feature",
    )
    assert bounded.items == ()
    for scope in ("all", None):
        kwargs: dict[str, Any] = {} if scope is None else {"search_scope": scope}
        page = await list_admin_features(migrated_session, q="원천전용명칭", **kwargs)
        assert [item.feature_id for item in page.items] == [feature_id]
    for query in ("광화문", "세종대로", feature_id):
        page = await list_admin_features(
            migrated_session,
            q=query,
            search_scope="feature",
        )
        assert [item.feature_id for item in page.items] == [feature_id]


async def test_feature_scope_paginates_without_duplicates(
    migrated_session: AsyncSession,
) -> None:
    ids = {feature_uuid(f"admin-feature-scope-page-{index}") for index in range(3)}
    for feature_id in ids:
        await _seed_feature(migrated_session, feature_id)
    first = await list_admin_features(
        migrated_session,
        q="광화문",
        search_scope="feature",
        page_size=2,
    )
    assert first.next_cursor is not None
    second = await list_admin_features(
        migrated_session,
        q="광화문",
        search_scope="feature",
        page_size=2,
        cursor=first.next_cursor,
    )
    returned = [item.feature_id for item in (*first.items, *second.items)]
    assert len(returned) == len(set(returned)) == 3
    assert set(returned) == ids
