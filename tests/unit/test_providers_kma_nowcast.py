"""``test_providers_kma_nowcast`` — KMA 초단기실황 변환 (PR#39)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from krtour.map.dto import ForecastStyle, TimelineBucket, WeatherDomain
from krtour.map.providers.kma import (
    KMA_METRIC_NAMES,
    KMA_METRIC_UNITS,
    ultra_short_nowcast_to_weather_values,
)

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _NowItem:
    """``KmaUltraShortNowcastItem`` Protocol 만족."""

    base_date: str
    base_time: str
    nx: int
    ny: int
    category: str
    obsr_value: str


_BASE = {"base_date": "20260528", "base_time": "0100", "nx": 60, "ny": 127}

_T1H = _NowItem(**_BASE, category="T1H", obsr_value="18.0")
_REH = _NowItem(**_BASE, category="REH", obsr_value="65")
_WSD = _NowItem(**_BASE, category="WSD", obsr_value="2.1")
_RN1_NONE = _NowItem(**_BASE, category="RN1", obsr_value="강수없음")
_PTY = _NowItem(**_BASE, category="PTY", obsr_value="0")

_FEATURE_ID = "f_global_w_seoul"


@pytest.mark.unit
def test_nowcast_returns_value_per_item() -> None:
    values = ultra_short_nowcast_to_weather_values(
        [_T1H, _REH, _WSD, _RN1_NONE, _PTY], feature_id=_FEATURE_ID
    )
    assert len(values) == 5
    metric_keys = [v.metric_key for v in values]
    assert metric_keys == ["T1H", "REH", "WSD", "RN1", "PTY"]


@pytest.mark.unit
def test_nowcast_observed_at_matches_base_datetime() -> None:
    """관측 시각 = base_date + base_time. valid_at은 None."""
    [v] = ultra_short_nowcast_to_weather_values([_T1H], feature_id=_FEATURE_ID)
    assert v.observed_at == datetime(2026, 5, 28, 1, 0, tzinfo=KST)
    assert v.valid_at is None
    assert v.issued_at is None  # nowcast는 issued_at 미사용


@pytest.mark.unit
def test_nowcast_metadata() -> None:
    """domain/style/bucket 정합."""
    [v] = ultra_short_nowcast_to_weather_values([_T1H], feature_id=_FEATURE_ID)
    assert v.weather_domain == WeatherDomain.KMA_ULTRA_SHORT_NOWCAST
    assert v.forecast_style == ForecastStyle.NOWCAST
    assert v.timeline_bucket == TimelineBucket.ULTRA_SHORT
    assert v.provider == "python-kma-api"


@pytest.mark.unit
def test_nowcast_value_and_unit() -> None:
    [v] = ultra_short_nowcast_to_weather_values([_T1H], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("18.0")
    assert v.value_text is None
    assert v.unit == KMA_METRIC_UNITS["T1H"]
    assert v.metric_name == KMA_METRIC_NAMES["T1H"]


@pytest.mark.unit
def test_nowcast_rain_text_absorbed() -> None:
    """'강수없음' → 0 + text 보존."""
    [v] = ultra_short_nowcast_to_weather_values(
        [_RN1_NONE], feature_id=_FEATURE_ID
    )
    assert v.value_number == Decimal("0")
    assert v.value_text == "강수없음"


@pytest.mark.unit
def test_nowcast_payload_no_fcst_fields() -> None:
    """초단기실황 payload는 fcst_date/fcst_time 없음."""
    [v] = ultra_short_nowcast_to_weather_values([_T1H], feature_id=_FEATURE_ID)
    assert "fcst_date" not in v.payload
    assert "fcst_time" not in v.payload
    assert v.payload["obsr_value"] == "18.0"


@pytest.mark.unit
def test_nowcast_source_record_key_threaded() -> None:
    values = ultra_short_nowcast_to_weather_values(
        [_T1H, _REH], feature_id=_FEATURE_ID, source_record_key="sr_now"
    )
    assert all(v.source_record_key == "sr_now" for v in values)


@pytest.mark.unit
def test_nowcast_empty_iterable() -> None:
    assert (
        ultra_short_nowcast_to_weather_values([], feature_id=_FEATURE_ID) == []
    )
