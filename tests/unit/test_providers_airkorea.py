"""``test_providers_airkorea`` — 대기질 측정소/측정값 정규화 (T-RV-55d)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.dto import (
    Address,
    Coordinate,
    FeatureBundle,
    FeatureKind,
    ForecastStyle,
    SourceRole,
    WeatherDomain,
)
from krtour.map.providers.airkorea import (
    AIR_QUALITY_MARKER_COLOR,
    AIR_QUALITY_STATION_CATEGORY,
    AIRKOREA_NORMALIZATION_VERSION,
    air_quality_to_weather_values,
)
from krtour.map.providers.airkorea import (
    air_quality_stations_to_bundles as _stations_async,
)

KST = timezone(timedelta(hours=9))


def stations_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_stations_async(items, **kwargs))


@dataclass(frozen=True)
class _Station:
    station_name: str
    addr: str | None
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class _Measurement:
    station_name: str
    data_time: datetime | None
    sido_name: str | None = "서울"
    khai_value: int | None = None
    khai_grade: int | None = None
    pm10_value: float | None = None
    pm10_grade: int | None = None
    pm25_value: float | None = None
    pm25_grade: int | None = None
    o3_value: float | None = None
    o3_grade: int | None = None
    no2_value: float | None = None
    no2_grade: int | None = None
    so2_value: float | None = None
    so2_grade: int | None = None
    co_value: float | None = None
    co_grade: int | None = None


_S1 = _Station(
    station_name="중구",
    addr="서울 중구 덕수궁길 15",
    lat=37.5640,
    lon=126.9750,
)


def _now() -> datetime:
    return datetime(2026, 6, 8, 12, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_station_is_weather_kind_without_detail() -> None:
    bundle = stations_to_bundles([_S1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.WEATHER
    assert feature.name == "중구"
    assert feature.category == AIR_QUALITY_STATION_CATEGORY  # 99000000
    assert feature.marker_color == AIR_QUALITY_MARKER_COLOR
    assert feature.detail is None  # weather kind는 detail 불가.
    assert feature.coord is not None
    # composite 안정키: station_name::<sido(addr 첫 토큰)>.
    assert bundle.source_record.source_entity_id == "중구::서울"
    assert bundle.source_record.source_entity_type == "air_quality_station"
    assert bundle.source_link.source_role == SourceRole.PRIMARY


@pytest.mark.unit
def test_station_reverse_geocoder_fills_bjd() -> None:
    async def _rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="1114000000", sigungu_code="11140", sido_code="11")

    bundle = stations_to_bundles([_S1], fetched_at=_now(), reverse_geocoder=_rg)[0]
    assert bundle.feature.address.bjd_code == "1114000000"
    # weather kind → feature_id의 kind[0] = 'w'.
    assert bundle.feature.feature_id.startswith("f_1114000000_w_")


@pytest.mark.unit
def test_air_quality_values_expand_per_pollutant() -> None:
    measurement = _Measurement(
        station_name="중구",
        data_time=datetime(2026, 6, 8, 11, 0, tzinfo=KST),
        khai_value=75,
        khai_grade=2,
        pm10_value=45.0,
        pm10_grade=2,
        pm25_value=18.0,
        pm25_grade=1,
        o3_value=0.035,
        o3_grade=2,
    )
    values = air_quality_to_weather_values(
        [measurement],
        station_feature_ids={"중구::서울": "f_1114000000_w_abc"},
        source_record_key="sr_air",
    )
    # 4 오염물질 (PM10/PM2_5/O3/CAI) — 결측(NO2/SO2/CO)은 제외.
    metric_keys = {v.metric_key for v in values}
    assert metric_keys == {"PM10", "PM2_5", "O3", "CAI"}
    by_key = {v.metric_key: v for v in values}
    assert by_key["PM10"].weather_domain == WeatherDomain.AIR_QUALITY
    assert by_key["PM10"].forecast_style == ForecastStyle.OBSERVED
    assert by_key["PM10"].timeline_bucket is None
    assert by_key["PM10"].unit == "μg/m³"
    assert by_key["PM10"].value_number == Decimal("45.0")
    assert by_key["PM10"].severity == "보통"  # grade 2
    assert by_key["PM2_5"].severity == "좋음"  # grade 1
    assert by_key["O3"].unit == "ppm"
    assert by_key["CAI"].unit == "score"
    assert by_key["CAI"].value_number == Decimal("75")
    # 관측 시각 + 정규화 버전.
    assert by_key["PM10"].observed_at == datetime(2026, 6, 8, 11, 0, tzinfo=KST)
    assert by_key["PM10"].normalization_version == AIRKOREA_NORMALIZATION_VERSION
    assert by_key["PM10"].feature_id == "f_1114000000_w_abc"


@pytest.mark.unit
def test_air_quality_naive_data_time_made_kst_aware() -> None:
    measurement = _Measurement(
        station_name="중구",
        data_time=datetime(2026, 6, 8, 11, 0),  # naive
        pm10_value=30.0,
    )
    [value] = air_quality_to_weather_values(
        [measurement], station_feature_ids={"중구::서울": "f_x_w_1"}
    )
    assert value.observed_at is not None
    assert value.observed_at.tzinfo is not None
    assert value.observed_at.utcoffset() == timedelta(hours=9)


@pytest.mark.unit
def test_air_quality_unmapped_station_skipped() -> None:
    measurement = _Measurement(
        station_name="없는측정소",
        data_time=_now(),
        pm10_value=30.0,
    )
    values = air_quality_to_weather_values(
        [measurement], station_feature_ids={"중구::서울": "f_x_w_1"}
    )
    assert values == []


@pytest.mark.unit
def test_air_quality_all_missing_yields_nothing() -> None:
    measurement = _Measurement(station_name="중구", data_time=_now())
    values = air_quality_to_weather_values(
        [measurement], station_feature_ids={"중구::서울": "f_x_w_1"}
    )
    assert values == []


@pytest.mark.unit
def test_same_station_name_in_different_sido_are_distinct() -> None:
    """``중구`` 측정소가 서울/대구에 둘 다 있어도 별개 feature + 정확한 join(#300)."""
    seoul = _Station(station_name="중구", addr="서울 중구 덕수궁길 15", lat=37.564, lon=126.975)
    daegu = _Station(station_name="중구", addr="대구광역시 중구 공평로 88", lat=35.869, lon=128.594)
    bundles = stations_to_bundles([seoul, daegu], fetched_at=_now())

    ids = {b.source_record.source_entity_id for b in bundles}
    assert ids == {"중구::서울", "중구::대구"}
    # feature_id도 서로 다르다(같은 이름이 한 feature로 접히지 않음).
    assert bundles[0].feature.feature_id != bundles[1].feature.feature_id

    station_map = {
        b.source_record.source_entity_id: b.feature.feature_id for b in bundles
    }
    measurements = [
        _Measurement(
            station_name="중구", sido_name="서울", data_time=_now(), pm10_value=45.0
        ),
        _Measurement(
            station_name="중구", sido_name="대구", data_time=_now(), pm10_value=80.0
        ),
    ]
    values = air_quality_to_weather_values(
        measurements, station_feature_ids=station_map
    )
    by_feature = {v.feature_id: v.value_number for v in values}
    # 서울 중구 45 / 대구 중구 80 — 각자 올바른 feature에 붙는다.
    assert by_feature[station_map["중구::서울"]] == Decimal("45.0")
    assert by_feature[station_map["중구::대구"]] == Decimal("80.0")
