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

from krtour.map_admin.app import create_app
from krtour.map_admin.settings import AdminSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(AdminSettings()))


@pytest.mark.unit
def test_features_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/features" in spec["paths"]
    assert "/features/in-bounds" in spec["paths"]
    assert "/features/search" in spec["paths"]
    assert "/features/nearby" in spec["paths"]
    assert "/features/{feature_id}" in spec["paths"]
    assert "/tripmate/features/batch" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "FeatureSummary" in schemas
    assert "FeaturesInBboxResponse" in schemas
    assert "FeatureDetailResponse" in schemas
    assert "FeatureDetailEnvelopeResponse" in schemas
    assert "FeatureBatchResponse" in schemas
    assert "FeatureSearchResponse" in schemas
    assert "FeaturesNearbyResponse" in schemas


@pytest.mark.unit
def test_features_nearby_validation(client: TestClient) -> None:
    # radius_m 필수 — 누락 시 DB 도달 전 422.
    assert client.get(
        "/features/nearby", params={"lon": 127.0, "lat": 37.5}
    ).status_code == 422
    # lon 범위 초과 → 422.
    assert client.get(
        "/features/nearby", params={"lon": 200.0, "lat": 37.5, "radius_m": 1000}
    ).status_code == 422
    # radius_m must be > 0 → 422.
    assert client.get(
        "/features/nearby", params={"lon": 127.0, "lat": 37.5, "radius_m": 0}
    ).status_code == 422
    # invalid sort → 422.
    assert client.get(
        "/features/nearby",
        params={"lon": 127.0, "lat": 37.5, "radius_m": 1000, "sort": "bogus"},
    ).status_code == 422


@pytest.mark.unit
def test_features_routes_disabled_unmounts() -> None:
    app = create_app(AdminSettings(features_routes_enabled=False))
    c = TestClient(app)
    # bbox 조회는 422(검증) 이전에 라우트 자체가 없어 404.
    r = c.get("/features", params={
        "min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38,
    })
    assert r.status_code == 404
    assert c.get("/features/x").status_code == 404
    assert c.post("/tripmate/features/batch", json={"feature_ids": ["x"]}).status_code == 404


@pytest.mark.unit
def test_bbox_min_greater_than_max_returns_422(client: TestClient) -> None:
    """min>max는 DB 도달 전 422 (get_session 의존성 미평가 경로는 아니지만
    검증이 핸들러 본문 첫 줄이라 빈 세션으로도 충분 — override로 안전 보장)."""
    from krtour.map_admin.db import get_session

    async def _empty_session() -> AsyncIterator[Any]:
        yield None  # 검증에서 막히므로 세션 미사용

    client.app.dependency_overrides[get_session] = _empty_session
    try:
        r = client.get("/features", params={
            "min_lon": 128, "min_lat": 37, "max_lon": 127, "max_lat": 38,
        })
        assert r.status_code == 422
        assert "bbox" in r.json()["error"]["message"]
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
    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import features as features_mod

    async def _none_get_row(_session: Any, _fid: str) -> None:
        return None

    monkeypatch.setattr(features_mod.feature_repo, "get_feature_row", _none_get_row)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/features/nonexistent")
        assert r.status_code == 404
        assert "nonexistent" in r.json()["error"]["message"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_list_features_maps_bbox_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import features as features_mod

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
def test_list_public_features_in_bounds_uses_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import features as features_mod

    rows = [
        {
            "feature_id": "f1", "kind": "place", "name": "장소", "category": "01010100",
            "lon": 126.97, "lat": 37.56, "marker_icon": "star", "marker_color": "P-03",
            "status": "active",
        }
    ]

    async def _bbox(_session: Any, **_kw: Any) -> list[dict[str, Any]]:
        assert _kw["categories"] == ["01010100"]
        return rows

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/features/in-bounds", params={
            "min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38,
            "category": ["01010100"],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["count"] == 1
        assert body["data"]["items"][0]["feature_id"] == "f1"
        assert body["data"]["cluster_unit"] is None
        assert "duration_ms" in body["meta"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_feature_detail_maps_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import features as features_mod

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
        assert body["data"]["kind"] == "event"
        assert body["data"]["detail"] == {"event_kind": "festival"}
        assert body["data"]["updated_at"] == "2026-05-29T00:00:00+09:00"
        assert "duration_ms" in body["meta"]
        # 공개 응답 schema는 raw/infra/dedup 전용 필드를 노출하지 않는다.
        assert "created_at" not in body["data"]
        assert "coord_5179_srid" not in body["data"]
        assert "parent_feature_id" not in body["data"]
        assert "sibling_group_id" not in body["data"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_tripmate_batch_returns_items_and_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import features as features_mod

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

    async def _get_rows(_session: Any, feature_ids: list[str]) -> dict[str, dict[str, Any]]:
        assert feature_ids == ["f1", "missing"]
        return {"f1": row}

    monkeypatch.setattr(features_mod.feature_repo, "get_feature_rows_by_ids", _get_rows)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.post(
            "/tripmate/features/batch",
            json={"feature_ids": ["f1", "missing", "f1"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["items"]["f1"]["name"] == "축제"
        assert "coord_5179_srid" not in body["data"]["items"]["f1"]
        assert "parent_feature_id" not in body["data"]["items"]["f1"]
        assert "sibling_group_id" not in body["data"]["items"]["f1"]
        assert body["data"]["missing"] == ["missing"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_search_features_maps_page_and_requires_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map.infra.feature_repo import FeatureSearchPage, FeatureSearchRow

    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import features as features_mod

    async def _search(_session: Any, **_kw: Any) -> FeatureSearchPage:
        assert _kw["q"] == "경복궁"
        return FeatureSearchPage(
            items=(
                FeatureSearchRow(
                    feature_id="f1",
                    kind="place",
                    name="경복궁",
                    category="01070100",
                    lon=126.977,
                    lat=37.5796,
                    marker_icon="monument",
                    marker_color="P-01",
                    status="active",
                    score=1.0,
                ),
            ),
            total_count=1,
            next_cursor=None,
        )

    monkeypatch.setattr(features_mod.feature_repo, "search_features", _search)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/features/search", params={"q": "경복궁"})
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["items"][0]["feature_id"] == "f1"
        assert body["data"]["total_count"] == 1
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_search_features_rejects_bad_bbox(
    client: TestClient,
) -> None:
    r = client.get("/features/search", params={"bbox": "127,37,126,38"})
    assert r.status_code == 422
    assert "bbox" in r.json()["error"]["message"]


@pytest.mark.unit
def test_search_features_rejects_missing_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import features as features_mod

    async def _search(_session: Any, **_kw: Any) -> None:
        raise ValueError("q 또는 bbox 중 하나는 필요합니다")

    monkeypatch.setattr(features_mod.feature_repo, "search_features", _search)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/features/search")
        assert r.status_code == 422
        assert "q 또는 bbox" in r.json()["error"]["message"]
    finally:
        client.app.dependency_overrides.clear()
