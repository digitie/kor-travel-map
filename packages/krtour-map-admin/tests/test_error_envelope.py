"""admin FastAPI 공통 error envelope 테스트."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from krtour.map_admin.app import create_app
from krtour.map_admin.settings import AdminSettings


@pytest.mark.unit
def test_http_exception_uses_error_envelope() -> None:
    app = create_app(AdminSettings())

    @app.get("/boom")
    async def _boom() -> None:
        raise HTTPException(status_code=404, detail="missing row")

    response = TestClient(app).get("/boom", headers={"X-Request-ID": "req-test-1"})

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "req-test-1"
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "https://krtour-map/errors/not-found"
    assert body["code"] == "NOT_FOUND"
    assert body["detail"] == "missing row"
    assert body["errors"] == []
    assert body["request_id"] == "req-test-1"


@pytest.mark.unit
def test_request_validation_error_uses_error_envelope() -> None:
    app = create_app(AdminSettings())
    response = TestClient(app).post(
        "/v1/debug/etl/data.go.kr-standard/datagokr_cultural_festivals/preview"
        "?source=bogus"
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["detail"] == "요청 값이 올바르지 않습니다."
    assert body["errors"]
    assert body["request_id"]
