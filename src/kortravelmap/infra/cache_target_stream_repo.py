"""Cache target source-generation, restore fence와 result outbox repository.

함수는 commit하지 않는다. 호출자는 source command/head/target/outbox/delivery를 같은
transaction에 묶고, HTTP 계층은 여기의 typed conflict를 RFC7807 응답으로 변환한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import text

from kortravelmap.core.cache_target_stream import (
    ActiveCacheTargetSourceV1,
    CacheTargetSourceV1,
    DeletedCacheTargetSourceV1,
    cache_target_source_fingerprint,
)
from kortravelmap.core.sync_scope import MAX_EXTERNAL_SYSTEM_NAME_LENGTH
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.domain_command_repo import canonical_domain_command_fingerprint
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    delete_poi_cache_target,
    upsert_poi_cache_target,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CacheTargetRestoreFenceResult",
    "CacheTargetSourceApplyResult",
    "CacheTargetStreamConflict",
    "CacheTargetStreamControl",
    "advance_cache_target_restore_fence",
    "apply_cache_target_source",
    "cache_target_stream_entity_tag",
    "get_cache_target_stream",
    "lock_cache_target_stream",
]

_MAX_BIGINT = 9_223_372_036_854_775_807


class CacheTargetStreamConflict(RuntimeError):
    """현재 stream/head/precondition과 command가 양립할 수 없음."""

    def __init__(self, code: str, message: str, *, current: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.current = current or {}


@dataclass(frozen=True, slots=True)
class CacheTargetStreamControl:
    external_system: str
    consumer_id: str
    restore_epoch: int
    control_version: int
    status: Literal["ready", "fenced", "blocked"]
    blocked_event_id: str | None
    consumer_enabled: bool
    created_at: datetime
    updated_at: datetime

    @property
    def entity_tag(self) -> str:
        return cache_target_stream_entity_tag(
            self.external_system,
            self.control_version,
        )


@dataclass(frozen=True, slots=True)
class CacheTargetSourceApplyResult:
    source_event_id: str
    outbox_event_id: str
    relay_order: int
    external_system: str
    target_key: str
    state: Literal["active", "deleted"]
    restore_epoch: int
    source_generation: int
    target_sequence: int
    source_payload_fingerprint: str
    payload: dict[str, Any]
    target: PoiCacheTarget | None
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class CacheTargetRestoreFenceResult:
    fence_id: str
    command_id: int
    external_system: str
    consumer_id: str
    previous_restore_epoch: int
    restore_epoch: int
    previous_control_version: int
    control_version: int
    invalidated_claim_count: int
    idempotent_replay: bool = False


_STREAM_COLUMNS = (
    "external_system, consumer_id, restore_epoch, control_version, status, "
    "blocked_event_id, consumer_enabled, created_at, updated_at"
)

_CREATE_STREAM_SQL = f"""
INSERT INTO ops.poi_cache_target_streams (
    external_system, consumer_id, restore_epoch, control_version, status,
    consumer_enabled
) VALUES (
    :external_system, :consumer_id, 1, 1, 'fenced', false
)
ON CONFLICT (external_system) DO NOTHING
RETURNING {_STREAM_COLUMNS}
"""

_GET_STREAM_SQL = f"""
SELECT {_STREAM_COLUMNS}
FROM ops.poi_cache_target_streams
WHERE external_system = :external_system
"""

_LOCK_STREAM_SQL = _GET_STREAM_SQL + " FOR UPDATE"

_LOCK_HEAD_SQL = """
SELECT external_system, target_key, target_id, state, restore_epoch,
       source_generation, source_payload_fingerprint, last_source_event_id,
       target_sequence, updated_at
FROM ops.poi_cache_target_source_heads
WHERE external_system = :external_system
  AND target_key = :target_key
FOR UPDATE
"""

_LOCK_TARGET_VERSION_SQL = """
SELECT target_id, lock_version
FROM ops.poi_cache_targets
WHERE target_id = CAST(:target_id AS uuid)
  AND deleted_at IS NULL
FOR UPDATE
"""

_GET_SOURCE_REPLAY_SQL = """
SELECT source.event_id AS source_event_id, source.external_system,
       source.target_key, source.restore_epoch, source.source_generation,
       source.request_fingerprint, source.source_payload_fingerprint,
       source.target_id AS historical_target_id,
       outbox.event_id AS outbox_event_id, outbox.relay_order,
       outbox.target_sequence, outbox.payload
