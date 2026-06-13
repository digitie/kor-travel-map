"""``test_etl_routers`` — ETL preview 라우터 (PR#44)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.etl_fixtures import FIXTURE_REGISTRY
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    app = create_app(ApiSettings())
    return TestClient(app)


def _data(response: Any) -> dict[str, Any]:
    return response.json()["data"]


# ── /debug/etl/providers ───────────────────────────────────────────────


@pytest.mark.unit
def test_providers_returns_registry(client: TestClient) -> None:
    response = client.get("/v1/debug/etl/providers")
    assert response.status_code == 200
    body = _data(response)
    providers = body["providers"]
    # registry에 있는 모든 provider 포함.
    registry_providers = sorted({e.provider for e in FIXTURE_REGISTRY})
    response_providers = sorted(p["provider"] for p in providers)
    assert response_providers == registry_providers


@pytest.mark.unit
def test_providers_includes_kma_datasets(client: TestClient) -> None:
    response = client.get("/v1/debug/etl/providers")
    body = _data(response)
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
    response = client.get("/v1/debug/etl/python-opinet-api/datasets")
    assert response.status_code == 200
    body = _data(response)
    assert body["provider"] == "python-opinet-api"
    dataset_keys = {d["dataset"] for d in body["datasets"]}
    assert "opinet_fuel_station_details" in dataset_keys
    assert "opinet_gas_station_prices" in dataset_keys


@pytest.mark.unit
def test_provider_datasets_unknown_404(client: TestClient) -> None:
    response = client.get("/v1/debug/etl/unknown-provider/datasets")
    assert response.status_code == 404
    body = response.json()
    assert "등록된 provider 아님" in body["detail"]


# ── /debug/etl/{provider}/{dataset}/preview ───────────────────────────


@pytest.mark.unit
def test_preview_datagokr_festival(client: TestClient) -> None:
    response = client.post(
        "/v1/debug/etl/data.go.kr-standard/datagokr_cultural_festivals/preview"
    )
    assert response.status_code == 200
    body = _data(response)
    assert body["provider"] == "data.go.kr-standard"
    assert body["dataset"] == "datagokr_cultural_festivals"
    assert body["source"] == "fixture"
    assert body["variant"] == "FeatureBundle"
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
        "/v1/debug/etl/python-kma-api/kma_short_forecast/preview"
    )
    assert response.status_code == 200
    body = _data(response)
    assert body["variant"] == "WeatherValue"
    assert len(body["items"]) >= 5
    item0 = body["items"][0]
    assert item0["weather_domain"] == "kma_short_forecast"
    assert item0["forecast_style"] == "short"
    assert item0["timeline_bucket"] == "short"


@pytest.mark.unit
def test_preview_kma_nowcast(client: TestClient) -> None:
    response = client.post(
        "/v1/debug/etl/python-kma-api/kma_ultra_short_nowcast/preview"
    )
    body = _data(response)
    assert len(body["items"]) == 5
    assert body["items"][0]["forecast_style"] == "nowcast"
    # nowcast는 observed_at 있고 valid_at 없음.
    assert body["items"][0]["observed_at"] is not None
    assert body["items"][0]["valid_at"] is None


@pytest.mark.unit
def test_preview_opinet_stations(client: TestClient) -> None:
    response = client.post(
        "/v1/debug/etl/python-opinet-api/opinet_fuel_station_details/preview"
    )
    body = _data(response)
    assert body["variant"] == "FeatureBundle"
    assert len(body["items"]) == 2
    item0 = body["items"][0]
    assert item0["feature"]["kind"] == "place"
    assert item0["feature"]["category"] == "06020000"
    assert item0["feature"]["marker_icon"] == "fuel"


@pytest.mark.unit
def test_preview_opinet_prices(client: TestClient) -> None:
    response = client.post(
        "/v1/debug/etl/python-opinet-api/opinet_gas_station_prices/preview"
    )
    body = _data(response)
    assert body["variant"] == "PriceValue"
    assert len(body["items"]) == 3
    item0 = body["items"][0]
    assert item0["price_domain"] == "opinet_gas_station"
    assert item0["unit"] == "KRW/L"


@pytest.mark.unit
def test_preview_airkorea_stations(client: TestClient) -> None:
    response = client.post(
        "/v1/debug/etl/python-airkorea-api/airkorea_stations/preview"
    )
    body = _data(response)
    assert body["variant"] == "FeatureBundle"
    assert len(body["items"]) == 1
    item0 = body["items"][0]
    # 측정소는 weather kind feature (place 아님).
    assert item0["feature"]["kind"] == "weather"
    assert item0["feature"]["category"] == "99000000"


@pytest.mark.unit
def test_preview_airkorea_air_quality(client: TestClient) -> None:
    response = client.post(
        "/v1/debug/etl/python-airkorea-api/airkorea_air_quality/preview"
    )
    body = _data(response)
    assert body["variant"] == "WeatherValue"
    # PM10/PM2_5/O3/CAI 4종(결측 제외).
    assert len(body["items"]) == 4
    metric_keys = {item["metric_key"] for item in body["items"]}
    assert metric_keys == {"PM10", "PM2_5", "O3", "CAI"}
    item0 = body["items"][0]
    assert item0["weather_domain"] == "air_quality"
    assert item0["forecast_style"] == "observed"


@pytest.mark.unit
def test_preview_unknown_dataset_404(client: TestClient) -> None:
    response = client.post(
        "/v1/debug/etl/python-kma-api/unknown_dataset/preview"
    )
    assert response.status_code == 404
    body = response.json()
    assert "등록되지 않은" in body["detail"]


@pytest.mark.unit
def test_preview_live_source_501_when_loader_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fixture엔 있으나 live loader 미등록 dataset → 501 (방어 분기).

    PR#58부터 11/11 fixture dataset이 전부 live 등록되어 실제로는 트리거되지
    않지만, 라우터 501 분기 자체는 유지 — find_live_loader를 None으로
    monkeypatch해 분기를 검증.
    """
    monkeypatch.setattr(
        "kortravelmap.api.routers.etl.find_live_loader",
        lambda *a, **k: None,
    )
    response = client.post(
        "/v1/debug/etl/python-kma-api/kma_weather_alerts/preview?source=live"
    )
    assert response.status_code == 501
    body = response.json()
    assert "source=live 미구현" in body["detail"]


