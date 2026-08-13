"""회차·출처가 겹치는 Feature 큐레이션 membership 통합 검증."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from kortravelmap.infra import curated_repo
from kortravelmap.infra.curation_repo import (
    _GET_COLLECTION_ID_BY_KEY_SQL,  # noqa: PLC2701 - concurrency regression
    _GET_SOURCE_ID_BY_DATASET_ID_SQL,  # noqa: PLC2701 - concurrency regression
    _LIST_FEATURE_ITEMS_SQL,  # noqa: PLC2701 - EXPLAIN 대상
    _RESOLVE_FEATURES_BATCH_SQL,  # noqa: PLC2701 - EXPLAIN 대상
    _UPSERT_COLLECTION_SQL,  # noqa: PLC2701 - concurrency regression
    _UPSERT_SOURCE_SQL,  # noqa: PLC2701 - concurrency regression
    CurationImportResult,
    CurationQuarantineMoveConflictError,
    CurationQuarantineTargetArchivedError,
    FeatureMatchRequest,
    ResolvedCurationImportRow,
    _upsert_id_with_fallback,  # noqa: PLC2701 - concurrency regression
    add_curation_item,
    archive_curation_collection,
    archive_curation_item,
    confirm_curation_quarantine_standalone,
    create_curation_collection,
    decode_collection_cursor,
    decode_quarantine_collection_cursor,
    decode_quarantine_item_cursor,
    encode_quarantine_collection_cursor,
    encode_quarantine_item_cursor,
    get_curation_collection,
    get_curation_item,
    get_feature_curation_group,
    import_curation_rows,
    list_curation_collections,
    list_curation_items_by_feature_ids,
    list_curation_quarantine_collections,
    list_curation_quarantine_items,
    list_feature_curation_groups,
    list_unattributed_curation_links,
    move_curation_quarantine_items,
    preview_curation_import,
    resolve_feature_matches,
    update_curation_collection,
    update_curation_item,
    upsert_curation_theme,
)
from kortravelmap.infra.models import (
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceRecordRow,
)
from tests.integration._db_cleanup import truncate_committed_test_rows

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_FEATURE_ID = "feature:curation-multi-test"


def _payload_hash(seed: str) -> str:
    """``ck_source_records_payload_hash``(^[0-9a-f]{1,64}$)를 만족하는 값."""

    return hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()


async def _dataset_id(session: AsyncSession, provider: str, dataset_key: str) -> int:
    """provider/dataset pair를 catalog에 심고 canonical id를 돌려준다.

    T-VN-33 이후 curated source·source entity의 dataset identity는
    ``provider_dataset_id`` 하나다 — provider/dataset_key 사본은 catalog
    projection으로만 남는다. 테스트 전용 pair는 catalog에 없으므로 먼저 심는다.
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


async def _catalog_dataset_id(
    engine: AsyncEngine, provider: str, dataset_key: str
) -> int:
    """committed fixture용 — 별도 connection에서 catalog 행을 심고 commit한다."""

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    async with _AsyncSession(engine, expire_on_commit=False) as catalog:
        dataset_id = await _dataset_id(catalog, provider, dataset_key)
        await catalog.commit()
    return dataset_id


async def _seed_foundations(session: AsyncSession) -> tuple[str, str]:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, address,
                marker_icon, marker_color
            ) VALUES (
                :feature_id, 'place', '겹치는 관광지', '01070100',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(126.9780, 37.5665), 4326
                ),
                '{"road":"서울"}'::jsonb, 'place', 'P-01'
            )
            """
        ),
        {"feature_id": _FEATURE_ID},
    )
    theme_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_description, theme_group,
                        default_curated, visibility, metadata
                    ) VALUES (
                        'tourism-100-test', '한국관광 100선', '', 'official',
                        false, 'public', '{}'::jsonb
                    )
                    RETURNING theme_id::text
                    """
                )
            )
        ).scalar_one()
    )
    source_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_sources (
                        provider_dataset_id, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        :provider_dataset_id, '문화체육관광부',
                        'manual', 'unknown', 'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id::text
                    """
                ),
                {
                    "provider_dataset_id": await _dataset_id(
                        session, "python-mcst-api", "tourism-100-test"
                    )
                },
            )
        ).scalar_one()
    )
    return theme_id, source_id


async def test_same_feature_returns_every_edition_and_subcourse_membership(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    collection_2023 = await create_curation_collection(
        migrated_session,
        collection_key="tourism-100:2023-2024",
        theme_id=theme_id,
        source_id=source_id,
        title="2023~2024 한국관광 100선",
        edition_key="2023-2024",
        status="published",
        visibility="public",
    )
    collection_2025 = await create_curation_collection(
        migrated_session,
        collection_key="tourism-100:2025-2026",
        theme_id=theme_id,
        source_id=source_id,
        title="2025~2026 한국관광 100선",
        edition_key="2025-2026",
        status="published",
        visibility="public",
    )
    first_page, collection_cursor = await list_curation_collections(
        migrated_session, theme_slug="tourism-100-test", limit=1
    )
    assert len(first_page) == 1
    assert collection_cursor is not None
    second_page, final_collection_cursor = await list_curation_collections(
        migrated_session,
        theme_slug="tourism-100-test",
        limit=1,
        cursor=collection_cursor,
    )
    assert len(second_page) == 1
    assert final_collection_cursor is None
    assert {first_page[0].collection_id, second_page[0].collection_id} == {
        collection_2023.collection_id,
        collection_2025.collection_id,
    }

    first, first_inserted = await add_curation_item(
        migrated_session,
        collection_id=collection_2023.collection_id,
        feature_id=_FEATURE_ID,
        external_item_id="2023:001",
        status="included",
        sort_order=1,
        metadata={"subcourse": "수도권"},
    )
    await add_curation_item(
        migrated_session,
        collection_id=collection_2025.collection_id,
        feature_id=_FEATURE_ID,
        external_item_id="2025:001",
        status="included",
        sort_order=1,
        metadata={"subcourse": "수도권"},
    )
    await add_curation_item(
        migrated_session,
        collection_id=collection_2025.collection_id,
        feature_id=_FEATURE_ID,
        external_item_id="2025:001:night-course",
        status="included",
        sort_order=2,
        metadata={"subcourse": "야간 코스"},
    )
    updated, second_inserted = await add_curation_item(
        migrated_session,
        collection_id=collection_2023.collection_id,
        feature_id=_FEATURE_ID,
        external_item_id="2023:001",
        status="included",
        sort_order=7,
        metadata={"subcourse": "수도권", "updated": True},
    )

    assert first_inserted
    assert not second_inserted
    assert first.curation_item_id == updated.curation_item_id
    assert updated.sort_order == 7

    group = await get_feature_curation_group(
        migrated_session, feature_id=_FEATURE_ID, public_only=True
    )
    assert group is not None
    assert len(group.curations) == 3
    assert {item.edition_key for item in group.curations} == {
        "2023-2024",
        "2025-2026",
    }
    assert {item.metadata.get("subcourse") for item in group.curations} == {"수도권", "야간 코스"}

    groups, next_cursor = await list_feature_curation_groups(
        migrated_session,
        public_only=True,
        min_lon=126.9,
        min_lat=37.5,
        max_lon=127.1,
        max_lat=37.7,
        page_size=10,
    )
    assert next_cursor is None
    assert len(groups) == 1
    assert groups[0].feature_id == _FEATURE_ID
    assert len(groups[0].curations) == 3

    # 여기서 재던 것은 "운영자가 feature를 **감췄을 때**" 큐레이션 공개면이 어떻게
    # 되는가다. 0095 backfill에서 `status='hidden'`은 (active, suppressed, valid)로
    # 갈린다 — 삭제(retired)가 아니라 **살아 있으나 게시되지 않은** 상태다. 그래서
    # lifecycle은 건드리지 않고 publication만 내린다. ck_features_state_tuple은
    # `lifecycle='active' OR publication='suppressed'`이므로 이 조합은 허용된다.
    # (lifecycle까지 retired로 내리면 soft delete가 되어, 아래에서 admin 표면에는
    # 남아 있어야 한다는 단언이 다른 사건을 재는 것이 된다.)
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET publication_state = 'suppressed' "
            "WHERE feature_id = :feature_id"
        ),
        {"feature_id": _FEATURE_ID},
    )
    assert (
        await get_feature_curation_group(migrated_session, feature_id=_FEATURE_ID, public_only=True)
        is None
    )
    public_collection = await get_curation_collection(
        migrated_session,
        collection_id=collection_2023.collection_id,
        public_only=True,
    )
    admin_collection = await get_curation_collection(
        migrated_session,
        collection_id=collection_2023.collection_id,
    )
    assert public_collection is not None
    assert admin_collection is not None
    assert public_collection[0].public_item_count == 0
    assert public_collection[1] == ()
    assert admin_collection[1][0].feature_id == _FEATURE_ID
    hidden_matches = await resolve_feature_matches(
        migrated_session,
        requests=(
            FeatureMatchRequest(
                row_number=1,
                feature_id=_FEATURE_ID,
                place_name=None,
                address_hint=None,
            ),
            FeatureMatchRequest(
                row_number=2,
                feature_id=None,
                place_name="겹치는 관광지",
                address_hint=None,
            ),
        ),
    )
    assert hidden_matches == {1: (), 2: ()}


async def test_public_collection_excludes_unlinked_included_item_everywhere(
    migrated_session: AsyncSession,
) -> None:
    """T-VN-40 공개 술어는 linked public Feature+trusted decision을 필수로 한다."""

    theme_id, source_id = await _seed_foundations(migrated_session)
    collection = await create_curation_collection(
        migrated_session,
        collection_key="tvn40-unlinked-public",
        theme_id=theme_id,
        source_id=source_id,
        title="연결되지 않은 공개 항목",
        edition_key="2026",
        status="published",
        visibility="public",
    )
    await add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=None,
        external_item_id="unlinked-included",
        place_name="미연결 장소",
        status="included",
    )

    public = await get_curation_collection(
        migrated_session,
        collection_id=collection.collection_id,
        public_only=True,
    )
    admin = await get_curation_collection(
        migrated_session,
        collection_id=collection.collection_id,
    )

    assert public is not None
    assert public[0].item_count == 0
    assert public[0].public_item_count == 0
    assert public[1] == ()
    assert admin is not None
    assert len(admin[1]) == 1
    assert admin[1][0].feature_id is None


def test_collection_cursor_rejects_non_uuid_tie_breaker() -> None:
    payload = base64.urlsafe_b64encode(
        b'{"updated_at":"2026-07-13T00:00:00+00:00","collection_id":"x"}'
    ).decode()
    with pytest.raises(ValueError, match="invalid curation collection cursor"):
        decode_collection_cursor(payload)


async def test_bulk_import_is_atomic_upsert_friendly_and_idempotent(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, marker_icon, marker_color
            ) VALUES
                ('feature:import-a', 'place', 'CSV 장소 A', '01070100',
                 'place', 'P-01'),
                ('feature:import-b', 'place', 'CSV 장소 B', '01070100',
                 'place', 'P-01')
            """
        )
    )
    common = {
        "collection_key": "csv-import:2026",
        "theme_slug": "csv-import-test",
        "theme_name": "CSV import 테스트",
        "theme_group": "test",
        "title": "2026 CSV import 테스트",
        "edition_key": "2026",
        "provider_dataset_id": await _dataset_id(
            migrated_session, "csv-import-provider", "csv-import-dataset"
        ),
        "source_name": "CSV import 출처",
        "source_url": None,
        "item_title": None,
        "item_summary": None,
        "place_name": "CSV 장소",
        "address_hint": None,
    }
    rows = [
        ResolvedCurationImportRow(
            row_number=2,
            source_item_key="item-a",
            feature_id="feature:import-a",
            sort_order=1,
            metadata={"ordinal": 1},
            **common,
        ),
        ResolvedCurationImportRow(
            row_number=4,
            source_item_key="item-unresolved",
            feature_id=None,
            sort_order=3,
            metadata={"ordinal": 3},
            **{**common, "place_name": "DB 미해결 공식 장소"},
        ),
        ResolvedCurationImportRow(
            row_number=3,
            source_item_key="item-b",
            feature_id="feature:import-b",
            sort_order=2,
            metadata={"ordinal": 2},
            **common,
        ),
    ]

    initial_plan = await preview_curation_import(migrated_session, rows=rows)
    first = await import_curation_rows(migrated_session, rows=rows, actor="test")
    no_op_plan = await preview_curation_import(migrated_session, rows=rows)
    second = await import_curation_rows(migrated_session, rows=rows, actor="test")
    replacement_rows = (
        ResolvedCurationImportRow(
            row_number=2,
            source_item_key="item-a",
            feature_id="feature:import-b",
            sort_order=1,
            metadata={"ordinal": 1, "rematched": True},
            **common,
        ),
        rows[1],
    )
    replacement_plan = await preview_curation_import(migrated_session, rows=replacement_rows)
    replaced = await import_curation_rows(
        migrated_session,
        rows=replacement_rows,
        actor="test",
    )

    assert initial_plan.inserted == 3
    assert initial_plan.updated == 0
    assert initial_plan.removals == ()
    assert first == {
        "rows": 3,
        "collections": 1,
        "inserted": 3,
        "updated": 0,
        "removed": 0,
        "removals": (),
        "import_batch_id": first["import_batch_id"],
    }
    assert second == {
        "rows": 3,
        "collections": 1,
        "inserted": 0,
        "updated": 0,
        "removed": 0,
        "removals": (),
        "import_batch_id": second["import_batch_id"],
    }
    assert no_op_plan.inserted == 0
    assert no_op_plan.updated == 0
    assert no_op_plan.removals == ()
    assert replacement_plan.inserted == 0
    assert replacement_plan.updated == 1
    assert {item.external_item_id for item in replacement_plan.removals} == {
        "item-b",
    }
    assert replaced == {
        "rows": 2,
        "collections": 1,
        "inserted": 0,
        "updated": 1,
        "removed": 1,
        "removals": replacement_plan.removals,
        "import_batch_id": replaced["import_batch_id"],
    }
    counts = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FILTER (WHERE i.source_present) AS present, "
                "count(*) AS total FROM feature.curation_items AS i "
                "JOIN feature.curation_collections AS c "
                "ON c.collection_id = i.collection_id "
                "WHERE c.collection_key = 'csv-import:2026'"
            )
        )
    ).one()
    assert counts == (2, 3)
    unresolved = (
        await migrated_session.execute(
            text("SELECT place_name FROM feature.curation_items WHERE feature_id IS NULL")
        )
    ).scalar_one()
    assert unresolved == "DB 미해결 공식 장소"
    rematched = (
        await migrated_session.execute(
            text(
                "SELECT feature_id FROM feature.curation_items "
                "WHERE external_item_id = 'item-a' AND source_present"
            )
        )
    ).scalar_one()
    assert rematched == "feature:import-b"


