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
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import merge_repo as _merge_repo
from kortravelmap.infra.curation_repo import (
    ResolvedCurationImportRow,
    add_curation_item,
    import_curation_rows,
    update_curation_item,
)
from kortravelmap.infra.merge_repo import (
    MergeConflictError,
    MergeNotFoundError,
)
from kortravelmap.infra.models import (
    DedupReviewQueueRow,
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)
from tests.integration.conftest import as_api_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


# ── 모든 merge 호출은 실제 API runtime role로 ────────────────────────────────
#
# 0222가 merge procedure에 0214와 같은 executor 게이트를 넣었다(admin executor만). 컨테이너
# superuser는 그 게이트에 걸리고, 애초에 superuser는 ACL을 안 봐서 fence 회귀를 못 잡는다
# (그래서 PR #994의 P1이 CI 초록·prod 빨강이었다). 그래서 이 모듈의 merge 호출 21곳은 전부
# `as_api_runtime`으로 감싼다. savepoint 안에서 감싸므로 merge가 예외를 내도(테스트가 기대하는
# MergeError 등) LOCAL authorization이 함께 되돌아가 뒤따르는 superuser 검증 SQL이 깨지지 않는다.


async def merge_from_review(session: AsyncSession, *args: Any, **kwargs: Any) -> Any:
    async with session.begin_nested(), as_api_runtime(session):
        return await _merge_repo.merge_from_review(session, *args, **kwargs)


async def apply_feature_merge(session: AsyncSession, *args: Any, **kwargs: Any) -> Any:
    async with session.begin_nested(), as_api_runtime(session):
        return await _merge_repo.apply_feature_merge(session, *args, **kwargs)

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
    )


def _source_entity(key: str, provider_dataset_id: int) -> SourceEntityRow:
    return SourceEntityRow(
        source_entity_key=key,
        provider_dataset_id=provider_dataset_id,
        source_entity_type="t",
        source_entity_id=key,
        first_seen_at=_FETCHED,
        last_seen_at=_FETCHED,
    )


def _source_record(key: str, *, source_entity_key: str) -> SourceRecordRow:
    return SourceRecordRow(
        source_record_key=key,
        source_entity_key=source_entity_key,
        raw_payload_hash=key.encode("utf-8").hex(),
        raw_data={},
        fetched_at=_FETCHED,
        imported_at=_FETCHED,
    )


def _link(feature_id: str, entity_key: str, *, primary: bool = True) -> SourceLinkRow:
    return SourceLinkRow(
        feature_id=feature_id,
        source_entity_key=entity_key,
        source_role="primary" if primary else "enrichment",
        match_method="natural_key",
        confidence=100,
    )