@pytest.mark.unit
def test_preview_live_kma_503_when_key_missing(client: TestClient) -> None:
    """KMA 단기예보는 live 등록됐지만 .env 키 없으면 503."""
    response = client.post(
        "/v1/debug/etl/python-kma-api/kma_short_forecast/preview?source=live"
    )
    assert response.status_code == 503
    body = response.json()
    assert "KMA_SERVICE_KEY 미설정" in body["detail"]


@pytest.mark.unit
def test_providers_dataset_marks_live_supported(client: TestClient) -> None:
    """KMA 4 dataset 전부 live_supported=True (PR#58부터 weather_alerts 포함)."""
    response = client.get("/v1/debug/etl/providers")
    body = _data(response)
    kma = next(p for p in body["providers"] if p["provider"] == "python-kma-api")
    live_map = {d["dataset"]: d["live_supported"] for d in kma["datasets"]}
    assert live_map["kma_short_forecast"] is True
    assert live_map["kma_ultra_short_nowcast"] is True
    assert live_map["kma_ultra_short_forecast"] is True
    # weather_alerts는 PR#58부터 apihub wrn_now_data(구조화 특보구역)로 live 등록.
    assert live_map["kma_weather_alerts"] is True


@pytest.mark.unit
def test_providers_krex_live_supported(client: TestClient) -> None:
    """krex 4 dataset은 PR#55부터 live_supported=True."""
    response = client.get("/v1/debug/etl/providers")
    body = _data(response)
    krex = next(p for p in body["providers"] if p["provider"] == "python-krex-api")
    live_map = {d["dataset"]: d["live_supported"] for d in krex["datasets"]}
    assert live_map["krex_rest_areas"] is True
    assert live_map["krex_rest_area_prices"] is True
    assert live_map["krex_rest_area_weather"] is True
    assert live_map["krex_traffic_notices"] is True


@pytest.mark.unit
def test_preview_live_krex_503_when_key_missing(client: TestClient) -> None:
    """krex는 live 등록됐지만 .env 키 없으면 503."""
    response = client.post(
        "/v1/debug/etl/python-krex-api/krex_rest_areas/preview?source=live"
    )
    assert response.status_code == 503
    body = response.json()
    assert "KREX_SERVICE_KEY 미설정" in body["detail"]


