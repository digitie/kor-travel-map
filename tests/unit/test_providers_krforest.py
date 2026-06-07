"""``test_providers_krforest`` — 산림청 휴양림/수목원 → FeatureBundle (T-RV-53a).

범위: ``recreation_forests_to_bundles`` / ``arboretums_to_bundles`` happy path,
좌표 nullable, 파생 자연키(institution_code 없음), place 카테고리/place_kind,
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
from krtour.map.providers.krforest import (
    ARBORETUM_CATEGORY,
    DATASET_KEY_ARBORETUMS,
    DATASET_KEY_RECREATION_FORESTS,
    KRFOREST_MARKER_COLOR,
    RECREATION_FOREST_CATEGORY,
)
from krtour.map.providers.krforest import (
    arboretums_to_bundles as _arboretums_async,
)
from krtour.map.providers.krforest import (
    recreation_forests_to_bundles as _recreation_forests_async,
)

KST = timezone(timedelta(hours=9))


def recreation_forests_to_bundles(
    items: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    return asyncio.run(_recreation_forests_async(items, **kwargs))


def arboretums_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_arboretums_async(items, **kwargs))


@dataclass(frozen=True)
class _Forest:
    """``RecreationForestItem`` Protocol 만족 fixture."""

    name: str | None
    sido_name: str | None
    forest_type: str | None
    address: str | None
    phone_number: str | None
    homepage_url: str | None
    latitude: float | None
    longitude: float | None
    institution_code: str | None
    raw: Any = field(default_factory=dict)


@dataclass(frozen=True)
class _Arb:
    """``ForestSpatialItem`` Protocol 만족 fixture."""

    name: str | None
    category: str | None
    address: str | None
    phone_number: str | None
    homepage_url: str | None
    latitude: float | None
    longitude: float | None
    region_code: str | None
    region_name: str | None
    raw: Any = field(default_factory=dict)


_FOREST_1 = _Forest(
    name="유명산자연휴양림",
    sido_name="경기도",
    forest_type="국립",
    address="경기도 가평군 설악면 유명산길 79-53",
    phone_number="031-589-5487",
    homepage_url="https://www.foresttrip.go.kr",
    latitude=37.6042,
    longitude=127.4831,
    institution_code="KFS-0001",
)

_FOREST_NO_CODE = _Forest(
    name="대관령자연휴양림",
    sido_name="강원특별자치도",
    forest_type="국립",
    address="강원특별자치도 강릉시 성산면 대관령옛길 999",
    phone_number=None,
    homepage_url=None,
    latitude=None,
    longitude=None,
    institution_code=None,  # 파생키 name::sido
)

_ARB_1 = _Arb(
    name="국립세종수목원",
    category="국립수목원",
    address="세종특별자치시 수목원로 136",
    phone_number="044-251-0001",
    homepage_url="https://www.sjna.or.kr",
    latitude=36.4978,
    longitude=127.2895,
    region_code="36110",
    region_name="세종특별자치시",
)


def _now() -> datetime:
    return datetime(2026, 6, 7, 12, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_recreation_forest_bundle_per_item_and_order() -> None:
    bundles = recreation_forests_to_bundles(
        [_FOREST_1, _FOREST_NO_CODE], fetched_at=_now()
    )
    assert len(bundles) == 2
    assert bundles[0].source_record.source_entity_id == "KFS-0001"


@pytest.mark.unit
def test_recreation_forest_feature_fields() -> None:
    bundle = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "유명산자연휴양림"
    assert feature.category == RECREATION_FOREST_CATEGORY  # 03030000
    assert feature.marker_color == KRFOREST_MARKER_COLOR
    assert feature.marker_icon  # 비어있지 않음(min_length=1)
    assert feature.coord is not None
    assert float(feature.coord.lat) == pytest.approx(37.6042)
    assert float(feature.coord.lon) == pytest.approx(127.4831)
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "recreation_forest"  # type: ignore[union-attr]
    assert detail.phones == ["031-589-5487"]  # type: ignore[union-attr]
    assert (  # forest_type가 facility_info에 보존
        detail.facility_info["forest_type"] == "국립"  # type: ignore[union-attr]
    )
    assert feature.feature_id.startswith("f_global_p_")


@pytest.mark.unit
def test_recreation_forest_derived_key_when_no_institution_code() -> None:
    bundle = recreation_forests_to_bundles([_FOREST_NO_CODE], fetched_at=_now())[0]
    # institution_code 없음 → name::sido 파생키.
    assert bundle.source_record.source_entity_id == "대관령자연휴양림::강원특별자치도"
    assert bundle.feature.coord is None
    assert bundle.feature.feature_id.startswith("f_global_p_")


@pytest.mark.unit
def test_arboretum_feature_fields_and_category() -> None:
    bundle = arboretums_to_bundles([_ARB_1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "국립세종수목원"
    assert feature.category == ARBORETUM_CATEGORY  # 01030000
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "arboretum"  # type: ignore[union-attr]
    # 안정키 없음 → name::region_code 파생.
    assert bundle.source_record.source_entity_id == "국립세종수목원::36110"
    assert bundle.source_record.dataset_key == DATASET_KEY_ARBORETUMS


@pytest.mark.unit
def test_source_record_provider_and_dataset() -> None:
    source = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0].source_record
    assert source.provider == "python-krforest-api"
    assert source.dataset_key == DATASET_KEY_RECREATION_FORESTS
    assert source.source_entity_type == "recreation_forest"
    assert source.raw_data["institution_code"] == "KFS-0001"


@pytest.mark.unit
def test_source_link_primary() -> None:
    link = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0].source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.match_method == "natural_key"
    assert link.confidence == 100
    assert link.is_primary_source is True


@pytest.mark.unit
def test_bundle_fk_consistency_and_determinism() -> None:
    a = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0]
    b = recreation_forests_to_bundles([_FOREST_1], fetched_at=_now())[0]
    assert a.feature.feature_id == a.source_link.feature_id
    assert a.source_record.source_record_key == a.source_link.source_record_key
    assert a.feature.feature_id == b.feature.feature_id
    assert a.source_record.source_record_key == b.source_record.source_record_key


@pytest.mark.unit
def test_naive_fetched_at_rejected() -> None:
    with pytest.raises(ValueError, match="aware"):
        recreation_forests_to_bundles(
            [_FOREST_1], fetched_at=datetime(2026, 6, 7, 12, 0, 0)
        )


@pytest.mark.unit
def test_reverse_geocoder_fills_bjd_code() -> None:
    async def _fake_rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="4151025000", sigungu_code="41510", sido_code="41")

    bundle = recreation_forests_to_bundles(
        [_FOREST_1], fetched_at=_now(), reverse_geocoder=_fake_rg
    )[0]
    assert bundle.feature.address.bjd_code == "4151025000"
    assert bundle.feature.feature_id.startswith("f_4151025000_p_")
