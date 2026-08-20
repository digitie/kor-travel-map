"""T-VN-41S `0230` migration을 격리 DB에서 실측한다.

**빈 DB로는 이 migration을 검증할 수 없다.** backfill/dedupe 문장을 한 줄도 타지 않기
때문이다. 실제로 빈 경로에서는 `min(uuid)` aggregate 부재, receipt append-only fence,
legacy FK 의존 순서가 전부 조용히 지나갔고 셋 다 심은 경로에서만 드러났다. 그래서 이
게이트는 **합칠 것이 있는** 상태(identity 1개 · receipt 3개 · item 2행씩 · 그중 하나는
reconciliation이 참조)를 심고 시작한다.

보는 것: dedupe 결과 · receipt_kind 분기 · legacy 표 제거 · 새 표의 append-only fence
(material은 compaction 1회만 허용) · compaction DELETE 허용 · partial unique가 compaction된
identity를 비워 주는지 · 복합 FK가 receipt 사본 drift를 막는지 · runtime ACL 재조정 ·
downgrade 거부.

거부를 볼 때는 **막힌 이유**까지 본다. §10은 receipt fence를 먼저 끈다 — 켜 둔 채
시험하면 trigger가 막고 FK는 한 번도 평가되지 않는데, 결과만 보면 FK가 막은 것처럼
읽힌다.

usage: scripts/verify-tvn41s-snapshot-material.sh
대상 DB는 ``KOR_TRAVEL_MAP_PG_DSN``으로 받는다 — 인자로 주면 자격증명이 ps에 남는다.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from tests.integration._tvn34_migration_bootstrap import bootstrap_tvn34_migration_roles

STREAM = "rehearsal:41s"
SEEDED = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
)
RECEIPT_FENCE = "trg_poi_cache_target_snapshots_append_only"

_SEED_STREAM_SQL = """
INSERT INTO ops.poi_cache_target_streams (
  external_system, consumer_id, restore_epoch
)
VALUES (:stream, 'rehearsal', 1)
ON CONFLICT DO NOTHING
"""

_SEED_RECEIPTS_SQL = """
INSERT INTO ops.poi_cache_target_snapshots (
  snapshot_id, external_system, restore_epoch, high_watermark_relay_order,
  material_high_watermark_relay_order, item_count, merkle_root,
  created_at, expires_at
)
SELECT CAST(id AS uuid), :stream, 1, 7, 5, 2, repeat('ab', 32),
       now(), now() + interval '1 day'
FROM unnest(CAST(:ids AS text[])) AS id
"""

_SEED_ITEMS_SQL = """
INSERT INTO ops.poi_cache_target_snapshot_items (
  snapshot_id, row_number, external_system, target_key, state,
  source_generation, source_payload_fingerprint
)
SELECT snapshot.snapshot_id, numbers.row_number, :stream,
       'key-' || numbers.row_number, 'active', 1, repeat('cd', 32)
