"""Actor-scoped domain command claim/replay application service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

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

from kortravelmap.api.domain_command_registry import (
    COMMAND_REGISTRY,
    CommandPolicyKind,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DomainCommandFingerprintConflict",
    "DomainCommandHandle",
    "DomainCommandPending",
    "DomainCommandReplay",
    "begin_domain_command",
    "complete_domain_command",
]

_DOMAIN_OPERATIONS = frozenset(
    policy.operation
    for policy in COMMAND_REGISTRY.values()
    if policy.kind is CommandPolicyKind.DOMAIN_LEDGER
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

    actor: str
    operation: str
    idempotency_key: str
    request_fingerprint: str


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
            actor=actor,
            operation=operation,
            idempotency_key=normalized_key,
        )
        if record is not None:
            raise DomainCommandReplay(record)
        raise DomainCommandPending(claim)
    await create_domain_command_claim(
        session,
        actor=actor,
        operation=operation,
        idempotency_key=normalized_key,
        request_fingerprint=request_fingerprint,
    )
    return DomainCommandHandle(
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
) -> None:
    """현재 transaction에 immutable terminal response를 추가한다."""

    await create_domain_command_record(
        session,
        actor=command.actor,
        operation=command.operation,
        idempotency_key=command.idempotency_key,
        response_status=status_code,
        response_body=_response_body(response),
    )
