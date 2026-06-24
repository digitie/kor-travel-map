"""admin FastAPI 공통 error envelope 테스트."""

from __future__ import annotations

from time import perf_counter

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.response import make_meta
from kortravelmap.api.settings import ApiSettings


@pytest.mark.unit
def test_http_exception_uses_error_envelope() -> None:
    app = create_app(ApiSettings())

    @app.get("/boom")
    async def _boom() -> None:
        raise HTTPException(status_code=404, detail="missing row")

    response = TestClient(app).get("/boom", headers={"X-Request-ID": "req-test-1"})

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "req-test-1"
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "https://kor-travel-map/errors/not-found"
    assert body["code"] == "NOT_FOUND"
    assert body["detail"] == "missing row"
    assert body["errors"] == []
    assert body["request_id"] == "req-test-1"


@pytest.mark.unit
def test_request_validation_error_uses_error_envelope() -> None:
    app = create_app(ApiSettings())
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


@pytest.mark.unit
def test_unhandled_exception_uses_problem_json_500() -> None:
    """generic 예외도 RFC7807 problem+json 500으로 통일된다 (#510).

    starlette 기본 핸들러의 ``text/plain`` 500을 막고, 응답 본문에 예외 메시지/
    stack이 새지 않는지 검증한다. ``raise_server_exceptions=False``로 TestClient가
    재-raise하지 않고 실제 핸들러 응답을 받는다.
    """
    app = create_app(ApiSettings())

    @app.get("/explode")
    async def _explode() -> None:
        raise RuntimeError("super secret internal stack detail")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/explode", headers={"X-Request-ID": "req-boom-500"}
    )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["status"] == 500
    assert body["request_id"] == "req-boom-500"
    # 예외 detail/stack은 절대 본문에 노출되지 않는다.
    serialized = response.text
    assert "super secret internal stack detail" not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code"),
    [
        ("/parity-404", 404, "NOT_FOUND"),
        ("/parity-422", 422, "VALIDATION_ERROR"),
        ("/parity-500", 500, "INTERNAL_ERROR"),
    ],
)
def test_error_envelope_parity_across_status_codes(
    path: str, expected_status: int, expected_code: str
) -> None:
    """404/422/500이 동일한 problem+json 형식·확장 멤버를 반환한다 (#510)."""
    app = create_app(ApiSettings())

    @app.get("/parity-404")
    async def _missing() -> None:
        raise HTTPException(status_code=404, detail="없음")

    @app.get("/parity-422")
    async def _unprocessable() -> None:
        raise HTTPException(status_code=422, detail="검증 실패")

    @app.get("/parity-500")
    async def _crash() -> None:
        raise RuntimeError("boom")

    response = TestClient(app, raise_server_exceptions=False).get(
        path, headers={"X-Request-ID": "req-parity"}
    )

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == expected_code
    assert body["status"] == expected_status
    assert body["request_id"] == "req-parity"
    assert "type" in body
    assert "title" in body
    assert body["errors"] == []


@pytest.mark.unit
def test_success_meta_uses_request_context_without_body_rewrite() -> None:
    app = create_app(ApiSettings())

    @app.get("/meta")
    async def _meta() -> dict[str, object]:
        return {
            "data": {"ok": True},
            "meta": make_meta(started_at=perf_counter()).model_dump(),
        }

    response = TestClient(app).get("/meta", headers={"X-Request-ID": "req-meta-1"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-meta-1"
    body = response.json()
    assert body["meta"]["request_id"] == "req-meta-1"


@pytest.mark.unit
def test_request_id_middleware_does_not_rewrite_json_body() -> None:
    app = create_app(ApiSettings())

    @app.get("/raw-meta")
    async def _raw_meta() -> JSONResponse:
        return JSONResponse({"meta": {}})

    response = TestClient(app).get(
        "/raw-meta",
        headers={"X-Request-ID": "req-no-rewrite-1"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-no-rewrite-1"
    assert response.json() == {"meta": {}}
