"""field ledger 값 직렬화 — numeric field는 JSON number여야 한다 (ADR-128 회귀)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from kortravelmap.infra.feature_repo import _field_value_json_default


@pytest.mark.unit
def test_decimal_values_become_json_numbers() -> None:
    payload = json.dumps(
        {
            "route.total_distance_meters": Decimal("1765.3"),
            "area.area_square_meters": Decimal("2500"),
            "event.starts_on": date(2026, 11, 27),
        },
        default=_field_value_json_default,
    )
    decoded = json.loads(payload)
    assert decoded["route.total_distance_meters"] == 1765.3
    assert decoded["area.area_square_meters"] == 2500
    assert isinstance(decoded["area.area_square_meters"], int)
    # 그 밖의 타입은 종전 default=str 그대로다.
    assert decoded["event.starts_on"] == "2026-11-27"


@pytest.mark.unit
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_decimal_is_rejected(value: Decimal) -> None:
    with pytest.raises(ValueError, match="유한"):
        _field_value_json_default(value)
