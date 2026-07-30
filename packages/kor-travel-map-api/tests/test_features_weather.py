"""단건/batch weather 라우터 — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.weather_repo import WeatherBatchItem, WeatherMetric
from sqlalchemy.exc import OperationalError

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
    assert "/v1/features/weather/batch" in spec["paths"]
    assert "FeatureWeatherResponse" in spec["components"]["schemas"]
    assert "WeatherBatchResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_weather_card_response_maps_metrics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    valid_at = datetime(2026, 6, 6, 3, 0, tzinfo=UTC)
    item = WeatherBatchItem(
        feature_id="f1",
        state="found",
        source_styles=["short"],
        current=[
            WeatherMetric(
                forecast_style="short", metric_key="TMP", metric_name="기온",
                timeline_bucket="short", value_number=Decimal("25.0"), value_text=None,
                unit="deg_c", severity=None, issued_at=None, valid_at=valid_at,
                observed_at=None, provider="python-kma-api",
                weather_domain="kma_short_forecast",
            )
        ],
        timeline=[],
        latest_at=valid_at,
        is_stale=False,
    )

    async def _batch(_s: Any, **kw: Any) -> tuple[WeatherBatchItem, ...]:
        assert kw["feature_ids"] == ("f1",)
        assert kw["target_at"] == kw["known_at"]
        return (item,)

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_items", _batch)
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
        assert m["provider"] == "python-kma-api"
        assert m["weather_domain"] == "kma_short_forecast"
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_card_404_when_feature_not_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비공개(draft/broken/inactive/hidden/삭제) parent feature의 weather payload는
    노출되지 않는다 — ADR-067 단일 공개 projection, F-1 (T-VN-04)."""
    from kortravelmap.api.routers import features as mod

    async def _retired(_s: Any, **_kw: Any) -> tuple[WeatherBatchItem, ...]:
        return (
            WeatherBatchItem(
                feature_id="hidden-f",
                state="retired",
                source_styles=[],
                current=[],
                timeline=[],
                latest_at=None,
                is_stale=True,
            ),
        )

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_items", _retired)
    _fake_session(client)
    try:
        r = client.get("/v1/features/hidden-f/weather")
        assert r.status_code == 404
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_batch_maps_found_no_data_retired_and_bitemporal_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    target_at = datetime(2026, 7, 30, 0, tzinfo=UTC)
    known_at = datetime(2026, 7, 29, 12, tzinfo=UTC)
    future_at = datetime(2026, 7, 31, 0, tzinfo=UTC)
    current_metric = WeatherMetric(
        forecast_style="observed",
        metric_key="T1H",
        metric_name="기온",
        timeline_bucket="ultra_short",
        value_number=Decimal("24.5"),
        value_text=None,
        unit="deg_c",
        severity=None,
        issued_at=None,
        valid_at=None,
        observed_at=target_at,
        provider="python-krex-api",
        weather_domain="rest_area_weather",
    )
    timeline_metric = WeatherMetric(
        forecast_style="short",
        metric_key="TMP",
        metric_name="기온",
        timeline_bucket="short",
        value_number=Decimal("27.0"),
        value_text=None,
        unit="deg_c",
        severity=None,
        issued_at=known_at,
        valid_at=future_at,
        observed_at=None,
        provider="python-kma-api",
        weather_domain="kma_short_forecast",
    )

    async def _batch(_s: Any, **kw: Any) -> tuple[WeatherBatchItem, ...]:
        assert kw == {
            "feature_ids": ["found", "no-data", "retired"],
            "target_at": target_at,
            "known_at": known_at,
        }
        return (
            WeatherBatchItem(
                feature_id="found",
                state="found",
                source_styles=["observed", "short"],
                current=[current_metric],
                timeline=[timeline_metric],
                latest_at=target_at,
                is_stale=False,
            ),
            WeatherBatchItem(
                feature_id="no-data",
                state="no_data",
                source_styles=[],
                current=[],
                timeline=[],
                latest_at=None,
                is_stale=True,
            ),
            WeatherBatchItem(
                feature_id="retired",
                state="retired",
                source_styles=[],
                current=[],
                timeline=[],
                latest_at=None,
                is_stale=True,
            ),
        )

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_items", _batch)
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "feature_ids": ["found", "no-data", "retired"],
                "target_at": target_at.isoformat(),
                "known_at": known_at.isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["target_at"] == "2026-07-30T00:00:00Z"
        assert data["known_at"] == "2026-07-29T12:00:00Z"
        assert data["timeline_until"] == "2026-08-09T00:00:00Z"
        assert [item["state"] for item in data["items"]] == [
            "found",
            "no_data",
            "retired",
        ]
        found = data["items"][0]
        assert found["current"][0]["provider"] == "python-krex-api"
        assert found["timeline"][0]["valid_at"] == "2026-07-31T00:00:00Z"
        assert data["items"][1] == {"state": "no_data", "feature_id": "no-data"}
        assert data["items"][2] == {"state": "retired", "feature_id": "retired"}
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        {
            "feature_ids": ["same", "same"],
            "target_at": "2026-07-30T00:00:00Z",
            "known_at": "2026-07-29T00:00:00Z",
        },
        {
            "feature_ids": ["naive"],
            "target_at": "2026-07-30T00:00:00",
            "known_at": "2026-07-29T00:00:00Z",
        },
    ],
)
def test_weather_batch_rejects_ambiguous_request_before_db(
    client: TestClient, body: dict[str, Any]
) -> None:
    response = client.post("/v1/features/weather/batch", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_weather_batch_maps_database_failure_to_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    async def _failed(_s: Any, **_kw: Any) -> None:
        raise OperationalError("weather batch", {}, OSError("database unavailable"))

    monkeypatch.setattr(mod.weather_repo, "get_weather_batch_items", _failed)
    _fake_session(client)
    try:
        response = client.post(
            "/v1/features/weather/batch",
            json={
                "feature_ids": ["f1"],
                "target_at": "2026-07-30T00:00:00Z",
                "known_at": "2026-07-29T00:00:00Z",
            },
        )
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "WEATHER_BATCH_UNAVAILABLE"
    finally:
        client.app.dependency_overrides.clear()
