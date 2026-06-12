"""``EventDetail`` — Feature.kind='event'의 detail (축제/공연/전시)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .opening_hours import FeatureOpeningHours

__all__ = ["EventDetail"]


class EventDetail(BaseModel):
    """Feature.kind='event'의 detail (docs/feature-model.md §6)."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    event_kind: str = Field(
        default="festival",
        description="festival / exhibition / concert / performance ...",
    )
    starts_on: date | None = None
    ends_on: date | None = None
    timezone: str = Field(
        default="Asia/Seoul",
        description="ADR-019 — KST 기본.",
    )
    opening_hours: FeatureOpeningHours | None = None
    venue_name: str | None = None
    tel: str | None = None
    content_id: str | None = Field(
        default=None,
        description="VisitKorea TourAPI contentId 등 provider 원천 id.",
    )
    content_type_id: str | None = None
    area_code: str | None = None
    sigungu_code: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_date_order(self) -> EventDetail:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError(
                f"ends_on ({self.ends_on}) must be >= starts_on ({self.starts_on})."
            )
        return self
