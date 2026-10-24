"""Dagster Feature ETL asset → 실제 PostGIS 적재 검증."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
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
    run_feature_place_knps_points,
    run_feature_place_krheritage_items,
    run_feature_place_mois_licenses,
    run_feature_place_transport_fuel_stations,
    run_feature_place_transport_rest_areas,
)
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
)
from kortravelmap.dagster.mois_chunked_load import resolve_mois_load_plan
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.dto import Address, Coordinate
from kortravelmap.providers.feature_operation_registry import (
    FEATURE_OPERATION_HANDLERS,
)
from kortravelmap.settings import KorTravelMapSettings
from tests.integration._db_cleanup import truncate_committed_test_rows

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 2, 12, 0, tzinfo=_KST)
# ``source_entities``를 빼면 안 된다. record만 지우면 entity가 링크 없이 남아
# 정합성 검사 F1(orphan source_entity)이 **다른 테스트에서** 켜진다 — 이 파일은
# commit하므로 남는 행이 세션 전역에 보인다. 실측: 이 목록에 entity가 없어
# `test_consistency_reports` 9건이 단독 실행에선 통과하고 전체 실행에선 실패했다.
# (heads는 record CASCADE로 함께 지워지지만 명시해 의도를 남긴다.)
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_entities, "
    "provider_sync.source_entity_heads, provider_sync.source_records, "
    "provider_sync.source_links, provider_sync.provider_sync_state, "
    "provider_sync.notice_lifecycle_scopes, "
    "provider_sync.notice_lineage_states, "
    "ops.dedup_review_queue RESTART IDENTITY CASCADE"
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


_KST_TZ = timezone(timedelta(hours=9))


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
    owner: str | None = None
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
            await truncate_committed_test_rows(session, _TRUNCATE_SQL)


async def _canonical_ids(
    engine: Any, legacy_feature_ids: Sequence[str]
) -> dict[str, str]:
    """legacy ``f_*`` → 적재가 발급한 정본 키(uuid text) 매핑.

    T-VN-39 재키(alembic 309) 뒤 ``feature.features.feature_id``는 서버가 발급하는
    UUIDv7이다. asset이 metadata로 돌려주는 ``feature_ids``는 provider 변환기가
    유도한 legacy 주소이고(그 바깥 이름과 값은 재키가 건드리지 않는다), DB 행을
    가리키거나 read 응답과 비교할 때는 ``feature_aliases``에서 한 번 정본 키로
    바꾼다 — 그 등록부가 legacy 문자열에서 정본 키로 가는 유일한 입구다
    (ADR-098 결정 6).
    """
    wanted = list(dict.fromkeys(legacy_feature_ids))
    async with AsyncSession(engine) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT a.alias, CAST(a.feature_id AS text) AS feature_id "
                    "FROM feature.feature_aliases AS a "
                    "WHERE a.alias_kind = 'legacy_feature_id' "
                    "  AND a.alias = ANY(CAST(:aliases AS text[]))"
                ),
                {"aliases": wanted},
            )
        ).all()
    mapping = {str(row.alias): str(row.feature_id) for row in rows}
    missing = [alias for alias in wanted if alias not in mapping]
    assert not missing, (
        f"legacy 주소 {missing!r}가 정본 키로 해석되지 않았다 — provider 적재 "
        "경로가 alias를 남기지 않았거나 Feature가 적재되지 않았다."
    )
    return mapping


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
            run_feature_place_transport_fuel_stations,
            map_client,
            transport_fuel_stations=[
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
            run_feature_place_transport_rest_areas,
            map_client,
            transport_rest_areas=[
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
                    owner="불국사",
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
            # 운영 기본 plan(전 업종 = 월간 schedule 경로) — definitions.py의 mois_load_plan
            # resource가 빈 run_config에서 만드는 것과 같다(ADR-108).
            mois_load_plan=resolve_mois_load_plan(
                KorTravelMapSettings.model_construct(
                    mois_source_db_path=None,
                    mois_geocode_concurrency=2,
                    mois_load_run_budget_seconds=14_400,
                )
            ),
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

    feature_results = [result for result in results if hasattr(result, "feature_ids")]

    assert len(feature_results) == len(results)
    assert all(result.load.features_inserted == 1 for result in feature_results)
    assert all(not result.address_validation.has_errors for result in feature_results)

    feature_ids = [
        feature_id for result in feature_results for feature_id in result.feature_ids
    ]
    assert len(feature_ids) == 8

    # 조회 키는 적재가 발급한 정본 키다 — asset이 돌려준 ``f_*``는 그 주소다.
    canonical_ids = await _canonical_ids(migrated_engine, feature_ids)
    for feature_id in feature_ids:
        row = await map_client.get_feature(canonical_ids[feature_id])
        assert row is not None
        assert row["coord_5179_srid"] == 5179
        assert row["legal_dong_code"] is not None
        assert row["sigungu_code"] is not None

    async with AsyncSession(migrated_engine) as session:
        feature_count = await session.scalar(text("SELECT count(*) FROM feature.features"))
        source_count = await session.scalar(
            text("SELECT count(*) FROM provider_sync.source_records")
        )
    # 유가 price·돌발 notice asset은 ADR-114 결정 7(1단계, migration 419)로 퇴역했다 — 그 현재
    # 상태는 Valkey(`transport_state_*`)가 든다(`tests/integration/test_valkey_transport_state.py`).
    assert feature_count == 8
    assert source_count == 8


async def _run_asset(
    runner: Callable[[AssetExecutionContext], Awaitable[Any]],
    client: AsyncKorTravelMapClient,
    **resources: object,
) -> Any:
    if "feature_operation_guard" not in resources:
        # asset 이름과 operation key는 registry에서 1:1이다(`run_<asset>` ↔ `<asset>_job`).
        # 등록된 operation일 때만 guard를 넣는다 — 그렇지 않은 helper asset은 그대로 둔다.
        operation_key = f"{runner.__name__.removeprefix('run_')}_job"
        if operation_key in FEATURE_OPERATION_HANDLERS:
            resources["feature_operation_guard"] = await _guard_resource(
                client, operation_key
            )
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": _ReverseGeocoder(),
            "fetched_at": _FETCHED,
            **resources,
        }
    )
    return await runner(context)


async def _guard_resource(
    client: AsyncKorTravelMapClient,
    operation_key: str,
) -> FeatureOperationExecutionGuard:
    """asset이 sync-state를 쓰려면 feature-operation guard가 있어야 한다.

    프로덕션에서는 ``run_tracked_feature_asset``이 실행 시작 시 이 guard를 넣는다.
    sync state의 정체성이 triple이 된 뒤(ADR-088) provider/dataset label로는 어느
    행인지 결정되지 않으므로, 직접 호출하는 테스트도 실행이 어느 operation인지
    똑같이 선언해야 한다 — 역산 fallback은 두지 않는 것이 계약이다.
    """

    memberships = await client.resolve_feature_operation_memberships(
        operation_key=operation_key,
    )
    return FeatureOperationExecutionGuard(
        client=client,
        instance=None,
        operation_key=operation_key,
        memberships=memberships,
        dagster_run_id="00000000-0000-4000-8000-000000000001",
        trigger_kind="schedule",
    )


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
