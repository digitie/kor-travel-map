"""M05 실제 CALL과 실제 scoped begin의 잠금 역순·protocol-first 회귀."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.feature_reference_reconciliation_repo import (
    resolve_manual_provider_dedup_case,
)
from kortravelmap.infra.manual_provider_dedup_repo import record_manual_provider_candidate
from kortravelmap.infra.scoped_feature_writes import (
    begin_scoped_feature_write,
    finish_scoped_feature_write,
    lock_scoped_feature_write_protocol,
)
from tests.integration.test_provider_field_scalar_projection import (
    _plan,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import (
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


def _sqlstate(error: BaseException) -> str | None:
    return getattr(getattr(error, "orig", None), "sqlstate", None)


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


async def _resolve_decision(admin, runtime, pair) -> dict[str, Any]:
    """기록된 후보 하나와 resolve 명령·reconciliation 구독을 준비하고 resolve 인자를 돌려준다."""
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
            'feature-reference-reconciliation:read','feature-reference-reconciliation:ack')
            ON CONFLICT DO NOTHING""")
        )
        await connection.execute(
            text("""INSERT INTO ops.feature_reference_reconciliation_leases(
            principal_id,acked_through_sequence,worker_id,lease_epoch,lease_expires_at)
            VALUES('service:feature-reference-reconciliation',0,NULL,0,NULL)
            ON CONFLICT DO NOTHING""")
        )
        row = (
            await connection.execute(
                text("""SELECT evidence_fingerprint,
            manual_feature_row_revision,provider_feature_row_revision
            FROM ops.manual_provider_dedup_cases WHERE case_id=:id"""),
                {"id": case["o_case_id"]},
            )
        ).one()
    return dict(
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


async def _contention(engines, *, fixed: bool, operation: str = "record") -> dict[str, Any]:
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
        decision = await _resolve_decision(admin, runtime, pair)
    feature = str(pair["provider_feature_id"])
    async with admin.connect() as connection:
        dataset = await connection.scalar(
            text("""SELECT provider_dataset_id
            FROM provider_sync.source_entities WHERE source_entity_key=:entity"""),
            {"entity": pair["source_entity_key"]},
        )
    attempt, owner, digest = await _plan(runtime, feature, dataset)
    traces = {}
    async with (
        AsyncSession(admin) as controller,
        AsyncSession(runtime) as scoped,
        AsyncSession(runtime) as manual,
    ):
        await controller.execute(text("SET LOCAL statement_timeout='8s'"))
        controller_pid = int(await controller.scalar(text("SELECT pg_backend_pid()")))
        await controller.execute(
            text("SELECT 1 FROM feature.features WHERE feature_id=:id FOR UPDATE"),
            {"id": UUID(feature)},
        )
        await scoped.begin()
        await lock_scoped_feature_write_protocol(scoped, exclusive=False)
        scoped_pid = int(await scoped.scalar(text("SELECT pg_backend_pid()")))
        await manual.begin()
        await manual.execute(text("SET LOCAL statement_timeout='8s'"))
        await manual.execute(text("SET LOCAL lock_timeout='5s'"))
        manual_pid = int(await manual.scalar(text("SELECT pg_backend_pid()")))
        assert len({controller_pid, scoped_pid, manual_pid}) == 3
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

        async def call_scoped():
            try:
                receipt = await begin_scoped_feature_write(
                    scoped, attempt_id=attempt, owner=owner, manifest_digest=digest
                )
                assert receipt["status"] == "applying"
                result = await finish_scoped_feature_write(
                    scoped, attempt_id=attempt, owner=owner, result_digest="e" * 64
                )
                await scoped.commit()
                return result
            finally:
                await scoped.rollback()

        manual_task = asyncio.create_task(call_manual())
        scoped_task = None
        try:
            # 433 DC-1: epoch=0의 M05는 P를 잡지 않는다. 대신 provider source 증거를 적재와 같은
            # 순서로 먼저 FOR SHARE한 뒤 Feature에서 controller를 기다린다.
            traces["manual_waits_at_feature_after_evidence"] = await _blockers(
                admin, manual_pid, controller_pid, manual_task
            )
            scoped_task = asyncio.create_task(call_scoped())
            # kernel은 source/head를 Feature보다 먼저 잡으려다 M05가 이미 쥔 증거 뒤에 선다.
            # 역순(M05 Feature→head, kernel head→Feature)이 없으므로 40P01이 나지 않는다.
            traces["scoped_waits_behind_manual_evidence"] = await _blockers(
                admin, scoped_pid, manual_pid if fixed else controller_pid, scoped_task
            )
            # 이 시점에 kernel 전체 begin은 실제 source/head를 먼저 잠갔다.
            # 컨트롤러는 행 잠금 해제 순서만 고정하며 A/B 제품 함수를 바꾸지 않는다.
            await controller.rollback()
            outcomes = await asyncio.wait_for(
                asyncio.gather(scoped_task, manual_task, return_exceptions=True), timeout=7
            )
            states = [
                _sqlstate(outcome) for outcome in outcomes if isinstance(outcome, BaseException)
            ]
            traces["error_sqlstates"] = states
            if fixed:
                assert states == [], outcomes
                assert outcomes[0]["status"] == "completed"
                assert outcomes[1][1] == ("created" if operation == "record" else "kept")
            else:
                assert "40P01" in states, outcomes
            return traces
        finally:
            await controller.rollback()
            for task in (manual_task, scoped_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(t for t in (manual_task, scoped_task) if t), return_exceptions=True
            )
            await scoped.rollback()
            await manual.rollback()


@pytest.mark.parametrize("operation", ["record", "resolve"])
async def test_actual_m05_call_and_scoped_begin_do_not_invert_locks(scalar_engines, operation):
    result = await _contention(scalar_engines, fixed=True, operation=operation)
    assert result["error_sqlstates"] == []


@pytest.mark.parametrize(("operation", "index"), [("record", 2), ("resolve", 3)])
async def test_m05_epoch0_waits_on_shared_protocol_behind_a_load(
    scalar_engines, operation, index
):
    """433 DC-1(리뷰 반영): M05는 epoch=0에서도 P SH로 적재(P EX) 뒤에 선다.

    적재는 한 transaction에서 bundle을 차례로 쓰며 Feature를 쥔 채 다음 head를 갱신한다.
    증거를 먼저 잡고 Feature를 기다리는 M05가 P 없이 겹치면 순환이다. 그래서 적재 뒤에서는
    기다리고(여기서는 짧은 상한의 55P03), 적재가 끝나면 같은 입력으로 끝난다.
    """
    admin, runtime = scalar_engines
    async with admin.connect() as connection:
        assert await connection.scalar(
            text("SELECT epoch FROM feature.provider_field_policy_epoch WHERE singleton")
        ) == 0
    pair = await _seed_manual_provider_pair(admin, index=index)
    decision = await _resolve_decision(admin, runtime, pair) if operation == "resolve" else None

    async def call(session):
        if decision is not None:
            result = await resolve_manual_provider_dedup_case(session, **decision)
            assert result.outcome == "kept"
        else:
            receipt = await record_manual_provider_candidate(
                session,
                manual_feature_id=str(pair["manual_feature_id"]),
                provider_feature_id=str(pair["provider_feature_id"]),
                scores=_SCORES,
                detector_causation=_CAUSATION,
            )
            assert receipt[1] == "created"

    async with AsyncSession(runtime) as holder, holder.begin():
        await lock_scoped_feature_write_protocol(holder, exclusive=True)
        with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 실제 P 대기 상한
            async with AsyncSession(runtime) as session, session.begin():
                await session.execute(text("SET LOCAL lock_timeout='300ms'"))
                await call(session)
        assert _sqlstate(caught.value) == "55P03"
    async with AsyncSession(runtime) as session, session.begin():
        await call(session)


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
    # 433 DC-1: 첫 진입은 증거 writer 진입이다(epoch=0 P SH, epoch>0 P EX).
    assert (
        row[0]
        .partition("\nBEGIN\n")[2]
        .lstrip()
        .startswith("PERFORM ops.lock_provider_evidence_writer_protocol();")
    )
    assert "lock_scoped_feature_write_protocol" not in row[0]
    assert row[1] == "ktm_manual_provider_dedup_procedure_owner"
    assert row[2] is (name != "resolve_manual_provider_dedup_case")
    assert row[3] is False


@pytest.mark.parametrize("name", _NAMES)
async def test_m05_epoch0_entry_takes_no_protocol_under_a_shared_caller(scalar_engines, name):
    """epoch=0의 진입은 P를 잡지 않으므로 SH caller에서도 승격 오류 없이 본문 검증까지 간다.

    epoch>0의 SH→EX 승격 거부는 ``test_single_writer_regime_entry.py``가 활성화 뒤에 본다.
    """
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        assert await session.scalar(
            text("SELECT epoch FROM feature.provider_field_policy_epoch WHERE singleton")
        ) == 0
        types = await session.scalar(
            text("""SELECT ARRAY(SELECT format_type(oid,NULL)
            FROM unnest(proallargtypes) WITH ORDINALITY a(oid,position) ORDER BY position)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='feature' AND p.proname=:name"""),
            {"name": name},
        )
        await session.execute(text("SET LOCAL ROLE ktm_manual_provider_dedup_procedure_owner"))
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
        try:
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text("CALL feature." + name + "(" + ",".join("NULL::" + t for t in types) + ")")
                )
            # 본문 자신의 executor/입력 검증에서 멈춘다. protocol 승격 오류가 아니다.
            assert "upgrade requires replan" not in str(caught.value.orig)
            assert caught.value.orig.sqlstate in {"42501", "23514", "25001", "P0002"}
        finally:
            await session.rollback()