FROM ops.poi_cache_target_source_events AS source
JOIN ops.poi_cache_target_outbox_events AS outbox
  ON outbox.source_event_id = source.event_id
 AND outbox.event_type = 'cache_target.state_applied'
WHERE source.external_system = :external_system
  AND source.idempotency_key = CAST(:idempotency_key AS uuid)
"""

_GET_SOURCE_EVENT_ID_SQL = """
SELECT external_system, idempotency_key, request_fingerprint
FROM ops.poi_cache_target_source_events
WHERE event_id = CAST(:event_id AS uuid)
"""

_GET_SOURCE_GENERATION_SQL = """
SELECT event_id, idempotency_key, request_fingerprint
FROM ops.poi_cache_target_source_events
WHERE external_system = :external_system
  AND target_key = :target_key
  AND restore_epoch = :restore_epoch
  AND source_generation = :source_generation
"""

_INSERT_HEAD_SQL = """
INSERT INTO ops.poi_cache_target_source_heads (
    external_system, target_key, target_id, state, restore_epoch,
    source_generation, source_payload_fingerprint, target_sequence
) VALUES (
    :external_system, :target_key, CAST(:target_id AS uuid), :state,
    :restore_epoch, :source_generation, :source_payload_fingerprint, 0
)
"""

_INSERT_SOURCE_EVENT_SQL = """
INSERT INTO ops.poi_cache_target_source_events (
    event_id, external_system, target_key, idempotency_key, operation,
    restore_epoch, source_generation, request_fingerprint,
    source_payload_fingerprint, outcome, target_id, occurred_at
) VALUES (
    CAST(:event_id AS uuid), :external_system, :target_key,
    CAST(:idempotency_key AS uuid), :operation, :restore_epoch,
    :source_generation, :request_fingerprint, :source_payload_fingerprint,
    'applied', CAST(:target_id AS uuid), CAST(:occurred_at AS timestamptz)
)
"""

_INSERT_OUTBOX_EVENT_SQL = """
INSERT INTO ops.poi_cache_target_outbox_events (
    event_id, event_type, external_system, target_key, target_id,
    restore_epoch, source_generation, target_sequence,
    source_payload_fingerprint, payload_fingerprint, payload, source_event_id
) VALUES (
    CAST(:event_id AS uuid), 'cache_target.state_applied', :external_system,
    :target_key, CAST(:target_id AS uuid), :restore_epoch, :source_generation,
    :target_sequence, :source_payload_fingerprint, :payload_fingerprint,
    CAST(:payload AS jsonb), CAST(:source_event_id AS uuid)
)
RETURNING relay_order
"""

_INSERT_DELIVERY_SQL = """
INSERT INTO ops.poi_cache_target_outbox_deliveries (event_id, status)
VALUES (CAST(:event_id AS uuid), 'pending')
"""

_UPDATE_HEAD_SQL = """
UPDATE ops.poi_cache_target_source_heads
SET target_id = CAST(:target_id AS uuid),
    state = :state,
    restore_epoch = :restore_epoch,
    source_generation = :source_generation,
    source_payload_fingerprint = :source_payload_fingerprint,
    last_source_event_id = CAST(:source_event_id AS uuid),
    target_sequence = :target_sequence,
    updated_at = now()
WHERE external_system = :external_system
  AND target_key = :target_key
"""

_GET_FENCE_BY_COMMAND_SQL = """
SELECT fence_id, command_id, external_system, consumer_id, request_fingerprint,
       previous_restore_epoch, restore_epoch, previous_control_version,
       control_version
FROM ops.poi_cache_target_restore_fences
WHERE command_id = :command_id
"""

_INVALIDATE_CLAIMS_SQL = """
UPDATE ops.poi_cache_target_outbox_claims
SET status = 'invalidated', completed_at = now()
WHERE external_system = :external_system
  AND status = 'active'
RETURNING claim_id
"""

_RELEASE_INVALIDATED_DELIVERIES_SQL = """
UPDATE ops.poi_cache_target_outbox_deliveries AS delivery
SET status = 'retry', claim_id = NULL, lease_token = NULL,
    lease_expires_at = NULL, available_at = now(), updated_at = now()
