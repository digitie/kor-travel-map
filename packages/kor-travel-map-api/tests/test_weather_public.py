"""``GET /features/*/weather*`` 공개 weather API — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.weather_repo import (
    WeatherAlertHistoryRow,
    WeatherAnchor,
    WeatherValueTimelineRow,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings()))


def _fake_session(client: TestClient) -> None:
    from kortravelmap.api.db import get_session

    async def _fs() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fs


@pytest.mark.unit
def test_weather_public_routes_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/features/weather/forecast" in spec["paths"]
    assert "/v1/features/{feature_id}/weather/forecast" in spec["paths"]
    assert "/v1/features/weather/alerts" in spec["paths"]
    assert not any(path.startswith("/v1/weather") for path in spec["paths"])
    assert "WeatherForecastResponse" in spec["components"]["schemas"]
    assert "WeatherAlertHistoryResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_weather_forecast_coordinate_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kortravelmap.api.routers.weather as mod

    issued = datetime(2026, 7, 9, 6, tzinfo=UTC)
    valid = datetime(2026, 7, 12, 0, tzinfo=UTC)

    async def _anchor(_s: Any, **_kw: Any) -> WeatherAnchor:
        return WeatherAnchor(
            feature_id="f_w",
            name="KMA mid anchor",
            lon=126.98,
            lat=37.56,
            distance_m=1200.0,
        )

    async def _values(_s: Any, **_kw: Any) -> list[WeatherValueTimelineRow]:
        return [
            WeatherValueTimelineRow(
                weather_value_key="wv1",
                feature_id="f_w",
                provider="python-kma-api",
                weather_domain="kma_mid_forecast",
                forecast_style="mid",
                timeline_bucket="mid",
                metric_key="TMX",
                metric_name="최고기온",
                value_number=Decimal("31.5"),
                value_text=None,
                unit="deg_c",
                severity=None,
                issued_at=issued,
                valid_at=valid,
                valid_from=valid,
                valid_until=None,
                observed_at=None,
                collected_at=issued,
                source_record_key="sr1",
            )
        ]

    monkeypatch.setattr(mod.weather_repo, "nearest_weather_feature_for_coordinate", _anchor)
    monkeypatch.setattr(mod.weather_repo, "list_weather_values", _values)
    _fake_session(client)
    try:
        response = client.get(
            "/v1/features/weather/forecast?lon=126.97&lat=37.56&forecast_style=mid"
            "&metric_key=TMX"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["target_lon"] == 126.97
        assert data["anchor"]["feature_id"] == "f_w"
        assert data["items"][0]["weather_domain"] == "kma_mid_forecast"
        assert data["items"][0]["value_number"] == 31.5
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_forecast_feature_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kortravelmap.api.routers.weather as mod

    async def _anchor(_s: Any, **_kw: Any) -> WeatherAnchor:
        return WeatherAnchor(
            feature_id="f_w",
            name="KMA short anchor",
            lon=126.98,
            lat=37.56,
            distance_m=2400.0,
        )

    async def _values(_s: Any, **_kw: Any) -> list[WeatherValueTimelineRow]:
        return []

    monkeypatch.setattr(mod.weather_repo, "nearest_weather_feature_for_feature", _anchor)
    monkeypatch.setattr(mod.weather_repo, "list_weather_values", _values)
    _fake_session(client)
    try:
        response = client.get("/v1/features/f_target/weather/forecast?limit=1")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["target_feature_id"] == "f_target"
        assert data["anchor"]["feature_id"] == "f_w"
        assert data["items"] == []
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_alert_history_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kortravelmap.api.routers.weather as mod

    issued = datetime(2026, 7, 9, 6, tzinfo=UTC)

    async def _alerts(_s: Any, **_kw: Any) -> list[WeatherAlertHistoryRow]:
        return [
            WeatherAlertHistoryRow(
                source_record_key="sr_alert",
                feature_id="f_notice",
                feature_name="호우주의보",
                feature_status="active",
                region_code="11B10101",
                region_name="서울특별시",
                phenomenon="호우",
                alert_type="heavy_rain_warning",
                level="주의보",
                title="호우주의보",
                description="강한 비",
                issued_at=issued,
                effective_from=issued,
                effective_until=None,
                source_agency="기상청",
                fetched_at=issued,
                imported_at=issued,
                last_seen_at=issued,
                payload={"region_code": "11B10101"},
            )
        ]

    monkeypatch.setattr(mod.weather_repo, "list_kma_weather_alert_history", _alerts)
    _fake_session(client)
    try:
        response = client.get("/v1/features/weather/alerts?region_code=11B10101")
        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert item["source_record_key"] == "sr_alert"
        assert item["region_code"] == "11B10101"
        assert item["phenomenon"] == "호우"
    finally:
        client.app.dependency_overrides.clear()
