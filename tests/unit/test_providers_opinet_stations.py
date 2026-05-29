"""``test_providers_opinet_stations`` — OpiNet 주유소 Feature 변환 (PR#43)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.dto import FeatureBundle, FeatureKind, SourceRole
from krtour.map.providers.opinet import (
    OPINET_STATION_CATEGORY,
    OPINET_STATION_DATASET_KEY,
    OPINET_STATION_MARKER_COLOR,
    OPINET_STATION_MARKER_ICON,
)
from krtour.map.providers.opinet import (
    stations_to_bundles as _stations_to_bundles_async,
)

KST = timezone(timedelta(hours=9))


def stations_to_bundles(
    items: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    """sync 테스트 ergonomics — 실제 async 변환을 asyncio.run으로 구동."""
    return asyncio.run(_stations_to_bundles_async(items, **kwargs))


@dataclass(frozen=True)
class _StationItem:
    """``OpinetStationItem`` Protocol 만족."""

    uni_id: str
    station_name: str
    brand_code: str | None
    address: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    tel: str | None
    lpg_yn: str | bool | None


_NOW = datetime(2026, 5, 28, 4, 0, tzinfo=KST)


_S1 = _StationItem(
    uni_id="A0000001",
    station_name="SK주유소 강남점",
    brand_code="SKE",
    address="서울특별시 강남구 테헤란로 100",
    longitude=Decimal("127.0376"),
    latitude=Decimal("37.4979"),
    tel="02-1234-5678",
    lpg_yn="Y",
)

_S2 = _StationItem(
    uni_id="A0000002",
    station_name="GS칼텍스 부산점",
    brand_code="GSC",
    address="부산광역시 해운대구 해운대로 200",
    longitude=Decimal("129.1604"),
    latitude=Decimal("35.1587"),
    tel="0517491234",
    lpg_yn="N",
)

_S3_NO_COORD = _StationItem(
    uni_id="A0000003",
    station_name="현대오일뱅크 ㅈㅓ주점",
    brand_code="HDO",
    address="제주특별자치도 제주시 노형로 100",
    longitude=None,
    latitude=None,
    tel=None,
    lpg_yn=None,
)


@pytest.mark.unit
def test_returns_bundle_per_item_order() -> None:
    bundles = stations_to_bundles([_S1, _S2, _S3_NO_COORD], fetched_at=_NOW)
    assert len(bundles) == 3
    assert [b.source_record.source_entity_id for b in bundles] == [
        "A0000001",
        "A0000002",
        "A0000003",
    ]


@pytest.mark.unit
def test_feature_metadata_happy() -> None:
    [bundle] = stations_to_bundles([_S1], fetched_at=_NOW)
    f = bundle.feature
    assert f.kind == FeatureKind.PLACE
    assert f.category == OPINET_STATION_CATEGORY  # "06020000"
    assert f.marker_icon == OPINET_STATION_MARKER_ICON  # "fuel"
    assert f.marker_color == OPINET_STATION_MARKER_COLOR  # "P-08"
    assert f.name == "SK주유소 강남점"
    assert f.feature_id.startswith("f_global_p_")  # reverse_geocoder=None → 'global'


@pytest.mark.unit
def test_coordinate_set_when_provided() -> None:
    [bundle] = stations_to_bundles([_S1], fetched_at=_NOW)
    coord = bundle.feature.coord
    assert coord is not None
    assert float(coord.lon) == pytest.approx(127.0376)
    assert float(coord.lat) == pytest.approx(37.4979)


@pytest.mark.unit
def test_no_coord_yields_none_coord() -> None:
    [bundle] = stations_to_bundles([_S3_NO_COORD], fetched_at=_NOW)
    assert bundle.feature.coord is None


@pytest.mark.unit
def test_place_detail_fields() -> None:
    [bundle] = stations_to_bundles([_S1], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.place_kind == "gas_station"  # type: ignore[union-attr]
    assert detail.phones == ["02-1234-5678"]  # type: ignore[union-attr]
    facility = detail.facility_info  # type: ignore[union-attr]
    assert facility["brand_code"] == "SKE"
    assert facility["lpg_yn"] is True


@pytest.mark.unit
def test_phone_normalized() -> None:
    """raw `0517491234` (10자리) → `051-749-1234`."""
    [bundle] = stations_to_bundles([_S2], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.phones == ["051-749-1234"]  # type: ignore[union-attr]


@pytest.mark.unit
def test_lpg_yn_coercion_n() -> None:
    [bundle] = stations_to_bundles([_S2], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.facility_info["lpg_yn"] is False  # type: ignore[union-attr]


@pytest.mark.unit
def test_lpg_yn_none_when_missing() -> None:
    [bundle] = stations_to_bundles([_S3_NO_COORD], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.facility_info["lpg_yn"] is None  # type: ignore[union-attr]


@pytest.mark.unit
def test_source_record_provider_dataset() -> None:
    [bundle] = stations_to_bundles([_S1], fetched_at=_NOW)
    src = bundle.source_record
    assert src.provider == "python-opinet-api"
    assert src.dataset_key == OPINET_STATION_DATASET_KEY
    assert src.source_entity_type == "fuel_station"
    assert src.source_entity_id == "A0000001"
    assert len(src.raw_payload_hash) == 32
    assert src.raw_name == "SK주유소 강남점"
    assert src.raw_address is not None
    assert src.fetched_at == _NOW


@pytest.mark.unit
def test_source_link_primary() -> None:
    [bundle] = stations_to_bundles([_S1], fetched_at=_NOW)
    link = bundle.source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.match_method == "natural_key"
    assert link.confidence == 100
    assert link.is_primary_source is True


@pytest.mark.unit
def test_bundle_fk_consistency() -> None:
    bundles = stations_to_bundles([_S1, _S2, _S3_NO_COORD], fetched_at=_NOW)
    for bundle in bundles:
        assert bundle.feature.feature_id == bundle.source_link.feature_id
        assert (
            bundle.source_record.source_record_key
            == bundle.source_link.source_record_key
        )


@pytest.mark.unit
def test_determinism() -> None:
    a = stations_to_bundles([_S1], fetched_at=_NOW)[0]
    b = stations_to_bundles([_S1], fetched_at=_NOW)[0]
    assert a.feature.feature_id == b.feature.feature_id
    assert (
        a.source_record.source_record_key == b.source_record.source_record_key
    )


@pytest.mark.unit
def test_naive_fetched_at_rejected() -> None:
    naive = datetime(2026, 5, 28, 4, 0, 0)
    with pytest.raises(ValueError, match="aware"):
        stations_to_bundles([_S1], fetched_at=naive)


@pytest.mark.unit
def test_address_normalize_korean() -> None:
    """raw 주소의 다중 공백/전각 공백 흡수."""
    weird = _StationItem(
        uni_id="A_W",
        station_name="이상한 주유소",
        brand_code="X",
        address="서울특별시  강남구   테헤란로  100",  # 다중 공백
        longitude=Decimal("127.0"),
        latitude=Decimal("37.5"),
        tel=None,
        lpg_yn=None,
    )
    [bundle] = stations_to_bundles([weird], fetched_at=_NOW)
    assert bundle.feature.address.road == "서울특별시 강남구 테헤란로 100"


@pytest.mark.unit
def test_empty_iterable() -> None:
    assert stations_to_bundles([], fetched_at=_NOW) == []
