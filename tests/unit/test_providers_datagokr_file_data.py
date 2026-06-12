"""``test_providers_datagokr_file_data`` — data.go.kr fileData curated source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.category import PlaceCategoryCode, is_known_category_code
from kortravelmap.dto import Address, Coordinate, FeatureKind, SourceRole
from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_DATASETS,
    DATAGOKR_FILEDATA_FOOD_MARKER_COLOR,
    DATAGOKR_FILEDATA_PROVIDER_NAME,
    file_data_rows_to_bundles,
)

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 6, 12, 18, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Record:
    raw: dict[str, Any]


async def _fake_reverse(_coord: Coordinate) -> Address:
    return Address(bjd_code="1114016200", sigungu_code="11140", sido_code="11")


@pytest.mark.unit
def test_dataset_table_covers_curated_filedata_sources() -> None:
    assert set(DATAGOKR_FILEDATA_DATASETS) == {
        "datagokr_seoul_bookstores",
        "datagokr_gyeonggi_muslim_friendly_restaurants",
        "datagokr_ansan_world_restaurants",
        "datagokr_jeju_local_restaurants",
    }
    for spec in DATAGOKR_FILEDATA_DATASETS.values():
        assert spec.dataset_key
        assert is_known_category_code(spec.category)
        assert spec.place_kind
        assert spec.entity_type


async def test_seoul_bookstore_raw_record_to_bundle() -> None:
    record = _Record(
        raw={
            "책방명": "이상한나라의헌책방",
            "주소": "서울특별시 중구 청계천로 274",
            "전화번호": "02-2266-1234",
            "책방구분명": "헌책방",
            "홈페이지": "https://example.test/book",
            "위도": "37.568533",
            "경도": "127.007754",
        }
    )

    [bundle] = await file_data_rows_to_bundles(
        [record],
        dataset_key="datagokr_seoul_bookstores",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )

    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "이상한나라의헌책방"
    assert feature.category == PlaceCategoryCode.TOURISM_CULTURAL_FACILITY.value
    assert feature.coord == Coordinate(lon=Decimal("127.007754"), lat=Decimal("37.568533"))
    assert feature.address.bjd_code == "1114016200"
    assert feature.detail.place_kind == "seoul_bookstore"  # type: ignore[union-attr]
    assert feature.detail.phones == ["02-2266-1234"]  # type: ignore[union-attr]
    assert feature.detail.facility_info["source_category"] == "헌책방"  # type: ignore[union-attr]

    source = bundle.source_record
    assert source.provider == DATAGOKR_FILEDATA_PROVIDER_NAME
    assert source.dataset_key == "datagokr_seoul_bookstores"
    assert source.source_entity_type == "bookstore"
    assert source.source_entity_id == "이상한나라의헌책방::서울특별시 중구 청계천로 274"
    assert source.raw_data["책방명"] == "이상한나라의헌책방"
    assert bundle.source_link.source_role == SourceRole.PRIMARY


@pytest.mark.unit
@pytest.mark.parametrize(
    ("dataset_key", "row", "place_kind", "facility_key", "facility_value"),
    [
        (
            "datagokr_gyeonggi_muslim_friendly_restaurants",
            {
                "지역": "수원",
                "종류": "무슬림 프렌들리",
                "상호": "수원할랄키친",
                "주소": "경기도 수원시 팔달구 정조로 1",
                "연락처": "031-111-2222",
            },
            "muslim_friendly_restaurant",
            "source_category",
            "무슬림 프렌들리",
        ),
        (
            "datagokr_ansan_world_restaurants",
            {
                "가게명": "안산월드푸드",
                "게시글 내용": "다문화 음식점",
                "음식종류": "중앙아시아",
                "연락처": "031-333-4444",
                "주소": "경기도 안산시 단원구 원곡동",
            },
            "ansan_world_restaurant",
            "description",
            "다문화 음식점",
        ),
        (
            "datagokr_jeju_local_restaurants",
            {
                "지정번호": "JEJU-001",
                "관리기관": "제주특별자치도",
                "업소명": "제주향토밥상",
                "소재지": "제주특별자치도 제주시 관덕로 1",
                "향토음식 주메뉴": "갈치국",
                "연락처": "064-123-4567",
                "데이터기준일자": "2025-11-20",
            },
            "jeju_local_restaurant",
            "source_category",
            "갈치국",
        ),
    ],
)
async def test_restaurant_filedata_dialects(
    dataset_key: str,
    row: dict[str, Any],
    place_kind: str,
    facility_key: str,
    facility_value: str,
) -> None:
    [bundle] = await file_data_rows_to_bundles([row], dataset_key=dataset_key, fetched_at=_NOW)

    feature = bundle.feature
    assert feature.category == PlaceCategoryCode.FOOD_RESTAURANT.value
    assert feature.marker_color == DATAGOKR_FILEDATA_FOOD_MARKER_COLOR
    assert feature.detail.place_kind == place_kind  # type: ignore[union-attr]
    assert feature.detail.facility_info[facility_key] == facility_value  # type: ignore[union-attr]
    assert bundle.source_record.dataset_key == dataset_key


async def test_filedata_unknown_dataset_raises() -> None:
    with pytest.raises(KeyError):
        await file_data_rows_to_bundles(
            [{"상호": "가게", "주소": "어딘가"}],
            dataset_key="datagokr_unknown",
            fetched_at=_NOW,
        )


async def test_filedata_skips_unidentifiable_rows() -> None:
    bundles = await file_data_rows_to_bundles(
        [
            {"상호": "", "주소": "서울특별시 어딘가"},
            {"상호": "주소없는가게"},
            {"상호": "정상가게", "주소": "서울특별시 중구 세종대로 1"},
        ],
        dataset_key="datagokr_gyeonggi_muslim_friendly_restaurants",
        fetched_at=_NOW,
    )
    assert len(bundles) == 1
    assert bundles[0].feature.name == "정상가게"
