"""0045가 기존 flat curated overlay를 collection/item으로 보존하는지 검증."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_legacy_curations_are_backfilled_without_membership_loss(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"curation_migration_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)

    async def assert_downgrade_blocked() -> None:
        nonlocal target_engine

        await target_engine.dispose()
        with pytest.raises(DBAPIError, match="0045 downgrade blocked") as error:
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                "0044_source_entities",
                downgrade=True,
            )
        assert getattr(error.value.orig, "sqlstate", None) == "P0001"
        target_engine = make_async_engine(target_dsn)

    try:
        await asyncio.to_thread(_run_alembic, target_dsn, "0044_source_entities")
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category, marker_icon, marker_color
                    ) VALUES (
                        'feature:legacy-curation', 'place', '기존 큐레이션 장소',
                        '01070100', 'place', 'P-01'
                    )
                    """
                )
            )
            theme_ids = (
                (
                    await connection.execute(
                        text(
                            """
                        INSERT INTO feature.curated_themes (
                            theme_slug, theme_name, theme_description, theme_group,
                            default_curated, visibility, metadata
                        ) VALUES
                            ('legacy-edition-a', '기존 회차 A', '', 'test', false,
                             'public', '{}'::jsonb),
                            ('legacy-edition-b', '기존 회차 B', '', 'test', false,
                             'public', '{}'::jsonb)
                        RETURNING theme_id::text
                        """
                        )
                    )
                )
                .scalars()
                .all()
            )
            source_id = (
                await connection.execute(
                    text(
                        """
                        INSERT INTO feature.curated_sources (
                            provider, dataset_key, source_name, source_kind,
                            update_cycle, provider_status, metadata
                        ) VALUES (
                            'migration-test', 'legacy-curation-source', '기존 출처',
                            'manual', 'unknown', 'manual_only', '{}'::jsonb
                        )
                        RETURNING source_id::text
                        """
                    )
                )
            ).scalar_one()
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, curation_status,
                        selection_origin, display_title, display_summary,
                        curation_relation, reuse_policy, metadata
                    ) VALUES
                        (CAST(:theme_a AS uuid), 'feature:legacy-curation',
                         CAST(:source_id AS uuid), 'curated', 'admin',
                         '2023 기존 목록', '2023 설명', 'nearby_option',
                         'manual_review', '{"edition":"2023"}'::jsonb),
                        (CAST(:theme_b AS uuid), 'feature:legacy-curation',
                         CAST(:source_id AS uuid), 'curated', 'admin',
                         '2025 기존 목록', '2025 설명', 'nearby_option',
                         'manual_review', '{"edition":"2025"}'::jsonb)
                    """
                ),
                {
                    "theme_a": theme_ids[0],
                    "theme_b": theme_ids[1],
                    "source_id": source_id,
                },
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, "0045_curation_collections")
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            collections = (
                await connection.execute(
                    text(
                        "SELECT title, status, visibility "
                        "FROM feature.curation_collections "
                        "WHERE collection_key LIKE 'legacy:%' ORDER BY title"
                    )
                )
            ).all()
            items = (
                await connection.execute(
                    text(
                        "SELECT i.feature_id, i.status, i.metadata "
                        "FROM feature.curation_items AS i "
                        "JOIN feature.curation_collections AS c "
                        "ON c.collection_id = i.collection_id "
                        "WHERE c.collection_key LIKE 'legacy:%' "
                        "ORDER BY c.title"
                    )
                )
            ).all()

        assert collections == [
            ("2023 기존 목록", "published", "public"),
            ("2025 기존 목록", "published", "public"),
        ]
        assert [row.feature_id for row in items] == [
            "feature:legacy-curation",
            "feature:legacy-curation",
        ]
        assert [row.status for row in items] == ["included", "included"]
        assert {row.metadata["edition"] for row in items} == {"2023", "2025"}

        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curated_features
                    SET curation_status = 'rejected', updated_at = now()
                    WHERE display_title = '2025 기존 목록'
                    """
                )
            )
        async with target_engine.connect() as connection:
            synced_status = (
                await connection.execute(
                    text(
                        """
                        SELECT i.status
                        FROM feature.curation_items AS i
                        JOIN feature.curation_collections AS c
                          ON c.collection_id = i.collection_id
                        WHERE c.title = '2025 기존 목록'
                        """
                    )
                )
            ).scalar_one()
        assert synced_status == "rejected"

        # 이후 downgrade 성공 경로 검증을 위해 legacy와 collection을 다시 같은 상태로 둔다.
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curated_features
                    SET curation_status = 'curated', updated_at = now()
                    WHERE display_title = '2025 기존 목록'
                    """
                )
            )

        # 새 계약에만 존재하는 collection/item은 legacy downgrade로 표현할 수 없다.
        # migration은 이를 조용히 DROP하지 않고 원 transaction을 거절해야 한다.
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    WITH new_collection AS (
                        INSERT INTO feature.curation_collections (
                            collection_key, theme_id, source_id, title,
                            edition_key, status, visibility, metadata
                        ) VALUES (
                            'manual-only:2026', CAST(:theme_id AS uuid),
                            CAST(:source_id AS uuid), '신규 전용 목록', '2026',
                            'published', 'public', '{"origin":"manual"}'::jsonb
                        )
                        RETURNING collection_id
                    )
                    INSERT INTO feature.curation_items (
                        collection_id, feature_id, external_item_id,
                        place_name, status
                    )
                    SELECT collection_id, 'feature:legacy-curation',
                           'manual-only-item', '신규 전용 장소', 'included'
                    FROM new_collection
                    """
                ),
                {"theme_id": theme_ids[0], "source_id": source_id},
            )

        await assert_downgrade_blocked()
        async with target_engine.begin() as connection:
            version = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            preserved = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM feature.curation_items AS i "
                        "JOIN feature.curation_collections AS c "
                        "ON c.collection_id = i.collection_id "
                        "WHERE c.collection_key = 'manual-only:2026'"
                    )
                )
            ).scalar_one()
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_collections "
                    "WHERE collection_key = 'manual-only:2026'"
                )
            )
        assert version == "0045_curation_collections"
        assert preserved == 1

        async with target_engine.connect() as connection:
            guarded_ids = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            c.collection_id::text AS collection_id,
                            i.curation_item_id::text AS curation_item_id
                        FROM feature.curation_collections AS c
                        JOIN feature.curation_items AS i
                          ON i.collection_id = c.collection_id
                        WHERE c.title = '2023 기존 목록'
                        """
                    )
                )
            ).one()

        # legacy backfill 뒤 item 표시/주소만 수동 변경해도 downgrade 시 유실된다.
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_items
                    SET place_name = '수동 변경 장소',
                        address_hint = '수동 변경 주소'
                    WHERE curation_item_id = CAST(:item_id AS uuid)
                    """
                ),
                {"item_id": guarded_ids.curation_item_id},
            )
        await assert_downgrade_blocked()
        async with target_engine.begin() as connection:
            preserved_item = (
                await connection.execute(
                    text(
                        """
                        SELECT place_name, address_hint
                        FROM feature.curation_items
                        WHERE curation_item_id = CAST(:item_id AS uuid)
                        """
                    ),
                    {"item_id": guarded_ids.curation_item_id},
                )
            ).one()
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_items AS i
                    SET place_name = f.name,
                        address_hint = COALESCE(
                            f.address ->> 'road',
                            f.address ->> 'legal'
                        )
                    FROM feature.curated_features AS cf
                    JOIN feature.features AS f ON f.feature_id = cf.feature_id
                    WHERE i.curation_item_id = cf.curated_feature_id
                      AND i.curation_item_id = CAST(:item_id AS uuid)
                    """
                ),
                {"item_id": guarded_ids.curation_item_id},
            )
        assert preserved_item == ("수동 변경 장소", "수동 변경 주소")

        # 생성/수정 시각 역시 legacy가 표현할 수 없는 독립 변경이다.
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_items
                    SET created_at = created_at - interval '1 day',
                        updated_at = updated_at + interval '1 day'
                    WHERE curation_item_id = CAST(:item_id AS uuid)
                    """
                ),
                {"item_id": guarded_ids.curation_item_id},
            )
        await assert_downgrade_blocked()
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_items AS i
                    SET created_at = cf.created_at,
                        updated_at = cf.updated_at
                    FROM feature.curated_features AS cf
                    WHERE i.curation_item_id = cf.curated_feature_id
                      AND i.curation_item_id = CAST(:item_id AS uuid)
                    """
                ),
                {"item_id": guarded_ids.curation_item_id},
            )

        # collection의 backfill 계산 결과 중 기존 guard가 보지 않던 필드를 바꾼다.
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_collections
                    SET theme_id = CAST(:other_theme_id AS uuid),
                        title = '수동 변경 목록',
                        edition_key = 'manual-edition',
                        description = '수동 변경 설명',
                        status = 'draft',
                        visibility = 'admin_only',
                        metadata = metadata || jsonb_build_object('manual', true),
                        created_at = created_at - interval '1 day',
                        updated_at = updated_at + interval '1 day',
                        archived_at = now()
                    WHERE collection_id = CAST(:collection_id AS uuid)
                    """
                ),
                {
                    "collection_id": guarded_ids.collection_id,
                    "other_theme_id": theme_ids[1],
                },
            )
        await assert_downgrade_blocked()
        async with target_engine.begin() as connection:
            preserved_collection = (
                await connection.execute(
                    text(
                        """
                        SELECT title, edition_key, metadata ->> 'manual'
                        FROM feature.curation_collections
                        WHERE collection_id = CAST(:collection_id AS uuid)
                        """
                    ),
                    {"collection_id": guarded_ids.collection_id},
                )
            ).one()
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_collections AS c
                    SET theme_id = cf.theme_id,
                        source_id = cf.source_id,
                        title = COALESCE(
                            NULLIF(btrim(cf.display_title), ''),
                            s.source_name
                        ),
                        edition_key = '',
                        description = cf.display_summary,
                        status = CASE
                            WHEN cf.curation_status = 'curated' THEN 'published'
                            WHEN cf.curation_status = 'archived' THEN 'archived'
                            ELSE 'draft'
                        END,
                        visibility = CASE
                            WHEN t.visibility = 'public' THEN 'public'
                            ELSE 'admin_only'
                        END,
                        metadata = jsonb_build_object(
                            'migrated_from',
                            'feature.curated_features'
                        ),
                        created_by = NULL,
                        updated_by = NULL,
                        created_at = cf.created_at,
                        updated_at = cf.updated_at,
                        archived_at = cf.archived_at
                    FROM feature.curated_features AS cf
                    JOIN feature.curated_themes AS t
                      ON t.theme_id = cf.theme_id
                    JOIN feature.curated_sources AS s
                      ON s.source_id = cf.source_id
                    WHERE c.collection_id = CAST(:collection_id AS uuid)
                      AND cf.display_title = '2023 기존 목록'
                    """
                ),
                {"collection_id": guarded_ids.collection_id},
            )
        assert preserved_collection == (
            "수동 변경 목록",
            "manual-edition",
            "true",
        )

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            "0044_source_entities",
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            new_tables = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'feature' "
                        "AND table_name IN ('curation_collections','curation_items')"
                    )
                )
            ).scalar_one()
            legacy_count = (
                await connection.execute(text("SELECT count(*) FROM feature.curated_features"))
            ).scalar_one()
        assert new_tables == 0
        assert legacy_count == 2
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()
