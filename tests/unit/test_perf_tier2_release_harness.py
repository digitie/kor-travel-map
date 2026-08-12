"""Tier-2 release benchmark를 plan shape·고정 ID와 분리하는 단위 검증."""

from __future__ import annotations

import pytest

import scripts.perf_tier2_release_harness as harness
from scripts.perf_tier2_release_harness import (
    BenchmarkCardinalityError,
    _build_viewports,
    _count_matching_rows_sql,
    _nearest_rank_percentile,
    _plan_returned_rows,
    _shared_read_blocks,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("sample_size", "expected_index", "expected_value"),
    [
        (1, 0, 1),
        (20, 18, 19),
        (30, 28, 29),
        (100, 94, 95),
    ],
)
def test_nearest_rank_p95_selects_expected_sorted_index_and_value(
    sample_size: int,
    expected_index: int,
    expected_value: int,
) -> None:
    values = list(range(sample_size, 0, -1))
    ordered = sorted(values)

    assert ordered[expected_index] == expected_value
    assert _nearest_rank_percentile(values, 0.95) == expected_value


@pytest.mark.parametrize(
    ("values", "percentile", "message"),
    [
        ([], 0.95, "표본은 비어"),
        ([1], 0.0, "0보다 크고 1 이하"),
        ([1], 1.01, "0보다 크고 1 이하"),
    ],
)
def test_nearest_rank_percentile_rejects_invalid_input(
    values: list[int], percentile: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _nearest_rank_percentile(values, percentile)


def test_shared_read_blocks_uses_root_cumulative_total_with_single_child() -> None:
    plan = {
        "Node Type": "Limit",
        "Shared Read Blocks": 10,
        "Plans": [
            {
                "Node Type": "Index Scan",
                "Shared Read Blocks": 10,
            }
        ],
    }

    assert _shared_read_blocks(plan) == 10


def test_shared_read_blocks_is_stable_for_append_and_parallel_plan_shape() -> None:
    plan = {
        "Node Type": "Gather",
        "Shared Read Blocks": 73,
        "Plans": [
            {
                "Node Type": "Append",
                "Shared Read Blocks": 73,
                "Plans": [
                    {"Node Type": "Parallel Seq Scan", "Shared Read Blocks": 31},
                    {"Node Type": "Parallel Bitmap Heap Scan", "Shared Read Blocks": 42},
                ],
            }
        ],
    }

    assert _shared_read_blocks(plan) == 73


def test_plan_returned_rows_accounts_for_root_loops() -> None:
    assert _plan_returned_rows({"Actual Rows": 25, "Actual Loops": 4}) == 100


def test_count_matching_rows_sql_removes_only_terminal_limit() -> None:
    sql = """
SELECT f.feature_id
FROM feature.public_features AS f
LEFT JOIN LATERAL (SELECT 1 LIMIT 1) AS child ON true
ORDER BY f.feature_id
LIMIT :limit
"""

    count_sql = _count_matching_rows_sql(sql, "limit")

    assert "SELECT 1 LIMIT 1" in count_sql
    assert "LIMIT :limit" not in count_sql
    assert count_sql.startswith("SELECT count(*) AS matched_rows FROM (")


def test_count_matching_rows_sql_removes_page_limit_inside_candidate_cte() -> None:
    """공개 bbox query처럼 page limit가 CTE 안에 있어도 pre-page 수를 센다."""

    sql = """
WITH candidates AS (
    SELECT f.feature_id
    FROM feature.public_features AS f
    WHERE EXISTS (SELECT 1 LIMIT 1)
    ORDER BY f.feature_id
    LIMIT :limit
)
SELECT feature_id
FROM candidates
ORDER BY feature_id
"""

    count_sql = _count_matching_rows_sql(sql, "limit")

    assert "SELECT 1 LIMIT 1" in count_sql
    assert "LIMIT :limit" not in count_sql


def test_count_matching_rows_sql_rejects_drifted_terminal_limit() -> None:
    with pytest.raises(ValueError, match="exactly one LIMIT :limit"):
        _count_matching_rows_sql("SELECT 1 LIMIT :other_limit", "limit")


def test_batch_viewport_uses_selected_database_ids() -> None:
    selected = [f"existing:f:{index:06d}" for index in range(200)]

    batch = _build_viewports(selected)[-1]

    assert batch.params == {"feature_ids": selected}
    assert batch.min_returned_rows == 200
    assert "LIMIT" not in batch.matched_rows_sql
    assert not any(feature_id.startswith("perf:f:") for feature_id in selected)


def test_batch_viewport_rejects_less_than_200_public_ids() -> None:
    with pytest.raises(BenchmarkCardinalityError, match="199건만 선택됨"):
        _build_viewports([f"existing:f:{index:06d}" for index in range(199)])


def test_main_does_not_emit_success_report_on_cardinality_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def _fail_run(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise BenchmarkCardinalityError("public feature 199건만 존재함")

    monkeypatch.setattr(harness, "_run", _fail_run)

    assert harness.main(["--dsn", "postgresql+asyncpg://unused", "--skip-seed"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cardinality 검증 실패" in captured.err
