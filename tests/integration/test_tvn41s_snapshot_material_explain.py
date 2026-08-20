"""`0230` material/receipt 모델의 hot query가 실제로 인덱스를 타는지 본다.

정규화가 만든 새 접근 경로 넷을 잰다.

1. **item page 읽기** — `(material_id, row_number)` PK keyset. 1,000,000행짜리 표에서
   page마다 seq scan을 하면 그 자체로 설계가 무너진다.
2. **material 재사용 조회** — identity partial unique. generic/reconciliation이 매 요청
   여기서 갈리므로 가장 자주 도는 술어다.
3. **orphan material item 정리** — GC batch가 매 tick 훑는다.
4. **compaction 후보 조회** — `WHERE compacted_at IS NULL` partial index.

계획을 강제하지 않는다. `enable_seqscan = off`로 "탈 인덱스가 있는가"를 묻는 것이 이
게이트의 질문이고(작은 fixture에서 planner는 어차피 seq scan을 고른다), 실제 처리량은
n150 soak이 따로 잰다.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import cache_target_reconciliation_repo as repo

pytestmark = pytest.mark.integration

_SYSTEM = "explain:41s"
_MATERIAL = "b1000000-0000-4000-8000-000000000001"
_RECEIPT = "b2000000-0000-4000-8000-000000000001"
_ROOT = "a" * 64


async def _explain(
    session: AsyncSession,
    sql: str,
    params: dict[str, Any],
) -> set[str]:
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (
        await session.execute(
            text("EXPLAIN (FORMAT JSON, COSTS OFF) " + sql),
            params,
        )
    ).scalar_one()[0]["Plan"]
    nodes = [plan]
    index_names: set[str] = set()
    while nodes:
        node = nodes.pop()
        nodes.extend(node.get("Plans", []))
        if node.get("Index Name") is not None:
            index_names.add(str(node["Index Name"]))
    if not index_names:  # pragma: no cover - 실패 진단용
        index_names.add(f"(no index) plan={plan}")
    return index_names


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_streams ("
            "external_system, consumer_id, restore_epoch) "
            "VALUES (:system, 'explain', 1) ON CONFLICT DO NOTHING"
        ),
        {"system": _SYSTEM},
    )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at) VALUES ("
            "CAST(:material_id AS uuid), :system, 1, 0, 0, 3, :root, now())"
        ),
        {"material_id": _MATERIAL, "system": _SYSTEM, "root": _ROOT},
    )
    # identity 술어가 **선택적**이어야 planner가 identity 인덱스를 고른다. material이
    # 하나뿐이면 두 partial index의 비용이 같아 아무 것이나 골라도 게이트가 통과한다 —
    # 그러면 "identity로 한 행을 찍는다"를 보는 게 아니라 "인덱스를 아무거나 탄다"를
    # 보는 게 된다.
    # 이 200개는 **실제 compaction 후보의 모양**을 갖춰야 한다 — receipt가 있고, 그
    # receipt가 만료됐고, item이 있다. 그렇지 않으면 후보가 0개라 planner의 선택이
    # 무의미해지고 게이트는 아무 것도 재지 않는다.
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at) "
            "SELECT CAST(lpad(to_hex(value), 8, '0') "
            "|| '-0000-4000-8000-000000000002' AS uuid), "
            ":system, 1, value, value, 1, :root, now() - make_interval(mins => value) "
            "FROM generate_series(1, 200) AS value"
        ),
        {"system": _SYSTEM, "root": _ROOT},
    )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshots ("
            "snapshot_id, material_id, receipt_kind, external_system, "
            "created_at, expires_at) "
            "SELECT x_extension.gen_random_uuid(), material.material_id, "
            "'reconciliation', :system, now() - interval '3 hours', "
            "now() - interval '1 hour' "
            "FROM ops.poi_cache_target_snapshot_materials AS material "
            "WHERE material.external_system = :system "
            "AND material.material_high_watermark_relay_order > 0"
        ),
        {"system": _SYSTEM},
    )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_material_items ("
            "material_id, row_number, target_key, state, source_generation, "
            "source_payload_fingerprint) "
            "SELECT material.material_id, 1, 'k', 'active', 1, :fingerprint "
            "FROM ops.poi_cache_target_snapshot_materials AS material "
            "WHERE material.external_system = :system "
            "AND material.material_high_watermark_relay_order > 0"
        ),
        {"system": _SYSTEM, "fingerprint": "b" * 64},
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
            "source_payload_fingerprint) "
            "SELECT CAST(:material_id AS uuid), value, 'key-' || value::text, "
            "'active', 1, :fingerprint FROM generate_series(1, 3) AS value"
        ),
        {"material_id": _MATERIAL, "fingerprint": "b" * 64},
    )
    # compaction 후보 조회의 값은 **이미 처리한 것을 건너뛴다**는 데 있다. 전부
    # 미처리인 fixture에서는 partial index가 전체와 같아 planner가 고를 이유가 없다.
    # 대부분을 compaction 상태로 만들어 그 술어를 선택적으로 만든다.
    await session.execute(
        text(
            "UPDATE ops.poi_cache_target_snapshot_materials "
            "SET compacted_at = now() "
            "WHERE external_system = :system "
            "AND material_high_watermark_relay_order > 10"
        ),
        {"system": _SYSTEM},
    )
    for relation in (
        "ops.poi_cache_target_snapshot_materials",
        "ops.poi_cache_target_snapshot_material_items",
        "ops.poi_cache_target_snapshots",
    ):
        await session.execute(text(f"ANALYZE {relation}"))


async def test_snapshot_material_hot_queries_have_index_paths(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)

    item_page = await _explain(
        migrated_session,
        repo._GET_SNAPSHOT_ITEMS_SQL,  # pyright: ignore[reportPrivateUsage]
        {
            "external_system": _SYSTEM,
            "material_id": _MATERIAL,
            "after_row_number": 0,
            "limit": 500,
        },
    )
    assert "pk_poi_cache_target_snapshot_material_items" in item_page, item_page

    reuse = await _explain(
        migrated_session,
        repo._GET_REUSABLE_MATERIAL_SQL,  # pyright: ignore[reportPrivateUsage]
        {
            "external_system": _SYSTEM,
            "restore_epoch": 1,
            "material_high_watermark_relay_order": 0,
        },
    )
    assert "uq_cache_target_snapshot_materials_live_identity" in reuse, reuse

    orphan_items = await _explain(
        migrated_session,
        repo._PRUNE_ORPHANED_MATERIAL_ITEMS_SQL,  # pyright: ignore[reportPrivateUsage]
        {"external_system": _SYSTEM, "limit": 1_000},
    )
    assert "pk_poi_cache_target_snapshot_material_items" in orphan_items, orphan_items

    compaction = await _explain(
        migrated_session,
        repo._MARK_COMPACTED_MATERIALS_SQL,  # pyright: ignore[reportPrivateUsage]
        {
            "external_system": _SYSTEM,
            "limit": 100,
            "compaction_retention_seconds": 30 * 24 * 60 * 60,
        },
    )
    # `(materialized_at, material_id) WHERE compacted_at IS NULL`은 술어와 정렬을 함께
    # 만족한다 — 후보 조회가 이것을 타지 않으면 compaction된 material을 매 tick 다시 훑는다.
    assert "idx_cache_target_snapshot_materials_compaction" in compaction, compaction

    receipt_by_material = await _explain(
        migrated_session,
        "SELECT snapshot_id FROM ops.poi_cache_target_snapshots "
        "WHERE material_id = CAST(:material_id AS uuid)",
        {"material_id": _MATERIAL},
    )
    # compaction 후보 조건이 material마다 receipt를 되짚는다 — 이 경로가 seq scan이면
    # GC tick이 receipt 표 전체를 material 수만큼 훑는다.
    assert "idx_cache_target_snapshots_material" in receipt_by_material, (
        receipt_by_material
    )
