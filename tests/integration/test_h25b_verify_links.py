"""H34 verifier 공개 모집단이 public curation repository 정본을 따르는지 검증."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.curation_repo import (
    add_curation_item,
    create_curation_collection,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "h25b_verify_links.py"
_SPEC = importlib.util.spec_from_file_location("h25b_verify_links_integration", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules["h25b_verify_links_integration"] = _MOD
_SPEC.loader.exec_module(_MOD)


async def _feature(session: AsyncSession, suffix: str) -> str:
    feature_id = f"feature:h34-public:{suffix}:{uuid4().hex}"
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, address,
                marker_icon, marker_color
            ) VALUES (
                :feature_id, 'place', :name, '01020300',
                '{"sido_code":"43","road":"충북 테스트"}'::jsonb,
                'place', 'P-01'
            )
            """
        ),
        {"feature_id": feature_id, "name": f"H34 {suffix}"},
    )
    return feature_id


async def _seed_public_scope_boundaries(
    session: AsyncSession,
) -> tuple[str, str, tuple[str, ...]]:
    token = uuid4().hex
    theme_rows = (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_description, theme_group,
                        default_curated, visibility, metadata
                    ) VALUES
                      (:public_slug, '공개 테마', '', 'official', false, 'public', '{}'),
                      (:private_slug, '비공개 테마', '', 'official', false, 'admin_only', '{}')
                    RETURNING theme_slug, theme_id::text
                    """
                ),
                {
                    "public_slug": f"h34-public-{token}",
                    "private_slug": f"h34-private-{token}",
                },
            )
        )
        .mappings()
        .all()
    )
    themes = {str(row["theme_slug"]): str(row["theme_id"]) for row in theme_rows}
    public_theme = themes[f"h34-public-{token}"]
    private_theme = themes[f"h34-private-{token}"]

    public_collection = await create_curation_collection(
        session,
        collection_key=f"h34-public:{token}",
        theme_id=public_theme,
        source_id=None,
        title="공개 collection",
        status="published",
        visibility="public",
    )
    draft_collection = await create_curation_collection(
        session,
        collection_key=f"h34-draft:{token}",
        theme_id=public_theme,
        source_id=None,
        title="draft collection",
        status="draft",
        visibility="public",
    )
    admin_collection = await create_curation_collection(
        session,
        collection_key=f"h34-admin:{token}",
        theme_id=public_theme,
        source_id=None,
        title="admin collection",
        status="published",
        visibility="admin_only",
    )
    private_theme_collection = await create_curation_collection(
        session,
        collection_key=f"h34-private-theme:{token}",
        theme_id=private_theme,
        source_id=None,
        title="private theme collection",
        status="published",
        visibility="public",
    )

    public_feature = await _feature(session, "public")
    candidate_feature = await _feature(session, "candidate")
    absent_feature = await _feature(session, "source-absent")
    draft_feature = await _feature(session, "draft-collection")
    admin_feature = await _feature(session, "admin-collection")
    private_theme_feature = await _feature(session, "private-theme")
    inactive_feature = await _feature(session, "inactive")
    feature_ids = (
        public_feature,
        candidate_feature,
        absent_feature,
        draft_feature,
        admin_feature,
        private_theme_feature,
        inactive_feature,
    )

    await add_curation_item(
        session,
        collection_id=public_collection.collection_id,
        feature_id=public_feature,
        external_item_id="public",
        status="included",
    )
    await session.execute(
        text(
            """
            UPDATE feature.features
               SET name = 'Ａ   관광지'
             WHERE feature_id = :feature_id
            """
        ),
        {"feature_id": public_feature},
    )
    await session.execute(
        text(
            """
            UPDATE feature.curation_items
               SET place_name = 'A 관광지'
             WHERE collection_id = CAST(:collection_id AS uuid)
               AND external_item_id = 'public'
            """
        ),
        {"collection_id": public_collection.collection_id},
    )
    await add_curation_item(
        session,
        collection_id=public_collection.collection_id,
        feature_id=candidate_feature,
        external_item_id="candidate",
        status="candidate",
    )
    absent_item, _ = await add_curation_item(
        session,
        collection_id=public_collection.collection_id,
        feature_id=absent_feature,
        external_item_id="source-absent",
        status="included",
    )
    await session.execute(
        text(
            "UPDATE feature.curation_items SET source_present = false "
            "WHERE curation_item_id = CAST(:item_id AS uuid)"
        ),
        {"item_id": absent_item.curation_item_id},
    )
    await add_curation_item(
        session,
        collection_id=draft_collection.collection_id,
        feature_id=draft_feature,
        external_item_id="draft-collection",
        status="included",
    )
    await add_curation_item(
        session,
        collection_id=admin_collection.collection_id,
        feature_id=admin_feature,
        external_item_id="admin-collection",
        status="included",
    )
    await add_curation_item(
        session,
        collection_id=private_theme_collection.collection_id,
        feature_id=private_theme_feature,
        external_item_id="private-theme",
        status="included",
    )
    await add_curation_item(
        session,
        collection_id=public_collection.collection_id,
        feature_id=inactive_feature,
        external_item_id="inactive-feature",
        status="included",
    )
    await session.execute(
        text(
            "UPDATE feature.features SET status = 'inactive' "
            "WHERE feature_id = :feature_id"
        ),
        {"feature_id": inactive_feature},
    )
    return token, public_feature, feature_ids


async def _cleanup(
    engine: AsyncEngine,
    *,
    token: str,
    feature_ids: tuple[str, ...],
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        await session.execute(
            text(
                "DELETE FROM feature.curation_collections "
                "WHERE collection_key LIKE :collection_key"
            ),
            {"collection_key": f"h34-%:{token}"},
        )
        await session.execute(
            text(
                "DELETE FROM feature.curated_themes "
                "WHERE theme_slug IN (:public_slug, :private_slug)"
            ),
            {
                "public_slug": f"h34-public-{token}",
                "private_slug": f"h34-private-{token}",
            },
        )
        await session.execute(
            text("DELETE FROM feature.features WHERE feature_id = ANY(:feature_ids)"),
            {"feature_ids": list(feature_ids)},
        )


async def test_public_audit_uses_committed_repeatable_read_repository_snapshot(
    migrated_engine: AsyncEngine,
) -> None:
    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        token, public_feature, feature_ids = await _seed_public_scope_boundaries(session)

    try:
        report = await _MOD.audit_database(
            migrated_engine.url.render_as_string(hide_password=False),
            scope="public",
        )
        token_results = [
            result
            for result in report["results"]
            if str(result["collection_key"]).endswith(token)
        ]

        assert [
            (result["feature_id"], result["external_item_id"])
            for result in token_results
        ] == [(public_feature, "public")]
        assert token_results[0]["axes"]["linked_name"] == "pass"
        assert token_results[0]["evidence"]["exact_name_candidate_feature_ids"] == [
            public_feature
        ]
        assert (
            token_results[0]["evidence"]["linked_feature_is_exact_name_candidate"]
            is True
        )
        assert report["schema_version"] == 2
        assert report["scope"] == "public"
        assert report["population"]["kind"] == "public-curation-repository"
        assert report["target_count"] >= 1
        assert report["snapshot"]["transaction_snapshot"]
        assert report["snapshot"]["database_name"]
        assert report["snapshot"]["isolation_level"] == "repeatable read"
        assert report["snapshot"]["read_only"] == "on"
        assert report["snapshot"]["transaction_started_at"]
    finally:
        await _cleanup(
            migrated_engine,
            token=token,
            feature_ids=feature_ids,
        )
