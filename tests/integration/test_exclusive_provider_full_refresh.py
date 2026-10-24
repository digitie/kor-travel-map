"""명시 EX 전체 적재의 실제 legacy 실패와 원자 복구를 검증한다."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import exclusive_provider_refresh as full
from kortravelmap.infra import feature_repo
from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    append_scoped_feature_write_manifest,
    claim_scoped_feature_write,
    seal_scoped_feature_write_manifest,
)
from tests.integration.test_scoped_native_scalar_refresh import scalar_container as scalar_container
from tests.integration.test_scoped_native_scalar_refresh import scalar_engines as scalar_engines
from tests.integration.test_scoped_provider_batch import _seed

pytestmark = pytest.mark.integration


async def test_active_primary_legacy_refresh_before(scalar_engines):
    admin, runtime = scalar_engines
    _, items = await _seed(admin, runtime)
    with pytest.raises(DBAPIError) as caught:
        async with AsyncSession(runtime) as session, session.begin():
            await feature_repo.load_bundles(session, [item.bundle for item in items])
    assert caught.value.orig.sqlstate == "23514"


async def _full_plan(
    runtime, dataset, items, *, bundles=None, geo=None, retire=False, exclusive=True
):
    inputs = [item.bundle for item in items] if bundles is None else bundles
    targets = {item.feature_id: 1 for item in items}
    kwargs = dict(
        dataset_id=dataset,
        provider=inputs[0].source_record.provider,
        dataset_key=inputs[0].source_record.dataset_key,
        source_entity_type=inputs[0].source_record.source_entity_type,
        active_targets=targets,
        geo=geo,
        retire_geometryless_areas=retire,
    )
    fingerprint = full.exclusive_provider_snapshot_input_digest(inputs, **kwargs)
    attempt, owner = uuid4(), uuid4()
    async with AsyncSession(runtime) as session, session.begin():
        dependencies = {}
        for item in items:
            feature = item.feature_id
            row = (
                await session.execute(
                    text("""SELECT row_revision,
                    ops.scoped_feature_write_membership_digest(feature_id)
                FROM feature.features WHERE feature_id=:id"""),
                    {"id": feature},
                )
            ).one()
            dependencies[("feature", str(feature))] = str(row[0])
            dependencies[("feature_membership", str(feature))] = row[1]
            for entity, key in (
                await session.execute(
                    text("""SELECT source_entity_key,current_source_record_key
                FROM provider_sync.source_links
                JOIN provider_sync.source_entity_heads USING(source_entity_key)
                WHERE feature_id=:id"""),
                    {"id": feature},
                )
            ).all():
                dependencies[("source_head", entity)] = key
        members = [
            ScopedWriteDependency(i, kind, key, value)
            for i, ((kind, key), value) in enumerate(sorted(dependencies.items()))
        ]
        await claim_scoped_feature_write(
            session,
            attempt_id=attempt,
            owner=owner,
            dataset_id=dataset,
            idempotency_key="native-full-refresh-v1:" + fingerprint + ":" + attempt.hex,
            regions=(),
            expected_members=len(members),
            input_digest=fingerprint,
            exclusive_protocol=exclusive,
        )
        await append_scoped_feature_write_manifest(
            session, attempt_id=attempt, owner=owner, members=members
        )
        manifest = await seal_scoped_feature_write_manifest(
            session, attempt_id=attempt, owner=owner
        )
    return inputs, dict(**kwargs, attempt_id=attempt, owner=owner, manifest_digest=manifest)


async def test_explicit_full_refresh_and_completed_replay(scalar_engines):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    inputs, plan = await _full_plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        result = await full.refresh_exclusive_provider_snapshot(session, inputs, **plan)
        assert result.load.bundles_total == 2
        assert not result.replayed
        assert result.attempt["status"] == "completed"
    async with AsyncSession(runtime) as session, session.begin():
        replay = await full.refresh_exclusive_provider_snapshot(session, inputs, **plan)
        assert replay.replayed
        assert replay.load.bundles_total == 0
        assert replay.retired is None
        assert replay.attempt["result_digest"] == result.attempt["result_digest"]


async def test_dynamic_client_final_input_geo_and_category(scalar_engines):
    from kortravelmap.client import AsyncKorTravelMapClient
    from kortravelmap.dto import Address, Coordinate
    from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    inputs = [
        i.bundle.model_copy(
            update={
                "feature": i.bundle.feature.model_copy(
                    update={
                        "category": "01010200",
                        "coord": Coordinate(lon=127.0, lat=37.5),
                        "address": Address(legal="owned geo fixture"),
                    }
                )
            }
        )
        for i in items
    ]
    record = inputs[0].source_record
    geo = GeoLoadContext(
        geo_applied=GeoApplied(reverse=True, geocode=False),
        current_dataset=DatasetRef(version_token="dv1-" + "a" * 32, data_token="dd1-" + "b" * 32),
        observed_data_tokens=frozenset({"dd1-" + "b" * 32}),
    )
    client = AsyncKorTravelMapClient(
        runtime,
        exclusive_provider_snapshot=full.ExclusiveProviderSnapshotOptions(
            provider=record.provider,
            dataset_key=record.dataset_key,
            source_entity_type=record.source_entity_type,
        ),
    )
    load, retired = await client.load_authoritative_feature_snapshot(
        inputs,
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        geo=geo,
        retire_geometryless_areas=True,
    )
    assert load.bundles_total == 2
    assert load.geo_stamps_written == 2
    assert retired == 0
    async with AsyncSession(admin) as session:
        for i in items:
            row = (
                await session.execute(
                    text(
                        """SELECT name,category,ST_X(coord),ST_Y(coord)
                FROM feature.features WHERE feature_id=:id""".replace(
                            "ST_X", "x_extension.ST_X"
                        ).replace("ST_Y", "x_extension.ST_Y")
                    ),
                    {"id": i.feature_id},
                )
            ).one()
            assert tuple(row) == (i.bundle.feature.name, "01010200", 127.0, 37.5)


async def test_completed_old_full_input_cannot_use_new_capture(scalar_engines):
    from kortravelmap.infra.scoped_provider_batch import ProviderScalarRefreshItem
    from tests.integration.test_scoped_provider_batch import _dataset_bundle

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    inputs, plan = await _full_plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        await full.refresh_exclusive_provider_snapshot(session, inputs, **plan)
    nextitems = [
        ProviderScalarRefreshItem(
            i.feature_id,
            _dataset_bundle(
                i.bundle.source_record.dataset_key,
                i.bundle.source_record.source_entity_id,
                "new-head",
                hours=1,
            ),
        )
        for i in items
    ]
    nextinputs, nextplan = await _full_plan(runtime, dataset, nextitems)
    async with AsyncSession(runtime) as session, session.begin():
        await full.refresh_exclusive_provider_snapshot(session, nextinputs, **nextplan)
    with pytest.raises(ValueError, match="stale"):
        async with AsyncSession(runtime) as session, session.begin():
            await full.refresh_exclusive_provider_snapshot(session, inputs, **plan)


async def test_client_second_source_failure_cancels_and_same_input_recovers(
    scalar_engines, monkeypatch
):
    from kortravelmap.client import AsyncKorTravelMapClient

    admin, runtime = scalar_engines
    _, items = await _seed(admin, runtime)
    record = items[0].bundle.source_record
    client = AsyncKorTravelMapClient(
        runtime,
        exclusive_provider_snapshot=full.ExclusiveProviderSnapshotOptions(
            record.provider, record.dataset_key, record.source_entity_type
        ),
    )
    original = feature_repo._upsert_source_record_state
    calls = 0

    async def failing(session, record):
        nonlocal calls
        value = await original(session, record)
        calls += 1
        if calls == 2:
            raise RuntimeError("owned second actual source DML failure")
        return value

    monkeypatch.setattr(feature_repo, "_upsert_source_record_state", failing)
    kwargs = dict(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
    )
    with pytest.raises(RuntimeError, match="second actual"):
        await client.load_authoritative_feature_snapshot([i.bundle for i in items], **kwargs)
    async with AsyncSession(admin) as session:
        rows = (
            (
                await session.execute(
                    text("""SELECT status FROM ops.feature_write_attempts a
            JOIN provider_sync.provider_datasets d USING(provider_dataset_id)
            WHERE d.dataset_key=:key"""),
                    {"key": record.dataset_key},
                )
            )
            .scalars()
            .all()
        )
        assert rows == ["cancelled"]
        names = (
            (
                await session.execute(
                    text(
                        "SELECT name FROM feature.features "
                        "WHERE feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY name"
                    ),
                    {"ids": [i.feature_id for i in items]},
                )
            )
            .scalars()
            .all()
        )
        assert names == ["before-0", "before-1"]
    monkeypatch.setattr(feature_repo, "_upsert_source_record_state", original)
    load, _ = await client.load_authoritative_feature_snapshot([i.bundle for i in items], **kwargs)
    assert load.bundles_total == 2


async def test_mixed_active_existing_new_and_distinct_historical_area_retire(scalar_engines):
    from kortravelmap.infra.feature_identity import resolve_feature_identity
    from tests.integration.test_scoped_provider_batch import _dataset_bundle

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    key = items[0].bundle.source_record.dataset_key
    existing = _dataset_bundle(key, uuid4().hex, "nonactive-existing", hours=-24)
    area = _dataset_bundle(key, uuid4().hex, "historical-geometryless-area", hours=-24)
    new = _dataset_bundle(key, uuid4().hex, "nonactive-new", hours=0)
    async with AsyncSession(runtime) as session, session.begin():
        await feature_repo.load_bundles(session, [existing, area])
        area_id = (await resolve_feature_identity(session, area.feature.feature_id)).feature_id
    # 정본 기존 회귀와 같은 pre-0086 historical shape: subtype 부재의 area.
    # active 데이터나 guard는 손대지 않는다. source entity는 active place와 별개다.
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("DELETE FROM feature.feature_places WHERE feature_id=CAST(:id AS uuid)"),
            {"id": area_id},
        )
        await session.execute(
            text("UPDATE feature.features SET kind='area' WHERE feature_id=CAST(:id AS uuid)"),
            {"id": area_id},
        )
    bundles = [existing, items[1].bundle, new, items[0].bundle]
    inputs, plan = await _full_plan(runtime, dataset, items, bundles=bundles, retire=True)
    async with AsyncSession(runtime) as session, session.begin():
        result = await full.refresh_exclusive_provider_snapshot(session, inputs, **plan)
        assert result.load.bundles_total == 4
        assert result.load.features_inserted == 1
        assert result.retired == 1
        assert result.load.curation_input_member_count == 5
    async with AsyncSession(admin) as session:
        state = (
            await session.execute(
                text(
                    "SELECT lifecycle_state,publication_state FROM feature.features "
                    "WHERE feature_id=CAST(:id AS uuid)"
                ),
                {"id": area_id},
            )
        ).one()
        assert tuple(state) == ("retired", "suppressed")


async def test_completed_replay_rejects_stamp_only_advance(scalar_engines):
    from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)

    def context(char):
        return GeoLoadContext(
            geo_applied=GeoApplied(reverse=True, geocode=False),
            current_dataset=DatasetRef(
                version_token="dv1-" + char * 32, data_token="dd1-" + char * 32
            ),
            observed_data_tokens=frozenset({"dd1-" + char * 32}),
        )

    inputs, oldplan = await _full_plan(runtime, dataset, items, geo=context("a"))
    async with AsyncSession(runtime) as session, session.begin():
        old = await full.refresh_exclusive_provider_snapshot(session, inputs, **oldplan)
    _, newplan = await _full_plan(runtime, dataset, items, geo=context("b"))
    async with AsyncSession(runtime) as session, session.begin():
        new = await full.refresh_exclusive_provider_snapshot(session, inputs, **newplan)
    assert old.load.curation_input_set_hash == new.load.curation_input_set_hash
    with pytest.raises(ValueError, match="stale"):
        async with AsyncSession(runtime) as session, session.begin():
            await full.refresh_exclusive_provider_snapshot(session, inputs, **oldplan)


async def test_planning_bulk_read_and_whole_timeout_roll_back_claim(scalar_engines, monkeypatch):
    import asyncio

    from sqlalchemy import event

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    record = items[0].bundle.source_record
    options = full.ExclusiveProviderSnapshotOptions(
        record.provider, record.dataset_key, record.source_entity_type
    )
    statements = []

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(runtime.sync_engine, "before_cursor_execute", observe)
    sealed = asyncio.Event()
    original = full.seal_scoped_feature_write_manifest

    async def stop_after_seal(*args, **kwargs):
        await original(*args, **kwargs)
        sealed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(full, "seal_scoped_feature_write_manifest", stop_after_seal)
    assert full._PLAN_SECONDS == 30.0
    monkeypatch.setattr(full, "_PLAN_SECONDS", 1.0)
    try:
        with pytest.raises(TimeoutError):
            async with AsyncSession(runtime) as session, session.begin():
                await full.prepare_exclusive_provider_snapshot(
                    session, tuple(i.bundle for i in items), options=options
                )
    finally:
        event.remove(runtime.sync_engine, "before_cursor_execute", observe)
    assert sealed.is_set()
    membership_reads = [
        s for s in statements if "scoped_feature_write_membership_digest(feature_id)" in s
    ]
    assert len(membership_reads) == 1
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM ops.feature_write_attempts WHERE provider_dataset_id=:id"
                ),
                {"id": dataset},
            )
            == 0
        )
    monkeypatch.setattr(full, "seal_scoped_feature_write_manifest", original)
    async with AsyncSession(runtime) as session, session.begin():
        recovered = await full.prepare_exclusive_provider_snapshot(
            session, tuple(i.bundle for i in items), options=options
        )
    assert recovered is not None
    from kortravelmap.infra.scoped_feature_writes import cancel_scoped_feature_write

    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(
            session, attempt_id=recovered.attempt_id, owner=recovered.owner
        )


@pytest.mark.parametrize("mismatch", ["owner", "mode", "target"])
async def test_wrong_binding_rejected_before_source_dml(scalar_engines, monkeypatch, mismatch):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    inputs, plan = await _full_plan(runtime, dataset, items, exclusive=mismatch != "mode")
    calls = 0

    async def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("source DML must not start for mismatched binding")

    monkeypatch.setattr(feature_repo, "_upsert_source_record_state", forbidden)
    if mismatch == "owner":
        plan["owner"] = uuid4()
    elif mismatch == "target":
        plan["active_targets"] = {uuid4(): 1}
    with pytest.raises((ValueError, DBAPIError)) as caught:
        async with AsyncSession(runtime) as session, session.begin():
            await full.refresh_exclusive_provider_snapshot(session, inputs, **plan)
    if mismatch == "owner":
        assert caught.value.orig.sqlstate == "40001"
    assert calls == 0
    from kortravelmap.infra.scoped_feature_writes import cancel_scoped_feature_write

    # 원 owner를 보존한 경우만 즉시 정리한다. 나머지는 소유 fixture 종료로 제거한다.
    if mismatch != "owner":
        async with AsyncSession(runtime) as session, session.begin():
            await cancel_scoped_feature_write(
                session, attempt_id=plan["attempt_id"], owner=plan["owner"]
            )


async def test_repeated_cancel_keeps_original_and_lease_takeover_fences_old_owner(
    scalar_engines, monkeypatch
):
    import asyncio

    import kortravelmap.client as client_module
    from kortravelmap.client import AsyncKorTravelMapClient
    from kortravelmap.infra import scoped_feature_writes as kernel

    admin, runtime = scalar_engines
    _, items = await _seed(admin, runtime)
    record = items[0].bundle.source_record
    client = AsyncKorTravelMapClient(
        runtime,
        exclusive_provider_snapshot=full.ExclusiveProviderSnapshotOptions(
            record.provider, record.dataset_key, record.source_entity_type
        ),
    )
    real_claim = full.claim_scoped_feature_write

    async def short_lease(*args, **kwargs):
        kwargs["lease_seconds"] = 1
        return await real_claim(*args, **kwargs)

    monkeypatch.setattr(full, "claim_scoped_feature_write", short_lease)
    plans = []
    real_prepare = client_module.prepare_exclusive_provider_snapshot

    async def observe_plan(*args, **kwargs):
        value = await real_prepare(*args, **kwargs)
        plans.append(value)
        return value

    monkeypatch.setattr(client_module, "prepare_exclusive_provider_snapshot", observe_plan)
    source_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    real_source = feature_repo._upsert_source_record_state
    calls = 0

    async def suspend_source(*args, **kwargs):
        nonlocal calls
        value = await real_source(*args, **kwargs)
        calls += 1
        if calls == 2:
            source_started.set()
            await asyncio.Event().wait()
        return value

    real_cancel = kernel.cancel_scoped_feature_write

    async def suspend_cleanup(*_args, **_kwargs):
        cleanup_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(feature_repo, "_upsert_source_record_state", suspend_source)
    monkeypatch.setattr(kernel, "cancel_scoped_feature_write", suspend_cleanup)
    kwargs = dict(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
    )
    task = asyncio.create_task(
        client.load_authoritative_feature_snapshot([i.bundle for i in items], **kwargs),
        name="owned-full-cancel-task",
    )
    try:
        await asyncio.wait_for(source_started.wait(), 5)
        task.cancel("owned-first")
        await asyncio.wait_for(cleanup_started.wait(), 5)
        task.cancel("owned-second")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, 3)
        assert caught.value.args == ("owned-first",)
        assert task.done()
        assert runtime.pool.checkedout() == 0
        old = plans[0]
        async with AsyncSession(admin) as session:
            assert (
                await session.scalar(
                    text("SELECT status FROM ops.feature_write_attempts WHERE attempt_id=:id"),
                    {"id": old.attempt_id},
                )
                == "ready"
            )
        monkeypatch.setattr(feature_repo, "_upsert_source_record_state", real_source)
        monkeypatch.setattr(kernel, "cancel_scoped_feature_write", real_cancel)
        await asyncio.sleep(1.1)
        load, _ = await client.load_authoritative_feature_snapshot(
            [i.bundle for i in items], **kwargs
        )
        assert load.bundles_total == 2
        with pytest.raises(DBAPIError) as stale:
            async with AsyncSession(runtime) as session, session.begin():
                await full.refresh_exclusive_provider_snapshot(
                    session,
                    [i.bundle for i in items],
                    dataset_id=old.dataset_id,
                    active_targets=old.active_targets,
                    attempt_id=old.attempt_id,
                    owner=old.owner,
                    manifest_digest=old.manifest_digest,
                    **kwargs,
                )
        assert stale.value.orig.sqlstate == "40001"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_sh_and_full_ex_keep_identical_active_base_semantics(scalar_engines):
    from kortravelmap.infra import scoped_provider_batch
    from tests.integration.test_scoped_provider_batch import _plan

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    shared, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        await scoped_provider_batch.refresh_scoped_provider_scalars_batch(session, items, **shared)

    async def active_bases():
        async with AsyncSession(admin) as session:
            return (
                await session.execute(
                    text("""SELECT feature_id,field_path,provider_dataset_id,
                source_entity_key,source_record_key,source_raw_payload_hash,value_json,
                observed_at,base_revision FROM feature.feature_base_field_values
                WHERE feature_id=ANY(CAST(:ids AS uuid[]))
                AND field_path IN ('core.name','place.phones') ORDER BY feature_id,field_path"""),
                    {"ids": [i.feature_id for i in items]},
                )
            ).all()

    before = await active_bases()
    inputs, exclusive = await _full_plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        await full.refresh_exclusive_provider_snapshot(session, inputs, **exclusive)
    assert await active_bases() == before


async def test_actual_bound_client_rejects_without_committing_caller(scalar_engines):
    from kortravelmap.dagster.feature_update_runner import _bind_client_to_session

    from kortravelmap.client import AsyncKorTravelMapClient

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    record = items[0].bundle.source_record
    client = AsyncKorTravelMapClient(
        runtime,
        exclusive_provider_snapshot=full.ExclusiveProviderSnapshotOptions(
            record.provider, record.dataset_key, record.source_entity_type
        ),
    )
    async with AsyncSession(runtime) as outer, outer.begin():
        bound = await _bind_client_to_session(client, outer)
        with pytest.raises(ValueError, match="transaction-bound"):
            await bound.load_authoritative_feature_snapshot(
                [i.bundle for i in items],
                provider=record.provider,
                dataset_key=record.dataset_key,
                source_entity_type=record.source_entity_type,
            )
        assert outer.in_transaction()
        assert outer.is_active
        assert await outer.scalar(text("SELECT 1")) == 1
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM ops.feature_write_attempts "
                    "WHERE provider_dataset_id=:dataset"
                ),
                {"dataset": dataset},
            )
            == 0
        )


@pytest.mark.parametrize("retired", [False, True])
async def test_shared_historical_area_rebind_rejected_without_fabricated_active(
    scalar_engines, retired
):

    from kortravelmap.infra.feature_identity import resolve_feature_identity
    from tests.integration.test_scoped_provider_batch import _dataset_bundle, _entity

    admin, runtime = scalar_engines
    key = uuid4().hex
    place = _dataset_bundle(key, uuid4().hex, "shared-place", hours=-24)
    area = _dataset_bundle(key, uuid4().hex, "historical-area", hours=-24)
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        dataset = await session.scalar(
            text("""INSERT INTO provider_sync.provider_datasets(
            provider,dataset_key,display_name,source_kind) VALUES(:p,:k,'owned historical','manual')
            RETURNING provider_dataset_id"""),
            {"p": place.source_record.provider, "k": key},
        )
    async with AsyncSession(runtime) as session, session.begin():
        await feature_repo.load_bundles(session, [place, area])
        place_id = (await resolve_feature_identity(session, place.feature.feature_id)).feature_id
        area_id = (await resolve_feature_identity(session, area.feature.feature_id)).feature_id
    # 정본 구형 데이터 모양만 만든다. active policy/guard/claim을 위조하지 않는다.
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("DELETE FROM feature.feature_places WHERE feature_id=CAST(:id AS uuid)"),
            {"id": area_id},
        )
        await session.execute(
            text("UPDATE feature.features SET kind='area' WHERE feature_id=CAST(:id AS uuid)"),
            {"id": area_id},
        )

    if retired:
        async with AsyncSession(runtime) as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT feature_id,CAST(:dataset AS bigint) AS provider_dataset_id "
                            "FROM feature.features WHERE feature_id=CAST(:id AS uuid)"
                        ),
                        {"id": area_id, "dataset": dataset},
                    )
                )
                .mappings()
                .all()
            )
            assert (
                await feature_repo._retire_provider_candidates(
                    session, rows, reason_code="provider_invalid_geometry"
                )
                == 1
            )

    async def rebind():
        async with AsyncSession(admin) as session, session.begin():
            await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            await session.execute(
                text(
                    "UPDATE provider_sync.source_links SET source_entity_key=:entity "
                    "WHERE feature_id=CAST(:id AS uuid)"
                ),
                {"id": area_id, "entity": _entity(place)},
            )

    with pytest.raises(DBAPIError) as caught:
        await rebind()
    assert caught.value.orig.sqlstate == "23514"
    async with AsyncSession(admin) as session:
        current = await session.scalar(
            text(
                "SELECT source_entity_key FROM provider_sync.source_links "
                "WHERE feature_id=CAST(:id AS uuid)"
            ),
            {"id": area_id},
        )
        assert current == _entity(area)
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM feature.provider_field_active_policies "
                    "WHERE feature_id=CAST(:id AS uuid)"
                ),
                {"id": place_id},
            )
            == 0
        )


async def test_new_context_acl_remains_closed(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as session:
        row = (
            await session.execute(
                text("""SELECT
            has_function_privilege(current_user,'feature._exclusive_provider_refresh_context(uuid,bigint)','EXECUTE'),
            has_table_privilege(current_user,'ops.feature_write_attempts','SELECT'),
            has_function_privilege(current_user,'feature.validate_exclusive_provider_snapshot(uuid,bigint,jsonb,text[])','EXECUTE')""")
            )
        ).one()
        assert tuple(row) == (False, False, True)


async def test_fresh_old_input_after_new_head_is_not_false_success(scalar_engines, monkeypatch):
    from kortravelmap.client import AsyncKorTravelMapClient
    from tests.integration.test_scoped_provider_batch import _dataset_bundle

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    old = [i.bundle for i in items]
    record = old[0].source_record
    client = AsyncKorTravelMapClient(
        runtime,
        exclusive_provider_snapshot=full.ExclusiveProviderSnapshotOptions(
            record.provider, record.dataset_key, record.source_entity_type
        ),
    )
    kwargs = dict(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
    )
    # 옛 A는 계획만 만들고 취소한다. completed 재사용이 아닌 fresh A를 뒤에서 호출한다.
    options = client._exclusive_provider_snapshot
    async with AsyncSession(runtime) as session, session.begin():
        a = await full.prepare_exclusive_provider_snapshot(session, tuple(old), options=options)
    await client._cancel_exclusive_snapshot_plan(a)
    newer = [
        _dataset_bundle(record.dataset_key, b.source_record.source_entity_id, "current-B", hours=1)
        for b in old
    ]
    await client.load_authoritative_feature_snapshot(newer, **kwargs)

    async def state():
        async with AsyncSession(admin) as session:
            heads = (
                await session.execute(
                    text("""SELECT h.source_entity_key,h.current_source_record_key
                FROM provider_sync.source_entity_heads h
                JOIN provider_sync.source_entities e USING(source_entity_key)
                WHERE e.provider_dataset_id=:dataset ORDER BY h.source_entity_key"""),
                    {"dataset": dataset},
                )
            ).all()
            capture = await feature_repo.capture_provider_curation_input(
                session, provider=record.provider, dataset_key=record.dataset_key
            )
            return heads, capture.curation_input_set_hash

    before = await state()
    original = feature_repo._upsert_source_record_state
    became = []

    async def observed(session, value):
        result = await original(session, value)
        became.append(result.became_current)
        return result

    monkeypatch.setattr(feature_repo, "_upsert_source_record_state", observed)
    with pytest.raises(DBAPIError) as caught:
        await client.load_authoritative_feature_snapshot(old, **kwargs)
    assert caught.value.orig.sqlstate == "23514"
    assert became == [False]
    assert await state() == before
    async with AsyncSession(admin) as session:
        statuses = (
            await session.execute(
                text("""SELECT status,count(*) FROM ops.feature_write_attempts
            WHERE provider_dataset_id=:dataset GROUP BY status ORDER BY status"""),
                {"dataset": dataset},
            )
        ).all()
        assert dict(statuses) == {"cancelled": 2, "completed": 1}
