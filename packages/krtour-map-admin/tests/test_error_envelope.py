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
    body = response.json()
    assert "detail" not in body
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "missing row"
    assert body["error"]["details"] == {}
    assert body["error"]["request_id"] == "req-test-1"


@pytest.mark.unit
def test_request_validation_error_uses_error_envelope() -> None:
    app = create_app(AdminSettings())
    response = TestClient(app).post(
        "/debug/etl/data.go.kr-standard/datagokr_cultural_festivals/preview"
        "?source=bogus"
    )

    assert response.status_code == 422
    body = response.json()
    assert "detail" not in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "요청 값이 올바르지 않습니다."
    assert body["error"]["details"]["errors"]
    assert body["error"]["request_id"]
