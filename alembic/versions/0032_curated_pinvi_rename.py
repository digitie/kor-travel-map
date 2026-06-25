"""curated overlay의 TripMate 명칭을 PinVi로 rename.

Revision ID: 0032_curated_pinvi_rename
Revises: 0031_concierge_curated_source
Create Date: 2026-06-25

Curated overlay는 PinVi가 소비하는 copy snapshot을 제공하지만, 초기 schema에는
이전 제품명인 TripMate가 컬럼명과 cache table명에 남아 있었다. 본 migration은
운영 데이터 보존을 위해 rename만 수행한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032_curated_pinvi_rename"
down_revision: str | Sequence[str] | None = "0031_concierge_curated_source"
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
        SET visibility = 'pinvi'
        WHERE visibility = 'tripmate'
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_themes
        ADD CONSTRAINT ck_curated_themes_visibility
        CHECK (visibility IN ('admin_only','public','pinvi'))
        """
    )

    op.execute(
        """
        ALTER TABLE feature.curated_features
        DROP CONSTRAINT ck_curated_features_tripmate_relation
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        DROP CONSTRAINT ck_curated_features_copy_policy
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN tripmate_relation TO pinvi_relation
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN tripmate_copy_policy TO pinvi_copy_policy
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
        UPDATE feature.curated_source_rules
        SET metadata = (
            metadata
            || CASE
                WHEN metadata ? 'tripmate_relation'
                THEN jsonb_build_object(
                    'pinvi_relation',
                    metadata ->> 'tripmate_relation'
                )
                ELSE '{}'::jsonb
            END
            || CASE
                WHEN metadata ? 'tripmate_copy_policy'
                THEN jsonb_build_object(
                    'pinvi_copy_policy',
                    metadata ->> 'tripmate_copy_policy'
                )
                ELSE '{}'::jsonb
            END
        ) - 'tripmate_relation' - 'tripmate_copy_policy'
        WHERE metadata ? 'tripmate_relation'
           OR metadata ? 'tripmate_copy_policy'
        """
    )

    op.execute(
        """
        ALTER TABLE feature.curated_tripmate_copy_snapshots
        RENAME TO curated_pinvi_copy_snapshots
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE feature.curated_pinvi_copy_snapshots
        RENAME TO curated_tripmate_copy_snapshots
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
        RENAME COLUMN pinvi_relation TO tripmate_relation
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        RENAME COLUMN pinvi_copy_policy TO tripmate_copy_policy
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_features
        ADD CONSTRAINT ck_curated_features_tripmate_relation
        CHECK (
            tripmate_relation IN (
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
        ADD CONSTRAINT ck_curated_features_copy_policy
        CHECK (tripmate_copy_policy IN ('copy_allowed','copy_blocked','manual_review'))
        """
    )
    op.execute(
        """
        UPDATE feature.curated_source_rules
        SET metadata = (
            metadata
            || CASE
                WHEN metadata ? 'pinvi_relation'
                THEN jsonb_build_object(
                    'tripmate_relation',
                    metadata ->> 'pinvi_relation'
                )
                ELSE '{}'::jsonb
            END
            || CASE
                WHEN metadata ? 'pinvi_copy_policy'
                THEN jsonb_build_object(
                    'tripmate_copy_policy',
                    metadata ->> 'pinvi_copy_policy'
                )
                ELSE '{}'::jsonb
            END
        ) - 'pinvi_relation' - 'pinvi_copy_policy'
        WHERE metadata ? 'pinvi_relation'
           OR metadata ? 'pinvi_copy_policy'
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
        UPDATE feature.curated_themes
        SET visibility = 'tripmate'
        WHERE visibility = 'pinvi'
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_themes
        ADD CONSTRAINT ck_curated_themes_visibility
        CHECK (visibility IN ('admin_only','public','tripmate'))
        """
    )
