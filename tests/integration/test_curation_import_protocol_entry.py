"""whole M03 import와 direct manual SQL의 protocol-first·rollback 계약."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.curation_import_children import ParentCommandIdentity
from kortravelmap.infra import curation_repo as repo
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_tvn_m03_import_child_issuance import (
    _domain_command,
    _row,
    _seed_dataset,
)
from tests.integration.test_tvn_m03_manual_curation import _collection, _command

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_IMPORT = "kortravelmap:curation-import"
_PROTOCOL = "SELECT ops.lock_scoped_feature_write_protocol(true)"


@dataclass
class Scenario:
    actor: str
    plan: str
    plan_hash: str
    command: int
    parent: ParentCommandIdentity
    collection_key: str
    collection: str
    direct: int
    suffix: str


async def _prepare(admin, runtime):
    suffix = uuid4().hex[:12]
    actor = "admin:import-protocol-" + suffix
    dataset = await _seed_dataset(admin, suffix=suffix)
    row = _row(
        suffix=suffix,
        dataset_id=dataset,
        row_number=2,
        source_item_key="manual-a",
        place_name="A manual " + suffix,
        manual_feature=dict(
            kind="place", category="12010000", coord=dict(lon="126.99100", lat="37.57960")
        ),
    )
    preview = await _domain_command(
        admin,
        actor=actor,
        operation="admin.curation-import.preview",
        idempotency_key=str(uuid4()),
        request_fingerprint="c" * 64,
    )
    plan = str(uuid4())
    content = uuid4().hex + uuid4().hex
    plan_hash = uuid4().hex + uuid4().hex
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        revisions = await repo.build_curation_import_revision_vector(session, rows=(row,))
        await repo.create_curation_import_plan_command(
            session,
            import_plan_id=plan,
            content_sha256=content,
            provenance_sha256=None,
            plan_sha256=plan_hash,
            summary=dict(has_errors=False, valid=1),
            rows=(row,),
            response_rows=(dict(row_number=2, valid=True),),
            revisions=revisions,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            command_id=preview,
            principal=actor,
        )
    key = str(uuid4())
    fingerprint = "d" * 64
    command = await _domain_command(
        admin,
        actor=actor,
        operation="admin.curation.import",
        idempotency_key=key,
        request_fingerprint=fingerprint,
    )
    parent = ParentCommandIdentity(
        actor=actor,
        operation="admin.curation.import",
        idempotency_key=key,
        request_fingerprint=fingerprint,
    )
    collection = await _collection(admin, actor=actor, suffix="direct-" + suffix)
    direct = await _command(
        admin, actor=actor, operation="admin.curation-item.create.manual-feature-v1"
    )

    return Scenario(
        actor, plan, plan_hash, command, parent, row.collection_key, collection, direct, suffix
    )


async def _import(session, case):
    claimed, rows, *_ = await repo.claim_curation_import_plan_command(
        session,
        import_plan_id=case.plan,
        plan_sha256=case.plan_hash,
        command_id=case.command,
        principal=case.actor,
    )
    result = await repo.import_curation_rows(
        session,
        rows=rows,
        actor=case.actor,
        source_content_sha256=claimed,
        batch_kind="csv_upload",
        command_id=case.command,
        parent_identity=case.parent,
        import_plan_id=case.plan,
        plan_sha256=case.plan_hash,
    )
    assert len(result["manual_children"]) == 1
    assert result["inserted"] == 1
    return result


async def _manual(session, case):
    result = await repo.create_manual_curation_item_with_feature_command(
        session,
        collection_id=case.collection,
        manual_feature=dict(
            kind="place",
            name="direct " + case.suffix,
            category="01070300",
            coord=dict(lon=127.1, lat=37.5),
            marker_icon="marker",
            marker_color="P-02",
        ),
        external_item_id="direct-" + case.suffix,
        command_id=case.direct,
        principal=case.actor,
    )
    assert isinstance(result, repo.CurationManualFeatureItem)


async def _lock_state(admin, *, pid, granted, key=None, blocker=None):
    predicate = (
        "objsubid=2 AND classid=1369104691::oid AND objid=115::oid"
        if key is None
        else "objsubid=1 AND classid=((hashtextextended(:key,0)>>32)&4294967295)::oid "
        "AND objid=(hashtextextended(:key,0)&4294967295)::oid"
    )
    async with AsyncSession(admin) as observer:
        return bool(
            await observer.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid "
                    "AND locktype='advisory' AND mode='ExclusiveLock' AND granted=:granted AND "
                    + predicate
                    + ") AND (CAST(:blocker AS integer) IS NULL OR "
                    "CAST(:blocker AS integer)=ANY(pg_blocking_pids(:pid)))"
                ),
                dict(pid=pid, granted=granted, key=key, blocker=blocker),
            )
        )


async def _wait(check, tasks):
    async with asyncio.timeout(4):
        while not await check():
            for task in tasks:
                if task.done():
                    task.result()
                    raise AssertionError("관측할 잠금 단계 전에 writer가 끝났습니다")
            await asyncio.sleep(0.01)


@asynccontextmanager
async def _transaction(runtime):
    async with AsyncSession(runtime) as session:
        tx = await session.begin()
        try:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            yield session
        finally:
            await tx.rollback()


@pytest.mark.parametrize("first", ["import", "manual"])
async def test_whole_import_and_manual_are_serialized_before_import_advisory(scalar_engines, first):
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime)
    ids, tasks = {}, []
    ready = {key: asyncio.Event() for key in ("import", "manual")}
    results = []

    async def run(name):
        async with _transaction(runtime) as session:
            ids[name] = int(await session.scalar(text("SELECT pg_backend_pid()")))
            ready[name].set()
            await (_import(session, case) if name == "import" else _manual(session, case))
            results.append(name)

    key = (
        "kortravelmap:curation-collection:" + case.collection_key if first == "import" else _IMPORT
    )
    second = "manual" if first == "import" else "import"
    async with AsyncSession(admin) as third:
        tx = await third.begin()
        try:
            blocker = int(await third.scalar(text("SELECT pg_backend_pid()")))
            await third.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), dict(key=key)
            )
            tasks.append(asyncio.create_task(run(first)))
            await asyncio.wait_for(ready[first].wait(), 3)
            await _wait(
                lambda: _lock_state(admin, pid=ids[first], granted=False, key=key, blocker=blocker),
                tasks,
            )
            assert await _lock_state(admin, pid=ids[first], granted=True)
            tasks.append(asyncio.create_task(run(second)))
            await asyncio.wait_for(ready[second].wait(), 3)
            await _wait(
                lambda: _lock_state(admin, pid=ids[second], granted=False, blocker=ids[first]),
                tasks,
            )
            # 후발 import는 import advisory를 선점하지 않고 protocol에서 기다린다.
            assert not await _lock_state(admin, pid=ids[second], granted=True, key=_IMPORT)
            await tx.rollback()
            await asyncio.wait_for(asyncio.gather(*tasks), 8)
            assert results == [first, second]
        finally:
            if tx.is_active:
                await tx.rollback()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("failure", ["shared_upgrade", "lock_timeout"])
async def test_failed_import_rolls_back_and_same_plan_can_retry(scalar_engines, failure):
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime)
    async with AsyncSession(admin) as blocker:
        tx = await blocker.begin()
        try:
            if failure == "lock_timeout":
                await blocker.execute(text(_PROTOCOL))
            async with _transaction(runtime) as session:
                if failure == "shared_upgrade":
                    await session.execute(
                        text("SELECT ops.lock_scoped_feature_write_protocol(false)")
                    )
                with pytest.raises(DBAPIError) as caught:
                    await _import(session, case)
                assert caught.value.orig.sqlstate == (
                    "23514" if failure == "shared_upgrade" else "55P03"
                )
        finally:
            await tx.rollback()
    async with AsyncSession(admin) as observer:
        assert (
            await observer.scalar(
                text(
                    "SELECT count(*) FROM ops.curation_import_manual_feature_children "
                    "WHERE import_plan_id=CAST(:plan AS uuid)"
                ),
                dict(plan=case.plan),
            )
            == 0
        )
    # plan claim과 child 발급은 첫 실패 TX에서 전부 취소된다. 같은 key/plan으로 재시도한다.
    async with _transaction(runtime) as session:
        first = await _import(session, case)
        assert not first["manual_children"][0].reused
    async with _transaction(runtime) as session:
        again = await _import(session, case)
        assert not again["manual_children"][0].reused


async def test_existing_autobegin_contract_keeps_caller_owned_rollback(scalar_engines):
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime)
    async with AsyncSession(runtime) as session:
        assert not session.in_transaction()
        # 기존 caller의 SET TRANSACTION이 autobegin을 연다. 명시 begin을 새로 요구하지 않는다.
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        assert session.in_transaction()
        result = await _import(session, case)
        child = result["manual_children"][0]
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM feature.features WHERE feature_id=CAST(:feature AS uuid)"
                ),
                dict(feature=child.feature_id),
            )
            == 1
        )
        await session.rollback()
    async with AsyncSession(admin) as observer:
        assert (
            await observer.scalar(
                text(
                    "SELECT count(*) FROM feature.features WHERE feature_id=CAST(:feature AS uuid)"
                ),
                dict(feature=child.feature_id),
            )
            == 0
        )
        assert (
            await observer.scalar(
                text(
                    "SELECT count(*) FROM ops.curation_import_manual_feature_children "
                    "WHERE import_plan_id=CAST(:plan AS uuid)"
                ),
                dict(plan=case.plan),
            )
            == 0
        )
    # 실패나 caller rollback 뒤에도 같은 plan과 deterministic child identity는 유효하다.
    async with _transaction(runtime) as session:
        again = await _import(session, case)
        assert not again["manual_children"][0].reused
