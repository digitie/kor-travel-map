"""Dagster maintenance job이 호출하는 consistency/dedup client 경로 검증."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map.client import AsyncKrtourMapClient
from krtour.map.infra.dedup_refresh_repo import DedupRefreshScope
from krtour.map.infra.models import FeatureRow, SourceLinkRow, SourceRecordRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
_TEMPLE_CAT = "01070100"
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue, "
    "ops.feature_consistency_reports RESTART IDENTITY CASCADE"
)


@pytest.fixture
async def map_client(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncKrtourMapClient]:
    client = AsyncKrtourMapClient(migrated_engine)
    try:
        yield client
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text(_TRUNCATE_SQL))


async def test_consistency_dedup_refresh_client_updates_queue_and_report(
    migrated_engine: AsyncEngine,
    map_client: AsyncKrtourMapClient,
) -> None:
    await _seed_feature_with_source(
        migrated_engine,
        feature_id="dagster-knps-temple",
        source_record_key="sr-knps-temple",
        provider="knps",
        dataset_key="knps_visitor_centers",
        name="불국사",
    )
    await _seed_feature_with_source(
        migrated_engine,
        feature_id="dagster-heritage-temple",
        source_record_key="sr-heritage-temple",
        provider="krheritage",
        dataset_key="krheritage_heritage_features",
        name="불국사",
    )

    dedup = await map_client.refresh_dedup_candidates_for_scope_pair(
        DedupRefreshScope(
            provider="knps",
            dataset_key="knps_visitor_centers",
            categories=(_TEMPLE_CAT,),
            limit=20,
        ),
        DedupRefreshScope(
            provider="krheritage",
            dataset_key="krheritage_heritage_features",
            categories=(_TEMPLE_CAT,),
            limit=20,
        ),
    )
    report = await map_client.run_consistency_report(
        persist=True,
        sample_limit=5,
        dedup_pending_threshold=0,
    )

    assert len(dedup.candidates) == 1
    assert dedup.queue.inserted == 1
    assert report.severity_max == "WARN"
    assert report.summary["by_code"]["F4"] == 1

    async with AsyncSession(migrated_engine) as session:
        queue_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM ops.dedup_review_queue "
                    "WHERE status = 'pending'"
                )
            )
        ).scalar_one()
        report_count = (
            await session.execute(
                text("SELECT count(*) FROM ops.feature_consistency_reports")
            )
        ).scalar_one()

    assert int(queue_count) == 1
    assert int(report_count) == 1


async def _seed_feature_with_source(
    engine: AsyncEngine,
    *,
    feature_id: str,
    source_record_key: str,
    provider: str,
    dataset_key: str,
    name: str,
) -> None:
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            FeatureRow(
                feature_id=feature_id,
                kind="place",
                name=name,
                category=_TEMPLE_CAT,
                coord=WKTElement("POINT(129.3320 35.7900)", srid=4326),
                detail={"summary": "temple"},
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            SourceRecordRow(
                source_record_key=source_record_key,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type="place",
                source_entity_id=feature_id,
                raw_name=name,
                raw_address="경상북도 경주시 불국로 385",
                raw_payload_hash=f"hash-{source_record_key}",
                raw_data={"feature_id": feature_id},
                fetched_at=_NOW,
                imported_at=_NOW,
            )
        )
        await session.flush()
        session.add(
            SourceLinkRow(
                feature_id=feature_id,
                source_record_key=source_record_key,
                source_role="primary",
                match_method="natural_key",
                confidence=100,
                is_primary_source=True,
                created_at=_NOW,
            )
        )