async def test_link_provenance_is_append_only_fail_closed_and_recoverable(
    migrated_session: AsyncSession,
) -> None:
    """Import/수동 승인 근거와 selective forward recovery를 실 DB에 고정한다."""
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, marker_icon, marker_color
            ) VALUES
                ('feature:provenance-a', 'place', '근거 장소 A', '01070100',
                 'place', 'P-01'),
                ('feature:provenance-b', 'place', '근거 장소 B', '01070100',
                 'place', 'P-01'),
                ('feature:provenance-c', 'place', '복구 장소 C', '01070100',
                 'place', 'P-01'),
                ('feature:provenance-unsafe', 'place', '미승인 장소', '01070100',
                 'place', 'P-01')
            """
        )
    )
    common = {
        "theme_slug": "provenance-test",
        "theme_name": "큐레이션 근거 테스트",
        "theme_group": "test",
        "edition_key": "2026",
        "provider_dataset_id": await _dataset_id(
            migrated_session, "provenance-provider", "provenance-dataset"
        ),
        "source_name": "근거 출처",
        "source_url": None,
        "source_component_key": "primary",
        "address_hint": "서울특별시 종로구",
        "sort_order": 1,
        "item_title": None,
        "item_summary": None,
        "metadata": {},
    }
    row_a = ResolvedCurationImportRow(
        row_number=2,
        collection_key="provenance:a",
        title="근거 목록 A",
        source_item_key="item-a",
        feature_id="feature:provenance-a",
        place_name="근거 장소 A",
        provenance={
            "sidecar_schema": 1,
            "address_fields": {"sido": "서울특별시", "sigungu": "종로구"},
        },
        **common,
    )
    row_b = ResolvedCurationImportRow(
        row_number=3,
        collection_key="provenance:b",
        title="근거 목록 B",
        source_item_key="item-b",
        feature_id="feature:provenance-b",
        place_name="근거 장소 B",
        provenance={"sidecar_schema": 1},
        **common,
    )
    first = await import_curation_rows(
        migrated_session,
        rows=(row_a, row_b),
        actor="provenance-importer",
        source_content_sha256="a" * 64,
        batch_kind="csv_upload",
    )
    assert first["import_batch_id"] is not None

    first_state = {
        str(row["external_item_id"]): dict(row)
        for row in (
            (
                await migrated_session.execute(
                    text(
                        """
                        SELECT
                            item.external_item_id,
                            item.curation_item_id::text AS curation_item_id,
                            item.current_import_row_id::text AS import_row_id,
                            item.accepted_link_decision_id::text AS decision_id,
                            decision.match_basis,
                            decision.resolver_version,
                            decision.actor,
                            decision.evidence,
                            import_row.provenance
                        FROM feature.curation_items AS item
                        JOIN feature.curation_link_decisions AS decision
                          ON decision.decision_id =
                             item.accepted_link_decision_id
                        JOIN feature.curation_import_rows AS import_row
                          ON import_row.import_row_id =
                             item.current_import_row_id
                        WHERE item.external_item_id IN ('item-a', 'item-b')
                        ORDER BY item.external_item_id
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
    }
    assert first_state["item-a"]["match_basis"] == "csv_explicit_feature_id"
    assert first_state["item-a"]["resolver_version"] == "explicit-feature-id-v1"
    assert first_state["item-a"]["actor"] == "provenance-importer"
    assert first_state["item-a"]["evidence"]["requested_feature_id"] == (
        "feature:provenance-a"
    )
    assert first_state["item-a"]["provenance"]["address_fields"] == {
        "sido": "서울특별시",
        "sigungu": "종로구",
    }
    batch = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT content_sha256, batch_kind, row_count, actor
                    FROM feature.curation_import_batches
                    WHERE import_batch_id = CAST(:batch_id AS uuid)
                    """
                ),
                {"batch_id": first["import_batch_id"]},
            )
        )
        .mappings()
        .one()
    )
    assert dict(batch) == {
        "content_sha256": "a" * 64,
        "batch_kind": "csv_upload",
        "row_count": 2,
        "actor": "provenance-importer",
    }
    immutable_history = (
        (
            "curation_import_batches",
            "import_batch_id",
            str(first["import_batch_id"]),
        ),
        (
            "curation_import_rows",
            "import_row_id",
            first_state["item-a"]["import_row_id"],
        ),
        (
            "curation_link_decisions",
            "decision_id",
            first_state["item-a"]["decision_id"],
        ),
    )
    for table_name, key_name, key_value in immutable_history:
        for statement in (
            f"UPDATE feature.{table_name} "
            f"SET {key_name} = {key_name} "
            f"WHERE {key_name} = CAST(:key_value AS uuid)",
            f"DELETE FROM feature.{table_name} "
            f"WHERE {key_name} = CAST(:key_value AS uuid)",
        ):
            with pytest.raises(DBAPIError, match="append-only"):
                async with migrated_session.begin_nested():
                    await migrated_session.execute(
                        text(statement),
                        {"key_value": key_value},
                    )
    no_truncate_triggers = (
        await migrated_session.execute(
            text(
                """
                SELECT array_agg(trigger.tgname ORDER BY trigger.tgname)
                FROM pg_trigger AS trigger
                JOIN pg_class AS relation
                  ON relation.oid = trigger.tgrelid
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'feature'
                  AND relation.relname IN (
                      'curation_import_batches',
                      'curation_import_rows',
                      'curation_link_decisions'
                  )
                  AND trigger.tgname LIKE '%_no_truncate'
                  AND NOT trigger.tgisinternal
                """
            )
        )
    ).scalar_one()
    assert no_truncate_triggers == [
        "trg_curation_import_batches_no_truncate",
        "trg_curation_import_rows_no_truncate",
        "trg_curation_link_decisions_no_truncate",
    ]
    batch_delete_action = (
        await migrated_session.execute(
            text(
                """
                SELECT constraint_name, delete_rule
                FROM information_schema.referential_constraints
                WHERE constraint_schema = 'feature'
                  AND constraint_name = 'fk_curation_import_rows_batch'
                """
            )
        )
    ).one()
    assert batch_delete_action == (
        "fk_curation_import_rows_batch",
        "RESTRICT",
    )

    decision_insert = """
        INSERT INTO feature.curation_link_decisions (
            decision_id,
            curation_item_id,
            feature_id,
            import_row_id,
            decision_kind,
            match_basis,
            resolver_version,
            evidence,
            actor,
            supersedes_decision_id
        ) VALUES (
            CAST(:decision_id AS uuid),
            CAST(:curation_item_id AS uuid),
            :feature_id,
            CAST(:import_row_id AS uuid),
            'accepted',
            'forward_recovery',
            'same-item-fk-test-v1',
            '{}'::jsonb,
            'same-item-fk-test',
            CAST(:supersedes_decision_id AS uuid)
        )
    """
    with pytest.raises(DBAPIError, match="fk_curation_link_decisions_import_row"):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(decision_insert),
                {
                    "decision_id": str(uuid4()),
                    "curation_item_id": first_state["item-a"]["curation_item_id"],
                    "feature_id": "feature:provenance-a",
                    "import_row_id": first_state["item-b"]["import_row_id"],
                    "supersedes_decision_id": None,
                },
            )
    with pytest.raises(DBAPIError, match="fk_curation_link_decisions_supersedes"):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(decision_insert),
                {
                    "decision_id": str(uuid4()),
                    "curation_item_id": first_state["item-a"]["curation_item_id"],
                    "feature_id": "feature:provenance-a",
                    "import_row_id": first_state["item-a"]["import_row_id"],
                    "supersedes_decision_id": first_state["item-b"]["decision_id"],
                },
            )
    self_decision_id = str(uuid4())
    with pytest.raises(DBAPIError, match="CheckViolationError"):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(decision_insert),
                {
                    "decision_id": self_decision_id,
                    "curation_item_id": first_state["item-a"]["curation_item_id"],
                    "feature_id": "feature:provenance-a",
                    "import_row_id": first_state["item-a"]["import_row_id"],
                    "supersedes_decision_id": self_decision_id,
                },
            )

    recovered_row_a = replace(
        row_a,
        feature_id="feature:provenance-c",
        provenance={"recovery_ticket": "#909"},
    )
    recovery = await import_curation_rows(
        migrated_session,
        rows=(recovered_row_a,),
        actor="recovery-operator",
        source_content_sha256="b" * 64,
        batch_kind="forward_recovery",
    )
    assert recovery["import_batch_id"] is not None
    recovered_state = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT
                        item.feature_id,
                        item.current_import_row_id::text AS import_row_id,
                        item.accepted_link_decision_id::text AS decision_id,
                        decision.match_basis,
                        decision.supersedes_decision_id::text AS supersedes
                    FROM feature.curation_items AS item
                    JOIN feature.curation_link_decisions AS decision
                      ON decision.decision_id =
                         item.accepted_link_decision_id
                    WHERE item.external_item_id = 'item-a'
                    """
                )
            )
        )
        .mappings()
        .one()
    )
    assert recovered_state["feature_id"] == "feature:provenance-c"
    assert recovered_state["match_basis"] == "forward_recovery"
    assert recovered_state["import_row_id"] != first_state["item-a"]["import_row_id"]
    assert recovered_state["decision_id"] != first_state["item-a"]["decision_id"]
    assert recovered_state["supersedes"] == first_state["item-a"]["decision_id"]

    untouched_b = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    current_import_row_id::text,
                    accepted_link_decision_id::text
                FROM feature.curation_items
                WHERE external_item_id = 'item-b'
                """
            )
        )
    ).one()
    assert untouched_b == (
        first_state["item-b"]["import_row_id"],
        first_state["item-b"]["decision_id"],
    )

    collection_a_id = (
        await migrated_session.execute(
            text(
                """
                SELECT collection_id::text
                FROM feature.curation_collections
                WHERE collection_key = 'provenance:a'
                """
            )
        )
    ).scalar_one()
    unsafe_item = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO feature.curation_items (
                    collection_id, feature_id, external_item_id,
                    place_name, status
                ) VALUES (
                    CAST(:collection_id AS uuid),
                    'feature:provenance-unsafe',
                    'unsafe-item',
                    '미승인 장소',
                    'included'
                )
                RETURNING curation_item_id::text
                """
            ),
            {"collection_id": collection_a_id},
        )
    ).scalar_one()
    audits = await list_unattributed_curation_links(migrated_session)
    assert [audit.curation_item_id for audit in audits] == [unsafe_item]
    assert (
        await get_feature_curation_group(
            migrated_session,
            feature_id="feature:provenance-unsafe",
            public_only=True,
        )
        is None
    )

    approved = await update_curation_item(
        migrated_session,
        collection_id=collection_a_id,
        curation_item_id=unsafe_item,
        updates={"feature_id": "feature:provenance-unsafe"},
        actor="manual-reviewer",
    )
    assert approved is not None
    assert approved.link_match_basis == "admin_review"
    assert approved.link_actor == "manual-reviewer"
    assert await list_unattributed_curation_links(migrated_session) == ()
    assert (
        await get_feature_curation_group(
            migrated_session,
            feature_id="feature:provenance-unsafe",
            public_only=True,
        )
        is not None
    )


async def test_authoritative_reimport_preserves_operator_curation_overrides(
    migrated_session: AsyncSession,
) -> None:
    """#699 회귀: authoritative CSV 재적재가 운영자 편집(status/curation_relation/
    reuse_policy)을 보존하고, provider 파생 필드만 갱신한다."""
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, marker_icon, marker_color
            ) VALUES
                ('feature:reimport-a', 'place', '재적재 장소 A', '01070100',
                 'place', 'P-01')
            """
        )
    )
    common = {
        "collection_key": "csv-reimport:2026",
        "theme_slug": "csv-reimport-test",
        "theme_name": "CSV 재적재 테스트",
        "theme_group": "test",
        "title": "재적재 테스트",
        "edition_key": "2026",
        "provider_dataset_id": await _dataset_id(
            migrated_session, "csv-reimport-provider", "csv-reimport-dataset"
        ),
        "source_name": "재적재 출처",
        "source_url": None,
        "item_title": None,
        "item_summary": None,
        "place_name": "원본 장소명",
        "address_hint": None,
    }
    rows = [
        ResolvedCurationImportRow(
            row_number=2,
            source_item_key="reimport-a",
            feature_id="feature:reimport-a",
            sort_order=1,
            metadata={"ordinal": 1},
            **common,
        ),
    ]

    # 1) 최초 적재 → default status='included'/relation='nearby_option'/reuse='manual_review'
    first = await import_curation_rows(migrated_session, rows=rows, actor="importer")
    assert first["inserted"] == 1

    ids = (
        await migrated_session.execute(
            text(
                "SELECT i.curation_item_id::text AS iid, i.collection_id::text AS cid "
                "FROM feature.curation_items AS i "
                "JOIN feature.curation_collections AS c "
                "ON c.collection_id = i.collection_id "
                "WHERE c.collection_key = :ck AND i.external_item_id = :eid "
                "AND i.archived_at IS NULL"
            ),
            {"ck": "csv-reimport:2026", "eid": "reimport-a"},
        )
    ).mappings().one()
    item_id = ids["iid"]
    collection_id = ids["cid"]

    created = await get_curation_item(
        migrated_session, collection_id=collection_id, curation_item_id=item_id
    )
    assert created is not None
    assert created.status == "included"
    assert created.curation_relation == "nearby_option"
    assert created.reuse_policy == "manual_review"

    # 2) 운영자 편집: 오매칭 숨김 + 대표 코스 + 재사용 차단
    await update_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
        updates={
            "status": "rejected",
            "curation_relation": "primary_stop",
            "reuse_policy": "blocked",
        },
        actor="operator",
    )

    # 3) 동일 authoritative CSV 재적재 → 운영자 override 3필드 보존, 무변경으로 집계
    reimport_plan = await preview_curation_import(migrated_session, rows=rows)
    reimport = await import_curation_rows(migrated_session, rows=rows, actor="importer")
    preserved = await get_curation_item(
        migrated_session, collection_id=collection_id, curation_item_id=item_id
    )
    assert preserved is not None
    assert preserved.status == "rejected"
    assert preserved.curation_relation == "primary_stop"
    assert preserved.reuse_policy == "blocked"
    assert reimport_plan.updated == 0
    assert reimport["updated"] == 0
    assert reimport["inserted"] == 0
    # authoritative replace의 DELETE-removals 경로가 operator-edited 행을 잘못 제거하지 않는다
    assert reimport["removed"] == 0

    # 4) provider 파생 필드(place_name)는 CSV authoritative라 재적재로 갱신되고,
    #    운영자 override 3필드는 여전히 보존된다.
    changed_rows = [
        ResolvedCurationImportRow(
            row_number=2,
            source_item_key="reimport-a",
            feature_id="feature:reimport-a",
            sort_order=1,
            metadata={"ordinal": 1},
            **{**common, "place_name": "갱신된 장소명"},
        ),
    ]
    changed_plan = await preview_curation_import(migrated_session, rows=changed_rows)
    changed = await import_curation_rows(
        migrated_session, rows=changed_rows, actor="importer"
    )
    after = await get_curation_item(
        migrated_session, collection_id=collection_id, curation_item_id=item_id
    )
    assert after is not None
    assert after.place_name == "갱신된 장소명"
    assert after.status == "rejected"
    assert after.curation_relation == "primary_stop"
    assert after.reuse_policy == "blocked"
    assert changed_plan.updated == 1
    assert changed["updated"] == 1

    # 5) authoritative source에서 일시 누락되면 membership/override는 남고 공개만 빠진다.
    sibling_rows = [
        ResolvedCurationImportRow(
            row_number=3,
            source_item_key="reimport-b",
            feature_id=None,
            sort_order=2,
            metadata={"ordinal": 2},
            **{**common, "place_name": "두 번째 장소"},
        ),
    ]
    removal_plan = await preview_curation_import(migrated_session, rows=sibling_rows)
    omitted = await import_curation_rows(
        migrated_session,
        rows=sibling_rows,
        actor="importer",
    )
    assert [item.curation_item_id for item in removal_plan.removals] == [item_id]
    assert omitted["removed"] == 1
    assert omitted["removals"][0].source_present is True
    assert (
        await get_curation_item(
            migrated_session,
            collection_id=collection_id,
            curation_item_id=item_id,
        )
        is None
    )
    missing = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
        include_archived=True,
    )
    assert missing is not None
    assert missing.source_present is False
    assert missing.status == "rejected"
    assert missing.curation_relation == "primary_stop"
    assert missing.reuse_policy == "blocked"
    current_collection = await get_curation_collection(
        migrated_session,
        collection_id=collection_id,
    )
    assert current_collection is not None
    assert current_collection[0].item_count == 1
    assert [item.external_item_id for item in current_collection[1]] == ["reimport-b"]
    audit_collection = await get_curation_collection(
        migrated_session,
        collection_id=collection_id,
        include_archived=True,
    )
    assert audit_collection is not None
    assert {item.external_item_id for item in audit_collection[1]} == {
        "reimport-a",
        "reimport-b",
    }

    # 6) 재등장은 source presence와 provider 파생 필드만 복원한다.
    reappearing_rows = [*changed_rows, *sibling_rows]
    reappearance_plan = await preview_curation_import(
        migrated_session,
        rows=reappearing_rows,
    )
    reappeared = await import_curation_rows(
        migrated_session,
        rows=reappearing_rows,
        actor="importer",
    )
    restored = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
    )
    assert reappearance_plan.updated == 1
    assert reappeared["updated"] == 1
    assert restored is not None
    assert restored.source_present is True
    assert restored.status == "rejected"
    assert restored.curation_relation == "primary_stop"
    assert restored.reuse_policy == "blocked"

    # 7) operator archive tombstone은 같은 authoritative identity가 다시 와도 부활하지 않는다.
    archived = await archive_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
        actor="operator",
    )
    assert archived is not None
    archived_plan = await preview_curation_import(
        migrated_session,
        rows=reappearing_rows,
    )
    after_archive = await import_curation_rows(
        migrated_session,
        rows=reappearing_rows,
        actor="importer",
    )
    assert archived_plan.inserted == 0
    assert archived_plan.updated == 0
    assert after_archive["inserted"] == 0
    assert after_archive["updated"] == 0
    active_count = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM feature.curation_items "
                "WHERE collection_id = CAST(:collection_id AS uuid) "
                "AND external_item_id = 'reimport-a' "
                "AND archived_at IS NULL"
            ),
            {"collection_id": collection_id},
        )
    ).scalar_one()
    assert active_count == 0
    tombstone = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
        include_archived=True,
    )
    assert tombstone is not None
    assert tombstone.status == "archived"


async def test_source_absent_included_item_is_hidden_and_can_be_archived(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, marker_icon, marker_color
            ) VALUES (
                'feature:source-absent', 'place', '원천 누락 장소',
                '01070100', 'place', 'P-01'
            )
            """
        )
    )
    common = {
        "collection_key": "source-absent:2026",
        "theme_slug": "source-absent",
        "theme_name": "원천 누락 테스트",
        "theme_group": "test",
        "title": "원천 누락 테스트",
        "edition_key": "2026",
        "provider_dataset_id": await _dataset_id(
            migrated_session, "source-absent-provider", "source-absent-dataset"
        ),
        "source_name": "원천 누락 출처",
        "source_url": None,
        "item_title": None,
        "item_summary": None,
        "address_hint": None,
    }
    present_row = ResolvedCurationImportRow(
        row_number=2,
        source_item_key="source-absent-a",
        feature_id="feature:source-absent",
        sort_order=1,
        metadata={},
        place_name="원천 누락 장소",
        **common,
    )
    sibling_row = ResolvedCurationImportRow(
        row_number=3,
        source_item_key="source-absent-b",
        feature_id=None,
        sort_order=2,
        metadata={},
        place_name="남은 장소",
        **common,
    )
    await import_curation_rows(
        migrated_session,
        rows=[present_row, sibling_row],
        actor="importer",
    )
    identity = (
        await migrated_session.execute(
            text(
                "SELECT i.collection_id::text, i.curation_item_id::text "
                "FROM feature.curation_items AS i "
                "JOIN feature.curation_collections AS c "
                "ON c.collection_id = i.collection_id "
                "WHERE c.collection_key = 'source-absent:2026' "
                "AND i.external_item_id = 'source-absent-a'"
            )
        )
    ).one()

    omitted = await import_curation_rows(
        migrated_session,
        rows=[sibling_row],
        actor="importer",
    )
    assert omitted["removed"] == 1
    public_collection = await get_curation_collection(
        migrated_session,
        collection_id=identity[0],
        public_only=True,
    )
    assert public_collection is not None
    assert [item.external_item_id for item in public_collection[1]] == [
        "source-absent-b"
    ]
    assert await get_feature_curation_group(
        migrated_session,
        feature_id="feature:source-absent",
        public_only=True,
    ) is None
    assert await list_curation_items_by_feature_ids(
        migrated_session,
        feature_ids=["feature:source-absent"],
        public_only=True,
    ) == {}
    groups, cursor = await list_feature_curation_groups(
        migrated_session,
        public_only=True,
        page_size=100,
    )
    assert all(group.feature_id != "feature:source-absent" for group in groups)
    assert cursor is None

    archived = await archive_curation_item(
        migrated_session,
        collection_id=identity[0],
        curation_item_id=identity[1],
        actor="operator",
    )
    assert archived is not None
    assert archived.source_present is False
    assert archived.status == "archived"
    replay = await import_curation_rows(
        migrated_session,
        rows=[present_row, sibling_row],
        actor="importer",
    )
    assert replay["inserted"] == 0
    assert replay["updated"] == 0
    assert (
        await get_curation_item(
            migrated_session,
            collection_id=identity[0],
            curation_item_id=identity[1],
            include_archived=True,
        )
    ) == archived


