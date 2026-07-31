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
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import curated_repo
from kortravelmap.infra.curation_repo import (
    ResolvedCurationImportRow,
    add_curation_item,
    import_curation_rows,
    update_curation_item,
)
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
                    collection_id, feature_id, external_item_id,
                    external_component_id, place_name, status
                )
                SELECT
                    collection_id, 'f_master', 'shared', 'component-01',
                    '마스터 장소', 'included'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, 'f_loser', 'shared', 'component-02',
                    '병합 대상 장소', 'included'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, 'f_loser', 'loser-only', 'primary',
                    '병합 대상 장소', 'included'
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
                    theme_id, feature_id, source_id, source_record_key, curation_status,
                    selection_origin, display_title, display_summary
                )
                SELECT
                    themes.theme_id, 'f_master', source.source_id, 'SR1', 'curated',
                    'admin', 'legacy 충돌 master', '병합 전 master'
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'legacy-merge-conflict'
                UNION ALL
                SELECT
                    themes.theme_id, 'f_loser', source.source_id, 'SR1', 'curated',
                    'admin', 'legacy 충돌 loser', '병합 전 loser'
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'legacy-merge-conflict'
                UNION ALL
                SELECT
                    themes.theme_id, 'f_loser', source.source_id, 'SR2', 'curated',
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


async def _purge_curation_test_provenance(
    session: AsyncSession,
    *,
    theme_slugs: tuple[str, ...],
) -> None:
    """불변 provenance를 쓰는 테스트 fixture만 leaf-first로 완전 정리한다."""

    item_ids = [
        str(row[0])
        for row in (
            await session.execute(
                text(
                    """
                    SELECT item.curation_item_id::text
                    FROM feature.curation_items AS item
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    JOIN feature.curated_themes AS theme
                      ON theme.theme_id = collection.theme_id
                    WHERE theme.theme_slug = ANY(CAST(:theme_slugs AS text[]))
                    """
                ),
                {"theme_slugs": list(theme_slugs)},
            )
        ).all()
    ]
    if not item_ids:
        return
    await session.execute(
        text(
            """
            UPDATE feature.curation_items
            SET current_import_row_id = NULL,
                accepted_link_decision_id = NULL
            WHERE curation_item_id = ANY(CAST(:item_ids AS uuid[]))
            """
        ),
        {"item_ids": item_ids},
    )
    while True:
        deleted = (
            await session.execute(
                text(
                    """
                    DELETE FROM feature.curation_link_decisions AS decision
                    WHERE decision.curation_item_id =
                          ANY(CAST(:item_ids AS uuid[]))
                      AND NOT EXISTS (
                          SELECT 1
                          FROM feature.curation_link_decisions AS child
                          WHERE child.supersedes_decision_id =
                                decision.decision_id
                      )
                    RETURNING decision.decision_id
                    """
                ),
                {"item_ids": item_ids},
            )
        ).all()
        if not deleted:
            break
    await session.execute(
        text(
            """
            DELETE FROM feature.curation_import_rows
            WHERE curation_item_id = ANY(CAST(:item_ids AS uuid[]))
            """
        ),
        {"item_ids": item_ids},
    )
    await session.execute(
        text(
            """
            DELETE FROM feature.curation_import_batches AS batch
            WHERE NOT EXISTS (
                SELECT 1
                FROM feature.curation_import_rows AS import_row
                WHERE import_row.import_batch_id = batch.import_batch_id
            )
            """
        )
    )


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


async def _reinsert_loser_only_legacy(session: AsyncSession) -> tuple[str, str]:
    deleted = (
        await session.execute(
            text(
                """
                DELETE FROM feature.curated_features
                WHERE display_title = 'legacy 단독 loser'
                RETURNING
                    theme_id::text,
                    source_id::text,
                    source_record_key,
                    curation_status,
                    selection_origin,
                    display_title,
                    display_summary
                """
            )
        )
    ).one()
    canonical_item_id = str(
        (
            await session.execute(
                text(
                    """
                    SELECT item.curation_item_id::text
                    FROM feature.curation_items AS item
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE collection.theme_id = CAST(:theme_id AS uuid)
                      AND item.feature_id = 'f_loser'
                      AND item.external_item_id = 'SR2'
                    """
                ),
                {"theme_id": deleted.theme_id},
            )
        ).scalar_one()
    )
    reinserted_legacy_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id,
                        feature_id,
                        source_id,
                        source_record_key,
                        curation_status,
                        selection_origin,
                        display_title,
                        display_summary
                    ) VALUES (
                        CAST(:theme_id AS uuid),
                        'f_loser',
                        CAST(:source_id AS uuid),
                        :source_record_key,
                        :curation_status,
                        :selection_origin,
                        :display_title,
                        :display_summary
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": deleted.theme_id,
                    "source_id": deleted.source_id,
                    "source_record_key": deleted.source_record_key,
                    "curation_status": deleted.curation_status,
                    "selection_origin": deleted.selection_origin,
                    "display_title": deleted.display_title,
                    "display_summary": deleted.display_summary,
                },
            )
        ).scalar_one()
    )
    assert reinserted_legacy_id != canonical_item_id
    mapped_projection_id = (
        await session.execute(
            text(
                """
                SELECT legacy_projection_id::text
                FROM feature.curation_items
                WHERE curation_item_id = CAST(:canonical_item_id AS uuid)
                """
            ),
            {"canonical_item_id": canonical_item_id},
        )
    ).scalar_one()
    assert mapped_projection_id == reinserted_legacy_id
    return canonical_item_id, reinserted_legacy_id


async def _wait_for_application_lock(
    observer: AsyncSession,
    *,
    application_name: str,
) -> None:
    for _ in range(50):
        await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
        waiting = (
            await observer.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_stat_activity "
                    "WHERE application_name = :application_name "
                    "AND wait_event_type = 'Lock'"
                    ")"
                ),
                {"application_name": application_name},
            )
        ).scalar_one()
        if waiting:
            return
        await asyncio.sleep(0.02)
    pytest.fail(f"{application_name} did not wait on a lock")


