"""실제 legacy claim→명시 lab cutover→한 sealed attempt의 두 Feature 원자 적용."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from kortravelmap.core.ids import make_source_record_key
from kortravelmap.infra import feature_repo
from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.feature_identity import resolve_feature_identity
from kortravelmap.infra.feature_repo import _make_source_entity_key
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)
from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    append_scoped_feature_write_manifest,
    claim_scoped_feature_write,
    seal_scoped_feature_write_manifest,
)
from tests.integration.test_scoped_native_scalar_refresh import _bundle
from tests.integration.test_scoped_native_scalar_refresh import (
    scalar_container as scalar_container,
)
from tests.integration.test_scoped_native_scalar_refresh import scalar_engines as scalar_engines

pytestmark = pytest.mark.integration


def _dataset_bundle(dataset, identity, name, *, hours):
    original = _bundle(identity, name, hours=hours)
    record = original.source_record
    key = make_source_record_key(
        provider=record.provider,
        dataset_key=dataset,
        source_entity_type=record.source_entity_type,
        source_entity_id=identity,
        raw_payload_hash=record.raw_payload_hash,
    )
    return original.model_copy(
        update={
            "source_record": record.model_copy(
                update={"dataset_key": dataset, "source_record_key": key}
            ),
            "source_link": original.source_link.model_copy(update={"source_record_key": key}),
        }
    )


async def _seed_bundles(admin, runtime, old, new):
    # 정본 loader는 dataset을 자동 등록하지 않는다. 소유 lab catalog만 사전 선언한다.
    record = old[0].source_record
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("""INSERT INTO provider_sync.provider_datasets(
            provider,dataset_key,display_name,source_kind)
            VALUES(:provider,:key,'owned batch fixture','manual')
            ON CONFLICT(provider,dataset_key) DO NOTHING"""),
            {"provider": record.provider, "key": record.dataset_key},
        )
    # 실제 정본 legacy loader가 canonical UUID/claim/alias와 source/link를 만든다.
    async with AsyncSession(runtime) as session, session.begin():
        await feature_repo.load_bundles(session, old)
        features = []
        for bundle in old:
            identity = await resolve_feature_identity(session, bundle.feature.feature_id)
            assert identity is not None
            features.append(UUID(str(identity.feature_id)))
        record = old[0].source_record
        dataset = await session.scalar(
            text("""SELECT provider_dataset_id
            FROM provider_sync.provider_datasets WHERE provider=:provider AND dataset_key=:key"""),
            {"provider": record.provider, "key": record.dataset_key},
        )
    presence = old[0].provider_field_presence
    fields = sorted(presence.supplied_fields)
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(
            text("""CALL feature.register_provider_field_shadow_policy(
            1,:dataset,:normalizer,CAST(:fields AS jsonb))"""),
            {
                "dataset": dataset,
                "normalizer": presence.normalizer_revision,
                "fields": json.dumps(
                    [
                        {
                            "field_path": field,
                            "provider_rank": 10,
                            "omitted_policy": "carry_forward",
                            "null_policy": "value",
                        }
                        for field in fields
                    ]
                ),
            },
        )
        arm_provider_field_shadow(session, 1)
        for feature, bundle in zip(features, old, strict=True):
            record = bundle.source_record
            entity = _entity(bundle)
            await capture_provider_field_candidates(
                session,
                feature_id=str(feature),
                dataset_id=dataset,
                entity_key=entity,
                record_key=record.source_record_key,
                values=native._provider_scalar_values(bundle, feature_id=feature),
                geometry_wkt="{}",
                presence=bundle.provider_field_presence,
            )
    # 운영 activation이 아니라 소유 fixture에서만 별도 실제 cutover를 수행한다.
    async with AsyncSession(admin) as session, session.begin():
        for feature in features:
            await session.execute(
                text("""CALL feature.activate_provider_field_policy(
                :feature,1,CAST(:fields AS text[]))"""),
                {"feature": feature, "fields": fields},
            )
    items = [batch.ProviderScalarRefreshItem(f, b) for f, b in zip(features, new, strict=True)]
    return dataset, items


async def _seed(admin, runtime, *, count=2):
    dataset_key = "batch-" + uuid4().hex
    keys = [uuid4().hex for _ in range(count)]
    old = [
        _dataset_bundle(dataset_key, key, f"before-{i}", hours=-24) for i, key in enumerate(keys)
    ]
    new = [_dataset_bundle(dataset_key, key, f"after-{i}", hours=0) for i, key in enumerate(keys)]
    return await _seed_bundles(admin, runtime, old, new)


def _entity(bundle):
    record = bundle.source_record
    return _make_source_entity_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
    )


async def _plan(
    runtime,
    dataset,
    items,
    *,
    exclusive=False,
    manifest_items=None,
    omit_head=False,
    retained_heads=None,
    lease_seconds=180,
):
    attempt, owner = uuid4(), uuid4()
    rows = {}
    planned = items if manifest_items is None else manifest_items
    async with AsyncSession(runtime) as session, session.begin():
        pid = await session.scalar(text("SELECT pg_backend_pid()"))
        for item in planned:
            feature = item.feature_id
            revision = await session.scalar(
                text("SELECT row_revision FROM feature.features WHERE feature_id=:id"),
                {"id": feature},
            )
            membership = await session.scalar(
                text("SELECT ops.scoped_feature_write_membership_digest(:id)"), {"id": feature}
            )
            heads = (
                await session.execute(
                    text("""SELECT source_entity_key,current_source_record_key
                FROM provider_sync.source_links
                JOIN provider_sync.source_entity_heads USING(source_entity_key)
                WHERE feature_id=:id ORDER BY source_entity_key"""),
                    {"id": feature},
                )
            ).all()
            for entity, record in heads:
                rows[("source_head", entity)] = record
            rows[("feature", str(feature))] = str(revision)
            rows[("feature_membership", str(feature))] = membership
        if retained_heads is not None:
            for entity, record in retained_heads.items():
                rows[("source_head", entity)] = record
        if omit_head:
            del rows[next(key for key in sorted(rows) if key[0] == "source_head")]
        members = [
            ScopedWriteDependency(i, kind, key, expected)
            for i, ((kind, key), expected) in enumerate(sorted(rows.items()))
        ]
        await claim_scoped_feature_write(
            session,
            attempt_id=attempt,
            owner=owner,
            dataset_id=dataset,
            idempotency_key=uuid4().hex,
            regions=(),
            expected_members=len(members),
            input_digest=batch.scoped_provider_refresh_batch_input_digest(
                items, dataset_id=dataset, policy_revision=1
            ),
            exclusive_protocol=exclusive,
            lease_seconds=lease_seconds,
        )
        for start in range(0, len(members), 256):
            await append_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner, members=members[start : start + 256]
            )
        digest = await seal_scoped_feature_write_manifest(session, attempt_id=attempt, owner=owner)
    return dict(
        dataset_id=dataset,
        policy_revision=1,
        attempt_id=attempt,
        owner=owner,
        manifest_digest=digest,
    ), pid


async def _snapshot(admin, items):
    async with AsyncSession(admin) as session:
        result = []
        for item in sorted(items, key=lambda item: item.feature_id):
            row = (
                await session.execute(
                    text("""SELECT f.name,p.phones,h.current_source_record_key,h.observed_at
                FROM feature.features f JOIN feature.feature_places p USING(feature_id)
                CROSS JOIN provider_sync.source_entity_heads h
                WHERE f.feature_id=:id AND h.source_entity_key=:entity"""),
                    {"id": item.feature_id, "entity": _entity(item.bundle)},
                )
            ).one()
            candidates = (
                await session.execute(
                    text("""SELECT field_path,value_json,value_source_hash,
                validated_source_hash,value_observed_at,validated_at,normalizer_revision
                FROM feature.provider_field_shadow_candidates
                WHERE feature_id=:id ORDER BY field_path"""),
                    {"id": item.feature_id},
                )
            ).all()
            result.append((tuple(row), [tuple(candidate) for candidate in candidates]))
        return result


def _apply(exclusive):
    return (
        batch.refresh_exclusive_provider_scalars_batch
        if exclusive
        else batch.refresh_scoped_provider_scalars_batch
    )


@pytest.mark.parametrize("exclusive", [False, True])
async def test_two_existing_primary_features_one_dataset_finish_once_and_replay_no_dml(
    scalar_engines, monkeypatch, exclusive
):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    plan, _ = await _plan(runtime, dataset, items, exclusive=exclusive)
    original = batch.finish_scoped_feature_write
    finishes = 0

    async def finish(*args, **kwargs):
        nonlocal finishes
        finishes += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(batch, "finish_scoped_feature_write", finish)
    async with AsyncSession(runtime) as session, session.begin():
        receipt = await _apply(exclusive)(session, reversed(items), **plan)
        assert receipt["status"] == "completed"
        assert receipt["exclusive_protocol"] is exclusive
        assert receipt["expected_members"] == 6
    assert finishes == 1
    after = await _snapshot(admin, items)
    for item, state in zip(sorted(items, key=lambda item: item.feature_id), after, strict=True):
        assert state[0][0] == item.bundle.feature.name
        assert state[0][2] == item.bundle.source_record.source_record_key

    async def forbidden(*args, **kwargs):
        pytest.fail("completed batch repeated source/candidate/winner DML or finish")

    for name in (
        "_upsert_source_record_state",
        "capture_provider_field_candidates",
        "recompute_provider_field_candidates",
    ):
        monkeypatch.setattr(native, name, forbidden)
    monkeypatch.setattr(batch, "finish_scoped_feature_write", forbidden)
    async with AsyncSession(runtime) as session, session.begin():
        replay = await _apply(exclusive)(session, items, **plan)
    assert replay == receipt
    assert await _snapshot(admin, items) == after
    # completed라도 caller owner/input/manifest/mode를 바꾼 replay는 허용하지 않는다.
    changed_manifest = ("0" if plan["manifest_digest"][0] != "0" else "1") + plan[
        "manifest_digest"
    ][1:]
    for changed in (plan | {"owner": uuid4()}, plan | {"manifest_digest": changed_manifest}):
        with pytest.raises(DBAPIError):
            async with AsyncSession(runtime) as session, session.begin():
                await _apply(exclusive)(session, items, **changed)
    with pytest.raises(ValueError, match="does not match"):
        async with AsyncSession(runtime) as session, session.begin():
            await _apply(exclusive)(session, items[:1], **plan)
    with pytest.raises(DBAPIError if exclusive else ValueError):
        async with AsyncSession(runtime) as session, session.begin():
            await _apply(not exclusive)(session, items, **plan)
    assert await _snapshot(admin, items) == after


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_second_actual_source_dml_failure_rolls_back_both_and_same_plan_recovers(
    scalar_engines, monkeypatch, failure
):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    plan, _ = await _plan(runtime, dataset, items)
    before = await _snapshot(admin, items)
    original = native._upsert_source_record_state
    writes = 0

    async def fail_second(session, record):
        nonlocal writes
        result = await original(session, record)
        writes += 1
        if writes == 2:
            assert await _snapshot(admin, items) == before
            raise failure("after second actual source DML")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(native, "_upsert_source_record_state", fail_second)
        with pytest.raises(failure):
            async with AsyncSession(runtime) as session, session.begin():
                await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)
    assert writes == 2
    assert await _snapshot(admin, items) == before
    async with AsyncSession(runtime) as session, session.begin():
        assert (await batch.refresh_scoped_provider_scalars_batch(session, items, **plan))[
            "status"
        ] == "completed"
    assert await _snapshot(admin, items) != before


async def test_whole_batch_deadline_after_second_dml_rolls_back_then_fresh_retry(
    scalar_engines, monkeypatch
):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    plan, _ = await _plan(runtime, dataset, items)
    before = await _snapshot(admin, items)
    original = native._upsert_source_record_state
    writes = 0

    async def wait_second(session, record):
        nonlocal writes
        result = await original(session, record)
        writes += 1
        if writes == 2:
            await asyncio.Event().wait()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(batch, "_BATCH_APPLY_SECONDS", 2.0)
        patch.setattr(native, "_upsert_source_record_state", wait_second)
        with pytest.raises(TimeoutError):
            async with AsyncSession(runtime) as session, session.begin():
                await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)
    assert writes == 2
    assert await _snapshot(admin, items) == before
    async with AsyncSession(runtime) as session, session.begin():
        assert (await batch.refresh_scoped_provider_scalars_batch(session, items, **plan))[
            "status"
        ] == "completed"


@pytest.mark.parametrize("exclusive", [False, True])
async def test_batch_cannot_substitute_protocol_mode_or_owner(scalar_engines, exclusive):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    plan, _ = await _plan(runtime, dataset, items, exclusive=exclusive)
    before = await _snapshot(admin, items)
    with pytest.raises(DBAPIError if exclusive else ValueError):
        async with AsyncSession(runtime) as session, session.begin():
            await _apply(not exclusive)(session, items, **plan)
    with pytest.raises(DBAPIError) as error:
        async with AsyncSession(runtime) as session, session.begin():
            await _apply(exclusive)(session, items, **(plan | {"owner": uuid4()}))
    assert getattr(error.value.orig, "sqlstate", None) == "40001"
    assert await _snapshot(admin, items) == before
    async with AsyncSession(runtime) as session, session.begin():
        await _apply(exclusive)(session, items, **plan)


@pytest.mark.parametrize("shape", ["extra-feature", "omitted-feature", "omitted-head"])
async def test_batch_manifest_must_be_exact_complete_feature_source_union(
    scalar_engines, monkeypatch, shape
):
    admin, runtime = scalar_engines
    dataset, all_items = await _seed(admin, runtime, count=3)
    items = all_items[:2]
    planned = (
        all_items
        if shape == "extra-feature"
        else items[:1]
        if shape == "omitted-feature"
        else items
    )
    plan, _ = await _plan(
        runtime, dataset, items, manifest_items=planned, omit_head=shape == "omitted-head"
    )
    before = await _snapshot(admin, all_items)

    async def forbidden(*args, **kwargs):
        pytest.fail("incomplete or extra manifest reached source DML")

    monkeypatch.setattr(native, "_upsert_source_record_state", forbidden)
    with pytest.raises(
        DBAPIError if shape == "omitted-head" else ValueError,
        match=None if shape == "omitted-head" else "complete manifest|does not match",
    ):
        async with AsyncSession(runtime) as session, session.begin():
            await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)
    assert await _snapshot(admin, all_items) == before


async def test_batch_rejects_retained_old_heads_after_valid_native_writer_commit(scalar_engines):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    previous = await _snapshot(admin, items)
    retained = {
        _entity(item.bundle): state[0][2]
        for item, state in zip(
            sorted(items, key=lambda item: item.feature_id), previous, strict=True
        )
    }
    writer_plan, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        await batch.refresh_scoped_provider_scalars_batch(session, items, **writer_plan)
    # 실제로 읽었던 옛 head가 남은 plan이다. 현재 source/candidate/winner는 정상 commit됐다.
    stale_plan, _ = await _plan(runtime, dataset, items, retained_heads=retained)
    before = await _snapshot(admin, items)
    with pytest.raises(DBAPIError) as error:
        async with AsyncSession(runtime) as session, session.begin():
            await batch.refresh_scoped_provider_scalars_batch(session, items, **stale_plan)
    assert getattr(error.value.orig, "sqlstate", None) == "40001"
    assert await _snapshot(admin, items) == before


async def test_late_old_attempt_cannot_apply_after_lease_takeover_new_epoch(scalar_engines):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    old, _ = await _plan(runtime, dataset, items, lease_seconds=1)
    await asyncio.sleep(1.1)
    current, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        await batch.refresh_scoped_provider_scalars_batch(session, items, **current)
    before = await _snapshot(admin, items)
    with pytest.raises(DBAPIError) as error:
        async with AsyncSession(runtime) as session, session.begin():
            await batch.refresh_scoped_provider_scalars_batch(session, items, **old)
    assert getattr(error.value.orig, "sqlstate", None) == "40001"
    assert await _snapshot(admin, items) == before


async def test_same_pool_one_connection_plan_commit_then_apply_fresh_transaction(scalar_engines):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    one = create_async_engine(runtime.url, pool_size=1, max_overflow=0, pool_timeout=1)
    try:
        async with AsyncSession(one) as session, session.begin():
            baseline = (
                await session.execute(
                    text(
                        "SELECT current_setting('statement_timeout'),"
                        "current_setting('lock_timeout')"
                    )
                )
            ).one()
        plan, plan_pid = await _plan(one, dataset, items)
        assert one.pool.checkedout() == 0
        async with AsyncSession(one) as session, session.begin():
            apply_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            assert apply_pid == plan_pid
            receipt = await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)
            assert receipt["status"] == "completed"
        assert one.pool.checkedout() == 0
        async with AsyncSession(one) as session, session.begin():
            assert await session.scalar(text("SELECT pg_backend_pid()")) == plan_pid
            restored = (
                await session.execute(
                    text(
                        "SELECT current_setting('statement_timeout'),"
                        "current_setting('lock_timeout')"
                    )
                )
            ).one()
            assert tuple(restored) == tuple(baseline)
    finally:
        await one.dispose()


async def test_input_changed_after_claim_is_rejected_before_dml_and_original_recovers(
    scalar_engines,
):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    plan, _ = await _plan(runtime, dataset, items)
    before = await _snapshot(admin, items)
    original = items[0].bundle.feature.name
    items[0].bundle.feature.name = "changed-after-claim"
    with pytest.raises(ValueError, match="does not match"):
        async with AsyncSession(runtime) as session, session.begin():
            await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)
    items[0].bundle.feature.name = original
    assert await _snapshot(admin, items) == before
    async with AsyncSession(runtime) as session, session.begin():
        await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)


async def test_batch_waits_for_exact_dataset_scope_before_any_source_dml(
    scalar_engines, monkeypatch
):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    plan, _ = await _plan(runtime, dataset, items)
    started = asyncio.Event()
    waiter = None
    task = None
    writes = 0
    original = native._upsert_source_record_state

    async def counted(session, record):
        nonlocal writes
        writes += 1
        return await original(session, record)

    async def apply():
        nonlocal waiter
        async with AsyncSession(runtime) as session, session.begin():
            waiter = await session.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            return await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)

    monkeypatch.setattr(native, "_upsert_source_record_state", counted)
    try:
        async with AsyncSession(admin) as blocker, blocker.begin():
            owner_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(
                text(
                    "SELECT provider_dataset_id FROM ops.feature_write_dataset_scopes "
                    "WHERE provider_dataset_id=:id FOR UPDATE"
                ),
                {"id": dataset},
            )
            task = asyncio.create_task(apply())
            await asyncio.wait_for(started.wait(), 1)
            blocked = False
            for _ in range(50):
                async with AsyncSession(admin) as observer:
                    blocked = await observer.scalar(
                        text("""SELECT EXISTS(
                        SELECT 1 FROM pg_locks WHERE pid=:waiter AND locktype='transactionid'
                        AND NOT granted AND :owner=ANY(pg_blocking_pids(:waiter)))"""),
                        {"waiter": waiter, "owner": owner_pid},
                    )
                if blocked:
                    break
                await asyncio.sleep(0.01)
            assert blocked
            assert not task.done()
            assert writes == 0
        assert (await asyncio.wait_for(task, 2))["status"] == "completed"
        assert writes == 2
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_oversize_batch_cannot_disturb_previous_completed_set(scalar_engines, monkeypatch):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    plan, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        await batch.refresh_scoped_provider_scalars_batch(session, items, **plan)
    before = await _snapshot(admin, items)

    async def forbidden(*args, **kwargs):
        pytest.fail("over-budget batch reached source DML")

    monkeypatch.setattr(native, "_upsert_source_record_state", forbidden)
    for bad in (
        (
            batch.ProviderScalarRefreshItem(UUID(int=i + 1), items[0].bundle)
            for i in range(batch._MAX_BATCH_ITEMS + 1)
        ),
        [
            batch.ProviderScalarRefreshItem(
                item.feature_id,
                item.bundle.model_copy(
                    update={
                        "source_record": item.bundle.source_record.model_copy(
                            update={"raw_data": {"oversize": "x" * 600_000}}
                        ),
                    }
                ),
            )
            for item in items
        ],
    ):
        with pytest.raises(ValueError, match="bounded|budget|1 MiB"):
            async with AsyncSession(runtime) as session, session.begin():
                await batch.refresh_scoped_provider_scalars_batch(session, bad, **plan)
        assert await _snapshot(admin, items) == before
    async with AsyncSession(runtime) as session, session.begin():
        assert (await batch.refresh_scoped_provider_scalars_batch(session, items, **plan))[
            "status"
        ] == "completed"


async def test_public_heritage_dto_converter_legacy_claim_then_two_item_batch(scalar_engines):
    # 기본 CI provider extra 부재는 명시 skip이며 SDK pin 설치 수용에서는 실제 실행한다.
    sdk = pytest.importorskip("krheritage.models", reason="optional pinned heritage SDK required")
    from datetime import timedelta

    from kortravelmap.providers.krheritage import heritage_items_to_bundles
    from kortravelmap.providers.krheritage_native import (
        HeritageGeoEvidence,
        assess_heritage_name_refresh,
    )
    from tests.integration.test_scoped_native_scalar_refresh import _TIME

    old, new = [], []
    for index in range(2):
        raw = {
            "key": {"ccbaKdcd": "11", "ccbaAsno": str(990010 + index), "ccbaCtcd": "11"},
            "ccbaMnm1": f"기준 유산 {index}",
            "ccmaName": "문화유산",
        }
        for output, name, at in (
            (old, f"기준 유산 {index}", _TIME - timedelta(days=1)),
            (new, f"다음 유산 {index}", _TIME),
        ):
            model = sdk.HeritageDetail.model_validate(raw | {"ccbaMnm1": name})
            bundle = (await heritage_items_to_bundles([model], fetched_at=at))[0]
            output.append(
                bundle.model_copy(
                    update={
                        "source_record": bundle.source_record.model_copy(
                            update={"imported_at": at}
                        ),
                    }
                )
            )
        eligibility = await assess_heritage_name_refresh(
            old[-1].source_record,
            new[-1],
            previous_normalizer_revision="krheritage-name-v1",
            previous_geo=HeritageGeoEvidence("not_requested"),
            current_geo=HeritageGeoEvidence("not_requested"),
            validate=sdk.HeritageDetail.model_validate,
        )
        assert eligibility.eligible
    admin, runtime = scalar_engines
    dataset, items = await _seed_bundles(admin, runtime, old, new)
    plan, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        assert (await batch.refresh_scoped_provider_scalars_batch(session, items, **plan))[
            "status"
        ] == "completed"
    after = await _snapshot(admin, items)
    assert sorted(row[0][0] for row in after) == ["다음 유산 0", "다음 유산 1"]


async def test_same_group_sh_then_ex_preserves_heads_candidates_and_result_digest(scalar_engines):
    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    first, _ = await _plan(runtime, dataset, items)
    async with AsyncSession(runtime) as session, session.begin():
        shared = await batch.refresh_scoped_provider_scalars_batch(session, items, **first)
    expected = await _snapshot(admin, items)
    second, _ = await _plan(runtime, dataset, items, exclusive=True)
    async with AsyncSession(runtime) as session, session.begin():
        exclusive = await batch.refresh_exclusive_provider_scalars_batch(session, items, **second)
    assert shared["input_digest"] == exclusive["input_digest"]
    assert shared["result_digest"] == exclusive["result_digest"]
    assert await _snapshot(admin, items) == expected


@pytest.mark.parametrize("armed", [False, True])
async def test_batch_ex_keeps_short_caller_lock_cap_and_same_artifact_recovers(
    scalar_engines, armed
):
    from kortravelmap.infra.feature_repo import FEATURE_CURATION_WRITE_WAIT_INFO_KEY
    from kortravelmap.infra.scoped_feature_writes import lock_scoped_feature_write_protocol

    admin, runtime = scalar_engines
    dataset, items = await _seed(admin, runtime)
    plan, _ = await _plan(runtime, dataset, items, exclusive=True)
    before = await _snapshot(admin, items)
    async with AsyncSession(runtime) as blocker, blocker.begin():
        await lock_scoped_feature_write_protocol(blocker, exclusive=False)

        async def blocked_apply():
            async with AsyncSession(runtime) as session, session.begin():
                await session.execute(text("SET LOCAL lock_timeout='25ms'"))
                if armed:
                    session.info[FEATURE_CURATION_WRITE_WAIT_INFO_KEY] = 1500
                return await batch.refresh_exclusive_provider_scalars_batch(session, items, **plan)

        with pytest.raises(DBAPIError) as error:
            # 잘못된 1500ms legacy hint로 확대되면 진단용750ms 상한이 실패시킨다.
            await asyncio.wait_for(blocked_apply(), 0.75)
        assert getattr(error.value.orig, "sqlstate", None) == "55P03"
        assert await _snapshot(admin, items) == before
    async with AsyncSession(runtime) as session, session.begin():
        assert (await batch.refresh_exclusive_provider_scalars_batch(session, items, **plan))[
            "status"
        ] == "completed"
