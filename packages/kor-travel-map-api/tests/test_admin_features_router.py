"""``/v1/admin/features`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.admin_feature_repo import (
    AdminFeatureDetail,
    AdminFeatureDetailFeature,
    AdminFeatureDetailFile,
    AdminFeatureDetailIssue,
    AdminFeatureDetailOverride,
    AdminFeatureDetailSource,
    AdminFeatureDetailVersion,
    AdminFeaturePage,
    AdminFeatureRow,
    AdminFeatureStateConflict,
    AdminFeatureStateNotFound,
    AdminFeatureStatePreconditionFailed,
    AdminFeatureStateTransition,
    AdminFeatureStateTransitionAudit,
    AdminFeatureStateTransitionAuditPage,
    FeatureChangeRequest,
    FeaturePreconditionFailed,
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
def client(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    from kortravelmap.api import domain_command_service

    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
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
                operation="admin.feature.create",
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


def _feature_row() -> AdminFeatureRow:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return AdminFeatureRow(
        feature_id="feature-1",
        feature_uuid=_expected_uuid("feature-1"),
        kind="place",
        name="광화문",
        category="01070300",
        lifecycle_state="active",
        publication_state="published",
        quality_state="valid",
        lon=126.9769,
        lat=37.5759,
        address_label="서울특별시 종로구",
        primary_provider="python-mois-api",
        primary_dataset_key="mois_license_features_bulk",
        issue_count=1,
        issues=(
            {
                "issue_id": "issue-1",
                "violation_type": "missing_address",
                "severity": "warning",
                "message": "주소 누락",
                "detected_at": now,
            },
        ),
        created_at=now,
        updated_at=now,
    )


def _feature_detail() -> AdminFeatureDetail:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    feature = AdminFeatureDetailFeature(
        feature_id="feature-1",
        feature_uuid=_expected_uuid("feature-1"),
        kind="place",
        name="광화문",
        category="01070300",
        lifecycle_state="active",
        publication_state="published",
        quality_state="valid",
        lon=126.9769,
        lat=37.5759,
        coord_precision_digits=5,
        area_square_meters=None,
        address={"road": "서울특별시 종로구 세종대로 1"},
        detail={"place_kind": "attraction"},
        urls={"homepage": "https://example.test"},
        raw_refs=[{"source": "fixture"}],
        legal_dong_code="1111010100",
        road_name_code=None,
        road_address_management_no=None,
        admin_dong_code="1111051500",
        sido_code="11",
        sigungu_code="11110",
        marker_icon="landmark",
        marker_color="P-01",
        parent_feature_id=None,
        sibling_group_id=None,
        data_origin="provider",
        data_version=0,
        row_revision=7,
        created_at=now,
        updated_at=now,
    )
    source = AdminFeatureDetailSource(
        source_entity_key="se-feature-1",
        source_record_key="sr-feature-1",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_entity_type="license_place",
        source_entity_id="sr-feature-1",
        source_role="primary",
        match_method="natural_key",
        confidence=100,
        raw_payload_hash="hash-1",
        raw_data={"id": "sr-feature-1"},
        fetched_at=now,
        imported_at=now,
        observed_at=now,
        expires_at=None,
        linked_at=now,
    )
    issue = AdminFeatureDetailIssue(
        issue_id="issue-1",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key="sr-feature-1",
        violation_type="missing_address",
        severity="warning",
        message="주소 누락",
        payload={"field": "address"},
        status="open",
        detected_at=now,
        resolved_at=None,
    )
    override = AdminFeatureDetailOverride(
        override_id="override-1",
        source_record_key=None,
        field_path="lifecycle_state",
        source_value="active",
        override_value="retired",
        prevent_provider_reactivation=True,
        status="active",
        reason="운영상 제외",
        created_by="local-admin",
        created_at=now,
    )
    version = AdminFeatureDetailVersion(
        feature_id="feature-1",
        version=0,
        origin="provider",
        change_kind="load",
        payload={"name": "광화문"},
        request_id=None,
        created_by="provider",
        created_at=now,
    )
    file = AdminFeatureDetailFile(
        file_id="file-1",
        file_type="image",
        storage_backend="rustfs",
        bucket="kor-travel-map",
        object_key="features/example.jpg",
        source_url="https://example.test/source.jpg",
        public_url="https://cdn.example.test/features/example.jpg",
        content_type="image/jpeg",
        byte_size=1234,
        checksum_sha256="a" * 64,
        width=640,
        height=480,
        role="primary",
        display_order=0,
        alt_text="광화문",
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        source_record_key="sr-feature-1",
        payload={},
        created_at=now,
        updated_at=now,
    )
    return AdminFeatureDetail(
        feature=feature,
        sources=(source,),
        issues=(issue,),
        overrides=(override,),
        versions=(version,),
        change_requests=(_change_request(action="update", state="applied"),),
        files=(file,),
        state_transitions=(
            AdminFeatureStateTransitionAudit(
                transition_id=101,
                from_lifecycle_state="active",
                from_publication_state="published",
                from_quality_state="valid",
                to_lifecycle_state="active",
                to_publication_state="suppressed",
                to_quality_state="valid",
                transition_kind="admin",
                reason_code="admin_suppress",
                principal="local-admin",
                causation_ref="admin:feature-1",
                provider_dataset_id=None,
                source_entity_key=None,
                source_record_key=None,
                occurred_at=now,
                row_revision=8,
            ),
        ),
    )


def _change_request(
    *,
    request_id: str = "change-1",
    feature_id: str = "feature-1",
    action: str = "add",
    state: str = "pending",
    review_mode: str = "require_review",
    base_row_revision: int | None = None,
    payload: dict[str, Any] | None = None,
    reason: str | None = "사용자 제보",
    requested_by: str | None = "local-admin",
    reviewed_by: str | None = None,
    applied_at: datetime | None = None,
) -> FeatureChangeRequest:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return FeatureChangeRequest(
        request_id=request_id,
        feature_id=feature_id,
        action=action,
        state=state,
        review_mode=review_mode,
        base_row_revision=base_row_revision,
        payload=payload or {},
        reason=reason,
        requested_by=requested_by,
        reviewed_by=reviewed_by,
        reviewed_at=now if reviewed_by is not None else None,
        applied_at=applied_at,
        created_at=now,
    )


@pytest.mark.unit
def test_admin_features_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/features" in spec["paths"]
    assert set(spec["paths"]["/v1/admin/features"]) >= {"get", "post"}
    assert "/v1/admin/features/{feature_id}" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/revision" in spec["paths"]
    assert set(spec["paths"]["/v1/admin/features/{feature_id}"]) >= {
        "get",
        "patch",
        "delete",
    }
    assert "/v1/admin/features/change-requests" in spec["paths"]
    assert "/v1/admin/features/change-requests/{request_id}/approve" in spec["paths"]
    assert "/v1/admin/features/change-requests/{request_id}/reject" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/state" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/state/reactivate" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/state/transitions" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/deactivate" not in spec["paths"]
    assert "/v1/admin/features/in-bounds" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/weather" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/price" in spec["paths"]
    assert "AdminFeatureRecord" in spec["components"]["schemas"]
    assert "AdminFeatureCreateRequest" in spec["components"]["schemas"]
    assert "AdminFeaturePatchRequest" in spec["components"]["schemas"]
    assert "AdminFeatureChangeResponse" in spec["components"]["schemas"]
    assert "AdminFeatureStatePatchRequest" in spec["components"]["schemas"]
    assert "AdminFeatureStateRetireRequest" in spec["components"]["schemas"]
    assert "AdminFeatureReactivateRequest" in spec["components"]["schemas"]
    assert "status" not in spec["components"]["schemas"]["AdminFeatureRecord"]["properties"]
    assert "status" not in spec["components"]["schemas"]["AdminFeatureMapItem"]["properties"]
    assert "status" not in spec["components"]["schemas"][
        "AdminFeatureDetailFeatureRecord"
    ]["properties"]
    assert (
        spec["components"]["schemas"]["AdminFeatureIssueRecord"][
            "additionalProperties"
        ]
        is False
    )


@pytest.mark.unit
def test_admin_in_bounds_combines_state_axes_with_and_for_items_and_clusters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _items(_session: Any, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["lifecycle_states"] == ["active"]
        assert kwargs["publication_states"] == ["draft", "suppressed"]
        assert kwargs["quality_states"] == ["quarantined"]
        assert kwargs["include_geometry"] is True
        return [
            {
                "feature_id": "inactive-1",
                "feature_uuid": _expected_uuid("inactive-1"),
                "kind": "place",
                "name": "비공개 운영 대상",
                "category": "01070300",
                "lon": 126.97,
                "lat": 37.57,
                "marker_icon": "place",
                "marker_color": "P-01",
                "lifecycle_state": "active",
                "publication_state": "suppressed",
                "quality_state": "quarantined",
            }
        ]

    async def _clusters(_session: Any, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["lifecycle_states"] == ["retired"]
        assert kwargs["publication_states"] == ["suppressed"]
        assert kwargs["quality_states"] == ["valid"]
        assert kwargs["cluster_unit"] == "sido"
        return [
            {
                "cluster_key": "11",
                "feature_count": 2,
                "lon": 126.97,
                "lat": 37.57,
            }
        ]

    monkeypatch.setattr(router_mod, "admin_features_in_bbox", _items)
    monkeypatch.setattr(router_mod, "cluster_admin_features_in_bbox", _clusters)

    item_response = client.get(
        "/v1/admin/features/in-bounds",
        params={
            "min_lon": 126.9,
            "min_lat": 37.5,
            "max_lon": 127.0,
            "max_lat": 37.6,
            "lifecycle_state": "active",
            "publication_state": ["draft", "suppressed"],
            "quality_state": "quarantined",
            "zoom": 14,
            "include_geometry": "true",
        },
    )
    assert item_response.status_code == 200
    # T-VN-32C 값 전환 — 지도 item의 feature_id 값은 stub row의 UUID 정본.
    assert (
        item_response.json()["data"]["items"][0]["feature_id"]
        == _expected_uuid("inactive-1")
    )
    item = item_response.json()["data"]["items"][0]
    assert item["lifecycle_state"] == "active"
    assert item["publication_state"] == "suppressed"
    assert item["quality_state"] == "quarantined"
    assert item_response.json()["data"]["clusters"] == []

    cluster_response = client.get(
        "/v1/admin/features/in-bounds",
        params={
            "min_lon": 126.9,
            "min_lat": 37.5,
            "max_lon": 127.0,
            "max_lat": 37.6,
            "lifecycle_state": "retired",
            "publication_state": "suppressed",
            "quality_state": "valid",
            "zoom": 7,
        },
    )
    assert cluster_response.status_code == 200
    assert cluster_response.json()["data"]["mode"] == "clusters"
    assert cluster_response.json()["data"]["clusters"][0]["feature_count"] == 2
    assert cluster_response.json()["data"]["items"] == []


@pytest.mark.unit
def test_admin_weather_and_price_cards_accept_nonpublic_feature(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra.price_repo import PriceCard
    from kortravelmap.infra.weather_repo import WeatherCard

    from kortravelmap.api.routers import admin_features as router_mod

    async def _exists(_session: Any, feature_id: str) -> bool:
        return feature_id == "hidden-1"

    async def _weather(_session: Any, **kwargs: Any) -> WeatherCard:
        assert kwargs["feature_id"] == "hidden-1"
        return WeatherCard(
            feature_id="hidden-1",
            source_styles=[],
            metrics=[],
            latest_at=None,
            is_stale=True,
        )

    async def _price(_session: Any, **kwargs: Any) -> PriceCard:
        assert kwargs["feature_id"] == "hidden-1"
        return PriceCard(
            feature_id="hidden-1",
            current=[],
            history=[],
            latest_at=None,
            is_stale=True,
        )

    monkeypatch.setattr(router_mod, "admin_feature_card_target_exists", _exists)
    monkeypatch.setattr(router_mod.weather_repo, "build_admin_weather_card", _weather)
    monkeypatch.setattr(router_mod.price_repo, "build_price_card", _price)

    weather = client.get("/v1/admin/features/hidden-1/weather")
    price = client.get("/v1/admin/features/hidden-1/price")
    deleted_weather = client.get("/v1/admin/features/deleted-1/weather")
    deleted_price = client.get("/v1/admin/features/deleted-1/price")

    assert weather.status_code == 200
    # T-VN-32C 값 전환 — 단건 card 응답의 feature_id는 UUID 정본
    # (repo 조회는 위 kwargs assert대로 legacy 축).
    assert weather.json()["data"]["feature_id"] == _expected_uuid("hidden-1")
    assert price.status_code == 200
    assert price.json()["data"]["feature_id"] == _expected_uuid("hidden-1")
    assert deleted_weather.status_code == 404
    assert deleted_price.status_code == 404


@pytest.mark.unit
def test_list_admin_features_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _list(_session: Any, **kwargs: Any) -> AdminFeaturePage:
        assert kwargs["q"] == "광화문"
        assert kwargs["kinds"] == ["place"]
        assert kwargs["lifecycle_states"] == ["retired"]
        assert kwargs["publication_states"] == ["suppressed"]
        assert kwargs["quality_states"] == ["quarantined"]
        # ADR-088 — provider 자연키 반복 필터는 삭제됐고 dataset canonical ID다.
        assert kwargs["provider_dataset_id"] == 7
        assert kwargs["page_size"] == 25
        assert kwargs["sort"] == "issue_count"
        assert kwargs["order"] == "desc"
        return AdminFeaturePage(items=(_feature_row(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_admin_features", _list)

    response = client.get(
        "/v1/admin/features",
        params={
            "q": "광화문",
            "kind": "place",
            "lifecycle_state": "retired",
            "publication_state": "suppressed",
            "quality_state": "quarantined",
            "provider_dataset_id": "7",
            "page_size": "25",
            "sort": "issue_count",
        },
    )

    assert response.status_code == 200
    body = response.json()
    # T-VN-32C 값 전환 — 응답 feature_id 값은 stub row의 UUID 정본이고,
    # next_cursor는 repo가 치환 전 legacy 축으로 encode한 값 그대로다.
    assert body["data"]["items"][0]["feature_id"] == _expected_uuid("feature-1")
    assert body["data"]["items"][0]["feature_uuid"] == _expected_uuid("feature-1")
    assert body["data"]["items"][0]["lifecycle_state"] == "active"
    assert body["data"]["items"][0]["publication_state"] == "published"
    assert body["data"]["items"][0]["quality_state"] == "valid"
    assert body["data"]["items"][0]["issues"][0]["issue_id"] == "issue-1"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "next",
        "total": None,
    }


def _patch_admin_resolved_identity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    feature_id: str | None = None,
) -> None:
    """T-VN-32B 경계 alias 해석 mock — 형식 계약(422)은 실제 검증을 태운다.

    uuid는 참조에서 결정적으로 만들되(테스트 편의 규약) 저장 계약은 아니다 —
    0083(T-VN-32C) 이후 실제 값은 비파생 UUIDv7이다.
    """
    from kortravelmap.core.ids import feature_uuid_from_legacy
    from kortravelmap.infra import feature_identity

    async def _resolve(_session: Any, ref: str) -> feature_identity.FeatureIdentity:
        feature_identity.validate_feature_ref(ref)
        resolved = feature_id if feature_id is not None else ref
        return feature_identity.FeatureIdentity(
            feature_id=resolved,
            feature_uuid=str(feature_uuid_from_legacy(resolved)),
        )

    monkeypatch.setattr(feature_identity, "resolve_feature_identity", _resolve)


@pytest.mark.unit
def test_get_admin_feature_detail_returns_linked_operational_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    _patch_admin_resolved_identity(monkeypatch)

    async def _detail(_session: Any, feature_id: str) -> AdminFeatureDetail:
        assert feature_id == "feature-1"
        return _feature_detail()

    async def _curations(
        _session: Any, **kwargs: Any
    ) -> dict[str, tuple[Any, ...]]:
        assert kwargs == {
            "feature_ids": ["feature-1"],
            "public_only": False,
        }
        return {"feature-1": ()}

    monkeypatch.setattr(router_mod, "get_admin_feature_detail", _detail)
    monkeypatch.setattr(
        router_mod.curation_repo,
        "list_curation_items_by_feature_ids",
        _curations,
    )

    response = client.get("/v1/admin/features/feature-1")

    assert response.status_code == 200
    assert "ETag" not in response.headers
    body = response.json()
    # T-VN-32C 값 전환 — feature record의 feature_id 값은 UUID 정본.
    assert body["data"]["feature"]["feature_id"] == _expected_uuid("feature-1")
    assert body["data"]["feature"]["feature_uuid"] == _expected_uuid("feature-1")
    assert body["data"]["feature"]["row_revision"] == 7
    assert body["data"]["feature"]["raw_refs"] == [{"source": "fixture"}]
    assert body["data"]["sources"][0]["source_entity_key"] == "se-feature-1"
    assert body["data"]["sources"][0]["raw_data"] == {"id": "sr-feature-1"}
    assert body["data"]["sources"][0]["observed_at"] == "2026-06-03T00:00:00Z"
    assert {
        "source_version",
        "raw_name",
        "raw_address",
        "raw_longitude",
        "raw_latitude",
    }.isdisjoint(body["data"]["sources"][0])
    assert body["data"]["issues"][0]["status"] == "open"
    assert body["data"]["overrides"][0]["field_path"] == "lifecycle_state"
    assert body["data"]["state_transitions"][0] == {
        "transition_id": 101,
        "from_lifecycle_state": "active",
        "from_publication_state": "published",
        "from_quality_state": "valid",
        "to_lifecycle_state": "active",
        "to_publication_state": "suppressed",
        "to_quality_state": "valid",
        "transition_kind": "admin",
        "reason_code": "admin_suppress",
        "principal": "local-admin",
        "causation_ref": "admin:feature-1",
        "provider_dataset_id": None,
        "source_entity_key": None,
        "source_record_key": None,
        "occurred_at": "2026-06-03T00:00:00Z",
        "row_revision": 8,
    }
    assert body["data"]["versions"][0]["change_kind"] == "load"
    assert body["data"]["change_requests"][0]["status"] == "applied"
    assert body["data"]["files"][0]["role"] == "primary"
    assert body["data"]["curations"] == []


@pytest.mark.unit
def test_get_admin_feature_detail_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    _patch_admin_resolved_identity(monkeypatch)

    async def _detail(_session: Any, feature_id: str) -> None:
        assert feature_id == "missing"

    monkeypatch.setattr(router_mod, "get_admin_feature_detail", _detail)

    response = client.get("/v1/admin/features/missing")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.unit
def test_get_admin_feature_detail_accepts_uuid_ref(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-VN-32B — admin 상세 경로도 UUID 참조를 경계에서 해석한다(내부는 legacy 키)."""
    from kortravelmap.core.ids import feature_uuid_from_legacy

    from kortravelmap.api.routers import admin_features as router_mod

    _patch_admin_resolved_identity(monkeypatch, feature_id="feature-1")
    requested_ids: list[str] = []

    async def _detail(_session: Any, feature_id: str) -> AdminFeatureDetail:
        requested_ids.append(feature_id)
        return _feature_detail()

    async def _curations(
        _session: Any, **_kwargs: Any
    ) -> dict[str, tuple[Any, ...]]:
        return {}

    monkeypatch.setattr(router_mod, "get_admin_feature_detail", _detail)
    monkeypatch.setattr(
        router_mod.curation_repo,
        "list_curation_items_by_feature_ids",
        _curations,
    )

    uuid_ref = str(feature_uuid_from_legacy("feature-1"))
    response = client.get(f"/v1/admin/features/{uuid_ref}")

    assert response.status_code == 200
    assert requested_ids == ["feature-1"]
    # T-VN-32C 값 전환 — 응답 feature_id 값은 UUID 정본.
    assert response.json()["data"]["feature"]["feature_id"] == uuid_ref


