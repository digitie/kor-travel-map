"""``test_providers_standard_tourist`` — datagokr 관광지 표준데이터 (T-RV-55a)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from krtour.map.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from krtour.map.providers.standard_data import (
    DATASET_KEY_TOURIST_ATTRACTIONS,
    TOURIST_ATTRACTION_CATEGORY,
    TOURIST_MARKER_COLOR,
)
from krtour.map.providers.standard_data import (
    tourist_attractions_to_bundles as _tourist_async,
)

KST = timezone(timedelta(hours=9))


def tourist_attractions_to_bundles(
    items: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    return asyncio.run(_tourist_async(items, **kwargs))


@dataclass(frozen=True)
class _Tourist:
    trrsrt_nm: str | None
    trrsrt_se: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    phone_number: str | None
    instt_code: str | None
    raw: Any = field(default_factory=dict)


_T1 = _Tourist(
    trrsrt_nm="에버랜드",
    trrsrt_se="테마파크",
    rdnmadr="경기도 용인시 처인구 포곡읍 에버랜드로 199",
    lnmadr=None,
    latitude=37.2940,
    longitude=127.2020,
    phone_number="031-320-5000",
    instt_code="TR-0001",
)


def _now() -> datetime:
    return datetime(2026, 6, 7, 12, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_tourist_feature_fields() -> None:
    bundle = tourist_attractions_to_bundles([_T1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "에버랜드"
    assert feature.category == TOURIST_ATTRACTION_CATEGORY  # 01000000
    assert feature.marker_color == TOURIST_MARKER_COLOR
    assert feature.marker_icon
    assert feature.coord is not None
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "tourist_attraction"  # type: ignore[union-attr]
    assert detail.phones == ["031-320-5000"]  # type: ignore[union-attr]
    assert bundle.source_record.dataset_key == DATASET_KEY_TOURIST_ATTRACTIONS


@pytest.mark.unit
def test_tourist_derived_key_when_no_instt_code() -> None:
    item = _Tourist(
        trrsrt_nm="남이섬",
        trrsrt_se="관광지",
        rdnmadr="강원특별자치도 춘천시 남산면 남이섬길 1",
        lnmadr=None,
        latitude=None,
        longitude=None,
        phone_number=None,
        instt_code=None,
    )
    bundle = tourist_attractions_to_bundles([item], fetched_at=_now())[0]
    expected = "남이섬::강원특별자치도 춘천시 남산면 남이섬길 1"
    assert bundle.source_record.source_entity_id == expected
    assert bundle.feature.coord is None
    assert bundle.feature.feature_id.startswith("f_global_p_")


@pytest.mark.unit
def test_tourist_source_link_primary_and_determinism() -> None:
    a = tourist_attractions_to_bundles([_T1], fetched_at=_now())[0]
    b = tourist_attractions_to_bundles([_T1], fetched_at=_now())[0]
    assert a.source_record.provider == "data.go.kr-standard"
    assert a.source_record.source_entity_type == "tourist_attraction"
    assert a.source_link.source_role == SourceRole.PRIMARY
    assert a.source_link.confidence == 100
    assert a.feature.feature_id == b.feature.feature_id


@pytest.mark.unit
def test_tourist_reverse_geocoder_fills_bjd() -> None:
    async def _rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="4146025300", sigungu_code="41460", sido_code="41")

    bundle = tourist_attractions_to_bundles([_T1], fetched_at=_now(), reverse_geocoder=_rg)[0]
    assert bundle.feature.address.bjd_code == "4146025300"
    assert bundle.feature.feature_id.startswith("f_4146025300_p_")