async def test_item_identity_patch_cannot_cross_resolved_or_unresolved_tombstone(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    collection = await create_curation_collection(
        migrated_session,
        collection_key="patch-tombstone:2026",
        theme_id=theme_id,
        source_id=source_id,
        title="PATCH tombstone 테스트",
    )
    resolved_tombstone, _ = await add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=_FEATURE_ID,
        external_item_id="resolved-tombstone",
    )
    await archive_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        curation_item_id=resolved_tombstone.curation_item_id,
    )
    resolved_active, _ = await add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=_FEATURE_ID,
        external_item_id="resolved-active",
    )
    with pytest.raises(ValueError, match="identity는 재사용"):
        await update_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            curation_item_id=resolved_active.curation_item_id,
            updates={"external_item_id": "resolved-tombstone"},
        )

    unresolved_tombstone, _ = await add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=None,
        external_item_id="unresolved-tombstone",
        place_name="미연결 tombstone",
    )
    await archive_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        curation_item_id=unresolved_tombstone.curation_item_id,
    )
    unresolved_active, _ = await add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=None,
        external_item_id="unresolved-active",
        place_name="미연결 active",
    )
    with pytest.raises(ValueError, match="identity는 재사용"):
        await update_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            curation_item_id=unresolved_active.curation_item_id,
            updates={"external_item_id": "unresolved-tombstone", "feature_id": None},
        )


async def test_legacy_writer_preserves_operator_override_and_tombstone(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    legacy_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, curation_status,
                        selection_origin, display_title, display_summary,
                        curation_relation, reuse_policy
                    ) VALUES (
                        CAST(:theme_id AS uuid), :feature_id,
                        CAST(:source_id AS uuid), 'curated', 'source_rule',
                        'legacy trigger', 'provider summary',
                        'nearby_option', 'manual_review'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                },
            )
        ).scalar_one()
    )
    legacy_item = (
        await migrated_session.execute(
            text(
                "SELECT collection_id::text, curation_item_id::text "
                "FROM feature.curation_items "
                "WHERE curation_item_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": legacy_id},
        )
    ).one()
    await update_curation_item(
        migrated_session,
        collection_id=legacy_item[0],
        curation_item_id=legacy_item[1],
        updates={
            "status": "rejected",
            "curation_relation": "primary_stop",
            "reuse_policy": "blocked",
        },
        actor="operator",
    )
    legacy_after_canonical = (
        await migrated_session.execute(
            text(
                "SELECT curation_status, curation_relation, reuse_policy, "
                "operator_updated_by, operator_updated_at IS NOT NULL "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": legacy_id},
        )
    ).one()
    assert legacy_after_canonical == (
        "rejected",
        "primary_stop",
        "blocked",
        "operator",
        True,
    )
    public_page = await curated_repo.list_curated_features(
        migrated_session,
        theme_id=theme_id,
    )
    assert public_page.items == ()

    await curated_repo.set_curated_feature_status(
        migrated_session,
        curated_feature_id=legacy_id,
        curation_status="curated",
        actor="legacy-operator",
    )
    await migrated_session.execute(
        text(
            "UPDATE feature.curation_items "
            "SET item_summary = 'canonical newer source', sort_order = 77, "
            "source_updated_at = clock_timestamp() "
            "WHERE curation_item_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": legacy_id},
    )
    await curated_repo.update_curated_feature(
        migrated_session,
        curated_feature_id=legacy_id,
        updates={
            "curation_relation": "food_stop",
            "reuse_policy": "allowed",
        },
        actor="legacy-patch-operator",
    )
    canonical_after_legacy = await get_curation_item(
        migrated_session,
        collection_id=legacy_item[0],
        curation_item_id=legacy_item[1],
    )
    assert canonical_after_legacy is not None
    assert canonical_after_legacy.status == "included"
    assert canonical_after_legacy.curation_relation == "food_stop"
    assert canonical_after_legacy.reuse_policy == "allowed"
    assert canonical_after_legacy.item_summary == "canonical newer source"
    assert canonical_after_legacy.sort_order == 77
    assert (
        await migrated_session.execute(
            text(
                "SELECT operator_updated_by "
                "FROM feature.curation_items "
                "WHERE curation_item_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": legacy_id},
        )
    ).scalar_one() == "legacy-patch-operator"
    operator_revision = (
        await migrated_session.execute(
            text(
                "SELECT operator_updated_by, operator_updated_at "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": legacy_id},
        )
    ).one()
    await curated_repo.update_curated_feature(
        migrated_session,
        curated_feature_id=legacy_id,
        updates={"display_summary": "source-only legacy patch"},
        actor="source-only-admin",
    )
    assert (
        await migrated_session.execute(
            text(
                "SELECT operator_updated_by, operator_updated_at "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": legacy_id},
        )
    ).one() == operator_revision
    with pytest.raises(ValueError, match="legacy writer"):
        await update_curation_item(
            migrated_session,
            collection_id=legacy_item[0],
            curation_item_id=legacy_item[1],
            updates={"item_summary": "canonical source drift"},
            actor="canonical-source-admin",
        )

    await update_curation_item(
        migrated_session,
        collection_id=legacy_item[0],
        curation_item_id=legacy_item[1],
        updates={
            "status": "rejected",
            "curation_relation": "primary_stop",
            "reuse_policy": "blocked",
        },
        actor="operator",
    )
    await migrated_session.execute(
        text(
            "UPDATE feature.curated_features "
            "SET display_summary = 'provider changed', rank_score = 42, "
            "curation_relation = 'food_stop', reuse_policy = 'allowed', "
            "updated_at = clock_timestamp() "
            "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": legacy_id},
    )
    preserved = await get_curation_item(
        migrated_session,
        collection_id=legacy_item[0],
        curation_item_id=legacy_item[1],
    )
    assert preserved is not None
    assert preserved.source_present is True
    assert preserved.status == "rejected"
    assert preserved.curation_relation == "primary_stop"
    assert preserved.reuse_policy == "blocked"
    assert preserved.item_summary == "provider changed"
    assert preserved.sort_order == 42

    archived = await archive_curation_item(
        migrated_session,
        collection_id=legacy_item[0],
        curation_item_id=legacy_item[1],
        actor="operator",
    )
    assert archived is not None
    legacy_archived = (
        await migrated_session.execute(
            text(
                "SELECT curation_status, archived_at IS NOT NULL "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": legacy_id},
        )
    ).one()
    assert legacy_archived == ("archived", True)
    await migrated_session.execute(
        text(
            "UPDATE feature.curated_features "
            "SET display_summary = 'must not resurrect', "
            "updated_at = clock_timestamp() "
            "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": legacy_id},
    )
    await migrated_session.execute(
        text(
            "DELETE FROM feature.curated_features "
            "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": legacy_id},
    )
    tombstone = await get_curation_item(
        migrated_session,
        collection_id=legacy_item[0],
        curation_item_id=legacy_item[1],
        include_archived=True,
    )
    assert tombstone is not None
    assert tombstone.status == "archived"
    assert tombstone.item_summary == "provider changed"


async def test_legacy_identity_move_does_not_overwrite_occupied_target(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    fetched_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    entity = SourceEntityRow(
        source_entity_key="curation-occupied-entity",
        provider_dataset_id=await _dataset_id(
            migrated_session, "python-mcst-api", "tourism-100-test"
        ),
        source_entity_type="place",
        source_entity_id="curation-occupied",
        first_seen_at=fetched_at,
        last_seen_at=fetched_at,
    )
    migrated_session.add(entity)
    await migrated_session.flush()
    for key, payload_hash in (
        ("curation-occupied-original", _payload_hash("curation-occupied-original")),
        ("curation-occupied-target", _payload_hash("curation-occupied-target")),
    ):
        migrated_session.add(
            SourceRecordRow(
                source_record_key=key,
                source_entity_key=entity.source_entity_key,
                raw_payload_hash=payload_hash,
                raw_data={},
                fetched_at=fetched_at,
            )
        )
    await migrated_session.flush()

    async def inject_reserved_marker_with_fake_capability() -> None:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "SELECT set_config("
                    "'kortravelmap.curation_sync_mode',"
                    "'merge_explicit',"
                    "true"
                    ")"
                )
            )
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, curation_status,
                        selection_origin, display_title, metadata
                    ) VALUES (
                        CAST(:theme_id AS uuid), :feature_id,
                        CAST(:source_id AS uuid), 'curated', 'source_rule',
                        'reserved marker injection',
                        '{"merge_projection_detached": true}'::jsonb
                    )
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                },
            )

    with pytest.raises(DBAPIError, match="reserved"):
        await inject_reserved_marker_with_fake_capability()

    legacy_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, source_record_key,
                        curation_status, selection_origin, display_title
                    ) VALUES (
                        CAST(:theme_id AS uuid), :feature_id,
                        CAST(:source_id AS uuid), 'curation-occupied-original',
                        'curated', 'source_rule', 'occupied identity'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                },
            )
        ).scalar_one()
    )
    collection_id = str(
        (
            await migrated_session.execute(
                text(
                    "SELECT collection_id::text "
                    "FROM feature.curation_items "
                    "WHERE curation_item_id = CAST(:legacy_id AS uuid)"
                ),
                {"legacy_id": legacy_id},
            )
        ).scalar_one()
    )
    occupied, inserted = await add_curation_item(
        migrated_session,
        collection_id=collection_id,
        feature_id=_FEATURE_ID,
        source_record_key="curation-occupied-target",
        external_item_id="curation-occupied-target",
        status="included",
        curation_relation="food_stop",
        reuse_policy="allowed",
        actor="occupied-owner",
    )
    assert inserted is True

    await migrated_session.execute(
        text(
            """
            UPDATE feature.curated_features
            SET source_record_key = 'curation-occupied-target',
                display_summary = 'provider moved identity',
                updated_at = clock_timestamp()
            WHERE curated_feature_id = CAST(:legacy_id AS uuid)
            """
        ),
        {"legacy_id": legacy_id},
    )
    state = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    (SELECT source_present
                     FROM feature.curation_items
                     WHERE curation_item_id = CAST(:legacy_id AS uuid)),
                    (SELECT source_present
                     FROM feature.curation_items
                     WHERE curation_item_id = CAST(:occupied_id AS uuid)),
                    (SELECT curation_relation
                     FROM feature.curation_items
                     WHERE curation_item_id = CAST(:occupied_id AS uuid)),
                    (SELECT reuse_policy
                     FROM feature.curation_items
                     WHERE curation_item_id = CAST(:occupied_id AS uuid)),
                    (SELECT metadata
                        @> '{"merge_projection_detached": true}'::jsonb
                     FROM feature.curated_features
                     WHERE curated_feature_id = CAST(:legacy_id AS uuid))
                """
            ),
            {
                "legacy_id": legacy_id,
                "occupied_id": occupied.curation_item_id,
            },
        )
    ).one()
    assert state == (False, True, "food_stop", "allowed", True)
    assert (
        await curated_repo.list_curated_features(
            migrated_session,
            theme_id=theme_id,
            public_only=True,
        )
    ).items == ()

    blocked = await curated_repo.update_curated_feature(
        migrated_session,
        curated_feature_id=legacy_id,
        updates={
            "curation_status": "curated",
            "metadata": {},
        },
        actor="detached-attacker",
    )
    assert blocked is None

    await migrated_session.execute(
        text(
            """
            UPDATE feature.curated_features
            SET curation_status = 'curated',
                archived_at = NULL,
                metadata = '{}'::jsonb,
                updated_at = clock_timestamp()
            WHERE curated_feature_id = CAST(:legacy_id AS uuid)
            """
        ),
        {"legacy_id": legacy_id},
    )
    detached_projection = (
        await migrated_session.execute(
            text(
                """
                SELECT curation_status, archived_at IS NOT NULL,
                       metadata @> '{"merge_projection_detached": true}'::jsonb
                FROM feature.curated_features
                WHERE curated_feature_id = CAST(:legacy_id AS uuid)
                """
            ),
            {"legacy_id": legacy_id},
        )
    ).one()
    assert detached_projection == ("archived", True, True)
    await migrated_session.execute(
        text(
            "DELETE FROM feature.curated_features "
            "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": legacy_id},
    )
    final_state = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    (SELECT source_present
                     FROM feature.curation_items
                     WHERE curation_item_id = CAST(:legacy_id AS uuid)),
                    (SELECT status
                     FROM feature.curation_items
                     WHERE curation_item_id = CAST(:occupied_id AS uuid)),
                    (SELECT curation_relation
                     FROM feature.curation_items
                     WHERE curation_item_id = CAST(:occupied_id AS uuid))
                """
            ),
            {
                "legacy_id": legacy_id,
                "occupied_id": occupied.curation_item_id,
            },
        )
    ).one()
    assert final_state == (False, "included", "food_stop")


async def test_manual_collection_keys_cannot_block_legacy_projection_creation(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    legacy_id = str(uuid4())
    second_legacy_id = str(uuid4())
    second_feature_id = f"feature:manual-key-collision-{uuid4().hex}"
    title = "manual key collision"
    base_key = str(
        (
            await migrated_session.execute(
                text(
                    "SELECT 'legacy:' || CAST(:theme_id AS uuid)::text || ':' || "
                    "CAST(:source_id AS uuid)::text || ':' || md5(:title)"
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "title": title,
                },
            )
        ).scalar_one()
    )
    await migrated_session.execute(
        text(
            """
            -- `status='active'`의 3축 등가물은 (active, published, valid)이고,
            -- 그것이 0095가 세 컬럼에 준 기본값 그대로다. 이 테스트가 재는 것은
            -- collection key 충돌이지 feature 상태가 아니므로, 축을 다시 적지 않고
            -- 기본값에 맡겨 잡음을 없앤다(이 파일의 다른 seed와 같은 방식).
            INSERT INTO feature.features (
                feature_id, kind, name, category
            ) VALUES (
                :feature_id, 'place', 'manual key collision second feature',
                '01070100'
            )
            """
        ),
        {"feature_id": second_feature_id},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.curation_collections (
                collection_key, theme_id, title
            ) VALUES
                (
                    :base_key,
                    CAST(:theme_id AS uuid),
                    'manual runtime base collision'
                ),
                (
                    :split_key,
                    CAST(:theme_id AS uuid),
                    'manual runtime split collision'
                )
            """
        ),
        {
            "base_key": base_key,
            "split_key": f"{base_key}:split:legacy",
            "theme_id": theme_id,
        },
    )

    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.curated_features (
                curated_feature_id, theme_id, feature_id, source_id,
                curation_status, selection_origin, display_title
            ) VALUES
                (
                    CAST(:legacy_id AS uuid),
                    CAST(:theme_id AS uuid),
                    :feature_id,
                    CAST(:source_id AS uuid),
                    'curated',
                    'source_rule',
                    :title
                ),
                (
                    CAST(:second_legacy_id AS uuid),
                    CAST(:theme_id AS uuid),
                    :second_feature_id,
                    CAST(:source_id AS uuid),
                    'curated',
                    'source_rule',
                    :title
                )
            """
        ),
        {
            "legacy_id": legacy_id,
            "second_legacy_id": second_legacy_id,
            "theme_id": theme_id,
            "feature_id": _FEATURE_ID,
            "second_feature_id": second_feature_id,
            "source_id": source_id,
            "title": title,
        },
    )

    keys = (
        await migrated_session.execute(
            text(
                """
                SELECT collection.collection_key, collection.title
                FROM feature.curation_collections AS collection
                WHERE collection.collection_key IN (
                        :base_key,
                        :split_key,
                        :resolved_key
                    )
                ORDER BY collection.collection_key
                """
            ),
            {
                "base_key": base_key,
                "split_key": f"{base_key}:split:legacy",
                "resolved_key": f"{base_key}:split:legacy:conflict:1",
            },
        )
    ).all()
    assert keys == [
        (base_key, "manual runtime base collision"),
        (
            f"{base_key}:split:legacy",
            "manual runtime split collision",
        ),
        (
            f"{base_key}:split:legacy:conflict:1",
            title,
        ),
    ]
    assert (
        await migrated_session.execute(
            text(
                """
                SELECT count(*)
                FROM feature.curation_items AS item
                JOIN feature.curation_collections AS collection
                  ON collection.collection_id = item.collection_id
                WHERE collection.collection_key = :resolved_key
                """
            ),
            {"resolved_key": f"{base_key}:split:legacy:conflict:1"},
        )
    ).scalar_one() == 2


