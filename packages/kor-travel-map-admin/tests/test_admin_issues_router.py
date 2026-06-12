"""``/v1/admin/issues`` 운영 이슈 라우터 단위 테스트 (T-212 / DA-D-04)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.feature_address_repo import (
    FeatureAddressOverrideResult,
    FeatureAddressSnapshot,
)
from kortravelmap.infra.integrity_violation_repo import (
    DataIntegrityViolation,
    DataIntegrityViolationStateConflict,
)
from kortravelmap.infra.ops_repo import OpsIntegrityIssue, OpsIntegrityIssuePage

from kortravelmap.admin.app import create_app
from kortravelmap.admin.db import get_session
from kortravelmap.admin.routers import admin_issues as router_mod
from kortravelmap.admin.settings import AdminSettings

_VIOLATION_KEY = "44444444-4444-4444-4444-444444444444"


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


def _ops_issue(issue_id: str = _VIOLATION_KEY) -> OpsIntegrityIssue:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OpsIntegrityIssue(
        issue_id=issue_id,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key="src-1",
        feature_id="feature-1",
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
        payload={"raw_address": "서울특별시 영등포구 여의공원로 120"},
        status="open",
        detected_at=now,
        resolved_at=None,
    )


def _violation(
    *,
    status: str = "open",
    feature_id: str | None = "feature-1",
    resolved_at: datetime | None = None,
) -> DataIntegrityViolation:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return DataIntegrityViolation(
        issue_id=_VIOLATION_KEY,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key="src-1",
        feature_id=feature_id,
        violation_type="address_mismatch",
        severity="warning",
        message="주소 매칭 실패",
        payload={"raw_address": "서울특별시 영등포구 여의공원로 120"},
        status=status,
        detected_at=now,
        resolved_at=resolved_at,
    )


def _snapshot(
    *,
    lon: float | None = 126.978,
    lat: float | None = 37.5665,
) -> FeatureAddressSnapshot:
    return FeatureAddressSnapshot(
        feature_id="feature-1",
        lon=lon,
        lat=lat,
        address={"road": "서울특별시 영등포구 여의공원로 120"},
        legal_dong_code="1156010100",
        sido_code="11",
        sigungu_code="11560",
        road_address_management_no=None,
        status="active",
    )


@pytest.mark.unit
def test_admin_issues_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/issues" in spec["paths"]
    assert "/v1/admin/issues/{issue_id}" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "AdminIssueListResponse" in schemas
    assert set(schemas["AdminIssueListResponse"]["properties"]) == {"data", "meta"}


@pytest.mark.unit
def test_list_issues_passes_filters_and_envelope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _list(_session: Any, **kwargs: Any) -> OpsIntegrityIssuePage:
        assert kwargs["status"] == "open"
        assert kwargs["violation_type"] == "address_mismatch"
        assert kwargs["provider"] == "python-mois-api"
        assert kwargs["dataset_key"] == "mois_license_features_bulk"
        assert kwargs["severity"] == "error"
        assert kwargs["feature_id"] == "feature-1"
        assert kwargs["q"] == "종로"
        assert kwargs["bbox"] == (126.97, 37.57, 126.98, 37.58)
        assert kwargs["limit"] == 25
        assert kwargs["cursor"] == "cursor-1"
        return OpsIntegrityIssuePage(items=(_ops_issue(),), next_cursor="cursor-2")

    monkeypatch.setattr(router_mod, "list_ops_integrity_issues", _list)

    response = client.get(
        "/v1/admin/issues",
        params={
            "status": "open",
            "issue_type": "address_mismatch",
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
            "severity": "error",
            "feature_id": "feature-1",
            "q": "종로",
            "min_lon": "126.97",
            "min_lat": "37.57",
            "max_lon": "126.98",
            "max_lat": "37.58",
            "page_size": "25",
            "cursor": "cursor-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "cursor-2",
        "total": None,
    }
    assert body["data"]["items"][0]["issue_id"] == _VIOLATION_KEY


@pytest.mark.unit
def test_list_issues_invalid_bbox_returns_422(client: TestClient) -> None:
    response = client.get(
        "/v1/admin/issues",
        params={"min_lon": "126.97", "min_lat": "37.57", "max_lon": "126.98"},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_list_issues_invalid_cursor_returns_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _list(_session: Any, **_kwargs: Any) -> OpsIntegrityIssuePage:
        raise ValueError("invalid integrity_issues cursor")

    monkeypatch.setattr(router_mod, "list_ops_integrity_issues", _list)

    response = client.get("/v1/admin/issues", params={"cursor": "bad"})

    assert response.status_code == 422


@pytest.mark.unit
def test_get_issue_detail_with_feature(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, key: str) -> DataIntegrityViolation:
        assert key == _VIOLATION_KEY
        return _violation()

    async def _feature(_session: Any, feature_id: str) -> FeatureAddressSnapshot:
        assert feature_id == "feature-1"
        return _snapshot()

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _get)
    monkeypatch.setattr(router_mod, "get_feature_address_snapshot", _feature)

    response = client.get(f"/v1/admin/issues/{_VIOLATION_KEY}")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["issue"]["issue_id"] == _VIOLATION_KEY
    assert body["data"]["feature"]["feature_id"] == "feature-1"
    assert body["data"]["feature"]["sigungu_code"] == "11560"


@pytest.mark.unit
def test_get_issue_detail_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _missing(_session: Any, _key: str) -> None:
        return None

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _missing)

    response = client.get(f"/v1/admin/issues/{_VIOLATION_KEY}")

    assert response.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        ("resolve", "resolved"),
        ("ignore", "ignored"),
        ("reopen", "open"),
    ],
)
def test_patch_status_actions(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    expected_status: str,
) -> None:
    async def _get(_session: Any, _key: str) -> DataIntegrityViolation:
        return _violation()

    captured: dict[str, Any] = {}

    async def _set(_session: Any, key: str, **kwargs: Any) -> DataIntegrityViolation:
        captured["key"] = key
        captured["status"] = kwargs["status"]
        captured["resolution_payload"] = kwargs["resolution_payload"]
        return _violation(status=kwargs["status"])

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _get)
    monkeypatch.setattr(router_mod, "set_data_integrity_violation_status", _set)

    response = client.patch(
        f"/v1/admin/issues/{_VIOLATION_KEY}",
        json={"action": action, "operator": "ops-1", "reason": "검토 완료"},
    )

    assert response.status_code == 200
    assert captured["status"] == expected_status
    assert captured["resolution_payload"]["action"] == action
    assert response.json()["data"]["issue"]["status"] == expected_status
    assert session.begin_count == 1


@pytest.mark.unit
def test_patch_state_conflict_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, _key: str) -> DataIntegrityViolation:
        return _violation(status="resolved")

    async def _set(_session: Any, key: str, **kwargs: Any) -> DataIntegrityViolation:
        raise DataIntegrityViolationStateConflict(
            issue_id=key,
            current_status="resolved",
            target_status=kwargs["status"],
        )

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _get)
    monkeypatch.setattr(router_mod, "set_data_integrity_violation_status", _set)

    response = client.patch(
        f"/v1/admin/issues/{_VIOLATION_KEY}",
        json={"action": "resolve"},
    )

    assert response.status_code == 409


@pytest.mark.unit
def test_patch_manual_override_applies_and_resolves(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, _key: str) -> DataIntegrityViolation:
        return _violation()

    captured: dict[str, Any] = {}

    async def _apply(
        _session: Any, feature_id: str, **kwargs: Any
    ) -> FeatureAddressOverrideResult:
        captured["feature_id"] = feature_id
        captured.update(kwargs)
        return FeatureAddressOverrideResult(
            snapshot=_snapshot(),
            overridden_fields=("coord", "legal_dong_code"),
        )

    async def _set(_session: Any, _key: str, **kwargs: Any) -> DataIntegrityViolation:
        return _violation(status=kwargs["status"])

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _get)
    monkeypatch.setattr(router_mod, "apply_feature_address_override", _apply)
    monkeypatch.setattr(router_mod, "set_data_integrity_violation_status", _set)

    response = client.patch(
        f"/v1/admin/issues/{_VIOLATION_KEY}",
        json={
            "action": "manual_override",
            "coord": {"lon": 126.978, "lat": 37.5665},
            "legal_dong_code": "1156010100",
            "operator": "ops-1",
            "reason": "수동 보정",
        },
    )

    assert response.status_code == 200
    assert captured["feature_id"] == "feature-1"
    assert captured["lon"] == 126.978
    assert captured["lat"] == 37.5665
    assert captured["legal_dong_code"] == "1156010100"
    assert captured["reason"] == "수동 보정"
    assert captured["operator"] == "ops-1"
    body = response.json()
    assert body["data"]["issue"]["status"] == "resolved"
    assert body["data"]["feature"]["feature_id"] == "feature-1"
    assert session.begin_count == 1


@pytest.mark.unit
def test_patch_manual_override_no_fields_returns_422(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, _key: str) -> DataIntegrityViolation:
        return _violation()

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _get)

    response = client.patch(
        f"/v1/admin/issues/{_VIOLATION_KEY}",
        json={"action": "manual_override"},
    )

    assert response.status_code == 422
    assert session.begin_count == 0


@pytest.mark.unit
def test_patch_action_requires_feature_returns_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, _key: str) -> DataIntegrityViolation:
        return _violation(feature_id=None)

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _get)

    response = client.patch(
        f"/v1/admin/issues/{_VIOLATION_KEY}",
        json={"action": "retry_reverse_geocode"},
    )

    assert response.status_code == 422
    assert "no linked feature" in response.json()["detail"]


@pytest.mark.unit
def test_patch_retry_reverse_geocode_returns_candidate(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, _key: str) -> DataIntegrityViolation:
        return _violation()

    async def _feature(_session: Any, _feature_id: str) -> FeatureAddressSnapshot:
        return _snapshot()

    captured: dict[str, Any] = {}

    async def _reverse(lon: float, lat: float) -> dict[str, Any]:
        captured["lon"] = lon
        captured["lat"] = lat
        return {
            "address": {"road": "서울특별시 영등포구 여의공원로 120"},
            "legal_dong_code": "1156010100",
            "sido_code": "11",
            "sigungu_code": "11560",
            "road_address_management_no": None,
        }

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _get)
    monkeypatch.setattr(router_mod, "get_feature_address_snapshot", _feature)
    monkeypatch.setattr(router_mod, "_reverse_geocode", _reverse)

    response = client.patch(
        f"/v1/admin/issues/{_VIOLATION_KEY}",
        json={"action": "retry_reverse_geocode"},
    )

    assert response.status_code == 200
    assert captured["lon"] == 126.978
    assert captured["lat"] == 37.5665
    body = response.json()
    # 상태 변경 없음 — 후보만 반환.
    assert body["data"]["issue"]["status"] == "open"
    assert body["data"]["geocode_candidate"]["legal_dong_code"] == "1156010100"
    assert session.begin_count == 0


@pytest.mark.unit
def test_patch_geocode_action_503_when_base_url_unset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, _key: str) -> DataIntegrityViolation:
        return _violation()

    async def _feature(_session: Any, _feature_id: str) -> FeatureAddressSnapshot:
        return _snapshot()

    async def _reverse(_lon: float, _lat: float) -> dict[str, Any] | None:
        raise router_mod._KorTravelGeoUnavailable("kor-travel-geo base URL 미설정")

    monkeypatch.setattr(router_mod, "get_data_integrity_violation", _get)
    monkeypatch.setattr(router_mod, "get_feature_address_snapshot", _feature)
    monkeypatch.setattr(router_mod, "_reverse_geocode", _reverse)

    response = client.patch(
        f"/v1/admin/issues/{_VIOLATION_KEY}",
        json={"action": "retry_reverse_geocode"},
    )

    assert response.status_code == 503
