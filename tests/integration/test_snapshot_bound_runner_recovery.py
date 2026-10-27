"""기존 두 asset의 실제 stale→typed reset→동일 artifact 재계획·seal·replay를 검증한다."""

from __future__ import annotations

import hashlib
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from dagster import DagsterInstance
from dagster._core.events import DagsterEvent
from dagster._core.storage.dagster_run import DagsterRunStatus
from kortravelmap.dagster import airport_snapshot_runner, assets, rest_snapshot_runner
from kortravelmap.dagster.airport_snapshot_observation import encode_airport_observation_context
from kortravelmap.dagster.airport_snapshot_postprocess import AirportPostprocessMember
from kortravelmap.dagster.airport_snapshot_runtime import AirportSnapshotRuntime
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
    run_tracked_feature_asset,
)
from kortravelmap.dagster.rest_snapshot_postprocess import RestPostprocessMember
from kortravelmap.dagster.rest_snapshot_runtime import RestSnapshotRuntime
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _airport_snapshot as airport_io
from kortravelmap.dto.geo_dataset import GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import encode_provider_snapshot_artifact
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotMember
from tests.integration.test_airport_snapshot_scheduled_runner import owned_airport_snapshot_job
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_atomic import _state, _warning_bundle
from tests.integration.test_rest_snapshot_atomic_recovery import owned_rest_recovery_job
from tests.integration.test_rest_snapshot_registration import _limits, _Member, _prepare_rest_case
from tests.integration.test_rest_snapshot_registration import _rest_catalog as _rest_catalog
from tests.integration.test_rest_snapshot_two_writers import (
    _AirportCase,
    _cancel_ready,
    _profile,
    _read,
)
from tests.integration.test_rest_snapshot_two_writers import pair_baselines as pair_baselines
from tests.integration.test_snapshot_ready_reset_races import _exact_state, _reset
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_transport_airport_evidence_reader import _context
from tests.unit.test_provider_snapshot_artifact import _PINS

pytestmark = [pytest.mark.integration, pytest.mark.timeout(50)]


async def _airport_case(admin, runtime, dataset, instance):
    # 정본 operation/membership와 실제 engine guard를 사용한다. donor의 임의 quota seed는 없다.
    client = AsyncKorTravelMapClient(runtime)
    operation = "feature_place_transport_airports_job"
    memberships = await client.resolve_feature_operation_memberships(operation_key=operation)
    assert len(memberships) == 1
    assert memberships[0].provider_dataset_id == dataset
    run = instance.create_run_for_job(
        owned_airport_snapshot_job,
        status=DagsterRunStatus.STARTED,
        tags={"kor_travel_map.operation_key": operation, "kor_travel_map.trigger_kind": "schedule"},
    )
    instance.report_dagster_event(
        DagsterEvent("PIPELINE_START", owned_airport_snapshot_job.name), run.run_id
    )
    guard = FeatureOperationExecutionGuard(
        client, instance, operation, tuple(memberships), run.run_id, "schedule"
    )
    mutation = await guard.ensure()
    assert len(mutation.operation.members) == 1
    child = mutation.operation.members[0]
    member = SnapshotMember(
        UUID(mutation.operation.root_job_id), UUID(child.job_id), UUID(child.import_job_dataset_id)
    )
    context = SimpleNamespace(
        run=run,
        run_id=run.run_id,
        retry_number=0,
        log=logging.getLogger("owned-ready-reset-airport"),
        resources=SimpleNamespace(
            kor_travel_map_client=client,
            feature_operation_guard=guard,
            airport_snapshot_runtime=AirportSnapshotRuntime(_PINS),
            strict_address="strict",
        ),
    )
    bundle = await _warning_bundle(observed=3)
    base_geo = _context()
    stats = GeoCallStats(observed_data_tokens=set(base_geo.observed_data_tokens))
    payload = encode_provider_snapshot_artifact(
        (bundle,),
        GeoLoadContext(base_geo.geo_applied, base_geo.current_dataset, stats.observed_data_tokens),
        pins=_PINS,
    )
    observation = encode_airport_observation_context(
        payload,
        pins=_PINS,
        root_run_id=context.run_id,
        observation_generation=context.run_id,
        upstream_eof=True,
        geo_stats=stats,
    )
    registered = await airport_io.register_airport_snapshot(
        client, member, payload=payload, context=observation, pins=_PINS
    )
    assert registered.created
    assert registered.token is not None
    saved = await airport_io.read_airport_snapshot(client, member, pins=_PINS)
    assert saved is not None
    lease = await airport_io.claim_airport_snapshot(client, saved, previous=registered.token)
    plan = await airport_io.plan_airport_snapshot(
        client, saved, lease.token, pins=_PINS, dataset_id=dataset
    )
    saved = await airport_io.read_airport_snapshot(client, member, pins=_PINS)
    assert saved is not None
    typed = AirportPostprocessMember(
        member.root_id,
        member.child_id,
        member.member_id,
        context.resources.feature_operation_guard.memberships[0],
    )
    return context, _AirportCase(client, member, typed, saved, lease.token, plan, context.run_id)


