"""``test_etl_live_krex_adapters`` — krex live loader 순수 adapter 단위 검증 (PR#55).

live loader의 async fetch는 KREX_SERVICE_KEY가 있어야 동작하므로 CI에서 검증
불가. 대신 raw dict → Protocol-만족 dataclass adapter(순수 함수)를 sample
payload로 검증하고, adapter 결과가 실제 본 lib 변환 함수(`rest_areas_to_bundles`
등)를 통과하는지 end-to-end로 확인한다 (Protocol shape 정합).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from krtour.map.providers.krex import (
    rest_area_prices_to_values,
    rest_area_weather_to_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)

from krtour.map_debug_ui.etl_live import (
    _adapt_krex_food_row,
    _adapt_krex_fuel_row,
    _adapt_krex_notice,
    _adapt_krex_rest_area,
    _adapt_krex_weather_row,
)

KST = timezone(timedelta(hours=9))
_OBS = datetime(2026, 5, 28, 10, 0, tzinfo=KST)
_FEATURE_ID = "f_global_p_0123456789abcdef0123"


# ── rest_area adapter ─────────────────────────────────────────────────


@pytest.mark.unit
def test_adapt_rest_area_maps_fields() -> None:
    raw = {
        "serviceAreaCode": "0010",
        "serviceAreaName": "안성휴게소(서울방향)",
        "direction": "서울",
        "routeName": "경부선",
        "svarAddr": "경기도 안성시 ...",
        "telNo": "031-000-0000",
    }
    a = _adapt_krex_rest_area(raw)
    assert a.uni_id == "0010"
    assert a.name == "안성휴게소(서울방향)"
    assert a.direction == "서울"
    assert a.highway_name == "경부선"
    assert a.address == "경기도 안성시 ..."
    assert a.tel == "031-000-0000"
    # serviceAreaRoute 응답에 좌표 없음.
    assert a.longitude is None
    assert a.latitude is None


@pytest.mark.unit
async def test_rest_area_adapter_passes_transform() -> None:
    """adapter 결과가 실제 rest_areas_to_bundles를 통과 (Protocol 정합)."""
    raw = {"serviceAreaCode": "0010", "serviceAreaName": "안성휴게소"}
    bundles = await rest_areas_to_bundles(
        [_adapt_krex_rest_area(raw)], fetched_at=_OBS  # type: ignore[list-item]
    )
    assert len(bundles) == 1
    assert bundles[0].feature.kind.value == "place"


# ── fuel price explode ────────────────────────────────────────────────


@pytest.mark.unit
def test_adapt_fuel_explodes_per_product() -> None:
    raw = {"serviceAreaCode": "0010", "gasoline_price": 1650, "diesel_price": 1550}
    rows = _adapt_krex_fuel_row(raw, observed_at=_OBS)
    keys = {r.product_key for r in rows}
    assert keys == {"gasoline", "diesel"}
    assert all(r.category == "fuel" for r in rows)
    assert all(isinstance(r.price, Decimal) for r in rows)


@pytest.mark.unit
def test_adapt_fuel_skips_zero_and_missing() -> None:
    raw = {"serviceAreaCode": "0010", "gasoline_price": 1650, "lpg_price": 0}
    rows = _adapt_krex_fuel_row(raw, observed_at=_OBS)
    assert {r.product_key for r in rows} == {"gasoline"}


@pytest.mark.unit
def test_adapt_fuel_camelcase_fallback() -> None:
    raw = {"serviceAreaCode": "0010", "gasolinePrice": 1700}
    rows = _adapt_krex_fuel_row(raw, observed_at=_OBS)
    assert rows[0].price == Decimal("1700")


# ── food price ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_adapt_food_row() -> None:
    raw = {"serviceAreaCode": "0010", "foodCode": "F1", "foodName": "우동", "price": 7000}
    food = _adapt_krex_food_row(raw, observed_at=_OBS)
    assert food is not None
    assert food.category == "food"
    assert food.product_key == "F1"
    assert food.product_name == "우동"
    assert food.price == Decimal("7000")


@pytest.mark.unit
def test_adapt_food_none_when_no_price() -> None:
    assert _adapt_krex_food_row({"serviceAreaCode": "0010"}, observed_at=_OBS) is None


@pytest.mark.unit
def test_prices_adapters_pass_transform() -> None:
    """fuel + food adapter 결과가 rest_area_prices_to_values를 통과."""
    fuel = _adapt_krex_fuel_row(
        {"serviceAreaCode": "0010", "gasoline_price": 1650}, observed_at=_OBS
    )
    food = _adapt_krex_food_row(
        {"serviceAreaCode": "0010", "foodCode": "F1", "price": 7000}, observed_at=_OBS
    )
    assert food is not None
    values = rest_area_prices_to_values(
        [*fuel, food], feature_id=_FEATURE_ID  # type: ignore[list-item]
    )
    assert len(values) == 2


# ── weather melt ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_adapt_weather_melts_metrics() -> None:
    raw = {"unitCode": "002 ", "tempValue": 18.5, "humidityValue": 60, "windValue": 2.1}
    rows = _adapt_krex_weather_row(raw, observed_at=_OBS)
    assert {r.metric_key for r in rows} == {"T1H", "REH", "WSD"}
    assert rows[0].uni_id == "002"  # trailing space stripped


@pytest.mark.unit
def test_adapt_weather_drops_sentinel() -> None:
    raw = {"unitCode": "002", "tempValue": -99.0, "humidityValue": 55}
    rows = _adapt_krex_weather_row(raw, observed_at=_OBS)
    assert {r.metric_key for r in rows} == {"REH"}  # -99 temp dropped


@pytest.mark.unit
def test_weather_adapter_passes_transform() -> None:
    raw = {"unitCode": "002", "tempValue": 18.5}
    rows = _adapt_krex_weather_row(raw, observed_at=_OBS)
    values = rest_area_weather_to_values(
        rows, feature_id=_FEATURE_ID  # type: ignore[arg-type]
    )
    assert len(values) == 1
    assert values[0].metric_key == "T1H"


# ── traffic notice synthesis ──────────────────────────────────────────


@pytest.mark.unit
def test_adapt_notice_synthesizes_id_and_agency() -> None:
    raw = {
        "incidentType": "사고",
        "message": "경부선 양방향 정체",
        "startDate": "20260528",
        "startTime": "0930",
    }
    n = _adapt_krex_notice(raw)
    assert n.notice_id  # 합성됨 (raw에 안정 id 없음)
    assert n.source_agency == "한국도로공사"
    assert n.title == "경부선 양방향 정체"
    assert n.valid_from == datetime(2026, 5, 28, 9, 30, tzinfo=KST)


@pytest.mark.unit
def test_adapt_notice_uses_explicit_id() -> None:
    n = _adapt_krex_notice({"incidentId": "INC-1", "message": "x", "incidentType": "공사"})
    assert n.notice_id == "INC-1"


@pytest.mark.unit
async def test_notice_adapter_passes_transform() -> None:
    raw = {"incidentType": "사고", "message": "정체", "startDate": "20260528"}
    bundles = await traffic_notices_to_bundles(
        [_adapt_krex_notice(raw)], fetched_at=_OBS  # type: ignore[list-item]
    )
    assert len(bundles) == 1
    assert bundles[0].feature.kind.value == "notice"
