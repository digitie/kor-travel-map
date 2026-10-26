"""저장 적용·원 결과·필수 후처리를 한 connection/TX에 결합한다."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text

from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorToken,
    SnapshotMember,
    SnapshotRecoveryCorruption,
    read_provider_snapshot_for_member,
)
from kortravelmap.infra.provider_snapshot_result import SnapshotApplyResult
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits

from ._snapshot_postprocess import run_snapshot_postprocess_in_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.client import AsyncKorTravelMapClient


@dataclass(frozen=True)
class SnapshotPostprocessWork:
    """저장된 원 bytes만으로 준비한 내부 작업이다. 외부 IO/별도 commit을 넣지 않는다."""

    receipt_candidate: bytes
    work: Callable[[AsyncKorTravelMapClient], Awaitable[None]]


@dataclass(frozen=True)
class SnapshotAtomicCompletion:
    result: SnapshotApplyResult
    receipt: bytes


async def run_snapshot_apply_postprocess(
    client: AsyncKorTravelMapClient,
    observed: RecoveredProviderSnapshot,
    token: SnapshotExecutorToken,
    member: SnapshotMember,
    *,
    pins: SnapshotArtifactPins,
    apply: Callable[[AsyncSession], Awaitable[SnapshotApplyResult]],
    prepare: Callable[[RecoveredProviderSnapshot], SnapshotPostprocessWork],
) -> SnapshotAtomicCompletion:
    """commit 응답 유실은 전파한다. 새 시도는 SDK0 read로 확인하며 자동 재적용하지 않는다.

    registration/claim/planning은 호출 전에 끝낸다. control child/root seal은 이 commit
    뒤 기존 별도 P_EX 경로에 맡긴다. SQL의 현재 fence와 원 입력 검증을 생략하지 않는다.
    """
    if client._transaction_bound is not False:  # noqa: SLF001
        raise RuntimeError("snapshot apply/postprocess requires its own transaction")
    if observed.status != "prepared" or token.snapshot_id != observed.snapshot_id:
        raise SnapshotRecoveryCorruption("exact prepared snapshot required for atomic apply")
    async with asyncio.timeout(30):
        async with client._session_factory() as session, session.begin():  # noqa: SLF001
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            await apply_bounded_transaction_limits(session)
            result = await apply(session)
            # 다른 session은 미commit 결과를 읽지 못한다. 같은 물리 connection에서만 읽는다.
            fresh = await read_provider_snapshot_for_member(session, member, expected_pins=pins)
            if (
                fresh is None
                or fresh.snapshot_id != token.snapshot_id
                or fresh.artifact_sha256 != observed.artifact_sha256
                or fresh.context_sha256 != observed.context_sha256
                or fresh.status != "applied"
                or fresh.applied_result != result
                or fresh.applied_result_bytes is None
                or fresh.postprocess_receipt is not None
                or fresh.root_status != "running"
                or fresh.child_status != "running"
                or fresh.cancellation_present
            ):
                raise SnapshotRecoveryCorruption("atomic apply did not retain its original result")
            prepared = prepare(fresh)
            if type(prepared) is not SnapshotPostprocessWork:
                raise SnapshotRecoveryCorruption("canonical postprocess work required")
            receipt = await run_snapshot_postprocess_in_session(
                client, session, token, prepared.receipt_candidate, prepared.work
            )
        # 이 위치는 outer commit 성공 응답 이후에만 도달한다.
    return SnapshotAtomicCompletion(result, receipt)