async def test_legacy_reinsert_restores_stable_source_identity_without_new_uuid(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    fetched_at = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
    entity = SourceEntityRow(
        source_entity_key="curation-reinsert-entity",
        provider_dataset_id=await _dataset_id(
            migrated_session, "python-mcst-api", "tourism-100-test"
        ),
        source_entity_type="place",
        source_entity_id="curation-reinsert",
        first_seen_at=fetched_at,
        last_seen_at=fetched_at,
    )
    migrated_session.add(entity)
    await migrated_session.flush()
    migrated_session.add(
        SourceRecordRow(
            source_record_key="curation-reinsert-record",
            source_entity_key=entity.source_entity_key,
            raw_payload_hash=_payload_hash("curation-reinsert"),
            raw_data={},
            fetched_at=fetched_at,
        )
    )
    await migrated_session.flush()
    # T-VN-33: 현재 record 포인터는 entity가 아니라 head가 소유한다.
    migrated_session.add(
        SourceEntityHeadRow(
            source_entity_key=entity.source_entity_key,
            current_source_record_key="curation-reinsert-record",
            observed_at=fetched_at,
        )
    )
    await migrated_session.flush()

    legacy_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, source_record_key,
                        curation_status, selection_origin, display_title
                    ) VALUES (
                        CAST(:theme_id AS uuid), :feature_id,
                        CAST(:source_id AS uuid), :source_record_key,
                        'curated', 'source_rule', 'stable reinsert'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                    "source_record_key": "curation-reinsert-record",
                },
            )
        ).scalar_one()
    )
    collection_id = str(
        (
            await migrated_session.execute(
                text(
                    "SELECT collection_id::text "
                    "FROM feature.curation_items "
                    "WHERE curation_item_id = CAST(:legacy_id AS uuid)"
                ),
                {"legacy_id": legacy_id},
            )
        ).scalar_one()
    )
    await migrated_session.execute(
        text(
            "UPDATE feature.curation_items "
            "SET status = 'candidate', operator_updated_by = NULL, "
            "operator_updated_at = NULL "
            "WHERE curation_item_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": legacy_id},
    )
    await migrated_session.execute(
        text(
            "DELETE FROM feature.curated_features "
            "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": legacy_id},
    )
    candidate_replacement_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, source_record_key,
                        curation_status, selection_origin, display_title
                    ) VALUES (
                        CAST(:theme_id AS uuid), :feature_id,
                        CAST(:source_id AS uuid), :source_record_key,
                        'curated', 'source_rule', 'stable reinsert'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                    "source_record_key": "curation-reinsert-record",
                },
            )
        ).scalar_one()
    )
    assert (
        await migrated_session.execute(
            text(
                "SELECT curation_status, operator_updated_at IS NULL "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": candidate_replacement_id},
        )
    ).one() == ("candidate", True)
    assert (
        await curated_repo.list_curated_features(
            migrated_session,
            theme_id=theme_id,
        )
    ).items == ()
    await migrated_session.execute(
        text(
            "DELETE FROM feature.curated_features "
            "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": candidate_replacement_id},
    )
    await update_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=legacy_id,
        updates={
            "status": "rejected",
            "curation_relation": "primary_stop",
            "reuse_policy": "blocked",
        },
        actor="operator",
    )
    await migrated_session.execute(
        text(
            "DELETE FROM feature.curated_features "
            "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": legacy_id},
    )
    absent = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=legacy_id,
        include_archived=True,
    )
    assert absent is not None
    assert absent.source_present is False

    replacement_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, source_record_key,
                        curation_status, selection_origin, display_title
                    ) VALUES (
                        CAST(:theme_id AS uuid), :feature_id,
                        CAST(:source_id AS uuid), :source_record_key,
                        'curated', 'source_rule', 'stable reinsert'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                    "source_record_key": "curation-reinsert-record",
                },
            )
        ).scalar_one()
    )
    assert replacement_id != legacy_id
    replacement_projection = (
        await migrated_session.execute(
            text(
                "SELECT curation_status, curation_relation, reuse_policy, "
                "operator_updated_by "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:replacement_id AS uuid)"
            ),
            {"replacement_id": replacement_id},
        )
    ).one()
    assert replacement_projection == (
        "rejected",
        "primary_stop",
        "blocked",
        "operator",
    )
    assert (
        await curated_repo.list_curated_features(
            migrated_session,
            theme_id=theme_id,
        )
    ).items == ()
    restored = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=legacy_id,
    )
    assert restored is not None
    assert restored.source_present is True
    assert restored.status == "rejected"
    assert restored.curation_relation == "primary_stop"
    assert restored.reuse_policy == "blocked"
    assert (
        await migrated_session.execute(
            text(
                "SELECT legacy_projection_id::text "
                "FROM feature.curation_items "
                "WHERE curation_item_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": legacy_id},
        )
    ).scalar_one() == replacement_id
    await update_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=legacy_id,
        updates={"curation_relation": "bookstore_stop"},
        actor="post-reinsert-operator",
    )
    replacement_legacy = (
        await migrated_session.execute(
            text(
                "SELECT curation_status, curation_relation, reuse_policy, "
                "operator_updated_by "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:replacement_id AS uuid)"
            ),
            {"replacement_id": replacement_id},
        )
    ).one()
    assert replacement_legacy == (
        "rejected",
        "bookstore_stop",
        "blocked",
        "post-reinsert-operator",
    )
    manual_collection = await create_curation_collection(
        migrated_session,
        collection_key="manual-cross-collection",
        theme_id=theme_id,
        source_id=source_id,
        title="동일 theme/source의 수동 컬렉션",
    )
    manual_item, inserted = await add_curation_item(
        migrated_session,
        collection_id=manual_collection.collection_id,
        feature_id=_FEATURE_ID,
        source_record_key="curation-reinsert-record",
        external_item_id="curation-reinsert-record",
        place_name="수동 컬렉션 장소",
        actor="manual-collection-writer",
    )
    assert inserted is True
    changed_manual = await update_curation_item(
        migrated_session,
        collection_id=manual_collection.collection_id,
        curation_item_id=manual_item.curation_item_id,
        updates={
            "item_title": "수동 컬렉션에서만 수정",
            "curation_relation": "food_stop",
        },
        actor="manual-collection-operator",
    )
    assert changed_manual is not None
    assert changed_manual.item_title == "수동 컬렉션에서만 수정"
    assert changed_manual.curation_relation == "food_stop"
    unchanged_legacy = (
        await migrated_session.execute(
            text(
                "SELECT curation_status, curation_relation, reuse_policy, "
                "operator_updated_by "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:replacement_id AS uuid)"
            ),
            {"replacement_id": replacement_id},
        )
    ).one()
    assert unchanged_legacy == replacement_legacy
    identity_rows = (
        await migrated_session.execute(
            text(
                "SELECT curation_item_id::text "
                "FROM feature.curation_items "
                "WHERE collection_id = CAST(:collection_id AS uuid) "
                "AND external_item_id = :source_record_key "
                "AND feature_id = :feature_id"
            ),
            {
                "collection_id": collection_id,
                "source_record_key": "curation-reinsert-record",
                "feature_id": _FEATURE_ID,
            },
        )
    ).scalars().all()
    assert identity_rows == [legacy_id]
    await migrated_session.execute(
        text(
            "DELETE FROM feature.curated_features "
            "WHERE curated_feature_id = CAST(:replacement_id AS uuid)"
        ),
        {"replacement_id": replacement_id},
    )
    deleted_again = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=legacy_id,
        include_archived=True,
    )
    assert deleted_again is not None
    assert deleted_again.source_present is False
    assert (
        await get_curation_item(
            migrated_session,
            collection_id=collection_id,
            curation_item_id=legacy_id,
        )
        is None
    )

    tombstone_source_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, source_record_key,
                        curation_status, selection_origin, display_title
                    ) VALUES (
                        CAST(:theme_id AS uuid), :feature_id,
                        CAST(:source_id AS uuid), :source_record_key,
                        'curated', 'source_rule', 'stable reinsert'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                    "source_record_key": "curation-reinsert-record",
                },
            )
        ).scalar_one()
    )
    archived = await archive_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=legacy_id,
        actor="archive-operator",
    )
    assert archived is not None
    await migrated_session.execute(
        text(
            "DELETE FROM feature.curated_features "
            "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
        ),
        {"legacy_id": tombstone_source_id},
    )
    tombstone_replacement_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, source_record_key,
                        curation_status, selection_origin, display_title
                    ) VALUES (
                        CAST(:theme_id AS uuid), :feature_id,
                        CAST(:source_id AS uuid), :source_record_key,
                        'curated', 'source_rule', 'stable reinsert renamed'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                    "source_record_key": "curation-reinsert-record",
                },
            )
        ).scalar_one()
    )
    tombstone_projection = (
        await migrated_session.execute(
            text(
                "SELECT curation_status, archived_at IS NOT NULL "
                "FROM feature.curated_features "
                "WHERE curated_feature_id = CAST(:legacy_id AS uuid)"
            ),
            {"legacy_id": tombstone_replacement_id},
        )
    ).one()
    assert tombstone_projection == ("archived", True)
    identity = (
        await migrated_session.execute(
            text(
                "SELECT curation_item_id::text, status, archived_at IS NOT NULL "
                "FROM feature.curation_items "
                "WHERE collection_id = CAST(:collection_id AS uuid) "
                "AND external_item_id = 'curation-reinsert-record' "
                "AND feature_id = :feature_id"
            ),
            {"collection_id": collection_id, "feature_id": _FEATURE_ID},
        )
    ).one()
    assert identity == (legacy_id, "archived", True)
    durable_identity_count = (
        await migrated_session.execute(
            text(
                """
                SELECT count(*)
                FROM feature.curation_items AS item
                JOIN feature.curation_collections AS collection
                  ON collection.collection_id = item.collection_id
                WHERE collection.theme_id = CAST(:theme_id AS uuid)
                  AND collection.source_id = CAST(:source_id AS uuid)
                  AND collection.metadata @>
                      '{"migrated_from": "feature.curated_features"}'::jsonb
                  AND item.external_item_id = 'curation-reinsert-record'
                  AND item.feature_id = :feature_id
                """
            ),
            {
                "theme_id": theme_id,
                "source_id": source_id,
                "feature_id": _FEATURE_ID,
            },
        )
    ).scalar_one()
    assert durable_identity_count == 1
    assert (
        await curated_repo.list_curated_features(
            migrated_session,
            theme_id=theme_id,
        )
    ).items == ()


async def test_legacy_reinsert_without_source_record_keeps_operator_tombstone(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    legacy_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id,
                        curation_status, selection_origin, display_title
                    ) VALUES (
                        CAST(:theme_id AS uuid),
                        :feature_id,
                        CAST(:source_id AS uuid),
                        'curated',
                        'source_rule',
                        'source record 없는 목록'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                },
            )
        ).scalar_one()
    )
    item_identity = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    curation_item_id::text,
                    collection_id::text,
                    external_item_id
                FROM feature.curation_items
                WHERE legacy_projection_id = CAST(:legacy_id AS uuid)
                """
            ),
            {"legacy_id": legacy_id},
        )
    ).one()
    archived = await archive_curation_item(
        migrated_session,
        collection_id=item_identity.collection_id,
        curation_item_id=item_identity.curation_item_id,
        actor="null-source-tombstone-operator",
    )
    assert archived is not None
    await migrated_session.execute(
        text(
            """
            DELETE FROM feature.curated_features
            WHERE curated_feature_id = CAST(:legacy_id AS uuid)
            """
        ),
        {"legacy_id": legacy_id},
    )
    replacement_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id,
                        curation_status, selection_origin, display_title
                    ) VALUES (
                        CAST(:theme_id AS uuid),
                        :feature_id,
                        CAST(:source_id AS uuid),
                        'curated',
                        'source_rule',
                        'source record 없는 목록 변경'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "feature_id": _FEATURE_ID,
                },
            )
        ).scalar_one()
    )
    projection = (
        await migrated_session.execute(
            text(
                """
                SELECT curation_status, archived_at IS NOT NULL
                FROM feature.curated_features
                WHERE curated_feature_id = CAST(:replacement_id AS uuid)
                """
            ),
            {"replacement_id": replacement_id},
        )
    ).one()
    durable_items = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    item.curation_item_id::text,
                    item.external_item_id,
                    item.status,
                    item.source_present,
                    item.legacy_projection_id::text
                FROM feature.curation_items AS item
                JOIN feature.curation_collections AS collection
                  ON collection.collection_id = item.collection_id
                WHERE collection.theme_id = CAST(:theme_id AS uuid)
                  AND collection.source_id = CAST(:source_id AS uuid)
                  AND collection.metadata @>
                      '{"migrated_from": "feature.curated_features"}'::jsonb
                  AND item.feature_id = :feature_id
                """
            ),
            {
                "theme_id": theme_id,
                "source_id": source_id,
                "feature_id": _FEATURE_ID,
            },
        )
    ).all()
    assert projection == ("archived", True)
    assert durable_items == [
        (
            item_identity.curation_item_id,
            item_identity.external_item_id,
            "archived",
            False,
            replacement_id,
        )
    ]


async def test_authoritative_reimport_does_not_resurrect_unresolved_archive(
    migrated_session: AsyncSession,
) -> None:
    """feature_id NULL identity도 provider 필드 변경으로 tombstone을 우회하지 못한다."""
    common = {
        "collection_key": "csv-archive-null:2026",
        "theme_slug": "csv-archive-null",
        "theme_name": "CSV archive NULL 테스트",
        "theme_group": "test",
        "title": "CSV archive NULL 테스트",
        "edition_key": "2026",
        "provider_dataset_id": await _dataset_id(
            migrated_session, "csv-archive-provider", "csv-archive-dataset"
        ),
        "source_name": "CSV archive 출처",
        "source_url": None,
        "source_item_key": "unresolved-a",
        "feature_id": None,
        "address_hint": None,
        "sort_order": 1,
        "item_title": None,
        "item_summary": None,
    }
    original_rows = [
        ResolvedCurationImportRow(
            row_number=2,
            place_name="미해결 장소",
            metadata={"revision": 1},
            **common,
        )
    ]
    await import_curation_rows(migrated_session, rows=original_rows, actor="importer")
    ids = (
        await migrated_session.execute(
            text(
                "SELECT i.collection_id::text AS collection_id, "
                "i.curation_item_id::text AS curation_item_id "
                "FROM feature.curation_items AS i "
                "JOIN feature.curation_collections AS c "
                "ON c.collection_id = i.collection_id "
                "WHERE c.collection_key = 'csv-archive-null:2026'"
            )
        )
    ).mappings().one()
    archived = await archive_curation_item(
        migrated_session,
        collection_id=ids["collection_id"],
        curation_item_id=ids["curation_item_id"],
        actor="operator",
    )
    assert archived is not None

    changed_rows = [
        ResolvedCurationImportRow(
            row_number=2,
            place_name="변경된 미해결 장소",
            metadata={"revision": 2},
            **common,
        )
    ]
    plan = await preview_curation_import(migrated_session, rows=changed_rows)
    result = await import_curation_rows(
        migrated_session,
        rows=changed_rows,
        actor="importer",
    )
    assert plan.inserted == 0
    assert plan.updated == 0
    assert result["inserted"] == 0
    assert result["updated"] == 0
    row = (
        await migrated_session.execute(
            text(
                "SELECT place_name, metadata, status, archived_at IS NOT NULL AS archived "
                "FROM feature.curation_items "
                "WHERE curation_item_id = CAST(:curation_item_id AS uuid)"
            ),
            {"curation_item_id": ids["curation_item_id"]},
        )
    ).mappings().one()
    assert row["place_name"] == "미해결 장소"
    assert row["metadata"] == {"revision": 1}
    assert row["status"] == "archived"
    assert row["archived"] is True


async def test_theme_upsert_fallback_sees_concurrent_identical_insert(
    migrated_engine: AsyncEngine,
) -> None:
    """ON CONFLICT가 본 새 row를 다음 READ COMMITTED statement에서 회수한다."""

    from sqlalchemy.ext.asyncio import AsyncSession

    suffix = uuid4().hex
    theme_slug = f"concurrent-theme-{suffix}"
    first_session = AsyncSession(migrated_engine, expire_on_commit=False)
    second_session = AsyncSession(migrated_engine, expire_on_commit=False)
    try:
        await first_session.begin()
        first_id = await upsert_curation_theme(
            first_session,
            theme_slug=theme_slug,
            theme_name="동시 생성 테마",
            theme_group="test",
        )
        await second_session.begin()
        second_task = asyncio.create_task(
            upsert_curation_theme(
                second_session,
                theme_slug=theme_slug,
                theme_name="동시 생성 테마",
                theme_group="test",
            )
        )
        await asyncio.sleep(0.2)
        await first_session.commit()
        second_id = await asyncio.wait_for(second_task, timeout=5)
        await second_session.commit()

        assert second_id == first_id
    finally:
        await first_session.close()
        await second_session.close()
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM feature.curated_themes WHERE theme_slug = :theme_slug"),
                {"theme_slug": theme_slug},
            )


