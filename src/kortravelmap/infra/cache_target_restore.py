"""Map restore swap 직전 cache-target stream epoch barrier 조정.

복원 DB가 live DB보다 오래된 restore epoch을 가진 경우에는 cutover를 거부한다.
허용된 복원본은 기존 ``advance_cache_target_restore_fence`` 도메인 함수로만
전진시키며, host restore command 재시도는 같은 domain command/fence receipt를
재생한다. 함수는 commit하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

from sqlalchemy import text

from kortravelmap.infra.cache_target_stream_repo import (
    CacheTargetRestoreFenceResult,
    CacheTargetStreamConflict,
    advance_cache_target_restore_fence,
)
from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
    get_domain_command_claim,
    lock_domain_command,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CacheTargetRestoreReference",
    "fence_restored_cache_target_streams",
    "list_cache_target_restore_references",
]

_RESTORE_COMMAND_NAMESPACE = UUID("c5a66adb-4271-49d2-8b65-685f6c51d84b")
_RESTORE_ACTOR = "system:map-restore-swap"
_RESTORE_OPERATION = "cache_target.restore_fence"
_RESTORE_REASON = "Map restore swap cutover"

_LIST_STREAMS_SQL = """
SELECT external_system, consumer_id, restore_epoch, control_version
FROM ops.poi_cache_target_streams
ORDER BY external_system
"""

_GET_FENCE_RECEIPT_SQL = """
SELECT request_fingerprint
FROM ops.poi_cache_target_restore_fences
WHERE command_id = :command_id
"""


@dataclass(frozen=True, slots=True)
class CacheTargetRestoreReference:
    """Cutover 직전 DB에서 읽은 stream 단조성 기준."""

    external_system: str
    consumer_id: str
    restore_epoch: int
    control_version: int


def _reference(row: Any) -> CacheTargetRestoreReference:
    values = row._mapping
    return CacheTargetRestoreReference(
        external_system=str(values["external_system"]),
        consumer_id=str(values["consumer_id"]),
        restore_epoch=int(values["restore_epoch"]),
        control_version=int(values["control_version"]),
    )


async def list_cache_target_restore_references(
    session: AsyncSession,
) -> tuple[CacheTargetRestoreReference, ...]:
    """DB의 cache-target stream control을 고정된 순서로 읽는다."""

    rows = (await session.execute(text(_LIST_STREAMS_SQL))).all()
    return tuple(_reference(row) for row in rows)


def _command_key(host_command_id: int, external_system: str) -> str:
    return str(
        uuid5(
            _RESTORE_COMMAND_NAMESPACE,
            f"{host_command_id}:{external_system}",
        )
    )


async def fence_restored_cache_target_streams(
    session: AsyncSession,
    *,
    live_references: tuple[CacheTargetRestoreReference, ...],
    host_command_id: int,
    host_input_digest: str,
) -> tuple[CacheTargetRestoreFenceResult, ...]:
    """복원 DB의 모든 stream을 외부 노출 전에 fence한다.

    live에만 있는 stream도 복원 DB에 fenced control로 다시 만든다. 단, 복원본에
    같은 stream이 있으면서 epoch이 live보다 낮거나 consumer binding이 다르면
    안전한 단조성 증거가 없으므로 전체 transaction을 거부한다.
    """

    if host_command_id <= 0:
        raise ValueError("host_command_id는 양의 정수여야 합니다.")
    if (
        len(host_input_digest) != 64
        or any(character not in "0123456789abcdef" for character in host_input_digest)
    ):
        raise ValueError("host_input_digest는 lowercase SHA-256 hex여야 합니다.")

    live_by_system = {item.external_system: item for item in live_references}
    if len(live_by_system) != len(live_references):
        raise ValueError("live_references에 external_system 중복이 있습니다.")
    restored_references = await list_cache_target_restore_references(session)
    restored_by_system = {
        item.external_system: item for item in restored_references
    }
    systems = sorted(live_by_system.keys() | restored_by_system.keys())
    results: list[CacheTargetRestoreFenceResult] = []

    for external_system in systems:
        live = live_by_system.get(external_system)
        restored = restored_by_system.get(external_system)
        if live is not None:
            consumer_id = live.consumer_id
        else:
            assert restored is not None
            consumer_id = restored.consumer_id
        command_key = _command_key(host_command_id, external_system)
        await lock_domain_command(
            session,
            actor=_RESTORE_ACTOR,
            operation=_RESTORE_OPERATION,
            idempotency_key=command_key,
        )
        existing_claim = await get_domain_command_claim(
            session,
            actor=_RESTORE_ACTOR,
            operation=_RESTORE_OPERATION,
            idempotency_key=command_key,
        )
        if existing_claim is not None:
            receipt = (
                await session.execute(
                    text(_GET_FENCE_RECEIPT_SQL),
                    {"command_id": existing_claim.command_id},
                )
            ).one_or_none()
            if receipt is None:
                raise CacheTargetStreamConflict(
                    "restore_fence_incomplete_command",
                    "restore command claim에 대응하는 fence receipt가 없습니다.",
                )
            results.append(
                await advance_cache_target_restore_fence(
                    session,
                    external_system=external_system,
                    consumer_id=consumer_id,
                    command_id=existing_claim.command_id,
                    expected_restore_epoch=(
                        restored.restore_epoch if restored is not None else 1
                    ),
                    expected_control_version=(
                        restored.control_version if restored is not None else 1
                    ),
                    reason=_RESTORE_REASON,
                    request_fingerprint=str(receipt._mapping["request_fingerprint"]),
                )
            )
            continue

        if live is not None and restored is not None:
            if live.consumer_id != restored.consumer_id:
                raise CacheTargetStreamConflict(
                    "restore_consumer_mismatch",
                    "live와 복원 DB의 consumer binding이 다릅니다.",
                    current={
                        "external_system": external_system,
                        "live_consumer_id": live.consumer_id,
                        "restored_consumer_id": restored.consumer_id,
                    },
                )
            if restored.restore_epoch < live.restore_epoch:
                raise CacheTargetStreamConflict(
                    "restore_epoch_regression",
                    "복원 DB의 restore epoch이 live DB보다 낮습니다.",
                    current={
                        "external_system": external_system,
                        "live_restore_epoch": live.restore_epoch,
                        "restored_restore_epoch": restored.restore_epoch,
                    },
                )
        elif live is not None and live.restore_epoch > 1:
            raise CacheTargetStreamConflict(
                "restore_epoch_regression",
                "복원 DB에 stream이 없고 live restore epoch이 초기값보다 높습니다.",
                current={
                    "external_system": external_system,
                    "live_restore_epoch": live.restore_epoch,
                    "restored_restore_epoch": None,
                },
            )

        expected_restore_epoch = restored.restore_epoch if restored is not None else 1
        expected_control_version = (
            restored.control_version if restored is not None else 1
        )
        request = {
            "version": "map-restore-swap-fence-v1",
            "host_command_id": host_command_id,
            "host_input_digest": host_input_digest,
            "external_system": external_system,
            "consumer_id": consumer_id,
            "expected_restore_epoch": expected_restore_epoch,
            "expected_control_version": expected_control_version,
            "reason": _RESTORE_REASON,
        }
        fingerprint = canonical_domain_command_fingerprint(request)
        claim = await create_domain_command_claim(
            session,
            actor=_RESTORE_ACTOR,
            operation=_RESTORE_OPERATION,
            idempotency_key=command_key,
            request_fingerprint=fingerprint,
        )
        results.append(
            await advance_cache_target_restore_fence(
                session,
                external_system=external_system,
                consumer_id=consumer_id,
                command_id=claim.command_id,
                expected_restore_epoch=expected_restore_epoch,
                expected_control_version=expected_control_version,
                reason=_RESTORE_REASON,
                request_fingerprint=fingerprint,
            )
        )

    return tuple(results)
