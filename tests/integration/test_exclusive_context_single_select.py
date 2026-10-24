"""423 후보 수/역할/실제 kernel 경계를 검증한다. 수집기 성능 시험은 아니다."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import exclusive_provider_refresh as full
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.provider_field_candidates import lock_provider_field_policy_epoch
from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    append_scoped_feature_write_manifest,
    begin_scoped_feature_write,
    claim_scoped_feature_write,
    lock_scoped_feature_write_protocol,
    seal_scoped_feature_write_manifest,
)
from tests.integration.test_exclusive_provider_full_refresh import _full_plan
from tests.integration.test_provider_field_scalar_projection import _activate
from tests.integration.test_provider_field_scalar_projection import _seed as _two_dataset_seed
from tests.integration.test_scoped_provider_batch import _seed, _snapshot
from tests.integration.test_scoped_provider_batch import scalar_container as scalar_container
from tests.integration.test_scoped_provider_batch import scalar_engines as scalar_engines

pytestmark = pytest.mark.integration
_CONTEXT = "feature._exclusive_provider_refresh_context(uuid,bigint)"


@pytest.fixture(autouse=True)
def _owned_resource_contract(scalar_container, request):
    wrapped = scalar_container.get_wrapped_container()
    wrapped.reload()
    attrs = wrapped.attrs
    identity = attrs["Config"]["Labels"]["codex.scalar-projection"]
    assert attrs["Name"] == "/kt-map-scalar-" + identity
    assert attrs["HostConfig"]["NanoCpus"] == 2_000_000_000
    assert attrs["HostConfig"]["Memory"] == attrs["HostConfig"]["MemorySwap"] == 1536 * 1024**2
    assert attrs["HostConfig"]["PidsLimit"] == 256
    request.node.user_properties.extend(
        [
            ("owned_container_id", attrs["Id"]),
            ("owned_container_name", attrs["Name"]),
            ("owned_container_label", identity),
            ("owned_image_id", attrs["Image"]),
        ]
    )


async def _probe(session, feature, dataset=None):
    # 일반 runtime 권한을 열지 않는다. private 함수 직접 관찰만 명시 owner로 한다.
    original = await session.scalar(text("SELECT current_user"))
    await session.execute(text("SET LOCAL ROLE ktm_feature_state_procedure_owner"))
    result = await session.scalar(
        text("SELECT feature._exclusive_provider_refresh_context(:feature,:dataset)"),
        {"feature": feature, "dataset": dataset},
    )
    await session.execute(text("RESET ROLE"))
    assert await session.scalar(text("SELECT current_user")) == original
    return result


@asynccontextmanager
async def _begun(runtime, plans, *, exclusive=True):
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await lock_scoped_feature_write_protocol(session, exclusive=exclusive)
            await lock_provider_field_policy_epoch(session)
            for plan in plans:
                result = await begin_scoped_feature_write(
                    session,
                    attempt_id=plan["attempt_id"],
                    owner=plan["owner"],
                    manifest_digest=plan["manifest_digest"],
                )
                assert result["status"] == "applying"
                assert result["exclusive_protocol"] is exclusive
            yield session
        finally:
            await session.rollback()


async def test_context_owner_acl_and_catalog_body(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT r.rolname,p.prosrc,
            p.provolatile::text,p.prosecdef,p.proconfig,
            has_function_privilege('ktm_feature_runtime',p.oid,'EXECUTE'),
            EXISTS(SELECT 1 FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner)))
                   WHERE grantee=0 AND privilege_type='EXECUTE')
            FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
            WHERE p.oid=to_regprocedure(:signature)"""),
                {"signature": _CONTEXT},
            )
        ).one()
    assert row[0] == "ktm_feature_state_procedure_owner"
    assert tuple(row[2:]) == ("v", True, ["search_path=pg_catalog"], False, False)
    historical = (
        Path(__file__).parents[2] / "alembic/versions/_420_exclusive_refresh_context.sql"
    ).read_text()
    marker = "    -- prefix는 용도 구분일 뿐이다."
    assert row[1].split(marker, 1)[1] == historical.split("$$")[1].split(marker, 1)[1]
    with pytest.raises(DBAPIError) as caught:
        async with AsyncSession(runtime) as session, session.begin():
            await session.scalar(
                text("SELECT feature._exclusive_provider_refresh_context(:id)"), {"id": uuid4()}
            )
    assert caught.value.orig.sqlstate == "42501"


