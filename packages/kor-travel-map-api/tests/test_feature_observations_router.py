"""Feature raw 관측 lineage REST 계약 (T-VN-05 이후 operator 전용).

T-VN-05(ADR-073/D-9-1): raw observation lineage(raw_data/raw_payload_hash/
source_record_key)는 공개 detail에서 제거하고 operator 표면
(``GET /features/{id}/sources``·observation history)으로 이동했다. 두 표면은
admin BFF 인증(``require_admin_frontend``)이 필요하다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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

# admin BFF secret이 없는 로컬-dev 프로필 — require_admin_frontend가 actor
# "local-dev"로 통과시킨다(기존 admin 라우터 테스트와 동일 패턴).
_OPERATOR_SETTINGS = ApiSettings(
    admin_proxy_secret=None,
    public_api_key_required=False,
    service_token=None,
    vworld_api_key=None,
)
# admin secret이 설정되면 로컬-dev 우회가 닫혀 인증 없는 호출은 거부된다.
_SECURED_SETTINGS = ApiSettings(
    admin_proxy_secret="secret",
    public_api_key_required=False,
    service_token=None,
    vworld_api_key=None,
)


def _client(settings: ApiSettings) -> TestClient:
    app = create_app(settings)

    async def _session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return _client(_OPERATOR_SETTINGS)


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
def test_feature_sources_returns_every_current_observation_for_operator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as module

    async def _row(_session: object, _feature_id: str) -> dict[str, Any]:
        return _feature_row()

    async def _observations(
        _session: object, _feature_id: str
    ) -> tuple[FeatureObservation, FeatureObservation]:
        from dataclasses import replace

        second = replace(
            _observation(),
            source_entity_key="se_mois",
            provider="python-mois-api",
            dataset_key="mois-place",
            source_entity_id="mois-1",
            source_record_key="sr_mois",
        )
        return _observation(), second

    monkeypatch.setattr(module.feature_repo, "get_feature_row", _row)
    monkeypatch.setattr(module.observation_repo, "get_current_observations", _observations)

    response = client.get("/v1/features/feature:multi/sources")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["feature_id"] == "feature:multi"
    observations = data["observations"]
    assert {item["provider"] for item in observations} == {
        "python-mcst-api",
        "python-mois-api",
    }
    # operator 표면은 raw lineage를 그대로 노출한다.
    assert observations[0]["raw_data"]["edition"] == "2025"
    assert observations[0]["raw_payload_hash"] == "hash-current"
    assert observations[0]["source_record_key"] == "sr_current"


@pytest.mark.unit
def test_observation_history_exposes_cursor_page_for_operator(
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

    monkeypatch.setattr(module.feature_repo, "get_feature_row", _row)
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
        "/v1/features/feature:multi/sources",
        "/v1/features/feature:multi/observations/se_mcst/history",
    ],
)
def test_raw_lineage_requires_operator_auth(path: str) -> None:
    """admin secret이 설정되면 인증 없는 raw lineage 호출은 403이다 (T-VN-05)."""
    client = _client(_SECURED_SETTINGS)
    response = client.get(path)
    assert response.status_code == 403


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/v1/features/feature:missing/sources",
        "/v1/features/feature:missing/observations/se_mcst/history",
    ],
)
def test_raw_lineage_404_when_feature_absent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    """operator lineage는 raw row 존재로 판정한다 — 없는 feature는 404."""
    from kortravelmap.api.routers import features as module

    async def _row(_session: object, _feature_id: str) -> None:
        return None

    monkeypatch.setattr(module.feature_repo, "get_feature_row", _row)

    response = client.get(path)

    assert response.status_code == 404
