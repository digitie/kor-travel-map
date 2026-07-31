"""Cache target result outbox의 claim/ACK/NACK/dead-letter 전달 상태."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import text

from kortravelmap.infra.cache_target_stream_repo import (
    CacheTargetStreamConflict,
    lock_cache_target_stream,
)
from kortravelmap.infra.domain_command_repo import canonical_domain_command_fingerprint

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CacheTargetAppliedReceipt",
    "CacheTargetClaimAckResult",
    "CacheTargetDeadLetter",
    "CacheTargetDeliveryResult",
    "CacheTargetEventClaim",
    "CacheTargetOutboxEvent",
    "CacheTargetDeadLetterPage",
    "ack_cache_target_events",
    "cache_target_dead_letter_entity_tag",
    "cache_target_event_cursor",
    "claim_cache_target_events",
    "get_cache_target_dead_letter",
    "list_cache_target_dead_letters",
    "nack_cache_target_event",
    "parse_cache_target_event_cursor",
    "replay_cache_target_dead_letter",
]

_MAX_CLAIM_LIMIT = 500
_MAX_LEASE_SECONDS = 300
_LOWERCASE_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class CacheTargetOutboxEvent:
    event_id: str
    event_type: str
    event_scope: Literal["target", "stream"]
    external_system: str
    target_key: str | None
    target_id: str | None
    restore_epoch: int
    source_generation: int | None
    target_sequence: int | None
    relay_order: int
    cursor: str
    source_payload_fingerprint: str
    payload_fingerprint: str
    payload: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CacheTargetEventClaim:
    claim_id: str
    external_system: str
    consumer_id: str
    lease_token: str
    status: str
    first_relay_order: int
    last_relay_order: int
    acked_through_relay_order: int | None
    lease_expires_at: datetime
    events: tuple[CacheTargetOutboxEvent, ...]
    idempotent_replay: bool = False

    @property
    def acked_through(self) -> str | None:
        """내부 relay order를 외부 opaque cursor로만 노출한다."""

        if self.acked_through_relay_order is None:
            return None
        return cache_target_event_cursor(self.acked_through_relay_order)


@dataclass(frozen=True, slots=True)
class CacheTargetAppliedReceipt:
    event_id: str
    payload_fingerprint: str


@dataclass(frozen=True, slots=True)
class CacheTargetClaimAckResult:
    claim_id: str
    status: Literal["active", "acked"]
    through_relay_order: int
    applied_count: int
    prefix_acked_count: int
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class CacheTargetDeliveryResult:
    event_id: str
    status: Literal["retry", "dead"]
    delivery_version: int
    attempt_count: int
    stream_blocked: bool

    @property
    def entity_tag(self) -> str:
        return cache_target_dead_letter_entity_tag(
            self.event_id,
            self.delivery_version,
        )


@dataclass(frozen=True, slots=True)
class CacheTargetDeadLetter:
    event: CacheTargetOutboxEvent
    delivery_version: int
    attempt_count: int
    error_class: str | None
    error_code: str | None
    error_fingerprint: str | None
    updated_at: datetime

    @property
    def entity_tag(self) -> str:
        return cache_target_dead_letter_entity_tag(
            self.event.event_id,
            self.delivery_version,
        )


@dataclass(frozen=True, slots=True)
class CacheTargetDeadLetterPage:
    items: tuple[CacheTargetDeadLetter, ...]
    next_cursor: str | None


_EXPIRE_CLAIMS_SQL = """
UPDATE ops.poi_cache_target_outbox_claims
SET status = 'expired', completed_at = now()
WHERE external_system = :external_system
  AND status = 'active'
  AND lease_expires_at <= now()
RETURNING claim_id
"""

_RELEASE_CLAIM_DELIVERIES_SQL = """
UPDATE ops.poi_cache_target_outbox_deliveries
SET status = 'retry', claim_id = NULL, lease_token = NULL,
    lease_expires_at = NULL, available_at = now(), updated_at = now()
WHERE status = 'leased'
  AND claim_id = ANY(CAST(:claim_ids AS uuid[]))
"""

_GET_CLAIM_BY_IDEMPOTENCY_SQL = """
SELECT claim_id, external_system, consumer_id, request_fingerprint,
       lease_token, status, first_relay_order, last_relay_order,
       acked_through_relay_order, lease_expires_at
FROM ops.poi_cache_target_outbox_claims
WHERE external_system = :external_system
  AND idempotency_key = CAST(:idempotency_key AS uuid)