async def _merge_from_review_with_short_lock_timeout(session: AsyncSession, review_id: str) -> None:
    await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
    await merge_from_review(session, review_id)


@pytest.fixture
async def seeded(pg_container: object, migrated_engine: AsyncEngine) -> object:
    """병합 대상 1쌍 적재 + teardown TRUNCATE. 반환: review_id."""
    review_id = await _seed_pair(migrated_engine)
    yield review_id
    async with AsyncSession(migrated_engine) as session, session.begin():
        await _purge_curation_test_provenance(
            session,
            theme_slugs=(
                "merge-test",
                "legacy-merge-conflict",
                "legacy-merge-loser-only",
                "legacy-merge-conflict-renamed",
                "legacy-merge-loser-only-renamed",
            ),
        )
        for statement in (
            "DELETE FROM ops.feature_merge_history "
            "WHERE master_feature_id IN ('f_master', 'f_loser') "
            "OR loser_feature_id IN ('f_master', 'f_loser')",
            "DELETE FROM ops.dedup_review_queue "
            "WHERE feature_id_a IN ('f_master', 'f_loser') "
            "OR feature_id_b IN ('f_master', 'f_loser')",
            "DELETE FROM feature.curated_features "
            "WHERE feature_id IN ('f_master', 'f_loser', 'f_theme_reuse')",
            "DELETE FROM feature.curation_collections "
            "WHERE theme_id IN ("
            "SELECT theme_id FROM feature.curated_themes "
            "WHERE theme_slug IN ("
            "'merge-test','legacy-merge-conflict','legacy-merge-loser-only'"
            ",'legacy-merge-conflict-renamed'"
            ",'legacy-merge-loser-only-renamed'"
            "))",
            "DELETE FROM feature.curated_themes "
            "WHERE theme_slug IN ("
            "'merge-test','legacy-merge-conflict','legacy-merge-loser-only'"
            ",'legacy-merge-conflict-renamed'"
            ",'legacy-merge-loser-only-renamed'"
            ")",
            "DELETE FROM feature.curated_sources "
            "WHERE provider = 'merge-test-provider' "
            "AND dataset_key = 'legacy-curation'",
            "DELETE FROM provider_sync.source_links "
            "WHERE feature_id IN ('f_master', 'f_loser')",
            "UPDATE provider_sync.source_entities "
            "SET current_source_record_key = NULL "
            "WHERE source_entity_key IN ('SE1', 'SE2')",
            "DELETE FROM provider_sync.source_records "
            "WHERE source_record_key IN ('SR1', 'SR2')",
            "DELETE FROM provider_sync.source_entities "
            "WHERE source_entity_key IN ('SE1', 'SE2')",
            "DELETE FROM feature.features "
            "WHERE feature_id IN ('f_master', 'f_loser', 'f_theme_reuse')",
        ):
            await session.execute(text(statement))


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
        await session.execute(
            text(
                """
                UPDATE feature.curated_features
                SET curation_status = 'candidate',
                    metadata = '{}'::jsonb,
                    updated_at = clock_timestamp()
                WHERE display_title = 'legacy 충돌 loser'
                """
            )
        )
        detached_marker_preserved = (
            await session.execute(
                text(
                    """
                    SELECT metadata @> '{"merge_projection_detached": true}'::jsonb
                    FROM feature.curated_features
                    WHERE display_title = 'legacy 충돌 loser'
                    """
                )
            )
        ).scalar_one()
        await session.execute(
            text(
                "DELETE FROM feature.curated_features "
                "WHERE display_title = 'legacy 충돌 loser'"
            )
        )
    assert legacy_rows == [
        ("legacy 단독 loser", "f_master", "curated", False),
        ("legacy 충돌 loser", "f_master", "archived", True),
        ("legacy 충돌 master", "f_master", "curated", False),
    ]
    assert detached_marker_preserved is True
    async with AsyncSession(migrated_engine) as session:
        active_legacy_items = (
            await session.execute(
                text(
                    """
                    SELECT c.title, i.feature_id, i.source_present
                    FROM feature.curation_items AS i
                    JOIN feature.curation_collections AS c
                      ON c.collection_id = i.collection_id
                    WHERE c.title IN (
                        'legacy 단독 loser',
                        'legacy 충돌 loser',
                        'legacy 충돌 master'
                    )
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


async def test_merge_moves_legacy_projection_into_canonical_only_master_identity(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(
            text(
                """
                UPDATE feature.curation_items AS item
                SET source_updated_at = now() - interval '2 hours'
                FROM feature.curated_features AS legacy
                WHERE legacy.curated_feature_id = item.curation_item_id
                  AND legacy.display_title = 'legacy 단독 loser'
                """
            )
        )
        (
            canonical_item_id,
            canonical_source_updated_at,
            original_collection_id,
        ) = (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curation_items (
                        collection_id, feature_id, source_record_key,
                        external_item_id, external_component_id,
                        place_name, status,
                        item_summary, metadata, source_updated_at
                    )
                    SELECT
                        item.collection_id,
                        'f_master',
                        item.source_record_key,
                        item.external_item_id,
                        'canonical-master',
                        'canonical-only master',
                        'included',
                        'canonical winner summary',
                        '{"winner": "master"}'::jsonb,
                        now() + interval '1 hour'
                    FROM feature.curation_items AS item
                    JOIN feature.curated_features AS legacy
                      ON legacy.curated_feature_id = item.curation_item_id
                    WHERE legacy.display_title = 'legacy 단독 loser'
                    RETURNING
                        curation_item_id::text,
                        source_updated_at,
                        collection_id::text
                    """
                )
            )
        ).one()
        canonical_item_id = str(canonical_item_id)
        await session.execute(
            text(
                """
                UPDATE feature.curated_themes
                SET theme_slug = 'legacy-merge-loser-only-renamed',
                    updated_at = clock_timestamp()
                WHERE theme_slug = 'legacy-merge-loser-only'
                """
            )
        )
        await session.execute(
            text(
                """
                UPDATE feature.curated_features
                SET display_summary = 'rename 뒤 provider 갱신',
                    updated_at = clock_timestamp()
                WHERE display_title = 'legacy 단독 loser'
                """
            )
        )
        mapped_collection_id = str(
            (
                await session.execute(
                    text(
                        """
                        SELECT item.collection_id::text
                        FROM feature.curation_items AS item
                        JOIN feature.curated_features AS legacy
                          ON legacy.curated_feature_id =
                             item.legacy_projection_id
                        WHERE legacy.display_title = 'legacy 단독 loser'
                        """
                    )
                )
            ).scalar_one()
        )
        assert mapped_collection_id == original_collection_id

    async with AsyncSession(migrated_engine) as session, session.begin():
        await merge_from_review(session, seeded, merged_by="op-1", reason="dup")

    async with AsyncSession(migrated_engine) as session:
        legacy = (
            await session.execute(
                text(
                    """
                    SELECT
                        feature_id,
                        archived_at IS NOT NULL,
                        metadata @> '{"merge_projection_detached": true}'::jsonb
                    FROM feature.curated_features
                    WHERE display_title = 'legacy 단독 loser'
                    """
                )
            )
        ).one()
        canonical = (
            await session.execute(
                text(
                    """
                    SELECT
                        feature_id,
                        archived_at IS NULL,
                        source_present,
                        place_name,
                        item_summary,
                        metadata,
                        source_updated_at
                    FROM feature.curation_items
                    WHERE curation_item_id = CAST(:canonical_item_id AS uuid)
                    """
                ),
                {"canonical_item_id": canonical_item_id},
            )
        ).one()

    assert legacy == ("f_master", True, True)
    assert canonical == (
        "f_master",
        True,
        True,
        "canonical-only master",
        "canonical winner summary",
        {"winner": "master"},
        canonical_source_updated_at,
    )


