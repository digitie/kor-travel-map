"""authoritative 큐레이션 source presence를 membership과 분리한다.

Revision ID: 0065_curation_source_presence
Revises: 0064_price_series_identity
Create Date: 2026-07-27

CSV에서 일시 누락된 membership을 삭제하면 운영자 status/relation/reuse override가
재등장 때 소실된다. ``source_present``를 durable membership에 저장해 누락은 비공개
상태 전환으로 표현하고, operator archive tombstone과 구분한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0065_curation_source_presence"
down_revision: str | Sequence[str] | None = "0064_price_series_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SYNC_FUNCTION_0065 = """
CREATE OR REPLACE FUNCTION feature.sync_curated_feature_collection()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_collection_id uuid;
    target_collection_key text;
    target_title text;
    target_external_item_id text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        UPDATE feature.curation_items
        SET source_present = false,
            updated_by = OLD.selected_by,
            updated_at = now()
        WHERE curation_item_id = OLD.curated_feature_id
          AND archived_at IS NULL
          AND source_present;
        RETURN OLD;
    END IF;

    SELECT
        'legacy:' || t.theme_slug || ':' || substr(md5(
            NEW.source_id::text || ':' ||
            COALESCE(NULLIF(btrim(NEW.display_title), ''), s.source_name)
        ), 1, 20),
        COALESCE(NULLIF(btrim(NEW.display_title), ''), s.source_name)
    INTO target_collection_key, target_title
    FROM feature.curated_themes AS t
    JOIN feature.curated_sources AS s ON s.source_id = NEW.source_id
    WHERE t.theme_id = NEW.theme_id;

    INSERT INTO feature.curation_collections (
        collection_key, theme_id, source_id, title, edition_key,
        description, status, visibility, metadata,
        created_at, updated_at, archived_at
    )
    SELECT
        target_collection_key,
        NEW.theme_id,
        NEW.source_id,
        target_title,
        '',
        NEW.display_summary,
        'published',
        CASE WHEN t.visibility = 'public' THEN 'public' ELSE 'admin_only' END,
        jsonb_build_object('migrated_from', 'feature.curated_features'),
        NEW.created_at,
        NEW.updated_at,
        NULL
    FROM feature.curated_themes AS t
    WHERE t.theme_id = NEW.theme_id
    ON CONFLICT (collection_key) DO UPDATE SET
        theme_id = EXCLUDED.theme_id,
        source_id = EXCLUDED.source_id,
        title = EXCLUDED.title,
        description = EXCLUDED.description,
        status = 'published',
        visibility = EXCLUDED.visibility,
        updated_at = EXCLUDED.updated_at,
        archived_at = NULL
    RETURNING collection_id INTO target_collection_id;

    target_external_item_id :=
        COALESCE(NEW.source_record_key, NEW.curated_feature_id::text);

    -- Legacy writer가 제공자 파생 필드를 갱신해도 operator-owned 상태는 보존한다.
    -- exact identity tombstone 또는 다른 active row가 target을 소유하면 현재 legacy
    -- mirror만 source-absent로 내리고 해당 identity를 되살리지 않는다.
    UPDATE feature.curation_items AS item
    SET collection_id = target_collection_id,
        feature_id = NEW.feature_id,
        source_record_key = NEW.source_record_key,
        external_item_id = target_external_item_id,
        place_name = feature_row.name,
        address_hint = COALESCE(
            feature_row.address ->> 'road',
            feature_row.address ->> 'legal'
        ),
        source_present = NEW.archived_at IS NULL,
        sort_order = GREATEST(0, round(NEW.rank_score)::integer),
        item_summary = NEW.display_summary,
        metadata = NEW.metadata || jsonb_build_object(
            'legacy_selection_origin', NEW.selection_origin,
            'legacy_content_version', NEW.content_version
        ),
        updated_by = NEW.selected_by,
        updated_at = NEW.updated_at
    FROM feature.features AS feature_row
    WHERE item.curation_item_id = NEW.curated_feature_id
      AND item.archived_at IS NULL
      AND feature_row.feature_id = NEW.feature_id
      AND NOT EXISTS (
          SELECT 1
          FROM feature.curation_items AS occupied
          WHERE occupied.curation_item_id <> item.curation_item_id
            AND occupied.collection_id = target_collection_id
            AND occupied.external_item_id = target_external_item_id
            AND occupied.feature_id IS NOT DISTINCT FROM NEW.feature_id
      );

    IF FOUND THEN
        RETURN NEW;
    END IF;

    UPDATE feature.curation_items AS item
    SET source_present = false,
        updated_by = NEW.selected_by,
        updated_at = NEW.updated_at
    WHERE item.curation_item_id = NEW.curated_feature_id
      AND item.archived_at IS NULL
      AND item.source_present;

    IF FOUND OR EXISTS (
        SELECT 1
        FROM feature.curation_items
        WHERE curation_item_id = NEW.curated_feature_id
    ) THEN
        RETURN NEW;
    END IF;

    INSERT INTO feature.curation_items (
        curation_item_id, collection_id, feature_id, source_record_key,
        external_item_id, place_name, address_hint, source_present,
        status, sort_order, item_title, item_summary,
        curation_relation, reuse_policy, metadata,
        created_by, updated_by,
        created_at, updated_at, archived_at
    )
    SELECT
        NEW.curated_feature_id,
        target_collection_id,
        NEW.feature_id,
        NEW.source_record_key,
        target_external_item_id,
        feature_row.name,
        COALESCE(feature_row.address ->> 'road', feature_row.address ->> 'legal'),
        NEW.archived_at IS NULL,
        CASE NEW.curation_status
            WHEN 'curated' THEN 'included'
            ELSE NEW.curation_status
        END,
        GREATEST(0, round(NEW.rank_score)::integer),
        NULL,
        NEW.display_summary,
        NEW.curation_relation,
        NEW.reuse_policy,
        NEW.metadata || jsonb_build_object(
            'legacy_selection_origin', NEW.selection_origin,
            'legacy_content_version', NEW.content_version
        ),
        NEW.selected_by,
        NEW.selected_by,
        NEW.created_at,
        NEW.updated_at,
        NEW.archived_at
    FROM feature.features AS feature_row
    WHERE feature_row.feature_id = NEW.feature_id
      AND NOT EXISTS (
          SELECT 1
          FROM feature.curation_items AS occupied
          WHERE occupied.collection_id = target_collection_id
            AND occupied.external_item_id = target_external_item_id
            AND occupied.feature_id IS NOT DISTINCT FROM NEW.feature_id
      )
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$
"""


_SYNC_FUNCTION_0064 = """
CREATE OR REPLACE FUNCTION feature.sync_curated_feature_collection()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_collection_id uuid;
    target_collection_key text;
    target_title text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM feature.curation_items
        WHERE curation_item_id = OLD.curated_feature_id;
        RETURN OLD;
    END IF;

    SELECT
        'legacy:' || t.theme_slug || ':' || substr(md5(
            NEW.source_id::text || ':' ||
            COALESCE(NULLIF(btrim(NEW.display_title), ''), s.source_name)
        ), 1, 20),
        COALESCE(NULLIF(btrim(NEW.display_title), ''), s.source_name)
    INTO target_collection_key, target_title
    FROM feature.curated_themes AS t
    JOIN feature.curated_sources AS s ON s.source_id = NEW.source_id
    WHERE t.theme_id = NEW.theme_id;

    INSERT INTO feature.curation_collections (
        collection_key, theme_id, source_id, title, edition_key,
        description, status, visibility, metadata,
        created_at, updated_at, archived_at
    )
    SELECT
        target_collection_key,
        NEW.theme_id,
        NEW.source_id,
        target_title,
        '',
        NEW.display_summary,
        'published',
        CASE WHEN t.visibility = 'public' THEN 'public' ELSE 'admin_only' END,
        jsonb_build_object('migrated_from', 'feature.curated_features'),
        NEW.created_at,
        NEW.updated_at,
        NULL
    FROM feature.curated_themes AS t
    WHERE t.theme_id = NEW.theme_id
    ON CONFLICT (collection_key) DO UPDATE SET
        theme_id = EXCLUDED.theme_id,
        source_id = EXCLUDED.source_id,
        title = EXCLUDED.title,
        description = EXCLUDED.description,
        status = 'published',
        visibility = EXCLUDED.visibility,
        updated_at = EXCLUDED.updated_at,
        archived_at = NULL
    RETURNING collection_id INTO target_collection_id;

    DELETE FROM feature.curation_items
    WHERE curation_item_id = NEW.curated_feature_id;

    INSERT INTO feature.curation_items (
        curation_item_id, collection_id, feature_id, source_record_key,
        external_item_id, place_name, address_hint,
        status, sort_order, item_title, item_summary,
        curation_relation, reuse_policy, metadata,
        created_by, updated_by,
        created_at, updated_at, archived_at
    )
    SELECT
        NEW.curated_feature_id,
        target_collection_id,
        NEW.feature_id,
        NEW.source_record_key,
        COALESCE(NEW.source_record_key, NEW.curated_feature_id::text),
        feature_row.name,
        COALESCE(
            feature_row.address ->> 'road',
            feature_row.address ->> 'legal'
        ),
        CASE NEW.curation_status
            WHEN 'curated' THEN 'included'
            ELSE NEW.curation_status
        END,
        GREATEST(0, round(NEW.rank_score)::integer),
        NULL,
        NEW.display_summary,
        NEW.curation_relation,
        NEW.reuse_policy,
        NEW.metadata || jsonb_build_object(
            'legacy_selection_origin', NEW.selection_origin,
            'legacy_content_version', NEW.content_version
        ),
        NEW.selected_by,
        NEW.selected_by,
        NEW.created_at,
        NEW.updated_at,
        NEW.archived_at
    FROM feature.features AS feature_row
    WHERE feature_row.feature_id = NEW.feature_id;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.add_column(
        "curation_items",
        sa.Column(
            "source_present",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="feature",
    )
    # 0064까지 partial unique가 허용한 tombstone+active resurrection 및 중복
    # tombstone을 operator tombstone 우선으로 정규화한다.
    op.execute(
        """
        DELETE FROM feature.curation_items AS active
        USING feature.curation_items AS tombstone
        WHERE active.archived_at IS NULL
          AND tombstone.archived_at IS NOT NULL
          AND active.collection_id = tombstone.collection_id
          AND active.external_item_id = tombstone.external_item_id
          AND active.feature_id IS NOT DISTINCT FROM tombstone.feature_id
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                curation_item_id,
                row_number() OVER (
                    PARTITION BY collection_id, external_item_id, feature_id
                    ORDER BY archived_at DESC, updated_at DESC, curation_item_id DESC
                ) AS ordinal
            FROM feature.curation_items
            WHERE archived_at IS NOT NULL
        )
        DELETE FROM feature.curation_items AS duplicate
        USING ranked
        WHERE duplicate.curation_item_id = ranked.curation_item_id
          AND ranked.ordinal > 1
        """
    )
    op.drop_index(
        "uq_curation_items_active_identity",
        table_name="curation_items",
        schema="feature",
    )
    op.create_index(
        "uq_curation_items_identity",
        "curation_items",
        ["collection_id", "external_item_id", "feature_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        schema="feature",
    )
    op.drop_index(
        "idx_curation_items_collection_status_order",
        table_name="curation_items",
        schema="feature",
    )
    op.drop_index(
        "idx_curation_items_feature_status_collection",
        table_name="curation_items",
        schema="feature",
    )
    op.create_index(
        "idx_curation_items_collection_status_order",
        "curation_items",
        ["collection_id", "source_present", "status", "sort_order", "curation_item_id"],
        schema="feature",
    )
    op.create_index(
        "idx_curation_items_feature_status_collection",
        "curation_items",
        ["feature_id", "source_present", "status", "collection_id"],
        schema="feature",
    )
    op.execute(_SYNC_FUNCTION_0065)


def downgrade() -> None:
    # source absence와 보존된 operator override는 0064가 표현할 수 없다. 이를
    # DELETE로 흉내 내 데이터 손실을 일으키지 않고 명시적 정리 전까지 차단한다.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM feature.curation_items
                WHERE NOT source_present
            ) THEN
                RAISE EXCEPTION
                    '0065 downgrade blocked: source-absent curation items exist'
                    USING ERRCODE = 'P0001';
            END IF;
        END;
        $$
        """
    )
    op.execute(_SYNC_FUNCTION_0064)
    op.drop_index(
        "idx_curation_items_feature_status_collection",
        table_name="curation_items",
        schema="feature",
    )
    op.drop_index(
        "idx_curation_items_collection_status_order",
        table_name="curation_items",
        schema="feature",
    )
    op.create_index(
        "idx_curation_items_feature_status_collection",
        "curation_items",
        ["feature_id", "status", "collection_id"],
        schema="feature",
    )
    op.create_index(
        "idx_curation_items_collection_status_order",
        "curation_items",
        ["collection_id", "status", "sort_order", "curation_item_id"],
        schema="feature",
    )
    op.drop_index(
        "uq_curation_items_identity",
        table_name="curation_items",
        schema="feature",
    )
    op.create_index(
        "uq_curation_items_active_identity",
        "curation_items",
        ["collection_id", "external_item_id", "feature_id"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
        postgresql_nulls_not_distinct=True,
        schema="feature",
    )
    op.drop_column("curation_items", "source_present", schema="feature")
