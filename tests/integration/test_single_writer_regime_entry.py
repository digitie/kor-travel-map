"""433 DC-1: 단건 writer의 regime 진입을 정책 활성화 전후로 실제 PG에서 반증한다.

- epoch=0: 진입은 P를 잡지 않는다(적재가 P EX를 쥐어도 기다리지 않는다).
- 첫 활성화: P EX + 보호 표 ACCESS EXCLUSIVE가 진행 중인 epoch=0 writer를 기다린다(drain).
  진입은 epoch 표를 ACCESS SHARE로 읽으므로, cutover를 기다린 진입은 **잠금 뒤에** 새 snapshot을
  잡아 바뀐 epoch를 읽는다.
- epoch>0: 진입은 P EX다. SH 보유자 뒤에서 기다리고, SH caller 안에서는 승격 거부(23514),
  P 없는 우회 DML은 barrier/strict guard가 23514로 닫는다.

이 모듈의 container는 모듈마다 새로 뜬다. 테스트 순서가 epoch의 세계를 정한다(파일 순서).
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_provider_field_scalar_projection import _activate, _seed
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]
_TRANSITION = """CALL feature.transition_feature_state(
    :feature,'retired','suppressed','valid',:revision,CAST(:context AS jsonb),NULL,NULL)"""
_OWN_PROTOCOL_MODES = """SELECT mode FROM pg_locks WHERE pid=pg_backend_pid()
AND locktype='advisory' AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
AND granted ORDER BY mode"""
_WAITING_ON_PROTOCOL = """SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid
AND locktype='advisory' AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
AND mode='ExclusiveLock' AND NOT granted) AND :blocker=ANY(pg_blocking_pids(:pid))"""


async def _epoch(admin) -> int:
    async with admin.connect() as connection:
        return int(
            await connection.scalar(
                text("SELECT epoch FROM feature.provider_field_policy_epoch WHERE singleton")
            )
        )


async def _writer_target(admin) -> dict[str, object]:
    feature, _datasets, _entities = await _seed(admin)
    async with admin.connect() as connection:
        revision = await connection.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=:id"),
            {"id": UUID(feature)},
        )
    return dict(
        feature=UUID(feature),
        revision=int(revision),
        context=json.dumps(
            dict(transition_kind="system", reason_code="regime-433", principal="admin:regime-433")
        ),
    )


async def _lifecycle(admin, feature: UUID) -> str:
    async with admin.connect() as connection:
        return str(
            await connection.scalar(
                text("SELECT lifecycle_state FROM feature.features WHERE feature_id=:id"),
                {"id": feature},
            )
        )


async def _blocked_by(admin, waiter: int, blocker: int, task: asyncio.Task[object]) -> None:
    async with asyncio.timeout(3):
        while True:
            if task.done():
                task.result()
                raise AssertionError("the call finished before waiting on its blocker")
            async with admin.connect() as observer:
                blocked = await observer.scalar(
                    text("SELECT :blocker=ANY(pg_blocking_pids(:waiter))"),
                    {"blocker": blocker, "waiter": waiter},
                )
            if blocked:
                return
            await asyncio.sleep(0.01)


async def test_epoch0_writer_finishes_while_a_load_holds_protocol_ex(scalar_engines):
    admin, runtime = scalar_engines
    assert await _epoch(admin) == 0
    target = await _writer_target(admin)
    async with AsyncSession(runtime) as holder, holder.begin():
        await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        async with AsyncSession(runtime) as session, session.begin():
            # 종전(415)에는 이 짧은 상한에서 55P03이었다(관리 UI 503).
            await session.execute(text("SET LOCAL lock_timeout='300ms'"))
            await session.execute(text(_TRANSITION), target)
            assert (await session.scalars(text(_OWN_PROTOCOL_MODES))).all() == []
    assert await _lifecycle(admin, target["feature"]) == "retired"


async def test_entry_blocked_by_a_cutover_reads_the_new_epoch(scalar_engines):
    """cutover가 epoch 표를 ACCESS EXCLUSIVE로 쥔 동안 들어온 진입은 그 commit 뒤의 값을 읽는다.

    plpgsql은 문장의 잠금을 먼저 얻고 snapshot을 나중에 잡는다(READ COMMITTED). 그래서 기다린
    진입은 epoch=0을 보고 P 없이 지나가지 않고, 새 epoch를 보고 P EX를 잡는다. 실제 활성화는
    이 표와 데이터 표를 함께 잠그므로 같은 성질을 쓴다. 끝에서 epoch를 0으로 되돌린다(guard는
    설치하지 않았다).
    """
    admin, runtime = scalar_engines
    assert await _epoch(admin) == 0
    target = await _writer_target(admin)
    started = asyncio.get_running_loop().create_future()

    async def write() -> list[str]:
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='5s'"))
            started.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            await session.execute(text(_TRANSITION), target)
            return list((await session.scalars(text(_OWN_PROTOCOL_MODES))).all())

    task = None
    try:
        async with AsyncSession(admin) as cutover:
            await cutover.begin()
            blocker = int(await cutover.scalar(text("SELECT pg_backend_pid()")))
            await cutover.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            await cutover.execute(
                text("LOCK TABLE feature.provider_field_policy_epoch IN ACCESS EXCLUSIVE MODE")
            )
            await cutover.execute(
                text("UPDATE feature.provider_field_policy_epoch SET epoch=epoch+1 WHERE singleton")
            )
            task = asyncio.create_task(write())
            waiter = await asyncio.wait_for(asyncio.shield(started), 3)
            await _blocked_by(admin, waiter, blocker, task)
            await cutover.commit()
        modes = await asyncio.wait_for(asyncio.shield(task), 5)
        assert modes == ["ExclusiveLock"]
        assert await _lifecycle(admin, target["feature"]) == "retired"
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with AsyncSession(admin) as reset, reset.begin():
            await reset.execute(
                text("UPDATE feature.provider_field_policy_epoch SET epoch=0 WHERE singleton")
            )
    assert await _epoch(admin) == 0


async def test_first_activation_drains_an_in_flight_epoch0_writer(scalar_engines):
    admin, runtime = scalar_engines
    assert await _epoch(admin) == 0
    policy_feature, _datasets, _entities = await _seed(admin)
    target = await _writer_target(admin)
    activation = None
    async with AsyncSession(runtime) as writer:
        await writer.begin()
        try:
            # 진입만 지나고 DML은 아직이다 — 리뷰가 찾은 순환 창(활성화가 보호 표를 차례로
            # 잠그다 epoch 표에서 기다리면, 이 writer의 다음 DML이 이미 잠긴 표에서 막힌다).
            await writer.execute(text("SELECT ops.lock_single_feature_writer_protocol()"))
            assert (await writer.scalars(text(_OWN_PROTOCOL_MODES))).all() == []
            writer_pid = int(await writer.scalar(text("SELECT pg_backend_pid()")))
            activation = asyncio.create_task(_activate(admin, policy_feature))
            async with asyncio.timeout(1.5):
                while True:
                    if activation.done():
                        activation.result()
                        raise AssertionError("activation did not wait for the epoch=0 writer")
                    async with admin.connect() as observer:
                        waiting = await observer.scalar(
                            text("""SELECT count(*) FROM pg_stat_activity
                            WHERE :writer=ANY(pg_blocking_pids(pid))"""),
                            {"writer": writer_pid},
                        )
                    if waiting:
                        break
                    await asyncio.sleep(0.01)
            # 활성화는 P EX 바로 뒤 epoch 표에서 기다리므로 다른 보호 표는 아직 비어 있다.
            # writer는 남은 DML을 끝까지 쓰고 commit한다(교착이면 여기서 40P01).
            await writer.execute(text(_TRANSITION), target)
            assert (await writer.scalars(text(_OWN_PROTOCOL_MODES))).all() == []
            await writer.commit()
        finally:
            await writer.rollback()
    assert activation is not None
    await asyncio.wait_for(activation, 10)
    assert await _epoch(admin) > 0
    assert await _lifecycle(admin, target["feature"]) == "retired"


async def test_regime_writer_takes_protocol_ex(scalar_engines):
    admin, runtime = scalar_engines
    assert await _epoch(admin) > 0
    target = await _writer_target(admin)
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text(_TRANSITION), target)
        assert (await session.scalars(text(_OWN_PROTOCOL_MODES))).all() == ["ExclusiveLock"]
    assert await _lifecycle(admin, target["feature"]) == "retired"


async def test_regime_writer_waits_on_protocol_ex_behind_a_shared_holder(scalar_engines):
    admin, runtime = scalar_engines
    assert await _epoch(admin) > 0
    target = await _writer_target(admin)
    started = asyncio.get_running_loop().create_future()

    async def write() -> None:
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='5s'"))
            started.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            await session.execute(text(_TRANSITION), target)

    task = None
    try:
        async with AsyncSession(runtime) as holder, holder.begin():
            await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
            blocker = int(await holder.scalar(text("SELECT pg_backend_pid()")))
            task = asyncio.create_task(write())
            waiter = await asyncio.wait_for(asyncio.shield(started), 3)
            async with asyncio.timeout(3):
                while True:
                    if task.done():
                        task.result()
                        raise AssertionError("regime writer did not wait for protocol EX")
                    async with admin.connect() as observer:
                        found = await observer.scalar(
                            text(_WAITING_ON_PROTOCOL), {"pid": waiter, "blocker": blocker}
                        )
                    if found:
                        break
                    await asyncio.sleep(0.01)
            assert await _lifecycle(admin, target["feature"]) == "active"
        await asyncio.wait_for(asyncio.shield(task), 5)
        assert await _lifecycle(admin, target["feature"]) == "retired"
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_regime_writer_under_a_shared_caller_is_an_upgrade_error(scalar_engines):
    admin, runtime = scalar_engines
    assert await _epoch(admin) > 0
    target = await _writer_target(admin)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 SH caller와 실제 CALL
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
            await session.execute(text(_TRANSITION), target)
    assert caught.value.orig.sqlstate == "23514"
    assert "upgrade requires replan" in str(caught.value.orig)
    assert await _lifecycle(admin, target["feature"]) == "active"


async def test_regime_rejects_protocol_free_bypass_dml(scalar_engines):
    """진입을 건너뛴 쓰기는 regime에서 닫힌 쪽으로 실패한다(412 barrier·430 strict guard)."""
    admin, runtime = scalar_engines
    assert await _epoch(admin) > 0
    target = await _writer_target(admin)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - P 없는 실제 DML 경계
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(
                text("UPDATE feature.features SET name=name WHERE feature_id=:id"),
                {"id": target["feature"]},
            )
    assert caught.value.orig.sqlstate == "23514"
    assert await _lifecycle(admin, target["feature"]) == "active"
