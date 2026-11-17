"""Tier-2 release benchmark를 plan shape·고정 ID와 분리하는 단위 검증."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

import scripts.perf_tier2_release_harness as harness
from kortravelmap.core.search_region import RegionSearch
from kortravelmap.infra.feature_repo import (
    _FEATURE_SEARCH_BY_SCORE_SQL,
    _search_score_sql,
    _SearchRegionArms,
)
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
    selected = [str(uuid.UUID(int=index + 1)) for index in range(200)]

    batch = next(v for v in _build_viewports(selected) if v.name == "200건 batch")

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


def test_search_viewport_params_cover_every_search_bind_parameter() -> None:
    """tier-2 search viewport의 파라미터가 검색 SQL의 bind를 전부 채운다(436 회귀 방지).

    검색 SQL에 bind가 늘면( ``q_compact``·``alias_name``·``alias_compact``·``cursor_rank``)
    이 dict와
    ``tests/integration/perf_gate.py``·``test_t212d_perf_explain.py``의 사본이 함께 따라가야
    한다. 빠지면 tier-2 하네스가 ``A value is required for bind parameter``로 죽는다.
    """
    from sqlalchemy import text

    from kortravelmap.infra.feature_repo import _FEATURE_SEARCH_BY_SCORE_SQL

    required = set(text(_FEATURE_SEARCH_BY_SCORE_SQL)._bindparams)
    assert required <= set(harness._COMMON_SEARCH)


# ── 읽기 기준선(T-READ-01) ────────────────────────────────────────────────────

_DETAIL_AND_BATCH_IDS = [str(uuid.UUID(int=index + 1)) for index in range(200)]


def _region(category_codes: tuple[str, ...] = ()) -> RegionSearch:
    return RegionSearch(
        region_label="부산",
        sigungu_codes=("26110", "26140"),
        remainder="맛집 국밥",
        category_codes=category_codes,
    )


def _all_region_variants() -> list[tuple[RegionSearch | None, _SearchRegionArms | None]]:
    variants: list[tuple[RegionSearch | None, _SearchRegionArms | None]] = [(None, None)]
    for name_mode in ("ilike", "strpos", None):
        for categories in (False, True):
            for token_mode in ("anchor", "scan", None):
                arms = _SearchRegionArms(
                    name_mode=name_mode,  # type: ignore[arg-type]
                    categories=categories,
                    token_mode=token_mode,  # type: ignore[arg-type]
                )
                variants.append((_region(("05010000",) if categories else ()), arms))
    return variants


def test_harness_connection_matches_api_jit_off_and_statement_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert harness.HARNESS_SERVER_SETTINGS == {"jit": "off", "statement_timeout": "30000"}
    captured: dict[str, object] = {}

    class _Stop(Exception):
        pass

    def fake_engine(dsn: object, **kwargs: object) -> object:
        captured.update(kwargs)
        raise _Stop

    monkeypatch.setattr(harness, "make_async_engine", fake_engine)
    with pytest.raises(_Stop):
        asyncio.run(harness._run("postgresql+asyncpg://unused/db", 1, 1, True))
    assert captured["server_settings"] == harness.HARNESS_SERVER_SETTINGS


def test_read_baseline_has_thirteen_named_viewports() -> None:
    region_viewports = [
        harness.Viewport(
            name=case.name,
            sql=_FEATURE_SEARCH_BY_SCORE_SQL,
            params=harness._search_viewport_params(
                case.q, alias_name=None, region=None, arms=None
            ),
            min_returned_rows=0,
            terminal_limit_parameter="limit_plus_one",
        )
        for case in harness.REGION_SEARCH_CASES
    ]

    viewports = _build_viewports(_DETAIL_AND_BATCH_IDS, region_viewports)

    names = [viewport.name for viewport in viewports]
    assert len(names) == 13
    assert len(set(names)) == 13
    assert "서울시청 읍면동 집계(zoom 12, PinVi 기본 화면)" in names
    assert "서울시청 읍면동 집계(zoom 13)" in names
    assert "수도권 시군구 집계(zoom 10)" in names
    assert "서울 개별 행 500건(zoom 14)" in names
    assert "상세 1건" in names
    assert [case.q for case in harness.REGION_SEARCH_CASES] == ["부산 맛집", "서울 맛집"]
    for viewport in viewports:
        required = set(text(viewport.sql)._bindparams)
        assert required <= set(viewport.params), viewport.name
        # 모든 viewport가 LIMIT 전 개수를 셀 수 있어야 한다.
        assert viewport.matched_rows_sql.startswith("SELECT count(*)")
    z12 = next(v for v in viewports if v.name.startswith("서울시청 읍면동 집계(zoom 12"))
    assert z12.params["kinds"] == ["place", "event", "notice", "price"]
    assert z12.params["limit"] == 500
    assert (z12.params["min_lon"], z12.params["max_lat"]) == (126.758, 37.677)


@pytest.mark.parametrize(("region", "arms"), _all_region_variants())
def test_region_search_params_and_constant_variant_cover_every_bind(
    region: RegionSearch | None, arms: _SearchRegionArms | None
) -> None:
    score_sql, _count_sql = _search_score_sql(region, arms)
    params = harness._search_viewport_params(
        "부산 맛집 국밥", alias_name="별칭", region=region, arms=arms
    )
    assert set(text(score_sql)._bindparams) <= set(params)

    variant = harness._constant_normalization_variant(score_sql)

    assert set(text(variant)._bindparams) <= set(params)
    compacted = variant[variant.index("\ncompacted AS (") : variant.index("\nranked AS (")]
    assert "normalize(" not in compacted
    for alias in (
        "compact_name",
        "compact_raw_name",
        "compact_tail",
        "compact_base_name",
        "compact_paren_base_name",
        "compact_bracket_name",
        "category_search_group",
        "search_group",
    ):
        assert f"AS {alias}" in compacted, alias
    if region is not None:
        assert "AS region_hit" in compacted
    # 원래 두 CTE가 내던 열은 변형도 모두 낸다(뒤 단계가 읽는다).
    original = score_sql[score_sql.index("\ncompacted AS (") : score_sql.index("\nranked AS (")]
    column_alias = re.compile(r"AS (\w+)\s*(?:,|\n\s*FROM)")
    assert set(column_alias.findall(original)) <= set(column_alias.findall(compacted))
    # 나머지(순위·접기·page)는 글자까지 같다.
    ranked = "\nranked AS ("
    assert variant[variant.index(ranked) :] == score_sql[score_sql.index(ranked) :]
    _count_matching_rows_sql(variant, "limit_plus_one")


def test_constant_variant_fails_closed_on_drifted_sql() -> None:
    with pytest.raises(ValueError, match="compacted"):
        harness._constant_normalization_variant("SELECT 1")


def test_subtract_share() -> None:
    assert harness._subtract_share(100.0, 60.0) == 0.4
    assert harness._subtract_share(0.0, 0.0) is None


def test_output_file_has_same_schema_across_runs_and_no_dsn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_run(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "mode": "existing",
            "requested_seed_rows": None,
            "iterations": 1,
            "viewports": [{"name": "v", "p50_ms": 1.0}],
            "region_search": [],
        }

    monkeypatch.setattr(harness, "_run", fake_run)
    dsn = "postgresql+asyncpg://user:hunter2@db.invalid/map"
    keys = []
    for index in range(2):
        output = tmp_path / f"run{index}.safe.json"
        assert harness.main(["--dsn", dsn, "--skip-seed", "--output", str(output)]) == 0
        written = output.read_text(encoding="utf-8")
        assert "hunter2" not in written
        assert "db.invalid" not in written
        report = json.loads(written)
        assert report["server_settings"] == harness.HARNESS_SERVER_SETTINGS
        keys.append(sorted(report))
    assert keys[0] == keys[1]
    assert "hunter2" not in capsys.readouterr().out
