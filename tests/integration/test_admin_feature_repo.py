"""``admin_feature_repo`` 통합 테스트 (ADR-045 T-207c)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map.dto import Address, Coordinate, Feature, PlaceDetail
from krtour.map.infra.admin_feature_repo import (
    deactivate_feature,
    list_admin_features,
    list_dedup_reviews,
    merge_dedup_review,
    set_dedup_review_decision,
)
from krtour.map.infra.feature_repo import upsert_feature
from krtour.map.infra.models import (
    DedupReviewQueueRow,
    FeatureRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)


def _feature_row(
    feature_id: str,
    *,
    name: str,
    status: str = "active",
) -> FeatureRow:
    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name=name,
        category="01070300",
        coord=WKTElement("POINT(126.9769 37.5759)", srid=4326),
        address={"road": "서울특별시 종로구 세종대로 1"},
        detail={"place_kind": "attraction"},
        urls={},
        raw_refs=[],
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _source_record(key: str, provider: str = "python-mois-api") -> SourceRecordRow:
    return SourceRecordRow(
        source_record_key=key,
        provider=provider,
        dataset_key="mois_license_features_bulk",
        source_entity_type="license_place",
        source_entity_id=key,
        raw_name="광화문",
        raw_address="서울특별시 종로구 세종대로 1",
        raw_payload_hash=f"hash-{key}",
        raw_data={"id": key},
        fetched_at=_NOW,
        imported_at=_NOW,
    )


def _source_link(feature_id: str, source_record_key: str) -> SourceLinkRow:
    return SourceLinkRow(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role="primary",
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
        created_at=_NOW,
    )


def _dto(feature_id: str, *, status: str = "active") -> Feature:
    return Feature(
        feature_id=feature_id,
        kind="place",
        name="광화문 재적재",
        category="01070300",
        coord=Coordinate(lon=Decimal("126.9769"), lat=Decimal("37.5759")),
        address=Address(
            road="서울특별시 종로구 세종대로 1",
            bjd_code="1111010100",
            sigungu_code="11110",
            sido_code="11",
        ),
        marker_icon="marker",
        marker_color="P-01",
        detail=PlaceDetail(feature_id=feature_id, place_kind="attraction"),
        status=status,
        created_at=_NOW,
        updated_at=_NOW + timedelta(minutes=5),
    )


async def _seed_feature(
    session: AsyncSession,
    feature_id: str = "feature-admin-1",
) -> None:
    session.add(_feature_row(feature_id, name="광화문"))
    session.add(_source_record(f"sr-{feature_id}"))
    await session.flush()
    session.add(_source_link(feature_id, f"sr-{feature_id}"))
    await session.flush()


async def _merge_dedup_review_with_short_lock_timeout(
    session: AsyncSession, review_key: str
) -> None:
    await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
    await merge_dedup_review(
        session,
        review_key,
        master_feature_id="feature-admin-lock-a",
    )


async def test_deactivate_creates_override_and_provider_upsert_preserves_status(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-reactivation"
    await _seed_feature(migrated_session, feature_id)

    result = await deactivate_feature(
        migrated_session,
        feature_id,
        reason="운영상 제외",
        operator="local-admin",
        prevent_provider_reactivation=True,
    )
    assert result is not None
    assert result.previous_status == "active"
    assert result.status == "inactive"
    assert result.override is not None
    assert result.override.field_path == "status"

    inserted = await upsert_feature(migrated_session, _dto(feature_id, status="active"))
    assert inserted is False

    row = (
        await migrated_session.execute(
            select(FeatureRow.status, FeatureRow.deleted_at).where(
                FeatureRow.feature_id == feature_id
            )
        )
    ).one()
    assert row.status == "inactive"
    assert row.deleted_at is None

    override_count = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM ops.feature_overrides "
                "WHERE feature_id = :feature_id AND status = 'active'"
            ),
            {"feature_id": feature_id},
        )
    ).scalar_one()
    assert override_count == 1


async def test_list_admin_features_filters_issue_and_primary_source(
    migrated_session: AsyncSession,
) -> None:
    await _seed_feature(migrated_session, "feature-admin-list")
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.data_integrity_violations (
                feature_id, provider, dataset_key,
                violation_type, severity, message
            ) VALUES (
                :feature_id, 'python-mois-api', 'mois_license_features_bulk',
                'missing_address', 'warning', '주소 검토 필요'
            )
            """
        ),
        {"feature_id": "feature-admin-list"},
    )

    page = await list_admin_features(
        migrated_session,
        q="광화문",
        providers=["python-mois-api"],
        has_issue=True,
        page_size=10,
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.feature_id == "feature-admin-list"
    assert item.primary_provider == "python-mois-api"
    assert item.issue_count == 1
    assert item.issues[0]["violation_type"] == "missing_address"


async def test_dedup_review_decision_updates_pending_only(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    session.add(_feature_row("feature-admin-dedup-a", name="중복 A"))
    session.add(_feature_row("feature-admin-dedup-b", name="중복 B"))
    await session.flush()
    review = DedupReviewQueueRow(
        feature_id_a="feature-admin-dedup-a",
        feature_id_b="feature-admin-dedup-b",
        total_score=90,
        name_score=95,
        spatial_score=80,
        category_score=100,
    )
    session.add(review)
    await session.flush()

    changed = await set_dedup_review_decision(
        session,
        str(review.review_key),
        decision="rejected",
        reviewed_by="local-admin",
        decision_reason="서로 다른 장소",
    )
    assert changed is True

    unchanged = await set_dedup_review_decision(
        session,
        str(review.review_key),
        decision="ignored",
    )
    assert unchanged is False


async def test_merge_dedup_review_explicit_master_locks_review_row(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        session.add(_feature_row("feature-admin-lock-a", name="잠금 A"))
        session.add(_feature_row("feature-admin-lock-b", name="잠금 B"))
        await session.flush()
        review = DedupReviewQueueRow(
            feature_id_a="feature-admin-lock-a",
            feature_id_b="feature-admin-lock-b",
            total_score=90,
            name_score=95,
            spatial_score=80,
            category_score=100,
            status="rejected",
        )
        session.add(review)
        await session.flush()
        review_key = str(review.review_key)

    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text(
                "SELECT review_key FROM ops.dedup_review_queue "
                "WHERE review_key = :review_key FOR UPDATE"
            ),
            {"review_key": review_key},
        )

        async with AsyncSession(migrated_engine) as contender:
            with pytest.raises(DBAPIError):
                await _merge_dedup_review_with_short_lock_timeout(
                    contender, review_key
                )


async def test_list_dedup_reviews_cursor_walks_same_score_without_gaps(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    for feature_id in (
        "feature-admin-cursor-a",
        "feature-admin-cursor-b",
        "feature-admin-cursor-c",
        "feature-admin-cursor-d",
    ):
        session.add(_feature_row(feature_id, name=feature_id))
    await session.flush()
    reviews = [
        DedupReviewQueueRow(
            review_key="00000000-0000-0000-0000-000000000003",
            feature_id_a="feature-admin-cursor-a",
            feature_id_b="feature-admin-cursor-b",
            total_score=Decimal("90.01"),
            name_score=95,
            spatial_score=80,
            category_score=100,
        ),
        DedupReviewQueueRow(
            review_key="00000000-0000-0000-0000-000000000002",
            feature_id_a="feature-admin-cursor-a",
            feature_id_b="feature-admin-cursor-c",
            total_score=Decimal("90.01"),
            name_score=94,
            spatial_score=80,
            category_score=100,
        ),
        DedupReviewQueueRow(
            review_key="00000000-0000-0000-0000-000000000001",
            feature_id_a="feature-admin-cursor-a",
            feature_id_b="feature-admin-cursor-d",
            total_score=Decimal("90.01"),
            name_score=93,
            spatial_score=80,
            category_score=100,
        ),
    ]
    session.add_all(reviews)
    await session.flush()

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(3):
        page = await list_dedup_reviews(session, page_size=1, cursor=cursor)
        assert len(page.items) == 1
        assert page.items[0].total_score_cursor == "90.01"
        seen.append(page.items[0].review_key)
        cursor = page.next_cursor

    assert seen == [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]
    assert cursor is None
