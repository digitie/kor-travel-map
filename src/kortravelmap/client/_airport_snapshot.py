"""Airport snapshot의 작은 client TX 경계. SDK·Dagster·공유 client 배선은 없다."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text

from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorLease,
    SnapshotExecutorToken,
    SnapshotMember,
    SnapshotMemberSeal,
    SnapshotRegistration,
    _member_params,
    claim_provider_snapshot_executor,
    read_provider_snapshot_for_member,
    register_provider_snapshot_artifact,
    seal_provider_snapshot_member,
)
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.client import AsyncKorTravelMapClient

LEASE_SECONDS = 300


class AirportSnapshotUnavailable(ValueError):
    """기존 executor에 결합된 client는 새 독립 TX를 시작할 수 없다."""


def _unbound(client: AsyncKorTravelMapClient) -> None:
    if client._transaction_bound is not False:
        raise AirportSnapshotUnavailable("airport snapshot requires the original unbound client")


@asynccontextmanager
async def _transaction(
    client: AsyncKorTravelMapClient, *, readonly: bool = False, repeatable: bool = False
) -> AsyncIterator[AsyncSession]:
    _unbound(client)
    async with asyncio.timeout(30):
        async with client._session_factory() as session, session.begin():
            if repeatable and not readonly:
                raise ValueError("airport planning snapshot must be read only")
            mode = "REPEATABLE READ" if repeatable else "READ COMMITTED"
            access = "READ ONLY" if readonly else "READ WRITE"
            await session.execute(text(f"SET TRANSACTION ISOLATION LEVEL {mode}, {access}"))
            await apply_bounded_transaction_limits(
                session, statement_timeout_ms=3000 if repeatable else 30000
            )
            yield session


async def read_airport_snapshot(
    client: AsyncKorTravelMapClient, member: SnapshotMember, *, pins: SnapshotArtifactPins | None
) -> RecoveredProviderSnapshot | None:
    """SDK보다 먼저 동일 statement의 원 입력/결과를 읽는다. 부재만 None이다."""
    async with _transaction(client, readonly=True) as session:
        if pins is None:
            present = await session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM ops.read_provider_snapshot_for_member("
                    ":root,:child,:member))"
                ),
                _member_params(member),
            )
            if type(present) is not bool or present:
                raise AirportSnapshotUnavailable(
                    "registered snapshot requires verified runtime pins"
                )
            return None
        return await read_provider_snapshot_for_member(session, member, expected_pins=pins)


async def register_airport_snapshot(
    client: AsyncKorTravelMapClient,
    member: SnapshotMember,
    *,
    payload: bytes,
    context: bytes,
    pins: SnapshotArtifactPins,
) -> SnapshotRegistration:
    """입력·원 관측을 한 번 등록한다. commit 응답 유실을 성공으로 추측하지 않는다."""
    async with _transaction(client) as session:
        return await register_provider_snapshot_artifact(
            session,
            member,
            artifact_payload=payload,
            observation_context=context,
            expected_pins=pins,
            lease_seconds=LEASE_SECONDS,
        )


async def claim_airport_snapshot(
    client: AsyncKorTravelMapClient,
    observed: RecoveredProviderSnapshot,
    *,
    previous: SnapshotExecutorToken | None = None,
) -> SnapshotExecutorLease:
    """DB의 실제 fence만 전달한다. read의 lease 시각으로 유효성을 판단하지 않는다."""
    async with _transaction(client) as session:
        return await claim_provider_snapshot_executor(
            session,
            observed.snapshot_id,
            artifact_sha256=observed.artifact_sha256,
            context_sha256=observed.context_sha256,
            lease_seconds=LEASE_SECONDS,
            previous=previous,
        )


async def seal_airport_snapshot(
    client: AsyncKorTravelMapClient,
    token: SnapshotExecutorToken,
    *,
    artifact_sha256: str,
    context_sha256: str,
    result_sha256: str,
    postprocess_sha256: str,
) -> SnapshotMemberSeal:
    """private marker·old seal/finish·control 전이를 원자 wrapper 한 번에 맡긴다."""
    async with _transaction(client) as session:
        return await seal_provider_snapshot_member(
            session,
            token,
            artifact_sha256=artifact_sha256,
            context_sha256=context_sha256,
            result_sha256=result_sha256,
            postprocess_sha256=postprocess_sha256,
        )
