"""``admin_feature_repo`` 통합 테스트 (ADR-045 T-207c)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import md5
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Address, Coordinate, Feature, PlaceDetail
from kortravelmap.infra import feature_repo
from kortravelmap.infra.admin_feature_repo import (
    AdminFeatureStateConflict,
    AdminFeatureStatePreconditionFailed,
    get_feature_row_revision,
    list_admin_feature_state_transitions,
    list_admin_features,
    list_dedup_reviews,
    merge_dedup_review,
    reactivate_admin_feature_state,
    set_dedup_review_decision,
    transition_admin_feature_state,
)
from kortravelmap.infra.feature_repo import upsert_feature
from kortravelmap.infra.models import (
    DedupReviewQueueRow,
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration._feature_ids import feature_uuid
from tests.integration._subtype_seed import seed_feature_subtype

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)

#: dedup 후보 쌍의 정본 키. 이 자리만은 :func:`feature_uuid`로 유도할 수 없다 —
#: ``ops.dedup_review_queue``의 ``ck_dedup_pair_order``가 ``feature_id_a <
#: feature_id_b``를 **uuid 비교**로 강제하는데, 라벨에서 유도한 값의 순서는 라벨의
#: 사전순과 무관하기 때문이다. 그래서 순서를 눈으로 확인할 수 있는 리터럴을 든다
#: (선례: ``test_merge_repo`` ``_F_LOSER``/``_F_MASTER`` · ``test_cli_dedup_merge``).
#: 마지막 마디의 오름차순이 곧 쌍 순서다.
_F_DEDUP_A = "00000000-0000-7000-8000-0000000b0001"
_F_DEDUP_B = "00000000-0000-7000-8000-0000000b0002"
_F_LOCK_A = "00000000-0000-7000-8000-0000000b0011"
_F_LOCK_B = "00000000-0000-7000-8000-0000000b0012"
_F_PAGE_A = "00000000-0000-7000-8000-0000000b0021"
_F_PAGE_B = "00000000-0000-7000-8000-0000000b0022"
_F_PAGE_C = "00000000-0000-7000-8000-0000000b0023"
_F_PAGE_D = "00000000-0000-7000-8000-0000000b0024"
_F_PAGE_E = "00000000-0000-7000-8000-0000000b0025"
_F_FP_A = "00000000-0000-7000-8000-0000000b0031"
_F_FP_B = "00000000-0000-7000-8000-0000000b0032"
_F_FP_C = "00000000-0000-7000-8000-0000000b0033"

#: provider writer에 넣는 **legacy** 식별자. ADR-098에서 DTO ``Feature.feature_id``는
#: provider 라이브러리가 ``make_feature_id(...)``로 유도한 ``f_*``이고 정본 키가
#: 아니다 — 서버가 claim으로 uuid를 발급하고 이 값은 ``feature.feature_aliases``에
#: 주소로 남는다. ``ck_feature_aliases_legacy_alias_shape``가 마지막 마디를 정확히
#: 16자 hex로 못박으므로 읽기 좋은 이름은 hex 안에서 만든다
#: (선례: ``test_feature_identity_boundary``의 ``f_1100000000_p_1db0000000000004``).
_LEGACY_PROVIDER_ID = "f_1100000000_p_ad3100000000ac71"


def _feature_row(
    feature_id: str,
    *,
    name: str,
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
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
        lifecycle_state=lifecycle_state,
        publication_state=publication_state,
        quality_state=quality_state,
        created_at=_NOW,
        updated_at=_NOW,
    )


_PROVIDER = "python-mois-api"
_DATASET_KEY = "mois_license_features_bulk"

_CATALOG_ID_SQL = """
SELECT provider_dataset_id
FROM provider_sync.provider_datasets
WHERE provider = :provider AND dataset_key = :dataset_key
"""

async def _provider_dataset_id(session: AsyncSession) -> int:
    """T-VN-33: source lineage identity는 catalog FK 하나뿐이다."""

    return int(
        (
            await session.execute(
                text(_CATALOG_ID_SQL),
                {"provider": _PROVIDER, "dataset_key": _DATASET_KEY},
            )
        ).scalar_one()
    )


def _source_entity(key: str, provider_dataset_id: int) -> SourceEntityRow:
    return SourceEntityRow(
        source_entity_key=f"se-{key}",
        provider_dataset_id=provider_dataset_id,
        source_entity_type="license_place",
        source_entity_id=key,
        first_seen_at=_NOW,
        last_seen_at=_NOW,
    )


def _source_record(key: str) -> SourceRecordRow:
    return SourceRecordRow(
        source_record_key=key,
        source_entity_key=f"se-{key}",
        # raw_payload_hash는 ``^[0-9a-f]{1,64}$`` CHECK를 만족해야 한다.
        raw_payload_hash=md5(key.encode("utf-8")).hexdigest(),
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


def _provider_source_membership(
    feature_id: str,
) -> feature_repo._ProviderSourceMembership:
    """`_seed_feature`가 만든 canonical source proof를 writer에 전달한다."""
    source_record_key = f"sr-{feature_id}"
    return feature_repo._ProviderSourceMembership(
        source_entity_key=f"se-{source_record_key}",
        source_record_key=source_record_key,
    )


def _dto(
    feature_id: str,
    *,
    legacy_feature_id: str = _LEGACY_PROVIDER_ID,
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
) -> Feature:
    """provider writer(:func:`upsert_feature`)에 넣을 DTO.

    T-VN-39/ADR-098 뒤 이 DTO의 ``feature_id``는 **legacy ``f_*``**다 — provider
    경로의 identity는 ``(provider_dataset_id, feature_kind, natural_key)`` claim이
    소유하고 정본 uuid는 서버가 발급한다. 그래서 정본 키(``feature_id`` 인자)는
    ``provider_natural_key``로 실어 ``_seed_feature``가 심은 claim과 만나게 하고,
    DTO 자신의 식별자 슬롯에는 legacy 주소를 둔다.
    """
    return Feature(
        feature_id=legacy_feature_id,
        provider_natural_key=feature_id,
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
        detail=PlaceDetail(feature_id=legacy_feature_id, place_kind="attraction"),
        lifecycle_state=lifecycle_state,
        publication_state=publication_state,
        quality_state=quality_state,
        created_at=_NOW,
        updated_at=_NOW + timedelta(minutes=5),
    )


_PROVIDER_IDENTITY_CLAIM_SQL = """
INSERT INTO provider_sync.provider_feature_identities (
    provider_dataset_id, feature_kind, natural_key, feature_id, bound_by_operation
) VALUES (
    :provider_dataset_id, 'place', :natural_key, CAST(:feature_id AS uuid),
    'provider_sync'
)
"""


async def _seed_feature(
    session: AsyncSession,
    feature_id: str,
    *,
    natural_key: str | None = None,
) -> None:
    """정본 키(uuid)로 심은 feature 1건 + 그 feature의 provider 계보.

    T-VN-39/ADR-098: provider 경로의 identity는 ``(provider_dataset_id,
    feature_kind, natural_key)`` claim이 소유한다. 재키 전에는 DTO의 ``f_*``가 곧
    PK라 ``ON CONFLICT (feature_id)``가 재적재를 같은 행으로 되돌렸지만, 이제 그
    자리를 claim이 대신한다. 그래서 직접 심은 core 행에도 claim을 함께 걸어야
    provider writer가 **같은** Feature로 돌아온다 — claim이 없으면 writer는 새
    uuid를 주조하고, "admin retirement를 우회하지 못한다"는 명제가 관측 불가능한
    다른 Feature 위에서 참이 되어 버린다.
    """
    session.add(_feature_row(feature_id, name="광화문"))
    await session.flush()
    await seed_feature_subtype(session, feature_id=feature_id, kind="place")
    provider_dataset_id = await _provider_dataset_id(session)
    await session.execute(
        text(_PROVIDER_IDENTITY_CLAIM_SQL),
        {
            "provider_dataset_id": provider_dataset_id,
            "natural_key": natural_key or feature_id,
            "feature_id": feature_id,
        },
    )
    entity = _source_entity(f"sr-{feature_id}", provider_dataset_id)
    session.add(entity)
    await session.flush()
    session.add(_source_record(f"sr-{feature_id}"))
    await session.flush()
    # T-VN-33: 현재 record 포인터는 entity가 아니라 head가 소유한다.
    session.add(
        SourceEntityHeadRow(
            source_entity_key=f"se-sr-{feature_id}",
            current_source_record_key=f"sr-{feature_id}",
            observed_at=_NOW,
        )
    )
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
        master_feature_id=_F_LOCK_A,
    )


async def test_admin_retire_reactivate_is_atomic_and_auditable(
    migrated_session: AsyncSession,
) -> None:
    feature_id = feature_uuid("feature-admin-reactivation")
    await _seed_feature(migrated_session, feature_id)
    initial_revision = await get_feature_row_revision(migrated_session, feature_id)
    assert initial_revision is not None

    retired = await transition_admin_feature_state(
        migrated_session,
        feature_id,
        expected_row_revision=initial_revision,
        reason_code="admin_retire",
        operator="local-admin",
        action="retire",
    )
    assert (
        retired.lifecycle_state,
        retired.publication_state,
        retired.quality_state,
    ) == ("retired", "suppressed", "valid")
    assert retired.row_revision > initial_revision
    assert retired.audit_transition_id > 0

    # 일반 provider writer는 admin retirement override를 우회하지 못한다.
    inserted = await upsert_feature(
        migrated_session,
        _dto(feature_id),
        provider_dataset_id=await _provider_dataset_id(migrated_session),
        source_membership=_provider_source_membership(feature_id),
    )
    assert inserted is False

    reactivation_revision = await get_feature_row_revision(
        migrated_session, feature_id
    )
    assert reactivation_revision is not None

    reactivated = await reactivate_admin_feature_state(
        migrated_session,
        feature_id,
        expected_row_revision=reactivation_revision,
        reason_code="admin_source_reactivated",
        operator="local-admin",
        provider_dataset_id=await _provider_dataset_id(migrated_session),
        source_entity_key=f"se-sr-{feature_id}",
        source_record_key=f"sr-{feature_id}",
    )
    assert (
        reactivated.lifecycle_state,
        reactivated.publication_state,
        reactivated.quality_state,
    ) == ("active", "suppressed", "valid")
    assert reactivated.row_revision > reactivation_revision

    timeline = await list_admin_feature_state_transitions(
        migrated_session, feature_id, limit=10
    )
    assert [item.transition_id for item in timeline.items] == sorted(
        (item.transition_id for item in timeline.items), reverse=True
    )
    assert {retired.audit_transition_id, reactivated.audit_transition_id}.issubset(
        {item.transition_id for item in timeline.items}
    )


async def test_admin_state_transition_rejects_stale_revision(
    migrated_session: AsyncSession,
) -> None:
    feature_id = feature_uuid("feature-admin-stale-revision")
    await _seed_feature(migrated_session, feature_id)
    revision = await get_feature_row_revision(migrated_session, feature_id)
    assert revision is not None

    await transition_admin_feature_state(
        migrated_session,
        feature_id,
        publication_state="suppressed",
        expected_row_revision=revision,
        reason_code="admin_suppress",
        operator="local-admin",
        action="patch",
    )
    with pytest.raises(AdminFeatureStatePreconditionFailed):
        await transition_admin_feature_state(
            migrated_session,
            feature_id,
            quality_state="quarantined",
            expected_row_revision=revision,
            reason_code="admin_quarantine",
            operator="local-admin",
            action="patch",
        )


async def test_list_admin_features_filters_issue_and_primary_source(
    migrated_session: AsyncSession,
) -> None:
    feature_id = feature_uuid("feature-admin-list")
    await _seed_feature(migrated_session, feature_id)
    provider_dataset_id = await _provider_dataset_id(migrated_session)
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.data_integrity_violations (
                feature_id, provider_dataset_id,
                violation_type, severity, message
            ) VALUES (
                :feature_id, :provider_dataset_id,
                'missing_address', 'warning', '주소 검토 필요'
            )
            """
        ),
        {
            "feature_id": feature_id,
            "provider_dataset_id": provider_dataset_id,
        },
    )

    page = await list_admin_features(
        migrated_session,
        q="광화문",
        provider_dataset_id=provider_dataset_id,
        has_issue=True,
        page_size=10,
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.feature_id == feature_id
    assert item.primary_provider == _PROVIDER
    assert item.primary_dataset_key == _DATASET_KEY
    assert item.issue_count == 1
    assert item.issues[0]["violation_type"] == "missing_address"


async def test_dedup_review_decision_updates_pending_only(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    session.add(_feature_row(_F_DEDUP_A, name="중복 A"))
    session.add(_feature_row(_F_DEDUP_B, name="중복 B"))
    await session.flush()
    review = DedupReviewQueueRow(
        feature_id_a=_F_DEDUP_A,
        feature_id_b=_F_DEDUP_B,
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
        session.add(_feature_row(_F_LOCK_A, name="잠금 A"))
        session.add(_feature_row(_F_LOCK_B, name="잠금 B"))
        await session.flush()
        # 이 블록은 rollback이 아니라 **커밋**된다(세션 공유 DB). subtype 없는
        # core 행을 남기면 뒤따르는 테스트의 consistency 게이트(F2 — subtype 결측)가
        # 막힌다. 프로덕션 writer는 두 쓰기를 한 트랜잭션에서 하므로, 시드도 그렇게 한다.
        for locked_id in (_F_LOCK_A, _F_LOCK_B):
            await seed_feature_subtype(session, feature_id=locked_id, kind="place")
        review = DedupReviewQueueRow(
            feature_id_a=_F_LOCK_A,
            feature_id_b=_F_LOCK_B,
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
    for feature_id, label in (
        (_F_PAGE_A, "feature-admin-page-a"),
        (_F_PAGE_B, "feature-admin-page-b"),
        (_F_PAGE_C, "feature-admin-page-c"),
        (_F_PAGE_D, "feature-admin-page-d"),
        (_F_PAGE_E, "feature-admin-page-e"),
    ):
        session.add(_feature_row(feature_id, name=label))
    await session.flush()
    reviews = [
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000003",
            feature_id_a=_F_PAGE_A,
            feature_id_b=_F_PAGE_B,
            total_score=Decimal("90.01"),
            name_score=95,
            spatial_score=80,
            category_score=100,
        ),
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000002",
            feature_id_a=_F_PAGE_A,
            feature_id_b=_F_PAGE_C,
            total_score=Decimal("90.01"),
            name_score=94,
            spatial_score=80,
            category_score=100,
        ),
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000001",
            feature_id_a=_F_PAGE_A,
            feature_id_b=_F_PAGE_D,
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
            feature_id_a=_F_PAGE_A,
            feature_id_b=_F_PAGE_E,
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
    for feature_id, label in (
        (_F_FP_A, "feature-fp-a"),
        (_F_FP_B, "feature-fp-b"),
        (_F_FP_C, "feature-fp-c"),
    ):
        session.add(_feature_row(feature_id, name=label))
    await session.flush()
    session.add_all(
        [
            DedupReviewQueueRow(
                review_id="00000000-0000-0000-0000-0000000000a2",
                feature_id_a=_F_FP_A,
                feature_id_b=_F_FP_B,
                total_score=Decimal("60.00"),
                name_score=60,
                spatial_score=60,
                category_score=60,
            ),
            DedupReviewQueueRow(
                review_id="00000000-0000-0000-0000-0000000000a1",
                feature_id_a=_F_FP_A,
                feature_id_b=_F_FP_C,
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


async def test_retired_feature_publication_patch_is_a_conflict_not_a_500(
    migrated_session: AsyncSession,
) -> None:
    """``ck_features_state_tuple`` 위반이 도메인 오류로 보존되는지 **실 DB로** 본다.

    이 축이 없으면 매핑은 조용히 죽는다. 실제로 그랬다 — constraint 이름을
    ``error.orig``에서만 찾았는데 asyncpg는 그것을 ``error.orig.__cause__``에 둔다.
    그래서 두 집합의 이름 8개가 **하나도** 매칭되지 않았고 모든 23514가 라우터의
    except 사슬을 통과해 catch-all 500이 됐다. 이름을 집합에서 빼도 게이트가 전부
    green이었으므로 매핑에는 부하가 전혀 없었다.

    단언 대상을 상태코드가 아니라 **도메인 예외 타입**으로 두는 이유는, 라우터가
    그 타입으로 409를 만들기 때문이다(타입이 맞으면 상태코드는 라우터 테스트가 고정한다).
    """

    feature_id = feature_uuid("feature-retired-publication-patch")
    await _seed_feature(migrated_session, feature_id)
    revision = await get_feature_row_revision(migrated_session, feature_id)
    assert revision is not None

    retired = await transition_admin_feature_state(
        migrated_session,
        feature_id,
        expected_row_revision=revision,
        reason_code="admin_retire",
        operator="local-admin",
        action="retire",
    )
    assert retired.lifecycle_state == "retired"

    with pytest.raises(AdminFeatureStateConflict):
        await transition_admin_feature_state(
            migrated_session,
            feature_id,
            expected_row_revision=retired.row_revision,
            reason_code="admin_publish_retired",
            operator="local-admin",
            action="patch",
            publication_state="published",
        )
