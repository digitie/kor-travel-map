"""``kortravelmap.dto.weather_state`` — Valkey에 담는 weather 현재·예보·세 구간 요약 값 모델
(ADR-114 2단계).

Map Dagster의 ``weather_state_*`` job이 이 모델의 JSON을 Valkey 세대 키에 쓰고, Map API의
``/v1/service/weather/*``가 같은 모델로 읽어 응답한다. 값의 모양은 여기 한 곳이 정본이다
(ADR-114 "구현 설계 — 2단계" W1·W2). 모양을 바꾸면 Valkey 키 접두사의 스키마 버전
(``infra.valkey_state.STATE_KEY_PREFIX``)도 함께 올린다.

- **값 하나 = weather 위치 하나**다. 일곱 데이터셋이 같은 ``feature_id``(위치)를 키로 쓴다.
- ``feature_id``는 ``core.make_feature_id``(``kind="weather"``, ``bjd_code=None``)로 만든 legacy
  형식 문자열이다. PG feature가 아니다(ADR-105가 PG weather feature를 지웠다).
- 법정동 코드는 weather가 준 값을 그대로 쓴다(ADR-114 결정 6) — geo를 다시 부르지 않는다.
- 시각은 timezone이 있는 값만 받는다(ADR-019).
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from kortravelmap.dto.transport_state import StateCoordinate

__all__ = [
    "DailySlot",
    "WeatherCurrentState",
    "WeatherDailySlotState",
    "WeatherDailySummaryState",
    "WeatherForecastGroupState",
    "WeatherForecastState",
    "WeatherForecastStyle",
    "WeatherLocationAddress",
    "WeatherLocationState",
    "WeatherObservationState",
]

WeatherForecastStyle = Literal["ultra_short", "short", "mid", "external"]
"""weather W3 예보 style. 데이터셋 하나가 style 하나다."""

DailySlot = Literal["morning", "noon", "evening"]
"""KST 하루 세 구간: morning [05,11) · noon [11,17) · evening [17,23)."""

MetricValue = float | str | None
"""weather metric 값 — 수·서술 문자열(예: 하늘상태 문구)·null. 문자열을 수로 바꾸지 않는다."""


class _StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WeatherLocationAddress(_StateModel):
    """weather가 준 행정 정보(ADR-114 결정 6 — 그대로 쓴다)."""

    sido_name: str | None = None
    sigungu_name: str | None = None
    bjd_code: str | None = Field(
        default=None,
        pattern=r"^[0-9]{10}$",
        description="법정동 코드 10자리(weather W1 ``legal_dong_code``). 없으면 null.",
    )


class WeatherLocationState(_StateModel):
    """weather 위치 1곳(W1 roster)."""

    feature_id: str
    kind: Literal["weather"] = "weather"
    category: str
    marker_icon: str
    marker_color: str
    location_id: str = Field(description="weather 위치 id(자연키).")
    name: str
    coord: StateCoordinate | None
    address: WeatherLocationAddress


class WeatherObservationState(_StateModel):
    """위치×provider×metric 최신 관측 1값(W2)."""

    provider: str
    metric_key: str
    value: MetricValue
    unit: str | None = None
    target_at: AwareDatetime = Field(description="관측·실황이 가리키는 시각.")
    known_at: AwareDatetime = Field(description="원천 fact의 인식 시각.")
    forecast_style: Literal["observed", "nowcast"]


class WeatherCurrentState(_StateModel):
    """위치 하나의 최신 관측 값들. ``(provider, metric_key)``당 하나."""

    feature_id: str
    location_id: str
    observations: list[WeatherObservationState]


class WeatherForecastGroupState(_StateModel):
    """위치×provider 예보 묶음 하나(W3). ``metrics``의 배열은 ``target_at``과 같은 길이다."""

    provider: str
    known_at: AwareDatetime
    published_at: AwareDatetime
    target_at: list[AwareDatetime] = Field(description="오름차순.")
    metrics: dict[str, list[MetricValue]]


class WeatherForecastState(_StateModel):
    """위치 하나의 한 style 예보(provider별 묶음)."""

    feature_id: str
    location_id: str
    forecast_style: WeatherForecastStyle
    groups: list[WeatherForecastGroupState]


class WeatherDailySlotState(_StateModel):
    """하루 한 구간 요약(W5). weather가 관측 기준으로 계산한 값을 그대로 담는다."""

    date: dt.date
    slot: DailySlot
    temp_min: float | None = None
    temp_max: float | None = None
    temp_avg: float | None = None
    humidity_avg: float | None = None
    precip_sum_mm: float | None = None
    precip_occurred: bool | None = None
    sky_code: int | None = None
    wind_speed_avg: float | None = None
    sample_count: int = Field(ge=0, le=6, description="채택된 관측 시간 bucket 수.")
    source_providers: list[str]
    partial: bool = Field(description="아직 끝나지 않은 구간.")


class WeatherDailySummaryState(_StateModel):
    """위치 하나의 최근 N일 세 구간 요약. ``(date, slot)`` 오름차순."""

    feature_id: str
    location_id: str
    slots: list[WeatherDailySlotState]