@pytest.mark.unit
def test_get_feature_revision_returns_stable_etag(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _revision(_session: Any, feature_id: str) -> int:
        assert feature_id == "feature-1"
        return 7

    monkeypatch.setattr(router_mod, "get_feature_row_revision", _revision)
    response = client.get("/v1/admin/features/feature-1/revision")

    assert response.status_code == 200
    assert response.headers["ETag"] == '"7"'
    assert response.json() == {
        "data": {"feature_id": "feature-1", "row_revision": 7}
    }


@pytest.mark.unit
def test_list_feature_state_transitions_is_newest_first_keyset_page(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    _patch_admin_resolved_identity(monkeypatch)

    async def _revision(_session: Any, feature_id: str) -> int:
        assert feature_id == "feature-1"
        return 9

    async def _transitions(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        assert feature_id == "feature-1"
        assert kwargs == {"limit": 2, "before_transition_id": 102}
        return AdminFeatureStateTransitionAuditPage(
            items=(
                AdminFeatureStateTransitionAudit(
                    transition_id=101,
                    from_lifecycle_state="active",
                    from_publication_state="published",
                    from_quality_state="valid",
                    to_lifecycle_state="active",
                    to_publication_state="suppressed",
                    to_quality_state="valid",
                    transition_kind="admin",
                    reason_code="admin_suppress",
                    principal="local-admin",
                    causation_ref="admin:feature-1",
                    provider_dataset_id=None,
                    source_entity_key=None,
                    source_record_key=None,
                    occurred_at=datetime(2026, 6, 3, tzinfo=UTC),
                    row_revision=8,
                ),
            ),
            next_cursor=101,
        )

    monkeypatch.setattr(router_mod, "get_feature_row_revision", _revision)
    monkeypatch.setattr(
        router_mod,
        "list_admin_feature_state_transitions",
        _transitions,
    )
    response = client.get(
        "/v1/admin/features/feature-1/state/transitions",
        params={"page_size": 2, "before_transition_id": 102},
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["transition_id"] == 101
    assert response.json()["data"]["items"][0]["causation_ref"] == "admin:feature-1"
    assert response.json()["meta"]["page"] == {
        "page_size": 2,
        "next_cursor": "101",
        "total": None,
    }


@pytest.mark.unit
def test_list_feature_state_transitions_returns_404_before_audit_query(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    _patch_admin_resolved_identity(monkeypatch)

    async def _missing(_session: Any, _feature_id: str) -> None:
        return None

    monkeypatch.setattr(router_mod, "get_feature_row_revision", _missing)
    response = client.get("/v1/admin/features/missing/state/transitions")
    assert response.status_code == 404


@pytest.mark.unit
def test_list_feature_change_requests_returns_current_review_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    client.app.dependency_overrides[router_mod._settings] = lambda: ApiSettings(
        feature_change_review_mode="immediate"
    )

    async def _list(_session: Any, **kwargs: Any) -> tuple[FeatureChangeRequest, ...]:
        assert kwargs["states"] == ["pending"]
        assert kwargs["actions"] == ["add"]
        assert kwargs["q"] == "광화문"
        assert kwargs["limit"] == 25
        return (_change_request(review_mode="immediate", state="applied"),)

    monkeypatch.setattr(router_mod, "list_feature_change_requests", _list)

    response = client.get(
        "/v1/admin/features/change-requests",
        params={
            "status": "pending",
            "action": "add",
            "q": "광화문",
            "page_size": "25",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["review_mode"] == "immediate"
    assert body["data"]["items"][0]["status"] == "applied"
    assert body["data"]["review_mode"] == "immediate"
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": None,
        "total": None,
    }


@pytest.mark.unit
def test_create_feature_request_uses_review_required_by_default(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _submit(_session: Any, **kwargs: Any) -> FeatureChangeRequest:
        assert kwargs["action"] == "add"
        assert kwargs["review_mode"] == "require_review"
        assert kwargs["payload"]["kind"] == "place"
        assert kwargs["payload"]["name"] == "사용자 장소"
        assert kwargs["payload"]["coord"] == {"lon": 126.98, "lat": 37.57}
        assert kwargs["payload"]["lifecycle_state"] == "active"
        assert kwargs["payload"]["publication_state"] == "published"
        assert kwargs["payload"]["quality_state"] == "valid"
        assert kwargs["payload"]["feature_id"] == kwargs["feature_id"]
        assert kwargs["reason"] == "사용자 제보"
        assert kwargs["requested_by"] == "local-dev"  # T-VN-20: principal, not body operator
        return _change_request(
            feature_id=kwargs["feature_id"],
            action=kwargs["action"],
            state="pending",
            review_mode=kwargs["review_mode"],
            payload=kwargs["payload"],
            reason=kwargs["reason"],
            requested_by=kwargs["requested_by"],
        )

    monkeypatch.setattr(router_mod, "submit_feature_change_request", _submit)

    response = client.post(
        "/v1/admin/features",
        json={
            "kind": "place",
            "name": "사용자 장소",
            "category": "01070300",
            "coord": {"lon": 126.98, "lat": 37.57},
            "marker_icon": "map-pin",
            "marker_color": "P-01",
            "reason": "사용자 제보",
            "operator": "admin-user",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["request"]["status"] == "pending"
    assert body["data"]["request"]["review_mode"] == "require_review"
    assert session.begin_count == 1

    # T-VN-32C 회귀 (W1) — 응답에서 복사한 UUID 형식 feature_id를 신규 legacy
    # id로 지정하는 요청은 422 fail-close다 (유령 행 각인 차단, DB 도달 전).
    uuid_body = client.post(
        "/v1/admin/features",
        json={
            "feature_id": _expected_uuid("ghost"),
            "kind": "place",
            "name": "사용자 장소",
            "category": "01070300",
            "coord": {"lon": 126.98, "lat": 37.57},
            "marker_icon": "map-pin",
            "marker_color": "P-01",
            "reason": "사용자 제보",
        },
    )
    assert uuid_body.status_code == 422
    assert "UUID" in uuid_body.json()["detail"]


@pytest.mark.unit
def test_patch_feature_request_can_apply_immediately(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    client.app.dependency_overrides[router_mod._settings] = lambda: ApiSettings(
        feature_change_review_mode="immediate"
    )

    async def _submit(_session: Any, **kwargs: Any) -> FeatureChangeRequest:
        assert kwargs["action"] == "update"
        assert kwargs["feature_id"] == "feature-1"
        assert kwargs["payload"] == {"name": "수정된 장소"}
        assert kwargs["review_mode"] == "immediate"
        assert kwargs["expected_row_revision"] == 4  # If-Match row_revision
        return _change_request(
            feature_id=kwargs["feature_id"],
            action=kwargs["action"],
            state="applied",
            review_mode=kwargs["review_mode"],
            payload=kwargs["payload"],
            applied_at=datetime(2026, 6, 3, tzinfo=UTC),
        )

    async def _revision(_session: Any, feature_id: str) -> int:
        assert feature_id == "feature-1"
        return 5  # 적용 후 trigger가 4→5로 증가

    monkeypatch.setattr(router_mod, "submit_feature_change_request", _submit)
    monkeypatch.setattr(router_mod, "get_feature_row_revision", _revision)

    response = client.patch(
        "/v1/admin/features/feature-1",
        headers={"If-Match": '"4"'},
        json={
            "name": "수정된 장소",
            "reason": "사용자 수정",
        },
    )

    assert response.status_code == 200
    assert response.headers["ETag"] == '"5"'
    assert response.json()["data"]["request"]["status"] == "applied"
    assert session.begin_count == 1


@pytest.mark.unit
def test_delete_feature_request_submits_soft_delete(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _submit(_session: Any, **kwargs: Any) -> FeatureChangeRequest:
        assert kwargs["action"] == "delete"
        assert kwargs["feature_id"] == "feature-1"
        assert kwargs["payload"] == {}
        assert kwargs["reason"] == "사용자 삭제 요청"
        assert kwargs["expected_row_revision"] == 9
        return _change_request(
            feature_id=kwargs["feature_id"],
            action=kwargs["action"],
            payload=kwargs["payload"],
            reason=kwargs["reason"],
        )

    async def _revision(_session: Any, feature_id: str) -> int:
        assert feature_id == "feature-1"
        return 10

    monkeypatch.setattr(router_mod, "submit_feature_change_request", _submit)
    monkeypatch.setattr(router_mod, "get_feature_row_revision", _revision)

    response = client.request(
        "DELETE",
        "/v1/admin/features/feature-1",
        headers={"If-Match": '"9"'},
        json={"reason": "사용자 삭제 요청"},
    )

    assert response.status_code == 200
    assert response.headers["ETag"] == '"10"'
    assert response.json()["data"]["request"]["action"] == "delete"
    assert session.begin_count == 1


@pytest.mark.unit
def test_approve_and_reject_feature_change_requests(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _apply(
        _session: Any,
        request_id: str,
        **kwargs: Any,
    ) -> FeatureChangeRequest:
        assert request_id == "change-1"
        assert kwargs["operator"] == "local-dev"  # T-VN-20: principal, not body operator
        assert "expected_row_revision" not in kwargs
        return _change_request(
            request_id=request_id,
            state="applied",
            reviewed_by=kwargs["operator"],
            applied_at=datetime(2026, 6, 3, tzinfo=UTC),
        )

    async def _revision(_session: Any, feature_id: str) -> int:
        assert feature_id == "feature-1"
        return 3

    async def _reject(
        _session: Any,
        request_id: str,
        **kwargs: Any,
    ) -> FeatureChangeRequest:
        assert request_id == "change-2"
        assert kwargs["operator"] == "local-dev"  # T-VN-20: principal, not body operator
        assert kwargs["reason"] == "중복"
        return _change_request(
            request_id=request_id,
            state="rejected",
            reviewed_by=kwargs["operator"],
            reason=kwargs["reason"],
        )

    monkeypatch.setattr(router_mod, "apply_feature_change_request", _apply)
    monkeypatch.setattr(router_mod, "reject_feature_change_request", _reject)
    monkeypatch.setattr(router_mod, "get_feature_row_revision", _revision)

    approve = client.post(
        "/v1/admin/features/change-requests/change-1/approve",
        json={"operator": "reviewer"},
    )
    reject = client.post(
        "/v1/admin/features/change-requests/change-2/reject",
        json={"operator": "reviewer", "reason": "중복"},
    )

    assert approve.status_code == 200
    assert approve.headers["ETag"] == '"3"'
    assert approve.json()["data"]["request"]["status"] == "applied"
    assert reject.status_code == 200
    assert reject.json()["data"]["request"]["status"] == "rejected"
    assert session.begin_count == 2


@pytest.mark.unit
def test_patch_feature_without_if_match_returns_428(client: TestClient) -> None:
    response = client.patch(
        "/v1/admin/features/feature-1",
        json={"name": "x", "reason": "r"},
    )
    assert response.status_code == 428
    assert response.json()["code"] == "PRECONDITION_REQUIRED"


@pytest.mark.unit
@pytest.mark.parametrize(
    "entity_tag",
    [
        "not-a-revision",
        "7",
        'W/"7"',
        "*",
        '"0"',
        '"007"',
        '"7", "8"',
        '"9223372036854775808"',
    ],
)
def test_delete_feature_with_noncanonical_if_match_returns_422(
    client: TestClient,
    entity_tag: str,
) -> None:
    response = client.request(
        "DELETE",
        "/v1/admin/features/feature-1",
        headers={"If-Match": entity_tag},
        json={"reason": "r"},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_patch_feature_with_duplicate_if_match_lines_returns_422(
    client: TestClient,
) -> None:
    response = client.patch(
        "/v1/admin/features/feature-1",
        headers=[("If-Match", '"7"'), ("If-Match", '"7"')],
        json={"name": "x", "reason": "r"},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_patch_feature_stale_if_match_returns_412(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _submit(_session: Any, **kwargs: Any) -> FeatureChangeRequest:
        raise FeaturePreconditionFailed(
            feature_id=kwargs["feature_id"], expected=3, current=8
        )

    monkeypatch.setattr(router_mod, "submit_feature_change_request", _submit)

    response = client.patch(
        "/v1/admin/features/feature-1",
        headers={"If-Match": '"3"'},
        json={"name": "x", "reason": "r"},
    )
    assert response.status_code == 412
    body = response.json()
    assert body["code"] == "PRECONDITION_FAILED"
    assert "current=8" in body["detail"]


@pytest.mark.unit
def test_get_feature_detail_does_not_use_row_revision_as_aggregate_validator(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    _patch_admin_resolved_identity(monkeypatch)

    async def _detail(_session: Any, feature_id: str) -> AdminFeatureDetail:
        return _feature_detail()

    async def _curations(
        _session: Any, **_kwargs: Any
    ) -> dict[str, tuple[Any, ...]]:
        return {}

    monkeypatch.setattr(router_mod, "get_admin_feature_detail", _detail)
    monkeypatch.setattr(
        router_mod.curation_repo,
        "list_curation_items_by_feature_ids",
        _curations,
    )

    response = client.get(
        "/v1/admin/features/feature-1",
        headers={"If-None-Match": '"12"'},
    )
    assert response.status_code == 200
    assert "ETag" not in response.headers
    assert response.json()["data"]["feature"]["row_revision"] == 7


@pytest.mark.unit
def test_feature_state_retire_is_atomic_and_returns_audited_etag(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _transition(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        assert feature_id == "feature-1"
        assert kwargs == {
            "action": "retire",
            "publication_state": None,
            "quality_state": None,
            "expected_row_revision": 7,
            "reason_code": "admin_retire",
            "operator": "local-dev",
        }
        return AdminFeatureStateTransition(
            feature_id="feature-1",
            lifecycle_state="retired",
            publication_state="suppressed",
            quality_state="valid",
            row_revision=8,
            audit_transition_id=101,
        )

    monkeypatch.setattr(router_mod, "transition_admin_feature_state", _transition)
    response = client.patch(
        "/v1/admin/features/feature-1/state",
        headers={"If-Match": '"7"'},
        json={"action": "retire", "reason_code": "admin_retire"},
    )

    assert response.status_code == 200
    assert response.headers["ETag"] == '"8"'
    assert response.json()["data"] == {
        "feature_id": _expected_uuid("feature-1"),
        "lifecycle_state": "retired",
        "publication_state": "suppressed",
        "quality_state": "valid",
        "row_revision": 8,
        "audit_transition_id": 101,
    }
    assert session.begin_count == 1


@pytest.mark.unit
def test_feature_state_patch_accepts_only_publication_and_quality_axes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _transition(_session: Any, _feature_id: str, **kwargs: Any) -> Any:
        assert kwargs["action"] == "patch"
        assert kwargs["publication_state"] == "draft"
        assert kwargs["quality_state"] == "quarantined"
        return AdminFeatureStateTransition(
            feature_id="feature-1",
            lifecycle_state="active",
            publication_state="draft",
            quality_state="quarantined",
            row_revision=8,
            audit_transition_id=102,
        )

    monkeypatch.setattr(router_mod, "transition_admin_feature_state", _transition)
    response = client.patch(
        "/v1/admin/features/feature-1/state",
        headers={"If-Match": '"7"'},
        json={
            "action": "patch",
            "publication_state": "draft",
            "quality_state": "quarantined",
            "reason_code": "admin_state_patch",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["publication_state"] == "draft"
    assert response.json()["data"]["quality_state"] == "quarantined"


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        {"action": "patch", "reason_code": "empty_axes"},
        {"action": "retire", "publication_state": "published", "reason_code": "mixed"},
        {"action": "patch", "lifecycle_state": "active", "reason_code": "bypass"},
    ],
)
def test_feature_state_rejects_empty_or_mixed_or_lifecycle_patch(
    client: TestClient,
    body: dict[str, Any],
) -> None:
    response = client.patch(
        "/v1/admin/features/feature-1/state",
        headers={"If-Match": '"7"'},
        json=body,
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_feature_state_missing_or_stale_or_conflict_has_explicit_semantics(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _missing(_session: Any, _feature_id: str, **_kwargs: Any) -> None:
        raise AdminFeatureStateNotFound("feature 없음")

    monkeypatch.setattr(router_mod, "transition_admin_feature_state", _missing)
    missing = client.patch(
        "/v1/admin/features/missing/state",
        headers={"If-Match": '"7"'},
        json={"action": "retire", "reason_code": "missing"},
    )
    assert missing.status_code == 404

    async def _stale(_session: Any, feature_id: str, **kwargs: Any) -> None:
        raise AdminFeatureStatePreconditionFailed(
            feature_id=feature_id,
            expected=kwargs["expected_row_revision"],
        )

    monkeypatch.setattr(router_mod, "transition_admin_feature_state", _stale)
    stale = client.patch(
        "/v1/admin/features/feature-1/state",
        headers={"If-Match": '"7"'},
        json={"action": "retire", "reason_code": "stale"},
    )
    assert stale.status_code == 412

    async def _conflict(_session: Any, _feature_id: str, **_kwargs: Any) -> None:
        raise AdminFeatureStateConflict("이미 retired입니다.")

    monkeypatch.setattr(router_mod, "transition_admin_feature_state", _conflict)
    conflict = client.patch(
        "/v1/admin/features/feature-1/state",
        headers={"If-Match": '"7"'},
        json={"action": "retire", "reason_code": "already_retired"},
    )
    assert conflict.status_code == 409


@pytest.mark.unit
@pytest.mark.parametrize("entity_tag", ["7", 'W/"7"', "*", '"0"', '"007"'])
def test_feature_state_requires_canonical_strong_if_match(
    client: TestClient,
    entity_tag: str,
) -> None:
    response = client.patch(
        "/v1/admin/features/feature-1/state",
        headers={"If-Match": entity_tag},
        json={"action": "retire", "reason_code": "test"},
    )
    assert response.status_code == 422
    missing = client.patch(
        "/v1/admin/features/feature-1/state",
        json={"action": "retire", "reason_code": "test"},
    )
    assert missing.status_code == 428


@pytest.mark.unit
def test_feature_state_reactivation_requires_current_source_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _reactivate(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        assert feature_id == "feature-1"
        assert kwargs == {
            "expected_row_revision": 8,
            "reason_code": "source_revalidated",
            "operator": "local-dev",
            "provider_dataset_id": 7,
            "source_entity_key": "entity-1",
            "source_record_key": "record-1",
        }
        return AdminFeatureStateTransition(
            feature_id="feature-1",
            lifecycle_state="active",
            publication_state="suppressed",
            quality_state="valid",
            row_revision=9,
            audit_transition_id=103,
        )

    monkeypatch.setattr(router_mod, "reactivate_admin_feature_state", _reactivate)
    response = client.post(
        "/v1/admin/features/feature-1/state/reactivate",
        headers={"If-Match": '"8"'},
        json={
            "reason_code": "source_revalidated",
            "provider_dataset_id": 7,
            "source_entity_key": "entity-1",
            "source_record_key": "record-1",
        },
    )
    assert response.status_code == 200
    assert response.headers["ETag"] == '"9"'
    assert response.json()["data"]["lifecycle_state"] == "active"

    malformed = client.post(
        "/v1/admin/features/feature-1/state/reactivate",
        headers={"If-Match": '"8"'},
        json={"reason_code": "missing_evidence"},
    )
    assert malformed.status_code == 422
