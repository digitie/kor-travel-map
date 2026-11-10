"""``test_providers_visitkorea_attractions`` — TourAPI 관광지·문화시설·레포츠 → place (#1459).

입력 행은 2026-11-09 운영 키로 받은 ``areaBasedList2``/``detailCommon2`` 실제 응답의 필드
값이다(부산타워 1277679·광안대교 128164·수산항 2788875). KorService2 목록은 옛 ``cat1~3``을
비워 준다 — 분류는 신 분류체계 ``lclsSystm1~3``이다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.category import PLACE_CATEGORY_DEFINITIONS, PlaceCategoryCode
from kortravelmap.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers import visitkorea_attractions as va
from kortravelmap.providers.visitkorea_attractions import (
    DATASET_KEY_VISITKOREA_ATTRACTIONS,
    attraction_category,
    plan_attraction_details,
)

pytestmark = pytest.mark.unit

KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 11, 9, 4, 45, tzinfo=KST)


@dataclass(frozen=True)
class _Item:
    content_id: str | None
    title: str | None
    content_type_id: str | None = "12"
    addr1: str | None = None
    addr2: str | None = None
    zipcode: str | None = None
    tel: str | None = None
    first_image: str | None = None
    first_image2: str | None = None
    map_x: float | None = None
    map_y: float | None = None
    lcls_systm1: str | None = None
    lcls_systm2: str | None = None
    lcls_systm3: str | None = None
    l_dong_regn_cd: str | None = None
    l_dong_signgu_cd: str | None = None
    created_time: datetime | None = None
    modified_time: datetime | None = None
    copyright_division_code: str | None = None
    overview: str | None = None
    homepage: str | None = None


_BUSAN_TOWER = _Item(
    content_id="1277679",
    title="부산타워",
    addr1="부산광역시 중구 용두산길 37-30",
    zipcode="48946",
    first_image="http://tong.visitkorea.or.kr/cms/resource/79/1277679_image2_1.jpg",
    first_image2="http://tong.visitkorea.or.kr/cms/resource/79/1277679_image3_1.jpg",
    map_x=129.0324096,
    map_y=35.1011207,
    lcls_systm1="VE",
    lcls_systm2="VE01",
    lcls_systm3="VE010200",
    l_dong_regn_cd="26",
    l_dong_signgu_cd="110",
    created_time=datetime(2011, 1, 5, 9, 0, tzinfo=KST),
    modified_time=datetime(2026, 3, 2, 10, 0, 1, tzinfo=KST),
    copyright_division_code="Type1",
    overview=(
        "부산타워는 부산 원도심 용두산공원에 있는 120m 높이의 전망대이다.<br>"
        "전망대에서는 부산항과 광안대교를 감상할 수 있다.&nbsp;"
    ),
    homepage='<a href="https://www.visitbusan.net" target="_blank">https://www.visitbusan.net</a>',
)
_GWANGAN = _Item(
    content_id="128164",
    title="광안대교",
    addr1="부산광역시 수영구 민락동",
    map_x=129.1186,
    map_y=35.1478,
    lcls_systm1="VE",
    lcls_systm2="VE01",
    lcls_systm3="VE010300",
    l_dong_regn_cd="26",
    l_dong_signgu_cd="500",
    modified_time=datetime(2025, 8, 1, 9, 0, tzinfo=KST),
    copyright_division_code="Type3",
)


async def _reverse(coord: Coordinate) -> Address:
    sigungu = "26110" if coord.lon < Decimal("129.1") else "26500"
    return Address(
        bjd_code=f"{sigungu}10100",
        sigungu_code=sigungu,
        sido_code="26",
        admin="가상동",
        zipcode="48900",
    )


def _bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(va.tourapi_attractions_to_bundles(items, fetched_at=_FETCHED, **kwargs))


# -- 분류 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lcls", "expected"),
    [
        # 3단계 표 — #1459 누락 목록의 실제 분류
        (("VE", "VE01", "VE010200"), PlaceCategoryCode.TOURISM_NATURE_OBSERVATORY),  # 부산타워
        (("NA", "NA01", "NA010100"), PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY),
        (("NA", "NA02", "NA020500"), PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND),
        (("NA", "NA02", "NA020900"), PlaceCategoryCode.TOURISM_NATURE_BEACH),
        (("NA", "NA04", "NA040600"), PlaceCategoryCode.LODGING_RECREATION_FOREST),
        (("HS", "HS03", "HS030100"), PlaceCategoryCode.TOURISM_HERITAGE_TEMPLE),
        (("EX", "EX05", "EX050100"), PlaceCategoryCode.HOT_SPRING_SPA_HOT_SPRING),  # 동래온천
        # 문화시설(14) 코드 — 같은 변환기로 14 dataset을 더할 때를 위해 둔다
        (("VE", "VE09", "VE090300"), PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_LIBRARY),
        # 강·호수 계열은 NA02 기본값(해안·섬)이 아니다
        (("NA", "NA02", "NA020200"), PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_RIVER_LAKE),
        # 3단계가 표에 없으면 2단계
        (("VE", "VE01", "VE010300"), PlaceCategoryCode.TOURISM),  # 다리/대교
        (("HS", "HS01", "HS010700"), PlaceCategoryCode.TOURISM_HERITAGE_HISTORIC_SITE),
        # 2단계도 없으면 1단계, 그것도 없으면 관광
        (("EX", "EX99", "EX990000"), PlaceCategoryCode.TOURISM_ACTIVITY),
        ((None, None, None), PlaceCategoryCode.TOURISM),
        (("ZZ", None, None), PlaceCategoryCode.TOURISM),
        # 상위 코드가 비어 와도 3단계 접두사로 내려간다
        ((None, None, "HS020100"), PlaceCategoryCode.TOURISM_HERITAGE_HISTORIC_SITE),
    ],
)
def test_attraction_category_maps_the_new_classification(
    lcls: tuple[str | None, str | None, str | None], expected: PlaceCategoryCode
) -> None:
    assert attraction_category(*lcls) == expected.value


@pytest.mark.parametrize(
    ("content_type", "lcls3", "title", "expected"),
    [
        # #1459 수용 예시 — 산막이옛길(28)·태권도원·국립세종도서관(14)
        ("28", "LS011900", "산막이옛길", PlaceCategoryCode.TOURISM_ACTIVITY_TREKKING),
        ("14", "VE090400", "태권도원", PlaceCategoryCode.TOURISM_CULTURAL_FACILITY),
        (
            "14",
            "VE090300",
            "국립세종도서관",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_LIBRARY,
        ),
        # 문화시설(14) 대표 코드
        ("14", "VE070100", "국립중앙박물관", PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM),
        ("14", "VE070600", "리움미술관", PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART),
        (
            "14",
            "VE060100",
            "세종문화회관",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL,
        ),
        ("14", "VE120300", "어느 문화공간", PlaceCategoryCode.TOURISM_CULTURAL_FACILITY),
        # 레포츠(28) 대표 코드
        ("28", "LS010400", "어느 컨트리클럽", PlaceCategoryCode.TOURISM_ACTIVITY_GOLF),
        ("28", "LS010800", "어느 스키장", PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS),
        ("28", "LS011900", "어느 서바이벌장", PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS),
        ("28", "LS020600", "어느 바다낚시터", PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS),
        ("28", "AC050100", "어느 야영장", PlaceCategoryCode.LODGING_CAMPGROUND),
        ("28", "AC050200", "어느 오토캠핑장", PlaceCategoryCode.LODGING_CAMPGROUND_AUTO),
        ("28", "AC050300", "어느 카라반", PlaceCategoryCode.LODGING_CAMPGROUND_CARAVAN_RENTAL),
        ("28", "AC050400", "어느 글램핑장", PlaceCategoryCode.LODGING_CAMPGROUND_GLAMPING),
        ("28", "AC030100", "어느 펜션", PlaceCategoryCode.LODGING_PENSION),
    ],
)
def test_culture_and_leisure_rows_get_their_own_categories(
    content_type: str, lcls3: str, title: str, expected: PlaceCategoryCode
) -> None:
    item = replace(
        _GWANGAN,
        content_id="77",
        content_type_id=content_type,
        title=title,
        lcls_systm1=lcls3[:2],
        lcls_systm2=lcls3[:4],
        lcls_systm3=lcls3,
    )
    (bundle,) = _bundles([item])
    assert bundle.feature.category == expected.value
    assert bundle.feature.detail.place_kind == {  # type: ignore[union-attr]
        "12": "tourapi_attraction",
        "14": "tourapi_culture_facility",
        "28": "tourapi_leisure",
    }[content_type]


@pytest.mark.parametrize(
    ("title", "trail"),
    [
        ("산막이옛길", True),
        ("산막이옛길(괴산)", True),
        ("제주올레 7코스", True),
        ("강화나들길 ①코스", True),
        ("어느 트레킹코스", True),
        ("어느 산책코스", True),
        ("제주올레 14-1코스", True),
        ("어느둘레길 제1코스", True),
        ("어느산책로 입구", True),
        ("어느둘레길(1구간) 입구", True),
        ("한강 자전거길", False),
        ("어느 서바이벌장", False),
        ("어느 짚라인", False),
    ],
)
def test_other_land_leisure_is_trekking_only_when_the_name_is_a_trail(
    title: str, trail: bool
) -> None:
    expected = (
        PlaceCategoryCode.TOURISM_ACTIVITY_TREKKING
        if trail
        else PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS
    )
    assert attraction_category("LS", "LS01", "LS011900", title) == expected.value
    # 다른 코드는 이름이 길이어도 그 코드의 분류다.
    assert attraction_category("LS", "LS01", "LS010200", title) == (
        PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS.value
    )


def test_the_fetcher_and_converter_share_one_content_type_list() -> None:
    assert va.TOURAPI_PLACE_CONTENT_TYPE_IDS == ("12", "14", "28")
    assert set(va._PLACE_KIND_BY_CONTENT_TYPE) == set(va.TOURAPI_PLACE_CONTENT_TYPE_IDS)


def test_every_mapped_category_exists_in_the_catalog() -> None:
    known = {definition.code for definition in PLACE_CATEGORY_DEFINITIONS}
    targets = {
        *va.TOURAPI_LCLS3_CATEGORY.values(),
        *va.TOURAPI_LCLS2_CATEGORY.values(),
        *va.TOURAPI_LCLS1_CATEGORY.values(),
    }
    assert {code.value for code in targets} <= known


# -- 변환 ------------------------------------------------------------------


def test_busan_tower_becomes_an_observatory_place() -> None:
    (bundle,) = _bundles([_BUSAN_TOWER], reverse_geocoder=_reverse)
    feature = bundle.feature
    assert feature.kind is FeatureKind.PLACE
    assert feature.name == "부산타워"
    assert feature.category == PlaceCategoryCode.TOURISM_NATURE_OBSERVATORY.value
    assert feature.provider_natural_key == "1277679"
    assert feature.coord == Coordinate(lon=Decimal("129.0324096"), lat=Decimal("35.1011207"))
    assert feature.address.road == "부산광역시 중구 용두산길 37-30"
    assert feature.address.bjd_code == "2611010100"
    assert feature.address.sigungu_code == "26110"

    record = bundle.source_record
    assert record.provider == "python-visitkorea-api"
    assert record.dataset_key == DATASET_KEY_VISITKOREA_ATTRACTIONS
    assert record.source_entity_type == "tourist_attraction"
    assert record.source_entity_id == "1277679"
    assert record.raw_data["modified_time"] == "2026-03-02T10:00:01+09:00"
    assert bundle.source_link.source_role is SourceRole.PRIMARY

    info = feature.detail.facility_info  # type: ignore[union-attr]
    assert info["homepage_url"] == "https://www.visitbusan.net"
    assert info["overview"] == (
        "부산타워는 부산 원도심 용두산공원에 있는 120m 높이의 전망대이다.\n"
        "전망대에서는 부산항과 광안대교를 감상할 수 있다."
    )
    assert info["attribution"] == "한국관광공사"
    assert info["license"] == "공공누리 제1유형(출처표시)"
    assert info["image_url"] == _BUSAN_TOWER.first_image
    assert info["tourapi_content_id"] == "1277679"

    roles = [(source.role, source.source_url) for source in bundle.file_sources]
    assert roles == [
        ("primary", _BUSAN_TOWER.first_image),
        ("thumbnail", _BUSAN_TOWER.first_image2),
    ]
    # 파일이 객체 저장소로 옮겨져도 이용 조건이 함께 간다.
    assert {source.payload["kogl_type"] for source in bundle.file_sources} == {"Type1"}
    assert {source.payload["attribution"] for source in bundle.file_sources} == {"한국관광공사"}


def test_transport_facility_rows_are_left_to_the_transport_source() -> None:
    # 공항·기차역·여객선·휴게소는 kor-travel-transport가 정본이다 — 중복 place를 만들지 않는다.
    airport = replace(_GWANGAN, content_id="9", lcls_systm2="VE11", lcls_systm3="VE110100")
    assert _bundles([airport, replace(airport, lcls_systm2=None)]) == []


@pytest.mark.parametrize(
    ("addr1", "road"),
    [
        ("부산광역시 중구 용두산길 37-30", True),
        ("서울특별시 종로구 세종대로 172", True),
        ("서울특별시 종로구 종로1가 1", False),  # 법정동 '종로1가'의 지번
        ("부산광역시 수영구 민락동", False),
    ],
)
def test_addr1_is_split_into_road_or_jibun(addr1: str, road: bool) -> None:
    (bundle,) = _bundles([replace(_GWANGAN, addr1=addr1)])
    assert (bundle.feature.address.road == addr1) is road
    assert (bundle.feature.address.legal == addr1) is not road


def test_jibun_only_address_goes_to_legal() -> None:
    (bundle,) = _bundles([_GWANGAN], reverse_geocoder=_reverse)
    assert bundle.feature.address.legal == "부산광역시 수영구 민락동"
    assert bundle.feature.address.road is None
    info = bundle.feature.detail.facility_info  # type: ignore[union-attr]
    assert info["license"] == "공공누리 제3유형(출처표시·변경금지)"
    assert "overview" not in info  # 상세를 아직 받지 않았다
    assert bundle.file_sources == []


def test_sigungu_falls_back_to_the_tourapi_legal_dong_codes_without_geo() -> None:
    (bundle,) = _bundles([_GWANGAN])
    assert bundle.feature.address.bjd_code is None
    assert bundle.feature.address.sigungu_code == "26500"
    assert bundle.feature.address.sido_code == "26"


def test_the_feature_id_is_stable_across_detail_and_payload_changes() -> None:
    (plain,) = _bundles([_GWANGAN], reverse_geocoder=_reverse)
    (detailed,) = _bundles(
        [replace(_GWANGAN, overview="해상 복층 교량이다.", homepage="")],
        reverse_geocoder=_reverse,
    )
    assert plain.feature.feature_id == detailed.feature.feature_id
    assert plain.source_record.raw_payload_hash != detailed.source_record.raw_payload_hash


def test_rows_without_content_id_or_title_are_skipped() -> None:
    assert _bundles([replace(_GWANGAN, content_id=" "), replace(_GWANGAN, title=None)]) == []


def test_a_repeated_content_id_keeps_one_bundle() -> None:
    # 순회 중 신규 등록으로 목록이 밀리면 페이지 경계 행이 두 번 온다.
    edited = replace(_GWANGAN, tel="051-000-0000")
    bundles = _bundles([_GWANGAN, _BUSAN_TOWER, edited])
    assert [b.source_record.source_entity_id for b in bundles] == ["128164", "1277679"]
    reversed_bundles = _bundles([edited, _BUSAN_TOWER, _GWANGAN])
    assert {b.source_record.raw_payload_hash for b in bundles} == {
        b.source_record.raw_payload_hash for b in reversed_bundles
    }


def test_zero_or_out_of_range_coordinates_are_dropped() -> None:
    (bundle,) = _bundles([replace(_GWANGAN, map_x=0.0, map_y=0.0)])
    assert bundle.feature.coord is None


# -- 상세 예산 -------------------------------------------------------------


def _stored(item: _Item, *, overview: str | None, homepage: str | None = "") -> dict[str, Any]:
    (bundle,) = _bundles([replace(item, overview=overview, homepage=homepage)])
    return dict(bundle.source_record.raw_data)


def test_plan_reuses_stored_detail_when_the_list_row_is_unchanged() -> None:
    stored = {"128164": _stored(_GWANGAN, overview="저장된 설명", homepage="<a href='x'>")}
    plan = plan_attraction_details([_GWANGAN], stored, budget=10)
    assert plan.reuse == {"128164": ("저장된 설명", "<a href='x'>")}
    assert plan.fetch == ()
    assert plan.deferred == 0


def test_plan_treats_an_empty_received_detail_as_received() -> None:
    stored = {"128164": _stored(_GWANGAN, overview="", homepage=None)}
    plan = plan_attraction_details([_GWANGAN], stored, budget=10)
    assert plan.reuse == {"128164": ("", "")}
    assert plan.fetch == ()


def test_plan_fetches_modified_rows_before_never_fetched_rows_within_budget() -> None:
    newer = replace(_GWANGAN, modified_time=datetime(2026, 11, 1, 9, 0, tzinfo=KST))
    never = [replace(_BUSAN_TOWER, content_id=str(9000 + n)) for n in range(3)]
    stored = {
        "128164": _stored(_GWANGAN, overview="낡은 설명"),
        "9001": _stored(never[1], overview=None),  # 목록에 있었지만 상세는 받지 못했다
    }
    plan = plan_attraction_details([*never, newer], stored, budget=2)
    assert plan.fetch == ("128164", "9000")
    assert plan.deferred == 2
    assert plan.reuse == {}  # 낡은 상세는 예산 밖이어도 이어 쓰지 않는다


def test_plan_ignores_rows_that_are_not_loaded() -> None:
    airport = replace(_GWANGAN, content_id="9", lcls_systm2="VE11", lcls_systm3="VE110100")
    plan = plan_attraction_details([airport, _BUSAN_TOWER], {}, budget=10)
    assert plan.fetch == ("1277679",)


def test_plan_with_zero_budget_fetches_nothing() -> None:
    plan = plan_attraction_details([_GWANGAN, _BUSAN_TOWER], {}, budget=0)
    assert plan.fetch == ()
    assert plan.deferred == 2
