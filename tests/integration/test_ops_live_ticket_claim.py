"""ops-live WebSocket ticket nonce 원자 소비 통합 테스트."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.ops_live_auth import OpsLiveTicketContext, claim_ops_live_ticket

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def test_ops_live_ticket_nonce_is_claimed_once_under_concurrency(
    migrated_engine: AsyncEngine,
) -> None:
    nonce = f"c7a-{uuid4().hex}"
    nonce_hash = hashlib.sha256(nonce.encode("ascii")).digest()
    expired_nonce_hash = hashlib.sha256(
        f"expired-{uuid4().hex}".encode("ascii")
    ).digest()
    grace_nonce_hash = hashlib.sha256(
        f"grace-{uuid4().hex}".encode("ascii")
    ).digest()
    context = OpsLiveTicketContext(
        actor="integration-admin",
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=60),
        nonce=nonce,
        subprotocol="ktm.ops-live.v1.integration",
    )

    async def _claim() -> bool:
        async with AsyncSession(migrated_engine) as session:
            return await claim_ops_live_ticket(session, context)

    try:
        async with AsyncSession(migrated_engine) as seed_session:
            await seed_session.execute(
                text(
                    "INSERT INTO ops.ops_live_ticket_claims "
                    "(nonce_hash, actor, expires_at) "
                    "VALUES "
                    "(:expired_nonce_hash, 'expired-admin', :expired_at), "
                    "(:grace_nonce_hash, 'grace-admin', :grace_at)"
                ),
                {
                    "expired_at": datetime.now(tz=UTC) - timedelta(seconds=61),
                    "expired_nonce_hash": expired_nonce_hash,
                    "grace_at": datetime.now(tz=UTC) - timedelta(seconds=30),
                    "grace_nonce_hash": grace_nonce_hash,
                },
            )
            await seed_session.commit()
        results = await asyncio.wait_for(
            asyncio.gather(_claim(), _claim()),
            timeout=5,
        )

        assert sorted(results) == [False, True]
        assert await _claim() is False
        async with AsyncSession(migrated_engine) as session:
            count = await session.scalar(
                text(
                    "SELECT COUNT(*) FROM ops.ops_live_ticket_claims "
                    "WHERE nonce_hash = :nonce_hash"
                ),
                {"nonce_hash": nonce_hash},
            )
            expired_count = await session.scalar(
                text(
                    "SELECT COUNT(*) FROM ops.ops_live_ticket_claims "
                    "WHERE nonce_hash = :nonce_hash"
                ),
                {"nonce_hash": expired_nonce_hash},
            )
            grace_count = await session.scalar(
                text(
                    "SELECT COUNT(*) FROM ops.ops_live_ticket_claims "
                    "WHERE nonce_hash = :nonce_hash"
                ),
                {"nonce_hash": grace_nonce_hash},
            )
        assert count == 1
        assert expired_count == 0
        assert grace_count == 1
    finally:
        async with AsyncSession(migrated_engine) as cleanup_session:
            await cleanup_session.execute(
                text(
                    "DELETE FROM ops.ops_live_ticket_claims "
                    "WHERE nonce_hash IN "
                    "(:nonce_hash, :expired_nonce_hash, :grace_nonce_hash)"
                ),
                {
                    "expired_nonce_hash": expired_nonce_hash,
                    "grace_nonce_hash": grace_nonce_hash,
                    "nonce_hash": nonce_hash,
                },
            )
            await cleanup_session.commit()
