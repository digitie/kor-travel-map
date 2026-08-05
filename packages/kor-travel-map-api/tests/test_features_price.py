"""``GET /features/{feature_id}/price`` 라우터 — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.price_repo import PriceCard, PricePoint

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(
        create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    )


def _fake_session(client: TestClient) -> None:
    from kortravelmap.api.db import get_session

    async def _fs() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fs


@pytest.mark.unit
def test_price_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/features/{feature_id}/price" in spec["paths"]
    assert "FeaturePriceResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_price_card_response_maps_current_and_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as mod

    observed_at = datetime(2026, 6, 26, 6, 18, tzinfo=UTC)
    point = PricePoint(
        provider="python-opinet-api",
        price_domain="opinet_gas_station",
        product_key="gasoline",
        product_name="휘발유",
        source_product_key="B027",
        source_product_name="휘발유",
        value_number=Decimal("1820.0"),
        unit="KRW/L",
        observed_at=observed_at,
    )
    card = PriceCard(
        feature_id="f1",
        asof=None,
        current=[point],
        history=[point],
        latest_at=observed_at,
        is_stale=False,
    )

    async def _card(_s: Any, **kw: Any) -> PriceCard:
        assert kw["feature_id"] == "f1"
        assert kw["history_limit"] == 25
        return card

    async def _public_row(_s: Any, feature_id: str) -> dict[str, Any]:
        assert feature_id == "f1"
        return {"feature_id": "f1", "kind": "price", "status": "active"}

    monkeypatch.setattr(mod.price_repo, "build_price_card", _card)
    monkeypatch.setattr(mod.feature_repo, "get_public_feature_row", _public_row)
    _fake_session(client)
    try:
        r = client.get("/v1/features/f1/price?history_limit=25")
        assert r.status_code == 200
        d = r.json()["data"]
        # T-VN-32C 값 전환 — 단건 card 응답의 feature_id는 UUID 정본
        # (경계 해석 identity의 uuid — repo 조회는 위 kw assert대로 legacy 축).
        from kortravelmap.core.ids import feature_uuid_from_legacy

        assert d["feature_id"] == str(feature_uuid_from_legacy("f1"))
        assert d["is_stale"] is False
        assert d["latest_at"] == "2026-06-26T06:18:00Z"
        assert d["current"][0]["product_key"] == "gasoline"
        assert d["current"][0]["value_number"] == 1820.0
        assert d["history"][0]["source_product_key"] == "B027"
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_price_card_404_when_feature_not_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비공개 parent feature의 price payload는 노출되지 않는다 — ADR-067 단일
    공개 projection, F-1 (T-VN-04)."""
    from kortravelmap.api.routers import features as mod

    async def _none(_s: Any, _fid: str) -> None:
        return None

    async def _card_should_not_run(_s: Any, **_kw: Any) -> Any:
        raise AssertionError("build_price_card must not run for non-public feature")

    monkeypatch.setattr(mod.feature_repo, "get_public_feature_row", _none)
    monkeypatch.setattr(mod.price_repo, "build_price_card", _card_should_not_run)
    _fake_session(client)
    try:
        r = client.get("/v1/features/hidden-f/price")
        assert r.status_code == 404
    finally:
        client.app.dependency_overrides.clear()
