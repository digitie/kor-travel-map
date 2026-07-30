"""surface별 CORS 분리 회귀 (T-VN-H03, ADR-066).

browser-facing public 표면(public-unauthenticated·public-keyed)만 CORS를 받고,
service/operator 표면은 CORS 헤더(``Access-Control-Allow-Origin``)를 내보내지
않는지 검증한다. operator 표면은 admin frontend가 same-origin Next.js BFF
(``/api/proxy``)로만 접근하고, service 표면은 server-to-server라 브라우저
cross-origin이 아니다 — 따라서 CORS 불필요.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.cors import (
    SurfaceScopedCORSMiddleware,
    build_cors_surface_patterns,
)
from kortravelmap.api.route_policy import (
    RoutePolicy,
    RoutePolicyMatrixRow,
)
from kortravelmap.api.settings import ApiSettings

ALLOWED_ORIGIN = "http://localhost:12705"
ARBITRARY_ORIGIN = "https://evil.example.com"
_ACAO = "access-control-allow-origin"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings()))


@pytest.mark.unit
def test_public_unauthenticated_route_gets_cors_for_allowed_origin(
    client: TestClient,
) -> None:
    response = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers[_ACAO] == ALLOWED_ORIGIN


@pytest.mark.unit
def test_public_keyed_preflight_gets_cors_for_allowed_origin(
    client: TestClient,
) -> None:
    # public-keyed read. preflight는 CORSMiddleware가 route/의존 실행 전에 직접
    # 응답하므로 DB 없이도 검증된다.
    response = client.options(
        "/v1/features",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Kor-Travel-Map-Api-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers[_ACAO] == ALLOWED_ORIGIN
    assert "GET" in response.headers["access-control-allow-methods"].split(", ")
    assert (
        "x-kor-travel-map-api-key"
        in response.headers["access-control-allow-headers"].casefold()
    )


@pytest.mark.unit
def test_public_conditional_get_preflight_allows_exact_headers(
    client: TestClient,
) -> None:
    response = client.options(
        "/v1/features/example",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": (
                "X-Kor-Travel-Map-Api-Key, If-None-Match"
            ),
        },
    )

    assert response.status_code == 200
    assert response.headers[_ACAO] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-methods"] == "GET"
    allowed_headers = response.headers["access-control-allow-headers"].casefold()
    assert "x-kor-travel-map-api-key" in allowed_headers
    assert "if-none-match" in allowed_headers


def _synthetic_public_row(
    path: str,
    methods: tuple[str, ...],
) -> RoutePolicyMatrixRow:
    return RoutePolicyMatrixRow(
        path=path,
        schema_path=path,
        methods=methods,
        is_websocket=False,
        include_in_schema=True,
        policy=RoutePolicy.PUBLIC_UNAUTHENTICATED,
        observed_enforcement=(),
    )


@pytest.mark.unit
def test_success_preflight_advertises_only_matching_route_methods() -> None:
    app = FastAPI()
    app.add_middleware(
        SurfaceScopedCORSMiddleware,
        surface_patterns=build_cors_surface_patterns(
            (
                _synthetic_public_row("/read", ("GET",)),
                _synthetic_public_row("/write", ("POST",)),
            )
        ),
        allow_origins=[ALLOWED_ORIGIN],
    )
    synthetic = TestClient(app)

    read = synthetic.options(
        "/read",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    write = synthetic.options(
        "/write",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert read.status_code == 200
    assert read.headers["access-control-allow-methods"] == "GET"
    assert "POST" not in read.headers["access-control-allow-methods"]
    assert write.status_code == 200
    assert write.headers["access-control-allow-methods"] == "POST"
    assert "GET" not in write.headers["access-control-allow-methods"]


@pytest.mark.unit
def test_public_preflight_rejects_route_method_without_acao(
    client: TestClient,
) -> None:
    response = client.options(
        "/v1/features",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 400
    assert _ACAO not in response.headers


@pytest.mark.unit
def test_public_preflight_rejects_private_header_without_acao(
    client: TestClient,
) -> None:
    response = client.options(
        "/v1/features",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Kor-Travel-Map-Admin-Password",
        },
    )

    assert response.status_code == 400
    assert _ACAO not in response.headers


@pytest.mark.unit
def test_public_route_does_not_reflect_arbitrary_origin(client: TestClient) -> None:
    # 설정된 public origin 목록에 없는 origin은 public route라도 ACAO를 받지 못한다.
    response = client.get("/health", headers={"Origin": ARBITRARY_ORIGIN})

    assert response.status_code == 200
    assert _ACAO not in response.headers


@pytest.mark.unit
def test_operator_route_gets_no_cors_for_allowed_origin(client: TestClient) -> None:
    # admin BFF surface(operator) — same-origin proxy로만 접근하므로 브라우저
    # cross-origin이 아니다. 설정된 public origin이라도 CORS를 광고하지 않는다.
    response = client.options(
        "/v1/ops/datasets/preview",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert _ACAO not in response.headers


@pytest.mark.unit
def test_operator_route_does_not_broadly_allow_arbitrary_origin(
    client: TestClient,
) -> None:
    response = client.options(
        "/v1/ops/datasets/preview",
        headers={
            "Origin": ARBITRARY_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.headers.get(_ACAO) != "*"
    assert _ACAO not in response.headers


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    ["/v1/features/batch", "/v1/features/weather/batch"],
)
def test_service_route_gets_no_cors(client: TestClient, path: str) -> None:
    # service surface(X-Kor-Travel-Map-Service-Token) —
    # server-to-server라 브라우저 cross-origin이 아니다. CORS 헤더를 내보내지 않는다.
    response = client.options(
        path,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert _ACAO not in response.headers
