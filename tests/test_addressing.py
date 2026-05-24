from __future__ import annotations

from dataclasses import dataclass

from kraddr.base import Address

from krtour_map.addressing import (
    enrich_address_from_coordinate,
    kraddr_geo_address_geocoder,
    kraddr_geo_reverse_geocoder,
    resolve_address_geocoder,
    resolve_reverse_geocoder,
)
from krtour_map.models import Coordinate
from krtour_map.providers import normalize_provider_name


@dataclass(frozen=True)
class KrAddrReverseResult:
    road_address: str
    legal_dong_code: str
    road_name_code: str
    building_management_number: str
    postal_code: str


class FakeKrAddrGeoStore:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], bool]] = []
        self.coord_calls: list[tuple[dict[str, object], bool]] = []

    def get_coord(
        self,
        request: dict[str, object],
        *,
        fallback: bool = True,
    ) -> list[dict[str, object]]:
        self.coord_calls.append((request, fallback))
        return [
            {
                "x": 126.9779,
                "y": 37.5663,
                "crs": "EPSG:4326",
                "road_address": "서울특별시 중구 세종대로 110",
                "legal_dong_code": "1114010300",
            }
        ]

    def get_address(
        self,
        request: dict[str, object],
        *,
        fallback: bool = True,
    ) -> KrAddrReverseResult:
        self.calls.append((request, fallback))
        return KrAddrReverseResult(
            road_address="서울특별시 중구 세종대로 110",
            legal_dong_code="1114010300",
            road_name_code="111402005001",
            building_management_number="1114010300100310000000001",
            postal_code="04524",
        )


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


def test_kraddr_geo_reverse_geocoder_uses_store_get_address() -> None:
    store = FakeKrAddrGeoStore()
    reverse_geocoder = kraddr_geo_reverse_geocoder(store=store, fallback=True)

    result = enrich_address_from_coordinate(
        address=Address(address="서울특별시 중구 세종대로 110"),
        coordinate=Coordinate(lat=37.5663, lon=126.9779),
        raw={},
        reverse_geocoder=reverse_geocoder,
        source_label="test_source",
    )

    assert result.address.legal_dong_code == "1114010300"
    assert store.calls[0][0]["x"] == 126.9779
    assert store.calls[0][0]["y"] == 37.5663
    assert store.calls[0][1] is True


def test_resolve_reverse_geocoder_from_kraddr_geo_store_resource() -> None:
    store = FakeKrAddrGeoStore()
    reverse_geocoder = resolve_reverse_geocoder(
        {
            "kraddr_geo_store": store,
            "kraddr_geo_fallback": "false",
            "kraddr_geo_max_distance_m": 120,
        }
    )

    assert reverse_geocoder is not None
    address = reverse_geocoder(Coordinate(lat=37.5663, lon=126.9779))
    assert isinstance(address, Address)
    assert address.legal_dong_code == "1114010300"
    assert store.calls[0][0]["max_distance_m"] == 120.0
    assert store.calls[0][1] is False


def test_kraddr_geo_address_geocoder_fills_missing_coordinate() -> None:
    store = FakeKrAddrGeoStore()
    address_geocoder = kraddr_geo_address_geocoder(store=store, fallback=False)

    result = enrich_address_from_coordinate(
        address=Address(address="서울특별시 중구 세종대로 110"),
        raw={},
        address_geocoder=address_geocoder,
        source_label="test_source",
    )

    assert result.coordinate is not None
    assert result.coordinate.latitude == 37.5663
    assert result.coordinate.longitude == 126.9779
    assert result.address.legal_dong_code == "1114010300"
    assert result.report.match_level == "address_geocode_legal_dong"
    assert store.coord_calls[0][1] is False


def test_resolve_address_geocoder_from_kraddr_geo_store_resource() -> None:
    store = FakeKrAddrGeoStore()
    address_geocoder = resolve_address_geocoder({"kraddr_geo_store": store})

    assert address_geocoder is not None
    coordinate = address_geocoder(Address(address="서울특별시 중구 세종대로 110"))
    assert isinstance(coordinate, dict)
    assert coordinate["x"] == 126.9779


def test_vworld_is_not_a_direct_krtour_map_provider() -> None:
    try:
        normalize_provider_name("vworld")
    except ValueError as exc:
        assert "Unsupported provider" in str(exc)
    else:  # pragma: no cover - defensive assertion.
        raise AssertionError("vworld should not normalize as a direct provider")


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
