"""curated public API 계약을 제품 비의존 이름으로 일반화.

Revision ID: 0034_generic_curated_contract
Revises: 0033_pinvi_poi_cache_metadata
Create Date: 2026-06-25

curated feature는 특정 downstream 제품의 copy 계약이 아니라 임의 소비자가
목록과 상세를 조회하는 공개 큐레이션 계약이다. DB 컬럼, cache table, metadata key를
제품명 없는 이름으로 바꾸고 기존 운영 데이터는 보존한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034_generic_curated_contract"
down_revision: str | Sequence[str] | None = "0033_pinvi_poi_cache_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE feature.curated_themes
        DROP CONSTRAINT ck_curated_themes_visibility
        """
    )
    op.execute(
        """
        UPDATE feature.curated_themes
        SET visibility = 'public'
        WHERE visibility IN ('pinvi', 'tripmate')
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_themes
        ADD CONSTRAINT ck_curated_themes_visibility
        CHECK (visibility IN ('admin_only','public'))
        """
    )

    op.execute(
        """
        ALTER TABLE feature.curated_features
        DROP CONSTRAINT ck_curated_features_pinvi_relation
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        DROP CONSTRAINT ck_curated_features_pinvi_copy_policy
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME CONSTRAINT ck_curated_features_copy_version
        TO ck_curated_features_content_version
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN pinvi_relation TO curation_relation
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN pinvi_copy_policy TO reuse_policy
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN copy_version TO content_version
        """
    )
    op.execute(
        """
        UPDATE feature.curated_features
        SET reuse_policy = CASE reuse_policy
            WHEN 'copy_allowed' THEN 'allowed'
            WHEN 'copy_blocked' THEN 'blocked'
            ELSE reuse_policy
        END
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        ADD CONSTRAINT ck_curated_features_curation_relation
        CHECK (
            curation_relation IN (
                'primary_stop','food_stop','cafe_stop','bookstore_stop',
                'nearby_option','accessibility_support','pet_support',
                'family_support','theme_area_anchor'
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        ADD CONSTRAINT ck_curated_features_reuse_policy
        CHECK (reuse_policy IN ('allowed','blocked','manual_review'))
        """
    )

    op.execute(
        """
        UPDATE feature.curated_source_rules
        SET metadata = (
            metadata
            || CASE
                WHEN NOT metadata ? 'curation_relation'
                 AND metadata ? 'pinvi_relation'
                THEN jsonb_build_object(
                    'curation_relation',
                    metadata ->> 'pinvi_relation'
                )
                WHEN NOT metadata ? 'curation_relation'
                 AND metadata ? 'tripmate_relation'
                THEN jsonb_build_object(
                    'curation_relation',
                    metadata ->> 'tripmate_relation'
                )
                ELSE '{}'::jsonb
            END
            || CASE
                WHEN NOT metadata ? 'reuse_policy'
                 AND metadata ? 'pinvi_copy_policy'
                THEN jsonb_build_object(
                    'reuse_policy',
                    CASE metadata ->> 'pinvi_copy_policy'
                        WHEN 'copy_allowed' THEN 'allowed'
                        WHEN 'copy_blocked' THEN 'blocked'
                        ELSE metadata ->> 'pinvi_copy_policy'
                    END
                )
                WHEN NOT metadata ? 'reuse_policy'
                 AND metadata ? 'tripmate_copy_policy'
                THEN jsonb_build_object(
                    'reuse_policy',
                    CASE metadata ->> 'tripmate_copy_policy'
                        WHEN 'copy_allowed' THEN 'allowed'
                        WHEN 'copy_blocked' THEN 'blocked'
                        ELSE metadata ->> 'tripmate_copy_policy'
                    END
                )
                ELSE '{}'::jsonb
            END
        ) - 'pinvi_relation' - 'tripmate_relation'
          - 'pinvi_copy_policy' - 'tripmate_copy_policy'
        WHERE metadata ? 'pinvi_relation'
           OR metadata ? 'tripmate_relation'
           OR metadata ? 'pinvi_copy_policy'
           OR metadata ? 'tripmate_copy_policy'
        """
    )
    op.execute(
        """
        UPDATE feature.curated_source_rules
        SET metadata = jsonb_set(
            metadata,
            '{reuse_policy}',
            to_jsonb(CASE metadata ->> 'reuse_policy'
                WHEN 'copy_allowed' THEN 'allowed'
                WHEN 'copy_blocked' THEN 'blocked'
                ELSE metadata ->> 'reuse_policy'
            END),
            true
        )
        WHERE metadata ->> 'reuse_policy' IN ('copy_allowed','copy_blocked')
        """
    )

    op.execute(
        """
        ALTER TABLE feature.curated_pinvi_copy_snapshots
        RENAME TO curated_feature_detail_snapshots
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_feature_detail_snapshots
        RENAME COLUMN copy_version TO content_version
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_feature_detail_snapshots
        RENAME CONSTRAINT ck_curated_copy_snapshots_version
        TO ck_curated_feature_detail_snapshots_version
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_feature_detail_snapshots
        RENAME CONSTRAINT ck_curated_copy_snapshots_snapshot
        TO ck_curated_feature_detail_snapshots_snapshot
        """
    )
    op.execute(
        """
        ALTER INDEX feature.idx_curated_copy_snapshots_updated
        RENAME TO idx_curated_feature_detail_snapshots_updated
        """
    )
    op.execute(
        """
        ALTER INDEX feature.idx_curated_copy_snapshots_etag
        RENAME TO idx_curated_feature_detail_snapshots_etag
        """
    )
    op.execute(
        """
        UPDATE feature.curated_feature_detail_snapshots
        SET snapshot = (
            snapshot - 'plan'
            || jsonb_build_object(
                'content',
                (
                    (snapshot -> 'plan') - 'copy_policy'
                    || jsonb_build_object(
                        'reuse_policy',
                        CASE snapshot #>> '{plan,copy_policy}'
                            WHEN 'copy_allowed' THEN 'allowed'
                            WHEN 'copy_blocked' THEN 'blocked'
                            ELSE snapshot #>> '{plan,copy_policy}'
                        END
                    )
                )
            )
        )
        WHERE snapshot ? 'plan'
        """
    )

    op.execute(
        """
        UPDATE ops.poi_cache_targets
        SET metadata = (
            metadata
            || jsonb_build_object('external_poi_id', metadata ->> 'pinvi_poi_id')
        ) - 'pinvi_poi_id'
        WHERE metadata ? 'pinvi_poi_id'
          AND NOT metadata ? 'external_poi_id'
        """
    )
    op.execute(
        """
        UPDATE ops.poi_cache_targets
        SET metadata = (
            metadata
            || jsonb_build_object('external_poi_id', metadata ->> 'tripmate_poi_id')
        ) - 'tripmate_poi_id'
        WHERE metadata ? 'tripmate_poi_id'
          AND NOT metadata ? 'external_poi_id'
        """
    )
    op.execute(
        """
        UPDATE ops.poi_cache_targets
        SET metadata = metadata - 'pinvi_poi_id' - 'tripmate_poi_id'
        WHERE metadata ? 'pinvi_poi_id'
           OR metadata ? 'tripmate_poi_id'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ops.poi_cache_targets
        SET metadata = (
            metadata
            || jsonb_build_object('pinvi_poi_id', metadata ->> 'external_poi_id')
        ) - 'external_poi_id'
        WHERE metadata ? 'external_poi_id'
          AND NOT metadata ? 'pinvi_poi_id'
        """
    )

    op.execute(
        """
        UPDATE feature.curated_feature_detail_snapshots
        SET snapshot = (
            snapshot - 'content'
            || jsonb_build_object(
                'plan',
                (
                    (snapshot -> 'content') - 'reuse_policy'
                    || jsonb_build_object(
                        'copy_policy',
                        CASE snapshot #>> '{content,reuse_policy}'
                            WHEN 'allowed' THEN 'copy_allowed'
                            WHEN 'blocked' THEN 'copy_blocked'
                            ELSE snapshot #>> '{content,reuse_policy}'
                        END
                    )
                )
            )
        )
        WHERE snapshot ? 'content'
        """
    )
    op.execute(
        """
        ALTER INDEX feature.idx_curated_feature_detail_snapshots_etag
        RENAME TO idx_curated_copy_snapshots_etag
        """
    )
    op.execute(
        """
        ALTER INDEX feature.idx_curated_feature_detail_snapshots_updated
        RENAME TO idx_curated_copy_snapshots_updated
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_feature_detail_snapshots
        RENAME CONSTRAINT ck_curated_feature_detail_snapshots_snapshot
        TO ck_curated_copy_snapshots_snapshot
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_feature_detail_snapshots
        RENAME CONSTRAINT ck_curated_feature_detail_snapshots_version
        TO ck_curated_copy_snapshots_version
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_feature_detail_snapshots
        RENAME COLUMN content_version TO copy_version
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_feature_detail_snapshots
        RENAME TO curated_pinvi_copy_snapshots
        """
    )

    op.execute(
        """
        UPDATE feature.curated_source_rules
        SET metadata = (
            metadata
            || CASE
                WHEN metadata ? 'curation_relation'
                THEN jsonb_build_object(
                    'pinvi_relation',
                    metadata ->> 'curation_relation'
                )
                ELSE '{}'::jsonb
            END
            || CASE
                WHEN metadata ? 'reuse_policy'
                THEN jsonb_build_object(
                    'pinvi_copy_policy',
                    CASE metadata ->> 'reuse_policy'
                        WHEN 'allowed' THEN 'copy_allowed'
                        WHEN 'blocked' THEN 'copy_blocked'
                        ELSE metadata ->> 'reuse_policy'
                    END
                )
                ELSE '{}'::jsonb
            END
        ) - 'curation_relation' - 'reuse_policy'
        WHERE metadata ? 'curation_relation'
           OR metadata ? 'reuse_policy'
        """
    )

    op.execute(
        """
        ALTER TABLE feature.curated_features
        DROP CONSTRAINT ck_curated_features_reuse_policy
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        DROP CONSTRAINT ck_curated_features_curation_relation
        """
    )
    op.execute(
        """
        UPDATE feature.curated_features
        SET reuse_policy = CASE reuse_policy
            WHEN 'allowed' THEN 'copy_allowed'
            WHEN 'blocked' THEN 'copy_blocked'
            ELSE reuse_policy
        END
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN content_version TO copy_version
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN reuse_policy TO pinvi_copy_policy
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN curation_relation TO pinvi_relation
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME CONSTRAINT ck_curated_features_content_version
        TO ck_curated_features_copy_version
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        ADD CONSTRAINT ck_curated_features_pinvi_relation
        CHECK (
            pinvi_relation IN (
                'primary_stop','food_stop','cafe_stop','bookstore_stop',
                'nearby_option','accessibility_support','pet_support',
                'family_support','theme_area_anchor'
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        ADD CONSTRAINT ck_curated_features_pinvi_copy_policy
        CHECK (pinvi_copy_policy IN ('copy_allowed','copy_blocked','manual_review'))
        """
    )

    op.execute(
        """
        ALTER TABLE feature.curated_themes
        DROP CONSTRAINT ck_curated_themes_visibility
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_themes
        ADD CONSTRAINT ck_curated_themes_visibility
        CHECK (visibility IN ('admin_only','public','pinvi'))
        """
    )