"""

_GET_ACTIVE_CLAIM_SQL = """
SELECT claim_id, lease_expires_at
FROM ops.poi_cache_target_outbox_claims
WHERE external_system = :external_system
  AND status = 'active'
"""

_EVENT_COLUMNS = """
event.event_id, event.event_type, event.external_system, event.target_key,
event.event_scope,
event.target_id, event.restore_epoch, event.source_generation,
event.target_sequence, event.relay_order, event.source_payload_fingerprint,
event.payload_fingerprint, event.payload, event.occurred_at
"""

_GET_CLAIM_EVENTS_SQL = f"""
SELECT {_EVENT_COLUMNS}
FROM ops.poi_cache_target_outbox_claim_events AS claimed
JOIN ops.poi_cache_target_outbox_events AS event
  ON event.event_id = claimed.event_id
WHERE claimed.claim_id = CAST(:claim_id AS uuid)
ORDER BY claimed.position
"""

_LOCK_UNDELIVERED_SQL = f"""
SELECT {_EVENT_COLUMNS}, delivery.status AS delivery_status,
       delivery.available_at, delivery.attempt_count,
       delivery.delivery_version
FROM ops.poi_cache_target_outbox_events AS event
JOIN ops.poi_cache_target_outbox_deliveries AS delivery
  ON delivery.event_id = event.event_id
WHERE event.external_system = :external_system
  AND delivery.status <> 'delivered'
ORDER BY event.relay_order
LIMIT :limit
FOR UPDATE OF delivery
"""

_INSERT_CLAIM_SQL = """
INSERT INTO ops.poi_cache_target_outbox_claims (
    claim_id, external_system, consumer_id, idempotency_key,
    request_fingerprint, lease_token, status, first_relay_order,
    last_relay_order, lease_expires_at
) VALUES (
    CAST(:claim_id AS uuid), :external_system, :consumer_id,
    CAST(:idempotency_key AS uuid), :request_fingerprint,
    CAST(:lease_token AS uuid), 'active', :first_relay_order,
    :last_relay_order, now() + make_interval(secs => :lease_seconds)
)
RETURNING lease_expires_at
"""

_LEASE_DELIVERIES_SQL = """
UPDATE ops.poi_cache_target_outbox_deliveries
SET status = 'leased', attempt_count = attempt_count + 1,
    claim_id = CAST(:claim_id AS uuid), lease_token = CAST(:lease_token AS uuid),
    lease_expires_at = CAST(:lease_expires_at AS timestamptz), updated_at = now()
WHERE event_id = ANY(CAST(:event_ids AS uuid[]))
"""

_INSERT_CLAIM_EVENT_SQL = """
INSERT INTO ops.poi_cache_target_outbox_claim_events (
    claim_id, event_id, relay_order, position
) VALUES (
    CAST(:claim_id AS uuid), CAST(:event_id AS uuid), :relay_order, :position
)
"""

_LOCK_CLAIM_SQL = """
SELECT claim_id, external_system, consumer_id, lease_token, status,
       first_relay_order, last_relay_order, acked_through_relay_order,
       lease_expires_at, lease_expires_at > now() AS lease_valid
FROM ops.poi_cache_target_outbox_claims
WHERE claim_id = CAST(:claim_id AS uuid)
FOR UPDATE
"""

_LOCK_ACK_EVENTS_SQL = """
SELECT claimed.event_id, claimed.relay_order, claimed.consumer_applied_at,
       claimed.prefix_acked_at, claimed.ack_payload_fingerprint,
       event.payload_fingerprint, delivery.status AS delivery_status
FROM ops.poi_cache_target_outbox_claim_events AS claimed
JOIN ops.poi_cache_target_outbox_events AS event
  ON event.event_id = claimed.event_id
JOIN ops.poi_cache_target_outbox_deliveries AS delivery
  ON delivery.event_id = claimed.event_id
WHERE claimed.claim_id = CAST(:claim_id AS uuid)
ORDER BY claimed.position
FOR UPDATE OF claimed, delivery
"""

_MARK_APPLIED_SQL = """
UPDATE ops.poi_cache_target_outbox_claim_events
SET consumer_applied_at = COALESCE(consumer_applied_at, now()),
    ack_payload_fingerprint = COALESCE(ack_payload_fingerprint, :fingerprint)
WHERE claim_id = CAST(:claim_id AS uuid)
  AND event_id = CAST(:event_id AS uuid)
"""

_MARK_PREFIX_ACKED_SQL = """
UPDATE ops.poi_cache_target_outbox_claim_events
SET prefix_acked_at = COALESCE(prefix_acked_at, now())
WHERE claim_id = CAST(:claim_id AS uuid)
  AND relay_order <= :through_relay_order
