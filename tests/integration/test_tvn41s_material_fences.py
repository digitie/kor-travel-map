"""`0231`이 새 표에 건 append-only fence가 실제로 존재하고 막는지 본다.

`0231` docstring은 "새 표에도 같은 fence를 건다"를 보장으로 제시한다. 그런데 `alembic
check`는 trigger를 비교하지 않고, 저장소 어디에도 그 fence들을 부르는 테스트가 없었다
(적대 리뷰 지적). 그 상태에서는 나중에 어떤 migration이 `ops.reject_snapshot_material_
mutation()`을 지우거나 약화시켜도 `pytest -q`와 `alembic check`가 모두 초록이다.

0231에서 새 표에 걸린 trigger는 **넷**이었다 — 두 표의 UPDATE fence와 두 표의
TRUNCATE fence. 0236은 여기에 item의 INSERT/DELETE 상태 fence를 추가한다. UPDATE만
보면 TRUNCATE trigger를 떨어뜨려도 초록이고, bounded DELETE로 되찾는 설계에서
TRUNCATE는 한 문장으로 전량을 날리는 우회로다.

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
    """`0231`은 "UPDATE/TRUNCATE만 막는다"를 보장으로 적었다 — TRUNCATE 쪽도 본다.

    UPDATE fence만 시험하면 나중에 TRUNCATE trigger 둘을 떨어뜨려도 `pytest -q`와
    `alembic check`가 모두 초록이다(적대 리뷰 지적). bounded DELETE로 되찾는 설계에서
    TRUNCATE는 한 문장으로 전량을 날리는 우회로다.

    두 표가 막히는 **방식이 다르다**. `material_items`는 아무도 참조하지 않으므로 평범한
    TRUNCATE가 곧장 fence에 닿는다. `materials`는 FK로 참조되고 있어 PostgreSQL이 먼저
    거부한다(`cannot truncate a table referenced in a foreign key constraint`) — fence에
    닿으려면 `CASCADE`가 필요하다. 그래서 둘 다 확인한다: FK가 1선이고 fence가 2선이다.
    FK만 믿으면 참조가 사라지는 날 조용히 뚫린다.
    """

    await _seed(migrated_session)

    # 1선: 참조가 있어 평범한 TRUNCATE는 PostgreSQL이 거부한다.
    reason = await _refused(
        migrated_session, "TRUNCATE ops.poi_cache_target_snapshot_materials"
    )
    assert "cannot truncate" in reason, reason

    # 2선: CASCADE로 그 1선을 넘어도 fence가 막는다.
    #
    # 그런데 CASCADE는 materials를 FK로 참조하는 표를 **전부** truncate 집합에 끌어들인다 —
    # receipt 표와 material item 표 둘 다다. 셋의 fence가 같은 함수를 써서 **같은 문자열**을
    # 내므로, 그대로 두면 materials fence를 지워도 형제가 대신 막아 단언이 통과한다
    # (적대 리뷰 지적 2회). 형제 둘을 savepoint 안에서 잠시 끄면 그 문자열을 낼 수 있는
    # 것은 materials fence뿐이다.
    siblings = (
        (
            "ops.poi_cache_target_snapshots",
            "trg_poi_cache_target_snapshots_no_truncate",
        ),
        (
            "ops.poi_cache_target_snapshot_material_items",
            "trg_poi_cache_target_snapshot_material_items_no_truncate",
        ),
    )
    for relation, trigger in siblings:
        await migrated_session.execute(
            text(f"ALTER TABLE {relation} DISABLE TRIGGER {trigger}")
        )
    reason = await _refused(
        migrated_session, "TRUNCATE ops.poi_cache_target_snapshot_materials CASCADE"
    )
    assert "append-only" in reason, reason
    for relation, trigger in siblings:
        await migrated_session.execute(
            text(f"ALTER TABLE {relation} ENABLE TRIGGER {trigger}")
        )

    # 참조가 없는 쪽은 곧장 fence다.
    reason = await _refused(
        migrated_session, "TRUNCATE ops.poi_cache_target_snapshot_material_items"
    )
    assert "append-only" in reason, reason


async def test_compaction_delete_of_material_items_stays_allowed(
    migrated_session: AsyncSession,
) -> None:
    """live item은 막고, compaction 표시 뒤의 bounded DELETE만 허용한다."""

    await _seed(migrated_session)

    reason = await _refused(
        migrated_session,
        "DELETE FROM ops.poi_cache_target_snapshot_material_items "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "before compaction" in reason, reason

    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_materials "
            "SET compacted_at = clock_timestamp() "
            "WHERE material_id = CAST(:material_id AS uuid)"
        ),
        {"material_id": _MATERIAL},
    )

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


async def test_live_material_delete_cascade_is_fail_closed(
    migrated_session: AsyncSession,
) -> None:
    """부모 DELETE의 ON DELETE CASCADE도 live item fence를 우회하지 못한다."""

    await _seed(migrated_session)

    reason = await _refused(
        migrated_session,
        "DELETE FROM ops.poi_cache_target_snapshot_materials "
        f"WHERE material_id = CAST('{_MATERIAL}' AS uuid)",
    )
    assert "before compaction" in reason, reason
