"""Dagster Feature ETL asset → 실제 PostGIS 적재 검증."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from dagster import AssetExecutionContext, build_asset_context
from krtour.map_dagster.assets import (
    run_feature_event_datagokr_cultural_festivals,
    run_feature_event_krheritage_events,
    run_feature_geometry_knps_records,
    run_feature_notice_krex_traffic_notices,
    run_feature_place_knps_points,
    run_feature_place_krex_rest_areas,
    run_feature_place_krheritage_items,
    run_feature_place_mois_licenses,
    run_feature_place_opinet_stations,
)
from krtour.map_dagster.etl import DagsterFeatureLoadResult
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map.client import AsyncKrtourMapClient
from krtour.map.dto import Address, Coordinate

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 2, 12, 0, tzinfo=_KST)
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue RESTART IDENTITY CASCADE"
)


@dataclass(frozen=True)
class _Festival:
    management_no: str
    festival_name: str
    venue_name: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    road_address: str | None
    jibun_address: str | None
    organizer_name: str | None
    organizer_tel: str | None
    data_reference_date: date | None
    provider_org_name: str | None


@dataclass(frozen=True)
class _Station:
    uni_id: str
    station_name: str
    brand_code: str | None
    address: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    tel: str | None
    lpg_yn: str | bool | None


@dataclass(frozen=True)
class _RestArea:
    uni_id: str
    name: str
    direction: str | None
    highway_name: str | None
    address: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    tel: str | None


@dataclass(frozen=True)
class _Notice:
    notice_id: str
    title: str
    notice_type: str
    description: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    valid_from: datetime | None
    valid_until: datetime | None
    severity: int | None
    source_agency: str | None


@dataclass(frozen=True)
class _HeritageItem:
    ccba_kdcd: str
    ccba_asno: str
    ccba_ctcd: str
    name: str
    heritage_type: str | None = None
    longitude: Decimal | float | None = None
    latitude: Decimal | float | None = None
    location_text: str | None = None
    designated_date: date | None = None
    manager: str | None = None
    geom_wkt: str | None = None
    image_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _HeritageEvent:
    sn: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    venue_name: str | None = None
    tel: str | None = None
    location_text: str | None = None
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
) -> AsyncIterator[AsyncKrtourMapClient]:
    client = AsyncKrtourMapClient(migrated_engine)
    try:
        yield client
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text(_TRUNCATE_SQL))


async def test_dagster_assets_validate_coordinates_and_load_to_postgis(
    map_client: AsyncKrtourMapClient,
    migrated_engine: Any,
) -> None:
    results = [
        await _run_asset(
            run_feature_event_datagokr_cultural_festivals,
            map_client,
            datagokr_cultural_festivals=[
                _Festival(
                    management_no="DAGSTER-FEST-001",
                    festival_name="서울 봄꽃 축제",
                    venue_name="여의도공원",
                    start_date=date(2026, 4, 5),
                    end_date=date(2026, 4, 12),
                    description="봄꽃 축제.",
                    latitude=Decimal("37.5263"),
                    longitude=Decimal("126.9239"),
                    road_address="서울특별시 영등포구 여의공원로 120",
                    jibun_address="서울특별시 영등포구 여의도동 8",
                    organizer_name="영등포구청",
                    organizer_tel="02-2670-3114",
                    data_reference_date=date(2026, 3, 1),
                    provider_org_name="서울특별시 영등포구",
                )
            ],
        ),
        await _run_asset(
            run_feature_place_opinet_stations,
            map_client,
            opinet_stations=[
                _Station(
                    uni_id="DAGSTER-OPINET-001",
                    station_name="SK주유소 강남점",
                    brand_code="SKE",
                    address="서울특별시 강남구 테헤란로 100",
                    longitude=Decimal("127.0376"),
                    latitude=Decimal("37.4979"),
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
                    uni_id="DAGSTER-KREX-RA-001",
                    name="서산휴게소",
                    direction="부산방향",
                    highway_name="서해안고속도로",
                    address="충청남도 서산시 운산면 서해로 100",
                    longitude=Decimal("126.6500"),
                    latitude=Decimal("36.7800"),
                    tel="041-1234-5678",
                )
            ],
        ),
        await _run_asset(
            run_feature_notice_krex_traffic_notices,
            map_client,
            krex_traffic_notices=[
                _Notice(
                    notice_id="DAGSTER-KREX-NOTICE-001",
                    title="서해안고속도로 105km 지점 도로공사",
                    notice_type="roadwork",
                    description="야간 차로 변경.",
                    longitude=Decimal("126.6500"),
                    latitude=Decimal("36.7800"),
                    valid_from=_FETCHED,
                    valid_until=_FETCHED + timedelta(days=1),
                    severity=2,
                    source_agency="한국도로공사",
                )
            ],
        ),
        await _run_asset(
            run_feature_place_krheritage_items,
            map_client,
            krheritage_items=[
                _HeritageItem(
                    ccba_kdcd="11",
                    ccba_asno="DAGSTER001",
                    ccba_ctcd="37",
                    name="석굴암 석굴",
                    heritage_type="전통사찰",
                    longitude=Decimal("129.349"),
                    latitude=Decimal("35.795"),
                    location_text="경상북도 경주시 진현동",
                    designated_date=date(1962, 12, 20),
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
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 9, 2),
                    venue_name="경주 문화마당",
                    location_text="경상북도 경주시 교동",
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

    for feature_id in feature_ids:
        row = await map_client.get_feature(feature_id)
        assert row is not None
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
    client: AsyncKrtourMapClient,
    **resources: object,
) -> DagsterFeatureLoadResult:
    context = build_asset_context(
        resources={
            "krtour_map_client": client,
            "reverse_geocoder": _ReverseGeocoder(),
            "fetched_at": _FETCHED,
            **resources,
        }
    )
    return await runner(context)


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
