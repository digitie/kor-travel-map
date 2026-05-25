"""``PlaceDetail`` — Feature.kind='place'의 detail."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import AnyUrl, BaseModel, ConfigDict, Field

from .opening_hours import FeatureOpeningHours

__all__ = ["PlaceDetail"]


class PlaceDetail(BaseModel):
    """Feature.kind='place'의 detail (docs/feature-model.md §5)."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    place_kind: str = Field(
        default="place",
        description=(
            "fuel_station / rest_area / beach / recreation_forest / museum / "
            "parking / license_place / mountain_shelter (ADR-027) ..."
        ),
    )
    phones: list[str] = Field(default_factory=list, max_length=3)
    reviews_link: dict[str, AnyUrl] = Field(default_factory=dict)
    business_hours: FeatureOpeningHours | None = None
    facility_info: dict[str, Any] = Field(
        default_factory=dict,
        description="provider별 부가 정보 (예: 해수욕장 ``beachWid``/``beachLen``).",
    )
    license_date: date | None = Field(
        default=None,
        description="MOIS 인허가 영업개시일 등 (Sprint 4).",
    )
    biz_number: str | None = Field(
        default=None,
        description="사업자등록번호 (MOIS provider).",
    )
    payload: dict[str, Any] = Field(default_factory=dict)
