"""`0236`의 배출 상태 열과 그 fence가 실제로 서는지 본다.

`0236`은 GC backlog 판정에서 "표시됐고 item이 남은 material"을 item 존재 probe 대신
``compaction_drained_at`` 상태 조회로 바꾼다. 그 바꿈이 뜻을 가지려면 세 가지가 동시에
참이어야 한다 — (1) 배출이 끝나면 실제로 표시가 찍힌다, (2) 그 표시가 backlog 판정에서
material을 **빼낸다**, (3) 두 시각이 각각 한 방향이라 되돌리거나 건너뛸 수 없다.

셋 중 하나라도 빠지면 조용히 무의미해진다. 표시가 안 찍히면 옛 전수 스캔과 같고,
판정이 그 열을 안 보면 열만 늘어난 것이고, fence가 없으면 아무 write나 그 열을 되돌려
GC가 이미 빈 material을 영원히 다시 훑는다.

`0231` fence 테스트와 마찬가지로 trigger의 **존재**가 아니라 **거부**를 본다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.cache_target_reconciliation_repo import (
    prune_expired_cache_target_snapshots_batch,
)

pytestmark = pytest.mark.integration

_SYSTEM = "drained:41s"
_MATERIAL = "d1000000-0000-4000-8000-000000000001"
_RECEIPT = "d2000000-0000-4000-8000-000000000001"
_ROOT = "c" * 64


async def _seed_compacted_material_with_items(
    session: AsyncSession,
    *,
    items: int,
) -> None:
    """이미 표시됐지만 아직 배출되지 않은 material을 만든다.

    fence가 `compacted_at`을 한 방향으로만 열어 두므로, 표시된 상태를 만들려면 INSERT
    시점에 이미 표시해 둔다(UPDATE로 표시하면 이 fixture가 fence를 거치게 되어 무엇을
    재는 테스트인지 흐려진다).
    """

    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_streams ("
            "external_system, consumer_id, restore_epoch) "
            "VALUES (:system, 'drained', 1) ON CONFLICT DO NOTHING"
        ),
        {"system": _SYSTEM},
    )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at, compacted_at) VALUES ("
            "CAST(:material_id AS uuid), :system, 1, 0, 0, :items, :root, "
            "now() - interval '1 hour', now() - interval '1 minute')"
        ),
        {
            "material_id": _MATERIAL,
            "system": _SYSTEM,
            "items": max(items, 1),
            "root": _ROOT,
        },
    )
    for row_number in range(1, items + 1):
        await session.execute(
            text(
                "INSERT INTO ops.poi_cache_target_snapshot_material_items ("
                "material_id, row_number, target_key, state, source_generation, "
                "source_payload_fingerprint) VALUES ("
                "CAST(:material_id AS uuid), :row_number, :target_key, 'deleted', 1, "
                ":fingerprint)"
            ),
            {
                "material_id": _MATERIAL,
                "row_number": row_number,
                "target_key": f"k-{row_number:04d}",
                "fingerprint": "b" * 64,
            },
        )


async def _refused(session: AsyncSession, sql: str) -> str:
    savepoint = await session.begin_nested()
    try:
        await session.execute(text(sql))
    except DBAPIError as error:
        await savepoint.rollback()
        return str(error)
    await savepoint.rollback()
    pytest.fail(f"막히지 않았다: {sql}")


async def _drained_at(session: AsyncSession) -> object:
    return (
        await session.execute(
            text(
                "SELECT compaction_drained_at "
                "FROM ops.poi_cache_target_snapshot_materials "
                "WHERE material_id = CAST(:material_id AS uuid)"
            ),
            {"material_id": _MATERIAL},
        )
    ).scalar_one()


async def test_gc_marks_a_material_drained_once_its_items_are_gone(
    migrated_session: AsyncSession,
) -> None:
    """배출이 끝나면 표시가 찍힌다 — 이게 없으면 옛 전수 스캔과 같다."""

    await _seed_compacted_material_with_items(migrated_session, items=3)
    assert await _drained_at(migrated_session) is None

    # item이 남아 있는 동안에는 찍히면 안 된다. 먼저 한 건만 배출시킨다.
    await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=1,
        header_limit=10,
    )
    remaining = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_snapshot_material_items "
                "WHERE material_id = CAST(:material_id AS uuid)"
            ),
            {"material_id": _MATERIAL},
        )
    ).scalar_one()
    assert remaining == 2, "이 단계는 '아직 배출 중'을 재는 것이라 item이 남아야 한다"
    assert await _drained_at(migrated_session) is None, (
        "item이 남았는데 배출 완료로 찍혔다 — GC가 아직 지울 것이 있는 material을 "
        "backlog에서 빼면 그 item은 영영 남는다"
    )

    # 남은 것을 마저 배출시키면 그때 찍힌다.
    await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=100,
        header_limit=10,
    )
    assert await _drained_at(migrated_session) is not None


async def test_backlog_ignores_a_drained_material(
    migrated_session: AsyncSession,
) -> None:
    """표시가 찍힌 material은 backlog 판정에서 빠진다.

    판정이 이 열을 보지 않으면 열만 늘어난 것이고, audit material이 쌓일수록 한가할 때의
    판정 비용이 계속 커진다 — 이 migration이 없애려던 것이 정확히 그것이다.
    """

    await _seed_compacted_material_with_items(migrated_session, items=2)

    first = await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=1,
        header_limit=10,
    )
    assert first.has_more, "item이 남았는데 backlog가 비었다고 했다"

    drained = await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=100,
        header_limit=10,
    )
    assert await _drained_at(migrated_session) is not None
    assert not drained.has_more, (
        "배출이 끝났는데 backlog가 남았다고 한다 — 판정이 compaction_drained_at을 "
        "보지 않는다"
    )


async def test_drain_mark_is_one_way(migrated_session: AsyncSession) -> None:
    """배출 표시는 되돌릴 수 없다. 되돌릴 수 있으면 GC가 다시 훑기 시작한다."""

    await _seed_compacted_material_with_items(migrated_session, items=1)
    await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=100,
        header_limit=10,
    )
    assert await _drained_at(migrated_session) is not None

    reason = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials "
        "SET compaction_drained_at = NULL "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "one-way" in reason, reason

    moved = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials "
        "SET compaction_drained_at = now() + interval '1 day' "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "one-way" in moved, moved


async def test_a_material_cannot_be_drained_before_it_is_compacted(
    migrated_session: AsyncSession,
) -> None:
    """표시 없이 배출만 찍는 것은 막는다.

    ``compacted_at``이 "회수를 시작했다"는 뜻이므로, 그것 없이 배출만 기록되면
    "아직 살아 있는 material의 item을 지웠다"가 표현 가능해진다.
    """

    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_streams ("
            "external_system, consumer_id, restore_epoch) "
            "VALUES (:system, 'drained', 1) ON CONFLICT DO NOTHING"
        ),
        {"system": _SYSTEM},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at) VALUES ("
            "CAST(:material_id AS uuid), :system, 2, 0, 0, 1, :root, now())"
        ),
        {"material_id": _RECEIPT, "system": _SYSTEM, "root": _ROOT},
    )

    reason = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials "
        "SET compaction_drained_at = now() "
        f"WHERE material_id = CAST('{_RECEIPT}' AS uuid)",
    )
    # CHECK와 fence 중 어느 쪽이 먼저 잡아도 된다 — 둘 다 이 상태를 표현 불가로 만든다.
    assert (
        "drained_after_compacted" in reason or "before it is compacted" in reason
    ), reason


async def test_the_draining_index_only_holds_undrained_materials(
    migrated_session: AsyncSession,
) -> None:
    """partial index가 배출된 material을 담지 않는지 직접 본다.

    판정 SQL만 보면 index가 통째로 없어도(=seq scan) 테스트는 통과한다. 이 migration의
    목적은 "정답"이 아니라 "상수 시간"이므로 색인 자체를 확인한다.
    """

    predicate = (
        await migrated_session.execute(
            text(
                "SELECT pg_get_expr(indpred, indrelid) "
                "FROM pg_index "
                "WHERE indexrelid = "
                "'ops.idx_poi_cache_target_snapshot_materials_draining'::regclass"
            )
        )
    ).scalar_one()
    assert "compacted_at IS NOT NULL" in predicate, predicate
    assert "compaction_drained_at IS NULL" in predicate, predicate

    await _seed_compacted_material_with_items(migrated_session, items=1)
    before = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_snapshot_materials "
                "WHERE compacted_at IS NOT NULL AND compaction_drained_at IS NULL"
            )
        )
    ).scalar_one()
    assert before >= 1

    await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=100,
        header_limit=10,
    )
    after = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_snapshot_materials "
                "WHERE compacted_at IS NOT NULL AND compaction_drained_at IS NULL"
            )
        )
    ).scalar_one()
    assert after == before - 1, (
        "배출된 material이 index 술어에서 빠지지 않았다 — 그러면 audit material이 "
        "쌓일수록 backlog 판정이 계속 무거워진다"
    )
