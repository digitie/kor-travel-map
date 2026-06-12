"""``test_providers_kma_ultra_short_forecast`` — KMA 초단기예보 (PR#41)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from kortravelmap.dto import ForecastStyle, TimelineBucket, WeatherDomain
from kortravelmap.providers.kma import (
    KMA_METRIC_NAMES,
    KMA_METRIC_UNITS,
    ultra_short_forecast_to_weather_values,
)

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _UFItem:
    """``KmaUltraShortForecastItem`` Protocol 만족."""

    base_date: str
    base_time: str
    fcst_date: str
    fcst_time: str
    nx: int
    ny: int
    category: str
    fcst_value: str


# 서울 격자, 발표 23:00 → 24:00 예보 (30분 단위, 6시간 forward).
_BASE = {
    "base_date": "20260527",
    "base_time": "2330",
    "fcst_date": "20260528",
    "fcst_time": "0000",
    "nx": 60,
    "ny": 127,
}

_T1H = _UFItem(**_BASE, category="T1H", fcst_value="18.5")
_RN1 = _UFItem(**_BASE, category="RN1", fcst_value="강수없음")
_PTY = _UFItem(**_BASE, category="PTY", fcst_value="0")
_LGT = _UFItem(**_BASE, category="LGT", fcst_value="0")
_SKY = _UFItem(**_BASE, category="SKY", fcst_value="1")

_FEATURE_ID = "f_global_w_seoul"


@pytest.mark.unit
def test_returns_value_per_item() -> None:
    """N items → N values, 순서 유지."""
    values = ultra_short_forecast_to_weather_values(
        [_T1H, _RN1, _PTY, _LGT, _SKY], feature_id=_FEATURE_ID
    )
    assert len(values) == 5
    metric_keys = [v.metric_key for v in values]
    assert metric_keys == ["T1H", "RN1", "PTY", "LGT", "SKY"]


@pytest.mark.unit
def test_metadata_ultra_short() -> None:
    """domain/style/bucket — KMA_ULTRA_SHORT_FORECAST + ULTRA_SHORT."""
    [v] = ultra_short_forecast_to_weather_values([_T1H], feature_id=_FEATURE_ID)
    assert v.weather_domain == WeatherDomain.KMA_ULTRA_SHORT_FORECAST
    assert v.forecast_style == ForecastStyle.ULTRA_SHORT
    assert v.timeline_bucket == TimelineBucket.ULTRA_SHORT
    assert v.provider == "python-kma-api"


@pytest.mark.unit
def test_issued_at_and_valid_at_parsed() -> None:
    """초단기예보는 issued_at + valid_at 모두 채움 (nowcast와 다름)."""
    [v] = ultra_short_forecast_to_weather_values([_T1H], feature_id=_FEATURE_ID)
    assert v.issued_at == datetime(2026, 5, 27, 23, 30, tzinfo=KST)
    assert v.valid_at == datetime(2026, 5, 28, 0, 0, tzinfo=KST)
    assert v.observed_at is None  # 예보이므로 관측 시각 없음


@pytest.mark.unit
def test_value_and_metric_metadata() -> None:
    [v] = ultra_short_forecast_to_weather_values([_T1H], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("18.5")
    assert v.unit == KMA_METRIC_UNITS["T1H"]
    assert v.metric_name == KMA_METRIC_NAMES["T1H"]


@pytest.mark.unit
def test_lgt_recognized() -> None:
    """LGT (낙뢰)는 초단기예보 전용 — KMA_METRIC_UNITS/NAMES에 등록."""
    [v] = ultra_short_forecast_to_weather_values([_LGT], feature_id=_FEATURE_ID)
    assert v.unit == "code"
    assert v.metric_name == "낙뢰"


@pytest.mark.unit
def test_rain_text_absorbed() -> None:
    [v] = ultra_short_forecast_to_weather_values([_RN1], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("0")
    assert v.value_text == "강수없음"


@pytest.mark.unit
def test_payload_preserves_raw_fields() -> None:
    [v] = ultra_short_forecast_to_weather_values([_T1H], feature_id=_FEATURE_ID)
    assert v.payload["base_date"] == "20260527"
    assert v.payload["base_time"] == "2330"
    assert v.payload["fcst_date"] == "20260528"
    assert v.payload["fcst_time"] == "0000"
    assert v.payload["fcst_value"] == "18.5"


@pytest.mark.unit
def test_source_record_key_threaded() -> None:
    values = ultra_short_forecast_to_weather_values(
        [_T1H, _PTY],
        feature_id=_FEATURE_ID,
        source_record_key="sr_uf",
    )
    assert all(v.source_record_key == "sr_uf" for v in values)


@pytest.mark.unit
def test_empty_iterable() -> None:
    assert (
        ultra_short_forecast_to_weather_values([], feature_id=_FEATURE_ID) == []
    )


@pytest.mark.unit
def test_bad_datetime_length_raises() -> None:
    bad = _UFItem(
        base_date="bad",
        base_time="2330",
        fcst_date="20260528",
        fcst_time="0000",
        nx=60,
        ny=127,
        category="T1H",
        fcst_value="18.5",
    )
    with pytest.raises(ValueError, match="KMA datetime"):
        ultra_short_forecast_to_weather_values([bad], feature_id=_FEATURE_ID)
