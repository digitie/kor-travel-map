"""T-VN-41S — 1,000,000 item 실측 soak (n150 PostGIS 격리 DB).

**여기서 재는 것과 재지 않는 것을 먼저 적는다.**

재는 것:

1. **1,000,000 admitted** — 상한과 정확히 같은 크기의 material을 실제로 만들고, 두 번의
   server-cursor scan과 1,000행 batch INSERT가 끝나는 시간·처리량·Python peak을 잰다.
2. **1,000,001 rejection의 zero partial row** — 상한을 하나 넘긴 상태에서 typed `413`이
   나고 material/receipt/item이 **한 행도** 남지 않는지 본다. admission은 header INSERT
   **전에** 판정하므로 rollback이 아니라 애초에 쓰지 않는 것이 계약이다.
3. **compaction 전후 relation bytes/dead tuple/vacuum** — 되찾은 공간을 숫자로 남긴다.

**여기서 재지 않는 것**: 운영 SLO, 동시 consumer 다수, VACUUM 튜닝. 그리고
**concurrent mutation의 fixed membership과 safe lower cursor는 이 스크립트가 재지
않는다** — 그 성질은 `tests/integration/test_cache_target_stream_repo.py`의
`test_fixed_snapshot_pages_ignore_concurrent_committed_write`,
`test_snapshot_barrier_keeps_outbox_cursor_commit_safe_across_writers`,
`test_generic_snapshot_reuse_ignores_nonmaterial_outbox_tail`이 작은 규모에서 정확히
본다. 여기서 다시 흉내 내면 같은 성질을 덜 정확하게 보는 두 번째 게이트가 될 뿐이다.

이 스크립트는 **한 번의 실측 증거**를 남길 뿐 처리량을 보증하지 않는다.

**종료 코드는 셋이다.** `0` = 전부 통과, `3` = 측정 축은 통과했고 **결정 대기** 항목만
남음, `4` = 실제 퇴행, `5` = **결정 대기 항목이 통과하기 시작**했다(보고서·백로그가 낡았다).
`3`과 `5`를 나눈 이유는 둘이 운영상 반대 신호이기 때문이다 — `3`은 "아직", `5`는 "이제
됐으니 문서를 고쳐라"다. `0`은 결정이 백로그에서 닫히고 이 스크립트의 결정 항목이 제거된
뒤에만 나온다. 지금은 `3`이다 — 광고한 1,000,000 item 상한이 배포 build 예산
(300초) 안에 들지 않는다. 그것을 그냥 `note`로 적고 `PASS(0)`을 찍으면 종료 코드가
보고서와 반대를 말하고, 반대로 `FAIL(4)`로 뭉뚱그리면 다른 다섯 축이 퇴행해도 종료
코드가 그대로라 아무도 차이를 못 본다. 근거는
`docs/reports/t-vn-41s-1m-soak-2026-08-21.md` §"열린 결정".

**source head는 tombstone(`state='deleted'`)으로 심는다.** `active`는
`target_id IS NOT NULL`을 요구하고 그 FK 때문에 `ops.poi_cache_targets` 1,000,000행이
따로 필요해진다. membership은 두 state를 모두 담고(merkle leaf는 state 1바이트만 다르다)
item 행에는 `target_id`가 없으므로, 여기서 재는 축(scan 처리량·item 행 크기·compaction
회수량)에는 차이가 없다. `active` 혼합 분포를 재고 싶다면 target을 함께 심어야 한다.

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
from kortravelmap.infra import cache_target_reconciliation_repo as repo
from kortravelmap.infra.cache_target_reconciliation_repo import (
    CacheTargetStreamConflict,
    get_cache_target_snapshot,
    prune_expired_cache_target_snapshots_batch,
)
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from tests.integration._tvn34_migration_bootstrap import bootstrap_tvn34_migration_roles

STREAM = "soak:41s"
#: 측정 대상 item 수. 인자로 주면 그 값, 없으면 배포 상한을 그대로 잰다 —
#: soak이 상한과 다른 크기를 재고 있으면 그 결과는 상한을 보증하지 못한다.
_CEILING = repo._SNAPSHOT_ITEM_LIMIT  # noqa: SLF001
ADMITTED = int(sys.argv[2]) if len(sys.argv) > 2 else _CEILING

#: **예산을 우회하지 않는다.** 예전 판은 측정 동안 `_SNAPSHOT_BUILD_TIMEOUT_SECONDS`를
#: 3,600초로 덮고 session `statement_timeout`도 3,600초로 올렸다. 그러면 `build_seconds`가
#: 배포 예산보다 작다는 **사후 비교**만 남고 `_snapshot_build_deadline`은 한 번도 돌지
#: 않는다 — 상한 크기 build가 배포 deadline을 넘기 시작해도 typed `snapshot_build_timeout`
#: 이 아니라 그냥 큰 숫자로 보인다. 지금은 배포 예산 그대로 돌고, 넘으면 그 자체가 실패다.
_SHIPPED_BUILD_BUDGET_SECONDS = repo._SNAPSHOT_BUILD_TIMEOUT_SECONDS  # noqa: SLF001
#: 안전계수는 repo가 정본이다 — soak과 단위 테스트가 같은 값을 읽어야 한다.
REQUIRED_SAFETY_FACTOR = repo.SNAPSHOT_BUILD_SAFETY_FACTOR

failures: list[str] = []
#: 결정 대기 중이라 red인 것이 정상인 항목. `failures`와 섞지 않는다 — 섞으면 다른 축이
#: 퇴행해도 종료 코드가 같아 아무도 차이를 못 본다.
known_open: list[str] = []
#: 반대 신호 — 결정 대기 항목이 **통과하기 시작**했다. "아직 안 됐다"와 "이제 됐으니 문서를
#: 고쳐라"는 운영상 반대 뜻이므로 종료 코드를 나눈다(적대 리뷰 지적).
docs_stale: list[str] = []
evidence: dict[str, Any] = {}


def check(label: str, actual: object, expected: object) -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else '!!'}] {label}: {actual!r} (기대 {expected!r})")
    if not ok:
        failures.append(f"{label}: {actual!r} != {expected!r}")


def note(label: str, value: object) -> None:
    evidence[label] = value
    print(f"  ·  {label}: {value}")


#: fixture는 정렬 비용을 정직하게 재야 한다. 예전 판은 `'soak-' || lpad(value, 8)`로
#: **13자 ASCII를 삽입 순서대로** 심었는데, build의 정렬 키가
#: `convert_to(normalize(target_key, NFC), 'UTF8')`이고 그 표현식에 인덱스가 없으므로
#: 그 fixture는 heap correlation ≈ 1.0인 **최선 조건**을 잰 것이었다. prod 실측 키는
#: 24~36자(평균 35.1, 전부 ASCII)이므로 md5 기반 37자로 맞춘다 — md5는 삽입 순서와
#: 정렬 순서의 상관도 함께 끊어 준다.
#: fingerprint도 상수를 쓰지 않는다 — 상수 fingerprint는 sha256 입력 지역성과 페이지
#: 압축률을 비현실적으로 좋게 만든다. state는 `deleted`로 둔다: `active` head는
#: `target_id`가 가리키는 실제 `ops.poi_cache_targets` 행(좌표 계열 CHECK 포함)을
#: 요구하므로 fixture 비용이 측정 대상을 압도한다. 정렬 비용은 키 폭·순서가 지배하고
#: state는 leaf 1바이트라 이 축의 대표성을 해치지 않는다.
_SEED_HEADS_SQL = """
INSERT INTO ops.poi_cache_target_source_heads (
    external_system, target_key, state, restore_epoch, source_generation,
    source_payload_fingerprint, target_sequence, updated_at
)
SELECT :stream,
       's-' || md5(value::text) || '-' || lpad((value % 100)::text, 2, '0'),
       'deleted',
       1, 1,
       md5(value::text) || md5((value + 1)::text),
       value, now()
