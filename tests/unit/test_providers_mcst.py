"""``test_providers_mcst`` — MCST(KCISA/ODCloud) → place FeatureBundle (T-220a)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.category import PlaceCategoryCode, is_known_category_code
from krtour.map.dto import Address, Coordinate, FeatureKind
from krtour.map.providers.mcst import (
    MCST_CULTURE_DATASETS,
    MCST_LIBRARY_DATASETS,
    MCST_MARKER_COLOR,
    MCST_PROVIDER_NAME,
    culture_records_to_bundles,
    library_records_to_bundles,
)

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 6, 11, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _CultureItem:
    """``McstCultureItem`` Protocol 만족 dataclass (mcst ``CultureRecord`` 대역)."""

    name: str | None = "테스트 서점"
    address: str | None = "서울특별시 종로구 세종대로 1"
    tel: str | None = "02-000-0000"
    url: str | None = "https://example.com"
    longitude: float | None = 126.978
    latitude: float | None = 37.5665
    category: str | None = "서점"
    raw: dict[str, Any] = field(default_factory=dict)


async def _fake_reverse(_coord: Coordinate) -> Address:
    return Address(
        admin="서울특별시 종로구 세종로",
        bjd_code="1111010100",
        sido_name="서울특별시",
        sigungu_name="종로구",
    )


# -- slug 메타표 전수 -------------------------------------------------------


@pytest.mark.unit
def test_culture_dataset_table_covers_all_14_kcisa_slugs() -> None:
    assert len(MCST_CULTURE_DATASETS) == 14
    assert set(MCST_CULTURE_DATASETS) == {
        "media_famous_places",
        "barrier_free_places",
        "pet_friendly_culture_facilities",
        "leisure_activity_facilities",
        "leisure_camping_facilities",
        "leisure_classes",
        "family_infant_culture_facilities",
        "multilingual_guide_culture_facilities",
        "world_restaurants",
        "small_theaters",
        "meeting_seminar_facilities",
        "independent_bookstores",
        "cafe_bookstores",
        "recommended_travel_destinations",
    }


@pytest.mark.unit
def test_dataset_specs_use_existing_categories_and_key_convention() -> None:
    """category는 전부 기존 코드(신설 X), dataset_key는 ``mcst_<slug>``."""
    for spec in [*MCST_CULTURE_DATASETS.values(), *MCST_LIBRARY_DATASETS.values()]:
        assert spec.dataset_key == f"mcst_{spec.slug}"
        assert is_known_category_code(spec.category), spec.slug
        assert spec.place_kind
        assert spec.label


@pytest.mark.unit
def test_library_dataset_table_covers_both_odcloud_slugs() -> None:
    assert set(MCST_LIBRARY_DATASETS) == {"public_libraries", "small_libraries"}
    for spec in MCST_LIBRARY_DATASETS.values():
        assert (
            spec.category
            == PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_LIBRARY.value
        )


# -- culture 변환 ------------------------------------------------------------


async def test_culture_bundle_core_fields_and_reverse_enrichment() -> None:
    [bundle] = await culture_records_to_bundles(
        [_CultureItem()],
        slug="independent_bookstores",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )

    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "테스트 서점"
    assert feature.category == PlaceCategoryCode.TOURISM_CULTURAL_FACILITY.value
    assert feature.marker_color == MCST_MARKER_COLOR
    assert feature.coord == Coordinate(
        lon=Decimal("126.978"), lat=Decimal("37.5665")
    )
    assert feature.address.bjd_code == "1111010100"
    assert feature.detail is not None
    assert feature.detail.place_kind == "independent_bookstore"  # type: ignore[union-attr]
    assert feature.detail.facility_info["source_category"] == "서점"  # type: ignore[union-attr]

    src = bundle.source_record
    assert src.provider == MCST_PROVIDER_NAME
    assert src.dataset_key == "mcst_independent_bookstores"
    assert src.source_entity_type == "culture_place"
    assert src.source_entity_id == "테스트 서점::서울특별시 종로구 세종대로 1"
    assert src.raw_address == "서울특별시 종로구 세종대로 1"
    assert bundle.source_link.is_primary_source is True


async def test_culture_without_coord_keeps_address_clue() -> None:
    [bundle] = await culture_records_to_bundles(
        [_CultureItem(longitude=None, latitude=None)],
        slug="cafe_bookstores",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )
    assert bundle.feature.coord is None
    # 좌표가 없으면 reverse 미호출 — provider 주소 텍스트가 위치 단서.
    assert bundle.feature.address.bjd_code is None
    assert bundle.feature.address.admin == "서울특별시 종로구 세종대로 1"
    assert bundle.source_record.raw_address == "서울특별시 종로구 세종대로 1"


async def test_culture_skips_unidentifiable_rows() -> None:
    bundles = await culture_records_to_bundles(
        [
            _CultureItem(name=None),
            _CultureItem(address=None, longitude=None, latitude=None),
            _CultureItem(),
        ],
        slug="world_restaurants",
        fetched_at=_NOW,
    )
    assert len(bundles) == 1


async def test_culture_unknown_slug_raises() -> None:
    with pytest.raises(KeyError):
        await culture_records_to_bundles(
            [_CultureItem()], slug="nope", fetched_at=_NOW
        )


# -- library 변환 -------------------------------------------------------------


_LIBRARY_ROW: dict[str, Any] = {
    "도서관명": "종로도서관",
    "시도명": "서울특별시",
    "시군구명": "종로구",
    "소재지도로명주소": "서울특별시 종로구 사직로9길 15-14",
    "위도": "37.5765",
    "경도": "126.9685",
    "전화번호": "02-721-0707",
    "홈페이지주소": "https://jnlib.example",
    "도서관유형": "공공도서관",
}


async def test_library_bundle_maps_korean_columns() -> None:
    [bundle] = await library_records_to_bundles(
        [_LIBRARY_ROW],
        slug="public_libraries",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )

    feature = bundle.feature
    assert feature.name == "종로도서관"
    assert (
        feature.category
        == PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_LIBRARY.value
    )
    assert feature.coord == Coordinate(
        lon=Decimal("126.9685"), lat=Decimal("37.5765")
    )
    assert feature.detail.place_kind == "public_library"  # type: ignore[union-attr]
    assert feature.detail.facility_info["library_type"] == "공공도서관"  # type: ignore[union-attr]
    assert feature.detail.facility_info["tel"] == "02-721-0707"  # type: ignore[union-attr]
    src = bundle.source_record
    assert src.dataset_key == "mcst_public_libraries"
    assert src.source_entity_type == "library"
    assert src.raw_data["도서관명"] == "종로도서관"


async def test_library_column_dialects_and_skip() -> None:
    rows: list[dict[str, Any]] = [
        # 방언: 작은도서관명/소재지/좌표 없음 — 주소 단서로 통과.
        {"작은도서관명": "마을 작은도서관", "소재지": "강원특별자치도 춘천시 1"},
        # 이름 없음 — skip.
        {"소재지": "어딘가"},
        # 좌표·주소 모두 없음 — skip.
        {"도서관명": "유령도서관"},
    ]
    bundles = await library_records_to_bundles(
        rows, slug="small_libraries", fetched_at=_NOW
    )
    [bundle] = bundles
    assert bundle.feature.name == "마을 작은도서관"
    assert bundle.feature.coord is None
    assert bundle.feature.detail.place_kind == "small_library"  # type: ignore[union-attr]
    assert bundle.source_record.raw_address == "강원특별자치도 춘천시 1"


async def test_library_invalid_coord_text_treated_as_missing() -> None:
    row = dict(_LIBRARY_ROW, 위도="없음", 경도="")
    [bundle] = await library_records_to_bundles(
        [row], slug="public_libraries", fetched_at=_NOW
    )
    assert bundle.feature.coord is None


async def test_same_row_is_deterministic_and_id_stable() -> None:
    a = (
        await culture_records_to_bundles(
            [_CultureItem()], slug="small_theaters", fetched_at=_NOW
        )
    )[0]
    b = (
        await culture_records_to_bundles(
            [_CultureItem()], slug="small_theaters", fetched_at=_NOW
        )
    )[0]
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key