async def test_theme_slug_reuse_cannot_take_legacy_collection(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        original = (
            await session.execute(
                text(
                    """
                    SELECT
                        legacy.theme_id::text,
                        legacy.source_id::text,
                        item.collection_id::text,
                        collection.collection_key
                    FROM feature.curated_features AS legacy
                    JOIN feature.curation_items AS item
                      ON item.legacy_projection_id =
                         legacy.curated_feature_id
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE legacy.display_title = 'legacy 단독 loser'
                    """
                )
            )
        ).one()
        await session.execute(
            text(
                """
                UPDATE feature.curated_themes
                SET theme_slug = 'legacy-merge-loser-only-renamed',
                    updated_at = clock_timestamp()
                WHERE theme_id = CAST(:theme_id AS uuid)
                """
            ),
            {"theme_id": original.theme_id},
        )
        await session.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, detail, status
                ) VALUES (
                    'f_theme_reuse', 'place', 'slug 재사용 장소',
                    '01070100', '{}'::jsonb, 'active'
                )
                """
            )
        )
        reused_theme_id = str(
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO feature.curated_themes (
                            theme_slug, theme_name, theme_group, visibility
                        ) VALUES (
                            'legacy-merge-loser-only',
                            'slug 재사용 theme',
                            'test',
                            'public'
                        )
                        RETURNING theme_id::text
                        """
                    )
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id,
                    curation_status, selection_origin, display_title
                ) VALUES (
                    CAST(:theme_id AS uuid),
                    'f_theme_reuse',
                    CAST(:source_id AS uuid),
                    'curated',
                    'source_rule',
                    'legacy 단독 loser'
                )
                """
            ),
            {
                "theme_id": reused_theme_id,
                "source_id": original.source_id,
            },
        )

    async with AsyncSession(migrated_engine) as session:
        original_owner = (
            await session.execute(
                text(
                    """
                    SELECT theme_id::text, source_id::text, collection_key
                    FROM feature.curation_collections
                    WHERE collection_id = CAST(:collection_id AS uuid)
                    """
                ),
                {"collection_id": original.collection_id},
            )
        ).one()
        reused = (
            await session.execute(
                text(
                    """
                    SELECT
                        collection.collection_id::text,
                        collection.theme_id::text,
                        collection.source_id::text,
                        collection.collection_key
                    FROM feature.curated_features AS legacy
                    JOIN feature.curation_items AS item
                      ON item.legacy_projection_id =
                         legacy.curated_feature_id
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE legacy.feature_id = 'f_theme_reuse'
                    """
                )
            )
        ).one()

    assert original_owner == (
        original.theme_id,
        original.source_id,
        original.collection_key,
    )
    assert reused.collection_id != original.collection_id
    assert reused.theme_id == reused_theme_id
    assert reused.source_id == original.source_id
    assert reused.collection_key != original.collection_key


async def test_merge_keeps_reinserted_nonconflicting_legacy_projection_active(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        canonical_item_id, reinserted_legacy_id = await _reinsert_loser_only_legacy(
            session
        )

    async with AsyncSession(migrated_engine) as session, session.begin():
        await merge_from_review(session, seeded, merged_by="op-1", reason="dup")

    async with AsyncSession(migrated_engine) as session:
        legacy = (
            await session.execute(
                text(
                    """
                    SELECT
                        feature_id,
                        curation_status,
                        archived_at IS NULL,
                        NOT metadata @>
                            '{"merge_projection_detached": true}'::jsonb
                    FROM feature.curated_features
                    WHERE curated_feature_id =
                          CAST(:reinserted_legacy_id AS uuid)
                    """
                ),
                {"reinserted_legacy_id": reinserted_legacy_id},
            )
        ).one()
        canonical = (
            await session.execute(
                text(
                    """
                    SELECT feature_id, source_present, archived_at IS NULL
                    FROM feature.curation_items
                    WHERE curation_item_id = CAST(:canonical_item_id AS uuid)
                    """
                ),
                {"canonical_item_id": canonical_item_id},
            )
        ).one()

    assert legacy == ("f_master", "curated", True, True)
    assert canonical == ("f_master", True, True)


async def test_merge_preserves_winner_for_reinserted_legacy_canonical_conflict(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        loser_item_id, reinserted_legacy_id = await _reinsert_loser_only_legacy(
            session
        )
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET source_updated_at = now() - interval '2 hours'
                WHERE curation_item_id = CAST(:loser_item_id AS uuid)
                """
            ),
            {"loser_item_id": loser_item_id},
        )
        master_item_id, master_source_updated_at = (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curation_items (
                        collection_id, feature_id, source_record_key,
                        external_item_id, external_component_id,
                        place_name, status,
                        item_summary, metadata, source_updated_at
                    )
                    SELECT
                        collection_id,
                        'f_master',
                        source_record_key,
                        external_item_id,
                        'canonical-master',
                        'reinsert canonical winner',
                        'included',
                        'reinsert winner summary',
                        '{"winner": "reinsert-master"}'::jsonb,
                        now() - interval '1 hour'
                    FROM feature.curation_items
                    WHERE curation_item_id = CAST(:loser_item_id AS uuid)
                    RETURNING curation_item_id::text, source_updated_at
                    """
                ),
                {"loser_item_id": loser_item_id},
            )
        ).one()

    async with AsyncSession(migrated_engine) as session, session.begin():
        await merge_from_review(session, seeded, merged_by="op-1", reason="dup")

    async with AsyncSession(migrated_engine) as session:
        legacy = (
            await session.execute(
                text(
                    """
                    SELECT
                        feature_id,
                        archived_at IS NOT NULL,
                        metadata @> '{"merge_projection_detached": true}'::jsonb
                    FROM feature.curated_features
                    WHERE curated_feature_id =
                          CAST(:reinserted_legacy_id AS uuid)
                    """
                ),
                {"reinserted_legacy_id": reinserted_legacy_id},
            )
        ).one()
        canonical = (
            await session.execute(
                text(
                    """
                    SELECT
                        feature_id,
                        place_name,
                        item_summary,
                        metadata,
                        source_updated_at,
                        legacy_projection_id
                    FROM feature.curation_items
                    WHERE curation_item_id = CAST(:master_item_id AS uuid)
                    """
                ),
                {"master_item_id": master_item_id},
            )
        ).one()

    assert legacy == ("f_master", True, True)
    assert canonical == (
        "f_master",
        "reinsert canonical winner",
        "reinsert winner summary",
        {"winner": "reinsert-master"},
        master_source_updated_at,
        None,
    )


async def test_reserved_detach_transition_rejects_unrelated_field_mutation(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        loser_legacy_id = str(
            (
                await session.execute(
                    text(
                        """
                        SELECT curated_feature_id::text
                        FROM feature.curated_features
                        WHERE display_title = 'legacy 충돌 loser'
                        """
                    )
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                DELETE FROM feature.curation_items
                WHERE curation_item_id = CAST(:legacy_id AS uuid)
                """
            ),
            {"legacy_id": loser_legacy_id},
        )

    with pytest.raises(DBAPIError, match="reserved"):
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(
                text(
                    """
                    UPDATE feature.curated_features
                    SET feature_id = 'f_master',
                        curation_status = 'archived',
                        display_summary = 'unauthorized mutation',
                        metadata = metadata || jsonb_build_object(
                            'merge_projection_detached',
                            true
                        ),
                        archived_at = now(),
                        updated_at = clock_timestamp()
                    WHERE curated_feature_id = CAST(:legacy_id AS uuid)
                    """
                ),
                {"legacy_id": loser_legacy_id},
            )


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


