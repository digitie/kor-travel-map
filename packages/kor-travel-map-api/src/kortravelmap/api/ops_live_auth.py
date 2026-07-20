"""ops live WebSocket의 짧은 수명 signed subprotocol ticket 검증."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from fastapi import WebSocket
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "OPS_LIVE_AUTH_CLOSE_CODE",
    "OPS_LIVE_EXPIRED_CLOSE_CODE",
    "OPS_LIVE_PROTOCOL_PREFIX",
    "OpsLiveTicketContext",
    "authenticate_ops_live_websocket",
    "claim_ops_live_ticket",
    "select_ops_live_subprotocol",
    "verify_ops_live_subprotocol",
]

OPS_LIVE_PROTOCOL_PREFIX: Final[str] = "ktm.ops-live.v1."
OPS_LIVE_AUTH_CLOSE_CODE: Final[int] = 4401
OPS_LIVE_EXPIRED_CLOSE_CODE: Final[int] = 4408

_AUDIENCE: Final[str] = "kor-travel-map-admin-ops-live"
_VERSION: Final[int] = 1
_TICKET_TTL_SECONDS: Final[int] = 60
_CLOCK_SKEW_SECONDS: Final[int] = 5
_SECRET_MIN_LENGTH: Final[int] = 32
_MAX_PROTOCOL_LENGTH: Final[int] = 2_048
_ACTOR_MAX_LENGTH: Final[int] = 80
_NONCE_MAX_LENGTH: Final[int] = 128
_CLAIM_RETENTION_GRACE_SECONDS: Final[int] = 60
_BASE64URL_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]+$")
_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset({"aud", "exp", "iat", "nonce", "sub", "v"})
_CLAIM_SQL: Final[str] = """
WITH expired AS (
  SELECT nonce_hash
  FROM ops.ops_live_ticket_claims
  WHERE expires_at <= (
    now() - CAST(:retention_grace_seconds AS integer) * interval '1 second'
  )
  ORDER BY expires_at
  LIMIT 1000
  FOR UPDATE SKIP LOCKED
), deleted AS (
  DELETE FROM ops.ops_live_ticket_claims AS claim
  USING expired
  WHERE claim.nonce_hash = expired.nonce_hash
), inserted AS (
  INSERT INTO ops.ops_live_ticket_claims (nonce_hash, actor, expires_at)
  VALUES (:nonce_hash, :actor, :expires_at)
  ON CONFLICT (nonce_hash) DO NOTHING
  RETURNING nonce_hash
)
SELECT EXISTS (SELECT 1 FROM inserted) AS claimed
"""


@dataclass(frozen=True, slots=True)
class OpsLiveTicketContext:
    """검증된 live 연결 actor와 lease."""

    actor: str
    expires_at: datetime
    nonce: str
    subprotocol: str


async def authenticate_ops_live_websocket(
    websocket: WebSocket,
) -> OpsLiveTicketContext | None:
    """signed ticket을 검증한다. 실패 연결의 observable close는 router가 담당한다."""

    settings = websocket.app.state.settings
    configured_secret = settings.admin_proxy_secret
    secret = configured_secret.get_secret_value().strip() if configured_secret is not None else ""
    return verify_ops_live_subprotocol(
        websocket.headers.get("sec-websocket-protocol"),
        secret=secret,
        allow_expired=True,
    )


async def claim_ops_live_ticket(
    session: AsyncSession,
    context: OpsLiveTicketContext,
) -> bool:
    """nonce hash PK insert로 ticket을 한 번만 원자적으로 소비한다.

    claim은 감사 event와 분리한 수명 저장소에 두고, 각 insert에서 만료 후 60초 grace가
    지난 row를 최대 1,000건 정리한다. 원 nonce는 저장하지 않는다.
    실패 rollback timeout은 연결 lease를 소유한 router의 bounded 정리 경계가 담당한다.
    """

    nonce_hash = hashlib.sha256(context.nonce.encode("ascii")).digest()
    result = await session.execute(
        text(_CLAIM_SQL),
        {
            "actor": context.actor,
            "expires_at": context.expires_at,
            "nonce_hash": nonce_hash,
            "retention_grace_seconds": _CLAIM_RETENTION_GRACE_SECONDS,
        },
    )
    claimed = bool(result.scalar_one())
    await session.commit()
    return claimed


def verify_ops_live_subprotocol(
    requested_protocols: str | None,
    *,
    secret: str,
    now: datetime | None = None,
    allow_expired: bool = False,
) -> OpsLiveTicketContext | None:
    """요청된 subprotocol 하나에서 live ticket을 상수시간 검증한다.

    WebSocket dependency만 ``allow_expired=True``를 사용한다. 서명·payload 계약이 모두
    유효한 만료 ticket의 protocol을 보존해 router가 browser-observable 4408로 닫기 위함이다.
    """

    if len(secret) < _SECRET_MIN_LENGTH:
        return None
    protocol = select_ops_live_subprotocol(requested_protocols)
    if protocol is None:
        return None
    ticket = protocol.removeprefix(OPS_LIVE_PROTOCOL_PREFIX)
    payload_part, signature_part = ticket.split(".")
    expected_signature = _base64url_encode(
        hmac.new(
            secret.encode(),
            payload_part.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(signature_part, expected_signature):
        return None
    payload = _decode_payload(payload_part)
    if payload is None or frozenset(payload) != _PAYLOAD_KEYS:
        return None

    actor = payload.get("sub")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    nonce = payload.get("nonce")
    version = payload.get("v")
    if payload.get("aud") != _AUDIENCE or version != _VERSION or isinstance(version, bool):
        return None
    if (
        not isinstance(actor, str)
        or not actor.strip()
        or len(actor) > _ACTOR_MAX_LENGTH
        or not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
        or not isinstance(nonce, str)
        or len(nonce) > _NONCE_MAX_LENGTH
        or not _is_base64url(nonce)
    ):
        return None
    current_time = now or datetime.now(tz=UTC)
    now_seconds = int(current_time.timestamp())
    if issued_at > now_seconds + _CLOCK_SKEW_SECONDS:
        return None
    if expires_at <= now_seconds and not allow_expired:
        return None
    if expires_at - issued_at != _TICKET_TTL_SECONDS:
        return None
    try:
        ticket_expires_at = datetime.fromtimestamp(expires_at, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return OpsLiveTicketContext(
        actor=actor.strip(),
        expires_at=min(
            ticket_expires_at,
            current_time + timedelta(seconds=_TICKET_TTL_SECONDS),
        ),
        nonce=nonce,
        subprotocol=protocol,
    )


def select_ops_live_subprotocol(requested_protocols: str | None) -> str | None:
    """브라우저 인증 거절 handshake에 되돌릴 단일 ticket candidate를 고른다.

    이 함수는 ticket을 인증하지 않는다. 응답 헤더에 안전하게 사용할 수 있는 형식의
    candidate 하나만 고르고, 서명·payload·만료·nonce 검증은 verifier와 router가
    계속 담당한다.
    """

    if not requested_protocols:
        return None
    protocols = [part.strip() for part in requested_protocols.split(",") if part.strip()]
    matching = [protocol for protocol in protocols if protocol.startswith(OPS_LIVE_PROTOCOL_PREFIX)]
    if len(matching) != 1:
        return None
    protocol = matching[0]
    if len(protocol) > _MAX_PROTOCOL_LENGTH:
        return None
    ticket = protocol.removeprefix(OPS_LIVE_PROTOCOL_PREFIX)
    try:
        payload_part, signature_part = ticket.split(".")
    except ValueError:
        return None
    if not _is_base64url(payload_part) or not _is_base64url(signature_part):
        return None
    return protocol


def _decode_payload(payload_part: str) -> dict[str, Any] | None:
    try:
        decoded = _base64url_decode(payload_part).decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, binascii.Error):
        return None
    return payload if isinstance(payload, dict) else None


def _is_base64url(value: str) -> bool:
    return bool(value) and _BASE64URL_RE.fullmatch(value) is not None


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )
