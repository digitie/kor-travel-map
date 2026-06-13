"""``/v1/admin/dedup-reviews`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.admin_feature_repo import (
    DedupFeatureSummary,
    DedupReviewPage,
    DedupReviewRow,
)
from kortravelmap.infra.merge_repo import (
    MergeConflictError,
    MergeError,
    MergeNotFoundError,
    MergeOutcome,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings


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
    app = create_app(ApiSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _review_row() -> DedupReviewRow:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    feature_a = DedupFeatureSummary(
        feature_id="feature-a",
        name="장소 A",
        kind="place",
        category="01070300",
        lon=126.9,
        lat=37.5,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )
    feature_b = DedupFeatureSummary(
        feature_id="feature-b",
        name="장소 B",
        kind="place",
        category="01070300",
        lon=126.9001,
        lat=37.5001,
        provider="python-datagokr-api",
        dataset_key="cultural_festivals",
    )
    return DedupReviewRow(
        review_id="review-1",
        status="pending",
        total_score=90.0,
        name_score=95.0,
        spatial_score=85.0,
        category_score=100.0,
        feature_a=feature_a,
        feature_b=feature_b,
        distance_m=12.5,
        decision_reason="manual_review",
        reviewed_by=None,
        reviewed_at=None,
        created_at=now,
    )


@pytest.mark.unit
def test_dedup_review_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/dedup-reviews" in spec["paths"]
    assert "/v1/admin/dedup-reviews/{review_id}" in spec["paths"]
    assert "DedupReviewRecord" in spec["components"]["schemas"]


@pytest.mark.unit
def test_list_dedup_reviews_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import dedup_review as router_mod

    async def _list(_session: Any, **kwargs: Any) -> DedupReviewPage:
        assert kwargs["statuses"] == ["pending"]
        assert kwargs["providers"] == ["python-mois-api"]
        assert kwargs["min_score"] == 80
        assert kwargs["page_size"] == 25
        return DedupReviewPage(items=(_review_row(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_dedup_reviews", _list)

    response = client.get(
        "/v1/admin/dedup-reviews",
        params={
            "status": "pending",
            "provider": "python-mois-api",
            "min_score": "80",
            "page_size": "25",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["review_id"] == "review-1"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "next",
        "total": None,
    }


@pytest.mark.unit
def test_patch_accepted_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import dedup_review as router_mod

    async def _set(_session: Any, review_id: str, **kwargs: Any) -> bool:
        assert review_id == "review-1"
        assert kwargs["decision"] == "accepted"
        assert kwargs["reviewed_by"] == "local-admin"
        return True

    monkeypatch.setattr(router_mod, "set_dedup_review_decision", _set)

    response = client.patch(
        "/v1/admin/dedup-reviews/review-1",
        json={
            "decision": "accepted",
            "decision_reason": "같은 장소",
            "reviewed_by": "local-admin",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["changed"] is True
    assert session.begin_count == 1


@pytest.mark.unit
def test_patch_merged_uses_advisory_lock(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import dedup_review as router_mod

    seen_lock: list[str] = []

    @asynccontextmanager
    async def _lock(_session: Any, key: str) -> AsyncIterator[None]:
        seen_lock.append(key)
        yield None

    async def _merge(_session: Any, review_id: str, **kwargs: Any) -> MergeOutcome:
        assert review_id == "review-1"
        assert kwargs["master_feature_id"] == "feature-a"
        return MergeOutcome(
            master_feature_id="feature-a",
            loser_feature_id="feature-b",
            source_links_moved=1,
            source_links_dropped=0,
            merge_id="merge-1",
            queue_updated=True,
        )

    monkeypatch.setattr(router_mod, "advisory_lock", _lock)
    monkeypatch.setattr(router_mod, "merge_dedup_review", _merge)

    response = client.patch(
        "/v1/admin/dedup-reviews/review-1",
        json={
            "decision": "merged",
            "master_feature_id": "feature-a",
            "decision_reason": "동일 장소",
            "reviewed_by": "local-admin",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["merge_id"] == "merge-1"
    assert seen_lock == ["dedup-merge:review-1"]
    assert session.begin_count == 1


@pytest.mark.unit
def test_patch_merged_not_found_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import dedup_review as router_mod

    @asynccontextmanager
    async def _lock(_session: Any, _key: str) -> AsyncIterator[None]:
        yield None

    async def _merge(_session: Any, review_id: str, **_kwargs: Any) -> MergeOutcome:
        raise MergeNotFoundError(f"review_id 없음 — {review_id!r}")

    monkeypatch.setattr(router_mod, "advisory_lock", _lock)
    monkeypatch.setattr(router_mod, "merge_dedup_review", _merge)

    response = client.patch(
        "/v1/admin/dedup-reviews/missing",
        json={"decision": "merged", "master_feature_id": "feature-a"},
    )

    assert response.status_code == 404
    assert "review_id 없음" in response.json()["detail"]


@pytest.mark.unit
def test_patch_merged_conflict_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import dedup_review as router_mod

    @asynccontextmanager
    async def _lock(_session: Any, _key: str) -> AsyncIterator[None]:
        yield None

    async def _merge(_session: Any, _review_id: str, **_kwargs: Any) -> MergeOutcome:
        raise MergeConflictError("이미 검토된 후보(status='merged')")

    monkeypatch.setattr(router_mod, "advisory_lock", _lock)
    monkeypatch.setattr(router_mod, "merge_dedup_review", _merge)

    response = client.patch(
        "/v1/admin/dedup-reviews/review-1",
        json={"decision": "merged", "master_feature_id": "feature-a"},
    )

    assert response.status_code == 409
    assert "이미 검토" in response.json()["detail"]


@pytest.mark.unit
def test_patch_merged_unknown_merge_error_hides_internal_message(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import dedup_review as router_mod

    @asynccontextmanager
    async def _lock(_session: Any, _key: str) -> AsyncIterator[None]:
        yield None

    async def _merge(_session: Any, _review_id: str, **_kwargs: Any) -> MergeOutcome:
        raise MergeError("internal merge detail")

    monkeypatch.setattr(router_mod, "advisory_lock", _lock)
    monkeypatch.setattr(router_mod, "merge_dedup_review", _merge)

    response = client.patch(
        "/v1/admin/dedup-reviews/review-1",
        json={"decision": "merged", "master_feature_id": "feature-a"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "dedup review merge failed"
