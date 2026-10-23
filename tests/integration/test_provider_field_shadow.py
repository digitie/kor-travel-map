"""ADR115 shadow만 쓰며 R1 값 원문과 R2 검증 head를 분리한다."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)
from tests.integration.test_tvn36_override_lineage_spine import _seed_feature_source

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _seed(session: AsyncSession) -> tuple[str, int]:
    feature_id, dataset_id = await _seed_feature_source(session)
    await session.execute(
        text("""
        INSERT INTO feature.provider_field_shadow_policies(
            policy_revision,provider_dataset_id,field_path,normalizer_revision,
            provider_rank,omitted_policy,null_policy
        ) VALUES (1,:dataset,'core.name','fixture-v1',10,'carry_forward','value'),
                 (1,:dataset,'place.biz_number','fixture-v1',10,'carry_forward','remove')
    """),
        {"dataset": dataset_id},
    )
    return feature_id, dataset_id


async def _capture(
    session: AsyncSession,
    feature_id: str,
    dataset_id: int,
    record: str,
    values: dict[str, object],
    *,
    proven: bool = True,
):
    return await capture_provider_field_candidates(
        session,
        feature_id=feature_id,
        dataset_id=dataset_id,
        entity_key="tvn36-lineage-entity",
        record_key=record,
        values=json.dumps(values),
        geometry_wkt="{}",
        presence=ProviderFieldPresence(
            normalizer_revision="fixture-v1", supplied_fields=frozenset(values)
        )
        if proven
        else None,
    )


async def _next_head(session: AsyncSession) -> None:
    await session.execute(
        text("""
        INSERT INTO provider_sync.source_records(
            source_record_key,source_entity_key,raw_data,raw_payload_hash,fetched_at
        ) VALUES ('shadow-r2','tvn36-lineage-entity','{"name":"second"}',:hash,now());
    """),
        {"hash": "c" * 64},
    )
    await session.execute(
        text("""
        UPDATE provider_sync.source_entity_heads SET current_source_record_key='shadow-r2',
            observed_at=observed_at + interval '1 second'
        WHERE source_entity_key='tvn36-lineage-entity'
    """)
    )


async def test_explicit_omission_carries_original_value_to_new_validated_head(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    first = await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"core.name": "first", "place.biz_number": "123"},
    )
    assert first.field_count == 2
    assert first.unresolved_count == 0
    await _next_head(session)
    second = await _capture(session, feature_id, dataset_id, "shadow-r2", {"core.name": "second"})
    assert second.unresolved_count == 0
    rows = (
        (
            await session.execute(
                text("""
        SELECT field_path,value_json,value_source_record_key,validated_source_record_key,
               availability,reason FROM feature.provider_field_shadow_candidates
        WHERE feature_id=CAST(:feature AS uuid) ORDER BY field_path
    """),
                {"feature": feature_id},
            )
        )
        .mappings()
        .all()
    )
    assert rows[0]["value_source_record_key"] == "shadow-r2"
    assert rows[1]["value_json"] == "123"
    assert rows[1]["value_source_record_key"] == "tvn36-lineage-record"
    assert rows[1]["validated_source_record_key"] == "shadow-r2"
    assert rows[1]["reason"] == "omitted_carry"
    # shadow는 기존 effective name을 고치지 않는다.
    assert (
        await session.scalar(
            text("SELECT name FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
            {"id": feature_id},
        )
        == "tvn36-lineage-place"
    )


async def test_explicit_null_removes_candidate_but_not_native_effective(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"core.name": "first", "place.biz_number": "123"},
    )
    await _next_head(session)
    await _capture(
        session,
        feature_id,
        dataset_id,
        "shadow-r2",
        {"core.name": "second", "place.biz_number": None},
    )
    row = (
        (
            await session.execute(
                text("""
        SELECT value_json,availability,reason,value_source_record_key
        FROM feature.provider_field_shadow_candidates WHERE field_path='place.biz_number'
    """)
            )
        )
        .mappings()
        .one()
    )
    assert dict(row) == {
        "value_json": None,
        "availability": "removed",
        "reason": "explicit_null",
        "value_source_record_key": "shadow-r2",
    }


async def test_missing_presence_is_unresolved_not_explicit_dto_null(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    feature_id, dataset_id = await _seed(session)
    arm_provider_field_shadow(session, 1)
    result = await _capture(
        session,
        feature_id,
        dataset_id,
        "tvn36-lineage-record",
        {"core.name": "first", "place.biz_number": None},
        proven=False,
    )
    assert result.field_count == result.unresolved_count == 2
    assert (
        await session.execute(
            text("SELECT DISTINCT reason FROM feature.provider_field_shadow_candidates")
        )
    ).scalars().all() == ["presence_unknown"]
