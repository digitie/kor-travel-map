"""``/v1/admin/features`` 라우터 단위 테스트."""

from __future__ import annotations

import hashlib
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
    AdminFeaturePage,
    AdminFeatureRow,
    AdminFeatureStateConflict,
    AdminFeatureStateNotFound,
    AdminFeatureStatePreconditionFailed,
    AdminFeatureStateTransition,
    AdminFeatureStateTransitionAudit,
    AdminFeatureStateTransitionAuditPage,
    AdminManualFeatureCreated,
    AdminManualFeatureExactDuplicate,
    AdminManualFeatureInvariantError,
    AdminManualFeatureProvenance,
    AdminManualFeatureValidationError,
    FeatureCreationOrigin,
    ManualFeatureIdentityClaim,
)
from kortravelmap.infra.domain_command_repo import DomainCommandRecord
from sqlalchemy.exc import DBAPIError

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    DomainCommandHandle,
    DomainCommandReplay,
)
from kortravelmap.api.settings import ApiSettings

ADMIN_ACTOR = "admin:manual-feature-test"
ADMIN_PROXY_SECRET = "admin-manual-feature-proxy-secret-0000000000000000"
ADMIN_FEATURE_CREATE_TOKEN = "admin-feature-create-router-test"
IDEMPOTENCY_KEY = "95000000-0000-4000-8000-000000000001"


class _Tx:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        if exc_type is None:
            self._session.commit_count += 1
        else:
            self._session.rollback_count += 1


class _FakeSession:
    def __init__(self) -> None:
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.statements: list[str] = []

    def begin(self) -> _Tx:
        self.begin_count += 1
        return _Tx(self)

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


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
            admin_manual_feature_create_enabled=True,
            admin_feature_create_token_sha256=hashlib.sha256(
                ADMIN_FEATURE_CREATE_TOKEN.encode("utf-8")
            ).hexdigest(),
            admin_proxy_secret=ADMIN_PROXY_SECRET,
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
            return_value=DomainCommandHandle(
                command_id=1,
                actor=ADMIN_ACTOR,
                operation="admin.feature.create.manual-v1",
                idempotency_key=IDEMPOTENCY_KEY,
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
        client=("127.0.0.1", 50000),
        headers={
            "Idempotency-Key": IDEMPOTENCY_KEY,
            "X-Kor-Travel-Map-Admin-Proxy-Secret": ADMIN_PROXY_SECRET,
            "X-Kor-Travel-Map-Actor": ADMIN_ACTOR,
            "X-Kor-Travel-Map-Admin-Feature-Create-Token": (
                ADMIN_FEATURE_CREATE_TOKEN
            ),
        },
    )


def _manual_create_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "place",
        "name": "사용자 장소",
        "category": "01070300",
        "coord": {"lon": 126.98, "lat": 37.57},
        "marker_icon": "map-pin",
        "marker_color": "P-01",
        "reason": "사용자 제보",
    }
    payload.update(updates)
    return payload


def _reverse_json_object_order(value: Any) -> Any:
    """PostgreSQL jsonb 왕복이 object key 순서를 보존하지 않는 상황을 모사한다."""

    if isinstance(value, dict):
        return {
            key: _reverse_json_object_order(value[key])
            for key in reversed(value)
        }
    if isinstance(value, list):
        return [_reverse_json_object_order(item) for item in value]
    return value


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
    assert "/v1/admin/features/change-requests" not in spec["paths"]
    assert "/v1/admin/features/{feature_id}/state" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/state/reactivate" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/state/transitions" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/field-overrides" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/field-overrides/revoke" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/deactivate" not in spec["paths"]
    assert "/v1/admin/features/in-bounds" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/weather" in spec["paths"]
    assert "/v1/admin/features/{feature_id}/price" in spec["paths"]
    assert "AdminFeatureRecord" in spec["components"]["schemas"]
    assert "AdminFeatureCreateRequest" in spec["components"]["schemas"]
    assert "AdminFeaturePatchRequest" in spec["components"]["schemas"]
    assert "AdminFeatureFieldOverrideResponse" in spec["components"]["schemas"]
    assert "AdminFeatureStatePatchRequest" in spec["components"]["schemas"]
    assert "AdminFeatureStateRetireRequest" in spec["components"]["schemas"]
    assert "AdminFeatureReactivateRequest" in spec["components"]["schemas"]
    assert "AdminFeatureFieldOverrideAuthorRequest" in spec["components"]["schemas"]
    assert "AdminFeatureFieldOverrideRevokeRequest" in spec["components"]["schemas"]
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
    assert body["data"]["overrides"][0]["field_path"] == "lifecycle_state"
    assert body["data"]["state_transitions"][0]["transition_kind"] == "admin"
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
def test_feature_creation_provenance_returns_explicit_evidence_absence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """existing non-manual Feature에는 fabricated provenance 대신 null을 낸다."""

    from kortravelmap.api.routers import admin_features as router_mod

    _patch_admin_resolved_identity(monkeypatch)

    async def _read(_session: Any, *, feature_uuid: str) -> AdminManualFeatureProvenance:
        assert feature_uuid == _expected_uuid("feature-1")
        return AdminManualFeatureProvenance(
            feature_id=feature_uuid,
            claim=None,
            origin=None,
        )

    monkeypatch.setattr(router_mod, "get_admin_manual_feature_provenance", _read)

    response = client.get("/v1/admin/features/feature-1/creation-provenance")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "feature_id": "feature-1",
        "feature_uuid": _expected_uuid("feature-1"),
        "claim": None,
        "origin": None,
    }