@pytest.mark.parametrize(
    ("loser_status", "expected_archived"),
    [("rejected", False), ("archived", True)],
)
async def test_merge_syncs_reconciled_operator_state_to_master_legacy_projection(
    seeded: str,
    migrated_engine: AsyncEngine,
    loser_status: str,
    expected_archived: bool,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(
            text(
                """
                WITH legacy_identity AS (
                    SELECT theme_id, source_id
                    FROM feature.curated_features
                    WHERE display_title = 'legacy 충돌 master'
                ), manual_collection AS (
                    INSERT INTO feature.curation_collections (
                        collection_key, theme_id, source_id, title
                    )
                    SELECT
                        'manual-cross-collection',
                        theme_id,
                        source_id,
                        '동일 출처 수동 컬렉션'
                    FROM legacy_identity
                    RETURNING collection_id
                )
                INSERT INTO feature.curation_items (
                    collection_id, feature_id, source_record_key,
                    external_item_id, place_name, status,
                    curation_relation, reuse_policy,
                    operator_updated_by, operator_updated_at
                )
                SELECT
                    collection_id, 'f_master', 'SR1',
                    'SR1', '수동 컬렉션 장소', 'included',
                    'food_stop', 'allowed',
                    'manual-collection-operator', now() + interval '1 day'
                FROM manual_collection
                """
            )
        )
        await session.execute(
            text(
                """
                UPDATE feature.curated_features
                SET display_title = 'legacy 충돌 master',
                    updated_at = clock_timestamp()
                WHERE display_title = 'legacy 충돌 loser'
                """
            )
        )
        projection_ids = (
            await session.execute(
                text(
                    """
                    SELECT
                        max(curated_feature_id::text)
                            FILTER (WHERE feature_id = 'f_master') AS master_id,
                        max(curated_feature_id::text)
                            FILTER (WHERE feature_id = 'f_loser') AS loser_id
                    FROM feature.curated_features
                    WHERE display_title = 'legacy 충돌 master'
                    """
                )
            )
        ).one()
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET status = :loser_status,
                    curation_relation = 'primary_stop',
                    reuse_policy = 'blocked',
                    operator_updated_by = 'loser-operator',
                    operator_updated_at = now(),
                    archived_at = CASE
                        WHEN :loser_status = 'archived' THEN now()
                        ELSE NULL
                    END,
                    updated_at = now()
                WHERE curation_item_id = CAST(:loser_id AS uuid)
                """
            ),
            {
                "loser_id": projection_ids.loser_id,
                "loser_status": loser_status,
            },
        )
        await session.execute(
            text(
                """
                UPDATE feature.curated_themes
                SET theme_slug = 'legacy-merge-conflict-renamed',
                    updated_at = clock_timestamp()
                WHERE theme_slug = 'legacy-merge-conflict'
                """
            )
        )
        await merge_from_review(session, seeded, merged_by="merge-operator")

    async with AsyncSession(migrated_engine) as session:
        master_projection = (
            await session.execute(
                text(
                    """
                    SELECT curation_status, archived_at IS NOT NULL,
                           curation_relation, reuse_policy,
                           operator_updated_by
                    FROM feature.curated_features
                    WHERE curated_feature_id = CAST(:master_id AS uuid)
                    """
                ),
                {"master_id": projection_ids.master_id},
            )
        ).one()
        public_count = (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM feature.curated_features
                    WHERE theme_id = (
                            SELECT theme_id
                            FROM feature.curated_features
                            WHERE curated_feature_id = CAST(:master_id AS uuid)
                        )
                      AND feature_id = 'f_master'
                      AND curation_status = 'curated'
                      AND archived_at IS NULL
                    """
                ),
                {"master_id": projection_ids.master_id},
            )
        ).scalar_one()
        manual_projection = (
            await session.execute(
                text(
                    """
                    SELECT item.status, item.curation_relation, item.reuse_policy,
                           item.operator_updated_by
                    FROM feature.curation_items AS item
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE collection.collection_key = 'manual-cross-collection'
                    """
                )
            )
        ).one()
    assert master_projection == (
        loser_status,
        expected_archived,
        "primary_stop",
        "blocked",
        "loser-operator",
    )
    assert public_count == 0
    assert manual_projection == (
        "included",
        "food_stop",
        "allowed",
        "manual-collection-operator",
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
                SET status = 'included',
                    curation_relation = 'food_stop',
                    reuse_policy = 'allowed',
                    updated_by = 'newer-visible-operator',
                    operator_updated_by = 'newer-visible-operator',
                    operator_updated_at = now() + interval '2 hours',
                    updated_at = now()
                WHERE feature_id = 'f_master'
                  AND external_item_id = 'shared'
                """
            )
        )
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET status = 'archived',
                    curation_relation = 'primary_stop',
                    reuse_policy = 'blocked',
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
                    SELECT feature_id, status, archived_at IS NOT NULL,
                           curation_relation, reuse_policy,
                           operator_updated_by
                        FROM feature.curation_items
                        WHERE external_item_id = 'shared'
                        ORDER BY feature_id NULLS LAST
                    """
                )
            )
        ).all()
    assert rows == [
        (
            "f_master",
            "archived",
            True,
            "primary_stop",
            "blocked",
            "archive-operator",
        ),
        (
            None,
            "archived",
            True,
            "primary_stop",
            "blocked",
            "archive-operator",
        ),
    ]