async def _rest_case(admin, runtime, catalog, instance):
    client = AsyncKorTravelMapClient(runtime)
    operation = catalog.membership.operation_key
    run = instance.create_run_for_job(
        owned_rest_recovery_job,
        status=DagsterRunStatus.STARTED,
        tags={"kor_travel_map.operation_key": operation, "kor_travel_map.trigger_kind": "schedule"},
    )
    instance.report_dagster_event(
        DagsterEvent("PIPELINE_START", owned_rest_recovery_job.name), run.run_id
    )
    guard = FeatureOperationExecutionGuard(
        client, instance, operation, (catalog.membership,), run.run_id, "schedule"
    )
    mutation = await guard.ensure()
    assert len(mutation.operation.members) == 1
    child = mutation.operation.members[0]
    identity = SnapshotMember(
        UUID(mutation.operation.root_job_id), UUID(child.job_id), UUID(child.import_job_dataset_id)
    )
    member = _Member(
        catalog,
        run.run_id,
        identity,
        RestPostprocessMember(
            identity.root_id, identity.child_id, identity.member_id, catalog.membership
        ),
    )
    case = await _prepare_rest_case(admin, runtime, catalog, count=2, member=member)
    context = SimpleNamespace(
        run=run,
        run_id=run.run_id,
        retry_number=0,
        log=logging.getLogger("owned-ready-reset-rest"),
        resources=SimpleNamespace(
            kor_travel_map_client=client,
            feature_operation_guard=guard,
            rest_snapshot_runtime=RestSnapshotRuntime(case.pins),
            strict_address="strict",
        ),
    )
    return context, case


