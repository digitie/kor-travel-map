"""Feature coord precision digits (T-RV-16).

Revision ID: 0015_feature_coord_precision
Revises: 0014_uuid_default_schema
Create Date: 2026-06-05

Dedup refresh와 admin 검토 UI가 원천 좌표 정밀도 신호를 잃지 않도록
``feature.features``에 ``coord_precision_digits``를 저장한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_feature_coord_precision"
down_revision: str | Sequence[str] | None = "0014_uuid_default_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "features",
        sa.Column("coord_precision_digits", sa.SmallInteger(), nullable=True),
        schema="feature",
    )
    op.execute(
        """
        UPDATE feature.features
        SET coord_precision_digits = 6
        WHERE coord IS NOT NULL
          AND coord_precision_digits IS NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION feature.set_feature_coord_precision()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.coord IS NULL THEN
                NEW.coord_precision_digits := NULL;
            ELSIF NEW.coord_precision_digits IS NULL THEN
                NEW.coord_precision_digits := 6;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_features_coord_precision
        BEFORE INSERT OR UPDATE OF coord, coord_precision_digits
        ON feature.features
        FOR EACH ROW
        EXECUTE FUNCTION feature.set_feature_coord_precision()
        """
    )
    op.create_check_constraint(
        "ck_features_coord_precision",
        "features",
        "("
        "coord IS NULL AND coord_precision_digits IS NULL"
        ") OR ("
        "coord IS NOT NULL AND coord_precision_digits BETWEEN 3 AND 8"
        ")",
        schema="feature",
    )
    op.execute(
        """
        CREATE INDEX idx_features_dedup_refresh_keyset
        ON feature.features (updated_at DESC, feature_id DESC)
        WHERE deleted_at IS NULL
          AND status = 'active'
          AND coord IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS feature.idx_features_dedup_refresh_keyset")
    op.drop_constraint(
        "ck_features_coord_precision",
        "features",
        schema="feature",
        type_="check",
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_features_coord_precision ON feature.features"
    )
    op.execute("DROP FUNCTION IF EXISTS feature.set_feature_coord_precision()")
    op.drop_column("features", "coord_precision_digits", schema="feature")
