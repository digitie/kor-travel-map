"""``test_providers_opinet_stations`` — OpiNet 주유소 Feature 변환 (PR#43)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.dto import FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers.opinet import (
    OPINET_PRICE_DATASET_KEY,
    OPINET_STATION_CATEGORY,
    OPINET_STATION_DATASET_KEY,
    OPINET_STATION_MARKER_COLOR,
    OPINET_STATION_MARKER_ICON,
)
from kortravelmap.providers.opinet import (
    station_details_to_price_features_and_values as _price_features_async,
)
from kortravelmap.providers.opinet import (
    stations_to_bundles as _stations_to_bundles_async,
)

KST = timezone(timedelta(hours=9))


def stations_to_bundles(
    items: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    """sync 테스트 ergonomics — 실제 async 변환을 asyncio.run으로 구동."""
    return asyncio.run(_stations_to_bundles_async(items, **kwargs))


def station_details_to_price_features_and_values(
    items: Iterable[Any], **kwargs: Any
) -> tuple[list[FeatureBundle], list[Any]]:
    return asyncio.run(_price_features_async(items, **kwargs))


@dataclass(frozen=True)
class _StationItem:
    """``OpinetStationItem`` Protocol 만족 (provider ``Station`` 정렬, ADR-044).

    ``tel``/``lpg_yn``은 ``Station``엔 없고 ``StationDetail``에만 있으나, 변환이
    ``getattr``로 보강하므로 테스트 dataclass엔 둔다(있을 때 보강 검증). ``lon``/
    ``lat``은 no-coord 케이스 검증용으로 ``None`` 허용(실 ``Station``은 항상 보유).
    """

    uni_id: str
    name: str
    brand: object | None
    address_road: str | None
    address_jibun: str | None
    lon: float | None
    lat: float | None
    tel: str | None = None
    lpg_yn: str | bool | None = None


@dataclass(frozen=True)
class _OilPrice:
    product_code: str
    price: int | None
    trade_date: date
    trade_time: time
    raw: dict[str, Any]


@dataclass(frozen=True)
class _StationDetail(_StationItem):
    prices: tuple[_OilPrice, ...] = ()


_NOW = datetime(2026, 5, 28, 4, 0, tzinfo=KST)


_S1 = _StationItem(
    uni_id="A0000001",
    name="SK주유소 강남점",
    brand="SKE",
    address_road="서울특별시 강남구 테헤란로 100",
    address_jibun=None,
    lon=127.0376,
    lat=37.4979,
    tel="02-1234-5678",
    lpg_yn="Y",
)

_S2 = _StationItem(
    uni_id="A0000002",
    name="GS칼텍스 부산점",
    brand="GSC",
    address_road="부산광역시 해운대구 해운대로 200",
    address_jibun=None,
    lon=129.1604,
    lat=35.1587,
    tel="0517491234",
    lpg_yn="N",
)

_S3_NO_COORD = _StationItem(
    uni_id="A0000003",
    name="현대오일뱅크 ㅈㅓ주점",
    brand="HDO",
    address_road=None,
    address_jibun="제주특별자치도 제주시 노형로 100",
    lon=None,
    lat=None,
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
        name="이상한 주유소",
        brand="X",
        address_road="서울특별시  강남구   테헤란로  100",  # 다중 공백
        address_jibun=None,
        lon=127.0,
        lat=37.5,
    )
    [bundle] = stations_to_bundles([weird], fetched_at=_NOW)
    assert bundle.feature.address.road == "서울특별시 강남구 테헤란로 100"


@pytest.mark.unit
def test_empty_iterable() -> None:
    assert stations_to_bundles([], fetched_at=_NOW) == []


@pytest.mark.unit
def test_station_detail_price_feature_and_values() -> None:
    detail = _StationDetail(
        **_S1.__dict__,
        prices=(
            _OilPrice(
                product_code="B027",
                price=1820,
                trade_date=date(2026, 6, 25),
                trade_time=time(10, 30),
                raw={"PRODCD": "B027", "PRICE": "1820"},
            ),
            _OilPrice(
                product_code="D047",
                price=1650,
                trade_date=date(2026, 6, 25),
                trade_time=time(10, 30),
                raw={"PRODCD": "D047", "PRICE": "1650"},
            ),
        ),
    )

    bundles, values = station_details_to_price_features_and_values(
        [detail], fetched_at=_NOW
    )

    assert len(bundles) == 1
    assert len(values) == 2
    bundle = bundles[0]
    assert bundle.feature.kind == FeatureKind.PRICE
    assert bundle.feature.category == OPINET_STATION_CATEGORY
    assert bundle.feature.name == "SK주유소 강남점 유가"
    assert bundle.feature.parent_feature_id is not None
    assert bundle.source_record.dataset_key == OPINET_PRICE_DATASET_KEY
    assert [value.product_key for value in values] == ["gasoline", "diesel"]
    assert {value.feature_id for value in values} == {bundle.feature.feature_id}


@pytest.mark.unit
def test_station_detail_price_skips_null_price() -> None:
    detail = _StationDetail(
        **_S1.__dict__,
        prices=(
            _OilPrice(
                product_code="B027",
                price=None,
                trade_date=date(2026, 6, 25),
                trade_time=time(10, 30),
                raw={"PRODCD": "B027", "PRICE": None},
            ),
        ),
    )

    bundles, values = station_details_to_price_features_and_values(
        [detail], fetched_at=_NOW
    )

    assert bundles == []
    assert values == []
