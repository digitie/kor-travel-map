"""``test_etl_routers`` — ETL preview 라우터 (PR#44)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from krtour.map_debug_ui.app import create_app
from krtour.map_debug_ui.etl_fixtures import FIXTURE_REGISTRY
from krtour.map_debug_ui.settings import DebugUiSettings


@pytest.fixture
def client() -> TestClient:
    app = create_app(DebugUiSettings())
    return TestClient(app)


# ── /debug/etl/providers ───────────────────────────────────────────────


@pytest.mark.unit
def test_providers_returns_registry(client: TestClient) -> None:
    response = client.get("/debug/etl/providers")
    assert response.status_code == 200
    body = response.json()
    providers = body["providers"]
    # registry에 있는 모든 provider 포함.
    registry_providers = sorted({e.provider for e in FIXTURE_REGISTRY})
    response_providers = sorted(p["provider"] for p in providers)
    assert response_providers == registry_providers


@pytest.mark.unit
def test_providers_includes_kma_datasets(client: TestClient) -> None:
    response = client.get("/debug/etl/providers")
    body = response.json()
    kma = next(p for p in body["providers"] if p["provider"] == "python-kma-api")
    dataset_keys = {d["dataset"] for d in kma["datasets"]}
    assert {
        "kma_short_forecast",
        "kma_ultra_short_nowcast",
        "kma_ultra_short_forecast",
    } <= dataset_keys


# ── /debug/etl/{provider}/datasets ─────────────────────────────────────


@pytest.mark.unit
def test_provider_datasets_opinet(client: TestClient) -> None:
    response = client.get("/debug/etl/python-opinet-api/datasets")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "python-opinet-api"
    dataset_keys = {d["dataset"] for d in body["datasets"]}
    assert "opinet_fuel_station_details" in dataset_keys
    assert "opinet_gas_station_prices" in dataset_keys


@pytest.mark.unit
def test_provider_datasets_unknown_404(client: TestClient) -> None:
    response = client.get("/debug/etl/unknown-provider/datasets")
    assert response.status_code == 404
    body = response.json()
    assert "등록된 provider 아님" in body["detail"]


# ── /debug/etl/{provider}/{dataset}/preview ───────────────────────────


@pytest.mark.unit
def test_preview_datagokr_festival(client: TestClient) -> None:
    response = client.post(
        "/debug/etl/data.go.kr-standard/datagokr_cultural_festivals/preview"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "data.go.kr-standard"
    assert body["dataset"] == "datagokr_cultural_festivals"
    assert body["source"] == "fixture"
    assert body["variant"] == "FeatureBundle"
    assert body["count"] == 2
    assert len(body["items"]) == 2
    # 첫 item이 FeatureBundle dict 구조.
    item0 = body["items"][0]
    assert "feature" in item0
    assert "source_record" in item0
    assert "source_link" in item0
    assert item0["feature"]["kind"] == "event"


@pytest.mark.unit
def test_preview_kma_short_forecast(client: TestClient) -> None:
    response = client.post(
        "/debug/etl/python-kma-api/kma_short_forecast/preview"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["variant"] == "WeatherValue"
    assert body["count"] >= 5
    item0 = body["items"][0]
    assert item0["weather_domain"] == "kma_short_forecast"
    assert item0["forecast_style"] == "short"
    assert item0["timeline_bucket"] == "short"


@pytest.mark.unit
def test_preview_kma_nowcast(client: TestClient) -> None:
    response = client.post(
        "/debug/etl/python-kma-api/kma_ultra_short_nowcast/preview"
    )
    body = response.json()
    assert body["count"] == 5
    assert body["items"][0]["forecast_style"] == "nowcast"
    # nowcast는 observed_at 있고 valid_at 없음.
    assert body["items"][0]["observed_at"] is not None
    assert body["items"][0]["valid_at"] is None


@pytest.mark.unit
def test_preview_opinet_stations(client: TestClient) -> None:
    response = client.post(
        "/debug/etl/python-opinet-api/opinet_fuel_station_details/preview"
    )
    body = response.json()
    assert body["variant"] == "FeatureBundle"
    assert body["count"] == 2
    item0 = body["items"][0]
    assert item0["feature"]["kind"] == "place"
    assert item0["feature"]["category"] == "06020000"
    assert item0["feature"]["marker_icon"] == "fuel"


@pytest.mark.unit
def test_preview_opinet_prices(client: TestClient) -> None:
    response = client.post(
        "/debug/etl/python-opinet-api/opinet_gas_station_prices/preview"
    )
    body = response.json()
    assert body["variant"] == "PriceValue"
    assert body["count"] == 3
    item0 = body["items"][0]
    assert item0["price_domain"] == "opinet_gas_station"
    assert item0["unit"] == "KRW/L"


@pytest.mark.unit
def test_preview_unknown_dataset_404(client: TestClient) -> None:
    response = client.post(
        "/debug/etl/python-kma-api/unknown_dataset/preview"
    )
    assert response.status_code == 404
    body = response.json()
    assert "등록되지 않은" in body["detail"]


@pytest.mark.unit
def test_preview_live_source_501_when_not_registered(client: TestClient) -> None:
    """datagokr_cultural_festivals는 LIVE_LOADER_REGISTRY 미등록 — 501."""
    response = client.post(
        "/debug/etl/data.go.kr-standard/datagokr_cultural_festivals/preview"
        "?source=live"
    )
    assert response.status_code == 501
    body = response.json()
    assert "source=live 미구현" in body["detail"]


@pytest.mark.unit
def test_preview_live_kma_503_when_key_missing(client: TestClient) -> None:
    """KMA 단기예보는 live 등록됐지만 .env 키 없으면 503."""
    response = client.post(
        "/debug/etl/python-kma-api/kma_short_forecast/preview?source=live"
    )
    assert response.status_code == 503
    body = response.json()
    assert "KMA_SERVICE_KEY 미설정" in body["detail"]


@pytest.mark.unit
def test_providers_dataset_marks_live_supported(client: TestClient) -> None:
    """KMA 3 dataset은 live_supported=True, 나머지는 False."""
    response = client.get("/debug/etl/providers")
    body = response.json()
    kma = next(p for p in body["providers"] if p["provider"] == "python-kma-api")
    live_map = {d["dataset"]: d["live_supported"] for d in kma["datasets"]}
    assert live_map["kma_short_forecast"] is True
    assert live_map["kma_ultra_short_nowcast"] is True
    assert live_map["kma_ultra_short_forecast"] is True
    # weather_alerts는 live 미등록.
    assert live_map["kma_weather_alerts"] is False


@pytest.mark.unit
def test_preview_invalid_source_query_422(client: TestClient) -> None:
    """source는 Literal['fixture', 'live'] — 그 외는 FastAPI validator가 422."""
    response = client.post(
        "/debug/etl/data.go.kr-standard/datagokr_cultural_festivals/preview"
        "?source=bogus"
    )
    assert response.status_code == 422


# ── debug_routes_enabled=False 시 unmount ───────────────────────────


@pytest.mark.unit
def test_etl_unmounted_when_debug_disabled() -> None:
    app = create_app(DebugUiSettings(debug_routes_enabled=False))
    client = TestClient(app)
    assert client.get("/debug/etl/providers").status_code == 404
