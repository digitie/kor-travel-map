"""Dagster Feature ETL asset → 실제 PostGIS 적재 검증."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from dagster import AssetExecutionContext, build_asset_context
from kortravelmap.dagster.assets import (
    run_feature_event_datagokr_cultural_festivals,
    run_feature_event_krheritage_events,
    run_feature_geometry_knps_records,
    run_feature_notice_krex_traffic_notices,
    run_feature_place_knps_points,
    run_feature_place_krex_rest_areas,
    run_feature_place_krheritage_items,
    run_feature_place_mois_licenses,
    run_feature_place_opinet_stations,
    run_feature_weather_airkorea_air_quality,
)
from kortravelmap.dagster.etl import DagsterFeatureLoadResult
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.dto import Address, Coordinate

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 2, 12, 0, tzinfo=_KST)
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue RESTART IDENTITY CASCADE"
)


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 — provider 실모델 필드명 (#374)."""

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


@dataclass(frozen=True)
class _Station:
    uni_id: str
    name: str
    brand: object | None
    address_road: str | None
    address_jibun: str | None
    lon: float | None
    lat: float | None
    tel: str | None = None
    lpg_yn: str | bool | None = None


@dataclass(frozen=True)
class _RestArea:
    name: str
    route_name: str | None
    direction: str | None
    lat: float | None
    lon: float | None
    phone_number: str | None


@dataclass(frozen=True)
class _Notice:
    """`KrexTrafficNoticeItem` Protocol 준수 (provider ``krex.models.Incident``
    realTimeSms shape 정합, #378)."""

    occurred_date: str | None
    occurred_time: str | None
    incident_type: str | None
    incident_type_code: str | None
    direction: str | None
    message: str | None
    point_name: str | None
    route_no: str | None
    route_name: str | None
    process_status: str | None
    process_status_code: str | None
    latitude: float | None
    longitude: float | None
    congestion_length: float | None
    series_no: int | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class _HeritageKey:
    ccba_kdcd: str
    ccba_asno: str
    ccba_ctcd: str

    @property
    def natural_key(self) -> str:
        return f"{self.ccba_kdcd}-{self.ccba_asno}-{self.ccba_ctcd}"


@dataclass(frozen=True)
class _HeritageItem:
    key: _HeritageKey
    name_ko: str
    category: str | None = None
    region: str | None = None
    sigungu: str | None = None
    longitude: Decimal | float | None = None
    latitude: Decimal | float | None = None
    location_text: str | None = None
    designated_at: str | None = None
    manager: str | None = None
    image_url: str | None = None


@dataclass(frozen=True)
class _HeritageEvent:
    sn: str | None
    title: str | None
    starts_on: date | None = None
    ends_on: date | None = None
    place: str | None = None
    tel_name: str | None = None
    address: str | None = None
    longitude: Decimal | float | None = None
    latitude: Decimal | float | None = None
    main_image: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _MoisRecord:
    service_slug: str
    mng_no: str | None = "DAGSTER-MOIS-001"
    is_open: bool | None = True
    place_name: str | None = "덕수궁 전통찻집"
    category: str | None = None
    title: str | None = None
    opn_authority_code: str | None = None
    status_code: str | None = "01"
    status_name: str | None = "영업/정상"
    detail_status_code: str | None = None
    detail_status_name: str | None = None
    license_date: date | None = None
    telno: str | None = None
    road_address: str | None = "서울특별시 종로구 세종대로 1"
    lot_address: str | None = "서울특별시 종로구 세종로 1"
    road_zip: str | None = None
    lot_zip: str | None = None
    legal_dong_code: str | None = None
    road_name_code: str | None = None
    building_management_number: str | None = None
    lon: float | None = 126.9700
    lat: float | None = 37.5700
    source_x: float | None = None
    source_y: float | None = None
    business_type_name: str | None = None
    subtype_name: str | None = None
    multi_use_business_place_yn: str | None = None
    sanitation_business_status_name: str | None = None
    facility_total_scale: str | None = None
    water_supply_facility_type_name: str | None = None
    culture_sports_business_type_name: str | None = None
    sales_method_name: str | None = None
    designation_date: date | None = None
    building_usage_name: str | None = None
    ground_floor_count: int | None = None
    underground_floor_count: int | None = None
    total_floor_count: int | None = None
    facility_area: float | None = None
    total_area: float | None = None
    sickbed_count: int | None = None
    bed_count: int | None = None
    healthcare_worker_count: int | None = None
    hospital_room_count: int | None = None
    medical_institution_type_name: str | None = None
    medical_subject_names: str | None = None


@dataclass(frozen=True)
class _KnpsPoint:
    source_id: str
    name: str
    longitude: Decimal | None
    latitude: Decimal | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class _KnpsGeometry:
    source_id: str
    name: str
    geom_wkt: str
    raw: dict[str, Any]


