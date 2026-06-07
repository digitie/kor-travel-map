"""``test_providers_standard_museums`` — datagokr 박물관/미술관 표준데이터 (T-RV-54a).

범위: ``museums_to_bundles`` happy path, fclty_type → category 분기(박물관 01040100/
미술관 01040200/미상 01040000), 파생 자연키(instt_code 없음), place place_kind,
결정성, SourceLink PRIMARY, ReverseGeocoder bjd 보강.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from krtour.map.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from krtour.map.providers.standard_data import (
    DATASET_KEY_MUSEUMS,
    MUSEUM_CATEGORY,
    MUSEUM_MARKER_COLOR,
)
from krtour.map.providers.standard_data import (
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
    assert bundle.source_record.source_entity_id == "MUS-0001"
    link = bundle.source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.confidence == 100
    assert link.is_primary_source is True


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
