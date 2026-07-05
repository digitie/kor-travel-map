"""``price_repo`` 순수 매퍼 단위 테스트 — DB 없는 row→DTO/enum 정규화만.

load/read 경로(session)는 integration에서 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

import pytest

from kortravelmap.dto.price import PriceValue
from kortravelmap.infra.price_repo import (
    _enum_value,
    _price_point,
    _price_value_params,
    _sort_current,
)

pytestmark = pytest.mark.unit


def _point(product_key: str, product_name: str | None = None):  # type: ignore[no-untyped-def]
    return _price_point(
        {
            "provider": "python-opinet-api",
            "price_domain": "fuel",
            "product_key": product_key,
            "product_name": product_name,
            "source_product_key": None,
            "source_product_name": None,
            "value_number": Decimal("1500"),
            "unit": "KRW/L",
            "observed_at": datetime(2026, 7, 4, 9, 0, tzinfo=UTC),
        }
    )


class _Domain(Enum):
    FUEL = "fuel"


def test_enum_value_unwraps_enum_and_passes_through_plain() -> None:
    assert _enum_value(_Domain.FUEL) == "fuel"
    assert _enum_value("fuel") == "fuel"


def test_price_point_maps_row_columns() -> None:
    row = {
        "provider": "python-opinet-api",
        "price_domain": "fuel",
        "product_key": "gasoline",
        "product_name": "휘발유",
        "source_product_key": "B027",
        "source_product_name": "휘발유",
        "value_number": Decimal("1685.00"),
        "unit": "KRW/L",
        "observed_at": datetime(2026, 7, 4, 9, 0, tzinfo=UTC),
    }
    point = _price_point(row)  # type: ignore[arg-type]
    assert point.provider == "python-opinet-api"
    assert point.price_domain == "fuel"
    assert point.product_key == "gasoline"
    assert point.product_name == "휘발유"
    assert point.value_number == Decimal("1685.00")
    assert point.unit == "KRW/L"
    assert point.observed_at.tzinfo is not None


def test_price_value_params_builds_deterministic_upsert_row() -> None:
    value = PriceValue(
        feature_id="f_1156010100_p_abc",
        provider="python-opinet-api",
        price_domain="opinet_gas_station",
        product_key="gasoline",
        product_name="휘발유",
        value_number=Decimal("1820.0"),
        unit="KRW/L",
        observed_at=datetime(2026, 7, 4, 3, 0, tzinfo=UTC),
    )
    params = _price_value_params(value)

    # price_domain enum은 문자열로 정규화된다.
    assert params["price_domain"] == "opinet_gas_station"
    assert params["feature_id"] == "f_1156010100_p_abc"
    assert params["provider"] == "python-opinet-api"
    assert params["product_key"] == "gasoline"
    assert params["value_number"] == Decimal("1820.0")
    # 결정적 PK key가 채워진다.
    assert isinstance(params["price_value_key"], str)
    assert params["price_value_key"]
    # payload는 JSON 문자열로 직렬화.
    assert isinstance(params["payload"], str)


def test_sort_current_tiebreaks_by_name_then_key() -> None:
    # 미정의 product는 동일 order로 떨어지므로 name→key 순으로 정렬된다.
    ordered = _sort_current([_point("zzz-unknown"), _point("aaa-unknown")])
    assert [p.product_key for p in ordered] == ["aaa-unknown", "zzz-unknown"]
