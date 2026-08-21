"""Cache target link/refresh/reconcile 결과를 transaction outbox에 기록한다.

함수는 commit하지 않는다. 호출자는 domain mutation과 event/delivery insert를 같은
``AsyncSession`` transaction에 둔다. source head가 없는 legacy/admin target은 외부
generation 계약에 참여하지 않으므로 event 대상에서 제외한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import text

from kortravelmap.core.cache_target_stream import (
    validate_cache_target_external_system,
    validate_cache_target_key,
)
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.cache_target_stream_repo import lock_stream_row_or_conflict
from kortravelmap.infra.domain_command_repo import canonical_domain_command_fingerprint

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CacheTargetRefreshMember",
    "CacheTargetRefreshProtocolViolation",
    "CacheTargetResultEvent",
    "append_cache_target_links_reconciled_events",
    "append_cache_target_refresh_status_events",
    "assert_cache_target_refresh_members_current",
    "capture_cache_target_refresh_members",
    "capture_cache_target_refresh_members_by_keys",
    "lock_cache_target_result_streams",
    "pinvi_cache_target_refresh_protocol_error",
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


CacheTargetRefreshReason = Literal[
    "epoch_moved",
    "generation_advanced",
    "fingerprint_changed",
    "head_missing",
]


class CacheTargetRefreshProtocolViolation(RuntimeError):
    """PinVi refresh가 source snapshot/restore fence 정본을 벗어났다.

    ``reason``은 호출자가 **무엇이 어긋났는지로 분기**하기 위한 판별값이다. 이 예외 하나가
    서로 다른 네 원인에서 올라오는데, 그중 restore fence 이동(``epoch_moved``)만이 "옛 epoch
    event는 설계상 거부되므로 relay event 없이 끝낸다"는 근거를 갖는다(runbook §5-5).
    generation 전진·fingerprint 변경·head 소멸은 stale tuple에라도 종결 event를 내는 편이
    PinVi 쪽 relay 종결성에 낫다 — 소비자가 요청의 끝을 못 보고 매달리는 것이 더 나쁘다.
    reason 없이 예외 클래스만 보고 삼키면 이 구분이 사라진다(#975 적대 재리뷰 P2-c).
    """

    #: restore fence가 지나가 captured epoch가 stale이다. 옛 epoch event는 거부된다.
    EPOCH_MOVED: Final[CacheTargetRefreshReason] = "epoch_moved"
    #: source generation이 전진했다. 같은 epoch 안이라 stale tuple에도 event를 낼 수 있다.
    GENERATION_ADVANCED: Final[CacheTargetRefreshReason] = "generation_advanced"
    #: source payload fingerprint가 바뀌었다. generation과 같은 취급.
    FINGERPRINT_CHANGED: Final[CacheTargetRefreshReason] = "fingerprint_changed"
    #: captured member가 가리키던 head row 자체가 사라졌다.
    HEAD_MISSING: Final[CacheTargetRefreshReason] = "head_missing"

    def __init__(self, message: str, reason: CacheTargetRefreshReason) -> None:
        # reason을 위치 인자로 받아 `args`에 담는다 — keyword-only로 두면 `BaseException`의
        # 기본 `__reduce__`가 `args`만으로 재구성하지 못해 pickle/copy 왕복이 깨진다
        # (적대 리뷰 P3, 실측). 예외는 프로세스 경계를 넘을 수 있어야 한다.
        super().__init__(message, reason)
        self.reason: CacheTargetRefreshReason = reason


_PINVI_CACHE_TARGET_SYSTEM = "pinvi"


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
  AND head.external_system = ANY(CAST(:external_systems AS text[]))
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

_SELECT_REFRESH_MEMBER_SYSTEMS_SQL = """
SELECT DISTINCT head.external_system
FROM ops.poi_cache_target_source_heads AS head
JOIN ops.poi_cache_targets AS target
  ON target.target_id = head.target_id
WHERE head.state = 'active'
  AND head.target_id::text = ANY(CAST(:target_ids AS text[]))
  AND target.deleted_at IS NULL
"""

_SELECT_REFRESH_KEY_SYSTEMS_SQL = """
SELECT DISTINCT head.external_system
FROM ops.poi_cache_target_source_heads AS head
JOIN ops.poi_cache_targets AS target
  ON target.target_id = head.target_id
WHERE head.external_system = :external_system
  AND head.target_key = ANY(CAST(:target_keys AS text[]))
  AND head.state = 'active'
  AND target.deleted_at IS NULL
  AND target.update_enabled
  AND target.refresh_policy <> 'disabled'
"""

_LOCK_RESULT_STREAMS_SQL = """
SELECT stream.external_system
FROM ops.poi_cache_target_streams AS stream
WHERE stream.external_system = ANY(CAST(:external_systems AS text[]))
ORDER BY stream.external_system COLLATE "C"
FOR UPDATE OF stream
"""

_SELECT_REQUEST_MEMBER_SYSTEMS_SQL = """
SELECT DISTINCT member.external_system
FROM ops.poi_cache_target_refresh_members AS member
WHERE member.request_id = CAST(:request_id AS uuid)
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

_SELECT_PINVI_REFRESH_PROTOCOL_SQL = """
SELECT member.target_key, member.restore_epoch, stream.restore_epoch AS stream_restore_epoch
FROM ops.poi_cache_target_refresh_members AS member
JOIN ops.poi_cache_target_streams AS stream
  ON stream.external_system = member.external_system
WHERE member.request_id = CAST(:request_id AS uuid)
  AND member.external_system = :external_system
ORDER BY member.target_key COLLATE "C", member.target_id
"""

_LOCK_HEAD_SQL = """
SELECT restore_epoch, source_generation, source_payload_fingerprint, target_sequence
FROM ops.poi_cache_target_source_heads
WHERE external_system = :external_system
  AND target_key = :target_key
FOR UPDATE
"""

_GET_LOCKED_STREAM_RESTORE_EPOCH_SQL = """
SELECT restore_epoch
FROM ops.poi_cache_target_streams
WHERE external_system = :external_system
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
    event_id, event_type, event_scope, external_system, target_key, target_id,
    restore_epoch, source_generation, target_sequence,
    source_payload_fingerprint, payload_fingerprint, payload,
    refresh_request_id, job_id, domain_command_id,
    reconciliation_request_id
) VALUES (
    CAST(:event_id AS uuid), :event_type, 'target', :external_system, :target_key,
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


async def _lock_result_streams(
    session: AsyncSession,
    *,
    external_systems: Sequence[str],
) -> None:
    systems = tuple(sorted(set(external_systems), key=lambda value: value.encode()))
    if not systems:
        return
    # build barrier가 같은 row를 `FOR SHARE OF stream`으로 예산 전 구간 쥔다. 여기서
    # 무한 대기하면 connection을 문 채 쌓이고 전 endpoint 공유 pool이 마른다 —
    # `lock_cache_target_stream` 경로만 고치면 이 경로로 같은 일이 그대로 일어난다.
    locked = (
        (
            await lock_stream_row_or_conflict(
                session,
                _LOCK_RESULT_STREAMS_SQL,
                {"external_systems": list(systems)},
            )
        )
        .scalars()
        .all()
    )
    if len(locked) != len(systems):
        raise RuntimeError("captured cache target stream이 사라졌습니다.")


async def lock_cache_target_result_streams(
    session: AsyncSession,
    *,
    request_id: str,
) -> None:
    """result mutation 전에 request member stream을 C-order로 선취한다."""
    request_id = _canonical_uuid(request_id, field="request_id")
    systems = (
        (
            await session.execute(
                text(_SELECT_REQUEST_MEMBER_SYSTEMS_SQL),
                {"request_id": request_id},
            )
        )
        .scalars()
        .all()
    )
    await _lock_result_streams(
        session,
        external_systems=tuple(str(value) for value in systems),
    )


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
        systems = (
            (
                await session.execute(
                    text(_SELECT_REFRESH_MEMBER_SYSTEMS_SQL),
                    {"target_ids": list(canonical_target_ids)},
                )
            )
            .scalars()
            .all()
        )
        locked_systems = tuple(str(value) for value in systems)
        if locked_systems:
            await _lock_result_streams(
                session,
                external_systems=locked_systems,
            )
            await session.execute(
                text(_CAPTURE_REFRESH_MEMBERS_SQL),
                {
                    "request_id": request_id,
                    "target_ids": list(canonical_target_ids),
                    "external_systems": list(locked_systems),
                },
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
    validate_cache_target_external_system(external_system)
    canonical_keys = tuple(sorted(set(target_keys)))
    for target_key in canonical_keys:
        validate_cache_target_key(target_key)
    if canonical_keys:
        systems = (
            (
                await session.execute(
                    text(_SELECT_REFRESH_KEY_SYSTEMS_SQL),
                    {
                        "external_system": external_system,
                        "target_keys": list(canonical_keys),
                    },
                )
            )
            .scalars()
            .all()
        )
        if systems:
            await _lock_result_streams(
                session,
                external_systems=(external_system,),
            )
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


async def assert_cache_target_refresh_members_current(
    session: AsyncSession,
    *,
    request_id: str,
) -> tuple[CacheTargetRefreshMember, ...]:
    """captured member가 아직 current source head와 같은지 stream→head 순서로 검증한다.

    refresh 실행 도중 source writer가 다음 generation을 커밋하면, 이전 snapshot으로
    link/freshness를 확정해서는 안 된다. 이 함수가 잡은 stream/head lock은 호출
    transaction 끝까지 유지되므로, 성공 뒤의 target/link mutation과 result event는
    같은 source tuple에 결박된다. 상태 이력(``queued``/``running``/``cancelled``)은
    captured tuple의 사실 기록이므로 여기서 검증하지 않는다.
    """

    await lock_cache_target_result_streams(session, request_id=request_id)
    members = await capture_cache_target_refresh_members(
        session,
        request_id=request_id,
        target_ids=(),
    )
    for member in members:
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
            raise CacheTargetRefreshProtocolViolation(
                "captured cache target refresh member의 source head가 사라졌습니다.",
                CacheTargetRefreshProtocolViolation.HEAD_MISSING,
            )
        values = head._mapping
        if int(values["restore_epoch"]) != member.restore_epoch:
            raise CacheTargetRefreshProtocolViolation(
                "captured cache target refresh member의 restore epoch가 현재 head와 다릅니다.",
                CacheTargetRefreshProtocolViolation.EPOCH_MOVED,
            )
        if int(values["source_generation"]) != member.source_generation:
            raise CacheTargetRefreshProtocolViolation(
                "captured cache target refresh member의 source generation이 전진했습니다.",
                CacheTargetRefreshProtocolViolation.GENERATION_ADVANCED,
            )
        if (
            str(values["source_payload_fingerprint"])
            != member.source_payload_fingerprint
        ):
            raise CacheTargetRefreshProtocolViolation(
                "captured cache target refresh member의 source fingerprint가 바뀌었습니다.",
                CacheTargetRefreshProtocolViolation.FINGERPRINT_CHANGED,
            )
    return members


async def pinvi_cache_target_refresh_protocol_error(
    session: AsyncSession,
    *,
    request_id: str,
    external_system: str,
    target_keys: Sequence[str],
) -> str | None:
    """PinVi queued refresh가 service snapshot과 현 restore epoch를 지키는지 확인한다.

    일반 writer로 과거에 영속된 PinVi request는 member가 없으므로 실행 전에 terminal
    fail-close한다. 이 검사는 stream ``FOR UPDATE``를 같은 transaction 끝까지 유지해
    fence와 status event append 사이에 epoch가 바뀌지 않게 한다.
    """

    if external_system != _PINVI_CACHE_TARGET_SYSTEM:
        return None
    request_id = _canonical_uuid(request_id, field="request_id")
    canonical_keys = tuple(sorted(set(target_keys)))
    for target_key in canonical_keys:
        validate_cache_target_key(target_key)
    locked_streams = (
        (
            await session.execute(
                text(_LOCK_RESULT_STREAMS_SQL),
                {"external_systems": [external_system]},
            )
        )
        .scalars()
        .all()
    )
    if len(locked_streams) != 1:
        return "PinVi refresh request에 cache target stream이 없습니다."
    rows = (
        await session.execute(
            text(_SELECT_PINVI_REFRESH_PROTOCOL_SQL),
            {"request_id": request_id, "external_system": external_system},
        )
    ).all()
    if not rows:
        return "PinVi refresh request에 ServiceToken source snapshot member가 없습니다."
    member_keys = tuple(str(row._mapping["target_key"]) for row in rows)
    if member_keys != canonical_keys:
        return "PinVi refresh request의 source snapshot member가 요청 target key와 다릅니다."
    if any(
        int(row._mapping["restore_epoch"]) != int(row._mapping["stream_restore_epoch"])
        for row in rows
    ):
        return "PinVi refresh request의 source snapshot restore epoch가 현재 stream과 다릅니다."
    return None


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
    await _lock_result_streams(
        session,
        external_systems=(member.external_system,),
    )
    stream_restore_epoch = await session.scalar(
        text(_GET_LOCKED_STREAM_RESTORE_EPOCH_SQL),
        {"external_system": member.external_system},
    )
    if stream_restore_epoch is None:
        raise RuntimeError("captured cache target stream이 사라졌습니다.")
    if int(stream_restore_epoch) != member.restore_epoch:
        raise CacheTargetRefreshProtocolViolation(
            "captured cache target refresh member의 restore epoch가 현재 stream과 다릅니다.",
            CacheTargetRefreshProtocolViolation.EPOCH_MOVED,
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
    await lock_cache_target_result_streams(
        session,
        request_id=request_id,
    )
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
    await lock_cache_target_result_streams(
        session,
        request_id=request_id,
    )
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