async def test_zero_context_and_exact_one_survives_loop_exit_and_rollback(scalar_engines):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime, count=1)
    _, plan = await _full_plan(runtime, dataset, items)
    before = await _snapshot(admin, items)
    async with AsyncSession(runtime) as session, session.begin():
        assert await _probe(session, items[0].feature_id, dataset) is False
    async with _begun(runtime, [plan]) as session:
        assert await _probe(session, items[0].feature_id) is True
        assert await _probe(session, items[0].feature_id, dataset) is True
        assert await _probe(session, items[0].feature_id, dataset + 1) is False
        assert await _probe(session, uuid4(), dataset) is False
    assert await _snapshot(admin, items) == before


async def test_shared_applying_is_not_ex_context(scalar_engines):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime, count=1)
    _, plan = await _full_plan(runtime, dataset, items, exclusive=False)
    async with _begun(runtime, [plan], exclusive=False) as session:
        assert await _probe(session, items[0].feature_id) is False


async def test_other_transaction_does_not_observe_own_applying_context(scalar_engines, request):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime, count=1)
    _, plan = await _full_plan(runtime, dataset, items)
    async with _begun(runtime, [plan]) as session:
        own_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        assert await _probe(session, items[0].feature_id) is True
        async with AsyncSession(admin) as observer, observer.begin():
            other_pid = await observer.scalar(text("SELECT pg_backend_pid()"))
            assert other_pid != own_pid
            assert await _probe(observer, items[0].feature_id) is False
        request.node.user_properties.append(("independent_backend_pids", [own_pid, other_pid]))


async def _prepare_existing_feature(runtime, feature, dataset):
    attempt, owner = uuid4(), uuid4()
    async with AsyncSession(runtime) as session, session.begin():
        revision = await session.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=:id"), {"id": feature}
        )
        membership = await session.scalar(
            text("SELECT ops.scoped_feature_write_membership_digest(:id)"), {"id": feature}
        )
        heads = (
            await session.execute(
                text("""SELECT source_entity_key,current_source_record_key
            FROM provider_sync.source_links
            JOIN provider_sync.source_entity_heads USING(source_entity_key)
            WHERE feature_id=:id"""),
                {"id": feature},
            )
        ).all()
        dependencies = {
            ("feature", str(feature)): str(revision),
            ("feature_membership", str(feature)): membership,
        }
        dependencies.update({("source_head", key): value for key, value in heads})
        members = [
            ScopedWriteDependency(i, kind, key, value)
            for i, ((kind, key), value) in enumerate(sorted(dependencies.items()))
        ]
        digest = "a" * 64
        await claim_scoped_feature_write(
            session,
            attempt_id=attempt,
            owner=owner,
            dataset_id=dataset,
            idempotency_key=f"native-full-refresh-v1:{digest}:{attempt.hex}",
            regions=(),
            expected_members=len(members),
            input_digest=digest,
            exclusive_protocol=True,
        )
        await append_scoped_feature_write_manifest(
            session, attempt_id=attempt, owner=owner, members=members
        )
        sealed = await seal_scoped_feature_write_manifest(session, attempt_id=attempt, owner=owner)
    return dict(attempt_id=attempt, owner=owner, manifest_digest=sealed)


async def test_two_real_applying_attempts_are_rejected_without_choosing_first(scalar_engines):
    admin, runtime = scalar_engines
    # 기존 명시 owner seed가 두 dataset/primary source를 만든다.
    # attempt/status/txid/manifest는 직접 쓰지 않고 정본 claim/seal/begin으로 2건을 만든다.
    feature, datasets, _ = await _two_dataset_seed(admin)
    await _activate(admin, feature)
    feature = UUID(feature)
    plans = [await _prepare_existing_feature(runtime, feature, dataset) for dataset in datasets]
    async with _begun(runtime, plans) as session:
        assert await _probe(session, feature) is False
        for dataset in datasets:
            assert await _probe(session, feature, dataset) is True


