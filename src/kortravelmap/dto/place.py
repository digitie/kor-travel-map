"""``PlaceDetail`` — Feature.kind='place'의 detail."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator

from .opening_hours import FeatureOpeningHours
from .visitor_info import VISITOR_INFO_KEY, PlaceVisitorInfo

__all__ = ["PlaceDetail"]


class PlaceDetail(BaseModel):
    """Feature.kind='place'의 detail (docs/architecture/feature-model.md §5)."""

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
        description=(
            "provider별 부가 정보 (예: 해수욕장 ``beachWid``/``beachLen``). "
            "``visitor_info`` 키는 typed ``PlaceVisitorInfo``다(ADR-126)."
        ),
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

    @field_validator("facility_info", mode="after")
    @classmethod
    def _typed_visitor_info(cls, value: dict[str, Any]) -> dict[str, Any]:
        """``facility_info["visitor_info"]``를 :class:`PlaceVisitorInfo`로 검증·정규화한다.

        모델이든 dict든 받아 같은 JSON 모양으로 둔다 — 저장값과 읽은 값의 표현이 갈라지지 않게.
        빈 안내(출처뿐)·``None``은 키째 뺀다. 맞지 않는 모양은 ``ValidationError``다(ADR-018).
        """
        if VISITOR_INFO_KEY not in value:
            return value
        raw = value[VISITOR_INFO_KEY]
        rest = {key: item for key, item in value.items() if key != VISITOR_INFO_KEY}
        if raw is None:
            return rest  # 명시 None = 방문 안내 없음
        info = (
            raw if isinstance(raw, PlaceVisitorInfo) else PlaceVisitorInfo.model_validate(raw)
        )
        if info.is_empty():
            return rest
        return rest | {VISITOR_INFO_KEY: info.model_dump(mode="json", exclude_defaults=True)}
