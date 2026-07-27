"""``test_merge_repo`` — dedup 수동 병합 1차 함수 (ADR-016, Sprint 4a).

``merge_from_review``/``apply_feature_merge``가 실 PostGIS에서:
① loser source_link를 master로 재지정(+ 충돌 link drop)
② loser curation item을 master로 재지정(+ 동일 item 충돌 drop)
③ loser feature soft-delete ④ ``feature_merge_history`` 기록
⑤ ``dedup_review_queue`` ``merged`` 전이 하는지 검증.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.merge_repo import (
    MergeConflictError,
    MergeNotFoundError,
    apply_feature_merge,
    merge_from_review,
)
from kortravelmap.infra.models import (
    DedupReviewQueueRow,
    FeatureRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_CAT = "01070100"
_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _feature(feature_id: str, *, with_coord: bool) -> FeatureRow:
    from geoalchemy2 import WKTElement

    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name="불국사",
        category=_CAT,
        coord=WKTElement("POINT(129.3320 35.7900)", srid=4326) if with_coord else None,
        detail={"summary": "temple"},
    )


def _source_entity(key: str, provider: str) -> SourceEntityRow:
    return SourceEntityRow(
        source_entity_key=key,
        provider=provider,
        dataset_key="d",
        source_entity_type="t",
        source_entity_id=key,
        current_source_record_key=None,
        first_seen_at=_FETCHED,
        last_seen_at=_FETCHED,
    )


def _source_record(key: str, provider: str, *, source_entity_key: str) -> SourceRecordRow:
    return SourceRecordRow(
        source_record_key=key,
        source_entity_key=source_entity_key,
        provider=provider,
        dataset_key="d",
        source_entity_type="t",
        source_entity_id=source_entity_key,
        raw_payload_hash="h",
        raw_data={},
        fetched_at=_FETCHED,
    )


def _link(feature_id: str, entity_key: str, *, primary: bool = True) -> SourceLinkRow:
    return SourceLinkRow(
        feature_id=feature_id,
        source_entity_key=entity_key,
        source_role="primary" if primary else "enrichment",
        match_method="natural_key",
        confidence=100,
        is_primary_source=primary,
    )


async def _seed_pair(engine: AsyncEngine) -> str:
    """master(좌표 O) + loser(좌표 X) + source_links(충돌 SR 포함) + 큐 1행 적재.

    반환: 생성된 ``review_id``. SE1은 양쪽 모두 링크(충돌), SE2는 loser 전용.
    """
    async with AsyncSession(engine) as session, session.begin():
        session.add(_feature("f_master", with_coord=True))
        session.add(_feature("f_loser", with_coord=False))
        entity_1 = _source_entity("SE1", "python-mois-api")
        entity_2 = _source_entity("SE2", "python-visitkorea-api")
        session.add(entity_1)
        session.add(entity_2)
        await session.flush()
        session.add(_source_record("SR1", "python-mois-api", source_entity_key="SE1"))
        session.add(_source_record("SR2", "python-visitkorea-api", source_entity_key="SE2"))
        await session.flush()
        entity_1.current_source_record_key = "SR1"
        entity_2.current_source_record_key = "SR2"
        await session.flush()
        session.add(_link("f_master", "SE1"))
        session.add(_link("f_loser", "SE1", primary=False))  # 충돌 — master 보유
        session.add(_link("f_loser", "SE2"))  # loser 전용 — 이동 대상
        await session.execute(
            text(
                """
                WITH theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group
                    ) VALUES ('merge-test', '병합 테스트', 'test')
                    RETURNING theme_id
                ), collection AS (
                    INSERT INTO feature.curation_collections (
                        collection_key, theme_id, title
                    )
                    SELECT 'merge-test:2026', theme_id, '병합 테스트 2026'
                    FROM theme
                    RETURNING collection_id
                )
                INSERT INTO feature.curation_items (
                    collection_id, feature_id, external_item_id, place_name, status
                )
                SELECT collection_id, 'f_master', 'shared', '마스터 장소', 'included'
                FROM collection
                UNION ALL
                SELECT collection_id, 'f_loser', 'shared', '병합 대상 장소', 'included'
                FROM collection
                UNION ALL
                SELECT collection_id, 'f_loser', 'loser-only', '병합 대상 장소', 'included'
                FROM collection
                """
            )
        )
        await session.execute(
            text(
                """
                WITH source AS (
                    INSERT INTO feature.curated_sources (
                        provider, dataset_key, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        'merge-test-provider', 'legacy-curation',
                        '병합 legacy 출처', 'manual', 'unknown',
                        'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id
                ), themes AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES
                        ('legacy-merge-conflict', 'legacy 병합 충돌', 'test', 'public'),
                        ('legacy-merge-loser-only', 'legacy 병합 단독', 'test', 'public')
                    RETURNING theme_id, theme_slug
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id, curation_status,
                    selection_origin, display_title, display_summary
                )
                SELECT
                    themes.theme_id, 'f_master', source.source_id, 'curated',
                    'admin', 'legacy 충돌 master', '병합 전 master'
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'legacy-merge-conflict'
                UNION ALL
                SELECT
                    themes.theme_id, 'f_loser', source.source_id, 'curated',
                    'admin', 'legacy 충돌 loser', '병합 전 loser'
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'legacy-merge-conflict'
                UNION ALL
                SELECT
                    themes.theme_id, 'f_loser', source.source_id, 'curated',
                    'admin', 'legacy 단독 loser', '병합 전 loser'
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'legacy-merge-loser-only'
                """
            )
        )
        row = DedupReviewQueueRow(
            feature_id_a="f_loser",
            feature_id_b="f_master",
            total_score=90,
            name_score=95,
            spatial_score=88,
            category_score=80,
        )
        session.add(row)
        await session.flush()
        return str(row.review_id)


async def _links_of(engine: AsyncEngine, feature_id: str) -> set[str]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(SourceLinkRow.source_entity_key).where(SourceLinkRow.feature_id == feature_id)
        )
        return {r[0] for r in result}


async def _feature_status(engine: AsyncEngine, feature_id: str) -> tuple[str, bool]:
    async with AsyncSession(engine) as session:
        row = (
            await session.execute(
                select(FeatureRow.status, FeatureRow.deleted_at).where(
                    FeatureRow.feature_id == feature_id
                )
            )
        ).one()
        return (row[0], row[1] is not None)


async def _merge_from_review_with_short_lock_timeout(session: AsyncSession, review_id: str) -> None:
    await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
    await merge_from_review(session, review_id)


@pytest.fixture
async def seeded(pg_container: object, migrated_engine: AsyncEngine) -> object:
    """병합 대상 1쌍 적재 + teardown TRUNCATE. 반환: review_id."""
    review_id = await _seed_pair(migrated_engine)
    yield review_id
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(
            text(
                "TRUNCATE feature.curation_collections, feature.curated_themes, "
                "feature.curated_sources, "
                "feature.features, provider_sync.source_entities, "
                "provider_sync.source_records, "
                "provider_sync.source_links, ops.dedup_review_queue, "
                "ops.feature_merge_history RESTART IDENTITY CASCADE"
            )
        )


async def test_merge_from_review_full_flow(seeded: str, migrated_engine: AsyncEngine) -> None:
    review_id = seeded
    async with AsyncSession(migrated_engine) as session, session.begin():
        outcome = await merge_from_review(session, review_id, merged_by="op-1", reason="dup")

    # 좌표 보유 master 선정 (ADR-016 1순위).
    assert outcome.master_feature_id == "f_master"
    assert outcome.loser_feature_id == "f_loser"
    # SE2 이동(1), 충돌 SE1 drop(1).
    assert outcome.source_links_moved == 1
    assert outcome.source_links_dropped == 1
    assert outcome.queue_updated is True

    # master는 SE1+SE2 보유, loser는 링크 없음.
    assert await _links_of(migrated_engine, "f_master") == {"SE1", "SE2"}
    assert await _links_of(migrated_engine, "f_loser") == set()
    async with AsyncSession(migrated_engine) as session:
        items = (
            await session.execute(
                text(
                    """
                    SELECT feature_id, external_item_id
                    FROM feature.curation_items
                    WHERE collection_id = (
                        SELECT collection_id
                        FROM feature.curation_collections
                        WHERE collection_key = 'merge-test:2026'
                    )
                      AND archived_at IS NULL
                    ORDER BY external_item_id
                    """
                )
            )
        ).all()
    assert items == [
        ("f_master", "loser-only"),
        ("f_master", "shared"),
    ]

    # legacy row도 master로 옮겨야 이후 0045 sync trigger가 loser를 되살리지 않는다.
    async with AsyncSession(migrated_engine) as session, session.begin():
        legacy_rows = (
            await session.execute(
                text(
                    """
                    SELECT display_title, feature_id, curation_status,
                           archived_at IS NOT NULL AS archived
                    FROM feature.curated_features
                    WHERE display_title LIKE 'legacy %'
                    ORDER BY display_title
                    """
                )
            )
        ).all()
        await session.execute(
            text(
                """
                UPDATE feature.curated_features
                SET display_summary = '병합 후 legacy writer 갱신',
                    updated_at = clock_timestamp()
                WHERE display_title IN ('legacy 충돌 loser', 'legacy 단독 loser')
                """
            )
        )
    assert legacy_rows == [
        ("legacy 단독 loser", "f_master", "curated", False),
        ("legacy 충돌 loser", "f_master", "archived", True),
        ("legacy 충돌 master", "f_master", "curated", False),
    ]
    async with AsyncSession(migrated_engine) as session:
        active_legacy_items = (
            await session.execute(
                text(
                    """
                    SELECT c.title, i.feature_id, i.source_present
                    FROM feature.curation_items AS i
                    JOIN feature.curation_collections AS c
                      ON c.collection_id = i.collection_id
                    WHERE c.collection_key LIKE 'legacy:legacy-merge-%'
                      AND i.archived_at IS NULL
                    ORDER BY c.title
                    """
                )
            )
        ).all()
        loser_memberships = (
            await session.execute(
                text("SELECT count(*) FROM feature.curation_items WHERE feature_id = 'f_loser'")
            )
        ).scalar_one()
    assert active_legacy_items == [
        ("legacy 단독 loser", "f_master", True),
        ("legacy 충돌 loser", "f_master", True),
        ("legacy 충돌 master", "f_master", True),
    ]
    assert loser_memberships == 0
    # loser soft-delete.
    assert await _feature_status(migrated_engine, "f_loser") == ("deleted", True)
    # master는 그대로 active.
    status, _ = await _feature_status(migrated_engine, "f_master")
    assert status == "active"

    # feature_merge_history 1행 + 큐 merged.
    async with AsyncSession(migrated_engine) as session:
        hist = (
            await session.execute(
                text(
                    "SELECT master_feature_id, loser_feature_id, score, "
                    "merged_by, review_id FROM ops.feature_merge_history"
                )
            )
        ).one()
        assert hist[0] == "f_master"
        assert hist[1] == "f_loser"
        assert float(hist[2]) == 90.0
        assert hist[3] == "op-1"
        assert str(hist[4]) == review_id
        qstatus = (
            await session.execute(
                text("SELECT status, reviewed_by FROM ops.dedup_review_queue WHERE review_id = :k"),
                {"k": review_id},
            )
        ).one()
        assert qstatus[0] == "merged"
        assert qstatus[1] == "op-1"
        override = (
            await session.execute(
                text(
                    """
                    SELECT override_value, prevent_provider_reactivation, reason, created_by
                    FROM ops.feature_overrides
                    WHERE feature_id = 'f_loser'
                      AND field_path = 'status'
                      AND status = 'active'
                    """
                )
            )
        ).one()
        assert override[0] == "deleted"
        assert override[1] is True
        assert override[2] == "dup"
        assert override[3] == "op-1"


@pytest.mark.parametrize(
    ("master_present", "loser_present", "expected_place"),
    [
        (False, True, "loser provider"),
        (True, False, "master provider"),
        (True, True, "loser provider"),
    ],
)
async def test_merge_reconciles_source_presence_and_latest_operator_override(
    seeded: str,
    migrated_engine: AsyncEngine,
    master_present: bool,
    loser_present: bool,
    expected_place: str,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET source_present = :master_present,
                    place_name = 'master provider',
                    status = 'included',
                    curation_relation = 'nearby_option',
                    reuse_policy = 'manual_review',
                    updated_by = 'master-provider-refresh',
                    source_updated_at = now() - interval '2 hours',
                    operator_updated_by = 'master-operator',
                    operator_updated_at = now() - interval '2 hours',
                    updated_at = now()
                WHERE feature_id = 'f_master'
                  AND external_item_id = 'shared'
                """
            ),
            {"master_present": master_present},
        )
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET source_present = :loser_present,
                    place_name = 'loser provider',
                    status = 'rejected',
                    curation_relation = 'primary_stop',
                    reuse_policy = 'blocked',
                    updated_by = 'loser-provider-refresh',
                    source_updated_at = now() - interval '1 hour',
                    operator_updated_by = 'latest-operator',
                    operator_updated_at = now() - interval '1 hour',
                    updated_at = now() - interval '3 hours'
                WHERE feature_id = 'f_loser'
                  AND external_item_id = 'shared'
                """
            ),
            {"loser_present": loser_present},
        )
        await merge_from_review(session, seeded, merged_by="merge-operator")

    async with AsyncSession(migrated_engine) as session:
        survivor = (
            await session.execute(
                text(
                    """
                    SELECT
                        feature_id, source_present, place_name, status,
                        curation_relation, reuse_policy, operator_updated_by
                    FROM feature.curation_items
                    WHERE feature_id = 'f_master'
                      AND external_item_id = 'shared'
                    """
                )
            )
        ).one()
    assert survivor == (
        "f_master",
        True,
        expected_place,
        "rejected",
        "primary_stop",
        "blocked",
        "latest-operator",
    )


async def test_merge_tombstone_wins_over_visible_duplicate(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET status = 'archived',
                    archived_at = now(),
                    updated_by = 'archive-operator',
                    operator_updated_by = 'archive-operator',
                    operator_updated_at = now(),
                    updated_at = now()
                WHERE feature_id = 'f_loser'
                  AND external_item_id = 'shared'
                """
            )
        )
        await merge_from_review(session, seeded, merged_by="merge-operator")

    async with AsyncSession(migrated_engine) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT feature_id, status, archived_at IS NOT NULL
                    FROM feature.curation_items
                    WHERE external_item_id = 'shared'
                    """
                )
            )
        ).all()
    assert rows == [("f_master", "archived", True)]


async def test_merge_locks_curation_collection_before_items(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    merge_task: asyncio.Task[None] | None = None

    async def run_merge() -> None:
        async with AsyncSession(migrated_engine) as contender, contender.begin():
            await contender.execute(
                text("SET LOCAL application_name = 'merge-lock-order-contender'")
            )
            await apply_feature_merge(
                contender,
                master_id="f_master",
                loser_id="f_loser",
                review_id=seeded,
                merged_by="lock-test",
            )

    async with AsyncSession(migrated_engine) as holder, holder.begin():
        collection_id = str(
            (
                await holder.execute(
                    text(
                        "SELECT collection_id::text "
                        "FROM feature.curation_items "
                        "WHERE feature_id = 'f_master' "
                        "AND external_item_id = 'shared'"
                    )
                )
            ).scalar_one()
        )
        await holder.execute(
            text(
                "SELECT collection_id "
                "FROM feature.curation_collections "
                "WHERE collection_id = CAST(:collection_id AS uuid) "
                "FOR UPDATE"
            ),
            {"collection_id": collection_id},
        )
        merge_task = asyncio.create_task(run_merge())
        for _ in range(50):
            await holder.execute(text("SELECT pg_stat_clear_snapshot()"))
            waiting = (
                await holder.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_stat_activity "
                        "WHERE application_name = 'merge-lock-order-contender' "
                        "AND wait_event_type = 'Lock'"
                        ")"
                    )
                )
            ).scalar_one()
            if waiting:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("merge가 collection parent lock에서 대기하지 않았습니다.")

        # parent-first면 contender는 아직 item을 잡지 않았다. 기존 item-first 구현은
        # 여기서 LockNotAvailable이 발생해 역순 잠금을 재현한다.
        await holder.execute(
            text(
                "SELECT curation_item_id "
                "FROM feature.curation_items "
                "WHERE feature_id = 'f_master' "
                "AND external_item_id = 'shared' "
                "FOR UPDATE NOWAIT"
            )
        )

    assert merge_task is not None
    await asyncio.wait_for(merge_task, timeout=5)


async def test_merge_from_review_unknown_key_raises(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        with pytest.raises(MergeNotFoundError, match="review_id 없음"):
            await merge_from_review(session, "00000000-0000-0000-0000-000000000000")


async def test_merge_from_review_already_merged_raises(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    review_id = seeded
    async with AsyncSession(migrated_engine) as session, session.begin():
        await merge_from_review(session, review_id)
    # 두 번째 시도 — 이미 merged.
    async with AsyncSession(migrated_engine) as session, session.begin():
        with pytest.raises(MergeConflictError, match="이미 검토"):
            await merge_from_review(session, review_id)


async def test_merge_from_review_locks_review_row(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    review_id = seeded
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
                await _merge_from_review_with_short_lock_timeout(contender, review_id)


async def test_apply_feature_merge_distinct_guard(
    seeded: str, migrated_engine: AsyncEngine
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        with pytest.raises(MergeConflictError, match="master와 loser가 같음"):
            await apply_feature_merge(session, master_id="f_master", loser_id="f_master")


async def test_merge_history_count_after_merge(seeded: str, migrated_engine: AsyncEngine) -> None:
    review_id = seeded
    async with AsyncSession(migrated_engine) as session, session.begin():
        await merge_from_review(session, review_id)
    async with AsyncSession(migrated_engine) as session:
        count = (
            await session.execute(
                select(func.count()).select_from(text("ops.feature_merge_history"))
            )
        ).scalar_one()
    assert count == 1
