"""``/v1/admin/features`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.admin_feature_repo import (
    AdminFeaturePage,
    AdminFeatureRow,
    FeatureChangeRequest,
    FeatureDeactivateResult,
    FeatureOverride,
    FeatureStateConflict,
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


def _feature_row() -> AdminFeatureRow:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return AdminFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="광화문",
        category="01070300",
        status="active",
        lon=126.9769,
        lat=37.5759,
        address_label="서울특별시 종로구",
        primary_provider="python-mois-api",
        primary_dataset_key="mois_license_features_bulk",
        issue_count=1,
        issues=(
            {
                "issue_id": "issue-1",
                "violation_type": "missing_address",
                "severity": "warning",
                "message": "주소 누락",
                "detected_at": now,
            },
        ),
        created_at=now,
        updated_at=now,
    )


def _change_request(
    *,
    request_id: str = "change-1",
    feature_id: str = "feature-1",
    action: str = "add",
    state: str = "pending",
    review_mode: str = "require_review",
    payload: dict[str, Any] | None = None,
    reason: str | None = "사용자 제보",
    requested_by: str | None = "local-admin",
    reviewed_by: str | None = None,
    applied_at: datetime | None = None,
) -> FeatureChangeRequest:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return FeatureChangeRequest(
        request_id=request_id,
        feature_id=feature_id,
        action=action,
        state=state,
        review_mode=review_mode,
        payload=payload or {},
        reason=reason,
        requested_by=requested_by,
        reviewed_by=reviewed_by,
        reviewed_at=now if reviewed_by is not None else None,
        applied_at=applied_at,
        created_at=now,
    )


@pytest.mark.unit
def test_admin_features_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/features" in spec["paths"]
    assert set(spec["paths"]["/v1/admin/features"]) >= {"get", "post"}
    assert "/v1/admin/features/{feature_id}" in spec["paths"]
    assert set(spec["paths"]["/v1/admin/features/{feature_id}"]) >= {"patch", "delete"}
    assert "/v1/admin/features/change-requests" in spec["paths"]
    assert "/v1/admin/features/change-requests/{request_id}/approve" in spec["paths"]
    assert "/v1/admin/features/change-requests/{request_id}/reject" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/deactivate" in spec["paths"]
    assert "AdminFeatureRecord" in spec["components"]["schemas"]
    assert "AdminFeatureCreateRequest" in spec["components"]["schemas"]
    assert "AdminFeaturePatchRequest" in spec["components"]["schemas"]
    assert "AdminFeatureChangeResponse" in spec["components"]["schemas"]
    assert (
        spec["components"]["schemas"]["AdminFeatureIssueRecord"][
            "additionalProperties"
        ]
        is False
    )


@pytest.mark.unit
def test_list_admin_features_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    async def _list(_session: Any, **kwargs: Any) -> AdminFeaturePage:
        assert kwargs["q"] == "광화문"
        assert kwargs["kinds"] == ["place"]
        assert kwargs["statuses"] == ["inactive"]
        assert kwargs["providers"] == ["python-mois-api"]
        assert kwargs["page_size"] == 25
        assert kwargs["sort"] == "issue_count"
        assert kwargs["order"] == "desc"
        return AdminFeaturePage(items=(_feature_row(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_admin_features", _list)

    response = client.get(
        "/v1/admin/features",
        params={
            "q": "광화문",
            "kind": "place",
            "status": "inactive",
            "provider": "python-mois-api",
            "page_size": "25",
            "sort": "issue_count",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["feature_id"] == "feature-1"
    assert body["data"]["items"][0]["issues"][0]["issue_id"] == "issue-1"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "next",
        "total": None,
    }


@pytest.mark.unit
def test_list_feature_change_requests_returns_current_review_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    client.app.dependency_overrides[router_mod._settings] = lambda: AdminSettings(
        feature_change_review_mode="immediate"
    )

    async def _list(_session: Any, **kwargs: Any) -> tuple[FeatureChangeRequest, ...]:
        assert kwargs["states"] == ["pending"]
        assert kwargs["actions"] == ["add"]
        assert kwargs["q"] == "광화문"
        assert kwargs["limit"] == 25
        return (_change_request(review_mode="immediate", state="applied"),)

    monkeypatch.setattr(router_mod, "list_feature_change_requests", _list)

    response = client.get(
        "/v1/admin/features/change-requests",
        params={
            "status": "pending",
            "action": "add",
            "q": "광화문",
            "page_size": "25",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["review_mode"] == "immediate"
    assert body["data"]["items"][0]["status"] == "applied"
    assert body["data"]["review_mode"] == "immediate"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": None,
        "total": None,
    }


@pytest.mark.unit
def test_create_feature_request_uses_review_required_by_default(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    async def _submit(_session: Any, **kwargs: Any) -> FeatureChangeRequest:
        assert kwargs["action"] == "add"
        assert kwargs["review_mode"] == "require_review"
        assert kwargs["payload"]["kind"] == "place"
        assert kwargs["payload"]["name"] == "사용자 장소"
        assert kwargs["payload"]["coord"] == {"lon": 126.98, "lat": 37.57}
        assert kwargs["payload"]["feature_id"] == kwargs["feature_id"]
        assert kwargs["reason"] == "사용자 제보"
        assert kwargs["requested_by"] == "tripmate-admin"
        return _change_request(
            feature_id=kwargs["feature_id"],
            action=kwargs["action"],
            state="pending",
            review_mode=kwargs["review_mode"],
            payload=kwargs["payload"],
            reason=kwargs["reason"],
            requested_by=kwargs["requested_by"],
        )

    monkeypatch.setattr(router_mod, "submit_feature_change_request", _submit)

    response = client.post(
        "/v1/admin/features",
        json={
            "kind": "place",
            "name": "사용자 장소",
            "category": "01070300",
            "coord": {"lon": 126.98, "lat": 37.57},
            "marker_icon": "map-pin",
            "marker_color": "P-01",
            "reason": "사용자 제보",
            "operator": "tripmate-admin",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["request"]["status"] == "pending"
    assert body["data"]["request"]["review_mode"] == "require_review"
    assert session.begin_count == 1


@pytest.mark.unit
def test_patch_feature_request_can_apply_immediately(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    client.app.dependency_overrides[router_mod._settings] = lambda: AdminSettings(
        feature_change_review_mode="immediate"
    )

    async def _submit(_session: Any, **kwargs: Any) -> FeatureChangeRequest:
        assert kwargs["action"] == "update"
        assert kwargs["feature_id"] == "feature-1"
        assert kwargs["payload"] == {"name": "수정된 장소"}
        assert kwargs["review_mode"] == "immediate"
        return _change_request(
            feature_id=kwargs["feature_id"],
            action=kwargs["action"],
            state="applied",
            review_mode=kwargs["review_mode"],
            payload=kwargs["payload"],
            applied_at=datetime(2026, 6, 3, tzinfo=UTC),
        )

    monkeypatch.setattr(router_mod, "submit_feature_change_request", _submit)

    response = client.patch(
        "/v1/admin/features/feature-1",
        json={
            "name": "수정된 장소",
            "reason": "사용자 수정",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["request"]["status"] == "applied"
    assert session.begin_count == 1


@pytest.mark.unit
def test_delete_feature_request_submits_soft_delete(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    async def _submit(_session: Any, **kwargs: Any) -> FeatureChangeRequest:
        assert kwargs["action"] == "delete"
        assert kwargs["feature_id"] == "feature-1"
        assert kwargs["payload"] == {}
        assert kwargs["reason"] == "사용자 삭제 요청"
        return _change_request(
            feature_id=kwargs["feature_id"],
            action=kwargs["action"],
            payload=kwargs["payload"],
            reason=kwargs["reason"],
        )

    monkeypatch.setattr(router_mod, "submit_feature_change_request", _submit)

    response = client.request(
        "DELETE",
        "/v1/admin/features/feature-1",
        json={"reason": "사용자 삭제 요청"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["request"]["action"] == "delete"
    assert session.begin_count == 1


@pytest.mark.unit
def test_approve_and_reject_feature_change_requests(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    async def _apply(
        _session: Any,
        request_id: str,
        **kwargs: Any,
    ) -> FeatureChangeRequest:
        assert request_id == "change-1"
        assert kwargs["operator"] == "reviewer"
        return _change_request(
            request_id=request_id,
            state="applied",
            reviewed_by=kwargs["operator"],
            applied_at=datetime(2026, 6, 3, tzinfo=UTC),
        )

    async def _reject(
        _session: Any,
        request_id: str,
        **kwargs: Any,
    ) -> FeatureChangeRequest:
        assert request_id == "change-2"
        assert kwargs["operator"] == "reviewer"
        assert kwargs["reason"] == "중복"
        return _change_request(
            request_id=request_id,
            state="rejected",
            reviewed_by=kwargs["operator"],
            reason=kwargs["reason"],
        )

    monkeypatch.setattr(router_mod, "apply_feature_change_request", _apply)
    monkeypatch.setattr(router_mod, "reject_feature_change_request", _reject)

    approve = client.post(
        "/v1/admin/features/change-requests/change-1/approve",
        json={"operator": "reviewer"},
    )
    reject = client.post(
        "/v1/admin/features/change-requests/change-2/reject",
        json={"operator": "reviewer", "reason": "중복"},
    )

    assert approve.status_code == 200
    assert approve.json()["data"]["request"]["status"] == "applied"
    assert reject.status_code == 200
    assert reject.json()["data"]["request"]["status"] == "rejected"
    assert session.begin_count == 2


@pytest.mark.unit
def test_deactivate_feature_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    now = datetime(2026, 6, 3, tzinfo=UTC)

    async def _deactivate(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        assert feature_id == "feature-1"
        assert kwargs["reason"] == "운영상 제외"
        assert kwargs["operator"] == "local-admin"
        assert kwargs["prevent_provider_reactivation"] is True
        return FeatureDeactivateResult(
            feature_id="feature-1",
            previous_status="active",
            status="inactive",
            override_created=True,
            override=FeatureOverride(
                override_id="override-1",
                feature_id="feature-1",
                field_path="status",
                override_value="inactive",
                prevent_provider_reactivation=True,
                reason="운영상 제외",
                created_by="local-admin",
                created_at=now,
            ),
        )

    monkeypatch.setattr(router_mod, "deactivate_feature", _deactivate)

    response = client.post(
        "/v1/admin/features/feature-1/deactivate",
        json={
            "reason": "운영상 제외",
            "operator": "local-admin",
            "prevent_provider_reactivation": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["override_created"] is True
    assert session.begin_count == 1


@pytest.mark.unit
def test_deactivate_missing_feature_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    async def _missing(_session: Any, _feature_id: str, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(router_mod, "deactivate_feature", _missing)

    response = client.post(
        "/v1/admin/features/missing/deactivate",
        json={"reason": "없음"},
    )

    assert response.status_code == 404


@pytest.mark.unit
def test_deactivate_state_conflict_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    async def _conflict(_session: Any, _feature_id: str, **_kwargs: Any) -> None:
        raise FeatureStateConflict(
            feature_id="feature-deleted",
            current_status="deleted",
            deleted_at=datetime(2026, 6, 3, tzinfo=UTC),
            target_status="inactive",
        )

    monkeypatch.setattr(router_mod, "deactivate_feature", _conflict)

    response = client.post(
        "/v1/admin/features/feature-deleted/deactivate",
        json={"reason": "삭제됨"},
    )

    assert response.status_code == 409
    assert "deleted" in response.json()["detail"]
