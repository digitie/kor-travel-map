"""``/v1/service/feature-alias-maps`` 이관 표면 계약 테스트 (T-VN-32C)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.core.feature_alias_map import FeatureAliasMapRowV1
from kortravelmap.core.ids import feature_uuid_from_legacy
from kortravelmap.infra.feature_alias_map_repo import (
    FeatureAliasMapChecksum,
    FeatureAliasMapIntegrityError,
    FeatureAliasMapPage,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import SERVICE_TOKEN_HEADER
from kortravelmap.api.db import get_session
from kortravelmap.api.routers import feature_alias_maps as alias_maps_mod
from kortravelmap.api.settings import ApiSettings

_SERVICE_TOKEN = "alias-map-service-token-000000000000000000000000"


async def _fake_session() -> AsyncIterator[Any]:
    yield object()


@pytest.fixture
def client() -> TestClient:
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _row(alias: str) -> FeatureAliasMapRowV1:
    """고정 row fixture — uuid는 alias에서 **결정적으로** 만들되 계약은 아니다.

    파생을 쓰는 이유는 테스트가 alias 하나로 기대 uuid를 재계산할 수 있어서지,
    저장 계약이 파생이라서가 아니다. 0083(T-VN-32C)부터 실제 저장값은 비파생
    UUIDv7이고 router는 저장값을 그대로 통과시킨다.
    """
    return FeatureAliasMapRowV1(
        alias=alias,
        feature_uuid=str(feature_uuid_from_legacy(alias)),
        alias_kind="legacy_feature_id",
    )


@pytest.mark.unit
def test_alias_map_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/service/feature-alias-maps" in spec["paths"]
    assert "/v1/service/feature-alias-maps/checksum" in spec["paths"]


@pytest.mark.unit
def test_alias_map_page_exposes_canonical_rows_and_keyset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = (_row("f_global_p_aaaa"), _row("f_global_p_bbbb"))

    async def _fetch(
        _session: Any, *, after_alias: str | None, limit: int
    ) -> FeatureAliasMapPage:
        assert after_alias == "f_global_p_0000"
        assert limit == 2
        return FeatureAliasMapPage(rows=rows, has_more=True)

    monkeypatch.setattr(alias_maps_mod, "fetch_feature_alias_map_page", _fetch)
    response = client.get(
        "/v1/service/feature-alias-maps",
        params={"after_alias": "f_global_p_0000", "limit": 2},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["schema_version"] == "feature-alias-map-v1"
    assert [row["alias"] for row in data["rows"]] == [
        "f_global_p_aaaa",
        "f_global_p_bbbb",
    ]
    # router는 저장소가 준 값을 그대로 통과시킨다 — 기대값은 파생 재계산이
    # 아니라 stub이 돌려준 행 자체다 (0083 이후 저장값은 비파생 v7).
    assert [row["feature_uuid"] for row in data["rows"]] == [
        row.feature_uuid for row in rows
    ]
    assert all(row["alias_kind"] == "legacy_feature_id" for row in data["rows"])
    assert data["has_more"] is True
    assert data["next_after_alias"] == "f_global_p_bbbb"


@pytest.mark.unit
def test_alias_map_last_page_has_no_next_keyset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fetch(
        _session: Any, *, after_alias: str | None, limit: int
    ) -> FeatureAliasMapPage:
        return FeatureAliasMapPage(rows=(_row("f_global_p_zzzz"),), has_more=False)

    monkeypatch.setattr(alias_maps_mod, "fetch_feature_alias_map_page", _fetch)
    data = client.get("/v1/service/feature-alias-maps").json()["data"]
    assert data["has_more"] is False
    assert data["next_after_alias"] is None


@pytest.mark.unit
def test_alias_map_checksum_exposes_count_and_root(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _compute(_session: Any) -> FeatureAliasMapChecksum:
        return FeatureAliasMapChecksum(alias_count=4, merkle_root="ab" * 32)

    monkeypatch.setattr(alias_maps_mod, "compute_feature_alias_map_checksum", _compute)
    response = client.get("/v1/service/feature-alias-maps/checksum")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "schema_version": "feature-alias-map-v1",
        "alias_count": 4,
        "merkle_root": "ab" * 32,
        # 0083 세대 표식 — 이 코드는 파생 미강제 세계에서만 배포된다(리뷰 2 F6).
        "derivation_enforced": False,
    }


@pytest.mark.unit
def test_alias_map_integrity_violation_maps_to_500_fail_close(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _compute(_session: Any) -> FeatureAliasMapChecksum:
        raise FeatureAliasMapIntegrityError("파생 계약 위반")

    async def _fetch(
        _session: Any, *, after_alias: str | None, limit: int
    ) -> FeatureAliasMapPage:
        raise FeatureAliasMapIntegrityError("파생 계약 위반")

    monkeypatch.setattr(alias_maps_mod, "compute_feature_alias_map_checksum", _compute)
    monkeypatch.setattr(alias_maps_mod, "fetch_feature_alias_map_page", _fetch)
    for path in (
        "/v1/service/feature-alias-maps/checksum",
        "/v1/service/feature-alias-maps",
    ):
        response = client.get(path)
        assert response.status_code == 500
        assert response.json()["code"] == "FEATURE_ALIAS_MAP_INTEGRITY"


@pytest.mark.unit
def test_alias_map_query_validation_is_fail_close(client: TestClient) -> None:
    assert (
        client.get("/v1/service/feature-alias-maps", params={"limit": 0}).status_code
        == 422
    )
    assert (
        client.get("/v1/service/feature-alias-maps", params={"limit": 1001}).status_code
        == 422
    )
    assert (
        client.get(
            "/v1/service/feature-alias-maps", params={"after_alias": ""}
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/v1/service/feature-alias-maps", params={"after_alias": "a" * 257}
        ).status_code
        == 422
    )


@pytest.mark.unit
def test_alias_map_requires_service_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiSettings(
            public_api_key_required=False,
            vworld_api_key=None,
            service_token=_SERVICE_TOKEN,
        )
    )
    app.dependency_overrides[get_session] = _fake_session
    client = TestClient(app)

    async def _compute(_session: Any) -> FeatureAliasMapChecksum:
        return FeatureAliasMapChecksum(alias_count=0, merkle_root="00" * 32)

    monkeypatch.setattr(alias_maps_mod, "compute_feature_alias_map_checksum", _compute)
    denied = client.get("/v1/service/feature-alias-maps/checksum")
    assert denied.status_code == 401
    allowed = client.get(
        "/v1/service/feature-alias-maps/checksum",
        headers={SERVICE_TOKEN_HEADER: _SERVICE_TOKEN},
    )
    assert allowed.status_code == 200
