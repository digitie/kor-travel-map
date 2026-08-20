"""admin FastAPI 공통 error envelope 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from kortravelmap.core.exceptions import GeoAuthNotConfiguredError, GeoRequestError
from kortravelmap.geocoding import KorTravelGeoRestClient
from kortravelmap.infra.domain_command_repo import (
    DomainCommandClaim,
    DomainCommandRecord,
)
from pydantic import SecretStr

from kortravelmap.api.app import create_app
from kortravelmap.api.domain_command_service import (
    DomainCommandFingerprintConflict,
    DomainCommandPending,
    DomainCommandReplay,
)
from kortravelmap.api.feature_update_http import to_http_exception
from kortravelmap.api.feature_update_service import (
    FeatureUpdateResolverError,
    FeatureUpdateServiceError,
    SigunguResolverUnavailable,
)
from kortravelmap.api.response import make_meta
from kortravelmap.api.settings import ApiSettings


def _domain_claim() -> DomainCommandClaim:
    return DomainCommandClaim(
        command_id=1,
        actor="admin:alice",
        operation="admin.feature.create",
        idempotency_key="95000000-0000-4000-8000-000000000001",
        fingerprint_version=1,
        request_fingerprint="a" * 64,
        created_at=datetime(2026, 7, 31, tzinfo=UTC),
    )


def _domain_record() -> DomainCommandRecord:
    claim = _domain_claim()
    return DomainCommandRecord(
        command_id=claim.command_id,
        actor=claim.actor,
        operation=claim.operation,
        idempotency_key=claim.idempotency_key,
        fingerprint_version=claim.fingerprint_version,
        request_fingerprint=claim.request_fingerprint,
        response_status=201,
        response_body={
            "data": {"feature_id": "feature-1"},
            "meta": {"duration_ms": 3, "request_id": "request-original"},
        },
        response_headers={"Location": "/v1/admin/features/feature-1"},
        claimed_at=claim.created_at,
        completed_at=claim.created_at,
    )


@pytest.mark.unit
def test_domain_command_terminal_result_replays_exact_response() -> None:
    app = create_app(ApiSettings())

    @app.post("/domain-replay")
    async def _domain_replay() -> None:
        raise DomainCommandReplay(_domain_record())

    response = TestClient(app).post(
        "/domain-replay",
        headers={"X-Request-ID": "request-retry"},
    )

    assert response.status_code == 201
    assert response.headers["idempotency-replayed"] == "true"
    assert response.headers["x-request-id"] == "request-original"
    assert response.headers["location"] == "/v1/admin/features/feature-1"
    assert response.json() == _domain_record().response_body


@pytest.mark.unit
def test_domain_command_problem_result_replays_its_stored_media_type() -> None:
    app = create_app(ApiSettings())
    record = replace(
        _domain_record(),
        response_status=409,
        response_body={
            "type": "https://kor-travel-map/errors/subscription-exists",
            "title": "subscription이 이미 있습니다.",
            "status": 409,
            "detail": "기존 immutable cursor를 유지합니다.",
            "code": "FEATURE_REFERENCE_RECONCILIATION_SUBSCRIPTION_EXISTS",
            "errors": [],
        },
        response_headers={"Content-Type": "application/problem+json"},
    )

    @app.post("/domain-problem-replay")
    async def _domain_problem_replay() -> None:
        raise DomainCommandReplay(record)

    response = TestClient(app).post("/domain-problem-replay")

    assert response.status_code == 409
    assert response.headers["idempotency-replayed"] == "true"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == record.response_body


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected_code", "retry_after"),
    [
        (
            DomainCommandFingerprintConflict(_domain_claim()),
            "IDEMPOTENCY_KEY_REUSED",
            None,
        ),
        (DomainCommandPending(_domain_claim()), "IDEMPOTENCY_RESULT_PENDING", "5"),
    ],
)
def test_domain_command_claim_errors_use_typed_problem(
    error: Exception,
    expected_code: str,
    retry_after: str | None,
) -> None:
    app = create_app(ApiSettings())

    @app.post("/domain-command-error")
    async def _domain_command_error() -> None:
        raise error

    response = TestClient(app).post(
        "/domain-command-error",
        headers={"X-Request-ID": "request-domain-error"},
    )

    assert response.status_code == 409
    assert response.headers.get("retry-after") == retry_after
    assert response.json()["code"] == expected_code
    assert response.json()["request_id"] == "request-domain-error"


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
        "/v1/ops/datasets/42/preview?sync_scope=dataset_wide",
        json={"source": "live", "max_items": 20},
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
    ("error", "expected_status", "expected_code"),
    [
        (
            GeoAuthNotConfiguredError("geo trusted proxy 인증 미설정"),
            503,
            "GEO_AUTH_NOT_CONFIGURED",
        ),
        (
            GeoRequestError("kor-travel-geo 호출 실패"),
            502,
            "PROVIDER_ERROR",
        ),
    ],
)
def test_typed_geo_errors_keep_exact_problem_code(
    error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    app = create_app(ApiSettings())

    @app.get("/geo-error")
    async def _geo_error() -> None:
        raise error

    response = TestClient(app, raise_server_exceptions=False).get(
        "/geo-error",
        headers={"X-Request-ID": "req-geo-error"},
    )

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": f"https://kor-travel-map/errors/{expected_code.lower().replace('_', '-')}",
        "title": str(error),
        "status": expected_status,
        "detail": str(error),
        "code": expected_code,
        "request_id": "req-geo-error",
        "errors": [],
    }


@pytest.mark.unit
def test_geo_problem_envelope_does_not_reflect_provider_base_url_secrets() -> None:
    """공통 502 handler까지 통과해도 provider URL의 userinfo/path는 노출되지 않는다."""
    app = create_app(ApiSettings())
    secret_user = "alice"
    secret_password = "base-password"
    secret_path = "private-token"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"status": "ERROR"})

    @app.get("/geo-sanitized-error")
    async def _geo_sanitized_error() -> None:
        async with httpx.AsyncClient(
            base_url=(
                f"http://{secret_user}:{secret_password}@geo.test/{secret_path}"
            ),
            transport=httpx.MockTransport(handler),
        ) as http:
            client = KorTravelGeoRestClient(
                http,
                api_key=SecretStr("configured-public-key"),
            )
            await client.reverse(127.0276, 37.4979)

    response = TestClient(app, raise_server_exceptions=False).get(
        "/geo-sanitized-error",
        headers={"X-Request-ID": "req-geo-sanitized"},
    )

    assert response.status_code == 502
    assert response.json()["code"] == "PROVIDER_ERROR"
    assert secret_user not in response.text
    assert secret_password not in response.text
    assert secret_path not in response.text
    assert "geo.test" not in response.text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (
            SigunguResolverUnavailable("geo trusted proxy 인증 미설정"),
            503,
            "GEO_AUTH_NOT_CONFIGURED",
        ),
        (
            FeatureUpdateResolverError("kor-travel-geo 호출 실패"),
            502,
            "PROVIDER_ERROR",
        ),
    ],
)
def test_feature_update_geo_adapter_keeps_typed_problem_code(
    error: FeatureUpdateServiceError,
    expected_status: int,
    expected_code: str,
) -> None:
    app = create_app(ApiSettings())

    @app.get("/feature-update-geo-error")
    async def _feature_update_geo_error() -> None:
        raise to_http_exception(error)

    response = TestClient(app).get("/feature-update-geo-error")

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code


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
