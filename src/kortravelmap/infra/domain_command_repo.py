"""Actor-scoped domain command terminal replay ledger.

Repository functions never commit.  Callers place the terminal ledger insert and
the domain mutation in the same transaction.  The transaction advisory lock
serializes concurrent retries for one ``(actor, operation, Idempotency-Key)``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from kortravelmap.infra.advisory_lock import advisory_lock_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DomainCommandClaim",
    "DomainCommandRecord",
    "canonical_domain_command_fingerprint",
    "create_domain_command_claim",
    "create_domain_command_record",
    "get_domain_command_claim",
    "get_domain_command_record",
    "lock_domain_command",
]


@dataclass(frozen=True, slots=True)
class DomainCommandClaim:
    """한 actor가 선점한 immutable command identity."""

    command_id: int
    actor: str
    operation: str
    idempotency_key: str
    fingerprint_version: int
    request_fingerprint: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DomainCommandRecord:
    """One append-only terminal command result."""

    command_id: int
    actor: str
    operation: str
    idempotency_key: str
    fingerprint_version: int
    request_fingerprint: str
    response_status: int
    response_body: dict[str, Any]
    response_headers: dict[str, str]
    claimed_at: datetime
    completed_at: datetime


_GET_CLAIM_SQL = """
SELECT command_id, actor, operation, idempotency_key, fingerprint_version,
       request_fingerprint, created_at
FROM ops.domain_commands
WHERE actor = :actor
  AND operation = :operation
  AND idempotency_key = CAST(:idempotency_key AS uuid)
"""

_GET_SQL = """
SELECT command.command_id, command.actor, command.operation,
       command.idempotency_key, command.fingerprint_version,
       command.request_fingerprint,
       result.response_status, result.response_body, result.response_headers,
       command.created_at AS claimed_at, result.completed_at
FROM ops.domain_commands AS command
JOIN ops.domain_command_results AS result
  ON result.command_id = command.command_id
WHERE command.command_id = :command_id
"""

_INSERT_CLAIM_SQL = """
INSERT INTO ops.domain_commands (
    actor, operation, idempotency_key, fingerprint_version,
    request_fingerprint
) VALUES (
    :actor, :operation, CAST(:idempotency_key AS uuid), 1,
    :request_fingerprint
)
RETURNING command_id, actor, operation, idempotency_key, fingerprint_version,
          request_fingerprint, created_at
"""

_INSERT_SQL = """
INSERT INTO ops.domain_command_results (
    command_id, response_status, response_body, response_headers
) VALUES (
    :command_id, :response_status, CAST(:response_body AS jsonb),
    CAST(:response_headers AS jsonb)
)
"""


def canonical_domain_command_fingerprint(payload: object) -> str:
    """Fingerprint one JSON-compatible path/body command payload."""

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def lock_domain_command(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: str,
) -> None:
    """Acquire the transaction lock for one actor-scoped command key."""

    lock_id = advisory_lock_key(
        f"domain-command:{actor}:{operation}:{idempotency_key}"
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:lock_id AS bigint))"),
        {"lock_id": lock_id},
    )


def _claim(row: Any) -> DomainCommandClaim:
    return DomainCommandClaim(
        command_id=int(row.command_id),
        actor=str(row.actor),
        operation=str(row.operation),
        idempotency_key=str(row.idempotency_key),
        fingerprint_version=int(row.fingerprint_version),
        request_fingerprint=str(row.request_fingerprint),
        created_at=row.created_at,
    )


def _record(row: Any) -> DomainCommandRecord:
    return DomainCommandRecord(
        command_id=int(row.command_id),
        actor=str(row.actor),
        operation=str(row.operation),
        idempotency_key=str(row.idempotency_key),
        fingerprint_version=int(row.fingerprint_version),
        request_fingerprint=str(row.request_fingerprint),
        response_status=int(row.response_status),
        response_body=dict(row.response_body),
        response_headers={
            str(key): str(value)
            for key, value in dict(row.response_headers).items()
        },
        claimed_at=row.claimed_at,
        completed_at=row.completed_at,
    )


async def get_domain_command_claim(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: str,
) -> DomainCommandClaim | None:
    row = (
        await session.execute(
            text(_GET_CLAIM_SQL),
            {
                "actor": actor,
                "operation": operation,
                "idempotency_key": idempotency_key,
            },
        )
    ).one_or_none()
    return _claim(row) if row is not None else None


async def get_domain_command_record(
    session: AsyncSession,
    *,
    command_id: int,
) -> DomainCommandRecord | None:
    row = (
        await session.execute(
            text(_GET_SQL),
            {"command_id": command_id},
        )
    ).one_or_none()
    return _record(row) if row is not None else None


async def create_domain_command_claim(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: str,
    request_fingerprint: str,
) -> DomainCommandClaim:
    row = (
        await session.execute(
            text(_INSERT_CLAIM_SQL),
            {
                "actor": actor,
                "operation": operation,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
            },
        )
    ).one()
    return _claim(row)


async def create_domain_command_record(
    session: AsyncSession,
    *,
    command_id: int,
    response_status: int,
    response_body: dict[str, Any],
    response_headers: dict[str, str],
) -> None:
    await session.execute(
        text(_INSERT_SQL),
        {
            "command_id": command_id,
            "response_status": response_status,
            "response_body": json.dumps(
                response_body,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "response_headers": json.dumps(
                response_headers,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )
