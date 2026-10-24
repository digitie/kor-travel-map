"""실제 native scalar source DML 중첩·rollback·artifact replay를 전용 PG에서 검사한다."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Feature,
    FeatureBundle,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra import scoped_provider_refresh as native
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
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_engines as scalar_engines,
)

pytestmark = pytest.mark.integration
_TIME = datetime(2026, 10, 24, 12, tzinfo=ZoneInfo("Asia/Seoul"))


def _bundle(identity, name, *, hours=0):
    provider = "native-scalar-fixture"
    raw = {"name": name, "phones": ["010-0000-0000"]}
    payload_hash = make_payload_hash(raw)
    record_key = make_source_record_key(
        provider=provider,
        dataset_key=identity,
        source_entity_type="place",
        source_entity_id=identity,
        raw_payload_hash=payload_hash,
    )
    legacy = make_feature_id(
        bjd_code=None,
        kind="place",
        category="01010100",
        source_type=provider,
        source_natural_key=identity,
    )
    return FeatureBundle(
        feature=Feature(
            feature_id=legacy,
            provider_natural_key=identity,
            kind="place",
            name=name,
            category="01010100",
            marker_icon="marker",
            marker_color="P-01",
            detail=PlaceDetail(feature_id=legacy, place_kind="tourism", phones=raw["phones"]),
        ),
        source_record=SourceRecord(
            provider=provider,
            dataset_key=identity,
            source_entity_type="place",
            source_entity_id=identity,
            raw_data=raw,
            raw_payload_hash=payload_hash,
            source_record_key=record_key,
            fetched_at=_TIME + timedelta(hours=hours),
            imported_at=_TIME + timedelta(hours=hours),
        ),
        source_link=SourceLink(
            feature_id=legacy,
            source_record_key=record_key,
            source_role=SourceRole.PRIMARY,
            match_method="fixture",
            confidence=100,
        ),
        provider_field_presence=ProviderFieldPresence(
            normalizer_revision="native-v1",
            supplied_fields={"core.name", "place.phones"},
        ),
    )


async def _seed(admin):
    identity = uuid4().hex
    old = _bundle(identity, "before", hours=-24)
    record = old.source_record
    entity = _make_source_entity_key(
        provider=record.provider,
        dataset_key=identity,
        source_entity_type="place",
        source_entity_id=identity,
    )
    feature = uuid4()
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(text("SET LOCAL statement_timeout='10s'"))
        dataset = await session.scalar(
            text("""INSERT INTO provider_sync.provider_datasets(
            provider,dataset_key,display_name,source_kind)
            VALUES(:provider,:key,'native scalar fixture','manual')
            RETURNING provider_dataset_id"""),
            {"provider": record.provider, "key": identity},
        )
        params = {
            "feature": feature,
            "entity": entity,
            "dataset": dataset,
            "identity": identity,
            "record": record.source_record_key,
            "hash": record.raw_payload_hash,
            "raw": json.dumps(record.raw_data),
            "at": record.imported_at,
        }
        for sql in [
            """INSERT INTO feature.features(feature_id,kind,name,category)
                VALUES(:feature,'place','before','01010100')""",
            """INSERT INTO feature.feature_places(feature_id,kind,place_kind)
                VALUES(:feature,'place','tourism')""",
            """INSERT INTO provider_sync.source_entities(source_entity_key,provider_dataset_id,
                source_entity_type,source_entity_id,first_seen_at,last_seen_at)
                VALUES(:entity,:dataset,'place',:identity,:at,:at)""",
            """INSERT INTO provider_sync.source_records(source_record_key,source_entity_key,
                raw_data,raw_payload_hash,fetched_at)
                VALUES(:record,:entity,CAST(:raw AS jsonb),:hash,:at)""",
            """INSERT INTO provider_sync.source_entity_heads(source_entity_key,
                current_source_record_key,observed_at) VALUES(:entity,:record,:at)""",
            """INSERT INTO provider_sync.source_links(feature_id,source_entity_key,source_role,
                match_method,confidence) VALUES(:feature,:entity,'primary','fixture',100)""",
        ]:
            await session.execute(text(sql), params)
        await session.execute(
            text("""CALL feature.register_provider_field_shadow_policy(
            1,:dataset,'native-v1',CAST(:fields AS jsonb))"""),
            {
                "dataset": dataset,
                "fields": json.dumps(
                    [
                        {
                            "field_path": field,
                            "provider_rank": 10,
                            "omitted_policy": "carry_forward",
                            "null_policy": "value",
                        }
                        for field in ["core.name", "place.phones"]
                    ]
                ),
            },
        )
        arm_provider_field_shadow(session, 1)
        await capture_provider_field_candidates(
            session,
            feature_id=str(feature),
            dataset_id=dataset,
            entity_key=entity,
            record_key=record.source_record_key,
            values=json.dumps({"core.name": "before", "place.phones": ["010-0000-0000"]}),
            geometry_wkt="{}",
            presence=old.provider_field_presence,
        )
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout='10s'"))
        await session.execute(text("SET LOCAL lock_timeout='2s'"))
        await session.execute(
            text("""CALL feature.activate_provider_field_policy(
            :feature,1,ARRAY['core.name','place.phones'])"""),
            {"feature": feature},
        )
    return feature, dataset, entity, identity


async def _plan(runtime, feature, dataset, bundle, *, exclusive_protocol=False):
    attempt, owner = uuid4(), uuid4()
    async with AsyncSession(runtime) as session, session.begin():
        revision = await session.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=:feature"),
            {"feature": feature},
        )
        heads = (
            await session.execute(
                text("""SELECT source_entity_key,current_source_record_key
            FROM provider_sync.source_links JOIN provider_sync.source_entity_heads
            USING(source_entity_key) WHERE feature_id=:feature ORDER BY source_entity_key"""),
                {"feature": feature},
            )
        ).all()
        membership = await session.scalar(
            text("SELECT ops.scoped_feature_write_membership_digest(:feature)"),
            {"feature": feature},
        )
        members = [
            ScopedWriteDependency(i, "source_head", entity, record)
            for i, (entity, record) in enumerate(heads)
        ]
        members += [
            ScopedWriteDependency(len(members), "feature", str(feature), str(revision)),
            ScopedWriteDependency(len(members) + 1, "feature_membership", str(feature), membership),
        ]
        await claim_scoped_feature_write(
            session,
            attempt_id=attempt,
            owner=owner,
            dataset_id=dataset,
            idempotency_key=uuid4().hex,
            regions=(),
            expected_members=len(members),
            exclusive_protocol=exclusive_protocol,
            input_digest=native.scoped_provider_refresh_input_digest(
                bundle, feature_id=feature, dataset_id=dataset, policy_revision=1
            ),
        )
        await append_scoped_feature_write_manifest(
            session, attempt_id=attempt, owner=owner, members=members
        )
        digest = await seal_scoped_feature_write_manifest(session, attempt_id=attempt, owner=owner)
    return dict(
        feature_id=feature,
        dataset_id=dataset,
        policy_revision=1,
        attempt_id=attempt,
        owner=owner,
        manifest_digest=digest,
    )


async def _read(admin, feature, entity):
    async with AsyncSession(admin) as session:
        return tuple(
            (
                await session.execute(
                    text("""SELECT feature.name,head.current_source_record_key
            FROM feature.features feature CROSS JOIN provider_sync.source_entity_heads head
            WHERE feature.feature_id=:feature AND head.source_entity_key=:entity"""),
                    {"feature": feature, "entity": entity},
                )
            ).one()
        )


async def test_native_independent_source_dml_actually_overlaps(scalar_engines, monkeypatch):
    admin, runtime = scalar_engines
    cases = [await _seed(admin), await _seed(admin)]
    bundles = [_bundle(case[3], f"after-{index}") for index, case in enumerate(cases)]
    plans = [
        await _plan(runtime, case[0], case[1], bundle)
        for case, bundle in zip(cases, bundles, strict=True)
    ]
    original = native._upsert_source_record_state
    reached = set()
    both = asyncio.Event()

    async def hold_after_actual_dml(session, record):
        result = await original(session, record)
        reached.add(await session.scalar(text("SELECT pg_backend_pid()")))
        if len(reached) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=3)
        return result

    monkeypatch.setattr(native, "_upsert_source_record_state", hold_after_actual_dml)

    async def apply(bundle, plan):
        async with AsyncSession(runtime) as session, session.begin():
            receipt = await native.refresh_scoped_provider_scalars(session, bundle, **plan)
            assert receipt["status"] == "completed"

    await asyncio.wait_for(
        asyncio.gather(*(apply(bundle, plan) for bundle, plan in zip(bundles, plans, strict=True))),
        timeout=10,
    )
    assert len(reached) == 2
    for case, bundle in zip(cases, bundles, strict=True):
        assert await _read(admin, case[0], case[2]) == (
            bundle.feature.name,
            bundle.source_record.source_record_key,
        )


@pytest.mark.parametrize(
    "failure", [RuntimeError, asyncio.CancelledError], ids=["injected-exception", "injected-cancel"]
)
async def test_native_failure_rolls_back_and_same_artifact_recovers(
    scalar_engines, monkeypatch, failure
):
    admin, runtime = scalar_engines
    feature, dataset, entity, identity = await _seed(admin)
    before = await _read(admin, feature, entity)
    bundle = _bundle(identity, "recovered")
    plan = await _plan(runtime, feature, dataset, bundle)
    original = native._upsert_source_record_state

    async def crash_after_source_dml(session, record):
        await original(session, record)
        raise failure("injected worker loss")

    with monkeypatch.context() as patch:
        patch.setattr(native, "_upsert_source_record_state", crash_after_source_dml)
        with pytest.raises(failure, match="injected worker loss"):
            async with AsyncSession(runtime) as session, session.begin():
                await native.refresh_scoped_provider_scalars(session, bundle, **plan)
    assert await _read(admin, feature, entity) == before
    async with AsyncSession(runtime) as session, session.begin():
        first = await native.refresh_scoped_provider_scalars(session, bundle, **plan)
    assert await _read(admin, feature, entity) == (
        "recovered",
        bundle.source_record.source_record_key,
    )

    async def no_dml(*args, **kwargs):
        pytest.fail("completed receipt replay performed source DML")

    monkeypatch.setattr(native, "_upsert_source_record_state", no_dml)
    async with AsyncSession(runtime) as session, session.begin():
        replay = await native.refresh_scoped_provider_scalars(session, bundle, **plan)
    assert replay["result_digest"] == first["result_digest"]


async def test_native_older_artifact_does_not_replace_current_winner(scalar_engines):
    admin, runtime = scalar_engines
    feature, dataset, entity, identity = await _seed(admin)
    bundle = _bundle(identity, "newest")
    plan = await _plan(runtime, feature, dataset, bundle)
    async with AsyncSession(runtime) as session, session.begin():
        await native.refresh_scoped_provider_scalars(session, bundle, **plan)
    older = _bundle(identity, "older", hours=-48)
    old_plan = await _plan(runtime, feature, dataset, older)
    async with AsyncSession(runtime) as session, session.begin():
        await native.refresh_scoped_provider_scalars(session, older, **old_plan)
    assert await _read(admin, feature, entity) == ("newest", bundle.source_record.source_record_key)


async def test_native_wrong_artifact_cannot_change_head_or_winner(scalar_engines):
    admin, runtime = scalar_engines
    feature, dataset, entity, identity = await _seed(admin)
    before = await _read(admin, feature, entity)
    intended = _bundle(identity, "intended")
    substituted = _bundle(identity, "substituted")
    plan = await _plan(runtime, feature, dataset, intended)
    with pytest.raises(ValueError, match="does not match this input"):
        async with AsyncSession(runtime) as session, session.begin():
            await native.refresh_scoped_provider_scalars(session, substituted, **plan)
    assert await _read(admin, feature, entity) == before
    async with AsyncSession(runtime) as session, session.begin():
        await native.refresh_scoped_provider_scalars(session, intended, **plan)
    assert await _read(admin, feature, entity) == (
        "intended",
        intended.source_record.source_record_key,
    )
