"""Actor-scoped domain command claim/replay application service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from inspect import Parameter, Signature, signature
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from fastapi import Depends, Header, Request, Response
from fastapi.encoders import jsonable_encoder
from kortravelmap.infra.domain_command_repo import (
    DomainCommandClaim,
    DomainCommandRecord,
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
    create_domain_command_record,
    get_domain_command_claim,
    get_domain_command_record,
    lock_domain_command,
)
from pydantic import BaseModel

from kortravelmap.api.auth import (
    AdminProxyContext,
    require_admin_frontend,
)
from kortravelmap.api.domain_command_registry import (
    COMMAND_REGISTRY,
    CommandPolicyKind,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DomainCommandFingerprintConflict",
    "DomainCommandHandle",
    "DomainCommandPending",
    "DomainCommandReplay",
    "begin_domain_command",
    "commit_domain_command_transaction",
    "complete_domain_command",
    "current_domain_command",
    "domain_command_transaction",
    "idempotent_domain_command",
]

_DOMAIN_POLICIES = {
    cast(str, policy.operation): policy
    for policy in COMMAND_REGISTRY.values()
    if policy.kind is CommandPolicyKind.DOMAIN_LEDGER
}
_DOMAIN_OPERATIONS = frozenset(_DOMAIN_POLICIES)
_RouteResult = TypeVar("_RouteResult", bound=BaseModel)
_ACTIVE_DOMAIN_SESSION: ContextVar[AsyncSession | None] = ContextVar(
    "kor_travel_map_domain_command_session",
    default=None,
)
_ACTIVE_DOMAIN_COMMAND: ContextVar[DomainCommandHandle | None] = ContextVar(
    "kor_travel_map_active_domain_command",
    default=None,
)
class DomainCommandError(Exception):
    """Domain command claim/replay base error."""


class DomainCommandFingerprintConflict(DomainCommandError):
    """같은 actor/key/operation을 다른 canonical payload에 재사용했다."""

    def __init__(self, claim: DomainCommandClaim) -> None:
        super().__init__("같은 Idempotency-Key를 다른 command payload에 재사용할 수 없습니다.")
        self.claim = claim


class DomainCommandPending(DomainCommandError):
    """Durable claim은 있으나 terminal 결과가 아직 없다."""

    def __init__(self, claim: DomainCommandClaim) -> None:
        super().__init__("command가 이미 시작됐지만 terminal 결과가 아직 확정되지 않았습니다.")
        self.claim = claim


class DomainCommandReplay(DomainCommandError):
    """이미 확정된 terminal 결과를 HTTP adapter에서 재생한다."""

    def __init__(self, record: DomainCommandRecord) -> None:
        super().__init__("terminal domain command result replay")
        self.record = record


@dataclass(frozen=True, slots=True)
class DomainCommandHandle:
    """새 command의 immutable claim identity."""

    command_id: int
    actor: str
    operation: str
    idempotency_key: str
    request_fingerprint: str


def current_domain_command() -> DomainCommandHandle:
    """현재 idempotent HTTP command의 immutable identity를 반환한다.

    domain command를 요구하는 DB procedure는 route가 새 claim을 중첩 생성하지 않고
    이 handle의 ``command_id``를 receipt로 사용해야 한다. 직접 Python 호출에는 HTTP
    command 경계가 없으므로 명시적으로 실패시킨다.
    """

    command = _ACTIVE_DOMAIN_COMMAND.get()
    if command is None:
        raise RuntimeError("활성 domain command transaction이 없습니다.")
    return command


def _response_body(response: BaseModel | dict[str, Any]) -> dict[str, Any]:
    body = (
        response.model_dump(mode="json")
        if isinstance(response, BaseModel)
        else response
    )
    if not isinstance(body, dict):
        raise TypeError("domain command response must serialize to a JSON object")
    return body


async def begin_domain_command(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: UUID,
    payload: object,
) -> DomainCommandHandle:
    """현재 transaction에서 claim하고 replay/conflict/pending을 fail-close한다.

    DB-only command는 domain mutation과 claim/result를 같은 transaction에 둔다.
    외부 I/O command는 이 함수가 만든 claim transaction을 먼저 commit한 뒤 side
    effect를 실행하고 별도 transaction에서 :func:`complete_domain_command`를
    호출한다. 따라서 process crash 뒤 claim-only 상태는 자동 재실행하지 않는다.
    """

    if operation not in _DOMAIN_OPERATIONS:
        raise ValueError(f"operation is not registered for domain ledger: {operation}")
    normalized_key = str(idempotency_key)
    request_fingerprint = canonical_domain_command_fingerprint(payload)
    await lock_domain_command(
        session,
        actor=actor,
        operation=operation,
        idempotency_key=normalized_key,
    )
    claim = await get_domain_command_claim(
        session,
        actor=actor,
        operation=operation,
        idempotency_key=normalized_key,
    )
    if claim is not None:
        if claim.request_fingerprint != request_fingerprint:
            raise DomainCommandFingerprintConflict(claim)
        record = await get_domain_command_record(
            session,
            command_id=claim.command_id,
        )
        if record is not None:
            raise DomainCommandReplay(record)
        raise DomainCommandPending(claim)
    claim = await create_domain_command_claim(
        session,
        actor=actor,
        operation=operation,
        idempotency_key=normalized_key,
        request_fingerprint=request_fingerprint,
    )
    return DomainCommandHandle(
        command_id=claim.command_id,
        actor=actor,
        operation=operation,
        idempotency_key=normalized_key,
        request_fingerprint=request_fingerprint,
    )


async def complete_domain_command(
    session: AsyncSession,
    *,
    command: DomainCommandHandle,
    response: BaseModel | dict[str, Any],
    status_code: int = 200,
    response_headers: dict[str, str] | None = None,
) -> None:
    """현재 transaction에 immutable terminal response를 추가한다."""

    await create_domain_command_record(
        session,
        command_id=command.command_id,
        response_status=status_code,
        response_body=_response_body(response),
        response_headers=response_headers or {},
    )


@asynccontextmanager
async def domain_command_transaction(
    session: AsyncSession,
) -> AsyncIterator[None]:
    """Route transaction을 outer domain command transaction에 결합한다."""

    if _ACTIVE_DOMAIN_SESSION.get() is session:
        yield
        return
    async with session.begin():
        yield


async def commit_domain_command_transaction(session: AsyncSession) -> None:
    """직접 Python 호출에서만 commit하고 HTTP command outer transaction은 보존한다."""

    if _ACTIVE_DOMAIN_SESSION.get() is not session:
        await session.commit()


def _material_response_headers(
    response: object,
    *,
    header_names: tuple[str, ...],
) -> dict[str, str]:
    if not isinstance(response, Response):
        return {}
    return {
        name: value
        for name in header_names
        if (value := response.headers.get(name)) is not None
    }


def _route_payload(
    function_signature: Signature,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    *,
    fingerprint_headers: tuple[str, ...],
) -> dict[str, object]:
    bound = function_signature.bind(*args, **kwargs)
    bound.apply_defaults()
    excluded = {"session", "context", "_context", "request", "response", "settings"}
    payload = {
        name: jsonable_encoder(value)
        for name, value in bound.arguments.items()
        if name not in excluded
    }
    if fingerprint_headers:
        request = cast(Request, bound.arguments["request"])
        payload["headers"] = {
            name: value.strip() if (value := request.headers.get(name)) else None
            for name in fingerprint_headers
        }
    return payload


def _domain_route_signature(
    function: Callable[..., Awaitable[BaseModel]],
) -> Signature:
    original = signature(function)
    parameters = list(original.parameters.values())
    names = original.parameters
    if "context" not in names:
        parameters.append(
            Parameter(
                "__domain_context",
                kind=Parameter.KEYWORD_ONLY,
                annotation=AdminProxyContext,
                default=Depends(require_admin_frontend),
            )
        )
    if "request" not in names:
        parameters.append(
            Parameter(
                "__domain_request",
                kind=Parameter.KEYWORD_ONLY,
                annotation=Request,
            )
        )
    parameters.append(
        Parameter(
            "__domain_idempotency_key",
            kind=Parameter.KEYWORD_ONLY,
            annotation=UUID,
            default=Header(
                alias="Idempotency-Key",
                description=(
                    "같은 인증 actor가 동일 command를 재시도할 때 재사용하는 UUID. "
                    "다른 canonical payload 재사용은 409."
                ),
            ),
        )
    )
    return original.replace(parameters=parameters)


def idempotent_domain_command(
    operation: str,
) -> Callable[
    [Callable[..., Awaitable[_RouteResult]]],
    Callable[..., Awaitable[_RouteResult]],
]:
    """Admin DB command의 claim, mutation, terminal result를 한 transaction으로 묶는다."""

    if operation not in _DOMAIN_OPERATIONS:
        raise ValueError(f"operation is not registered for domain ledger: {operation}")
    policy = _DOMAIN_POLICIES[operation]
    success_status = policy.success_status
    assert success_status is not None

    def decorate(
        function: Callable[..., Awaitable[_RouteResult]],
    ) -> Callable[..., Awaitable[_RouteResult]]:
        original_signature = signature(function)
        exposed_signature = _domain_route_signature(
            cast(Callable[..., Awaitable[BaseModel]], function)
        )

        @wraps(function)
        async def wrapped(*args: object, **kwargs: object) -> _RouteResult:
            # 직접 호출 단위 테스트와 내부 Python 호출은 HTTP command 경계가 아니다.
            # FastAPI는 합성 signature의 header 인자를 항상 전달한다.
            if "__domain_idempotency_key" not in kwargs:
                return await function(*args, **kwargs)
            idempotency_key = cast(
                UUID,
                kwargs.pop("__domain_idempotency_key"),
            )
            context = cast(
                AdminProxyContext,
                kwargs.get("context") or kwargs.pop("__domain_context"),
            )
            if "request" not in kwargs:
                kwargs.pop("__domain_request")
            session = cast("AsyncSession", kwargs["session"])
            payload = _route_payload(
                original_signature,
                args,
                kwargs,
                fingerprint_headers=policy.fingerprint_headers,
            )
            async with session.begin():
                token = _ACTIVE_DOMAIN_SESSION.set(session)
                try:
                    command = await begin_domain_command(
                        session,
                        actor=context.actor,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        payload=payload,
                    )
                    command_token = _ACTIVE_DOMAIN_COMMAND.set(command)
                    result = await function(*args, **kwargs)
                    route_response = kwargs.get("response")
                    await complete_domain_command(
                        session,
                        command=command,
                        response=result,
                        status_code=success_status,
                        response_headers=_material_response_headers(
                            route_response,
                            header_names=policy.replay_headers,
                        ),
                    )
                finally:
                    if "command_token" in locals():
                        _ACTIVE_DOMAIN_COMMAND.reset(command_token)
                    _ACTIVE_DOMAIN_SESSION.reset(token)
            return result

        wrapped.__signature__ = exposed_signature  # type: ignore[attr-defined]
        return wrapped

    return decorate