async def test_cross_title_legacy_moves_do_not_lock_source_collections_in_reverse(
    migrated_engine: AsyncEngine,
) -> None:
    """A→B/B→A 이동은 target collection 뒤 source parent를 역순 잠그지 않는다."""

    from sqlalchemy.ext.asyncio import AsyncSession

    suffix = uuid4().hex
    feature_a = f"feature:cross-title-a-{suffix}"
    feature_b = f"feature:cross-title-b-{suffix}"
    theme_slug = f"cross-title-{suffix}"
    provider = f"cross-title-provider-{suffix}"

    setup = AsyncSession(migrated_engine, expire_on_commit=False)
    try:
        async with setup.begin():
            await setup.execute(
                text(
                    """
                    -- `status='active'` = (active, published, valid) = 세 컬럼의
                    -- 기본값. 이 테스트는 collection 잠금 순서를 재므로 상태 축을
                    -- 명시할 이유가 없다.
                    INSERT INTO feature.features (
                        feature_id, kind, name, category
                    ) VALUES
                        (:feature_a, 'place', '교차 이동 A', '01070100'),
                        (:feature_b, 'place', '교차 이동 B', '01070100')
                    """
                ),
                {"feature_a": feature_a, "feature_b": feature_b},
            )
            theme_id = str(
                (
                    await setup.execute(
                        text(
                            """
                            INSERT INTO feature.curated_themes (
                                theme_slug, theme_name, theme_group
                            ) VALUES (:theme_slug, '교차 이동', 'test')
                            RETURNING theme_id::text
                            """
                        ),
                        {"theme_slug": theme_slug},
                    )
                ).scalar_one()
            )
            source_id = str(
                (
                    await setup.execute(
                        text(
                            """
                            INSERT INTO feature.curated_sources (
                                provider_dataset_id, source_name, source_kind,
                                update_cycle, provider_status, metadata
                            ) VALUES (
                                :provider_dataset_id, '교차 이동 source',
                                'manual', 'unknown', 'manual_only', '{}'::jsonb
                            )
                            RETURNING source_id::text
                            """
                        ),
                        {
                            "provider_dataset_id": await _dataset_id(
                                setup, provider, "dataset"
                            )
                        },
                    )
                ).scalar_one()
            )
            rows = (
                await setup.execute(
                    text(
                        """
                        INSERT INTO feature.curated_features (
                            theme_id, feature_id, source_id,
                            curation_status, selection_origin, display_title
                        ) VALUES
                            (
                                CAST(:theme_id AS uuid), :feature_a,
                                CAST(:source_id AS uuid),
                                'curated', 'source_rule', '교차 제목 A'
                            ),
                            (
                                CAST(:theme_id AS uuid), :feature_b,
                                CAST(:source_id AS uuid),
                                'curated', 'source_rule', '교차 제목 B'
                            )
                        RETURNING curated_feature_id::text, display_title
                        """
                    ),
                    {
                        "theme_id": theme_id,
                        "source_id": source_id,
                        "feature_a": feature_a,
                        "feature_b": feature_b,
                    },
                )
            ).all()
            legacy_ids = {str(title): str(legacy_id) for legacy_id, title in rows}
            collection_rows = (
                await setup.execute(
                    text(
                        """
                        SELECT collection.collection_id::text, collection.title
                        FROM feature.curation_collections AS collection
                        WHERE collection.theme_id = CAST(:theme_id AS uuid)
                          AND collection.source_id = CAST(:source_id AS uuid)
                        """
                    ),
                    {"theme_id": theme_id, "source_id": source_id},
                )
            ).all()
            collection_ids = {
                str(title): str(collection_id)
                for collection_id, title in collection_rows
            }
    finally:
        await setup.close()

    first = AsyncSession(migrated_engine, expire_on_commit=False)
    second = AsyncSession(migrated_engine, expire_on_commit=False)
    try:
        await first.begin()
        await second.begin()
        for session in (first, second):
            await session.execute(text("SET LOCAL deadlock_timeout = '100ms'"))
            await session.execute(text("SET LOCAL statement_timeout = '5s'"))
        await first.execute(
            text(
                "SELECT collection_id FROM feature.curation_collections "
                "WHERE collection_id = CAST(:collection_id AS uuid) FOR UPDATE"
            ),
            {"collection_id": collection_ids["교차 제목 B"]},
        )
        await second.execute(
            text(
                "SELECT collection_id FROM feature.curation_collections "
                "WHERE collection_id = CAST(:collection_id AS uuid) FOR UPDATE"
            ),
            {"collection_id": collection_ids["교차 제목 A"]},
        )

        async def move(
            session: AsyncSession,
            *,
            legacy_id: str,
            title: str,
        ) -> None:
            await session.execute(
                text(
                    """
                    UPDATE feature.curated_features
                    SET display_title = :title,
                        updated_at = clock_timestamp()
                    WHERE curated_feature_id = CAST(:legacy_id AS uuid)
                    """
                ),
                {"legacy_id": legacy_id, "title": title},
            )

        await asyncio.wait_for(
            asyncio.gather(
                move(
                    first,
                    legacy_id=legacy_ids["교차 제목 A"],
                    title="교차 제목 B",
                ),
                move(
                    second,
                    legacy_id=legacy_ids["교차 제목 B"],
                    title="교차 제목 A",
                ),
            ),
            timeout=4,
        )
        await first.commit()
        await second.commit()
    finally:
        await first.close()
        await second.close()
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_features "
                    "WHERE theme_id = CAST(:theme_id AS uuid)"
                ),
                {"theme_id": theme_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_items "
                    "WHERE collection_id IN ("
                    "SELECT collection_id FROM feature.curation_collections "
                    "WHERE theme_id = CAST(:theme_id AS uuid))"
                ),
                {"theme_id": theme_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_collections "
                    "WHERE theme_id = CAST(:theme_id AS uuid)"
                ),
                {"theme_id": theme_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_sources "
                    "WHERE source_id = CAST(:source_id AS uuid)"
                ),
                {"source_id": source_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_themes "
                    "WHERE theme_id = CAST(:theme_id AS uuid)"
                ),
                {"theme_id": theme_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.features "
                    "WHERE feature_id IN (:feature_a, :feature_b)"
                ),
                {"feature_a": feature_a, "feature_b": feature_b},
            )


async def test_source_and_collection_fallbacks_see_concurrent_identical_insert(
    migrated_engine: AsyncEngine,
) -> None:
    """import 전용 source/collection upsert도 새 statement snapshot을 사용한다."""

    from sqlalchemy.ext.asyncio import AsyncSession

    suffix = uuid4().hex
    theme_slug = f"concurrent-import-foundation-{suffix}"
    provider_dataset_id = await _catalog_dataset_id(
        migrated_engine, f"concurrent-source-{suffix}", "dataset"
    )
    source_params = {
        "provider_dataset_id": provider_dataset_id,
        "source_name": "동시 생성 출처",
        "source_url": None,
    }
    collection_key = f"concurrent-collection:{suffix}"
    first_session = AsyncSession(migrated_engine, expire_on_commit=False)
    second_session = AsyncSession(migrated_engine, expire_on_commit=False)
    try:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as setup:
            theme_id = await upsert_curation_theme(
                setup,
                theme_slug=theme_slug,
                theme_name="동시 생성 기반 테마",
                theme_group="test",
            )
            await setup.commit()

        await first_session.begin()
        source_id = str(
            (
                await first_session.execute(
                    text(
                        """
                        INSERT INTO feature.curated_sources (
                            provider_dataset_id, source_name, source_url,
                            source_kind, update_cycle, provider_status, metadata
                        ) VALUES (
                            :provider_dataset_id, :source_name, :source_url,
                            'manual', 'unknown', 'manual_only', '{}'::jsonb
                        )
                        RETURNING source_id::text
                        """
                    ),
                    source_params,
                )
            ).scalar_one()
        )
        await second_session.begin()
        source_task = asyncio.create_task(
            _upsert_id_with_fallback(
                second_session,
                upsert_sql=_UPSERT_SOURCE_SQL,
                lookup_sql=_GET_SOURCE_ID_BY_DATASET_ID_SQL,
                params=source_params,
                entity="test source",
            )
        )
        await asyncio.sleep(0.2)
        await first_session.commit()
        concurrent_source_id = await asyncio.wait_for(source_task, timeout=5)
        await second_session.commit()
        assert concurrent_source_id == source_id

        collection_params = {
            "collection_key": collection_key,
            "theme_id": theme_id,
            "source_id": source_id,
            "title": "동시 생성 collection",
            "edition_key": "2026",
            "actor": "concurrency-test",
        }
        await first_session.begin()
        collection_id = str(
            (
                await first_session.execute(
                    text(
                        """
                        INSERT INTO feature.curation_collections (
                            collection_key, theme_id, source_id, title,
                            edition_key, status, visibility, metadata,
                            created_by, updated_by
                        ) VALUES (
                            :collection_key, CAST(:theme_id AS uuid),
                            CAST(:source_id AS uuid), :title, :edition_key,
                            'published', 'public', '{}'::jsonb, :actor, :actor
                        )
                        RETURNING collection_id::text
                        """
                    ),
                    collection_params,
                )
            ).scalar_one()
        )
        await second_session.begin()
        collection_task = asyncio.create_task(
            _upsert_id_with_fallback(
                second_session,
                upsert_sql=_UPSERT_COLLECTION_SQL,
                lookup_sql=_GET_COLLECTION_ID_BY_KEY_SQL,
                params=collection_params,
                entity="test collection",
            )
        )
        await asyncio.sleep(0.2)
        await first_session.commit()
        concurrent_collection_id = await asyncio.wait_for(collection_task, timeout=5)
        await second_session.commit()
        assert concurrent_collection_id == collection_id
    finally:
        await first_session.close()
        await second_session.close()
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_collections "
                    "WHERE collection_key = :collection_key"
                ),
                {"collection_key": collection_key},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_sources "
                    "WHERE provider_dataset_id = :provider_dataset_id"
                ),
                {"provider_dataset_id": provider_dataset_id},
            )
            await connection.execute(
                text("DELETE FROM feature.curated_themes WHERE theme_slug = :theme_slug"),
                {"theme_slug": theme_slug},
            )


async def test_concurrent_import_returns_the_items_actually_removed(
    migrated_engine: AsyncEngine,
) -> None:
    """lock 전 preview가 stale이어도 commit 결과는 DELETE RETURNING을 따른다."""

    from sqlalchemy.ext.asyncio import AsyncSession

    suffix = uuid4().hex
    common = {
        "collection_key": f"concurrent-import:{suffix}",
        "theme_slug": f"concurrent-import-theme-{suffix}",
        "theme_name": "동시 import 테마",
        "theme_group": "test",
        "title": "동시 import 목록",
        "edition_key": "2026",
        "provider_dataset_id": await _catalog_dataset_id(
            migrated_engine,
            f"concurrent-import-provider-{suffix}",
            "concurrent-import-dataset",
        ),
        "source_name": "동시 import 출처",
        "source_url": None,
        "feature_id": None,
        "address_hint": None,
        "sort_order": 1,
        "item_title": None,
        "item_summary": None,
        "metadata": {},
    }
    rows_a = (
        ResolvedCurationImportRow(
            row_number=2,
            source_item_key="item-a",
            place_name="동시 장소 A",
            **common,
        ),
    )
    rows_b = (
        ResolvedCurationImportRow(
            row_number=2,
            source_item_key="item-b",
            place_name="동시 장소 B",
            **common,
        ),
    )
    first_session = AsyncSession(migrated_engine, expire_on_commit=False)
    second_session = AsyncSession(migrated_engine, expire_on_commit=False)

    async def _commit(
        session: AsyncSession,
        rows: tuple[ResolvedCurationImportRow, ...],
        actor: str,
    ) -> CurationImportResult:
        result = await import_curation_rows(session, rows=rows, actor=actor)
        await session.commit()
        return result

    try:
        first_preview = await preview_curation_import(first_session, rows=rows_a)
        second_preview = await preview_curation_import(second_session, rows=rows_b)
        assert first_preview.removals == ()
        assert second_preview.removals == ()

        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(
                _commit(first_session, rows_a, "import-a"),
                _commit(second_session, rows_b, "import-b"),
            ),
            timeout=10,
        )
        results = (first_result, second_result)
        assert sorted(result["removed"] for result in results) == [0, 1]
        for result in results:
            removals = result["removals"]
            assert result["removed"] == len(removals)
        if first_result["removed"] == 1:
            assert {item.external_item_id for item in first_result["removals"]} == {"item-b"}
        else:
            assert {item.external_item_id for item in second_result["removals"]} == {"item-a"}
    finally:
        await first_session.close()
        await second_session.close()
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE feature.curation_collections "
                    "SET status = 'archived', archived_at = now() "
                    "WHERE collection_key = :collection_key"
                ),
                {"collection_key": common["collection_key"]},
            )


async def test_new_collection_create_add_does_not_deadlock_import(
    migrated_engine: AsyncEngine,
) -> None:
    """미커밋 collection도 logical key lock을 Feature lock보다 먼저 잡는다."""

    from sqlalchemy.ext.asyncio import AsyncSession

    suffix = uuid4().hex
    feature_id = f"feature:collection-key-lock:{suffix}"
    collection_key = f"collection-key-lock:{suffix}"
    theme_slug = f"collection-key-lock-{suffix}"
    provider = f"collection-key-lock-{suffix}"
    setup = AsyncSession(migrated_engine, expire_on_commit=False)
    creator = AsyncSession(migrated_engine, expire_on_commit=False)
    importer = AsyncSession(migrated_engine, expire_on_commit=False)
    import_task: asyncio.Task[CurationImportResult] | None = None
    try:
        await setup.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, marker_icon, marker_color
                ) VALUES (
                    :feature_id, 'place', 'collection key lock 장소',
                    '01070100', 'place', 'P-01'
                )
                """
            ),
            {"feature_id": feature_id},
        )
        provider_dataset_id = await _dataset_id(setup, provider, "dataset")
        source_id = str(
            (
                await setup.execute(
                    text(
                        """
                        INSERT INTO feature.curated_sources (
                            provider_dataset_id, source_name, source_kind,
                            update_cycle, provider_status, metadata
                        ) VALUES (
                            :provider_dataset_id, 'collection key lock 출처',
                            'manual', 'unknown', 'manual_only', '{}'::jsonb
                        )
                        RETURNING source_id::text
                        """
                    ),
                    {"provider_dataset_id": provider_dataset_id},
                )
            ).scalar_one()
        )
        await setup.commit()

        theme_id = await upsert_curation_theme(
            creator,
            theme_slug=theme_slug,
            theme_name="collection key lock 테마",
            theme_group="test",
        )
        import_row = ResolvedCurationImportRow(
            row_number=2,
            collection_key=collection_key,
            theme_slug=theme_slug,
            theme_name="collection key lock 테마",
            theme_group="test",
            title="공식 import collection",
            edition_key="2026",
            provider_dataset_id=provider_dataset_id,
            source_name="collection key lock 출처",
            source_url=None,
            source_item_key="official-item",
            source_component_key="primary",
            feature_id=feature_id,
            place_name="collection key lock 장소",
            address_hint=None,
            sort_order=1,
            item_title=None,
            item_summary=None,
            metadata={},
        )
        import_task = asyncio.create_task(
            import_curation_rows(
                importer,
                rows=(import_row,),
                actor="importer",
            )
        )
        await asyncio.sleep(0.2)
        assert not import_task.done()

        collection = await create_curation_collection(
            creator,
            collection_key=collection_key,
            theme_id=theme_id,
            source_id=source_id,
            title="미커밋 collection",
            actor="creator",
        )
        _, inserted = await add_curation_item(
            creator,
            collection_id=collection.collection_id,
            feature_id=feature_id,
            external_item_id="manual-item",
            place_name="collection key lock 장소",
            actor="creator",
        )
        assert inserted is True
        await creator.commit()
        result = await asyncio.wait_for(import_task, timeout=5)
        await importer.commit()
        assert result["inserted"] == 1
        assert result["removed"] == 1
    finally:
        if import_task is not None and not import_task.done():
            import_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await import_task
        await setup.close()
        await creator.close()
        await importer.close()
        async with AsyncSession(
            migrated_engine, expire_on_commit=False
        ) as cleanup, cleanup.begin():
            await truncate_committed_test_rows(
                cleanup,
                "TRUNCATE feature.features RESTART IDENTITY CASCADE",
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curated_sources "
                    "WHERE provider_dataset_id = :provider_dataset_id"
                ),
                {"provider_dataset_id": provider_dataset_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM feature.curated_themes "
                    "WHERE theme_slug = :theme_slug"
                ),
                {"theme_slug": theme_slug},
            )


async def test_admin_can_resolve_and_archive_unmatched_item_with_actor_audit(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    collection = await create_curation_collection(
        migrated_session,
        collection_key="manual-resolution:2026",
        theme_id=theme_id,
        source_id=source_id,
        title="미연결 장소 해소 테스트",
        actor="collection-creator",
    )
    unresolved, _ = await add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=None,
        external_item_id="unmatched-lighthouse",
        place_name="미연결 등대",
        address_hint="서울",
        actor="item-creator",
    )

    still_unresolved = await get_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        curation_item_id=unresolved.curation_item_id,
    )
    assert still_unresolved is not None
    assert still_unresolved.feature_id is None
    assert still_unresolved.created_by == "item-creator"

    resolved = await update_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        curation_item_id=unresolved.curation_item_id,
        updates={"feature_id": _FEATURE_ID, "curation_relation": "primary_stop"},
        actor="item-resolver",
    )

    assert resolved is not None
    assert resolved.curation_item_id == unresolved.curation_item_id
    assert resolved.feature_id == _FEATURE_ID
    assert resolved.place_name == "미연결 등대"
    assert resolved.address_hint == "서울"
    assert resolved.created_by == "item-creator"
    assert resolved.updated_by == "item-resolver"
    assert resolved.curation_relation == "primary_stop"
    sibling, sibling_inserted = await add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=None,
        external_item_id="unmatched-lighthouse",
        external_component_id="component-02",
        place_name="두 번째 미연결 등대",
        actor="component-writer",
    )
    assert sibling_inserted
    assert sibling.feature_id is None
    with pytest.raises(ValueError, match="다른 component가 이미"):
        await update_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            curation_item_id=sibling.curation_item_id,
            updates={"feature_id": _FEATURE_ID},
            actor="invalid-resolver",
        )

    # 아래 `add_curation_item`이 거절해야 하는 대상은 "감춰진 feature"다.
    # `status='hidden'`의 3축 등가물은 (active, suppressed, valid)이므로
    # publication만 내린다 — retired로 내리면 "삭제된 feature 거절"이라는 다른
    # 명제를 재게 되고, 이 테스트가 뒤에서 확인하는 archive/actor 감사 경로도
    # soft delete 쪽으로 옮겨간다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET publication_state = 'suppressed' "
            "WHERE feature_id = :feature_id"
        ),
        {"feature_id": _FEATURE_ID},
    )
    archived = await archive_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        curation_item_id=unresolved.curation_item_id,
        actor="item-archiver",
    )
    assert archived is not None
    assert archived.status == "archived"
    assert archived.archived_at is not None
    assert archived.updated_by == "item-archiver"
    with pytest.raises(ValueError, match="active Feature"):
        await add_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            feature_id=_FEATURE_ID,
            external_item_id="hidden-feature-with-place-name",
            place_name="숨김 Feature 수동 표기",
            actor="invalid-writer",
        )
    collection_actor = (
        await migrated_session.execute(
            text(
                "SELECT updated_by FROM feature.curation_collections "
                "WHERE collection_id = CAST(:collection_id AS uuid)"
            ),
            {"collection_id": collection.collection_id},
        )
    ).scalar_one()
    assert collection_actor == "item-archiver"


async def test_import_retargets_stable_component_without_losing_operator_state(
    migrated_session: AsyncSession,
) -> None:
    await _seed_foundations(migrated_session)
    common = {
        "collection_key": "component-retarget:2026",
        "theme_slug": "component-retarget",
        "theme_name": "복합 항목 재연결",
        "theme_group": "test",
        "title": "복합 항목 재연결",
        "edition_key": "2026",
        "provider_dataset_id": await _dataset_id(
            migrated_session, "migration-test", "component-retarget"
        ),
        "source_name": "migration test",
        "source_url": None,
        "source_item_key": "compound-item",
        "place_name": "미연결 구성 장소",
        "address_hint": None,
        "sort_order": 1,
        "item_title": None,
        "item_summary": None,
        "metadata": {"provider_revision": 1},
    }
    unresolved_rows = (
        ResolvedCurationImportRow(
            row_number=2,
            source_component_key="component-01",
            feature_id=None,
            **common,
        ),
        ResolvedCurationImportRow(
            row_number=3,
            source_component_key="component-02",
            feature_id=None,
            **{**common, "sort_order": 2},
        ),
    )
    first = await import_curation_rows(
        migrated_session,
        rows=unresolved_rows,
        actor="importer",
    )
    assert first["inserted"] == 2
    identities = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT
                        item.external_component_id,
                        item.curation_item_id::text
                    FROM feature.curation_items AS item
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE collection.collection_key = 'component-retarget:2026'
                    ORDER BY item.external_component_id
                    """
                )
            )
        )
        .tuples()
        .all()
    )
    item_ids = dict(identities)
    collection_id = (
        await migrated_session.execute(
            text(
                """
                SELECT collection_id::text
                FROM feature.curation_collections
                WHERE collection_key = 'component-retarget:2026'
                """
            )
        )
    ).scalar_one()
    updated = await update_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_ids["component-01"],
        updates={
            "status": "rejected",
            "curation_relation": "primary_stop",
            "reuse_policy": "blocked",
        },
        actor="operator",
    )
    assert updated is not None

    rematched_rows = (
        ResolvedCurationImportRow(
            row_number=2,
            source_component_key="component-01",
            feature_id=_FEATURE_ID,
            **{
                **common,
                "place_name": "겹치는 관광지",
                "metadata": {"provider_revision": 2},
            },
        ),
        unresolved_rows[1],
    )
    second = await import_curation_rows(
        migrated_session,
        rows=rematched_rows,
        actor="importer",
    )
    assert second["inserted"] == 0
    assert second["updated"] == 1
    after = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_ids["component-01"],
    )
    assert after is not None
    assert after.curation_item_id == item_ids["component-01"]
    assert after.external_component_id == "component-01"
    assert after.feature_id == _FEATURE_ID
    assert after.status == "rejected"
    assert after.curation_relation == "primary_stop"
    assert after.reuse_policy == "blocked"
    assert after.metadata == {"provider_revision": 2}