"""

_MARK_PREFIX_DELIVERED_SQL = """
UPDATE ops.poi_cache_target_outbox_deliveries AS delivery
SET status = 'delivered', claim_id = NULL, lease_token = NULL,
    lease_expires_at = NULL, delivered_at = COALESCE(delivered_at, now()),
    updated_at = now()
FROM ops.poi_cache_target_outbox_claim_events AS claimed
WHERE claimed.claim_id = CAST(:claim_id AS uuid)
  AND claimed.relay_order <= :through_relay_order
  AND delivery.event_id = claimed.event_id
"""

_UPDATE_CLAIM_ACK_SQL = """
UPDATE ops.poi_cache_target_outbox_claims
SET acked_through_relay_order = :through_relay_order,
    status = CASE WHEN last_relay_order = :through_relay_order
                  THEN 'acked' ELSE 'active' END,
    completed_at = CASE WHEN last_relay_order = :through_relay_order
                        THEN now() ELSE NULL END
WHERE claim_id = CAST(:claim_id AS uuid)
RETURNING status
"""

_LOCK_NACK_EVENT_SQL = """
SELECT claimed.event_id, delivery.status, delivery.attempt_count,
       delivery.delivery_version,
       NOT EXISTS (
         SELECT 1
         FROM ops.poi_cache_target_outbox_claim_events AS earlier
         WHERE earlier.claim_id = claimed.claim_id
           AND earlier.position < claimed.position
           AND earlier.prefix_acked_at IS NULL
       ) AS is_unacked_head
FROM ops.poi_cache_target_outbox_claim_events AS claimed
JOIN ops.poi_cache_target_outbox_deliveries AS delivery
  ON delivery.event_id = claimed.event_id
WHERE claimed.claim_id = CAST(:claim_id AS uuid)
  AND claimed.event_id = CAST(:event_id AS uuid)
FOR UPDATE OF delivery
"""

_INVALIDATE_CLAIM_SQL = """
UPDATE ops.poi_cache_target_outbox_claims
SET status = 'invalidated', completed_at = now()
WHERE claim_id = CAST(:claim_id AS uuid)
  AND status = 'active'
"""

_NACK_DELIVERY_SQL = """
UPDATE ops.poi_cache_target_outbox_deliveries
SET status = :status, delivery_version = delivery_version + 1,
    claim_id = NULL, lease_token = NULL, lease_expires_at = NULL,
    available_at = CASE WHEN :status = 'retry'
                        THEN now() + make_interval(secs => :backoff_seconds)
                        ELSE available_at END,
    error_class = :error_class, error_code = :error_code,
    error_fingerprint = :error_fingerprint, updated_at = now()
WHERE event_id = CAST(:event_id AS uuid)
RETURNING delivery_version, attempt_count
"""

_BLOCK_STREAM_SQL = """
UPDATE ops.poi_cache_target_streams
SET status = 'blocked', blocked_event_id = CAST(:event_id AS uuid),
    updated_at = now()
WHERE external_system = :external_system
"""

_GET_DEAD_LETTER_SQL = f"""
SELECT {_EVENT_COLUMNS}, delivery.delivery_version, delivery.attempt_count,
       delivery.error_class, delivery.error_code, delivery.error_fingerprint,
       delivery.updated_at
FROM ops.poi_cache_target_outbox_events AS event
JOIN ops.poi_cache_target_outbox_deliveries AS delivery
  ON delivery.event_id = event.event_id
WHERE event.event_id = CAST(:event_id AS uuid)
  AND delivery.status = 'dead'
"""

_LOCK_DEAD_LETTER_SQL = _GET_DEAD_LETTER_SQL + " FOR UPDATE OF delivery"

_LIST_DEAD_LETTERS_SQL = f"""
SELECT {_EVENT_COLUMNS}, delivery.delivery_version, delivery.attempt_count,
       delivery.error_class, delivery.error_code, delivery.error_fingerprint,
       delivery.updated_at
FROM ops.poi_cache_target_outbox_events AS event
JOIN ops.poi_cache_target_outbox_deliveries AS delivery
  ON delivery.event_id = event.event_id
WHERE delivery.status = 'dead'
  AND (
    CAST(:cursor_updated_at AS timestamptz) IS NULL
    OR (delivery.updated_at, event.event_id) <
       (CAST(:cursor_updated_at AS timestamptz), CAST(:cursor_event_id AS uuid))
  )
