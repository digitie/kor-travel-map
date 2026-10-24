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


async def _full_plan(runtime, dataset, items, *, bundles=None, geo=None, retire=False):
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
            exclusive_protocol=True,
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
