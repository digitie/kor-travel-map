"""``Feature`` — 본 라이브러리의 핵심 DTO.

ADR 참조
--------
- ADR-009 — ``feature_id`` 결정적 생성 (``make_feature_id``, PR#20 core/)
- ADR-018 — ``Feature.detail``은 자유 dict 금지, kind별 detail로만 적재
- ADR-019 — 모든 datetime은 KST aware

본 PR (Sprint 1)은 Pydantic 모델만. ``make_feature_id``의 실제 구현은 PR#20.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Final

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ..core import kst_now
from ._enums import FeatureKind, FeatureStatus
from .address import Address
from .area import AreaDetail
from .coordinate import Coordinate
from .event import EventDetail
from .notice import NoticeDetail
from .place import PlaceDetail
from .route import RouteDetail
from .urls import FeatureUrls, RawDataRef

__all__ = ["Feature"]


# ADR-018 — kind → 허용 detail 모델 매핑.
_DETAIL_MODELS: Final[dict[FeatureKind, type[BaseModel]]] = {
    FeatureKind.PLACE: PlaceDetail,
    FeatureKind.EVENT: EventDetail,
    FeatureKind.NOTICE: NoticeDetail,
    FeatureKind.ROUTE: RouteDetail,
    FeatureKind.AREA: AreaDetail,
    # FeatureKind.PRICE / WEATHER는 detail=None (별도 WeatherValue/PriceValue 테이블).
}

# `marker_color` regex — `P-01` ~ `P-16`만 허용.
_MARKER_COLOR_REGEX: Final[re.Pattern[str]] = re.compile(r"^P-(0[1-9]|1[0-6])$")


class Feature(BaseModel):
    """본 라이브러리의 핵심 DTO. 모든 적재 결과는 ``Feature`` 인스턴스.

    ``coord``는 ``None`` 가능 (예: VisitKorea 축제 좌표 nullable). ``detail``은
    ``kind``에 맞는 모델만 허용 (ADR-018) — dict 입력은 ``ValidationError``.

    예시:
        >>> from krtour.map.dto import Feature, Coordinate, PlaceDetail
        >>> Feature(
        ...     feature_id="place:abc123",
        ...     kind="place",
        ...     name="홍대 카페",
        ...     coord=Coordinate(lon=126.92, lat=37.55),
        ...     category="02020101",
        ...     marker_icon="cafe",
        ...     marker_color="P-03",
        ...     detail=PlaceDetail(feature_id="place:abc123", place_kind="cafe"),
        ... )
    """

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(min_length=1, description="``make_feature_id(...)`` 결과.")
    kind: FeatureKind
    name: str = Field(min_length=1)
    coord: Coordinate | None = None
    address: Address = Field(default_factory=Address)
    category: str = Field(
        min_length=1,
        description="``krtour.map.category.PlaceCategoryCode`` value 8자리 (ADR-023).",
    )
    urls: FeatureUrls = Field(default_factory=FeatureUrls)
    marker_icon: str = Field(min_length=1, description="Maki icon name.")
    marker_color: str = Field(
        description="``'P-01'`` ~ ``'P-16'`` 팔레트 코드.",
    )
    parent_feature_id: str | None = None
    sibling_group_id: str | None = Field(
        default=None,
        description="dedup sibling group UUID (string 표현). ADR-016 Record Linkage 결과.",
    )
    detail: (
        PlaceDetail | EventDetail | NoticeDetail | RouteDetail | AreaDetail | None
    ) = None
    raw_refs: list[RawDataRef] = Field(default_factory=list)
    status: FeatureStatus = FeatureStatus.ACTIVE
    created_at: datetime = Field(default_factory=kst_now)
    updated_at: datetime = Field(default_factory=kst_now)
    deleted_at: datetime | None = None

    # ── validators ───────────────────────────────────────────────────────

    @field_validator("marker_color")
    @classmethod
    def _check_marker_color(cls, value: str) -> str:
        if not _MARKER_COLOR_REGEX.match(value):
            raise ValueError(
                f"marker_color must match {_MARKER_COLOR_REGEX.pattern!r}, got {value!r}."
            )
        return value

    @field_validator("created_at", "updated_at", "deleted_at")
    @classmethod
    def _check_kst_aware(cls, value: datetime | None) -> datetime | None:
        """ADR-019 — naive datetime 입력은 ValidationError."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "datetime must be timezone-aware (KST). naive datetime은 금지 (ADR-019)."
            )
        return value

    @model_validator(mode="after")
    def _check_detail_matches_kind(self) -> Feature:
        """ADR-018 — ``detail``은 ``kind``에 맞는 모델만 허용."""
        if self.detail is None:
            # price/weather는 detail=None 허용. 나머지는 detail 필수가 아닌 권장.
            return self
        expected = _DETAIL_MODELS.get(self.kind)
        if expected is None:
            # kind=price/weather에 detail이 들어왔으면 거부.
            raise ValueError(
                f"kind={self.kind.value!r}는 detail을 가질 수 없음 (price/weather는 "
                "별도 WeatherValue/PriceValue 테이블)."
            )
        if not isinstance(self.detail, expected):
            raise ValueError(
                f"kind={self.kind.value!r}는 {expected.__name__}만 허용, "
                f"got {type(self.detail).__name__}."
            )
        return self
