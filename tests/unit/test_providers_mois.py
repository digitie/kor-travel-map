"""``test_providers_mois`` — MOIS 인허가(LOCALDATA) place 변환 (ADR-034 ⑦).

테스트 범위:
- PROMOTED 슬러그 → place FeatureBundle (category/place_kind/marker).
- EXCLUDED / 미매핑 슬러그 / 비영업 record skip.
- 좌표 WGS84 passthrough / 좌표 없음 / 한국 경계 밖 drop.
- legal_dong_code → bjd_code 1차 (geocoder 미호출), 없으면 역지오코딩 보강 + 좌표 dedup.
- opn_authority_code는 bjd로 쓰지 않음 (payload만).
- 주소/전화 정규화, facility_info, 결정성, SourceRole.PRIMARY, 자연키 `::`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.dto import Address, Coordinate, FeatureKind, SourceRole
from krtour.map.providers.mois import (
    EXCLUDED_SERVICE_SLUGS,
    MOIS_MARKER_COLOR,
    PROMOTED_CATEGORY_BY_SLUG,
    PROMOTED_PLACE_KIND_BY_SLUG,
    PROMOTED_SERVICE_SLUGS,
    PROVIDER_NAME,
    license_records_to_bundles,
    resolve_license_category,
    resolve_license_place_kind,
)

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Record:
    """``MoisLicensePlaceRecord`` Protocol 만족 (mois.db.PlaceRecord 모사)."""

    service_slug: str
    mng_no: str | None = "MNG-0001"
    is_open: bool | None = True
    place_name: str | None = "테스트 사업장"
    category: str | None = None
    title: str | None = None
    opn_authority_code: str | None = None
    status_code: str | None = "01"
    status_name: str | None = "영업/정상"
    detail_status_code: str | None = None
    detail_status_name: str | None = None
    license_date: date | None = None
    telno: str | None = None
    road_address: str | None = None
    lot_address: str | None = None
    road_zip: str | None = None
    lot_zip: str | None = None
    legal_dong_code: str | None = None
    road_name_code: str | None = None
    building_management_number: str | None = None
    lon: float | None = None
    lat: float | None = None
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


class _FakeGeocoder:
    """좌표 → Address 역지오코더 (호출 횟수 기록)."""

    def __init__(self, address: Address) -> None:
        self._address = address
        self.calls = 0

    async def __call__(self, coord: Coordinate) -> Address:
        self.calls += 1
        return self._address


async def _bundles(records: list[_Record], **kwargs: Any) -> list[Any]:
    return await license_records_to_bundles(records, fetched_at=_FETCHED, **kwargs)


# -- resolver 단위 ------------------------------------------------------------


def test_promoted_slug_counts() -> None:
    assert len(PROMOTED_SERVICE_SLUGS) == 42
    assert len(EXCLUDED_SERVICE_SLUGS) == 21
    # category / place_kind 매핑이 PROMOTED 전 슬러그를 커버.
    assert set(PROMOTED_CATEGORY_BY_SLUG) == PROMOTED_SERVICE_SLUGS
    assert set(PROMOTED_PLACE_KIND_BY_SLUG) == PROMOTED_SERVICE_SLUGS
    # PROMOTED ∩ EXCLUDED = ∅.
    assert not (PROMOTED_SERVICE_SLUGS & EXCLUDED_SERVICE_SLUGS)


@pytest.mark.parametrize(
    ("slug", "category", "place_kind"),
    [
        ("general_restaurants", "02010100", "restaurant"),
        ("traditional_temples", "01070100", "temple_traditional"),
        ("tourist_accommodations", "03010100", "lodging_tourist_hotel"),
        ("public_baths", "04020100", "public_bath"),
        ("golf_courses", "01080100", "golf_course"),
    ],
)
def test_resolve_category_and_place_kind(slug: str, category: str, place_kind: str) -> None:
    assert resolve_license_category(slug) == category
    assert resolve_license_place_kind(slug) == place_kind


def test_resolve_category_none_for_non_promoted() -> None:
    assert resolve_license_category("billiard_halls") is None
    assert resolve_license_category("hospitals") is None


# -- 변환 (성공 케이스) -------------------------------------------------------


async def test_promoted_restaurant_bundle() -> None:
    rec = _Record(
        service_slug="general_restaurants",
        mng_no="3000000-101-2024-00001",
        place_name="한식당 가나다",
        legal_dong_code="1111010100",
        road_address="서울특별시 종로구 세종대로 1",
        lot_address="서울특별시 종로구 세종로 1",
        telno="0212345678",
        lon=126.9784,
        lat=37.5665,
    )
    [bundle] = await _bundles([rec])
    feature = bundle.feature
    assert feature.kind is FeatureKind.PLACE
    assert feature.name == "한식당 가나다"
    assert feature.category == "02010100"
    assert feature.marker_color == MOIS_MARKER_COLOR
    assert feature.coord == Coordinate(lon=Decimal("126.9784"), lat=Decimal("37.5665"))
    assert feature.address.bjd_code == "1111010100"
    assert feature.address.sigungu_code == "11110"
    assert feature.address.sido_code == "11"
    assert feature.detail.place_kind == "restaurant"
    assert feature.detail.phones == ["02-1234-5678"]
    # FK consistency (FeatureBundle validator가 보장하지만 명시 확인).
    assert bundle.source_link.feature_id == feature.feature_id
    assert bundle.source_link.source_record_key == bundle.source_record.source_record_key
    assert bundle.source_link.source_role is SourceRole.PRIMARY
    assert bundle.source_record.provider == PROVIDER_NAME
    assert bundle.source_record.source_entity_id == "general_restaurants::3000000-101-2024-00001"


async def test_natural_key_uses_double_colon_separator() -> None:
    # 구분자는 `::` (make_feature_id/make_source_record_key가 `|` 금지).
    rec = _Record(service_slug="bakeries", mng_no="3000000-101-2024-00077")
    [bundle] = await _bundles([rec])
    assert bundle.source_record.source_entity_id == "bakeries::3000000-101-2024-00077"
    assert "|" not in bundle.source_record.source_entity_id
    assert bundle.feature.feature_id.startswith("f_")


# -- skip 케이스 --------------------------------------------------------------


async def test_excluded_slug_skipped() -> None:
    recs = [_Record(service_slug="billiard_halls"), _Record(service_slug="pet_grooming")]
    assert await _bundles(recs) == []


async def test_unmapped_slug_skipped() -> None:
    assert await _bundles([_Record(service_slug="hospitals")]) == []


async def test_closed_record_skipped() -> None:
    recs = [
        _Record(service_slug="general_restaurants", is_open=False),
        _Record(service_slug="general_restaurants", is_open=None),
    ]
    assert await _bundles(recs) == []


async def test_mixed_batch_keeps_only_promoted_open() -> None:
    recs = [
        _Record(service_slug="general_restaurants", mng_no="keep1"),
        _Record(service_slug="billiard_halls", mng_no="drop_excluded"),
        _Record(service_slug="hospitals", mng_no="drop_unmapped"),
        _Record(service_slug="bakeries", mng_no="drop_closed", is_open=False),
        _Record(service_slug="public_baths", mng_no="keep2"),
    ]
    bundles = await _bundles(recs)
    kept = [b.source_record.source_entity_id for b in bundles]
    assert kept == ["general_restaurants::keep1", "public_baths::keep2"]


# -- 좌표 처리 ----------------------------------------------------------------


async def test_coordinate_passthrough_wgs84() -> None:
    rec = _Record(service_slug="bakeries", lon=129.0756, lat=35.1796, legal_dong_code="2611010100")
    [bundle] = await _bundles([rec])
    assert bundle.feature.coord == Coordinate(lon=Decimal("129.0756"), lat=Decimal("35.1796"))


async def test_no_coordinate_still_builds_bundle() -> None:
    rec = _Record(service_slug="bakeries", lon=None, lat=None, legal_dong_code="1111010100")
    [bundle] = await _bundles([rec])
    assert bundle.feature.coord is None
    assert bundle.feature.feature_id.startswith("f_1111010100_p_")


async def test_out_of_korea_coord_dropped() -> None:
    rec = _Record(service_slug="bakeries", lon=2.3522, lat=48.8566, legal_dong_code="1111010100")
    [bundle] = await _bundles([rec])
    assert bundle.feature.coord is None  # 파리 좌표 → 경계 밖 → None


# -- bjd_code 보강 ------------------------------------------------------------


async def test_legal_dong_code_fills_bjd_without_geocoder() -> None:
    geo = _FakeGeocoder(Address(bjd_code="2611010100"))
    rec = _Record(
        service_slug="general_restaurants",
        legal_dong_code="1111010100",
        lon=126.97,
        lat=37.56,
    )
    [bundle] = await _bundles([rec], reverse_geocoder=geo)
    assert bundle.feature.address.bjd_code == "1111010100"
    assert geo.calls == 0  # legal_dong_code 있으면 역지오코딩 호출 안 함


async def test_reverse_geocoder_fills_and_dedupes() -> None:
    geo = _FakeGeocoder(Address(bjd_code="1111010100", sigungu_code="11110", sido_code="11"))
    recs = [
        _Record(service_slug="bakeries", mng_no="a", legal_dong_code=None, lon=126.97, lat=37.56),
        _Record(service_slug="bakeries", mng_no="b", legal_dong_code=None, lon=126.97, lat=37.56),
    ]
    bundles = await _bundles(recs, reverse_geocoder=geo)
    assert all(b.feature.address.bjd_code == "1111010100" for b in bundles)
    assert geo.calls == 1  # 동일 좌표 → cached_reverse_geocoder로 1회만


async def test_opn_authority_code_not_used_as_bjd() -> None:
    rec = _Record(
        service_slug="bakeries",
        legal_dong_code=None,
        opn_authority_code="3000000",
        lon=None,
        lat=None,
    )
    [bundle] = await _bundles([rec])
    assert bundle.feature.address.bjd_code is None
    assert bundle.feature.feature_id.startswith("f_global_p_")
    assert bundle.feature.detail.payload["opn_authority_code"] == "3000000"


# -- 주소 / detail ------------------------------------------------------------


async def test_address_and_zip_normalized() -> None:
    rec = _Record(
        service_slug="bakeries",
        road_address="서울특별시  종로구   세종대로 1",  # 다중 공백
        lot_address="서울특별시 종로구 세종로 1",
        road_zip="03172",
        lot_zip="110-061",  # 구 우편번호 형식 → 거부
        road_name_code="111103100015",
        building_management_number="1111010100100010000000001",
        legal_dong_code="1111010100",
    )
    [bundle] = await _bundles([rec])
    addr = bundle.feature.address
    assert addr.road == "서울특별시 종로구 세종대로 1"
    assert addr.zipcode == "03172"
    assert addr.road_name_code == "111103100015"
    assert addr.road_address_management_no == "1111010100100010000000001"


async def test_facility_info_built() -> None:
    rec = _Record(
        service_slug="general_restaurants",
        legal_dong_code="1111010100",
        sanitation_business_status_name="정상",
        water_supply_facility_type_name="상수도",
        business_type_name="일반음식점",
        multi_use_business_place_yn="Y",
        total_area=120.5,
        total_floor_count=3,
        building_usage_name="근린생활시설",
    )
    [bundle] = await _bundles([rec])
    fi = bundle.feature.detail.facility_info
    assert fi["service_slug"] == "general_restaurants"
    assert fi["food"]["multi_use"] is True
    assert fi["building"]["total_area_m2"] == 120.5


async def test_phones_and_license_date_and_epsg5174() -> None:
    rec = _Record(
        service_slug="bakeries",
        legal_dong_code="1111010100",
        telno="0311234567",
        license_date=date(2020, 3, 15),
        source_x=197123.4,
        source_y=451234.5,
    )
    [bundle] = await _bundles([rec])
    detail = bundle.feature.detail
    assert detail.phones == ["031-123-4567"]
    assert detail.license_date == date(2020, 3, 15)
    assert detail.payload["epsg5174"] == {"x": 197123.4, "y": 451234.5}


# -- 결정성 -------------------------------------------------------------------


async def test_deterministic_ids() -> None:
    rec = _Record(service_slug="general_restaurants", mng_no="X1", legal_dong_code="1111010100")
    [b1] = await _bundles([rec])
    [b2] = await _bundles([rec])
    assert b1.feature.feature_id == b2.feature.feature_id
    assert b1.source_record.source_record_key == b2.source_record.source_record_key