WHERE delivery.status = 'leased'
  AND delivery.claim_id = ANY(CAST(:claim_ids AS uuid[]))
"""

_UPDATE_RESTORE_FENCE_SQL = """
UPDATE ops.poi_cache_target_streams
SET restore_epoch = restore_epoch + 1,
    control_version = control_version + 1,
    status = 'fenced', blocked_event_id = NULL,
    last_barrier_command_id = :command_id,
    consumer_enabled = false,
    updated_at = now()
WHERE external_system = :external_system
RETURNING restore_epoch, control_version
"""

_INSERT_RESTORE_FENCE_SQL = """
INSERT INTO ops.poi_cache_target_restore_fences (
    fence_id, external_system, consumer_id, command_id,
    previous_restore_epoch, restore_epoch, previous_control_version,
    control_version, reason, request_fingerprint
) VALUES (
    CAST(:fence_id AS uuid), :external_system, :consumer_id, :command_id,
    :previous_restore_epoch, :restore_epoch, :previous_control_version,
    :control_version, :reason, :request_fingerprint
)
"""


def _validate_identity(external_system: str, target_key: str | None = None) -> None:
    if not external_system or external_system != external_system.strip():
        raise ValueError("external_system은 trim된 비어 있지 않은 문자열이어야 합니다.")
    if len(external_system) > MAX_EXTERNAL_SYSTEM_NAME_LENGTH:
        raise ValueError(f"external_system은 {MAX_EXTERNAL_SYSTEM_NAME_LENGTH}자 이하여야 합니다.")
    if target_key is not None and (
        not target_key or target_key != target_key.strip() or len(target_key) > 512
    ):
        raise ValueError("target_key는 trim된 1~512자 문자열이어야 합니다.")


def _canonical_uuid(value: str, *, field: str) -> str:
    canonical = str(UUID(value))
    if value != canonical:
        raise ValueError(f"{field}는 lowercase canonical UUID여야 합니다.")
    return canonical


def cache_target_stream_entity_tag(external_system: str, control_version: int) -> str:
    """stream control CAS용 raw strong ETag."""
    _validate_identity(external_system)
    if not 0 < control_version <= _MAX_BIGINT:
        raise ValueError("control_version은 양의 BIGINT 범위여야 합니다.")
    return f'"{external_system}:{control_version}"'


def _stream(row: Any) -> CacheTargetStreamControl:
    values = row._mapping
    return CacheTargetStreamControl(
        external_system=str(values["external_system"]),
        consumer_id=str(values["consumer_id"]),
        restore_epoch=int(values["restore_epoch"]),
        control_version=int(values["control_version"]),
        status=values["status"],
        blocked_event_id=(
            str(values["blocked_event_id"]) if values["blocked_event_id"] is not None else None
        ),
        consumer_enabled=bool(values["consumer_enabled"]),
        created_at=values["created_at"],
        updated_at=values["updated_at"],
    )


async def get_cache_target_stream(
    session: AsyncSession,
    *,
    external_system: str,
) -> CacheTargetStreamControl | None:
    """stream control을 lock 없이 조회한다."""
    _validate_identity(external_system)
    row = (
        await session.execute(text(_GET_STREAM_SQL), {"external_system": external_system})
    ).one_or_none()
    return _stream(row) if row is not None else None


async def _lock_or_create_stream(
    session: AsyncSession,
    *,
    external_system: str,
    consumer_id: str,
) -> CacheTargetStreamControl:
    if not consumer_id or consumer_id != consumer_id.strip() or len(consumer_id) > 128:
        raise ValueError("consumer_id는 trim된 1~128자 문자열이어야 합니다.")
    created = (
        await session.execute(
            text(_CREATE_STREAM_SQL),
            {"external_system": external_system, "consumer_id": consumer_id},
        )
    ).one_or_none()
    row = created
    if row is None:
        row = (
            await session.execute(
                text(_LOCK_STREAM_SQL),
                {"external_system": external_system},
            )
        ).one()
    control = _stream(row)
    if control.consumer_id != consumer_id:
        raise CacheTargetStreamConflict(
            "consumer_mismatch",
            "service principal consumer_id가 stream binding과 다릅니다.",
            current={"consumer_id": control.consumer_id},
        )
    return control


async def lock_cache_target_stream(
    session: AsyncSession,
    *,
    external_system: str,
    consumer_id: str,
) -> CacheTargetStreamControl:
    """stream을 없으면 fenced로 만들고 row lock+consumer binding을 반환한다."""
    _validate_identity(external_system)
    return await _lock_or_create_stream(
        session,
        external_system=external_system,
        consumer_id=consumer_id,
    )


def _source_request_fingerprint(
    *,
    source_event_id: str,
    operation: str,
    external_system: str,
    target_key: str,
    restore_epoch: int,
    source_generation: int,
    source_payload_fingerprint: str,
    create_only: bool,
    expected_target_id: str | None,
    expected_lock_version: int | None,
) -> str:
    return str(
        canonical_domain_command_fingerprint(
            {
                "version": "cache-target-source-command-v1",
                "source_event_id": source_event_id,
                "operation": operation,
                "external_system": external_system,
                "target_key": target_key,
                "restore_epoch": restore_epoch,
                "source_generation": source_generation,
                "source_payload_fingerprint": source_payload_fingerprint,
                "precondition": {
                    "create_only": create_only,
                    "target_id": expected_target_id,
                    "lock_version": expected_lock_version,
                },
            }
        )
    )


async def _lock_source_command(
    session: AsyncSession,
    *,
    external_system: str,
    idempotency_key: str,
) -> None:
    lock_id = advisory_lock_key(f"cache-target-source:{external_system}:{idempotency_key}")
    await session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:lock_id AS bigint))"),
        {"lock_id": lock_id},
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("저장된 outbox payload가 object가 아닙니다.")
    return {str(key): item for key, item in value.items()}


def _replay_result(row: Any) -> CacheTargetSourceApplyResult:
    values = row._mapping
    payload = _json_object(values["payload"])
    state = payload.get("state")
    if state not in ("active", "deleted"):
        raise ValueError("저장된 state_applied payload state가 유효하지 않습니다.")
    return CacheTargetSourceApplyResult(
        source_event_id=str(values["source_event_id"]),
        outbox_event_id=str(values["outbox_event_id"]),
        relay_order=int(values["relay_order"]),
        external_system=str(values["external_system"]),
        target_key=str(values["target_key"]),
        state=state,
        restore_epoch=int(values["restore_epoch"]),
        source_generation=int(values["source_generation"]),
        target_sequence=int(values["target_sequence"]),
        source_payload_fingerprint=str(values["source_payload_fingerprint"]),
        payload=payload,
        target=None,
        idempotent_replay=True,
    )


async def apply_cache_target_source(
    session: AsyncSession,
    *,
    consumer_id: str,
    source_event_id: str,
    idempotency_key: str,
    external_system: str,
    target_key: str,
    restore_epoch: int,
    source_generation: int,
    source: CacheTargetSourceV1,
    occurred_at: datetime,
    create_only: bool,
    expected_target_id: str | None = None,
    expected_lock_version: int | None = None,
) -> CacheTargetSourceApplyResult:
    """desired state 한 건과 result outbox를 같은 transaction에 적용한다."""
    _validate_identity(external_system, target_key)
    source_event_id = _canonical_uuid(source_event_id, field="source_event_id")
    idempotency_key = _canonical_uuid(idempotency_key, field="idempotency_key")
    if not 0 < restore_epoch <= _MAX_BIGINT:
        raise ValueError("restore_epoch은 양의 BIGINT 범위여야 합니다.")
    if not 0 < source_generation <= _MAX_BIGINT:
        raise ValueError("source_generation은 양의 BIGINT 범위여야 합니다.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("occurred_at은 timezone-aware datetime이어야 합니다.")
    if expected_target_id is not None:
        expected_target_id = _canonical_uuid(
            expected_target_id,
            field="expected_target_id",
        )
    if (expected_target_id is None) != (expected_lock_version is None):
        raise ValueError("target precondition UUID와 version은 함께 있어야 합니다.")
    if expected_lock_version is not None and not 0 < expected_lock_version <= _MAX_BIGINT:
        raise ValueError("expected_lock_version은 양의 BIGINT 범위여야 합니다.")
    if create_only and expected_target_id is not None:
        raise ValueError("create_only와 target version precondition은 함께 쓸 수 없습니다.")

    operation = "delete" if isinstance(source, DeletedCacheTargetSourceV1) else "upsert"
    source_fingerprint = cache_target_source_fingerprint(source)
    request_fingerprint = _source_request_fingerprint(
        source_event_id=source_event_id,
        operation=operation,
        external_system=external_system,
        target_key=target_key,
        restore_epoch=restore_epoch,
        source_generation=source_generation,
        source_payload_fingerprint=source_fingerprint,
        create_only=create_only,
        expected_target_id=expected_target_id,
        expected_lock_version=expected_lock_version,
    )

    await _lock_source_command(
        session,
        external_system=external_system,
        idempotency_key=idempotency_key,
    )
    event_identity = (
        await session.execute(
            text(_GET_SOURCE_EVENT_ID_SQL),
            {"event_id": source_event_id},
        )
    ).one_or_none()
    if event_identity is not None and (
        str(event_identity._mapping["external_system"]) != external_system
        or str(event_identity._mapping["idempotency_key"]) != idempotency_key
        or str(event_identity._mapping["request_fingerprint"]) != request_fingerprint
    ):
        raise CacheTargetStreamConflict(
            "source_event_id_reused",
            "같은 source_event_id가 다른 command identity에 사용됐습니다.",
        )

    replay = (
        await session.execute(
            text(_GET_SOURCE_REPLAY_SQL),
            {"external_system": external_system, "idempotency_key": idempotency_key},
        )
    ).one_or_none()
    if replay is not None:
        if str(replay._mapping["request_fingerprint"]) != request_fingerprint:
            raise CacheTargetStreamConflict(
                "idempotency_key_reused",
                "같은 Idempotency-Key가 다른 source command에 사용됐습니다.",
            )
        return _replay_result(replay)

    control = await _lock_or_create_stream(
        session,
        external_system=external_system,
        consumer_id=consumer_id,
    )
    if restore_epoch != control.restore_epoch:
        raise CacheTargetStreamConflict(
            "restore_epoch_mismatch",
            "source command restore_epoch가 Map control epoch와 다릅니다.",
            current={
                "restore_epoch": control.restore_epoch,
                "entity_tag": control.entity_tag,
            },
        )

    head = (
        await session.execute(
            text(_LOCK_HEAD_SQL),
            {"external_system": external_system, "target_key": target_key},
        )
    ).one_or_none()
    expected_generation = 1 if head is None else int(head._mapping["source_generation"]) + 1
    if source_generation != expected_generation:
        generation_row = (
            await session.execute(
                text(_GET_SOURCE_GENERATION_SQL),
                {
                    "external_system": external_system,
                    "target_key": target_key,
                    "restore_epoch": restore_epoch,
                    "source_generation": source_generation,
                },
            )
        ).one_or_none()
        raise CacheTargetStreamConflict(
            "source_generation_mismatch",
            "source_generation은 natural key별로 정확히 1씩 증가해야 합니다.",
            current={
                "source_generation": expected_generation - 1,
                "expected_next_generation": expected_generation,
                "existing_event_id": (
                    str(generation_row._mapping["event_id"]) if generation_row is not None else None
                ),
            },
        )

    current_target_id = (
        str(head._mapping["target_id"])
        if head is not None and head._mapping["target_id"] is not None
        else None
    )
    current_target_version: int | None = None
    if current_target_id is not None:
        target_version_row = (
            await session.execute(
                text(_LOCK_TARGET_VERSION_SQL),
                {"target_id": current_target_id},
            )
        ).one_or_none()
        if target_version_row is not None:
            current_target_version = int(target_version_row._mapping["lock_version"])

    if create_only:
        if current_target_id is not None:
            raise CacheTargetStreamConflict(
                "create_precondition_failed",
                "If-None-Match create에 이미 active target이 존재합니다.",
                current={
                    "target_id": current_target_id,
                    "lock_version": current_target_version,
                },
            )
    elif (
        expected_target_id is None
        or current_target_id != expected_target_id
        or current_target_version != expected_lock_version
    ):
        raise CacheTargetStreamConflict(
            "target_precondition_failed",
            "If-Match target UUID 또는 lock_version이 현재 target과 다릅니다.",
            current={
                "target_id": current_target_id,
                "lock_version": current_target_version,
            },
        )

    target: PoiCacheTarget | None
    historical_target_id: str | None
    event_target_id: str | None
    if isinstance(source, ActiveCacheTargetSourceV1):
        target = await upsert_poi_cache_target(
            session,
            external_system=external_system,
            target_key=target_key,
            name=None,
            lon=source.lon_e6 / 1_000_000,
            lat=source.lat_e6 / 1_000_000,
            radius_km=source.radius_m / 1_000,
            coord_precision_digits=6,
            scope_mode="center_radius",
            update_enabled=source.update_enabled,
            refresh_policy="provider_default",
            provider_overrides={},
            metadata={"external_poi_id": target_key},
            on_conflict="move",
        )
        historical_target_id = target.target_id
        event_target_id = target.target_id
        state: Literal["active", "deleted"] = "active"
        payload: dict[str, Any] = {
            "version": "cache-target-event-v1",
            "state": state,
            "source_event_id": source_event_id,
            "target": {
                "target_id": target.target_id,
                "entity_tag": target.entity_tag,
                "coord": {"lon_e6": source.lon_e6, "lat_e6": source.lat_e6},
                "radius_m": source.radius_m,
                "update_enabled": source.update_enabled,
            },
        }
    else:
        if current_target_id is None:
            raise CacheTargetStreamConflict(
                "target_not_found",
                "삭제할 active target이 없습니다.",
            )
        deleted = await delete_poi_cache_target(
            session,
            external_system=external_system,
            target_key=target_key,
            expected_target_id=current_target_id,
            expected_lock_version=expected_lock_version or 0,
        )
        if deleted.status != "deleted" or deleted.target is None:
            raise CacheTargetStreamConflict(
                "target_precondition_failed",
                "target delete CAS가 현재 row와 충돌했습니다.",
            )
        target = deleted.target
        historical_target_id = target.target_id
        event_target_id = None
        state = "deleted"
        payload = {
            "version": "cache-target-event-v1",
            "state": state,
            "source_event_id": source_event_id,
            "target": None,
        }

    if head is None:
        await session.execute(
            text(_INSERT_HEAD_SQL),
            {
                "external_system": external_system,
                "target_key": target_key,
                "target_id": event_target_id,
                "state": state,
                "restore_epoch": restore_epoch,
                "source_generation": source_generation,
                "source_payload_fingerprint": source_fingerprint,
            },
        )

    await session.execute(
        text(_INSERT_SOURCE_EVENT_SQL),
        {
            "event_id": source_event_id,
            "external_system": external_system,
            "target_key": target_key,
            "idempotency_key": idempotency_key,
            "operation": operation,
            "restore_epoch": restore_epoch,
            "source_generation": source_generation,
            "request_fingerprint": request_fingerprint,
            "source_payload_fingerprint": source_fingerprint,
            "target_id": historical_target_id,
            "occurred_at": occurred_at.astimezone(UTC),
        },
    )

    target_sequence = 1
    outbox_event_id = str(uuid4())
    payload_fingerprint = canonical_domain_command_fingerprint(payload)
    relay_order = int(
        (
            await session.execute(
                text(_INSERT_OUTBOX_EVENT_SQL),
                {
                    "event_id": outbox_event_id,
                    "external_system": external_system,
                    "target_key": target_key,
                    "target_id": event_target_id,
                    "restore_epoch": restore_epoch,
                    "source_generation": source_generation,
                    "target_sequence": target_sequence,
                    "source_payload_fingerprint": source_fingerprint,
                    "payload_fingerprint": payload_fingerprint,
                    "payload": json.dumps(
                        payload,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "source_event_id": source_event_id,
                },
            )
        ).scalar_one()
    )
    await session.execute(text(_INSERT_DELIVERY_SQL), {"event_id": outbox_event_id})
    await session.execute(
        text(_UPDATE_HEAD_SQL),
        {
            "external_system": external_system,
            "target_key": target_key,
            "target_id": event_target_id,
            "state": state,
            "restore_epoch": restore_epoch,
            "source_generation": source_generation,
            "source_payload_fingerprint": source_fingerprint,
            "source_event_id": source_event_id,
            "target_sequence": target_sequence,
        },
    )
    return CacheTargetSourceApplyResult(
        source_event_id=source_event_id,
        outbox_event_id=outbox_event_id,
        relay_order=relay_order,
        external_system=external_system,
        target_key=target_key,
        state=state,
        restore_epoch=restore_epoch,
        source_generation=source_generation,
        target_sequence=target_sequence,
        source_payload_fingerprint=source_fingerprint,
        payload=payload,
        target=target,
        idempotent_replay=False,
    )


async def advance_cache_target_restore_fence(
    session: AsyncSession,
    *,
    external_system: str,
    consumer_id: str,
    command_id: int,
    expected_restore_epoch: int,
    expected_control_version: int,
    reason: str,
    request_fingerprint: str,
) -> CacheTargetRestoreFenceResult:
    """domain-command claim과 같은 transaction에서 epoch barrier를 전진시킨다."""
    _validate_identity(external_system)
    if not reason or reason != reason.strip() or len(reason) > 1000:
        raise ValueError("reason은 trim된 1~1000자 문자열이어야 합니다.")
    if len(request_fingerprint) != 64:
        raise ValueError("request_fingerprint는 SHA-256 hex여야 합니다.")

    existing = (
        await session.execute(text(_GET_FENCE_BY_COMMAND_SQL), {"command_id": command_id})
    ).one_or_none()
    if existing is not None:
        values = existing._mapping
        if (
            str(values["external_system"]) != external_system
            or str(values["consumer_id"]) != consumer_id
            or str(values["request_fingerprint"]) != request_fingerprint
        ):
            raise CacheTargetStreamConflict(
                "restore_fence_command_mismatch",
                "command_id가 다른 restore fence request에 연결돼 있습니다.",
            )
        return CacheTargetRestoreFenceResult(
            fence_id=str(values["fence_id"]),
            command_id=int(values["command_id"]),
            external_system=str(values["external_system"]),
            consumer_id=str(values["consumer_id"]),
            previous_restore_epoch=int(values["previous_restore_epoch"]),
            restore_epoch=int(values["restore_epoch"]),
            previous_control_version=int(values["previous_control_version"]),
            control_version=int(values["control_version"]),
            invalidated_claim_count=0,
            idempotent_replay=True,
        )

    control = await _lock_or_create_stream(
        session,
        external_system=external_system,
        consumer_id=consumer_id,
    )
    if (
        control.restore_epoch != expected_restore_epoch
        or control.control_version != expected_control_version
    ):
        raise CacheTargetStreamConflict(
            "restore_fence_precondition_failed",
            "restore epoch 또는 stream ETag가 현재 control과 다릅니다.",
            current={
                "restore_epoch": control.restore_epoch,
                "control_version": control.control_version,
                "entity_tag": control.entity_tag,
            },
        )
    if control.restore_epoch == _MAX_BIGINT or control.control_version == _MAX_BIGINT:
        raise CacheTargetStreamConflict(
            "stream_version_exhausted",
            "restore epoch 또는 control version이 BIGINT 최댓값에 도달했습니다.",
        )

    invalidated_rows = (
        await session.execute(
            text(_INVALIDATE_CLAIMS_SQL),
            {"external_system": external_system},
        )
    ).all()
    claim_ids = [str(row._mapping["claim_id"]) for row in invalidated_rows]
    if claim_ids:
        await session.execute(
            text(_RELEASE_INVALIDATED_DELIVERIES_SQL),
            {"claim_ids": claim_ids},
        )
    advanced = (
        await session.execute(
            text(_UPDATE_RESTORE_FENCE_SQL),
            {"external_system": external_system, "command_id": command_id},
        )
    ).one()
    restore_epoch = int(advanced._mapping["restore_epoch"])
    control_version = int(advanced._mapping["control_version"])
    fence_id = str(uuid4())
    await session.execute(
        text(_INSERT_RESTORE_FENCE_SQL),
        {
            "fence_id": fence_id,
            "external_system": external_system,
            "consumer_id": consumer_id,
            "command_id": command_id,
            "previous_restore_epoch": control.restore_epoch,
            "restore_epoch": restore_epoch,
            "previous_control_version": control.control_version,
            "control_version": control_version,
            "reason": reason,
            "request_fingerprint": request_fingerprint,
        },
    )
    return CacheTargetRestoreFenceResult(
        fence_id=fence_id,
        command_id=command_id,
        external_system=external_system,
        consumer_id=consumer_id,
        previous_restore_epoch=control.restore_epoch,
        restore_epoch=restore_epoch,
        previous_control_version=control.control_version,
        control_version=control_version,
        invalidated_claim_count=len(claim_ids),
    )
