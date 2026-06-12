"""``test_core_weather`` — pure 헬퍼 (PR#39, ADR-010)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from kortravelmap.core.weather import (
    filter_by_provider,
    group_by_metric_key,
    latest_by_metric_key,
    pick_nowcast_value,
    pick_timeline_slice,
)
from kortravelmap.dto import (
    ForecastStyle,
    TimelineBucket,
    WeatherDomain,
    WeatherValue,
)

KST = timezone(timedelta(hours=9))

_FEATURE_ID = "f_global_w_seoul"


def _v(
    *,
    metric_key: str,
    domain: WeatherDomain = WeatherDomain.KMA_SHORT_FORECAST,
    style: ForecastStyle = ForecastStyle.SHORT,
    bucket: TimelineBucket | None = TimelineBucket.SHORT,
    value: str = "0",
    issued: datetime | None = None,
    valid: datetime | None = None,
    observed: datetime | None = None,
    collected: datetime | None = None,
    provider: str = "python-kma-api",
) -> WeatherValue:
    """fixture builder."""
    return WeatherValue(
        feature_id=_FEATURE_ID,
        provider=provider,
        weather_domain=domain,
        forecast_style=style,
        timeline_bucket=bucket,
        metric_key=metric_key,
        value_number=Decimal(value),
        issued_at=issued,
        valid_at=valid,
        observed_at=observed,
        collected_at=collected or datetime(2026, 5, 28, 2, 0, tzinfo=KST),
    )


# -- pick_nowcast_value -----------------------------------------------


@pytest.mark.unit
class TestPickNowcastValue:
    def test_picks_most_recent_observed(self) -> None:
        a = _v(
            metric_key="T1H",
            style=ForecastStyle.NOWCAST,
            bucket=TimelineBucket.ULTRA_SHORT,
            observed=datetime(2026, 5, 28, 0, 0, tzinfo=KST),
            value="17.0",
        )
        b = _v(
            metric_key="T1H",
            style=ForecastStyle.NOWCAST,
            bucket=TimelineBucket.ULTRA_SHORT,
            observed=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
            value="18.0",
        )
        picked = pick_nowcast_value([a, b], metric_key="T1H")
        assert picked is not None
        assert picked.value_number == Decimal("18.0")

    def test_filters_by_metric_key(self) -> None:
        t = _v(
            metric_key="T1H",
            style=ForecastStyle.NOWCAST,
            observed=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
            value="18.0",
        )
        r = _v(
            metric_key="REH",
            style=ForecastStyle.NOWCAST,
            observed=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
            value="65",
        )
        picked = pick_nowcast_value([t, r], metric_key="REH")
        assert picked is not None
        assert picked.metric_key == "REH"

    def test_skips_non_nowcast_observed_styles(self) -> None:
        """forecast style 일반 short는 미포함 — nowcast/observed만."""
        short = _v(
            metric_key="T1H",
            style=ForecastStyle.SHORT,
            valid=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
            value="20.0",
        )
        assert pick_nowcast_value([short], metric_key="T1H") is None

    def test_returns_none_when_no_match(self) -> None:
        assert pick_nowcast_value([], metric_key="T1H") is None

    def test_observed_style_eligible(self) -> None:
        """forest_mountain_weather etc — `observed` style도 nowcast picker 대상."""
        v = _v(
            metric_key="T1H",
            domain=WeatherDomain.FOREST_MOUNTAIN_WEATHER,
            style=ForecastStyle.OBSERVED,
            bucket=TimelineBucket.ULTRA_SHORT,
            observed=datetime(2026, 5, 28, 1, 30, tzinfo=KST),
            value="14.0",
            provider="python-krforest-api",
        )
        picked = pick_nowcast_value([v], metric_key="T1H")
        assert picked is not None
        assert picked.value_number == Decimal("14.0")


# -- pick_timeline_slice -----------------------------------------------


@pytest.mark.unit
class TestPickTimelineSlice:
    def test_sorted_by_valid_at_ascending(self) -> None:
        late = _v(
            metric_key="TMP",
            valid=datetime(2026, 5, 28, 12, 0, tzinfo=KST),
            value="25.0",
        )
        early = _v(
            metric_key="TMP",
            valid=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
            value="22.0",
        )
        result = pick_timeline_slice([late, early], bucket=TimelineBucket.SHORT)
        assert [v.value_number for v in result] == [Decimal("22.0"), Decimal("25.0")]

    def test_filters_by_bucket(self) -> None:
        short = _v(
            metric_key="TMP",
            bucket=TimelineBucket.SHORT,
            valid=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
            value="20.0",
        )
        mid = _v(
            metric_key="TMP",
            bucket=TimelineBucket.MID,
            valid=datetime(2026, 5, 29, 9, 0, tzinfo=KST),
            value="22.0",
        )
        result = pick_timeline_slice([short, mid], bucket=TimelineBucket.MID)
        assert len(result) == 1
        assert result[0].value_number == Decimal("22.0")

    def test_skips_valid_at_none(self) -> None:
        no_valid = _v(
            metric_key="TMP",
            bucket=TimelineBucket.SHORT,
            observed=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
            value="18.0",
        )
        result = pick_timeline_slice([no_valid], bucket=TimelineBucket.SHORT)
        assert result == []


# -- group_by_metric_key -----------------------------------------------


@pytest.mark.unit
def test_group_by_metric_key_preserves_input_order() -> None:
    a = _v(metric_key="TMP", valid=datetime(2026, 5, 28, 9, 0, tzinfo=KST), value="20.0")
    b = _v(metric_key="REH", valid=datetime(2026, 5, 28, 9, 0, tzinfo=KST), value="65")
    c = _v(metric_key="TMP", valid=datetime(2026, 5, 28, 12, 0, tzinfo=KST), value="22.0")
    grouped = group_by_metric_key([a, b, c])
    assert set(grouped.keys()) == {"TMP", "REH"}
    assert grouped["TMP"] == [a, c]  # 입력 순서 유지
    assert grouped["REH"] == [b]


# -- filter_by_provider -----------------------------------------------


@pytest.mark.unit
def test_filter_by_provider() -> None:
    kma = _v(
        metric_key="T1H",
        provider="python-kma-api",
        observed=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
        value="18.0",
    )
    forest = _v(
        metric_key="T1H",
        provider="python-krforest-api",
        domain=WeatherDomain.FOREST_MOUNTAIN_WEATHER,
        style=ForecastStyle.OBSERVED,
        bucket=TimelineBucket.ULTRA_SHORT,
        observed=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
        value="14.0",
    )
    only_kma = filter_by_provider([kma, forest], provider="python-kma-api")
    assert only_kma == [kma]


# -- latest_by_metric_key ---------------------------------------------


@pytest.mark.unit
class TestLatestByMetricKey:
    def test_prefers_observed_at_over_valid_at(self) -> None:
        observed = _v(
            metric_key="T1H",
            style=ForecastStyle.NOWCAST,
            bucket=TimelineBucket.ULTRA_SHORT,
            observed=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
            value="18.0",
        )
        forecasted = _v(
            metric_key="T1H",
            valid=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
            value="22.0",
        )
        result = latest_by_metric_key([observed, forecasted])
        # observed_at 우선 (forecasted는 observed_at None).
        assert result["T1H"] is observed

    def test_skips_when_both_observed_and_valid_none(self) -> None:
        ghost = _v(
            metric_key="T1H",
            style=ForecastStyle.ADVISORY,
            bucket=None,
            value="0",
        )
        result = latest_by_metric_key([ghost])
        assert result == {}

    def test_groups_distinct_metric_keys(self) -> None:
        a = _v(
            metric_key="T1H",
            valid=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
            value="18",
        )
        b = _v(
            metric_key="REH",
            valid=datetime(2026, 5, 28, 1, 0, tzinfo=KST),
            value="65",
        )
        result = latest_by_metric_key([a, b])
        assert set(result.keys()) == {"T1H", "REH"}