async def test_legacy_and_canonical_writers_share_lock_order(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as lookup:
        legacy_id, collection_id, item_id = (
            await lookup.execute(
                text(
                    """
                    SELECT legacy.curated_feature_id::text,
                           item.collection_id::text,
                           item.curation_item_id::text
                    FROM feature.curated_features AS legacy
                    JOIN feature.curation_items AS item
                      ON item.curation_item_id = legacy.curated_feature_id
                    WHERE legacy.display_title = 'legacy 충돌 master'
                    """
                )
            )
        ).one()

    async def update_canonical() -> None:
        async with AsyncSession(migrated_engine) as contender, contender.begin():
            await contender.execute(
                text("SET LOCAL application_name = 'canonical-legacy-lock-contender'")
            )
            updated = await update_curation_item(
                contender,
                collection_id=collection_id,
                curation_item_id=item_id,
                updates={"curation_relation": "food_stop"},
                actor="canonical-lock-test",
            )
            assert updated is not None

    task: asyncio.Task[None] | None = None
    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text(
                "SELECT curated_feature_id "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:legacy_id AS uuid) "
                "FOR UPDATE"
            ),
            {"legacy_id": legacy_id},
        )
        task = asyncio.create_task(update_canonical())
        for _ in range(50):
            await holder.execute(text("SELECT pg_stat_clear_snapshot()"))
            waiting = (
                await holder.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_stat_activity
                            WHERE application_name =
                                'canonical-legacy-lock-contender'
                              AND wait_event_type = 'Lock'
                        )
                        """
                    )
                )
            ).scalar_one()
            if waiting:
                break
            await asyncio.sleep(0.02)
        assert waiting is True
        await holder.execute(
            text(
                """
                UPDATE feature.curated_features
                SET display_summary = 'legacy lock-order update',
                    updated_at = clock_timestamp()
                WHERE curated_feature_id = CAST(:legacy_id AS uuid)
                """
            ),
            {"legacy_id": legacy_id},
        )

    assert task is not None
    await asyncio.wait_for(task, timeout=5)


async def _seed_import_race_collection(
    engine: AsyncEngine,
) -> tuple[ResolvedCurationImportRow, str, str, str]:
    suffix = uuid4().hex
    collection_key = f"merge-import-race:{suffix}"
    theme_slug = f"merge-import-race-{suffix}"
    provider = f"merge-import-race-{suffix}"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                WITH theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group
                    ) VALUES (:theme_slug, 'merge/import race', 'test')
                    RETURNING theme_id
                ), source AS (
                    INSERT INTO feature.curated_sources (
                        provider, dataset_key, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        :provider, 'race', 'merge/import race',
                        'manual', 'unknown', 'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id
                )
                INSERT INTO feature.curation_collections (
                    collection_key, theme_id, source_id, title, edition_key
                )
                SELECT :collection_key, theme_id, source_id, 'race', '2026'
                FROM theme CROSS JOIN source
                """
            ),
            {
                "theme_slug": theme_slug,
                "provider": provider,
                "collection_key": collection_key,
            },
        )
    row = ResolvedCurationImportRow(
        row_number=2,
        collection_key=collection_key,
        theme_slug=theme_slug,
        theme_name="merge/import race",
        theme_group="test",
        title="race",
        edition_key="2026",
        provider=provider,
        dataset_key="race",
        source_name="merge/import race",
        source_url=None,
        source_item_key="loser-item",
        feature_id="f_loser",
        place_name="병합 loser",
        address_hint=None,
        sort_order=1,
        item_title=None,
        item_summary=None,
        metadata={},
    )
    return row, collection_key, theme_slug, provider


