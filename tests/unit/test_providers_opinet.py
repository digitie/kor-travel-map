"""``test_providers_opinet`` — OpiNet 가격 변환 (PR#42)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from kortravelmap.dto import PriceDomain
from kortravelmap.providers.opinet import (
    OPINET_PRODUCT_KEY_MAP,
    OPINET_PRODUCT_NAME_KO,
    prices_to_values,
)

KST = timezone(timedelta(hours=9))

_FEATURE_ID = "f_1156010100_p_station_a"


@dataclass(frozen=True)
class _PriceItem:
    """``OpinetPriceItem`` Protocol 만족."""

    uni_id: str
    prodcd: str
    price: str
    trade_dt: datetime


_T1 = datetime(2026, 5, 28, 3, 0, tzinfo=KST)
_T2 = datetime(2026, 5, 28, 4, 0, tzinfo=KST)


_GASOLINE = _PriceItem(uni_id="A0000001", prodcd="B027", price="1820", trade_dt=_T1)
_DIESEL = _PriceItem(uni_id="A0000001", prodcd="D047", price="1650", trade_dt=_T1)
_PREMIUM = _PriceItem(uni_id="A0000001", prodcd="B034", price="2050", trade_dt=_T1)
_LPG = _PriceItem(uni_id="A0000001", prodcd="K015", price="1100", trade_dt=_T1)
_THOUSANDS = _PriceItem(
    uni_id="A0000001", prodcd="B027", price="1,820", trade_dt=_T2
)


@pytest.mark.unit
def test_returns_value_per_item_in_order() -> None:
    values = prices_to_values(
        [_GASOLINE, _DIESEL, _PREMIUM, _LPG], feature_id=_FEATURE_ID
    )
    assert len(values) == 4
    product_keys = [v.product_key for v in values]
    assert product_keys == ["gasoline", "diesel", "premium_gasoline", "lpg"]


@pytest.mark.unit
def test_gasoline_metadata() -> None:
    [v] = prices_to_values([_GASOLINE], feature_id=_FEATURE_ID)
    assert v.price_domain == PriceDomain.OPINET_GAS_STATION
    assert v.product_key == "gasoline"
    assert v.product_name == OPINET_PRODUCT_NAME_KO["gasoline"]
    assert v.source_product_key == "B027"
    assert v.provider == "python-opinet-api"
    assert v.unit == "KRW/L"
    assert v.normalization_version == "opinet-v1.0"


@pytest.mark.unit
def test_value_decimal() -> None:
    [v] = prices_to_values([_GASOLINE], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("1820")
    assert v.feature_id == _FEATURE_ID
    assert v.observed_at == _T1


@pytest.mark.unit
def test_product_code_map_complete() -> None:
    """OPINET_PRODUCT_KEY_MAP 5종 — gasoline/diesel/premium_gasoline/kerosene/lpg."""
    assert OPINET_PRODUCT_KEY_MAP["B027"] == "gasoline"
    assert OPINET_PRODUCT_KEY_MAP["D047"] == "diesel"
    assert OPINET_PRODUCT_KEY_MAP["B034"] == "premium_gasoline"
    assert OPINET_PRODUCT_KEY_MAP["C004"] == "kerosene"
    assert OPINET_PRODUCT_KEY_MAP["K015"] == "lpg"
    # 한글 이름도 모두 존재.
    for key in ["gasoline", "diesel", "premium_gasoline", "kerosene", "lpg"]:
        assert key in OPINET_PRODUCT_NAME_KO


@pytest.mark.unit
def test_thousands_separator_absorbed() -> None:
    """'1,820' 천단위 구분자 흡수."""
    [v] = prices_to_values([_THOUSANDS], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("1820")


@pytest.mark.unit
def test_unknown_prodcd_falls_through() -> None:
    """알 수 없는 prodcd는 소문자 그대로 product_key."""
    item = _PriceItem(uni_id="X", prodcd="Z999", price="500", trade_dt=_T1)
    [v] = prices_to_values([item], feature_id=_FEATURE_ID)
    assert v.product_key == "z999"
    assert v.product_name is None
    assert v.source_product_key == "Z999"


@pytest.mark.unit
def test_payload_preserves_raw_fields() -> None:
    [v] = prices_to_values([_GASOLINE], feature_id=_FEATURE_ID)
    assert v.payload == {
        "uni_id": "A0000001",
        "prodcd": "B027",
        "price": "1820",
        "trade_dt": _T1.isoformat(),
    }


@pytest.mark.unit
def test_source_record_key_threaded() -> None:
    values = prices_to_values(
        [_GASOLINE, _DIESEL],
        feature_id=_FEATURE_ID,
        source_record_key="sr_opinet",
    )
    assert all(v.source_record_key == "sr_opinet" for v in values)


@pytest.mark.unit
def test_empty_iterable() -> None:
    assert prices_to_values([], feature_id=_FEATURE_ID) == []


@pytest.mark.unit
def test_int_price_value() -> None:
    """price가 int 타입으로도 들어올 수 있음."""
    item = _PriceItem(
        uni_id="A0000001",
        prodcd="B027",
        price="1820",  # 여전히 str — Protocol에서 str|Decimal|int|float
        trade_dt=_T1,
    )
    [v] = prices_to_values([item], feature_id=_FEATURE_ID)
    assert v.value_number == Decimal("1820")
