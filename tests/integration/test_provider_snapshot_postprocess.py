"""전체430 설치의 실제 apply→원자 후처리. 함수 임의 설치/권한 우회는 없다."""

from __future__ import annotations

import json

import pytest
from kortravelmap.dagster.airport_snapshot_backend import AirportSnapshotBackend
from kortravelmap.dagster.airport_snapshot_observation import encode_airport_observation_context
from kortravelmap.dagster.airport_snapshot_postprocess import (
    AirportPostprocessMember,
    prepare_airport_snapshot_postprocess,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.dto.geo_dataset import GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra.provider_snapshot_artifact import encode_provider_snapshot_artifact
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    SnapshotMember,
    bind_provider_snapshot_plan,
    read_provider_snapshot_for_member,
    register_provider_snapshot_artifact,
)
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits
from kortravelmap.providers.kor_travel_transport_apply import apply_stored_airport_reobservation
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_registration import _prepare
from tests.integration.test_scoped_provider_batch import _plan
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_transport_airport_evidence_reader import _bundle, _context, _read, _seed
from tests.unit.test_provider_snapshot_artifact import _PINS

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]


@pytest.fixture(scope="module")
async def initialized_airport(scalar_engines):
    admin, runtime = scalar_engines
    return await _seed(admin, runtime, [await _bundle(0)])


async def _applied(admin, runtime, initial):
    dataset, features = initial
    incoming = await _bundle(0, observed=1)
    prepared = await _read(runtime, dataset, [incoming])
    assert prepared.eligible
    found_dataset, run, membership, args = await _prepare(admin, runtime)
    assert found_dataset == dataset
    member = SnapshotMember(args["root"], args["source"], args["member"])
    baseline_geo = _context()
    stats = GeoCallStats(observed_data_tokens=set(baseline_geo.observed_data_tokens))
    geo = GeoLoadContext(
        baseline_geo.geo_applied, baseline_geo.current_dataset, stats.observed_data_tokens
    )
    artifact = encode_provider_snapshot_artifact((incoming,), geo, pins=_PINS)
    context = encode_airport_observation_context(
        artifact,
        pins=_PINS,
        root_run_id=run,
        observation_generation=run,
        upstream_eof=True,
        geo_stats=stats,
    )
    async with AsyncSession(runtime) as session, session.begin():
        await apply_bounded_transaction_limits(session)
        registration = await register_provider_snapshot_artifact(
            session,
            member,
            artifact_payload=artifact,
            observation_context=context,
            expected_pins=_PINS,
            lease_seconds=300,
        )
    assert registration.created
    token = registration.token
    assert token is not None
    items = [batch.ProviderScalarRefreshItem(features[0], incoming)]
    plan, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        await apply_bounded_transaction_limits(session)
        await bind_provider_snapshot_plan(
            session,
            token,
            attempt_id=plan["attempt_id"],
            owner=plan["owner"],
            manifest_digest=plan["manifest_digest"],
            kernel_input_digest=batch.scoped_provider_refresh_batch_input_digest(
                items,
                dataset_id=dataset,
                policy_revision=1,
            ),
        )
    try:
        async with AsyncSession(runtime) as session, session.begin():
            await apply_bounded_transaction_limits(session)
            await apply_stored_airport_reobservation(
                session,
                artifact,
                prepared,
                pins=_PINS,
                snapshot_id=token.snapshot_id,
                generation=token.generation,
                fence=token.fence,
                attempt_id=plan["attempt_id"],
                owner=plan["owner"],
                manifest_digest=plan["manifest_digest"],
            )
    except BaseException as primary:
        # 이미 commit한 계획의 자기 lease만 회수한다. 첫 실패가 다음 사례를 가리지 않게 한다.
        from kortravelmap.infra.scoped_feature_writes import cancel_scoped_feature_write

        try:
            async with AsyncSession(runtime) as cleanup, cleanup.begin():
                await apply_bounded_transaction_limits(cleanup)
                await cancel_scoped_feature_write(
                    cleanup, attempt_id=plan["attempt_id"], owner=plan["owner"]
                )
        except BaseException as cleanup_error:
            primary.add_note("owned plan cleanup also failed: " + type(cleanup_error).__name__)
        raise
    async with AsyncSession(runtime) as session, session.begin():
        saved = await read_provider_snapshot_for_member(session, member, expected_pins=_PINS)
    assert saved is not None
    assert saved.status == "applied"
    assert saved.applied_result_bytes is not None
    intent = prepare_airport_snapshot_postprocess(
        member=AirportPostprocessMember(
            member.root_id, member.child_id, member.member_id, membership
        ),
        artifact_bytes=artifact,
        context_bytes=context,
        result_bytes=saved.applied_result_bytes,
        expected_pins=_PINS,
        expected_root_run_id=run,
    )
    return token, intent


