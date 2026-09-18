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


#: 2026-09-19 라이브 OA-21062 응답 1행(`TbSlibBookstoreInfo`)을 그대로 옮긴 것.
#:
#: 손으로 다듬지 않는다 — `STORE_TYPE_NAME`의 꼬리 공백까지 원천이 실제로 주는
#: 모양이고, 그 모양이 변환을 지나는지가 여기서 세는 것이다.
_SEOUL_OPEN_DATA_ROW = {
    "STORE_SEQ_NO": 2283.0,
    "STORE_NAME": "1984",
    "GU_CODE": "313",
    "CODE_VALUE": "마포구",
    "ADRES": "마포구 동교로 194 혜원빌딩",
    "TEL_NO": "02-325-1984",
    "HMPG_URL": "",
    "STORE_TYPE": "0002",
    "STORE_TYPE_NAME": "새책방      ",
    "XCNTS": "37.5573847248586",
    "YDNTS": "126.922886096614",
    "SNS": "https://www.instagram.com/1984store",
}


async def test_seoul_open_data_row_to_bundle() -> None:
    """서울 열린데이터광장(OA-21062) row도 같은 dialect를 지나야 한다.

    종전 원천인 data.go.kr odcloud는 2026-09-18 기준 404 `등록되지 않은 서비스
    입니다`로 사라졌다. dataset_key와 provider 이름은 레지스트리 신원이라 그대로
    두고 **원천만** 옮겼으므로, 같은 dataset이 두 벌의 열 이름을 받는다.
    """

    [bundle] = await file_data_rows_to_bundles(
        [_Record(raw=dict(_SEOUL_OPEN_DATA_ROW))],
        dataset_key="datagokr_seoul_bookstores",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )

    feature = bundle.feature
    assert feature.name == "1984"
    assert feature.detail.place_kind == "seoul_bookstore"  # type: ignore[union-attr]
    assert feature.detail.phones == ["02-325-1984"]  # type: ignore[union-attr]
    facility = feature.detail.facility_info  # type: ignore[union-attr]
    assert facility["source_category"] == "새책방"
    assert facility["district"] == "마포구"
    assert facility["sns_url"] == "https://www.instagram.com/1984store"
    # 원천이 시(市)를 빼고 준다 — 주소는 주소대로 온전해야 한다.
    assert feature.address.road == "서울특별시 마포구 동교로 194 혜원빌딩"
    # 자연키는 표기가 아니라 값이다 — 원천이 2283.0을 "2283"으로 바꿔도 같아야 한다.
    assert bundle.source_record.source_entity_id == "2283"


async def test_the_seoul_open_data_axes_are_not_swapped() -> None:
    """**`XCNTS`가 위도이고 `YDNTS`가 경도다.**

    X를 경도로 읽는 통념대로 일반 키 목록에 넣으면 조용히 뒤집힌 좌표가 들어온다.
    한국 bbox 검사(`_validated_lonlat`)가 그물이 되어 주지만 그것은 그물이지
    근거가 아니다 — 축을 명시했다는 사실을 여기서 못박는다.
    """

    [bundle] = await file_data_rows_to_bundles(
        [_Record(raw=dict(_SEOUL_OPEN_DATA_ROW))],
        dataset_key="datagokr_seoul_bookstores",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )

    coord = bundle.feature.coord
    assert coord is not None
    # 마포구 동교동 — 경도 126.92, 위도 37.55.
    assert float(coord.lon) == pytest.approx(126.922886, abs=1e-5)
    assert float(coord.lat) == pytest.approx(37.557384, abs=1e-5)


async def test_the_seoul_address_prefix_is_not_doubled() -> None:
    """원천이 언젠가 시 이름을 붙여 주기 시작해도 두 번 붙지 않는다."""

    row = dict(_SEOUL_OPEN_DATA_ROW)
    row["ADRES"] = "서울특별시 마포구 동교로 194"

    [bundle] = await file_data_rows_to_bundles(
        [_Record(raw=row)],
        dataset_key="datagokr_seoul_bookstores",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )

    assert bundle.feature.address.road == "서울특별시 마포구 동교로 194"
