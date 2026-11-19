#!/usr/bin/env python3
"""Tier-2 release/cutover 성능 harness — performance.md §8.3, ADR-075 D-12-4.

**PR gate가 아니다.** release/cutover 절차에서만 수동 실행한다(§8.3 tier-2). 100만+
실분포 fixture에서 대표 viewport를 ``EXPLAIN (ANALYZE, BUFFERS)``로 재고, n150 기준
p95 실행시간·shared read blocks·응답 bytes budget을 기록한다. CI에서 절대 돌리지
않는다(대용량 fixture는 CI 시간/자원을 초과).

대표 viewport (§8.3):
  - 서울 밀집 in-bounds
  - 전국 low-zoom cluster rollup (place/event = point-only, 전 kind = geometry arm 포함)
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
때만 JSON을 stdout에 출력하여 release 리포트에 첨부한다. ``--output <파일>``이면 같은
JSON을 그 파일에도 쓴다(``.safe.json`` — DSN·key를 담지 않는다).

읽기 기준선(읽기 성능 계획 T-READ-01)
-------------------------------------

- 연결은 운영 API처럼 ``jit=off``이고 문장 상한 30초다(``HARNESS_SERVER_SETTINGS``). JIT를
  켠 수치는 운영이 보지 않는 수치다(2026-11-12 "부산 맛집" 7.6초 중 7.2초가 JIT).
- viewport 13개 — 위 6개 + 지역 검색 2개("부산 맛집" 좁은 지역, "서울 맛집" 넓은 지역)·시군구
  집계(zoom 10)·서울시청 읍면동 집계(zoom 12·13, PinVi 기본 화면)·개별 행 500건(zoom 14)·상세 1건.
- 지역 검색 SQL은 고정 문자열이 아니다. 요청 때와 같이 ``_resolve_search_region`` →
  ``_search_region_arms`` → ``_search_region_params`` → ``_search_score_sql``로 만든다. 전처리
  질의 셋(별칭·지역 표본·지역 행 수)은 따로 잰다.
- 이름 정규화 비중은 EXPLAIN 노드로 잴 수 없다(``compacted``·``hits``는 inline되는 CTE).
  **빼고 잰다** — 본 질의(i)와, 같은 질의에서 두 CTE의 식을 상수·원래 열로 바꾼 변형(ii)의
  p50으로 (i − ii) / i. 변형은 이 harness 안에만 있고 운영 SQL은 바꾸지 않는다.

운영 DB에서 돌리는 것은 소유자가 승인한 조용한 창에서만 한다(계획 §8.1).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeVar

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from kortravelmap.core.search_region import RegionSearch  # noqa: E402
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn  # noqa: E402
from kortravelmap.infra.feature_repo import (  # noqa: E402
    _CLUSTER_BBOX_POINT_ONLY_SQL_BY_UNIT,
    _CLUSTER_BBOX_SQL_BY_UNIT,
    _CLUSTER_HASH_AGGREGATE_ON_SQL,
    _FEATURE_SEARCH_BY_SCORE_SQL,
    _FEATURES_IN_BBOX_SQL,
    _GET_PUBLIC_FEATURE_SQL,
    _GET_PUBLIC_FEATURES_BY_IDS_SQL,
    _NEARBY_COORD_DISTANCE_SQL,
    _SEARCH_ALIAS_LOOKUP_SQL,
    _SEARCH_REGION_ENTRIES_SQL,
    _SEARCH_REGION_ROW_COUNT_SQL,
    _resolve_search_region,
    _search_region_arms,
    _search_region_params,
    _search_score_sql,
    _SearchRegionArms,
    search_alias_key,
    search_bracket_like_pattern,
)
from tests.integration.perf_gate import seed_hot_query_features  # noqa: E402

#: 운영 API engine과 같은 연결 설정(``api/db.py``의 ``jit=off``) + 문장 상한 30초.
HARNESS_SERVER_SETTINGS: Final[dict[str, str]] = {
    "jit": "off",
    "statement_timeout": "30000",
}

# ── 대표 viewport 정의 (§8.3) ────────────────────────────────────────────────

_SEOUL_DENSE_BBOX = {
    "min_lon": 126.96,
    "min_lat": 37.50,
    "max_lon": 127.06,
    "max_lat": 37.58,
    "kinds": ["place", "event"],
    "categories": None,
    "providers": None,
    "attributes": None,
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
    "attributes": None,
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
    "attributes": None,
    "limit_plus_one": 51,
    "cursor_distance_m": None,
    "cursor_name": None,
    "cursor_last_updated_at": None,
    "cursor_feature_id": None,
}
_COMMON_SEARCH = {
    "q": "카페",
    # 436: 순위 비교 키와 별칭 이름. 상용 검색어라 별칭은 없다.
    "q_compact": "카페",
    "alias_name": None,
    "alias_compact": None,
    # 끝 괄호 이름 팔: 공백 뺀 검색어가 3글자 미만이면 없다(``search_bracket_like_pattern``).
    "bracket_like": None,
    "bbox_enabled": False,
    "min_lon": None,
    "min_lat": None,
    "max_lon": None,
    "max_lat": None,
    "kinds": None,
    "categories": None,
    "attributes": None,
    "cursor_rank": None,
    "cursor_score": None,
    "cursor_feature_id": None,
    "limit_plus_one": 51,
}

# ── 읽기 기준선 viewport (T-READ-01) ─────────────────────────────────────────

#: PinVi 지도 기본 kind(``place``·``event``·``notice``·``price``)와 PinVi in-bounds 기본 500건.
_PINVI_DEFAULT_KINDS: Final[list[str]] = ["place", "event", "notice", "price"]
_PINVI_MAX_ITEMS: Final[int] = 500

#: 서울시청 중심 zoom 12 화면(PinVi 기본 화면 — 계획 F-04). zoom 13·14는 같은 중심의 절반·4분의 1.
_SEOUL_CITY_HALL_Z12: Final[tuple[float, float, float, float]] = (
    126.758,
    37.456,
    127.198,
    37.677,
)


def _zoomed_bbox(
    bbox: tuple[float, float, float, float], factor: float
) -> tuple[float, float, float, float]:
    """같은 중심에서 가로·세로를 ``factor``배로 줄인 bbox(소수 5자리)."""

    min_lon, min_lat, max_lon, max_lat = bbox
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2
    half_lon = (max_lon - min_lon) * factor / 2
    half_lat = (max_lat - min_lat) * factor / 2
    return (
        round(center_lon - half_lon, 5),
        round(center_lat - half_lat, 5),
        round(center_lon + half_lon, 5),
        round(center_lat + half_lat, 5),
    )


_SEOUL_CITY_HALL_Z13 = _zoomed_bbox(_SEOUL_CITY_HALL_Z12, 0.5)
_SEOUL_CITY_HALL_Z14 = _zoomed_bbox(_SEOUL_CITY_HALL_Z12, 0.25)
#: 수도권 zoom 10 화면(시군구 집계).
_CAPITAL_AREA_Z10: Final[tuple[float, float, float, float]] = (126.6, 37.3, 127.4, 37.8)


def _cluster_params(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    min_lon, min_lat, max_lon, max_lat = bbox
    return {
        "min_lon": min_lon,
        "min_lat": min_lat,
        "max_lon": max_lon,
        "max_lat": max_lat,
        "kinds": list(_PINVI_DEFAULT_KINDS),
        "categories": None,
        "providers": None,
        "attributes": None,
        "limit": _PINVI_MAX_ITEMS,
    }


def _rows_params(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    return {
        **_cluster_params(bbox),
        "cursor_feature_id": None,
        "price_stale_hide_days": 4,
    }


@dataclass(frozen=True, slots=True)
class RegionSearchCase:
    """지역 검색 viewport 하나 — 이름과 검색어."""

    name: str
    q: str


REGION_SEARCH_CASES: Final[tuple[RegionSearchCase, ...]] = (
    RegionSearchCase(name="지역 검색(좁은 지역) 부산 맛집", q="부산 맛집"),
    RegionSearchCase(name="지역 검색(넓은 지역) 서울 맛집", q="서울 맛집"),
)

#: 운영 ``search_features``가 본 질의 앞에 거는 두 줄(같은 transaction).
_SEARCH_PRE: Final[tuple[str, ...]] = (
    "SET LOCAL pg_trgm.similarity_threshold = 0.2",
    "SET LOCAL jit = off",
)


@dataclass(frozen=True, slots=True)
class PreparedRegionSearch:
    """요청 때와 같은 함수로 만든 지역 검색 본 질의·변형·전처리 질의."""

    case: RegionSearchCase
    viewport: Viewport
    constant_variant: Viewport
    preprocessing: tuple[Viewport, ...]
    region: RegionSearch | None
    arms: _SearchRegionArms | None


def _search_viewport_params(
    q: str,
    *,
    alias_name: str | None,
    region: RegionSearch | None,
    arms: _SearchRegionArms | None,
) -> dict[str, Any]:
    """``search_features``가 본 질의에 넘기는 bind 값과 같은 dict(첫 페이지, 50건, bbox 없음)."""

    return {
        **_search_region_params(region, arms),
        "q": q,
        "q_compact": search_alias_key(q),
        "alias_name": alias_name,
        "alias_compact": search_alias_key(alias_name) if alias_name else None,
        "bracket_like": search_bracket_like_pattern(q),
        "bbox_enabled": False,
        "min_lon": None,
        "min_lat": None,
        "max_lon": None,
        "max_lat": None,
        "kinds": None,
        "categories": None,
        "attributes": None,
        "limit_plus_one": 51,
        "cursor_rank": None,
        "cursor_score": None,
        "cursor_feature_id": None,
    }


_COMPACTED_START: Final[str] = "\ncompacted AS ("
_HITS_START: Final[str] = "\nhits AS ("
_RANKED_START: Final[str] = "\nranked AS ("
_SEARCH_GROUP_ALIAS: Final[str] = "AS search_group"
_HITS_FROM: Final[str] = "\n    FROM compacted\n"


def _constant_normalization_variant(sql: str) -> str:
    """``compacted``·``hits``의 정규화 식을 값싼 식으로 바꾼 검색 SQL(harness 전용).

    비교 키(``compact_*``)는 정규화하지 않은 원래 열(괄호 변형은 NULL), 분류 그룹은 상수 0이다.
    원래 열을 쓰는 이유: 키가 모두 같은 상수면 뒤의 접기(``ST_ClusterDBSCAN`` partition)가 후보
    전부를 한 무리로 묶어 비용이 오히려 바뀐다. ``hits``의 지역 일치 열(``region_hit``)은 그대로
    둔다. 모양이 예상과 다르면(운영 SQL이 바뀌면) 추측하지 않고 실패한다.
    """

    for marker in (_COMPACTED_START, _HITS_START, _RANKED_START):
        if sql.count(marker) != 1:
            raise ValueError(f"search SQL must contain exactly one {marker.strip()!r}")
    compacted_at = sql.index(_COMPACTED_START)
    hits_at = sql.index(_HITS_START)
    ranked_at = sql.index(_RANKED_START)
    if not compacted_at < hits_at < ranked_at:
        raise ValueError("search SQL CTE order drifted: compacted → hits → ranked expected")
    hits_block = sql[hits_at:ranked_at]
    if hits_block.count(_SEARCH_GROUP_ALIAS) != 1 or hits_block.count(_HITS_FROM) != 1:
        raise ValueError("hits CTE shape drifted")
    group_end = hits_block.index(_SEARCH_GROUP_ALIAS) + len(_SEARCH_GROUP_ALIAS)
    region_hit_columns = hits_block[group_end : hits_block.index(_HITS_FROM)]
    replacement = f"""
