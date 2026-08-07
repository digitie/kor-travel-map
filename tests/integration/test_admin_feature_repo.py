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

from kortravelmap.dto import Address, Coordinate, Feature, PlaceDetail
from kortravelmap.infra.admin_feature_repo import (
    FeatureStateConflict,
    apply_feature_change_request,
    deactivate_feature,
    get_feature_row_revision,
    list_admin_features,
    list_dedup_reviews,
    merge_dedup_review,
    set_dedup_review_decision,
    submit_feature_change_request,
)
from kortravelmap.infra.feature_repo import upsert_feature
from kortravelmap.infra.models import (
    DedupReviewQueueRow,
    FeatureRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration._subtype_seed import seed_feature_subtype

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
        urls={},
        raw_refs=[],
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _source_entity(key: str, provider: str = "python-mois-api") -> SourceEntityRow:
    return SourceEntityRow(
        source_entity_key=f"se-{key}",
        provider=provider,
        dataset_key="mois_license_features_bulk",
        source_entity_type="license_place",
        source_entity_id=key,
        current_source_record_key=None,
        first_seen_at=_NOW,
        last_seen_at=_NOW,
    )


def _source_record(key: str, provider: str = "python-mois-api") -> SourceRecordRow:
    return SourceRecordRow(
        source_record_key=key,
        source_entity_key=f"se-{key}",
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
        source_entity_key=f"se-{source_record_key}",
        source_role="primary",
        match_method="natural_key",
        confidence=100,
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
    entity = _source_entity(f"sr-{feature_id}")
    session.add(entity)
    await session.flush()
    session.add(_source_record(f"sr-{feature_id}"))
    await session.flush()
    entity.current_source_record_key = f"sr-{feature_id}"
    await session.flush()
    session.add(_source_link(feature_id, f"sr-{feature_id}"))
    await session.flush()


async def _merge_dedup_review_with_short_lock_timeout(
    session: AsyncSession, review_id: str
) -> None:
    await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
    await merge_dedup_review(
        session,
        review_id,
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


async def test_deactivate_rejects_deleted_feature(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-deleted"
    await _seed_feature(migrated_session, feature_id)
    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET status = 'deleted',
                deleted_at = now(),
                updated_at = now()
            WHERE feature_id = :feature_id
            """
        ),
        {"feature_id": feature_id},
    )

    with pytest.raises(FeatureStateConflict) as exc_info:
        await deactivate_feature(
            migrated_session,
            feature_id,
            reason="삭제 feature 부활 방지",
            operator="local-admin",
        )

    assert exc_info.value.current_status == "deleted"
    row = (
        await migrated_session.execute(
            select(FeatureRow.status, FeatureRow.deleted_at).where(
                FeatureRow.feature_id == feature_id
            )
        )
    ).one()
    assert row.status == "deleted"
    assert row.deleted_at is not None


async def test_user_update_version_overrides_provider_reload(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-user-update"
    await _seed_feature(migrated_session, feature_id)

    request = await submit_feature_change_request(
        migrated_session,
        action="update",
        feature_id=feature_id,
        payload={
            "name": "사용자 수정 이름",
            "road_name_code": "111104100001",
            "admin_dong_code": "1111051500",
            "urls": {"homepage": "https://example.test/user-feature"},
            # T-VN-35(ADR-086): admin detail도 kind별 typed 컬럼으로 들어가므로
            # 필수 필드(place_kind)를 갖춘 shape이어야 한다. 자유 키는 payload로.
            "detail": {"place_kind": "attraction", "payload": {"note": "사용자 수정"}},
        },
        review_mode="immediate",
        reason="사용자 제보 반영",
        requested_by="admin",
        expected_row_revision=await get_feature_row_revision(
            migrated_session, feature_id
        ),
    )
    assert request.state == "applied"

    second_request = await submit_feature_change_request(
        migrated_session,
        action="update",
        feature_id=feature_id,
        payload={
            "name": "사용자 수정 이름 2",
            "detail": {
                "place_kind": "attraction",
                "payload": {"note": "사용자 수정 2"},
            },
        },
        review_mode="immediate",
        reason="사용자 제보 추가 반영",
        requested_by="admin",
        expected_row_revision=await get_feature_row_revision(
            migrated_session, feature_id
        ),
    )
    assert second_request.state == "applied"

    inserted = await upsert_feature(migrated_session, _dto(feature_id, status="active"))
    assert inserted is False

    row = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    name, road_name_code, admin_dong_code, urls, detail,
                    data_origin, data_version, user_change_kind
                FROM feature.features_detailed
                WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert row["name"] == "사용자 수정 이름 2"
    assert row["road_name_code"] == "111104100001"
    assert row["admin_dong_code"] == "1111051500"
    assert row["urls"]["homepage"] == "https://example.test/user-feature"
    assert row["detail"]["payload"]["note"] == "사용자 수정 2"
    assert row["data_origin"] == "user_request"
    assert row["data_version"] == 2
    assert row["user_change_kind"] == "update"

    versions = (
        await migrated_session.execute(
            text(
                """
                SELECT version, origin, change_kind
                FROM feature.feature_versions
                WHERE feature_id = :feature_id
                ORDER BY version
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    assert [(v["version"], v["origin"], v["change_kind"]) for v in versions] == [
        (0, "provider", "load"),
        (1, "user_request", "update"),
        (2, "user_request", "update"),
    ]
    version_payloads = (
        await migrated_session.execute(
            text(
                """
                SELECT version, payload
                FROM feature.feature_versions
                WHERE feature_id = :feature_id
                  AND version IN (1, 2)
                ORDER BY version
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    assert version_payloads[0]["payload"]["name"] == "사용자 수정 이름"
    assert version_payloads[0]["payload"]["data_version"] == 1
    assert version_payloads[1]["payload"]["name"] == "사용자 수정 이름 2"
    assert version_payloads[1]["payload"]["data_version"] == 2


async def test_user_delete_soft_delete_prevents_provider_resurrection(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-user-delete"
    await _seed_feature(migrated_session, feature_id)

    request = await submit_feature_change_request(
        migrated_session,
        action="delete",
        feature_id=feature_id,
        payload={},
        review_mode="immediate",
        reason="사용자 삭제 요청",
        requested_by="admin",
        expected_row_revision=await get_feature_row_revision(
            migrated_session, feature_id
        ),
    )
    assert request.state == "applied"

    await upsert_feature(migrated_session, _dto(feature_id, status="active"))

    row = (
        await migrated_session.execute(
            text(
                """
                SELECT status, data_origin, data_version, user_deleted_at, user_deleted_by
                FROM feature.features
                WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert row["status"] == "deleted"
    assert row["data_origin"] == "user_request"
    assert row["data_version"] == 1
    assert row["user_deleted_at"] is not None
    assert row["user_deleted_by"] == "admin"


async def test_review_required_add_applies_only_after_admin_approval(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-user-add"
    payload = {
        "kind": "place",
        "name": "사용자 추가 장소",
        "category": "01070300",
        "coord": {"lon": 126.9769, "lat": 37.5759},
        "marker_icon": "marker",
        "marker_color": "P-01",
        "detail": {"place_kind": "attraction"},
    }

    request = await submit_feature_change_request(
        migrated_session,
        action="add",
        feature_id=feature_id,
        payload=payload,
        review_mode="require_review",
        reason="사용자 추가 요청",
        requested_by="external-app",
    )
    assert request.state == "pending"
    assert (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": feature_id},
        )
    ).scalar_one() == 0

    applied = await apply_feature_change_request(
        migrated_session,
        request.request_id,
        operator="admin",
    )
    assert applied is not None
    assert applied.state == "applied"

    row = (
        await migrated_session.execute(
            text(
                """
                SELECT name, data_origin, data_version, user_change_kind
                FROM feature.features
                WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert row["name"] == "사용자 추가 장소"
    assert row["data_origin"] == "user_request"
    assert row["data_version"] == 1
    assert row["user_change_kind"] == "add"


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
        str(review.review_id),
        decision="rejected",
        reviewed_by="local-admin",
        decision_reason="서로 다른 장소",
    )
    assert changed is True

    unchanged = await set_dedup_review_decision(
        session,
        str(review.review_id),
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
        # 이 블록은 rollback이 아니라 **커밋**된다(세션 공유 DB). subtype 없는
        # core 행을 남기면 뒤따르는 테스트의 consistency 게이트(F2 — subtype 결측)가
        # 막힌다. 프로덕션 writer는 두 쓰기를 한 트랜잭션에서 하므로, 시드도 그렇게 한다.
        for locked_id in ("feature-admin-lock-a", "feature-admin-lock-b"):
            await seed_feature_subtype(session, feature_id=locked_id, kind="place")
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
        review_id = str(review.review_id)

    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text(
                "SELECT review_id FROM ops.dedup_review_queue "
                "WHERE review_id = :review_id FOR UPDATE"
            ),
            {"review_id": review_id},
        )

        async with AsyncSession(migrated_engine) as contender:
            with pytest.raises(DBAPIError):
                await _merge_dedup_review_with_short_lock_timeout(
                    contender, review_id
                )


async def test_list_dedup_reviews_keyset_walk_stable_under_mutation(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    for feature_id in (
        "feature-admin-page-a",
        "feature-admin-page-b",
        "feature-admin-page-c",
        "feature-admin-page-d",
        "feature-admin-page-e",
    ):
        session.add(_feature_row(feature_id, name=feature_id))
    await session.flush()
    reviews = [
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000003",
            feature_id_a="feature-admin-page-a",
            feature_id_b="feature-admin-page-b",
            total_score=Decimal("90.01"),
            name_score=95,
            spatial_score=80,
            category_score=100,
        ),
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000002",
            feature_id_a="feature-admin-page-a",
            feature_id_b="feature-admin-page-c",
            total_score=Decimal("90.01"),
            name_score=94,
            spatial_score=80,
            category_score=100,
        ),
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000001",
            feature_id_a="feature-admin-page-a",
            feature_id_b="feature-admin-page-d",
            total_score=Decimal("90.01"),
            name_score=93,
            spatial_score=80,
            category_score=100,
        ),
    ]
    session.add_all(reviews)
    await session.flush()

    # 동일 total_score에서 (total_score DESC, review_id DESC) total order를 keyset이
    # page_size=1로 정확히 walk한다.
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(3):
        page = await list_dedup_reviews(session, page_size=1, cursor=cursor)
        assert len(page.items) == 1
        assert page.total_count == 3
        seen.append(page.items[0].review_id)
        cursor = page.next_cursor
    assert seen == [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]
    assert cursor is None  # 마지막 페이지 뒤 next_cursor는 None

    # 페이지 경계 mutation 회귀: page1 뒤 커서보다 앞(더 높은 점수) 행을 삽입해도 keyset은
    # 남은 행만 중복·누락 없이 이어간다. OFFSET이라면 삽입이 뒤 페이지를 한 칸 밀어 앞
    # 페이지 행을 재노출한다.
    page1 = await list_dedup_reviews(session, page_size=1, cursor=None)
    assert [item.review_id for item in page1.items] == [
        "00000000-0000-0000-0000-000000000003"
    ]
    session.add(
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000009",
            feature_id_a="feature-admin-page-a",
            feature_id_b="feature-admin-page-e",
            total_score=Decimal("99.99"),  # page1 커서보다 상위 순위
            name_score=99,
            spatial_score=80,
            category_score=100,
        )
    )
    await session.flush()

    walked: list[str] = [page1.items[0].review_id]
    cursor = page1.next_cursor
    while cursor is not None:
        page = await list_dedup_reviews(session, page_size=1, cursor=cursor)
        assert len(page.items) <= 1
        walked.extend(item.review_id for item in page.items)
        cursor = page.next_cursor

    # 삽입한 상위 점수 009는 커서 앞이라 이 walk에 나타나지 않고, 003 재노출 없이 002·001을
    # 각각 정확히 한 번 본다(중복·누락 0).
    assert walked == [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]
    assert len(walked) == len(set(walked))


async def test_list_dedup_reviews_cursor_rejects_filter_change(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    for feature_id in ("feature-fp-a", "feature-fp-b", "feature-fp-c"):
        session.add(_feature_row(feature_id, name=feature_id))
    await session.flush()
    session.add_all(
        [
            DedupReviewQueueRow(
                review_id="00000000-0000-0000-0000-0000000000a2",
                feature_id_a="feature-fp-a",
                feature_id_b="feature-fp-b",
                total_score=Decimal("60.00"),
                name_score=60,
                spatial_score=60,
                category_score=60,
            ),
            DedupReviewQueueRow(
                review_id="00000000-0000-0000-0000-0000000000a1",
                feature_id_a="feature-fp-a",
                feature_id_b="feature-fp-c",
                total_score=Decimal("55.00"),
                name_score=55,
                spatial_score=55,
                category_score=55,
            ),
        ]
    )
    await session.flush()

    page = await list_dedup_reviews(session, page_size=1, min_score=10)
    assert page.next_cursor is not None

    # 같은 커서를 다른 필터(min_score 변경)로 재사용하면 fingerprint 불일치로 거부한다.
    with pytest.raises(ValueError, match="invalid dedup_review cursor"):
        await list_dedup_reviews(
            session, page_size=1, min_score=20, cursor=page.next_cursor
        )
    # 같은 필터면 keyset을 정상적으로 이어간다.
    page2 = await list_dedup_reviews(
        session, page_size=1, min_score=10, cursor=page.next_cursor
    )
    assert [item.review_id for item in page2.items] == [
        "00000000-0000-0000-0000-0000000000a1"
    ]
