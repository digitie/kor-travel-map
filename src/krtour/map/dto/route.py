"""``RouteDetail`` + ROUTE_TYPES + ``normalize_route_type``.

geometry는 ``features.geom`` (LINESTRING / MULTILINESTRING) 컬럼에 저장.
``RouteDetail``은 메타만.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "RouteDetail",
    # 표준 route_type 상수
    "ROUTE_TYPE_ROUTE",
    "ROUTE_TYPE_HIKING_TRAIL",
    "ROUTE_TYPE_ACCESSIBLE_WALK",
    "ROUTE_TYPE_TREKKING",
    "ROUTE_TYPE_FOREST_TRAIL",
    "ROUTE_TYPE_TOURISM_ROAD",
    "ROUTE_TYPE_WALKING_COURSE",
    "ROUTE_TYPE_CYCLING",
    "ROUTE_TYPE_DRIVE_COURSE",
    # 집합
    "ROUTE_TYPES",
    # helper
    "normalize_route_type",
]


# ── 표준 route_type 상수 ─────────────────────────────────────────────────

ROUTE_TYPE_ROUTE: Final[str] = "route"
ROUTE_TYPE_HIKING_TRAIL: Final[str] = "hiking_trail"
ROUTE_TYPE_ACCESSIBLE_WALK: Final[str] = "accessible_walk"
ROUTE_TYPE_TREKKING: Final[str] = "trekking"
ROUTE_TYPE_FOREST_TRAIL: Final[str] = "forest_trail"
ROUTE_TYPE_TOURISM_ROAD: Final[str] = "tourism_road"
ROUTE_TYPE_WALKING_COURSE: Final[str] = "walking_course"
ROUTE_TYPE_CYCLING: Final[str] = "cycling"
ROUTE_TYPE_DRIVE_COURSE: Final[str] = "drive_course"

ROUTE_TYPES: Final[tuple[str, ...]] = (
    ROUTE_TYPE_ROUTE,
    ROUTE_TYPE_HIKING_TRAIL,
    ROUTE_TYPE_ACCESSIBLE_WALK,
    ROUTE_TYPE_TREKKING,
    ROUTE_TYPE_FOREST_TRAIL,
    ROUTE_TYPE_TOURISM_ROAD,
    ROUTE_TYPE_WALKING_COURSE,
    ROUTE_TYPE_CYCLING,
    ROUTE_TYPE_DRIVE_COURSE,
)


# ── 한국어/영어 alias → canonical route_type ─────────────────────────────

_ROUTE_ALIAS_MAP: Final[dict[str, str]] = {
    "등산로": ROUTE_TYPE_HIKING_TRAIL,
    "산행로": ROUTE_TYPE_HIKING_TRAIL,
    "hiking": ROUTE_TYPE_HIKING_TRAIL,
    "무장애산책길": ROUTE_TYPE_ACCESSIBLE_WALK,
    "무장애길": ROUTE_TYPE_ACCESSIBLE_WALK,
    "accessible": ROUTE_TYPE_ACCESSIBLE_WALK,
    "트레킹": ROUTE_TYPE_TREKKING,
    "둘레길": ROUTE_TYPE_TREKKING,
    "trekking": ROUTE_TYPE_TREKKING,
    "숲길": ROUTE_TYPE_FOREST_TRAIL,
    "산림욕장": ROUTE_TYPE_FOREST_TRAIL,
    "forest_trail": ROUTE_TYPE_FOREST_TRAIL,
    "관광도로": ROUTE_TYPE_TOURISM_ROAD,
    "tourism_road": ROUTE_TYPE_TOURISM_ROAD,
    "관광길": ROUTE_TYPE_TOURISM_ROAD,
    "산책로": ROUTE_TYPE_WALKING_COURSE,
    "walking": ROUTE_TYPE_WALKING_COURSE,
    "자전거길": ROUTE_TYPE_CYCLING,
    "자전거도로": ROUTE_TYPE_CYCLING,
    "cycling": ROUTE_TYPE_CYCLING,
    "drive_course": ROUTE_TYPE_DRIVE_COURSE,
    "드라이브코스": ROUTE_TYPE_DRIVE_COURSE,
}


def normalize_route_type(value: str) -> str:
    """``route_type`` alias를 canonical value로 정규화한다.

    이미 canonical이면 그대로 반환. alias 매핑에 있으면 변환. 둘 다 아니면
    fallback ``ROUTE_TYPE_ROUTE`` (general route) — route_type은 notice_type
    과 달리 unknown에 lenient. provider별 새 케이스가 자주 들어옴.
    """
    if value in ROUTE_TYPES:
        return value
    if value in _ROUTE_ALIAS_MAP:
        return _ROUTE_ALIAS_MAP[value]
    return ROUTE_TYPE_ROUTE


# ── RouteDetail 본체 ─────────────────────────────────────────────────────


class RouteDetail(BaseModel):
    """Feature.kind='route'의 detail (docs/feature-model.md §8)."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    route_type: str = Field(default=ROUTE_TYPE_ROUTE)
    geometry_source: str | None = Field(
        default=None,
        description="``'krforest'``, ``'datagokr_standard'``, ``'knps'``, ...",
    )
    geometry_status: str | None = Field(
        default=None,
        description="``'provided'`` / ``'missing_route_geometry'`` / ...",
    )
    total_distance_meters: Decimal | None = Field(default=None, ge=0)
    expected_duration_minutes: int | None = Field(default=None, ge=1)
    difficulty: str | None = Field(
        default=None,
        description="``'easy'`` / ``'moderate'`` / ``'hard'`` 또는 KNPS 5단계.",
    )
    begin_name: str | None = None
    begin_address: str | None = None
    end_name: str | None = None
    end_address: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("route_type", mode="before")
    @classmethod
    def _normalize_route_type(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError(f"route_type must be a string, got {type(value).__name__}.")
        return normalize_route_type(value)
