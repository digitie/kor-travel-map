"""ADR-081 cache-target service/admin API entry point contract tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra import cache_target_event_cursor
from kortravelmap.infra.cache_target_stream_repo import CacheTargetStreamConflict
from pydantic import ValidationError

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import CACHE_TARGET_CONSUMER_HEADER, SERVICE_TOKEN_HEADER
from kortravelmap.api.cache_target_stream_schema import (
    CacheTargetEventRecord,
    CacheTargetRestoreFenceRecord,
    CacheTargetStreamStatusRecord,
)
from kortravelmap.api.cache_target_stream_service import get_cache_target_stream_service
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    DomainCommandFingerprintConflict,
    DomainCommandReplay,
)
from kortravelmap.api.settings import ApiSettings

TOKEN = "cache-target-token-000000000000000000000000"
CONSUMER_ID = "pinvi-consumer"
EXTERNAL_SYSTEM = "pinvi"
SOURCE_EVENT_ID = "11111111-1111-4111-8111-111111111111"
IDEMPOTENCY_KEY = "22222222-2222-4222-8222-222222222222"
TARGET_ID = "33333333-3333-4333-8333-333333333333"
EVENT_ID = "44444444-4444-4444-8444-444444444444"
CLAIM_ID = "55555555-5555-4555-8555-555555555555"
LEASE_TOKEN = "66666666-6666-4666-8666-666666666666"
RECONCILIATION_REQUEST_ID = "88888888-8888-4888-8888-888888888888"
RECONCILIATION_SNAPSHOT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


class _FakeSession:
    def begin(self) -> Any:
        class _Tx:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *_exc: object) -> None:
                return None

        return _Tx()


class _FakeCacheTargetService:
    def __init__(self) -> None:
        self.apply_calls: list[dict[str, Any]] = []
        self.claim_calls: list[dict[str, Any]] = []
        self.reconciliation_calls: list[dict[str, Any]] = []
        self.reconciliation_begin_calls: list[dict[str, Any]] = []
        self.reconciliation_seal_calls: list[dict[str, Any]] = []
        self.reconciliation_metadata_calls: list[dict[str, Any]] = []
        self.reconciliation_completion_calls: list[dict[str, Any]] = []
        self.reconciliation_snapshot_calls: list[dict[str, Any]] = []
        self.reconciliation_completion_error: Exception | None = None
        self.operation_result: Any = SimpleNamespace(
            operation_id=RECONCILIATION_REQUEST_ID,
            status="superseded",
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            status_url=(
                f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}"
            ),
        )
        self.restore_calls: list[dict[str, Any]] = []
        self.replay_calls: list[dict[str, Any]] = []
        self.apply_result: Any = SimpleNamespace(
            external_system=EXTERNAL_SYSTEM,
            target_key="target-1",
            state="active",
            restore_epoch=1,
            source_generation=1,
            source_payload_fingerprint="a" * 64,
            target_sequence=1,
            target=SimpleNamespace(
                target_id=TARGET_ID,
                entity_tag=f'"{TARGET_ID}:7"',
            ),
            occurred_at=NOW,
            updated_at=NOW,
        )
        self.stream = SimpleNamespace(
            external_system=EXTERNAL_SYSTEM,
            restore_epoch=4,
            control_version=2,
            entity_tag=f'"{EXTERNAL_SYSTEM}:2"',
            status="ready",
            consumer_id=CONSUMER_ID,
            blocked_event_id=None,
            active_reconciliation=None,
            updated_at=NOW,
        )
        self.restore_result: Any = SimpleNamespace(
            fence_id="77777777-7777-4777-8777-777777777777",
            external_system=EXTERNAL_SYSTEM,
            consumer_id=CONSUMER_ID,
            previous_restore_epoch=4,
            restore_epoch=5,
            previous_control_version=2,
            control_version=3,
            invalidated_claim_count=2,
            superseded_delivery_count=4,
            superseded_reconciliation_count=1,
            superseded_reconciliation_request_id=RECONCILIATION_REQUEST_ID,
        )
        self.dead_letter: Any | None = None
        self.claim_result: Any | None = None
        self.reconciliation_result: Any = SimpleNamespace(
            operation_id=RECONCILIATION_REQUEST_ID,
            status="running",
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            status_url=f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}",
            retry_after_seconds=5,
        )
        self.reconciliation_begin_result: Any = SimpleNamespace(
            operation_id=RECONCILIATION_REQUEST_ID,
            status="preparing",
            status_url=f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}",
            retry_after_seconds=5,
            entity_tag=f'"{RECONCILIATION_REQUEST_ID}:1"',
            stream_entity_tag=f'"{EXTERNAL_SYSTEM}:3"',
        )
        self.reconciliation_seal_result: Any = SimpleNamespace(
            operation_id=RECONCILIATION_REQUEST_ID,
            status="running",
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            status_url=f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}",
            retry_after_seconds=5,
            entity_tag=f'"{RECONCILIATION_REQUEST_ID}:2"',
            stream_entity_tag=f'"{EXTERNAL_SYSTEM}:3"',
        )
        self.reconciliation_metadata_result: Any = SimpleNamespace(
            request_id=RECONCILIATION_REQUEST_ID,
            external_system=EXTERNAL_SYSTEM,
            consumer_id=CONSUMER_ID,
            status="running",
            phase_version=2,
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            restore_epoch=4,
            stream_control_version=2,
            item_count=1,
            merkle_root="a" * 64,
            entity_tag=f'"{RECONCILIATION_REQUEST_ID}:2"',
            stream_entity_tag=f'"{EXTERNAL_SYSTEM}:2"',
        )
        self.reconciliation_completion_result: Any = SimpleNamespace(
            operation_id="99999999-9999-4999-8999-999999999999",
            status="succeeded",
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            status_url=(
                "/v1/ops/cache-target-operations/"
                "99999999-9999-4999-8999-999999999999"
            ),
            retry_after_seconds=None,
        )
        self.reconciliation_snapshot_result: Any = SimpleNamespace(
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            external_system=EXTERNAL_SYSTEM,
            restore_epoch=4,
            high_watermark_cursor="snapshot-high-watermark",
            count=1,
            merkle_root="a" * 64,
            items=[
                SimpleNamespace(
                    external_system=EXTERNAL_SYSTEM,
                    target_key="target-1",
                    state="active",
                    source_generation=1,
                    source_payload_fingerprint="b" * 64,
                )
            ],
            next_cursor=None,
        )
        self.replay_result: Any = SimpleNamespace(
            event_id=EVENT_ID,
            status="retry",
            delivery_version=3,
            entity_tag=f'"{EVENT_ID}:3"',
        )

    async def apply_cache_target_source(self, _session: Any, **kwargs: Any) -> Any:
        self.apply_calls.append(kwargs)
        return self.apply_result

    async def get_cache_target_stream(
        self,
        _session: Any,
        *,
        external_system: str,
        consumer_id: str,
    ) -> Any:
        assert external_system == EXTERNAL_SYSTEM
        if consumer_id != CONSUMER_ID:
            raise CacheTargetStreamConflict("consumer_mismatch", "consumer mismatch")
        return self.stream

    async def advance_cache_target_restore_fence(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.restore_calls.append(kwargs)
        return self.restore_result

    async def claim_cache_target_events(self, _session: Any, **kwargs: Any) -> Any:
        self.claim_calls.append(kwargs)
        return self.claim_result

    async def request_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.reconciliation_calls.append(kwargs)
        return self.reconciliation_result

    async def begin_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.reconciliation_begin_calls.append(kwargs)
        return self.reconciliation_begin_result

    async def seal_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.reconciliation_seal_calls.append(kwargs)
        return self.reconciliation_seal_result

    async def complete_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.reconciliation_completion_calls.append(kwargs)
        if self.reconciliation_completion_error is not None:
            raise self.reconciliation_completion_error
        return self.reconciliation_completion_result

    async def get_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.reconciliation_metadata_calls.append(kwargs)
        if isinstance(self.reconciliation_metadata_result, Exception):
            raise self.reconciliation_metadata_result
        return self.reconciliation_metadata_result

    async def get_cache_target_reconciliation_snapshot(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.reconciliation_snapshot_calls.append(kwargs)
        if kwargs["consumer_id"] != CONSUMER_ID:
            raise CacheTargetStreamConflict("consumer_mismatch", "consumer mismatch")
        return self.reconciliation_snapshot_result

    async def get_cache_target_dead_letter(
        self,
        _session: Any,
        *,
        event_id: str,
    ) -> Any | None:
        assert event_id == EVENT_ID
        return self.dead_letter

    async def get_cache_target_operation(
        self,
        _session: Any,
        *,
        operation_id: str,
    ) -> Any:
        assert operation_id == RECONCILIATION_REQUEST_ID
        return self.operation_result

    async def replay_cache_target_dead_letter(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.replay_calls.append(kwargs)
        return self.replay_result


def _token_sha256(token: str = TOKEN) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _settings(
    *,
    token: str = TOKEN,
    scopes: list[str] | None = None,
    external_systems: list[str] | None = None,
    admin_destructive_enabled: bool = False,
    consumer_id: str = CONSUMER_ID,
    principal_id: str = "svc:pinvi",
) -> ApiSettings:
    return ApiSettings(
        _env_file=None,
        admin_proxy_secret=None,
        ops_cancel_token=None,
        ops_read_token=None,
        public_api_key_required=False,
        service_token=None,
        vworld_api_key=None,
        admin_destructive_enabled=admin_destructive_enabled,
        cache_target_service_principals=[
            {
                "principal_id": principal_id,
                "consumer_id": consumer_id,
                "token_sha256": _token_sha256(token),
                "scopes": scopes or ["cache-target:consumer"],
                "external_systems": external_systems or [EXTERNAL_SYSTEM],
            }
        ],
    )


def _client(
    service: _FakeCacheTargetService,
    *,
    settings: ApiSettings | None = None,
) -> TestClient:
    app = create_app(settings or _settings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_cache_target_stream_service] = lambda: service
    return TestClient(app, client=("127.0.0.1", 50000))


def _service_headers(
    *,
    token: str = TOKEN,
    idempotency_key: str = IDEMPOTENCY_KEY,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        SERVICE_TOKEN_HEADER: token,
        "Idempotency-Key": idempotency_key,
    }
    if extra:
        headers.update(extra)
    return headers


def _upsert_body() -> dict[str, Any]:
    return {
        "source_event_id": SOURCE_EVENT_ID,
        "restore_epoch": 1,
        "source_generation": 1,
        "coord": {"lon": "127.100001", "lat": "37.500001"},
        "radius_km": "1.25",
        "update_enabled": True,
        "occurred_at": NOW.isoformat(),
    }


def _restore_fence_record_payload(
    *,
    superseded_reconciliation_count: int,
    superseded_reconciliation_request_id: str | None,
) -> dict[str, Any]:
    return {
        "external_system": EXTERNAL_SYSTEM,
        "restore_epoch": 5,
        "control_version": 3,
        "entity_tag": f'"{EXTERNAL_SYSTEM}:3"',
        "state": "fenced",
        "fence_id": "77777777-7777-4777-8777-777777777777",
        "previous_restore_epoch": 4,
        "previous_control_version": 2,
        "invalidated_claim_count": 2,
        "superseded_delivery_count": 4,
        "superseded_reconciliation_count": superseded_reconciliation_count,
        "superseded_reconciliation_request_id": (
            superseded_reconciliation_request_id
        ),
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("count", "request_id"),
    [
        (0, RECONCILIATION_REQUEST_ID),
        (1, None),
    ],
)
def test_restore_fence_receipt_rejects_uncorrelated_reconciliation_fields(
    count: int,
    request_id: str | None,
) -> None:
    with pytest.raises(ValidationError, match="request_id가 일치해야"):
        CacheTargetRestoreFenceRecord.model_validate(
            _restore_fence_record_payload(
                superseded_reconciliation_count=count,
                superseded_reconciliation_request_id=request_id,
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("count", "request_id"),
    [
        (0, None),
        (1, RECONCILIATION_REQUEST_ID),
    ],
)
def test_restore_fence_receipt_accepts_correlated_reconciliation_fields(
    count: int,
    request_id: str | None,
) -> None:
    record = CacheTargetRestoreFenceRecord.model_validate(
        _restore_fence_record_payload(
            superseded_reconciliation_count=count,
            superseded_reconciliation_request_id=request_id,
        )
    )

    assert record.superseded_reconciliation_count == count
    assert (
        str(record.superseded_reconciliation_request_id)
        if record.superseded_reconciliation_request_id is not None
        else None
    ) == request_id


@pytest.mark.unit
def test_restore_fence_openapi_documents_receipt_correlation_invariant() -> None:
    client = _client(_FakeCacheTargetService())

    schema = client.app.openapi()["components"]["schemas"][
        "CacheTargetRestoreFenceRecord"
    ]

    assert schema["description"] == (
        "Restore-fence control state와 durable effect receipt.\n\n"
        "불변조건: `superseded_reconciliation_count == 0` iff\n"
        "`superseded_reconciliation_request_id == null`이고, count가 `1` iff "
        "request ID가\nnon-null이다."
    )


@pytest.mark.unit
def test_ops_stream_status_requires_superseded_count() -> None:
    payload = {
        "external_system": EXTERNAL_SYSTEM,
        "restore_epoch": 4,
        "control_version": 3,
        "consumer_enabled": True,
        "state": "ready",
        "pending_count": 0,
        "leased_count": 0,
        "retry_count": 0,
        "dead_count": 0,
        "delivered_count": 7,
        "superseded_count": 5,
        "updated_at": NOW,
    }

    record = CacheTargetStreamStatusRecord.model_validate(payload)
    assert record.superseded_count == 5
    payload.pop("superseded_count")
    with pytest.raises(ValidationError):
        CacheTargetStreamStatusRecord.model_validate(payload)


@pytest.mark.unit
def test_ops_recovery_operation_exposes_superseded_status_enum() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = client.get(
        f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}"
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "superseded"
    operation_schema = client.app.openapi()["components"]["schemas"][
        "CacheTargetRecoveryOperationRecord"
    ]
    assert "superseded" in operation_schema["properties"]["status"]["enum"]


@pytest.mark.unit
def test_put_cache_target_uses_bound_principal_and_create_precondition() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = client.put(
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
        headers=_service_headers(extra={"If-None-Match": "*"}),
        json=_upsert_body(),
    )

    assert response.status_code == 200, response.text
    assert response.headers["etag"] == f'"{TARGET_ID}:7"'
    assert response.json()["data"]["target_id"] == TARGET_ID
    assert service.apply_calls[0]["consumer_id"] == CONSUMER_ID
    assert service.apply_calls[0]["create_only"] is True
    assert service.apply_calls[0]["expected_target_id"] is None


@pytest.mark.unit
def test_put_cache_target_rejects_missing_precondition_before_service_call() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = client.put(
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
        headers=_service_headers(),
        json=_upsert_body(),
    )

    assert response.status_code == 428
    assert response.json()["code"] == "PRECONDITION_REQUIRED"
    assert service.apply_calls == []


@pytest.mark.unit
def test_put_cache_target_maps_result_precondition_failure_to_412() -> None:
    service = _FakeCacheTargetService()
    service.apply_result = SimpleNamespace(status="precondition_failed")
    client = _client(service)

    response = client.put(
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
        headers=_service_headers(extra={"If-Match": f'"{TARGET_ID}:7"'}),
        json=_upsert_body(),
    )

    assert response.status_code == 412
    assert response.json()["code"] == "PRECONDITION_FAILED"


@pytest.mark.unit
def test_put_cache_target_rejects_float_decimal_inputs() -> None:
    service = _FakeCacheTargetService()
    body = _upsert_body()
    body["radius_km"] = 1.25
    client = _client(service)

    response = client.put(
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
        headers=_service_headers(extra={"If-None-Match": "*"}),
        json=body,
    )

    assert response.status_code == 422
    assert service.apply_calls == []


@pytest.mark.unit
def test_cache_target_claim_serializes_stream_scoped_reconciled_event() -> None:
    service = _FakeCacheTargetService()
    service.claim_result = SimpleNamespace(
        claim_id=CLAIM_ID,
        external_system=EXTERNAL_SYSTEM,
        consumer_id=CONSUMER_ID,
        lease_token=LEASE_TOKEN,
        status="active",
        first_relay_order=10,
        last_relay_order=11,
        acked_through_relay_order=10,
        acked_through="opaque-cursor-10",
        lease_expires_at=NOW + timedelta(seconds=60),
        events=[
            SimpleNamespace(
                event_id=EVENT_ID,
                event_scope="target",
                event_type="cache_target.state_applied",
                external_system=EXTERNAL_SYSTEM,
                target_key="target-1",
                target_id=TARGET_ID,
                restore_epoch=1,
                source_generation=1,
                target_sequence=1,
                relay_order=10,
                cursor="cursor-10",
                source_payload_fingerprint="a" * 64,
                payload_fingerprint="b" * 64,
                payload={
                    "version": "cache-target-event-v1",
                    "state": "active",
                    "source_event_id": SOURCE_EVENT_ID,
                    "target": {
                        "target_id": TARGET_ID,
                        "entity_tag": f'"{TARGET_ID}:7"',
                        "coord": {"lon_e6": 126_978_400, "lat_e6": 37_566_500},
                        "radius_m": 1_000,
                        "update_enabled": True,
                    },
                },
                occurred_at=NOW,
            ),
            SimpleNamespace(
                event_id="77777777-7777-4777-8777-777777777777",
                event_scope="stream",
                event_type="cache_target.reconciled",
                external_system=EXTERNAL_SYSTEM,
                target_key="stale-fake-target",
                target_id=TARGET_ID,
                restore_epoch=1,
                source_generation=99,
                target_sequence=9,
                relay_order=11,
                cursor="cursor-11",
                source_payload_fingerprint="c" * 64,
                payload_fingerprint="d" * 64,
                payload={
                    "request_id": RECONCILIATION_REQUEST_ID,
                    "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
                    "actual_merkle_root": "c" * 64,
                    "expected_merkle_root": "c" * 64,
                    "status": "succeeded",
                    "version": "cache-target-reconciliation-v1",
                },
                occurred_at=NOW + timedelta(seconds=1),
            ),
        ],
    )
    client = _client(service, settings=_settings(scopes=["cache-target:claim"]))

    response = client.post(
        "/v1/service/cache-target-event-claims",
        headers=_service_headers(),
        json={
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "limit": 2,
            "lease_seconds": 60,
        },
    )

    assert response.status_code == 200, response.text
    assert service.claim_calls[0]["external_system"] == EXTERNAL_SYSTEM
    assert service.claim_calls[0]["consumer_id"] == CONSUMER_ID
    assert response.json()["data"]["acked_through"] == "opaque-cursor-10"
    events = response.json()["data"]["events"]
    assert events[0]["event_scope"] == "target"
    assert events[0]["target_key"] == "target-1"
    assert events[0]["target_id"] == TARGET_ID
    assert events[0]["source_generation"] == 1
    assert events[0]["target_sequence"] == 1
    assert events[1]["event_scope"] == "stream"
    assert events[1]["event_type"] == "cache_target.reconciled"
    assert events[1]["target_key"] is None
    assert events[1]["target_id"] is None
    assert events[1]["source_generation"] is None
    assert events[1]["target_sequence"] is None
    assert events[1]["source_payload_fingerprint"] == "c" * 64
    assert events[1]["payload"] == {
        "request_id": RECONCILIATION_REQUEST_ID,
        "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
        "actual_merkle_root": "c" * 64,
        "expected_merkle_root": "c" * 64,
        "status": "succeeded",
        "version": "cache-target-reconciliation-v1",
    }


@pytest.mark.unit
def test_cache_target_event_record_rejects_inconsistent_stream_scope() -> None:
    with pytest.raises(ValidationError, match="stream-scoped cache target events"):
        CacheTargetEventRecord(
            event_id=EVENT_ID,
            event_scope="stream",
            event_type="cache_target.state_applied",
            external_system=EXTERNAL_SYSTEM,
            target_key=None,
            target_id=None,
            restore_epoch=1,
            source_generation=None,
            target_sequence=None,
            relay_order=1,
            cursor="cursor-1",
            source_payload_fingerprint="a" * 64,
            payload_fingerprint="b" * 64,
            payload={
                "version": "cache-target-event-v1",
                "state": "deleted",
                "source_event_id": SOURCE_EVENT_ID,
                "target": None,
            },
            occurred_at=NOW,
        )


@pytest.mark.unit
def test_refresh_request_rejects_more_than_500_targets_before_service_call() -> None:
    service = _FakeCacheTargetService()
    client = _client(service, settings=_settings(scopes=["cache-target:consumer"]))

    response = client.post(
        "/v1/service/refresh-requests",
        headers=_service_headers(),
        json={
            "external_system": EXTERNAL_SYSTEM,
            "target_keys": [f"target-{index}" for index in range(501)],
            "reason": "operator refresh",
        },
    )

    assert response.status_code == 422


@pytest.mark.unit
@pytest.mark.parametrize(
    ("endpoint", "body_patch"),
    [
        ("claim", {"lease_seconds": 301}),
        ("ack", {"through_cursor": "not-a-cache-target-event-cursor"}),
        ("ack", {"lease_token": "not-a-uuid"}),
        ("ack", {"applied": [{"event_id": EVENT_ID, "payload_fingerprint": "A" * 64}]}),
        ("nack", {"lease_token": "not-a-uuid"}),
        ("nack", {"error_code": "x" * 129}),
        ("nack", {"error_fingerprint": "A" * 64}),
        ("nack", {"error_fingerprint": "a" * 63}),
    ],
)
def test_cache_target_delivery_bounds_return_stable_422(
    endpoint: str,
    body_patch: dict[str, Any],
) -> None:
    service = _FakeCacheTargetService()
    client = _client(service)
    if endpoint == "claim":
        response = client.post(
            "/v1/service/cache-target-event-claims",
            headers=_service_headers(),
            json={
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "limit": 1,
                **body_patch,
            },
        )
    elif endpoint == "ack":
        response = client.post(
            "/v1/service/cache-target-event-acks",
            headers={SERVICE_TOKEN_HEADER: TOKEN},
            json={
                "consumer_id": CONSUMER_ID,
                "claim_id": CLAIM_ID,
                "lease_token": LEASE_TOKEN,
                "through_cursor": cache_target_event_cursor(1),
                "applied": [],
                **body_patch,
            },
        )
    else:
        response = client.post(
            "/v1/service/cache-target-event-nacks",
            headers={SERVICE_TOKEN_HEADER: TOKEN},
            json={
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "claim_id": CLAIM_ID,
                "lease_token": LEASE_TOKEN,
                "event_id": EVENT_ID,
                "disposition": "permanent",
                "error_class": "unsupported",
                **body_patch,
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.claim_calls == []
    assert service.reconciliation_snapshot_calls == []


@pytest.mark.unit
def test_cache_target_service_token_must_be_registered() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    missing = client.get(f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}")
    unknown = client.get(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}",
        headers={SERVICE_TOKEN_HEADER: "shared-service-token"},
    )

    assert (missing.status_code, missing.json()["code"]) == (
        401,
        "CACHE_TARGET_SERVICE_TOKEN_REQUIRED",
    )
    assert (unknown.status_code, unknown.json()["code"]) == (
        401,
        "CACHE_TARGET_SERVICE_TOKEN_INVALID",
    )


@pytest.mark.unit
def test_cache_target_principal_registry_rejects_duplicate_token_digest() -> None:
    base = {
        "consumer_id": CONSUMER_ID,
        "token_sha256": _token_sha256(),
        "scopes": ["cache-target:read"],
        "external_systems": [EXTERNAL_SYSTEM],
    }

    with pytest.raises(ValueError, match="token digests must be unique"):
        ApiSettings(
            _env_file=None,
            admin_proxy_secret=None,
            ops_cancel_token=None,
            ops_read_token=None,
            public_api_key_required=False,
            service_token=None,
            vworld_api_key=None,
            cache_target_service_principals=[
                {"principal_id": "svc:pinvi-a", **base},
                {"principal_id": "svc:pinvi-b", **base},
            ],
        )


@pytest.mark.unit
def test_cache_target_consumer_header_is_only_exact_binding_check() -> None:
    service = _FakeCacheTargetService()
    client = _client(service, settings=_settings(scopes=["cache-target:read"]))

    response = client.get(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}",
        headers={
            SERVICE_TOKEN_HEADER: TOKEN,
            CACHE_TARGET_CONSUMER_HEADER: "other-consumer",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CACHE_TARGET_CONSUMER_FORBIDDEN"


@pytest.mark.unit
def test_cache_target_service_scope_and_system_are_fail_closed() -> None:
    service = _FakeCacheTargetService()
    settings = _settings(scopes=["cache-target:read"], external_systems=["other"])
    client = _client(service, settings=settings)

    response = client.get(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}",
        headers={SERVICE_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CACHE_TARGET_EXTERNAL_SYSTEM_FORBIDDEN"


@pytest.mark.unit
def test_restore_fence_uses_stream_etag_and_domain_command_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    captured_complete: dict[str, Any] = {}

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["actor"] == "svc:pinvi"
        assert kwargs["operation"] == "service.cache-target-restore-fence.create"
        assert kwargs["idempotency_key"].hex == IDEMPOTENCY_KEY.replace("-", "")
        return SimpleNamespace(command_id=123, request_fingerprint="b" * 64)

    async def _complete_domain_command(_session: Any, **kwargs: Any) -> None:
        captured_complete.update(kwargs)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    monkeypatch.setattr(
        router_module,
        "complete_domain_command",
        _complete_domain_command,
    )
    client = _client(
        service,
        settings=_settings(scopes=["cache-target:restore-fence"]),
    )

    response = client.post(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}/restore-fences",
        headers=_service_headers(extra={"If-Match": f'"{EXTERNAL_SYSTEM}:2"'}),
        json={
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "reason": "operator-requested restore barrier",
        },
    )

    assert response.status_code == 201, response.text
    assert response.headers["etag"] == f'"{EXTERNAL_SYSTEM}:3"'
    data = response.json()["data"]
    assert data["state"] == "fenced"
    assert data["invalidated_claim_count"] == 2
    assert data["superseded_delivery_count"] == 4
    assert data["superseded_reconciliation_count"] == 1
    assert data["superseded_reconciliation_request_id"] == RECONCILIATION_REQUEST_ID
    assert service.restore_calls[0]["command_id"] == 123
    assert service.restore_calls[0]["expected_control_version"] == 2
    assert captured_complete["status_code"] == 201
    assert captured_complete["response_headers"] == {"ETag": f'"{EXTERNAL_SYSTEM}:3"'}


@pytest.mark.unit
def test_restore_fence_rejects_other_stream_etag_before_domain_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    begin_calls: list[dict[str, Any]] = []

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        begin_calls.append(kwargs)
        return SimpleNamespace(command_id=123, request_fingerprint="b" * 64)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    client = _client(
        service,
        settings=_settings(scopes=["cache-target:restore-fence"]),
    )

    response = client.post(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}/restore-fences",
        headers=_service_headers(extra={"If-Match": '"other:2"'}),
        json={
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "reason": "operator-requested restore barrier",
        },
    )

    assert response.status_code == 412
    assert response.json()["code"] == "PRECONDITION_FAILED"
    assert begin_calls == []
    assert service.restore_calls == []


@pytest.mark.unit
def test_admin_reconciliation_passes_domain_command_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    captured_complete: dict[str, Any] = {}

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["actor"] == "local-dev"
        assert kwargs["operation"] == "admin.cache-target-reconciliation.request"
        assert kwargs["idempotency_key"].hex == IDEMPOTENCY_KEY.replace("-", "")
        assert kwargs["payload"] == {
            "external_system": EXTERNAL_SYSTEM,
            "reason": "operator-requested checksum reconciliation",
        }
        return SimpleNamespace(command_id=456, request_fingerprint="e" * 64)

    async def _complete_domain_command(_session: Any, **kwargs: Any) -> None:
        captured_complete.update(kwargs)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    monkeypatch.setattr(
        router_module,
        "complete_domain_command",
        _complete_domain_command,
    )
    client = _client(service, settings=_settings(admin_destructive_enabled=True))

    response = client.post(
        "/v1/admin/cache-target-reconciliations",
        headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        json={
            "external_system": EXTERNAL_SYSTEM,
            "reason": "operator-requested checksum reconciliation",
        },
    )

    assert response.status_code == 202, response.text
    assert response.headers["location"] == service.reconciliation_result.status_url
    assert response.headers["retry-after"] == "5"
    assert response.json()["data"]["snapshot_id"] == RECONCILIATION_SNAPSHOT_ID
    assert service.reconciliation_calls[0]["command_id"] == 456
    assert service.reconciliation_calls[0]["external_system"] == EXTERNAL_SYSTEM
    assert captured_complete["status_code"] == 202
    assert captured_complete["response_headers"] == {
        "Location": service.reconciliation_result.status_url,
        "Retry-After": "5",
    }


@pytest.mark.unit
def test_admin_reconciliation_requires_destructive_gate() -> None:
    service = _FakeCacheTargetService()
    client = _client(service, settings=_settings(admin_destructive_enabled=False))

    response = client.post(
        "/v1/admin/cache-target-reconciliations",
        headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        json={"external_system": EXTERNAL_SYSTEM, "reason": "operator request"},
    )

    assert response.status_code == 403
    assert service.reconciliation_calls == []


@pytest.mark.unit
def test_service_reconciliation_begin_uses_recovery_scope_and_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    captured_complete: dict[str, Any] = {}

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["actor"] == "svc:pinvi"
        assert kwargs["operation"] == "service.cache-target-reconciliation.begin"
        assert kwargs["idempotency_key"].hex == IDEMPOTENCY_KEY.replace("-", "")
        assert kwargs["payload"] == {
            "body": {
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "expected_restore_epoch": 4,
                "reason": "PinVi restore cutover",
            },
            "headers": {"If-Match": None, "If-None-Match": "*"},
        }
        return SimpleNamespace(command_id=701, request_fingerprint="a" * 64)

    async def _complete_domain_command(_session: Any, **kwargs: Any) -> None:
        captured_complete.update(kwargs)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    monkeypatch.setattr(router_module, "complete_domain_command", _complete_domain_command)
    client = _client(service, settings=_settings(scopes=["cache-target:recovery"]))

    response = client.post(
        "/v1/service/cache-target-reconciliations",
        headers=_service_headers(extra={"If-None-Match": "*"}),
        json={
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "reason": "PinVi restore cutover",
        },
    )

    assert response.status_code == 201, response.text
    assert response.headers["etag"] == f'"{RECONCILIATION_REQUEST_ID}:1"'
    assert response.headers["location"] == (
        f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}"
    )
    assert response.json()["data"] == {
        "operation_id": RECONCILIATION_REQUEST_ID,
        "status": "preparing",
        "snapshot_id": None,
        "status_url": f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}",
        "entity_tag": f'"{RECONCILIATION_REQUEST_ID}:1"',
        "stream_entity_tag": f'"{EXTERNAL_SYSTEM}:3"',
    }
    assert service.reconciliation_begin_calls == [
        {
            "command_id": 701,
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "expected_control_version": None,
            "create_only": True,
            "reason": "PinVi restore cutover",
        }
    ]
    assert captured_complete["status_code"] == 201
    assert captured_complete["response_headers"] == {
        "Location": f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}",
        "Retry-After": "5",
        "ETag": f'"{RECONCILIATION_REQUEST_ID}:1"',
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("extra_headers", "expected_status"),
    [
        ({}, 428),
        (
            {
                "If-None-Match": "*",
                "If-Match": f'"{EXTERNAL_SYSTEM}:2"',
            },
            422,
        ),
    ],
)
def test_service_reconciliation_begin_requires_exactly_one_stream_precondition(
    extra_headers: dict[str, str],
    expected_status: int,
) -> None:
    service = _FakeCacheTargetService()
    client = _client(service, settings=_settings(scopes=["cache-target:recovery"]))

    response = client.post(
        "/v1/service/cache-target-reconciliations",
        headers=_service_headers(extra=extra_headers),
        json={
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "reason": "PinVi restore cutover",
        },
    )

    assert response.status_code == expected_status
    assert service.reconciliation_begin_calls == []


@pytest.mark.unit
def test_service_reconciliation_seal_uses_request_etag_and_exact_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    captured_complete: dict[str, Any] = {}

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["actor"] == "svc:pinvi"
        assert kwargs["operation"] == "service.cache-target-reconciliation.seal"
        assert kwargs["idempotency_key"].hex == IDEMPOTENCY_KEY.replace("-", "")
        assert kwargs["payload"] == {
            "request_id": RECONCILIATION_REQUEST_ID,
            "body": {
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "expected_restore_epoch": 4,
                "expected_item_count": 1,
                "expected_merkle_root": "a" * 64,
            },
            "headers": {"If-Match": f'"{RECONCILIATION_REQUEST_ID}:1"'},
        }
        return SimpleNamespace(command_id=702, request_fingerprint="b" * 64)

    async def _complete_domain_command(_session: Any, **kwargs: Any) -> None:
        captured_complete.update(kwargs)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    monkeypatch.setattr(router_module, "complete_domain_command", _complete_domain_command)
    client = _client(service, settings=_settings(scopes=["cache-target:recovery"]))
    path = f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/seals"
    headers = _service_headers(extra={"If-Match": f'"{RECONCILIATION_REQUEST_ID}:1"'})
    body = {
        "external_system": EXTERNAL_SYSTEM,
        "consumer_id": CONSUMER_ID,
        "expected_restore_epoch": 4,
        "expected_item_count": 1,
        "expected_merkle_root": "a" * 64,
    }

    first = client.post(path, headers=headers, json=body)

    assert first.status_code == 200, first.text
    assert first.headers["etag"] == f'"{RECONCILIATION_REQUEST_ID}:2"'
    assert service.reconciliation_metadata_calls == [
        {"request_id": RECONCILIATION_REQUEST_ID}
    ]
    assert service.reconciliation_seal_calls == [
        {
            "request_id": RECONCILIATION_REQUEST_ID,
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "expected_phase_version": 1,
            "expected_restore_epoch": 4,
            "expected_item_count": 1,
            "expected_merkle_root": "a" * 64,
        }
    ]
    assert captured_complete["response_headers"] == {
        "ETag": f'"{RECONCILIATION_REQUEST_ID}:2"',
    }

    replay_record = SimpleNamespace(
        response_body=captured_complete["response"].model_dump(mode="json"),
        response_status=200,
        response_headers=captured_complete["response_headers"],
    )

    async def _replay_domain_command(_session: Any, **_kwargs: Any) -> Any:
        raise DomainCommandReplay(replay_record)

    monkeypatch.setattr(router_module, "begin_domain_command", _replay_domain_command)
    replay = client.post(path, headers=headers, json=body)

    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["etag"] == first.headers["etag"]
    assert replay.headers["idempotency-replayed"] == "true"
    assert len(service.reconciliation_seal_calls) == 1


@pytest.mark.unit
def test_service_reconciliation_seal_authorizes_stored_request_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    service.reconciliation_metadata_result = SimpleNamespace(
        request_id=RECONCILIATION_REQUEST_ID,
        external_system="other",
        consumer_id=CONSUMER_ID,
    )
    ledger_calls: list[dict[str, Any]] = []

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        ledger_calls.append(kwargs)
        return SimpleNamespace(command_id=793, request_fingerprint="d" * 64)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    client = _client(
        service,
        settings=_settings(
            scopes=["cache-target:recovery"],
            external_systems=[EXTERNAL_SYSTEM],
        ),
    )

    response = client.post(
        f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/seals",
        headers=_service_headers(extra={"If-Match": f'"{RECONCILIATION_REQUEST_ID}:1"'}),
        json={
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "expected_item_count": 1,
            "expected_merkle_root": "a" * 64,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CACHE_TARGET_EXTERNAL_SYSTEM_FORBIDDEN"
    assert service.reconciliation_metadata_calls == [
        {"request_id": RECONCILIATION_REQUEST_ID}
    ]
    assert ledger_calls == []
    assert service.reconciliation_seal_calls == []
    assert service.reconciliation_snapshot_calls == []
    assert service.reconciliation_completion_calls == []


@pytest.mark.unit
def test_service_reconciliation_completion_binds_preconditions_and_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    service.stream.active_reconciliation = SimpleNamespace(
        request_id=RECONCILIATION_REQUEST_ID,
        status="running",
        snapshot_id=RECONCILIATION_SNAPSHOT_ID,
        restore_epoch=4,
        count=1,
        merkle_root="a" * 64,
        high_watermark_cursor="snapshot-high-watermark",
        entity_tag=f'"{RECONCILIATION_REQUEST_ID}:2"',
        stream_entity_tag=f'"{EXTERNAL_SYSTEM}:2"',
        created_at=NOW,
    )
    captured_complete: dict[str, Any] = {}

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["actor"] == "svc:pinvi"
        assert kwargs["operation"] == "service.cache-target-reconciliation.complete"
        assert kwargs["payload"] == {
            "request_id": RECONCILIATION_REQUEST_ID,
            "body": {
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
                "expected_restore_epoch": 4,
                "actual_merkle_root": "a" * 64,
            },
        }
        return SimpleNamespace(command_id=789, request_fingerprint="f" * 64)

    async def _complete_domain_command(_session: Any, **kwargs: Any) -> None:
        captured_complete.update(kwargs)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    monkeypatch.setattr(router_module, "complete_domain_command", _complete_domain_command)
    client = _client(
        service,
        settings=_settings(scopes=["cache-target:read", "cache-target:snapshot"]),
    )
    request_id = RECONCILIATION_REQUEST_ID

    discovery = client.get(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}",
        headers=_service_headers(),
    )
    assert discovery.status_code == 200, discovery.text
    active = discovery.json()["data"]["active_reconciliation"]
    assert active["request_id"] == request_id
    assert active["snapshot_id"] == RECONCILIATION_SNAPSHOT_ID
    assert active["entity_tag"] == f'"{RECONCILIATION_REQUEST_ID}:2"'
    assert active["stream_entity_tag"] == f'"{EXTERNAL_SYSTEM}:2"'
    fixed = client.get(
        f"/v1/service/cache-target-reconciliations/{request_id}/snapshot",
        headers=_service_headers(),
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["data"]["snapshot_id"] == active["snapshot_id"]
    assert fixed.json()["data"]["merkle_root"] == active["merkle_root"]
    assert service.reconciliation_metadata_calls == [{"request_id": request_id}]
    assert service.reconciliation_snapshot_calls == [
        {
            "request_id": request_id,
            "consumer_id": CONSUMER_ID,
            "limit": 500,
            "cursor": None,
        }
    ]

    response = client.post(
        f"/v1/service/cache-target-reconciliations/{request_id}/completions",
        headers=_service_headers(),
        json={
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
            "expected_restore_epoch": 4,
            "actual_merkle_root": "a" * 64,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "succeeded"
    assert service.reconciliation_completion_calls == [
        {
            "request_id": request_id,
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
            "expected_restore_epoch": 4,
            "actual_merkle_root": "a" * 64,
        }
    ]
    assert captured_complete["status_code"] == 200


@pytest.mark.unit
def test_reconciliation_discovery_snapshot_and_completion_reject_other_consumer() -> None:
    service = _FakeCacheTargetService()
    client = _client(
        service,
        settings=_settings(
            scopes=["cache-target:read", "cache-target:snapshot"],
            consumer_id="other-consumer",
            principal_id="svc:other",
        ),
    )
    request_id = "88888888-8888-4888-8888-888888888888"
    headers = _service_headers()

    discovery = client.get(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}",
        headers=headers,
    )
    fixed = client.get(
        f"/v1/service/cache-target-reconciliations/{request_id}/snapshot",
        headers=headers,
    )
    completion = client.post(
        f"/v1/service/cache-target-reconciliations/{request_id}/completions",
        headers=headers,
        json={
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
            "expected_restore_epoch": 4,
            "actual_merkle_root": "a" * 64,
        },
    )

    assert discovery.status_code == 403
    assert fixed.status_code == 403
    assert completion.status_code == 403
    assert service.reconciliation_metadata_calls == [
        {"request_id": request_id},
        {"request_id": request_id},
    ]
    assert service.reconciliation_snapshot_calls == []
    assert service.reconciliation_completion_calls == []


@pytest.mark.unit
def test_service_reconciliation_completion_authorizes_stored_request_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    service.reconciliation_metadata_result = SimpleNamespace(
        request_id=RECONCILIATION_REQUEST_ID,
        external_system="other",
        consumer_id=CONSUMER_ID,
    )
    ledger_calls: list[dict[str, Any]] = []

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        ledger_calls.append(kwargs)
        return SimpleNamespace(command_id=794, request_fingerprint="e" * 64)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    client = _client(
        service,
        settings=_settings(
            scopes=["cache-target:snapshot"],
            external_systems=[EXTERNAL_SYSTEM],
        ),
    )

    response = client.post(
        f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/completions",
        headers=_service_headers(),
        json={
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
            "expected_restore_epoch": 4,
            "actual_merkle_root": "a" * 64,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CACHE_TARGET_EXTERNAL_SYSTEM_FORBIDDEN"
    assert service.reconciliation_metadata_calls == [
        {"request_id": RECONCILIATION_REQUEST_ID}
    ]
    assert ledger_calls == []
    assert service.reconciliation_seal_calls == []
    assert service.reconciliation_snapshot_calls == []
    assert service.reconciliation_completion_calls == []


@pytest.mark.unit
def test_reconciliation_snapshot_checks_external_system_before_item_read() -> None:
    service = _FakeCacheTargetService()
    service.reconciliation_metadata_result = SimpleNamespace(
        request_id=RECONCILIATION_REQUEST_ID,
        external_system="other",
        consumer_id=CONSUMER_ID,
        status="running",
        phase_version=2,
        snapshot_id=RECONCILIATION_SNAPSHOT_ID,
        restore_epoch=4,
        stream_control_version=2,
        item_count=1,
        merkle_root="a" * 64,
        entity_tag=f'"{RECONCILIATION_REQUEST_ID}:2"',
        stream_entity_tag='"other:2"',
    )
    client = _client(
        service,
        settings=_settings(
            scopes=["cache-target:snapshot"],
            external_systems=[EXTERNAL_SYSTEM],
        ),
    )

    response = client.get(
        f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/snapshot",
        headers={SERVICE_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CACHE_TARGET_EXTERNAL_SYSTEM_FORBIDDEN"
    assert service.reconciliation_metadata_calls == [
        {"request_id": RECONCILIATION_REQUEST_ID}
    ]
    assert service.reconciliation_snapshot_calls == []


@pytest.mark.unit
def test_reconciliation_snapshot_missing_request_returns_404() -> None:
    service = _FakeCacheTargetService()
    service.reconciliation_metadata_result = CacheTargetStreamConflict(
        "reconciliation_not_found",
        "reconciliation request가 없습니다.",
    )
    client = _client(service, settings=_settings(scopes=["cache-target:snapshot"]))

    response = client.get(
        f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/snapshot",
        headers={SERVICE_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RECONCILIATION_NOT_FOUND"
    assert service.reconciliation_snapshot_calls == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path_suffix", "headers", "body"),
    [
        (
            "seals",
            _service_headers(extra={"If-Match": f'"{RECONCILIATION_REQUEST_ID}:1"'}),
            {
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "expected_restore_epoch": 4,
                "expected_item_count": 1,
                "expected_merkle_root": "a" * 64,
            },
        ),
        (
            "completions",
            _service_headers(),
            {
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
                "expected_restore_epoch": 4,
                "actual_merkle_root": "a" * 64,
            },
        ),
    ],
)
def test_reconciliation_mutations_missing_request_return_404_before_write(
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    service.reconciliation_metadata_result = CacheTargetStreamConflict(
        "reconciliation_not_found",
        "reconciliation request가 없습니다.",
    )
    ledger_calls: list[dict[str, Any]] = []

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        ledger_calls.append(kwargs)
        return SimpleNamespace(command_id=795, request_fingerprint="f" * 64)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    client = _client(
        service,
        settings=_settings(scopes=["cache-target:recovery", "cache-target:snapshot"]),
    )

    response = client.post(
        f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/{path_suffix}",
        headers=headers,
        json=body,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RECONCILIATION_NOT_FOUND"
    assert service.reconciliation_metadata_calls == [
        {"request_id": RECONCILIATION_REQUEST_ID}
    ]
    assert ledger_calls == []
    assert service.reconciliation_seal_calls == []
    assert service.reconciliation_snapshot_calls == []
    assert service.reconciliation_completion_calls == []


@pytest.mark.unit
def test_service_reconciliation_completion_distinguishes_412_and_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    service.reconciliation_completion_error = CacheTargetStreamConflict(
        "reconciliation_precondition_failed",
        "snapshot precondition mismatch",
        current={"snapshot_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"},
    )

    async def _begin_domain_command(_session: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(command_id=792, request_fingerprint="c" * 64)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    client = _client(service, settings=_settings(scopes=["cache-target:snapshot"]))
    path = (
        "/v1/service/cache-target-reconciliations/"
        "88888888-8888-4888-8888-888888888888/completions"
    )
    body = {
        "external_system": EXTERNAL_SYSTEM,
        "consumer_id": CONSUMER_ID,
        "snapshot_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "expected_restore_epoch": 4,
        "actual_merkle_root": "a" * 64,
    }
    stale_requests = (
        (
            "/v1/service/cache-target-reconciliations/"
            "99999999-9999-4999-8999-999999999999/completions",
            body,
        ),
        (path, {**body, "snapshot_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}),
        (path, {**body, "expected_restore_epoch": 5}),
    )
    for stale_path, stale_body in stale_requests:
        stale = client.post(
            stale_path,
            headers=_service_headers(),
            json=stale_body,
        )
        assert stale.status_code == 412
        assert stale.json()["code"] == "RECONCILIATION_PRECONDITION_FAILED"

    async def _idempotency_conflict(_session: Any, **_kwargs: Any) -> Any:
        raise DomainCommandFingerprintConflict(
            SimpleNamespace(
                operation="service.cache-target-reconciliation.complete",
                idempotency_key=IDEMPOTENCY_KEY,
            )
        )

    monkeypatch.setattr(router_module, "begin_domain_command", _idempotency_conflict)
    conflict = client.post(
        path,
        headers=_service_headers(),
        json={**body, "actual_merkle_root": "b" * 64},
    )

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.unit
def test_service_dead_letter_replay_exact_response_uses_domain_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    service.dead_letter = SimpleNamespace(
        event=SimpleNamespace(external_system=EXTERNAL_SYSTEM),
        delivery_version=2,
    )
    captured: dict[str, Any] = {}

    async def _begin_domain_command(_session: Any, **kwargs: Any) -> Any:
        assert kwargs["actor"] == "svc:pinvi"
        assert kwargs["operation"] == "service.cache-target-dead-letter.replay"
        assert kwargs["payload"] == {
            "event_id": EVENT_ID,
            "body": {"reason": "manual replay"},
            "headers": {"If-Match": f'"{EVENT_ID}:2"'},
        }
        return SimpleNamespace(command_id=790, request_fingerprint="e" * 64)

    async def _complete_domain_command(_session: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    monkeypatch.setattr(router_module, "complete_domain_command", _complete_domain_command)
    client = _client(
        service,
        settings=_settings(scopes=["cache-target:recovery-replay"]),
    )
    path = f"/v1/service/cache-target-event-dead-letters/{EVENT_ID}/replays"
    headers = _service_headers(extra={"If-Match": f'"{EVENT_ID}:2"'})
    first = client.post(path, headers=headers, json={"reason": "manual replay"})
    assert first.status_code == 200, first.text
    assert captured["response_headers"] == {"ETag": f'"{EVENT_ID}:3"'}
    assert len(service.replay_calls) == 1

    replay_record = SimpleNamespace(
        response_body=captured["response"].model_dump(mode="json"),
        response_status=200,
        response_headers=captured["response_headers"],
    )

    async def _replay_domain_command(_session: Any, **_kwargs: Any) -> Any:
        raise DomainCommandReplay(replay_record)

    monkeypatch.setattr(router_module, "begin_domain_command", _replay_domain_command)
    replay = client.post(path, headers=headers, json={"reason": "manual replay"})

    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["etag"] == first.headers["etag"]
    assert replay.headers["idempotency-replayed"] == "true"
    assert len(service.replay_calls) == 1


@pytest.mark.unit
def test_service_dead_letter_replay_checks_event_system_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    service.dead_letter = SimpleNamespace(
        event=SimpleNamespace(
            event_id=EVENT_ID,
            event_type="cache_target.state_applied",
            external_system="other",
            relay_order=1,
            target_key="target-1",
            target_id=TARGET_ID,
            restore_epoch=1,
            source_generation=1,
            target_sequence=1,
            cursor="cursor-1",
            source_payload_fingerprint="a" * 64,
            payload_fingerprint="b" * 64,
            payload={},
            occurred_at=NOW,
        ),
        delivery_version=2,
        attempt_count=1,
        error_class="permanent",
        error_code="failed",
        error_fingerprint="c" * 64,
        entity_tag=f'"{EVENT_ID}:2"',
        updated_at=NOW + timedelta(seconds=1),
    )

    async def _begin_domain_command(_session: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(command_id=791, request_fingerprint="d" * 64)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    client = _client(
        service,
        settings=_settings(scopes=["cache-target:recovery-replay"]),
    )

    response = client.post(
        f"/v1/service/cache-target-event-dead-letters/{EVENT_ID}/replays",
        headers=_service_headers(extra={"If-Match": f'"{EVENT_ID}:2"'}),
        json={"reason": "manual replay"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CACHE_TARGET_EXTERNAL_SYSTEM_FORBIDDEN"
    assert service.replay_calls == []