compacted AS (
    SELECT
        filtered.*,
        CAST(display_name AS text) AS compact_name,
        CASE WHEN CAST(:alias_compact AS text) IS NOT NULL
             THEN CAST(name AS text) END AS compact_raw_name,
        CAST(display_name AS text) AS compact_tail,
        CAST(NULL AS text) AS compact_base_name,
        CAST(NULL AS text) AS compact_paren_base_name,
        CAST(NULL AS text) AS compact_bracket_name,
        0 AS category_search_group
    FROM filtered
),
hits AS (
    SELECT
        compacted.*,
        0 AS search_group{region_hit_columns}
    FROM compacted
),"""
    return sql[:compacted_at] + replacement + sql[ranked_at:]


async def _prepare_region_search(
    session: AsyncSession, case: RegionSearchCase
) -> PreparedRegionSearch:
    """운영 ``search_features``의 전처리를 그대로 돌려 본 질의 SQL·인자를 만든다."""

    q_compact = search_alias_key(case.q)
    alias_name = (
        await session.execute(text(_SEARCH_ALIAS_LOOKUP_SQL), {"alias_key": q_compact})
    ).scalar_one_or_none()
    region = await _resolve_search_region(session, case.q)
    arms = await _search_region_arms(session, region) if region is not None else None
    score_sql, _count_sql = _search_score_sql(region, arms)
    params = _search_viewport_params(
        case.q,
        alias_name=str(alias_name) if alias_name is not None else None,
        region=region,
        arms=arms,
    )
    preprocessing: list[Viewport] = [
        Viewport(
            name=f"{case.name} 전처리: 별칭 조회",
            sql=_SEARCH_ALIAS_LOOKUP_SQL,
            params={"alias_key": q_compact},
            min_returned_rows=0,
        ),
        Viewport(
            name=f"{case.name} 전처리: 지역 표본",
            sql=_SEARCH_REGION_ENTRIES_SQL,
            params={},
            min_returned_rows=0,
        ),
    ]
    if region is not None:
        preprocessing.append(
            Viewport(
                name=f"{case.name} 전처리: 지역 행 수",
                sql=_SEARCH_REGION_ROW_COUNT_SQL,
                params={"region_codes": list(region.sigungu_codes)},
                min_returned_rows=1,
            )
        )
    # 데이터가 그 지역을 모르면(fixture) 빈 결과도 기록한다 — 보고서의 returned_rows가 보여 준다.
    viewport = Viewport(
        name=case.name,
        sql=score_sql,
        params=params,
        min_returned_rows=0,
        terminal_limit_parameter="limit_plus_one",
        pre=_SEARCH_PRE,
    )
    constant_variant = Viewport(
        name=f"{case.name} (정규화 식 상수화 변형)",
        sql=_constant_normalization_variant(score_sql),
        params=params,
        min_returned_rows=0,
        terminal_limit_parameter="limit_plus_one",
        pre=_SEARCH_PRE,
    )
    return PreparedRegionSearch(
        case=case,
        viewport=viewport,
        constant_variant=constant_variant,
        preprocessing=tuple(preprocessing),
        region=region,
        arms=arms,
    )


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

    LATERAL/CTE 내부의 ``LIMIT 1``은 query 의미의 일부이므로 보존한다. 공개 bbox
    SQL처럼 page ``LIMIT``가 candidate CTE 안에 있을 수 있으므로, named terminal
    placeholder의 **유일한** 출현만 제거한다. 같은 placeholder가 여러 곳이면 어느
    limit가 page 경계인지 추측하지 않고 fail-close한다.
    """

    matched_sql = sql.rstrip()
    if terminal_limit_parameter is not None:
        terminal_limit = f"LIMIT :{terminal_limit_parameter}"
        if matched_sql.count(terminal_limit) != 1:
            raise ValueError(
                f"query must contain exactly one {terminal_limit} to count pre-limit rows"
            )
        matched_sql = matched_sql.replace(terminal_limit, "", 1)
        # 거리순 nearby 후보의 KNN 상한(T-READ-09) — page 경계와 같은 placeholder라 함께 뗀다.
        matched_sql = matched_sql.replace(
            f"FETCH FIRST (:{terminal_limit_parameter}) ROWS WITH TIES", ""
        )
    return f"SELECT count(*) AS matched_rows FROM ({matched_sql}) AS matched"


