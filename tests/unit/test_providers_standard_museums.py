"""``test_providers_standard_museums`` — datagokr 박물관/미술관 표준데이터 (T-RV-54a).

범위: ``museums_to_bundles`` happy path, fclty_type → category 분기(박물관 01040100/
미술관 01040200/미상 01040000), 파생 자연키(instt_code 없음), place place_kind,
결정성, SourceLink PRIMARY, ReverseGeocoder bjd 보강.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers.standard_data import (
    DATASET_KEY_MUSEUMS,
    MUSEUM_CATEGORY,
    MUSEUM_MARKER_COLOR,
)
from kortravelmap.providers.standard_data import (
    museums_to_bundles as _museums_async,
)

KST = timezone(timedelta(hours=9))


def museums_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_museums_async(items, **kwargs))


@dataclass(frozen=True)
class _Museum:
    """``PublicMuseumArtItem`` Protocol 만족 fixture."""

    fclty_nm: str | None
    fclty_type: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    oper_phone_number: str | None
    homepage_url: str | None
    instt_code: str | None
    fclty_info: str | None = None
    weekday_oper_open_hhmm: str | None = None
    weekday_oper_colse_hhmm: str | None = None
    holiday_oper_open_hhmm: str | None = None
    holiday_close_open_hhmm: str | None = None
    rstde_info: str | None = None
    adult_chrge: int | None = None
    yngbgs_chrge: int | None = None
    child_chrge: int | None = None
    etc_chrge_info: str | None = None
    fclty_intrcn: str | None = None
    trnsport_info: str | None = None
    reference_date: date | None = None
    raw: Any = field(default_factory=dict)


_MUSEUM = _Museum(
    fclty_nm="국립중앙박물관",
    fclty_type="박물관",
    rdnmadr="서울특별시 용산구 서빙고로 137",
    lnmadr="서울특별시 용산구 용산동6가 168-6",
    latitude=37.5240,
    longitude=126.9803,
    oper_phone_number="02-2077-9000",
    homepage_url="https://www.museum.go.kr",
    instt_code="MUS-0001",
)

_ART = _Museum(
    fclty_nm="국립현대미술관 서울",
    fclty_type="미술관",
    rdnmadr="서울특별시 종로구 삼청로 30",
    lnmadr=None,
    latitude=37.5790,
    longitude=126.9800,
    oper_phone_number="02-3701-9500",
    homepage_url="https://www.mmca.go.kr",
    instt_code=None,  # 파생키 name::road
)


def _now() -> datetime:
    return datetime(2026, 6, 7, 12, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_museum_bundle_fields_and_category() -> None:
    bundle = museums_to_bundles([_MUSEUM], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "국립중앙박물관"
    assert feature.category == "01040100"  # 박물관
    assert feature.marker_color == MUSEUM_MARKER_COLOR
    assert feature.marker_icon
    assert feature.coord is not None
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "museum"  # type: ignore[union-attr]
    assert detail.phones == ["02-2077-9000"]  # type: ignore[union-attr]
    assert feature.feature_id.startswith("f_global_p_")


@pytest.mark.unit
def test_art_gallery_category_and_derived_key() -> None:
    bundle = museums_to_bundles([_ART], fetched_at=_now())[0]
    assert bundle.feature.category == "01040200"  # 미술관
    # instt_code 없음 → name::road 파생.
    expected_key = "국립현대미술관 서울::서울특별시 종로구 삼청로 30"
    assert bundle.source_record.source_entity_id == expected_key
    assert bundle.source_record.dataset_key == DATASET_KEY_MUSEUMS


@pytest.mark.unit
def test_unknown_type_falls_back_to_parent_category() -> None:
    item = _Museum(
        fclty_nm="어린이체험관",
        fclty_type=None,
        rdnmadr="대전광역시 유성구 대덕대로 480",
        lnmadr=None,
        latitude=None,
        longitude=None,
        oper_phone_number=None,
        homepage_url=None,
        instt_code="MUS-9",
    )
    bundle = museums_to_bundles([item], fetched_at=_now())[0]
    assert bundle.feature.category == MUSEUM_CATEGORY  # 01040000 parent
    assert bundle.feature.coord is None


@pytest.mark.unit
def test_source_record_provider_and_link_primary() -> None:
    bundle = museums_to_bundles([_MUSEUM], fetched_at=_now())[0]
    assert bundle.source_record.provider == "data.go.kr-standard"
    assert bundle.source_record.source_entity_type == "museum_art_gallery"
    # instt_code는 제공 기관(지자체) 코드라 시설마다 다르지 않다 — 공개 파일 1,070행에 215개.
    # 있어도 identity로 쓰지 않는다(2026-11-11 적대 리뷰 HIGH).
    assert bundle.source_record.source_entity_id == f"{_MUSEUM.fclty_nm}::{_MUSEUM.rdnmadr}"
    link = bundle.source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.confidence == 100


@pytest.mark.unit
def test_determinism_and_fk_consistency() -> None:
    a = museums_to_bundles([_MUSEUM], fetched_at=_now())[0]
    b = museums_to_bundles([_MUSEUM], fetched_at=_now())[0]
    assert a.feature.feature_id == a.source_link.feature_id
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key


@pytest.mark.unit
def test_naive_fetched_at_rejected() -> None:
    with pytest.raises(ValueError, match="aware"):
        museums_to_bundles([_MUSEUM], fetched_at=datetime(2026, 6, 7, 12, 0, 0))


@pytest.mark.unit
def test_reverse_geocoder_fills_bjd_code() -> None:
    async def _rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="1117010200", sigungu_code="11170", sido_code="11")

    bundle = museums_to_bundles([_MUSEUM], fetched_at=_now(), reverse_geocoder=_rg)[0]
    assert bundle.feature.address.bjd_code == "1117010200"
    assert bundle.feature.feature_id.startswith("f_1117010200_p_")


@pytest.mark.unit
def test_museum_visitor_info_keeps_hours_fees_and_intro() -> None:
    """관람시간·휴관·요금·소개·교통을 버리지 않는다(ADR-126)."""
    item = replace(
        _MUSEUM,
        weekday_oper_open_hhmm="10:00",
        weekday_oper_colse_hhmm="1800",
        holiday_oper_open_hhmm="10:00",
        holiday_close_open_hhmm="25:00",  # 형식 밖 → 공휴일 줄은 만들지 않는다
        rstde_info="1월 1일, 설날·추석 당일",
        adult_chrge=2000,
        yngbgs_chrge=1000,
        child_chrge=0,
        etc_chrge_info="특별전 별도",
        fclty_intrcn="<p>한국 최대의 박물관</p>",
        trnsport_info="4호선 이촌역",
        fclty_info="-",  # 자리표시는 버린다
        reference_date=date(2026, 3, 1),
    )
    bundle = museums_to_bundles([item], fetched_at=_now())[0]
    info = bundle.feature.detail.facility_info["visitor_info"]  # type: ignore[union-attr]
    assert info == {
        "source": "datagokr_museum",
        "attribution": "공공데이터포털 전국박물관미술관정보표준데이터",
        "reference_date": "2026-03-01",
        "description": "한국 최대의 박물관",
        "usage_hours": "평일 10:00~18:00",
        "rest_days": "1월 1일, 설날·추석 당일",
        "fee_text": "특별전 별도",
        "fees": [
            {"audience": "adult", "amount_krw": 2000},
            {"audience": "youth", "amount_krw": 1000},
            {"audience": "child", "amount_krw": 0},
        ],
        "transport": "4호선 이촌역",
    }
    raw = bundle.source_record.raw_data
    assert raw["reference_date"] == "2026-03-01"
    assert raw["fclty_intrcn"] == "<p>한국 최대의 박물관</p>"


@pytest.mark.unit
def test_museum_without_visitor_fields_has_no_visitor_info_and_old_raw_shape() -> None:
    bundle = museums_to_bundles([_MUSEUM], fetched_at=_now())[0]
    assert "visitor_info" not in bundle.feature.detail.facility_info  # type: ignore[union-attr]
    # 값 없는 새 키는 raw에 없다 — 이 기능 전에 저장된 원본을 replay해도 같은 hash다.
    assert set(bundle.source_record.raw_data) == {
        "fclty_nm",
        "fclty_type",
        "rdnmadr",
        "lnmadr",
        "latitude",
        "longitude",
        "oper_phone_number",
        "homepage_url",
        "instt_code",
    }


def _visitor_info(item: _Museum) -> Any:
    detail = museums_to_bundles([item], fetched_at=_now())[0].feature.detail
    return detail.facility_info["visitor_info"]  # type: ignore[union-attr]


@pytest.mark.unit
def test_museum_zero_fees_with_fee_text_are_not_shown_as_free() -> None:
    item = replace(
        _MUSEUM, adult_chrge=0, yngbgs_chrge=0, child_chrge=0, etc_chrge_info="성인 3,000원"
    )
    info = _visitor_info(item)
    assert "fees" not in info
    assert info["fee_text"] == "성인 3,000원"


@pytest.mark.unit
def test_museum_placeholder_hours_are_dropped() -> None:
    item = replace(
        _MUSEUM,
        weekday_oper_open_hhmm="00:00",
        weekday_oper_colse_hhmm="00:00",
        holiday_oper_open_hhmm="09:00",
        holiday_close_open_hhmm="24:00",
    )
    info = _visitor_info(item)
    assert info["usage_hours"] == "공휴일 09:00~24:00"
