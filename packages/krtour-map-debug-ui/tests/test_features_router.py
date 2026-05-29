"""``test_features_router`` — ``/features`` 조회 라우터 (PR, ADR-035/004/012).

DB 무관 단위 테스트:
- 라우터 마운트 + OpenAPI 노출
- ``features_routes_enabled=False`` 시 unmount
- bbox min>max 422 검증 (DB 도달 전 차단)
- get_session 의존성 override로 404 / bbox 결과 매핑

실 DB(testcontainers) 적재→조회 round-trip은 메인 lib 통합 테스트
``tests/integration/test_feature_repo_load.py`` + frontend e2e(#117)에서.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from krtour.map_debug_ui.app import create_app
from krtour.map_debug_ui.settings import DebugUiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(DebugUiSettings()))


@pytest.mark.unit
def test_features_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/features" in spec["paths"]
    assert "/features/{feature_id}" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "FeatureSummary" in schemas
    assert "FeaturesInBboxResponse" in schemas
    assert "FeatureDetailResponse" in schemas


@pytest.mark.unit
def test_features_routes_disabled_unmounts() -> None:
    app = create_app(DebugUiSettings(features_routes_enabled=False))
    c = TestClient(app)
    # bbox 조회는 422(검증) 이전에 라우트 자체가 없어 404.
    r = c.get("/features", params={
        "min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38,
    })
    assert r.status_code == 404
    assert c.get("/features/x").status_code == 404


@pytest.mark.unit
def test_bbox_min_greater_than_max_returns_422(client: TestClient) -> None:
    """min>max는 DB 도달 전 422 (get_session 의존성 미평가 경로는 아니지만
    검증이 핸들러 본문 첫 줄이라 빈 세션으로도 충분 — override로 안전 보장)."""
    from krtour.map_debug_ui.db import get_session

    async def _empty_session() -> AsyncIterator[Any]:
        yield None  # 검증에서 막히므로 세션 미사용

    client.app.dependency_overrides[get_session] = _empty_session
    try:
        r = client.get("/features", params={
            "min_lon": 128, "min_lat": 37, "max_lon": 127, "max_lat": 38,
        })
        assert r.status_code == 422
        assert "bbox" in r.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()


class _FakeSession:
    """``feature_repo`` 호출을 가로채는 최소 fake (DB 무관 단위 테스트용)."""

    def __init__(self, *, get_row: dict[str, Any] | None, bbox_rows: list[dict[str, Any]]):
        self._get_row = get_row
        self._bbox_rows = bbox_rows


@pytest.mark.unit
def test_get_feature_404_when_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_debug_ui.db import get_session
    from krtour.map_debug_ui.routers import features as features_mod

    async def _none_get_row(_session: Any, _fid: str) -> None:
        return None

    monkeypatch.setattr(features_mod.feature_repo, "get_feature_row", _none_get_row)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/features/nonexistent")
        assert r.status_code == 404
        assert "nonexistent" in r.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_list_features_maps_bbox_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_debug_ui.db import get_session
    from krtour.map_debug_ui.routers import features as features_mod

    rows = [
        {
            "feature_id": "f1", "kind": "place", "name": "장소", "category": "01010100",
            "lon": 126.97, "lat": 37.56, "marker_icon": "star", "marker_color": "P-03",
            "status": "active",
        }
    ]

    async def _bbox(_session: Any, **_kw: Any) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/features", params={
            "min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38,
            "kind": ["place"],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["items"][0]["feature_id"] == "f1"
        assert body["items"][0]["lon"] == 126.97
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_feature_detail_maps_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_debug_ui.db import get_session
    from krtour.map_debug_ui.routers import features as features_mod

    row = {
        "feature_id": "f1", "kind": "event", "name": "축제", "category": "01000000",
        "lon": 126.92, "lat": 37.52, "coord_5179_srid": 5179,
        "address": {"road": "서울"}, "detail": {"event_kind": "festival"},
        "urls": {}, "raw_refs": [],
        "legal_dong_code": None, "sido_code": "11", "sigungu_code": "11560",
        "marker_icon": "star", "marker_color": "P-11", "status": "active",
        "parent_feature_id": None, "sibling_group_id": None,
        "created_at": "2026-05-29T00:00:00+09:00",
        "updated_at": "2026-05-29T00:00:00+09:00", "deleted_at": None,
    }

    async def _get_row(_session: Any, _fid: str) -> dict[str, Any]:
        return row

    monkeypatch.setattr(features_mod.feature_repo, "get_feature_row", _get_row)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/features/f1")
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "event"
        assert body["coord_5179_srid"] == 5179
        assert body["detail"] == {"event_kind": "festival"}
        # 응답 schema는 created_at 등 raw 전용 필드를 노출하지 않는다.
        assert "created_at" not in body
    finally:
        client.app.dependency_overrides.clear()
