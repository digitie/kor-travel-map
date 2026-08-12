"""Dagster maintenance job이 호출하는 consistency/dedup client 경로 검증."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from hashlib import md5
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.dedup_refresh_repo import DedupRefreshScope
from kortravelmap.infra.models import (
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)
from tests.integration._db_cleanup import truncate_committed_test_rows

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration._subtype_seed import seed_feature_subtype

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
_TEMPLE_CAT = "01070100"
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_entities, "
    "provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue, "
    "ops.feature_consistency_reports RESTART IDENTITY CASCADE"
)


@pytest.fixture
async def map_client(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncKorTravelMapClient]:
    client = AsyncKorTravelMapClient(migrated_engine)
    try:
        yield client
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await truncate_committed_test_rows(session, _TRUNCATE_SQL)


async def test_consistency_dedup_refresh_client_updates_queue_and_report(
    migrated_engine: AsyncEngine,
    map_client: AsyncKorTravelMapClient,
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
    assert report.severity_max == "WARN", report.cases_json()
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


async def _dataset_id(session: AsyncSession, *, provider: str, dataset_key: str) -> int:
    """fixture 전용 catalog 행을 만들고 canonical id를 돌려준다 (T-VN-33).

    dedup refresh scope는 여전히 provider/dataset_key 표시 자연키를 받지만,
    source entity의 identity는 ``provider_dataset_id`` 하나다.
    """

    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :dataset_key, :provider, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = EXCLUDED.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": provider, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )


async def _seed_feature_with_source(
    engine: AsyncEngine,
    *,
    feature_id: str,
    source_record_key: str,
    provider: str,
    dataset_key: str,
    name: str,
) -> None:
    source_entity_key = f"se-{source_record_key}"
    async with AsyncSession(engine) as session, session.begin():
        dataset_id = await _dataset_id(session, provider=provider, dataset_key=dataset_key)
        session.add(
            FeatureRow(
                feature_id=feature_id,
                kind="place",
                name=name,
                category=_TEMPLE_CAT,
                coord=WKTElement("POINT(129.3320 35.7900)", srid=4326),
                # T-VN-34C: 이 seed가 원했던 건 "dedup/consistency가 실제로 훑는
                # 공개 표면 위의 feature"였고, 그 자리를 legacy `status='active'`가
                # 대신하고 있었다. 0097이 status를 물리 삭제했으므로 같은 뜻을
                # 3축으로 적는다 — dedup_refresh_repo의 후보 SQL이 요구하는
                # 술어가 정확히 active/published/valid 세 개다(축 하나라도 빠지면
                # draft·suppressed·quarantined 행이 후보로 새어 들어온다).
                lifecycle_state="active",
                publication_state="published",
                quality_state="valid",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            SourceEntityRow(
                source_entity_key=source_entity_key,
                provider_dataset_id=dataset_id,
                source_entity_type="place",
                source_entity_id=feature_id,
                first_seen_at=_NOW,
                last_seen_at=_NOW,
            )
        )
        await session.flush()
        # T-VN-35: place는 subtype 행이 정본이다 — 없으면 consistency F2가 잡는다.
        await seed_feature_subtype(session, feature_id=feature_id, kind="place")
        session.add(
            SourceRecordRow(
                source_record_key=source_record_key,
                source_entity_key=source_entity_key,
                # ck_source_records_payload_hash_canonical = ^[0-9a-f]{1,64}$
                raw_payload_hash=md5(source_record_key.encode()).hexdigest(),
                raw_data={"feature_id": feature_id, "name": name},
                fetched_at=_NOW,
                imported_at=_NOW,
            )
        )
        await session.flush()
        session.add(
            SourceEntityHeadRow(
                source_entity_key=source_entity_key,
                current_source_record_key=source_record_key,
                observed_at=_NOW,
            )
        )
        await session.flush()
        session.add(
            SourceLinkRow(
                feature_id=feature_id,
                source_entity_key=source_entity_key,
                source_role="primary",
                match_method="natural_key",
                confidence=100,
                created_at=_NOW,
            )
        )
