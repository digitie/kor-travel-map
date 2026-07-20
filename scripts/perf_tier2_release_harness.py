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

``--skip-seed``로 이미 적재된 DB를 그대로 잰다. 이 모드의 200건 batch는
public projection의 실제 non-notice ID를 정렬해 사용한다. notice 전용 추가 감산
predicate와 batch 후보 의미가 어긋나지 않도록 notice는 선택하지 않는다. fixture
생성은 수 분~수십 분이 걸릴 수 있다. 각 viewport가 최소 반환 행 계약을 만족할
때만 JSON을 stdout에 출력하여 release 리포트에 첨부한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

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

_BATCH_CARDINALITY = 200
_PUBLIC_BATCH_CANDIDATE_PREDICATE_SQL = "kind <> 'notice'"
_SELECT_PUBLIC_BATCH_IDS_SQL = f"""
SELECT feature_id
FROM feature.public_features
WHERE {_PUBLIC_BATCH_CANDIDATE_PREDICATE_SQL}
ORDER BY feature_id
LIMIT :limit
"""
_COUNT_PUBLIC_FEATURES_SQL = "SELECT count(*) FROM feature.public_features"
_COUNT_PUBLIC_BATCH_CANDIDATES_SQL = f"""
SELECT count(*)
FROM feature.public_features
WHERE {_PUBLIC_BATCH_CANDIDATE_PREDICATE_SQL}
"""

_PercentileValue = TypeVar("_PercentileValue", int, float)


class BenchmarkCardinalityError(RuntimeError):
    """성공 release evidence를 만들 수 없는 입력 cardinality 오류."""


def _nearest_rank_percentile(
    values: Sequence[_PercentileValue], percentile: float
) -> _PercentileValue:
    """정렬한 표본의 nearest-rank percentile 값을 보간 없이 반환한다."""

    if not values:
        raise ValueError("percentile 표본은 비어 있을 수 없습니다.")
    if not 0.0 < percentile <= 1.0:
        raise ValueError("percentile은 0보다 크고 1 이하여야 합니다.")
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


@dataclass(frozen=True, slots=True)
class Viewport:
    """실측 query와 성공 report에 필요한 최소 반환 행 계약."""

    name: str
    sql: str
    params: Mapping[str, Any]
    min_returned_rows: int
    terminal_limit_parameter: str | None = None
    pre: tuple[str, ...] = ()

    @property
    def matched_rows_sql(self) -> str:
        """cursor/filter 적용 후 terminal LIMIT 전 전체 cardinality SQL."""

        return _count_matching_rows_sql(self.sql, self.terminal_limit_parameter)


def _count_matching_rows_sql(sql: str, terminal_limit_parameter: str | None) -> str:
    """production SQL의 terminal LIMIT만 제거해 전체 match count를 만든다.

    LATERAL/CTE 내부의 ``LIMIT 1``은 query 의미의 일부이므로 보존한다. 호출자가
    지정한 terminal placeholder가 실제 마지막 clause가 아니면 조용히 잘못된
    evidence를 만들지 않고 즉시 실패한다.
    """

    matched_sql = sql.rstrip()
    if terminal_limit_parameter is not None:
        terminal_limit = f"\nLIMIT :{terminal_limit_parameter}"
        if not matched_sql.endswith(terminal_limit):
            raise ValueError(
                f"query must end with {terminal_limit.strip()} to count pre-limit rows"
            )
        matched_sql = matched_sql[: -len(terminal_limit)]
    return f"SELECT count(*) AS matched_rows FROM ({matched_sql}) AS matched"


