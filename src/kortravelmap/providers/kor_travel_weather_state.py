"""``kortravelmap.providers.kor_travel_weather_state`` — weather export → Valkey 상태 값
(ADR-114 2단계).

``providers.kor_travel_weather``가 엄격히 읽은 W1·W2·W3·W5 항목을 ``dto.weather_state`` 값과
:class:`~kortravelmap.infra.valkey_state.StateItem`으로 바꾼다. HTTP는 Dagster fetcher가, 저장은
``infra.valkey_state``가 한다 — 이 모듈은 변환과 데이터셋 정의(이름·교체 거부 기준·신선도 상한)만
갖는다. 설계 정본은 ADR-114 "구현 설계 — 2단계" W1·W2·W4.

- **값 하나 = 위치 하나**다. 일곱 데이터셋이 같은 ``feature_id``
  (:func:`weather_location_feature_id`)를 키로 쓴다. W2·W3·W5의 행은 위치 단위로 묶는다
  (:class:`CurrentGrouper`·:class:`ForecastGrouper`·:class:`DailySummaryGrouper`).
- 같은 위치 안에서 같은 관측(provider, metric)·예보 묶음(provider)·요약(date, slot)이 두 번 오면
  원천 순서의 첫 행을 남기고 버린 수를 센다(적재 op metadata ``row_duplicates``).
- geo를 부르지 않는다. 법정동 코드는 weather W1 값을 그대로 쓴다(결정 6).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from kortravelmap.core.ids import make_feature_id
from kortravelmap.dto import FeatureKind
from kortravelmap.dto.weather_state import (
    WeatherCurrentState,
    WeatherDailySlotState,
    WeatherDailySummaryState,
    WeatherForecastGroupState,
    WeatherForecastState,
    WeatherForecastStyle,
    WeatherLocationAddress,
    WeatherLocationState,
    WeatherObservationState,
)
from kortravelmap.infra.valkey_state import ShrinkGuard, StateItem
from kortravelmap.providers.kor_travel_transport_state import state_coordinate, to_state_item
from kortravelmap.providers.kor_travel_weather import (
    KOR_TRAVEL_WEATHER_PROVIDER_NAME,
    WeatherExportCurrentValue,
    WeatherExportDailySummary,
    WeatherExportForecastGroup,
    WeatherExportLocation,
)

__all__ = [
    "DATASET_CURRENT",
    "DATASET_DAILY_SUMMARIES",
    "DATASET_FORECAST_EXTERNAL",
    "DATASET_FORECAST_MID",
    "DATASET_FORECAST_SHORT",
    "DATASET_FORECAST_ULTRA_SHORT",
    "DATASET_LOCATIONS",
    "FORECAST_DATASETS",
    "WEATHER_LOCATION_CATEGORY",
    "WEATHER_LOCATION_MARKER_COLOR",
    "WEATHER_LOCATION_MARKER_ICON",
    "WEATHER_STATE_DATASETS",
    "DailySummaryGrouper",
    "CurrentGrouper",
    "ForecastGrouper",
    "WeatherStateDataset",
    "earliest_or_none",
    "location_state",
    "location_state_items",
    "weather_location_feature_id",
]

WEATHER_LOCATION_CATEGORY: Final[str] = "99000000"
"""weather kind의 category sentinel — ADR-105 전 KMA 격자 weather feature와 같은 값."""
WEATHER_LOCATION_MARKER_ICON: Final[str] = "weather"
WEATHER_LOCATION_MARKER_COLOR: Final[str] = "P-01"
_SOURCE_TYPE: Final[str] = f"{KOR_TRAVEL_WEATHER_PROVIDER_NAME}:locations"


@dataclass(frozen=True, slots=True)
class WeatherStateDataset:
    """Valkey weather 상태 데이터셋 하나의 정의(ADR-114 W1)."""

    name: str
    guard: ShrinkGuard
    max_age: timedelta
    style: WeatherForecastStyle | None = None
    """예보 데이터셋이면 weather W3 ``style``."""


DATASET_LOCATIONS: Final = WeatherStateDataset(
    name="weather.locations",
    guard=ShrinkGuard(min_ratio=0.9, baseline_min=100, min_count=1_000),
    max_age=timedelta(days=8),
)
DATASET_CURRENT: Final = WeatherStateDataset(
    name="weather.current",
    guard=ShrinkGuard(min_ratio=0.8, baseline_min=50, min_count=500),
    max_age=timedelta(hours=3),
)
DATASET_FORECAST_ULTRA_SHORT: Final = WeatherStateDataset(
    name="weather.forecast_ultra_short",
    guard=ShrinkGuard(min_ratio=0.8, baseline_min=50, min_count=500),
    max_age=timedelta(hours=3),
    style="ultra_short",
)
DATASET_FORECAST_SHORT: Final = WeatherStateDataset(
    name="weather.forecast_short",
    guard=ShrinkGuard(min_ratio=0.9, baseline_min=100, min_count=1_000),
    max_age=timedelta(hours=12),
    style="short",
)
DATASET_FORECAST_MID: Final = WeatherStateDataset(
    name="weather.forecast_mid",
    guard=ShrinkGuard(min_ratio=0.8, baseline_min=50, min_count=300),
    max_age=timedelta(hours=36),
    style="mid",
)
DATASET_FORECAST_EXTERNAL: Final = WeatherStateDataset(
    name="weather.forecast_external",
    guard=ShrinkGuard(min_ratio=0.8, baseline_min=50, allow_empty_below_baseline=True),
    max_age=timedelta(hours=12),
    style="external",
)
DATASET_DAILY_SUMMARIES: Final = WeatherStateDataset(
    name="weather.daily_summaries",
    guard=ShrinkGuard(min_ratio=0.9, baseline_min=100, min_count=1_000),
    max_age=timedelta(hours=6),
)

FORECAST_DATASETS: Final[tuple[WeatherStateDataset, ...]] = (
    DATASET_FORECAST_ULTRA_SHORT,
    DATASET_FORECAST_SHORT,
    DATASET_FORECAST_MID,
    DATASET_FORECAST_EXTERNAL,
)

WEATHER_STATE_DATASETS: Final[tuple[WeatherStateDataset, ...]] = (
    DATASET_LOCATIONS,
    DATASET_CURRENT,
    *FORECAST_DATASETS,
    DATASET_DAILY_SUMMARIES,
)


def weather_location_feature_id(location_id: str) -> str:
    """weather 위치의 ``feature_id``. ``bjd_code=None`` — 법정동이 바뀌어도 id는 그대로다(W1)."""
    return make_feature_id(
        bjd_code=None,
        kind=FeatureKind.WEATHER.value,
        category=WEATHER_LOCATION_CATEGORY,
        source_type=_SOURCE_TYPE,
        source_natural_key=location_id,
    )


def location_state(location: WeatherExportLocation) -> WeatherLocationState:
    """W1 위치 → 값. 좌표는 한국 주변 범위만 받는다(1단계 D1과 같은 규칙)."""
    return WeatherLocationState(
        feature_id=weather_location_feature_id(location.location_id),
        category=WEATHER_LOCATION_CATEGORY,
        marker_icon=WEATHER_LOCATION_MARKER_ICON,
        marker_color=WEATHER_LOCATION_MARKER_COLOR,
        location_id=location.location_id,
        name=location.name.strip() or location.location_id,
        coord=state_coordinate(location.longitude, location.latitude),
        address=WeatherLocationAddress(
            sido_name=location.sido_name,
            sigungu_name=location.sigungu_name,
            bjd_code=location.legal_dong_code,
        ),
    )


def location_state_items(locations: Iterable[WeatherExportLocation]) -> list[StateItem]:
    """W1 위치들 → 상태 항목(GEO 포함). 같은 위치의 중복은 store가 첫 행을 남긴다."""
    return [to_state_item(location_state(location)) for location in locations]


@dataclass
class CurrentGrouper:
    """W2 행을 위치별 :class:`WeatherCurrentState`로 묶는다."""

    duplicates: int = 0
    _rows: dict[str, dict[tuple[str, str], WeatherObservationState]] = field(
        default_factory=dict
    )

    def add(self, row: WeatherExportCurrentValue) -> None:
        bucket = self._rows.setdefault(row.location_id, {})
        key = (row.provider, row.metric_key)
        if key in bucket:
            self.duplicates += 1
            return
        bucket[key] = WeatherObservationState(
            provider=row.provider,
            metric_key=row.metric_key,
            value=row.value,
            unit=row.unit,
            target_at=row.target_at,
            known_at=row.known_at,
            forecast_style=row.forecast_style,
        )

    def items(self) -> list[StateItem]:
        return [
            to_state_item(
                WeatherCurrentState(
                    feature_id=weather_location_feature_id(location_id),
                    location_id=location_id,
                    observations=list(rows.values()),
                )
            )
            for location_id, rows in self._rows.items()
        ]


@dataclass
class ForecastGrouper:
    """W3 묶음을 위치별 :class:`WeatherForecastState`로 묶는다(provider당 묶음 하나)."""

    style: WeatherForecastStyle
    duplicates: int = 0
    _groups: dict[str, dict[str, WeatherForecastGroupState]] = field(default_factory=dict)

    def add(self, group: WeatherExportForecastGroup) -> None:
        bucket = self._groups.setdefault(group.location_id, {})
        if group.provider in bucket:
            self.duplicates += 1
            return
        bucket[group.provider] = WeatherForecastGroupState(
            provider=group.provider,
            known_at=group.known_at,
            published_at=group.published_at,
            target_at=list(group.target_at),
            metrics={name: list(values) for name, values in group.metrics.items()},
        )

    def items(self) -> list[StateItem]:
        return [
            to_state_item(
                WeatherForecastState(
                    feature_id=weather_location_feature_id(location_id),
                    location_id=location_id,
                    forecast_style=self.style,
                    groups=list(groups.values()),
                )
            )
            for location_id, groups in self._groups.items()
        ]


_SLOT_ORDER: Final[dict[str, int]] = {"morning": 0, "noon": 1, "evening": 2}


@dataclass
class DailySummaryGrouper:
    """W5 행을 위치별 :class:`WeatherDailySummaryState`로 묶는다(``(date, slot)`` 오름차순)."""

    duplicates: int = 0
    _slots: dict[str, dict[tuple[object, str], WeatherDailySlotState]] = field(
        default_factory=dict
    )

    def add(self, row: WeatherExportDailySummary) -> None:
        bucket = self._slots.setdefault(row.location_id, {})
        key = (row.date, row.slot)
        if key in bucket:
            self.duplicates += 1
            return
        bucket[key] = WeatherDailySlotState(
            date=row.date,
            slot=row.slot,
            temp_min=row.temp_min,
            temp_max=row.temp_max,
            temp_avg=row.temp_avg,
            humidity_avg=row.humidity_avg,
            precip_sum_mm=row.precip_sum_mm,
            precip_occurred=row.precip_occurred,
            sky_code=row.sky_code,
            wind_speed_avg=row.wind_speed_avg,
            sample_count=row.sample_count,
            source_providers=list(row.source_providers),
            partial=row.partial,
        )

    def items(self) -> list[StateItem]:
        return [
            to_state_item(
                WeatherDailySummaryState(
                    feature_id=weather_location_feature_id(location_id),
                    location_id=location_id,
                    slots=sorted(
                        slots.values(), key=lambda s: (s.date, _SLOT_ORDER[s.slot])
                    ),
                )
            )
            for location_id, slots in self._slots.items()
        ]


def earliest_or_none(values: Iterable[datetime | None]) -> datetime | None:
    """페이지들의 원천 수집 시각 집계 — 하나라도 ``None``이면 ``None``, 아니면 가장 이른 값(W4)."""
    seen: list[datetime] = []
    for value in values:
        if value is None:
            return None
        seen.append(value)
    return min(seen) if seen else None