@pytest.mark.unit
def test_providers_opinet_live_supported(client: TestClient) -> None:
    """opinet 2 dataset은 PR#56부터 live_supported=True."""
    response = client.get("/v1/debug/etl/providers")
    body = _data(response)
    op = next(p for p in body["providers"] if p["provider"] == "python-opinet-api")
    live_map = {d["dataset"]: d["live_supported"] for d in op["datasets"]}
    assert live_map["opinet_fuel_station_details"] is True
    assert live_map["opinet_gas_station_prices"] is True


@pytest.mark.unit
def test_preview_live_opinet_503_when_key_missing(client: TestClient) -> None:
    """opinet은 live 등록됐지만 .env 키 없으면 503."""
    response = client.post(
        "/v1/debug/etl/python-opinet-api/opinet_fuel_station_details/preview?source=live"
    )
    assert response.status_code == 503
    body = response.json()
    assert "OPINET_SERVICE_KEY 미설정" in body["detail"]


@pytest.mark.unit
def test_providers_datagokr_live_supported(client: TestClient) -> None:
    """datagokr_cultural_festivals는 PR#57부터 live_supported=True."""
    response = client.get("/v1/debug/etl/providers")
    body = _data(response)
    dg = next(
        p for p in body["providers"] if p["provider"] == "data.go.kr-standard"
    )
    live_map = {d["dataset"]: d["live_supported"] for d in dg["datasets"]}
    assert live_map["datagokr_cultural_festivals"] is True


@pytest.mark.unit
def test_preview_live_datagokr_503_when_key_missing(client: TestClient) -> None:
    """datagokr은 live 등록됐지만 .env 키 없으면 503."""
    response = client.post(
        "/v1/debug/etl/data.go.kr-standard/datagokr_cultural_festivals/preview?source=live"
    )
    assert response.status_code == 503
    body = response.json()
    assert "DATAGOKR_SERVICE_KEY 미설정" in body["detail"]


@pytest.mark.unit
def test_providers_kma_weather_alerts_live_supported(client: TestClient) -> None:
    """kma_weather_alerts는 PR#58부터 live_supported=True (apihub wrn_now_data)."""
    response = client.get("/v1/debug/etl/providers")
    body = _data(response)
    kma = next(p for p in body["providers"] if p["provider"] == "python-kma-api")
    live_map = {d["dataset"]: d["live_supported"] for d in kma["datasets"]}
    assert live_map["kma_weather_alerts"] is True


@pytest.mark.unit
def test_preview_live_kma_alerts_503_when_both_keys_missing(
    client: TestClient,
) -> None:
    """특보현황 live는 data.go.kr serviceKey(primary) 또는 apihub authKey(fallback)
    필요 — 둘 다 미설정 시 503. 두 키 이름 모두 안내 (KMA 소스 정책: data.go.kr 우선).
    """
    response = client.post(
        "/v1/debug/etl/python-kma-api/kma_weather_alerts/preview?source=live"
    )
    assert response.status_code == 503
    body = response.json()
    assert "KMA_APIHUB_KEY 미설정" in body["detail"]
    assert "KMA_SERVICE_KEY" in body["detail"]


@pytest.mark.unit
def test_preview_invalid_source_query_422(client: TestClient) -> None:
    """source는 Literal['fixture', 'live'] — 그 외는 FastAPI validator가 422."""
    response = client.post(
        "/v1/debug/etl/data.go.kr-standard/datagokr_cultural_festivals/preview"
        "?source=bogus"
    )
    assert response.status_code == 422


# ── CORS (frontend 12705 → backend 12701 cross-origin) ────────────────


@pytest.mark.unit
def test_cors_allows_frontend_origin(client: TestClient) -> None:
    """frontend(Next.js dev/start 12705) origin은 CORS 허용 (debug UI 동작 전제)."""
    response = client.get(
        "/v1/debug/etl/providers",
        headers={"Origin": "http://localhost:12705"},
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == "http://localhost:12705"
    )


@pytest.mark.unit
def test_cors_preflight_options(client: TestClient) -> None:
    """preflight OPTIONS도 허용 origin에 대해 200 + allow-origin."""
    response = client.options(
        "/v1/debug/etl/python-kma-api/kma_short_forecast/preview",
        headers={
            "Origin": "http://localhost:12705",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == "http://localhost:12705"
    )


# ── debug_routes_enabled=False 시 unmount ───────────────────────────


@pytest.mark.unit
def test_etl_unmounted_when_debug_disabled() -> None:
    app = create_app(ApiSettings(debug_routes_enabled=False))
    client = TestClient(app)
    assert client.get("/v1/debug/etl/providers").status_code == 404
