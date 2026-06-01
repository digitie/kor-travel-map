"""``test_etl_live_datagokr_adapters`` — datagokr live loader adapter 검증 (PR#57).

async fetch는 DATAGOKR_SERVICE_KEY 필요해 CI 미검증. raw dict(표준데이터 alias) →
`CulturalFestivalItem` Protocol adapter(순수 함수)를 검증하고, adapter 결과가
실제 `cultural_festivals_to_bundles`를 통과하는지 본다 (로컬 python-datagokr-api
`PublicCulturalFestival` alias 기준 — ADR-044).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

from krtour.map_admin.etl_live import (
    _adapt_datagokr_festival,
    _datagokr_parse_date,
)

_KST = timezone(timedelta(hours=9))

# 표준데이터 raw JSON (PublicCulturalFestival alias 그대로).
_RAW = {
    "fstvlNm": "서울 봄꽃 축제",
    "opar": "여의도공원",
    "fstvlStartDate": "2026-04-05",
    "fstvlEndDate": "2026-04-12",
    "fstvlCo": "봄꽃 축제 상세 설명.",
    "mnnstNm": "영등포구청",
    "phoneNumber": "02-2670-3114",
    "rdnmadr": "서울특별시 영등포구 여의공원로 120",
    "lnmadr": "서울특별시 영등포구 여의도동 8",
    "latitude": "37.5263",
    "longitude": "126.9239",
    "referenceDate": "2026-03-01",
    "instt_nm": "서울특별시 영등포구",
}


@pytest.mark.unit
def test_parse_date_variants() -> None:
    assert _datagokr_parse_date("2026-04-05") == date(2026, 4, 5)
    assert _datagokr_parse_date("20260405") == date(2026, 4, 5)
    assert _datagokr_parse_date("2026.04.05") == date(2026, 4, 5)
    assert _datagokr_parse_date(None) is None
    assert _datagokr_parse_date("bad") is None


@pytest.mark.unit
def test_adapt_festival_maps_alias_fields() -> None:
    a = _adapt_datagokr_festival(_RAW)
    assert a.festival_name == "서울 봄꽃 축제"
    assert a.venue_name == "여의도공원"
    assert a.start_date == date(2026, 4, 5)
    assert a.end_date == date(2026, 4, 12)
    assert a.description == "봄꽃 축제 상세 설명."
    assert a.organizer_name == "영등포구청"
    assert a.organizer_tel == "02-2670-3114"
    assert a.road_address == "서울특별시 영등포구 여의공원로 120"
    assert a.jibun_address == "서울특별시 영등포구 여의도동 8"
    assert a.latitude is not None
    assert a.longitude is not None
    assert float(a.latitude) == 37.5263
    assert float(a.longitude) == 126.9239
    assert a.data_reference_date == date(2026, 3, 1)
    assert a.provider_org_name == "서울특별시 영등포구"


@pytest.mark.unit
def test_adapt_festival_synthesizes_management_no() -> None:
    """표준데이터에 관리번호 없음 → (축제명@도로명) 합성, 결정적."""
    a = _adapt_datagokr_festival(_RAW)
    b = _adapt_datagokr_festival(dict(_RAW))
    assert a.management_no == b.management_no  # 결정적
    assert "서울 봄꽃 축제" in a.management_no


@pytest.mark.unit
def test_adapt_festival_handles_missing_coords() -> None:
    raw = {k: v for k, v in _RAW.items() if k not in {"latitude", "longitude"}}
    a = _adapt_datagokr_festival(raw)
    assert a.latitude is None
    assert a.longitude is None


@pytest.mark.unit
async def test_festival_adapter_passes_transform() -> None:
    """adapter 결과가 실제 cultural_festivals_to_bundles를 통과 (Protocol 정합)."""
    bundles = await cultural_festivals_to_bundles(
        [_adapt_datagokr_festival(_RAW)],  # type: ignore[list-item]
        fetched_at=datetime.now(tz=_KST),
    )
    assert len(bundles) == 1
    assert bundles[0].feature.kind.value == "event"
    assert bundles[0].feature.name == "서울 봄꽃 축제"
