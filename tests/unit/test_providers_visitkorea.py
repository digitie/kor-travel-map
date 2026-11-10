"""``test_providers_visitkorea`` — TourAPI 축제(``searchFestival2``) → 1차 event Feature.

2026-11-10 소유자 결정으로 data.go.kr 전국문화축제표준데이터를 쓰지 않는다. TourAPI 축제가
유일한 축제 원천이고 이름으로 다른 축제에 붙는 enrichment가 아니라 Feature를 직접 만든다.

입력 행은 2026-11-10 운영 키로 받은 ``searchFestival2`` 실제 응답의 필드 값이다
(포항국제불빛축제 588175 — ``lclsSystm3`` EV010200, 좌표·법정동 코드 보유).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.category import PlaceCategoryCode
from kortravelmap.core.events import has_required_event_details
from kortravelmap.dto import (
    Address,
    Coordinate,
    EventDetail,
    FeatureBundle,
    FeatureKind,
    FeatureQualityState,
    SourceRole,
)
from kortravelmap.providers import visitkorea as vk

pytestmark = pytest.mark.unit

KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 11, 10, 4, 35, tzinfo=KST)


@dataclass(frozen=True)
class _Item:
    content_id: str | None
    title: str | None
    content_type_id: str | None = "15"
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
    event_start_date: str | None = None
    event_end_date: str | None = None
    overview: str | None = None
    homepage: str | None = None


_POHANG = _Item(
    content_id="588175",
    title="포항국제불빛축제",
    addr1="경상북도 포항시 북구 두호동 685-1",
    addr2="영일대해수욕장 일원",
    tel="054-270-5114",
    first_image="http://tong.visitkorea.or.kr/cms/resource/75/588175_image2_1.jpg",
    first_image2="http://tong.visitkorea.or.kr/cms/resource/75/588175_image3_1.jpg",
    map_x=129.3655,
    map_y=36.0567,
    lcls_systm1="EV",
    lcls_systm2="EV01",
    lcls_systm3="EV010200",
    l_dong_regn_cd="47",
    l_dong_signgu_cd="113",
    modified_time=datetime(2026, 10, 30, 11, 2, 3, tzinfo=KST),
    copyright_division_code="Type3",
    event_start_date="20261119",
    event_end_date="20261121",
)


async def _reverse(coord: Coordinate) -> Address:
    return Address(
        bjd_code="4711310100",
        sigungu_code="47113",
        sido_code="47",
        admin="두호동",
        zipcode="37707",
    )


def _bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(vk.tourapi_festivals_to_bundles(items, fetched_at=_FETCHED, **kwargs))


def _detail(bundle: FeatureBundle) -> EventDetail:
    assert isinstance(bundle.feature.detail, EventDetail)
    return bundle.feature.detail


# -- 정체성 ---------------------------------------------------------------


def test_a_tourapi_festival_becomes_a_primary_event_feature() -> None:
    (bundle,) = _bundles([_POHANG], reverse_geocoder=_reverse)
    feature = bundle.feature
    assert feature.kind is FeatureKind.EVENT
    assert feature.name == "포항국제불빛축제"
    assert feature.category == PlaceCategoryCode.TOURISM_EVENT.value
    assert (feature.marker_icon, feature.marker_color) == ("star", "P-11")
    assert feature.coord == Coordinate(lon=Decimal("129.3655"), lat=Decimal("36.0567"))
    assert feature.address.bjd_code == "4711310100"
    assert feature.quality_state is FeatureQualityState.VALID

    record = bundle.source_record
    assert record.provider == "python-visitkorea-api"
    assert record.dataset_key == vk.DATASET_KEY_VISITKOREA_FESTIVALS == "visitkorea_festivals"
    assert record.source_entity_id == "588175"
    # 1차 source다 — 다른 원천의 축제에 이름으로 붙는 enrichment가 아니다.
    assert bundle.source_link.source_role is SourceRole.PRIMARY
    assert bundle.source_link.feature_id == feature.feature_id


def test_festival_dates_venue_and_tourapi_ids_land_in_the_event_detail() -> None:
    (bundle,) = _bundles([_POHANG], reverse_geocoder=_reverse)
    detail = _detail(bundle)
    # 공개 축제 API(``event_kind IN ('festival', …)``)가 이 행을 그대로 고른다.
    assert detail.event_kind == "festival"
    assert (detail.starts_on, detail.ends_on) == (date(2026, 11, 19), date(2026, 11, 21))
    # 장소는 원천이 준 개최지 주소다(행정구역으로 추정하지 않는다).
    assert detail.venue_name == "경상북도 포항시 북구 두호동 685-1 영일대해수욕장 일원"
    assert detail.tel == "054-270-5114"
    assert (detail.content_id, detail.content_type_id) == ("588175", "15")
    assert detail.payload["lcls_systm3"] == "EV010200"
    assert has_required_event_details(detail)


def test_overview_and_homepage_from_the_detail_call_are_exposed() -> None:
    item = replace(
        _POHANG,
        overview="포항의 밤바다를 수놓는 불빛축제.<br>불꽃쇼&nbsp;공연",
        homepage='<a href="https://phfireworks.ipohang.org" target="_blank">홈페이지</a>',
    )
    (bundle,) = _bundles([item])
    detail = _detail(bundle)
    # 공개 축제 view의 ``festival_content``는 ``payload['content']``를 읽는다.
    assert detail.payload["content"] == "포항의 밤바다를 수놓는 불빛축제.\n불꽃쇼 공연"
    assert str(bundle.feature.urls.homepage) == "https://phfireworks.ipohang.org/"
    # replay가 ``TourItem``으로 되살릴 수 있게 상세 원문을 raw_data에 남긴다.
    assert bundle.source_record.raw_data["overview"] == item.overview
    assert bundle.source_record.raw_data["event_start_date"] == "20261119"


def test_images_are_referenced_with_the_kogl_license() -> None:
    (bundle,) = _bundles([_POHANG])
    roles = [(source.role, source.dataset_key) for source in bundle.file_sources]
    assert roles == [
        ("primary", "visitkorea_festivals"),
        ("thumbnail", "visitkorea_festivals"),
    ]
    assert {source.payload["kogl_type"] for source in bundle.file_sources} == {"Type3"}


# -- 품질 경계 ------------------------------------------------------------


def test_inverted_dates_are_dropped_and_the_row_is_quarantined() -> None:
    (bundle,) = _bundles([replace(_POHANG, event_start_date="20261121", event_end_date="20261119")])
    detail = _detail(bundle)
    assert (detail.starts_on, detail.ends_on) == (None, None)
    assert bundle.feature.quality_state is FeatureQualityState.QUARANTINED


@pytest.mark.parametrize("value", ["", "2026111", "20261340", "abc"])
def test_malformed_dates_are_not_guessed(value: str) -> None:
    (bundle,) = _bundles([replace(_POHANG, event_start_date=value)])
    assert _detail(bundle).starts_on is None
    assert bundle.feature.quality_state is FeatureQualityState.QUARANTINED


def test_a_row_without_an_address_has_no_venue_and_is_quarantined() -> None:
    (bundle,) = _bundles([replace(_POHANG, addr1=None, addr2=None)])
    assert _detail(bundle).venue_name is None
    assert bundle.feature.quality_state is FeatureQualityState.QUARANTINED


def test_rows_without_content_id_or_title_are_skipped() -> None:
    assert _bundles([replace(_POHANG, content_id=" "), replace(_POHANG, title=None)]) == []


def test_a_repeated_content_id_keeps_one_bundle_deterministically() -> None:
    edited = replace(_POHANG, title="제23회 포항국제불빛축제")
    forward = _bundles([_POHANG, edited])
    backward = _bundles([edited, _POHANG])
    assert len(forward) == len(backward) == 1
    assert forward[0].source_record == backward[0].source_record


def test_without_coordinates_the_address_resolver_fills_the_legal_dong() -> None:
    calls: list[Address] = []

    async def _resolve(address: Address) -> Address:
        calls.append(address)
        return Address(bjd_code="4711310100", sigungu_code="47113", sido_code="47")

    async def _never(coord: Coordinate) -> Address:  # pragma: no cover — 좌표가 없다
        raise AssertionError("좌표 없는 행에 역지오코딩을 부르지 않는다")

    (bundle,) = _bundles(
        [replace(_POHANG, map_x=None, map_y=None)],
        reverse_geocoder=_never,
        address_resolver=_resolve,
    )
    assert bundle.feature.coord is None
    assert bundle.feature.address.bjd_code == "4711310100"
    assert calls[0].legal == "경상북도 포항시 북구 두호동 685-1"


def test_without_geo_the_tourapi_legal_dong_codes_give_the_sigungu() -> None:
    (bundle,) = _bundles([_POHANG])
    assert (bundle.feature.address.sigungu_code, bundle.feature.address.sido_code) == (
        "47113",
        "47",
    )


def test_a_naive_fetched_at_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone|aware|naive"):
        asyncio.run(vk.tourapi_festivals_to_bundles([_POHANG], fetched_at=datetime(2026, 11, 10)))


def test_the_feature_id_does_not_move_when_the_detail_arrives() -> None:
    (plain,) = _bundles([_POHANG], reverse_geocoder=_reverse)
    detailed_item = replace(_POHANG, overview="본문", homepage="")
    (detailed,) = _bundles([detailed_item], reverse_geocoder=_reverse)
    assert plain.feature.feature_id == detailed.feature.feature_id


# -- 수집 창 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("today", "start"),
    [
        (date(2026, 11, 10), date(2025, 11, 1)),
        (date(2026, 1, 31), date(2025, 1, 1)),
        (date(2026, 12, 1), date(2025, 12, 1)),
    ],
)
def test_the_window_starts_on_the_first_of_the_month_a_year_back(today: date, start: date) -> None:
    # ``searchFestival2``의 ``eventStartDate``는 그날 이후에 **끝나는** 행사를 준다(2026-11-10
    # 실측: 20251101로 879건, 그 전에 시작해 진행 중인 2건 포함). 공개 축제 API는 앞뒤 한 달을
    # 함께 세므로 한 해 전 그달 1일부터 받는다.
    assert vk.festival_window_start(today) == start
