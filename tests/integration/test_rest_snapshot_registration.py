"""Rest432 실제215와 quota/GC의 격리 통합시험. 실제 수용은 실행 결과로 구분한다.

A215와 B admission/GC는 별도150초 owned runner로 선택한다. 이 파일은 한도를 늘리거나
기존 quota를 재설정하지 않는다. GC의 시간/종결 상태 구성은 기존 owned fault fixture다.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID, uuid4

import pytest
from kortravelmap.dagster.rest_snapshot_backend import RestSnapshotBackend
from kortravelmap.dagster.rest_snapshot_observation import (
    RestExportWindow,
    decode_rest_observation_context,
    encode_rest_observation_context,
)
from kortravelmap.dagster.rest_snapshot_postprocess import (
    RestPostprocessMember,
    prepare_rest_snapshot_postprocess,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _rest_snapshot as io
from kortravelmap.client._snapshot_atomic import run_snapshot_apply_postprocess
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.dto.geo_dataset import GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra import feature_repo
from kortravelmap.infra.feature_operation_repo import (
    ensure_dagster_feature_operation,
    reconcile_dagster_feature_run,
)
from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorToken,
    SnapshotMember,
    register_provider_snapshot_artifact,
)
from kortravelmap.infra.rest_area_snapshot_artifact import (
    decode_rest_area_snapshot_artifact,
    encode_rest_area_snapshot_artifact,
)
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits
from kortravelmap.providers import kor_travel_rest_apply as rest_apply
from kortravelmap.providers.kor_travel_transport import TransportCollection
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_registration import _wire as _airport_wire
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_transport_rest_evidence_reader import (
    _PINS,
    _TIME,
    _bundle,
    _context,
    _seed,
)
from tests.integration.test_tvn36_override_lineage_spine import _constraint_name
from tests.unit.test_provider_snapshot_artifact import _PINS as _AIRPORT_PINS

pytestmark = pytest.mark.integration
_OPERATION = "feature_place_transport_rest_areas_job"


@dataclass(frozen=True)
class _Catalog:
    dataset: int
    airport: int
    membership: ProviderDatasetOperationMembership


@dataclass(frozen=True)
class _Member:
    catalog: _Catalog
    run: str
    identity: SnapshotMember
    typed: RestPostprocessMember


@dataclass(frozen=True)
class _Wire:
    payload: bytes
    context: bytes

    @property
    def reserved(self):
        return len(self.payload) + len(self.context) + 8192


@dataclass(frozen=True)
class _PreparedRest:
    client: AsyncKorTravelMapClient
    member: SnapshotMember
    typed_member: RestPostprocessMember
    observed: RecoveredProviderSnapshot
    token: SnapshotExecutorToken
    plan: io.RestSnapshotPlan
    run: str
    pins: SnapshotArtifactPins
    wire: _Wire


async def _limits(session):
    await apply_bounded_transaction_limits(session, statement_timeout_ms=3000, lock_timeout_ms=1000)


async def _quota_state(admin, dataset, airport):
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await _limits(session)
        return [
            tuple(row)
            for row in (
                await session.execute(
                    text("""SELECT quota_key,max_bytes,max_rows,used_bytes,used_rows
                        FROM ops.provider_snapshot_quota_limits
                        WHERE quota_key=ANY(CAST(:keys AS bigint[])) ORDER BY quota_key"""),
                    {"keys": [0, dataset, airport]},
                )
            ).all()
        ]


@pytest.fixture(scope="module", name="rest_catalog")
async def _rest_catalog(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await _limits(session)
        datasets = (
            await session.execute(
                text("""SELECT dataset_key,provider_dataset_id FROM provider_sync.provider_datasets
                    WHERE provider='kor-travel-transport' AND is_active
                    AND dataset_key IN ('transport_airports','transport_rest_areas')
                    ORDER BY dataset_key""")
            )
        ).all()
        assert [row[0] for row in datasets] == ["transport_airports", "transport_rest_areas"]
        airport, dataset = [row[1] for row in datasets]
        operations = (
            await session.execute(
                text("""SELECT operation.operation_key,scope.sync_scope
                    FROM provider_sync.provider_dataset_operations operation
                    JOIN provider_sync.provider_dataset_operation_scopes scope
                        USING(provider_dataset_id,operation_key,operation_kind)
                    WHERE operation.provider_dataset_id=:dataset
                        AND operation.operation_key=:operation
                        AND operation.operation_kind='refresh' AND operation.is_enabled"""),
                {"dataset": dataset, "operation": _OPERATION},
            )
        ).all()
        assert [tuple(row) for row in operations] == [(_OPERATION, "dataset_wide")]
    assert await _quota_state(admin, dataset, airport) == sorted(
        [
            (0, 16 * 1024**2, 256, 0, 0),
            (airport, 4 * 1024**2, 64, 0, 0),
            (dataset, 8 * 1024**2, 16, 0, 0),
        ]
    )
    # function-scope strict_engines에 의존하지 않고 같은 정본 setup만 수행한다.
    async with AsyncSession(admin) as session, session.begin():
        await _limits(session)
        await feature_repo.lock_feature_curation_write(session)
        await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
        await session.execute(text("SELECT feature._install_strict_sh_data_guards()"))
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await _limits(session)
        assert (await session.execute(text("SELECT session_user,current_user"))).one() == (
            "ktm_feature_service",
            "ktm_feature_service",
        )
        assert (
            await session.scalar(
                text("SELECT feature._assert_strict_sh_data_guard_inventory(true)")
            )
            is True
        )
        assert (
            await session.scalar(
                text("""SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgfoid IN (
                'feature._strict_sh_data_statement_guard()'::regprocedure,
                'feature._strict_sh_source_row_guard()'::regprocedure,
                'feature._strict_sh_feature_row_guard()'::regprocedure)""")
            )
            == 33
        )
    return _Catalog(
        dataset, airport, ProviderDatasetOperationMembership(dataset, "dataset_wide", _OPERATION)
    )


@pytest.fixture(scope="module")
async def rest_215_baseline(scalar_engines, rest_catalog):
    admin, runtime = scalar_engines
    return await _seed_rest_baseline(admin, runtime, rest_catalog, count=215)


async def _seed_rest_baseline(admin, runtime, catalog, *, count=2, bundles=None):
    assert type(count) is int
    assert 1 <= count <= 256
    if bundles is None:
        bundles = tuple([await _bundle(i) for i in range(count)])
    assert type(bundles) is tuple
    assert len(bundles) == count
    seeded, ids = await _seed(admin, runtime, bundles)
    assert seeded == catalog.dataset
    assert len(ids) == len(set(ids)) == count
    return tuple(ids)


async def _member(runtime, catalog):
    run = "rest432-" + uuid4().hex
    now = datetime.now(UTC)
    async with AsyncSession(runtime) as session, session.begin():
        await _limits(session)
        mutation = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=run,
            trigger_kind="schedule",
            selected_memberships=(catalog.membership,),
            operation_key=_OPERATION,
            engine_created_at=now,
            engine_started_at=now,
            observed_status="STARTED",
        )
    operation = mutation.operation
    assert operation.dagster_run_id == run
    assert len(operation.members) == 1
    child = operation.members[0]
    assert child.membership == catalog.membership
    root = UUID(operation.root_job_id)
    source = UUID(child.job_id)
    member = UUID(child.import_job_dataset_id)
    return _Member(
        catalog,
        run,
        SnapshotMember(root, source, member),
        RestPostprocessMember(root, source, member, catalog.membership),
    )


async def _wire(member, count=215, observed=1, *, bundles=None):
    if bundles is None:
        bundles = tuple([await _bundle(i, observed=observed) for i in range(count)])
    assert type(bundles) is tuple
    assert len(bundles) == count
    old_geo = _context()
    stats = GeoCallStats(observed_data_tokens=set(old_geo.observed_data_tokens))
    geo = GeoLoadContext(old_geo.geo_applied, old_geo.current_dataset, stats.observed_data_tokens)
    payload = encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)
    captured = bundles[0].source_record.fetched_at
    body = json.dumps(
        {
            "items": [
                {
                    "natural_key": b.source_record.source_entity_id,
                    "name": b.feature.name,
                    "route_name": "경부선",
                    "direction": "상행",
                    "longitude": 127.0,
                    "latitude": 37.5,
                    "phone_number": "031-123-4567",
                    "raw": {},
                }
                for b in bundles
            ],
            "has_more": False,
            "next_cursor": None,
            "collection": {
                "source": "krex_rest_area",
                "last_success_at": _TIME.isoformat(),
                "failed": False,
                "stale": False,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    window = RestExportWindow(
        count,
        len(body),
        hashlib.sha256(body).hexdigest(),
        captured,
        TransportCollection("krex_rest_area", _TIME, False, False),
    )
    context = encode_rest_observation_context(
        payload,
        pins=_PINS,
        root_run_id=member.run,
        observation_generation=member.run,
        upstream_eof=True,
        geo_stats=stats,
        export_window=window,
    )
    assert len(payload) <= 1024**2
    assert len(context) <= 8192
    return _Wire(payload, context)


def _retarget_wire(wire, original, member):
    # 새 root/member가 같은 불변 원관측을 저장하는 quota admission 시험이다. 새 HTTP가 아니다.
    restored = decode_rest_observation_context(
        wire.context, wire.payload, expected_pins=_PINS, expected_root_run_id=original.run
    )
    context = encode_rest_observation_context(
        wire.payload,
        pins=_PINS,
        root_run_id=member.run,
        observation_generation=member.run,
        upstream_eof=True,
        geo_stats=restored.geo_stats,
        export_window=restored.export_window,
    )
    return _Wire(wire.payload, context)


async def _prepare_rest_case(admin, runtime, catalog, *, count=2, input_bundles=None, member=None):
    # seed는 caller가 명시한다. real Dagster guard의 기존 member도 그대로 받는다.
    if member is None:
        member = await _member(runtime, catalog)
    else:
        assert isinstance(member, _Member)
        assert member.catalog == catalog
        assert member.typed.membership == catalog.membership
        assert member.identity.root_id == member.typed.root_job_id
        assert member.identity.child_id == member.typed.source_job_id
        assert member.identity.member_id == member.typed.import_job_dataset_id
    wire = await _wire(member, count=count, bundles=input_bundles)
    client = AsyncKorTravelMapClient(runtime)
    preparation = await io.prepare_rest_snapshot_input(
        client, wire.payload, pins=_PINS, dataset_id=catalog.dataset
    )
    assert preparation.eligible is True
    assert preparation.reason == "unchanged_reobservation"
    assert preparation.evidence.evidence_complete
    assert preparation.evidence.db_scope_eof
    assert len(preparation.evidence.items) == count
    registered = await io.register_rest_snapshot(
        client, member.identity, payload=wire.payload, context=wire.context, pins=_PINS
    )
    assert registered.created
    assert registered.token is not None
    observed = await io.read_rest_snapshot(client, member.identity, pins=_PINS)
    assert observed is not None
    assert observed.status == "prepared"
    lease = await io.claim_rest_snapshot(client, observed, previous=registered.token)
    observed = await io.read_rest_snapshot(client, member.identity, pins=_PINS)
    assert observed is not None
    plan = await io.plan_rest_snapshot(
        client, observed, lease.token, pins=_PINS, dataset_id=catalog.dataset
    )
    observed = await io.read_rest_snapshot(client, member.identity, pins=_PINS)
    assert observed is not None
    assert observed.kernel_binding is not None
    assert observed.kernel_binding.attempt_id == plan.attempt_id
    return _PreparedRest(
        client, member.identity, member.typed, observed, lease.token, plan, member.run, _PINS, wire
    )


async def _register_in(session, member, wire):
    return await register_provider_snapshot_artifact(
        session,
        member.identity,
        artifact_payload=wire.payload,
        observation_context=wire.context,
        expected_pins=_PINS,
        lease_seconds=60,
    )


async def _snapshot_count(admin, root_ids):
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await _limits(session)
        return await session.scalar(
            text(
                "SELECT count(*) FROM ops.provider_snapshot_artifacts "
                "WHERE root_job_id=ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": root_ids},
        )


async def test_a_original_215_apply_required_postprocess_one_commit_and_separate_seal(
    scalar_engines, rest_catalog, rest_215_baseline, request, monkeypatch
):
    admin, runtime = scalar_engines
    started, cpu = time.perf_counter(), time.process_time()
    case = await _prepare_rest_case(admin, runtime, rest_catalog, count=215)
    member = _Member(rest_catalog, case.run, case.member, case.typed_member)
    client, wire, observed, plan = case.client, case.wire, case.observed, case.plan
    original_evidence = copy.deepcopy(plan.preparation.evidence)
    metrics = {"reader_calls": [], "decode_seconds": [], "assessment_seconds": []}
    original_reader = rest_apply._read_locked_evidence
    original_decode = rest_apply.decode_transport_rest_evidence
    original_assess = rest_apply.assess_transport_rest_area_reobservation_evidence

    async def settings(session):
        rows = (
            await session.execute(
                text(
                    "SELECT name,setting,session_user,current_user FROM pg_settings "
                    "WHERE name IN ('statement_timeout','lock_timeout') ORDER BY name"
                )
            )
        ).all()
        assert {(row[2], row[3]) for row in rows} == {
            ("ktm_feature_service", "ktm_feature_service")
        }
        return {str(row[0]): int(row[1]) for row in rows}

    async def measured_reader(session, dataset):
        prior = await settings(session)
        scalar = session.scalar

        async def measured_scalar(statement, *args, **kwargs):
            assert (
                str(statement) == "SELECT feature.read_transport_rest_snapshot_evidence(:dataset)"
            )
            active = await settings(session)
            assert 0 < active["statement_timeout"] <= 3000
            assert 0 < active["lock_timeout"] <= 1000
            clock = time.perf_counter()
            try:
                return await scalar(statement, *args, **kwargs)
            finally:
                metrics["reader_calls"].append(
                    {
                        "server_settings_ms": active,
                        "client_roundtrip_seconds": time.perf_counter() - clock,
                    }
                )

        with monkeypatch.context() as local:
            local.setattr(session, "scalar", measured_scalar)
            raw = await original_reader(session, dataset)
        assert await settings(session) == prior
        return raw

    def measured_decode(*args, **kwargs):
        clock = time.perf_counter()
        try:
            return original_decode(*args, **kwargs)
        finally:
            metrics["decode_seconds"].append(time.perf_counter() - clock)

    async def measured_assess(*args, **kwargs):
        clock = time.perf_counter()
        try:
            return await original_assess(*args, **kwargs)
        finally:
            metrics["assessment_seconds"].append(time.perf_counter() - clock)

    monkeypatch.setattr(rest_apply, "_read_locked_evidence", measured_reader)
    monkeypatch.setattr(rest_apply, "decode_transport_rest_evidence", measured_decode)
    monkeypatch.setattr(
        rest_apply, "assess_transport_rest_area_reobservation_evidence", measured_assess
    )
    atomic_started = time.perf_counter()
    try:
        completion = await run_snapshot_apply_postprocess(
            client,
            observed,
            case.token,
            member.identity,
            pins=_PINS,
            apply=partial(
                io.apply_rest_snapshot_in_session,
                observed=observed,
                token=case.token,
                plan=plan,
                pins=_PINS,
            ),
            prepare=RestSnapshotBackend(member.typed, _PINS, member.run).prepare,
        )
    finally:
        atomic_elapsed = time.perf_counter() - atomic_started
        request.node.user_properties.append(
            ("rest432_locked_reader", json.dumps(metrics, sort_keys=True))
        )
    assert (
        len(metrics["reader_calls"])
        == len(metrics["decode_seconds"])
        == len(metrics["assessment_seconds"])
        == 1
    )
    assert completion.result.load.bundles_total == 215
    assert completion.result.retired == 0
    assert 0 < completion.result.load.curation_input_member_count <= 2730
    assert len(completion.result.load.curation_input_set_hash) == 64
    fresh = await io.read_rest_snapshot(client, member.identity, pins=_PINS)
    assert fresh is not None
    assert fresh.status == "postprocessed"
    assert fresh.applied_result == completion.result
    assert fresh.applied_result_bytes is not None
    assert fresh.postprocess_receipt == completion.receipt
    intent = prepare_rest_snapshot_postprocess(
        member=member.typed,
        artifact_bytes=fresh.artifact_payload,
        context_bytes=fresh.observation_context,
        result_bytes=fresh.applied_result_bytes,
        expected_pins=_PINS,
        expected_root_run_id=member.run,
    )
    assert intent.receipt_candidate == completion.receipt
    assert intent.observation.observation_generation == member.run
    assert intent.observation.fetched_at == _TIME + timedelta(hours=1)
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await _limits(session)
        state = (
            await session.execute(
                text("""SELECT run.status,run.source_observations,
            run.findings_observed,run.findings_unique,run.findings_upserted,
            (SELECT count(*) FROM ops.integrity_finding_observations obs
             WHERE obs.observation_run_id=run.observation_run_id)
            FROM ops.integrity_observation_runs run
            JOIN ops.integrity_observation_scopes scope USING(integrity_observation_scope_id)
            WHERE scope.provider_dataset_id=:dataset AND run.external_run_id=:run"""),
                {"dataset": rest_catalog.dataset, "run": member.run},
            )
        ).one()
        assert tuple(state) == (
            "authoritative",
            215,
            len(intent.findings),
            len({x.dedupe_key for x in intent.findings}),
            len({x.dedupe_key for x in intent.findings}),
            len({x.dedupe_key for x in intent.findings}),
        )
        cursor = await session.scalar(
            text("""SELECT cursor FROM provider_sync.provider_sync_state
            WHERE provider_dataset_id=:dataset AND sync_scope='dataset_wide'
                AND operation_key=:operation"""),
            {"dataset": rest_catalog.dataset, "operation": _OPERATION},
        )
        assert cursor == intent.cursor
    after = await io.prepare_rest_snapshot_input(
        client, wire.payload, pins=_PINS, dataset_id=rest_catalog.dataset
    )
    assert after.eligible
    assert after.evidence.evidence_complete
    assert after.evidence.db_scope_eof
    assert {UUID(item["feature"]["feature_id"]) for item in after.evidence.items} == set(
        rest_215_baseline
    )
    before_items = {
        item["source_entity"]["source_entity_key"]: item for item in original_evidence.items
    }
    after_items = {
        item["source_entity"]["source_entity_key"]: item for item in after.evidence.items
    }
    assert before_items.keys() == after_items.keys()
    assert after.evidence.policy_epoch == original_evidence.policy_epoch
    stored = decode_rest_area_snapshot_artifact(wire.payload, expected_pins=_PINS)
    incoming = {bundle.source_record.source_entity_id: bundle for bundle in stored.bundles}
    for key, current in after_items.items():
        previous = before_items[key]
        old_base = {row["field_path"]: row for row in previous["non_scalar_base"]}
        new_base = {row["field_path"]: row for row in current["non_scalar_base"]}
        assert len(old_base) == len(new_base) == 23
        assert new_base == old_base
        # scalar 재관측의 row_revision 외 비scalar/Geo/policy 값과 lineage는 그대로다.
        assert {k: v for k, v in current["feature"].items() if k != "row_revision"} == {
            k: v for k, v in previous["feature"].items() if k != "row_revision"
        }
        for binding in ("claim", "membership", "active_policy", "policy", "geocode_stamp"):
            assert current[binding] == previous[binding]
        record = incoming.pop(current["source_entity"]["source_entity_id"]).source_record
        assert current["source_head"]["source_entity_key"] == key
        assert current["source_head"]["current_source_record_key"] == record.source_record_key
        assert current["current_record"]["source_record_key"] == record.source_record_key
        assert current["current_record"]["raw_payload_hash"] == record.raw_payload_hash
        # head는 입력의 관측(imported) 시각, immutable row는 최초 raw 수집 시각을 보존한다.
        assert datetime.fromisoformat(current["source_head"]["observed_at"]) == record.imported_at
        assert current["current_record"] == previous["current_record"]
        assert record.fetched_at == _TIME + timedelta(hours=1)
    assert not incoming
    await io.seal_rest_snapshot(
        client,
        case.token,
        artifact_sha256=fresh.artifact_sha256,
        context_sha256=fresh.context_sha256,
        result_sha256=hashlib.sha256(fresh.applied_result_bytes).hexdigest(),
        postprocess_sha256=hashlib.sha256(completion.receipt).hexdigest(),
    )
    sealed = await io.read_rest_snapshot(client, member.identity, pins=_PINS)
    assert sealed is not None
    assert sealed.status == "child_sealed"
    assert sealed.applied_result_bytes == fresh.applied_result_bytes
    assert sealed.postprocess_receipt == completion.receipt
    request.node.user_properties.append(
        (
            "rest432_215",
            json.dumps(
                {
                    "count": 215,
                    "whole_complete": True,
                    "eligible": True,
                    "retired": 0,
                    "artifact_bytes": len(wire.payload),
                    "context_bytes": len(wire.context),
                    "reserved_bytes": wire.reserved,
                    "result_bytes": len(fresh.applied_result_bytes),
                    "receipt_bytes": len(completion.receipt),
                    "atomic_wall_seconds": atomic_elapsed,
                    "client_wall_seconds": time.perf_counter() - started,
                    "client_cpu_seconds": time.process_time() - cpu,
                    "backend_cpu_rss": "unmeasured",
                    "input": "owned synthetic current-export-window; upstreamHTTP0",
                },
                sort_keys=True,
            ),
        )
    )


async def test_b_duplicate_ignores_locked_quota_and_preserves_original_reservation(
    scalar_engines, rest_catalog
):
    admin, runtime = scalar_engines
    member = await _member(runtime, rest_catalog)
    wire = await _wire(member, count=2)
    before = await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport)
    client = AsyncKorTravelMapClient(runtime)
    first = await io.register_rest_snapshot(
        client, member.identity, payload=wire.payload, context=wire.context, pins=_PINS
    )
    assert first.created
    assert first.token is not None
    after = await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport)
    assert after == [
        (
            key,
            maximum,
            rows,
            used + wire.reserved if key in {0, rest_catalog.dataset} else used,
            count + 1 if key in {0, rest_catalog.dataset} else count,
        )
        for key, maximum, rows, used, count in before
    ]
    async with AsyncSession(admin) as holder, holder.begin():
        await _limits(holder)
        await holder.execute(
            text("""SELECT quota_key FROM ops.provider_snapshot_quota_limits
            WHERE quota_key=ANY(CAST(:keys AS bigint[])) ORDER BY quota_key FOR UPDATE"""),
            {"keys": [0, rest_catalog.dataset]},
        )
        duplicate = await io.register_rest_snapshot(
            client, member.identity, payload=wire.payload, context=wire.context, pins=_PINS
        )
        assert duplicate.snapshot_id == first.snapshot_id
        assert duplicate.created is False
        assert duplicate.token is None
    assert await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport) == after


async def test_b_airport_wire_is_rejected_by_rest_db_member_without_reservation(
    scalar_engines, rest_catalog
):
    admin, runtime = scalar_engines
    member = await _member(runtime, rest_catalog)
    airport = await _airport_wire(member.run)
    before = await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport)

    async def attempt():
        async with AsyncSession(runtime) as session, session.begin():
            await _limits(session)
            await register_provider_snapshot_artifact(
                session,
                member.identity,
                artifact_payload=airport["payload"],
                observation_context=airport["context"],
                expected_pins=_AIRPORT_PINS,
                lease_seconds=60,
            )

    with pytest.raises(DBAPIError) as raised:
        await attempt()
    assert raised.value.orig.sqlstate == "23514"
    assert _constraint_name(raised.value) == "ck_provider_snapshot_registration_domain"
    assert await _snapshot_count(admin, [member.identity.root_id]) == 0
    assert await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport) == before


@pytest.mark.parametrize("boundary", ["rows", "bytes"])
async def test_b_actual_fixed_policy_first_overflow_is_53000_and_whole_tx_rolls_back(
    scalar_engines, rest_catalog, boundary, request
):
    admin, runtime = scalar_engines
    before = await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport)
    rest = next(row for row in before if row[0] == rest_catalog.dataset)
    assert rest[1:3] == (8 * 1024**2, 16)
    members = [await _member(runtime, rest_catalog) for _ in range(17)]
    count = 2 if boundary == "rows" else 215
    first_wire = await _wire(members[0], count=count)
    wires = [first_wire] + [
        _retarget_wire(first_wire, members[0], member) for member in members[1:]
    ]
    admitted = 0
    used, rows = rest[3:5]
    expected = 0
    for wire in wires:
        if rows == 16 or wire.reserved > 8 * 1024**2 - used:
            break
        expected += 1
        used += wire.reserved
        rows += 1
    assert 0 < expected < len(members)
    if boundary == "rows":
        assert rows == 16
    else:
        assert rows < 16
        assert wires[expected].reserved > 8 * 1024**2 - used

    async def reserve_until_rejected():
        nonlocal admitted
        async with asyncio.timeout(30):
            async with AsyncSession(runtime) as session, session.begin():
                await _limits(session)
                for member, wire in zip(members, wires, strict=True):
                    registered = await _register_in(session, member, wire)
                    assert registered.created
                    admitted += 1

    with pytest.raises(DBAPIError) as raised:
        await reserve_until_rejected()
    assert raised.value.orig.sqlstate == "53000"
    assert _constraint_name(raised.value) == "ck_provider_snapshot_quota_available"
    assert admitted == expected
    assert await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport) == before
    assert await _snapshot_count(admin, [member.identity.root_id for member in members]) == 0
    request.node.user_properties.append(
        (
            "rest432_quota_" + boundary,
            json.dumps(
                {
                    "initial_used_bytes": rest[3],
                    "initial_used_rows": rest[4],
                    "admitted_before_rollback": admitted,
                    "attempted_reservations": [wire.reserved for wire in wires[: expected + 1]],
                    "sqlstate": "53000",
                    "rollback_exact": True,
                    "quota_max_bytes": rest[1],
                    "quota_max_rows": rest[2],
                },
                sort_keys=True,
            ),
        )
    )


async def _age_owned_snapshot(admin, member, snapshot, *, running):
    # 기존 terminal_gc의 시간구성만 이 실제 Rest 등록에 적용한다. immutable UPDATE/trigger변경0.
    old = datetime.now(UTC) - timedelta(days=8)
    async with AsyncSession(admin) as session, session.begin():
        await _limits(session)
        await feature_repo.lock_feature_curation_write(session)
        # 기존 P_EX/fence는 유지하고 첫 data 접근 전 tracking lineage L을 선취득한다.
        await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
        root = (
            await session.execute(
                text(
                    "SELECT created_at,started_at,status,dagster_run_status FROM ops.import_jobs "
                    "WHERE job_id=:root FOR UPDATE"
                ),
                {"root": member.identity.root_id},
            )
        ).one()
        assert root.status == "running"
        assert root.dagster_run_status == "STARTED"
        if not running:
            # 종결은 raw status가 아니라 정본 typed 명령으로 만든다.
            mutation = await reconcile_dagster_feature_run(
                session,
                dagster_run_id=member.run,
                trigger_kind="schedule",
                terminal_status="FAILURE",
                selected_memberships=(member.catalog.membership,),
                operation_key=member.catalog.membership.operation_key,
                engine_created_at=root.created_at,
                engine_started_at=root.started_at,
                engine_finished_at=datetime.now(UTC),
                error=None,
            )
            assert mutation.operation.status == "failed"
            assert len(mutation.operation.members) == 1
            assert mutation.operation.members[0].status == "failed"
        records = []
        for table in ("artifacts", "controls", "quota_reservations"):
            records.append(
                (
                    table,
                    dict(
                        (
                            await session.execute(
                                text(
                                    f"SELECT * FROM ops.provider_snapshot_{table} "
                                    "WHERE snapshot_id=:id"
                                ),
                                {"id": snapshot},
                            )
                        )
                        .mappings()
                        .one()
                    ),
                )
            )
        for table in ("controls", "quota_reservations", "artifacts"):
            await session.execute(
                text(f"DELETE FROM ops.provider_snapshot_{table} WHERE snapshot_id=:id"),
                {"id": snapshot},
            )
        for table, record in records:
            for generated in ("artifact_sha256", "context_sha256", "result_sha256"):
                record.pop(generated, None)
            if table == "artifacts":
                record["created_at"] = old
            elif table == "controls":
                record["updated_at"] = record["lease_expires_at"] = old
            columns = ",".join(record)
            values = ",".join(":" + column for column in record)
            await session.execute(
                text(f"INSERT INTO ops.provider_snapshot_{table}({columns}) VALUES({values})"),
                record,
            )
        # 정본 running/terminal 상태는 유지하고 소유 fixture의 경과 시간만 구성한다.
        for job in (member.identity.root_id, member.identity.child_id):
            await session.execute(
                text("""UPDATE ops.import_jobs
                SET created_at=:old,started_at=:old,finished_at=:finished
                WHERE job_id=:job"""),
                {
                    "old": old,
                    "finished": None if running else old,
                    "job": job,
                },
            )


async def test_b_rest_gc_preserves_running_then_returns_exact_terminal_reservation(
    scalar_engines, rest_catalog
):
    admin, runtime = scalar_engines
    member = await _member(runtime, rest_catalog)
    wire = await _wire(member, count=2)
    client = AsyncKorTravelMapClient(runtime)
    registered = await io.register_rest_snapshot(
        client, member.identity, payload=wire.payload, context=wire.context, pins=_PINS
    )
    assert registered.created
    await _age_owned_snapshot(admin, member, registered.snapshot_id, running=True)
    before = await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport)
    assert await io.collect_expired_rest_snapshots(client) == 0
    assert await _snapshot_count(admin, [member.identity.root_id]) == 1
    await _age_owned_snapshot(admin, member, registered.snapshot_id, running=False)
    async with AsyncSession(admin) as observer:
        jobs = (
            await observer.execute(
                text(
                    "SELECT job_id,to_jsonb(j) FROM ops.import_jobs j "
                    "WHERE job_id IN (:root,:child) ORDER BY job_id"
                ),
                {"root": member.identity.root_id, "child": member.identity.child_id},
            )
        ).all()
    async with AsyncSession(runtime) as session:
        await _limits(session)
        assert await session.scalar(text("SELECT ops.collect_expired_provider_snapshots(1)")) == 1
        await session.rollback()
    assert await _snapshot_count(admin, [member.identity.root_id]) == 1
    assert await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport) == before
    assert await io.collect_expired_rest_snapshots(client) == 1
    assert await _snapshot_count(admin, [member.identity.root_id]) == 0
    assert await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport) == [
        (
            key,
            maximum,
            rows,
            used - wire.reserved if key in {0, rest_catalog.dataset} else used,
            count - 1 if key in {0, rest_catalog.dataset} else count,
        )
        for key, maximum, rows, used, count in before
    ]
    async with AsyncSession(admin) as observer:
        assert (
            await observer.execute(
                text(
                    "SELECT job_id,to_jsonb(j) FROM ops.import_jobs j "
                    "WHERE job_id IN (:root,:child) ORDER BY job_id"
                ),
                {"root": member.identity.root_id, "child": member.identity.child_id},
            )
        ).all() == jobs
    assert await io.collect_expired_rest_snapshots(client) == 0


async def test_same_member_physical_registration_reserves_once_and_hides_duplicate_nonce(
    scalar_engines, rest_catalog, request
):
    # 두 별도 Service 연결의 실제 대기 후 immutable 저장과 최초 nonce의 단일성을 확인한다.
    from kortravelmap.infra.provider_snapshot_recovery_repo import read_provider_snapshot_for_member
    from tests.integration.test_rest_snapshot_two_writers import _exact_blocker, _wait_stage

    admin, runtime = scalar_engines
    member = await _member(runtime, rest_catalog)
    wire = await _wire(member, count=2)
    before = await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport)
    held, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    identities = {}
    tasks = []

    async def actor(name):
        async with AsyncSession(runtime) as session, session.begin():
            await _limits(session)
            identity = tuple(
                (
                    await session.execute(
                        text(
                            "SELECT pid,backend_start,usename FROM pg_stat_activity "
                            "WHERE pid=pg_backend_pid()"
                        )
                    )
                ).one()
            )
            assert identity[1] is not None
            assert identity[2] == "ktm_feature_service"
            identities[name] = identity
            if name == "duplicate":
                started.set()
            registered = await _register_in(session, member, wire)
            observed = await read_provider_snapshot_for_member(
                session, member.identity, expected_pins=_PINS
            )
            assert observed is not None
            assert observed.snapshot_id == registered.snapshot_id
            assert observed.artifact_payload == wire.payload
            assert observed.observation_context == wire.context
            assert observed.status == "prepared"
            assert observed.kernel_binding is None
            if name == "first":
                held.set()
                await release.wait()
        return registered, observed.lease_expires_at

    primary = None
    try:
        async with asyncio.timeout(15):
            first_task = asyncio.create_task(actor("first"))
            tasks.append(first_task)
            await _wait_stage(first_task, held)
            duplicate_task = asyncio.create_task(actor("duplicate"))
            tasks.append(duplicate_task)
            await _wait_stage(duplicate_task, started)
            wait_event = await _exact_blocker(
                admin, identities["duplicate"], identities["first"], duplicate_task
            )
            release.set()
            (first, first_expiry), (duplicate, duplicate_expiry) = await asyncio.gather(*tasks)
    except BaseException as error:
        primary = error
        raise
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        try:
            async with asyncio.timeout(5):
                await asyncio.gather(*tasks, return_exceptions=True)
        except BaseException as cleanup_error:
            if primary is None:
                raise
            primary.add_note("registration actor drain: " + type(cleanup_error).__name__)

    assert first.created is True
    assert first.token is not None
    assert first.token.generation == 1
    assert duplicate.created is False
    assert duplicate.token is None
    assert duplicate.snapshot_id == first.snapshot_id
    assert duplicate_expiry == first_expiry
    after = await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport)
    assert after == [
        (
            key,
            maximum,
            rows,
            used + wire.reserved if key in {0, rest_catalog.dataset} else used,
            count + 1 if key in {0, rest_catalog.dataset} else count,
        )
        for key, maximum, rows, used, count in before
    ]
    assert await _snapshot_count(admin, [member.identity.root_id]) == 1

    async def stored_rows():
        async with AsyncSession(admin) as session, session.begin():
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await _limits(session)
            return (
                await session.execute(
                    text("""SELECT a.artifact_payload,a.observation_context,
                    c.executor_generation,c.executor_fence,c.lease_expires_at,c.status,
                    q.reserved_bytes FROM ops.provider_snapshot_artifacts a
                    JOIN ops.provider_snapshot_controls c USING(snapshot_id)
                    JOIN ops.provider_snapshot_quota_reservations q USING(snapshot_id)
                    WHERE a.root_job_id=:root AND a.source_job_id=:child
                    AND a.import_job_dataset_id=:member"""),
                    {
                        "root": member.identity.root_id,
                        "child": member.identity.child_id,
                        "member": member.identity.member_id,
                    },
                )
            ).all()

    original = await stored_rows()
    assert len(original) == 1
    assert tuple(original[0]) == (
        wire.payload,
        wire.context,
        first.token.generation,
        first.token.fence,
        first_expiry,
        "prepared",
        wire.reserved,
    )
    restored = decode_rest_observation_context(
        wire.context, wire.payload, expected_pins=_PINS, expected_root_run_id=member.run
    )
    changed = _Wire(
        wire.payload,
        encode_rest_observation_context(
            wire.payload,
            pins=_PINS,
            root_run_id=member.run,
            observation_generation=member.run + "::retry:1",
            upstream_eof=True,
            geo_stats=restored.geo_stats,
            export_window=restored.export_window,
        ),
    )
    assert changed.context != wire.context

    async def changed_input():
        async with AsyncSession(runtime) as session, session.begin():
            await _limits(session)
            await _register_in(session, member, changed)

    with pytest.raises(DBAPIError) as raised:
        await changed_input()
    assert raised.value.orig.sqlstate == "23514"
    assert _constraint_name(raised.value) == "ck_provider_snapshot_immutable_input"
    assert await stored_rows() == original
    assert await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport) == after
    request.node.user_properties.append(
        (
            "rest432_same_member_registration",
            json.dumps(
                {
                    "physical_backends": 2,
                    "exact_blocker": True,
                    "wait_event": wait_event,
                    "immutable_rows": 1,
                    "reservation_rows": 1,
                    "reserved_bytes": wire.reserved,
                    "quota_charges": 1,
                    "created_first_only": True,
                    "duplicate_nonce_absent": True,
                    "lease_unchanged": True,
                    "different_input_sqlstate": "23514",
                    "different_input_constraint": "ck_provider_snapshot_immutable_input",
                },
                sort_keys=True,
            ),
        )
    )
