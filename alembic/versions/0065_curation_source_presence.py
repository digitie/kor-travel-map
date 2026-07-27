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
from sqlalchemy.dialects import postgresql

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
    target_collection_base_key text;
    target_key_conflict_ordinal integer;
    target_title text;
    mapped_collection_id uuid;
    mapped_theme_id uuid;
    mapped_source_id uuid;
    mapped_title text;
    mapped_archived boolean;
    mapped_external_item_id text;
    target_external_item_id text;
    operator_change boolean;
    source_change boolean;
    source_presence_change boolean;
    item_matched boolean;
    direct_item_id uuid;
    target_identity_item_id uuid;
    target_projection_id uuid;
    target_item_id uuid;
BEGIN
    -- detach marker는 merge/trigger 내부 상태다. 일반 INSERT 또는 top-level
    -- UPDATE로 주입해 canonical sync와 공개 projection을 우회할 수 없다.
    IF TG_OP = 'INSERT'
       AND NEW.metadata @> '{"merge_projection_detached": true}'::jsonb
    THEN
        RAISE EXCEPTION
            'merge_projection_detached metadata is reserved'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE'
       AND NOT OLD.metadata @> '{"merge_projection_detached": true}'::jsonb
       AND NEW.metadata @> '{"merge_projection_detached": true}'::jsonb
       AND pg_trigger_depth() = 1
    THEN
        -- Merge가 허용받는 유일한 top-level 전이는 UUID mirror를 분리한
        -- same-theme legacy conflict 또는 저장된 collection/external identity가
        -- 같은 canonical pair의 loser를 archive하는 경우다. 호출자 토큰/GUC가
        -- 아니라 transaction 안의 물리 불변식으로 권한을 판정한다.
        IF NEW.feature_id IS DISTINCT FROM OLD.feature_id
           AND NEW.curation_status = 'archived'
           AND NEW.archived_at IS NOT NULL
           AND NEW.metadata = OLD.metadata || jsonb_build_object(
               'merge_projection_detached',
               true
           )
           AND to_jsonb(NEW) - ARRAY[
               'feature_id',
               'curation_status',
               'metadata',
               'archived_at',
               'updated_at'
           ] = to_jsonb(OLD) - ARRAY[
               'feature_id',
               'curation_status',
               'metadata',
               'archived_at',
               'updated_at'
           ]
           AND (
               (
                   NOT EXISTS (
                       SELECT 1
                       FROM feature.curation_items AS direct_item
                       WHERE (
                               direct_item.legacy_projection_id =
                               NEW.curated_feature_id
                               OR (
                                   direct_item.legacy_projection_id IS NULL
                                   AND direct_item.curation_item_id =
                                       NEW.curated_feature_id
                               )
                           )
                         AND direct_item.archived_at IS NULL
                   )
                   AND EXISTS (
                       SELECT 1
                       FROM feature.curated_features AS master_legacy
                       WHERE master_legacy.curated_feature_id <>
                             NEW.curated_feature_id
                         AND master_legacy.theme_id = NEW.theme_id
                         AND master_legacy.feature_id = NEW.feature_id
                         AND master_legacy.archived_at IS NULL
                         AND NOT master_legacy.metadata @>
                             '{"merge_projection_detached": true}'::jsonb
                   )
               )
               OR EXISTS (
                   SELECT 1
                   FROM feature.curation_items AS loser_item
                   JOIN feature.curation_items AS master_item
                     ON master_item.collection_id = loser_item.collection_id
                    AND master_item.external_item_id =
                        loser_item.external_item_id
                   WHERE master_item.feature_id = NEW.feature_id
                     AND loser_item.legacy_projection_id =
                         NEW.curated_feature_id
                     AND master_item.curation_item_id <>
                         loser_item.curation_item_id
               )
           )
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'merge_projection_detached metadata is reserved'
            USING ERRCODE = '23514';
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
            IF NOT NEW.metadata @> '{"merge_projection_detached": true}'::jsonb
               OR NEW.curation_status <> 'archived'
               OR NEW.archived_at IS NULL
            THEN
                UPDATE feature.curated_features
                SET curation_status = 'archived',
                    metadata = NEW.metadata || jsonb_build_object(
                        'merge_projection_detached',
                        true
                    ),
                    archived_at = COALESCE(
                        NEW.archived_at,
                        OLD.archived_at,
                        clock_timestamp()
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
        UPDATE feature.curation_items AS item
        SET source_present = false,
            source_updated_at = CASE
                WHEN item.source_present THEN clock_timestamp()
                ELSE item.source_updated_at
            END,
            legacy_projection_id = NULL,
            updated_by = COALESCE(OLD.rejected_by, OLD.selected_by),
            updated_at = now()
        WHERE (
              item.legacy_projection_id = OLD.curated_feature_id
              OR (
                  item.legacy_projection_id IS NULL
                  AND item.curation_item_id = OLD.curated_feature_id
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

    target_external_item_id :=
        COALESCE(NEW.source_record_key, NEW.curated_feature_id::text);

    SELECT COALESCE(NULLIF(btrim(NEW.display_title), ''), s.source_name)
    INTO target_title
    FROM feature.curated_themes AS t
    JOIN feature.curated_sources AS s ON s.source_id = NEW.source_id
    WHERE t.theme_id = NEW.theme_id;

    target_collection_base_key :=
        'legacy:' || NEW.theme_id::text || ':' || NEW.source_id::text || ':' ||
        md5(target_title);
    target_collection_key := target_collection_base_key;
    target_key_conflict_ordinal := 0;

    -- 이미 projection과 연결된 membership은 semantic group
    -- (theme_id/source_id/title)이 같으면 collection_id가 불변 identity다.
    -- theme slug 같은 표시 필드가 바뀌어도 기존 collection을 유지한다. Item을
    -- 먼저 잠그면 canonical writer의 legacy→collection→item 순서와 역전되므로
    -- 여기서는 관계만 읽고, collection을 잠근 다음 아래에서 item을 잠근다.
    SELECT
        item.collection_id,
        collection.theme_id,
        collection.source_id,
        collection.title,
        item.archived_at IS NOT NULL,
        item.external_item_id
    INTO
        mapped_collection_id,
        mapped_theme_id,
        mapped_source_id,
        mapped_title,
        mapped_archived,
        mapped_external_item_id
    FROM feature.curation_items AS item
    JOIN feature.curation_collections AS collection
      ON collection.collection_id = item.collection_id
    WHERE (
            item.legacy_projection_id = NEW.curated_feature_id
            OR (
                item.legacy_projection_id IS NULL
                AND item.curation_item_id = NEW.curated_feature_id
            )
        )
       OR (
            collection.theme_id = NEW.theme_id
            AND collection.source_id IS NOT DISTINCT FROM NEW.source_id
            AND collection.metadata @>
                '{"migrated_from": "feature.curated_features"}'::jsonb
            AND item.source_record_key
                IS NOT DISTINCT FROM NEW.source_record_key
            AND item.feature_id IS NOT DISTINCT FROM NEW.feature_id
        )
    ORDER BY
        (item.legacy_projection_id = NEW.curated_feature_id) DESC NULLS LAST,
        (item.archived_at IS NOT NULL) DESC,
        item.operator_updated_at DESC NULLS LAST,
        item.source_updated_at DESC,
        item.curation_item_id DESC
    LIMIT 1;

    IF NEW.source_record_key IS NULL
       AND mapped_collection_id IS NOT NULL
       AND mapped_theme_id = NEW.theme_id
       AND mapped_source_id IS NOT DISTINCT FROM NEW.source_id
    THEN
        -- source_record가 없는 legacy projection도 theme/source/feature active
        -- uniqueness 아래 같은 논리 membership이다. UUID fallback을 새로 만들지
        -- 않고 durable item의 external identity를 재사용한다.
        target_external_item_id := mapped_external_item_id;
    END IF;

    IF mapped_collection_id IS NOT NULL
       AND mapped_theme_id = NEW.theme_id
       AND mapped_source_id IS NOT DISTINCT FROM NEW.source_id
       AND (mapped_title = target_title OR mapped_archived)
    THEN
        UPDATE feature.curation_collections AS collection
        SET title = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN target_title
                ELSE collection.title
            END,
            description = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN NEW.display_summary
                ELSE collection.description
            END,
            status = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN 'published'
                ELSE collection.status
            END,
            visibility = CASE
                WHEN collection.updated_by IS NOT NULL
                  OR mapped_title <> target_title
                THEN collection.visibility
                WHEN theme.visibility = 'public' THEN 'public'
                ELSE 'admin_only'
            END,
            updated_at = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN NEW.updated_at
                ELSE collection.updated_at
            END,
            archived_at = CASE
                WHEN collection.updated_by IS NULL
                 AND mapped_title = target_title
                THEN NULL
                ELSE collection.archived_at
            END
        FROM feature.curated_themes AS theme
        WHERE collection.collection_id = mapped_collection_id
          AND collection.theme_id = NEW.theme_id
          AND collection.source_id IS NOT DISTINCT FROM NEW.source_id
          AND theme.theme_id = NEW.theme_id
        RETURNING collection.collection_id INTO target_collection_id;
    ELSE
        -- migration이 보존한 base/split key 형태와 무관하게 semantic group의
        -- canonical collection을 먼저 찾는다. Admin이 base key를 선점했거나
        -- 과거 duplicate가 split key로 남아도 신규 projection이 별도 published
        -- collection을 만들어 collection-level tombstone을 우회하지 않는다.
        SELECT collection.collection_id
        INTO target_collection_id
        FROM feature.curation_collections AS collection
        WHERE collection.theme_id = NEW.theme_id
          AND collection.source_id IS NOT DISTINCT FROM NEW.source_id
          AND collection.title = target_title
          AND collection.metadata @>
              '{"migrated_from": "feature.curated_features"}'::jsonb
        ORDER BY
            EXISTS (
                SELECT 1
                FROM feature.curation_items AS grouped_item
                WHERE grouped_item.collection_id =
                      collection.collection_id
            ) DESC,
            collection.updated_at DESC,
            collection.collection_id
        LIMIT 1
        FOR UPDATE OF collection;

        IF target_collection_id IS NOT NULL THEN
            UPDATE feature.curation_collections AS collection
            SET description = CASE
                    WHEN collection.updated_by IS NULL
                    THEN NEW.display_summary
                    ELSE collection.description
                END,
                status = CASE
                    WHEN collection.updated_by IS NULL
                    THEN 'published'
                    ELSE collection.status
                END,
                visibility = CASE
                    WHEN collection.updated_by IS NULL
                     AND theme.visibility = 'public'
                    THEN 'public'
                    WHEN collection.updated_by IS NULL
                    THEN 'admin_only'
                    ELSE collection.visibility
                END,
                updated_at = CASE
                    WHEN collection.updated_by IS NULL
                    THEN NEW.updated_at
                    ELSE collection.updated_at
                END,
                archived_at = CASE
                    WHEN collection.updated_by IS NULL
                    THEN NULL
                    ELSE collection.archived_at
                END
            FROM feature.curated_themes AS theme
            WHERE collection.collection_id = target_collection_id
              AND theme.theme_id = NEW.theme_id;
        ELSE
            LOOP
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
                CASE
                    WHEN t.visibility = 'public' THEN 'public'
                    ELSE 'admin_only'
                END,
                jsonb_build_object('migrated_from', 'feature.curated_features'),
                NEW.created_at,
                NEW.updated_at,
                NULL
            FROM feature.curated_themes AS t
            WHERE t.theme_id = NEW.theme_id
            ON CONFLICT (collection_key) DO UPDATE SET
                title = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN EXCLUDED.title
                    ELSE feature.curation_collections.title
                END,
                description = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN EXCLUDED.description
                    ELSE feature.curation_collections.description
                END,
                status = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN 'published'
                    ELSE feature.curation_collections.status
                END,
                visibility = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN EXCLUDED.visibility
                    ELSE feature.curation_collections.visibility
                END,
                updated_at = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN EXCLUDED.updated_at
                    ELSE feature.curation_collections.updated_at
                END,
                archived_at = CASE
                    WHEN feature.curation_collections.updated_by IS NULL
                    THEN NULL
                    ELSE feature.curation_collections.archived_at
                END
            WHERE feature.curation_collections.theme_id = EXCLUDED.theme_id
              AND feature.curation_collections.source_id
                  IS NOT DISTINCT FROM EXCLUDED.source_id
              AND feature.curation_collections.metadata @>
                  '{"migrated_from": "feature.curated_features"}'::jsonb
            RETURNING collection_id INTO target_collection_id;

            EXIT WHEN target_collection_id IS NOT NULL;

            -- collection_key는 admin이 임의 지정할 수 있다. 충돌 행을 덮지 않고
            -- 같은 semantic group의 모든 projection이 공유하는 다음 free
            -- legacy suffix를 찾는다. Projection UUID를 suffix로 쓰면 같은 title의
            -- row마다 collection이 분절된다.
            target_key_conflict_ordinal := target_key_conflict_ordinal + 1;
            target_collection_key :=
                target_collection_base_key || ':split:legacy' || CASE
                    WHEN target_key_conflict_ordinal = 1 THEN ''
                    ELSE ':conflict:' ||
                         (target_key_conflict_ordinal - 1)::text
                END;
            END LOOP;
        END IF;
    END IF;

    IF target_collection_id IS NULL THEN
        RAISE EXCEPTION
            'legacy collection identity conflict for theme %, source %',
            NEW.theme_id,
            NEW.source_id
            USING ERRCODE = '23505';
    END IF;

    -- UUID mirror와 stable identity target을 먼저 하나씩 잠근 뒤 갱신 대상을
    -- 단일화한다. 두 identity가 서로 다른 row를 가리키면 target owner를
    -- 덮지 않고 기존 mirror만 source-absent로 내린 뒤 legacy projection을
    -- 영구 detach한다.
    SELECT item.curation_item_id
    INTO direct_item_id
    FROM feature.curation_items AS item
    JOIN feature.curation_collections AS collection
      ON collection.collection_id = item.collection_id
    WHERE (
            item.legacy_projection_id = NEW.curated_feature_id
            OR (
                item.legacy_projection_id IS NULL
                AND item.curation_item_id = NEW.curated_feature_id
            )
        )
       OR (
            collection.theme_id = NEW.theme_id
            AND collection.source_id IS NOT DISTINCT FROM NEW.source_id
            AND collection.metadata @>
                '{"migrated_from": "feature.curated_features"}'::jsonb
            AND item.source_record_key
                IS NOT DISTINCT FROM NEW.source_record_key
            AND item.feature_id IS NOT DISTINCT FROM NEW.feature_id
        )
    ORDER BY
        (item.legacy_projection_id = NEW.curated_feature_id) DESC NULLS LAST,
        (item.archived_at IS NOT NULL) DESC,
        item.operator_updated_at DESC NULLS LAST,
        item.source_updated_at DESC,
        item.curation_item_id DESC
    LIMIT 1
    FOR UPDATE OF item;

    SELECT item.curation_item_id, item.legacy_projection_id
    INTO target_identity_item_id, target_projection_id
    FROM feature.curation_items AS item
    WHERE item.collection_id = target_collection_id
      AND item.external_item_id = target_external_item_id
      AND item.feature_id IS NOT DISTINCT FROM NEW.feature_id
    FOR UPDATE;

    IF (
           direct_item_id IS NOT NULL
           AND target_identity_item_id IS NOT NULL
           AND direct_item_id <> target_identity_item_id
       )
       OR (
           target_projection_id IS NOT NULL
           AND target_projection_id <> NEW.curated_feature_id
       )
    THEN
        UPDATE feature.curation_items
        SET source_present = false,
            source_updated_at = CASE
                WHEN source_present THEN clock_timestamp()
                ELSE source_updated_at
            END,
            legacy_projection_id = NULL,
            updated_by = COALESCE(NEW.rejected_by, NEW.selected_by),
            updated_at = NEW.updated_at
        WHERE curation_item_id = direct_item_id;

        UPDATE feature.curated_features
        SET curation_status = 'archived',
            metadata = metadata || jsonb_build_object(
                    'merge_projection_detached',
                    true
                ),
            archived_at = COALESCE(archived_at, clock_timestamp()),
            updated_at = clock_timestamp()
        WHERE curated_feature_id = NEW.curated_feature_id;
        RETURN NEW;
    END IF;

    target_item_id := COALESCE(direct_item_id, target_identity_item_id);

    UPDATE feature.curation_items AS item
    SET legacy_projection_id = NEW.curated_feature_id
    WHERE item.curation_item_id = target_item_id
      AND (
          item.legacy_projection_id IS NULL
          OR item.legacy_projection_id = NEW.curated_feature_id
      );

    -- collection owner 복구는 operator tombstone에도 적용한다. Provider 파생값은
    -- 아래 active-row UPDATE에서 보존하지만, archived item을 탈취된 public
    -- collection에 남겨 두면 stable identity 조회와 비공개 보장이 모두 깨진다.
    UPDATE feature.curation_items AS item
    SET collection_id = target_collection_id
    WHERE item.curation_item_id = target_item_id
      AND item.collection_id <> target_collection_id;

    -- Legacy writer가 제공자 파생 필드를 갱신해도 operator-owned 상태는 보존한다.
    -- UUID/stable identity 경로는 같은 projection UPDATE를 공유하며 archived
    -- tombstone은 WHERE에서 제외해 계속 우선한다.
    UPDATE feature.curation_items AS item
    SET feature_id = CASE
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
        END,
        legacy_projection_id = NEW.curated_feature_id
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
          AND item.legacy_projection_id = NEW.curated_feature_id
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
        legacy_projection_id = NULL,
        updated_by = COALESCE(NEW.rejected_by, NEW.selected_by),
        updated_at = NEW.updated_at
    WHERE (
            item.legacy_projection_id = NEW.curated_feature_id
            OR (
                item.legacy_projection_id IS NULL
                AND item.curation_item_id = NEW.curated_feature_id
            )
        )
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
        legacy_projection_id,
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
        NEW.curated_feature_id,
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
    op.add_column(
        "curation_items",
        sa.Column(
            "legacy_projection_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
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
    # Admin collection_key는 임의 문자열이므로 migration 전용 staging namespace도
    # 충돌할 수 있다. DDL transaction의 table lock 안에서 unique constraint를 잠시
    # 제거하고 최종 key를 직접 배정한 뒤 즉시 복원한다.
    op.drop_constraint(
        "uq_curation_collections_collection_key",
        "curation_collections",
        schema="feature",
        type_="unique",
    )
    # 0064의 slug rename 또는 지원되는 collection title PATCH는 동일
    # (theme/source/title) group을 여러 collection_id로 만들 수 있다. 이를 억지로
    # 합치면 operator state를 잃으므로 가장 최근 non-empty collection을 base key로
    # 고르고 나머지는 명시적 ``:split:<collection_id>`` identity로 보존한다.
    op.execute(
        """
        WITH legacy_keys AS (
            SELECT
                collection.collection_id,
                'legacy:' || collection.theme_id::text || ':' ||
                    collection.source_id::text || ':' ||
                    md5(collection.title) AS base_key,
                collection.updated_at,
                EXISTS (
                    SELECT 1
                    FROM feature.curation_items AS item
                    WHERE item.collection_id = collection.collection_id
                ) AS has_items
            FROM feature.curation_collections AS collection
            WHERE collection.source_id IS NOT NULL
              AND collection.metadata @>
                  '{"migrated_from": "feature.curated_features"}'::jsonb
        ), ranked AS (
            SELECT
                legacy_keys.*,
                row_number() OVER (
                    PARTITION BY legacy_keys.base_key
                    ORDER BY
                        legacy_keys.has_items DESC,
                        legacy_keys.updated_at DESC,
                        legacy_keys.collection_id
                ) AS group_ordinal
            FROM legacy_keys
        ), preferred AS (
            SELECT
                ranked.collection_id,
                CASE
                    WHEN ranked.group_ordinal = 1
                     AND NOT EXISTS (
                         SELECT 1
                         FROM feature.curation_collections AS occupied
                         WHERE NOT occupied.metadata @>
                             '{"migrated_from": "feature.curated_features"}'::jsonb
                           AND occupied.collection_key = ranked.base_key
                     )
                    THEN ranked.base_key
                    WHEN ranked.group_ordinal = 1
                    THEN ranked.base_key || ':split:legacy'
                    ELSE ranked.base_key || ':split:' ||
                         ranked.collection_id::text
                END AS preferred_key
            FROM ranked
        ), assigned AS (
            SELECT
                preferred.collection_id,
                free_key.collection_key
            FROM preferred
            CROSS JOIN LATERAL (
                SELECT CASE
                    WHEN suffix.value = 0 THEN preferred.preferred_key
                    ELSE preferred.preferred_key || ':conflict:' ||
                         suffix.value::text
                END AS collection_key
                FROM generate_series(
                    0,
                    (
                        SELECT count(*)::integer + 1
                        FROM feature.curation_collections AS occupied
                        WHERE NOT occupied.metadata @>
                            '{"migrated_from": "feature.curated_features"}'::jsonb
                    )
                ) AS suffix(value)
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM feature.curation_collections AS occupied
                    WHERE NOT occupied.metadata @>
                        '{"migrated_from": "feature.curated_features"}'::jsonb
                      AND occupied.collection_key = CASE
                          WHEN suffix.value = 0
                          THEN preferred.preferred_key
                          ELSE preferred.preferred_key || ':conflict:' ||
                               suffix.value::text
                      END
                )
                ORDER BY suffix.value
                LIMIT 1
            ) AS free_key
        )
        UPDATE feature.curation_collections AS collection
        SET collection_key = assigned.collection_key
        FROM assigned
        WHERE assigned.collection_id = collection.collection_id
        """
    )
    op.create_unique_constraint(
        "uq_curation_collections_collection_key",
        "curation_collections",
        ["collection_key"],
        schema="feature",
    )
    op.execute(
        """
        UPDATE feature.curated_features
        SET archived_at = COALESCE(archived_at, updated_at, now())
        WHERE curation_status = 'archived'
          AND archived_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE feature.curated_features
        SET operator_updated_by = COALESCE(rejected_by, selected_by),
            operator_updated_at = COALESCE(rejected_at, selected_at, updated_at)
        WHERE selection_origin IN ('admin', 'external_api')
           OR curation_status = 'archived'
        """
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
        SET archived_at = COALESCE(archived_at, updated_at, now())
        WHERE status = 'archived'
          AND archived_at IS NULL
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
    op.execute(
        """
        UPDATE feature.curation_items AS item
        SET legacy_projection_id = legacy.curated_feature_id
        FROM feature.curated_features AS legacy
        WHERE item.curation_item_id = legacy.curated_feature_id
        """
    )
    # 0064 slug 재사용으로 collection owner가 덮인 경우, projection과 같은 stored
    # external identity의 canonical merge pair뿐 아니라 owner 교체 전에 생성된
    # canonical-only item도 원래 논리 group에 속한다. 현재 owner projection의
    # 최초 created_at을 경계로 보존해 projection 이동 뒤에도 안전하게 분리한다.
    op.execute(
        """
        CREATE TEMP TABLE curation_owner_repairs_0065
        ON COMMIT DROP
        AS
        SELECT
            legacy.curated_feature_id AS legacy_projection_id,
            item.collection_id AS old_collection_id,
            item.external_item_id,
            COALESCE(
                (
                    SELECT min(current_item.created_at)
                    FROM feature.curation_items AS current_item
                    JOIN feature.curated_features AS current_legacy
                      ON current_legacy.curated_feature_id =
                         current_item.legacy_projection_id
                    WHERE current_item.collection_id = item.collection_id
                      AND current_legacy.theme_id = collection.theme_id
                      AND current_legacy.source_id
                          IS NOT DISTINCT FROM collection.source_id
                ),
                (
                    SELECT owner_theme.created_at
                    FROM feature.curated_themes AS owner_theme
                    WHERE owner_theme.theme_id = collection.theme_id
                )
            ) AS owner_changed_at
        FROM feature.curated_features AS legacy
        JOIN feature.curation_items AS item
          ON item.legacy_projection_id = legacy.curated_feature_id
        JOIN feature.curation_collections AS collection
          ON collection.collection_id = item.collection_id
        WHERE collection.theme_id <> legacy.theme_id
           OR collection.source_id IS DISTINCT FROM legacy.source_id
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
                survivor.curation_item_id,
                survivor.curation_relation,
                survivor.reuse_policy,
                survivor.operator_updated_by,
                survivor.operator_updated_at,
                survivor.archived_at
        ), duplicate_ids AS MATERIALIZED (
            SELECT duplicate.curation_item_id
            FROM feature.curation_items AS duplicate
            JOIN reconciled
              ON duplicate.collection_id = reconciled.collection_id
             AND duplicate.external_item_id = reconciled.external_item_id
             AND duplicate.feature_id IS NOT DISTINCT FROM reconciled.feature_id
            WHERE duplicate.curation_item_id <> reconciled.curation_item_id
        ), archived_survivor_legacy AS (
            UPDATE feature.curated_features AS legacy
            SET curation_status = 'archived',
                selection_origin = CASE
                    WHEN reconciled.operator_updated_at IS NOT NULL
                    THEN 'admin'
                    ELSE legacy.selection_origin
                END,
                curation_relation = reconciled.curation_relation,
                reuse_policy = reconciled.reuse_policy,
                operator_updated_by = reconciled.operator_updated_by,
                operator_updated_at = reconciled.operator_updated_at,
                archived_at = reconciled.archived_at,
                updated_at = clock_timestamp(),
                content_version = legacy.content_version + 1
            FROM reconciled
            WHERE legacy.curated_feature_id =
                  reconciled.curation_item_id
              AND reconciled.archived_at IS NOT NULL
              AND (
                  legacy.curation_status,
                  legacy.selection_origin,
                  legacy.curation_relation,
                  legacy.reuse_policy,
                  legacy.operator_updated_by,
                  legacy.operator_updated_at,
                  legacy.archived_at
              ) IS DISTINCT FROM (
                  'archived',
                  CASE
                      WHEN reconciled.operator_updated_at IS NOT NULL
                      THEN 'admin'
                      ELSE legacy.selection_origin
                  END,
                  reconciled.curation_relation,
                  reconciled.reuse_policy,
                  reconciled.operator_updated_by,
                  reconciled.operator_updated_at,
                  reconciled.archived_at
              )
            RETURNING legacy.curated_feature_id
        ), detached_legacy AS (
            UPDATE feature.curated_features AS legacy
            SET curation_status = 'archived',
                metadata = legacy.metadata || jsonb_build_object(
                    'merge_projection_detached',
                    true
                ),
                archived_at = COALESCE(legacy.archived_at, clock_timestamp()),
                updated_at = clock_timestamp()
            FROM duplicate_ids
            WHERE legacy.curated_feature_id = duplicate_ids.curation_item_id
            RETURNING legacy.curated_feature_id
        )
        DELETE FROM feature.curation_items AS duplicate
        USING duplicate_ids
        WHERE duplicate.curation_item_id = duplicate_ids.curation_item_id
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
    op.create_foreign_key(
        "fk_curation_items_legacy_projection_id_curated_features",
        "curation_items",
        "curated_features",
        ["legacy_projection_id"],
        ["curated_feature_id"],
        source_schema="feature",
        referent_schema="feature",
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "uq_curation_items_legacy_projection_id",
        "curation_items",
        ["legacy_projection_id"],
        unique=True,
        postgresql_where=sa.text("legacy_projection_id IS NOT NULL"),
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
    op.execute(
        "ALTER TABLE feature.curated_features "
        "ENABLE TRIGGER trg_sync_curated_feature_collection"
    )
    # 0064의 slug 재사용 ON CONFLICT가 collection owner를 덮은 과거 상태를
    # 명시적 legacy_projection_id 정본으로 복구한다. Trigger는 올바른 semantic
    # collection을 찾거나 만들고, item을 collection lock 뒤에 재배치한다.
    op.execute(
        """
        UPDATE feature.curated_features AS legacy
        SET updated_at = clock_timestamp()
        FROM feature.curation_items AS item
        JOIN feature.curation_collections AS collection
          ON collection.collection_id = item.collection_id
        WHERE item.legacy_projection_id = legacy.curated_feature_id
          AND (
              collection.theme_id <> legacy.theme_id
              OR collection.source_id IS DISTINCT FROM legacy.source_id
          )
        """
    )
    op.execute(
        """
        WITH pair_targets AS (
            SELECT
                repair.old_collection_id,
                repair.external_item_id,
                min(mapped.collection_id::text)::uuid AS target_collection_id
            FROM curation_owner_repairs_0065 AS repair
            JOIN feature.curation_items AS mapped
              ON mapped.legacy_projection_id =
                 repair.legacy_projection_id
            GROUP BY
                repair.old_collection_id,
                repair.external_item_id
            HAVING count(DISTINCT mapped.collection_id) = 1
        )
        UPDATE feature.curation_items AS companion
        SET collection_id = target.target_collection_id,
            updated_at = clock_timestamp()
        FROM pair_targets AS target
        WHERE companion.collection_id = target.old_collection_id
          AND companion.legacy_projection_id IS NULL
          AND companion.external_item_id = target.external_item_id
          AND companion.collection_id <> target.target_collection_id
          AND NOT EXISTS (
              SELECT 1
              FROM feature.curation_items AS occupied
              WHERE occupied.collection_id =
                    target.target_collection_id
                AND occupied.external_item_id =
                    companion.external_item_id
                AND occupied.feature_id IS NOT DISTINCT FROM
                    companion.feature_id
                AND occupied.curation_item_id <>
                    companion.curation_item_id
          )
        """
    )
    op.execute(
        """
        WITH single_owner_targets AS (
            SELECT
                repair.old_collection_id,
                min(repair.owner_changed_at) AS owner_changed_at,
                min(mapped.collection_id::text)::uuid AS target_collection_id
            FROM curation_owner_repairs_0065 AS repair
            JOIN feature.curation_items AS mapped
              ON mapped.legacy_projection_id =
                 repair.legacy_projection_id
            GROUP BY repair.old_collection_id
            HAVING count(DISTINCT mapped.collection_id) = 1
        )
        UPDATE feature.curation_items AS companion
        SET collection_id = target.target_collection_id,
            updated_at = clock_timestamp()
        FROM single_owner_targets AS target
        WHERE companion.collection_id = target.old_collection_id
          AND companion.legacy_projection_id IS NULL
          AND target.owner_changed_at IS NOT NULL
          AND companion.created_at < target.owner_changed_at
          AND companion.collection_id <> target.target_collection_id
          AND NOT EXISTS (
              SELECT 1
              FROM feature.curation_items AS occupied
              WHERE occupied.collection_id =
                    target.target_collection_id
                AND occupied.external_item_id =
                    companion.external_item_id
                AND occupied.feature_id IS NOT DISTINCT FROM
                    companion.feature_id
                AND occupied.curation_item_id <>
                    companion.curation_item_id
          )
        """
    )
    # 구 스키마는 같은 transaction 안의 owner 교체 전후 canonical-only item이나
    # 3회 이상 slug 재사용 이력을 완전히 표현하지 못한다. 확정할 수 없는 item을
    # 임의 owner의 public collection에 노출하지 않고 원 payload 그대로 admin-only
    # quarantine으로 옮겨 명시적 재분류 대상으로 보존한다.
    op.execute(
        """
        CREATE TEMP TABLE curation_owner_quarantines_0065
        ON COMMIT DROP
        AS
        WITH repair_summary AS (
            SELECT
                repair.old_collection_id,
                min(repair.owner_changed_at) AS owner_changed_at
            FROM curation_owner_repairs_0065 AS repair
            GROUP BY repair.old_collection_id
        )
        SELECT
            summary.old_collection_id,
            x_extension.gen_random_uuid() AS quarantine_collection_id
        FROM repair_summary AS summary
        WHERE EXISTS (
            SELECT 1
            FROM feature.curation_items AS companion
            WHERE companion.collection_id = summary.old_collection_id
              AND companion.legacy_projection_id IS NULL
              AND (
                  summary.owner_changed_at IS NULL
                  OR companion.created_at <= summary.owner_changed_at
                  OR EXISTS (
                      SELECT 1
                      FROM curation_owner_repairs_0065 AS paired
                      WHERE paired.old_collection_id =
                            summary.old_collection_id
                        AND paired.external_item_id =
                            companion.external_item_id
                  )
              )
        )
        """
    )
    op.execute(
        """
        INSERT INTO feature.curation_collections (
            collection_id,
            collection_key,
            theme_id,
            source_id,
            title,
            edition_key,
            description,
            status,
            visibility,
            metadata,
            created_by,
            updated_by,
            created_at,
            updated_at
        )
        SELECT
            quarantine.quarantine_collection_id,
            'legacy:quarantine:' ||
                quarantine.quarantine_collection_id::text,
            old_collection.theme_id,
            old_collection.source_id,
            '[0065 격리] ' || old_collection.title,
            old_collection.edition_key,
            '0065 owner 이력 불충분으로 자동 공개하지 않는 canonical item',
            'draft',
            'admin_only',
            jsonb_build_object(
                'migration_quarantine', '0065',
                'original_collection_id',
                quarantine.old_collection_id
            ),
            'migration:0065',
            'migration:0065',
            clock_timestamp(),
            clock_timestamp()
        FROM curation_owner_quarantines_0065 AS quarantine
        JOIN feature.curation_collections AS old_collection
          ON old_collection.collection_id =
             quarantine.old_collection_id
        """
    )
    op.execute(
        """
        WITH repair_summary AS (
            SELECT
                repair.old_collection_id,
                min(repair.owner_changed_at) AS owner_changed_at
            FROM curation_owner_repairs_0065 AS repair
            GROUP BY repair.old_collection_id
        )
        UPDATE feature.curation_items AS companion
        SET collection_id = quarantine.quarantine_collection_id,
            updated_at = clock_timestamp()
        FROM curation_owner_quarantines_0065 AS quarantine
        JOIN repair_summary AS summary
          ON summary.old_collection_id =
             quarantine.old_collection_id
        WHERE companion.collection_id =
              quarantine.old_collection_id
          AND companion.legacy_projection_id IS NULL
          AND (
              summary.owner_changed_at IS NULL
              OR companion.created_at <= summary.owner_changed_at
              OR EXISTS (
                  SELECT 1
                  FROM curation_owner_repairs_0065 AS paired
                  WHERE paired.old_collection_id =
                        summary.old_collection_id
                    AND paired.external_item_id =
                        companion.external_item_id
              )
          )
        """
    )
    op.execute("DROP TABLE curation_owner_quarantines_0065")
    op.execute("DROP TABLE curation_owner_repairs_0065")


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
                   OR (
                       legacy_projection_id IS NOT NULL
                       AND legacy_projection_id <> curation_item_id
                   )
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
    # 0064 key도 staging namespace 없이 최종값으로 직접 바꾼다. 같은
    # slug/source/title collection과 수동 key가 겹치면 base 하나 또는 충돌 없는
    # split suffix를 배정한다.
    op.drop_constraint(
        "uq_curation_collections_collection_key",
        "curation_collections",
        schema="feature",
        type_="unique",
    )
    op.execute(
        """
        WITH legacy_keys AS (
            SELECT
                collection.collection_id,
                'legacy:' || theme.theme_slug || ':' || substr(md5(
                    collection.source_id::text || ':' || collection.title
                ), 1, 20) AS base_key,
                collection.updated_at,
                EXISTS (
                    SELECT 1
                    FROM feature.curation_items AS item
                    WHERE item.collection_id = collection.collection_id
                ) AS has_items
            FROM feature.curation_collections AS collection
            JOIN feature.curated_themes AS theme
              ON theme.theme_id = collection.theme_id
            WHERE collection.source_id IS NOT NULL
              AND collection.metadata @>
                  '{"migrated_from": "feature.curated_features"}'::jsonb
        ), ranked AS (
            SELECT
                legacy_keys.*,
                row_number() OVER (
                    PARTITION BY legacy_keys.base_key
                    ORDER BY
                        legacy_keys.has_items DESC,
                        legacy_keys.updated_at DESC,
                        legacy_keys.collection_id
                ) AS group_ordinal
            FROM legacy_keys
        ), preferred AS (
            SELECT
                ranked.collection_id,
                CASE
                    WHEN ranked.group_ordinal = 1
                     AND NOT EXISTS (
                         SELECT 1
                         FROM feature.curation_collections AS occupied
                         WHERE NOT occupied.metadata @>
                             '{"migrated_from": "feature.curated_features"}'::jsonb
                           AND occupied.collection_key = ranked.base_key
                     )
                    THEN ranked.base_key
                    WHEN ranked.group_ordinal = 1
                    THEN ranked.base_key || ':split:legacy'
                    ELSE ranked.base_key || ':split:' ||
                         ranked.collection_id::text
                END AS preferred_key
            FROM ranked
        ), assigned AS (
            SELECT
                preferred.collection_id,
                free_key.collection_key
            FROM preferred
            CROSS JOIN LATERAL (
                SELECT CASE
                    WHEN suffix.value = 0 THEN preferred.preferred_key
                    ELSE preferred.preferred_key || ':conflict:' ||
                         suffix.value::text
                END AS collection_key
                FROM generate_series(
                    0,
                    (
                        SELECT count(*)::integer + 1
                        FROM feature.curation_collections AS occupied
                        WHERE NOT occupied.metadata @>
                            '{"migrated_from": "feature.curated_features"}'::jsonb
                    )
                ) AS suffix(value)
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM feature.curation_collections AS occupied
                    WHERE NOT occupied.metadata @>
                        '{"migrated_from": "feature.curated_features"}'::jsonb
                      AND occupied.collection_key = CASE
                          WHEN suffix.value = 0
                          THEN preferred.preferred_key
                          ELSE preferred.preferred_key || ':conflict:' ||
                               suffix.value::text
                      END
                )
                ORDER BY suffix.value
                LIMIT 1
            ) AS free_key
        )
        UPDATE feature.curation_collections AS collection
        SET collection_key = assigned.collection_key
        FROM assigned
        WHERE assigned.collection_id = collection.collection_id
        """
    )
    op.create_unique_constraint(
        "uq_curation_collections_collection_key",
        "curation_collections",
        ["collection_key"],
        schema="feature",
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
    op.drop_index(
        "uq_curation_items_legacy_projection_id",
        table_name="curation_items",
        schema="feature",
    )
    op.drop_constraint(
        "fk_curation_items_legacy_projection_id_curated_features",
        "curation_items",
        schema="feature",
        type_="foreignkey",
    )
    op.drop_column("curation_items", "legacy_projection_id", schema="feature")
    op.drop_column("curation_items", "operator_updated_at", schema="feature")
    op.drop_column("curation_items", "operator_updated_by", schema="feature")
    op.drop_column("curation_items", "source_updated_at", schema="feature")
    op.drop_column("curation_items", "source_present", schema="feature")
    op.drop_column("curated_features", "operator_updated_at", schema="feature")
    op.drop_column("curated_features", "operator_updated_by", schema="feature")
