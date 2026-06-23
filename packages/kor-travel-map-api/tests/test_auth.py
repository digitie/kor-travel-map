"""앱 레벨 service-token / 파괴적 작업 kill-switch (ADR-045 D-1 B안)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import (
    ADMIN_ACTOR_HEADER,
    ADMIN_PROXY_SECRET_HEADER,
    SERVICE_TOKEN_HEADER,
    require_admin_destructive_enabled,
    require_admin_frontend,
    require_service_token,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings


def _api_settings(**overrides: Any) -> ApiSettings:
    values: dict[str, Any] = {
        "admin_proxy_secret": None,
        "public_api_key_required": False,
        "service_token": None,
        "vworld_api_key": None,
    }
    values.update(overrides)
    return ApiSettings(**values)


def _request(settings: ApiSettings) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


# ── dependency 단위 ──────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_service_token_unset_allows_any() -> None:
    settings = _api_settings(service_token=None)
    # 미설정이면 헤더 유무와 무관하게 통과(raise 없음).
    await require_service_token(_request(settings), token=None)
    await require_service_token(_request(settings), token="anything")


@pytest.mark.unit
async def test_service_token_set_requires_match() -> None:
    settings = _api_settings(service_token=SecretStr("s3cr3t"))
    await require_service_token(_request(settings), token="s3cr3t")  # 일치 → OK
    for bad in (None, "", "wrong"):
        with pytest.raises(HTTPException) as exc:
            await require_service_token(_request(settings), token=bad)
        assert exc.value.status_code == 401


@pytest.mark.unit
def test_admin_destructive_kill_switch() -> None:
    require_admin_destructive_enabled(
        _request(_api_settings(admin_destructive_enabled=True))
    )
    with pytest.raises(HTTPException) as exc:
        require_admin_destructive_enabled(
            _request(_api_settings(admin_destructive_enabled=False))
        )
    assert exc.value.status_code == 403


def test_admin_frontend_gate_requires_proxy_secret_when_configured() -> None:
    settings = _api_settings(admin_proxy_secret=SecretStr("proxy-secret"))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={ADMIN_ACTOR_HEADER: "admin"},
    )
    context = require_admin_frontend(request, proxy_secret="proxy-secret")
    assert context.actor == "admin"

    with pytest.raises(HTTPException) as exc:
        require_admin_frontend(request, proxy_secret=None)
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        require_admin_frontend(request, proxy_secret="wrong")
    assert exc.value.status_code == 403


def test_admin_frontend_gate_keeps_local_dev_compat_when_secret_unset() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=_api_settings())),
        client=SimpleNamespace(host="testclient"),
        headers={},
    )
    assert require_admin_frontend(request).actor == "local-dev"


# ── TestClient 통합 ──────────────────────────────────────────────────────────


class _FakeSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        class _Result:
            def scalars(self) -> Any:
                return self

            def mappings(self) -> Any:
                return self

            def all(self) -> list[Any]:
                return []

        return _Result()

    def begin(self) -> Any:
        class _Tx:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *_e: object) -> None:
                return None

        return _Tx()


def _client(settings: ApiSettings) -> TestClient:
    app = create_app(settings)

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.mark.unit
def test_openapi_declares_service_token_scheme() -> None:
    client = _client(_api_settings(service_token=SecretStr("tok")))
    spec = client.get("/openapi.json").json()
    assert "ServiceToken" in spec["components"]["securitySchemes"]
    scheme = spec["components"]["securitySchemes"]["ServiceToken"]
    assert scheme["in"] == "header"
    assert scheme["name"] == SERVICE_TOKEN_HEADER
    # /features/batch service read는 security 요구, /features 공용 GET read는 없음.
    tri = spec["paths"]["/v1/features/batch"]["post"]
    assert tri.get("security")
    feat = spec["paths"]["/v1/features"]["get"]
    assert not feat.get("security")


@pytest.mark.unit
def test_batch_requires_token_when_set() -> None:
    client = _client(_api_settings(service_token=SecretStr("tok")))
    # 헤더 없음/오류 → 401(핸들러/DB 도달 전 auth 차단).
    assert client.post("/v1/features/batch", json={}).status_code == 401
    assert (
        client.post(
            "/v1/features/batch",
            json={},
            headers={SERVICE_TOKEN_HEADER: "wrong"},
        ).status_code
        == 401
    )


@pytest.mark.unit
def test_batch_token_unset_not_blocked() -> None:
    client = _client(_api_settings(service_token=None))
    # 미설정이면 auth가 막지 않는다(하위호환). 본문/DB 사유로 401은 아니어야 한다.
    assert client.post("/v1/features/batch", json={}).status_code != 401


@pytest.mark.unit
def test_features_not_gated_by_service_token() -> None:
    client = _client(_api_settings(service_token=SecretStr("tok")))
    # 브라우저 admin UI도 쓰는 공용 read surface는 service token으로 막지 않는다.
    assert client.get("/v1/features?limit=1").status_code != 401


@pytest.mark.unit
def test_public_api_key_required_accepts_vworld_fallback() -> None:
    client = _client(
        _api_settings(
            public_api_key_required=True,
            vworld_api_key=SecretStr("vw-test-key"),
        )
    )
    assert client.get("/v1/categories?key=vw-test-key").status_code == 200
    assert client.get("/v1/categories?key=wrong").status_code == 401
    assert client.get("/v1/categories").status_code == 401


@pytest.mark.unit
def test_public_api_key_required_trusts_admin_proxy() -> None:
    client = _client(
        _api_settings(
            admin_proxy_secret=SecretStr("proxy-secret"),
            public_api_key_required=True,
        )
    )
    response = client.get(
        "/v1/categories",
        headers={
            ADMIN_ACTOR_HEADER: "admin",
            ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
        },
    )
    assert response.status_code == 200


@pytest.mark.unit
def test_admin_proxy_secret_deny_and_allow_over_http() -> None:
    client = _client(_api_settings(admin_proxy_secret=SecretStr("proxy-secret")))
    assert client.get("/v1/admin/auth-events").status_code == 403
    assert (
        client.get(
            "/v1/admin/auth-events",
            headers={
                ADMIN_ACTOR_HEADER: "admin",
                ADMIN_PROXY_SECRET_HEADER: "wrong",
            },
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/v1/admin/auth-events",
            headers={
                ADMIN_ACTOR_HEADER: "admin",
                ADMIN_PROXY_SECRET_HEADER: "proxy-secret",
            },
        ).status_code
        == 200
    )


@pytest.mark.unit
def test_destructive_admin_blocked_when_disabled() -> None:
    client = _client(_api_settings(admin_destructive_enabled=False))
    assert (
        client.post(
            "/v1/admin/features/f_x/deactivate", json={"reason": "test"}
        ).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE", "/v1/admin/poi-cache-targets/tripmate/key-1"
        ).status_code
        == 403
    )
