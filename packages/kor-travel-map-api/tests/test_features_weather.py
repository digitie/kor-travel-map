"""``GET /features/{feature_id}/weather`` 라우터 (T-213e) — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.weather_repo import WeatherCard, WeatherMetric

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
def test_weather_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/features/{feature_id}/weather" in spec["paths"]
    assert "FeatureWeatherResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_weather_card_response_maps_metrics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

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

    async def _public_row(_s: Any, feature_id: str) -> dict[str, Any]:
        assert feature_id == "f1"
        return {"feature_id": "f1", "kind": "place", "status": "active"}

    monkeypatch.setattr(mod.weather_repo, "build_weather_card", _card)
    monkeypatch.setattr(mod.feature_repo, "get_public_feature_row", _public_row)
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


@pytest.mark.unit
def test_weather_card_404_when_feature_not_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비공개(draft/broken/inactive/hidden/삭제) parent feature의 weather payload는
    노출되지 않는다 — ADR-067 단일 공개 projection, F-1 (T-VN-04)."""
    from kortravelmap.api.routers import features as mod

    async def _none(_s: Any, _fid: str) -> None:
        return None

    async def _card_should_not_run(_s: Any, **_kw: Any) -> Any:
        raise AssertionError("build_weather_card must not run for non-public feature")

    monkeypatch.setattr(mod.feature_repo, "get_public_feature_row", _none)
    monkeypatch.setattr(mod.weather_repo, "build_weather_card", _card_should_not_run)
    _fake_session(client)
    try:
        r = client.get("/v1/features/hidden-f/weather")
        assert r.status_code == 404
    finally:
        client.app.dependency_overrides.clear()
