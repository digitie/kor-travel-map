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


def _expected_uuid(feature_id: str) -> str:
    from kortravelmap.core.ids import feature_uuid_from_legacy

    return str(feature_uuid_from_legacy(feature_id))


def _patch_resolved_identity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    feature_id: str | None = None,
) -> None:
    """T-VN-32B 경계 alias 해석을 mock — 형식 계약(422)은 실제 검증을 태운다.

    ``feature_id``가 주어지면 어떤 참조든 그 legacy id로 해석(UUID 참조 시나리오),
    없으면 참조 문자열 자신을 legacy id로 해석한다.
    """
    from kortravelmap.infra import feature_identity

    async def _resolve(_session: Any, ref: str) -> feature_identity.FeatureIdentity:
        feature_identity.validate_feature_ref(ref)
        resolved = feature_id if feature_id is not None else ref
        return feature_identity.FeatureIdentity(
            feature_id=resolved,
            feature_uuid=_expected_uuid(resolved),
        )

    monkeypatch.setattr(feature_identity, "resolve_feature_identity", _resolve)


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
    assert "/v1/features/weather/batch" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "FeatureSummary" in schemas
    assert "FeaturePriceResponse" in schemas
    assert "FeaturesInBboxResponse" in schemas
    assert "FeatureDetailResponse" in schemas
    assert "FeatureDetailEnvelopeResponse" in schemas
    assert "FeatureBatchResponse" in schemas
    assert "WeatherBatchResponse" in schemas
    assert "FeatureSearchResponse" in schemas
    assert "FeaturesNearbyResponse" in schemas
    batch_responses = spec["paths"]["/v1/features/batch"]["post"]["responses"]
    assert "503" in batch_responses
    assert (
        batch_responses["503"]["content"]["application/problem+json"]["schema"]["$ref"]
        == "#/components/schemas/ProblemDetail"
    )


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

    _patch_resolved_identity(monkeypatch)
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

    async def _public_identities(
        _session: Any, feature_ids: list[str]
    ) -> dict[str, str]:
        assert feature_ids == ["notice-old"]
        return {}

    _patch_resolved_identity(monkeypatch)
    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_row", _get_row)
    monkeypatch.setattr(
        features_mod.feature_repo,
        "public_active_notice_feature_identities",
        _public_identities,
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
            "feature_uuid": _expected_uuid("f1"),
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
        # T-VN-32B additive — repo row의 UUID 정본이 응답에 병행 노출된다.
        assert body["data"]["items"][0]["feature_uuid"] == _expected_uuid("f1")
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

    _patch_resolved_identity(monkeypatch)
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
        # T-VN-32B additive — UUID 정본 병행 노출 (feature_id는 legacy 유지).
        assert body["data"]["feature_id"] == "f1"
        assert body["data"]["feature_uuid"] == _expected_uuid("f1")
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
def test_get_feature_accepts_uuid_ref_via_boundary_resolution(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-VN-32B 경계 alias 해석 — canonical UUID 참조도 같은 detail로 해석된다.

    경계에서 UUID → legacy 정본 키로 해석한 뒤 내부 조회는 legacy 키로만 한다.
    응답 ``feature_id``는 legacy 유지(값 전환은 T-VN-32C), ``feature_uuid`` 병행.
    """
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    row = {
        "feature_id": "f1",
        "kind": "place",
        "name": "장소",
        "category": "01010100",
        "lon": 126.97,
        "lat": 37.56,
        "address": {},
        "detail": {},
        "urls": {},
        "legal_dong_code": None,
        "sido_code": None,
        "sigungu_code": None,
        "marker_icon": None,
        "marker_color": None,
        "status": "active",
        "row_revision": 3,
        "updated_at": "2026-08-04T00:00:00+09:00",
        "deleted_at": None,
    }
    requested_ids: list[str] = []

    async def _get_row(_session: Any, feature_id: str) -> dict[str, Any]:
        requested_ids.append(feature_id)
        return row

    async def _curations(
        _session: Any, *, feature_ids: list[str], public_only: bool
    ) -> dict[str, tuple[Any, ...]]:
        assert feature_ids == ["f1"]
        return {}

    _patch_resolved_identity(monkeypatch, feature_id="f1")
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
        r = client.get(f"/v1/features/{_expected_uuid('f1')}")
        assert r.status_code == 200
        # 내부 전달은 해석된 legacy 정본 키.
        assert requested_ids == ["f1"]
        body = r.json()
        assert body["data"]["feature_id"] == "f1"
        assert body["data"]["feature_uuid"] == _expected_uuid("f1")
        assert r.headers["ETag"] == '"3"'
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_feature_ref_format_error_maps_to_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """형식 오류 참조(공백 패딩·길이 초과)는 DB 해석 전에 422다 (T-VN-32B)."""
    from kortravelmap.api.db import get_session

    _patch_resolved_identity(monkeypatch)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        padded = client.get("/v1/features/%20f1")
        assert padded.status_code == 422

        overlong = client.get("/v1/features/" + "x" * 257)
        assert overlong.status_code == 422
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

    _patch_resolved_identity(monkeypatch)
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
def test_features_batch_returns_exhaustive_typed_items(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra.feature_repo import FeatureBatchItemRow

    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _get_items(
        _session: Any,
        items: tuple[tuple[str, int | None], ...],
    ) -> tuple[FeatureBatchItemRow, ...]:
        assert items == (
            ("found", None),
            ("retired", None),
            ("suppressed", None),
            ("missing", None),
            ("unchanged", 17),
        )
        return (
            FeatureBatchItemRow(
                feature_id="found",
                state="found",
                row_revision=9,
                trip_card={
                    "feature_id": "found",
                    "kind": "event",
                    "name": "축제",
                    "category": "01000000",
                    "lon": 126.92,
                    "lat": 37.52,
                    "address": {"road": "서울"},
                    "marker_icon": "star",
                    "marker_color": "P-11",
                },
                feature_uuid=_expected_uuid("found"),
            ),
            FeatureBatchItemRow(
                feature_id="retired",
                state="retired",
                row_revision=10,
                trip_card=None,
                feature_uuid=_expected_uuid("retired"),
            ),
            FeatureBatchItemRow(
                feature_id="suppressed",
                state="suppressed",
                row_revision=11,
                trip_card=None,
                feature_uuid=_expected_uuid("suppressed"),
            ),
            FeatureBatchItemRow(
                feature_id="missing",
                state="missing",
                row_revision=None,
                trip_card=None,
            ),
            FeatureBatchItemRow(
                feature_id="unchanged",
                state="unchanged",
                row_revision=17,
                trip_card=None,
                feature_uuid=_expected_uuid("unchanged"),
            ),
        )

    monkeypatch.setattr(features_mod.feature_repo, "get_service_feature_batch_items", _get_items)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.post(
            "/v1/features/batch",
            json={
                "items": [
                    {"feature_id": "found"},
                    {"feature_id": "retired"},
                    {"feature_id": "suppressed"},
                    {"feature_id": "missing"},
                    {"feature_id": "unchanged", "known_row_revision": 17},
                ]
            },
        )
        assert r.status_code == 200
        items = r.json()["data"]["items"]
        assert [item["state"] for item in items] == [
            "found",
            "retired",
            "suppressed",
            "missing",
            "unchanged",
        ]
        # T-VN-32B additive — 상태별 item에 feature_uuid 병행 노출(missing 제외).
        assert items[0] == {
            "state": "found",
            "feature_id": "found",
            "feature_uuid": _expected_uuid("found"),
            "row_revision": 9,
            "trip_card": {
                "feature_id": "found",
                "kind": "event",
                "name": "축제",
                "category": "01000000",
                "lon": 126.92,
                "lat": 37.52,
                "address": {"road": "서울"},
                "marker_icon": "star",
                "marker_color": "P-11",
            },
        }
        assert items[1] == {
            "state": "retired",
            "feature_id": "retired",
            "feature_uuid": _expected_uuid("retired"),
            "row_revision": 10,
        }
        assert items[2] == {
            "state": "suppressed",
            "feature_id": "suppressed",
            "feature_uuid": _expected_uuid("suppressed"),
            "row_revision": 11,
        }
        assert items[3] == {"state": "missing", "feature_id": "missing"}
        assert items[4] == {
            "state": "unchanged",
            "feature_id": "unchanged",
            "feature_uuid": _expected_uuid("unchanged"),
            "row_revision": 17,
        }
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_features_batch_rejects_duplicate_ids_before_db(
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/features/batch",
        json={"items": [{"feature_id": "same"}, {"feature_id": "same"}]},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_features_batch_maps_database_failure_to_service_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import OperationalError

    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    async def _get_items(
        _session: Any,
        _items: tuple[tuple[str, int | None], ...],
    ) -> None:
        raise OperationalError("SELECT feature batch", {}, OSError("database unavailable"))

    monkeypatch.setattr(features_mod.feature_repo, "get_service_feature_batch_items", _get_items)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        response = client.post(
            "/v1/features/batch",
            json={"items": [{"feature_id": "unavailable"}]},
        )
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "FEATURE_BATCH_UNAVAILABLE"
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("revision", "expected_status"),
    [
        (9_223_372_036_854_775_807, 200),
        (9_223_372_036_854_775_808, 422),
    ],
)
def test_features_batch_bounds_known_revision_to_postgres_bigint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    revision: int,
    expected_status: int,
) -> None:
    from kortravelmap.infra.feature_repo import FeatureBatchItemRow

    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import features as features_mod

    called = False

    async def _get_items(
        _session: Any,
        items: tuple[tuple[str, int | None], ...],
    ) -> tuple[FeatureBatchItemRow, ...]:
        nonlocal called
        called = True
        assert items == (("boundary", 9_223_372_036_854_775_807),)
        return (
            FeatureBatchItemRow(
                feature_id="boundary",
                state="unchanged",
                row_revision=9_223_372_036_854_775_807,
                trip_card=None,
            ),
        )

    monkeypatch.setattr(features_mod.feature_repo, "get_service_feature_batch_items", _get_items)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        response = client.post(
            "/v1/features/batch",
            json={
                "items": [
                    {
                        "feature_id": "boundary",
                        "known_row_revision": revision,
                    }
                ]
            },
        )
        assert response.status_code == expected_status
        assert called is (expected_status == 200)
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
