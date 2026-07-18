"""Feature current observations와 payload history REST 계약."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.observation_repo import (
    FeatureObservation,
    ObservationHistoryPage,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        ApiSettings(public_api_key_required=False, vworld_api_key=None)
    )

    async def _session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def _observation(*, current: bool = True) -> FeatureObservation:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    return FeatureObservation(
        feature_id="feature:multi",
        source_entity_key="se_mcst",
        provider="python-mcst-api",
        dataset_key="tourism-100",
        source_entity_type="place",
        source_entity_id="official-1",
        first_seen_at=now,
        entity_last_seen_at=now,
        source_record_key="sr_current" if current else "sr_old",
        source_version="2025" if current else "2023",
        raw_name="같은 관광지",
        raw_address="서울특별시",
        raw_longitude=Decimal("126.978"),
        raw_latitude=Decimal("37.566"),
        raw_data={"edition": "2025" if current else "2023"},
        raw_payload_hash="hash-current" if current else "hash-old",
        fetched_at=now,
        imported_at=now,
        record_last_seen_at=now,
        expires_at=None,
        source_role="primary",
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
        linked_at=now,
        is_current=current,
    )


def _feature_row() -> dict[str, Any]:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    return {
        "feature_id": "feature:multi",
        "kind": "place",
        "name": "같은 관광지",
        "category": "01070100",
        "lon": 126.978,
        "lat": 37.566,
        "area_square_meters": None,
        "address": {"road": "서울특별시"},
        "detail": {},
        "urls": {},
        "legal_dong_code": None,
        "sido_code": "11",
        "sigungu_code": "11110",
        "marker_icon": "place",
        "marker_color": "P-01",
        "status": "active",
        "updated_at": now,
        "deleted_at": None,
    }


@pytest.mark.unit
def test_feature_detail_returns_every_current_observation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as module

    async def _row(_session: object, _feature_id: str) -> dict[str, Any]:
        return _feature_row()

    async def _curations(_session: object, **_kwargs: Any) -> dict[str, tuple[Any, ...]]:
        return {}

    async def _observations(
        _session: object, _feature_id: str
    ) -> tuple[FeatureObservation, FeatureObservation]:
        second = replace(
            _observation(),
            source_entity_key="se_mois",
            provider="python-mois-api",
            dataset_key="mois-place",
            source_entity_id="mois-1",
            source_record_key="sr_mois",
        )
        return _observation(), second

    monkeypatch.setattr(module.feature_repo, "get_public_feature_row", _row)
    monkeypatch.setattr(module.curation_repo, "list_curation_items_by_feature_ids", _curations)
    monkeypatch.setattr(module.observation_repo, "get_current_observations", _observations)

    response = client.get("/v1/features/feature:multi")

    assert response.status_code == 200
    observations = response.json()["data"]["observations"]
    assert {item["provider"] for item in observations} == {
        "python-mcst-api",
        "python-mois-api",
    }
    assert observations[0]["raw_data"]["edition"] == "2025"


@pytest.mark.unit
def test_observation_history_exposes_cursor_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as module

    async def _row(_session: object, _feature_id: str) -> dict[str, Any]:
        return _feature_row()

    async def _history(_session: object, **kwargs: Any) -> ObservationHistoryPage:
        assert kwargs["feature_id"] == "feature:multi"
        assert kwargs["source_entity_key"] == "se_mcst"
        assert kwargs["limit"] == 1
        return ObservationHistoryPage(items=(_observation(current=False),), next_cursor="next")

    monkeypatch.setattr(module.feature_repo, "get_public_feature_row", _row)
    monkeypatch.setattr(module.observation_repo, "get_observation_history", _history)

    response = client.get(
        "/v1/features/feature:multi/observations/se_mcst/history",
        params={"page_size": 1},
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["raw_data"] == {"edition": "2023"}
    assert response.json()["meta"]["page"]["next_cursor"] == "next"


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/v1/features/feature:multi",
        "/v1/features/feature:multi/observations/se_mcst/history",
    ],
)
def test_public_feature_detail_and_history_hide_non_public_features(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    """비공개 feature는 detail/history에서 404다.

    T-VN-04(ADR-067) 이후 공개 판정은 라우터가 아니라 ``feature.public_features``
    projection이 내린다 — 비공개 row는 ``get_public_feature_row``가 ``None``을
    돌려주고 라우터는 404로 응답한다. 상태별(hidden/deleted/retired/draft/broken/
    admin-inactive) SQL 판정 자체는 통합 테스트
    ``tests/integration/test_public_features_view.py``의 상태 matrix가 검증한다.
    """
    from kortravelmap.api.routers import features as module

    async def _row(_session: object, _feature_id: str) -> None:
        return None

    monkeypatch.setattr(module.feature_repo, "get_public_feature_row", _row)

    response = client.get(path)

    assert response.status_code == 404
