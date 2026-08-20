"""`0230`이 새 표에 건 append-only fence가 실제로 존재하고 막는지 본다.

`0230` docstring은 "새 표에도 같은 fence를 건다"를 보장으로 제시한다. 그런데 `alembic
check`는 trigger를 비교하지 않고, 저장소 어디에도 그 fence들을 부르는 테스트가 없었다
(적대 리뷰 지적). 그 상태에서는 나중에 어떤 migration이 `ops.reject_snapshot_material_
mutation()`을 지우거나 약화시켜도 `pytest -q`와 `alembic check`가 모두 초록이다.

새 표에 걸린 trigger는 **넷**이다 — 두 표의 UPDATE fence와 두 표의 TRUNCATE fence. 넷을
다 본다. UPDATE만 보면 TRUNCATE trigger를 떨어뜨려도 초록이고, bounded DELETE로 되찾는
설계에서 TRUNCATE는 한 문장으로 전량을 날리는 우회로다.

여기서는 trigger의 **존재**가 아니라 **거부**를 본다. 존재만 보면 함수 본문이 `RETURN
NEW`로 바뀌어도 통과한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_SYSTEM = "fence:41s"
_MATERIAL = "c1000000-0000-4000-8000-000000000001"
_RECEIPT = "c2000000-0000-4000-8000-000000000001"
_ROOT = "a" * 64


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_streams ("
            "external_system, consumer_id, restore_epoch) "
            "VALUES (:system, 'fence', 1) ON CONFLICT DO NOTHING"
        ),
        {"system": _SYSTEM},
    )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at) VALUES ("
            "CAST(:material_id AS uuid), :system, 1, 0, 0, 1, :root, now())"
        ),
        {"material_id": _MATERIAL, "system": _SYSTEM, "root": _ROOT},
    )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshots ("
            "snapshot_id, material_id, receipt_kind, external_system, "
            "created_at, expires_at) VALUES ("
            "CAST(:receipt_id AS uuid), CAST(:material_id AS uuid), 'generic', "
            ":system, now(), now() + interval '2 hours')"
        ),
        {"receipt_id": _RECEIPT, "material_id": _MATERIAL, "system": _SYSTEM},
    )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_material_items ("
            "material_id, row_number, target_key, state, source_generation, "
            "source_payload_fingerprint) VALUES ("
            "CAST(:material_id AS uuid), 1, 'k', 'active', 1, :fingerprint)"
        ),
        {"material_id": _MATERIAL, "fingerprint": "b" * 64},
    )


async def _refused(session: AsyncSession, sql: str) -> str:
    """`sql`이 실제로 막히는지 보고 그 이유 문자열을 돌려준다."""

    savepoint = await session.begin_nested()
    try:
        await session.execute(text(sql))
    except DBAPIError as error:
        await savepoint.rollback()
        return str(error)
    await savepoint.rollback()
    pytest.fail(f"막히지 않았다: {sql}")


async def test_material_item_rows_are_append_only(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)

    reason = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_material_items "
        "SET target_key = 'rewritten' "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "append-only" in reason, reason


async def test_material_row_allows_only_the_compaction_transition(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)

    # 내용 변경은 막힌다.
    reason = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials SET item_count = 99 "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "append-only except compaction" in reason, reason

    # compaction과 내용 변경을 함께 넣는 것도 막힌다 — 표시를 구실로 root를 다시 쓰는
    # 경로가 열리면 감사 증거가 증거가 아니게 된다.
    reason = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials "
        "SET compacted_at = now(), merkle_root = repeat('ff', 32) "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "must not change the material" in reason, reason

    # 표시 자체는 한 번 통과한다.
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_materials SET compacted_at = now() "
            "WHERE material_id = CAST(:material_id AS uuid)"
        ),
        {"material_id": _MATERIAL},
    )

    # 두 번은 막힌다.
    reason = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials SET compacted_at = now() "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "already compacted" in reason, reason


async def test_truncate_is_refused_on_both_new_tables(
    migrated_session: AsyncSession,
) -> None:
    """`0230`은 "UPDATE/TRUNCATE만 막는다"를 보장으로 적었다 — TRUNCATE 쪽도 본다.

    UPDATE fence만 시험하면 나중에 TRUNCATE trigger 둘을 떨어뜨려도 `pytest -q`와
    `alembic check`가 모두 초록이다(적대 리뷰 지적). bounded DELETE로 되찾는 설계에서
    TRUNCATE는 한 문장으로 전량을 날리는 우회로다.
    """

    await _seed(migrated_session)

    for relation in (
        "ops.poi_cache_target_snapshot_material_items",
        "ops.poi_cache_target_snapshot_materials",
    ):
        reason = await _refused(migrated_session, f"TRUNCATE {relation}")
        assert "append-only" in reason, (relation, reason)


async def test_compaction_delete_of_material_items_stays_allowed(
    migrated_session: AsyncSession,
) -> None:
    """fence가 DELETE까지 막으면 compaction 자체가 불가능해진다."""

    await _seed(migrated_session)

    deleted = (
        await migrated_session.execute(
            text(
                "DELETE FROM ops.poi_cache_target_snapshot_material_items "
                "WHERE material_id = CAST(:material_id AS uuid)"
            ),
            {"material_id": _MATERIAL},
        )
    ).rowcount
    assert deleted == 1
