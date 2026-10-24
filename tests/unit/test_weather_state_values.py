"""ADR-114 2단계 — weather export 파서와 Valkey 상태 값 변환(Valkey·HTTP 없이).

골든 ``tests/unit/golden/kor-travel-weather/{current,daily-summaries}.json``은 weather 저장소가
격리 PostgreSQL + 실제 uvicorn HTTP에서 받은 W2·W5 시험 응답 원문이다(weather
``docs/examples/map-service/``, 제품 소스 ``10b69156``). 위치·예보 응답은 weather OpenAPI
(main ``7aa7e70``) 모양대로 여기서 만든다.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.core.ids import make_feature_id
from kortravelmap.dto.weather_state import (
    WeatherCurrentState,
    WeatherDailySummaryState,
    WeatherForecastState,
    WeatherLocationState,
)
from kortravelmap.providers.kor_travel_weather import (
    WeatherExportContractError,
    parse_current_page,
    parse_daily_summary_page,
    parse_forecast_page,
    parse_location_page,
)
from kortravelmap.providers.kor_travel_weather_state import (
    DATASET_FORECAST_EXTERNAL,
    WEATHER_STATE_DATASETS,
    CurrentGrouper,
    DailySummaryGrouper,
    ForecastGrouper,
    earliest_or_none,
    location_state,
    location_state_items,
    weather_location_feature_id,
)

pytestmark = pytest.mark.unit

GOLDEN = Path(__file__).resolve().parent / "golden" / "kor-travel-weather"
NOW = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)


def _golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def _meta(count: int, **overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "generated_at": NOW.isoformat(),
        "source_collected_at": (NOW - timedelta(minutes=7)).isoformat(),
        "source_status": "ok",
        "item_count": count,
        "snapshot_id": "snap-1",
        "snapshot_generated_at": NOW.isoformat(),
        "as_of": NOW.isoformat(),
        "next_cursor": None,
        "has_more": False,
        "next_since": None,
    }
    meta.update(overrides)
    return meta


def _location(location_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "location_id": location_id,
        "name": f"위치 {location_id}",
        "latitude": 37.5665,
        "longitude": 126.978,
        "legal_dong_code": "1111010100",
        "sido_name": "서울특별시",
        "sigungu_name": "종로구",
    }
    row.update(overrides)
    return row


def _group(location_id: str, provider: str = "python-kma-api", **overrides: Any) -> dict[str, Any]:
    targets = [NOW + timedelta(hours=h) for h in (1, 2, 3)]
    row: dict[str, Any] = {
        "location_id": location_id,
        "provider": provider,
        "forecast_style": "short",
        "known_at": (NOW - timedelta(hours=1)).isoformat(),
        "published_at": (NOW - timedelta(minutes=50)).isoformat(),
        "target_at": [t.isoformat() for t in targets],
        "metrics": {"TMP": [12.0, 13.5, None], "SKY": ["맑음", "구름많음", "흐림"]},
    }
    row.update(overrides)
    return row


# -- 파서 ------------------------------------------------------------------------------


def test_golden_current_page_parses_and_groups_per_location() -> None:
    page = parse_current_page(_golden("current.json"))
    assert page.meta.source_status == "ok"
    assert len(page.items) == page.meta.item_count == 44
    grouper = CurrentGrouper()
    for row in page.items:
        grouper.add(row)
    items = grouper.items()
    locations = {row.location_id for row in page.items}
    assert len(items) == len(locations)
    assert grouper.duplicates == 0
    values = [WeatherCurrentState.model_validate_json(item.value) for item in items]
    assert sum(len(v.observations) for v in values) == 44
    assert all(item.coord is None for item in items)  # GEO는 위치 데이터셋 하나뿐이다
    assert {v.feature_id for v in values} == {
        weather_location_feature_id(location_id) for location_id in locations
    }


def test_golden_daily_page_parses_and_keeps_empty_slots_as_null() -> None:
    page = parse_daily_summary_page(_golden("daily-summaries.json"))
    assert page.meta.has_more is True
    assert page.meta.next_cursor
    grouper = DailySummaryGrouper()
    for row in page.items:
        grouper.add(row)
    (item,) = grouper.items()
    summary = WeatherDailySummaryState.model_validate_json(item.value)
    assert [(s.date, s.slot) for s in summary.slots] == [
        (date(2026, 10, 22), "morning"),
        (date(2026, 10, 22), "noon"),
    ]
    assert summary.slots[0].temp_avg is None
    assert summary.slots[0].sample_count == 0


def test_unknown_fields_are_ignored_but_missing_fields_fail() -> None:
    body = {"items": [_location("a", extra_field="new")], "meta": _meta(1, extra=True)}
    assert parse_location_page(body).items[0].location_id == "a"
    broken = {"items": [{"location_id": "a"}], "meta": _meta(1)}
    with pytest.raises(WeatherExportContractError):
        parse_location_page(broken)


@pytest.mark.parametrize(
    "meta",
    [
        _meta(2),  # item_count 불일치
        _meta(1, source_status="failed"),  # failed는 503으로 온다 — 200 본문이면 계약 위반
        _meta(1, has_more=True, next_cursor=None),
        _meta(1, generated_at="2026-10-24T03:00:00"),  # timezone 없음
    ],
)
def test_page_meta_contract_violations(meta: dict[str, Any]) -> None:
    with pytest.raises(WeatherExportContractError):
        parse_location_page({"items": [_location("a")], "meta": meta})


@pytest.mark.parametrize(
    "group",
    [
        _group("a", metrics={"TMP": [1.0, 2.0]}),  # 배열 길이
        _group("a", forecast_style="mid"),  # 요청 style과 다름
        _group(
            "a",
            target_at=[(NOW + timedelta(hours=h)).isoformat() for h in (2, 1)],
            metrics={"TMP": [1.0, 2.0]},
        ),  # 오름차순 아님
    ],
)
def test_forecast_group_contract_violations(group: dict[str, Any]) -> None:
    with pytest.raises(WeatherExportContractError):
        parse_forecast_page({"items": [group], "meta": _meta(1)}, style="short")


def test_body_that_is_not_an_object_is_a_contract_error() -> None:
    with pytest.raises(WeatherExportContractError):
        parse_current_page([1, 2])


# -- 값 --------------------------------------------------------------------------------


def test_location_id_matches_make_feature_id_with_global_bjd() -> None:
    expected = make_feature_id(
        bjd_code=None,
        kind="weather",
        category="99000000",
        source_type="kor-travel-weather:locations",
        source_natural_key="loc-1",
    )
    assert weather_location_feature_id("loc-1") == expected
    assert expected.startswith("f_global_w_")


def test_location_bjd_is_taken_as_is_but_not_part_of_the_id() -> None:
    page = parse_location_page(
        {
            "items": [
                _location("a"),
                _location("a2", legal_dong_code="2611010100"),
            ],
            "meta": _meta(2),
        }
    )
    first = location_state(page.items[0])
    assert first.address.bjd_code == "1111010100"
    assert first.feature_id == weather_location_feature_id("a")
    moved = location_state(page.items[0].model_copy(update={"legal_dong_code": "2611010100"}))
    assert moved.feature_id == first.feature_id


def test_out_of_range_coordinates_are_dropped_not_fatal() -> None:
    page = parse_location_page(
        {
            "items": [
                _location("sea", latitude=0.0, longitude=0.0),
                _location("far", latitude=10.0, longitude=127.0),
                _location("none", latitude=None, longitude=None),
                _location("ok"),
            ],
            "meta": _meta(4),
        }
    )
    items = location_state_items(page.items)
    assert [item.coord is not None for item in items] == [False, False, False, True]
    assert WeatherLocationState.model_validate_json(items[3].value).coord is not None


def test_groupers_keep_the_first_row_and_count_duplicates() -> None:
    page = parse_forecast_page(
        {
            "items": [
                _group("a"),
                _group("a", metrics={"TMP": [0.0, 0.0, 0.0]}),
                _group("a", provider="open_meteo"),
                _group("b"),
            ],
            "meta": _meta(4),
        },
        style="short",
    )
    grouper = ForecastGrouper(style="short")
    for group in page.items:
        grouper.add(group)
    assert grouper.duplicates == 1
    values = {
        state.location_id: state
        for state in (WeatherForecastState.model_validate_json(i.value) for i in grouper.items())
    }
    assert [g.provider for g in values["a"].groups] == ["python-kma-api", "open_meteo"]
    assert values["a"].groups[0].metrics["TMP"] == [12.0, 13.5, None]
    assert values["a"].groups[0].metrics["SKY"] == ["맑음", "구름많음", "흐림"]


def test_daily_grouper_sorts_by_date_then_slot() -> None:
    rows = []
    for day, slot in [(23, "evening"), (22, "noon"), (23, "morning"), (22, "morning")]:
        rows.append(
            {
                "location_id": "a",
                "date": f"2026-10-{day}",
                "slot": slot,
                "temp_min": 1.0,
                "temp_max": 2.0,
                "temp_avg": 1.5,
                "humidity_avg": 60.0,
                "precip_sum_mm": 0.0,
                "precip_occurred": False,
                "sky_code": 1,
                "wind_speed_avg": 2.0,
                "sample_count": 6,
                "source_providers": ["python-kma-api"],
                "partial": False,
            }
        )
    rows.append({**rows[0]})
    page = parse_daily_summary_page({"items": rows, "meta": _meta(len(rows))})
    grouper = DailySummaryGrouper()
    for row in page.items:
        grouper.add(row)
    (item,) = grouper.items()
    summary = WeatherDailySummaryState.model_validate_json(item.value)
    assert [(s.date.day, s.slot) for s in summary.slots] == [
        (22, "morning"),
        (22, "noon"),
        (23, "morning"),
        (23, "evening"),
    ]
    assert grouper.duplicates == 1


def test_earliest_source_collected_at_is_null_if_any_page_is_null() -> None:
    a = NOW - timedelta(minutes=3)
    b = NOW - timedelta(minutes=9)
    assert earliest_or_none([a, b]) == b
    assert earliest_or_none([a, None, b]) is None
    assert earliest_or_none([]) is None


def test_dataset_table_is_unique_and_only_external_may_be_empty() -> None:
    names = [dataset.name for dataset in WEATHER_STATE_DATASETS]
    assert len(names) == len(set(names)) == 7
    assert all(name.startswith("weather.") and ":" not in name for name in names)
    empties = [d.name for d in WEATHER_STATE_DATASETS if d.guard.allow_empty_below_baseline]
    assert empties == [DATASET_FORECAST_EXTERNAL.name]
    styles = {d.style for d in WEATHER_STATE_DATASETS if d.style is not None}
    assert styles == {"ultra_short", "short", "mid", "external"}


def test_location_items_carry_the_weather_location_id_as_lookup_key() -> None:
    page = parse_location_page({"items": [_location("loc-9")], "meta": _meta(1)})
    (item,) = location_state_items(page.items)
    assert item.lookup_keys == ("loc-9",)
    assert item.id == weather_location_feature_id("loc-9")


@pytest.mark.parametrize("location_id", ["a|b", "tab\there", "", "nul\x00x"])
def test_location_ids_make_feature_id_cannot_take_are_contract_errors(location_id: str) -> None:
    with pytest.raises(WeatherExportContractError):
        parse_location_page({"items": [_location(location_id)], "meta": _meta(1)})
    with pytest.raises(WeatherExportContractError):
        parse_forecast_page({"items": [_group(location_id)], "meta": _meta(1)}, style="short")


def test_location_roster_does_not_report_source_status() -> None:
    from kortravelmap.providers.kor_travel_weather_state import DATASET_LOCATIONS

    assert DATASET_LOCATIONS.reports_source_status is False
    assert all(d.reports_source_status for d in WEATHER_STATE_DATASETS if d is not DATASET_LOCATIONS)