async def test_merge_first_serializes_import_against_feature_lifecycle(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    row, collection_key, theme_slug, provider = await _seed_import_race_collection(
        migrated_engine
    )

    async def run_import() -> None:
        async with AsyncSession(migrated_engine) as importer, importer.begin():
            await importer.execute(
                text("SET LOCAL application_name = 'merge-first-import-contender'")
            )
            await import_curation_rows(importer, rows=(row,), actor="import-race")

    async def run_merge() -> None:
        async with AsyncSession(migrated_engine) as merger, merger.begin():
            await merger.execute(
                text("SET LOCAL application_name = 'merge-first-merge-contender'")
            )
            await merge_from_review(
                merger,
                seeded,
                merged_by="merge-import-race",
            )

    import_task: asyncio.Task[None] | None = None
    merge_task: asyncio.Task[None] | None = None
    try:
        async with AsyncSession(migrated_engine) as holder, holder.begin():
            await holder.execute(
                text(
                    "SELECT collection.collection_id "
                    "FROM feature.curation_collections AS collection "
                    "JOIN feature.curation_items AS item "
                    "ON item.collection_id = collection.collection_id "
                    "WHERE item.feature_id = 'f_master' "
                    "AND item.external_item_id = 'shared' "
                    "FOR UPDATE"
                )
            )
            merge_task = asyncio.create_task(run_merge())
            for _ in range(50):
                await holder.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = (
                    await holder.execute(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_stat_activity
                                WHERE application_name =
                                    'merge-first-merge-contender'
                                  AND wait_event_type = 'Lock'
                            )
                            """
                        )
                    )
                ).scalar_one()
                if waiting:
                    break
                await asyncio.sleep(0.02)
            assert waiting is True
            import_task = asyncio.create_task(run_import())
            for _ in range(50):
                await holder.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = (
                    await holder.execute(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_stat_activity
                                WHERE application_name =
                                    'merge-first-import-contender'
                                  AND wait_event_type = 'Lock'
                            )
                            """
                        )
                    )
                ).scalar_one()
                if waiting:
                    break
                await asyncio.sleep(0.02)
            assert waiting is True

        assert merge_task is not None
        await asyncio.wait_for(merge_task, timeout=5)
        assert import_task is not None
        with pytest.raises(ValueError, match="lifecycle"):
            await asyncio.wait_for(import_task, timeout=5)
    finally:
        for task in (import_task, merge_task):
            if task is not None and not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await _purge_curation_test_provenance(
                cleanup,
                theme_slugs=(theme_slug,),
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curation_collections "
                    "WHERE collection_key = :collection_key"
                ),
                {"collection_key": collection_key},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curated_themes "
                    "WHERE theme_slug = :theme_slug"
                ),
                {"theme_slug": theme_slug},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curated_sources "
                    "WHERE provider = :provider AND dataset_key = 'race'"
                ),
                {"provider": provider},
            )


