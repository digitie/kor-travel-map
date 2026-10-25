"""합성430의 실제 등록/중복/quota/FK 순서 시험. 공통 fixture/권한 우회는 없다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra.feature_operation_repo import ensure_dagster_feature_operation
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_tvn36_override_lineage_spine import _constraint_name

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_AT = datetime(2026, 10, 25, 3, 2, 1, tzinfo=UTC)
_SIGNATURE = "ops.register_provider_snapshot_artifact(uuid,uuid,uuid,bytea,bytea,text,integer)"
_SQL = """SELECT * FROM ops.register_provider_snapshot_artifact(
    CAST(:root AS uuid),CAST(:source AS uuid),CAST(:member AS uuid),
    :payload,:context,:native,:lease)"""


@pytest.fixture
async def registration_engines(scalar_engines):
    admin, runtime = scalar_engines
    async with admin.connect() as connection:
        row = (
            await connection.execute(
                text("""SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner),
                    p.prosecdef,p.proconfig FROM pg_proc p
                    WHERE p.oid=to_regprocedure(:signature)"""),
                {"signature": _SIGNATURE},
            )
        ).one()
        assert row[1] == "ktm_curation_command_owner"
        assert row[2] is True
        assert row[3] == ["search_path=pg_catalog"]
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not await connection.scalar(
                text(
                    "SELECT has_table_privilege('ktm_feature_service',"
                    "'ops.provider_snapshot_artifacts',:privilege)"
                ),
                {"privilege": privilege},
            )
    # 정본 migration/ACL이 없으면 실패한다. 테스트가 함수 설치나 GRANT를 대신하지 않는다.
    return admin, runtime


async def _prepare(admin, runtime, *, status="STARTED"):
    operation = "snapshot-register-" + uuid4().hex
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        dataset = await session.scalar(
            text("""INSERT INTO provider_sync.provider_datasets
                (provider,dataset_key,display_name,source_kind)
                VALUES('kor-travel-transport','transport_airports','owned airport','manual')
                ON CONFLICT(provider,dataset_key) DO UPDATE SET is_active=true
                RETURNING provider_dataset_id""")
        )
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
        # 명시 관리 설정. 기존 reservation의 계수를 0으로 덮지 않는다.
        for key in (0, dataset):
            await session.execute(
                text("""INSERT INTO ops.provider_snapshot_quota_limits
                    (quota_key,max_bytes,max_rows) VALUES(:key,4194304,16)
                    ON CONFLICT(quota_key) DO UPDATE SET
                    max_bytes=ops.provider_snapshot_quota_limits.used_bytes+4194304,
                    max_rows=ops.provider_snapshot_quota_limits.used_rows+16"""),
                {"key": key},
            )
    membership = ProviderDatasetOperationMembership(dataset, "dataset_wide", operation)
    run = "snapshot-register-" + uuid4().hex
    async with AsyncSession(runtime) as session, session.begin():
        result = await ensure_dagster_feature_operation(
            session,
            dagster_run_id=run,
            trigger_kind="manual",
            selected_memberships=(membership,),
            operation_key=operation,
            engine_created_at=_AT,
            engine_started_at=_AT if status == "STARTED" else None,
            observed_status=status,
        )
    op = result.operation
    assert len(op.members) == 1
    member = op.members[0]
    return (
        dataset,
        run,
        membership,
        {
            "root": UUID(op.root_job_id),
            "source": UUID(member.job_id),
            "member": UUID(member.import_job_dataset_id),
            "lease": 60,
        },
    )


async def _wire(run):
    # Root가 합성할 W의 실제 public pure codec. 수기 JSON으로 정상 DTO 권위를 만들지 않는다.
    from kortravelmap.dagster.airport_snapshot_observation import encode_airport_observation_context
    from kortravelmap.infra.provider_snapshot_artifact import (
        SnapshotArtifactPins,
        encode_provider_snapshot_artifact,
    )

    from kortravelmap.providers.kor_travel_transport import TransportAirport
    from kortravelmap.providers.kor_travel_transport_native import (
        AIRPORT_NAME_NORMALIZER_REVISION,
        TransportGeoEvidence,
        transport_item_to_native_bundle,
    )

    pins = SnapshotArtifactPins(
        "a" * 40,
        "b" * 64,
        "kor-travel-transport",
        "transport_airports",
        "airport",
        AIRPORT_NAME_NORMALIZER_REVISION,
        "transport-airport-geo-v1",
        "aware-clock-preserved-v1",
    )
    bundle = await transport_item_to_native_bundle(
        TransportAirport("P01", "공항", "Airport", "ZZZZ", "서울", None, {}),
        fetched_at=_AT,
        geo=TransportGeoEvidence("not_requested"),
    )
    artifact = encode_provider_snapshot_artifact((bundle,), None, pins=pins)
    context = encode_airport_observation_context(
        artifact,
        pins=pins,
        root_run_id=run,
        observation_generation=run,
        upstream_eof=True,
        geo_stats=None,
    )
    return {
        "payload": artifact,
        "context": context,
        "native": json.loads(artifact)["native_input_digest"],
    }


async def _quotas(session, dataset):
    return (
        await session.execute(
            text("""SELECT quota_key,used_bytes,used_rows FROM ops.provider_snapshot_quota_limits
                WHERE quota_key=ANY(CAST(:keys AS bigint[])) ORDER BY quota_key"""),
            {"keys": [0, dataset]},
        )
    ).all()


async def _bounded(session):
    await session.execute(text("SET LOCAL lock_timeout='900ms'"))
    await session.execute(text("SET LOCAL statement_timeout='2s'"))


async def test_actual_service_registration_duplicate_and_outer_rollback(registration_engines):
    admin, runtime = registration_engines
    dataset, run, _, args = await _prepare(admin, runtime)
    args.update(await _wire(run))
    async with AsyncSession(admin) as observer:
        before = await _quotas(observer, dataset)
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(text("SELECT session_user")) == "ktm_feature_service"
        first = (await session.execute(text(_SQL), args)).one()
        assert first.created is True
        assert first.generation == 1
        assert first.fence is not None
    snapshot = first.snapshot_id
    async with AsyncSession(admin) as observer:
        control_before = (
            await observer.execute(
                text("""SELECT executor_generation,executor_fence,lease_expires_at,status
                    FROM ops.provider_snapshot_controls WHERE snapshot_id=:id"""),
                {"id": snapshot},
            )
        ).one()
        after_first = await _quotas(observer, dataset)
        reserved = len(args["payload"]) + len(args["context"]) + 8192
        assert after_first == [(key, size + reserved, rows + 1) for key, size, rows in before]
        row = (
            await observer.execute(
                text("""SELECT artifact_sha256,context_sha256,artifact_payload,observation_context
                    FROM ops.provider_snapshot_artifacts WHERE snapshot_id=:id"""),
                {"id": snapshot},
            )
        ).one()
        assert row == (
            hashlib.sha256(args["payload"]).hexdigest(),
            hashlib.sha256(args["context"]).hexdigest(),
            args["payload"],
            args["context"],
        )
    # 소유 관리자의 무변경 row-lock probe다. duplicate는 quota를 요청하지 않아야 한다.
    async with AsyncSession(admin) as quota_holder, quota_holder.begin():
        await quota_holder.execute(
            text("""SELECT quota_key FROM ops.provider_snapshot_quota_limits
                WHERE quota_key=ANY(CAST(:keys AS bigint[])) ORDER BY quota_key FOR UPDATE"""),
            {"keys": [0, dataset]},
        )
        async with AsyncSession(runtime) as session, session.begin():
            await _bounded(session)
            duplicate = (await session.execute(text(_SQL), args)).one()
            assert tuple(duplicate) == (snapshot, False, None, None)
    async with AsyncSession(admin) as observer:
        assert await _quotas(observer, dataset) == after_first
        assert (
            await observer.execute(
                text("""SELECT executor_generation,executor_fence,lease_expires_at,status
                    FROM ops.provider_snapshot_controls WHERE snapshot_id=:id"""),
                {"id": snapshot},
            )
        ).one() == control_before

    # 별도 member의 미commit 최초등록은 전체 rollback된다. private raw관찰은 관리자만 한다.
    dataset2, run2, _, args2 = await _prepare(admin, runtime)
    args2.update(await _wire(run2))
    async with AsyncSession(admin) as observer:
        before_rollback = await _quotas(observer, dataset2)
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await _bounded(session)
            pending = (await session.execute(text(_SQL), args2)).one()
            assert pending.created
        finally:
            await session.rollback()
    async with AsyncSession(admin) as observer:
        assert await _quotas(observer, dataset2) == before_rollback
        for table in ("artifacts", "controls", "quota_reservations"):
            assert (
                await observer.scalar(
                    text(
                        f"SELECT count(*) FROM ops.provider_snapshot_{table} WHERE snapshot_id=:id"
                    ),
                    {"id": pending.snapshot_id},
                )
                == 0
            )


@pytest.mark.parametrize("changed", ["payload", "context"])
async def test_same_member_different_immutable_bytes_rejected(registration_engines, changed):
    admin, runtime = registration_engines
    dataset, run, _, args = await _prepare(admin, runtime)
    args.update(await _wire(run))
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        first = (await session.execute(text(_SQL), args)).one()
    async with AsyncSession(admin) as observer:
        before = await _quotas(observer, dataset)
    other = dict(args)
    context = json.loads(other["context"])
    if changed == "payload":
        other["payload"] += b" "
        context["artifact_sha256"] = hashlib.sha256(other["payload"]).hexdigest()
    else:
        context["observation_generation"] = run + "::retry:1"
    other["context"] = json.dumps(context, separators=(",", ":"), sort_keys=True).encode()
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await _bounded(session)
            with pytest.raises(DBAPIError) as caught:
                await session.execute(text(_SQL), other)
            assert _constraint_name(caught.value) == "ck_provider_snapshot_immutable_input"
        finally:
            await session.rollback()
    async with AsyncSession(admin) as observer:
        assert await _quotas(observer, dataset) == before
        assert (
            await observer.scalar(
                text("SELECT count(*) FROM ops.provider_snapshot_artifacts WHERE snapshot_id=:id"),
                {"id": first.snapshot_id},
            )
            == 1
        )


@pytest.mark.parametrize(
    "broken",
    [
        "domain",
        "root",
        "sha",
        "count",
        "eof",
        "lease",
        "geo_int",
        "geo_array",
        "geo_str",
        "geo_bool",
    ],
)
async def test_invalid_header_or_lease_has_no_registration(registration_engines, broken):
    admin, runtime = registration_engines
    dataset, run, _, args = await _prepare(admin, runtime)
    args.update(await _wire(run))
    context = json.loads(args["context"])
    field, value = {
        "domain": ("domain", "wrong"),
        "root": ("root_run_id", "another-run"),
        "sha": ("artifact_sha256", "0" * 64),
        "count": ("source_observations", 2),
        "eof": ("upstream_eof", False),
        "geo_int": ("geo_stats", 1),
        "geo_array": ("geo_stats", []),
        "geo_str": ("geo_stats", "invalid"),
        "geo_bool": ("geo_stats", False),
        "lease": ("domain", context["domain"]),
    }[broken]
    context[field] = value
    args["context"] = json.dumps(context, separators=(",", ":"), sort_keys=True).encode()
    if broken == "lease":
        args["lease"] = 4
    async with AsyncSession(admin) as observer:
        before = await _quotas(observer, dataset)
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await _bounded(session)
            with pytest.raises(DBAPIError) as caught:
                await session.execute(text(_SQL), args)
            if broken != "lease":
                assert _constraint_name(caught.value) == "ck_provider_snapshot_registration_domain"
            else:
                assert caught.value.orig.sqlstate == "22023"
        finally:
            await session.rollback()
    async with AsyncSession(admin) as observer:
        assert await _quotas(observer, dataset) == before
        assert (
            await observer.scalar(
                text(
                    "SELECT count(*) FROM ops.provider_snapshot_artifacts "
                    "WHERE import_job_dataset_id=:member"
                ),
                {"member": args["member"]},
            )
            == 0
        )


@pytest.mark.parametrize(
    "quota_case", ["missing_global", "missing_dataset", "full_global", "full_dataset"]
)
async def test_management_quota_fault_rolls_back_all_registration(registration_engines, quota_case):
    admin, runtime = registration_engines
    dataset, run, _, args = await _prepare(admin, runtime)
    args.update(await _wire(run))
    dataset2, run2, _, second = await _prepare(admin, runtime)
    assert dataset2 == dataset
    second.update(await _wire(run2))
    async with AsyncSession(admin) as observer:
        before = await _quotas(observer, dataset)
    # 설정 장애 주입은 소유 관리자 TX다. 실제 LOGIN 정본 성공은 별도 시험에서 검증한다.
    async with AsyncSession(admin) as management:
        await management.begin()
        try:
            await management.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            key = 0 if quota_case.endswith("global") else dataset
            if quota_case.startswith("missing"):
                await management.execute(
                    text("DELETE FROM ops.provider_snapshot_quota_limits WHERE quota_key=:key"),
                    {"key": key},
                )
            else:
                await management.execute(
                    text(
                        "UPDATE ops.provider_snapshot_quota_limits "
                        "SET max_rows=used_rows+1 WHERE quota_key=:key"
                    ),
                    {"key": key},
                )
            await management.execute(text("SET LOCAL ROLE ktm_feature_service"))
            await _bounded(management)
            if quota_case.startswith("full"):
                first = (await management.execute(text(_SQL), args)).one()
                assert first.created
            with pytest.raises(DBAPIError) as caught:
                await management.execute(text(_SQL), second)
            assert _constraint_name(caught.value) == "ck_provider_snapshot_quota_available"
        finally:
            await management.rollback()
    async with AsyncSession(admin) as observer:
        assert await _quotas(observer, dataset) == before
        assert (
            await observer.scalar(
                text("""SELECT count(*) FROM ops.provider_snapshot_artifacts
                WHERE import_job_dataset_id=ANY(CAST(:members AS uuid[]))"""),
                {"members": [args["member"], second["member"]]},
            )
            == 0
        )


async def test_registration_waits_for_leaf_root_before_quota_then_completes(registration_engines):
    admin, runtime = registration_engines
    dataset, run, membership, args = await _prepare(admin, runtime)
    args.update(await _wire(run))
    task = None
    started = asyncio.Event()
    waiter_pid = None
    pending_snapshot = None

    async def register_waiter():
        nonlocal waiter_pid, pending_snapshot
        async with AsyncSession(runtime) as session:
            await session.begin()
            try:
                await _bounded(session)
                waiter_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                started.set()
                result = (await session.execute(text(_SQL), args)).one()
                pending_snapshot = result.snapshot_id
                assert result.created
                return result
            finally:
                await session.rollback()

    async with AsyncSession(runtime) as leaf:
        await leaf.begin()
        try:
            await _bounded(leaf)
            leaf_pid = await leaf.scalar(text("SELECT pg_backend_pid()"))
            # 실제 canonical L-only leaf가 root→child/member를 잡은 상태다.
            await ensure_dagster_feature_operation(
                leaf,
                dagster_run_id=run,
                trigger_kind="manual",
                selected_memberships=(membership,),
                operation_key=membership.operation_key,
                engine_created_at=_AT,
                engine_started_at=_AT,
                observed_status="STARTED",
            )
            task = asyncio.create_task(register_waiter())
            await asyncio.wait_for(started.wait(), 1)
            blocked = False
            for _ in range(50):
                async with admin.connect() as observer:
                    blocked = leaf_pid in await observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": waiter_pid},
                    )
                if blocked:
                    break
                await asyncio.sleep(0.01)
            assert blocked
            assert not task.done()
            # 등록은 root KEY SHARE 대기 전 own scope X를 잡았지만 quota는 아직 잡지 않았다.
            async with AsyncSession(admin) as observer, observer.begin():
                await observer.execute(text("SET LOCAL statement_timeout='500ms'"))
                rows = (
                    await observer.execute(
                        text("""SELECT quota_key FROM ops.provider_snapshot_quota_limits
                            WHERE quota_key=ANY(CAST(:keys AS bigint[])) ORDER BY quota_key
                            FOR UPDATE NOWAIT"""),
                        {"keys": [0, dataset]},
                    )
                ).all()
                assert len(rows) == 2
            with pytest.raises(DBAPIError) as caught:
                async with AsyncSession(admin) as observer, observer.begin():
                    await observer.execute(
                        text("""SELECT provider_dataset_id FROM ops.feature_write_dataset_scopes
                            WHERE provider_dataset_id=:dataset FOR UPDATE NOWAIT"""),
                        {"dataset": dataset},
                    )
            assert caught.value.orig.sqlstate == "55P03"
            await leaf.commit()
            result = await asyncio.wait_for(task, 2)
            assert result.created
        finally:
            if leaf.in_transaction():
                await leaf.rollback()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
    async with AsyncSession(admin) as observer:
        assert (
            await observer.scalar(
                text("SELECT count(*) FROM ops.provider_snapshot_artifacts WHERE snapshot_id=:id"),
                {"id": pending_snapshot},
            )
            == 0
        )


async def test_queued_root_rejected_by_actual_service(registration_engines):
    admin, runtime = registration_engines
    dataset, run, _, args = await _prepare(admin, runtime, status="QUEUED")
    args.update(await _wire(run))
    async with AsyncSession(admin) as observer:
        before = await _quotas(observer, dataset)
    async with AsyncSession(runtime) as session:
        await session.begin()
        try:
            await _bounded(session)
            with pytest.raises(DBAPIError) as caught:
                await session.execute(text(_SQL), args)
            assert _constraint_name(caught.value) == "ck_provider_snapshot_member_binding"
        finally:
            await session.rollback()
    async with AsyncSession(admin) as observer:
        assert await _quotas(observer, dataset) == before
        assert (
            await observer.scalar(
                text(
                    "SELECT count(*) FROM ops.provider_snapshot_artifacts "
                    "WHERE import_job_dataset_id=:member"
                ),
                {"member": args["member"]},
            )
            == 0
        )
