"""합성430의 실제 예약 caller/SDK0 재개와 동일 executor 세대의 재계획 source.

owned PG에서만 실행한다. SDK 입력/Geo 네트워크는 synthetic이며 DB·guard·converter·
plan/apply/postprocess/seal은 실제 구현이다. worker kill/운영 runtime receipt 증거는 아니다.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from dagster import DagsterInstance, job
from dagster._core.events import DagsterEvent
from dagster._core.storage.dagster_run import DagsterRunStatus
from kortravelmap.dagster import assets
from kortravelmap.dagster.airport_snapshot_observation import (
    decode_airport_observation_context,
    encode_airport_observation_context,
)
from kortravelmap.dagster.airport_snapshot_runtime import AirportSnapshotRuntime
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
    run_tracked_feature_asset,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _airport_snapshot as io
from kortravelmap.dto.geo_dataset import GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import encode_provider_snapshot_artifact
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotMember
from kortravelmap.infra.scoped_feature_writes import cancel_scoped_feature_write
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits
from kortravelmap.providers.kor_travel_transport import TransportAirport, TransportCoordinate
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_expired_plan_reset import _expire
from tests.integration.test_scoped_native_scalar_refresh import _TIME
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_transport_airport_evidence_reader import _bundle, _context, _seed
from tests.unit.test_provider_snapshot_artifact import _PINS

pytestmark = [pytest.mark.integration, pytest.mark.timeout(50)]


@job
def owned_airport_snapshot_job():
    pass


@pytest.fixture(scope="module")
async def airport_baseline(scalar_engines):
    return await _seed(*scalar_engines, [await _bundle(0)])


async def _scheduled(admin, runtime, instance, dataset):
    operation = "owned-airport-scheduled-" + uuid4().hex
    async with AsyncSession(admin) as session, session.begin():
        await apply_bounded_transaction_limits(session)
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("""INSERT INTO provider_sync.provider_dataset_operations
            (provider_dataset_id,operation_key,operation_kind,is_enabled)
            VALUES(:dataset,:operation,'refresh',true)"""),
            {"dataset": dataset, "operation": operation},
        )
        await session.execute(
            text("""INSERT INTO provider_sync.provider_dataset_operation_scopes
            (provider_dataset_id,sync_scope,operation_key,operation_kind)
            VALUES(:dataset,'dataset_wide',:operation,'refresh')"""),
            {"dataset": dataset, "operation": operation},
        )
        # 관리 fixture의 유한 quota 설정. 기존 used 계수를 초기화하지 않는다.
        for key in (0, dataset):
            await session.execute(
                text("""INSERT INTO ops.provider_snapshot_quota_limits
                (quota_key,max_bytes,max_rows) VALUES(:key,4194304,16)
                ON CONFLICT(quota_key) DO UPDATE SET
                max_bytes=ops.provider_snapshot_quota_limits.used_bytes+4194304,
                max_rows=ops.provider_snapshot_quota_limits.used_rows+16"""),
                {"key": key},
            )
    client = AsyncKorTravelMapClient(runtime)
    memberships = await client.resolve_feature_operation_memberships(operation_key=operation)
    assert len(memberships) == 1
    assert memberships[0].provider_dataset_id == dataset
    run = instance.create_run_for_job(
        owned_airport_snapshot_job,
        status=DagsterRunStatus.STARTED,
        tags={"kor_travel_map.operation_key": operation, "kor_travel_map.trigger_kind": "schedule"},
    )
    # 실제 Dagster event storage에 시작을 기록해 guard가 engine 시각/상태를 읽는다.
    instance.report_dagster_event(
        DagsterEvent("PIPELINE_START", owned_airport_snapshot_job.name), run.run_id
    )
    assert instance.get_run_record_by_id(run.run_id).start_time is not None
    guard = FeatureOperationExecutionGuard(
        client, instance, operation, memberships, run.run_id, "schedule"
    )
    mutation = await guard.ensure()
    assert mutation.operation.trigger_kind == "schedule"
    assert len(mutation.operation.members) == 1
    child = mutation.operation.members[0]
    identity = SnapshotMember(
        UUID(mutation.operation.root_job_id), UUID(child.job_id), UUID(child.import_job_dataset_id)
    )
    context = SimpleNamespace(
        run_id=run.run_id,
        retry_number=2,
        resources=SimpleNamespace(
            kor_travel_map_client=client,
            feature_operation_guard=guard,
            airport_snapshot_runtime=AirportSnapshotRuntime(_PINS),
            strict_address="strict",
            fetched_at=_TIME + timedelta(hours=1),
        ),
        log=logging.getLogger("owned-airport-snapshot"),
    )
    return context, client, identity


class _StoredGeoOnly:
    def __init__(self):
        self.stats = GeoCallStats()
        self.calls = 0

    async def __call__(self, coordinate):
        self.calls += 1
        raise AssertionError("live Geo forbidden: seeded canonical address must be reused")


class _Dataset:
    async def current(self):
        return _context().current_dataset

    async def recheck(self):
        return _context().current_dataset


async def _durable_state(admin, identity, membership):
    async with AsyncSession(admin) as session:
        artifact = (
            await session.execute(
                text("""SELECT to_jsonb(a),to_jsonb(c),j.status,
                (SELECT cursor FROM provider_sync.provider_sync_state s
                 WHERE s.provider_dataset_id=a.provider_dataset_id
                   AND s.sync_scope=a.sync_scope AND s.operation_key=a.operation_key)
                FROM ops.provider_snapshot_artifacts a
                JOIN ops.provider_snapshot_controls c USING(snapshot_id)
                JOIN ops.import_job_datasets m ON m.import_job_dataset_id=a.import_job_dataset_id
                JOIN ops.import_jobs j ON j.job_id=m.job_id
                WHERE a.import_job_dataset_id=:member"""),
                {"member": identity.member_id},
            )
        ).one()
        assert artifact[0]["provider_dataset_id"] == membership.provider_dataset_id
        return artifact


async def _cancel_if_ready(runtime, client, identity, primary=None):
    try:
        saved = await io.read_airport_snapshot(client, identity, pins=_PINS)
        if (
            saved is not None
            and saved.kernel_binding is not None
            and saved.kernel_binding.status == "ready"
        ):
            async with AsyncSession(runtime) as session, session.begin():
                await apply_bounded_transaction_limits(session)
                await cancel_scoped_feature_write(
                    session,
                    attempt_id=saved.kernel_binding.attempt_id,
                    owner=saved.kernel_binding.owner,
                )
    except BaseException as cleanup:
        if primary is None:
            raise
        primary.add_note("owned kernel cleanup failed: " + type(cleanup).__name__)


async def test_scheduled_entry_seals_then_same_run_replays_without_sdk_geo_or_clock(
    scalar_engines, airport_baseline, monkeypatch, request
):
    admin, runtime = scalar_engines
    dataset, _ = airport_baseline
    with DagsterInstance.ephemeral() as instance:
        context, client, identity = await _scheduled(admin, runtime, instance, dataset)
        guard = context.resources.feature_operation_guard
        assert await io.read_airport_snapshot(client, identity, pins=_PINS) is None
        calls = {"read": 0, "gc": 0, "fetch": 0}
        original_read, original_gc = io.read_airport_snapshot, io.collect_expired_airport_snapshots

        async def observed_read(*args, **kwargs):
            calls["read"] += 1
            return await original_read(*args, **kwargs)

        async def observed_gc(*args, **kwargs):
            calls["gc"] += 1
            return await original_gc(*args, **kwargs)

        def synthetic_sdk_rows():
            assert calls["read"] >= 1
            assert calls["gc"] == 1
            calls["fetch"] += 1
            assert calls["fetch"] == 1
            return [
                TransportAirport(
                    "Q00",
                    "소유 공항 0",
                    "OWNED AIRPORT 0",
                    "X000",
                    "서울특별시",
                    TransportCoordinate(lat=37.5, lon=127.0),
                    {},
                )
            ]

        live = _StoredGeoOnly()
        context.resources.transport_airports = synthetic_sdk_rows
        context.resources.reverse_geocoder = live
        context.resources.kor_travel_geo_dataset = _Dataset()
        monkeypatch.setattr(io, "read_airport_snapshot", observed_read)
        monkeypatch.setattr(io, "collect_expired_airport_snapshots", observed_gc)
        primary = None
        try:
            first = await run_tracked_feature_asset(
                context, assets.run_feature_place_transport_airports
            )
            saved = await original_read(client, identity, pins=_PINS)
            assert saved is not None
            assert saved.status == "child_sealed"
            assert saved.applied_result is not None
            assert saved.applied_result_bytes is not None
            assert saved.postprocess_receipt is not None
            assert first.load == saved.applied_result.load
            assert first.load.bundles_total == 1
            observation = decode_airport_observation_context(
                saved.observation_context,
                saved.artifact_payload,
                expected_pins=_PINS,
                expected_root_run_id=context.run_id,
            )
            assert observation.observation_generation == context.run_id + "::retry:2"
            assert observation.fetched_at == _TIME + timedelta(hours=1)
            assert observation.geo_stats == live.stats
            assert live.calls == 0
            assert calls["fetch"] == 1
            assert calls["gc"] == 1
            assert live.stats.reuse["skipped"] == 1
            before = await _durable_state(admin, identity, guard.memberships[0])
            assert before[2] == "done"
            assert before[1]["postprocess_txid"] is None
            assert before[1]["seal_txid"] is None

            def forbidden():
                raise AssertionError("registered replay must not fetch SDK/Geo or generate a clock")

            context.retry_number = 9
            for name in (
                "transport_airports",
                "reverse_geocoder",
                "kor_travel_geo_dataset",
                "fetched_at",
            ):
                setattr(context.resources, name, forbidden)
            replay = await run_tracked_feature_asset(
                context, assets.run_feature_place_transport_airports
            )
            assert replay == first
            assert await _durable_state(admin, identity, guard.memberships[0]) == before
            assert calls["fetch"] == 1
            assert calls["gc"] == 1
            assert (await original_read(client, identity, pins=_PINS)) == saved
            request.node.user_properties.append(("airport_snapshot_run", context.run_id))
            request.node.user_properties.append(
                ("original_generation", observation.observation_generation)
            )
            request.node.user_properties.append(("artifact_sha256", saved.artifact_sha256))
            request.node.user_properties.append(
                ("result_sha256", hashlib.sha256(saved.applied_result_bytes).hexdigest())
            )
        except BaseException as error:
            primary = error
            raise
        finally:
            await _cancel_if_ready(runtime, client, identity, primary)


async def test_expired_plan_recreates_unique_attempt_under_same_snapshot_generation(
    scalar_engines, airport_baseline, request
):
    admin, runtime = scalar_engines
    dataset, _ = airport_baseline
    with DagsterInstance.ephemeral() as instance:
        context, client, identity = await _scheduled(admin, runtime, instance, dataset)
        bundle = await _bundle(0, observed=2)
        baseline_geo = _context()
        stats = GeoCallStats(observed_data_tokens=set(baseline_geo.observed_data_tokens))
        geo = GeoLoadContext(
            baseline_geo.geo_applied, baseline_geo.current_dataset, stats.observed_data_tokens
        )
        payload = encode_provider_snapshot_artifact((bundle,), geo, pins=_PINS)
        observation = encode_airport_observation_context(
            payload,
            pins=_PINS,
            root_run_id=context.run_id,
            observation_generation=context.run_id,
            upstream_eof=True,
            geo_stats=stats,
        )
        registered = await io.register_airport_snapshot(
            client, identity, payload=payload, context=observation, pins=_PINS
        )
        assert registered.created
        assert registered.token is not None
        token = registered.token
        first = second = None
        primary = None
        try:
            saved = await io.read_airport_snapshot(client, identity, pins=_PINS)
            lease = await io.claim_airport_snapshot(client, saved, previous=token)
            assert lease.token == token
            first = await io.plan_airport_snapshot(
                client, saved, token, pins=_PINS, dataset_id=dataset
            )
            bound = await io.read_airport_snapshot(client, identity, pins=_PINS)
            assert bound.kernel_binding.attempt_id == first.attempt_id
            # 정확한 소유 attempt lease만 fault-inject한다. executor fence/epoch는 불변이다.
            await _expire(admin, dataset, {"attempt": str(first.attempt_id)})
            assert await io.reset_airport_snapshot_plan(client, bound, token) == "reset"
            reset = await io.read_airport_snapshot(client, identity, pins=_PINS)
            assert reset.status == "prepared"
            assert reset.kernel_binding is None
            assert reset.artifact_payload == saved.artifact_payload
            assert reset.observation_context == saved.observation_context
            second = await io.plan_airport_snapshot(
                client, reset, token, pins=_PINS, dataset_id=dataset
            )
            assert second.attempt_id != first.attempt_id
            assert second.owner != first.owner
            rebound = await io.read_airport_snapshot(client, identity, pins=_PINS)
            assert rebound.kernel_binding.attempt_id == second.attempt_id
            async with AsyncSession(admin) as session:
                control = (
                    await session.execute(
                        text("""SELECT executor_generation,executor_fence
                    FROM ops.provider_snapshot_controls WHERE snapshot_id=:snapshot"""),
                        {"snapshot": token.snapshot_id},
                    )
                ).one()
                attempts = (
                    await session.execute(
                        text("""SELECT attempt_id,idempotency_key,status
                    FROM ops.feature_write_attempts
                    WHERE attempt_id=ANY(CAST(:attempts AS uuid[]))"""),
                        {"attempts": [first.attempt_id, second.attempt_id]},
                    )
                ).all()
            assert control == (token.generation, token.fence)
            assert len(attempts) == 2
            old, new = (
                {row[0]: row for row in attempts}[first.attempt_id],
                {row[0]: row for row in attempts}[second.attempt_id],
            )
            assert old[2] == "cancelled"
            assert new[2] == "ready"
            assert old[1] != new[1]
            assert str(first.attempt_id) in old[1]
            assert str(second.attempt_id) in new[1]
            request.node.user_properties.append(("snapshot_generation", str(token.generation)))
            request.node.user_properties.append(("old_attempt", str(first.attempt_id)))
            request.node.user_properties.append(("new_attempt", str(second.attempt_id)))
        except BaseException as error:
            primary = error
            raise
        finally:
            await _cancel_if_ready(runtime, client, identity, primary)
