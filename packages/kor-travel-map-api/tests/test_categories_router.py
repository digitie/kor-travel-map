"""``GET /categories`` 라우터 테스트 (T-213f).

정적 카탈로그 경로는 DB를 쓰지 않지만 ``Depends(get_session)``는 해소되므로,
``get_session``을 fake로 override해 DB 없이 검증한다. counts 경로는
``feature_repo.category_feature_counts``를 monkeypatch한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings()))


def _override_session(client: TestClient) -> None:
    from kortravelmap.api.db import get_session

    async def _fake() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake


@pytest.mark.unit
def test_categories_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/categories" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "CategoriesResponse" in schemas
    assert "CategorySummary" in schemas


@pytest.mark.unit
def test_categories_static_returns_full_catalog(client: TestClient) -> None:
    _override_session(client)
    try:
        r = client.get("/v1/categories")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["include_counts"] is False
        assert len(body["data"]["items"]) == 144
        item = body["data"]["items"][0]
        assert {"code", "depth", "label", "path", "maki_icon", "is_active"} <= set(item)
        assert item["db_feature_count"] is None
        assert item["db_active"] is None
        codes = {i["code"] for i in body["data"]["items"]}
        assert "00000000" in codes  # sentinel 포함
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_categories_include_counts_merges_db(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.db import get_session
    from kortravelmap.api.routers import categories as cat_mod

    async def _fake_counts(_session: Any, *, active_only: bool = False) -> dict[str, int]:
        return {"01070100": 5}

    monkeypatch.setattr(cat_mod.feature_repo, "category_feature_counts", _fake_counts)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/v1/categories", params={"include_counts": "true"})
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["include_counts"] is True
        by_code = {i["code"]: i for i in body["data"]["items"]}
        assert by_code["01070100"]["db_feature_count"] == 5
        assert by_code["01070100"]["db_active"] is True
        other = next(c for c in by_code if c != "01070100")
        assert by_code[other]["db_feature_count"] == 0
        assert by_code[other]["db_active"] is False
    finally:
        client.app.dependency_overrides.clear()
