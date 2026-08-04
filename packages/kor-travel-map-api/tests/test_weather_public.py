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
    assert "/v1/admin/features/weather/alerts" in spec["paths"]
    assert not any(path.startswith("/v1/weather") for path in spec["paths"])
    assert "PublicWeatherForecastResponse" in spec["components"]["schemas"]
    assert "PublicWeatherAlertHistoryResponse" in spec["components"]["schemas"]
    assert "AdminWeatherAlertHistoryResponse" in spec["components"]["schemas"]


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
        assert "source_record_key" not in data["items"][0]
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
        # T-VN-32C 리뷰 F2 — 경계 해석 결과의 UUID 정본 병행 노출 (additive).
        from kortravelmap.core.ids import feature_uuid_from_legacy

        assert data["target_feature_uuid"] == str(feature_uuid_from_legacy("f_target"))
        assert data["anchor"]["feature_id"] == "f_w"
        assert data["items"] == []
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_weather_forecast_feature_ref_boundary(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2 회귀 — `/features/{feature_id}/weather/forecast`도 경계 해석 규칙을 탄다.

    종전에는 이 경로만 해석을 건너뛰어 형식 오류·미존재 UUID에도 200 + 빈 timeline을
    돌려줬다(적대 리뷰 실측). 형제 `/features/{id}` 경로들과 같은 규칙이어야 한다:
    형식 오류 422, 미해석 404. (echo-resolver가 형식 검증은 실제로 태운다 —
    conftest 참조. 404는 resolver를 미해석으로 덮어써 검증.)
    """
    import kortravelmap.api.routers.weather as mod

    _fake_session(client)
    try:
        # 형식 오류 → 422 (실제 validate_feature_ref 경로)
        padded = client.get("/v1/features/%20f_pad%20/weather/forecast?limit=1")
        assert padded.status_code == 422
        oversized = client.get(f"/v1/features/{'x' * 257}/weather/forecast?limit=1")
        assert oversized.status_code == 422

        # 미해석 참조 → 404 (resolver 덮어쓰기 — conftest 규약)
        from kortravelmap.infra import feature_identity

        async def _miss(_s: Any, ref: str) -> None:
            feature_identity.validate_feature_ref(ref)

        monkeypatch.setattr(feature_identity, "resolve_feature_identity", _miss)
        missing = client.get(
            "/v1/features/0f9d3c6e-5a41-4b2e-9c77-2b8a1d4e6f30/weather/forecast?limit=1"
        )
        assert missing.status_code == 404

        # anchor repo까지 도달하지 않았음을 함께 고정 — 해석이 첫 관문이다.
        async def _explode(_s: Any, **_kw: Any) -> Any:
            raise AssertionError("미해석 참조가 repo까지 내려왔다")

        monkeypatch.setattr(
            mod.weather_repo, "nearest_weather_feature_for_feature", _explode
        )
        still_missing = client.get("/v1/features/f_gone/weather/forecast?limit=1")
        assert still_missing.status_code == 404
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
        assert item["region_code"] == "11B10101"
        assert item["phenomenon"] == "호우"
        assert {
            "source_record_key",
            "payload",
            "fetched_at",
            "imported_at",
            "last_seen_at",
        }.isdisjoint(item)
        # T-VN-04: 공개 join으로 상수화된 feature_status는 응답에서 제거됐다.
        assert "feature_status" not in item

        admin_response = client.get(
            "/v1/admin/features/weather/alerts?region_code=11B10101"
        )
        assert admin_response.status_code == 200
        admin_item = admin_response.json()["data"]["items"][0]
        assert admin_item["source_record_key"] == "sr_alert"
        assert admin_item["payload"] == {"region_code": "11B10101"}
        assert admin_item["fetched_at"] == issued.isoformat().replace("+00:00", "Z")
    finally:
        client.app.dependency_overrides.clear()
