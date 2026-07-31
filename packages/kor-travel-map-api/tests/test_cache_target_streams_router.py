"""ADR-081 cache-target service/admin API entry point contract tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import CACHE_TARGET_CONSUMER_HEADER, SERVICE_TOKEN_HEADER
from kortravelmap.api.cache_target_stream_service import get_cache_target_stream_service
from kortravelmap.api.db import get_session
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
            invalidated_claim_count=0,
        )
        self.dead_letter: Any | None = None
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
    ) -> Any:
        assert external_system == EXTERNAL_SYSTEM
        return self.stream

    async def advance_cache_target_restore_fence(
        self,
        _session: Any,
        **kwargs: Any,
    ) -> Any:
        self.restore_calls.append(kwargs)
        return self.restore_result

    async def get_cache_target_dead_letter(
        self,
        _session: Any,
        *,
        event_id: str,
    ) -> Any | None:
        assert event_id == EVENT_ID
        return self.dead_letter

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
) -> ApiSettings:
    return ApiSettings(
        _env_file=None,
        admin_proxy_secret=None,
        ops_cancel_token=None,
        ops_read_token=None,
        public_api_key_required=False,
        service_token=None,
        vworld_api_key=None,
        cache_target_service_principals=[
            {
                "principal_id": "svc:pinvi",
                "consumer_id": CONSUMER_ID,
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
    assert response.json()["data"]["state"] == "fenced"
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
def test_service_dead_letter_replay_checks_event_system_allowlist() -> None:
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