async def test_import_adopts_migrated_legacy_components_without_losing_state(
    migrated_session: AsyncSession,
) -> None:
    await _seed_foundations(migrated_session)
    second_feature_id = "feature:curation-component-second"
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, marker_icon, marker_color
            ) VALUES (
                :feature_id, 'place', '두 번째 구성 장소', '01070100',
                'place', 'P-01'
            )
            """
        ),
        {"feature_id": second_feature_id},
    )
    common = {
        "collection_key": "component-adoption:2026",
        "theme_slug": "component-adoption",
        "theme_name": "복합 항목 identity 승계",
        "theme_group": "test",
        "title": "복합 항목 identity 승계",
        "edition_key": "2026",
        "provider_dataset_id": await _dataset_id(
            migrated_session, "migration-test", "component-adoption"
        ),
        "source_name": "migration test",
        "source_url": None,
        "source_item_key": "official-compound-item",
        "address_hint": None,
        "item_title": None,
        "item_summary": None,
        "metadata": {"provider_revision": 1},
    }
    rows = (
        ResolvedCurationImportRow(
            row_number=2,
            source_component_key="component-01",
            feature_id=_FEATURE_ID,
            place_name="겹치는 관광지",
            sort_order=1,
            **common,
        ),
        ResolvedCurationImportRow(
            row_number=3,
            source_component_key="component-02",
            feature_id=second_feature_id,
            place_name="두 번째 구성 장소",
            sort_order=1,
            **common,
        ),
    )
    first = await import_curation_rows(migrated_session, rows=rows, actor="importer")
    assert first["inserted"] == 2
    collection_id = (
        await migrated_session.execute(
            text(
                """
                SELECT collection_id::text
                FROM feature.curation_collections
                WHERE collection_key = 'component-adoption:2026'
                """
            )
        )
    ).scalar_one()
    original = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT feature_id, curation_item_id::text
                    FROM feature.curation_items
                    WHERE collection_id = CAST(:collection_id AS uuid)
                    ORDER BY feature_id
                    """
                ),
                {"collection_id": collection_id},
            )
        )
        .tuples()
        .all()
    )
    original_ids = dict(original)
    operator_item_id = original_ids[_FEATURE_ID]
    await update_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=operator_item_id,
        updates={
            "status": "rejected",
            "curation_relation": "primary_stop",
            "reuse_policy": "blocked",
        },
        actor="operator",
    )
    await migrated_session.execute(
        text(
            """
            UPDATE feature.curation_items
            SET external_component_id = 'legacy:' || curation_item_id::text,
                source_present = feature_id <> :source_absent_feature_id
            WHERE collection_id = CAST(:collection_id AS uuid)
            """
        ),
        {
            "collection_id": collection_id,
            "source_absent_feature_id": _FEATURE_ID,
        },
    )

    preview = await preview_curation_import(migrated_session, rows=rows)
    assert preview.inserted == 0
    assert preview.updated == 2
    assert preview.removals == ()
    adopted = await import_curation_rows(
        migrated_session,
        rows=rows,
        actor="official-reimport",
    )
    assert adopted == {
        "rows": 2,
        "collections": 1,
        "inserted": 0,
        "updated": 2,
        "removed": 0,
        "removals": (),
        "import_batch_id": adopted["import_batch_id"],
    }
    after_rows = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT
                        feature_id,
                        curation_item_id::text,
                        external_component_id,
                        source_present,
                        status,
                        curation_relation,
                        reuse_policy,
                        operator_updated_by
                    FROM feature.curation_items
                    WHERE collection_id = CAST(:collection_id AS uuid)
                    ORDER BY feature_id
                    """
                ),
                {"collection_id": collection_id},
            )
        )
        .mappings()
        .all()
    )
    assert {row["feature_id"]: row["curation_item_id"] for row in after_rows} == (
        original_ids
    )
    assert {row["external_component_id"] for row in after_rows} == {
        "component-01",
        "component-02",
    }
    assert all(row["source_present"] for row in after_rows)
    operator_row = next(
        row for row in after_rows if row["curation_item_id"] == operator_item_id
    )
    assert operator_row["status"] == "rejected"
    assert operator_row["curation_relation"] == "primary_stop"
    assert operator_row["reuse_policy"] == "blocked"
    assert operator_row["operator_updated_by"] == "operator"


async def test_import_adopts_source_absent_legacy_projection_to_primary(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    projection_id = str(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, curation_status,
                        selection_origin, display_title, display_summary
                    ) VALUES (
                        CAST(:theme_id AS uuid),
                        :feature_id,
                        CAST(:source_id AS uuid),
                        'curated',
                        'admin',
                        'legacy projection collection',
                        'legacy projection summary'
                    )
                    RETURNING curated_feature_id::text
                    """
                ),
                {
                    "theme_id": theme_id,
                    "feature_id": _FEATURE_ID,
                    "source_id": source_id,
                },
            )
        ).scalar_one()
    )
    projection_item = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT
                        item.curation_item_id::text,
                        item.collection_id::text,
                        item.external_component_id,
                        collection.collection_key,
                        collection.title
                    FROM feature.curation_items AS item
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE item.legacy_projection_id =
                          CAST(:projection_id AS uuid)
                    """
                ),
                {"projection_id": projection_id},
            )
        )
        .mappings()
        .one()
    )
    item_id = str(projection_item["curation_item_id"])
    collection_id = str(projection_item["collection_id"])
    assert projection_item["external_component_id"] == f"legacy:{projection_id}"
    updated = await update_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
        updates={
            "status": "rejected",
            "curation_relation": "primary_stop",
            "reuse_policy": "blocked",
        },
        actor="projection-operator",
    )
    assert updated is not None
    await migrated_session.execute(
        text(
            """
            UPDATE feature.curation_items
            SET source_present = false
            WHERE curation_item_id = CAST(:item_id AS uuid)
            """
        ),
        {"item_id": item_id},
    )
    row = ResolvedCurationImportRow(
        row_number=2,
        collection_key=str(projection_item["collection_key"]),
        theme_slug="tourism-100-test",
        theme_name="한국관광 100선",
        theme_group="official",
        title=str(projection_item["title"]),
        edition_key="",
        provider_dataset_id=await _dataset_id(
            migrated_session, "python-mcst-api", "tourism-100-test"
        ),
        source_name="문화체육관광부",
        source_url=None,
        source_item_key=projection_id,
        source_component_key="primary",
        feature_id=_FEATURE_ID,
        place_name="겹치는 관광지",
        address_hint=None,
        sort_order=0,
        item_title=None,
        item_summary="authoritative summary",
        metadata={"provider_revision": 2},
    )

    preview = await preview_curation_import(migrated_session, rows=(row,))
    assert preview.inserted == 0
    assert preview.updated == 1
    assert preview.removals == ()
    adopted = await import_curation_rows(
        migrated_session,
        rows=(row,),
        actor="official-reimport",
    )
    assert adopted["inserted"] == 0
    assert adopted["updated"] == 1
    assert adopted["removed"] == 0
    after = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
    )
    assert after is not None
    assert after.external_component_id == "primary"
    assert after.source_present is True
    assert after.status == "rejected"
    assert after.curation_relation == "primary_stop"
    assert after.reuse_policy == "blocked"
    operator_updated_by = (
        await migrated_session.execute(
            text(
                """
                SELECT operator_updated_by
                FROM feature.curation_items
                WHERE curation_item_id = CAST(:item_id AS uuid)
                """
            ),
            {"item_id": item_id},
        )
    ).scalar_one()
    assert operator_updated_by == "projection-operator"


async def test_import_adopts_archived_legacy_identity_without_resurrection(
    migrated_session: AsyncSession,
) -> None:
    await _seed_foundations(migrated_session)
    row = ResolvedCurationImportRow(
        row_number=2,
        collection_key="archived-component-adoption:2026",
        theme_slug="archived-component-adoption",
        theme_name="보관 component identity 승계",
        theme_group="test",
        title="보관 component identity 승계",
        edition_key="2026",
        provider_dataset_id=await _dataset_id(
            migrated_session, "migration-test", "archived-component-adoption"
        ),
        source_name="migration test",
        source_url=None,
        source_item_key="archived-official-item",
        source_component_key="component-01",
        feature_id=_FEATURE_ID,
        place_name="겹치는 관광지",
        address_hint=None,
        sort_order=1,
        item_title=None,
        item_summary="original summary",
        metadata={"provider_revision": 1},
    )
    first = await import_curation_rows(
        migrated_session,
        rows=(row,),
        actor="initial-import",
    )
    assert first["inserted"] == 1
    item = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT
                        item.curation_item_id::text,
                        item.collection_id::text
                    FROM feature.curation_items AS item
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE collection.collection_key =
                          'archived-component-adoption:2026'
                    """
                )
            )
        )
        .mappings()
        .one()
    )
    item_id = str(item["curation_item_id"])
    collection_id = str(item["collection_id"])
    archived = await archive_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
        actor="archive-operator",
    )
    assert archived is not None
    await migrated_session.execute(
        text(
            """
            UPDATE feature.curation_items
            SET external_component_id = 'legacy:' || curation_item_id::text
            WHERE curation_item_id = CAST(:item_id AS uuid)
            """
        ),
        {"item_id": item_id},
    )

    preview = await preview_curation_import(migrated_session, rows=(row,))
    assert preview.inserted == 0
    assert preview.updated == 1
    assert preview.removals == ()
    adopted = await import_curation_rows(
        migrated_session,
        rows=(row,),
        actor="official-reimport",
    )
    assert adopted["inserted"] == 0
    assert adopted["updated"] == 1
    assert adopted["removed"] == 0
    after = await get_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=item_id,
        include_archived=True,
    )
    assert after is not None
    assert after.curation_item_id == item_id
    assert after.external_component_id == "component-01"
    assert after.status == "archived"
    assert after.archived_at is not None
    assert after.item_summary == "original summary"
    assert after.metadata == {"provider_revision": 1}
    audit = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT count(*)::integer, max(operator_updated_by)
                    FROM feature.curation_items
                    WHERE collection_id = CAST(:collection_id AS uuid)
                      AND external_item_id = 'archived-official-item'
                    """
                ),
                {"collection_id": collection_id},
            )
        )
        .tuples()
        .one()
    )
    assert audit == (1, "archive-operator")


async def test_import_rejects_ambiguous_legacy_adoption_without_mutation(
    migrated_session: AsyncSession,
) -> None:
    await _seed_foundations(migrated_session)
    row = ResolvedCurationImportRow(
        row_number=2,
        collection_key="ambiguous-component-adoption:2026",
        theme_slug="ambiguous-component-adoption",
        theme_name="모호한 component identity 승계",
        theme_group="test",
        title="모호한 component identity 승계",
        edition_key="2026",
        provider_dataset_id=await _dataset_id(
            migrated_session, "migration-test", "ambiguous-component-adoption"
        ),
        source_name="migration test",
        source_url=None,
        source_item_key="ambiguous-official-item",
        source_component_key="component-01",
        feature_id=_FEATURE_ID,
        place_name="겹치는 관광지",
        address_hint=None,
        sort_order=1,
        item_title=None,
        item_summary="official summary",
        metadata={"provider_revision": 1},
    )
    first = await import_curation_rows(
        migrated_session,
        rows=(row,),
        actor="initial-import",
    )
    assert first["inserted"] == 1
    original = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT
                        item.curation_item_id::text,
                        item.collection_id::text
                    FROM feature.curation_items AS item
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE collection.collection_key =
                          'ambiguous-component-adoption:2026'
                    """
                )
            )
        )
        .mappings()
        .one()
    )
    archived_item_id = str(original["curation_item_id"])
    collection_id = str(original["collection_id"])
    archived = await archive_curation_item(
        migrated_session,
        collection_id=collection_id,
        curation_item_id=archived_item_id,
        actor="archive-operator",
    )
    assert archived is not None
    await migrated_session.execute(
        text(
            """
            UPDATE feature.curation_items
            SET external_component_id = 'legacy:' || curation_item_id::text
            WHERE curation_item_id = CAST(:item_id AS uuid)
            """
        ),
        {"item_id": archived_item_id},
    )
    active, inserted = await add_curation_item(
        migrated_session,
        collection_id=collection_id,
        external_item_id=row.source_item_key,
        external_component_id="legacy:active-candidate",
        feature_id=_FEATURE_ID,
        place_name=row.place_name,
        actor="active-writer",
    )
    assert inserted is True
    assert active.archived_at is None

    async def snapshot() -> list[dict[str, object]]:
        return [
            dict(item)
            for item in (
                (
                    await migrated_session.execute(
                        text(
                            """
                            SELECT
                                curation_item_id::text,
                                external_component_id,
                                source_present,
                                status,
                                operator_updated_by,
                                archived_at
                            FROM feature.curation_items
                            WHERE collection_id = CAST(:collection_id AS uuid)
                              AND external_item_id = :external_item_id
                            ORDER BY curation_item_id
                            """
                        ),
                        {
                            "collection_id": collection_id,
                            "external_item_id": row.source_item_key,
                        },
                    )
                )
                .mappings()
                .all()
            )
        ]

    before = await snapshot()
    assert len(before) == 2
    foundation_before = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT
                        theme.theme_name,
                        source.source_name,
                        source.source_url,
                        collection.title
                    FROM feature.curation_collections AS collection
                    JOIN feature.curated_themes AS theme
                      ON theme.theme_id = collection.theme_id
                    JOIN feature.curated_sources AS source
                      ON source.source_id = collection.source_id
                    WHERE collection.collection_id =
                          CAST(:collection_id AS uuid)
                    """
                ),
                {"collection_id": collection_id},
            )
        )
        .mappings()
        .one()
    )
    conflicting_row = replace(
        row,
        theme_name="반영되면 안 되는 테마",
        source_name="반영되면 안 되는 출처",
        source_url="https://invalid.example.test/rejected-import",
        title="반영되면 안 되는 collection 제목",
    )
    with pytest.raises(ValueError, match="승계 후보가 모호합니다"):
        await preview_curation_import(migrated_session, rows=(conflicting_row,))
    assert await snapshot() == before
    with pytest.raises(ValueError, match="승계 후보가 모호합니다"):
        await import_curation_rows(
            migrated_session,
            rows=(conflicting_row,),
            actor="official-reimport",
        )
    assert await snapshot() == before
    foundation_after = (
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT
                        theme.theme_name,
                        source.source_name,
                        source.source_url,
                        collection.title
                    FROM feature.curation_collections AS collection
                    JOIN feature.curated_themes AS theme
                      ON theme.theme_id = collection.theme_id
                    JOIN feature.curated_sources AS source
                      ON source.source_id = collection.source_id
                    WHERE collection.collection_id =
                          CAST(:collection_id AS uuid)
                    """
                ),
                {"collection_id": collection_id},
            )
        )
        .mappings()
        .one()
    )
    assert dict(foundation_after) == dict(foundation_before)