def _build_viewports(batch_feature_ids: list[str]) -> tuple[Viewport, ...]:
    """DB에서 실제 선택한 public ID로 batch viewport를 구성한다."""

    if len(batch_feature_ids) != _BATCH_CARDINALITY:
        raise BenchmarkCardinalityError(
            f"200건 batch에 non-notice public feature {_BATCH_CARDINALITY}건이 필요하지만 "
            f"{len(batch_feature_ids)}건만 선택됨"
        )
    return (
        Viewport(
            name="서울 밀집 in-bounds",
            sql=_FEATURES_IN_BBOX_SQL,
            params=_SEOUL_DENSE_BBOX,
            min_returned_rows=1,
            terminal_limit_parameter="limit",
        ),
        Viewport(
            name="전국 low-zoom cluster(sido)",
            sql=_CLUSTER_BBOX_SQL_BY_UNIT["sido"],
            params=_NATIONWIDE_LOWZOOM_BBOX,
            min_returned_rows=1,
            terminal_limit_parameter="limit",
        ),
        Viewport(
            name="100km nearby",
            sql=_NEARBY_COORD_DISTANCE_SQL,
            params=_NEARBY_100KM,
            min_returned_rows=1,
            terminal_limit_parameter="limit_plus_one",
        ),
        Viewport(
            name="상용 검색어 search",
            sql=_FEATURE_SEARCH_BY_SCORE_SQL,
            params=_COMMON_SEARCH,
            min_returned_rows=1,
            terminal_limit_parameter="limit_plus_one",
            pre=("SET LOCAL pg_trgm.similarity_threshold = 0.2",),
        ),
        Viewport(
            name="200건 batch",
            sql=_GET_PUBLIC_FEATURES_BY_IDS_SQL,
            params={"feature_ids": batch_feature_ids},
            min_returned_rows=_BATCH_CARDINALITY,
        ),
    )


def _shared_read_blocks(plan: Mapping[str, Any]) -> int:
    """query 전체의 shared read를 최상위 Plan 누적값으로 반환한다.

    PostgreSQL의 상위 node buffer 수치는 child 사용량을 이미 포함한다.
    plan tree를 재귀 합산하면 plan shape에 따라 같은 I/O가 중복 계산된다.
    """

    return int(plan.get("Shared Read Blocks", 0) or 0)


def _plan_returned_rows(plan: Mapping[str, Any]) -> int:
    """최상위 Plan이 반환한 전체 행 수를 계산한다."""

    actual_rows = float(plan.get("Actual Rows", 0.0) or 0.0)
    actual_loops = float(plan.get("Actual Loops", 1.0) or 0.0)
    return int(round(actual_rows * actual_loops))


async def _select_public_batch_feature_ids(session: AsyncSession) -> list[str]:
    """notice visibility drift가 없는 실제 public ID 200개를 결정적으로 선택한다."""

    result = await session.execute(
        text(_SELECT_PUBLIC_BATCH_IDS_SQL), {"limit": _BATCH_CARDINALITY}
    )
    feature_ids = [str(row[0]) for row in result.all()]
    if len(feature_ids) != _BATCH_CARDINALITY:
        raise BenchmarkCardinalityError(
            f"--skip-seed 포함 모든 모드에 non-notice public feature "
            f"{_BATCH_CARDINALITY}건이 필요하지만 {len(feature_ids)}건만 존재함"
        )
    return feature_ids


async def _measure_cardinality_and_response(
    session: AsyncSession, viewport: Viewport
) -> tuple[int, int, int]:
    """LIMIT 전 match와 실제 반환 행·JSON 바이트를 분리해 재고 검증한다."""

    for statement in viewport.pre:
        await session.execute(text(statement))
    matched_rows = int(
        (
            await session.execute(
                text(viewport.matched_rows_sql), dict(viewport.params)
            )
        ).scalar_one()
    )
    row = (
        await session.execute(
            text(
                "SELECT count(*) AS returned_rows, "
                "coalesce(sum(octet_length(coalesce(row_to_json(t)::text, ''))), 0) "
                "AS response_bytes FROM (" + viewport.sql + ") AS t"
            ),
            dict(viewport.params),
        )
    ).one()
    returned_rows = int(row.returned_rows)
    response_bytes = int(row.response_bytes or 0)
    if returned_rows > matched_rows:
        raise BenchmarkCardinalityError(
            f"{viewport.name}: returned_rows={returned_rows}가 "
            f"matched_rows={matched_rows}보다 큼"
        )
    if returned_rows < viewport.min_returned_rows:
        raise BenchmarkCardinalityError(
            f"{viewport.name}: 최소 {viewport.min_returned_rows}행이 필요하지만 "
            f"{returned_rows}행만 반환됨"
        )
    return matched_rows, returned_rows, response_bytes


