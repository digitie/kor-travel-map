"""Feature의 다중 current observation과 payload cursor history 통합 검증."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra.feature_repo import _make_source_entity_key, load_bundle
from kortravelmap.infra.observation_repo import (
    get_current_observations,
    get_current_observations_by_feature_ids,
    get_observation_history,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_FEATURE_ID = "feature:multi-observation-test"


async def _seed_active_provider_dataset(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> None:
    """관측 fixture가 쓰는 동적 provider/dataset 정본을 준비한다."""
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind, is_active
            ) VALUES (
                :provider, :dataset_key, 'observation integration fixture', 'manual', true
            )
            ON CONFLICT (provider, dataset_key) DO UPDATE
            SET is_active = true
            """
        ),
        {"provider": provider, "dataset_key": dataset_key},
    )


def _bundle(
    *,
    provider: str,
    entity_id: str,
    edition: str,
    fetched_at: datetime,
) -> FeatureBundle:
    raw_data = {"entity_id": entity_id, "edition": edition}
    payload_hash = make_payload_hash(raw_data)
    record_key = make_source_record_key(
        provider=provider,
        dataset_key="observation-test",
        source_entity_type="place",
        source_entity_id=entity_id,
        raw_payload_hash=payload_hash,
    )
    feature = Feature(
        feature_id=_FEATURE_ID,
        kind=FeatureKind.PLACE,
        name="다중 관측 테스트 장소",
        category="01070100",
        address=Address(),
        marker_icon="place",
        marker_color="P-01",
        # T-VN-35(ADR-086): place subtype ``place_kind``는 NOT NULL이다.
        detail=PlaceDetail(feature_id=_FEATURE_ID, place_kind="attraction"),
        created_at=fetched_at,
        updated_at=fetched_at,
    )
    record = SourceRecord(
        source_record_key=record_key,
        provider=provider,
        dataset_key="observation-test",
        source_entity_type="place",
        source_entity_id=entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        imported_at=fetched_at,
    )
    link = SourceLink(
        feature_id=_FEATURE_ID,
        source_record_key=record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        created_at=fetched_at,
    )
    return FeatureBundle(feature=feature, source_record=record, source_link=link)


async def test_current_observations_keep_multiple_primary_entities_and_history(
    migrated_session: AsyncSession,
) -> None:
    first_at = datetime(2026, 7, 13, 1, 0, tzinfo=UTC)
    second_at = first_at + timedelta(hours=1)
    provider_a = "python-mcst-api"
    provider_b = "python-mois-api"

    old = _bundle(
        provider=provider_a,
        entity_id="mcst-1",
        edition="2023",
        fetched_at=first_at,
    )
    current = _bundle(
        provider=provider_a,
        entity_id="mcst-1",
        edition="2025",
        fetched_at=second_at,
    )
    other = _bundle(
        provider=provider_b,
        entity_id="mois-1",
        edition="current",
        fetched_at=second_at,
    )

    await _seed_active_provider_dataset(
        migrated_session, provider=provider_a, dataset_key="observation-test"
    )
    await _seed_active_provider_dataset(
        migrated_session, provider=provider_b, dataset_key="observation-test"
    )
    await load_bundle(migrated_session, old)
    second_result = await load_bundle(migrated_session, current)
    await load_bundle(migrated_session, other)
    reappeared_result = await load_bundle(migrated_session, old)
    await migrated_session.flush()

    assert second_result.source_records_inserted == 1
    assert second_result.source_links_inserted == 0
    assert second_result.source_links_updated == 1
    assert reappeared_result.source_records_inserted == 0
    assert reappeared_result.features_updated == 0

    observations = await get_current_observations(migrated_session, _FEATURE_ID)
    assert len(observations) == 2
    assert all(item.source_role == SourceRole.PRIMARY for item in observations)
    by_provider = {item.provider: item for item in observations}
    assert by_provider[provider_a].source_record_key == current.source_record.source_record_key
    assert by_provider[provider_a].raw_data["edition"] == "2025"
    assert by_provider[provider_b].raw_data["edition"] == "current"

    batch = await get_current_observations_by_feature_ids(
        migrated_session, [_FEATURE_ID, "feature:missing"]
    )
    assert len(batch[_FEATURE_ID]) == 2
    assert batch["feature:missing"] == ()

    entity_key = _make_source_entity_key(
        provider=provider_a,
        dataset_key="observation-test",
        source_entity_type="place",
        source_entity_id="mcst-1",
    )
    first_page = await get_observation_history(
        migrated_session,
        feature_id=_FEATURE_ID,
        source_entity_key=entity_key,
        limit=1,
    )
    assert [item.raw_data["edition"] for item in first_page.items] == ["2025"]
    assert first_page.items[0].is_current
    assert first_page.next_cursor is not None

    second_page = await get_observation_history(
        migrated_session,
        feature_id=_FEATURE_ID,
        source_entity_key=entity_key,
        cursor=first_page.next_cursor,
        limit=1,
    )
    assert [item.raw_data["edition"] for item in second_page.items] == ["2023"]
    assert not second_page.items[0].is_current
    assert second_page.next_cursor is None