def _build_viewports(
    batch_feature_ids: list[str],
    region_searches: Sequence[Viewport] = (),
) -> tuple[Viewport, ...]:
    """DB에서 실제 선택한 public ID로 batch·상세 viewport를 구성한다.

    ``region_searches``는 ``_prepare_region_search``가 DB에서 만든 지역 검색 본 질의다(요청 때와
    같은 전처리를 거쳐야 SQL이 정해진다). 운영 기준선은 13개 전부를 잰다.
    """

    if len(batch_feature_ids) != _BATCH_CARDINALITY:
        raise BenchmarkCardinalityError(
            f"200건 batch에 non-notice public feature {_BATCH_CARDINALITY}건이 필요하지만 "
            f"{len(batch_feature_ids)}건만 선택됨"
        )
    return (
        *_release_viewports(batch_feature_ids),
        *region_searches,
        *_read_baseline_viewports(batch_feature_ids[0]),
    )


def _read_baseline_viewports(detail_feature_id: str) -> tuple[Viewport, ...]:
    """T-READ-01이 더한 PinVi 모양 viewport(지역 검색 제외 5개)."""

    return (
        Viewport(
            name="수도권 시군구 집계(zoom 10)",
            sql=_CLUSTER_BBOX_POINT_ONLY_SQL_BY_UNIT["sigungu"],
            params=_cluster_params(_CAPITAL_AREA_Z10),
            min_returned_rows=1,
            terminal_limit_parameter="limit",
            pre=(_CLUSTER_HASH_AGGREGATE_ON_SQL,),
        ),
        Viewport(
            name="서울시청 읍면동 집계(zoom 12, PinVi 기본 화면)",
            sql=_CLUSTER_BBOX_POINT_ONLY_SQL_BY_UNIT["eupmyeondong"],
            params=_cluster_params(_SEOUL_CITY_HALL_Z12),
            min_returned_rows=1,
            terminal_limit_parameter="limit",
            pre=(_CLUSTER_HASH_AGGREGATE_ON_SQL,),
        ),
        Viewport(
            name="서울시청 읍면동 집계(zoom 13)",
            sql=_CLUSTER_BBOX_POINT_ONLY_SQL_BY_UNIT["eupmyeondong"],
            params=_cluster_params(_SEOUL_CITY_HALL_Z13),
            min_returned_rows=1,
            terminal_limit_parameter="limit",
            pre=(_CLUSTER_HASH_AGGREGATE_ON_SQL,),
        ),
        Viewport(
            name="서울 개별 행 500건(zoom 14)",
            sql=_FEATURES_IN_BBOX_SQL,
            params=_rows_params(_SEOUL_CITY_HALL_Z14),
            min_returned_rows=1,
            terminal_limit_parameter="limit",
        ),
        Viewport(
            name="상세 1건",
            sql=_GET_PUBLIC_FEATURE_SQL,
            params={"feature_id": uuid.UUID(detail_feature_id)},
            min_returned_rows=1,
        ),
    )