async def test_feature_curation_lookup_uses_membership_index(
    migrated_session: AsyncSession,
) -> None:
    theme_id, source_id = await _seed_foundations(migrated_session)
    collection = await create_curation_collection(
        migrated_session,
        collection_key="curation-perf:2026",
        theme_id=theme_id,
        source_id=source_id,
        title="큐레이션 조회 인덱스 검증",
        status="published",
        visibility="public",
    )
    await add_curation_item(
        migrated_session,
        collection_id=collection.collection_id,
        feature_id=_FEATURE_ID,
        external_item_id="perf-item",
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, marker_icon, marker_color
            )
            SELECT
                'feature:curation-perf:' || g::text,
                'place', '큐레이션 성능 장소 ' || g::text, '01070100',
                'place', 'P-01'
            FROM generate_series(1, 500) AS g
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.curation_items (
                collection_id, feature_id, external_item_id, place_name,
                status, sort_order
            )
            SELECT
                CAST(:collection_id AS uuid),
                'feature:curation-perf:' || g::text,
                'perf-item-' || g::text,
                '큐레이션 성능 장소 ' || g::text,
                'included', g
            FROM generate_series(1, 500) AS g
            """
        ),
        {"collection_id": collection.collection_id},
    )
    await migrated_session.execute(text("ANALYZE feature.features"))
    await migrated_session.execute(text("ANALYZE feature.curation_items"))
    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (
        await migrated_session.execute(
            text("EXPLAIN (FORMAT JSON, COSTS OFF) " + _LIST_FEATURE_ITEMS_SQL),
            {"feature_id": _FEATURE_ID, "public_only": True},
        )
    ).scalar_one()[0]["Plan"]

    def index_names(node: object) -> set[str]:
        if not isinstance(node, dict):
            return set()
        names = {str(node["Index Name"])} if "Index Name" in node else set()
        for child in node.get("Plans", []):
            names.update(index_names(child))
        return names

    public_lookup_indexes = index_names(plan)
    assert "idx_curation_items_feature_status_collection" in public_lookup_indexes
    assert "idx_curation_link_decisions_item_time" in public_lookup_indexes

    match_plan = (
        await migrated_session.execute(
            text("EXPLAIN (FORMAT JSON, COSTS OFF) " + _RESOLVE_FEATURES_BATCH_SQL),
            {
                "requests": json.dumps(
                    [
                        {
                            "row_number": 2,
                            "feature_id": None,
                            "place_name": "겹치는 관광지",
                            "address_hint": None,
                        }
                    ],
                    ensure_ascii=False,
                )
            },
        )
    ).scalar_one()[0]["Plan"]
    # 이 matcher가 훑는 후보 집합은 `lifecycle='active' AND publication <> 'suppressed'`
    # 라 draft·quarantined를 포함한다. 0096이 `idx_features_lower_name_keyset`을 공개
    # 3축 partial로 좁힌 뒤로는 그 인덱스를 고를 수 없었고, 한동안 이 단언은
    # `pk_features`만 남긴 채 이름 분기의 접근 경로를 공백으로 두고 있었다.
    #
    # 0098이 admin scope 전체 인덱스(`idx_features_admin_lower_name_keyset`)를 신설했다.
    # 술어가 없는 인덱스라 이 후보 집합을 그대로 덮는다 — matcher를 공개 축으로 좁히지
    # 않고도 이름 분기의 보증이 선다.
    # 0098 이후 planner는 PK 대신 이 인덱스를 고른다 — 이름으로 좁히는 것이 실제로
    # 더 선택적이기 때문이다. 즉 이름 분기가 인덱스를 타게 됐다는 뜻이고, 그것이
    # 이 gate가 원래 지키려던 명제다.
    match_indexes = index_names(match_plan)
    assert "idx_features_admin_lower_name_keyset" in match_indexes, match_indexes


async def test_address_hint_matches_split_jsonb_fields(
    migrated_session: AsyncSession,
) -> None:
    """주소 후보는 authoritative field의 정규화된 literal hierarchy만 일치시킨다."""
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, marker_icon, marker_color, address
            ) VALUES
                (
                    'feature:h31-split-address', 'place', '토큰분리 등대', '01050400',
                    'place', 'P-09',
                    '{"sido_name":"울산광역시","sigungu_name":"울주군",'
                    '"admin":"울산광역시 울주군 서생면"}'::jsonb
                ),
                (
                    'feature:h31-wrong-field', 'place', '토큰분리 등대', '01050400',
                    'place', 'P-09',
                    '{"sido_name":"울산광역시","sigungu_name":"울주군",'
                    '"admin":"울산광역시 울주군 온산읍",'
                    '"road":"울산광역시 울주군 서생면로 1"}'::jsonb
                )
            """
        )
    )

    async def _match(hint: str | None) -> tuple[str, ...]:
        matches = await resolve_feature_matches(
            migrated_session,
            requests=(
                FeatureMatchRequest(
                    row_number=1,
                    feature_id=None,
                    place_name="토큰분리 등대",
                    address_hint=hint,
                ),
            ),
        )
        return tuple(m.feature_id for m in matches[1])

    # hierarchy가 맞는 authoritative component만 남는다.
    assert await _match("울산광역시 울주군 서생면") == ("feature:h31-split-address",)
    # NFD 입력도 NFKC/NFC 주소와 같은 의미다.
    assert await _match(
        unicodedata.normalize("NFD", "울산광역시 울주군 서생면")
    ) == ("feature:h31-split-address",)
    # SQL LIKE wildcard는 주소 증거 없이 후보를 만들 수 없다.
    assert await _match("%") == ()
    assert await _match("_") == ()
    # hierarchy가 하나라도 어긋나면 일치하지 않는다.
    assert await _match("울산광역시 동구 일산동") == ()
    assert await _match("부산광역시 울주군 서생면") == ()
    # 공백은 정규화하되 token boundary는 유지한다.
    assert await _match("울산광역시   울주군") == (
        "feature:h31-split-address",
        "feature:h31-wrong-field",
    )


