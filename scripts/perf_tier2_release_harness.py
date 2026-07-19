#!/usr/bin/env python3
"""Tier-2 release/cutover 성능 harness — performance.md §8.3, ADR-075 D-12-4.

**PR gate가 아니다.** release/cutover 절차에서만 수동 실행한다(§8.3 tier-2). 100만+
실분포 fixture에서 대표 viewport를 ``EXPLAIN (ANALYZE, BUFFERS)``로 재고, n150 기준
p95 실행시간·shared read blocks·응답 bytes budget을 기록한다. CI에서 절대 돌리지
않는다(대용량 fixture는 CI 시간/자원을 초과).

대표 viewport (§8.3):
  - 서울 밀집 in-bounds
  - 전국 low-zoom cluster rollup
  - 100km nearby
  - 상용 검색어 search
  - 200건 batch

사용법 (별도 준비된 빈 PostGIS + alembic head 적용 DB에):
    KOR_TRAVEL_MAP_PG_DSN=postgresql+asyncpg://... \
      python scripts/perf_tier2_release_harness.py --rows 1000000 --iterations 30

``--skip-seed``로 이미 적재된 DB를 그대로 잰다. fixture 생성은 수 분~수십 분이
걸릴 수 있다. 결과는 JSON으로 stdout에 출력하며 release 리포트에 첨부한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from kortravelmap.infra.db import make_async_engine, normalize_async_dsn  # noqa: E402
from kortravelmap.infra.feature_repo import (  # noqa: E402
    _CLUSTER_BBOX_SQL_BY_UNIT,
    _FEATURE_SEARCH_BY_SCORE_SQL,
    _FEATURES_IN_BBOX_SQL,
    _GET_PUBLIC_FEATURES_BY_IDS_SQL,
    _NEARBY_COORD_DISTANCE_SQL,
)
from tests.integration.perf_gate import seed_hot_query_features  # noqa: E402

# ── 대표 viewport 정의 (§8.3) ────────────────────────────────────────────────

_SEOUL_DENSE_BBOX = {
    "min_lon": 126.96,
    "min_lat": 37.50,
    "max_lon": 127.06,
    "max_lat": 37.58,
    "kinds": ["place", "event"],
    "categories": None,
    "providers": None,
    "cursor_feature_id": None,
    "limit": 200,
    "price_stale_hide_days": 4,
}
_NATIONWIDE_LOWZOOM_BBOX = {
    "min_lon": 125.0,
    "min_lat": 33.0,
    "max_lon": 132.0,
    "max_lat": 39.0,
    "kinds": ["place", "event"],
    "categories": None,
    "providers": None,
    "limit": 200,
}
_NEARBY_100KM = {
    "lon": 126.978,
    "lat": 37.5665,
    "radius_m": 100_000.0,
    "kinds": ["place"],
    "categories": None,
    "statuses": ["active"],
    "providers": None,
    "limit_plus_one": 51,
    "cursor_distance_m": None,
    "cursor_name": None,
    "cursor_last_updated_at": None,
    "cursor_feature_id": None,
}
_COMMON_SEARCH = {
    "q": "카페",
    "bbox_enabled": False,
    "min_lon": None,
    "min_lat": None,
    "max_lon": None,
    "max_lat": None,
    "kinds": None,
    "categories": None,
    "cursor_score": None,
    "cursor_feature_id": None,
    "limit_plus_one": 51,
}
_BATCH_200 = {"feature_ids": [f"perf:f:{i:06d}" for i in range(1, 201)]}

_VIEWPORTS: list[dict[str, Any]] = [
    {"name": "서울 밀집 in-bounds", "sql": _FEATURES_IN_BBOX_SQL, "params": _SEOUL_DENSE_BBOX},
    {
        "name": "전국 low-zoom cluster(sido)",
        "sql": _CLUSTER_BBOX_SQL_BY_UNIT["sido"],
        "params": _NATIONWIDE_LOWZOOM_BBOX,
    },
    {"name": "100km nearby", "sql": _NEARBY_COORD_DISTANCE_SQL, "params": _NEARBY_100KM},
    {
        "name": "상용 검색어 search",
        "sql": _FEATURE_SEARCH_BY_SCORE_SQL,
        "params": _COMMON_SEARCH,
        "pre": ["SET LOCAL pg_trgm.similarity_threshold = 0.2"],
    },
    {"name": "200건 batch", "sql": _GET_PUBLIC_FEATURES_BY_IDS_SQL, "params": _BATCH_200},
]


def _shared_read_blocks(plan: dict[str, Any]) -> int:
    total = int(plan.get("Shared Read Blocks", 0) or 0)
    for child in plan.get("Plans", []):
        total += _shared_read_blocks(child)
    return total


async def _explain_analyze(
    session: AsyncSession, sql: str, params: dict[str, Any], pre: list[str]
) -> dict[str, Any]:
    for statement in pre:
        await session.execute(text(statement))
    result = await session.execute(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), params
    )
    explained: dict[str, Any] = result.scalar_one()[0]
    return explained


async def _run(dsn: str, rows: int, iterations: int, skip_seed: bool) -> dict[str, Any]:
    engine = make_async_engine(normalize_async_dsn(dsn))

    @event.listens_for(engine.sync_engine, "connect")
    def _sp(dbapi_conn: Any, _rec: Any) -> None:
        cur = dbapi_conn.cursor()
        try:
            cur.execute("SET search_path = public, x_extension")
        finally:
            cur.close()

    report: dict[str, Any] = {"rows": rows, "iterations": iterations, "viewports": []}
    async with AsyncSession(engine) as session:
        if not skip_seed:
            seed_started = time.perf_counter()
            async with session.begin():
                await seed_hot_query_features(session, n=rows)
            report["seed_seconds"] = round(time.perf_counter() - seed_started, 1)

        for viewport in _VIEWPORTS:
            durations_ms: list[float] = []
            shared_reads: list[int] = []
            response_bytes = 0
            plan_json: dict[str, Any] = {}
            for _ in range(iterations):
                async with session.begin():
                    explained = await _explain_analyze(
                        session,
                        viewport["sql"],
                        viewport["params"],
                        viewport.get("pre", []),
                    )
                plan = explained["Plan"]
                durations_ms.append(float(explained.get("Execution Time", 0.0)))
                shared_reads.append(_shared_read_blocks(plan))
                plan_json = plan
            # response bytes: 실제 행 직렬화 크기 근사(JSON row_to_json 합).
            async with session.begin():
                for statement in viewport.get("pre", []):
                    await session.execute(text(statement))
                size_row = (
                    await session.execute(
                        text(
                            "SELECT coalesce(sum(octet_length("
                            "coalesce(row_to_json(t)::text, ''))), 0) "
                            "FROM (" + viewport["sql"] + ") AS t"
                        ),
                        viewport["params"],
                    )
                ).scalar_one()
                response_bytes = int(size_row or 0)

            ordered = sorted(durations_ms)
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            report["viewports"].append(
                {
                    "name": viewport["name"],
                    "p50_ms": round(statistics.median(durations_ms), 2),
                    "p95_ms": round(p95, 2),
                    "max_ms": round(max(durations_ms), 2),
                    "shared_read_blocks_p95": sorted(shared_reads)[
                        min(len(shared_reads) - 1, int(len(shared_reads) * 0.95))
                    ],
                    "response_bytes": response_bytes,
                    "top_node": plan_json.get("Node Type"),
                }
            )
    await engine.dispose()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("KOR_TRAVEL_MAP_PG_DSN"),
        help="asyncpg DSN. 기본은 KOR_TRAVEL_MAP_PG_DSN env.",
    )
    args = parser.parse_args(argv)
    if not args.dsn:
        parser.error("--dsn 또는 KOR_TRAVEL_MAP_PG_DSN이 필요합니다.")
    report = asyncio.run(
        _run(args.dsn, args.rows, args.iterations, args.skip_seed)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