@pytest.mark.parametrize(("mutation", "state"), [("membership", "40001"), ("head", "23514")])
async def test_explicit_owner_corruption_still_reaches_first_candidate_guard(
    scalar_engines, mutation, state
):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime, count=1)
    _, plan = await _full_plan(runtime, dataset, items)
    async with _begun(runtime, [plan]) as session:

        async def corrupt_then_probe():
            async with session.begin_nested():
                # 고권한 negative fixture다. runtime direct DML 허용이나 정상 경로라고 세지 않는다.
                await session.execute(text("SET LOCAL ROLE ktm_feature_state_procedure_owner"))
                if mutation == "membership":
                    await session.execute(
                        text("""UPDATE ops.feature_write_manifests SET expected_value=:bad
                        WHERE attempt_id=:attempt AND dependency_kind='feature_membership'"""),
                        {"bad": "0" * 64, "attempt": plan["attempt_id"]},
                    )
                else:
                    await session.execute(
                        text("""DELETE FROM ops.feature_write_manifests
                        WHERE attempt_id=:attempt AND dependency_kind='source_head'"""),
                        {"attempt": plan["attempt_id"]},
                    )
                await session.execute(text("RESET ROLE"))
                await _probe(session, items[0].feature_id)

        with pytest.raises(DBAPIError) as caught:
            await corrupt_then_probe()
        assert caught.value.orig.sqlstate == state
        assert await _probe(session, items[0].feature_id) is True


async def test_completed_context_is_false_and_public_replay_remains_completed(scalar_engines):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime, count=1)
    inputs, plan = await _full_plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        first = await full.refresh_exclusive_provider_snapshot(session, inputs, **plan)
        assert not first.replayed
    async with AsyncSession(runtime) as session, session.begin():
        assert await _probe(session, items[0].feature_id) is False
        replay = await full.refresh_exclusive_provider_snapshot(session, inputs, **plan)
        assert replay.replayed
        assert replay.attempt["status"] == "completed"


async def test_external_public_writer_blocks_then_times_out_without_context(
    scalar_engines, request
):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime, count=1)
    _, plan = await _full_plan(runtime, dataset, items)
    other = make_async_engine(
        runtime.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0
    )
    pid_ready = asyncio.get_running_loop().create_future()

    async def writer():
        async with AsyncSession(other) as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout='3s'"))
            await session.execute(text("SET LOCAL lock_timeout='1s'"))
            pid_ready.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await session.scalar(
                text("""SELECT feature.upsert_provider_geocode_stamps_ex(
                ARRAY[CAST(:feature AS uuid)],ARRAY['geocoded']::text[],
                :version,:data)"""),
                {
                    "feature": items[0].feature_id,
                    "version": "dv1-" + "a" * 32,
                    "data": "dd1-" + "a" * 32,
                },
            )

    task = None
    try:
        async with _begun(runtime, [plan]) as session:
            holder = await session.scalar(text("SELECT pg_backend_pid()"))
            task = asyncio.create_task(writer())
            waiter = await asyncio.wait_for(pid_ready, timeout=2)
            assert waiter != holder
            async with AsyncSession(admin) as observer, observer.begin():
                await observer.execute(text("SET LOCAL statement_timeout='1s'"))
                for _ in range(100):
                    blockers = await observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}
                    )
                    if holder in blockers:
                        break
                    await asyncio.sleep(0.005)
                else:
                    raise AssertionError("exact protocol blocker was not observed")
            with pytest.raises(DBAPIError) as caught:
                await asyncio.wait_for(task, timeout=2)
            assert caught.value.orig.sqlstate == "55P03"
            assert await _probe(session, items[0].feature_id) is True
            request.node.user_properties.append(("exact_blocking_pair", [holder, waiter]))
        async with AsyncSession(other) as session, session.begin():
            assert await session.scalar(text("SELECT 1")) == 1
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await other.dispose()