FROM ops.poi_cache_target_snapshots AS snapshot
CROSS JOIN (VALUES (1::bigint), (2::bigint)) AS numbers(row_number)
WHERE snapshot.external_system = :stream
"""

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else '!!'}] {label}: {actual!r} (기대 {expected!r})")
    if not ok:
        failures.append(f"{label}: {actual!r} != {expected!r}")


async def refused_by(engine: AsyncEngine, sql: str, want: str) -> None:
    """`sql`이 `want`를 담은 오류로 막히는지 본다 — 막힌 **이유**까지 본다."""

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            await conn.execute(text(sql))
    except Exception as error:  # noqa: BLE001 — 어떤 오류로 막히는지 그대로 본다
        message = f"{type(error).__name__}: {error}"
        ok = want in message
        print(f"  [{'OK' if ok else '!!'}] 거부 이유에 {want!r}: {message[:150]}")
        if not ok:
            failures.append(f"{want} 아닌 이유로 막힘: {message[:200]}")
        return
    print(f"  [!!] 막히지 않았다 (기대: {want}) — {sql.strip()[:90]}")
    failures.append(f"막히지 않음: {sql.strip()[:90]}")


async def main() -> int:
    repo_root = Path(sys.argv[1])
    dsn = normalize_async_dsn(os.environ["KOR_TRAVEL_MAP_PG_DSN"])

    engine = make_async_engine(dsn, pool_size=1)
    try:
        migrator_password = await bootstrap_tvn34_migration_roles(engine)
    finally:
        await engine.dispose()
    print("role bootstrap OK")

    migrator_dsn = make_url(dsn).set(
        username="ktm_feature_migrator", password=migrator_password
    )
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", migrator_dsn.render_as_string(hide_password=False)
    )
    os.environ["KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"] = "true"

    print("\n== 1) 0229까지 ==")
    await asyncio.to_thread(command.upgrade, config, "0229_tvn40b_source_rule_action")

    print("\n== 2) 합칠 그룹 심기 (identity 1 · receipt 3 · item 2행씩) ==")
    db = make_async_engine(
        normalize_async_dsn(migrator_dsn.render_as_string(hide_password=False)),
        pool_size=1,
    )
    try:
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            await conn.execute(text(_SEED_STREAM_SQL), {"stream": STREAM})
            await conn.execute(
                text(_SEED_RECEIPTS_SQL), {"stream": STREAM, "ids": list(SEEDED)}
            )
            await conn.execute(text(_SEED_ITEMS_SQL), {"stream": STREAM})
            command_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO ops.domain_commands (
                            actor, operation, idempotency_key, request_fingerprint
                        )
                        VALUES ('rehearsal', 'cache_target.reconcile',
                                x_extension.gen_random_uuid(), repeat('ef', 32))
                        RETURNING command_id
                        """
                    )
                )
            ).scalar_one()
            # 하나는 reconciliation이 참조하게 만들어 receipt_kind 분기를 실제로 탄다.
            await conn.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_reconciliation_requests (
                        request_id, external_system, command_id, reason, status,
                        snapshot_id, expected_merkle_root, actual_merkle_root,
                        started_at, completed_at
                    )
                    VALUES (x_extension.gen_random_uuid(), :stream, :command_id,
                            'rehearsal', 'succeeded', CAST(:snapshot_id AS uuid),
                            repeat('ab', 32), repeat('ab', 32), now(), now())
                    """
                ),
                {"stream": STREAM, "command_id": command_id, "snapshot_id": SEEDED[0]},
            )
        async with db.connect() as conn:
            seeded_receipts = (
                await conn.execute(
                    text("SELECT count(*) FROM ops.poi_cache_target_snapshots")
                )
            ).scalar_one()
            seeded_items = (
                await conn.execute(
                    text("SELECT count(*) FROM ops.poi_cache_target_snapshot_items")
                )
            ).scalar_one()
        print(f"  심은 receipt={seeded_receipts} item={seeded_items}")

        print("\n== 3) 0230 ==")
        await asyncio.to_thread(command.upgrade, config, "0230_tvn41s_snapshot_material")

        print("\n== 4) 결과 ==")
        async with db.connect() as conn:

            async def scalar(sql: str) -> object:
                return (await conn.execute(text(sql))).scalar_one()

            check(
                "material 수 (receipt 3 -> material 1)",
                await scalar(
                    "SELECT count(*) FROM ops.poi_cache_target_snapshot_materials"
                ),
                1,
            )
            check(
                "material item 수 (중복 6행 -> 2행)",
                await scalar(
                    "SELECT count(*)"
                    " FROM ops.poi_cache_target_snapshot_material_items"
                ),
                2,
            )
            check(
                "receipt 수 (그대로)",
                await scalar("SELECT count(*) FROM ops.poi_cache_target_snapshots"),
                3,
            )
            check(
                "세 receipt가 material 하나를 공유",
                await scalar(
                    "SELECT count(DISTINCT material_id)"
                    " FROM ops.poi_cache_target_snapshots"
                ),
                1,
            )
            check(
                "receipt_kind 분기",
                await scalar(
                    "SELECT string_agg(DISTINCT receipt_kind, ',')"
                    " FROM ops.poi_cache_target_snapshots"
                ),
                "generic,reconciliation",
            )
            check(
                "reconciliation receipt 1건",
                await scalar(
                    "SELECT count(*) FROM ops.poi_cache_target_snapshots"
                    " WHERE receipt_kind = 'reconciliation'"
                ),
                1,
            )
            check(
                "legacy item 표 제거",
                await scalar(
                    "SELECT to_regclass('ops.poi_cache_target_snapshot_items')::text"
                ),
                None,
            )
            check(
                "대표 material_id = min(snapshot_id)",
                str(
                    await scalar(
                        "SELECT material_id"
                        " FROM ops.poi_cache_target_snapshot_materials"
                    )
                ),
                SEEDED[0],
            )
            check(
                "legacy material_bytes는 NULL",
                await scalar(
                    "SELECT count(*) FROM ops.poi_cache_target_snapshot_materials"
                    " WHERE material_bytes IS NOT NULL"
                ),
                0,
            )
            fence_state = await scalar(
                "SELECT tgenabled FROM pg_trigger"
                f" WHERE tgname = '{RECEIPT_FENCE}'"
                " AND tgrelid = 'ops.poi_cache_target_snapshots'::regclass"
            )
            check(
                "receipt fence가 다시 켜져 있다",
                fence_state.decode("ascii")
                if isinstance(fence_state, bytes)
                else fence_state,
                "O",
            )

        print("\n== 5) 새 표도 append-only인가 ==")
        await refused_by(
            db,
            "UPDATE ops.poi_cache_target_snapshot_material_items"
            " SET target_key = 'rewritten'",
            "append-only",
        )
        await refused_by(
            db,
            "UPDATE ops.poi_cache_target_snapshot_materials SET item_count = 99",
            "append-only except compaction",
        )
        await refused_by(
            db,
            "UPDATE ops.poi_cache_target_snapshot_materials"
            " SET compacted_at = now(), merkle_root = repeat('ff', 32)",
            "must not change the material",
        )

        print("\n== 6) compaction 자체는 통과하고, 두 번은 막는가 ==")
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            await conn.execute(
                text(
                    "UPDATE ops.poi_cache_target_snapshot_materials"
                    " SET compacted_at = now()"
                )
            )
        print("  [OK] compacted_at NULL -> NOT NULL 1회 허용")
        await refused_by(
            db,
            "UPDATE ops.poi_cache_target_snapshot_materials SET compacted_at = now()",
            "already compacted",
        )

        print("\n== 7) compaction DELETE는 허용되는가 ==")
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            deleted = (
                await conn.execute(
                    text(
                        "DELETE FROM ops.poi_cache_target_snapshot_material_items"
                        " WHERE row_number = 2"
                    )
                )
            ).rowcount
        check("compaction DELETE 허용", deleted, 1)

        print("\n== 8) compaction된 identity를 다시 고정할 수 있는가 ==")
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            await conn.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_snapshot_materials (
                      material_id, external_system, restore_epoch,
                      material_high_watermark_relay_order,
                      safe_high_watermark_relay_order, item_count,
                      merkle_root, materialized_at
                    ) VALUES (
                      '44444444-4444-4444-8444-444444444444', :stream, 1, 5, 7, 2,
                      repeat('ab', 32), now()
                    )
                    """
                ),
                {"stream": STREAM},
            )
        print("  [OK] partial unique가 compaction된 identity를 비워 준다")

        print("\n== 9) 살아 있는 identity 중복은 막는가 ==")
        await refused_by(
            db,
            """
            INSERT INTO ops.poi_cache_target_snapshot_materials (
              material_id, external_system, restore_epoch,
              material_high_watermark_relay_order,
              safe_high_watermark_relay_order, item_count,
              merkle_root, materialized_at
            ) VALUES (
              '55555555-5555-4555-8555-555555555555', 'rehearsal:41s', 1, 5, 7, 2,
              repeat('ab', 32), now()
            )
            """,
            "uq_cache_target_snapshot_materials_live_identity",
        )

        print("\n== 10) 복합 FK가 receipt의 external_system 사본 drift를 막는가 ==")
        # receipt fence를 먼저 끈다 — 켜 둔 채 시험하면 trigger가 막고 FK는 한 번도
        # 평가되지 않는데, 결과만 보면 FK가 막은 것처럼 읽힌다.
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            await conn.execute(
                text(
                    "ALTER TABLE ops.poi_cache_target_snapshots"
                    f" DISABLE TRIGGER {RECEIPT_FENCE}"
                )
            )
        # receipt가 material에서 물려받은 사본은 `external_system` 하나다(safe cursor를
        # material로 옮긴 뒤). **존재하는 다른 stream**으로 바꿔야 stream FK는 만족하고
        # material 복합 FK만 걸린다 — 없는 stream을 쓰면 stream FK가 먼저 막아서 이
        # 검사가 다른 것을 보게 된다.
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            await conn.execute(text(_SEED_STREAM_SQL), {"stream": f"{STREAM}:other"})
        try:
            await refused_by(
                db,
                "UPDATE ops.poi_cache_target_snapshots"
                f" SET external_system = '{STREAM}:other'",
                "fk_cache_target_snapshots_material",
            )
        finally:
            async with db.begin() as conn:
                await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
                await conn.execute(
                    text(
                        "ALTER TABLE ops.poi_cache_target_snapshots"
                        f" ENABLE TRIGGER {RECEIPT_FENCE}"
                    )
                )
    finally:
        await db.dispose()

    print("\n== 11) runtime ACL 재조정 ==")
    from kortravelmap.infra.runtime_privileges import (  # noqa: PLC0415
        reconcile_runtime_privileges,
    )

    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = migrator_dsn.render_as_string(
        hide_password=False
    )
    await reconcile_runtime_privileges()
    print("  reconcile_runtime_privileges OK")

    print("\n== 12) downgrade 거부 ==")
    refused = False
    try:
        await asyncio.to_thread(command.downgrade, config, "-1")
    except RuntimeError as error:
        # "forward-only"만 보면 `alembic/env.py`의 0200 경계 guard가 발화해도
        # 통과한다(그 문구도 forward-only를 담는다). revision id까지 본다.
        refused = "0230_tvn41s_snapshot_material is forward-only" in str(error)
        print(f"  거부됨: {str(error)[:90]}")
    check("downgrade 거부", refused, True)

    print()
    if failures:
        print("REHEARSAL: FAIL")
        for failure in failures:
            print("  !", failure)
        return 4
    print("REHEARSAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
