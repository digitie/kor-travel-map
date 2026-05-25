"""영업시간 DTO (``docs/feature-opening-hours.md`` + ``docs/feature-model.md §10``).

Google Places 호환 형태:
- ``day`` 0=Sunday ~ 6=Saturday
- ``time`` "HHMM" (24h, leading zero)
- ``periods`` open/close 쌍의 리스트
- 24/7는 close=None + open=(day=0, time="0000")
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "OpeningTime",
    "OpeningPeriod",
    "SpecialOpeningDay",
    "FeatureOpeningHours",
]


_TIME_HHMM = r"^([01]\d|2[0-3])[0-5]\d$"


class OpeningTime(BaseModel):
    """영업 시각 (Google Places 호환)."""

    model_config = ConfigDict(extra="forbid")

    day: Annotated[int, Field(ge=0, le=6, description="0=일요일 ~ 6=토요일.")]
    time: Annotated[str, Field(pattern=_TIME_HHMM, description="``HHMM`` 형식 (24h).")]


class OpeningPeriod(BaseModel):
    """영업 한 구간 (open ~ close).

    ``close=None`` + ``open.day=0`` + ``open.time="0000"``는 24/7 표시.
    """

    model_config = ConfigDict(extra="forbid")

    open: OpeningTime
    close: OpeningTime | None = None


class SpecialOpeningDay(BaseModel):
    """특정 날짜의 예외 영업 (휴무 / 단축 / 연장)."""

    model_config = ConfigDict(extra="forbid")

    date: date
    is_closed: bool = False
    periods: list[OpeningPeriod] | None = None
    exceptional_hours: bool = True


class FeatureOpeningHours(BaseModel):
    """Feature의 영업시간 묶음."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(
        default="Asia/Seoul",
        description="대한민국 운영 환경에서는 항상 Asia/Seoul (ADR-019).",
    )
    open_now: bool | None = Field(
        default=None,
        description="provider가 알려준 즉시 영업 여부 (스냅샷). 본 라이브러리가 계산하지 않음.",
    )
    periods: list[OpeningPeriod] = Field(default_factory=list)
    special_days: list[SpecialOpeningDay] = Field(default_factory=list)
    weekday_text: list[str] = Field(
        default_factory=list,
        description="UI 표시용 사람이 읽기 쉬운 요일 텍스트 (예: ``'월요일: 09:00 ~ 22:00'``).",
    )
