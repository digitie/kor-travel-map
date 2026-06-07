"""``test_providers_krairport`` — 공항 메타데이터 → FeatureBundle (T-RV-55e)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from krtour.map.dto import Address, Coordinate, FeatureBundle, FeatureKind, SourceRole
from krtour.map.providers.krairport import (
    AIRPORT_CATEGORY,
    AIRPORT_MARKER_COLOR,
    DATASET_KEY_AIRPORTS,
)
from krtour.map.providers.krairport import (
    airports_to_bundles as _airports_async,
)

KST = timezone(timedelta(hours=9))


def airports_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_airports_async(items, **kwargs))


@dataclass(frozen=True)
class _Coord:
    lat: float
    lon: float


@dataclass(frozen=True)
class _Airport:
    code: str
    name_korean: str | None
    name_english: str
    icao_code: str | None
    municipality: str | None
    coordinate: Any


_A1 = _Airport(
    code="ICN",
    name_korean="인천국제공항",
    name_english="Incheon International Airport",
    icao_code="RKSI",
    municipality="인천광역시",
    coordinate=_Coord(lat=37.4602, lon=126.4407),
)


def _now() -> datetime:
    return datetime(2026, 6, 8, 12, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_airport_feature_fields_and_natural_key() -> None:
    bundle = airports_to_bundles([_A1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "인천국제공항"
    assert feature.category == AIRPORT_CATEGORY  # 06050000
    assert feature.marker_color == AIRPORT_MARKER_COLOR
    assert feature.coord is not None
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "airport"  # type: ignore[union-attr]
    assert detail.facility_info["icao_code"] == "RKSI"  # type: ignore[union-attr]
    # 안정키 = 공항 코드(IATA).
    assert bundle.source_record.source_entity_id == "ICN"
    assert bundle.source_record.dataset_key == DATASET_KEY_AIRPORTS
    assert bundle.source_record.source_entity_type == "airport"


@pytest.mark.unit
def test_airport_falls_back_to_english_name() -> None:
    item = _Airport(
        code="GMP",
        name_korean=None,
        name_english="Gimpo International Airport",
        icao_code="RKSS",
        municipality="서울특별시",
        coordinate=_Coord(lat=37.5587, lon=126.7906),
    )
    bundle = airports_to_bundles([item], fetched_at=_now())[0]
    assert bundle.feature.name == "Gimpo International Airport"


@pytest.mark.unit
def test_airport_source_link_primary_and_provider() -> None:
    bundle = airports_to_bundles([_A1], fetched_at=_now())[0]
    assert bundle.source_record.provider == "python-krairport-api"
    assert bundle.source_link.source_role == SourceRole.PRIMARY
    assert bundle.source_link.confidence == 100
    assert bundle.source_link.match_method == "natural_key"


@pytest.mark.unit
def test_airport_missing_coordinate_is_safe() -> None:
    item = _Airport(
        code="XXX",
        name_korean="좌표없음공항",
        name_english="No Coordinate Airport",
        icao_code=None,
        municipality="강원특별자치도",
        coordinate=None,
    )
    bundle = airports_to_bundles([item], fetched_at=_now())[0]
    assert bundle.feature.coord is None
    # 좌표가 없으면 reverse 보강 불가 → municipality가 admin으로 남는다.
    assert bundle.feature.address.admin == "강원특별자치도"


@pytest.mark.unit
def test_airport_reverse_geocoder_fills_bjd() -> None:
    async def _rg(coord: Coordinate) -> Address | None:
        return Address(bjd_code="2818510700", sigungu_code="28185", sido_code="28")

    bundle = airports_to_bundles([_A1], fetched_at=_now(), reverse_geocoder=_rg)[0]
    assert bundle.feature.address.bjd_code == "2818510700"
    assert bundle.feature.feature_id.startswith("f_2818510700_p_")
