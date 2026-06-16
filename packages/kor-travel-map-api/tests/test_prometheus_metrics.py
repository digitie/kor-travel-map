"""Prometheus metrics endpoint tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


def _metric_lines(body: str, metric: str) -> list[str]:
    """Exposition 본문에서 ``metric{`` 으로 시작하는 sample 라인만 추린다.

    ``metric{`` 직후로 앵커해 ``metric_created``/``metric_bucket`` 같은 파생 라인과 구분한다.
    실패 시 진단 메시지로도 쓴다(어떤 라벨 조합이 실제로 기록됐는지 노출).
    """
    prefix = metric + "{"
    return [line for line in body.splitlines() if line.startswith(prefix)]


def _http_requests_total(body: str, **labels: str) -> float | None:
    """``kor_travel_map_http_requests_total`` sample 값을 라벨 순서 무관하게 파싱(없으면 None).

    단일 요청이면 값은 1.0이지만, pytest random-order 실행에서 prometheus counter 값이
    누적돼 정확-값 비교가 flaky했다(라벨/기록 자체는 정상). 라벨 집합 일치 + 값 양수로
    검증해 결정적으로 만든다. exposition 라벨 순서/포맷에 의존하지 않도록 라인 안에서
    ``key="value"`` 조각을 부분일치로 모두 찾는 방식이다.
    """
    for line in _metric_lines(body, "kor_travel_map_http_requests_total"):
        head, _, raw_value = line.rpartition(" ")
        if all(f'{key}="{val}"' in head for key, val in labels.items()):
            try:
                return float(raw_value)
            except ValueError:
                return None
    return None


@pytest.mark.unit
def test_prometheus_metrics_endpoint_records_http_request() -> None:
    app = create_app(ApiSettings(features_routes_enabled=False))
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    body = metrics.text
    assert "kor_travel_map_app_info" in body
    health_total = _http_requests_total(
        body, method="GET", path="/health", status_code="200", surface="system"
    )
    assert health_total is not None, _metric_lines(
        body, "kor_travel_map_http_requests_total"
    )
    assert health_total >= 1.0
    assert "kor_travel_map_http_request_duration_seconds_bucket" in body
    assert "kor_travel_map_http_response_size_bytes_bucket" in body
    assert 'path="/metrics"' not in body


@pytest.mark.unit
def test_prometheus_metrics_records_public_rest_surface() -> None:
    app = create_app(
        ApiSettings(
            admin_routes_enabled=False,
            debug_routes_enabled=False,
            ops_routes_enabled=False,
        )
    )
    client = TestClient(app)

    response = client.get("/v1/categories")
    assert response.status_code == 200

    body = client.get("/metrics").text
    categories_total = _http_requests_total(
        body, method="GET", path="/v1/categories", status_code="200", surface="public"
    )
    assert categories_total is not None, _metric_lines(
        body, "kor_travel_map_http_requests_total"
    )
    assert categories_total >= 1.0


@pytest.mark.unit
def test_prometheus_metrics_uses_unmatched_label_for_404() -> None:
    app = create_app(ApiSettings(features_routes_enabled=False))
    client = TestClient(app)

    response = client.get("/missing/path")
    assert response.status_code == 404

    body = client.get("/metrics").text
    assert (
        'kor_travel_map_http_requests_total{method="GET",'
        'path="__unmatched__",status_code="404",surface="other"} 1.0'
    ) in body


@pytest.mark.unit
def test_prometheus_metrics_records_db_query_metrics() -> None:
    app = create_app(ApiSettings(features_routes_enabled=False))
    metrics = app.state.prometheus_metrics

    metrics.observe_db_query(
        statement="SELECT 1",
        duration_seconds=0.002,
        status="ok",
    )

    body = TestClient(app).get("/metrics").text
    assert (
        'kor_travel_map_db_queries_total{operation="select",path="__unknown__",'
        'status="ok",surface="unknown"} 1.0'
    ) in body
    assert "kor_travel_map_db_query_duration_seconds_bucket" in body


@pytest.mark.unit
def test_prometheus_metrics_records_db_query_with_request_labels() -> None:
    app = create_app(ApiSettings(features_routes_enabled=False))
    metrics = app.state.prometheus_metrics

    @app.get("/probe-db")
    async def probe_db_query_metric() -> dict[str, bool]:
        metrics.observe_db_query(
            statement="UPDATE feature.features SET updated_at = updated_at",
            duration_seconds=0.004,
            status="ok",
        )
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/probe-db")
    assert response.status_code == 200

    body = client.get("/metrics").text
    assert (
        'kor_travel_map_db_queries_total{operation="update",path="/probe-db",'
        'status="ok",surface="other"} 1.0'
    ) in body


@pytest.mark.unit
def test_prometheus_metrics_can_be_disabled() -> None:
    app = create_app(
        ApiSettings(
            features_routes_enabled=False,
            prometheus_metrics_enabled=False,
        )
    )
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 404
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]
