"""앱 레벨 service-token / 파괴적 작업 kill-switch (ADR-045 D-1 B안)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from krtour.map_admin.app import create_app
from krtour.map_admin.auth import (
    SERVICE_TOKEN_HEADER,
    require_admin_destructive_enabled,
    require_service_token,
)
from krtour.map_admin.db import get_session
from krtour.map_admin.settings import AdminSettings


def _request(settings: AdminSettings) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


# ── dependency 단위 ──────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_service_token_unset_allows_any() -> None:
    settings = AdminSettings(service_token=None)
    # 미설정이면 헤더 유무와 무관하게 통과(raise 없음).
    await require_service_token(_request(settings), token=None)
    await require_service_token(_request(settings), token="anything")


@pytest.mark.unit
async def test_service_token_set_requires_match() -> None:
    settings = AdminSettings(service_token=SecretStr("s3cr3t"))
    await require_service_token(_request(settings), token="s3cr3t")  # 일치 → OK
    for bad in (None, "", "wrong"):
        with pytest.raises(HTTPException) as exc:
            await require_service_token(_request(settings), token=bad)
        assert exc.value.status_code == 401


@pytest.mark.unit
def test_admin_destructive_kill_switch() -> None:
    require_admin_destructive_enabled(_request(AdminSettings(admin_destructive_enabled=True)))
    with pytest.raises(HTTPException) as exc:
        require_admin_destructive_enabled(
            _request(AdminSettings(admin_destructive_enabled=False))
        )
    assert exc.value.status_code == 403


# ── TestClient 통합 ──────────────────────────────────────────────────────────


class _FakeSession:
    def begin(self) -> Any:
        class _Tx:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *_e: object) -> None:
                return None

        return _Tx()


def _client(settings: AdminSettings) -> TestClient:
    app = create_app(settings)

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


@pytest.mark.unit
def test_openapi_declares_service_token_scheme() -> None:
    client = _client(AdminSettings(service_token=SecretStr("tok")))
    spec = client.get("/openapi.json").json()
    assert "ServiceToken" in spec["components"]["securitySchemes"]
    scheme = spec["components"]["securitySchemes"]["ServiceToken"]
    assert scheme["in"] == "header"
    assert scheme["name"] == SERVICE_TOKEN_HEADER
    # /tripmate/* 외부 surface는 security 요구, /features 공용 read는 없음.
    tri = spec["paths"]["/tripmate/feature-update-requests"]["post"]
    assert tri.get("security")
    feat = spec["paths"]["/features"]["get"]
    assert not feat.get("security")


@pytest.mark.unit
def test_tripmate_requires_token_when_set() -> None:
    client = _client(AdminSettings(service_token=SecretStr("tok")))
    # 헤더 없음/오류 → 401(핸들러/DB 도달 전 auth 차단).
    assert client.post("/tripmate/feature-update-requests", json={}).status_code == 401
    assert (
        client.post(
            "/tripmate/feature-update-requests",
            json={},
            headers={SERVICE_TOKEN_HEADER: "wrong"},
        ).status_code
        == 401
    )


@pytest.mark.unit
def test_tripmate_token_unset_not_blocked() -> None:
    client = _client(AdminSettings(service_token=None))
    # 미설정이면 auth가 막지 않는다(하위호환). 본문/DB 사유로 401은 아니어야 한다.
    assert client.post("/tripmate/feature-update-requests", json={}).status_code != 401


@pytest.mark.unit
def test_features_not_gated_by_service_token() -> None:
    client = _client(AdminSettings(service_token=SecretStr("tok")))
    # 브라우저 admin UI도 쓰는 공용 read surface는 service token으로 막지 않는다.
    assert client.get("/features?limit=1").status_code != 401


@pytest.mark.unit
def test_destructive_admin_blocked_when_disabled() -> None:
    client = _client(AdminSettings(admin_destructive_enabled=False))
    assert (
        client.post(
            "/admin/features/f_x/deactivate", json={"reason": "test"}
        ).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE", "/admin/poi-cache-targets/tripmate/key-1"
        ).status_code
        == 403
    )
