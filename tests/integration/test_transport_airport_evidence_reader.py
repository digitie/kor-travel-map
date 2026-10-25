"""격리 PG의 synthetic 공항1→15와 실제 converter/loader/명시 lab cutover.

source-only checkpoint다. 운영 공항15의 적격성·upstream EOF·SH collector 수용이 아니다.
단일 testcase의 단계별 추가라 고정 dataset과 module-scope fixture를 다른 test가 공유하지 않는다.
"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Address
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import feature_repo
from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.feature_identity import resolve_feature_identity
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)
from kortravelmap.infra.transport_airport_evidence_reader import read_transport_airport_evidence
from kortravelmap.providers.kor_travel_transport import TransportAirport, TransportCoordinate
from kortravelmap.providers.kor_travel_transport_evidence import (
    prepare_transport_airport_reobservation,
)
from kortravelmap.providers.kor_travel_transport_native import (
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_scoped_native_scalar_refresh import _TIME
from tests.integration.test_scoped_provider_batch import _entity, _plan

pytestmark = pytest.mark.integration
_VERSION, _DATA = "dv1-" + "a" * 32, "dd1-" + "b" * 32
_ADDRESS = Address(legal="서울특별시 영등포구 여의도동 8", bjd_code="1156011000")


def _context():
    return GeoLoadContext(
        GeoApplied(reverse=True, geocode=False),
        DatasetRef(version_token=_VERSION, data_token=_DATA),
        frozenset({_DATA}),
    )


async def _bundle(index, *, changed=False, observed=0):
    item = TransportAirport(
        f"Q{index:02d}",
        f"소유 공항 {index}" + (" 변경" if changed else ""),
        f"OWNED AIRPORT {index}",
        f"X{index:03d}",
        "서울특별시",
        TransportCoordinate(lat=37.5, lon=127.0),
        {},
    )
    return await transport_item_to_native_bundle(
        item,
        fetched_at=_TIME + timedelta(hours=observed),
        geo=TransportGeoEvidence("resolved", _VERSION, _DATA, _ADDRESS, "0" * 64),
    )


async def _seed(admin, runtime, bundles):
    """기존 batch fixture 순서에 실제 loader Geo 인자만 명시한다. 권한 우회는 없다."""
    record = bundles[0].source_record
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("""INSERT INTO provider_sync.provider_datasets(
            provider,dataset_key,display_name,source_kind)
            VALUES(:provider,:key,'owned airport fixture','manual')
            ON CONFLICT(provider,dataset_key) DO NOTHING"""),
            {"provider": record.provider, "key": record.dataset_key},
        )
    async with AsyncSession(runtime) as session, session.begin():
        loaded = await feature_repo.load_bundles(session, bundles, geo=_context())
        assert loaded.geo_stamps_written == len(bundles)
        ids = []
        for bundle in bundles:
            identity = await resolve_feature_identity(session, bundle.feature.feature_id)
            assert identity is not None
            ids.append(UUID(str(identity.feature_id)))
        dataset = await session.scalar(
            text("""SELECT provider_dataset_id
            FROM provider_sync.provider_datasets WHERE provider=:provider AND dataset_key=:key"""),
            {"provider": record.provider, "key": record.dataset_key},
        )
    presence = bundles[0].provider_field_presence
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(
            text("""CALL feature.register_provider_field_shadow_policy(
            1,:dataset,:normalizer,CAST(:fields AS jsonb))"""),
            {
                "dataset": dataset,
                "normalizer": presence.normalizer_revision,
                "fields": json.dumps(
                    [
                        dict(
                            field_path="core.name",
                            provider_rank=10,
                            omitted_policy="carry_forward",
                            null_policy="value",
                        )
                    ]
                ),
            },
        )
        arm_provider_field_shadow(session, 1)
        for feature, bundle in zip(ids, bundles, strict=True):
            await capture_provider_field_candidates(
                session,
                feature_id=str(feature),
                dataset_id=dataset,
                entity_key=_entity(bundle),
                record_key=bundle.source_record.source_record_key,
                values=native._provider_scalar_values(bundle, feature_id=feature),
                geometry_wkt="{}",
                presence=bundle.provider_field_presence,
            )
    async with AsyncSession(admin) as session, session.begin():
        for feature in ids:
            await session.execute(
                text("""CALL feature.activate_provider_field_policy(
                :feature,1,ARRAY['core.name']::text[])"""),
                {"feature": feature},
            )
    return dataset, ids


async def _read(runtime, dataset, bundles):
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='3s'"))
        await session.execute(text("SET LOCAL lock_timeout='1s'"))
        role = (await session.execute(text("SELECT session_user,current_user"))).one()
        assert role == ("ktm_feature_service", "ktm_feature_service")
        evidence = await read_transport_airport_evidence(session, dataset)
        prepared = await prepare_transport_airport_reobservation(
            session, bundles, dataset_id=dataset, geo=_context()
        )
        assert prepared.evidence.dataset_id == evidence.dataset_id
        assert prepared.evidence.evidence_complete == evidence.evidence_complete
        assert prepared.evidence.reason == evidence.reason
        assert prepared.evidence.policy_epoch == evidence.policy_epoch
        assert [{**item, "non_name_base": _base(item)} for item in prepared.evidence.items] == [
            {**item, "non_name_base": _base(item)} for item in evidence.items
        ]
        assert prepared.input_eof
        assert prepared.collector_ready is False
        assert prepared.requires_database_reverification
        return prepared


def _base(item):
    result = {row["field_path"]: row for row in item["non_name_base"]}
    assert len(result) == 24
    return result


async def test_actual_airport_one_then_fifteen_r1_r2_geo_and_native(scalar_engines, request):
    admin, runtime = scalar_engines
    first = await _bundle(0)
    dataset, ids = await _seed(admin, runtime, [first])
    before = await _read(runtime, dataset, [await _bundle(0, observed=1)])
    assert before.eligible
    assert before.evidence.db_scope_eof
    assert len(before.evidence.items) == 1
    initial = before.evidence.items[0]
    assert initial["geocode_stamp"]["reverse_outcome"] == "called"
    assert initial["current_record"]["raw_payload_hash"] == first.source_record.raw_payload_hash
    # 실제 EX sealed scalar 경계로 이름만 R2를 만든다. changed raw SH 허가가 아니다.
    changed = await _bundle(0, changed=True, observed=2)
    entries = [batch.ProviderScalarRefreshItem(ids[0], changed)]
    plan, _ = await _plan(runtime, dataset, entries, exclusive=True)
    async with AsyncSession(runtime) as session, session.begin():
        result = await batch.refresh_scoped_provider_scalars_batch(session, entries, **plan)
        assert result["status"] == "completed"
    current = await _bundle(0, changed=True, observed=3)
    after = await _read(runtime, dataset, [current])
    assert after.eligible
    row = after.evidence.items[0]
    assert _base(row) == _base(initial)
    assert row["base_record"] == initial["base_record"]
    assert row["geocode_stamp"] == initial["geocode_stamp"]
    assert (
        row["name_candidate"]["value_source_record_key"] == changed.source_record.source_record_key
    )
    assert row["name_base"]["source_record_key"] == changed.source_record.source_record_key
    assert row["current_record"]["source_record_key"] == changed.source_record.source_record_key
    # 같은 DS에14개를 정본으로 추가한다. 원래1개와 정책/identity를 삭제하거나 재작성하지 않는다.
    others = [await _bundle(index) for index in range(1, 15)]
    same_dataset, _ = await _seed(admin, runtime, others)
    assert same_dataset == dataset
    final_input = [current] + [await _bundle(index, observed=3) for index in range(1, 15)]
    final = await _read(runtime, dataset, final_input)
    if final.evidence.evidence_complete:
        assert final.eligible
        assert final.evidence.db_scope_eof
        assert len(final.evidence.items) == 15
        outcome = "complete15"
    else:
        assert not final.eligible
        assert final.reason == "budget_exceeded"
        assert final.evidence.items == ()
        assert not final.evidence.db_scope_eof
        outcome = "whole_budget_rejection15"
    # 알려진 budget 거부도 그대로 기록하며 15행 적격을 전제하지 않는다.
    request.node.user_properties.append(("airport15_outcome", outcome))
