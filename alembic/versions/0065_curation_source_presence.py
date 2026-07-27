"""authoritative 큐레이션 source presence를 membership과 분리한다.

Revision ID: 0065_curation_source_presence
Revises: 0064_price_series_identity
Create Date: 2026-07-27

CSV에서 일시 누락된 membership을 삭제하면 운영자 status/relation/reuse override가
재등장 때 소실된다. ``source_present``를 durable membership에 저장해 누락은 비공개
상태 전환으로 표현하고, source/operator revision과 archive tombstone을 분리한다.
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
    operator_change boolean;
    source_change boolean;
    source_presence_change boolean;
    item_matched boolean;
    direct_item_id uuid;
    target_identity_item_id uuid;
    target_item_id uuid;
BEGIN
    IF COALESCE(
        current_setting('kortravelmap.curation_sync_mode', true),
        ''
    ) = 'merge_explicit' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    -- Feature merge가 충돌 해소용으로 archive한 legacy projection은 더 이상
    -- canonical membership의 source가 아니다. 이후 운영 도구가 이 projection의
    -- 설명 등을 수정하거나 삭제해도 survivor를 되감지 않는다.
    IF TG_OP = 'DELETE' THEN
        IF OLD.metadata @> '{"merge_projection_detached": true}'::jsonb THEN
            RETURN OLD;
        END IF;
    ELSE
        IF TG_OP = 'UPDATE'
           AND OLD.metadata @> '{"merge_projection_detached": true}'::jsonb
        THEN
            -- ``metadata`` PATCH가 내부 detach marker를 제거해도 즉시 복원한다.
            -- 이 UPDATE의 재진입은 NEW marker 분기에서 끝나므로 canonical에는
            -- 어떤 source/operator revision도 전파하지 않는다.
            IF NOT NEW.metadata @> '{"merge_projection_detached": true}'::jsonb THEN
                UPDATE feature.curated_features
                SET metadata = NEW.metadata || jsonb_build_object(
                        'merge_projection_detached',
                        true
                    )
                WHERE curated_feature_id = NEW.curated_feature_id;
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.metadata @> '{"merge_projection_detached": true}'::jsonb THEN
            RETURN NEW;
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        SELECT
            'legacy:' || t.theme_slug || ':' || substr(md5(
                OLD.source_id::text || ':' ||
                COALESCE(NULLIF(btrim(OLD.display_title), ''), s.source_name)
            ), 1, 20)
        INTO target_collection_key
        FROM feature.curated_themes AS t
        JOIN feature.curated_sources AS s ON s.source_id = OLD.source_id
        WHERE t.theme_id = OLD.theme_id;

        UPDATE feature.curation_items AS item
        SET source_present = false,
            source_updated_at = clock_timestamp(),
            updated_by = COALESCE(OLD.rejected_by, OLD.selected_by),
            updated_at = now()
        FROM feature.curation_collections AS collection
        WHERE item.collection_id = collection.collection_id
          AND item.archived_at IS NULL
          AND item.source_present
          AND (
              item.curation_item_id = OLD.curated_feature_id
              OR (
                  OLD.source_record_key IS NOT NULL
                  AND collection.collection_key = target_collection_key
                  AND item.external_item_id = OLD.source_record_key
                  AND item.feature_id IS NOT DISTINCT FROM OLD.feature_id
              )
          );
        RETURN OLD;
    END IF;

    IF TG_OP = 'INSERT' THEN
        operator_change := NEW.operator_updated_at IS NOT NULL;
        source_change := true;
        source_presence_change := true;
    ELSE
        operator_change :=
            NEW.operator_updated_at IS DISTINCT FROM OLD.operator_updated_at
            OR NEW.operator_updated_by IS DISTINCT FROM OLD.operator_updated_by;
        source_change :=
            NEW.theme_id IS DISTINCT FROM OLD.theme_id
            OR NEW.source_id IS DISTINCT FROM OLD.source_id
            OR NEW.feature_id IS DISTINCT FROM OLD.feature_id
            OR NEW.source_record_key IS DISTINCT FROM OLD.source_record_key
            OR NEW.rank_score IS DISTINCT FROM OLD.rank_score
            OR NEW.display_title IS DISTINCT FROM OLD.display_title
            OR NEW.display_summary IS DISTINCT FROM OLD.display_summary
            OR NEW.metadata IS DISTINCT FROM OLD.metadata;
        source_presence_change :=
            NOT operator_change
            AND NEW.archived_at IS DISTINCT FROM OLD.archived_at;
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

    -- UUID mirror와 stable identity target을 먼저 하나씩 잠근 뒤 갱신 대상을
    -- 단일화한다. 두 identity가 서로 다른 row를 가리키면 target owner를
    -- 덮지 않고 기존 mirror만 source-absent로 내린 뒤 legacy projection을
    -- 영구 detach한다.
    SELECT item.curation_item_id
    INTO direct_item_id
    FROM feature.curation_items AS item
    WHERE item.curation_item_id = NEW.curated_feature_id
    FOR UPDATE;

    SELECT item.curation_item_id
    INTO target_identity_item_id
    FROM feature.curation_items AS item
    WHERE item.collection_id = target_collection_id
      AND item.external_item_id = target_external_item_id
      AND item.feature_id IS NOT DISTINCT FROM NEW.feature_id
    FOR UPDATE;

    IF direct_item_id IS NOT NULL
       AND target_identity_item_id IS NOT NULL
       AND direct_item_id <> target_identity_item_id
    THEN
        UPDATE feature.curation_items
        SET source_present = false,
            source_updated_at = clock_timestamp(),
            updated_by = COALESCE(NEW.rejected_by, NEW.selected_by),
            updated_at = NEW.updated_at
        WHERE curation_item_id = direct_item_id
          AND archived_at IS NULL
          AND source_present;

        UPDATE feature.curated_features
        SET metadata = metadata || jsonb_build_object(
                'merge_projection_detached',
                true
            )
        WHERE curated_feature_id = NEW.curated_feature_id;
        RETURN NEW;
    END IF;

    target_item_id := COALESCE(direct_item_id, target_identity_item_id);

    -- Legacy writer가 제공자 파생 필드를 갱신해도 operator-owned 상태는 보존한다.
    -- UUID/stable identity 경로는 같은 projection UPDATE를 공유하며 archived
    -- tombstone은 WHERE에서 제외해 계속 우선한다.
    UPDATE feature.curation_items AS item
    SET collection_id = CASE
            WHEN source_change THEN target_collection_id
            ELSE item.collection_id
        END,
        feature_id = CASE
            WHEN source_change THEN NEW.feature_id
            ELSE item.feature_id
        END,
        source_record_key = CASE
            WHEN source_change THEN NEW.source_record_key
            ELSE item.source_record_key
        END,
        external_item_id = CASE
            WHEN source_change THEN target_external_item_id
            ELSE item.external_item_id
        END,
        place_name = CASE
            WHEN source_change THEN feature_row.name
            ELSE item.place_name
        END,
        address_hint = CASE
            WHEN source_change THEN COALESCE(
                feature_row.address ->> 'road',
                feature_row.address ->> 'legal'
            )
            ELSE item.address_hint
        END,
        source_present = CASE
            WHEN source_change OR source_presence_change
            THEN NEW.archived_at IS NULL
            ELSE item.source_present
        END,
        source_updated_at = CASE
            WHEN source_change OR source_presence_change THEN clock_timestamp()
            ELSE item.source_updated_at
        END,
        sort_order = CASE
            WHEN source_change THEN GREATEST(0, round(NEW.rank_score)::integer)
            ELSE item.sort_order
        END,
        item_summary = CASE
            WHEN source_change THEN NEW.display_summary
            ELSE item.item_summary
        END,
        status = CASE
            WHEN operator_change THEN CASE NEW.curation_status
                WHEN 'curated' THEN 'included'
                ELSE NEW.curation_status
            END
            ELSE item.status
        END,
        curation_relation = CASE
            WHEN operator_change THEN NEW.curation_relation
            ELSE item.curation_relation
        END,
        reuse_policy = CASE
            WHEN operator_change THEN NEW.reuse_policy
            ELSE item.reuse_policy
        END,
        metadata = CASE
            WHEN source_change THEN NEW.metadata || jsonb_build_object(
                'legacy_selection_origin', NEW.selection_origin,
                'legacy_content_version', NEW.content_version
            )
            ELSE item.metadata
        END,
        updated_by = COALESCE(NEW.rejected_by, NEW.selected_by),
        updated_at = NEW.updated_at,
        operator_updated_by = CASE
            WHEN operator_change
            THEN COALESCE(
                NEW.operator_updated_by,
                item.operator_updated_by
            )
            ELSE item.operator_updated_by
        END,
        operator_updated_at = CASE
            WHEN operator_change
            THEN NEW.operator_updated_at
            ELSE item.operator_updated_at
        END,
        archived_at = CASE
            WHEN operator_change THEN NEW.archived_at
            ELSE item.archived_at
        END
    FROM feature.features AS feature_row
    WHERE item.curation_item_id = target_item_id
      AND item.archived_at IS NULL
      AND feature_row.feature_id = NEW.feature_id;

    item_matched := FOUND;

    -- stable identity가 기존 operator state/tombstone을 보존했다면 새 legacy
    -- UUID의 공개 projection도 같은 상태로 교정한다. depth 1에서만 역동기화하고
    -- 실제 값이 다를 때만 UPDATE해 trigger 재진입을 한 번으로 제한한다.
    IF pg_trigger_depth() = 1 THEN
        UPDATE feature.curated_features AS legacy
        SET curation_status = CASE item.status
                WHEN 'included' THEN 'curated'
                ELSE item.status
            END,
            selection_origin = CASE
                WHEN item.operator_updated_at IS NOT NULL THEN 'admin'
                ELSE legacy.selection_origin
            END,
            selected_by = CASE
                WHEN item.status = 'included' THEN item.operator_updated_by
                ELSE legacy.selected_by
            END,
            selected_at = CASE
                WHEN item.status = 'included' THEN item.operator_updated_at
                ELSE legacy.selected_at
            END,
            rejected_by = CASE
                WHEN item.status = 'rejected' THEN item.operator_updated_by
                ELSE legacy.rejected_by
            END,
            rejected_at = CASE
                WHEN item.status = 'rejected' THEN item.operator_updated_at
                ELSE legacy.rejected_at
            END,
            curation_relation = item.curation_relation,
            reuse_policy = item.reuse_policy,
            operator_updated_by = item.operator_updated_by,
            operator_updated_at = item.operator_updated_at,
            archived_at = item.archived_at,
            content_version = legacy.content_version + 1,
            updated_at = clock_timestamp()
        FROM feature.curation_items AS item
        WHERE legacy.curated_feature_id = NEW.curated_feature_id
          AND (
              item.curation_item_id = NEW.curated_feature_id
              OR (
                  item.collection_id = target_collection_id
                  AND item.external_item_id = target_external_item_id
                  AND item.feature_id IS NOT DISTINCT FROM NEW.feature_id
              )
          )
          AND (
              legacy.curation_status,
              legacy.curation_relation,
              legacy.reuse_policy,
              legacy.operator_updated_by,
              legacy.operator_updated_at,
              legacy.archived_at
          ) IS DISTINCT FROM (
              CASE item.status
                  WHEN 'included' THEN 'curated'
                  ELSE item.status
              END,
              item.curation_relation,
              item.reuse_policy,
              item.operator_updated_by,
              item.operator_updated_at,
              item.archived_at
          );
    END IF;

    IF item_matched OR EXISTS (
        SELECT 1
        FROM feature.curation_items
        WHERE collection_id = target_collection_id
          AND external_item_id = target_external_item_id
          AND feature_id IS NOT DISTINCT FROM NEW.feature_id
    ) THEN
        RETURN NEW;
    END IF;

    UPDATE feature.curation_items AS item
    SET source_present = false,
        source_updated_at = CASE
            WHEN source_change OR source_presence_change THEN clock_timestamp()
            ELSE item.source_updated_at
        END,
        updated_by = COALESCE(NEW.rejected_by, NEW.selected_by),
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
        source_updated_at,
        status, sort_order, item_title, item_summary,
        curation_relation, reuse_policy, metadata,
        created_by, updated_by, operator_updated_by, operator_updated_at,
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
        clock_timestamp(),
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
        COALESCE(NEW.rejected_by, NEW.selected_by),
        COALESCE(NEW.rejected_by, NEW.selected_by),
        CASE
            WHEN operator_change THEN NEW.operator_updated_by
            ELSE NULL
        END,
        CASE
            WHEN operator_change THEN NEW.operator_updated_at
            ELSE NULL
        END,
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
        "curated_features",
        sa.Column("operator_updated_by", sa.Text(), nullable=True),
        schema="feature",
    )
    op.add_column(
        "curated_features",
        sa.Column("operator_updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="feature",
    )
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
    op.add_column(
        "curation_items",
        sa.Column(
            "source_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="feature",
    )
    op.add_column(
        "curation_items",
        sa.Column("operator_updated_by", sa.Text(), nullable=True),
        schema="feature",
    )
    op.add_column(
        "curation_items",
        sa.Column("operator_updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="feature",
    )
    # 0065 이전에는 provider refresh와 운영자 수정을 같은 updated_at에 기록했다.
    # 명시적 operator origin/override로 식별 가능한 행만 보수적으로 이관한다.
    # 0064 trigger는 legacy UPDATE마다 canonical item을 DELETE+INSERT한다. 새
    # provenance backfill 동안 이를 끄지 않으면 이미 존재하는 canonical override를
    # legacy 값으로 되감는다. DDL과 backfill은 같은 migration transaction이라 실패 시
    # trigger 상태도 함께 rollback된다.
    op.execute(
        "ALTER TABLE feature.curated_features "
        "DISABLE TRIGGER trg_sync_curated_feature_collection"
    )
    op.execute(
        """
        UPDATE feature.curated_features
        SET operator_updated_by = COALESCE(rejected_by, selected_by),
            operator_updated_at = COALESCE(rejected_at, selected_at, updated_at)
        WHERE selection_origin IN ('admin', 'external_api')
        """
    )
    op.execute(
        "ALTER TABLE feature.curated_features "
        "ENABLE TRIGGER trg_sync_curated_feature_collection"
    )
    op.execute(
        """
        UPDATE feature.curation_items
        SET source_updated_at = updated_at
        """
    )
    op.execute(
        """
        UPDATE feature.curation_items
        SET operator_updated_by = updated_by,
            operator_updated_at = updated_at
        WHERE status IN ('rejected', 'archived')
           OR curation_relation <> 'nearby_option'
           OR reuse_policy <> 'manual_review'
           OR metadata ->> 'legacy_selection_origin' IN ('admin', 'external_api')
        """
    )
    # 0064까지 partial unique가 허용한 tombstone+active resurrection 및 중복
    # tombstone을 단일 survivor로 합친다. Tombstone status/provenance는 우선하되
    # provider 파생 필드는 source revision이 가장 최신인 row에서 보존한다.
    op.execute(
        """
        WITH tombstone_winners AS MATERIALIZED (
            SELECT DISTINCT ON (
                collection_id,
                external_item_id,
                feature_id
            )
                collection_id,
                external_item_id,
                feature_id,
                curation_item_id,
                status,
                curation_relation,
                reuse_policy,
                updated_by,
                operator_updated_by,
                operator_updated_at,
                updated_at,
                archived_at
            FROM feature.curation_items
            WHERE archived_at IS NOT NULL
            ORDER BY
                collection_id,
                external_item_id,
                feature_id,
                COALESCE(operator_updated_at, archived_at, updated_at) DESC,
                curation_item_id DESC
        ), source_winners AS MATERIALIZED (
            SELECT DISTINCT ON (
                item.collection_id,
                item.external_item_id,
                item.feature_id
            )
                item.collection_id,
                item.external_item_id,
                item.feature_id,
                item.source_record_key,
                item.place_name,
                item.address_hint,
                item.source_present,
                item.source_updated_at,
                item.sort_order,
                item.item_title,
                item.item_summary,
                item.metadata,
                item.updated_at
            FROM feature.curation_items AS item
            JOIN tombstone_winners AS tombstone
              ON tombstone.collection_id = item.collection_id
             AND tombstone.external_item_id = item.external_item_id
             AND tombstone.feature_id IS NOT DISTINCT FROM item.feature_id
            ORDER BY
                item.collection_id,
                item.external_item_id,
                item.feature_id,
                item.source_updated_at DESC,
                item.updated_at DESC,
                item.curation_item_id DESC
        ), reconciled AS (
            UPDATE feature.curation_items AS survivor
            SET source_record_key = source.source_record_key,
                place_name = source.place_name,
                address_hint = source.address_hint,
                source_present = source.source_present,
                source_updated_at = source.source_updated_at,
                status = 'archived',
                sort_order = source.sort_order,
                item_title = source.item_title,
                item_summary = source.item_summary,
                curation_relation = tombstone.curation_relation,
                reuse_policy = tombstone.reuse_policy,
                metadata = source.metadata,
                updated_by = tombstone.updated_by,
                operator_updated_by = tombstone.operator_updated_by,
                operator_updated_at = tombstone.operator_updated_at,
                updated_at = GREATEST(source.updated_at, tombstone.updated_at),
                archived_at = tombstone.archived_at
            FROM tombstone_winners AS tombstone
            JOIN source_winners AS source
              ON source.collection_id = tombstone.collection_id
             AND source.external_item_id = tombstone.external_item_id
             AND source.feature_id IS NOT DISTINCT FROM tombstone.feature_id
            WHERE survivor.curation_item_id = tombstone.curation_item_id
            RETURNING
                survivor.collection_id,
                survivor.external_item_id,
                survivor.feature_id,
                survivor.curation_item_id
        )
        DELETE FROM feature.curation_items AS duplicate
        USING reconciled
        WHERE duplicate.collection_id = reconciled.collection_id
          AND duplicate.external_item_id = reconciled.external_item_id
          AND duplicate.feature_id IS NOT DISTINCT FROM reconciled.feature_id
          AND duplicate.curation_item_id <> reconciled.curation_item_id
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
                   OR operator_updated_by IS NOT NULL
                   OR operator_updated_at IS NOT NULL
            ) OR EXISTS (
                SELECT 1
                FROM feature.curated_features
                WHERE operator_updated_by IS NOT NULL
                   OR operator_updated_at IS NOT NULL
                   OR metadata @> '{"merge_projection_detached": true}'::jsonb
            ) THEN
                RAISE EXCEPTION
                    '0065 downgrade blocked: durable curation state exists'
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
    op.drop_column("curation_items", "operator_updated_at", schema="feature")
    op.drop_column("curation_items", "operator_updated_by", schema="feature")
    op.drop_column("curation_items", "source_updated_at", schema="feature")
    op.drop_column("curation_items", "source_present", schema="feature")
    op.drop_column("curated_features", "operator_updated_at", schema="feature")
    op.drop_column("curated_features", "operator_updated_by", schema="feature")
