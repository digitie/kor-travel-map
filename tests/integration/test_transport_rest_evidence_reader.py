"""격리 PG의 synthetic 휴게소1→215→MAX+1와 실제 converter/loader/명시 lab cutover.

source-only checkpoint다. 운영 휴게소215의 적격성·upstream EOF·SH collector 수용이 아니다.
단일 testcase의 단계별 추가라 고정 dataset과 module-scope fixture를 다른 test가 공유하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from time import perf_counter, process_time
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Address
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import feature_repo
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.feature_identity import resolve_feature_identity
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)
from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.transport_rest_evidence_reader import read_transport_rest_evidence
from kortravelmap.providers.kor_travel_rest_evidence import (
    prepare_transport_rest_area_reobservation,
)
from kortravelmap.providers.kor_travel_transport import TransportRestArea
from kortravelmap.providers.kor_travel_transport_native import (
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)
from kortravelmap.providers.krex import rest_area_natural_key
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_scoped_native_scalar_refresh import _TIME
from tests.integration.test_scoped_provider_batch import _entity

pytestmark = pytest.mark.integration
_VERSION, _DATA = "dv1-" + "a" * 32, "dd1-" + "b" * 32
_ADDRESS = Address(legal="서울특별시 영등포구 여의도동 8", bjd_code="1156011000")

_PINS = SnapshotArtifactPins(
    code_revision="a" * 40,
    sdk_inventory_sha256="b" * 64,
    provider="kor-travel-transport",
    dataset_key="transport_rest_areas",
    source_entity_type="rest_area",
    normalizer_revision="transport-rest-area-name-phones-v1",
    geo_domain="transport-rest-area-geo-v1",
    clock_domain="aware-clock-preserved-v1",
)


def _context():
    return GeoLoadContext(
        GeoApplied(reverse=True, geocode=False),
        DatasetRef(version_token=_VERSION, data_token=_DATA),
        frozenset({_DATA}),
    )


async def _bundle(index, *, observed=0):
    item = TransportRestArea(
        "pending",
        f"소유 휴게소 {index}",
        "경부선",
        "상행",
        127.0,
        37.5,
        "031-123-4567",
        None,
        None,
        None,
        {},
    )
    item = replace(item, natural_key=rest_area_natural_key(item))
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
            VALUES(:provider,:key,'owned rest fixture','manual')
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
                        ),
                        dict(
                            field_path="place.phones",
                            provider_rank=10,
                            omitted_policy="carry_forward",
                            null_policy="value",
                        ),
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
                :feature,1,ARRAY['core.name','place.phones']::text[])"""),
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
        evidence = await read_transport_rest_evidence(session, dataset)
        prepared = await prepare_transport_rest_area_reobservation(
            session, bundles, dataset_id=dataset, pins=_PINS, geo=_context()
        )
        assert prepared.evidence.dataset_id == evidence.dataset_id
        assert prepared.evidence.evidence_complete == evidence.evidence_complete
        assert prepared.evidence.reason == evidence.reason
        assert prepared.evidence.policy_epoch == evidence.policy_epoch
        assert [{**item, "non_scalar_base": _base(item)} for item in prepared.evidence.items] == [
            {**item, "non_scalar_base": _base(item)} for item in evidence.items
        ]
        assert prepared.input_eof
        assert prepared.collector_ready is False
        assert prepared.requires_database_reverification
        return prepared


def _base(item):
    result = {row["field_path"]: row for row in item["non_scalar_base"]}
    assert len(result) == 23
    return result


async def test_actual_rest_whole_rr_grows_to_215_then_scope_max_plus_one(scalar_engines, request):
    """단일 owned dataset을 정본 loader로 늘린다. SQL timeout/오류는 숨기지 않는다."""
    admin, runtime = scalar_engines
    previous = 0
    dataset = None
    observations = []
    for count in (1, 15, 64, 128, 215):
        incoming = [await _bundle(i) for i in range(previous, count)]
        same_dataset, ids = await _seed(admin, runtime, incoming)
        assert len(ids) == count - previous
        if dataset is not None:
            assert same_dataset == dataset
        dataset = same_dataset
        snapshot = [await _bundle(i, observed=3) for i in range(count)]
        started, cpu = perf_counter(), process_time()
        outcome = await _read(runtime, dataset, snapshot)
        observation = {
            "count": count,
            "client_wall_seconds": perf_counter() - started,
            "client_process_cpu_seconds": process_time() - cpu,
            "evidence_complete": outcome.evidence.evidence_complete,
            "reason": outcome.reason,
            "codec_and_two_reader_calls_included": True,
        }
        if outcome.evidence.evidence_complete:
            assert outcome.eligible
            assert outcome.evidence.db_scope_eof
            assert len(outcome.evidence.items) == count
            observation["decoder_json_bytes"] = len(
                json.dumps(
                    [dict(item) for item in outcome.evidence.items], ensure_ascii=False
                ).encode("utf-8")
            )
            for item in outcome.evidence.items:
                assert len(_base(item)) == 23
                assert item["name_candidate"]["field_path"] == "core.name"
                assert item["phones_candidate"]["field_path"] == "place.phones"
                assert item["phones_candidate"]["value_json"] == ["031-123-4567"]
                assert item["geocode_stamp"]["reverse_outcome"] == "called"
        else:
            assert not outcome.eligible
            assert outcome.reason == "budget_exceeded"
            assert outcome.evidence.items == ()
            assert not outcome.evidence.db_scope_eof
        observations.append(observation)
        request.node.user_properties.append(
            (f"rest_whole_rr_{count}", json.dumps(observation, sort_keys=True))
        )
        previous = count
    # caller 입력 길이로 DB EOF를 추정하지 않고 실제257행에서256 상한을 검증한다.
    await _seed(admin, runtime, [await _bundle(i) for i in range(215, 257)])
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='3s'"))
        await session.execute(text("SET LOCAL lock_timeout='1s'"))
        rejected = await read_transport_rest_evidence(session, dataset)
        assert not rejected.evidence_complete
        assert not rejected.db_scope_eof
        assert rejected.reason.value == "budget_exceeded"
        assert rejected.items == ()
    request.node.user_properties.append(("client_metrics_are_not_backend_cpu_or_spi", True))
