"""``test_providers_standard_special_streets`` — 지역특화거리 표준데이터."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers.standard_data import (
    DATASET_KEY_SPECIAL_STREETS,
    SPECIAL_STREET_CATEGORY,
    SPECIAL_STREET_MARKER_COLOR,
)
from kortravelmap.providers.standard_data import (
    special_streets_to_bundles as _special_async,
)

KST = timezone(timedelta(hours=9))


def special_streets_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_special_async(items, **kwargs))


@dataclass(frozen=True)
class _SpecialStreet:
    stret_nm: str | None
    stret_intrcn: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    stret_lt: float | None
    stor_number: int | None
    appn_year: int | None
    phone_number: str | None
    institution_nm: str | None
    reference_date: date | None
    instt_code: str | None
    instt_nm: str | None
    raw: Any = field(default_factory=dict)


_S1 = _SpecialStreet(
    stret_nm="광릉숲음식문화특화테마거리",
    stret_intrcn="향토음식 기반 특화거리",
    rdnmadr="경기도 남양주시 진접읍 광릉수목원로 179-19",
    lnmadr=None,
    latitude=37.74711118,
    longitude=127.1874489,
    stret_lt=480.0,
    stor_number=15,
    appn_year=2015,
    phone_number="031-590-2237",
    institution_nm="경기도 남양주시청 위생과",
    reference_date=date(2026, 3, 26),
    instt_code="3990000",
    instt_nm="경기도 남양주시",
)


def _now() -> datetime:
    return datetime(2026, 6, 12, 18, 30, tzinfo=KST)


@pytest.mark.unit
def test_special_street_feature_fields() -> None:
    bundle = special_streets_to_bundles([_S1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "광릉숲음식문화특화테마거리"
    assert feature.category == SPECIAL_STREET_CATEGORY
    assert feature.marker_color == SPECIAL_STREET_MARKER_COLOR
    assert feature.coord is not None
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "theme_area_anchor"  # type: ignore[union-attr]
    assert detail.phones == ["031-590-2237"]  # type: ignore[union-attr]
    assert detail.facility_info["stor_number"] == 15  # type: ignore[union-attr]
    assert detail.facility_info["stret_lt"] == 480.0  # type: ignore[union-attr]


@pytest.mark.unit
def test_special_street_source_record_and_link() -> None:
    bundle = special_streets_to_bundles([_S1], fetched_at=_now())[0]
    source = bundle.source_record
    assert source.provider == "data.go.kr-standard"
    assert source.dataset_key == DATASET_KEY_SPECIAL_STREETS
    assert source.source_entity_type == "special_street"
    assert source.source_entity_id == (
        "광릉숲음식문화특화테마거리::경기도 남양주시 진접읍 광릉수목원로 179-19"
    )
    assert source.raw_data["reference_date"] == "2026-03-26"
    assert bundle.source_link.source_role == SourceRole.PRIMARY


@pytest.mark.unit
def test_special_street_reverse_geocoder_fills_bjd() -> None:
    async def _rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="4136025321", sigungu_code="41360", sido_code="41")

    bundle = special_streets_to_bundles([_S1], fetched_at=_now(), reverse_geocoder=_rg)[0]
    assert bundle.feature.address.bjd_code == "4136025321"
    assert bundle.feature.feature_id.startswith("f_4136025321_p_")


@pytest.mark.unit
def test_special_street_skips_rows_without_name_or_location() -> None:
    blank = _SpecialStreet(
        stret_nm="",
        stret_intrcn=None,
        rdnmadr="서울특별시 어딘가",
        lnmadr=None,
        latitude=None,
        longitude=None,
        stret_lt=None,
        stor_number=None,
        appn_year=None,
        phone_number=None,
        institution_nm=None,
        reference_date=None,
        instt_code=None,
        instt_nm=None,
    )
    no_location = _SpecialStreet(
        stret_nm="위치없는거리",
        stret_intrcn=None,
        rdnmadr=None,
        lnmadr=None,
        latitude=None,
        longitude=None,
        stret_lt=None,
        stor_number=None,
        appn_year=None,
        phone_number=None,
        institution_nm=None,
        reference_date=None,
        instt_code=None,
        instt_nm=None,
    )
    assert (
        special_streets_to_bundles([blank, no_location, _S1], fetched_at=_now())[0].feature.name
        == "광릉숲음식문화특화테마거리"
    )
