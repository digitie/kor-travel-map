"""큐레이션 묶음과 Feature membership을 분리한다.

Revision ID: 0045_curation_collections
Revises: 0044_source_entities
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0045_curation_collections"
down_revision: str | Sequence[str] | None = "0044_source_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feature.curation_collections (
            collection_id uuid PRIMARY KEY
                DEFAULT x_extension.gen_random_uuid(),
            collection_key text NOT NULL,
            theme_id uuid NOT NULL REFERENCES feature.curated_themes(theme_id)
                ON DELETE RESTRICT,
            source_id uuid REFERENCES feature.curated_sources(source_id)
                ON DELETE SET NULL,
            title text NOT NULL,
            edition_key text NOT NULL DEFAULT '',
            description text,
            status text NOT NULL DEFAULT 'draft',
            visibility text NOT NULL DEFAULT 'admin_only',
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_by text,
            updated_by text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            archived_at timestamptz,
            CONSTRAINT uq_curation_collections_collection_key
                UNIQUE (collection_key),
            CONSTRAINT ck_curation_collections_key
                CHECK (btrim(collection_key) <> ''),
            CONSTRAINT ck_curation_collections_title
                CHECK (btrim(title) <> ''),
            CONSTRAINT ck_curation_collections_status
                CHECK (status IN ('draft','published','archived')),
            CONSTRAINT ck_curation_collections_visibility
                CHECK (visibility IN ('admin_only','public')),
            CONSTRAINT ck_curation_collections_metadata
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curation_collections_theme_status_edition
        ON feature.curation_collections (
            theme_id, status, edition_key, collection_id
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curation_collections_source_status
        ON feature.curation_collections (source_id, status, collection_id)
        """
    )

    op.execute(
        """
        CREATE TABLE feature.curation_items (
            curation_item_id uuid PRIMARY KEY
                DEFAULT x_extension.gen_random_uuid(),
            collection_id uuid NOT NULL
                REFERENCES feature.curation_collections(collection_id)
                ON DELETE CASCADE,
            feature_id text REFERENCES feature.features(feature_id)
                ON DELETE SET NULL,
            source_record_key text REFERENCES provider_sync.source_records(
                source_record_key
            ) ON DELETE SET NULL,
            external_item_id text NOT NULL,
            place_name text NOT NULL,
            address_hint text,
            status text NOT NULL DEFAULT 'candidate',
            sort_order integer NOT NULL DEFAULT 0,
            item_title text,
            item_summary text,
            curation_relation text NOT NULL DEFAULT 'nearby_option',
            reuse_policy text NOT NULL DEFAULT 'manual_review',
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_by text,
            updated_by text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            archived_at timestamptz,
            CONSTRAINT ck_curation_items_external_id
                CHECK (btrim(external_item_id) <> ''),
            CONSTRAINT ck_curation_items_place_name
                CHECK (btrim(place_name) <> ''),
            CONSTRAINT ck_curation_items_status
                CHECK (status IN ('candidate','included','rejected','archived')),
            CONSTRAINT ck_curation_items_sort_order CHECK (sort_order >= 0),
            CONSTRAINT ck_curation_items_relation CHECK (
                curation_relation IN (
                    'primary_stop','food_stop','cafe_stop','bookstore_stop',
                    'nearby_option','accessibility_support','pet_support',
                    'family_support','theme_area_anchor'
                )
            ),
            CONSTRAINT ck_curation_items_reuse_policy CHECK (
                reuse_policy IN ('allowed','blocked','manual_review')
            ),
            CONSTRAINT ck_curation_items_metadata
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_curation_items_active_identity
        ON feature.curation_items (
            collection_id, external_item_id, feature_id
        ) NULLS NOT DISTINCT
        WHERE archived_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curation_items_collection_status_order
        ON feature.curation_items (
            collection_id, status, sort_order, curation_item_id
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curation_items_feature_status_collection
        ON feature.curation_items (feature_id, status, collection_id)
        """
    )

    # 기존 flat overlay는 title/theme/source 조합별 collection으로 무손실 복사한다.
    op.execute(
        """
        INSERT INTO feature.curation_collections (
            collection_key, theme_id, source_id, title, edition_key,
            description, status, visibility, metadata,
            created_at, updated_at, archived_at
        )
        SELECT
            'legacy:' || t.theme_slug || ':' || substr(md5(
                cf.source_id::text || ':' ||
                COALESCE(NULLIF(btrim(cf.display_title), ''), s.source_name)
            ), 1, 20),
            cf.theme_id,
            cf.source_id,
            COALESCE(NULLIF(btrim(cf.display_title), ''), s.source_name),
            '',
            max(cf.display_summary),
            CASE
                WHEN bool_or(cf.curation_status = 'curated') THEN 'published'
                WHEN bool_and(cf.curation_status = 'archived') THEN 'archived'
                ELSE 'draft'
            END,
            CASE WHEN t.visibility = 'public' THEN 'public' ELSE 'admin_only' END,
            jsonb_build_object('migrated_from', 'feature.curated_features'),
            min(cf.created_at),
            max(cf.updated_at),
            CASE
                WHEN bool_and(cf.archived_at IS NOT NULL)
                THEN max(cf.archived_at)
                ELSE NULL
            END
        FROM feature.curated_features AS cf
        JOIN feature.curated_themes AS t ON t.theme_id = cf.theme_id
        JOIN feature.curated_sources AS s ON s.source_id = cf.source_id
        GROUP BY
            t.theme_slug, t.visibility, cf.theme_id, cf.source_id,
            COALESCE(NULLIF(btrim(cf.display_title), ''), s.source_name),
            s.source_name
        ON CONFLICT (collection_key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO feature.curation_items (
            curation_item_id, collection_id, feature_id, source_record_key,
            external_item_id, place_name, address_hint,
            status, sort_order, item_title, item_summary,
            curation_relation, reuse_policy, metadata,
            created_by, updated_by,
            created_at, updated_at, archived_at
        )
        SELECT
            cf.curated_feature_id,
            cc.collection_id,
            cf.feature_id,
            cf.source_record_key,
            COALESCE(cf.source_record_key, cf.curated_feature_id::text),
            f.name,
            COALESCE(f.address ->> 'road', f.address ->> 'legal'),
            CASE cf.curation_status
                WHEN 'curated' THEN 'included'
                ELSE cf.curation_status
            END,
            GREATEST(0, round(cf.rank_score)::integer),
            NULL,
            cf.display_summary,
            cf.curation_relation,
            cf.reuse_policy,
            cf.metadata || jsonb_build_object(
                'legacy_selection_origin', cf.selection_origin,
                'legacy_content_version', cf.content_version
            ),
            cf.selected_by,
            cf.selected_by,
            cf.created_at,
            cf.updated_at,
            cf.archived_at
        FROM feature.curated_features AS cf
        JOIN feature.features AS f ON f.feature_id = cf.feature_id
        JOIN feature.curated_themes AS t ON t.theme_id = cf.theme_id
        JOIN feature.curated_sources AS s ON s.source_id = cf.source_id
        JOIN feature.curation_collections AS cc
          ON cc.collection_key = 'legacy:' || t.theme_slug || ':' || substr(md5(
                cf.source_id::text || ':' ||
                COALESCE(NULLIF(btrim(cf.display_title), ''), s.source_name)
            ), 1, 20)
        ON CONFLICT (curation_item_id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE FUNCTION feature.sync_curated_feature_collection()
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
                f.name,
                COALESCE(f.address ->> 'road', f.address ->> 'legal'),
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
            FROM feature.features AS f
            WHERE f.feature_id = NEW.feature_id;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sync_curated_feature_collection
        AFTER INSERT OR UPDATE OR DELETE ON feature.curated_features
        FOR EACH ROW
        EXECUTE FUNCTION feature.sync_curated_feature_collection()
        """
    )


