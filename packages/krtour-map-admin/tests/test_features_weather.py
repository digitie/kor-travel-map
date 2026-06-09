"""``GET /features/{feature_id}/weather`` 라우터 (T-213e) — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.weather_repo import WeatherCard, WeatherMetric

from krtour.map_admin.app import create_app
from krtour.map_admin.settings import AdminSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(AdminSettings()))


def _fake_session(client: TestClient) -> None:
    from krtour.map_admin.db import get_session

    async def _fs() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fs


@pytest.mark.unit
def test_weather_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/features/{feature_id}/weather" in spec["paths"]
    assert "FeatureWeatherResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_weather_card_response_maps_metrics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.routers import features as mod

    valid_at = datetime(2026, 6, 6, 3, 0, tzinfo=UTC)
    card = WeatherCard(
        feature_id="f1",
        asof=None,
        source_styles=["short"],
        metrics=[
            WeatherMetric(
                forecast_style="short", metric_key="TMP", metric_name="기온",
                timeline_bucket="short", value_number=Decimal("25.0"), value_text=None,
                unit="deg_c", severity=None, issued_at=None, valid_at=valid_at,
                observed_at=None,
            )
        ],
        latest_at=valid_at,
        is_stale=False,
    )

    async def _card(_s: Any, **_kw: Any) -> WeatherCard:
        return card

    monkeypatch.setattr(mod.weather_repo, "build_weather_card", _card)
    _fake_session(client)
    try:
        r = client.get("/v1/features/f1/weather")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["feature_id"] == "f1"
        assert d["source_styles"] == ["short"]
        assert d["is_stale"] is False
        m = d["metrics"][0]
        assert m["forecast_style"] == "short"
        assert m["metric_key"] == "TMP"
        assert m["value_number"] == 25.0  # Decimal → float
        assert m["unit"] == "deg_c"
    finally:
        client.app.dependency_overrides.clear()
