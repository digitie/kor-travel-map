"""weather feature bbox summary의 provider 식별 PostGIS 통합 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo, weather_repo
from kortravelmap.providers.airkorea import (
    air_quality_stations_to_bundles,
    air_quality_to_weather_values,
)
from kortravelmap.providers.kma import (
    KMA_ULTRA_SHORT_GRID_DATASET_KEY,
    grid_to_weather_bundle,
    ultra_short_nowcast_to_weather_values,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=_KST)


@dataclass
class _AirKoreaStation:
    station_name: str = "중구"
    addr: str | None = "서울특별시 중구 덕수궁길 15"
    lat: float | None = 37.564
    lon: float | None = 126.975


@dataclass
class _AirKoreaMeasurement:
    station_name: str = "중구"
    data_time: datetime | None = _NOW
    sido_name: str | None = "서울"
    pm10_value: float | None = 42.0
    pm10_grade: int | None = 2
    pm25_value: float | None = 18.0
    pm25_grade: int | None = 1
    khai_value: int | None = None
    khai_grade: int | None = None
    o3_value: float | None = None
    o3_grade: int | None = None
    no2_value: float | None = None
    no2_grade: int | None = None
    so2_value: float | None = None
    so2_grade: int | None = None
    co_value: float | None = None
    co_grade: int | None = None


@dataclass
class _KmaNowcast:
    base_date: str = "20260713"
    base_time: str = "1200"
    nx: int = 60
    ny: int = 127
    category: str = "T1H"
    obsr_value: str = "27.5"


async def test_weather_summary_distinguishes_kma_and_airkorea_values(
    migrated_session: AsyncSession,
) -> None:
    """provider 변환값이 bbox→client cluster leaf까지 보존된다.

    UI mock이 아닌 실 provider 변환 ``WeatherValue``를 PostGIS에 적재한다.
    기존 DB의 generic marker도 summary provider로 구분할 수 있게 아이콘을
    의도적으로 ``marker``로 되돌려 검증한다.
    """
    kma = await grid_to_weather_bundle(
        60,
        127,
        37.5665,
        126.978,
        dataset_key=KMA_ULTRA_SHORT_GRID_DATASET_KEY,
        name_label="기상청 초단기",
        fetched_at=_NOW,
    )
    [airkorea] = await air_quality_stations_to_bundles(
        [_AirKoreaStation()],
        fetched_at=_NOW,
    )
    await feature_repo.load_bundles(migrated_session, [kma, airkorea])

    kma_values = ultra_short_nowcast_to_weather_values(
        [_KmaNowcast()],
        feature_id=kma.feature.feature_id,
        source_record_key=kma.source_record.source_record_key,
    )
    airkorea_values = air_quality_to_weather_values(
        [_AirKoreaMeasurement()],
        station_feature_ids={"중구::서울": airkorea.feature.feature_id},
        source_record_key=airkorea.source_record.source_record_key,
    )
    assert await weather_repo.load_weather_values(
        migrated_session, [*kma_values, *airkorea_values]
    ) == 3
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET marker_icon = 'marker' "
            "WHERE feature_id = ANY(CAST(:feature_ids AS text[]))"
        ),
        {"feature_ids": [kma.feature.feature_id, airkorea.feature.feature_id]},
    )

    for include_geometry in (False, True):
        rows = await feature_repo.features_in_bbox(
            migrated_session,
            min_lon=126.9,
            min_lat=37.5,
            max_lon=127.1,
            max_lat=37.7,
            kinds=["weather"],
            include_geometry=include_geometry,
        )
        by_id = {row["feature_id"]: row for row in rows}

        kma_summary = by_id[kma.feature.feature_id]["weather_summary"]
        assert kma_summary["provider"] == "python-kma-api"
        assert kma_summary["metric_key"] == "T1H"
        assert float(kma_summary["value_number"]) == 27.5

        airkorea_summary = by_id[airkorea.feature.feature_id]["weather_summary"]
        assert airkorea_summary["provider"] == "python-airkorea-api"
        assert airkorea_summary["metric_key"] == "PM10"
        assert float(airkorea_summary["value_number"]) == 42.0

        assert by_id[kma.feature.feature_id]["marker_icon"] == "marker"
        assert by_id[airkorea.feature.feature_id]["marker_icon"] == "marker"
