"""Cache target link/refresh/reconcile 결과를 transaction outbox에 기록한다.

함수는 commit하지 않는다. 호출자는 domain mutation과 event/delivery insert를 같은
``AsyncSession`` transaction에 둔다. source head가 없는 legacy/admin target은 외부
generation 계약에 참여하지 않으므로 event 대상에서 제외한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import text

from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.domain_command_repo import canonical_domain_command_fingerprint

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CacheTargetRefreshMember",
    "CacheTargetResultEvent",
    "append_cache_target_links_reconciled_events",
    "append_cache_target_refresh_status_events",
    "capture_cache_target_refresh_members",
    "capture_cache_target_refresh_members_by_keys",
]

CacheTargetResultEventType = Literal[
    "cache_target.links_reconciled",
    "refresh_request.status_changed",
    "cache_target.reconciled",
]
CacheTargetRefreshStatus = Literal[
    "queued",
    "running",
    "done",
    "failed",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class CacheTargetRefreshMember:
    request_id: str
    target_id: str
    external_system: str
    target_key: str
    restore_epoch: int
    source_generation: int
    source_payload_fingerprint: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CacheTargetResultEvent:
    event_id: str
    event_type: CacheTargetResultEventType
    external_system: str
    target_key: str
    target_id: str
    restore_epoch: int
    source_generation: int
    target_sequence: int
    relay_order: int
    source_payload_fingerprint: str
    payload_fingerprint: str
    payload: dict[str, Any]
    occurred_at: datetime
    idempotent_replay: bool = False


_CAPTURE_REFRESH_MEMBERS_SQL = """
INSERT INTO ops.poi_cache_target_refresh_members (
    request_id, target_id, external_system, target_key,
    restore_epoch, source_generation
)
SELECT CAST(:request_id AS uuid), head.target_id, head.external_system,
       head.target_key, head.restore_epoch, head.source_generation
FROM ops.poi_cache_target_source_heads AS head
JOIN ops.poi_cache_targets AS target
  ON target.target_id = head.target_id
WHERE head.state = 'active'
  AND head.target_id::text = ANY(CAST(:target_ids AS text[]))
  AND target.deleted_at IS NULL
ORDER BY head.external_system, head.target_key
FOR KEY SHARE OF head
ON CONFLICT (request_id, target_id) DO NOTHING
"""

_CAPTURE_REFRESH_MEMBERS_BY_KEYS_SQL = """
INSERT INTO ops.poi_cache_target_refresh_members (
    request_id, target_id, external_system, target_key,
    restore_epoch, source_generation
)
SELECT CAST(:request_id AS uuid), head.target_id, head.external_system,
       head.target_key, head.restore_epoch, head.source_generation
FROM ops.poi_cache_target_source_heads AS head
JOIN ops.poi_cache_targets AS target
  ON target.target_id = head.target_id
WHERE head.external_system = :external_system
  AND head.target_key = ANY(CAST(:target_keys AS text[]))
  AND head.state = 'active'
  AND target.deleted_at IS NULL
  AND target.update_enabled
  AND target.refresh_policy <> 'disabled'
ORDER BY head.external_system, head.target_key
FOR KEY SHARE OF head
ON CONFLICT (request_id, target_id) DO NOTHING
"""

_SELECT_REFRESH_MEMBERS_SQL = """
SELECT member.request_id, member.target_id, member.external_system,
       member.target_key, member.restore_epoch, member.source_generation,
       source.source_payload_fingerprint, member.created_at
FROM ops.poi_cache_target_refresh_members AS member
JOIN ops.poi_cache_target_source_events AS source
  ON source.external_system = member.external_system
 AND source.target_key = member.target_key
 AND source.restore_epoch = member.restore_epoch
 AND source.source_generation = member.source_generation
WHERE member.request_id = CAST(:request_id AS uuid)
ORDER BY member.external_system, member.target_key, member.target_id
"""

_LOCK_HEAD_SQL = """
SELECT restore_epoch, source_generation, target_sequence
FROM ops.poi_cache_target_source_heads
WHERE external_system = :external_system
  AND target_key = :target_key
