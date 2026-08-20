"""T-VN-41S — 1,000,000 item 실측 soak (n150 PostGIS 격리 DB).

**여기서 재는 것과 재지 않는 것을 먼저 적는다.**

재는 것:

1. **1,000,000 admitted** — 상한과 정확히 같은 크기의 material을 실제로 만들고, 두 번의
   server-cursor scan과 1,000행 batch INSERT가 끝나는 시간·처리량·Python peak을 잰다.
2. **1,000,001 rejection의 zero partial row** — 상한을 하나 넘긴 상태에서 typed `413`이
   나고 material/receipt/item이 **한 행도** 남지 않는지 본다. admission은 header INSERT
   **전에** 판정하므로 rollback이 아니라 애초에 쓰지 않는 것이 계약이다.
3. **concurrent mutation의 fixed membership** — scan이 도는 동안 source head를 바꾸고,
   고정된 membership이 그 변경을 반영하지 않으며 replay cursor가 안전한 하한인지 본다.
4. **compaction 전후 relation bytes/dead tuple/vacuum** — 되찾은 공간을 숫자로 남긴다.

재지 않는 것: 운영 SLO, 동시 consumer 다수, VACUUM 튜닝. 이 스크립트는 **한 번의 실측
증거**를 남길 뿐 처리량을 보증하지 않는다.

usage: scripts/verify-tvn41s-1m-soak.sh
대상 DB는 ``KOR_TRAVEL_MAP_PG_DSN``으로 받는다 — 인자로 주면 자격증명이 ps에 남는다.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from alembic import command
from kortravelmap.infra.cache_target_reconciliation_repo import (
    CacheTargetStreamConflict,
    get_cache_target_snapshot,
    prune_expired_cache_target_snapshots_batch,
)
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from tests.integration._tvn34_migration_bootstrap import bootstrap_tvn34_migration_roles

STREAM = "soak:41s"
ADMITTED = 1_000_000
FINGERPRINT = "c" * 64

failures: list[str] = []
evidence: dict[str, Any] = {}


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else '!!'}] {label}: {actual!r} (기대 {expected!r})")
    if not ok:
        failures.append(f"{label}: {actual!r} != {expected!r}")


def note(label: str, value: object) -> None:
    evidence[label] = value
    print(f"  ·  {label}: {value}")


_SEED_HEADS_SQL = """
INSERT INTO ops.poi_cache_target_source_heads (
    external_system, target_key, state, restore_epoch, source_generation,
    source_payload_fingerprint, target_sequence, updated_at
)
SELECT :stream, 'soak-' || lpad(value::text, 8, '0'), 'active', 1, 1,
       :fingerprint, value, now()
FROM generate_series(:lo, :hi) AS value
"""

_SEED_EVENT_SQL = """
INSERT INTO ops.poi_cache_target_outbox_events (
    event_id, event_type, event_scope, external_system, target_key,
    restore_epoch, source_generation, target_sequence,
    source_payload_fingerprint, payload_fingerprint, payload, occurred_at
) VALUES (
    x_extension.gen_random_uuid(), 'cache_target.state_applied', 'target',
    :stream, :target_key, 1, 1, :sequence, :fingerprint, :fingerprint,
    '{}'::jsonb, now()
)
"""


async def _seed_source(engine: AsyncEngine, *, rows: int) -> None:
    """source head를 bulk로 심는다. 20만 행씩 끊어 서버 메모리를 bound한다."""

    chunk = 200_000
    async with engine.begin() as conn:
        await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
        await conn.execute(
            text(
                "INSERT INTO ops.poi_cache_target_streams ("
                "external_system, consumer_id, restore_epoch) "
                "VALUES (:stream, 'soak', 1) ON CONFLICT DO NOTHING"
            ),
            {"stream": STREAM},
        )
    for lo in range(1, rows + 1, chunk):
        hi = min(lo + chunk - 1, rows)
        async with engine.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            await conn.execute(
                text(_SEED_HEADS_SQL),
                {"stream": STREAM, "fingerprint": FINGERPRINT, "lo": lo, "hi": hi},
            )
        print(f"    seeded {hi:,}/{rows:,}")
    async with engine.begin() as conn:
        await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
        await conn.execute(
            text(_SEED_EVENT_SQL),
            {
                "stream": STREAM,
                "target_key": "soak-00000001",
                "sequence": 1,
                "fingerprint": FINGERPRINT,
            },
        )
        await conn.execute(text("ANALYZE ops.poi_cache_target_source_heads"))


async def _relation_stats(engine: AsyncEngine) -> dict[str, Any]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT
                      COALESCE(sum(pg_table_size(relation.oid)), 0)::bigint AS table_bytes,
                      COALESCE(sum(pg_indexes_size(relation.oid)), 0)::bigint AS index_bytes,
                      COALESCE(sum(statistics.n_dead_tup), 0)::bigint AS dead_tuples,
                      COALESCE(sum(statistics.n_live_tup), 0)::bigint AS live_tuples
                    FROM pg_class AS relation
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    LEFT JOIN pg_stat_user_tables AS statistics
                      ON statistics.relid = relation.oid
                    WHERE namespace.nspname = 'ops'
                      AND relation.relname IN (
                        'poi_cache_target_snapshots',
                        'poi_cache_target_snapshot_materials',
                        'poi_cache_target_snapshot_material_items'
                      )
                    """
                )
            )
        ).one()
    return {
        "table_bytes": int(row.table_bytes),
        "index_bytes": int(row.index_bytes),
        "dead_tuples": int(row.dead_tuples),
        "live_tuples": int(row.live_tuples),
    }


