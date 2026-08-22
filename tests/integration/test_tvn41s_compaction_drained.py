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
#: 아직 표시되지 않은 별도 material. 배출 전제 위반을 재는 테스트에만 쓴다.
_LIVE_MATERIAL = "d3000000-0000-4000-8000-000000000001"
_COMPACTED_RECEIPT = "d4000000-0000-4000-8000-000000000001"
_ROOT = "c" * 64


async def _seed_compacted_material_with_items(
    session: AsyncSession,
    *,
    items: int,
) -> None:
    """이미 표시됐지만 아직 배출되지 않은 material을 만든다.

    receipt를 붙인 뒤 `compacted_at`을 한 방향으로 표시한다. terminal material에는 새
    receipt를 붙일 수 없다는 `0236` fence 때문에 producer가 실제로 수행하는 순서를
    fixture도 그대로 따른다.

    **receipt를 반드시 붙인다.** receipt 없는 material은 orphan이라 item을 비운 뒤 행째
    삭제되고, 그러면 배출 표시를 확인할 대상이 사라진다. 배출 표시가 뜻을 갖는 것은
    audit 증거로 **영구 보존되는** material 쪽이다 — GC가 매 batch 훑는 것도 그쪽이다.
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
            "item_count, merkle_root, materialized_at) VALUES ("
            "CAST(:material_id AS uuid), :system, 1, 0, 0, :items, :root, "
            "now() - interval '1 hour')"
        ),
        {
            "material_id": _MATERIAL,
            "system": _SYSTEM,
            "items": max(items, 1),
            "root": _ROOT,
        },
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
    # item을 material에 채운 뒤 compaction을 표시한다. 0236은 terminal material에
    # 새 item을 넣는 것도 차단하므로, 이 순서가 producer와 raw INSERT fence 모두의
    # 정상 경계다.
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
    await session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_materials "
            "SET compacted_at = now() - interval '1 minute' "
            "WHERE material_id = CAST(:material_id AS uuid)"
        ),
        {"material_id": _MATERIAL},
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


async def test_last_receipt_marks_orphan_and_blocks_reuse(
    migrated_session: AsyncSession,
) -> None:
    """마지막 receipt 삭제가 orphan 상태를 만들고 새 receipt를 거부한다."""

    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_streams ("
            "external_system, consumer_id, restore_epoch) "
            "VALUES (:system, 'drained-orphan', 1) ON CONFLICT DO NOTHING"
        ),
        {"system": _SYSTEM},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at) VALUES ("
            "CAST(:material_id AS uuid), :system, 1, 0, 0, 1, :root, now())"
        ),
        {"material_id": _MATERIAL, "system": _SYSTEM, "root": _ROOT},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshots ("
            "snapshot_id, material_id, receipt_kind, external_system, "
            "created_at, expires_at) VALUES ("
            "CAST(:receipt_id AS uuid), CAST(:material_id AS uuid), 'generic', "
            ":system, now(), now() + interval '2 hours')"
        ),
        {"receipt_id": _RECEIPT, "material_id": _MATERIAL, "system": _SYSTEM},
    )
    await migrated_session.execute(
        text(
            "DELETE FROM ops.poi_cache_target_snapshots "
            "WHERE snapshot_id = CAST(:receipt_id AS uuid)"
        ),
        {"receipt_id": _RECEIPT},
    )

    orphaned_at = (
        await migrated_session.execute(
            text(
                "SELECT orphaned_at "
                "FROM ops.poi_cache_target_snapshot_materials "
                "WHERE material_id = CAST(:material_id AS uuid)"
            ),
            {"material_id": _MATERIAL},
        )
    ).scalar_one()
    assert orphaned_at is not None

    reason = await _refused(
        migrated_session,
        "INSERT INTO ops.poi_cache_target_snapshots ("
        "snapshot_id, material_id, receipt_kind, external_system, "
        "created_at, expires_at) VALUES ("
        "x_extension.gen_random_uuid(), "
        f"CAST('{_MATERIAL}' AS uuid), 'generic', '{_SYSTEM}', "
        "now(), now() + interval '2 hours')",
    )
    assert "already orphaned" in reason, reason

    moved = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials "
        "SET orphaned_at = NULL "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "one-way" in moved or "receipt trigger" in moved, moved


async def test_compacted_material_blocks_new_receipt(
    migrated_session: AsyncSession,
) -> None:
    """terminal audit material은 orphan이 아니어도 새 receipt를 받을 수 없다."""

    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_streams ("
            "external_system, consumer_id, restore_epoch) "
            "VALUES (:system, 'drained-compacted', 1) ON CONFLICT DO NOTHING"
        ),
        {"system": _SYSTEM},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at) VALUES ("
            "CAST(:material_id AS uuid), :system, 1, 0, 0, 1, :root, now())"
        ),
        {"material_id": _LIVE_MATERIAL, "system": _SYSTEM, "root": _ROOT},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshots ("
            "snapshot_id, material_id, receipt_kind, external_system, "
            "created_at, expires_at) VALUES ("
            "CAST(:receipt_id AS uuid), CAST(:material_id AS uuid), 'generic', "
            ":system, now(), now() + interval '2 hours')"
        ),
        {
            "receipt_id": _RECEIPT,
            "material_id": _LIVE_MATERIAL,
            "system": _SYSTEM,
        },
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_materials "
            "SET compacted_at = clock_timestamp() "
            "WHERE material_id = CAST(:material_id AS uuid)"
        ),
        {"material_id": _LIVE_MATERIAL},
    )

    reason = await _refused(
        migrated_session,
        "INSERT INTO ops.poi_cache_target_snapshots ("
        "snapshot_id, material_id, receipt_kind, external_system, "
        "created_at, expires_at) VALUES ("
        f"CAST('{_COMPACTED_RECEIPT}' AS uuid), "
        f"CAST('{_LIVE_MATERIAL}' AS uuid), 'reconciliation', '{_SYSTEM}', "
        "now(), now() + interval '2 hours')",
    )
    assert "already compacted" in reason, reason


async def test_compacted_material_blocks_new_item(
    migrated_session: AsyncSession,
) -> None:
    """terminal material에 raw item INSERT를 허용하면 drained fence가 무력해진다."""

    await _seed_compacted_material_with_items(migrated_session, items=1)

    reason = await _refused(
        migrated_session,
        "INSERT INTO ops.poi_cache_target_snapshot_material_items ("
        "material_id, row_number, target_key, state, source_generation, "
        "source_payload_fingerprint) VALUES ("
        f"CAST('{_MATERIAL}' AS uuid), 2, 'k-0002', 'deleted', 1, "
        "repeat('b', 64))",
    )
    assert "cannot be inserted after compaction" in reason, reason


async def test_material_cannot_be_marked_drained_with_items(
    migrated_session: AsyncSession,
) -> None:
    """compaction과 drained를 한 번에 표시해 남은 item을 backlog에서 숨길 수 없다."""

    await _seed_compacted_material_with_items(migrated_session, items=1)

    reason = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials "
        "SET compacted_at = clock_timestamp(), "
        "compaction_drained_at = clock_timestamp() "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "while items remain" in reason, reason


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
        {"material_id": _LIVE_MATERIAL, "system": _SYSTEM, "root": _ROOT},
    )

    reason = await _refused(
        migrated_session,
        "UPDATE ops.poi_cache_target_snapshot_materials "
        "SET compaction_drained_at = now() "
        f"WHERE material_id = CAST('{_LIVE_MATERIAL}' AS uuid)",
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


def test_both_backlog_queries_ask_the_same_question_about_drained_materials() -> None:
    """두 backlog 질의가 같은 술어를 써야 한다.

    한쪽만 고치면 이 migration은 **아무것도 고치지 않는다**. `_SELECT_..._SYSTEM_SQL`이
    매 batch에서 먼저 돌고, 네 갈래가 `UNION`으로 합쳐진 뒤에야 `LIMIT 1`이 걸리므로
    갈래마다 전량 평가된다 — 옛 `EXISTS(item)` 술어가 거기 남아 있으면 compacted
    material마다 index probe 한 번이 그대로 계속된다(적대 리뷰가 실제로 이 상태를 잡았다).

    SQL 문자열을 보는 이유: 동작 테스트는 두 질의가 **우연히 같은 답**을 낼 때 통과한다.
    여기서 지키려는 것은 답이 아니라 비용이므로 술어 자체를 본다.
    """

    from kortravelmap.infra import cache_target_reconciliation_repo as repo

    select_sql = repo._SELECT_EXPIRED_SNAPSHOT_GC_SYSTEM_SQL  # noqa: SLF001
    has_sql = repo._HAS_EXPIRED_SNAPSHOT_GC_BACKLOG_SQL  # noqa: SLF001

    for name, sql in (("select_system", select_sql), ("has_backlog", has_sql)):
        assert "material.orphaned_at IS NOT NULL" in sql, (
            f"{name}이 orphan 상태를 사용하지 않는다 — anti-join이 backlog tick으로 "
            "되돌아간다"
        )
        assert "material.compaction_drained_at IS NULL" in sql, (
            f"{name}이 배출 상태를 보지 않는다 — partial index가 쓰이지 않는다"
        )

    # 옛 술어가 어느 쪽에도 남아 있으면 안 된다. `compacted_at IS NOT NULL` 바로 뒤에
    # item 존재를 묻는 형태가 그것이다.
    stale = "material.compacted_at IS NOT NULL\n    AND EXISTS ("
    for name, sql in (("select_system", select_sql), ("has_backlog", has_sql)):
        assert stale not in sql, (
            f"{name}에 옛 item-probe 술어가 남아 있다 — compacted material마다 "
            "index probe 한 번이 그대로다"
        )
