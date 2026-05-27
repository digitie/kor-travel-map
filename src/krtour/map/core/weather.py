"""``krtour.map.core.weather`` — 날씨 시계열 pure 헬퍼.

`docs/weather-feature-normalization.md §6` 의 `build_weather_card` 패턴 중
**DB 없이 동작하는 pure 함수만** 본 모듈에 둔다. async `build_weather_card
(client, feature_id)` (DB fetch가 필요한)은 `infra/feature_repo.py` 진입 후
`client.py`에서 합성.

ADR 참조
--------
- ADR-001 — core는 dto만 import (본 모듈은 외부 의존 X)
- ADR-010 — `forecast_style` vs `timeline_bucket` 두 축 분리

본 모듈의 함수는 모두 ``list[WeatherValue]``를 받아 정렬/필터/group_by한다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from krtour.map.dto import ForecastStyle, TimelineBucket, WeatherValue

__all__ = [
    "pick_nowcast_value",
    "pick_timeline_slice",
    "group_by_metric_key",
    "filter_by_provider",
    "latest_by_metric_key",
]


# ── 시점값 (nowcast) 선택 ──────────────────────────────────────────────


def pick_nowcast_value(
    values: Iterable[WeatherValue], *, metric_key: str
) -> WeatherValue | None:
    """관측(`forecast_style=nowcast` 또는 `observed`) 중 가장 최근 ``observed_at``.

    Parameters
    ----------
    values
        ``WeatherValue`` iterable. 같은 ``feature_id``일 필요는 없음 (호출자
        책임).
    metric_key
        ``"T1H"``/``"PM10"`` 등 표준 metric.

    Returns
    -------
    WeatherValue | None
        매칭되는 row 중 ``observed_at`` 가장 최근. 없으면 ``None``.

    Notes
    -----
    `observed_at`이 None인 row는 무시. 동시각 row가 있으면 ``collected_at``이
    가장 최근인 것을 선호 (provider가 같은 시각을 늦게 재공시한 경우).
    """
    candidates = [
        v
        for v in values
        if v.metric_key == metric_key
        and v.observed_at is not None
        and v.forecast_style in {ForecastStyle.NOWCAST, ForecastStyle.OBSERVED}
    ]
    if not candidates:
        return None

    def _sort_key(value: WeatherValue) -> tuple[str, str]:
        # observed_at은 위 filter에서 None을 제거했으므로 항상 datetime.
        assert value.observed_at is not None
        return (value.observed_at.isoformat(), value.collected_at.isoformat())

    return max(candidates, key=_sort_key)


# ── timeline bucket 분할 ──────────────────────────────────────────────


def pick_timeline_slice(
    values: Iterable[WeatherValue],
    *,
    bucket: TimelineBucket,
) -> list[WeatherValue]:
    """timeline_bucket 일치 row만 추출 + ``valid_at`` 오름차순 정렬.

    Parameters
    ----------
    values
        ``WeatherValue`` iterable.
    bucket
        ``TimelineBucket`` enum 또는 동등 string.

    Returns
    -------
    list[WeatherValue]
        ``valid_at`` 오름차순. ``valid_at=None`` row는 결과에서 제외 (시간축
        모호 — frontend 표시 어려움).
    """
    def _by_valid_at(value: WeatherValue) -> str:
        # 위 filter에서 valid_at None을 제거했으므로 항상 datetime.
        assert value.valid_at is not None
        return value.valid_at.isoformat()

    return sorted(
        (
            v
            for v in values
            if v.timeline_bucket == bucket and v.valid_at is not None
        ),
        key=_by_valid_at,
    )


# ── group_by / 편의 ──────────────────────────────────────────────────


def group_by_metric_key(
    values: Iterable[WeatherValue],
) -> dict[str, list[WeatherValue]]:
    """`metric_key`로 group_by + 원래 순서 유지.

    같은 metric_key 안의 row 순서는 입력 순서 그대로 (안정 정렬). 정렬이 필요
    하면 호출자가 추가로 정렬.
    """
    grouped: dict[str, list[WeatherValue]] = defaultdict(list)
    for v in values:
        grouped[v.metric_key].append(v)
    return dict(grouped)


def filter_by_provider(
    values: Iterable[WeatherValue], *, provider: str
) -> list[WeatherValue]:
    """canonical provider name이 일치하는 row만. 입력 순서 유지."""
    return [v for v in values if v.provider == provider]


def latest_by_metric_key(
    values: Iterable[WeatherValue],
) -> dict[str, WeatherValue]:
    """metric별 가장 최근 row만 추림.

    "최근" 기준 우선순위:
    1) `observed_at`이 가장 큰 row
    2) 동률 시 `valid_at` 가장 큰 row
    3) 그래도 동률이면 `collected_at` 가장 큰 row

    `observed_at`/`valid_at` 모두 None인 row는 후보에서 제외.
    """

    def _sort_key(v: WeatherValue) -> tuple[bool, str, str, str]:
        # tie-breaker 없이 키 비교가 None 섞이면 깨지므로 datetime → ISO 문자열
        # 변환 후 비교 (또는 빈 문자열 fallback).
        obs = v.observed_at.isoformat() if v.observed_at is not None else ""
        val = v.valid_at.isoformat() if v.valid_at is not None else ""
        col = v.collected_at.isoformat()
        return (bool(v.observed_at), obs, val, col)

    result: dict[str, WeatherValue] = {}
    for v in values:
        if v.observed_at is None and v.valid_at is None:
            continue
        current = result.get(v.metric_key)
        if current is None or _sort_key(v) > _sort_key(current):
            result[v.metric_key] = v
    return result