@pytest.mark.parametrize("kind", ["airport", "rest"])
async def test_actual_asset_replans_current_executor_and_replays_original_receipt(
    scalar_engines, rest_catalog, pair_baselines, monkeypatch, request, kind
):
    admin, runtime = scalar_engines
    with DagsterInstance.ephemeral() as instance:
        if kind == "airport":
            context, case = await _airport_case(admin, runtime, pair_baselines, instance)
            runner = airport_snapshot_runner
            entry = assets.run_feature_place_transport_airports
            collection = "_collect_or_legacy"
        else:
            context, case = await _rest_case(admin, runtime, rest_catalog, instance)
            runner = rest_snapshot_runner
            entry = assets.run_feature_place_transport_rest_areas
            collection = "_collect_rest_snapshot_input"
        io = _profile(case)
        forbidden = AsyncMock(
            side_effect=AssertionError("stored artifact must not refetch SDK/Geo/clock")
        )
        monkeypatch.setattr(runner, collection, forbidden)
        for name in (
            "fetched_at",
            "reverse_geocoder",
            "transport_airports",
            "transport_rest_areas",
        ):
            setattr(context.resources, name, forbidden)
        # 기존 등록 worker의 lease만 만료시켜 정상 SDK0 handoff로 현재 generation을 얻는다.
        # kernel plan lease는 만료시키거나 owner를 바꾸지 않는다.
        async with AsyncSession(admin) as session, session.begin():
            await _limits(session)
            await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            changed = await session.scalar(
                text("""UPDATE ops.provider_snapshot_controls
                SET lease_expires_at=clock_timestamp()-interval '1 second'
                WHERE snapshot_id=:snapshot AND executor_generation=:generation
                  AND executor_fence=:fence AND status='prepared' RETURNING snapshot_id"""),
                {
                    "snapshot": case.token.snapshot_id,
                    "generation": case.token.generation,
                    "fence": case.token.fence,
                },
            )
            assert changed == case.token.snapshot_id
        original_plan = getattr(io, f"plan_{kind}_snapshot")
        original_reset = getattr(io, f"reset_rolled_back_{kind}_snapshot_plan")
        original_seal = getattr(io, f"seal_{kind}_snapshot")
        original_apply = getattr(io, f"apply_{kind}_snapshot_in_session")
        apply_calls = []
        plans, reset_calls, applied_rejections = [], [], []

        async def observed_apply(*args, **kwargs):
            apply_calls.append(True)
            return await original_apply(*args, **kwargs)

        async def plan_then_first_stale(*args, **kwargs):
            plan = await original_plan(*args, **kwargs)
            plans.append(plan)
            if len(plans) == 1:
                fid = UUID(plan.preparation.evidence.items[0]["feature"]["feature_id"])
                async with AsyncSession(admin) as session, session.begin():
                    await _limits(session)
                    await session.execute(
                        text("SELECT ops.lock_scoped_feature_write_protocol(true)")
                    )
                    assert (
                        await session.scalar(
                            text("""UPDATE feature.features SET row_revision=row_revision+1
                        WHERE feature_id=:feature RETURNING feature_id"""),
                            {"feature": fid},
                        )
                        == fid
                    )
            return plan

        async def exact_reset(client, fresh, token, plan):
            assert plan is plans[0]
            assert fresh.artifact_payload == case.observed.artifact_payload
            assert fresh.observation_context == case.observed.observation_context
            assert token.generation == case.token.generation + 1
            reset_calls.append(plan)
            return await original_reset(client, fresh, token, plan)

        async def reject_applied_before_canonical_seal(client, token, **kwargs):
            # 실제 성공 apply/postprocess commit 뒤에도 root/member는 활성 상태다.
            # 완결된 현재 결과를 새 reset이 되돌릴 수 없음을 canonical seal 직전에 검사한다.
            plan = plans[-1]
            params = {
                "snapshot": token.snapshot_id,
                "generation": token.generation,
                "fence": token.fence,
                "attempt": plan.attempt_id,
                "owner": plan.owner,
                "manifest": plan.manifest_digest,
            }
            before = await _exact_state(admin, params)
            assert before[1]["status"] != "prepared"
            with pytest.raises(DBAPIError) as denied:
                await _reset(runtime, params)
            assert denied.value.orig.sqlstate == "23514"
            assert (
                denied.value.orig.__cause__.constraint_name == "ck_provider_snapshot_apply_required"
            )
            assert await _exact_state(admin, params) == before
            applied_rejections.append(True)
            return await original_seal(client, token, **kwargs)

        monkeypatch.setattr(io, f"apply_{kind}_snapshot_in_session", observed_apply)
        monkeypatch.setattr(io, f"plan_{kind}_snapshot", plan_then_first_stale)
        monkeypatch.setattr(io, f"reset_rolled_back_{kind}_snapshot_plan", exact_reset)
        monkeypatch.setattr(io, f"seal_{kind}_snapshot", reject_applied_before_canonical_seal)
        primary = None
        try:
            result = await run_tracked_feature_asset(context, entry)
            saved = await _read(case)
            assert saved is not None
            assert saved.status == "child_sealed"
            assert saved.artifact_payload == case.observed.artifact_payload
            assert saved.observation_context == case.observed.observation_context
            assert saved.applied_result is not None
            assert saved.applied_result.load == result.load
            assert saved.postprocess_receipt is not None
            assert len(plans) == 2
            assert len(reset_calls) == 1
            assert applied_rejections == [True]
            assert plans[0].attempt_id != plans[1].attempt_id
            assert plans[0].owner != plans[1].owner
            assert plans[0].input_digest == plans[1].input_digest
            async with AsyncSession(admin) as session:
                await _limits(session)
                rows = (
                    await session.execute(
                        text("""SELECT attempt_id,idempotency_key,status
                    FROM ops.feature_write_attempts
                    WHERE attempt_id=ANY(CAST(:attempts AS uuid[]))"""),
                        {"attempts": [plan.attempt_id for plan in plans]},
                    )
                ).all()
            states = {row.attempt_id: row for row in rows}
            assert states[plans[0].attempt_id].status == "cancelled"
            assert states[plans[1].attempt_id].status == "completed"
            assert (
                states[plans[0].attempt_id].idempotency_key
                != states[plans[1].attempt_id].idempotency_key
            )
            before_replay = await _state(admin)
            before_apply_calls = len(apply_calls)
            assert before_apply_calls == 2
            replay = await run_tracked_feature_asset(context, entry)
            assert replay == result
            assert await _state(admin) == before_replay
            assert len(apply_calls) == before_apply_calls
            assert await _read(case) == saved
            assert len(plans) == 2
            assert len(reset_calls) == 1
            forbidden.assert_not_awaited()
            request.node.user_properties.append(
                (
                    "bound_runner_recovery",
                    json.dumps(
                        {
                            "kind": kind,
                            "plans": 2,
                            "typed_resets": 1,
                            "same_artifact": True,
                            "postprocess_and_seal": True,
                            "completed_replay_source_rows_unchanged": True,
                            "completed_replay_native_apply_calls": 0,
                            "current_generation": case.token.generation + 1,
                            "applied_reset_rejected": True,
                            "artifact_sha256": hashlib.sha256(saved.artifact_payload).hexdigest(),
                        }
                    ),
                )
            )
        except BaseException as error:
            primary = error
            raise
        finally:
            await _cancel_ready(runtime, case, primary)
