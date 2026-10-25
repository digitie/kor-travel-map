"""동일 후처리 TX의 private SD 진입·완료. SDK나 transaction을 소유하지 않는다."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.infra.provider_snapshot_recovery_repo import (
    SnapshotExecutorToken,
    SnapshotRecoveryCorruption,
    _token_params,
    _transaction,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ProviderSnapshotSuperseded(RuntimeError):
    """새 적용/관측이 앞섰다. 원 run을 무한 재시도하거나 새 성공으로 바꾸지 않는다."""


def _receipt(raw: bytes) -> None:
    if type(raw) is not bytes or not 1 <= len(raw) <= 4096:
        raise SnapshotRecoveryCorruption("bounded postprocess receipt bytes required")


def _superseded(exc: DBAPIError) -> bool:
    return (
        getattr(exc.orig, "sqlstate", None) == "55000"
        and getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        == "ck_provider_snapshot_superseded"
    )


async def begin_provider_snapshot_postprocess(
    session: AsyncSession, token: SnapshotExecutorToken, receipt: bytes
) -> bytes | None:
    """None이면 같은 TX 후처리가 필요하다. 이미 완료면 원 receipt를 반환한다."""
    _transaction(session)
    _receipt(receipt)
    params = {**_token_params(token), "receipt": receipt}
    try:
        value = await session.scalar(
            text(
                "SELECT ops.begin_provider_snapshot_postprocess"
                "(:snapshot,:generation,:fence,:receipt)"
            ),
            params,
        )
    except DBAPIError as exc:
        if _superseded(exc):
            raise ProviderSnapshotSuperseded("snapshot was superseded before postprocess") from None
        raise
    if value is not None and (type(value) is not bytes or value != receipt):
        raise SnapshotRecoveryCorruption("saved postprocess receipt differs from original intent")
    return value


async def finish_provider_snapshot_postprocess(
    session: AsyncSession, token: SnapshotExecutorToken, receipt: bytes
) -> None:
    _transaction(session)
    _receipt(receipt)
    await session.execute(
        text(
            "SELECT ops.finish_provider_snapshot_postprocess(:snapshot,:generation,:fence,:receipt)"
        ),
        {**_token_params(token), "receipt": receipt},
    )
