"""``test_dto_price`` — PriceValue DTO (PR#42)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from kortravelmap.dto import PriceDomain, PriceValue

KST = timezone(timedelta(hours=9))


def _now() -> datetime:
    return datetime(2026, 5, 28, 3, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_opinet_gasoline_happy() -> None:
    p = PriceValue(
        feature_id="f_1156010100_p_abc",
        provider="python-opinet-api",
        price_domain=PriceDomain.OPINET_GAS_STATION,
        product_key="gasoline",
        product_name="휘발유",
        value_number=Decimal("1820.0"),
        unit="KRW/L",
        observed_at=_now(),
    )
    assert p.value_number == Decimal("1820.0")
    assert p.unit == "KRW/L"
    assert p.product_key == "gasoline"


@pytest.mark.unit
def test_default_unit_krw() -> None:
    """unit 기본값 KRW (입장료 등 가격 단위만 있는 dataset)."""
    p = PriceValue(
        feature_id="f_global_p_abc",
        provider="python-krex-api",
        price_domain=PriceDomain.ADMISSION_FEE,
        product_key="adult",
        value_number=Decimal("3000"),
        observed_at=_now(),
    )
    assert p.unit == "KRW"


@pytest.mark.unit
def test_naive_observed_at_rejected() -> None:
    naive = datetime(2026, 5, 28, 3, 0, 0)
    with pytest.raises(ValueError, match="aware"):
        PriceValue(
            feature_id="f_global_p_abc",
            provider="python-opinet-api",
            price_domain=PriceDomain.OPINET_GAS_STATION,
            product_key="gasoline",
            value_number=Decimal("1820"),
            observed_at=naive,
        )


@pytest.mark.unit
def test_negative_value_rejected() -> None:
    with pytest.raises(ValueError, match="0 이상"):
        PriceValue(
            feature_id="f_global_p_abc",
            provider="python-opinet-api",
            price_domain=PriceDomain.OPINET_GAS_STATION,
            product_key="gasoline",
            value_number=Decimal("-100"),
            observed_at=_now(),
        )


@pytest.mark.unit
def test_zero_value_allowed() -> None:
    """0원 가격 (이벤트 무료 등) 허용."""
    p = PriceValue(
        feature_id="f_global_p_abc",
        provider="python-krex-api",
        price_domain=PriceDomain.ADMISSION_FEE,
        product_key="adult",
        value_number=Decimal("0"),
        observed_at=_now(),
    )
    assert p.value_number == Decimal("0")


@pytest.mark.unit
def test_extra_field_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        PriceValue(
            feature_id="f_global_p_abc",
            provider="python-opinet-api",
            price_domain=PriceDomain.OPINET_GAS_STATION,
            product_key="gasoline",
            value_number=Decimal("1820"),
            observed_at=_now(),
            unknown_field="x",  # type: ignore[call-arg]
        )


@pytest.mark.unit
def test_identity_tuple() -> None:
    p = PriceValue(
        feature_id="f_1156010100_p_abc",
        provider="python-opinet-api",
        price_domain=PriceDomain.OPINET_GAS_STATION,
        product_key="gasoline",
        value_number=Decimal("1820"),
        observed_at=_now(),
    )
    assert p.identity() == (
        "f_1156010100_p_abc",
        "python-opinet-api",
        "opinet_gas_station",
        "gasoline",
        _now(),
    )


@pytest.mark.unit
def test_identity_differs_on_product_key() -> None:
    base = dict(
        feature_id="f_1156010100_p_abc",
        provider="python-opinet-api",
        price_domain=PriceDomain.OPINET_GAS_STATION,
        value_number=Decimal("1820"),
        observed_at=_now(),
    )
    a = PriceValue(**base, product_key="gasoline")
    b = PriceValue(**base, product_key="diesel")
    assert a.identity() != b.identity()


@pytest.mark.unit
def test_collected_at_default_kst_aware() -> None:
    p = PriceValue(
        feature_id="f_global_p_abc",
        provider="python-opinet-api",
        price_domain=PriceDomain.OPINET_GAS_STATION,
        product_key="gasoline",
        value_number=Decimal("1820"),
        observed_at=_now(),
    )
    assert p.collected_at.tzinfo is not None
