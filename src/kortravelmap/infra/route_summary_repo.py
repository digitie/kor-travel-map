"""공개 route 요약(거리·소요시간·난이도·출발/도착) 조회 repository (ADR-128).

공개 목록(bbox·in-bounds·search·nearby)과 상세가 ``kind='route'`` 항목에 같은 요약을 싣도록
한 페이지의 route id를 한 번에 읽는다. 읽는 곳은 ``feature.public_features`` 하나뿐이다 —
공개 여부 판정을 다시 하지 않고, 공개 view에 없는 id는 결과에서 빠진다.

출발·도착 좌표는 저장 열이 아니라 geometry에서 유도한다. 등산 코스(``hiking_course``)는
조립 때 **첫 선이 본선이고 정점 순서가 진행 방향**이 되도록 저장했으므로(``core.route_course``)
첫 선의 첫/끝 점이 곧 출발/도착이다. 다른 route_type은 원천 디지타이징 방향이라 진행
방향이 정의돼 있지 않아 출발·도착을 내지 않는다.

``duration_basis``(원천/추정)와 ``course_shape``는 ``detail.payload``에 있다. 공개 detail은
payload를 벗기지만(T-VN-05) 이 두 값은 원천 raw가 아니라 Map이 만든 해석이라 요약으로
올린다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto.route import ROUTE_TYPE_HIKING_COURSE

__all__ = [
    "PublicRouteSummary",
    "list_public_route_summaries",
]


@dataclass(frozen=True, slots=True)
class PublicRouteSummary:
    """공개 route 1건의 요약."""

    feature_id: str
    route_type: str
    length_m: float | None
    duration_minutes: int | None
    duration_basis: str | None
    difficulty: str | None
    shape: str | None
    start: tuple[float, float] | None
    start_name: str | None
    end: tuple[float, float] | None
    end_name: str | None


_SUMMARY_SQL: Final[str] = """
SELECT
    CAST(f.feature_id AS text) AS feature_id,
    f.detail ->> 'route_type' AS route_type,
    f.detail ->> 'total_distance_meters' AS total_distance_meters,
    f.detail ->> 'expected_duration_minutes' AS expected_duration_minutes,
    f.detail ->> 'difficulty' AS difficulty,
    f.detail ->> 'begin_name' AS begin_name,
    f.detail ->> 'end_name' AS end_name,
    f.detail -> 'payload' ->> 'duration_basis' AS duration_basis,
    f.detail -> 'payload' ->> 'course_shape' AS course_shape,
    -- 출발·도착은 방향이 정의된 등산 코스에만 계산한다 — 다른 route는 geometry를 풀지 않는다.
    CASE WHEN f.detail ->> 'route_type' = :directed_route_type THEN
        x_extension.ST_X(x_extension.ST_StartPoint(x_extension.ST_GeometryN(f.geom, 1)))
    END AS start_lon,
    CASE WHEN f.detail ->> 'route_type' = :directed_route_type THEN
        x_extension.ST_Y(x_extension.ST_StartPoint(x_extension.ST_GeometryN(f.geom, 1)))
    END AS start_lat,
    CASE WHEN f.detail ->> 'route_type' = :directed_route_type THEN
        x_extension.ST_X(x_extension.ST_EndPoint(x_extension.ST_GeometryN(f.geom, 1)))
    END AS end_lon,
    CASE WHEN f.detail ->> 'route_type' = :directed_route_type THEN
        x_extension.ST_Y(x_extension.ST_EndPoint(x_extension.ST_GeometryN(f.geom, 1)))
    END AS end_lat
FROM feature.public_features AS f
WHERE f.feature_id = ANY(CAST(:feature_ids AS uuid[]))
  AND f.kind = 'route'
"""


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    return None if number is None else int(number)


def _point(lon: Any, lat: Any) -> tuple[float, float] | None:
    lon_value, lat_value = _float_or_none(lon), _float_or_none(lat)
    if lon_value is None or lat_value is None:
        return None
    return (lon_value, lat_value)


async def list_public_route_summaries(
    session: AsyncSession, feature_ids: Sequence[str]
) -> dict[str, PublicRouteSummary]:
    """공개 route id → 요약. route가 아니거나 비공개인 id는 결과에 없다."""
    ids = sorted({str(feature_id) for feature_id in feature_ids})
    if not ids:
        return {}
    rows = (
        await session.execute(
            text(_SUMMARY_SQL),
            {"feature_ids": ids, "directed_route_type": ROUTE_TYPE_HIKING_COURSE},
        )
    ).mappings().all()
    summaries: dict[str, PublicRouteSummary] = {}
    for row in rows:
        route_type = row["route_type"] or "route"
        directed = route_type == ROUTE_TYPE_HIKING_COURSE
        duration = _int_or_none(row["expected_duration_minutes"])
        # 출처는 provider가 payload에 적은 값만 믿는다 — 추론하지 않는다(운영자 override나
        # 새 provider의 추정값을 원천으로 잘못 표시하지 않게).
        basis = row["duration_basis"] if duration is not None else None
        summaries[row["feature_id"]] = PublicRouteSummary(
            feature_id=row["feature_id"],
            route_type=route_type,
            length_m=_float_or_none(row["total_distance_meters"]),
            duration_minutes=duration,
            duration_basis=basis,
            difficulty=row["difficulty"],
            shape=row["course_shape"] if directed else None,
            start=_point(row["start_lon"], row["start_lat"]) if directed else None,
            start_name=row["begin_name"],
            end=_point(row["end_lon"], row["end_lat"]) if directed else None,
            end_name=row["end_name"],
        )
    return summaries