def downgrade() -> None:
    # collection/item은 legacy flat overlay보다 표현력이 크다. 신규/직접 수정 data를
    # 조용히 DROP하지 않고, legacy에서 완전히 재구성할 수 없는 행이 하나라도 있으면
    # transaction 전체를 중단해 운영자가 명시적으로 정리·백업하도록 한다.
    op.execute(
        """
        DO $$
        DECLARE
            unsupported_collections bigint;
            unsupported_items bigint;
        BEGIN
            WITH expected_collections AS (
                SELECT
                    'legacy:' || t.theme_slug || ':' || substr(md5(
                        cf.source_id::text || ':' ||
                        COALESCE(
                            NULLIF(btrim(cf.display_title), ''),
                            s.source_name
                        )
                    ), 1, 20) AS collection_key,
                    cf.theme_id,
                    cf.source_id,
                    COALESCE(
                        NULLIF(btrim(cf.display_title), ''),
                        s.source_name
                    ) AS title,
                    ''::text AS edition_key,
                    max(cf.display_summary) AS description,
                    CASE
                        WHEN bool_or(cf.curation_status = 'curated')
                        THEN 'published'
                        WHEN bool_and(cf.curation_status = 'archived')
                        THEN 'archived'
                        ELSE 'draft'
                    END AS status,
                    CASE
                        WHEN t.visibility = 'public' THEN 'public'
                        ELSE 'admin_only'
                    END AS visibility,
                    jsonb_build_object(
                        'migrated_from',
                        'feature.curated_features'
                    ) AS metadata,
                    min(cf.created_at) AS created_at,
                    max(cf.updated_at) AS updated_at,
                    CASE
                        WHEN bool_and(cf.archived_at IS NOT NULL)
                        THEN max(cf.archived_at)
                        ELSE NULL
                    END AS archived_at
                FROM feature.curated_features AS cf
                JOIN feature.curated_themes AS t
                  ON t.theme_id = cf.theme_id
                JOIN feature.curated_sources AS s
                  ON s.source_id = cf.source_id
                GROUP BY
                    t.theme_slug,
                    t.visibility,
                    cf.theme_id,
                    cf.source_id,
                    COALESCE(
                        NULLIF(btrim(cf.display_title), ''),
                        s.source_name
                    ),
                    s.source_name
            )
            SELECT count(*)
            INTO unsupported_collections
            FROM expected_collections AS expected
            FULL OUTER JOIN feature.curation_collections AS actual
              ON actual.collection_key = expected.collection_key
            WHERE expected.collection_key IS NULL
               OR actual.collection_key IS NULL
               OR actual.theme_id IS DISTINCT FROM expected.theme_id
               OR actual.source_id IS DISTINCT FROM expected.source_id
               OR actual.title IS DISTINCT FROM expected.title
               OR actual.edition_key IS DISTINCT FROM expected.edition_key
               OR actual.description IS DISTINCT FROM expected.description
               OR actual.status IS DISTINCT FROM expected.status
               OR actual.visibility IS DISTINCT FROM expected.visibility
               OR actual.metadata IS DISTINCT FROM expected.metadata
               OR actual.created_by IS NOT NULL
               OR actual.updated_by IS NOT NULL
               OR actual.created_at IS DISTINCT FROM expected.created_at
               OR actual.updated_at IS DISTINCT FROM expected.updated_at
               OR actual.archived_at IS DISTINCT FROM expected.archived_at;

            WITH expected_items AS (
                SELECT
                    cf.curated_feature_id AS curation_item_id,
                    'legacy:' || t.theme_slug || ':' || substr(md5(
                        cf.source_id::text || ':' ||
                        COALESCE(
                            NULLIF(btrim(cf.display_title), ''),
                            s.source_name
                        )
                    ), 1, 20) AS collection_key,
                    cf.feature_id,
                    cf.source_record_key,
                    COALESCE(
                        cf.source_record_key,
                        cf.curated_feature_id::text
                    ) AS external_item_id,
                    f.name AS place_name,
                    COALESCE(
                        f.address ->> 'road',
                        f.address ->> 'legal'
                    ) AS address_hint,
                    CASE cf.curation_status
                        WHEN 'curated' THEN 'included'
                        ELSE cf.curation_status
                    END AS status,
                    GREATEST(0, round(cf.rank_score)::integer) AS sort_order,
                    cf.display_summary AS item_summary,
                    cf.curation_relation,
                    cf.reuse_policy,
                    cf.metadata || jsonb_build_object(
                        'legacy_selection_origin', cf.selection_origin,
                        'legacy_content_version', cf.content_version
                    ) AS metadata,
                    cf.selected_by AS created_by,
                    cf.selected_by AS updated_by,
                    cf.created_at,
                    cf.updated_at,
                    cf.archived_at
                FROM feature.curated_features AS cf
                JOIN feature.features AS f
                  ON f.feature_id = cf.feature_id
                JOIN feature.curated_themes AS t
                  ON t.theme_id = cf.theme_id
                JOIN feature.curated_sources AS s
                  ON s.source_id = cf.source_id
            )
            SELECT count(*)
            INTO unsupported_items
            FROM expected_items AS expected
            FULL OUTER JOIN feature.curation_items AS actual
              ON actual.curation_item_id = expected.curation_item_id
            LEFT JOIN feature.curation_collections AS collection
              ON collection.collection_id = actual.collection_id
            WHERE expected.curation_item_id IS NULL
               OR actual.curation_item_id IS NULL
               OR collection.collection_key
                    IS DISTINCT FROM expected.collection_key
               OR actual.feature_id IS DISTINCT FROM expected.feature_id
               OR actual.source_record_key
                    IS DISTINCT FROM expected.source_record_key
               OR actual.external_item_id
                    IS DISTINCT FROM expected.external_item_id
               OR actual.place_name IS DISTINCT FROM expected.place_name
               OR actual.address_hint IS DISTINCT FROM expected.address_hint
               OR actual.status IS DISTINCT FROM expected.status
               OR actual.sort_order IS DISTINCT FROM expected.sort_order
               OR actual.item_title IS NOT NULL
               OR actual.item_summary IS DISTINCT FROM expected.item_summary
               OR actual.curation_relation
                    IS DISTINCT FROM expected.curation_relation
               OR actual.reuse_policy IS DISTINCT FROM expected.reuse_policy
               OR actual.metadata IS DISTINCT FROM expected.metadata
               OR actual.created_by IS DISTINCT FROM expected.created_by
               OR actual.updated_by IS DISTINCT FROM expected.updated_by
               OR actual.created_at IS DISTINCT FROM expected.created_at
               OR actual.updated_at IS DISTINCT FROM expected.updated_at
               OR actual.archived_at IS DISTINCT FROM expected.archived_at;

            IF unsupported_collections > 0 OR unsupported_items > 0 THEN
                RAISE EXCEPTION
                    '0045 downgrade blocked: % unsupported collection(s), '
                    '% unsupported item(s); export or remove richer data first',
                    unsupported_collections,
                    unsupported_items;
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sync_curated_feature_collection ON feature.curated_features"
    )
    op.execute("DROP FUNCTION IF EXISTS feature.sync_curated_feature_collection()")
    op.execute("DROP TABLE IF EXISTS feature.curation_items")
    op.execute("DROP TABLE IF EXISTS feature.curation_collections")
