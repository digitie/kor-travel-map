"""기존 typed reset의 live READY lease 거부를 실제 Airport apply TX에서 재현한다.

아직 제품 변경 전 source다. upstream/Geo 호출과 운영 설정 변경은 없으며,
공식 등록·executor·plan·atomic apply가 만드는 정확 binding을 사용한다.
"""

from __future__ import annotations

import pytest
from dagster import DagsterInstance
from kortravelmap.dagster.airport_snapshot_observation import encode_airport_observation_context
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import _airport_snapshot as io
from kortravelmap.client._snapshot_atomic import run_snapshot_apply_postprocess
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import encode_provider_snapshot_artifact
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits
from tests.integration.test_airport_snapshot_scheduled_runner import (
    _cancel_if_ready,
    _context,
    _durable_state,
    _scheduled,
)
from tests.integration.test_airport_snapshot_scheduled_runner import (
    airport_baseline as airport_baseline,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_transport_airport_evidence_reader import _bundle
from tests.unit.test_provider_snapshot_artifact import _PINS

pytestmark = [pytest.mark.integration, pytest.mark.timeout(50)]


def _unreachable_postprocess(_observed):
    raise AssertionError("selected stale must abort before postprocess")


async def test_selected_stale_rolls_back_before_live_bound_reset_is_rejected(
    scalar_engines, airport_baseline, request
):
    admin, runtime = scalar_engines
    dataset, feature_ids = airport_baseline
    with DagsterInstance.ephemeral() as instance:
        context, client, identity = await _scheduled(admin, runtime, instance, dataset)
        bundle = await _bundle(0, observed=2)
        geo = _context()
        payload = encode_provider_snapshot_artifact((bundle,), geo, pins=_PINS)
        observation = encode_airport_observation_context(
            payload,
            pins=_PINS,
            root_run_id=context.run_id,
            observation_generation=context.run_id,
            upstream_eof=True,
            geo_stats=GeoCallStats(observed_data_tokens=set(geo.observed_data_tokens)),
        )
        registered = await io.register_airport_snapshot(
            client, identity, payload=payload, context=observation, pins=_PINS
        )
        assert registered.created
        assert registered.token is not None
        token = registered.token
        primary = None
        try:
            saved = await io.read_airport_snapshot(client, identity, pins=_PINS)
            assert saved is not None
            lease = await io.claim_airport_snapshot(client, saved, previous=token)
            assert lease.token == token
            plan = await io.plan_airport_snapshot(
                client, saved, token, pins=_PINS, dataset_id=dataset
            )
            bound = await io.read_airport_snapshot(client, identity, pins=_PINS)
            assert bound is not None
            assert bound.kernel_binding is not None
            assert bound.kernel_binding.attempt_id == plan.attempt_id
            # 계획 뒤 정확한 소유 Feature revision만 바꿔 기존 manifest를 낡게 한다.
            # 원천/후보/Geo/원 artifact는 바꾸지 않으며 source DML 전 재검증이 거부한다.
            async with AsyncSession(admin) as session, session.begin():
                await apply_bounded_transaction_limits(session)
                await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
                rows = await session.scalar(
                    text("""UPDATE feature.features SET row_revision=row_revision+1
                    WHERE feature_id=:feature RETURNING feature_id"""),
                    {"feature": feature_ids[0]},
                )
                assert rows == feature_ids[0]
            before = await _durable_state(
                admin, identity, context.resources.feature_operation_guard.memberships[0]
            )
            apply_txid = None

            async def apply(session):
                nonlocal apply_txid
                apply_txid = await session.scalar(text("SELECT txid_current()"))
                return await io.apply_airport_snapshot_in_session(
                    session, bound, token, plan, pins=_PINS
                )

            with pytest.raises(io.AirportSnapshotReplanRequired) as selected:
                await run_snapshot_apply_postprocess(
                    client,
                    bound,
                    token,
                    identity,
                    pins=_PINS,
                    apply=apply,
                    prepare=_unreachable_postprocess,
                )
            database_error = selected.value.__cause__
            assert isinstance(database_error, DBAPIError)
            assert database_error.orig.sqlstate == "40001"
            cause = database_error.orig.__cause__
            assert cause.sqlstate == "40001"
            assert cause.constraint_name is None
            assert cause.message == "manifest feature changed; replan"
            assert type(apply_txid) is int
            async with AsyncSession(admin) as observer:
                assert (
                    await observer.scalar(
                        text("SELECT pg_xact_status(CAST(:xid AS xid8))"), {"xid": apply_txid}
                    )
                    == "aborted"
                )
                assert (
                    await observer.scalar(
                        text("""SELECT status='ready' AND lease_until>clock_timestamp()
                    FROM ops.feature_write_attempts WHERE attempt_id=:attempt"""),
                        {"attempt": plan.attempt_id},
                    )
                    is True
                )
            assert (
                await _durable_state(
                    admin, identity, context.resources.feature_operation_guard.memberships[0]
                )
                == before
            )
            with pytest.raises(DBAPIError) as rejected:
                await io.reset_airport_snapshot_plan(client, bound, token)
            assert rejected.value.orig.sqlstate == "55P03"
            assert (
                rejected.value.orig.__cause__.message
                == "snapshot kernel plan lease is still active"
            )
            assert (
                await _durable_state(
                    admin, identity, context.resources.feature_operation_guard.memberships[0]
                )
                == before
            )
            request.node.user_properties.extend(
                [
                    ("selected_stale", "40001:manifest feature changed; replan"),
                    ("apply_transaction", "aborted"),
                    ("bound_reset", "55P03:live-ready-lease"),
                    ("snapshot_id", str(token.snapshot_id)),
                    ("artifact_sha256", bound.artifact_sha256),
                ]
            )
        except BaseException as error:
            primary = error
            raise
        finally:
            await _cancel_if_ready(runtime, client, identity, primary)