FOR UPDATE
"""

_GET_REPLAY_SQL = """
SELECT event_id, event_type, external_system, target_key, target_id,
       restore_epoch, source_generation, target_sequence, relay_order,
       source_payload_fingerprint, payload_fingerprint, payload, occurred_at
FROM ops.poi_cache_target_outbox_events
WHERE external_system = :external_system
  AND target_key = :target_key
  AND restore_epoch = :restore_epoch
  AND source_generation = :source_generation
  AND event_type = :event_type
  AND payload_fingerprint = :payload_fingerprint
  AND refresh_request_id IS NOT DISTINCT FROM CAST(:refresh_request_id AS uuid)
  AND reconciliation_request_id IS NOT DISTINCT FROM
      CAST(:reconciliation_request_id AS uuid)
ORDER BY target_sequence
LIMIT 1
"""

_GET_LAST_SEQUENCE_SQL = """
SELECT COALESCE(max(target_sequence), 0)
FROM ops.poi_cache_target_outbox_events
WHERE external_system = :external_system
  AND target_key = :target_key
  AND restore_epoch = :restore_epoch
  AND source_generation = :source_generation
"""

_INSERT_EVENT_SQL = """
INSERT INTO ops.poi_cache_target_outbox_events (
    event_id, event_type, external_system, target_key, target_id,
    restore_epoch, source_generation, target_sequence,
    source_payload_fingerprint, payload_fingerprint, payload,
    refresh_request_id, job_id, domain_command_id,
    reconciliation_request_id
) VALUES (
    CAST(:event_id AS uuid), :event_type, :external_system, :target_key,
    CAST(:target_id AS uuid), :restore_epoch, :source_generation,
    :target_sequence, :source_payload_fingerprint, :payload_fingerprint,
    CAST(:payload AS jsonb), CAST(:refresh_request_id AS uuid),
    CAST(:job_id AS uuid), :domain_command_id,
    CAST(:reconciliation_request_id AS uuid)
)
RETURNING event_id, event_type, external_system, target_key, target_id,
          restore_epoch, source_generation, target_sequence, relay_order,
          source_payload_fingerprint, payload_fingerprint, payload, occurred_at
"""

_INSERT_DELIVERY_SQL = """
INSERT INTO ops.poi_cache_target_outbox_deliveries (event_id, status)
VALUES (CAST(:event_id AS uuid), 'pending')
"""

_BUMP_CURRENT_HEAD_SEQUENCE_SQL = """
UPDATE ops.poi_cache_target_source_heads
SET target_sequence = GREATEST(target_sequence, :target_sequence),
    updated_at = now()
WHERE external_system = :external_system
  AND target_key = :target_key
  AND restore_epoch = :restore_epoch
  AND source_generation = :source_generation
