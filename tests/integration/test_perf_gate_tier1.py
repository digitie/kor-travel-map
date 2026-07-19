"""Tier-1 성능 gate (매 PR, CI integration job) — performance.md §8.3, ADR-075 D-12-4.

세 검사를 CI에서 상시 수행한다:

1. **planner-default EXPLAIN smoke**: hot public query(bbox/in-bounds·nearby·search·
   detail·batch·category counts·cluster rollup)를 ``enable_seqscan`` 조작 없이 EXPLAIN해
   ``feature.features`` base-table Seq Scan이 없고 기대 index를 쓰는지 검사한다.
   ``enable_seqscan=off`` crutch는 쓰지 않는다(그건 회귀 감시 전용).
2. **query 수 ≠ batch item 수 가드**: public batch read를 item 50개·100개로 호출해
   발생 SQL statement 수가 item 수에 비례하지 않고 일정(1건)함을 검사한다(N+1 회귀 차단).
3. **response-shape 회귀**: hot query 결과 컬럼 집합을 frozen snapshot과 비교해
   우발적 필드 추가/삭제를 잡는다.

hot query를 늘리려면 ``perf_gate.HOT_QUERIES``에 한 줄 추가한다(§8.3 절차).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kortravelmap.infra import feature_repo
from tests.integration.perf_gate import (
    HOT_QUERIES,
    assert_no_seq_scan_on,
    assert_uses_index,
    count_sql_statements,
    explain_plan,
    query_result_columns,
    seed_hot_query_features,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.perf_gate]


@pytest.mark.parametrize("hot", HOT_QUERIES, ids=lambda h: h.name)
async def test_tier1_hot_query_planner_default_no_seq_scan(
    migrated_session: AsyncSession,
    hot: object,
) -> None:
    """각 hot query가 planner 기본 설정에서 features Seq Scan 없이 index를 탄다."""

    await seed_hot_query_features(migrated_session)
    plan = await explain_plan(
        migrated_session,
        hot.sql,  # type: ignore[attr-defined]
        hot.params,  # type: ignore[attr-defined]
        planner_default=True,
        pre_statements=hot.pre_statements,  # type: ignore[attr-defined]
    )
    assert_no_seq_scan_on(plan, *hot.no_seq_scan_on)  # type: ignore[attr-defined]
    assert_uses_index(plan, *hot.expected_indexes)  # type: ignore[attr-defined]


async def test_tier1_public_batch_query_count_is_constant(
    migrated_engine: AsyncEngine,
    migrated_session: AsyncSession,
) -> None:
    """public batch read의 SQL statement 수가 item 수에 비례하지 않는다(N+1 가드)."""

    await seed_hot_query_features(migrated_session)
    ids_50 = [f"perf:f:{i:06d}" for i in range(1, 51)]
    ids_100 = [f"perf:f:{i:06d}" for i in range(1, 101)]

    with count_sql_statements(migrated_engine) as stmts_50:
        rows_50 = await feature_repo.get_public_feature_rows_by_ids(
            migrated_session, ids_50
        )
    with count_sql_statements(migrated_engine) as stmts_100:
        rows_100 = await feature_repo.get_public_feature_rows_by_ids(
            migrated_session, ids_100
        )

    # item 2배에도 query 수가 그대로여야 한다(단일 ANY(ids) read).
    assert len(stmts_50) == 1, stmts_50
    assert len(stmts_100) == len(stmts_50), (len(stmts_50), len(stmts_100))
    # 실제로 더 많은 row를 읽었는지도 확인(seed의 active 비율 반영).
    assert len(rows_100) > len(rows_50) > 0


# hot query 결과 컬럼 frozen snapshot (response-shape 회귀). 값 변경은 의도적
# 계약 변경일 때만 이 dict를 갱신한다.
_FROZEN_SHAPES: dict[str, tuple[str, ...]] = {
    "public detail (PK)": (
        "address",
        "area_square_meters",
        "category",
        "coord_5179_srid",
        "coord_precision_digits",
        "created_at",
        "deleted_at",
        "detail",
        "feature_id",
        "kind",
        "lat",
        "legal_dong_code",
        "lon",
        "marker_color",
        "marker_icon",
        "name",
        "parent_feature_id",
        "raw_refs",
        "row_revision",
        "sibling_group_id",
        "sido_code",
        "sigungu_code",
        "status",
        "updated_at",
        "urls",
    ),
    "category counts (GROUP BY)": ("category", "n"),
}


@pytest.mark.parametrize("query_name", sorted(_FROZEN_SHAPES))
async def test_tier1_hot_response_shape_is_frozen(
    migrated_session: AsyncSession,
    query_name: str,
) -> None:
    """hot query 결과 컬럼이 frozen snapshot과 일치한다(우발적 필드 변경 차단)."""

    await seed_hot_query_features(migrated_session)
    hot = next(h for h in HOT_QUERIES if h.name == query_name)
    columns = await query_result_columns(migrated_session, hot.sql, hot.params)
    assert columns == _FROZEN_SHAPES[query_name], (
        f"{query_name} response shape drifted: {columns} != "
        f"{_FROZEN_SHAPES[query_name]}. 의도적 계약 변경이면 _FROZEN_SHAPES를 갱신."
    )
