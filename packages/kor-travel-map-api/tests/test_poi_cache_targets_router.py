"""POI/cache target admin API와 by-target feature 조회 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from kortravelmap.infra.feature_repo import NearbyFeaturePage, NearbyFeatureRow
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    PoiCacheTargetConflict,
    PoiCacheTargetDeleteResult,
    PoiCacheTargetPage,
)
from starlette.requests import Request

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings

TARGET_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


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
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            service_token=None,
            admin_destructive_enabled=True,
            public_api_key_required=False,
        )
    )

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _target(*, target_key: str = "poi-1", lock_version: int = 7) -> PoiCacheTarget:
    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    return PoiCacheTarget(
        target_id=TARGET_ID,
        lock_version=lock_version,
        external_system="external-app",
        target_key=target_key,
        name="서울시청",
        lon=126.978,
        lat=37.5665,
        coord_precision_digits=6,
        coord_key="126.978000:37.566500:p6",
        radius_km=5.0,
        scope_mode="center_radius",
        update_enabled=True,
        refresh_policy="provider_default",
        provider_overrides={},
        metadata={"external_poi_id": target_key},
        last_seen_at=now,
        last_requested_at=None,
        last_refreshed_at=None,
        last_failed_at=None,
        next_eligible_refresh_at=None,
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )


def _nearby_expected_uuid(feature_id: str) -> str:
    """결정적 mock uuid — 테스트 편의 규약이지 저장 계약(0083 비파생 v7)이 아니다."""
    from kortravelmap.core.ids import feature_uuid_from_legacy

    return str(feature_uuid_from_legacy(feature_id))


def _nearby_row() -> NearbyFeatureRow:
    now = datetime(2026, 6, 3, 12, 5, tzinfo=UTC)
    return NearbyFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="주변 주유소",
        category="06020000",
        lon=126.98,
        lat=37.56,
        distance_m=320.5,
        primary_provider="python-opinet-api",
        primary_dataset_key="opinet_stations",
        last_updated_at=now,
        feature_uuid=_nearby_expected_uuid("feature-1"),
    )


@pytest.mark.unit
def test_poi_cache_target_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/poi-cache-targets" in spec["paths"]
    assert "/v1/admin/poi-cache-targets/{external_system}/{target_key}" in spec["paths"]
    assert "/v1/features/nearby/by-target" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "PoiCacheTargetUpsertRequest" in schemas
    assert "FeaturesNearbyByTargetResponse" in schemas
    assert set(schemas["PoiCacheTargetListResponse"]["properties"]) == {"data", "meta"}
    assert "next_cursor" not in schemas["PoiCacheTargetListData"]["properties"]
    upsert_props = schemas["PoiCacheTargetUpsertRequest"]["properties"]
    assert "metadata" in upsert_props
    assert "metadata_" not in upsert_props
    assert upsert_props["provider_overrides"]["maxProperties"] == 64
    path_parameters = spec["paths"][
        "/v1/admin/poi-cache-targets/{external_system}/{target_key}"
    ]["put"]["parameters"]
    external_system = next(
        item for item in path_parameters if item["name"] == "external_system"
    )
    assert external_system["schema"]["maxLength"] == 112
    item_path = spec["paths"][
        "/v1/admin/poi-cache-targets/{external_system}/{target_key}"
    ]
    delete_operation = item_path["delete"]
    if_match = next(
        item
        for item in delete_operation["parameters"]
        if item["name"] == "If-Match"
    )
    assert if_match["in"] == "header"
    assert if_match["required"] is True
    assert {"403", "404", "412", "422", "428"} <= set(
        delete_operation["responses"]
    )
    for method in ("get", "put", "delete"):
        assert "ETag" in item_path[method]["responses"]["200"]["headers"]
    mutation_meta = schemas["PoiCacheTargetMutationMeta"]
    assert "dataset_projection_revision" in mutation_meta["required"]
    assert "entity_tag" in schemas["PoiCacheTargetRecord"]["required"]


@pytest.mark.unit
def test_put_poi_cache_target_rejects_impossible_external_system_before_transaction(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.put(
        f"/v1/admin/poi-cache-targets/{'x' * 113}/poi-1",
        json={"coord": {"lon": 126.978, "lat": 37.5665}},
    )

    assert response.status_code == 422
    assert session.begin_count == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "body", "headers"),
    [
        (
            "PUT",
            "/v1/admin/poi-cache-targets/pinvi/poi-1",
            {"coord": {"lon": 126.978, "lat": 37.5665}},
            {},
        ),
        (
            "DELETE",
            "/v1/admin/poi-cache-targets/pinvi/poi-1",
            None,
            {"If-Match": f'"{TARGET_ID}:7"'},
        ),
    ],
)
def test_admin_target_writer_rejects_relay_owned_pinvi_before_transaction(
    client: TestClient,
    session: _FakeSession,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    headers: dict[str, str],
) -> None:
    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 409
    assert response.json()["code"] == "CACHE_TARGET_SOURCE_PROTOCOL_REQUIRED"
    assert session.begin_count == 0


@pytest.mark.unit
def test_put_pinvi_target_409_documents_source_protocol_rejection() -> None:
    spec = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            service_token=None,
            admin_destructive_enabled=True,
            public_api_key_required=False,
        )
    ).openapi()
    description = spec["paths"]["/v1/admin/poi-cache-targets/{external_system}/{target_key}"][
        "put"
    ]["responses"]["409"]["description"]

    assert "좌표 conflict" in description
    assert "source protocol" in description


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "params"),
    [
        ("GET", "/v1/admin/poi-cache-targets/external-app/poi:e\u0301", None),
        ("DELETE", "/v1/admin/poi-cache-targets/external-app/poi:e\u0301", None),
        ("GET", "/v1/admin/poi-cache-targets", {"external_system": " pinvi "}),
    ],
)
def test_admin_cache_target_reads_reject_noncanonical_identity_before_repository(
    client: TestClient,
    session: _FakeSession,
    method: str,
    path: str,
    params: dict[str, str] | None,
) -> None:
    response = client.request(
        method,
        path,
        params=params,
        headers={"If-Match": f'"{TARGET_ID}:7"'},
    )

    assert response.status_code == 422
    assert session.begin_count == 0


@pytest.mark.unit
def test_put_poi_cache_target_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _upsert(_session: Any, **kwargs: Any) -> PoiCacheTarget:
        assert kwargs["external_system"] == "external-app"
        assert kwargs["target_key"] == "poi-1"
        assert kwargs["lon"] == 126.978
        assert kwargs["on_conflict"] == "reject"
        assert kwargs["provider_overrides"] == {
            "python-kma-api:kma_weather_alerts": {
                "targeted_policy": "allow_targeted",
                "min_interval_seconds": 300,
            }
        }
        assert kwargs["metadata"] == {
            "external_poi_id": "poi-1",
            "labels": ["city"],
        }
        return _target()

    async def _revision(_session: Any) -> int:
        return 41

    monkeypatch.setattr(router_mod, "upsert_poi_cache_target", _upsert)
    monkeypatch.setattr(router_mod, "get_dataset_projection_revision", _revision)

    response = client.put(
        "/v1/admin/poi-cache-targets/external-app/poi-1",
        json={
            "coord": {"lon": 126.978, "lat": 37.5665},
            "radius_km": 5.0,
            "provider_overrides": {
                "python-kma-api:kma_weather_alerts": {
                    "targeted_policy": "allow_targeted",
                    "min_interval_seconds": 300,
                }
            },
            "metadata": {"external_poi_id": "poi-1", "labels": ["city"]},
        },
    )

    assert response.status_code == 200
    assert response.headers["etag"] == f'"{TARGET_ID}:7"'
    assert response.json()["data"]["entity_tag"] == response.headers["etag"]
    assert response.json()["data"]["coord_key"] == "126.978000:37.566500:p6"
    assert response.json()["data"]["metadata"] == {"external_poi_id": "poi-1"}
    assert response.json()["meta"]["dataset_projection_revision"] == 41
    assert session.begin_count == 1


@pytest.mark.unit
@pytest.mark.parametrize("legacy_key", ["pinvi_poi_id", "tripmate_poi_id"])
def test_put_poi_cache_target_accepts_legacy_external_poi_id_aliases(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    legacy_key: str,
) -> None:
    # #546 — 구 키(pinvi_poi_id/tripmate_poi_id)는 422 대신 external_poi_id로 정규화.
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _upsert(_session: Any, **kwargs: Any) -> PoiCacheTarget:
        # validation_alias로 정규화되어 repo에는 external_poi_id로만 전달.
        assert kwargs["metadata"] == {"external_poi_id": "poi-legacy"}
        return _target(target_key="poi-legacy")

    async def _revision(_session: Any) -> int:
        return 42

    monkeypatch.setattr(router_mod, "upsert_poi_cache_target", _upsert)
    monkeypatch.setattr(router_mod, "get_dataset_projection_revision", _revision)

    response = client.put(
        "/v1/admin/poi-cache-targets/external-app/poi-legacy",
        json={
            "coord": {"lon": 126.978, "lat": 37.5665},
            "metadata": {legacy_key: "poi-legacy"},
        },
    )

    assert response.status_code == 200
    # 응답(직렬화)은 external_poi_id만 노출 (구 키 echo 안 함).
    assert response.json()["data"]["metadata"] == {"external_poi_id": "poi-legacy"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        {"metadata": {"unknown": True}},
        {"provider_overrides": {"python-a-api": {"unknown": True}}},
        {
            "provider_overrides": {
                f"python-provider-{index}": {"targeted_policy": "allow_targeted"}
                for index in range(65)
            }
        },
    ],
)
def test_put_poi_cache_target_rejects_unbounded_payloads_before_transaction(
    client: TestClient,
    session: _FakeSession,
    payload: dict[str, Any],
) -> None:
    body: dict[str, Any] = {"coord": {"lon": 126.978, "lat": 37.5665}}
    body.update(payload)

    response = client.put("/v1/admin/poi-cache-targets/external-app/poi-1", json=body)

    assert response.status_code == 422
    assert session.begin_count == 0


@pytest.mark.unit
def test_put_poi_cache_target_conflict_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _conflict(_session: Any, **_kwargs: Any) -> PoiCacheTarget:
        raise PoiCacheTargetConflict("coord conflict")

    monkeypatch.setattr(router_mod, "upsert_poi_cache_target", _conflict)

    response = client.put(
        "/v1/admin/poi-cache-targets/external-app/poi-1",
        json={"coord": {"lon": 126.978, "lat": 37.5665}},
    )

    assert response.status_code == 409
    assert "coord conflict" in response.json()["detail"]


@pytest.mark.unit
def test_list_poi_cache_targets_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _list(_session: Any, **kwargs: Any) -> PoiCacheTargetPage:
        assert kwargs["external_system"] == "external-app"
        assert kwargs["update_enabled"] is True
        assert kwargs["include_deleted"] is False
        assert kwargs["limit"] == 25
        assert kwargs["cursor"] == "cursor-1"
        return PoiCacheTargetPage(items=(_target(),), next_cursor="cursor-2")

    monkeypatch.setattr(router_mod, "list_poi_cache_targets", _list)

    response = client.get(
        "/v1/admin/poi-cache-targets",
        params={
            "external_system": "external-app",
            "update_enabled": "true",
            "page_size": "25",
            "cursor": "cursor-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "cursor-2",
        "total": None,
    }
    assert body["data"]["items"][0]["target_key"] == "poi-1"
    assert body["data"]["items"][0]["entity_tag"] == f'"{TARGET_ID}:7"'


@pytest.mark.unit
def test_list_poi_cache_targets_rejects_invalid_cursor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _list(_session: Any, **_kwargs: Any) -> PoiCacheTargetPage:
        raise ValueError("invalid poi cache target cursor")

    monkeypatch.setattr(router_mod, "list_poi_cache_targets", _list)

    response = client.get("/v1/admin/poi-cache-targets", params={"cursor": "bad"})

    assert response.status_code == 422
    assert "invalid poi cache target cursor" in response.json()["detail"]


@pytest.mark.unit
def test_get_poi_cache_target_404_when_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _missing(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(router_mod, "get_poi_cache_target_by_key", _missing)

    response = client.get("/v1/admin/poi-cache-targets/external-app/missing")

    assert response.status_code == 404


@pytest.mark.unit
def test_get_poi_cache_target_returns_strong_target_etag(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _get(_session: Any, **_kwargs: Any) -> PoiCacheTarget:
        return _target()

    monkeypatch.setattr(router_mod, "get_poi_cache_target_by_key", _get)

    response = client.get("/v1/admin/poi-cache-targets/external-app/poi-1")

    assert response.status_code == 200
    assert response.headers["etag"] == f'"{TARGET_ID}:7"'
    assert response.json()["data"]["entity_tag"] == response.headers["etag"]
    assert "dataset_projection_revision" not in response.json()["meta"]


@pytest.mark.unit
def test_delete_poi_cache_target_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _delete(_session: Any, **kwargs: Any) -> PoiCacheTargetDeleteResult:
        assert kwargs["external_system"] == "external-app"
        assert kwargs["target_key"] == "poi-1"
        assert kwargs["expected_target_id"] == TARGET_ID
        assert kwargs["expected_lock_version"] == 7
        return PoiCacheTargetDeleteResult(
            status="deleted",
            target=_target(lock_version=8),
        )

    async def _revision(_session: Any) -> int:
        return 43

    monkeypatch.setattr(router_mod, "delete_poi_cache_target", _delete)
    monkeypatch.setattr(router_mod, "get_dataset_projection_revision", _revision)

    response = client.delete(
        "/v1/admin/poi-cache-targets/external-app/poi-1",
        headers={"If-Match": f'"{TARGET_ID}:7"'},
    )

    assert response.status_code == 200
    assert response.headers["etag"] == f'"{TARGET_ID}:8"'
    assert response.json()["data"]["target_id"] == TARGET_ID
    assert response.json()["data"]["entity_tag"] == response.headers["etag"]
    assert response.json()["meta"]["dataset_projection_revision"] == 43
    assert session.begin_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("header", "expected_status"),
    [
        (None, 428),
        ("*", 422),
        (f'W/"{TARGET_ID}:7"', 422),
        (
            f'"{TARGET_ID}:7", "22222222-2222-4222-8222-222222222222:1"',
            422,
        ),
        ('"not-a-uuid"', 422),
        (f'"{TARGET_ID}"', 422),
        (f'"{TARGET_ID}:0"', 422),
        (f'"{TARGET_ID}:01"', 422),
        (f'"{TARGET_ID.upper()}:7"', 422),
        (f'"{TARGET_ID}:9223372036854775808"', 422),
        (f' "{TARGET_ID}:7"', 422),
    ],
)
def test_delete_poi_cache_target_rejects_missing_or_invalid_if_match(
    client: TestClient,
    session: _FakeSession,
    header: str | None,
    expected_status: int,
) -> None:
    headers = {} if header is None else {"If-Match": header}

    response = client.delete(
        "/v1/admin/poi-cache-targets/external-app/poi-1",
        headers=headers,
    )

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert session.begin_count == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            f'"{TARGET_ID}:7"',
            '"22222222-2222-4222-8222-222222222222:1"',
        ),
        (
            '"22222222-2222-4222-8222-222222222222:1"',
            f'"{TARGET_ID}:7"',
        ),
    ],
)
def test_expected_target_identity_rejects_duplicate_raw_if_match_lines(
    first: str,
    second: str,
) -> None:
    from kortravelmap.api.routers.poi_cache_targets import (
        _expected_target_identity,
    )

    raw_headers = [
        (b"if-match", first.encode("ascii")),
        (b"if-match", second.encode("ascii")),
    ]
    request = Request(
        {
            "type": "http",
            "method": "DELETE",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": raw_headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
        }
    )

    assert request.headers.getlist("if-match") == [first, second]
    with pytest.raises(HTTPException) as exc_info:
        _expected_target_identity(request)

    assert exc_info.value.status_code == 422


@pytest.mark.unit
@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        (PoiCacheTargetDeleteResult(status="not_found"), 404),
        (PoiCacheTargetDeleteResult(status="precondition_failed"), 412),
    ],
)
def test_delete_poi_cache_target_maps_atomic_precondition_result(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    result: PoiCacheTargetDeleteResult,
    expected_status: int,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _delete(
        _session: Any, **_kwargs: Any
    ) -> PoiCacheTargetDeleteResult:
        return result

    async def _unexpected_revision(_session: Any) -> int:
        raise AssertionError("failed delete must not read a mutation revision receipt")

    monkeypatch.setattr(router_mod, "delete_poi_cache_target", _delete)
    monkeypatch.setattr(
        router_mod,
        "get_dataset_projection_revision",
        _unexpected_revision,
    )

    response = client.delete(
        "/v1/admin/poi-cache-targets/external-app/poi-1",
        headers={"If-Match": f'"{TARGET_ID}:7"'},
    )

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert session.begin_count == 1


@pytest.mark.unit
def test_features_nearby_by_target_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import features as features_mod

    async def _get_target(_session: Any, **kwargs: Any) -> PoiCacheTarget:
        assert kwargs["external_system"] == "external-app"
        assert kwargs["target_key"] == "poi-1"
        return _target()

    async def _nearby(_session: Any, **kwargs: Any) -> NearbyFeaturePage:
        assert kwargs["target_id"] == TARGET_ID
        assert kwargs["radius_km"] == 3.0
        assert kwargs["kinds"] == ["place"]
        assert kwargs["categories"] == ["06020000"]
        assert kwargs["providers"] == ["python-opinet-api"]
        assert kwargs["sort"] == "distance"
        assert kwargs["limit"] == 10
        return NearbyFeaturePage(items=(_nearby_row(),), next_cursor="next")

    monkeypatch.setattr(features_mod, "get_poi_cache_target_by_key", _get_target)
    monkeypatch.setattr(
        features_mod.feature_repo,
        "features_nearby_poi_cache_target",
        _nearby,
    )

    response = client.get(
        "/v1/features/nearby/by-target",
        params=[
            ("external_system", "external-app"),
            ("target_key", "poi-1"),
            ("radius_km", "3.0"),
            ("kind", "place"),
            ("category", "06020000"),
            ("provider", "python-opinet-api"),
            ("page_size", "10"),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["target"]["target_key"] == "poi-1"
    assert set(body["data"]["target"]) == {
        "external_system",
        "target_key",
        "lon",
        "lat",
    }
    assert body["data"]["items"][0]["distance_m"] == 320.5
    # T-VN-32C 값 전환 — 응답 feature_id 값은 stub row의 UUID 정본.
    assert body["data"]["items"][0]["feature_id"] == (
        _nearby_expected_uuid("feature-1")
    )
    assert "primary_provider" not in body["data"]["items"][0]
    assert "primary_dataset_key" not in body["data"]["items"][0]
    assert body["meta"]["page"] == {
        "page_size": 10,
        "next_cursor": "next",
        "total": None,
    }


@pytest.mark.unit
def test_features_nearby_by_target_404_when_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import features as features_mod

    async def _missing(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(features_mod, "get_poi_cache_target_by_key", _missing)

    response = client.get(
        "/v1/features/nearby/by-target",
        params={"external_system": "external-app", "target_key": "missing"},
    )

    assert response.status_code == 404
