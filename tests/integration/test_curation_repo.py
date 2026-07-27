"""회차·출처가 겹치는 Feature 큐레이션 membership 통합 검증."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text

from kortravelmap.infra.curation_repo import (
    _GET_COLLECTION_ID_BY_KEY_SQL,  # noqa: PLC2701 - concurrency regression
    _GET_SOURCE_ID_BY_KEY_SQL,  # noqa: PLC2701 - concurrency regression
    _LIST_FEATURE_ITEMS_SQL,  # noqa: PLC2701 - EXPLAIN 대상
    _RESOLVE_FEATURES_BATCH_SQL,  # noqa: PLC2701 - EXPLAIN 대상
    _UPSERT_COLLECTION_SQL,  # noqa: PLC2701 - concurrency regression
    _UPSERT_SOURCE_SQL,  # noqa: PLC2701 - concurrency regression
    CurationImportResult,
    FeatureMatchRequest,
    ResolvedCurationImportRow,
    _upsert_id_with_fallback,  # noqa: PLC2701 - concurrency regression
    add_curation_item,
    archive_curation_item,
    create_curation_collection,
    decode_collection_cursor,
    get_curation_collection,
    get_curation_item,
    get_feature_curation_group,
    import_curation_rows,
    list_curation_collections,
    list_feature_curation_groups,
    preview_curation_import,
    resolve_feature_matches,
    update_curation_item,
    upsert_curation_theme,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_FEATURE_ID = "feature:curation-multi-test"


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
                        provider, dataset_key, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        'python-mcst-api', 'tourism-100-test', '문화체육관광부',
                        'manual', 'unknown', 'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id::text
                    """
                )
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

    await migrated_session.execute(
        text("UPDATE feature.features SET status = 'hidden' WHERE feature_id = :feature_id"),
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
        "provider": "csv-import-provider",
        "dataset_key": "csv-import-dataset",
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
    }
    assert second == {
        "rows": 3,
        "collections": 1,
        "inserted": 0,
        "updated": 0,
        "removed": 0,
        "removals": (),
    }
    assert no_op_plan.inserted == 0
    assert no_op_plan.updated == 0
    assert no_op_plan.removals == ()
    assert replacement_plan.inserted == 1
    assert replacement_plan.updated == 0
    assert {item.external_item_id for item in replacement_plan.removals} == {
        "item-a",
        "item-b",
    }
    assert replaced == {
        "rows": 2,
        "collections": 1,
        "inserted": 1,
        "updated": 0,
        "removed": 2,
        "removals": replacement_plan.removals,
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
    assert counts == (2, 4)
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
        "provider": "csv-reimport-provider",
        "dataset_key": "csv-reimport-dataset",
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
        "provider": "csv-archive-provider",
        "dataset_key": "csv-archive-dataset",
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


async def test_source_and_collection_fallbacks_see_concurrent_identical_insert(
    migrated_engine: AsyncEngine,
) -> None:
    """import 전용 source/collection upsert도 새 statement snapshot을 사용한다."""

    from sqlalchemy.ext.asyncio import AsyncSession

    suffix = uuid4().hex
    theme_slug = f"concurrent-import-foundation-{suffix}"
    source_params = {
        "provider": f"concurrent-source-{suffix}",
        "dataset_key": "dataset",
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
                            provider, dataset_key, source_name, source_url,
                            source_kind, update_cycle, provider_status, metadata
                        ) VALUES (
                            :provider, :dataset_key, :source_name, :source_url,
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
                lookup_sql=_GET_SOURCE_ID_BY_KEY_SQL,
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
                    "WHERE provider = :provider AND dataset_key = :dataset_key"
                ),
                source_params,
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
        "provider": f"concurrent-import-provider-{suffix}",
        "dataset_key": "concurrent-import-dataset",
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
                    "DELETE FROM feature.curation_collections "
                    "WHERE collection_key = :collection_key"
                ),
                {"collection_key": common["collection_key"]},
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_sources "
                    "WHERE provider = :provider AND dataset_key = :dataset_key"
                ),
                {
                    "provider": common["provider"],
                    "dataset_key": common["dataset_key"],
                },
            )
            await connection.execute(
                text("DELETE FROM feature.curated_themes WHERE theme_slug = :theme_slug"),
                {"theme_slug": common["theme_slug"]},
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

    with pytest.raises(ValueError, match="미연결 항목이 이미 존재"):
        await add_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            feature_id=_FEATURE_ID,
            external_item_id="unmatched-lighthouse",
            actor="invalid-resolver",
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
    with pytest.raises(ValueError, match="Feature 연결 항목이 이미 존재"):
        await add_curation_item(
            migrated_session,
            collection_id=collection.collection_id,
            feature_id=None,
            external_item_id="unmatched-lighthouse",
            place_name="중복 미연결 등대",
            actor="invalid-writer",
        )

    await migrated_session.execute(
        text("UPDATE feature.features SET status = 'hidden' WHERE feature_id = :feature_id"),
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

    assert "idx_curation_items_feature_status_collection" in index_names(plan)

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
    assert "idx_features_lower_name_keyset" in index_names(match_plan)