async def _seed_provider_dataset(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind
                    ) VALUES (
                        :provider, :dataset_key, :display_name, 'manual'
                    )
                    ON CONFLICT (provider, dataset_key) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        is_active = true
                    RETURNING provider_dataset_id
                    """
                ),
                {
                    "provider": provider,
                    "dataset_key": dataset_key,
                    "display_name": f"{provider}/{dataset_key}",
                },
            )
        ).scalar_one()
    )


async def _seed_curated_source(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    source_name: str,
) -> None:
    """T-VN-40 import가 요구하는 retained source catalog를 준비한다."""

    await session.execute(
        text(
            """
            INSERT INTO feature.curated_sources (
                provider_dataset_id, source_name, source_kind,
                update_cycle, provider_status, metadata
            ) VALUES (
                :provider_dataset_id, :source_name, 'manual',
                'unknown', 'manual_only', '{}'::jsonb
            )
            ON CONFLICT (provider_dataset_id) DO NOTHING
            """
        ),
        {
            "provider_dataset_id": provider_dataset_id,
            "source_name": source_name,
        },
    )


async def _seed_pair(engine: AsyncEngine) -> str:
    """master(좌표 O) + loser(좌표 X) + source_links(충돌 SR 포함) + 큐 1행 적재.

    반환: 생성된 ``review_id``. SE1은 양쪽 모두 링크(충돌), SE2는 loser 전용.
    """
    async with AsyncSession(engine) as session, session.begin():
        session.add(_feature("f_master", with_coord=True))
        session.add(_feature("f_loser", with_coord=False))
        mois_dataset_id = await _seed_provider_dataset(
            session, provider="merge-test-mois", dataset_key="d"
        )
        visitkorea_dataset_id = await _seed_provider_dataset(
            session, provider="merge-test-visitkorea", dataset_key="d"
        )
        curated_dataset_id = await _seed_provider_dataset(
            session, provider="merge-test-provider", dataset_key="legacy-curation"
        )
        entity_1 = _source_entity("SE1", mois_dataset_id)
        entity_2 = _source_entity("SE2", visitkorea_dataset_id)
        session.add(entity_1)
        session.add(entity_2)
        await session.flush()
        session.add(_source_record("SR1", source_entity_key="SE1"))
        session.add(_source_record("SR2", source_entity_key="SE2"))
        await session.flush()
        session.add_all(
            (
                SourceEntityHeadRow(
                    source_entity_key="SE1",
                    current_source_record_key="SR1",
                    observed_at=_FETCHED,
                ),
                SourceEntityHeadRow(
                    source_entity_key="SE2",
                    current_source_record_key="SR2",
                    observed_at=_FETCHED,
                ),
            )
        )
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
                        provider_dataset_id, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        :curated_dataset_id, '병합 legacy 출처', 'manual', 'unknown',
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
            ,
            {"curated_dataset_id": curated_dataset_id},
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
    """DB owner인 테스트 teardown만 immutable trigger를 끄고 leaf-first 정리한다."""

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
    immutable_tables = (
        "curation_import_batches",
        "curation_import_rows",
        "curation_link_decisions",
    )
    for table_name in immutable_tables:
        await session.execute(
            text(
                f"ALTER TABLE feature.{table_name} "
                f"DISABLE TRIGGER trg_{table_name}_append_only"
            )
        )
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
    for table_name in reversed(immutable_tables):
        await session.execute(
            text(
                f"ALTER TABLE feature.{table_name} "
                f"ENABLE TRIGGER trg_{table_name}_append_only"
            )
        )


async def _links_of(engine: AsyncEngine, feature_id: str) -> set[str]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(SourceLinkRow.source_entity_key).where(SourceLinkRow.feature_id == feature_id)
        )
        return {r[0] for r in result}


async def _feature_axes(engine: AsyncEngine, feature_id: str) -> tuple[str, str, str]:
    """Feature의 (lifecycle, publication, quality) 3축을 읽는다.

    0097이 ``status``/``deleted_at``을 물리 삭제했다. 이 헬퍼가 돌려주던
    ``(status, deleted_at IS NOT NULL)`` 쌍은 두 축으로 갈라졌다 —
    ``deleted_at IS NULL``이 ``lifecycle_state='active'``이고, ``status='active'``는
    세 축이 모두 공개값인 상태다. 병합이 어느 축을 건드렸는지 구분해서 봐야 하므로
    쌍이 아니라 축 3개를 그대로 돌려준다.
    """

    async with AsyncSession(engine) as session:
        row = (
            await session.execute(
                select(
                    FeatureRow.lifecycle_state,
                    FeatureRow.publication_state,
                    FeatureRow.quality_state,
                ).where(FeatureRow.feature_id == feature_id)
            )
        ).one()
        return (row[0], row[1], row[2])


async def _is_on_public_surface(engine: AsyncEngine, feature_id: str) -> bool:
    """``feature.public_features``에 그 Feature가 실재하는지.

    "공개 표면에 보인다"의 정본 술어는 0097이 만든 이 view다. 테스트가 축 3개를
    손으로 조합해 공개 여부를 흉내 내면 view 정의가 바뀔 때 조용히 갈라지므로,
    공개 여부는 view 실재로만 단언한다.
    """

    async with AsyncSession(engine) as session:
        return bool(
            (
                await session.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM feature.public_features "
                        "WHERE feature_id = :feature_id)"
                    ),
                    {"feature_id": feature_id},
                )
            ).scalar_one()
        )


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
            "WHERE provider_dataset_id IN ("
            "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
            "WHERE provider IN ('merge-test-mois', 'merge-test-visitkorea', "
            "'merge-test-provider'))",
            "DELETE FROM provider_sync.source_links "
            "WHERE feature_id IN ('f_master', 'f_loser')",
            "DELETE FROM provider_sync.source_entity_heads "
            "WHERE source_entity_key IN ('SE1', 'SE2')",
            "DELETE FROM provider_sync.source_records "
            "WHERE source_record_key IN ('SR1', 'SR2')",
            "DELETE FROM provider_sync.source_entities "
            "WHERE source_entity_key IN ('SE1', 'SE2')",
            "DELETE FROM feature.features "
            "WHERE feature_id IN ('f_master', 'f_loser', 'f_theme_reuse')",
            "DELETE FROM provider_sync.provider_datasets "
            "WHERE provider IN ('merge-test-mois', 'merge-test-visitkorea', "
            "'merge-test-provider')",
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
    # loser는 T-VN-34 typed lifecycle transition으로 retire/suppress된다.
    async with AsyncSession(migrated_engine) as session:
        loser_axes = (
            await session.execute(
                text(
                    """
                    SELECT lifecycle_state, publication_state, quality_state
                    FROM feature.features WHERE feature_id = 'f_loser'
                    """
                )
            )
        ).one()
    assert tuple(loser_axes) == ("retired", "suppressed", "valid")
    # master는 transition writer가 건드리지 않는다. legacy `status='active'`가
    # 뜻하던 상태는 3축에서 (active, published, valid)이고, 그 셋이 곧 공개 projection
    # 술어이므로 "축이 그대로다"와 "공개 표면에 그대로 있다"를 함께 못 박는다.
    assert await _feature_axes(migrated_engine, "f_master") == (
        "active",
        "published",
        "valid",
    )
    assert await _is_on_public_surface(migrated_engine, "f_master") is True
    # loser는 반대로 공개 표면에서 사라져야 한다(legacy `deleted_at IS NOT NULL`).
    assert await _is_on_public_surface(migrated_engine, "f_loser") is False

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
                      AND field_path = 'lifecycle_state'
                      AND status = 'active'
                    """
                )
            )
        ).one()
        assert override[0] == "retired"
        assert override[1] is True
        assert override[2] == "dup"
        assert override[3] == "op-1"


