"""T-VN-40 Map→PinVi snapshot 문자열 경계의 실제 catalog/DB 검증."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_snapshot_text_bounds_are_validated_and_fail_closed(
    migrated_session: AsyncSession,
) -> None:
    """producer DB가 paired consumer보다 긴 문자열을 저장하지 못하게 한다."""

    constraint_rows = (
        await migrated_session.execute(
            text(
                """
                SELECT con.conname, con.convalidated
                  FROM pg_catalog.pg_constraint AS con
                  JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid
                  JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace
                 WHERE ns.nspname = 'feature'
                   AND con.conname IN (
                       'ck_curated_themes_snapshot_text_bounds',
                       'ck_curation_collections_snapshot_text_bounds'
                   )
                 ORDER BY con.conname
                """
            )
        )
    ).all()
    assert constraint_rows == [
        ("ck_curated_themes_snapshot_text_bounds", True),
        ("ck_curation_collections_snapshot_text_bounds", True),
    ]

    theme_id = str(uuid4())
    collection_id = str(uuid4())
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.curated_themes (
                theme_id, theme_slug, theme_name, theme_group, owner_kind
            ) VALUES (
                CAST(:theme_id AS uuid), :theme_slug, :theme_name, 'paired-boundary',
                'operator'
            )
            """
        ),
        {"theme_id": theme_id, "theme_slug": "s" * 128, "theme_name": "n" * 200},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.curation_collections (
                collection_id, collection_key, theme_id, title, edition_key
            ) VALUES (
                CAST(:collection_id AS uuid), :collection_key,
                CAST(:theme_id AS uuid), :title, :edition_key
            )
            """
        ),
        {
            "collection_id": collection_id,
            "collection_key": f"paired-boundary:{collection_id}",
            "theme_id": theme_id,
            "title": "t" * 300,
            "edition_key": "e" * 100,
        },
    )

    invalid_updates = (
        (
            "UPDATE feature.curated_themes SET theme_slug = :value "
            "WHERE theme_id = CAST(:row_id AS uuid)",
            theme_id,
            "s" * 129,
            "ck_curated_themes_snapshot_text_bounds",
        ),
        (
            "UPDATE feature.curated_themes SET theme_name = :value "
            "WHERE theme_id = CAST(:row_id AS uuid)",
            theme_id,
            "n" * 201,
            "ck_curated_themes_snapshot_text_bounds",
        ),
        (
            "UPDATE feature.curation_collections SET title = :value "
            "WHERE collection_id = CAST(:row_id AS uuid)",
            collection_id,
            "t" * 301,
            "ck_curation_collections_snapshot_text_bounds",
        ),
        (
            "UPDATE feature.curation_collections SET edition_key = :value "
            "WHERE collection_id = CAST(:row_id AS uuid)",
            collection_id,
            "e" * 101,
            "ck_curation_collections_snapshot_text_bounds",
        ),
    )
    for statement, row_id, value, constraint_name in invalid_updates:
        with pytest.raises(IntegrityError, match=constraint_name):
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(statement),
                    {"row_id": row_id, "value": value},
                )
