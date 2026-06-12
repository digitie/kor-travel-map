"""``test_providers_kma`` — KMA 단기예보 변환 (PR#38)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from kortravelmap.dto import ForecastStyle, TimelineBucket, WeatherDomain
from kortravelmap.providers.kma import (
    KMA_METRIC_NAMES,
    KMA_METRIC_UNITS,
    KmaMidRegionSpec,
    parse_mid_region_features,
    parse_weather_extra_points,
    short_forecast_to_weather_values,
)

KST = timezone(timedelta(hours=9))


# -- parse_weather_extra_points (T-219a) -----------------------------------


def test_parse_weather_extra_points_none_and_empty() -> None:
    assert parse_weather_extra_points(None) == []
    assert parse_weather_extra_points("") == []
    assert parse_weather_extra_points("  ;  ") == []


def test_parse_weather_extra_points_multiple_with_spaces() -> None:
    assert parse_weather_extra_points("126.978, 37.5665 ; 129.075,35.1796") == [
        (126.978, 37.5665),
        (129.075, 35.1796),
    ]


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("126.978", "lon,lat"),  # lat 누락
        ("126.978,37.5665,9", "lon,lat"),  # 조각 3개
        ("abc,37.5", "숫자 변환 실패"),  # 비숫자
        ("10.0,37.5", "bbox"),  # 한국 bbox 밖 (lon)
        ("126.978,50.0", "bbox"),  # 한국 bbox 밖 (lat)
    ],
)
def test_parse_weather_extra_points_rejects_invalid(value: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_weather_extra_points(value)


# -- parse_mid_region_features (T-219c) -------------------------------------


def test_parse_mid_region_features_none_and_empty() -> None:
    assert parse_mid_region_features(None) == ()
    assert parse_mid_region_features("  ") == ()


def test_parse_mid_region_features_valid_specs() -> None:
    specs = parse_mid_region_features(
        '[{"land_reg_id": " 11B00000 ", "ta_reg_id": "11B10101",'
        ' "feature_ids": ["f1", " f2 "]}]'
    )
    assert specs == (
        KmaMidRegionSpec(
            land_reg_id="11B00000",
            ta_reg_id="11B10101",
            feature_ids=("f1", "f2"),
        ),
    )


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("{not json", "JSON 파싱 실패"),
        ('{"land_reg_id": "x"}', "배열"),
        ('["x"]', "객체"),
        ('[{"ta_reg_id": "a", "feature_ids": ["f"]}]', "land_reg_id"),
        ('[{"land_reg_id": "a", "feature_ids": ["f"]}]', "ta_reg_id"),
        ('[{"land_reg_id": "a", "ta_reg_id": "b", "feature_ids": []}]', "feature_ids"),
        (
            '[{"land_reg_id": "a", "ta_reg_id": "b", "feature_ids": ["f"]},'
            ' {"land_reg_id": "a", "ta_reg_id": "b", "feature_ids": ["g"]}]',
            "중복",
        ),
    ],
)
def test_parse_mid_region_features_rejects_invalid(value: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_mid_region_features(value)


@dataclass(frozen=True)
class _Item:
    """``KmaShortForecastItem`` Protocol 만족 dataclass."""

    base_date: str
    base_time: str
    fcst_date: str
    fcst_time: str
    nx: int
    ny: int
    category: str
    fcst_value: str


# 서울(60,127) 격자, 발표 23:00 → 익일 09:00 예보.
_BASE = {
    "base_date": "20260527",
    "base_time": "2300",
    "fcst_date": "20260528",
    "fcst_time": "0900",
    "nx": 60,
    "ny": 127,
}

_TMP = _Item(**_BASE, category="TMP", fcst_value="23.5")
_REH = _Item(**_BASE, category="REH", fcst_value="65")
_WSD = _Item(**_BASE, category="WSD", fcst_value="2.1")
_PTY_RAIN = _Item(**_BASE, category="PTY", fcst_value="1")
_SKY = _Item(**_BASE, category="SKY", fcst_value="3")
_RN1_NONE = _Item(**_BASE, category="RN1", fcst_value="강수없음")
_RN1_BELOW = _Item(**_BASE, category="RN1", fcst_value="1mm 미만")
_SNO = _Item(**_BASE, category="SNO", fcst_value="0.5")


_FEATURE_ID = "f_global_w_seoul"


# -- 핵심 흐름 ----------------------------------------------------------


@pytest.mark.unit
def test_returns_value_per_item_in_order() -> None:
    """N items → N values, 순서 유지."""
    items = [_TMP, _REH, _WSD, _PTY_RAIN, _SKY, _RN1_NONE, _RN1_BELOW, _SNO]
    values = short_forecast_to_weather_values(items, feature_id=_FEATURE_ID)
    assert len(values) == 8
    metric_keys = [v.metric_key for v in values]
    assert metric_keys == [
        "TMP", "REH", "WSD", "PTY", "SKY", "RN1", "RN1", "SNO",
    ]


@pytest.mark.unit
def test_temperature_value_decoded() -> None:
    """TMP — Decimal 변환 + unit/metric_name 매핑."""
    [v] = short_forecast_to_weather_values([_TMP], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("23.5")
    assert v.value_text is None
    assert v.unit == KMA_METRIC_UNITS["TMP"] == "deg_c"
    assert v.metric_name == KMA_METRIC_NAMES["TMP"] == "기온"


@pytest.mark.unit
def test_rain_text_zero_value() -> None:
    """RN1 '강수없음' → value_number=0 + value_text 보존."""
    [v] = short_forecast_to_weather_values([_RN1_NONE], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("0")
    assert v.value_text == "강수없음"


@pytest.mark.unit
def test_rain_text_below_threshold() -> None:
    """RN1 '1mm 미만' → 보수적으로 0 + 원문 보존."""
    [v] = short_forecast_to_weather_values([_RN1_BELOW], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("0")
    assert v.value_text == "1mm 미만"


@pytest.mark.unit
def test_pty_code_value() -> None:
    """PTY '1' (비) — Decimal '1' (숫자 변환 가능)."""
    [v] = short_forecast_to_weather_values([_PTY_RAIN], feature_id=_FEATURE_ID)
    # PTY 문자열 "1"은 Decimal 변환 성공 → value_number=1, value_text=None.
    # 운영상 텍스트 의미가 더 중요하나, schema는 숫자도 허용.
    assert v.value_number == Decimal("1")
    assert v.unit == "code"


@pytest.mark.unit
def test_datetime_parsed_to_kst_aware() -> None:
    """KMA datetime → ADR-019 KST aware."""
    [v] = short_forecast_to_weather_values([_TMP], feature_id=_FEATURE_ID)
    assert v.issued_at is not None
    assert v.issued_at.tzinfo is not None
    assert v.issued_at == datetime(2026, 5, 27, 23, 0, tzinfo=KST)
    assert v.valid_at == datetime(2026, 5, 28, 9, 0, tzinfo=KST)


@pytest.mark.unit
def test_forecast_metadata_fields() -> None:
    """forecast_style/timeline_bucket/weather_domain — KMA 단기예보 정합."""
    [v] = short_forecast_to_weather_values([_TMP], feature_id=_FEATURE_ID)
    assert v.weather_domain == WeatherDomain.KMA_SHORT_FORECAST
    assert v.forecast_style == ForecastStyle.SHORT
    assert v.timeline_bucket == TimelineBucket.SHORT
    assert v.provider == "python-kma-api"  # canonical (ADR-024)
    assert v.normalization_version == "kma-v1.0"
    assert v.feature_id == _FEATURE_ID


@pytest.mark.unit
def test_source_record_key_threaded() -> None:
    """source_record_key 전달 시 모든 결과에 박힘."""
    values = short_forecast_to_weather_values(
        [_TMP, _REH], feature_id=_FEATURE_ID, source_record_key="sr_demo"
    )
    assert all(v.source_record_key == "sr_demo" for v in values)


@pytest.mark.unit
def test_source_record_key_default_none() -> None:
    """source_record_key 미전달 시 None."""
    [v] = short_forecast_to_weather_values([_TMP], feature_id=_FEATURE_ID)
    assert v.source_record_key is None


@pytest.mark.unit
def test_payload_preserves_raw_fields() -> None:
    """payload에 raw fields 전부 보존."""
    [v] = short_forecast_to_weather_values([_TMP], feature_id=_FEATURE_ID)
    assert v.payload == {
        "base_date": "20260527",
        "base_time": "2300",
        "fcst_date": "20260528",
        "fcst_time": "0900",
        "nx": 60,
        "ny": 127,
        "category": "TMP",
        "fcst_value": "23.5",
    }


# -- 에러 경로 ---------------------------------------------------------


@pytest.mark.unit
def test_bad_datetime_length_raises() -> None:
    """date_str 길이 위반은 ValueError."""
    bad = _Item(
        base_date="2026527",  # 7자리 (8자리여야)
        base_time="2300",
        fcst_date="20260528",
        fcst_time="0900",
        nx=60,
        ny=127,
        category="TMP",
        fcst_value="23.5",
    )
    with pytest.raises(ValueError, match="KMA datetime 형식"):
        short_forecast_to_weather_values([bad], feature_id=_FEATURE_ID)


@pytest.mark.unit
def test_empty_iterable_returns_empty_list() -> None:
    """빈 input → 빈 결과."""
    assert short_forecast_to_weather_values([], feature_id=_FEATURE_ID) == []