async def test_merge_keeps_legacy_and_provenance_less_links_fail_closed(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        state = (
            await session.execute(
                text(
                    """
                    SELECT
                        collection_id::text,
                        curation_item_id::text
                    FROM feature.curation_items
                    WHERE feature_id = 'f_loser'
                      AND external_item_id = 'loser-only'
                    """
                )
            )
        ).one()
        legacy_decision_id = str(
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO feature.curation_link_decisions (
                            curation_item_id,
                            feature_id,
                            decision_kind,
                            match_basis,
                            resolver_version,
                            evidence,
                            actor
                        ) VALUES (
                            CAST(:item_id AS uuid),
                            'f_loser',
                            'accepted',
                            'legacy_unattributed',
                            'pre-0072-unknown',
                            '{"fixture":"legacy"}'::jsonb,
                            'migration:0072'
                        )
                        RETURNING decision_id::text
                        """
                    ),
                    {"item_id": state.curation_item_id},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET accepted_link_decision_id =
                        CAST(:decision_id AS uuid)
                WHERE curation_item_id = CAST(:item_id AS uuid)
                """
            ),
            {
                "decision_id": legacy_decision_id,
                "item_id": state.curation_item_id,
            },
        )
        provenance_less_item_id = str(
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO feature.curation_items (
                            collection_id,
                            feature_id,
                            external_item_id,
                            external_component_id,
                            place_name,
                            status
                        ) VALUES (
                            CAST(:collection_id AS uuid),
                            'f_loser',
                            'provenance-less',
                            'primary',
                            '근거 없는 병합 대상',
                            'included'
                        )
                        RETURNING curation_item_id::text
                        """
                    ),
                    {"collection_id": state.collection_id},
                )
            ).scalar_one()
        )
        await merge_from_review(
            session,
            seeded,
            merged_by="fail-close-merge",
            reason="unsafe links stay private",
        )

    async with AsyncSession(migrated_engine) as session:
        moved = (
            await session.execute(
                text(
                    """
                    SELECT
                        external_item_id,
                        feature_id,
                        accepted_link_decision_id::text
                    FROM feature.curation_items
                    WHERE curation_item_id IN (
                        CAST(:legacy_item_id AS uuid),
                        CAST(:provenance_less_item_id AS uuid)
                    )
                    ORDER BY external_item_id
                    """
                ),
                {
                    "legacy_item_id": state.curation_item_id,
                    "provenance_less_item_id": provenance_less_item_id,
                },
            )
        ).all()
        public_gate_count = (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM feature.curation_items AS item
                    JOIN feature.curation_link_decisions AS decision
                      ON decision.decision_id =
                         item.accepted_link_decision_id
                     AND decision.curation_item_id =
                         item.curation_item_id
                     AND decision.feature_id = item.feature_id
                    WHERE item.curation_item_id IN (
                        CAST(:legacy_item_id AS uuid),
                        CAST(:provenance_less_item_id AS uuid)
                    )
                      AND decision.decision_kind = 'accepted'
                      AND decision.match_basis <> 'legacy_unattributed'
                    """
                ),
                {
                    "legacy_item_id": state.curation_item_id,
                    "provenance_less_item_id": provenance_less_item_id,
                },
            )
        ).scalar_one()
        revocations = (
            await session.execute(
                text(
                    """
                    SELECT
                        curation_item_id::text,
                        decision_kind,
                        match_basis,
                        evidence->>'trusted_acceptance'
                    FROM feature.curation_link_decisions
                    WHERE curation_item_id IN (
                        CAST(:legacy_item_id AS uuid),
                        CAST(:provenance_less_item_id AS uuid)
                    )
                      AND resolver_version = 'feature-merge-v1'
                    ORDER BY curation_item_id
                    """
                ),
                {
                    "legacy_item_id": state.curation_item_id,
                    "provenance_less_item_id": provenance_less_item_id,
                },
            )
        ).all()
    assert moved == [
        ("loser-only", "f_master", None),
        ("provenance-less", "f_master", None),
    ]
    assert public_gate_count == 0
    assert len(revocations) == 2
    assert all(row[1:] == ("revoked", "forward_recovery", "false") for row in revocations)


