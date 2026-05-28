"""``test_etl_live_kma_alert_adapters`` — KMA 특보현황 live adapter 검증 (PR#58).

apihub `wrn_now_data` async fetch는 KMA_APIHUB_KEY 필요해 CI 미검증. 본 모듈은
text 응답 파서(`_kma_apihub_parse_table`) + raw 행 → `KmaWeatherAlertItem`
Protocol adapter(`_adapt_kma_wrn_row`)를 검증하고, adapter 결과가 실제
`weather_alerts_to_notice_bundles`(region fan-out)를 통과하는지 본다 (ADR-044).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from krtour.map.providers.kma import weather_alerts_to_notice_bundles

from krtour.map_debug_ui.etl_live import (
    KST,
    _adapt_datagokr_wrn,
    _adapt_kma_wrn_row,
    _datagokr_wrn_level,
    _datagokr_wrn_notice_type,
    _kma_apihub_parse_dt,
    _kma_apihub_parse_table,
)

# apihub wrn_now_data 모의 응답 — `#`-주석 헤더 + 콤마 구분 데이터 행.
_SAMPLE_TEXT = """#START7777
#  특보현황 조회 (wrn_now_data)
#  REG_ID  : 특보구역코드
#  WRN     : 특보종류 (R:호우 H:폭염 ...)
# REG_ID TM_FC TM_EF WRN LVL CMD ED_TM
L1010100,202605281100,202605281130,R,2,1,
L1100600,202605281100,202605281200,H,1,1,
#7777END
"""

# 공백 구분 변형 (apihub 일부 endpoint는 공백 table — 파서가 양쪽 지원).
_SAMPLE_TEXT_WS = (
    "# REG_ID TM_FC TM_EF WRN LVL CMD\n"
    "L1010100 202605281100 202605281130 S 2 1\n"
)


@pytest.mark.unit
def test_parse_dt_variants() -> None:
    assert _kma_apihub_parse_dt("202605281130") == datetime(
        2026, 5, 28, 11, 30, tzinfo=KST
    )
    assert _kma_apihub_parse_dt("20260528") == datetime(2026, 5, 28, tzinfo=KST)
    assert _kma_apihub_parse_dt(None) is None
    assert _kma_apihub_parse_dt("bad") is None
    assert _kma_apihub_parse_dt("") is None


@pytest.mark.unit
def test_parse_table_finds_comment_header() -> None:
    rows = _kma_apihub_parse_table(_SAMPLE_TEXT)
    assert len(rows) == 2
    assert rows[0]["REG_ID"] == "L1010100"
    assert rows[0]["WRN"] == "R"
    assert rows[0]["LVL"] == "2"
    assert rows[1]["REG_ID"] == "L1100600"
    assert rows[1]["WRN"] == "H"


@pytest.mark.unit
def test_parse_table_whitespace_delimited() -> None:
    rows = _kma_apihub_parse_table(_SAMPLE_TEXT_WS)
    assert len(rows) == 1
    assert rows[0]["REG_ID"] == "L1010100"
    assert rows[0]["WRN"] == "S"


@pytest.mark.unit
def test_parse_table_no_header_returns_empty() -> None:
    """known 컬럼 토큰 없는 응답 → graceful 빈 list."""
    assert _kma_apihub_parse_table("# 그냥 안내문\n데이터없음\n") == []
    assert _kma_apihub_parse_table("") == []


@pytest.mark.unit
def test_adapt_row_maps_known_warning_code() -> None:
    rows = _kma_apihub_parse_table(_SAMPLE_TEXT)
    a = _adapt_kma_wrn_row(rows[0])
    assert a is not None
    # R(호우) + LVL 2(경보) → heavy_rain_warning, level 경보.
    assert a.alert_type == "heavy_rain_warning"
    assert a.level == "경보"
    assert a.title == "호우경보"
    assert a.issued_at == datetime(2026, 5, 28, 11, 0, tzinfo=KST)
    assert a.effective_from == datetime(2026, 5, 28, 11, 30, tzinfo=KST)
    assert a.source_agency == "기상청"
    assert len(a.regions) == 1
    assert a.regions[0].region_code == "L1010100"
    # alert_id는 결정적 (구역×발표×종류×등급).
    assert a.alert_id == "L1010100:202605281100:R:2"


@pytest.mark.unit
def test_adapt_row_unspecced_code_degrades_to_weather_alert() -> None:
    """alias 미등록 종류(강풍 W 등)는 generic weather_alert로 강등."""
    row = {"REG_ID": "L1010100", "TM_FC": "202605281100", "WRN": "W", "LVL": "1"}
    a = _adapt_kma_wrn_row(row)
    assert a is not None
    assert a.alert_type == "weather_alert"
    assert a.title == "강풍주의보"


@pytest.mark.unit
def test_adapt_row_missing_required_returns_none() -> None:
    assert _adapt_kma_wrn_row({"TM_FC": "202605281100", "LVL": "1"}) is None  # no REG/WRN
    assert _adapt_kma_wrn_row({"REG_ID": "L1010100"}) is None  # no WRN


@pytest.mark.unit
def test_adapter_passes_transform() -> None:
    """adapter 결과가 실제 weather_alerts_to_notice_bundles를 통과 (Protocol 정합)."""
    rows = _kma_apihub_parse_table(_SAMPLE_TEXT)
    adapted = [a for a in (_adapt_kma_wrn_row(r) for r in rows) if a is not None]
    bundles = weather_alerts_to_notice_bundles(
        adapted,  # type: ignore[arg-type]
        fetched_at=datetime.now(tz=KST),
    )
    # 2 alert × 1 region each → 2 bundle (notice).
    assert len(bundles) == 2
    assert bundles[0].feature.kind.value == "notice"
    assert bundles[0].feature.detail.notice_type == "heavy_rain_warning"
    assert bundles[1].feature.detail.notice_type == "heat_wave_warning"


# ── data.go.kr getWthrWrnList fallback (PR#60) — apihub 활용신청 전 live 경로 ──

# 실 getWthrWrnList 응답 형태 (2026-05 확인): stnId/title/tmFc(int)/tmSeq.
_DG_WRN_ROW = {
    "stnId": "108",
    "title": "[특보] 제05-115호 : 2026.05.27.04:00 / 강풍주의보·풍랑주의보 발효 (*)",
    "tmFc": 202605270400,
    "tmSeq": 115,
}


@pytest.mark.unit
def test_datagokr_wrn_notice_type_keyword() -> None:
    assert _datagokr_wrn_notice_type("호우주의보 발효") == "heavy_rain_warning"
    assert _datagokr_wrn_notice_type("대설경보") == "heavy_snow_warning"
    assert _datagokr_wrn_notice_type("폭염주의보") == "heat_wave_warning"
    # alias 미등록 종류 → generic weather_alert (ValueError 회피).
    assert _datagokr_wrn_notice_type("강풍주의보·풍랑주의보") == "weather_alert"
    assert _datagokr_wrn_notice_type("특보 없음") == "weather_alert"


@pytest.mark.unit
def test_datagokr_wrn_level_priority() -> None:
    assert _datagokr_wrn_level("호우경보") == "경보"
    assert _datagokr_wrn_level("강풍주의보") == "주의보"
    assert _datagokr_wrn_level("예비특보 발표") == "예비특보"
    assert _datagokr_wrn_level("특보 해제") is None


@pytest.mark.unit
def test_adapt_datagokr_wrn_maps_fields() -> None:
    a = _adapt_datagokr_wrn(_DG_WRN_ROW)
    assert a.alert_id == "108:202605270400:115"  # 결정적 자연키
    assert a.alert_type == "weather_alert"  # 강풍 → generic
    assert a.level == "주의보"
    assert a.issued_at == datetime(2026, 5, 27, 4, 0, tzinfo=KST)
    assert a.source_agency == "기상청"
    assert len(a.regions) == 1
    assert a.regions[0].region_code == "stn:108"
    assert a.regions[0].region_name == "기상청(전국 본청)"


@pytest.mark.unit
def test_adapt_datagokr_wrn_unknown_stn_fallback_name() -> None:
    a = _adapt_datagokr_wrn({"stnId": "999", "title": "호우경보", "tmFc": "202605270400"})
    assert a.regions[0].region_name == "KMA 관서 999"
    assert a.alert_type == "heavy_rain_warning"
    assert a.level == "경보"


@pytest.mark.unit
def test_datagokr_wrn_passes_transform() -> None:
    """fallback adapter 결과도 weather_alerts_to_notice_bundles 통과."""
    bundles = weather_alerts_to_notice_bundles(
        [_adapt_datagokr_wrn(_DG_WRN_ROW)],  # type: ignore[list-item]
        fetched_at=datetime.now(tz=KST),
    )
    assert len(bundles) == 1
    assert bundles[0].feature.kind.value == "notice"
    assert bundles[0].feature.detail.notice_type == "weather_alert"
