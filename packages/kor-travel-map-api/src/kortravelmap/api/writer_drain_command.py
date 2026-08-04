"""Private API-image entrypoint for the cache-target writer drain.

``python -m kortravelmap.api.writer_drain_command`` accepts one bounded JSON
object on stdin. 성공 시 stdout에는 Manager가 검증하는 receipt JSON 한 줄만
기록한다. raw Dagster identity, URL, credential, GraphQL error는 어느 경로에도
내보내지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Sequence
from uuid import UUID

import httpx
from kortravelmap.infra.db import make_async_session_factory

from kortravelmap.api import db
from kortravelmap.api.settings import ApiSettings
from kortravelmap.api.writer_drain_service import (
    CONTRACT_VERSION,
    WriterDrainCommandError,
    WriterDrainRequest,
    execute_writer_drain,
)

__all__ = ["main", "parse_request"]

_MAX_STDIN_BYTES = 8_192
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_BEGIN_KEYS = frozenset({"contract_version", "operation", "owner_kind", "owner_id"})
_FOLLOWUP_KEYS = _BEGIN_KEYS | frozenset({"lease_id", "prior_receipt_sha256"})


def _canonical_uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise WriterDrainCommandError("INVALID_COMMAND")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise WriterDrainCommandError("INVALID_COMMAND") from exc
    if str(parsed) != value:
        raise WriterDrainCommandError("INVALID_COMMAND")
    return parsed


def _sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise WriterDrainCommandError("INVALID_COMMAND")
    return value


def parse_request(raw: bytes) -> WriterDrainRequest:
    """strict stdin schema → typed command. unknown key도 fail-close한다."""

    if not raw or len(raw) > _MAX_STDIN_BYTES:
        raise WriterDrainCommandError("INVALID_COMMAND")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WriterDrainCommandError("INVALID_COMMAND") from exc
    if not isinstance(value, dict):
        raise WriterDrainCommandError("INVALID_COMMAND")
    if value.get("contract_version") != CONTRACT_VERSION:
        raise WriterDrainCommandError("INVALID_COMMAND")
    operation = value.get("operation")
    owner_kind = value.get("owner_kind")
    if operation not in {"begin", "attest", "restore"} or owner_kind not in {
        "diagnostic",
        "cutover",
    }:
        raise WriterDrainCommandError("INVALID_COMMAND")
    expected_keys = _BEGIN_KEYS if operation == "begin" else _FOLLOWUP_KEYS
    if set(value) != expected_keys:
        raise WriterDrainCommandError("INVALID_COMMAND")
    owner_id = _canonical_uuid(value.get("owner_id"))
    if operation == "begin":
        return WriterDrainRequest(
            operation="begin",
            owner_kind=owner_kind,
            owner_id=owner_id,
            lease_id=None,
            prior_receipt_sha256=None,
        )
    return WriterDrainRequest(
        operation=operation,
        owner_kind=owner_kind,
        owner_id=owner_id,
        lease_id=_canonical_uuid(value.get("lease_id")),
        prior_receipt_sha256=_sha256(value.get("prior_receipt_sha256")),
    )


async def _run(raw: bytes) -> bytes:
    request = parse_request(raw)
    settings = ApiSettings()
    engine = await db.get_engine()
    session_factory = make_async_session_factory(engine)
    async with httpx.AsyncClient(timeout=settings.dagster_request_timeout_seconds) as client:
        receipt = await execute_writer_drain(
            request=request,
            session_factory=session_factory,
            settings=settings,
            http_client=client,
        )
    return receipt.json_bytes()


def main(argv: Sequence[str] | None = None) -> int:
    """stdin 한 건을 실행한다. argv는 미래 확장을 위해 명시적으로 거부한다."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        print("writer-drain: INVALID_COMMAND", file=sys.stderr)
        return 2
    try:
        output = asyncio.run(_run(sys.stdin.buffer.read(_MAX_STDIN_BYTES + 1)))
    except WriterDrainCommandError as exc:
        print(f"writer-drain: {exc.code}", file=sys.stderr)
        return 2
    except Exception:
        # DSN/URL/GraphQL 원문을 exception repr으로 노출하지 않는다.
        print("writer-drain: INTERNAL_ERROR", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(output + b"\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint.
    raise SystemExit(main())
