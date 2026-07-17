"""``/v1/admin/features/update-requests`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestIdempotency,
    FeatureUpdateRequestPage,
    FeatureUpdateRequestPreview,
)
from kortravelmap.providers.kma import (
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
)
from kortravelmap.providers.mois import DATASET_KEY_BULK, DATASET_KEY_DETAIL
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME

from kortravelmap.api import feature_update_service as service_mod
from kortravelmap.api import mois_source_precheck
from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.pipeline_cancellation_schema import PipelineCancellationDetailRecord
from kortravelmap.api.routers import feature_update_requests as router_mod
from kortravelmap.api.settings import ApiSettings

_REQUEST_ID = "22222222-2222-4222-8222-222222222222"
_MISSING_REQUEST_ID = "33333333-3333-4333-8333-333333333333"
_JOB_ID = "55555555-5555-4555-8555-555555555555"


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

    def begin_nested(self) -> _Tx:
        return _Tx()


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = create_app(ApiSettings(admin_proxy_secret=None))

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    async def _no_active_request(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _lock_idempotency(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _no_idempotency(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _record_idempotency(
        *_args: Any,
        **kwargs: Any,
    ) -> FeatureUpdateRequestIdempotency:
        return FeatureUpdateRequestIdempotency(
            idempotency_key=kwargs["idempotency_key"],
            fingerprint_version=1,
            request_fingerprint=kwargs["request_fingerprint"],
            request_id=kwargs["request_id"],
            actor=kwargs["actor"],
            reused_active_request=kwargs["reused_active_request"],
            created_at=datetime(2026, 6, 3, tzinfo=UTC),
        )

    async def _ready_mois_source_sync(
        _resolved_pairs: frozenset[tuple[str, str]],
        **_kwargs: Any,
    ) -> None:
        return None

    app.dependency_overrides[get_session] = _fake_session
    monkeypatch.setattr(
        service_mod,
        "find_active_provider_dataset_request",
        _no_active_request,
    )
    monkeypatch.setattr(
        service_mod,
        "lock_feature_update_request_idempotency",
        _lock_idempotency,
    )
    monkeypatch.setattr(
        service_mod,
        "get_feature_update_request_idempotency",
        _no_idempotency,
    )
    monkeypatch.setattr(
        service_mod,
        "create_feature_update_request_idempotency",
        _record_idempotency,
    )
    monkeypatch.setattr(
        mois_source_precheck,
        "ensure_mois_source_sync_for_plan",
        _ready_mois_source_sync,
    )
    return TestClient(
        app,
        headers={"Idempotency-Key": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
    )


def _request(
    *,
    request_id: str = _REQUEST_ID,
    job_id: str = _JOB_ID,
    state: str = "queued",
    run_mode: str = "queued",
    dispatch_requested_at: datetime | None = None,
) -> FeatureUpdateRequest:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return FeatureUpdateRequest(
        request_id=request_id,
        scope_type="feature_ids",
        scope={"type": "feature_ids", "feature_ids": ["feature-1"]},
        providers=(MOIS_PROVIDER_NAME,),
        dataset_keys=(DATASET_KEY_BULK,),
        update_policy={"mode": "refresh_existing"},
        run_mode=run_mode,
        priority=50,
        status=state,
        matched_scope={"feature_count": 1, "sigungu_codes": []},
        job_id=job_id,
        dagster_run_id=None,
        operator="tester",
        reason="unit",
        error_message=None,
        created_at=now,
        started_at=None,
        finished_at=None,
        generation=1,
        dispatch_requested_at=dispatch_requested_at,
    )


def _cancellation_detail(request_id: str) -> PipelineCancellationDetailRecord:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return PipelineCancellationDetailRecord.model_validate(
        {
            "cancellation_id": "77777777-7777-4777-8777-777777777777",
            "previous_cancellation_id": None,
            "root": {"kind": "update_request", "id": request_id},
            "status": "completed",
            "requested_at": now,
            "requested_by": "local-dev",
            "reason": "stop",
            "error": None,
            "updated_at": now,
            "finished_at": now,
            "retryable": False,
            "unresolved_member_count": 0,
            "members": [
                {
                    "job_id": _JOB_ID,
                    "dagster_run_id": None,
                    "operation_kind": None,
                    "requires_run_termination": False,
                    "initial_status": "queued",
                    "result": "cancelled",
                    "terminal_status": "cancelled",
                    "error": None,
                    "updated_at": now,
                }
            ],
            "dagster_runs": [],
        }
    )


def _preview() -> FeatureUpdateRequestPreview:
    return FeatureUpdateRequestPreview(
        scope_type="feature_ids",
        scope={"type": "feature_ids", "feature_ids": ["feature-1"]},
        providers=(MOIS_PROVIDER_NAME,),
        dataset_keys=(DATASET_KEY_BULK,),
        update_policy={},
        run_mode="queued",
        priority=50,
        matched_scope={"feature_count": 1, "sigungu_codes": []},
    )


@pytest.mark.unit
def test_update_request_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/features/update-requests" in spec["paths"]
    assert "/v1/admin/features/update-requests/preview" in spec["paths"]
    assert "/v1/admin/features/update-requests/{request_id}" in spec["paths"]
    assert "/v1/admin/features/update-requests/{request_id}/cancel" in spec["paths"]
    assert "/v1/admin/features/update-requests/{request_id}/run-now" in spec["paths"]
    assert "/v1/admin/feature-update-requests" not in spec["paths"]
    assert "/v1/admin/feature-update-requests/{request_id}" not in spec["paths"]
    assert "FeatureUpdateRequestCreateRequest" in spec["components"]["schemas"]
    assert "FeatureUpdateRequestRecord" in spec["components"]["schemas"]
    assert "FeatureUpdateRequestCreatedRecord" in spec["components"]["schemas"]
    assert "FeatureUpdateRequestPreviewRecord" in spec["components"]["schemas"]
    assert "FeatureUpdateRequestPreviewRequest" in spec["components"]["schemas"]
    assert "FeatureUpdateRequestPreviewResponse" in spec["components"]["schemas"]
    assert "FeatureUpdateRequestMutationResponse" in spec["components"]["schemas"]
    record_schema = spec["components"]["schemas"]["FeatureUpdateRequestRecord"]
    assert {
        "request_id",
        "job_id",
        "dagster_run_id",
        "requested_sync_scope",
        "effective_sync_scope",
        "dispatch_requested_at",
        "created_at",
        "started_at",
        "finished_at",
        "generation",
        "status_url",
    } <= set(record_schema["required"])
    assert record_schema["properties"]["request_id"]["format"] == "uuid"
    assert record_schema["properties"]["job_id"]["format"] == "uuid"
    assert record_schema["properties"]["scope"]["discriminator"]["propertyName"] == "type"
    assert len(record_schema["properties"]["scope"]["oneOf"]) == 6
    assert record_schema["properties"]["update_policy"]["$ref"].endswith("/FeatureUpdatePolicy")
    preview_schema = spec["components"]["schemas"]["FeatureUpdateRequestPreviewRecord"]
    assert {
        "request_id",
        "job_id",
        "dagster_run_id",
        "created_at",
        "started_at",
        "finished_at",
        "generation",
        "status_url",
    }.isdisjoint(preview_schema["properties"])
    create_data_schema = spec["components"]["schemas"]["FeatureUpdateRequestCreateResponse"][
        "properties"
    ]["data"]
    assert create_data_schema["$ref"].endswith("/FeatureUpdateRequestCreatedRecord")
    reused_response = spec["paths"]["/v1/admin/features/update-requests"]["post"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert reused_response["$ref"].endswith("/FeatureUpdateRequestCreateResponse")
    create_operation = spec["paths"]["/v1/admin/features/update-requests"]["post"]
    idempotency_header = next(
        parameter
        for parameter in create_operation["parameters"]
        if parameter["name"] == "Idempotency-Key"
    )
    assert idempotency_header["required"] is True
    assert idempotency_header["schema"]["format"] == "uuid"
    assert {
        "data",
        "idempotent_replay",
        "reused_active_request",
        "meta",
    } <= set(spec["components"]["schemas"]["FeatureUpdateRequestCreateResponse"]["required"])
    create_responses = spec["paths"]["/v1/admin/features/update-requests"]["post"]["responses"]
    for code in ("409", "502", "503"):
        schema = create_responses[code]["content"]["application/problem+json"]["schema"]
        assert schema["$ref"].endswith("/ProblemDetail")
    preview_response = spec["paths"]["/v1/admin/features/update-requests/preview"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert preview_response["$ref"].endswith("/FeatureUpdateRequestPreviewResponse")
    run_now_response = spec["paths"]["/v1/admin/features/update-requests/{request_id}/run-now"][
        "post"
    ]["responses"]["200"]["content"]["application/json"]["schema"]
    assert run_now_response["$ref"].endswith("/FeatureUpdateRequestMutationResponse")
    request_schema = spec["components"]["schemas"]["FeatureUpdateRequestCreateRequest"]
    assert "dry_run" not in request_schema["properties"]
    assert "operator" not in request_schema["properties"]
    preview_request_schema = spec["components"]["schemas"]["FeatureUpdateRequestPreviewRequest"]
    assert "dry_run" not in preview_request_schema["properties"]
    sigungu_match = spec["components"]["schemas"]["SigunguByRadiusScope"]["properties"]["match"]
    assert sigungu_match["const"] == "intersects"
    scope_schema = request_schema["properties"]["scope"]
    assert scope_schema["discriminator"]["propertyName"] == "type"
    assert len(scope_schema["oneOf"]) == 6
    assert request_schema["properties"]["providers"]["maxItems"] == 32
    assert request_schema["properties"]["providers"]["uniqueItems"] is True
    assert request_schema["properties"]["dataset_keys"]["maxItems"] == 64
    assert request_schema["properties"]["dataset_keys"]["uniqueItems"] is True
    assert request_schema["properties"]["priority"]["minimum"] == 0
    assert request_schema["properties"]["priority"]["maximum"] == 1000
    bbox_properties = spec["components"]["schemas"]["BboxScope"]["properties"]
    for field in ("min_lon", "max_lon"):
        assert bbox_properties[field]["minimum"] == -180
        assert bbox_properties[field]["maximum"] == 180
        assert {"ge", "le"}.isdisjoint(bbox_properties[field])
    for field in ("min_lat", "max_lat"):
        assert bbox_properties[field]["minimum"] == -90
        assert bbox_properties[field]["maximum"] == 90
        assert {"ge", "le"}.isdisjoint(bbox_properties[field])
    point_properties = spec["components"]["schemas"]["FeatureUpdatePoint"]["properties"]
    assert point_properties["lon"]["minimum"] == -180
    assert point_properties["lon"]["maximum"] == 180
    assert point_properties["lat"]["minimum"] == -90
    assert point_properties["lat"]["maximum"] == 90
    for scope_name in ("CenterRadiusScope", "SigunguByRadiusScope"):
        radius_schema = spec["components"]["schemas"][scope_name]["properties"]["radius_km"]
        assert radius_schema["exclusiveMinimum"] == 0
        assert radius_schema["maximum"] == 500
        assert {"gt", "le"}.isdisjoint(radius_schema)
    reason_schema = next(
        item
        for item in request_schema["properties"]["reason"]["anyOf"]
        if item.get("type") == "string"
    )
    assert reason_schema["minLength"] == 1
    assert reason_schema["maxLength"] == 500
    assert (
        spec["components"]["schemas"]["FeatureIdsScope"]["properties"]["feature_ids"]["uniqueItems"]
        is True
    )
    assert (
        spec["components"]["schemas"]["CacheTargetKeysScope"]["properties"]["target_keys"][
            "uniqueItems"
        ]
        is True
    )
    assert (
        spec["components"]["schemas"]["CacheTargetKeysScope"]["properties"]["external_system"][
            "maxLength"
        ]
        == 112
    )
    update_policy_schema = spec["components"]["schemas"]["FeatureUpdatePolicy"]
    assert update_policy_schema["additionalProperties"] is False
    assert "required" not in update_policy_schema
    assert update_policy_schema["properties"]["include_inactive"]["type"] == "boolean"
    assert "anyOf" not in update_policy_schema["properties"]["include_inactive"]
    list_parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in spec["paths"]["/v1/admin/features/update-requests"]["get"]["parameters"]
    }
    assert set(list_parameters["scope_type"]["anyOf"][0]["enum"]) == {
        "feature_ids",
        "center_radius",
        "sigungu_by_radius",
        "bbox",
        "provider_dataset",
        "cache_target_keys",
    }
    for path, method in (
        ("/v1/admin/features/update-requests/{request_id}", "get"),
        ("/v1/admin/features/update-requests/{request_id}/cancel", "post"),
        ("/v1/admin/features/update-requests/{request_id}/run-now", "post"),
    ):
        parameter = spec["paths"][path][method]["parameters"][0]
        assert parameter["schema"]["format"] == "uuid"
    cancel_operation = spec["paths"]["/v1/admin/features/update-requests/{request_id}/cancel"][
        "post"
    ]
    assert {"200", "404", "409", "422", "502", "503", "default"} <= set(
        cancel_operation["responses"]
    )
    for status_code in ("409", "502", "503"):
        assert cancel_operation["responses"][status_code]["headers"]["Retry-After"]["schema"] == {
            "type": "integer"
        }
    for path in (
        "/v1/admin/features/update-requests",
        "/v1/admin/features/update-requests/{request_id}/run-now",
    ):
        conflict = spec["paths"][path]["post"]["responses"]["409"]
        assert "headers" not in conflict


@pytest.mark.unit
def test_preview_returns_preview_without_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequestPreview:
        assert kwargs["scope"] == {"type": "feature_ids", "feature_ids": ["feature-1"]}
        return _preview()

    monkeypatch.setattr(service_mod, "preview_feature_update_request_repo", _enqueue)

    response = client.post(
        "/v1/admin/features/update-requests/preview",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["result_kind"] == "preview"
    assert {
        "request_id",
        "job_id",
        "dagster_run_id",
        "created_at",
        "started_at",
        "finished_at",
        "generation",
        "status_url",
    }.isdisjoint(body["data"])
    assert body["data"]["matched_scope"]["feature_count"] == 1
    assert session.begin_count == 0


@pytest.mark.unit
def test_unfiltered_non_direct_preview_is_rejected_before_resolution(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_preview(
        _session: Any,
        **_kwargs: Any,
    ) -> FeatureUpdateRequestPreview:
        raise AssertionError("unbounded non-direct request must fail before resolution")

    monkeypatch.setattr(
        service_mod,
        "preview_feature_update_request_repo",
        _unexpected_preview,
    )

    response = client.post(
        "/v1/admin/features/update-requests/preview",
        json={"scope": {"type": "feature_ids", "feature_ids": ["feature-1"]}},
    )

    assert response.status_code == 422
    assert "filter를 하나 이상" in response.json()["detail"]
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_rejects_dry_run_flag(client: TestClient, session: _FakeSession) -> None:
    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_actual_request_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["priority"] == 75
        assert kwargs["operator"] == "local-dev"
        return _request()

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
            "run_mode": "queued",
            "priority": 75,
        },
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["result_kind"] == "request"
    assert data["job_id"] == _JOB_ID
    assert data["created_at"] is not None
    assert data["generation"] == 1
    assert response.json()["reused_active_request"] is False
    assert response.json()["idempotent_replay"] is False
    assert data["status_url"] == (f"/v1/admin/features/update-requests/{_REQUEST_ID}")
    assert session.begin_count == 1


@pytest.mark.unit
def test_create_requires_uuid_idempotency_key(client: TestClient) -> None:
    del client.headers["Idempotency-Key"]

    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
        },
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_create_idempotency_replays_canonical_body_and_conflicts_on_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping: FeatureUpdateRequestIdempotency | None = None
    terminal = replace(_request(), state="done", operator="local-dev", reason="same")

    async def _enqueue(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        return replace(_request(), operator="local-dev", reason="same")

    async def _get_mapping(*_args: Any, **_kwargs: Any) -> Any:
        return mapping

    async def _insert_mapping(
        *_args: Any,
        **kwargs: Any,
    ) -> FeatureUpdateRequestIdempotency:
        nonlocal mapping
        mapping = FeatureUpdateRequestIdempotency(
            idempotency_key=kwargs["idempotency_key"],
            fingerprint_version=1,
            request_fingerprint=kwargs["request_fingerprint"],
            request_id=kwargs["request_id"],
            actor=kwargs["actor"],
            reused_active_request=kwargs["reused_active_request"],
            created_at=datetime(2026, 6, 3, tzinfo=UTC),
        )
        return mapping

    async def _get_request(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        return terminal

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _enqueue)
    monkeypatch.setattr(
        service_mod,
        "get_feature_update_request_idempotency",
        _get_mapping,
    )
    monkeypatch.setattr(
        service_mod,
        "create_feature_update_request_idempotency",
        _insert_mapping,
    )
    monkeypatch.setattr(service_mod, "get_update_request", _get_request)

    base = {
        "providers": [MOIS_PROVIDER_NAME],
        "dataset_keys": [DATASET_KEY_BULK],
        "reason": "same",
    }
    first = client.post(
        "/v1/admin/features/update-requests",
        json={
            **base,
            "scope": {
                "type": "feature_ids",
                "feature_ids": ["feature-b", "feature-a"],
            },
        },
    )
    replay = client.post(
        "/v1/admin/features/update-requests",
        json={
            **base,
            "scope": {
                "type": "feature_ids",
                "feature_ids": ["feature-a", "feature-b"],
            },
        },
    )
    mismatch = client.post(
        "/v1/admin/features/update-requests",
        json={
            **base,
            "reason": "different",
            "scope": {
                "type": "feature_ids",
                "feature_ids": ["feature-a", "feature-b"],
            },
        },
    )

    assert first.status_code == 201
    assert first.json()["idempotent_replay"] is False
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["data"]["status"] == "done"
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "FEATURE_UPDATE_IDEMPOTENCY_CONFLICT"
    assert mismatch.json()["details"]["request_id"] == _REQUEST_ID


@pytest.mark.unit
def test_distinct_keys_enqueue_the_same_canonical_set_plan(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[dict[str, Any]] = []
    ledger_keys: list[str] = []

    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        enqueued.append(kwargs)
        return replace(
            _request(request_id=str(uuid4())),
            scope=kwargs["scope"],
            providers=tuple(kwargs["providers"]),
            dataset_keys=tuple(kwargs["dataset_keys"]),
            operator=kwargs["operator"],
            reason=kwargs["reason"],
        )

    async def _insert_mapping(
        *_args: Any,
        **kwargs: Any,
    ) -> FeatureUpdateRequestIdempotency:
        ledger_keys.append(kwargs["idempotency_key"])
        return FeatureUpdateRequestIdempotency(
            idempotency_key=kwargs["idempotency_key"],
            fingerprint_version=1,
            request_fingerprint=kwargs["request_fingerprint"],
            request_id=kwargs["request_id"],
            actor=kwargs["actor"],
            reused_active_request=kwargs["reused_active_request"],
            created_at=datetime(2026, 6, 3, tzinfo=UTC),
        )

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _enqueue)
    monkeypatch.setattr(
        service_mod,
        "create_feature_update_request_idempotency",
        _insert_mapping,
    )
    first_key = "10000000-0000-4000-8000-000000000001"
    second_key = "10000000-0000-4000-8000-000000000002"
    base = {
        "providers": [MOIS_PROVIDER_NAME],
        "reason": "canonical plan",
    }
    first = client.post(
        "/v1/admin/features/update-requests",
        headers={"Idempotency-Key": first_key},
        json={
            **base,
            "dataset_keys": [DATASET_KEY_DETAIL, DATASET_KEY_BULK],
            "scope": {
                "type": "feature_ids",
                "feature_ids": ["feature-b", "feature-a"],
            },
        },
    )
    second = client.post(
        "/v1/admin/features/update-requests",
        headers={"Idempotency-Key": second_key},
        json={
            **base,
            "dataset_keys": [DATASET_KEY_BULK, DATASET_KEY_DETAIL],
            "scope": {
                "type": "feature_ids",
                "feature_ids": ["feature-a", "feature-b"],
            },
        },
    )

    assert (first.status_code, second.status_code) == (201, 201)
    assert ledger_keys == [first_key, second_key]
    assert len(enqueued) == 2
    assert (
        enqueued[0]["scope"]
        == enqueued[1]["scope"]
        == {
            "type": "feature_ids",
            "feature_ids": ["feature-a", "feature-b"],
        }
    )
    assert (
        enqueued[0]["dataset_keys"]
        == enqueued[1]["dataset_keys"]
        == tuple(sorted((DATASET_KEY_BULK, DATASET_KEY_DETAIL)))
    )


@pytest.mark.unit
def test_kma_default_scope_records_requested_and_effective_scope_separately(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["effective_sync_scope"] == "target_grids"
        return replace(
            _request(),
            scope_type="provider_dataset",
            scope={
                "type": "provider_dataset",
                "provider": KMA_PROVIDER_NAME,
                "dataset_key": KMA_SHORT_FORECAST_DATASET_KEY,
            },
            providers=(),
            dataset_keys=(),
            effective_sync_scope="target_grids",
        )

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": KMA_PROVIDER_NAME,
                "dataset_key": KMA_SHORT_FORECAST_DATASET_KEY,
            }
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["requested_sync_scope"] is None
    assert response.json()["data"]["effective_sync_scope"] == "target_grids"


@pytest.mark.unit
def test_kma_explicit_default_reuses_omitted_default_active_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = replace(
        _request(),
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider": KMA_PROVIDER_NAME,
            "dataset_key": KMA_SHORT_FORECAST_DATASET_KEY,
        },
        providers=(),
        dataset_keys=(),
        update_policy={},
        operator="local-dev",
        reason="same",
        effective_sync_scope="target_grids",
    )

    async def _active(*_args: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["sync_scope"] == "target_grids"
        return existing

    async def _unexpected_enqueue(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise AssertionError("canonical default scope must reuse the active request")

    monkeypatch.setattr(service_mod, "find_active_provider_dataset_request", _active)
    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _unexpected_enqueue)

    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": KMA_PROVIDER_NAME,
                "dataset_key": KMA_SHORT_FORECAST_DATASET_KEY,
                "sync_scope": "target_grids",
            },
            "reason": "same",
        },
    )

    assert response.status_code == 200
    assert response.json()["reused_active_request"] is True
    assert response.json()["data"]["request_id"] == existing.request_id


@pytest.mark.unit
def test_non_direct_kma_selection_is_rejected_before_enqueue(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_enqueue(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise AssertionError("non-direct KMA selection must not enqueue")

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _unexpected_enqueue)

    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [KMA_PROVIDER_NAME],
        },
    )

    assert response.status_code == 422
    assert "provider_dataset scope" in response.json()["detail"]
    assert session.begin_count == 1


@pytest.mark.unit
def test_kma_external_system_scope_requires_active_targets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _has_targets(
        _session: Any,
        *,
        external_system: str,
    ) -> bool:
        calls.append(external_system)
        return external_system == "concierge"

    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        return replace(
            _request(),
            scope_type="provider_dataset",
            scope=dict(kwargs["scope"]),
            providers=(),
            dataset_keys=(),
            effective_sync_scope=kwargs["effective_sync_scope"],
        )

    monkeypatch.setattr(
        service_mod,
        "has_active_poi_cache_targets_for_external_system",
        _has_targets,
    )
    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _enqueue)
    scope = {
        "type": "provider_dataset",
        "provider": KMA_PROVIDER_NAME,
        "dataset_key": KMA_SHORT_FORECAST_DATASET_KEY,
        "sync_scope": "external_system:concierge",
    }

    response = client.post(
        "/v1/admin/features/update-requests",
        json={"scope": scope},
    )

    assert response.status_code == 201
    assert calls == ["concierge"]
    assert response.json()["data"]["requested_sync_scope"] == ("external_system:concierge")
    assert response.json()["data"]["effective_sync_scope"] == ("external_system:concierge")

    response = client.post(
        "/v1/admin/features/update-requests",
        json={"scope": {**scope, "sync_scope": "external_system:missing"}},
    )
    assert response.status_code == 422
    assert "활성 POI cache target이 없는" in response.json()["detail"]


@pytest.mark.unit
def test_legacy_update_request_aliases_are_not_mounted(
    client: TestClient,
    session: _FakeSession,
) -> None:
    for prefix in (
        "/feature-update-requests",
        "/v1/admin/feature-update-requests",
    ):
        response = client.post(
            prefix,
            json={
                "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
                "run_mode": "queued",
            },
        )
        assert response.status_code == 404
        assert client.get(f"{prefix}/{_REQUEST_ID}").status_code == 404
    assert session.begin_count == 0


@pytest.mark.unit
def test_preview_rejects_legacy_center_radius_shape_before_enqueue(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_enqueue(_session: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise AssertionError("validation should run before enqueue")

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _unexpected_enqueue)

    response = client.post(
        "/v1/admin/features/update-requests/preview",
        json={
            "scope": {
                "type": "center_radius",
                "lon": 127.0,
                "lat": 37.0,
                "radius_km": 5,
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_rejects_unknown_update_policy_key(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "update_policy": {"surprise": True},
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "surprise" in str(body["errors"])
    assert session.begin_count == 0


@pytest.mark.unit
@pytest.mark.parametrize("invalid_value", ["false", 0, None])
@pytest.mark.parametrize(
    "path",
    [
        "/v1/admin/features/update-requests",
        "/v1/admin/features/update-requests/preview",
    ],
)
def test_request_rejects_non_boolean_update_policy_value(
    client: TestClient,
    session: _FakeSession,
    path: str,
    invalid_value: Any,
) -> None:
    response = client.post(
        path,
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "update_policy": {"include_inactive": invalid_value},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/v1/admin/features/update-requests",
            {
                "scope": {
                    "type": "center_radius",
                    "center": {"lon": "127.0", "lat": 37.0},
                    "radius_km": 5,
                }
            },
        ),
        (
            "/v1/admin/features/update-requests/preview",
            {
                "scope": {
                    "type": "center_radius",
                    "center": {"lon": 127.0, "lat": 37.0},
                    "radius_km": True,
                }
            },
        ),
        (
            "/v1/admin/features/update-requests",
            {
                "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
                "priority": "75",
            },
        ),
        (
            f"/v1/admin/features/update-requests/{_REQUEST_ID}/run-now",
            {"priority": True},
        ),
        (
            "/v1/admin/features/update-requests",
            {
                "scope": {
                    "type": "center_radius",
                    "center": {"lon": 10**1000, "lat": 37},
                    "radius_km": 5,
                }
            },
        ),
    ],
)
def test_request_rejects_coerced_numeric_input(
    client: TestClient,
    session: _FakeSession,
    path: str,
    body: dict[str, Any],
) -> None:
    response = client.post(path, json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


@pytest.mark.unit
@pytest.mark.parametrize("reason", ["   ", "x" * 501])
def test_request_rejects_invalid_audit_reason(
    client: TestClient,
    session: _FakeSession,
    reason: str,
) -> None:
    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": []},
            "reason": reason,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "scope"),
    [
        (
            "/v1/admin/features/update-requests",
            {"type": "feature_ids", "feature_ids": ["feature-1", "feature-1"]},
        ),
        (
            "/v1/admin/features/update-requests/preview",
            {
                "type": "cache_target_keys",
                "external_system": "pinvi",
                "target_keys": ["poi-1", "poi-1"],
            },
        ),
    ],
)
def test_request_rejects_duplicate_scope_items(
    client: TestClient,
    session: _FakeSession,
    path: str,
    scope: dict[str, Any],
) -> None:
    response = client.post(path, json={"scope": scope})

    assert response.status_code == 422
    assert "unique" in str(response.json()["errors"])
    assert session.begin_count == 0


@pytest.mark.unit
def test_cache_target_scope_accepts_max_external_system_identity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external_system = "x" * 112

    async def _preview_request(
        _session: Any,
        **kwargs: Any,
    ) -> FeatureUpdateRequestPreview:
        assert kwargs["scope"]["external_system"] == external_system
        return _preview()

    monkeypatch.setattr(
        service_mod,
        "preview_feature_update_request_repo",
        _preview_request,
    )

    response = client.post(
        "/v1/admin/features/update-requests/preview",
        json={
            "scope": {
                "type": "cache_target_keys",
                "external_system": external_system,
                "target_keys": ["target-1"],
            },
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
        },
    )

    assert response.status_code == 200


@pytest.mark.unit
def test_cache_target_scope_rejects_impossible_external_system_identity(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.post(
        "/v1/admin/features/update-requests/preview",
        json={
            "scope": {
                "type": "cache_target_keys",
                "external_system": "x" * 113,
                "target_keys": ["target-1"],
            },
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
        },
    )

    assert response.status_code == 422
    assert session.begin_count == 0


@pytest.mark.unit
def test_request_rejects_redundant_provider_dataset_filters(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            },
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
        },
    )

    assert response.status_code == 422
    assert "must not repeat" in str(response.json()["errors"])
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_rejects_unbounded_provider_filter_list(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [f"python-provider-{index}-api" for index in range(33)],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_rejects_duplicate_filter_items(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [MOIS_PROVIDER_NAME, MOIS_PROVIDER_NAME],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "unique" in str(response.json()["errors"])
    assert session.begin_count == 0


@pytest.mark.unit
def test_preview_rejects_non_refreshable_provider_dataset_before_enqueue(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_enqueue(_session: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise AssertionError("non-refreshable request should be rejected")

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _unexpected_enqueue)

    response = client.post(
        "/v1/admin/features/update-requests/preview",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_DETAIL],
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert MOIS_PROVIDER_NAME in body["detail"]
    assert DATASET_KEY_DETAIL in body["detail"]
    assert session.begin_count == 0


@pytest.mark.unit
def test_preview_sigungu_scope_without_kor_travel_geo_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Settings:
        kor_travel_geo_base_url = None

    monkeypatch.setattr(router_mod, "KorTravelMapSettings", _Settings)

    response = client.post(
        "/v1/admin/features/update-requests/preview",
        json={
            "scope": {
                "type": "sigungu_by_radius",
                "center": {"lon": 127.0, "lat": 37.0},
                "radius_km": 5,
            },
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
        },
    )

    assert response.status_code == 503
    assert "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL" in response.json()["detail"]


@pytest.mark.unit
def test_list_requests_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _list(_session: Any, **kwargs: Any) -> FeatureUpdateRequestPage:
        assert kwargs["status"] == "queued"
        assert kwargs["scope_type"] == "feature_ids"
        assert kwargs["provider"] == "python-a-api"
        assert kwargs["dataset_key"] == "dataset-a"
        assert kwargs["limit"] == 25
        return FeatureUpdateRequestPage(items=(_request(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_update_requests", _list)

    response = client.get(
        "/v1/admin/features/update-requests",
        params={
            "status": "queued",
            "scope_type": "feature_ids",
            "provider": "python-a-api",
            "dataset_key": "dataset-a",
            "page_size": 25,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "next",
        "total": None,
    }
    assert body["data"]["items"][0]["request_id"] == _REQUEST_ID
    assert body["data"]["items"][0]["status"] == "queued"


@pytest.mark.unit
def test_list_requests_rejects_unknown_scope_type(client: TestClient) -> None:
    response = client.get(
        "/v1/admin/features/update-requests",
        params={"scope_type": "unknown"},
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_get_request_404_when_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _missing(_session: Any, _request_id: str) -> None:
        return None

    monkeypatch.setattr(router_mod, "get_update_request", _missing)

    response = client.get(f"/v1/admin/features/update-requests/{_MISSING_REQUEST_ID}")

    assert response.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/admin/features/update-requests/not-a-uuid"),
        ("post", "/v1/admin/features/update-requests/not-a-uuid/run-now"),
    ],
)
def test_request_resource_rejects_malformed_uuid(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.request(method, path)

    assert response.status_code == 422


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/v1/admin/features/update-requests",
            {
                "scope": {"type": "feature_ids", "feature_ids": []},
                "operator": "spoofed",
            },
        ),
        (
            f"/v1/admin/features/update-requests/{_REQUEST_ID}/run-now",
            {"operator": "spoofed"},
        ),
    ],
)
def test_request_mutations_reject_operator_override(
    client: TestClient,
    path: str,
    body: dict[str, Any],
) -> None:
    response = client.post(path, json=body)

    assert response.status_code == 422


@pytest.mark.unit
def test_cancel_request_delegates_canonical_admin_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = _REQUEST_ID
    calls: list[dict[str, Any]] = []

    async def _cancel(**kwargs: Any) -> PipelineCancellationDetailRecord:
        calls.append(kwargs)
        return _cancellation_detail(request_id)

    monkeypatch.setattr(
        router_mod.pipeline_cancellation_service,
        "cancel_pipeline_execution",
        _cancel,
    )

    response = client.post(
        f"/v1/admin/features/update-requests/{request_id}/cancel",
        json={"reason": "stop"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "completed"
    assert calls[0]["kind"] == "update_request"
    assert calls[0]["execution_id"] == request_id
    assert calls[0]["requested_by"] == "local-dev"
    assert calls[0]["reason"] == "stop"
    assert calls[0]["engine"] is not None
    assert isinstance(calls[0]["settings"], ApiSettings)
    assert calls[0]["http_client"] is not None


@pytest.mark.unit
def test_cancel_request_rejects_actor_override(client: TestClient) -> None:
    request_id = _REQUEST_ID
    response = client.post(
        f"/v1/admin/features/update-requests/{request_id}/cancel",
        json={"actor": "spoofed"},
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_run_now_dispatches_same_canonical_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, request_id: str) -> FeatureUpdateRequest:
        assert request_id == _REQUEST_ID
        return _request()

    async def _dispatch(_session: Any, request_id: str) -> FeatureUpdateRequest:
        assert request_id == _REQUEST_ID
        return _request(
            dispatch_requested_at=datetime(2026, 6, 3, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(service_mod, "get_update_request", _get)
    monkeypatch.setattr(service_mod, "request_feature_update_dispatch", _dispatch)

    response = client.post(
        f"/v1/admin/features/update-requests/{_REQUEST_ID}/run-now",
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["request_id"] == _REQUEST_ID
    assert body["data"]["job_id"] == _JOB_ID
    assert body["data"]["run_mode"] == "queued"
    assert body["data"]["dispatch_requested_at"] is not None
    assert body["data"]["generation"] == 1


@pytest.mark.unit
def test_run_now_rejects_running_request_with_cancellation_requested(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session: Any, _request_id: str) -> FeatureUpdateRequest:
        return replace(
            _request(state="running"),
            cancellation_id="77777777-7777-4777-8777-777777777777",
        )

    monkeypatch.setattr(service_mod, "get_update_request", _get)

    response = client.post(
        f"/v1/admin/features/update-requests/{_REQUEST_ID}/run-now",
        json={},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "REQUEST_NOT_DISPATCHABLE"
    assert response.json()["details"]["status"] == "cancellation_requested"


@pytest.mark.unit
def test_create_run_now_lock_busy_returns_retry_after(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise FeatureUpdateLockBusy(retry_after_seconds=15)

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
            "run_mode": "now",
        },
    )

    assert response.status_code == 409
    assert response.headers["retry-after"] == "15"
    body = response.json()
    assert body["code"] == "LOCK_BUSY"
    assert body["details"]["retry_after_seconds"] == 15


@pytest.mark.unit
def test_create_unknown_enqueue_error_hides_internal_message(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise RuntimeError("secret DSN leaked")

    monkeypatch.setattr(service_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/v1/admin/features/update-requests",
        json={
            "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
            "providers": [MOIS_PROVIDER_NAME],
            "dataset_keys": [DATASET_KEY_BULK],
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == ("feature update request enqueue failed")
