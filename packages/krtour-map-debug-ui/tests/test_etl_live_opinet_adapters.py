"""``test_etl_live_opinet_adapters`` — opinet live loader 순수 adapter 검증 (PR#56).

async fetch는 OPINET_SERVICE_KEY가 있어야 동작하므로 CI 미검증. 대신 raw dict →
Protocol-만족 adapter(순수 함수)를 sample payload로 검증하고, KATEC→WGS84
reprojection을 round-trip으로 확인하며, adapter 결과가 실제 변환 함수
(`stations_to_bundles`/`prices_to_values`)를 통과하는지 본다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from krtour.map.providers.opinet import prices_to_values, stations_to_bundles

from krtour.map_debug_ui.etl_live import (
    _OPINET_KATEC_PROJ,
    _adapt_opinet_price,
    _adapt_opinet_station,
    _opinet_katec_to_wgs84,
)

_KST = timezone(timedelta(hours=9))
_FEATURE_ID = "f_global_p_0123456789abcdef0123"


def _seoul_katec() -> tuple[float, float]:
    """서울(127.0, 37.5)을 OpiNet KATEC (x, y)로 forward 변환 (round-trip용)."""
    from pyproj import Transformer

    fwd = Transformer.from_crs("EPSG:4326", _OPINET_KATEC_PROJ, always_xy=True)
    x, y = fwd.transform(127.0, 37.5)
    return float(x), float(y)


# ── KATEC reprojection ────────────────────────────────────────────────


@pytest.mark.unit
def test_katec_roundtrip_seoul() -> None:
    x, y = _seoul_katec()
    out = _opinet_katec_to_wgs84(x, y)
    assert out is not None
    lon, lat = out
    assert abs(float(lon) - 127.0) < 0.001
    assert abs(float(lat) - 37.5) < 0.001


@pytest.mark.unit
def test_katec_out_of_range_returns_none() -> None:
    # 비현실적 KATEC 값 → WGS84 범위 밖이거나 변환 실패 → None.
    assert _opinet_katec_to_wgs84(1e12, 1e12) is None


# ── station adapter ───────────────────────────────────────────────────


@pytest.mark.unit
def test_adapt_station_maps_fields_and_coords() -> None:
    x, y = _seoul_katec()
    raw = {
        "UNI_ID": "A0019314",
        "OS_NM": "서울주유소",
        "POLL_DIV_CO": "SKE",
        "NEW_ADR": "서울특별시 중구 ...",
        "VAN_ADR": "서울특별시 중구 ... 지번",
        "GIS_X_COOR": str(x),
        "GIS_Y_COOR": str(y),
        "TEL": "02-000-0000",
        "LPG_YN": "N",
    }
    a = _adapt_opinet_station(raw)
    assert a.uni_id == "A0019314"
    assert a.station_name == "서울주유소"
    assert a.brand_code == "SKE"
    assert a.address == "서울특별시 중구 ..."  # NEW_ADR(road) 우선
    assert a.tel == "02-000-0000"
    assert a.lpg_yn == "N"
    assert a.longitude is not None
    assert a.latitude is not None
    assert abs(float(a.longitude) - 127.0) < 0.001
    assert abs(float(a.latitude) - 37.5) < 0.001


@pytest.mark.unit
def test_adapt_station_no_coords_when_missing() -> None:
    a = _adapt_opinet_station({"UNI_ID": "X", "OS_NM": "좌표없음주유소"})
    assert a.longitude is None
    assert a.latitude is None


@pytest.mark.unit
def test_station_adapter_passes_transform() -> None:
    x, y = _seoul_katec()
    raw = {"UNI_ID": "A1", "OS_NM": "주유소", "GIS_X_COOR": str(x), "GIS_Y_COOR": str(y)}
    bundles = stations_to_bundles(
        [_adapt_opinet_station(raw)],  # type: ignore[list-item]
        fetched_at=datetime.now(tz=_KST),
    )
    assert len(bundles) == 1
    assert bundles[0].feature.kind.value == "place"
    assert bundles[0].feature.category == "06020000"


# ── price adapter ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_adapt_price_maps_fields() -> None:
    raw = {"PRODCD": "B027", "PRICE": "1650", "TRADE_DT": "20260528", "TRADE_TM": "120000"}
    p = _adapt_opinet_price(raw, uni_id="A1")
    assert p is not None
    assert p.uni_id == "A1"
    assert p.prodcd == "B027"
    assert p.price == Decimal("1650")
    assert p.trade_dt.year == 2026
    assert p.trade_dt.hour == 12


@pytest.mark.unit
def test_adapt_price_none_when_missing() -> None:
    assert _adapt_opinet_price({"PRODCD": "B027"}, uni_id="A1") is None
    assert _adapt_opinet_price({"PRICE": "1650"}, uni_id="A1") is None


@pytest.mark.unit
def test_price_adapter_passes_transform() -> None:
    rows = [
        {"PRODCD": "B027", "PRICE": "1650", "TRADE_DT": "20260528", "TRADE_TM": "120000"},
        {"PRODCD": "D047", "PRICE": "1550", "TRADE_DT": "20260528", "TRADE_TM": "120000"},
    ]
    adapted = [p for r in rows if (p := _adapt_opinet_price(r, uni_id="A1")) is not None]
    values = prices_to_values(adapted, feature_id=_FEATURE_ID)  # type: ignore[arg-type]
    assert len(values) == 2
    assert values[0].price_domain.value == "opinet_gas_station"
