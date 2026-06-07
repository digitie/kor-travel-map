"""``test_providers_khoa`` — 해양수산부 해수욕장정보 → FeatureBundle (T-RV-55c)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from krtour.map.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from krtour.map.providers.khoa import (
    BEACH_CATEGORY,
    BEACH_MARKER_COLOR,
    DATASET_KEY_BEACHES,
)
from krtour.map.providers.khoa import (
    beaches_to_bundles as _beaches_async,
)

KST = timezone(timedelta(hours=9))


def beaches_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_beaches_async(items, **kwargs))


@dataclass(frozen=True)
class _Beach:
    name: str
    sido_name: str
    gugun_name: str | None
    latitude: float | None
    longitude: float | None
    beach_kind: str | None
    image_url: str | None
    raw: Any = field(default_factory=dict)


_B1 = _Beach(
    name="해운대해수욕장",
    sido_name="부산광역시",
    gugun_name="해운대구",
    latitude=35.1587,
    longitude=129.1604,
    beach_kind="해수욕장",
    image_url="https://example.com/haeundae.jpg",
)


def _now() -> datetime:
    return datetime(2026, 6, 8, 12, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_beach_feature_fields_and_derived_key() -> None:
    bundle = beaches_to_bundles([_B1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "해운대해수욕장"
    assert feature.category == BEACH_CATEGORY  # 01020300
    assert feature.marker_color == BEACH_MARKER_COLOR
    assert feature.coord is not None
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "beach"  # type: ignore[union-attr]
    assert detail.facility_info["beach_kind"] == "해수욕장"  # type: ignore[union-attr]
    # 안정키 없음 → name::sido::gugun 파생.
    assert bundle.source_record.source_entity_id == "해운대해수욕장::부산광역시::해운대구"
    assert bundle.source_record.dataset_key == DATASET_KEY_BEACHES
    # 도로명 주소가 없어 admin은 sido+gugun.
    assert bundle.feature.address.admin == "부산광역시 해운대구"


@pytest.mark.unit
def test_beach_source_link_primary_and_provider() -> None:
    bundle = beaches_to_bundles([_B1], fetched_at=_now())[0]
    assert bundle.source_record.provider == "python-khoa-api"
    assert bundle.source_record.source_entity_type == "beach"
    assert bundle.source_link.source_role == SourceRole.PRIMARY
    assert bundle.source_link.confidence == 100


@pytest.mark.unit
def test_beach_reverse_geocoder_fills_bjd() -> None:
    async def _rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="2635010300", sigungu_code="26350", sido_code="26")

    bundle = beaches_to_bundles([_B1], fetched_at=_now(), reverse_geocoder=_rg)[0]
    assert bundle.feature.address.bjd_code == "2635010300"
    assert bundle.feature.feature_id.startswith("f_2635010300_p_")
