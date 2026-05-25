"""``krtour.map.dto`` — Pydantic v2 입력/출력 DTO.

본 모듈은 ``Feature`` + 5개 detail kind (place/event/notice/route/area)와
부수 모델 (Coordinate/Address/OpeningHours/...)을 노출한다.

**Sprint 1 (PR#19) 시점**: Feature + 5 detail + Coordinate + Address + URLs
+ OpeningHours + enums + NOTICE_TYPES 14건 (ADR-027) + AreaDetail.area_kind
hazard_zone (ADR-027). **Sprint 2 PR에서 추가 예정**:
- ``WeatherValue`` (kind=weather 시계열, ADR-010)
- ``PriceValue`` (kind=price 시계열)
- ``SourceRecord`` / ``SourceLink``
- ``FeatureFile`` / ``FeatureFileSource``
- ``ProviderSyncState`` / ``ImportJob``
- ``FeatureBundle`` (적재 단위)

ADR 참조
--------
- ADR-001 — 의존 방향 ``category → dto → core → infra → providers → client → cli``
- ADR-018 — ``Feature.detail`` 자유 dict 금지
- ADR-019 — KST aware datetime만 허용
- ADR-027 — ``NOTICE_TYPES`` 14건 (``access_restriction``/``fire_alert``),
  ``AreaDetail.area_kind`` Literal에 ``hazard_zone``
- ADR-028 amendment — KNPS ``protected_area`` / ``facility_road`` 표준값
"""

from __future__ import annotations

from ._enums import FeatureKind, FeatureStatus, SourceRole
from ._time import KST, check_aware_datetime, kst_now
from .address import Address
from .area import AREA_KINDS, AreaDetail
from .coordinate import Coordinate
from .event import EventDetail
from .feature import Feature
from .notice import (
    NOTICE_TYPE_ACCESS_RESTRICTION,
    NOTICE_TYPE_COASTAL_ISOLATION,
    NOTICE_TYPE_EARTHQUAKE,
    NOTICE_TYPE_FIRE_ALERT,
    NOTICE_TYPE_HEAT_WAVE,
    NOTICE_TYPE_HEAVY_RAIN,
    NOTICE_TYPE_HEAVY_SNOW,
    NOTICE_TYPE_LANDSLIDE,
    NOTICE_TYPE_ROAD_CLOSURE,
    NOTICE_TYPE_ROADWORK,
    NOTICE_TYPE_SAFETY,
    NOTICE_TYPE_TRAFFIC,
    NOTICE_TYPE_TRAFFIC_ACCIDENT,
    NOTICE_TYPE_WEATHER_ALERT,
    NOTICE_TYPES,
    NoticeDetail,
    normalize_notice_type,
)
from .opening_hours import (
    FeatureOpeningHours,
    OpeningPeriod,
    OpeningTime,
    SpecialOpeningDay,
)
from .place import PlaceDetail
from .route import (
    ROUTE_TYPE_ACCESSIBLE_WALK,
    ROUTE_TYPE_CYCLING,
    ROUTE_TYPE_DRIVE_COURSE,
    ROUTE_TYPE_FACILITY_ROAD,
    ROUTE_TYPE_FOREST_TRAIL,
    ROUTE_TYPE_HIKING_TRAIL,
    ROUTE_TYPE_ROUTE,
    ROUTE_TYPE_TOURISM_ROAD,
    ROUTE_TYPE_TREKKING,
    ROUTE_TYPE_WALKING_COURSE,
    ROUTE_TYPES,
    RouteDetail,
    normalize_route_type,
)
from .urls import FeatureUrls, RawDataRef

__all__ = [
    # enums
    "FeatureKind",
    "FeatureStatus",
    "SourceRole",
    # 기본 모델
    "Coordinate",
    "Address",
    "FeatureUrls",
    "RawDataRef",
    # 영업시간
    "OpeningTime",
    "OpeningPeriod",
    "SpecialOpeningDay",
    "FeatureOpeningHours",
    # detail kinds
    "PlaceDetail",
    "EventDetail",
    "NoticeDetail",
    "RouteDetail",
    "AreaDetail",
    "AREA_KINDS",
    # notice_type 표준 + alias normalize (ADR-027)
    "NOTICE_TYPES",
    "NOTICE_TYPE_TRAFFIC",
    "NOTICE_TYPE_TRAFFIC_ACCIDENT",
    "NOTICE_TYPE_ROAD_CLOSURE",
    "NOTICE_TYPE_ROADWORK",
    "NOTICE_TYPE_WEATHER_ALERT",
    "NOTICE_TYPE_HEAVY_RAIN",
    "NOTICE_TYPE_HEAVY_SNOW",
    "NOTICE_TYPE_HEAT_WAVE",
    "NOTICE_TYPE_SAFETY",
    "NOTICE_TYPE_EARTHQUAKE",
    "NOTICE_TYPE_LANDSLIDE",
    "NOTICE_TYPE_COASTAL_ISOLATION",
    "NOTICE_TYPE_ACCESS_RESTRICTION",
    "NOTICE_TYPE_FIRE_ALERT",
    "normalize_notice_type",
    # route_type 표준 + alias normalize
    "ROUTE_TYPES",
    "ROUTE_TYPE_ROUTE",
    "ROUTE_TYPE_HIKING_TRAIL",
    "ROUTE_TYPE_ACCESSIBLE_WALK",
    "ROUTE_TYPE_TREKKING",
    "ROUTE_TYPE_FOREST_TRAIL",
    "ROUTE_TYPE_TOURISM_ROAD",
    "ROUTE_TYPE_FACILITY_ROAD",
    "ROUTE_TYPE_WALKING_COURSE",
    "ROUTE_TYPE_CYCLING",
    "ROUTE_TYPE_DRIVE_COURSE",
    "normalize_route_type",
    # Feature 본체
    "Feature",
    # KST aware datetime helper (PR#24, dto가 source of truth)
    "KST",
    "kst_now",
    "check_aware_datetime",
]
