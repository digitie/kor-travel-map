"""``/v1/admin/enrichment-reviews`` 라우터 단위 테스트 (T-RV-52c)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.admin_feature_repo import (
    EnrichmentReviewDetail,
    EnrichmentReviewPage,
    EnrichmentReviewRow,
    ReviewFeatureDetail,
    ReviewSourceDetail,
)
from kortravelmap.infra.enrichment_review_repo import EnrichmentDecisionResult
from kortravelmap.infra.feature_repo import EnrichmentLoadResult

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
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            service_token=None,
            vworld_api_key=None,
        )
    )

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
        target_start_date="2026-04-05",
        target_end_date="2026-04-12",
        source_provider="python-visitkorea-api",
        source_dataset_key="visitkorea_festival_events",
        source_entity_id="2747929",
        source_name="서울 봄꽃",
        source_lon=126.9001,
        source_lat=37.5001,
        source_start_date="20260405",
        source_end_date="20260412",
        distance_m=12.5,
        spatial_score=77.88,
        decision_reason=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=now,
    )


def _target_detail(detail: dict[str, Any] | None = None) -> ReviewFeatureDetail:
    now = datetime(2026, 6, 8, tzinfo=UTC)
    return ReviewFeatureDetail(
        feature_id="f_festival",
        kind="event",
        name="서울 봄꽃 축제",
        category="01010100",
        status="active",
        lon=126.9,
        lat=37.5,
        address={"legal": "서울"},
        detail=detail if detail is not None else {"starts_on": "2026-04-05"},
        urls={"homepage": "https://example.invalid"},
        raw_refs=[],
        marker_icon=None,
        marker_color=None,
        data_origin="provider",
        data_version=1,
        created_at=now,
        updated_at=now,
        sources=(),
    )


def _source_detail() -> ReviewSourceDetail:
    now = datetime(2026, 6, 8, tzinfo=UTC)
    return ReviewSourceDetail(
        source_record_key="sr-vk",
        provider="python-visitkorea-api",
        dataset_key="visitkorea_festival_events",
        source_entity_type="festival",
        source_entity_id="2747929",
        source_version=None,
        raw_name="서울 봄꽃",
        raw_address="서울",
        raw_longitude=126.9001,
        raw_latitude=37.5001,
        raw_payload_hash="hash-vk",
        raw_data={"eventstartdate": "20260405", "eventenddate": "20260412"},
        fetched_at=now,
        imported_at=now,
        expires_at=None,
    )


def _review_detail(*, target_detail: dict[str, Any] | None = None) -> EnrichmentReviewDetail:
    now = datetime(2026, 6, 8, tzinfo=UTC)
    has_target_detail = bool(target_detail if target_detail is not None else True)
    return EnrichmentReviewDetail(
        review_id="review-1",
        status="pending",
        name_score=82.0,
        target_feature_id="f_festival",
        target_name="서울 봄꽃 축제",
        source_provider="python-visitkorea-api",
        source_dataset_key="visitkorea_festival_events",
        source_entity_id="2747929",
        source_name="서울 봄꽃",
        target_start_date="2026-04-05",
        target_end_date="2026-04-12",
        source_start_date="20260405",
        source_end_date="20260412",
        distance_m=12.5,
        spatial_score=77.88,
        decision_reason=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=now,
        target=_target_detail(target_detail),
        source=_source_detail(),
        target_detail_available=has_target_detail,
        default_detail_source="target" if has_target_detail else "visitkorea",
    )


@pytest.mark.unit
def test_enrichment_review_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/enrichment-reviews" in spec["paths"]
    assert "/v1/admin/enrichment-reviews/{review_id}" in spec["paths"]
    assert "EnrichmentReviewRecord" in spec["components"]["schemas"]
    assert "EnrichmentReviewDetailResponse" in spec["components"]["schemas"]
    assert (
        spec["components"]["schemas"]["EnrichmentReviewDetailData"]["properties"][
            "detail_source_effect"
        ]["const"]
        == "audit_only"
    )
    assert (
        spec["components"]["schemas"]["EnrichmentReviewDecisionData"]["properties"][
            "detail_source_effect"
        ]["const"]
        == "audit_only"
    )
    assert "next_cursor" not in spec["components"]["schemas"]["OffsetPageMeta"][
        "properties"
    ]


@pytest.mark.unit
def test_list_enrichment_reviews_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import enrichment_review as router_mod

    async def _list(_session: Any, **kwargs: Any) -> EnrichmentReviewPage:
        assert kwargs["statuses"] == ["pending"]
        assert kwargs["providers"] == ["python-visitkorea-api"]
        assert kwargs["min_score"] == 70
        assert kwargs["page_size"] == 25
        assert kwargs["page"] == 3
        assert "cursor" not in kwargs
        return EnrichmentReviewPage(
            items=(_review_row(),),
            total_count=42,
        )

    monkeypatch.setattr(router_mod, "list_enrichment_reviews", _list)

    response = client.get(
        "/v1/admin/enrichment-reviews",
        params={
            "status": "pending",
            "provider": "python-visitkorea-api",
            "min_score": "70",
            "page_size": "25",
            "page": "3",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["review_id"] == "review-1"
    assert body["data"]["items"][0]["source_name"] == "서울 봄꽃"
    assert body["data"]["items"][0]["distance_m"] == 12.5
    assert body["data"]["items"][0]["spatial_score"] == 77.88
    assert body["data"]["items"][0]["target_start_date"] == "2026-04-05"
    assert body["data"]["items"][0]["source_start_date"] == "20260405"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "total": 42,
    }


@pytest.mark.unit
def test_get_enrichment_review_detail_returns_compare_payload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import enrichment_review as router_mod

    async def _get(_session: Any, review_id: str) -> EnrichmentReviewDetail | None:
        assert review_id == "review-1"
        return _review_detail()

    monkeypatch.setattr(router_mod, "get_enrichment_review_detail", _get)

    response = client.get("/v1/admin/enrichment-reviews/review-1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target"]["name"] == "서울 봄꽃 축제"
    assert data["source"]["raw_name"] == "서울 봄꽃"
    assert data["default_detail_source"] == "target"
    assert data["detail_source_effect"] == "audit_only"
    assert data["target_detail_available"] is True
    assert data["distance_m"] == 12.5


@pytest.mark.unit
def test_get_enrichment_review_detail_defaults_to_visitkorea_without_clean_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import enrichment_review as router_mod

    async def _get(_session: Any, _review_id: str) -> EnrichmentReviewDetail | None:
        return _review_detail(target_detail={})

    monkeypatch.setattr(router_mod, "get_enrichment_review_detail", _get)

    response = client.get("/v1/admin/enrichment-reviews/review-1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target_detail_available"] is False
    assert data["default_detail_source"] == "visitkorea"


@pytest.mark.unit
def test_get_enrichment_review_detail_missing_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import enrichment_review as router_mod

    async def _get(_session: Any, _review_id: str) -> None:
        return None

    monkeypatch.setattr(router_mod, "get_enrichment_review_detail", _get)

    response = client.get("/v1/admin/enrichment-reviews/missing")

    assert response.status_code == 404
    assert "enrichment review 없음" in response.json()["detail"]


@pytest.mark.unit
def test_patch_accepted_applies_and_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import enrichment_review as router_mod

    async def _decide(
        _session: Any, review_id: str, decision: str, **kwargs: Any
    ) -> EnrichmentDecisionResult:
        assert review_id == "review-1"
        assert decision == "accepted"
        assert kwargs["reviewed_by"] == "local-admin"
        assert kwargs["reason"] == "같은 축제; detail_source=visitkorea"
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
            "selected_detail_source": "visitkorea",
            "reviewed_by": "local-admin",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is True
    assert data["applied"] is True
    assert data["selected_detail_source"] == "visitkorea"
    assert data["detail_source_effect"] == "audit_only"
    assert data["source_links_inserted"] == 1
    assert session.begin_count == 1


@pytest.mark.unit
def test_patch_reject_does_not_apply(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import enrichment_review as router_mod

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
    assert data["selected_detail_source"] is None
    assert data["detail_source_effect"] == "audit_only"
    assert data["source_links_inserted"] is None


@pytest.mark.unit
def test_patch_already_reviewed_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import enrichment_review as router_mod

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