ORDER BY delivery.updated_at DESC, event.event_id DESC
LIMIT :limit
"""

_REPLAY_DEAD_LETTER_SQL = """
UPDATE ops.poi_cache_target_outbox_deliveries
SET status = 'retry', delivery_version = delivery_version + 1,
    available_at = now(), error_class = NULL, error_code = NULL,
    error_fingerprint = NULL, updated_at = now()
WHERE event_id = CAST(:event_id AS uuid)
RETURNING delivery_version, attempt_count
"""


def _canonical_uuid(value: str, *, field: str) -> str:
    canonical = str(UUID(value))
    if value != canonical:
        raise ValueError(f"{field}는 lowercase canonical UUID여야 합니다.")
    return canonical


def _sha256(value: str, *, field: str) -> str:
    if len(value) != 64 or any(character not in _LOWERCASE_HEX for character in value):
        raise ValueError(f"{field}는 lowercase SHA-256 hex여야 합니다.")
    return value


def cache_target_event_cursor(relay_order: int) -> str:
    """global relay order를 versioned opaque cursor로 직렬화한다."""
    if relay_order < 0:
        raise ValueError("relay_order는 0 이상이어야 합니다.")
    raw = json.dumps(
        {"kind": "cache_target_event", "relay_order": relay_order, "v": 1},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_cache_target_event_cursor(cursor: str) -> int:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("ascii"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("유효하지 않은 cache target event cursor입니다.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "cache_target_event"
        or payload.get("v") != 1
        or not isinstance(payload.get("relay_order"), int)
        or payload["relay_order"] < 0
    ):
        raise ValueError("유효하지 않은 cache target event cursor입니다.")
    if cache_target_event_cursor(payload["relay_order"]) != cursor:
        raise ValueError("event cursor가 canonical encoding이 아닙니다.")
    return int(payload["relay_order"])


def cache_target_dead_letter_entity_tag(event_id: str, delivery_version: int) -> str:
    event_id = _canonical_uuid(event_id, field="event_id")
    if delivery_version <= 0:
        raise ValueError("delivery_version은 양수여야 합니다.")
    return f'"{event_id}:{delivery_version}"'


def _encode_dead_letter_cursor(*, updated_at: datetime, event_id: str) -> str:
    raw = json.dumps(
        {
            "event_id": event_id,
            "kind": "cache_target_dead_letter",
            "updated_at": updated_at.isoformat(),
            "v": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_dead_letter_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("ascii"))
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        event_id = _canonical_uuid(str(payload["event_id"]), field="event_id")
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("유효하지 않은 dead-letter cursor입니다.") from exc
    if (
        payload.get("kind") != "cache_target_dead_letter"
        or payload.get("v") != 1
        or updated_at.tzinfo is None
    ):
        raise ValueError("유효하지 않은 dead-letter cursor입니다.")
    if _encode_dead_letter_cursor(updated_at=updated_at, event_id=event_id) != cursor:
        raise ValueError("dead-letter cursor가 canonical encoding이 아닙니다.")
    return updated_at, event_id


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("outbox payload는 object여야 합니다.")
    return {str(key): item for key, item in value.items()}


def _event(row: Any) -> CacheTargetOutboxEvent:
    values = row._mapping
    relay_order = int(values["relay_order"])
    return CacheTargetOutboxEvent(
        event_id=str(values["event_id"]),
        event_type=str(values["event_type"]),
        event_scope=values["event_scope"],
        external_system=str(values["external_system"]),
        target_key=(str(values["target_key"]) if values["target_key"] is not None else None),
        target_id=(str(values["target_id"]) if values["target_id"] is not None else None),
        restore_epoch=int(values["restore_epoch"]),
        source_generation=(
            int(values["source_generation"])
            if values["source_generation"] is not None
            else None
        ),
        target_sequence=(
            int(values["target_sequence"])
            if values["target_sequence"] is not None
            else None
        ),
        relay_order=relay_order,
        cursor=cache_target_event_cursor(relay_order),
        source_payload_fingerprint=str(values["source_payload_fingerprint"]),
        payload_fingerprint=str(values["payload_fingerprint"]),
        payload=_payload(values["payload"]),
        occurred_at=values["occurred_at"],
    )


async def _claim_from_row(
    session: AsyncSession,
    row: Any,
    *,
    idempotent_replay: bool,
) -> CacheTargetEventClaim:
    values = row._mapping
    events = (
        await session.execute(
            text(_GET_CLAIM_EVENTS_SQL),
            {"claim_id": str(values["claim_id"])},
        )
    ).all()
    return CacheTargetEventClaim(
        claim_id=str(values["claim_id"]),
        external_system=str(values["external_system"]),
        consumer_id=str(values["consumer_id"]),
        lease_token=str(values["lease_token"]),
        status=str(values["status"]),
        first_relay_order=int(values["first_relay_order"]),
        last_relay_order=int(values["last_relay_order"]),
        acked_through_relay_order=(
            int(values["acked_through_relay_order"])
            if values["acked_through_relay_order"] is not None
            else None
        ),
        lease_expires_at=values["lease_expires_at"],
        events=tuple(_event(event) for event in events),
        idempotent_replay=idempotent_replay,
    )


async def claim_cache_target_events(
    session: AsyncSession,
    *,
    external_system: str,
    consumer_id: str,
    idempotency_key: str,
    limit: int = 100,
    lease_seconds: int = 60,
) -> CacheTargetEventClaim | None:
    """external system의 단일 global stream에서 ordered lease를 만든다."""
    idempotency_key = _canonical_uuid(idempotency_key, field="idempotency_key")
    if not 0 < limit <= _MAX_CLAIM_LIMIT:
        raise ValueError(f"limit은 1~{_MAX_CLAIM_LIMIT}이어야 합니다.")
    if not 0 < lease_seconds <= _MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds는 1~{_MAX_LEASE_SECONDS}여야 합니다.")
    fingerprint = canonical_domain_command_fingerprint(
        {
            "version": "cache-target-claim-v1",
            "external_system": external_system,
            "consumer_id": consumer_id,
            "limit": limit,
            "lease_seconds": lease_seconds,
        }
    )
    control = await lock_cache_target_stream(
        session,
        external_system=external_system,
        consumer_id=consumer_id,
    )

    replay = (
        await session.execute(
            text(_GET_CLAIM_BY_IDEMPOTENCY_SQL),
            {"external_system": external_system, "idempotency_key": idempotency_key},
        )
    ).one_or_none()
    if replay is not None:
        if str(replay._mapping["request_fingerprint"]) != fingerprint:
            raise CacheTargetStreamConflict(
                "idempotency_key_reused",
                "claim Idempotency-Key가 다른 request에 사용됐습니다.",
            )
        return await _claim_from_row(session, replay, idempotent_replay=True)

    expired = (
        await session.execute(
            text(_EXPIRE_CLAIMS_SQL),
            {"external_system": external_system},
        )
    ).all()
    expired_ids = [str(row._mapping["claim_id"]) for row in expired]
    if expired_ids:
        await session.execute(
            text(_RELEASE_CLAIM_DELIVERIES_SQL),
            {"claim_ids": expired_ids},
        )
    active = (
        await session.execute(
            text(_GET_ACTIVE_CLAIM_SQL),
            {"external_system": external_system},
        )
    ).one_or_none()
    if active is not None:
        raise CacheTargetStreamConflict(
            "active_claim_exists",
            "external system stream에 아직 active claim이 있습니다.",
            current={"claim_id": str(active._mapping["claim_id"])},
        )
    if not control.consumer_enabled:
        raise CacheTargetStreamConflict(
            "consumer_disabled",
            "cache target stream consumer가 비활성 상태입니다.",
        )
    if control.status == "fenced":
        raise CacheTargetStreamConflict(
            "stream_fenced",
            "cache target stream이 restore/reconciliation fence 상태입니다.",
        )

    rows = (
        await session.execute(
            text(_LOCK_UNDELIVERED_SQL),
            {"external_system": external_system, "limit": limit},
        )
    ).all()
    if not rows:
        return None
    first = rows[0]._mapping
    if control.status == "blocked" and str(first["event_id"]) != control.blocked_event_id:
        raise CacheTargetStreamConflict(
            "blocked_event_not_head",
            "stream blocked event가 undelivered prefix와 일치하지 않습니다.",
        )
    if first["delivery_status"] == "dead":
        raise CacheTargetStreamConflict(
            "stream_blocked",
            "dead-letter event replay 전에는 다음 event를 claim할 수 없습니다.",
            current={"event_id": str(first["event_id"])},
        )

    claimable: list[Any] = []
    for row in rows:
        values = row._mapping
        if values["delivery_status"] not in ("pending", "retry"):
            break
        if values["available_at"] > datetime.now(values["available_at"].tzinfo):
            break
        claimable.append(row)
        if control.status == "blocked":
            break
    if not claimable:
        return None

    claim_id = str(uuid4())
    lease_token = str(uuid4())
    first_order = int(claimable[0]._mapping["relay_order"])
    last_order = int(claimable[-1]._mapping["relay_order"])
    lease_expires_at = (
        await session.execute(
            text(_INSERT_CLAIM_SQL),
            {
                "claim_id": claim_id,
                "external_system": external_system,
                "consumer_id": consumer_id,
                "idempotency_key": idempotency_key,
                "request_fingerprint": fingerprint,
                "lease_token": lease_token,
                "first_relay_order": first_order,
                "last_relay_order": last_order,
                "lease_seconds": lease_seconds,
            },
        )
    ).scalar_one()
    event_ids = [str(row._mapping["event_id"]) for row in claimable]
    await session.execute(
        text(_LEASE_DELIVERIES_SQL),
        {
            "claim_id": claim_id,
            "lease_token": lease_token,
            "lease_expires_at": lease_expires_at,
            "event_ids": event_ids,
        },
    )
    for position, row in enumerate(claimable, start=1):
        await session.execute(
            text(_INSERT_CLAIM_EVENT_SQL),
            {
                "claim_id": claim_id,
                "event_id": str(row._mapping["event_id"]),
                "relay_order": int(row._mapping["relay_order"]),
                "position": position,
            },
        )
    return CacheTargetEventClaim(
        claim_id=claim_id,
        external_system=external_system,
        consumer_id=consumer_id,
        lease_token=lease_token,
        status="active",
        first_relay_order=first_order,
        last_relay_order=last_order,
        acked_through_relay_order=None,
        lease_expires_at=lease_expires_at,
        events=tuple(_event(row) for row in claimable),
    )


async def _validated_claim(
    session: AsyncSession,
    *,
    claim_id: str,
    lease_token: str,
    consumer_id: str,
) -> Any:
    claim_id = _canonical_uuid(claim_id, field="claim_id")
    lease_token = _canonical_uuid(lease_token, field="lease_token")
    row = (await session.execute(text(_LOCK_CLAIM_SQL), {"claim_id": claim_id})).one_or_none()
    if row is None:
        raise CacheTargetStreamConflict("claim_not_found", "claim이 없습니다.")
    values = row._mapping
    if str(values["consumer_id"]) != consumer_id or str(values["lease_token"]) != lease_token:
        raise CacheTargetStreamConflict(
            "claim_binding_mismatch",
            "claim consumer 또는 lease token이 다릅니다.",
        )
    return row


async def ack_cache_target_events(
    session: AsyncSession,
    *,
    consumer_id: str,
    claim_id: str,
    lease_token: str,
    through_cursor: str,
    applied: Sequence[CacheTargetAppliedReceipt],
) -> CacheTargetClaimAckResult:
    """consumer applied receipt를 기록하고 contiguous claim prefix를 ACK한다."""
    through_order = parse_cache_target_event_cursor(through_cursor)
    claim = await _validated_claim(
        session,
        claim_id=claim_id,
        lease_token=lease_token,
        consumer_id=consumer_id,
    )
    claim_values = claim._mapping
    if claim_values["status"] not in ("active", "acked"):
        raise CacheTargetStreamConflict("claim_not_active", "ACK 가능한 claim이 아닙니다.")
    if claim_values["status"] == "active" and not claim_values["lease_valid"]:
        raise CacheTargetStreamConflict("claim_expired", "claim lease가 만료됐습니다.")

    rows = (
        await session.execute(
            text(_LOCK_ACK_EVENTS_SQL),
            {"claim_id": str(claim_values["claim_id"])},
        )
    ).all()
    by_event = {str(row._mapping["event_id"]): row for row in rows}
    by_order = {int(row._mapping["relay_order"]): row for row in rows}
    if through_order not in by_order:
        raise CacheTargetStreamConflict(
            "ack_cursor_not_in_claim",
            "through_cursor가 claim event를 가리키지 않습니다.",
        )
    previous_through = claim_values["acked_through_relay_order"]
    if previous_through is not None and through_order < int(previous_through):
        raise CacheTargetStreamConflict(
            "ack_cursor_regression",
            "through_cursor는 이미 ACK한 prefix보다 뒤로 갈 수 없습니다.",
            current={"acked_through_relay_order": int(previous_through)},
        )
    receipt_ids: set[str] = set()
    for receipt in applied:
        event_id = _canonical_uuid(receipt.event_id, field="applied.event_id")
        fingerprint = _sha256(
            receipt.payload_fingerprint,
            field="applied.payload_fingerprint",
        )
        row = by_event.get(event_id)
        if row is None or str(row._mapping["payload_fingerprint"]) != fingerprint:
            raise CacheTargetStreamConflict(
                "applied_receipt_mismatch",
                "applied receipt event 또는 payload fingerprint가 claim과 다릅니다.",
            )
        if event_id in receipt_ids:
            raise ValueError("applied receipt event_id가 중복됐습니다.")
        receipt_ids.add(event_id)
        stored = row._mapping["ack_payload_fingerprint"]
        if stored is not None and str(stored) != fingerprint:
            raise CacheTargetStreamConflict(
                "applied_receipt_changed",
                "이미 기록된 applied fingerprint를 바꿀 수 없습니다.",
            )
        await session.execute(
            text(_MARK_APPLIED_SQL),
            {"claim_id": claim_id, "event_id": event_id, "fingerprint": fingerprint},
        )

    prefix = [row for row in rows if int(row._mapping["relay_order"]) <= through_order]
    for row in prefix:
        event_id = str(row._mapping["event_id"])
        if row._mapping["consumer_applied_at"] is None and event_id not in receipt_ids:
            raise CacheTargetStreamConflict(
                "ack_prefix_not_applied",
                "through_cursor prefix의 모든 event에 applied receipt가 필요합니다.",
            )

    already_acked = all(row._mapping["prefix_acked_at"] is not None for row in prefix)
    await session.execute(
        text(_MARK_PREFIX_ACKED_SQL),
        {"claim_id": claim_id, "through_relay_order": through_order},
    )
    await session.execute(
        text(_MARK_PREFIX_DELIVERED_SQL),
        {"claim_id": claim_id, "through_relay_order": through_order},
    )
    raw_status = str(
        (
            await session.execute(
                text(_UPDATE_CLAIM_ACK_SQL),
                {"claim_id": claim_id, "through_relay_order": through_order},
            )
        ).scalar_one()
    )
    if raw_status not in ("active", "acked"):
        msg = f"unexpected claim status returned after ACK: {raw_status!r}"
        raise RuntimeError(msg)
    status = cast("Literal['active', 'acked']", raw_status)
    return CacheTargetClaimAckResult(
        claim_id=claim_id,
        status=status,
        through_relay_order=through_order,
        applied_count=len(receipt_ids),
        prefix_acked_count=len(prefix),
        idempotent_replay=already_acked,
    )


async def nack_cache_target_event(
    session: AsyncSession,
    *,
    external_system: str,
    consumer_id: str,
    claim_id: str,
    lease_token: str,
    event_id: str,
    error_class: Literal["transient", "permanent"],
    error_code: str,
    error_fingerprint: str,
    backoff_seconds: int = 30,
    max_attempts: int = 5,
) -> CacheTargetDeliveryResult:
    """claim을 무효화하고 transient retry 또는 permanent dead/block으로 전이한다."""
    if error_class not in ("transient", "permanent"):
        raise ValueError("error_class는 transient 또는 permanent여야 합니다.")
    if not error_code or len(error_code) > 128:
        raise ValueError("error_code는 1~128자여야 합니다.")
    error_fingerprint = _sha256(error_fingerprint, field="error_fingerprint")
    if not 0 <= backoff_seconds <= 3600:
        raise ValueError("backoff_seconds는 0~3600이어야 합니다.")
    if max_attempts <= 0:
        raise ValueError("max_attempts는 양수여야 합니다.")
    event_id = _canonical_uuid(event_id, field="event_id")
    claim = await _validated_claim(
        session,
        claim_id=claim_id,
        lease_token=lease_token,
        consumer_id=consumer_id,
    )
    values = claim._mapping
    if values["status"] != "active" or not values["lease_valid"]:
        raise CacheTargetStreamConflict("claim_not_active", "NACK 가능한 claim이 아닙니다.")
    if str(values["external_system"]) != external_system:
        raise CacheTargetStreamConflict(
            "claim_stream_mismatch",
            "claim external_system이 요청과 다릅니다.",
        )
    delivery = (
        await session.execute(
            text(_LOCK_NACK_EVENT_SQL),
            {"claim_id": claim_id, "event_id": event_id},
        )
    ).one_or_none()
    if delivery is None or delivery._mapping["status"] != "leased":
        raise CacheTargetStreamConflict(
            "event_not_leased",
            "event가 이 claim에 leased 상태가 아닙니다.",
        )
    attempt_count = int(delivery._mapping["attempt_count"])
    next_status: Literal["retry", "dead"] = (
        "dead" if error_class == "permanent" or attempt_count >= max_attempts else "retry"
    )
    if next_status == "dead" and not bool(delivery._mapping["is_unacked_head"]):
        raise CacheTargetStreamConflict(
            "dead_letter_requires_prefix_ack",
            "dead 전이 전 claim의 앞선 event prefix를 먼저 ACK해야 합니다.",
        )
    await session.execute(text(_INVALIDATE_CLAIM_SQL), {"claim_id": claim_id})
    await session.execute(
        text(_RELEASE_CLAIM_DELIVERIES_SQL),
        {"claim_ids": [claim_id]},
    )
    updated = (
        await session.execute(
            text(_NACK_DELIVERY_SQL),
            {
                "event_id": event_id,
                "status": next_status,
                "backoff_seconds": backoff_seconds,
                "error_class": error_class,
                "error_code": error_code,
                "error_fingerprint": error_fingerprint,
            },
        )
    ).one()
    if next_status == "dead":
        await session.execute(
            text(_BLOCK_STREAM_SQL),
            {"external_system": external_system, "event_id": event_id},
        )
    return CacheTargetDeliveryResult(
        event_id=event_id,
        status=next_status,
        delivery_version=int(updated._mapping["delivery_version"]),
        attempt_count=int(updated._mapping["attempt_count"]),
        stream_blocked=next_status == "dead",
    )


def _dead_letter(row: Any) -> CacheTargetDeadLetter:
    values = row._mapping
    return CacheTargetDeadLetter(
        event=_event(row),
        delivery_version=int(values["delivery_version"]),
        attempt_count=int(values["attempt_count"]),
        error_class=values["error_class"],
        error_code=values["error_code"],
        error_fingerprint=values["error_fingerprint"],
        updated_at=values["updated_at"],
    )


async def get_cache_target_dead_letter(
    session: AsyncSession,
    *,
    event_id: str,
) -> CacheTargetDeadLetter | None:
    event_id = _canonical_uuid(event_id, field="event_id")
    row = (await session.execute(text(_GET_DEAD_LETTER_SQL), {"event_id": event_id})).one_or_none()
    return _dead_letter(row) if row is not None else None


async def list_cache_target_dead_letters(
    session: AsyncSession,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> CacheTargetDeadLetterPage:
    """변경 시각 역순 keyset으로 dead-letter를 조회한다."""

    if not 0 < limit <= 500:
        raise ValueError("limit은 1 이상 500 이하여야 합니다.")
    cursor_updated_at, cursor_event_id = _parse_dead_letter_cursor(cursor)
    rows = (
        await session.execute(
            text(_LIST_DEAD_LETTERS_SQL),
            {
                "cursor_updated_at": cursor_updated_at,
                "cursor_event_id": cursor_event_id,
                "limit": limit + 1,
            },
        )
    ).all()
    items = tuple(_dead_letter(row) for row in rows[:limit])
    next_cursor = None
    if len(rows) > limit and items:
        last = items[-1]
        next_cursor = _encode_dead_letter_cursor(
            updated_at=last.updated_at,
            event_id=last.event.event_id,
        )
    return CacheTargetDeadLetterPage(items=items, next_cursor=next_cursor)


async def replay_cache_target_dead_letter(
    session: AsyncSession,
    *,
    event_id: str,
    expected_delivery_version: int,
) -> CacheTargetDeliveryResult:
    """동일 immutable event를 dead에서 retry로 되돌리고 stream block은 유지한다."""
    event_id = _canonical_uuid(event_id, field="event_id")
    row = (await session.execute(text(_LOCK_DEAD_LETTER_SQL), {"event_id": event_id})).one_or_none()
    if row is None:
        raise CacheTargetStreamConflict("dead_letter_not_found", "dead letter가 없습니다.")
    if int(row._mapping["delivery_version"]) != expected_delivery_version:
        raise CacheTargetStreamConflict(
            "dead_letter_precondition_failed",
            "dead-letter delivery version이 If-Match와 다릅니다.",
            current={
                "entity_tag": cache_target_dead_letter_entity_tag(
                    event_id,
                    int(row._mapping["delivery_version"]),
                )
            },
        )
    updated = (await session.execute(text(_REPLAY_DEAD_LETTER_SQL), {"event_id": event_id})).one()
    return CacheTargetDeliveryResult(
        event_id=event_id,
        status="retry",
        delivery_version=int(updated._mapping["delivery_version"]),
        attempt_count=int(updated._mapping["attempt_count"]),
        stream_blocked=True,
    )
