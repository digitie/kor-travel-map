"""원천 구간을 이어 만든 등산 코스 ``FeatureBundle`` 조립 공용부 (ADR-128).

산림청 등산로(``providers.krforest``)와 KNPS 탐방로(``providers.knps``)가 함께 쓴다.
provider별 모듈은 **무엇을 한 코스로 묶을지**(그룹 키·출발 힌트·원천 속성 해석)만 정하고,
코스 Feature·SourceRecord·SourceLink의 모양은 여기 한 곳이 정한다.

코스 Feature의 계약:

- ``kind='route'``, ``RouteDetail.route_type='hiking_course'``.
- ``coord`` = **출발점**(geometry 첫 선의 첫 점). PinVi 등 소비자는 코스를 일정에 넣을 때
  이 좌표를 POI 위치로 쓴다 — 선의 무게중심은 산 한가운데라 찾아갈 수 없다.
- ``geom`` = 방향이 맞춰진 코스 선(:mod:`kortravelmap.core.route_course`).
- 거리·소요시간·난이도·출발/도착 이름은 ``feature_routes`` 정규 열에 싣는다(공개 표면).
  출처 구분(원천/추정)과 구간 계보는 ``payload``에 싣는다(공개 표면에서는 벗겨진다).
- 원천 구간은 코스 SourceRecord의 ``raw_data.segments``에 원문 그대로 남는다 — 코스의
  계보이자 구간 단위 속성(거리·상하행 시간·난이도…)의 보존처다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

from shapely import wkt as shapely_wkt

from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.core.route_course import AssembledCourse
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    RouteDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.route import ROUTE_TYPE_HIKING_COURSE
from kortravelmap.geocoding import ReverseGeocoder

__all__ = [
    "COURSE_GEOMETRY_STATUS",
    "DurationBasis",
    "ESTIMATED_MINUTES_PER_KM",
    "CourseAggregate",
    "build_course_bundle",
    "estimate_duration_minutes",
    "sorted_unique_texts",
]

COURSE_GEOMETRY_STATUS: Final[str] = "assembled"
"""``RouteDetail.geometry_status`` — 원천 구간을 이어 Map이 조립한 선."""

ESTIMATED_MINUTES_PER_KM: Final[float] = 18.0
"""원천 소요시간이 없을 때의 거리 기반 추정치(분/km).

산림청 등산로 원천의 상행시간/거리 중앙값이 17.8분/km(약 3.4 km/h, 2026-11 prod 57,047구간
실측)라 그 값을 쓴다. 고도 자료가 없어 Naismith식 오르막 가산은 하지 않는다 — 추정값은
항상 ``duration_basis='estimated'``로 표시한다.
"""

DurationBasis = Literal["source", "estimated"]


def estimate_duration_minutes(length_m: float) -> int:
    """거리만으로 추정한 소요시간(분, 최소 1)."""
    return max(1, math.ceil(length_m / 1000.0 * ESTIMATED_MINUTES_PER_KM))


@dataclass(frozen=True, slots=True)
class CourseAggregate:
    """provider가 원천 구간에서 모은 코스 속성."""

    natural_key: str
    name: str
    segment_source_ids: tuple[str, ...]
    segment_raws: tuple[Mapping[str, Any], ...]
    """구간 원문(raw) — 코스 SourceRecord ``raw_data.segments``에 그대로 남긴다."""
    source_distance_m: float | None
    """원천이 적은 구간 거리의 합(m). 모르면 ``None``."""
    source_duration_minutes: int | None
    """원천 소요시간 합(분). 하나라도 빠졌으면 ``None`` — 추정으로 내려간다."""
    difficulty: str | None
    begin_name: str | None = None
    end_name: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    """provider 고유 계보·원천 값(공개 표면에서는 벗겨진다)."""


async def build_course_bundle(
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    category: str,
    marker_icon: str,
    marker_color: str,
    geometry_source: str,
    course: AssembledCourse,
    aggregate: CourseAggregate,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    """조립된 코스 1개를 ``FeatureBundle``로 만든다."""
    start = Coordinate(lon=Decimal(str(course.start[0])), lat=Decimal(str(course.start[1])))
    address = await _course_address(course, start, reverse_geocoder)
    if aggregate.source_duration_minutes is not None:
        duration = max(1, aggregate.source_duration_minutes)
        duration_basis: DurationBasis = "source"
    else:
        duration = estimate_duration_minutes(course.length_m)
        duration_basis = "estimated"
    raw_data: dict[str, Any] = {
        "course_key": aggregate.natural_key,
        "segments": [dict(raw) for raw in aggregate.segment_raws],
        "_kortravelmap_course": {
            "geometry_wkt": course.wkt,
            "shape": course.shape,
            "excluded_segment_ids": list(course.excluded_segment_ids),
        },
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=aggregate.natural_key,
        raw_payload_hash=payload_hash,
    )
    # route identity는 원천-native다(bjd_code=None) — 역지오 결과가 바뀌어도 같은 코스는
    # 같은 id로 남는다(krforest 구간 route와 같은 규칙).
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.ROUTE.value,
        category=category,
        source_type=f"{provider}:{dataset_key}",
        source_natural_key=aggregate.natural_key,
    )
    detail_payload: dict[str, Any] = {
        "dataset_key": dataset_key,
        "course_key": aggregate.natural_key,
        "course_shape": course.shape,
        "part_count": course.part_count,
        "main_length_m": round(course.main_length_m, 1),
        "segment_count": len(aggregate.segment_source_ids),
        "segment_source_ids": list(aggregate.segment_source_ids),
        "excluded_segment_ids": list(course.excluded_segment_ids),
        "source_distance_m": (
            round(aggregate.source_distance_m, 1)
            if aggregate.source_distance_m is not None
            else None
        ),
        "duration_basis": duration_basis,
        "availability_status_source": "not_available",
        **dict(aggregate.payload),
    }
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=aggregate.natural_key,
        kind=FeatureKind.ROUTE,
        name=aggregate.name,
        coord=start,
        address=address or Address(),
        geom=course.wkt,
        category=category,
        marker_icon=marker_icon,
        marker_color=marker_color,
        detail=RouteDetail(
            feature_id=feature_id,
            route_type=ROUTE_TYPE_HIKING_COURSE,
            geometry_source=geometry_source,
            geometry_status=COURSE_GEOMETRY_STATUS,
            total_distance_meters=Decimal(str(round(course.length_m, 1))),
            expected_duration_minutes=duration,
            difficulty=aggregate.difficulty,
            begin_name=aggregate.begin_name,
            end_name=aggregate.end_name,
            payload=detail_payload,
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(provider),
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=aggregate.natural_key,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
    )
    return FeatureBundle(feature=feature, source_record=source_record, source_link=source_link)


async def _course_address(
    course: AssembledCourse, start: Coordinate, reverse_geocoder: ReverseGeocoder | None
) -> Address | None:
    """출발점 역지오. 법정동을 못 얻으면(해안·경계선 위 들머리) 본선 중간점으로 다시 묻는다.

    구간 route는 선의 무게중심으로 역지오했고 prod 57k건이 모두 법정동을 얻었다. 출발점은 망의
    바깥 말단이라 경계 밖에 걸릴 수 있으므로, 그때만 본선 중간점으로 다시 묻는다.
    """
    if reverse_geocoder is None:
        return None
    address = await reverse_geocoder(start)
    if address is not None and address.bjd_code is not None:
        return address
    geometry = shapely_wkt.loads(course.wkt)
    main_line = geometry.geoms[0] if hasattr(geometry, "geoms") else geometry
    # 선의 대표점(PointOnSurface)은 정점이 둘뿐인 선에서 끝점이 된다 — 본선의 중간점을 쓴다.
    representative = main_line.interpolate(0.5, normalized=True)
    fallback = await reverse_geocoder(
        Coordinate(lon=Decimal(str(representative.x)), lat=Decimal(str(representative.y)))
    )
    return fallback if fallback is not None and fallback.bjd_code is not None else address


def sorted_unique_texts(values: Sequence[str | None]) -> list[str]:
    """비어 있지 않은 문자열을 중복 없이 정렬해 돌려준다(payload 요약용)."""
    return sorted({value for value in values if value})
