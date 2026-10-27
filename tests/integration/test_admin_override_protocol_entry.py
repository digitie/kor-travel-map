"""전화/주소 override의 첫 행 잠금 전 진입과 caller TX 수명을 실제 PG로 검증한다.

433 DC-1: 주소 override는 단건 regime 진입(epoch>0에서만 P EX)이다 — 이 모듈은 정책을 활성화하지
않으므로 epoch=0에서 P 없이 행 잠금만 기다린다. 전화 override는 같은 transaction에서 source
record/link를 쓰는 enrichment 경로라 적재 fence(P EX)를 그대로 먼저 잡는다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.feature_address_repo import apply_feature_address_override
from kortravelmap.infra.feature_repo import set_feature_phones
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]


async def _seed(admin: Any) -> UUID:
    feature = uuid4()
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("""INSERT INTO feature.features(feature_id,kind,name,category)
                VALUES(:feature,'place','override fixture','01010100')"""),
            {"feature": feature},
        )
        await session.execute(
            text("""INSERT INTO feature.feature_places(feature_id,kind,place_kind,phones)
                VALUES(:feature,'place','tourism',ARRAY[]::text[])"""),
            {"feature": feature},
        )
    return feature


async def _apply(kind: str, session: AsyncSession, feature: UUID) -> None:
    if kind == "phones":
        assert await set_feature_phones(session, str(feature), ["02-1234-5678"])
    else:
        result = await apply_feature_address_override(
            session,
            str(feature),
            address={"road": "fixture address"},
            operator="admin:fixture",
            reason="fixture",
        )
        assert result is not None
        assert result.snapshot.address == {"road": "fixture address"}


async def _state(admin: Any, feature: UUID) -> str:
    async with AsyncSession(admin) as session:
        value = await session.scalar(
            text("""SELECT jsonb_build_object(
                'core',(SELECT to_jsonb(f) FROM feature.features f WHERE feature_id=:feature),
                'place',(SELECT to_jsonb(p) FROM feature.feature_places p
                    WHERE feature_id=:feature),
                'overrides',(SELECT jsonb_agg(to_jsonb(o) ORDER BY to_jsonb(o)::text COLLATE "C")
                    FROM ops.feature_overrides o WHERE feature_id=:feature),
                'claims',(SELECT count(*) FROM ops.domain_commands),
                'results',(SELECT count(*) FROM ops.domain_command_results))"""),
            {"feature": feature},
        )
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def _wait_protocol_blocker(admin: Any, waiter: int, blocker: int) -> None:
    async with asyncio.timeout(3):
        while True:
            async with AsyncSession(admin) as observer:
                blocked = await observer.scalar(
                    text("""SELECT EXISTS(SELECT 1 FROM pg_locks
                        WHERE pid=:waiter AND locktype='advisory'
                        AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
                        AND mode='ExclusiveLock' AND NOT granted)
                        AND :blocker=ANY(pg_blocking_pids(:waiter))"""),
                    {"waiter": waiter, "blocker": blocker},
                )
            if blocked:
                return
            await asyncio.sleep(0.01)


async def _wait_row_blocker_without_protocol(
    admin: Any, waiter: int, blocker: int, task: asyncio.Task[Any]
) -> None:
    """433 DC-1(epoch=0): 단건 writer는 P를 요청하지 않고 실제 행 잠금에서만 기다린다."""
    async with asyncio.timeout(3):
        while True:
            if task.done():
                task.result()
                raise AssertionError("writer finished before waiting on the held row")
            async with AsyncSession(admin) as observer:
                row = (
                    await observer.execute(
                        text("""SELECT :blocker=ANY(pg_blocking_pids(:waiter)),
                        EXISTS(SELECT 1 FROM pg_locks WHERE pid=:waiter
                        AND locktype='advisory' AND classid=1369104691::oid
                        AND objid=115::oid AND objsubid=2)"""),
                        {"waiter": waiter, "blocker": blocker},
                    )
                ).one()
            if row[0]:
                assert row[1] is False, "epoch=0 single writer requested the protocol gate"
                return
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("kind", ["phones", "address"])
@pytest.mark.parametrize("same_feature", [True, False], ids=["same", "independent"])
async def test_override_entry_order_before_any_feature_row_lock(
    scalar_engines: Any,
    kind: str,
    same_feature: bool,
) -> None:
    admin, runtime = scalar_engines
    held = await _seed(admin)
    target = held if same_feature else await _seed(admin)
    writer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def write() -> None:
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='5s'"))
            writer_pid.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            await _apply(kind, session, target)

    task = None
    try:
        async with AsyncSession(admin) as shared, shared.begin():
            blocker = int(await shared.scalar(text("SELECT pg_backend_pid()")))
            await shared.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
            await shared.execute(
                text("SELECT 1 FROM feature.features WHERE feature_id=:feature FOR UPDATE"),
                {"feature": held},
            )
            task = asyncio.create_task(write())
            waiter = await asyncio.wait_for(asyncio.shield(writer_pid), 3)
            if kind == "phones":
                # enrichment fence 경로: 적재처럼 P EX를 행보다 먼저 기다린다.
                await _wait_protocol_blocker(admin, waiter, blocker)
                assert not task.done()
            elif same_feature:
                await _wait_row_blocker_without_protocol(admin, waiter, blocker, task)
            else:
                # 433 DC-1: 다른 Feature의 주소 override는 SH 보유자 뒤에서 기다리지 않는다.
                await asyncio.wait_for(asyncio.shield(task), 3)
            if kind == "phones" and not same_feature:
                # 다른 Feature여도 EX 대기 전에 행을 선점하지 않아야 한다.
                async with AsyncSession(admin) as observer, observer.begin():
                    assert (
                        await observer.scalar(
                            text(
                                "SELECT 1 FROM feature.features WHERE feature_id=:feature "
                                "FOR UPDATE NOWAIT"
                            ),
                            {"feature": target},
                        )
                        == 1
                    )
        await asyncio.wait_for(asyncio.shield(task), 5)
        async with AsyncSession(admin) as observer:
            if kind == "phones":
                assert await observer.scalar(
                    text("SELECT phones FROM feature.feature_places WHERE feature_id=:feature"),
                    {"feature": target},
                ) == ["02-1234-5678"]
            else:
                assert await observer.scalar(
                    text("SELECT address FROM feature.features WHERE feature_id=:feature"),
                    {"feature": target},
                ) == {"road": "fixture address"}
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_phone_fence_upgrade_is_rejected_without_override_writes(
    scalar_engines: Any,
) -> None:
    admin, runtime = scalar_engines
    feature = await _seed(admin)
    before = await _state(admin, feature)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 gate/override 경계
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
            await _apply("phones", session, feature)
    assert caught.value.orig.sqlstate == "23514"
    assert await _state(admin, feature) == before
    # abort/rollback 후 새 TX는 같은 입력을 정상 author할 수 있다.
    async with AsyncSession(runtime) as session, session.begin():
        await _apply("phones", session, feature)


async def test_epoch0_address_override_under_shared_protocol_does_not_upgrade(
    scalar_engines: Any,
) -> None:
    """433 DC-1: epoch=0의 주소 override는 P를 잡지 않으므로 SH 보유 caller에서도 쓴다."""
    admin, runtime = scalar_engines
    feature = await _seed(admin)
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
        await _apply("address", session, feature)
        modes = (
            await session.scalars(
                text("""SELECT mode FROM pg_locks WHERE pid=pg_backend_pid()
                AND locktype='advisory' AND classid=1369104691::oid
                AND objid=115::oid AND objsubid=2 AND granted""")
            )
        ).all()
    assert modes == ["ShareLock"]


@pytest.mark.parametrize("kind", ["phones", "address"])
async def test_caller_rollback_preserves_values_and_command_ledger(
    scalar_engines: Any,
    kind: str,
) -> None:
    admin, runtime = scalar_engines
    feature = await _seed(admin)
    before = await _state(admin, feature)
    async with AsyncSession(runtime) as session:
        await _apply(kind, session, feature)
        await session.rollback()
    assert await _state(admin, feature) == before
    async with AsyncSession(admin) as observer, observer.begin():
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(1369104691,115)"))
        assert await observer.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended('feature-curation-write',0))")
        )
        assert (
            await observer.scalar(
                text("SELECT 1 FROM feature.features WHERE feature_id=:feature FOR UPDATE NOWAIT"),
                {"feature": feature},
            )
            == 1
        )
    async with AsyncSession(runtime) as session, session.begin():
        await _apply(kind, session, feature)