async def _explain_analyze(
    session: AsyncSession,
    sql: str,
    params: Mapping[str, Any],
    pre: tuple[str, ...],
) -> dict[str, Any]:
    for statement in pre:
        await session.execute(text(statement))
    result = await session.execute(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), dict(params)
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

    try:
        report: dict[str, Any] = {
            "mode": "existing" if skip_seed else "seeded",
            "requested_seed_rows": None if skip_seed else rows,
            "iterations": iterations,
            "viewports": [],
        }
        async with AsyncSession(engine) as session:
            if not skip_seed:
                seed_started = time.perf_counter()
                async with session.begin():
                    await seed_hot_query_features(
                        session,
                        n=rows,
                        feature_id_prefix="tier2:f:",
                    )
                report["seed_seconds"] = round(time.perf_counter() - seed_started, 1)

            async with session.begin():
                public_feature_rows = int(
                    (
                        await session.execute(text(_COUNT_PUBLIC_FEATURES_SQL))
                    ).scalar_one()
                )
                batch_candidate_rows = int(
                    (
                        await session.execute(
                            text(_COUNT_PUBLIC_BATCH_CANDIDATES_SQL)
                        )
                    ).scalar_one()
                )
                batch_feature_ids = await _select_public_batch_feature_ids(session)
            report["public_feature_rows"] = public_feature_rows
            report["batch_candidate_rows"] = batch_candidate_rows
            viewports = _build_viewports(batch_feature_ids)

            for viewport in viewports:
                durations_ms: list[float] = []
                shared_reads: list[int] = []
                plan_returned_rows: list[int] = []
                plan_json: dict[str, Any] = {}
                async with session.begin():
                    matched_rows, returned_rows, response_bytes = (
                        await _measure_cardinality_and_response(session, viewport)
                    )

                for _ in range(iterations):
                    async with session.begin():
                        explained = await _explain_analyze(
                            session,
                            viewport.sql,
                            viewport.params,
                            viewport.pre,
                        )
                    plan = explained["Plan"]
                    durations_ms.append(float(explained.get("Execution Time", 0.0)))
                    shared_reads.append(_shared_read_blocks(plan))
                    plan_returned_rows.append(_plan_returned_rows(plan))
                    plan_json = plan

                if any(count != returned_rows for count in plan_returned_rows):
                    raise BenchmarkCardinalityError(
                        f"{viewport.name}: EXPLAIN returned_rows={plan_returned_rows}와 "
                        f"response returned_rows={returned_rows}가 다름"
                    )

                report["viewports"].append(
                    {
                        "name": viewport.name,
                        "matched_rows": matched_rows,
                        "returned_rows": returned_rows,
                        "minimum_returned_rows": viewport.min_returned_rows,
                        "p50_ms": round(_nearest_rank_percentile(durations_ms, 0.5), 2),
                        "p95_ms": round(_nearest_rank_percentile(durations_ms, 0.95), 2),
                        "max_ms": round(max(durations_ms), 2),
                        "shared_read_blocks_p95": _nearest_rank_percentile(
                            shared_reads, 0.95
                        ),
                        "response_bytes": response_bytes,
                        "top_node": plan_json.get("Node Type"),
                    }
                )
        return report
    finally:
        await engine.dispose()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다.")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=_positive_int, default=1_000_000)
    parser.add_argument("--iterations", type=_positive_int, default=30)
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("KOR_TRAVEL_MAP_PG_DSN"),
        help="asyncpg DSN. 기본은 KOR_TRAVEL_MAP_PG_DSN env.",
    )
    args = parser.parse_args(argv)
    if not args.dsn:
        parser.error("--dsn 또는 KOR_TRAVEL_MAP_PG_DSN이 필요합니다.")
    try:
        report = asyncio.run(
            _run(args.dsn, args.rows, args.iterations, args.skip_seed)
        )
    except BenchmarkCardinalityError as exc:
        print(f"benchmark cardinality 검증 실패: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
