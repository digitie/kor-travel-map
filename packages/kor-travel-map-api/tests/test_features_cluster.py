"""``GET /features/in-bounds`` 클러스터링 (T-213c) — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kortravelmap.api.app import create_app
from kortravelmap.api.response import ClusterMeta
from kortravelmap.api.settings import ApiSettings

_BBOX = {"min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings()))


def _fake_session(client: TestClient) -> None:
    from kortravelmap.api.db import get_session

    async def _fs() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fs


@pytest.mark.unit
def test_cluster_meta_requires_shared_enum_contract() -> None:
    """cluster meta가 있으면 현재 단위는 필수이고 drill-down은 enum|null이다."""
    schema = ClusterMeta.model_json_schema()

    assert set(schema["required"]) == {"cluster_unit", "drill_down_unit"}
    assert schema["properties"]["cluster_unit"]["enum"] == [
        "sido",
        "sigungu",
        "eupmyeondong",
    ]
    assert schema["properties"]["drill_down_unit"]["anyOf"] == [
        {"enum": ["sido", "sigungu", "eupmyeondong"], "type": "string"},
        {"type": "null"},
    ]
    assert ClusterMeta(
        cluster_unit="eupmyeondong",
        drill_down_unit=None,
    ).model_dump() == {
        "cluster_unit": "eupmyeondong",
        "drill_down_unit": None,
    }
    with pytest.raises(ValidationError):
        ClusterMeta.model_validate({"drill_down_unit": "sigungu"})
    with pytest.raises(ValidationError):
        ClusterMeta.model_validate(
            {"cluster_unit": "sido", "drill_down_unit": "ri"}
        )


@pytest.mark.unit
def test_in_bounds_cluster_unit_returns_clusters(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    async def _cluster(_s: Any, **kw: Any) -> list[dict[str, Any]]:
        assert kw["cluster_unit"] == "sigungu"
        return [
            {"cluster_key": "11110", "feature_count": 3, "lon": 127.0, "lat": 37.5}
        ]

    monkeypatch.setattr(mod.feature_repo, "cluster_features_in_bbox", _cluster)
    _fake_session(client)
    try:
        r = client.get("/v1/features/in-bounds", params={**_BBOX, "cluster_unit": "sigungu"})
        assert r.status_code == 200
        body = r.json()
        d = body["data"]
        assert body["meta"]["cluster"] == {
            "cluster_unit": "sigungu",
            "drill_down_unit": "eupmyeondong",
        }
        assert d["mode"] == "clusters"
        assert d["items"] == []
        assert d["clusters"][0]["cluster_key"] == "11110"
        assert d["clusters"][0]["feature_count"] == 3
        # 지도 완결성 계약 (ADR-073 D-9-2): truncated/coverage/drill-down 명시.
        assert d["truncated"] is False
        assert "cluster_unit" not in d
        assert "drill_down_unit" not in d
        assert d["coverage"] == {"returned": 1, "limit": 1000}
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_in_bounds_cluster_truncation_is_explicit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cluster 결과가 max_items에서 잘리면 truncated=true로 명시된다 (F-8)."""
    from kortravelmap.api.routers import features as mod

    captured: dict[str, Any] = {}

    async def _cluster(_s: Any, **kw: Any) -> list[dict[str, Any]]:
        captured["limit"] = kw["limit"]
        # max_items+1 요청에 대해 limit개(=2) 초과분까지 돌려준다.
        return [
            {"cluster_key": f"111{i:02d}", "feature_count": 5 - i, "lon": 127.0, "lat": 37.5}
            for i in range(kw["limit"])
        ]

    monkeypatch.setattr(mod.feature_repo, "cluster_features_in_bbox", _cluster)
    _fake_session(client)
    try:
        r = client.get(
            "/v1/features/in-bounds",
            params={**_BBOX, "cluster_unit": "sido", "max_items": 2},
        )
        assert r.status_code == 200
        d = r.json()["data"]
        # router가 max_items+1로 조회해 초과 여부를 판정한다.
        assert captured["limit"] == 3
        assert d["mode"] == "clusters"
        assert d["truncated"] is True
        assert len(d["clusters"]) == 2  # 상위 max_items개만 반환.
        assert r.json()["meta"]["cluster"] == {
            "cluster_unit": "sido",
            "drill_down_unit": "sigungu",
        }
        assert d["coverage"] == {"returned": 2, "limit": 2}
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_in_bounds_zoom_derives_cluster_unit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    captured: dict[str, Any] = {}

    async def _cluster(_s: Any, **kw: Any) -> list[dict[str, Any]]:
        captured["unit"] = kw["cluster_unit"]
        return []

    monkeypatch.setattr(mod.feature_repo, "cluster_features_in_bbox", _cluster)
    _fake_session(client)
    try:
        r = client.get("/v1/features/in-bounds", params={**_BBOX, "zoom": 9})
        assert r.status_code == 200
        assert captured["unit"] == "sigungu"  # zoom 9 → sigungu
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_in_bounds_high_zoom_returns_individual_features(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.core.ids import feature_uuid_from_legacy

    from kortravelmap.api.routers import features as mod

    f1_uuid = str(feature_uuid_from_legacy("f1"))

    async def _bbox(_s: Any, **_kw: Any) -> list[dict[str, Any]]:
        assert _kw["price_stale_hide_days"] is None
        return [
            {
                "feature_id": "f1", "kind": "place", "name": "x", "category": "06020000",
                "feature_uuid": f1_uuid,
                # `FeatureSummary`는 상태 축을 아예 싣지 않는다(extra="forbid").
                # 공개 요약에서 상태는 노출 대상이 아니라 **필터 조건**이므로,
                # legacy `status`를 3축으로 바꾸는 것이 아니라 빼는 것이 맞다.
                "lon": 126.9, "lat": 37.5, "marker_icon": None, "marker_color": None,
            }
        ]

    monkeypatch.setattr(mod.feature_repo, "features_in_bbox", _bbox)
    _fake_session(client)
    try:
        r = client.get("/v1/features/in-bounds", params={**_BBOX, "zoom": 16})
        assert r.status_code == 200
        body = r.json()
        d = body["data"]
        assert body["meta"]["cluster"] is None  # zoom≥14 → 개별
        assert d["mode"] == "items"
        # T-VN-32C 값 전환 — 응답 feature_id 값은 stub row의 UUID 정본.
        assert d["items"][0]["feature_id"] == f1_uuid
        assert d["clusters"] == []
        # items 모드 완결성 계약: truncated/coverage 명시, cluster metadata 없음.
        assert d["truncated"] is False
        assert "cluster_unit" not in d
        assert "drill_down_unit" not in d
        assert d["coverage"] == {"returned": 1, "limit": 1000}
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_in_bounds_invalid_cluster_unit_422(client: TestClient) -> None:
    r = client.get("/v1/features/in-bounds", params={**_BBOX, "cluster_unit": "bogus"})
    assert r.status_code == 422