"""


def _canonical_uuid(value: str, *, field: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field}는 canonical UUID여야 합니다.") from exc


def _member(row: Any) -> CacheTargetRefreshMember:
    values = row._mapping
    return CacheTargetRefreshMember(
        request_id=str(values["request_id"]),
        target_id=str(values["target_id"]),
        external_system=str(values["external_system"]),
        target_key=str(values["target_key"]),
        restore_epoch=int(values["restore_epoch"]),
        source_generation=int(values["source_generation"]),
        source_payload_fingerprint=str(values["source_payload_fingerprint"]),
        created_at=values["created_at"],
    )


def _event(row: Any, *, idempotent_replay: bool) -> CacheTargetResultEvent:
    values = row._mapping
    payload_value = values["payload"]
    payload = (
        dict(payload_value)
        if isinstance(payload_value, dict)
        else dict(json.loads(str(payload_value)))
    )
    raw_event_type = str(values["event_type"])
    if raw_event_type not in (
        "cache_target.links_reconciled",
        "refresh_request.status_changed",
        "cache_target.reconciled",
    ):
        raise RuntimeError(f"unexpected cache target result event type: {raw_event_type}")
    event_type = cast("CacheTargetResultEventType", raw_event_type)
    return CacheTargetResultEvent(
        event_id=str(values["event_id"]),
        event_type=event_type,
        external_system=str(values["external_system"]),
        target_key=str(values["target_key"]),
        target_id=str(values["target_id"]),
        restore_epoch=int(values["restore_epoch"]),
        source_generation=int(values["source_generation"]),
        target_sequence=int(values["target_sequence"]),
        relay_order=int(values["relay_order"]),
        source_payload_fingerprint=str(values["source_payload_fingerprint"]),
        payload_fingerprint=str(values["payload_fingerprint"]),
        payload=payload,
        occurred_at=values["occurred_at"],
        idempotent_replay=idempotent_replay,
    )


async def capture_cache_target_refresh_members(
    session: AsyncSession,
    *,
    request_id: str,
    target_ids: Sequence[str],
) -> tuple[CacheTargetRefreshMember, ...]:
    """refresh 시작 시 target UUID와 source tuple을 고정한다."""
    request_id = _canonical_uuid(request_id, field="request_id")
    canonical_target_ids = tuple(
        sorted({_canonical_uuid(value, field="target_id") for value in target_ids})
    )
    if canonical_target_ids:
        await session.execute(
            text(_CAPTURE_REFRESH_MEMBERS_SQL),
            {"request_id": request_id, "target_ids": list(canonical_target_ids)},
        )
    rows = (
        await session.execute(
            text(_SELECT_REFRESH_MEMBERS_SQL),
            {"request_id": request_id},
        )
    ).all()
    return tuple(_member(row) for row in rows)


async def capture_cache_target_refresh_members_by_keys(
    session: AsyncSession,
    *,
    request_id: str,
    external_system: str,
    target_keys: Sequence[str],
) -> tuple[CacheTargetRefreshMember, ...]:
    """``cache_target_keys`` request의 active source tuple을 시작 시점에 고정한다."""
    request_id = _canonical_uuid(request_id, field="request_id")
    if not external_system or external_system != external_system.strip():
        raise ValueError("external_system은 trim된 비어 있지 않은 문자열이어야 합니다.")
    canonical_keys = tuple(sorted({str(value) for value in target_keys}))
    if any(not key or key != key.strip() for key in canonical_keys):
        raise ValueError("target_key는 trim된 비어 있지 않은 문자열이어야 합니다.")
    if canonical_keys:
        await session.execute(
            text(_CAPTURE_REFRESH_MEMBERS_BY_KEYS_SQL),
            {
                "request_id": request_id,
                "external_system": external_system,
                "target_keys": list(canonical_keys),
            },
        )
    return await capture_cache_target_refresh_members(
        session,
        request_id=request_id,
        target_ids=(),
    )


async def _append_result_event(
    session: AsyncSession,
    *,
    member: CacheTargetRefreshMember,
    event_type: CacheTargetResultEventType,
    payload: Mapping[str, Any],
    refresh_request_id: str | None,
    job_id: str | None,
    domain_command_id: int | None = None,
    reconciliation_request_id: str | None = None,
) -> CacheTargetResultEvent:
    payload_value = dict(payload)
    payload_fingerprint = str(canonical_domain_command_fingerprint(payload_value))
    refresh_request_id = (
        _canonical_uuid(refresh_request_id, field="refresh_request_id")
        if refresh_request_id is not None
        else None
    )
    job_id = _canonical_uuid(job_id, field="job_id") if job_id is not None else None
    reconciliation_request_id = (
        _canonical_uuid(reconciliation_request_id, field="reconciliation_request_id")
        if reconciliation_request_id is not None
        else None
    )
    lock_id = advisory_lock_key(
        "cache-target-result:"
        f"{member.external_system}:{member.target_key}:"
        f"{member.restore_epoch}:{member.source_generation}"
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:lock_id AS bigint))"),
        {"lock_id": lock_id},
    )
    head = (
        await session.execute(
            text(_LOCK_HEAD_SQL),
            {
                "external_system": member.external_system,
                "target_key": member.target_key,
            },
        )
    ).one_or_none()
    if head is None:
        raise RuntimeError("captured cache target source head가 사라졌습니다.")

    params = {
        "external_system": member.external_system,
        "target_key": member.target_key,
        "restore_epoch": member.restore_epoch,
        "source_generation": member.source_generation,
        "event_type": event_type,
        "payload_fingerprint": payload_fingerprint,
        "refresh_request_id": refresh_request_id,
        "reconciliation_request_id": reconciliation_request_id,
    }
    replay = (await session.execute(text(_GET_REPLAY_SQL), params)).one_or_none()
    if replay is not None:
        return _event(replay, idempotent_replay=True)

    last_sequence = int((await session.execute(text(_GET_LAST_SEQUENCE_SQL), params)).scalar_one())
    target_sequence = last_sequence + 1
    event_id = str(uuid4())
    inserted = (
        await session.execute(
            text(_INSERT_EVENT_SQL),
            {
                **params,
                "event_id": event_id,
                "target_id": member.target_id,
                "target_sequence": target_sequence,
                "source_payload_fingerprint": member.source_payload_fingerprint,
                "payload": json.dumps(
                    payload_value,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "job_id": job_id,
                "domain_command_id": domain_command_id,
            },
        )
    ).one()
    await session.execute(text(_INSERT_DELIVERY_SQL), {"event_id": event_id})
    await session.execute(
        text(_BUMP_CURRENT_HEAD_SEQUENCE_SQL),
        {
            **params,
            "target_sequence": target_sequence,
        },
    )
    return _event(inserted, idempotent_replay=False)


async def append_cache_target_refresh_status_events(
    session: AsyncSession,
    *,
    request_id: str,
    job_id: str,
    status: CacheTargetRefreshStatus,
    error_code: str | None = None,
) -> tuple[CacheTargetResultEvent, ...]:
    """captured member별 refresh status event를 같은 transaction에 기록한다."""
    if status not in ("queued", "running", "done", "failed", "cancelled"):
        raise ValueError("지원하지 않는 refresh status입니다.")
    members = await capture_cache_target_refresh_members(
        session,
        request_id=request_id,
        target_ids=(),
    )
    events: list[CacheTargetResultEvent] = []
    for member in members:
        events.append(
            await _append_result_event(
                session,
                member=member,
                event_type="refresh_request.status_changed",
                payload={
                    "version": "cache-target-event-v1",
                    "request_id": request_id,
                    "job_id": job_id,
                    "status": status,
                    "target_id": member.target_id,
                    "error_code": error_code,
                },
                refresh_request_id=request_id,
                job_id=job_id,
            )
        )
    return tuple(events)


async def append_cache_target_links_reconciled_events(
    session: AsyncSession,
    *,
    request_id: str,
    job_id: str,
    active_link_counts: Mapping[str, int],
) -> tuple[CacheTargetResultEvent, ...]:
    """captured member별 link snapshot 교체 결과 event를 기록한다."""
    counts = {
        _canonical_uuid(target_id, field="target_id"): int(count)
        for target_id, count in active_link_counts.items()
    }
    if any(count < 0 for count in counts.values()):
        raise ValueError("active_link_count는 음수일 수 없습니다.")
    members = await capture_cache_target_refresh_members(
        session,
        request_id=request_id,
        target_ids=(),
    )
    events: list[CacheTargetResultEvent] = []
    for member in members:
        if member.target_id not in counts:
            continue
        events.append(
            await _append_result_event(
                session,
                member=member,
                event_type="cache_target.links_reconciled",
                payload={
                    "version": "cache-target-event-v1",
                    "request_id": request_id,
                    "job_id": job_id,
                    "status": "reconciled",
                    "target_id": member.target_id,
                    "active_link_count": counts[member.target_id],
                },
                refresh_request_id=request_id,
                job_id=job_id,
            )
        )
    return tuple(events)
