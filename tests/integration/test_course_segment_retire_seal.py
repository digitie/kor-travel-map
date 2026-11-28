"""등산 코스 적재가 구간 route를 은퇴시킨 run도 child 완료 seal까지 통과한다(ADR-128 개정).

#1569는 코스 적재(seal 기대값을 그 transaction에서 잡음)와 구간 은퇴를 두 transaction으로 돌려,
은퇴가 1건이라도 있으면 완료 seal이 ``provider load input changed before child completion``
(``ck_tvn40_provider_snapshot_load_input``)으로 실패했다
(prod krforest 57,033건·knps 609건 은퇴 run). 여기서는 실제 asset → client → 실제 tracked
finish(별도 SERIALIZABLE seal)를 탄다. worker 실행은 아니다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from kortravelmap.dagster.assets import run_feature_route_krforest_mountain_trails
from kortravelmap.dagster.feature_operation_tracking import (
    _guard_from_context_async,
    run_tracked_feature_asset,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import kortravelmap.client as client_module
from kortravelmap.providers.feature_operation_registry import resolve_feature_operation_handler
from kortravelmap.providers.krforest import (
    MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE,
    MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE,
    mountain_trails_to_bundles,
)
from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_canonical_provider_operations import (
    _resource_init_context,
    _tracking_context,
)
from tests.integration.test_heritage_collector_tracking import _Geo, _tree
from tests.integration.test_heritage_collector_tracking import (
    collector_client as collector_client,
)
from tests.integration.test_hiking_course_load import _Trail, _trail

pytestmark = pytest.mark.integration
_AT = datetime(2026, 11, 28, 9, tzinfo=ZoneInfo("Asia/Seoul"))
_OPERATION = "feature_route_krforest_mountain_trails_job"


async def _readonly(engine, sql, params=None):
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return (await session.execute(text(sql), params or {})).mappings().all()


def _segments(mountain_code: str) -> list[_Trail]:
    """한 산의 구간 3개 → 코스 2개(서쪽구간 2구간 + 동쪽구간 1구간)."""
    trails = [
        _trail(1, [(127.000, 37.5), (127.010, 37.5)], segment_name="서쪽구간"),
        _trail(2, [(127.020, 37.5), (127.010, 37.5)], segment_name="서쪽구간"),
        _trail(3, [(127.100, 37.5), (127.140, 37.5)], segment_name="동쪽구간", length_km=3.53),
    ]
    return [
        _Trail(
            name=trail.name,
            source_id=f"{trail.source_id}:{mountain_code}",
            source_file=trail.source_file,
            layer_name=trail.layer_name,
            geometry_type=trail.geometry_type,
            geometry=trail.geometry,
            bbox=trail.bbox,
            raw={**trail.raw, "MNTN_CODE": mountain_code},
        )
        for trail in trails
    ]


async def _active_by_entity_type(engine, provider_dataset_id: int) -> dict[str, int]:
    rows = await _readonly(
        engine,
        """
        SELECT entity.source_entity_type, count(*) FILTER (
                 WHERE feature.lifecycle_state = 'active') AS active
        FROM provider_sync.source_entities entity
        JOIN provider_sync.source_links link ON link.source_entity_key = entity.source_entity_key
        JOIN feature.features feature ON feature.feature_id = link.feature_id
        WHERE entity.provider_dataset_id = :dataset AND link.source_role = 'primary'
        GROUP BY entity.source_entity_type
        """,
        {"dataset": provider_dataset_id},
    )
    return {row["source_entity_type"]: int(row["active"]) for row in rows}


async def test_course_run_that_retires_segments_seals_the_final_state(
    collector_client, monkeypatch
):
    """구간 3건 은퇴 run이 tracked finish·seal까지 성공하고 seal 값은 은퇴 뒤 상태다."""
    admin, runtime, client = collector_client
    run_id = str(uuid4())
    mountain_code = str(900_000_000 + int(uuid4().hex[:6], 16) % 99_999_999)
    records = _segments(mountain_code)
    geo = _Geo()

    # 1) #1569 이전 상태: 구간이 구간 그대로 route Feature로 실려 있다.
    await client.load_feature_bundles(
        await mountain_trails_to_bundles(records, fetched_at=_AT, reverse_geocoder=geo)
    )

    init = _resource_init_context(
        client,
        run_id=run_id,
        tags={"kor_travel_map.operation_key": _OPERATION, "kor_travel_map.trigger_kind": "manual"},
    )
    init.run.job_name = resolve_feature_operation_handler(_OPERATION).job_name
    guard = await _guard_from_context_async(init)
    assert len(guard.memberships) == 1
    await guard.ensure()
    member = guard.memberships[0]
    assert await _active_by_entity_type(admin, member.provider_dataset_id) == {
        MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE: 3
    }
    child_id = (await _tree(admin, run_id))[1]["job_id"]

    snapshot_transactions: list[int] = []
    capture = client_module.capture_provider_curation_input
    retire = client_module.retire_features_by_source_entity_ids

    async def capture_probe(session, **kwargs):
        snapshot_transactions.append(
            int(await session.scalar(text("SELECT txid_current()")))
        )
        return await capture(session, **kwargs)

    retire_transactions: list[int] = []

    async def retire_probe(session, **kwargs):
        retire_transactions.append(int(await session.scalar(text("SELECT txid_current()"))))
        return await retire(session, **kwargs)

    monkeypatch.setattr(client_module, "capture_provider_curation_input", capture_probe)
    monkeypatch.setattr(client_module, "retire_features_by_source_entity_ids", retire_probe)

    context = _tracking_context(guard, retry_number=0)
    context.log = logging.getLogger(__name__)
    context.add_output_metadata = lambda _value: None
    context.resources.reverse_geocoder = geo
    context.resources.kor_travel_geo_dataset = geo
    context.resources.fetched_at = _AT
    context.resources.strict_address = "strict"
    context.resources.krforest_mountain_trails = records

    result = await run_tracked_feature_asset(context, run_feature_route_krforest_mountain_trails)

    # 코스 적재·구간 은퇴·seal 캡처가 한 transaction이다 — seal은 한 번만, 은퇴와 같은 txid.
    assert len(snapshot_transactions) == 1
    assert retire_transactions == snapshot_transactions
    assert result.load.bundles_total == 2
    assert result.load.superseded_retired == 3
    assert await _active_by_entity_type(admin, member.provider_dataset_id) == {
        MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE: 2,
        MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE: 0,
    }

    # child가 done이고 receipt는 run이 넘긴 seal 값(은퇴 뒤 상태)과 같다.
    tree = await _tree(admin, run_id)
    assert tree[1]["status"] == "done"
    receipt = await _readonly(
        admin,
        "SELECT input_member_count, source_input_set_hash "
        "FROM ops.curation_provider_snapshot_receipts WHERE source_job_id=CAST(:child AS uuid)",
        {"child": child_id},
    )
    assert len(receipt) == 1
    assert receipt[0]["input_member_count"] == result.load.curation_input_member_count
    assert receipt[0]["source_input_set_hash"] == result.load.curation_input_set_hash

    sync_rows = await _readonly(
        admin,
        """
        SELECT cursor FROM provider_sync.provider_sync_state
        WHERE provider_dataset_id=:dataset AND sync_scope=:scope AND operation_key=:operation
        """,
        {
            "dataset": member.provider_dataset_id,
            "scope": member.sync_scope,
            "operation": _OPERATION,
        },
    )
    assert len(sync_rows) == 1
    assert sync_rows[0]["cursor"]["segment_routes_retired"] == 3
    assert sync_rows[0]["cursor"]["course_segments_covered"] == 3
    assert runtime.pool.checkedout() == 0