def _release_viewports(batch_feature_ids: list[str]) -> tuple[Viewport, ...]:
    """§8.3 release viewport 6개(종전)."""

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
            sql=_CLUSTER_BBOX_POINT_ONLY_SQL_BY_UNIT["sido"],
            params=_NATIONWIDE_LOWZOOM_BBOX,
            min_returned_rows=1,
            terminal_limit_parameter="limit",
            pre=(_CLUSTER_HASH_AGGREGATE_ON_SQL,),
        ),
        # #1455 — route/area를 포함하는 요청은 geometry arm이 실린 SQL을 탄다.
        Viewport(
            name="전국 low-zoom cluster(sido, 전 kind)",
            sql=_CLUSTER_BBOX_SQL_BY_UNIT["sido"],
            params={**_NATIONWIDE_LOWZOOM_BBOX, "kinds": None},
            min_returned_rows=1,
            terminal_limit_parameter="limit",
            pre=(_CLUSTER_HASH_AGGREGATE_ON_SQL,),
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
    # 운영 DB에 ``--skip-seed``로 붙을 때는 연결을 읽기 전용으로 연다 — flag를 빠뜨려도 쓰지 못한다
    # (빠뜨리면 아래 seed가 INSERT하다 25006으로 실패한다).
    server_settings = dict(HARNESS_SERVER_SETTINGS)
    if skip_seed:
        server_settings["default_transaction_read_only"] = "on"
    engine = make_async_engine(normalize_async_dsn(dsn), server_settings=server_settings)

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
                    # 대량 seed와 ANALYZE는 30초를 넘을 수 있다 — seed transaction만 끈다.
                    await session.execute(text("SET LOCAL statement_timeout = 0"))
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
            prepared: list[PreparedRegionSearch] = []
            for case in REGION_SEARCH_CASES:
                async with session.begin():
                    prepared.append(await _prepare_region_search(session, case))
            viewports = _build_viewports(
                batch_feature_ids, [search.viewport for search in prepared]
            )

            for viewport in viewports:
                report["viewports"].append(
                    await _measure_viewport(session, viewport, iterations)
                )

            measured = {entry["name"]: entry for entry in report["viewports"]}
            region_reports: list[dict[str, Any]] = []
            for search in prepared:
                preprocessing = [
                    await _measure_viewport(session, viewport, iterations)
                    for viewport in search.preprocessing
                ]
                variant = await _measure_viewport(
                    session, search.constant_variant, iterations
                )
                full_p50 = float(measured[search.viewport.name]["p50_ms"])
                region_reports.append(
                    {
                        "name": search.case.name,
                        "q": search.case.q,
                        "region_resolved": search.region is not None,
                        "region_code_count": (
                            len(search.region.sigungu_codes)
                            if search.region is not None
                            else 0
                        ),
                        "arms": _arms_report(search.arms),
                        "preprocessing": preprocessing,
                        "preprocessing_p50_sum_ms": round(
                            sum(float(entry["p50_ms"]) for entry in preprocessing), 2
                        ),
                        "name_normalization": {
                            # 변형은 비교 키가 상수라 지역 일치·이름 일치·접기가 달라질 수 있다 —
                            # 두 질의가 같은 행 수를 냈는지 함께 적어 비중을 읽을 때 본다.
                            "same_row_counts": (
                                measured[search.viewport.name]["matched_rows"]
                                == variant["matched_rows"]
                                and measured[search.viewport.name]["returned_rows"]
                                == variant["returned_rows"]
                            ),
                            "full_p50_ms": full_p50,
                            "constant_variant_p50_ms": variant["p50_ms"],
                            "share": _subtract_share(full_p50, float(variant["p50_ms"])),
                            "constant_variant": variant,
                        },
                    }
                )
            report["region_search"] = region_reports
        return report
    finally:
        await engine.dispose()


def _arms_report(arms: _SearchRegionArms | None) -> dict[str, Any] | None:
    if arms is None:
        return None
    return {
        "name_mode": arms.name_mode,
        "categories": arms.categories,
        "token_mode": arms.token_mode,
    }


def _subtract_share(full_ms: float, variant_ms: float) -> float | None:
    """빼고 재는 비중 (i − ii) / i. 본 질의가 0 ms면 정의하지 않는다(``None``)."""

    if full_ms <= 0:
        return None
    return round((full_ms - variant_ms) / full_ms, 4)


async def _measure_viewport(
    session: AsyncSession, viewport: Viewport, iterations: int
) -> dict[str, Any]:
    """viewport 하나를 ``iterations``번 EXPLAIN ANALYZE로 재 report 항목을 만든다."""

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

    return {
        "name": viewport.name,
        "matched_rows": matched_rows,
        "returned_rows": returned_rows,
        "minimum_returned_rows": viewport.min_returned_rows,
        "p50_ms": round(_nearest_rank_percentile(durations_ms, 0.5), 2),
        "p95_ms": round(_nearest_rank_percentile(durations_ms, 0.95), 2),
        "max_ms": round(max(durations_ms), 2),
        "shared_read_blocks_p95": _nearest_rank_percentile(shared_reads, 0.95),
        "response_bytes": response_bytes,
        "top_node": plan_json.get("Node Type"),
    }


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
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="report JSON을 stdout과 함께 이 파일(.safe.json)에도 쓴다. DSN은 담지 않는다.",
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
    report = {**report, "server_settings": dict(HARNESS_SERVER_SETTINGS)}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
