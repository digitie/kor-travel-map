"""Admin frontend→API CORS 회귀."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings()))


@pytest.mark.unit
def test_cors_allows_frontend_origin_on_surviving_read_route(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:12705"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:12705"


@pytest.mark.unit
def test_cors_preflight_allows_canonical_admin_mutation(client: TestClient) -> None:
    response = client.options(
        "/v1/ops/datasets/preview",
        headers={
            "Origin": "http://localhost:12705",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:12705"
