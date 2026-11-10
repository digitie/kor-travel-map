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
- 예보는 증분(``since``)을 지금 세대에 병합할 수 있다(:func:`merge_forecast_delta`, ADR-122). 병합
  결과는 같은 시각의 전량과 같은 값이어야 한다 — 그래서 위치 안 묶음은 provider 순으로 둔다.
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
    "ForecastDeltaRefused",
    "ForecastGrouper",
    "ForecastMerge",
    "WeatherStateDataset",
    "earliest_or_none",
    "location_state",
    "location_state_items",
    "merge_forecast_delta",
    "trim_forecast_group",
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
    reports_source_status: bool = True
    """원천이 이 집합의 수집 상태를 실제로 알리는가. W1 위치 roster는 언제나 ``stale``·
    ``source_collected_at=null``을 보낸다(카탈로그 수집 시각을 알 수 없다) — 그 값을 그대로
    내보내면 소비자가 모든 위치를 stale로 표시한다. 그래서 응답 신선도의 ``source_status``를
    null(해당 없음)로 둔다(ADR-114 W4)."""


DATASET_LOCATIONS: Final = WeatherStateDataset(
    name="weather.locations",
    guard=ShrinkGuard(min_ratio=0.9, baseline_min=100, min_count=1_000),
    max_age=timedelta(days=8),
    reports_source_status=False,
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
    # 하한은 실측으로 정한다(ADR-114 "켜기 전 live 개수와 대조"). 2026-11-02 운영: 단기예보 한 회차
    # (기상청 격자 300개 상한)의 attempt 218개가 공개된 시점에 위치 273곳(airkorea 126·krforest 90·
    # krex 39·khoa 11·kma 7), 완결 추정 약 340~375곳이다. 1,000이면 완결된 회차도 "53건 < 1000"처럼
    # 매번 교체를 거부해 한 번도 적재되지 않았다. 포화된 odroid에서는 한 회차 격자의 1/3 가까이가
    # artifact 쓰기·증명 실패로 빠지므로 절대 하한은 완결 추정의 약 2/3(250곳)이고, 비율도 같은 몫
    # (65%)이라 완결 회차(375곳) 뒤의 그런 회차(약 250곳)도 받는다. 소수만 온 깨진 집합(53곳)은
    # 거부한다.
    guard=ShrinkGuard(min_ratio=0.65, baseline_min=100, min_count=250),
    max_age=timedelta(hours=12),
    style="short",
)
DATASET_FORECAST_MID: Final = WeatherStateDataset(
    name="weather.forecast_mid",
    # 중기예보는 weather가 중기 지역 코드를 단 target에만 낸다(2026-11-02 운영 21곳:
    # 서울·인천·수원·춘천·원주·강릉·대전·세종·청주·광주·목포·여수·전주·대구·안동·포항·
    # 부산·울산·창원·제주·서귀포). 하한 300곳이면 완결된 집합도 "21건 < 300"으로 매번
    # 거부된다. 절대 하한은 그 2/3(14곳)이다. baseline_min도 그 아래라야 비율 검사(80%)가
    # 작동한다.
    guard=ShrinkGuard(min_ratio=0.8, baseline_min=10, min_count=14),
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
    """W1 위치들 → 상태 항목(GEO 포함). 같은 위치의 중복은 store가 첫 행을 남긴다.

    보조 키 표(``lookup``)에 weather ``location_id`` → ``feature_id``를 싣는다 — 소비자(PinVi)가
    이미 가진 weather 위치 id로 찾을 수 있게(ADR-114 W7).
    """
    return [
        to_state_item(location_state(location), lookup_keys=(location.location_id,))
        for location in locations
    ]


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
        bucket[group.provider] = _group_state(group)

    def items(self) -> list[StateItem]:
        return [
            _forecast_item(self.style, location_id, groups)
            for location_id, groups in self._groups.items()
        ]


def _group_state(group: WeatherExportForecastGroup) -> WeatherForecastGroupState:
    return WeatherForecastGroupState(
        provider=group.provider,
        known_at=group.known_at,
        published_at=group.published_at,
        target_at=list(group.target_at),
        metrics={name: list(values) for name, values in group.metrics.items()},
    )


def _forecast_item(
    style: WeatherForecastStyle, location_id: str, groups: dict[str, WeatherForecastGroupState]
) -> StateItem:
    """위치 하나의 값. 묶음은 **provider 순**이다 — 원천 페이지 순서(weather scope namespace 순)에
    기대지 않아야 증분 병합(:func:`merge_forecast_delta`)과 전량이 같은 바이트가 된다(ADR-122)."""
    return to_state_item(
        WeatherForecastState(
            feature_id=weather_location_feature_id(location_id),
            location_id=location_id,
            forecast_style=style,
            groups=[groups[provider] for provider in sorted(groups)],
        )
    )


# -- 예보 증분 병합 (ADR-122) ------------------------------------------------------------


class ForecastDeltaRefused(ValueError):
    """이 증분은 지금 세대에 병합해도 전량과 같아진다고 보장할 수 없다 — 전량으로 다시 받는다.

    ``reason``은 op metadata ``resync_reason``에 그대로 남는 짧은 code다.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ForecastMerge:
    """증분 병합 결과와 그 내역(op metadata)."""

    items: list[StateItem]
    delta_rows: int
    """증분 응답의 묶음 수."""
    replaced: int
    """지금 세대의 묶음을 증분이 바꾼 수."""
    added: int
    """증분으로 새로 생긴 (위치, provider) 묶음 수."""
    carried: int
    """증분에 없어 지금 세대에서 이어 온 묶음 수(잘린 것 포함, 빠진 것 제외)."""
    trimmed: int
    """이어 온 묶음 중 지난 ``target_at``을 뗀 수."""
    expired: int
    """이어 온 묶음 중 남는 시각이 없어 뺀 수(weather 전량도 그 묶음을 내지 않는다)."""


def trim_forecast_group(
    group: WeatherForecastGroupState, now: datetime
) -> WeatherForecastGroupState | None:
    """weather가 ``now``에 같은 승인 묶음을 다시 낸다면 낼 값. 남는 시각이 없으면 ``None``.

    weather W3는 ``target_at > now``인 point만 내고, metric은 그 미래 point가 있을 때만 싣는다
    (``export_forecasts._page_items``). 그래서 시각을 뗀 뒤 값이 모두 null인 metric은 뺀다 — 원래
    값 배열의 null은 "point 없음"이기 때문이다. 시각을 하나도 떼지 않았으면 묶음을 그대로 둔다.
    ``known_at``은 지난 point까지 포함한 최댓값이라 바뀌지 않는다.
    """
    keep = [index for index, target in enumerate(group.target_at) if target > now]
    if len(keep) == len(group.target_at):
        return group
    if not keep:
        return None
    metrics: dict[str, list[float | str | None]] = {}
    for name, values in group.metrics.items():
        kept = [values[i] for i in keep]
        if any(value is not None for value in kept):
            metrics[name] = kept
    return group.model_copy(
        update={"target_at": [group.target_at[i] for i in keep], "metrics": metrics}
    )


def merge_forecast_delta(
    base: Iterable[WeatherForecastState],
    delta: Iterable[WeatherExportForecastGroup],
    *,
    style: WeatherForecastStyle,
    since: datetime,
    now: datetime,
) -> ForecastMerge:
    """지금 세대(``base``) + weather ``since`` 증분 → 새 세대 값(ADR-122).

    weather 계약: ``since`` 응답은 ``published_at > since``인 승인 scope의 (위치, provider) 묶음을
    **통째로** 다시 낸다. 그래서 증분에 온 묶음은 지금 세대의 같은 (위치, provider) 묶음을 그대로
    바꾸고, 오지 않은 묶음은 weather가 ``now``에 낼 모양으로 지난 시각을 뗀다
    (:func:`trim_forecast_group`). 다음 경우는 전량과 같아진다고 보장할 수 없어
    :class:`ForecastDeltaRefused`로 거절한다(호출자는 전량으로 다시 받는다):

    - 증분 안에 같은 (위치, provider)가 두 번 온다(전량의 "첫 행" 선택을 재현할 수 없다).
    - 증분 묶음의 ``published_at``이 ``since`` 이하다(계약 위반).
    - 증분 묶음이 지금 세대의 같은 묶음보다 오래됐다(publication clock 역행).
    - 지금 세대 값이 다른 style이거나 ``feature_id``가 위치 id와 맞지 않는다.

    weather가 since 응답에 싣지 않는 제거(위치가 scope에서 빠짐·승인 만료·provider 퇴역)는 여기서
    볼 수 없다 — 주기 전량 재동기화가 고친다.
    """
    incoming: dict[str, dict[str, WeatherExportForecastGroup]] = {}
    rows = 0
    for group in delta:
        rows += 1
        if group.forecast_style != style:
            raise ForecastDeltaRefused(
                "delta_style_mismatch", f"증분 묶음 style {group.forecast_style!r} ≠ {style!r}."
            )
        if group.published_at <= since:
            raise ForecastDeltaRefused(
                "delta_not_after_since",
                f"증분 묶음 {group.location_id}/{group.provider}의 published_at"
                f"({group.published_at.isoformat()})이 since({since.isoformat()}) 이하다.",
            )
        bucket = incoming.setdefault(group.location_id, {})
        if group.provider in bucket:
            raise ForecastDeltaRefused(
                "delta_duplicates",
                f"증분에 {group.location_id}/{group.provider} 묶음이 두 번 왔다.",
            )
        bucket[group.provider] = group

    merged: dict[str, dict[str, WeatherForecastGroupState]] = {}
    replaced = carried = trimmed = expired = 0
    for state in base:
        if state.forecast_style != style or state.feature_id != weather_location_feature_id(
            state.location_id
        ):
            raise ForecastDeltaRefused(
                "base_mismatch",
                f"지금 세대 값 {state.feature_id}가 style {style!r}·위치 id와 맞지 않는다.",
            )
        if state.location_id in merged:
            raise ForecastDeltaRefused(
                "base_mismatch", f"지금 세대에 위치 {state.location_id}가 두 번 있다."
            )
        fresh = incoming.get(state.location_id, {})
        kept_groups = merged[state.location_id] = {}
        for stored in state.groups:
            if stored.provider in kept_groups:
                raise ForecastDeltaRefused(
                    "base_mismatch",
                    f"지금 세대 위치 {state.location_id}에 {stored.provider} 묶음이 두 번 있다.",
                )
            update = fresh.get(stored.provider)
            if update is not None:
                if update.published_at < stored.published_at:
                    raise ForecastDeltaRefused(
                        "published_at_regressed",
                        f"증분 {state.location_id}/{stored.provider}이 지금 세대보다 오래됐다"
                        f"({update.published_at.isoformat()} < "
                        f"{stored.published_at.isoformat()}).",
                    )
                replaced += 1
                continue
            kept = trim_forecast_group(stored, now)
            if kept is None:
                expired += 1
                continue
            carried += 1
            if kept is not stored:
                trimmed += 1
            kept_groups[stored.provider] = kept

    for location_id, rows_by_provider in incoming.items():
        target = merged.setdefault(location_id, {})
        for provider, row in rows_by_provider.items():
            target[provider] = _group_state(row)
    added = sum(len(groups) for groups in incoming.values()) - replaced

    return ForecastMerge(
        items=[
            _forecast_item(style, location_id, groups)
            for location_id, groups in sorted(merged.items())
            if groups
        ],
        delta_rows=rows,
        replaced=replaced,
        added=added,
        carried=carried,
        trimmed=trimmed,
        expired=expired,
    )


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
