"""`0231` material/receipt 모델의 hot query가 실제로 인덱스를 타는지 본다.

정규화가 만든 새 접근 경로 넷을 잰다.

1. **item page 읽기** — `(material_id, row_number)` PK keyset. 1,000,000행짜리 표에서
   page마다 seq scan을 하면 그 자체로 설계가 무너진다.
2. **material 재사용 조회** — identity partial unique. generic/reconciliation이 매 요청
   여기서 갈리므로 가장 자주 도는 술어다.
3. **orphan material item 정리** — GC batch가 매 tick 훑는다.
4. **compaction 후보 조회** — `WHERE compacted_at IS NULL` partial index.

계획을 강제하지 않는다. `enable_seqscan = off`로 "탈 인덱스가 있는가"를 묻는 것이 이
게이트의 질문이고, 실제 처리량은 n150 soak이 따로 잰다.

**fixture 모양이 곧 이 게이트의 유효성이다.** 다섯 번 고쳐 쓰면서 알았다.

- material이 하나면 두 partial index의 비용이 같아 아무 것이나 골라도 통과한다.
- material마다 item이 1행이면 정렬이 공짜라 `(material_id, row_number)` PK 대신
  `(material_id, target_key)` UNIQUE를 고른다.
- **compaction 후보가 0개면 planner의 선택 자체가 무의미하다.** 후보 조건은
  `poi_cache_target_reconciliation_requests` 행을 요구하는데 `receipt_kind`만 맞춘
  fixture에는 그 행이 없어 후보가 0이었다(적대 리뷰 지적). request를 심는다.
- **stream이 하나면 `external_system` 제한이 공짜다.** orphan 정리 인덱스의 값은 다른
  stream의 material을 건너뛰는 데 있으므로 stream을 셋 둔다.
- `enable_seqscan = off` 아래에서 "Seq Scan 노드가 없다"는 **반증 불가능**하다. 인덱스가
  있는 표에서는 어떤 크기에서도 통과한다(적대 리뷰 지적). 그 단언을 인덱스 이름 단언으로
  바꿨다.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import cache_target_reconciliation_repo as repo

pytestmark = pytest.mark.integration

_SYSTEM = "explain:41s"
#: orphan 정리 인덱스의 값은 **다른 stream을 건너뛰는 것**이다. stream이 하나면 그
#: 제한이 공짜라 인덱스가 없어도 같은 계획이 나온다.
_OTHER_SYSTEMS = ("explain:41s-b", "explain:41s-c")
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
    for system in (_SYSTEM, *_OTHER_SYSTEMS):
        await session.execute(
            text(
                "INSERT INTO ops.poi_cache_target_streams ("
                "external_system, consumer_id, restore_epoch) "
                "VALUES (:system, 'explain', 1) ON CONFLICT DO NOTHING"
            ),
            {"system": system},
        )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at) VALUES ("
            "CAST(:material_id AS uuid), :system, 1, 0, 0, 5000, :root, now())"
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
            "'active', 1, :fingerprint FROM generate_series(1, 5000) AS value"
        ),
        {"material_id": _MATERIAL, "fingerprint": "b" * 64},
    )
    # 다른 stream에도 material을 채운다 — orphan 정리 인덱스가 건너뛸 대상이다.
    for index, system in enumerate(_OTHER_SYSTEMS, start=1):
        await session.execute(
            text(
                "INSERT INTO ops.poi_cache_target_snapshot_materials ("
                "material_id, external_system, restore_epoch, "
                "material_high_watermark_relay_order, "
                "safe_high_watermark_relay_order, "
                "item_count, merkle_root, materialized_at) "
                "SELECT CAST(lpad(to_hex(value), 8, '0') "
                "|| '-0000-4000-8000-00000000000' || :suffix AS uuid), "
                ":system, 1, value, value, 0, :root, "
                "now() - make_interval(mins => value) "
                "FROM generate_series(1, 200) AS value"
            ),
            {"system": system, "root": _ROOT, "suffix": str(index + 2)},
        )

    # 후보 조건은 `poi_cache_target_reconciliation_requests` 행을 요구한다 —
    # `receipt_kind`만 맞추면 후보가 0개가 되어 게이트가 아무 것도 재지 않는다.
    # 살아남을 10개(material order 1..10)를 실제 terminal audit 후보로 만든다.
    await session.execute(
        text(
            "INSERT INTO ops.domain_commands ("
            "actor, operation, idempotency_key, request_fingerprint) "
            "SELECT 'explain', 'cache_target.reconcile', "
            "x_extension.gen_random_uuid(), :fingerprint "
            "FROM generate_series(1, 10) AS value"
        ),
        {"fingerprint": "e" * 64},
    )
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_reconciliation_requests ("
            "request_id, external_system, command_id, reason, status, "
            "phase_version, snapshot_id, expected_merkle_root, "
            "actual_merkle_root, started_at, completed_at) "
            "SELECT x_extension.gen_random_uuid(), :system, command.command_id, "
            "'explain', 'succeeded', 3, receipt.snapshot_id, :root, :root, "
            "now() - interval '41 days', now() - interval '40 days' "
            "FROM ("
            "  SELECT receipt.snapshot_id, "
            "         row_number() OVER (ORDER BY receipt.snapshot_id) AS position "
            "  FROM ops.poi_cache_target_snapshots AS receipt "
            "  JOIN ops.poi_cache_target_snapshot_materials AS material "
            "    ON material.material_id = receipt.material_id "
            "  WHERE material.external_system = :system "
            "    AND material.material_high_watermark_relay_order BETWEEN 1 AND 10"
            ") AS receipt "
            "JOIN ("
            "  SELECT command_id, "
            "         row_number() OVER (ORDER BY command_id DESC) AS position "
            "  FROM ops.domain_commands "
            "  WHERE operation = 'cache_target.reconcile' "
            "  ORDER BY command_id DESC LIMIT 10"
            ") AS command ON command.position = receipt.position"
        ),
        {"system": _SYSTEM, "root": _ROOT},
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
        "ops.poi_cache_target_reconciliation_requests",
    ):
        await session.execute(text(f"ANALYZE {relation}"))


async def _compaction_candidate_count(session: AsyncSession) -> int:
    """게이트가 재는 대상이 실재하는지 먼저 센다.

    후보가 0개면 planner의 선택은 무의미하고, 그 위의 인덱스 단언은 통과하면서 아무
    것도 재지 않는다. 실제로 그 상태로 한동안 초록이었다(적대 리뷰 지적).
    """

    predicate = repo._COMPACTION_CANDIDATE_PREDICATE  # pyright: ignore[reportPrivateUsage]
    return int(
        await session.scalar(  # type: ignore[arg-type]
            text(
                "SELECT count(*) "
                "FROM ops.poi_cache_target_snapshot_materials AS material "
                f"WHERE material.external_system = :external_system AND {predicate}"
            ),
            {
                "external_system": _SYSTEM,
                "compaction_retention_seconds": 30 * 24 * 60 * 60,
            },
        )
        or 0
    )


async def test_snapshot_material_hot_queries_have_index_paths(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)

    # 이 게이트의 전제. 후보가 없으면 아래 compaction 단언은 통과하면서 아무 것도
    # 재지 않는다 — 실제로 그 상태였다.
    candidates = await _compaction_candidate_count(migrated_session)
    assert candidates > 0, "compaction 후보가 0개다 — 아래 단언은 아무 것도 재지 않는다"

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
    # 후보는 `external_system` + `compacted_at IS NULL` 범위다. partial unique가 그
    # 범위를 그대로 주므로 이것을 탄다 — 타지 않으면 compaction된 material을 매 tick
    # 다시 훑는다. 살아 있는 material은 stream당 소수라(generic 상한이 2다) 남은
    # `materialized_at` 정렬은 그 소수만 정렬한다.
    assert "uq_cache_target_snapshot_materials_live_identity" in compaction, compaction

    # orphan material 정리는 `compacted_at`을 보지 않아 partial index에 걸리지 못한다.
    # 전용 sweep 인덱스가 없으면 `external_system` 제한을 인덱스로 좁히지 못해 다른
    # stream의 material까지 훑는다 — fixture에 stream이 셋 있어 그 차이가 실재한다.
    #
    # 앞판은 여기서 `enable_seqscan = off` 아래 "Seq Scan 노드가 없다"를 단언했는데,
    # 그 설정이 seq scan에 disable_cost를 더하므로 인덱스가 있는 표에서는 어떤
    # 크기에서도 통과한다 — 반증 불가능한 단언이었다.
    orphan_materials = await _explain(
        migrated_session,
        repo._PRUNE_ORPHANED_MATERIALS_SQL,  # pyright: ignore[reportPrivateUsage]
        {"external_system": _SYSTEM, "limit": 100},
    )
    assert "idx_cache_target_snapshot_materials_sweep" in orphan_materials, (
        orphan_materials
    )

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
