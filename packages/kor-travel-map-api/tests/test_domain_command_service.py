"""T-VN-12 공통 domain command claim/replay service."""

from __future__ import annotations

from datetime import UTC, datetime
from inspect import signature
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException, Request, Response
from kortravelmap.infra.domain_command_repo import (
    DomainCommandClaim,
    DomainCommandRecord,
    canonical_domain_command_fingerprint,
)
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from starlette.datastructures import UploadFile

from kortravelmap.api import domain_command_service as service
from kortravelmap.api.auth import AdminProxyContext

_KEY = UUID("95000000-0000-4000-8000-000000000001")
_ACTOR = "admin:alice"
_OPERATION = "admin.feature.create.manual-v1"
_PAYLOAD = {"path": {}, "body": {"name": "서울"}}
_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _claim(*, fingerprint: str | None = None) -> DomainCommandClaim:
    return DomainCommandClaim(
        command_id=1,
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
        command_id=1,
        actor=_ACTOR,
        operation=_OPERATION,
        idempotency_key=str(_KEY),
        fingerprint_version=1,
        request_fingerprint=canonical_domain_command_fingerprint(_PAYLOAD),
        response_status=201,
        response_body={"data": {"feature_id": "feature-1"}},
        response_headers={
            "ETag": '"revision-1"',
            "Location": "/v1/admin/features/feature-1",
        },
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
    assert handle.command_id == 1
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


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Session:
    def __init__(self) -> None:
        self.begin_count = 0

    def begin(self) -> _Tx:
        self.begin_count += 1
        return _Tx()

    def in_transaction(self) -> bool:
        return False


class _SqlStateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _SerializableSession(_Session):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def execute(self, statement: object) -> None:
        self.events.append(f"sql:{statement}")


def _request(*, headers: dict[str, str] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/admin/features",
            "headers": [
                (name.lower().encode("ascii"), value.encode("ascii"))
                for name, value in (headers or {}).items()
            ],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1),
            "scheme": "http",
            "app": type("_App", (), {"state": type("_State", (), {})()})(),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["admin.feature.patch", "admin.feature.delete"],
)
async def test_same_key_and_body_with_different_if_match_conflicts(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_fingerprint: str | None = None
    command = service.DomainCommandHandle(
        command_id=1,
        actor=_ACTOR,
        operation=operation,
        idempotency_key=str(_KEY),
        request_fingerprint="a" * 64,
    )

    async def _begin(
        _session: object,
        *,
        actor: str,
        operation: str,
        idempotency_key: UUID,
        payload: object,
    ) -> service.DomainCommandHandle:
        nonlocal first_fingerprint
        fingerprint = canonical_domain_command_fingerprint(payload)
        if first_fingerprint is None:
            first_fingerprint = fingerprint
            return command
        if fingerprint != first_fingerprint:
            raise service.DomainCommandFingerprintConflict(
                _claim(fingerprint=first_fingerprint)
            )
        return command

    monkeypatch.setattr(service, "begin_domain_command", _begin)
    monkeypatch.setattr(service, "complete_domain_command", AsyncMock())

    @service.idempotent_domain_command(operation)
    async def _route(
        body: _Response,
        context: AdminProxyContext,
        session: _Session,
        request: Request,
    ) -> _Response:
        return body

    body = _Response(data={"name": "같은 본문"})
    first = await _route(
        body=body,
        context=AdminProxyContext(actor=_ACTOR),
        session=_Session(),
        request=_request(headers={"If-Match": '"7"'}),
        __domain_idempotency_key=_KEY,
    )

    assert first is body
    with pytest.raises(service.DomainCommandFingerprintConflict):
        await _route(
            body=body,
            context=AdminProxyContext(actor=_ACTOR),
            session=_Session(),
            request=_request(headers={"If-Match": '"8"'}),
            __domain_idempotency_key=_KEY,
        )


@pytest.mark.asyncio
async def test_manual_create_decorator_sets_isolation_before_claim_and_wraps_201_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _OPERATION
    events: list[str] = []
    command = service.DomainCommandHandle(
        command_id=1,
        actor=_ACTOR,
        operation=operation,
        idempotency_key=str(_KEY),
        request_fingerprint="a" * 64,
    )
    async def begin(*_args: object, **_kwargs: object) -> service.DomainCommandHandle:
        events.append("claim")
        return command

    async def complete(*_args: object, **_kwargs: object) -> None:
        events.append("terminal")

    monkeypatch.setattr(service, "begin_domain_command", begin)
    complete_mock = AsyncMock(side_effect=complete)
    monkeypatch.setattr(service, "complete_domain_command", complete_mock)

    @service.idempotent_domain_command(operation)
    async def _route(
        body: _Response,
        context: AdminProxyContext,
        session: _Session,
        request: Request,
        response: Response,
    ) -> _Response:
        events.append("mutation")
        response.headers["ETag"] = '"revision-7"'
        response.headers["Location"] = "/v1/admin/features/feature-1"
        return body

    exposed = signature(_route)
    header = exposed.parameters["__domain_idempotency_key"]
    assert header.annotation is UUID
    assert header.default.alias == "Idempotency-Key"
    session = _SerializableSession(events)
    response = _Response(data={"feature_id": "feature-1"})
    http_response = Response()

    result = await _route(
        body=response,
        context=AdminProxyContext(actor=_ACTOR),
        session=session,
        request=_request(),
        response=http_response,
        __domain_idempotency_key=_KEY,
    )

    assert result is response
    assert session.begin_count == 1
    assert events == [
        "sql:SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
        "claim",
        "mutation",
        "terminal",
    ]
    complete_mock.assert_awaited_once_with(
        session,
        command=command,
        response=response,
        status_code=201,
        response_headers={
            "ETag": '"revision-7"',
            "Location": "/v1/admin/features/feature-1",
        },
    )


@pytest.mark.asyncio
async def test_read_committed_manual_create_does_not_retry_serialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    command = service.DomainCommandHandle(
        command_id=1,
        actor=_ACTOR,
        operation=_OPERATION,
        idempotency_key=str(_KEY),
        request_fingerprint="a" * 64,
    )

    async def begin(*_args: object, **_kwargs: object) -> service.DomainCommandHandle:
        events.append("claim")
        return command

    monkeypatch.setattr(service, "begin_domain_command", begin)
    complete = AsyncMock()
    monkeypatch.setattr(service, "complete_domain_command", complete)

    @service.idempotent_domain_command(_OPERATION)
    async def _route(
        context: AdminProxyContext,
        session: _SerializableSession,
        request: Request,
    ) -> _Response:
        events.append("mutation")
        raise DBAPIError(None, None, _SqlStateError("40001"), False)

    session = _SerializableSession(events)
    with pytest.raises(DBAPIError):
        await _route(
            context=AdminProxyContext(actor=_ACTOR),
            session=session,
            request=_request(),
            __domain_idempotency_key=_KEY,
        )

    assert session.begin_count == 1
    assert events == [
        "sql:SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
        "claim",
        "mutation",
    ]
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_decorator_uses_operation_success_status_without_response_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = "admin.curation-collection.create"
    command = service.DomainCommandHandle(
        command_id=1,
        actor=_ACTOR,
        operation=operation,
        idempotency_key=str(_KEY),
        request_fingerprint="a" * 64,
    )
    monkeypatch.setattr(
        service,
        "begin_domain_command",
        AsyncMock(return_value=command),
    )
    complete = AsyncMock()
    monkeypatch.setattr(service, "complete_domain_command", complete)

    @service.idempotent_domain_command(operation)
    async def _route(
        context: AdminProxyContext,
        session: _Session,
        request: Request,
    ) -> _Response:
        return _Response(data={"collection_id": "collection-1"})

    session = _SerializableSession([])
    result = await _route(
        context=AdminProxyContext(actor=_ACTOR),
        session=session,
        request=_request(),
        __domain_idempotency_key=_KEY,
    )

    complete.assert_awaited_once_with(
        session,
        command=command,
        response=result,
        status_code=201,
        response_headers={},
    )


@pytest.mark.asyncio
async def test_serializable_multipart_fingerprint_streams_and_rewinds_each_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = "admin.curation-import.preview"
    events: list[str] = []
    payloads: list[object] = []
    reads: list[bytes] = []
    command = service.DomainCommandHandle(
        command_id=1,
        actor=_ACTOR,
        operation=operation,
        idempotency_key=str(_KEY),
        request_fingerprint="a" * 64,
    )

    async def begin(
        *_args: object, payload: object, **_kwargs: object
    ) -> service.DomainCommandHandle:
        payloads.append(payload)
        return command

    monkeypatch.setattr(service, "begin_domain_command", begin)
    monkeypatch.setattr(service, "complete_domain_command", AsyncMock())

    @service.idempotent_domain_command(operation)
    async def _route(
        file: UploadFile,
        provenance_file: UploadFile | None,
        context: AdminProxyContext,
        session: _SerializableSession,
        request: Request,
    ) -> _Response:
        reads.append(await file.read())
        if len(reads) == 1:
            raise DBAPIError(None, None, _SqlStateError("40001"), False)
        return _Response(data={"import_plan_id": "plan-1"})

    content = b"collection_key,theme_slug\ncollection,theme\n"
    result = await _route(
        file=UploadFile(BytesIO(content), filename="curations.csv"),
        provenance_file=None,
        context=AdminProxyContext(actor=_ACTOR),
        session=_SerializableSession(events),
        request=_request(),
        __domain_idempotency_key=_KEY,
    )

    assert result.data == {"import_plan_id": "plan-1"}
    assert reads == [content, content]
    assert payloads == [
        {
            "file": {
                "sha256": "b3bd60f28eb1639d2a58118ba9626bcc43ff4d1f26caae00aaad62cc8186b80f"
            },
            "provenance_file": None,
        },
        {
            "file": {
                "sha256": "b3bd60f28eb1639d2a58118ba9626bcc43ff4d1f26caae00aaad62cc8186b80f"
            },
            "provenance_file": None,
        },
    ]


@pytest.mark.asyncio
async def test_serializable_policy_sets_first_statement_and_retries_whole_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = "admin.curated-source-rule.patch"
    events: list[str] = []
    command = service.DomainCommandHandle(
        command_id=1,
        actor=_ACTOR,
        operation=operation,
        idempotency_key=str(_KEY),
        request_fingerprint="a" * 64,
    )

    async def begin(*_args: object, **_kwargs: object) -> service.DomainCommandHandle:
        events.append("claim")
        return command

    async def complete(*_args: object, **_kwargs: object) -> None:
        events.append("terminal")

    monkeypatch.setattr(service, "begin_domain_command", begin)
    monkeypatch.setattr(service, "complete_domain_command", complete)
    route_attempts = 0

    @service.idempotent_domain_command(operation)
    async def _route(
        context: AdminProxyContext,
        session: _SerializableSession,
        request: Request,
    ) -> _Response:
        nonlocal route_attempts
        route_attempts += 1
        events.append("mutation")
        if route_attempts < 3:
            raise DBAPIError(None, None, _SqlStateError("40001"), False)
        return _Response(data={"rule_id": "rule-1"})

    session = _SerializableSession(events)
    result = await _route(
        context=AdminProxyContext(actor=_ACTOR),
        session=session,
        request=_request(),
        __domain_idempotency_key=_KEY,
    )

    assert result.data == {"rule_id": "rule-1"}
    assert session.begin_count == 3
    assert route_attempts == 3
    assert events == [
        "sql:SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
        "claim",
        "mutation",
        "sql:SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
        "claim",
        "mutation",
        "sql:SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
        "claim",
        "mutation",
        "terminal",
    ]


@pytest.mark.asyncio
async def test_route_error_rolls_back_claim_and_does_not_persist_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = service.DomainCommandHandle(
        command_id=1,
        actor=_ACTOR,
        operation=_OPERATION,
        idempotency_key=str(_KEY),
        request_fingerprint="a" * 64,
    )
    begin = AsyncMock(return_value=command)
    complete = AsyncMock()
    monkeypatch.setattr(service, "begin_domain_command", begin)
    monkeypatch.setattr(service, "complete_domain_command", complete)

    @service.idempotent_domain_command(_OPERATION)
    async def _route(
        context: AdminProxyContext,
        session: _Session,
        request: Request,
    ) -> _Response:
        raise HTTPException(status_code=503, detail="temporary provider failure")

    session = _SerializableSession([])
    with pytest.raises(HTTPException) as raised:
        await _route(
            context=AdminProxyContext(actor=_ACTOR),
            session=session,
            request=_request(),
            __domain_idempotency_key=_KEY,
        )

    assert raised.value.status_code == 503
    assert session.begin_count == 1
    begin.assert_awaited_once()
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_serializes_typed_response_as_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_record = AsyncMock()
    monkeypatch.setattr(service, "create_domain_command_record", create_record)
    command = service.DomainCommandHandle(
        command_id=1,
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
        command_id=1,
        response_status=201,
        response_body={"data": {"created_at": "2026-07-31T00:00:00Z"}},
        response_headers={},
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
