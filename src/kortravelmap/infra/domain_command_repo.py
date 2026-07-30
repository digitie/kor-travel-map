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
    "DomainCommandRecord",
    "canonical_domain_command_fingerprint",
    "create_domain_command_record",
    "get_domain_command_record",
    "lock_domain_command",
]


@dataclass(frozen=True, slots=True)
class DomainCommandRecord:
    """One append-only terminal command result."""

    actor: str
    operation: str
    idempotency_key: str
    fingerprint_version: int
    request_fingerprint: str
    response_status: int
    response_body: dict[str, Any]
    created_at: datetime


_GET_SQL = """
SELECT actor, operation, idempotency_key, fingerprint_version,
       request_fingerprint, response_status, response_body, created_at
FROM ops.domain_command_ledger
WHERE actor = :actor
  AND operation = :operation
  AND idempotency_key = CAST(:idempotency_key AS uuid)
"""

_INSERT_SQL = """
INSERT INTO ops.domain_command_ledger (
    actor, operation, idempotency_key, fingerprint_version,
    request_fingerprint, response_status, response_body
) VALUES (
    :actor, :operation, CAST(:idempotency_key AS uuid), 1,
    :request_fingerprint, :response_status, CAST(:response_body AS jsonb)
)
RETURNING actor, operation, idempotency_key, fingerprint_version,
          request_fingerprint, response_status, response_body, created_at
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


def _record(row: Any) -> DomainCommandRecord:
    return DomainCommandRecord(
        actor=str(row.actor),
        operation=str(row.operation),
        idempotency_key=str(row.idempotency_key),
        fingerprint_version=int(row.fingerprint_version),
        request_fingerprint=str(row.request_fingerprint),
        response_status=int(row.response_status),
        response_body=dict(row.response_body),
        created_at=row.created_at,
    )


async def get_domain_command_record(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: str,
) -> DomainCommandRecord | None:
    row = (
        await session.execute(
            text(_GET_SQL),
            {
                "actor": actor,
                "operation": operation,
                "idempotency_key": idempotency_key,
            },
        )
    ).one_or_none()
    return _record(row) if row is not None else None


async def create_domain_command_record(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: str,
    request_fingerprint: str,
    response_status: int,
    response_body: dict[str, Any],
) -> DomainCommandRecord:
    row = (
        await session.execute(
            text(_INSERT_SQL),
            {
                "actor": actor,
                "operation": operation,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "response_status": response_status,
                "response_body": json.dumps(
                    response_body,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        )
    ).one()
    return _record(row)