async def test_import_first_merge_moves_newly_committed_membership(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    row, collection_key, theme_slug, provider = await _seed_import_race_collection(
        migrated_engine
    )

    async def run_import() -> None:
        async with AsyncSession(migrated_engine) as importer, importer.begin():
            await importer.execute(
                text("SET LOCAL application_name = 'import-first-import-contender'")
            )
            await import_curation_rows(importer, rows=(row,), actor="import-race")

    async def run_merge() -> None:
        async with AsyncSession(migrated_engine) as merger, merger.begin():
            await merger.execute(
                text("SET LOCAL application_name = 'import-first-merge-contender'")
            )
            await merge_from_review(
                merger,
                seeded,
                merged_by="merge-import-race",
            )

    import_task: asyncio.Task[None] | None = None
    merge_task: asyncio.Task[None] | None = None
    try:
        async with AsyncSession(migrated_engine) as holder, holder.begin():
            await holder.execute(
                text(
                    "SELECT collection_id "
                    "FROM feature.curation_collections "
                    "WHERE collection_key = :collection_key "
                    "FOR UPDATE"
                ),
                {"collection_key": collection_key},
            )
            import_task = asyncio.create_task(run_import())
            for _ in range(50):
                await holder.execute(text("SELECT pg_stat_clear_snapshot()"))
                import_waiting = (
                    await holder.execute(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_stat_activity
                                WHERE application_name =
                                    'import-first-import-contender'
                                  AND wait_event_type = 'Lock'
                            )
                            """
                        )
                    )
                ).scalar_one()
                if import_waiting:
                    break
                await asyncio.sleep(0.02)
            assert import_waiting is True

            merge_task = asyncio.create_task(run_merge())
            for _ in range(50):
                await holder.execute(text("SELECT pg_stat_clear_snapshot()"))
                merge_waiting = (
                    await holder.execute(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_stat_activity
                                WHERE application_name =
                                    'import-first-merge-contender'
                                  AND wait_event_type = 'Lock'
                            )
                            """
                        )
                    )
                ).scalar_one()
                if merge_waiting:
                    break
                await asyncio.sleep(0.02)
            assert merge_waiting is True

        assert import_task is not None
        await asyncio.wait_for(import_task, timeout=5)
        assert merge_task is not None
        await asyncio.wait_for(merge_task, timeout=5)
        async with AsyncSession(migrated_engine) as session:
            state = (
                await session.execute(
                    text(
                            """
                            SELECT
                                item.feature_id,
                                item.source_present,
                                decision.match_basis,
                                decision.resolver_version,
                                decision.actor,
                                decision.evidence->>'loser_feature_id'
                            FROM feature.curation_items AS item
                            JOIN feature.curation_collections AS collection
                              ON collection.collection_id = item.collection_id
                            JOIN feature.curation_link_decisions AS decision
                              ON decision.decision_id =
                                 item.accepted_link_decision_id
                            WHERE collection.collection_key = :collection_key
                              AND item.external_item_id = 'loser-item'
                        """
                    ),
                    {"collection_key": collection_key},
                )
            ).one()
            loser_count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM feature.curation_items "
                        "WHERE feature_id = 'f_loser'"
                    )
                )
            ).scalar_one()
        assert state == (
            "f_master",
            True,
            "forward_recovery",
            "feature-merge-v1",
            "merge-import-race",
            "f_loser",
        )
        assert loser_count == 0
    finally:
        for task in (import_task, merge_task):
            if task is not None and not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await _purge_curation_test_provenance(
                cleanup,
                theme_slugs=(theme_slug,),
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curation_collections "
                    "WHERE collection_key = :collection_key"
                ),
                {"collection_key": collection_key},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curated_themes "
                    "WHERE theme_slug = :theme_slug"
                ),
                {"theme_slug": theme_slug},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curated_sources "
                    "WHERE provider = :provider AND dataset_key = 'race'"
                ),
                {"provider": provider},
            )


@pytest.mark.parametrize("writer_kind", ["add", "feature_link", "legacy_create"])
async def test_merge_first_rechecks_all_membership_writer_feature_lifecycles(
    seeded: str,
    migrated_engine: AsyncEngine,
    writer_kind: str,
) -> None:
    suffix = uuid4().hex
    theme_slug = f"merge-writer-race-{suffix}"
    unresolved_item_id: str | None = None
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        collection_id = str(
            (
                await setup.execute(
                    text(
                        "SELECT collection_id::text "
                        "FROM feature.curation_collections "
                        "WHERE collection_key = 'merge-test:2026'"
                    )
                )
            ).scalar_one()
        )
        source_id = str(
            (
                await setup.execute(
                    text(
                        "SELECT source_id::text "
                        "FROM feature.curated_sources "
                        "WHERE provider = 'merge-test-provider' "
                        "AND dataset_key = 'legacy-curation'"
                    )
                )
            ).scalar_one()
        )
        theme_id = str(
            (
                await setup.execute(
                    text(
                        "INSERT INTO feature.curated_themes ("
                        "theme_slug, theme_name, theme_group"
                        ") VALUES (:theme_slug, 'merge writer race', 'test') "
                        "RETURNING theme_id::text"
                    ),
                    {"theme_slug": theme_slug},
                )
            ).scalar_one()
        )
        if writer_kind == "feature_link":
            unresolved, inserted = await add_curation_item(
                setup,
                collection_id=collection_id,
                feature_id=None,
                external_item_id=f"feature-link-{suffix}",
                place_name="미연결 merge race",
                actor="race-setup",
            )
            assert inserted is True
            unresolved_item_id = unresolved.curation_item_id

    async def run_merge() -> None:
        async with AsyncSession(migrated_engine) as merger, merger.begin():
            await merger.execute(
                text("SET LOCAL application_name = 'membership-writer-merge'")
            )
            await merge_from_review(
                merger,
                seeded,
                merged_by="membership-writer-race",
            )

    async def run_writer() -> None:
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            await writer.execute(
                text("SET LOCAL application_name = 'membership-writer-contender'")
            )
            if writer_kind == "add":
                await add_curation_item(
                    writer,
                    collection_id=collection_id,
                    feature_id="f_loser",
                    external_item_id=f"canonical-add-{suffix}",
                    actor="race-writer",
                )
            elif writer_kind == "feature_link":
                assert unresolved_item_id is not None
                await update_curation_item(
                    writer,
                    collection_id=collection_id,
                    curation_item_id=unresolved_item_id,
                    updates={"feature_id": "f_loser"},
                    actor="race-writer",
                )
            else:
                await curated_repo.create_curated_feature(
                    writer,
                    theme_id=theme_id,
                    feature_id="f_loser",
                    source_id=source_id,
                    actor="race-writer",
                )

    merge_task: asyncio.Task[None] | None = None
    writer_task: asyncio.Task[None] | None = None
    try:
        async with AsyncSession(migrated_engine) as holder, holder.begin():
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
            await _wait_for_application_lock(
                holder,
                application_name="membership-writer-merge",
            )
            writer_task = asyncio.create_task(run_writer())
            await _wait_for_application_lock(
                holder,
                application_name="membership-writer-contender",
            )
            blocked_by_merge = (
                await holder.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_stat_activity AS writer
                            JOIN pg_stat_activity AS merger
                              ON merger.pid = ANY(
                                  pg_blocking_pids(writer.pid)
                              )
                            WHERE writer.application_name =
                                  'membership-writer-contender'
                              AND merger.application_name =
                                  'membership-writer-merge'
                        )
                        """
                    )
                )
            ).scalar_one()
            assert blocked_by_merge is True

        assert merge_task is not None
        await asyncio.wait_for(merge_task, timeout=5)
        assert writer_task is not None
        with pytest.raises(ValueError, match="active Feature|Feature가 없습니다"):
            await asyncio.wait_for(writer_task, timeout=5)
    finally:
        for task in (writer_task, merge_task):
            if task is not None and not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await _purge_curation_test_provenance(
                cleanup,
                theme_slugs=(theme_slug,),
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curated_features "
                    "WHERE theme_id = CAST(:theme_id AS uuid)"
                ),
                {"theme_id": theme_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curation_collections "
                    "WHERE theme_id = CAST(:theme_id AS uuid)"
                ),
                {"theme_id": theme_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curated_themes "
                    "WHERE theme_id = CAST(:theme_id AS uuid)"
                ),
                {"theme_id": theme_id},
            )


async def test_membership_writer_first_is_seen_and_moved_by_merge(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    external_item_id = f"writer-first-{suffix}"
    merge_task: asyncio.Task[None] | None = None

    async def run_merge() -> None:
        async with AsyncSession(migrated_engine) as merger, merger.begin():
            await merger.execute(
                text("SET LOCAL application_name = 'writer-first-merge'")
            )
            await merge_from_review(
                merger,
                seeded,
                merged_by="writer-first-race",
            )

    async with AsyncSession(migrated_engine) as writer, writer.begin():
        collection_id = str(
            (
                await writer.execute(
                    text(
                        "SELECT collection_id::text "
                        "FROM feature.curation_collections "
                        "WHERE collection_key = 'merge-test:2026'"
                    )
                )
            ).scalar_one()
        )
        await add_curation_item(
            writer,
            collection_id=collection_id,
            feature_id="f_loser",
            external_item_id=external_item_id,
            actor="writer-first",
        )
        merge_task = asyncio.create_task(run_merge())
        await _wait_for_application_lock(
            writer,
            application_name="writer-first-merge",
        )

    assert merge_task is not None
    await asyncio.wait_for(merge_task, timeout=5)
    async with AsyncSession(migrated_engine) as session:
        state = (
            await session.execute(
                text(
                    "SELECT feature_id, source_present "
                    "FROM feature.curation_items "
                    "WHERE external_item_id = :external_item_id"
                ),
                {"external_item_id": external_item_id},
            )
        ).one()
    assert state == ("f_master", True)


async def test_rule_apply_rechecks_feature_after_waiting_for_merge(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    theme_slug = f"merge-rule-race-{suffix}"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        rule_id = str(
            (
                await setup.execute(
                    text(
                        """
                        WITH theme AS (
                            INSERT INTO feature.curated_themes (
                                theme_slug, theme_name, theme_group
                            ) VALUES (
                                :theme_slug, 'merge rule race', 'test'
                            )
                            RETURNING theme_id
                        ), source AS (
                            INSERT INTO feature.curated_sources (
                                provider, dataset_key, source_name,
                                source_kind, update_cycle,
                                provider_status, metadata
                            ) VALUES (
                                'python-visitkorea-api', 'd',
                                'merge rule race', 'openapi', 'unknown',
                                'implemented', '{}'::jsonb
                            )
                            RETURNING source_id
                        )
                        INSERT INTO feature.curated_source_rules (
                            theme_id, source_id, dataset_key, default_action,
                            enabled, priority
                        )
                        SELECT
                            theme_id, source_id, 'd', 'candidate', true, 1
                        FROM theme CROSS JOIN source
                        RETURNING rule_id::text
                        """
                    ),
                    {"theme_slug": theme_slug},
                )
            ).scalar_one()
        )
        collection_id = str(
            (
                await setup.execute(
                    text(
                        "SELECT collection_id::text "
                        "FROM feature.curation_collections "
                        "WHERE collection_key = 'merge-test:2026'"
                    )
                )
            ).scalar_one()
        )

    async def run_merge() -> None:
        async with AsyncSession(migrated_engine) as merger, merger.begin():
            await merger.execute(
                text("SET LOCAL application_name = 'rule-race-merge'")
            )
            await merge_from_review(merger, seeded, merged_by="rule-race")

    async def run_rule() -> int:
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            await writer.execute(
                text("SET LOCAL application_name = 'rule-race-writer'")
            )
            result = await curated_repo.apply_curated_source_rule(
                writer,
                rule_id=rule_id,
            )
            return result.inserted_or_updated

    merge_task: asyncio.Task[None] | None = None
    rule_task: asyncio.Task[int] | None = None
    try:
        async with AsyncSession(migrated_engine) as holder, holder.begin():
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
            await _wait_for_application_lock(
                holder,
                application_name="rule-race-merge",
            )
            rule_task = asyncio.create_task(run_rule())
            await _wait_for_application_lock(
                holder,
                application_name="rule-race-writer",
            )

        assert merge_task is not None
        await asyncio.wait_for(merge_task, timeout=5)
        assert rule_task is not None
        assert await asyncio.wait_for(rule_task, timeout=5) == 0
    finally:
        for task in (rule_task, merge_task):
            if task is not None and not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_collections "
                    "WHERE theme_id IN ("
                    "SELECT theme_id FROM feature.curated_themes "
                    "WHERE theme_slug = :theme_slug"
                    ")"
                ),
                {"theme_slug": theme_slug},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_source_rules "
                    "WHERE rule_id = CAST(:rule_id AS uuid)"
                ),
                {"rule_id": rule_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_sources "
                    "WHERE provider = 'python-visitkorea-api' "
                    "AND dataset_key = 'd' "
                    "AND source_name = 'merge rule race'"
                )
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_themes "
                    "WHERE theme_slug = :theme_slug"
                ),
                {"theme_slug": theme_slug},
            )


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
