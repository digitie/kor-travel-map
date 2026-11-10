"""장소 속성(ADR-121 §7) HTTP 표면 단위 테스트 — DB 없이 repo를 stub한다.

- ``GET /v1/place-attributes`` 공개 catalog
- 공개 목록·in-bounds·검색·주변(좌표·target)과 admin in-bounds의 ``attribute`` 검증
  (개수 상한·모르는 코드·공개 경로의 ``admin_only`` 코드 → 422)과 repo 전달
- 응답의 ``attribute_codes``·상세 ``attributes``·속성 digest ETag
- ``GET /v1/admin/theme-attach-decisions`` 읽기 전용 목록
- OpenAPI: service 표면(``/v1/service/admin-features``)과 admin 목록은 ``attribute``가 없다
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.feature_repo import (
    FeatureSearchPage,
    FeatureSearchRow,
    NearbyFeaturePage,
    NearbyFeatureRow,
)
from kortravelmap.infra.place_attribute_repo import (
    PlaceAttribute,
    ThemeAttachDecision,
    ThemeAttachDecisionPage,
    place_attribute_digest,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_read_snapshot_session, get_session
from kortravelmap.api.settings import ApiSettings

ADMIN_ACTOR = "admin:place-attribute-test"
ADMIN_PROXY_SECRET = "place-attribute-admin-proxy-secret-00000000000000"

_CATALOG: tuple[PlaceAttribute, ...] = (
    PlaceAttribute("pet_friendly", "반려동물 동반 가능", "companion", "public", 10),
    PlaceAttribute("barrier_free", "무장애 편의", "accessibility", "public", 30),
    PlaceAttribute("internal_review", "내부 검토", "companion", "admin_only", 90),
)
_BBOX = {"min_lon": 126.9, "min_lat": 37.5, "max_lon": 127.0, "max_lat": 37.6}


def _feature_uuid(label: str) -> str:
    from kortravelmap.core.ids import feature_uuid_from_legacy

    return str(feature_uuid_from_legacy(label))


async def _fake_session() -> AsyncIterator[Any]:
    yield object()


def _override_sessions(app: Any) -> None:
    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_read_snapshot_session] = _fake_session


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    _override_sessions(app)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def admin_client() -> Iterator[TestClient]:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=ADMIN_PROXY_SECRET,
            public_api_key_required=False,
            service_token=None,
            vworld_api_key=None,
        )
    )
    _override_sessions(app)
    try:
        yield TestClient(
            app,
            client=("127.0.0.1", 50000),
            headers={
                "X-Kor-Travel-Map-Admin-Proxy-Secret": ADMIN_PROXY_SECRET,
                "X-Kor-Travel-Map-Actor": ADMIN_ACTOR,
            },
        )
    finally:
        app.dependency_overrides.clear()


def _patch_catalog(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """catalog 조회를 stub하고 ``public_only`` 인자를 기록한다(공개면 admin_only를 뺀다)."""
    from kortravelmap.infra import place_attribute_repo

    calls: list[bool] = []

    async def _list(_session: Any, *, public_only: bool = False) -> tuple[PlaceAttribute, ...]:
        calls.append(public_only)
        return tuple(item for item in _CATALOG if item.is_public or not public_only)

    monkeypatch.setattr(place_attribute_repo, "list_place_attributes", _list)
    return calls


def _bbox_row(label: str, codes: list[str]) -> dict[str, Any]:
    return {
        "feature_id": label,
        "feature_uuid": _feature_uuid(label),
        "kind": "place",
        "name": "장소",
        "category": "01010100",
        "lon": 126.97,
        "lat": 37.56,
        "marker_icon": "star",
        "marker_color": "P-03",
        "price_summary": None,
        "attribute_codes": codes,
    }


def _nearby_row(label: str, codes: tuple[str, ...]) -> NearbyFeatureRow:
    return NearbyFeatureRow(
        feature_id=label,
        kind="place",
        name="주변 장소",
        category="01010100",
        lon=126.97,
        lat=37.56,
        distance_m=12.5,
        primary_provider="python-visitkorea-api",
        primary_dataset_key="visitkorea_places",
        last_updated_at=datetime(2026, 11, 10, tzinfo=UTC),
        feature_uuid=_feature_uuid(label),
        attribute_codes=codes,
    )


# ── catalog ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_place_attribute_catalog_lists_public_codes_in_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_catalog(monkeypatch)
    response = client.get("/v1/place-attributes")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"] == [
        {"code": "pet_friendly", "label": "반려동물 동반 가능", "group": "companion",
         "sort_order": 10},
        {"code": "barrier_free", "label": "무장애 편의", "group": "accessibility",
         "sort_order": 30},
    ]
    assert "duration_ms" in body["meta"]
    assert calls == [True]


# ── 검증 (422) ───────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/features", _BBOX),
        ("/v1/features/in-bounds", _BBOX),
        ("/v1/features/search", {"q": "카페"}),
        ("/v1/features/nearby", {"lon": 126.97, "lat": 37.56, "radius_m": 500}),
    ],
)
def test_public_attribute_filter_rejects_more_than_five_before_db(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    params: dict[str, Any],
) -> None:
    calls = _patch_catalog(monkeypatch)
    query = [*params.items(), *(("attribute", f"code_{index}") for index in range(6))]
    response = client.get(path, params=query)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["details"]["max_items"] == 5
    # 개수 상한은 catalog를 읽기 전에 막는다.
    assert calls == []


@pytest.mark.unit
@pytest.mark.parametrize("code", ["no_such_code", "internal_review"])
@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/features", _BBOX),
        ("/v1/features/in-bounds", {**_BBOX, "zoom": 7}),
        ("/v1/features/search", {"q": "카페"}),
        ("/v1/features/nearby", {"lon": 126.97, "lat": 37.56, "radius_m": 500}),
    ],
)
def test_public_attribute_filter_rejects_unknown_and_admin_only_codes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    params: dict[str, Any],
    code: str,
) -> None:
    """공개 경로는 ``admin_only`` 코드를 모르는 코드와 똑같이 거부한다(존재를 드러내지 않는다)."""
    calls = _patch_catalog(monkeypatch)
    response = client.get(path, params=[*params.items(), ("attribute", code)])
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["unknown_attributes"] == [code]
    assert calls == [True]


@pytest.mark.unit
def test_nearby_by_target_rejects_admin_only_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as features_mod

    _patch_catalog(monkeypatch)

    async def _target(_session: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            target_id="t-1", external_system="external-app", target_key="poi-1",
            lon=126.97, lat=37.56,
        )

    monkeypatch.setattr(features_mod, "get_poi_cache_target_by_key", _target)
    response = client.get(
        "/v1/features/nearby/by-target",
        params=[
            ("external_system", "external-app"),
            ("target_key", "poi-1"),
            ("attribute", "internal_review"),
        ],
    )
    assert response.status_code == 422
    assert response.json()["details"]["unknown_attributes"] == ["internal_review"]


# ── repo 전달과 응답 ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_bbox_list_passes_sorted_attributes_and_returns_codes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as features_mod

    _patch_catalog(monkeypatch)
    seen: dict[str, Any] = {}

    async def _bbox(_session: Any, **kwargs: Any) -> list[dict[str, Any]]:
        seen.update(kwargs)
        return [_bbox_row("f1", ["barrier_free", "pet_friendly"])]

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)
    response = client.get(
        "/v1/features",
        params=[
            *_BBOX.items(),
            ("attribute", "pet_friendly"),
            ("attribute", "barrier_free"),
            ("attribute", "pet_friendly"),
        ],
    )
    assert response.status_code == 200, response.text
    # 정렬·중복 제거된 코드가 AND 필터로 내려간다.
    assert seen["attributes"] == ["barrier_free", "pet_friendly"]
    item = response.json()["data"]["items"][0]
    assert item["attribute_codes"] == ["barrier_free", "pet_friendly"]


@pytest.mark.unit
def test_bbox_list_without_attribute_skips_catalog_and_passes_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as features_mod

    calls = _patch_catalog(monkeypatch)
    seen: dict[str, Any] = {}

    async def _bbox(_session: Any, **kwargs: Any) -> list[dict[str, Any]]:
        seen.update(kwargs)
        return [_bbox_row("f1", [])]

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)
    response = client.get("/v1/features", params=_BBOX)
    assert response.status_code == 200
    assert seen["attributes"] is None
    assert calls == []
    assert response.json()["data"]["items"][0]["attribute_codes"] == []


@pytest.mark.unit
def test_in_bounds_passes_attributes_to_both_modes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as features_mod

    _patch_catalog(monkeypatch)
    seen: dict[str, Any] = {}

    async def _bbox(_session: Any, **kwargs: Any) -> list[dict[str, Any]]:
        seen["items"] = kwargs["attributes"]
        return [_bbox_row("f1", ["pet_friendly"])]

    async def _clusters(_session: Any, **kwargs: Any) -> list[dict[str, Any]]:
        seen["clusters"] = kwargs["attributes"]
        return [{"cluster_key": "11", "feature_count": 1, "lon": 126.97, "lat": 37.56}]

    monkeypatch.setattr(features_mod.feature_repo, "features_in_bbox", _bbox)
    monkeypatch.setattr(features_mod.feature_repo, "cluster_features_in_bbox", _clusters)
    items = client.get(
        "/v1/features/in-bounds", params=[*_BBOX.items(), ("attribute", "pet_friendly")]
    )
    clusters = client.get(
        "/v1/features/in-bounds",
        params=[*_BBOX.items(), ("zoom", "7"), ("attribute", "pet_friendly")],
    )
    assert items.status_code == 200
    assert clusters.status_code == 200
    assert seen == {"items": ["pet_friendly"], "clusters": ["pet_friendly"]}
    assert items.json()["data"]["items"][0]["attribute_codes"] == ["pet_friendly"]
    assert clusters.json()["data"]["mode"] == "clusters"


@pytest.mark.unit
def test_search_passes_attributes_and_returns_codes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as features_mod

    _patch_catalog(monkeypatch)
    seen: dict[str, Any] = {}

    async def _search(_session: Any, **kwargs: Any) -> FeatureSearchPage:
        seen.update(kwargs)
        return FeatureSearchPage(
            items=(
                FeatureSearchRow(
                    feature_id="f1", kind="place", name="카페", category="05020000",
                    lon=126.97, lat=37.56, marker_icon=None, marker_color=None,
                    score=1.0, feature_uuid=_feature_uuid("f1"), rank=0,
                    attribute_codes=("pet_friendly",),
                ),
            ),
            next_cursor=None,
        )

    monkeypatch.setattr(features_mod.feature_repo, "search_features", _search)
    response = client.get(
        "/v1/features/search", params=[("q", "카페"), ("attribute", "pet_friendly")]
    )
    assert response.status_code == 200, response.text
    assert seen["attributes"] == ["pet_friendly"]
    assert response.json()["data"]["items"][0]["attribute_codes"] == ["pet_friendly"]


@pytest.mark.unit
def test_nearby_routes_pass_attributes_and_return_codes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as features_mod

    _patch_catalog(monkeypatch)
    seen: dict[str, Any] = {}

    async def _nearby(_session: Any, **kwargs: Any) -> NearbyFeaturePage:
        seen["coord"] = kwargs["attributes"]
        return NearbyFeaturePage(items=(_nearby_row("n1", ("barrier_free",)),), next_cursor=None)

    async def _nearby_target(_session: Any, **kwargs: Any) -> NearbyFeaturePage:
        seen["target"] = kwargs["attributes"]
        return NearbyFeaturePage(items=(_nearby_row("n2", ("barrier_free",)),), next_cursor=None)

    async def _target(_session: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            target_id="t-1", external_system="external-app", target_key="poi-1",
            lon=126.97, lat=37.56,
        )

    monkeypatch.setattr(features_mod.feature_repo, "features_nearby", _nearby)
    monkeypatch.setattr(
        features_mod.feature_repo, "features_nearby_poi_cache_target", _nearby_target
    )
    monkeypatch.setattr(features_mod, "get_poi_cache_target_by_key", _target)
    coord = client.get(
        "/v1/features/nearby",
        params=[("lon", 126.97), ("lat", 37.56), ("radius_m", 500), ("attribute", "barrier_free")],
    )
    target = client.get(
        "/v1/features/nearby/by-target",
        params=[
            ("external_system", "external-app"),
            ("target_key", "poi-1"),
            ("attribute", "barrier_free"),
        ],
    )
    assert coord.status_code == 200
    assert target.status_code == 200
    assert seen == {"coord": ["barrier_free"], "target": ["barrier_free"]}
    assert coord.json()["data"]["items"][0]["attribute_codes"] == ["barrier_free"]
    assert target.json()["data"]["items"][0]["attribute_codes"] == ["barrier_free"]


# ── 상세: attributes + digest ETag ──────────────────────────────────────


def _detail_row() -> dict[str, Any]:
    return {
        "feature_id": "f1",
        "feature_uuid": _feature_uuid("f1"),
        "kind": "place",
        "name": "도서관",
        "category": "01000000",
        "lon": 126.92,
        "lat": 37.52,
        "address": {},
        "detail": {},
        "urls": {},
        "legal_dong_code": None,
        "sido_code": "11",
        "sigungu_code": "11560",
        "marker_icon": "star",
        "marker_color": "P-11",
        "row_revision": 7,
        "updated_at": "2026-11-10T00:00:00+09:00",
    }


def _patch_detail(
    monkeypatch: pytest.MonkeyPatch, attributes: tuple[PlaceAttribute, ...]
) -> None:
    from kortravelmap.infra import feature_identity

    from kortravelmap.api.routers import features as features_mod

    async def _resolve(_session: Any, ref: str) -> feature_identity.FeatureIdentity:
        feature_identity.validate_feature_ref(ref)
        return feature_identity.FeatureIdentity(feature_id=ref, feature_uuid=_feature_uuid(ref))

    async def _row(_session: Any, _feature_id: str) -> dict[str, Any]:
        return _detail_row()

    async def _curations(_session: Any, **_kwargs: Any) -> dict[str, tuple[Any, ...]]:
        return {}

    async def _attributes(
        _session: Any, feature_id: str, *, public_only: bool
    ) -> tuple[PlaceAttribute, ...]:
        assert feature_id == "f1"
        assert public_only is True
        return attributes

    monkeypatch.setattr(feature_identity, "resolve_feature_identity", _resolve)
    monkeypatch.setattr(features_mod.feature_repo, "get_public_feature_row", _row)
    monkeypatch.setattr(
        features_mod.curation_repo, "list_curation_items_by_feature_ids", _curations
    )
    monkeypatch.setattr(
        features_mod.place_attribute_repo, "list_feature_place_attributes", _attributes
    )


@pytest.mark.unit
def test_detail_carries_attributes_and_digest_etag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_detail(monkeypatch, (_CATALOG[0], _CATALOG[1]))
    response = client.get("/v1/features/f1")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["attributes"] == [
        {"code": "pet_friendly", "label": "반려동물 동반 가능", "group": "companion"},
        {"code": "barrier_free", "label": "무장애 편의", "group": "accessibility"},
    ]
    # digest는 코드·라벨·묶음·순서를 모두 접는다.
    # 라벨만 바뀌어도 ETag가 바뀐다.
    rows = "\n".join(
        f"{item.code}\t{item.label}\t{item.group}\t{item.sort_order}"
        for item in sorted(
            (_CATALOG[0], _CATALOG[1]), key=lambda item: (item.sort_order, item.code)
        )
    )
    digest = hashlib.sha256(rows.encode("utf-8")).hexdigest()[:16]
    etag = f'"7-{digest}"'
    assert response.headers["ETag"] == etag
    relabeled = replace(_CATALOG[0], label="반려동물 동반")
    assert place_attribute_digest((relabeled, _CATALOG[1])) != digest

    cached = client.get("/v1/features/f1", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.headers["ETag"] == etag
    # 속성이 바뀌기 전의(혹은 속성 없는) revision-only ETag는 더 이상 일치하지 않는다.
    stale = client.get("/v1/features/f1", headers={"If-None-Match": '"7"'})
    assert stale.status_code == 200
    malformed = client.get("/v1/features/f1", headers={"If-None-Match": '"7-xyz"'})
    assert malformed.status_code == 422


@pytest.mark.unit
def test_detail_without_attributes_keeps_revision_only_etag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_detail(monkeypatch, ())
    response = client.get("/v1/features/f1")
    assert response.status_code == 200
    assert response.headers["ETag"] == '"7"'
    assert response.json()["data"]["attributes"] == []
    assert client.get("/v1/features/f1", headers={"If-None-Match": '"7"'}).status_code == 304


# ── admin ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_admin_in_bounds_accepts_admin_only_code(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    calls = _patch_catalog(monkeypatch)
    seen: dict[str, Any] = {}

    async def _items(_session: Any, **kwargs: Any) -> list[dict[str, Any]]:
        seen.update(kwargs)
        return [
            {
                "feature_id": "a1",
                "feature_uuid": _feature_uuid("a1"),
                "kind": "place",
                "name": "검토 대상",
                "category": "01070300",
                "lon": 126.97,
                "lat": 37.57,
                "marker_icon": None,
                "marker_color": None,
                "lifecycle_state": "active",
                "publication_state": "draft",
                "quality_state": "valid",
                "attribute_codes": ["internal_review"],
            }
        ]

    monkeypatch.setattr(router_mod, "admin_features_in_bbox", _items)
    response = admin_client.get(
        "/v1/admin/features/in-bounds",
        params=[*_BBOX.items(), ("attribute", "internal_review")],
    )
    assert response.status_code == 200, response.text
    assert calls == [False]
    assert seen["attributes"] == ["internal_review"]
    assert response.json()["data"]["items"][0]["attribute_codes"] == ["internal_review"]


@pytest.mark.unit
def test_admin_in_bounds_rejects_unknown_code(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_catalog(monkeypatch)
    response = admin_client.get(
        "/v1/admin/features/in-bounds",
        params=[*_BBOX.items(), ("attribute", "no_such_code")],
    )
    assert response.status_code == 422
    assert response.json()["details"]["unknown_attributes"] == ["no_such_code"]


@pytest.mark.unit
def test_admin_theme_attach_decisions_lists_page(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra import place_attribute_repo

    seen: dict[str, Any] = {}
    decided_at = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)

    async def _list(_session: Any, **kwargs: Any) -> ThemeAttachDecisionPage:
        seen.update(kwargs)
        return ThemeAttachDecisionPage(
            items=(
                ThemeAttachDecision(
                    provider_dataset_id=7,
                    provider="python-mcst-api",
                    dataset_key="mcst_barrier_free_places_csv",
                    natural_key="row-1",
                    state="matched",
                    target_feature_id=_feature_uuid("f1"),
                    rule_version="theme-attach-v1",
                    evidence={"candidates": [{"distance_m": 12.0, "tier": 1}]},
                    decided_at=decided_at,
                ),
            ),
            next_cursor="next-cursor",
        )

    monkeypatch.setattr(place_attribute_repo, "list_theme_attach_decisions", _list)
    response = admin_client.get(
        "/v1/admin/theme-attach-decisions",
        params={
            "dataset_key": "mcst_barrier_free_places_csv",
            "state": "matched",
            "page_size": 20,
        },
    )
    assert response.status_code == 200, response.text
    assert seen == {
        "dataset_key": "mcst_barrier_free_places_csv",
        "state": "matched",
        "page_size": 20,
        "cursor": None,
    }
    body = response.json()
    assert body["data"]["items"] == [
        {
            "provider": "python-mcst-api",
            "dataset_key": "mcst_barrier_free_places_csv",
            "natural_key": "row-1",
            "state": "matched",
            "target_feature_id": _feature_uuid("f1"),
            "rule_version": "theme-attach-v1",
            "evidence": {"candidates": [{"distance_m": 12.0, "tier": 1}]},
            "decided_at": "2026-11-10T03:00:00Z",
        }
    ]
    assert body["meta"]["page"]["next_cursor"] == "next-cursor"


@pytest.mark.unit
@pytest.mark.parametrize(
    "params",
    [{"state": "bogus"}, {"page_size": 201}, {"page_size": 0}],
)
def test_admin_theme_attach_decisions_rejects_bad_query(
    admin_client: TestClient, params: dict[str, Any]
) -> None:
    response = admin_client.get("/v1/admin/theme-attach-decisions", params=params)
    assert response.status_code == 422


@pytest.mark.unit
def test_admin_theme_attach_decisions_maps_cursor_error_to_422(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra import place_attribute_repo

    async def _list(_session: Any, **_kwargs: Any) -> ThemeAttachDecisionPage:
        raise place_attribute_repo.ThemeAttachDecisionCursorError("invalid cursor")

    monkeypatch.setattr(place_attribute_repo, "list_theme_attach_decisions", _list)
    response = admin_client.get(
        "/v1/admin/theme-attach-decisions", params={"cursor": "not-a-cursor"}
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_theme_attach_decisions_requires_admin_proxy() -> None:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=ADMIN_PROXY_SECRET,
            public_api_key_required=False,
            service_token=None,
            vworld_api_key=None,
        )
    )
    response = TestClient(app).get("/v1/admin/theme-attach-decisions")
    assert response.status_code in {401, 403}


# ── OpenAPI 표면 ─────────────────────────────────────────────────────────


def _parameter_names(spec: dict[str, Any], path: str) -> set[str]:
    return {item["name"] for item in spec["paths"][path]["get"].get("parameters", [])}


@pytest.mark.unit
def test_openapi_exposes_attribute_filter_on_listed_reads_only(client: TestClient) -> None:
    spec = client.app.openapi()
    for path in (
        "/v1/features",
        "/v1/features/in-bounds",
        "/v1/features/search",
        "/v1/features/nearby",
        "/v1/features/nearby/by-target",
        "/v1/admin/features/in-bounds",
    ):
        assert "attribute" in _parameter_names(spec, path), path
    # admin 목록은 PinVi service 표면과 handler·DTO를 공유한다 — service 계약 불변(§7.3).
    assert "attribute" not in _parameter_names(spec, "/v1/admin/features")
    assert "attribute" not in _parameter_names(spec, "/v1/service/admin-features")
    schemas = spec["components"]["schemas"]
    assert "attribute_codes" in schemas["FeatureSummary"]["properties"]
    assert "attribute_codes" in schemas["NearbyFeatureSummary"]["properties"]
    assert "attributes" in schemas["FeatureDetailResponse"]["properties"]
    assert "attribute_codes" not in schemas["AdminFeatureRecord"]["properties"]
    assert "attribute_codes" not in schemas["FeatureTripCard"]["properties"]
    assert "/v1/place-attributes" in spec["paths"]
    assert "/v1/admin/theme-attach-decisions" in spec["paths"]
