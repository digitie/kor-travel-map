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


def _parse_sample(line: str) -> tuple[dict[str, str], float | None]:
    """``metric{labels} value`` 한 줄을 (라벨 dict, 값)으로 파싱한다."""
    head, _, raw_value = line.rpartition(" ")
    _, _, label_block = head.partition("{")
    labels: dict[str, str] = {}
    for pair in label_block.rstrip("}").split(","):
        key, sep, val = pair.partition("=")
        if sep:
            labels[key.strip()] = val.strip().strip('"')
    try:
        return labels, float(raw_value)
    except ValueError:
        return labels, None


def _find_http_request(
    body: str, **want: str
) -> tuple[dict[str, str], float | None] | None:
    """``http_requests_total`` 라인 중 want 라벨을 모두 만족하는 첫 sample.

    라벨 순서/포맷·값 누적에 견고하게 라인 단위로 파싱한다(정확-값 비교 대신 라벨 일치).
    ``_total{`` 시작 라인만 골라 ``_total_created`` 파생 라인과 구분한다.
    """
    for line in _metric_lines(body, "kor_travel_map_http_requests_total"):
        labels, value = _parse_sample(line)
        if all(labels.get(key) == val for key, val in want.items()):
            return labels, value
    return None


def _find_request_exception(
    body: str, **want: str
) -> tuple[dict[str, str], float | None] | None:
    """``http_request_exceptions_total`` 라인 중 want 라벨을 모두 만족하는 첫 sample."""
    for line in _metric_lines(body, "kor_travel_map_http_request_exceptions_total"):
        labels, value = _parse_sample(line)
        if all(labels.get(key) == val for key, val in want.items()):
            return labels, value
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
    sample = _find_http_request(
        body, method="GET", status_code="200", surface="system"
    )
    assert sample is not None, _metric_lines(
        body, "kor_travel_map_http_requests_total"
    )
    labels, value = sample
    assert value is not None
    assert value >= 1.0
    # path는 정규 라우트 템플릿이어야 한다(__unmatched__ 아님). ``/health``는 public_status_router가
    # prefix 없이 마운트되므로 정확히 ``/health``로 기록돼야 한다(ADR-048 /v1 clean cut).
    assert labels["path"] == "/health"
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
    sample = _find_http_request(
        body, method="GET", status_code="200", surface="public"
    )
    assert sample is not None, _metric_lines(
        body, "kor_travel_map_http_requests_total"
    )
    labels, value = sample
    assert value is not None
    assert value >= 1.0
    # surface=public인 요청은 /v1/categories뿐. path 라벨은 매칭된 라우트 템플릿
    # ``/categories``로 정확히 기록돼야 한다(__unmatched__ 아님). /v1 prefix는
    # include_router로 적용돼 scope route 템플릿에는 나타나지 않는다(성공 메트릭과 동일).
    assert labels["path"] == "/categories"


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
def test_prometheus_metrics_exception_uses_routed_path_label() -> None:
    """라우팅된 /v1/... 엔드포인트에서 예외가 나면 정규 템플릿 path로 집계해야 한다(#448).

    예외 카운터는 진입 시점의 잠정 path(best-effort, __unmatched__ 가능)가 아니라,
    예외 전파 시점에 채워진 ``scope['route']`` 기준 템플릿 path를 라벨로 써야 한다.
    """
    app = create_app(ApiSettings(features_routes_enabled=False))

    @app.get("/v1/boom/{item_id}")
    async def boom_endpoint(item_id: str) -> dict[str, str]:
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/boom/42")
    assert response.status_code == 500

    body = client.get("/metrics").text
    sample = _find_request_exception(
        body, method="GET", exception_type="RuntimeError"
    )
    assert sample is not None, _metric_lines(
        body, "kor_travel_map_http_request_exceptions_total"
    )
    labels, value = sample
    assert value is not None
    assert value >= 1.0
    # 정규 라우트 템플릿이어야 한다(__unmatched__ 아님). path param은 ``{item_id}``로 보존된다.
    assert labels["path"] == "/v1/boom/{item_id}"


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