@pytest.mark.unit
def test_feature_creation_provenance_returns_claim_and_origin(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """manual evidence는 opaque ID/UUID 쌍을 같은 snapshot으로 반환한다."""

    from kortravelmap.api.routers import admin_features as router_mod

    feature_uuid = "0198d9f1-7a31-7e52-8ea8-cb2548d3a891"
    _patch_admin_resolved_identity(monkeypatch, feature_id="manual-feature")

    async def _read(_session: Any, *, feature_uuid: str) -> AdminManualFeatureProvenance:
        return AdminManualFeatureProvenance(
            feature_id=feature_uuid,
            claim=ManualFeatureIdentityClaim(
                feature_id=feature_uuid,
                feature_kind="place",
                name_key="m02 provenance 장소",
                lon_e6=127_500_000,
                lat_e6=36_500_000,
                claim_basis="manual_create",
                claimed_at=datetime(2026, 8, 20, tzinfo=UTC),
                claimed_by_command_id=71,
            ),
            origin=FeatureCreationOrigin(
                origin_kind="manual_admin",
                creation_command_id=71,
                creator_principal_id="admin-ui-bff.manual-feature-create.v1",
                created_by_actor="admin:m02",
                created_at=datetime(2026, 8, 20, tzinfo=UTC),
                invoker_role="ktm_feature_api_runtime",
                procedure_definer="ktm_manual_feature_procedure_owner",
            ),
        )

    monkeypatch.setattr(router_mod, "get_admin_manual_feature_provenance", _read)

    # UUID path를 써도 response는 해석된 opaque ID와 UUID를 각각 돌려준다.
    async def _resolve(_session: Any, _ref: str) -> Any:
        from kortravelmap.infra.feature_identity import FeatureIdentity

        return FeatureIdentity(feature_id="manual-feature", feature_uuid=feature_uuid)

    monkeypatch.setattr(router_mod, "resolve_feature_ref_or_error", _resolve)

    response = client.get(f"/v1/admin/features/{feature_uuid}/creation-provenance")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["feature_id"] == "manual-feature"
    assert data["feature_uuid"] == feature_uuid
    assert data["claim"]["claimed_by_command_id"] == 71
    assert data["origin"] == {
        "origin_kind": "manual_admin",
        "creation_command_id": 71,
        "creator_principal_id": "admin-ui-bff.manual-feature-create.v1",
        "created_by_actor": "admin:m02",
        "created_at": "2026-08-20T00:00:00Z",
        "invoker_role": "ktm_feature_api_runtime",
        "procedure_definer": "ktm_manual_feature_procedure_owner",
    }


@pytest.mark.unit
def test_feature_creation_provenance_rejects_reader_identity_mismatch() -> None:
    """reader UUID와 resolver UUID가 다르면 opaque ID를 투영하지 않는다."""

    from kortravelmap.api.routers import admin_features as router_mod

    provenance = AdminManualFeatureProvenance(
        feature_id="0198d9f1-7a31-7e52-8ea8-cb2548d3a891",
        claim=None,
        origin=None,
    )

    with pytest.raises(AdminManualFeatureInvariantError, match="해석된 Feature identity"):
        router_mod._manual_feature_provenance_response(
            provenance,
            feature_id="feature-m04-approved",
            feature_uuid="0198d9f1-7a31-7e52-8ea8-cb2548d3a892",
            started_at=0.0,
        )


@pytest.mark.unit
def test_feature_creation_provenance_rejects_claim_identity_mismatch() -> None:
    """immutable claim UUID도 outer Feature identity와 같아야 한다."""

    from kortravelmap.api.routers import admin_features as router_mod

    feature_uuid = "0198d9f1-7a31-7e52-8ea8-cb2548d3a891"
    provenance = AdminManualFeatureProvenance(
        feature_id=feature_uuid,
        claim=ManualFeatureIdentityClaim(
            feature_id="0198d9f1-7a31-7e52-8ea8-cb2548d3a892",
            feature_kind="place",
            name_key="m02 mismatch 장소",
            lon_e6=127_500_000,
            lat_e6=36_500_000,
            claim_basis="manual_create",
            claimed_at=datetime(2026, 8, 20, tzinfo=UTC),
            claimed_by_command_id=71,
        ),
        origin=None,
    )

    with pytest.raises(AdminManualFeatureInvariantError, match="immutable claim UUID"):
        router_mod._manual_feature_provenance_response(
            provenance,
            feature_id="feature-m04-approved",
            feature_uuid=feature_uuid,
            started_at=0.0,
        )


@pytest.mark.unit
@pytest.mark.parametrize("mismatch", ["reader", "claim"])
def test_feature_creation_provenance_route_sanitizes_identity_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    """불변 UUID 불일치는 HTTP 경계에서도 evidence를 노출하지 않고 닫는다."""

    from kortravelmap.infra.feature_identity import FeatureIdentity

    from kortravelmap.api.routers import admin_features as router_mod

    feature_uuid = "0198d9f1-7a31-7e52-8ea8-cb2548d3a891"
    mismatched_uuid = "0198d9f1-7a31-7e52-8ea8-cb2548d3a892"

    async def _resolve(_session: Any, _ref: str) -> FeatureIdentity:
        return FeatureIdentity(feature_id="feature-m04-approved", feature_uuid=feature_uuid)

    async def _read(_session: Any, *, feature_uuid: str) -> AdminManualFeatureProvenance:
        return AdminManualFeatureProvenance(
            feature_id=mismatched_uuid if mismatch == "reader" else feature_uuid,
            claim=(
                None
                if mismatch == "reader"
                else ManualFeatureIdentityClaim(
                    feature_id=mismatched_uuid,
                    feature_kind="place",
                    name_key="m02 mismatch 장소",
                    lon_e6=127_500_000,
                    lat_e6=36_500_000,
                    claim_basis="manual_create",
                    claimed_at=datetime(2026, 8, 20, tzinfo=UTC),
                    claimed_by_command_id=71,
                )
            ),
            origin=None,
        )

    monkeypatch.setattr(router_mod, "resolve_feature_ref_or_error", _resolve)
    monkeypatch.setattr(router_mod, "get_admin_manual_feature_provenance", _read)
    probe = TestClient(
        client.app,
        client=("127.0.0.1", 50000),
        raise_server_exceptions=False,
        headers=client.headers,
    )
    response = probe.get("/v1/admin/features/feature-m04-approved/creation-provenance")
    probe.close()

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["status"] == 500
    assert body["detail"] == "서버 내부 오류가 발생했습니다."
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["errors"] == []
    assert "data" not in body
    assert "feature-m04-approved" not in response.text
    assert "immutable claim UUID" not in response.text


@pytest.mark.unit
def test_create_feature_authors_typed_override_receipt(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _create(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["payload"]["kind"] == "place"
        assert kwargs["payload"]["name"] == "사용자 장소"
        assert kwargs["payload"]["coord"] == {"lon": 126.98, "lat": 37.57}
        assert "feature_id" not in kwargs
        assert "lifecycle_state" not in kwargs
        assert "publication_state" not in kwargs
        assert "quality_state" not in kwargs
        assert kwargs["reason_code"] == "사용자 제보"
        assert kwargs["operator"] == ADMIN_ACTOR
        assert kwargs["command_id"] == 1
        return AdminManualFeatureCreated(
            feature_id="f_global_p_9f9480adb6abef69",
            feature_uuid="0198d9f1-7a31-7e52-8ea8-cb2548d3a891",
            row_revision=2,
            command_id=1,
            applied_field_count=7,
        )

    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", _create)

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
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert response.headers["ETag"] == '"2"'
    assert response.headers["Location"] == (
        "/v1/admin/features/0198d9f1-7a31-7e52-8ea8-cb2548d3a891"
    )
    assert body["data"]["feature_id"] == "0198d9f1-7a31-7e52-8ea8-cb2548d3a891"
    assert body["data"]["creation_origin"] == "manual_admin"
    assert body["data"]["command_id"] == 1
    assert body["data"]["applied_field_count"] == 7
    assert session.begin_count == 1
    assert session.commit_count == 1
    assert session.rollback_count == 0

    # M01 clean cutover — canonical identity는 caller 입력이 아니라 서버 발급이다.
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
    assert uuid_body.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_create_feature_name_bound_is_deferred_to_exact_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    raw_name = f" {'a' * 200} "

    async def _create(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["payload"]["name"] == raw_name
        return AdminManualFeatureCreated(
            feature_id="f_global_p_9f9480adb6abef69",
            feature_uuid="0198d9f1-7a31-7e52-8ea8-cb2548d3a891",
            row_revision=2,
            command_id=1,
            applied_field_count=7,
        )

    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", _create)

    response = client.post(
        "/v1/admin/features",
        json=_manual_create_payload(name=raw_name),
    )

    assert response.status_code == 201


@pytest.mark.unit
def test_create_feature_replay_is_byte_equivalent_and_does_not_write_twice(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    created = AdminManualFeatureCreated(
        feature_id="f_global_p_9f9480adb6abef69",
        feature_uuid="0198d9f1-7a31-7e52-8ea8-cb2548d3a891",
        row_revision=2,
        command_id=1,
        applied_field_count=7,
    )
    create = AsyncMock(return_value=created)
    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", create)
    command = DomainCommandHandle(
        command_id=1,
        actor=ADMIN_ACTOR,
        operation="admin.feature.create.manual-v1",
        idempotency_key=IDEMPOTENCY_KEY,
        request_fingerprint="a" * 64,
    )
    terminal_record: DomainCommandRecord | None = None

    async def _begin(_session: Any, **_kwargs: Any) -> DomainCommandHandle:
        if terminal_record is not None:
            raise DomainCommandReplay(terminal_record)
        return command

    async def _complete(
        _session: Any,
        *,
        command: DomainCommandHandle,
        response: Any,
        status_code: int,
        response_headers: dict[str, str],
    ) -> None:
        nonlocal terminal_record
        assert command.command_id == 1
        assert status_code == 201
        assert response_headers == {
            "ETag": '"2"',
            "Location": "/v1/admin/features/0198d9f1-7a31-7e52-8ea8-cb2548d3a891",
        }
        completed_at = datetime(2026, 8, 19, tzinfo=UTC)
        serialized = response.model_dump(mode="json")
        reordered = _reverse_json_object_order(serialized)
        assert isinstance(reordered, dict)
        assert tuple(reordered) == tuple(reversed(tuple(serialized)))
        assert tuple(reordered["data"]) == tuple(
            reversed(tuple(serialized["data"]))
        )
        terminal_record = DomainCommandRecord(
            command_id=command.command_id,
            actor=command.actor,
            operation=command.operation,
            idempotency_key=command.idempotency_key,
            fingerprint_version=1,
            request_fingerprint=command.request_fingerprint,
            response_status=status_code,
            response_body=reordered,
            response_headers=response_headers,
            claimed_at=completed_at,
            completed_at=completed_at,
        )

    begin = AsyncMock(side_effect=_begin)
    complete = AsyncMock(side_effect=_complete)
    monkeypatch.setattr(domain_command_service, "begin_domain_command", begin)
    monkeypatch.setattr(domain_command_service, "complete_domain_command", complete)

    first = client.post("/v1/admin/features", json=_manual_create_payload())
    replay = client.post("/v1/admin/features", json=_manual_create_payload())

    assert first.status_code == replay.status_code == 201
    assert first.content == replay.content
    assert replay.headers["ETag"] == first.headers["ETag"] == '"2"'
    assert replay.headers["Location"] == first.headers["Location"]
    assert replay.headers["X-Request-ID"] == first.headers["X-Request-ID"]
    assert "Idempotency-Replayed" not in first.headers
    assert replay.headers["Idempotency-Replayed"] == "true"
    create.assert_awaited_once()
    assert begin.await_count == 2
    complete.assert_awaited_once()
    assert session.begin_count == 2
    assert session.commit_count == 1
    assert session.rollback_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("headers", "expected_code"),
    [
        (
            {
                "Idempotency-Key": IDEMPOTENCY_KEY,
                "X-Kor-Travel-Map-Admin-Proxy-Secret": ADMIN_PROXY_SECRET,
                "X-Kor-Travel-Map-Actor": ADMIN_ACTOR,
            },
            "ADMIN_FEATURE_CREATE_SCOPE_REQUIRED",
        ),
        (
            {
                "Idempotency-Key": IDEMPOTENCY_KEY,
                "X-Kor-Travel-Map-Actor": ADMIN_ACTOR,
                "X-Kor-Travel-Map-Admin-Feature-Create-Token": (
                    ADMIN_FEATURE_CREATE_TOKEN
                ),
            },
            "FORBIDDEN",
        ),
        (
            {
                "Idempotency-Key": IDEMPOTENCY_KEY,
                "X-Kor-Travel-Map-Admin-Proxy-Secret": ADMIN_PROXY_SECRET,
                "X-Kor-Travel-Map-Actor": ADMIN_ACTOR,
                "X-Kor-Travel-Map-Admin-Feature-Create-Token": "wrong",
            },
            "ADMIN_FEATURE_CREATE_SCOPE_REQUIRED",
        ),
        (
            {
                "Idempotency-Key": IDEMPOTENCY_KEY,
                "X-Kor-Travel-Map-Admin-Proxy-Secret": "wrong",
                "X-Kor-Travel-Map-Actor": ADMIN_ACTOR,
                "X-Kor-Travel-Map-Admin-Feature-Create-Token": (
                    ADMIN_FEATURE_CREATE_TOKEN
                ),
            },
            "FORBIDDEN",
        ),
    ],
)
def test_manual_create_auth_failures_never_claim_or_write(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    expected_code: str,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    create = AsyncMock()
    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", create)
    probe = TestClient(
        client.app,
        client=("127.0.0.1", 50000),
        headers=headers,
    )
    response = probe.post("/v1/admin/features", json=_manual_create_payload())
    probe.close()

    assert response.status_code == 403
    assert response.json()["code"] == expected_code
    domain_command_service.begin_domain_command.assert_not_awaited()
    domain_command_service.complete_domain_command.assert_not_awaited()
    create.assert_not_awaited()
    assert session.begin_count == 0
    assert session.rollback_count == 0


@pytest.mark.unit
def test_manual_create_disabled_flag_returns_503_before_ledger(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    client.app.state.settings.admin_manual_feature_create_enabled = False
    create = AsyncMock()
    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", create)

    response = client.post("/v1/admin/features", json=_manual_create_payload())

    assert response.status_code == 503
    assert response.json()["code"] == "MANUAL_FEATURE_CREATE_NOT_READY"
    domain_command_service.begin_domain_command.assert_not_awaited()
    domain_command_service.complete_domain_command.assert_not_awaited()
    create.assert_not_awaited()
    assert session.begin_count == 0
    assert session.rollback_count == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("feature_id", "f_caller_owned"),
        ("idempotency_key", "caller-owned"),
        ("operator", "caller-owned"),
        ("lifecycle_state", "active"),
        ("publication_state", "published"),
        ("quality_state", "valid"),
    ],
)
def test_create_feature_rejects_caller_owned_identity_and_state(
    client: TestClient,
    field: str,
    value: str,
) -> None:
    payload = {
        "kind": "place",
        "name": "사용자 장소",
        "category": "01070300",
        "coord": {"lon": 126.98, "lat": 37.57},
        "marker_icon": "map-pin",
        "marker_color": "P-01",
        "reason": "사용자 제보",
        field: value,
    }
    response = client.post("/v1/admin/features", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [
        {
            "field": field,
            "message": "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.",
        }
    ]
    assert "input" not in body["errors"][0]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("coord", "expected_field"),
    [
        (None, "coord"),
        ({"lon": "126.98", "lat": 37.57}, "coord.lon"),
        ({"lon": True, "lat": 37.57}, "coord.lon"),
        ({"lon": 123.999999, "lat": 37.57}, "coord.lon"),
        ({"lon": 126.98, "lat": 39.500001}, "coord.lat"),
    ],
)
def test_create_feature_requires_strict_korea_coord(
    client: TestClient,
    coord: object,
    expected_field: str,
) -> None:
    response = client.post(
        "/v1/admin/features",
        json={
            "kind": "place",
            "name": "사용자 장소",
            "category": "01070300",
            "coord": coord,
            "marker_icon": "map-pin",
            "marker_color": "P-01",
            "reason": "사용자 제보",
        },
    )
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "field": expected_field,
            "message": "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.",
        }
    ]


@pytest.mark.unit
def test_create_feature_missing_coord_has_stable_sanitized_error(
    client: TestClient,
) -> None:
    payload = _manual_create_payload()
    payload.pop("coord")

    response = client.post("/v1/admin/features", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["errors"] == [
        {
            "field": "coord",
            "message": "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.",
        }
    ]
    assert "input" not in response.text


@pytest.mark.unit
def test_create_whitespace_only_name_reaches_named_db_validation(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    raw_name = " \t "

    async def _invalid(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["payload"]["name"] == raw_name
        raise AdminManualFeatureValidationError(
            field="name",
            constraint="ck_manual_feature_identity_claims_name_key",
        )

    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", _invalid)

    response = client.post(
        "/v1/admin/features",
        json=_manual_create_payload(name=raw_name),
    )

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "field": "name",
            "message": "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.",
        }
    ]
    assert response.json()["details"]["constraint"] == (
        "ck_manual_feature_identity_claims_name_key"
    )
    domain_command_service.complete_domain_command.assert_not_awaited()
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.unit
def test_create_preserves_raw_trimmed_multibyte_name_for_db_normalization(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    normalized_name = "가" * 170
    raw_name = f"{' ' * 20}{normalized_name}{' ' * 20}"
    assert len(raw_name) > 200
    assert len(raw_name.strip()) == 170
    assert len(raw_name.strip().encode("utf-8")) == 510

    async def _create(_session: Any, **kwargs: Any) -> AdminManualFeatureCreated:
        assert kwargs["payload"]["name"] == raw_name
        return AdminManualFeatureCreated(
            feature_id="f_global_p_9f9480adb6abef69",
            feature_uuid="0198d9f1-7a31-7e52-8ea8-cb2548d3a891",
            row_revision=2,
            command_id=1,
            applied_field_count=7,
        )

    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", _create)

    response = client.post(
        "/v1/admin/features",
        json=_manual_create_payload(name=raw_name),
    )

    assert response.status_code == 201


@pytest.mark.unit
def test_create_python_identity_validation_uses_typed_envelope_and_rolls_back(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra import feature_identity

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    async def _missing_parent(_session: Any, _ref: str) -> None:
        return None

    monkeypatch.setattr(feature_identity, "resolve_feature_identity", _missing_parent)
    create = AsyncMock()
    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", create)
    rejected_ref = "f_rejected-parent-input"

    response = client.post(
        "/v1/admin/features",
        json=_manual_create_payload(parent_feature_id=rejected_ref),
    )

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "field": "parent_feature_id",
            "message": "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.",
        }
    ]
    assert rejected_ref not in response.text
    domain_command_service.begin_domain_command.assert_awaited_once()
    domain_command_service.complete_domain_command.assert_not_awaited()
    create.assert_not_awaited()
    assert session.begin_count == 1
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.unit
def test_create_typed_db_validation_has_stable_field_and_no_terminal(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    async def _invalid(_session: Any, **_kwargs: Any) -> Any:
        raise AdminManualFeatureValidationError(
            field="coord.lon",
            constraint="ck_manual_feature_identity_coord_range",
        )

    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", _invalid)

    response = client.post("/v1/admin/features", json=_manual_create_payload())

    assert response.status_code == 422
    body = response.json()
    assert body["errors"] == [
        {
            "field": "coord.lon",
            "message": "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.",
        }
    ]
    assert body["details"]["constraint"] == (
        "ck_manual_feature_identity_coord_range"
    )
    domain_command_service.complete_domain_command.assert_not_awaited()
    assert session.begin_count == 1
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("failure", "private_fragments"),
    [
        pytest.param(
            AdminManualFeatureInvariantError(
                "receipt invariant failed for secret-feature-payload"
            ),
            ("receipt invariant", "secret-feature-payload"),
            id="trusted-receipt-invariant",
        ),
        pytest.param(
            DBAPIError(
                "CALL feature.secret_manual_create(:payload)",
                {"payload": "private-request-payload"},
                RuntimeError(
                    "driver detail: constraint ck_private_internal_causation"
                ),
                False,
            ),
            (
                "feature.secret_manual_create",
                "private-request-payload",
                "driver detail",
                "ck_private_internal_causation",
            ),
            id="unknown-dbapi",
        ),
    ],
)
def test_create_internal_fault_is_sanitized_and_rolls_back_without_terminal(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    private_fragments: tuple[str, ...],
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    async def _fail(_session: Any, **_kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", _fail)

    response = client.post("/v1/admin/features", json=_manual_create_payload())

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_SERVER_ERROR"
    assert "details" not in body
    assert body["request_id"] == response.headers["X-Request-ID"]
    for fragment in private_fragments:
        assert fragment not in response.text
    domain_command_service.complete_domain_command.assert_not_awaited()
    assert session.begin_count == 1
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.unit
def test_create_ledger_dbapi_fault_uses_m01_internal_code_without_write(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    private_fragments = (
        "ops.secret_domain_claim",
        "private-ledger-payload",
        "driver ledger detail",
        "ck_private_ledger_constraint",
    )
    begin = AsyncMock(
        side_effect=DBAPIError(
            "SELECT ops.secret_domain_claim(:payload)",
            {"payload": "private-ledger-payload"},
            RuntimeError(
                "driver ledger detail: constraint ck_private_ledger_constraint"
            ),
            False,
        )
    )
    create = AsyncMock()
    monkeypatch.setattr(domain_command_service, "begin_domain_command", begin)
    monkeypatch.setattr(router_mod, "create_admin_feature_with_field_overrides", create)
    probe = TestClient(
        client.app,
        client=("127.0.0.1", 50000),
        raise_server_exceptions=False,
        headers={
            "Idempotency-Key": IDEMPOTENCY_KEY,
            "X-Kor-Travel-Map-Admin-Proxy-Secret": ADMIN_PROXY_SECRET,
            "X-Kor-Travel-Map-Actor": ADMIN_ACTOR,
            "X-Kor-Travel-Map-Admin-Feature-Create-Token": (
                ADMIN_FEATURE_CREATE_TOKEN
            ),
        },
    )

    response = probe.post("/v1/admin/features", json=_manual_create_payload())
    probe.close()

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_SERVER_ERROR"
    assert "details" not in body
    assert body["request_id"] == response.headers["X-Request-ID"]
    for fragment in private_fragments:
        assert fragment not in response.text
    begin.assert_awaited_once()
    domain_command_service.complete_domain_command.assert_not_awaited()
    create.assert_not_awaited()
    assert session.begin_count == 1
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.unit
def test_create_feature_exact_duplicate_returns_existing_uuid(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_features as router_mod

    async def _duplicate(_session: Any, **_kwargs: Any) -> Any:
        return AdminManualFeatureExactDuplicate(
            existing_feature_uuid="0198d9f1-7a31-7e52-8ea8-cb2548d3a891"
        )

    monkeypatch.setattr(
        router_mod,
        "create_admin_feature_with_field_overrides",
        _duplicate,
    )
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
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "MANUAL_FEATURE_EXACT_DUPLICATE"
    assert response.json()["details"] == {
        "constraint": "uq_manual_feature_identity_claims_exact",
        "existing_feature_id": "0198d9f1-7a31-7e52-8ea8-cb2548d3a891",
    }
    domain_command_service.complete_domain_command.assert_not_awaited()
    assert session.begin_count == 1
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.unit
def test_patch_feature_authors_typed_override_receipt(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _patch(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["feature_id"] == "feature-1"
        assert kwargs["payload"] == {"name": "수정된 장소"}
        assert kwargs["expected_row_revision"] == 4  # If-Match row_revision
        assert kwargs["reason_code"] == "사용자 수정"
        assert kwargs["operator"] == ADMIN_ACTOR
        assert kwargs["command_id"] == 1
        return router_mod.FeatureFieldOverrideCommand(
            feature_id="feature-1",
            row_revision=5,
            command_id=1,
            applied_field_count=1,
        )

    monkeypatch.setattr(router_mod, "patch_admin_feature_with_field_overrides", _patch)

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
    assert response.json()["data"]["applied_field_count"] == 1
    assert session.begin_count == 1


@pytest.mark.unit
def test_create_strict_coord_does_not_change_patch_coercion_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    _patch_admin_resolved_identity(monkeypatch)

    async def _patch(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["payload"]["coord"] == {"lon": 126.98, "lat": 37.57}
        return router_mod.FeatureFieldOverrideCommand(
            feature_id="feature-1",
            row_revision=5,
            command_id=1,
            applied_field_count=2,
        )

    monkeypatch.setattr(router_mod, "patch_admin_feature_with_field_overrides", _patch)

    response = client.patch(
        "/v1/admin/features/feature-1",
        headers={"If-Match": '"4"'},
        json={
            "coord": {"lon": "126.98", "lat": "37.57"},
            "reason": "좌표 보정",
        },
    )

    assert response.status_code == 200


@pytest.mark.unit
def test_delete_feature_retires_with_typed_state_command(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _retire(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        assert feature_id == "feature-1"
        assert kwargs["action"] == "retire"
        assert kwargs["expected_row_revision"] == 9
        assert kwargs["reason_code"] == "사용자 삭제 요청"
        return AdminFeatureStateTransition(
            feature_id="feature-1",
            lifecycle_state="retired",
            publication_state="suppressed",
            quality_state="valid",
            row_revision=10,
            audit_transition_id=201,
        )

    monkeypatch.setattr(router_mod, "transition_admin_feature_state", _retire)

    response = client.request(
        "DELETE",
        "/v1/admin/features/feature-1",
        headers={"If-Match": '"9"'},
        json={"reason": "사용자 삭제 요청"},
    )

    assert response.status_code == 200
    assert response.headers["ETag"] == '"10"'
    assert response.json()["data"]["lifecycle_state"] == "retired"
    assert session.begin_count == 1


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

    async def _patch(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        raise router_mod.FeatureFieldOverridePreconditionFailed(
            feature_id=feature_id,
            expected=kwargs["expected_row_revision"],
        )

    monkeypatch.setattr(router_mod, "patch_admin_feature_with_field_overrides", _patch)

    response = client.patch(
        "/v1/admin/features/feature-1",
        headers={"If-Match": '"3"'},
        json={"name": "x", "reason": "r"},
    )
    assert response.status_code == 412
    body = response.json()
    assert body["code"] == "PRECONDITION_FAILED"


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
            "operator": ADMIN_ACTOR,
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
            "operator": ADMIN_ACTOR,
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


@pytest.mark.unit
def test_feature_field_override_author_uses_open_domain_command_and_etag(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    async def _author(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        assert feature_id == "feature-1"
        assert kwargs == {
            "expected_row_revision": 8,
            "reason_code": "correct_address",
            "operator": ADMIN_ACTOR,
            "command_id": 1,
            "values": {"core.address": {"road": "새 주소"}},
            "geometry_wkt": {},
        }
        return router_mod.FeatureFieldOverrideCommand(
            feature_id="feature-1",
            row_revision=9,
            command_id=1,
            applied_field_count=1,
        )

    monkeypatch.setattr(router_mod, "author_admin_feature_field_overrides", _author)
    response = client.post(
        "/v1/admin/features/feature-1/field-overrides",
        headers={"If-Match": '"8"'},
        json={
            "reason_code": "correct_address",
            "values": {"core.address": {"road": "새 주소"}},
        },
    )

    assert response.status_code == 200
    assert response.headers["ETag"] == '"9"'
    assert response.json()["data"] == {
        "feature_id": _expected_uuid("feature-1"),
        "row_revision": 9,
        "command_id": 1,
        "applied_field_count": 1,
    }
    assert session.begin_count == 1


@pytest.mark.unit
def test_feature_field_override_revoke_rejects_bad_paths_and_maps_stale_revision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_features as router_mod

    malformed = client.post(
        "/v1/admin/features/feature-1/field-overrides/revoke",
        headers={"If-Match": '"8"'},
        json={"reason_code": "restore", "field_paths": ["core.name", "core.name"]},
    )
    assert malformed.status_code == 422

    async def _stale(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        raise router_mod.FeatureFieldOverridePreconditionFailed(
            feature_id=feature_id,
            expected=kwargs["expected_row_revision"],
        )

    monkeypatch.setattr(router_mod, "revoke_admin_feature_field_overrides", _stale)
    stale = client.post(
        "/v1/admin/features/feature-1/field-overrides/revoke",
        headers={"If-Match": '"8"'},
        json={"reason_code": "restore", "field_paths": ["core.name"]},
    )
    assert stale.status_code == 412