async def test_address_candidate_reimport_is_idempotent_and_never_publicly_links(
    migrated_session: AsyncSession,
) -> None:
    """주소 후보는 반복 import에서도 미승인 상태이며 Feature 공개 membership이 아니다."""
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, marker_icon, marker_color, address
            ) VALUES (
                'feature:h31-preview-only', 'place', '미승인 등대', '01050400',
                'place', 'P-09',
                '{"sido_name":"울산광역시","sigungu_name":"울주군",'
                '"admin":"울산광역시 울주군 서생면 대송리"}'::jsonb
            )
            """
        )
    )
    matches = await resolve_feature_matches(
        migrated_session,
        requests=(
            FeatureMatchRequest(
                row_number=2,
                feature_id=None,
                place_name="미승인 등대",
                address_hint="울산광역시 울주군 서생면 대송리",
            ),
        ),
    )
    assert [match.feature_id for match in matches[2]] == ["feature:h31-preview-only"]

    row = ResolvedCurationImportRow(
        row_number=2,
        collection_key="h31-preview-only:2026",
        theme_slug="h31-preview-only",
        theme_name="주소 후보 검토",
        theme_group="official",
        title="주소 후보 검토 목록",
        edition_key="2026",
        provider_dataset_id=await _dataset_id(
            migrated_session, "official-static-source", "h31-preview-only"
        ),
        source_name="공식 정적 원천",
        source_url="https://example.test/h31-preview-only",
        source_item_key="preview-only-1",
        source_component_key="primary",
        feature_id=None,
        place_name="미승인 등대",
        address_hint="울산광역시 울주군 서생면 대송리",
        sort_order=1,
        item_title="미승인 등대",
        item_summary=None,
        metadata={},
    )
    first = await import_curation_rows(
        migrated_session,
        rows=(row,),
        actor="official-import",
    )
    second = await import_curation_rows(
        migrated_session,
        rows=(row,),
        actor="official-import",
    )
    await migrated_session.execute(
        text(
            """
            UPDATE feature.curation_collections
            SET status = 'published', visibility = 'public'
            WHERE collection_key = 'h31-preview-only:2026'
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            UPDATE feature.curated_themes
            SET visibility = 'public'
            WHERE theme_slug = 'h31-preview-only'
            """
        )
    )

    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert (
        await get_feature_curation_group(
            migrated_session,
            feature_id="feature:h31-preview-only",
            public_only=True,
        )
        is None
    )
    stored_feature_id = (
        await migrated_session.execute(
            text(
                """
                SELECT item.feature_id
                FROM feature.curation_items AS item
                JOIN feature.curation_collections AS collection
                  ON collection.collection_id = item.collection_id
                WHERE collection.collection_key = 'h31-preview-only:2026'
                  AND item.external_item_id = 'preview-only-1'
                """
            )
        )
    ).scalar_one()
    assert stored_feature_id is None


# ---------------------------------------------------------------------------
# T-VN-H22 — `0065` quarantine 재분류 backend
#
# 실데이터 격리는 0건이 정상이라 테스트가 head 스키마 위에 marker collection을
# 직접 합성한다 (`0065`를 실제로 돌리지 않는다).
# ---------------------------------------------------------------------------


async def _plant_quarantine_collection(
    session: AsyncSession,
    *,
    theme_id: str,
    source_id: str | None,
    original_collection_id: str | None,
    title: str = "[0065 격리] 원제",
    extra_metadata: dict[str, str] | None = None,
) -> str:
    """`0065`가 만드는 정본 marker 그대로 격리 collection을 합성한다."""

    quarantine_id = str(uuid4())
    metadata: dict[str, str] = {"migration_quarantine": "0065"}
    if original_collection_id is not None:
        metadata["original_collection_id"] = original_collection_id
    metadata.update(extra_metadata or {})
    await session.execute(
        text(
            """
            INSERT INTO feature.curation_collections (
                collection_id, collection_key, theme_id, source_id, title,
                edition_key, description, status, visibility, metadata,
                created_by, updated_by
            ) VALUES (
                CAST(:collection_id AS uuid),
                'legacy:quarantine:' || :collection_id,
                CAST(:theme_id AS uuid), CAST(:source_id AS uuid), :title,
                '', '0065 owner 이력 불충분', 'draft', 'admin_only',
                CAST(:metadata AS jsonb), 'migration:0065', 'migration:0065'
            )
            """
        ),
        {
            "collection_id": quarantine_id,
            "theme_id": theme_id,
            "source_id": source_id,
            "title": title,
            "metadata": json.dumps(metadata),
        },
    )
    return quarantine_id


async def _seed_second_theme_and_source(session: AsyncSession) -> tuple[str, str]:
    theme_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_description, theme_group,
                        default_curated, visibility, metadata
                    ) VALUES (
                        'tourism-100-test-v2', '한국관광 100선 v2', '', 'official',
                        false, 'admin_only', '{}'::jsonb
                    )
                    RETURNING theme_id::text
                    """
                )
            )
        ).scalar_one()
    )
    source_id = str(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_sources (
                        provider_dataset_id, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        :provider_dataset_id, '한국관광공사',
                        'manual', 'unknown', 'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id::text
                    """
                ),
                {
                    "provider_dataset_id": await _dataset_id(
                        session, "python-kto-api", "tourism-100-test-v2"
                    )
                },
            )
        ).scalar_one()
    )
    return theme_id, source_id


def test_quarantine_cursor_roundtrip_rejects_key_drift_and_tampering() -> None:
    collection_id = str(uuid4())
    item_id = str(uuid4())
    collection_cursor = encode_quarantine_collection_cursor(collection_id)
    item_cursor = encode_quarantine_item_cursor(item_id)

    assert decode_quarantine_collection_cursor(None) is None
    assert decode_quarantine_item_cursor(None) is None
    assert decode_quarantine_collection_cursor(collection_cursor) == collection_id
    assert decode_quarantine_item_cursor(item_cursor) == item_id

    # 정확 키 집합 검사 — 다른 cursor 종을 서로 넣으면 거절돼야 한다.
    with pytest.raises(ValueError, match="invalid curation quarantine cursor"):
        decode_quarantine_collection_cursor(item_cursor)
    with pytest.raises(ValueError, match="invalid curation quarantine item cursor"):
        decode_quarantine_item_cursor(collection_cursor)

    def _forge(payload: dict[str, object]) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(payload).encode())
            .decode()
            .rstrip("=")
        )

    with pytest.raises(ValueError, match="invalid curation quarantine cursor"):
        decode_quarantine_collection_cursor(
            _forge({"v": 2, "collection_id": collection_id})
        )
    with pytest.raises(ValueError, match="invalid curation quarantine cursor"):
        decode_quarantine_collection_cursor(_forge({"v": 1, "collection_id": "x"}))
    with pytest.raises(ValueError, match="invalid curation quarantine cursor"):
        decode_quarantine_collection_cursor(
            _forge({"v": 1, "collection_id": collection_id, "extra": "smuggled"})
        )
    with pytest.raises(ValueError, match="invalid curation quarantine cursor"):
        decode_quarantine_collection_cursor(collection_cursor + "?!")


async def test_quarantine_read_model_returns_parallel_theme_source(
    migrated_session: AsyncSession,
) -> None:
    """① 목록 read model — 격리 보관본과 원본의 **현재** theme/source 병렬 반환."""

    theme_id, source_id = await _seed_foundations(migrated_session)
    theme2_id, source2_id = await _seed_second_theme_and_source(migrated_session)
    original = await create_curation_collection(
        migrated_session,
        collection_key="h22:original",
        theme_id=theme_id,
        source_id=source_id,
        title="원본 collection",
        status="published",
        visibility="public",
    )
    quarantine_id = await _plant_quarantine_collection(
        migrated_session,
        theme_id=theme_id,
        source_id=source_id,
        original_collection_id=original.collection_id,
    )
    # 원본은 0065 이후 운영자가 theme/source를 바꿨다 — 병렬 표시가 "현재"를
    # 되짚는지 반증 가능하게 만든다.
    await update_curation_collection(
        migrated_session,
        collection_id=original.collection_id,
        updates={"theme_id": theme2_id, "source_id": source2_id},
    )
    await add_curation_item(
        migrated_session,
        collection_id=quarantine_id,
        feature_id=None,
        external_item_id="q-item-1",
        place_name="격리 항목 1",
        actor="seeder",
    )
    archived_item, _ = await add_curation_item(
        migrated_session,
        collection_id=quarantine_id,
        feature_id=None,
        external_item_id="q-item-2",
        place_name="격리 항목 2",
        actor="seeder",
    )
    await archive_curation_item(
        migrated_session,
        collection_id=quarantine_id,
        curation_item_id=archived_item.curation_item_id,
        actor="seeder",
    )
    # 원본 행이 사라진 기록도 표시된다 (exists=false).
    dangling_original_id = str(uuid4())
    dangling_quarantine_id = await _plant_quarantine_collection(
        migrated_session,
        theme_id=theme_id,
        source_id=None,
        original_collection_id=dangling_original_id,
    )

    rows, next_cursor = await list_curation_quarantine_collections(migrated_session)

    assert next_cursor is None
    assert len(rows) == 2
    by_id = {row.collection_id: row for row in rows}
    row = by_id[quarantine_id]
    assert row.collection_key == f"legacy:quarantine:{quarantine_id}"
    assert row.title == "[0065 격리] 원제"
    assert row.status == "draft"
    assert row.visibility == "admin_only"
    assert row.created_by == "migration:0065"
    assert row.marker_intact is True
    assert row.item_count == 2  # archived 포함 물리 행 수
    assert row.quarantine_theme is not None
    assert row.quarantine_theme.theme_slug == "tourism-100-test"
    assert row.quarantine_source is not None
    assert row.quarantine_source.provider == "python-mcst-api"
    assert row.original_collection is not None
    assert row.original_collection.collection_id == original.collection_id
    assert row.original_collection.exists is True
    assert row.original_collection.title == "원본 collection"
    assert row.original_collection.status == "published"
    assert row.original_collection.visibility == "public"
    assert row.original_collection.theme is not None
    assert row.original_collection.theme.theme_slug == "tourism-100-test-v2"
    assert row.original_collection.source is not None
    assert row.original_collection.source.provider == "python-kto-api"

    dangling = by_id[dangling_quarantine_id]
    assert dangling.quarantine_source is None
    assert dangling.original_collection is not None
    assert dangling.original_collection.collection_id == dangling_original_id
    assert dangling.original_collection.exists is False
    assert dangling.original_collection.title is None
    assert dangling.original_collection.theme is None
    assert dangling.original_collection.source is None

    # keyset 페이지네이션 — collection_id 오름차순 + cursor roundtrip.
    first_page, cursor = await list_curation_quarantine_collections(
        migrated_session, limit=1
    )
    assert len(first_page) == 1
    assert cursor is not None
    second_page, final_cursor = await list_curation_quarantine_collections(
        migrated_session, limit=1, cursor=cursor
    )
    assert len(second_page) == 1
    assert final_cursor is None
    assert first_page[0].collection_id < second_page[0].collection_id
    assert {first_page[0].collection_id, second_page[0].collection_id} == {
        quarantine_id,
        dangling_quarantine_id,
    }


async def test_quarantine_conflict_preview_truth_table(
    migrated_session: AsyncSession,
) -> None:
    """② conflict preview 진리표 — (A)만 / (B)만 / (A) 우선 / movable / 미해결 target."""

    theme_id, source_id = await _seed_foundations(migrated_session)
    target = await create_curation_collection(
        migrated_session,
        collection_key="h22:conflict-target",
        theme_id=theme_id,
        source_id=source_id,
        title="이동 target",
    )
    quarantine_id = await _plant_quarantine_collection(
        migrated_session,
        theme_id=theme_id,
        source_id=source_id,
        original_collection_id=target.collection_id,
    )

    async def _target_item(
        external_item_id: str,
        component: str,
        feature_id: str | None,
        *,
        archived: bool = False,
    ) -> str:
        item, _ = await add_curation_item(
            migrated_session,
            collection_id=target.collection_id,
            feature_id=feature_id,
            external_item_id=external_item_id,
            external_component_id=component,
            place_name="target 항목",
            actor="seeder",
        )
        if archived:
            await archive_curation_item(
                migrated_session,
                collection_id=target.collection_id,
                curation_item_id=item.curation_item_id,
                actor="seeder",
            )
        return item.curation_item_id

    async def _quarantine_item(
        external_item_id: str, component: str, feature_id: str | None
    ) -> str:
        item, _ = await add_curation_item(
            migrated_session,
            collection_id=quarantine_id,
            feature_id=feature_id,
            external_item_id=external_item_id,
            external_component_id=component,
            place_name="격리 항목",
            actor="seeder",
        )
        return item.curation_item_id

    # (A)만 — target 상대가 archived여도 (A)는 partial이 아니라 걸린다.
    dup_target_id = await _target_item("dup-ext", "primary", None, archived=True)
    await _quarantine_item("dup-ext", "primary", None)
    # (B)만 — (A) 회피: 같은 external_item_id + 다른 component + 같은 feature + 양쪽 active.
    shared_target_id = await _target_item("shared-ext", "t-comp", _FEATURE_ID)
    await _quarantine_item("shared-ext", "q-comp", _FEATURE_ID)
    # (A)+(B) 동시 — (A)가 우선해야 한다.
    both_target_id = await _target_item("both-ext", "primary", _FEATURE_ID)
    await _quarantine_item("both-ext", "primary", _FEATURE_ID)
    # movable — target에 상대 없음.
    await _quarantine_item("free-ext", "primary", None)
    # movable — (B) 후보가 있으나 target 쪽이 archived라 partial 술어 불충족.
    await _target_item("shared2-ext", "t2-comp", _FEATURE_ID, archived=True)
    await _quarantine_item("shared2-ext", "q2-comp", _FEATURE_ID)
    # movable — **양쪽 feature_id NULL** + 다른 component + 양쪽 active (적대 리뷰 F1).
    # (B) 비교가 `=`가 아니라 `IS NOT DISTINCT FROM`으로 퇴행하면 NULL끼리 매칭돼
    # 이 행이 가짜 active_source_feature_conflict가 된다 — 그 변이를 이 행이 죽인다.
    await _target_item("nullpair-ext", "t3-comp", None)
    await _quarantine_item("nullpair-ext", "q3-comp", None)

    result = await list_curation_quarantine_items(
        migrated_session, collection_id=quarantine_id
    )
    assert result is not None
    preview, next_cursor = result
    assert next_cursor is None
    assert preview.target_collection_id == target.collection_id
    assert preview.target_missing is False
    assert preview.target_archived is False
    assert len(preview.items) == 6
    verdicts = {
        (item.external_item_id, item.external_component_id): (
            item.conflict_kind,
            item.conflict_item_id,
        )
        for item in preview.items
    }
    assert verdicts == {
        ("dup-ext", "primary"): ("component_identity_conflict", dup_target_id),
        ("shared-ext", "q-comp"): ("active_source_feature_conflict", shared_target_id),
        ("both-ext", "primary"): ("component_identity_conflict", both_target_id),
        ("free-ext", "primary"): ("movable", None),
        ("shared2-ext", "q2-comp"): ("movable", None),
        ("nullpair-ext", "q3-comp"): ("movable", None),
    }

    # item keyset 페이지네이션 — curation_item_id 오름차순, 중복/누락 없음.
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(4):
        page_result = await list_curation_quarantine_items(
            migrated_session, collection_id=quarantine_id, limit=2, cursor=cursor
        )
        assert page_result is not None
        page, cursor = page_result
        seen.extend(item.curation_item_id for item in page.items)
        if cursor is None:
            break
    assert len(seen) == 6
    assert seen == sorted(seen)
    assert set(seen) == {item.curation_item_id for item in preview.items}

    # 명시 target이 없는 uuid면 target_missing으로 전 item이 표시된다.
    missing_result = await list_curation_quarantine_items(
        migrated_session,
        collection_id=quarantine_id,
        target_collection_id=str(uuid4()),
    )
    assert missing_result is not None
    missing_preview, _ = missing_result
    assert missing_preview.target_missing is True
    assert missing_preview.target_archived is False
    assert {item.conflict_kind for item in missing_preview.items} == {"target_missing"}
    assert {item.conflict_item_id for item in missing_preview.items} == {None}

    # 원본 기록이 아예 없으면 no_target.
    orphan_quarantine_id = await _plant_quarantine_collection(
        migrated_session,
        theme_id=theme_id,
        source_id=None,
        original_collection_id=None,
    )
    await add_curation_item(
        migrated_session,
        collection_id=orphan_quarantine_id,
        feature_id=None,
        external_item_id="orphan-1",
        place_name="고아 항목",
        actor="seeder",
    )
    orphan_result = await list_curation_quarantine_items(
        migrated_session, collection_id=orphan_quarantine_id
    )
    assert orphan_result is not None
    orphan_preview, _ = orphan_result
    assert orphan_preview.target_collection_id is None
    assert orphan_preview.target_missing is True
    assert [item.conflict_kind for item in orphan_preview.items] == ["no_target"]

    # 정본 술어에 안 걸리는 collection은 preview 대상이 아니다.
    assert (
        await list_curation_quarantine_items(
            migrated_session, collection_id=target.collection_id
        )
        is None
    )

    # preview/command 판정 일치 (적대 리뷰 F2/F3) — command가 422로 거부하는 입력을
    # preview가 "전 item 자기 충돌"이나 정상 preview로 보여주면 안 된다.
    with pytest.raises(ValueError, match="자신"):
        await list_curation_quarantine_items(
            migrated_session,
            collection_id=quarantine_id,
            target_collection_id=quarantine_id,
        )
    with pytest.raises(ValueError, match="격리 간 이동"):
        await list_curation_quarantine_items(
            migrated_session,
            collection_id=quarantine_id,
            target_collection_id=orphan_quarantine_id,
        )
    with pytest.raises(ValueError, match="격리 간 이동"):
        await move_curation_quarantine_items(
            migrated_session,
            collection_id=quarantine_id,
            target_collection_id=orphan_quarantine_id,
            item_ids=None,
            actor="mover",
        )


async def test_quarantine_move_is_atomic_and_deletes_empty_collection(
    migrated_session: AsyncSession,
) -> None:
    """③ move 성공 + 빈 격리 DELETE ④ 충돌 fail-close(무변경) ⑥ actor 기록."""

    theme_id, source_id = await _seed_foundations(migrated_session)
    target = await create_curation_collection(
        migrated_session,
        collection_key="h22:move-target",
        theme_id=theme_id,
        source_id=source_id,
        title="이동 target",
    )
    quarantine_id = await _plant_quarantine_collection(
        migrated_session,
        theme_id=theme_id,
        source_id=source_id,
        original_collection_id=target.collection_id,
    )
    conflict_target_item, _ = await add_curation_item(
        migrated_session,
        collection_id=target.collection_id,
        feature_id=None,
        external_item_id="dup-ext",
        place_name="선점 항목",
        actor="seeder",
    )
    movable_1, _ = await add_curation_item(
        migrated_session,
        collection_id=quarantine_id,
        feature_id=None,
        external_item_id="move-1",
        place_name="이동 1",
        actor="seeder",
    )
    movable_2, _ = await add_curation_item(
        migrated_session,
        collection_id=quarantine_id,
        feature_id=None,
        external_item_id="move-2",
        place_name="이동 2",
        actor="seeder",
    )
    conflicted, _ = await add_curation_item(
        migrated_session,
        collection_id=quarantine_id,
        feature_id=None,
        external_item_id="dup-ext",
        place_name="충돌 항목",
        actor="seeder",
    )

    async def _item_states() -> dict[str, tuple[str, str]]:
        rows = (
            (
                await migrated_session.execute(
                    text(
                        "SELECT curation_item_id::text AS curation_item_id, "
                        "       collection_id::text AS collection_id, updated_by "
                        "FROM feature.curation_items "
                        "WHERE curation_item_id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {
                        "ids": [
                            movable_1.curation_item_id,
                            movable_2.curation_item_id,
                            conflicted.curation_item_id,
                        ]
                    },
                )
            )
            .mappings()
            .all()
        )
        return {
            row["curation_item_id"]: (row["collection_id"], row["updated_by"])
            for row in rows
        }

    # ④ 전체 이동은 충돌 1건 때문에 원자적으로 거부되고 아무 행도 안 바뀐다.
    before = await _item_states()
    with pytest.raises(CurationQuarantineMoveConflictError) as conflict_info:
        await move_curation_quarantine_items(
            migrated_session,
            collection_id=quarantine_id,
            actor="ops:h22-reviewer",
        )
    assert [
        (c.curation_item_id, c.conflict_kind, c.conflict_item_id)
        for c in conflict_info.value.conflicts
    ] == [
        (
            conflicted.curation_item_id,
            "component_identity_conflict",
            conflict_target_item.curation_item_id,
        )
    ]
    assert await _item_states() == before
    assert before[movable_1.curation_item_id] == (quarantine_id, "seeder")

    # 중복 item_ids는 422 계약(ValueError)이다.
    with pytest.raises(ValueError, match="중복"):
        await move_curation_quarantine_items(
            migrated_session,
            collection_id=quarantine_id,
            item_ids=[movable_1.curation_item_id, movable_1.curation_item_id],
            actor="ops:h22-reviewer",
        )

    # marker 없는 collection은 move 대상이 아니다 (⑦의 move 측).
    with pytest.raises(LookupError, match="quarantine collection 없음"):
        await move_curation_quarantine_items(
            migrated_session,
            collection_id=target.collection_id,
            actor="ops:h22-reviewer",
        )

    # 부분 이동(충돌 없는 subset)은 성공하고 actor가 updated_by에 박힌다 (⑥).
    moved_ids, deleted = await move_curation_quarantine_items(
        migrated_session,
        collection_id=quarantine_id,
        item_ids=[movable_1.curation_item_id, movable_2.curation_item_id],
        actor="ops:h22-reviewer",
    )
    assert set(moved_ids) == {movable_1.curation_item_id, movable_2.curation_item_id}
    assert deleted is False
    after_partial = await _item_states()
    assert after_partial[movable_1.curation_item_id] == (
        target.collection_id,
        "ops:h22-reviewer",
    )
    assert after_partial[movable_2.curation_item_id] == (
        target.collection_id,
        "ops:h22-reviewer",
    )
    assert after_partial[conflicted.curation_item_id] == (quarantine_id, "seeder")

    # archived target은 409 계약의 전용 예외로 거부된다.
    archived_target = await create_curation_collection(
        migrated_session,
        collection_key="h22:archived-target",
        theme_id=theme_id,
        source_id=None,
        title="archive된 target",
    )
    await archive_curation_collection(
        migrated_session,
        collection_id=archived_target.collection_id,
        actor="seeder",
    )
    with pytest.raises(CurationQuarantineTargetArchivedError):
        await move_curation_quarantine_items(
            migrated_session,
            collection_id=quarantine_id,
            target_collection_id=archived_target.collection_id,
            actor="ops:h22-reviewer",
        )

    # 존재하지 않는 target은 404 계약(LookupError)이다.
    with pytest.raises(LookupError, match="target collection 없음"):
        await move_curation_quarantine_items(
            migrated_session,
            collection_id=quarantine_id,
            target_collection_id=str(uuid4()),
            actor="ops:h22-reviewer",
        )

    # ③ 남은 item을 빈 target으로 옮기면 격리 collection 행이 DELETE된다.
    fresh_target = await create_curation_collection(
        migrated_session,
        collection_key="h22:fresh-target",
        theme_id=theme_id,
        source_id=None,
        title="새 target",
    )
    moved_ids, deleted = await move_curation_quarantine_items(
        migrated_session,
        collection_id=quarantine_id,
        target_collection_id=fresh_target.collection_id,
        actor="ops:h22-reviewer",
    )
    assert moved_ids == (conflicted.curation_item_id,)
    assert deleted is True
    remaining = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM feature.curation_collections "
                "WHERE collection_id = CAST(:collection_id AS uuid)"
            ),
            {"collection_id": quarantine_id},
        )
    ).scalar_one()
    assert remaining == 0
    final_states = await _item_states()
    assert final_states[conflicted.curation_item_id] == (
        fresh_target.collection_id,
        "ops:h22-reviewer",
    )


async def test_quarantine_confirm_standalone_removes_marker_only(
    migrated_session: AsyncSession,
) -> None:
    """⑤ marker 키 제거 + key/title 갱신 ⑥ actor 기록 ⑦ marker 없으면 LookupError."""

    theme_id, source_id = await _seed_foundations(migrated_session)
    original = await create_curation_collection(
        migrated_session,
        collection_key="h22:standalone-original",
        theme_id=theme_id,
        source_id=source_id,
        title="원본",
    )
    quarantine_id = await _plant_quarantine_collection(
        migrated_session,
        theme_id=theme_id,
        source_id=source_id,
        original_collection_id=original.collection_id,
        extra_metadata={"note": "keep-me"},
    )
    await add_curation_item(
        migrated_session,
        collection_id=quarantine_id,
        feature_id=None,
        external_item_id="standalone-1",
        place_name="독립 항목",
        actor="seeder",
    )

    confirmed_id, confirmed_key = await confirm_curation_quarantine_standalone(
        migrated_session,
        collection_id=quarantine_id,
        collection_key="  h22:standalone-confirmed  ",
        title="  독립 확정  ",
        actor="ops:h22-reviewer",
    )

    assert confirmed_id == quarantine_id
    assert confirmed_key == "h22:standalone-confirmed"
    row = (
        (
            await migrated_session.execute(
                text(
                    "SELECT collection_key, title, status, visibility, metadata, "
                    "       created_by, updated_by "
                    "FROM feature.curation_collections "
                    "WHERE collection_id = CAST(:collection_id AS uuid)"
                ),
                {"collection_id": quarantine_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["collection_key"] == "h22:standalone-confirmed"
    assert row["title"] == "독립 확정"
    assert row["status"] == "draft"
    assert row["visibility"] == "admin_only"
    assert row["created_by"] == "migration:0065"
    assert row["updated_by"] == "ops:h22-reviewer"
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    assert metadata == {"note": "keep-me"}

    # 확정된 collection은 더 이상 격리 정본 술어에 안 걸린다.
    rows, _ = await list_curation_quarantine_collections(migrated_session)
    assert [r.collection_id for r in rows] == []
    with pytest.raises(LookupError, match="quarantine collection 없음"):
        await confirm_curation_quarantine_standalone(
            migrated_session,
            collection_id=quarantine_id,
            collection_key="h22:standalone-again",
            title="재확정",
            actor="ops:h22-reviewer",
        )

    # 빈 key/title은 422 계약(ValueError)이다.
    with pytest.raises(ValueError, match="required"):
        await confirm_curation_quarantine_standalone(
            migrated_session,
            collection_id=quarantine_id,
            collection_key="   ",
            title="제목",
            actor="ops:h22-reviewer",
        )

    # 중복 collection_key는 unique 제약 IntegrityError로 fail-close한다 (마지막
    # 단언 — 이 시점 이후 transaction은 abort 상태라 teardown rollback에 맡긴다).
    second_quarantine_id = await _plant_quarantine_collection(
        migrated_session,
        theme_id=theme_id,
        source_id=None,
        original_collection_id=None,
    )
    with pytest.raises(IntegrityError):
        await confirm_curation_quarantine_standalone(
            migrated_session,
            collection_id=second_quarantine_id,
            collection_key="h22:standalone-confirmed",
            title="중복 확정",
            actor="ops:h22-reviewer",
        )
