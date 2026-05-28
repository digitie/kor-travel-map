"""``test_providers_kma_mid`` — KMA 중기예보 변환 (PR#52, ADR-010).

본 PR 테스트 범위:
- 중기육상예보(`mid_land_forecast_to_weather_values`): 3~7일 AM/PM fan-out +
  8~10일 단일. SKY 텍스트 + POP.
- 중기기온(`mid_temperature_to_weather_values`): 일자별 TMN/TMX.
- AM/PM 구간이 `valid_from`/`valid_until`, identity 유일성은 `valid_at`.
- None/빈 텍스트 metric 생략.
- forecast_style=mid / timeline_bucket=mid / weather_domain=kma_mid_forecast.
- `tm_fc` 형식 위반 reject.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from krtour.map.dto import ForecastStyle, TimelineBucket, WeatherDomain
from krtour.map.providers.kma import (
    mid_land_forecast_to_weather_values,
    mid_temperature_to_weather_values,
)

KST = timezone(timedelta(hours=9))
_FEATURE_ID = "f_global_w_0123456789abcdef0123"


# -- fixtures -------------------------------------------------------------


@dataclass(frozen=True)
class _Land:
    """``KmaMidLandForecastItem`` Protocol 만족."""

    reg_id: str
    tm_fc: str
    wf_3_am: str | None
    wf_3_pm: str | None
    wf_4_am: str | None
    wf_4_pm: str | None
    wf_5_am: str | None
    wf_5_pm: str | None
    wf_6_am: str | None
    wf_6_pm: str | None
    wf_7_am: str | None
    wf_7_pm: str | None
    wf_8: str | None
    wf_9: str | None
    wf_10: str | None
    rn_st_3_am: int | None
    rn_st_3_pm: int | None
    rn_st_4_am: int | None
    rn_st_4_pm: int | None
    rn_st_5_am: int | None
    rn_st_5_pm: int | None
    rn_st_6_am: int | None
    rn_st_6_pm: int | None
    rn_st_7_am: int | None
    rn_st_7_pm: int | None
    rn_st_8: int | None
    rn_st_9: int | None
    rn_st_10: int | None


@dataclass(frozen=True)
class _Temp:
    """``KmaMidTemperatureItem`` Protocol 만족."""

    reg_id: str
    tm_fc: str
    ta_min_3: int | None
    ta_max_3: int | None
    ta_min_4: int | None
    ta_max_4: int | None
    ta_min_5: int | None
    ta_max_5: int | None
    ta_min_6: int | None
    ta_max_6: int | None
    ta_min_7: int | None
    ta_max_7: int | None
    ta_min_8: int | None
    ta_max_8: int | None
    ta_min_9: int | None
    ta_max_9: int | None
    ta_min_10: int | None
    ta_max_10: int | None


def _full_land(**overrides: object) -> _Land:
    """모든 필드 채운 land fixture (개별 테스트가 override)."""
    base: dict[str, object] = {
        "reg_id": "11B00000",
        "tm_fc": "202605280600",
    }
    for day in (3, 4, 5, 6, 7):
        base[f"wf_{day}_am"] = "맑음"
        base[f"wf_{day}_pm"] = "구름많음"
        base[f"rn_st_{day}_am"] = 20
        base[f"rn_st_{day}_pm"] = 30
    for day in (8, 9, 10):
        base[f"wf_{day}"] = "흐림"
        base[f"rn_st_{day}"] = 40
    base.update(overrides)
    return _Land(**base)  # type: ignore[arg-type]


def _full_temp(**overrides: object) -> _Temp:
    base: dict[str, object] = {"reg_id": "11B10101", "tm_fc": "202605280600"}
    for day in (3, 4, 5, 6, 7, 8, 9, 10):
        base[f"ta_min_{day}"] = 10 + day
        base[f"ta_max_{day}"] = 20 + day
    base.update(overrides)
    return _Temp(**base)  # type: ignore[arg-type]


# -- 중기육상 ------------------------------------------------------------


@pytest.mark.unit
def test_mid_land_fanout_count() -> None:
    """3~7일 AM/PM(10) + 8~10일(3) = 13 period × (SKY + POP) = 26 value."""
    values = mid_land_forecast_to_weather_values(
        [_full_land()], feature_id=_FEATURE_ID
    )
    assert len(values) == 26
    # 모두 mid 축.
    for v in values:
        assert v.weather_domain is WeatherDomain.KMA_MID_FORECAST
        assert v.forecast_style is ForecastStyle.MID
        assert v.timeline_bucket is TimelineBucket.MID


@pytest.mark.unit
def test_mid_land_am_pm_windows() -> None:
    """day3 AM = 발표일+3일 00~12시, PM = 12~24시 (valid_at=구간 시작)."""
    values = mid_land_forecast_to_weather_values(
        [_full_land()], feature_id=_FEATURE_ID
    )
    sky = [v for v in values if v.metric_key == "SKY"]
    # day3 AM SKY: valid_from = 2026-05-31 00:00 KST, valid_until 12:00.
    day3_am = next(
        v for v in sky if v.valid_from == datetime(2026, 5, 31, 0, 0, tzinfo=KST)
    )
    assert day3_am.value_text == "맑음"
    assert day3_am.valid_until == datetime(2026, 5, 31, 12, 0, tzinfo=KST)
    assert day3_am.valid_at == day3_am.valid_from  # identity 유일성
    # day3 PM: 12~24시 → 구름많음.
    day3_pm = next(
        v for v in sky if v.valid_from == datetime(2026, 5, 31, 12, 0, tzinfo=KST)
    )
    assert day3_pm.value_text == "구름많음"
    assert day3_pm.valid_until == datetime(2026, 6, 1, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_mid_land_day8_single_fullday() -> None:
    values = mid_land_forecast_to_weather_values(
        [_full_land()], feature_id=_FEATURE_ID
    )
    # day8 (발표일+8 = 2026-06-05) 종일 SKY.
    day8 = next(
        v
        for v in values
        if v.metric_key == "SKY"
        and v.valid_from == datetime(2026, 6, 5, 0, 0, tzinfo=KST)
    )
    assert day8.value_text == "흐림"
    assert day8.valid_until == datetime(2026, 6, 6, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_mid_land_pop_numeric() -> None:
    values = mid_land_forecast_to_weather_values(
        [_full_land()], feature_id=_FEATURE_ID
    )
    pop = [v for v in values if v.metric_key == "POP"]
    assert all(v.unit == "%" for v in pop)
    day3_am_pop = next(
        v for v in pop if v.valid_from == datetime(2026, 5, 31, 0, 0, tzinfo=KST)
    )
    assert day3_am_pop.value_number == Decimal("20")


@pytest.mark.unit
def test_mid_land_skips_none_and_blank() -> None:
    """None/빈 텍스트 metric은 생략."""
    item = _full_land(wf_3_am=None, rn_st_3_am=None, wf_3_pm="  ")
    values = mid_land_forecast_to_weather_values([item], feature_id=_FEATURE_ID)
    # day3 AM SKY+POP 둘 다 생략, day3 PM SKY(공백) 생략 → 3 value 감소
    # (전체 26 - 2[am sky+pop] - 1[pm sky 공백] = 23). day3 PM POP은 남음.
    assert len(values) == 23


@pytest.mark.unit
def test_mid_land_identity_unique() -> None:
    """fan-out된 값들의 identity()가 모두 유일 (DB UNIQUE 정합)."""
    values = mid_land_forecast_to_weather_values(
        [_full_land()], feature_id=_FEATURE_ID
    )
    identities = [v.identity() for v in values]
    assert len(identities) == len(set(identities))


# -- 중기기온 ------------------------------------------------------------


@pytest.mark.unit
def test_mid_temp_fanout() -> None:
    """3~10일(8) × (TMN + TMX) = 16 value."""
    values = mid_temperature_to_weather_values([_full_temp()], feature_id=_FEATURE_ID)
    assert len(values) == 16
    tmn = [v for v in values if v.metric_key == "TMN"]
    tmx = [v for v in values if v.metric_key == "TMX"]
    assert len(tmn) == 8
    assert len(tmx) == 8
    assert all(v.unit == "deg_c" for v in values)


@pytest.mark.unit
def test_mid_temp_values() -> None:
    values = mid_temperature_to_weather_values([_full_temp()], feature_id=_FEATURE_ID)
    # day3: ta_min=13, ta_max=23 (10+3, 20+3). valid_from = 발표일+3 = 05-31.
    day3_min = next(
        v
        for v in values
        if v.metric_key == "TMN"
        and v.valid_from == datetime(2026, 5, 31, 0, 0, tzinfo=KST)
    )
    assert day3_min.value_number == Decimal("13")


@pytest.mark.unit
def test_mid_temp_skips_none() -> None:
    values = mid_temperature_to_weather_values(
        [_full_temp(ta_min_3=None)], feature_id=_FEATURE_ID
    )
    assert len(values) == 15  # 16 - 1


@pytest.mark.unit
def test_mid_temp_identity_unique() -> None:
    values = mid_temperature_to_weather_values([_full_temp()], feature_id=_FEATURE_ID)
    identities = [v.identity() for v in values]
    assert len(identities) == len(set(identities))


# -- 공통 ----------------------------------------------------------------


@pytest.mark.unit
def test_mid_invalid_tm_fc_rejected() -> None:
    with pytest.raises(ValueError, match="tm_fc"):
        mid_land_forecast_to_weather_values(
            [_full_land(tm_fc="202605280")], feature_id=_FEATURE_ID
        )