async def _state(admin, token, intent):
    async with admin.connect() as connection:
        control = (
            await connection.execute(
                text("""SELECT status,postprocess_receipt,
            postprocess_txid,postprocess_intent_sha256 FROM ops.provider_snapshot_controls
            WHERE snapshot_id=:snapshot"""),
                {"snapshot": token.snapshot_id},
            )
        ).one()
        cursor = await connection.scalar(
            text("""SELECT cursor FROM provider_sync.provider_sync_state
            WHERE provider_dataset_id=:dataset AND sync_scope=:scope
              AND operation_key=:operation"""),
            {
                "dataset": intent.member.membership.provider_dataset_id,
                "scope": intent.member.membership.sync_scope,
                "operation": intent.member.membership.operation_key,
            },
        )
    return tuple(control), cursor


async def test_real_apply_partial_postprocess_rollback_then_replay(
    scalar_engines, initialized_airport, monkeypatch
):
    admin, runtime = scalar_engines
    token, intent = await _applied(admin, runtime, initialized_airport)
    before = await _state(admin, token, intent)
    original = AsyncKorTravelMapClient.record_sync_success_for_operation_membership

    async def fail_after_sync(client, **kwargs):
        await original(client, **kwargs)
        raise RuntimeError("owned fault after actual sync write")

    backend = AirportSnapshotBackend(AsyncKorTravelMapClient(runtime), token)
    with monkeypatch.context() as fault:
        fault.setattr(
            AsyncKorTravelMapClient, "record_sync_success_for_operation_membership", fail_after_sync
        )
        with pytest.raises(RuntimeError, match="owned fault"):
            await backend.complete_provider_snapshot_postprocess(intent)
    assert await _state(admin, token, intent) == before
    receipt = await backend.complete_provider_snapshot_postprocess(intent)
    assert receipt == intent.receipt_candidate
    state = await _state(admin, token, intent)
    assert state == (("postprocessed", receipt, None, None), intent.cursor)
    # 저장 완료를 확인한 후 반복 호출은 원 bytes/counter/clock을 유지한다.
    assert await backend.complete_provider_snapshot_postprocess(intent) == receipt
    assert await _state(admin, token, intent) == state


async def test_receipt_exchange_and_partial_marker_storage_are_rejected(
    scalar_engines, initialized_airport
):
    admin, runtime = scalar_engines
    token, intent = await _applied(admin, runtime, initialized_airport)
    changed = json.loads(intent.receipt_candidate)
    changed["fetched_at"] = "2026-10-25T00:00:00+00:00"
    other = json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
    assert other != intent.receipt_candidate
    params = {"snapshot": token.snapshot_id, "generation": token.generation, "fence": token.fence}
    async with AsyncSession(runtime) as session:
        await session.begin()
        await apply_bounded_transaction_limits(session)
        assert (
            await session.scalar(
                text(
                    "SELECT ops.begin_provider_snapshot_postprocess("
                    ":snapshot,:generation,:fence,:receipt)"
                ),
                {**params, "receipt": intent.receipt_candidate},
            )
            is None
        )
        with pytest.raises(DBAPIError) as caught:
            await session.execute(
                text(
                    "SELECT ops.finish_provider_snapshot_postprocess("
                    ":snapshot,:generation,:fence,:receipt)"
                ),
                {**params, "receipt": other},
            )
        assert caught.value.orig.sqlstate == "23514"
        await session.rollback()
    # 소유 fixture의 잘못된 저장 조합도 DB CHECK가 거부해야 한다.
    async with admin.connect() as connection:
        await connection.begin()
        with pytest.raises(DBAPIError) as caught:
            await connection.execute(
                text("""UPDATE ops.provider_snapshot_controls
                SET postprocess_intent_sha256=:digest,postprocess_txid=NULL
                WHERE snapshot_id=:snapshot"""),
                {"snapshot": token.snapshot_id, "digest": "a" * 64},
            )
        assert caught.value.orig.sqlstate == "23514"
        await connection.rollback()


async def test_existing_short_server_limits_are_never_extended(scalar_engines):
    _, runtime = scalar_engines
    from time import monotonic

    from kortravelmap.infra.transaction_limits import transaction_deadline

    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout='200ms'"))
        await session.execute(text("SET LOCAL lock_timeout='100ms'"))
        with transaction_deadline(monotonic() + 30):
            await apply_bounded_transaction_limits(session)
        assert await session.scalar(text("SHOW statement_timeout")) == "200ms"
        assert await session.scalar(text("SHOW lock_timeout")) == "100ms"