FROM generate_series(CAST(:lo AS bigint), CAST(:hi AS bigint)) AS value
"""

#: material identity를 바꿔 재사용을 막는 가장 싼 방법. outbox event로 material
#: watermark를 올리려면 `target` scope event가 `target_id`를 요구하고 그 FK 때문에
#: 실제 `ops.poi_cache_targets` 행(좌표 계열 CHECK 포함)이 필요해진다. 여기서 재는 것은
#: admission이지 fencing이 아니므로 identity의 다른 축인 `restore_epoch`을 올린다.
_BUMP_RESTORE_EPOCH_SQL = """
UPDATE ops.poi_cache_target_streams
SET restore_epoch = restore_epoch + 1, updated_at = now()
WHERE external_system = :stream
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
                {"stream": STREAM, "lo": lo, "hi": hi},
            )
        print(f"    seeded {hi:,}/{rows:,}")
    async with engine.begin() as conn:
        await conn.execute(text("SET ROLE ktm_feature_schema_owner"))
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
        note("shipped_build_budget_seconds", _SHIPPED_BUILD_BUDGET_SECONDS)
        # `note`가 아니라 `check`다. "광고한 상한이 실제로 도달 가능하다"는 이 soak이
        # 재는 성질이고, 지금 그것은 **거짓**이다. 거짓인 채 `SOAK: PASS`를 찍으면
        # 종료 코드가 보고서와 반대를 말한다(적대 리뷰 지적).
        # 상한과 같은 크기가 **배포 예산 안에서, 여유를 갖고** 끝나는지가 이 soak의
        # 본 판정이다. 예전에는 정책 결정 대기라 red를 따로 셌지만, 결정이 닫힌 뒤로는
        # 그냥 실패다 — admission이 받아들인 크기를 build가 못 끝내면 계약이 거짓말이다.
        #
        # 여유를 요구하는 이유: 이 측정은 조용한 호스트의 한 번이고, 운영에서는 항상
        # 다른 부하가 있다. 정렬 키 표현식에 인덱스가 없어 비용이 Θ(N log N)이고
        # work_mem 절벽도 있으므로, 예산에 겨우 드는 값은 상한으로 삼을 수 없다.
        budget_ceiling = _SHIPPED_BUILD_BUDGET_SECONDS / REQUIRED_SAFETY_FACTOR
        check(
            f"build이 예산/{REQUIRED_SAFETY_FACTOR:.0f} 안에 든다"
            f" ({build_seconds:.1f}s <= {budget_ceiling:.0f}s)",
            build_seconds <= budget_ceiling,
            True,
        )
        if ADMITTED != repo._SNAPSHOT_ITEM_LIMIT:  # noqa: SLF001
            docs_stale.append(
                f"soak이 상한이 아닌 크기를 쟀다: ADMITTED={ADMITTED:,} != "
                f"상한 {repo._SNAPSHOT_ITEM_LIMIT:,}"  # noqa: SLF001
                " — 이 결과는 상한을 보증하지 않는다"
            )
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
                    # 3단계가 재는 것은 **상한 + 1 거부**다. ADMITTED가 상한보다 작으면
                    # ADMITTED + 1은 상한 아래라 아무것도 거부되지 않고, 그런데도 그 아래
                    # 단언들이 ADMITTED를 기대해 통과처럼 보이지 않고 엉뚱하게 실패한다.
                    "lo": ADMITTED + 1,
                    "hi": _CEILING + 1,
                },
            )
            # identity를 바꿔 재사용을 막는다 — 재사용하면 admission을 타지 않고
            # 이 단계가 아무 것도 재지 않는다.
            await conn.execute(text(_BUMP_RESTORE_EPOCH_SQL), {"stream": STREAM})
        rejected: str | None = None
        async with AsyncSession(db) as session:
            try:
                async with session.begin():
                    await session.execute(text("SET ROLE ktm_feature_schema_owner"))
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
                # `expires_at > created_at` CHECK가 있다. 방금 만든 receipt라
                # `now() - 1 hour`는 created_at보다 이르다.
                text(
                    "UPDATE ops.poi_cache_target_snapshots "
                    "SET expires_at = created_at + interval '1 millisecond'"
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
    for item in known_open + docs_stale:
        print("  ~", item)
    if failures:
        print("SOAK: FAIL")
        for failure in failures:
            print("  !", failure)
        return 4
    if docs_stale:
        print("SOAK: PASS (열린 결정이 해소됐다 — 보고서·백로그를 갱신하라)")
        return 5
    if known_open:
        # 측정 축은 전부 통과했고 남은 것은 결정뿐이다. 종료 코드를 나눠 둬야
        # 퇴행(4)과 미결(3)을 wrapper가 구분할 수 있다.
        print("SOAK: PASS (열린 결정 대기)")
        return 3
    print("SOAK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
