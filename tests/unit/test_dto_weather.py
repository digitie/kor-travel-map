"""``test_dto_weather`` — WeatherValue DTO (PR#38, ADR-010)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from krtour.map.dto import (
    ForecastStyle,
    TimelineBucket,
    WeatherDomain,
    WeatherValue,
)

KST = timezone(timedelta(hours=9))


def _now() -> datetime:
    return datetime(2026, 5, 28, 1, 0, 0, tzinfo=KST)


# -- happy path -----------------------------------------------------------


@pytest.mark.unit
def test_kma_short_forecast_temperature_happy() -> None:
    """KMA 단기예보 TMP 1건."""
    issued = datetime(2026, 5, 27, 23, 0, tzinfo=KST)
    valid = datetime(2026, 5, 28, 9, 0, tzinfo=KST)
    v = WeatherValue(
        feature_id="f_global_w_abc",
        provider="python-kma-api",
        weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
        forecast_style=ForecastStyle.SHORT,
        timeline_bucket=TimelineBucket.SHORT,
        metric_key="TMP",
        metric_name="기온",
        value_number=Decimal("23.5"),
        unit="deg_c",
        issued_at=issued,
        valid_at=valid,
    )
    assert v.value_number == Decimal("23.5")
    assert v.unit == "deg_c"
    assert v.timeline_bucket == TimelineBucket.SHORT


@pytest.mark.unit
def test_observed_with_observed_at() -> None:
    """관측(observed) — `observed_at`만 채움."""
    v = WeatherValue(
        feature_id="f_global_w_obs",
        provider="python-krforest-api",
        weather_domain=WeatherDomain.FOREST_MOUNTAIN_WEATHER,
        forecast_style=ForecastStyle.OBSERVED,
        timeline_bucket=TimelineBucket.ULTRA_SHORT,
        metric_key="T1H",
        metric_name="현재 기온",
        value_number=Decimal("18.0"),
        unit="deg_c",
        observed_at=_now(),
    )
    assert v.observed_at == _now()
    assert v.issued_at is None
    assert v.valid_at is None


@pytest.mark.unit
def test_advisory_no_timeline_bucket() -> None:
    """특보 advisory — `timeline_bucket=None` 허용."""
    v = WeatherValue(
        feature_id="f_global_w_alert",
        provider="python-kma-api",
        weather_domain=WeatherDomain.KMA_WEATHER_ALERT,
        forecast_style=ForecastStyle.ADVISORY,
        timeline_bucket=None,
        metric_key="HEAVY_RAIN",
        value_text="호우주의보",
        severity="주의보",
        valid_from=_now(),
        valid_until=_now() + timedelta(hours=6),
    )
    assert v.timeline_bucket is None
    assert v.severity == "주의보"


# -- validator ---------------------------------------------------------


@pytest.mark.unit
def test_naive_datetime_rejected() -> None:
    """ADR-019 — naive datetime 거부."""
    naive = datetime(2026, 5, 27, 23, 0, 0)
    with pytest.raises(ValueError, match="aware"):
        WeatherValue(
            feature_id="f_global_w_abc",
            provider="python-kma-api",
            weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
            forecast_style=ForecastStyle.SHORT,
            metric_key="TMP",
            value_number=Decimal("23.5"),
            issued_at=naive,
        )


@pytest.mark.unit
def test_missing_value_rejected() -> None:
    """value_number와 value_text 모두 없으면 reject."""
    with pytest.raises(ValueError, match="value_number 또는 value_text"):
        WeatherValue(
            feature_id="f_global_w_abc",
            provider="python-kma-api",
            weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
            forecast_style=ForecastStyle.SHORT,
            metric_key="TMP",
            # value_number / value_text 둘 다 없음.
        )


@pytest.mark.unit
def test_text_only_value_ok() -> None:
    """value_text만 있어도 valid (예: PTY 코드는 텍스트 fallback)."""
    v = WeatherValue(
        feature_id="f_global_w_abc",
        provider="python-kma-api",
        weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
        forecast_style=ForecastStyle.SHORT,
        metric_key="PTY",
        value_text="1",  # 비
        unit="code",
    )
    assert v.value_text == "1"
    assert v.value_number is None


@pytest.mark.unit
def test_valid_range_order_rejected() -> None:
    """valid_until < valid_from은 reject."""
    with pytest.raises(ValueError, match="valid_until"):
        WeatherValue(
            feature_id="f_global_w_abc",
            provider="python-kma-api",
            weather_domain=WeatherDomain.KMA_WEATHER_ALERT,
            forecast_style=ForecastStyle.ADVISORY,
            metric_key="HEAVY_RAIN",
            value_text="호우주의보",
            valid_from=_now(),
            valid_until=_now() - timedelta(hours=1),  # 잘못된 순서
        )


@pytest.mark.unit
def test_extra_field_rejected() -> None:
    """ADR-018 — extra='forbid'."""
    with pytest.raises(ValueError, match="unknown"):
        WeatherValue(
            feature_id="f_global_w_abc",
            provider="python-kma-api",
            weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
            forecast_style=ForecastStyle.SHORT,
            metric_key="TMP",
            value_number=Decimal("23.5"),
            unknown_field="x",  # type: ignore[call-arg]
        )


# -- identity tuple ----------------------------------------------------


@pytest.mark.unit
def test_identity_tuple_excludes_timeline_bucket() -> None:
    """ADR-010 — timeline_bucket은 unique key에 미포함."""
    issued = datetime(2026, 5, 27, 23, 0, tzinfo=KST)
    valid = datetime(2026, 5, 28, 9, 0, tzinfo=KST)
    base_args: dict = {
        "feature_id": "f_global_w_abc",
        "provider": "python-kma-api",
        "weather_domain": WeatherDomain.KMA_SHORT_FORECAST,
        "forecast_style": ForecastStyle.SHORT,
        "metric_key": "TMP",
        "value_number": Decimal("23.5"),
        "issued_at": issued,
        "valid_at": valid,
    }
    a = WeatherValue(**base_args, timeline_bucket=TimelineBucket.SHORT)
    b = WeatherValue(**base_args, timeline_bucket=TimelineBucket.MID)
    # 다른 timeline_bucket이라도 identity는 동일.
    assert a.identity() == b.identity()


@pytest.mark.unit
def test_identity_differs_on_metric_key() -> None:
    """metric_key가 다르면 identity 다름."""
    issued = datetime(2026, 5, 27, 23, 0, tzinfo=KST)
    base_args: dict = {
        "feature_id": "f_global_w_abc",
        "provider": "python-kma-api",
        "weather_domain": WeatherDomain.KMA_SHORT_FORECAST,
        "forecast_style": ForecastStyle.SHORT,
        "value_number": Decimal("0"),
        "issued_at": issued,
    }
    a = WeatherValue(**base_args, metric_key="TMP")
    b = WeatherValue(**base_args, metric_key="REH")
    assert a.identity() != b.identity()


# -- collected_at default ---------------------------------------------


@pytest.mark.unit
def test_collected_at_default_is_kst_aware() -> None:
    """`collected_at` 기본값은 KST aware (ADR-019)."""
    v = WeatherValue(
        feature_id="f_global_w_abc",
        provider="python-kma-api",
        weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
        forecast_style=ForecastStyle.SHORT,
        metric_key="TMP",
        value_number=Decimal("23.5"),
    )
    assert v.collected_at.tzinfo is not None
