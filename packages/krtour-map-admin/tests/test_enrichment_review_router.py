"""``/v1/admin/enrichment-reviews`` 라우터 단위 테스트 (T-RV-52c)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.admin_feature_repo import (
    EnrichmentReviewPage,
    EnrichmentReviewRow,
)
from krtour.map.infra.enrichment_review_repo import EnrichmentDecisionResult
from krtour.map.infra.feature_repo import EnrichmentLoadResult

from krtour.map_admin.app import create_app
from krtour.map_admin.db import get_session
from krtour.map_admin.settings import AdminSettings


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
    app = create_app(AdminSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _review_row() -> EnrichmentReviewRow:
    now = datetime(2026, 6, 8, tzinfo=UTC)
    return EnrichmentReviewRow(
        review_id="review-1",
        status="pending",
        name_score=82.0,
        target_feature_id="f_festival",
        target_name="서울 봄꽃 축제",
        target_kind="event",
        target_category="01010100",
        target_lon=126.9,
        target_lat=37.5,
        source_provider="python-visitkorea-api",
        source_dataset_key="visitkorea_festival_events",
        source_entity_id="2747929",
        source_name="서울 봄꽃",
        decision_reason=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=now,
    )


@pytest.mark.unit
def test_enrichment_review_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/enrichment-reviews" in spec["paths"]
    assert "/v1/admin/enrichment-reviews/{review_id}" in spec["paths"]
    assert "EnrichmentReviewRecord" in spec["components"]["schemas"]


@pytest.mark.unit
def test_list_enrichment_reviews_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import enrichment_review as router_mod

    async def _list(_session: Any, **kwargs: Any) -> EnrichmentReviewPage:
        assert kwargs["statuses"] == ["pending"]
        assert kwargs["providers"] == ["python-visitkorea-api"]
        assert kwargs["min_score"] == 70
        assert kwargs["page_size"] == 25
        return EnrichmentReviewPage(items=(_review_row(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_enrichment_reviews", _list)

    response = client.get(
        "/v1/admin/enrichment-reviews",
        params={
            "status": "pending",
            "provider": "python-visitkorea-api",
            "min_score": "70",
            "page_size": "25",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["review_id"] == "review-1"
    assert body["data"]["items"][0]["source_name"] == "서울 봄꽃"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "next",
        "total": None,
    }


@pytest.mark.unit
def test_patch_accepted_applies_and_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import enrichment_review as router_mod

    async def _decide(
        _session: Any, review_id: str, decision: str, **kwargs: Any
    ) -> EnrichmentDecisionResult:
        assert review_id == "review-1"
        assert decision == "accepted"
        assert kwargs["reviewed_by"] == "local-admin"
        return EnrichmentDecisionResult(
            review_id="review-1",
            decision="accepted",
            changed=True,
            applied=True,
            load=EnrichmentLoadResult(
                enrichments_total=1,
                source_records_inserted=1,
                source_links_inserted=1,
                source_links_updated=0,
            ),
        )

    monkeypatch.setattr(router_mod, "decide_enrichment_review", _decide)

    response = client.patch(
        "/v1/admin/enrichment-reviews/review-1",
        json={
            "decision": "accepted",
            "decision_reason": "같은 축제",
            "reviewed_by": "local-admin",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is True
    assert data["applied"] is True
    assert data["source_links_inserted"] == 1
    assert session.begin_count == 1


@pytest.mark.unit
def test_patch_reject_does_not_apply(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import enrichment_review as router_mod

    async def _decide(
        _session: Any, _review_id: str, decision: str, **_kwargs: Any
    ) -> EnrichmentDecisionResult:
        return EnrichmentDecisionResult(
            review_id="review-1", decision=decision, changed=True, applied=False
        )

    monkeypatch.setattr(router_mod, "decide_enrichment_review", _decide)

    response = client.patch(
        "/v1/admin/enrichment-reviews/review-1",
        json={"decision": "rejected"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["applied"] is False
    assert data["source_links_inserted"] is None


@pytest.mark.unit
def test_patch_already_reviewed_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import enrichment_review as router_mod

    async def _decide(
        _session: Any, _review_id: str, decision: str, **_kwargs: Any
    ) -> EnrichmentDecisionResult:
        return EnrichmentDecisionResult(
            review_id="review-1", decision=decision, changed=False, applied=False
        )

    monkeypatch.setattr(router_mod, "decide_enrichment_review", _decide)

    response = client.patch(
        "/v1/admin/enrichment-reviews/review-1",
        json={"decision": "accepted"},
    )

    assert response.status_code == 409
    assert "전이 실패" in response.json()["detail"]
