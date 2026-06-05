"""``/admin/feature-update-requests`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestPage,
    FeatureUpdateRequestPreview,
)

from krtour.map_admin.app import create_app
from krtour.map_admin.db import get_session
from krtour.map_admin.settings import AdminSettings


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.begin_count = 0

    def begin(self) -> _Tx:
        self.begin_count += 1
        return _Tx()


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


def _request(
    *,
    request_id: str = "req-1",
    state: str = "queued",
    run_mode: str = "queued",
) -> FeatureUpdateRequest:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return FeatureUpdateRequest(
        request_id=request_id,
        scope_type="feature_ids",
        scope={"type": "feature_ids", "feature_ids": ["feature-1"]},
        providers=("python-a-api",),
        dataset_keys=("dataset-a",),
        update_policy={"mode": "refresh_existing"},
        run_mode=run_mode,
        priority=50,
        state=state,
        dry_run=False,
        matched_scope={"feature_count": 1, "sigungu_codes": []},
        job_id="job-1",
        dagster_run_id=None,
        operator="tester",
        reason="unit",
        error_message=None,
        created_at=now,
        started_at=None,
        finished_at=None,
        updated_at=now,
    )


def _preview() -> FeatureUpdateRequestPreview:
    return FeatureUpdateRequestPreview(
        scope_type="feature_ids",
        scope={"type": "feature_ids", "feature_ids": ["feature-1"]},
        providers=("python-a-api",),
        dataset_keys=("dataset-a",),
        update_policy={},
        run_mode="queued",
        priority=50,
        matched_scope={"feature_count": 1, "sigungu_codes": []},
    )


@pytest.mark.unit
def test_update_request_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/admin/feature-update-requests" in spec["paths"]
    assert "/admin/feature-update-requests/{request_id}" in spec["paths"]
    assert "/admin/feature-update-requests/{request_id}/cancel" in spec["paths"]
    assert "/admin/feature-update-requests/{request_id}/run-now" in spec["paths"]
    assert "FeatureUpdateRequestCreateRequest" in spec["components"]["schemas"]
    assert "FeatureUpdateRequestRecord" in spec["components"]["schemas"]
    request_schema = spec["components"]["schemas"][
        "FeatureUpdateRequestCreateRequest"
    ]
    scope_schema = request_schema["properties"]["scope"]
    assert scope_schema["discriminator"]["propertyName"] == "type"
    assert len(scope_schema["oneOf"]) == 6
    assert request_schema["properties"]["providers"]["maxItems"] == 32
    update_policy_schema = spec["components"]["schemas"]["FeatureUpdatePolicy"]
    assert update_policy_schema["additionalProperties"] is False


@pytest.mark.unit
def test_create_dry_run_returns_preview_without_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequestPreview:
        assert kwargs["dry_run"] is True
        assert kwargs["scope"] == {"type": "feature_ids", "feature_ids": ["feature-1"]}
        return _preview()

    monkeypatch.setattr(router_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/admin/feature-update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": ["python-a-api"],
            "dataset_keys": ["dataset-a"],
            "dry_run": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["state"] == "dry_run"
    assert body["data"]["request_id"] is None
    assert body["data"]["matched_scope"]["feature_count"] == 1
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_actual_request_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["dry_run"] is False
        assert kwargs["priority"] == 75
        return _request()

    monkeypatch.setattr(router_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/admin/feature-update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "run_mode": "queued",
            "priority": 75,
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["status_url"] == (
        "/admin/feature-update-requests/req-1"
    )
    assert session.begin_count == 1


@pytest.mark.unit
def test_create_rejects_legacy_center_radius_shape_before_enqueue(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _unexpected_enqueue(
        _session: Any, **_kwargs: Any
    ) -> FeatureUpdateRequest:
        raise AssertionError("validation should run before enqueue")

    monkeypatch.setattr(
        router_mod, "enqueue_feature_update_request", _unexpected_enqueue
    )

    response = client.post(
        "/admin/feature-update-requests",
        json={
            "scope": {
                "type": "center_radius",
                "lon": 127.0,
                "lat": 37.0,
                "radius_km": 5,
            },
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_rejects_unknown_update_policy_key(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.post(
        "/admin/feature-update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "update_policy": {"surprise": True},
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "surprise" in str(body["error"]["details"])
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_rejects_unbounded_provider_filter_list(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.post(
        "/admin/feature-update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [f"python-provider-{index}-api" for index in range(33)],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_sigungu_scope_without_kraddr_geo_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    class _Settings:
        kraddr_geo_base_url = None

    monkeypatch.setattr(router_mod, "KrtourMapSettings", _Settings)

    response = client.post(
        "/admin/feature-update-requests",
        json={
            "scope": {
                "type": "sigungu_by_radius",
                "center": {"lon": 127.0, "lat": 37.0},
                "radius_km": 5,
            },
            "dry_run": True,
        },
    )

    assert response.status_code == 503
    assert "KRTOUR_MAP_KRADDR_GEO_BASE_URL" in response.json()["error"]["message"]


@pytest.mark.unit
def test_list_requests_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _list(_session: Any, **kwargs: Any) -> FeatureUpdateRequestPage:
        assert kwargs["state"] == "queued"
        assert kwargs["scope_type"] == "feature_ids"
        assert kwargs["provider"] == "python-a-api"
        assert kwargs["dataset_key"] == "dataset-a"
        assert kwargs["limit"] == 25
        return FeatureUpdateRequestPage(items=(_request(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_update_requests", _list)

    response = client.get(
        "/admin/feature-update-requests",
        params={
            "state": "queued",
            "scope_type": "feature_ids",
            "provider": "python-a-api",
            "dataset_key": "dataset-a",
            "page_size": 25,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["next_cursor"] == "next"
    assert body["items"][0]["request_id"] == "req-1"


@pytest.mark.unit
def test_get_request_404_when_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _missing(_session: Any, _request_id: str) -> None:
        return None

    monkeypatch.setattr(router_mod, "get_update_request", _missing)

    response = client.get("/admin/feature-update-requests/missing")

    assert response.status_code == 404


@pytest.mark.unit
def test_cancel_request_returns_cancelled(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _cancel(
        _session: Any, request_id: str, *, error_message: str | None
    ) -> FeatureUpdateRequest:
        assert request_id == "req-1"
        assert error_message == "stop"
        return _request(state="cancelled")

    monkeypatch.setattr(router_mod, "cancel_update_request", _cancel)

    response = client.post(
        "/admin/feature-update-requests/req-1/cancel",
        json={"error_message": "stop"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["state"] == "cancelled"
    assert session.begin_count == 1


@pytest.mark.unit
def test_run_now_requeues_existing_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _get(_session: Any, request_id: str) -> FeatureUpdateRequest:
        assert request_id == "req-1"
        return _request()

    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["run_mode"] == "now"
        assert kwargs["priority"] == 90
        assert kwargs["reason"] == "force"
        return _request(request_id="req-2", run_mode="now")

    monkeypatch.setattr(router_mod, "get_update_request", _get)
    monkeypatch.setattr(router_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/admin/feature-update-requests/req-1/run-now",
        json={"priority": 90, "reason": "force"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["request_id"] == "req-2"
    assert body["data"]["run_mode"] == "now"


@pytest.mark.unit
def test_create_run_now_lock_busy_returns_retry_after(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _enqueue(_session: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise FeatureUpdateLockBusy(retry_after_seconds=15)

    monkeypatch.setattr(router_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/admin/feature-update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "run_mode": "now",
        },
    )

    assert response.status_code == 409
    assert response.headers["retry-after"] == "15"
    body = response.json()
    assert body["error"]["code"] == "LOCK_BUSY"
    assert body["error"]["details"]["retry_after_seconds"] == 15


@pytest.mark.unit
def test_create_unknown_enqueue_error_hides_internal_message(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import feature_update_requests as router_mod

    async def _enqueue(_session: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise RuntimeError("secret DSN leaked")

    monkeypatch.setattr(router_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/admin/feature-update-requests",
        json={"scope": {"type": "feature_ids", "feature_ids": ["feature-1"]}},
    )

    assert response.status_code == 500
    assert response.json()["error"]["message"] == (
        "feature update request enqueue failed"
    )
