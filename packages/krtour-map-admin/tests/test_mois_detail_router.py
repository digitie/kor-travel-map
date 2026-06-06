"""``test_mois_detail_router`` — MOIS on-demand 상세 라우터 (Step D, ADR-035/004).

DB 무관 단위 테스트 (``get_primary_source_detail`` monkeypatch):
- 라우터 마운트 + OpenAPI 노출
- ``features_routes_enabled=False`` 시 unmount
- 미적재 license_id → 404
- 적재된 license_id → 상세 매핑 + 프로세스 캐시 히트(2회차 cached=True)

실 DB round-trip은 메인 lib 통합 테스트(``feature_repo.get_primary_source_detail``)에서.
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


@pytest.fixture(autouse=True)
def _clear_cache() -> AsyncIterator[None]:
    from krtour.map_admin.routers.mois_detail import clear_detail_cache

    clear_detail_cache()
    yield
    clear_detail_cache()


@pytest.mark.unit
def test_mois_detail_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/debug/mois-license/{license_id}" in spec["paths"]
    assert "MoisLicenseDetailResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_mois_detail_unmounts_when_features_disabled() -> None:
    app = create_app(AdminSettings(features_routes_enabled=False))
    c = TestClient(app)
    assert c.get("/debug/mois-license/x").status_code == 404
    spec = c.get("/openapi.json").json()
    assert "/debug/mois-license/{license_id}" not in spec["paths"]


@pytest.mark.unit
def test_mois_detail_404_when_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import mois_detail as mod

    async def _none(_session: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(mod.feature_repo, "get_primary_source_detail", _none)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/debug/mois-license/general_restaurants::nope")
        assert r.status_code == 404
        assert "nope" in r.json()["error"]["message"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_mois_detail_returns_and_caches(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.db import get_session
    from krtour.map_admin.routers import mois_detail as mod

    calls = {"n": 0}
    detail = {
        "feature_id": "f_x",
        "name": "한식당 가나다",
        "category": "02010100",
        "status": "active",
        "lon": 126.97,
        "lat": 37.56,
        "address": {"road": "서울 종로구"},
        "detail": {"place_kind": "restaurant"},
        "raw_data": {"BPLC_NM": "한식당 가나다", "mng_no": "A1"},
    }

    async def _detail(_session: Any, **_kw: Any) -> dict[str, Any]:
        calls["n"] += 1
        return detail

    monkeypatch.setattr(mod.feature_repo, "get_primary_source_detail", _detail)

    async def _fake_session() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake_session
    try:
        lid = "general_restaurants::A1"
        r1 = client.get(f"/debug/mois-license/{lid}")
        assert r1.status_code == 200
        body = r1.json()
        assert body["data"]["license_id"] == lid
        assert body["data"]["feature_id"] == "f_x"
        assert body["data"]["raw"]["BPLC_NM"] == "한식당 가나다"
        assert body["meta"]["cached"] is False

        # 2회차 — 프로세스 캐시 히트 (DB 재조회 없음).
        r2 = client.get(f"/debug/mois-license/{lid}")
        assert r2.status_code == 200
        assert r2.json()["meta"]["cached"] is True
        assert calls["n"] == 1  # repo는 1회만 호출
    finally:
        client.app.dependency_overrides.clear()