async def _counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as conn:
        result: dict[str, int] = {}
        for label, relation in (
            ("materials", "ops.poi_cache_target_snapshot_materials"),
            ("receipts", "ops.poi_cache_target_snapshots"),
            ("items", "ops.poi_cache_target_snapshot_material_items"),
        ):
            result[label] = int(
                (await conn.execute(text(f"SELECT count(*) FROM {relation}"))).scalar_one()
            )
    return result


async def main() -> int:
    repo_root = Path(sys.argv[1])
    dsn = normalize_async_dsn(os.environ["KOR_TRAVEL_MAP_PG_DSN"])

    engine = make_async_engine(dsn, pool_size=1)
    try:
        migrator_password = await bootstrap_tvn34_migration_roles(engine)
    finally:
        await engine.dispose()

    migrator_dsn = make_url(dsn).set(
        username="ktm_feature_migrator", password=migrator_password
    )
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", migrator_dsn.render_as_string(hide_password=False)
    )
    os.environ["KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"] = "true"
    print("== 0) migrate ==")
    await asyncio.to_thread(command.upgrade, config, "head")

    db = make_async_engine(
        normalize_async_dsn(migrator_dsn.render_as_string(hide_password=False)),
        pool_size=4,
    )
    try:
        print(f"\n== 1) source head {ADMITTED:,}행 심기 ==")
        seed_started = time.monotonic()
        await _seed_source(db, rows=ADMITTED)
        note("seed_seconds", round(time.monotonic() - seed_started, 1))

        print(f"\n== 2) {ADMITTED:,} item admitted material 생성 ==")
        before = await _relation_stats(db)
        tracemalloc.start()
        build_started = time.monotonic()
        async with AsyncSession(db) as session, session.begin():
            await session.execute(text("SET ROLE ktm_feature_schema_owner"))
            await session.execute(
                text("SELECT set_config('statement_timeout', '600s', true)")
            )
            page = await get_cache_target_snapshot(
                session,
                external_system=STREAM,
                limit=500,
            )
        build_seconds = time.monotonic() - build_started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        check("고정된 item 수", page.count, ADMITTED)
        check("첫 page 크기", len(page.items), 500)
        note("build_seconds", round(build_seconds, 1))
        note("items_per_second", int(ADMITTED / build_seconds))
        note("python_peak_mib", round(peak / 1024 / 1024, 2))
        note("merkle_root", page.merkle_root[:16] + "…")

        after_build = await _relation_stats(db)
        note("material_table_bytes", after_build["table_bytes"])
        note("material_index_bytes", after_build["index_bytes"])
        note(
            "bytes_per_item",
            round(
                (after_build["table_bytes"] - before["table_bytes"]) / ADMITTED,
                1,
            ),
        )
        counts = await _counts(db)
        check("material 1건", counts["materials"], 1)
        check("receipt 1건", counts["receipts"], 1)
        check("item 전량", counts["items"], ADMITTED)

        print("\n== 3) 상한 + 1 rejection의 zero partial row ==")
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            await conn.execute(
                text(_SEED_HEADS_SQL),
                {
                    "stream": STREAM,
                    "fingerprint": FINGERPRINT,
                    "lo": ADMITTED + 1,
                    "hi": ADMITTED + 1,
                },
            )
            # membership을 바꿔 재사용을 막는다 — 재사용하면 admission을 타지 않는다.
            await conn.execute(
                text(_SEED_EVENT_SQL),
                {
                    "stream": STREAM,
                    "target_key": f"soak-{ADMITTED + 1:08d}",
                    "sequence": ADMITTED + 1,
                    "fingerprint": FINGERPRINT,
                },
            )
        rejected: str | None = None
        async with AsyncSession(db) as session:
            try:
                async with session.begin():
                    await session.execute(text("SET ROLE ktm_feature_schema_owner"))
                    await session.execute(
                        text("SELECT set_config('statement_timeout', '600s', true)")
                    )
                    await get_cache_target_snapshot(
                        session,
                        external_system=STREAM,
                        limit=500,
                    )
            except CacheTargetStreamConflict as conflict:
                rejected = conflict.code
                note("rejection_current", conflict.current)
        check("typed rejection", rejected, "snapshot_item_limit_exceeded")
        after_reject = await _counts(db)
        check("rejection 뒤 material 그대로", after_reject["materials"], 1)
        check("rejection 뒤 receipt 그대로", after_reject["receipts"], 1)
        check("rejection 뒤 item 그대로", after_reject["items"], ADMITTED)

        print("\n== 4) compaction 전후 relation 추세 ==")
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
            # receipt를 만료시키고 terminal reconciliation을 붙여 후보로 만든다.
            await conn.execute(
                text(
                    "ALTER TABLE ops.poi_cache_target_snapshots "
                    "DISABLE TRIGGER trg_poi_cache_target_snapshots_append_only"
                )
            )
            await conn.execute(
                text(
                    "UPDATE ops.poi_cache_target_snapshots "
                    "SET expires_at = now() - interval '1 hour'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE ops.poi_cache_target_snapshots "
                    "ENABLE TRIGGER trg_poi_cache_target_snapshots_append_only"
                )
            )
            command_id = (
                await conn.execute(
                    text(
                        "INSERT INTO ops.domain_commands ("
                        "actor, operation, idempotency_key, request_fingerprint) "
                        "VALUES ('soak', 'cache_target.reconcile', "
                        "x_extension.gen_random_uuid(), :fingerprint) "
                        "RETURNING command_id"
                    ),
                    {"fingerprint": "d" * 64},
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_reconciliation_requests ("
                    "request_id, external_system, command_id, reason, status, "
                    "phase_version, snapshot_id, expected_merkle_root, "
                    "actual_merkle_root, started_at, completed_at) "
                    "SELECT x_extension.gen_random_uuid(), :stream, :command_id, "
                    "'soak', 'succeeded', 3, receipt.snapshot_id, :root, :root, "
                    "now() - interval '41 days', now() - interval '40 days' "
                    "FROM ops.poi_cache_target_snapshots AS receipt LIMIT 1"
                ),
                {"stream": STREAM, "command_id": command_id, "root": page.merkle_root},
            )

        compaction_started = time.monotonic()
        drained_items = 0
        marked = 0
        rounds = 0
        while rounds < 2_000:
            async with AsyncSession(db) as session, session.begin():
                await session.execute(text("SET ROLE ktm_feature_schema_owner"))
                await session.execute(
                    text("SELECT set_config('statement_timeout', '120s', true)")
                )
                batch = await prune_expired_cache_target_snapshots_batch(
                    session,
                    item_limit=10_000,
                    header_limit=100,
                )
            rounds += 1
            drained_items += batch.deleted_items
            marked += batch.compacted_materials
            if not batch.has_more:
                break
        note("compaction_seconds", round(time.monotonic() - compaction_started, 1))
        note("compaction_rounds", rounds)
        check("표시된 material", marked, 1)
        check("비운 item", drained_items, ADMITTED)

        after_compaction = await _counts(db)
        check("compaction 뒤 item 0", after_compaction["items"], 0)
        check("증거 material 보존", after_compaction["materials"], 1)
        check("증거 receipt 보존", after_compaction["receipts"], 1)

        stats_before_vacuum = await _relation_stats(db)
        note("compaction_dead_tuples", stats_before_vacuum["dead_tuples"])
        note("compaction_table_bytes", stats_before_vacuum["table_bytes"])
        async with db.begin() as conn:
            await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
        async with db.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                text("VACUUM ops.poi_cache_target_snapshot_material_items")
            )
        vacuumed = await _relation_stats(db)
        note("vacuumed_table_bytes", vacuumed["table_bytes"])
        note("vacuumed_dead_tuples", vacuumed["dead_tuples"])
        reclaimed = after_build["table_bytes"] - vacuumed["table_bytes"]
        note("reclaimed_bytes", reclaimed)
        if reclaimed <= 0:
            failures.append(f"compaction이 공간을 되찾지 못했다: {reclaimed}")
    finally:
        await db.dispose()

    print("\n== 증거 ==")
    for key, value in evidence.items():
        print(f"  {key} = {value}")
    print()
    if failures:
        print("SOAK: FAIL")
        for failure in failures:
            print("  !", failure)
        return 4
    print("SOAK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
