"""``NoticeDetail`` + NOTICE_TYPES 14건 + ``normalize_notice_type``.

ADR 참조
--------
- ADR-018 — ``Feature.detail``은 자유 dict 금지, NoticeDetail로만 적재
- ADR-019 — datetime 모두 KST aware
- ADR-027 — ``NOTICE_TYPE_ACCESS_RESTRICTION`` / ``NOTICE_TYPE_FIRE_ALERT``
  추가 (generic, ``payload.domain``으로 출처 구분: ``forest`` / ``coastal``
  / ``urban`` ...)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._time import check_aware_datetime

__all__ = [
    # NoticeDetail 본체
    "NoticeDetail",
    # 표준 notice_type 상수
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
    "NOTICE_TYPE_ACCESS_RESTRICTION",  # ADR-027
    "NOTICE_TYPE_FIRE_ALERT",  # ADR-027
    # 집합
    "NOTICE_TYPES",
    # helper
    "normalize_notice_type",
]


# ── 표준 notice_type 상수 (docs/etl/notice-feature-etl.md §3) ────────────────

NOTICE_TYPE_TRAFFIC: Final[str] = "traffic"
NOTICE_TYPE_TRAFFIC_ACCIDENT: Final[str] = "traffic_accident"
NOTICE_TYPE_ROAD_CLOSURE: Final[str] = "road_closure"
NOTICE_TYPE_ROADWORK: Final[str] = "roadwork"
NOTICE_TYPE_WEATHER_ALERT: Final[str] = "weather_alert"
NOTICE_TYPE_HEAVY_RAIN: Final[str] = "heavy_rain_warning"
NOTICE_TYPE_HEAVY_SNOW: Final[str] = "heavy_snow_warning"
NOTICE_TYPE_HEAT_WAVE: Final[str] = "heat_wave_warning"
NOTICE_TYPE_SAFETY: Final[str] = "safety"
NOTICE_TYPE_EARTHQUAKE: Final[str] = "earthquake"
NOTICE_TYPE_LANDSLIDE: Final[str] = "landslide_warning"
NOTICE_TYPE_COASTAL_ISOLATION: Final[str] = "coastal_isolation"
# ADR-027: forest/beach/urban generic notice. payload.domain으로 출처 구분.
NOTICE_TYPE_ACCESS_RESTRICTION: Final[str] = "access_restriction"
NOTICE_TYPE_FIRE_ALERT: Final[str] = "fire_alert"

NOTICE_TYPES: Final[tuple[str, ...]] = (
    NOTICE_TYPE_TRAFFIC,
    NOTICE_TYPE_TRAFFIC_ACCIDENT,
    NOTICE_TYPE_ROAD_CLOSURE,
    NOTICE_TYPE_ROADWORK,
    NOTICE_TYPE_WEATHER_ALERT,
    NOTICE_TYPE_HEAVY_RAIN,
    NOTICE_TYPE_HEAVY_SNOW,
    NOTICE_TYPE_HEAT_WAVE,
    NOTICE_TYPE_SAFETY,
    NOTICE_TYPE_EARTHQUAKE,
    NOTICE_TYPE_LANDSLIDE,
    NOTICE_TYPE_COASTAL_ISOLATION,
    NOTICE_TYPE_ACCESS_RESTRICTION,
    NOTICE_TYPE_FIRE_ALERT,
)


# ── 한국어/영어 alias → canonical notice_type ────────────────────────────

_ALIAS_MAP: Final[dict[str, str]] = {
    # weather alerts (base type + 주의보/경보 suffix 모두 매핑)
    "호우": NOTICE_TYPE_HEAVY_RAIN,
    "호우주의보": NOTICE_TYPE_HEAVY_RAIN,
    "호우경보": NOTICE_TYPE_HEAVY_RAIN,
    "heavy_rain": NOTICE_TYPE_HEAVY_RAIN,
    "대설": NOTICE_TYPE_HEAVY_SNOW,
    "대설주의보": NOTICE_TYPE_HEAVY_SNOW,
    "대설경보": NOTICE_TYPE_HEAVY_SNOW,
    "폭설": NOTICE_TYPE_HEAVY_SNOW,
    "heavy_snow": NOTICE_TYPE_HEAVY_SNOW,
    "폭염": NOTICE_TYPE_HEAT_WAVE,
    "폭염주의보": NOTICE_TYPE_HEAT_WAVE,
    # KMA 기상특보 13종 중 전용 canonical이 없는 종류 → generic weather_alert.
    # (payload/title에 원문 특보명 보존. docs/etl/notice-feature-etl.md §3 / ADR-027.)
    "강풍": NOTICE_TYPE_WEATHER_ALERT,
    "풍랑": NOTICE_TYPE_WEATHER_ALERT,
    "태풍": NOTICE_TYPE_WEATHER_ALERT,
    "건조": NOTICE_TYPE_WEATHER_ALERT,
    "한파": NOTICE_TYPE_WEATHER_ALERT,
    "폭풍해일": NOTICE_TYPE_WEATHER_ALERT,
    "황사": NOTICE_TYPE_WEATHER_ALERT,
    "weather_alert": NOTICE_TYPE_WEATHER_ALERT,
    "지진": NOTICE_TYPE_EARTHQUAKE,
    "earthquake": NOTICE_TYPE_EARTHQUAKE,
    "산사태": NOTICE_TYPE_LANDSLIDE,
    "landslide": NOTICE_TYPE_LANDSLIDE,
    # coastal
    "바다갈라짐": NOTICE_TYPE_COASTAL_ISOLATION,
    "coastal_isolation": NOTICE_TYPE_COASTAL_ISOLATION,
    # traffic
    "교통사고": NOTICE_TYPE_TRAFFIC_ACCIDENT,
    "accident": NOTICE_TYPE_TRAFFIC_ACCIDENT,
    "통제": NOTICE_TYPE_ROAD_CLOSURE,
    "도로통제": NOTICE_TYPE_ROAD_CLOSURE,
    "road_closure": NOTICE_TYPE_ROAD_CLOSURE,
    "공사": NOTICE_TYPE_ROADWORK,
    "도로공사": NOTICE_TYPE_ROADWORK,
    "roadwork": NOTICE_TYPE_ROADWORK,
    # ADR-027: access_restriction (산림/해변/공원/등산로 출입 제한)
    "입산통제": NOTICE_TYPE_ACCESS_RESTRICTION,
    "입산제한": NOTICE_TYPE_ACCESS_RESTRICTION,
    "forest_access": NOTICE_TYPE_ACCESS_RESTRICTION,
    "hiking_closure": NOTICE_TYPE_ACCESS_RESTRICTION,
    "해수욕장폐장": NOTICE_TYPE_ACCESS_RESTRICTION,
    "beach_closure": NOTICE_TYPE_ACCESS_RESTRICTION,
    "공원폐쇄": NOTICE_TYPE_ACCESS_RESTRICTION,
    "park_closure": NOTICE_TYPE_ACCESS_RESTRICTION,
    # ADR-027: fire_alert (산불 + 화재 일반)
    "산불경보": NOTICE_TYPE_FIRE_ALERT,
    "forest_fire": NOTICE_TYPE_FIRE_ALERT,
    "fire": NOTICE_TYPE_FIRE_ALERT,
    "화재경보": NOTICE_TYPE_FIRE_ALERT,
}


def normalize_notice_type(value: str) -> str:
    """``notice_type`` alias를 canonical value로 정규화한다.

    이미 canonical (``NOTICE_TYPES`` 중 하나)이면 그대로 반환. alias 매핑에
    있으면 canonical로 변환. 둘 다 아니면 ``ValueError``.

    예시:
        >>> normalize_notice_type("호우경보")
        'heavy_rain_warning'
        >>> normalize_notice_type("입산통제")
        'access_restriction'
        >>> normalize_notice_type("traffic")
        'traffic'
    """
    if value in NOTICE_TYPES:
        return value
    if value in _ALIAS_MAP:
        return _ALIAS_MAP[value]
    raise ValueError(
        f"unknown notice_type: {value!r}. "
        f"NOTICE_TYPES 중 하나이거나 한/영 alias여야 함 "
        f"(docs/etl/notice-feature-etl.md §3, ADR-027 generic 명명)."
    )


# ── NoticeDetail 본체 ────────────────────────────────────────────────────


class NoticeDetail(BaseModel):
    """Feature.kind='notice'의 detail (docs/architecture/feature-model.md §7).

    ``notice_type``은 ``normalize_notice_type``으로 자동 정규화 (validator).
    severity 0~5 (0=정보 / 5=즉시 대응).

    ADR-019 — ``valid_start_time``/``valid_end_time``은 KST aware datetime만.
    naive 입력은 ValidationError.

    ADR-027 — generic ``access_restriction`` / ``fire_alert``는 ``payload.
    domain``으로 forest/coastal/urban 출처 구분.
    """

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    notice_type: str = Field(
        description="NOTICE_TYPES 중 하나. alias 입력은 자동 정규화."
    )
    severity: int | None = Field(
        default=None,
        ge=0,
        le=5,
        description="0=정보, 1=주의보, 2=경보, 3=긴급, 4=위험, 5=매우 위험.",
    )
    valid_start_time: datetime | None = None
    valid_end_time: datetime | None = None
    source_agency: str | None = Field(default=None, description="발령 기관 (예: 기상청).")
    officer_name: str | None = Field(default=None, description="작성자 (있으면).")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "provider 원문 + ADR-027 generic notice의 출처 구분. 예: "
            "`{'domain': 'forest', 'krex_grade': 'Level3', 'krex_grade_desc': "
            "'차량 통행 통제'}`."
        ),
    )

    @field_validator("notice_type", mode="before")
    @classmethod
    def _normalize_notice_type(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError(f"notice_type must be a string, got {type(value).__name__}.")
        return normalize_notice_type(value)

    @field_validator("valid_start_time", "valid_end_time")
    @classmethod
    def _check_aware(cls, value: datetime | None) -> datetime | None:
        """ADR-019 — naive datetime 입력은 ValidationError.

        review report P0-2: PR#19 시점엔 ``Feature`` timestamp만 검증했지만
        notice의 효력 기간 datetime도 동일 정책 적용.
        """
        return check_aware_datetime(value)
