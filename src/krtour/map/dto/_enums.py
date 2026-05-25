"""``krtour.map.dto._enums`` — Feature/Source enum 정의.

ADR 참조
--------
- ADR-018 — ``Feature.detail`` 자유 dict 금지 (``FeatureKind`` 분기 강제)
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["FeatureKind", "FeatureStatus", "SourceRole"]


class FeatureKind(StrEnum):
    """Feature 종류 7종 (``docs/feature-model.md §1``)."""

    PLACE = "place"
    EVENT = "event"
    NOTICE = "notice"
    PRICE = "price"
    WEATHER = "weather"
    ROUTE = "route"
    AREA = "area"


class FeatureStatus(StrEnum):
    """Feature 상태 (``docs/feature-model.md §2``)."""

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    HIDDEN = "hidden"
    BROKEN = "broken"
    DELETED = "deleted"


class SourceRole(StrEnum):
    """SourceRecord/SourceLink role (``docs/feature-model.md §3``)."""

    PRIMARY = "primary"
    BASE_ADDRESS = "base_address"
    BASE_COORDINATE = "base_coordinate"
    ENRICHMENT = "enrichment"
    CORRECTION = "correction"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    MEDIA = "media"
    WEATHER_CONTEXT = "weather_context"