class _ReverseGeocoder:
    async def __call__(self, coord: Coordinate) -> Address:
        lon = float(coord.lon)
        lat = float(coord.lat)
        if abs(lon - 126.9239) < 0.01 and abs(lat - 37.5263) < 0.01:
            return _address("1156010100", "11560", "11", "서울특별시", "영등포구")
        if abs(lon - 127.0376) < 0.01 and abs(lat - 37.4979) < 0.01:
            return _address("1168010100", "11680", "11", "서울특별시", "강남구")
        if abs(lon - 126.65) < 0.02 and abs(lat - 36.78) < 0.02:
            return _address("4421010100", "44210", "44", "충청남도", "서산시")
        if abs(lon - 129.35) < 0.02 and abs(lat - 35.80) < 0.02:
            return _address("4713010100", "47130", "47", "경상북도", "경주시")
        return _address("1111010100", "11110", "11", "서울특별시", "종로구")


@pytest.fixture
async def map_client(
    migrated_engine: Any,
) -> AsyncIterator[AsyncKorTravelMapClient]:
    client = AsyncKorTravelMapClient(migrated_engine)
    try:
        yield client
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text(_TRUNCATE_SQL))


async def test_dagster_assets_validate_coordinates_and_load_to_postgis(
    map_client: AsyncKorTravelMapClient,
    migrated_engine: Any,
) -> None:
    results = [
        await _run_asset(
            run_feature_event_datagokr_cultural_festivals,
            map_client,
            datagokr_cultural_festivals=[
                _Festival(
                    fstvl_nm="서울 봄꽃 축제",
                    opar="여의도공원",
                    fstvl_start_date=date(2026, 4, 5),
                    fstvl_end_date=date(2026, 4, 12),
                    fstvl_co="봄꽃 축제.",
                    mnnst_nm="영등포구청",
                    phone_number="02-2670-3114",
                    rdnmadr="서울특별시 영등포구 여의공원로 120",
                    lnmadr="서울특별시 영등포구 여의도동 8",
                    latitude=37.5263,
                    longitude=126.9239,
                    reference_date=date(2026, 3, 1),
                    instt_nm="서울특별시 영등포구",
                )
            ],
        ),
        await _run_asset(
            run_feature_place_opinet_stations,
            map_client,
            opinet_stations=[
                _Station(
                    uni_id="DAGSTER-OPINET-001",
                    name="SK주유소 강남점",
                    brand="SKE",
                    address_road="서울특별시 강남구 테헤란로 100",
                    address_jibun=None,
                    lon=127.0376,
                    lat=37.4979,
                    tel="02-1234-5678",
                    lpg_yn="Y",
                )
            ],
        ),
        await _run_asset(
            run_feature_place_krex_rest_areas,
            map_client,
            krex_rest_areas=[
                _RestArea(
                    name="서산휴게소",
                    route_name="서해안고속도로",
                    direction="부산방향",
                    lat=36.7800,
                    lon=126.6500,
                    phone_number="041-1234-5678",
                )
            ],
        ),
        await _run_asset(
            run_feature_notice_krex_traffic_notices,
            map_client,
            krex_traffic_notices=[
                _Notice(
                    occurred_date="2026.05.28",
                    occurred_time="05:00:00",
                    incident_type="공사",  # → roadwork
                    incident_type_code="3",
                    direction="부산방향",
                    message="서해안고속도로 105km 지점 도로공사",
                    point_name="서산나들목",
                    route_no="0150",
                    route_name="서해안고속도로",
                    process_status="진행",
                    process_status_code="1",
                    latitude=None,
                    longitude=None,
                    congestion_length=None,
                    series_no=1,
                    raw={
                        "accDate": "2026.05.28",
                        "accHour": "05:00:00",
                        "accType": "공사",
                        "smsText": "서해안고속도로 105km 지점 도로공사",
                        "nosunNM": "0150",
                        "roadNM": "서해안고속도로",
                    },
                )
            ],
        ),
        await _run_asset(
            run_feature_place_krheritage_items,
            map_client,
            krheritage_items=[
                _HeritageItem(
                    key=_HeritageKey(
                        ccba_kdcd="11",
                        ccba_asno="DAGSTER001",
                        ccba_ctcd="37",
                    ),
                    name_ko="석굴암 석굴",
                    category="전통사찰",
                    longitude=Decimal("129.349"),
                    latitude=Decimal("35.795"),
                    location_text="경상북도 경주시 진현동",
                    designated_at="19621220",
                    manager="불국사",
                )
            ],
        ),
        await _run_asset(
            run_feature_event_krheritage_events,
            map_client,
            krheritage_events=[
                _HeritageEvent(
                    sn="DAGSTER-HERITAGE-EVENT-001",
                    title="경주 전통문화 행사",
                    starts_on=date(2026, 9, 1),
                    ends_on=date(2026, 9, 2),
                    place="경주 문화마당",
                    address="경상북도 경주시 교동",
                    longitude=Decimal("129.350"),
                    latitude=Decimal("35.796"),
                )
            ],
        ),
        await _run_asset(
            run_feature_place_mois_licenses,
            map_client,
            mois_license_records=[_MoisRecord(service_slug="general_restaurants")],
        ),
        await _run_asset(
            run_feature_place_knps_points,
            map_client,
            knps_point_records=[
                _KnpsPoint(
                    source_id="DAGSTER-KNPS-POINT-001",
                    name="북한산 탐방지원센터",
                    longitude=Decimal("126.9876"),
                    latitude=Decimal("37.6584"),
                    raw={"MNG_NO": "DAGSTER-KNPS-POINT-001"},
                )
            ],
            knps_point_dataset_key="knps_visitor_centers",
        ),
        await _run_asset(
            run_feature_geometry_knps_records,
            map_client,
            knps_geometry_records=[
                _KnpsGeometry(
                    source_id="DAGSTER-KNPS-GEOM-001",
                    name="북한산 둘레길",
                    geom_wkt="LINESTRING(126.98 37.65, 126.99 37.66, 127.0 37.67)",
                    raw={"NO": "DAGSTER-KNPS-GEOM-001"},
                )
            ],
            knps_geometry_dataset_key="knps_trails",
        ),
    ]

    assert all(result.load.features_inserted == 1 for result in results)
    assert all(not result.address_validation.has_errors for result in results)
    feature_ids = [feature_id for result in results for feature_id in result.feature_ids]
    assert len(feature_ids) == 9

    # krex 교통 공지는 provider Incident에 좌표가 없어 coordless로 적재된다
    # (ADR-044) — 좌표/행정코드 보강 단언에서 제외하고 별도로 검증한다.
    notice_feature_ids = set(results[3].feature_ids)

    for feature_id in feature_ids:
        row = await map_client.get_feature(feature_id)
        assert row is not None
        if feature_id in notice_feature_ids:
            # coordless notice: 좌표·법정동코드 없이 적재됨.
            assert row["coord_5179_srid"] is None
            assert row["legal_dong_code"] is None
            continue
        assert row["coord_5179_srid"] == 5179
        assert row["legal_dong_code"] is not None
        assert row["sigungu_code"] is not None

    async with AsyncSession(migrated_engine) as session:
        feature_count = await session.scalar(text("SELECT count(*) FROM feature.features"))
        source_count = await session.scalar(
            text("SELECT count(*) FROM provider_sync.source_records")
        )
    assert feature_count == 9
    assert source_count == 9