async def test_duplicate_merge_appends_survivor_owned_current_import_row(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    provider = "merge-test-provider"
    dataset_key = "duplicate-provenance"
    async with AsyncSession(migrated_engine) as session, session.begin():
        provider_dataset_id = await _seed_provider_dataset(
            session, provider=provider, dataset_key=dataset_key
        )
        await _seed_curated_source(
            session,
            provider_dataset_id=provider_dataset_id,
            source_name="병합 테스트 출처",
        )
    common = {
        "collection_key": "merge-test:2026",
        "theme_slug": "merge-test",
        "theme_name": "병합 테스트",
        "theme_group": "test",
        "title": "병합 테스트 2026",
        "edition_key": "2026",
        "provider_dataset_id": provider_dataset_id,
        "source_name": "병합 테스트 출처",
        "source_url": None,
        "source_item_key": "shared",
        "address_hint": None,
        "sort_order": 1,
        "item_title": None,
        "item_summary": None,
    }
    rows = (
        ResolvedCurationImportRow(
            row_number=2,
            source_component_key="component-01",
            feature_id="f_master",
            place_name="이전 master source",
            metadata={"provider_revision": "master-old"},
            provenance={"fixture": "master-import"},
            **common,
        ),
        ResolvedCurationImportRow(
            row_number=3,
            source_component_key="component-02",
            feature_id="f_loser",
            place_name="최신 loser source",
            metadata={"provider_revision": "loser-new"},
            provenance={"fixture": "loser-import"},
            **common,
        ),
    )
    async with AsyncSession(migrated_engine) as session, session.begin():
        await import_curation_rows(
            session,
            rows=rows,
            actor="duplicate-importer",
            source_content_sha256="c" * 64,
            batch_kind="csv_upload",
        )
        before = {
            str(row["feature_id"]): dict(row)
            for row in (
                (
                    await session.execute(
                        text(
                            """
                            SELECT
                                feature_id,
                                curation_item_id::text,
                                current_import_row_id::text,
                                accepted_link_decision_id::text
                            FROM feature.curation_items
                            WHERE external_item_id = 'shared'
                              AND source_present
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
        }
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET source_updated_at = source_updated_at + interval '1 hour'
                WHERE curation_item_id =
                      CAST(:loser_item_id AS uuid)
                """
            ),
            {"loser_item_id": before["f_loser"]["curation_item_id"]},
        )
        await merge_from_review(
            session,
            seeded,
            merged_by="duplicate-merge-operator",
            reason="loser provider row is newer",
        )

    async with AsyncSession(migrated_engine) as session:
        survivor = (
            (
                await session.execute(
                    text(
                        """
                        SELECT
                            item.curation_item_id::text,
                            item.place_name,
                            item.metadata,
                            item.current_import_row_id::text,
                            import_row.curation_item_id::text AS row_owner,
                            import_row.row_payload->>'place_name' AS row_place_name,
                            import_row.row_payload->'metadata' AS row_metadata,
                            import_row.row_payload->>'provider' AS row_provider,
                            import_row.row_payload->>'dataset_key' AS row_dataset_key,
                            import_row.provenance,
                            batch.batch_kind,
                            batch.row_count,
                            batch.actor,
                            decision.import_row_id::text AS decision_import_row_id,
                            decision.match_basis,
                            decision.resolver_version,
                            decision.supersedes_decision_id::text
                        FROM feature.curation_items AS item
                        JOIN feature.curation_import_rows AS import_row
                          ON import_row.import_row_id =
                             item.current_import_row_id
                        JOIN feature.curation_import_batches AS batch
                          ON batch.import_batch_id =
                             import_row.import_batch_id
                        JOIN feature.curation_link_decisions AS decision
                          ON decision.decision_id =
                             item.accepted_link_decision_id
                        WHERE item.curation_item_id =
                              CAST(:survivor_item_id AS uuid)
                        """
                    ),
                    {"survivor_item_id": before["f_master"]["curation_item_id"]},
                )
            )
            .mappings()
            .one()
        )
    assert survivor["place_name"] == "최신 loser source"
    assert survivor["metadata"] == {"provider_revision": "loser-new"}
    assert survivor["current_import_row_id"] not in {
        before["f_master"]["current_import_row_id"],
        before["f_loser"]["current_import_row_id"],
    }
    assert survivor["row_owner"] == before["f_master"]["curation_item_id"]
    assert survivor["row_place_name"] == survivor["place_name"]
    assert survivor["row_metadata"] == survivor["metadata"]
    assert survivor["row_provider"] == provider
    assert survivor["row_dataset_key"] == dataset_key
    assert survivor["provenance"]["provider_winner_import_row_id"] == (
        before["f_loser"]["current_import_row_id"]
    )
    assert survivor["batch_kind"] == "forward_recovery"
    assert survivor["row_count"] == 1
    assert survivor["actor"] == "duplicate-merge-operator"
    assert survivor["decision_import_row_id"] == survivor["current_import_row_id"]
    assert survivor["match_basis"] == "forward_recovery"
    assert survivor["resolver_version"] == "feature-merge-v2"
    assert survivor["supersedes_decision_id"] == (
        before["f_master"]["accepted_link_decision_id"]
    )


async def test_duplicate_merge_reconciles_active_and_historical_components(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        provider_dataset_id = await _seed_provider_dataset(
            session,
            provider="merge-test-provider",
            dataset_key="duplicate-multi-component",
        )
        await _seed_curated_source(
            session,
            provider_dataset_id=provider_dataset_id,
            source_name="병합 테스트 출처",
        )
    common = {
        "collection_key": "merge-test:2026",
        "theme_slug": "merge-test",
        "theme_name": "병합 테스트",
        "theme_group": "test",
        "title": "병합 테스트 2026",
        "edition_key": "2026",
        "provider_dataset_id": provider_dataset_id,
        "source_name": "병합 테스트 출처",
        "source_url": None,
        "source_item_key": "shared",
        "address_hint": None,
        "sort_order": 1,
        "item_title": None,
        "item_summary": None,
    }
    first_rows = (
        ResolvedCurationImportRow(
            row_number=2,
            source_component_key="component-01",
            feature_id="f_master",
            place_name="master current",
            metadata={"revision": "master-first"},
            provenance={"fixture": "master-first"},
            **common,
        ),
        ResolvedCurationImportRow(
            row_number=3,
            source_component_key="component-02",
            feature_id="f_loser",
            place_name="loser historical",
            metadata={"revision": "loser-history"},
            provenance={"fixture": "loser-history"},
            **common,
        ),
    )
    second_rows = (
        ResolvedCurationImportRow(
            row_number=2,
            source_component_key="component-01",
            feature_id="f_master",
            place_name="master current",
            metadata={"revision": "master-second"},
            provenance={"fixture": "master-second"},
            **common,
        ),
        ResolvedCurationImportRow(
            row_number=3,
            source_component_key="component-03",
            feature_id="f_loser",
            place_name="loser active winner",
            metadata={"revision": "loser-active"},
            provenance={"fixture": "loser-active"},
            **common,
        ),
    )

    async with AsyncSession(migrated_engine) as session, session.begin():
        await import_curation_rows(
            session,
            rows=first_rows,
            actor="multi-component-first",
            source_content_sha256="d" * 64,
            batch_kind="csv_upload",
        )
        await import_curation_rows(
            session,
            rows=second_rows,
            actor="multi-component-second",
            source_content_sha256="e" * 64,
            batch_kind="csv_upload",
        )
        await session.execute(
            text(
                """
                UPDATE feature.curation_items
                SET source_updated_at =
                    source_updated_at + interval '1 hour'
                WHERE feature_id = 'f_loser'
                  AND external_item_id = 'shared'
                  AND source_present
                """
            )
        )
        before = {
            str(row["external_component_id"]): dict(row)
            for row in (
                (
                    await session.execute(
                        text(
                            """
                            SELECT
                                external_component_id,
                                curation_item_id::text,
                                source_present,
                                current_import_row_id::text
                            FROM feature.curation_items
                            WHERE external_item_id = 'shared'
                            ORDER BY external_component_id
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
        }

        await merge_from_review(
            session,
            seeded,
            merged_by="multi-component-merge",
            reason="canonical group reconciliation",
        )

    async with AsyncSession(migrated_engine) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT
                            item.external_component_id,
                            item.feature_id,
                            item.source_present,
                            item.archived_at IS NOT NULL AS archived,
                            item.place_name,
                            item.metadata,
                            item.current_import_row_id::text,
                            import_row.curation_item_id::text AS row_owner,
                            import_row.provenance
                        FROM feature.curation_items AS item
                        LEFT JOIN feature.curation_import_rows AS import_row
                          ON import_row.import_row_id =
                             item.current_import_row_id
                         AND import_row.curation_item_id =
                             item.curation_item_id
                        WHERE item.external_item_id = 'shared'
                        ORDER BY item.external_component_id
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
        active_count = (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM feature.curation_items
                    WHERE external_item_id = 'shared'
                      AND feature_id = 'f_master'
                      AND source_present
                      AND archived_at IS NULL
                    """
                )
            )
        ).scalar_one()

    by_component = {
        str(row["external_component_id"]): dict(row) for row in rows
    }
    survivor = by_component["component-01"]
    historical = by_component["component-02"]
    archived_current = by_component["component-03"]

    assert active_count == 1
    assert all(row["feature_id"] == "f_master" for row in rows)
    assert survivor["source_present"] is True
    assert survivor["archived"] is False
    assert survivor["place_name"] == "loser active winner"
    assert survivor["metadata"] == {"revision": "loser-active"}
    assert survivor["row_owner"] == before["component-01"]["curation_item_id"]
    assert survivor["current_import_row_id"] not in {
        before["component-01"]["current_import_row_id"],
        before["component-03"]["current_import_row_id"],
    }
    assert survivor["provenance"]["provider_winner_import_row_id"] == (
        before["component-03"]["current_import_row_id"]
    )

    assert historical["source_present"] is False
    assert historical["archived"] is True
    assert historical["current_import_row_id"] == (
        before["component-02"]["current_import_row_id"]
    )
    assert historical["row_owner"] == before["component-02"]["curation_item_id"]
    assert historical["provenance"] == {"fixture": "loser-history"}

    assert archived_current["source_present"] is False
    assert archived_current["archived"] is True
    assert archived_current["current_import_row_id"] == (
        before["component-03"]["current_import_row_id"]
    )
    assert archived_current["row_owner"] == (
        before["component-03"]["curation_item_id"]
    )
    assert archived_current["provenance"] == {"fixture": "loser-active"}


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
        # 이 fixture가 f_theme_reuse에 요구하는 것은 "legacy writer가 붙일 수 있는
        # 평범한 공개 Feature" 하나뿐이다. 0097이 지운 legacy `status='active'`는
        # 3축의 (active, published, valid)이고 그 셋이 그대로 컬럼 DEFAULT이므로,
        # 축을 적지 않는 편이 원래 INSERT와 등가다.
        await session.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category
                ) VALUES (
                    'f_theme_reuse', 'place', 'slug 재사용 장소', '01070100'
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
                      AND source_present
                      AND archived_at IS NULL
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
            "f_master",
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
                WITH dataset AS (
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind
                    ) VALUES (:provider, 'race', 'merge/import race', 'manual')
                    RETURNING provider_dataset_id
                ), theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group
                    ) VALUES (:theme_slug, 'merge/import race', 'test')
                    RETURNING theme_id
                ), source AS (
                    INSERT INTO feature.curated_sources (
                        provider_dataset_id, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    )
                    SELECT provider_dataset_id, 'merge/import race',
                           'manual', 'unknown', 'manual_only', '{}'::jsonb
                    FROM dataset
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
        provider_dataset_id = int(
            (
                await connection.execute(
                    text(
                        "SELECT provider_dataset_id "
                        "FROM provider_sync.provider_datasets "
                        "WHERE provider = :provider AND dataset_key = 'race'"
                    ),
                    {"provider": provider},
                )
            ).scalar_one()
        )
    row = ResolvedCurationImportRow(
        row_number=2,
        collection_key=collection_key,
        theme_slug=theme_slug,
        theme_name="merge/import race",
        theme_group="test",
        title="race",
        edition_key="2026",
        provider_dataset_id=provider_dataset_id,
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
                    "WHERE provider_dataset_id IN ("
                    "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
                    "WHERE provider = :provider AND dataset_key = 'race')"
                ),
                {"provider": provider},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM provider_sync.provider_datasets "
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
                    "WHERE provider_dataset_id IN ("
                    "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
                    "WHERE provider = :provider AND dataset_key = 'race')"
                ),
                {"provider": provider},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM provider_sync.provider_datasets "
                    "WHERE provider = :provider AND dataset_key = 'race'"
                ),
                {"provider": provider},
            )


# T-VN-40A: `legacy_create` case를 뺐다. 그 case는 "merge 중 legacy writer가 끼어든다"를
# 시뮬레이션했는데, fence 뒤로 legacy write는 static 층에서 즉시 죽어 **끼어들 수가
# 없다.** 남겨두면 fence 예외를 race 결과로 오독한다. fence 자체는
# `test_curated_repo.py::test_manual_curated_feature_writes_are_fenced`가 검증한다.
@pytest.mark.parametrize("writer_kind", ["add", "feature_link"])
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
            else:  # pragma: no cover — legacy_create는 parametrize에서 뺐다 (T-VN-40A)
                raise AssertionError(f"unexpected writer_kind {writer_kind!r}")

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
        # 단언의 본질은 "merge가 retire한 f_loser에는 어떤 membership writer도
        # 붙지 못한다"이고, 세 writer는 각자 다른 문구로 거절한다. legacy_create만
        # 3축 전환에서 문구가 "active Feature"→"selectable Feature"로 바뀌었는데,
        # 그 가드가 보는 술어가 legacy `status NOT IN ('deleted','hidden')`의 등가물인
        # `lifecycle='active' AND publication <> 'suppressed'`라서 draft·quarantined도
        # 통과시키기 때문이다 — 'active'는 이제 lifecycle 축 이름이라 오해를 부른다.
        # 통짜 OR 대신 writer별 문구를 못 박아, 가드가 서로 뒤바뀌는 것까지 잡는다.
        expected_refusal = {
            "add": "must reference an active Feature",
            "feature_link": "Feature가 없습니다",
        }[writer_kind]
        with pytest.raises(ValueError, match=expected_refusal):
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
