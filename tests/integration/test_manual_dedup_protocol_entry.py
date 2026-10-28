"""M05 실제 CALL의 protocol-first 회귀: 적재(P EX) 뒤에서 행보다 P를 먼저 기다린다.

434까지 이 모듈은 실제 scoped kernel begin(P SH + manifest 행)과 M05 CALL의 잠금 역순을 봤다.
ADR-117(435)이 kernel과 공유 P를 지웠으므로, 남은 성질은 "M05는 P EX를 첫 문장에서 잡아, 적재가
P EX와 같은 Feature 행을 쥔 동안 행을 하나도 잡지 않고 P에서 기다리다 적재 뒤에 끝난다"이다.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.feature_reference_reconciliation_repo import (
    resolve_manual_provider_dedup_case,
)
from kortravelmap.infra.manual_provider_dedup_repo import record_manual_provider_candidate
from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_tvn_m05_manual_provider_dedup import (
    _CAUSATION,
    _SCORES,
    _open_command,
    _record_candidate,
    _seed_manual_provider_pair,
)

pytestmark = pytest.mark.integration
_WAITING_ON_PROTOCOL = """SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid
AND locktype='advisory' AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
AND mode='ExclusiveLock' AND NOT granted)"""


async def _blockers(engine, waiting: int, blocker: int, task):
    async with asyncio.timeout(3):
        while True:
            if task.done():
                task.result()
                raise AssertionError("entry finished before its controlled lock boundary")
            async with engine.connect() as connection:
                rows = await connection.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting}
                )
            if blocker in rows:
                return list(rows)
            await asyncio.sleep(0.01)


async def _contention(engines, *, operation: str = "record") -> dict[str, Any]:
    admin, runtime = engines
    # 소유 testcontainer의 진단 주기만 낮춘다. 제품의 1s lock_timeout/ACL은 유지한다.
    async with admin.connect() as setup:
        setup = await setup.execution_options(isolation_level="AUTOCOMMIT")
        await setup.execute(text("ALTER SYSTEM SET deadlock_timeout='100ms'"))
        assert await setup.scalar(text("SELECT pg_reload_conf()"))
    async with asyncio.timeout(3):
        while True:
            async with runtime.connect() as probe:
                value = await probe.scalar(text("SELECT current_setting('deadlock_timeout')"))
            if value == "100ms":
                break
            await asyncio.sleep(0.02)
    pair = await _seed_manual_provider_pair(admin, index=0 if operation == "record" else 1)
    decision = None
    if operation == "resolve":
        case = await _record_candidate(
            runtime,
            manual_feature_id=str(pair["manual_feature_id"]),
            provider_feature_id=str(pair["provider_feature_id"]),
        )
        command = await _open_command(
            admin, actor=str(pair["actor"]), operation="admin.manual-provider-dedup-case.resolve.v1"
        )
        async with admin.begin() as connection:
            await connection.execute(
                text("""INSERT INTO ops.feature_reference_reconciliation_subscriptions(
                principal_id,initial_event_sequence,read_scope,ack_scope)
                VALUES('service:feature-reference-reconciliation',0,
                'feature-reference-reconciliation:read','feature-reference-reconciliation:ack')""")
            )
            await connection.execute(
                text("""INSERT INTO ops.feature_reference_reconciliation_leases(
                principal_id,acked_through_sequence,worker_id,lease_epoch,lease_expires_at)
                VALUES('service:feature-reference-reconciliation',0,NULL,0,NULL)""")
            )
            row = (
                await connection.execute(
                    text("""SELECT evidence_fingerprint,
                manual_feature_row_revision,provider_feature_row_revision
                FROM ops.manual_provider_dedup_cases WHERE case_id=:id"""),
                    {"id": case["o_case_id"]},
                )
            ).one()
        decision = dict(
            case_id=case["o_case_id"],
            decision="kept",
            expected_case_fingerprint=row[0],
            expected_manual_row_revision=row[1],
            expected_provider_row_revision=row[2],
            survivor_feature_id=None,
            reason="isolated lock-order test",
            actor=str(pair["actor"]),
            command_id=command,
        )
    feature = str(pair["provider_feature_id"])
    traces: dict[str, Any] = {}
    async with AsyncSession(admin) as load, AsyncSession(runtime) as manual:
        await load.begin()
        await load.execute(text("SET LOCAL statement_timeout='8s'"))
        load_pid = int(await load.scalar(text("SELECT pg_backend_pid()")))
        # 적재 모양: P EX → 대상 Feature 행.
        await load.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await load.execute(
            text("SELECT 1 FROM feature.features WHERE feature_id=:id FOR UPDATE"),
            {"id": UUID(feature)},
        )
        await manual.begin()
        await manual.execute(text("SET LOCAL statement_timeout='8s'"))
        await manual.execute(text("SET LOCAL lock_timeout='5s'"))
        manual_pid = int(await manual.scalar(text("SELECT pg_backend_pid()")))
        assert tuple((await manual.execute(text("SELECT session_user,current_user"))).one()) == (
            "ktm_feature_service",
            "ktm_feature_service",
        )

        async def call_manual():
            try:
                if decision is not None:
                    result = await resolve_manual_provider_dedup_case(manual, **decision)
                    receipt = (str(result.resolution_id), result.outcome)
                else:
                    receipt = await record_manual_provider_candidate(
                        manual,
                        manual_feature_id=str(pair["manual_feature_id"]),
                        provider_feature_id=feature,
                        scores=_SCORES,
                        detector_causation=_CAUSATION,
                    )
                await manual.commit()
                return receipt
            finally:
                await manual.rollback()

        manual_task = asyncio.create_task(call_manual())
        try:
            traces["manual_waits_on_load"] = await _blockers(
                admin, manual_pid, load_pid, manual_task
            )
            async with admin.connect() as observer:
                # 행이 아니라 P에서 기다린다.
                assert await observer.scalar(text(_WAITING_ON_PROTOCOL), {"pid": manual_pid})
            # P 앞에서 manual Feature 행을 선점하지 않았다(행 잠금은 pg_locks에 보이지 않으므로
            # 실제 NOWAIT 잠금으로 확인한다).
            async with AsyncSession(admin) as observer, observer.begin():
                assert (
                    await observer.scalar(
                        text(
                            "SELECT 1 FROM feature.features WHERE feature_id=:id "
                            "FOR UPDATE NOWAIT"
                        ),
                        {"id": pair["manual_uuid"]},
                    )
                    == 1
                )
            await load.commit()
            outcome = await asyncio.wait_for(asyncio.shield(manual_task), 7)
            assert outcome[1] == ("created" if operation == "record" else "kept")
            return traces
        finally:
            await load.rollback()
            if not manual_task.done():
                manual_task.cancel()
            await asyncio.gather(manual_task, return_exceptions=True)
            await manual.rollback()


@pytest.mark.parametrize("operation", ["record", "resolve"])
async def test_actual_m05_call_waits_on_protocol_before_rows_behind_a_load(
    scalar_engines, operation
):
    result = await _contention(scalar_engines, operation=operation)
    assert result["manual_waits_on_load"]


_NAMES = (
    "record_manual_provider_dedup_candidate",
    "resolve_manual_provider_dedup_case",
    "resolve_manual_provider_dedup_case_v2",
)


@pytest.mark.parametrize("name", _NAMES)
async def test_m05_owner_acl_and_first_protocol_entry(scalar_engines, name):
    admin, _ = scalar_engines
    async with admin.connect() as connection:
        row = (
            await connection.execute(
                text("""SELECT procedure.prosrc,role.rolname,
            has_function_privilege('ktm_feature_service',procedure.oid,'EXECUTE'),
            EXISTS(SELECT 1 FROM aclexplode(procedure.proacl) acl WHERE acl.grantee=0)
            FROM pg_proc procedure JOIN pg_namespace ns ON ns.oid=procedure.pronamespace
            JOIN pg_roles role ON role.oid=procedure.proowner
            WHERE ns.nspname='feature' AND procedure.proname=:name"""),
                {"name": name},
            )
        ).one()
    assert (
        row[0]
        .partition("\nBEGIN\n")[2]
        .lstrip()
        .startswith("PERFORM ops.lock_scoped_feature_write_protocol(true);")
    )
    assert row[1] == "ktm_manual_provider_dedup_procedure_owner"
    assert row[2] is (name != "resolve_manual_provider_dedup_case")
    assert row[3] is False