async def _run_asset(
    runner: Callable[[AssetExecutionContext], Awaitable[DagsterFeatureLoadResult]],
    client: AsyncKorTravelMapClient,
    **resources: object,
) -> DagsterFeatureLoadResult:
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": _ReverseGeocoder(),
            "fetched_at": _FETCHED,
            **resources,
        }
    )
    return await runner(context)


@dataclass(frozen=True)
class _AirStation:
    station_name: str
    addr: str | None
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class _AirMeasurement:
    station_name: str
    sido_name: str | None
    data_time: datetime
    pm10_value: float | None = None
    pm10_grade: int | None = None
    khai_value: int | None = None
    khai_grade: int | None = None
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


async def test_airkorea_asset_distinct_features_for_same_station_name(
    map_client: AsyncKorTravelMapClient,
    migrated_engine: Any,
) -> None:
    """동명 측정소(서울/대구 ``중구``)가 asset join에서 별개 feature로 분리(#301)."""
    stations = [
        _AirStation("중구", "서울 중구 덕수궁길 15", 37.5640, 126.9750),
        _AirStation("중구", "대구광역시 중구 공평로 88", 35.8690, 128.5940),
    ]
    measurements = [
        _AirMeasurement("중구", "서울", _FETCHED, pm10_value=40.0, pm10_grade=2),
        _AirMeasurement("중구", "대구", _FETCHED, pm10_value=85.0, pm10_grade=3),
    ]
    context = build_asset_context(
        resources={
            "kor_travel_map_client": map_client,
            "reverse_geocoder": _ReverseGeocoder(),
            "fetched_at": _FETCHED,
            "airkorea_stations": stations,
            "airkorea_air_quality": measurements,
        }
    )
    result = await run_feature_weather_airkorea_air_quality(context)
    assert result.stations.features_inserted == 2  # 두 측정소 별개.
    assert result.weather_values == 2  # 각 PM10 1개.

    async with AsyncSession(migrated_engine) as session:
        # 두 측정값이 서로 다른 feature_id에 붙고, 값이 뒤섞이지 않았는지.
        rows = (
            await session.execute(
                text(
                    "SELECT v.feature_id, v.value_number "
                    "FROM feature.feature_weather_values AS v "
                    "WHERE v.weather_domain = 'air_quality' AND v.metric_key = 'PM10'"
                )
            )
        ).all()
    assert len(rows) == 2
    by_feature = {fid: float(val) for fid, val in rows}
    assert len(by_feature) == 2  # 서로 다른 feature 2개.
    assert sorted(by_feature.values()) == [40.0, 85.0]


def _address(
    bjd_code: str,
    sigungu_code: str,
    sido_code: str,
    sido_name: str,
    sigungu_name: str,
) -> Address:
    return Address(
        legal=f"{sido_name} {sigungu_name}",
        bjd_code=bjd_code,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        sido_name=sido_name,
        sigungu_name=sigungu_name,
    )
