"""``test_providers_mcst`` — MCST 파일데이터(CSV) → place FeatureBundle (#395)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.category import PlaceCategoryCode, is_known_category_code
from krtour.map.dto import Address, Coordinate, FeatureKind
from krtour.map.providers.mcst import (
    MCST_EXCLUDED_FILE_DATASETS,
    MCST_FILE_DATASETS,
    MCST_MARKER_COLOR,
    MCST_PROVIDER_NAME,
    file_rows_to_bundles,
    parse_kcisa_coordinates,
)

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 6, 12, 12, 0, tzinfo=_KST)


async def _fake_reverse(_coord: Coordinate) -> Address:
    return Address(
        admin="서울특별시 종로구 세종로",
        bjd_code="1111010100",
        sido_name="서울특별시",
        sigungu_name="종로구",
    )


def _world_restaurant_row(**overrides: Any) -> dict[str, Any]:
    """공통 방언 A 실측 샘플 (world_restaurants_csv)."""
    row: dict[str, Any] = {
        "TITLE": "과카몰레",
        "ISSUEDDATE": "2022-11-30",
        "CATEGORY1": "음식점/유흥시설",
        "CATEGORY2": "남미음식",
        "CATEGORY3": "",
        "INFORMATION": "무료주차 불가|발렛주차 불가",
        "TEL": "0507-1368-9998",
        "OPERATINGTIME": "월-금 11시-21시30분",
        "ADDRESS": "(17982)경기도 평택시 팽성읍 안정순환로222번길 92",
        "COORDINATES": "N36.960756, E127.043367",
        "RNUM": "1",
    }
    row.update(overrides)
    return row


# -- slug 메타표 전수 -------------------------------------------------------


@pytest.mark.unit
def test_file_dataset_table_covers_all_12_loaded_slugs() -> None:
    assert len(MCST_FILE_DATASETS) == 12
    assert set(MCST_FILE_DATASETS) == {
        # KCISA 공통 방언 A (8종)
        "world_restaurants_csv",
        "pet_friendly_culture_facilities_csv",
        "barrier_free_places_csv",
        "leisure_activity_facilities_csv",
        "family_infant_culture_facilities_csv",
        "leisure_camping_facilities_csv",
        "leisure_classes_csv",
        "media_famous_places_csv",
        # CNTC_RESRCE (2종)
        "independent_bookstores_csv",
        "cafe_bookstores_csv",
        # 분리좌표 (1종)
        "children_bookstores_csv",
        # 한국어 주소-only (1종)
        "golf_courses_status",
    }


@pytest.mark.unit
def test_excluded_dataset_table_documents_3_slugs_with_reason() -> None:
    assert set(MCST_EXCLUDED_FILE_DATASETS) == {
        "tourism_attractions_csv",
        "recommended_travel_destinations_csv",
        "public_libraries",
    }
    # 적재/제외가 겹치지 않는다.
    assert not set(MCST_EXCLUDED_FILE_DATASETS) & set(MCST_FILE_DATASETS)
    for reason in MCST_EXCLUDED_FILE_DATASETS.values():
        assert reason


@pytest.mark.unit
def test_dataset_specs_use_existing_categories_and_key_convention() -> None:
    """category는 전부 기존 코드(신설 X), dataset_key는 ``mcst_<slug>``."""
    for spec in MCST_FILE_DATASETS.values():
        assert spec.dataset_key == f"mcst_{spec.slug}"
        assert is_known_category_code(spec.category), spec.slug
        assert spec.place_kind
        assert spec.label
        assert spec.dialect in {
            "kcisa_common",
            "cntc_resrce",
            "split_coord",
            "korean_address",
        }


# -- COORDINATES 파서 ---------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 실측 형식 1 — N/E 접두, lat-lon 순.
        ("N37.545904, E126.92094", (126.92094, 37.545904)),
        ("N36.960756, E127.043367", (127.043367, 36.960756)),
        # 실측 형식 2 — 평문 lat-lon 순 (콤마 주위 공백 변형).
        ("35.86561079 , 128.6083915", (128.6083915, 35.86561079)),
        # 실측 변형 — 콤마 없이 공백만 (cafe_bookstores_csv).
        ("37.54497283 126.9676467", (126.9676467, 37.54497283)),
        # 순서 뒤집힘 — bbox로 감지해 교정.
        ("128.6083915, 35.86561079", (128.6083915, 35.86561079)),
    ],
)
def test_parse_kcisa_coordinates_valid(
    text: str, expected: tuple[float, float]
) -> None:
    assert parse_kcisa_coordinates(text) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "주소문자열",
        "37.5",  # 토큰 1개
        "37.5, 126.9, 99",  # 토큰 3개
        "N37.5, N126.9",  # 축 중복
        "1.0, 2.0",  # 한국 bbox 밖 (swap해도 밖)
        "-37.5, 126.9",  # 남반구 — bbox 밖
    ],
)
def test_parse_kcisa_coordinates_invalid_returns_none(text: str | None) -> None:
    assert parse_kcisa_coordinates(text) is None


# -- 공통 방언 A --------------------------------------------------------------


async def test_kcisa_common_bundle_core_fields_and_reverse_enrichment() -> None:
    [bundle] = await file_rows_to_bundles(
        [_world_restaurant_row()],
        slug="world_restaurants_csv",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )

    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "과카몰레"
    assert feature.category == PlaceCategoryCode.FOOD_RESTAURANT.value
    assert feature.marker_color == MCST_MARKER_COLOR
    assert feature.coord == Coordinate(
        lon=Decimal("127.043367"), lat=Decimal("36.960756")
    )
    assert feature.address.bjd_code == "1111010100"
    assert feature.detail is not None
    assert feature.detail.place_kind == "world_restaurant"  # type: ignore[union-attr]
    facility = feature.detail.facility_info  # type: ignore[union-attr]
    assert facility["source_category"] == "음식점/유흥시설 > 남미음식"
    assert facility["tel"] == "0507-1368-9998"

    src = bundle.source_record
    assert src.provider == MCST_PROVIDER_NAME
    assert src.dataset_key == "mcst_world_restaurants_csv"
    assert src.source_entity_type == "culture_place"
    assert (
        src.source_entity_id
        == "과카몰레::(17982)경기도 평택시 팽성읍 안정순환로222번길 92"
    )
    # raw_data는 CSV row 원본 보존.
    assert src.raw_data["COORDINATES"] == "N36.960756, E127.043367"
    assert bundle.source_link.is_primary_source is True


async def test_kcisa_common_placeholder_url_dropped() -> None:
    """실측 placeholder(``정보없음``)는 facility_info에서 제외."""
    [bundle] = await file_rows_to_bundles(
        [_world_restaurant_row(URL="정보없음")],
        slug="leisure_activity_facilities_csv",
        fetched_at=_NOW,
    )
    assert "url" not in bundle.feature.detail.facility_info  # type: ignore[union-attr]


async def test_media_famous_places_uses_placename_and_media_title() -> None:
    row = {
        "PLACENAME": "노보카인",
        "FORMAT": "drama",
        "MEDIATITLE": "미치겠다, 너땜에!",
        "ADDRESS": "(04074)서울특별시 마포구 와우산로3길 36",
        "TEL": "070-8650-7776",
        "COORDINATES": "N37.545904, E126.92094",
        "RNUM": "1",
    }
    [bundle] = await file_rows_to_bundles(
        [row], slug="media_famous_places_csv", fetched_at=_NOW
    )
    assert bundle.feature.name == "노보카인"
    assert bundle.feature.coord == Coordinate(
        lon=Decimal("126.92094"), lat=Decimal("37.545904")
    )
    facility = bundle.feature.detail.facility_info  # type: ignore[union-attr]
    assert facility["media_title"] == "미치겠다, 너땜에!"


async def test_leisure_classes_without_coordinates_keeps_address_clue() -> None:
    """leisure_classes_csv는 좌표 컬럼이 없다(실측) — 주소 단서 경로."""
    row = {
        "TITLE": "원데이 캘리그라피 취미반",
        "CATEGORY1": "여가활동",
        "CATEGORY2": "클래스",
        "CATEGORY3": "캘리그래피",
        "ADDRESS": "서울특별시 강북구 수유동",
        "RNUM": "1",
    }
    [bundle] = await file_rows_to_bundles(
        [row],
        slug="leisure_classes_csv",
        fetched_at=_NOW,
        reverse_geocoder=_fake_reverse,
    )
    assert bundle.feature.coord is None
    # 좌표가 없으면 reverse 미호출 — provider 주소 텍스트가 위치 단서.
    assert bundle.feature.address.bjd_code is None
    assert bundle.feature.address.admin == "서울특별시 강북구 수유동"
    assert bundle.source_record.raw_address == "서울특별시 강북구 수유동"


async def test_invalid_coordinates_fall_back_to_address_clue() -> None:
    [bundle] = await file_rows_to_bundles(
        [_world_restaurant_row(COORDINATES="좌표없음")],
        slug="world_restaurants_csv",
        fetched_at=_NOW,
    )
    assert bundle.feature.coord is None
    assert bundle.source_record.raw_address is not None


# -- CNTC_RESRCE 방언 ---------------------------------------------------------


async def test_cntc_resrce_bundle_maps_columns_and_plain_coordinates() -> None:
    row = {
        "CNTC_RESRCE_ID": "B553457-04-012",
        "CNTC_RESRCE_NO": "1",
        "TITLE": "굿브랜딩북스",
        "ISSUED_DATE": "2024-10-23",
        "SUBJECT_KEYWORD": "독립서점 , 일반",
        "ADDRESS": "(41946) 대구광역시 중구 달구벌대로447길 72-1",
        "CONTACT_POINT": "0534261765",
        "COORDINATES": "35.86561079 , 128.6083915",
        "RNUM": "1",
    }
    [bundle] = await file_rows_to_bundles(
        [row], slug="independent_bookstores_csv", fetched_at=_NOW
    )
    feature = bundle.feature
    assert feature.name == "굿브랜딩북스"
    assert feature.category == PlaceCategoryCode.TOURISM_CULTURAL_FACILITY.value
    assert feature.coord == Coordinate(
        lon=Decimal("128.6083915"), lat=Decimal("35.86561079")
    )
    assert feature.detail.place_kind == "independent_bookstore"  # type: ignore[union-attr]
    facility = feature.detail.facility_info  # type: ignore[union-attr]
    assert facility["tel"] == "0534261765"
    assert facility["cntc_resrce_id"] == "B553457-04-012"
    assert bundle.source_record.dataset_key == "mcst_independent_bookstores_csv"


# -- 분리좌표 방언 ------------------------------------------------------------


async def test_split_coord_bundle_maps_fclty_columns() -> None:
    row = {
        "RNUM": "1",
        "ESNTL_ID": "KCCBSPO22N000000085",
        "FCLTY_NM": "평촌어린이서점스펀지북",
        "LCLAS_NM": "아동서점",
        "MLSFC_NM": "아동서적",
        "FCLTY_ROAD_NM_ADDR": "경기 안양시 동안구 흥안대로 460 1층",
        "FCLTY_LA": "37.39513617",
        "FCLTY_LO": "126.9760656",
        "TEL_NO": "314225455",
    }
    [bundle] = await file_rows_to_bundles(
        [row], slug="children_bookstores_csv", fetched_at=_NOW
    )
    feature = bundle.feature
    assert feature.name == "평촌어린이서점스펀지북"
    assert feature.coord == Coordinate(
        lon=Decimal("126.9760656"), lat=Decimal("37.39513617")
    )
    assert feature.detail.place_kind == "children_bookstore"  # type: ignore[union-attr]
    facility = feature.detail.facility_info  # type: ignore[union-attr]
    assert facility["source_category"] == "아동서점 > 아동서적"
    assert bundle.source_record.raw_address == "경기 안양시 동안구 흥안대로 460 1층"


async def test_split_coord_out_of_bbox_treated_as_missing() -> None:
    row = {
        "FCLTY_NM": "이상좌표 서점",
        "FCLTY_ROAD_NM_ADDR": "경기 안양시 어딘가",
        "FCLTY_LA": "0.4375",  # 실측에 시간분수형 오염값 존재 가능 — bbox 밖
        "FCLTY_LO": "0.75",
    }
    [bundle] = await file_rows_to_bundles(
        [row], slug="children_bookstores_csv", fetched_at=_NOW
    )
    assert bundle.feature.coord is None


# -- 한국어 주소-only 방언 ----------------------------------------------------


async def test_korean_address_golf_course_composes_region_address() -> None:
    row = {
        "지역": "강원",
        "이름": "라데나골프클럽",
        "사업자": "두산큐벡스㈜(문희종)",
        "소재지": "춘천시 신동면 칠전동길 72",
        "면적(제곱미터)": "1533823",
        "홀": "27",
        "구분": "회원제",
    }
    [bundle] = await file_rows_to_bundles(
        [row], slug="golf_courses_status", fetched_at=_NOW
    )
    feature = bundle.feature
    assert feature.name == "라데나골프클럽"
    assert feature.category == PlaceCategoryCode.TOURISM_ACTIVITY_GOLF.value
    assert feature.coord is None
    # 지역 + 소재지 합성 주소 단서.
    assert bundle.source_record.raw_address == "강원 춘천시 신동면 칠전동길 72"
    facility = feature.detail.facility_info  # type: ignore[union-attr]
    assert facility["source_category"] == "회원제"
    assert facility["hole_count"] == "27"
    assert bundle.source_record.source_entity_type == "sports_facility"


# -- 공통 규칙 ----------------------------------------------------------------


async def test_skips_unidentifiable_rows() -> None:
    rows = [
        _world_restaurant_row(TITLE=""),  # 이름 없음 — skip
        _world_restaurant_row(ADDRESS="", COORDINATES=""),  # 위치 단서 없음 — skip
        _world_restaurant_row(),
    ]
    bundles = await file_rows_to_bundles(
        rows, slug="world_restaurants_csv", fetched_at=_NOW
    )
    assert len(bundles) == 1


async def test_unknown_slug_raises() -> None:
    with pytest.raises(KeyError):
        await file_rows_to_bundles(
            [_world_restaurant_row()], slug="nope", fetched_at=_NOW
        )


async def test_excluded_slug_is_not_loadable() -> None:
    """제외 dataset은 메타표에 없어 변환 호출이 실패한다(조용한 적재 방지)."""
    with pytest.raises(KeyError):
        await file_rows_to_bundles(
            [{"TITLE": "기사", "ADDRESS": "어딘가"}],
            slug="tourism_attractions_csv",
            fetched_at=_NOW,
        )


async def test_same_row_is_deterministic_and_id_stable() -> None:
    a = (
        await file_rows_to_bundles(
            [_world_restaurant_row()], slug="world_restaurants_csv", fetched_at=_NOW
        )
    )[0]
    b = (
        await file_rows_to_bundles(
            [_world_restaurant_row()], slug="world_restaurants_csv", fetched_at=_NOW
        )
    )[0]
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key
