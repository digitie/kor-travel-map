"""``/v1/ops/{system-logs,api-call-logs}`` 라우터 단위 테스트 (T-212c)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.log_repo import (
    ApiCallLogPage,
    ApiCallLogRow,
    SystemLogPage,
    SystemLogRow,
)

from krtour.map_admin.app import create_app
from krtour.map_admin.db import get_session
from krtour.map_admin.settings import AdminSettings

_NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


class _FakeSession:
    pass


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession) -> TestClient:
    app = create_app(AdminSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _sys_row(key: str = "11111111-1111-1111-1111-111111111111") -> SystemLogRow:
    return SystemLogRow(
        system_log_id=key,
        level="info",
        source="offline_upload",
        event="upload_done",
        message="업로드 완료",
        detail={"count": 3},
        request_id="req-1",
        created_at=_NOW,
    )


def _api_row(key: str = "22222222-2222-2222-2222-222222222222") -> ApiCallLogRow:
    return ApiCallLogRow(
        api_call_log_id=key,
        method="GET",
        path="/v1/ops/metrics",
        status_code=200,
        duration_ms=12,
        request_id="req-2",
        error_code=None,
        created_at=_NOW,
    )


@pytest.mark.unit
def test_ops_logs_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/ops/system-logs" in spec["paths"]
    assert "/v1/ops/api-call-logs" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "SystemLogsResponse" in schemas
    assert "ApiCallLogsResponse" in schemas
    assert set(schemas["SystemLogsResponse"]["properties"]) == {"data", "meta"}


@pytest.mark.unit
def test_system_logs_list_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops_logs as router_mod

    async def _list(_session: Any, **kwargs: Any) -> SystemLogPage:
        assert kwargs == {
            "level": "warning",
            "source": "geocoding",
            "q": "실패",
            "limit": 25,
            "cursor": "cursor-1",
        }
        return SystemLogPage(items=(_sys_row(),), next_cursor="cursor-2")

    monkeypatch.setattr(router_mod, "list_system_logs", _list)

    response = client.get(
        "/v1/ops/system-logs?level=warning&source=geocoding&q=실패"
        "&page_size=25&cursor=cursor-1"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert body["data"]["items"][0]["log_id"] == _sys_row().system_log_id
    assert body["data"]["items"][0]["detail"] == {"count": 3}
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "cursor-2",
        "total": None,
    }
    assert "duration_ms" in body["meta"]


@pytest.mark.unit
def test_api_call_logs_list_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops_logs as router_mod

    async def _list(_session: Any, **kwargs: Any) -> ApiCallLogPage:
        assert kwargs == {
            "method": "GET",
            "min_status": 500,
            "path": "/ops",
            "limit": 50,
            "cursor": None,
        }
        return ApiCallLogPage(items=(_api_row(),), next_cursor=None)

    monkeypatch.setattr(router_mod, "list_api_call_logs", _list)

    response = client.get("/v1/ops/api-call-logs?method=GET&min_status=500&path=/ops")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["status_code"] == 200
    assert body["data"]["items"][0]["log_id"] == _api_row().api_call_log_id
    assert body["meta"]["page"] == {
        "page_size": 50,
        "next_cursor": None,
        "total": None,
    }


@pytest.mark.unit
def test_system_logs_invalid_cursor_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import ops_logs as router_mod

    async def _list(_session: Any, **kwargs: Any) -> SystemLogPage:
        raise ValueError("invalid system_logs cursor")

    monkeypatch.setattr(router_mod, "list_system_logs", _list)

    response = client.get("/v1/ops/system-logs?cursor=bad")

    assert response.status_code == 422


@pytest.mark.unit
def test_api_call_logs_min_status_out_of_range_422(client: TestClient) -> None:
    # Query(ge=100, le=599) → 99는 FastAPI validation 422.
    response = client.get("/v1/ops/api-call-logs?min_status=99")
    assert response.status_code == 422
