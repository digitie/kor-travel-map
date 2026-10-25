"""Rest432/Airport의 두 physical writer와 공통 topic 직렬 구간을 검증한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from kortravelmap.dagster.airport_snapshot_backend import prepare_airport_postprocess_work
from kortravelmap.dagster.airport_snapshot_observation import encode_airport_observation_context
from kortravelmap.dagster.airport_snapshot_postprocess import (
    AirportPostprocessMember,
    prepare_airport_snapshot_postprocess,
)
from kortravelmap.dagster.rest_snapshot_backend import RestSnapshotBackend
from kortravelmap.dagster.rest_snapshot_postprocess import prepare_rest_snapshot_postprocess
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _airport_snapshot as airport_io
from kortravelmap.client import _rest_snapshot as rest_io
from kortravelmap.client._snapshot_atomic import (
    SnapshotPostprocessWork,
    run_snapshot_apply_postprocess,
)
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.dto.geo_dataset import GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.feature_operation_repo import ensure_dagster_feature_operation
from kortravelmap.infra.provider_snapshot_artifact import encode_provider_snapshot_artifact
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotMember
from kortravelmap.infra.scoped_feature_writes import cancel_scoped_feature_write
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_atomic import _warning_bundle
from tests.integration.test_rest_snapshot_registration import (
    _limits,
    _prepare_rest_case,
    _seed_rest_baseline,
)
from tests.integration.test_rest_snapshot_registration import (
    _rest_catalog as _rest_catalog,
)
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_transport_airport_evidence_reader import _context, _seed
from tests.unit.test_provider_snapshot_artifact import _PINS

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]


@dataclass(frozen=True)
class _AirportCase:
    client: AsyncKorTravelMapClient
    member: SnapshotMember
    typed_member: AirportPostprocessMember
    observed: object
    token: object
    plan: object
    run: str
    pins: object = _PINS


@pytest.fixture(scope="module")
async def pair_baselines(scalar_engines, rest_catalog):
    admin, runtime = scalar_engines
    # J의 catalog는 fresh quota RO와 정본 strict33 설치를 먼저 수행한다.
    # 기존 Airport _prepare의 quota overwrite/임의 operation seed는 재사용하지 않는다.
    await _seed_rest_baseline(admin, runtime, rest_catalog, count=2)
    dataset, ids = await _seed(admin, runtime, [await _warning_bundle()])
    assert dataset == rest_catalog.airport
    assert len(ids) == 1
    assert dataset != rest_catalog.dataset
    return dataset


async def _prepare_airport_case(runtime, dataset):
    operation = "feature_place_transport_airports_job"
    async with AsyncSession(runtime) as session, session.begin():
        await _limits(session)
        rows = (
            await session.execute(
                text("""SELECT operation.operation_key,scope.sync_scope
                FROM provider_sync.provider_dataset_operations operation
                JOIN provider_sync.provider_dataset_operation_scopes scope
                  USING(provider_dataset_id,operation_key,operation_kind)
                WHERE operation.provider_dataset_id=:dataset AND operation.operation_key=:operation
                  AND operation.is_enabled AND operation.operation_kind='refresh'"""),
                {"dataset": dataset, "operation": operation},
            )
        ).all()
        assert [tuple(row) for row in rows] == [(operation, "dataset_wide")]
        membership = ProviderDatasetOperationMembership(dataset, "dataset_wide", operation)
        run = "airport432-pair-" + uuid4().hex
        now = datetime.now(UTC)
        mutation = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=run,
            trigger_kind="schedule",
            selected_memberships=(membership,),
            operation_key=operation,
            engine_created_at=now,
            engine_started_at=now,
            observed_status="STARTED",
        )
    assert len(mutation.operation.members) == 1
    child = mutation.operation.members[0]
    assert child.membership == membership
    member = SnapshotMember(
        UUID(mutation.operation.root_job_id), UUID(child.job_id), UUID(child.import_job_dataset_id)
    )
    typed = AirportPostprocessMember(member.root_id, member.child_id, member.member_id, membership)
    geo = _context()
    stats = GeoCallStats(observed_data_tokens=set(geo.observed_data_tokens))
    payload = encode_provider_snapshot_artifact(
        (await _warning_bundle(observed=1),),
        GeoLoadContext(geo.geo_applied, geo.current_dataset, stats.observed_data_tokens),
        pins=_PINS,
    )
    context = encode_airport_observation_context(
        payload,
        pins=_PINS,
        root_run_id=run,
        observation_generation=run,
        upstream_eof=True,
        geo_stats=stats,
    )
    client = AsyncKorTravelMapClient(runtime)
    registration = await airport_io.register_airport_snapshot(
        client, member, payload=payload, context=context, pins=_PINS
    )
    assert registration.created
    assert registration.token is not None
    observed = await airport_io.read_airport_snapshot(client, member, pins=_PINS)
    assert observed is not None
    assert observed.status == "prepared"
    lease = await airport_io.claim_airport_snapshot(client, observed, previous=registration.token)
    observed = await airport_io.read_airport_snapshot(client, member, pins=_PINS)
    plan = await airport_io.plan_airport_snapshot(
        client, observed, lease.token, pins=_PINS, dataset_id=dataset
    )
    observed = await airport_io.read_airport_snapshot(client, member, pins=_PINS)
    assert observed is not None
    assert observed.kernel_binding is not None
    assert observed.kernel_binding.attempt_id == plan.attempt_id
    return _AirportCase(client, member, typed, observed, lease.token, plan, run)


def _profile(case):
    return airport_io if case.pins.source_entity_type == "airport" else rest_io


def _intent(case, observed):
    prepare = (
        prepare_airport_snapshot_postprocess
        if case.pins.source_entity_type == "airport"
        else prepare_rest_snapshot_postprocess
    )
    return prepare(
        member=case.typed_member,
        artifact_bytes=observed.artifact_payload,
        context_bytes=observed.observation_context,
        result_bytes=observed.applied_result_bytes,
        expected_pins=case.pins,
        expected_root_run_id=case.run,
    )


def _work(case, observed):
    if case.pins.source_entity_type == "airport":
        return prepare_airport_postprocess_work(_intent(case, observed))
    return RestSnapshotBackend(case.typed_member, case.pins, case.run).prepare(observed)


async def _run_case(case, *, client=None, after_apply=None, before_work=None, after_work=None):
    async def apply(session):
        row = (
            await session.execute(
                text("""SELECT pid,backend_start,usename FROM pg_stat_activity
            WHERE pid=pg_backend_pid() AND backend_type='client backend'""")
            )
        ).one()
        assert row.usename == "ktm_feature_service"
        apply_fn = (
            airport_io.apply_airport_snapshot_in_session
            if case.pins.source_entity_type == "airport"
            else rest_io.apply_rest_snapshot_in_session
        )
        result = await apply_fn(
            session, observed=case.observed, token=case.token, plan=case.plan, pins=case.pins
        )
        if after_apply is not None:
            await after_apply(session, tuple(row), result)
        return result

    def prepare(fresh):
        canonical = _work(case, fresh)

        async def callback(bound):
            if before_work is not None:
                await before_work(bound, fresh)
            await canonical.work(bound)
            if after_work is not None:
                await after_work(bound, fresh)

        return SnapshotPostprocessWork(canonical.receipt_candidate, callback)

    return await run_snapshot_apply_postprocess(
        client or case.client,
        case.observed,
        case.token,
        case.member,
        pins=case.pins,
        apply=apply,
        prepare=prepare,
    )


async def _read(case):
    return await getattr(
        _profile(case),
        "read_"
        + ("airport" if case.pins.source_entity_type == "airport" else "rest")
        + "_snapshot",
    )(case.client, case.member, pins=case.pins)


async def _cancel_ready(runtime, case, primary=None):
    try:
        saved = await _read(case)
        if saved is not None and saved.kernel_binding is not None:
            binding = saved.kernel_binding
            if binding.status == "ready":
                async with AsyncSession(runtime) as session, session.begin():
                    await _limits(session)
                    await cancel_scoped_feature_write(
                        session, attempt_id=binding.attempt_id, owner=binding.owner
                    )
    except BaseException as cleanup:
        if primary is None:
            raise
        primary.add_note("owned ready-plan cleanup failed: " + type(cleanup).__name__)


async def _assert_postprocessed_and_seal(case, completion):
    fresh = await _read(case)
    assert fresh is not None
    assert fresh.status == "postprocessed"
    assert fresh.applied_result == completion.result
    assert fresh.postprocess_receipt == completion.receipt
    intent = _intent(case, fresh)
    assert intent.receipt_candidate == completion.receipt
    assert intent.observation.observation_generation == case.run
    seal = (
        airport_io.seal_airport_snapshot
        if case.pins.source_entity_type == "airport"
        else (rest_io.seal_rest_snapshot)
    )
    await seal(
        case.client,
        case.token,
        artifact_sha256=fresh.artifact_sha256,
        context_sha256=fresh.context_sha256,
        result_sha256=hashlib.sha256(fresh.applied_result_bytes).hexdigest(),
        postprocess_sha256=hashlib.sha256(completion.receipt).hexdigest(),
    )
    assert (await _read(case)).status == "child_sealed"
    return len(intent.findings)


async def _topics(admin):
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await _limits(session)
        rows = (
            await session.execute(
                text("""SELECT topic,revision
        FROM ops.ops_live_topic_revisions WHERE topic IN ('dataset_projection','provider_sync')
        ORDER BY topic COLLATE "C"
            """)
            )
        ).all()
        assert len(rows) == 2
        return dict(rows)


async def _exact_blocker(admin, blocked_identity, holder_identity, task):
    blocked, started, login = blocked_identity
    holder, holder_started, holder_login = holder_identity
    assert blocked != holder
    # 원 lock_timeout1s보다 짧다. query 문자열/DSN은 기록하지 않는다.
    async with asyncio.timeout(0.8), AsyncSession(admin) as observer:
        while True:
            if task.done():
                await task
                raise AssertionError("second writer ended before the physical wait was observed")
            # pg_stat_activity의 transaction statistics snapshot을 poll마다 새로 받는다.
            async with observer.begin():
                await observer.execute(text("SET TRANSACTION READ ONLY"))
                await observer.execute(text("SET LOCAL statement_timeout='300ms'"))
                row = (
                    await observer.execute(
                        text("""SELECT a.wait_event_type,a.wait_event,
                    pg_blocking_pids(a.pid),EXISTS(SELECT 1 FROM pg_locks l
                      WHERE l.pid=a.pid AND NOT l.granted),
                    EXISTS(SELECT 1 FROM pg_stat_activity h WHERE h.pid=:holder
                      AND h.backend_start=:holder_started AND h.usename=:holder_login)
                    FROM pg_stat_activity a WHERE a.pid=:pid AND a.backend_start=:started
                      AND a.usename=:login"""),
                        dict(
                            pid=blocked,
                            started=started,
                            login=login,
                            holder=holder,
                            holder_started=holder_started,
                            holder_login=holder_login,
                        ),
                    )
                ).one()
            if row[0] == "Lock" and holder in row[2]:
                assert row[3] is True
                assert row[4] is True
                return row[1]
            await asyncio.sleep(0.005)


async def _wait_stage(task, event):
    waiter = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait([task, waiter], timeout=5, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task  # 원 SQL/제품 예외를 timeout으로 가리지 않는다.
            raise AssertionError("writer completed before its held stage")
        assert waiter in done, "owned writer stage deadline"
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.parametrize("leader", ["airport", "rest"])
async def test_disjoint_physical_source_writers_serialize_global_topics_without_lost_effects(
    scalar_engines,
    rest_catalog,
    pair_baselines,
    request,
    leader,
):
    admin, runtime = scalar_engines
    airport = await _prepare_airport_case(runtime, pair_baselines)
    rest = await _prepare_rest_case(admin, runtime, rest_catalog, count=2)
    cases = {"airport": airport, "rest": rest}
    follower = "rest" if leader == "airport" else "airport"
    assert airport.typed_member.membership.provider_dataset_id != rest_catalog.dataset
    before = await _topics(admin)
    identities, source_done = {}, {name: asyncio.Event() for name in cases}
    held, release = asyncio.Event(), asyncio.Event()
    started = time.perf_counter()
    tasks, primary, lock_wait = {}, None, None

    def source_observer(name):
        async def observe(session, identity, result):
            identities[name] = identity
            assert result.load.bundles_total == (1 if name == "airport" else 2)
            source_done[name].set()

        return observe

    async def hold_after_actual_work(bound, fresh):
        held.set()
        await release.wait()

    try:
        tasks[leader] = asyncio.create_task(
            _run_case(
                cases[leader],
                after_apply=source_observer(leader),
                after_work=hold_after_actual_work,
            )
        )
        await _wait_stage(tasks[leader], held)
        tasks[follower] = asyncio.create_task(
            _run_case(
                cases[follower],
                after_apply=source_observer(follower),
            )
        )
        await _wait_stage(tasks[follower], source_done[follower])
        # A가 commit 전인데 B의 실제 source apply도 끝났다. 공통 topic 안쪽에 양자 barrier0.
        assert not tasks[leader].done()
        assert source_done[leader].is_set()
        lock_wait = await _exact_blocker(
            admin, identities[follower], identities[leader], tasks[follower]
        )
        release.set()
        async with asyncio.timeout(10):
            completions = await asyncio.gather(tasks["airport"], tasks["rest"])
        after = await _topics(admin)
        assert after["provider_sync"] >= before["provider_sync"] + 2
        assert after["dataset_projection"] >= before["dataset_projection"] + 2
        counts = {}
        for name, completion in zip(["airport", "rest"], completions, strict=True):
            counts[name] = await _assert_postprocessed_and_seal(cases[name], completion)
        assert counts == {"airport": 1, "rest": 0}
        request.node.user_properties.append(
            (
                "physical_pair",
                json.dumps(
                    {
                        "leader": leader,
                        "actual_backends": 2,
                        "source_overlap": True,
                        "exact_blocker": True,
                        "wait_event": lock_wait,
                        "findings": counts,
                        "whole_wall_seconds": time.perf_counter() - started,
                        "backend_cpu_RSS": "unmeasured",
                        "child_seal": "separate TX",
                    },
                    sort_keys=True,
                ),
            )
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        release.set()
        for task in tasks.values():
            if not task.done():
                task.cancel()
        try:
            async with asyncio.timeout(5):
                await asyncio.gather(*tasks.values(), return_exceptions=True)
        except BaseException as cleanup:
            if primary is None:
                raise
            primary.add_note("owned writer drain failed: " + type(cleanup).__name__)
        finally:
            for case in cases.values():
                await _cancel_ready(runtime, case, primary)
