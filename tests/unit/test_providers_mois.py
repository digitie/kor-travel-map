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

import dataclasses
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.cli.records import MoisLicenseJsonRecord
from kortravelmap.dto import Address, Coordinate, FeatureKind, SourceRole
from kortravelmap.providers.mois import (
    EXCLUDED_SERVICE_SLUGS,
    MOIS_MARKER_COLOR,
    PROMOTED_CATEGORY_BY_SLUG,
    PROMOTED_PLACE_KIND_BY_SLUG,
    PROMOTED_SERVICE_SLUGS,
    PROVIDER_NAME,
    _facility_info,
    _raw_data,
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


async def test_address_resolver_fills_bjd_without_legal_code_or_coord() -> None:
    calls: list[Address] = []

    async def _resolver(address: Address) -> Address | None:
        calls.append(address)
        return Address(
            road=address.road,
            legal=address.legal,
            bjd_code="1114010100",
            sigungu_code="11140",
            sido_code="11",
            admin="서울특별시 중구 태평로1가",
        )

    rec = _Record(
        service_slug="bakeries",
        legal_dong_code=None,
        lon=None,
        lat=None,
        road_address="서울특별시 중구 세종대로 110",
        lot_address="서울특별시 중구 태평로1가 31",
    )

    [bundle] = await _bundles([rec], address_resolver=_resolver)

    assert len(calls) == 1
    assert calls[0].road == "서울특별시 중구 세종대로 110"
    assert calls[0].legal == "서울특별시 중구 태평로1가 31"
    assert bundle.feature.address.bjd_code == "1114010100"
    assert bundle.feature.address.sigungu_code == "11140"
    assert bundle.feature.address.sido_code == "11"
    assert bundle.feature.feature_id.startswith("f_1114010100_p_")


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


# -- raw_data round-trip (backup-restore §10 절차 4) ---------------------------


def _fully_populated_record() -> _Record:
    """모든 Protocol 필드가 **비어 있지 않은** record.

    필드를 손으로 나열하지 않고 dataclass 정의에서 만든다 — Protocol에 필드가 추가되면
    이 헬퍼가 자동으로 채우고, 아래 손실 집합이 갱신되지 않으면 테스트가 실패한다.
    """

    values: dict[str, Any] = {}
    for index, field in enumerate(dataclasses.fields(_Record), start=1):
        annotation = str(field.type)
        if "bool" in annotation:
            values[field.name] = True
        elif "date" in annotation:
            values[field.name] = date(2020, 1, 1 + (index % 27))
        elif "int" in annotation:
            values[field.name] = index
        elif "float" in annotation:
            values[field.name] = float(index)
        else:
            values[field.name] = f"v{index}"
    values["service_slug"] = "general_restaurants"
    values["multi_use_business_place_yn"] = "Y"
    return _Record(**values)


#: ``_raw_data``가 **버리는** Protocol 필드. 복원 드릴(§10 절차 4)은 저장된
#: ``source_records.raw_data``를 NDJSON으로 되먹이므로, 여기 있는 값은 replay로 돌아오지
#: 않는다. 이 집합이 줄면 ``docs/backup-restore.md`` §10도 함께 고쳐야 한다.
_RAW_DATA_DROPS = frozenset(
    {
        "bed_count",
        "building_management_number",
        "building_usage_name",
        "designation_date",
        "facility_area",
        "facility_total_scale",
        "ground_floor_count",
        "healthcare_worker_count",
        "hospital_room_count",
        "lot_zip",
        "medical_institution_type_name",
        "medical_subject_names",
        "multi_use_business_place_yn",
        "road_zip",
        "sales_method_name",
        "sanitation_business_status_name",
        "sickbed_count",
        "total_area",
        "total_floor_count",
        "underground_floor_count",
        "water_supply_facility_type_name",
    }
)


def test_raw_data_round_trip_drops_exactly_the_known_fields() -> None:
    """``raw_data`` → NDJSON → record 되먹임에서 무엇이 사라지는지 못박는다.

    ``docs/backup-restore.md`` §10 절차 4는 ``source_records.raw_data``를 되먹여 결손을
    메운다. 그런데 ``_raw_data``는 payload_hash용 canonical dict라 Protocol 중 기본·분류 필드만
    담고, NDJSON 래퍼(``MoisLicenseJsonRecord.__getattr__``)는 없는 key를 **조용히 None**으로
    돌려준다. 그래서 되먹임은 실패하지 않고 **부분 복원**된다 — 이쪽이 훨씬 위험하다.
    """

    original = _fully_populated_record()
    replayed = MoisLicenseJsonRecord(_raw_data(original, category="food"))

    dropped = {
        field.name for field in dataclasses.fields(_Record) if getattr(replayed, field.name) is None
    }
    assert dropped == set(_RAW_DATA_DROPS), (
        "raw_data round-trip의 손실 집합이 바뀌었다 — docs/backup-restore.md §10 절차 4의"
        " 경고와 절차 5의 확인 축도 함께 고쳐라.\n"
        f"  새로 사라진 것: {sorted(dropped - set(_RAW_DATA_DROPS))}\n"
        f"  이제 살아남는 것: {sorted(set(_RAW_DATA_DROPS) - dropped)}"
    )


def test_raw_data_round_trip_empties_facility_info_blocks() -> None:
    """손실이 **본문 어디에 나타나는지**까지 고정한다.

    이름 목록만 비교하면 "그래서 뭐가 나빠지나"가 안 보인다. 복원 드릴이 실제로 놓치는
    것은 ``PlaceDetail.facility_info``의 building/medical/food와 culture_sports의 나머지 필드다.
    절차 5의 확인 축(F1, feature 카운트, identity 4축)은 이 손실을 전혀 보지 못한다.
    """

    original = _fully_populated_record()
    replayed = MoisLicenseJsonRecord(_raw_data(original, category="food"))

    before = _facility_info(original)
    after = _facility_info(replayed)

    assert set(before) >= {"building", "medical", "food", "culture_sports"}, (
        "전제가 깨졌다 — 모든 필드를 채운 record인데 facility_info 블록이 안 생긴다"
    )
    assert set(after) == {
        "service_slug", "category", "subtype_name", "sales_method_name", "culture_sports",
    }, (
        f"되먹임 후 facility_info가 예상과 다르다: {sorted(after)}"
    )
    assert after["subtype_name"] == original.subtype_name
    assert after["culture_sports"]["type"] == original.culture_sports_business_type_name
    assert after["culture_sports"]["designation_date"] is None
    assert after["sales_method_name"] is None


# -- 재개형 적재 사전 계산 (ADR-108) -----------------------------------------------


async def test_payload_hash_helper_matches_the_bundle_it_predicts() -> None:
    """재개 키가 변환 결과와 **같은 값**이어야 한다 — 다르면 모든 행이 매번 "바뀐 것"이 된다.

    좌표만 있는 record(역지오코딩을 탄다)와 법정동 코드를 가진 record 둘 다 본다. 해시는
    지오코딩 결과와 무관해야 하므로 geocoder가 무엇을 돌려주든 같아야 한다.
    """
    from kortravelmap.providers.mois import license_record_payload_hash

    records = [
        _Record(service_slug="general_restaurants", mng_no="h-1", lon=126.97, lat=37.56),
        _Record(service_slug="bakeries", mng_no="h-2", legal_dong_code="1111010100"),
    ]
    for address in (Address(bjd_code="1111010100"), Address(bjd_code="2611010100")):
        bundles = await _bundles(records, reverse_geocoder=_FakeGeocoder(address))
        assert [b.source_record.raw_payload_hash for b in bundles] == [
            license_record_payload_hash(r) for r in records
        ]


def test_payload_hash_helper_rejects_non_promoted_slug() -> None:
    from kortravelmap.providers.mois import license_record_payload_hash

    with pytest.raises(ValueError, match="PROMOTED"):
        license_record_payload_hash(_Record(service_slug="billiard_halls"))


async def test_reverse_coordinate_helper_matches_what_the_converter_geocodes() -> None:
    """선조회할 좌표 = 변환이 실제로 geocoder에 넘기는 좌표. 법정동 코드가 있으면 없다."""
    from kortravelmap.providers.mois import license_reverse_geocode_coordinate

    seen: list[Coordinate] = []

    async def _geo(coord: Coordinate) -> Address:
        seen.append(coord)
        return Address(bjd_code="1111010100")

    records = [
        _Record(service_slug="general_restaurants", mng_no="c-1", lon=126.97, lat=37.56),
        _Record(
            service_slug="general_restaurants",
            mng_no="c-2",
            lon=127.01,
            lat=37.50,
            legal_dong_code="1168010100",
        ),
        _Record(service_slug="general_restaurants", mng_no="c-3"),
    ]
    await _bundles(records, reverse_geocoder=_geo)

    predicted = [license_reverse_geocode_coordinate(r) for r in records]
    assert predicted[1] is None
    assert predicted[2] is None
    assert [c for c in predicted if c is not None] == seen


# -- 행 evidence(ADR-109 결정 3 ②, T-GR-03) ---------------------------------------------------


async def _resolver_with(code: str | None) -> Any:
    async def _resolver(address: Address) -> Address | None:
        return None if code is None else Address(bjd_code=code, sigungu_code=code[:5])

    return _resolver


@pytest.mark.parametrize(
    ("record", "reverse", "resolver_code", "expected"),
    [
        # payload 법정동코드 — geo를 부르지 않는다.
        (
            {"legal_dong_code": "1111010100", "lon": 126.97, "lat": 37.56},
            True,
            None,
            (False, False),
        ),
        # 좌표 + reverse — 불렀다.
        ({"lon": 126.97, "lat": 37.56}, True, None, (True, False)),
        # 좌표 없음 + geocode가 코드를 받았다.
        ({"road_address": "서울특별시 중구 세종대로 110"}, False, "1114010100", (False, True)),
        # 좌표 없음 + geocode를 시도했지만 코드를 못 받았다 — 받은 것만 센다.
        ({"road_address": "서울특별시 중구 세종대로 110"}, False, None, (False, False)),
    ],
    ids=["payload-code", "reverse", "geocode-obtained", "geocode-missed"],
)
async def test_bundle_carries_the_geo_attempt_evidence(
    record: dict[str, Any],
    reverse: bool,
    resolver_code: str | None,
    expected: tuple[bool, bool],
) -> None:
    kwargs: dict[str, Any] = {"address_resolver": await _resolver_with(resolver_code)}
    if reverse:
        kwargs["reverse_geocoder"] = _FakeGeocoder(Address(bjd_code="1111010100"))
    [bundle] = await _bundles([_Record(service_slug="bakeries", **record)], **kwargs)
    assert bundle.geo_attempt is not None
    assert (
        bundle.geo_attempt.reverse_attempted,
        bundle.geo_attempt.geocode_obtained_code,
    ) == expected


@pytest.mark.parametrize(
    ("slug", "subtype", "expected"),
    [
        ("general_restaurants", "중국식", "02010400"),
        ("general_restaurants", "일식", "02010300"),
        ("general_restaurants", "경양식", "02010200"),
        ("general_restaurants", "한식", "02010100"),
        ("rest_cafes", "다방", "02020000"),
        ("large_scale_retail_stores", "대형마트", "05030000"),
        ("large_scale_retail_stores", "백화점", "05050000"),
        ("large_scale_retail_stores", "모르는 업태", "05050000"),
        ("tourist_accommodations", "가족호텔업", "03010000"),
        ("tourist_accommodations", "비즈니스호텔", "03010200"),
        ("general_restaurants", "관광호텔", "02010100"),
    ],
)
async def test_structured_license_subtype_preserves_legacy_identity_and_hash_prediction(
    slug: str, subtype: str, expected: str,
) -> None:
    from kortravelmap.providers.mois import license_record_payload_hash

    original = _Record(service_slug=slug, place_name="호텔 앞 중국식당")
    [old] = await _bundles([original])
    record = dataclasses.replace(original, subtype_name=subtype)
    [bundle] = await _bundles([record])
    assert bundle.feature.category == expected
    assert bundle.feature.feature_id == old.feature.feature_id
    assert bundle.feature.provider_natural_key == old.feature.provider_natural_key
    assert bundle.feature.marker_color == MOIS_MARKER_COLOR
    assert bundle.source_record.raw_payload_hash == license_record_payload_hash(record)
    assert bundle.source_record.raw_data.get("subtype_name") == subtype


async def test_conflicting_structured_license_fields_keep_slug_fallback() -> None:
    [bundle] = await _bundles([_Record(
        service_slug="general_restaurants", subtype_name="중국식", business_type_name="일식",
    )])
    assert bundle.feature.category == "02010100"


async def test_subtype_fields_do_not_churn_the_hash_of_slugs_they_cannot_reclassify() -> None:
    """업태 필드는 분류를 세분화하는 슬러그의 해시에만 들어간다(#1444 리뷰).

    다른 슬러그(제과점 등)는 업태가 분류를 바꾸지 못한다. 그런데도 해시에 넣으면 배포 뒤
    재개형 적재(ADR-108)가 그 슬러그 전체를 "바뀐 것"으로 보고 역지오코딩부터 다시 한다.
    """
    from kortravelmap.providers.mois import license_record_payload_hash

    plain = _Record(service_slug="bakeries", mng_no="3000000-101-2024-00078")
    typed = dataclasses.replace(
        plain, subtype_name="제과점", business_type_name="제과점영업",
        culture_sports_business_type_name="기타",
    )
    assert license_record_payload_hash(typed) == license_record_payload_hash(plain)
    [bundle] = await _bundles([typed])
    assert "subtype_name" not in bundle.source_record.raw_data
    assert bundle.source_record.raw_payload_hash == license_record_payload_hash(typed)


# -- 적재 순서 (docs §10.1) ------------------------------------------------------


def test_load_order_covers_every_promoted_slug_once_lodging_first_mass_food_last() -> None:
    from kortravelmap.providers.mois import MOIS_SLUG_LOAD_GROUPS, MOIS_SLUG_LOAD_ORDER

    assert len(MOIS_SLUG_LOAD_ORDER) == len(set(MOIS_SLUG_LOAD_ORDER)) == len(
        PROMOTED_SERVICE_SLUGS
    )
    assert set(MOIS_SLUG_LOAD_ORDER) == PROMOTED_SERVICE_SLUGS
    groups = [name for name, _slugs in MOIS_SLUG_LOAD_GROUPS]
    assert groups[0] == "lodging"
    assert groups[-1] == "mass_food"
    rank = {slug: i for i, slug in enumerate(MOIS_SLUG_LOAD_ORDER)}
    lodging = dict(MOIS_SLUG_LOAD_GROUPS)["lodging"]
    for mass in ("general_restaurants", "rest_cafes", "bakeries"):
        assert all(rank[slug] < rank[mass] for slug in lodging)
        assert rank[mass] >= len(MOIS_SLUG_LOAD_ORDER) - 3
    assert rank["lodgings"] < rank["tourist_accommodations"] < rank["tourism_businesses"]


def test_order_service_slugs_sorts_by_priority_and_rejects_unknown() -> None:
    from kortravelmap.providers.mois import order_service_slugs

    assert order_service_slugs(["general_restaurants", "lodgings", "golf_courses", "lodgings"]) == (
        "lodgings", "golf_courses", "general_restaurants",
    )
    with pytest.raises(ValueError, match="billiard_halls"):
        order_service_slugs(["billiard_halls"])


# -- 업태별 분류·승격 제외 (docs §6.1) -------------------------------------------


@pytest.mark.parametrize(
    ("subtype", "category"),
    [
        ("관광호텔", "03010100"),
        ("일반호텔", "03010000"),
        ("휴양콘도미니엄업", "03020100"),
        ("숙박업(생활)", "03000000"),
        ("여관업", "03040100"),
        ("여인숙업", "03040100"),
        ("숙박업 기타", "03040100"),
    ],
)
async def test_lodging_category_follows_the_license_subtype(subtype: str, category: str) -> None:
    record = _Record(
        service_slug="lodgings", subtype_name=subtype, business_type_name=subtype,
        legal_dong_code="1111010100",
    )
    [bundle] = await _bundles([record])
    assert bundle.feature.category == category
    # 업태가 분류를 바꾸므로 해시에 담는다(같은 payload면 같은 분류).
    assert bundle.source_record.raw_data["subtype_name"] == subtype


async def test_tourism_business_lodging_is_lodging_and_travel_agency_is_not_promoted() -> None:
    from kortravelmap.providers.mois import license_record_is_promotable

    hotel = _Record(
        service_slug="tourism_businesses", mng_no="TB-1", subtype_name="관광숙박업",
        culture_sports_business_type_name="관광숙박업", legal_dong_code="5011025300",
    )
    agency = _Record(
        service_slug="tourism_businesses", mng_no="TB-2", place_name="㈜호텔신라",
        subtype_name="여행업", culture_sports_business_type_name="여행업",
        legal_dong_code="1114016200",
    )
    facility = dataclasses.replace(
        hotel, mng_no="TB-3", subtype_name="관광객이용시설업",
        culture_sports_business_type_name="관광객이용시설업",
    )
    assert license_record_is_promotable(hotel)
    assert not license_record_is_promotable(agency)
    bundles = await _bundles([hotel, agency, facility])
    by_id = {b.source_record.source_entity_id: b for b in bundles}
    assert set(by_id) == {"tourism_businesses::TB-1", "tourism_businesses::TB-3"}
    assert by_id["tourism_businesses::TB-1"].feature.category == "03010100"
    assert by_id["tourism_businesses::TB-1"].feature.detail.place_kind == "lodging_tourist_hotel"
    assert by_id["tourism_businesses::TB-3"].feature.category == "01000000"
    assert by_id["tourism_businesses::TB-3"].feature.detail.place_kind == "tourism_business_office"


# -- 표시 이름 (docs §6.4) --------------------------------------------------------


async def test_feature_name_drops_the_legal_form_and_keeps_it_in_detail() -> None:
    record = _Record(
        service_slug="lodgings", place_name="(주)호텔롯데 롯데시티호텔대전",
        subtype_name="관광호텔", legal_dong_code="3020012800",
    )
    [bundle] = await _bundles([record])
    assert bundle.feature.name == "롯데시티호텔대전"
    assert bundle.feature.detail.payload["legal_name"] == "(주)호텔롯데 롯데시티호텔대전"
    assert bundle.source_record.raw_data["place_name"] == "(주)호텔롯데 롯데시티호텔대전"
    # 규칙 판이 아니라 결과를 해시한다 — 결과가 바뀐 행만 다시 변환된다.
    assert bundle.source_record.raw_data["display_name"] == "롯데시티호텔대전"
    assert bundle.feature.detail.place_kind == "lodging_tourist_hotel"

    english = dataclasses.replace(
        record, mng_no="X-2",
        place_name="페어필드 바이 메리어트 서울(Fairfield by Marriott-Seoul)",
    )
    [bundle] = await _bundles([english])
    assert bundle.feature.name == "페어필드 바이 메리어트 서울(Fairfield by Marriott-Seoul)"
    assert "display_name" not in bundle.source_record.raw_data


async def test_hangul_branch_bracket_expands_for_lodging_only() -> None:
    hotel = _Record(
        service_slug="lodgings", place_name="주식회사 라한호텔(경주)",
        subtype_name="관광호텔", legal_dong_code="4713012500",
    )
    bakery = _Record(
        service_slug="bakeries", mng_no="B-9", place_name="베이커리(본점)",
        legal_dong_code="1111010100",
    )
    [lodging, bread] = await _bundles([hotel, bakery])
    assert lodging.feature.name == "라한호텔 경주"
    assert bread.feature.name == "베이커리(본점)"
    assert "display_name" not in bread.source_record.raw_data


async def test_name_rule_does_not_touch_the_hash_of_rows_whose_name_is_unchanged() -> None:
    """이미 적재된 업종의 평범한 상호는 해시 입력이 그대로여야 한다(재개형 적재가 건너뛴다).

    해시 입력 키 집합을 이 변경 전 그대로 박는다. 새 키가 모든 행에 붙으면 이미 적재된 13만 행이
    전부 "바뀐 것"이 되어 역지오코딩부터 다시 한다.
    """
    legacy_keys = {
        "service_slug", "mng_no", "category", "title", "place_name", "opn_authority_code",
        "status_code", "status_name", "detail_status_code", "detail_status_name", "is_open",
        "license_date", "telno", "road_address", "lot_address", "legal_dong_code",
        "road_name_code", "lon", "lat", "source_x", "source_y", "krtour_category",
    }
    names = ("파리바게뜨 광화문점", "  뚜레쥬르   서촌점 ", "베이커리(본점)", "스타벅스(STARBUCKS)")
    for name in names:
        plain = _Record(
            service_slug="bakeries", mng_no="B-1", place_name=name, lon=126.97, lat=37.57,
            legal_dong_code="1111010100",
        )
        [bundle] = await _bundles([plain])
        assert bundle.feature.name == " ".join(name.split()), name
        assert set(bundle.source_record.raw_data) == legacy_keys, name
        assert "legal_name" not in bundle.feature.detail.payload
    # 법인 표기가 붙은 행만 표시 이름을 싣는다(그 행만 한 번 다시 변환된다).
    marked = _Record(
        service_slug="bakeries", mng_no="B-3", place_name="(주)파리크라상 광화문점",
        lon=126.97, lat=37.57, legal_dong_code="1111010100",
    )
    [bundle] = await _bundles([marked])
    assert set(bundle.source_record.raw_data) == legacy_keys | {"display_name"}
    # 원천 좌표가 없고 주소가 있는 행만 좌표 규칙 판을 싣는다 — 한 번 정지오코딩된다.
    no_point = _Record(
        service_slug="bakeries", mng_no="B-2", place_name="파리바게뜨 서촌점",
        road_address="서울특별시 종로구 자하문로 1",
    )
    [bundle] = await _bundles([no_point])
    assert set(bundle.source_record.raw_data) == legacy_keys | {"coord_rule"}
    nothing = dataclasses.replace(no_point, mng_no="B-4", road_address=None)
    [bundle] = await _bundles([nothing])
    assert set(bundle.source_record.raw_data) == legacy_keys


# -- 숙박 계열 중복 흡수 (docs §6.3) ----------------------------------------------


def _family(slug: str, mng_no: str, name: str, **kw: Any) -> _Record:
    subtype = "관광호텔" if slug == "lodgings" else "관광숙박업"
    fields: dict[str, Any] = {
        "service_slug": slug,
        "mng_no": mng_no,
        "place_name": name,
        "subtype_name": subtype,
        "road_address": "강원특별자치도 속초시 설악산로 998 (설악동)",
        "lon": 128.5072,
        "lat": 38.1729,
    }
    if slug == "lodgings":
        fields["business_type_name"] = subtype
    else:
        fields["culture_sports_business_type_name"] = subtype
    fields.update(kw)
    return _Record(**fields)


def test_same_hotel_in_three_license_slugs_is_one_place_lodgings_wins() -> None:
    from kortravelmap.providers.mois import LicenseShadowIndex, license_source_entity_id

    lodging = _family("lodgings", "L-1", "(주)이랜드파크켄싱턴호텔설악(스타)")
    tourist = _family("tourist_accommodations", "T-1", "(주)이랜드파크 켄싱턴호텔 설악(스타)")
    business = _family("tourism_businesses", "B-1", "켄싱턴호텔설악(스타)")
    index = LicenseShadowIndex.build([business, tourist, lodging])

    assert index.winner_for(lodging) is None
    assert index.winner_for(tourist) == license_source_entity_id(lodging)
    assert index.winner_for(business) == license_source_entity_id(lodging)


def test_shadowing_needs_the_same_name_and_the_same_building_or_a_near_point() -> None:
    from kortravelmap.providers.mois import LicenseShadowIndex

    lodging = _family("lodgings", "L-1", "라한호텔전주")
    other_name = _family("tourist_accommodations", "T-1", "라한호텔울산")
    far_same_name = _family(
        "tourist_accommodations", "T-2", "라한호텔전주",
        road_address="전북특별자치도 전주시 덕진구 다른로 1", lon=127.20, lat=35.90,
    )
    near_other_address = _family(
        "tourist_accommodations", "T-3", "라한호텔전주",
        road_address=None, lon=128.5075, lat=38.1730,  # 약 30 m
    )
    same_building_detail = _family(
        "tourist_accommodations", "T-4", "라한호텔 전주",
        road_address="강원특별자치도 속초시 설악산로 998, 1층일부", lon=None, lat=None,
    )
    index = LicenseShadowIndex.build([lodging])

    assert index.winner_for(other_name) is None
    assert index.winner_for(far_same_name) is None
    assert index.winner_for(near_other_address) is not None
    assert index.winner_for(same_building_detail) is not None


def test_same_slug_duplicates_and_non_lodging_rows_are_not_shadowed() -> None:
    from kortravelmap.providers.mois import LicenseShadowIndex

    first = _family("lodgings", "L-1", "켄싱턴리조트설악밸리")
    second = _family("lodgings", "L-2", "켄싱턴리조트설악밸리")
    agency = _family(
        "tourism_businesses", "B-1", "켄싱턴리조트설악밸리",
        subtype_name="여행업", culture_sports_business_type_name="여행업",
    )
    facility = _family(
        "tourism_businesses", "B-2", "켄싱턴리조트설악밸리",
        subtype_name="관광객이용시설업", culture_sports_business_type_name="관광객이용시설업",
    )
    bakery = _family("bakeries", "K-1", "켄싱턴리조트설악밸리", subtype_name=None)
    index = LicenseShadowIndex.build([first, second, agency, facility, bakery])

    assert len(index) == 2
    assert index.winner_for(second) is None, "같은 업종 안의 중복은 이 규칙의 대상이 아니다"
    assert index.winner_for(facility) is None
    assert index.winner_for(bakery) is None


def test_same_building_name_containment_is_one_hotel() -> None:
    """제주신라: lodgings "호텔신라제주" ↔ 관광숙박업 "(주)호텔신라 제주신라"(같은 건물)."""
    from kortravelmap.providers.mois import LicenseShadowIndex, license_source_entity_id

    road = "제주특별자치도 서귀포시 중문관광로72번길 75 (색달동)"
    lodging = _family("lodgings", "L-9", "호텔신라제주", road_address=road)
    tourist = _family("tourist_accommodations", "T-9", "(주)호텔신라 제주신라", road_address=road)
    other_building = _family(
        "tourist_accommodations", "T-8", "(주)호텔신라 제주신라",
        road_address="제주특별자치도 제주시 노연로 69", lon=126.49, lat=33.49,
    )
    short = _family("tourist_accommodations", "T-7", "호텔", road_address=road)
    index = LicenseShadowIndex.build([lodging])

    assert index.winner_for(tourist) == license_source_entity_id(lodging)
    assert index.winner_for(other_building) is None
    assert index.winner_for(short) is None, "짧은 키는 포함 규칙을 쓰지 않는다"


def test_winner_chain_resolves_to_the_root_lodging() -> None:
    """B가 T와 이름이 같고 T가 L에 포함 규칙으로 가려지면 B의 답은 L이다(사슬의 맨 앞).

    T를 답으로 주면 T가 철회돼 지도에 없으므로 적재기가 B를 다시 싣는다(델타 리뷰 MED).
    """
    from kortravelmap.providers.mois import LicenseShadowIndex, license_source_entity_id

    road = "제주특별자치도 서귀포시 중문관광로72번길 75 (색달동)"
    lodging = _family("lodgings", "L-9", "호텔신라제주", road_address=road)
    tourist = _family("tourist_accommodations", "T-9", "(주)호텔신라 제주신라", road_address=road)
    business = _family("tourism_businesses", "B-9", "(주)호텔신라 제주신라", road_address=road)
    index = LicenseShadowIndex.build([lodging, tourist, business])

    assert index.winner_for(business) == license_source_entity_id(lodging)
    assert index.winner_for(tourist) == license_source_entity_id(lodging)


def test_containment_needs_a_prefix_and_the_same_lodging_class() -> None:
    from kortravelmap.providers.mois import LicenseShadowIndex

    road = "서울특별시 강남구 테헤란로 1"
    residence = _family(
        "lodgings", "L-1", "OO호텔레지던스", road_address=road,
        subtype_name="숙박업(생활)", business_type_name="숙박업(생활)",
    )
    hotel = _family("tourist_accommodations", "T-1", "OO호텔", road_address=road)
    suffix = _family("tourist_accommodations", "T-2", "레지던스", road_address=road)
    index = LicenseShadowIndex.build([residence])

    assert index.winner_for(hotel) is None, "생활숙박(0300)은 관광호텔(0301)을 가리지 않는다"
    assert index.winner_for(suffix) is None, "뒷부분 포함은 같은 시설이 아니다"


def test_in_hotel_facility_with_the_hotels_exact_name_is_shadowed() -> None:
    """호텔 사우나·공연장이 호텔 상호 그대로 같은 건물에 있으면 가려진다(이름이 다르면 남는다)."""
    from kortravelmap.providers.mois import LicenseShadowIndex, license_source_entity_id

    road = "전북특별자치도 전주시 완산구 기린대로 85, 1층일부"
    lodging = _family("lodgings", "L-5", "주식회사라한호텔전주", road_address=road)
    bath = _Record(
        service_slug="public_baths", mng_no="P-1", place_name="주식회사라한호텔전주",
        subtype_name="공동탕업", road_address="전북특별자치도 전주시 완산구 기린대로 85, 라한",
    )
    named_sauna = dataclasses.replace(bath, mng_no="P-2", place_name="라한호텔전주 사우나")
    elsewhere = dataclasses.replace(bath, mng_no="P-3", road_address="전주시 다른로 1")
    hall = _Record(
        service_slug="performance_halls", mng_no="H-1", place_name="라한호텔전주",
        road_address=road,
    )
    index = LicenseShadowIndex.build([lodging, bath, hall])

    assert len(index) == 1, "시설 업종은 이기지 않는다"
    assert index.winner_for(bath) == license_source_entity_id(lodging)
    assert index.winner_for(hall) == license_source_entity_id(lodging)
    assert index.winner_for(named_sauna) is None
    assert index.winner_for(elsewhere) is None


# -- 원천 좌표 없는 행의 정지오코딩 (docs §7) ----------------------------------------


async def test_address_geocoder_supplies_a_point_only_when_the_source_has_none() -> None:
    """공용 원천 좌표 결측 fallback(#1463)을 쓴다 — 같은 주소는 한 번, 원천 법정동이 이긴다."""
    calls: list[str | None] = []

    async def geocode(address: Address) -> Coordinate | None:
        calls.append(address.road)
        return Coordinate(lon=Decimal("127.1"), lat=Decimal("37.5"))

    no_point = _Record(
        service_slug="lodgings", mng_no="N-1", road_address="서울특별시 송파구 올림픽로 300",
        legal_dong_code="1171010200",
    )
    has_point = dataclasses.replace(no_point, mng_no="N-2", lon=127.0, lat=37.4)
    duplicate = dataclasses.replace(no_point, mng_no="N-3")
    district_only = dataclasses.replace(
        no_point, mng_no="N-4", road_address="서울특별시 송파구", lot_address=None
    )
    bundles = await _bundles(
        [no_point, has_point, duplicate, district_only], address_geocoder=geocode
    )

    # 같은 주소는 한 번, 번지 없는 주소는 묻지 않는다.
    assert calls == ["서울특별시 송파구 올림픽로 300"]
    located = bundles[0].feature
    assert located.coord is not None
    assert float(located.coord.lon) == pytest.approx(127.1)
    assert located.address.bjd_code == "1171010200"
    assert located.detail.payload["coord_source"] == "kor_travel_geo_geocode"
    assert "coord_source" not in bundles[1].feature.detail.payload
    kept = bundles[1].feature.coord
    assert kept is not None
    assert float(kept.lon) == pytest.approx(127.0)
    assert bundles[3].feature.coord is None


async def test_located_point_is_reverse_geocoded_when_the_source_has_no_code() -> None:
    async def geocode(_address: Address) -> Coordinate | None:
        return Coordinate(lon=Decimal("127.1"), lat=Decimal("37.5"))

    reverse = _FakeGeocoder(Address(bjd_code="1171010100", sigungu_code="11710", sido_code="11"))
    record = _Record(service_slug="lodgings", road_address="서울특별시 송파구 올림픽로 300")
    [bundle] = await _bundles([record], address_geocoder=geocode, reverse_geocoder=reverse)
    assert reverse.calls == 1
    assert bundle.feature.address.bjd_code == "1171010100"
    assert bundle.geo_attempt is not None
    assert bundle.geo_attempt.reverse_attempted, "스탬프는 called — geo 릴리스가 바뀌면 다시 푼다"


async def test_address_geocoder_miss_leaves_the_row_without_a_point() -> None:
    async def geocode(_address: Address) -> None:
        return None

    record = _Record(service_slug="lodgings", road_address="어딘가 1", legal_dong_code="1111010100")
    [bundle] = await _bundles([record], address_geocoder=geocode)
    assert bundle.feature.coord is None
    assert "coord_source" not in bundle.feature.detail.payload
