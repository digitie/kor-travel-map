from __future__ import annotations

from dataclasses import dataclass

from kraddr.base import Address

from krtour_map.addressing import enrich_address_from_coordinate
from krtour_map.models import Coordinate


@dataclass(frozen=True)
class KrAddrReverseResult:
    road_address: str
    legal_dong_code: str
    road_name_code: str
    building_management_number: str
    postal_code: str


def test_enrich_address_from_coordinate_fills_legal_dong_code() -> None:
    result = enrich_address_from_coordinate(
        address=Address(address="서울 종로구 세종대로 1"),
        coordinate=Coordinate(lat=37.5796, lon=126.9769),
        raw={},
        reverse_geocoder=lambda _coord: {
            "road_address": "서울 종로구 세종대로 1",
            "legal_dong_code": "1111011900",
        },
        source_label="test_source",
        source_entity_id="100",
    )

    assert result.address.display_address == "서울 종로구 세종대로 1"
    assert result.address.legal_dong_code == "1111011900"
    assert result.report.match_level == "coordinate_legal_dong"
    assert result.report.confidence == 90
    assert result.report.code_source == "coordinate_reverse_geocode"


def test_enrich_address_accepts_kraddr_geo_reverse_result_object() -> None:
    result = enrich_address_from_coordinate(
        address=Address(address="서울특별시 중구 세종대로 110"),
        coordinate=Coordinate(lat=37.5663, lon=126.9779),
        raw={},
        reverse_geocoder=lambda _coord: KrAddrReverseResult(
            road_address="서울특별시 중구 세종대로 110",
            legal_dong_code="1114010300",
            road_name_code="111402005001",
            building_management_number="1114010300100310000000001",
            postal_code="04524",
        ),
        source_label="test_source",
        source_entity_id="100",
    )

    assert result.address.legal_dong_code == "1114010300"
    assert result.address.road_name is not None
    assert result.address.road_name.effective_road_name_code is not None
    assert result.address.road_name.effective_road_name_code.code == "111402005001"
    assert result.report.match_level == "coordinate_legal_dong"


def test_enrich_address_converts_valid_sigungu_code_to_legal_dong_code() -> None:
    result = enrich_address_from_coordinate(
        address=Address(address="서울 종로구"),
        raw={"sggCd": "11110"},
        source_label="test_source",
    )

    assert result.address.legal_dong_code == "1111000000"
    assert result.report.match_level == "sigungu_code_only"
    assert result.report.confidence == 65


def test_enrich_address_converts_road_name_components_to_legal_dong_code() -> None:
    result = enrich_address_from_coordinate(
        address=Address(address="서울 종로구 세종대로 1"),
        raw={
            "admCd": "1111011900",
            "rnMgtSn": "111104100001",
            "udrtYn": "0",
            "buldMnnm": "1",
            "buldSlno": "0",
        },
        source_label="test_source",
    )

    assert result.address.legal_dong_code == "1111011900"
    assert result.address.road_name is not None
    assert result.address.road_name.effective_road_name_code is not None
    assert result.report.match_level == "provider_code_converted"


def test_provider_specific_address_code_is_reported_but_not_saved_as_legal_dong() -> None:
    result = enrich_address_from_coordinate(
        address=Address(address="서울 강남구 테헤란로 1"),
        raw={"sigun_code": "0113"},
        source_label="opinet",
        source_entity_id="A0010207",
    )

    assert result.address.legal_dong_code is None
    assert result.report.provider_code_type == "sigun_code"
    assert result.report.provider_code_value == "0113"
    assert result.report.match_level == "address_text_only"
    assert "provider-specific address code" in result.report.notes[-1]
