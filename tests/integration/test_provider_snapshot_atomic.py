"""실제 Airport 기준선으로 새 선택A의 원자성/응답경계복구를 먼저 검증한다.

Rest profile/두 물리 writer는 새 typed seam 합성 뒤 별도 추가한다. collect는 PG 수용이 아니다.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from kortravelmap.dagster.airport_snapshot_backend import (
    AirportSnapshotBackend,
    prepare_airport_postprocess_work,
)
from kortravelmap.dagster.airport_snapshot_observation import encode_airport_observation_context
from kortravelmap.dagster.airport_snapshot_postprocess import (
    AirportPostprocessMember,
    prepare_airport_snapshot_postprocess,
)
from kortravelmap.dagster.etl import _address_validation_findings
from kortravelmap.dagster.validation import validate_feature_bundles_address
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _airport_snapshot as io
from kortravelmap.client import _snapshot_postprocess as postprocess
from kortravelmap.client._snapshot_atomic import run_snapshot_apply_postprocess
from kortravelmap.dto import Address
from kortravelmap.dto.geo_dataset import GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import encode_provider_snapshot_artifact
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorToken,
    SnapshotMember,
    read_provider_snapshot_for_member,
)
from kortravelmap.providers.kor_travel_transport import TransportAirport, TransportCoordinate
from kortravelmap.providers.kor_travel_transport_native import (
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)
from tests.integration.test_airport_snapshot_scheduled_runner import _cancel_if_ready
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_registration import _prepare
from tests.integration.test_scoped_native_scalar_refresh import _TIME
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_transport_airport_evidence_reader import _context, _seed
from tests.unit.test_provider_snapshot_artifact import _PINS

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]


@pytest.fixture(scope="module")
async def airport_baseline(scalar_engines):
    return await _seed(*scalar_engines, [await _warning_bundle()])


async def _warning_bundle(*, index=0, observed=0):
    # 기존 pure observation의 실제 warning 패턴을 public converter로 재현한다.
    geo = _context().current_dataset
    item = TransportAirport(
        f"Q{index:02d}",
        f"소유 공항 {index}",
        f"OWNED AIRPORT {index}",
        f"X{index:03d}",
        "서울특별시 종로구",
        TransportCoordinate(lat=37.5, lon=127.0),
        {},
    )
    bundle = await transport_item_to_native_bundle(
        item,
        fetched_at=_TIME + timedelta(hours=observed),
        geo=TransportGeoEvidence(
            "resolved",
            geo.version_token,
            geo.data_token,
            Address(bjd_code="1156011000", sigungu_name="기장군"),
            "0" * 64,
        ),
    )
    validation = validate_feature_bundles_address((bundle,))
    assert validation.error_count == 0
    assert validation.warning_count == 1
    assert len(validation.issues) == 1
    return bundle


@dataclass(frozen=True)
class _Pending:
    client: AsyncKorTravelMapClient
    member: SnapshotMember
    typed_member: AirportPostprocessMember
    observed: RecoveredProviderSnapshot
    token: SnapshotExecutorToken
    plan: io.AirportSnapshotPlan
    run: str
    stale_key: str
    stale_id: UUID


async def _prepared(admin, runtime, baseline):
    dataset, _ = baseline
    client = AsyncKorTravelMapClient(runtime)
    incoming = await _warning_bundle(observed=1)
    found, run, membership, ids = await _prepare(admin, runtime)
    assert found == dataset
    member = SnapshotMember(ids["root"], ids["source"], ids["member"])
    # 실제 정본 검증/변환으로 만든 이전 Q01 미연결 warning을 commit해 stale row를 준비한다.
    # 현재 snapshot Q00의 full finding set에는 이 identity가 없다.
    previous = await _warning_bundle(index=1)
    record = previous.source_record
    old_findings = _address_validation_findings(
        validate_feature_bundles_address((previous,)),
        provider=_PINS.provider,
        dataset_key=_PINS.dataset_key,
        loaded_feature_ids=set(),
        dropped_feature_ids=frozenset(),
        source_identities={
            record.source_record_key: (record.source_entity_type, record.source_entity_id)
        },
    )
    assert len(old_findings) == 1
    assert old_findings[0].linked is False
    written = await client.record_address_validation_findings(
        old_findings,
        provider=_PINS.provider,
        dataset_key=_PINS.dataset_key,
        run_id="prior-" + run,
    )
    assert written.unique_count == 1
    assert written.upserted_count == 1
    async with AsyncSession(admin) as observer:
        stale_id = (
            await observer.scalars(
                text(
                    "SELECT issue_id FROM ops.data_integrity_violations "
                    "WHERE provider_dataset_id=:dataset AND status='open' "
                    "AND payload->>'dedupe_key'=:key"
                ),
                {"dataset": dataset, "key": old_findings[0].dedupe_key},
            )
        ).one()
    base_geo = _context()
    stats = GeoCallStats(observed_data_tokens=set(base_geo.observed_data_tokens))
    geo = GeoLoadContext(base_geo.geo_applied, base_geo.current_dataset, stats.observed_data_tokens)
    payload = encode_provider_snapshot_artifact((incoming,), geo, pins=_PINS)
    context = encode_airport_observation_context(
        payload,
        pins=_PINS,
        root_run_id=run,
        observation_generation=run,
        upstream_eof=True,
        geo_stats=stats,
    )
    registration = await io.register_airport_snapshot(
        client, member, payload=payload, context=context, pins=_PINS
    )
    assert registration.created
    assert registration.token is not None
    observed = await io.read_airport_snapshot(client, member, pins=_PINS)
    assert observed is not None
    assert observed.status == "prepared"
    lease = await io.claim_airport_snapshot(client, observed, previous=registration.token)
    plan = await io.plan_airport_snapshot(
        client, observed, lease.token, pins=_PINS, dataset_id=dataset
    )
    observed = await io.read_airport_snapshot(client, member, pins=_PINS)
    assert observed is not None
    assert observed.kernel_binding is not None
    assert observed.kernel_binding.attempt_id == plan.attempt_id
    return _Pending(
        client,
        member,
        AirportPostprocessMember(member.root_id, member.child_id, member.member_id, membership),
        observed,
        lease.token,
        plan,
        run,
        old_findings[0].dedupe_key,
        UUID(str(stale_id)),
    )


def _intent(case, fresh):
    intent = prepare_airport_snapshot_postprocess(
        member=case.typed_member,
        artifact_bytes=fresh.artifact_payload,
        context_bytes=fresh.observation_context,
        result_bytes=fresh.applied_result_bytes,
        expected_pins=_PINS,
        expected_root_run_id=case.run,
    )
    assert intent.observation.validation.error_count == 0
    assert intent.observation.validation.warning_count == 1
    assert len(intent.findings) == 1
    assert len({finding.dedupe_key for finding in intent.findings}) == 1
    return intent


async def _run(case, *, after_apply=None):
    async def apply(session):
        result = await io.apply_airport_snapshot_in_session(
            session, observed=case.observed, token=case.token, plan=case.plan, pins=_PINS
        )
        if after_apply is not None:
            fresh = await read_provider_snapshot_for_member(
                session, case.member, expected_pins=_PINS
            )
            assert fresh.status == "applied"
            assert fresh.applied_result == result
            assert fresh.applied_result_bytes is not None
            raise after_apply
        return result

    return await run_snapshot_apply_postprocess(
        case.client,
        case.observed,
        case.token,
        case.member,
        pins=_PINS,
        apply=apply,
        prepare=lambda fresh: prepare_airport_postprocess_work(_intent(case, fresh)),
    )


# 이 owned DB 안의 작은 synthetic 자료만 비교한다. mutable 운영 DB/임의 relation 입력은 없다.
_STATE_TABLES = (
    "provider_sync.source_records",
    "provider_sync.source_entities",
    "provider_sync.source_entity_heads",
    "provider_sync.source_links",
    "feature.features",
    "feature.feature_places",
    "feature.feature_geocode_stamps",
    "feature.provider_field_shadow_candidates",
    "feature.provider_field_active_policies",
    "ops.feature_write_attempts",
    "ops.provider_snapshot_artifacts",
    "ops.provider_snapshot_controls",
    "ops.integrity_observation_scopes",
    "ops.integrity_observation_runs",
    "ops.integrity_finding_observations",
    "ops.data_integrity_violations",
    "provider_sync.provider_sync_state",
    "ops.ops_live_topic_revisions",
)


async def _state(admin):
    result = {}
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='3s'"))
        await session.execute(text("SET LOCAL lock_timeout='1s'"))
        for table in _STATE_TABLES:
            rows = (
                await session.scalars(text(f"SELECT to_jsonb(t) FROM {table} t LIMIT 1025"))
            ).all()
            assert len(rows) <= 1024
            result[table] = tuple(sorted(json.dumps(row, sort_keys=True) for row in rows))
    return result


@pytest.mark.parametrize("stage", ["after_apply", "findings", "sync", "stale_close", "receipt"])
@pytest.mark.parametrize("cancel", [False, True], ids=["exception", "cancel"])
async def test_actual_effects_and_original_result_rollback_together_then_same_plan_recovers(
    scalar_engines,
    airport_baseline,
    monkeypatch,
    stage,
    cancel,
):
    admin, runtime = scalar_engines
    case = await _prepared(admin, runtime, airport_baseline)
    primary = None
    try:
        before = await _state(admin)
        fault = asyncio.CancelledError() if cancel else RuntimeError("owned atomic stage fault")
        with monkeypatch.context() as patch:
            if stage == "receipt":
                original = postprocess.finish_provider_snapshot_postprocess

                async def fail_receipt(*args, **kwargs):
                    await original(*args, **kwargs)
                    saved = await read_provider_snapshot_for_member(
                        args[0], case.member, expected_pins=_PINS
                    )
                    assert saved.status == "postprocessed"
                    assert saved.postprocess_receipt is not None
                    raise fault

                patch.setattr(postprocess, "finish_provider_snapshot_postprocess", fail_receipt)
            elif stage != "after_apply":
                name = {
                    "findings": "record_address_validation_findings",
                    "sync": "record_sync_success_for_operation_membership",
                    "stale_close": "close_stale_address_validation_findings",
                }[stage]
                original = getattr(AsyncKorTravelMapClient, name)

                async def fail_effect(bound, *args, **kwargs):
                    written = await original(bound, *args, **kwargs)
                    # 같은 rollback_only 연결에서 실제 DML을 관측한 뒤 실패시킨다.
                    async with bound._session_factory() as probe, probe.begin():
                        dataset = case.typed_member.membership.provider_dataset_id
                        if stage == "findings":
                            assert written.observed_count == 1
                            assert written.unique_count == 1
                            assert written.upserted_count == 1
                            finding = args[0][0]
                            assert (
                                await probe.scalar(
                                    text(
                                        "SELECT count(*) FROM ops.data_integrity_violations "
                                        "WHERE provider_dataset_id=:dataset "
                                        "AND payload->>'dedupe_key'=:key"
                                    ),
                                    {"dataset": dataset, "key": finding.dedupe_key},
                                )
                                == 1
                            )
                            assert (
                                await probe.scalar(
                                    text(
                                        "SELECT count(*) FROM ops.integrity_finding_observations f "
                                        "JOIN ops.integrity_observation_runs r "
                                        "USING(observation_run_id) "
                                        "WHERE r.external_run_id=:run AND f.dedupe_key=:key"
                                    ),
                                    {"run": case.run, "key": finding.dedupe_key},
                                )
                                == 1
                            )
                        elif stage == "sync":
                            cursor = await probe.scalar(
                                text(
                                    "SELECT cursor FROM provider_sync.provider_sync_state "
                                    "WHERE provider_dataset_id=:dataset "
                                    "AND operation_key=:operation "
                                    "AND sync_scope=:scope"
                                ),
                                {
                                    "dataset": dataset,
                                    "operation": case.typed_member.membership.operation_key,
                                    "scope": case.typed_member.membership.sync_scope,
                                },
                            )
                            assert cursor is not None
                            assert (
                                cursor["loaded_at"]
                                == case.observed.artifact.bundles[
                                    0
                                ].source_record.fetched_at.isoformat()
                            )
                        else:
                            assert stage == "stale_close"
                            assert written >= 1
                            assert (
                                await probe.scalar(
                                    text(
                                        "SELECT status FROM ops.data_integrity_violations "
                                        "WHERE issue_id=:issue"
                                    ),
                                    {"issue": case.stale_id},
                                )
                                == "resolved"
                            )
                            assert (
                                await probe.scalar(
                                    text(
                                        "SELECT status FROM ops.integrity_observation_runs "
                                        "WHERE external_run_id=:run"
                                    ),
                                    {"run": case.run},
                                )
                                == "authoritative"
                            )
                    raise fault

                patch.setattr(AsyncKorTravelMapClient, name, fail_effect)
            with pytest.raises(type(fault)) as raised:
                await _run(case, after_apply=fault if stage == "after_apply" else None)
            assert raised.value is fault
        assert await _state(admin) == before
        saved = await io.read_airport_snapshot(case.client, case.member, pins=_PINS)
        assert saved.status == "prepared"
        assert saved.applied_result_bytes is None
        assert saved.postprocess_receipt is None
        completed = await _run(case)
        saved = await io.read_airport_snapshot(case.client, case.member, pins=_PINS)
        assert saved.status == "postprocessed"
        assert saved.applied_result == completed.result
        assert saved.postprocess_receipt == completed.receipt
        assert completed.result.load.bundles_total == 1
        assert completed.result.retired == 0
        # Child seal은 별도 TX이므로 이 성공을 seal/root 완료라고 부르지 않는다.
        assert saved.child_status == "running"
        assert saved.root_status == "running"
    except BaseException as error:
        primary = error
        raise
    finally:
        await _cancel_if_ready(runtime, case.client, case.member, primary)


async def test_committed_response_loss_sdk0_reuses_exact_result_without_duplicate_effects(
    scalar_engines,
    airport_baseline,
    monkeypatch,
):
    admin, runtime = scalar_engines
    case = await _prepared(admin, runtime, airport_baseline)
    primary = None
    try:

        class LostResponse(RuntimeError):
            pass

        async def lose_response():
            await _run(case)
            raise LostResponse("owned response boundary after successful commit")

        with pytest.raises(LostResponse):
            await lose_response()
        # commit 성공/응답경계 fault이며 실제 wire-loss를 흉내냈다고 과장하지 않는다.
        saved = await io.read_airport_snapshot(case.client, case.member, pins=_PINS)
        assert saved.status == "postprocessed"
        assert saved.applied_result_bytes is not None
        intent = _intent(case, saved)
        before_replay = await _state(admin)

        async def forbidden(*args, **kwargs):
            pytest.fail("stored completion replay performed apply or postprocess effects")

        with monkeypatch.context() as patch:
            patch.setattr(io, "apply_airport_snapshot_in_session", forbidden)
            for name in (
                "record_address_validation_findings",
                "record_sync_success_for_operation_membership",
                "close_stale_address_validation_findings",
            ):
                patch.setattr(AsyncKorTravelMapClient, name, forbidden)
            receipt = await AirportSnapshotBackend(
                case.client, case.token
            ).complete_provider_snapshot_postprocess(intent)
        assert receipt == saved.postprocess_receipt == intent.receipt_candidate
        assert await _state(admin) == before_replay
        again = await io.read_airport_snapshot(case.client, case.member, pins=_PINS)
        assert again == saved
    except BaseException as error:
        primary = error
        raise
    finally:
        await _cancel_if_ready(runtime, case.client, case.member, primary)
