"""원 counter를 보존하며 후처리 효과와 receipt를 한 transaction에 commit한다."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from kortravelmap.infra.provider_snapshot_postprocess_repo import (
    begin_provider_snapshot_postprocess,
    finish_provider_snapshot_postprocess,
)
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotExecutorToken
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient


class _SnapshotConnectionGuard:
    def connect(self) -> None:
        raise RuntimeError("snapshot postprocess must keep its original connection")


async def run_snapshot_postprocess(
    client: AsyncKorTravelMapClient,
    token: SnapshotExecutorToken,
    receipt_candidate: bytes,
    work: Callable[[AsyncKorTravelMapClient], Awaitable[None]],
) -> bytes:
    """전용 RC TX. 기존 client의 내부 commit은 rollback_only로 바깥 TX에 결합한다."""
    if client._transaction_bound:  # noqa: SLF001
        raise RuntimeError("snapshot postprocess requires its own transaction")
    if type(receipt_candidate) is not bytes or not 1 <= len(receipt_candidate) <= 4096:
        raise ValueError("bounded postprocess receipt candidate required")
    async with asyncio.timeout(30):
        async with client._session_factory() as session, session.begin():  # noqa: SLF001
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            await apply_bounded_transaction_limits(session)
            existing = await begin_provider_snapshot_postprocess(session, token, receipt_candidate)
            if existing is not None:
                return existing
            connection = await session.connection()
            bound = copy.copy(client)
            bound._session_factory = async_sessionmaker(  # noqa: SLF001
                bind=connection,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                join_transaction_mode="rollback_only",
            )
            bound._engine = cast("AsyncEngine", _SnapshotConnectionGuard())  # noqa: SLF001
            bound._transaction_bound = True  # noqa: SLF001
            await work(bound)
            await finish_provider_snapshot_postprocess(session, token, receipt_candidate)
        # commit 응답이 불명확하면 여기까지 오지 않는다. caller는 SDK0 member read로 확인한다.
    return receipt_candidate
