"""``test_providers_standard_traditional_markets`` — 전국전통시장표준데이터 (#1459).

입력 행은 공공데이터포털 15012894 상세 페이지 그리드 미리보기의 실제 행이다
(데이터기준일자 2025-11-10). "전북특별차치도"는 원천 오타를 그대로 둔 것이다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.category import PlaceCategoryCode
from kortravelmap.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers.standard_data import (
    DATASET_KEY_TRADITIONAL_MARKETS,
    TRADITIONAL_MARKET_CATEGORY,
    TRADITIONAL_MARKET_MARKER_COLOR,
    traditional_market_natural_key,
)
from kortravelmap.providers.standard_data import (
    traditional_markets_to_bundles as _markets_async,
)

KST = timezone(timedelta(hours=9))


def traditional_markets_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_markets_async(items, **kwargs))


@dataclass(frozen=True)
class _Market:
    mrkt_nm: str | None
    mrkt_type: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    mrkt_estbl_cycle: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    stor_number: int | None = None
    trtmnt_prdlst: str | None = None
    use_gcct: str | None = None
    homepage_url: str | None = None
    pblic_toilet_yn: str | None = None
    prkplce_yn: str | None = None
    estbl_year: int | None = None
    phone_number: str | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    raw: Any = field(default_factory=dict)


_MANGWON = _Market(
    mrkt_nm="망원시장",
    mrkt_type="상설장",
    rdnmadr="서울특별시 마포구 망원로8길 7",
    lnmadr="서울특별시 마포구 망원동 486-37",
    mrkt_estbl_cycle="매일",
    latitude=37.55715742,
    longitude=126.9059507,
    stor_number=82,
    trtmnt_prdlst="농산물+축산물+가공식품+가정용품+음식점",
    pblic_toilet_yn="Y",
    prkplce_yn="Y",
    estbl_year=2006,
    phone_number="02-335-3591",
    reference_date=date(2025, 11, 10),
)
_GANGHWA = _Market(
    mrkt_nm="강화풍물시장",
    mrkt_type="상설장",
    rdnmadr="인천광역시 강화군 강화읍 중앙로 17-9",
    lnmadr="인천광역시 강화군 강화읍 갑곳리 849",
    mrkt_estbl_cycle="2일+7일",
    latitude=37.74141775,
    longitude=126.4928651,
    stor_number=178,
    reference_date=date(2025, 11, 10),
)
_HAMYEOL_NO_COORD = _Market(
    mrkt_nm="함열시장",
    rdnmadr="전북특별차치도 익산시 함열읍 2길 8",
    lnmadr="전북특별차치도 익산시 와리 565-26",
    reference_date=date(2025, 11, 10),
)
_YEONGDONG_NO_ROAD = _Market(
    mrkt_nm="영동전통시장",
    lnmadr="충청북도 영동군 영동읍 계산리 694-13",
    latitude=36.17521123,
    longitude=127.7801451,
    phone_number="043-742-0808",
)


def _now() -> datetime:
    return datetime(2026, 11, 9, 9, 0, tzinfo=KST)


@pytest.mark.unit
def test_market_feature_fields() -> None:
    bundle = traditional_markets_to_bundles([_MANGWON], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "망원시장"
    assert feature.category == TRADITIONAL_MARKET_CATEGORY
    assert feature.category == PlaceCategoryCode.CONVENIENCE_TRADITIONAL_MARKET.value
    assert feature.marker_icon == "shop"
    assert feature.marker_color == TRADITIONAL_MARKET_MARKER_COLOR
    assert feature.coord == Coordinate(lon=Decimal("126.9059507"), lat=Decimal("37.55715742"))
    assert feature.address.road == "서울특별시 마포구 망원로8길 7"
    assert feature.address.legal == "서울특별시 마포구 망원동 486-37"
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "traditional_market"  # type: ignore[union-attr]
    assert detail.phones == ["02-335-3591"]  # type: ignore[union-attr]
    info = detail.facility_info  # type: ignore[union-attr]
    assert info["mrkt_type"] == "상설장"
    assert info["mrkt_estbl_cycle"] == "매일"
    assert info["stor_number"] == 82
    assert info["pblic_toilet_yn"] == "Y"
    assert info["prkplce_yn"] == "Y"
    assert info["estbl_year"] == 2006
    assert "coord_source" not in info  # 원천 좌표를 썼다


@pytest.mark.unit
def test_market_source_record_and_stable_natural_key() -> None:
    bundle = traditional_markets_to_bundles([_MANGWON], fetched_at=_now())[0]
    source = bundle.source_record
    assert source.provider == "data.go.kr-standard"
    assert source.dataset_key == DATASET_KEY_TRADITIONAL_MARKETS == "datagokr_traditional_markets"
    assert source.source_entity_type == "traditional_market"
    assert source.source_entity_id == "망원시장::서울특별시마포구"
    assert source.raw_data["reference_date"] == "2025-11-10"
    assert source.raw_data["mrkt_nm"] == "망원시장"
    assert bundle.source_link.source_role == SourceRole.PRIMARY

    # 연간 갱신의 흔한 주소 편집(띄어쓰기·번지·괄호 동명·도로명 채움)은 같은 entity·feature다.
    for edited in (
        replace(_MANGWON, rdnmadr="서울특별시  마포구 망원로8길7"),
        replace(_MANGWON, rdnmadr="서울특별시 마포구 망원로8길 9 (망원동)"),
        replace(_MANGWON, rdnmadr=None),
    ):
        again = traditional_markets_to_bundles([edited], fetched_at=_now())[0]
        assert again.source_record.source_entity_id == source.source_entity_id
        assert again.feature.feature_id == bundle.feature.feature_id


@pytest.mark.unit
def test_market_natural_key_falls_back_to_jibun_and_distinguishes_same_name() -> None:
    assert (
        traditional_market_natural_key("영동전통시장", None, "충청북도 영동군 영동읍 계산리 694-13")
        == "영동전통시장::충청북도영동군"
    )
    # 주소가 없으면 좌표가 지역을 대신한다(주소 없는 "중앙시장"끼리 전국에서 겹치지 않게).
    assert (
        traditional_market_natural_key(
            "중앙시장", None, None, coord=Coordinate(lon=Decimal("128.9"), lat=Decimal("37.75"))
        )
        == "중앙시장::37.7500,128.9000"
    )
    a = _Market(mrkt_nm="중앙시장", rdnmadr="강원특별자치도 강릉시 금성로 21", latitude=37.75,
                longitude=128.9)
    b = _Market(mrkt_nm="중앙시장", rdnmadr="강원특별자치도 속초시 중앙로147번길 16",
                latitude=38.2, longitude=128.59)
    bundles = traditional_markets_to_bundles([a, b], fetched_at=_now())
    assert len({x.source_record.source_entity_id for x in bundles}) == 2
    assert len({x.feature.feature_id for x in bundles}) == 2


@pytest.mark.unit
def test_market_reverse_geocoder_fills_codes() -> None:
    calls: list[Coordinate] = []

    async def _rg(coord: Coordinate) -> Address | None:
        calls.append(coord)
        return Address(bjd_code="1144012400", sigungu_code="11440", sido_code="11")

    bundle = traditional_markets_to_bundles([_MANGWON], fetched_at=_now(), reverse_geocoder=_rg)[0]
    assert calls == [Coordinate(lon=Decimal("126.9059507"), lat=Decimal("37.55715742"))]
    assert bundle.feature.address.bjd_code == "1144012400"
    assert bundle.feature.address.sigungu_code == "11440"
    assert bundle.feature.feature_id.startswith("f_1144012400_p_")


@pytest.mark.unit
def test_market_without_coord_is_geocoded_and_reverse_geocoded() -> None:
    asked: list[Address] = []

    # 도로명→지번 순서는 공용 정지오코더(``geocode_address``)의 일이다 — 변환은 주소 둘을 함께 준다.
    async def _geocode(address: Address) -> Coordinate | None:
        asked.append(address)
        return Coordinate(lon=Decimal("126.9629"), lat=Decimal("36.0703"))

    reversed_: list[Coordinate] = []

    async def _rg(coord: Coordinate) -> Address | None:
        reversed_.append(coord)
        return Address(bjd_code="5214034021", sigungu_code="52140", sido_code="52")

    bundle = traditional_markets_to_bundles(
        [_HAMYEOL_NO_COORD],
        fetched_at=_now(),
        reverse_geocoder=_rg,
        address_geocoder=_geocode,
    )[0]
    assert [(a.road, a.legal) for a in asked] == [
        ("전북특별차치도 익산시 함열읍 2길 8", "전북특별차치도 익산시 와리 565-26"),
    ]
    geocoded = Coordinate(lon=Decimal("126.9629"), lat=Decimal("36.0703"))
    assert bundle.feature.coord == geocoded
    assert reversed_ == [geocoded]
    assert bundle.feature.address.bjd_code == "5214034021"
    assert bundle.feature.detail.facility_info["coord_source"] == "geocode"  # type: ignore[union-attr]
    # 정지오코딩 좌표는 원천 raw에 섞지 않는다(replay가 원천 그대로 다시 변환한다).
    assert bundle.source_record.raw_data["latitude"] is None


@pytest.mark.unit
def test_market_with_coord_never_calls_address_geocoder() -> None:
    async def _geocode(address: Address) -> Coordinate | None:
        raise AssertionError("좌표가 있는 행은 정지오코딩하지 않는다")

    bundles = traditional_markets_to_bundles(
        [_MANGWON, _GANGHWA, _YEONGDONG_NO_ROAD], fetched_at=_now(), address_geocoder=_geocode
    )
    assert [b.feature.name for b in bundles] == ["망원시장", "강화풍물시장", "영동전통시장"]
    assert bundles[1].feature.detail.facility_info["mrkt_estbl_cycle"] == "2일+7일"  # type: ignore[union-attr]
    assert bundles[2].feature.address.road is None
    assert bundles[2].feature.address.legal == "충청북도 영동군 영동읍 계산리 694-13"


@pytest.mark.unit
def test_market_without_coord_and_without_geocoder_keeps_row_without_coord() -> None:
    bundle = traditional_markets_to_bundles([_HAMYEOL_NO_COORD], fetched_at=_now())[0]
    assert bundle.feature.coord is None
    assert bundle.feature.name == "함열시장"


@pytest.mark.unit
def test_market_skips_nameless_and_locationless_rows() -> None:
    nameless = _Market(mrkt_nm="  ", rdnmadr="서울특별시 어딘가")
    locationless = _Market(mrkt_nm="위치없는시장")
    bundles = traditional_markets_to_bundles(
        [nameless, locationless, _MANGWON], fetched_at=_now()
    )
    assert [b.feature.name for b in bundles] == ["망원시장"]


@pytest.mark.unit
def test_same_name_in_same_sigungu_gets_full_address_keys() -> None:
    east = _Market(mrkt_nm="동부시장", rdnmadr="전라남도 해남군 해남읍 고산로 1", latitude=34.57,
                   longitude=126.6)
    west = _Market(mrkt_nm="동부시장", rdnmadr="전라남도 해남군 화원면 금평길 2", latitude=34.7,
                   longitude=126.3)
    alone = _Market(mrkt_nm="서부시장", rdnmadr="전라남도 해남군 해남읍 중앙1로 3", latitude=34.57,
                    longitude=126.59)
    bundles = traditional_markets_to_bundles([east, west, alone], fetched_at=_now())
    ids = [b.source_record.source_entity_id for b in bundles]
    assert ids == [
        "동부시장::전라남도해남군::전라남도해남군해남읍고산로1",
        "동부시장::전라남도해남군::전라남도해남군화원면금평길2",
        "서부시장::전라남도해남군",
    ]


@pytest.mark.unit
def test_duplicate_rows_keep_one_regardless_of_page_order() -> None:
    other = replace(_MANGWON, phone_number="02-000-0000")
    forward = traditional_markets_to_bundles([_MANGWON, other], fetched_at=_now())
    backward = traditional_markets_to_bundles([other, _MANGWON], fetched_at=_now())
    assert len(forward) == len(backward) == 1
    assert forward[0].source_record.raw_payload_hash == backward[0].source_record.raw_payload_hash

