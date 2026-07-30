"""T-VN-12 공통 domain command claim/replay service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from kortravelmap.infra.domain_command_repo import (
    DomainCommandClaim,
    DomainCommandRecord,
    canonical_domain_command_fingerprint,
)
from pydantic import BaseModel

from kortravelmap.api import domain_command_service as service

_KEY = UUID("95000000-0000-4000-8000-000000000001")
_ACTOR = "admin:alice"
_OPERATION = "admin.feature.create"
_PAYLOAD = {"path": {}, "body": {"name": "서울"}}
_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _claim(*, fingerprint: str | None = None) -> DomainCommandClaim:
    return DomainCommandClaim(
        actor=_ACTOR,
        operation=_OPERATION,
        idempotency_key=str(_KEY),
        fingerprint_version=1,
        request_fingerprint=fingerprint
        or canonical_domain_command_fingerprint(_PAYLOAD),
        created_at=_NOW,
    )


def _record() -> DomainCommandRecord:
    return DomainCommandRecord(
        actor=_ACTOR,
        operation=_OPERATION,
        idempotency_key=str(_KEY),
        fingerprint_version=1,
        request_fingerprint=canonical_domain_command_fingerprint(_PAYLOAD),
        response_status=201,
        response_body={"data": {"feature_id": "feature-1"}},
        claimed_at=_NOW,
        completed_at=_NOW,
    )


@pytest.mark.asyncio
async def test_begin_creates_new_actor_scoped_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = AsyncMock()
    get_claim = AsyncMock(return_value=None)
    create_claim = AsyncMock(return_value=_claim())
    monkeypatch.setattr(service, "lock_domain_command", lock)
    monkeypatch.setattr(service, "get_domain_command_claim", get_claim)
    monkeypatch.setattr(service, "create_domain_command_claim", create_claim)

    handle = await service.begin_domain_command(
        AsyncMock(),
        actor=_ACTOR,
        operation=_OPERATION,
        idempotency_key=_KEY,
        payload=_PAYLOAD,
    )

    assert handle.actor == _ACTOR
    assert handle.idempotency_key == str(_KEY)
    assert handle.request_fingerprint == canonical_domain_command_fingerprint(_PAYLOAD)
    lock.assert_awaited_once()
    create_claim.assert_awaited_once()


@pytest.mark.asyncio
async def test_begin_replays_same_fingerprint_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    monkeypatch.setattr(service, "lock_domain_command", AsyncMock())
    monkeypatch.setattr(
        service,
        "get_domain_command_claim",
        AsyncMock(return_value=_claim()),
    )
    monkeypatch.setattr(
        service,
        "get_domain_command_record",
        AsyncMock(return_value=record),
    )

    with pytest.raises(service.DomainCommandReplay) as raised:
        await service.begin_domain_command(
            AsyncMock(),
            actor=_ACTOR,
            operation=_OPERATION,
            idempotency_key=_KEY,
            payload=_PAYLOAD,
        )

    assert raised.value.record is record


@pytest.mark.asyncio
async def test_begin_rejects_different_payload_before_result_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_record = AsyncMock()
    monkeypatch.setattr(service, "lock_domain_command", AsyncMock())
    monkeypatch.setattr(
        service,
        "get_domain_command_claim",
        AsyncMock(return_value=_claim(fingerprint="f" * 64)),
    )
    monkeypatch.setattr(service, "get_domain_command_record", get_record)

    with pytest.raises(service.DomainCommandFingerprintConflict):
        await service.begin_domain_command(
            AsyncMock(),
            actor=_ACTOR,
            operation=_OPERATION,
            idempotency_key=_KEY,
            payload=_PAYLOAD,
        )

    get_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_begin_does_not_rerun_claim_without_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "lock_domain_command", AsyncMock())
    monkeypatch.setattr(
        service,
        "get_domain_command_claim",
        AsyncMock(return_value=_claim()),
    )
    monkeypatch.setattr(
        service,
        "get_domain_command_record",
        AsyncMock(return_value=None),
    )

    with pytest.raises(service.DomainCommandPending):
        await service.begin_domain_command(
            AsyncMock(),
            actor=_ACTOR,
            operation=_OPERATION,
            idempotency_key=_KEY,
            payload=_PAYLOAD,
        )


class _Response(BaseModel):
    data: dict[str, Any]


@pytest.mark.asyncio
async def test_complete_serializes_typed_response_as_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_record = AsyncMock()
    monkeypatch.setattr(service, "create_domain_command_record", create_record)
    command = service.DomainCommandHandle(
        actor=_ACTOR,
        operation=_OPERATION,
        idempotency_key=str(_KEY),
        request_fingerprint="a" * 64,
    )
    session = AsyncMock()

    await service.complete_domain_command(
        session,
        command=command,
        response=_Response(data={"created_at": _NOW}),
        status_code=201,
    )

    create_record.assert_awaited_once_with(
        session,
        actor=_ACTOR,
        operation=_OPERATION,
        idempotency_key=str(_KEY),
        response_status=201,
        response_body={"data": {"created_at": "2026-07-31T00:00:00Z"}},
    )


@pytest.mark.asyncio
async def test_begin_rejects_operation_not_in_static_registry() -> None:
    with pytest.raises(ValueError, match="not registered"):
        await service.begin_domain_command(
            AsyncMock(),
            actor=_ACTOR,
            operation="admin.future-command",
            idempotency_key=_KEY,
            payload=_PAYLOAD,
        )
