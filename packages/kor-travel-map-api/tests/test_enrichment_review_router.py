"""``/v1/admin/features/enrichment-reviews`` 라우터 단위 테스트 (T-RV-52c)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

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
def client(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    from kortravelmap.api import domain_command_service

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
    monkeypatch.setattr(
        domain_command_service,
        "begin_domain_command",
        AsyncMock(
            return_value=domain_command_service.DomainCommandHandle(
                command_id=1,
                actor="local-dev",
                operation="admin.enrichment-review.decide",
                idempotency_key="95000000-0000-4000-8000-000000000001",
                request_fingerprint="a" * 64,
            )
        ),
    )
    monkeypatch.setattr(
        domain_command_service,
        "complete_domain_command",
        AsyncMock(),
    )
    return TestClient(
        app,
        headers={"Idempotency-Key": "95000000-0000-4000-8000-000000000001"},
    )


def _expected_uuid(feature_id: str) -> str:
    """결정적 mock uuid — 테스트 편의 규약이지 저장 계약(0083 비파생 v7)이 아니다."""
    from kortravelmap.core.ids import feature_uuid_from_legacy

    return str(feature_uuid_from_legacy(feature_id))


def _review_row() -> EnrichmentReviewRow:
    now = datetime(2026, 6, 8, tzinfo=UTC)
    return EnrichmentReviewRow(
        review_id="review-1",
        status="pending",
        name_score=82.0,
        target_feature_id="f_festival",
        target_feature_uuid=_expected_uuid("f_festival"),
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
        feature_uuid=_expected_uuid("f_festival"),
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
        raw_payload_hash="hash-vk",
        raw_data={"eventstartdate": "20260405", "eventenddate": "20260412"},
        fetched_at=now,
        imported_at=now,
        observed_at=now,
    )


def _review_detail(*, target_detail: dict[str, Any] | None = None) -> EnrichmentReviewDetail:
    now = datetime(2026, 6, 8, tzinfo=UTC)
    has_target_detail = bool(target_detail if target_detail is not None else True)
    return EnrichmentReviewDetail(
        review_id="review-1",
        status="pending",
        name_score=82.0,
        target_feature_id="f_festival",
        target_feature_uuid=_expected_uuid("f_festival"),
        target_name="서울 봄꽃 축제",
        source_provider="python-visitkorea-api",
        source_dataset_key="visitkorea_festival_events",
        source_entity_id="2747929",
        source_name="서울 봄꽃",
        source_lon=126.9001,
        source_lat=37.5001,
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
    assert "/v1/admin/features/enrichment-reviews" in spec["paths"]
    assert "/v1/admin/features/enrichment-reviews/{review_id}" in spec["paths"]
    assert "/v1/admin/enrichment-reviews" not in spec["paths"]
    assert "/v1/admin/enrichment-reviews/{review_id}" not in spec["paths"]
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
    # T-VN-H06: keyset cursor 목록이므로 meta는 next_cursor를 노출하는 PageMeta다.
    assert "next_cursor" in spec["components"]["schemas"]["PageMeta"]["properties"]


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
        assert kwargs["cursor"] == "opaque-cursor-xyz"
        assert "page" not in kwargs
        return EnrichmentReviewPage(
            items=(_review_row(),),
            total_count=42,
            next_cursor="next-abc",
        )

    monkeypatch.setattr(router_mod, "list_enrichment_reviews", _list)

    response = client.get(
        "/v1/admin/features/enrichment-reviews",
        params={
            "status": "pending",
            "provider": "python-visitkorea-api",
            "min_score": "70",
            "page_size": "25",
            "cursor": "opaque-cursor-xyz",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["review_id"] == "review-1"
    # T-VN-32C 값 전환 — target feature 참조 표시는 UUID 정본.
    assert body["data"]["items"][0]["target_feature_id"] == (
        _expected_uuid("f_festival")
    )
    assert body["data"]["items"][0]["source_name"] == "서울 봄꽃"
    assert body["data"]["items"][0]["distance_m"] == 12.5
    assert body["data"]["items"][0]["spatial_score"] == 77.88
    assert body["data"]["items"][0]["target_start_date"] == "2026-04-05"
    assert body["data"]["items"][0]["source_start_date"] == "20260405"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "next-abc",
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

    response = client.get("/v1/admin/features/enrichment-reviews/review-1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target"]["name"] == "서울 봄꽃 축제"
    # T-VN-32C 값 전환 — target/비교 snapshot의 feature 참조는 UUID 정본.
    assert data["target_feature_id"] == _expected_uuid("f_festival")
    assert data["target"]["feature_id"] == _expected_uuid("f_festival")
    assert data["source_name"] == "서울 봄꽃"
    assert data["source_lon"] == 126.9001
    assert data["source_lat"] == 37.5001
    assert {
        "source_version",
        "raw_name",
        "raw_address",
        "raw_longitude",
        "raw_latitude",
    }.isdisjoint(data["source"])
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

    response = client.get("/v1/admin/features/enrichment-reviews/review-1")

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

    response = client.get("/v1/admin/features/enrichment-reviews/missing")

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
        # T-VN-20 (ADR-066 D-2): reviewed_by는 인증 principal(local-dev)에서만
        # 파생한다. body의 reviewed_by 필드는 제거돼 더 이상 보낼 수 없다.
        assert kwargs["reviewed_by"] == "local-dev"
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
        "/v1/admin/features/enrichment-reviews/review-1",
        json={
            "decision": "accepted",
            "decision_reason": "같은 축제",
            "selected_detail_source": "visitkorea",
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
def test_patch_rejects_removed_reviewed_by_body_field(
    client: TestClient,
) -> None:
    # T-VN-20 (ADR-066 D-2): 제거된 body actor 필드를 보내면 extra="forbid"로 422.
    response = client.patch(
        "/v1/admin/features/enrichment-reviews/review-1",
        json={"decision": "accepted", "reviewed_by": "attacker"},
    )
    assert response.status_code == 422


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
        "/v1/admin/features/enrichment-reviews/review-1",
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
        "/v1/admin/features/enrichment-reviews/review-1",
        json={"decision": "accepted"},
    )

    assert response.status_code == 409
    assert "전이 실패" in response.json()["detail"]
