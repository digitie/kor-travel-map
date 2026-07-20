"""``test_features_router`` — ``/v1/features`` 조회 라우터 (PR, ADR-035/004/012).

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
from kortravelmap.core.exceptions import (
    FeatureSearchCursorInvalidError,
    FeatureSearchCursorQueryMismatchError,
    FeatureSearchCursorTamperedError,
    FeatureSearchCursorVersionUnsupportedError,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None)))


@pytest.mark.unit
def test_features_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/features" in spec["paths"]
    assert "/v1/features/in-bounds" in spec["paths"]
    assert "/v1/features/search" in spec["paths"]
    assert "/v1/features/nearby" in spec["paths"]
    assert "/v1/features/{feature_id}" in spec["paths"]
    assert "/v1/features/{feature_id}/price" in spec["paths"]
    assert "/v1/features/batch" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "FeatureSummary" in schemas
    assert "FeaturePriceResponse" in schemas
    assert "FeaturesInBboxResponse" in schemas
    assert "FeatureDetailResponse" in schemas
    assert "FeatureDetailEnvelopeResponse" in schemas
    assert "FeatureBatchResponse" in schemas
    assert "FeatureSearchResponse" in schemas
    assert "FeaturesNearbyResponse" in schemas


@pytest.mark.unit
def test_features_in_bbox_exposes_provider_filter(client: TestClient) -> None:
    """``/v1/features``(지도 뷰포트 endpoint)가 provider(소스) 필터 파라미터를 노출해야
    한다 — admin 지도의 소스 필터가 실제로 동작하려면 이 endpoint가 provider를 받아
    ``features_in_bbox(providers=...)``로 넘겨야 한다(엔드포인트 오인 회귀 방지)."""
    spec = client.get("/openapi.json").json()
    params = spec["paths"]["/v1/features"]["get"].get("parameters", [])
    names = {p["name"] for p in params}
    assert "provider" in names, f"/v1/features must expose the provider filter; has {sorted(names)}"


@pytest.mark.unit
def test_features_nearby_validation(client: TestClient) -> None:
    # radius_m 필수 — 누락 시 DB 도달 전 422.
    assert client.get("/v1/features/nearby", params={"lon": 127.0, "lat": 37.5}).status_code == 422
    # lon 범위 초과 → 422.
    assert (
        client.get(
            "/v1/features/nearby", params={"lon": 200.0, "lat": 37.5, "radius_m": 1000}
        ).status_code
        == 422
    )
    # radius_m must be > 0 → 422.
    assert (
        client.get(
            "/v1/features/nearby", params={"lon": 127.0, "lat": 37.5, "radius_m": 0}
        ).status_code
        == 422
    )
    # invalid sort → 422.
    assert (
        client.get(
            "/v1/features/nearby",
            params={"lon": 127.0, "lat": 37.5, "radius_m": 1000, "sort": "bogus"},
        ).status_code
        == 422
    )


@pytest.mark.unit
def test_features_routes_disabled_unmounts() -> None:
    app = create_app(ApiSettings(features_routes_enabled=False))
    c = TestClient(app)
    # bbox 조회는 422(검증) 이전에 라우트 자체가 없어 404.
    r = c.get(
        "/v1/features",
        params={
            "min_lon": 126,
            "min_lat": 37,
            "max_lon": 127,
            "max_lat": 38,
        },
    )
    assert r.status_code == 404
    assert c.get("/v1/features/x").status_code == 404
    assert c.post("/v1/features/batch", json={"feature_ids": ["x"]}).status_code == 404


@pytest.mark.unit
def test_bbox_min_greater_than_max_returns_422(client: TestClient) -> None:
    """min>max는 DB 도달 전 422 (get_session 의존성 미평가 경로는 아니지만
    검증이 핸들러 본문 첫 줄이라 빈 세션으로도 충분 — override로 안전 보장)."""
    from kortravelmap.api.db import get_session

    async def _empty_session() -> AsyncIterator[Any]:
        yield None  # 검증에서 막히므로 세션 미사용

    client.app.dependency_overrides[get_session] = _empty_session
    try:
        r = client.get(
            "/v1/features",
            params={
                "min_lon": 128,
                "min_lat": 37,
                "max_lon": 127,
                "max_lat": 38,
            },
        )
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
def test_get_feature_404_when_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _none_get_row(_session: Any, _fid: str) -> None:
        return None

    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_row", _none_get_row)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/v1/features/nonexistent")
        assert r.status_code == 404
        assert "nonexistent" in r.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_feature_404_when_notice_is_ended_or_non_latest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    row = {
        "feature_id": "notice-old",
        "kind": "notice",
        "status": "active",
        "row_revision": 7,
        "deleted_at": None,
    }

    async def _get_row(_session: Any, _fid: str) -> dict[str, Any]:
        return row

    async def _public_ids(_session: Any, feature_ids: list[str]) -> set[str]:
        assert feature_ids == ["notice-old"]
        return set()

    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_row", _get_row)
    monkeypatch.setattr(
        features_mod.feature_repo,
        "public_active_notice_feature_ids",
        _public_ids,
    )

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/v1/features/notice-old")
        assert r.status_code == 404
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_list_features_maps_bbox_rows(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    rows = [
        {
            "feature_id": "f1",
            "kind": "place",
            "name": "장소",
            "category": "01010100",
            "lon": 126.97,
            "lat": 37.56,
            "marker_icon": "star",
            "marker_color": "P-03",
            "status": "active",
            "price_summary": None,
        }
    ]

    async def _bbox(_session: Any, **_kw: Any) -> list[dict[str, Any]]:
        assert _kw["limit"] == 101
        assert _kw["cursor"] is None
        assert _kw["price_stale_hide_days"] is None
        return rows

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get(
            "/v1/features",
            params={
                "min_lon": 126,
                "min_lat": 37,
                "max_lon": 127,
                "max_lat": 38,
                "kind": ["place"],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["items"][0]["feature_id"] == "f1"
        assert body["data"]["items"][0]["lon"] == 126.97
        assert body["data"]["items"][0]["price_summary"] is None
        assert body["meta"]["page"] == {
            "page_size": 100,
            "next_cursor": None,
            "total": None,
        }
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_list_features_include_geometry_maps_route_area_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    rows = [
        {
            "feature_id": "route1",
            "kind": "route",
            "name": "탐방로",
            "category": "02000000",
            "lon": 127.0,
            "lat": 37.5,
            "marker_icon": "park",
            "marker_color": "P-06",
            "status": "active",
            "geometry": {
                "type": "LineString",
                "coordinates": [[127.0, 37.5], [127.1, 37.6]],
            },
            "area_square_meters": None,
        },
        {
            "feature_id": "area1",
            "kind": "area",
            "name": "국립공원",
            "category": "03000000",
            "lon": 127.2,
            "lat": 37.7,
            "marker_icon": "park",
            "marker_color": "P-06",
            "status": "active",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [127.0, 37.5],
                        [127.2, 37.5],
                        [127.2, 37.7],
                        [127.0, 37.7],
                        [127.0, 37.5],
                    ]
                ],
            },
            "area_square_meters": 12345.6,
        },
    ]

    async def _bbox(_session: Any, **_kw: Any) -> list[dict[str, Any]]:
        assert _kw["include_geometry"] is True
        return rows

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get(
            "/v1/features",
            params={
                "min_lon": 126,
                "min_lat": 37,
                "max_lon": 128,
                "max_lat": 38,
                "include_geometry": "true",
            },
        )
        assert r.status_code == 200
        body = r.json()
        route, area = body["data"]["items"]
        assert route["geometry"]["type"] == "LineString"
        assert route["area_square_meters"] is None
        assert area["geometry"]["type"] == "Polygon"
        assert area["area_square_meters"] == 12345.6
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_list_features_default_omits_geometry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """include_geometry 미지정 시 repo는 include_geometry=False로 호출되고
    응답의 geometry/area_square_meters는 None이다 (PR #512 follow-up)."""
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    rows = [
        {
            "feature_id": "f1",
            "kind": "place",
            "name": "장소",
            "category": "01010100",
            "lon": 126.97,
            "lat": 37.56,
            "marker_icon": "star",
            "marker_color": "P-03",
            "status": "active",
        }
    ]

    async def _bbox(_session: Any, **_kw: Any) -> list[dict[str, Any]]:
        assert _kw["include_geometry"] is False
        return rows

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get(
            "/v1/features",
            params={
                "min_lon": 126,
                "min_lat": 37,
                "max_lon": 127,
                "max_lat": 38,
            },
        )
        assert r.status_code == 200
        item = r.json()["data"]["items"][0]
        assert item["geometry"] is None
        assert item["area_square_meters"] is None
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_list_public_features_in_bounds_include_geometry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /features/in-bounds`` 의 include_geometry=true는 repo로 전달되고
    route/area geometry가 매핑된다 (PR #512 follow-up)."""
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    rows = [
        {
            "feature_id": "route1",
            "kind": "route",
            "name": "탐방로",
            "category": "02000000",
            "lon": 127.0,
            "lat": 37.5,
            "marker_icon": "park",
            "marker_color": "P-06",
            "status": "active",
            "geometry": {
                "type": "LineString",
                "coordinates": [[127.0, 37.5], [127.1, 37.6]],
            },
            "area_square_meters": None,
        }
    ]

    async def _bbox(_session: Any, **_kw: Any) -> list[dict[str, Any]]:
        assert _kw["include_geometry"] is True
        return rows

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get(
            "/v1/features/in-bounds",
            params={
                "min_lon": 126,
                "min_lat": 37,
                "max_lon": 128,
                "max_lat": 38,
                "include_geometry": "true",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["cluster"] is None
        route = body["data"]["items"][0]
        assert route["geometry"]["type"] == "LineString"
        assert route["area_square_meters"] is None
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_list_public_features_in_bounds_uses_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    rows = [
        {
            "feature_id": "f1",
            "kind": "place",
            "name": "장소",
            "category": "01010100",
            "lon": 126.97,
            "lat": 37.56,
            "marker_icon": "star",
            "marker_color": "P-03",
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
        r = client.get(
            "/v1/features/in-bounds",
            params={
                "min_lon": 126,
                "min_lat": 37,
                "max_lon": 127,
                "max_lat": 38,
                "category": ["01010100"],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["items"][0]["feature_id"] == "f1"
        assert body["meta"]["cluster"] is None
        assert "duration_ms" in body["meta"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_feature_detail_maps_row(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    row = {
        "feature_id": "f1",
        "kind": "event",
        "name": "축제",
        "category": "01000000",
        "lon": 126.92,
        "lat": 37.52,
        "coord_5179_srid": 5179,
        "address": {"road": "서울"},
        "detail": {"event_kind": "festival", "payload": {"raw_source_field": "x"}},
        "urls": {},
        "raw_refs": [],
        "legal_dong_code": None,
        "sido_code": "11",
        "sigungu_code": "11560",
        "marker_icon": "star",
        "marker_color": "P-11",
        "status": "active",
        "row_revision": 7,
        "parent_feature_id": None,
        "sibling_group_id": None,
        "created_at": "2026-05-29T00:00:00+09:00",
        "updated_at": "2026-05-29T00:00:00+09:00",
        "deleted_at": None,
    }

    async def _get_row(_session: Any, _fid: str) -> dict[str, Any]:
        return row

    async def _curations(
        _session: Any, *, feature_ids: list[str], public_only: bool
    ) -> dict[str, tuple[Any, ...]]:
        assert feature_ids == ["f1"]
        assert public_only is True
        return {}

    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_row", _get_row)
    monkeypatch.setattr(
        features_mod.curation_repo,
        "list_curation_items_by_feature_ids",
        _curations,
    )

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/v1/features/f1")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["kind"] == "event"
        # T-VN-05: provider raw passthrough(``payload``)는 공개 detail에서 벗겨진다.
        assert body["data"]["detail"] == {"event_kind": "festival"}
        assert "payload" not in body["data"]["detail"]
        assert body["data"]["updated_at"] == "2026-05-29T00:00:00+09:00"
        assert body["data"]["row_revision"] == 7
        assert r.headers["ETag"] == '"7"'
        assert body["data"]["curations"] == []
        # T-VN-05: raw observation lineage는 공개 detail에서 제거됐다.
        assert "observations" not in body["data"]
        assert "duration_ms" in body["meta"]
        # 공개 응답 schema는 raw/infra/dedup 전용 필드를 노출하지 않는다.
        assert "created_at" not in body["data"]
        assert "coord_5179_srid" not in body["data"]
        assert "parent_feature_id" not in body["data"]
        assert "sibling_group_id" not in body["data"]

        cached = client.get(
            "/v1/features/f1",
            headers={
                "Origin": "http://localhost:12705",
                "If-None-Match": '"7"',
            },
        )
        assert cached.status_code == 304
        assert cached.headers["ETag"] == '"7"'
        assert cached.headers["Access-Control-Allow-Origin"] == (
            "http://localhost:12705"
        )
        assert "etag" in cached.headers["Access-Control-Expose-Headers"].casefold()
        assert cached.content == b""

        malformed = client.get(
            "/v1/features/f1",
            headers={"If-None-Match": 'W/"7"'},
        )
        assert malformed.status_code == 422
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_mois_place_detail_strips_raw_provider_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MOIS 인허가 place의 공개 detail은 provider raw subset(``payload``)을 감춘다.

    T-VN-05(F-3): providers/mois.py PlaceDetail.payload의 mng_no/status_code/
    detail_status_*/opn_authority_code/title/epsg5174가 공개 표면에 새면 안 된다.
    typed 공개-안전 필드(place_kind/phones/facility_info/license_date)는 유지한다.
    """
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    row = {
        "feature_id": "mois:1",
        "kind": "place",
        "name": "관광식당",
        "category": "07010100",
        "lon": 127.0,
        "lat": 37.5,
        "address": {"road": "서울"},
        "detail": {
            "feature_id": "mois:1",
            "place_kind": "license_place",
            "phones": ["02-000-0000"],
            "facility_info": {"seats": 40},
            "license_date": "2020-01-01",
            "payload": {
                "mng_no": "MNG-123",
                "status_code": "01",
                "status_name": "영업중",
                "detail_status_code": "13",
                "detail_status_name": "영업중",
                "opn_authority_code": "3210000",
                "title": "내부 원문 제목",
                "epsg5174": {"x": 1.0, "y": 2.0},
            },
        },
        "urls": {},
        "legal_dong_code": None,
        "sido_code": "11",
        "sigungu_code": "11110",
        "marker_icon": "restaurant",
        "marker_color": "P-07",
        "status": "active",
        "row_revision": 3,
        "updated_at": "2026-05-29T00:00:00+09:00",
        "deleted_at": None,
    }

    async def _get_row(_session: Any, _fid: str) -> dict[str, Any]:
        return row

    async def _curations(
        _session: Any, *, feature_ids: list[str], public_only: bool
    ) -> dict[str, tuple[Any, ...]]:
        return {}

    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_row", _get_row)
    monkeypatch.setattr(
        features_mod.curation_repo,
        "list_curation_items_by_feature_ids",
        _curations,
    )

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/v1/features/mois:1")
        assert r.status_code == 200
        detail = r.json()["data"]["detail"]
        # provider raw subset은 통째로 사라진다.
        assert "payload" not in detail
        serialized = str(r.json())
        for raw_key in (
            "mng_no",
            "status_code",
            "detail_status_code",
            "opn_authority_code",
            "epsg5174",
        ):
            assert raw_key not in serialized
        # typed 공개-안전 필드는 유지된다.
        assert detail["place_kind"] == "license_place"
        assert detail["facility_info"] == {"seats": 40}
        assert detail["license_date"] == "2020-01-01"
        assert "observations" not in r.json()["data"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_area_contained_features_maps_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    area_row = {
        "feature_id": "area1",
        "kind": "area",
        "name": "국립공원",
        "category": "03000000",
        "lon": 127.0,
        "lat": 37.5,
        "area_square_meters": 12345.0,
        "address": {},
        "detail": {},
        "urls": {},
        "legal_dong_code": None,
        "sido_code": None,
        "sigungu_code": None,
        "marker_icon": None,
        "marker_color": None,
        "status": "active",
        "updated_at": "2026-05-29T00:00:00+09:00",
        "deleted_at": None,
    }
    contained_rows = [
        {
            "feature_id": "place1",
            "kind": "place",
            "name": "포함 장소",
            "category": "01000000",
            "lon": 127.01,
            "lat": 37.51,
            "marker_icon": "star",
            "marker_color": "P-03",
            "status": "active",
        }
    ]

    async def _get_row(_session: Any, _fid: str) -> dict[str, Any]:
        return area_row

    async def _contained(_session: Any, **kw: Any) -> list[dict[str, Any]]:
        assert kw["feature_id"] == "area1"
        assert kw["limit"] == 51
        return contained_rows

    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_row", _get_row)
    monkeypatch.setattr(
        features_mod.feature_repo,
        "features_contained_in_area",
        _contained,
    )

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get(
            "/v1/features/area1/contained-features",
            params={"page_size": 51},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["area_square_meters"] == 12345.0
        assert body["data"]["items"][0]["feature_id"] == "place1"
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_area_contained_features_rejects_non_area(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _get_row(_session: Any, _fid: str) -> dict[str, Any]:
        return {"feature_id": "place1", "kind": "place", "deleted_at": None}

    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_row", _get_row)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/v1/features/place1/contained-features")
        assert r.status_code == 422
        assert "area feature" in r.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_features_batch_returns_items_and_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    row = {
        "feature_id": "f1",
        "kind": "event",
        "name": "축제",
        "category": "01000000",
        "lon": 126.92,
        "lat": 37.52,
        "coord_5179_srid": 5179,
        "address": {"road": "서울"},
        "detail": {"event_kind": "festival", "payload": {"raw_source_field": "x"}},
        "urls": {},
        "raw_refs": [],
        "legal_dong_code": None,
        "sido_code": "11",
        "sigungu_code": "11560",
        "marker_icon": "star",
        "marker_color": "P-11",
        "status": "active",
        "row_revision": 9,
        "parent_feature_id": None,
        "sibling_group_id": None,
        "created_at": "2026-05-29T00:00:00+09:00",
        "updated_at": "2026-05-29T00:00:00+09:00",
        "deleted_at": None,
    }

    async def _get_rows(_session: Any, feature_ids: list[str]) -> dict[str, dict[str, Any]]:
        assert feature_ids == ["f1", "missing"]
        return {"f1": row}

    async def _curations(
        _session: Any, *, feature_ids: list[str], public_only: bool
    ) -> dict[str, tuple[Any, ...]]:
        assert feature_ids == ["f1", "missing"]
        assert public_only is True
        return {}

    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_rows_by_ids", _get_rows)
    monkeypatch.setattr(
        features_mod.curation_repo,
        "list_curation_items_by_feature_ids",
        _curations,
    )

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.post(
            "/v1/features/batch",
            json={"feature_ids": ["f1", "missing", "f1"]},
        )
        assert r.status_code == 200
        body = r.json()
        found = body["data"]["found"]["f1"]
        assert found["name"] == "축제"
        assert found["row_revision"] == 9
        assert "coord_5179_srid" not in found
        assert "parent_feature_id" not in found
        assert "sibling_group_id" not in found
        assert found["curations"] == []
        # T-VN-05: service batch는 고정 typed payload — raw lineage/payload 없음.
        assert "observations" not in found
        assert "payload" not in found["detail"]
        assert body["data"]["missing"] == ["missing"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_features_batch_reports_ended_or_non_latest_notice_as_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _get_rows(_session: Any, feature_ids: list[str]) -> dict[str, dict[str, Any]]:
        assert feature_ids == ["notice-old"]
        return {
            "notice-old": {
                "feature_id": "notice-old",
                "kind": "notice",
                "status": "active",
                "deleted_at": None,
            }
        }

    async def _public_ids(_session: Any, feature_ids: list[str]) -> set[str]:
        assert feature_ids == ["notice-old"]
        return set()

    async def _empty(_session: Any, *args: Any, **kwargs: Any) -> dict[str, tuple[Any, ...]]:
        return {}

    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_rows_by_ids", _get_rows)
    monkeypatch.setattr(
        features_mod.feature_repo,
        "public_active_notice_feature_ids",
        _public_ids,
    )
    monkeypatch.setattr(
        features_mod.curation_repo,
        "list_curation_items_by_feature_ids",
        _empty,
    )

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.post(
            "/v1/features/batch",
            json={"feature_ids": ["notice-old"]},
        )
        assert r.status_code == 200
        assert r.json()["data"] == {"found": {}, "missing": ["notice-old"]}
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_search_features_maps_page_and_requires_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra.feature_repo import FeatureSearchPage, FeatureSearchRow

    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _search(_session: Any, **_kw: Any) -> FeatureSearchPage:
        assert _kw["q"] == "경복궁"
        assert _kw["page_size"] == 50
        assert _kw["include_total"] is True
        assert isinstance(_kw["cursor_signing_key"], bytes)
        assert len(_kw["cursor_signing_key"]) >= 32
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
        r = client.get(
            "/v1/features/search",
            params={"q": "경복궁", "include_total": "true"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["items"][0]["feature_id"] == "f1"
        assert body["meta"]["page"] == {
            "page_size": 50,
            "next_cursor": None,
            "total": 1,
        }
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_search_features_omits_total_without_count_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra.feature_repo import FeatureSearchPage

    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _search(_session: Any, **kwargs: Any) -> FeatureSearchPage:
        assert kwargs["include_total"] is False
        return FeatureSearchPage(items=(), total_count=None, next_cursor=None)

    monkeypatch.setattr(features_mod.feature_repo, "search_features", _search)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        response = client.get("/v1/features/search", params={"q": "경복궁"})
        assert response.status_code == 200
        assert response.json()["meta"]["page"]["total"] is None
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            FeatureSearchCursorInvalidError("invalid"),
            "FEATURE_SEARCH_CURSOR_INVALID",
        ),
        (
            FeatureSearchCursorVersionUnsupportedError("unsupported"),
            "FEATURE_SEARCH_CURSOR_VERSION_UNSUPPORTED",
        ),
        (
            FeatureSearchCursorTamperedError("tampered"),
            "FEATURE_SEARCH_CURSOR_TAMPERED",
        ),
        (
            FeatureSearchCursorQueryMismatchError("mismatch"),
            "CURSOR_QUERY_MISMATCH",
        ),
    ],
)
def test_search_features_maps_typed_cursor_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_code: str,
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _search(_session: Any, **_kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(features_mod.feature_repo, "search_features", _search)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        response = client.get(
            "/v1/features/search",
            params={"q": "경복궁", "cursor": "opaque"},
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == expected_code
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_search_features_rejects_partial_bbox(
    client: TestClient,
) -> None:
    # bbox는 4개(min_lon/min_lat/max_lon/max_lat) 모두 지정해야 한다 (T-214e).
    r = client.get(
        "/v1/features/search",
        params={"min_lon": 127, "min_lat": 37, "max_lon": 126},
    )
    assert r.status_code == 422
    assert "bbox" in r.json()["detail"]


@pytest.mark.unit
def test_search_features_rejects_missing_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _search(_session: Any, **_kw: Any) -> None:
        raise ValueError("q 또는 bbox 중 하나는 필요합니다")

    monkeypatch.setattr(features_mod.feature_repo, "search_features", _search)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/v1/features/search")
        assert r.status_code == 422
        assert "q 또는 bbox" in r.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()
