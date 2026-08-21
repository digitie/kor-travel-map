"""ADR-081 cache-target service/admin API entry point contract tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from kortravelmap.infra import (
    cache_target_event_cursor,
    snapshot_build_budget_seconds,
)
from kortravelmap.infra import cache_target_reconciliation_repo
from kortravelmap.infra import cache_target_stream_repo
from kortravelmap.infra.cache_target_stream_repo import CacheTargetStreamConflict
from pydantic import ValidationError

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import CACHE_TARGET_CONSUMER_HEADER, SERVICE_TOKEN_HEADER
from kortravelmap.api.cache_target_stream_schema import (
    CacheTargetEventRecord,
    CacheTargetRecoveryOperationRecord,
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

COMMAND_TOKEN = "cache-target-command-token-00000000000000000000"
CONSUMER_TOKEN = "cache-target-consumer-token-0000000000000000000"
RESTORE_TOKEN = "cache-target-restore-token-00000000000000000000"
RECOVERY_TOKEN = "cache-target-recovery-token-0000000000000000000"
OTHER_CONSUMER_TOKEN = "cache-target-other-consumer-token-000000000000000"
TOKEN = CONSUMER_TOKEN
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

_ROLE_SCOPES = {
    "command": {"cache-target:command"},
    "consumer": {
        "cache-target:read",
        "cache-target:claim",
        "cache-target:ack",
        "cache-target:nack",
        "cache-target:snapshot",
    },
    "restore": {"cache-target:restore-fence"},
    "recovery": {"cache-target:recovery", "cache-target:recovery-replay"},
}
_SERVICE_OPERATION_CONTRACT = {
    ("put", "/v1/service/cache-targets/{external_system}/{target_key}"): (
        "cache-target:command",
        "command",
    ),
    ("get", "/v1/service/cache-targets/{external_system}/{target_key}"): (
        "cache-target:read",
        "consumer",
    ),
    ("delete", "/v1/service/cache-targets/{external_system}/{target_key}"): (
        "cache-target:command",
        "command",
    ),
    ("get", "/v1/service/cache-target-streams/{external_system}"): (
        "cache-target:read",
        "consumer",
    ),
    ("post", "/v1/service/cache-target-streams/{external_system}/restore-fences"): (
        "cache-target:restore-fence",
        "restore",
    ),
    ("post", "/v1/service/refresh-requests"): (
        "cache-target:command",
        "command",
    ),
    ("get", "/v1/service/refresh-requests/{request_id}"): (
        "cache-target:read",
        "consumer",
    ),
    ("post", "/v1/service/cache-target-event-claims"): (
        "cache-target:claim",
        "consumer",
    ),
    ("post", "/v1/service/cache-target-event-acks"): (
        "cache-target:ack",
        "consumer",
    ),
    ("post", "/v1/service/cache-target-event-nacks"): (
        "cache-target:nack",
        "consumer",
    ),
    ("get", "/v1/service/cache-target-event-dead-letters/{event_id}"): (
        "cache-target:recovery-replay",
        "recovery",
    ),
    ("post", "/v1/service/cache-target-event-dead-letters/{event_id}/replays"): (
        "cache-target:recovery-replay",
        "recovery",
    ),
    ("post", "/v1/service/cache-target-reconciliations"): (
        "cache-target:recovery",
        "recovery",
    ),
    ("post", "/v1/service/cache-target-reconciliations/{request_id}/seals"): (
        "cache-target:recovery",
        "recovery",
    ),
    ("post", "/v1/service/cache-target-reconciliations/{request_id}/completions"): (
        "cache-target:snapshot",
        "consumer",
    ),
    ("get", "/v1/service/cache-target-snapshots/{external_system}"): (
        "cache-target:snapshot",
        "consumer",
    ),
    ("get", "/v1/service/cache-target-reconciliations/{request_id}/snapshot"): (
        "cache-target:snapshot",
        "consumer",
    ),
}
_TOKEN_BY_ROLE = {
    "command": COMMAND_TOKEN,
    "consumer": CONSUMER_TOKEN,
    "restore": RESTORE_TOKEN,
    "recovery": RECOVERY_TOKEN,
}


class _FakeSession:
    def __init__(self) -> None:
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def begin(self) -> Any:
        self.begin_calls += 1
        session = self

        class _Tx:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(
                self,
                exc_type: object,
                _exc: object,
                _traceback: object,
            ) -> None:
                if exc_type is None:
                    session.commit_calls += 1
                else:
                    session.rollback_calls += 1

        return _Tx()


class _FakeCacheTargetService:
    def __init__(self) -> None:
        self.all_calls: list[str] = []
        self.apply_calls: list[dict[str, Any]] = []
        self.claim_calls: list[dict[str, Any]] = []
        self.reconciliation_calls: list[dict[str, Any]] = []
        self.snapshot_calls: list[dict[str, Any]] = []
        self.reconciliation_begin_calls: list[dict[str, Any]] = []
        self.reconciliation_seal_calls: list[dict[str, Any]] = []
        self.reconciliation_metadata_calls: list[dict[str, Any]] = []
        self.reconciliation_completion_calls: list[dict[str, Any]] = []
        self.reconciliation_snapshot_calls: list[dict[str, Any]] = []
        self.reconciliation_completion_error: Exception | None = None
        self.reconciliation_snapshot_error: Exception | None = None
        self.snapshot_error: Exception | None = None
        self.operation_result: Any = SimpleNamespace(
            operation_id=RECONCILIATION_REQUEST_ID,
            status="superseded",
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            status_url=(f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}"),
        )
        self.restore_calls: list[dict[str, Any]] = []
        self.refresh_calls: list[dict[str, Any]] = []
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
        self.source_result: Any = SimpleNamespace(
            external_system=EXTERNAL_SYSTEM,
            target_key="target-1",
            state="deleted",
            restore_epoch=1,
            source_generation=2,
            source_payload_fingerprint="b" * 64,
            target_sequence=1,
            target_id=None,
            entity_tag=None,
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
            status_url=("/v1/ops/cache-target-operations/99999999-9999-4999-8999-999999999999"),
            retry_after_seconds=None,
        )
        self.reconciliation_snapshot_result: Any = SimpleNamespace(
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            external_system=EXTERNAL_SYSTEM,
            restore_epoch=4,
            high_watermark_cursor="snapshot-high-watermark",
            count=1,
            merkle_root="a" * 64,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
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
        self.snapshot_result: Any = SimpleNamespace(
            snapshot_id=RECONCILIATION_SNAPSHOT_ID,
            external_system=EXTERNAL_SYSTEM,
            restore_epoch=4,
            high_watermark_cursor="snapshot-high-watermark",
            count=1,
            merkle_root="a" * 64,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            items=[
                SimpleNamespace(
                    external_system=EXTERNAL_SYSTEM,
                    target_key="target-1",
                    state="active",
                    source_generation=1,
                    source_payload_fingerprint="b" * 64,
                )
            ],
            next_cursor="next-snapshot-page",
        )
        self.replay_result: Any = SimpleNamespace(
            event_id=EVENT_ID,
            status="retry",
            delivery_version=3,
            entity_tag=f'"{EVENT_ID}:3"',
        )
        self.refresh_result: Any = SimpleNamespace(
            request_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            status="queued",
            status_url="/v1/service/refresh-requests/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            retry_after_seconds=5,
            created_at=NOW,
            updated_at=NOW,
        )

    async def apply_cache_target_source(self, _session: Any, **kwargs: Any) -> Any:
        self.all_calls.append("apply_cache_target_source")
        self.apply_calls.append(kwargs)
        return self.apply_result

    async def get_cache_target_source(self, _session: Any, **_kwargs: Any) -> Any:
        self.all_calls.append("get_cache_target_source")
        return self.source_result

    async def get_cache_target_stream(
        self,
        _session: Any,
        *,
        external_system: str,
        consumer_id: str,
    ) -> Any:
        self.all_calls.append("get_cache_target_stream")
        assert external_system == EXTERNAL_SYSTEM
        if consumer_id != CONSUMER_ID:
            raise CacheTargetStreamConflict("consumer_mismatch", "consumer mismatch")
        return self.stream

    async def advance_cache_target_restore_fence(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("advance_cache_target_restore_fence")
        self.restore_calls.append(kwargs)
        return self.restore_result

    async def create_refresh_request(self, _session: Any, **kwargs: Any) -> Any:
        self.all_calls.append("create_refresh_request")
        self.refresh_calls.append(kwargs)
        return self.refresh_result

    async def claim_cache_target_events(self, _session: Any, **kwargs: Any) -> Any:
        self.all_calls.append("claim_cache_target_events")
        self.claim_calls.append(kwargs)
        return self.claim_result

    async def request_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("request_cache_target_reconciliation")
        self.reconciliation_calls.append(kwargs)
        return self.reconciliation_result

    async def begin_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("begin_cache_target_reconciliation")
        self.reconciliation_begin_calls.append(kwargs)
        return self.reconciliation_begin_result

    async def seal_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("seal_cache_target_reconciliation")
        self.reconciliation_seal_calls.append(kwargs)
        return self.reconciliation_seal_result

    async def complete_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("complete_cache_target_reconciliation")
        self.reconciliation_completion_calls.append(kwargs)
        if self.reconciliation_completion_error is not None:
            raise self.reconciliation_completion_error
        return self.reconciliation_completion_result

    async def get_cache_target_reconciliation(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("get_cache_target_reconciliation")
        self.reconciliation_metadata_calls.append(kwargs)
        if isinstance(self.reconciliation_metadata_result, Exception):
            raise self.reconciliation_metadata_result
        return self.reconciliation_metadata_result

    async def get_cache_target_reconciliation_snapshot(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("get_cache_target_reconciliation_snapshot")
        self.reconciliation_snapshot_calls.append(kwargs)
        if kwargs["consumer_id"] != CONSUMER_ID:
            raise CacheTargetStreamConflict("consumer_mismatch", "consumer mismatch")
        if self.reconciliation_snapshot_error is not None:
            raise self.reconciliation_snapshot_error
        return self.reconciliation_snapshot_result

    async def get_cache_target_snapshot(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("get_cache_target_snapshot")
        self.snapshot_calls.append(kwargs)
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return self.snapshot_result

    async def get_cache_target_dead_letter(
        self,
        _session: Any,
        *,
        event_id: str,
    ) -> Any | None:
        self.all_calls.append("get_cache_target_dead_letter")
        assert event_id == EVENT_ID
        return self.dead_letter

    async def get_cache_target_operation(
        self,
        _session: Any,
        *,
        operation_id: str,
    ) -> Any:
        self.all_calls.append("get_cache_target_operation")
        assert operation_id == RECONCILIATION_REQUEST_ID
        return self.operation_result

    async def replay_cache_target_dead_letter(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.all_calls.append("replay_cache_target_dead_letter")
        self.replay_calls.append(kwargs)
        return self.replay_result


def _token_sha256(token: str = TOKEN) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _principal_registry(
    *,
    consumer_id: str = CONSUMER_ID,
    external_systems: list[str] | None = None,
) -> list[dict[str, Any]]:
    systems = external_systems or [EXTERNAL_SYSTEM]
    return [
        {
            "principal_id": "svc:pinvi-command",
            "consumer_id": consumer_id,
            "token_sha256": _token_sha256(COMMAND_TOKEN),
            "scopes": ["cache-target:command"],
            "external_systems": systems,
        },
        {
            "principal_id": "svc:pinvi-consumer",
            "consumer_id": consumer_id,
            "token_sha256": _token_sha256(CONSUMER_TOKEN),
            "scopes": [
                "cache-target:read",
                "cache-target:claim",
                "cache-target:ack",
                "cache-target:nack",
                "cache-target:snapshot",
            ],
            "external_systems": systems,
        },
        {
            "principal_id": "svc:pinvi-restore",
            "consumer_id": consumer_id,
            "token_sha256": _token_sha256(RESTORE_TOKEN),
            "scopes": ["cache-target:restore-fence"],
            "external_systems": systems,
        },
        {
            "principal_id": "svc:pinvi-recovery",
            "consumer_id": consumer_id,
            "token_sha256": _token_sha256(RECOVERY_TOKEN),
            "scopes": ["cache-target:recovery", "cache-target:recovery-replay"],
            "external_systems": systems,
        },
    ]


def _settings(
    *,
    principals: list[dict[str, Any]] | None = None,
    admin_destructive_enabled: bool = False,
) -> ApiSettings:
    return ApiSettings(
        _env_file=None,
        admin_proxy_secret=None,
        ops_cancel_token=None,
        ops_fixture_token=None,
        ops_read_token=None,
        public_api_key_required=False,
        service_token=None,
        vworld_api_key=None,
        admin_destructive_enabled=admin_destructive_enabled,
        cache_target_service_principals=principals or _principal_registry(),
    )


def _client(
    service: _FakeCacheTargetService,
    *,
    settings: ApiSettings | None = None,
    session: _FakeSession | None = None,
) -> TestClient:
    app = create_app(settings or _settings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session or _FakeSession()

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


def _request_service_operation(
    client: TestClient,
    route: tuple[str, str],
    *,
    token: str,
) -> Any:
    method, template = route
    path = (
        template.replace("{external_system}", EXTERNAL_SYSTEM)
        .replace("{target_key}", "target-1")
        .replace("{request_id}", RECONCILIATION_REQUEST_ID)
        .replace("{event_id}", EVENT_ID)
    )
    headers = _service_headers(token=token)
    body: dict[str, Any] | None = None
    if route == (
        "put",
        "/v1/service/cache-targets/{external_system}/{target_key}",
    ):
        headers["If-None-Match"] = "*"
        body = _upsert_body()
    elif route == (
        "delete",
        "/v1/service/cache-targets/{external_system}/{target_key}",
    ):
        headers["If-Match"] = f'"{TARGET_ID}:7"'
        body = {
            "source_event_id": SOURCE_EVENT_ID,
            "restore_epoch": 1,
            "source_generation": 2,
            "occurred_at": NOW.isoformat(),
        }
    elif route == (
        "post",
        "/v1/service/cache-target-streams/{external_system}/restore-fences",
    ):
        headers["If-Match"] = f'"{EXTERNAL_SYSTEM}:2"'
        body = {
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "reason": "operator-requested restore barrier",
        }
    elif route == ("post", "/v1/service/refresh-requests"):
        body = {
            "external_system": EXTERNAL_SYSTEM,
            "target_keys": ["target-1"],
            "reason": "operator refresh",
        }
    elif route == ("post", "/v1/service/cache-target-event-claims"):
        body = {
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "limit": 1,
            "lease_seconds": 60,
        }
    elif route == ("post", "/v1/service/cache-target-event-acks"):
        body = {
            "consumer_id": CONSUMER_ID,
            "claim_id": CLAIM_ID,
            "lease_token": LEASE_TOKEN,
            "through_cursor": cache_target_event_cursor(1),
            "applied": [],
        }
    elif route == ("post", "/v1/service/cache-target-event-nacks"):
        body = {
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "claim_id": CLAIM_ID,
            "lease_token": LEASE_TOKEN,
            "event_id": EVENT_ID,
            "disposition": "permanent",
            "error_class": "unsupported",
            "error_fingerprint": "a" * 64,
        }
    elif route == (
        "post",
        "/v1/service/cache-target-event-dead-letters/{event_id}/replays",
    ):
        headers["If-Match"] = f'"{EVENT_ID}:2"'
        body = {"reason": "manual replay"}
    elif route == ("post", "/v1/service/cache-target-reconciliations"):
        headers["If-None-Match"] = "*"
        body = {
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "reason": "PinVi restore cutover",
        }
    elif route == (
        "post",
        "/v1/service/cache-target-reconciliations/{request_id}/seals",
    ):
        headers["If-Match"] = f'"{RECONCILIATION_REQUEST_ID}:2"'
        body = {
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "expected_item_count": 1,
            "expected_merkle_root": "a" * 64,
        }
    elif route == (
        "post",
        "/v1/service/cache-target-reconciliations/{request_id}/completions",
    ):
        body = {
            "external_system": EXTERNAL_SYSTEM,
            "consumer_id": CONSUMER_ID,
            "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
            "expected_restore_epoch": 4,
            "actual_merkle_root": "a" * 64,
        }
    return client.request(method.upper(), path, headers=headers, json=body)


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
        "superseded_reconciliation_request_id": (superseded_reconciliation_request_id),
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
def test_restore_fence_openapi_encodes_receipt_correlation_invariant() -> None:
    client = _client(_FakeCacheTargetService())

    operation = client.app.openapi()["paths"][
        "/v1/service/cache-target-streams/{external_system}/restore-fences"
    ]["post"]
    assert {"200", "201"} <= set(operation["responses"])
    assert operation["responses"]["200"]["description"] == "exact Idempotency-Key replay"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CacheTargetRestoreFenceResponse"
    }

    schema = client.app.openapi()["components"]["schemas"]["CacheTargetRestoreFenceRecord"]

    assert schema["oneOf"] == [
        {
            "properties": {
                "superseded_reconciliation_count": {"const": 0},
                "superseded_reconciliation_request_id": {"type": "null"},
            },
            "required": [
                "superseded_reconciliation_count",
                "superseded_reconciliation_request_id",
            ],
        },
        {
            "properties": {
                "superseded_reconciliation_count": {"const": 1},
                "superseded_reconciliation_request_id": {
                    "format": "uuid",
                    "type": "string",
                },
            },
            "required": [
                "superseded_reconciliation_count",
                "superseded_reconciliation_request_id",
            ],
        },
    ]

    validator = Draft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    assert validator.is_valid(
        _restore_fence_record_payload(
            superseded_reconciliation_count=0,
            superseded_reconciliation_request_id=None,
        )
    )
    assert validator.is_valid(
        _restore_fence_record_payload(
            superseded_reconciliation_count=1,
            superseded_reconciliation_request_id=RECONCILIATION_REQUEST_ID,
        )
    )
    assert not validator.is_valid(
        _restore_fence_record_payload(
            superseded_reconciliation_count=0,
            superseded_reconciliation_request_id=RECONCILIATION_REQUEST_ID,
        )
    )
    assert not validator.is_valid(
        _restore_fence_record_payload(
            superseded_reconciliation_count=1,
            superseded_reconciliation_request_id=None,
        )
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

    response = client.get(f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "superseded"
    operation_schema = client.app.openapi()["components"]["schemas"][
        "CacheTargetRecoveryOperationRecord"
    ]
    assert "superseded" in operation_schema["properties"]["status"]["enum"]
    assert operation_schema["properties"]["operation_id"]["format"] == "uuid"


@pytest.mark.unit
def test_ops_recovery_operation_rejects_non_uuid_operation_id() -> None:
    with pytest.raises(ValidationError, match="UUID"):
        CacheTargetRecoveryOperationRecord.model_validate(
            {
                "operation_id": "not-a-uuid",
                "status": "accepted",
            }
        )

    service = _FakeCacheTargetService()
    service.operation_result = SimpleNamespace(
        operation_id="not-a-uuid",
        status="accepted",
        snapshot_id=None,
        status_url=None,
    )
    client = _client(service)
    with pytest.raises(ValidationError, match="UUID"):
        client.get(f"/v1/ops/cache-target-operations/{RECONCILIATION_REQUEST_ID}")


@pytest.mark.unit
def test_put_cache_target_uses_bound_principal_and_create_precondition() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = client.put(
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
        headers=_service_headers(token=COMMAND_TOKEN, extra={"If-None-Match": "*"}),
        json=_upsert_body(),
    )

    assert response.status_code == 200, response.text
    assert response.headers["etag"] == f'"{TARGET_ID}:7"'
    assert response.json()["data"]["target_id"] == TARGET_ID
    assert response.json()["data"]["target_sequence"] == 1
    assert service.apply_calls[0]["consumer_id"] == CONSUMER_ID
    assert service.apply_calls[0]["create_only"] is True
    assert service.apply_calls[0]["expected_target_id"] is None


@pytest.mark.unit
def test_delete_cache_target_replay_preserves_historical_identity_and_etag() -> None:
    service = _FakeCacheTargetService()
    entity_tag = f'"{TARGET_ID}:8"'
    service.apply_result = SimpleNamespace(
        external_system=EXTERNAL_SYSTEM,
        target_key="target-1",
        state="deleted",
        restore_epoch=1,
        source_generation=2,
        source_payload_fingerprint="b" * 64,
        target_sequence=1,
        target_id=TARGET_ID,
        entity_tag=entity_tag,
        target=None,
        occurred_at=NOW,
        updated_at=NOW,
        idempotent_replay=True,
    )
    client = _client(service)

    response = client.request(
        "DELETE",
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
        headers=_service_headers(
            token=COMMAND_TOKEN,
            extra={"If-Match": f'"{TARGET_ID}:7"'},
        ),
        json={
            "source_event_id": SOURCE_EVENT_ID,
            "restore_epoch": 1,
            "source_generation": 2,
            "occurred_at": NOW.isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["etag"] == entity_tag
    assert response.json()["data"]["state"] == "deleted"
    assert response.json()["data"]["target_id"] == TARGET_ID
    assert response.json()["data"]["entity_tag"] == entity_tag


@pytest.mark.unit
def test_get_deleted_cache_target_keeps_nullable_read_projection() -> None:
    service = _FakeCacheTargetService()
    service.source_result.target_sequence = None
    client = _client(service)

    response = client.get(
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1?include_deleted=true",
        headers=_service_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["state"] == "deleted"
    assert response.json()["data"]["target_id"] is None
    assert response.json()["data"]["entity_tag"] is None
    assert response.json()["data"]["target_sequence"] is None
    assert "etag" not in response.headers


@pytest.mark.unit
@pytest.mark.parametrize("target_sequence", [None, 0])
def test_put_mutation_rejects_nonpositive_or_null_target_sequence(
    target_sequence: int | None,
) -> None:
    service = _FakeCacheTargetService()
    service.apply_result.target_sequence = target_sequence
    client = _client(service)

    with pytest.raises(ValidationError, match="target_sequence"):
        client.put(
            f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
            headers=_service_headers(
                token=COMMAND_TOKEN,
                extra={"If-None-Match": "*"},
            ),
            json=_upsert_body(),
        )


@pytest.mark.unit
def test_delete_mutation_rejects_nullable_target_receipt() -> None:
    service = _FakeCacheTargetService()
    service.apply_result = service.source_result
    client = _client(service)

    with pytest.raises(ValidationError, match="target_id"):
        client.request(
            "DELETE",
            f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
            headers=_service_headers(
                token=COMMAND_TOKEN,
                extra={"If-Match": f'"{TARGET_ID}:7"'},
            ),
            json={
                "source_event_id": SOURCE_EVENT_ID,
                "restore_epoch": 1,
                "source_generation": 2,
                "occurred_at": NOW.isoformat(),
            },
        )


@pytest.mark.unit
def test_put_cache_target_rejects_missing_precondition_before_service_call() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = client.put(
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
        headers=_service_headers(token=COMMAND_TOKEN),
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
        headers=_service_headers(
            token=COMMAND_TOKEN,
            extra={"If-Match": f'"{TARGET_ID}:7"'},
        ),
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
        headers=_service_headers(token=COMMAND_TOKEN, extra={"If-None-Match": "*"}),
        json=body,
    )

    assert response.status_code == 422
    assert service.apply_calls == []


@pytest.mark.unit
@pytest.mark.parametrize("invalid_target_key", ["e\u0301", "\u3000target-1"])
def test_put_cache_target_rejects_noncanonical_target_key_before_service_call(
    invalid_target_key: str,
) -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = client.put(
        f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/{invalid_target_key}",
        headers=_service_headers(token=COMMAND_TOKEN, extra={"If-None-Match": "*"}),
        json=_upsert_body(),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.apply_calls == []


@pytest.mark.unit
def test_reconciliation_begin_rejects_noncanonical_system_before_service_call() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = client.post(
        "/v1/service/cache-target-reconciliations",
        headers=_service_headers(
            token=RECOVERY_TOKEN,
            extra={"If-None-Match": "*"},
        ),
        json={
            "external_system": "\u3000pinvi",
            "consumer_id": CONSUMER_ID,
            "expected_restore_epoch": 4,
            "reason": "PinVi restore cutover",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert service.reconciliation_begin_calls == []


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
    client = _client(service)

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
    client = _client(service)

    response = client.post(
        "/v1/service/refresh-requests",
        headers=_service_headers(token=COMMAND_TOKEN),
        json={
            "external_system": EXTERNAL_SYSTEM,
            "target_keys": [f"target-{index}" for index in range(501)],
            "reason": "operator refresh",
        },
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_refresh_request_rejects_duplicate_targets_before_service_call() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = client.post(
        "/v1/service/refresh-requests",
        headers={
            **_service_headers(token=COMMAND_TOKEN),
            "Idempotency-Key": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        },
        json={
            "external_system": EXTERNAL_SYSTEM,
            "target_keys": ["target-1", "target-1"],
            "reason": "operator refresh",
        },
    )

    assert response.status_code == 422
    assert service.refresh_calls == []


@pytest.mark.unit
def test_refresh_request_accepts_full_root_target_key_length() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)
    target_key = "x" * 512

    response = client.post(
        "/v1/service/refresh-requests",
        headers={
            **_service_headers(token=COMMAND_TOKEN),
            "Idempotency-Key": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        },
        json={
            "external_system": EXTERNAL_SYSTEM,
            "target_keys": [target_key],
            "reason": "operator refresh",
        },
    )

    assert response.status_code == 202, response.text
    assert service.refresh_calls[0]["target_keys"] == [target_key]


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
def test_removed_cache_target_consumer_umbrella_is_rejected_by_registry() -> None:
    principals = _principal_registry()
    principals[0]["scopes"] = ["cache-target:consumer"]
    with pytest.raises(ValidationError) as exc_info:
        _settings(principals=principals)

    assert exc_info.value.errors()[0]["input"] == "cache-target:consumer"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("role", "token"),
    [
        ("consumer", CONSUMER_TOKEN),
        ("restore", RESTORE_TOKEN),
        ("recovery", RECOVERY_TOKEN),
    ],
)
@pytest.mark.parametrize("command_route", ["put", "delete", "refresh"])
def test_non_command_roles_cannot_call_command_routes(
    role: str,
    token: str,
    command_route: str,
) -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    if command_route == "put":
        response = client.put(
            f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
            headers=_service_headers(token=token, extra={"If-None-Match": "*"}),
            json=_upsert_body(),
        )
    elif command_route == "delete":
        response = client.request(
            "DELETE",
            f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
            headers=_service_headers(
                token=token,
                extra={"If-Match": f'"{TARGET_ID}:7"'},
            ),
            json={
                "source_event_id": SOURCE_EVENT_ID,
                "restore_epoch": 1,
                "source_generation": 2,
                "occurred_at": NOW.isoformat(),
            },
        )
    else:
        response = client.post(
            "/v1/service/refresh-requests",
            headers=_service_headers(token=token),
            json={
                "external_system": EXTERNAL_SYSTEM,
                "target_keys": ["target-1"],
                "reason": "operator refresh",
            },
        )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "CACHE_TARGET_SCOPE_FORBIDDEN"
    assert role in {"consumer", "restore", "recovery"}
    assert service.apply_calls == []
    assert service.refresh_calls == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "consumer_or_recovery_route",
    [
        "read",
        "claim",
        "ack",
        "nack",
        "snapshot",
        "restore-fence",
        "recovery",
        "recovery-replay",
    ],
)
def test_command_scope_cannot_call_other_role_routes(
    consumer_or_recovery_route: str,
) -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    if consumer_or_recovery_route == "read":
        response = client.get(
            f"/v1/service/cache-targets/{EXTERNAL_SYSTEM}/target-1",
            headers=_service_headers(token=COMMAND_TOKEN),
        )
    elif consumer_or_recovery_route == "claim":
        response = client.post(
            "/v1/service/cache-target-event-claims",
            headers=_service_headers(token=COMMAND_TOKEN),
            json={
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "limit": 1,
                "lease_seconds": 60,
            },
        )
    elif consumer_or_recovery_route == "ack":
        response = client.post(
            "/v1/service/cache-target-event-acks",
            headers={SERVICE_TOKEN_HEADER: COMMAND_TOKEN},
            json={
                "consumer_id": CONSUMER_ID,
                "claim_id": CLAIM_ID,
                "lease_token": LEASE_TOKEN,
                "through_cursor": cache_target_event_cursor(1),
                "applied": [],
            },
        )
    elif consumer_or_recovery_route == "nack":
        response = client.post(
            "/v1/service/cache-target-event-nacks",
            headers={SERVICE_TOKEN_HEADER: COMMAND_TOKEN},
            json={
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "claim_id": CLAIM_ID,
                "lease_token": LEASE_TOKEN,
                "event_id": EVENT_ID,
                "disposition": "permanent",
                "error_class": "unsupported",
                "error_fingerprint": "a" * 64,
            },
        )
    elif consumer_or_recovery_route == "snapshot":
        response = client.get(
            f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
            headers=_service_headers(token=COMMAND_TOKEN),
        )
    elif consumer_or_recovery_route == "restore-fence":
        response = client.post(
            f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}/restore-fences",
            headers=_service_headers(
                token=COMMAND_TOKEN,
                extra={"If-Match": f'"{EXTERNAL_SYSTEM}:2"'},
            ),
            json={
                "consumer_id": CONSUMER_ID,
                "expected_restore_epoch": 4,
                "reason": "operator-requested restore barrier",
            },
        )
    elif consumer_or_recovery_route == "recovery":
        response = client.post(
            "/v1/service/cache-target-reconciliations",
            headers=_service_headers(
                token=COMMAND_TOKEN,
                extra={"If-None-Match": "*"},
            ),
            json={
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": CONSUMER_ID,
                "expected_restore_epoch": 4,
                "reason": "PinVi restore cutover",
            },
        )
    else:
        response = client.post(
            f"/v1/service/cache-target-event-dead-letters/{EVENT_ID}/replays",
            headers=_service_headers(
                token=COMMAND_TOKEN,
                extra={"If-Match": f'"{EVENT_ID}:2"'},
            ),
            json={"reason": "manual replay"},
        )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "CACHE_TARGET_SCOPE_FORBIDDEN"
    assert service.claim_calls == []
    assert service.restore_calls == []
    assert service.reconciliation_begin_calls == []
    assert service.snapshot_calls == []
    assert service.replay_calls == []


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
    principals = _principal_registry()
    principals[1]["token_sha256"] = principals[0]["token_sha256"]
    with pytest.raises(ValueError, match="token digests must be unique"):
        _settings(principals=principals)


@pytest.mark.unit
@pytest.mark.parametrize(
    "protected_overrides",
    [
        {"admin_proxy_secret": COMMAND_TOKEN},
        {"service_token": COMMAND_TOKEN},
        {"metrics_token": COMMAND_TOKEN},
        {"cursor_signing_secret": COMMAND_TOKEN},
        {
            "ops_read_token": COMMAND_TOKEN,
            "ops_cancel_token": "distinct-ops-cancel-token-000000000000000000",
            "ops_fixture_token": "distinct-ops-fixture-token-00000000000000000",
        },
        {
            "ops_read_token": "distinct-ops-read-token-00000000000000000000",
            "ops_cancel_token": COMMAND_TOKEN,
            "ops_fixture_token": "distinct-ops-fixture-token-00000000000000000",
        },
    ],
)
def test_cache_target_registry_rejects_protected_secret_digest_collision(
    protected_overrides: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="digest must be distinct"):
        ApiSettings(
            _env_file=None,
            cache_target_service_principals=_principal_registry(),
            **protected_overrides,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "cache_role_token",
    [COMMAND_TOKEN, CONSUMER_TOKEN, RESTORE_TOKEN, RECOVERY_TOKEN],
)
def test_cache_target_registry_rejects_public_api_key_digest_collision(
    cache_role_token: str,
) -> None:
    with pytest.raises(ValueError, match="distinct from public API key"):
        ApiSettings(
            _env_file=None,
            cache_target_service_principals=_principal_registry(),
            vworld_api_key=cache_role_token,
        )


@pytest.mark.unit
def test_cache_target_openapi_declares_route_scope_and_caller_role_contract() -> None:
    schema = create_app(_settings()).openapi()
    actual: dict[tuple[str, str], str] = {}
    for path, path_item in schema["paths"].items():
        if not path.startswith(
            ("/v1/service/cache-target", "/v1/service/refresh-requests")
        ):
            continue
        for method, operation in path_item.items():
            if method not in {"get", "put", "post", "delete"}:
                continue
            actual[(method, path)] = operation["x-required-service-scope"]

    assert set(actual) == set(_SERVICE_OPERATION_CONTRACT)
    for route, (required_scope, caller_role) in _SERVICE_OPERATION_CONTRACT.items():
        assert actual[route] == required_scope
        assert required_scope in _ROLE_SCOPES[caller_role]


@pytest.mark.unit
@pytest.mark.parametrize("route", list(_SERVICE_OPERATION_CONTRACT))
def test_cache_target_runtime_uses_inventory_required_scope_before_service_call(
    route: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import cache_target_streams as router_module

    required_scope, caller_role = _SERVICE_OPERATION_CONTRACT[route]
    captured_scopes: list[str] = []

    def _capture_scope(
        _context: Any,
        *,
        scope: str,
        external_system: str | None = None,
    ) -> None:
        del external_system
        captured_scopes.append(scope)
        raise HTTPException(status_code=418, detail="scope captured before lookup")

    monkeypatch.setattr(
        router_module,
        "require_cache_target_service_scope",
        _capture_scope,
    )
    service = _FakeCacheTargetService()
    client = _client(service)

    response = _request_service_operation(
        client,
        route,
        token=_TOKEN_BY_ROLE[caller_role],
    )

    assert response.status_code == 418, (route, response.text)
    assert captured_scopes == [required_scope]
    assert service.all_calls == []


_WRONG_ROLE_OPERATION_CASES = [
    (route, wrong_role)
    for route, (_scope, caller_role) in _SERVICE_OPERATION_CONTRACT.items()
    for wrong_role in _TOKEN_BY_ROLE
    if wrong_role != caller_role
]


@pytest.mark.unit
@pytest.mark.parametrize(("route", "wrong_role"), _WRONG_ROLE_OPERATION_CASES)
def test_cache_target_inventory_wrong_roles_are_forbidden_before_service_call(
    route: tuple[str, str],
    wrong_role: str,
) -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

    response = _request_service_operation(
        client,
        route,
        token=_TOKEN_BY_ROLE[wrong_role],
    )

    assert response.status_code == 403, (route, wrong_role, response.text)
    assert response.json()["code"] == "CACHE_TARGET_SCOPE_FORBIDDEN"
    assert service.all_calls == []


@pytest.mark.unit
def test_cache_target_registry_accepts_exact_profiles_as_scope_sets() -> None:
    principals = _principal_registry()
    principals[1]["scopes"] = list(reversed(principals[1]["scopes"]))
    principals[3]["scopes"] = list(reversed(principals[3]["scopes"]))

    settings = _settings(principals=principals)

    assert len(settings.cache_target_service_principals) == 4


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_scopes",
    [
        ["cache-target:command", "cache-target:read"],
        ["cache-target:read"],
        ["cache-target:recovery-replay"],
    ],
)
def test_cache_target_registry_rejects_mixed_or_incomplete_role_profiles(
    invalid_scopes: list[str],
) -> None:
    principals = _principal_registry()
    principals[0]["scopes"] = invalid_scopes

    with pytest.raises(ValidationError, match="exact role profile"):
        _settings(principals=principals)


@pytest.mark.unit
def test_cache_target_registry_rejects_missing_or_duplicate_binding_roles() -> None:
    missing = _principal_registry()[:-1]
    with pytest.raises(ValueError, match="missing exact roles"):
        _settings(principals=missing)

    duplicate = _principal_registry()
    duplicate.append(
        {
            **duplicate[0],
            "principal_id": "svc:pinvi-command-duplicate",
            "token_sha256": _token_sha256(
                "cache-target-command-duplicate-token-000000000000"
            ),
        }
    )
    with pytest.raises(ValueError, match="exactly one principal"):
        _settings(principals=duplicate)


@pytest.mark.unit
def test_cache_target_registry_rejects_split_or_overlapping_binding_ownership() -> None:
    split = _principal_registry()
    split[3]["consumer_id"] = "other-consumer"
    with pytest.raises(ValueError, match="one binding owner"):
        _settings(principals=split)

    overlap = _principal_registry()
    other_group = _principal_registry(consumer_id="other-consumer")
    for index, principal in enumerate(other_group):
        principal["principal_id"] = f"svc:other-{index}"
        principal["token_sha256"] = _token_sha256(
            f"cache-target-other-token-{index}-000000000000000000"
        )
    with pytest.raises(ValueError, match="one binding owner"):
        _settings(principals=[*overlap, *other_group])


@pytest.mark.unit
def test_cache_target_registry_rejects_same_consumer_disjoint_bindings() -> None:
    other_group = _principal_registry(external_systems=["other"])
    for index, principal in enumerate(other_group):
        principal["principal_id"] = f"svc:other-{index}"
        principal["token_sha256"] = _token_sha256(
            f"cache-target-other-token-{index}-000000000000000000"
        )

    with pytest.raises(ValueError, match="exactly one canonical binding"):
        _settings(principals=[*_principal_registry(), *other_group])


@pytest.mark.unit
def test_cache_target_registry_accepts_sorted_multi_system_union_binding() -> None:
    settings = _settings(
        principals=_principal_registry(external_systems=["other", EXTERNAL_SYSTEM]),
    )

    assert all(
        principal.external_systems == ["other", EXTERNAL_SYSTEM]
        for principal in settings.cache_target_service_principals
    )


@pytest.mark.unit
def test_cache_target_registry_accepts_multiple_disjoint_complete_groups() -> None:
    other_group = _principal_registry(
        consumer_id="other-consumer",
        external_systems=["other"],
    )
    for index, principal in enumerate(other_group):
        principal["principal_id"] = f"svc:other-{index}"
        principal["token_sha256"] = _token_sha256(
            f"cache-target-other-token-{index}-000000000000000000"
        )

    settings = _settings(principals=[*_principal_registry(), *other_group])

    assert len(settings.cache_target_service_principals) == 8


@pytest.mark.unit
@pytest.mark.parametrize("route", ["ack", "nack"])
def test_cross_binding_consumer_mutations_are_forbidden_before_service_call(
    route: str,
) -> None:
    other_group = _principal_registry(
        consumer_id="other-consumer",
        external_systems=["other"],
    )
    for index, principal in enumerate(other_group):
        principal["principal_id"] = f"svc:other-{index}"
        token = (
            OTHER_CONSUMER_TOKEN
            if principal["scopes"][0] == "cache-target:read"
            else f"cache-target-other-token-{index}-000000000000000000"
        )
        principal["token_sha256"] = _token_sha256(token)
    service = _FakeCacheTargetService()
    client = _client(
        service,
        settings=_settings(principals=[*_principal_registry(), *other_group]),
    )

    if route == "ack":
        response = client.post(
            "/v1/service/cache-target-event-acks",
            headers={SERVICE_TOKEN_HEADER: OTHER_CONSUMER_TOKEN},
            json={
                "consumer_id": CONSUMER_ID,
                "claim_id": CLAIM_ID,
                "lease_token": LEASE_TOKEN,
                "through_cursor": cache_target_event_cursor(1),
                "applied": [],
            },
        )
    else:
        response = client.post(
            "/v1/service/cache-target-event-nacks",
            headers={SERVICE_TOKEN_HEADER: OTHER_CONSUMER_TOKEN},
            json={
                "external_system": EXTERNAL_SYSTEM,
                "consumer_id": "other-consumer",
                "claim_id": CLAIM_ID,
                "lease_token": LEASE_TOKEN,
                "event_id": EVENT_ID,
                "disposition": "permanent",
                "error_class": "unsupported",
                "error_fingerprint": "a" * 64,
            },
        )

    assert response.status_code == 403, response.text
    assert response.json()["code"] in {
        "CACHE_TARGET_CONSUMER_FORBIDDEN",
        "CACHE_TARGET_EXTERNAL_SYSTEM_FORBIDDEN",
    }
    assert service.all_calls == []


@pytest.mark.unit
def test_cache_target_consumer_header_is_only_exact_binding_check() -> None:
    service = _FakeCacheTargetService()
    client = _client(service)

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
    settings = _settings(
        principals=_principal_registry(external_systems=["other"]),
    )
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
        assert kwargs["actor"] == "svc:pinvi-restore"
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
    client = _client(service)

    response = client.post(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}/restore-fences",
        headers=_service_headers(
            token=RESTORE_TOKEN,
            extra={"If-Match": f'"{EXTERNAL_SYSTEM}:2"'},
        ),
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
    # 첫 transport response는 POST contract의 201이나, exact idempotency replay는
    # ADR-081에 따라 200을 replay한다.
    assert captured_complete["status_code"] == 200
    assert captured_complete["response_headers"] == {"ETag": f'"{EXTERNAL_SYSTEM}:3"'}


@pytest.mark.unit
def test_restore_fence_exact_replay_returns_200_after_initial_201(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.domain_command_service import DomainCommandReplay
    from kortravelmap.api.routers import cache_target_streams as router_module

    service = _FakeCacheTargetService()
    captured: dict[str, Any] = {}

    async def _begin_domain_command(_session: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(command_id=124, request_fingerprint="c" * 64)

    async def _complete_domain_command(_session: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(router_module, "begin_domain_command", _begin_domain_command)
    monkeypatch.setattr(router_module, "complete_domain_command", _complete_domain_command)
    client = _client(service)
    headers = _service_headers(
        token=RESTORE_TOKEN,
        extra={"If-Match": f'"{EXTERNAL_SYSTEM}:2"'},
    )
    body = {
        "consumer_id": CONSUMER_ID,
        "expected_restore_epoch": 4,
        "reason": "operator-requested restore barrier",
    }

    first = client.post(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}/restore-fences",
        headers=headers,
        json=body,
    )
    assert first.status_code == 201, first.text
    assert captured["status_code"] == 200

    replay_record = SimpleNamespace(
        operation="service.cache-target-restore-fence.create",
        response_body=captured["response"].model_dump(mode="json"),
        response_status=captured["status_code"],
        response_headers=captured["response_headers"],
    )

    async def _replay_domain_command(_session: Any, **_kwargs: Any) -> Any:
        raise DomainCommandReplay(replay_record)

    monkeypatch.setattr(router_module, "begin_domain_command", _replay_domain_command)
    replay = client.post(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}/restore-fences",
        headers=headers,
        json=body,
    )

    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert replay.headers["etag"] == first.headers["etag"]
    assert replay.headers["idempotency-replayed"] == "true"
    assert len(service.restore_calls) == 1


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
    client = _client(service)

    response = client.post(
        f"/v1/service/cache-target-streams/{EXTERNAL_SYSTEM}/restore-fences",
        headers=_service_headers(
            token=RESTORE_TOKEN,
            extra={"If-Match": '"other:2"'},
        ),
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
        assert kwargs["actor"] == "svc:pinvi-recovery"
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
    client = _client(service)

    response = client.post(
        "/v1/service/cache-target-reconciliations",
        headers=_service_headers(
            token=RECOVERY_TOKEN,
            extra={"If-None-Match": "*"},
        ),
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
    client = _client(service)

    response = client.post(
        "/v1/service/cache-target-reconciliations",
        headers=_service_headers(token=RECOVERY_TOKEN, extra=extra_headers),
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
        assert kwargs["actor"] == "svc:pinvi-recovery"
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
    client = _client(service)
    path = f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/seals"
    headers = _service_headers(
        token=RECOVERY_TOKEN,
        extra={"If-Match": f'"{RECONCILIATION_REQUEST_ID}:1"'},
    )
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
    assert service.reconciliation_metadata_calls == [{"request_id": RECONCILIATION_REQUEST_ID}]
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
        operation="service.cache-target-reconciliation.seal",
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
    client = _client(service)

    response = client.post(
        f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/seals",
        headers=_service_headers(
            token=RECOVERY_TOKEN,
            extra={"If-Match": f'"{RECONCILIATION_REQUEST_ID}:1"'},
        ),
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
    assert service.reconciliation_metadata_calls == [{"request_id": RECONCILIATION_REQUEST_ID}]
    assert ledger_calls == []
    assert service.reconciliation_seal_calls == []
    assert service.reconciliation_snapshot_calls == []
    assert service.reconciliation_completion_calls == []


@pytest.mark.unit
def test_service_snapshot_commits_route_owned_transaction() -> None:
    service = _FakeCacheTargetService()
    session = _FakeSession()
    client = _client(service, session=session)

    response = client.get(
        f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}?page_size=1",
        headers=_service_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["snapshot_id"] == RECONCILIATION_SNAPSHOT_ID
    assert response.json()["data"]["created_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert response.json()["data"]["expires_at"] == (
        NOW + timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    assert response.json()["meta"]["page"]["next_cursor"] == "next-snapshot-page"
    assert session.begin_calls == 1
    assert session.commit_calls == 1
    assert session.rollback_calls == 0
    assert service.snapshot_calls == [
        {
            "external_system": EXTERNAL_SYSTEM,
            "limit": 1,
            "cursor": None,
        }
    ]


@pytest.mark.unit
def test_service_snapshot_rolls_back_route_owned_transaction_on_error() -> None:
    service = _FakeCacheTargetService()
    service.snapshot_error = RuntimeError("snapshot failed after write")
    session = _FakeSession()
    client = _client(service, session=session)

    with pytest.raises(RuntimeError, match="snapshot failed after write"):
        client.get(
            f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
            headers=_service_headers(),
        )

    assert session.begin_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("code", "expected_code"),
    [
        ("snapshot_barrier_timeout", "SNAPSHOT_BARRIER_TIMEOUT"),
        ("snapshot_busy", "SNAPSHOT_BUSY"),
        ("snapshot_ttl_too_short", "SNAPSHOT_TTL_TOO_SHORT"),
    ],
)
def test_service_snapshot_unavailable_is_retryable_without_waiting(
    code: str,
    expected_code: str,
) -> None:
    """barrier/lock을 못 잡은 실패는 아무것도 태우지 않았으므로 곧바로 다시 와도 된다."""

    service = _FakeCacheTargetService()
    service.snapshot_error = CacheTargetStreamConflict(
        code,
        "snapshot already in progress",
    )
    session = _FakeSession()
    client = _client(service, session=session)

    response = client.get(
        f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
        headers=_service_headers(),
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["code"] == expected_code
    assert session.commit_calls == 0
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_service_snapshot_build_timeout_waits_out_the_whole_budget() -> None:
    """예산을 통째로 태운 실패는 1초 뒤 재시도를 지시하면 안 된다.

    재시도가 즉시 advisory lock을 다시 잡고 같은 예산을 또 태우므로, 그 stream은
    barrier를 놓지 않는 100% duty cycle로 물린다. 그동안 writer는 계속 밀린다.
    """

    service = _FakeCacheTargetService()
    service.snapshot_error = CacheTargetStreamConflict(
        "snapshot_build_timeout",
        "snapshot materialization 누적 제한 시간이 초과되었습니다.",
    )
    session = _FakeSession()
    client = _client(service, session=session)

    response = client.get(
        f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
        headers=_service_headers(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "SNAPSHOT_BUILD_TIMEOUT"
    retry_after = int(response.headers["retry-after"])
    assert retry_after == int(snapshot_build_budget_seconds())
    assert retry_after > 1


@pytest.mark.unit
def test_build_timeout_retry_after_follows_the_budget_at_request_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """예산을 바꾸면 wire 값도 따라와야 한다.

    import 시각에 얼려 두면 예산을 바꾼 프로세스에서 둘이 갈린다. 예산과 같은지만 보는
    단언은 양쪽이 같은 상수를 읽으므로 그 어긋남을 보지 못한다 — 그래서 흔든다.
    """

    monkeypatch.setattr(
        cache_target_reconciliation_repo,
        "_SNAPSHOT_BUILD_TIMEOUT_SECONDS",
        123.0,
    )
    service = _FakeCacheTargetService()
    service.snapshot_error = CacheTargetStreamConflict(
        "snapshot_build_timeout",
        "snapshot materialization 누적 제한 시간이 초과되었습니다.",
    )
    client = _client(service, session=_FakeSession())

    response = client.get(
        f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
        headers=_service_headers(),
    )

    assert response.headers["retry-after"] == "123"


@pytest.mark.unit
def test_stream_busy_retry_after_is_longer_than_the_lock_wait() -> None:
    """재시도 간격이 lock 대기보다 짧으면 duty cycle이 높아 무한 대기와 크게 다르지 않다.

    대기 `w`초, 재시도 간격 `r`초면 한 client가 붙드는 connection 몫은 `w / (w + r)`이다.
    `w=5, r=1`이면 83%다 — 그건 pool 고갈을 고친 것이 아니라 17% 할인이다.
    """

    service = _FakeCacheTargetService()
    service.snapshot_error = CacheTargetStreamConflict(
        "stream_busy",
        "stream이 다른 작업에 잡혀 있습니다.",
    )
    client = _client(service, session=_FakeSession())

    response = client.get(
        f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
        headers=_service_headers(),
    )

    assert response.status_code == 503
    retry_after = int(response.headers["retry-after"])
    lock_wait_seconds = int(
        cache_target_stream_repo.STREAM_WRITER_LOCK_TIMEOUT.removesuffix("s")
    )
    assert retry_after > lock_wait_seconds, (
        f"재시도 간격 {retry_after}초가 lock 대기 {lock_wait_seconds}초보다 짧다 — "
        f"duty cycle {lock_wait_seconds / (lock_wait_seconds + retry_after):.0%}"
    )


@pytest.mark.unit
def test_service_snapshot_capacity_returns_oldest_expiry_retry_after() -> None:
    service = _FakeCacheTargetService()
    service.snapshot_error = CacheTargetStreamConflict(
        "snapshot_capacity_exceeded",
        "snapshot capacity reached",
        current={
            "snapshot_count": 2,
            "snapshot_limit": 2,
            "oldest_expires_at": "2026-08-01T12:45:00+00:00",
            "retry_after_seconds": 2_701,
        },
    )
    session = _FakeSession()
    client = _client(service, session=session)

    response = client.get(
        f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
        headers=_service_headers(),
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "2701"
    problem = response.json()
    assert problem["code"] == "SNAPSHOT_CAPACITY_EXCEEDED"
    assert problem["details"]["snapshot_limit"] == 2
    assert problem["details"]["oldest_expires_at"] == (
        "2026-08-01T12:45:00+00:00"
    )
    assert session.commit_calls == 0
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_service_snapshot_item_ceiling_returns_non_retryable_payload_too_large() -> None:
    service = _FakeCacheTargetService()
    service.snapshot_error = CacheTargetStreamConflict(
        "snapshot_item_limit_exceeded",
        "snapshot item capacity reached",
        current={"item_count_lower_bound": 1_000_001, "item_limit": 1_000_000},
    )
    session = _FakeSession()
    client = _client(service, session=session)

    response = client.get(
        f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
        headers=_service_headers(),
    )

    assert response.status_code == 413
    assert "retry-after" not in response.headers
    assert response.json()["code"] == "SNAPSHOT_ITEM_LIMIT_EXCEEDED"
    assert response.json()["details"] == {
        "item_count_lower_bound": 1_000_001,
        "item_limit": 1_000_000,
    }
    assert session.commit_calls == 0
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_service_snapshot_byte_ceiling_returns_non_retryable_payload_too_large() -> None:
    service = _FakeCacheTargetService()
    service.snapshot_error = CacheTargetStreamConflict(
        "snapshot_byte_limit_exceeded",
        "snapshot byte capacity reached",
        current={
            "material_bytes_lower_bound": 58_720_257,
            "material_byte_limit": 58_720_256,
        },
    )
    session = _FakeSession()
    client = _client(service, session=session)

    response = client.get(
        f"/v1/service/cache-target-snapshots/{EXTERNAL_SYSTEM}",
        headers=_service_headers(),
    )

    assert response.status_code == 413
    assert "retry-after" not in response.headers
    assert response.json()["code"] == "SNAPSHOT_BYTE_LIMIT_EXCEEDED"
    assert response.json()["details"]["material_byte_limit"] == 58_720_256
    assert session.commit_calls == 0
    assert session.rollback_calls == 1


@pytest.mark.unit
def test_reconciliation_snapshot_compaction_returns_typed_gone_receipt() -> None:
    service = _FakeCacheTargetService()
    service.reconciliation_snapshot_error = CacheTargetStreamConflict(
        "snapshot_material_compacted",
        "snapshot item material compacted",
        current={
            "snapshot_id": RECONCILIATION_SNAPSHOT_ID,
            "item_count": 1,
            "merkle_root": "a" * 64,
            "compacted_at": "2026-08-18T00:00:00+00:00",
        },
    )
    client = _client(service)

    response = client.get(
        "/v1/service/cache-target-reconciliations/"
        f"{RECONCILIATION_REQUEST_ID}/snapshot",
        headers=_service_headers(),
    )

    assert response.status_code == 410
    assert "retry-after" not in response.headers
    assert response.json()["code"] == "SNAPSHOT_MATERIAL_COMPACTED"
    assert response.json()["details"]["snapshot_id"] == RECONCILIATION_SNAPSHOT_ID
    assert response.json()["details"]["merkle_root"] == "a" * 64


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
        assert kwargs["actor"] == "svc:pinvi-consumer"
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
    client = _client(service)
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
            principals=_principal_registry(consumer_id="other-consumer"),
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
    client = _client(service)

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
    assert service.reconciliation_metadata_calls == [{"request_id": RECONCILIATION_REQUEST_ID}]
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
    client = _client(service)

    response = client.get(
        f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/snapshot",
        headers={SERVICE_TOKEN_HEADER: TOKEN},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CACHE_TARGET_EXTERNAL_SYSTEM_FORBIDDEN"
    assert service.reconciliation_metadata_calls == [{"request_id": RECONCILIATION_REQUEST_ID}]
    assert service.reconciliation_snapshot_calls == []


@pytest.mark.unit
def test_reconciliation_snapshot_missing_request_returns_404() -> None:
    service = _FakeCacheTargetService()
    service.reconciliation_metadata_result = CacheTargetStreamConflict(
        "reconciliation_not_found",
        "reconciliation request가 없습니다.",
    )
    client = _client(service)

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
            _service_headers(
                token=RECOVERY_TOKEN,
                extra={"If-Match": f'"{RECONCILIATION_REQUEST_ID}:1"'},
            ),
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
    client = _client(service)

    response = client.post(
        f"/v1/service/cache-target-reconciliations/{RECONCILIATION_REQUEST_ID}/{path_suffix}",
        headers=headers,
        json=body,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RECONCILIATION_NOT_FOUND"
    assert service.reconciliation_metadata_calls == [{"request_id": RECONCILIATION_REQUEST_ID}]
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
    client = _client(service)
    path = (
        "/v1/service/cache-target-reconciliations/88888888-8888-4888-8888-888888888888/completions"
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
        assert kwargs["actor"] == "svc:pinvi-recovery"
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
    client = _client(service)
    path = f"/v1/service/cache-target-event-dead-letters/{EVENT_ID}/replays"
    headers = _service_headers(
        token=RECOVERY_TOKEN,
        extra={"If-Match": f'"{EVENT_ID}:2"'},
    )
    first = client.post(path, headers=headers, json={"reason": "manual replay"})
    assert first.status_code == 200, first.text
    assert captured["response_headers"] == {"ETag": f'"{EVENT_ID}:3"'}
    assert len(service.replay_calls) == 1

    replay_record = SimpleNamespace(
        operation="service.cache-target-dead-letter.replay",
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
    client = _client(service)

    response = client.post(
        f"/v1/service/cache-target-event-dead-letters/{EVENT_ID}/replays",
        headers=_service_headers(
            token=RECOVERY_TOKEN,
            extra={"If-Match": f'"{EVENT_ID}:2"'},
        ),
        json={"reason": "manual replay"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CACHE_TARGET_EXTERNAL_SYSTEM_FORBIDDEN"
    assert service.replay_calls == []
